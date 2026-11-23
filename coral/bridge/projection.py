"""Engine state written onto the run row and the agent-slot rows the queue reads.

Executors and the drainer read these rows, never the engine state: the slot's
generation fences stale work and its session lets a writer's close commit.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from coral.bridge.keys import roster_index, slot_create_key, store_activation_id, store_slot_id
from coral.db.enum_codecs import RUN_PAUSE_REASON, RUN_STATUS, SLOT_STATUS, SlotRole
from coral.engine import types as engine
from coral.engine.machines.activation import find_activation
from coral.profiles.refs import roster_stance
from coral.stores.protocols import AgentSlotDraft, AgentSlotState, CoralRun

# Stances whose slots write the run worktree; any other profile reads it.
_SLOT_ROLES: Mapping[str, SlotRole] = {
    "implementer": SlotRole.STEP_AGENT,
    "reviewer": SlotRole.VERIFIER,
}


@dataclass(frozen=True)
class RunProjection:
    """Run-row fields that differ from the engine state; unset ones stay as stored."""

    status: int | None = None
    pause_reason: int | None = None
    clear_pause_reason: bool = False
    finished_at: int | None = None
    activation_count_delta: int = 0


def slot_role(profile: str) -> SlotRole:
    """The slot role of a roster entry's stance; an unknown one gets the read-only role."""
    return _SLOT_ROLES.get(roster_stance(profile) or profile, SlotRole.VERIFIER)


def run_status_code(state: engine.RunState) -> int:
    """The run row's status: a run the engine has not started is still starting."""
    return RUN_STATUS["starting" if state.status is None else state.status]


def project_run(run: CoralRun, state: engine.RunState, *, now: int) -> RunProjection:
    """
    The run-row changes that make ``run`` show ``state``.

    A paused run shows its first cause; a run that is not paused clears the reason;
    a finished run records ``now`` as its finish time once.
    """
    status = run_status_code(state)
    pause_reason: int | None = None
    clear_pause_reason = False
    if state.status == "paused" and state.causes:
        code = RUN_PAUSE_REASON[state.causes[0].reason]
        if run.pause_reason != code:
            pause_reason = code
    elif state.status != "paused" and run.pause_reason is not None:
        clear_pause_reason = True
    finished = state.status in engine.TERMINAL_STATUSES and run.finished_at is None
    return RunProjection(
        status=None if status == run.status else status,
        pause_reason=pause_reason,
        clear_pause_reason=clear_pause_reason,
        finished_at=now if finished else None,
        activation_count_delta=len(state.activations) - run.activation_count,
    )


def project_slots(
    run_id: str,
    state: engine.RunState,
    loaded: Sequence[AgentSlotState],
    *,
    now: int,
) -> tuple[AgentSlotDraft, ...]:
    """
    A draft for every engine slot whose row is missing or shows something else.

    The engine owns the ids, scope, role, generation, status, session, nudge and
    rejection counts; every other column keeps what the loaded row holds.
    """
    rows = {row.id: row for row in loaded}
    streaks = {item.slot_id: item.count for item in state.reject_streaks}
    drafts: list[AgentSlotDraft] = []
    for slot in state.slots:
        row_id = store_slot_id(run_id, slot.id)
        row = rows.get(row_id)
        stored = (
            _as_draft(row)
            if row is not None
            else AgentSlotDraft(
                id=row_id,
                activation_id="",
                node_id="",
                scope_key="",
                roster_index=0,
                role=0,
                created_at=now,
                updated_at=now,
            )
        )
        owner = find_activation(state, slot.activation_id)
        projected = dataclasses.replace(
            stored,
            activation_id=store_activation_id(run_id, slot.activation_id),
            node_id=owner.node_id if owner is not None else slot.activation_id.split("|", 1)[0],
            scope_key=slot.id,
            roster_index=roster_index(slot.id),
            role=int(slot_role(slot.profile)),
            session_generation=slot.session_generation,
            status=SLOT_STATUS[slot.status],
            session_id=_created_session(state, slot.id),
            nudges=slot.nudges,
            consecutive_rejections=streaks.get(slot.id, 0),
        )
        if row is None or projected != stored:
            drafts.append(dataclasses.replace(projected, updated_at=now))
    return tuple(drafts)


def _created_session(state: engine.RunState, engine_slot_id: str) -> str | None:
    """The session the slot's latest create reported once it completed; ``None`` before."""
    key = slot_create_key(state, engine_slot_id)
    receipt = next((item for item in state.receipts if item.key == key), None)
    reported = receipt.payload.get("session_id") if receipt is not None else None
    return reported if isinstance(reported, str) else None


def _as_draft(row: AgentSlotState) -> AgentSlotDraft:
    names = {field.name for field in dataclasses.fields(AgentSlotDraft)}
    return AgentSlotDraft(**{name: getattr(row, name) for name in names})


__all__ = ["RunProjection", "project_run", "project_slots", "run_status_code", "slot_role"]
