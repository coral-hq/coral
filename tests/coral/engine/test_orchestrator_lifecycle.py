"""Run-level Retry and the orchestrator's backoff ladder."""

from __future__ import annotations

from datetime import timedelta

import pytest

from coral.engine import transition
from coral.engine.lifecycle import run_level_retryable
from coral.engine.machines.run import accepted_kinds
from coral.engine.types import (
    RULES,
    ChooseArrow,
    EffectCompleted,
    HandoffEvaluated,
    HandoffReceived,
    OrchestratorTurn,
    PauseCause,
    PauseRun,
    Rejection,
    ResumeRun,
    RetryRun,
    RunState,
    StartRun,
    TimerDue,
)
from coral.model.ir import CompiledGraph
from tests.coral.engine.drive import NOW, Driven, drive
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    start,
    step,
    workflow_text,
)

RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1", rules=RULES)
SLOT = "work||:0"
TRANSIENT = OrchestratorTurn(failed=True, failure="infra.transient")


def _graph(text: str) -> CompiledGraph:
    graph = compile_text(text)[0]
    assert not graph.analysis.unresolved, graph.analysis.unresolved
    return graph


def _step_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), step("work"), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )


def _decision_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), decision("choose"), step("work"), step("other"), end()],
            [
                arrow("a1", "start", "choose"),
                arrow("a2", "choose", "work", label="approved"),
                arrow("a3", "choose", "other", label="rejected"),
                arrow("a4", "work", "end"),
                arrow("a5", "other", "end"),
            ],
        )
    )


def _with_causes(state: RunState, *causes: PauseCause) -> RunState:
    return state.model_copy(update={"status": "paused", "causes": causes})


def _run_level(detail: str) -> PauseCause:
    return PauseCause(reason="failure_path", detail=detail, subject="")


def _key(stage: int) -> str:
    return f"orchestrator_backoff:orchestrator:{stage}"


def _ladder(driven: Driven) -> list[tuple[str, int, int, timedelta]]:
    return [
        (timer.subject, timer.generation, timer.stage, timer.due_at - NOW)
        for timer in driven.state.timers
        if timer.kind == "orchestrator_backoff"
    ]


def _due(graph: CompiledGraph, driven: Driven, stage: int, after: timedelta) -> Driven:
    return drive(graph, [TimerDue(timer_key=_key(stage))], after=driven, now=NOW + after)


@pytest.mark.parametrize(
    ("detail", "bumped"),
    [
        ("anchor:dispatch.failed", False),
        ("gate:dispatch.failed", False),
        ("unbuildable", False),
        ("orchestrator:session.failed", True),
        ("decision:drift.session_archived", True),
    ],
)
def test_retry_run_clears_a_run_level_cause_and_bumps_only_for_the_orchestrator(
    detail: str, bumped: bool
) -> None:
    graph = _decision_graph()
    paused = drive(graph, [RUN, PauseRun(reason="failure_path", detail=detail)])
    assert run_level_retryable(paused.state) == (_run_level(detail),)
    retried = drive(graph, [RetryRun()], after=paused)
    assert retried.log[-1].rejection is None
    assert (retried.state.status, retried.state.causes) == ("running", ())
    assert retried.state.orchestrator_generation == (2 if bumped else 1)


def test_retry_run_keeps_step_and_other_causes_and_stays_paused() -> None:
    graph = _step_graph()
    step_cause = PauseCause(reason="failure_path", detail="agent.failed", subject=SLOT)
    infra = PauseCause(reason="infra", detail="anchor:session.failed", subject="")
    paused = _with_causes(
        drive(graph, [RUN]).state, infra, _run_level("orchestrator:x"), step_cause
    )
    retried = transition(graph, paused, RetryRun(), NOW)
    assert retried.entry.rejection is None
    assert (retried.state.status, retried.state.causes) == ("paused", (infra, step_cause))
    assert retried.state.orchestrator_generation == 2
    assert retried.entry.effects == ()


