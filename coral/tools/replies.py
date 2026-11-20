"""The replies engine tools give and the ``next`` text that tells the agent what to do.

No text for a paused, cancelled or finished run, or a replaced session, invites
another call: each says to stop and end the turn. An orchestrator is never
told that Coral resumes a step: it has none.
"""

from __future__ import annotations

import dataclasses

from coral.engine.types import Rejection
from coral.tools.catalog import CHOOSE_ARROW
from coral.tools.port import EngineRefused
from coral.tools.schemas import (
    DECISION_CLOSED,
    EVALUATION_IN_PROGRESS,
    EVIDENCE_MISSING,
    HANDOFF_INVALID,
    NOT_ORCHESTRATOR,
    NOT_RUN_MEMBER,
    RUN_CANCELLED,
    RUN_PAUSED,
    SLOT_CLOSED,
    SLOT_SUPERSEDED,
    TOOL_ILLEGAL,
    LoopUse,
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
EVIDENCE_RERUN = "Run the commands named above, then call coral_submit_handoff again."
EVIDENCE_FINAL = (
    "This step is out of attempts, so Coral did not take the handoff. Stop now and end your turn."
)
EVIDENCE_WAIT = (
    "Coral is still checking the commands this step ran; call coral_submit_handoff again "
    "in a moment."
)
NOT_THE_ORCHESTRATOR = (
    "Only the run's current orchestrator can choose arrows. Stop now and end your turn."
)
NO_OPEN_DECISION = "No decision is open now. Stop now and end your turn."
# After a choice: other decisions of the run may be waiting on the orchestrator.
CHOICE_DONE = "Answer any other open decision request, then end your turn."


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


def evidence_missing(message: str, *, final: bool) -> ToolReply:
    """A ``done`` handoff whose commands did not pass; counted against the step's attempts."""
    return ToolReply(
        accepted=False,
        reason=EVIDENCE_MISSING,
        next=EVIDENCE_FINAL if final else EVIDENCE_RERUN,
        message=message,
    )


def evidence_in_progress() -> ToolReply:
    """Coral cannot judge the commands yet; uncounted, and the same call may be made again."""
    return ToolReply(accepted=False, reason=EVALUATION_IN_PROGRESS, next=EVIDENCE_WAIT)


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


def not_orchestrator() -> ToolReply:
    return ToolReply(accepted=False, reason=NOT_ORCHESTRATOR, next=NOT_THE_ORCHESTRATOR)


def choice_paused(reason: str | None) -> ToolReply:
    """A paused run's answer to an orchestrator, naming the pause reason when it is known."""
    cause = f" ({reason})" if reason else ""
    return ToolReply(
        accepted=False,
        reason=RUN_PAUSED,
        next=f"The run is paused{cause}. Stop now and end your turn.",
    )


def illegal_choice(field: str, message: str, allowed: tuple[str, ...] = ()) -> ToolReply:
    """An uncounted refusal of a choice, naming the one argument to fix."""
    return ToolReply(
        accepted=False,
        reason=TOOL_ILLEGAL,
        allowed_values=allowed,
        next=f"Fix {field} and call coral_choose_arrow again.",
        field=field,
        message=message,
    )


def unknown_decision(open_ids: tuple[str, ...]) -> ToolReply:
    """A ``decision_id`` that names no open decision; with none open, there is nothing to do."""
    if not open_ids:
        return dataclasses.replace(
            illegal_choice("decision_id", "No decision is open."), next=NO_OPEN_DECISION
        )
    return illegal_choice("decision_id", "Use one of the open decision ids.", open_ids)


def choice_made(
    label: str,
    target: str | None,
    *,
    loop: LoopUse | None = None,
    redirected: bool = False,
    duplicate: bool = False,
) -> ToolReply:
    """
    A taken choice, or the receipt of one taken earlier.

    :param label: The chosen label, one of the decision's own.
    :param target: The node Coral went to: the chosen arrow's target, or the
        at-limit arrow's when a loop limit redirected the choice.
    :param loop: The pass a back arrow started and the loop's limit.
    """
    where = f"'{target}'" if target is not None else "no further node"
    if redirected:
        went = f"'{label}' reached its loop limit, so Coral took the at-limit arrow to {where}."
    elif loop is not None:
        limit = f" of {loop.limit}" if loop.limit is not None else ""
        went = f"Coral took '{label}' back to {where} for pass {loop.used}{limit}."
    else:
        went = f"Coral took '{label}' to {where}."
    if duplicate:
        went = f"This decision is already made: {went}"
    return ToolReply(
        accepted=True,
        next=f"{went} {CHOICE_DONE}",
        duplicate=duplicate,
        loop=loop,
        redirected=redirected,
    )


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
        return choice_paused(None) if tool == CHOOSE_ARROW.name else run_paused(None)
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
        return illegal_choice(
            "label", "Use one of the decision's labels.", tuple(rejection.allowed_values)
        )
    raise EngineRefused(rejection)
