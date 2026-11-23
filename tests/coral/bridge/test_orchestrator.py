"""A workflow with a decision runs unattended: the orchestrator is created, asked, reminded.

Tier A: the world's bridge on fake stores with a manual clock, the real session
executors over fake sessions, the turn-fact recorder and executor, and a drainer
with the bridge's hold policy. A scripted agent hands off each step and a scripted
orchestrator answers each decision through ``coral_choose_arrow``.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from coral.bridge.codec import decode_entries
from coral.bridge.commit import Applied, build_commit
from coral.bridge.config import MAX_COMMIT_ROWS
from coral.bridge.keys import (
    ORCHESTRATOR_SLOT_ID,
    decision_request_key,
    effect_work_id,
    orchestrator_effect_key,
)
from coral.bridge.orchestrator import open_decisions, turn_input
from coral.db.enum_codecs import ActorKind, RunPauseReason, RunStatus, WorkStatus
from coral.engine import transition
from coral.engine.types import Input, OrchestratorTurn, PauseCause, PauseRun, ResumeRun, RetryRun
from coral.model.ids import effect_session_id
from coral.omni.protocols import CoralSessionError
from coral.queue.drainer import FinishedWork
from coral.signals.turn_facts import EdgeFacts
from coral.stores.fakes import FakeQueueStore
from coral.stores.protocols import CommitOutcome, Transition, WorkItem, WorkItemDraft
from tests.coral.bridge._scripted_runs import RUN_ID, accept, start_run
from tests.coral.bridge._world import (
    USER,
    WORKSPACE,
    Agent,
    Orchestrator,
    Sessions,
    World,
    finished,
    serving,
    settle,
    start,
)
from tests.coral.engine.drive import drive
from tests.coral.omni.fakes import present
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    fixture_text,
    step,
    workflow_text,
)
from tests.coral.workflow_builders import start as start_node

LOOP = fixture_text("loop")
# The step's close opens both decisions in one commit.
TWO_DECISIONS = workflow_text(
    [start_node(), step("plan"), decision("left"), decision("right"), end()],
    [
        arrow("a1", "start", "plan"),
        arrow("a2", "plan", "left"),
        arrow("a3", "plan", "right"),
        arrow("a4", "left", "end", label="ok"),
        arrow("a5", "right", "end", label="ok"),
    ],
)
WORK_1 = "work||a4:1:0"
WORK_2 = "work||a4:2:0"
DECISION_1 = "review||a4:1"
DECISION_2 = "review||a4:2"
DECISION_3 = "review||a4:3"
REVISE = ("revise", "The parser change has no tests; add them.")
APPROVED = ("approved", "The tests cover the change.")
REQUEST = "Coral decision request."
REMINDER = "Reminder: this Coral decision is still waiting for your choice."
REREQUEST = "The run is running again, and this Coral decision still needs your choice."
INSTRUCTION = "Call coral_choose_arrow with decision_id"
# claude-sdk's shapes, wrapped by the runtime, as the step tests use them.
OVERLOADED = (
    "inner executor error: "
    'API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'
)
RATE_LIMITED = (
    "inner executor error: "
    'API Error: 429 {"type":"error","error":{"type":"rate_limit_error","message":"Rate limited"}}'
)
NOT_LOGGED_IN = "Invalid API key · Please run /login"


@pytest.fixture
async def sessions(tmp_path: Path) -> AsyncIterator[Sessions]:
    async with serving(World.fake(tmp_path)) as served:
        yield served


@pytest.fixture
async def asked(sessions: Sessions) -> tuple[Sessions, str]:
    """A loop run whose first pass handed off: its decision is open and the orchestrator asked."""
    run = start(sessions.world, LOOP)
    await sessions.run(Agent(sessions))
    assert [_opening(text) for text in _orchestrator_texts(sessions, run.id)] == [REQUEST]
    return sessions, run.id


def _record_commits(monkeypatch: pytest.MonkeyPatch, world: World) -> list[Transition]:
    """Every transition the run store applies from now on, in order."""
    applied: list[Transition] = []
    apply = world.runs.apply_transition

    def recording(
        run_id: str, expected_version: int, transition: Transition, **options: Any
    ) -> CommitOutcome:
        outcome = apply(run_id, expected_version, transition, **options)
        if outcome.applied:
            applied.append(transition)
        return outcome

    monkeypatch.setattr(world.runs, "apply_transition", recording)
    return applied


def _bridge_rows(transition: Transition) -> list[dict[str, Any]]:
    """The orchestrator's create and decision messages a transition queues."""
    payloads = [json.loads(draft.payload) for draft in transition.outbox_work]
    return [
        payload
        for payload in payloads
        if payload.get("bridge_item") in ("orchestrator", "decision")
    ]


def _orchestrator_texts(sessions: Sessions, run_id: str) -> list[str]:
    orchestrator = sessions.world.run(run_id).orchestrator_session_id
    return [
        str(send["text"]) for send in sessions.messages() if send["session_id"] == orchestrator
    ]


def _opening(text: str) -> str:
    return text.split("\n", 1)[0]


def _texts_of(sessions: Sessions, session_id: str) -> list[str]:
    return [str(send["text"]) for send in sessions.messages(session_id)]


def _status(world: World, run_id: str) -> tuple[int, int | None]:
    run = world.run(run_id)
    return run.status, run.pause_reason


def _decision_rows(world: World, run_id: str) -> list[WorkItem]:
    return [
        item
        for item in world.work(run_id)
        if json.loads(item.payload).get("bridge_item") == "decision"
    ]


def _orchestrator_creates(sessions: Sessions) -> int:
    return len([item for item in sessions.facade.requests if item.slot_role == "orchestrator"])


def _pause_and_resume(world: World, run_id: str) -> int:
    """A user pause and its resume; returns the run version the resume wrote."""
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
        actor=USER,
    )
    resumed = world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
    return resumed.outcome.version


