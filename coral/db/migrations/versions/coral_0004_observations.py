"""Command observations: each step session's shell, write and edit calls, for done-when evidence.

Revision ID: coral_0004_observations
Revises: coral_0003_engine_bridge

Downgrade drops the observations. A step with done-when commands then has no
evidence until its commands run again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from coral.db.types import CAPPED_TEXT, CaseSensitiveString

revision: str = "coral_0004_observations"
down_revision: str | None = "coral_0003_engine_bridge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "coral_command_observations"
_RUN_INDEX = "ix_coral_command_observations_run"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("op_key", CaseSensitiveString(128), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("obs_seq", sa.BigInteger(), nullable=False),
        sa.Column("tool", sa.SmallInteger(), nullable=False),
        sa.Column("command", CAPPED_TEXT, nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("timed_out", sa.Boolean(), nullable=False),
        sa.Column("l1_after", sa.String(64), nullable=True),
        sa.Column("changed_path", CaseSensitiveString(4096), nullable=True),
        sa.PrimaryKeyConstraint(
            "workspace_id", "session_id", "op_key", name="pk_coral_command_observations"
        ),
        sa.CheckConstraint("tool IN (1, 2, 3)", name="ck_coral_command_observations_tool"),
    )
    op.create_index(_RUN_INDEX, _TABLE, ["workspace_id", "run_id", "session_id"], unique=False)


def downgrade() -> None:
    op.drop_index(_RUN_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
