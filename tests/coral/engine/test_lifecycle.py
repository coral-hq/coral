"""Pause, resume, cancel, retry, activation cap, and rejected calls."""

from __future__ import annotations

import pytest

from coral.engine import fold, transition
from coral.engine.types import (
    AnswerGate,
    CancelRun,
    ChooseArrow,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    InfraBackoffExhausted,
    Input,
    PauseCause,
    PauseReason,
    PauseRun,
    PostCloseActivity,
    RejectionObserved,
    RejectStreak,
    ResumeRun,
    RetryStep,
    RunnerLost,
    SessionFailed,
    StartRun,
    TimerDue,
    TurnEnded,
    UsageLimited,
    WaitingWithoutElicitation,
)
from coral.model.ir import CompiledGraph
from tests.coral.engine.drive import NOW, drive
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    gate,
    start,
    step,
    workflow_text,
)

RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1")
SLOT = "work||:0"
_RESUME_ONLY = (
    "user",
    "rejected_calls",
    "auth",
    "drift",
    "plan_limit",
    "authority_revoked",
)
_RETRY_ONLY = ("failure_path", "liveness")


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


def _gate_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), gate("hold", outcomes=["approve"]), step("work"), end()],
            [
                arrow("a1", "start", "hold"),
                arrow("a2", "hold", "work", label="approve"),
                arrow("a3", "work", "end"),
            ],
        )
    )


def _fan_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [
                start(),
                step("work", roster=["implementer", "reviewer"]),
                gate("hold", outcomes=["approve"]),
                end(),
            ],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "start", "hold"),
                arrow("a3", "work", "end"),
                arrow("a4", "hold", "end", label="approve"),
            ],
        )
    )


@pytest.mark.parametrize("reason", _RESUME_ONLY)
def test_resume_clears_only_its_reasons(reason: PauseReason) -> None:
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason=reason, detail="hold")])
    resumed = transition(graph, paused.state, ResumeRun(), NOW)
    assert resumed.entry.rejection is None
    assert resumed.state.status == "running"
    assert resumed.state.causes == ()
    assert fold(graph, (*paused.log, resumed.entry)) == resumed.state

    retry = transition(graph, paused.state, RetryStep(node_id="work"), NOW)
    assert retry.entry.rejection is not None
    assert retry.entry.rejection.code == "resume_not_allowed"
    assert retry.state == paused.state
    assert retry.entry.effects == ()
    assert fold(graph, (*paused.log, retry.entry)) == paused.state


@pytest.mark.parametrize("reason", (*_RETRY_ONLY, "infra"))
def test_retry_clears_infra_failure_path_and_liveness(reason: PauseReason) -> None:
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason=reason, detail="hold")])
    retried = transition(graph, paused.state, RetryStep(node_id="work"), NOW)
    assert retried.entry.rejection is None
    assert retried.state.causes == ()
    assert retried.state.status == "running"
    assert all(item.node_id != "end" for item in retried.state.activations)
    assert fold(graph, (*paused.log, retried.entry)) == retried.state
    if reason != "infra":
        resume = transition(graph, paused.state, ResumeRun(), NOW)
        assert resume.entry.rejection is not None
        assert resume.entry.rejection.code == "resume_not_allowed"
        assert resume.state == paused.state


def test_infra_also_clears_on_resume() -> None:
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason="infra", detail="hold")])
    resumed = transition(graph, paused.state, ResumeRun(), NOW)
    assert resumed.entry.rejection is None
    assert resumed.state.status == "running"
    assert resumed.state.causes == ()
    assert fold(graph, (*paused.log, resumed.entry)) == resumed.state


