"""Split fixture contract: Coral tables and writes stay in the operational DB file."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from omnigent.db.utils import (
    get_or_create_conversation_engine,
    get_or_create_engine,
    make_named_managed_session_maker,
)
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests.stores.coral._faults import (
    SimulatedCrash,
    crash_around,
    fresh_process,
)
from tests.stores.coral._schema import ProbeRow
from tests.stores.coral.conftest import CoralSplitDb

_CORAL_TABLES = {"coral_workflows", "coraltest_probe"}


def _tables(database_path: Path) -> set[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in rows}


def _row_count(database_path: Path, table: str) -> int:
    with sqlite3.connect(database_path) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def _add_probe(session: Session, key: str) -> None:
    session.add(ProbeRow(key=key, note="coral state"))


def _write_probe(engine: Engine, key: str) -> None:
    sessions = make_named_managed_session_maker(engine, query_name_prefix="coral.test_probe")
    with sessions("write_probe") as session:
        _add_probe(session, key)


def test_coral_tables_live_only_in_operational_db(coral_split_db: CoralSplitDb) -> None:
    coral_split_db.conversation_store.create_conversation(kind="default", title="placed")

    operational_tables = _tables(coral_split_db.operational_path)
    conversation_tables = _tables(coral_split_db.conversation_path)

    assert operational_tables >= _CORAL_TABLES
    assert not {table for table in conversation_tables if table.startswith("coral")}
    assert {"conversations", "conversation_items"} <= conversation_tables
    assert _row_count(coral_split_db.conversation_path, "conversations") == 1
    assert _row_count(coral_split_db.operational_path, "conversations") == 0


def test_crash_after_conversation_write_keeps_conversation_and_no_probe_row(
    coral_split_db: CoralSplitDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation = coral_split_db.conversation_store.create_conversation(
        kind="default", title="survives"
    )
    crash_around(monkeypatch, sys.modules[__name__], "_add_probe", when="after")

    with pytest.raises(SimulatedCrash):
        _write_probe(get_or_create_engine(coral_split_db.operational_uri), "lost")

    operational_engine = fresh_process(coral_split_db.operational_uri)
    fresh_process(coral_split_db.conversation_uri, connect=get_or_create_conversation_engine)
    reopened = SqlAlchemyConversationStore(
        coral_split_db.operational_uri, coral_split_db.conversation_uri
    )
    restored = reopened.get_conversation(conversation.id)
    assert restored is not None
    assert restored.title == "survives"
    with operational_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ProbeRow)) == 0
