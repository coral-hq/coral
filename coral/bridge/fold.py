"""A run's engine state folded from its stored log, cached per process and extended.

Rows are read at or below the run version a caller loaded, so the state always
matches that one snapshot. A cached fold at a lower version is extended with
the rows after its last seq: seqs are allocated under the run row's lock, so
every row of a later version has a higher seq.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol

from coral.bridge.codec import decode_entries
from coral.bridge.config import ENGINE_LOG_PAGE, FOLD_CACHE_RUNS
from coral.engine import fold as fold_log
from coral.engine import types as engine
from coral.model.ir import CompiledGraph
from coral.stores.protocols import CoralRun, RunLogEntry, RunNotFound


class EngineLogReader(Protocol):
    def get_run(self, run_id: str, *, workspace_id: int | None = None) -> CoralRun | None: ...

    def read_engine_log(
        self,
        run_id: str,
        *,
        workspace_id: int,
        after_seq: int = 0,
        max_run_version: int,
        limit: int = 500,
    ) -> list[RunLogEntry]: ...


@dataclass(frozen=True)
class FoldedRun:
    """The engine state at ``version``; ``last_seq`` is the newest engine row read."""

    version: int
    last_seq: int
    state: engine.RunState


@dataclass(frozen=True)
class _Cached:
    folded: FoldedRun
    graph_hash: str
    config: engine.EngineConfig


class EngineStateCache:
    """Folded engine states by run, least recently used first out.

    The bound is a run count. A run's state grows with its log, up to about 12 MB at
    the start limits (1,000 activations with full handoff bodies), so the default
    trades worst-case memory for typical runs that are far smaller.
    """

    def __init__(
        self,
        reader: EngineLogReader,
        *,
        max_runs: int = FOLD_CACHE_RUNS,
        page_size: int = ENGINE_LOG_PAGE,
    ) -> None:
        if max_runs < 1 or page_size < 1:
            raise ValueError("max_runs and page_size must be at least 1")
        self._reader = reader
        self._max_runs = max_runs
        self._page_size = page_size
        self._lock = threading.Lock()
        self._runs: OrderedDict[tuple[int, str], _Cached] = OrderedDict()

    def fold(
        self,
        *,
        workspace_id: int,
        run_id: str,
        version: int,
        graph: CompiledGraph,
        config: engine.EngineConfig,
    ) -> FoldedRun:
        """
        The run's engine state at ``version``, from rows committed at or below it.

        ``version`` must come from the same snapshot the log is read in (a run version
        loaded before the fold); a fold is cached under it and reused on every hit.

        :raises ValueError: when the run has not committed ``version`` yet, so the fold
            would miss its rows.
        :raises RunNotFound: when the workspace has no such run.
        :raises EngineLogDecodeError: for a stored row that is not an engine entry.
        """
        key = (workspace_id, run_id)
        with self._lock:
            cached = self._runs.get(key)
        base = FoldedRun(version=0, last_seq=0, state=engine.empty_state())
        if (
            cached is not None
            and cached.graph_hash == graph.content_hash
            and cached.config == config
            and cached.folded.version <= version
        ):
            if cached.folded.version == version:
                self._remember(key, cached)
                return cached.folded
            base = cached.folded
        folded = self._extend(workspace_id, run_id, version, base, graph, config)
        self._remember(key, _Cached(folded=folded, graph_hash=graph.content_hash, config=config))
        return folded

    def forget(self, *, workspace_id: int, run_id: str) -> None:
        with self._lock:
            self._runs.pop((workspace_id, run_id), None)

    def _extend(
        self,
        workspace_id: int,
        run_id: str,
        version: int,
        base: FoldedRun,
        graph: CompiledGraph,
        config: engine.EngineConfig,
    ) -> FoldedRun:
        run = self._reader.get_run(run_id, workspace_id=workspace_id)
        if run is None:
            raise RunNotFound(f"Run {run_id!r} not found in workspace {workspace_id}")
        if version > run.version:
            raise ValueError(f"run {run_id} has not committed version {version}")
        state = base.state
        last_seq = base.last_seq
        while True:
            rows = self._reader.read_engine_log(
                run_id,
                workspace_id=workspace_id,
                after_seq=last_seq,
                max_run_version=version,
                limit=self._page_size,
            )
            state = fold_log(graph, decode_entries(rows), config, start=state)
            if rows:
                last_seq = rows[-1].seq
            if len(rows) < self._page_size:
                return FoldedRun(version=version, last_seq=last_seq, state=state)

    def _remember(self, key: tuple[int, str], cached: _Cached) -> None:
        with self._lock:
            current = self._runs.get(key)
            # A concurrent fold of a newer version keeps its place.
            if current is None or current.folded.version <= cached.folded.version:
                self._runs[key] = cached
            self._runs.move_to_end(key)
            while len(self._runs) > self._max_runs:
                self._runs.popitem(last=False)


__all__ = ["EngineLogReader", "EngineStateCache", "FoldedRun"]
