"""One commit per engine input batch: log rows, outbox, timers, projections, resume releases."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from coral.bridge.commit import (
    RESUME_RELEASE_CODES,
    Applied,
    CommitExtras,
    EngineSnapshot,
    build_commit,
)
from coral.bridge.config import LOCK_TIMEOUT_S, ceil_epoch_seconds
from coral.bridge.keys import anchor_effect_key, effect_work_id
from coral.bridge.mapping import UnsupportedStance
from coral.bridge.service import (
    USER_PAUSE_DETAIL,
    EngineBridge,
    EngineLoadFailed,
    RunNotRunnable,
)
from coral.db.enum_codecs import (
    ActorKind,
    LogKind,
    RunPauseReason,
    RunStatus,
    SlotStatus,
    WorkKind,
    WorkStatus,
)
from coral.engine import transition
from coral.engine.types import (
    CancelRun,
    EffectCompleted,
    HandoffEvaluated,
    Input,
    PauseRun,
    ResumeRun,
    SessionFailed,
    StartRun,
    Timer,
    TimerDue,
)
from coral.recovery.cancel import cancel_run_row
from coral.recovery.drift import DriftFinding, drift_log_checksum
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import (
    CommitOutcome,
    RunLogEntry,
    Transition,
    TransitionTooLarge,
    WorkItem,
    WorkItemDraft,
)
from tests.coral.bridge._scripted_runs import accept
from tests.coral.bridge._world import (
    IMPLEMENT,
    WORKSPACE,
    World,
    finished,
    row_of,
    run_spec,
    settle,
    start,
    start_without_engine,
)
from tests.coral.workflow_builders import arrow, end, step, workflow_text
from tests.coral.workflow_builders import start as start_node

FAILED_TURN = SessionFailed(
    slot_id=IMPLEMENT, failure_class="infra.transient", cause="529", fact_key="turn:s:1:msg:a"
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


def _applied(world: World, snapshot: EngineSnapshot, inputs: tuple[Input, ...]) -> list[Applied]:
    state = snapshot.state
    applied: list[Applied] = []
    for command in inputs:
        result = transition(snapshot.graph, state, command, world.clock(), snapshot.config)
        applied.append(Applied(entry=result.entry, before=state, after=result.state))
        state = result.state
    return applied


def _build(world: World, run_id: str, *inputs: Input, **options: object) -> Transition:
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
    applied = _applied(world, snapshot, inputs)
    return build_commit(snapshot, applied, now=world.clock(), **options)  # type: ignore[arg-type]


def _commit(world: World, run_id: str, *inputs: Input) -> None:
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: inputs
    )
    world.assert_fold_matches(run_id)


def _create_row(world: World, run_id: str, slot: str | None = None) -> WorkItem:
    rows = [
        item
        for item in world.work(run_id)
        if json.loads(item.payload).get("engine_kind") == "create_session"
        and (slot is None or json.loads(item.payload)["engine_slot_id"] == slot)
    ]
    assert len(rows) == 1
    return rows[0]


def _feed(world: World, item: WorkItem, status: WorkStatus, **outcome: Any) -> None:
    world.bridge.feed(finished(settle(world, item, status, **outcome)))


def _working(world: World) -> str:
    """A started two-step run whose implementer's create and brief completed."""
    run = start(world)
    created = {"session_id": "s" * 32, "role": "step", "generation": 1}
    _feed(world, _create_row(world, run.id), WorkStatus.SUCCEEDED, result=created)
    sent = {"session_id": "s" * 32, "stable_id": "m1"}
    _feed(world, row_of(world, run.id, "send_input"), WorkStatus.SUCCEEDED, result=sent)
    return run.id


def _causes(world: World, run_id: str) -> list[tuple[str, str]]:
    state = world.assert_fold_matches(run_id)
    return [(cause.reason, cause.detail) for cause in state.causes]


# ── build_commit ─────────────────────────────────────────────────────────────


