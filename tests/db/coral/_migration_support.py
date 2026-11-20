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


def insert_row(engine: Engine, table: sa.Table, values: dict[str, object]) -> None:
    """Insert one committed row."""
    with engine.begin() as conn:
        conn.execute(table.insert().values(**values))


def insert_run(engine: Engine, run_id: str, *, status: int, pause_reason: int | None) -> None:
    """Insert one committed run row in workspace 1."""
    insert_row(
        engine, RunRow.__table__, run_values(run_id, status=status, pause_reason=pause_reason)
    )


def _checks(inspector: sa.Inspector, table: str) -> list[tuple[str | None, str]]:
    try:
        return sorted(
            (check["name"], check["sqltext"]) for check in inspector.get_check_constraints(table)
        )
    except NotImplementedError:
        return []


def reflected_schema(engine: Engine) -> dict[str, dict[str, object]]:
    """Columns, keys, indexes and checks of every Coral data table, as the lane reflects them."""
    inspector = sa.inspect(engine)
    tables = sorted(
        name
        for name in inspector.get_table_names()
        if name.startswith("coral_") and name != "coral_alembic_version"
    )
    return {
        table: {
            "columns": {
                column["name"]: (repr(column["type"]), column["nullable"])
                for column in inspector.get_columns(table)
            },
            "primary_key": inspector.get_pk_constraint(table)["constrained_columns"],
            "indexes": sorted(
                (index["name"], tuple(index["column_names"]), bool(index["unique"]))
                for index in inspector.get_indexes(table)
            ),
            "unique": sorted(
                (unique["name"], tuple(unique["column_names"]))
                for unique in inspector.get_unique_constraints(table)
            ),
            "checks": _checks(inspector, table),
        }
        for table in tables
    }
