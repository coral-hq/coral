"""SES-10 structure.cancel_region: interrupt and close sibling slots."""

from __future__ import annotations

from coral.engine.regions import CANCEL_REGION
from coral.engine.types import ApplyResult, Effect, RunState, effect_key
from coral.model.ir import CompiledGraph

__all__ = ["CANCEL_REGION", "apply_cancel_region", "close_effects_for_cancel"]


def apply_cancel_region(
    graph: CompiledGraph,
    state: RunState,
    effect: Effect,
) -> ApplyResult:
    """Receipt a cancel and emit close_slot for the subject when it is still live."""
    del graph  # Region membership is already decided by ENG-08 emitters.
    if effect.kind != CANCEL_REGION:
        return ApplyResult(state=state)
    closes = close_effects_for_cancel(state, effect)
    seq = state.seq + 1
    updated = state.model_copy(update={"seq": seq, "effects": (*state.effects, *closes)})
    return ApplyResult(state=updated, effects=closes, receipt_key=effect.effect_key)


def close_effects_for_cancel(state: RunState, effect: Effect) -> tuple[Effect, ...]:
    """One ``close_slot`` for the cancel subject when that slot is still open."""
    run_id = state.run_id if isinstance(state.run_id, str) else ""
    slot = next((item for item in state.slots if item.id == effect.subject), None)
    if slot is None or slot.status in {"closing", "closed"}:
        # Subject may be an activation id: close every live slot under it.
        slots = [
            item
            for item in state.slots
            if item.activation_id == effect.subject and item.status not in {"closing", "closed"}
        ]
    else:
        slots = [slot]
    seq = state.seq + 1
    return tuple(
        Effect(
            effect_key=effect_key(run_id, seq + offset, "close_slot", item.id),
            kind="close_slot",
            subject=item.id,
            payload={"interrupt": True, "closed_label": True},
        )
        for offset, item in enumerate(slots)
    )
