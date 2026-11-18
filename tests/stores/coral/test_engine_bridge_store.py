"""Run store additions the engine bridge needs, on every DB lane and on the fakes."""

from __future__ import annotations

import dataclasses
import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from coral.bridge.mapping import edge_signal_key, regather_key, turn_signal_draft
from coral.db import WorkflowVersionRow
from coral.db.enum_codecs import ActorKind, LogKind, RunStatus, WorkKind, WorkStatus
from coral.queue import SqlAlchemyCoralQueueStore
from coral.signals.turn_facts import EdgeFacts
from coral.stores.fakes import FakeQueueStore, FakeRunStore
from coral.stores.protocols import (
    CommitOutcome,
    CoralRun,
    LogEntryDraft,
    QueueStore,
    RunStartSpec,
    RunStore,
    RunVersionConflict,
    StartKeyConflict,
    ToolReplyDraft,
    ToolReplyTooLarge,
    Transition,
    WorkItem,
    WorkItemDraft,
)
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.stores.work_rows import MIN_HOLD_DELAY_S
from coral.stores.workflow_versions import SqlAlchemyWorkflowVersionStore
from tests.coral.workflow_builders import compile_text, fixture_text
from tests.stores.coral._faults import fresh_process, run_racing

# A non-default workspace, passed explicitly to every call.
WORKSPACE = 7
NOW = 1_700_000_000
LATER = NOW + 300
WORKER = "worker-1"


@dataclass(frozen=True)
class Stores:
    runs: RunStore
    queue: QueueStore


@pytest.fixture(params=["sql", "fake"])
def stores(request: pytest.FixtureRequest) -> Stores:
    if request.param == "sql":
        uri = request.getfixturevalue("coral_db_uri")
        return Stores(SqlAlchemyCoralRunStore(uri), SqlAlchemyCoralQueueStore(uri))
    run_store = FakeRunStore()
    return Stores(run_store, FakeQueueStore(run_store=run_store))


def _start(
    stores: Stores,
    *,
    start_key: str = "run-1",
    engine_config: str | None = None,
    workspace_id: int = WORKSPACE,
) -> CoralRun:
    # The run id derives from the user and start key, so another workspace gets the same id.
    return stores.runs.start_run(
        RunStartSpec(
            workflow_id="f" * 32,
            version_id="e" * 32,
            title="Bridge run",
            request_preview="Build it",
            workspace_id=workspace_id,
            user_id="alice",
            engine_config=engine_config,
        ),
        start_key=start_key,
        now=NOW,
    )


def _log(body: str, *, kind: LogKind = LogKind.ENGINE, audit_only: bool = False) -> LogEntryDraft:
    return LogEntryDraft(
        kind=int(kind), actor_kind=int(ActorKind.ENGINE), body=body, audit_only=audit_only
    )


def _commit(
    stores: Stores, run: CoralRun, transition: Transition, *, now: int = NOW
) -> CommitOutcome:
    _, version = stores.runs.load_run_state(run.id, workspace_id=run.workspace_id)
    return stores.runs.apply_transition(
        run.id, version, transition, workspace_id=run.workspace_id, now=now
    )


def _bodies(stores: Stores, run: CoralRun, **read: int) -> list[str]:
    read.setdefault("max_run_version", 1_000)
    rows = stores.runs.read_engine_log(run.id, workspace_id=WORKSPACE, **read)
    return [row.body for row in rows]


def _effect(run: CoralRun, key: str) -> WorkItemDraft:
    return WorkItemDraft.effect(run_id=run.id, idempotency_key=key, payload={"effect_type": key})


def _claimed(stores: Stores, draft: WorkItemDraft, *, workspace_id: int = WORKSPACE) -> WorkItem:
    """Enqueue ``draft`` and claim it; nothing else may be ready at ``NOW``."""
    stores.queue.enqueue_work([draft], workspace_id=workspace_id, now=NOW)
    return _claim_at(stores, NOW, workspace_id=workspace_id)


