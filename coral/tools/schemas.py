"""Parameter schemas of Coral's engine tools and the reply every call gets (K6 v0).

Standard library only: hosts and runners import this through the tool catalog.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

# The canonical handoff body a submit commits, in UTF-8 bytes.
HANDOFF_BODY_MAX_BYTES = 12_288
# coral_submit_handoff field bounds, shared by its schema and its planner.
HANDOFF_KIND = "handoff"
HANDOFF_STATUSES = ("done", "blocked")
ACTIVATION_ID_MAX = 512
REPORT_MAX = 8000
BLOCKED_REASON_MAX = 2000
LABEL_MAX = 200
ARTIFACTS_MAX = 50
ARTIFACT_MAX = 1024
# coral_choose_arrow field bounds, shared by its schema and its planner.
DECISION_ID_MAX = 512
REASON_MAX = 4000
# coral_message_agent / assign_* field bounds (TLS-04).
MESSAGE_TEXT_MAX = 8000
MESSAGE_TO_MAX = 512
REPLY_TO_MAX = 512
ASSIGN_REASON_MAX = 2000
ASSIGN_TASK_MAX = 8000
ASSIGN_PROFILE_MAX = 64
ASSIGN_COUNT_MAX = 20

SUBMIT_HANDOFF_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "activation_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": ACTIVATION_ID_MAX,
            "description": "The activation id from your brief.",
        },
        "status": {
            "type": "string",
            "enum": list(HANDOFF_STATUSES),
            "description": "done when your work is finished; blocked when you cannot continue.",
        },
        "report": {
            "type": "string",
            "minLength": 1,
            "maxLength": REPORT_MAX,
            "description": "What you did and how you checked it, or what you tried.",
        },
        "blocked_reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": BLOCKED_REASON_MAX,
            "description": "Required when status is blocked: what stops you.",
        },
        # Only handoffs are offered: a refresh note would always be refused and counted.
        "kind": {
            "type": "string",
            "enum": [HANDOFF_KIND],
            "default": HANDOFF_KIND,
            "description": "Leave this as handoff.",
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": LABEL_MAX,
            "description": (
                "Only for a done handoff when your brief lists outcome labels: the label "
                "that fits your result."
            ),
        },
        "artifacts": {
            "type": "array",
            "maxItems": ARTIFACTS_MAX,
            "items": {"type": "string", "minLength": 1, "maxLength": ARTIFACT_MAX},
            "description": "Paths or references to what you produced.",
        },
    },
    "required": ["activation_id", "status", "report"],
    "additionalProperties": False,
}

CHOOSE_ARROW_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "decision_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": DECISION_ID_MAX,
            "description": "The decision id from the decision request.",
        },
        "label": {
            "type": "string",
            "minLength": 1,
            "maxLength": LABEL_MAX,
            "description": "One of the labels the decision request lists.",
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": REASON_MAX,
            "description": "A short reason for your choice.",
        },
    },
    "required": ["decision_id", "label", "reason"],
    "additionalProperties": False,
}

MESSAGE_AGENT_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "to": {
            "type": "string",
            "minLength": 1,
            "maxLength": MESSAGE_TO_MAX,
            "description": '"orchestrator" or a member id from your brief, e.g. "review/codex#1".',
        },
        "text": {
            "type": "string",
            "minLength": 1,
            "maxLength": MESSAGE_TEXT_MAX,
            "description": "The message to deliver.",
        },
        "reply_to": {
            "type": "string",
            "minLength": 1,
            "maxLength": REPLY_TO_MAX,
            "description": "Optional id of the message you are replying to.",
        },
    },
    "required": ["to", "text"],
    "additionalProperties": False,
}

ASSIGN_AGENTS_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "activation_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": ACTIVATION_ID_MAX,
            "description": "The activation waiting for roster assignment.",
        },
        "assignments": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": ASSIGN_PROFILE_MAX,
                    },
                    "count": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": ASSIGN_COUNT_MAX,
                    },
                },
                "required": ["profile", "count"],
                "additionalProperties": False,
            },
            "description": "Profiles and counts within the authored up-to bounds.",
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": ASSIGN_REASON_MAX,
            "description": "Why these agents are being assigned.",
        },
    },
    "required": ["activation_id", "assignments", "reason"],
    "additionalProperties": False,
}

ASSIGN_TASK_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "activation_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": ACTIVATION_ID_MAX,
            "description": "The activation in merge_conflict that needs re-tasking.",
        },
        "member": {
            "type": "string",
            "minLength": 1,
            "maxLength": MESSAGE_TO_MAX,
            "description": "The member id to re-task, e.g. implementer#1.",
        },
        "task": {
            "type": "string",
            "minLength": 1,
            "maxLength": ASSIGN_TASK_MAX,
            "description": "What the member should do in its worktree.",
        },
        "reason": {
            "type": "string",
            "minLength": 1,
            "maxLength": ASSIGN_REASON_MAX,
            "description": "Why this member is being re-tasked.",
        },
    },
    "required": ["activation_id", "member", "task", "reason"],
    "additionalProperties": False,
}

# Reply reasons. Only handoff.invalid counts toward a slot's rejected-call streak.
HANDOFF_INVALID = "handoff.invalid"
TOOL_ILLEGAL = "tool.illegal"
RUN_PAUSED = "run.paused"
RUN_CANCELLED = "run_cancelled"
NOT_RUN_MEMBER = "not_run_member"
SLOT_CLOSED = "slot_closed"
EVALUATION_IN_PROGRESS = "evaluation_in_progress"
SLOT_SUPERSEDED = "slot.superseded"
DECISION_CLOSED = "decision_closed"
NOT_ORCHESTRATOR = "not_orchestrator"
# The evidence check produces evidence.missing; take-over and messaging are reserved.
EVIDENCE_MISSING = "evidence.missing"
RUN_TAKEN_OVER = "run.taken_over"
RECIPIENT_CLOSING = "recipient_closing"

REASONS = frozenset(
    {
        HANDOFF_INVALID,
        TOOL_ILLEGAL,
        RUN_PAUSED,
        RUN_CANCELLED,
        NOT_RUN_MEMBER,
        SLOT_CLOSED,
        EVALUATION_IN_PROGRESS,
        SLOT_SUPERSEDED,
        DECISION_CLOSED,
        NOT_ORCHESTRATOR,
        EVIDENCE_MISSING,
        RUN_TAKEN_OVER,
        RECIPIENT_CLOSING,
    }
)
COUNTED_REASONS = frozenset({HANDOFF_INVALID})


@dataclass(frozen=True)
class LoopUse:
    """The pass of a loop now running and the loop's limit (``None`` when unlimited)."""

    used: int
    limit: int | None


