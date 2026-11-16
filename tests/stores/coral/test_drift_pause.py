"""A run paused for drift is stored and read back on every DB lane."""

from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from coral.db.enum_codecs import (
    ActorKind,
    LogKind,
    RunPauseReason,
    RunStatus,
    decode_run_pause_reason,
    encode_run_pause_reason,
)
from coral.stores.protocols import LogEntryDraft, RunStartSpec, Transition
from coral.stores.runs import SqlAlchemyCoralRunStore
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
            Transition(pause_reason=int(RunPauseReason.DRIFT) + 1),
            workspace_id=WORKSPACE,
        )
    _, unchanged_version = reopened.load_run_state(run.id, workspace_id=WORKSPACE)
    assert unchanged_version == version
