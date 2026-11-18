"""Integration tests for SqlAlchemyCoralQueueStore, FakeQueueStore, and WorkDrainer."""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select

from coral.db import WorkRow, coral_engine, ensure_coral_schema
from coral.db.enum_codecs import RunStatus, WorkKind, WorkStatus
from coral.queue import (
    EffectCompleted,
    EffectFailed,
    ExecutionContext,
    SqlAlchemyCoralQueueStore,
    StartupLeaseLost,
    WorkDrainer,
    clear_executors,
    register_executor,
)
from coral.slots.executors import CANCEL_SESSIONS
from coral.stores.fakes import FakeQueueStore
from coral.stores.protocols import (
    AgentSlotDraft,
    QueueStore,
    RunStartSpec,
    Transition,
    WorkItem,
    WorkItemDraft,
)
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.stores.work_rows import MIN_HOLD_DELAY_S


def test_queue_enqueue_claim_renew_finish_reclaim_lifecycle(db_uri: str) -> None:
    """Verify enqueue idempotency, claim ordering, expired-lease rejection, finish, and reclaim."""
    ensure_coral_schema(db_uri)
    q = SqlAlchemyCoralQueueStore(db_uri, default_workspace_id=1)
    assert isinstance(q, QueueStore)

    eff1 = WorkItemDraft.effect(
        run_id="run_q1",
        idempotency_key="eff:1",
        payload={"effect_type": "git.prepare", "step": 1},
        available_at=100,
    )
    eff1_dup = WorkItemDraft.effect(
        run_id="run_q1",
        idempotency_key="eff:1",
        payload={"effect_type": "git.prepare", "step": 999},
        available_at=100,
    )
    eff2 = WorkItemDraft.effect(
        run_id="run_q1",
        idempotency_key="eff:2",
        payload={"effect_type": "git.prepare", "step": 2},
        available_at=200,
    )
    sig1 = WorkItemDraft.signal(
        run_id="run_q1",
        idempotency_key="sig:1",
        payload={"signal": "wake"},
        available_at=90,
    )
    timer1 = WorkItemDraft.timer(
        run_id="run_q1",
        idempotency_key="tmr:1",
        available_at=150,
        payload={"timer": "deadline"},
    )

    q.enqueue_work([eff1, eff1_dup, eff2, sig1, timer1], workspace_id=1, now=100)

    # Ready signals and due timers discovery
    signals = q.discover_ready_signals(workspace_id=1, now=100)
    assert [s.id for s in signals] == [sig1.id]
    assert q.discover_due_timers(workspace_id=1, now=120) == []
    timers = q.discover_due_timers(workspace_id=1, now=150)
    assert [t.id for t in timers] == [timer1.id]

    ready_effects = q.discover_ready_effects(workspace_id=1, now=150)
    assert [e.id for e in ready_effects] == [eff1.id]
    assert '"step": 1' in ready_effects[0].payload

    # Claim at t=50 (before available_at=100) returns None
    assert q.claim_work("w1", workspace_id=1, now_fn=lambda: 50.0) is None

    # Claim at t=120 claims eff1 (eff2 available at 200 is not yet due)
    claimed1 = q.claim_work("w1", workspace_id=1, lease_seconds=60, now_fn=lambda: 120.0)
    assert claimed1 is not None
    assert claimed1.id == eff1.id
    assert claimed1.attempts == 1
    assert claimed1.status == int(WorkStatus.CLAIMED)
    assert claimed1.lease_holder == "w1"
    assert claimed1.lease_expires_at == 180

    # Second claim at t=120 returns None since eff1 is CLAIMED and eff2 is due at 200
    assert q.claim_work("w2", workspace_id=1, now_fn=lambda: 120.0) is None

    # Renew with wrong worker fails
    assert not q.renew_lease(
        claimed1.id, worker_id="w2", lease_seconds=60, workspace_id=1, now_fn=lambda: 150.0
    )

    # Renew while active succeeds and advances lease_expires_at to 150 + 60 = 210
    assert q.renew_lease(
        claimed1.id, worker_id="w1", lease_seconds=60, workspace_id=1, now_fn=lambda: 150.0
    )

    # Late heartbeat after expiry (t=210 or t=220) MUST NOT revive an expired claim
    assert not q.renew_lease(
        claimed1.id, worker_id="w1", lease_seconds=60, workspace_id=1, now_fn=lambda: 210.0
    )
    assert not q.renew_lease(
        claimed1.id, worker_id="w1", lease_seconds=60, workspace_id=1, now_fn=lambda: 220.0
    )

    # Expired effect is visible in discover_expired_effects
    expired = q.discover_expired_effects(workspace_id=1, now=220)
    assert [e.id for e in expired] == [claimed1.id]

    # Reclaim expired work resets status to PENDING without resetting attempts or cksum
    reclaimed_count = q.reclaim_expired_work(workspace_id=1, now_fn=lambda: 220.0)
    assert reclaimed_count == 1

    # Re-claiming eff1 increments attempts to 2
    claimed1_retry = q.claim_work("w2", workspace_id=1, lease_seconds=60, now_fn=lambda: 225.0)
    assert claimed1_retry is not None
    assert claimed1_retry.id == eff1.id
    assert claimed1_retry.attempts == 2
    assert claimed1_retry.lease_holder == "w2"
    assert claimed1_retry.lease_expires_at == 285

    # Stale worker w1 with old expected_lease_expires_at=210 cannot finish the work
    assert not q.finish_work(
        claimed1.id,
        worker_id="w1",
        expected_lease_expires_at=210,
        status=int(WorkStatus.SUCCEEDED),
        workspace_id=1,
        now_fn=lambda: 230.0,
    )

    # Active worker w2 with matching expected_lease_expires_at=285 finishes the work
    assert q.finish_work(
        claimed1_retry.id,
        worker_id="w2",
        expected_lease_expires_at=285,
        status=int(WorkStatus.SUCCEEDED),
        result={"commit": "abc123"},
        workspace_id=1,
        now_fn=lambda: 230.0,
    )


