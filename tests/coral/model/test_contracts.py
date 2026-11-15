"""Contracts: authoring schema, IR immutability, canonical hashing, pure-tier imports."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from coral.model import CompiledGraph, Workflow, canonical_bytes, canonical_json, content_hash
from coral.model.authoring import Arrow, DecisionNode, GateNode, StartNode
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    end,
    fixture_text,
    load_ok,
    start,
    step,
    workflow_text,
)


def _document(**overrides: object) -> dict[str, object]:
    return {"id": "demo", "name": "Demo", "nodes": [], "arrows": [], **overrides}


def test_ir_module_imports() -> None:
    import coral.model.ir as ir

    assert ir.IR_VERSION == 1


@pytest.mark.parametrize("workflow_id", ["runs", "templates", "new"])
def test_reserved_workflow_ids_are_rejected(workflow_id: str) -> None:
    with pytest.raises(ValidationError, match="reserved"):
        Workflow.model_validate(_document(id=workflow_id))


@pytest.mark.parametrize("workflow_id", ["Demo", "-demo", "has space", "x" * 65, "", "a/b"])
def test_invalid_workflow_slugs_are_rejected(workflow_id: str) -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate(_document(id=workflow_id))


@pytest.mark.parametrize("workflow_id", ["demo", "a", "my.flow-1_x", "0abc", "x" * 64])
def test_valid_workflow_slugs_are_accepted(workflow_id: str) -> None:
    assert Workflow.model_validate(_document(id=workflow_id)).id == workflow_id


@pytest.mark.parametrize("node_id", ["Start", "has.dot", "-x", "a b", ""])
def test_invalid_node_ids_are_rejected(node_id: str) -> None:
    with pytest.raises(ValidationError):
        StartNode.model_validate({"id": node_id, "kind": "start"})


@pytest.mark.parametrize(
    "model", [StartNode, DecisionNode, GateNode], ids=["start", "decision", "gate"]
)
def test_models_forbid_unknown_keys(model: type) -> None:
    kind = {StartNode: "start", DecisionNode: "decision", GateNode: "gate"}[model]
    with pytest.raises(ValidationError, match="Extra inputs"):
        model.model_validate({"id": "x", "kind": kind, "surprise": 1})


def test_arrow_forbids_unknown_keys_and_uses_from_alias() -> None:
    parsed = Arrow.model_validate({"id": "a1", "from": "x", "to": "y"})
    assert parsed.from_node == "x"
    with pytest.raises(ValidationError):
        Arrow.model_validate({"id": "a1", "from": "x", "to": "y", "extra": True})


def test_gate_outcomes_default_to_approve_and_reject() -> None:
    assert GateNode.model_validate({"id": "g", "kind": "gate"}).outcomes == ["approve", "reject"]


def test_compiled_graph_is_frozen() -> None:
    graph, _ = compile_text(fixture_text("minimal"))
    with pytest.raises(ValidationError):
        graph.name = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        graph.nodes[0].id = "changed"  # type: ignore[misc]
    assert isinstance(graph.nodes, tuple)


def test_canonical_json_ignores_key_order() -> None:
    forward = {"b": [1, {"y": 1, "x": 2}], "a": "é"}
    reverse = {"a": "é", "b": [1, {"x": 2, "y": 1}]}
    assert canonical_json(forward) == canonical_json(reverse)
    assert b" " not in canonical_json({"a": 1, "b": 2})


def test_canonical_bytes_stable_under_dump_reorder() -> None:
    graph, _ = compile_text(fixture_text("loop"))
    dumped = graph.model_dump(mode="json", exclude={"analysis", "content_hash"})
    reordered = json.loads(json.dumps(dumped))
    reordered = {key: reordered[key] for key in reversed(list(reordered))}
    for arrow_entry in reordered["arrows"]:
        arrow_entry.pop("kind")
    assert canonical_json(reordered) == canonical_bytes(graph)


def test_canonical_bytes_exclude_derived_fields() -> None:
    graph, _ = compile_text(fixture_text("loop"))
    data = json.loads(canonical_bytes(graph))
    assert "analysis" not in data and "content_hash" not in data
    assert all("kind" not in entry for entry in data["arrows"])
    stripped = graph.model_copy(update={"analysis": type(graph.analysis)(), "content_hash": "x"})
    assert canonical_bytes(stripped) == canonical_bytes(graph)


def test_content_hash_is_sha256_hex_of_canonical_bytes() -> None:
    graph, _ = compile_text(fixture_text("minimal"))
    assert graph.content_hash == content_hash(canonical_bytes(graph))
    assert len(graph.content_hash) == 64
    assert content_hash(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_hash_ignores_yaml_key_order_comments_and_explicit_defaults() -> None:
    nodes = [start(), step("work"), end()]
    arrows = [arrow("a1", "start", "work"), arrow("a2", "work", "end")]
    base, _ = compile_text(workflow_text(nodes, arrows))
    explicit, _ = compile_text(
        workflow_text([start(), step("work", attempts=3, concurrency=1), end()], arrows)
        + "# trailing comment\n"
    )
    assert base.content_hash == explicit.content_hash
    swapped = workflow_text(nodes, arrows).replace(
        "id: demo\nname: Demo\n", "name: Demo\nid: demo\n"
    )
    assert compile_text(swapped)[0].content_hash == base.content_hash


def test_hash_changes_with_content() -> None:
    nodes = [start(), step("work"), end()]
    arrows = [arrow("a1", "start", "work"), arrow("a2", "work", "end")]
    changed = [start(), step("work", goal="Different goal"), end()]
    assert (
        compile_text(workflow_text(nodes, arrows))[0].content_hash
        != compile_text(workflow_text(changed, arrows))[0].content_hash
    )


def test_authoring_canonical_bytes_use_yaml_aliases() -> None:
    workflow = load_ok(fixture_text("minimal")).workflow
    data = json.loads(canonical_bytes(workflow))
    assert data["arrows"][0]["from"] == "start"


def test_compiled_graph_json_round_trip() -> None:
    graph, _ = compile_text(fixture_text("loop"))
    assert CompiledGraph.model_validate_json(graph.model_dump_json()) == graph


def test_pure_tier_does_not_import_omnigent() -> None:
    code = (
        "import sys, coral.model, coral.validate\n"
        "bad = sorted(m for m in sys.modules if m == 'omnigent' or m.startswith('omnigent.')"
        " or m.startswith('coral.omni') or m in ('coral.stores', 'coral.api'))\n"
        "print(bad)\nsys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
