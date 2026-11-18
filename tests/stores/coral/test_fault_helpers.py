"""Coral DB-lane fixture and fault-primitive contracts, on every DB lane."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy import Engine, func, inspect, select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from coral.db.models_workflows import WorkflowRow
from omnigent.db.utils import (
    NamedManagedSessionMaker,
    get_or_create_engine,
    make_named_managed_session_maker,
)
from tests.stores.coral._faults import (
    SimulatedCrash,
    crash_around,
    crash_around_async,
    fresh_process,
    hold_sqlite_write_lock,
    run_racing,
    short_sqlite_busy,
)
from tests.stores.coral._schema import ProbeRow


def _probe_sessions(engine: Engine, *, immediate: bool = False) -> NamedManagedSessionMaker:
    return make_named_managed_session_maker(
        engine, query_name_prefix="coral.test_probe", immediate=immediate
    )


def _probe_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(ProbeRow))


def _add_second(session: Session, key: str) -> None:
    session.add(ProbeRow(key=key, note="second"))


def _write_pair(engine: Engine) -> None:
    with _probe_sessions(engine)("write_pair") as session:
        session.add(ProbeRow(key="a", note="first"))
        session.flush()
        _add_second(session, "b")


def test_coral_db_uri_has_coral_and_probe_tables_and_no_rows(coral_db_uri: str) -> None:
    engine = get_or_create_engine(coral_db_uri)

    tables = set(inspect(engine).get_table_names())

    assert {"agents", "coral_workflows", "coraltest_probe"} <= tables
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(WorkflowRow)) == 0
    assert _probe_count(engine) == 0


def test_two_writes_in_one_named_session_commit_both_rows(coral_db_uri: str) -> None:
    _write_pair(get_or_create_engine(coral_db_uri))

    assert _probe_count(fresh_process(coral_db_uri)) == 2


@pytest.mark.parametrize("when", ["before", "after"])
def test_crash_between_two_writes_in_one_named_session_leaves_no_rows(
    coral_db_uri: str, monkeypatch: pytest.MonkeyPatch, when: Literal["before", "after"]
) -> None:
    crash_around(monkeypatch, sys.modules[__name__], "_add_second", when=when)

    with pytest.raises(SimulatedCrash):
        _write_pair(get_or_create_engine(coral_db_uri))

    assert _probe_count(fresh_process(coral_db_uri)) == 0


class _Doubler:
    """A sync and a coroutine method that record each call and double its value."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def double(self, value: int) -> int:
        self.calls.append(value)
        return value * 2

    async def double_async(self, value: int) -> int:
        return self.double(value)


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("coroutine", [False, True], ids=["sync", "async"])
async def test_a_crash_with_matching_hits_only_the_calls_it_accepts(
    monkeypatch: pytest.MonkeyPatch, when: Literal["before", "after"], coroutine: bool
) -> None:
    doubler = _Doubler()
    if coroutine:
        crash_around_async(
            monkeypatch, doubler, "double_async", when=when, matching=lambda value: value == 2
        )
    else:
        crash_around(monkeypatch, doubler, "double", when=when, matching=lambda value: value == 2)

    async def call(value: int) -> int:
        return await doubler.double_async(value) if coroutine else doubler.double(value)

    assert await call(1) == 2
    with pytest.raises(SimulatedCrash):
        await call(2)
    assert doubler.calls == ([1] if when == "before" else [1, 2])


def test_racing_inserts_on_one_key_have_one_winner(coral_db_uri: str) -> None:
    engine = get_or_create_engine(coral_db_uri)

    def insert_same_key(index: int) -> int:
        with _probe_sessions(engine)("insert_same_key") as session:
            session.add(ProbeRow(key="same", note=f"writer {index}"))
        return index

    outcomes = run_racing(4, insert_same_key)

    winners = [outcome for outcome in outcomes if outcome.error is None]
    losers = [outcome.error for outcome in outcomes if outcome.error is not None]
    assert len(winners) == 1
    assert len(losers) == 3
    assert all(isinstance(error, DBAPIError) for error in losers), losers
    assert _probe_count(fresh_process(coral_db_uri)) == 1


@pytest.mark.skipif(
    bool(os.environ.get("OMNIGENT_TEST_DB_URI")),
    reason="SQLite write locks and busy_timeout exist only on the SQLite lane",
)
def test_held_write_lock_with_short_busy_timeout_raises_operational_error(
    coral_db_uri: str,
) -> None:
    engine = get_or_create_engine(coral_db_uri)
    database_path = Path(str(engine.url.database))

    with hold_sqlite_write_lock(database_path), short_sqlite_busy(engine, 200):
        started = time.monotonic()
        with pytest.raises(OperationalError, match="locked"):
            with _probe_sessions(engine, immediate=True)("insert_while_locked") as session:
                session.add(ProbeRow(key="blocked", note="never written"))
        elapsed = time.monotonic() - started

    assert elapsed < 5
    assert _probe_count(engine) == 0
