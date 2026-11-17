"""Slot phases from session creation through close."""

from __future__ import annotations

from pydantic import JsonValue

from coral.engine.facts import turn_key_generation
from coral.engine.machines.activation import (
    choosable_labels,
    find_activation,
    finish_activation,
    replace_activation,
    routes_by_label,
)
from coral.engine.machines.run import record_pause, refuse, refuse_unknown
from coral.engine.types import (
    ActivationStatus,
    ApplyResult,
    Effect,
    EffectCompleted,
    HandoffEvaluated,
    HandoffReceived,
    PostCloseActivity,
    Receipt,
    RunState,
    Slot,
    TurnEnded,
    effect_key,
)
from coral.model.ir import CompiledGraph
from coral.signals.nudge import decide, turn_ended_snapshot


def complete_effect(
    graph: CompiledGraph, state: RunState, effect: Effect, command: EffectCompleted
) -> ApplyResult:
    """Apply a completed ``create_session``, ``send_input``, ``close_slot``, or ``nudge``."""
    slot = find_slot(state, effect.subject)
    if slot is None:
        return refuse_unknown(state)
    if effect.kind == "create_session" and slot.status == "pending":
        return _session_created(state, effect, slot, command.payload)
    if effect.kind == "send_input" and slot.status == "session_created":
        return _working(state, effect, slot, command.payload)
    if effect.kind == "close_slot" and slot.status == "closing":
        return _closed(graph, state, effect, slot, command.payload)
    if effect.kind == "nudge":
        return _nudged(state, effect, slot, command.payload)
    return refuse_unknown(state)


def note_turn_ended(state: RunState, command: TurnEnded) -> ApplyResult:
    """Move a working slot to evaluating and receipt the fact. No handoff body is stored.

    A nudge is emitted when ``decide`` is true for the slot status before that move.
    A second ``TurnEnded`` returns the receipt and emits nothing.
    """
    if any(item.key == command.fact_key for item in state.receipts):
        return ApplyResult(state=state, receipt_key=command.fact_key)
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if slot.status == "closed":
        return refuse(state, "slot.closed")
    if slot.status != "working":
        return refuse_unknown(state)
    generation = turn_key_generation(command.fact_key)
    if generation is not None and generation < slot.session_generation:
        return refuse(state, "slot.superseded")
    seq = state.seq + 1
    effects: tuple[Effect, ...] = ()
    if decide(turn_ended_snapshot(command.origin), slot.status, fact_key=command.fact_key):
        run_id = state.run_id if isinstance(state.run_id, str) else ""
        effects = (
            Effect(
                effect_key=effect_key(run_id, seq, "nudge", slot.id),
                kind="nudge",
                subject=slot.id,
                payload={"fact_key": command.fact_key},
            ),
        )
    updated = _map_slot(state, slot.id, status="evaluating")
    receipt = Receipt(key=command.fact_key, payload={"status": "evaluating"})
    updated = updated.model_copy(
        update={
            "seq": seq,
            "receipts": (*updated.receipts, receipt),
            "effects": (*updated.effects, *effects),
        }
    )
    return ApplyResult(
        state=_rephase(updated, slot.activation_id),
        effects=effects,
        receipt_key=command.fact_key,
    )


def receive_handoff(
    graph: CompiledGraph, state: RunState, command: HandoffReceived
) -> ApplyResult:
    """Store the handoff and evaluate it. A second handoff is in progress.

    A slot whose turn ended without a handoff is evaluating with no body and still
    accepts one. A given label must be one of the step's arrow labels.
    """
    found = guard_handoff(state, command.slot_id, command.session_generation)
    if isinstance(found, ApplyResult):
        return found
    if found.status in {"pending", "session_created", "briefed"}:
        return refuse(state, "slot.not_ready")
    if found.status == "closing":
        return refuse(state, "slot.closed")
    if state.status != "running":
        return refuse(state, "run_paused")
    if found.status == "evaluating" and found.handoff is not None:
        return _in_progress(state)
    slot = found
    if command.label is not None:
        labels = _step_labels(graph, state, slot)
        if command.label not in labels:
            return refuse(state, "handoff.invalid", labels)
    updated = _map_slot(
        state,
        slot.id,
        status="evaluating",
        handoff=command.body,
        handoff_label=command.label,
    )
    updated = updated.model_copy(update={"seq": state.seq + 1})
    return ApplyResult(state=_rephase(updated, slot.activation_id))


