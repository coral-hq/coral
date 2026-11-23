"""A run killed at any point and restarted ends once, with nothing duplicated, on every DB lane.

Each case runs a workflow on SQL stores until the process dies at one point
(``SimulatedCrash``). A new process then starts on the same database as the server
does: new engines, stores, bridge and drainer, its clock past the work lease, the
bound-session index refreshed and the startup sweep run (expired leases reclaimed,
each unfinished run's resync scheduled). It drains with the same scripted agents,
whose sessions, host and runners outlived the process; a call whose reply was lost
is resent under its operation id. The linear workflow and the decision workflow
are both killed at every shared point.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from coral.bridge.codec import decode_entries
from coral.bridge.commit import build_commit
from coral.bridge.keys import ORCHESTRATOR_SLOT_ID, orchestrator_effect_key
from coral.db import WorkRow
from coral.db.enum_codecs import (
    LogKind,
    RunPauseReason,
    RunStatus,
    StableIdKind,
    WorkKind,
    WorkStatus,
)
from coral.engine.types import RetryRun
from coral.model.ids import effect_session_id
from coral.stores.protocols import Transition, WorkItem
from coral.stores.stable_ids import SqlAlchemyStableIdStore
from tests.coral.bridge._world import (
    USER,
    WORKSPACE,
    Actor,
    Agent,
    Orchestrator,
    Sessions,
    World,
    restarted,
    run_id_for,
    serving,
    start,
)
from tests.coral.omni.fakes import present
from tests.coral.workflow_builders import fixture_text
from tests.stores.coral._faults import (
    SimulatedCrash,
    crash_around,
    crash_around_async,
    fresh_process,
)

RUN_ID = run_id_for()
ORCHESTRATOR = effect_session_id(WORKSPACE, orchestrator_effect_key(RUN_ID))
# The step each workflow opens first, a writer in both.
FIRST_STEP = {"two_steps": "implement||:0", "loop": "work||a4:1:0"}
# The orchestrator's choices on ``loop``: one pass back, then on to the end.
CHOICES = [("revise", "Add the missing tests."), ("approved", "The tests cover it.")]
# The work lease of the world's drainer.
LEASE_S = 60
# claude-sdk's 529 as the runtime reports it; its first backoff stage is due 30 s later.
OVERLOADED = 'API Error: 529 {"type":"error","error":{"type":"overloaded_error"}}'
STAGE_ONE_S = 30


def _payload(item: WorkItem) -> dict[str, Any]:
    return json.loads(item.payload)


def _step_create(item: WorkItem) -> bool:
    return _payload(item).get("engine_kind") == "create_session"


def _commit_of(kind: str, *, replied: bool = False) -> Callable[..., bool]:
    """Matches the run-store commit that logs an accepted ``kind`` input (and a tool reply)."""

    def matching(run_id: str, expected_version: int, transition: Transition, **_: Any) -> bool:
        kinds = {
            json.loads(log.body)["input"]["kind"]
            for log in transition.logs
            if log.kind == int(LogKind.ENGINE) and not log.audit_only
        }
        return kind in kinds and (not replied or transition.tool_reply is not None)

    return matching


def _names_the_orchestrator(
    run_id: str, expected_version: int, transition: Transition, **_: Any
) -> bool:
    return transition.orchestrator_session_id is not None


def _ends_the_run(run_id: str, expected_version: int, transition: Transition, **_: Any) -> bool:
    return transition.status == int(RunStatus.COMPLETED)


Install = Callable[[pytest.MonkeyPatch, Sessions], None]


@dataclass(frozen=True)
class CrashPoint:
    """
    Where the process dies, and what the run went through before it.

    :param claims: The process dies inside a claimed item, which the restart must
        reclaim once its lease expires and run to success.
    :param failed_turn: The first step's turn fails with a 529 and its first backoff
        stage re-prompts it before the step hands off.
    :param drift: The retried close reports pending input: the run pauses ``drift``
        and a person resumes it.
    """

    name: str
    install: Install
    claims: bool = False
    failed_turn: bool = False
    drift: bool = False


SHARED = (
    # W1: ``start_run`` committed, the engine's ``StartRun`` did not.
    CrashPoint(
        "start",
        lambda patch, sessions: crash_around(
            patch,
            sessions.world.runs,
            "apply_transition",
            when="before",
            matching=_commit_of("start_run"),
        ),
    ),
    # W3: the step create is claimed and has not run.
    CrashPoint(
        "claim",
        lambda patch, sessions: crash_around_async(
            patch, sessions.drainer, "run_claimed", when="before", matching=_step_create
        ),
        claims=True,
    ),
    # W4: the facade created and bound the step session; the row is still claimed.
    CrashPoint(
        "create",
        lambda patch, sessions: crash_around_async(
            patch,
            sessions.facade,
            "create_session",
            when="after",
            matching=lambda request, **_: (
                request.role == "step" and request.engine_slot_id != ORCHESTRATOR_SLOT_ID
            ),
        ),
        claims=True,
    ),
    # W4: the facade created the run's anchor session; its row is still claimed.
    CrashPoint(
        "anchor_create",
        lambda patch, sessions: crash_around_async(
            patch,
            sessions.facade,
            "create_session",
            when="after",
            matching=lambda request, **_: request.role == "anchor",
        ),
        claims=True,
    ),
    # W5: the step create's row finished; its feed never ran.
    CrashPoint(
        "finish",
        lambda patch, sessions: crash_around_async(
            patch,
            sessions.threads,
            "feed",
            when="before",
            matching=lambda finished: _step_create(finished.item),
        ),
    ),
    # The create's feed committed and queued the brief; the index push is lost with the process.
    CrashPoint(
        "feed",
        lambda patch, sessions: crash_around_async(
            patch,
            sessions.threads,
            "feed",
            when="after",
            matching=lambda finished: _step_create(finished.item),
        ),
    ),
    # W4: the brief reached the session; its row is still claimed.
    CrashPoint(
        "send",
        lambda patch, sessions: crash_around_async(
            patch,
            sessions.dispatch,
            "send_message",
            when="after",
            matching=lambda **send: send["session_id"] != ORCHESTRATOR,
        ),
        claims=True,
    ),
    # W6: the accepted handoff and its reply committed; the reply never reached the runner.
    CrashPoint(
        "handoff",
        lambda patch, sessions: crash_around(
            patch,
            sessions.world.runs,
            "apply_transition",
            when="after",
            matching=_commit_of("handoff_received", replied=True),
        ),
    ),
    # W4: the close took the turn-end tree and set the closed label, and has not stopped.
    CrashPoint(
        "close_before_stop",
        lambda patch, sessions: crash_around_async(
            patch, sessions.dispatch, "stop", when="before"
        ),
        claims=True,
    ),
    # W4: the stop is confirmed and the commit's HEAD not yet recorded, so the retry
    # cannot know of the stop and measures the tree again (session-facade contract).
    CrashPoint(
        "close_after_stop",
        lambda patch, sessions: crash_around_async(patch, sessions.dispatch, "stop", when="after"),
        claims=True,
    ),
    # W4: past the stop and the writer's commit: the retry flags the tree for review.
    CrashPoint(
        "close_after_commit",
        lambda patch, sessions: crash_around_async(
            patch,
            sessions.host,
            "request",
            when="after",
            matching=lambda host_id, op, **_: op == "commit",
        ),
        claims=True,
        drift=True,
    ),
    # W5: the writer's close row finished; its feed, which ends the activation, never ran.
    CrashPoint(
        "finish_close",
        lambda patch, sessions: crash_around_async(
            patch,
            sessions.threads,
            "feed",
            when="before",
            matching=lambda finished: _payload(finished.item).get("engine_kind") == "close_slot",
        ),
    ),
    # W8: the failed turn's ``SessionFailed`` committed; its signal row is still claimed.
    CrashPoint(
        "signal",
        lambda patch, sessions: crash_around(
            patch,
            sessions.world.runs,
            "apply_transition",
            when="after",
            matching=_commit_of("session_failed"),
        ),
        claims=True,
        failed_turn=True,
    ),
    # W8: the backoff stage's ``TimerDue`` and its nudge committed; the timer row is claimed.
    CrashPoint(
        "timer",
        lambda patch, sessions: crash_around(
            patch,
            sessions.world.runs,
            "apply_transition",
            when="after",
            matching=_commit_of("timer_due"),
        ),
        claims=True,
        failed_turn=True,
    ),
)
DECISION = (
    # W12: the commit opening the decision named the orchestrator and queued its create
    # and request.
    CrashPoint(
        "decision_open",
        lambda patch, sessions: crash_around(
            patch,
            sessions.world.runs,
            "apply_transition",
            when="after",
            matching=_names_the_orchestrator,
        ),
    ),
    # W12: the facade created and bound the orchestrator; its row is still claimed.
    CrashPoint(
        "orchestrator_create",
        lambda patch, sessions: crash_around_async(
            patch,
            sessions.facade,
            "create_session",
            when="after",
            matching=lambda request, **_: request.engine_slot_id == ORCHESTRATOR_SLOT_ID,
        ),
        claims=True,
    ),
    # W12: the decision request reached the orchestrator; its row is still claimed.
    CrashPoint(
        "decision_request",
        lambda patch, sessions: crash_around_async(
            patch,
            sessions.dispatch,
            "send_message",
            when="after",
            matching=lambda **send: send["session_id"] == ORCHESTRATOR,
        ),
        claims=True,
    ),
    # W6: the choice and its reply committed; the reply never reached the runner.
    CrashPoint(
        "choice",
        lambda patch, sessions: crash_around(
            patch,
            sessions.world.runs,
            "apply_transition",
            when="after",
            matching=_commit_of("choose_arrow", replied=True),
        ),
    ),
    # The commit that ends the run and queues its wind-down landed; nothing ran after it.
    CrashPoint(
        "ended",
        lambda patch, sessions: crash_around(
            patch,
            sessions.world.runs,
            "apply_transition",
            when="after",
            matching=_ends_the_run,
        ),
    ),
)
CASES = [
    *(
        pytest.param(workflow, point, id=f"{workflow}-{point.name}")
        for workflow in ("two_steps", "loop")
        for point in SHARED
    ),
    *(pytest.param("loop", point, id=f"loop-{point.name}") for point in DECISION),
]


def _actors(sessions: Sessions, workflow: str) -> list[Agent | Orchestrator]:
    actors: list[Agent | Orchestrator] = [Agent(sessions)]
    if workflow == "loop":
        actors.append(Orchestrator(sessions, CHOICES))
    return actors


async def _run(
    sessions: Sessions, workflow: str, actors: Sequence[Actor], *, failed_turn: bool
) -> None:
    """Start the run and drive it to its end."""
    start(sessions.world, fixture_text(workflow))
    if failed_turn:
        await sessions.drain()
        sessions.fail_turn(RUN_ID, FIRST_STEP[workflow], OVERLOADED)
        await sessions.drain()
        sessions.world.clock.advance(STAGE_ONE_S)
        await sessions.drain()
    await sessions.run(*actors)


def _restarted(crashed: Sessions) -> AbstractAsyncContextManager[Sessions]:
    """A new process on the dead one's database, started as the Coral lifespan starts it."""
    return restarted(crashed, lease_s=LEASE_S)


