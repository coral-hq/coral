"""Startup recovery sweep for reclaiming expired work and reconciling active runs and gates."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from coral.omni.protocols import NoOpScopeRunner, RunScopeRunner
from coral.stores.protocols import CoralRun, GateVisitState, QueueStore, RunStore

_logger = logging.getLogger(__name__)

GateRepublisher = Callable[[GateVisitState], Awaitable[None] | None]
RunReconciler = Callable[[CoralRun], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class StartupReport:
    """Summary of a completed startup recovery sweep."""

    reclaimed_work: int = 0
    active_runs_scanned: int = 0
    active_runs_reconciled: int = 0
    open_gates_scanned: int = 0
    open_gates_republished: int = 0
    errors: int = 0


async def startup_recovery_sweep(
    run_store: RunStore,
    queue_store: QueueStore,
    *,
    scope_runner: RunScopeRunner | None = None,
    gate_republisher: GateRepublisher | None = None,
    run_reconciler: RunReconciler | None = None,
    page_size: int = 100,
    clock: Callable[[], float] = time.time,
) -> StartupReport:
    """Reclaim expired work items and scan open gates and active runs across all workspaces.

    Errors in individual gate republishers or run reconcilers are logged and counted
    without aborting the sweep for remaining gates or runs.
    """
    runner: RunScopeRunner = scope_runner if scope_runner is not None else NoOpScopeRunner()
    reclaimed_total = 0
    while True:
        batch_reclaimed = await asyncio.to_thread(
            queue_store.reclaim_expired_work,
            limit=page_size,
            now_fn=clock,
        )
        reclaimed_total += batch_reclaimed
        if batch_reclaimed < page_size:
            break

    open_gates_scanned = 0
    open_gates_republished = 0
    errors = 0
    gate_cursor: tuple[int, str, str] | None = None
    while True:
        gates = await asyncio.to_thread(
            run_store.list_open_gates_all_workspaces,
            cursor=gate_cursor,
            limit=page_size,
        )
        if not gates:
            break
        for gate in gates:
            open_gates_scanned += 1
            if gate_republisher is not None:
                try:
                    async with runner.run_scope(
                        workspace_id=gate.workspace_id,
                        run_id=gate.run_id,
                        user_id=gate.owner_user_id,
                    ):
                        res = gate_republisher(gate)
                        if inspect.isawaitable(res):
                            await res
                    open_gates_republished += 1
                except Exception:
                    errors += 1
                    _logger.exception(
                        "Startup sweep failed republishing gate %s for run %s in workspace %d",
                        gate.id,
                        gate.run_id,
                        gate.workspace_id,
                    )
        if len(gates) < page_size:
            break
        last_gate = gates[-1]
        gate_cursor = (last_gate.workspace_id, last_gate.run_id, last_gate.id)

    active_runs_scanned = 0
    active_runs_reconciled = 0
    run_cursor: tuple[int, str] | None = None
    while True:
        runs = await asyncio.to_thread(
            run_store.list_active_runs_all_workspaces,
            cursor=run_cursor,
            limit=page_size,
        )
        if not runs:
            break
        for run in runs:
            active_runs_scanned += 1
            if run_reconciler is not None:
                try:
                    async with contextlib.AsyncExitStack() as stack:
                        await stack.enter_async_context(
                            runner.run_scope(
                                workspace_id=run.workspace_id,
                                run_id=run.id,
                                user_id=run.user_id,
                                account_generation=run.account_generation,
                            )
                        )
                        res = run_reconciler(run)
                        if inspect.isawaitable(res):
                            await res
                    active_runs_reconciled += 1
                except Exception:
                    errors += 1
                    _logger.exception(
                        "Startup sweep failed reconciling run %s in workspace %d",
                        run.id,
                        run.workspace_id,
                    )
        if len(runs) < page_size:
            break
        last_run = runs[-1]
        run_cursor = (last_run.workspace_id, last_run.id)

    return StartupReport(
        reclaimed_work=reclaimed_total,
        active_runs_scanned=active_runs_scanned,
        active_runs_reconciled=active_runs_reconciled,
        open_gates_scanned=open_gates_scanned,
        open_gates_republished=open_gates_republished,
        errors=errors,
    )


__all__ = [
    "GateRepublisher",
    "RunReconciler",
    "StartupReport",
    "startup_recovery_sweep",
]
