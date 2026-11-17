"""Slot handoff phases, labelled step arrows, and inputs that leave the run untouched."""

from __future__ import annotations

import pytest

from coral.engine import empty_state, fold, transition
from coral.engine.types import (
    CancelRun,
    ChooseArrow,
    Effect,
    EffectCompleted,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    PauseCause,
    PauseRun,
    Receipt,
    Rejection,
    RejectionObserved,
    RejectStreak,
    RunState,
    StartRun,
    TimerDue,
    TurnEnded,
    activation_id,
    slot_id,
)
from coral.model.ir import CompiledGraph
from tests.coral.engine.drive import NOW, drive
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    end,
    fixture_text,
    start,
    step,
    workflow_text,
)

CONFIG = EngineConfig()
RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1")
SLOT = "work||:0"
FACT_KEY = "turn:sess-1:1:resp-1"


def _graph(text: str) -> CompiledGraph:
    graph = compile_text(text)[0]
    assert not graph.analysis.unresolved, graph.analysis.unresolved
    return graph


def _labelled_step(*, failure: bool = False) -> CompiledGraph:
    """A single-agent step whose outgoing arrows are the labels ``ok`` and ``broken``."""
    nodes = [start(), step("work"), step("ship"), step("fix"), end()]
    arrows = [
        arrow("a1", "start", "work"),
        arrow("a2", "work", "ship", label="ok"),
        arrow("a3", "work", "fix", label="broken"),
        arrow("a4", "ship", "end"),
        arrow("a5", "fix", "end"),
    ]
    if failure:
        nodes.insert(-1, step("bail"))
        arrows += [arrow("a6", "work", "bail", label="failure"), arrow("a7", "bail", "end")]
    return _graph(workflow_text(nodes, arrows))


def _finish(slot: str, label: str | None = None) -> list[HandoffReceived | HandoffEvaluated]:
    return [
        HandoffReceived(slot_id=slot, body="done", label=label),
        HandoffEvaluated(slot_id=slot, outcome="accepted"),
    ]


def _last_effect(state: RunState, kind: str) -> Effect:
    return next(effect for effect in reversed(state.effects) if effect.kind == kind)


def _node_statuses(state: RunState) -> dict[str, str]:
    return {item.node_id: item.status for item in state.activations}


def test_single_agent_step_takes_the_labelled_arrow_its_handoff_names() -> None:
    graph = _labelled_step()
    driven = drive(graph, [RUN, *_finish(SLOT, label="ok")], config=CONFIG)
    assert driven.state.status == "running"
    opened = _node_statuses(driven.state)
    assert opened["work"] == "closed"
    assert opened["ship"] == "running"
    assert "fix" not in opened
    created = [
        effect.subject for effect in driven.state.effects if effect.kind == "create_session"
    ]
    assert created == [SLOT, "ship||:0"]
    skipped = [item for item in driven.state.receipts if item.key.startswith("skipped:")]
    assert skipped == [
        Receipt(key="skipped:work||:a3", payload={"code": "arrow.skipped", "arrow_id": "a3"})
    ]
    assert driven.state.slots[0].handoff_label == "ok"

    loop = _graph(
        workflow_text(
            [start(), step("work"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "end", label="done"),
                arrow("a3", "work", "work", label="again", back=True, limit=2, at_limit="a4"),
                arrow("a4", "work", "end"),
            ],
        )
    )
    first = slot_id(activation_id("work", (), ("a3:1",)), 0)
    second = slot_id(activation_id("work", (), ("a3:2",)), 0)
    again = drive(loop, [RUN, *_finish(first, label="again")], config=CONFIG)
    assert again.state.status == "running"
    assert [item.iteration_path for item in again.state.activations if item.node_id == "work"] == [
        ("a3:1",),
        ("a3:2",),
    ]
    limited = drive(loop, [*_finish(second, label="again")], config=CONFIG, after=again)
    assert limited.state.status == "completed"
    assert all(item.iteration_path != ("a3:3",) for item in limited.state.activations)
    receipts = {item.key: item.payload for item in limited.state.receipts}
    assert receipts["loop:a3||"] == {"code": "loop.limit_reached", "redirected": True}
    assert receipts["skipped:work||a3:1:a2"] == {"code": "arrow.skipped", "arrow_id": "a2"}
    assert receipts["skipped:work||a3:2:a2"] == {"code": "arrow.skipped", "arrow_id": "a2"}
    assert [item.pass_index for item in limited.state.loop_counters] == [2]


