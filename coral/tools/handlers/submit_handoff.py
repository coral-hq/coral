"""``coral_submit_handoff``: a pure planner over one run snapshot.

Checks run in a fixed order, first match wins: membership, session
generation, a closed slot (the receipt of an earlier handoff), run status,
slot readiness, a handoff already being evaluated, then the arguments one
field at a time. Only an argument error is counted against the slot; the
other refusals write nothing. A valid handoff commits ``HandoffReceived`` and
``HandoffEvaluated`` together.
"""

from __future__ import annotations

import heapq
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from coral.db.enum_codecs import (
    RunStatus,
    SessionBindingProgress,
    SessionBindingRole,
    SlotRole,
    decode_run_pause_reason,
)
from coral.engine.lifecycle import REJECTED_CALL_LIMIT
from coral.engine.machines.activation import choosable_labels, find_activation, routes_by_label
from coral.engine.machines.slot import find_slot
from coral.engine.types import HandoffEvaluated, HandoffReceived, RejectionObserved, Slot
from coral.tools import replies
from coral.tools.dispatch import EngineToolCall
from coral.tools.port import Commit, Plan, Reply, RunSnapshot
from coral.tools.schemas import (
    ARTIFACT_MAX,
    ARTIFACTS_MAX,
    BLOCKED_REASON_MAX,
    HANDOFF_BODY_MAX_BYTES,
    HANDOFF_INVALID,
    HANDOFF_KIND,
    HANDOFF_STATUSES,
    REPORT_MAX,
    SUBMIT_HANDOFF_PARAMETERS,
    ToolReply,
)

_PROPERTIES = SUBMIT_HANDOFF_PARAMETERS["properties"]
_FIELDS = frozenset(_PROPERTIES) if isinstance(_PROPERTIES, Mapping) else frozenset()
_SCHEMA_REQUIRED = SUBMIT_HANDOFF_PARAMETERS["required"]
_REQUIRED = (
    tuple(str(name) for name in _SCHEMA_REQUIRED) if isinstance(_SCHEMA_REQUIRED, list) else ()
)
# An explicit null for one of these reads as leaving it out.
_OPTIONAL = _FIELDS - frozenset(_REQUIRED)
_NOT_READY = frozenset({"pending", "session_created", "briefed"})
_FINISHED = frozenset({int(RunStatus.COMPLETED), int(RunStatus.FAILED)})
# Unknown argument names are never echoed raw: at most this many plain names are listed.
_UNKNOWN_LISTED = 5
_PLAIN_NAME = re.compile(r"[A-Za-z0-9_]{1,32}")


@dataclass(frozen=True)
class _Handoff:
    """Valid arguments: the canonical body the engine stores, and what routes it."""

    body: str
    status: str
    label: str | None


def plan(snapshot: RunSnapshot, *, call: EngineToolCall) -> Plan:
    """
    Answer one ``coral_submit_handoff`` call against ``snapshot``.

    :returns: A :class:`Reply` that writes nothing, or a :class:`Commit` of the
        handoff (or of a counted ``handoff.invalid`` observation).
    """
    binding = call.binding
    slot = _member_slot(snapshot, call)
    if slot is None:
        return Reply(replies.not_run_member(), log="not a step of this run")
    if binding.session_generation < slot.session_generation:
        return Reply(replies.superseded(), log="superseded handoff")
    if binding.session_generation > slot.session_generation:
        # A stopped run says stop; only a live one asks the newer session to retry.
        return _run_fence(snapshot) or Reply(
            replies.retry_shortly(), log="binding ahead of the engine"
        )
    if slot.status in {"closing", "closed"}:
        handoff = _checked(snapshot, slot, call.arguments)
        if isinstance(handoff, _Handoff) and handoff.body == slot.handoff:
            return Reply(replies.accepted(handoff.status, duplicate=True))
        return Reply(replies.slot_closed(), log="slot already closed")
    fenced = _run_fence(snapshot)
    if fenced is not None:
        return fenced
    if slot.status in _NOT_READY:
        return Reply(replies.retry_shortly(), log="slot not ready")
    if slot.status == "evaluating" and slot.handoff is not None:
        return Reply(replies.evaluating(), log="a handoff is being evaluated")
    handoff = _checked(snapshot, slot, call.arguments)
    if isinstance(handoff, ToolReply):
        if _streak(snapshot, slot) + 1 >= REJECTED_CALL_LIMIT:
            # This observation pauses the run, so the reply says stop.
            handoff = replies.stopping(handoff, "rejected_calls")
        observed = RejectionObserved(slot_id=slot.id, code=HANDOFF_INVALID)
        return Commit((observed,), handoff, observation=True)
    generation = binding.session_generation
    return Commit(
        (
            HandoffReceived(
                slot_id=slot.id,
                body=handoff.body,
                session_generation=generation,
                label=handoff.label,
            ),
            HandoffEvaluated(
                slot_id=slot.id,
                outcome="accepted" if handoff.status == "done" else "blocked",
                session_generation=generation,
            ),
        ),
        replies.accepted(handoff.status),
    )


