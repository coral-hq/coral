"""Integration tests for SqlAlchemyCoralRunStore across SQLite, Postgres, CRDB, and MySQL."""

from __future__ import annotations

import dataclasses
import hashlib
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import event, select, text

from coral.alerts.types import LOCAL_USER_ID
from coral.db import WorkRow, coral_engine, ensure_coral_schema
from coral.db.enum_codecs import GateVisitStatus, LogKind, RunStatus, WorkStatus
from coral.omni.protocols import Viewer
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import (
    MAX_OWNED_RUNS_LIMIT,
    STORED_TEXT_ERRORS,
    ActivationDraft,
    CoralRun,
    GateVisitDraft,
    InvalidRunCursor,
    LogEntryDraft,
    RunLogEntry,
    RunStartSpec,
    RunState,
    RunStore,
    RunVersionConflict,
    StartKeyConflict,
    Transition,
    TransitionTooLarge,
    WorkItemDraft,
)
from coral.stores.run_commit import commit_with_retry
from coral.stores.runs import SqlAlchemyCoralRunStore
from omnigent.db import current_query_name
from tests.stores.coral._alerts import (
    ALICE,
    BOB,
    NOW,
    OTHER_WORKSPACE,
    WORKSPACE,
    start_owned_run,
)


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


@pytest.mark.parametrize("store_kind", ["sqlalchemy", "fake"])
def test_list_open_gates_reads_only_the_runs_open_rows(db_uri: str, store_kind: str) -> None:
    ensure_coral_schema(db_uri)
    store: SqlAlchemyCoralRunStore | FakeRunStore = (
        SqlAlchemyCoralRunStore(db_uri) if store_kind == "sqlalchemy" else FakeRunStore()
    )
    run = store.start_run(RunStartSpec("wf", "v1", "Run", "p", workspace_id=1))
    other = store.start_run(RunStartSpec("wf", "v1", "Other", "p", workspace_id=1))
    elsewhere = store.start_run(RunStartSpec("wf", "v1", "Elsewhere", "p", workspace_id=2))

    def gate(gate_id: str, status: GateVisitStatus) -> GateVisitDraft:
        return GateVisitDraft(
            id=gate_id,
            activation_id="act_1",
            node_id="gate_node",
            scope_key="root",
            visit_no=1,
            token=f"token_{gate_id}",
            status=int(status),
            elicitation_id=f"coral_gate_{gate_id}",
        )

    store.apply_transition(
        run.id,
        1,
        Transition(
            gate_visits=(
                gate("g2", GateVisitStatus.OPEN),
                gate("g1", GateVisitStatus.OPEN),
                gate("g3", GateVisitStatus.RESOLVED),
            )
        ),
        workspace_id=1,
    )
    store.apply_transition(
        other.id, 1, Transition(gate_visits=(gate("g4", GateVisitStatus.OPEN),)), workspace_id=1
    )
    store.apply_transition(
        elsewhere.id,
        1,
        Transition(gate_visits=(gate("g5", GateVisitStatus.OPEN),)),
        workspace_id=2,
    )

    assert [g.id for g in store.list_open_gates(run.id, workspace_id=1)] == ["g1", "g2"]
    assert store.list_open_gates(run.id, workspace_id=2) == []
    assert [g.elicitation_id for g in store.list_open_gates(elsewhere.id, workspace_id=2)] == [
        "coral_gate_g5"
    ]


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


