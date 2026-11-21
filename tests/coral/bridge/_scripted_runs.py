"""Engine runs the bridge tests read: fixture graphs, handoff bodies and replayed logs."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from coral.engine import empty_state, transition
from coral.engine.machines.activation import choosable_labels, find_activation, routes_by_label
from coral.engine.types import (
    RULES,
    AnswerGate,
    CancelRun,
    ChooseArrow,
    EffectCompleted,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    LogEntry,
    PauseRun,
    ResumeRun,
    RunState,
    SessionFailed,
    StartRun,
    TimerDue,
    TurnEnded,
)
from coral.model.ids import derived_id
from coral.model.ir import CompiledGraph
from tests.coral.engine.drive import NOW, Driven, drive
from tests.coral.workflow_builders import compile_text, fixture_text

# A non-zero workspace, so a missing workspace argument cannot pass by default.
WORKSPACE = 7
RUN_ID = derived_id("coral-run", "alice", "start-1")
START_KEY = "start-1"
IMPLEMENT = "implement||:0"
REVIEW = "review||:0"


def fixture_graph(name: str) -> CompiledGraph:
    return compile_text(fixture_text(name))[0]


def start_run(graph: CompiledGraph, run_id: str = RUN_ID) -> StartRun:
    return StartRun(
        run_id=run_id, start_key=START_KEY, version_hash=graph.content_hash, rules=RULES
    )


def handoff_body(
    activation_id: str, report: str, *, status: str = "done", label: str | None = None
) -> str:
    """The canonical body ``coral_submit_handoff`` commits."""
    fields: dict[str, object] = {
        "activation_id": activation_id,
        "status": status,
        "report": report,
    }
    if label is not None:
        fields["label"] = label
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def accept(slot_id: str, report: str, *, label: str | None = None) -> tuple[Input, ...]:
    """A done handoff of ``slot_id`` and its acceptance, as the submit planner commits them."""
    activation = slot_id.rsplit(":", 1)[0]
    return (
        HandoffReceived(slot_id=slot_id, body=handoff_body(activation, report, label=label)),
        HandoffEvaluated(slot_id=slot_id, outcome="accepted"),
    )


def _effect_of(driven: Driven, kind: str) -> str:
    return next(effect.effect_key for effect in driven.log[-1].effects if effect.kind == kind)


def eventful_two_steps(graph: CompiledGraph) -> Driven:
    """The two-step run with a failed turn, its backoff nudge, a turn-end nudge, a pause,
    a resume and a refused late input, each at its own time."""
    driven = drive(graph, [start_run(graph)])
    failed = SessionFailed(
        slot_id=IMPLEMENT,
        failure_class="infra.transient",
        cause="529",
        fact_key="turn:s:1:msg:a",
    )
    driven = drive(graph, [failed], after=driven, now=NOW + timedelta(minutes=1))
    stage_one = min(driven.state.timers, key=lambda timer: timer.stage)
    driven = drive(graph, [TimerDue(timer_key=stage_one.key)], after=driven, now=stage_one.due_at)
    later = stage_one.due_at + timedelta(seconds=5)
    driven = drive(
        graph, [EffectCompleted(effect_key=_effect_of(driven, "nudge"))], after=driven, now=later
    )
    ended = TurnEnded(slot_id=IMPLEMENT, fact_key="turn:s:1:msg:b")
    driven = drive(graph, [ended], after=driven, now=later + timedelta(minutes=1))
    driven = drive(
        graph,
        [EffectCompleted(effect_key=_effect_of(driven, "nudge"))],
        after=driven,
        now=later + timedelta(minutes=2),
    )
    driven = drive(
        graph,
        accept(IMPLEMENT, "Implemented the bridge."),
        after=driven,
        now=later + timedelta(minutes=5),
    )
    driven = drive(
        graph,
        [PauseRun(reason="user", detail="look"), ResumeRun()],
        after=driven,
        now=later + timedelta(minutes=6),
    )
    driven = drive(
        graph, accept(REVIEW, "Looks right."), after=driven, now=later + timedelta(minutes=7)
    )
    return drive(
        graph,
        [HandoffEvaluated(slot_id=REVIEW, outcome="accepted")],
        after=driven,
        now=later + timedelta(minutes=8),
    )


def next_inputs(graph: CompiledGraph, state: RunState) -> tuple[Input, ...]:
    """Hand off the first working slot, else choose the first open decision or gate label."""
    for slot in state.slots:
        if slot.status != "working":
            continue
        owner = find_activation(state, slot.activation_id)
        node_id = owner.node_id if owner is not None else ""
        labels = choosable_labels(graph, node_id)
        label = labels[0] if labels and routes_by_label(graph, node_id) else None
        return accept(slot.id, f"report of {slot.id}", label=label)
    for decision in state.decisions:
        if decision.status == "decided":
            continue
        owner = find_activation(state, decision.activation_id)
        if owner is None or owner.status == "closed":
            continue
        return (
            ChooseArrow(
                node_id=decision.node_id,
                label=choosable_labels(graph, decision.node_id)[0],
                reason="the first label",
                item_path=owner.item_path,
                iteration_path=owner.iteration_path,
            ),
        )
    for visit in state.gates:
        if visit.status == "open":
            node_id = visit.activation_id.split("|", 1)[0]
            return (
                AnswerGate(
                    token=visit.token, label=choosable_labels(graph, node_id)[0], by="alice"
                ),
            )
    return ()


def exercise(graph: CompiledGraph) -> Driven:
    """Run ``graph`` to its end with a pause, a resume, a refused input and a late cancel."""
    driven = drive(graph, [start_run(graph), PauseRun(reason="user", detail="look"), ResumeRun()])
    for _ in range(40):
        inputs = next_inputs(graph, driven.state)
        if not inputs:
            break
        driven = drive(graph, inputs, after=driven)
    return drive(
        graph,
        [HandoffEvaluated(slot_id="no-such-slot", outcome="accepted"), CancelRun()],
        after=driven,
    )


@dataclass(frozen=True)
class Step:
    """One logged input with the state before and after it."""

    before: RunState
    entry: LogEntry
    after: RunState


def replay(
    graph: CompiledGraph, log: Sequence[LogEntry], config: EngineConfig | None = None
) -> list[Step]:
    """Re-apply ``log`` and pair every entry with the states around it."""
    cfg = config if config is not None else EngineConfig()
    state = empty_state()
    steps: list[Step] = []
    for entry in log:
        result = transition(graph, state, entry.input, entry.now, cfg)
        assert result.entry == entry
        steps.append(Step(before=state, entry=entry, after=result.state))
        state = result.state
    return steps
