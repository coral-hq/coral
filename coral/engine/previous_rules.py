"""The edge runner-loss rule a run started without a rules marker folds with.

Stored logs hold edge runner losses, keyed then by session generation, so an unmarked run
keeps that key and payload. Every other input of an unmarked run takes the current rules.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import JsonValue

from coral.engine.facts import previous_runner_loss_key
from coral.engine.lifecycle import (
    _arm_infra_unless_live,
    _effect,
    _fact_is_stale,
    _has_receipt,
    _session_from_turn_key,
)
from coral.engine.machines.run import receipt_only, refuse, refuse_unknown
from coral.engine.machines.slot import find_slot, mark_failed_turn
from coral.engine.types import ApplyResult, Receipt, RunState, SessionFailed, TimerPolicy


def session_runner_lost(
    state: RunState, command: SessionFailed, now: datetime, policy: TimerPolicy
) -> ApplyResult:
    """Mark the failed turn, arm the ladder, and emit one effect per session generation."""
    if _has_receipt(state, command.fact_key):
        return ApplyResult(state=state, receipt_key=command.fact_key)
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if _fact_is_stale(slot, command.fact_key):
        return refuse(state, "slot.superseded")
    session_id, generation = _session_from_turn_key(command.fact_key, slot.session_generation)
    key = previous_runner_loss_key(session_id, generation)
    payload: dict[str, JsonValue] = {"session_id": session_id, "generation": generation}
    marked, _armed = _arm_infra_unless_live(
        mark_failed_turn(state, slot.id, command.fact_key), slot, now, policy
    )
    if _has_receipt(state, key):
        return receipt_only(marked, command.fact_key, {"failure_class": "infra.runner_lost"})
    seq = state.seq + 1
    effect = _effect(marked, seq, "runner_lost", slot.id, payload)
    receipts = tuple(
        Receipt(key=item, payload=dict(payload)) for item in dict.fromkeys((key, command.fact_key))
    )
    updated = marked.model_copy(
        update={
            "seq": seq,
            "effects": (*marked.effects, effect),
            "receipts": (*marked.receipts, *receipts),
        }
    )
    return ApplyResult(state=updated, effects=(effect,), receipt_key=key)
