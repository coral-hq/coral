"""Reducer effects and bridge items as ``coral_work`` rows: pure and deterministic.

A row rides the same commit as the engine entry that emitted its effect, keyed by
that effect's key, so a repeat of the commit never queues it twice. Slot effects
carry the store slot id and generation, so the drainer can fence stale work. A
gate's publish and withdraw are bridge rows naming only the visit.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from coral.bridge.config import (
    MAX_PAYLOAD_BYTES,
    REGATHER_BUCKET_S,
    ceil_epoch_seconds,
    epoch_seconds,
)
from coral.bridge.gate_rows import gate_publish_draft, gate_withdraw_draft
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
from coral.bridge.messages import (
    DecisionMessage,
    brief_text,
    decision_request_text,
    nudge_text,
    orchestrator_title,
    salvage_note,
)
from coral.bridge.projection import slot_role
from coral.db.enum_codecs import SlotRole
from coral.engine import types as engine
from coral.engine.machines.activation import find_activation
from coral.engine.machines.slot import find_slot
from coral.model.ir import CompiledGraph
from coral.signals.turn_facts import EdgeFacts
from coral.slots.executors import CANCEL_SESSIONS, CLOSE_SLOT, CREATE_SESSION, SEND_INPUT
from coral.stores.protocols import WorkItemDraft
from coral.tools.catalog import ORCHESTRATOR_STANCE, STEP_STANCES

# Effects whose outcome is fed back to the engine as a completion or a failure.
FED_KINDS = frozenset(
    {"create_session", "send_input", "close_slot", "nudge", "retry_step", "runner_lost"}
)
# Effects that queue no work yet, and why; each is logged when it is committed.
UNMAPPED_KINDS: Mapping[str, str] = MappingProxyType(
    {
        "notify": "alerts come from the commit; a decision's reminder goes to the orchestrator",
        "arm_timer": "timer rows come from the run's armed timers",
    }
)
# The row of a ``retry_step``: fence the old session, salvage and reset (``coral.recovery``).
RECOVERY_RESTART = "recovery.restart"
# The row of a ``runner_lost``: bring the lost runner back in its session (``coral.recovery``).
RECOVERY_WAKE = "recovery.wake"
TIMER = "timer"
RUN_RESYNC = "run_resync"
TURN_FACT = "turn_fact"
# The bridge row of a message to the orchestrator about a decision.
DECISION_ITEM = "decision"
# The idempotency key of a run's one recurring resync row.
_RESYNC_KEY = "resync"
# A resync result's epoch second by which the row should run again (a liveness grace ends).
NEXT_RESYNC_AT = "next_resync_at"
_SCOPE_KEY_CHARS = 512
_ORCHESTRATOR_OWNER = f"slot:{ORCHESTRATOR_SLOT_ID}"


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
            ctx.graph,
            ctx.state,
            effect.subject,
            request_preview=ctx.request_preview,
            salvage=salvage_note(effect.payload),
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
    if effect.kind == "retry_step":
        return _restart(ctx, effect)
    if effect.kind == "runner_lost":
        return _wake(ctx, effect)
    if effect.kind == "publish_gate":
        return gate_publish_draft(ctx, effect)
    if effect.kind == "withdraw_gate":
        return gate_withdraw_draft(ctx, effect)
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
    """
    The create of the run's orchestrator session, titled after the run.

    It is due at once, so it runs before the request queued beside it.
    """
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
        owner_key=_ORCHESTRATOR_OWNER,
        available_at=0,
    )
    return _checked(draft)


def decision_message_draft(
    ctx: MapContext,
    *,
    session_id: str,
    decision_id: str,
    message: DecisionMessage,
    key: str,
) -> WorkItemDraft:
    """A request, reminder or re-request of an open decision, sent to the orchestrator."""
    text = decision_request_text(ctx.graph, ctx.state, decision_id, kind=message)
    payload = {
        "effect_type": SEND_INPUT,
        "effect_key": key,
        "bridge_item": DECISION_ITEM,
        "decision_id": decision_id,
        "session_id": session_id,
        "text": text,
        "kind": "brief" if message == "request" else "nudge",
    }
    owner = find_activation(ctx.state, decision_id)
    draft = WorkItemDraft.effect(
        run_id=ctx.run_id,
        idempotency_key=key,
        payload=payload,
        node_id=owner.node_id if owner is not None else None,
        scope_key=decision_id if len(decision_id) <= _SCOPE_KEY_CHARS else None,
        slot_generation=ORCHESTRATOR_GENERATION,
        owner_key=_ORCHESTRATOR_OWNER,
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


def resync_draft(run_id: str, *, available_at: int = 0) -> WorkItemDraft:
    """The run's one ``run_resync`` row; rescheduling it never queues a second one."""
    return WorkItemDraft.signal(
        run_id=run_id,
        idempotency_key=_RESYNC_KEY,
        payload={"effect_type": RUN_RESYNC},
        available_at=available_at,
    )


def edge_signal_key(session_id: str, edge: EdgeFacts) -> str:
    """One signal per published edge: a repeat of the edge writes no second row."""
    tail = edge.response_id or edge.origin
    return f"sig:{session_id}:{tail}:{edge.status}:{edge.observed_at_ms}"


def regather_key(session_id: str, now_s: int) -> str:
    """One re-gather per session in each five-minute bucket."""
    return f"sig:{session_id}:resync:{now_s // REGATHER_BUCKET_S}"