@pytest.mark.parametrize("label", [None, "again"], ids=["no_label", "its_label"])
def test_step_with_only_a_labelled_back_arrow_loops_with_or_without_its_label(
    label: str | None,
) -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "work", label="again", back=True, limit=2, at_limit="a3"),
                arrow("a3", "work", "end"),
            ],
        )
    )
    first = slot_id(activation_id("work", (), ("a2:1",)), 0)
    second = slot_id(activation_id("work", (), ("a2:2",)), 0)
    driven = drive(
        graph, [RUN, *_finish(first, label=label), *_finish(second, label=label)], config=CONFIG
    )
    assert all(entry.rejection is None for entry in driven.log)
    assert driven.state.status == "completed"
    receipts = {item.key: item.payload for item in driven.state.receipts}
    assert receipts["loop:a2||"] == {"code": "loop.limit_reached", "redirected": True}


@pytest.mark.parametrize(
    ("label", "taken", "target", "other"),
    [("again", "b1", "work", "b2"), ("redo", "b2", "prep", "b1")],
)
def test_step_with_two_labelled_back_arrows_takes_only_the_chosen_one(
    label: str, taken: str, target: str, other: str
) -> None:
    graph = _graph(
        workflow_text(
            [start(), step("prep"), step("work"), end()],
            [
                arrow("a1", "start", "prep"),
                arrow("a2", "prep", "work"),
                arrow("b1", "work", "work", label="again", back=True, limit=2, at_limit="x1"),
                arrow("b2", "work", "prep", label="redo", back=True, limit=2, at_limit="x2"),
                arrow("x1", "work", "end"),
                arrow("x2", "work", "end"),
            ],
        )
    )
    prep = slot_id(activation_id("prep", (), ("b2:1",)), 0)
    work = slot_id(activation_id("work", (), ("b2:1", "b1:1")), 0)
    working = drive(graph, [RUN, *_finish(prep)], config=CONFIG)
    unlabelled = drive(graph, _finish(work), after=working)
    assert unlabelled.log[-1].rejection == Rejection(
        code="handoff.invalid", allowed_values=("again", "redo")
    )

    driven = drive(graph, _finish(work, label=label), after=working)
    assert all(entry.rejection is None for entry in driven.log)
    live = [item.node_id for item in driven.state.activations if item.status != "closed"]
    assert live == [target]
    moved = set(driven.state.loop_counters) - set(working.state.loop_counters)
    assert {item.back_arrow_id for item in moved} == {taken}
    owner = activation_id("work", (), ("b2:1", "b1:1"))
    assert any(item.key == f"skipped:{owner}:{other}" for item in driven.state.receipts)


@pytest.mark.parametrize("labelled", [True, False], ids=["labelled", "plain"])
def test_evaluation_without_a_received_handoff_is_not_ready(labelled: bool) -> None:
    graph = _labelled_step() if labelled else _graph(fixture_text("minimal"))
    ended = drive(graph, [RUN, TurnEnded(slot_id=SLOT, fact_key=FACT_KEY)], config=CONFIG)
    assert ended.state.slots[0].status == "evaluating"
    for outcome in ("accepted", "blocked", "evidence_missing"):
        refused = drive(graph, [HandoffEvaluated(slot_id=SLOT, outcome=outcome)], after=ended)
        assert refused.log[-1].rejection == Rejection(code="slot.not_ready"), outcome
        assert refused.state == ended.state
    uncounted = drive(graph, [RejectionObserved(slot_id=SLOT, code="slot.not_ready")], after=ended)
    assert uncounted.state.reject_streaks == ()


@pytest.mark.parametrize(
    ("labelled", "allowed"), [(True, ("ok", "broken")), (False, ())], ids=["labelled", "plain"]
)
def test_handoff_label_outside_the_step_labels_is_handoff_invalid(
    labelled: bool, allowed: tuple[str, ...]
) -> None:
    graph = _labelled_step() if labelled else _graph(fixture_text("minimal"))
    working = drive(graph, [RUN], config=CONFIG)
    refused = drive(
        graph, [HandoffReceived(slot_id=SLOT, body="done", label="nope")], after=working
    )
    assert refused.log[-1].rejection == Rejection(code="handoff.invalid", allowed_values=allowed)
    assert refused.log[-1].effects == ()
    assert refused.state == working.state
    counted = drive(
        graph, [RejectionObserved(slot_id=SLOT, code="handoff.invalid")], after=refused
    )
    assert counted.log[-1].rejection is None
    assert counted.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=1),)