@pytest.mark.parametrize("store_kind", ["sqlalchemy", "fake"])
def test_post_commit_unregister_removes_only_its_own_registration(
    db_uri: str, store_kind: str
) -> None:
    """Each registration's unregister is idempotent and leaves the same callback's other one."""
    ensure_coral_schema(db_uri)
    store: RunStore = (
        SqlAlchemyCoralRunStore(db_uri) if store_kind == "sqlalchemy" else FakeRunStore()
    )
    run = store.start_run(RunStartSpec("wf", "v1", "Hook Run", "p", workspace_id=1))
    calls: list[tuple[str, str, int]] = []

    def first(run_id: str, version: int) -> None:
        calls.append(("first", run_id, version))

    def second(run_id: str, version: int) -> None:
        calls.append(("second", run_id, version))

    unregister_first = store.register_post_commit(first)
    unregister_second = store.register_post_commit(second)
    unregister_second_again = store.register_post_commit(second)
    store.apply_transition(run.id, 1, Transition(status=int(RunStatus.RUNNING)), workspace_id=1)
    assert calls == [("first", run.id, 2), ("second", run.id, 2), ("second", run.id, 2)]

    unregister_first()
    unregister_second()
    unregister_second()
    calls.clear()
    store.apply_transition(run.id, 2, Transition(status=int(RunStatus.PAUSED)), workspace_id=1)
    # The second registration of the same callback survives the first one's unregister.
    assert calls == [("second", run.id, 3)]

    unregister_second_again()
    calls.clear()
    store.apply_transition(run.id, 3, Transition(status=int(RunStatus.RUNNING)), workspace_id=1)
    assert calls == []


@pytest.mark.parametrize("store_kind", ["sqlalchemy", "fake"])
def test_post_commit_hooks_survive_a_failing_hook_and_changes_made_while_they_run(
    db_uri: str, store_kind: str
) -> None:
    """A raising hook never stops the next; (un)registering inside a hook applies next commit."""
    ensure_coral_schema(db_uri)
    store: RunStore = (
        SqlAlchemyCoralRunStore(db_uri) if store_kind == "sqlalchemy" else FakeRunStore()
    )
    run = store.start_run(RunStartSpec("wf", "v1", "Hook Run", "p", workspace_id=1))
    calls: list[str] = []
    unregisters: dict[str, Callable[[], None]] = {}

    def failing(_run_id: str, _version: int) -> None:
        calls.append("failing")
        raise RuntimeError("an unrelated hook failed")

    def late(_run_id: str, _version: int) -> None:
        calls.append("late")

    def once(_run_id: str, _version: int) -> None:
        calls.append("once")
        # Called on the committing thread with the registry unlocked: no deadlock.
        unregisters["once"]()
        unregisters["late"] = store.register_post_commit(late)

    def cache(_run_id: str, _version: int) -> None:
        calls.append("cache")

    store.register_post_commit(failing)
    unregisters["once"] = store.register_post_commit(once)
    store.register_post_commit(cache)

    store.apply_transition(run.id, 1, Transition(status=int(RunStatus.RUNNING)), workspace_id=1)
    assert calls == ["failing", "once", "cache"]
    calls.clear()
    store.apply_transition(run.id, 2, Transition(status=int(RunStatus.PAUSED)), workspace_id=1)
    assert calls == ["failing", "cache", "late"]
    # A conflicting transition commits nothing and calls no hook.
    calls.clear()
    with pytest.raises(RunVersionConflict):
        store.apply_transition(
            run.id, 2, Transition(status=int(RunStatus.RUNNING)), workspace_id=1
        )
    assert calls == []


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


# ── Owner-scoped run list and tolerant log reads (SQL and fake) ─────────────────

# Stored text that does not decode: a framed value whose zstd frame is garbage, and legacy
# unframed bytes that are not UTF-8.
_ZSTD_GARBAGE = b"\x00\x01not a zstd frame"
_NOT_UTF8 = b"\xff\xfe"
_CORRUPT_LOG_TEXT = {
    "body": text(
        "UPDATE coral_run_log SET body = :stored "
        "WHERE workspace_id = :workspace_id AND run_id = :run_id AND seq = :seq"
    ),
    "view_patch": text(
        "UPDATE coral_run_log SET view_patch = :stored "
        "WHERE workspace_id = :workspace_id AND run_id = :run_id AND seq = :seq"
    ),
}