def test_worker_replica_leases_db_and_fake(db_uri: str) -> None:
    """Verify singleton worker replica lease acquisition, renewal, expiry takeover, and release."""
    ensure_coral_schema(db_uri)
    for store in (
        SqlAlchemyCoralQueueStore(db_uri, default_workspace_id=1),
        FakeQueueStore(default_workspace_id=1),
    ):
        assert store.acquire_worker_lease(
            "coral.primary", "rep-1", lease_seconds=120, now_fn=lambda: 1000.0
        )
        # Second replica rejected while lease is active
        assert not store.acquire_worker_lease(
            "coral.primary", "rep-2", lease_seconds=120, now_fn=lambda: 1050.0
        )
        # Holder renews at t=1030 -> expires at 1150
        assert store.renew_worker_lease(
            "coral.primary", "rep-1", lease_seconds=120, now_fn=lambda: 1030.0
        )
        # Non-holder cannot renew
        assert not store.renew_worker_lease(
            "coral.primary", "rep-2", lease_seconds=120, now_fn=lambda: 1040.0
        )
        # Late renewal at t=1150 (expired) fails
        assert not store.renew_worker_lease(
            "coral.primary", "rep-1", lease_seconds=120, now_fn=lambda: 1150.0
        )
        # Takeover by rep-2 at t=1150 succeeds
        assert store.acquire_worker_lease(
            "coral.primary", "rep-2", lease_seconds=120, now_fn=lambda: 1150.0
        )
        # Release by wrong holder fails; release by rep-2 succeeds
        assert not store.release_worker_lease("coral.primary", "rep-1")
        assert store.release_worker_lease("coral.primary", "rep-2")
        # Immediate re-acquisition by rep-1 succeeds after release
        assert store.acquire_worker_lease(
            "coral.primary", "rep-1", lease_seconds=120, now_fn=lambda: 1160.0
        )


