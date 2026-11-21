"""The bridge's own executors, its hold policy and its thread pool, alone and behind a drainer."""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import itertools
import json
import threading
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from coral.bridge.codec import decode_entries
from coral.bridge.config import HOLD_RULES, HOST_WAIT_HOLDS
from coral.bridge.executors import (
    BRIDGE_THREAD_NAME,
    BoundedThreads,
    BridgeThreads,
    PoolClosed,
    bridge_hold_policy,
    crosses_host_wait,
    run_resync_executor,
    timer_executor,
)
from coral.bridge.mapping import (
    NEXT_RESYNC_AT,
    RUN_RESYNC,
    TIMER,
    MappedPayloadTooLarge,
    UnsupportedStance,
    resync_draft,
    timer_draft,
)
from coral.bridge.service import EngineBridge, ResyncReport
from coral.db.enum_codecs import LogKind, RunPauseReason, RunStatus, WorkKind, WorkStatus
from coral.engine.types import PauseRun, SessionFailed, Timer, TimerDue
from coral.model.ids import anchor_session_id, effect_session_id
from coral.queue import executors as queue_executors
from coral.queue.drainer import WorkDrainer
from coral.queue.executors import (
    EffectCompleted,
    EffectFailed,
    EffectOutcome,
    ExecutionContext,
    register_executor,
    unregister_executor,
)
from coral.recovery.drift import DriftDetected, DriftFinding, DriftPauser
from coral.slots.executors import CREATE_SESSION, create_session_executor
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import WorkItem, WorkItemDraft
from tests.budgets import budget
from tests.coral.bridge._world import (
    IMPLEMENT,
    USER,
    WORKSPACE,
    World,
    finished,
    row_of,
    settle,
    start,
    start_without_engine,
)
from tests.coral.omni.fakes import FakeSessionFacade
from tests.coral.workspace._executor_fakes import RecordingScopeRunner

FAILED_TURN = SessionFailed(
    slot_id=IMPLEMENT, failure_class="infra.transient", cause="529", fact_key="turn:s:1:msg:a"
)
WORKER = "worker-1"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


@pytest.fixture
async def threads(world: World) -> AsyncIterator[BridgeThreads]:
    pool = BridgeThreads(world.bridge)
    try:
        yield pool
    finally:
        pool.close()


def _context(item: WorkItem) -> ExecutionContext:
    return ExecutionContext(
        work=item, workspace_id=item.workspace_id, run_id=item.run_id, worker_id=WORKER
    )


def _armed_timer(world: World) -> tuple[str, Timer]:
    """A two-step run whose implementer's turn failed, so its backoff ladder is armed."""
    run = start(world)
    created = {"session_id": "s" * 32, "role": "step", "generation": 1}
    create = row_of(world, run.id, "create_session", engine_kind="create_session")
    world.bridge.feed(finished(settle(world, create, WorkStatus.SUCCEEDED, result=created)))
    sent = {"session_id": "s" * 32, "stable_id": "m1"}
    brief = row_of(world, run.id, "send_input")
    world.bridge.feed(finished(settle(world, brief, WorkStatus.SUCCEEDED, result=sent)))
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run.id, inputs=lambda _snapshot: (FAILED_TURN,)
    )
    state = world.assert_fold_matches(run.id)
    return run.id, min(state.timers, key=lambda timer: timer.due_at)


def _timer_row(world: World, run_id: str, timer: Timer) -> WorkItem:
    (row,) = world.queue.get_work([timer_draft(run_id, timer).id], workspace_id=WORKSPACE)
    return row


def _timer_dues(world: World, run_id: str) -> list[str]:
    """The keys of the timers the run's engine log has fired."""
    world.assert_fold_matches(run_id)
    return [
        entry.input.timer_key
        for entry in decode_entries(world.engine_log(run_id))
        if isinstance(entry.input, TimerDue)
    ]


def _paused_rows(world: World, run_id: str) -> list[dict[str, Any]]:
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    return [
        json.loads(row.body)
        for row in runs.logs[(WORKSPACE, run_id)]
        if row.kind == int(LogKind.PAUSED)
    ]


def _corrupt_engine_log(world: World, run_id: str) -> None:
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    logs = runs.logs[(WORKSPACE, run_id)]
    logs[0] = dataclasses.replace(logs[0], body='{"seq": "not an entry"}')


