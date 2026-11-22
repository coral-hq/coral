"""The liveness pass and the wake: a working step's missing runner, lost and brought back.

The grace runs from this process's own first sighting of the runner missing. The wake
brings the runner back in its session through the relaunch path, holds the step while its
host is offline, and never supersedes a runner its host calls alive.

Tier A: the world's bridge on fake stores and its session side (the real executors and
drainer over the fake session server, whose runner liveness a test sets as the server
would report it). The clock is the world's.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import pytest

from coral.bridge.codec import decode_entries
from coral.bridge.mapping import NEXT_RESYNC_AT, RECOVERY_WAKE, resync_draft
from coral.bridge.service import EngineBridge
from coral.db.enum_codecs import WorkStatus
from coral.engine.lifecycle import retryable_activations
from coral.engine.types import (
    CancelRun,
    EffectCompleted,
    InfraBackoffExhausted,
    PauseRun,
    ResumeRun,
    RetryStep,
    RunnerHeld,
    RunnerHoldEnded,
    RunnerLost,
    SessionFailed,
    Slot,
    UsageLimited,
)
from coral.omni.protocols import CoralSessionError
from coral.queue.conformance import run_executor_conformance
from coral.queue.executors import EffectCompleted as Completed
from coral.queue.executors import EffectOutcome
from coral.recovery.drift import DriftDetected, DriftFinding
from coral.recovery.relaunch import LivenessPass, LivenessRef
from coral.stores.protocols import RunContended, WorkItem
from tests.coral.bridge._scripted_runs import accept
from tests.coral.bridge._world import (
    IMPLEMENT,
    START,
    WORKSPACE,
    Sessions,
    World,
    row_of,
    serving,
    start,
)
from tests.coral.omni.fakes import present
from tests.coral.slots._close_fakes import FakeSession
from tests.coral.workflow_builders import arrow, end, step, workflow_text
from tests.coral.workflow_builders import start as start_node
from tests.coral.workspace._executor_fakes import effect_context

GRACE_S = 90
RUNNER = "runner-1"
WAKE = RECOVERY_WAKE
START_EPOCH = int(START.timestamp())


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


@pytest.fixture
async def working(world: World) -> AsyncIterator[tuple[Sessions, str]]:
    """A two-step run whose implementer got its brief and works on it, with its runner online."""
    run = start(world)
    async with serving(world) as sessions:
        await sessions.drain()
        assert len(sessions.messages()) == 1
        yield sessions, run.id


def _pass(sessions: Sessions, grace_s: int = GRACE_S) -> LivenessPass:
    return LivenessPass(sessions.threads, sessions.dispatch, grace_s=grace_s)


async def _check(liveness: LivenessPass, run_id: str) -> int | None:
    return await liveness.check_run(workspace_id=WORKSPACE, run_id=run_id)


def _runner(sessions: Sessions, run_id: str) -> FakeSession:
    return sessions.dispatch.sessions[sessions.session_of(run_id, IMPLEMENT)]


def _drop(runner: FakeSession, *, stamp_age_s: float | None = None, now: Any = None) -> None:
    """The runner's tunnel drops: the server clears its stamp, or a stale one is left."""
    runner.runner_alive = False
    runner.runner_fresh = False
    runner.runner_last_seen = None if stamp_age_s is None else now - timedelta(seconds=stamp_age_s)


def _losses(world: World, run_id: str) -> list[RunnerLost]:
    world.assert_fold_matches(run_id)
    entries = decode_entries(world.engine_log(run_id))
    return [entry.input for entry in entries if isinstance(entry.input, RunnerLost)]


def _line(run_id: str, *, started: int = 0, lost: int = 0, known: int = 0, again: int = 0) -> str:
    return (
        f"Coral liveness of run {run_id}: {started} runner clock(s) started, {lost} runner(s) "
        f"lost, {known} loss(es) already recorded, {again} report(s) to make again"
    )


def _wakes(world: World, run_id: str) -> list[dict[str, Any]]:
    state = world.assert_fold_matches(run_id)
    return [dict(effect.payload) for effect in state.effects if effect.kind == "runner_lost"]


@pytest.mark.parametrize("stamp", ["cleared", "an_hour_old"])
async def test_a_missing_runner_is_lost_once_the_grace_from_its_first_sighting_ends(
    world: World, working: tuple[Sessions, str], stamp: str
) -> None:
    sessions, run_id = working
    runner = _runner(sessions, run_id)
    # However old the stamp is, the clock starts at this process's own first sighting.
    _drop(runner, stamp_age_s=None if stamp == "cleared" else 3600, now=world.clock.now)
    liveness = _pass(sessions)
    first_sighting = world.clock.now
    grace_end = world.clock.epoch + GRACE_S

    dues = [await _check(liveness, run_id)]
    world.clock.advance(GRACE_S - 1)
    dues.append(await _check(liveness, run_id))
    assert _losses(world, run_id) == []
    world.clock.advance(1)
    dues.append(await _check(liveness, run_id))
    world.clock.advance(600)
    dues.append(await _check(liveness, run_id))

    assert dues == [grace_end, grace_end, None, None]
    [lost] = _losses(world, run_id)
    assert (lost.slot_id, lost.runner_id, lost.observed_at) == (IMPLEMENT, RUNNER, first_sighting)
    [wake] = _wakes(world, run_id)
    assert (wake["runner_id"], wake["generation"]) == (RUNNER, 1)
    assert wake["session_id"] == sessions.session_of(run_id, IMPLEMENT)


@pytest.mark.parametrize("seen", ["connected", "fresh_stamp"])
async def test_a_connected_runner_or_a_stamp_the_server_calls_fresh_never_starts_a_clock(
    world: World, working: tuple[Sessions, str], seen: str
) -> None:
    sessions, run_id = working
    runner = _runner(sessions, run_id)
    if seen == "fresh_stamp":
        # Its tunnel is on another replica, which keeps the stamp fresh.
        runner.runner_alive = False
        runner.runner_fresh = True
    liveness = _pass(sessions)

    dues = []
    for _ in range(5):
        dues.append(await _check(liveness, run_id))
        world.clock.advance(GRACE_S)

    assert dues == [None] * 5
    assert _losses(world, run_id) == []


@pytest.mark.parametrize("change", ["came_back", "new_runner"])
async def test_a_clock_ends_when_its_runner_comes_back_or_the_session_gets_another_runner(
    world: World, working: tuple[Sessions, str], change: str
) -> None:
    sessions, run_id = working
    runner = _runner(sessions, run_id)
    _drop(runner)
    liveness = _pass(sessions)
    await _check(liveness, run_id)
    world.clock.advance(GRACE_S - 10)
    if change == "came_back":
        runner.runner_alive = True
        assert await _check(liveness, run_id) is None
        _drop(runner)
    else:
        runner.runner_id = "runner-2"
    world.clock.advance(1)
    restarted_at = world.clock.now

    due = await _check(liveness, run_id)
    world.clock.advance(GRACE_S - 1)
    await _check(liveness, run_id)
    assert _losses(world, run_id) == []
    world.clock.advance(1)
    await _check(liveness, run_id)

    assert due == int((restarted_at + timedelta(seconds=GRACE_S)).timestamp())
    [lost] = _losses(world, run_id)
    assert (lost.runner_id, lost.observed_at) == (runner.runner_id, restarted_at)


async def test_a_run_that_stops_running_drops_its_clocks_and_its_working_slots_start_afresh(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    _drop(_runner(sessions, run_id))
    liveness = _pass(sessions)
    await _check(liveness, run_id)
    world.clock.advance(GRACE_S - 1)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )

    assert await _check(liveness, run_id) is None
    world.clock.advance(GRACE_S)
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor="user:alice")
    await sessions.drain()
    resumed_at = world.clock.now
    due = await _check(liveness, run_id)

    assert due == int((resumed_at + timedelta(seconds=GRACE_S)).timestamp())
    assert _losses(world, run_id) == []


async def test_a_slot_that_handed_off_is_no_longer_watched(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    _drop(_runner(sessions, run_id))
    liveness = _pass(sessions)
    await _check(liveness, run_id)
    reads = sessions.events.count("runner_liveness")
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: accept(IMPLEMENT, "Done.")
    )
    world.clock.advance(GRACE_S)

    assert await _check(liveness, run_id) is None
    assert sessions.events.count("runner_liveness") == reads
    assert _losses(world, run_id) == []


