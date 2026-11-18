"""A failed turn (529, 429, 401) pauses its run with the right cause; resume re-prompts the step.

Tier A, acceptance criterion 4: the world's bridge on fake stores with a manual
clock, the real session executors over fake sessions, the turn-fact recorder and
executor, and a drainer with the bridge's hold policy. Each failure arrives as
claude-sdk reports it: a failed status edge with its error code and text.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from coral.bridge.codec import decode_entries
from coral.db.enum_codecs import RunPauseReason, RunStatus, WorkStatus
from coral.engine.types import ResumeRun, SessionFailed, TimerDue, TurnEnded
from tests.coral.bridge._world import (
    IMPLEMENT,
    REVIEW,
    USER,
    WORKSPACE,
    Agent,
    Sessions,
    World,
    serving,
    start,
)

# claude-sdk's shapes, wrapped by the runtime: the status only at the start of a
# RuntimeError's text, or its auth code.
OVERLOADED = (
    "inner executor error: "
    'API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'
)
RATE_LIMITED = (
    "inner executor error: "
    'API Error: 429 {"type":"error","error":{"type":"rate_limit_error","message":"Rate limited"}}'
)
NOT_LOGGED_IN = "Invalid API key · Please run /login"
BACKOFF = "Your last turn stopped before it finished."
RESUME = "The run is running again."
TURN_ENDED = "Your turn ended without a handoff."


class SimulatedCrash(BaseException):
    """The process died; nothing in the code under test catches it."""


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


@pytest.fixture
async def briefed(world: World) -> AsyncIterator[tuple[Sessions, str]]:
    """A two-step run whose implementer got its brief and is working on it."""
    run = start(world)
    async with serving(world) as sessions:
        await sessions.drain()
        assert len(sessions.messages()) == 1
        yield sessions, run.id


def _inputs(world: World, run_id: str) -> list[Any]:
    world.assert_fold_matches(run_id)
    return [entry.input for entry in decode_entries(world.engine_log(run_id))]


def _failures(world: World, run_id: str) -> list[tuple[str, str]]:
    return [
        (command.failure_class, command.cause)
        for command in _inputs(world, run_id)
        if isinstance(command, SessionFailed)
    ]


def _texts(sessions: Sessions, run_id: str) -> list[str]:
    session_id = sessions.session_of(run_id, IMPLEMENT)
    return [str(send["text"]) for send in sessions.messages(session_id)]


def _status(world: World, run_id: str) -> tuple[int, int | None]:
    run = world.run(run_id)
    return run.status, run.pause_reason


RUNNING = (int(RunStatus.RUNNING), None)


async def _at(world: World, sessions: Sessions, start_at: Any, seconds: float) -> None:
    """Move the clock to ``seconds`` after ``start_at`` and run what came due."""
    world.clock.now = start_at
    world.clock.advance(seconds)
    await sessions.drain()


async def test_a_529_backs_off_with_re_prompts_then_pauses_infra_and_resume_re_prompts_once(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    failed_at = world.clock.now
    sessions.fail_turn(run_id, IMPLEMENT, OVERLOADED)
    await sessions.drain()
    assert _failures(world, run_id) == [("infra.transient", "529")]
    assert _status(world, run_id) == RUNNING

    # Stages 1 and 2 re-prompt; each re-prompted turn fails the same way.
    for stage_at in (30, 120):
        await _at(world, sessions, failed_at, stage_at)
        assert _texts(sessions, run_id)[-1].startswith(BACKOFF)
        assert _status(world, run_id) == RUNNING
        sessions.fail_turn(run_id, IMPLEMENT, OVERLOADED)
        await sessions.drain()
    # Stage 3 finds the slot still failing: the run pauses.
    await _at(world, sessions, failed_at, 480)

    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.INFRA))
    assert _failures(world, run_id) == [("infra.transient", "529")] * 3
    assert len(_texts(sessions, run_id)) == 3

    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
    await sessions.drain()
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    texts = _texts(sessions, run_id)
    assert len(texts) == 4 and texts[-1].startswith(RESUME)
    assert _status(world, run_id) == RUNNING
    # The re-prompted step hands off and the run finishes.
    await sessions.run(Agent(sessions))
    assert world.run(run_id).status == int(RunStatus.COMPLETED)


@pytest.mark.parametrize("stage", [1, 2])
async def test_a_529_whose_re_prompted_turn_recovers_at_a_stage_never_pauses(
    world: World, briefed: tuple[Sessions, str], stage: int
) -> None:
    sessions, run_id = briefed
    failed_at = world.clock.now
    sessions.fail_turn(run_id, IMPLEMENT, OVERLOADED)
    # The same failure reported again under another publish changes nothing.
    sessions.publish(
        run_id,
        IMPLEMENT,
        "failed",
        turn_outcome="failed",
        error_code="RuntimeError",
        error_message=OVERLOADED,
        observed_at_ms=int(failed_at.timestamp() * 1000) + 1,
    )
    await sessions.drain()
    stages = (30, 120)[:stage]
    for stage_at in stages:
        await _at(world, sessions, failed_at, stage_at)
        assert _texts(sessions, run_id)[-1].startswith(BACKOFF)
        if stage_at != stages[-1]:
            sessions.fail_turn(run_id, IMPLEMENT, OVERLOADED)
            await sessions.drain()

    # The latest re-prompted turn completes: every later stage only disarms.
    sessions.complete_turn(run_id, IMPLEMENT)
    await sessions.drain()
    await _at(world, sessions, failed_at, 480)

    assert _status(world, run_id) == RUNNING
    assert _failures(world, run_id) == [("infra.transient", "529")] * stage
    texts = _texts(sessions, run_id)
    assert len(texts) == 2 + stage and texts[-1].startswith(TURN_ENDED)
    state = world.assert_fold_matches(run_id)
    assert [timer for timer in state.timers if timer.kind == "infra_backoff"] == []
    ended = [command for command in _inputs(world, run_id) if isinstance(command, TurnEnded)]
    assert len(ended) == 1


async def test_a_re_prompted_turn_still_running_at_eight_minutes_is_not_paused(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    failed_at = world.clock.now
    sessions.fail_turn(run_id, IMPLEMENT, OVERLOADED)
    await sessions.drain()
    await _at(world, sessions, failed_at, 30)
    # The re-prompt is taken and its turn runs past every stage.
    sessions.publish(run_id, IMPLEMENT, "running", response_id="resp_2")

    for stage_at in (120, 480):
        await _at(world, sessions, failed_at, stage_at)

    assert _status(world, run_id) == RUNNING
    assert len(_texts(sessions, run_id)) == 2
    state = world.assert_fold_matches(run_id)
    assert [timer for timer in state.timers if timer.kind == "infra_backoff"] == []


async def test_a_resume_re_prompts_once_across_a_crash_between_its_commit_and_the_send(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    sessions.fail_turn(run_id, IMPLEMENT, "Invalid bearer token", code="claude_sdk_auth_failed")
    await sessions.drain()
    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.AUTH))
    session_id = sessions.session_of(run_id, IMPLEMENT)
    fake = sessions.dispatch.sessions[session_id]

    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)

    def crash() -> None:
        raise SimulatedCrash

    # The process dies after the re-prompt reached the session, before its row finished.
    sessions.dispatch.hooks["send_message"] = crash
    claimed = await sessions.drainer.claim()
    assert claimed is not None and json.loads(claimed.payload)["engine_kind"] == "nudge"
    with pytest.raises(SimulatedCrash):
        await sessions.drainer.run_claimed(claimed)
    del sessions.dispatch.hooks["send_message"]
    # A new process: the lease runs out and is reclaimed, the resync repairs, the drain retries.
    world.clock.advance(61)
    world.queue.reclaim_expired_work(now_fn=lambda: world.clock.now.timestamp())
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    reprompts = [
        item for item in fake.transcript if item.text.split("\n", 1)[-1].startswith(RESUME)
    ]
    assert len(reprompts) == 1
    [row] = world.queue.get_work([claimed.id], workspace_id=WORKSPACE)
    assert row.status == int(WorkStatus.SUCCEEDED)
    resumes = [command for command in _inputs(world, run_id) if isinstance(command, ResumeRun)]
    assert len(resumes) == 1
    assert _status(world, run_id) == RUNNING


async def test_a_429_pauses_plan_limit_and_its_probe_clears_and_re_prompts_even_after_a_recovery(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    limited_at = world.clock.now
    sessions.fail_turn(run_id, IMPLEMENT, RATE_LIMITED)
    await sessions.drain()
    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.PLAN_LIMIT))
    assert _failures(world, run_id) == [("plan.usage_limit", "429")]

    # The first probe (5 minutes) clears the pause and re-prompts the step.
    await _at(world, sessions, limited_at, 300)
    assert _status(world, run_id) == RUNNING
    assert _texts(sessions, run_id)[-1].startswith(RESUME)

    # The re-prompted turn recovers, which disarms the next probe; a later 429 still clears.
    sessions.complete_turn(run_id, IMPLEMENT)
    await sessions.drain()
    assert _texts(sessions, run_id)[-1].startswith(TURN_ENDED)
    limited_again = world.clock.now
    sessions.fail_turn(run_id, IMPLEMENT, RATE_LIMITED)
    await sessions.drain()
    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.PLAN_LIMIT))
    await _at(world, sessions, limited_again, 300)

    assert _status(world, run_id) == RUNNING
    texts = _texts(sessions, run_id)
    assert len(texts) == 4 and texts[-1].startswith(RESUME)
    assert len(_failures(world, run_id)) == 2


async def test_a_429_that_fails_again_after_its_probe_waits_for_the_doubled_probe(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    limited_at = world.clock.now
    sessions.fail_turn(run_id, IMPLEMENT, RATE_LIMITED)
    await sessions.drain()
    await _at(world, sessions, limited_at, 300)
    assert _status(world, run_id) == RUNNING
    assert len(_texts(sessions, run_id)) == 2

    # The probe's re-prompt hits the limit again: paused until the next probe (10 minutes).
    sessions.fail_turn(run_id, IMPLEMENT, RATE_LIMITED)
    await sessions.drain()
    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.PLAN_LIMIT))
    await _at(world, sessions, limited_at, 899)
    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.PLAN_LIMIT))
    assert len(_texts(sessions, run_id)) == 2
    await _at(world, sessions, limited_at, 900)

    assert _status(world, run_id) == RUNNING
    texts = _texts(sessions, run_id)
    assert len(texts) == 3 and texts[-1].startswith(RESUME)
    assert _failures(world, run_id) == [("plan.usage_limit", "429")] * 2


async def test_a_resume_before_the_plan_probe_re_prompts_once_and_the_probe_adds_none(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    limited_at = world.clock.now
    sessions.fail_turn(run_id, IMPLEMENT, RATE_LIMITED)
    await sessions.drain()
    await _at(world, sessions, limited_at, 60)
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
    await sessions.drain()
    assert len(_texts(sessions, run_id)) == 2

    await _at(world, sessions, limited_at, 300)

    assert _status(world, run_id) == RUNNING
    texts = _texts(sessions, run_id)
    assert len(texts) == 2 and texts[-1].startswith(RESUME)


async def test_a_401_after_a_resume_pauses_again_and_each_resume_re_prompts_once(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    for resumes in (1, 2):
        sessions.fail_turn(run_id, IMPLEMENT, NOT_LOGGED_IN, code="claude_sdk_auth_failed")
        await sessions.drain()
        assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.AUTH))
        world.clock.advance(60)
        world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
        await sessions.drain()
        world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
        await sessions.drain()
        texts = _texts(sessions, run_id)
        assert len(texts) == 1 + resumes and texts[-1].startswith(RESUME)
        assert _status(world, run_id) == RUNNING

    assert _failures(world, run_id) == [("auth", "claude_sdk_auth_failed")] * 2
    await sessions.run(Agent(sessions))
    assert world.run(run_id).status == int(RunStatus.COMPLETED)


async def test_a_401_pauses_auth_and_resume_re_prompts_once(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    sessions.fail_turn(run_id, IMPLEMENT, NOT_LOGGED_IN, code="claude_sdk_auth_failed")
    await sessions.drain()
    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.AUTH))
    assert _failures(world, run_id) == [("auth", "claude_sdk_auth_failed")]
    # Nothing re-prompts a paused run on its own.
    world.clock.advance(3_600)
    await sessions.drain()
    assert len(_texts(sessions, run_id)) == 1

    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
    await sessions.drain()

    texts = _texts(sessions, run_id)
    assert len(texts) == 2 and texts[-1].startswith(RESUME)
    assert _status(world, run_id) == RUNNING


async def test_a_failed_turn_after_an_accepted_handoff_changes_nothing(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    agent = Agent(sessions)
    assert await agent.act() == 1
    assert agent.calls[-1].reply.accepted
    version = world.run(run_id).version

    # The handed-off turn ends failed before its close runs.
    sessions.fail_turn(run_id, IMPLEMENT, OVERLOADED)
    claimed = await sessions.drainer.claim()
    assert claimed is not None
    if json.loads(claimed.payload).get("effect_type") != "turn_fact":
        await sessions.drainer.run_claimed(claimed)
        claimed = await sessions.drainer.claim()
        assert claimed is not None
    await sessions.drainer.run_claimed(claimed)

    assert _failures(world, run_id) == []
    assert world.run(run_id).version >= version
    await sessions.run(agent)
    assert _failures(world, run_id) == []
    assert world.run(run_id).status == int(RunStatus.COMPLETED)
    assert sessions.session_of(run_id, REVIEW)


async def test_turn_ends_without_a_handoff_are_nudged_up_to_the_cap_then_pause(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed

    for _ in range(4):
        world.clock.advance(1)
        sessions.complete_turn(run_id, IMPLEMENT)
        await sessions.drain()

    texts = _texts(sessions, run_id)
    assert len(texts) == 4 and all(text.startswith(TURN_ENDED) for text in texts[1:])
    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.REJECTED_CALLS))
    ended = [command for command in _inputs(world, run_id) if isinstance(command, TurnEnded)]
    assert len(ended) == 4


async def test_the_backoff_stages_fire_from_their_timer_rows(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    failed_at = world.clock.now
    sessions.fail_turn(run_id, IMPLEMENT, OVERLOADED)
    await sessions.drain()

    # One second early, the stage-1 row is held, not spent.
    await _at(world, sessions, failed_at, 29)
    assert len(_texts(sessions, run_id)) == 1
    await _at(world, sessions, failed_at, 30)

    fired = [command for command in _inputs(world, run_id) if isinstance(command, TimerDue)]
    assert [command.timer_key.rsplit(":", 1)[-1] for command in fired] == ["1"]
    assert _texts(sessions, run_id)[-1].startswith(BACKOFF)