def _orchestrator_create(world: World, run_id: str) -> WorkItem:
    [row] = world.queue.get_work(
        [effect_work_id(run_id, orchestrator_effect_key(run_id))], workspace_id=WORKSPACE
    )
    return row


def _signals_of(world: World, run_id: str, session_id: str) -> list[WorkItem]:
    return [
        item
        for item in world.work(run_id)
        if json.loads(item.payload).get("effect_type") == "turn_fact"
        and json.loads(item.payload).get("session_id") == session_id
    ]


async def _run_through_holds(sessions: Sessions, *actors: Any) -> None:
    """Run, then once more after the shortest hold, so a briefly held item gets its turn."""
    await sessions.run(*actors)
    sessions.world.clock.advance(5)
    await sessions.run(*actors)


# ── creation and requests ────────────────────────────────────────────────────


async def test_the_first_open_decision_creates_the_orchestrator_and_asks_it_in_one_commit(
    sessions: Sessions, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = sessions.world
    commits = _record_commits(monkeypatch, world)
    run = start(world, LOOP)

    await sessions.run(Agent(sessions))

    orchestrator = effect_session_id(WORKSPACE, orchestrator_effect_key(run.id))
    assert world.run(run.id).orchestrator_session_id == orchestrator
    # One commit opened the decision, named the orchestrator and queued its create and request.
    [opening] = [commit for commit in commits if commit.orchestrator_session_id is not None]
    assert opening.orchestrator_session_id == orchestrator
    rows = _bridge_rows(opening)
    assert [(row["effect_type"], row["bridge_item"]) for row in rows] == [
        ("create_session", "orchestrator"),
        ("send_input", "decision"),
    ]
    request = rows[1]
    assert request["effect_key"] == f"{run.id}:decision_request:{DECISION_1}"
    assert (request["session_id"], request["kind"]) == (orchestrator, "brief")
    assert all(not _bridge_rows(commit) for commit in commits if commit is not opening)
    # The create ran once, as the run's orchestrator; its session got the request.
    creates = [item for item in sessions.facade.requests if item.slot_role == "orchestrator"]
    assert [(item.engine_slot_id, item.generation) for item in creates] == [
        (ORCHESTRATOR_SLOT_ID, 1)
    ]
    assert sessions.agents.resolved[-1]["stance"] == "orchestrator"
    assert [_opening(text) for text in _texts_of(sessions, orchestrator)] == [REQUEST]
    assert _orchestrator_create(world, run.id).status == int(WorkStatus.SUCCEEDED)
    # Its binding is indexed, so its failed turns reach the run.
    bound = world.bound.lookup(WORKSPACE, orchestrator)
    assert bound is not None and (bound.orchestrator, bound.engine_slot_id) == (
        True,
        ORCHESTRATOR_SLOT_ID,
    )

    # The second decision is only asked: the orchestrator exists.
    commits.clear()
    await sessions.run(Agent(sessions), Orchestrator(sessions, [REVISE]))

    asking = [commit for commit in commits if _bridge_rows(commit)]
    assert [commit.orchestrator_session_id for commit in asking] == [None]
    [second] = _bridge_rows(asking[0])
    assert (second["effect_type"], second["effect_key"]) == (
        "send_input",
        f"{run.id}:decision_request:{DECISION_2}",
    )
    assert (
        len([item for item in sessions.facade.requests if item.slot_role == "orchestrator"]) == 1
    )
    assert [_opening(text) for text in _texts_of(sessions, orchestrator)] == [REQUEST, REQUEST]


async def test_decisions_opened_together_share_one_create_and_get_one_question_each_per_resume(
    sessions: Sessions, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = sessions.world
    commits = _record_commits(monkeypatch, world)
    run = start(world, TWO_DECISIONS)

    await sessions.run(Agent(sessions))

    [opening] = [commit for commit in commits if _bridge_rows(commit)]
    assert opening.orchestrator_session_id == sessions.orchestrator_of(run.id)
    assert [row["effect_key"] for row in _bridge_rows(opening)] == [
        orchestrator_effect_key(run.id),
        f"{run.id}:decision_request:left||",
        f"{run.id}:decision_request:right||",
    ]
    versions = []
    for _ in range(2):
        versions.append(_pause_and_resume(world, run.id))
        await sessions.drain()
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    await sessions.drain()

    texts = _orchestrator_texts(sessions, run.id)
    assert [_opening(text) for text in texts] == [REQUEST] * 2 + [REREQUEST] * 4
    keys = {json.loads(item.payload)["effect_key"] for item in _decision_rows(world, run.id)}
    assert {
        f"{run.id}:decision_rerequest:{decision_id}:{version}"
        for decision_id in ("left||", "right||")
        for version in versions
    } <= keys
    orchestrator = Orchestrator(sessions, [("ok", "The plan holds."), ("ok", "So does this.")])
    await sessions.run(orchestrator)
    assert [call.reply.accepted for call in orchestrator.calls] == [True, True]
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    assert _orchestrator_creates(sessions) == 1


async def test_a_loop_run_advances_unattended_as_the_orchestrator_chooses_revise_then_approved(
    sessions: Sessions,
) -> None:
    world = sessions.world
    run = start(world, LOOP)
    agent = Agent(sessions, reports={"work": "Changed the parser in parser.py."})
    orchestrator = Orchestrator(sessions, [REVISE, APPROVED])

    await sessions.run(agent, orchestrator)

    chooser = sessions.orchestrator_of(run.id)
    assert [
        (
            call.session_id,
            call.arguments["decision_id"],
            call.arguments["label"],
            call.reply.accepted,
        )
        for call in orchestrator.calls
    ] == [(chooser, DECISION_1, "revise", True), (chooser, DECISION_2, "approved", True)]
    # Each request names the decision, its labels and the instruction before the quoted
    # report, and repeats the instruction after it.
    requests = _orchestrator_texts(sessions, run.id)
    assert [_opening(text) for text in requests] == [REQUEST, REQUEST]
    first = requests[0]
    report = first.index("> Changed the parser in parser.py.")
    assert (
        first.index(f"Decision id: {DECISION_1}")
        < first.index('Labels: "approved", "revise"')
        < first.index(INSTRUCTION)
        < report
        < first.rindex(f"Again: {INSTRUCTION}")
    )
    # The revise pass's brief carries the decision's reason.
    revised = _texts_of(sessions, sessions.session_of(run.id, WORK_2))[0]
    assert revised.startswith("Coral step brief.")
    assert f'The orchestrator chose "revise" at decision {DECISION_1}' in revised
    assert f"> {REVISE[1]}" in revised
    # The choices are the orchestrator's entries, recorded with its session.
    rows = world.engine_log(run.id)
    chosen = [
        (row.actor_kind, row.actor_ref, entry.input.label)
        for row, entry in zip(rows, decode_entries(rows), strict=True)
        if entry.input.kind == "choose_arrow"
    ]
    assert chosen == [
        (int(ActorKind.ORCHESTRATOR), chooser, "revise"),
        (int(ActorKind.ORCHESTRATOR), chooser, "approved"),
    ]
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    assert world.assert_fold_matches(run.id).status == "completed"
    assert (
        len([item for item in sessions.facade.requests if item.slot_role == "orchestrator"]) == 1
    )


async def test_only_the_runs_orchestrator_session_may_choose(asked: tuple[Sessions, str]) -> None:
    sessions, run_id = asked
    world = sessions.world
    step = sessions.session_of(run_id, WORK_1)
    version = world.run(run_id).version

    reply = await Orchestrator(sessions).choose(step, DECISION_1, *APPROVED)

    assert (reply.accepted, reply.reason) == (False, "not_orchestrator")
    assert world.run(run_id).version == version
    # The orchestrator's own choice is taken.
    taken = await Orchestrator(sessions).choose(
        sessions.orchestrator_of(run_id), DECISION_1, *APPROVED
    )
    assert taken.accepted
    await sessions.run()
    assert world.run(run_id).status == int(RunStatus.COMPLETED)


async def test_a_loop_at_its_limit_completes_with_one_session_brief_and_close_per_pass(
    sessions: Sessions,
) -> None:
    world = sessions.world
    run = start(world, LOOP)
    orchestrator = Orchestrator(sessions, [REVISE] * 4)

    await sessions.run(Agent(sessions), orchestrator)

    # The third revise is past the limit of 3 passes and goes to the end instead.
    assert [
        (call.arguments["decision_id"], call.reply.accepted, call.reply.redirected)
        for call in orchestrator.calls
    ] == [(DECISION_1, True, False), (DECISION_2, True, False), (DECISION_3, True, True)]
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    passes = ["work||a4:1:0", WORK_2, "work||a4:3:0"]
    steps = [
        item.engine_slot_id for item in sessions.facade.requests if item.slot_role == "step_agent"
    ]
    assert sorted(steps) == passes
    briefs = [
        send for send in sessions.messages() if str(send["text"]).startswith("Coral step brief.")
    ]
    assert sorted(sessions.session_of(run.id, slot) for slot in passes) == sorted(
        str(send["session_id"]) for send in briefs
    )
    closes = [
        item
        for item in world.work(run.id)
        if json.loads(item.payload).get("effect_type") == "close_slot"
    ]
    assert [item.status for item in closes] == [int(WorkStatus.SUCCEEDED)] * 3
    assert _orchestrator_creates(sessions) == 1
    assert [_opening(text) for text in _orchestrator_texts(sessions, run.id)] == [REQUEST] * 3


# ── reminders, re-requests and the resync ────────────────────────────────────


async def test_an_unanswered_decision_is_reminded_at_30_minutes_then_at_60(
    asked: tuple[Sessions, str],
) -> None:
    sessions, run_id = asked
    world = sessions.world
    opened_at = world.clock.now

    world.clock.now = opened_at + timedelta(minutes=29, seconds=59)
    await sessions.drain()
    early = [_opening(text) for text in _orchestrator_texts(sessions, run_id)]
    world.clock.now = opened_at + timedelta(minutes=30)
    await sessions.drain()
    reminded = world.assert_fold_matches(run_id)
    world.clock.now = opened_at + timedelta(minutes=60)
    await sessions.drain()
    escalated = world.assert_fold_matches(run_id)
    world.clock.now = opened_at + timedelta(hours=3)
    await sessions.drain()

    assert early == [REQUEST]
    texts = _orchestrator_texts(sessions, run_id)
    assert [_opening(text) for text in texts] == [REQUEST, REMINDER, REMINDER]
    assert all(f"Decision id: {DECISION_1}" in text for text in texts)
    assert [item.status for item in reminded.decisions] == ["reminded"]
    assert [item.status for item in escalated.decisions] == ["escalated"]
    # Each reminder is keyed by the watchdog's notify effect.
    notified = [effect.effect_key for effect in escalated.effects if effect.kind == "notify"]
    rows = [json.loads(item.payload) for item in _decision_rows(world, run_id)]
    assert sorted(row["effect_key"] for row in rows if row["kind"] == "nudge") == sorted(notified)
    assert len(notified) == 2

    await sessions.run(Orchestrator(sessions, [APPROVED]))
    assert world.run(run_id).status == int(RunStatus.COMPLETED)


async def test_a_decision_answered_after_its_reminder_is_not_reminded_again(
    asked: tuple[Sessions, str],
) -> None:
    sessions, run_id = asked
    world = sessions.world
    opened_at = world.clock.now
    world.clock.now = opened_at + timedelta(minutes=30)
    await sessions.drain()
    orchestrator = sessions.orchestrator_of(run_id)
    assert (await Orchestrator(sessions).choose(orchestrator, DECISION_1, *REVISE)).accepted
    # The choice disarms the alert still due at 60 minutes.
    state = world.assert_fold_matches(run_id)
    assert [timer for timer in state.timers if timer.subject == DECISION_1] == []

    for later in (timedelta(minutes=60), timedelta(hours=3)):
        world.clock.now = opened_at + later
        await sessions.drain()

    texts = _orchestrator_texts(sessions, run_id)
    assert [_opening(text) for text in texts] == [REQUEST, REMINDER]


async def test_resume_re_requests_the_open_decision_once(asked: tuple[Sessions, str]) -> None:
    sessions, run_id = asked
    world = sessions.world
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
        actor=USER,
    )

    resumed = world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
    await sessions.drain()
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    texts = _orchestrator_texts(sessions, run_id)
    assert [_opening(text) for text in texts] == [REQUEST, REREQUEST]
    assert f"Decision id: {DECISION_1}" in texts[-1]
    keys = [json.loads(item.payload)["effect_key"] for item in _decision_rows(world, run_id)]
    assert f"{run_id}:decision_rerequest:{DECISION_1}:{resumed.outcome.version}" in keys

    await sessions.run(Orchestrator(sessions, [APPROVED]))
    assert world.run(run_id).status == int(RunStatus.COMPLETED)


async def test_the_resync_queues_a_lost_request_again_by_its_recomputed_key(
    asked: tuple[Sessions, str],
) -> None:
    sessions, run_id = asked
    world = sessions.world
    [request] = _decision_rows(world, run_id)
    assert isinstance(world.queue, FakeQueueStore)
    del world.queue.work[(WORKSPACE, request.id)]

    report = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    assert report.enqueued == 1
    [again] = _decision_rows(world, run_id)
    assert (again.id, again.status) == (request.id, int(WorkStatus.SUCCEEDED))
    # The stable id of the request makes its second send the same message.
    orchestrator = sessions.orchestrator_of(run_id)
    transcript = sessions.dispatch.sessions[orchestrator].transcript
    assert len(transcript) == 1


class _LostFeedback(BaseException):
    """The process dies after a row finished, before its feedback ran."""


async def test_the_resync_indexes_an_orchestrator_whose_create_feedback_was_lost(
    sessions: Sessions,
) -> None:
    world = sessions.world
    run = start(world, LOOP)

    async def die_before_the_create_feed(done: FinishedWork) -> None:
        if json.loads(done.item.payload).get("bridge_item") == "orchestrator":
            raise _LostFeedback

    sessions.before_feed = die_before_the_create_feed
    with pytest.raises(_LostFeedback):
        await sessions.run(Agent(sessions))
    sessions.before_feed = None
    orchestrator = sessions.orchestrator_of(run.id)
    assert _orchestrator_create(world, run.id).status == int(WorkStatus.SUCCEEDED)
    assert world.bound.lookup(WORKSPACE, orchestrator) is None

    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    await sessions.drain()

    # Indexed again, so its failed turn reaches the run.
    assert world.bound.lookup(WORKSPACE, orchestrator) is not None
    sessions.fail_session(orchestrator, NOT_LOGGED_IN, code="claude_sdk_auth_failed")
    await sessions.drain()
    assert _status(world, run.id) == (int(RunStatus.PAUSED), int(RunPauseReason.AUTH))


async def test_a_failed_request_whose_feedback_was_lost_pauses_at_the_resync_and_resume_revives(
    asked: tuple[Sessions, str],
) -> None:
    sessions, run_id = asked
    world = sessions.world
    [request] = _decision_rows(world, run_id)
    # The request ran out of retries and the process died before feeding the failure.
    settle(
        world,
        request,
        WorkStatus.FAILED,
        error_code="infra.transient",
        result={"last_error_code": "session.host_offline"},
    )

    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)

    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(RunPauseReason.INFRA))
    state = world.assert_fold_matches(run_id)
    assert state.causes == (
        PauseCause(reason="infra", detail="decision:session.host_offline", subject=""),
    )
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
    await sessions.drain()

    [revived] = [row for row in _decision_rows(world, run_id) if row.id == request.id]
    assert revived.status == int(WorkStatus.SUCCEEDED)
    # The revived request finds its message already delivered; the re-request is new.
    transcript = sessions.dispatch.sessions[sessions.orchestrator_of(run_id)].transcript
    assert len(transcript) == 2 and REREQUEST in transcript[-1].text
    await sessions.run(Orchestrator(sessions, [APPROVED]))
    assert world.run(run_id).status == int(RunStatus.COMPLETED)


