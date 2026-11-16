"""Loop pass counts, AND and XOR joins, blocked failure routing, and liveness."""

from __future__ import annotations

from coral.engine import fold, transition
from coral.engine.machines.activation import traverse_arrow
from coral.engine.types import (
    AttemptCount,
    ChooseArrow,
    HandoffEvaluated,
    HandoffReceived,
    PauseCause,
    RunState,
    StartRun,
    activation_id,
)
from coral.model.ir import CompiledArrow, CompiledGraph
from tests.coral.engine.drive import NOW, drive
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

RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1")


def _graph(text: str) -> CompiledGraph:
    graph = compile_text(text)[0]
    assert not graph.analysis.unresolved
    return graph


def _finish(slot_id: str, body: str = "done") -> list[HandoffReceived | HandoffEvaluated]:
    return [
        HandoffReceived(slot_id=slot_id, body=body),
        HandoffEvaluated(slot_id=slot_id, outcome="accepted"),
    ]


def _slot(node_id: str, iteration: tuple[str, ...] = ()) -> str:
    return f"{activation_id(node_id, (), iteration)}:0"


def _revise(node_id: str, iteration: tuple[str, ...], reason: str) -> ChooseArrow:
    return ChooseArrow(node_id=node_id, label="revise", reason=reason, iteration_path=iteration)


def _counter(state: RunState, back_arrow_id: str, enclosing: tuple[str, ...]) -> int:
    matched = [
        item.pass_index
        for item in state.loop_counters
        if item.back_arrow_id == back_arrow_id and item.iteration_path == enclosing
    ]
    assert len(matched) == 1
    return matched[0]


def test_loop_limit_three_reaches_end_on_the_third_revise() -> None:
    graph = _graph(fixture_text("loop"))
    first = ("a4:1",)
    second = ("a4:2",)
    third = ("a4:3",)
    opened = drive(graph, [RUN, *_finish(_slot("work", first))])
    assert _counter(opened.state, "a4", ()) == 1
    assert [
        item.iteration_path for item in opened.state.activations if item.node_id == "work"
    ] == [first]

    revised = drive(graph, [RUN, *_finish(_slot("work", first)), _revise("review", first, "once")])
    assert _counter(revised.state, "a4", ()) == 2
    assert {
        item.iteration_path for item in revised.state.activations if item.node_id == "work"
    } == {
        first,
        second,
    }

    done = drive(
        graph,
        [
            RUN,
            *_finish(_slot("work", first)),
            _revise("review", first, "once"),
            *_finish(_slot("work", second)),
            _revise("review", second, "twice"),
            *_finish(_slot("work", third)),
            _revise("review", third, "third"),
        ],
    )
    assert done.state.status == "completed"
    assert _counter(done.state, "a4", ()) == 3
    work = [item for item in done.state.activations if item.node_id == "work"]
    assert [item.iteration_path for item in work] == [first, second, third]
    assert all(item.status == "closed" for item in work)
    assert all(item.iteration_path != ("a4:4",) for item in done.state.activations)
    arrivals = [item.arrow_id for item in done.state.arrivals]
    assert arrivals.count("a5") == 1
    assert "a3" not in arrivals
    assert any(item.payload.get("redirected") is True for item in done.state.receipts)
    assert any(item.payload.get("code") == "loop.limit_reached" for item in done.state.receipts)
    assert any(item.payload.get("code") == "arrow.skipped" for item in done.state.receipts)
    end = next(item for item in done.state.activations if item.node_id == "end")
    assert end.status == "closed"
    assert fold(graph, done.log) == done.state

    choice = f"choice:{activation_id('review', (), third)}:revise"
    again = transition(graph, done.state, _revise("review", third, "third"), NOW)
    assert again.state == done.state
    assert again.entry.rejection is None
    assert again.entry.effects == ()
    assert again.entry.receipt_key == choice
    assert fold(graph, (*done.log, again.entry)) == done.state


