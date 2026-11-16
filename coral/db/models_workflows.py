"""Backwards-compatible workflow model re-export module."""

from __future__ import annotations

from coral.db.base import CoralBase
from coral.db.models.core import WorkflowRow
from coral.db.types import CAPPED_TEXT as _CAPPED_TEXT
from coral.db.types import CHECKSUM32 as _CHECKSUM32
from coral.db.types import MAX_STORED_BYTES

__all__ = [
    "MAX_STORED_BYTES",
    "_CAPPED_TEXT",
    "_CHECKSUM32",
    "CoralBase",
    "WorkflowRow",
]
