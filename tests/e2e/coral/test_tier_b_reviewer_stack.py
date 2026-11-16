"""A generated reviewer step runs through the real server, runner and CLI, and writes nothing."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml

import omnigent
from coral.omni.server.bundles import pack_bundle
from coral.profiles.bundle_spec import Stance, StepRef, build_step_bundle_yaml
from omnigent.runner.identity import OMNIGENT_INTERNAL_WS_ORIGIN
from tests._helpers.operator_agents import post_operator_session
from tests.e2e._harness_probes import skip_if_harness_cli_missing
from tests.e2e.conftest import (
    configure_mock_llm,
    get_mock_message_requests,
    poll_session_until_terminal,
    send_user_message_to_session,
)
from tests.e2e.coral._claude_sdk_kit import tool_results
from tests.e2e.coral.conftest import CORAL_TIER_B_HARNESS

_OPT_IN = "CORAL_TIER_B_STACK_SAMPLE"
_SHELL_TOOL = "mcp__omnigent__sys_os_shell"
_WRITE_TOOL = "mcp__omnigent__sys_os_write"
_SANDBOX_BINARY = {"linux": "bwrap", "darwin": "sandbox-exec"}.get(sys.platform)
ORIGINAL = "orig\n"


@pytest.fixture
def workspace() -> Iterator[Path]:
    # Under $HOME so seatbelt's default /private/var/folders grant cannot hide a missing one.
    root = Path(tempfile.mkdtemp(prefix=".coral-reviewer-stack-", dir=Path.home()))
    (root / "existing.txt").write_text(ORIGINAL)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _reviewer_bundle(*, model: str, mock_llm_server_url: str, workspace: Path) -> bytes:
    config = yaml.safe_load(
        build_step_bundle_yaml(
            StepRef(workflow_id="tier-b", node_id="review", roster_index=0),
            Stance.REVIEWER,
            model=model,
            provider=None,
        )
    )
    config["executor"]["auth"] = {
        "type": "api_key",
        "api_key": "mock-key",
        "base_url": mock_llm_server_url,
    }
    config["os_env"]["cwd"] = str(workspace)
    package = Path(omnigent.__file__).resolve().parent
    if not package.is_relative_to(Path(sys.prefix).resolve()):
        # Test-only read grant: seatbelt refuses to import the helper from an editable checkout.
        config["os_env"]["sandbox"]["read_paths"] = [str(package)]
    return pack_bundle(yaml.safe_dump(config, sort_keys=True).encode())


# The shared live_server runner inherits this process's environment and real HOME.
@pytest.mark.skipif(
    os.environ.get(_OPT_IN) != "1",
    reason=f"set {_OPT_IN}=1 in an environment with no Claude login or provider credentials",
)
@pytest.mark.skipif(
    _SANDBOX_BINARY is None or shutil.which(_SANDBOX_BINARY) is None,
    reason="needs bwrap on Linux or sandbox-exec on macOS",
)
@pytest.mark.timeout(300)
def test_reviewer_step_cannot_write_through_the_real_stack(
    http_client: httpx.Client,
    live_runner_id: str,
    mock_llm_server_url: str,
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)
    monkeypatch.setitem(http_client.headers, "x-omnigent-background-session-titles", "off")
    uid = uuid.uuid4().hex[:8]
    model = f"mock-coral-reviewer-{uid}"
    prompt = f"Review the workspace {uid}."
    shell_call = {
        "call_id": f"call_shell_{uid}",
        "name": _SHELL_TOOL,
        "arguments": json.dumps({"command": "echo x > owned.txt; echo rc=$?"}),
    }
    write_call = {
        "call_id": f"call_write_{uid}",
        "name": _WRITE_TOOL,
        "arguments": json.dumps({"path": "owned.txt", "content": "x"}),
    }
    configure_mock_llm(
        mock_llm_server_url,
        [{"tool_calls": [shell_call]}, {"tool_calls": [write_call]}, {"text": f"done {uid}"}],
        key=model,
        required_tools=[_SHELL_TOOL],
    )
    bundle = _reviewer_bundle(
        model=model, mock_llm_server_url=mock_llm_server_url, workspace=workspace
    )

    created = post_operator_session(
        http_client.post, "/v1/sessions", bundle, headers={"Origin": OMNIGENT_INTERNAL_WS_ORIGIN}
    )
    created.raise_for_status()
    session_id = created.json()["session_id"]
    http_client.patch(
        f"/v1/sessions/{session_id}", json={"runner_id": live_runner_id}
    ).raise_for_status()
    response_id = send_user_message_to_session(http_client, session_id=session_id, content=prompt)
    body = poll_session_until_terminal(
        http_client, session_id=session_id, response_id=response_id, timeout=240
    )

    assert body["status"] == "completed", body["error"]
    requests = get_mock_message_requests(mock_llm_server_url, key=model)
    shell_results = tool_results(requests, call_id=shell_call["call_id"])
    write_results = tool_results(requests, call_id=write_call["call_id"])
    assert shell_results and all("rc=1" in result for result in shell_results), shell_results
    assert write_results and all(
        "report-only" in r or "blocked by sandbox" in r for r in write_results
    ), write_results
    assert sorted(p.name for p in workspace.iterdir()) == ["existing.txt"]
    assert (workspace / "existing.txt").read_text() == ORIGINAL