def test_budget_resumes_only_with_a_raised_cap() -> None:
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason="budget", detail="activation_cap")])
    blocked = transition(graph, paused.state, ResumeRun(), NOW)
    assert blocked.entry.rejection is not None
    assert blocked.entry.rejection.code == "resume_not_allowed"
    assert blocked.state == paused.state
    same = transition(graph, paused.state, ResumeRun(cap=paused.state.max_activations), NOW)
    assert same.entry.rejection is not None
    assert same.entry.rejection.code == "resume_not_allowed"
    assert same.state == paused.state
    retry = transition(graph, paused.state, RetryStep(node_id="work"), NOW)
    assert retry.entry.rejection is not None
    assert retry.entry.rejection.code == "resume_not_allowed"
    assert retry.state == paused.state
    raised = transition(graph, paused.state, ResumeRun(cap=paused.state.max_activations + 1), NOW)
    assert raised.entry.rejection is None
    assert raised.state.status == "running"
    assert raised.state.causes == ()
    assert raised.state.max_activations == paused.state.max_activations + 1
    assert fold(graph, (*paused.log, raised.entry)) == raised.state


def test_engine_upgrade_rejects_resume_and_retry_then_cancel() -> None:
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason="engine_upgrade", detail="move")])
    resume = transition(graph, paused.state, ResumeRun(cap=100_000), NOW)
    assert resume.entry.rejection is not None
    assert resume.entry.rejection.code == "resume_not_allowed"
    assert resume.state == paused.state
    assert resume.state.max_activations == paused.state.max_activations
    retry = transition(graph, paused.state, RetryStep(node_id="work"), NOW)
    assert retry.entry.rejection is not None
    assert retry.entry.rejection.code == "resume_not_allowed"
    assert retry.state == paused.state
    cancelled = transition(graph, paused.state, CancelRun(), NOW)
    assert cancelled.entry.rejection is None
    assert cancelled.state.status == "cancelled"
    assert cancelled.state.timers == ()
    assert fold(graph, (*paused.log, cancelled.entry)) == cancelled.state


def test_mixed_causes_resume_leaves_failure_path() -> None:
    graph = _step_graph()
    paused = drive(
        graph,
        [
            RUN,
            PauseRun(reason="user", detail="hold"),
            PauseRun(reason="failure_path", detail="blocked"),
        ],
    )
    resumed = transition(graph, paused.state, ResumeRun(), NOW)
    assert resumed.entry.rejection is None
    assert resumed.state.status == "paused"
    assert resumed.state.causes == (
        PauseCause(reason="failure_path", detail="blocked", subject=""),
    )
    assert resumed.state.max_activations == paused.state.max_activations
    assert all(item.node_id != "end" for item in resumed.state.activations)
    assert fold(graph, (*paused.log, resumed.entry)) == resumed.state

    missed = transition(graph, resumed.state, ResumeRun(cap=20_000), NOW)
    assert missed.entry.rejection is not None
    assert missed.entry.rejection.code == "resume_not_allowed"
    assert missed.state == resumed.state
    assert missed.entry.effects == ()
    assert fold(graph, (*paused.log, resumed.entry, missed.entry)) == resumed.state


def test_retry_bumps_generation_resets_attempts_and_does_not_open_successor() -> None:
    graph = _step_graph()
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="partial"),
            HandoffEvaluated(slot_id=SLOT, outcome="evidence_missing", missing=("spec",)),
            PauseRun(reason="failure_path", detail="blocked"),
            RetryStep(node_id="work"),
        ],
    )
    assert driven.state.status == "running"
    assert driven.state.causes == ()
    slot = driven.state.slots[0]
    assert slot.session_generation == 2
    assert slot.status == "pending"
    assert driven.state.attempts[0].used == 0
    work = next(item for item in driven.state.activations if item.node_id == "work")
    assert work.status == "starting"
    assert work.outcome is None
    assert all(item.node_id != "end" for item in driven.state.activations)
    effect = driven.log[-1].effects[0]
    assert [item.kind for item in driven.log[-1].effects] == ["retry_step"]
    assert effect.payload == {
        "generation": 2,
        "phases": ["fence_stop", "create_unbriefed", "salvage_reset", "brief"],
    }
    assert fold(graph, driven.log) == driven.state