# ── failures ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("message", "code", "reason", "failure_class"),
    [
        (RATE_LIMITED, "RuntimeError", RunPauseReason.PLAN_LIMIT, "plan.usage_limit"),
        (NOT_LOGGED_IN, "claude_sdk_auth_failed", RunPauseReason.AUTH, "auth"),
    ],
    ids=["429", "401"],
)
async def test_a_failed_orchestrator_turn_pauses_its_run_and_resume_re_requests(
    asked: tuple[Sessions, str],
    message: str,
    code: str,
    reason: RunPauseReason,
    failure_class: str,
) -> None:
    sessions, run_id = asked
    world = sessions.world
    orchestrator = sessions.orchestrator_of(run_id)

    sessions.fail_session(orchestrator, message, code=code)
    [signal] = _signals_of(world, run_id, orchestrator)
    await sessions.drain()

    assert _status(world, run_id) == (int(RunStatus.PAUSED), int(reason))
    state = world.assert_fold_matches(run_id)
    expected = PauseCause(
        reason=reason.name.lower(), detail=f"orchestrator:{failure_class}", subject=""
    )
    assert state.causes == (expected,)
    [done] = world.queue.get_work([signal.id], workspace_id=WORKSPACE)
    assert json.loads(done.result or "{}") == {"turn_fact": "orchestrator_paused"}
    # The same failure seen again changes nothing.
    version = world.run(run_id).version
    world.clock.advance(1)
    sessions.fail_session(orchestrator, message, code=code)
    await sessions.drain()
    assert world.run(run_id).version == version

    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
    await sessions.drain()

    assert [_opening(text) for text in _orchestrator_texts(sessions, run_id)] == [
        REQUEST,
        REREQUEST,
    ]
    await sessions.run(Orchestrator(sessions, [APPROVED]))
    assert world.run(run_id).status == int(RunStatus.COMPLETED)