def test_refused_entries_ride_audit_only_and_no_op_entries_are_not_stored(world: World) -> None:
    run = start(world)
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    repeat = StartRun(run_id=run.id, start_key=run.id, version_hash=snapshot.graph.content_hash)
    built = _build(
        world,
        run.id,
        PauseRun(reason="user", detail="look"),
        repeat,
        HandoffEvaluated(slot_id="no-such-slot", outcome="accepted"),
        actor="user:bob",
    )
    assert [(log.audit_only, json.loads(log.body)["input"]["kind"]) for log in built.logs] == [
        (False, "pause_run"),
        (True, "handoff_evaluated"),
    ]
    assert {log.actor_ref for log in built.logs} == {"user:bob"}
    assert built.logs[0].actor_kind == int(ActorKind.USER)
    assert (built.status, built.pause_reason) == (int(RunStatus.PAUSED), int(RunPauseReason.USER))


def test_a_commit_of_only_refused_entries_writes_nothing(world: World) -> None:
    run = start(world)
    built = _build(world, run.id, HandoffEvaluated(slot_id="no-such-slot", outcome="accepted"))
    assert built.is_empty


def test_effects_become_rows_and_unmapped_kinds_are_only_logged(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    run = start(world)
    with caplog.at_level(logging.INFO, logger="coral.bridge.commit"):
        built = _build(world, run.id, CancelRun())
    (cancel,) = built.outbox_work
    assert json.loads(cancel.payload)["effect_type"] == "cancel_sessions"
    assert "notify" in caplog.text
    assert (built.status, built.finished_at) == (int(RunStatus.CANCELLED), world.clock.epoch)


def test_timer_rows_are_queued_once_per_arming(world: World) -> None:
    run_id = _working(world)
    built = _build(world, run_id, FAILED_TURN)
    timers = [item for item in built.outbox_work if item.kind == int(WorkKind.TIMER)]
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
    armed = _applied(world, snapshot, (FAILED_TURN,))[-1].after.timers
    assert sorted(item.available_at for item in timers) == sorted(
        ceil_epoch_seconds(timer.due_at) for timer in armed
    )
    assert len(timers) == 3
    _commit(world, run_id, FAILED_TURN)
    again = _build(world, run_id, PauseRun(reason="user", detail="look"))
    assert not [item for item in again.outbox_work if item.kind == int(WorkKind.TIMER)]


def test_only_slot_rows_that_differ_are_written(world: World) -> None:
    run = start(world)
    unchanged = _build(world, run.id, PauseRun(reason="user", detail="look"))
    assert unchanged.agent_slots == ()
    key = json.loads(_create_row(world, run.id).payload)["effect_key"]
    created = _build(
        world, run.id, EffectCompleted(effect_key=key, payload={"session_id": "s" * 32})
    )
    (slot,) = created.agent_slots
    assert (slot.status, slot.session_id) == (int(SlotStatus.SESSION_CREATED), "s" * 32)


def test_a_resume_releases_holds_and_revives_unreceipted_effects(world: World) -> None:
    run = start(world)
    _commit(world, run.id, PauseRun(reason="user", detail="look"))
    built = _build(world, run.id, ResumeRun())
    assert set(built.release_held_codes) == set(RESUME_RELEASE_CODES)
    assert "run.paused" in built.release_held_codes
    assert any(code.startswith("drift.") for code in built.release_held_codes)
    assert set(built.revive_work_ids) == {
        _create_row(world, run.id).id,
        effect_work_id(run.id, anchor_effect_key(run.id)),
    }
    still_paused = _build(world, run.id, PauseRun(reason="user", detail="again"))
    assert (still_paused.release_held_codes, still_paused.revive_work_ids) == ((), ())


def test_timer_rows_are_dropped_first_when_the_outbox_is_full(world: World) -> None:
    run_id = _working(world)
    extra = [
        WorkItemDraft.signal(run_id=run_id, idempotency_key=f"x{index}", payload={})
        for index in range(62)
    ]
    built = _build(world, run_id, FAILED_TURN, extra_outbox=extra)
    timers = [item for item in built.outbox_work if item.kind == int(WorkKind.TIMER)]
    assert len(built.outbox_work) == 64
    assert len(timers) == 2
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
    armed = sorted(
        _applied(world, snapshot, (FAILED_TURN,))[-1].after.timers, key=lambda t: t.due_at
    )
    assert sorted(item.available_at for item in timers) == [
        ceil_epoch_seconds(timer.due_at) for timer in armed[:2]
    ]
    more = [
        WorkItemDraft.signal(run_id=run_id, idempotency_key=f"y{index}", payload={})
        for index in range(3)
    ]
    with pytest.raises(TransitionTooLarge):
        _build(world, run_id, FAILED_TURN, extra_outbox=[*extra, *more])


def test_more_than_64_log_rows_are_too_large(world: World) -> None:
    run = start(world)
    pauses = tuple(PauseRun(reason="user", detail=f"look {index}") for index in range(65))
    with pytest.raises(TransitionTooLarge):
        _build(world, run.id, *pauses)


def test_a_pause_made_outside_the_engine_stays_until_a_resume_lifts_it(world: World) -> None:
    run = start(world)
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    runs.runs[(WORKSPACE, run.id)] = dataclasses.replace(
        runs.runs[(WORKSPACE, run.id)],
        status=int(RunStatus.PAUSED),
        pause_reason=int(RunPauseReason.FAILURE_PATH),
    )
    key = json.loads(_create_row(world, run.id).payload)["effect_key"]
    fed = _build(world, run.id, EffectCompleted(effect_key=key, payload={"session_id": "s" * 32}))
    assert (fed.status, fed.pause_reason, fed.clear_pause_reason) == (None, None, False)
    assert fed.release_held_codes == ()
    lifted = _build(world, run.id, ResumeRun(), lift_store_pause=True)
    assert (lifted.status, lifted.clear_pause_reason) == (int(RunStatus.RUNNING), True)
    assert "run.paused" in lifted.release_held_codes


def test_an_engine_that_runs_again_on_its_own_lifts_the_rows_pause(world: World) -> None:
    run_id = _working(world)
    limited = SessionFailed(
        slot_id=IMPLEMENT,
        failure_class="plan.usage_limit",
        cause="429",
        fact_key="turn:s:1:msg:m1",
    )
    _commit(world, run_id, limited)
    assert world.run(run_id).pause_reason == int(RunPauseReason.PLAN_LIMIT)
    [probe] = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state.timers
    world.clock.now = probe.due_at

    # The plan probe clears the engine's own pause: the row follows it.
    cleared = _build(world, run_id, TimerDue(timer_key=probe.key))

    assert (cleared.status, cleared.clear_pause_reason) == (int(RunStatus.RUNNING), True)
    assert "run.paused" in cleared.release_held_codes


def _plan_limited(world: World) -> tuple[str, Timer]:
    """A working run paused ``plan_limit`` by a 429, and the probe that will clear it."""
    run_id = _working(world)
    limited = SessionFailed(
        slot_id=IMPLEMENT,
        failure_class="plan.usage_limit",
        cause="429",
        fact_key="turn:s:1:msg:m1",
    )
    _commit(world, run_id, limited)
    [probe] = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state.timers
    return run_id, probe


def test_a_drift_found_under_a_plan_pause_keeps_the_row_paused_when_the_probe_clears(
    world: World,
) -> None:
    run_id, probe = _plan_limited(world)
    world.bridge.pause_for_drift(
        workspace_id=WORKSPACE,
        run_id=run_id,
        cause="session_archived",
        body={"kind": "pause_run", "reason": "drift", "cause": "session_archived"},
        checksum_parts=("coral-drift", run_id, "session_archived", "s" * 32),
        now_us=0,
    )
    world.clock.now = probe.due_at

    cleared = _build(world, run_id, TimerDue(timer_key=probe.key))

    # The engine is still paused by the drift: the row stays paused, now showing the
    # drift, and nothing is released.
    assert (cleared.status, cleared.pause_reason, cleared.clear_pause_reason) == (
        None,
        int(RunPauseReason.DRIFT),
        False,
    )
    assert (cleared.release_held_codes, cleared.revive_work_ids) == ((), ())


def test_a_pause_made_on_the_row_alone_outlives_an_engine_pause_and_its_clearing(
    world: World,
) -> None:
    run_id = _working(world)
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    runs.runs[(WORKSPACE, run_id)] = dataclasses.replace(
        runs.runs[(WORKSPACE, run_id)],
        status=int(RunStatus.PAUSED),
        pause_reason=int(RunPauseReason.FAILURE_PATH),
    )
    limited = SessionFailed(
        slot_id=IMPLEMENT,
        failure_class="plan.usage_limit",
        cause="429",
        fact_key="turn:s:1:msg:m1",
    )
    _commit(world, run_id, limited)
    # The engine's own pause does not take over the row's reason.
    assert world.run(run_id).pause_reason == int(RunPauseReason.FAILURE_PATH)
    [probe] = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state.timers
    world.clock.now = probe.due_at

    cleared = _build(world, run_id, TimerDue(timer_key=probe.key))
    lifted = _build(world, run_id, ResumeRun(), lift_store_pause=True)

    assert (cleared.status, cleared.pause_reason, cleared.clear_pause_reason) == (
        None,
        None,
        False,
    )
    assert (cleared.release_held_codes, cleared.revive_work_ids) == ((), ())
    assert (lifted.status, lifted.clear_pause_reason) == (int(RunStatus.RUNNING), True)


# ── commands ─────────────────────────────────────────────────────────────────


def _two_slot_yaml() -> str:
    nodes = [start_node(), step("pair", ["implementer", "reviewer"]), end()]
    return workflow_text(nodes, [arrow("a1", "start", "pair"), arrow("a2", "pair", "end")])


def test_resume_releases_holds_revives_exhausted_effects_and_reprompts_in_one_commit(
    world: World,
) -> None:
    run = start(world, _two_slot_yaml())
    writer, reader = _create_row(world, run.id, "pair||:0"), _create_row(world, run.id, "pair||:1")
    _feed(world, writer, WorkStatus.SUCCEEDED, result={"session_id": "w" * 32, "generation": 1})
    sent = {"session_id": "w" * 32, "stable_id": "m"}
    _feed(world, row_of(world, run.id, "send_input"), WorkStatus.SUCCEEDED, result=sent)
    # The writer's turn fails on auth, and the reader's create runs out of retries.
    _commit(
        world,
        run.id,
        SessionFailed(
            slot_id="pair||:0", failure_class="auth", cause="401", fact_key="turn:w:1:m"
        ),
    )
    exhausted = {"last_error_code": "session.host_offline"}
    _feed(world, reader, WorkStatus.FAILED, error_code="infra.transient", result=exhausted)
    anchor = row_of(world, run.id, "create_session")
    assert json.loads(anchor.payload)["bridge_item"] == "anchor"
    settle(
        world,
        anchor,
        WorkStatus.PENDING,
        error_code="run.paused",
        held_since=world.clock.epoch,
        available_at=world.clock.epoch + 300,
    )
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.AUTH),
    )

    world.clock.advance(60)
    commit = world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:bob")

    assert commit.outcome.version == paused.version + 1
    resumed = world.run(run.id)
    assert (resumed.status, resumed.pause_reason) == (int(RunStatus.RUNNING), None)
    (revived,) = world.queue.get_work([reader.id], workspace_id=WORKSPACE)
    assert (revived.status, revived.attempts, revived.available_at) == (
        int(WorkStatus.PENDING),
        0,
        world.clock.epoch,
    )
    (released,) = world.queue.get_work([anchor.id], workspace_id=WORKSPACE)
    assert (released.available_at, released.held_since) == (world.clock.epoch, None)
    nudges = [
        json.loads(item.payload)
        for item in world.work(run.id)
        if json.loads(item.payload).get("engine_kind") == "nudge"
    ]
    assert [nudge["kind"] for nudge in nudges] == ["nudge"]
    resume_row = world.engine_log(run.id)[-1]
    assert (resume_row.actor_ref, json.loads(resume_row.body)["input"]["kind"]) == (
        "user:bob",
        "resume_run",
    )
    world.assert_fold_matches(run.id)


