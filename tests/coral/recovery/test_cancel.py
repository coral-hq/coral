"""A store-only cancel: a run the bridge cannot load ends on its row, and its work still runs.

The queued session cancels are drained through the real ``cancel_sessions`` executor,
and gate prompts go through the real sweep, so nothing queued here waits on an engine
that cannot load.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import zstandard

from coral.alerts.rules import UNSTOPPED_SESSIONS_MESSAGES
from coral.alerts.types import AlertPayload
from coral.bridge.codec import decode_entries
from coral.bridge.config import LOCK_TIMEOUT_S
from coral.bridge.service import EngineLoadFailed
from coral.db.enum_codecs import (
    ActorKind,
    AlertKind,
    AlertPriority,
    AlertStatus,
    GateVisitStatus,
    LogKind,
    RunStatus,
    SlotStatus,
    WorkStatus,
)
from coral.gates.sweep import GatePromptSweeper
from coral.model.ids import anchor_session_id
from coral.recovery.cancel import (
    MAX_STORE_CANCEL_SESSIONS,
    StoreCancel,
    cancel_run_row,
    withdraw_local_prompts,
)
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import AlertRecord, RunNotFound, WorkItem
from tests.coral.bridge._gates import GATE_ONLY, GateIds, before_next_commit, gate_rows
from tests.coral.bridge._world import (
    IMPLEMENT,
    USER,
    WORKSPACE,
    Agent,
    FakeGatePrompts,
    RecordingGatePublisher,
    World,
    finished,
    row_of,
    run_spec,
    serving,
    settle,
    start,
    start_without_engine,
)
from tests.coral.workflow_builders import fixture_text
from tests.coral.workspace._executor_fakes import RecordingScopeRunner

ACTOR = "alice"
CREATED = {"session_id": "s" * 32, "role": "step", "generation": 1}


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


def _runs(world: World) -> FakeRunStore:
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    return runs


def _cancel(world: World, run_id: str) -> StoreCancel:
    return cancel_run_row(
        world.runs,
        workspace_id=WORKSPACE,
        run_id=run_id,
        actor=ACTOR,
        now_us=world.clock.epoch * 1_000_000,
        lock_timeout_s=LOCK_TIMEOUT_S,
    )


def _engine_unloadable(world: World, run_id: str) -> Callable[[], None]:
    """The run's rows still decode; its frozen engine config is gone until the call returned."""
    key = (WORKSPACE, run_id)
    runs = _runs(world)
    spec = runs.specs[key]
    runs.specs[key] = dataclasses.replace(spec, engine_config=None)

    def loadable() -> None:
        runs.specs[key] = spec

    return loadable