@pytest.mark.parametrize(
    "ran", [False, True], ids=["lingering_status", "failed_after_the_request"]
)
async def test_a_failed_orchestrator_turn_whose_edge_was_lost_pauses_at_the_re_gather(
    asked: tuple[Sessions, str], ran: bool
) -> None:
    sessions, run_id = asked
    world = sessions.world
    orchestrator = sessions.orchestrator_of(run_id)
    if ran:
        # The orchestrator took the request, then its turn failed; the edge never came.
        sessions.dispatch.reply(orchestrator, assistant=False)
    sessions.dispatch.sessions[orchestrator].status = "failed"

    world.clock.advance(300)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()

    [signal] = _signals_of(world, run_id, orchestrator)
    if not ran:
        # A status left from before the request: nothing to pause for.
        assert json.loads(signal.result or "{}") == {"turn_fact": "orchestrator_turn"}
        assert world.run(run_id).status == int(RunStatus.RUNNING)
        return
    # A lost runner is transient: the orchestrator backs off instead of pausing.
    assert json.loads(signal.result or "{}") == {"turn_fact": "orchestrator_backoff"}
    assert world.run(run_id).status == int(RunStatus.RUNNING)
    assert {timer.kind for timer in world.assert_fold_matches(run_id).timers} >= {
        "orchestrator_backoff"
    }


