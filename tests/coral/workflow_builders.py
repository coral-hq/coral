"""Small builders for workflow YAML used across the Coral model and validator tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from coral.model import CompiledGraph, Loaded, SourceMap, compile, load
from coral.validate import ValidateContext, ValidationReport, validate

FIXTURES = Path(__file__).parent / "fixtures" / "workflows"


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.yaml").read_text()


def start(node_id: str = "start") -> dict[str, object]:
    return {"id": node_id, "kind": "start"}


def end(node_id: str = "end") -> dict[str, object]:
    return {"id": node_id, "kind": "end"}


def step(node_id: str, roster: list[str] | None = None, **fields: object) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "step",
        "goal": f"Do {node_id}",
        "roster": roster or ["implementer"],
        **fields,
    }


def decision(node_id: str) -> dict[str, object]:
    return {"id": node_id, "kind": "decision"}


def gate(node_id: str, **fields: object) -> dict[str, object]:
    return {"id": node_id, "kind": "gate", **fields}


def arrow(arrow_id: str, source: str, target: str, **fields: object) -> dict[str, object]:
    return {"id": arrow_id, "from": source, "to": target, **fields}


def workflow_text(
    nodes: list[dict[str, object]], arrows: list[dict[str, object]], **fields: object
) -> str:
    document = {"id": "demo", "name": "Demo", **fields, "nodes": nodes, "arrows": arrows}
    return yaml.safe_dump(document, sort_keys=False)


def load_ok(text: str) -> Loaded:
    loaded = load(text)
    assert not hasattr(loaded, "code"), loaded
    assert isinstance(loaded, Loaded)
    return loaded


def compile_text(text: str) -> tuple[CompiledGraph, SourceMap]:
    loaded = load_ok(text)
    return compile(loaded), loaded.source_map


def validate_text(text: str, ctx: ValidateContext | None = None) -> ValidationReport:
    graph, source_map = compile_text(text)
    return validate(graph, source_map, ctx)
