"""Validator rules: each rule has failing and passing cases, plus report mechanics."""

from __future__ import annotations

import pytest

from coral.model.ir import UnresolvedFact
from coral.validate import (
    ValidateContext,
    ValidationReport,
    register_rule,
    registered_rules,
    validate,
)
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    fixture_text,
    gate,
    start,
    step,
    validate_text,
    workflow_text,
)


def _linear(*middle: dict[str, object]) -> str:
    """start -> middle... -> end in a chain."""
    nodes = [start(), *middle, end()]
    arrows = [
        arrow(f"a{i}", nodes[i]["id"], nodes[i + 1]["id"])  # type: ignore[arg-type]
        for i in range(len(nodes) - 1)
    ]
    return workflow_text(nodes, arrows)


def _loop(
    *,
    back: dict[str, object] | None = None,
    extra_nodes: tuple[dict[str, object], ...] = (),
    extra_arrows: tuple[dict[str, object], ...] = (),
    at_limit_arrow: dict[str, object] | None = None,
) -> str:
    """The loop fixture with a replaceable back arrow, exit arrow and extra elements."""
    back_arrow = back or {"label": "revise", "back": True, "limit": 3, "at_limit": "a5"}
    return workflow_text(
        [start(), step("work"), decision("review"), end(), *extra_nodes],
        [
            arrow("a1", "start", "work"),
            arrow("a2", "work", "review"),
            arrow("a3", "review", "end", label="approved"),
            arrow("a4", "review", "work", **back_arrow),
            at_limit_arrow or arrow("a5", "review", "end"),
            *extra_arrows,
        ],
    )


def _gate_text(gate_fields: dict[str, object], exit_labels: list[str]) -> str:
    arrows = [arrow("a1", "start", "approval")]
    arrows += [
        arrow(f"g{i}", "approval", "end", label=label) for i, label in enumerate(exit_labels)
    ]
    return workflow_text([start(), gate("approval", **gate_fields), end()], arrows)


def _list_text(
    consumer: dict[str, object], producer_parts: list[dict[str, str]] | None = None
) -> str:
    nodes = [
        start(),
        step(
            "plan",
            parts=producer_parts
            if producer_parts is not None
            else [{"name": "items", "kind": "list"}],
        ),
        consumer,
        end(),
    ]
    arrows = [
        arrow("a1", "start", "plan"),
        arrow("a2", "plan", str(consumer["id"])),
        arrow("a3", str(consumer["id"]), "end"),
    ]
    return workflow_text(nodes, arrows)


def _unreachable_node() -> str:
    nodes = [start(), step("work"), step("orphan"), end()]
    arrows = [
        arrow("a1", "start", "work"),
        arrow("a2", "work", "end"),
        arrow("a3", "orphan", "end"),
    ]
    return workflow_text(nodes, arrows)


def _dead_end() -> str:
    nodes = [start(), step("work"), step("stuck"), end()]
    arrows = [
        arrow("a1", "start", "work"),
        arrow("a2", "work", "end"),
        arrow("a3", "work", "stuck", label="x"),
    ]
    return workflow_text(nodes, arrows)


