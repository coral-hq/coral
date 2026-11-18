"""Status edges become turn facts: recorded, gathered, reconciled and folded into the run.

Tier A: the world's bridge on fake stores, the real session executors over fake
sessions, the turn-fact recorder and executor, and a drainer with the bridge's hold
policy. A test publishes edges as the server would and moves the clock.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from coral.bridge.bound_sessions import BoundSession
from coral.bridge.codec import decode_entries
from coral.bridge.keys import store_slot_id
from coral.bridge.mapping import (
    TURN_FACT,
    MapContext,
    orchestrator_create_draft,
    turn_signal_draft,
)
from coral.db.enum_codecs import RunPauseReason, RunStatus, WorkKind, WorkStatus
from coral.engine.types import PauseRun, SessionFailed, TurnEnded
from coral.omni.server.turn_facts import TurnFactRecorder
from coral.queue import FinishedWork
from coral.stores.fakes import FakeQueueStore
from coral.stores.protocols import WorkItem
from coral.stores.session_bindings import SessionBindingDraft
from tests.coral.bridge._world import (
    IMPLEMENT,
    USER,
    WORKSPACE,
    Agent,
    Sessions,
    World,
    finished,
    row_of,
    serving,
    settle,
    start,
)
from tests.coral.omni.fakes import present
from tests.coral.workspace._executor_fakes import FakeBindings

NUDGE = "Your turn ended without a handoff."
BACKOFF = "Your last turn stopped before it finished."
RESUME = "The run is running again."
OVERLOADED = "API Error: 529 Overloaded"


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


def _of(world: World, run_id: str, kind: type) -> list[Any]:
    return [command for command in _inputs(world, run_id) if isinstance(command, kind)]


def _texts(sessions: Sessions) -> list[str]:
    return [str(send["text"]) for send in sessions.messages()]


def _signals(world: World, run_id: str) -> list[WorkItem]:
    return [
        item
        for item in world.work(run_id)
        if item.kind == int(WorkKind.SIGNAL)
        and json.loads(item.payload).get("effect_type") == TURN_FACT
    ]


def _brief_id(sessions: Sessions) -> str:
    return str(sessions.messages()[0]["stable_id"])


async def test_an_engine_turn_that_completed_is_nudged_once(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)

    sessions.complete_turn(run_id, IMPLEMENT, turn_response_id="resp_1")
    # The same edge again, and a later report of the same turn, change nothing.
    sessions.publish(
        run_id, IMPLEMENT, "idle", turn_outcome="completed", turn_response_id="resp_1"
    )
    world.clock.advance(1)
    sessions.publish(run_id, IMPLEMENT, "idle", turn_outcome="completed")
    await sessions.drain()
    world.clock.advance(5)
    await sessions.drain()

    [ended] = _of(world, run_id, TurnEnded)
    assert ended.fact_key == f"turn:{session_id}:1:msg:{_brief_id(sessions)}"
    texts = _texts(sessions)
    assert len(texts) == 2 and texts[1].startswith(NUDGE)
    assert {item.status for item in _signals(world, run_id)} == {int(WorkStatus.SUCCEEDED)}


@pytest.mark.parametrize("turn", ["user_typed", "cancelled", "undecided"])
async def test_turns_the_engine_did_not_finish_never_nudge(
    world: World, briefed: tuple[Sessions, str], turn: str
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)
    fake = sessions.dispatch.sessions[session_id]
    edge: dict[str, Any] = {"turn_outcome": "completed"}
    if turn == "user_typed":
        sessions.dispatch.post_user_message(session_id, "typed-1", author=USER)
    elif turn == "cancelled":
        edge["turn_outcome"] = "cancelled"
    else:
        # The engine message is out of the walk's reach.
        fake.transcript.clear()

    sessions.complete_turn(run_id, IMPLEMENT, **edge)
    if turn == "cancelled":
        # A person's stop: the runner records the interrupted turn after its reply.
        sessions.dispatch.mark_interrupted(session_id)
    await sessions.drain()
    # The re-gather, without the edge, decides the same.
    world.clock.advance(300)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    assert _of(world, run_id, TurnEnded) == []
    assert len(sessions.messages()) == 1
    assert len(_signals(world, run_id)) == 2
    assert {item.status for item in _signals(world, run_id)} == {int(WorkStatus.SUCCEEDED)}
    assert world.run(run_id).status == int(RunStatus.RUNNING)


@pytest.mark.parametrize("ended_in", ["reply", "tool_call"])
@pytest.mark.parametrize("seen", ["edge", "re_gather"])
async def test_an_archived_step_session_pauses_its_run_for_drift_and_is_never_nudged(
    world: World, briefed: tuple[Sessions, str], ended_in: str, seen: str
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)
    sessions.dispatch.reply(session_id, assistant=ended_in == "reply")
    sessions.facade.sessions.states[(WORKSPACE, session_id)] = present(
        session_id, archived=True, archived_at="2026-01-01T12:00:02Z"
    )

    if seen == "edge":
        # The archive's teardown publishes the session's last edge.
        sessions.publish(run_id, IMPLEMENT, "idle", origin="archive_idle")
    else:
        sessions.dispatch.sessions[session_id].status = "idle"
        world.clock.advance(300)
        world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    assert _of(world, run_id, TurnEnded) == []
    assert len(sessions.messages()) == 1
    assert _status_of(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.DRIFT))
    causes = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state.causes
    assert [(cause.reason, cause.detail) for cause in causes] == [("drift", "session_archived")]
    [signal] = _signals(world, run_id)
    assert json.loads(signal.result or "{}") == {"turn_fact": "drift"}


@pytest.mark.parametrize("change", ["archived", "deleted"])
async def test_archiving_or_deleting_a_finished_step_session_is_no_drift(
    world: World, briefed: tuple[Sessions, str], change: str
) -> None:
    sessions, run_id = briefed
    agent = Agent(sessions)
    assert await agent.act() == 1
    await sessions.drain()
    state = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state
    assert [slot.status for slot in state.slots if slot.id == IMPLEMENT] == ["closed"]
    session_id = sessions.session_of(run_id, IMPLEMENT)
    sessions.facade.sessions.states[(WORKSPACE, session_id)] = (
        present(session_id, archived=True, archived_at="2026-01-01T12:00:02Z", closed=True)
        if change == "archived"
        else present(session_id, exists=False)
    )

    # A person tidies up the finished step while the run goes on to review.
    sessions.publish(run_id, IMPLEMENT, "idle", origin="archive_idle")
    await sessions.drain()

    [signal] = _signals(world, run_id)
    assert json.loads(signal.result or "{}") == {"turn_fact": "slot_closed"}
    assert world.run(run_id).status == int(RunStatus.RUNNING)
    await sessions.run(agent)
    assert world.run(run_id).status == int(RunStatus.COMPLETED)


async def test_a_closed_step_session_is_not_read(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)
    sessions.facade.sessions.states[(WORKSPACE, session_id)] = present(session_id, closed=True)

    sessions.complete_turn(run_id, IMPLEMENT)
    await sessions.drain()

    assert _of(world, run_id, TurnEnded) == []
    [signal] = _signals(world, run_id)
    assert json.loads(signal.result or "{}") == {"turn_fact": "session_closed"}
    assert world.run(run_id).status == int(RunStatus.RUNNING)


def _status_of(world: World, run_id: str) -> tuple[int, int | None]:
    run = world.run(run_id)
    return run.status, run.pause_reason


@pytest.mark.parametrize(
    ("tool_items", "beyond"), [(998, False), (999, True)], ids=["in_reach", "beyond_reach"]
)
async def test_a_turn_too_long_for_the_walk_is_re_prompted_not_left_silent(
    world: World, briefed: tuple[Sessions, str], tool_items: int, beyond: bool
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)
    sessions.dispatch.scan_limit = 1_000
    sessions.dispatch.reply(session_id, assistant=False, count=tool_items)

    # With its reply the turn is 999 or 1,000 items after the brief.
    sessions.complete_turn(run_id, IMPLEMENT)
    await sessions.drain()

    if not beyond:
        assert len(_of(world, run_id, TurnEnded)) == 1
        assert _texts(sessions)[-1].startswith(NUDGE)
        return
    [failed] = _of(world, run_id, SessionFailed)
    assert (failed.failure_class, failed.cause) == ("infra.transient", "turn_unreadable")
    assert failed.fact_key == f"turn:{session_id}:1:msg:{_brief_id(sessions)}"
    assert _of(world, run_id, TurnEnded) == []
    # The backoff re-prompts the step; its next turn is in reach again.
    world.clock.advance(30)
    await sessions.drain()
    assert _texts(sessions)[-1].startswith(BACKOFF)
    sessions.complete_turn(run_id, IMPLEMENT)
    await sessions.drain()
    assert len(_of(world, run_id, TurnEnded)) == 1
    assert _texts(sessions)[-1].startswith(NUDGE)
    assert world.run(run_id).status == int(RunStatus.RUNNING)


async def test_late_edges_of_a_turn_the_nudge_superseded_change_nothing(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)
    fake = sessions.dispatch.sessions[session_id]
    ended_at_ms = int(world.clock.now.timestamp() * 1000)
    sessions.complete_turn(run_id, IMPLEMENT, turn_response_id="resp_1")
    world.clock.advance(1)
    await sessions.drain()
    # The nudged turn is at work when the first turn's other edges arrive, out of order.
    sessions.dispatch.reply(session_id, assistant=False)
    for status, outcome in (("failed", "failed"), ("idle", "completed"), ("idle", None)):
        sessions.publish(
            run_id,
            IMPLEMENT,
            status,
            turn_outcome=outcome,
            turn_response_id="resp_1" if outcome else None,
            error_code="RuntimeError" if status == "failed" else None,
            error_message=OVERLOADED if status == "failed" else None,
            observed_at_ms=ended_at_ms + 1,
        )
        fake.status = "running"
    await sessions.drain()

    assert len(_of(world, run_id, TurnEnded)) == 1
    assert _of(world, run_id, SessionFailed) == []
    assert len(_texts(sessions)) == 2
    assert len(_signals(world, run_id)) == 4
    assert {item.status for item in _signals(world, run_id)} == {int(WorkStatus.SUCCEEDED)}


async def test_a_person_typing_into_the_step_never_nudges_and_its_handoff_still_advances(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)
    sessions.dispatch.reply(session_id, assistant=False, count=3)
    sessions.dispatch.post_user_message(session_id, "typed-1", author=USER)
    # The engine's turn ends, then the person's own turn fails.
    sessions.complete_turn(run_id, IMPLEMENT, turn_response_id="resp_1")
    world.clock.advance(1)
    sessions.dispatch.reply(session_id, assistant=False)
    sessions.fail_turn(run_id, IMPLEMENT, OVERLOADED)
    await sessions.drain()
    world.clock.advance(300)
    assert world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id).regathered == 1
    await sessions.drain()

    assert (_of(world, run_id, TurnEnded), _of(world, run_id, SessionFailed)) == ([], [])
    assert len(_texts(sessions)) == 1
    assert world.assert_fold_matches(run_id).timers == ()
    # The agent's handoff is still accepted; the person's input pauses it for a decision.
    agent = Agent(sessions)
    await sessions.run(agent)
    run = world.run(run_id)
    assert (run.status, run.pause_reason) == (int(RunStatus.PAUSED), int(RunPauseReason.DRIFT))
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
    await sessions.run(agent)
    assert world.run(run_id).status == int(RunStatus.COMPLETED)
    assert len(sessions.messages(session_id)) == 1


async def test_a_turn_of_many_tool_items_still_reads_as_the_engines(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    sessions.dispatch.reply(sessions.session_of(run_id, IMPLEMENT), assistant=False, count=120)

    sessions.complete_turn(run_id, IMPLEMENT)
    await sessions.drain()

    assert len(_of(world, run_id, TurnEnded)) == 1
    assert _texts(sessions)[-1].startswith(NUDGE)


@pytest.mark.parametrize("paused", [False, True], ids=["running", "paused"])
async def test_a_signal_for_a_slot_awaiting_its_send_is_held_then_applied_with_its_edge(
    world: World, paused: bool
) -> None:
    run = start(world)
    async with serving(world) as sessions:
        held: list[WorkItem] = []

        async def turn_fails_before_the_send_is_fed(finished: FinishedWork) -> None:
            payload = json.loads(finished.item.payload)
            if payload.get("engine_kind") != "send_input" or held:
                return
            if paused:
                world.bridge.commit_inputs(
                    workspace_id=WORKSPACE,
                    run_id=run.id,
                    inputs=lambda _snapshot: (
                        PauseRun(reason="user", detail="paused by a person"),
                    ),
                )
            sessions.fail_turn(run.id, IMPLEMENT, "API Error: 529 Overloaded")
            # The signal runs while the brief has no receipt yet.
            claimed = await sessions.drainer.drain_once()
            assert claimed is not None
            held.extend(_signals(world, run.id))

        sessions.before_feed = turn_fails_before_the_send_is_fed
        await sessions.drain()
        sessions.before_feed = None

        [signal] = held
        assert signal.status == int(WorkStatus.PENDING)
        assert signal.error_code == ("run.paused" if paused else "signal.awaiting_effect")
        assert signal.attempts == 0 and signal.held_since is not None
        assert _of(world, run.id, SessionFailed) == []
        if paused:
            world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor=USER)
        else:
            world.clock.advance(5)
        await sessions.drain()

    [failed] = _of(world, run.id, SessionFailed)
    # Applied after the receipt with the edge's own error.
    assert (failed.failure_class, failed.cause) == ("infra.transient", "529")
    assert world.run(run.id).status == int(RunStatus.RUNNING)


async def test_a_failed_turn_whose_edge_was_lost_backs_off_on_the_re_gather(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)
    sessions.dispatch.reply(session_id, assistant=False)
    sessions.dispatch.sessions[session_id].status = "failed"

    report = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    assert report.regathered == 1
    [failed] = _of(world, run_id, SessionFailed)
    assert (failed.failure_class, failed.cause) == ("infra.transient", "edge_lost")
    state = world.assert_fold_matches(run_id)
    assert {timer.kind for timer in state.timers} == {"infra_backoff"}
    assert world.run(run_id).status == int(RunStatus.RUNNING)


async def test_a_completed_turn_whose_edge_was_lost_is_nudged_by_the_re_gather(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)
    sessions.dispatch.reply(session_id)
    sessions.dispatch.sessions[session_id].status = "idle"

    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    assert len(_of(world, run_id, TurnEnded)) == 1
    assert _texts(sessions)[-1].startswith(NUDGE)


@pytest.mark.parametrize("queued", [False, True], ids=["delivered", "still_queued"])
async def test_a_lingering_failed_status_before_the_re_prompt_ran_builds_no_fact(
    world: World, briefed: tuple[Sessions, str], queued: bool
) -> None:
    sessions, run_id = briefed
    session_id = sessions.session_of(run_id, IMPLEMENT)
    fake = sessions.dispatch.sessions[session_id]
    sessions.fail_turn(run_id, IMPLEMENT, "API Error: 529 Overloaded")
    await sessions.drain()
    world.clock.advance(30)
    await sessions.drain()
    assert _texts(sessions)[-1].startswith(BACKOFF)
    if queued:
        fake.queued.append(fake.transcript.pop())

    # The status is still the first turn's: the re-prompt has not run.
    assert fake.status == "failed"
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()
    assert len(_of(world, run_id, SessionFailed)) == 1

    # Then the re-prompt runs and fails, and its edge is lost too.
    fake.transcript.extend(fake.queued)
    fake.queued.clear()
    sessions.dispatch.reply(session_id, assistant=False)
    world.clock.advance(300)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    first, second = _of(world, run_id, SessionFailed)
    assert (first.cause, second.cause) == ("529", "edge_lost")
    reprompt_id = str(sessions.messages()[-1]["stable_id"])
    assert second.fact_key == f"turn:{session_id}:1:msg:{reprompt_id}"


class _DownQueue(FakeQueueStore):
    """The world's queue store while the database is down: every write fails."""

    def enqueue_work(self, items: Any, **kwargs: Any) -> list[str]:
        raise ConnectionError("the database is down")


