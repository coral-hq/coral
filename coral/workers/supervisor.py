"""Worker supervisor coordinating replica lease, startup recovery sweep, and work drainer."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Sequence
from types import TracebackType

from coral.db.enum_codecs import WorkKind
from coral.omni.protocols import RunScopeRunner
from coral.queue.drainer import WorkDrainer
from coral.reconcile.startup import (
    GateRepublisher,
    RunReconciler,
    StartupReport,
    startup_recovery_sweep,
)
from coral.stores.protocols import QueueStore, RunStore
from coral.workers.worker_lease import (
    DEFAULT_WORKER_LEASE_NAME,
    DEFAULT_WORKER_LEASE_SECONDS,
    DEFAULT_WORKER_RENEW_INTERVAL_S,
    WorkerLeaseManager,
)

_logger = logging.getLogger(__name__)


async def _wait_any_event(events: Sequence[asyncio.Event], timeout: float) -> bool:
    if any(ev.is_set() for ev in events):
        return True
    waiters = [asyncio.create_task(ev.wait()) for ev in events]
    try:
        done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        return bool(done)
    finally:
        for w in waiters:
            w.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)


class WorkerSupervisor:
    """Supervises leader lease acquisition, startup sweep, and background work draining."""

    def __init__(
        self,
        run_store: RunStore,
        queue_store: QueueStore,
        *,
        worker_id: str | None = None,
        lease_name: str = DEFAULT_WORKER_LEASE_NAME,
        lease_seconds: int = DEFAULT_WORKER_LEASE_SECONDS,
        renew_interval_s: float = DEFAULT_WORKER_RENEW_INTERVAL_S,
        poll_interval_s: float = 0.25,
        standby_retry_s: float = 2.0,
        work_lease_seconds: int = 60,
        kinds: Sequence[int] = (
            int(WorkKind.EFFECT),
            int(WorkKind.SIGNAL),
            int(WorkKind.TIMER),
        ),
        scope_runner: RunScopeRunner | None = None,
        gate_republisher: GateRepublisher | None = None,
        run_reconciler: RunReconciler | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._run_store = run_store
        self._queue_store = queue_store
        self._lease_manager = WorkerLeaseManager(
            queue_store,
            worker_id=worker_id,
            lease_name=lease_name,
            lease_seconds=lease_seconds,
            renew_interval_s=renew_interval_s,
            clock=clock,
        )
        self._drainer = WorkDrainer(
            queue_store,
            worker_id=self._lease_manager.worker_id,
            kinds=kinds,
            lease_seconds=work_lease_seconds,
            scope_runner=scope_runner,
            clock=clock,
        )
        self._poll_interval_s = poll_interval_s
        self._standby_retry_s = standby_retry_s
        self._scope_runner = scope_runner
        self._gate_republisher = gate_republisher
        self._run_reconciler = run_reconciler
        self._clock = clock
        self._stop_event = asyncio.Event()
        self._leader_ready_event = asyncio.Event()
        self._main_task: asyncio.Task[None] | None = None
        self.last_startup_report: StartupReport | None = None

    @property
    def worker_id(self) -> str:
        return self._lease_manager.worker_id

    @property
    def lease_manager(self) -> WorkerLeaseManager:
        return self._lease_manager

    @property
    def is_leader(self) -> bool:
        return self._lease_manager.is_leader

    @property
    def leader_ready_event(self) -> asyncio.Event:
        return self._leader_ready_event

    async def start(self) -> None:
        """Start the background supervisor task."""
        if self._main_task is not None and not self._main_task.done():
            return
        self._stop_event.clear()
        self._leader_ready_event.clear()
        self._main_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop all background tasks and release the replica lease immediately."""
        self._stop_event.set()
        task = self._main_task
        self._main_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._lease_manager.release()
        self._leader_ready_event.clear()

    async def __aenter__(self) -> WorkerSupervisor:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb
        await self.stop()

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                acquired = await self._lease_manager.try_acquire()
            except Exception:
                _logger.exception("Error attempting to acquire Coral worker lease")
                acquired = False

            if not acquired:
                self._leader_ready_event.clear()
                await _wait_any_event((self._stop_event,), self._standby_retry_s)
                continue

            await self._run_leader_epoch()
            self._leader_ready_event.clear()

    async def _run_leader_epoch(self) -> None:
        loss_ev = self._lease_manager.lease_lost_event
        try:
            self.last_startup_report = await startup_recovery_sweep(
                self._run_store,
                self._queue_store,
                scope_runner=self._scope_runner,
                gate_republisher=self._gate_republisher,
                run_reconciler=self._run_reconciler,
                clock=self._clock,
            )
        except Exception:
            _logger.exception("Error during Coral startup recovery sweep")

        if self._stop_event.is_set() or loss_ev.is_set():
            return

        self._leader_ready_event.set()
        renew_task = asyncio.create_task(self._renewal_loop())
        drain_task = asyncio.create_task(self._drain_loop())
        try:
            await _wait_any_event((self._stop_event, loss_ev), timeout=3600.0)
        finally:
            renew_task.cancel()
            drain_task.cancel()
            await asyncio.gather(renew_task, drain_task, return_exceptions=True)

    async def _renewal_loop(self) -> None:
        loss_ev = self._lease_manager.lease_lost_event
        while not self._stop_event.is_set() and not loss_ev.is_set():
            woke = await _wait_any_event(
                (self._stop_event, loss_ev),
                self._lease_manager.renew_interval_s,
            )
            if woke:
                return
            ok = await self._lease_manager.renew_once()
            if not ok:
                return
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    self._queue_store.reclaim_expired_work,
                    now_fn=self._clock,
                )

    async def _drain_loop(self) -> None:
        loss_ev = self._lease_manager.lease_lost_event
        while not self._stop_event.is_set() and not loss_ev.is_set():
            item = await self._drainer.drain_once()
            if item is not None:
                continue
            await _wait_any_event(
                (self._stop_event, loss_ev),
                self._poll_interval_s,
            )


__all__ = ["WorkerSupervisor"]
