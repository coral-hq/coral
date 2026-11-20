"""Worker supervisor: the replica lease, the startup sweep, the drain pool and the resync task."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from types import TracebackType
from typing import Any

from coral.db.enum_codecs import WorkKind
from coral.omni.protocols import RunScopeRunner
from coral.queue.drainer import (
    DEFAULT_EXECUTION_LIMIT_S,
    HoldPolicy,
    WorkDrainer,
    WorkFinishedHook,
)
from coral.queue.run_effects import describe_exception, raise_if_cancelling
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

# Waits until one of the events is set or ``timeout`` seconds pass (``None``: no
# timeout); returns whether an event is set.
EventWait = Callable[[Sequence[asyncio.Event], float | None], Awaitable[bool]]

RETRY_START_S = 1.0
RETRY_MAX_S = 30.0
PURGE_INTERVAL_S = 3600
PURGE_BATCH = 500
# Batches per resync tick, so a large backlog does not hold the resync task.
PURGE_BATCHES_PER_TICK = 20
MAX_DRAIN_CONCURRENCY = 64
# A leader that cannot confirm its lease steps down once this share of it has passed.
_STEP_DOWN_FRACTION = 0.75
# Finished signal and timer rows are purged after the retention; effect rows stay for audit.
_PURGED_KINDS = (int(WorkKind.SIGNAL), int(WorkKind.TIMER))


async def _wait_any_event(events: Sequence[asyncio.Event], timeout: float | None) -> bool:
    if any(ev.is_set() for ev in events):
        return True
    if not events:
        if timeout is None:
            await asyncio.get_running_loop().create_future()
        await asyncio.sleep(timeout or 0)
        return False
    waiters = [asyncio.create_task(ev.wait()) for ev in events]
    try:
        done, _ = await asyncio.wait(waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        return bool(done)
    finally:
        for w in waiters:
            w.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)


def _sleep_with(wait: EventWait) -> Callable[[float], Awaitable[None]]:
    """A sleep on ``wait``'s clock."""

    async def sleep(seconds: float) -> None:
        await wait((), seconds)

    return sleep


def _retry_delay(failures: int) -> float:
    """1 s after the first failure in a row, doubling up to :data:`RETRY_MAX_S`."""
    return min(RETRY_MAX_S, RETRY_START_S * 2 ** min(failures - 1, 16))


