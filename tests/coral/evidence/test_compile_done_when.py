"""Compiling an authored ``done_when`` block to the K11 requirement."""

from __future__ import annotations

import pytest

from coral.evidence.ir import EvidenceIRError, RequiredCommand, compile_done_when
from coral.model import load
from tests.coral.workflow_builders import arrow, compile_text, end, start, step, workflow_text


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


def _done_when_workflow(done_when: object) -> str:
    return workflow_text(
        [start(), step("work", done_when=done_when), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )


def test_a_step_done_when_compiles_into_the_graph() -> None:
    graph, _ = compile_text(_done_when_workflow({"commands": [{"id": "t", "run": "pytest -q"}]}))
    work = next(node for node in graph.nodes if node.id == "work")
    assert work.evidence is not None
    assert work.evidence.items == (RequiredCommand(item_id="t", run="pytest -q"),)


def test_a_step_without_done_when_keeps_its_graph_hash() -> None:
    text = workflow_text(
        [start(), step("work"), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )
    graph, _ = compile_text(text)
    assert all(node.evidence is None for node in graph.nodes)
    assert "evidence" not in graph.model_dump(exclude_defaults=True)["nodes"][1]


def test_a_bad_done_when_is_a_load_error() -> None:
    loaded = load(_done_when_workflow({"commands": []}))
    assert hasattr(loaded, "code"), loaded
    assert "done_when.commands" in str(loaded)
