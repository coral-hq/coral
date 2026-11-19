"""Answers to gate prompts: who may answer, which visit it is, and what the engine said.

An answer names a session and a prompt id; everything else comes from the
server: the run from the session's anchor binding, the visit from the run's row
holding that prompt id, and the actor from the caller's identity once it is
proven to be the run owner. The owner is checked on the run row before any
engine state is loaded. A visit that can no longer be answered is classified
without the engine; a live one is committed once through the bridge. Only a few
answers are in flight at once, so a flood of them cannot take the bridge's
threads from the drain. Logs carry the run, the prompt id and the reason, never
a note or an answer's content, and store errors are described without their
statement's parameters.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from coral.alerts.types import LOCAL_USER_ID, generation_matches, normalize_owner
from coral.bridge.executors import BridgeThreads, PoolClosed
from coral.bridge.messages import strip_format_characters
from coral.bridge.service import EngineLoadFailed, GateAnswerResult
from coral.db.enum_codecs import SessionBindingRole
from coral.engine import types as engine
from coral.gates.ids import (
    GATE_ELICITATION_ID,
    MAX_GATE_NOTE_CHARS,
    find_visit,
    gate_node,
    is_binary_gate,
    live_visit,
    receipt_label,
    row_by_elicitation,
)
from coral.model.ids import anchor_session_id
from coral.model.ir import CompiledNode
from coral.omni.protocols import Viewer
from coral.queue.run_effects import describe_exception, raise_if_cancelling
from coral.stores.protocols import CoralRun, RunNotFound, RunStore
from coral.stores.session_bindings import SessionBindingLookup

_logger = logging.getLogger(__name__)

# How long one answer may wait on the store, the bridge's threads and its commit.
ANSWER_TIMEOUT_S = 30.0
# Answers in flight at once in one process; half the bridge's smallest pool.
MAX_ANSWERS_IN_FLIGHT = 4

GateRefusal = Literal[
    "not_permitted",
    "stale_visit",
    "already_answered",
    "no_longer_waiting",
    "run_paused",
    "invalid_answer",
    "run_busy",
]
_TEXT: dict[GateRefusal, str] = {
    "not_permitted": "Only the run owner can answer this gate.",
    "stale_visit": "This gate was asked again; answer the latest one.",
    "already_answered": "This gate was already answered.",
    "no_longer_waiting": "This gate is no longer waiting.",
    "run_paused": "The run is paused; resume it, then answer.",
    "invalid_answer": "The answer is not one this gate takes.",
    "run_busy": "The run is busy; try again.",
}
_NOTE_TEXT = f"The note must be text of at most {MAX_GATE_NOTE_CHARS:,} characters."
_CROWDED_TEXT = "Too many gate answers at once; try again."


@dataclass(frozen=True)
class GateAnswer:
    """
    One answer posted to a gate prompt.

    :param session_id: The session the answer was posted to.
    :param content: The form's content; ``{}`` when the answer carried none.
    :param viewer: The caller, built where the request was authenticated.
    """

    workspace_id: int
    session_id: str
    elicitation_id: str
    action: Literal["accept", "decline", "cancel"]
    content: Mapping[str, object]
    viewer: Viewer


@dataclass(frozen=True)
class GateVerdict:
    """
    What an answer got.

    :param status: ``duplicate``: the same answer was taken earlier.
    :param reason: For a refusal, why; ``not_permitted`` is because of who answered.
    :param message: For a refusal, the text the caller is shown.
    :param clear_pending: The visit can no longer be answered, so a prompt still
        pending for it on this session should be dropped.
    """

    status: Literal["accepted", "duplicate", "refused"]
    reason: GateRefusal | None = None
    message: str | None = None
    clear_pending: bool = False


def gate_refusal(
    reason: GateRefusal, *, message: str | None = None, clear_pending: bool = False
) -> GateVerdict:
    """A refusal with the reason's own text unless ``message`` is given."""
    return GateVerdict(
        status="refused",
        reason=reason,
        message=message or _TEXT[reason],
        clear_pending=clear_pending,
    )


_ACCEPTED = GateVerdict(status="accepted")
_DUPLICATE = GateVerdict(status="duplicate", clear_pending=True)


