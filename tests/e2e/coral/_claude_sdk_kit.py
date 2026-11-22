"""Run the real claude-sdk executor and ``claude`` CLI against ``mock_llm_server`` only."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from pathlib import Path
from typing import Any

import claude_agent_sdk

from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor, _find_system_claude
from omnigent.inner.datamodel import OSEnvSpec
from omnigent.inner.executor import ExecutorError, ToolSpec, TurnComplete
from tests.e2e.conftest import (
    _mock_llm_server_process,
    configure_mock_llm,
    get_mock_message_requests,
)

PROBE_MCP_SERVER = Path(__file__).with_name("_probe_mcp_server.py")
PROBE_SERVER_NAME = "probe"
MOCK_API_KEY_HELPER = "printf %s mock-key"
LOCAL_HOSTS = "127.0.0.1,localhost"
_INHERITED_NAMES = frozenset(
    {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "USER", "LOGNAME", "SHELL"}
)
_INHERITED_PREFIXES = ("PYTEST_", "COV_CORE_", "COVERAGE_")
_PROXY_NAMES = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")


_REFUSAL = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


class _RefuseAndRecord(socketserver.StreamRequestHandler):
    server: _RecordingServer
    timeout = 5

    def handle(self) -> None:
        try:
            line = self.rfile.readline(65536)
        except TimeoutError:
            return
        self.server.request_lines.append(line.decode("latin-1").strip())
        self.wfile.write(_REFUSAL)


class _RecordingServer(socketserver.ThreadingTCPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _RefuseAndRecord)
        self.request_lines: list[str] = []


class EgressRecorder:
    """A local HTTP proxy that refuses every request and records its request line."""

    def __init__(self) -> None:
        self._server = _RecordingServer()
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def request_lines(self) -> list[str]:
        return list(self._server.request_lines)

    def __enter__(self) -> EgressRecorder:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def write_claude_home(root: Path, *, marker: Path) -> Path:
    """Create a fresh ``HOME`` whose ``.claude.json`` declares the stdio probe MCP server."""
    home = root / "home"
    home.mkdir(parents=True)
    server = {
        "type": "stdio",
        "command": sys.executable,
        "args": [str(PROBE_MCP_SERVER), str(marker)],
    }
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {PROBE_SERVER_NAME: server}}))
    return home


def mock_only_env(
    *, home: Path, base_url: str, proxy_url: str, inherited: Mapping[str, str]
) -> dict[str, str | None]:
    """Changes that leave the CLI only the mock; ``None`` unsets each non-allowlisted name.

    :param base_url: Mock root URL with no ``/v1`` suffix, e.g. ``"http://127.0.0.1:5123"``.
    """
    changes: dict[str, str | None] = {
        name: None
        for name in inherited
        if name not in _INHERITED_NAMES and not name.startswith(_INHERITED_PREFIXES)
    }
    proxies = {**dict.fromkeys(_PROXY_NAMES, proxy_url), "NO_PROXY": LOCAL_HOSTS}
    changes.update(proxies)
    changes.update({name.lower(): value for name, value in proxies.items()})
    changes.update(
        {
            "HOME": str(home),
            # The CLI reads .claude.json and settings.json here, not in the real ~/.claude.
            "CLAUDE_CONFIG_DIR": str(home),
            "ANTHROPIC_BASE_URL": base_url,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            # The CLI sandbox cannot see an editable checkout outside the workspace.
            "OMNIGENT_CLAUDE_SDK_NO_SANDBOX": "1",
        }
    )
    return changes


def make_executor(
    workspace: Path,
    *,
    model: str,
    permission_mode: str,
    coral: bool = False,
    os_env: OSEnvSpec | None = None,
    isolate_claude_config: bool = False,
    api_key_helper: str = MOCK_API_KEY_HELPER,
) -> ClaudeSDKExecutor:
    """
    The executor the harness builds; ``coral`` sets the credential and policy flags a
    ``params.coral`` spec sets, and ``isolate_claude_config`` its private config dir.
    """
    return ClaudeSDKExecutor(
        cwd=str(workspace),
        os_env=os_env,
        model=model,
        permission_mode=permission_mode,
        api_key_helper=api_key_helper,
        require_api_credential=coral,
        tool_call_policy_hook=coral,
        isolate_claude_config=isolate_claude_config,
    )


def probe_tool(tool: str) -> str:
    return f"mcp__{PROBE_SERVER_NAME}__{tool}"


def tool_search_then_call(tool: str, arguments: dict[str, Any], *, call_id: str) -> list[dict]:
    """Script ToolSearch then the tool call; the CLI hides MCP tools behind ToolSearch."""
    search = json.dumps({"query": f"select:{tool}", "max_results": 1})
    search_call = {"name": "ToolSearch", "arguments": search, "call_id": f"{call_id}_search"}
    tool_call = {"name": tool, "arguments": json.dumps(arguments), "call_id": call_id}
    return [{"tool_calls": [search_call]}, {"tool_calls": [tool_call]}]


def tool_results(message_requests: list[dict], *, call_id: str) -> list[str]:
    """Serialized ``tool_result`` blocks for ``call_id`` in mock message-request entries."""
    found = []
    for entry in message_requests:
        for message in entry["body"].get("messages", []):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and block.get("tool_use_id") == call_id
                ):
                    found.append(json.dumps(block))
    return found


async def collect_turn(
    executor: ClaudeSDKExecutor, text: str, *, session_id: str, tools: list[ToolSpec] | None = None
) -> list:
    messages = [{"role": "user", "content": text, "session_id": session_id}]
    return [event async for event in executor.run_turn(messages, tools or [], "")]


def cli_versions() -> dict[str, str]:
    """Versions the executor would run: the system ``claude`` it resolves and the SDK."""
    cli = _find_system_claude()
    output = subprocess.run([cli, "--version"], capture_output=True, text=True, check=False)
    return {
        "cli_path": cli,
        "cli_version": output.stdout.strip(),
        "sdk_version": claude_agent_sdk.__version__,
    }


def apply_env(changes: dict[str, str | None], environ: MutableMapping[str, str]) -> None:
    for name, value in changes.items():
        if value is None:
            environ.pop(name, None)
        else:
            environ[name] = value


async def run_probe_case(
    *,
    model: str,
    permission_mode: str,
    turn_timeout_s: float,
    tool: str | None = None,
    arguments: dict[str, Any] | None = None,
    policy_evaluator: Callable[[str, dict], Awaitable[object]] | None = None,
    extra_queues: tuple[dict[str, Any], ...] = (),
    extra_env: dict[str, str | None] | None = None,
    coral: bool = False,
) -> dict[str, Any]:
    """One turn in a fresh temp dir, mock and egress recorder; returns what was observed.

    It swaps ``os.environ`` for the turn, so it is for probe scripts, not pytest.
    """
    saved_environ = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix="claude-sdk-probe-") as temp_dir:
            return await _run_probe_turn(
                Path(temp_dir),
                model=model,
                permission_mode=permission_mode,
                turn_timeout_s=turn_timeout_s,
                tool=tool,
                arguments=arguments,
                policy_evaluator=policy_evaluator,
                extra_queues=extra_queues,
                extra_env=extra_env or {},
                coral=coral,
            )
    finally:
        os.environ.clear()
        os.environ.update(saved_environ)


async def _run_probe_turn(
    root: Path,
    *,
    model: str,
    permission_mode: str,
    turn_timeout_s: float,
    tool: str | None,
    arguments: dict[str, Any] | None,
    policy_evaluator: Callable[[str, dict], Awaitable[object]] | None,
    extra_queues: tuple[dict[str, Any], ...],
    extra_env: dict[str, str | None],
    coral: bool,
) -> dict[str, Any]:
    token = f"PROBE-{uuid.uuid4().hex[:8]}"
    call_id = f"toolu_{token.lower().replace('-', '_')}"
    marker = root / "marker.txt"
    workspace = root / "workspace"
    workspace.mkdir()
    home = write_claude_home(root, marker=marker)
    mock_server = contextlib.contextmanager(_mock_llm_server_process)(root)
    with mock_server as base_url, EgressRecorder() as recorder:
        scripted = []
        if tool is not None:
            scripted = tool_search_then_call(probe_tool(tool), arguments or {}, call_id=call_id)
        configure_mock_llm(base_url, [*scripted, *[{"text": f"done {token}"}] * 3], match=token)
        for queue in extra_queues:
            configure_mock_llm(base_url, **queue)
        changes = mock_only_env(
            home=home, base_url=base_url, proxy_url=recorder.url, inherited=os.environ
        )
        apply_env(changes, os.environ)
        apply_env(extra_env, os.environ)
        executor = make_executor(
            workspace, model=model, permission_mode=permission_mode, coral=coral
        )
        if policy_evaluator is not None:
            executor._policy_evaluator = policy_evaluator  # type: ignore[attr-defined]
        events: list = []
        turn_timed_out = False
        started = time.monotonic()
        try:
            async with asyncio.timeout(turn_timeout_s):
                events = await collect_turn(executor, f"Call the tool. {token}", session_id=token)
        except TimeoutError:
            turn_timed_out = True
        finally:
            await executor.close()
        elapsed = time.monotonic() - started
        requests = get_mock_message_requests(base_url)
        egress = recorder.request_lines
    completed = [event.response or "" for event in events if isinstance(event, TurnComplete)]
    return {
        "token": token,
        "model": model,
        "permission_mode": permission_mode,
        "elapsed_s": round(elapsed, 1),
        "turn_timed_out": turn_timed_out,
        "completed_with_token": any(f"done {token}" in text for text in completed),
        "errors": [event.message[:300] for event in events if isinstance(event, ExecutorError)],
        "mock_message_requests": len(requests),
        "egress_request_lines": egress,
        "marker": marker.read_text().splitlines() if marker.exists() else [],
        "tool_results": [result[:300] for result in tool_results(requests, call_id=call_id)],
    }