def _exhaust(world: World, item: WorkItem) -> WorkItem:
    exhausted = {"last_error_code": "session.host_offline"}
    return settle(world, item, WorkStatus.FAILED, error_code="infra.transient", result=exhausted)


def test_a_resume_revives_an_exhausted_effect_once_per_pause(world: World) -> None:
    run = start(world)
    create = _create_row(world, run.id)
    world.bridge.feed(finished(_exhaust(world, create)))
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    (revived,) = world.queue.get_work([create.id], workspace_id=WORKSPACE)
    assert revived.status == int(WorkStatus.PENDING)

    # The revived row runs out again before its feed lands; a second resume changes nothing.
    again = _exhaust(world, revived)
    version = world.run(run.id).version
    second = world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    assert not second.outcome.applied
    assert world.run(run.id).version == version
    (row,) = world.queue.get_work([create.id], workspace_id=WORKSPACE)
    assert row.status == int(WorkStatus.FAILED)

    world.bridge.feed(finished(again))
    assert world.run(run.id).pause_reason == int(RunPauseReason.INFRA)
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    (row,) = world.queue.get_work([create.id], workspace_id=WORKSPACE)
    assert (row.status, row.attempts) == (int(WorkStatus.PENDING), 0)
    world.assert_fold_matches(run.id)


