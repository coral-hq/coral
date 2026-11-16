"""Coral claude-sdk sessions enforce TOOL_CALL policy and have no native subagent tools."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from omnigent.inner.executor import ExecutorError, TurnComplete
from omnigent.inner.hook_scripts.subagent_router import AGENT_TOOL_NAMES
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
_TURN_BOUND_SECONDS = 90
_DENY_REASON = "probe tools are denied"


def _deny_probe_tools(calls: list[str]):
    async def evaluate(phase: str, payload: dict) -> SimpleNamespace:
        name = str(payload.get("name", ""))
        calls.append(name)
        denied = phase == "PHASE_TOOL_CALL" and name.startswith(probe_tool(""))
        action = "POLICY_ACTION_DENY" if denied else "POLICY_ACTION_ALLOW"
        return SimpleNamespace(action=action, reason=_DENY_REASON)

    return evaluate


async def _scripted_turn(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    *,
    scripted: list[dict],
    token: str,
    permission_mode: str,
    coral: bool,
    calls: list[str] | None = None,
) -> tuple[list, Path, list[str]]:
    configure_mock_llm(base_url, [*scripted, *[{"text": f"done {token}"}] * 3], match=token)
    marker = root / "marker.txt"
    home = write_claude_home(root, marker=marker)
    workspace = root / "workspace"
    workspace.mkdir()
    with EgressRecorder() as recorder:
        env = mock_only_env(
            home=home, base_url=base_url, proxy_url=recorder.url, inherited=os.environ
        )
        for name, value in env.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        executor = make_executor(
            workspace, model=_MODEL, permission_mode=permission_mode, coral=coral
        )
        if calls is not None:
            executor._policy_evaluator = _deny_probe_tools(calls)  # type: ignore[attr-defined]
        try:
            async with asyncio.timeout(_TURN_BOUND_SECONDS):
                events = await collect_turn(executor, f"Call the tool. {token}", session_id=token)
        except TimeoutError:
            pytest.fail(f"turn was still running after {_TURN_BOUND_SECONDS}s")
        finally:
            await executor.close()
        egress = recorder.request_lines
    return events, marker, egress


def _assert_completed(events: list, token: str) -> None:
    assert [event.message for event in events if isinstance(event, ExecutorError)] == []
    completed = [event for event in events if isinstance(event, TurnComplete)]
    assert completed and f"done {token}" in (completed[-1].response or "")


@pytest.mark.timeout(240)
@pytest.mark.parametrize("permission_mode", ["default", "bypassPermissions", "auto"])
async def test_coral_session_denies_a_connector_tool_in_every_mode(
    isolated_mock_llm_server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    permission_mode: str,
) -> None:
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    token = f"GATE-{uuid.uuid4().hex[:8]}"
    call_id = f"toolu_gate_{token[-8:]}"
    calls: list[str] = []

    events, marker, egress = await _scripted_turn(
        tmp_path,
        monkeypatch,
        isolated_mock_llm_server_url,
        scripted=tool_search_then_call(probe_tool("touch"), {"note": token}, call_id=call_id),
        token=token,
        permission_mode=permission_mode,
        coral=True,
        calls=calls,
    )

    _assert_completed(events, token)
    assert not marker.exists()
    assert calls.count(probe_tool("touch")) == 1
    requests = get_mock_message_requests(isolated_mock_llm_server_url)
    results = tool_results(requests, call_id=call_id)
    assert results and all(_DENY_REASON in result for result in results)
    assert egress == []


@pytest.mark.timeout(180)
async def test_non_coral_session_keeps_upstream_policy_gating(
    isolated_mock_llm_server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    token = f"UPSTREAM-{uuid.uuid4().hex[:8]}"
    call_id = f"toolu_upstream_{token[-8:]}"
    calls: list[str] = []

    events, marker, _ = await _scripted_turn(
        tmp_path,
        monkeypatch,
        isolated_mock_llm_server_url,
        scripted=tool_search_then_call(probe_tool("touch"), {"note": token}, call_id=call_id),
        token=token,
        permission_mode="bypassPermissions",
        coral=False,
        calls=calls,
    )

    _assert_completed(events, token)
    assert marker.read_text().splitlines() == [f"touched {token}"]
    assert probe_tool("touch") not in calls


@pytest.mark.timeout(180)
@pytest.mark.parametrize("tool", AGENT_TOOL_NAMES)
async def test_coral_session_has_no_native_subagent_tools(
    isolated_mock_llm_server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
) -> None:
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    token = f"SPAWN-{uuid.uuid4().hex[:8]}"
    call_id = f"toolu_spawn_{token[-8:]}"
    arguments = {
        "description": "rogue",
        "prompt": "touch a file",
        "subagent_type": "general-purpose",
    }

    events, _, egress = await _scripted_turn(
        tmp_path,
        monkeypatch,
        isolated_mock_llm_server_url,
        scripted=tool_search_then_call(tool, arguments, call_id=call_id),
        token=token,
        permission_mode="bypassPermissions",
        coral=True,
        calls=[],
    )

    _assert_completed(events, token)
    requests = get_mock_message_requests(isolated_mock_llm_server_url)
    results = tool_results(requests, call_id=call_id)
    assert results and all(f"No such tool available: {tool}" in result for result in results)
    assert egress == []
