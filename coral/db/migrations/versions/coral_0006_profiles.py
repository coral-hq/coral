"""Profile revisions, and the revision each run pinned of every profile it uses.

Revision ID: coral_0006_profiles
Revises: coral_0005_alerts_and_gates

Downgrade drops both tables, with every saved profile and pin.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from coral.db.types import CAPPED_TEXT, CHECKSUM32, CaseSensitiveString

revision: str = "coral_0006_profiles"
down_revision: str | None = "coral_0005_alerts_and_gates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REVISIONS = "coral_profile_revisions"
_PINS = "coral_run_profile_pins"
_PINS_INDEX = "ix_coral_run_profile_pins_ref"


def upgrade() -> None:
    op.create_table(
        _REVISIONS,
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("profile_ref", CaseSensitiveString(128), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("spec_json", CAPPED_TEXT, nullable=False),
        sa.Column("content_digest", CHECKSUM32, nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "id", name="pk_coral_profile_revisions"),
        sa.UniqueConstraint(
            "workspace_id", "profile_ref", "revision_no", name="uq_coral_profile_revisions_no"
        ),
    )
    op.create_table(
        _PINS,
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("profile_ref", CaseSensitiveString(128), nullable=False),
        sa.Column("revision_id", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id", "run_id", "profile_ref", name="pk_coral_run_profile_pins"
        ),
    )
    op.create_index(_PINS_INDEX, _PINS, ["workspace_id", "profile_ref"])


def downgrade() -> None:
    op.drop_index(_PINS_INDEX, table_name=_PINS)
    op.drop_table(_PINS)
    op.drop_table(_REVISIONS)
