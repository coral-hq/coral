"""Slim workflow definition table.

Uses its own declarative base so Omnigent's migrations never see it. Production
DDL belongs to the Coral Alembic environment; tests create the table from
``CoralBase.metadata``.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.mysql import BINARY as MySQLBinary
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from omnigent.db.compression import CompressedText

# Largest framed (compressed) inline YAML or compiled JSON value.
MAX_STORED_BYTES = 16_383

_CAPPED_TEXT = CompressedText(max_stored_bytes=MAX_STORED_BYTES)
_CHECKSUM32 = LargeBinary(32).with_variant(MySQLBinary(32), "mysql")


class CoralBase(DeclarativeBase):
    """Declarative base for Coral tables."""


class WorkflowRow(CoralBase):
    __tablename__ = "coral_workflows"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workflow_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    yaml_text: Mapped[str] = mapped_column(_CAPPED_TEXT)
    compiled_json: Mapped[str] = mapped_column(_CAPPED_TEXT)
    content_hash: Mapped[bytes] = mapped_column(_CHECKSUM32)
    validation_state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("workspace_id", "workflow_key", name="uq_coral_workflows_key"),
    )