async def test_a_failed_read_keeps_the_slots_clock_and_logs_only_the_run_and_error_type(
    world: World, working: tuple[Sessions, str], caplog: pytest.LogCaptureFixture
) -> None:
    sessions, run_id = working
    _drop(_runner(sessions, run_id))
    liveness = _pass(sessions)
    await _check(liveness, run_id)
    world.clock.advance(GRACE_S - 1)
    sessions.dispatch.refusals["runner_liveness"] = RuntimeError("token=abc at /secret/path")

    with caplog.at_level(logging.WARNING, logger="coral.recovery.relaunch"):
        due = await _check(liveness, run_id)
    world.clock.advance(1)
    await _check(liveness, run_id)

    assert due == world.clock.epoch
    [record] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert run_id in record.getMessage() and "RuntimeError" in record.getMessage()
    assert "secret" not in record.getMessage() and "token" not in record.getMessage()
    assert len(_losses(world, run_id)) == 1


async def test_a_loss_report_that_cannot_be_committed_is_made_at_the_next_pass(
    world: World, working: tuple[Sessions, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions, run_id = working
    _drop(_runner(sessions, run_id))
    liveness = _pass(sessions)
    await _check(liveness, run_id)
    world.clock.advance(GRACE_S)
    apply = EngineBridge.apply_turn_fact
    calls: list[bool] = []

    def contended_once(bridge: EngineBridge, **kwargs: Any) -> Any:
        if not calls:
            calls.append(True)
            raise RunContended("version conflict")
        return apply(bridge, **kwargs)

    monkeypatch.setattr(EngineBridge, "apply_turn_fact", contended_once)
    assert await _check(liveness, run_id) is None
    assert _losses(world, run_id) == []
    world.clock.advance(60)
    await _check(liveness, run_id)

    assert len(_losses(world, run_id)) == 1


async def test_the_pass_logs_one_line_when_it_starts_or_reports_a_clock(
    world: World, working: tuple[Sessions, str], caplog: pytest.LogCaptureFixture
) -> None:
    sessions, run_id = working
    _drop(_runner(sessions, run_id))
    liveness = _pass(sessions)

    with caplog.at_level(logging.INFO, logger="coral.recovery.relaunch"):
        for step in (0, 30, GRACE_S - 30, 30):
            world.clock.advance(step)
            await _check(liveness, run_id)

    lines = [r.getMessage() for r in caplog.records if r.name == "coral.recovery.relaunch"]
    assert lines == [
        _line(run_id, started=1),
        _line(run_id, lost=1),
    ]


async def test_the_resync_runs_again_when_the_grace_ends_not_at_a_later_tick(
    world: World,
) -> None:
    run = start(world)
    ref = LivenessRef()
    async with serving(world, liveness=ref) as sessions:
        await sessions.drain()
        ref.current = _pass(sessions)
        _drop(_runner(sessions, run.id))
        world.bridge.schedule_resync(world.run(run.id))
        await sessions.drain()
        (row,) = world.queue.get_work([resync_draft(run.id).id], workspace_id=WORKSPACE)
        grace_end = world.clock.epoch + GRACE_S
        assert (row.status, row.available_at) == (int(WorkStatus.PENDING), grace_end)

        world.clock.advance(GRACE_S - 1)
        await sessions.drain()
        assert _losses(world, run.id) == []
        world.clock.advance(1)
        await sessions.drain()

        [lost] = _losses(world, run.id)
        assert lost.runner_id == RUNNER
        (row,) = world.queue.get_work([resync_draft(run.id).id], workspace_id=WORKSPACE)
        assert row.status == int(WorkStatus.SUCCEEDED)
        assert NEXT_RESYNC_AT not in (row.result or "")


async def test_an_unset_liveness_ref_reads_nothing(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    _drop(_runner(sessions, run_id))
    ref = LivenessRef()

    assert await ref.check_run(workspace_id=WORKSPACE, run_id=run_id) is None
    assert "runner_liveness" not in sessions.events


def _wake_finds_the_runner_back(world: World, run_id: str) -> None:
    """Commit what the wake commits when it finds the lost runner back, its turn running."""
    state = world.assert_fold_matches(run_id)
    receipted = {receipt.key for receipt in state.receipts}
    [wake] = [
        effect
        for effect in state.effects
        if effect.kind == "runner_lost" and effect.effect_key not in receipted
    ]
    payload: dict[str, Any] = {
        "outcome": "runner_back",
        "turn_running": True,
        "seen_at": world.clock.now.isoformat(),
    }
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (EffectCompleted(effect_key=wake.effect_key, payload=payload),),
    )


async def test_a_runner_lost_again_after_it_came_back_is_a_second_loss(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    runner = _runner(sessions, run_id)
    liveness = _pass(sessions)
    _drop(runner)
    await _check(liveness, run_id)
    world.clock.advance(GRACE_S)
    await _check(liveness, run_id)
    # The runner reconnects: a pass sees it, and the wake finds it back with its turn.
    world.clock.advance(5)
    runner.runner_alive = True
    assert await _check(liveness, run_id) is None
    _wake_finds_the_runner_back(world, run_id)
    world.clock.advance(30)
    _drop(runner)
    second_sighting = world.clock.now

    await _check(liveness, run_id)
    world.clock.advance(GRACE_S - 1)
    await _check(liveness, run_id)
    assert len(_losses(world, run_id)) == 1
    world.clock.advance(1)
    await _check(liveness, run_id)

    _first, second = _losses(world, run_id)
    assert (second.runner_id, second.observed_at) == (RUNNER, second_sighting)
    [slot] = [s for s in world.assert_fold_matches(run_id).slots if s.id == IMPLEMENT]
    assert (slot.wakes, slot.connection_epoch) == (2, 1)
    assert len(_wakes(world, run_id)) == 2


async def test_one_pass_watches_many_runs_on_one_host_each_on_its_own_clock(
    world: World,
) -> None:
    """The server's one pass serves every run; runs on one host drop ten seconds apart."""
    runs = [start(world, start_key=f"start-{index}").id for index in range(4)]
    ref = LivenessRef()
    async with serving(world, liveness=ref) as sessions:
        await sessions.drain()
        ref.current = _pass(sessions)
        for index, run_id in enumerate(runs):
            world.clock.advance(0 if index == 0 else 10)
            _drop(_runner(sessions, run_id))
            world.bridge.schedule_resync(world.run(run_id))
            await sessions.drain()
            (row,) = world.queue.get_work([resync_draft(run_id).id], workspace_id=WORKSPACE)
            assert row.available_at == world.clock.epoch + GRACE_S

        # No tick: each run's own rescheduled resync reports its loss at its grace end.
        world.clock.advance(GRACE_S - 10 * (len(runs) - 1) - 1)
        await sessions.drain()
        lost_by_then = [sum(1 for run_id in runs if _losses(world, run_id))]
        for _ in runs:
            world.clock.advance(1)
            await sessions.drain()
            lost_by_then.append(sum(1 for run_id in runs if _losses(world, run_id)))
            world.clock.advance(9)
            await sessions.drain()

    assert lost_by_then == [0, 1, 2, 3, 4]
    assert all(len(_losses(world, run_id)) == 1 for run_id in runs)


async def test_a_replica_that_leads_again_gives_a_missing_runner_a_full_grace(
    world: World, working: tuple[Sessions, str]
) -> None:
    """Clocks from an earlier leader term never fire at the first pass of the next one."""
    sessions, run_id = working
    runner = _runner(sessions, run_id)
    ref = LivenessRef()
    ref.current = _pass(sessions)
    _drop(runner)
    await ref.check_run(workspace_id=WORKSPACE, run_id=run_id)
    # Another replica leads for an hour, while the runner comes back. This one leads
    # again a second after the runner dropped once more, and never saw it connected.
    world.clock.advance(3600)
    ref.reset()
    sighting = world.clock.now

    due = await ref.check_run(workspace_id=WORKSPACE, run_id=run_id)
    world.clock.advance(GRACE_S - 1)
    await ref.check_run(workspace_id=WORKSPACE, run_id=run_id)
    assert _losses(world, run_id) == []
    world.clock.advance(1)
    await ref.check_run(workspace_id=WORKSPACE, run_id=run_id)

    assert due == int((sighting + timedelta(seconds=GRACE_S)).timestamp())
    [lost] = _losses(world, run_id)
    assert lost.observed_at == sighting


async def test_a_runner_the_wake_found_back_that_drops_before_any_pass_is_lost_again(
    world: World, working: tuple[Sessions, str], caplog: pytest.LogCaptureFixture
) -> None:
    """A loss after a reconnect is a new loss, though no pass ever sees the runner connected."""
    sessions, run_id = working
    runner = _runner(sessions, run_id)
    liveness = _pass(sessions)
    _drop(runner)
    await _check(liveness, run_id)
    world.clock.advance(GRACE_S)
    await _check(liveness, run_id)
    # It reconnects and the wake finds it back with its turn running, ending the outage;
    # it drops again before the next resync tick and stays gone.
    world.clock.advance(1)
    _wake_finds_the_runner_back(world, run_id)
    world.clock.advance(9)
    second_sighting = world.clock.now + timedelta(seconds=50)
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="coral.recovery.relaunch"):
        for _ in range(10):
            world.clock.advance(50)
            await _check(liveness, run_id)

    first, second = _losses(world, run_id)
    assert (first.runner_id, second.runner_id) == (RUNNER, RUNNER)
    assert second.observed_at == second_sighting
    [slot] = [s for s in world.assert_fold_matches(run_id).slots if s.id == IMPLEMENT]
    assert (slot.wakes, slot.connection_epoch) == (2, 1)
    lines = [r.getMessage() for r in caplog.records if r.name == "coral.recovery.relaunch"]
    assert lines == [_line(run_id, started=1), _line(run_id, lost=1)]


async def test_a_report_the_engine_drops_is_made_again_and_not_logged_as_lost(
    world: World, working: tuple[Sessions, str], caplog: pytest.LogCaptureFixture
) -> None:
    """The lowest grace with a clock stepping exactly to its end: the engine's own 30 s
    grace needs the sighting strictly older, so the first report records nothing."""
    sessions, run_id = working
    _drop(_runner(sessions, run_id))
    liveness = _pass(sessions, grace_s=30)

    with caplog.at_level(logging.INFO, logger="coral.recovery.relaunch"):
        await _check(liveness, run_id)
        world.clock.advance(30)
        await _check(liveness, run_id)
        assert _losses(world, run_id) == []
        world.clock.advance(60)
        await _check(liveness, run_id)
        world.clock.advance(60)
        await _check(liveness, run_id)

    assert len(_losses(world, run_id)) == 1
    lines = [r.getMessage() for r in caplog.records if r.name == "coral.recovery.relaunch"]
    assert lines == [_line(run_id, started=1), _line(run_id, again=1), _line(run_id, lost=1)]


async def test_a_loss_the_edge_already_reported_is_logged_as_recorded_not_lost(
    world: World, working: tuple[Sessions, str], caplog: pytest.LogCaptureFixture
) -> None:
    sessions, run_id = working
    session_id = sessions.session_of(run_id, IMPLEMENT)
    sessions.facade.sessions.states[(WORKSPACE, session_id)] = present(
        session_id, runner_id=RUNNER
    )
    _drop(_runner(sessions, run_id))
    liveness = _pass(sessions)
    await _check(liveness, run_id)
    sessions.publish_to(
        session_id,
        "failed",
        turn_outcome="failed",
        error_code="runner_disconnected",
        error_message="Runner disconnected unexpectedly.",
        failure_origin="runner_offline_sweep",
    )
    # The edge's wake cannot reach the host yet, so the outage stays open.
    sessions.relauncher.answers.append(
        CoralSessionError("session.runner_status_unknown", "no answer", retryable=True)
    )
    await sessions.drain()
    assert len(_wakes(world, run_id)) == 1
    world.clock.advance(GRACE_S)
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="coral.recovery.relaunch"):
        assert await _check(liveness, run_id) is None
        world.clock.advance(60)
        await _check(liveness, run_id)

    assert _losses(world, run_id) == []
    assert len(_wakes(world, run_id)) == 1
    lines = [r.getMessage() for r in caplog.records if r.name == "coral.recovery.relaunch"]
    assert lines == [_line(run_id, known=1)]


async def test_a_stamp_that_goes_stale_after_the_first_pass_starts_the_clock_then(
    world: World, working: tuple[Sessions, str]
) -> None:
    """A short lease: the pre-crash stamp is still fresh at the first pass, stale later."""
    sessions, run_id = working
    runner = _runner(sessions, run_id)
    runner.runner_alive = False
    runner.runner_fresh = True
    liveness = _pass(sessions)
    assert await _check(liveness, run_id) is None
    world.clock.advance(60)
    runner.runner_fresh = False
    stale_at = world.clock.now

    due = await _check(liveness, run_id)
    world.clock.advance(GRACE_S - 1)
    await _check(liveness, run_id)
    assert _losses(world, run_id) == []
    world.clock.advance(1)
    await _check(liveness, run_id)

    assert due == int((stale_at + timedelta(seconds=GRACE_S)).timestamp())
    [lost] = _losses(world, run_id)
    assert lost.observed_at == stale_at


# ── The wake ────────────────────────────────────────────────────────────────


def _lose(world: World, sessions: Sessions, run_id: str, slot_id: str = IMPLEMENT) -> str:
    """The slot's runner is gone, and its loss is committed as the liveness pass reports it."""
    session_id = sessions.session_of(run_id, slot_id)
    runner = sessions.dispatch.sessions[session_id]
    runner.runner_alive = False
    [slot] = [s for s in world.assert_fold_matches(run_id).slots if s.id == slot_id]
    lost = RunnerLost(
        slot_id=slot_id,
        session_id=session_id,
        generation=slot.session_generation,
        runner_id=runner.runner_id,
        observed_at=world.clock.now,
    )
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: (lost,)
    )
    return session_id


