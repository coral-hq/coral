"""Compiling an authored ``done_when`` block to the K11 requirement."""

from __future__ import annotations

import pytest

from coral.evidence.ir import EvidenceIRError, RequiredCommand, compile_done_when


def test_commands_compile_with_default_ids() -> None:
    requirement = compile_done_when(
        {"commands": [{"run": "  ruff format .", "may_modify": True}, {"run": "pytest -q"}]},
        yaml_path="nodes[1].done_when",
    )
    assert requirement.scope == "per_agent"
    assert requirement.items == (
        RequiredCommand(item_id="c1", run="ruff format .", may_modify=True),
        RequiredCommand(item_id="c2", run="pytest -q"),
    )


@pytest.mark.parametrize(
    ("block", "path"),
    [
        ([], "done_when"),
        ({}, "done_when.commands"),
        ({"commands": []}, "done_when.commands"),
        ({"commands": [{}]}, "done_when.commands[0].run"),
        ({"commands": [{"run": " "}]}, "done_when.commands[0].run"),
        ({"commands": [{"run": "a && b"}]}, "done_when.commands[0].run"),
        ({"commands": [{"run": "x", "shell": True}]}, "done_when.commands[0].shell"),
        ({"commands": [{"run": "x", "may_modify": "yes"}]}, "done_when.commands[0].may_modify"),
        (
            {"commands": [{"id": "t", "run": "x"}, {"id": "t", "run": "y"}]},
            "done_when.commands[1].id",
        ),
        ({"commands": [{"run": "x"}], "scope": "per_step"}, "done_when.scope"),
    ],
)
def test_bad_blocks_name_their_yaml_path(block: object, path: str) -> None:
    with pytest.raises(EvidenceIRError) as raised:
        compile_done_when(block, yaml_path="done_when")
    assert raised.value.yaml_path == path
