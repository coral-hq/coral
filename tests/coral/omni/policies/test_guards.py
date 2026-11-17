"""Coral's role guards: the step roster, the orchestrator allowlist and the anchor's deny-all."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import cast

import pytest

from coral.omni.policies import guards
from coral.omni.policies.guards import (
    deny_all_tools,
    is_engine_tool,
    is_tool_search,
    orchestrator_guard,
    step_roster,
    tool_name,
)
from coral.omni.server.bundles import pack_bundle
from coral.profiles.bundle_spec import Stance, StepRef, build_step_bundle_yaml
from coral.tools.catalog import ENGINE_TOOL_NAMES
from omnigent.policies.registry import get_entry
from omnigent.policies.schema import PolicyEvent, PolicyResponse
from omnigent.runner.policy import RunnerToolPolicyGate
from omnigent.server.bundles import validate_agent_bundle

Guard = Callable[[PolicyEvent], PolicyResponse]

OMNIGENT = "mcp__omnigent__"
GUARDS = (step_roster, orchestrator_guard, deny_all_tools)
ORCHESTRATOR_DENY = (
    "[orchestrator] A Coral orchestrator can only call coral_choose_arrow "
    "(and ToolSearch to load it)."
)
# Every cross-session tool Omnigent registers today.
SESSION_TOOLS = (
    "sys_session_create",
    "sys_session_send",
    "sys_session_close",
    "sys_session_message",
    "sys_session_share",
    "sys_session_rename",
    "sys_session_list",
    "sys_session_get_history",
    "sys_session_get_info",
)


def _tool_call(name: object, *, data_name: object = None) -> PolicyEvent:
    """A tool call dispatched as *name*; *data_name* stands for a rewritten ``data.name``."""
    data = {"name": name if data_name is None else data_name, "arguments": {}}
    return cast(PolicyEvent, {"type": "tool_call", "target": name, "data": data})


def _both_forms(*names: str) -> list[str]:
    return [form for name in names for form in (name, OMNIGENT + name)]


@pytest.mark.parametrize(
    "name",
    [
        *_both_forms(
            *SESSION_TOOLS,
            "sys_session_future",
            "search_conversations",
            "Agent",
            "Task",
            "collaborationspawn_agent",
        ),
        "mcp__codex__Spawn_Agent",
        # A call that names no tool.
        "",
        OMNIGENT,
        None,
    ],
)
def test_step_roster_denies_cross_session_tools_in_both_name_forms(name: object) -> None:
    verdict = step_roster(_tool_call(name))

    assert verdict == {
        "result": "DENY",
        "reason": "[roster] Coral steps cannot start, message or read other sessions or "
        "agents. Put what you need in your handoff report.",
    }


@pytest.mark.parametrize(
    "name",
    [
        *_both_forms("sys_os_shell", "coral_submit_handoff", "sys_os_write"),
        "ToolSearch",
        "Skill",
        "sys_sessionx",
        "search_conversations_x",
    ],
)
def test_step_roster_allows_a_steps_own_tools(name: str) -> None:
    assert step_roster(_tool_call(name)) == {"result": "ALLOW"}


@pytest.mark.parametrize(
    "name", ["coral_choose_arrow", OMNIGENT + "coral_choose_arrow", "ToolSearch"]
)
def test_orchestrator_allowlist_allows_choose_arrow_and_toolsearch(name: str) -> None:
    assert orchestrator_guard(_tool_call(name)) == {"result": "ALLOW"}


@pytest.mark.parametrize(
    "name",
    [
        "Edit",
        "Write",
        "MultiEdit",
        "NotebookEdit",
        "Bash",
        "Skill",
        "sys_os_shell",
        "sys_os_write",
        "sys_os_edit",
        "sys_os_read",
        *_both_forms("sys_session_message", "coral_submit_handoff"),
        "mcp__fs__write_file",
        # Exact names only: a look-alike gets no exemption.
        "coral_x",
        "coral_choose_arrow_x",
        "Coral_choose_arrow",
        OMNIGENT + OMNIGENT + "coral_choose_arrow",
        "mcp__fs__coral_choose_arrow",
        OMNIGENT + "ToolSearch",
        "toolsearch",
        "ToolSearch ",
        "",
        None,
    ],
)
def test_orchestrator_allowlist_denies_every_other_tool(name: object) -> None:
    assert orchestrator_guard(_tool_call(name)) == {"result": "DENY", "reason": ORCHESTRATOR_DENY}


@pytest.mark.parametrize(
    "name",
    [
        *_both_forms("coral_choose_arrow", "coral_submit_handoff"),
        "ToolSearch",
        "AskUserQuestion",
        "",
    ],
)
def test_anchor_denies_every_tool_call(name: str) -> None:
    assert deny_all_tools(_tool_call(name)) == {
        "result": "DENY",
        "reason": "[anchor] The Coral run anchor does not run tools.",
    }


@pytest.mark.parametrize("guard", GUARDS)
@pytest.mark.parametrize(
    "phase", ["request", "tool_result", "response", "llm_request", "llm_response"]
)
def test_guards_allow_every_other_phase(guard: Guard, phase: str) -> None:
    event = cast(
        PolicyEvent, {"type": phase, "data": {"name": "sys_session_send", "arguments": {}}}
    )

    assert guard(event) == {"result": "ALLOW"}


@pytest.mark.parametrize(
    ("event", "nameless_tool_call"),
    [
        ({}, False),
        ({"type": "tool_call"}, True),
        ({"type": "tool_call", "data": "Agent"}, True),
        (None, False),
        ("tool_call", False),
    ],
    ids=["empty", "no_data", "data_not_a_mapping", "none", "not_a_mapping"],
)
def test_a_malformed_event_never_raises(event: object, nameless_tool_call: bool) -> None:
    policy_event = cast(PolicyEvent, event)
    expected = "DENY" if nameless_tool_call else "ALLOW"

    for guard in GUARDS:
        assert guard(policy_event)["result"] == expected


def test_guards_decide_on_the_dispatched_target_not_a_rewritten_name() -> None:
    # An earlier policy's transform can rewrite data.name, never the target.
    assert step_roster(_tool_call("sys_session_send", data_name="sys_os_read"))["result"] == "DENY"
    assert step_roster(_tool_call("sys_os_read", data_name="sys_session_send")) == {
        "result": "ALLOW"
    }
    assert orchestrator_guard(_tool_call("Edit", data_name="coral_choose_arrow"))["result"] == (
        "DENY"
    )
    assert orchestrator_guard(_tool_call("coral_choose_arrow", data_name="Edit")) == {
        "result": "ALLOW"
    }


@pytest.mark.parametrize(
    ("event", "name"),
    [
        ({"type": "tool_call", "target": "Edit", "data": {"name": "Skill"}}, "Edit"),
        # Only an absent target falls back to the name the call carries.
        ({"type": "tool_call", "data": {"name": "Skill"}}, "Skill"),
        ({"type": "tool_call", "target": None, "data": {"name": "Skill"}}, "Skill"),
        ({"type": "tool_call", "target": 7, "data": {"name": "Skill"}}, ""),
        ({"type": "tool_call", "target": "", "data": {"name": "Skill"}}, ""),
    ],
    ids=["target", "no_target", "null_target", "non_string_target", "empty_target"],
)
def test_tool_name_reads_the_target_first(event: dict[str, object], name: str) -> None:
    assert tool_name(cast(PolicyEvent, event)) == name


def test_exemptions_match_exact_engine_tool_names_only() -> None:
    for name in ENGINE_TOOL_NAMES:
        assert is_engine_tool(name)
        assert is_engine_tool(OMNIGENT + name)
    for name in (
        "coral_x",
        "coral_submit_handoff_x",
        "Coral_submit_handoff",
        "mcp__fs__coral_submit_handoff",
        OMNIGENT + OMNIGENT + "coral_choose_arrow",
        OMNIGENT,
        "",
    ):
        assert not is_engine_tool(name), name
    assert is_tool_search("ToolSearch")
    for name in (OMNIGENT + "ToolSearch", "toolsearch", "ToolSearch_x", " ToolSearch", ""):
        assert not is_tool_search(name), name


@pytest.mark.usefixtures("coral_policy_registry")
def test_the_three_guards_are_registered_internal_only_callables() -> None:
    handlers = [entry["handler"] for entry in guards.POLICY_REGISTRY]

    assert handlers == [
        "coral.omni.policies.guards.step_roster",
        "coral.omni.policies.guards.orchestrator_guard",
        "coral.omni.policies.guards.deny_all_tools",
    ]
    for handler, guard in zip(handlers, GUARDS, strict=True):
        entry = get_entry(str(handler))
        assert entry is not None
        assert (entry.kind, entry.internal_only, entry.params_schema) == ("callable", True, None)
        module, _, name = str(handler).rpartition(".")
        assert getattr(importlib.import_module(module), name) is guard


@pytest.mark.usefixtures("coral_policy_registry")
@pytest.mark.parametrize(
    ("stance", "denied", "allowed"),
    [
        (Stance.ANCHOR, "ToolSearch", None),
        (Stance.ORCHESTRATOR, "sys_os_shell", "coral_choose_arrow"),
        (Stance.IMPLEMENTER, "sys_session_message", "sys_os_shell"),
        (Stance.REVIEWER, OMNIGENT + "sys_session_list", "sys_os_read"),
    ],
)
async def test_a_generated_bundle_starts_on_a_runner_and_its_guard_decides(
    stance: Stance, denied: str, allowed: str | None
) -> None:
    config_yaml = build_step_bundle_yaml(
        StepRef(workflow_id="demo.flow", node_id="check", roster_index=0),
        stance,
        model=None,
        provider=None,
    )
    gate = RunnerToolPolicyGate.from_spec(validate_agent_bundle(pack_bundle(config_yaml)))

    # An allowlist or a deny-all must not keep the agent from starting.
    await gate.evaluate_agent_start({"agent_name": "step", "harness": "claude-sdk"})
    assert (await gate.evaluate_tool_call(denied, {})).action == "deny"
    if allowed is not None:
        assert (await gate.evaluate_tool_call(allowed, {})).action == "allow"
