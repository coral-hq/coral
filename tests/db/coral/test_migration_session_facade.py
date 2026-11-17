"""coral_0002 on every DB lane: upgrading a populated coral_0001 database, refusing downgrade."""

from __future__ import annotations

import os
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from coral.db import RunRow
from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.db.migrate import _build_coral_alembic_config, _crdb_version_tuple, _prepare_crdb_ddl
from omnigent.db.utils import create_db_engine, is_cockroachdb

_CORE = "coral_0001_core"
_SESSION_FACADE = "coral_0002_session_facade"
_SESSION_TABLES = {"coral_session_bindings", "coral_stable_ids", "coral_workspace_op_intents"}
_RUNS = RunRow.__table__
_PAUSED = int(RunStatus.PAUSED)
_DRIFT = int(RunPauseReason.DRIFT)
# MySQL reports CHECK violations as OperationalError (3819).
_CHECK_VIOLATION = (IntegrityError, OperationalError)


def _migrate(engine: Engine, direction: Literal["upgrade", "downgrade"], revision: str) -> None:
    """Move the Coral chain on one connection, preparing CockroachDB like ensure_coral_schema."""
    config = _build_coral_alembic_config(engine.url.render_as_string(hide_password=False))
    crdb = is_cockroachdb(engine.dialect.name)
    crdb_version = _crdb_version_tuple(engine) if crdb else None
    with engine.connect() as conn:
        if crdb:
            _prepare_crdb_ddl(conn, crdb_version)
        config.attributes["connection"] = conn
        getattr(command, direction)(config, revision)
        if conn.in_transaction():
            conn.commit()


@pytest.fixture
def coral_core_engine(tmp_path: Path) -> Iterator[Engine]:
    """A scratch database on the active lane with the Coral chain at coral_0001_core."""
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
        _migrate(engine, "upgrade", _CORE)
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


def _insert_run(engine: Engine, run_id: str, *, status: int, pause_reason: int | None) -> None:
    with engine.begin() as conn:
        conn.execute(
            _RUNS.insert().values(
                workspace_id=1,
                id=run_id,
                workflow_id="wf",
                version_id="ver",
                status=status,
                pause_reason=pause_reason,
                version=1,
                next_log_seq=1,
                activation_count=0,
                title="run",
                engine_version=1,
                state_version=1,
                log_version=1,
                created_at=0,
                updated_at=0,
            )
        )


def _pause_reasons(engine: Engine) -> dict[str, int | None]:
    with engine.connect() as conn:
        return {row.id: row.pause_reason for row in conn.execute(sa.select(_RUNS))}


def _revision(engine: Engine) -> str:
    with engine.connect() as conn:
        return conn.execute(sa.text("SELECT version_num FROM coral_alembic_version")).scalar_one()


def test_upgrade_keeps_existing_runs_and_downgrade_refuses_drift_pauses(
    coral_core_engine: Engine,
) -> None:
    engine = coral_core_engine
    engine_upgrade = int(RunPauseReason.ENGINE_UPGRADE)
    _insert_run(engine, "paused", status=_PAUSED, pause_reason=engine_upgrade)
    _insert_run(engine, "running", status=int(RunStatus.RUNNING), pause_reason=None)
    with pytest.raises(_CHECK_VIOLATION):
        _insert_run(engine, "drift-too-early", status=_PAUSED, pause_reason=_DRIFT)

    # The check is replaced on a table committed before the upgrade, as in a deployment.
    _migrate(engine, "upgrade", _SESSION_FACADE)

    assert _pause_reasons(engine) == {"paused": engine_upgrade, "running": None}
    assert set(sa.inspect(engine).get_table_names()) >= _SESSION_TABLES
    _insert_run(engine, "drift", status=_PAUSED, pause_reason=_DRIFT)
    with pytest.raises(_CHECK_VIOLATION):
        _insert_run(engine, "unknown-reason", status=_PAUSED, pause_reason=_DRIFT + 1)
    with pytest.raises(_CHECK_VIOLATION):
        _insert_run(engine, "unknown-status", status=99, pause_reason=None)

    with pytest.raises(RuntimeError, match="paused for drift"):
        _migrate(engine, "downgrade", _CORE)
    assert _revision(engine) == _SESSION_FACADE
    assert set(sa.inspect(engine).get_table_names()) >= _SESSION_TABLES

    # Once the drift pause is reconciled, the downgrade restores the narrow check.
    user = int(RunPauseReason.USER)
    with engine.begin() as conn:
        conn.execute(_RUNS.update().where(_RUNS.c.id == "drift").values(pause_reason=user))
    _migrate(engine, "downgrade", _CORE)

    assert _revision(engine) == _CORE
    assert _SESSION_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    assert _pause_reasons(engine) == {"paused": engine_upgrade, "running": None, "drift": user}
    with pytest.raises(_CHECK_VIOLATION):
        _insert_run(engine, "drift-after-downgrade", status=_PAUSED, pause_reason=_DRIFT)


def test_session_facade_downgrade_requires_a_live_connection() -> None:
    config = _build_coral_alembic_config("postgresql://")
    config.output_buffer = StringIO()

    with pytest.raises(RuntimeError, match="requires a live connection"):
        command.downgrade(config, f"{_SESSION_FACADE}:{_CORE}", sql=True)
    assert "ALTER TABLE" not in config.output_buffer.getvalue()
    assert "DROP TABLE" not in config.output_buffer.getvalue()