@pytest.mark.parametrize(
    ("held", "code"),
    [
        (
            PauseCause(reason="infra", detail="infra.host_offline", subject=SLOT),
            "host_offline_hold",
        ),
        (
            PauseCause(reason="infra", detail="recovery.restarting", subject=SLOT),
            "restart_in_progress",
        ),
        (PauseCause(reason="user", detail="hold", subject=""), "retry_not_allowed"),
        (
            PauseCause(reason="failure_path", detail="agent.failed", subject=SLOT),
            "retry_not_allowed",
        ),
    ],
    ids=["host_offline", "restarting", "user_only", "step_only"],
)
def test_retry_run_refusals(held: PauseCause, code: str) -> None:
    graph = _step_graph()
    causes = (held,) if held.reason in {"user", "failure_path"} else (held, _run_level("anchor:x"))
    paused = _with_causes(drive(graph, [RUN]).state, *causes)
    refused = transition(graph, paused, RetryRun(), NOW)
    assert refused.entry.rejection == Rejection(code=code)
    assert refused.state == paused


def test_retry_run_of_a_running_run_or_past_the_generation_bound_is_refused() -> None:
    graph = _decision_graph()
    running = drive(graph, [RUN]).state
    assert transition(graph, running, RetryRun(), NOW).entry.rejection == Rejection(
        code="retry_not_allowed"
    )
    at_bound = _with_causes(
        running.model_copy(update={"orchestrator_generation": 32_767}),
        _run_level("orchestrator:session.failed"),
    )
    refused = transition(graph, at_bound, RetryRun(), NOW)
    assert refused.entry.rejection == Rejection(code="retry_not_allowed")


def test_retry_run_back_to_running_reprompts_as_resume_does() -> None:
    graph = _step_graph()
    started = drive(graph, [RUN]).state
    slots = tuple(
        slot.model_copy(update={"failed_turn": "turn:s:1:a"}) if slot.id == SLOT else slot
        for slot in started.slots
    )
    failed = started.model_copy(update={"slots": slots})
    retried = transition(graph, _with_causes(failed, _run_level("anchor:x")), RetryRun(), NOW)
    resumed = transition(
        graph,
        _with_causes(failed, PauseCause(reason="user", detail="hold", subject="")),
        ResumeRun(),
        NOW,
    )
    assert retried.entry.effects == resumed.entry.effects
    assert [(item.kind, item.payload["reason"]) for item in retried.entry.effects] == [
        ("nudge", "resume")
    ]
    assert retried.state == resumed.state


def test_transient_orchestrator_failure_backs_off_then_pauses() -> None:
    graph = _decision_graph()
    armed = drive(graph, [RUN, TRANSIENT])
    assert armed.state.status == "running"
    assert _ladder(armed) == [
        ("orchestrator", 1, 1, timedelta(seconds=30)),
        ("orchestrator", 1, 2, timedelta(minutes=2)),
        ("orchestrator", 1, 3, timedelta(minutes=8)),
    ]
    again = drive(graph, [TRANSIENT], after=armed, now=NOW + timedelta(seconds=10))
    assert again.state == armed.state

    first = _due(graph, again, 1, timedelta(seconds=30))
    second = _due(graph, first, 2, timedelta(minutes=2))
    for driven, stage in ((first, 1), (second, 2)):
        (effect,) = driven.log[-1].effects
        assert (effect.kind, effect.subject, effect.payload) == (
            "notify",
            "orchestrator",
            {"kind": "orchestrator_backoff", "stage": stage},
        )
        assert driven.state.status == "running"
    third = _due(graph, second, 3, timedelta(minutes=8))
    assert third.log[-1].effects == ()
    assert third.state.causes == (
        PauseCause(reason="infra", detail="orchestrator:infra.transient", subject=""),
    )
    assert _ladder(third) == []


def test_a_stage_3_pause_also_drops_earlier_stages_still_armed() -> None:
    graph = _decision_graph()
    armed = drive(graph, [RUN, TRANSIENT])
    # Stages 1 and 2 were late; stage 3 fires first.
    paused = _due(graph, armed, 3, timedelta(minutes=8))
    assert paused.state.status == "paused"
    assert _ladder(paused) == []