def test_nested_inner_counter_starts_at_one_on_the_second_outer_pass() -> None:
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
    outer_1 = ("a8:1",)
    outer_2 = ("a8:2",)
    inner_1 = ("a8:1", "a5:1")
    inner_2 = ("a8:1", "a5:2")
    driven = drive(
        graph,
        [
            RUN,
            *_finish(_slot("outer", outer_1)),
            *_finish(_slot("inner", inner_1)),
            _revise("ireview", inner_1, "inner again"),
            *_finish(_slot("inner", inner_2)),
            ChooseArrow(
                node_id="ireview", label="done", reason="inner ok", iteration_path=inner_2
            ),
            _revise("oreview", outer_1, "outer again"),
            *_finish(_slot("outer", outer_2)),
        ],
    )
    assert driven.state.status == "running"
    assert _counter(driven.state, "a5", outer_1) == 2
    assert _counter(driven.state, "a5", outer_2) == 1
    assert _counter(driven.state, "a8", ()) == 2
    inner = next(
        item for item in driven.state.activations if item.iteration_path == ("a8:2", "a5:1")
    )
    assert inner.node_id == "inner"
    assert inner.status != "closed"
    assert fold(graph, driven.log) == driven.state


def test_blocked_leaves_attempts_unchanged_and_follows_failure() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work", attempts=3), step("bail"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "end"),
                arrow("a3", "work", "bail", label="failure"),
            ],
        )
    )
    slot = _slot("work")
    missing = HandoffEvaluated(slot_id=slot, outcome="evidence_missing", missing=("spec",))
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=slot, body="partial"),
            missing,
            HandoffReceived(slot_id=slot, body="blocked"),
            HandoffEvaluated(slot_id=slot, outcome="blocked"),
        ],
    )
    assert driven.state.status == "running"
    assert driven.state.causes == ()
    assert driven.state.attempts == (AttemptCount(activation_id="work||", used=1),)
    work = next(item for item in driven.state.activations if item.node_id == "work")
    assert work.status == "closed"
    assert work.outcome == "failed"
    closes = [
        effect
        for entry in driven.log
        if entry.rejection is None
        for effect in entry.effects
        if effect.kind == "close_slot" and effect.subject == slot
    ]
    assert len(closes) == 1
    assert closes[0].payload == {"interrupt": True, "closed_label": True}
    assert any(
        item.node_id == "bail" and item.status != "closed" for item in driven.state.activations
    )
    assert all(item.node_id != "end" for item in driven.state.activations)
    assert fold(graph, driven.log) == driven.state


def test_blocked_without_failure_arrow_pauses() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work"), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )
    slot = _slot("work")
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=slot, body="nope"),
            HandoffEvaluated(slot_id=slot, outcome="blocked"),
        ],
    )
    assert driven.state.status == "paused"
    assert driven.state.causes == (
        PauseCause(reason="failure_path", detail="blocked", subject=slot),
    )
    assert driven.state.attempts == ()
    assert fold(graph, driven.log) == driven.state


def test_parallel_merge_waits_until_both_branches_arrive() -> None:
    graph = _graph(fixture_text("parallel"))
    opened = drive(graph, [RUN, *_finish(_slot("plan"))])
    assert opened.state.status == "running"
    assert opened.state.causes == ()
    live = {item.node_id for item in opened.state.activations if item.status != "closed"}
    assert {"build", "docs"} <= live
    assert all(item.node_id != "merge" for item in opened.state.activations)

    waiting = drive(graph, [RUN, *_finish(_slot("plan")), *_finish(_slot("docs"))])
    merge = next(item for item in waiting.state.activations if item.node_id == "merge")
    assert merge.status == "waiting_join"
    assert waiting.state.causes == ()
    assert [item.arrow_id for item in waiting.state.arrivals] == ["a5"]
    assert all(slot.activation_id != merge.id for slot in waiting.state.slots)
    build = next(item for item in waiting.state.activations if item.node_id == "build")
    assert build.status != "closed"
    assert fold(graph, waiting.log) == waiting.state

    done = drive(
        graph,
        [
            RUN,
            *_finish(_slot("plan")),
            *_finish(_slot("docs")),
            *_finish(_slot("build")),
            *_finish(_slot("merge")),
        ],
    )
    assert done.state.status == "completed"
    assert done.state.causes == ()
    assert {item.arrow_id for item in done.state.arrivals} == {"a4", "a5"}
    finished = next(item for item in done.state.activations if item.node_id == "merge")
    assert finished.status == "closed"
    assert fold(graph, done.log) == done.state


