"""The real claude-sdk executor and ``claude`` CLI use the mock with no proxied HTTP(S) egress."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
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
from omnigent.inner import claude_sdk_executor
from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec
from omnigent.inner.executor import ExecutorError, TurnComplete
from omnigent.inner.sandbox import _default_sandbox_for_platform
from tests.e2e._harness_probes import skip_if_harness_cli_missing
from tests.e2e.conftest import configure_mock_llm, get_mock_message_requests
from tests.e2e.coral._claude_sdk_kit import (
    PROBE_MCP_SERVER,
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


def _request_shapes(mock_url: str, token: str) -> set[tuple[tuple[str, ...], str]]:
    """Each Messages request of the turn with ``token``: its sorted betas and ``thinking``."""
    return {
        (tuple(sorted(entry["betas"])), json.dumps(entry["body"].get("thinking"), sort_keys=True))
        for entry in get_mock_message_requests(mock_url)
        if token in json.dumps(entry["body"])
    }


# A real CLI on the direct-key path, where no gateway switch turns its betas off.
@pytest.mark.timeout(300)
async def test_a_coral_direct_key_cli_sends_the_same_requests_through_its_proxy(
    isolated_mock_llm_server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    The ``anthropic-beta`` header and the ``thinking`` field of every model request a Coral
    step's real CLI makes on an API key, as the mock upstream records them, in three launches:
    as before the credential proxy (the CLI on the endpoint itself), through the proxy, and
    through the proxy with the CLI told its base URL is the Anthropic API, which the executor
    does only for an upstream that is. The proxy changes neither; the switch only adds betas;
    and the proxy refuses none of the CLI's requests in either mode.
    """
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    mock = isolated_mock_llm_server_url
    home = write_claude_home(tmp_path, marker=tmp_path / "marker.txt")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    caplog.set_level(logging.WARNING, logger="omnigent.inner.claude_gateway_shim")
    launches = {
        "unproxied": {"IS_POSIX": False},
        "proxied": {},
        "assumed_first_party": {"_is_first_party_url": lambda url: True},
    }
    shapes: dict[str, set[tuple[tuple[str, ...], str]]] = {}
    proxied: dict[str, bool] = {}
    with EgressRecorder() as recorder:
        _set_env(
            monkeypatch,
            mock_only_env(home=home, base_url=mock, proxy_url=recorder.url, inherited=os.environ),
        )
        for launch, patches in launches.items():
            token = f"TIERB-{uuid.uuid4().hex[:8]}"
            configure_mock_llm(mock, [{"text": f"done {token}"}] * 4, match=token)
            with monkeypatch.context() as patched:
                for name, value in patches.items():
                    patched.setattr(claude_sdk_executor, name, value)
                executor = make_executor(
                    workspace, model=_MODEL, permission_mode="bypassPermissions", coral=True
                )
                executor._policy_evaluator = _allow_every_tool  # type: ignore[attr-defined]
                try:
                    async with asyncio.timeout(_TURN_BOUND_SECONDS):
                        events = await collect_turn(executor, f"Reply. {token}", session_id=token)
                except TimeoutError:
                    pytest.fail(f"the {launch} turn was still running after 60s")
                finally:
                    proxied[launch] = executor._gateway_shim is not None
                    await executor.close()
            assert [e.message for e in events if isinstance(e, ExecutorError)] == [], launch
            completed = [event for event in events if isinstance(event, TurnComplete)]
            assert completed and f"done {token}" in (completed[-1].response or ""), launch
            shapes[launch] = _request_shapes(mock, token)
        egress = recorder.request_lines

    print("request shapes:", json.dumps({k: sorted(v) for k, v in shapes.items()}))
    assert proxied == {"unproxied": False, "proxied": True, "assumed_first_party": True}
    assert egress == []
    refusals = [
        record.getMessage()
        for record in caplog.records
        if record.name == "omnigent.inner.claude_gateway_shim"
    ]
    assert refusals == [], refusals
    assert shapes["unproxied"] and shapes["proxied"] == shapes["unproxied"]
    betas = {
        launch: {beta for flags, _ in seen for beta in flags} for launch, seen in shapes.items()
    }
    thinking = {launch: {field for _, field in seen} for launch, seen in shapes.items()}
    # No gateway switch here, so the CLI keeps its experimental betas and says how it thinks.
    assert "claude-code-20250219" in betas["proxied"]
    assert thinking["proxied"] != {"null"}, thinking
    # Told it is on the Anthropic API, the CLI sends the same thinking field and more betas.
    # Measured on 2.1.325: cache-diagnosis-2026-04-07, prompt-caching-scope-2026-01-05 and
    # thinking-binding-controls-2026-08-01, betas that CLI adds only on a first-party URL.
    assert thinking["assumed_first_party"] == thinking["proxied"]
    restored = betas["assumed_first_party"] - betas["proxied"]
    assert betas["assumed_first_party"] > betas["proxied"], sorted(restored)
    assert "prompt-caching-scope-2026-01-05" in restored, sorted(restored)


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


