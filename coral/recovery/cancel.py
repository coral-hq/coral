"""Store-only cancel: a run whose engine state cannot be loaded ends on its row alone.

Such a run cannot take the engine's ``CancelRun``, so one commit on its row cancels
it: a ``RUN_FINISHED`` entry saying what was done, the run-end alerts, its open gate
rows cancelled, and, when its rows decode, one ``cancel_sessions`` row per step
session still open. Those rows name no engine kind and no bridge item, so their
executor runs without the engine and nothing is fed back. When the rows do not
decode no session can be named, and a step whose create has not finished names none
yet (the session it makes stays idle): the run guard refuses those sessions' tool
calls, and the alert and the entry say they may still run. A cancelled gate row's
prompt goes with this process's withdraw and every process's sweep, which reads
``OPEN`` rows only. If the engine loads again later, its next commit cancels it
first (``EngineBridge.commit_inputs``).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from coral.alerts.rules import UnstoppedSessions, run_end_alerts
from coral.bridge.config import MAX_ACTOR_REF_CHARS, MAX_LIVE_SLOTS
from coral.bridge.gate_rows import gate_visit_draft
from coral.bridge.service import LOAD_FAILED_DETAIL
from coral.db.enum_codecs import ActorKind, GateVisitStatus, LogKind, RunStatus, SlotStatus
from coral.model.ids import anchor_session_id
from coral.omni.protocols import GatePublisher
from coral.queue.run_effects import describe_exception, raise_if_cancelling
from coral.slots.executors import CANCEL_SESSIONS
from coral.stores.protocols import (
    STORED_TEXT_ERRORS,
    UNFINISHED_RUN_STATUSES,
    CommitOutcome,
    CoralRun,
    GateVisitState,
    LogEntryDraft,
    RunNotFound,
    RunStore,
    Transition,
    WorkItemDraft,
)
from coral.stores.run_commit import commit_on_run_row

_logger = logging.getLogger(__name__)

# Every slot a run can have live, and its orchestrator.
MAX_STORE_CANCEL_SESSIONS = MAX_LIVE_SLOTS + 1


@dataclass(frozen=True)
class StoreCancel:
    """
    What a store-only cancel committed.

    :param outcome: Not applied when the run had finished already: nothing was written.
    :param sessions_queued: How many ``cancel_sessions`` rows were queued.
    :param sessions_unreachable: A step session may be left running: the run's rows
        did not decode, more were open than one cancel queues, or a step's session
        was still being created.
    :param gate_rows: The gate rows cancelled, as they were; the caller withdraws
        their prompts from its own process.
    """

    outcome: CommitOutcome
    sessions_queued: int = 0
    sessions_unreachable: bool = False
    gate_rows: tuple[GateVisitState, ...] = ()


@dataclass(frozen=True)
class _Found:
    sessions: tuple[str, ...]
    unstopped: UnstoppedSessions | None
    gates: tuple[GateVisitState, ...]


def cancel_run_row(
    run_store: RunStore,
    *,
    workspace_id: int,
    run_id: str,
    actor: str,
    now_us: int,
    lock_timeout_s: float | None = None,
) -> StoreCancel:
    """
    Cancel an unfinished run on its row alone; a finished run is left as it is.

    Each attempt reads the slot and gate rows after the run row it commits against,
    so a commit landing in between makes the next attempt read them again. A read
    that does not decode leaves its part out instead of failing the cancel.

    :param actor: Who cancels the run, recorded on the ``RUN_FINISHED`` entry.
    :param now_us: The cancel's time, in microseconds.
    :raises RunNotFound: when the workspace has no such run.
    :raises RunContended: when other commits kept winning.
    """
    now_s = now_us // 1_000_000
    found: list[_Found] = []

    def reduce(run: CoralRun) -> Transition:
        found.clear()
        if run.status not in UNFINISHED_RUN_STATUSES:
            return Transition.empty()
        sessions, unstopped = _open_sessions(run_store, run)
        found.append(_Found(sessions, unstopped, _open_gates(run_store, run)))
        return _cancelled(run, found[0], actor=actor, now_s=now_s, now_us=now_us)

    outcome = commit_on_run_row(
        run_store=run_store,
        workspace_id=workspace_id,
        run_id=run_id,
        reduce_fn=reduce,
        now=now_s,
        lock_timeout_s=lock_timeout_s,
    )
    if not outcome.applied or not found:
        return StoreCancel(outcome=outcome)
    (done,) = found
    if done.unstopped is not None:
        _logger.warning(
            "Coral cancelled run %s on its row; %s of its step sessions may still run",
            run_id,
            done.unstopped,
        )
    else:
        _logger.info(
            "Coral cancelled run %s on its row: %d session stops queued, %d gate rows closed",
            run_id,
            len(done.sessions),
            len(done.gates),
        )
    return StoreCancel(
        outcome=outcome,
        sessions_queued=len(done.sessions),
        sessions_unreachable=done.unstopped is not None,
        gate_rows=done.gates,
    )


async def withdraw_local_prompts(publisher: GatePublisher, rows: Sequence[GateVisitState]) -> int:
    """
    Withdraw the prompts of cancelled gate rows from this process, best effort.

    Another process's copy goes with its sweep. Call it in the run's workspace scope.

    :returns: How many of the prompts were pending here.
    """
    withdrawn = 0
    for row in rows:
        if row.elicitation_id is None:
            continue
        try:
            if await publisher.withdraw(
                session_id=anchor_session_id(row.workspace_id, row.run_id),
                elicitation_id=row.elicitation_id,
            ):
                withdrawn += 1
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- the sweep retries
            raise_if_cancelling(exc)
            _logger.warning(
                "Coral could not withdraw a gate prompt of cancelled run %s; the sweep will: %s",
                row.run_id,
                describe_exception(exc),
            )
    return withdrawn


def _open_sessions(
    run_store: RunStore, run: CoralRun
) -> tuple[tuple[str, ...], UnstoppedSessions | None]:
    """
    The step sessions to stop, at most :data:`MAX_STORE_CANCEL_SESSIONS`, and which
    may be left running.

    Slots that are not closed and name a session, and the orchestrator the run names
    (a cancel of a session never bound counts as done). None when the rows do not
    decode or are missing: the cancel executor could not read them either. A slot
    not closed that names no session yet has a create that may still make one.
    """
    try:
        rows, _version = run_store.load_run_state(run.id, workspace_id=run.workspace_id)
    except (*STORED_TEXT_ERRORS, RunNotFound) as exc:
        _logger.warning(
            "Coral cannot read the slots of run %s to stop their sessions: %s",
            run.id,
            describe_exception(exc),
        )
        return (), "all"
    open_slots = [slot for slot in rows.agent_slots if slot.status != int(SlotStatus.CLOSED)]
    named = [] if run.orchestrator_session_id is None else [run.orchestrator_session_id]
    named.extend(slot.session_id for slot in open_slots if slot.session_id is not None)
    sessions = tuple(dict.fromkeys(named))
    creating = any(slot.session_id is None for slot in open_slots)
    left = len(sessions) > MAX_STORE_CANCEL_SESSIONS or creating
    return sessions[:MAX_STORE_CANCEL_SESSIONS], "some" if left else None


def _open_gates(run_store: RunStore, run: CoralRun) -> tuple[GateVisitState, ...]:
    """The run's open gate rows; none when they do not decode."""
    try:
        return tuple(run_store.list_open_gates(run.id, workspace_id=run.workspace_id))
    except STORED_TEXT_ERRORS as exc:
        _logger.warning(
            "Coral cannot read the open gates of run %s to close them: %s",
            run.id,
            describe_exception(exc),
        )
        return ()


