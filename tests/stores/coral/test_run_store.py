"""Integration tests for SqlAlchemyCoralRunStore across SQLite, Postgres, CRDB, and MySQL."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select

from coral.db import WorkRow, coral_engine, ensure_coral_schema
from coral.db.enum_codecs import GateVisitStatus, RunStatus, WorkStatus
from coral.stores.protocols import (
    ActivationDraft,
    GateVisitDraft,
    LogEntryDraft,
    RunStartSpec,
    RunState,
    RunVersionConflict,
    StartKeyConflict,
    Transition,
    TransitionTooLarge,
    WorkItemDraft,
)
from coral.stores.run_commit import commit_with_retry
from coral.stores.runs import SqlAlchemyCoralRunStore


def test_start_run_idempotency_and_conflict(db_uri: str) -> None:
    """Non-keyed runs are distinct; start_key is idempotent or conflicts on mismatch."""
    ensure_coral_schema(db_uri)
    store = SqlAlchemyCoralRunStore(db_uri)

    # 1. Non-keyed runs generate distinct IDs
    spec_non_keyed = RunStartSpec(
        workflow_id="wf_nk",
        version_id="ver_nk",
        title="Non-Keyed Run",
        request_preview="Preview",
        workspace_id=1,
    )
    run1 = store.start_run(spec_non_keyed)
    run2 = store.start_run(spec_non_keyed)
    assert run1.id != run2.id
    assert run1.version == 1
    assert run2.version == 1
    assert run1.status == int(RunStatus.STARTING)

    # 2. Keyed runs with matching spec return identical CoralRun
    spec_keyed = RunStartSpec(
        workflow_id="wf_k",
        version_id="ver_k",
        title="Keyed Run",
        request_preview="Preview Keyed",
        workspace_id=1,
        user_id="user_alice",
    )
    k1 = store.start_run(spec_keyed, start_key="webhook_123")
    k2 = store.start_run(spec_keyed, start_key="webhook_123")
    assert k1.id == k2.id
    assert k1.version == 1
    assert k2.version == 1

    # 3. Keyed run with different spec raises StartKeyConflict
    spec_conflict = RunStartSpec(
        workflow_id="wf_k",
        version_id="ver_k",
        title="Changed Title",
        request_preview="Preview Keyed",
        workspace_id=1,
        user_id="user_alice",
    )
    with pytest.raises(StartKeyConflict, match="webhook_123"):
        store.start_run(spec_conflict, start_key="webhook_123")


def test_apply_transition_cas_contention_and_retry(db_uri: str) -> None:
    """CAS transitions enforce expected_version and commit_with_retry resolves contention."""
    ensure_coral_schema(db_uri)
    store = SqlAlchemyCoralRunStore(db_uri)

    spec = RunStartSpec(
        workflow_id="wf_cas",
        version_id="ver_cas",
        title="CAS Run",
        request_preview="Preview",
        workspace_id=1,
    )
    run = store.start_run(spec)

    state, version = store.load_run_state(run.id, workspace_id=1)
    assert version == 1
    assert state.run_id == run.id

    # Caller 1 succeeds at version 1
    t1 = Transition(
        status=int(RunStatus.RUNNING),
        logs=(
            LogEntryDraft(
                kind=1,
                actor_kind=1,
                body='{"event": "start"}',
            ),
        ),
    )
    outcome1 = store.apply_transition(run.id, expected_version=1, transition=t1, workspace_id=1)
    assert outcome1.version == 2
    assert outcome1.applied is True

    # Caller 2 attempting at expected_version=1 fails with RunVersionConflict
    t2 = Transition(
        status=int(RunStatus.RUNNING),
        logs=(LogEntryDraft(kind=1, actor_kind=1, body='{"event": "stale"}'),),
    )
    with pytest.raises(RunVersionConflict) as exc_info:
        store.apply_transition(run.id, expected_version=1, transition=t2, workspace_id=1)

    assert exc_info.value.expected_version == 1
    assert exc_info.value.actual_version == 2

    # commit_with_retry transparently reads fresh state and commits
    def advance(s: RunState) -> Transition:
        return Transition(
            logs=(LogEntryDraft(kind=1, actor_kind=1, body=f'{{"v": {s.version}}}'),),
        )

    retry_outcome = commit_with_retry(
        run_store=store,
        workspace_id=1,
        run_id=run.id,
        reduce_fn=advance,
    )
    assert retry_outcome.applied is True
    assert retry_outcome.version == 3


def test_transition_too_large(db_uri: str) -> None:
    """Transitions exceeding 64 logs or 64 outbox items are rejected before DB calls."""
    ensure_coral_schema(db_uri)
    store = SqlAlchemyCoralRunStore(db_uri)

    spec = RunStartSpec(
        workflow_id="wf_cap",
        version_id="ver_cap",
        title="Cap Run",
        request_preview="Preview",
        workspace_id=1,
    )
    run = store.start_run(spec)

    # 65 logs
    too_many_logs = Transition(
        logs=tuple(LogEntryDraft(kind=1, actor_kind=1, body=f'{{"i": {i}}}') for i in range(65))
    )
    with pytest.raises(TransitionTooLarge, match="65 logs"):
        store.apply_transition(run.id, 1, too_many_logs, workspace_id=1)

    # 65 outbox items
    too_many_work = Transition(
        outbox_work=tuple(
            WorkItemDraft.effect(
                run_id=run.id,
                idempotency_key=f"eff_{i}",
                payload={"i": i},
            )
            for i in range(65)
        )
    )
    with pytest.raises(TransitionTooLarge, match="65 outbox"):
        store.apply_transition(run.id, 1, too_many_work, workspace_id=1)


def test_outbox_work_and_consumed_work_ids(db_uri: str) -> None:
    """Outbox items are inserted idempotently; consumed items transition to SUCCEEDED."""
    ensure_coral_schema(db_uri)
    store = SqlAlchemyCoralRunStore(db_uri)

    spec = RunStartSpec(
        workflow_id="wf_work",
        version_id="ver_work",
        title="Work Run",
        request_preview="Preview",
        workspace_id=1,
    )
    run = store.start_run(spec)

    effect_draft = WorkItemDraft.effect(
        run_id=run.id,
        idempotency_key="create_session_1",
        payload={"slot_id": "slot_a"},
    )

    t1 = Transition(outbox_work=(effect_draft,))
    outcome1 = store.apply_transition(run.id, 1, t1, workspace_id=1)
    assert outcome1.version == 2
    assert outcome1.work_ids == (effect_draft.id,)

    engine = coral_engine(db_uri)
    with engine.connect() as conn:
        row = (
            conn.execute(
                select(WorkRow).where(WorkRow.workspace_id == 1, WorkRow.id == effect_draft.id)
            )
            .mappings()
            .one()
        )
        assert row["status"] == int(WorkStatus.PENDING)
        assert row["finished_at"] is None

    # Re-emitting identical outbox work does not fail or clobber
    t2 = Transition(outbox_work=(effect_draft,))
    outcome2 = store.apply_transition(run.id, 2, t2, workspace_id=1)
    assert outcome2.version == 3

    # Consume the work item inside the next transition
    t3 = Transition(consumed_work_ids=(effect_draft.id,))
    outcome3 = store.apply_transition(run.id, 3, t3, workspace_id=1)
    assert outcome3.version == 4

    with engine.connect() as conn:
        row = (
            conn.execute(
                select(WorkRow).where(WorkRow.workspace_id == 1, WorkRow.id == effect_draft.id)
            )
            .mappings()
            .one()
        )
        assert row["status"] == int(WorkStatus.SUCCEEDED)
        assert row["finished_at"] is not None


def test_keyset_scans_and_cross_workspace_isolation(db_uri: str) -> None:
    """Keyset pagination queries handle ties, ordering, and cross-workspace boundaries."""
    ensure_coral_schema(db_uri)
    store = SqlAlchemyCoralRunStore(db_uri)

    # Create runs across workspaces 1 and 2 with controlled timestamps
    base_time = 1_700_000_000
    r1 = store.start_run(RunStartSpec("wf", "v1", "Run 1", "p", workspace_id=1), now=base_time)
    r2 = store.start_run(
        RunStartSpec("wf", "v1", "Run 2", "p", workspace_id=1), now=base_time + 10
    )
    r3 = store.start_run(
        RunStartSpec("wf", "v1", "Run 3", "p", workspace_id=1),
        now=base_time + 10,  # tie
    )
    r_ws2 = store.start_run(
        RunStartSpec("wf", "v1", "Run WS2", "p", workspace_id=2), now=base_time + 20
    )

    # 1. list_runs for workspace 1 (descending)
    page1 = store.list_runs(workspace_id=1, limit=2, descending=True)
    assert len(page1) == 2
    cursor = (page1[-1].created_at, page1[-1].id)
    page2 = store.list_runs(workspace_id=1, cursor=cursor, limit=2, descending=True)
    assert len(page2) == 1
    all_ws1_ids = [r.id for r in page1] + [r.id for r in page2]
    assert set(all_ws1_ids) == {r1.id, r2.id, r3.id}
    assert r_ws2.id not in all_ws1_ids

    # 2. list_runs for workspace 2
    ws2_runs = store.list_runs(workspace_id=2)
    assert len(ws2_runs) == 1
    assert ws2_runs[0].id == r_ws2.id

    # 3. list_active_runs_all_workspaces
    active = store.list_active_runs_all_workspaces(limit=10)
    active_ids = {r.id for r in active}
    assert {r1.id, r2.id, r3.id, r_ws2.id}.issubset(active_ids)

    # Complete r1 -> status=COMPLETED (terminal)
    store.apply_transition(
        r1.id,
        1,
        Transition(status=int(RunStatus.COMPLETED)),
        workspace_id=1,
    )
    active_after = store.list_active_runs_all_workspaces(limit=10)
    active_after_ids = {r.id for r in active_after}
    assert r1.id not in active_after_ids

    # 4. read_log and find_receipt
    cmd_cksum = hashlib.sha256(b"cmd_token").digest()
    store.apply_transition(
        r2.id,
        1,
        Transition(
            logs=(
                LogEntryDraft(kind=1, actor_kind=1, body="log 1"),
                LogEntryDraft(kind=2, actor_kind=2, body="log 2", idempotency_cksum=cmd_cksum),
                LogEntryDraft(kind=3, actor_kind=1, body="log 3"),
            )
        ),
        workspace_id=1,
    )

    logs = store.read_log(r2.id, after_seq=1, limit=2, workspace_id=1)
    assert len(logs) == 2
    assert logs[0].seq == 2
    assert logs[1].seq == 3

    receipt = store.find_receipt(r2.id, cmd_cksum, workspace_id=1)
    assert receipt is not None
    assert receipt.seq == 2
    assert receipt.run_version == 2

    # Receipt in wrong workspace or wrong checksum returns None
    assert store.find_receipt(r2.id, cmd_cksum, workspace_id=2) is None
    assert store.find_receipt(r2.id, b"wrong_cksum", workspace_id=1) is None

    # 5. list_open_gates_all_workspaces
    gate_draft = GateVisitDraft(
        id="gate_1",
        activation_id="act_1",
        node_id="gate_node",
        scope_key="root",
        visit_no=1,
        token="token_xyz",
        status=int(GateVisitStatus.OPEN),
    )
    store.apply_transition(r2.id, 2, Transition(gate_visits=(gate_draft,)), workspace_id=1)
    open_gates = store.list_open_gates_all_workspaces(limit=10)
    assert any(g.id == "gate_1" for g in open_gates)


def test_post_commit_hook_execution_and_resilience(db_uri: str) -> None:
    """Post-commit callbacks execute after commit, and callback exceptions do not fail commit."""
    ensure_coral_schema(db_uri)
    store = SqlAlchemyCoralRunStore(db_uri)

    spec = RunStartSpec("wf", "v1", "Hook Run", "p", workspace_id=1)
    run = store.start_run(spec)

    calls: list[tuple[str, int]] = []

    def failing_hook(run_id: str, version: int) -> None:
        calls.append((run_id, version))
        raise RuntimeError("Post-commit hook failed!")

    store.register_post_commit(failing_hook)

    # apply_transition must succeed despite hook exception
    outcome = store.apply_transition(
        run.id,
        1,
        Transition(status=int(RunStatus.RUNNING)),
        workspace_id=1,
    )
    assert outcome.applied is True
    assert outcome.version == 2
    assert calls == [(run.id, 2)]

    # Run state was committed to DB
    loaded, v = store.load_run_state(run.id, workspace_id=1)
    assert v == 2
    assert loaded.status == int(RunStatus.RUNNING)


def test_updating_activation_preserves_original_created_at(db_uri: str) -> None:
    """Updating an activation with default created_at=0 preserves original created_at."""
    ensure_coral_schema(db_uri)
    store = SqlAlchemyCoralRunStore(db_uri)

    run = store.start_run(RunStartSpec("wf", "v1", "Timestamp Run", "p", workspace_id=1), now=100)
    store.apply_transition(
        run.id,
        1,
        Transition(
            activations=(
                ActivationDraft(id="act_ts", node_id="step_1", scope_key="root", status=2),
            )
        ),
        workspace_id=1,
        now=1_000,
    )
    store.apply_transition(
        run.id,
        2,
        Transition(
            activations=(
                ActivationDraft(id="act_ts", node_id="step_1", scope_key="root", status=4),
            )
        ),
        workspace_id=1,
        now=2_000,
    )
    loaded, _ = store.load_run_state(run.id, workspace_id=1)
    assert len(loaded.activations) == 1
    assert loaded.activations[0].created_at == 1_000
    assert loaded.activations[0].updated_at == 2_000