async def test_a_turn_end_lost_in_a_store_outage_is_nudged_after_recovery(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    outage = TurnFactRecorder(
        world.bound, _DownQueue(), clock=lambda: world.clock.epoch, sleep=lambda _s: None
    )
    sessions.recorder = outage
    outage.start()
    try:
        sessions.complete_turn(run_id, IMPLEMENT)
    finally:
        outage.close()
    assert (outage.dropped_failed, _signals(world, run_id)) == (1, [])

    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    assert len(_of(world, run_id, TurnEnded)) == 1
    assert _texts(sessions)[-1].startswith(NUDGE)


async def test_the_create_feedback_puts_the_step_session_in_the_index(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed

    assert world.bound.lookup(WORKSPACE, sessions.session_of(run_id, IMPLEMENT)) == BoundSession(
        run_id=run_id,
        engine_slot_id=IMPLEMENT,
        store_slot_id=store_slot_id(run_id, IMPLEMENT),
        generation=1,
    )


def test_a_create_finished_before_a_crash_is_indexed_by_the_resync_feed(world: World) -> None:
    run = start(world)
    step = settle(
        world,
        row_of(world, run.id, "create_session", engine_kind="create_session"),
        WorkStatus.SUCCEEDED,
        result={"session_id": "s" * 32, "role": "step", "generation": 1},
    )
    anchor = settle(
        world,
        row_of(world, run.id, "create_session"),
        WorkStatus.SUCCEEDED,
        result={"session_id": "a" * 32, "role": "anchor", "generation": 1},
    )
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    orchestrator = orchestrator_create_draft(
        MapContext(
            workspace_id=WORKSPACE,
            run_id=run.id,
            graph=snapshot.graph,
            state=snapshot.state,
            request_preview="",
            title=run.title,
            now=world.clock.now,
        )
    )
    world.queue.enqueue_work([orchestrator], workspace_id=WORKSPACE, now=world.clock.epoch)
    [queued] = world.queue.get_work([orchestrator.id], workspace_id=WORKSPACE)
    chosen = settle(world, queued, WorkStatus.SUCCEEDED, result={"session_id": "o" * 32})

    # The rows finished and the process died before feeding them.
    assert len(world.bound) == 0
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    world.bridge.feed(finished(chosen))
    world.bridge.feed(finished(anchor))

    assert world.bound.lookup(WORKSPACE, "s" * 32) == BoundSession(
        run_id=run.id,
        engine_slot_id=IMPLEMENT,
        store_slot_id=store_slot_id(run.id, IMPLEMENT),
        generation=1,
    )
    found = world.bound.lookup(WORKSPACE, "o" * 32)
    assert found is not None and (found.orchestrator, found.engine_slot_id) == (
        True,
        "orchestrator",
    )
    assert world.bound.lookup(WORKSPACE, "a" * 32) is None
    assert step.id != anchor.id


async def test_the_resync_re_gathers_working_slots_of_a_running_run_once_per_bucket(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed

    reports = [world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id) for _ in range(2)]
    one_bucket = _signals(world, run_id)
    world.clock.advance(300)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    two_buckets = _signals(world, run_id)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="paused by a person"),),
    )
    world.clock.advance(300)
    paused = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)

    assert [report.regathered for report in reports] == [1, 1]
    assert (len(one_bucket), len(two_buckets), paused.regathered) == (1, 2, 0)
    payload = json.loads(one_bucket[0].payload)
    assert "edge" not in payload
    assert (payload["session_id"], payload["engine_slot_id"], payload["generation"]) == (
        sessions.session_of(run_id, IMPLEMENT),
        IMPLEMENT,
        1,
    )
    assert world.run(run_id).pause_reason == int(RunPauseReason.USER)