def _cancelled(run: CoralRun, found: _Found, *, actor: str, now_s: int, now_us: int) -> Transition:
    body = {
        "kind": "cancel_run",
        "status": "cancelled",
        "store_only": True,
        "cause": LOAD_FAILED_DETAIL,
        "sessions_queued": len(found.sessions),
        "sessions_unreachable": found.unstopped is not None,
        "gates_closed": len(found.gates),
    }
    entry = LogEntryDraft(
        kind=int(LogKind.RUN_FINISHED),
        actor_kind=int(ActorKind.USER),
        actor_ref=actor[:MAX_ACTOR_REF_CHARS],
        body=json.dumps(body, sort_keys=True),
        created_at_us=now_us,
    )
    alerts = run_end_alerts(run, int(RunStatus.CANCELLED), unstopped=found.unstopped)
    return Transition(
        status=int(RunStatus.CANCELLED),
        clear_pause_reason=True,
        finished_at=now_s,
        gate_visits=tuple(
            dataclasses.replace(
                gate_visit_draft(row), status=int(GateVisitStatus.CANCELLED), resolved_at=now_s
            )
            for row in found.gates
        ),
        alert_raises=alerts.raises,
        alert_resolutions=alerts.resolutions,
        logs=(entry,),
        outbox_work=tuple(
            _session_cancel(run.id, session_id, now_s) for session_id in found.sessions
        ),
    )


def _session_cancel(run_id: str, session_id: str, now_s: int) -> WorkItemDraft:
    """A ``cancel_sessions`` row for one session; seq 0 is no engine entry's."""
    key = f"{run_id}:0:{CANCEL_SESSIONS}:{session_id}"
    payload = {
        "effect_type": CANCEL_SESSIONS,
        "effect_key": key,
        "session_id": session_id,
        "closed_label": True,
    }
    return WorkItemDraft.effect(
        run_id=run_id, idempotency_key=key, payload=payload, available_at=now_s
    )


__all__ = [
    "MAX_STORE_CANCEL_SESSIONS",
    "StoreCancel",
    "cancel_run_row",
    "withdraw_local_prompts",
]
