"""coral_0002 on every DB lane: upgrading a populated coral_0001 database, refusing downgrade."""

from __future__ import annotations

from io import StringIO

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from coral.db import RunRow
from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.db.migrate import _build_coral_alembic_config
from tests.db.coral._migration_support import coral_revision, insert_run, migrate_coral

_CORE = "coral_0001_core"
_SESSION_FACADE = "coral_0002_session_facade"
_SESSION_TABLES = {"coral_session_bindings", "coral_stable_ids", "coral_workspace_op_intents"}
_RUNS = RunRow.__table__
_PAUSED = int(RunStatus.PAUSED)
_DRIFT = int(RunPauseReason.DRIFT)
# MySQL reports CHECK violations as OperationalError (3819).
_CHECK_VIOLATION = (IntegrityError, OperationalError)


@pytest.fixture
def coral_core_engine(coral_scratch_engine: Engine) -> Engine:
    """A scratch database on the active lane with the Coral chain at coral_0001_core."""
    migrate_coral(coral_scratch_engine, "upgrade", _CORE)
    return coral_scratch_engine


def _pause_reasons(engine: Engine) -> dict[str, int | None]:
    with engine.connect() as conn:
        return {row.id: row.pause_reason for row in conn.execute(sa.select(_RUNS))}


def test_upgrade_keeps_existing_runs_and_downgrade_refuses_drift_pauses(
    coral_core_engine: Engine,
) -> None:
    engine = coral_core_engine
    engine_upgrade = int(RunPauseReason.ENGINE_UPGRADE)
    insert_run(engine, "paused", status=_PAUSED, pause_reason=engine_upgrade)
    insert_run(engine, "running", status=int(RunStatus.RUNNING), pause_reason=None)
    with pytest.raises(_CHECK_VIOLATION):
        insert_run(engine, "drift-too-early", status=_PAUSED, pause_reason=_DRIFT)

    # The check is replaced on a table committed before the upgrade, as in a deployment.
    migrate_coral(engine, "upgrade", _SESSION_FACADE)

    assert _pause_reasons(engine) == {"paused": engine_upgrade, "running": None}
    assert set(sa.inspect(engine).get_table_names()) >= _SESSION_TABLES
    insert_run(engine, "drift", status=_PAUSED, pause_reason=_DRIFT)
    with pytest.raises(_CHECK_VIOLATION):
        insert_run(engine, "unknown-reason", status=_PAUSED, pause_reason=_DRIFT + 1)
    with pytest.raises(_CHECK_VIOLATION):
        insert_run(engine, "unknown-status", status=99, pause_reason=None)

    with pytest.raises(RuntimeError, match="paused for drift"):
        migrate_coral(engine, "downgrade", _CORE)
    assert coral_revision(engine) == _SESSION_FACADE
    assert set(sa.inspect(engine).get_table_names()) >= _SESSION_TABLES

    # Once the drift pause is reconciled, the downgrade restores the narrow check.
    user = int(RunPauseReason.USER)
    with engine.begin() as conn:
        conn.execute(_RUNS.update().where(_RUNS.c.id == "drift").values(pause_reason=user))
    migrate_coral(engine, "downgrade", _CORE)

    assert coral_revision(engine) == _CORE
    assert _SESSION_TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    assert _pause_reasons(engine) == {"paused": engine_upgrade, "running": None, "drift": user}
    with pytest.raises(_CHECK_VIOLATION):
        insert_run(engine, "drift-after-downgrade", status=_PAUSED, pause_reason=_DRIFT)


def test_session_facade_downgrade_requires_a_live_connection() -> None:
    config = _build_coral_alembic_config("postgresql://")
    config.output_buffer = StringIO()

    with pytest.raises(RuntimeError, match="requires a live connection"):
        command.downgrade(config, f"{_SESSION_FACADE}:{_CORE}", sql=True)
    assert "ALTER TABLE" not in config.output_buffer.getvalue()
    assert "DROP TABLE" not in config.output_buffer.getvalue()