def test_stale_generation_does_not_pause_nudge_or_keep_old_backoff() -> None:
    graph = _step_graph()
    running = drive(graph, [RUN])
    failed = transition(
        graph,
        running.state,
        SessionFailed(
            slot_id=SLOT,
            failure_class="infra.transient",
            cause="529",
            fact_key="turn:sess-1:1:resp-1",
        ),
        NOW,
    )
    paused = transition(
        graph, failed.state, PauseRun(reason="infra", detail="infra.transient"), NOW
    )
    retried = transition(graph, paused.state, RetryStep(node_id="work"), NOW)
    assert retried.entry.rejection is None
    assert retried.state.slots[0].session_generation == 2
    assert all(timer.kind not in {"infra_backoff", "plan_probe"} for timer in retried.state.timers)
    stage3 = next(
        timer
        for timer in failed.state.timers
        if timer.kind == "infra_backoff" and timer.stage == 3
    )
    late = transition(graph, retried.state, TimerDue(timer_key=stage3.key), NOW)
    assert late.state == retried.state
    assert late.entry.effects == ()

    auth = transition(
        graph,
        retried.state,
        SessionFailed(
            slot_id=SLOT,
            failure_class="auth",
            cause="401",
            fact_key="turn:sess-1:1:old",
        ),
        NOW,
    )
    assert auth.entry.rejection is not None
    assert auth.entry.rejection.code == "slot.superseded"
    assert auth.state == retried.state
    assert auth.entry.effects == ()
    assert fold(graph, (*running.log, failed.entry, paused.entry, retried.entry, auth.entry)) == (
        retried.state
    )

    lost = transition(
        graph, retried.state, RunnerLost(slot_id=SLOT, session_id="sess-1", generation=1), NOW
    )
    assert lost.entry.rejection is not None
    assert lost.entry.rejection.code == "slot.superseded"
    assert lost.state == retried.state

    working = retried.state.model_copy(
        update={"slots": (retried.state.slots[0].model_copy(update={"status": "working"}),)}
    )
    nudged = transition(graph, working, TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:old"), NOW)
    assert nudged.entry.rejection is not None
    assert nudged.entry.rejection.code == "slot.superseded"
    assert nudged.state == working
    assert nudged.entry.effects == ()


def test_retry_of_a_missing_activation_is_rejected() -> None:
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason="failure_path", detail="blocked")])
    missing = transition(graph, paused.state, RetryStep(node_id="missing"), NOW)
    assert missing.entry.rejection is not None
    assert missing.entry.rejection.code == "rejected"
    assert missing.state == paused.state
    assert missing.entry.effects == ()


