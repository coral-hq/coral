"""Each Required rule's compiled policy gives its declared verdict through the real builtin."""

from __future__ import annotations

import pytest

from coral.profiles.spec import RuleInstance, RuleStrength
from coral.rules.catalog import _WRITE_TOOLS, CATALOG, RELATIVE_PATHS
from coral.rules.compile import compile_rules
from omnigent.policies.builtins.cel import cel_policy
from omnigent.policies.builtins.safety import NATIVE_WRITE_TOOLS
from omnigent.policies.function import resolve_function_policy
from omnigent.policies.types import EvaluationContext, PolicyResult
from omnigent.spec.types import FunctionPolicySpec, FunctionRef, Phase, PhaseSelector, PolicyAction

ALLOW = PolicyAction.ALLOW
DENY = PolicyAction.DENY


async def _decision(
    template: str, params: dict[str, object], tool: str, arguments: dict[str, object]
) -> PolicyResult:
    rule = RuleInstance(template=template, params=params, strength=RuleStrength.REQUIRED)
    (body,) = compile_rules([rule]).policies.values()
    assert body["type"] == "function" and body["on"] == ["tool_call"]
    function = body["function"]
    policy = resolve_function_policy(
        FunctionPolicySpec(
            name=f"coral_rule_{template}",
            on=[PhaseSelector(Phase.TOOL_CALL)],
            function=FunctionRef(function["path"], arguments=function["arguments"]),
        )
    )
    context = EvaluationContext(
        phase=Phase.TOOL_CALL, tool_name=tool, content={"name": tool, "arguments": arguments}
    )
    return await policy.evaluate(context, {})


async def _verdict(
    template: str, params: dict[str, object], tool: str, arguments: dict[str, object]
) -> PolicyAction:
    return (await _decision(template, params, tool, arguments)).action


INFRA = {"paths": ["infra", "secrets/keys"]}


@pytest.mark.parametrize(
    ("tool", "arguments", "verdict"),
    [
        ("sys_os_write", {"path": "infra/x"}, DENY),
        ("sys_os_edit", {"path": "infra"}, DENY),
        ("sys_os_write", {"path": "./infra/x"}, DENY),
        ("sys_os_write", {"path": ".//./infra/x"}, DENY),
        ("sys_os_write", {"path": "INFRA/x"}, DENY),
        ("Write", {"file_path": "/abs/repo/infra/x"}, DENY),
        # Absolute, home-relative and backslash paths are refused outright.
        ("Edit", {"file_path": "/abs/repo/src/x"}, DENY),
        ("Edit", {"file_path": "~/repo/src/x"}, DENY),
        ("Edit", {"file_path": "src\\x"}, DENY),
        ("MultiEdit", {"file_path": "secrets//./keys/k"}, DENY),
        ("NotebookEdit", {"notebook_path": "infra/n.ipynb"}, DENY),
        ("write", {"path": "infra/x"}, DENY),
        ("edit", {"path": "infra/x"}, DENY),
        # A decoy key does not hide the real target.
        ("Write", {"path": "src/x", "file_path": "infra/x"}, DENY),
        ("Write", {"path": 1, "file_path": "infra/x"}, DENY),
        # An upward segment is denied whatever it points at.
        ("sys_os_write", {"path": "../x"}, DENY),
        ("sys_os_write", {"path": "src/../../x"}, DENY),
        ("sys_os_write", {"path": "src/x"}, ALLOW),
        # Prefixes anchor at the workspace root.
        ("sys_os_write", {"path": "a/infra/x"}, ALLOW),
        ("sys_os_write", {"path": "infrastructure/x"}, ALLOW),
        ("sys_os_write", {"path": "secrets/other"}, ALLOW),
        ("sys_os_write", {"path": "x..y/z"}, ALLOW),
        ("sys_os_write", {}, ALLOW),
        ("sys_os_read", {"path": "infra/x"}, ALLOW),
        ("sys_os_shell", {"command": "echo > infra/x"}, ALLOW),
    ],
)
async def test_protect_paths(
    tool: str, arguments: dict[str, object], verdict: PolicyAction
) -> None:
    assert await _verdict("protect_paths", INFRA, tool, arguments) is verdict


@pytest.mark.parametrize(
    "path", ["/home/u/infra/repo/src/x.py", "/abs/repo/infra/x", "../x", "src/../infra"]
)
async def test_protect_paths_tells_the_agent_to_use_a_relative_path(path: str) -> None:
    decision = await _decision("protect_paths", INFRA, "sys_os_write", {"path": path})

    assert decision.action is DENY
    assert decision.reason == RELATIVE_PATHS