@dataclass(frozen=True)
class ToolReply:
    """
    What an engine tool call returns to the agent, as JSON text in a normal tool result.

    :param accepted: True when Coral took the call (a duplicate included).
    :param reason: One of :data:`REASONS` when not accepted, else ``None``.
    :param allowed_values: Values the refused field accepts: enum values, the
        step's arrow labels, the slot's activation id or open decision ids only.
    :param next: What the agent should do now.
    :param field: The one argument a ``handoff.invalid`` or ``tool.illegal`` names.
    :param duplicate: True when this repeats an earlier accepted call.
    :param message_id: Delivery id for an accepted ``coral_message_agent`` call.
    :param delivery: Delivery state for an accepted message (``queued``).
    :param members: Assigned member ids for an accepted ``coral_assign_agents``.
    """

    accepted: bool
    reason: str | None = None
    allowed_values: tuple[str, ...] = ()
    next: str = ""
    field: str | None = None
    message: str | None = None
    duplicate: bool = False
    loop: LoopUse | None = None
    redirected: bool = False
    message_id: str | None = None
    delivery: str | None = None
    members: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.accepted and self.reason is not None:
            raise ValueError("an accepted reply has no reason")
        if not self.accepted and self.reason not in REASONS:
            raise ValueError(f"unknown reply reason {self.reason!r}")
        if not all(isinstance(value, str) for value in self.allowed_values):
            raise ValueError("allowed values must be strings")
        if not all(isinstance(value, str) for value in self.members):
            raise ValueError("members must be strings")

    def to_json(self) -> str:
        """Sorted-key JSON. The optional fields appear only when set."""
        body: dict[str, object] = {
            "accepted": self.accepted,
            "reason": self.reason,
            "allowed_values": list(self.allowed_values),
            "next": self.next,
        }
        if self.field is not None:
            body["field"] = self.field
        if self.message is not None:
            body["message"] = self.message
        if self.duplicate:
            body["duplicate"] = True
        if self.loop is not None:
            body["loop"] = {"used": self.loop.used, "limit": self.loop.limit}
        if self.redirected:
            body["redirected"] = True
        if self.message_id is not None:
            body["message_id"] = self.message_id
        if self.delivery is not None:
            body["delivery"] = self.delivery
        if self.members:
            body["members"] = list(self.members)
        return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> ToolReply:
        """
        Read a reply :meth:`to_json` wrote, as a stored reply is replayed.

        :raises ValueError: For text that is not such a reply.
        """
        body = json.loads(text)
        if not isinstance(body, dict) or not _REQUIRED_KEYS <= body.keys() <= _REPLY_KEYS:
            raise ValueError("not a Coral tool reply")
        accepted = body["accepted"]
        reason = body["reason"]
        values = body["allowed_values"]
        next_text = body["next"]
        field = body.get("field")
        message = body.get("message")
        duplicate = body.get("duplicate", False)
        redirected = body.get("redirected", False)
        loop = body.get("loop")
        message_id = body.get("message_id")
        delivery = body.get("delivery")
        members = body.get("members", [])
        if not (
            isinstance(accepted, bool)
            and (reason is None or isinstance(reason, str))
            and isinstance(values, list)
            and isinstance(next_text, str)
            and (field is None or isinstance(field, str))
            and (message is None or isinstance(message, str))
            and isinstance(duplicate, bool)
            and isinstance(redirected, bool)
            and (message_id is None or isinstance(message_id, str))
            and (delivery is None or isinstance(delivery, str))
            and isinstance(members, list)
            and all(isinstance(item, str) for item in members)
        ):
            raise ValueError("not a Coral tool reply")
        return cls(
            accepted=accepted,
            reason=reason,
            allowed_values=tuple(values),
            next=next_text,
            field=field,
            message=message,
            duplicate=duplicate,
            loop=None if loop is None else _loop_use(loop),
            redirected=redirected,
            message_id=message_id,
            delivery=delivery,
            members=tuple(members),
        )


_REQUIRED_KEYS = frozenset({"accepted", "reason", "allowed_values", "next"})
_REPLY_KEYS = _REQUIRED_KEYS | {
    "field",
    "message",
    "duplicate",
    "loop",
    "redirected",
    "message_id",
    "delivery",
    "members",
}


def _loop_use(value: object) -> LoopUse:
    if isinstance(value, dict) and value.keys() == {"used", "limit"}:
        used = value["used"]
        limit = value["limit"]
        limit_ok = limit is None or (isinstance(limit, int) and not isinstance(limit, bool))
        if isinstance(used, int) and not isinstance(used, bool) and limit_ok:
            return LoopUse(used=used, limit=limit)
    raise ValueError("not a Coral tool reply")