def evaluate_handoff(
    graph: CompiledGraph, state: RunState, command: HandoffEvaluated
) -> ApplyResult:
    """Accept a handoff by closing the slot. A step routed by label needs the label it chose."""
    found = require_evaluating(state, command.slot_id, command.session_generation)
    if isinstance(found, ApplyResult):
        return found
    if state.status != "running":
        return refuse(state, "run_paused")
    owner = find_activation(state, found.activation_id)
    if owner is not None and routes_by_label(graph, owner.node_id) and found.handoff_label is None:
        return refuse(state, "handoff.invalid", choosable_labels(graph, owner.node_id))
    run_id = state.run_id
    if not isinstance(run_id, str):
        return refuse_unknown(state)
    slot = found
    base = _reset_streak(state, slot.id)
    seq = state.seq + 1
    close = Effect(
        effect_key=effect_key(run_id, seq, "close_slot", slot.id),
        kind="close_slot",
        subject=slot.id,
        payload={"interrupt": True, "closed_label": True},
    )
    updated = _map_slot(base, slot.id, status="closing")
    updated = updated.model_copy(update={"seq": seq, "effects": (*updated.effects, close)})
    return ApplyResult(state=_rephase(updated, slot.activation_id), effects=(close,))


def guard_handoff(state: RunState, slot_id: str, generation: int) -> Slot | ApplyResult:
    """Reject a closed slot or a handoff from an older session generation."""
    slot = find_slot(state, slot_id)
    if slot is None:
        return refuse_unknown(state)
    if slot.status == "closed":
        return refuse(state, "slot.closed")
    if generation < slot.session_generation:
        return refuse(state, "slot.superseded")
    return slot


def require_evaluating(state: RunState, slot_id: str, generation: int) -> Slot | ApplyResult:
    """The slot must be evaluating a received handoff, on its current session generation.

    An evaluating slot with no body ended its turn without a handoff, so there is nothing
    to evaluate yet.
    """
    found = guard_handoff(state, slot_id, generation)
    if isinstance(found, ApplyResult):
        return found
    if found.status != "evaluating":
        return refuse_unknown(state)
    if found.handoff is None:
        return refuse(state, "slot.not_ready")
    return found


def return_to_working(state: RunState, slot_id: str) -> RunState:
    """Put a slot back to work without closing it. Its handoff body and label are dropped."""
    slot = find_slot(state, slot_id)
    if slot is None:
        return state
    updated = _map_slot(state, slot_id, status="working", handoff=None, handoff_label=None)
    return _rephase(updated, slot.activation_id)


def note_post_close(state: RunState, command: PostCloseActivity) -> ApplyResult:
    """A closed slot that keeps working sets drift and pauses a running run."""
    slot = find_slot(state, command.slot_id)
    if slot is None or slot.status != "closed" or state.status != "running":
        return refuse_unknown(state)
    drifted = _map_slot(state, slot.id, drift=True)
    paused = record_pause(drifted, "drift", "post_close", slot.id)
    return ApplyResult(state=paused.model_copy(update={"seq": state.seq + 1}))


def find_slot(state: RunState, slot_id: str) -> Slot | None:
    for slot in state.slots:
        if slot.id == slot_id:
            return slot
    return None


def _session_created(
    state: RunState,
    effect: Effect,
    slot: Slot,
    payload: dict[str, JsonValue],
) -> ApplyResult:
    run_id = state.run_id
    if not isinstance(run_id, str):
        return refuse_unknown(state)
    seq = state.seq + 1
    brief = Effect(
        effect_key=effect_key(run_id, seq, "send_input", slot.id),
        kind="send_input",
        subject=slot.id,
        payload={
            "node_id": _text(effect.payload, "node_id"),
            "profile": slot.profile,
            "goal": _text(effect.payload, "goal"),
        },
    )
    updated = _commit(
        state,
        slot,
        status="session_created",
        receipt=Receipt(key=effect.effect_key, payload=dict(payload)),
        effects=(brief,),
        seq=seq,
    )
    return ApplyResult(
        state=_rephase(updated, slot.activation_id),
        effects=(brief,),
        receipt_key=effect.effect_key,
    )


def _working(
    state: RunState,
    effect: Effect,
    slot: Slot,
    payload: dict[str, JsonValue],
) -> ApplyResult:
    updated = _commit(
        state,
        slot,
        status="working",
        receipt=Receipt(key=effect.effect_key, payload=dict(payload)),
        seq=state.seq + 1,
    )
    return ApplyResult(
        state=_rephase(updated, slot.activation_id),
        receipt_key=effect.effect_key,
    )


