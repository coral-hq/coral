# CORAL(S105): observers of MCP-proxied tool calls (new file).
"""Observers of MCP-proxied tool calls: each call's start, its result, and its end.

``_handle_mcp_tools_call`` opens a :func:`tool_call_scope` per call, and calls
:func:`complete_tool_call` with the runner's raw output before TOOL_RESULT policy,
so an observer records the result before the agent sees it. When the scope
closes, every observer whose call did not complete is released, whatever path the
call ended on. With no observer registered, each step is a dictionary read.

Observers must be cheap in ``enter`` and ``release`` (they run on the event loop),
bound their own ``complete`` work, and never change the tool result: a raise is
logged and dropped.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

_logger = logging.getLogger(__name__)

# Upper bound on one observer's complete; it should bound itself well below this.
COMPLETE_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class ObservedToolCall:
    """
    A finished tool call, before TOOL_RESULT policy.

    :param tool_name: As the agent called it, e.g. ``"sys_os_shell"`` or
        ``"mcp__omnigent__sys_os_shell"``.
    :param output: The runner's raw output text.
    """

    session_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    output: str
    is_error: bool
    operation_id: str | None


class ToolCallObserver(Protocol):
    def enter(self, session_id: str, tool_name: str, operation_id: str | None) -> object | None:
        """Note a call starting; return a token to follow it, or ``None`` to ignore it."""
        ...

    async def complete(self, token: object, call: ObservedToolCall) -> None:
        """Record the call's result; the token is released afterwards either way."""
        ...

    def release(self, token: object) -> None:
        """The call ended; called once per token, after ``complete`` if it ran."""
        ...


# custom-lint: disable-next=workspace-scoped-cache -- keyed by observer name, not a tenant id
_observers: dict[str, ToolCallObserver] = {}
_observers_lock = threading.Lock()
_entered: contextvars.ContextVar[list[tuple[ToolCallObserver, object]] | None] = (
    contextvars.ContextVar("omnigent_tool_call_observers", default=None)
)


def register_tool_call_observer(name: str, observer: ToolCallObserver) -> Callable[[], None]:
    """
    Register ``observer`` under ``name``, e.g. ``"coral.evidence"``.

    :returns: An idempotent unregister that removes it only while it is still
        the observer under ``name``.
    """
    with _observers_lock:
        replaced = _observers.get(name)
        _observers[name] = observer
    if replaced is not None and replaced is not observer:
        _logger.warning("tool-call observer %r replaced an earlier registration", name)

    def unregister() -> None:
        with _observers_lock:
            if _observers.get(name) is observer:
                del _observers[name]

    return unregister


@contextmanager
def tool_call_scope(session_id: str, tool_name: object, operation_id: object) -> Iterator[None]:
    """Enter every observer for one call, and release each one when the call ends."""
    with _observers_lock:
        observers = list(_observers.values())
    if not observers or not isinstance(tool_name, str):
        yield
        return
    operation = operation_id if isinstance(operation_id, str) else None
    entered: list[tuple[ToolCallObserver, object]] = []
    for observer in observers:
        try:
            token = observer.enter(session_id, tool_name, operation)
        except Exception:
            _logger.exception("tool-call observer failed to enter a call")
            continue
        if token is not None:
            entered.append((observer, token))
    reset = _entered.set(entered)
    try:
        yield
    finally:
        _entered.reset(reset)
        for observer, token in entered:
            try:
                observer.release(token)
            except Exception:
                _logger.exception("tool-call observer failed to release a call")


async def complete_tool_call(
    session_id: str,
    tool_name: str,
    arguments: Mapping[str, Any],
    output: str,
    *,
    is_error: bool,
    operation_id: str | None,
) -> None:
    """Give the scope's observers the call's raw result; never raises."""
    entered = _entered.get()
    if not entered:
        return
    call = ObservedToolCall(
        session_id=session_id,
        tool_name=tool_name,
        arguments=dict(arguments),
        output=output,
        is_error=is_error,
        operation_id=operation_id,
    )
    for observer, token in entered:
        try:
            await asyncio.wait_for(observer.complete(token, call), COMPLETE_TIMEOUT_S)
        except Exception:
            _logger.exception("tool-call observer failed to record a call")


__all__ = [
    "COMPLETE_TIMEOUT_S",
    "ObservedToolCall",
    "ToolCallObserver",
    "complete_tool_call",
    "register_tool_call_observer",
    "tool_call_scope",
]