def test_second_xor_arrival_starts_nothing() -> None:
    graph = _graph(
        workflow_text(
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
    )
    driven = drive(
        graph,
        [
            RUN,
            ChooseArrow(node_id="pick", label="left", reason="take left"),
            *_finish(_slot("a")),
        ],
    )
    assert driven.state.status == "running"
    started = [item for item in driven.state.activations if item.node_id == "after"]
    assert len(started) == 1
    assert started[0].status != "waiting_join"
    assert [item.arrow_id for item in driven.state.arrivals] == ["a4"]
    assert fold(graph, driven.log) == driven.state

    other = _arrow(graph, "a5")
    state, effects, _receipt = traverse_arrow(driven.state, graph, other)
    assert effects == ()
    assert [item.id for item in state.activations if item.node_id == "after"] == [started[0].id]
    assert any(item.payload.get("code") == "arrow.logged" for item in state.receipts)
    assert sum(item.arrow_id == "a5" for item in state.arrivals) == 1


def test_duplicate_join_arrival_returns_its_receipt() -> None:
    graph = _graph(fixture_text("parallel"))
    waiting = drive(graph, [RUN, *_finish(_slot("plan")), *_finish(_slot("docs"))])
    assert len(waiting.state.arrivals) == 1
    arrival = waiting.state.arrivals[0]
    state, effects, receipt = traverse_arrow(waiting.state, graph, _arrow(graph, arrival.arrow_id))
    assert state == waiting.state
    assert effects == ()
    assert receipt == arrival.receipt_key
    assert fold(graph, waiting.log) == waiting.state


def test_dead_and_source_pauses_liveness() -> None:
    graph = _graph(
        workflow_text(
            [
                start(),
                step("plan"),
                step("build"),
                step("docs"),
                step("merge"),
                step("bail"),
                end(),
            ],
            [
                arrow("a1", "start", "plan"),
                arrow("a2", "plan", "build"),
                arrow("a3", "plan", "docs"),
                arrow("a4", "build", "merge"),
                arrow("a5", "docs", "merge"),
                arrow("a6", "merge", "end"),
                arrow("a7", "build", "bail", label="failure"),
            ],
        )
    )
    live = drive(graph, [RUN, *_finish(_slot("plan"))])
    assert live.state.causes == ()
    assert {item.node_id for item in live.state.activations if item.status != "closed"} >= {
        "build",
        "docs",
    }

    driven = drive(
        graph,
        [
            RUN,
            *_finish(_slot("plan")),
            *_finish(_slot("docs")),
            HandoffReceived(slot_id=_slot("build"), body="cannot"),
            HandoffEvaluated(slot_id=_slot("build"), outcome="blocked"),
        ],
    )
    assert driven.state.status == "paused"
    assert driven.state.causes == (
        PauseCause(
            reason="liveness",
            detail="merge is waiting for build, which can no longer run.",
            subject="build",
        ),
    )
    merge = next(item for item in driven.state.activations if item.node_id == "merge")
    assert merge.status == "waiting_join"
    build = next(item for item in driven.state.activations if item.node_id == "build")
    assert build.status == "closed"
    assert driven.state.attempts == ()
    assert fold(graph, driven.log) == driven.state


def test_non_decision_tail_redirects_at_the_limit() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work"), step("tail"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "tail"),
                arrow("a3", "tail", "work", label="again", back=True, limit=1, at_limit="a4"),
                arrow("a4", "tail", "end"),
            ],
        )
    )
    first = ("a3:1",)
    driven = drive(graph, [RUN, *_finish(_slot("work", first)), *_finish(_slot("tail", first))])
    assert driven.state.status == "completed"
    assert _counter(driven.state, "a3", ()) == 1
    assert [
        item.iteration_path for item in driven.state.activations if item.node_id == "work"
    ] == [first]
    assert any(item.payload.get("code") == "loop.limit_reached" for item in driven.state.receipts)
    assert fold(graph, driven.log) == driven.state