def _corrupt_log_text(uri: str, run_id: str, seq: int, column: str, stored: bytes) -> None:
    with coral_engine(uri).begin() as connection:
        connection.execute(
            _CORRUPT_LOG_TEXT[column],
            {"stored": stored, "workspace_id": WORKSPACE, "run_id": run_id, "seq": seq},
        )


@dataclass(frozen=True)
class _Lane:
    """A run store, and how to make the stored text of one of its log rows undecodable."""

    store: SqlAlchemyCoralRunStore | FakeRunStore
    corrupt: Callable[[str, int, str, bytes], None]


@pytest.fixture(params=["sql", "fake"])
def lane(request: pytest.FixtureRequest) -> _Lane:
    """The SQL run store or the fake; each parity test holds both to the same expectations."""
    if request.param == "fake":
        fake = FakeRunStore(default_workspace_id=WORKSPACE)

        def corrupt_fake(run_id: str, seq: int, _column: str, _stored: bytes) -> None:
            fake.undecodable_logs.add((WORKSPACE, run_id, seq))

        return _Lane(fake, corrupt_fake)
    uri = request.getfixturevalue("coral_db_uri")

    def corrupt_sql(run_id: str, seq: int, column: str, stored: bytes) -> None:
        _corrupt_log_text(uri, run_id, seq, column, stored)

    return _Lane(SqlAlchemyCoralRunStore(uri), corrupt_sql)


def _owned(
    store: RunStore,
    viewer: Viewer,
    *,
    workspace_id: int = WORKSPACE,
    statuses: Sequence[RunStatus] = (),
    workflow_id: str | None = None,
    after: tuple[int, str] | None = None,
    limit: int = 25,
) -> tuple[list[str], tuple[int, str] | None]:
    runs, cursor = store.list_owned_runs(
        workspace_id=workspace_id,
        viewer=viewer,
        statuses=[int(status) for status in statuses],
        workflow_id=workflow_id,
        after=after,
        limit=limit,
    )
    return [run.id for run in runs], cursor


def _walk(
    store: RunStore,
    viewer: Viewer,
    *,
    limit: int,
    statuses: Sequence[RunStatus] = (),
    between_pages: Callable[[], None] = lambda: None,
) -> tuple[list[str], list[tuple[int, str]]]:
    """Every page's ids in order, and each cursor a page handed back."""
    seen: list[str] = []
    cursors: list[tuple[int, str]] = []
    after: tuple[int, str] | None = None
    while True:
        ids, after = _owned(store, viewer, statuses=statuses, after=after, limit=limit)
        assert len(ids) <= limit
        seen.extend(ids)
        if after is None:
            return seen, cursors
        cursors.append(after)
        between_pages()


def _newest_first(runs: Sequence[CoralRun]) -> list[str]:
    return [run.id for run in sorted(runs, key=lambda run: (run.created_at, run.id), reverse=True)]


def _set_status(store: RunStore, run: CoralRun, status: RunStatus) -> None:
    current = store.get_run(run.id, workspace_id=run.workspace_id)
    assert current is not None
    store.apply_transition(
        run.id, current.version, Transition(status=int(status)), workspace_id=run.workspace_id
    )