def _wake_row(world: World, run_id: str) -> WorkItem:
    rows = [row for row in world.work(run_id) if json.loads(row.payload)["effect_type"] == WAKE]
    return rows[-1]


def _result(row: WorkItem) -> dict[str, Any]:
    assert row.status == int(WorkStatus.SUCCEEDED), (row.status, row.error_code)
    assert row.result is not None
    return json.loads(row.result)


def _slot(world: World, run_id: str, slot_id: str = IMPLEMENT) -> Slot:
    [slot] = [s for s in world.assert_fold_matches(run_id).slots if s.id == slot_id]
    return slot


def _nudges(sessions: Sessions, session_id: str) -> list[str]:
    return [str(send["text"]) for send in sessions.messages(session_id)[1:]]


def _inputs(world: World, run_id: str, kind: type[Any]) -> list[Any]:
    world.assert_fold_matches(run_id)
    return [e.input for e in decode_entries(world.engine_log(run_id)) if isinstance(e.input, kind)]


def _causes(world: World, run_id: str) -> list[tuple[str, str, str]]:
    state = world.assert_fold_matches(run_id)
    return [(cause.reason, cause.detail, cause.subject) for cause in state.causes]


async def test_a_lost_runner_is_relaunched_in_its_own_session_and_re_prompted_once(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)

    await sessions.drain()

    result = _result(_wake_row(world, run_id))
    assert result == {
        "outcome": "relaunched",
        "turn_running": False,
        "seen_at": world.clock.now.isoformat(),
    }
    assert sessions.relauncher.calls == [(WORKSPACE, session_id, 1)]
    [nudge] = _nudges(sessions, session_id)
    assert nudge.startswith("Your runner stopped and Coral restarted it.")
    slot = _slot(world, run_id)
    assert (slot.status, slot.session_generation, slot.wakes) == ("working", 1, 1)
    assert slot.retired_runners == (RUNNER,)
    assert world.assert_fold_matches(run_id).status == "running"


@pytest.mark.parametrize("turn", ["running", "idle"])
async def test_a_runner_found_back_re_prompts_only_a_turn_that_stopped(
    world: World, working: tuple[Sessions, str], turn: str
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)
    sessions.dispatch.sessions[session_id].status = turn
    sessions.relauncher.answers.append("connected")

    await sessions.drain()

    result = _result(_wake_row(world, run_id))
    assert (result["outcome"], result["turn_running"]) == ("runner_back", turn == "running")
    assert len(_nudges(sessions, session_id)) == (0 if turn == "running" else 1)
    slot = _slot(world, run_id)
    assert (slot.connection_epoch, slot.retired_runners) == (1, ())
    assert slot.failed_turn is None if turn == "running" else True


@pytest.mark.parametrize("change", ["handed_off", "archived", "deleted"])
async def test_a_wake_skips_a_slot_that_moved_on_or_a_session_that_drifted(
    world: World, working: tuple[Sessions, str], change: str
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)
    if change == "handed_off":
        world.bridge.commit_inputs(
            workspace_id=WORKSPACE,
            run_id=run_id,
            inputs=lambda _snapshot: accept(IMPLEMENT, "Done."),
        )
    else:
        states = {
            "archived": present(session_id, archived=True),
            "deleted": present(session_id, exists=False),
        }
        sessions.facade.sessions.states[(WORKSPACE, session_id)] = states[change]

    await sessions.drain()

    assert _result(_wake_row(world, run_id))["outcome"] == "skipped"
    assert sessions.relauncher.calls == []
    state = world.assert_fold_matches(run_id)
    drifted = change in ("archived", "deleted")
    assert (state.status == "paused") is drifted
    if drifted:
        assert [cause.reason for cause in state.causes] == ["drift"]


