"""Workflow alerts, and gate visit tokens wide enough for every engine token.

Revision ID: coral_0004_alerts_and_gates
Revises: coral_0003_engine_bridge

Downgrade refuses while any alert exists or any gate token is longer than 64 characters.
Stop Coral servers before downgrading. On CockroachDB the downgrade leaves the token column
at 512 characters: narrowing a STRING must validate every row, which CockroachDB does only
outside a transaction and behind an experimental setting.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import sqlalchemy as sa
from alembic import context, op

from coral.db.types import CAPPED_TEXT, CaseSensitiveString
from omnigent.db.utils import is_cockroachdb

revision: str = "coral_0004_alerts_and_gates"
down_revision: str | None = "coral_0003_engine_bridge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALERTS = "coral_alerts"
_INBOX_INDEX = "ix_coral_alerts_inbox"
_SUBJECT_INDEX = "ix_coral_alerts_subject"
_GATE_VISITS = "coral_gate_visits"
_OLD_TOKEN_CHARS = 64
_OLD_TOKEN = sa.String(_OLD_TOKEN_CHARS)
_NEW_TOKEN = CaseSensitiveString(512)


def _recreate() -> Literal["always", "auto"]:
    # SQLite cannot change a column type in place, so batch mode rebuilds the table.
    return "always" if op.get_bind().dialect.name == "sqlite" else "auto"


def upgrade() -> None:
    # Widened first: if MySQL refuses it, nothing else of this revision exists yet.
    with op.batch_alter_table(_GATE_VISITS, recreate=_recreate()) as batch_op:
        # MySQL's MODIFY restates the column, so it must be told the column stays NOT NULL.
        batch_op.alter_column(
            "token",
            existing_type=_OLD_TOKEN,
            type_=_NEW_TOKEN,
            existing_nullable=False,
        )
    op.create_table(
        _ALERTS,
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("owner_user_id", sa.String(128), nullable=True),
        sa.Column("account_generation", sa.String(32), nullable=True),
        sa.Column("kind", sa.SmallInteger(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("subject_id", sa.String(32), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("payload", CAPPED_TEXT, nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("acked_at", sa.BigInteger(), nullable=True),
        sa.Column("acked_by", sa.String(128), nullable=True),
        sa.Column("resolved_at", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", "id", name="pk_coral_alerts"),
        sa.CheckConstraint("kind IN (1, 2, 3, 4, 5, 6, 7, 8, 9)", name="ck_coral_alerts_kind"),
        sa.CheckConstraint("priority IN (1, 2)", name="ck_coral_alerts_priority"),
        sa.CheckConstraint("status IN (1, 2, 3)", name="ck_coral_alerts_status"),
    )
    op.create_index(
        _INBOX_INDEX,
        _ALERTS,
        ["workspace_id", "owner_user_id", "status", "priority", "created_at", "id"],
    )
    op.create_index(_SUBJECT_INDEX, _ALERTS, ["workspace_id", "run_id", "subject_id"])


def _downgrade_blockers(bind: sa.Connection) -> list[str]:
    """Name each kind of stored data the coral_0003 schema cannot hold."""
    alerts = sa.table(_ALERTS, sa.column("id"))
    visits = sa.table(_GATE_VISITS, sa.column("id"), sa.column("token"))
    probes = {
        "alerts": sa.select(alerts.c.id),
        f"gate tokens longer than {_OLD_TOKEN_CHARS} characters": sa.select(visits.c.id).where(
            sa.func.char_length(visits.c.token) > _OLD_TOKEN_CHARS
        ),
    }
    return [name for name, probe in probes.items() if bind.execute(probe.limit(1)).first()]


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "Downgrade requires a live connection to check for alerts and long gate tokens"
        )
    bind = op.get_bind()
    # Checked before any DDL: MySQL commits each statement.
    found = _downgrade_blockers(bind)
    if found:
        raise RuntimeError(
            f"Delete Coral alerts and gate visits whose token is longer than {_OLD_TOKEN_CHARS} "
            f"characters before downgrading (found {', '.join(found)})"
        )

    # The narrowing can still fail on data, so it runs before anything is dropped.
    if not is_cockroachdb(bind.dialect.name):
        with op.batch_alter_table(_GATE_VISITS, recreate=_recreate()) as batch_op:
            batch_op.alter_column(
                "token",
                existing_type=_NEW_TOKEN,
                type_=_OLD_TOKEN,
                existing_nullable=False,
            )
    op.drop_index(_SUBJECT_INDEX, table_name=_ALERTS)
    op.drop_index(_INBOX_INDEX, table_name=_ALERTS)
    op.drop_table(_ALERTS)
