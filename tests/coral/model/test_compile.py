"""Compile: deterministic frozen IR with defaults and arrow classification."""

from __future__ import annotations

from coral.model import compile
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    fixture_text,
    load_ok,
    start,
    step,
    workflow_text,
)


def test_minimal_compiles_with_defaults() -> None:
    graph, _ = compile_text(fixture_text("minimal"))
    assert graph.workflow_id == "demo"
    assert graph.ir_version == 1
    work = graph.nodes[1]
    assert (work.attempts, work.concurrency) == (3, 1)
    assert graph.nodes[0].attempts is None
    assert [a.kind for a in graph.arrows] == ["forward", "forward"]
    assert graph.analysis.unresolved == ()


def test_compile_is_deterministic() -> None:
    text = fixture_text("loop")
    first, second = compile_text(text)[0], compile_text(text)[0]
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_explicit_values_override_defaults() -> None:
    text = workflow_text(
        [start(), step("work", attempts=5, concurrency=2), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )
    work = compile_text(text)[0].nodes[1]
    assert (work.attempts, work.concurrency) == (5, 2)


def test_arrow_kinds_are_classified() -> None:
    graph, _ = compile_text(fixture_text("loop"))
    kinds = {a.id: a.kind for a in graph.arrows}
    assert kinds == {
        "a1": "forward",
        "a2": "forward",
        "a3": "forward",
        "a4": "back",
        "a5": "at_limit",
    }


def test_failure_label_marks_failure_arrows() -> None:
    text = workflow_text(
        [start(), step("work"), step("recover"), end()],
        [
            arrow("a1", "start", "work"),
            arrow("a2", "work", "end", label="ok"),
            arrow("a3", "work", "recover", label="failure"),
            arrow("a4", "recover", "end"),
        ],
    )
    graph, _ = compile_text(text)
    assert {a.id: a.kind for a in graph.arrows}["a3"] == "failure"


def test_compile_does_not_raise_on_broken_graphs() -> None:
    text = workflow_text(
        [start(), step("x"), step("y"), end()],
        [
            arrow("a1", "start", "x"),
            arrow("a2", "x", "y"),
            arrow("a3", "y", "x"),
            arrow("a4", "y", "missing"),
        ],
    )
    graph, _ = compile_text(text)
    assert {fact.code for fact in graph.analysis.unresolved} == {
        "cycle_without_back_arrow",
        "dangling_arrow",
    }


def test_duplicate_ids_are_preserved_for_the_validator() -> None:
    text = workflow_text(
        [start(), step("work"), step("work"), end()],
        [arrow("a1", "start", "work"), arrow("a1", "work", "end")],
    )
    graph, _ = compile_text(text)
    assert [n.id for n in graph.nodes] == ["start", "work", "work", "end"]
    assert graph.node_index("work") == 1
    assert graph.arrow_index("a1") == 0
    assert graph.node_index("nope") is None and graph.arrow_index("nope") is None


def test_compile_accepts_loaded_directly() -> None:
    loaded = load_ok(fixture_text("minimal"))
    assert compile(loaded).content_hash == compile(loaded).content_hash


def test_decision_node_compiles() -> None:
    text = workflow_text(
        [start(), decision("pick"), end()],
        [arrow("a1", "start", "pick"), arrow("a2", "pick", "end", label="done")],
    )
    assert compile_text(text)[0].nodes[1].kind == "decision"
