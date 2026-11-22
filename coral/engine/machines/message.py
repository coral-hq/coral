"""TLS-04 ``MessageAgent``, ``AssignAgents`` and ``AssignTask`` reducer handlers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from coral.engine.machines.activation import find_activation
from coral.engine.machines.run import refuse, refuse_unknown
from coral.engine.machines.slot import find_slot
from coral.engine.types import (
    ApplyResult,
    AssignAgents,
    AssignTask,
    AwaitAssignment,
    Effect,
    MessageAgent,
    Receipt,
    RecordMergeConflict,
    RunState,
    effect_key,
)
from coral.model.ir import CompiledGraph

# Matches ``coral.bridge.keys.ORCHESTRATOR_SLOT_ID``; engine must not import the bridge.
ORCHESTRATOR_SLOT_ID = "orchestrator"
MESSAGE_RATE_LIMIT = 10
MESSAGE_RATE_WINDOW = timedelta(minutes=1)
_CLOSING = frozenset({"evaluating", "closing", "closed"})
_STEER = "steer"
_MESSAGE_RECEIPT = "message"


def message_agent(
    graph: CompiledGraph, state: RunState, command: MessageAgent, now: datetime
) -> ApplyResult:
    """Emit a ``steer`` effect to the recipient, or refuse closing / rate / peer rules."""
    if state.status != "running":
        return refuse(state, "run_paused" if state.status == "paused" else "run_terminal")
    if command.from_slot_id == command.to_slot_id:
        return refuse(state, "tool.illegal")
    if (
        command.from_slot_id != ORCHESTRATOR_SLOT_ID
        and find_slot(state, command.from_slot_id) is None
    ):
        return refuse_unknown(state)
    recipient = (
        None
        if command.to_slot_id == ORCHESTRATOR_SLOT_ID
        else find_slot(state, command.to_slot_id)
    )
    if command.to_slot_id != ORCHESTRATOR_SLOT_ID and recipient is None:
        return refuse(state, "tool.illegal")
    if recipient is not None and recipient.status in _CLOSING:
        return refuse(state, "recipient_closing")
    if not _peer_allowed(graph, state, command.from_slot_id, command.to_slot_id):
        return refuse(state, "tool.illegal")
    if _rate_exceeded(state, command.from_slot_id, now):
        return refuse(state, "tool.illegal")
    run_id = state.run_id if isinstance(state.run_id, str) else ""
    seq = state.seq + 1
    header = _header(state, command.from_slot_id)
    body = f"{header}\n{command.text}"
    effect = Effect(
        effect_key=effect_key(run_id, seq, _STEER, command.to_slot_id),
        kind=_STEER,
        subject=command.to_slot_id,
        payload={
            "text": body,
            "from_slot_id": command.from_slot_id,
            "reply_to": command.reply_to,
        },
    )
    receipt = Receipt(
        key=f"{_MESSAGE_RECEIPT}:{command.from_slot_id}:{seq}",
        payload={"sent_at": now.astimezone(UTC).isoformat(), "to": command.to_slot_id},
    )
    updated = state.model_copy(
        update={
            "seq": seq,
            "effects": (*state.effects, effect),
            "receipts": (*state.receipts, receipt),
        }
    )
    return ApplyResult(state=updated, effects=(effect,), receipt_key=receipt.key)


def assign_agents(state: RunState, command: AssignAgents) -> ApplyResult:
    """Staff an activation waiting for assignment; identical repeats return the receipt."""
    owner = find_activation(state, command.activation_id)
    if owner is None:
        return refuse(state, "tool.illegal")
    if owner.sub_state != "awaiting_assignment":
        return refuse(state, "tool.illegal")
    receipt_key = f"assign_agents:{command.activation_id}"
    prior = next((item for item in state.receipts if item.key == receipt_key), None)
    wanted = dict(command.assignments)
    if prior is not None:
        previous = prior.payload.get("assignments")
        if previous == [[profile, count] for profile, count in command.assignments]:
            return ApplyResult(state=state, receipt_key=receipt_key)
        return refuse(state, "tool.illegal")
    if not wanted or any(count < 1 or count > 20 for count in wanted.values()):
        return refuse(state, "tool.illegal")
    seq = state.seq + 1
    receipt = Receipt(
        key=receipt_key,
        payload={
            "assignments": [[profile, count] for profile, count in command.assignments],
            "reason": command.reason,
        },
    )
    cleared = owner.model_copy(update={"sub_state": None})
    activations = tuple(cleared if item.id == owner.id else item for item in state.activations)
    updated = state.model_copy(
        update={"seq": seq, "activations": activations, "receipts": (*state.receipts, receipt)}
    )
    return ApplyResult(state=updated, receipt_key=receipt_key)


def record_merge_conflict(state: RunState, command: RecordMergeConflict) -> ApplyResult:
    """Open merge_conflict on an activation so assign_task may re-task a member."""
    owner = find_activation(state, command.activation_id)
    if owner is None or owner.status == "closed":
        return refuse(state, "tool.illegal")
    seq = state.seq + 1
    patched = owner.model_copy(
        update={
            "sub_state": "merge_conflict",
            "conflict_files": command.files,
            "resolver_slot_id": None,
        }
    )
    activations = tuple(patched if item.id == owner.id else item for item in state.activations)
    receipt = Receipt(
        key=f"merge_conflict:{owner.id}:{seq}",
        payload={"files": list(command.files)},
    )
    updated = state.model_copy(
        update={"seq": seq, "activations": activations, "receipts": (*state.receipts, receipt)}
    )
    return ApplyResult(state=updated, receipt_key=receipt.key)


def await_assignment(state: RunState, command: AwaitAssignment) -> ApplyResult:
    """Mark an activation as waiting for coral_assign_agents."""
    owner = find_activation(state, command.activation_id)
    if owner is None or owner.status == "closed":
        return refuse(state, "tool.illegal")
    seq = state.seq + 1
    patched = owner.model_copy(update={"sub_state": "awaiting_assignment"})
    activations = tuple(patched if item.id == owner.id else item for item in state.activations)
    receipt = Receipt(key=f"await_assignment:{owner.id}:{seq}", payload={})
    updated = state.model_copy(
        update={"seq": seq, "activations": activations, "receipts": (*state.receipts, receipt)}
    )
    return ApplyResult(state=updated, receipt_key=receipt.key)


def assign_task(state: RunState, command: AssignTask) -> ApplyResult:
    """Re-task a merge_conflict member with a ``[Coral task]`` steer effect."""
    owner = find_activation(state, command.activation_id)
    if owner is None or owner.sub_state != "merge_conflict":
        return refuse(state, "tool.illegal")
    member = find_slot(state, command.member_slot_id)
    if member is None or member.activation_id != owner.id:
        return refuse(state, "tool.illegal")
    if member.status in _CLOSING:
        return refuse(state, "recipient_closing")
    if owner.resolver_slot_id is not None and owner.resolver_slot_id != member.id:
        return refuse(state, "tool.illegal")
    run_id = state.run_id if isinstance(state.run_id, str) else ""
    seq = state.seq + 1
    files = ", ".join(owner.conflict_files) if owner.conflict_files else "(unspecified)"
    text = (
        f"[Coral task]\nResolve merge conflicts in your worktree.\n"
        f"Files: {files}\n\n{command.task}\n\nReason: {command.reason}"
    )
    effect = Effect(
        effect_key=effect_key(run_id, seq, _STEER, member.id),
        kind=_STEER,
        subject=member.id,
        payload={"text": text, "kind": "task", "activation_id": owner.id},
    )
    receipt = Receipt(
        key=f"assign_task:{owner.id}:{member.id}:{seq}",
        payload={"member": member.id, "task": command.task},
    )
    resolving = owner.model_copy(update={"resolver_slot_id": member.id})
    activations = tuple(resolving if item.id == owner.id else item for item in state.activations)
    updated = state.model_copy(
        update={
            "seq": seq,
            "activations": activations,
            "effects": (*state.effects, effect),
            "receipts": (*state.receipts, receipt),
        }
    )
    return ApplyResult(state=updated, effects=(effect,), receipt_key=receipt.key)


def _peer_allowed(
    graph: CompiledGraph, state: RunState, from_slot_id: str, to_slot_id: str
) -> bool:
    if from_slot_id == ORCHESTRATOR_SLOT_ID or to_slot_id == ORCHESTRATOR_SLOT_ID:
        return True
    sender = find_slot(state, from_slot_id)
    recipient = find_slot(state, to_slot_id)
    if sender is None or recipient is None:
        return False
    if sender.activation_id == recipient.activation_id:
        return True
    from_owner = find_activation(state, sender.activation_id)
    to_owner = find_activation(state, recipient.activation_id)
    if from_owner is None or to_owner is None:
        return False
    return _same_region(graph, from_owner.node_id, to_owner.node_id)


def _same_region(graph: CompiledGraph, left: str, right: str) -> bool:
    for region in graph.analysis.regions:
        nodes = set(region.node_ids) | {region.split_node_id, region.join_node_id}
        if left in nodes and right in nodes:
            return True
    return False


def _rate_exceeded(state: RunState, from_slot_id: str, now: datetime) -> bool:
    floor = now.astimezone(UTC) - MESSAGE_RATE_WINDOW
    count = 0
    prefix = f"{_MESSAGE_RECEIPT}:{from_slot_id}:"
    for receipt in state.receipts:
        if not receipt.key.startswith(prefix):
            continue
        raw = receipt.payload.get("sent_at")
        if not isinstance(raw, str):
            continue
        try:
            sent = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if sent.tzinfo is None:
            sent = sent.replace(tzinfo=UTC)
        if sent >= floor:
            count += 1
    return count >= MESSAGE_RATE_LIMIT


def _header(state: RunState, from_slot_id: str) -> str:
    if from_slot_id == ORCHESTRATOR_SLOT_ID:
        return "[Coral message from orchestrator (Orchestrator)]"
    slot = find_slot(state, from_slot_id)
    if slot is None:
        return "[Coral message from unknown]"
    owner = find_activation(state, slot.activation_id)
    node = owner.node_id if owner is not None else "step"
    index = from_slot_id.rsplit(":", 1)[-1]
    member = f"{node}/{slot.profile}#{int(index) + 1}" if index.isdigit() else slot.profile
    title = slot.profile.replace("_", " ").title()
    return f"[Coral message from {member} ({title})]"