# ── timer ────────────────────────────────────────────────────────────────────


async def test_a_timer_is_held_before_its_due_time_and_fires_at_it(
    world: World, threads: BridgeThreads
) -> None:
    run_id, timer = _armed_timer(world)
    row = _timer_row(world, run_id, timer)
    execute = timer_executor(threads)

    early = await execute(_context(row))
    assert isinstance(early, EffectFailed)
    assert (early.error_code, early.retryable) == ("timer.early", True)
    assert bridge_hold_policy(row, early, world.clock.epoch) == 5
    assert _timer_dues(world, run_id) == []

    world.clock.now = timer.due_at
    fired = await execute(_context(row))
    assert fired == EffectCompleted()
    assert _timer_dues(world, run_id) == [timer.key]
    # Stage one re-prompts the failed slot.
    assert row_of(world, run_id, "send_input", engine_kind="nudge") is not None


async def test_a_drained_timer_row_that_comes_early_is_held_not_spent(
    world: World, threads: BridgeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drainer whose clock runs ahead of the bridge's claims the row early; it waits."""
    monkeypatch.setattr(queue_executors, "_EXECUTORS", {})
    register_executor(TIMER, timer_executor(threads))
    run_id, timer = _armed_timer(world)
    ahead = 3.0
    drainer = WorkDrainer(
        world.queue,
        worker_id=WORKER,
        kinds=(int(WorkKind.TIMER),),
        clock=lambda: world.clock.now.timestamp() + ahead,
        hold_policy=bridge_hold_policy,
        on_finished=threads.feed,
    )
    world.clock.now = timer.due_at
    world.clock.advance(-ahead)

    assert await drainer.drain_once() is not None
    held = _timer_row(world, run_id, timer)
    assert (held.status, held.attempts, held.error_code) == (
        int(WorkStatus.PENDING),
        0,
        "timer.early",
    )
    assert _timer_dues(world, run_id) == []

    world.clock.advance(5)
    assert await drainer.drain_once() is not None
    assert _timer_row(world, run_id, timer).status == int(WorkStatus.SUCCEEDED)
    assert _timer_dues(world, run_id) == [timer.key]


async def test_a_stale_or_redelivered_timer_row_fires_nothing(
    world: World, threads: BridgeThreads
) -> None:
    run_id, timer = _armed_timer(world)
    execute = timer_executor(threads)
    # A row of an earlier arming: due by its own payload, while the timer now fires later.
    earlier = timer.model_copy(update={"due_at": timer.due_at - timedelta(seconds=10)})
    world.queue.enqueue_work(
        [timer_draft(run_id, earlier)], workspace_id=WORKSPACE, now=world.clock.epoch
    )
    world.clock.now = earlier.due_at
    version = world.run(run_id).version

    assert await execute(_context(_timer_row(world, run_id, earlier))) == EffectCompleted()
    assert (world.run(run_id).version, _timer_dues(world, run_id)) == (version, [])

    world.clock.now = timer.due_at
    current = _timer_row(world, run_id, timer)
    outcomes = [await execute(_context(current)) for _ in range(2)]

    # The redelivery finds the timer fired and disarmed: one TimerDue in one commit.
    assert outcomes == [EffectCompleted(), EffectCompleted()]
    assert (world.run(run_id).version, _timer_dues(world, run_id)) == (version + 1, [timer.key])


async def test_a_timer_whose_firing_cannot_be_committed_stays_armed_for_the_resync(
    world: World, threads: BridgeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, timer = _armed_timer(world)
    row = _timer_row(world, run_id, timer)
    world.clock.now = timer.due_at

    def refuse(*_args: object) -> None:
        raise UnsupportedStance("slot has no step stance")

    with monkeypatch.context() as patched:
        # The stage's re-prompt cannot be mapped, so its firing cannot be committed.
        patched.setattr("coral.bridge.commit.map_effect", refuse)
        outcome = await timer_executor(threads)(_context(row))

    # Not spent: the row fails, the run pauses visibly, and the timer is still armed.
    assert isinstance(outcome, EffectFailed)
    assert (outcome.error_code, outcome.retryable) == ("engine.commit_unbuildable", False)
    assert bridge_hold_policy(row, outcome, world.clock.epoch) is None
    assert _timer_dues(world, run_id) == []
    state = world.assert_fold_matches(run_id)
    assert [(cause.reason, cause.detail) for cause in state.causes] == [
        ("failure_path", "unsupported_stance")
    ]
    assert timer.key in {armed.key for armed in state.timers}
    # The drainer stores it failed; the resync revives the row of the still-armed timer.
    settle(world, row, WorkStatus.FAILED, error_code=outcome.error_code)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    revived = _timer_row(world, run_id, timer)
    assert (revived.status, revived.attempts) == (int(WorkStatus.PENDING), 0)


async def test_a_timer_of_a_run_that_cannot_be_loaded_fails_and_pauses_the_run_once(
    world: World,
) -> None:
    run_id, timer = _armed_timer(world)
    row = _timer_row(world, run_id, timer)
    world.clock.now = timer.due_at
    _corrupt_engine_log(world, run_id)
    # A process that has not folded the run yet reads the corrupt row.
    fresh = BridgeThreads(
        EngineBridge(
            run_store=world.runs,
            queue_store=world.queue,
            versions=world.versions,
            clock=world.clock,
        )
    )
    execute = timer_executor(fresh)
    try:
        outcomes = [await execute(_context(row)) for _ in range(2)]
    finally:
        fresh.close()

    # Failed, not spent: the resync revives the row of a still-armed timer once the run loads.
    assert all(
        isinstance(outcome, EffectFailed)
        and (outcome.error_code, outcome.retryable) == ("engine.load_failed", False)
        for outcome in outcomes
    )
    paused = world.run(run_id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    assert [body["detail"] for body in _paused_rows(world, run_id)] == ["engine.load_failed"]


@pytest.mark.parametrize(
    "payload",
    [
        {"effect_type": TIMER},
        {"effect_type": TIMER, "timer_key": "", "due_at": "2026-01-01T12:00:00+00:00"},
        {"effect_type": TIMER, "timer_key": "k", "due_at": "not a time"},
        {"effect_type": TIMER, "timer_key": "k", "due_at": "2026-01-01T12:00:00"},
        {"effect_type": TIMER, "timer_key": "k" * 513, "due_at": "2026-01-01T12:00:00+00:00"},
    ],
    ids=["missing", "empty_key", "bad_time", "naive_time", "long_key"],
)
async def test_an_unreadable_timer_payload_fails_permanently(
    world: World, threads: BridgeThreads, payload: dict[str, Any]
) -> None:
    run = start(world)
    row = dataclasses.replace(
        row_of(world, run.id, "create_session"),
        kind=int(WorkKind.TIMER),
        payload=json.dumps(payload),
    )

    outcome = await timer_executor(threads)(_context(row))

    assert isinstance(outcome, EffectFailed)
    assert (outcome.error_code, outcome.retryable) == ("effect.invalid_payload", False)


# ── run_resync ───────────────────────────────────────────────────────────────


def _resync_row(world: World, run_id: str) -> WorkItem:
    world.queue.enqueue_work([resync_draft(run_id)], workspace_id=WORKSPACE, now=world.clock.epoch)
    (row,) = world.queue.get_work([resync_draft(run_id).id], workspace_id=WORKSPACE)
    return row


async def test_the_resync_executor_repairs_its_run(world: World, threads: BridgeThreads) -> None:
    run = start_without_engine(world)

    outcome = await run_resync_executor(threads)(_context(_resync_row(world, run.id)))

    assert isinstance(outcome, EffectCompleted)
    assert outcome.result is not None and outcome.result["started"] is True
    assert world.run(run.id).status == int(RunStatus.RUNNING)
    assert row_of(world, run.id, "create_session") is not None
    world.assert_fold_matches(run.id)


async def test_the_resync_of_a_run_that_cannot_be_loaded_pauses_it_once_and_completes(
    world: World, threads: BridgeThreads
) -> None:
    run = start(world)
    _corrupt_engine_log(world, run.id)
    execute = run_resync_executor(threads)
    row = _resync_row(world, run.id)

    outcomes = [await execute(_context(row)) for _ in range(2)]

    assert outcomes == [EffectCompleted(), EffectCompleted()]
    assert [body["detail"] for body in _paused_rows(world, run.id)] == ["engine.load_failed"]
    assert world.run(run.id).pause_reason == int(RunPauseReason.FAILURE_PATH)


async def test_the_resync_of_a_missing_run_fails_permanently(
    world: World, threads: BridgeThreads
) -> None:
    run = start(world)
    row = dataclasses.replace(_resync_row(world, run.id), run_id="f" * 32)

    outcome = await run_resync_executor(threads)(_context(row))

    assert isinstance(outcome, EffectFailed)
    assert (outcome.error_code, outcome.retryable) == ("effect.run_missing", False)


@pytest.mark.parametrize("status", ["running", "paused", "cancelled"])
async def test_a_resync_with_nothing_to_repair_completes_without_writing(
    world: World, threads: BridgeThreads, status: str
) -> None:
    run = start(world)
    if status == "paused":
        world.bridge.commit_inputs(
            workspace_id=WORKSPACE,
            run_id=run.id,
            inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
        )
    elif status == "cancelled":
        world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    version = world.run(run.id).version
    row = _resync_row(world, run.id)

    outcomes = [await run_resync_executor(threads)(_context(row)) for _ in range(2)]

    assert outcomes == [EffectCompleted(result=dataclasses.asdict(ResyncReport()))] * 2
    assert world.run(run.id).version == version


class _RecordingLiveness:
    """A liveness check that records each run it checks and names a scripted time."""

    def __init__(self, due: int | None) -> None:
        self.due = due
        self.checked: list[tuple[int, str]] = []

    async def check_run(self, *, workspace_id: int, run_id: str) -> int | None:
        self.checked.append((workspace_id, run_id))
        return self.due


@pytest.mark.parametrize("due", [None, 1_900_000_000])
async def test_the_resync_checks_the_runs_runners_after_its_repair(
    world: World, threads: BridgeThreads, due: int | None
) -> None:
    run = start(world)
    liveness = _RecordingLiveness(due)

    outcome = await run_resync_executor(threads, liveness)(_context(_resync_row(world, run.id)))

    assert liveness.checked == [(WORKSPACE, run.id)]
    assert isinstance(outcome, EffectCompleted) and outcome.result is not None
    assert outcome.result.get(NEXT_RESYNC_AT) == due


async def test_a_resync_that_cannot_load_its_run_checks_no_runner(
    world: World, threads: BridgeThreads
) -> None:
    run = start(world)
    _corrupt_engine_log(world, run.id)
    liveness = _RecordingLiveness(1_900_000_000)

    outcome = await run_resync_executor(threads, liveness)(_context(_resync_row(world, run.id)))

    assert outcome == EffectCompleted()
    assert liveness.checked == []


@pytest.mark.parametrize(
    ("effect_type", "status", "rescheduled"),
    [
        (RUN_RESYNC, WorkStatus.SUCCEEDED, True),
        (RUN_RESYNC, WorkStatus.FAILED, False),
        (TIMER, WorkStatus.SUCCEEDED, False),
    ],
)
def test_a_finished_resync_that_names_its_next_time_is_due_again_then(
    world: World, effect_type: str, status: WorkStatus, rescheduled: bool
) -> None:
    run = start(world)
    row = _resync_row(world, run.id)
    due = world.clock.epoch + 90
    done = settle(world, row, status, result={NEXT_RESYNC_AT: due})
    if effect_type != RUN_RESYNC:
        done = dataclasses.replace(done, payload=json.dumps({"effect_type": effect_type}))

    world.bridge.feed(finished(done))

    (after,) = world.queue.get_work([resync_draft(run.id).id], workspace_id=WORKSPACE)
    if rescheduled:
        assert (after.status, after.available_at) == (int(WorkStatus.PENDING), due)
    else:
        assert after.status == int(status)


# ── hold policy ──────────────────────────────────────────────────────────────

NOW_S = 1_800_000_000


def _item(held_since: int | None = None, error_code: str | None = None) -> WorkItem:
    """A claimed row; ``error_code`` is the code its last hold or retry stored."""
    return WorkItem(
        workspace_id=WORKSPACE,
        id="w" * 32,
        run_id="r" * 32,
        kind=int(WorkKind.EFFECT),
        status=int(WorkStatus.CLAIMED),
        payload="{}",
        idempotency_cksum=b"\0" * 32,
        available_at=0,
        created_at_us=0,
        held_since=held_since,
        error_code=error_code,
    )


def _refusal(code: str, *, retryable: bool = True) -> EffectFailed:
    return EffectFailed(error_code=code, message="refused", retryable=retryable)


@pytest.mark.parametrize(
    ("code", "delay"),
    [
        ("run.paused", 300),
        ("drift.anchor_archived", 300),
        ("drift.session_deleted", 300),
        ("slot.close_blocked", 15),
        ("session.not_ready", 5),
        ("session.anchor_missing", 5),
        ("session.host_offline", 30),
        ("session.turn_state_unknown", 30),
        ("executor.missing", 60),
        ("signal.awaiting_effect", 5),
        ("timer.early", 5),
        ("recovery.host_offline", 30),
    ],
)
def test_a_domain_wait_is_held_from_its_first_refusal(code: str, delay: int) -> None:
    # Permanent drift failures are held like retryable waits: only the resume ends them.
    failure = _refusal(code, retryable=not code.startswith("drift."))
    assert bridge_hold_policy(_item(), failure, NOW_S) == delay
    assert bridge_hold_policy(_item(held_since=NOW_S - 600), failure, NOW_S) == delay


@pytest.mark.parametrize(
    "code", sorted(code for code, (_delay, horizon) in HOLD_RULES.items() if horizon is not None)
)
def test_a_hold_with_a_horizon_ends_that_long_after_its_first_refusal(code: str) -> None:
    delay, horizon = HOLD_RULES[code]
    # A runner the host calls alive is waited on for 10 minutes; other waits for 30.
    assert horizon == (600 if code == "recovery.runner_alive" else 1_800)
    held = _refusal(code)
    assert bridge_hold_policy(_item(NOW_S - horizon + 1, code), held, NOW_S) == delay
    assert bridge_hold_policy(_item(NOW_S - horizon, code), held, NOW_S) is None
    # Waiting on an offline host before it does not count toward this horizon...
    host_wait = (
        "session.host_offline" if code != "session.host_offline" else "recovery.host_offline"
    )
    assert bridge_hold_policy(_item(NOW_S - horizon, host_wait), held, NOW_S) == delay
    assert crosses_host_wait(_item(NOW_S - horizon, host_wait), code)
    # ...while a retry or a hold of any other code before it does, unless this code is a
    # wait for an offline host itself, which is measured from its own start.
    other = bridge_hold_policy(_item(NOW_S - horizon, "net.timeout"), held, NOW_S)
    assert other == (delay if code in HOST_WAIT_HOLDS else None)


@pytest.mark.parametrize(
    "code",
    [
        "run.paused",
        "drift.anchor_bound",
        "slot.close_blocked",
        "signal.awaiting_effect",
        "recovery.host_offline",
    ],
)
def test_a_hold_without_a_horizon_lasts_until_its_condition_ends(code: str) -> None:
    assert bridge_hold_policy(_item(held_since=NOW_S - 10**7), _refusal(code), NOW_S) is not None


@pytest.mark.parametrize(
    "code",
    [
        "infra.transient",
        "session.agent_not_supported",
        "effect.invalid_payload",
        "drift",
        "drift.some_future_cause",
    ],
)
def test_other_failures_take_the_normal_retry(code: str) -> None:
    assert bridge_hold_policy(_item(), _refusal(code), NOW_S) is None


async def test_a_missing_executor_is_held_for_30_minutes_then_pauses_the_run_infra(
    world: World, threads: BridgeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queue_executors, "_EXECUTORS", {})
    run = start(world)
    started = world.clock.epoch
    drainer = WorkDrainer(
        world.queue,
        worker_id=WORKER,
        clock=lambda: world.clock.now.timestamp(),
        rng=lambda: 0.5,
        hold_policy=bridge_hold_policy,
        on_finished=threads.feed,
    )

    def creates() -> list[WorkItem]:
        return [
            item
            for item in world.work(run.id)
            if json.loads(item.payload)["effect_type"] == CREATE_SESSION
        ]

    async def drain_due() -> None:
        while await drainer.drain_once() is not None:
            pass

    while world.clock.epoch < started + 1_740:
        await drain_due()
        world.clock.advance(60)
    # Held: no attempt spent and the run still running, 29 minutes in.
    assert {(item.status, item.attempts, item.held_since) for item in creates()} == {
        (int(WorkStatus.PENDING), 0, started)
    }
    assert world.run(run.id).status == int(RunStatus.RUNNING)

    for _ in range(200):
        await drain_due()
        if all(item.status == int(WorkStatus.FAILED) for item in creates()):
            break
        world.clock.advance(60)
    assert {
        (item.status, item.error_code, json.loads(item.result or "{}").get("last_error_code"))
        for item in creates()
    } == {(int(WorkStatus.FAILED), "infra.transient", "executor.missing")}
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.INFRA),
    )
    state = world.assert_fold_matches(run.id)
    assert {cause.reason for cause in state.causes} == {"infra"}
    assert ("infra", "anchor:executor.missing") in {
        (cause.reason, cause.detail) for cause in state.causes
    }


async def test_a_hold_written_after_the_resume_released_holds_is_released_by_the_resync(
    world: World, threads: BridgeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claimed while running, refused paused, resumed before the hold: the resync frees it."""
    monkeypatch.setattr(queue_executors, "_EXECUTORS", {})
    run = start(world)
    create = row_of(world, run.id, "create_session", engine_kind="create_session")

    async def paused_meanwhile(ctx: ExecutionContext) -> EffectOutcome:
        payload = json.loads(ctx.work.payload)
        if payload.get("role") == "anchor":
            return EffectCompleted({"session_id": "a" * 32, "role": "anchor", "generation": 1})
        # The run pauses and resumes while this item is claimed: the resume cannot release it.
        world.bridge.commit_inputs(
            workspace_id=WORKSPACE,
            run_id=run.id,
            inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
        )
        world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
        return EffectFailed(error_code="run.paused", message="paused", retryable=True)

    register_executor(CREATE_SESSION, paused_meanwhile)
    drainer = WorkDrainer(
        world.queue,
        worker_id=WORKER,
        clock=lambda: world.clock.now.timestamp(),
        hold_policy=bridge_hold_policy,
        on_finished=threads.feed,
    )
    while await drainer.drain_once() is not None:
        pass
    (held,) = world.queue.get_work([create.id], workspace_id=WORKSPACE)
    assert (held.status, held.error_code, held.available_at) == (
        int(WorkStatus.PENDING),
        "run.paused",
        world.clock.epoch + 300,
    )

    outcome = await run_resync_executor(threads)(_context(_resync_row(world, run.id)))

    assert isinstance(outcome, EffectCompleted)
    assert outcome.result is not None and outcome.result["released"] is True
    (released,) = world.queue.get_work([create.id], workspace_id=WORKSPACE)
    assert (released.available_at, released.held_since, released.attempts) == (
        world.clock.epoch,
        None,
        0,
    )


@pytest.mark.parametrize(
    "error",
    [UnsupportedStance("slot has no step stance"), MappedPayloadTooLarge("payload too large")],
    ids=["unsupported_stance", "payload_too_large"],
)
async def test_a_completion_whose_commit_cannot_be_built_pauses_the_run_instead_of_retrying(
    world: World,
    threads: BridgeThreads,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    """Fed through the drainer's hook: the item stays done and the run pauses visibly."""
    monkeypatch.setattr(queue_executors, "_EXECUTORS", {})
    run = start(world)
    create = row_of(world, run.id, "create_session", engine_kind="create_session")

    async def create_session(ctx: ExecutionContext) -> EffectOutcome:
        payload = json.loads(ctx.work.payload)
        if payload.get("role") == "anchor":
            return EffectCompleted({"session_id": "a" * 32, "role": "anchor", "generation": 1})
        return EffectCompleted({"session_id": "s" * 32, "role": "step", "generation": 1})

    def refuse(*_args: object) -> None:
        raise error

    register_executor(CREATE_SESSION, create_session)
    # The brief the completion emits cannot be mapped.
    monkeypatch.setattr("coral.bridge.commit.map_effect", refuse)
    drainer = WorkDrainer(
        world.queue,
        worker_id=WORKER,
        clock=lambda: world.clock.now.timestamp(),
        hold_policy=bridge_hold_policy,
        on_finished=threads.feed,
    )
    while await drainer.drain_once() is not None:
        pass

    (done,) = world.queue.get_work([create.id], workspace_id=WORKSPACE)
    assert (done.status, done.attempts) == (int(WorkStatus.SUCCEEDED), 1)
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    detail = "unsupported_stance" if isinstance(error, UnsupportedStance) else "payload_too_large"
    state = world.assert_fold_matches(run.id)
    assert [(cause.reason, cause.detail) for cause in state.causes] == [("failure_path", detail)]
    # A second feed of the same outcome changes nothing.
    version = world.run(run.id).version
    await threads.feed(finished(done))
    assert world.run(run.id).version == version
    unregister_executor(CREATE_SESSION, create_session)


class _RecordingAgents:
    """A ``StepAgentResolver`` answering one agent and recording who it resolved for."""

    def __init__(self) -> None:
        self.calls: set[tuple[object, ...]] = set()

    async def resolve(self, **step: Any) -> str:
        self.calls.add(tuple(sorted(step.items())))
        return "c" * 32


async def test_drift_a_mapped_create_finds_pauses_through_the_engine_until_it_is_gone(
    world: World, threads: BridgeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Held, never spent; resumed while the drift persists, the next create pauses it again."""
    monkeypatch.setattr(queue_executors, "_EXECUTORS", {})
    run = start(world)
    finding = DriftFinding("anchor_archived", anchor_session_id(WORKSPACE, run.id), "1700000000")
    facade = FakeSessionFacade(refusal=DriftDetected(finding))
    agents = _RecordingAgents()
    pauser = DriftPauser(world.runs, engine=threads)
    executor = create_session_executor(
        facade, world.runs, pauser, RecordingScopeRunner(), agents=agents
    )
    register_executor(CREATE_SESSION, executor)
    drainer = WorkDrainer(
        world.queue,
        worker_id=WORKER,
        kinds=(int(WorkKind.EFFECT),),
        clock=lambda: world.clock.now.timestamp(),
        hold_policy=bridge_hold_policy,
        on_finished=threads.feed,
    )

    def creates() -> set[tuple[int, int]]:
        return {
            (item.status, item.attempts)
            for item in world.work(run.id)
            if json.loads(item.payload)["effect_type"] == CREATE_SESSION
        }

    async def drain_due() -> None:
        while await drainer.drain_once() is not None:
            pass

    for pauses in (1, 2):
        await drain_due()
        paused = world.run(run.id)
        assert (paused.status, paused.pause_reason) == (
            int(RunStatus.PAUSED),
            int(RunPauseReason.DRIFT),
        )
        state = world.assert_fold_matches(run.id)
        assert [(cause.reason, cause.detail) for cause in state.causes] == [
            ("drift", "anchor_archived")
        ]
        assert len(_paused_rows(world, run.id)) == pauses
        assert creates() == {(int(WorkStatus.PENDING), 0)}
        world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")

    facade.refusal = None
    await drain_due()

    assert creates() == {(int(WorkStatus.SUCCEEDED), 1)}
    assert world.run(run.id).status == int(RunStatus.RUNNING)
    assert [slot.status for slot in world.assert_fold_matches(run.id).slots] == ["session_created"]
    # The mapped step create resolved its stance as the run owner's agent, for its session.
    create = row_of(world, run.id, "create_session", engine_kind="create_session")
    session_id = effect_session_id(WORKSPACE, json.loads(create.payload)["effect_key"])
    assert agents.calls == {
        (
            ("node_id", "implement"),
            ("owner", USER),
            ("roster_index", 0),
            ("session_id", session_id),
            ("stance", "implementer"),
            ("workflow_slug", "two-steps"),
            ("workspace_id", WORKSPACE),
        )
    }
    assert {request.agent_id for request in facade.requests if request.role == "step"} == {
        "c" * 32
    }


# ── thread pool ──────────────────────────────────────────────────────────────

_CALLER = contextvars.ContextVar[str]("caller")


async def test_bridge_calls_run_on_the_bridge_pool_with_the_callers_context(
    threads: BridgeThreads,
) -> None:
    _CALLER.set("drain-worker")

    def where() -> tuple[str, str]:
        return threading.current_thread().name, _CALLER.get()

    name, caller = await threads.run(where)

    assert name.startswith(BRIDGE_THREAD_NAME)
    assert caller == "drain-worker"


async def test_a_closed_pool_takes_no_more_calls(world: World) -> None:
    pool = BridgeThreads(world.bridge)
    pool.close()
    assert pool.closed
    with pytest.raises(RuntimeError):
        await pool.run(datetime.now)


async def test_a_call_waiting_for_a_thread_when_the_pool_closes_is_dropped_as_retryable() -> None:
    pool = BoundedThreads(max_workers=1, thread_name_prefix="test-pool")
    entered, release = threading.Event(), threading.Event()
    ran: list[str] = []

    def held() -> str:
        entered.set()
        assert release.wait(budget(10))
        return "ran"

    try:
        running = asyncio.create_task(pool.run(held))
        assert await asyncio.to_thread(entered.wait, budget(10))
        queued = asyncio.create_task(pool.run(ran.append, "queued"))
        await asyncio.sleep(0)
        pool.close()
    finally:
        release.set()

    # The running call finishes; the waiting one never runs and is retryable, not cancelled.
    assert await running == "ran"
    with pytest.raises(PoolClosed):
        await queued
    assert ran == []


async def test_a_cancelled_caller_of_a_waiting_call_is_still_cancelled() -> None:
    pool = BoundedThreads(max_workers=1, thread_name_prefix="test-pool")
    entered, release = threading.Event(), threading.Event()

    def held() -> None:
        entered.set()
        assert release.wait(budget(10))

    try:
        running = asyncio.create_task(pool.run(held))
        assert await asyncio.to_thread(entered.wait, budget(10))
        queued = asyncio.create_task(pool.run(datetime.now))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
    finally:
        release.set()
        pool.close()
    await running


async def test_the_reconciler_schedules_the_runs_resync_on_the_pool(
    world: World, threads: BridgeThreads
) -> None:
    run = start(world)

    await threads.schedule_resync(world.run(run.id))

    (row,) = world.queue.get_work([resync_draft(run.id).id], workspace_id=WORKSPACE)
    assert (row.status, row.available_at) == (int(WorkStatus.PENDING), world.clock.epoch)
    assert json.loads(row.payload) == {"effect_type": RUN_RESYNC}


async def test_two_horizon_codes_that_alternate_stay_bounded_by_the_first_holds_start(
    world: World, threads: BridgeThreads, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner the host calls alive, then a step not ready, then alive again, and so on."""
    monkeypatch.setattr(queue_executors, "_EXECUTORS", {})
    codes = itertools.cycle(["recovery.runner_alive", "session.not_ready"])

    async def refuse(_ctx: ExecutionContext) -> EffectFailed:
        return EffectFailed(error_code=next(codes), message="refused", retryable=True)

    register_executor("test.alternating", refuse)
    run = start(world)
    draft = WorkItemDraft.effect(
        run_id=run.id, idempotency_key="alternating", payload={"effect_type": "test.alternating"}
    )
    world.queue.enqueue_work([draft], workspace_id=WORKSPACE, now=world.clock.epoch)
    drainer = WorkDrainer(
        world.queue,
        worker_id=WORKER,
        kinds=(int(WorkKind.EFFECT),),
        clock=lambda: world.clock.now.timestamp(),
        rng=lambda: 0.5,
        hold_policy=bridge_hold_policy,
        hold_restart=crosses_host_wait,
    )
    started = world.clock.epoch
    seen: list[tuple[int, str | None, int, int | None]] = []
    while world.clock.epoch < started + 900:
        while await drainer.drain_once() is not None:
            pass
        [row] = world.queue.get_work([draft.id], workspace_id=WORKSPACE)
        seen.append((world.clock.epoch - started, row.error_code, row.attempts, row.held_since))
        world.clock.advance(30)

    # One start for both codes, so neither restarts the other's horizon.
    assert {held_since for _at, _code, _attempts, held_since in seen} == {started}
    # The alive hold ends ten minutes after the first hold: its refusals then spend attempts.
    assert all(attempts == 0 for at, _code, attempts, _since in seen if at < 600)
    assert seen[-1][2] > 0