def _failed_edge(**fields: Any) -> EdgeFacts:
    values: dict[str, Any] = {"status": "failed", "observed_at_ms": 1, "turn_outcome": "failed"}
    values.update(fields)
    return EdgeFacts(**values)


_COMPLETED = EdgeFacts(status="idle", observed_at_ms=1, turn_outcome="completed")


@pytest.mark.parametrize(
    ("edge", "backing_off", "expected"),
    [
        # A failure no rule names is still resumable: an orchestrator has no step to retry.
        (
            _failed_edge(error_code="RuntimeError", error_message="something broke"),
            False,
            PauseRun(reason="infra", detail="orchestrator:agent.failed"),
        ),
        (
            _failed_edge(error_code="runner_disconnected"),
            False,
            PauseRun(reason="infra", detail="orchestrator:infra.runner_lost"),
        ),
        (
            _failed_edge(turn_outcome=None, error_code="budget_exhausted"),
            False,
            PauseRun(reason="plan_limit", detail="orchestrator:plan.spend_cap"),
        ),
        (
            _failed_edge(error_code="RuntimeError", error_message=OVERLOADED),
            False,
            OrchestratorTurn(failed=True, failure="infra.transient"),
        ),
        (_failed_edge(turn_outcome="cancelled"), True, None),
        (_failed_edge(origin="archive_failed"), True, None),
        (_COMPLETED, False, None),
        (_COMPLETED, True, OrchestratorTurn(failed=False)),
        (None, True, None),
    ],
    ids=[
        "unnamed",
        "runner_lost",
        "spend_cap",
        "transient",
        "cancelled",
        "archive",
        "completed",
        "completed_backing_off",
        "no_edge",
    ],
)
def test_an_orchestrator_turn_backs_off_or_pauses_by_the_step_classifier(
    edge: EdgeFacts | None, backing_off: bool, expected: Input | None
) -> None:
    assert turn_input(edge, backing_off) == expected


async def test_completed_orchestrator_turns_write_nothing(asked: tuple[Sessions, str]) -> None:
    sessions, run_id = asked
    world = sessions.world
    orchestrator = sessions.orchestrator_of(run_id)
    version = world.run(run_id).version

    sessions.dispatch.reply(orchestrator)
    sessions.publish_to(orchestrator, "idle", turn_outcome="completed")
    await sessions.drain()

    # Without a backoff to end, the turn is read and nothing is committed.
    [signal] = _signals_of(world, run_id, orchestrator)
    assert json.loads(signal.result or "{}") == {"turn_fact": "orchestrator_turn"}
    assert world.run(run_id).version == version


@pytest.mark.parametrize("seen", ["failed_turn", "archived", "failed_request"])
async def test_the_orchestrator_while_no_decision_waits_changes_nothing(
    asked: tuple[Sessions, str], seen: str
) -> None:
    sessions, run_id = asked
    world = sessions.world
    orchestrator = sessions.orchestrator_of(run_id)
    [request] = _decision_rows(world, run_id)
    assert (await Orchestrator(sessions).choose(orchestrator, DECISION_1, *REVISE)).accepted
    await sessions.drain()
    # The revise pass is working: no decision waits on the orchestrator.
    assert _texts_of(sessions, sessions.session_of(run_id, WORK_2))
    version = world.run(run_id).version

    if seen == "failed_turn":
        sessions.fail_session(orchestrator, OVERLOADED)
    elif seen == "archived":
        sessions.facade.sessions.states[(WORKSPACE, orchestrator)] = present(
            orchestrator, archived=True, archived_at="2026-01-01T12:00:02Z"
        )
        sessions.publish_to(orchestrator, "idle", origin="archive_idle", turn_outcome=None)
    else:
        # The first decision's request failed late, after its decision was made.
        failed = settle(world, request, WorkStatus.FAILED, error_code="session.deleted")
        world.bridge.feed(finished(failed))
    await sessions.drain()

    if seen != "failed_request":
        [signal] = _signals_of(world, run_id, orchestrator)
        assert json.loads(signal.result or "{}") == {"turn_fact": "no_input"}
    assert (world.run(run_id).version, _status(world, run_id)) == (
        version,
        (int(RunStatus.RUNNING), None),
    )