@dataclass(frozen=True)
class Row:
    id: str
    kind: int
    status: int
    attempts: int
    payload: dict[str, Any]


def _work(db_uri: str) -> dict[str, Row]:
    """Every work row of the run, by id, as a new process reads it."""
    with Session(fresh_process(db_uri)) as db:
        rows = db.execute(
            select(
                WorkRow.id, WorkRow.kind, WorkRow.status, WorkRow.attempts, WorkRow.payload
            ).where(WorkRow.workspace_id == WORKSPACE, WorkRow.run_id == RUN_ID)
        ).all()
    return {
        row_id: Row(row_id, kind, status, attempts, json.loads(payload))
        for row_id, kind, status, attempts, payload in rows
    }


def _messages(sessions: Sessions, session_id: str) -> Counter[StableIdKind]:
    """The kinds of the engine messages the session holds, each delivered exactly once."""
    assert sessions.world.db_uri is not None
    stable_ids = SqlAlchemyStableIdStore(sessions.world.db_uri)
    recorded = stable_ids.checksums_for_session(WORKSPACE, session_id, run_id=RUN_ID)
    delivered = Counter(
        item.item_id
        for item in sessions.dispatch.sessions[session_id].transcript
        if item.item_id in recorded
    )
    assert delivered == Counter(dict.fromkeys(recorded, 1)), session_id
    kinds: Counter[StableIdKind] = Counter()
    for stable_id in recorded:
        record = stable_ids.lookup(WORKSPACE, stable_id, run_id=RUN_ID)
        assert record is not None
        kinds[record.kind] += 1
    return kinds


