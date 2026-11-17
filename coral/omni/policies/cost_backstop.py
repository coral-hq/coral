"""The cost backstop: a bound session that has spent its cap gets no more tool calls.

Coral's policy provider builds it on every policy build from the session
row's own priced spend, never the run-wide usage policies otherwise see. At
or over the cap, every tool call is denied except the exact engine tools and
exactly ``ToolSearch``, which get the engine's own answer, and the run pauses
as ``paused(budget)`` through the pauser the lifespan installs. Those exempt
tools are all an orchestrator may call, so an orchestrator's exempt calls
pause the run too, and then pass on to meet it paused. Unpriced usage passes.
Only tool calls are decided; it never asks and never raises. Spend is recorded
at the end of each turn, so the cap can be overshot by a whole turn.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from coral.db.enum_codecs import RunPauseReason
from coral.omni.policies.guards import is_engine_tool, is_tool_call, is_tool_search, tool_name
from coral.omni.policies.run_guard import Evaluator
from coral.omni.policies.state import log_traceback_once
from coral.recovery.pause import PauseResult
from omnigent.policies.schema import PolicyEvent, PolicyResponse

_logger = logging.getLogger(__name__)

SESSION_CAP_CONFIG_KEY = "coral_session_cost_cap_usd"
SESSION_CAP_ENV = "CORAL_SESSION_COST_CAP_USD"
DEFAULT_SESSION_CAP_USD = 25.0
MAX_SESSION_CAP_USD = 1_000_000.0
# Said only when this call paused the run, or found it paused for budget already.
_PAUSED_TEXT = (
    "[budget] This session has spent about ${spent} of its ${cap} cap (an estimate), so "
    "Coral paused the run. Stop now and end your turn."
)
_REACHED_TEXT = (
    "[budget] This session has reached its cost cap: it has spent about ${spent} of its "
    "${cap} cap (an estimate). Stop now and end your turn."
)


class BudgetPauser(Protocol):
    """Pauses a live run as ``paused(budget)`` because one of its sessions spent its cap."""

    def __call__(
        self,
        *,
        workspace_id: int,
        run_id: str,
        session_id: str,
        spent_usd: float,
        cap_usd: float,
        now_us: int,
    ) -> PauseResult | None: ...


@dataclass(eq=False)
class _Installed:
    pauser: BudgetPauser


class _PauserSlot:
    """The one process-wide budget pauser; a later install replaces an earlier one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._installed: _Installed | None = None

    def install(self, pauser: BudgetPauser) -> Callable[[], None]:
        installed = _Installed(pauser)
        with self._lock:
            self._installed = installed

        def uninstall() -> None:
            with self._lock:
                if self._installed is installed:
                    self._installed = None

        return uninstall

    def current(self) -> BudgetPauser | None:
        with self._lock:
            return None if self._installed is None else self._installed.pauser


_PAUSER = _PauserSlot()


def install_budget_pauser(pauser: BudgetPauser) -> Callable[[], None]:
    """
    Install the pauser every cost backstop calls on a deny.

    :returns: An idempotent uninstall that removes only this installation.
    """
    return _PAUSER.install(pauser)


def session_spend_usd(usage: object) -> float | None:
    """
    A session's own priced spend from its row's ``session_usage``; ``None`` when unpriced.

    The larger of ``policy_cost_usd`` and ``total_cost_usd``, each counted only
    when it is a finite number, so an enforcement figure a client posted can
    never hide the spend the server recorded.
    """
    if not isinstance(usage, Mapping):
        return None
    figures = [_finite(usage.get(key)) for key in ("policy_cost_usd", "total_cost_usd")]
    priced = [figure for figure in figures if figure is not None]
    return max(priced) if priced else None


