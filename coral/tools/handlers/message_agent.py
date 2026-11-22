"""``coral_message_agent``: plan a ``MessageAgent`` delivery through the decision port."""

from __future__ import annotations

from collections.abc import Mapping

from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole, SlotRole
from coral.engine.machines.activation import find_activation
from coral.engine.machines.message import ORCHESTRATOR_SLOT_ID
from coral.engine.machines.slot import find_slot
from coral.engine.types import MessageAgent
from coral.tools import replies
from coral.tools.dispatch import EngineToolCall
from coral.tools.handlers.common import (
    pause_reason,
    run_stop,
    text_argument,
    unknown_arguments_message,
)
from coral.tools.port import Commit, Plan, Reply, RunSnapshot
from coral.tools.schemas import MESSAGE_AGENT_PARAMETERS, MESSAGE_TEXT_MAX, REPLY_TO_MAX

_PROPERTIES = MESSAGE_AGENT_PARAMETERS["properties"]
_FIELDS = frozenset(_PROPERTIES) if isinstance(_PROPERTIES, Mapping) else frozenset()


def plan(snapshot: RunSnapshot, *, call: EngineToolCall) -> Plan:
    """Answer one ``coral_message_agent`` call against ``snapshot``."""
    sender = _sender_slot(snapshot, call)
    if sender is None:
        return Reply(replies.not_run_member(), log="not a run member")
    fenced = _run_fence(snapshot)
    if fenced is not None:
        return fenced
    arguments = call.arguments
    unknown = [name for name in arguments if name not in _FIELDS]
    if unknown:
        message = unknown_arguments_message(unknown, _FIELDS)
        return Reply(replies.illegal_message("arguments", message), log="unknown arguments")
    text = text_argument(arguments.get("text"), MESSAGE_TEXT_MAX)
    if text is None:
        return Reply(
            replies.illegal_message("text", f"Give text of 1 to {MESSAGE_TEXT_MAX} characters."),
            log="no usable text",
        )
    reply_to = arguments.get("reply_to")
    if reply_to is not None:
        reply_to = text_argument(reply_to, REPLY_TO_MAX)
        if reply_to is None:
            return Reply(
                replies.illegal_message("reply_to", "reply_to must be a short string."),
                log="bad reply_to",
            )
    target = arguments.get("to")
    to_slot = _resolve_member(snapshot, target)
    if to_slot is None:
        return Reply(
            replies.illegal_message("to", "Use orchestrator or a member id from your brief."),
            log="unknown recipient",
        )
    command = MessageAgent(
        from_slot_id=sender,
        to_slot_id=to_slot,
        text=text,
        reply_to=reply_to if isinstance(reply_to, str) else None,
    )
    # message_id is the steer effect key shape the reducer will emit next.
    run_id = snapshot.state.run_id if isinstance(snapshot.state.run_id, str) else ""
    message_id = f"{run_id}:{snapshot.state.seq + 1}:steer:{to_slot}"
    return Commit((command,), replies.message_queued(message_id))


def _sender_slot(snapshot: RunSnapshot, call: EngineToolCall) -> str | None:
    binding = call.binding
    if (
        binding.role is not SessionBindingRole.STEP
        or binding.progress < SessionBindingProgress.ROW_CREATED
        or binding.run_id != snapshot.run.id
        or binding.workspace_id != snapshot.run.workspace_id
    ):
        return None
    if binding.slot_role is SlotRole.ORCHESTRATOR:
        if snapshot.run.orchestrator_session_id != binding.session_id:
            return None
        return ORCHESTRATOR_SLOT_ID
    if binding.slot_role is not SlotRole.STEP_AGENT or binding.slot_id is None:
        return None
    slot = find_slot(snapshot.state, binding.slot_id)
    if slot is None:
        return None
    return slot.id


def _resolve_member(snapshot: RunSnapshot, target: object) -> str | None:
    if not isinstance(target, str) or not target:
        return None
    if target in {"orchestrator", ORCHESTRATOR_SLOT_ID}:
        return ORCHESTRATOR_SLOT_ID
    if find_slot(snapshot.state, target) is not None:
        return target
    # node/profile#n (1-based roster index)
    if "/" in target and "#" in target:
        left, _, index_text = target.rpartition("#")
        node_profile, _, profile = left.rpartition("/")
        if not index_text.isdigit() or not node_profile or not profile:
            return None
        index = int(index_text) - 1
        if index < 0:
            return None
        for slot in snapshot.state.slots:
            owner = find_activation(snapshot.state, slot.activation_id)
            if (
                owner is not None
                and owner.node_id == node_profile
                and slot.profile == profile
                and slot.id.endswith(f":{index}")
            ):
                return slot.id
    # profile#n within a single open step (ambiguous when many nodes share a profile)
    if "#" in target and "/" not in target:
        profile, _, index_text = target.partition("#")
        if not index_text.isdigit():
            return None
        index = int(index_text) - 1
        matches = [
            slot
            for slot in snapshot.state.slots
            if slot.profile == profile and slot.id.endswith(f":{index}")
        ]
        if len(matches) == 1:
            return matches[0].id
    return None


def _run_fence(snapshot: RunSnapshot) -> Reply | None:
    stop = run_stop(snapshot)
    if stop == "cancelled":
        return Reply(replies.run_cancelled(), log="message after cancel")
    if stop == "finished":
        return Reply(replies.slot_closed(), log="run finished")
    if stop == "paused":
        return Reply(replies.run_paused(pause_reason(snapshot)))
    return None