def test_accepted_handoff_on_a_labelled_step_needs_its_label() -> None:
    graph = _labelled_step()
    received = drive(graph, [RUN, HandoffReceived(slot_id=SLOT, body="done")], config=CONFIG)
    assert received.log[-1].rejection is None
    assert received.state.slots[0].status == "evaluating"
    refused = drive(graph, [HandoffEvaluated(slot_id=SLOT, outcome="accepted")], after=received)
    assert refused.log[-1].rejection == Rejection(
        code="handoff.invalid", allowed_values=("ok", "broken")
    )
    assert refused.state == received.state
    counted = drive(
        graph, [RejectionObserved(slot_id=SLOT, code="handoff.invalid")], after=refused
    )
    assert counted.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=1),)

    # Only a corrupt log reaches the finish without a label; the run pauses rather than guess.
    closing = drive(graph, _finish(SLOT, label="ok"), after=drive(graph, [RUN]), auto_ack=False)
    assert closing.state.slots[0].status == "closing"
    corrupt = closing.state.model_copy(
        update={"slots": (closing.state.slots[0].model_copy(update={"handoff_label": None}),)}
    )
    close = _last_effect(corrupt, "close_slot")
    finished = transition(
        graph,
        corrupt,
        EffectCompleted(effect_key=close.effect_key, payload={"pending_input": False}),
        NOW,
        CONFIG,
    )
    assert finished.entry.rejection is None
    assert finished.state.status == "paused"
    assert finished.state.causes == (
        PauseCause(reason="failure_path", detail="handoff_label_missing", subject="work"),
    )
    assert set(_node_statuses(finished.state)) == {"start", "work"}


def test_blocked_handoff_on_a_labelled_step_needs_no_label() -> None:
    blocked = [
        HandoffReceived(slot_id=SLOT, body="cannot"),
        HandoffEvaluated(slot_id=SLOT, outcome="blocked"),
    ]
    routed = drive(_labelled_step(failure=True), [RUN, *blocked], config=CONFIG)
    assert all(entry.rejection is None for entry in routed.log)
    assert routed.state.status == "running"
    work = next(item for item in routed.state.activations if item.node_id == "work")
    assert (work.status, work.outcome) == ("closed", "failed")
    assert set(_node_statuses(routed.state)) == {"start", "work", "bail"}

    paused = drive(_labelled_step(), [RUN, *blocked], config=CONFIG)
    assert all(entry.rejection is None for entry in paused.log)
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="failure_path", detail="blocked", subject=SLOT),
    )


def test_blocked_handoff_ignores_its_label_and_failure_is_not_a_choice() -> None:
    graph = _labelled_step(failure=True)
    working = drive(graph, [RUN], config=CONFIG)
    refused = drive(
        graph, [HandoffReceived(slot_id=SLOT, body="done", label="failure")], after=working
    )
    assert refused.log[-1].rejection == Rejection(
        code="handoff.invalid", allowed_values=("ok", "broken")
    )
    assert refused.state == working.state

    blocked = drive(
        graph,
        [
            HandoffReceived(slot_id=SLOT, body="cannot", label="ok"),
            HandoffEvaluated(slot_id=SLOT, outcome="blocked"),
        ],
        after=working,
    )
    assert all(entry.rejection is None for entry in blocked.log)
    assert set(_node_statuses(blocked.state)) == {"start", "work", "bail"}
    assert all(not item.key.startswith("route:") for item in blocked.state.receipts)


def test_nudged_slot_accepts_a_handoff_and_its_nudge_completes() -> None:
    graph = _graph(fixture_text("minimal"))
    ended = drive(graph, [RUN, TurnEnded(slot_id=SLOT, fact_key=FACT_KEY)], config=CONFIG)
    nudge = _last_effect(ended.state, "nudge")
    assert ended.state.slots[0].status == "evaluating"
    assert ended.state.slots[0].handoff is None

    received = drive(graph, [HandoffReceived(slot_id=SLOT, body="shipped")], after=ended)
    assert received.log[-1].rejection is None
    assert received.state.seq == ended.state.seq + 1
    slot = received.state.slots[0]
    assert (slot.status, slot.handoff) == ("evaluating", "shipped")

    accepted = drive(
        graph,
        [HandoffEvaluated(slot_id=SLOT, outcome="accepted")],
        after=received,
        auto_ack=False,
    )
    assert accepted.state.slots[0].status == "closing"
    late = drive(
        graph, [EffectCompleted(effect_key=nudge.effect_key)], after=accepted, auto_ack=False
    )
    entry = late.log[-1]
    assert entry.rejection is None
    assert entry.receipt_key == nudge.effect_key
    assert entry.effects == ()
    assert late.state.slots == accepted.state.slots
    assert late.state.seq == accepted.state.seq + 1

    close = _last_effect(late.state, "close_slot")
    done = drive(
        graph,
        [EffectCompleted(effect_key=close.effect_key, payload={"pending_input": False})],
        after=late,
    )
    assert done.state.status == "completed"