def _rows_undecodable(
    world: World, run_id: str, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    load = world.runs.load_run_state

    def failing(broken: str, **options: object) -> object:
        if broken == run_id:
            raise error
        return load(broken, **options)  # type: ignore[arg-type]

    monkeypatch.setattr(world.runs, "load_run_state", failing)


def _finished_body(world: World, run_id: str) -> dict[str, Any]:
    (row,) = [
        row
        for row in world.runs.read_log(run_id, workspace_id=WORKSPACE)
        if row.kind == int(LogKind.RUN_FINISHED)
    ]
    assert (row.actor_kind, row.actor_ref) == (int(ActorKind.USER), ACTOR)
    return json.loads(row.body)


def _session_cancels(world: World, run_id: str) -> list[WorkItem]:
    """The run's ``cancel_sessions`` rows but the anchor's, which :func:`_anchor_cancels` reads."""
    anchor = anchor_session_id(WORKSPACE, run_id)
    return [
        item
        for item in world.work(run_id)
        if json.loads(item.payload).get("effect_type") == "cancel_sessions"
        and json.loads(item.payload).get("session_id") != anchor
    ]


def _anchor_cancels(world: World, run_id: str) -> list[str]:
    """The effect keys of the run's ``cancel_sessions`` rows for its anchor."""
    anchor = anchor_session_id(WORKSPACE, run_id)
    payloads = [json.loads(item.payload) for item in world.work(run_id)]
    return [
        payload["effect_key"]
        for payload in payloads
        if payload.get("effect_type") == "cancel_sessions" and payload["session_id"] == anchor
    ]


def _alerts(world: World, run_id: str, kind: AlertKind) -> list[AlertRecord]:
    return [
        alert
        for alert in _runs(world).list_alerts(run_id, workspace_id=WORKSPACE)
        if alert.kind == int(kind)
    ]


def _body(*, queued: int, unreachable: bool, gates: int) -> dict[str, Any]:
    return {
        "kind": "cancel_run",
        "status": "cancelled",
        "store_only": True,
        "cause": "engine.load_failed",
        "sessions_queued": queued,
        "sessions_unreachable": unreachable,
        "gates_closed": gates,
    }


async def test_queued_session_cancels_stop_exactly_this_runs_sessions(world: World) -> None:
    async with serving(world) as sessions:
        run = start(world)
        other = start(world, spec=run_spec(start_key="other"), start_key="other")
        await sessions.run()
        implementer = sessions.session_of(run.id, IMPLEMENT)
        loadable = _engine_unloadable(world, run.id)
        with pytest.raises(EngineLoadFailed):
            world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor=ACTOR)

        cancelled = _cancel(world, run.id)

        assert cancelled.outcome.applied
        assert (cancelled.sessions_queued, cancelled.sessions_unreachable) == (2, False)
        assert cancelled.gate_rows == ()
        row = world.run(run.id)
        assert (row.status, row.pause_reason, row.finished_at) == (
            int(RunStatus.CANCELLED),
            None,
            world.clock.epoch,
        )
        assert _finished_body(world, run.id) == _body(queued=2, unreachable=False, gates=0)
        anchor = anchor_session_id(WORKSPACE, run.id)
        assert _anchor_cancels(world, run.id) == [f"{run.id}:0:cancel_sessions:{anchor}"]
        (queued,) = _session_cancels(world, run.id)
        assert json.loads(queued.payload) == {
            "effect_type": "cancel_sessions",
            "effect_key": f"{run.id}:0:cancel_sessions:{implementer}",
            "session_id": implementer,
            "closed_label": True,
        }
        # No fence and nothing fed back: the engine that would read it cannot load.
        assert (queued.scope_key, queued.slot_generation, queued.owner_key) == (None, None, None)
        # The failed load's pause alert is resolved; the run ended once.
        (pause,) = _alerts(world, run.id, AlertKind.PAUSE)
        (ended,) = _alerts(world, run.id, AlertKind.RUN_CANCELLED)
        assert (pause.status, ended.status) == (int(AlertStatus.RESOLVED), int(AlertStatus.OPEN))
        assert AlertPayload.model_validate_json(ended.payload).message == "The run was cancelled."
        assert ended.priority == int(AlertPriority.LOW)

        await sessions.drain()

        assert sessions.dispatch.stops == [(implementer, USER)]
        assert sessions.dispatch.sessions[implementer].closed
        (drained,) = world.queue.get_work([queued.id], workspace_id=WORKSPACE)
        assert drained.status == int(WorkStatus.SUCCEEDED)
        assert world.run(other.id).status == int(RunStatus.RUNNING)

        logs = world.runs.read_log(run.id, workspace_id=WORKSPACE)
        again = _cancel(world, run.id)
        assert not again.outcome.applied
        assert (again.sessions_queued, again.gate_rows) == (0, ())
        assert world.runs.read_log(run.id, workspace_id=WORKSPACE) == logs
        assert _session_cancels(world, run.id) == [drained]

        # It loads again: a resume that raced the cancel commits the engine's cancel first.
        loadable()
        world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor=ACTOR)
        kinds = [entry.input.kind for entry in decode_entries(world.engine_log(run.id))]
        assert (world.run(run.id).status, kinds[-1]) == (int(RunStatus.CANCELLED), "cancel_run")
        await sessions.drain()
        # The engine's own cancel stops the session again, which changes nothing.
        assert sessions.dispatch.stops == [(implementer, USER)] * 2
        assert [item.status for item in _session_cancels(world, run.id)] == [
            int(WorkStatus.SUCCEEDED)
        ] * 2
        # The run ended once: one entry, one alert.
        assert _finished_body(world, run.id) == _body(queued=2, unreachable=False, gates=0)
        assert len(_alerts(world, run.id, AlertKind.RUN_CANCELLED)) == 1


