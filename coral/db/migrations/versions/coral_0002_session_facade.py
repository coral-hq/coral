"""Session facade tables and the drift pause reason.

Revision ID: coral_0002_session_facade
Revises: coral_0001_core

Downgrade refuses while any run is paused for drift; resume or cancel those runs first.
Stop Coral servers before downgrading: the downgrade drops in-flight session state.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from coral.db.types import CHECKSUM32, CaseSensitiveString

revision: str = "coral_0002_session_facade"
down_revision: str | None = "coral_0001_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DRIFT = 12
_PAUSE_REASON_CHECK = "ck_coral_runs_pause_reason"
_PAUSE_REASON_CHECK_V2 = "ck_coral_runs_pause_reason_v2"


def upgrade() -> None:
    with op.batch_alter_table("coral_runs") as batch_op:
        # A distinct name lets CockroachDB replace the check in one transaction.
        batch_op.drop_constraint(_PAUSE_REASON_CHECK, type_="check")
        batch_op.create_check_constraint(
            _PAUSE_REASON_CHECK_V2,
            "pause_reason IS NULL OR pause_reason IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)",
        )
    op.create_table(
        "coral_session_bindings",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("role", sa.SmallInteger(), nullable=False),
        sa.Column("slot_id", CaseSensitiveString(512), nullable=True),
        sa.Column("slot_role", sa.SmallInteger(), nullable=True),
        sa.Column("effect_cksum", CHECKSUM32, nullable=False),
        sa.Column("session_generation", sa.SmallInteger(), nullable=False),
        sa.Column("host_id", sa.String(64), nullable=True),
        sa.Column("progress", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "session_id",
            name="pk_coral_session_bindings",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "run_id",
            "effect_cksum",
            name="uq_coral_session_bindings_effect",
        ),
        sa.CheckConstraint(
            "role IN (1, 2)",
            name="ck_coral_session_bindings_role",
        ),
        sa.CheckConstraint(
            "slot_role IS NULL OR slot_role IN (1, 2, 3, 4)",
            name="ck_coral_session_bindings_slot_role",
        ),
        sa.CheckConstraint(
            "progress IN (1, 2, 3)",
            name="ck_coral_session_bindings_progress",
        ),
    )
    op.create_index(
        "ix_coral_session_bindings_run",
        "coral_session_bindings",
        ["workspace_id", "run_id", "role", "session_id"],
        unique=False,
    )
    op.create_table(
        "coral_stable_ids",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("stable_id", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("effect_cksum", CHECKSUM32, nullable=False),
        sa.Column("content_cksum", CHECKSUM32, nullable=False),
        sa.Column("kind", sa.SmallInteger(), nullable=False),
        sa.Column("session_generation", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "stable_id",
            name="pk_coral_stable_ids",
        ),
        sa.CheckConstraint(
            "kind IN (1, 2, 3)",
            name="ck_coral_stable_ids_kind",
        ),
    )
    op.create_index(
        "ix_coral_stable_ids_session",
        "coral_stable_ids",
        ["workspace_id", "session_id", "stable_id"],
        unique=False,
    )
    op.create_table(
        "coral_workspace_op_intents",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("op_key", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("op", sa.SmallInteger(), nullable=False),
        sa.Column("host_id", sa.String(64), nullable=False),
        sa.Column("root", sa.String(2048), nullable=False),
        sa.Column("expected_head", sa.String(64), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "op_key",
            name="pk_coral_workspace_op_intents",
        ),
        sa.CheckConstraint(
            "op IN (1, 2, 3)",
            name="ck_coral_workspace_op_intents_op",
        ),
    )
    op.create_index(
        "ix_coral_workspace_op_intents_run",
        "coral_workspace_op_intents",
        ["workspace_id", "run_id", "op_key"],
        unique=False,
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires a live connection to check for drift pauses")
    runs = sa.table("coral_runs", sa.column("pause_reason"))
    drift_pause = sa.select(runs.c.pause_reason).where(runs.c.pause_reason == _DRIFT).limit(1)
    if op.get_bind().execute(drift_pause).first():
        raise RuntimeError("Resume or cancel runs paused for drift before downgrading")

    # The check can still fail on data, so restore it before dropping anything.
    with op.batch_alter_table("coral_runs") as batch_op:
        batch_op.drop_constraint(_PAUSE_REASON_CHECK_V2, type_="check")
        batch_op.create_check_constraint(
            _PAUSE_REASON_CHECK,
            "pause_reason IS NULL OR pause_reason IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)",
        )
    op.drop_index("ix_coral_workspace_op_intents_run", table_name="coral_workspace_op_intents")
    op.drop_index("ix_coral_stable_ids_session", table_name="coral_stable_ids")
    op.drop_index("ix_coral_session_bindings_run", table_name="coral_session_bindings")
    op.drop_table("coral_workspace_op_intents")
    op.drop_table("coral_stable_ids")
    op.drop_table("coral_session_bindings")
