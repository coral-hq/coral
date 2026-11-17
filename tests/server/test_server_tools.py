# CORAL(S10): server tool registry tests (new file).
"""The process-wide registry of tools the server runs for a session's runner."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator

import pytest

from omnigent.server.server_tools import (
    ServerToolCall,
    ServerToolHandler,
    ServerToolResult,
    granted_server_tool,
    register_server_tool,
    run_server_tool,
    server_tool,
)
from omnigent.spec import AgentSpec
from omnigent.spec.types import LocalToolInfo, MCPServerConfig, ToolRuntime
from tests.tools.test_extensions import StubToolProvider, installed_tool_providers, tool_schema

ECHO_TOOL = "coral_test_echo"


@pytest.fixture
def register() -> Iterator[Callable[[str, ServerToolHandler], Callable[[], None]]]:
    """Register server tools for one test and unregister them afterwards."""
    unregisters: list[Callable[[], None]] = []

    def _register(name: str, handler: ServerToolHandler) -> Callable[[], None]:
        unregister = register_server_tool(name, handler)
        unregisters.append(unregister)
        return unregister

    yield _register
    for unregister in unregisters:
        unregister()


def _handler(text: str) -> ServerToolHandler:
    async def handle(call: ServerToolCall) -> ServerToolResult:
        return ServerToolResult(f"{text}:{call.arguments.get('text')}")

    return handle


def _call(**overrides: object) -> ServerToolCall:
    fields: dict[str, object] = {
        "session_id": "conv_server_tools",
        "name": ECHO_TOOL,
        "arguments": {"text": "hi"},
        "operation_id": "mcpop_1",
        "runner_proven": True,
        "actor": {"run_as": "alice@example.com"},
    }
    fields.update(overrides)
    return ServerToolCall(**fields)  # type: ignore[arg-type]


def echo_spec(
    *local_tool_names: str, given: bool = True, mcp_servers: tuple[str, ...] = ()
) -> AgentSpec:
    """A spec :func:`echo_provider` gives the echo tool to unless *given* is false."""
    return AgentSpec(
        spec_version=1,
        skills_filter="none",
        params={"echo": True} if given else {},
        mcp_servers=[
            MCPServerConfig(name=name, transport="stdio", command="true") for name in mcp_servers
        ],
        local_tools=[
            LocalToolInfo(
                name=name,
                path=None,
                language="python",
                runtime=ToolRuntime.CLIENT,
                parameters={"type": "object", "properties": {}},
            )
            for name in local_tool_names
        ],
    )


def echo_provider(consulted: list[AgentSpec] | None = None) -> StubToolProvider:
    """A tool provider offering the echo tool to :func:`echo_spec` specs, recording each spec."""

    def applies(spec: AgentSpec) -> bool:
        if consulted is not None:
            consulted.append(spec)
        return "echo" in spec.params

    return StubToolProvider(tools=(tool_schema(ECHO_TOOL),), applies=applies)


def test_lookup_strips_one_omnigent_prefix_and_misses_cleanly(register) -> None:
    handler = _handler("echo")
    assert server_tool(ECHO_TOOL) is None
    assert server_tool(f"mcp__omnigent__{ECHO_TOOL}") is None

    register(ECHO_TOOL, handler)

    assert server_tool(ECHO_TOOL) is handler
    assert server_tool(f"mcp__omnigent__{ECHO_TOOL}") is handler
    assert server_tool(f"mcp__omnigent__mcp__omnigent__{ECHO_TOOL}") is None
    assert server_tool(f"other__{ECHO_TOOL}") is None
    assert server_tool(f"{ECHO_TOOL}_x") is None
    assert server_tool("") is None
    for malformed in (123, ["x"], {"a": 1}, None):  # a malformed call's name has no handler
        assert server_tool(malformed) is None  # type: ignore[arg-type]
        assert granted_server_tool(malformed, echo_spec()) is None  # type: ignore[arg-type]


def test_registry_unregister_is_identity_checked(
    register, caplog: pytest.LogCaptureFixture
) -> None:
    first, second = _handler("first"), _handler("second")
    unregister_first = register(ECHO_TOOL, first)

    with caplog.at_level(logging.WARNING, logger="omnigent.server.server_tools"):
        unregister_second = register(ECHO_TOOL, second)
    assert server_tool(ECHO_TOOL) is second
    assert [record.getMessage() for record in caplog.records] == [
        f"server tool {ECHO_TOOL!r} replaced an earlier registration"
    ]

    unregister_first()  # replaced: must not remove the newer handler
    assert server_tool(ECHO_TOOL) is second
    unregister_second()
    assert server_tool(ECHO_TOOL) is None
    unregister_second()  # idempotent
    assert server_tool(ECHO_TOOL) is None

    # The same handler registered twice: no warning, and the older registration's
    # unregister keeps the newer one.
    unregister_old = register(ECHO_TOOL, first)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="omnigent.server.server_tools"):
        unregister_new = register(ECHO_TOOL, first)
    assert caplog.records == []
    unregister_old()
    assert server_tool(ECHO_TOOL) is first
    unregister_new()
    assert server_tool(ECHO_TOOL) is None


@pytest.mark.parametrize(
    "name",
    [
        "",
        "bad name",
        "coral_test_echo\n",
        "coral__echo",
        f"mcp__omnigent__{ECHO_TOOL}",
        "sys_advise_models",
        "x" * 257,
        42,
    ],
    ids=[
        "empty",
        "space",
        "trailing-newline",
        "double-underscore",
        "namespaced",
        "framework-sys",
        "too-long",
        "not-a-string",
    ],
)
def test_invalid_server_tool_names_are_refused(name: object) -> None:
    with pytest.raises(ValueError, match="server tool name"):
        register_server_tool(name, _handler("never"))  # type: ignore[arg-type]
    assert server_tool(ECHO_TOOL) is None


@pytest.mark.asyncio
async def test_run_server_tool_turns_handler_failures_into_logged_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def raises(call: ServerToolCall) -> ServerToolResult:
        raise RuntimeError("handler bug")

    async def wrong_type(call: ServerToolCall) -> ServerToolResult:
        return "plain text"  # type: ignore[return-value]

    async def wrong_text(call: ServerToolCall) -> ServerToolResult:
        return ServerToolResult(b"bytes")  # type: ignore[arg-type]

    failed = ServerToolResult("server tool failed; see the server log", is_error=True)
    for handler, traceback in ((raises, True), (wrong_type, False), (wrong_text, False)):
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="omnigent.server.server_tools"):
            assert await run_server_tool(handler, _call()) == failed
        assert len(caplog.records) == 1, handler
        record = caplog.records[0]
        assert record.session_id == "conv_server_tools"  # type: ignore[attr-defined]
        assert (record.exc_info is not None) is traceback, handler

    error = ServerToolResult("[busy] retry", is_error=True)

    async def returns_error(call: ServerToolCall) -> ServerToolResult:
        return error

    assert await run_server_tool(returns_error, _call()) is error
    assert await run_server_tool(_handler("echo"), _call()) == ServerToolResult("echo:hi")


@pytest.mark.asyncio
async def test_run_server_tool_lets_cancellation_through() -> None:
    async def cancelled(call: ServerToolCall) -> ServerToolResult:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_server_tool(cancelled, _call())


def test_granted_server_tool_needs_the_tool_from_a_provider(register) -> None:
    consulted: list[AgentSpec] = []
    handler = _handler("echo")
    provider = echo_provider(consulted)
    granted = echo_spec()
    with installed_tool_providers(provider):
        # Nothing registered: no provider is consulted.
        assert granted_server_tool(ECHO_TOOL, granted) is None
        assert consulted == []

        register(ECHO_TOOL, handler)
        assert granted_server_tool(ECHO_TOOL, granted) is handler
        assert granted_server_tool(f"mcp__omnigent__{ECHO_TOOL}", granted) is handler
        # A spec the provider gives nothing to, e.g. an ordinary agent.
        assert granted_server_tool(ECHO_TOOL, echo_spec(given=False)) is None
        # The agent's own tool of that name wins, as on the runner.
        assert granted_server_tool(ECHO_TOOL, echo_spec(ECHO_TOOL)) is None
        assert granted_server_tool(ECHO_TOOL, echo_spec("other_tool")) is handler
        # A spec MCP server named ``mcp`` owns the prefixed form; the bare name stays granted.
        with_mcp = echo_spec(mcp_servers=("mcp",))
        assert granted_server_tool(f"mcp__omnigent__{ECHO_TOOL}", with_mcp) is None
        assert granted_server_tool(ECHO_TOOL, with_mcp) is handler
        assert granted_server_tool(
            f"mcp__omnigent__{ECHO_TOOL}", echo_spec(mcp_servers=("x",))
        ) is (handler)

    # The runner never registers a provider tool with a framework tool's name (S7).
    framework = StubToolProvider(tools=(tool_schema("load_skill"), tool_schema("web_search")))
    with installed_tool_providers(framework):
        for name in ("load_skill", "web_search"):
            register(name, handler)
            assert granted_server_tool(name, granted) is None

    other = StubToolProvider(tools=(tool_schema(ECHO_TOOL),))
    with installed_tool_providers(provider, other):
        # A name two providers offer is served by neither.
        assert granted_server_tool(ECHO_TOOL, granted) is None