def test_nudge_completion_returns_a_bodiless_slot_to_work() -> None:
    graph = _graph(fixture_text("minimal"))
    ended = drive(graph, [RUN, TurnEnded(slot_id=SLOT, fact_key=FACT_KEY)], config=CONFIG)
    nudge = _last_effect(ended.state, "nudge")
    resumed = drive(graph, [EffectCompleted(effect_key=nudge.effect_key)], after=ended)
    entry = resumed.log[-1]
    assert entry.rejection is None
    assert entry.receipt_key == nudge.effect_key
    assert entry.effects == ()
    assert resumed.state.slots[0].status == "working"
    assert _node_statuses(resumed.state)["work"] == "running"

    second = drive(
        graph, [TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:resp-2")], after=resumed
    )
    assert second.log[-1].rejection is None
    assert [effect.kind for effect in second.log[-1].effects] == ["nudge"]
    assert second.state.slots[0].status == "evaluating"
    repeat = drive(graph, [EffectCompleted(effect_key=nudge.effect_key)], after=second)
    assert repeat.log[-1].receipt_key == nudge.effect_key
    assert repeat.state == second.state


def test_early_or_closing_handoff_rejection_has_no_input_kinds() -> None:
    graph = _graph(fixture_text("minimal"))
    pending = drive(graph, [RUN], config=CONFIG, auto_ack=False)
    create = _last_effect(pending.state, "create_session")
    created = drive(
        graph, [EffectCompleted(effect_key=create.effect_key)], after=pending, auto_ack=False
    )
    briefed = created.state.model_copy(
        update={"slots": (created.state.slots[0].model_copy(update={"status": "briefed"}),)}
    )
    closing = drive(graph, _finish(SLOT), after=drive(graph, [RUN]), auto_ack=False)
    cases = (
        (pending.state, "pending", "slot.not_ready"),
        (created.state, "session_created", "slot.not_ready"),
        (briefed, "briefed", "slot.not_ready"),
        (closing.state, "closing", "slot.closed"),
    )
    for state, status, code in cases:
        assert state.slots[0].status == status
        result = transition(graph, state, HandoffReceived(slot_id=SLOT, body="early"), NOW, CONFIG)
        assert result.entry.rejection == Rejection(code=code), status
        assert result.state == state
        assert result.entry.effects == ()


def test_evidence_miss_then_turn_end_then_handoff_is_accepted() -> None:
    graph = _labelled_step()
    missed = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="partial", label="ok"),
            HandoffEvaluated(slot_id=SLOT, outcome="evidence_missing", missing=("spec",)),
        ],
        config=CONFIG,
    )
    slot = missed.state.slots[0]
    assert (slot.status, slot.handoff, slot.handoff_label) == ("working", None, None)
    ended = drive(graph, [TurnEnded(slot_id=SLOT, fact_key=FACT_KEY)], after=missed)
    assert ended.state.slots[0].status == "evaluating"

    handoff = HandoffReceived(slot_id=SLOT, body="complete", label="broken")
    direct = drive(graph, [handoff], after=ended)
    assert direct.log[-1].rejection is None
    slot = direct.state.slots[0]
    assert (slot.status, slot.handoff, slot.handoff_label) == ("evaluating", "complete", "broken")

    nudge = _last_effect(ended.state, "nudge")
    nudged = drive(
        graph,
        [
            EffectCompleted(effect_key=nudge.effect_key),
            handoff,
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        after=ended,
    )
    assert all(entry.rejection is None for entry in nudged.log[len(ended.log) :])
    assert nudged.log[len(ended.log)].receipt_key == nudge.effect_key
    opened = _node_statuses(nudged.state)
    assert opened["fix"] == "running"
    assert "ship" not in opened


@pytest.mark.parametrize(
    "command",
    [
        EffectCompleted(effect_key="missing"),
        HandoffReceived(slot_id="work||:0", body="nope"),
        HandoffEvaluated(slot_id="work||:0", outcome="accepted"),
        HandoffEvaluated(slot_id="work||:0", outcome="blocked"),
        CancelRun(),
        PauseRun(reason="user", detail="hold"),
        ChooseArrow(node_id="work", label="go", reason="because"),
        TimerDue(timer_key="watchdog:work:1:1"),
    ],
)
def test_empty_state_rejects_anything_but_start(command: Input) -> None:
    graph = compile_text(fixture_text("minimal"))[0]
    state = empty_state()
    result = transition(graph, state, command, NOW, CONFIG)
    assert result.state == state
    assert result.entry.rejection is not None
    assert result.entry.rejection.code == "rejected"
    assert result.entry.rejection.allowed_values == ("start_run",)
    assert result.entry.rejection.mutates is False
    assert result.entry.effects == ()
    assert result.entry.patch == ()
    assert fold(graph, (result.entry,), CONFIG) == state


def test_start_rejects_unresolved_graph() -> None:
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
    state = empty_state()
    result = transition(
        graph,
        state,
        StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1"),
        NOW,
        CONFIG,
    )
    assert result.state == state
    assert result.entry.rejection is not None
    assert result.entry.rejection.code == "graph.unresolved"
    assert result.entry.effects == ()
    assert fold(graph, (result.entry,), CONFIG) == state