def _claim_at(stores: Stores, at: int, *, workspace_id: int = WORKSPACE) -> WorkItem:
    item = stores.queue.claim_work(WORKER, workspace_id=workspace_id, now_fn=lambda: float(at))
    assert item is not None
    return item


def _finish(
    stores: Stores,
    item: WorkItem,
    status: WorkStatus,
    *,
    error_code: str | None = None,
    next_available_at: int | None = None,
    hold: bool = False,
    at: int = NOW,
) -> None:
    assert item.lease_expires_at is not None
    assert stores.queue.finish_work(
        item.id,
        worker_id=WORKER,
        expected_lease_expires_at=item.lease_expires_at,
        status=int(status),
        result={"detail": "kept"} if status is WorkStatus.FAILED else None,
        error_code=error_code,
        next_available_at=next_available_at,
        workspace_id=item.workspace_id,
        now_fn=lambda: float(at),
        hold=hold,
    )


def _failed(stores: Stores, run: CoralRun, key: str) -> WorkItem:
    item = _claimed(stores, _effect(run, key), workspace_id=run.workspace_id)
    _finish(stores, item, WorkStatus.FAILED, error_code="infra.transient")
    return item


def _held(stores: Stores, run: CoralRun, key: str, code: str) -> WorkItem:
    item = _claimed(stores, _effect(run, key), workspace_id=run.workspace_id)
    _finish(stores, item, WorkStatus.PENDING, error_code=code, next_available_at=LATER, hold=True)
    return item


def _read(stores: Stores, *items: WorkItem) -> dict[str, WorkItem]:
    found = stores.queue.get_work([item.id for item in items], workspace_id=WORKSPACE)
    return {item.id: item for item in found}


def test_read_engine_log_returns_the_runs_engine_rows_up_to_the_version_bound(
    stores: Stores,
) -> None:
    run = _start(stores)
    other = _start(stores, start_key="run-2")
    first = _commit(stores, run, Transition(logs=(_log("e1"), _log("p1", kind=LogKind.PAUSED))))
    _commit(stores, other, Transition(logs=(_log("other run"),)))
    second = _commit(
        stores, run, Transition(logs=(_log("refused", audit_only=True), _log("e2"), _log("e3")))
    )

    rows = stores.runs.read_engine_log(
        run.id, workspace_id=WORKSPACE, max_run_version=second.version
    )
    assert [(row.seq, row.run_version, row.body) for row in rows] == [
        (1, first.version, "e1"),
        (3, second.version, "refused"),
        (4, second.version, "e2"),
        (5, second.version, "e3"),
    ]
    assert {row.kind for row in rows} == {int(LogKind.ENGINE)}
    # Audit rows come back flagged; the reader decides to skip them.
    assert [row.audit_only for row in rows] == [False, True, False, False]
    # Never past the loaded version, whatever the paging.
    assert _bodies(stores, run, max_run_version=first.version) == ["e1"]
    assert _bodies(stores, run, max_run_version=run.version) == []
    assert _bodies(stores, run, after_seq=1, limit=2) == ["refused", "e2"]
    assert _bodies(stores, run, after_seq=4) == ["e3"]
    assert stores.runs.read_engine_log(run.id, workspace_id=WORKSPACE + 1, max_run_version=9) == []


