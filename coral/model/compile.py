"""Compile a loaded authoring document into a frozen, content-hashed graph."""

from __future__ import annotations

from coral.model import authoring
from coral.model.analysis import analyze
from coral.model.canonical import canonical_bytes, content_hash
from coral.model.ir import (
    DEFAULT_ATTEMPTS,
    DEFAULT_CONCURRENCY,
    FAILURE_LABEL,
    ArrowKind,
    CompiledArrow,
    CompiledGraph,
    CompiledNode,
    CompiledPart,
)
from coral.model.loader import Loaded


def _compile_node(node: authoring.AuthoringNode) -> CompiledNode:
    match node:
        case authoring.StepNode():
            return CompiledNode(
                id=node.id,
                kind="step",
                name=node.name,
                goal=node.goal,
                roster=tuple(node.roster),
                harness=node.harness,
                attempts=node.attempts if node.attempts is not None else DEFAULT_ATTEMPTS,
                concurrency=(
                    node.concurrency if node.concurrency is not None else DEFAULT_CONCURRENCY
                ),
                list_from=node.list_from,
                parts=tuple(CompiledPart(name=p.name, kind=p.kind) for p in node.parts),
            )
        case authoring.DecisionNode():
            return CompiledNode(
                id=node.id, kind="decision", name=node.name, question=node.question
            )
        case authoring.GateNode():
            return CompiledNode(
                id=node.id,
                kind="gate",
                name=node.name,
                prompt=node.prompt,
                outcomes=tuple(node.outcomes),
            )
        case authoring.StartNode():
            return CompiledNode(id=node.id, kind="start", name=node.name)
        case authoring.EndNode():
            return CompiledNode(id=node.id, kind="end", name=node.name)
    raise AssertionError(f"unhandled node type {type(node).__name__}")


def _arrow_kind(arrow: authoring.Arrow, at_limit_ids: set[str]) -> ArrowKind:
    if arrow.back:
        return "back"
    if arrow.id in at_limit_ids:
        return "at_limit"
    if arrow.label == FAILURE_LABEL:
        return "failure"
    return "forward"


def compile(loaded: Loaded) -> CompiledGraph:
    """Build the frozen graph, its Analysis and its content hash. Never raises on bad graphs."""
    workflow = loaded.workflow
    at_limit_ids = {a.at_limit for a in workflow.arrows if a.back and a.at_limit is not None}
    nodes = tuple(_compile_node(node) for node in workflow.nodes)
    arrows = tuple(
        CompiledArrow(
            id=arrow.id,
            source=arrow.from_node,
            target=arrow.to,
            label=arrow.label,
            kind=_arrow_kind(arrow, at_limit_ids),
            limit=arrow.limit,
            at_limit=arrow.at_limit,
        )
        for arrow in workflow.arrows
    )
    graph = CompiledGraph(
        workflow_id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        nodes=nodes,
        arrows=arrows,
        analysis=analyze(nodes, arrows),
    )
    return graph.model_copy(update={"content_hash": content_hash(canonical_bytes(graph))})