def _member_slot(snapshot: RunSnapshot, call: EngineToolCall) -> Slot | None:
    """The engine slot of a created step session of this run; never an orchestrator's."""
    binding = call.binding
    if (
        binding.role is not SessionBindingRole.STEP
        or binding.slot_role is SlotRole.ORCHESTRATOR
        or binding.progress < SessionBindingProgress.ROW_CREATED
        or binding.run_id != snapshot.run.id
        or binding.workspace_id != snapshot.run.workspace_id
        or binding.slot_id is None
    ):
        return None
    return find_slot(snapshot.state, binding.slot_id)


def _run_fence(snapshot: RunSnapshot) -> Reply | None:
    """Refuse a cancelled, finished or paused run, by its store row or its engine state."""
    stored, engine = snapshot.run.status, snapshot.state.status
    if stored == RunStatus.CANCELLED or engine == "cancelled":
        return Reply(replies.run_cancelled(), log="handoff arrived after cancel")
    if stored in _FINISHED or engine in {"completed", "failed"}:
        return Reply(replies.slot_closed(), log="run finished")
    if stored == RunStatus.PAUSED or engine == "paused":
        return Reply(replies.run_paused(_pause_reason(snapshot)))
    return None


def _streak(snapshot: RunSnapshot, slot: Slot) -> int:
    """The slot's counted rejections in a row."""
    return next(
        (item.count for item in snapshot.state.reject_streaks if item.slot_id == slot.id), 0
    )


def _pause_reason(snapshot: RunSnapshot) -> str | None:
    """The store's pause reason (drift and budget pauses live only there), else the engine's."""
    code = snapshot.run.pause_reason
    if snapshot.run.status == RunStatus.PAUSED and code is not None:
        try:
            return decode_run_pause_reason(code)
        except ValueError:
            return None
    causes = snapshot.state.causes
    return causes[0].reason if snapshot.state.status == "paused" and causes else None


def _checked(
    snapshot: RunSnapshot, slot: Slot, arguments: Mapping[str, object]
) -> _Handoff | ToolReply:
    """The handoff the arguments describe, or the counted refusal of the first bad field."""
    arguments = {
        name: value
        for name, value in arguments.items()
        if not (value is None and name in _OPTIONAL)
    }
    if arguments.get("kind", HANDOFF_KIND) != HANDOFF_KIND:
        return replies.invalid_handoff("kind", "Only handoff is accepted.", (HANDOFF_KIND,))
    unknown = [name for name in arguments if name not in _FIELDS]
    if unknown:
        return replies.invalid_handoff("arguments", _unknown_message(unknown))
    for name in _REQUIRED:
        if name not in arguments:
            return replies.invalid_handoff(name, "This argument is required.")
    if arguments["activation_id"] != slot.activation_id:
        return replies.invalid_handoff(
            "activation_id",
            "Use the activation id from your brief.",
            (slot.activation_id,),
        )
    status = arguments["status"]
    if not isinstance(status, str) or status not in HANDOFF_STATUSES:
        return replies.invalid_handoff("status", "Use done or blocked.", HANDOFF_STATUSES)
    report = _text(arguments["report"], REPORT_MAX)
    if report is None:
        return replies.invalid_handoff(
            "report", f"Write a report of 1 to {REPORT_MAX} characters."
        )
    blocked_reason: str | None = None
    if status == "blocked":
        blocked_reason = _text(arguments.get("blocked_reason"), BLOCKED_REASON_MAX)
        if blocked_reason is None:
            return replies.invalid_handoff(
                "blocked_reason",
                f"A blocked handoff needs a reason of 1 to {BLOCKED_REASON_MAX} characters.",
            )
    elif "blocked_reason" in arguments:
        return replies.invalid_handoff("blocked_reason", "Only a blocked handoff has a reason.")
    label = _label(snapshot, slot, status, arguments)
    if isinstance(label, ToolReply):
        return label
    artifacts = _artifacts(arguments.get("artifacts", []))
    if artifacts is None:
        return replies.invalid_handoff(
            "artifacts",
            f"Give at most {ARTIFACTS_MAX} paths of 1 to {ARTIFACT_MAX} characters each.",
        )
    fields: dict[str, object] = {
        "activation_id": slot.activation_id,
        "status": status,
        "report": report,
    }
    if blocked_reason is not None:
        fields["blocked_reason"] = blocked_reason
    if label is not None:
        fields["label"] = label
    if artifacts:
        fields["artifacts"] = artifacts
    body = _json(fields)
    if len(body.encode("utf-8")) > HANDOFF_BODY_MAX_BYTES:
        return _oversized(fields)
    return _Handoff(body=body, status=status, label=label)