def _nudged(
    state: RunState,
    effect: Effect,
    slot: Slot,
    payload: dict[str, JsonValue],
) -> ApplyResult:
    """The nudge started a turn. A slot still waiting for its handoff goes back to work.

    A nudge for an older session generation only records its receipt.
    """
    fact_key = effect.payload.get("fact_key")
    generation = turn_key_generation(fact_key) if isinstance(fact_key, str) else None
    stale = generation is not None and generation < slot.session_generation
    waiting = not stale and slot.status == "evaluating" and slot.handoff is None
    updated = _commit(
        state,
        slot,
        status="working" if waiting else slot.status,
        receipt=Receipt(key=effect.effect_key, payload=dict(payload)),
        seq=state.seq + 1,
    )
    if waiting:
        updated = _rephase(updated, slot.activation_id)
    return ApplyResult(state=updated, receipt_key=effect.effect_key)


def _closed(
    graph: CompiledGraph,
    state: RunState,
    effect: Effect,
    slot: Slot,
    payload: dict[str, JsonValue],
) -> ApplyResult:
    pending = payload.get("pending_input") is True
    updated = _commit(
        state,
        slot,
        status="closing" if pending else "closed",
        pending_input=pending,
        receipt=Receipt(key=effect.effect_key, payload=dict(payload)),
        seq=state.seq + 1,
    )
    if pending:
        return ApplyResult(
            state=_rephase(updated, slot.activation_id),
            receipt_key=effect.effect_key,
        )
    owners = [item for item in updated.slots if item.activation_id == slot.activation_id]
    if owners and all(item.status == "closed" for item in owners):
        finished, spawned = finish_activation(updated, graph, slot.activation_id)
        return ApplyResult(state=finished, effects=spawned, receipt_key=effect.effect_key)
    return ApplyResult(
        state=_rephase(updated, slot.activation_id),
        receipt_key=effect.effect_key,
    )


def _commit(
    state: RunState,
    slot: Slot,
    *,
    status: str,
    receipt: Receipt,
    seq: int,
    effects: tuple[Effect, ...] = (),
    pending_input: bool | None = None,
) -> RunState:
    changes: dict[str, object] = {"status": status}
    if pending_input is not None:
        changes["pending_input"] = pending_input
    mapped = _map_slot(state, slot.id, **changes)
    return mapped.model_copy(
        update={
            "seq": seq,
            "receipts": (*mapped.receipts, receipt),
            "effects": (*mapped.effects, *effects),
        }
    )


def _reset_streak(state: RunState, slot_id: str) -> RunState:
    """An accepted handoff clears that slot's rejection streak."""
    if not any(item.slot_id == slot_id and item.count for item in state.reject_streaks):
        return state
    return state.model_copy(
        update={
            "reject_streaks": tuple(
                item.model_copy(update={"count": 0}) if item.slot_id == slot_id else item
                for item in state.reject_streaks
            )
        }
    )


def _map_slot(state: RunState, slot_id: str, **changes: object) -> RunState:
    return state.model_copy(
        update={
            "slots": tuple(
                item.model_copy(update=changes) if item.id == slot_id else item
                for item in state.slots
            )
        }
    )


def _rephase(state: RunState, owner_id: str) -> RunState:
    """Match the activation to its live slots. A failed close stays failed."""
    slots = [slot for slot in state.slots if slot.activation_id == owner_id]
    if not slots or all(slot.status == "closed" for slot in slots):
        return state
    owner = find_activation(state, owner_id)
    if owner is None or owner.status == "closed" or owner.outcome == "failed":
        return state
    status: ActivationStatus
    if any(slot.status in {"pending", "session_created"} for slot in slots):
        status = "starting"
    elif any(slot.status in {"evaluating", "closing"} for slot in slots):
        status = "evaluating"
    elif any(slot.status == "working" for slot in slots):
        status = "running"
    else:
        status = "starting"
    return replace_activation(state, owner_id, status=status)


def _in_progress(state: RunState) -> ApplyResult:
    return refuse(state, "evaluation_in_progress")


def _step_labels(graph: CompiledGraph, state: RunState, slot: Slot) -> tuple[str, ...]:
    """The arrow labels the slot's step can choose. An unlabelled step has none."""
    owner = find_activation(state, slot.activation_id)
    if owner is None:
        return ()
    return choosable_labels(graph, owner.node_id)


def _text(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key, "")
    return value if isinstance(value, str) else ""