async def test_work_drainer_fencing_backoff_and_scope(db_uri: str) -> None:
    """Verify WorkDrainer terminal-run fencing, stale slot fencing, backoff, and scopes."""
    ensure_coral_schema(db_uri)
    run_store = SqlAlchemyCoralRunStore(db_uri, default_workspace_id=1)
    queue_store = SqlAlchemyCoralQueueStore(db_uri, default_workspace_id=1)

    clear_executors()
    executed_ids: list[str] = []
    entered_scopes: list[tuple[int, str | None, str | None]] = []

    class RecordingScopeRunner:
        @contextlib.asynccontextmanager
        async def run_scope(
            self,
            *,
            workspace_id: int,
            run_id: str | None = None,
            user_id: str | None = None,
            account_generation: str | None = None,
            host_id: str | None = None,
            owner_key: str | None = None,
        ) -> AsyncIterator[None]:
            entered_scopes.append((workspace_id, run_id, owner_key))
            yield

    try:
        # 1. Terminal run fencing: work item for COMPLETED run is marked ABANDONED
        term_run = run_store.start_run(
            RunStartSpec(
                workflow_id="wf_d",
                version_id="v1",
                title="Terminal Run",
                request_preview="req",
                workspace_id=1,
            ),
            now=100,
        )
        run_store.apply_transition(
            term_run.id,
            1,
            Transition(status=int(RunStatus.COMPLETED), finished_at=110),
            workspace_id=1,
            now=110,
        )
        w_term = WorkItemDraft.effect(
            run_id=term_run.id,
            idempotency_key="eff:term",
            payload={"effect_type": "test.ok"},
            available_at=100,
        )
        queue_store.enqueue_work([w_term], workspace_id=1, now=110)

        async def _ok_exec(ctx: ExecutionContext) -> EffectCompleted:
            await ctx.ensure_lease()
            executed_ids.append(ctx.work.id)
            return EffectCompleted(result={"ok": True})

        register_executor("test.ok", _ok_exec)

        now_val = 120.0
        drainer = WorkDrainer(
            queue_store,
            worker_id="drainer-1",
            scope_runner=RecordingScopeRunner(),
            workspace_id=1,
            clock=lambda: now_val,
            rng=lambda: 0.5,
        )
        drained = await drainer.drain_once()
        assert drained is not None and drained.id == w_term.id
        assert executed_ids == []

        engine = coral_engine(db_uri)
        with engine.connect() as conn:
            row = conn.execute(select(WorkRow).where(WorkRow.id == w_term.id)).one()
            assert row.status == int(WorkStatus.ABANDONED)
            assert row.error_code == "run.terminal"

        # 2. Stale slot generation fencing: slot at gen=2 abandons work with slot_generation=1
        active_run = run_store.start_run(
            RunStartSpec(
                workflow_id="wf_d",
                version_id="v1",
                title="Active Run",
                request_preview="req",
                workspace_id=1,
            ),
            now=100,
        )
        run_store.apply_transition(
            active_run.id,
            1,
            Transition(
                status=int(RunStatus.RUNNING),
                agent_slots=(
                    AgentSlotDraft(
                        id="slot_1",
                        activation_id="act_1",
                        node_id="n1",
                        scope_key="root",
                        roster_index=0,
                        role=1,
                        session_generation=2,
                    ),
                ),
            ),
            workspace_id=1,
            now=110,
        )
        w_stale_slot = WorkItemDraft.effect(
            run_id=active_run.id,
            idempotency_key="eff:stale_slot",
            payload={"effect_type": "test.ok", "slot_id": "slot_1"},
            slot_generation=1,
            owner_key="slot:slot_1",
            available_at=100,
        )
        w_valid_slot = WorkItemDraft.effect(
            run_id=active_run.id,
            idempotency_key="eff:valid_slot",
            payload={"effect_type": "test.ok", "slot_id": "slot_1"},
            slot_generation=2,
            owner_key="slot:slot_1",
            available_at=101,
        )
        queue_store.enqueue_work([w_stale_slot, w_valid_slot], workspace_id=1, now=110)

        await drainer.drain_until_empty()
        assert executed_ids == [w_valid_slot.id]
        assert entered_scopes == [(1, active_run.id, "slot:slot_1")]

        with engine.connect() as conn:
            stale_row = conn.execute(select(WorkRow).where(WorkRow.id == w_stale_slot.id)).one()
            valid_row = conn.execute(select(WorkRow).where(WorkRow.id == w_valid_slot.id)).one()
            assert stale_row.status == int(WorkStatus.ABANDONED)
            assert stale_row.error_code == "slot.generation_mismatch"
            assert valid_row.status == int(WorkStatus.SUCCEEDED)

        # 3. Transient retry backoff up to max_attempts=8 -> infra.transient
        async def _flaky_exec(ctx: ExecutionContext) -> EffectFailed:
            await ctx.ensure_lease()
            return EffectFailed(error_code="net.timeout", message="timed out", retryable=True)

        register_executor("test.flaky", _flaky_exec)
        w_flaky = WorkItemDraft.effect(
            run_id=active_run.id,
            idempotency_key="eff:flaky",
            payload={"effect_type": "test.flaky"},
            available_at=120,
        )
        queue_store.enqueue_work([w_flaky], workspace_id=1, now=120)

        for attempt in range(1, 8):
            item = await drainer.drain_once()
            assert item is not None
            assert item.attempts == attempt
            with engine.connect() as conn:
                r = conn.execute(select(WorkRow).where(WorkRow.id == w_flaky.id)).one()
                assert r.status == int(WorkStatus.PENDING)
                assert r.available_at > now_val
                now_val = float(r.available_at)

        # 8th attempt exhausts retries -> FAILED with error_code="infra.transient"
        item8 = await drainer.drain_once()
        assert item8 is not None and item8.attempts == 8
        with engine.connect() as conn:
            r8 = conn.execute(select(WorkRow).where(WorkRow.id == w_flaky.id)).one()
            assert r8.status == int(WorkStatus.FAILED)
            assert r8.error_code == "infra.transient"

        # 4. StartupLeaseLost leaves item unclaimed/uncommitted by the stale worker
        async def _lost_lease_exec(ctx: ExecutionContext) -> EffectCompleted:
            raise StartupLeaseLost("lease lost mid-flight")

        register_executor("test.lease_lost", _lost_lease_exec)
        w_lost = WorkItemDraft.effect(
            run_id=active_run.id,
            idempotency_key="eff:lost",
            payload={"effect_type": "test.lease_lost"},
            available_at=int(now_val),
        )
        queue_store.enqueue_work([w_lost], workspace_id=1, now=int(now_val))
        await drainer.drain_once()
        with engine.connect() as conn:
            r_lost = conn.execute(select(WorkRow).where(WorkRow.id == w_lost.id)).one()
            assert r_lost.status == int(WorkStatus.CLAIMED)
    finally:
        clear_executors()