def test_list_owned_runs_lists_the_viewers_runs_in_the_workspace_newest_first(
    lane: _Lane,
) -> None:
    store = lane.store
    mine = [start_owned_run(store, f"mine-{i}", now=NOW + i) for i in range(3)]
    proven = start_owned_run(store, "proven", generation="g1", now=NOW + 3)
    bobs = start_owned_run(store, "bobs", user_id=BOB, now=NOW + 4)
    elsewhere = start_owned_run(store, "elsewhere", workspace_id=OTHER_WORKSPACE, now=NOW + 5)
    start_owned_run(store, "old-account", generation="g0", now=NOW + 6)
    unowned = start_owned_run(store, "unowned", user_id=None, now=NOW + 7)
    named_local = start_owned_run(store, "named-local", user_id=LOCAL_USER_ID, now=NOW + 8)
    # Owners compare exactly, even where the database collation folds them.
    for lookalike in ("ALICE", "alice ", "alicé", "LOCAL", "local "):
        start_owned_run(store, f"lookalike-{lookalike}", user_id=lookalike, now=NOW + 9)

    assert _owned(store, Viewer(ALICE)) == (_newest_first(mine), None)
    assert _owned(store, Viewer(ALICE, "g1", check_generation=True)) == (
        _newest_first([*mine, proven]),
        None,
    )
    # A generation the request did not prove, or another one, sees only unrecorded runs.
    for viewer in (Viewer(ALICE, "g1"), Viewer(ALICE, "g2", check_generation=True)):
        assert _owned(store, viewer) == (_newest_first(mine), None)
    for local in (Viewer(None), Viewer(LOCAL_USER_ID)):
        assert _owned(store, local) == (_newest_first([unowned, named_local]), None)
    assert _owned(store, Viewer(BOB)) == ([bobs.id], None)
    assert _owned(store, Viewer(ALICE), workspace_id=OTHER_WORKSPACE) == ([elsewhere.id], None)
    assert _owned(store, Viewer("carol")) == ([], None)


def test_list_owned_runs_filters_by_status_and_workflow(lane: _Lane) -> None:
    store = lane.store
    running = start_owned_run(store, "running", workflow_id="wf-a", now=NOW)
    paused = start_owned_run(store, "paused", workflow_id="wf-a", now=NOW + 1)
    completed = start_owned_run(store, "completed", workflow_id="wf-b", now=NOW + 2)
    starting = start_owned_run(store, "starting", workflow_id="wf-b", now=NOW + 3)
    bobs = start_owned_run(store, "bobs", user_id=BOB, workflow_id="wf-a", now=NOW + 4)
    for run, status in (
        (running, RunStatus.RUNNING),
        (paused, RunStatus.PAUSED),
        (completed, RunStatus.COMPLETED),
        (bobs, RunStatus.RUNNING),
    ):
        _set_status(store, run, status)
    alice = Viewer(ALICE)

    assert _owned(store, alice, statuses=(RunStatus.RUNNING,)) == ([running.id], None)
    assert _owned(store, alice, statuses=(RunStatus.RUNNING, RunStatus.PAUSED)) == (
        [paused.id, running.id],
        None,
    )
    assert _owned(store, alice, statuses=(RunStatus.FAILED,)) == ([], None)
    assert _owned(store, alice, workflow_id="wf-a") == ([paused.id, running.id], None)
    assert _owned(
        store,
        alice,
        workflow_id="wf-b",
        statuses=(RunStatus.COMPLETED, RunStatus.STARTING),
    ) == ([starting.id, completed.id], None)
    assert _owned(store, alice, workflow_id="wf-c") == ([], None)


