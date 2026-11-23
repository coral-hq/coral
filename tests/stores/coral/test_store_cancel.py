"""The store-only cancel on every DB lane: one commit, read back by a fresh process."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from coral.alerts.rules import UNSTOPPED_SESSIONS_MESSAGES
from coral.alerts.types import AlertPayload
from coral.bridge.config import LOCK_TIMEOUT_S
from coral.bridge.keys import effect_work_id
from coral.db import RunLogRow
from coral.db.enum_codecs import (
    AlertKind,
    AlertStatus,
    GateVisitStatus,
    LogKind,
    RunStatus,
    WorkStatus,
)
from coral.model.ids import effect_session_id
from coral.queue import FinishedWork
from coral.recovery.cancel import StoreCancel, cancel_run_row
from coral.stores.alerts import SqlAlchemyAlertStore
from tests.coral.bridge._gates import GATE_ONLY, complete, effects, gate_rows
from tests.coral.bridge._world import IMPLEMENT, WORKSPACE, World, run_spec, start
from tests.stores.coral._faults import fresh_process, run_racing

ACTOR = "alice"
SESSION = "s" * 32


def _cancel(world: World, run_id: str) -> StoreCancel:
    return cancel_run_row(
        world.runs,
        workspace_id=WORKSPACE,
        run_id=run_id,
        actor=ACTOR,
        now_us=world.clock.epoch * 1_000_000,
        lock_timeout_s=LOCK_TIMEOUT_S,
    )


def _reopened(coral_db_uri: str) -> World:
    fresh_process(coral_db_uri)
    return World.sql(coral_db_uri)


def _engine_unloadable(coral_db_uri: str, run_id: str) -> None:
    """The run's rows still decode; its engine log does not."""
    engine = fresh_process(coral_db_uri)
    with Session(engine) as session, session.begin():
        session.execute(
            update(RunLogRow)
            .where(RunLogRow.workspace_id == WORKSPACE, RunLogRow.run_id == run_id)
            .values(body="{}")
        )


def _kinds(world: World, run_id: str) -> list[int]:
    return [row.kind for row in world.runs.read_log(run_id, workspace_id=WORKSPACE)]


def test_a_run_whose_rows_do_not_decode_is_read_and_cancelled_on_its_row(
    coral_db_uri: str,
) -> None:
    run = start(World.sql(coral_db_uri))
    engine = fresh_process(coral_db_uri)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE coral_run_specs SET engine_config = :stored WHERE run_id = :run_id"),
            {"stored": b"\x00\x01not a zstd frame", "run_id": run.id},
        )
    world = World.sql(coral_db_uri)

    read = world.bridge.read(workspace_id=WORKSPACE, run_id=run.id)
    assert (read.run, read.rows, read.snapshot) == (world.run(run.id), None, None)
    assert world.run(run.id).version == run.version
    assert _kinds(world, run.id) == [int(LogKind.ENGINE)]

    cancelled = _cancel(world, run.id)
    assert cancelled.outcome.applied
    assert (cancelled.sessions_queued, cancelled.sessions_unreachable) == (0, True)

    reopened = _reopened(coral_db_uri)
    row = reopened.run(run.id)
    assert (row.status, row.finished_at) == (int(RunStatus.CANCELLED), reopened.clock.epoch)
    assert _kinds(reopened, run.id) == [int(LogKind.ENGINE), int(LogKind.RUN_FINISHED)]
    finished = reopened.runs.read_log(run.id, workspace_id=WORKSPACE)[-1]
    body = json.loads(finished.body)
    assert (body["store_only"], body["sessions_queued"], body["sessions_unreachable"]) == (
        True,
        0,
        True,
    )
    alerts = SqlAlchemyAlertStore(coral_db_uri).list_for_run(workspace_id=WORKSPACE, run_id=run.id)
    (ended,) = [alert for alert in alerts if alert.kind == int(AlertKind.RUN_CANCELLED)]
    assert ended.status == int(AlertStatus.OPEN)
    assert (
        AlertPayload.model_validate_json(ended.payload).message
        == (UNSTOPPED_SESSIONS_MESSAGES["all"])
    )

    again = _cancel(reopened, run.id)
    assert not again.outcome.applied
    assert _kinds(_reopened(coral_db_uri), run.id) == [
        int(LogKind.ENGINE),
        int(LogKind.RUN_FINISHED),
    ]


def test_a_run_whose_spec_row_is_missing_is_read_and_cancelled_on_its_row(
    coral_db_uri: str,
) -> None:
    run = start(World.sql(coral_db_uri))
    engine = fresh_process(coral_db_uri)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM coral_run_specs WHERE run_id = :run_id"), {"run_id": run.id}
        )
    world = World.sql(coral_db_uri)

    read = world.bridge.read(workspace_id=WORKSPACE, run_id=run.id)
    assert (read.run, read.rows, read.snapshot) == (world.run(run.id), None, None)

    cancelled = _cancel(world, run.id)

    assert (cancelled.outcome.applied, cancelled.sessions_unreachable) == (True, True)
    assert _reopened(coral_db_uri).run(run.id).status == int(RunStatus.CANCELLED)


