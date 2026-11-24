"""Run the real claude-sdk executor and ``claude`` CLI against ``mock_llm_server`` only."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shlex
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass
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

# The programs that reach a keychain by name. ``gh`` is one because the real one runs
# /usr/bin/security by its full path, which no ``security`` stand-in on PATH intercepts.
KEYCHAIN_PROGRAMS = ("security", "gh")
_STUB_SCRIPT = r"""#!/bin/sh
# Test stand-in for @PROGRAM@: answers as a machine with no login. It records bounded names
# only (a subcommand, a keychain service), never an account, a secret, an input or an output.
exec 2>/dev/null
word() {
  case $1 in
    '' | *[!abcdefghijklmnopqrstuvwxyz-]*) word=other ;;
    *) word=$1; [ "${#1}" -le 40 ] || word=other ;;
  esac
}
@NAMES@
printf '%s\t%s\t%s\n' @PROGRAM@ "$call" "$item" >> @LOG@
exit @STATUS@
"""
# The subcommand, and the service of the last ``-s``.
_SECURITY_NAMES = r"""word "${1-}"
call=$word
item=
while [ "$#" -gt 1 ]; do
  if [ "$1" = -s ]; then
    case $2 in
      '' | *[!ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\ ._:-]*) item=other ;;
      *) item=$2; [ "${#2}" -le 64 ] || item=other ;;
    esac
  fi
  shift
done"""
# The command and its subcommand.
_GH_NAMES = r"""word "${1-}"
call=$word
word "${2-}"
call="$call $word"
item="""
# Each stand-in's names and its status: the real ``security``'s "item not found", and what
# ``gh auth token`` exits with when logged out.
_STUBS = {"security": (_SECURITY_NAMES, 44), "gh": (_GH_NAMES, 1)}
# A line as a stand-in writes it: the program, one or two bounded words, a bounded service.
_LOG_LINE = re.compile(r"(security|gh)\t[a-z-]{1,40}( [a-z-]{1,40})?\t[A-Za-z0-9 ._:-]{0,64}")
# The only calls a mock stack may make, as log lines: the CLI's keychain reads and its
# lock-state query (the shapes CLI 2.1.325 holds), and the login checks through gh of
# Omnigent's readiness probe and of the CLI. A write (``-i``, ``add-``, ``delete-``), another
# item, or a name a stand-in bounded to ``other`` is unexpected.
_EXPECTED_CALLS = re.compile(
    r"security\tfind-generic-password\tClaude Code(-credentials)?(-[0-9a-f]{8})?"
    r"|security\tfind-generic-password\tClaude Code-(device-keys|doctor-probe)"
    r"|security\tshow-keychain-info\t"
    r"|gh\tauth (token|status)\t"
)


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


def _shown(line: str) -> str:
    """A log line for a message: its names, or ``malformed`` for one no stand-in writes."""
    return " ".join(line.split("\t")).rstrip() if _LOG_LINE.fullmatch(line) else "malformed"


def _unlisted(line: str) -> str:
    """A log line for a failure: its subcommand and item apart, as the stand-in bounded them."""
    if not _LOG_LINE.fullmatch(line):
        return "malformed"
    program, call, item = line.split("\t")
    return f"{program} subcommand {call!r} item {item!r}"


@dataclass(frozen=True)
class KeychainStubs:
    """
    Stand-ins for :data:`KEYCHAIN_PROGRAMS` in ``directory``, and the ``log`` of what they
    were asked: one line of bounded names per call, ``program<TAB>call<TAB>item``.
    """

    directory: Path
    log: Path

    def first_on(self, env: Mapping[str, str]) -> dict[str, str]:
        """
        ``env`` with the stand-ins first on ``PATH``. An empty or missing ``PATH`` gains no
        empty entry, which would search the working directory.
        """
        entries = filter(None, (str(self.directory), env.get("PATH", "")))
        return {**env, "PATH": os.pathsep.join(entries)}

    def _lines(self) -> list[str]:
        try:
            return self.log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def calls(self) -> list[str]:
        """Each call's names, oldest first: ``security find-generic-password Claude Code``."""
        return [_shown(line) for line in self._lines()]

    def unexpected(self) -> list[str]:
        """
        The calls a mock stack should not make, each naming what to review:
        ``security subcommand 'add-generic-password' item 'Claude Code'``.
        """
        return [_unlisted(line) for line in self._lines() if not _EXPECTED_CALLS.fullmatch(line)]

    def bypassed(self, path: str | None) -> list[str]:
        """
        The programs a process with this ``PATH`` would find elsewhere than these stand-ins,
        or nowhere, so the answer is one on macOS and Linux; nothing is executed. An empty
        or relative entry ahead of them searches that process's own directory, so it counts
        for every program.
        """
        entries = (path or "").split(os.pathsep)
        own = str(self.directory)
        ahead = entries[: entries.index(own)] if own in entries else entries
        if not path or not all(os.path.isabs(entry) for entry in ahead):
            return list(KEYCHAIN_PROGRAMS)
        return [
            program
            for program in KEYCHAIN_PROGRAMS
            if not self._is_own(program, shutil.which(program, path=path))
        ]

    def _is_own(self, program: str, found: str | None) -> bool:
        try:
            return found is not None and os.path.samefile(found, self.directory / program)
        except OSError:
            return False


def install_keychain_stubs(directory: Path, *, log: Path | None = None) -> KeychainStubs:
    """
    Write the stand-ins into ``directory``, owner-only, and start their log: by default
    ``calls.log`` beside it. The same on every platform.

    ``security`` exits 44 and ``gh`` exits 1; neither prints or reads anything, and a log
    that cannot be written changes neither. A directory this creates is owner-only too.
    """
    directory = Path(os.path.abspath(directory))
    for missing in (*reversed(directory.parents), directory):
        if not missing.exists():
            missing.mkdir(mode=0o700)
    directory.chmod(0o700)
    log = directory.parent / "calls.log" if log is None else Path(os.path.abspath(log))
    os.close(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600))
    for program, (names, status) in _STUBS.items():
        script = _STUB_SCRIPT.replace("@NAMES@", names).replace("@PROGRAM@", program)
        script = script.replace("@LOG@", shlex.quote(str(log))).replace("@STATUS@", str(status))
        (directory / program).write_text(script)
        (directory / program).chmod(0o700)
    return KeychainStubs(directory, log)


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
    gateway_base_url: str | None = None,
) -> ClaudeSDKExecutor:
    """
    The executor the harness builds; ``coral`` sets the credential and policy flags a
    ``params.coral`` spec sets, and ``isolate_claude_config`` its private config dir. With
    ``gateway_base_url`` it is built as for an API key that names its own endpoint.
    """
    gateway: dict[str, Any] = {}
    if gateway_base_url is not None:
        gateway = {
            "gateway": True,
            "base_url_override": gateway_base_url,
            "gateway_auth_command": api_key_helper,
        }
    return ClaudeSDKExecutor(
        cwd=str(workspace),
        os_env=os_env,
        model=model,
        permission_mode=permission_mode,
        api_key_helper=api_key_helper,
        require_api_credential=coral,
        tool_call_policy_hook=coral,
        isolate_claude_config=isolate_claude_config,
        **gateway,
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
