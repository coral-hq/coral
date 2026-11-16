"""SQLAlchemy implementation of the Coral leased work queue and worker lease store."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import Engine, asc, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from coral.db import (
    DEFAULT_WORKSPACE_ID,
    AgentSlotRow,
    RunRow,
    WorkerLeaseRow,
    WorkRow,
    coral_engine,
    current_workspace_id,
    make_named_managed_session_maker,
    run_write_transaction,
    shared_read_scope,
)
from coral.db.enum_codecs import WorkKind, WorkStatus
from coral.stores.protocols import WorkItem, WorkItemDraft


def _supports_skip_locked(dialect_name: str) -> bool:
    return dialect_name in {"postgresql", "mysql", "cockroachdb"}


def _to_work_item(row: WorkRow) -> WorkItem:
    return WorkItem(
        workspace_id=row.workspace_id,
        id=row.id,
        run_id=row.run_id,
        kind=row.kind,
        status=row.status,
        payload=row.payload,
        idempotency_cksum=row.idempotency_cksum,
        available_at=row.available_at,
        created_at_us=row.created_at_us,
        attempts=row.attempts,
        node_id=row.node_id,
        scope_key=row.scope_key,
        slot_generation=row.slot_generation,
        owner_key=row.owner_key,
        lease_expires_at=row.lease_expires_at,
        lease_holder=row.lease_holder,
        result=row.result,
        result_ref=row.result_ref,
        error_code=row.error_code,
        finished_at=row.finished_at,
    )


class SqlAlchemyCoralQueueStore:
    """SQLAlchemy implementation of the Coral QueueStore protocol."""

    def __init__(
        self,
        db_uri_or_engine: str | Engine,
        *,
        default_workspace_id: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._engine: Engine = (
            coral_engine(db_uri_or_engine)
            if isinstance(db_uri_or_engine, str)
            else db_uri_or_engine
        )
        self._default_workspace_id = default_workspace_id
        self._clock = clock
        self._session = make_named_managed_session_maker(
            self._engine,
            query_name_prefix="coral.queue_store",
        )
        self._write_session = make_named_managed_session_maker(
            self._engine,
            query_name_prefix="coral.queue_store",
            immediate=True,
        )

    def _resolve_workspace_id(self, workspace_id: int | None) -> int:
        if workspace_id is not None:
            return workspace_id
        if self._default_workspace_id is not None:
            return self._default_workspace_id
        try:
            return current_workspace_id()
        except LookupError:
            return DEFAULT_WORKSPACE_ID

    def enqueue_work(
        self,
        items: Sequence[WorkItemDraft],
        *,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[str]:
        """Idempotently enqueue work items on (workspace_id, run_id, idempotency_cksum)."""
        if not items:
            return []
        ws = self._resolve_workspace_id(workspace_id)
        now_s = int(self._clock()) if now is None else now
        now_us = now_s * 1_000_000
        dialect = self._engine.dialect.name
        enqueued_ids = [item.id for item in items]

        def _op(session: Session) -> list[str]:
            for item in items:
                values: dict[str, Any] = {
                    "workspace_id": ws,
                    "id": item.id,
                    "run_id": item.run_id,
                    "kind": int(item.kind),
                    "status": int(WorkStatus.PENDING),
                    "node_id": item.node_id,
                    "scope_key": item.scope_key,
                    "slot_generation": item.slot_generation,
                    "payload": item.payload,
                    "owner_key": item.owner_key,
                    "attempts": 0,
                    "available_at": item.available_at,
                    "lease_expires_at": None,
                    "lease_holder": None,
                    "result": None,
                    "result_ref": None,
                    "error_code": None,
                    "idempotency_cksum": item.idempotency_cksum,
                    "created_at_us": now_us,
                    "finished_at": None,
                }
                if dialect == "mysql":
                    stmt = (
                        mysql_insert(WorkRow)
                        .values(**values)
                        .on_duplicate_key_update(workspace_id=WorkRow.workspace_id)
                    )
                elif dialect == "sqlite":
                    stmt = sqlite_insert(WorkRow).values(**values).on_conflict_do_nothing()
                else:
                    stmt = pg_insert(WorkRow).values(**values).on_conflict_do_nothing()
                session.execute(stmt)
            return enqueued_ids

        return run_write_transaction(self._write_session, "enqueue_work", _op)

    def claim_work(
        self,
        worker_id: str,
        *,
        kinds: Sequence[int] = (int(WorkKind.EFFECT),),
        lease_seconds: int = 60,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> WorkItem | None:
        """Atomically claim the next ready work item matching kinds."""
        if not kinds:
            return None
        clock = now_fn or self._clock
        dialect = self._engine.dialect.name
        skip_locked = _supports_skip_locked(dialect)
        kind_vals = [int(k) for k in kinds]

        def _op(session: Session) -> WorkItem | None:
            pre_now = int(clock())
            stmt = select(WorkRow).where(
                WorkRow.status == int(WorkStatus.PENDING),
                WorkRow.kind.in_(kind_vals),
                WorkRow.available_at <= pre_now,
            )
            if workspace_id is not None:
                stmt = stmt.where(WorkRow.workspace_id == workspace_id)
            stmt = (
                stmt.order_by(asc(WorkRow.available_at), asc(WorkRow.id))
                .limit(1)
                .with_for_update(skip_locked=skip_locked)
            )
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                return None
            locked_now = int(clock())
            if row.status != int(WorkStatus.PENDING) or row.available_at > locked_now:
                return None
            row.status = int(WorkStatus.CLAIMED)
            row.lease_holder = worker_id
            row.lease_expires_at = locked_now + lease_seconds
            row.attempts = int(row.attempts) + 1
            session.flush()
            return _to_work_item(row)

        return run_write_transaction(self._write_session, "claim_work", _op)

    def renew_lease(
        self,
        work_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> bool:
        """Renew an active work item lease; never revives an already-expired claim."""
        clock = now_fn or self._clock
        ws = self._resolve_workspace_id(workspace_id)

        def _op(session: Session) -> bool:
            row = session.execute(
                select(WorkRow)
                .where(WorkRow.workspace_id == ws, WorkRow.id == work_id)
                .with_for_update()
            ).scalar_one_or_none()
            locked_now = int(clock())
            if (
                row is None
                or row.status != int(WorkStatus.CLAIMED)
                or row.lease_holder != worker_id
                or row.lease_expires_at is None
                or row.lease_expires_at <= locked_now
            ):
                return False
            row.lease_expires_at = locked_now + lease_seconds
            session.flush()
            return True

        return run_write_transaction(self._write_session, "renew_lease", _op)

    def finish_work(
        self,
        work_id: str,
        *,
        worker_id: str,
        expected_lease_expires_at: int,
        status: int,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        next_available_at: int | None = None,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> bool:
        """Complete, fail, abandon, or reschedule a claimed work item conditioned on its lease."""
        clock = now_fn or self._clock
        ws = self._resolve_workspace_id(workspace_id)

        def _op(session: Session) -> bool:
            row = session.execute(
                select(WorkRow)
                .where(WorkRow.workspace_id == ws, WorkRow.id == work_id)
                .with_for_update()
            ).scalar_one_or_none()
            locked_now = int(clock())
            if (
                row is None
                or row.status != int(WorkStatus.CLAIMED)
                or row.lease_holder != worker_id
                or row.lease_expires_at != expected_lease_expires_at
            ):
                return False
            row.status = int(status)
            row.lease_holder = None
            row.lease_expires_at = None
            row.result = json.dumps(result, sort_keys=True) if result is not None else None
            row.error_code = error_code
            if next_available_at is not None:
                row.available_at = next_available_at
            row.finished_at = None if int(status) == int(WorkStatus.PENDING) else locked_now
            session.flush()
            return True

        return run_write_transaction(self._write_session, "finish_work", _op)

    def reclaim_expired_work(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> int:
        """Reclaim expired CLAIMED work items back to PENDING without touching attempts."""
        clock = now_fn or self._clock
        dialect = self._engine.dialect.name
        skip_locked = _supports_skip_locked(dialect)

        def _op(session: Session) -> int:
            pre_now = int(clock())
            stmt = select(WorkRow).where(
                WorkRow.status == int(WorkStatus.CLAIMED),
                WorkRow.lease_expires_at.is_not(None),
                WorkRow.lease_expires_at <= pre_now,
            )
            if workspace_id is not None:
                stmt = stmt.where(WorkRow.workspace_id == workspace_id)
            stmt = (
                stmt.order_by(asc(WorkRow.lease_expires_at), asc(WorkRow.id))
                .limit(limit)
                .with_for_update(skip_locked=skip_locked)
            )
            rows = session.execute(stmt).scalars().all()
            locked_now = int(clock())
            reclaimed = 0
            for row in rows:
                if (
                    row.status == int(WorkStatus.CLAIMED)
                    and row.lease_expires_at is not None
                    and row.lease_expires_at <= locked_now
                ):
                    row.status = int(WorkStatus.PENDING)
                    row.lease_holder = None
                    row.lease_expires_at = None
                    reclaimed += 1
            if reclaimed:
                session.flush()
            return reclaimed

        return run_write_transaction(self._write_session, "reclaim_expired_work", _op)

    def discover_ready_signals(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[WorkItem]:
        """Discover pending signal work items ready for processing."""
        now_s = int(self._clock()) if now is None else now
        with shared_read_scope(), self._session("discover_ready_signals") as session:
            stmt = select(WorkRow).where(
                WorkRow.status == int(WorkStatus.PENDING),
                WorkRow.kind == int(WorkKind.SIGNAL),
                WorkRow.available_at <= now_s,
            )
            if workspace_id is not None:
                stmt = stmt.where(WorkRow.workspace_id == workspace_id)
            stmt = stmt.order_by(asc(WorkRow.available_at), asc(WorkRow.id)).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [_to_work_item(r) for r in rows]

    def discover_due_timers(
        self,
        *,
        now: int,
        limit: int = 100,
        workspace_id: int | None = None,
    ) -> list[WorkItem]:
        """Discover pending timer work items due at or before now."""
        with shared_read_scope(), self._session("discover_due_timers") as session:
            stmt = select(WorkRow).where(
                WorkRow.status == int(WorkStatus.PENDING),
                WorkRow.kind == int(WorkKind.TIMER),
                WorkRow.available_at <= now,
            )
            if workspace_id is not None:
                stmt = stmt.where(WorkRow.workspace_id == workspace_id)
            stmt = stmt.order_by(asc(WorkRow.available_at), asc(WorkRow.id)).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [_to_work_item(r) for r in rows]

    def discover_ready_effects(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[WorkItem]:
        """Discover pending effect work items ready for execution."""
        now_s = int(self._clock()) if now is None else now
        with shared_read_scope(), self._session("discover_ready_effects") as session:
            stmt = select(WorkRow).where(
                WorkRow.status == int(WorkStatus.PENDING),
                WorkRow.kind == int(WorkKind.EFFECT),
                WorkRow.available_at <= now_s,
            )
            if workspace_id is not None:
                stmt = stmt.where(WorkRow.workspace_id == workspace_id)
            stmt = stmt.order_by(asc(WorkRow.available_at), asc(WorkRow.id)).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [_to_work_item(r) for r in rows]

    def discover_expired_effects(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[WorkItem]:
        """Discover claimed effect work items whose lease has expired."""
        now_s = int(self._clock()) if now is None else now
        with shared_read_scope(), self._session("discover_expired_effects") as session:
            stmt = select(WorkRow).where(
                WorkRow.status == int(WorkStatus.CLAIMED),
                WorkRow.kind == int(WorkKind.EFFECT),
                WorkRow.lease_expires_at.is_not(None),
                WorkRow.lease_expires_at <= now_s,
            )
            if workspace_id is not None:
                stmt = stmt.where(WorkRow.workspace_id == workspace_id)
            stmt = stmt.order_by(asc(WorkRow.available_at), asc(WorkRow.id)).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [_to_work_item(r) for r in rows]

    def get_run_status(
        self,
        run_id: str,
        *,
        workspace_id: int | None = None,
    ) -> int | None:
        """Return the current status integer of a run, or None if not found."""
        ws = self._resolve_workspace_id(workspace_id)
        with shared_read_scope(), self._session("get_run_status") as session:
            return session.execute(
                select(RunRow.status).where(
                    RunRow.workspace_id == ws,
                    RunRow.id == run_id,
                )
            ).scalar_one_or_none()

    def get_slot_generation(
        self,
        run_id: str,
        slot_id: str,
        *,
        workspace_id: int | None = None,
    ) -> int | None:
        """Return the current session_generation of an agent slot, or None if not found."""
        ws = self._resolve_workspace_id(workspace_id)
        with shared_read_scope(), self._session("get_slot_generation") as session:
            return session.execute(
                select(AgentSlotRow.session_generation).where(
                    AgentSlotRow.workspace_id == ws,
                    AgentSlotRow.run_id == run_id,
                    AgentSlotRow.id == slot_id,
                )
            ).scalar_one_or_none()

    def acquire_worker_lease(
        self,
        name: str,
        worker_id: str,
        *,
        lease_seconds: int = 120,
        now_fn: Callable[[], float] | None = None,
    ) -> bool:
        """Acquire or take over an expired singleton worker lease in workspace_id=0."""
        clock = now_fn or self._clock
        dialect = self._engine.dialect.name
        ws = DEFAULT_WORKSPACE_ID

        def _op(session: Session) -> bool:
            init_values: dict[str, Any] = {
                "workspace_id": ws,
                "name": name,
                "holder_id": "",
                "acquired_at": 0,
                "expires_at": 0,
            }
            if dialect == "mysql":
                init_stmt = (
                    mysql_insert(WorkerLeaseRow)
                    .values(**init_values)
                    .on_duplicate_key_update(workspace_id=WorkerLeaseRow.workspace_id)
                )
            elif dialect == "sqlite":
                init_stmt = (
                    sqlite_insert(WorkerLeaseRow).values(**init_values).on_conflict_do_nothing()
                )
            else:
                init_stmt = (
                    pg_insert(WorkerLeaseRow).values(**init_values).on_conflict_do_nothing()
                )
            session.execute(init_stmt)

            row = session.execute(
                select(WorkerLeaseRow)
                .where(
                    WorkerLeaseRow.workspace_id == ws,
                    WorkerLeaseRow.name == name,
                )
                .with_for_update()
            ).scalar_one()
            locked_now = int(clock())
            if row.expires_at > locked_now and row.holder_id != worker_id:
                return False
            row.holder_id = worker_id
            row.acquired_at = locked_now
            row.expires_at = locked_now + lease_seconds
            session.flush()
            return True

        return run_write_transaction(self._write_session, "acquire_worker_lease", _op)

    def renew_worker_lease(
        self,
        name: str,
        worker_id: str,
        *,
        lease_seconds: int = 120,
        now_fn: Callable[[], float] | None = None,
    ) -> bool:
        """Renew an active worker replica lease held by worker_id; never revives expired leases."""
        clock = now_fn or self._clock
        ws = DEFAULT_WORKSPACE_ID

        def _op(session: Session) -> bool:
            row = session.execute(
                select(WorkerLeaseRow)
                .where(
                    WorkerLeaseRow.workspace_id == ws,
                    WorkerLeaseRow.name == name,
                )
                .with_for_update()
            ).scalar_one_or_none()
            locked_now = int(clock())
            if row is None or row.holder_id != worker_id or row.expires_at <= locked_now:
                return False
            row.expires_at = locked_now + lease_seconds
            session.flush()
            return True

        return run_write_transaction(self._write_session, "renew_worker_lease", _op)

    def release_worker_lease(
        self,
        name: str,
        worker_id: str,
    ) -> bool:
        """Explicitly release a worker replica lease held by worker_id."""
        ws = DEFAULT_WORKSPACE_ID

        def _op(session: Session) -> bool:
            row = session.execute(
                select(WorkerLeaseRow)
                .where(
                    WorkerLeaseRow.workspace_id == ws,
                    WorkerLeaseRow.name == name,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if row is None or row.holder_id != worker_id:
                return False
            row.holder_id = ""
            row.expires_at = 0
            session.flush()
            return True

        return run_write_transaction(self._write_session, "release_worker_lease", _op)


__all__ = ["SqlAlchemyCoralQueueStore"]