async def test_a_permanent_orchestrator_create_failure_pauses_the_run_visibly(
    sessions: Sessions,
) -> None:
    world = sessions.world
    sessions.agents.refusals["orchestrator"] = CoralSessionError(
        "session.agent_not_supported", "no orchestrator bundle"
    )
    run = start(world, LOOP)

    await _run_through_holds(sessions, Agent(sessions))

    assert _orchestrator_create(world, run.id).status == int(WorkStatus.FAILED)
    assert _status(world, run.id) == (int(RunStatus.PAUSED), int(RunPauseReason.FAILURE_PATH))
    state = world.assert_fold_matches(run.id)
    assert state.causes == (
        PauseCause(
            reason="failure_path", detail="orchestrator:session.agent_not_supported", subject=""
        ),
    )
    # The request waits for the orchestrator; nothing reached a session.
    assert _orchestrator_texts(sessions, run.id) == []
    assert {row.error_code for row in _decision_rows(world, run.id)} == {"run.paused"}


async def test_an_exhausted_orchestrator_create_pauses_infra_and_resume_revives_it(
    sessions: Sessions,
) -> None:
    world = sessions.world
    sessions.agents.refusals["orchestrator"] = CoralSessionError(
        "dispatch.unavailable", "the host did not answer", retryable=True
    )
    run = start(world, LOOP)
    await sessions.run(Agent(sessions))
    for _ in range(20):
        if _orchestrator_create(world, run.id).status == int(WorkStatus.FAILED):
            break
        world.clock.advance(60)
        await sessions.drain()

    assert _status(world, run.id) == (int(RunStatus.PAUSED), int(RunPauseReason.INFRA))
    assert world.assert_fold_matches(run.id).causes == (
        PauseCause(reason="infra", detail="orchestrator:dispatch.unavailable", subject=""),
    )
    # The request never failed: it waited for the create, then for the resume.
    assert {row.status for row in _decision_rows(world, run.id)} == {int(WorkStatus.PENDING)}

    del sessions.agents.refusals["orchestrator"]
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor=USER)
    await _run_through_holds(sessions, Orchestrator(sessions, [APPROVED]))

    assert _orchestrator_create(world, run.id).status == int(WorkStatus.SUCCEEDED)
    # The held request and the resume's re-request both reach the new session.
    assert sorted(_opening(text) for text in _orchestrator_texts(sessions, run.id)) == sorted(
        [REQUEST, REREQUEST]
    )
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    assert (
        len([item for item in sessions.facade.requests if item.slot_role == "orchestrator"]) == 1
    )


async def test_a_failed_create_or_request_row_fed_twice_pauses_once(
    asked: tuple[Sessions, str],
) -> None:
    sessions, run_id = asked
    world = sessions.world
    [request] = _decision_rows(world, run_id)
    failed = settle(world, request, WorkStatus.FAILED, error_code="session.deleted")

    world.bridge.feed(finished(failed))
    version = world.run(run_id).version
    world.bridge.feed(finished(failed))

    assert world.run(run_id).version == version
    assert world.assert_fold_matches(run_id).causes == (
        PauseCause(reason="failure_path", detail="decision:session.deleted", subject=""),
    )


@pytest.mark.parametrize("seen", ["archive_edge", "re_gather", "re_gather_after_the_alert"])
@pytest.mark.parametrize("change", ["archived", "deleted"])
async def test_an_archived_or_deleted_orchestrator_pauses_its_run_for_a_run_level_retry(
    asked: tuple[Sessions, str], seen: str, change: str
) -> None:
    sessions, run_id = asked
    world = sessions.world
    orchestrator = sessions.orchestrator_of(run_id)
    if seen == "re_gather_after_the_alert":
        # Both watchdog stages are spent: no further message to the orchestrator is due.
        for _stage in range(2):
            world.clock.advance(1_800)
            await sessions.drain()
        assert [_opening(text) for text in _orchestrator_texts(sessions, run_id)] == [
            REQUEST,
            REMINDER,
            REMINDER,
        ]
        assert world.assert_fold_matches(run_id).timers == ()
    sessions.facade.sessions.states[(WORKSPACE, orchestrator)] = (
        present(orchestrator, archived=True, archived_at="2026-01-01T12:00:02Z")
        if change == "archived"
        else present(orchestrator, exists=False)
    )
    sent = len(_orchestrator_texts(sessions, run_id))

    if seen == "archive_edge":
        sessions.publish_to(orchestrator, "idle", origin="archive_idle", turn_outcome=None)
    else:
        world.clock.advance(300)
        report = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
        assert report.regathered == 1
    await sessions.drain()

    assert _status(world, run_id) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    assert world.assert_fold_matches(run_id).causes == (
        PauseCause(
            reason="failure_path", detail=f"orchestrator:drift.session_{change}", subject=""
        ),
    )
    assert [
        json.loads(row.result or "{}") for row in _signals_of(world, run_id, orchestrator)
    ] == [{"turn_fact": "orchestrator_paused"}]
    assert len(_orchestrator_texts(sessions, run_id)) == sent


async def test_a_running_run_re_gathers_its_orchestrator_only_while_a_decision_waits(
    asked: tuple[Sessions, str],
) -> None:
    sessions, run_id = asked
    world = sessions.world
    orchestrator = sessions.orchestrator_of(run_id)

    waiting = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    await sessions.drain()
    assert (await Orchestrator(sessions).choose(orchestrator, DECISION_1, *REVISE)).accepted
    await sessions.drain()
    world.clock.advance(300)
    answered = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)

    # Waiting: only the orchestrator (the step is closed); answered: only the new pass.
    assert (waiting.regathered, answered.regathered) == (1, 1)
    [signal] = _signals_of(world, run_id, orchestrator)
    assert json.loads(signal.result or "{}") == {"turn_fact": "orchestrator_turn"}
    assert world.run(run_id).status == int(RunStatus.RUNNING)