def test_cancel_then_handoff_choice_and_gate_are_run_cancelled() -> None:
    graph = _step_graph()
    running = drive(graph, [RUN])
    cancelled = transition(graph, running.state, CancelRun(), NOW)
    assert cancelled.state.status == "cancelled"
    handoff = transition(graph, cancelled.state, HandoffReceived(slot_id=SLOT, body="late"), NOW)
    assert handoff.entry.rejection is not None
    assert handoff.entry.rejection.code == "run_cancelled"
    assert handoff.entry.effects == ()
    assert handoff.state == cancelled.state
    evaluated = transition(
        graph,
        cancelled.state,
        HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        NOW,
    )
    assert evaluated.entry.rejection is not None
    assert evaluated.entry.rejection.code == "run_cancelled"
    assert evaluated.entry.effects == ()
    assert evaluated.state == cancelled.state

    choices = _decision_graph()
    opened = drive(choices, [RUN])
    chosen = transition(
        choices,
        opened.state,
        ChooseArrow(node_id="choose", label="approved", reason="ship it"),
        NOW,
    )
    assert chosen.entry.receipt_key == "choice:choose||:approved"
    stopped = transition(choices, chosen.state, CancelRun(), NOW)
    duplicate = transition(
        choices,
        stopped.state,
        ChooseArrow(node_id="choose", label="approved", reason="again"),
        NOW,
    )
    assert duplicate.entry.rejection is not None
    assert duplicate.entry.rejection.code == "run_cancelled"
    assert duplicate.entry.receipt_key is None
    assert duplicate.entry.effects == ()
    assert duplicate.state == stopped.state
    assert fold(choices, (*opened.log, chosen.entry, stopped.entry, duplicate.entry)) == (
        stopped.state
    )

    gates = _gate_graph()
    held = drive(gates, [RUN])
    token = held.state.gates[0].token
    answered = transition(
        gates, held.state, AnswerGate(token=token, label="approve", by="sam", note="ok"), NOW
    )
    resolved = next(item for item in answered.state.gates if item.token == token)
    assert resolved.status == "resolved"
    assert resolved.label == "approve"
    stopped_gate = transition(gates, answered.state, CancelRun(), NOW)
    repeat = transition(
        gates,
        stopped_gate.state,
        AnswerGate(token=token, label="approve", by="sam", note="late"),
        NOW,
    )
    assert repeat.entry.rejection is not None
    assert repeat.entry.rejection.code == "run_cancelled"
    assert repeat.entry.receipt_key is None
    assert repeat.entry.effects == ()
    assert repeat.state == stopped_gate.state


def test_second_cancel_returns_the_receipt() -> None:
    graph = _step_graph()
    running = drive(graph, [RUN])
    first = transition(graph, running.state, CancelRun(), NOW)
    assert first.entry.receipt_key == "cancel:run-1"
    second = transition(graph, first.state, CancelRun(), NOW)
    assert second.entry.rejection is None
    assert second.entry.effects == ()
    assert second.entry.patch == ()
    assert second.entry.receipt_key == first.entry.receipt_key
    assert second.state == first.state
    assert fold(graph, (*running.log, first.entry, second.entry)) == first.state


def test_cancel_of_a_completed_run_is_terminal() -> None:
    graph = _step_graph()
    done = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="shipped"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
    )
    assert done.state.status == "completed"
    cancelled = transition(graph, done.state, CancelRun(), NOW)
    assert cancelled.entry.rejection is not None
    assert cancelled.entry.rejection.code == "run_terminal"
    assert cancelled.state == done.state
    assert cancelled.entry.effects == ()


def test_cancel_emits_one_effect_per_live_slot_and_open_gate() -> None:
    graph = _fan_graph()
    running = drive(graph, [RUN])
    assert running.state.timers
    live = [slot.id for slot in running.state.slots if slot.status != "closed"]
    open_visits = [visit.token for visit in running.state.gates if visit.status == "open"]
    assert live == ["work||:0", "work||:1"]
    assert len(open_visits) == 1
    cancelled = transition(graph, running.state, CancelRun(), NOW)
    assert cancelled.entry.rejection is None
    assert cancelled.state.status == "cancelled"
    assert cancelled.state.timers == ()
    kinds = [effect.kind for effect in cancelled.entry.effects]
    assert kinds == ["cancel_sessions", "cancel_sessions", "withdraw_gate", "notify"]
    assert [effect.subject for effect in cancelled.entry.effects[:2]] == live
    assert cancelled.entry.effects[0].payload == {"interrupt": True, "closed_label": True}
    assert cancelled.entry.effects[1].payload == {"interrupt": True, "closed_label": True}
    withdraw = cancelled.entry.effects[2]
    assert withdraw.subject == open_visits[0]
    assert withdraw.payload == {"token": open_visits[0]}
    assert cancelled.entry.effects[3].payload == {"kind": "run_cancelled"}
    assert fold(graph, (*running.log, cancelled.entry)) == cancelled.state


