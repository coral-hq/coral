"""The replies engine tools give and the ``next`` text that tells the agent what to do.

No text for a paused, cancelled or finished run, or a replaced session, invites
another call: each says to stop and end the turn.
"""

from __future__ import annotations

import dataclasses

from coral.engine.types import Rejection
from coral.tools.catalog import CHOOSE_ARROW
from coral.tools.port import EngineRefused
from coral.tools.schemas import (
    DECISION_CLOSED,
    EVALUATION_IN_PROGRESS,
    HANDOFF_INVALID,
    NOT_RUN_MEMBER,
    RUN_CANCELLED,
    RUN_PAUSED,
    SLOT_CLOSED,
    SLOT_SUPERSEDED,
    TOOL_ILLEGAL,
    ToolReply,
)

STOP = "Handoff accepted. Stop now and end your turn; Coral closes this session."
STOP_BLOCKED = "Coral recorded that you are blocked. Stop now and end your turn."
RETRY_SHORTLY = (
    "Coral is not ready for this handoff yet; call coral_submit_handoff again in a moment."
)
EVALUATING = "Coral is already evaluating your handoff. Stop now and end your turn."
SUPERSEDED = "A newer session has taken over this step. Stop now and end your turn."
CANCELLED = "The Coral run was cancelled. Stop now and end your turn."
STEP_CLOSED = "This step is closed. Stop now and end your turn."
DECIDED = "This decision is already made. Stop now and end your turn."
NOT_A_MEMBER = (
    "This session is not a Coral step that can make this call. Stop now and end your turn."
)
BUSY = "Coral is busy; make the same call again in a moment."


def stop_paused(reason: str | None) -> str:
    """The ``next`` of a paused run, naming the pause reason when it is known."""
    cause = f" ({reason})" if reason else ""
    return (
        f"The run is paused{cause}. Stop now and end your turn; Coral resumes this step "
        "when the run resumes."
    )


def accepted(status: str, *, duplicate: bool = False) -> ToolReply:
    """A taken handoff, or the receipt of one taken earlier. ``status`` is done or blocked."""
    return ToolReply(
        accepted=True, next=STOP_BLOCKED if status == "blocked" else STOP, duplicate=duplicate
    )


def invalid_handoff(field: str, message: str, allowed: tuple[str, ...] = ()) -> ToolReply:
    """A counted refusal naming the one argument to fix."""
    return ToolReply(
        accepted=False,
        reason=HANDOFF_INVALID,
        allowed_values=allowed,
        next=f"Fix {field} and call coral_submit_handoff again.",
        field=field,
        message=message,
    )


def stopping(reply: ToolReply, reason: str) -> ToolReply:
    """``reply`` whose commit also pauses the run: it says stop instead of asking for a fix."""
    return dataclasses.replace(reply, next=stop_paused(reason))


def busy() -> ToolReply:
    """Too many decisions in flight; uncounted, and the same call may be made again."""
    return ToolReply(accepted=False, reason=EVALUATION_IN_PROGRESS, next=BUSY)


def not_run_member() -> ToolReply:
    return ToolReply(accepted=False, reason=NOT_RUN_MEMBER, next=NOT_A_MEMBER)


def superseded() -> ToolReply:
    return ToolReply(accepted=False, reason=SLOT_SUPERSEDED, next=SUPERSEDED)


def retry_shortly() -> ToolReply:
    return ToolReply(accepted=False, reason=EVALUATION_IN_PROGRESS, next=RETRY_SHORTLY)


def evaluating() -> ToolReply:
    return ToolReply(accepted=False, reason=EVALUATION_IN_PROGRESS, next=EVALUATING)


def slot_closed() -> ToolReply:
    return ToolReply(accepted=False, reason=SLOT_CLOSED, next=STEP_CLOSED)


def run_cancelled() -> ToolReply:
    return ToolReply(accepted=False, reason=RUN_CANCELLED, next=CANCELLED)


def run_paused(reason: str | None) -> ToolReply:
    return ToolReply(accepted=False, reason=RUN_PAUSED, next=stop_paused(reason))


def decision_closed() -> ToolReply:
    return ToolReply(accepted=False, reason=DECISION_CLOSED, next=DECIDED)


def reply_for_engine_rejection(tool: str, rejection: Rejection) -> ToolReply:
    """
    The reply for the engine refusing a planned input of ``tool``.

    Only ``handoff.invalid`` and ``tool.illegal`` carry values (the step's or
    decision's labels); every other code's values are dropped.

    :raises EngineRefused: For a code no reply covers, such as the generic
        ``rejected``, whose values are reducer input kinds.
    """
    code = rejection.code
    if code == "slot.superseded":
        return superseded()
    if code == "slot.closed":
        return slot_closed()
    if code == "run_paused":
        return run_paused(None)
    if code == "run_cancelled":
        return run_cancelled()
    if code == "run_terminal":
        return decision_closed() if tool == CHOOSE_ARROW.name else slot_closed()
    if code == "evaluation_in_progress":
        return evaluating()
    if code == "slot.not_ready":
        return retry_shortly()
    if code == "decision_closed":
        return decision_closed()
    if code == HANDOFF_INVALID:
        return invalid_handoff(
            "label", "Use one of the step's labels.", tuple(rejection.allowed_values)
        )
    if code == TOOL_ILLEGAL:
        return ToolReply(
            accepted=False,
            reason=TOOL_ILLEGAL,
            allowed_values=tuple(rejection.allowed_values),
            next="Choose one of the allowed labels and call coral_choose_arrow again.",
            field="label",
            message="Use one of the decision's labels.",
        )
    raise EngineRefused(rejection)
