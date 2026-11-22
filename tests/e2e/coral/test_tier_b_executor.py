"""The real claude-sdk executor and ``claude`` CLI use the mock with no proxied HTTP(S) egress."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import coral
import omnigent
import tests.e2e.coral._claude_config_probe as probe
from coral.omni.server.step_agents import checkout_read_paths
from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec
from omnigent.inner.executor import ExecutorError, TurnComplete
from omnigent.inner.sandbox import _default_sandbox_for_platform
from tests.e2e._harness_probes import skip_if_harness_cli_missing
from tests.e2e.conftest import configure_mock_llm, get_mock_message_requests
from tests.e2e.coral._claude_sdk_kit import (
    EgressRecorder,
    collect_turn,
    make_executor,
    mock_only_env,
    probe_tool,
    tool_results,
    tool_search_then_call,
    write_claude_home,
)
from tests.e2e.coral.conftest import CORAL_TIER_B_HARNESS

_MODEL = "mock-coral-tier-b"
_TURN_BOUND_SECONDS = 60


def _set_env(monkeypatch: pytest.MonkeyPatch, changes: dict[str, str | None]) -> None:
    for name, value in changes.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


async def _one_turn(workspace: Path, text: str, *, session_id: str) -> list:
    executor = make_executor(workspace, model=_MODEL, permission_mode="bypassPermissions")
    try:
        async with asyncio.timeout(_TURN_BOUND_SECONDS):
            return await collect_turn(executor, text, session_id=session_id)
    except TimeoutError:
        pytest.fail(f"turn was still running after {_TURN_BOUND_SECONDS}s")
    finally:
        await executor.close()


@pytest.mark.timeout(180)
async def test_scripted_mcp_tool_turn_completes_with_no_proxied_egress(
    isolated_mock_llm_server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    token = f"TIERB-{uuid.uuid4().hex[:8]}"
    call_id = f"toolu_tierb_{token[-8:]}"
    scripted = tool_search_then_call(probe_tool("touch"), {"note": token}, call_id=call_id)
    # Extra entries absorb the CLI's side requests that repeat the prompt.
    configure_mock_llm(
        isolated_mock_llm_server_url, [*scripted, *[{"text": f"done {token}"}] * 3], match=token
    )
    marker = tmp_path / "marker.txt"
    home = write_claude_home(tmp_path, marker=marker)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with EgressRecorder() as recorder:
        env = mock_only_env(
            home=home,
            base_url=isolated_mock_llm_server_url,
            proxy_url=recorder.url,
            inherited=os.environ,
        )
        _set_env(monkeypatch, env)
        events = await _one_turn(workspace, f"Call the tool. {token}", session_id=token)
        egress = recorder.request_lines

    assert [event.message for event in events if isinstance(event, ExecutorError)] == []
    completed = [event for event in events if isinstance(event, TurnComplete)]
    assert completed and f"done {token}" in (completed[-1].response or "")
    assert marker.read_text().splitlines() == [f"touched {token}"]
    requests = get_mock_message_requests(isolated_mock_llm_server_url)
    assert any(f"TOUCHED-{token}" in result for result in tool_results(requests, call_id=call_id))
    assert egress == []


@pytest.mark.timeout(120)
async def test_egress_recorder_sees_model_traffic_aimed_off_the_machine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    home = write_claude_home(tmp_path, marker=tmp_path / "marker.txt")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with EgressRecorder() as recorder:
        env = mock_only_env(
            home=home,
            base_url="https://api.example.invalid",
            proxy_url=recorder.url,
            inherited=os.environ,
        )
        _set_env(monkeypatch, env)
        events = await _one_turn(workspace, "Reply.", session_id=uuid.uuid4().hex[:8])
        egress = recorder.request_lines

    assert [event for event in events if isinstance(event, ExecutorError)]
    assert "CONNECT api.example.invalid:443 HTTP/1.1" in egress


# Logs the keychain item each lookup names, then answers "not found", so no lookup reaches a
# real keychain; the CLI runs ``security`` by its bare name.
_SECURITY_STUB = """#!/bin/sh
service=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-s" ]; then service="$2"; fi
  shift
