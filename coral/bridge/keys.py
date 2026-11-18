"""Ids and keys the bridge derives from engine ids, so every process derives the same ones."""

from __future__ import annotations

from coral.bridge.config import epoch_us
from coral.engine import types as engine
from coral.engine.machines.slot import effect_seq
from coral.model.ids import derived_id, effect_session_id

# The orchestrator's binding slot; engine slot ids always contain ``|``, so it cannot collide.
ORCHESTRATOR_SLOT_ID = "orchestrator"
ORCHESTRATOR_GENERATION = 1


def store_slot_id(run_id: str, engine_slot_id: str) -> str:
    """The 32-hex ``coral_agent_slots`` id of an engine slot."""
    return derived_id("coral-slot", run_id, engine_slot_id)


def store_activation_id(run_id: str, engine_activation_id: str) -> str:
    """The 32-hex activation id store rows carry for an engine activation."""
    return derived_id("coral-activation", run_id, engine_activation_id)


def slot_owner_key(run_id: str, engine_slot_id: str) -> str:
    """The work rows' ``owner_key`` of a slot's items."""
    return f"slot:{store_slot_id(run_id, engine_slot_id)}"


def roster_index(engine_slot_id: str) -> int:
    """The roster position an engine slot id ``{activation}:{index}`` ends with; 0 if absent."""
    _owner, _, index = engine_slot_id.rpartition(":")
    return int(index) if index.isdigit() else 0


def anchor_effect_key(run_id: str) -> str:
    return f"{run_id}:anchor:create_session"


def orchestrator_effect_key(run_id: str, generation: int = ORCHESTRATOR_GENERATION) -> str:
    return f"{run_id}:{ORCHESTRATOR_SLOT_ID}:{generation}:create_session"


def timer_work_key(timer: engine.Timer) -> str:
    """One work row per arming: a re-armed timer with a new due time gets a new row."""
    return f"timer:{timer.key}:{timer.generation}:{epoch_us(timer.due_at)}"


def slot_create_key(state: engine.RunState, engine_slot_id: str) -> str | None:
    """The key of the slot's latest ``create_session`` effect, or ``None`` before it has one."""
    latest: str | None = None
    latest_seq = -1
    for effect in state.effects:
        if effect.kind != "create_session" or effect.subject != engine_slot_id:
            continue
        seq = effect_seq(effect)
        if latest is None or seq > latest_seq:
            latest, latest_seq = effect.effect_key, seq
    return latest


def slot_session_id(workspace_id: int, state: engine.RunState, engine_slot_id: str) -> str | None:
    """
    The step session the slot's latest create makes, known before that create completes.

    The facade derives step session ids from the create's effect key, so a cancel can
    name a session whose create is still in flight.
    """
    key = slot_create_key(state, engine_slot_id)
    return None if key is None else effect_session_id(workspace_id, key)


__all__ = [
    "ORCHESTRATOR_GENERATION",
    "ORCHESTRATOR_SLOT_ID",
    "anchor_effect_key",
    "orchestrator_effect_key",
    "roster_index",
    "slot_create_key",
    "slot_owner_key",
    "slot_session_id",
    "store_activation_id",
    "store_slot_id",
    "timer_work_key",
]