@pytest.mark.parametrize(
    ("viewer", "owners"),
    [
        (Viewer(ALICE), (ALICE,)),
        # The local user's runs are stored under two owners, read as two ranges and merged.
        (Viewer(None), (None, LOCAL_USER_ID)),
    ],
    ids=["named", "local"],
)
def test_list_owned_runs_pages_tied_runs_without_gaps_or_repeats(
    lane: _Lane, viewer: Viewer, owners: tuple[str | None, ...]
) -> None:
    store = lane.store
    # Three start times, so ids break most ties; the stored owner alternates, and other
    # owners' rows share every time.
    mine = [
        start_owned_run(store, f"tie-{i}", user_id=owners[i % len(owners)], now=NOW + i % 3)
        for i in range(17)
    ]
    bobs = [start_owned_run(store, f"bobs-{i}", user_id=BOB, now=NOW + i % 3) for i in range(6)]
    for i in range(6):
        start_owned_run(
            store,
            f"old-account-{i}",
            user_id=owners[i % len(owners)],
            generation="g0",
            now=NOW + i % 3,
        )
    expected = _newest_first(mine)

    for limit in (1, 2, 5, 16, 17, 18, MAX_OWNED_RUNS_LIMIT):
        assert _walk(store, viewer, limit=limit)[0] == expected, limit
    # A cursor is only a position: another owner's row, or no row at all, pages from there.
    for after in ((bobs[1].created_at, bobs[1].id), (NOW + 1, "f" * 32), (NOW + 1, "")):
        older = [run for run in mine if (run.created_at, run.id) < after]
        assert _owned(store, viewer, after=after, limit=MAX_OWNED_RUNS_LIMIT) == (
            _newest_first(older),
            None,
        )
    for run in mine[::2]:
        _set_status(store, run, RunStatus.RUNNING)
    running = _newest_first(mine[::2])
    assert _walk(store, viewer, limit=3, statuses=(RunStatus.RUNNING,))[0] == running

    # Runs start between pages: a newer one sorts before the cursor, an older one after it.
    added: list[CoralRun] = []

    def start_two() -> None:
        if not added:
            added.append(start_owned_run(store, "newer", user_id=owners[-1], now=NOW + 100))
            added.append(start_owned_run(store, "older", user_id=owners[0], now=NOW - 100))

    seen, _ = _walk(store, viewer, limit=4, between_pages=start_two)
    assert seen == [*expected, added[1].id]
    assert _owned(store, viewer, limit=1)[0] == [added[0].id]


