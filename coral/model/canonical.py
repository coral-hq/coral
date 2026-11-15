"""Canonical serialization and content hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from coral.model.authoring import Workflow
from coral.model.ir import CompiledGraph

# Derived fields never contribute to the hash: Analysis, the hash itself and
# the arrow classification are all computed from the authored content.
_DERIVED_GRAPH_FIELDS: dict[str, object] = {
    "analysis": True,
    "content_hash": True,
    "arrows": {"__all__": {"kind"}},
}


def canonical_json(data: Mapping[str, object]) -> bytes:
    """Serialize JSON-compatible data with sorted keys and compact separators."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_bytes(subject: Workflow | CompiledGraph) -> bytes:
    """Canonical JSON for the authored content of a workflow or compiled graph."""
    if isinstance(subject, CompiledGraph):
        data = subject.model_dump(mode="json", exclude=_DERIVED_GRAPH_FIELDS)  # type: ignore[arg-type]
    else:
        data = subject.model_dump(mode="json", by_alias=True)
    return canonical_json(data)


def content_hash(canonical: bytes) -> str:
    """SHA-256 hex digest of canonical bytes."""
    return hashlib.sha256(canonical).hexdigest()