def test_cancel_skips_a_closed_slot() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work", roster=["implementer", "reviewer"]), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )
    running = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="done"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
    )
    assert running.state.slots[0].status == "closed"
    assert running.state.slots[1].status != "closed"
    cancelled = transition(graph, running.state, CancelRun(), NOW)
    kinds = [(effect.kind, effect.subject) for effect in cancelled.entry.effects]
    assert kinds == [
        ("cancel_sessions", "work||:1"),
        ("notify", "run-1"),
    ]


def test_activation_cap_pauses_until_resume_raises_it() -> None:
    graph = _step_graph()
    from coral.engine.types import EngineConfig

    config = EngineConfig(max_activations=1)
    paused = drive(graph, [RUN], config=config)
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="budget", detail="activation_cap", subject="work"),
    )
    assert all(item.node_id != "work" for item in paused.state.activations)
    refused = transition(graph, paused.state, ResumeRun(cap=1), NOW, config)
    assert refused.entry.rejection is not None
    assert refused.entry.rejection.code == "resume_not_allowed"
    assert refused.state == paused.state
    resumed = transition(graph, paused.state, ResumeRun(cap=2), NOW, config)
    assert resumed.entry.rejection is None
    assert resumed.state.status == "running"
    assert resumed.state.max_activations == 2
    assert resumed.state.causes == ()
    assert any(item.node_id == "work" for item in resumed.state.activations)
    assert [effect.kind for effect in resumed.entry.effects] == ["create_session"]
    assert all(item.node_id != "end" for item in resumed.state.activations)
    assert fold(graph, (*paused.log, resumed.entry), config) == resumed.state


def _finish(slot_id: str) -> list[HandoffReceived | HandoffEvaluated]:
    return [
        HandoffReceived(slot_id=slot_id, body="done"),
        HandoffEvaluated(slot_id=slot_id, outcome="accepted"),
    ]


def test_resume_opens_a_refused_choice() -> None:
    graph = _decision_graph()
    config = EngineConfig(max_activations=2)
    choice = ChooseArrow(node_id="choose", label="approved", reason="ship it")
    paused = drive(graph, [RUN, choice], config=config)
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="budget", detail="activation_cap", subject="work"),
    )
    assert all(item.node_id != "work" for item in paused.state.activations)
    decided = next(item for item in paused.state.decisions if item.node_id == "choose")
    assert decided.status == "decided"
    assert decided.label == "approved"
    resumed = transition(graph, paused.state, ResumeRun(cap=3), NOW, config)
    assert resumed.state.status == "running"
    assert [item.node_id for item in resumed.state.activations if item.node_id == "work"] == [
        "work"
    ]
    assert [effect.kind for effect in resumed.entry.effects] == ["create_session"]
    again = transition(graph, resumed.state, choice, NOW, config)
    assert again.entry.rejection is None
    assert again.entry.effects == ()
    assert [item.node_id for item in again.state.activations if item.node_id == "work"] == ["work"]
    assert fold(graph, (*paused.log, resumed.entry, again.entry), config) == again.state


def test_resume_opens_a_refused_gate_target() -> None:
    graph = _gate_graph()
    config = EngineConfig(max_activations=2)
    opened = drive(graph, [RUN], config=config)
    token = next(visit.token for visit in opened.state.gates if visit.status == "open")
    answer = AnswerGate(token=token, label="approve", by="sam")
    paused = drive(graph, [RUN, answer], config=config)
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="budget", detail="activation_cap", subject="work"),
    )
    assert all(item.node_id != "work" for item in paused.state.activations)
    resumed = transition(graph, paused.state, ResumeRun(cap=3), NOW, config)
    assert resumed.state.status == "running"
    assert any(item.node_id == "work" for item in resumed.state.activations)
    visit = next(item for item in resumed.state.gates if item.token == token)
    assert visit.status == "resolved"
    assert all(effect.payload.get("decision.made") is not True for effect in resumed.entry.effects)
    assert fold(graph, (*paused.log, resumed.entry), config) == resumed.state


