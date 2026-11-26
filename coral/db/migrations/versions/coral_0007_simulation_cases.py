"""Saved simulation cases: the last run's mismatch lines, and one name per workflow.

Revision ID: coral_0007_simulation_cases
Revises: coral_0006_profiles

Downgrade drops the mismatch lines and the unique name index.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from coral.db.types import CAPPED_TEXT, CaseSensitiveString

revision: str = "coral_0007_simulation_cases"
down_revision: str | None = "coral_0006_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CASES = "coral_simulation_cases"
_NAME_INDEX = "uq_coral_simulation_cases_name"
_OLD_NAME = sa.String(256)
_NEW_NAME = CaseSensitiveString(256)


def _is_mysql() -> bool:
    return op.get_bind().dialect.name == "mysql"


def upgrade() -> None:
    with op.batch_alter_table(_CASES) as batch_op:
        batch_op.add_column(sa.Column("last_mismatches", CAPPED_TEXT, nullable=True))
        if _is_mysql():
            batch_op.alter_column(
                "name", existing_type=_OLD_NAME, type_=_NEW_NAME, existing_nullable=False
            )
    op.create_index(_NAME_INDEX, _CASES, ["workspace_id", "workflow_id", "name"], unique=True)


def downgrade() -> None:
    op.drop_index(_NAME_INDEX, table_name=_CASES)
    with op.batch_alter_table(_CASES) as batch_op:
        batch_op.drop_column("last_mismatches")
        if _is_mysql():
            batch_op.alter_column(
                "name", existing_type=_NEW_NAME, type_=_OLD_NAME, existing_nullable=False
            )
