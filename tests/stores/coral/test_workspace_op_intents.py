"""Workspace op intent store on every DB lane: the first try's expected HEAD is kept."""

from __future__ import annotations

from typing import Literal

import pytest

from coral.db.enum_codecs import WorkspaceOpIntentOp
from coral.stores import workspace_op_intents
from coral.stores.workspace_op_intents import (
    OpIntentConflict,
    SqlAlchemyWorkspaceOpIntentStore,
    WorkspaceOpIntent,
    WorkspaceOpIntents,
)
from tests.stores.coral._faults import SimulatedCrash, crash_around, fresh_process, run_racing

WORKSPACE = 7
RUN = "a" * 32
OP_KEY = "k" * 32
HOST = "e" * 32
ROOT = "/Users/dev/repo-worktrees/coral-r-0a1b2c3d4e5f-base"
FIRST_HEAD = "1" * 40


def _clock() -> float:
    return 1_700_000_000.0


def _reserve(
    store: SqlAlchemyWorkspaceOpIntentStore,
    *,
    op_key: str = OP_KEY,
    run_id: str = RUN,
    op: WorkspaceOpIntentOp | str = WorkspaceOpIntentOp.COMMIT,
    host_id: str = HOST,
    root: str = ROOT,
    expected_head: str | None = FIRST_HEAD,
) -> WorkspaceOpIntent:
    return store.reserve(
        WORKSPACE,
        op_key=op_key,
        run_id=run_id,
        op=op,
        host_id=host_id,
        root=root,
        expected_head=expected_head,
    )


def test_reserve_keeps_the_first_expected_head_across_retries(coral_db_uri: str) -> None:
    store = SqlAlchemyWorkspaceOpIntentStore(coral_db_uri, clock=_clock)
    assert isinstance(store, WorkspaceOpIntents)

    first = _reserve(store)
    assert first == WorkspaceOpIntent(
        workspace_id=WORKSPACE,
        op_key=OP_KEY,
        run_id=RUN,
        op=WorkspaceOpIntentOp.COMMIT,
        host_id=HOST,
        root=ROOT,
        expected_head=FIRST_HEAD,
        created_at=1_700_000_000,
    )
    # A retry after the commit moved HEAD still reads the HEAD recorded before the first try.
    assert _reserve(store, expected_head="2" * 40) == first

    reopened = SqlAlchemyWorkspaceOpIntentStore(fresh_process(coral_db_uri), clock=_clock)
    assert reopened.get(WORKSPACE, OP_KEY, run_id=RUN) == first
    assert reopened.get(WORKSPACE, "m" * 32, run_id=RUN) is None
    assert reopened.get(WORKSPACE + 1, OP_KEY, run_id=RUN) is None
    # Another run never reads this run's intent or its HEAD.
    assert reopened.get(WORKSPACE, OP_KEY, run_id="b" * 32) is None


def test_reserve_conflicts_on_another_op_host_root_or_run(coral_db_uri: str) -> None:
    store = SqlAlchemyWorkspaceOpIntentStore(coral_db_uri, clock=_clock)
    stored = _reserve(store)

    for reserve_differently, field in (
        (lambda: _reserve(store, op="reset"), "op"),
        (lambda: _reserve(store, host_id="f" * 32), "host_id"),
        (lambda: _reserve(store, root="/Users/dev/other-worktree"), "root"),
        (lambda: _reserve(store, run_id="b" * 32), "run_id"),
    ):
        with pytest.raises(OpIntentConflict) as raised:
            reserve_differently()
        assert raised.value.fields == (field,)
        assert raised.value.stored == stored
        assert RUN not in str(raised.value)


def test_intent_without_an_expected_head_is_stored(coral_db_uri: str) -> None:
    store = SqlAlchemyWorkspaceOpIntentStore(coral_db_uri, clock=_clock)

    salvage = _reserve(store, expected_head=None, op_key="s" * 32, op="salvage")

    assert salvage.expected_head is None
    assert salvage.op is WorkspaceOpIntentOp.SALVAGE
    assert store.get(WORKSPACE, "s" * 32, run_id=RUN) == salvage


def test_concurrent_reservations_agree_on_one_expected_head(coral_db_uri: str) -> None:
    store = SqlAlchemyWorkspaceOpIntentStore(coral_db_uri, clock=_clock)

    outcomes = run_racing(4, lambda index: _reserve(store, expected_head=str(index) * 40))

    assert [outcome.error for outcome in outcomes] == [None] * 4
    stored = store.get(WORKSPACE, OP_KEY, run_id=RUN)
    assert stored is not None
    assert {outcome.value for outcome in outcomes} == {stored}


def test_concurrent_reservations_from_other_runs_conflict(coral_db_uri: str) -> None:
    store = SqlAlchemyWorkspaceOpIntentStore(coral_db_uri, clock=_clock)

    outcomes = run_racing(4, lambda index: _reserve(store, run_id=str(index) * 32))

    winners = [outcome.value for outcome in outcomes if outcome.error is None]
    losers = [outcome.error for outcome in outcomes if outcome.error is not None]
    assert len(winners) == 1
    assert all(isinstance(error, OpIntentConflict) for error in losers), losers
    assert store.get(WORKSPACE, OP_KEY, run_id=winners[0].run_id) == winners[0]


@pytest.mark.parametrize(("when", "kept_head"), [("before", "2" * 40), ("after", FIRST_HEAD)])
def test_retry_after_a_crash_around_the_insert_reads_the_recorded_head(
    coral_db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
    when: Literal["before", "after"],
    kept_head: str,
) -> None:
    store = SqlAlchemyWorkspaceOpIntentStore(coral_db_uri, clock=_clock)
    crash_around(monkeypatch, workspace_op_intents, "run_write_transaction", when=when)
    with pytest.raises(SimulatedCrash):
        _reserve(store)
    monkeypatch.undo()

    # The retry reads HEAD after it moved; only an intent the crashed try stored keeps the old one.
    reopened = SqlAlchemyWorkspaceOpIntentStore(fresh_process(coral_db_uri), clock=_clock)
    assert _reserve(reopened, expected_head="2" * 40).expected_head == kept_head