def test_tool_reply_commits_with_its_transition_and_a_repeat_writes_nothing(
    stores: Stores,
) -> None:
    run = _start(stores)
    other = _start(stores, start_key="run-2")
    cksum = hashlib.sha256(b"tool call 1").digest()
    held = _held(stores, run, "held", "run.paused")
    failed = _failed(stores, run, "failed")
    before = _read(stores, held, failed)

    stored = _commit(
        stores,
        run,
        Transition(logs=(_log("decide"),), tool_reply=ToolReplyDraft(cksum, '{"ok": true}')),
    )

    assert stores.runs.find_tool_reply(run.id, cksum, workspace_id=WORKSPACE) == '{"ok": true}'
    assert stores.runs.find_tool_reply(run.id, b"\1" * 32, workspace_id=WORKSPACE) is None
    assert stores.runs.find_tool_reply(other.id, cksum, workspace_id=WORKSPACE) is None
    assert stores.runs.find_tool_reply(run.id, cksum, workspace_id=WORKSPACE + 1) is None

    # The same call committed again fails as a whole, queue changes included.
    new = _effect(run, "new")
    with pytest.raises(IntegrityError):
        _commit(
            stores,
            run,
            Transition(
                status=int(RunStatus.RUNNING),
                logs=(_log("decide again"),),
                outbox_work=(new,),
                revive_work_ids=(failed.id,),
                release_held_codes=("run.paused",),
                tool_reply=ToolReplyDraft(cksum, '{"ok": false}'),
            ),
            now=NOW + 10,
        )
    reread = stores.runs.get_run(run.id, workspace_id=WORKSPACE)
    assert reread is not None
    assert (reread.version, reread.status) == (stored.version, int(RunStatus.STARTING))
    assert _bodies(stores, run) == ["decide"]
    assert stores.runs.find_tool_reply(run.id, cksum, workspace_id=WORKSPACE) == '{"ok": true}'
    assert stores.queue.get_work([new.id], workspace_id=WORKSPACE) == []
    assert _read(stores, held, failed) == before


def test_tool_reply_checksum_is_scoped_to_its_run_and_workspace(stores: Stores) -> None:
    run = _start(stores)
    other = _start(stores, start_key="run-2")
    twin = _start(stores, workspace_id=WORKSPACE + 1)
    assert twin.id == run.id
    cksum = hashlib.sha256(b"tool call 1").digest()

    for owner, reply in ((run, "mine"), (other, "other run"), (twin, "other workspace")):
        _commit(stores, owner, Transition(tool_reply=ToolReplyDraft(cksum, reply)))

    assert [
        stores.runs.find_tool_reply(owner.id, cksum, workspace_id=owner.workspace_id)
        for owner in (run, other, twin)
    ] == ["mine", "other run", "other workspace"]
    with pytest.raises(IntegrityError):
        _commit(stores, run, Transition(tool_reply=ToolReplyDraft(cksum, "again")))
    # The refused repeat leaves the run committable at the same version.
    assert _commit(stores, run, Transition(logs=(_log("next"),))).version == run.version + 2
    assert _bodies(stores, run) == ["next"]


def test_racing_commits_at_one_version_apply_exactly_one(stores: Stores) -> None:
    run = _start(stores)
    cksum = hashlib.sha256(b"tool call 1").digest()

    def commit(index: int) -> CommitOutcome:
        return stores.runs.apply_transition(
            run.id,
            run.version,
            Transition(
                logs=(_log(f"writer {index} a"), _log(f"writer {index} b")),
                outbox_work=(_effect(run, f"writer {index}"),),
                tool_reply=ToolReplyDraft(cksum, f"writer {index}"),
            ),
            workspace_id=WORKSPACE,
            now=NOW,
        )

    outcomes = run_racing(2, commit)

    # The run-row lock orders them: the loser sees a moved version before its reply insert.
    [winner] = [index for index, outcome in enumerate(outcomes) if outcome.error is None]
    [loser] = [outcome.error for outcome in outcomes if outcome.error is not None]
    assert isinstance(loser, RunVersionConflict)
    rows = stores.runs.read_engine_log(run.id, workspace_id=WORKSPACE, max_run_version=99)
    assert [(row.seq, row.run_version, row.body) for row in rows] == [
        (1, run.version + 1, f"writer {winner} a"),
        (2, run.version + 1, f"writer {winner} b"),
    ]
    assert stores.runs.find_tool_reply(run.id, cksum, workspace_id=WORKSPACE) == f"writer {winner}"
    drafts = [_effect(run, f"writer {index}") for index in (0, 1)]
    stored = stores.queue.get_work([draft.id for draft in drafts], workspace_id=WORKSPACE)
    assert [item.id for item in stored] == [drafts[winner].id]


