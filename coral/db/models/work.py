"""Work and queue ORM models (tables 15-16)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from coral.db.base import CoralBase
from coral.db.enum_codecs import WORK_KIND, WORK_STATUS, make_enum_check_constraint
from coral.db.types import CAPPED_TEXT, CHECKSUM32, CaseSensitiveString


class WorkRow(CoralBase):
    """Unified durable leased work item (signal, timer, or effect)."""

    __tablename__ = "coral_work"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    node_id: Mapped[str | None] = mapped_column(
        CaseSensitiveString(64), nullable=True, default=None
    )
    scope_key: Mapped[str | None] = mapped_column(
        CaseSensitiveString(512), nullable=True, default=None
    )
    slot_generation: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    payload: Mapped[str] = mapped_column(CAPPED_TEXT, nullable=False)
    owner_key: Mapped[str | None] = mapped_column(
        CaseSensitiveString(64), nullable=True, default=None
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    available_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lease_expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    lease_holder: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    result: Mapped[str | None] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    result_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    idempotency_cksum: Mapped[bytes] = mapped_column(CHECKSUM32, nullable=False)
    created_at_us: Mapped[int] = mapped_column(BigInteger, nullable=False)
    finished_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    # Epoch seconds of the first refusal of the current hold; null when not held.
    held_since: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("attempts", 0)
        super().__init__(**kwargs)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "run_id", "idempotency_cksum", name="uq_coral_work_idempotency"
        ),
        Index(
            "ix_coral_work_ready",
            "status",
            "available_at",
            "workspace_id",
            "run_id",
            "id",
        ),
        Index(
            "ix_coral_work_expired",
            "status",
            "lease_expires_at",
            "workspace_id",
            "run_id",
            "id",
        ),
        Index("ix_coral_work_run", "workspace_id", "run_id", "status", "id"),
        # The retention purge: finished rows of one kind and status, oldest first.
        Index(
            "ix_coral_work_finished",
            "kind",
            "status",
            "finished_at",
            "workspace_id",
            "id",
        ),
        make_enum_check_constraint("kind", WORK_KIND, name="ck_coral_work_kind"),
        make_enum_check_constraint("status", WORK_STATUS, name="ck_coral_work_status"),
    )


class WorkerLeaseRow(CoralBase):
    """Distributed leader/worker lease row."""

    __tablename__ = "coral_worker_leases"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(CaseSensitiveString(64), primary_key=True)
    holder_id: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


__all__ = [
    "WorkRow",
    "WorkerLeaseRow",
]