async def test_work_drainer_runs_wind_down_effects_of_a_cancelled_run(db_uri: str) -> None:
    """A cancelled run's cancel_sessions item still runs; other effects and stale slots do not."""
    ensure_coral_schema(db_uri)
    run_store = SqlAlchemyCoralRunStore(db_uri, default_workspace_id=1)
    queue_store = SqlAlchemyCoralQueueStore(db_uri, default_workspace_id=1)
    run = run_store.start_run(
        RunStartSpec(
            workflow_id="wf_d",
            version_id="v1",
            title="Cancelled Run",
            request_preview="req",
            workspace_id=1,
        ),
        now=100,
    )
    slot = AgentSlotDraft(
        id="slot_1",
        activation_id="act_1",
        node_id="n1",
        scope_key="root",
        roster_index=0,
        role=1,
        session_generation=2,
    )
    run_store.apply_transition(
        run.id,
        1,
        Transition(status=int(RunStatus.RUNNING), agent_slots=(slot,)),
        workspace_id=1,
        now=105,
    )
    # cancel_run marks the run cancelled in the transition that enqueues cancel_sessions.
    run_store.apply_transition(
        run.id,
        2,
        Transition(status=int(RunStatus.CANCELLED), finished_at=110),
        workspace_id=1,
        now=110,
    )
    cancel = WorkItemDraft.effect(
        run_id=run.id,
        idempotency_key="eff:cancel",
        payload={"effect_type": CANCEL_SESSIONS, "slot_id": "slot_1"},
        slot_generation=2,
        owner_key="slot:slot_1",
        available_at=100,
    )
    other = WorkItemDraft.effect(
        run_id=run.id,
        idempotency_key="eff:other",
        payload={"effect_type": "test.ok"},
        available_at=101,
    )
    stale_cancel = WorkItemDraft.effect(
        run_id=run.id,
        idempotency_key="eff:stale_cancel",
        payload={"effect_type": CANCEL_SESSIONS, "slot_id": "slot_1"},
        slot_generation=1,
        owner_key="slot:slot_1",
        available_at=102,
    )
    queue_store.enqueue_work([cancel, other, stale_cancel], workspace_id=1, now=110)
    executed: list[str] = []

    async def _record(ctx: ExecutionContext) -> EffectCompleted:
        executed.append(ctx.work.id)
        return EffectCompleted()

    clear_executors()
    try:
        register_executor(CANCEL_SESSIONS, _record, runs_after_terminal=True)
        register_executor("test.ok", _record)
        drainer = WorkDrainer(
            queue_store, worker_id="drainer-1", workspace_id=1, clock=lambda: 120.0
        )

        assert await drainer.drain_until_empty() == 3
    finally:
        clear_executors()

    assert executed == [cancel.id]
    with coral_engine(db_uri).connect() as conn:
        rows = {
            row.id: (row.status, row.error_code)
            for row in conn.execute(select(WorkRow).where(WorkRow.run_id == run.id))
        }
    assert rows == {
        cancel.id: (int(WorkStatus.SUCCEEDED), None),
        other.id: (int(WorkStatus.ABANDONED), "run.terminal"),
        stale_cancel.id: (int(WorkStatus.ABANDONED), "slot.generation_mismatch"),
    }