def _security_stub(workspace: Path) -> tuple[Path, Path]:
    """A ``security`` stub dir in the workspace, which the wrap reads, and the log it writes."""
    stubs, log = workspace / "stubbin", workspace / "security.log"
    stubs.mkdir(parents=True)
    (stubs / "security").write_text(_SECURITY_STUB.format(log=log))
    (stubs / "security").chmod(0o755)
    return stubs, log


def _step_sandbox() -> OSEnvSandboxSpec:
    """The platform's default sandbox as a step gets it, writable only in the workspace."""
    packages = (Path(omnigent.__file__).parent, Path(coral.__file__).parent)
    return OSEnvSandboxSpec(
        type=_default_sandbox_for_platform().type,
        read_paths=list(checkout_read_paths(packages, Path(sys.prefix))),
        write_paths=["."],
    )


def _hashed_lookups(log: Path) -> list[str]:
    """The keychain items the stub was asked for; none may be the default, unhashed ones."""
    services = log.read_text().splitlines() if log.exists() else []
    assert services or sys.platform != "darwin", "the security stub saw no lookup"
    assert all(re.fullmatch(r"Claude Code.*-[0-9a-f]{8}", name) for name in services), services
    return services


# A real CLI in its sandbox wrap, with code it runs there trying the user's Claude config.
@pytest.mark.timeout(240)
async def test_a_coral_cli_keeps_its_claude_config_out_of_the_home(
    isolated_mock_llm_server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    A Coral step's real CLI, wrapped in its OS sandbox with a private config dir, completes a
    turn on API-key auth against the mock, through its executor's credential proxy. Its API
    key helper, which the CLI runs inside the wrap, cannot write the throwaway home's plugins,
    sessions, session-env, backups or .claude.json, or read its session key, credentials or
    keychain stand-in, and the home is unchanged. That helper's environment holds the proxy's
    session token and nowhere the model key, and the proxy refuses none of the CLI's requests.
    Every keychain lookup names a per-dir item. An oversized tool result is reported unsaved,
    with the pagination advice, since the dir has no ``projects/``.
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
    stubs, log = _security_stub(workspace)
    scratch.mkdir()
    shutil.copy(probe.__file__, workspace / "probe.py")
    report = workspace / "report.txt"
    model_key = f"sk-ant-test-{secrets.token_hex(16)}"
    # The probe gets the key's length and digest, and looks for it in its own environment.
    probe_argv = [sys.executable, str(workspace / "probe.py"), str(report), str(home), ""]
    helper = shlex.join([*probe_argv, probe.secret_spec(model_key)])
    # The CLI's helper only prints its session token, so the probe runs in front of that.
    monkeypatch.setattr(
        claude_sdk_executor,
        "_PROXY_TOKEN_HELPER",
        f"{helper}; {claude_sdk_executor._PROXY_TOKEN_HELPER}",
    )
    harness_root = Path(tempfile.mkdtemp(prefix="crl-", dir="/tmp"))
    caplog.set_level(logging.WARNING, logger="omnigent.inner.claude_gateway_shim")
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
            sandbox = _step_sandbox()
            executor = make_executor(
                workspace,
                model=_MODEL,
                permission_mode="bypassPermissions",
                coral=True,
                os_env=OSEnvSpec(type="caller_process", cwd=str(workspace), sandbox=sandbox),
                isolate_claude_config=True,
                api_key_helper=f"printf %s {model_key}",
                gateway_base_url=isolated_mock_llm_server_url,
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
    own = ["config_private yes", "config_writable yes", "projects no", "config_seeded no"]
    own += ["seed_source_write no", "securestorage_own yes", "proxy_token yes", "model_key no"]
    assert verdicts == [f"{name} no" for name in probe.HOME_CHECKS] + own, verdicts
    config_dir = Path(named.removeprefix("config_dir "))
    assert config_dir.name == "claude_config_dir" and scratch.resolve() in config_dir.parents
    assert not list(scratch.glob("omnigent-osenv-*")), "close left a launch scratch"
    assert probe.tree(home) == before, "the step changed the home"
    # The pinned CLI needs no route the proxy does not forward, and always sent its token.
    refusals = [
        record.getMessage()
        for record in caplog.records
        if record.name == "omnigent.inner.claude_gateway_shim"
    ]
    assert refusals == [], refusals
    _hashed_lookups(log)
    [*_, result] = tool_results(
        get_mock_message_requests(isolated_mock_llm_server_url), call_id=call_id
    )
    # Measured on 2.1.325: "Failed to save output to file: ENOTDIR: ... If this MCP server
    # provides pagination or filtering tools, use them to retrieve specific portions of the data."
    assert "Failed to save output to file" in result, result[:600]
    assert "use them to retrieve specific portions of the data" in result, result[:600]
    assert "has been saved to" not in result, result[:600]
    assert egress == []


# A real non-Coral CLI in its sandbox wrap: its user MCP servers come from a read-only seed.
@pytest.mark.timeout(240)
async def test_a_sandboxed_agent_loads_its_mcp_servers_without_the_home(
    isolated_mock_llm_server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    claude_config_seed_source: None,
) -> None:
    """
    A non-Coral agent's real CLI, wrapped by default with its own config dir, starts the user
    MCP server from the throwaway config's ``.claude.json`` inside the wrap and calls it, while a
    server the user disabled for this project stays off. That server's start-up code cannot
    write the home's plugins, sessions, session-env, backups or ``.claude.json``, or read its
    session key, credentials or keychain stand-in, or write the seed; its own dir holds the
    seeded copy. The home is unchanged, every keychain lookup names a per-dir item, and nothing
    leaves the machine.
    """
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    token = f"TIERB-{uuid.uuid4().hex[:8]}"
    call_id = f"toolu_seed_{token[-8:]}"
    tool = f"mcp__{probe.SEED_SERVER}__touch"
    scripted = tool_search_then_call(tool, {"note": token}, call_id=call_id)
    configure_mock_llm(
        isolated_mock_llm_server_url, [*scripted, *[{"text": f"done {token}"}] * 3], match=token
    )
    home, workspace, scratch = (tmp_path / name for name in ("home", "workspace", "tmp"))
    probe.seed_claude_home(home)
    stubs, log = _security_stub(workspace)
    scratch.mkdir()
    for script in (probe.__file__, PROBE_MCP_SERVER):
        shutil.copy(script, workspace / Path(script).name)
    report, disabled_report = workspace / "report.txt", workspace / "disabled-report.txt"
    harness_root = Path(tempfile.mkdtemp(prefix="crl-", dir="/tmp"))
    try:
        with EgressRecorder() as recorder:
            env = mock_only_env(
                home=home,
                base_url=isolated_mock_llm_server_url,
                proxy_url=recorder.url,
                inherited=os.environ,
            )
            # The kit's throwaway config dir stands in for one the host forwards, so even an
            # unwrapped CLI would ask only for hashed keychain items.
            env.update(
                {
                    "OMNIGENT_CLAUDE_SDK_NO_SANDBOX": None,
                    "OMNIGENT_HARNESS_TMP_PARENT": str(harness_root),
                    "TMPDIR": str(scratch),
                    "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
                }
            )
            _set_env(monkeypatch, env)
            monkeypatch.setattr(tempfile, "tempdir", None)
            executor = make_executor(
                workspace,
                model=_MODEL,
                permission_mode="bypassPermissions",
                os_env=OSEnvSpec(
                    type="caller_process", cwd=str(workspace), sandbox=_step_sandbox()
                ),
            )
            seed = executor._claude_config_seed_path  # type: ignore[attr-defined]
            assert seed is not None and not seed.parent.exists()

            def server(marker: Path, *probe_args: Path) -> dict:
                command = [str(workspace / PROBE_MCP_SERVER.name), str(marker)]
                probe_env = {"CLAUDE_CONFIG_PROBE": "\n".join(map(str, probe_args))}
                return {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": command,
                    "env": probe_env,
                }

            user_config = {
                "mcpServers": {
                    probe.SEED_SERVER: server(workspace / "marker.txt", report, home, seed),
                    "disabled-probe": server(workspace / "disabled.txt", disabled_report, home),
                },
                "projects": {str(workspace.resolve()): {"disabledMcpServers": ["disabled-probe"]}},
                "oauthAccount": {"emailAddress": "user@example.test"},
            }
            (home / ".claude.json").write_text(json.dumps(user_config))
            before = probe.tree(home)
            try:
                with caplog.at_level(logging.INFO, logger="omnigent.inner.claude_sdk_executor"):
                    async with asyncio.timeout(_TURN_BOUND_SECONDS * 2):
                        events = await collect_turn(
                            executor, f"Call the tool. {token}", session_id=token
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
    [*_, result] = tool_results(
        get_mock_message_requests(isolated_mock_llm_server_url), call_id=call_id
    )
    assert f"TOUCHED-{token}" in result, result[:600]
    *verdicts, named = report.read_text().splitlines()
    own = ["config_private yes", "config_writable yes", "projects no", "config_seeded yes"]
    own += ["seed_source_write no", "securestorage_own yes"]
    assert verdicts == [f"{name} no" for name in probe.HOME_CHECKS] + own, verdicts
    config_dir = Path(named.removeprefix("config_dir "))
    assert config_dir.name == "claude_config_dir" and scratch.resolve() in config_dir.parents
    assert not list(scratch.glob("omnigent-osenv-*")), "close left a launch scratch"
    assert not disabled_report.exists(), "a server the user disabled started in the sandbox"
    # Logging stores a lone mapping argument as the record's args.
    [init] = [
        record.args
        for record in caplog.records
        if record.msg == "Claude CLI system message: %s"
        and isinstance(record.args, dict)
        and record.args.get("subtype") == "init"
    ]
    statuses = {server["name"]: server["status"] for server in init["mcp_servers"]}
    # Measured on 2.1.325: "pending" at init, as the CLI starts MCP servers in the background.
    assert statuses[probe.SEED_SERVER] in ("pending", "connected"), statuses
    assert statuses.get("disabled-probe") in (None, "disabled"), statuses
    assert probe.tree(home) == before, "the agent changed the home"
    assert not seed.parent.exists(), "close left the seed behind"
    _hashed_lookups(log)
    assert egress == []
