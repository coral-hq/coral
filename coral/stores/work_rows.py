"""Rules shared by every writer of ``coral_work`` rows: inserts, re-pends and holds."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Executable
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from coral.db import WorkRow
from coral.db.enum_codecs import WorkStatus
from coral.stores.protocols import WorkItemDraft

FINISHED_WORK_STATUSES = (
    int(WorkStatus.SUCCEEDED),
    int(WorkStatus.FAILED),
    int(WorkStatus.ABANDONED),
)

# A hold re-pends no sooner than this, so a held item is never claimable at once.
MIN_HOLD_DELAY_S = 5


def repended_values(available_at: int) -> dict[str, Any]:
    """Column values that make a finished row pending again, no attempt spent."""
    return {
        "status": int(WorkStatus.PENDING),
        "attempts": 0,
        "available_at": available_at,
        "error_code": None,
        "result": None,
        "finished_at": None,
        "held_since": None,
    }


def insert_pending_if_absent(
    dialect_name: str,
    workspace_id: int,
    item: WorkItemDraft,
    *,
    run_id: str,
    available_at: int,
    now_us: int,
) -> Executable:
    """Insert ``item`` as a new PENDING row unless its id or idempotency key exists."""
    values: dict[str, Any] = {
        "workspace_id": workspace_id,
        "id": item.id,
        "run_id": run_id,
        "kind": int(item.kind),
        "status": int(WorkStatus.PENDING),
        "node_id": item.node_id,
        "scope_key": item.scope_key,
        "slot_generation": item.slot_generation,
        "payload": item.payload,
        "owner_key": item.owner_key,
        "attempts": 0,
        "available_at": available_at,
        "lease_expires_at": None,
        "lease_holder": None,
        "result": None,
        "result_ref": None,
        "error_code": None,
        "idempotency_cksum": item.idempotency_cksum,
        "created_at_us": now_us,
        "finished_at": None,
    }
    if dialect_name == "mysql":
        return (
            mysql_insert(WorkRow)
            .values(**values)
            .on_duplicate_key_update(workspace_id=WorkRow.workspace_id)
        )
    if dialect_name == "sqlite":
        return sqlite_insert(WorkRow).values(**values).on_conflict_do_nothing()
    return pg_insert(WorkRow).values(**values).on_conflict_do_nothing()


__all__ = [
    "FINISHED_WORK_STATUSES",
    "MIN_HOLD_DELAY_S",
    "insert_pending_if_absent",
    "repended_values",
]
