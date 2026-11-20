"""Gate delivery: a live visit's prompt on its run's anchor, and a closed visit's withdrawal.

Payloads name only the visit's row; the anchor comes from the run and the prompt
id from the row, so a payload can point at nothing else. Both executors re-read
the engine state: a publish shows only live visits and reads the state again
afterwards, withdrawing what it showed for a visit that closed meanwhile (a
cancel or an answer that raced it). They are never fed to the engine.
"""

from __future__ import annotations

import asyncio
import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from coral.bridge.executors import BridgeThreads
from coral.bridge.service import LOAD_FAILED_DETAIL, EngineLoadFailed
from coral.db.enum_codecs import SessionBindingProgress
from coral.engine import types as engine
from coral.gates.ids import find_visit, live_visit
from coral.gates.prompt import gate_params
from coral.model.ids import anchor_session_id
from coral.omni.protocols import GatePublisher, RunScopeRunner
from coral.queue.executors import EffectExecutor, EffectOutcome, ExecutionContext
from coral.queue.run_effects import EffectRefused, invalid_payload, run_effect
from coral.stores.protocols import GateVisitState, RunState, RunStore
from coral.stores.session_bindings import SessionBindings

_VISIT_ID = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class PublishReport:
    """
    What one publish pass did.

    :param published: The prompt ids published.
    :param withdrawn: Of those, the ones whose visit was no longer live on the second
        read, so they were withdrawn again.
    :param missing: Visits that are live but whose row is not written yet.
    """

    published: tuple[str, ...] = ()
    withdrawn: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


async def publish_live(
    publisher: GatePublisher,
    threads: BridgeThreads,
    *,
    workspace_id: int,
    run_id: str,
    visit_ids: Sequence[str],
) -> PublishReport:
    """
    Publish each live visit's prompt on the run's anchor, then withdraw any that closed.

    Loads the run once, publishes every live visit among ``visit_ids`` with its
    row's prompt id and K14 params, loads it again and withdraws each published
    prompt whose visit is no longer live. The caller is in the run's workspace scope.

    :raises EngineLoadFailed: when the run cannot be loaded; it is paused once.
    """
    bridge = threads.bridge
    snapshot = await threads.run(bridge.load, workspace_id=workspace_id, run_id=run_id)
    rows = {row.id: row for row in snapshot.store.gate_visits}
    anchor = anchor_session_id(workspace_id, run_id)
    published: list[tuple[str, str]] = []
    missing: list[str] = []
    for visit_id in dict.fromkeys(visit_ids):
        visit = _live(snapshot.state, run_id, visit_id)
        if visit is None:
            continue
        row = rows.get(visit_id)
        if row is None or row.elicitation_id is None:
            missing.append(visit_id)
            continue
        params = gate_params(snapshot.graph, snapshot.state, snapshot.store.run, visit, row)
        await publisher.publish(
            session_id=anchor, elicitation_id=row.elicitation_id, params=params
        )
        published.append((visit_id, row.elicitation_id))
    if not published:
        return PublishReport(missing=tuple(missing))
    again = await threads.run(bridge.load, workspace_id=workspace_id, run_id=run_id)
    withdrawn: list[str] = []
    for visit_id, elicitation_id in published:
        if _live(again.state, run_id, visit_id) is None:
            await publisher.withdraw(session_id=anchor, elicitation_id=elicitation_id)
            withdrawn.append(elicitation_id)
    return PublishReport(
        published=tuple(elicitation_id for _visit_id, elicitation_id in published),
        withdrawn=tuple(withdrawn),
        missing=tuple(missing),
    )


def gate_publish_executor(
    threads: BridgeThreads,
    publisher: GatePublisher,
    bindings: SessionBindings,
    run_store: RunStore,
    scope_runner: RunScopeRunner,
) -> EffectExecutor:
    """
    The ``gate_publish`` executor: show a live visit's prompt on its run's anchor.

    Payload: ``effect_key`` and ``visit_id`` (32 lowercase hex). Until the anchor's
    create has finished it fails retryable ``session.anchor_missing`` (held), and a
    live visit whose row is not written yet fails retryable ``gate.row_missing``.
    A visit that is not live is not shown. Result: ``{elicitation_id, published}``,
    ``published`` false when nothing stayed shown. A paused run's live visit is shown.
    """

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(
            _publish, ctx, threads=threads, publisher=publisher, bindings=bindings
        )
        return await run_effect(ctx, run_store, scope_runner, _visit_payload, body)

    return execute