def test_a_resume_never_revives_a_permanent_failure(world: World) -> None:
    run = start(world)
    failed = settle(
        world,
        _create_row(world, run.id),
        WorkStatus.FAILED,
        error_code="session.agent_not_supported",
    )
    world.bridge.feed(finished(failed))
    version = world.run(run.id).version
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    (row,) = world.queue.get_work([failed.id], workspace_id=WORKSPACE)
    assert (row.status, row.error_code) == (int(WorkStatus.FAILED), "session.agent_not_supported")
    paused = world.run(run.id)
    assert (paused.version, paused.pause_reason) == (version, int(RunPauseReason.FAILURE_PATH))


def test_cancel_of_the_widest_allowed_graph_commits(world: World) -> None:
    branches = [step(f"r{index}", ["reviewer"] * 16) for index in range(2)]
    nodes = [
        start_node(),
        step("split", ["reviewer"]),
        *branches,
        step("join", ["reviewer"]),
        end(),
    ]
    arrows = [arrow("a0", "start", "split"), arrow("a9", "join", "end")]
    for index, branch in enumerate(branches):
        arrows += [
            arrow(f"i{index}", "split", str(branch["id"])),
            arrow(f"o{index}", str(branch["id"]), "join"),
        ]
    run = start(world, workflow_text(nodes, arrows))
    # The split hands off and closes, which opens the region's 32 slots.
    _feed(world, _create_row(world, run.id), WorkStatus.SUCCEEDED, result={"session_id": "p" * 32})
    _feed(world, row_of(world, run.id, "send_input"), WorkStatus.SUCCEEDED, result={})
    _commit(world, run.id, *accept("split||:0", "split done"))
    _feed(world, row_of(world, run.id, "close_slot"), WorkStatus.SUCCEEDED, result={})
    state = world.assert_fold_matches(run.id)
    assert len([slot for slot in state.slots if slot.status != "closed"]) == 32

    commit = world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")

    assert commit.outcome.applied
    assert world.run(run.id).status == int(RunStatus.CANCELLED)
    cancels = [
        item
        for item in world.work(run.id)
        if json.loads(item.payload).get("effect_type") == "cancel_sessions"
    ]
    assert len(cancels) == 32
    world.assert_fold_matches(run.id)


