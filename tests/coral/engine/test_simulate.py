"""Simulate: the real reducer with stub effects, answered from a script."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import random
import subprocess
import sys
import tracemalloc
from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from coral.engine import fold
from coral.engine import simulate as simulate_module
from coral.engine.projection import project
from coral.engine.simulate import (
    DEFAULT_MAX_TRANSITIONS,
    DONE_WHEN_VALUES,
    MAX_GRAPH_SEATS,
    MAX_INPUT_VALUES,
    MAX_SCRIPT_INPUTS,
    MAX_SCRIPT_VALUES,
    MAX_SIMULATED_ARROWS,
    MAX_SIMULATED_NODES,
    MAX_STEP_SEATS,
    MAX_VALUE_CHARS,
    SIMULATED_BY,
    SIMULATED_HANDOFF,
    SIMULATION_RUN_ID,
    STUBBED_EFFECTS,
    UNANSWERED_EFFECTS,
    UNSUPPORTED_EFFECTS,
    SimInput,
    SimLoop,
    SimRejection,
    SimScript,
    SimSessions,
    Simulation,
    SimUnconsumed,
    check_script_text,
    classify_effect,
    simulate,
)
from coral.engine.types import (
    RULES,
    AnswerGate,
    EffectCompleted,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    RunState,
    StartRun,
    Transition,
    activation_id,
    loop_limit_key,
)
from coral.model.canonical import canonical_json
from coral.model.ir import CompiledGraph
from tests.coral.engine.drive import drive
from tests.coral.workflow_builders import (
    FIXTURES,
    arrow,
    compile_text,
    decision,
    end,
    fixture_text,
    gate,
    start,
    step,
    workflow_text,
)

REPO = Path(__file__).resolve().parents[3]
REVIEW_LOOP = REPO / "tests" / "e2e" / "coral" / "fixtures" / "review_loop.yaml"
# The activation cap a run started with the defaults gets.
RUN_CAP = 100
APPROVED = ("approved",)
CHANGES = "changes_requested"

Answer = tuple[str, str, Sequence[str]]


def _review_loop_text(*, limit: int = 2) -> str:
    text = REVIEW_LOOP.read_text().replace("{impl_token}", "").replace("{review_token}", "")
    return text.replace("limit: 2,", f"limit: {limit},")


def _checked_review_text() -> str:
    """The review loop whose label-routed review step also has a done-when check."""
    return _review_loop_text().replace(
        "    roster: [reviewer]\n",
        "    roster: [reviewer]\n    done_when: {commands: [{run: ls}]}\n",
    )


def _graph(text: str) -> CompiledGraph:
    graph = compile_text(text)[0]
    assert not graph.analysis.unresolved, graph.analysis.unresolved
    return graph


def _script(*answers: Answer) -> SimScript:
    return SimScript(
        inputs=tuple(
            SimInput(node_id=node_id, kind=kind, values=tuple(values))  # type: ignore[arg-type]
            for node_id, kind, values in answers
        )
    )


def _run(
    graph: CompiledGraph,
    *answers: Answer,
    max_activations: int = RUN_CAP,
    **bounds: int,
) -> Simulation:
    simulation = simulate(graph, _script(*answers), max_activations=max_activations, **bounds)
    # The same reducer: replaying the log with the run's own config gives the final state.
    assert fold(graph, simulation.log, simulation.config) == simulation.state
    assert simulation.config.max_activations == max_activations
    assert simulation.result.entries == len(simulation.log)
    return simulation


def _path(simulation: Simulation) -> tuple[str, ...]:
    return tuple(f"{item.node_id}:{item.result}" for item in simulation.result.steps)


def test_approved_review_completes_with_three_sessions() -> None:
    simulation = _run(
        _graph(_review_loop_text()),
        ("implement", "done_when", ["pass"]),
        ("review", "label", APPROVED),
        ("approve_change", "gate", ["approve"]),
    )
    result = simulation.result
    assert result.outcome == "completed"
    assert _path(simulation) == ("implement:done", "review:approved", "approve_change:approve")
    assert [item.kind for item in result.steps] == ["step", "step", "gate"]
    assert result.steps[0].activation_id == "implement||a4:1"
    assert result.gates_reached == ("approve_change",)
    assert result.limits_hit == ()
    assert result.step_activations == 2
    assert result.sessions == SimSessions(anchor=1, orchestrator=0, steps=2, total=3)
    assert result.unconsumed == ()
    assert result.needs_input is None and result.rejection is None
    assert result.limit is None
    assert result.view.status == "completed"
    assert len(result.trace_digest) == 64


def test_changes_requested_past_the_limit_takes_the_at_limit_arrow() -> None:
    simulation = _run(
        _graph(_review_loop_text()),
        ("implement", "done_when", ["pass", "pass"]),
        ("review", "label", [CHANGES, CHANGES, CHANGES]),
        ("approve_change", "gate", ["approve"]),
    )
    result = simulation.result
    assert result.outcome == "completed"
    assert _path(simulation) == (
        "implement:done",
        f"review:{CHANGES}",
        "implement:done",
        f"review:{CHANGES}",
        "approve_change:approve",
    )
    assert result.limits_hit == ("a4",)
    assert result.loops == (
        SimLoop(back_arrow_id="a4", iteration_path=(), passes=2, limit=2, limit_hit=True),
    )
    assert result.unconsumed == (SimUnconsumed(node_id="review", kind="label", values=(CHANGES,)),)
    assert result.sessions.total == 5


def test_loop_limit_counts_passes() -> None:
    simulation = _run(
        _graph(_review_loop_text(limit=3)),
        ("implement", "done_when", ["pass"] * 3),
        ("review", "label", [CHANGES] * 3),
        ("approve_change", "gate", ["approve"]),
    )
    result = simulation.result
    assert result.outcome == "completed"
    assert _path(simulation).count(f"review:{CHANGES}") == 3
    assert _path(simulation)[-1] == "approve_change:approve"
    assert result.limits_hit == ("a4",)
    assert result.loops[0].passes == 3
    assert result.loops[0].limit_hit is True
    assert result.unconsumed == ()
    assert result.step_activations == 6
    assert result.sessions.total == 7


def test_a_nested_loop_reports_each_counter_by_its_enclosing_pass() -> None:
    graph = _graph(
        workflow_text(
            [
                start(),
                step("outer"),
                step("inner"),
                decision("ireview"),
                decision("oreview"),
                end(),
            ],
            [
                arrow("a1", "start", "outer"),
                arrow("a2", "outer", "inner"),
                arrow("a3", "inner", "ireview"),
                arrow("a4", "ireview", "oreview", label="done"),
                arrow("a5", "ireview", "inner", label="revise", back=True, limit=3, at_limit="a6"),
                arrow("a6", "ireview", "oreview"),
                arrow("a7", "oreview", "end", label="done"),
                arrow("a8", "oreview", "outer", label="revise", back=True, limit=3, at_limit="a9"),
                arrow("a9", "oreview", "end"),
            ],
        )
    )
    simulation = _run(graph, ("ireview", "label", ["revise"] * 3), ("oreview", "label", ["done"]))
    result = simulation.result
    assert result.outcome == "completed"
    assert result.loops == (
        SimLoop(back_arrow_id="a8", iteration_path=(), passes=1, limit=3, limit_hit=False),
        SimLoop(back_arrow_id="a5", iteration_path=("a8:1",), passes=3, limit=3, limit_hit=True),
    )
    # The decision's own choice receipt also says the limit was reached; it is not counted.
    assert result.limits_hit == ("a5",)
    key = loop_limit_key("a5", (), ("a8:1",))
    assert key == "loop:a5||a8:1"
    assert any(item.key == key for item in simulation.state.receipts)
    # The inner limit hit again on the second outer pass is listed again.
    twice = _run(
        graph, ("ireview", "label", ["revise"] * 6), ("oreview", "label", ["revise", "done"])
    )
    assert twice.result.outcome == "completed"
    assert twice.result.limits_hit == ("a5", "a5")
    assert [
        (item.back_arrow_id, item.iteration_path, item.limit_hit) for item in twice.result.loops
    ] == [
        ("a8", (), False),
        ("a5", ("a8:1",), True),
        ("a5", ("a8:2",), True),
    ]


def test_a_failed_done_when_retries_in_the_same_session() -> None:
    simulation = _run(
        _graph(_review_loop_text()),
        ("implement", "done_when", ["fail", "pass"]),
        ("review", "label", APPROVED),
        ("approve_change", "gate", ["approve"]),
    )
    result = simulation.result
    assert result.outcome == "completed"
    assert _path(simulation)[:2] == ("implement:evidence_missing", "implement:done")
    assert result.sessions.total == 3


def test_done_when_failing_every_attempt_pauses_on_the_failure_path() -> None:
    simulation = _run(_graph(_review_loop_text()), ("implement", "done_when", ["fail"] * 3))
    result = simulation.result
    assert result.outcome == "paused"
    assert _path(simulation) == ("implement:evidence_missing",) * 3
    assert result.view.causes[0].reason == "failure_path"
    assert result.view.causes[0].detail == "attempts_exhausted:c1"


@pytest.mark.parametrize(
    ("answers", "node_id", "kind", "allowed", "path"),
    [
        ((), "implement", "done_when", DONE_WHEN_VALUES, ()),
        (
            (("implement", "done_when", ["pass"]),),
            "review",
            "label",
            ("approved", CHANGES),
            ("implement:done",),
        ),
        (
            (("implement", "done_when", ["pass"]), ("review", "label", APPROVED)),
            "approve_change",
            "gate",
            ("approve", "reject"),
            ("implement:done", "review:approved"),
        ),
    ],
    ids=["done_when", "label", "gate"],
)
def test_an_exhausted_script_asks_for_the_next_value(
    answers: tuple[Answer, ...],
    node_id: str,
    kind: str,
    allowed: tuple[str, ...],
    path: tuple[str, ...],
) -> None:
    simulation = _run(_graph(_review_loop_text()), *answers)
    result = simulation.result
    assert result.outcome == "needs_input"
    assert result.needs_input is not None
    assert result.needs_input.node_id == node_id
    assert result.needs_input.kind == kind
    assert result.needs_input.allowed_values == allowed
    assert result.needs_input.activation_id.startswith(f"{node_id}|")
    assert _path(simulation) == path
    assert result.view.status == "running"


def test_needs_input_consumes_nothing_when_a_second_value_is_missing() -> None:
    simulation = _run(
        _graph(_checked_review_text()),
        ("implement", "done_when", ["pass"]),
        ("review", "done_when", ["pass"]),
    )
    result = simulation.result
    assert result.outcome == "needs_input"
    assert result.needs_input is not None
    assert (result.needs_input.node_id, result.needs_input.kind) == ("review", "label")
    assert result.unconsumed == (
        SimUnconsumed(node_id="review", kind="done_when", values=("pass",)),
    )
    assert _path(simulation) == ("implement:done",)


@pytest.mark.parametrize(
    ("review_done_when", "path"),
    [((), ("implement:done",)), (("fail",), ("implement:done", "review:evidence_missing"))],
    ids=["asked_before_the_label", "a_failed_check_needs_no_label"],
)
def test_a_checked_label_step_asks_for_its_check_first(
    review_done_when: tuple[str, ...], path: tuple[str, ...]
) -> None:
    answers: list[Answer] = [("implement", "done_when", ["pass"])]
    if review_done_when:
        answers.append(("review", "done_when", review_done_when))
    simulation = _run(_graph(_checked_review_text()), *answers)
    asked = simulation.result.needs_input
    assert asked is not None
    assert (asked.node_id, asked.kind, asked.allowed_values) == (
        "review",
        "done_when",
        DONE_WHEN_VALUES,
    )
    assert _path(simulation) == path


def test_a_label_is_consumed_only_by_the_accepted_handoff() -> None:
    simulation = _run(
        _graph(_checked_review_text()),
        ("implement", "done_when", ["pass"]),
        ("review", "done_when", ["fail", "pass"]),
        ("review", "label", APPROVED),
        ("approve_change", "gate", ["approve"]),
    )
    assert simulation.result.outcome == "completed"
    assert _path(simulation) == (
        "implement:done",
        "review:evidence_missing",
        "review:approved",
        "approve_change:approve",
    )
    assert simulation.result.unconsumed == ()


@pytest.mark.parametrize(
    ("fixture", "answers", "rejection"),
    [
        (
            "review_loop",
            (("implement", "done_when", ["pass"]), ("review", "label", ["maybe"])),
            SimRejection(
                node_id="review",
                kind="label",
                value="maybe",
                code="handoff.invalid",
                allowed_values=("approved", CHANGES),
            ),
        ),
        (
            "review_loop",
            (
                ("implement", "done_when", ["pass"]),
                ("review", "label", APPROVED),
                ("approve_change", "gate", ["maybe"]),
            ),
            SimRejection(
                node_id="approve_change",
                kind="gate",
                value="maybe",
                code="tool.illegal",
                allowed_values=("approve", "reject"),
            ),
        ),
        (
            "loop",
            (("review", "label", ["maybe"]),),
            SimRejection(
                node_id="review",
                kind="label",
                value="maybe",
                code="tool.illegal",
                allowed_values=("approved", "revise"),
            ),
        ),
    ],
    ids=["step_label", "gate_value", "decision_label"],
)
def test_an_illegal_value_gets_the_reducers_rejection(
    fixture: str, answers: tuple[Answer, ...], rejection: SimRejection
) -> None:
    text = _review_loop_text() if fixture == "review_loop" else fixture_text(fixture)
    simulation = _run(_graph(text), *answers)
    assert simulation.result.outcome == "rejected"
    assert simulation.result.rejection == rejection
    assert simulation.log[-1].rejection is not None
    assert simulation.log[-1].rejection.code == rejection.code


def test_a_decision_counts_the_orchestrator() -> None:
    simulation = _run(_graph(fixture_text("loop")), ("review", "label", ["revise", "approved"]))
    result = simulation.result
    assert result.outcome == "completed"
    assert _path(simulation) == ("work:done", "review:revise", "work:done", "review:approved")
    assert [item.kind for item in result.steps] == ["step", "decision", "step", "decision"]
    assert result.sessions == SimSessions(anchor=1, orchestrator=1, steps=2, total=4)


def test_a_two_seat_step_counts_two_sessions_per_activation() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("pair", roster=["implementer", "reviewer"]), end()],
            [arrow("a1", "start", "pair"), arrow("a2", "pair", "end")],
        )
    )
    simulation = _run(graph)
    result = simulation.result
    assert result.outcome == "completed"
    assert _path(simulation) == ("pair:done", "pair:done")
    assert result.step_activations == 1
    assert result.sessions == SimSessions(anchor=1, orchestrator=0, steps=2, total=3)


def test_a_gate_asks_with_its_outcomes_in_their_declared_order() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work"), gate("check", outcomes=["approve", "reject"]), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "check"),
                arrow("a3", "check", "end", label="reject"),
                arrow("a4", "check", "end", label="approve"),
            ],
        )
    )
    asked = _run(graph).result.needs_input
    assert asked is not None
    assert (asked.node_id, asked.kind, asked.allowed_values) == (
        "check",
        "gate",
        ("approve", "reject"),
    )


def test_a_gate_in_a_loop_is_answered_on_every_visit() -> None:
    graph = _graph(fixture_text("gated"))
    approved = _run(graph, ("approve_change", "gate", ["reject", "approve"])).result
    assert approved.outcome == "completed"
    assert approved.gates_reached == ("approve_change", "approve_change")
    assert approved.limits_hit == ()
    # The second reject is at the back arrow's limit and takes its at-limit arrow.
    at_limit = _run(graph, ("approve_change", "gate", ["reject", "reject"]))
    assert at_limit.result.outcome == "completed"
    assert _path(at_limit) == (
        "implement:done",
        "approve_change:reject",
        "implement:done",
        "approve_change:reject",
    )
    assert at_limit.result.gates_reached == ("approve_change", "approve_change")
    assert at_limit.result.limits_hit == ("a4",)
    assert at_limit.result.loops == (
        SimLoop(back_arrow_id="a4", iteration_path=(), passes=2, limit=2, limit_hit=True),
    )
    assert at_limit.result.sessions.total == 3


def test_a_parallel_region_hands_off_the_first_slot_in_the_run_state_first() -> None:
    simulation = _run(_graph(fixture_text("parallel")))
    assert simulation.result.outcome == "completed"
    assert _path(simulation) == ("plan:done", "build:done", "docs:done", "merge:done")
    assert simulation.result.sessions.total == 5


def _describe(command: Input) -> str:
    if isinstance(command, EffectCompleted):
        _, _, kind, subject = command.effect_key.split(":", 3)
        return f"ack {kind} {subject}"
    return f"{command.kind} {getattr(command, 'slot_id', '')}".strip()


def test_the_driver_acks_every_effect_before_a_handoff_and_hands_off_before_a_gate() -> None:
    pair = _run(
        _graph(
            workflow_text(
                [start(), step("pair", roster=["implementer", "reviewer"]), end()],
                [arrow("a1", "start", "pair"), arrow("a2", "pair", "end")],
            )
        )
    )
    assert [_describe(entry.input) for entry in pair.log] == [
        "start_run",
        "ack create_session pair||:0",
        "ack create_session pair||:1",
        "ack send_input pair||:0",
        "ack send_input pair||:1",
        "handoff_received pair||:0",
        "handoff_evaluated pair||:0",
        "ack close_slot pair||:0",
        "handoff_received pair||:1",
        "handoff_evaluated pair||:1",
        "ack close_slot pair||:1",
    ]
    branches = _graph(
        workflow_text(
            [
                start(),
                step("plan"),
                step("work"),
                gate("check", outcomes=["approve"]),
                step("merge"),
                end(),
            ],
            [
                arrow("a1", "start", "plan"),
                arrow("a2", "plan", "work"),
                arrow("a3", "plan", "check"),
                arrow("a4", "work", "merge"),
                arrow("a5", "check", "merge", label="approve"),
                arrow("a6", "merge", "end"),
            ],
        )
    )
    both = _run(branches, ("check", "gate", ["approve"]))
    assert both.result.outcome == "completed"
    assert _path(both) == ("plan:done", "work:done", "check:approve", "merge:done")


FIRST_PASS, SECOND_PASS = ("a4:1",), ("a4:2",)


def _handoff(
    node_id: str,
    iteration: tuple[str, ...],
    *,
    label: str | None = None,
    missing: tuple[str, ...] | None = None,
) -> list[Input]:
    """What a host reports for one handoff: received, then accepted or missing evidence."""
    slot_id = f"{activation_id(node_id, (), iteration)}:0"
    received = HandoffReceived(slot_id=slot_id, body=SIMULATED_HANDOFF, label=label)
    if missing is None:
        return [received, HandoffEvaluated(slot_id=slot_id, outcome="accepted")]
    evaluated = HandoffEvaluated(slot_id=slot_id, outcome="evidence_missing", missing=missing)
    return [received, evaluated]


@pytest.mark.parametrize(
    ("answers", "handoffs", "gate"),
    [
        (
            (
                ("implement", "done_when", ["pass"]),
                ("review", "label", APPROVED),
                ("approve_change", "gate", ["approve"]),
            ),
            [
                *_handoff("implement", FIRST_PASS),
                *_handoff("review", FIRST_PASS, label="approved"),
            ],
            "approve",
        ),
        (
            (
                ("implement", "done_when", ["pass", "pass"]),
                ("review", "label", [CHANGES, CHANGES]),
                ("approve_change", "gate", ["approve"]),
            ),
            [
                *_handoff("implement", FIRST_PASS),
                *_handoff("review", FIRST_PASS, label=CHANGES),
                *_handoff("implement", SECOND_PASS),
                *_handoff("review", SECOND_PASS, label=CHANGES),
            ],
            "approve",
        ),
        (
            (
                ("implement", "done_when", ["fail", "pass"]),
                ("review", "label", APPROVED),
                ("approve_change", "gate", ["reject"]),
            ),
            [
                *_handoff("implement", FIRST_PASS, missing=("c1",)),
                *_handoff("implement", FIRST_PASS),
                *_handoff("review", FIRST_PASS, label="approved"),
            ],
            "reject",
        ),
        (
            (("implement", "done_when", ["fail"] * 3),),
            [*_handoff("implement", FIRST_PASS, missing=("c1",))] * 3,
            None,
        ),
    ],
    ids=["approved", "changes_to_the_limit", "check_fails_then_passes", "checks_exhausted"],
)
def test_the_log_equals_the_real_engine_driven_by_hand(
    answers: tuple[Answer, ...], handoffs: list[Input], gate: str | None
) -> None:
    graph = _graph(_review_loop_text())
    simulation = _run(graph, *answers)
    start_run = StartRun(
        run_id=SIMULATION_RUN_ID,
        start_key=SIMULATION_RUN_ID,
        version_hash=graph.content_hash,
        rules=RULES,
    )
    driven = drive(graph, [start_run, *handoffs], config=simulation.config)
    if gate is not None:
        visit = next(item for item in driven.state.gates if item.status == "open")
        answer = AnswerGate(token=visit.token, label=gate, by=SIMULATED_BY)
        driven = drive(graph, [answer], config=simulation.config, after=driven)
    assert driven.log == simulation.log
    assert driven.state == simulation.state


def test_values_no_node_asks_for_are_reported_unconsumed_in_script_order() -> None:
    simulation = _run(
        _graph(fixture_text("two_steps")),
        ("nope", "label", ["x"]),
        ("implement", "gate", ["approve", "reject"]),
    )
    assert simulation.result.outcome == "completed"
    assert simulation.result.unconsumed == (
        SimUnconsumed(node_id="nope", kind="label", values=("x",)),
        SimUnconsumed(node_id="implement", kind="gate", values=("approve", "reject")),
    )


def test_the_transition_cap_ends_in_step_limit() -> None:
    simulation = _run(_graph(fixture_text("two_steps")), max_transitions=5)
    assert simulation.result.outcome == "step_limit"
    assert simulation.result.limit == "transitions"
    assert simulation.result.entries == 5
    assert simulation.state.status == "running"


def test_the_transition_cap_holds_between_a_handoffs_two_inputs() -> None:
    graph = _graph(fixture_text("two_steps"))
    full = _run(graph).result.entries
    for cap in range(1, full):
        simulation = _run(graph, max_transitions=cap)
        result = simulation.result
        assert (result.outcome, result.limit) == ("step_limit", "transitions")
        # A handoff that would not fit is not started, so it is never cut in half.
        assert cap - 1 <= result.entries <= cap
        assert all(slot.status != "evaluating" for slot in simulation.state.slots)
    assert _run(graph, max_transitions=full).result.outcome == "completed"


def test_a_handoff_the_transition_cap_cannot_fit_consumes_nothing() -> None:
    answers: tuple[Answer, ...] = (
        ("implement", "done_when", ["pass"]),
        ("review", "label", APPROVED),
        ("approve_change", "gate", ["approve"]),
    )
    graph = _graph(_review_loop_text())
    full = _run(graph, *answers).result.entries
    kinds = {"implement": "done_when", "review": "label", "approve_change": "gate"}
    for cap in range(1, full):
        result = _run(graph, *answers, max_transitions=cap).result
        # Every scripted value is either on the answered path or left unconsumed.
        used = [(item.node_id, kinds[item.node_id]) for item in result.steps]
        left = [(item.node_id, item.kind) for item in result.unconsumed for _ in item.values]
        assert sorted(used + left) == sorted((node, kind) for node, kind, _ in answers), cap


def test_the_activation_cap_pauses_the_run() -> None:
    simulation = _run(_graph(fixture_text("two_steps")), max_activations=1)
    assert simulation.result.outcome == "paused"
    assert simulation.result.view.causes[0].reason == "budget"


def test_a_graph_with_unresolved_facts_is_refused() -> None:
    graph = compile_text(
        workflow_text(
            [start(), step("a"), step("b"), end()],
            [
                arrow("a1", "start", "a"),
                arrow("a2", "a", "b"),
                arrow("a3", "b", "a"),
                arrow("a4", "b", "end"),
            ],
        )
    )[0]
    assert graph.analysis.unresolved
    with pytest.raises(ValueError, match="unresolved"):
        simulate(graph, SimScript(), max_activations=RUN_CAP)


def _inputs(count: int, values: int = 1) -> list[dict[str, object]]:
    return [
        {"node_id": f"n{index}", "kind": "label", "values": ["v"] * values}
        for index in range(count)
    ]


@pytest.mark.parametrize(
    "inputs",
    [
        [{"node_id": "review", "kind": "list_len", "values": ["2"]}],
        [{"node_id": "implement", "kind": "done_when", "values": ["maybe"]}],
        [
            {"node_id": "review", "kind": "label", "values": ["approved"]},
            {"node_id": "review", "kind": "label", "values": ["approved"]},
        ],
        _inputs(MAX_SCRIPT_INPUTS + 1),
        _inputs(1, MAX_INPUT_VALUES + 1),
        _inputs(11, 91),
        [{"node_id": "review", "kind": "label", "values": [""]}],
        [{"node_id": "review", "kind": "label", "values": ["x" * (MAX_VALUE_CHARS + 1)]}],
        [{"node_id": "review", "kind": "label", "values": []}],
        [{"node_id": "", "kind": "label", "values": ["approved"]}],
        [{"node_id": "n" * 65, "kind": "label", "values": ["approved"]}],
        [{"node_id": "review", "kind": "label", "values": ["approved"], "extra": 1}],
        [{"node_id": "review", "kind": "label", "values": ["bad\ud800"]}],
        [{"node_id": "review\x00", "kind": "label", "values": ["approved"]}],
        [{"node_id": "review", "kind": "label", "values": ["app\u202eroved"]}],
        [{"node_id": "review", "kind": "label", "values": ["line\nbreak"]}],
    ],
    ids=[
        "unknown_kind",
        "done_when_value",
        "duplicate_pair",
        "too_many_inputs",
        "too_many_values_in_one_input",
        "too_many_values",
        "empty_value",
        "long_value",
        "no_values",
        "empty_node_id",
        "long_node_id",
        "unknown_field",
        "lone_surrogate",
        "nul",
        "bidi_control",
        "control_character",
    ],
)
def test_a_malformed_script_is_refused(inputs: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError) as caught:
        SimScript.model_validate({"inputs": inputs})
    # The messages name the rule, never the refused text.
    for error in caught.value.errors():
        assert "\ud800" not in error["msg"] and "\u202e" not in error["msg"]


@pytest.mark.parametrize(
    "value",
    [
        "a\x00b",
        "a\x1fb",
        "a\x7fb",
        "a\x85b",
        "a\x9fb",
        "a\u061cb",
        "a\u200fb",
        "a\u2066b",
        "a\ud800b",
    ],
    ids=["nul", "c0", "del", "nel", "c1", "arabic_mark", "rtl_mark", "isolate", "surrogate"],
)
def test_check_script_text_refuses_controls_bidi_marks_and_surrogates(value: str) -> None:
    with pytest.raises(ValueError, match="control characters") as caught:
        check_script_text(value)
    assert value not in str(caught.value)


def test_check_script_text_returns_plain_text_unchanged() -> None:
    assert (
        check_script_text("changes_requested \u00e9 \u5909\u66f4")
        == "changes_requested \u00e9 \u5909\u66f4"
    )


def test_a_script_at_every_bound_is_accepted() -> None:
    script = SimScript.model_validate(
        {
            "inputs": [
                *_inputs(9, MAX_INPUT_VALUES),
                {
                    "node_id": "n" * 64,
                    "kind": "label",
                    "values": ["x" * MAX_VALUE_CHARS] * MAX_INPUT_VALUES,
                },
            ]
        }
    )
    assert sum(len(item.values) for item in script.inputs) == MAX_SCRIPT_VALUES
    assert len(SimScript.model_validate({"inputs": _inputs(MAX_SCRIPT_INPUTS)}).inputs) == 200


_DIGESTS_PROGRAM = """
import json, sys
from coral.engine.simulate import SimScript, simulate
from coral.model import compile, load
cases = json.load(sys.stdin)
digests = []
for case in cases:
    graph = compile(load(case["text"]))
    script = SimScript.model_validate(case["script"])
    digests.append(simulate(graph, script, max_activations=case["cap"]).result.trace_digest)
