"""The bridge's commits on every DB lane: one transaction each, read back by a fresh process."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from coral.bridge.keys import anchor_effect_key, effect_work_id, store_slot_id
from coral.bridge.service import EngineLoadFailed
from coral.db import RunLogRow
from coral.db.enum_codecs import (
    ActorKind,
    LogKind,
    RunPauseReason,
    RunStatus,
    SlotStatus,
    WorkKind,
    WorkStatus,
)
from coral.stores.protocols import WorkItem
from tests.coral.bridge._world import IMPLEMENT, WORKSPACE, World, finished, start
from tests.coral.workflow_builders import arrow, end, step, workflow_text
from tests.coral.workflow_builders import start as start_node
from tests.stores.coral._faults import fresh_process

WORKER = "worker-1"


def _claim(world: World) -> WorkItem:
    item = world.queue.claim_work(
        WORKER,
        kinds=(int(WorkKind.EFFECT),),
        workspace_id=WORKSPACE,
        now_fn=lambda: float(world.clock.epoch),
    )
    assert item is not None and item.lease_expires_at is not None
    return item


def _finish(
    world: World,
    item: WorkItem,
    status: WorkStatus,
    *,
    error_code: str | None = None,
    result: dict[str, object] | None = None,
    hold: bool = False,
) -> WorkItem:
    assert item.lease_expires_at is not None
    assert world.queue.finish_work(
        item.id,
        worker_id=WORKER,
        expected_lease_expires_at=item.lease_expires_at,
        status=int(status),
        error_code=error_code,
        result=result,
        next_available_at=world.clock.epoch + 300 if hold else None,
        workspace_id=WORKSPACE,
        now_fn=lambda: float(world.clock.epoch),
        hold=hold,
    )
    (row,) = world.queue.get_work([item.id], workspace_id=WORKSPACE)
    return row


def _reopened(coral_db_uri: str) -> World:
    fresh_process(coral_db_uri)
    return World.sql(coral_db_uri)


def test_a_start_commits_its_log_rows_and_outbox_together(coral_db_uri: str) -> None:
    world = World.sql(coral_db_uri)
    run = start(world, actor="user:alice")
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    create_key = next(effect.effect_key for effect in snapshot.state.effects)
    work_ids = [
        effect_work_id(run.id, anchor_effect_key(run.id)),
        effect_work_id(run.id, create_key),
    ]

    reopened = _reopened(coral_db_uri)
    assert reopened.run(run.id).status == int(RunStatus.RUNNING)
    rows = reopened.queue.get_work(work_ids, workspace_id=WORKSPACE)
    assert {row.status for row in rows} == {int(WorkStatus.PENDING)}
    assert len(rows) == 2
    (log,) = reopened.engine_log(run.id)
    assert (log.actor_kind, log.actor_ref) == (int(ActorKind.USER), "user:alice")
    state, _version = reopened.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    (slot,) = state.agent_slots
    assert (slot.id, slot.status) == (store_slot_id(run.id, IMPLEMENT), int(SlotStatus.PENDING))
    reopened.assert_fold_matches(run.id)


def test_a_resume_releases_and_revives_in_the_same_commit(coral_db_uri: str) -> None:
    world = World.sql(coral_db_uri)
    nodes = [start_node(), step("pair", ["implementer", "reviewer"]), end()]
    run = start(
        world, workflow_text(nodes, [arrow("a1", "start", "pair"), arrow("a2", "pair", "end")])
    )
    anchor = _claim(world)
    assert json.loads(anchor.payload)["bridge_item"] == "anchor"
    world.bridge.feed(finished(_finish(world, anchor, WorkStatus.SUCCEEDED, result={})))
    first, second = _claim(world), _claim(world)
    writer, reader = sorted(
        (first, second), key=lambda item: json.loads(item.payload)["engine_slot_id"]
    )
    created = {"session_id": "w" * 32, "role": "step", "generation": 1}
    world.bridge.feed(finished(_finish(world, writer, WorkStatus.SUCCEEDED, result=created)))
    exhausted = _finish(
        world,
        reader,
        WorkStatus.FAILED,
        error_code="infra.transient",
        result={"last_error_code": "session.host_offline"},
    )
    world.bridge.feed(finished(exhausted))
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.INFRA),
    )
    brief = _claim(world)
    assert json.loads(brief.payload)["kind"] == "brief"
    held = _finish(world, brief, WorkStatus.PENDING, error_code="run.paused", hold=True)
    assert held.held_since is not None

    world.clock.advance(30)
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:bob")

    reopened = _reopened(coral_db_uri)
    resumed = reopened.run(run.id)
    assert (resumed.status, resumed.version) == (int(RunStatus.RUNNING), paused.version + 1)
    revived, released = (
        reopened.queue.get_work([item_id], workspace_id=WORKSPACE)[0]
        for item_id in (reader.id, brief.id)
    )
    assert (revived.status, revived.attempts, revived.error_code) == (
        int(WorkStatus.PENDING),
        0,
        None,
    )
    assert (released.status, released.held_since, released.available_at) == (
        int(WorkStatus.PENDING),
        None,
        world.clock.epoch,
    )
    reopened.assert_fold_matches(run.id)


def test_a_corrupt_engine_row_pauses_the_run_once(coral_db_uri: str) -> None:
    world = World.sql(coral_db_uri)
    run = start(world)
    engine = fresh_process(coral_db_uri)
    with Session(engine) as session, session.begin():
        session.execute(
            update(RunLogRow)
            .where(RunLogRow.workspace_id == WORKSPACE, RunLogRow.run_id == run.id)
            .values(body="{}")
        )

    reopened = World.sql(coral_db_uri)
    for _ in range(2):
        with pytest.raises(EngineLoadFailed):
            reopened.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    paused = reopened.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    kinds = [row.kind for row in reopened.runs.read_log(run.id, workspace_id=WORKSPACE)]
    assert kinds == [int(LogKind.ENGINE), int(LogKind.PAUSED)]


def test_a_run_whose_spec_text_does_not_decode_is_paused_once(coral_db_uri: str) -> None:
    world = World.sql(coral_db_uri)
    run = start(world)
    engine = fresh_process(coral_db_uri)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE coral_run_specs SET engine_config = :stored WHERE run_id = :run_id"),
            {"stored": b"\x00\x01not a zstd frame", "run_id": run.id},
        )

    reopened = World.sql(coral_db_uri)
    for _ in range(2):
        with pytest.raises(EngineLoadFailed):
            reopened.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    paused = reopened.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    kinds = [row.kind for row in reopened.runs.read_log(run.id, workspace_id=WORKSPACE)]
    assert kinds == [int(LogKind.ENGINE), int(LogKind.PAUSED)]
