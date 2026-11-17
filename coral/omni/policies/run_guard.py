"""The run guard: a stopped run's sessions, and closed ones, get only Coral's engine tools.

Coral's policy provider builds it on every policy build from the run status it
read and the session row's ``omnigent.closed`` label. While the run is paused,
cancelled, finished or gone, or the session is closed, every tool call is
denied except the exact engine tools, which get the engine's own structured
answer, and exactly ``ToolSearch``, which loads them. Every deny tells the
agent to stop and end its turn. Only tool calls are decided, and evaluating
never raises.
"""

from __future__ import annotations

from collections.abc import Callable

from coral.db.enum_codecs import RunStatusStr
from coral.omni.policies.guards import is_engine_tool, is_tool_call, is_tool_search, tool_name
from coral.omni.policies.state import MISSING
from omnigent.policies.schema import PolicyEvent, PolicyResponse

Evaluator = Callable[[PolicyEvent], PolicyResponse]

_STOP = "Stop now and end your turn."
_LIVE = frozenset({RunStatusStr.STARTING.value, RunStatusStr.RUNNING.value})
# ``{who}`` is "step", or "session" for an orchestrator, which is not a step.
_STOPPED = {
    RunStatusStr.CANCELLED.value: f"[run.cancelled] The Coral run was cancelled. {_STOP}",
    RunStatusStr.COMPLETED.value: f"[run.finished] The Coral run has finished. {_STOP}",
    RunStatusStr.FAILED.value: f"[run.finished] The Coral run has finished. {_STOP}",
    MISSING: f"[run.missing] This {{who}}'s Coral run no longer exists. {_STOP}",
}
_CLOSED = f"[session.closed] Coral closed this {{who}}. {_STOP}"


def run_guard(
    *,
    run_status: str,
    pause_reason: str | None,
    closed: bool,
    orchestrator: bool = False,
) -> Evaluator:
    """
    Policy factory: deny tool calls while the run is stopped or the session is closed.

    :param run_status: The run's stored status (a ``RunStatusStr`` value) or
        ``"missing"``.
    :param pause_reason: Why a paused run is paused, e.g. ``"drift"``, when known.
    :param closed: Whether the session row carries ``omnigent.closed``.
    :param orchestrator: The session is the run's orchestrator: its texts name
        the session, not a step, and no step resumes.
    :returns: An evaluator that ALLOWs every call while the run is starting or
        running and the session is open; otherwise it DENYs every tool call
        but the exact engine tools and ``ToolSearch``.
    :raises ValueError: For a run status the guard does not know.
    """
    deny = _deny_reason(run_status, pause_reason, closed=closed, orchestrator=orchestrator)

    def evaluate(event: PolicyEvent) -> PolicyResponse:
        if deny is None or not is_tool_call(event):
            return {"result": "ALLOW"}
        name = tool_name(event)
        if is_engine_tool(name) or is_tool_search(name):
            return {"result": "ALLOW"}
        return {"result": "DENY", "reason": deny}

    return evaluate


def _deny_reason(
    run_status: str, pause_reason: str | None, *, closed: bool, orchestrator: bool
) -> str | None:
    """The deny text for the state, or ``None`` when tool calls may run."""
    known = run_status in _LIVE or run_status in _STOPPED or run_status == RunStatusStr.PAUSED
    if not known:
        raise ValueError(f"unknown run status {run_status!r}")
    who = "session" if orchestrator else "step"
    if closed:
        return _CLOSED.format(who=who)
    if run_status == RunStatusStr.PAUSED:
        cause = f" ({pause_reason})" if pause_reason else ""
        resumes = "" if orchestrator else "; Coral resumes this step when the run resumes"
        return f"[run.paused] The Coral run is paused{cause}. Stop now and end your turn{resumes}."
    stopped = _STOPPED.get(run_status)
    return None if stopped is None else stopped.format(who=who)