def _once_each(counts: Mapping[Any, int]) -> bool:
    return set(counts.values()) == {1}


def _assert_completed_once(
    sessions: Sessions, workflow: str, actors: Sequence[Agent | Orchestrator], *, nudged: bool
) -> None:
    world = sessions.world
    assert world.db_uri is not None
    run = world.run(RUN_ID)
    assert (run.status, run.finished_at is not None) == (int(RunStatus.COMPLETED), True)
    state = world.assert_fold_matches(RUN_ID)
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=RUN_ID)
    assert build_commit(snapshot, (), now=world.clock()).is_empty
    slots = {(slot.id, slot.session_generation) for slot in state.slots}
    decisions = len(state.decisions)
    assert (len(slots), decisions) == ((2, 0) if workflow == "two_steps" else (2, 2))

    # One session per slot and generation, one anchor, one orchestrator for a decision.
    requests = sessions.facade.requests
    steps: dict[tuple[str | None, int | None], set[str]] = {}
    for request in requests:
        if request.role == "step" and request.engine_slot_id != ORCHESTRATOR_SLOT_ID:
            key = (request.engine_slot_id, request.generation)
            steps.setdefault(key, set()).add(request.effect_key)
    assert set(steps) == slots
    assert all(len(keys) == 1 for keys in steps.values())
    orchestrators = {
        request.effect_key
        for request in requests
        if request.engine_slot_id == ORCHESTRATOR_SLOT_ID
    }
    assert orchestrators == ({orchestrator_effect_key(RUN_ID)} if decisions else set())
    assert run.orchestrator_session_id == (ORCHESTRATOR if decisions else None)
    created = {session_id for _, session_id in sessions.facade.sessions.created}
    assert len(created) == len(slots) + 1 + (1 if decisions else 0)

    # One brief per step session and every engine message delivered once; only the
    # failed turn's backoff stage re-prompts. The orchestrator is asked once per decision.
    for slot_id, _ in slots:
        kinds = _messages(sessions, sessions.session_of(RUN_ID, slot_id))
        nudges = 1 if nudged and slot_id == FIRST_STEP[workflow] else 0
        assert (kinds[StableIdKind.BRIEF], kinds[StableIdKind.NUDGE]) == (1, nudges), slot_id
    if decisions:
        assert _messages(sessions, ORCHESTRATOR)[StableIdKind.BRIEF] == decisions

    # One handoff per slot, one choice per decision, in the log.
    inputs = [entry.input for entry in decode_entries(world.engine_log(RUN_ID))]
    handoffs = Counter(item.slot_id for item in inputs if item.kind == "handoff_received")
    assert set(handoffs) == {slot_id for slot_id, _ in slots} and _once_each(handoffs)
    choices = Counter(
        (item.node_id, item.item_path, item.iteration_path)
        for item in inputs
        if item.kind == "choose_arrow"
    )
    assert sum(choices.values()) == decisions and (not choices or _once_each(choices))
    # Each handoff and choice was answered as taken, a resent call by its stored reply
    # (the planner would answer a new call for it as a duplicate).
    answers = {
        (
            call.session_id,
            call.arguments.get("activation_id", call.arguments.get("decision_id")),
        ): (
            call.reply.accepted,
            call.reply.duplicate,
        )
        for actor in actors
        for call in actor.calls
    }
    assert len(answers) == len(slots) + decisions
    assert set(answers.values()) == {(True, False)}
    assert sum(len(actor.calls) for actor in actors) == len(slots) + decisions

    # Each writer committed once, at one recorded HEAD, also when its close ran again.
    commits = {
        (request.op_key, request.params["expected_head"])
        for request in sessions.host.requests
        if request.op == "commit"
    }
    writers = 1 if workflow == "two_steps" else 2
    assert (len(commits), len({op_key for op_key, _ in commits})) == (writers, writers)

    # One create, brief and close row per slot; no effect ran out of retries, and no
    # row is left claimed.
    work = _work(world.db_uri).values()
    assert int(WorkStatus.CLAIMED) not in {row.status for row in work}
    effects = [row for row in work if row.kind == int(WorkKind.EFFECT)]
    assert int(WorkStatus.FAILED) not in {row.status for row in effects}
    per_slot = Counter(
        (row.payload["engine_kind"], row.payload.get("kind"), row.payload["slot_id"])
        for row in effects
        if row.payload.get("engine_kind") in ("create_session", "send_input", "close_slot")
    )
    assert len(per_slot) == 3 * len(slots) and _once_each(per_slot)
    # The anchor and the orchestrator were wound down once, by the commit that ended the run.
    wind_down = sorted(
        row.payload["effect_key"]
        for row in effects
        if row.payload["effect_key"].endswith(":wind_down")
    )
    orchestrator_stop = [f"{RUN_ID}:{ORCHESTRATOR_SLOT_ID}:1:wind_down"] if decisions else []
    assert wind_down == [f"{RUN_ID}:anchor:wind_down", *orchestrator_stop]
    if decisions:
        assert sessions.dispatch.sessions[ORCHESTRATOR].closed