async def test_a_working_slot_awaiting_its_re_prompt_is_not_re_gathered(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    sessions.fail_turn(run_id, IMPLEMENT, "API Error: 529 Overloaded")
    await sessions.drain()
    world.clock.advance(30)
    # Only the stage-1 timer runs: the slot works on, its re-prompt not yet delivered.
    assert await sessions.drainer.drain_once() is not None

    awaiting = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()
    delivered = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)

    assert (awaiting.regathered, delivered.regathered) == (0, 1)
    assert _texts(sessions)[-1].startswith(BACKOFF)


@pytest.mark.parametrize("binding", ["unbound", "other_run", "orchestrator"])
async def test_a_signal_of_a_session_the_slot_does_not_hold_changes_nothing(
    world: World, briefed: tuple[Sessions, str], binding: str
) -> None:
    sessions, run_id = briefed
    session_id = "x" * 32
    bindings = sessions.bindings
    assert isinstance(bindings, FakeBindings)
    if binding != "unbound":
        bindings.reserve(
            SessionBindingDraft(
                workspace_id=WORKSPACE,
                session_id=session_id,
                run_id=run_id if binding == "orchestrator" else "q" * 32,
                role="step",
                effect_key=f"{run_id}:orchestrator:1:create_session",
                slot_id="orchestrator" if binding == "orchestrator" else IMPLEMENT,
                slot_role="orchestrator" if binding == "orchestrator" else "step_agent",
                session_generation=1,
            )
        )
    slot = "orchestrator" if binding == "orchestrator" else IMPLEMENT
    draft = turn_signal_draft(
        run_id=run_id,
        session_id=session_id,
        engine_slot_id=slot,
        generation=1,
        idempotency_key=f"sig:{session_id}:resync:0",
        edge=None,
        available_at=world.clock.epoch,
    )
    world.queue.enqueue_work([draft], workspace_id=WORKSPACE, now=world.clock.epoch)
    version = world.run(run_id).version

    await sessions.drain()

    [row] = world.queue.get_work([draft.id], workspace_id=WORKSPACE)
    assert row.status == int(WorkStatus.SUCCEEDED)
    expected = "orchestrator" if binding == "orchestrator" else "unbound"
    assert json.loads(row.result or "{}") == {"turn_fact": expected}
    assert world.run(run_id).version == version


async def test_a_signal_with_a_malformed_payload_fails_permanently(
    world: World, briefed: tuple[Sessions, str]
) -> None:
    sessions, run_id = briefed
    draft = turn_signal_draft(
        run_id=run_id,
        session_id=sessions.session_of(run_id, IMPLEMENT),
        engine_slot_id=IMPLEMENT,
        generation=1,
        idempotency_key="sig:bad",
        edge=None,
        available_at=world.clock.epoch,
    )
    payload = {**json.loads(draft.payload), "edge": {"status": "idle"}}
    bad = dataclasses.replace(draft, payload=json.dumps(payload))
    world.queue.enqueue_work([bad], workspace_id=WORKSPACE, now=world.clock.epoch)

    await sessions.drain()

    [row] = world.queue.get_work([bad.id], workspace_id=WORKSPACE)
    assert (row.status, row.error_code) == (int(WorkStatus.FAILED), "effect.invalid_payload")