async def test_a_reminder_due_while_paused_is_not_sent_and_the_resume_asks_once(
    asked: tuple[Sessions, str],
) -> None:
    sessions, run_id = asked
    world = sessions.world
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
        actor=USER,
    )
    world.clock.advance(3 * 3_600)
    await sessions.drain()

    assert [item.status for item in world.assert_fold_matches(run_id).decisions] == ["escalated"]
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor=USER)
    await sessions.drain()

    assert [_opening(text) for text in _orchestrator_texts(sessions, run_id)] == [
        REQUEST,
        REREQUEST,
    ]


def test_a_resume_with_more_open_decisions_than_a_commit_holds_drops_the_extra_re_asks(
    tmp_path: Path,
) -> None:
    # Start refuses such a workflow; a run pinned before that bound still resumes.
    names = [f"d{index}" for index in range(70)]
    graph = compile_text(
        workflow_text(
            [start_node(), step("plan"), *(decision(name) for name in names), end()],
            [
                arrow("a0", "start", "plan"),
                *(arrow(f"s{index}", "plan", name) for index, name in enumerate(names)),
                *(arrow(f"e{index}", name, "end", label="ok") for index, name in enumerate(names)),
            ],
        )
    )[0]
    driven = drive(graph, [start_run(graph)])
    driven = drive(graph, accept("plan||:0", "Planned."), after=driven)
    driven = drive(graph, [PauseRun(reason="user", detail="look")], after=driven)
    assert len(open_decisions(driven.state)) == 70
    world = World.fake(tmp_path)
    run = start(world, LOOP)
    loaded = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    assert run.id == RUN_ID
    named = dataclasses.replace(
        loaded.store,
        run=dataclasses.replace(
            loaded.store.run,
            orchestrator_session_id=effect_session_id(WORKSPACE, orchestrator_effect_key(run.id)),
        ),
    )
    snapshot = dataclasses.replace(loaded, store=named, graph=graph, state=driven.state)
    resumed = transition(graph, driven.state, ResumeRun(), world.clock(), snapshot.config)

    built = build_commit(
        snapshot,
        [Applied(entry=resumed.entry, before=driven.state, after=resumed.state)],
        now=world.clock(),
    )

    kinds = [json.loads(row.payload).get("kind") for row in built.outbox_work]
    assert len(built.outbox_work) == MAX_COMMIT_ROWS
    assert kinds == ["nudge"] * MAX_COMMIT_ROWS
    assert built.release_held_codes


# ── backoff ──────────────────────────────────────────────────────────────────


async def test_a_transiently_failing_orchestrator_is_re_asked_at_each_stage_then_paused(
    sessions: Sessions,
) -> None:
    world = sessions.world
    run = start(world, TWO_DECISIONS)
    await sessions.run(Agent(sessions))
    orchestrator = sessions.orchestrator_of(run.id)
    assert [_opening(text) for text in _orchestrator_texts(sessions, run.id)] == [REQUEST] * 2

    sessions.fail_session(orchestrator, OVERLOADED)
    await sessions.drain()
    [signal] = _signals_of(world, run.id, orchestrator)
    assert json.loads(signal.result or "{}") == {"turn_fact": "orchestrator_backoff"}
    assert world.run(run.id).status == int(RunStatus.RUNNING)

    # 30 s, then 2 min: one re-ask per open decision at each stage.
    for seconds, asked in ((30, 4), (90, 6)):
        world.clock.advance(seconds)
        await sessions.drain()
        texts = [_opening(text) for text in _orchestrator_texts(sessions, run.id)]
        assert texts == [REQUEST] * 2 + [REMINDER] * (asked - 2)
        assert world.run(run.id).status == int(RunStatus.RUNNING)

    # 8 min: still failing, the run pauses resumably and the ladder is spent.
    world.clock.advance(360)
    await sessions.drain()
    assert _status(world, run.id) == (int(RunStatus.PAUSED), int(RunPauseReason.INFRA))
    state = world.assert_fold_matches(run.id)
    assert state.causes == (
        PauseCause(reason="infra", detail="orchestrator:infra.transient", subject=""),
    )
    assert [timer.kind for timer in state.timers if timer.kind == "orchestrator_backoff"] == []
    assert len(_orchestrator_texts(sessions, run.id)) == 6

    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor=USER)
    await sessions.run(Orchestrator(sessions, [("ok", "Fine."), ("ok", "Fine.")]))
    assert world.run(run.id).status == int(RunStatus.COMPLETED)


async def test_a_completed_orchestrator_turn_ends_its_backoff(
    asked: tuple[Sessions, str],
) -> None:
    sessions, run_id = asked
    world = sessions.world
    orchestrator = sessions.orchestrator_of(run_id)
    sessions.fail_session(orchestrator, OVERLOADED)
    await sessions.drain()
    timers = world.assert_fold_matches(run_id).timers
    assert len([timer for timer in timers if timer.kind == "orchestrator_backoff"]) == 3

    world.clock.advance(1)
    sessions.dispatch.reply(orchestrator)
    sessions.publish_to(orchestrator, "idle", turn_outcome="completed")
    await sessions.drain()
    timers = world.assert_fold_matches(run_id).timers
    assert [timer for timer in timers if timer.kind == "orchestrator_backoff"] == []
    world.clock.advance(480)
    await sessions.drain()

    assert world.run(run_id).status == int(RunStatus.RUNNING)
    assert [_opening(text) for text in _orchestrator_texts(sessions, run_id)] == [REQUEST]

    # A second ladder in the same generation re-asks again at its own stages.
    sessions.fail_session(orchestrator, OVERLOADED)
    await sessions.drain()
    world.clock.advance(30)
    await sessions.drain()
    assert [_opening(text) for text in _orchestrator_texts(sessions, run_id)] == [
        REQUEST,
        REMINDER,
    ]


