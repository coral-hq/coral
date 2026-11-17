# CORAL(S10): tools the server runs for a session's runner (new file).
"""Tools the server runs itself instead of forwarding them to the session's runner.

An installed extension registers a handler under a tool name. The session MCP
proxy (``POST /v1/sessions/{id}/mcp``) runs it after TOOL_CALL policy, with the
policy's arguments as a dict, but only for a session whose agent an installed
tool provider gave that tool (:mod:`omnigent.tools.extensions`). With nothing
registered, the proxy behaves as before.

S10 does not authorize the caller beyond the route's edit access: a handler
must check ``runner_proven`` and the operation id itself and treat both the
operation id and the arguments as untrusted input. S10 sets no time limit
either: a handler must bound its own work, and the runner may resend the same
operation id while the first call is still running.

The registry is process-wide, keyed by tool name: the latest registration of a
name wins, as with the other server registries.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from omnigent.tools.extensions import (
    extension_tool_name,
    extension_tool_sets,
    is_extension_tool_name,
    is_framework_tool_name,
)

if TYPE_CHECKING:
    from omnigent.spec import AgentSpec

_logger = logging.getLogger(__name__)

# claude-sdk exposes the runner's tools under this MCP server prefix.
_OMNIGENT_TOOL_PREFIX = "mcp__omnigent__"
# Framework tools (``sys_*``) keep their own handling, e.g. ``sys_advise_models``.
_FRAMEWORK_TOOL_PREFIX = "sys_"
_FAILED_TEXT = "server tool failed; see the server log"


@dataclass(frozen=True)
class ServerToolCall:
    """One call of a server tool, after TOOL_CALL policy. Nothing in it is authorized yet.

    :param session_id: The calling session, e.g. ``"conv_abc123"``.
    :param name: The bare tool name, e.g. ``"coral_submit_handoff"``.
    :param arguments: The arguments policy let through, possibly transformed:
        always a dict, its fields unvalidated.
    :param operation_id: The caller's operation id for this call (1-128
        characters, client-chosen), or ``None`` when the caller sent none.
    :param runner_proven: Whether the caller proved it is the session's runner;
        a handler that must run only for the runner checks it.
    :param actor: The policy principal, e.g. ``{"run_as": "alice@example.com"}``.
    """

    session_id: str
    name: str
    arguments: Mapping[str, object]
    operation_id: str | None
    runner_proven: bool
    actor: Mapping[str, str] | None


@dataclass(frozen=True)
class ServerToolResult:
    """What a server tool answers.

    :param text: The tool output, or the error message when *is_error*.
    :param is_error: ``True`` returns a JSON-RPC ``-32000`` error instead of a
        tool result.
    """

    text: str
    is_error: bool = False


ServerToolHandler = Callable[[ServerToolCall], Awaitable[ServerToolResult]]


@dataclass(frozen=True, eq=False)
class _Registration:
    """One registration; its identity lets an unregister remove only itself."""

    handler: ServerToolHandler


# Process-wide registry keyed by tool name, never by session.
# custom-lint: disable-next=workspace-scoped-cache -- keyed by tool name, not a tenant id
_registrations: dict[str, _Registration] = {}
_registrations_lock = threading.Lock()


def register_server_tool(name: str, handler: ServerToolHandler) -> Callable[[], None]:
    """Run *handler* on the server for tool *name*.

    Registering a name again replaces its handler and logs a warning.

    :param name: A tool name of 1-256 letters, digits, ``_`` or ``-``, without
        ``__`` and not starting with ``sys_``, e.g. ``"coral_submit_handoff"``.
        Registering the same handler again replaces it silently.
    :param handler: Awaited with each :class:`ServerToolCall`; it must bound
        its own work.
    :returns: An idempotent unregister function that removes this registration
        only while it is still the one registered under *name*.
    :raises ValueError: If *name* is not a valid server tool name.
    """
    if not _is_server_tool_name(name):
        raise ValueError(f"invalid server tool name {name!r}")
    registration = _Registration(handler)
    with _registrations_lock:
        replaced = _registrations.get(name)
        _registrations[name] = registration
    if replaced is not None and replaced.handler is not handler:
        _logger.warning("server tool %r replaced an earlier registration", name)

    def unregister() -> None:
        with _registrations_lock:
            if _registrations.get(name) is registration:
                del _registrations[name]

    return unregister


def server_tool_name(name: str) -> str:
    """Return *name* without one leading ``mcp__omnigent__`` prefix."""
    return name.removeprefix(_OMNIGENT_TOOL_PREFIX)


def server_tool(name: str) -> ServerToolHandler | None:
    """Return the handler registered for *name* (bare or ``mcp__omnigent__``), else ``None``.

    A name that is not a string (a malformed call) has no handler.
    """
    if not isinstance(name, str):
        return None
    with _registrations_lock:
        registration = _registrations.get(server_tool_name(name))
    return None if registration is None else registration.handler


def granted_server_tool(name: str, spec: AgentSpec) -> ServerToolHandler | None:
    """Return the handler for *name* when *spec*'s agent was given that tool, else ``None``.

    The agent was given it when an installed tool provider offers the tool for
    *spec*, the name is not a framework tool's (the runner never registers a
    provider tool under one) and the spec declares no local tool of that name,
    which the runner keeps instead. A ``mcp__omnigent__`` name is left to a
    spec MCP server named ``mcp``, whose tools share that prefix. Providers are
    consulted only for a registered name.

    :param name: The called tool name, bare or ``mcp__omnigent__``-prefixed.
    :param spec: The calling session's agent spec.
    """
    handler = server_tool(name)
    if handler is None:
        return None
    bare = server_tool_name(name)
    if any(info.name == bare for info in spec.local_tools):
        return None
    if bare != name and any(server.name == "mcp" for server in spec.mcp_servers):
        return None
    if is_framework_tool_name(bare):
        return None

    offered = {
        extension_tool_name(schema)
        for tool_set in extension_tool_sets(spec)
        for schema in tool_set.tools
    }
    return handler if bare in offered else None


async def run_server_tool(handler: ServerToolHandler, call: ServerToolCall) -> ServerToolResult:
    """Await *handler* with *call*; a failure becomes a logged error result.

    A handler that raises (other than cancellation) or returns anything but a
    :class:`ServerToolResult` with string text is logged with the session id
    and answered with ``ServerToolResult("server tool failed; see the server
    log", is_error=True)``.
    """
    log_extra = {"session_id": call.session_id}
    try:
        result = await handler(call)
    except Exception:  # a handler bug must answer the call, not break the proxy
        _logger.exception("Server tool %r failed", call.name, extra=log_extra)
        return ServerToolResult(_FAILED_TEXT, is_error=True)
    if not isinstance(result, ServerToolResult):
        problem = f"a {type(result).__name__}"
    elif not isinstance(result.text, str):
        problem = f"{type(result.text).__name__} text"
    else:
        return result
    _logger.error(
        "Server tool %r returned an invalid result (%s)", call.name, problem, extra=log_extra
    )
    return ServerToolResult(_FAILED_TEXT, is_error=True)


def _is_server_tool_name(name: object) -> bool:
    return is_extension_tool_name(name) and not name.startswith(_FRAMEWORK_TOOL_PREFIX)
