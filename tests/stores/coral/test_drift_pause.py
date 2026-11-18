"""A run paused for drift is stored and read back on every DB lane."""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from coral.bridge.codec import decode_entries
from coral.bridge.executors import BridgeThreads
from coral.db.enum_codecs import (
    ActorKind,
    LogKind,
    RunPauseReason,
    RunStatus,
    decode_run_pause_reason,
    encode_run_pause_reason,
)
from coral.engine.types import PauseRun
from coral.model.ids import anchor_session_id
from coral.recovery.drift import DriftFinding, DriftPauser
from coral.stores.protocols import LogEntryDraft, RunStartSpec, Transition
from coral.stores.runs import SqlAlchemyCoralRunStore
from tests.coral.bridge._world import WORKSPACE as ENGINE_WORKSPACE
from tests.coral.bridge._world import World, start
from tests.stores.coral._faults import fresh_process

WORKSPACE = 7


def test_drift_pause_persists_on_every_lane(coral_db_uri: str) -> None:
    store = SqlAlchemyCoralRunStore(coral_db_uri)
    run = store.start_run(
        RunStartSpec(
            workflow_id="wf_drift",
            version_id="ver_drift",
            title="Drift run",
            request_preview="Preview",
            workspace_id=WORKSPACE,
        )
    )
    store.apply_transition(
        run.id, run.version, Transition(status=int(RunStatus.RUNNING)), workspace_id=WORKSPACE
    )
    pause_body = {
        "kind": "pause_run",
        "reason": "drift",
        "cause": "anchor_archived",
        "session_id": "c" * 32,
        "detail": "1700000000",
    }
    store.apply_transition(
        run.id,
        run.version + 1,
        Transition(
            status=int(RunStatus.PAUSED),
            pause_reason=encode_run_pause_reason("drift"),
            logs=(
                LogEntryDraft(
                    kind=int(LogKind.PAUSED),
                    actor_kind=int(ActorKind.ENGINE),
                    body=json.dumps(pause_body, sort_keys=True),
                    idempotency_cksum=hashlib.sha256(b"drift-pause").digest(),
                ),
            ),
        ),
        workspace_id=WORKSPACE,
    )

    reopened = SqlAlchemyCoralRunStore(fresh_process(coral_db_uri))
    state, version = reopened.load_run_state(run.id, workspace_id=WORKSPACE)
    assert state.run.status == RunStatus.PAUSED
    assert state.run.pause_reason == RunPauseReason.DRIFT == 12
    assert decode_run_pause_reason(state.run.pause_reason) == "drift"
    assert version == run.version + 2

    # The widened check constraint still refuses a code no release defines.
    # MySQL reports CHECK violations as OperationalError (3819).
    with pytest.raises((IntegrityError, OperationalError)):
        reopened.apply_transition(
            run.id,
            version,
            Transition(pause_reason=max(RunPauseReason) + 1),
            workspace_id=WORKSPACE,
        )
    _, unchanged_version = reopened.load_run_state(run.id, workspace_id=WORKSPACE)
    assert unchanged_version == version


def test_drift_pauses_once_per_epoch_on_every_lane(coral_db_uri: str) -> None:
    """The epoch in the pause entry's identity is what lets a resumed run pause again."""
    from coral.model.ids import anchor_session_id
    from coral.recovery.drift import DriftFinding, drift_log_checksum, pause_run_for_drift

    store = SqlAlchemyCoralRunStore(coral_db_uri)
    run = store.start_run(
        RunStartSpec(
            workflow_id="wf_drift",
            version_id="ver_drift",
            title="Drift run",
            request_preview="Preview",
            workspace_id=WORKSPACE,
        )
    )
    store.apply_transition(
        run.id, run.version, Transition(status=int(RunStatus.RUNNING)), workspace_id=WORKSPACE
    )
    finding = DriftFinding("anchor_archived", anchor_session_id(WORKSPACE, run.id), "1700000000")

    def pause() -> bool:
        return pause_run_for_drift(
            store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=1_700_000_000
        ).applied

    assert pause()
    assert not pause()
    _, paused_version = store.load_run_state(run.id, workspace_id=WORKSPACE)
    # A resume without unarchiving the anchor, then the next detection.
    store.apply_transition(
        run.id,
        paused_version,
        Transition(status=int(RunStatus.RUNNING), clear_pause_reason=True),
        workspace_id=WORKSPACE,
    )
    assert pause()

    reopened = SqlAlchemyCoralRunStore(fresh_process(coral_db_uri))
    state, version = reopened.load_run_state(run.id, workspace_id=WORKSPACE)
    assert (state.run.status, state.run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.DRIFT)
    pauses = [
        entry
        for entry in reopened.read_log(run.id, workspace_id=WORKSPACE)
        if entry.kind == int(LogKind.PAUSED)
    ]
    assert len(pauses) == 2
    assert [entry.idempotency_cksum for entry in pauses] == [
        drift_log_checksum(run.id, finding, paused_version - 1),
        drift_log_checksum(run.id, finding, paused_version + 1),
    ]
    # Without the epoch, the second pause would repeat the first entry's identity: refused.
    with pytest.raises((IntegrityError, OperationalError)):
        reopened.apply_transition(
            run.id,
            version,
            Transition(
                logs=(
                    LogEntryDraft(
                        kind=int(LogKind.PAUSED),
                        actor_kind=int(ActorKind.ENGINE),
                        body="{}",
                        idempotency_cksum=pauses[0].idempotency_cksum,
                    ),
                )
            ),
            workspace_id=WORKSPACE,
        )


async def test_a_drift_pause_through_the_engine_resumes_on_every_lane(coral_db_uri: str) -> None:
    """The engine's pause and the drift entry commit together; a resume lifts both."""
    world = World.sql(coral_db_uri)
    run = start(world)
    finding = DriftFinding(
        "session_archived", anchor_session_id(ENGINE_WORKSPACE, run.id), "1700000000"
    )
    threads = BridgeThreads(world.bridge)
    try:
        pauser = DriftPauser(world.runs, engine=threads, now_us=lambda: 1_700_000_000_000_000)
        assert (
            await pauser.pause(workspace_id=ENGINE_WORKSPACE, run_id=run.id, finding=finding)
        ).applied

        reopened = SqlAlchemyCoralRunStore(fresh_process(coral_db_uri))
        state, version = reopened.load_run_state(run.id, workspace_id=ENGINE_WORKSPACE)
        assert (state.run.status, state.run.pause_reason) == (
            RunStatus.PAUSED,
            RunPauseReason.DRIFT,
        )
        logs = reopened.read_log(run.id, workspace_id=ENGINE_WORKSPACE)
        [marker] = [entry for entry in logs if entry.kind == int(LogKind.PAUSED)]
        engine_rows = reopened.read_engine_log(
            run.id, workspace_id=ENGINE_WORKSPACE, max_run_version=version
        )
        pause = decode_entries(engine_rows)[-1].input
        assert pause == PauseRun(reason="drift", detail="session_archived")
        assert marker.run_version == engine_rows[-1].run_version == version
        assert json.loads(marker.body)["cause"] == "session_archived"

        world.bridge.resume_run(workspace_id=ENGINE_WORKSPACE, run_id=run.id, actor="user:alice")
        resumed = SqlAlchemyCoralRunStore(fresh_process(coral_db_uri)).get_run(
            run.id, workspace_id=ENGINE_WORKSPACE
        )
        assert resumed is not None
        assert (resumed.status, resumed.pause_reason) == (RunStatus.RUNNING, None)
        assert world.assert_fold_matches(run.id).causes == ()
    finally:
        threads.close()
