"""The supervisor's drain pool, its survival of store errors, and its resync and retention task."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import Counter
from collections.abc import Collection, Sequence
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from coral.db.enum_codecs import RunPauseReason, RunStatus, WorkKind, WorkStatus
from coral.queue import (
    EffectCompleted,
    ExecutionContext,
    FinishedWork,
    register_executor,
    unregister_executor,
)
from coral.stores.fakes import FakeQueueStore, FakeRunStore
from coral.stores.protocols import CoralRun, RunStartSpec, Transition, WorkItem, WorkItemDraft
from coral.workers import DEFAULT_WORKER_LEASE_NAME, WorkerSupervisor
from tests._helpers.polling import poll_until_async
from tests.budgets import budget

_START = 1_700_000_000.0
_STEP = "test.pool_step"
_SENTINEL = "SENTINEL-bound-parameter"


class VirtualTime:
    """A test clock whose timed waits end only when the test advances it past them."""

    def __init__(self, now: float) -> None:
        self.now = now
        self._timers: list[tuple[float, float, asyncio.Future[None]]] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds
        for deadline, _, timer in self._timers:
            if deadline <= self.now and not timer.done():
                timer.set_result(None)

    def waiting(self, timeout: float, count: int = 1) -> bool:
        """Whether at least ``count`` waits of ``timeout`` seconds are pending."""
        pending = [length for _, length, timer in self._timers if not timer.done()]
        return pending.count(timeout) >= count

    async def wait(self, events: Sequence[asyncio.Event], timeout: float | None) -> bool:
        if any(event.is_set() for event in events):
            return True
        waiters: list[asyncio.Future[Any]] = [asyncio.ensure_future(e.wait()) for e in events]
        entry: tuple[float, float, asyncio.Future[None]] | None = None
        if timeout is not None and timeout <= 0:
            await asyncio.sleep(0)
            return any(event.is_set() for event in events)
        if timeout is not None:
            entry = (self.now + timeout, timeout, asyncio.get_running_loop().create_future())
            self._timers.append(entry)
            waiters.append(entry[2])
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            if entry is not None:
                self._timers.remove(entry)
        return any(event.is_set() for event in events)


def _store_error() -> OperationalError:
    return OperationalError(
        "SELECT * FROM coral_work WHERE payload = ?", (_SENTINEL,), Exception("database is locked")
    )


class FlakyQueue(FakeQueueStore):
    """A fake queue whose claims, lease calls and purges fail with a store error when asked to."""

    def __init__(
        self,
        *,
        run_store: FakeRunStore,
        failing_claims: int = 0,
        failing_renewals: int = 0,
        failing_purges: int = 0,
        purge_counts: Sequence[int] = (),
    ) -> None:
        super().__init__(run_store=run_store)
        self.failing_claims = failing_claims
        self.failing_renewals = failing_renewals
        self.failing_purges = failing_purges
        # Worker-lease calls fail while "down" and block in their thread while "hung".
        self.lease_store = "up"
        self.unhung = threading.Event()
        self.claims = 0
        self.purges: list[tuple[tuple[int, ...], int, int]] = []
        self._purge_counts = list(purge_counts)

    def claim_work(self, worker_id: str, **kwargs: Any) -> WorkItem | None:
        self.claims += 1
        if self.failing_claims:
            self.failing_claims -= 1
            raise _store_error()
        return super().claim_work(worker_id, **kwargs)

    def _lease_store_call(self) -> None:
        if self.lease_store == "down":
            raise _store_error()
        if self.lease_store == "hung":
            self.unhung.wait()

    def acquire_worker_lease(self, name: str, worker_id: str, **kwargs: Any) -> bool:
        self._lease_store_call()
        return super().acquire_worker_lease(name, worker_id, **kwargs)

    def renew_worker_lease(self, name: str, worker_id: str, **kwargs: Any) -> bool:
        self._lease_store_call()
        if self.failing_renewals:
            self.failing_renewals -= 1
            raise _store_error()
        return super().renew_worker_lease(name, worker_id, **kwargs)

    def purge_finished(
        self, *, kinds: Sequence[int], finished_before: int, limit: int = 500
    ) -> int:
        self.purges.append((tuple(kinds), finished_before, limit))
        if self.failing_purges:
            self.failing_purges -= 1
            raise _store_error()
        if self._purge_counts:
            return self._purge_counts.pop(0)
        return super().purge_finished(kinds=kinds, finished_before=finished_before, limit=limit)


class FlakyRuns(FakeRunStore):
    """A fake run store whose next active-run listing fails once when asked to."""

    fail_next_listing = False

    def list_active_runs_all_workspaces(self, **kwargs: Any) -> list[CoralRun]:
        if self.fail_next_listing:
            self.fail_next_listing = False
            raise _store_error()
        return super().list_active_runs_all_workspaces(**kwargs)


def _effect(run_id: str, key: str, *, available_at: int = 0) -> WorkItemDraft:
    return WorkItemDraft.effect(
        run_id=run_id,
        idempotency_key=key,
        payload={"effect_type": _STEP},
        available_at=available_at,
    )


def _supervisor(
    run_store: FakeRunStore, queue: FakeQueueStore, time: VirtualTime, **kwargs: Any
) -> WorkerSupervisor:
    settings: dict[str, Any] = {
        "worker_id": "worker-1",
        "clock": time,
        "wait": time.wait,
        "resync_interval_s": None,
        "renew_interval_s": 10_000.0,
        # Idle workers wait this times the pool size, never a retry delay's length.
        "poll_interval_s": 0.1,
        **kwargs,
    }
    return WorkerSupervisor(run_store, queue, **settings)


async def _leading(supervisor: WorkerSupervisor) -> None:
    await asyncio.wait_for(supervisor.leader_ready_event.wait(), timeout=budget(10))


def _statuses(queue: FakeQueueStore, ids: Collection[str]) -> set[int]:
    return {item.status for item in queue.get_work(list(ids), workspace_id=1)}


async def test_four_workers_drain_four_runs_and_never_two_items_of_one_run() -> None:
    run_store = FakeRunStore()
    queue = FakeQueueStore(run_store=run_store)
    keys = [("run-a", "a1"), ("run-a", "a2"), ("run-b", "b1"), ("run-b", "b2")]
    keys += [("run-c", "c1"), ("run-d", "d1")]
    drafts = {key: _effect(run_id, key) for run_id, key in keys}
    queue.enqueue_work(list(drafts.values()), workspace_id=1, now=int(_START))
    blocked_run = asyncio.Event()
    other_runs = asyncio.Event()
    running: Counter[str] = Counter()
    peak: Counter[str] = Counter()
    started: list[str] = []
    finished: list[str] = []

    async def _step(ctx: ExecutionContext) -> EffectCompleted:
        running[ctx.run_id] += 1
        peak[ctx.run_id] = max(peak[ctx.run_id], running[ctx.run_id])
        started.append(ctx.run_id)
        try:
            await (blocked_run if ctx.run_id == "run-a" else other_runs).wait()
        finally:
            running[ctx.run_id] -= 1
        return EffectCompleted()

    async def _on_finished(work: FinishedWork) -> None:
        finished.append(work.item.id)

    time = VirtualTime(_START)
    register_executor(_STEP, _step)
    try:
        async with _supervisor(
            run_store, queue, time, drain_concurrency=4, on_finished=_on_finished
        ) as supervisor:
            await _leading(supervisor)
            # One item of each run is in flight; run-a's second waits behind its first.
            await poll_until_async(
                lambda: set(running.elements()) == {"run-a", "run-b", "run-c", "run-d"},
                timeout_s=budget(10),
            )
            assert sorted(started) == ["run-a", "run-b", "run-c", "run-d"]

            # The blocked run does not stop the others: run-b's second item drains too.
            other_runs.set()
            await poll_until_async(lambda: len(finished) == 4, timeout_s=budget(10))
            assert set(finished) == {drafts[key].id for key in ("b1", "b2", "c1", "d1")}
            assert (running["run-a"], started.count("run-a")) == (1, 1)

            blocked_run.set()
            await poll_until_async(lambda: len(finished) == 6, timeout_s=budget(10))
    finally:
        unregister_executor(_STEP, _step)

    assert set(peak.values()) == {1}
    assert _statuses(queue, [draft.id for draft in drafts.values()]) == {int(WorkStatus.SUCCEEDED)}


async def test_an_item_reclaimed_while_in_flight_keeps_its_run_excluded_until_it_returns() -> None:
    run_store = FakeRunStore()
    queue = FakeQueueStore(run_store=run_store)
    slow = _effect("run-a", "a1")
    later = _effect("run-a", "a2", available_at=int(_START) + 1)
    other = _effect("run-b", "b1", available_at=int(_START) + 1)
    queue.enqueue_work([slow, later, other], workspace_id=1, now=int(_START))
    release = asyncio.Event()
    running: Counter[str] = Counter()
    peak: Counter[str] = Counter()
    started: list[str] = []
    finished: list[str] = []

    async def _step(ctx: ExecutionContext) -> EffectCompleted:
        running[ctx.run_id] += 1
        peak[ctx.run_id] = max(peak[ctx.run_id], running[ctx.run_id])
        started.append(ctx.work.id)
        try:
            if started == [slow.id]:
                await release.wait()
        finally:
            running[ctx.run_id] -= 1
        return EffectCompleted()

    async def _on_finished(work: FinishedWork) -> None:
        finished.append(work.item.id)

    time = VirtualTime(_START)
    register_executor(_STEP, _step)
    try:
        async with _supervisor(
            run_store,
            queue,
            time,
            drain_concurrency=2,
            work_lease_seconds=60,
            lease_seconds=100_000,
            renew_interval_s=10.0,
            on_finished=_on_finished,
        ) as supervisor:
            await _leading(supervisor)
            await poll_until_async(lambda: started == [slow.id] and time.waiting(0.2))
            # The renewal loop reclaims the expired item while its executor still runs.
            time.advance(60)
            await poll_until_async(
                lambda: _statuses(queue, [slow.id, later.id]) == {int(WorkStatus.PENDING)}
            )
            # A claim after the reclaim still skips both of run-a's items.
            await poll_until_async(lambda: time.waiting(0.2))
            time.advance(1)
            await poll_until_async(lambda: time.waiting(0.2))
            assert (started, finished, running["run-a"]) == ([slow.id, other.id], [other.id], 1)

            # Its fenced finish calls no hook; then the run's items run again, one at a time.
            release.set()
            await poll_until_async(lambda: len(finished) == 3, timeout_s=budget(10))
    finally:
        unregister_executor(_STEP, _step)

    assert started == [slow.id, other.id, slow.id, later.id]
    assert finished == [other.id, slow.id, later.id]
    assert set(peak.values()) == {1}
    assert [item.attempts for item in queue.get_work([slow.id], workspace_id=1)] == [2]


async def test_a_lost_worker_lease_cancels_items_in_flight_and_stops_claiming() -> None:
    run_store = FakeRunStore()
    queue = FakeQueueStore(run_store=run_store)
    first = _effect("run-a", "a1")
    queue.enqueue_work([first], workspace_id=1, now=int(_START))
    started: list[str] = []
    cancelled: list[str] = []
    finished: list[str] = []

    async def _step(ctx: ExecutionContext) -> EffectCompleted:
        started.append(ctx.work.id)
        if len(started) == 1:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(ctx.work.id)
                raise
        return EffectCompleted()

    async def _on_finished(work: FinishedWork) -> None:
        finished.append(work.item.id)

    time = VirtualTime(_START)
    register_executor(_STEP, _step)
    try:
        async with _supervisor(
            run_store,
            queue,
            time,
            lease_seconds=100,
            renew_interval_s=10.0,
            work_lease_seconds=60,
            standby_retry_s=50.0,
            on_finished=_on_finished,
        ) as supervisor:
            await _leading(supervisor)
            await poll_until_async(lambda: started == [first.id] and time.waiting(10.0))
            # Another replica holds the lease, so the next renewal fails and the epoch ends.
            queue.worker_leases[DEFAULT_WORKER_LEASE_NAME] = (
                "worker-2",
                int(_START),
                int(_START) + 200,
            )
            time.advance(10)
            await poll_until_async(lambda: time.waiting(50.0), timeout_s=budget(10))
            assert (cancelled, supervisor.is_leader) == ([first.id], False)

            # In standby nothing is claimed; the cancelled item keeps its lease.
            second = _effect("run-b", "b1")
            queue.enqueue_work([second], workspace_id=1, now=int(time.now))
            for _ in range(3):
                time.advance(50)
                await poll_until_async(lambda: time.waiting(50.0), timeout_s=budget(10))
            assert _statuses(queue, [first.id]) == {int(WorkStatus.CLAIMED)}
            assert (_statuses(queue, [second.id]), finished) == ({int(WorkStatus.PENDING)}, [])

            # Once the other lease expires this replica leads again and re-runs the item.
            time.advance(50)
            await poll_until_async(lambda: len(finished) == 2, timeout_s=budget(10))
    finally:
        unregister_executor(_STEP, _step)

    assert sorted(finished) == sorted([first.id, second.id])
    assert [item.attempts for item in queue.get_work([first.id], workspace_id=1)] == [2]


async def test_a_failing_claim_is_logged_and_retried_after_a_growing_delay(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_store = FakeRunStore()
    queue = FlakyQueue(run_store=run_store, failing_claims=6)
    draft = _effect("run-a", "a1")
    queue.enqueue_work([draft], workspace_id=1, now=int(_START))
    finished: list[str] = []

    async def _step(ctx: ExecutionContext) -> EffectCompleted:
        return EffectCompleted()

    async def _on_finished(work: FinishedWork) -> None:
        finished.append(work.item.id)

    caplog.set_level(logging.WARNING, logger="coral.workers.supervisor")
    time = VirtualTime(_START)
    register_executor(_STEP, _step)
    try:
        async with _supervisor(
            run_store, queue, time, drain_concurrency=1, on_finished=_on_finished
        ) as supervisor:
            await _leading(supervisor)
            # 1 s after the first failure in a row, doubling up to 30 s.
            for delay in (1.0, 2.0, 4.0, 8.0, 16.0, 30.0):
                await poll_until_async(lambda delay=delay: time.waiting(delay))
                time.advance(delay)
            await poll_until_async(lambda: finished == [draft.id], timeout_s=budget(10))
            assert supervisor.is_leader
    finally:
        unregister_executor(_STEP, _step)

    failures = [r.getMessage() for r in caplog.records if "drain worker" in r.getMessage()]
    assert len(failures) == 6
    assert all("OperationalError" in message for message in failures)
    assert _SENTINEL not in caplog.text


async def test_an_item_in_flight_outlives_an_hour_of_leadership() -> None:
    run_store = FakeRunStore()
    queue = FakeQueueStore(run_store=run_store)
    draft = _effect("run-a", "a1")
    queue.enqueue_work([draft], workspace_id=1, now=int(_START))
    release = asyncio.Event()
    started: list[str] = []
    cancelled: list[str] = []

    async def _step(ctx: ExecutionContext) -> EffectCompleted:
        started.append(ctx.work.id)
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.append(ctx.work.id)
            raise
        return EffectCompleted()

    time = VirtualTime(_START)
    register_executor(_STEP, _step)
    try:
        async with _supervisor(
            run_store,
            queue,
            time,
            lease_seconds=7200,
            work_lease_seconds=7200,
            renew_interval_s=30.0,
        ) as supervisor:
            await _leading(supervisor)
            await poll_until_async(lambda: started == [draft.id], timeout_s=budget(10))

            time.advance(3601)
            renewed_at = int(_START + 3601)
            await poll_until_async(
                lambda: queue.worker_leases[DEFAULT_WORKER_LEASE_NAME][1] == renewed_at,
                timeout_s=budget(10),
            )
            assert supervisor.is_leader
            assert (cancelled, _statuses(queue, [draft.id])) == ([], {int(WorkStatus.CLAIMED)})

            release.set()
            await poll_until_async(
                lambda: _statuses(queue, [draft.id]) == {int(WorkStatus.SUCCEEDED)},
                timeout_s=budget(10),
            )
    finally:
        unregister_executor(_STEP, _step)

    [done] = queue.get_work([draft.id], workspace_id=1)
    assert (done.attempts, started, cancelled) == (1, [draft.id], [])


def _start_run(run_store: FakeRunStore, title: str, status: RunStatus | None = None) -> str:
    run = run_store.start_run(
        RunStartSpec(workflow_id="wf", version_id="v1", title=title, request_preview="req"),
        now=int(_START),
    )
    if status is not None:
        run_store.apply_transition(
            run.id,
            1,
            Transition(
                status=int(status),
                pause_reason=int(RunPauseReason.USER) if status is RunStatus.PAUSED else None,
            ),
            now=int(_START),
        )
    return run.id


async def test_the_resync_task_reconciles_active_runs_each_interval_and_purges_hourly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_store = FlakyRuns()
    queue = FlakyQueue(run_store=run_store, purge_counts=(500, 500, 3))
    active = [
        _start_run(run_store, "Starting"),
        _start_run(run_store, "Paused", RunStatus.PAUSED),
    ]
    _start_run(run_store, "Completed", RunStatus.COMPLETED)
    reconciled: list[str] = []

    async def _reconcile(run: CoralRun) -> None:
        reconciled.append(run.id)

    def swept(times: int) -> bool:
        """Whether each active run, and only those, was reconciled ``times`` times."""
        return Counter(reconciled) == Counter(dict.fromkeys(active, times))

    async def tick(seconds: float, *, expected_sweeps: int) -> None:
        time.advance(seconds)
        await poll_until_async(lambda: swept(expected_sweeps), timeout_s=budget(10))
        await poll_until_async(lambda: time.waiting(600.0), timeout_s=budget(10))

    caplog.set_level(logging.WARNING, logger="coral.workers.supervisor")
    time = VirtualTime(_START)
    kinds = (int(WorkKind.SIGNAL), int(WorkKind.TIMER))
    retention = 86_400
    async with _supervisor(
        run_store,
        queue,
        time,
        run_reconciler=_reconcile,
        resync_interval_s=600.0,
        retention_s=retention,
        lease_seconds=100_000,
    ) as supervisor:
        await _leading(supervisor)
        # The startup sweep reconciles each active run once; the task waits an interval.
        assert swept(1)
        await poll_until_async(lambda: time.waiting(600.0), timeout_s=budget(10))
        assert queue.purges == []

        # The first tick sweeps and purges until a batch is short.
        await tick(600, expected_sweeps=2)
        first_cutoff = int(_START + 600) - retention
        assert queue.purges == [(kinds, first_cutoff, 500)] * 3

        # A store error in the next sweep is logged; the task retries after 1 s.
        run_store.fail_next_listing = True
        time.advance(600)
        await poll_until_async(lambda: time.waiting(1.0), timeout_s=budget(10))
        assert swept(2)
        await tick(1, expected_sweeps=3)

        # Ticks within the hour after the first purge do not purge again; the next one does.
        for expected_sweeps in (4, 5, 6, 7):
            await tick(600, expected_sweeps=expected_sweeps)
        assert len(queue.purges) == 3
        await tick(600, expected_sweeps=8)
        assert supervisor.is_leader

    assert queue.purges[3:] == [(kinds, int(_START + 4201) - retention, 500)]
    failures = [r.getMessage() for r in caplog.records if "resync" in r.getMessage()]
    assert len(failures) == 1 and "OperationalError" in failures[0]
    assert _SENTINEL not in caplog.text


async def _stray_cancellation() -> None:
    """Await a future someone else cancelled, which raises ``CancelledError`` here."""
    future = asyncio.get_running_loop().create_future()
    future.cancel()
    await future


async def test_idle_workers_poll_the_queue_once_per_poll_interval() -> None:
    run_store = FakeRunStore()
    queue = FlakyQueue(run_store=run_store)
    time = VirtualTime(_START)
    async with _supervisor(run_store, queue, time, drain_concurrency=4) as supervisor:
        await _leading(supervisor)
        # Each of the four idle workers waits four poll intervals between claims.
        await poll_until_async(lambda: time.waiting(0.4, count=4), timeout_s=budget(10))
        assert queue.claims == 4
        for rounds in (1, 2, 3):
            time.advance(0.4)
            await poll_until_async(
                lambda rounds=rounds: (
                    queue.claims == 4 + 4 * rounds and time.waiting(0.4, count=4)
                ),
                timeout_s=budget(10),
            )


async def test_a_failed_lease_renewal_is_retried_and_leadership_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_store = FakeRunStore()
    queue = FlakyQueue(run_store=run_store, failing_renewals=1)
    finished: list[str] = []

    async def _step(ctx: ExecutionContext) -> EffectCompleted:
        return EffectCompleted()

    async def _on_finished(work: FinishedWork) -> None:
        finished.append(work.item.id)

    caplog.set_level(logging.WARNING, logger="coral.workers.supervisor")
    time = VirtualTime(_START)
    register_executor(_STEP, _step)
    try:
        async with _supervisor(
            run_store,
            queue,
            time,
            drain_concurrency=1,
            lease_seconds=120,
            renew_interval_s=30.0,
            on_finished=_on_finished,
        ) as supervisor:
            await _leading(supervisor)
            await poll_until_async(lambda: time.waiting(30.0), timeout_s=budget(10))
            time.advance(30)
            await poll_until_async(lambda: time.waiting(1.0), timeout_s=budget(10))
            time.advance(1)
            await poll_until_async(
                lambda: queue.worker_leases[DEFAULT_WORKER_LEASE_NAME][1] == int(_START) + 31,
                timeout_s=budget(10),
            )
            # Still leading, and the pool still drains.
            draft = _effect("run-a", "a1")
            queue.enqueue_work([draft], workspace_id=1, now=int(time.now))
            time.advance(0.1)
            await poll_until_async(lambda: finished == [draft.id], timeout_s=budget(10))
            assert supervisor.is_leader
    finally:
        unregister_executor(_STEP, _step)

    failures = [r.getMessage() for r in caplog.records if "renewal failed" in r.getMessage()]
    assert failures == [
        "Coral worker lease renewal failed (1 in a row): OperationalError (orig Exception)"
    ]
    assert _SENTINEL not in caplog.text


@pytest.mark.parametrize(
    ("lease_store", "waits"),
    [
        # Renewals fail and are retried until a quarter of the lease is left (+90 s).
        ("down", (30.0, 1.0, 2.0, 4.0, 8.0, 16.0, 29.0)),
        # A renewal that never returns is given up at the same point.
        ("hung", (30.0, 60.0)),
    ],
)
async def test_a_replica_that_cannot_renew_steps_down_before_another_can_lead(
    lease_store: str, waits: tuple[float, ...], caplog: pytest.LogCaptureFixture
) -> None:
    run_store = FakeRunStore()
    first_queue = FlakyQueue(run_store=run_store)
    second_queue = FakeQueueStore(run_store=run_store)
    second_queue.worker_leases = first_queue.worker_leases
    draft = _effect("run-a", "a1")
    first_queue.enqueue_work([draft], workspace_id=1, now=int(_START))
    seen: list[tuple[str, str, float]] = []

    async def _step(ctx: ExecutionContext) -> EffectCompleted:
        seen.append((ctx.worker_id, "started", time.now))
        if ctx.worker_id == "worker-1":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                seen.append((ctx.worker_id, "cancelled", time.now))
                raise
        return EffectCompleted()

    caplog.set_level(logging.WARNING, logger="coral.workers.supervisor")
    time = VirtualTime(_START)
    leases = {"lease_seconds": 120, "standby_retry_s": 7.0}
    first = _supervisor(run_store, first_queue, time, renew_interval_s=30.0, **leases)
    second = _supervisor(run_store, second_queue, time, worker_id="worker-2", **leases)
    register_executor(_STEP, _step)
    try:
        async with first:
            await _leading(first)
            await poll_until_async(lambda: len(seen) == 1, timeout_s=budget(10))
            async with second:
                await poll_until_async(lambda: time.waiting(7.0), timeout_s=budget(10))
                first_queue.lease_store = lease_store
                for delay in waits:
                    await poll_until_async(
                        lambda delay=delay: time.waiting(delay), timeout_s=budget(10)
                    )
                    time.advance(delay)
                await poll_until_async(
                    lambda: len(seen) == 2 and not first.leader_ready_event.is_set(),
                    timeout_s=budget(10),
                )
                assert not first.is_leader

                # The other replica leads only once the lease has expired, and re-runs the item.
                time.advance(35)
                await poll_until_async(
                    lambda: _statuses(first_queue, [draft.id]) == {int(WorkStatus.SUCCEEDED)},
                    timeout_s=budget(10),
                )
                assert (first.is_leader, second.is_leader) == (False, True)
    finally:
        first_queue.unhung.set()
        unregister_executor(_STEP, _step)

    assert seen == [
        ("worker-1", "started", _START),
        ("worker-1", "cancelled", _START + 90),
        ("worker-2", "started", _START + 125),
    ]
    assert "stepping down" in caplog.text
    assert _SENTINEL not in caplog.text


class _Crash(BaseException):
    """Ends the task it is raised in: nothing in the supervisor catches it."""


async def test_a_drain_worker_that_dies_restarts_leadership(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_store = FakeRunStore()
    queue = FakeQueueStore(run_store=run_store)
    crashing = _effect("run-a", "a1")
    later = _effect("run-b", "b1", available_at=int(_START) + 1)
    queue.enqueue_work([crashing, later], workspace_id=1, now=int(_START))
    finished: list[str] = []

    async def _step(ctx: ExecutionContext) -> EffectCompleted:
        if ctx.work.id == crashing.id:
            raise _Crash()
        return EffectCompleted()

    async def _on_finished(work: FinishedWork) -> None:
        finished.append(work.item.id)

    caplog.set_level(logging.WARNING, logger="coral.workers.supervisor")
    time = VirtualTime(_START)
    register_executor(_STEP, _step)
    try:
        async with _supervisor(
            run_store, queue, time, drain_concurrency=1, on_finished=_on_finished
        ) as supervisor:
            await _leading(supervisor)
            # The epoch ends and leadership restarts after the first retry delay.
            await poll_until_async(lambda: time.waiting(1.0), timeout_s=budget(10))
            assert not supervisor.leader_ready_event.is_set()
            time.advance(1)
            await poll_until_async(lambda: finished == [later.id], timeout_s=budget(10))
            assert supervisor.is_leader and supervisor.leader_ready_event.is_set()
    finally:
        unregister_executor(_STEP, _step)

    assert "Coral leader task coral-drain-worker-0 ended: _Crash; restarting leadership" in (
        caplog.text
    )
    assert _statuses(queue, [crashing.id]) == {int(WorkStatus.CLAIMED)}


async def test_a_stray_cancellation_fails_its_item_and_the_worker_keeps_draining(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_store = FakeRunStore()
    queue = FakeQueueStore(run_store=run_store)
    first, second, third = (
        _effect(run_id, key, available_at=int(_START) - offset)
        for run_id, key, offset in (("run-a", "a1", 3), ("run-b", "b1", 2), ("run-c", "c1", 1))
    )
    queue.enqueue_work([first, second, third], workspace_id=1, now=int(_START))
    calls: Counter[str] = Counter()
    finished: list[str] = []

    async def _step(ctx: ExecutionContext) -> EffectCompleted:
        calls[ctx.work.id] += 1
        if ctx.work.id == first.id and calls[first.id] == 1:
            await _stray_cancellation()
        return EffectCompleted()

    async def _on_finished(work: FinishedWork) -> None:
        finished.append(work.item.id)
        if work.item.id == second.id:
            await _stray_cancellation()

    caplog.set_level(logging.WARNING, logger="coral")
    time = VirtualTime(_START)
    register_executor(_STEP, _step)
    try:
        async with _supervisor(
            run_store, queue, time, drain_concurrency=1, on_finished=_on_finished
        ) as supervisor:
            await _leading(supervisor)
            await poll_until_async(lambda: finished == [second.id, third.id], timeout_s=budget(10))
            [retried] = queue.get_work([first.id], workspace_id=1)
            assert (retried.status, retried.attempts, retried.error_code) == (
                int(WorkStatus.PENDING),
                1,
                "executor.cancelled",
            )
            # The same worker runs the retry once it is due.
            time.advance(2)
            await poll_until_async(lambda: len(finished) == 3, timeout_s=budget(10))
            assert supervisor.is_leader
    finally:
        unregister_executor(_STEP, _step)

    assert finished == [second.id, third.id, first.id]
    assert "leader task" not in caplog.text
    messages = [record.getMessage() for record in caplog.records]
    assert f"Work finished hook failed for work_id={second.id}: CancelledError" in messages
    assert (
        f"Unhandled exception in effect executor for work_id={first.id}: CancelledError"
        in messages
    )


async def test_a_failing_purge_and_a_purge_backlog_wait_for_later_ticks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_store = FakeRunStore()
    queue = FlakyQueue(run_store=run_store, failing_purges=1, purge_counts=[500] * 25)
    _start_run(run_store, "Running", RunStatus.RUNNING)
    reconciled: list[str] = []

    async def _reconcile(run: CoralRun) -> None:
        reconciled.append(run.id)

    caplog.set_level(logging.WARNING, logger="coral.workers.supervisor")
    time = VirtualTime(_START)
    async with _supervisor(
        run_store,
        queue,
        time,
        run_reconciler=_reconcile,
        resync_interval_s=600.0,
        lease_seconds=100_000,
    ) as supervisor:
        await _leading(supervisor)
        # Per tick: sweeps so far, purge calls so far.
        for sweeps, purge_calls in ((2, 1), (3, 21), (4, 27), (5, 27)):
            await poll_until_async(lambda: time.waiting(600.0), timeout_s=budget(10))
            time.advance(600)
            await poll_until_async(
                lambda sweeps=sweeps: len(reconciled) == sweeps and time.waiting(600.0),
                timeout_s=budget(10),
            )
            assert len(queue.purges) == purge_calls
        assert supervisor.is_leader

    failures = [r.getMessage() for r in caplog.records if "purge failed" in r.getMessage()]
    assert failures == [
        "Coral retention purge failed (1 in a row): OperationalError (orig Exception)"
    ]
    assert "resync task failed" not in caplog.text