def test_resume_revives_and_releases_only_the_rows_their_rules_name(stores: Stores) -> None:
    run = _start(stores)
    other = _start(stores, start_key="run-2")
    _commit(stores, run, Transition(status=int(RunStatus.PAUSED)))
    revived = _failed(stores, run, "revived")
    left_failed = _failed(stores, run, "left failed")
    other_failed = _failed(stores, other, "other run failed")
    succeeded = _claimed(stores, _effect(run, "succeeded"))
    _finish(stores, succeeded, WorkStatus.SUCCEEDED)
    paused = _held(stores, run, "paused", "run.paused")
    drift = _held(stores, run, "drift", "drift.anchor_bound")
    not_ready = _held(stores, run, "not ready", "session.not_ready")
    other_paused = _held(stores, other, "other run paused", "run.paused")
    # A paused item claimed again is in flight: release leaves it to its worker.
    in_flight = _claimed(stores, _effect(run, "in flight"))
    _finish(stores, in_flight, WorkStatus.PENDING, error_code="run.paused", hold=True)
    assert _claim_at(stores, NOW + MIN_HOLD_DELAY_S).id == in_flight.id
    untouched = (left_failed, other_failed, succeeded, not_ready, other_paused, in_flight)
    before = _read(stores, revived, paused, drift, *untouched)

    resumed = _commit(
        stores,
        run,
        Transition(
            status=int(RunStatus.RUNNING),
            logs=(_log("resume"),),
            revive_work_ids=(revived.id, succeeded.id, other_failed.id, paused.id),
            release_held_codes=("run.paused", "drift.anchor_bound"),
        ),
        now=NOW + 10,
    )

    after = _read(stores, revived, paused, drift, *untouched)
    assert after[revived.id] == dataclasses.replace(
        before[revived.id],
        status=int(WorkStatus.PENDING),
        attempts=0,
        available_at=NOW + 10,
        error_code=None,
        result=None,
        finished_at=None,
    )
    assert before[paused.id].held_since == NOW
    for released in (paused, drift):
        assert after[released.id] == dataclasses.replace(
            before[released.id], available_at=NOW + 10, held_since=None
        )
    assert {item.id: after[item.id] for item in untouched} == {
        item.id: before[item.id] for item in untouched
    }
    reread = stores.runs.get_run(run.id, workspace_id=WORKSPACE)
    assert reread is not None
    assert (reread.version, reread.status) == (resumed.version, int(RunStatus.RUNNING))


def test_revive_and_release_touch_only_the_commits_workspace_and_revive_once(
    stores: Stores,
) -> None:
    run = _start(stores)
    twin = _start(stores, workspace_id=WORKSPACE + 1)
    failed = _failed(stores, run, "failed")
    held = _held(stores, run, "held", "run.paused")
    abandoned = _claimed(stores, _effect(run, "abandoned"))
    _finish(stores, abandoned, WorkStatus.ABANDONED, error_code="run.terminal")
    # The same work ids, failed and held, in the twin run of another workspace.
    _failed(stores, twin, "failed")
    _held(stores, twin, "held", "run.paused")
    twin_before = stores.queue.get_work([failed.id, held.id], workspace_id=WORKSPACE + 1)
    abandoned_before = _read(stores, abandoned)

    revive = Transition(revive_work_ids=(failed.id, abandoned.id))
    _commit(stores, run, dataclasses.replace(revive, release_held_codes=("run.paused",)))
    revived = _read(stores, failed)[failed.id]
    assert (revived.status, revived.available_at) == (int(WorkStatus.PENDING), NOW)
    assert _read(stores, held)[held.id].held_since is None
    assert _read(stores, abandoned) == abandoned_before
    assert stores.queue.get_work([failed.id, held.id], workspace_id=WORKSPACE + 1) == twin_before

    # A repeated revive finds the row pending and leaves it.
    _commit(stores, run, revive, now=LATER)
    assert _read(stores, failed)[failed.id] == revived


