"""The real claude-sdk executor and ``claude`` CLI talk to the mock and to nothing else."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from omnigent.inner.executor import ExecutorError, TurnComplete
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
async def test_scripted_mcp_tool_turn_completes_with_no_egress(
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
            home=home, base_url=isolated_mock_llm_server_url, proxy_url=recorder.url
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
            home=home, base_url="https://api.example.invalid", proxy_url=recorder.url
        )
        _set_env(monkeypatch, env)
        events = await _one_turn(workspace, "Reply.", session_id=uuid.uuid4().hex[:8])
        egress = recorder.request_lines

    assert [event for event in events if isinstance(event, ExecutorError)]
    assert "CONNECT api.example.invalid:443 HTTP/1.1" in egress