def test_a_completed_turn_or_a_decision_disarms_the_ladder() -> None:
    graph = _decision_graph()
    armed = drive(graph, [RUN, TRANSIENT])
    replied = drive(graph, [OrchestratorTurn(failed=False)], after=armed)
    assert _ladder(replied) == []
    quiet = drive(graph, [OrchestratorTurn(failed=False)], after=replied)
    assert quiet.state == replied.state

    decided = drive(
        graph, [ChooseArrow(node_id="choose", label="approved", reason="ok")], after=armed
    )
    assert decided.log[-1].rejection is None
    assert _ladder(decided) == []


def test_a_stale_generation_or_paused_run_stage_only_disarms() -> None:
    graph = _decision_graph()
    armed = drive(graph, [RUN, TRANSIENT])
    stale = armed.state.model_copy(update={"orchestrator_generation": 2})
    fired = transition(graph, stale, TimerDue(timer_key=_key(3)), NOW + timedelta(minutes=8))
    assert fired.entry.effects == ()
    assert (fired.state.status, fired.state.causes) == ("running", ())
    assert [timer.key for timer in fired.state.timers if timer.kind == "orchestrator_backoff"] == [
        _key(1),
        _key(2),
    ]

    paused = drive(graph, [PauseRun(reason="user", detail="hold")], after=armed)
    first = _due(graph, paused, 1, timedelta(seconds=30))
    assert first.log[-1].effects == ()
    third = _due(graph, first, 3, timedelta(minutes=8))
    assert third.state.causes == (PauseCause(reason="user", detail="hold", subject=""),)
    assert _ladder(third) == [("orchestrator", 1, 2, timedelta(minutes=2))]


def test_orchestrator_retry_drops_the_ladder_and_other_failures_are_not_supported() -> None:
    graph = _decision_graph()
    armed = drive(graph, [RUN, TRANSIENT])
    retried = drive(
        graph,
        [PauseRun(reason="failure_path", detail="orchestrator:session.failed"), RetryRun()],
        after=armed,
    )
    assert retried.state.orchestrator_generation == 2
    assert _ladder(retried) == []
    rearmed = drive(graph, [TRANSIENT], after=retried)
    assert {generation for _, generation, _, _ in _ladder(rearmed)} == {2}

    refused = transition(graph, armed.state, OrchestratorTurn(failed=True, failure="auth"), NOW)
    assert refused.entry.rejection == Rejection(code="not_supported")
    paused = drive(graph, [PauseRun(reason="user", detail="hold"), TRANSIENT], after=retried)
    assert _ladder(paused) == []


def test_retry_run_finishes_a_pending_close_as_resume_does() -> None:
    graph = _step_graph()
    closing = drive(
        graph,
        [
            HandoffReceived(slot_id=SLOT, body="done"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        after=drive(graph, [RUN]),
        auto_ack=False,
    )
    close = next(effect for effect in closing.state.effects if effect.kind == "close_slot")
    paused = drive(
        graph,
        [
            PauseRun(reason="failure_path", detail="anchor:dispatch.failed"),
            EffectCompleted(effect_key=close.effect_key, payload={"pending_input": True}),
            ResumeRun(),
        ],
        after=closing,
        auto_ack=False,
    )
    assert paused.state.causes == (_run_level("anchor:dispatch.failed"),)
    assert "retry_run" in accepted_kinds(paused.state)
    retried = drive(graph, [RetryRun()], after=paused, auto_ack=False)
    assert retried.state.status == "completed"
    assert "orchestrator_turn" not in accepted_kinds(retried.state)


def test_both_live_states_accept_an_orchestrator_turn() -> None:
    graph = _decision_graph()
    running = drive(graph, [RUN])
    paused = drive(graph, [PauseRun(reason="user", detail="hold")], after=running)
    assert "orchestrator_turn" in accepted_kinds(running.state)
    assert "retry_run" not in accepted_kinds(running.state)
    assert {"orchestrator_turn", "retry_run"} <= set(accepted_kinds(paused.state))