@pytest.mark.parametrize(
    ("viewer", "owners"),
    [
        (Viewer(ALICE, "g1", check_generation=True), (ALICE,)),
        # The local user's runs are stored under two owners, read as two ranges and merged.
        (Viewer(None, "g1", check_generation=True), (None, LOCAL_USER_ID)),
    ],
    ids=["named", "local"],
)
def test_rows_the_exact_owner_check_drops_are_read_past_and_never_become_the_cursor(
    lane: _Lane,
    monkeypatch: pytest.MonkeyPatch,
    viewer: Viewer,
    owners: tuple[str | None, ...],
) -> None:
    store = lane.store
    kept: list[CoralRun] = []
    # Oldest first: dropped rows at both ends, between kept rows and in a long stretch. The
    # stored owner switches every four rows, and neighbouring rows share a start time.
    for index, kind in enumerate("DDKDKDDDDDKKDKDD"):
        owner, now = owners[index // 4 % len(owners)], NOW + (index + 1) // 2
        if kind == "K":
            kept.append(start_owned_run(store, f"kept-{index}", user_id=owner, now=now))
        else:
            start_owned_run(store, f"dropped-{index}", user_id=owner, generation="g1", now=now)
    # A folding collation returns look-alike rows that the exact check then drops; rows
    # recorded under g1 stand in for them here.
    module: Any = sys.modules[type(store).__module__]
    real_is_owner = module.is_owner
    monkeypatch.setattr(
        module,
        "is_owner",
        lambda owner, generation, who: (
            generation != "g1" and real_is_owner(owner, generation, who)
        ),
    )
    kept_keys = {(run.created_at, run.id) for run in kept}

    for limit in (1, 2, 3, len(kept) + 1):
        seen, cursors = _walk(store, viewer, limit=limit)
        assert seen == _newest_first(kept), limit
        assert set(cursors) <= kept_keys, limit
    # Only dropped rows follow the last kept one, so a full page has no cursor.
    assert _walk(store, viewer, limit=len(kept)) == (_newest_first(kept), [])


@pytest.mark.parametrize("limit", [0, MAX_OWNED_RUNS_LIMIT + 1])
def test_list_owned_runs_takes_one_to_fifty_runs_a_page(lane: _Lane, limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        _owned(lane.store, Viewer(ALICE), limit=limit)


@pytest.mark.parametrize(
    "after",
    [
        (2**63, "a" * 32),
        (-1, "a" * 32),
        (True, "a" * 32),
        (NOW, "a" * 33),
        (NOW, "A" * 32),
        (NOW, "g" * 32),
        (NOW, "a\x00"),
    ],
    ids=["time-past-64-bits", "negative-time", "bool-time", "long-id", "upper", "not-hex", "nul"],
)
def test_a_cursor_no_stored_run_key_can_hold_is_refused_before_any_read(
    lane: _Lane, after: Any
) -> None:
    start_owned_run(lane.store, "mine")

    with pytest.raises(InvalidRunCursor):
        _owned(lane.store, Viewer(ALICE), after=after)
    # The widest cursor a stored key can hold still pages normally.
    assert _owned(lane.store, Viewer(ALICE), after=(2**63 - 1, "f" * 32))[1] is None


def test_list_owned_runs_reads_an_index_range_in_order_without_sorting(coral_db_uri: str) -> None:
    engine = coral_engine(coral_db_uri)
    store = SqlAlchemyCoralRunStore(engine)
    run = start_owned_run(store, "plan", workflow_id="wf-a")
    start_owned_run(store, "local", user_id=None)
    queries: list[tuple[str, Any]] = []

    def capture(*args: Any) -> None:
        statement, parameters = args[2], args[3]
        if statement.lstrip().upper().startswith("SELECT") and "coral_runs" in statement:
            queries.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        _owned(store, Viewer(ALICE))
        _owned(
            store,
            Viewer(ALICE, "g1", check_generation=True),
            statuses=(RunStatus.STARTING, RunStatus.RUNNING),
            after=(run.created_at + 1, run.id),
        )
        _owned(store, Viewer(ALICE), workflow_id="wf-a", after=(run.created_at + 1, run.id))
        _owned(store, Viewer(None))
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert queries
    assert all("LIMIT" in statement for statement, _ in queries)
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as connection:
        for statement, parameters in queries:
            plan = str(
                connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).all()
            )
            assert "ix_coral_runs_owner" in plan or "ix_coral_runs_workflow" in plan, plan
            assert "TEMP B-TREE" not in plan, plan


def _run_on_host(
    store: RunStore,
    key: str,
    host_id: str | None,
    status: RunStatus,
    *,
    workspace_id: int = WORKSPACE,
) -> CoralRun:
    spec = RunStartSpec(
        "wf", "v1", f"Run {key}", "p", workspace_id=workspace_id, user_id=ALICE, host_id=host_id
    )
    run = store.start_run(spec, start_key=key, now=NOW)
    if status != RunStatus.STARTING:
        _set_status(store, run, status)
    return run


def test_only_a_workspaces_starting_running_or_paused_runs_name_their_hosts(
    lane: _Lane,
) -> None:
    store = lane.store
    for status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        _run_on_host(store, f"finished-{status.name}", "host-1", status)
    _run_on_host(store, "no-host", None, RunStatus.RUNNING)
    _run_on_host(store, "elsewhere", "host-1", RunStatus.RUNNING, workspace_id=OTHER_WORKSPACE)
    for status in (RunStatus.STARTING, RunStatus.RUNNING, RunStatus.PAUSED):
        _run_on_host(store, f"unfinished-{status.name}", f"host-{status.name}", status)
    # Two live runs on one host name it once.
    _run_on_host(store, "running-again", "host-RUNNING", RunStatus.RUNNING)

    assert store.unfinished_run_hosts(workspace_id=WORKSPACE) == {
        "host-STARTING",
        "host-RUNNING",
        "host-PAUSED",
    }
    assert store.unfinished_run_hosts(workspace_id=OTHER_WORKSPACE) == {"host-1"}
    assert store.unfinished_run_hosts(workspace_id=999) == frozenset()


def _commit_logs(store: RunStore, run: CoralRun, count: int) -> list[RunLogEntry]:
    store.apply_transition(
        run.id,
        run.version,
        Transition(
            logs=tuple(
                LogEntryDraft(
                    kind=int(LogKind.ENGINE),
                    actor_kind=1,
                    body=f'{{"n": {n}}}',
                    node_id=f"node-{n}",
                    view_patch=f'[{{"op": "replace", "path": "/status", "value": "s{n}"}}]',
                )
                for n in range(1, count + 1)
            )
        ),
        workspace_id=run.workspace_id,
        now=NOW,
    )
    return store.read_log(run.id, workspace_id=run.workspace_id)


def test_a_tolerant_log_read_shows_rows_whose_text_does_not_decode_as_placeholders(
    lane: _Lane,
) -> None:
    store = lane.store
    run = start_owned_run(store, "log")
    original = _commit_logs(store, run, 5)
    lane.corrupt(run.id, 2, "body", _ZSTD_GARBAGE)
    lane.corrupt(run.id, 4, "view_patch", _NOT_UTF8)

    with pytest.raises(STORED_TEXT_ERRORS):
        store.read_log(run.id, workspace_id=WORKSPACE)
    tolerant = store.read_log(run.id, workspace_id=WORKSPACE, tolerant=True)

    unreadable = {
        seq: dataclasses.replace(original[seq - 1], body="", view_patch=None, unreadable=True)
        for seq in (2, 4)
    }
    assert tolerant == [unreadable.get(entry.seq, entry) for entry in original]
    assert not any(entry.unreadable for entry in original)
    # A page bounded by after_seq and limit isolates the same rows; a clean page reads as usual.
    page = store.read_log(run.id, workspace_id=WORKSPACE, after_seq=1, limit=2, tolerant=True)
    assert page == tolerant[1:3]
    clean = store.read_log(run.id, workspace_id=WORKSPACE, after_seq=4, tolerant=True)
    assert clean == store.read_log(run.id, workspace_id=WORKSPACE, after_seq=4) == original[4:]
    # The engine rows a load folds still raise.
    with pytest.raises(STORED_TEXT_ERRORS):
        store.read_engine_log(run.id, workspace_id=WORKSPACE, max_run_version=run.version + 1)


@pytest.mark.parametrize(
    ("column", "stored"),
    [("body", b"\x00"), ("view_patch", b"\x00"), ("body", b"\x00\x01")],
    ids=["body-nul", "view-patch-nul", "body-codec-only"],
)
def test_a_tolerant_log_read_shows_a_too_short_stored_value_as_a_placeholder(
    lane: _Lane, column: str, stored: bytes
) -> None:
    store = lane.store
    run = start_owned_run(store, "short")
    original = _commit_logs(store, run, 3)
    lane.corrupt(run.id, 2, column, stored)

    with pytest.raises(STORED_TEXT_ERRORS):
        store.read_log(run.id, workspace_id=WORKSPACE)
    assert store.read_log(run.id, workspace_id=WORKSPACE, tolerant=True) == [
        original[0],
        dataclasses.replace(original[1], body="", view_patch=None, unreadable=True),
        original[2],
    ]


def test_owned_run_lists_and_tolerant_log_reads_run_under_their_query_names(
    coral_db_uri: str,
) -> None:
    engine = coral_engine(coral_db_uri)
    store = SqlAlchemyCoralRunStore(engine)
    run = start_owned_run(store, "names")
    _commit_logs(store, run, 2)
    _corrupt_log_text(coral_db_uri, run.id, 1, "body", _ZSTD_GARBAGE)
    names: list[str | None] = []

    def capture(*args: Any) -> None:
        if "coral_runs" in args[2] or "coral_run_log" in args[2]:
            names.append(current_query_name())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        _owned(store, Viewer(ALICE))
        store.read_log(run.id, workspace_id=WORKSPACE, tolerant=True)
        store.unfinished_run_hosts(workspace_id=WORKSPACE)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert list(dict.fromkeys(names)) == [
        "coral.run_store.list_owned_runs",
        "coral.run_store.read_log",
        "coral.run_store.read_log_isolate_unreadable",
        "coral.run_store.unfinished_run_hosts",
    ]
