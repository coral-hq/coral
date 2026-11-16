"""Coral schema for DB-lane tests: production Coral tables plus a test-only probe table."""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

from filelock import FileLock
from sqlalchemy import Connection, Engine, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from coral.db.models_workflows import CoralBase
from omnigent.db.cockroachdb import _crdb_server_version, _prepare_crdb_schema_transaction
from omnigent.db.utils import _engine_cache, _engine_lock, get_or_create_engine, is_cockroachdb

# Same path as tests/db/conftest.py so every worker on the host shares one CRDB DDL lock.
CRDB_SCHEMA_LOCK = Path(tempfile.gettempdir()) / "omnigent-crdb-schema-ddl.lock"


class CoralTestBase(DeclarativeBase):
    """Test-only tables; never part of CoralBase."""


class ProbeRow(CoralTestBase):
    __tablename__ = "coraltest_probe"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    note: Mapped[str] = mapped_column(String(255))


_CORAL_METADATA = (CoralBase.metadata, CoralTestBase.metadata)


def _run_schema_ddl(engine: Engine, apply: Callable[[MetaData, Connection], None]) -> None:
    if is_cockroachdb(engine.dialect.name):
        version = _crdb_server_version(engine)
        with engine.connect() as connection:
            _prepare_crdb_schema_transaction(connection, version)
            for metadata in _CORAL_METADATA:
                apply(metadata, connection)
            connection.commit()
        return
    with engine.begin() as connection:
        for metadata in _CORAL_METADATA:
            apply(metadata, connection)


def create_coral_schema(engine: Engine) -> None:
    """Create the Coral and test-only tables that are missing."""
    _run_schema_ddl(
        engine, lambda metadata, connection: metadata.create_all(connection, checkfirst=True)
    )


def drop_coral_schema(engine: Engine) -> None:
    _run_schema_ddl(
        engine, lambda metadata, connection: metadata.drop_all(connection, checkfirst=True)
    )


@contextlib.contextmanager
def crdb_ddl_lock(engine: Engine) -> Iterator[None]:
    """Serialize schema DDL across workers on CockroachDB; no-op on other dialects."""
    if not is_cockroachdb(engine.dialect.name):
        yield
        return
    with FileLock(str(CRDB_SCHEMA_LOCK)):
        yield


def build_coral_sqlite_template(directory: Path) -> Path:
    """Write a read-only SQLite file with Omnigent migrations and the Coral schema applied."""
    source = directory / "source.db"
    template = directory / "empty.db"
    uri = f"sqlite:///{source}"
    engine = get_or_create_engine(uri)
    try:
        create_coral_schema(engine)
        # SQLite backup includes committed WAL contents without copying sidecars.
        with (
            contextlib.closing(sqlite3.connect(source)) as src,
            contextlib.closing(sqlite3.connect(template)) as dst,
        ):
            src.backup(dst)
    finally:
        with _engine_lock:
            _engine_cache.pop(uri, None)
        engine.dispose()
    template.chmod(0o444)
    return template