@pytest.mark.parametrize(("workflow", "point"), CASES)
async def test_a_run_killed_at_any_point_completes_after_a_restart_without_duplicates(
    coral_db_uri: str, monkeypatch: pytest.MonkeyPatch, workflow: str, point: CrashPoint
) -> None:
    async with serving(World.sql(coral_db_uri)) as sessions:
        actors = _actors(sessions, workflow)
        with monkeypatch.context() as patch:
            point.install(patch, sessions)
            with pytest.raises(SimulatedCrash):
                await _run(sessions, workflow, actors, failed_turn=point.failed_turn)
    assert sessions.world.db_uri is not None
    claimed = [
        row
        for row in _work(sessions.world.db_uri).values()
        if row.status == int(WorkStatus.CLAIMED)
    ]
    assert len(claimed) == int(point.claims)

    async with _restarted(sessions) as restarted:
        for actor in actors:
            actor.reconnect(restarted)
        await restarted.run(*actors)
        if point.drift:
            paused = restarted.world.run(RUN_ID)
            assert (paused.status, paused.pause_reason) == (
                int(RunStatus.PAUSED),
                int(RunPauseReason.DRIFT),
            )
            causes = restarted.world.bridge.load(
                workspace_id=WORKSPACE, run_id=RUN_ID
            ).state.causes
            assert [(cause.reason, cause.detail) for cause in causes] == [
                ("drift", "pending_input")
            ]
            restarted.world.bridge.resume_run(workspace_id=WORKSPACE, run_id=RUN_ID, actor=USER)
            await restarted.run(*actors)

        _assert_completed_once(restarted, workflow, actors, nudged=point.failed_turn)
    # The item the process died in ran again once its lease expired, and succeeded.
    after = _work(coral_db_uri)
    assert [(after[row.id].status, after[row.id].attempts) for row in claimed] == [
        (int(WorkStatus.SUCCEEDED), row.attempts + 1) for row in claimed
    ]


