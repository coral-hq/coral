"""Reducer effects and bridge items as ``coral_work`` rows: pure and deterministic.

A row rides the same commit as the engine entry that emitted its effect, keyed by
that effect's key, so a repeat of the commit never queues it twice. Slot effects
carry the store slot id and generation, so the drainer can fence stale work.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from coral.bridge.config import MAX_PAYLOAD_BYTES, ceil_epoch_seconds, epoch_seconds
from coral.bridge.keys import (
    ORCHESTRATOR_GENERATION,
    ORCHESTRATOR_SLOT_ID,
    anchor_effect_key,
    orchestrator_effect_key,
    roster_index,
    slot_owner_key,
    slot_session_id,
    store_slot_id,
    timer_work_key,
)
from coral.bridge.messages import brief_text, nudge_text, orchestrator_title
from coral.bridge.projection import slot_role
from coral.db.enum_codecs import SlotRole
from coral.engine import types as engine
from coral.engine.machines.activation import find_activation
from coral.engine.machines.slot import find_slot
from coral.model.ir import CompiledGraph
from coral.slots.executors import CANCEL_SESSIONS, CLOSE_SLOT, CREATE_SESSION, SEND_INPUT
from coral.stores.protocols import WorkItemDraft
from coral.tools.catalog import ORCHESTRATOR_STANCE, STEP_STANCES

# Effects whose outcome is fed back to the engine as a completion or a failure.
FED_KINDS = frozenset({"create_session", "send_input", "close_slot", "nudge"})
# Effects that queue no work yet, and why; each is logged when it is committed.
UNMAPPED_KINDS: Mapping[str, str] = MappingProxyType(
    {
        "publish_gate": "gates are not published yet",
        "withdraw_gate": "gates are not published yet",
        "notify": "notifications are not delivered yet",
        "runner_lost": "lost runners are not restarted yet",
        "retry_step": "step retries are not run yet",
        "arm_timer": "timer rows come from the run's armed timers",
    }
)
TIMER = "timer"
_SCOPE_KEY_CHARS = 512


class MappedPayloadTooLarge(ValueError):
    """A mapped work payload would not fit its column; messages are bounded so it cannot."""


class UnsupportedStance(ValueError):
    """A step's roster profile is not a step stance; start refuses such a workflow."""


@dataclass(frozen=True)
class MapContext:
    """What a commit's effects are mapped against.

    ``state`` is the state after the entry that emitted the effects, and ``now`` that
    commit's time; a row mapped again later from a newer state may differ.
    """

    workspace_id: int
    run_id: str
    graph: CompiledGraph
    state: engine.RunState
    request_preview: str
    title: str
    now: datetime


def map_effect(ctx: MapContext, effect: engine.Effect) -> WorkItemDraft | None:
    """The work row an effect queues, or ``None`` for a kind with no executor."""
    if effect.kind == "create_session":
        return _create(ctx, effect)
    if effect.kind == "send_input":
        text = brief_text(
            ctx.graph, ctx.state, effect.subject, request_preview=ctx.request_preview
        )
        return _slot_draft(ctx, effect, SEND_INPUT, _message(ctx, effect, "brief", text))
    if effect.kind == "nudge":
        # A nudge held while the run is paused is delivered after the resume.
        reason = "resume" if ctx.state.status == "paused" else effect.payload.get("reason")
        text = nudge_text(ctx.state, effect.subject, reason if isinstance(reason, str) else None)
        return _slot_draft(ctx, effect, SEND_INPUT, _message(ctx, effect, "nudge", text))
    if effect.kind == "close_slot":
        fields = {
            "session_id": slot_session_id(ctx.workspace_id, ctx.state, effect.subject),
            "interrupt": effect.payload.get("interrupt") is not False,
            "closed_label": effect.payload.get("closed_label") is not False,
        }
        return _slot_draft(ctx, effect, CLOSE_SLOT, fields)
    if effect.kind == "cancel_sessions":
        # A slot whose create is in flight is cancelled by the session that create makes.
        fields = {
            "session_id": slot_session_id(ctx.workspace_id, ctx.state, effect.subject),
            "closed_label": effect.payload.get("closed_label") is not False,
        }
        return _slot_draft(ctx, effect, CANCEL_SESSIONS, fields)
    return None


def anchor_create_draft(ctx: MapContext) -> WorkItemDraft:
    """The run's anchor session create, due at once so it runs before the steps."""
    key = anchor_effect_key(ctx.run_id)
    payload = {
        "effect_type": CREATE_SESSION,
        "effect_key": key,
        "bridge_item": "anchor",
        "role": "anchor",
    }
    return _checked(WorkItemDraft.effect(run_id=ctx.run_id, idempotency_key=key, payload=payload))


