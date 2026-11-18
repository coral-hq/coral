"""Canonical serialization and content hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from coral.model.authoring import Workflow
from coral.model.ir import CompiledGraph

# Analysis and the hash itself are derived, so they never contribute to the hash.
# Arrow kinds do: an authored ``back: true`` is recorded nowhere else.
_DERIVED_GRAPH_FIELDS: dict[str, object] = {"analysis": True, "content_hash": True}


def canonical_json(data: Mapping[str, object]) -> bytes:
    """Serialize JSON-compatible data with sorted keys and compact separators."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_bytes(subject: Workflow | CompiledGraph) -> bytes:
    """Canonical JSON for the authored content of a workflow or compiled graph."""
    if isinstance(subject, CompiledGraph):
        # Fields at their default are left out, so adding an optional IR field later
        # keeps the hash of every graph already pinned; runs fold with those pins.
        # ``ir_version`` is always kept: a field whose meaning changes bumps it.
        data = subject.model_dump(
            mode="json",
            exclude=_DERIVED_GRAPH_FIELDS,  # type: ignore[arg-type]
            exclude_defaults=True,
        )
        data["ir_version"] = subject.ir_version
    else:
        data = subject.model_dump(mode="json", by_alias=True)
    return canonical_json(data)


def content_hash(canonical: bytes) -> str:
    """SHA-256 hex digest of canonical bytes."""
    return hashlib.sha256(canonical).hexdigest()


def analysis_digest(graph: CompiledGraph) -> str:
    """
    SHA-256 hex digest of the graph's stored analysis.

    Fields at their default are left out, so adding an optional analysis field later
    keeps the digest of every analysis already pinned.
    """
    return content_hash(
        canonical_json(graph.analysis.model_dump(mode="json", exclude_defaults=True))
    )