class GateAnswers:
    """Takes answers to gate prompts for the run owner; safe to share between requests."""

    def __init__(
        self,
        *,
        threads: BridgeThreads,
        bindings: SessionBindingLookup,
        run_store: RunStore,
        timeout_s: float = ANSWER_TIMEOUT_S,
        max_in_flight: int = MAX_ANSWERS_IN_FLIGHT,
    ) -> None:
        """
        :param threads: Runs the store reads and bridge calls.
        :param timeout_s: The answer's whole wait; past it the answer is refused
            ``run_busy``, and a commit already under way still lands, so a retry is
            then a duplicate.
        :param max_in_flight: Answers taken at once; one more is refused ``run_busy``
            at once, so the caller retries.
        """
        self._threads = threads
        self._bindings = bindings
        self._runs = run_store
        self._timeout_s = timeout_s
        self._in_flight = asyncio.Semaphore(max_in_flight)

    async def answer(self, answer: GateAnswer) -> GateVerdict:
        """
        Check the anchor, the owner and the visit, then commit the answer once.

        Anything that goes wrong on the way (a timeout, a closing pool, a store error)
        is refused ``run_busy``: nothing was committed, or a retry is a duplicate.
        """
        if self._in_flight.locked():
            _logger.debug("Coral refused gate prompt %s: too many answers", answer.elicitation_id)
            return gate_refusal("run_busy", message=_CROWDED_TEXT)
        async with self._in_flight:
            try:
                async with asyncio.timeout(self._timeout_s):
                    return await self._answer(answer)
            except (TimeoutError, PoolClosed):
                _logger.warning(
                    "Coral could not answer gate prompt %s in time; refused as busy",
                    answer.elicitation_id,
                )
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged
                raise_if_cancelling(exc)
                # A statement error's text holds its parameters, the note among them.
                _logger.error(
                    "Coral could not answer gate prompt %s; refused as busy: %s",
                    answer.elicitation_id,
                    describe_exception(exc),
                )
        return gate_refusal("run_busy")

    async def _answer(self, answer: GateAnswer) -> GateVerdict:
        workspace_id, elicitation_id = answer.workspace_id, answer.elicitation_id
        gone = gate_refusal("no_longer_waiting", clear_pending=True)
        if not GATE_ELICITATION_ID.fullmatch(elicitation_id):
            return gone
        binding = await self._threads.run(
            self._bindings.find_by_session, workspace_id, answer.session_id
        )
        if (
            binding is None
            or binding.role != SessionBindingRole.ANCHOR
            or anchor_session_id(workspace_id, binding.run_id) != answer.session_id
        ):
            return gone
        run_id = binding.run_id
        run = await self._threads.run(self._runs.get_run, run_id, workspace_id=workspace_id)
        if run is None:
            return gone
        if not _is_owner(run, answer.viewer):
            _logger.info(
                "Coral refused an answer to gate prompt %s of run %s from %s: not the run owner",
                elicitation_id,
                run_id,
                answer.viewer.user_id or LOCAL_USER_ID,
            )
            return gate_refusal("not_permitted")
        bridge = self._threads.bridge
        try:
            snapshot = await self._threads.run(
                bridge.load, workspace_id=workspace_id, run_id=run_id
            )
        except EngineLoadFailed:
            return gate_refusal("run_paused")
        except RunNotFound:
            return gone
        row = row_by_elicitation(snapshot.store.gate_visits, elicitation_id)
        visit = None if row is None else find_visit(snapshot.state, run_id, row.id)
        if visit is None:
            return gone
        node = gate_node(snapshot.graph, visit)
        outcomes = tuple(node.outcomes) if node is not None else ()
        label = answer_label(node, answer.action, answer.content)
        if not live_visit(snapshot.state, visit):
            verdict = closed_visit_verdict(
                visit, receipt_label(snapshot.state, visit.token), label
            )
            return self._logged(verdict, run_id, elicitation_id)
        if label is None:
            return gate_refusal("invalid_answer", message=_choose(outcomes))
        note = answer_note(answer.content)
        if note is None:
            return gate_refusal("invalid_answer", message=_NOTE_TEXT)
        try:
            result = await self._threads.run(
                bridge.answer_gate,
                workspace_id=workspace_id,
                run_id=run_id,
                token=visit.token,
                label=label,
                note=note,
                actor=answer.viewer.user_id or LOCAL_USER_ID,
            )
        except EngineLoadFailed:
            return gate_refusal("run_paused")
        except RunNotFound:
            return gone
        return self._logged(result_verdict(result, label, outcomes), run_id, elicitation_id)

    @staticmethod
    def _logged(verdict: GateVerdict, run_id: str, elicitation_id: str) -> GateVerdict:
        _logger.info(
            "Gate prompt %s of run %s answered: %s",
            elicitation_id,
            run_id,
            verdict.reason or verdict.status,
        )
        return verdict


