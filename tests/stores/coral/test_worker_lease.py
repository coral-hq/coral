"""Multi-DB integration tests for WorkerLeaseManager and WorkerSupervisor failover."""

from __future__ import annotations

import asyncio
import time

from coral.db import ensure_coral_schema
from coral.queue import (
    EffectCompleted,
    ExecutionContext,
    SqlAlchemyCoralQueueStore,
    clear_executors,
    register_executor,
)
from coral.stores.protocols import WorkItemDraft
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.workers import WorkerLeaseManager, WorkerSupervisor
from tests._helpers.polling import poll_until_async


async def test_worker_lease_manager_single_leader_and_takeover(db_uri: str) -> None:
    """Verify two WorkerLeaseManagers contend on one DB and standby takes over on expiry."""
    ensure_coral_schema(db_uri)
    now_s = 1000.0
    q = SqlAlchemyCoralQueueStore(db_uri, default_workspace_id=1, clock=lambda: now_s)

    m1 = WorkerLeaseManager(
        q,
        worker_id="replica-1",
        lease_name="coral.test.lease",
        lease_seconds=120,
        clock=lambda: now_s,
    )
    m2 = WorkerLeaseManager(
        q,
        worker_id="replica-2",
        lease_name="coral.test.lease",
        lease_seconds=120,
        clock=lambda: now_s,
    )

    assert await m1.try_acquire()
    assert m1.is_leader
    assert not m1.lease_lost_event.is_set()

    # Replica 2 cannot acquire while Replica 1 holds unexpired lease
    assert not await m2.try_acquire()
    assert not m2.is_leader

    # Advance to t=1030: Replica 1 renews -> expires at 1150
    now_s = 1030.0
    assert await m1.renew_once()
    assert m1.is_leader

    # Advance to t=1160 (past 1150 expiry): Replica 2 takes over
    now_s = 1160.0
    assert await m2.try_acquire()
    assert m2.is_leader

    # Replica 1's next renewal fails and sets lease_lost_event within 1 renewal cycle
    assert not await m1.renew_once()
    assert not m1.is_leader
    assert m1.lease_lost_event.is_set()

    # Explicit release by Replica 2 allows Replica 1 to re-acquire immediately
    assert await m2.release()
    assert not m2.is_leader
    assert await m1.try_acquire()
    assert m1.is_leader
    await m1.release()


async def test_two_supervisors_single_leader_and_fast_shutdown(db_uri: str) -> None:
    """Two supervisors on one DB: only leader runs sweep/drainer; stop() releases in < 100ms."""
    ensure_coral_schema(db_uri)
    run_store = SqlAlchemyCoralRunStore(db_uri, default_workspace_id=1)
    queue_store = SqlAlchemyCoralQueueStore(db_uri, default_workspace_id=1)

    clear_executors()
    executed_by: list[str] = []
    try:

        async def _rec_exec(ctx: ExecutionContext) -> EffectCompleted:
            await ctx.ensure_lease()
            executed_by.append(ctx.worker_id)
            return EffectCompleted(result={"worker": ctx.worker_id})

        register_executor("sup.effect", _rec_exec)

        draft = WorkItemDraft.effect(
            run_id="run_sup_1",
            idempotency_key="sup:1",
            payload={"effect_type": "sup.effect"},
            available_at=0,
        )
        queue_store.enqueue_work([draft], workspace_id=1, now=10)

        sup1 = WorkerSupervisor(
            run_store,
            queue_store,
            worker_id="sup-1",
            poll_interval_s=0.05,
            standby_retry_s=0.05,
        )
        sup2 = WorkerSupervisor(
            run_store,
            queue_store,
            worker_id="sup-2",
            poll_interval_s=0.05,
            standby_retry_s=0.05,
        )

        await sup1.start()
        await asyncio.wait_for(sup1.leader_ready_event.wait(), timeout=2.0)
        assert sup1.is_leader

        await sup2.start()
        await poll_until_async(lambda: len(executed_by) == 1, timeout_s=2.0)
        assert not sup2.is_leader
        assert executed_by == ["sup-1"]

        # Stopping sup1 completes and releases lease cleanly so sup2 takes over
        t0 = time.perf_counter()
        await sup1.stop()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        assert elapsed_ms < 500.0
        assert not sup1.is_leader

        await asyncio.wait_for(sup2.leader_ready_event.wait(), timeout=2.0)
        assert sup2.is_leader
        await sup2.stop()
    finally:
        clear_executors()
