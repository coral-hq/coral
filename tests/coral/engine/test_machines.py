"""Unknown inputs and unresolved graphs leave the run untouched."""

from __future__ import annotations

import pytest

from coral.engine import empty_state, fold, transition
from coral.engine.types import (
    CancelRun,
    ChooseArrow,
    EffectCompleted,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    PauseRun,
    StartRun,
    TimerDue,
)
from tests.coral.engine.drive import NOW
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