def test_resume_opens_a_refused_xor_target() -> None:
    graph = _graph(
        workflow_text(
            [start(), decision("pick"), step("left"), step("right"), step("after"), end()],
            [
                arrow("a1", "start", "pick"),
                arrow("a2", "pick", "left", label="approved"),
                arrow("a3", "pick", "right", label="rejected"),
                arrow("a4", "left", "after"),
                arrow("a5", "right", "after"),
                arrow("a6", "after", "end"),
            ],
        )
    )
    config = EngineConfig(max_activations=3)
    paused = drive(
        graph,
        [
            RUN,
            ChooseArrow(node_id="pick", label="approved", reason="take left"),
            *_finish("left||:0"),
        ],
        config=config,
    )
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="budget", detail="activation_cap", subject="after"),
    )
    assert all(item.node_id != "after" for item in paused.state.activations)
    resumed = transition(graph, paused.state, ResumeRun(cap=4), NOW, config)
    assert resumed.state.status == "running"
    opened = [item for item in resumed.state.activations if item.node_id == "after"]
    assert len(opened) == 1
    assert opened[0].status != "waiting_join"
    assert fold(graph, (*paused.log, resumed.entry), config) == resumed.state


def test_resume_restores_a_refused_and_join_as_waiting() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("plan"), step("build"), step("docs"), step("merge"), end()],
            [
                arrow("a1", "start", "plan"),
                arrow("a2", "plan", "build"),
                arrow("a3", "plan", "docs"),
                arrow("a4", "build", "merge"),
                arrow("a5", "docs", "merge"),
                arrow("a6", "merge", "end"),
            ],
        )
    )
    config = EngineConfig(max_activations=4)
    paused = drive(
        graph,
        [RUN, *_finish("plan||:0"), *_finish("docs||:0")],
        config=config,
    )
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="budget", detail="activation_cap", subject="merge"),
    )
    assert all(item.node_id != "merge" for item in paused.state.activations)
    build = next(item for item in paused.state.activations if item.node_id == "build")
    assert build.status != "closed"
    resumed = transition(graph, paused.state, ResumeRun(cap=5), NOW, config)
    assert resumed.state.status == "running"
    merge = [item for item in resumed.state.activations if item.node_id == "merge"]
    assert len(merge) == 1
    assert merge[0].status == "waiting_join"
    assert fold(graph, (*paused.log, resumed.entry), config) == resumed.state


def test_resume_of_a_dead_and_join_pauses_liveness() -> None:
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
    config = EngineConfig(max_activations=5)
    paused = drive(
        graph,
        [
            RUN,
            *_finish("plan||:0"),
            HandoffReceived(slot_id="build||:0", body="cannot"),
            HandoffEvaluated(slot_id="build||:0", outcome="blocked"),
            *_finish("bail||:0"),
            *_finish("docs||:0"),
        ],
        config=config,
    )
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="budget", detail="activation_cap", subject="merge"),
    )
    assert all(item.status == "closed" for item in paused.state.activations)
    resumed = transition(graph, paused.state, ResumeRun(cap=6), NOW, config)
    assert resumed.state.status == "paused"
    assert resumed.state.causes == (
        PauseCause(
            reason="liveness",
            detail="merge is waiting for build, which can no longer run.",
            subject="build",
        ),
    )
    merge = next(item for item in resumed.state.activations if item.node_id == "merge")
    assert merge.status == "waiting_join"
    assert fold(graph, (*paused.log, resumed.entry), config) == resumed.state