def test_an_oversized_transition_pauses_the_run_visibly(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    run = start(world)
    flood = tuple(
        WorkItemDraft.signal(run_id=run.id, idempotency_key=f"x{index}", payload={})
        for index in range(65)
    )
    with caplog.at_level(logging.WARNING, logger="coral.bridge.service"):
        commit = world.bridge.commit_inputs(
            workspace_id=WORKSPACE,
            run_id=run.id,
            inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
            extra=lambda _snapshot, _applied: CommitExtras(outbox=flood),
        )
    assert commit.outcome.applied
    assert "pause_run" in caplog.text
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    assert _causes(world, run.id) == [("failure_path", "transition_too_large")]
    assert len(world.work(run.id)) == 2


def _refuse_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object) -> None:
        raise UnsupportedStance("slot has no step stance")

    monkeypatch.setattr("coral.bridge.commit.map_effect", refuse)


def test_a_mapping_that_cannot_succeed_pauses_instead_of_retrying(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world)
    _refuse_mapping(monkeypatch)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run.id, inputs=lambda _snapshot: (CancelRun(),)
    )
    assert _causes(world, run.id) == [("failure_path", "unsupported_stance")]


def test_a_start_whose_commit_cannot_be_built_pauses_the_run_row(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _refuse_mapping(monkeypatch)
    run = start(world)
    assert (run.status, run.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    (paused,) = world.runs.read_log(run.id, workspace_id=WORKSPACE)
    assert paused.kind == int(LogKind.PAUSED)
    assert json.loads(paused.body)["detail"] == "unsupported_stance"


def _runs(world: World) -> FakeRunStore:
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    return runs


def _logs(world: World, run_id: str) -> list[RunLogEntry]:
    return _runs(world).logs[(WORKSPACE, run_id)]


def test_a_corrupt_engine_row_pauses_the_run_once(world: World) -> None:
    run = start(world)
    logs = _logs(world, run.id)
    logs[0] = dataclasses.replace(logs[0], body='{"seq": "not an entry"}')
    for _ in range(2):
        with pytest.raises(EngineLoadFailed):
            world.bridge.fire_timer(workspace_id=WORKSPACE, run_id=run.id, timer_key="t")
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    (pause,) = [row for row in logs if row.kind == int(LogKind.PAUSED)]
    assert json.loads(pause.body)["detail"] == "engine.load_failed"
    assert "not an entry" not in pause.body


def test_a_missing_frozen_config_or_pinned_version_is_a_load_failure(world: World) -> None:
    run = start(world)
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    runs.specs[(WORKSPACE, run.id)] = dataclasses.replace(
        runs.specs[(WORKSPACE, run.id)], engine_config=None
    )
    with pytest.raises(EngineLoadFailed):
        world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    other = start(world, spec=run_spec(start_key="k2"), start_key="k2")
    runs.runs[(WORKSPACE, other.id)] = dataclasses.replace(
        runs.runs[(WORKSPACE, other.id)], version_id="0" * 32
    )
    with pytest.raises(EngineLoadFailed):
        world.bridge.load(workspace_id=WORKSPACE, run_id=other.id)


def test_a_graph_other_than_the_one_the_run_started_on_does_not_load(world: World) -> None:
    run = start(world)
    logs = _logs(world, run.id)
    body = json.loads(logs[0].body)
    body["input"]["version_hash"] = "c" * 64
    logs[0] = dataclasses.replace(logs[0], body=json.dumps(body))
    with pytest.raises(EngineLoadFailed):
        world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)


def test_a_drift_pause_commits_the_engine_pause_with_its_paused_row(world: World) -> None:
    run = start(world)
    finding = DriftFinding("session_archived", "s" * 32, "2026-01-01")
    version = world.run(run.id).version
    world.bridge.pause_for_drift(
        workspace_id=WORKSPACE,
        run_id=run.id,
        cause=finding.cause,
        body={"kind": "pause_run", "reason": "drift", "cause": finding.cause},
        checksum_parts=("coral-drift", run.id, finding.cause, finding.session_id),
        now_us=world.clock.epoch * 1_000_000,
    )
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.DRIFT),
    )
    rows = world.runs.read_log(run.id, workspace_id=WORKSPACE)
    marker = next(row for row in rows if row.kind == int(LogKind.PAUSED))
    assert marker.idempotency_cksum == drift_log_checksum(run.id, finding, version)
    assert _causes(world, run.id) == [("drift", "session_archived")]
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    assert world.run(run.id).status == int(RunStatus.RUNNING)


