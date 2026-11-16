"""Coral DB-lane fixtures: every test here starts from Omnigent's schema plus the Coral tables."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import make_url

from omnigent.db.utils import get_or_create_engine
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests.stores.coral._faults import evict_cached_engine
from tests.stores.coral._schema import (
    build_coral_sqlite_template,
    crdb_ddl_lock,
    create_coral_schema,
    drop_coral_schema,
)


@pytest.fixture(scope="session")
def _sqlite_db_template(
    tmp_path_factory: pytest.TempPathFactory, _worker_db_uri: str
) -> Path | None:
    """Migrate once per worker; the root db_uri fixture copies this for each test."""
    if _worker_db_uri:
        return None
    return build_coral_sqlite_template(tmp_path_factory.mktemp("coral-db-template"))


@pytest.fixture(scope="module")
def _coral_schema_on_worker_db(_worker_db_uri: str) -> Iterator[None]:
    """Add the Coral tables to the shared external worker DB for this module only."""
    if not _worker_db_uri:
        yield
        return
    engine = get_or_create_engine(_worker_db_uri)
    with crdb_ddl_lock(engine):
        create_coral_schema(engine)
    yield
    with crdb_ddl_lock(engine):
        drop_coral_schema(engine)


@pytest.fixture
def coral_db_uri(db_uri: str, _coral_schema_on_worker_db: None) -> str:
    """:returns: An operational DB URI with Coral tables and no rows, on the active lane."""
    return db_uri


@dataclass(frozen=True)
class CoralSplitDb:
    operational_uri: str
    conversation_uri: str
    operational_path: Path
    conversation_path: Path
    conversation_store: SqlAlchemyConversationStore


@pytest.fixture
def coral_split_db(
    coral_db_uri: str, tmp_path: Path, _worker_db_uri: str
) -> Iterator[CoralSplitDb]:
    """:returns: The Coral operational DB plus a conversation DB in a separate SQLite file."""
    if _worker_db_uri:
        pytest.skip("split-DB lane is SQLite + SQLite")
    conversation_path = tmp_path / "conversations.db"
    conversation_uri = f"sqlite:///{conversation_path}"
    yield CoralSplitDb(
        operational_uri=coral_db_uri,
        conversation_uri=conversation_uri,
        operational_path=Path(str(make_url(coral_db_uri).database)),
        conversation_path=conversation_path,
        conversation_store=SqlAlchemyConversationStore(coral_db_uri, conversation_uri),
    )
    # db_uri evicts only the operational engine.
    evict_cached_engine(conversation_uri)