def _json(fields: Mapping[str, object]) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _oversized(fields: dict[str, object]) -> ToolReply:
    """Name what to shrink: the part that alone makes the body too big, or both."""
    limit = HANDOFF_BODY_MAX_BYTES
    without_artifacts = {name: value for name, value in fields.items() if name != "artifacts"}
    report_too_big = len(_json(without_artifacts).encode("utf-8")) > limit
    artifacts_too_big = len(_json({**fields, "report": ""}).encode("utf-8")) > limit
    if report_too_big and not artifacts_too_big:
        return replies.invalid_handoff(
            "report", f"The handoff is over {limit} bytes; shorten the report."
        )
    if artifacts_too_big and not report_too_big:
        return replies.invalid_handoff(
            "artifacts", f"The handoff is over {limit} bytes; list fewer or shorter artifacts."
        )
    return replies.invalid_handoff(
        "report",
        f"The handoff is over {limit} bytes; shorten the report and list fewer or shorter "
        "artifacts.",
    )


def _unknown_message(unknown: Sequence[object]) -> str:
    """How many unknown arguments came, naming at most a few plain ones; never raw text."""
    plain = [name for name in unknown if isinstance(name, str) and _PLAIN_NAME.fullmatch(name)]
    named = heapq.nsmallest(_UNKNOWN_LISTED, plain)
    listed = f" ({', '.join(named)})" if named else ""
    known = ", ".join(sorted(_FIELDS))
    return f"{len(unknown)} unknown argument(s){listed}; the arguments are {known}."


def _label(
    snapshot: RunSnapshot, slot: Slot, status: str, arguments: Mapping[str, object]
) -> str | ToolReply | None:
    """A done handoff names its arrow on a step that routes by label; nothing else has one."""
    owner = find_activation(snapshot.state, slot.activation_id)
    node_id = owner.node_id if owner is not None else ""
    labels = choosable_labels(snapshot.graph, node_id)
    if status == "blocked" or not labels:
        if "label" in arguments:
            return replies.invalid_handoff(
                "label", "Only a done handoff on a step with labels names one."
            )
        return None
    if "label" not in arguments:
        if routes_by_label(snapshot.graph, node_id):
            return replies.invalid_handoff(
                "label", "Name the label that fits your result.", labels
            )
        return None
    given = arguments["label"]
    if not isinstance(given, str) or given not in labels:
        return replies.invalid_handoff("label", "Use one of the step's labels.", labels)
    return given


def _text(value: object, max_length: int) -> str | None:
    """Non-blank text of at most ``max_length`` characters that UTF-8 can encode."""
    if not isinstance(value, str) or len(value) > max_length or not value.strip():
        return None
    return value if _encodable(value) else None


def _artifacts(value: object) -> list[str] | None:
    """At most ``ARTIFACTS_MAX`` paths of 1 to ``ARTIFACT_MAX`` characters."""
    if not isinstance(value, list | tuple) or len(value) > ARTIFACTS_MAX:
        return None
    paths: list[str] = []
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item) <= ARTIFACT_MAX:
            return None
        if not _encodable(item):
            return None
        paths.append(item)
    return paths


def _encodable(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True
