"""Building observations from finished ``sys_os_*`` calls."""

from __future__ import annotations

import json

import pytest

from coral.evidence.capture import (
    MAX_COMMAND_CHARS,
    observation_from_tool,
    observed_tool,
    op_key_for,
    shell_exit,
)


def _envelope(exit_code: object, *, timed_out: bool = False) -> str:
    return json.dumps(
        {"stdout": "ok", "stderr": "", "exit_code": exit_code, "timed_out": timed_out}
    )


def test_only_shell_write_and_edit_are_observed() -> None:
    assert observed_tool("sys_os_shell") == "shell"
    assert observed_tool("mcp__omnigent__sys_os_edit") == "edit"
    assert observed_tool("sys_os_write") == "write"
    assert observed_tool("sys_os_read") is None
    assert observed_tool("coral_submit_handoff") is None


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (_envelope(0), (0, False)),
        (_envelope(3), (3, False)),
        (_envelope(None, timed_out=True), (None, True)),
        (_envelope(True), (None, False)),
        ("exit_code: 0", (None, False)),
        ("Error: RuntimeError: boom", (None, False)),
        (json.dumps({"stdout": "exit_code 0"}), (None, False)),
    ],
)
def test_the_exit_code_comes_only_from_the_envelope(
    output: str, expected: tuple[int | None, bool]
) -> None:
    assert shell_exit(output) == expected


def test_a_shell_call_records_its_command_exit_code_and_l1() -> None:
    obs = observation_from_tool(
        session_id="s",
        op_key="op",
        obs_seq=5,
        tool_name="mcp__omnigent__sys_os_shell",
        arguments={"command": "pytest -q"},
        output=_envelope(1),
        l1_after="d" * 64,
    )
    assert obs is not None
    assert (obs.tool, obs.command, obs.exit_code, obs.l1_after) == (
        "shell",
        "pytest -q",
        1,
        "d" * 64,
    )


def test_an_overlong_command_is_kept_as_unknown() -> None:
    obs = observation_from_tool(
        session_id="s",
        op_key="op",
        obs_seq=1,
        tool_name="sys_os_shell",
        arguments={"command": "pytest -q " + "x" * MAX_COMMAND_CHARS + " || true"},
        output=_envelope(0),
        l1_after=None,
    )
    assert obs is not None and obs.command is None


def test_a_write_or_edit_is_a_path_marker() -> None:
    obs = observation_from_tool(
        session_id="s",
        op_key="op",
        obs_seq=1,
        tool_name="sys_os_edit",
        arguments={"path": "src/app.py", "old": "a", "new": "b"},
        output="ok",
        l1_after=None,
    )
    assert obs is not None and (obs.tool, obs.changed_path) == ("edit", "src/app.py")
    assert (
        observation_from_tool(
            session_id="s",
            op_key="op",
            obs_seq=1,
            tool_name="sys_os_read",
            arguments={"path": "a"},
            output="",
            l1_after=None,
        )
        is None
    )


def test_op_keys_are_bounded() -> None:
    assert op_key_for("mcpop_1", "fallback") == "mcpop_1"
    assert op_key_for(None, "fallback") == "fallback"
    long_key = op_key_for("x" * 500, "fallback")
    assert long_key.startswith("sha256:") and len(long_key) <= 128