done
printf '%s\\n' "$service" >> "{log}"
exit 44
"""
# Past the CLI's MCP output limit, so it tries to keep the result under its config dir.
_OVERSIZED_RESULT = "\n".join(f"line {i:06d} " + "x" * 40 for i in range(3000))


async def _allow_every_tool(phase: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(action="POLICY_ACTION_ALLOW", reason="")


async def _oversized_tool(name: str, arguments: dict) -> dict:
    return {"result": _OVERSIZED_RESULT}


# A real CLI in its sandbox wrap, with code it runs there trying the user's Claude config.
@pytest.mark.timeout(240)
async def test_a_coral_cli_keeps_its_claude_config_out_of_the_home(
    isolated_mock_llm_server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A Coral step's real CLI, wrapped in its OS sandbox with a private config dir, completes a
    turn on API-key auth against the mock. Its API key helper, which the CLI runs inside the
    wrap, cannot write the throwaway home's plugins, sessions, session-env, backups or
    .claude.json, or read its session key, credentials or keychain stand-in, and the home is
    unchanged. Every keychain lookup names a per-dir item. An oversized tool result is
    reported unsaved, with the pagination advice, since the dir has no ``projects/``.
    """
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    token = f"TIERB-{uuid.uuid4().hex[:8]}"
    call_id = f"toolu_cfg_{token[-8:]}"
    scripted = tool_search_then_call("mcp__omnigent__dump", {}, call_id=call_id)
    configure_mock_llm(
        isolated_mock_llm_server_url, [*scripted, *[{"text": f"done {token}"}] * 3], match=token
    )
    home, workspace, scratch = (tmp_path / name for name in ("home", "workspace", "tmp"))
    probe.seed_claude_home(home)
    stubs = workspace / "stubbin"
    stubs.mkdir(parents=True)
    scratch.mkdir()
    shutil.copy(probe.__file__, workspace / "probe.py")
    (stubs / "security").write_text(_SECURITY_STUB.format(log=workspace / "security.log"))
    (stubs / "security").chmod(0o755)
    report = workspace / "report.txt"
    helper = shlex.join([sys.executable, str(workspace / "probe.py"), str(report), str(home)])
    harness_root = Path(tempfile.mkdtemp(prefix="crl-", dir="/tmp"))
    try:
        with EgressRecorder() as recorder:
            env = mock_only_env(
                home=home,
                base_url=isolated_mock_llm_server_url,
                proxy_url=recorder.url,
                inherited=os.environ,
            )
            # The kit's throwaway config dir stands in for a user value the host forwards.
            env.update(
                {
                    "CLAUDE_SECURESTORAGE_CONFIG_DIR": str(home / ".claude"),
                    "OMNIGENT_CLAUDE_SDK_NO_SANDBOX": None,
                    "OMNIGENT_HARNESS_TMP_PARENT": str(harness_root),
                    "TMPDIR": str(scratch),
                    "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
                }
            )
            _set_env(monkeypatch, env)
            monkeypatch.setattr(tempfile, "tempdir", None)
            packages = (Path(omnigent.__file__).parent, Path(coral.__file__).parent)
            sandbox = OSEnvSandboxSpec(
                type=_default_sandbox_for_platform().type,
                read_paths=list(checkout_read_paths(packages, Path(sys.prefix))),
                write_paths=["."],
            )
            executor = make_executor(
                workspace,
                model=_MODEL,
                permission_mode="bypassPermissions",
                coral=True,
                os_env=OSEnvSpec(type="caller_process", cwd=str(workspace), sandbox=sandbox),
                isolate_claude_config=True,
                api_key_helper=f"{helper}; printf %s mock-key",
            )
            executor._policy_evaluator = _allow_every_tool  # type: ignore[attr-defined]
            # After the wrap made the only home dir it grants, ~/.npm/_logs.
            before = probe.tree(home)
            executor._tool_executor = _oversized_tool
            dump = {
                "name": "dump",
                "description": "Return a large text.",
                "parameters": {"type": "object", "properties": {}},
            }
            try:
                async with asyncio.timeout(_TURN_BOUND_SECONDS * 2):
                    events = await collect_turn(
                        executor, f"Call the tool. {token}", session_id=token, tools=[dump]
                    )
            except TimeoutError:
                pytest.fail(f"turn was still running after {_TURN_BOUND_SECONDS * 2}s")
            finally:
                await executor.close()
            egress = recorder.request_lines
    finally:
        shutil.rmtree(harness_root, ignore_errors=True)

    assert [event.message for event in events if isinstance(event, ExecutorError)] == []
    completed = [event for event in events if isinstance(event, TurnComplete)]
    assert completed and f"done {token}" in (completed[-1].response or "")
    *verdicts, named = report.read_text().splitlines()
    own = ["config_private yes", "config_writable yes", "projects no", "securestorage_own yes"]
    assert verdicts == [f"{name} no" for name in probe.HOME_CHECKS] + own, verdicts
    config_dir = Path(named.removeprefix("config_dir "))
    assert config_dir.name == "claude_config_dir" and scratch.resolve() in config_dir.parents
    assert probe.tree(home) == before, "the step changed the home"
    log = workspace / "security.log"
    services = log.read_text().splitlines() if log.exists() else []
    assert services or sys.platform != "darwin", "the security stub saw no lookup"
    assert all(re.fullmatch(r"Claude Code.*-[0-9a-f]{8}", name) for name in services), services
    [*_, result] = tool_results(
        get_mock_message_requests(isolated_mock_llm_server_url), call_id=call_id
    )
    # Measured on 2.1.325: "Failed to save output to file: ENOTDIR: ... If this MCP server
    # provides pagination or filtering tools, use them to retrieve specific portions of the data."
    assert "Failed to save output to file" in result, result[:600]
    assert "use them to retrieve specific portions of the data" in result, result[:600]
    assert "has been saved to" not in result, result[:600]
    assert egress == []
