"""Scratch databases for Coral migration tests on the active DB lane."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from omnigent.db.utils import create_db_engine


@pytest.fixture
def coral_scratch_engine(tmp_path: Path) -> Iterator[Engine]:
    """An empty database on the active lane with no Coral revision applied."""
    root_uri = os.environ.get("OMNIGENT_TEST_DB_URI")
    admin = sa.create_engine(root_uri, isolation_level="AUTOCOMMIT") if root_uri else None
    uri = f"sqlite:///{tmp_path / 'coral.db'}"
    name = f"coral_migration_{uuid4().hex}"
    quoted = name
    engine = None
    database_created = False
    try:
        if admin is not None:
            quoted = admin.dialect.identifier_preparer.quote(name)
            with admin.connect() as conn:
                conn.execute(sa.text(f"CREATE DATABASE {quoted}"))
            database_created = True
            uri = admin.url.set(database=name).render_as_string(hide_password=False)
        engine = create_db_engine(uri)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if admin is not None:
            try:
                if database_created:
                    cascade = " CASCADE" if admin.dialect.name == "cockroachdb" else ""
                    with admin.connect() as conn:
                        conn.execute(sa.text(f"DROP DATABASE {quoted}{cascade}"))
            finally:
                admin.dispose()