def _finite(value: object) -> float | None:
    """*value* as a float when it is a finite number (never a bool), else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        figure = float(value)
    except OverflowError:  # an integer too large for a float
        return None
    return figure if math.isfinite(figure) else None


def cost_backstop(
    *,
    cap_usd: float,
    spent_usd: float | None,
    workspace_id: int,
    run_id: str,
    session_id: str,
    orchestrator: bool = False,
) -> Evaluator:
    """
    Policy factory: deny tool calls once the session's own spend reaches its cap.

    :param cap_usd: The per-session cap.
    :param spent_usd: The session's priced spend; ``None`` when unpriced, which passes.
    :param workspace_id: The run's workspace.
    :param run_id: The run to pause.
    :param session_id: The bound session the spend belongs to.
    :param orchestrator: The session is the run's orchestrator, whose only
        tools are the exempt ones: they pause the run too.
    :returns: An evaluator that ALLOWs every call below the cap. At or over
        it, it pauses the run and DENYs every tool call but the exact engine
        tools and ``ToolSearch``, which it ALLOWs without a pause (a step) or
        after one (an orchestrator).
    """
    if spent_usd is None or spent_usd < cap_usd:
        return _allow
    spent = spent_usd
    amounts = {"spent": _usd(spent), "cap": _usd(cap_usd)}
    paused_text = _PAUSED_TEXT.format(**amounts)
    reached_text = _REACHED_TEXT.format(**amounts)

    def evaluate(event: PolicyEvent) -> PolicyResponse:
        if not is_tool_call(event):
            return {"result": "ALLOW"}
        name = tool_name(event)
        exempt = is_engine_tool(name) or is_tool_search(name)
        if exempt and not orchestrator:
            return {"result": "ALLOW"}
        paused = _pause(workspace_id, run_id, session_id, spent, cap_usd)
        if exempt:
            # The orchestrator's engine call then meets the paused run and gets its answer.
            return {"result": "ALLOW"}
        return {"result": "DENY", "reason": paused_text if paused else reached_text}

    return evaluate


def _usd(amount: float) -> str:
    """Dollars to the cent, or to two significant digits below a cent."""
    if amount == 0 or abs(amount) >= 0.01:
        return f"{amount:,.2f}"
    return f"{amount:.2g}"


def _allow(_event: PolicyEvent) -> PolicyResponse:
    """The backstop of a session below its cap, or whose spend is unpriced."""
    return {"result": "ALLOW"}


def _pause(
    workspace_id: int, run_id: str, session_id: str, spent_usd: float, cap_usd: float
) -> bool:
    """
    Pause the run through the installed pauser; a failure is logged, never raised.

    :returns: Whether the run is paused for budget now: this call paused it, or
        it already was.
    """
    # Not ``workspace_id``: the debug-log sink reads that as the deployment's workspace.
    extra = {"session_id": session_id, "coral_workspace_id": workspace_id}
    pauser = _PAUSER.current()
    if pauser is None:
        _logger.warning(
            "Coral has no budget pauser installed; run %s is not paused", run_id, extra=extra
        )
        return False
    try:
        result = pauser(
            workspace_id=workspace_id,
            run_id=run_id,
            session_id=session_id,
            spent_usd=spent_usd,
            cap_usd=cap_usd,
            now_us=time.time_ns() // 1_000,
        )
    except Exception as exc:  # noqa: BLE001 -- logged; the call is denied and the next one retries
        log_traceback_once(_logger, "budget pause", exc)
        _logger.warning(
            "Coral could not pause run %s for session %s's spend cap (%s); denying the call",
            run_id,
            session_id,
            type(exc).__name__,
            extra=extra,
        )
        return False
    if not isinstance(result, PauseResult):
        return False
    if result.applied:
        _logger.warning(
            "Coral paused run %s: session %s spent about $%s of its $%s cap",
            run_id,
            session_id,
            _usd(spent_usd),
            _usd(cap_usd),
            extra=extra,
        )
        return True
    return result.pause_reason == int(RunPauseReason.BUDGET)


def resolve_session_cap_usd(
    server_config: Mapping[str, Any] | None, env: Mapping[str, str] | None = None
) -> float:
    """
    The per-session cost cap: the environment, else the server config, else the default.

    :param server_config: The server config; ``coral_session_cost_cap_usd`` is a number.
    :param env: The environment (``os.environ`` when ``None``);
        ``CORAL_SESSION_COST_CAP_USD`` wins and a blank value counts as unset.
    :returns: The cap in US dollars, by default ``25.0``.
    :raises ValueError: For a value that is not a finite number in (0, 1,000,000].
    """
    source = os.environ if env is None else env
    raw_env = source.get(SESSION_CAP_ENV, "").strip()
    raw: object
    if raw_env:
        name, raw = SESSION_CAP_ENV, raw_env
        try:
            cap = float(raw_env)
        except ValueError:
            cap = math.nan
    else:
        name = SESSION_CAP_CONFIG_KEY
        raw = None if server_config is None else server_config.get(SESSION_CAP_CONFIG_KEY)
        if raw is None:
            return DEFAULT_SESSION_CAP_USD
        is_number = isinstance(raw, int | float) and not isinstance(raw, bool)
        try:
            cap = float(raw) if is_number else math.nan
        except OverflowError:  # an integer too large for a float
            cap = math.nan
    if not (math.isfinite(cap) and 0 < cap <= MAX_SESSION_CAP_USD):
        raise ValueError(
            f"Coral session cost cap {name}={_shown(raw)} must be a number of US dollars "
            f"above 0 and at most {MAX_SESSION_CAP_USD:,.0f}"
        )
    return cap


def _shown(raw: object) -> str:
    """*raw* for an error message, cut to 64 characters."""
    try:
        text = repr(raw)
    except ValueError:  # an integer with more digits than Python converts to text
        text = f"<{type(raw).__name__} too long to show>"
    return text[:64]
