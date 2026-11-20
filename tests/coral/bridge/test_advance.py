"""A run on ``two_steps`` advances step to step unattended: briefs, handoffs, closes, done.

The real executors run over fake sessions and in-memory stores, drained on a manual
clock; a scripted agent answers each brief through the engine tools.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from coral.bridge.codec import decode_entries
from coral.bridge.executors import DECISION_THREAD_NAME, BoundedThreads
from coral.bridge.port import StoreDecisionPort
from coral.db.enum_codecs import RunStatus, WorkStatus
from coral.engine.types import PauseRun
from coral.queue import FinishedWork
from coral.tools.dispatch import ToolDispatcher
from coral.tools.handlers import PLANNERS
from coral.tools.schemas import ToolReply
from tests.coral.bridge._world import (
    IMPLEMENT,
    REVIEW,
    WORKSPACE,
    Agent,
    Sessions,
    World,
    serving,
    start,
)

REPORT = "Implemented the parser change in parser.py and added its tests."
ADVANCED_KINDS = [
    "start_run",
    "effect_completed",  # implementer created
    "effect_completed",  # its brief delivered
    "handoff_received",
    "handoff_evaluated",
    "effect_completed",  # implementer closed: review opens
    "effect_completed",  # reviewer created
    "effect_completed",  # its brief delivered
    "handoff_received",
    "handoff_evaluated",
    "effect_completed",  # reviewer closed: the run ends
]


@pytest.fixture
async def sessions(tmp_path: Path) -> AsyncIterator[Sessions]:
    async with serving(World.fake(tmp_path)) as served:
        yield served


def _kinds(sessions: Sessions, run_id: str) -> list[str]:
    return [entry.input.kind for entry in decode_entries(sessions.world.engine_log(run_id))]


def _briefs(sessions: Sessions, session_id: str) -> list[str]:
    return [
        str(message["text"])
        for message in sessions.messages(session_id)
        if str(message["text"]).startswith("Coral step brief.")
    ]


async def test_a_two_step_run_advances_unattended_to_completed(sessions: Sessions) -> None:
    world = sessions.world
    run = start(world)
    agent = Agent(sessions, reports={"implement": REPORT})

    await sessions.run(agent)

    # One session per slot, each created once, and one brief each.
    steps = [request for request in sessions.facade.requests if request.role == "step"]
    assert [request.engine_slot_id for request in steps] == [IMPLEMENT, REVIEW]
    implementer = sessions.session_of(run.id, IMPLEMENT)
    reviewer = sessions.session_of(run.id, REVIEW)
    assert implementer != reviewer
    assert [len(_briefs(sessions, session)) for session in (implementer, reviewer)] == [1, 1]
    assert len(sessions.messages()) == 2
    # The review brief quotes the implementer's report.
    assert REPORT in _briefs(sessions, reviewer)[0]
    # Two accepted handoffs, one from each step's own session.
    assert [(call.session_id, call.reply.accepted) for call in agent.calls] == [
        (implementer, True),
        (reviewer, True),
    ]
    assert _kinds(sessions, run.id) == ADVANCED_KINDS
    # Each handoff commit records the session that called.
    actors = {
        (entry.input.kind, row.actor_ref)
        for row, entry in zip(
            world.engine_log(run.id), decode_entries(world.engine_log(run.id)), strict=True
        )
        if entry.input.kind == "handoff_received"
    }
    assert actors == {("handoff_received", implementer), ("handoff_received", reviewer)}
    # Only the writer's close committed in the run worktree.
    assert sessions.host.ops().count("commit") == 1
    finished = world.run(run.id)
    assert finished.status == int(RunStatus.COMPLETED)
    assert finished.finished_at is not None
    assert world.assert_fold_matches(run.id).status == "completed"
    # Nothing is left to run: every row of the run finished.
    assert {item.status for item in world.work(run.id)} == {int(WorkStatus.SUCCEEDED)}
    # One create, brief and close row per step, beside the anchor's create.
    payloads = [json.loads(item.payload) for item in world.work(run.id)]
    assert Counter(payload["effect_type"] for payload in payloads) == {
        "create_session": 3,
        "send_input": 2,
        "close_slot": 2,
    }
    closed = [
        payload["session_id"] for payload in payloads if payload["effect_type"] == "close_slot"
    ]
    assert sorted(closed) == sorted([implementer, reviewer])


async def test_runs_side_by_side_on_a_small_decision_pool_each_advance_once_per_step(
    sessions: Sessions,
) -> None:
    """Every call is sent twice at once, as a resending runner; two threads decide them all."""
    world = sessions.world
    decisions = BoundedThreads(max_workers=2, thread_name_prefix=DECISION_THREAD_NAME)
    sessions.dispatcher = ToolDispatcher(
        StoreDecisionPort(world.bridge), PLANNERS, run_in_thread=decisions.run
    )
    runs = [start(world, start_key=f"start-{index}") for index in range(8)]
    agent = Agent(sessions, copies=2)
    try:
        await sessions.run(agent)
    finally:
        decisions.close()

    # A resent call gets its original's reply.
    replies: dict[tuple[str, str], list[ToolReply]] = {}
    for call in agent.calls:
        replies.setdefault((call.session_id, call.operation_id), []).append(call.reply)
    assert all(len(sent) == 2 and sent[0] == sent[1] for sent in replies.values())
    for run in runs:
        implementer = sessions.session_of(run.id, IMPLEMENT)
        reviewer = sessions.session_of(run.id, REVIEW)
        assert sorted(
            session
            for (session, _), sent in replies.items()
            if sent[0].accepted and session in (implementer, reviewer)
        ) == sorted([implementer, reviewer])
        # The review brief quotes this run's report and names no other run.
        [brief] = _briefs(sessions, reviewer)
        assert f"Finished implement in run {run.id}." in brief
        assert not [other.id for other in runs if other.id != run.id and other.id in brief]
        assert _kinds(sessions, run.id) == ADVANCED_KINDS
        assert world.run(run.id).status == int(RunStatus.COMPLETED)
        assert world.assert_fold_matches(run.id).status == "completed"


async def test_an_early_handoff_is_told_to_retry_and_is_accepted_on_its_retry(
    sessions: Sessions,
) -> None:
    """The agent hands off before the brief's completion is folded: the slot is not ready."""
    world = sessions.world
    run = start(world)
    agent = Agent(sessions)
    early: list[str | None] = []

    async def hand_off_before_the_feed(finished: FinishedWork) -> None:
        payload = json.loads(finished.item.payload)
        if payload.get("engine_kind") == "send_input" and not early:
            await agent.act()
            early.append(agent.calls[-1].reply.reason)

    sessions.before_feed = hand_off_before_the_feed
    await sessions.run(agent)

    assert early == ["evaluation_in_progress"]
    implementer = sessions.session_of(run.id, IMPLEMENT)
    assert [
        (call.reply.accepted, call.reply.reason)
        for call in agent.calls
        if call.session_id == implementer
    ] == [(False, "evaluation_in_progress"), (True, None)]
    # The refused call wrote nothing: the log is the unattended run's.
    assert _kinds(sessions, run.id) == ADVANCED_KINDS
    assert world.run(run.id).status == int(RunStatus.COMPLETED)