def test_second_pass_of_a_staggered_and_join_stays_live() -> None:
    graph = _graph(
        workflow_text(
            [
                start(),
                step("head"),
                step("left"),
                step("mid"),
                step("right"),
                step("merge"),
                decision("review"),
                end(),
            ],
            [
                arrow("a1", "start", "head"),
                arrow("a2", "head", "left"),
                arrow("a3", "head", "mid"),
                arrow("a4", "left", "merge"),
                arrow("a5", "mid", "right"),
                arrow("a6", "right", "merge"),
                arrow("a7", "merge", "review"),
                arrow("a8", "review", "end", label="approved"),
                arrow("a9", "review", "head", label="revise", back=True, limit=3, at_limit="a10"),
                arrow("a10", "review", "end"),
            ],
        )
    )
    first = ("a9:1",)
    second = ("a9:2",)
    driven = drive(
        graph,
        [
            RUN,
            *_finish(_slot("head", first)),
            *_finish(_slot("left", first)),
            *_finish(_slot("mid", first)),
            *_finish(_slot("right", first)),
            *_finish(_slot("merge", first)),
            _revise("review", first, "again"),
            *_finish(_slot("head", second)),
            *_finish(_slot("left", second)),
        ],
    )
    assert driven.state.status == "running"
    assert driven.state.causes == ()
    merge = next(
        item
        for item in driven.state.activations
        if item.node_id == "merge" and item.iteration_path == second
    )
    assert merge.status == "waiting_join"
    mid = next(
        item
        for item in driven.state.activations
        if item.node_id == "mid" and item.iteration_path == second
    )
    assert mid.status != "closed"
    assert fold(graph, driven.log) == driven.state


def test_and_join_that_is_the_loop_head_starts_one_row() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("left"), step("right"), step("merge"), step("tail"), end()],
            [
                arrow("a1", "start", "left"),
                arrow("a2", "start", "right"),
                arrow("a3", "left", "merge"),
                arrow("a4", "right", "merge"),
                arrow("a5", "merge", "tail"),
                arrow("a7", "tail", "merge", label="again", back=True, limit=1, at_limit="a8"),
                arrow("a8", "tail", "end"),
            ],
        )
    )
    waiting = drive(graph, [RUN, *_finish(_slot("left"))])
    assert waiting.state.status == "running"
    assert waiting.state.causes == ()
    held = [item for item in waiting.state.activations if item.node_id == "merge"]
    assert len(held) == 1
    assert held[0].status == "waiting_join"
    assert held[0].iteration_path == ("a7:1",)

    opened = drive(graph, [RUN, *_finish(_slot("left")), *_finish(_slot("right"))])
    merges = [item for item in opened.state.activations if item.node_id == "merge"]
    assert [item.id for item in merges] == [activation_id("merge", (), ("a7:1",))]
    assert merges[0].status != "waiting_join"
    assert opened.state.status == "running"
    assert fold(graph, opened.log) == opened.state


def test_blocked_slot_does_not_let_a_sibling_take_the_forward_arrow() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work", roster=["a", "b"]), step("bail"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "end"),
                arrow("a3", "work", "bail", label="failure"),
            ],
        )
    )
    owner = activation_id("work")
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=f"{owner}:0", body="cannot"),
            HandoffEvaluated(slot_id=f"{owner}:0", outcome="blocked"),
            HandoffReceived(slot_id=f"{owner}:1", body="done"),
            HandoffEvaluated(slot_id=f"{owner}:1", outcome="accepted"),
        ],
    )
    assert driven.state.status == "running"
    work = next(item for item in driven.state.activations if item.node_id == "work")
    assert work.status == "closed"
    assert work.outcome == "failed"
    assert driven.state.attempts == ()
    bail = next(item for item in driven.state.activations if item.node_id == "bail")
    assert bail.status != "closed"
    assert all(item.node_id != "end" for item in driven.state.activations)
    assert fold(graph, driven.log) == driven.state


def test_attempt_cap_on_one_slot_does_not_let_a_sibling_complete() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work", roster=["a", "b"], attempts=1), step("bail"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "end"),
                arrow("a3", "work", "bail", label="failure"),
            ],
        )
    )
    owner = activation_id("work")
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=f"{owner}:0", body="partial"),
            HandoffEvaluated(slot_id=f"{owner}:0", outcome="evidence_missing", missing=("spec",)),
            HandoffReceived(slot_id=f"{owner}:1", body="done"),
            HandoffEvaluated(slot_id=f"{owner}:1", outcome="accepted"),
        ],
    )
    assert driven.state.status == "running"
    work = next(item for item in driven.state.activations if item.node_id == "work")
    assert work.status == "closed"
    assert work.outcome == "failed"
    assert driven.state.attempts == (AttemptCount(activation_id=owner, used=1),)
    bail = next(item for item in driven.state.activations if item.node_id == "bail")
    assert bail.status != "closed"
    assert all(item.node_id != "end" for item in driven.state.activations)
    assert fold(graph, driven.log) == driven.state


def _arrow(graph: CompiledGraph, arrow_id: str) -> CompiledArrow:
    for item in graph.arrows:
        if item.id == arrow_id:
            return item
    raise AssertionError(arrow_id)
