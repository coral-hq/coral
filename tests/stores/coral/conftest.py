"""Coral DB-lane fixtures: every test here starts from Omnigent's schema plus the Coral tables."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from omnigent.db.utils import get_or_create_engine
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