# ── Holds, claim exclusion, rescheduling and retention (SQL and fake) ──────────

_WS = 7
_NOW = 1_700_000_000
_WORKER = "worker-1"


@pytest.fixture(params=["sql", "fake"])
def queue(request: pytest.FixtureRequest) -> QueueStore:
    if request.param == "sql":
        return SqlAlchemyCoralQueueStore(request.getfixturevalue("coral_db_uri"))
    return FakeQueueStore()


def _signal(run_id: str, key: str, *, available_at: int = 0) -> WorkItemDraft:
    return WorkItemDraft.signal(
        run_id=run_id, idempotency_key=key, payload={}, available_at=available_at
    )


def _claim(queue: QueueStore, at: int, *, workspace_id: int = _WS, **kwargs: Any) -> WorkItem:
    item = queue.claim_work(
        _WORKER,
        kinds=(int(WorkKind.SIGNAL), int(WorkKind.TIMER), int(WorkKind.EFFECT)),
        workspace_id=workspace_id,
        now_fn=lambda: float(at),
        **kwargs,
    )
    assert item is not None
    return item


def _finish(
    queue: QueueStore,
    item: WorkItem,
    status: WorkStatus,
    at: int,
    *,
    workspace_id: int = _WS,
    **kwargs: Any,
) -> None:
    assert item.lease_expires_at is not None
    assert queue.finish_work(
        item.id,
        worker_id=_WORKER,
        expected_lease_expires_at=item.lease_expires_at,
        status=int(status),
        workspace_id=workspace_id,
        now_fn=lambda: float(at),
        **kwargs,
    )


def _one(queue: QueueStore, draft: WorkItemDraft, *, workspace_id: int = _WS) -> WorkItem:
    [item] = queue.get_work([draft.id], workspace_id=workspace_id)
    return item


def test_claim_skips_items_of_excluded_runs(queue: QueueStore) -> None:
    busy = _signal("run-busy", "first", available_at=_NOW - 10)
    free = _signal("run-free", "second", available_at=_NOW)
    queue.enqueue_work([busy, free], workspace_id=_WS, now=_NOW)

    assert _claim(queue, _NOW, exclude_run_ids=("run-busy",)).id == free.id
    assert (
        queue.claim_work(
            _WORKER,
            kinds=(int(WorkKind.SIGNAL),),
            workspace_id=_WS,
            now_fn=lambda: float(_NOW),
            exclude_run_ids=("run-busy",),
        )
        is None
    )
    assert _claim(queue, _NOW).id == busy.id


def test_hold_repends_without_spending_an_attempt_and_keeps_its_start(
    queue: QueueStore,
) -> None:
    draft = _signal("run-1", "held")
    queue.enqueue_work([draft], workspace_id=_WS, now=_NOW)

    for at in (_NOW, _NOW + 300, _NOW + 600):
        claimed = _claim(queue, at)
        assert claimed.attempts == 1
        _finish(
            queue,
            claimed,
            WorkStatus.PENDING,
            at,
            error_code="run.paused",
            next_available_at=at + 300,
            hold=True,
        )
        held = _one(queue, draft)
        assert (held.status, held.attempts, held.available_at) == (
            int(WorkStatus.PENDING),
            0,
            at + 300,
        )
        assert (held.held_since, held.error_code, held.finished_at) == (_NOW, "run.paused", None)

    # A hold needs the item re-pended; the claim is left as it was.
    claimed = _claim(queue, _NOW + 900)
    with pytest.raises(ValueError, match="hold"):
        queue.finish_work(
            claimed.id,
            worker_id=_WORKER,
            expected_lease_expires_at=claimed.lease_expires_at or 0,
            status=int(WorkStatus.FAILED),
            workspace_id=_WS,
            now_fn=lambda: float(_NOW + 900),
            hold=True,
        )
    assert _one(queue, draft) == claimed

    # A retry past the horizon spends an attempt but keeps the first refusal's time,
    # so the horizon is not restarted by the next hold.
    _finish(
        queue,
        claimed,
        WorkStatus.PENDING,
        _NOW + 900,
        error_code="session.not_ready",
        next_available_at=_NOW + 910,
    )
    retried = _one(queue, draft)
    assert (retried.held_since, retried.attempts) == (_NOW, 1)
    claimed = _claim(queue, _NOW + 910)
    _finish(queue, claimed, WorkStatus.PENDING, _NOW + 910, error_code="run.paused", hold=True)
    assert _one(queue, draft).held_since == _NOW
    _finish(queue, _claim(queue, _NOW + 920), WorkStatus.SUCCEEDED, _NOW + 920)
    done = _one(queue, draft)
    assert (done.status, done.held_since, done.finished_at) == (
        int(WorkStatus.SUCCEEDED),
        None,
        _NOW + 920,
    )


