"""Workflow alert ORM model (table 21)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from coral.db.base import CoralBase
from coral.db.enum_codecs import (
    ALERT_KIND,
    ALERT_PRIORITY,
    ALERT_STATUS,
    make_enum_check_constraint,
)
from coral.db.types import CAPPED_TEXT


class AlertRow(CoralBase):
    """Something a run's owner should see, kept until it is acked or what it points at resolves."""

    __tablename__ = "coral_alerts"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Derived from the run, kind and raise key, so raising twice keeps one row.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    account_generation: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # What the alert points at; resolutions match on it.
    subject_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    payload: Mapped[str] = mapped_column(CAPPED_TEXT, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    acked_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    acked_by: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    resolved_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)

    __table_args__ = (
        # The owner's feed: open rows by priority, then newest first.
        Index(
            "ix_coral_alerts_inbox",
            "workspace_id",
            "owner_user_id",
            "status",
            "priority",
            "created_at",
            "id",
        ),
        Index("ix_coral_alerts_subject", "workspace_id", "run_id", "subject_id"),
        make_enum_check_constraint("kind", ALERT_KIND, name="ck_coral_alerts_kind"),
        make_enum_check_constraint("priority", ALERT_PRIORITY, name="ck_coral_alerts_priority"),
        make_enum_check_constraint("status", ALERT_STATUS, name="ck_coral_alerts_status"),
    )


__all__ = ["AlertRow"]