def answer_label(
    node: CompiledNode | None, action: str, content: Mapping[str, object]
) -> str | None:
    """
    The gate outcome an answer chooses, or ``None`` when it chooses none.

    ``accept`` names its ``decision``; without one it approves a binary gate.
    ``decline`` rejects a gate that has a ``reject`` outcome. ``cancel`` chooses nothing.
    """
    if node is None:
        return None
    outcomes = tuple(node.outcomes)
    if action == "accept":
        decision = content.get("decision")
        if decision is None:
            return "approve" if is_binary_gate(node) else None
        return decision if isinstance(decision, str) and decision in outcomes else None
    if action == "decline" and "reject" in outcomes:
        return "reject"
    return None


def answer_note(content: Mapping[str, object]) -> str | None:
    """The answer's note (``""`` when absent), or ``None`` when it is not text a row can hold."""
    note = content.get("note")
    if note is None:
        return ""
    if not isinstance(note, str) or len(note) > MAX_GATE_NOTE_CHARS:
        return None
    return note


def closed_visit_verdict(
    visit: engine.GateVisit, answered: str | None, label: str | None
) -> GateVerdict:
    """
    What an answer to a visit that can no longer be answered gets.

    :param answered: The label the visit's receipt records, if it was answered.
    :param label: The label this answer chose, if any.
    """
    if answered is not None:
        return _answered(answered, label)
    if visit.status == "superseded":
        return gate_refusal("stale_visit", clear_pending=True)
    return gate_refusal("no_longer_waiting", clear_pending=True)


def result_verdict(result: GateAnswerResult, label: str, outcomes: Sequence[str]) -> GateVerdict:
    """
    What the bridge's commit of ``label`` means for the caller.

    A refusal that reports how the visit was answered, whatever its code, is a
    duplicate of that answer or ``already_answered``.
    """
    if result.outcome == "accepted":
        return _ACCEPTED
    if result.outcome == "duplicate":
        return _DUPLICATE
    code = result.code
    if code == "run.contended":
        return gate_refusal("run_busy")
    if code == "tool.illegal":
        return gate_refusal("invalid_answer", message=_choose(result.allowed or outcomes))
    if code == "invalid_answer":
        return gate_refusal("invalid_answer", message=_NOTE_TEXT)
    if result.answered_label is not None:
        return _answered(result.answered_label, label)
    if code == "gate.stale":
        return gate_refusal("stale_visit", clear_pending=True)
    if code == "rejected":
        return gate_refusal("already_answered", clear_pending=True)
    if code in ("run_paused", "unbuildable"):
        return gate_refusal("run_paused")
    if code not in ("run_cancelled", "run_terminal"):
        _logger.warning("Coral got an unexpected gate answer refusal %r", code)
    return gate_refusal("no_longer_waiting", clear_pending=True)


def _answered(answered: str, label: str | None) -> GateVerdict:
    if answered == label:
        return _DUPLICATE
    shown = strip_format_characters(answered)
    return gate_refusal(
        "already_answered", message=f"Already answered: {shown}.", clear_pending=True
    )


def _is_owner(run: CoralRun, viewer: Viewer) -> bool:
    """The caller is the run's owner, under the generation the run recorded, if any."""
    return normalize_owner(run.user_id) == normalize_owner(viewer.user_id) and (
        generation_matches(run.account_generation, viewer)
    )


def _choose(outcomes: Sequence[str]) -> str:
    if not outcomes:
        return _TEXT["invalid_answer"]
    return f"Choose one of: {', '.join(strip_format_characters(item) for item in outcomes)}."


__all__ = [
    "ANSWER_TIMEOUT_S",
    "MAX_ANSWERS_IN_FLIGHT",
    "GateAnswer",
    "GateAnswers",
    "GateRefusal",
    "GateVerdict",
    "answer_label",
    "answer_note",
    "closed_visit_verdict",
    "gate_refusal",
    "result_verdict",
]
