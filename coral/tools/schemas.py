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
# Reserved for the evidence check, take-over and messaging tools; nothing produces them yet.
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

    def __post_init__(self) -> None:
        if self.accepted and self.reason is not None:
            raise ValueError("an accepted reply has no reason")
        if not self.accepted and self.reason not in REASONS:
            raise ValueError(f"unknown reply reason {self.reason!r}")
        if not all(isinstance(value, str) for value in self.allowed_values):
            raise ValueError("allowed values must be strings")

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
        if not (
            isinstance(accepted, bool)
            and (reason is None or isinstance(reason, str))
            and isinstance(values, list)
            and isinstance(next_text, str)
            and (field is None or isinstance(field, str))
            and (message is None or isinstance(message, str))
            and isinstance(duplicate, bool)
            and isinstance(redirected, bool)
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
        )


_REQUIRED_KEYS = frozenset({"accepted", "reason", "allowed_values", "next"})
_REPLY_KEYS = _REQUIRED_KEYS | {"field", "message", "duplicate", "loop", "redirected"}


def _loop_use(value: object) -> LoopUse:
    if isinstance(value, dict) and value.keys() == {"used", "limit"}:
        used = value["used"]
        limit = value["limit"]
        limit_ok = limit is None or (isinstance(limit, int) and not isinstance(limit, bool))
        if isinstance(used, int) and not isinstance(used, bool) and limit_ok:
            return LoopUse(used=used, limit=limit)
    raise ValueError("not a Coral tool reply")