def orchestrator_create_draft(ctx: MapContext) -> WorkItemDraft:
    """The create of the run's orchestrator session, titled after the run."""
    key = orchestrator_effect_key(ctx.run_id)
    payload = {
        "effect_type": CREATE_SESSION,
        "effect_key": key,
        "bridge_item": "orchestrator",
        "role": "step",
        "stance": ORCHESTRATOR_STANCE,
        "engine_slot_id": ORCHESTRATOR_SLOT_ID,
        "slot_role": SlotRole.ORCHESTRATOR.name.lower(),
        "generation": ORCHESTRATOR_GENERATION,
        "title": orchestrator_title(ctx.title),
    }
    draft = WorkItemDraft.effect(
        run_id=ctx.run_id,
        idempotency_key=key,
        payload=payload,
        scope_key=ORCHESTRATOR_SLOT_ID,
        slot_generation=ORCHESTRATOR_GENERATION,
        owner_key=f"slot:{ORCHESTRATOR_SLOT_ID}",
        available_at=epoch_seconds(ctx.now),
    )
    return _checked(draft)


def timer_draft(run_id: str, timer: engine.Timer) -> WorkItemDraft:
    """The row that fires an armed timer, due no earlier than its deadline."""
    payload = {"effect_type": TIMER, "timer_key": timer.key, "due_at": timer.due_at.isoformat()}
    draft = WorkItemDraft.timer(
        run_id=run_id,
        idempotency_key=timer_work_key(timer),
        available_at=ceil_epoch_seconds(timer.due_at),
        payload=payload,
        scope_key=timer.subject if len(timer.subject) <= _SCOPE_KEY_CHARS else None,
    )
    return _checked(draft)


def _create(ctx: MapContext, effect: engine.Effect) -> WorkItemDraft:
    slot = find_slot(ctx.state, effect.subject)
    profile = slot.profile if slot is not None else str(effect.payload.get("profile", ""))
    # The stance picks the session's bundle and tools, so only a step stance gets one.
    if profile not in STEP_STANCES:
        raise UnsupportedStance(f"slot {effect.subject} has no step stance")
    fields = {
        "role": "step",
        "stance": profile,
        "workflow_slug": ctx.graph.workflow_id,
        "node_id": _node_id(ctx, effect),
        "roster_index": roster_index(effect.subject),
        "engine_slot_id": effect.subject,
        "slot_role": slot_role(profile).name.lower(),
        "generation": slot.session_generation if slot is not None else 1,
    }
    return _slot_draft(ctx, effect, CREATE_SESSION, fields)


def _message(ctx: MapContext, effect: engine.Effect, kind: str, text: str) -> dict[str, Any]:
    return {
        "session_id": slot_session_id(ctx.workspace_id, ctx.state, effect.subject),
        "text": text,
        "kind": kind,
    }


def _slot_draft(
    ctx: MapContext, effect: engine.Effect, effect_type: str, fields: Mapping[str, Any]
) -> WorkItemDraft:
    slot = find_slot(ctx.state, effect.subject)
    payload = {
        "effect_type": effect_type,
        "effect_key": effect.effect_key,
        "engine_kind": effect.kind,
        **fields,
        "slot_id": store_slot_id(ctx.run_id, effect.subject),
    }
    draft = WorkItemDraft.effect(
        run_id=ctx.run_id,
        idempotency_key=effect.effect_key,
        payload=payload,
        node_id=_node_id(ctx, effect),
        scope_key=effect.subject,
        slot_generation=slot.session_generation if slot is not None else None,
        owner_key=slot_owner_key(ctx.run_id, effect.subject),
        available_at=epoch_seconds(ctx.now),
    )
    return _checked(draft)


def _node_id(ctx: MapContext, effect: engine.Effect) -> str | None:
    slot = find_slot(ctx.state, effect.subject)
    owner = find_activation(ctx.state, slot.activation_id) if slot is not None else None
    if owner is not None:
        return owner.node_id
    node_id = effect.payload.get("node_id")
    return node_id if isinstance(node_id, str) else None


def _checked(draft: WorkItemDraft) -> WorkItemDraft:
    if len(draft.payload.encode()) > MAX_PAYLOAD_BYTES:
        raise MappedPayloadTooLarge(f"work payload {draft.id} is over {MAX_PAYLOAD_BYTES} bytes")
    return draft


__all__ = [
    "FED_KINDS",
    "TIMER",
    "UNMAPPED_KINDS",
    "MapContext",
    "MappedPayloadTooLarge",
    "UnsupportedStance",
    "anchor_create_draft",
    "map_effect",
    "orchestrator_create_draft",
    "timer_draft",
]
