"""Analysis: joins, loops, regions, labels, list references and unresolved facts."""

from __future__ import annotations

from coral.model import CompiledGraph
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    fixture_text,
    start,
    step,
    workflow_text,
)


def _graph(nodes: list[dict[str, object]], arrows: list[dict[str, object]]) -> CompiledGraph:
    return compile_text(workflow_text(nodes, arrows))[0]


def _fact_codes(graph: CompiledGraph) -> set[str]:
    return {fact.code for fact in graph.analysis.unresolved}


def _joins(graph: CompiledGraph) -> dict[str, tuple[str, str | None]]:
    return {j.node_id: (j.join_type, j.split_node_id) for j in graph.analysis.join_types}


def test_loop_table_describes_body_entry_and_exit() -> None:
    graph = compile_text(fixture_text("loop"))[0]
    (loop,) = graph.analysis.loops
    assert (loop.back_arrow_id, loop.head, loop.tail) == ("a4", "work", "review")
    assert loop.body == ("work", "review")
    assert loop.limit == 3 and loop.at_limit_arrow_id == "a5"
    assert loop.entry_arrow_ids == ("a1",)
    assert graph.analysis.unresolved == ()


def test_back_arrows_do_not_count_toward_join_arity() -> None:
    graph = compile_text(fixture_text("loop"))[0]
    # "work" has a forward arrow plus the back arrow, yet is not a join.
    assert "work" not in _joins(graph)
    # "end" merges a decision's alternatives: an XOR join.
    assert _joins(graph) == {"end": ("xor", None)}


def test_parallel_split_forms_and_join_and_region() -> None:
    graph = compile_text(fixture_text("parallel"))[0]
    assert _joins(graph) == {"merge": ("and", "plan")}
    (region,) = graph.analysis.regions
    assert (region.split_node_id, region.join_node_id) == ("plan", "merge")
    assert region.node_ids == ("build", "docs")
    assert graph.analysis.unresolved == ()


def test_decision_alternatives_merge_with_xor() -> None:
    graph = _graph(
        [start(), decision("pick"), step("a"), step("b"), step("after"), end()],
        [
            arrow("a1", "start", "pick"),
            arrow("a2", "pick", "a", label="left"),
            arrow("a3", "pick", "b", label="right"),
            arrow("a4", "a", "after"),
            arrow("a5", "b", "after"),
            arrow("a6", "after", "end"),
        ],
    )
    assert _joins(graph) == {"after": ("xor", None)}
    assert graph.analysis.regions == ()
    assert graph.analysis.unresolved == ()


def test_xor_merge_inside_parallel_branch_then_and_join() -> None:
    graph = _graph(
        [
            start(),
            step("fork"),
            step("a"),
            decision("d"),
            step("x"),
            step("y"),
            step("m"),
            step("b"),
            step("join"),
            end(),
        ],
        [
            arrow("a1", "start", "fork"),
            arrow("a2", "fork", "a"),
            arrow("a3", "fork", "b"),
            arrow("a4", "a", "d"),
            arrow("a5", "d", "x", label="x"),
            arrow("a6", "d", "y", label="y"),
            arrow("a7", "x", "m"),
            arrow("a8", "y", "m"),
            arrow("a9", "m", "join"),
            arrow("a10", "b", "join"),
            arrow("a11", "join", "end"),
        ],
    )
    assert _joins(graph) == {"m": ("xor", None), "join": ("and", "fork")}
    assert graph.analysis.unresolved == ()


def test_nested_parallel_regions_close_independently() -> None:
    graph = _graph(
        [
            start(),
            step("outer"),
            step("a"),
            step("inner"),
            step("c"),
            step("d"),
            step("inner_join"),
            step("b"),
            step("outer_join"),
            end(),
        ],
        [
            arrow("a1", "start", "outer"),
            arrow("a2", "outer", "a"),
            arrow("a3", "outer", "b"),
            arrow("a4", "a", "inner"),
            arrow("a5", "inner", "c"),
            arrow("a6", "inner", "d"),
            arrow("a7", "c", "inner_join"),
            arrow("a8", "d", "inner_join"),
            arrow("a9", "inner_join", "outer_join"),
            arrow("a10", "b", "outer_join"),
            arrow("a11", "outer_join", "end"),
        ],
    )
    assert _joins(graph) == {"inner_join": ("and", "inner"), "outer_join": ("and", "outer")}
    assert len(graph.analysis.regions) == 2
    assert graph.analysis.unresolved == ()