def gate_withdraw_executor(
    threads: BridgeThreads,
    publisher: GatePublisher,
    run_store: RunStore,
    scope_runner: RunScopeRunner,
) -> EffectExecutor:
    """
    The ``gate_withdraw`` executor: drop a closed visit's prompt from its run's anchor.

    Registered to run after its run ended, since a cancel queues one per open
    visit. A visit that is still live, or a row without a prompt id, is left
    alone; withdrawing an absent prompt changes nothing. Result:
    ``{elicitation_id, withdrawn}``.
    """

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(_withdraw, ctx, threads=threads, publisher=publisher)
        return await run_effect(ctx, run_store, scope_runner, _visit_payload, body)

    return execute


async def _publish(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    threads: BridgeThreads,
    publisher: GatePublisher,
    bindings: SessionBindings,
) -> dict[str, Any]:
    anchor = anchor_session_id(state.workspace_id, state.run_id)
    binding = await asyncio.to_thread(
        bindings.get, state.workspace_id, anchor, run_id=state.run_id
    )
    if binding is None or binding.progress < SessionBindingProgress.INITIALIZED:
        raise EffectRefused(
            "session.anchor_missing",
            f"run {state.run_id}'s anchor session is not created yet",
            retryable=True,
        )
    await ctx.ensure_lease()
    try:
        report = await publish_live(
            publisher,
            threads,
            workspace_id=state.workspace_id,
            run_id=state.run_id,
            visit_ids=(payload["visit_id"],),
        )
    except EngineLoadFailed:
        raise _unloadable(state) from None
    if report.missing:
        raise EffectRefused(
            "gate.row_missing",
            f"run {state.run_id}'s gate visit row is not written yet",
            retryable=True,
        )
    shown = [item for item in report.published if item not in report.withdrawn]
    elicitation_id = report.published[0] if report.published else None
    return {"elicitation_id": elicitation_id, "published": bool(shown)}


async def _withdraw(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    threads: BridgeThreads,
    publisher: GatePublisher,
) -> dict[str, Any]:
    visit_id = payload["visit_id"]
    try:
        snapshot = await threads.run(
            threads.bridge.load, workspace_id=state.workspace_id, run_id=state.run_id
        )
    except EngineLoadFailed:
        raise _unloadable(state) from None
    row = _row(snapshot.store.gate_visits, visit_id)
    elicitation_id = row.elicitation_id if row is not None else None
    if elicitation_id is None or _live(snapshot.state, state.run_id, visit_id) is not None:
        return {"elicitation_id": elicitation_id, "withdrawn": False}
    await ctx.ensure_lease()
    withdrawn = await publisher.withdraw(
        session_id=anchor_session_id(state.workspace_id, state.run_id),
        elicitation_id=elicitation_id,
    )
    return {"elicitation_id": elicitation_id, "withdrawn": withdrawn}


def _visit_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    visit_id = payload.get("visit_id")
    if not isinstance(visit_id, str) or not _VISIT_ID.fullmatch(visit_id):
        raise invalid_payload("visit_id must be 32 lowercase hex characters")
    return {"visit_id": visit_id}


def _live(state: engine.RunState, run_id: str, visit_id: str) -> engine.GateVisit | None:
    """The engine visit of the row ``visit_id`` while it can be answered, else ``None``."""
    visit = find_visit(state, run_id, visit_id)
    return visit if visit is not None and live_visit(state, visit) else None


def _row(rows: Sequence[GateVisitState], visit_id: str) -> GateVisitState | None:
    return next((row for row in rows if row.id == visit_id), None)


def _unloadable(state: RunState) -> EffectRefused:
    return EffectRefused(LOAD_FAILED_DETAIL, f"run {state.run_id} cannot be loaded; it is paused")


__all__ = [
    "PublishReport",
    "gate_publish_executor",
    "gate_withdraw_executor",
    "publish_live",
]