def boot_regather_key(session_id: str, boot_id: str) -> str:
    """A session's first re-gather in a process, whatever re-gather the last one queued."""
    return f"sig:{session_id}:boot:{boot_id}"


def turn_signal_draft(
    *,
    run_id: str,
    session_id: str,
    engine_slot_id: str,
    generation: int,
    idempotency_key: str,
    edge: EdgeFacts | None,
    available_at: int,
) -> WorkItemDraft:
    """
    The ``turn_fact`` signal of a session's turn end, or of a re-gather without an edge.

    It is fenced by the slot's generation. An edge whose error text does not fit the
    payload keeps a shorter message.
    """
    while True:
        payload: dict[str, Any] = {
            "effect_type": TURN_FACT,
            "session_id": session_id,
            "slot_id": store_slot_id(run_id, engine_slot_id),
            "engine_slot_id": engine_slot_id,
            "generation": generation,
        }
        if edge is not None:
            payload["edge"] = edge.payload()
        draft = WorkItemDraft.signal(
            run_id=run_id,
            idempotency_key=idempotency_key,
            payload=payload,
            scope_key=engine_slot_id if len(engine_slot_id) <= _SCOPE_KEY_CHARS else None,
            owner_key=slot_owner_key(run_id, engine_slot_id),
            slot_generation=generation,
            available_at=available_at,
        )
        fits = len(draft.payload.encode()) <= MAX_PAYLOAD_BYTES
        if fits or edge is None or not edge.error_message:
            return _checked(draft)
        message = edge.error_message
        edge = dataclasses.replace(edge, error_message=message[: len(message) // 2])


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


def _restart(ctx: MapContext, effect: engine.Effect) -> WorkItemDraft:
    """
    The restart of a retried slot, fenced by the slot's new generation.

    It names the session of the slot's latest create, still the old generation's,
    whether that session wrote the run worktree, and the slot's newest close whose
    commit never reached a receipt: a commit it made is still this step's own.
    """
    slot = find_slot(ctx.state, effect.subject)
    generation = effect.payload.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool):
        generation = slot.session_generation if slot is not None else 1
    expected_head = effect.payload.get("expected_head")
    fields = {
        "engine_slot_id": effect.subject,
        "generation": generation,
        "session_id": slot_session_id(ctx.workspace_id, ctx.state, effect.subject),
        "writer": slot is not None and slot_role(slot.profile) == SlotRole.STEP_AGENT,
        "expected_head": expected_head if isinstance(expected_head, str) else None,
        "close_key": _unreported_close(ctx.state, effect.subject),
    }
    return _slot_draft(ctx, effect, RECOVERY_RESTART, fields, generation=generation)


def _wake(ctx: MapContext, effect: engine.Effect) -> WorkItemDraft:
    """
    The wake of a slot's lost runner, fenced by the generation that lost it.

    It names the lost session and runner as the engine saw them.
    """
    slot = find_slot(ctx.state, effect.subject)
    generation = effect.payload.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool):
        generation = slot.session_generation if slot is not None else 1
    session_id = effect.payload.get("session_id")
    runner_id = effect.payload.get("runner_id")
    fields = {
        "engine_slot_id": effect.subject,
        "generation": generation,
        "session_id": (
            session_id
            if isinstance(session_id, str)
            else slot_session_id(ctx.workspace_id, ctx.state, effect.subject)
        ),
        "runner_id": runner_id if isinstance(runner_id, str) else None,
    }
    return _slot_draft(ctx, effect, RECOVERY_WAKE, fields, generation=generation)


def _unreported_close(state: engine.RunState, engine_slot_id: str) -> str | None:
    """The key of the slot's newest close, unless a receipt recorded the commit it made."""
    close = next(
        (
            effect
            for effect in reversed(state.effects)
            if effect.kind == "close_slot" and effect.subject == engine_slot_id
        ),
        None,
    )
    if close is None:
        return None
    for receipt in state.receipts:
        commit = receipt.payload.get("commit")
        if receipt.key == close.effect_key and isinstance(commit, str) and commit:
            return None
    return close.effect_key


def _message(ctx: MapContext, effect: engine.Effect, kind: str, text: str) -> dict[str, Any]:
    return {
        "session_id": slot_session_id(ctx.workspace_id, ctx.state, effect.subject),
        "text": text,
        "kind": kind,
    }


def _slot_draft(
    ctx: MapContext,
    effect: engine.Effect,
    effect_type: str,
    fields: Mapping[str, Any],
    *,
    generation: int | None = None,
) -> WorkItemDraft:
    """:param generation: The row's slot generation; the slot's current one by default."""
    slot = find_slot(ctx.state, effect.subject)
    if generation is None and slot is not None:
        generation = slot.session_generation
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
        slot_generation=generation,
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
    "DECISION_ITEM",
    "FED_KINDS",
    "NEXT_RESYNC_AT",
    "RECOVERY_RESTART",
    "RECOVERY_WAKE",
    "RUN_RESYNC",
    "TIMER",
    "TURN_FACT",
    "UNMAPPED_KINDS",
    "MapContext",
    "MappedPayloadTooLarge",
    "UnsupportedStance",
    "anchor_create_draft",
    "boot_regather_key",
    "decision_message_draft",
    "edge_signal_key",
    "map_effect",
    "orchestrator_create_draft",
    "regather_key",
    "resync_draft",
    "timer_draft",
    "turn_signal_draft",
]
