"""Scripted driver: fixed clock, optional effect ack, fold equals state, settled bodies."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from coral.engine import empty_state, fold, transition
from coral.engine.types import EffectCompleted, EngineConfig, Input, LogEntry, RunState
from coral.model.ir import CompiledGraph

NOW = datetime(2026, 1, 1, tzinfo=UTC)
_AUTO_ACK = frozenset({"create_session", "send_input", "close_slot"})
_HOLDS_HANDOFF = frozenset({"evaluating", "closing", "closed"})


def assert_handoff_bodies_settled(state: RunState) -> None:
    """A slot keeps a handoff body or label only while evaluating, closing or closed."""
    for slot in state.slots:
        if slot.status not in _HOLDS_HANDOFF:
            assert slot.handoff is None, slot
            assert slot.handoff_label is None, slot


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
    after: Driven | None = None,
) -> Driven:
    """Apply ``steps``, continuing ``after`` when given.

    When ``auto_ack`` is set, complete session, brief, and close.
    """
    cfg = config if config is not None else EngineConfig()
    state = after.state if after is not None else empty_state()
    log: list[LogEntry] = list(after.log) if after is not None else []
    pending: list[Input] = list(steps)
    while pending:
        command = pending.pop(0)
        result = transition(graph, state, command, NOW, cfg)
        assert result.entry.now == NOW
        log.append(result.entry)
        assert fold(graph, log, cfg) == result.state
        assert_handoff_bodies_settled(result.state)
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