def test_a_drift_pause_of_a_run_the_engine_has_not_started_starts_it_first(
    world: World,
) -> None:
    run = start_without_engine(world)
    assert run.status == int(RunStatus.STARTING)
    world.bridge.pause_for_drift(
        workspace_id=WORKSPACE,
        run_id=run.id,
        cause="anchor_archived",
        body={"kind": "pause_run", "reason": "drift", "cause": "anchor_archived"},
        checksum_parts=("coral-drift", run.id, "anchor_archived", "a" * 32),
        now_us=world.clock.epoch * 1_000_000,
    )
    assert world.run(run.id).status == int(RunStatus.PAUSED)
    assert [row.kind for row in world.runs.read_log(run.id, workspace_id=WORKSPACE)] == [
        int(LogKind.ENGINE),
        int(LogKind.ENGINE),
        int(LogKind.PAUSED),
    ]
    assert _causes(world, run.id) == [("drift", "anchor_archived")]
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    assert world.run(run.id).status == int(RunStatus.RUNNING)


@pytest.mark.parametrize("started", [True, False], ids=["running", "not_started"])
def test_a_user_pause_pauses_through_the_engine_once(world: World, started: bool) -> None:
    run = start(world) if started else start_without_engine(world)

    paused = world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")

    assert (paused.outcome, paused.code, paused.commit.outcome.applied) == ("paused", None, True)
    row = world.run(run.id)
    assert (row.status, row.pause_reason) == (int(RunStatus.PAUSED), int(RunPauseReason.USER))
    assert _causes(world, run.id) == [("user", USER_PAUSE_DETAIL)]
    kinds = [json.loads(entry.body)["input"]["kind"] for entry in world.engine_log(run.id)]
    # A run whose engine never started starts first, in the same commit.
    assert kinds == ["start_run", "pause_run"]
    assert {entry.actor_ref for entry in world.engine_log(run.id)[-1:]} == {"user:alice"}
    # The owner's own pause raises no alert.
    assert _runs(world).list_alerts(run.id, workspace_id=WORKSPACE) == []

    again = world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    assert (again.outcome, again.commit.outcome.applied) == ("unchanged", False)
    assert world.run(run.id).version == row.version