def test_a_store_only_cancel_queues_session_cancels_and_closes_gate_rows(
    coral_db_uri: str,
) -> None:
    world = World.sql(coral_db_uri)
    stepping = start(world)
    complete(
        world,
        stepping.id,
        "create_session",
        IMPLEMENT,
        {"session_id": SESSION, "role": "step", "generation": 1},
    )
    gated = start(world, GATE_ONLY, spec=run_spec(start_key="gated"), start_key="gated")
    for run_id in (stepping.id, gated.id):
        _engine_unloadable(coral_db_uri, run_id)
    world = World.sql(coral_db_uri)

    # The step's session and the anchor.
    assert _cancel(world, stepping.id).sessions_queued == 2
    assert len(_cancel(world, gated.id).gate_rows) == 1

    reopened = _reopened(coral_db_uri)
    key = f"{stepping.id}:0:cancel_sessions:{SESSION}"
    (queued,) = reopened.queue.get_work([effect_work_id(stepping.id, key)], workspace_id=WORKSPACE)
    assert queued.status == int(WorkStatus.PENDING)
    assert json.loads(queued.payload) == {
        "effect_type": "cancel_sessions",
        "effect_key": key,
        "session_id": SESSION,
        "closed_label": True,
    }
    assert (queued.scope_key, queued.slot_generation) == (None, None)
    (closed,) = gate_rows(reopened, gated.id)
    assert closed.status == int(GateVisitStatus.CANCELLED)
    assert reopened.runs.list_open_gates(gated.id, workspace_id=WORKSPACE) == []


def test_racing_store_only_cancels_finish_the_run_once(coral_db_uri: str) -> None:
    world = World.sql(coral_db_uri)
    run = start(world)
    _engine_unloadable(coral_db_uri, run.id)
    world = World.sql(coral_db_uri)

    outcomes = run_racing(2, lambda _index: _cancel(world, run.id))

    assert [outcome.error for outcome in outcomes] == [None, None]
    applied = [
        outcome.value.outcome.applied
        for outcome in outcomes
        if isinstance(outcome.value, StoreCancel)
    ]
    assert sorted(applied) == [False, True]
    reopened = _reopened(coral_db_uri)
    assert _kinds(reopened, run.id).count(int(LogKind.RUN_FINISHED)) == 1
    assert reopened.run(run.id).status == int(RunStatus.CANCELLED)


@pytest.mark.parametrize("order", ["cancel_first", "feed_first", "racing"])
def test_a_store_only_cancel_and_an_engine_commit_end_the_run_once_in_any_order(
    coral_db_uri: str, order: str
) -> None:
    world = World.sql(coral_db_uri)
    run = start(world)
    (create,) = effects(world, run.id, "create_session")
    (item,) = world.queue.get_work(
        [effect_work_id(run.id, create.effect_key)], workspace_id=WORKSPACE
    )
    session_id = effect_session_id(WORKSPACE, create.effect_key)
    created = FinishedWork(
        item=item,
        status=int(WorkStatus.SUCCEEDED),
        error_code=None,
        result={"session_id": session_id, "role": "step", "generation": 1},
    )
    # Another process, whose engine still loads, feeds the step's create meanwhile.
    feeder = World.sql(coral_db_uri)
    feeder.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    operations = [lambda: _cancel(world, run.id), lambda: feeder.bridge.feed(created)]

    if order == "racing":
        outcomes = run_racing(2, lambda index: operations[index]())
        assert [outcome.error for outcome in outcomes] == [None, None]
    else:
        for operation in operations if order == "cancel_first" else operations[::-1]:
            operation()

    reopened = _reopened(coral_db_uri)
    assert reopened.run(run.id).status == int(RunStatus.CANCELLED)
    assert _kinds(reopened, run.id).count(int(LogKind.RUN_FINISHED)) == 1
    # The created session is named either way: by the store-only cancel from its slot
    # when the feed lands first, else by the engine's cancel the feed's commit makes.
    engine = reopened.bridge.load(workspace_id=WORKSPACE, run_id=run.id).state
    keys = [
        f"{run.id}:0:cancel_sessions:{session_id}",
        *(effect.effect_key for effect in engine.effects if effect.kind == "cancel_sessions"),
    ]
    rows = reopened.queue.get_work(
        [effect_work_id(run.id, key) for key in keys], workspace_id=WORKSPACE
    )
    assert {json.loads(row.payload)["session_id"] for row in rows} == {session_id}
    if order != "racing":
        # Only a feed after the cancel converges the engine; a racing one may do either.
        assert engine.status == ("cancelled" if order == "cancel_first" else "running")