async def test_a_handoff_while_paused_is_refused_and_the_step_resubmits_after_resume(
    sessions: Sessions,
) -> None:
    world = sessions.world
    run = start(world)
    agent = Agent(sessions)
    # The implementer has its brief; the run pauses before it hands off.
    await sessions.run()
    implementer = sessions.session_of(run.id, IMPLEMENT)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
        actor="user:alice",
    )

    await agent.act()
    [paused] = agent.calls
    assert (paused.reply.accepted, paused.reply.reason) == (False, "run.paused")
    # Told to stop, the step ends its turn; its nudge waits for the resume.
    assert sessions.end_turn(run.id, IMPLEMENT).outcome.applied
    await sessions.run(agent)
    assert len(sessions.messages(implementer)) == 1

    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    await sessions.run(agent)

    # The resume re-prompted the step once, and it handed off again.
    [brief, nudge] = [str(message["text"]) for message in sessions.messages(implementer)]
    assert brief.startswith("Coral step brief.")
    assert nudge.startswith("The run is running again.")
    assert [
        (call.reply.accepted, call.reply.reason)
        for call in agent.calls
        if call.session_id == implementer
    ] == [(False, "run.paused"), (True, None)]
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    state = world.assert_fold_matches(run.id)
    assert [slot.status for slot in state.slots] == ["closed", "closed"]