@pytest.mark.parametrize("status", [WorkStatus.FAILED, WorkStatus.ABANDONED])
def test_a_finish_ends_the_hold(queue: QueueStore, status: WorkStatus) -> None:
    draft = _signal("run-1", "held")
    queue.enqueue_work([draft], workspace_id=_WS, now=_NOW)
    _finish(queue, _claim(queue, _NOW), WorkStatus.PENDING, _NOW, error_code="x", hold=True)

    _finish(queue, _claim(queue, _NOW + 60), status, _NOW + 60, error_code="x")

    assert _one(queue, draft).held_since is None


def test_a_hold_is_never_due_sooner_than_the_minimum_delay(queue: QueueStore) -> None:
    draft = _signal("run-1", "held")
    queue.enqueue_work([draft], workspace_id=_WS, now=_NOW)

    # No delay, then one in the past: neither makes the item claimable at once.
    for next_available_at in (None, _NOW - 60):
        at = _NOW if next_available_at is None else _NOW + 10
        _finish(
            queue,
            _claim(queue, at),
            WorkStatus.PENDING,
            at,
            error_code="run.paused",
            next_available_at=next_available_at,
            hold=True,
        )
        assert _one(queue, draft).available_at == at + MIN_HOLD_DELAY_S
        assert (
            queue.claim_work(
                _WORKER,
                kinds=(int(WorkKind.SIGNAL),),
                workspace_id=_WS,
                now_fn=lambda at=at: float(at + MIN_HOLD_DELAY_S - 1),
            )
            is None
        )


def test_get_work_reads_only_the_callers_workspace(queue: QueueStore) -> None:
    first = _signal("run-1", "first")
    second = _signal("run-1", "second")
    queue.enqueue_work([first, second], workspace_id=_WS, now=_NOW)
    queue.enqueue_work([first], workspace_id=_WS + 1, now=_NOW)

    assert {item.id for item in queue.get_work([second.id, first.id], workspace_id=_WS)} == {
        first.id,
        second.id,
    }
    assert [item.workspace_id for item in queue.get_work([first.id], workspace_id=_WS + 1)] == [
        _WS + 1
    ]
    assert queue.get_work([second.id], workspace_id=_WS + 1) == []
    assert queue.get_work([], workspace_id=_WS) == []


def test_reschedule_inserts_repends_finished_rows_and_keeps_the_earlier_time(
    queue: QueueStore,
) -> None:
    draft = _signal("run-1", "resync")

    queue.reschedule_work(draft, workspace_id=_WS, available_at=_NOW + 900)
    inserted = _one(queue, draft)
    assert (inserted.status, inserted.attempts, inserted.available_at) == (
        int(WorkStatus.PENDING),
        0,
        _NOW + 900,
    )
    # A pending row keeps the earlier time: a later call never delays it.
    queue.reschedule_work(draft, workspace_id=_WS, available_at=_NOW + 960)
    assert _one(queue, draft).available_at == _NOW + 900
    queue.reschedule_work(draft, workspace_id=_WS, available_at=_NOW)
    assert _one(queue, draft).available_at == _NOW

    # A claimed row belongs to its worker.
    claimed = _claim(queue, _NOW)
    queue.reschedule_work(draft, workspace_id=_WS, available_at=_NOW - 60)
    assert _one(queue, draft) == claimed

    for status, at in (
        (WorkStatus.SUCCEEDED, _NOW),
        (WorkStatus.FAILED, _NOW + 60),
        (WorkStatus.ABANDONED, _NOW + 120),
    ):
        if status is not WorkStatus.SUCCEEDED:
            claimed = _claim(queue, at)
        _finish(queue, claimed, status, at, error_code="code", result={"r": 1})
        queue.reschedule_work(draft, workspace_id=_WS, available_at=at + 60)
        repended = _one(queue, draft)
        assert repended == dataclasses.replace(
            repended,
            status=int(WorkStatus.PENDING),
            attempts=0,
            available_at=at + 60,
            error_code=None,
            result=None,
            finished_at=None,
            held_since=None,
            lease_holder=None,
            lease_expires_at=None,
        )
    assert len(queue.get_work([draft.id], workspace_id=_WS)) == 1
    assert queue.get_work([draft.id], workspace_id=_WS + 1) == []


