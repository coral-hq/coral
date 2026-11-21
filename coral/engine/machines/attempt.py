"""Count evidence-missing evaluations against a step's attempt cap."""

from __future__ import annotations

from coral.engine.control import failure_arrow, traverse
from coral.engine.machines.activation import find_activation, find_node, replace_activation
from coral.engine.machines.run import record_pause, refuse
from coral.engine.machines.slot import require_evaluating, return_to_working
from coral.engine.types import (
    RULES,
    ApplyResult,
    AttemptCount,
    Effect,
    HandoffEvaluated,
    RunState,
    Slot,
    effect_key,
)
from coral.model.ir import DEFAULT_ATTEMPTS, CompiledGraph

_EXHAUSTED_PREFIX = "attempts_exhausted:"
_MAX_MISSING_CHARS = 256


def note_evidence_missing(
    graph: CompiledGraph, state: RunState, command: HandoffEvaluated
) -> ApplyResult:
    """Spend one attempt. Below the cap, keep working. At the cap, take failure or pause."""
    found = require_evaluating(state, command.slot_id, command.session_generation)
    if isinstance(found, ApplyResult):
        return found
    if state.status != "running":
        return refuse(state, "run_paused")
    owner = find_activation(state, found.activation_id)
    node = find_node(graph, owner.node_id) if owner is not None else None
    cap = node.attempts if node is not None and node.attempts is not None else DEFAULT_ATTEMPTS
    used = _used(state, found.activation_id) + 1
    counted = _set_used(state, found.activation_id, used)
    if used < cap:
        working = return_to_working(counted, found.id)
        return ApplyResult(state=working.model_copy(update={"seq": state.seq + 1}))
    failure = failure_arrow(graph, owner.node_id) if owner is not None else None
    if failure is None or owner is None:
        ids = ", ".join(command.missing)
        if state.rules < RULES:
            # The previous rules named the ids as the subject.
            paused = record_pause(counted, "failure_path", "attempts_exhausted", ids)
            return ApplyResult(state=paused.model_copy(update={"seq": state.seq + 1}))
        # The slot is the subject so a retry finds the step; the detail names the ids.
        detail = _EXHAUSTED_PREFIX + ids[:_MAX_MISSING_CHARS]
        paused = record_pause(counted, "failure_path", detail, found.id)
        return ApplyResult(state=paused.model_copy(update={"seq": state.seq + 1}))
    failed, closing = _close_failed(counted, found)
    opened = traverse(
        failed,
        graph,
        failure,
        item_path=owner.item_path,
        iteration_path=owner.iteration_path,
    )
    return ApplyResult(state=opened.state, effects=(*closing, *opened.effects))


def note_blocked(graph: CompiledGraph, state: RunState, command: HandoffEvaluated) -> ApplyResult:
    """Take the failure arrow without spending an attempt, or pause when it is absent."""
    found = require_evaluating(state, command.slot_id, command.session_generation)
    if isinstance(found, ApplyResult):
        return found
    if state.status != "running":
        return refuse(state, "run_paused")
    owner = find_activation(state, found.activation_id)
    node_id = owner.node_id if owner is not None else ""
    failure = failure_arrow(graph, node_id)
    if failure is None or owner is None:
        paused = record_pause(state, "failure_path", "blocked", found.id)
        return ApplyResult(state=paused.model_copy(update={"seq": state.seq + 1}))
    failed, closing = _close_failed(state, found)
    opened = traverse(
        failed,
        graph,
        failure,
        item_path=owner.item_path,
        iteration_path=owner.iteration_path,
    )
    return ApplyResult(state=opened.state, effects=(*closing, *opened.effects))


def _close_failed(state: RunState, slot: Slot) -> tuple[RunState, tuple[Effect, ...]]:
    """Fail the activation and ask for this slot to stop.

    The slot stays ``closing`` until ``close_slot`` completes, so the stop is in the
    outbox. The activation is already ``failed``, so a sibling cannot take the forward arrow.
    """
    run_id = state.run_id if isinstance(state.run_id, str) else ""
    seq = state.seq + 1
    close = Effect(
        effect_key=effect_key(run_id, seq, "close_slot", slot.id),
        kind="close_slot",
        subject=slot.id,
        payload={"interrupt": True, "closed_label": True},
    )
    closing = state.model_copy(
        update={
            "seq": seq,
            "effects": (*state.effects, close),
            "slots": tuple(
                item.model_copy(update={"status": "closing"}) if item.id == slot.id else item
                for item in state.slots
            ),
        }
    )
    failed = replace_activation(closing, slot.activation_id, status="closed", outcome="failed")
    return failed, (close,)


def _used(state: RunState, owner_id: str) -> int:
    for item in state.attempts:
        if item.activation_id == owner_id:
            return item.used
    return 0


def _set_used(state: RunState, owner_id: str, used: int) -> RunState:
    found = False
    rows: list[AttemptCount] = []
    for item in state.attempts:
        if item.activation_id == owner_id:
            rows.append(item.model_copy(update={"used": used}))
            found = True
        else:
            rows.append(item)
    if not found:
        rows.append(AttemptCount(activation_id=owner_id, used=used))
    return state.model_copy(update={"attempts": tuple(rows)})