class WorkerSupervisor:
    """
    Supervises the leader lease, the startup sweep, the drain pool and the resync task.

    While leader, ``drain_concurrency`` workers drain the queue, never two items
    of one run at once in this process, and every ``resync_interval_s`` the
    resync task passes each active run to ``run_reconciler`` and each run's open
    gates to ``gate_republisher`` (as the startup sweep does) and, hourly, purges
    finished signal and timer rows older than ``retention_s``. Workers, the task
    and the lease renewal log their errors and retry after a growing delay. The
    replica steps down when it cannot confirm its lease (a renewal or the reclaim
    after it fails or hangs) before the last quarter of the lease, and restarts its
    leadership when one of its tasks ends.

    :param poll_interval_s: How often the pool as a whole polls an empty queue.
    :param resync_interval_s: ``None`` turns off the resync task and the purge.
    :param execution_limit_s: How long one attempt of an item may run; ``None``: no limit.
    :param wait: The timed wait every loop uses; tests pass a virtual clock's.
    """

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
        drain_concurrency: int = 4,
        on_finished: WorkFinishedHook | None = None,
        hold_policy: HoldPolicy | None = None,
        resync_interval_s: float | None = 60.0,
        retention_s: int = 86_400,
        execution_limit_s: float | None = DEFAULT_EXECUTION_LIMIT_S,
        wait: EventWait = _wait_any_event,
    ) -> None:
        if not 1 <= drain_concurrency <= MAX_DRAIN_CONCURRENCY:
            raise ValueError(f"drain_concurrency must be 1-{MAX_DRAIN_CONCURRENCY}")
        if resync_interval_s is not None and resync_interval_s <= 0:
            raise ValueError("resync_interval_s must be positive")
        if retention_s < PURGE_INTERVAL_S:
            raise ValueError(f"retention_s must be at least {PURGE_INTERVAL_S}")
        if renew_interval_s >= lease_seconds * _STEP_DOWN_FRACTION:
            # Its renewal would come after the step-down time, so leadership would flap.
            raise ValueError(
                "renew_interval_s must be below 3/4 of lease_seconds, when the leader steps down"
            )
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
            on_finished=on_finished,
            hold_policy=hold_policy,
            execution_limit_s=execution_limit_s,
            sleep=_sleep_with(wait),
        )
        self._poll_interval_s = poll_interval_s
        self._standby_retry_s = standby_retry_s
        self._scope_runner = scope_runner
        self._gate_republisher = gate_republisher
        self._run_reconciler = run_reconciler
        self._clock = clock
        self._drain_concurrency = drain_concurrency
        self._resync_interval_s = resync_interval_s
        self._retention_s = retention_s
        self._wait = wait
        # Workers claim one at a time, excluding the runs this process has in flight.
        self._claim_lock = asyncio.Lock()
        self._busy_runs: set[str] = set()
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
        faults = 0
        while not self._stop_event.is_set():
            try:
                acquired = await self._lease_manager.try_acquire()
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged; retried
                raise_if_cancelling(exc)
                _logger.error(
                    "Error attempting to acquire Coral worker lease: %s", describe_exception(exc)
                )
                acquired = False

            if not acquired:
                self._leader_ready_event.clear()
                await self._wait((self._stop_event,), self._standby_retry_s)
                continue

            faulted = await self._run_leader_epoch()
            self._leader_ready_event.clear()
            faults = faults + 1 if faulted else 0
            if faulted:
                await self._wait((self._stop_event,), _retry_delay(faults))

    async def _run_leader_epoch(self) -> bool:
        """Lead until a stop, a lost lease or a task's end; ``True`` for the last."""
        loss_ev = self._lease_manager.lease_lost_event
        task_ended = asyncio.Event()
        tasks: list[asyncio.Task[None]] = []

        def start(name: str, work: Coroutine[Any, Any, None]) -> None:
            task = asyncio.create_task(work, name=name)
            task.add_done_callback(lambda _task: task_ended.set())
            tasks.append(task)

        # Renewing from the start, so a long startup sweep cannot outlast the lease.
        start("coral-lease-renewal", self._renewal_loop())
        try:
            try:
                self.last_startup_report = await startup_recovery_sweep(
                    self._run_store,
                    self._queue_store,
                    scope_runner=self._scope_runner,
                    gate_republisher=self._gate_republisher,
                    run_reconciler=self._run_reconciler,
                    clock=self._clock,
                )
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged
                raise_if_cancelling(exc)
                _logger.error(
                    "Error during Coral startup recovery sweep: %s", describe_exception(exc)
                )

            if self._stop_event.is_set() or loss_ev.is_set():
                return False

            self._leader_ready_event.set()
            for index in range(self._drain_concurrency):
                start(f"coral-drain-worker-{index}", self._drain_worker())
            if self._resync_interval_s is not None:
                start("coral-resync", self._resync_loop(self._resync_interval_s))
            # No timeout: an item in flight is never cancelled for the epoch's age.
            await self._wait((self._stop_event, loss_ev, task_ended), None)
            if self._stop_event.is_set() or loss_ev.is_set():
                return False
            for task in tasks:
                if task.done():
                    _logger.error(
                        "Coral leader task %s ended: %s; restarting leadership",
                        task.get_name(),
                        _task_end(task),
                    )
            return True
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _renewal_loop(self) -> None:
        """Renew the lease; a failed renewal is retried until the lease's last quarter."""
        manager = self._lease_manager
        loss_ev = manager.lease_lost_event
        failures = 0
        while True:
            delay = manager.renew_interval_s if failures == 0 else _retry_delay(failures)
            delay = min(delay, max(0.0, self._step_down_at() - self._clock()))
            if await self._wait((self._stop_event, loss_ev), delay):
                return
            try:
                renewed = bool(await self._by_step_down(manager.renew_once()))
            except _LeaseOverdue:
                _logger.error("Coral worker lease renewal did not return in time; stepping down")
                manager.mark_lost()
                return
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged; retried
                raise_if_cancelling(exc)
                failures += 1
                _logger.error(
                    "Coral worker lease renewal failed (%d in a row): %s",
                    failures,
                    describe_exception(exc),
                )
                if self._clock() >= self._step_down_at():
                    _logger.error("Coral worker lease could not be confirmed; stepping down")
                    manager.mark_lost()
                    return
                continue
            if not renewed:
                return
            failures = 0
            try:
                await self._by_step_down(
                    asyncio.to_thread(self._queue_store.reclaim_expired_work, now_fn=self._clock)
                )
            except _LeaseOverdue:
                # Until this returns no renewal can run, so the lease would lapse unseen.
                _logger.error(
                    "Coral reclaim of expired work did not return in time; stepping down"
                )
                manager.mark_lost()
                return
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged
                raise_if_cancelling(exc)
                _logger.error("Coral reclaim of expired work failed: %s", describe_exception(exc))

    async def _by_step_down[T](self, work: Awaitable[T]) -> T | None:
        """
        ``work``'s result, given up once the step-down time passes on this replica's clock.

        A store call stuck in a lock wait or on a half-open connection cannot hold
        leadership past that time; its thread may still finish. ``None`` when a stop or
        a lost lease comes first.

        :raises _LeaseOverdue: when the step-down time passed first.
        """
        loss_ev = self._lease_manager.lease_lost_event
        call = asyncio.ensure_future(work)
        timer = asyncio.ensure_future(
            self._wait((self._stop_event, loss_ev), max(0.0, self._step_down_at() - self._clock()))
        )
        returned = False
        try:
            await asyncio.wait({call, timer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            returned = call.done()
            call.cancel()
            timer.cancel()
            await asyncio.gather(call, timer, return_exceptions=True)
        if returned:
            return call.result()
        if timer.result():
            return None
        raise _LeaseOverdue

    def _step_down_at(self) -> float:
        """When to stop leading without a renewal: a quarter of the lease before it ends."""
        until = self._lease_manager.confirmed_until
        if until is None:
            return self._clock()
        return until - self._lease_manager.lease_seconds * (1 - _STEP_DOWN_FRACTION)

    async def _drain_worker(self) -> None:
        loss_ev = self._lease_manager.lease_lost_event
        failures = 0
        while not self._stop_event.is_set() and not loss_ev.is_set():
            try:
                drained = await self._drain_next()
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged; retried
                raise_if_cancelling(exc)
                failures += 1
                _logger.error(
                    "Coral drain worker failed (%d in a row): %s",
                    failures,
                    describe_exception(exc),
                )
                delay = _retry_delay(failures)
            else:
                failures = 0
                if drained:
                    continue
                # Idle workers poll in turn: the pool polls once per poll interval.
                delay = self._poll_interval_s * self._drain_concurrency
            await self._wait((self._stop_event, loss_ev), delay)

    async def _drain_next(self) -> bool:
        """Claim and run one item of a run no other worker has in flight."""
        if self._clock() >= self._step_down_at():
            # The lease is unconfirmed this late: claim nothing until a renewal lands.
            return False
        async with self._claim_lock:
            claimed = await self._drainer.claim(exclude_run_ids=frozenset(self._busy_runs))
            if claimed is None:
                return False
            self._busy_runs.add(claimed.run_id)
        try:
            await self._drainer.run_claimed(claimed)
        finally:
            self._busy_runs.discard(claimed.run_id)
        return True

    async def _resync_loop(self, interval_s: float) -> None:
        loss_ev = self._lease_manager.lease_lost_event
        failures = 0
        purge_failures = 0
        next_purge_at: float | None = None
        while True:
            delay = interval_s if failures == 0 else _retry_delay(failures)
            if await self._wait((self._stop_event, loss_ev), delay):
                return
            if self._run_reconciler is not None or self._gate_republisher is not None:
                try:
                    # The republisher shows only prompts this process lost since the last tick.
                    await startup_recovery_sweep(
                        self._run_store,
                        self._queue_store,
                        scope_runner=self._scope_runner,
                        gate_republisher=self._gate_republisher,
                        run_reconciler=self._run_reconciler,
                        clock=self._clock,
                    )
                    failures = 0
                except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- retried
                    raise_if_cancelling(exc)
                    failures += 1
                    _logger.error(
                        "Coral resync task failed (%d in a row): %s",
                        failures,
                        describe_exception(exc),
                    )
            now = self._clock()
            if next_purge_at is not None and now < next_purge_at:
                continue
            # A failed purge is retried at the next tick, without hurrying the sweep.
            try:
                done = await self._purge_finished(now)
                purge_failures = 0
                next_purge_at = now + PURGE_INTERVAL_S if done else now
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged; retried
                raise_if_cancelling(exc)
                purge_failures += 1
                _logger.error(
                    "Coral retention purge failed (%d in a row): %s",
                    purge_failures,
                    describe_exception(exc),
                )

    async def _purge_finished(self, now: float) -> bool:
        """Purge up to :data:`PURGE_BATCHES_PER_TICK` batches; ``True`` once a batch is short."""
        finished_before = int(now) - self._retention_s
        for _ in range(PURGE_BATCHES_PER_TICK):
            purged = await asyncio.to_thread(
                self._queue_store.purge_finished,
                kinds=_PURGED_KINDS,
                finished_before=finished_before,
                limit=PURGE_BATCH,
            )
            if purged < PURGE_BATCH:
                return True
        return False


class _LeaseOverdue(Exception):
    """A renewal-loop store call did not return before the replica had to step down."""


def _task_end(task: asyncio.Task[None]) -> str:
    """How a finished task ended, for a log line."""
    if task.cancelled():
        return "cancelled"
    exc = task.exception()
    return "returned" if exc is None else describe_exception(exc)


__all__ = ["EventWait", "WorkerSupervisor"]