async def test_a_wake_waits_while_its_run_is_paused_for_anything_but_a_host_hold(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    _lose(world, sessions, run_id)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="paused by alice"),),
    )

    await sessions.drain()

    row = _wake_row(world, run_id)
    assert (row.status, row.error_code) == (int(WorkStatus.PENDING), "run.paused")
    assert row.available_at == world.clock.epoch + 300
    assert sessions.relauncher.calls == []


def _host_offline() -> CoralSessionError:
    return CoralSessionError("session.host_offline", "host is not connected", retryable=True)


async def _held(world: World, sessions: Sessions, run_id: str, polls: int) -> str:
    """The runner lost while its host is offline, its wake polling ``polls`` times."""
    session_id = _lose(world, sessions, run_id)
    sessions.relauncher.answers.extend(_host_offline() for _ in range(polls))
    for poll in range(polls):
        if poll:
            world.clock.advance(30)
        await sessions.drain()
    return session_id


async def test_an_offline_host_holds_the_step_once_over_many_polls_with_cancel_only(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = await _held(world, sessions, run_id, polls=4)

    row = _wake_row(world, run_id)
    assert (row.status, row.error_code) == (int(WorkStatus.PENDING), "recovery.host_offline")
    assert row.available_at == world.clock.epoch + 30
    assert len(sessions.relauncher.calls) == 4
    assert len(_inputs(world, run_id, RunnerHeld)) == 1
    assert _causes(world, run_id) == [("infra", "infra.host_offline", IMPLEMENT)]
    state = world.assert_fold_matches(run_id)
    # Only Cancel: Resume and Retry are refused while the host is away.
    assert retryable_activations(state) == ()
    resumed = world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: (ResumeRun(),)
    )
    assert [entry.rejection.code for entry in resumed.entries if entry.rejection] == [
        "resume_not_allowed"
    ]
    assert _nudges(sessions, session_id) == []


@pytest.mark.parametrize("found", ["connected", "relaunched"])
async def test_the_hosts_return_ends_the_hold_then_finds_or_relaunches_the_runner(
    world: World, working: tuple[Sessions, str], found: str
) -> None:
    sessions, run_id = working
    session_id = await _held(world, sessions, run_id, polls=2)
    sessions.relauncher.answers.append(found)  # type: ignore[arg-type]
    sessions.dispatch.sessions[session_id].status = "idle"

    world.clock.advance(30)
    await sessions.drain()

    result = _result(_wake_row(world, run_id))
    assert result["outcome"] == ("runner_back" if found == "connected" else "relaunched")
    [ended] = _inputs(world, run_id, RunnerHoldEnded)
    assert (ended.slot_id, ended.generation) == (IMPLEMENT, 1)
    assert world.assert_fold_matches(run_id).status == "running"
    assert _causes(world, run_id) == []
    assert len(_nudges(sessions, session_id)) == 1
    assert len(_inputs(world, run_id, RunnerHeld)) == 1


async def test_a_runner_the_host_calls_alive_is_held_then_pauses_and_a_resume_wakes_it_again(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)
    sessions.relauncher.fallback = _alive

    await sessions.drain()
    row = _wake_row(world, run_id)
    assert (row.status, row.error_code) == (int(WorkStatus.PENDING), "recovery.runner_alive")
    assert row.available_at == world.clock.epoch + 30
    # Held for ten minutes from its first refusal, then retried as any failure is.
    for _ in range(80):
        world.clock.advance(30)
        await sessions.drain()
        if _wake_row(world, run_id).status == int(WorkStatus.FAILED):
            break

    assert _wake_row(world, run_id).status == int(WorkStatus.FAILED)
    assert world.clock.epoch - START_EPOCH >= 600
    assert _causes(world, run_id) == [("infra", "recovery.runner_alive", IMPLEMENT)]
    # The old runner is never superseded: no relaunch, so no restarted-runner prompt.
    assert _slot(world, run_id).retired_runners == ()
    assert not any(
        text.startswith("Your runner stopped") for text in _nudges(sessions, session_id)
    )
    # A Resume revives the wake, which now finds the runner back and re-prompts it.
    sessions.relauncher.fallback = lambda _session_id: "connected"
    sessions.dispatch.sessions[session_id].status = "idle"
    before = len(_nudges(sessions, session_id))
    resumed = world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: (ResumeRun(),)
    )
    await sessions.drain()

    assert [entry.rejection for entry in resumed.entries] == [None]
    assert _result(_wake_row(world, run_id))["outcome"] == "runner_back"
    assert _causes(world, run_id) == []
    # The resume's own re-prompt is the step's one prompt; the wake adds none.
    assert len(_nudges(sessions, session_id)) == before + 1


def _alive(session_id: str) -> Literal["connected", "relaunched"]:
    raise CoralSessionError(
        "recovery.runner_alive", f"{session_id}'s runner is alive", retryable=True
    )