def _budget_text(attempts: int) -> str:
    return workflow_text(
        [start(), step("work", attempts=attempts), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )


# (case id, rule, workflow text, context, message fragment, expected yaml_path or None)
FAILING: list[tuple[str, str, str, ValidateContext | None, str, str | None]] = [
    (
        "v1-no-start",
        "V1",
        workflow_text([step("work"), end()], [arrow("a1", "work", "end")]),
        None,
        "no start node",
        "nodes",
    ),
    (
        "v1-two-starts",
        "V1",
        workflow_text(
            [start(), start("start2"), end()],
            [arrow("a1", "start", "end"), arrow("a2", "start2", "end")],
        ),
        None,
        "second start node",
        "nodes[1]",
    ),
    (
        "v1-no-end",
        "V1",
        workflow_text([start(), step("work")], [arrow("a1", "start", "work")]),
        None,
        "no end node",
        "nodes",
    ),
    ("v1-unreachable", "V1", _unreachable_node(), None, "'orphan' cannot be reached", "nodes[2]"),
    ("v1-dead-end", "V1", _dead_end(), None, "'stuck' cannot reach an end", "nodes[2]"),
    (
        "v1-arrow-into-start",
        "V1",
        workflow_text(
            [start(), step("work"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "start"),
                arrow("a3", "work", "end"),
            ],
        ),
        None,
        "enters the start node",
        "arrows[1]",
    ),
    (
        "v1-arrow-out-of-end",
        "V1",
        workflow_text(
            [start(), end(), step("work")],
            [arrow("a1", "start", "end"), arrow("a2", "end", "work")],
        ),
        None,
        "leaves the end node",
        "arrows[1]",
    ),
    (
        "v1-dangling-arrow",
        "V1",
        workflow_text(
            [start(), end()],
            [arrow("a1", "start", "ghost"), arrow("a2", "start", "end", label="x")],
        ),
        None,
        "not a node",
        "arrows[0]",
    ),
    (
        "v2-skippable-join",
        "V2",
        fixture_text("deadlock_join"),
        None,
        "do not all meet",
        "nodes[1]",
    ),
    (
        "v2-split-without-join",
        "V2",
        workflow_text(
            [start(), step("fork"), step("a"), step("b"), end("end1"), end("end2")],
            [
                arrow("a1", "start", "fork"),
                arrow("a2", "fork", "a"),
                arrow("a3", "fork", "b"),
                arrow("a4", "a", "end1"),
                arrow("a5", "b", "end2"),
            ],
        ),
        None,
        "never meet",
        "nodes[1]",
    ),
    (
        "v3-mixed-labels",
        "V3",
        workflow_text(
            [start(), decision("pick"), step("a"), step("b"), end()],
            [
                arrow("a1", "start", "pick"),
                arrow("a2", "pick", "a", label="left"),
                arrow("a3", "pick", "b"),
                arrow("a4", "a", "end"),
                arrow("a5", "b", "end"),
            ],
        ),
        None,
        "both labelled and unlabelled",
        "arrows[2]",
    ),
    (
        "v4-label-on-start",
        "V4",
        workflow_text(
            [start(), step("work"), end()],
            [arrow("a1", "start", "work", label="go"), arrow("a2", "work", "end")],
        ),
        None,
        "cannot choose between arrows",
        "arrows[0]",
    ),
    (
        "v4-label-on-multi-agent-step",
        "V4",
        workflow_text(
            [start(), step("work", roster=["a", "b"]), step("x"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "x", label="one"),
                arrow("a3", "work", "end", label="two"),
                arrow("a4", "x", "end"),
            ],
        ),
        None,
        "several agents",
        "arrows[1]",
    ),
    (
        "v4-decision-without-labels",
        "V4",
        workflow_text(
            [start(), decision("pick"), step("a"), step("b"), end()],
            [
                arrow("a1", "start", "pick"),
                arrow("a2", "pick", "a"),
                arrow("a3", "pick", "b"),
                arrow("a4", "a", "end"),
                arrow("a5", "b", "end"),
            ],
        ),
        None,
        "without labels",
        "arrows[1]",
    ),
    (
        "v4-duplicate-label",
        "V4",
        workflow_text(
            [start(), decision("pick"), step("a"), step("b"), end()],
            [
                arrow("a1", "start", "pick"),
                arrow("a2", "pick", "a", label="same"),
                arrow("a3", "pick", "b", label="same"),
                arrow("a4", "a", "end"),
                arrow("a5", "b", "end"),
            ],
        ),
        None,
        "more than one arrow",
        "nodes[1]",
    ),
    (
        "v5-cycle-without-back-arrow",
        "V5",
        workflow_text(
            [start(), step("x"), step("y"), end()],
            [
                arrow("a1", "start", "x"),
                arrow("a2", "x", "y"),
                arrow("a3", "y", "x", label="again"),
                arrow("a4", "y", "end", label="done"),
            ],
        ),
        None,
        "no back arrow",
        None,
    ),
    (
        "v5-missing-limit",
        "V5",
        _loop(back={"label": "revise", "back": True, "at_limit": "a5"}),
        None,
        "needs limit",
        "arrows[3]",
    ),
    (
        "v5-limit-zero",
        "V5",
        _loop(back={"label": "revise", "back": True, "limit": 0, "at_limit": "a5"}),
        None,
        "needs limit",
        "arrows[3].limit",
    ),
    (
        "v5-missing-at-limit",
        "V5",
        _loop(back={"label": "revise", "back": True, "limit": 3}),
        None,
        "needs at_limit",
        "arrows[3]",
    ),
    (
        "v5-at-limit-unknown-arrow",
        "V5",
        _loop(back={"label": "revise", "back": True, "limit": 3, "at_limit": "zzz"}),
        None,
        "not an arrow id",
        "arrows[3].at_limit",
    ),
    (
        "v5-at-limit-inside-body",
        "V5",
        _loop(at_limit_arrow=arrow("a5", "review", "work")),
        None,
        "leads back into the loop",
        "arrows[3]",
    ),
    (
        "v5-at-limit-from-other-node",
        "V5",
        _loop(at_limit_arrow=arrow("a5", "work", "end")),
        None,
        "must leave 'review'",
        "arrows[3]",
    ),
    (
        "v5-unlabelled-back-arrow",
        "V5",
        _loop(back={"back": True, "limit": 3, "at_limit": "a5"}),
        None,
        "has no label",
        "arrows[3]",
    ),
    (
        "v5-second-entry",
        "V5",
        _loop(
            extra_nodes=(step("side"),),
            extra_arrows=(arrow("a6", "start", "side"), arrow("a7", "side", "review")),
        ),
        None,
        "entered only at its first node",
        "arrows[6]",
    ),
    (
        "v5-two-back-arrows-same-head",
        "V5",
        _loop(
            extra_arrows=(
                arrow("a6", "review", "work", label="other", back=True, limit=2, at_limit="a5"),
            ),
        ),
        None,
        "Use one back arrow per loop",
        "arrows[5]",
    ),
    (
        "v5-limit-on-forward-arrow",
        "V5",
        workflow_text(
            [start(), step("work"), end()],
            [arrow("a1", "start", "work", limit=2), arrow("a2", "work", "end")],
        ),
        None,
        "not a back arrow",
        "arrows[0]",
    ),
    (
        "v6-malformed-reference",
        "V6",
        _list_text(step("each", list_from="items")),
        None,
        "node_id.part_name",
        "nodes[2].list_from",
    ),
    (
        "v6-unknown-node",
        "V6",
        _list_text(step("each", list_from="nope.items")),
        None,
        "there is no node 'nope'",
        "nodes[2].list_from",
    ),
    (
        "v6-not-upstream",
        "V6",
        _list_text(step("each", list_from="each2.items")),
        None,
        "there is no node 'each2'",
        "nodes[2].list_from",
    ),
    (
        "v6-source-after-consumer",
        "V6",
        workflow_text(
            [
                start(),
                step("each", list_from="later.items"),
                step("later", parts=[{"name": "items", "kind": "list"}]),
                end(),
            ],
            [
                arrow("a1", "start", "each"),
                arrow("a2", "each", "later"),
                arrow("a3", "later", "end"),
            ],
        ),
        None,
        "does not run before",
        "nodes[1].list_from",
    ),
    (
        "v6-part-not-a-list",
        "V6",
        _list_text(
            step("each", list_from="plan.items"),
            producer_parts=[{"name": "items", "kind": "text"}],
        ),
        None,
        "no list part",
        "nodes[2].list_from",
    ),
    (
        "v6-part-missing",
        "V6",
        _list_text(step("each", list_from="plan.items"), producer_parts=[]),
        None,
        "no list part",
        "nodes[2].list_from",
    ),
    (
        "v7-label-not-an-outcome",
        "V7",
        _gate_text({}, ["approve", "reject", "maybe"]),
        None,
        "not an outcome",
        "arrows[3]",
    ),
    (
        "v7-outcome-without-arrow",
        "V7",
        _gate_text({}, ["approve"]),
        None,
        "outcome 'reject' but no arrow",
        "nodes[1]",
    ),
    (
        "v7-no-approve",
        "V7",
        _gate_text({"outcomes": ["reject"]}, ["reject"]),
        None,
        "no 'approve' outcome",
        "nodes[1]",
    ),
    (
        "v7-cannot-reject",
        "V7",
        _gate_text({"outcomes": ["approve", "revise"]}, ["approve", "revise"]),
        None,
        "no way to reject",
        "nodes[1]",
    ),
    (
        "v7-duplicate-outcome",
        "V7",
        _gate_text({"outcomes": ["approve", "approve"]}, ["approve"]),
        None,
        "same outcome twice",
        "nodes[1]",
    ),
    (
        "v10-unconfigured-harness",
        "V10",
        _linear(step("work", harness="claude")),
        ValidateContext(harnesses={}),
        "is not configured",
        "nodes[1].harness",
    ),
    (
        "v10-false-harness",
        "V10",
        _linear(step("work", harness="claude")),
        ValidateContext(harnesses={"claude": False}),
        "not true",
        "nodes[1].harness",
    ),
    (
        "v10-truthy-string-is-not-true",
        "V10",
        _linear(step("work", harness="claude")),
        ValidateContext(harnesses={"claude": "yes"}),
        "'yes'",
        "nodes[1].harness",
    ),
    (
        "v10-truthy-int-is-not-true",
        "V10",
        _linear(step("work", harness="claude")),
        ValidateContext(harnesses={"claude": 1}),
        "not true",
        "nodes[1].harness",
    ),
    (
        "v12-over-budget",
        "V12",
        _budget_text(attempts=50),
        ValidateContext(max_activations=10),
        "up to 50 step activations",
        "",
    ),
    (
        "v12-loop-multiplies-attempts",
        "V12",
        _loop(),
        ValidateContext(max_activations=5),
        "up to 12 step activations",
        "",
    ),
    (
        "v13-duplicate-node-id",
        "V13",
        workflow_text(
            [start(), step("work"), step("work"), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        ),
        None,
        "Node id 'work' is used more than once",
        "nodes[2].id",
    ),
    (
        "v13-duplicate-arrow-id",
        "V13",
        workflow_text(
            [start(), step("work"), end()],
            [arrow("a1", "start", "work"), arrow("a1", "work", "end")],
        ),
        None,
        "Arrow id 'a1' is used more than once",
        "arrows[1].id",
    ),
]


def _previous_with_work_node() -> ValidateContext:
    previous, _ = compile_text(_linear(step("work", name="Build", goal="Build the thing")))
    return ValidateContext(previous=previous)


FAILING.append(
    (
        "v13-rename-hint",
        "V13",
        _linear(step("build", name="Build", goal="Build the thing")),
        _previous_with_work_node(),
        "looks like its replacement",
        "nodes[1]",
    )
)


def _passing_cases() -> list[tuple[str, str, ValidateContext | None]]:
    gate_text = _gate_text({}, ["approve", "reject"])
    approve_only = _gate_text({"outcomes": ["approve"]}, ["approve"])
    failure_arrow = workflow_text(
        [start(), gate("approval", outcomes=["approve", "revise"]), step("fix"), end()],
        [
            arrow("a1", "start", "approval"),
            arrow("a2", "approval", "end", label="approve"),
            arrow("a3", "approval", "fix", label="revise"),
            arrow("a4", "approval", "fix", label="failure"),
            arrow("a5", "fix", "end"),
        ],
    )
    list_text = _list_text(step("each", list_from="plan.items"))
    return [
        ("V1", fixture_text("minimal"), None),
        ("V1", fixture_text("loop"), None),
        ("V2", fixture_text("parallel"), None),
        ("V2", fixture_text("loop"), None),
        ("V3", fixture_text("loop"), None),
        ("V3", fixture_text("parallel"), None),
        ("V4", fixture_text("loop"), None),
        (
            "V4",
            workflow_text(
                [start(), step("work"), step("x"), end()],
                [
                    arrow("a1", "start", "work"),
                    arrow("a2", "work", "x", label="more"),
                    arrow("a3", "work", "end", label="done"),
                    arrow("a4", "x", "end"),
                ],
            ),
            None,
        ),
        ("V5", fixture_text("loop"), None),
        ("V5", fixture_text("minimal"), None),
        ("V6", list_text, None),
        ("V6", fixture_text("minimal"), None),
        ("V7", gate_text, None),
        ("V7", approve_only, None),
        ("V7", failure_arrow, None),
        (
            "V10",
            _linear(step("work", harness="claude")),
            ValidateContext(harnesses={"claude": True}),
        ),
        ("V10", fixture_text("minimal"), None),
        ("V12", fixture_text("minimal"), None),
        ("V12", fixture_text("loop"), ValidateContext(max_activations=15, warn_ratio=1.0)),
        ("V13", fixture_text("minimal"), None),
        (
            "V13",
            _linear(step("work", name="Build", goal="Build the thing")),
            _previous_with_work_node(),
        ),
    ]


def _problems_for(report: ValidationReport, rule: str) -> list[str]:
    return [f"{p.severity}: {p.message}" for p in report.for_rule(rule)]


@pytest.mark.parametrize(
    ("rule", "text", "ctx", "fragment", "yaml_path"),
    [pytest.param(*case[1:], id=case[0]) for case in FAILING],
)
def test_rule_reports_failing_workflow(
    rule: str, text: str, ctx: ValidateContext | None, fragment: str, yaml_path: str | None
) -> None:
    report = validate_text(text, ctx)
    matching = [p for p in report.for_rule(rule) if fragment in p.message]
    assert matching, (
        f"no {rule} problem containing {fragment!r}; got {_problems_for(report, rule)}"
    )
    if yaml_path is not None:
        assert any(p.yaml_path == yaml_path for p in matching), [p.yaml_path for p in matching]
        assert all(p.range is not None for p in matching if p.yaml_path is not None)
    if any(p.severity == "error" for p in matching):
        assert not report.runnable


@pytest.mark.parametrize(
    ("rule", "text", "ctx"),
    [pytest.param(*case, id=f"{case[0]}-{index}") for index, case in enumerate(_passing_cases())],
)
def test_rule_accepts_valid_workflow(rule: str, text: str, ctx: ValidateContext | None) -> None:
    report = validate_text(text, ctx)
    assert [p for p in report.for_rule(rule) if p.severity != "info"] == []


@pytest.mark.parametrize("name", ["minimal", "loop", "parallel", "review_prs"])
def test_valid_fixtures_are_runnable_without_problems(name: str) -> None:
    report = validate_text(fixture_text(name))
    assert report.problems == ()
    assert report.runnable


def test_deadlock_fixture_is_not_runnable() -> None:
    report = validate_text(fixture_text("deadlock_join"))
    assert not report.runnable
    assert report.for_rule("V2")


def test_rules_are_registered_in_numeric_order() -> None:
    assert [spec.rule_id for spec in registered_rules()] == [
        "V1",
        "V2",
        "V3",
        "V4",
        "V5",
        "V6",
        "V7",
        "V10",
        "V12",
        "V13",
    ]


def test_registering_a_rule_twice_is_an_error() -> None:
    with pytest.raises(ValueError, match="already registered"):
        register_rule("V1")(lambda inp: [])


def test_all_problems_are_collected_not_just_the_first() -> None:
    report = validate_text(
        workflow_text(
            [start(), start("start2"), step("work", harness="nope"), step("work")],
            [arrow("a1", "start", "work"), arrow("a1", "start2", "ghost")],
        )
    )
    assert {p.rule for p in report.problems} >= {"V1", "V10", "V13"}
    assert not report.runnable


def test_warnings_and_info_do_not_block_runnable() -> None:
    warning_report = validate_text(
        fixture_text("loop"), ValidateContext(max_activations=15, warn_ratio=0.5)
    )
    assert [p.severity for p in warning_report.problems] == ["warning"]
    assert warning_report.runnable
    assert warning_report.warnings and not warning_report.errors


def test_unhandled_unresolved_fact_blocks_runnable() -> None:
    graph, source_map = compile_text(fixture_text("minimal"))
    analysis = graph.analysis.model_copy(
        update={
            "unresolved": (
                UnresolvedFact(code="future_fact", message="needs attention", node_ids=("work",)),
            )
        }
    )
    report = validate(
        graph.model_copy(update={"analysis": analysis}), source_map, ValidateContext()
    )
    assert not report.runnable
    (problem,) = report.problems
    assert (problem.rule, problem.yaml_path) == ("A0", "nodes[1]")


def test_problem_carries_ids_and_source_range() -> None:
    report = validate_text(_loop(back={"label": "revise", "back": True, "at_limit": "a5"}))
    (problem,) = [p for p in report.for_rule("V5") if "needs limit" in p.message]
    assert problem.arrow_ids == ("a4",)
    assert problem.range is not None and problem.range.start_line > 1
    assert problem.severity == "error"


def test_validate_context_defaults_are_used_when_omitted() -> None:
    graph, source_map = compile_text(fixture_text("minimal"))
    assert validate(graph, source_map).runnable
