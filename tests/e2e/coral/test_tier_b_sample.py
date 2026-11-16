"""A claude-sdk session runs a scripted Omnigent tool through the real server and runner."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest

from tests.e2e._harness_probes import skip_if_harness_cli_missing
from tests.e2e.conftest import (
    configure_mock_llm,
    create_runner_bound_session,
    get_mock_message_requests,
    poll_session_until_terminal,
    register_inline_agent,
    send_user_message_to_session,
)
from tests.e2e.coral._claude_sdk_kit import tool_results
from tests.e2e.coral.conftest import CORAL_TIER_B_HARNESS

_SHELL_TOOL = "mcp__omnigent__sys_os_shell"


@pytest.mark.compat_smoke
@pytest.mark.timeout(300)
def test_claude_sdk_session_runs_scripted_shell_tool_through_the_runner(
    http_client: httpx.Client,
    live_runner_id: str,
    mock_llm_server_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    monkeypatch.setitem(http_client.headers, "x-omnigent-background-session-titles", "off")
    uid = uuid.uuid4().hex[:8]
    model = f"mock-coral-tier-b-{uid}"
    token = f"TIERB-{uid}"
    call_id = f"call_tierb_{uid}"
    prompt = f"Run the Tier B probe {token}."
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    configure_mock_llm(
        mock_llm_server_url,
        [{"text": '{"title":"Tier B sample"}'}],
        key=f"{model}-title",
        match=f"<session>\n{prompt}\n</session>",
    )
    agent_name = register_inline_agent(
        http_client,
        name=model,
        harness=CORAL_TIER_B_HARNESS,
        model=model,
        profile="",
        prompt="Run the requested shell command, then report completion.",
        mock_llm_base_url=mock_llm_server_url,
        # The OS sandbox is not under test, and macOS seatbelt refuses a venv outside the cwd.
        extra_config={
            "os_env": {
                "type": "caller_process",
                "cwd": str(workspace),
                "sandbox": {"type": "none"},
            }
        },
        operator_authored=True,
    )
    shell_call = {
        "call_id": call_id,
        "name": _SHELL_TOOL,
        "arguments": json.dumps({"command": f"printf %s {token}"}),
    }
    # Requests that do not advertise the shell tool (classifier, titles) cannot drain this queue.
    configure_mock_llm(
        mock_llm_server_url,
        [{"tool_calls": [shell_call]}, {"text": f"done {token}"}],
        key=model,
        required_tools=[_SHELL_TOOL],
    )
    session_id = create_runner_bound_session(
        http_client, agent_name=agent_name, runner_id=live_runner_id
    )

    response_id = send_user_message_to_session(http_client, session_id=session_id, content=prompt)
    body = poll_session_until_terminal(
        http_client, session_id=session_id, response_id=response_id, timeout=240
    )

    assert body["status"] == "completed", body["error"]
    requests = get_mock_message_requests(mock_llm_server_url, key=model)
    assert any(token in result for result in tool_results(requests, call_id=call_id)), requests