async def test_open_gate_rows_are_cancelled_and_their_prompts_withdrawn_everywhere(
    tmp_path: Path,
) -> None:
    world = World.fake(tmp_path, gate_ids=GateIds())
    run = start(world, GATE_ONLY)
    async with serving(world) as sessions:
        await sessions.drain()
        anchor = anchor_session_id(WORKSPACE, run.id)
        (row,) = gate_rows(world, run.id)
        assert row.elicitation_id is not None
        assert (anchor, row.elicitation_id) in sessions.gates.pending
        # Another process tracks the same prompt; its sweep keeps a live visit's.
        elsewhere = RecordingGatePublisher()
        tracked = FakeGatePrompts(elsewhere)
        tracked.track(anchor, row.elicitation_id)
        sweeper = GatePromptSweeper(
            threads=sessions.threads,
            run_store=world.runs,
            bindings=sessions.bindings,
            publisher=elsewhere,
            prompts=tracked,
            scope_runner=RecordingScopeRunner(),
        )
        assert await sweeper.sweep_once() == 0
        loadable = _engine_unloadable(world, run.id)

        cancelled = _cancel(world, run.id)

        assert [gate.id for gate in cancelled.gate_rows] == [row.id]
        (closed,) = gate_rows(world, run.id)
        assert (closed.status, closed.resolved_at) == (
            int(GateVisitStatus.CANCELLED),
            world.clock.epoch,
        )
        assert _finished_body(world, run.id) == _body(queued=1, unreachable=False, gates=1)
        (gate_alert,) = _alerts(world, run.id, AlertKind.GATE)
        assert gate_alert.status == int(AlertStatus.RESOLVED)
        # No withdraw rows: their executor needs the engine.
        types = {json.loads(item.payload)["effect_type"] for item in world.work(run.id)}
        assert "gate_withdraw" not in types
        # This process withdraws at once; every other one at its next sweep.
        assert await withdraw_local_prompts(sessions.gates, cancelled.gate_rows) == 1
        assert (anchor, row.elicitation_id) not in sessions.gates.pending
        assert await sweeper.sweep_once() == 1
        assert elsewhere.calls == [("withdraw", anchor, row.elicitation_id)]
        assert tracked.prompts == []

        # It loads again: the engine's cancel leaves the gate closed and is not asked again.
        loadable()
        world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor=ACTOR)
        (still,) = gate_rows(world, run.id)
        assert still.status == int(GateVisitStatus.CANCELLED)
        await sessions.drain()
        assert [call[0] for call in sessions.gates.calls] == ["publish", "withdraw", "withdraw"]
        assert (anchor, row.elicitation_id) not in sessions.gates.pending


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(zstandard.ZstdError("not a zstd frame"), id="zstd"),
        pytest.param(ValueError("Truncated compression frame"), id="cut_short"),
    ],
)
async def test_a_run_whose_rows_do_not_decode_is_cancelled_and_says_its_sessions_still_run(
    world: World, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    async with serving(world) as sessions:
        run = start(world)
        await sessions.run()
        _rows_undecodable(world, run.id, monkeypatch, error)
        read = world.bridge.read(workspace_id=WORKSPACE, run_id=run.id)
        assert (read.rows, read.snapshot) == (None, None)

        cancelled = _cancel(world, run.id)

        assert cancelled.outcome.applied
        assert (cancelled.sessions_queued, cancelled.sessions_unreachable) == (0, True)
        assert cancelled.gate_rows == ()
        assert world.run(run.id).status == int(RunStatus.CANCELLED)
        assert _finished_body(world, run.id) == _body(queued=0, unreachable=True, gates=0)
        (ended,) = _alerts(world, run.id, AlertKind.RUN_CANCELLED)
        message = AlertPayload.model_validate_json(ended.payload).message
        assert message == UNSTOPPED_SESSIONS_MESSAGES["all"]
        # It asks the owner to act.
        assert ended.priority == int(AlertPriority.NORMAL)
        assert _session_cancels(world, run.id) == []

        await sessions.drain()
        assert sessions.dispatch.stops == []
        # Every later load still fails; none of them pauses the cancelled run.
        ended = world.run(run.id)
        with pytest.raises(EngineLoadFailed):
            world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
        assert world.run(run.id) == ended


async def test_queued_session_cancels_stop_the_runs_orchestrator(world: World) -> None:
    run = start(world, fixture_text("loop"))
    async with serving(world) as sessions:
        # The step hands off and closes; its decision is put to the orchestrator.
        await sessions.run(Agent(sessions))
        orchestrator = sessions.orchestrator_of(run.id)
        stopped = list(sessions.dispatch.stops)
        _engine_unloadable(world, run.id)

        cancelled = _cancel(world, run.id)
        await sessions.drain()

        assert (cancelled.sessions_queued, cancelled.sessions_unreachable) == (2, False)
        assert sessions.dispatch.stops == [*stopped, (orchestrator, USER)]
        assert sessions.dispatch.sessions[orchestrator].closed
        (queued,) = _session_cancels(world, run.id)
        assert queued.status == int(WorkStatus.SUCCEEDED)


def test_open_gate_rows_that_do_not_decode_are_left_and_the_run_still_cancels(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world, GATE_ONLY)
    _engine_unloadable(world, run.id)

    def undecodable(_run_id: str, **_options: object) -> object:
        raise zstandard.ZstdError("not a zstd frame")

    monkeypatch.setattr(world.runs, "list_open_gates", undecodable)

    cancelled = _cancel(world, run.id)

    assert (cancelled.outcome.applied, cancelled.gate_rows) == (True, ())
    assert world.run(run.id).status == int(RunStatus.CANCELLED)
    assert _finished_body(world, run.id) == _body(queued=1, unreachable=False, gates=0)
    (left,) = gate_rows(world, run.id)
    assert left.status == int(GateVisitStatus.OPEN)


def test_more_unclosed_slot_sessions_than_the_cap_queue_the_cap(world: World) -> None:
    run = start(world)
    runs = _runs(world)
    (template,) = (
        slot for (_ws, run_id, _id), slot in runs.agent_slots.items() if run_id == run.id
    )

    def slot(index: int, session_id: str, status: SlotStatus) -> None:
        slot_id = f"{index:032x}"
        runs.agent_slots[(WORKSPACE, run.id, slot_id)] = dataclasses.replace(
            template, id=slot_id, roster_index=index, session_id=session_id, status=int(status)
        )

    # 70 historic slots, closed long ago, and 40 still open: more than one commit takes.
    for index in range(70):
        slot(index, f"closed-{index:02d}", SlotStatus.CLOSED)
    for index in range(40):
        slot(100 + index, f"live-{index:02d}", SlotStatus.WORKING)
    key = (WORKSPACE, run.id)
    runs.runs[key] = dataclasses.replace(runs.runs[key], orchestrator_session_id="o" * 32)
    _engine_unloadable(world, run.id)

    cancelled = _cancel(world, run.id)

    assert MAX_STORE_CANCEL_SESSIONS == 34
    assert (cancelled.sessions_queued, cancelled.sessions_unreachable) == (34, True)
    queued = {json.loads(item.payload)["session_id"] for item in _session_cancels(world, run.id)}
    assert len(queued) == 33 and len(_anchor_cancels(world, run.id)) == 1
    assert "o" * 32 in queued
    assert all(session.startswith("live-") for session in queued - {"o" * 32})
    (ended,) = _alerts(world, run.id, AlertKind.RUN_CANCELLED)
    # Some were stopped, so the alert does not say none were.
    assert (
        AlertPayload.model_validate_json(ended.payload).message
        == (UNSTOPPED_SESSIONS_MESSAGES["some"])
    )
    assert ended.priority == int(AlertPriority.NORMAL)


def test_a_commit_between_the_cancels_reads_and_its_write_makes_it_read_again(
    world: World,
) -> None:
    run = start(world)
    create = row_of(world, run.id, "create_session", engine_kind="create_session")
    # The step's create completes just before the cancel writes: its slot names a session.
    before_next_commit(
        world,
        lambda: world.bridge.feed(
            finished(settle(world, create, WorkStatus.SUCCEEDED, result=CREATED))
        ),
    )

    cancelled = _cancel(world, run.id)

    # The first read found the create unfinished; the second, the session it made.
    assert (cancelled.sessions_queued, cancelled.sessions_unreachable) == (2, False)
    (queued,) = _session_cancels(world, run.id)
    assert json.loads(queued.payload)["session_id"] == "s" * 32


def test_a_step_whose_session_is_still_being_created_is_reported_as_maybe_running(
    world: World,
) -> None:
    # The implementer's create is queued, so its slot names no session yet.
    run = start(world)
    _engine_unloadable(world, run.id)

    cancelled = _cancel(world, run.id)

    assert (cancelled.sessions_queued, cancelled.sessions_unreachable) == (1, True)
    assert _finished_body(world, run.id) == _body(queued=1, unreachable=True, gates=0)
    (ended,) = _alerts(world, run.id, AlertKind.RUN_CANCELLED)
    assert (
        AlertPayload.model_validate_json(ended.payload).message
        == (UNSTOPPED_SESSIONS_MESSAGES["some"])
    )
    assert ended.priority == int(AlertPriority.NORMAL)


def test_a_run_whose_spec_row_is_missing_cancels_and_says_its_sessions_may_run(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world)
    load = world.runs.load_run_state

    def spec_missing(run_id: str, **options: object) -> object:
        if run_id == run.id:
            raise RunNotFound(f"RunSpec for run {run_id!r} not found")
        return load(run_id, **options)  # type: ignore[arg-type]

    monkeypatch.setattr(world.runs, "load_run_state", spec_missing)

    cancelled = _cancel(world, run.id)

    assert (cancelled.outcome.applied, cancelled.sessions_unreachable) == (True, True)
    assert world.run(run.id).status == int(RunStatus.CANCELLED)
    (ended,) = _alerts(world, run.id, AlertKind.RUN_CANCELLED)
    assert (
        AlertPayload.model_validate_json(ended.payload).message
        == (UNSTOPPED_SESSIONS_MESSAGES["all"])
    )


def test_a_later_feed_cancels_a_loadable_engine_first_and_the_row_stays_cancelled(
    world: World,
) -> None:
    run = start(world)
    create = row_of(world, run.id, "create_session", engine_kind="create_session")
    # Cancelled on its row while it could not load; it loads again later.
    _cancel(world, run.id)
    version = world.run(run.id).version

    world.bridge.feed(finished(settle(world, create, WorkStatus.SUCCEEDED, result=CREATED)))

    row = world.run(run.id)
    assert (row.status, row.version) == (int(RunStatus.CANCELLED), version + 1)
    # The fed completion changes nothing once the engine is cancelled.
    kinds = [entry.input.kind for entry in decode_entries(world.engine_log(run.id))]
    assert kinds == ["start_run", "cancel_run"]
    assert world.assert_fold_matches(run.id).status == "cancelled"
    # The engine's cancel stops the step's session as an engine cancel always does.
    (engine_cancel,) = _session_cancels(world, run.id)
    assert json.loads(engine_cancel.payload)["engine_kind"] == "cancel_sessions"
    assert len(_alerts(world, run.id, AlertKind.RUN_CANCELLED)) == 1


def test_a_run_cancelled_on_its_row_before_its_engine_started_never_starts(
    world: World,
) -> None:
    run = start_without_engine(world)
    _cancel(world, run.id)
    cancelled = world.run(run.id)

    started = world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda snapshot: (world.bridge.start_input(snapshot),),
        actor="user:alice",
    )
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    replayed = start(world, spec=run_spec(start_key="bare"), start_key="bare")

    assert (started.outcome.applied, started.entries) == (False, ())
    assert world.run(run.id) == cancelled == replayed
    assert world.engine_log(run.id) == []
