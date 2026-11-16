"""Atomic rollback and transaction boundary tests for SqlAlchemyCoralRunStore."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from coral.db import (
    ActivationRow,
    GateVisitRow,
    RunLogRow,
    RunRow,
    WorkRow,
    coral_engine,
    ensure_coral_schema,
)
from coral.db.enum_codecs import GateVisitStatus, RunStatus
from coral.stores.protocols import (
    ActivationDraft,
    GateVisitDraft,
    LogEntryDraft,
    RunStartSpec,
    Transition,
    WorkItemDraft,
)
from coral.stores.runs import SqlAlchemyCoralRunStore


def test_transition_atomic_rollback_on_constraint_violation(db_uri: str) -> None:
    """An exception mid-transition rolls back RunRow updates, child rows, and suppresses hooks."""
    ensure_coral_schema(db_uri)
    store = SqlAlchemyCoralRunStore(db_uri)

    spec = RunStartSpec(
        workflow_id="wf_rollback",
        version_id="ver_rollback",
        title="Rollback Test Run",
        request_preview="Preview",
        workspace_id=1,
    )
    run = store.start_run(spec)
    assert run.version == 1
    assert run.next_log_seq == 1

    hook_fired = False

    def post_commit_hook(run_id: str, version: int) -> None:
        nonlocal hook_fired
        hook_fired = True

    store.register_post_commit(post_commit_hook)

    # Prepare child rows that would succeed if committed
    act_draft = ActivationDraft(
        id="act_fail_1",
        node_id="step_1",
        scope_key="root",
        status=1,
    )
    gate_draft = GateVisitDraft(
        id="gate_fail_1",
        activation_id="act_fail_1",
        node_id="step_1",
        scope_key="root",
        visit_no=1,
        token="token_fail",
        status=int(GateVisitStatus.OPEN),
    )
    work_draft = WorkItemDraft.effect(
        run_id=run.id,
        idempotency_key="eff_rollback",
        payload={"param": "fail"},
    )

    # Induce CheckConstraint failure on RunLogRow:
    # kind=999 is outside valid LOG_KIND enum range (1..21)
    invalid_log = LogEntryDraft(
        kind=999,
        actor_kind=1,
        body="invalid kind payload",
    )

    failing_transition = Transition(
        status=int(RunStatus.RUNNING),
        activations=(act_draft,),
        gate_visits=(gate_draft,),
        outbox_work=(work_draft,),
        logs=(invalid_log,),
    )

    with pytest.raises(IntegrityError):
        store.apply_transition(
            run_id=run.id,
            expected_version=1,
            transition=failing_transition,
            workspace_id=1,
        )

    # 1. Post-commit hook MUST NOT have fired
    assert hook_fired is False

    # 2. Inspect database state directly: assert complete rollback
    engine = coral_engine(db_uri)
    with engine.connect() as conn:
        # RunRow version and next_log_seq must remain 1
        run_row = (
            conn.execute(select(RunRow).where(RunRow.workspace_id == 1, RunRow.id == run.id))
            .mappings()
            .one()
        )
        assert run_row["version"] == 1
        assert run_row["next_log_seq"] == 1
        assert run_row["status"] == int(RunStatus.STARTING)

        # 0 rows in coral_activations
        act_count = conn.scalar(
            select(ActivationRow.id).where(
                ActivationRow.workspace_id == 1, ActivationRow.run_id == run.id
            )
        )
        assert act_count is None

        # 0 rows in coral_gate_visits
        gate_count = conn.scalar(
            select(GateVisitRow.id).where(
                GateVisitRow.workspace_id == 1, GateVisitRow.run_id == run.id
            )
        )
        assert gate_count is None

        # 0 rows in coral_work
        work_count = conn.scalar(
            select(WorkRow.id).where(WorkRow.workspace_id == 1, WorkRow.run_id == run.id)
        )
        assert work_count is None

        # 0 rows in coral_run_log
        log_count = conn.scalar(
            select(RunLogRow.seq).where(RunLogRow.workspace_id == 1, RunLogRow.run_id == run.id)
        )
        assert log_count is None

    # 3. Subsequent valid transition commits cleanly from version 1 to 2
    valid_transition = Transition(
        status=int(RunStatus.RUNNING),
        logs=(
            LogEntryDraft(
                kind=1,
                actor_kind=1,
                body="valid payload",
            ),
        ),
    )
    outcome = store.apply_transition(
        run_id=run.id,
        expected_version=1,
        transition=valid_transition,
        workspace_id=1,
    )
    assert outcome.applied is True
    assert outcome.version == 2
    assert hook_fired is True

    # Confirm version 2 is now in DB
    state, ver = store.load_run_state(run.id, workspace_id=1)
    assert ver == 2
    assert state.status == int(RunStatus.RUNNING)


def test_transition_rollback_on_duplicate_receipt_checksum(db_uri: str) -> None:
    """Duplicate idempotency checksum within same transition triggers rollback."""
    ensure_coral_schema(db_uri)
    store = SqlAlchemyCoralRunStore(db_uri)

    spec = RunStartSpec(
        workflow_id="wf_dup",
        version_id="ver_dup",
        title="Duplicate Checksum Run",
        request_preview="Preview",
        workspace_id=1,
    )
    run = store.start_run(spec)

    dup_cksum = hashlib.sha256(b"duplicate_key").digest()
    log1 = LogEntryDraft(kind=1, actor_kind=1, body="first", idempotency_cksum=dup_cksum)
    log2 = LogEntryDraft(kind=1, actor_kind=1, body="second", idempotency_cksum=dup_cksum)

    # uq_coral_run_log_idempotency triggers IntegrityError on duplicate checksum
    with pytest.raises(IntegrityError):
        store.apply_transition(
            run_id=run.id,
            expected_version=1,
            transition=Transition(logs=(log1, log2)),
            workspace_id=1,
        )

    # Confirm 0 logs committed and version unchanged
    engine = coral_engine(db_uri)
    with engine.connect() as conn:
        run_row = (
            conn.execute(select(RunRow).where(RunRow.workspace_id == 1, RunRow.id == run.id))
            .mappings()
            .one()
        )
        assert run_row["version"] == 1
        assert run_row["next_log_seq"] == 1