async def test_a_host_on_an_older_coral_fails_the_wake_for_good(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    _lose(world, sessions, run_id)
    sessions.relauncher.answers.append(
        CoralSessionError("session.host_unsupported", "update Coral on that host")
    )

    await sessions.drain()

    row = _wake_row(world, run_id)
    assert (row.status, row.error_code) == (int(WorkStatus.FAILED), "session.host_unsupported")
    assert _causes(world, run_id) == [("failure_path", "session.host_unsupported", IMPLEMENT)]


async def test_a_fourth_loss_of_one_generation_drops_the_ladder_instead_of_waking(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    for _ in range(3):
        world.clock.advance(1)
        _lose(world, sessions, run_id)
        await sessions.drain()
        assert _result(_wake_row(world, run_id))["outcome"] == "relaunched"
    wakes = len(_wakes(world, run_id))

    world.clock.advance(1)
    _lose(world, sessions, run_id)
    await sessions.drain()

    assert (wakes, len(_wakes(world, run_id))) == (3, 3)
    assert len(sessions.relauncher.calls) == 3
    assert _slot(world, run_id).wakes == 3
    assert _causes(world, run_id) == [("infra", "infra.runner_lost", IMPLEMENT)]


async def test_wake_executor_conformance(world: World, working: tuple[Sessions, str]) -> None:
    sessions, run_id = working
    session_id = sessions.session_of(run_id, IMPLEMENT)
    payload = json.loads(row_of(world, run_id, "send_input").payload)
    wake = {
        "effect_type": WAKE,
        "effect_key": f"{run_id}:99:runner_lost:{IMPLEMENT}",
        "engine_kind": "runner_lost",
        "engine_slot_id": IMPLEMENT,
        "generation": 1,
        "session_id": session_id,
        "runner_id": RUNNER,
        "slot_id": payload["slot_id"],
    }
    outcomes: list[EffectOutcome] = []

    async def recording(ctx: Any) -> EffectOutcome:
        outcome = await sessions.executors()[WAKE](ctx)
        outcomes.append(outcome)
        return outcome

    await run_executor_conformance(
        recording, effect_type=WAKE, payload=wake, workspace_id=WORKSPACE, run_id=run_id
    )

    first, repeat = (outcome for outcome in outcomes)
    assert isinstance(first, Completed) and isinstance(repeat, Completed)
    assert first.result == repeat.result
    assert first.result is not None and first.result["outcome"] == "runner_back"


# ── The wake under edge cases ───────────────────────────────────────────────

# One step of two slots on one host, each with its own session and runner.
PAIR = workflow_text(
    [start_node(), step("work", roster=["implementer", "reviewer"]), end()],
    [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
)
PAIR_SLOTS = ("work||:0", "work||:1")


@dataclass
class _HostLink:
    """Whether the steps' host is connected; while it is not, every relaunch is refused."""

    online: bool = False


def _host_comes_and_goes(sessions: Sessions) -> _HostLink:
    """The relaunch path refuses ``session.host_offline`` until the host is back online."""
    link = _HostLink()
    back = sessions.relauncher.fallback

    def answer(session_id: str) -> Literal["connected", "relaunched"]:
        if not link.online:
            raise _host_offline()
        return back(session_id)

    sessions.relauncher.fallback = answer
    return link


def _wake_rows(world: World, run_id: str) -> dict[str, WorkItem]:
    """Each slot's wake row, by engine slot id (one wake per slot here)."""
    rows: dict[str, WorkItem] = {}
    for row in world.work(run_id):
        payload = json.loads(row.payload)
        if payload["effect_type"] == WAKE:
            rows[payload["engine_slot_id"]] = row
    return rows


def _restarted_prompts(sessions: Sessions, session_id: str) -> list[str]:
    """The ``runner_lost`` re-prompts the session got."""
    return [
        text for text in _nudges(sessions, session_id) if text.startswith("Your runner stopped")
    ]


def _commit(world: World, run_id: str, *inputs: Any) -> Any:
    return world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: inputs
    )


def _rejections(commit: Any) -> list[str]:
    return [entry.rejection.code for entry in commit.entries if entry.rejection]


async def test_two_held_slots_on_one_host_both_poll_and_both_come_back_with_it(
    world: World,
) -> None:
    run_id = start(world, PAIR).id
    async with serving(world) as sessions:
        await sessions.drain()
        link = _host_comes_and_goes(sessions)
        session_ids = [_lose(world, sessions, run_id, slot_id) for slot_id in PAIR_SLOTS]
        await sessions.drain()
        world.clock.advance(30)
        await sessions.drain()
        causes_while_away = _causes(world, run_id)
        polled = sorted(session_id for _ws, session_id, _gen in sessions.relauncher.calls)
        waits = {(row.status, row.error_code) for row in _wake_rows(world, run_id).values()}

        link.online = True
        world.clock.advance(30)
        await sessions.drain()

        # Each slot's own wake holds its own slot once, and both keep polling the host.
        hold = "infra", "infra.host_offline"
        assert sorted(causes_while_away) == sorted((*hold, slot_id) for slot_id in PAIR_SLOTS)
        assert polled == sorted(session_ids * 2)
        assert waits == {(int(WorkStatus.PENDING), "recovery.host_offline")}
        held = _inputs(world, run_id, RunnerHeld)
        assert sorted(item.slot_id for item in held) == sorted(PAIR_SLOTS)
        # The host's return brings both back: each hold ends once, each step re-prompted once.
        ended = _inputs(world, run_id, RunnerHoldEnded)
        assert sorted(item.slot_id for item in ended) == sorted(PAIR_SLOTS)
        outcomes = {
            slot: _result(row)["outcome"] for slot, row in _wake_rows(world, run_id).items()
        }
        assert outcomes == dict.fromkeys(PAIR_SLOTS, "relaunched")
        state = world.assert_fold_matches(run_id)
        assert (state.status, state.causes) == ("running", ())
        # One re-prompt each; the slot back first, while the other still held the run,
        # is re-prompted with the resume text once the run runs again.
        for session_id in session_ids:
            assert len(_nudges(sessions, session_id)) == 1


async def _held_then_paused(world: World, sessions: Sessions, run_id: str) -> str:
    """Held on an offline host, then paused by a person; the host comes back meanwhile."""
    link = _host_comes_and_goes(sessions)
    session_id = _lose(world, sessions, run_id)
    await sessions.drain()
    _commit(world, run_id, PauseRun(reason="user", detail="paused by alice"))
    link.online = True
    world.clock.advance(30)
    await sessions.drain()
    return session_id


async def test_a_held_step_that_is_also_paused_comes_back_once_only_after_the_resume(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = await _held_then_paused(world, sessions, run_id)
    row = _wake_row(world, run_id)
    waited, polls = (row.status, row.error_code), len(sessions.relauncher.calls)

    resumed = _commit(world, run_id, ResumeRun())
    still_held = _causes(world, run_id)
    for _ in range(12):
        world.clock.advance(30)
        await sessions.drain()
        if _wake_row(world, run_id).status != int(WorkStatus.PENDING):
            break

    # Nothing is relaunched while the person's pause stands, though the host is back.
    assert waited == (int(WorkStatus.PENDING), "run.paused")
    assert polls == 1
    # The Resume clears only the person's pause; the hold stands until the wake ends it.
    assert _rejections(resumed) == []
    assert still_held == [("infra", "infra.host_offline", IMPLEMENT)]
    assert _result(_wake_row(world, run_id))["outcome"] == "relaunched"
    assert len(_inputs(world, run_id, RunnerHoldEnded)) == 1
    state = world.assert_fold_matches(run_id)
    assert (state.status, state.causes) == ("running", ())
    assert len(_restarted_prompts(sessions, session_id)) == 1


async def test_a_resume_that_leaves_the_host_hold_re_checks_the_host_within_30_seconds(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    await _held_then_paused(world, sessions, run_id)

    _commit(world, run_id, ResumeRun())
    world.clock.advance(30)
    await sessions.drain()

    assert _result(_wake_row(world, run_id))["outcome"] == "relaunched"


async def test_a_run_cancelled_while_its_step_is_held_never_relaunches_the_runner(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    link = _host_comes_and_goes(sessions)
    session_id = _lose(world, sessions, run_id)
    await sessions.drain()
    # The cancel's close shows on the session's row, as the real facade reads it.
    closed = present(session_id, closed=True)
    sessions.dispatch.hooks["set_closed"] = lambda: sessions.facade.sessions.states.update(
        {(WORKSPACE, session_id): closed}
    )

    cancelled = _commit(world, run_id, CancelRun())
    await sessions.drain()
    link.online = True
    world.clock.advance(30)
    await sessions.drain()

    assert _rejections(cancelled) == []
    assert world.assert_fold_matches(run_id).status == "cancelled"
    # Only the first poll, while the host was away, reached the relaunch path; the
    # drainer drops the wake of a run that ended.
    assert len(sessions.relauncher.calls) == 1
    row = _wake_row(world, run_id)
    assert (row.status, row.error_code) == (int(WorkStatus.ABANDONED), "run.terminal")
    assert _nudges(sessions, session_id) == []


async def test_a_cancel_that_lands_while_the_relaunch_runs_leaves_no_runner_and_no_re_prompt(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)
    relaunch = sessions.relauncher.fallback

    def cancelled_meanwhile(session_id: str) -> Literal["connected", "relaunched"]:
        # The person cancels after the wake loaded the run, while its relaunch runs.
        _commit(world, run_id, CancelRun())
        return relaunch(session_id)

    sessions.relauncher.fallback = cancelled_meanwhile

    await sessions.drain()

    assert _result(_wake_row(world, run_id))["outcome"] == "relaunched"
    assert world.assert_fold_matches(run_id).status == "cancelled"
    # The cancel's own close stops the relaunched runner, and the re-prompt the wake's
    # result asks for is dropped with the ended run.
    fake = sessions.dispatch.sessions[session_id]
    assert (fake.closed, fake.runner_alive) == (True, False)
    assert _nudges(sessions, session_id) == []


async def test_a_wake_repeated_after_its_relaunch_finds_the_runner_back_and_re_prompts_once(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)
    payload = _wake_row(world, run_id).payload
    # The first try relaunches, then loses its lease before its result is stored.
    lost = await sessions.executors()[WAKE](
        effect_context(workspace_id=WORKSPACE, run_id=run_id, payload=payload)
    )
    # The relaunched runner runs no turn yet.
    sessions.dispatch.sessions[session_id].status = "idle"

    await sessions.drain()

    assert isinstance(lost, Completed) and lost.result is not None
    assert lost.result["outcome"] == "relaunched"
    assert _result(_wake_row(world, run_id))["outcome"] == "runner_back"
    assert len(sessions.relauncher.calls) == 2
    assert len(_restarted_prompts(sessions, session_id)) == 1
    slot = _slot(world, run_id)
    assert (slot.wakes, slot.connection_epoch, slot.failed_turn) == (1, 1, None)


async def test_a_retry_while_a_wake_waits_on_the_pause_leaves_the_old_session_unlaunched(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    # The restart's salvage and reset, as the host answers them.
    sessions.host.replies.update(
        {
            "salvage": lambda request: {
                "ref": f"refs/coral/salvage/{request.op_key}",
                "commit": "f" * 40,
            },
            "reset": {"head": "1" * 40},
        }
    )
    old = _lose(world, sessions, run_id)
    # The slot's ladder gives out before its wake runs, so the run pauses for a Retry.
    _commit(world, run_id, InfraBackoffExhausted(slot_id=IMPLEMENT))
    await sessions.drain()
    row = _wake_row(world, run_id)
    waited = (row.status, row.error_code)

    retried = _commit(world, run_id, RetryStep(node_id="implement"))
    for _ in range(12):
        await sessions.drain()
        world.clock.advance(30)

    assert waited == (int(WorkStatus.PENDING), "run.paused")
    assert _rejections(retried) == []
    slot = _slot(world, run_id)
    new = sessions.session_of(run_id, IMPLEMENT)
    assert (slot.session_generation, slot.status) == (2, "working") and new != old
    # Generation 1's wake never reaches the relaunch path, so session 1 gets no runner.
    assert sessions.relauncher.calls == []
    wake = _wake_row(world, run_id)
    assert (wake.status, wake.error_code) == (
        int(WorkStatus.ABANDONED),
        "slot.generation_mismatch",
    )
    assert _restarted_prompts(sessions, old) == [] and _restarted_prompts(sessions, new) == []
    assert len(sessions.messages(new)) == 1
    assert world.assert_fold_matches(run_id).status == "running"


async def test_losses_held_on_an_offline_host_still_count_toward_the_fourth(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    link = _host_comes_and_goes(sessions)
    for _ in range(3):
        world.clock.advance(1)
        link.online = False
        _lose(world, sessions, run_id)
        await sessions.drain()
        assert _causes(world, run_id) == [("infra", "infra.host_offline", IMPLEMENT)]
        link.online = True
        world.clock.advance(30)
        await sessions.drain()
        assert _causes(world, run_id) == []

    world.clock.advance(1)
    link.online = False
    _lose(world, sessions, run_id)
    await sessions.drain()

    assert len(_wakes(world, run_id)) == 3
    assert len(_inputs(world, run_id, RunnerHeld)) == 3
    assert len(_inputs(world, run_id, RunnerHoldEnded)) == 3
    assert _slot(world, run_id).wakes == 3
    assert _causes(world, run_id) == [("infra", "infra.runner_lost", IMPLEMENT)]


async def test_an_edge_for_a_held_runner_adds_no_second_wake_and_no_second_hold(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = await _held(world, sessions, run_id, polls=1)
    runner = sessions.dispatch.sessions[session_id].runner_id
    # The server's own edge for the same runner, applied while the step is held.
    edge = SessionFailed(
        slot_id=IMPLEMENT,
        failure_class="infra.runner_lost",
        cause="runner_interrupted",
        fact_key=f"turn:{session_id}:1:edge",
        runner_id=runner,
        observed_at=world.clock.now,
    )
    _commit(world, run_id, edge)
    sessions.relauncher.answers.append(_host_offline())
    world.clock.advance(30)
    await sessions.drain()

    assert len(_wakes(world, run_id)) == 1
    assert len(_inputs(world, run_id, RunnerHeld)) == 1
    assert _slot(world, run_id).wakes == 1
    assert _causes(world, run_id) == [("infra", "infra.host_offline", IMPLEMENT)]


def _sends_through_the_relaunch_path(
    sessions: Sessions, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """Every engine send first brings the step's runner up through the relauncher, as the
    real dispatch's ``_connect_runner`` does; returns the sessions it was called for."""
    sent = sessions.dispatch.send_message
    called: list[str] = []

    async def send_message(**fields: Any) -> Any:
        called.append(fields["session_id"])
        await sessions.relauncher.ensure_runner(
            workspace_id=fields["workspace_id"], session_id=fields["session_id"], generation=1
        )
        return await sent(**fields)

    monkeypatch.setattr(sessions.dispatch, "send_message", send_message)
    return called


async def test_a_runner_the_host_calls_alive_is_held_its_full_ten_minutes_when_sends_relaunch(
    world: World, working: tuple[Sessions, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions, run_id = working
    _lose(world, sessions, run_id)
    sessions.relauncher.fallback = _alive
    _sends_through_the_relaunch_path(sessions, monkeypatch)

    await sessions.drain()
    for _ in range(80):
        world.clock.advance(30)
        await sessions.drain()
        if _wake_row(world, run_id).status != int(WorkStatus.PENDING):
            break

    assert _causes(world, run_id) == [("infra", "recovery.runner_alive", IMPLEMENT)]


async def test_a_step_still_on_its_old_runner_after_a_relaunch_is_woken_when_it_is_lost(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)

    def adopted(session_id: str) -> Literal["connected", "relaunched"]:
        # The launch found the old runner connected again and kept it.
        sessions.dispatch.sessions[session_id].runner_alive = True
        return "relaunched"

    sessions.relauncher.fallback = adopted
    await sessions.drain()
    assert sessions.dispatch.sessions[session_id].runner_id == RUNNER
    world.clock.advance(120)
    _lose(world, sessions, run_id)
    await sessions.drain()

    assert len(_wakes(world, run_id)) == 2


# ── Fix round: a hold ends with its wake; one turn per relaunch; horizons ─────


@pytest.mark.parametrize("ending", ["host_on_an_older_coral", "session_closed"])
async def test_a_hold_ends_when_its_wake_ends_without_the_runner(
    world: World, working: tuple[Sessions, str], ending: str
) -> None:
    sessions, run_id = working
    session_id = await _held(world, sessions, run_id, polls=1)
    if ending == "host_on_an_older_coral":
        sessions.relauncher.answers.append(
            CoralSessionError("session.host_unsupported", "update Coral on that host")
        )
    else:
        sessions.facade.sessions.states[(WORKSPACE, session_id)] = present(session_id, closed=True)

    world.clock.advance(30)
    await sessions.drain()

    code = "session.host_unsupported" if ending == "host_on_an_older_coral" else "session.closed"
    row = _wake_row(world, run_id)
    assert (row.status, row.error_code) == (int(WorkStatus.FAILED), code)
    # The hold is gone; what stands is the step's own failure, which a Retry restarts.
    assert _causes(world, run_id) == [("failure_path", code, IMPLEMENT)]
    state = world.assert_fold_matches(run_id)
    assert retryable_activations(state) == (_slot(world, run_id).activation_id,)
    assert len(_inputs(world, run_id, RunnerHoldEnded)) == 1


async def test_a_relaunched_runner_that_already_runs_a_turn_is_not_re_prompted(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)
    sessions.dispatch.sessions[session_id].status = "running"

    await sessions.drain()

    result = _result(_wake_row(world, run_id))
    assert (result["outcome"], result["turn_running"]) == ("relaunched", True)
    assert _nudges(sessions, session_id) == []
    slot = _slot(world, run_id)
    assert (slot.failed_turn, slot.retired_runners) == (None, (RUNNER,))


async def test_a_hold_end_that_cannot_be_committed_fails_the_wake_retryably(
    world: World, working: tuple[Sessions, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions, run_id = working
    session_id = await _held(world, sessions, run_id, polls=1)
    commit = world.bridge.commit_inputs
    contended = [True]

    def commit_inputs(**kwargs: Any) -> Any:
        snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
        ending = any(isinstance(item, RunnerHoldEnded) for item in kwargs["inputs"](snapshot))
        if ending and contended:
            contended.pop()
            raise RunContended("other commits kept winning")
        return commit(**kwargs)

    monkeypatch.setattr(world.bridge, "commit_inputs", commit_inputs)
    world.clock.advance(30)
    await sessions.drain()
    row = _wake_row(world, run_id)
    failed_once = (row.status, row.error_code, row.result)

    world.clock.advance(60)
    await sessions.drain()

    assert failed_once == (int(WorkStatus.PENDING), "run.contended", None)
    # The next try finds the relaunched runner connected and ends the hold then.
    assert _result(_wake_row(world, run_id))["outcome"] == "runner_back"
    assert _causes(world, run_id) == []
    assert len(_nudges(sessions, session_id)) == 1


async def test_a_runner_alive_after_a_long_offline_hold_still_gets_its_ten_minutes(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    # Offline for longer than the alive hold's horizon.
    await _held(world, sessions, run_id, polls=25)
    assert world.clock.epoch - START_EPOCH > 600
    sessions.relauncher.fallback = _alive
    world.clock.advance(30)
    await sessions.drain()
    alive_since = world.clock.epoch

    while world.clock.epoch - alive_since < 570:
        world.clock.advance(30)
        await sessions.drain()
        row = _wake_row(world, run_id)
        assert (row.status, row.error_code) == (int(WorkStatus.PENDING), "recovery.runner_alive")
        assert row.attempts == 0
    for _ in range(80):
        world.clock.advance(30)
        await sessions.drain()
        if _wake_row(world, run_id).status == int(WorkStatus.FAILED):
            break

    assert _wake_row(world, run_id).status == int(WorkStatus.FAILED)
    assert _causes(world, run_id) == [("infra", "recovery.runner_alive", IMPLEMENT)]


async def test_a_wake_for_a_generation_the_slot_left_skips_without_relaunching(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = sessions.session_of(run_id, IMPLEMENT)
    payload = json.loads(row_of(world, run_id, "send_input").payload)
    stale = {
        "effect_type": WAKE,
        "effect_key": f"{run_id}:98:runner_lost:{IMPLEMENT}",
        "engine_kind": "runner_lost",
        "engine_slot_id": IMPLEMENT,
        "generation": 2,
        "session_id": session_id,
        "runner_id": RUNNER,
        "slot_id": payload["slot_id"],
    }
    outcomes: list[EffectOutcome] = []

    async def recording(ctx: Any) -> EffectOutcome:
        outcome = await sessions.executors()[WAKE](ctx)
        outcomes.append(outcome)
        return outcome

    await run_executor_conformance(
        recording, effect_type=WAKE, payload=stale, workspace_id=WORKSPACE, run_id=run_id
    )

    assert [outcome.result for outcome in outcomes if isinstance(outcome, Completed)] == [
        {"outcome": "skipped", "turn_running": False}
    ] * 2
    assert sessions.relauncher.calls == []


async def test_a_session_deleted_while_it_relaunched_pauses_its_run_for_drift(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = await _held(world, sessions, run_id, polls=1)
    sessions.relauncher.answers.append(
        DriftDetected(DriftFinding("session_deleted", session_id, "deleted"))
    )

    world.clock.advance(30)
    await sessions.drain()

    assert _result(_wake_row(world, run_id))["outcome"] == "skipped"
    # The hold ends with the wake; the run waits on the drift pause, which Resume clears.
    assert [reason for reason, _detail, _subject in _causes(world, run_id)] == ["drift"]


# ── Re-check: every way a wake ends moves its step on ────────────────────────


def _infra_stages(world: World, run_id: str, slot_id: str = IMPLEMENT) -> list[int]:
    """The slot's armed infra backoff stages."""
    state = world.assert_fold_matches(run_id)
    return sorted(
        timer.stage
        for timer in state.timers
        if timer.kind == "infra_backoff" and timer.subject == slot_id
    )


def _no_status_answer(session_id: str) -> Literal["connected", "relaunched"]:
    raise CoralSessionError(
        "session.runner_status_unknown", f"no answer about {session_id}'s runner", retryable=True
    )


async def _until_the_wake_settles(world: World, sessions: Sessions, run_id: str) -> None:
    for _ in range(80):
        if _wake_row(world, run_id).status != int(WorkStatus.PENDING):
            return
        world.clock.advance(60)
        await sessions.drain()


# The restart's salvage and reset, as the host answers them.
_RESTART_REPLIES: dict[str, Any] = {
    "salvage": lambda request: {"ref": f"refs/coral/salvage/{request.op_key}", "commit": "f" * 40},
    "reset": {"head": "1" * 40},
}


@pytest.mark.parametrize(
    "ending",
    [
        "relaunched",
        "relaunched_running",
        "runner_back_running",
        "runner_back_idle",
        "permanent",
        "exhausted",
    ],
)
async def test_every_way_a_wake_ends_re_prompts_the_step_or_pauses_its_run(
    world: World, working: tuple[Sessions, str], ending: str
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)
    stages_at_loss = _infra_stages(world, run_id)
    fake = sessions.dispatch.sessions[session_id]
    if ending.startswith("runner_back"):
        sessions.relauncher.answers.append("connected")
    if ending.endswith("_running"):
        fake.status = "running"
    if ending == "permanent":
        sessions.relauncher.answers.append(
            CoralSessionError("session.host_unsupported", "update Coral on that host")
        )
    if ending == "exhausted":
        sessions.relauncher.fallback = _no_status_answer

    await sessions.drain()
    stages_in_flight = _infra_stages(world, run_id)
    await _until_the_wake_settles(world, sessions, run_id)

    # The wake replaced the ladder: no stage at the loss, while it ran, or after it.
    assert stages_at_loss == stages_in_flight == _infra_stages(world, run_id) == []
    state = world.assert_fold_matches(run_id)
    slot = _slot(world, run_id)
    if ending in ("relaunched", "runner_back_idle"):
        assert (state.status, slot.status, slot.failed_turn) == ("running", "working", None)
        assert len(_nudges(sessions, session_id)) == 1
    elif ending.endswith("_running"):
        # The turn the runner already runs is left to end; its end moves the step on.
        assert (state.status, slot.failed_turn, _nudges(sessions, session_id)) == (
            "running",
            None,
            [],
        )
        sessions.complete_turn(run_id, IMPLEMENT)
        await sessions.drain()
        # The turn ended without a handoff, so the step is nudged for one.
        assert (_slot(world, run_id).status, len(_nudges(sessions, session_id))) == ("working", 1)
    elif ending == "permanent":
        assert _causes(world, run_id) == [("failure_path", "session.host_unsupported", IMPLEMENT)]
        assert retryable_activations(state) == (slot.activation_id,)
        assert _nudges(sessions, session_id) == []
    else:
        row = _wake_row(world, run_id)
        assert (row.status, row.error_code) == (int(WorkStatus.FAILED), "infra.transient")
        assert _causes(world, run_id) == [("infra", "session.runner_status_unknown", IMPLEMENT)]
        assert _nudges(sessions, session_id) == []
        # A Resume re-prompts the step once and revives the wake, which adds no second prompt.
        sessions.relauncher.fallback = sessions._runner_back_or_relaunched
        resumed = _commit(world, run_id, ResumeRun())
        await sessions.drain()
        assert _rejections(resumed) == []
        assert _result(_wake_row(world, run_id))["outcome"] == "relaunched"
        assert len(_nudges(sessions, session_id)) == 1
        assert world.assert_fold_matches(run_id).status == "running"
        assert _infra_stages(world, run_id) == []


async def test_a_wake_waiting_on_its_steps_failure_is_dropped_by_the_retry_that_restarts_it(
    world: World,
) -> None:
    run_id = start(world, PAIR).id
    async with serving(world) as sessions:
        sessions.host.replies.update(_RESTART_REPLIES)
        await sessions.drain()
        waiting, failing = PAIR_SLOTS
        old = {slot_id: sessions.session_of(run_id, slot_id) for slot_id in PAIR_SLOTS}

        def answer(session_id: str) -> Literal["connected", "relaunched"]:
            if session_id == old[failing]:
                raise CoralSessionError("session.host_unsupported", "update Coral on that host")
            return _no_status_answer(session_id)

        sessions.relauncher.fallback = answer
        for slot_id in PAIR_SLOTS:
            _lose(world, sessions, run_id, slot_id)
        await sessions.drain()
        world.clock.advance(60)
        await sessions.drain()
        rows = _wake_rows(world, run_id)
        before_retry = {
            slot_id: (rows[slot_id].status, rows[slot_id].error_code) for slot_id in PAIR_SLOTS
        }
        calls = len(sessions.relauncher.calls)

        retried = _commit(world, run_id, RetryStep(node_id="work"))
        for _ in range(12):
            await sessions.drain()
            world.clock.advance(30)

        # One slot's wake failed for good; the other's waits on that pause.
        assert before_retry == {
            failing: (int(WorkStatus.FAILED), "session.host_unsupported"),
            waiting: (int(WorkStatus.PENDING), "run.paused"),
        }
        assert _rejections(retried) == []
        rows = _wake_rows(world, run_id)
        assert (rows[waiting].status, rows[waiting].error_code) == (
            int(WorkStatus.ABANDONED),
            "slot.generation_mismatch",
        )
        # Generation 1's wake never runs again; each slot's new session gets its brief.
        assert len(sessions.relauncher.calls) == calls
        state = world.assert_fold_matches(run_id)
        assert (state.status, state.causes) == ("running", ())
        for slot_id in PAIR_SLOTS:
            slot = _slot(world, run_id, slot_id)
            new = sessions.session_of(run_id, slot_id)
            assert (slot.session_generation, slot.status, slot.wakes) == (2, "working", 0)
            assert new != old[slot_id]
            assert len(sessions.messages(new)) == 1
            assert _restarted_prompts(sessions, old[slot_id]) == []
            assert _infra_stages(world, run_id, slot_id) == []


async def test_a_wake_failed_on_a_closed_session_is_retried_into_a_new_session_and_generation(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    sessions.host.replies.update(_RESTART_REPLIES)
    old = _lose(world, sessions, run_id)
    # Someone closed the working step's session.
    sessions.facade.sessions.states[(WORKSPACE, old)] = present(old, closed=True)
    await sessions.drain()
    row = _wake_row(world, run_id)
    failed = (row.status, row.error_code)
    paused = _causes(world, run_id)
    offered = retryable_activations(world.assert_fold_matches(run_id))

    retried = _commit(world, run_id, RetryStep(node_id="implement"))
    for _ in range(12):
        await sessions.drain()
        world.clock.advance(30)

    assert failed == (int(WorkStatus.FAILED), "session.closed")
    assert paused == [("failure_path", "session.closed", IMPLEMENT)]
    assert offered == (_slot(world, run_id).activation_id,)
    assert _rejections(retried) == []
    slot = _slot(world, run_id)
    new = sessions.session_of(run_id, IMPLEMENT)
    assert (slot.session_generation, slot.status, slot.wakes, slot.failed_turn) == (
        2,
        "working",
        0,
        None,
    )
    assert new != old
    # The new session gets the step's brief; the closed one gets nothing more.
    assert len(sessions.messages(new)) == 1
    assert _nudges(sessions, old) == []
    assert sessions.relauncher.calls == []
    state = world.assert_fold_matches(run_id)
    assert (state.status, state.causes) == ("running", ())


@pytest.mark.parametrize("held", [False, True])
async def test_a_runner_changed_refusal_is_retried_and_the_next_try_finds_the_runner_back(
    world: World, working: tuple[Sessions, str], held: bool
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)
    fake = sessions.dispatch.sessions[session_id]
    first_try = [True]

    def rebound_meanwhile(session_id: str) -> Literal["connected", "relaunched"]:
        if first_try:
            first_try.pop()
            # Another launch rebinds the session; its runner connects just after.
            fake.runner_id, fake.runner_alive = "runner-from-elsewhere", True
            raise CoralSessionError(
                "session.runner_changed", "moved to another runner", retryable=True
            )
        return sessions._runner_back_or_relaunched(session_id)

    if held:
        sessions.relauncher.answers.append(_host_offline())
    sessions.relauncher.fallback = rebound_meanwhile
    await sessions.drain()
    if held:
        world.clock.advance(30)
        await sessions.drain()
    row = _wake_row(world, run_id)
    refused = (row.status, row.error_code, row.held_since, row.attempts)
    causes_after_refusal = _causes(world, run_id)
    await _until_the_wake_settles(world, sessions, run_id)

    # A normal retry, not a hold: it spends an attempt, and any host hold ends with it.
    # Leaving a wait for an offline host, the retry also drops that wait's start.
    assert refused == (int(WorkStatus.PENDING), "session.runner_changed", None, 1)
    assert causes_after_refusal == []
    assert len(_inputs(world, run_id, RunnerHoldEnded)) == int(held)
    result = _result(_wake_row(world, run_id))
    assert (result["outcome"], result["turn_running"]) == ("runner_back", False)
    slot = _slot(world, run_id)
    assert (slot.retired_runners, slot.connection_epoch, slot.failed_turn) == ((), 1, None)
    assert fake.runner_id == "runner-from-elsewhere"
    assert len(_nudges(sessions, session_id)) == 1
    assert world.assert_fold_matches(run_id).status == "running"


async def test_each_hold_code_runs_its_own_horizon_across_offline_alive_offline_alive(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    host = ["offline"]

    def answer(session_id: str) -> Literal["connected", "relaunched"]:
        if host[0] == "offline":
            raise _host_offline()
        return _alive(session_id)

    sessions.relauncher.fallback = answer

    async def phase(state: str, seconds: int) -> list[tuple[int, str | None, int | None, int]]:
        host[0] = state
        seen = []
        for _ in range(seconds // 30):
            world.clock.advance(30)
            await sessions.drain()
            row = _wake_row(world, run_id)
            seen.append((row.status, row.error_code, row.held_since, row.attempts))
        return seen

    session_id = _lose(world, sessions, run_id)
    await sessions.drain()
    offline_since = world.clock.epoch
    # Offline for longer than the alive hold's horizon: no horizon, no attempt spent.
    offline = await phase("offline", 720)
    alive = await phase("alive", 300)
    alive_since = alive[0][2]
    offline_again = await phase("offline", 900)
    offline_again_since = offline_again[0][2]
    alive_again = await phase("alive", 570)
    alive_again_since = alive_again[0][2]
    await _until_the_wake_settles(world, sessions, run_id)

    hold, alive_hold = "recovery.host_offline", "recovery.runner_alive"
    pending = int(WorkStatus.PENDING)
    assert offline == [(pending, hold, offline_since, 0)] * len(offline)
    assert alive_since == offline_since + 750
    assert alive == [(pending, alive_hold, alive_since, 0)] * len(alive)
    assert offline_again_since == alive_since + 300
    assert offline_again == [(pending, hold, offline_again_since, 0)] * len(offline_again)
    # The second alive hold gets its own full ten minutes, however long the others ran.
    assert alive_again_since == offline_again_since + 900
    assert alive_again == [(pending, alive_hold, alive_again_since, 0)] * len(alive_again)
    row = _wake_row(world, run_id)
    assert row.status == int(WorkStatus.FAILED)
    assert world.clock.epoch - alive_again_since >= 600
    assert _causes(world, run_id) == [("infra", alive_hold, IMPLEMENT)]
    # Each offline phase held the step once; each alive answer ended that hold.
    assert len(_inputs(world, run_id, RunnerHeld)) == 2
    assert len(_inputs(world, run_id, RunnerHoldEnded)) == 2
    assert _slot(world, run_id).retired_runners == ()
    assert _restarted_prompts(sessions, session_id) == []


@pytest.mark.parametrize("person_paused", [False, True])
async def test_a_cleared_cause_releases_a_waiting_wake_only_when_host_holds_alone_remain(
    world: World, person_paused: bool
) -> None:
    run_id = start(world, PAIR).id
    async with serving(world) as sessions:
        await sessions.drain()
        held, limited = PAIR_SLOTS
        link = _host_comes_and_goes(sessions)
        _lose(world, sessions, run_id, held)
        await sessions.drain()
        # The other slot hits its plan limit; its probe clears that cause in 5 minutes.
        limited_session = sessions.session_of(run_id, limited)
        _commit(
            world,
            run_id,
            UsageLimited(slot_id=limited, fact_key=f"turn:{limited_session}:1:usage"),
        )
        if person_paused:
            _commit(world, run_id, PauseRun(reason="user", detail="paused by alice"))
        link.online = True
        world.clock.advance(30)
        await sessions.drain()
        waiting = _wake_rows(world, run_id)[held]
        waited = (waiting.status, waiting.error_code, waiting.available_at)
        calls = len(sessions.relauncher.calls)

        world.clock.advance(270)
        await sessions.drain()
        at_probe = _wake_rows(world, run_id)[held]
        calls_at_probe = len(sessions.relauncher.calls)
        causes_at_probe = _causes(world, run_id)

        assert waited == (int(WorkStatus.PENDING), "run.paused", world.clock.epoch + 30)
        assert calls == 1
        hold = ("infra", "infra.host_offline", held)
        if not person_paused:
            # The probe's commit left only the hold, so the wake checks the host at once.
            assert causes_at_probe == []
            assert calls_at_probe == 2
            assert _result(at_probe)["outcome"] == "relaunched"
            return
        # The person's pause still stands: the wake keeps waiting, and nothing relaunches.
        assert causes_at_probe == [hold, ("user", "paused by alice", "")]
        # Not released either: the row still waits out its own 300 s.
        assert (at_probe.status, at_probe.error_code, at_probe.available_at) == waited
        assert calls_at_probe == 1
        # Their Resume leaves only the hold, and the wake checks the host at once.
        _commit(world, run_id, ResumeRun())
        await sessions.drain()
        assert len(sessions.relauncher.calls) == 2
        assert _result(_wake_rows(world, run_id)[held])["outcome"] == "relaunched"
        assert _causes(world, run_id) == []


async def test_a_turn_failure_that_lands_during_the_alive_hold_re_prompts_and_pauses_nothing(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    session_id = _lose(world, sessions, run_id)
    sessions.relauncher.fallback = _alive
    await sessions.drain()
    # A lagging turn fact of the lost runner arms the slot's ladder while the wake holds.
    _commit(
        world,
        run_id,
        SessionFailed(
            slot_id=IMPLEMENT,
            failure_class="infra.transient",
            cause="turn_failed",
            fact_key=f"turn:{session_id}:1:transient",
            observed_at=world.clock.now,
        ),
    )
    armed = _infra_stages(world, run_id)
    seen: list[tuple[int, list[tuple[str, str, str]], int]] = []
    for _ in range(19):
        world.clock.advance(30)
        await sessions.drain()
        seen.append(
            (
                len(_nudges(sessions, session_id)),
                _causes(world, run_id),
                _wake_row(world, run_id).attempts,
            )
        )
    await _until_the_wake_settles(world, sessions, run_id)

    assert armed == [1, 2, 3]
    # Every stage came due while the wake was out: none re-prompted or paused the step.
    assert seen == [(0, [], 0)] * 19
    assert _infra_stages(world, run_id) == []
    assert _causes(world, run_id) == [("infra", "recovery.runner_alive", IMPLEMENT)]
    assert _nudges(sessions, session_id) == []


async def test_a_no_answer_try_inside_the_alive_hold_does_not_restart_its_ten_minutes(
    world: World, working: tuple[Sessions, str]
) -> None:
    sessions, run_id = working
    _lose(world, sessions, run_id)
    host = ["alive"]

    def answer(session_id: str) -> Literal["connected", "relaunched"]:
        if host[0] == "silent":
            # One status query the host does not answer in time, then alive again.
            host[0] = "alive"
            return _no_status_answer(session_id)
        return _alive(session_id)

    sessions.relauncher.fallback = answer
    await sessions.drain()
    alive_since = world.clock.epoch
    while world.clock.epoch - alive_since < 300:
        world.clock.advance(30)
        await sessions.drain()
    host[0] = "silent"
    while world.clock.epoch - alive_since < 690:
        world.clock.advance(30)
        await sessions.drain()

    row = _wake_row(world, run_id)
    # Ten minutes after the alive hold began it no longer holds: its tries spend attempts.
    assert row.error_code == "recovery.runner_alive"
    assert row.attempts >= 2
