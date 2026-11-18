"""Session facade ORM models (tables 17-19): session bindings, stable ids, op intents."""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from coral.db.base import CoralBase
from coral.db.enum_codecs import (
    SESSION_BINDING_PROGRESS,
    SESSION_BINDING_ROLE,
    SLOT_ROLE,
    STABLE_ID_KIND,
    WORKSPACE_OP_INTENT_OP,
    make_enum_check_constraint,
)
from coral.db.types import CHECKSUM32, CaseSensitiveString


class SessionBindingRow(CoralBase):
    """Omnigent session created for a run: its anchor or one engine step slot."""

    __tablename__ = "coral_session_bindings"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Engine slot id; null for the anchor.
    slot_id: Mapped[str | None] = mapped_column(
        CaseSensitiveString(512), nullable=True, default=None
    )
    # Decides who may commit; null for the anchor.
    slot_role: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    # sha256 of the creating effect key; the anchor keeps its first effect's.
    effect_cksum: Mapped[bytes] = mapped_column(CHECKSUM32, nullable=False)
    session_generation: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    host_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("session_generation", 1)
        super().__init__(**kwargs)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "run_id", "effect_cksum", name="uq_coral_session_bindings_effect"
        ),
        Index("ix_coral_session_bindings_run", "workspace_id", "run_id", "role", "session_id"),
        # One step session per slot and generation; anchors have no slot and never collide.
        Index(
            "uq_coral_session_bindings_slot_generation",
            "workspace_id",
            "run_id",
            "slot_id",
            "session_generation",
            unique=True,
        ),
        make_enum_check_constraint(
            "role", SESSION_BINDING_ROLE, name="ck_coral_session_bindings_role"
        ),
        make_enum_check_constraint(
            "slot_role", SLOT_ROLE, name="ck_coral_session_bindings_slot_role", nullable=True
        ),
        make_enum_check_constraint(
            "progress", SESSION_BINDING_PROGRESS, name="ck_coral_session_bindings_progress"
        ),
    )


class StableIdRow(CoralBase):
    """Message item id the engine sent to a session, recorded before the send."""

    __tablename__ = "coral_stable_ids"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stable_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    effect_cksum: Mapped[bytes] = mapped_column(CHECKSUM32, nullable=False)
    # sha256 of the exact text sent, to check an item found under this id is the engine's.
    content_cksum: Mapped[bytes] = mapped_column(CHECKSUM32, nullable=False)
    kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    session_generation: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_coral_stable_ids_session", "workspace_id", "session_id", "stable_id"),
        make_enum_check_constraint("kind", STABLE_ID_KIND, name="ck_coral_stable_ids_kind"),
    )


class WorkspaceOpIntentRow(CoralBase):
    """Workspace write op recorded before its first try, keeping the HEAD it expects."""

    __tablename__ = "coral_workspace_op_intents"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    op_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    op: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    host_id: Mapped[str] = mapped_column(String(64), nullable=False)
    root: Mapped[str] = mapped_column(String(2048), nullable=False)
    expected_head: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_coral_workspace_op_intents_run", "workspace_id", "run_id", "op_key"),
        make_enum_check_constraint(
            "op", WORKSPACE_OP_INTENT_OP, name="ck_coral_workspace_op_intents_op"
        ),
    )


__all__ = [
    "SessionBindingRow",
    "StableIdRow",
    "WorkspaceOpIntentRow",
]
