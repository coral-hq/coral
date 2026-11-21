"""Level-triggered reconcile. Returns inputs and does not apply them."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from coral.engine.classify import classify_failure
from coral.engine.facts import TurnFact, runner_loss_key
from coral.engine.machines.slot import awaiting_effect, reports_an_ended_outage
from coral.engine.turn_end import evaluate
from coral.engine.types import (
    EngineConfig,
    Input,
    RunnerLost,
    RunState,
    SessionFailed,
    TurnEnded,
)

__all__ = ["awaiting_effect", "reconcile"]


def reconcile(
    state: RunState,
    facts: Sequence[TurnFact],
    now: datetime,
    config: EngineConfig,
) -> tuple[Input, ...]:
    """Inputs for facts whose keys are not yet receipted.

    Facts are ordered before the first one for a key is chosen, then the inputs are
    sorted, so one multiset always returns the same tuple. ``state`` is not mutated.
    A missing ``generation`` is the string ``"None"`` in the turn key. A missing
    ``session_id`` or response tail is that same string.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("now must be timezone-aware")
    produced: list[Input] = []
    seen_turn: set[str] = set()
    seen_runner: set[str] = set()
    for fact in sorted(facts, key=_fact_sort_key):
        if awaiting_effect(state, fact.slot_id):
            continue
        fact_key = _turn_key(fact)
        if fact_key not in seen_turn and not _receipted(state, fact_key):
            verdict = evaluate(fact)
            if verdict == "completed":
                seen_turn.add(fact_key)
                produced.append(
                    TurnEnded(
                        slot_id=fact.slot_id,
                        fact_key=fact_key,
                        origin=fact.origin if isinstance(fact.origin, str) else "engine",
                    )
                )
            elif verdict == "failed":
                seen_turn.add(fact_key)
                failure = classify_failure(fact)
                produced.append(
                    SessionFailed(
                        slot_id=fact.slot_id,
                        failure_class=failure.name,
                        cause=failure.cause,
                        fact_key=fact_key,
                        runner_id=fact.runner_id,
                        observed_at=fact.observed_at,
                    )
                )
        lost = _runner_lost(state, fact, now, config)
        if lost is None:
            continue
        runner_key = _loss_key(state, lost)
        if runner_key in seen_runner or _receipted(state, runner_key):
            continue
        seen_runner.add(runner_key)
        produced.append(lost)
    return tuple(sorted(produced, key=_input_sort_key))


def _turn_key(fact: TurnFact) -> str:
    """``turn:{session}:{generation}:{response_id or origin}``.

    ``generation`` is the decimal text, or ``"None"`` when the fact has no generation.
    The tail is ``response_id`` when it is present, otherwise ``origin``.
    """
    generation = "None" if fact.generation is None else str(fact.generation)
    session = "None" if fact.session_id is None else fact.session_id
    tail = fact.response_id if fact.response_id is not None else fact.origin
    tail_text = "None" if tail is None else tail
    return f"turn:{session}:{generation}:{tail_text}"


def _runner_lost(
    state: RunState, fact: TurnFact, now: datetime, config: EngineConfig
) -> RunnerLost | None:
    """One loss when the runner is older than the grace and the slot is working."""
    if not isinstance(fact.session_id, str) or not isinstance(fact.generation, int):
        return None
    seen = fact.runner_last_seen
    if seen is None or seen >= now - config.runner_grace:
        return None
    slot = next((item for item in state.slots if item.id == fact.slot_id), None)
    if slot is None or slot.status != "working":
        return None
    if reports_an_ended_outage(slot, fact.runner_id, seen):
        return None
    return RunnerLost(
        slot_id=fact.slot_id,
        session_id=fact.session_id,
        generation=fact.generation,
        runner_id=fact.runner_id,
        fact_key=_turn_key(fact),
        observed_at=seen,
    )


def _loss_key(state: RunState, lost: RunnerLost) -> str:
    """The key the reducer receipts for this loss."""
    slot = next((item for item in state.slots if item.id == lost.slot_id), None)
    epoch = slot.connection_epoch if slot is not None else 0
    return runner_loss_key(lost.session_id, lost.generation, lost.runner_id, lost.fact_key, epoch)


def _receipted(state: RunState, key: str) -> bool:
    return any(item.key == key for item in state.receipts)


def _fact_sort_key(fact: TurnFact) -> tuple[object, ...]:
    """Every field that can change an input, so a multiset has one order."""
    seen = ""
    if fact.runner_last_seen is not None:
        seen = fact.runner_last_seen.isoformat()
    return (
        fact.slot_id,
        _opt_str(fact.session_id),
        _opt_int(fact.generation),
        _opt_str(fact.response_id),
        _opt_str(fact.origin),
        _opt_str(fact.live_status),
        _opt_str(fact.turn_outcome),
        fact.engine_stable_id_present is True,
        fact.newest_substantive_item_is_assistant is True,
        fact.saw_response_completed is True,
        _opt_int(fact.background_tasks),
        _opt_int(fact.pending_elicitation_count),
        fact.engine_pending_input is True,
        fact.engine_started is True,
        _opt_int(fact.status_code),
        _opt_str(fact.error_text),
        _opt_str(fact.error_code),
        _opt_str(fact.failure_origin),
        seen,
        _opt_str(fact.runner_id),
        "" if fact.observed_at is None else fact.observed_at.isoformat(),
    )


def _opt_str(value: str | None) -> tuple[bool, str]:
    if value is None:
        return (False, "")
    return (True, value)


def _opt_int(value: int | None) -> tuple[bool, int]:
    if value is None:
        return (False, 0)
    return (True, value)


def _input_sort_key(command: Input) -> tuple[str, str, str]:
    if isinstance(command, RunnerLost):
        loss = (
            f"{command.session_id}:{command.generation}:{command.runner_id}:{command.fact_key}"
            f":{command.observed_at}"
        )
        return (command.kind, loss, command.slot_id)
    if isinstance(command, (TurnEnded, SessionFailed)):
        return (command.kind, command.fact_key, command.slot_id)
    kind = getattr(command, "kind", "")
    fact_key = getattr(command, "fact_key", "")
    slot_id = getattr(command, "slot_id", "")
    return (str(kind), str(fact_key), str(slot_id))