async def test_a_run_killed_right_after_a_run_level_retry_replaces_its_orchestrator_once(
    coral_db_uri: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with serving(World.sql(coral_db_uri)) as sessions:
        actors = _actors(sessions, "loop")
        start(sessions.world, fixture_text("loop"))
        await sessions.run(actors[0])
        # The orchestrator is archived while its decision waits: the run pauses for a retry.
        sessions.facade.sessions.states[(WORKSPACE, ORCHESTRATOR)] = present(
            ORCHESTRATOR, archived=True, archived_at="2026-01-01T12:00:02Z"
        )
        sessions.publish_to(ORCHESTRATOR, "idle", origin="archive_idle", turn_outcome=None)
        await sessions.drain()
        paused = sessions.world.run(RUN_ID)
        assert (paused.status, paused.pause_reason) == (
            int(RunStatus.PAUSED),
            int(RunPauseReason.FAILURE_PATH),
        )
        with monkeypatch.context() as patch:
            crash_around(
                patch,
                sessions.world.runs,
                "apply_transition",
                when="after",
                matching=_commit_of("retry_run"),
            )
            with pytest.raises(SimulatedCrash):
                sessions.world.bridge.commit_inputs(
                    workspace_id=WORKSPACE,
                    run_id=RUN_ID,
                    inputs=lambda _snapshot: (RetryRun(),),
                    actor=USER,
                )

    async with _restarted(sessions) as restarted:
        for actor in actors:
            actor.reconnect(restarted)
        await restarted.run(*actors)

        run = restarted.world.run(RUN_ID)
        replacement = effect_session_id(WORKSPACE, orchestrator_effect_key(RUN_ID, 2))
        assert (run.status, run.orchestrator_session_id) == (
            int(RunStatus.COMPLETED),
            replacement,
        )
        creates = [
            request.effect_key
            for request in restarted.facade.requests
            if request.engine_slot_id == ORCHESTRATOR_SLOT_ID
        ]
        assert creates == [orchestrator_effect_key(RUN_ID), orchestrator_effect_key(RUN_ID, 2)]
        # Both decisions were asked of the replacement once; the old one was fenced.
        assert _messages(restarted, replacement)[StableIdKind.BRIEF] == 2
        assert _messages(restarted, ORCHESTRATOR)[StableIdKind.BRIEF] == 1
        assert restarted.dispatch.sessions[ORCHESTRATOR].closed
    work = _work(coral_db_uri).values()
    assert int(WorkStatus.FAILED) not in {row.status for row in work}
