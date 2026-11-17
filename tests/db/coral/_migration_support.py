"""Move the Coral Alembic chain on a scratch database of the active DB lane."""

from __future__ import annotations

from typing import Literal

import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine

from coral.db import RunRow
from coral.db.migrate import _build_coral_alembic_config, _crdb_version_tuple, _prepare_crdb_ddl
from omnigent.db.utils import is_cockroachdb


def migrate_coral(
    engine: Engine, direction: Literal["upgrade", "downgrade"], revision: str
) -> None:
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


def coral_revision(engine: Engine) -> str:
    """Return the database's current Coral revision."""
    with engine.connect() as conn:
        return conn.execute(sa.text("SELECT version_num FROM coral_alembic_version")).scalar_one()


def run_values(run_id: str, *, status: int, pause_reason: int | None) -> dict[str, object]:
    """Column values of one run row in workspace 1."""
    return {
        "workspace_id": 1,
        "id": run_id,
        "workflow_id": "wf",
        "version_id": "ver",
        "status": status,
        "pause_reason": pause_reason,
        "version": 1,
        "next_log_seq": 1,
        "activation_count": 0,
        "title": "run",
        "engine_version": 1,
        "state_version": 1,
        "log_version": 1,
        "created_at": 0,
        "updated_at": 0,
    }


def insert_run(engine: Engine, run_id: str, *, status: int, pause_reason: int | None) -> None:
    """Insert one committed run row in workspace 1."""
    values = run_values(run_id, status=status, pause_reason=pause_reason)
    with engine.begin() as conn:
        conn.execute(RunRow.__table__.insert().values(**values))