async def test_protect_paths_names_the_protected_paths() -> None:
    decision = await _decision("protect_paths", INFRA, "sys_os_write", {"path": "infra/x"})

    assert decision.reason is not None and "under infra/, secrets/keys/" in decision.reason


def test_protect_paths_reads_the_tool_name_from_the_target() -> None:
    rule = RuleInstance(template="protect_paths", params=INFRA, strength=RuleStrength.REQUIRED)
    (body,) = compile_rules([rule]).policies.values()
    arguments = body["function"]["arguments"]
    evaluate = cel_policy(**arguments)
    write = {"path": "infra/x"}

    target_only = {"type": "tool_call", "target": "sys_os_write", "data": {"arguments": write}}
    assert evaluate(target_only) == {"result": "DENY", "reason": arguments["reason"]}
    # A rewritten data.name does not change which tool runs.
    renamed = {**target_only, "data": {"name": "sys_os_read", "arguments": write}}
    assert evaluate(renamed) == {"result": "DENY", "reason": arguments["reason"]}


def test_the_write_tool_list_matches_omnigents() -> None:
    assert set(_WRITE_TOOLS) == NATIVE_WRITE_TOOLS | {
        "sys_os_write",
        "sys_os_edit",
        "write",
        "edit",
    }


async def test_protect_paths_escapes_regex_characters() -> None:
    params = {"paths": ["a.b"]}
    assert await _verdict("protect_paths", params, "sys_os_write", {"path": "a.b/x"}) is DENY
    assert await _verdict("protect_paths", params, "sys_os_write", {"path": "axb/x"}) is ALLOW


@pytest.mark.parametrize(
    ("path", "verdict"),
    [
        ("my-dir/x", DENY),
        ("/abs/a_b/./c-d.e/f", DENY),
        (".github/workflows/ci.yml", DENY),
        ("myXdir/x", ALLOW),
        ("a_b/cXd.e/f", ALLOW),
        ("xgithub/w", ALLOW),
    ],
)
async def test_protect_paths_escapes_every_allowed_character(
    path: str, verdict: PolicyAction
) -> None:
    params = {"paths": ["my-dir", "a_b/c-d.e", ".github"]}
    assert await _verdict("protect_paths", params, "sys_os_write", {"path": path}) is verdict


@pytest.mark.parametrize(
    ("command", "verdict"),
    [
        ("git push origin main", DENY),
        ("gh pr merge 1", DENY),
        ("rm -rf build", DENY),
        ("git commit -m x", ALLOW),
        ("pytest -q", ALLOW),
    ],
)
async def test_limit_blast_radius(command: str, verdict: PolicyAction) -> None:
    result = await _verdict("limit_blast_radius", {}, "sys_os_shell", {"command": command})
    assert result is verdict


@pytest.mark.parametrize(
    ("tool", "arguments", "verdict"),
    [
        ("sys_os_write", {"path": "/etc/x"}, DENY),
        ("Write", {"file_path": "../x"}, DENY),
        ("sys_os_write", {"path": "src/x"}, ALLOW),
    ],
)
async def test_stay_in_worktree(
    tool: str, arguments: dict[str, object], verdict: PolicyAction
) -> None:
    assert await _verdict("stay_in_worktree", {}, tool, arguments) is verdict


def test_every_template_documents_its_bypasses_and_statement() -> None:
    assert set(CATALOG) == {"limit_blast_radius", "stay_in_worktree", "protect_paths"}
    for template_id, template in CATALOG.items():
        assert template.id == template_id
        assert template.bypasses
        assert template.title


def test_protect_paths_statement_names_the_paths() -> None:
    template = CATALOG["protect_paths"]
    params = template.params_model.model_validate({"paths": ["infra/", "secrets"]})
    assert template.statement(params) == "Never change files under infra/, secrets/."


async def test_stay_in_worktree_tells_the_agent_to_use_a_relative_path() -> None:
    decision = await _decision(
        "stay_in_worktree", {}, "sys_os_write", {"path": "/Users/me/wt/src/x.py"}
    )

    assert decision.action is DENY
    assert decision.reason is not None and decision.reason.startswith(RELATIVE_PATHS)
    assert ".worktrees" not in decision.reason
