"""Gates on Omnigent: prompts published on anchors, tracked per process, answered by the owner.

The publisher shows and drops gate prompts through the request-free elicitation
seam (S6a). The tracker observes every prompt this process publishes (S5) so
the sweep can find stale ones. The verdict handler (S6b) builds the caller's
:class:`Viewer` in the request's own task, then hands the answer to
:class:`~coral.gates.verdict.GateAnswers`. The admission flag tells the mutation
guard that the handler is registered, so a run's anchor takes approvals.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from coral.gates.ids import GATE_ELICITATION_ID
from coral.gates.verdict import GateAnswer, GateAnswers, GateVerdict, gate_refusal
from coral.limits import WarnOnce
from coral.omni.protocols import TrackedPrompt
from coral.omni.server.access import viewer_for
from omnigent.db.db_models import current_workspace_id
from omnigent.runtime import pending_elicitations
from omnigent.server import elicitation_hooks
from omnigent.server.auth import AuthProvider
from omnigent.server.elicitation_hooks import (
    ElicitationVerdict,
    VerdictDecision,
    VerdictHandler,
)

_logger = logging.getLogger(__name__)

# Prompts one process tracks for the sweep; past this the oldest is dropped.
MAX_TRACKED_PROMPTS = 10_000
_REQUEST = "response.elicitation_request"
_RESOLVED = "response.elicitation_resolved"
_STOPPED_TEXT = "Coral is not taking gate answers right now; try again."
# How long the lifespan's exit lets answers admitted before it reach the handler.
ANSWER_GRACE_S = 0.05


class OmnigentGatePublisher:
    """``GatePublisher`` over the S6a seam; called in the session's workspace scope."""

    async def publish(
        self, *, session_id: str, elicitation_id: str, params: Mapping[str, Any]
    ) -> None:
        await elicitation_hooks.publish_form_elicitation(
            session_id, params, elicitation_id=elicitation_id
        )

    async def withdraw(self, *, session_id: str, elicitation_id: str) -> bool:
        return elicitation_hooks.withdraw_elicitation(session_id, elicitation_id)


class LocalGatePrompts:
    """
    The gate prompts this process saw published and not resolved: an S5 observer.

    Tracks a ``coral_gate_*`` prompt published with no ``target_session_id``
    (mirrors of a child's prompt are not this process's to sweep), keyed by the
    publisher's workspace, and forgets it on its resolved event. A prompt
    dropped without an event stays tracked until the sweep finds it no longer
    pending. Thread-safe and O(1) per event.
    """

    def __init__(self, *, limit: int = MAX_TRACKED_PROMPTS) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._prompts: OrderedDict[TrackedPrompt, None] = OrderedDict()
        self._full = WarnOnce()

    def observe(self, conversation_id: str, event: dict[str, Any]) -> None:
        """The S5 observer; reads the event and never changes it."""
        elicitation_id = event.get("elicitation_id")
        if not isinstance(elicitation_id, str) or not GATE_ELICITATION_ID.fullmatch(
            elicitation_id
        ):
            return
        kind = event.get("type")
        prompt = TrackedPrompt(current_workspace_id(), conversation_id, elicitation_id)
        if kind == _RESOLVED:
            with self._lock:
                self._prompts.pop(prompt, None)
            return
        params = event.get("params")
        if kind != _REQUEST or not isinstance(params, Mapping):
            return
        if params.get("target_session_id") is not None:
            return
        with self._lock:
            self._prompts[prompt] = None
            dropped = len(self._prompts) > self._limit
            if dropped:
                self._prompts.popitem(last=False)
        if dropped and self._full.first():
            _logger.warning(
                "Coral tracks at most %d gate prompts per process; the oldest are no longer swept",
                self._limit,
            )

    def tracked(self) -> list[TrackedPrompt]:
        with self._lock:
            return list(self._prompts)

    def forget(self, prompt: TrackedPrompt) -> None:
        with self._lock:
            self._prompts.pop(prompt, None)

    def is_pending(self, prompt: TrackedPrompt) -> bool:
        """Whether the prompt is still pending here; call in its workspace's scope."""
        found = pending_elicitations.lookup(
            prompt.elicitation_id, conversation_id=prompt.session_id
        )
        return found is not None


class GateAnswering:
    """Whether Coral's gate verdict handler is registered: the guard's admission flag."""

    def __init__(self) -> None:
        self._enabled = False

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def __call__(self) -> bool:
        return self._enabled


def gate_verdict_handler(
    answers: GateAnswers, auth_provider: AuthProvider | None, answering: GateAnswering
) -> VerdictHandler:
    """
    The S6b handler for gate prompts.

    It runs in the answering request's task, so the caller's Viewer is built there
    from ``resolved_by`` and the request's account authority, before any thread hop.
    A caller with no usable identity is refused ``not_permitted`` without an answer.
    While ``answering`` is off (the lifespan is starting or stopping) every answer is
    refused ``run_busy``, so one admitted just before exit is retried, not dropped.
    """

    async def handle(verdict: ElicitationVerdict) -> VerdictDecision:
        if not answering():
            return _decision(gate_refusal("run_busy", message=_STOPPED_TEXT))
        viewer = viewer_for(verdict.resolved_by, auth_provider)
        if viewer is None:
            _logger.info(
                "Coral refused an answer to gate prompt %s: the caller has no usable identity",
                verdict.elicitation_id,
            )
            return _decision(gate_refusal("not_permitted"))
        result = verdict.result
        gate = await answers.answer(
            GateAnswer(
                workspace_id=current_workspace_id(),
                session_id=verdict.session_id,
                elicitation_id=verdict.elicitation_id,
                action=result.action,
                content=dict(result.content or {}),
                viewer=viewer,
            )
        )
        return _decision(gate)

    return handle


def _decision(verdict: GateVerdict) -> VerdictDecision:
    if verdict.status == "accepted":
        return VerdictDecision(accepted=True)
    if verdict.status == "duplicate":
        return VerdictDecision(accepted=True, duplicate=True, clear_pending=verdict.clear_pending)
    return VerdictDecision(
        accepted=False,
        forbidden=verdict.reason == "not_permitted",
        clear_pending=verdict.clear_pending,
        reason=verdict.reason,
        message=verdict.message,
    )


__all__ = [
    "ANSWER_GRACE_S",
    "MAX_TRACKED_PROMPTS",
    "GateAnswering",
    "LocalGatePrompts",
    "OmnigentGatePublisher",
    "gate_verdict_handler",
]
