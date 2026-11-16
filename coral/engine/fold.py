"""Replay a log by calling ``transition`` again."""

from __future__ import annotations

from collections.abc import Sequence

from coral.engine.reducer import transition
from coral.engine.types import EngineConfig, LogEntry, RunState, empty_state
from coral.model.ir import CompiledGraph


def fold(
    graph: CompiledGraph,
    log: Sequence[LogEntry],
    config: EngineConfig | None = None,
) -> RunState:
    """Replay accepted log entries. Entries with a rejection are skipped."""
    cfg = config if config is not None else EngineConfig()
    state = empty_state()
    for entry in log:
        if entry.rejection is not None:
            continue
        state = transition(graph, state, entry.input, entry.now, cfg).state
    return state
