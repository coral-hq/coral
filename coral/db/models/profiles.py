"""Profile revision and run pin ORM models."""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from coral.db.base import CoralBase
from coral.db.types import CAPPED_TEXT, CHECKSUM32, CaseSensitiveString


class ProfileRevisionRow(CoralBase):
    """One immutable revision of a profile; saving changed content adds the next one."""

    __tablename__ = "coral_profile_revisions"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Derived from the profile ref and revision number.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_ref: Mapped[str] = mapped_column(CaseSensitiveString(128), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_json: Mapped[str] = mapped_column(CAPPED_TEXT, nullable=False)
    content_digest: Mapped[bytes] = mapped_column(CHECKSUM32, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "profile_ref", "revision_no", name="uq_coral_profile_revisions_no"
        ),
    )


class RunProfilePinRow(CoralBase):
    """The revision of a profile a run's steps are built from, written once at run start."""

    __tablename__ = "coral_run_profile_pins"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_ref: Mapped[str] = mapped_column(CaseSensitiveString(128), primary_key=True)
    revision_id: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (Index("ix_coral_run_profile_pins_ref", "workspace_id", "profile_ref"),)


__all__ = ["ProfileRevisionRow", "RunProfilePinRow"]
