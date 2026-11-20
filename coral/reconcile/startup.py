"""Startup recovery sweep for reclaiming expired work and reconciling active runs and gates."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from coral.omni.protocols import NoOpScopeRunner, RunScopeRunner
from coral.queue.run_effects import describe_exception, raise_if_cancelling
from coral.stores.protocols import CoralRun, GateVisitState, QueueStore, RunStore

_logger = logging.getLogger(__name__)

# Republishes one run's OPEN gate rows, called in that run's scope.
GateRepublisher = Callable[[Sequence[GateVisitState]], Awaitable[None] | None]
RunReconciler = Callable[[CoralRun], Awaitable[None] | None]
# Runs whose gates are republished at once, and how long each may take.
DEFAULT_GATE_CONCURRENCY = 4
DEFAULT_GATE_TIMEOUT_S = 10.0


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
    gate_concurrency: int = DEFAULT_GATE_CONCURRENCY,
    gate_timeout_s: float = DEFAULT_GATE_TIMEOUT_S,
    clock: Callable[[], float] = time.time,
) -> StartupReport:
    """Reclaim expired work items and scan open gates and active runs across all workspaces.

    Open gates go to the republisher one run at a time, at most ``gate_concurrency``
    runs at once, each within ``gate_timeout_s``. A failing or slow republish, a
    failed gate listing or a failing run reconciler is logged and counted without
    aborting the sweep for the remaining runs. Without a republisher the gates are
    not scanned.
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

    gates = _GateSweep(scanned=0, republished=0, errors=0)
    if gate_republisher is not None:
        gates = await _republish_open_gates(
            run_store,
            runner,
            gate_republisher,
            page_size=page_size,
            concurrency=gate_concurrency,
            timeout_s=gate_timeout_s,
        )
    errors = gates.errors

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
                except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged
                    raise_if_cancelling(exc)
                    errors += 1
                    _logger.error(
                        "Startup sweep failed reconciling run %s in workspace %d: %s",
                        run.id,
                        run.workspace_id,
                        describe_exception(exc),
                    )
        if len(runs) < page_size:
            break
        last_run = runs[-1]
        run_cursor = (last_run.workspace_id, last_run.id)

    return StartupReport(
        reclaimed_work=reclaimed_total,
        active_runs_scanned=active_runs_scanned,
        active_runs_reconciled=active_runs_reconciled,
        open_gates_scanned=gates.scanned,
        open_gates_republished=gates.republished,
        errors=errors,
    )


@dataclass(frozen=True, slots=True)
class _GateSweep:
    scanned: int
    republished: int
    errors: int


async def _republish_open_gates(
    run_store: RunStore,
    runner: RunScopeRunner,
    republisher: GateRepublisher,
    *,
    page_size: int,
    concurrency: int,
    timeout_s: float,
) -> _GateSweep:
    """
    Page the OPEN gate rows and republish each run's rows as one batch.

    Rows come ordered by workspace, run and id, so a full page's last run may
    continue on the next page: its rows wait for that page.
    """
    limit = asyncio.Semaphore(concurrency)

    async def republish(rows: list[GateVisitState]) -> bool:
        first = rows[0]
        async with limit:
            try:
                async with asyncio.timeout(timeout_s):
                    async with runner.run_scope(
                        workspace_id=first.workspace_id,
                        run_id=first.run_id,
                        user_id=first.owner_user_id,
                    ):
                        res = republisher(rows)
                        if inspect.isawaitable(res):
                            await res
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged
                raise_if_cancelling(exc)
                _logger.error(
                    "Startup sweep failed republishing %d gates of run %s in workspace %d: %s",
                    len(rows),
                    first.run_id,
                    first.workspace_id,
                    describe_exception(exc),
                )
                return False
        return True

    scanned = republished = errors = 0
    cursor: tuple[int, str, str] | None = None
    carried: list[GateVisitState] = []
    while True:
        try:
            page = await asyncio.to_thread(
                run_store.list_open_gates_all_workspaces, cursor=cursor, limit=page_size
            )
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged
            raise_if_cancelling(exc)
            # The runs already listed are still republished; the next sweep lists again.
            errors += 1
            _logger.error("Startup sweep could not list open gates: %s", describe_exception(exc))
            page = []
        scanned += len(page)
        full = len(page) == page_size
        runs = _by_run([*carried, *page])
        carried = runs.pop() if full and runs else []
        outcomes = await asyncio.gather(*(republish(rows) for rows in runs))
        for rows, ok in zip(runs, outcomes, strict=True):
            if ok:
                republished += len(rows)
            else:
                errors += 1
        if not full:
            return _GateSweep(scanned=scanned, republished=republished, errors=errors)
        last = page[-1]
        cursor = (last.workspace_id, last.run_id, last.id)


def _by_run(rows: list[GateVisitState]) -> list[list[GateVisitState]]:
    """Consecutive rows of the same run, in order."""
    runs: list[list[GateVisitState]] = []
    for row in rows:
        if runs and (runs[-1][0].workspace_id, runs[-1][0].run_id) == (
            row.workspace_id,
            row.run_id,
        ):
            runs[-1].append(row)
        else:
            runs.append([row])
    return runs


__all__ = [
    "DEFAULT_GATE_CONCURRENCY",
    "DEFAULT_GATE_TIMEOUT_S",
    "GateRepublisher",
    "RunReconciler",
    "StartupReport",
    "startup_recovery_sweep",
]
