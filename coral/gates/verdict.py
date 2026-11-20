"""Answers to gate visits: who may answer, which visit it is, and what the engine said.

A prompt's answer names a session and a prompt id; everything else comes from the
server: the run from the session's anchor binding, the visit from the run's row
holding that prompt id, and the actor from the caller's identity once it is
proven to be the run owner. The owner is checked on the run row before any
engine state is loaded. An answer through the runs API names the run, the gate
and the visit's token instead; its owner is checked on the run row the same way.
A visit that can no longer be answered is classified without the engine; a live
one is committed once through the bridge. Only a few answers are in flight at
once, in all and per user, so a flood of them cannot take the bridge's threads
from the drain and one user's answers cannot keep another's out. An answer is
admitted once its run and owner are known and before any engine state is loaded,
so nobody else's answers use up an owner's admissions, and a refused answer loads
nothing. Logs carry the run, the prompt or visit id and the reason, never a note or an
answer's content, and store errors are described without their statement's
parameters.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, TypeVar

from coral.alerts.types import LOCAL_USER_ID, is_owner, normalize_owner
from coral.bridge.commit import EngineSnapshot
from coral.bridge.executors import BridgeThreads, PoolClosed
from coral.bridge.messages import sanitize, strip_format_characters
from coral.bridge.service import EngineLoadFailed, GateAnswerResult
from coral.db.enum_codecs import SessionBindingRole
from coral.engine import types as engine
from coral.gates.ids import (
    GATE_ELICITATION_ID,
    MAX_GATE_NOTE_CHARS,
    find_visit,
    gate_node,
    gate_visit_id,
    is_binary_gate,
    live_visit,
    receipt_label,
    row_by_elicitation,
)
from coral.model.ids import anchor_session_id
from coral.model.ir import CompiledNode
from coral.omni.protocols import Viewer
from coral.queue.run_effects import describe_exception, raise_if_cancelling
from coral.stores.protocols import (
    UNFINISHED_RUN_STATUSES,
    CoralRun,
    GateVisitState,
    RunNotFound,
    RunStore,
)
from coral.stores.session_bindings import SessionBindingLookup

_logger = logging.getLogger(__name__)

# How long one answer may wait on the store, the bridge's threads and its commit.
ANSWER_TIMEOUT_S = 30.0
# Answers in flight at once in one process (half the bridge's smallest pool), and for
# one user (half of those), so one user's answers never hold every admission.
MAX_ANSWERS_IN_FLIGHT = 4
MAX_ANSWERS_PER_USER = 2

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
_NOTE_CHARACTERS_TEXT = "The note must not hold NUL or unpaired surrogate characters."
_CROWDED_TEXT = "Too many gate answers at once; try again."

_V = TypeVar("_V")


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


@dataclass(frozen=True)
class VisitAnswer:
    """
    An answer to one visit of a gate, posted through the runs API.

    :param token: The visit's engine token, as the run's detail lists it.
    :param outcome: The outcome chosen; one the gate does not have chooses none.
    :param viewer: The caller, built where the request was authenticated; it must own
        the run, checked on its row before the answer is admitted.
    """

    workspace_id: int
    run_id: str
    node_id: str
    token: str
    outcome: str
    note: str
    viewer: Viewer


@dataclass(frozen=True)
class VisitVerdict:
    """
    What an answer to a visit got.

    :param verdict: ``None`` when the run has no visit with that token at that gate.
    :param row: The visit's gate row, whose prompt the caller may withdraw.
    """

    verdict: GateVerdict | None
    row: GateVisitState | None = None


_ACCEPTED = GateVerdict(status="accepted")
_DUPLICATE = GateVerdict(status="duplicate", clear_pending=True)
_CROWDED = GateVerdict(status="refused", reason="run_busy", message=_CROWDED_TEXT)
# A caller's share of the admissions: its normalized owner id and account generation.
_CallerKey = tuple[str | None, str | None]


class _Admissions:
    """Answers admitted at once, at most so many in all and per caller; use on one loop."""

    def __init__(self, *, total: int, per_caller: int) -> None:
        self._total = total
        self._per_caller = per_caller
        self._admitted = 0
        self._by_caller: dict[_CallerKey, int] = {}

    @contextmanager
    def admit(self, viewer: Viewer) -> Iterator[bool]:
        """Whether ``viewer``'s answer is admitted; an admission is held for the block."""
        key = (normalize_owner(viewer.user_id), viewer.account_generation)
        held = self._by_caller.get(key, 0)
        if self._admitted >= self._total or held >= self._per_caller:
            yield False
            return
        self._admitted += 1
        self._by_caller[key] = held + 1
        try:
            yield True
        finally:
            self._admitted -= 1
            if held:
                self._by_caller[key] = held
            else:
                self._by_caller.pop(key, None)


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
        max_per_user: int = MAX_ANSWERS_PER_USER,
    ) -> None:
        """
        :param threads: Runs the store reads and bridge calls.
        :param timeout_s: The answer's whole wait; past it the answer is refused
            ``run_busy``, and a commit already under way still lands, so a retry is
            then a duplicate.
        :param max_in_flight: Answers taken at once; one more is refused ``run_busy``
            at once, so the caller retries.
        :param max_per_user: Answers of one user (and account generation) taken at once.
        """
        self._threads = threads
        self._bindings = bindings
        self._runs = run_store
        self._timeout_s = timeout_s
        self._admissions = _Admissions(total=max_in_flight, per_caller=max_per_user)

    async def answer(self, answer: GateAnswer) -> GateVerdict:
        """
        Check the anchor, the owner and the visit, then commit the answer once.

        Anything that goes wrong on the way (a timeout, a closing pool, a store error)
        is refused ``run_busy``: nothing was committed, or a retry is a duplicate.
        """
        return await self._bounded(
            answer.elicitation_id, self._answer(answer), gate_refusal("run_busy")
        )

    async def answer_visit(self, answer: VisitAnswer) -> VisitVerdict:
        """
        Answer the run's visit ``answer.token`` of the gate ``answer.node_id`` once.

        The owner is checked on the run row, then the answer is admitted, and only then
        is the run loaded, so another user's answer and one past the caller's share
        load nothing. The verdicts are the prompt's, decided in the same order: a visit
        that can no longer be answered says so before an outcome the gate lacks is
        refused. Errors on the way are refused ``run_busy``, as :meth:`answer` refuses
        them.
        """
        return await self._bounded(
            answer.run_id, self._answer_visit(answer), VisitVerdict(gate_refusal("run_busy"))
        )

    async def _bounded(self, subject: str, call: Awaitable[_V], busy: _V) -> _V:
        """``call`` within the answer's timeout; ``busy`` when anything goes wrong."""
        try:
            async with asyncio.timeout(self._timeout_s):
                return await call
        except (TimeoutError, PoolClosed):
            _logger.warning("Coral could not answer gate %s in time; refused as busy", subject)
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged
            raise_if_cancelling(exc)
            # A statement error's text holds its parameters, the note among them.
            _logger.error(
                "Coral could not answer gate %s; refused as busy: %s",
                subject,
                describe_exception(exc),
            )
        return busy

    @staticmethod
    def _crowded(subject: str) -> GateVerdict:
        """The refusal of an answer past the admissions; the caller retries."""
        _logger.debug("Coral refused an answer to gate %s: too many answers", subject)
        return _CROWDED

    async def _unloadable(self, workspace_id: int, run_id: str) -> GateVerdict:
        """
        The refusal of an answer to a run that cannot be loaded: an ended run's gates
        no longer wait; an unfinished one is paused, as the failed load paused it.
        """
        run = await self._threads.run(self._runs.get_run, run_id, workspace_id=workspace_id)
        if run is None or run.status not in UNFINISHED_RUN_STATUSES:
            return gate_refusal("no_longer_waiting", clear_pending=True)
        return gate_refusal("run_paused")

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
            return self._not_permitted(elicitation_id, run_id, answer.viewer)
        with self._admissions.admit(answer.viewer) as admitted:
            if not admitted:
                return self._crowded(elicitation_id)
            return await self._answer_prompt(answer, run_id)

    async def _answer_prompt(self, answer: GateAnswer, run_id: str) -> GateVerdict:
        workspace_id, elicitation_id = answer.workspace_id, answer.elicitation_id
        gone = gate_refusal("no_longer_waiting", clear_pending=True)
        try:
            snapshot = await self._threads.run(
                self._threads.bridge.load, workspace_id=workspace_id, run_id=run_id
            )
        except EngineLoadFailed:
            return await self._unloadable(workspace_id, run_id)
        except RunNotFound:
            return gone
        row = row_by_elicitation(snapshot.store.gate_visits, elicitation_id)
        visit = None if row is None else find_visit(snapshot.state, run_id, row.id)
        if visit is None:
            return gone
        node = gate_node(snapshot.graph, visit)
        return await self._conclude(
            snapshot,
            visit,
            node,
            label=answer_label(node, answer.action, answer.content),
            note=answer_note(answer.content),
            viewer=answer.viewer,
            subject=elicitation_id,
        )

    async def _answer_visit(self, answer: VisitAnswer) -> VisitVerdict:
        workspace_id, run_id = answer.workspace_id, answer.run_id
        visit_id = gate_visit_id(run_id, answer.token)
        run = await self._threads.run(self._runs.get_run, run_id, workspace_id=workspace_id)
        if run is None:
            return VisitVerdict(None)
        if not _is_owner(run, answer.viewer):
            return VisitVerdict(self._not_permitted(visit_id, run_id, answer.viewer))
        with self._admissions.admit(answer.viewer) as admitted:
            if not admitted:
                return VisitVerdict(self._crowded(visit_id))
            return await self._visit_verdict(answer, visit_id)

    async def _visit_verdict(self, answer: VisitAnswer, visit_id: str) -> VisitVerdict:
        workspace_id, run_id = answer.workspace_id, answer.run_id
        try:
            snapshot = await self._threads.run(
                self._threads.bridge.load, workspace_id=workspace_id, run_id=run_id
            )
        except EngineLoadFailed:
            return VisitVerdict(await self._unloadable(workspace_id, run_id))
        except RunNotFound:
            return VisitVerdict(None)
        # The owner's account generation may have moved since the row was read.
        if not _is_owner(snapshot.store.run, answer.viewer):
            return VisitVerdict(self._not_permitted(visit_id, run_id, answer.viewer))
        visit = find_visit(snapshot.state, run_id, visit_id)
        node = None if visit is None else gate_node(snapshot.graph, visit)
        if visit is None or node is None or node.id != answer.node_id:
            return VisitVerdict(None)
        row = next((item for item in snapshot.store.gate_visits if item.id == visit_id), None)
        verdict = await self._conclude(
            snapshot,
            visit,
            node,
            label=answer.outcome if answer.outcome in node.outcomes else None,
            note=answer_note({"note": answer.note}),
            viewer=answer.viewer,
            subject=visit_id,
        )
        return VisitVerdict(verdict, row)

    async def _conclude(
        self,
        snapshot: EngineSnapshot,
        visit: engine.GateVisit,
        node: CompiledNode | None,
        *,
        label: str | None,
        note: str | None,
        viewer: Viewer,
        subject: str,
    ) -> GateVerdict:
        """
        Classify a visit that can no longer be answered, else commit ``label`` once.

        :param label: The outcome the answer chose, ``None`` when it chose none.
        :param note: The answer's note, ``None`` when it is not text a row can hold.
        :param subject: The prompt or visit id the logs name.
        """
        run_id = snapshot.store.run_id
        outcomes = tuple(node.outcomes) if node is not None else ()
        if not live_visit(snapshot.state, visit):
            verdict = closed_visit_verdict(
                visit, receipt_label(snapshot.state, visit.token), label
            )
            return self._logged(verdict, run_id, subject)
        if label is None:
            return gate_refusal("invalid_answer", message=_choose(outcomes))
        if note is None:
            return gate_refusal("invalid_answer", message=_NOTE_TEXT)
        if sanitize(note) != note:
            return gate_refusal("invalid_answer", message=_NOTE_CHARACTERS_TEXT)
        try:
            result = await self._threads.run(
                self._threads.bridge.answer_gate,
                workspace_id=snapshot.store.workspace_id,
                run_id=run_id,
                token=visit.token,
                label=label,
                note=note,
                actor=viewer.user_id or LOCAL_USER_ID,
            )
        except EngineLoadFailed:
            return await self._unloadable(snapshot.store.workspace_id, run_id)
        except RunNotFound:
            return gate_refusal("no_longer_waiting", clear_pending=True)
        return self._logged(result_verdict(result, label, outcomes), run_id, subject)

    @staticmethod
    def _not_permitted(subject: str, run_id: str, viewer: Viewer) -> GateVerdict:
        _logger.info(
            "Coral refused an answer to gate %s of run %s from %s: not the run owner",
            subject,
            run_id,
            viewer.user_id or LOCAL_USER_ID,
        )
        return gate_refusal("not_permitted")

    @staticmethod
    def _logged(verdict: GateVerdict, run_id: str, subject: str) -> GateVerdict:
        _logger.info(
            "Gate %s of run %s answered: %s", subject, run_id, verdict.reason or verdict.status
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
    return is_owner(run.user_id, run.account_generation, viewer)


def _choose(outcomes: Sequence[str]) -> str:
    if not outcomes:
        return _TEXT["invalid_answer"]
    return f"Choose one of: {', '.join(strip_format_characters(item) for item in outcomes)}."


__all__ = [
    "ANSWER_TIMEOUT_S",
    "MAX_ANSWERS_IN_FLIGHT",
    "MAX_ANSWERS_PER_USER",
    "GateAnswer",
    "GateAnswers",
    "GateRefusal",
    "GateVerdict",
    "VisitAnswer",
    "VisitVerdict",
    "answer_label",
    "answer_note",
    "closed_visit_verdict",
    "gate_refusal",
    "result_verdict",
]