def test_hold_start_survives_reclaim_and_restarts_after_a_release(stores: Stores) -> None:
    run = _start(stores)
    item = _held(stores, run, "held", "run.paused")

    # A crash while claimed: the reclaim keeps the hold's start and the spent attempt.
    claimed = _claim_at(stores, LATER)
    assert (claimed.held_since, claimed.attempts) == (NOW, 1)
    assert (
        stores.queue.reclaim_expired_work(workspace_id=WORKSPACE, now_fn=lambda: float(LATER + 60))
        == 1
    )
    reclaimed = _read(stores, item)[item.id]
    assert (reclaimed.status, reclaimed.held_since) == (int(WorkStatus.PENDING), NOW)
    again = _claim_at(stores, LATER + 60)
    _finish(stores, again, WorkStatus.PENDING, error_code="run.paused", hold=True, at=LATER + 60)
    held = _read(stores, item)[item.id]
    assert (held.held_since, held.attempts) == (NOW, 1)

    # The resume releases it; a later hold measures its horizon from its own start.
    _commit(stores, run, Transition(release_held_codes=("run.paused",)), now=LATER + 100)
    assert _read(stores, item)[item.id].held_since is None
    rehold = _claim_at(stores, LATER + 100)
    _finish(stores, rehold, WorkStatus.PENDING, error_code="run.paused", hold=True, at=LATER + 120)
    assert _read(stores, item)[item.id].held_since == LATER + 120


def test_engine_config_is_stored_with_the_spec_and_part_of_its_digest(stores: Stores) -> None:
    frozen = '{"max_activations": 100, "rejected_call_limit": 3}'
    run = _start(stores, engine_config=frozen)

    state, _ = stores.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    assert state.spec.engine_config == frozen
    assert _start(stores, engine_config=frozen).id == run.id
    for changed in ('{"max_activations": 5, "rejected_call_limit": 3}', None):
        with pytest.raises(StartKeyConflict):
            _start(stores, engine_config=changed)


def test_tool_reply_needs_a_32_byte_checksum_and_a_reply_that_fits(stores: Stores) -> None:
    run = _start(stores)

    with pytest.raises(ValueError, match="32 bytes"):
        ToolReplyDraft(b"\0" * 31, "{}")
    with pytest.raises(ToolReplyTooLarge):
        ToolReplyDraft(b"\0" * 32, os.urandom(20_000).hex())
    with pytest.raises(ValueError, match="32 bytes"):
        stores.runs.find_tool_reply(run.id, b"\0" * 33, workspace_id=WORKSPACE)
    assert ToolReplyDraft(b"\0" * 32, "x" * 50_000).reply == "x" * 50_000


def test_engine_log_reads_need_a_positive_limit(stores: Stores) -> None:
    run = _start(stores)

    with pytest.raises(ValueError, match="limit"):
        stores.runs.read_engine_log(run.id, workspace_id=WORKSPACE, max_run_version=9, limit=0)


def test_transition_with_only_bridge_fields_is_not_empty() -> None:
    assert Transition().is_empty
    assert not Transition(tool_reply=ToolReplyDraft(b"\0" * 32, "{}")).is_empty
    assert not Transition(revive_work_ids=("work",)).is_empty
    assert not Transition(release_held_codes=("run.paused",)).is_empty


