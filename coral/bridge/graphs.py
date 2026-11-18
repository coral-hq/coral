"""The graph a run folds with: its pinned version, checked against its own content hash.

The version store keeps whatever hash a caller pins under, so the hash is
recomputed here from the graph before a run may use it.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Protocol

from coral.bridge.config import FOLD_CACHE_RUNS
from coral.model.canonical import canonical_bytes, content_hash
from coral.model.ids import derived_id
from coral.model.ir import CompiledGraph
from coral.stores.workflow_versions import PinnedVersion


class WorkflowVersions(Protocol):
    def load(self, *, workspace_id: int, version_id: str) -> PinnedVersion | None: ...


class PinnedGraphError(Exception):
    """A run's pinned graph cannot be used."""


class PinnedGraphMissing(PinnedGraphError, LookupError):
    """The workspace has no version by that id."""


class PinnedGraphUnreadable(PinnedGraphError, ValueError):
    """The version row exists but holds no graph this process can read."""


class PinnedGraphMismatch(PinnedGraphError, ValueError):
    """The stored graph is not the one its hash, its id or its run names."""


def verified_content_hash(graph: CompiledGraph) -> str:
    """
    The graph's content hash, recomputed from its authored content.

    :raises PinnedGraphMismatch: when the graph carries another hash.
    """
    recomputed = content_hash(canonical_bytes(graph))
    if graph.content_hash != recomputed:
        raise PinnedGraphMismatch(
            f"graph {graph.workflow_id!r} carries a content hash its content does not have"
        )
    return recomputed


class PinnedGraphs:
    """Loads pinned graphs once per process; a pinned version never changes."""

    def __init__(self, versions: WorkflowVersions, *, max_entries: int = FOLD_CACHE_RUNS) -> None:
        self._versions = versions
        self._max_entries = max_entries
        self._lock = threading.Lock()
        self._graphs: OrderedDict[tuple[int, str], CompiledGraph] = OrderedDict()

    def load(
        self, *, workspace_id: int, version_id: str, expected_hash: str | None = None
    ) -> CompiledGraph:
        """
        The graph of a pinned version.

        :param expected_hash: The hash the run started with, when it must match.
        :raises PinnedGraphMissing: when the workspace has no such version.
        :raises PinnedGraphUnreadable: when the row stores no inline graph.
        :raises PinnedGraphMismatch: when the stored hash is not the graph's own, the id
            is not the one its content derives, or the run started on another hash.
        """
        key = (workspace_id, version_id)
        with self._lock:
            graph = self._graphs.get(key)
            if graph is not None:
                self._graphs.move_to_end(key)
        if graph is None:
            graph = self._read(workspace_id, version_id)
            with self._lock:
                self._graphs[key] = graph
                self._graphs.move_to_end(key)
                while len(self._graphs) > self._max_entries:
                    self._graphs.popitem(last=False)
        if expected_hash is not None and graph.content_hash != expected_hash:
            raise PinnedGraphMismatch(
                f"workflow version {version_id} is not the graph its run started on"
            )
        return graph

    def _read(self, workspace_id: int, version_id: str) -> CompiledGraph:
        try:
            pinned = self._versions.load(workspace_id=workspace_id, version_id=version_id)
        except ValueError:
            raise PinnedGraphUnreadable(
                f"workflow version {version_id} holds no readable inline graph"
            ) from None
        if pinned is None or pinned.workspace_id != workspace_id:
            raise PinnedGraphMissing(f"workflow version {version_id} is not in this workspace")
        try:
            recomputed = verified_content_hash(pinned.graph)
        except PinnedGraphMismatch:
            raise PinnedGraphMismatch(
                f"workflow version {version_id} holds a graph its stored hash does not name"
            ) from None
        derived = derived_id("coral-workflow-version", pinned.workflow_id, recomputed)
        if pinned.content_hash != recomputed or pinned.id != derived:
            raise PinnedGraphMismatch(
                f"workflow version {version_id} holds a graph its stored hash does not name"
            )
        return pinned.graph


__all__ = [
    "PinnedGraphError",
    "PinnedGraphMismatch",
    "PinnedGraphMissing",
    "PinnedGraphUnreadable",
    "PinnedGraphs",
    "WorkflowVersions",
    "verified_content_hash",
]
