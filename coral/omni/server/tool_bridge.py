"""Coral's engine tools as server tools: transport checks, the session's binding, then the port.

Each handler refuses, as a ``-32000`` transport fault, a call without the
runner's operation id, a call the session's own runner did not send (on every
server, single-user included), and any call while the server has no decision
port; each refusal logs a warning naming the session. It then reads the
session's binding by the authenticated session id, fresh on every call, and
dispatches. The run, role, slot and generation come only from that row, never
from labels or arguments.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from contextlib import AsyncExitStack

from coral.stores.session_bindings import FreshBindingLookup
from coral.tools import replies
from coral.tools.catalog import EngineToolDecl, validate_catalog
from coral.tools.dispatch import EngineToolCall, ToolDispatcher, TransportError
from coral.tools.handlers import PLANNERS
from coral.tools.port import RunDecisionPort
from omnigent.db.db_models import current_workspace_id
from omnigent.server.server_tools import (
    ServerToolCall,
    ServerToolHandler,
    ServerToolResult,
    register_server_tool,
)
from omnigent.tools import extensions

_logger = logging.getLogger(__name__)

NO_OPERATION_ID = "Coral tools need the runner's operation id"
NOT_THE_RUNNER = "Coral tools can be called only by the session's own runner"
ENGINE_NOT_RUNNING = "Coral's workflow engine is not running on this server"
LOOKUP_FAILED = "could not look up this session; retry"


def register_engine_tools(
    *,
    catalog: Sequence[EngineToolDecl],
    port: RunDecisionPort | None,
    bindings: FreshBindingLookup,
    stack: AsyncExitStack,
) -> None:
    """
    Register one server tool per ``catalog`` entry; each unregister goes on ``stack``.

    :param catalog: The tools runners advertise; production lists none, so
        nothing is registered.
    :param port: Where calls are decided; ``None`` answers every call that
        "the engine is not running".
    :param bindings: A lookup whose ``reads_fresh`` is true: it reads the store
        on every call, so the planners see a binding's current progress. A
        cache that keeps found rows is refused, even with an empty catalog.
    :raises TypeError: For a lookup that does not declare fresh reads.
    :raises ValueError: For a declaration that cannot be offered, or one no
        planner answers.
    """
    if getattr(bindings, "reads_fresh", False) is not True:
        raise TypeError(
            "engine tools need a binding lookup that reads the store on every call "
            "(reads_fresh); a cache of found bindings would serve stale progress"
        )
    validate_catalog(catalog)
    unplanned = [decl.name for decl in catalog if decl.name not in PLANNERS]
    if unplanned:
        raise ValueError(f"no planner answers engine tool {unplanned[0]!r}")
    if not catalog:
        return
    # S10 grants a tool only if a provider offers it; load them now, not on the event loop.
    extensions.default_tool_providers()
    dispatcher = None if port is None else ToolDispatcher(port, PLANNERS)
    for decl in catalog:
        unregister = register_server_tool(decl.name, _handler(decl.name, dispatcher, bindings))
        stack.callback(unregister)


def _handler(
    tool: str, dispatcher: ToolDispatcher | None, bindings: FreshBindingLookup
) -> ServerToolHandler:
    def refuse(call: ServerToolCall, message: str) -> ServerToolResult:
        # The session only: the arguments and the operation id are the caller's.
        _logger.warning("Coral %s from session %s refused: %s", tool, call.session_id, message)
        return ServerToolResult(message, is_error=True)

    async def handle(call: ServerToolCall) -> ServerToolResult:
        if call.operation_id is None:
            return refuse(call, NO_OPERATION_ID)
        if not call.runner_proven:
            return refuse(call, NOT_THE_RUNNER)
        if dispatcher is None:
            return refuse(call, ENGINE_NOT_RUNNING)
        workspace_id = current_workspace_id()
        try:
            binding = await asyncio.to_thread(
                bindings.find_by_session, workspace_id, call.session_id
            )
        except Exception:
            _logger.exception(
                "Coral %s from session %s: the binding lookup failed", tool, call.session_id
            )
            return ServerToolResult(LOOKUP_FAILED, is_error=True)
        if binding is None:
            _logger.info(
                "Coral %s from session %s refused: not_run_member (no binding)",
                tool,
                call.session_id,
            )
            return ServerToolResult(replies.not_run_member().to_json())
        engine_call = EngineToolCall(
            binding=binding,
            tool=tool,
            arguments=call.arguments,
            operation_id=call.operation_id,
        )
        try:
            reply = await dispatcher.dispatch(engine_call)
        except TransportError as exc:
            return ServerToolResult(str(exc), is_error=True)
        return ServerToolResult(reply.to_json())

    return handle