print(json.dumps(digests))
"""


def _random_script(rng: random.Random) -> SimScript:
    labels = ("approved", CHANGES, CHANGES, "maybe")
    return _script(
        (
            "implement",
            "done_when",
            [rng.choice(DONE_WHEN_VALUES) for _ in range(rng.randint(1, 6))],
        ),
        ("review", "label", [rng.choice(labels) for _ in range(rng.randint(1, 4))]),
        ("approve_change", "gate", [rng.choice(("approve", "reject"))]),
    )


def test_the_trace_digest_is_deterministic_across_processes_and_hash_seeds() -> None:
    review_loop = _review_loop_text()
    approved = _script(
        ("implement", "done_when", ["pass"]),
        ("review", "label", APPROVED),
        ("approve_change", "gate", ["approve"]),
    )
    rejected = _script(
        ("implement", "done_when", ["pass"]),
        ("review", "label", APPROVED),
        ("approve_change", "gate", ["reject"]),
    )
    rng = random.Random(157)
    cases = [
        (review_loop, approved),
        (review_loop, rejected),
        (fixture_text("parallel"), SimScript()),
        *((review_loop, _random_script(rng)) for _ in range(20)),
    ]
    first = [simulate(_graph(text), script, max_activations=RUN_CAP) for text, script in cases]
    again = [simulate(_graph(text), script, max_activations=RUN_CAP) for text, script in cases]
    assert [item.result for item in first] == [item.result for item in again]
    digests = [item.result.trace_digest for item in first]
    assert digests[0] != digests[1]
    seed = "2" if os.environ.get("PYTHONHASHSEED") == "1" else "1"
    payload = [
        {"text": text, "script": script.model_dump(mode="json"), "cap": RUN_CAP}
        for text, script in cases
    ]
    completed = subprocess.run(
        [sys.executable, "-c", _DIGESTS_PROGRAM],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, "PYTHONHASHSEED": seed},
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == digests


def test_the_trace_digest_covers_every_logged_field() -> None:
    simulation = _run(_graph(_review_loop_text()), ("implement", "done_when", ["pass"]))
    digest = hashlib.sha256()
    for entry in simulation.log:
        digest.update(canonical_json(entry.model_dump(mode="json")) + b"\n")
    assert simulation.result.trace_digest == digest.hexdigest()


def test_the_trace_digest_never_holds_the_whole_log_as_text() -> None:
    # Every session's create effect carries the step's goal, so a long goal makes a long log.
    graph = _graph(
        workflow_text(
            [
                start(),
                step("work", roster=["implementer"] * MAX_STEP_SEATS, goal="x" * 240 * 1024),
                step("review", roster=["reviewer"]),
                end(),
            ],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "review"),
                arrow("a3", "review", "end", label="approved"),
                arrow("a4", "review", "work", label=CHANGES, back=True, limit=8, at_limit="a5"),
                arrow("a5", "review", "end"),
            ],
        )
    )
    script = _script(("review", "label", [CHANGES] * 8))
    tracemalloc.start()
    try:
        simulation = simulate(graph, script, max_activations=RUN_CAP)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    created = sum(
        1
        for entry in simulation.log
        for effect in entry.effects
        if effect.kind == "create_session"
    )
    # The log as one JSON text would be well over 30 MB.
    assert created * 240 * 1024 > 30 * 2**20
    assert peak < 20 * 2**20


def _roster_text(seats: int, steps: int = 1) -> str:
    # A fresh roster list per step: a shared one would dump as a YAML alias.
    nodes = [
        start(),
        *(step(f"s{index}", roster=["implementer"] * seats) for index in range(steps)),
        end(),
    ]
    chain = ["start", *(f"s{index}" for index in range(steps)), "end"]
    arrows = [
        arrow(f"a{index}", source, target)
        for index, (source, target) in enumerate(pairwise(chain))
    ]
    return workflow_text(nodes, arrows)


NO_SESSIONS = SimSessions(anchor=0, orchestrator=0, steps=0, total=0)


@pytest.mark.parametrize(
    ("seats", "steps", "limit"),
    [
        (5000, 1, "step_seats"),
        (MAX_STEP_SEATS + 1, 1, "step_seats"),
        (MAX_STEP_SEATS, MAX_GRAPH_SEATS // MAX_STEP_SEATS + 1, "graph_seats"),
    ],
    ids=["huge_roster", "one_seat_over_the_step_cap", "over_the_graph_cap"],
)
def test_too_many_roster_seats_end_in_step_limit_before_the_run_starts(
    seats: int, steps: int, limit: str
) -> None:
    simulation = _run(_graph(_roster_text(seats, steps)))
    assert simulation.result.outcome == "step_limit"
    assert simulation.result.limit == limit
    assert simulation.result.entries == 0
    assert simulation.result.sessions == NO_SESSIONS


def test_seats_at_both_caps_simulate() -> None:
    assert _run(_graph(_roster_text(MAX_STEP_SEATS))).result.outcome == "completed"
    simulation = _run(_graph(_roster_text(MAX_STEP_SEATS, MAX_GRAPH_SEATS // MAX_STEP_SEATS)))
    assert simulation.result.outcome == "completed"
    assert simulation.result.sessions.steps == MAX_GRAPH_SEATS


def _gate_chains(
    chains: int, length: int, *, fork: bool, tail: int = 0, extra: int = 0
) -> tuple[str, list[Answer]]:
    """Gate chains that all meet at one AND join, beside a short branch.

    ``fork`` splits them from a step beside a second step (the security review's shape);
    otherwise from the start beside one gate (the staff review's shape). ``tail`` gates
    follow the join, each able to reject to the end, the first with ``extra`` more
    outcomes (the re-check's shape). Only the chain gates are answered.
    """
    if fork:
        nodes = [start(), step("fork"), step("side"), step("merge"), end()]
        arrows = [
            arrow("a1", "start", "fork"),
            arrow("a2", "fork", "side"),
            arrow("a3", "side", "merge"),
        ]
        head, answers = "fork", []
    else:
        nodes = [start(), gate("short", outcomes=["approve"]), step("merge"), end()]
        arrows = [arrow("a1", "start", "short"), arrow("a2", "short", "merge", label="approve")]
        head, answers = "start", [("short", "gate", ["approve"])]
    previous, label = "merge", None
    for index in range(tail):
        outcomes = [
            "approve",
            "reject",
            *(f"o{other}" for other in range(extra if index == 0 else 0)),
        ]
        nodes.append(gate(f"t{index}", outcomes=outcomes))
        arrows.append(
            arrow(f"ta{index}", previous, f"t{index}", **({"label": label} if label else {}))
        )
        arrows.extend(
            arrow(f"tr{index}_{item}", f"t{index}", "end", label=item) for item in outcomes[1:]
        )
        previous, label = f"t{index}", "approve"
    arrows.append(arrow("a9", previous, "end", **({"label": label} if label else {})))
    for chain in range(chains):
        arrows.append(arrow(f"h{chain}", head, f"g{chain}_0"))
        for index in range(length):
            node_id = f"g{chain}_{index}"
            target = f"g{chain}_{index + 1}" if index + 1 < length else "merge"
            nodes.append(gate(node_id, outcomes=["approve"]))
            arrows.append(arrow(f"e{chain}_{index}", node_id, target, label="approve"))
            answers.append((node_id, "gate", ["approve"]))
    return workflow_text(nodes, arrows), answers


def _join_shape(
    *, fork: bool, tail: int, fill_arrows: bool, nodes: int = MAX_SIMULATED_NODES
) -> tuple[str, list[Answer]]:
    """Three-gate chains into a join, then a tail, sized to exactly ``nodes`` nodes.

    With ``fill_arrows``, the first tail gate takes extra outcomes up to the arrow cap.
    """
    chains = (nodes - (5 if fork else 4) - tail) // 3
    tail = nodes - (5 if fork else 4) - chains * 3
    text, answers = _gate_chains(chains, 3, fork=fork, tail=tail)
    if not fill_arrows:
        return text, answers
    extra = MAX_SIMULATED_ARROWS - len(_graph(text).arrows)
    return _gate_chains(chains, 3, fork=fork, tail=tail, extra=extra)


@pytest.mark.parametrize(
    "shape",
    [
        _join_shape(fork=False, tail=0, fill_arrows=False, nodes=MAX_SIMULATED_NODES + 1),
        _gate_chains(10, 100, fork=False),
        _join_shape(fork=True, tail=0, fill_arrows=False, nodes=MAX_SIMULATED_NODES + 1),
        _gate_chains(40, 20, fork=True),
        # 128 nodes and 256 arrows: a join, then a gate tail; about 2 s at those caps.
        _gate_chains(30, 3, fork=True, tail=33, extra=66),
    ],
    ids=[
        "staff_just_over",
        "staff_measured",
        "security_just_over",
        "security_measured",
        "recheck_tail_measured",
    ],
)
def test_a_graph_over_the_node_cap_ends_in_step_limit_before_the_run_starts(
    shape: tuple[str, list[Answer]],
) -> None:
    text, answers = shape
    graph = _graph(text)
    assert len(graph.nodes) > MAX_SIMULATED_NODES
    simulation = _run(graph, *answers[:MAX_SCRIPT_INPUTS])
    assert (simulation.result.outcome, simulation.result.limit) == ("step_limit", "graph_size")
    assert simulation.result.entries == 0
    assert simulation.result.sessions == NO_SESSIONS


@pytest.mark.parametrize(
    ("fork", "tail", "fill_arrows"),
    [(False, 0, False), (True, 0, False), (True, MAX_SIMULATED_NODES // 6, True)],
    ids=["staff_at_the_cap", "security_at_the_cap", "tail_and_padding_at_both_caps"],
)
def test_a_join_graph_at_the_node_cap_simulates(fork: bool, tail: int, fill_arrows: bool) -> None:
    text, answers = _join_shape(fork=fork, tail=tail, fill_arrows=fill_arrows)
    graph = _graph(text)
    assert len(graph.nodes) == MAX_SIMULATED_NODES
    if fill_arrows:
        assert len(graph.arrows) == MAX_SIMULATED_ARROWS
    simulation = _run(graph, *answers)
    assert simulation.result.limit is None
    assert simulation.result.outcome in {"paused", "completed", "needs_input"}
    assert simulation.result.entries > 0


def _labelled_choice_text(labels: int) -> str:
    return workflow_text(
        [start(), step("work"), decision("review"), end()],
        [
            arrow("a1", "start", "work"),
            arrow("a2", "work", "review"),
            *(arrow(f"x{index}", "review", "end", label=f"l{index}") for index in range(labels)),
        ],
    )


def test_a_graph_over_the_arrow_cap_ends_in_step_limit_before_the_run_starts() -> None:
    over = _graph(_labelled_choice_text(MAX_SIMULATED_ARROWS - 1))
    assert len(over.nodes) < MAX_SIMULATED_NODES < len(over.arrows)
    refused = _run(over, ("review", "label", ["l0"])).result
    assert (refused.outcome, refused.limit, refused.entries) == ("step_limit", "graph_size", 0)
    at_cap = _graph(_labelled_choice_text(MAX_SIMULATED_ARROWS - 2))
    assert len(at_cap.arrows) == MAX_SIMULATED_ARROWS
    assert _run(at_cap, ("review", "label", ["l0"])).result.outcome == "completed"


def _wide_loop_text(seats: int, limit: int) -> str:
    return workflow_text(
        [
            start(),
            step("work", roster=["implementer"] * seats),
            step("review", roster=["reviewer"]),
            end(),
        ],
        [
            arrow("a1", "start", "work"),
            arrow("a2", "work", "review"),
            arrow("a3", "review", "end", label="approved"),
            arrow("a4", "review", "work", label=CHANGES, back=True, limit=limit, at_limit="a5"),
            arrow("a5", "review", "end"),
        ],
    )


def test_the_work_budget_ends_a_wide_loop_before_the_transition_cap() -> None:
    simulation = _run(
        _graph(_wide_loop_text(MAX_STEP_SEATS, 32)), ("review", "label", [CHANGES] * 100)
    )
    assert simulation.result.outcome == "step_limit"
    assert simulation.result.limit == "work"
    assert simulation.result.entries < DEFAULT_MAX_TRANSITIONS
    assert simulation.state.status == "running"


def test_the_work_budget_counts_the_receipts_a_wide_choice_adds() -> None:
    # Each choice receipts every labelled arrow it skips, copying the receipts each time.
    labels = MAX_SIMULATED_ARROWS - 4
    skipped = [arrow(f"x{index}", "review", "end", label=f"l{index}") for index in range(labels)]
    graph = _graph(
        workflow_text(
            [start(), step("work"), decision("review"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "review"),
                arrow("a3", "review", "work", label="revise", back=True, limit=60, at_limit="a4"),
                arrow("a4", "review", "end"),
                *skipped,
            ],
        )
    )
    assert len(graph.arrows) == MAX_SIMULATED_ARROWS
    simulation = _run(graph, ("review", "label", ["revise"] * 60))
    assert (simulation.result.outcome, simulation.result.limit) == ("step_limit", "work")
    # Charged one state per transition instead, the budget would allow about 40 choices.
    assert len([item for item in simulation.result.steps if item.kind == "decision"]) < 15


def test_a_small_work_budget_ends_in_step_limit() -> None:
    simulation = _run(_graph(fixture_text("two_steps")), max_work=10)
    assert (simulation.result.outcome, simulation.result.limit) == ("step_limit", "work")
    assert 0 < simulation.result.entries < 5


def test_the_work_budget_charges_the_graph_scans_of_every_transition() -> None:
    # Unreachable gates leave the run unchanged and only make the graph larger.
    small = fixture_text("minimal")
    islands = workflow_text(
        [
            start(),
            step("work"),
            end(),
            *(gate(f"i{index}", outcomes=["approve"]) for index in range(MAX_SIMULATED_NODES - 3)),
        ],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )
    assert _run(_graph(small), max_work=300).result.outcome == "completed"
    large = _run(_graph(islands), max_work=300).result
    assert (large.outcome, large.limit) == ("step_limit", "work")
    assert _run(_graph(islands)).result.outcome == "completed"


def test_the_effect_tables_cover_every_kind_the_bridge_knows() -> None:
    from coral.bridge.mapping import FED_KINDS, UNMAPPED_KINDS

    # The bridge maps these three only inside ``map_effect``, in neither set.
    known = (
        FED_KINDS
        | frozenset(UNMAPPED_KINDS)
        | {"publish_gate", "withdraw_gate", "cancel_sessions"}
    )
    stubbed = frozenset(STUBBED_EFFECTS)
    assert known <= stubbed | UNANSWERED_EFFECTS | UNSUPPORTED_EFFECTS
    assert not stubbed & UNANSWERED_EFFECTS
    assert not stubbed & UNSUPPORTED_EFFECTS
    assert not UNANSWERED_EFFECTS & UNSUPPORTED_EFFECTS
    # An acknowledgement reports what the effect's executor would.
    assert {kind: dict(payload) for kind, payload in STUBBED_EFFECTS.items()} == {
        "create_session": {},
        "send_input": {},
        "close_slot": {"pending_input": False},
        "nudge": {},
        "steer": {},
    }


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("create_session", "stubbed"),
        ("send_input", "stubbed"),
        ("close_slot", "stubbed"),
        ("nudge", "stubbed"),
        ("steer", "stubbed"),
        ("publish_gate", "unanswered"),
        ("withdraw_gate", "unanswered"),
        ("notify", "unanswered"),
        ("arm_timer", "unanswered"),
        ("retry_step", "unsupported"),
        ("runner_lost", "unsupported"),
        ("cancel_sessions", "unsupported"),
        ("structure.start_item", "unsupported"),
        ("structure.cancel_region", "unsupported"),
        ("structure.fan_out", "unsupported"),
        ("", "unsupported"),
    ],
)
def test_classify_effect(kind: str, expected: str) -> None:
    assert classify_effect(kind) == expected


def test_an_unclassified_effect_ends_the_simulation_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        simulate_module, "UNANSWERED_EFFECTS", UNANSWERED_EFFECTS - {"publish_gate"}
    )
    simulation = _run(_graph(fixture_text("gate_only")), ("approve", "gate", ["approve"]))
    result = simulation.result
    assert result.outcome == "unsupported"
    assert result.unsupported_effect == "publish_gate"
    assert result.steps == ()
    assert result.unconsumed == (
        SimUnconsumed(node_id="approve", kind="gate", values=("approve",)),
    )


def test_a_run_waiting_on_an_unanswered_effect_stalls(monkeypatch: pytest.MonkeyPatch) -> None:
    stubbed = {kind: payload for kind, payload in STUBBED_EFFECTS.items() if kind != "close_slot"}
    monkeypatch.setattr(simulate_module, "STUBBED_EFFECTS", MappingProxyType(stubbed))
    monkeypatch.setattr(simulate_module, "UNANSWERED_EFFECTS", UNANSWERED_EFFECTS | {"close_slot"})
    simulation = _run(_graph(fixture_text("minimal")))
    result = simulation.result
    assert result.outcome == "stalled"
    assert result.stall_code is None
    assert _path(simulation) == ("work:done",)
    assert result.view.status == "running"


def test_a_refused_generated_input_stalls_with_the_reducers_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The driver then hands off a label-routed step without its label.
    monkeypatch.setattr(simulate_module, "routes_by_label", lambda graph, node_id: False)
    simulation = _run(
        _graph(_review_loop_text()),
        ("implement", "done_when", ["pass"]),
        ("review", "label", APPROVED),
    )
    result = simulation.result
    assert result.outcome == "stalled"
    assert result.stall_code == "handoff.invalid"
    assert result.rejection is None
    assert simulation.log[-1].rejection is not None
    assert _path(simulation) == ("implement:done",)
    assert result.unconsumed == (SimUnconsumed(node_id="review", kind="label", values=APPROVED),)


def test_a_refused_unlabelled_handoff_stalls_rather_than_rejecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_transition = simulate_module.transition

    def stale_handoffs(
        graph: CompiledGraph,
        state: RunState,
        command: Input,
        now: datetime,
        config: EngineConfig | None = None,
    ) -> Transition:
        # A handoff from an older session generation, which the reducer supersedes.
        if isinstance(command, HandoffReceived):
            command = command.model_copy(update={"session_generation": 0})
        return real_transition(graph, state, command, now, config)

    monkeypatch.setattr(simulate_module, "transition", stale_handoffs)
    simulation = _run(_graph(fixture_text("minimal")))
    result = simulation.result
    assert result.outcome == "stalled"
    assert result.stall_code == "slot.superseded"
    assert result.rejection is None
    assert result.steps == ()


def test_a_refused_acknowledgement_stalls_with_the_reducers_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A gate's publication has no slot, so the reducer refuses its acknowledgement.
    stubbed = {**STUBBED_EFFECTS, "publish_gate": MappingProxyType({})}
    monkeypatch.setattr(simulate_module, "STUBBED_EFFECTS", MappingProxyType(stubbed))
    monkeypatch.setattr(
        simulate_module, "UNANSWERED_EFFECTS", UNANSWERED_EFFECTS - {"publish_gate"}
    )
    simulation = _run(_graph(fixture_text("gate_only")), ("approve", "gate", ["approve"]))
    result = simulation.result
    assert result.outcome == "stalled"
    assert result.stall_code == "rejected"
    assert result.steps == ()
    assert result.unconsumed == (
        SimUnconsumed(node_id="approve", kind="gate", values=("approve",)),
    )


def _answer_every_question(graph: CompiledGraph) -> Simulation:
    """Simulate, answering each needs_input with ``pass`` or the first allowed value."""
    answers: dict[tuple[str, str], list[str]] = {}
    for _ in range(MAX_INPUT_VALUES):
        simulation = _run(
            graph, *((node_id, kind, values) for (node_id, kind), values in answers.items())
        )
        asked = simulation.result.needs_input
        if asked is None:
            return simulation
        value = "pass" if asked.kind == "done_when" else asked.allowed_values[0]
        answers.setdefault((asked.node_id, asked.kind), []).append(value)
    raise AssertionError("the simulation kept asking")


_SWEPT = {
    **{path.stem: path for path in sorted(FIXTURES.glob("*.yaml"))},
    "e2e_review_loop": REVIEW_LOOP,
    "pr_review_loop_template": REPO / "coral" / "templates" / "pr_review_loop.yaml",
}


# Fixtures whose analysis leaves facts unresolved: validation refuses them, and so does Simulate.
_UNRESOLVED = frozenset({"deadlock_join"})


@pytest.mark.parametrize("name", sorted(_SWEPT))
def test_every_fixture_simulates_without_an_unsupported_effect_or_a_stall(name: str) -> None:
    text = _SWEPT[name].read_text().replace("{impl_token}", "").replace("{review_token}", "")
    graph = compile_text(text)[0]
    assert bool(graph.analysis.unresolved) == (name in _UNRESOLVED)
    if name in _UNRESOLVED:
        with pytest.raises(ValueError, match="unresolved"):
            simulate(graph, SimScript(), max_activations=RUN_CAP)
        return
    simulation = _answer_every_question(graph)
    assert simulation.result.outcome not in {"unsupported", "stalled", "rejected"}
    for entry in simulation.log:
        for effect in entry.effects:
            assert classify_effect(effect.kind) != "unsupported", effect.kind
    # The test driver, given the same answers and acking on its own, reaches the same run.
    answers = [
        entry.input for entry in simulation.log if not isinstance(entry.input, EffectCompleted)
    ]
    replayed = drive(graph, answers, config=simulation.config)
    assert project(replayed.state) == simulation.result.view


_ALLOWED_IMPORTS = frozenset(
    {"__future__", "collections", "dataclasses", "datetime", "hashlib", "re", "types", "typing"}
    | {"pydantic", "yaml"}
)


@pytest.mark.parametrize("module", ["simulate", "simcase"])
def test_simulate_modules_import_only_pure_names(module: str) -> None:
    """Simulate executes nothing: no I/O, process or network module, no app-tier code."""
    tree = ast.parse((REPO / "coral" / "engine" / f"{module}.py").read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            imported.append(node.module)
    assert imported
    for name in imported:
        top = name.split(".", 1)[0]
        pure = name.startswith(("coral.engine.", "coral.model.")) or name in {
            "coral.engine",
            "coral.model",
        }
        assert top in _ALLOWED_IMPORTS or pure, name