# ── replacement ──────────────────────────────────────────────────────────────


def _retry_run(world: World, run_id: str) -> None:
    commit = world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: (RetryRun(),), actor=USER
    )
    assert commit.outcome.applied


async def _lose_orchestrator(sessions: Sessions, run_id: str, change: str = "archived") -> str:
    """Archive or delete the run's orchestrator and let its edge pause the run."""
    orchestrator = sessions.orchestrator_of(run_id)
    sessions.facade.sessions.states[(WORKSPACE, orchestrator)] = (
        present(orchestrator, archived=True, archived_at="2026-01-01T12:00:02Z")
        if change == "archived"
        else present(orchestrator, exists=False)
    )
    sessions.publish_to(orchestrator, "idle", origin="archive_idle", turn_outcome=None)
    await sessions.drain()
    assert _status(sessions.world, run_id) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    return orchestrator


@pytest.mark.parametrize("change", ["archived", "deleted"])
async def test_one_retry_replaces_a_lost_orchestrator_and_the_new_one_finishes_the_run(
    asked: tuple[Sessions, str], monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    sessions, run_id = asked
    world = sessions.world
    [first_request] = _decision_rows(world, run_id)
    # Generation 1 keeps the keys stored runs have.
    assert json.loads(first_request.payload)["effect_key"] == decision_request_key(
        run_id, DECISION_1
    )
    old = await _lose_orchestrator(sessions, run_id, change)
    commits = _record_commits(monkeypatch, world)

    _retry_run(world, run_id)

    new = effect_session_id(WORKSPACE, orchestrator_effect_key(run_id, 2))
    [retry] = commits
    assert retry.orchestrator_session_id == new
    rows = [json.loads(draft.payload) for draft in retry.outbox_work]
    assert [
        (row["effect_type"], row["effect_key"], row.get("session_id"))
        for row in rows
        if row["effect_key"].startswith(f"{run_id}:{ORCHESTRATOR_SLOT_ID}:")
    ] == [
        ("cancel_sessions", f"{run_id}:orchestrator:1:fence", old),
        ("create_session", f"{run_id}:orchestrator:2:create_session", None),
        ("send_input", f"{run_id}:orchestrator:2:decision_request:{DECISION_1}", new),
    ]
    [logged] = [row for row in world.engine_log(run_id) if row.actor_kind == int(ActorKind.USER)][
        -1:
    ]
    assert json.loads(logged.body)["input"]["kind"] == "retry_run"
    # A resync right after finds every row of the new generation.
    assert world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id).enqueued == 0
    await sessions.drain()

    # The old session is fenced: stopped, labelled closed, its choice refused.
    assert sessions.dispatch.sessions[old].closed
    refused = await Orchestrator(sessions).choose(old, DECISION_1, *APPROVED)
    assert not refused.accepted
    await sessions.run(Orchestrator(sessions, [APPROVED]))

    assert world.run(run_id).status == int(RunStatus.COMPLETED)
    assert world.assert_fold_matches(run_id).orchestrator_generation == 2
    assert [_opening(text) for text in _texts_of(sessions, new)] == [REQUEST]
    assert _orchestrator_creates(sessions) == 2


async def test_a_replaced_generations_rows_change_nothing(asked: tuple[Sessions, str]) -> None:
    sessions, run_id = asked
    world = sessions.world
    [first_request] = _decision_rows(world, run_id)
    old = await _lose_orchestrator(sessions, run_id)
    _retry_run(world, run_id)
    await sessions.drain()
    version = world.run(run_id).version

    # A late failure of a generation-1 row feeds nothing.
    failed = settle(world, first_request, WorkStatus.FAILED, error_code="session.deleted")
    world.bridge.feed(finished(failed))
    assert world.run(run_id).version == version

    # A message still queued for the old session completes without being sent.
    payload = {
        **json.loads(first_request.payload),
        "effect_key": f"{run_id}:decision_rerequest:{DECISION_1}:99",
    }
    stale = WorkItemDraft.effect(
        run_id=run_id, idempotency_key=payload["effect_key"], payload=payload
    )
    world.queue.enqueue_work([stale], workspace_id=WORKSPACE, now=world.clock.epoch)
    sent = len(sessions.messages(old))
    await sessions.drain()

    [row] = world.queue.get_work([stale.id], workspace_id=WORKSPACE)
    assert (row.status, json.loads(row.result or "{}")) == (
        int(WorkStatus.SUCCEEDED),
        {"skipped": "stale_orchestrator"},
    )
    assert len(sessions.messages(old)) == sent
    assert world.run(run_id).status == int(RunStatus.RUNNING)


async def test_a_retry_of_a_failed_request_replaces_the_orchestrator(
    asked: tuple[Sessions, str],
) -> None:
    sessions, run_id = asked
    world = sessions.world
    [request] = _decision_rows(world, run_id)
    failed = settle(world, request, WorkStatus.FAILED, error_code="drift.session_archived")
    world.bridge.feed(finished(failed))
    assert world.assert_fold_matches(run_id).causes == (
        PauseCause(reason="failure_path", detail="decision:drift.session_archived", subject=""),
    )

    _retry_run(world, run_id)
    await sessions.run(Orchestrator(sessions, [APPROVED]))

    assert world.run(run_id).status == int(RunStatus.COMPLETED)
    assert world.run(run_id).orchestrator_session_id == effect_session_id(
        WORKSPACE, orchestrator_effect_key(run_id, 2)
    )
