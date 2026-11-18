"""The run's orchestrator: created for its first open decision, asked, reminded, re-asked.

The commit that opens a run's first decision also names the orchestrator session on
the run row and queues its create and the decision's request, so the session and its
first question appear together or not at all. A later decision only queues a request.
A watchdog ``notify`` on an open decision of a running run becomes a reminder, and
every return to running asks again about each decision still open. A failed,
archived or deleted orchestrator pauses the run while a decision waits on it; the
resume asks again. Only generation 1 exists here: replacing an orchestrator, and
keys scoped to its generation, belong to the restart ladder.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from coral.bridge.keys import (
    decision_request_key,
    decision_rerequest_key,
    effect_work_id,
    orchestrator_effect_key,
)
from coral.bridge.mapping import MapContext, decision_message_draft, orchestrator_create_draft
from coral.bridge.messages import DecisionMessage
from coral.engine import types as engine
from coral.engine.classify import classify_failure
from coral.engine.facts import TurnSnapshot
from coral.model.ids import effect_session_id
from coral.signals.turn_facts import EdgeFacts, is_archive_origin
from coral.stores.protocols import CoralRun, WorkItemDraft

# The pause detail of a failed orchestrator turn is this prefix and its failure class.
FAILURE_DETAIL_PREFIX = "orchestrator"


@dataclass(frozen=True)
class OrchestratorRows:
    """
    What one commit adds for the run's orchestrator.

    :param outbox: The create and the requests, which the commit must carry.
    :param asks: Re-requests and reminders, which a full commit may drop: each
        decision already had its request.
    :param session_id: The orchestrator session to name on the run row, set only by
        the commit that creates it.
    """

    outbox: tuple[WorkItemDraft, ...] = ()
    asks: tuple[WorkItemDraft, ...] = ()
    session_id: str | None = None


def open_decisions(state: engine.RunState) -> tuple[engine.Decision, ...]:
    """The decisions still waiting for a choice; none before the run starts or once it ends."""
    if state.status is None or state.status in engine.TERMINAL_STATUSES:
        return ()
    return tuple(item for item in state.decisions if item.status != "decided")


def orchestrator_session_id(run: CoralRun) -> str:
    """The orchestrator the run's row names, else the session its first create derives."""
    named = run.orchestrator_session_id
    if named is not None:
        return named
    return effect_session_id(run.workspace_id, orchestrator_effect_key(run.id))


def regather_session(run: CoralRun, state: engine.RunState) -> str | None:
    """The orchestrator a resync checks on: the named one, while a decision waits on it."""
    return run.orchestrator_session_id if open_decisions(state) else None


def is_decision_reminder(state: engine.RunState, effect: engine.Effect) -> bool:
    """Whether ``effect`` is a watchdog's ``notify`` on a decision still open in ``state``."""
    return (
        effect.kind == "notify"
        and effect.payload.get("kind") == "watchdog"
        and any(item.activation_id == effect.subject for item in open_decisions(state))
    )


def orchestrator_rows(
    ctx: MapContext,
    run: CoralRun,
    *,
    first: engine.RunState,
    effects: Iterable[engine.Effect],
    resumed: bool,
    run_version: int,
) -> OrchestratorRows:
    """
    The rows a commit queues for the orchestrator, from the states around it.

    ``ctx.state`` is the commit's final state. While a decision is open and the run
    names no orchestrator, its create comes first and every open decision is
    requested; otherwise each newly opened decision is requested, each still-open
    one is re-requested on a return to running (``resumed``), and each watchdog
    ``notify`` among ``effects`` on an open decision becomes a reminder while the run
    runs (a paused run is re-asked when it resumes).

    :param run_version: The version this commit gives the run, which keys re-requests.
    """
    waiting = open_decisions(ctx.state)
    if not waiting:
        return OrchestratorRows()
    named = run.orchestrator_session_id is not None
    session_id = orchestrator_session_id(run)
    rows: list[WorkItemDraft] = [] if named else [orchestrator_create_draft(ctx)]
    asks: list[WorkItemDraft] = []
    was_open = {item.activation_id for item in open_decisions(first)}
    for decision in waiting:
        decision_id = decision.activation_id
        if not named or decision_id not in was_open:
            key = decision_request_key(run.id, decision_id)
            rows.append(_message(ctx, session_id, decision_id, "request", key))
        elif resumed:
            key = decision_rerequest_key(run.id, decision_id, run_version)
            asks.append(_message(ctx, session_id, decision_id, "rerequest", key))
    if ctx.state.status == "running":
        for effect in effects:
            if is_decision_reminder(ctx.state, effect):
                key = effect.effect_key
                asks.append(_message(ctx, session_id, effect.subject, "reminder", key))
    return OrchestratorRows(
        outbox=tuple(rows), asks=tuple(asks), session_id=None if named else session_id
    )


