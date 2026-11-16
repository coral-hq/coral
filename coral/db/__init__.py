"""Coral database models and Omnigent DB helpers."""

from __future__ import annotations

from coral.db.base import CoralBase
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
    "encode",
    "make_named_managed_session_maker",
]