def test_a_user_pause_of_a_finished_run_is_refused_and_writes_nothing(world: World) -> None:
    run = start(world)
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    version = world.run(run.id).version

    refused = world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")

    assert (refused.outcome, refused.code) == ("refused", "run_terminal")
    assert not refused.commit.outcome.applied
    assert world.run(run.id).version == version


@pytest.mark.parametrize("started", [True, False], ids=["engine_running", "engine_not_started"])
def test_a_user_pause_of_a_run_cancelled_on_its_row_is_refused(
    world: World, started: bool
) -> None:
    run = start(world) if started else start_without_engine(world)
    cancel_run_row(
        world.runs,
        workspace_id=WORKSPACE,
        run_id=run.id,
        actor="alice",
        now_us=world.clock.epoch * 1_000_000,
        lock_timeout_s=LOCK_TIMEOUT_S,
    )

    refused = world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")

    # WHY: the commit may apply (it cancels a running engine first), yet the pause did not.
    assert (refused.outcome, refused.code) == ("refused", "run_terminal")
    assert refused.commit.outcome.applied == started
    assert world.run(run.id).status == int(RunStatus.CANCELLED)


def _paused_by_engine(reason: str) -> Callable[[World, str], None]:
    def pause(world: World, run_id: str) -> None:
        _commit(world, run_id, PauseRun(reason=reason, detail="cause"))  # type: ignore[arg-type]

    return pause


def _paused_on_its_row(world: World, run_id: str) -> None:
    """A failed load pauses the row alone; the engine runs on once the run loads again."""
    key = (WORKSPACE, run_id)
    spec = _runs(world).specs[key]
    _runs(world).specs[key] = dataclasses.replace(spec, engine_config=None)
    with pytest.raises(EngineLoadFailed):
        world.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
    _runs(world).specs[key] = spec