def test_lock_timeout_issues_set_local_timeouts_on_the_postgresql_family(
    coral_db_uri: str,
) -> None:
    engine = fresh_process(coral_db_uri)
    store = SqlAlchemyCoralRunStore(engine)
    stores = Stores(store, SqlAlchemyCoralQueueStore(engine))
    run = _start(stores)
    statements: list[str] = []

    def capture(_conn: object, _cursor: object, statement: str, *_args: object) -> None:
        statements.append(statement)

    def set_local_statements(commit: Callable[[], object]) -> list[str]:
        statements.clear()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            commit()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        return [statement for statement in statements if statement.startswith("SET LOCAL")]

    bounded = set_local_statements(
        lambda: store.apply_transition(
            run.id, 1, Transition(logs=(_log("e1"),)), workspace_id=WORKSPACE, lock_timeout_s=10
        )
    )
    unbounded = set_local_statements(
        lambda: store.apply_transition(
            run.id, 2, Transition(logs=(_log("e2"),)), workspace_id=WORKSPACE
        )
    )
    # Under a millisecond rounds up: 0 would turn both timeouts off.
    tiny = set_local_statements(
        lambda: store.apply_transition(
            run.id,
            3,
            Transition(logs=(_log("e3"),)),
            workspace_id=WORKSPACE,
            lock_timeout_s=0.0004,
        )
    )

    # MySQL keeps its lock wait timeout and SQLite its busy timeout.
    postgresql_family = engine.dialect.name in {"postgresql", "cockroachdb"}
    assert bounded == (
        ["SET LOCAL lock_timeout = 10000", "SET LOCAL statement_timeout = 15000"]
        if postgresql_family
        else []
    )
    assert tiny == (
        ["SET LOCAL lock_timeout = 1", "SET LOCAL statement_timeout = 1"]
        if postgresql_family
        else []
    )
    assert unbounded == []
    assert _bodies(stores, run) == ["e1", "e2", "e3"]
    with pytest.raises(ValueError, match="lock_timeout_s"):
        store.apply_transition(
            run.id, 4, Transition(logs=(_log("e4"),)), workspace_id=WORKSPACE, lock_timeout_s=0
        )


def test_pinned_version_round_trips_and_racing_pins_store_one_row(coral_db_uri: str) -> None:
    yaml_text = fixture_text("loop")
    graph, _ = compile_text(yaml_text)
    versions = SqlAlchemyWorkflowVersionStore(coral_db_uri, clock=lambda: float(NOW))

    def pin(_index: int = 0) -> object:
        return versions.pin(
            workspace_id=WORKSPACE,
            workflow_id="f" * 32,
            graph=graph,
            yaml_text=yaml_text,
            created_by="alice",
        )

    outcomes = run_racing(4, pin)

    assert [outcome.error for outcome in outcomes] == [None] * 4
    pinned = versions.pin(
        workspace_id=WORKSPACE,
        workflow_id="f" * 32,
        graph=graph,
        yaml_text=yaml_text,
        created_by=None,
    )
    assert [outcome.value for outcome in outcomes] == [pinned] * 4
    engine = fresh_process(coral_db_uri)
    reopened = SqlAlchemyWorkflowVersionStore(engine)
    assert reopened.load(workspace_id=WORKSPACE, version_id=pinned.id) == pinned
    with engine.connect() as connection:
        count = connection.execute(select(func.count()).select_from(WorkflowVersionRow))
        assert count.scalar_one() == 1


def test_a_turn_signal_is_written_once_per_edge_and_once_per_re_gather_bucket(
    stores: Stores,
) -> None:
    run = _start(stores)
    session_id = "s" * 32
    edge = EdgeFacts(status="failed", observed_at_ms=NOW * 1000, turn_outcome="failed")

    def signal(key: str, facts: EdgeFacts | None) -> WorkItemDraft:
        return turn_signal_draft(
            run_id=run.id,
            session_id=session_id,
            engine_slot_id="implement||:0",
            generation=1,
            idempotency_key=key,
            edge=facts,
            available_at=NOW,
        )

    first = signal(edge_signal_key(session_id, edge), edge)
    repeat = signal(edge_signal_key(session_id, edge), edge)
    later_edge = dataclasses.replace(edge, observed_at_ms=NOW * 1000 + 1)
    later = signal(edge_signal_key(session_id, later_edge), later_edge)
    bucket = signal(regather_key(session_id, NOW), None)
    same_bucket = signal(regather_key(session_id, NOW + 299 - NOW % 300), None)
    for draft in (first, repeat, later, bucket, same_bucket):
        stores.queue.enqueue_work([draft], workspace_id=WORKSPACE, now=NOW)

    ids = {first.id, repeat.id, later.id, bucket.id, same_bucket.id}
    rows = stores.queue.get_work(sorted(ids), workspace_id=WORKSPACE)
    assert (len(ids), len(rows)) == (3, 3)
    assert {row.kind for row in rows} == {int(WorkKind.SIGNAL)}
    assert all(row.slot_generation == 1 for row in rows)