def test_three_tool_illegal_observations_pause() -> None:
    graph = _step_graph()
    observed = RejectionObserved(slot_id=SLOT, code="tool.illegal")
    driven = drive(graph, [RUN, observed, observed, observed])
    assert driven.state.status == "paused"
    assert driven.state.causes == (
        PauseCause(reason="rejected_calls", detail="tool.illegal", subject=SLOT),
    )
    assert driven.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=3),)
    resumed = transition(graph, driven.state, ResumeRun(), NOW)
    assert resumed.state.status == "running"
    assert resumed.state.causes == ()
    assert resumed.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=0),)
    assert fold(graph, (*driven.log, resumed.entry)) == resumed.state


def test_evidence_missing_does_not_increment_and_accept_resets() -> None:
    graph = _step_graph()
    counted = drive(
        graph,
        [
            RUN,
            RejectionObserved(slot_id=SLOT, code="tool.illegal"),
            RejectionObserved(slot_id=SLOT, code="evidence.missing"),
            RejectionObserved(slot_id=SLOT, code="evaluation_in_progress"),
        ],
    )
    assert counted.state.status == "running"
    assert counted.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=1),)
    invalid = transition(
        graph, counted.state, RejectionObserved(slot_id=SLOT, code="handoff.invalid"), NOW
    )
    assert invalid.state.status == "running"
    assert invalid.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=2),)

    opened = drive(
        graph,
        [
            RUN,
            RejectionObserved(slot_id=SLOT, code="tool.illegal"),
            RejectionObserved(slot_id=SLOT, code="tool.illegal"),
        ],
    )
    assert opened.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=2),)
    received = transition(graph, opened.state, HandoffReceived(slot_id=SLOT, body="ship"), NOW)
    accepted = transition(
        graph,
        received.state,
        HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        NOW,
    )
    assert accepted.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=0),)
    again = transition(
        graph, accepted.state, RejectionObserved(slot_id=SLOT, code="tool.illegal"), NOW
    )
    twice = transition(
        graph, again.state, RejectionObserved(slot_id=SLOT, code="tool.illegal"), NOW
    )
    assert twice.state.status == "running"
    assert twice.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=2),)
    logged = (*opened.log, received.entry, accepted.entry, again.entry, twice.entry)
    assert fold(graph, logged) == twice.state


def test_choose_arrow_illegal_does_not_start_a_streak() -> None:
    graph = _decision_graph()
    opened = drive(graph, [RUN])
    illegal = transition(
        graph,
        opened.state,
        ChooseArrow(node_id="choose", label="nope", reason="because"),
        NOW,
    )
    assert illegal.entry.rejection is not None
    assert illegal.entry.rejection.code == "tool.illegal"
    assert illegal.state.reject_streaks == ()
    assert illegal.state == opened.state


def test_only_start_run_has_version_hash() -> None:
    bare = (
        PauseRun,
        ResumeRun,
        CancelRun,
        RetryStep,
        TimerDue,
        RejectionObserved,
        SessionFailed,
        InfraBackoffExhausted,
        HandoffReceived,
        HandoffEvaluated,
        ChooseArrow,
        AnswerGate,
        PostCloseActivity,
        TurnEnded,
        RunnerLost,
        UsageLimited,
        WaitingWithoutElicitation,
    )
    assert "version_hash" in StartRun.model_fields
    for model in bare:
        assert "version_hash" not in model.model_fields


def test_unstarted_run_rejects_lifecycle_commands() -> None:
    graph = _step_graph()
    commands: tuple[Input, ...] = (
        ResumeRun(),
        RetryStep(node_id="work"),
        SessionFailed(slot_id=SLOT, failure_class="infra.transient", cause="down", fact_key="f"),
        InfraBackoffExhausted(slot_id=SLOT),
        RejectionObserved(slot_id=SLOT, code="tool.illegal"),
    )
    for command in commands:
        result = transition(graph, drive(graph, []).state, command, NOW)
        assert result.entry.rejection is not None
        assert result.entry.rejection.code == "rejected"
        assert result.entry.rejection.allowed_values == ("start_run",)
        assert result.state.status is None