@pytest.mark.parametrize(
    ("pause", "left"),
    [
        (_paused_by_engine("drift"), []),
        (_paused_by_engine("failure_path"), [("failure_path", "cause")]),
        (_paused_by_engine("budget"), [("budget", "cause")]),
        (_paused_on_its_row, []),
    ],
    ids=["drift", "failure_path", "budget", "row_only"],
)
def test_a_user_pause_of_a_run_paused_for_another_cause_keeps_it_until_resumed(
    world: World, pause: Callable[[World, str], None], left: list[tuple[str, str]]
) -> None:
    run = start(world)
    pause(world, run.id)
    shown = world.run(run.id)
    assert shown.status == int(RunStatus.PAUSED)

    assert (
        world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice").outcome
        == "paused"
    )

    assert ("user", USER_PAUSE_DETAIL) in _causes(world, run.id)
    # The row keeps showing the pause it had.
    assert world.run(run.id).pause_reason == shown.pause_reason
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    # A resume lifts the user's pause; a cause only a retry or a higher cap clears stays.
    assert _causes(world, run.id) == left
    row = world.run(run.id)
    still = (int(RunStatus.PAUSED), shown.pause_reason)
    assert (row.status, row.pause_reason) == (still if left else (int(RunStatus.RUNNING), None))


def test_a_timer_fires_at_the_bridge_clock(world: World) -> None:
    run_id = _working(world)
    _commit(world, run_id, FAILED_TURN)
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
    first = min(snapshot.state.timers, key=lambda timer: timer.due_at)
    early = world.bridge.fire_timer(workspace_id=WORKSPACE, run_id=run_id, timer_key=first.key)
    assert not early.outcome.applied
    world.clock.now = first.due_at
    fired = world.bridge.fire_timer(workspace_id=WORKSPACE, run_id=run_id, timer_key=first.key)
    assert fired.outcome.applied
    assert isinstance(fired.entries[0].input, TimerDue)
    world.assert_fold_matches(run_id)


def test_every_commit_bounds_its_lock_wait(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    timeouts: list[float | None] = []
    apply = world.runs.apply_transition

    def recording(
        *args: object, lock_timeout_s: float | None = None, **kwargs: object
    ) -> CommitOutcome:
        timeouts.append(lock_timeout_s)
        return apply(*args, lock_timeout_s=lock_timeout_s, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(world.runs, "apply_transition", recording)
    run_id = _working(world)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor="user:alice")
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    logs = _logs(world, run_id)
    logs[0] = dataclasses.replace(logs[0], body="{}")
    # A new process reads the corrupt row and pauses the run on the row alone.
    fresh = EngineBridge(
        run_store=world.runs, queue_store=world.queue, versions=world.versions, clock=world.clock
    )
    with pytest.raises(EngineLoadFailed):
        fresh.load(workspace_id=WORKSPACE, run_id=run_id)
    assert world.run(run_id).pause_reason == int(RunPauseReason.FAILURE_PATH)
    assert len(timeouts) >= 6
    assert set(timeouts) == {10.0}


@pytest.mark.parametrize("cap", [0, 1_001])
def test_a_resume_cap_outside_the_start_bounds_is_refused(world: World, cap: int) -> None:
    run = start(world)
    _commit(world, run.id, PauseRun(reason="user", detail="look"))
    version = world.run(run.id).version
    with pytest.raises(RunNotRunnable) as refused:
        world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:a", cap=cap)
    assert refused.value.code == "run.field_invalid"
    assert world.run(run.id).version == version


def test_cancel_of_a_wide_run_whose_engine_never_started_commits(world: World) -> None:
    wide = workflow_text(
        [start_node(), step("panel", ["reviewer"] * 32), end()],
        [arrow("a1", "start", "panel"), arrow("a2", "panel", "end")],
    )
    run = start_without_engine(world, yaml_text=wide)
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    assert world.run(run.id).status == int(RunStatus.CANCELLED)
    cancels = [
        item
        for item in world.work(run.id)
        if json.loads(item.payload).get("effect_type") == "cancel_sessions"
    ]
    assert len(cancels) == 32
    world.assert_fold_matches(run.id)
