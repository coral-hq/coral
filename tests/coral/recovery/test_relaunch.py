"""The liveness pass: a working step's missing runner is lost once its grace runs out.

The grace runs from this process's own first sighting of the runner missing.

Tier A: the world's bridge on fake stores and its session side (the real executors and
drainer over the fake session server, whose runner liveness a test sets as the server
would report it). The clock is the world's.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from coral.bridge.codec import decode_entries
from coral.bridge.mapping import NEXT_RESYNC_AT, resync_draft
from coral.bridge.service import EngineBridge
from coral.db.enum_codecs import WorkStatus
from coral.engine.types import EffectCompleted, PauseRun, RunnerLost
from coral.recovery.relaunch import LivenessPass, LivenessRef
from coral.stores.protocols import RunContended
from tests.coral.bridge._scripted_runs import accept
from tests.coral.bridge._world import (
    IMPLEMENT,
    WORKSPACE,
    Sessions,
    World,
    serving,
    start,
)
from tests.coral.omni.fakes import present
from tests.coral.slots._close_fakes import FakeSession

GRACE_S = 90
RUNNER = "runner-1"


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
    """R65 through the engine's own record: no pass ever sees the runner connected."""
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