def test_decision_that_can_skip_an_and_join_is_unresolved() -> None:
    graph = compile_text(fixture_text("deadlock_join"))[0]
    assert "region_not_closed" in _fact_codes(graph)
    fact = next(f for f in graph.analysis.unresolved if f.code == "region_not_closed")
    assert "'abandon'" in fact.message or "'end'" in fact.message
    assert graph.analysis.regions == ()


def test_parallel_split_without_join_is_unresolved() -> None:
    graph = _graph(
        [start(), step("fork"), step("a"), step("b"), end("end1"), end("end2")],
        [
            arrow("a1", "start", "fork"),
            arrow("a2", "fork", "a"),
            arrow("a3", "fork", "b"),
            arrow("a4", "a", "end1"),
            arrow("a5", "b", "end2"),
        ],
    )
    assert _fact_codes(graph) == {"split_without_join"}


def test_branch_mixed_with_outside_path_is_ambiguous_join() -> None:
    graph = _graph(
        [start(), step("fork"), step("a"), step("b"), step("join"), end()],
        [
            arrow("a1", "start", "fork"),
            arrow("a2", "fork", "a"),
            arrow("a3", "fork", "b"),
            arrow("a4", "a", "join"),
            arrow("a5", "b", "join"),
            arrow("a6", "start", "join"),
            arrow("a7", "join", "end"),
        ],
    )
    assert "ambiguous_join" in _fact_codes(graph)


def test_cycle_without_back_arrow_is_unresolved_not_raised() -> None:
    graph = _graph(
        [start(), step("x"), step("y"), end()],
        [
            arrow("a1", "start", "x"),
            arrow("a2", "x", "y"),
            arrow("a3", "y", "x"),
            arrow("a4", "y", "end"),
        ],
    )
    (fact,) = [f for f in graph.analysis.unresolved if f.code == "cycle_without_back_arrow"]
    assert fact.node_ids == ("x", "y")


def test_self_loop_without_back_arrow_is_a_cycle() -> None:
    graph = _graph(
        [start(), step("x"), end()],
        [arrow("a1", "start", "x"), arrow("a2", "x", "x"), arrow("a3", "x", "end")],
    )
    assert "cycle_without_back_arrow" in _fact_codes(graph)


def test_back_arrow_that_closes_no_cycle_is_unresolved() -> None:
    graph = _graph(
        [start(), step("x"), step("y"), end()],
        [
            arrow("a1", "start", "x"),
            arrow("a2", "x", "end"),
            arrow("a3", "y", "x", back=True, label="r", limit=2),
            arrow("a4", "start", "y", label="z"),
        ],
    )
    assert "back_arrow_not_cycle" in _fact_codes(graph)
    assert graph.analysis.loops[0].body == ()


def test_dangling_arrow_is_unresolved() -> None:
    graph = _graph([start(), end()], [arrow("a1", "start", "ghost"), arrow("a2", "start", "end")])
    assert _fact_codes(graph) == {"dangling_arrow"}


def test_label_sets_exclude_failure_and_at_limit_arrows() -> None:
    graph = compile_text(fixture_text("loop"))[0]
    label_sets = {s.node_id: s for s in graph.analysis.label_sets}
    assert label_sets["review"].labels == ("approved", "revise")
    assert label_sets["review"].unlabelled_arrow_ids == ()
    assert label_sets["work"].labelled_arrow_ids == ()


def test_checked_parts_resolve_list_references() -> None:
    graph = _graph(
        [
            start(),
            step("plan", parts=[{"name": "items", "kind": "list"}]),
            step("each", list_from="plan.items"),
            step("bad", list_from="later.items"),
            step("later"),
            end(),
        ],
        [
            arrow("a1", "start", "plan"),
            arrow("a2", "plan", "each"),
            arrow("a3", "each", "bad"),
            arrow("a4", "bad", "later"),
            arrow("a5", "later", "end"),
        ],
    )
    checked = {c.node_id: c for c in graph.analysis.checked_parts}
    assert checked["each"].source_upstream and checked["each"].part_is_list
    assert checked["bad"].source_exists and not checked["bad"].source_upstream
