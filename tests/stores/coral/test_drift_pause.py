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
from tests.stores.coral._faults import fresh_process, run_racing

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


def test_session_cap_pause_repeats_after_resume(coral_db_uri: str) -> None:
    """One budget pause entry per pause epoch, as for drift: a resume at the cap re-pauses."""
    from coral.recovery.pause import pause_log_checksum, pause_run_for_session_cap

    store = SqlAlchemyCoralRunStore(coral_db_uri)
    run = store.start_run(
        RunStartSpec(
            workflow_id="wf_budget",
            version_id="ver_budget",
            title="Budget run",
            request_preview="Preview",
            workspace_id=WORKSPACE,
        )
    )
    store.apply_transition(
        run.id, run.version, Transition(status=int(RunStatus.RUNNING)), workspace_id=WORKSPACE
    )
    session_id = "s" * 32

    def pause() -> bool:
        return pause_run_for_session_cap(
            store,
            workspace_id=WORKSPACE,
            run_id=run.id,
            session_id=session_id,
            spent_usd=25.75,
            cap_usd=25.0,
            now_us=1_700_000_000_000_000,
        ).applied

    assert pause()
    assert not pause()
    _, paused_version = store.load_run_state(run.id, workspace_id=WORKSPACE)
    # The user resumes without raising the cap; the session's next tool call pauses again.
    store.apply_transition(
        run.id,
        paused_version,
        Transition(status=int(RunStatus.RUNNING), clear_pause_reason=True),
        workspace_id=WORKSPACE,
    )
    assert pause()

    reopened = SqlAlchemyCoralRunStore(fresh_process(coral_db_uri))
    state, _ = reopened.load_run_state(run.id, workspace_id=WORKSPACE)
    assert (state.run.status, state.run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.BUDGET)
    pauses = [
        entry
        for entry in reopened.read_log(run.id, workspace_id=WORKSPACE)
        if entry.kind == int(LogKind.PAUSED)
    ]
    parts = ("coral-budget", run.id, "session_cap", session_id)
    assert [entry.idempotency_cksum for entry in pauses] == [
        pause_log_checksum(parts, paused_version - 1),
        pause_log_checksum(parts, paused_version + 1),
    ]
    assert all(entry.actor_kind == int(ActorKind.ENGINE) for entry in pauses)
    assert all(entry.created_at_us == 1_700_000_000_000_000 for entry in pauses)
    assert [json.loads(entry.body) for entry in pauses] == [
        {
            "kind": "pause_run",
            "reason": "budget",
            "cause": "session_cap",
            "session_id": session_id,
            "spent_usd": 25.75,
            "cap_usd": 25.0,
        }
    ] * 2


def test_racing_session_cap_pauses_commit_one_entry_per_epoch(coral_db_uri: str) -> None:
    """Several over-cap sessions of one run, some calling twice at once, pause it once."""
    from coral.recovery.pause import pause_run_for_session_cap

    store = SqlAlchemyCoralRunStore(coral_db_uri)
    run = store.start_run(
        RunStartSpec(
            workflow_id="wf_budget",
            version_id="ver_budget",
            title="Budget run",
            request_preview="Preview",
            workspace_id=WORKSPACE,
        )
    )
    store.apply_transition(
        run.id, run.version, Transition(status=int(RunStatus.RUNNING)), workspace_id=WORKSPACE
    )
    sessions = [f"{index}" * 32 for index in range(4)]

    def pause(index: int) -> bool:
        return pause_run_for_session_cap(
            store,
            workspace_id=WORKSPACE,
            run_id=run.id,
            session_id=sessions[index % len(sessions)],
            spent_usd=30.0,
            cap_usd=25.0,
            now_us=1_700_000_000_000_000,
        ).applied

    for epoch in range(2):
        outcomes = run_racing(2 * len(sessions), pause)
        assert [outcome.error for outcome in outcomes] == [None] * 2 * len(sessions)
        assert sum(bool(outcome.value) for outcome in outcomes) == 1
        state, version = store.load_run_state(run.id, workspace_id=WORKSPACE)
        assert (state.run.status, state.run.pause_reason) == (
            RunStatus.PAUSED,
            RunPauseReason.BUDGET,
        )
        if epoch == 0:
            # Resumed without a raised cap: the next race pauses it once more.
            store.apply_transition(
                run.id,
                version,
                Transition(status=int(RunStatus.RUNNING), clear_pause_reason=True),
                workspace_id=WORKSPACE,
            )

    reopened = SqlAlchemyCoralRunStore(fresh_process(coral_db_uri))
    pauses = [
        entry
        for entry in reopened.read_log(run.id, workspace_id=WORKSPACE)
        if entry.kind == int(LogKind.PAUSED)
    ]
    assert len(pauses) == 2
    assert {json.loads(entry.body)["session_id"] for entry in pauses} <= set(sessions)
    _, version = reopened.load_run_state(run.id, workspace_id=WORKSPACE)
    assert version == run.version + 4