def test_purge_finished_deletes_old_finished_signal_and_timer_rows_in_batches(
    queue: QueueStore,
) -> None:
    cutoff = _NOW
    old = cutoff - 100

    def finished(
        draft: WorkItemDraft, status: WorkStatus, at: int, workspace_id: int = _WS
    ) -> None:
        queue.enqueue_work([draft], workspace_id=workspace_id, now=at)
        claimed = _claim(queue, at, workspace_id=workspace_id)
        assert claimed.id == draft.id
        _finish(queue, claimed, status, at, workspace_id=workspace_id)

    purged = [
        _signal("run-1", "succeeded"),
        WorkItemDraft.timer(run_id="run-1", idempotency_key="failed timer", available_at=0),
        _signal("run-1", "abandoned"),
    ]
    finished(purged[0], WorkStatus.SUCCEEDED, old)
    finished(purged[1], WorkStatus.FAILED, old)
    finished(purged[2], WorkStatus.ABANDONED, old)
    other_workspace = _signal("run-9", "other workspace")
    finished(other_workspace, WorkStatus.SUCCEEDED, old, workspace_id=_WS + 1)
    effect = WorkItemDraft.effect(run_id="run-1", idempotency_key="effect", payload={})
    finished(effect, WorkStatus.SUCCEEDED, old)
    recent = _signal("run-1", "recent")
    finished(recent, WorkStatus.SUCCEEDED, cutoff)
    claimed = _signal("run-1", "claimed")
    queue.enqueue_work([claimed], workspace_id=_WS, now=old)
    _claim(queue, old)
    pending = _signal("run-1", "pending", available_at=_NOW + 3600)
    queue.enqueue_work([pending], workspace_id=_WS, now=old)

    kinds = (int(WorkKind.SIGNAL), int(WorkKind.TIMER))
    batches = [
        queue.purge_finished(kinds=kinds, finished_before=cutoff, limit=3) for _ in range(3)
    ]

    assert batches == [3, 1, 0]
    kept = [effect, recent, claimed, pending]
    assert {
        item.id for item in queue.get_work([d.id for d in purged + kept], workspace_id=_WS)
    } == {draft.id for draft in kept}
    assert queue.get_work([other_workspace.id], workspace_id=_WS + 1) == []
    assert queue.purge_finished(kinds=(), finished_before=cutoff) == 0


def test_effect_rows_are_never_rescheduled_or_purged(queue: QueueStore) -> None:
    effect = WorkItemDraft.effect(run_id="run-1", idempotency_key="effect", payload={})
    queue.enqueue_work([effect], workspace_id=_WS, now=_NOW)
    _finish(queue, _claim(queue, _NOW), WorkStatus.SUCCEEDED, _NOW)
    before = _one(queue, effect)

    with pytest.raises(ValueError, match="not effects"):
        queue.reschedule_work(effect, workspace_id=_WS, available_at=_NOW + 60)
    with pytest.raises(ValueError, match="keeps effect rows"):
        queue.purge_finished(
            kinds=(int(WorkKind.SIGNAL), int(WorkKind.EFFECT)), finished_before=_NOW + 60
        )
    assert _one(queue, effect) == before


def test_claim_breaks_ties_by_id(queue: QueueStore) -> None:
    drafts = [_signal("run-1", key) for key in ("one", "two", "three", "four")]
    queue.enqueue_work(drafts, workspace_id=_WS, now=_NOW)

    claimed = [_claim(queue, _NOW).id for _ in drafts]

    assert claimed == sorted(draft.id for draft in drafts)
