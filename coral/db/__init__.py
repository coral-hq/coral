"""Coral database models and Omnigent DB helpers."""

from __future__ import annotations

from coral.db.base import CoralBase
from coral.db.migrate import (
    CoralSchemaOrderError,
    clear_coral_schema_cache,
    coral_engine,
    current_coral_revision,
    ensure_coral_schema,
    run_coral_migrations_with_retry,
)
from coral.db.models import (
    ActivationRow,
    AgentSlotRow,
    BlobRefRow,
    GateVisitRow,
    HandoffItemRow,
    HandoffRow,
    JoinArrivalRow,
    RunLogRow,
    RunRow,
    RunSpecRow,
    SimulationCaseRow,
    WorkerLeaseRow,
    WorkflowDraftRow,
    WorkflowRow,
    WorkflowVersionRow,
    WorkRow,
)
from coral.db.types import (
    CAPPED_TEXT,
    CHECKSUM32,
    LARGE_CAPPED_TEXT,
    LARGE_MAX_STORED_BYTES,
    MAX_STORED_BYTES,
    CaseSensitiveString,
)
from omnigent.db.compression import CompressedText, encode
from omnigent.db.utils import make_named_managed_session_maker

__all__ = [
    "CAPPED_TEXT",
    "CHECKSUM32",
    "LARGE_CAPPED_TEXT",
    "LARGE_MAX_STORED_BYTES",
    "MAX_STORED_BYTES",
    "ActivationRow",
    "AgentSlotRow",
    "BlobRefRow",
    "CaseSensitiveString",
    "CompressedText",
    "CoralBase",
    "CoralSchemaOrderError",
    "GateVisitRow",
    "HandoffItemRow",
    "HandoffRow",
    "JoinArrivalRow",
    "RunLogRow",
    "RunRow",
    "RunSpecRow",
    "SimulationCaseRow",
    "WorkRow",
    "WorkerLeaseRow",
    "WorkflowDraftRow",
    "WorkflowRow",
    "WorkflowVersionRow",
    "clear_coral_schema_cache",
    "coral_engine",
    "current_coral_revision",
    "encode",
    "ensure_coral_schema",
    "make_named_managed_session_maker",
    "run_coral_migrations_with_retry",
]
