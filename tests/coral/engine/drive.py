"""Scripted driver: fixed clock, optional effect ack, fold equals state."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from coral.engine import empty_state, fold, transition
from coral.engine.types import EffectCompleted, EngineConfig, Input, LogEntry, RunState
from coral.model.ir import CompiledGraph

NOW = datetime(2026, 1, 1, tzinfo=UTC)
_AUTO_ACK = frozenset({"create_session", "send_input", "close_slot"})


@dataclass(frozen=True)
class Driven:
    state: RunState
    log: tuple[LogEntry, ...]


def drive(
    graph: CompiledGraph,
    steps: Sequence[Input],
    *,
    config: EngineConfig | None = None,
    auto_ack: bool = True,
) -> Driven:
    """Apply ``steps``. When ``auto_ack`` is set, complete session, brief, and close."""
    cfg = config if config is not None else EngineConfig()
    state = empty_state()
    log: list[LogEntry] = []
    pending: list[Input] = list(steps)
    while pending:
        command = pending.pop(0)
        result = transition(graph, state, command, NOW, cfg)
        assert result.entry.now == NOW
        log.append(result.entry)
        assert fold(graph, log, cfg) == result.state
        state = result.state
        if auto_ack and result.entry.rejection is None:
            acknowledgements = [
                EffectCompleted(
                    effect_key=effect.effect_key,
                    payload={"pending_input": False} if effect.kind == "close_slot" else {},
                )
                for effect in result.entry.effects
                if effect.kind in _AUTO_ACK
            ]
            pending = acknowledgements + pending
    return Driven(state=state, log=tuple(log))