def repair_drafts(ctx: MapContext, run: CoralRun) -> tuple[WorkItemDraft, ...]:
    """
    The orchestrator rows a resync expects: the create and each open decision's request.

    Empty while the run names no orchestrator; the resync's own commit then names it.
    """
    if run.orchestrator_session_id is None:
        return ()
    session_id = orchestrator_session_id(run)
    requests = (
        _message(
            ctx,
            session_id,
            item.activation_id,
            "request",
            decision_request_key(run.id, item.activation_id),
        )
        for item in open_decisions(ctx.state)
    )
    return (orchestrator_create_draft(ctx), *requests)


def revivable_work_ids(run: CoralRun, state: engine.RunState) -> tuple[str, ...]:
    """Rows a resume may revive: the orchestrator's create and each open decision's request."""
    waiting = open_decisions(state)
    if run.orchestrator_session_id is None and not waiting:
        return ()
    keys = [
        orchestrator_effect_key(run.id),
        *(decision_request_key(run.id, item.activation_id) for item in waiting),
    ]
    return tuple(effect_work_id(run.id, key) for key in keys)


def failure_pause(edge: EdgeFacts | None) -> engine.PauseRun | None:
    """
    The pause a failed orchestrator turn asks for, by the step classifier's class.

    A plan limit pauses ``plan_limit`` and an auth failure ``auth``; any other class
    pauses ``infra``, so a resume clears it. ``None`` for an edge that reports no
    failed turn.
    """
    if edge is None or is_archive_origin(edge.origin):
        return None
    failed = edge.turn_outcome == "failed" or (
        edge.turn_outcome is None and edge.status == "failed"
    )
    if not failed:
        return None
    failure = classify_failure(
        TurnSnapshot(
            error_code=edge.error_code,
            error_text=edge.error_message,
            failure_origin=edge.failure_origin,
        )
    )
    reason: engine.PauseReason = "infra"
    if failure.name.startswith("plan."):
        reason = "plan_limit"
    elif failure.name == "auth":
        reason = "auth"
    return engine.PauseRun(reason=reason, detail=f"{FAILURE_DETAIL_PREFIX}:{failure.name}")


def failure_inputs(
    state: engine.RunState, run: CoralRun, session_id: str, pause: engine.PauseRun
) -> tuple[engine.Input, ...]:
    """``pause`` while ``session_id`` is the run's orchestrator and a decision waits on it."""
    if run.orchestrator_session_id != session_id or not open_decisions(state):
        return ()
    return (pause,)


def _message(
    ctx: MapContext,
    session_id: str,
    decision_id: str,
    message: DecisionMessage,
    key: str,
) -> WorkItemDraft:
    return decision_message_draft(
        ctx, session_id=session_id, decision_id=decision_id, message=message, key=key
    )


__all__ = [
    "FAILURE_DETAIL_PREFIX",
    "OrchestratorRows",
    "failure_inputs",
    "failure_pause",
    "is_decision_reminder",
    "open_decisions",
    "orchestrator_rows",
    "orchestrator_session_id",
    "regather_session",
    "repair_drafts",
    "revivable_work_ids",
]
