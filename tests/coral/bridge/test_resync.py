"""Level-triggered repair of a run: every rule is safe to repeat; a second pass writes nothing."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import zstandard

from coral.bridge import fold as fold_module
from coral.bridge.commit import build_commit
from coral.bridge.config import PAUSED_RESYNC_DELAY_S, ceil_epoch_seconds
from coral.bridge.keys import anchor_effect_key, effect_work_id
from coral.bridge.mapping import resync_draft, timer_draft, turn_signal_draft
from coral.bridge.service import EngineBridge, EngineLoadFailed, ResyncReport
from coral.db.enum_codecs import (
    GateVisitStatus,
    LogKind,
    RunPauseReason,
    RunStatus,
    SlotStatus,
    WorkKind,
    WorkStatus,
)
from coral.engine.types import PauseRun, SessionFailed
from coral.model.ids import effect_session_id
from coral.stores.fakes import FakeQueueStore, FakeRunStore
from coral.stores.protocols import CommitOutcome, RunContended, WorkItem, WorkItemDraft
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
    CHANGE_TOKEN,
    CHANGE_TOKEN_AGAIN,
    GATE_ONLY,
    GATED,
    IMPLEMENT_AGAIN,
    answer,
    effects,
    gate_rows,
    hand_off,
    work_for,
)
from tests.coral.bridge._scripted_runs import accept
from tests.coral.bridge._world import (
    IMPLEMENT,
    REVIEW,
    WORKSPACE,
    World,
    finished,
    row_of,
    run_id_for,
    settle,
    start,
    start_without_engine,
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


def _create(world: World, run_id: str) -> WorkItem:
    return row_of(world, run_id, "create_session", engine_kind="create_session")


def _resync(world: World, run_id: str) -> ResyncReport:
    report = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    world.assert_fold_matches(run_id)
    return report


def _quiet(world: World, run_id: str) -> None:
    """A resync of a repaired run writes nothing and queues nothing."""
    version = world.run(run_id).version
    rows = world.work(run_id)
    _resync(world, run_id)
    assert world.run(run_id).version == version
    assert world.work(run_id) == rows


def _queue(world: World) -> FakeQueueStore:
    assert isinstance(world.queue, FakeQueueStore)
    return world.queue


def _runs(world: World) -> FakeRunStore:
    assert isinstance(world.runs, FakeRunStore)
    return world.runs


def test_a_run_started_without_its_engine_start_is_started(world: World) -> None:
    run = start_without_engine(world)
    report = _resync(world, run.id)
    assert report.started
    started = world.run(run.id)
    assert started.status == int(RunStatus.RUNNING)
    payloads = [json.loads(item.payload) for item in world.work(run.id)]
    kinds = {payload.get("bridge_item") or payload["engine_kind"] for payload in payloads}
    assert kinds == {"anchor", "create_session"}
    _quiet(world, run.id)


def test_a_finished_row_whose_feed_was_lost_is_fed(world: World) -> None:
    run = start(world)
    settle(world, _create(world, run.id), WorkStatus.SUCCEEDED, result={"session_id": "s" * 32})
    report = _resync(world, run.id)
    assert report.fed == 1
    state, _version = world.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    assert state.agent_slots[0].status == int(SlotStatus.SESSION_CREATED)
    assert json.loads(row_of(world, run.id, "send_input").payload)["kind"] == "brief"
    _quiet(world, run.id)


def test_a_failed_row_of_a_running_run_pauses_it_and_is_never_revived(world: World) -> None:
    run = start(world)
    failed = settle(
        world,
        _create(world, run.id),
        WorkStatus.FAILED,
        error_code="infra.transient",
        result={"last_error_code": "session.host_offline"},
    )
    _resync(world, run.id)
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.INFRA),
    )
    (row,) = world.queue.get_work([failed.id], workspace_id=WORKSPACE)
    assert row.status == int(WorkStatus.FAILED)
    _quiet(world, run.id)
    (row,) = world.queue.get_work([failed.id], workspace_id=WORKSPACE)
    assert row.status == int(WorkStatus.FAILED)


def test_a_missing_row_of_an_unreceipted_effect_is_queued_again(world: World) -> None:
    run = start(world)
    create = _create(world, run.id)
    anchor_id = effect_work_id(run.id, anchor_effect_key(run.id))
    del _queue(world).work[(WORKSPACE, create.id)]
    del _queue(world).work[(WORKSPACE, anchor_id)]
    report = _resync(world, run.id)
    assert report.enqueued == 2
    again = _create(world, run.id)
    assert (again.id, again.payload, again.slot_generation) == (
        create.id,
        create.payload,
        create.slot_generation,
    )
    assert world.queue.get_work([anchor_id], workspace_id=WORKSPACE)
    _quiet(world, run.id)


def _with_backoff(world: World) -> str:
    run = start(world)
    created = {"session_id": "s" * 32}
    world.bridge.feed(
        finished(settle(world, _create(world, run.id), WorkStatus.SUCCEEDED, result=created))
    )
    world.bridge.feed(
        finished(
            settle(
                world, row_of(world, run.id, "send_input"), WorkStatus.SUCCEEDED, result=created
            )
        )
    )
    failed = SessionFailed(
        slot_id=IMPLEMENT, failure_class="infra.transient", cause="529", fact_key="turn:s:1:msg:a"
    )
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run.id, inputs=lambda _snapshot: (failed,)
    )
    return run.id


def test_timer_rows_of_armed_timers_are_added_back_and_failed_ones_revived(
    world: World,
) -> None:
    run_id = _with_backoff(world)
    timers = sorted(
        world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state.timers,
        key=lambda t: t.due_at,
    )
    lost, failed = (timer_draft(run_id, timer) for timer in timers[:2])
    del _queue(world).work[(WORKSPACE, lost.id)]
    (row,) = world.queue.get_work([failed.id], workspace_id=WORKSPACE)
    settle(world, row, WorkStatus.FAILED, error_code="infra.transient")
    version = world.run(run_id).version

    report = _resync(world, run_id)

    assert report.timers == 2
    restored, revived = (
        world.queue.get_work([lost.id], workspace_id=WORKSPACE)[0],
        world.queue.get_work([failed.id], workspace_id=WORKSPACE)[0],
    )
    assert (restored.status, restored.available_at) == (
        int(WorkStatus.PENDING),
        ceil_epoch_seconds(timers[0].due_at),
    )
    assert (revived.status, revived.attempts, revived.error_code) == (
        int(WorkStatus.PENDING),
        0,
        None,
    )
    # Timer rows are queue rows; the run itself is not written.
    assert world.run(run_id).version == version
    _quiet(world, run_id)


def test_a_diverged_run_or_slot_row_is_repaired(world: World) -> None:
    run = start(world)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )
    runs = _runs(world)
    key = (WORKSPACE, run.id)
    runs.runs[key] = dataclasses.replace(
        runs.runs[key], pause_reason=int(RunPauseReason.INFRA), activation_count=0
    )
    slot_key = next(k for k in runs.agent_slots if k[1] == run.id)
    runs.agent_slots[slot_key] = dataclasses.replace(
        runs.agent_slots[slot_key], status=int(SlotStatus.CLOSED), nudges=9
    )
    report = _resync(world, run.id)
    assert report.repaired
    repaired = world.run(run.id)
    state = world.assert_fold_matches(run.id)
    assert (repaired.pause_reason, repaired.activation_count) == (
        int(RunPauseReason.USER),
        len(state.activations),
    )
    assert (runs.agent_slots[slot_key].status, runs.agent_slots[slot_key].nudges) == (
        int(SlotStatus.PENDING),
        0,
    )
    _quiet(world, run.id)


def test_held_rows_of_a_running_run_are_released(world: World) -> None:
    run = start(world)
    create = _create(world, run.id)
    settle(
        world,
        create,
        WorkStatus.PENDING,
        error_code="run.paused",
        held_since=world.clock.epoch - 10,
        available_at=world.clock.epoch + 300,
    )
    report = _resync(world, run.id)
    assert report.released
    (row,) = world.queue.get_work([create.id], workspace_id=WORKSPACE)
    assert (row.available_at, row.held_since) == (world.clock.epoch, None)
    _quiet(world, run.id)


def test_a_held_turn_signal_of_a_running_run_is_released(world: World) -> None:
    # A signal claimed while the resume committed, then held for the pause it saw.
    run = start(world)
    signal = turn_signal_draft(
        run_id=run.id,
        session_id="session-1",
        engine_slot_id=IMPLEMENT,
        generation=1,
        idempotency_key="sig:held",
        edge=None,
        available_at=world.clock.epoch,
    )
    world.queue.enqueue_work([signal], workspace_id=WORKSPACE, now=world.clock.epoch)
    (row,) = world.queue.get_work([signal.id], workspace_id=WORKSPACE)
    settle(
        world,
        row,
        WorkStatus.PENDING,
        error_code="run.paused",
        held_since=world.clock.epoch - 10,
        available_at=world.clock.epoch + 300,
    )
    report = _resync(world, run.id)
    assert report.released
    (row,) = world.queue.get_work([signal.id], workspace_id=WORKSPACE)
    assert (row.available_at, row.held_since) == (world.clock.epoch, None)
    _quiet(world, run.id)


def test_an_unloadable_run_pauses_once_and_later_resyncs_do_nothing(world: World) -> None:
    run = start(world)
    logs = _runs(world).logs[(WORKSPACE, run.id)]
    logs[0] = dataclasses.replace(logs[0], body="{}")
    with pytest.raises(EngineLoadFailed):
        world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    with pytest.raises(EngineLoadFailed):
        world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    assert world.run(run.id).version == paused.version
    assert [row.kind for row in logs].count(int(LogKind.PAUSED)) == 1


def test_a_defect_while_folding_is_raised_not_filed_as_an_unloadable_run(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world)

    def broken(*_args: object, **_kwargs: object) -> object:
        raise ValueError("a reducer defect")

    monkeypatch.setattr(fold_module, "fold_log", broken)
    # A new process: nothing folded yet.
    cold = EngineBridge(
        run_store=world.runs, queue_store=world.queue, versions=world.versions, clock=world.clock
    )
    version = world.run(run.id).version

    with pytest.raises(ValueError, match="reducer defect"):
        cold.resync_run(workspace_id=WORKSPACE, run_id=run.id)

    # Nothing paused the run: a fixed defect lets it go on.
    assert (world.run(run.id).status, world.run(run.id).version) == (
        int(RunStatus.RUNNING),
        version,
    )


def test_a_terminal_run_is_only_projected(world: World) -> None:
    run = start(world)
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    del _queue(world).work[(WORKSPACE, _create(world, run.id).id)]
    report = _resync(world, run.id)
    assert (report.enqueued, report.fed) == (0, 0)
    _quiet(world, run.id)


class _Crash(BaseException):
    """Process death at one chosen point of the write side."""


class _CrashPoints:
    """Numbers each point a process can die at and dies at ``crash_at`` (0: never)."""

    def __init__(self, crash_at: int) -> None:
        self.crash_at = crash_at
        self.passed = 0

    def point(self) -> None:
        self.passed += 1
        if self.passed == self.crash_at:
            raise _Crash


def _outcome(item: WorkItem) -> dict[str, object]:
    """What a successful executor reports for the row."""
    payload = json.loads(item.payload)
    if payload.get("engine_kind") == "create_session":
        session = effect_session_id(WORKSPACE, payload["effect_key"])
        return {"session_id": session, "role": "step", "generation": item.slot_generation}
    if payload.get("engine_kind") == "send_input":
        return {"session_id": payload["session_id"], "stable_id": payload["effect_key"]}
    return {}


def _drive(world: World, run_id: str, points: _CrashPoints) -> None:
    """Run every due effect row to success and feed it; a working slot hands off at once."""
    for _ in range(50):
        state = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state
        for slot in state.slots:
            if slot.status == "working":
                world.bridge.commit_inputs(
                    workspace_id=WORKSPACE,
                    run_id=run_id,
                    inputs=lambda _snapshot, slot_id=slot.id: accept(slot_id, "done"),
                )
        due = [
            item
            for item in world.work(run_id)
            if item.kind == int(WorkKind.EFFECT) and item.status == int(WorkStatus.PENDING)
        ]
        if not due:
            return
        done = settle(world, due[0], WorkStatus.SUCCEEDED, result=_outcome(due[0]))
        points.point()
        world.bridge.feed(finished(done))
    raise AssertionError(f"run {run_id} did not settle")


def _crash_once(world: World, monkeypatch: pytest.MonkeyPatch, crash_at: int) -> int:
    """Start and drive the run, dying at point ``crash_at``; returns the points passed."""
    points = _CrashPoints(crash_at)
    apply = world.runs.apply_transition

    def dying(*args: Any, **kwargs: Any) -> CommitOutcome:
        points.point()
        outcome = apply(*args, **kwargs)
        points.point()
        return outcome

    with monkeypatch.context() as patch:
        patch.setattr(world.runs, "apply_transition", dying)
        with contextlib.suppress(_Crash):
            _drive(world, start(world).id, points)
    return points.passed


def test_a_two_step_run_survives_a_crash_at_any_point_of_its_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "count").mkdir()
    total = _crash_once(World.fake(tmp_path / "count"), monkeypatch, crash_at=0)
    for crash_at in range(1, total + 1):
        (tmp_path / str(crash_at)).mkdir()
        world = World.fake(tmp_path / str(crash_at))
        assert _crash_once(world, monkeypatch, crash_at) == crash_at
        # A new process: no cached state, the resync repairs, the drain goes on.
        world = dataclasses.replace(
            world,
            bridge=EngineBridge(
                run_store=world.runs,
                queue_store=world.queue,
                versions=world.versions,
                clock=world.clock,
            ),
        )
        run_id = run_id_for()
        _resync(world, run_id)
        _drive(world, run_id, _CrashPoints(0))

        assert world.run(run_id).status == int(RunStatus.COMPLETED), crash_at
        snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
        assert build_commit(snapshot, (), now=world.clock()).is_empty
        log = world.engine_log(run_id)
        inputs = [json.loads(row.body)["input"] for row in log if not row.audit_only]
        completed = Counter(
            item["effect_key"] for item in inputs if item["kind"] == "effect_completed"
        )
        received = Counter(
            item["slot_id"] for item in inputs if item["kind"] == "handoff_received"
        )
        rows = Counter(
            (payload.get("engine_kind"), payload.get("engine_slot_id"), payload.get("slot_id"))
            for payload in (
                json.loads(item.payload)
                for item in world.work(run_id)
                if item.kind == int(WorkKind.EFFECT)
            )
        )
        assert set(completed.values()) == set(received.values()) == set(rows.values()) == {1}
        assert len(completed) == 6 and set(received) == {IMPLEMENT, REVIEW}
        _quiet(world, run_id)


def _resync_row(world: World, run_id: str) -> WorkItem:
    rows = world.queue.get_work([resync_draft(run_id).id], workspace_id=WORKSPACE)
    assert len(rows) == 1
    return rows[0]


def test_a_running_run_s_resync_is_due_now_and_a_paused_one_s_every_15_minutes(
    world: World,
) -> None:
    run = start(world)
    world.bridge.schedule_resync(world.run(run.id))
    row = _resync_row(world, run.id)
    assert (row.kind, row.available_at) == (int(WorkKind.SIGNAL), world.clock.epoch)
    assert json.loads(row.payload)["effect_type"] == "run_resync"

    other = start_without_engine(world, start_key="paused")
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=other.id,
        inputs=lambda snapshot: (
            world.bridge.start_input(snapshot),
            PauseRun(reason="user", detail="look"),
        ),
    )
    first_due = world.clock.epoch + PAUSED_RESYNC_DELAY_S
    for _ in range(5):
        world.bridge.schedule_resync(world.run(other.id))
        world.clock.advance(60)
    assert _resync_row(world, other.id).available_at == first_due

    # After it ran, the next one is another 15 minutes out.
    world.clock.advance(PAUSED_RESYNC_DELAY_S)
    settle(world, _resync_row(world, other.id), WorkStatus.SUCCEEDED)
    world.bridge.schedule_resync(world.run(other.id))
    assert _resync_row(world, other.id).available_at == world.clock.epoch + PAUSED_RESYNC_DELAY_S
    assert _resync_row(world, other.id).status == int(WorkStatus.PENDING)


def test_a_finished_run_gets_no_resync_row(world: World) -> None:
    run = start(world)
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    world.bridge.schedule_resync(world.run(run.id))
    assert world.queue.get_work([resync_draft(run.id).id], workspace_id=WORKSPACE) == []


def test_a_failure_read_by_a_resync_before_a_resume_does_not_pause_the_run_again(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )
    settle(
        world,
        _create(world, run.id),
        WorkStatus.FAILED,
        error_code="infra.transient",
        result={"last_error_code": "session.host_offline"},
    )
    get_work = world.queue.get_work
    resumed: list[bool] = []

    def resumed_after_the_read(work_ids: Sequence[str], *, workspace_id: int) -> list[WorkItem]:
        rows = get_work(work_ids, workspace_id=workspace_id)
        if not resumed:
            # The user resumes between the resync's read and its feed.
            resumed.append(True)
            world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
        return rows

    monkeypatch.setattr(world.queue, "get_work", resumed_after_the_read)
    _resync(world, run.id)
    assert resumed == [True]
    assert world.run(run.id).status == int(RunStatus.RUNNING)


def test_a_run_paused_outside_the_engine_keeps_its_holds(world: World) -> None:
    run = start(world)
    runs = _runs(world)
    runs.runs[(WORKSPACE, run.id)] = dataclasses.replace(
        runs.runs[(WORKSPACE, run.id)],
        status=int(RunStatus.PAUSED),
        pause_reason=int(RunPauseReason.DRIFT),
    )
    settle(
        world,
        _create(world, run.id),
        WorkStatus.PENDING,
        error_code="run.paused",
        held_since=world.clock.epoch,
        available_at=world.clock.epoch + 300,
    )
    report = _resync(world, run.id)
    assert not report.released
    _quiet(world, run.id)


def test_a_resync_start_records_the_owner_as_its_actor(world: World) -> None:
    run = start_without_engine(world)
    _resync(world, run.id)
    (row,) = world.engine_log(run.id)
    assert row.actor_ref == "alice"


def test_a_contended_feed_does_not_stop_the_other_repairs(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    run = start(world)
    settle(world, _create(world, run.id), WorkStatus.SUCCEEDED, result={"session_id": "s" * 32})
    runs = _runs(world)
    slot_key = next(key for key in runs.agent_slots if key[1] == run.id)
    runs.agent_slots[slot_key] = dataclasses.replace(runs.agent_slots[slot_key], nudges=9)

    def contended(*_args: object) -> tuple[()]:
        raise RunContended("version conflict after 5 attempts")

    monkeypatch.setattr(world.bridge, "_current", contended)
    with caplog.at_level(logging.WARNING, logger="coral.bridge.service"):
        report = world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    assert "contended" in caplog.text
    assert report.repaired
    assert runs.agent_slots[slot_key].nudges == 0


def test_a_resync_already_due_in_time_is_not_written_again(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world)
    writes: list[int] = []
    reschedule = world.queue.reschedule_work

    def counted(draft: WorkItemDraft, *, workspace_id: int, available_at: int) -> None:
        writes.append(available_at)
        reschedule(draft, workspace_id=workspace_id, available_at=available_at)

    monkeypatch.setattr(world.queue, "reschedule_work", counted)
    for _ in range(3):
        world.bridge.schedule_resync(world.run(run.id))
        world.clock.advance(60)
    assert len(writes) == 1


def test_a_run_whose_rows_do_not_decode_is_paused_on_its_row(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    run = start(world)

    def undecodable(*_args: object, **_kwargs: object) -> None:
        raise zstandard.ZstdError("not a zstd frame")

    monkeypatch.setattr(world.runs, "load_run_state", undecodable)
    with caplog.at_level(logging.WARNING, logger="coral.bridge.service"):
        for _ in range(2):
            with pytest.raises(EngineLoadFailed):
                world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    logs = _runs(world).logs[(WORKSPACE, run.id)]
    assert [row.kind for row in logs].count(int(LogKind.PAUSED)) == 1
    # One error for the pause; a later failure only warns, and the next resync is 15 min out.
    assert [record.levelno for record in caplog.records] == [logging.ERROR, logging.WARNING]
    world.bridge.schedule_resync(paused)
    (row,) = world.queue.get_work([resync_draft(run.id).id], workspace_id=WORKSPACE)
    assert row.available_at == world.clock.epoch + PAUSED_RESYNC_DELAY_S


# ── gate delivery ────────────────────────────────────────────────────────────


def _gate_publish(world: World, run_id: str, token: str) -> WorkItem:
    (effect,) = [item for item in effects(world, run_id, "publish_gate") if item.subject == token]
    item = work_for(world, run_id, effect.effect_key)
    assert item is not None
    return item


def test_a_resume_revives_a_failed_publish_of_a_live_visit(world: World) -> None:
    run = start(world, GATE_ONLY)
    failed = settle(
        world,
        _gate_publish(world, run.id, APPROVE_TOKEN),
        WorkStatus.FAILED,
        error_code="infra.transient",
        result={"last_error_code": "session.anchor_missing"},
    )
    world.bridge.feed(finished(failed))
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.INFRA),
    )
    state = world.assert_fold_matches(run.id)
    assert [(cause.reason, cause.detail) for cause in state.causes] == [
        ("infra", "gate:session.anchor_missing")
    ]

    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")

    (revived,) = world.queue.get_work([failed.id], workspace_id=WORKSPACE)
    assert revived.status == int(WorkStatus.PENDING)
    assert world.run(run.id).status == int(RunStatus.RUNNING)


def test_a_resync_queues_a_missing_publish_and_writes_missing_gate_rows(world: World) -> None:
    # As for a run whose gate opened before gates were delivered: no row, no publish.
    run = start(world, GATE_ONLY)
    publish = _gate_publish(world, run.id, APPROVE_TOKEN)
    (row,) = gate_rows(world, run.id)
    del _queue(world).work[(WORKSPACE, publish.id)]
    _runs(world).gate_visits.clear()
    world.clock.advance(60)

    report = _resync(world, run.id)

    assert (report.enqueued, report.repaired) == (1, True)
    again = _gate_publish(world, run.id, APPROVE_TOKEN)
    assert (again.id, again.payload) == (publish.id, publish.payload)
    (repaired,) = gate_rows(world, run.id)
    assert repaired.elicitation_id != row.elicitation_id
    assert repaired.opened_at == world.clock.epoch
    assert (
        dataclasses.replace(repaired, elicitation_id=row.elicitation_id, opened_at=row.opened_at)
        == row
    )
    _quiet(world, run.id)


def test_a_failed_publish_is_fed_only_while_its_visit_is_live(world: World) -> None:
    run = start(world, GATED)
    hand_off(world, run.id)
    first = _gate_publish(world, run.id, CHANGE_TOKEN)
    answer(world, run.id, CHANGE_TOKEN, "reject")
    # The visit was answered before its publish ran out: the failure stands for nothing.
    failed = settle(world, first, WorkStatus.FAILED, error_code="session.anchor_missing")
    version = world.run(run.id).version
    world.bridge.feed(finished(failed))
    _resync(world, run.id)
    assert (world.run(run.id).status, world.run(run.id).version) == (
        int(RunStatus.RUNNING),
        version,
    )

    hand_off(world, run.id, IMPLEMENT_AGAIN)
    settle(
        world,
        _gate_publish(world, run.id, CHANGE_TOKEN_AGAIN),
        WorkStatus.FAILED,
        error_code="effect.invalid_payload",
    )
    report = _resync(world, run.id)

    assert report.fed >= 1
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    state = world.assert_fold_matches(run.id)
    assert [(cause.reason, cause.detail) for cause in state.causes] == [
        ("failure_path", "gate:effect.invalid_payload")
    ]


def test_a_resync_queues_only_the_live_visit_s_missing_publish(world: World) -> None:
    run = start(world, GATED)
    hand_off(world, run.id)
    answer(world, run.id, CHANGE_TOKEN, "reject")
    hand_off(world, run.id, IMPLEMENT_AGAIN)
    dead = _gate_publish(world, run.id, CHANGE_TOKEN)
    live = _gate_publish(world, run.id, CHANGE_TOKEN_AGAIN)
    for item in (dead, live):
        del _queue(world).work[(WORKSPACE, item.id)]

    report = _resync(world, run.id)

    assert report.enqueued == 1
    assert world.queue.get_work([dead.id], workspace_id=WORKSPACE) == []
    again = _gate_publish(world, run.id, CHANGE_TOKEN_AGAIN)
    assert (again.id, again.payload) == (live.id, live.payload)
    _quiet(world, run.id)


def test_a_withdraw_that_finishes_after_the_cancel_changes_nothing(world: World) -> None:
    run = start(world, GATE_ONLY)
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")
    (withdraw,) = effects(world, run.id, "withdraw_gate")
    item = work_for(world, run.id, withdraw.effect_key)
    assert item is not None
    version = world.run(run.id).version

    for status, code in (
        (WorkStatus.FAILED, "session.anchor_missing"),
        (WorkStatus.SUCCEEDED, None),
    ):
        world.bridge.feed(finished(settle(world, item, status, error_code=code)))
        assert (world.run(run.id).status, world.run(run.id).version) == (
            int(RunStatus.CANCELLED),
            version,
        )
    _quiet(world, run.id)


def test_a_resync_of_a_run_cancelled_before_gate_rows_writes_them_and_queues_nothing(
    world: World,
) -> None:
    # As for a run cancelled at a gate before gates were delivered: no rows, no delivery.
    run = start(world, GATE_ONLY)
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")
    for kind in ("publish_gate", "withdraw_gate"):
        (effect,) = effects(world, run.id, kind)
        del _queue(world).work[(WORKSPACE, effect_work_id(run.id, effect.effect_key))]
    _runs(world).gate_visits.clear()
    rows = world.work(run.id)

    assert _resync(world, run.id).repaired

    (row,) = gate_rows(world, run.id)
    assert (row.token, row.status) == (APPROVE_TOKEN, int(GateVisitStatus.CANCELLED))
    assert world.work(run.id) == rows
    _quiet(world, run.id)


def test_a_resync_that_dies_after_queueing_a_publish_writes_its_row_next_time(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world, GATE_ONLY)
    publish = _gate_publish(world, run.id, APPROVE_TOKEN)
    del _queue(world).work[(WORKSPACE, publish.id)]
    _runs(world).gate_visits.clear()

    def dying(*_args: Any, **_kwargs: Any) -> CommitOutcome:
        raise _Crash

    with monkeypatch.context() as patch:
        patch.setattr(world.runs, "apply_transition", dying)
        with pytest.raises(_Crash):
            world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    # The publish was queued outside the commit that would write its row.
    assert _gate_publish(world, run.id, APPROVE_TOKEN).id == publish.id
    assert gate_rows(world, run.id) == []

    report = _resync(world, run.id)

    assert (report.enqueued, report.repaired) == (0, True)
    (row,) = gate_rows(world, run.id)
    assert (row.token, row.status) == (APPROVE_TOKEN, int(GateVisitStatus.OPEN))
    _quiet(world, run.id)


def test_a_failed_withdraw_of_a_superseded_visit_never_pauses_the_running_run(
    world: World,
) -> None:
    run = start(world, GATED)
    hand_off(world, run.id)
    answer(world, run.id, CHANGE_TOKEN, "reject")
    hand_off(world, run.id, IMPLEMENT_AGAIN)
    (withdraw,) = effects(world, run.id, "withdraw_gate")
    assert withdraw.subject == CHANGE_TOKEN
    item = work_for(world, run.id, withdraw.effect_key)
    assert item is not None
    version = world.run(run.id).version

    failed = settle(world, item, WorkStatus.FAILED, error_code="session.anchor_missing")
    world.bridge.feed(finished(failed))
    _resync(world, run.id)

    assert (world.run(run.id).status, world.run(run.id).version) == (
        int(RunStatus.RUNNING),
        version,
    )
    assert not world.assert_fold_matches(run.id).causes
