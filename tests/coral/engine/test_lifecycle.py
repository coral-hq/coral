"""Pause, resume, cancel, retry, activation cap, and rejected calls."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from coral.engine import fold, transition
from coral.engine.types import (
    AnswerGate,
    CancelRun,
    ChooseArrow,
    EffectCompleted,
    EffectFailed,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    InfraBackoffExhausted,
    Input,
    LogEntry,
    PauseCause,
    PauseReason,
    PauseRun,
    PostCloseActivity,
    Rejection,
    RejectionObserved,
    RejectStreak,
    ResumeRun,
    RetryStep,
    RunnerLost,
    RunState,
    SessionFailed,
    StartRun,
    TimerDue,
    TurnEnded,
    UsageLimited,
    WaitingWithoutElicitation,
)
from coral.model.ir import CompiledGraph
from tests.coral.engine.drive import NOW, Driven, assert_handoff_bodies_settled, drive
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


def test_retried_slot_starts_without_a_handoff_body() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work"), step("ship"), step("fix"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "ship", label="ok"),
                arrow("a3", "work", "fix", label="broken"),
                arrow("a4", "ship", "end"),
                arrow("a5", "fix", "end"),
            ],
        )
    )
    retried = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="partial", label="ok"),
            PauseRun(reason="failure_path", detail="blocked"),
            RetryStep(node_id="work"),
        ],
    )
    slot = retried.state.slots[0]
    assert (slot.status, slot.session_generation) == ("pending", 2)
    assert (slot.handoff, slot.handoff_label) == (None, None)

    # Nothing in the reducer briefs a retried session yet, so stand in for its brief ack.
    working = retried.state.model_copy(
        update={"slots": (slot.model_copy(update={"status": "working"}),)}
    )
    ended = transition(
        graph, working, TurnEnded(slot_id=SLOT, fact_key="turn:sess-2:2:resp-1"), NOW
    )
    assert ended.entry.rejection is None
    assert ended.state.slots[0].status == "evaluating"
    handoff = HandoffReceived(slot_id=SLOT, body="complete", label="broken", session_generation=2)
    direct = transition(graph, ended.state, handoff, NOW)
    assert direct.entry.rejection is None
    assert (direct.state.slots[0].handoff, direct.state.slots[0].handoff_label) == (
        "complete",
        "broken",
    )

    nudge = next(effect for effect in ended.entry.effects if effect.kind == "nudge")
    resumed = transition(graph, ended.state, EffectCompleted(effect_key=nudge.effect_key), NOW)
    assert resumed.entry.rejection is None
    assert resumed.state.slots[0].status == "working"
    after_nudge = transition(graph, resumed.state, handoff, NOW)
    assert after_nudge.entry.rejection is None
    assert after_nudge.state.slots[0].status == "evaluating"
    for state in (working, ended.state, direct.state, resumed.state, after_nudge.state):
        assert_handoff_bodies_settled(state)


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


_FORKED = workflow_text(
    [start(), step("work"), step("ship"), step("fix"), end()],
    [
        arrow("a1", "start", "work"),
        arrow("a2", "work", "ship", label="ok"),
        arrow("a3", "work", "fix", label="broken"),
        arrow("a4", "ship", "end"),
        arrow("a5", "fix", "end"),
    ],
)
_LOOPED = workflow_text(
    [start(), step("work"), end()],
    [
        arrow("a1", "start", "work"),
        arrow("a2", "work", "end", label="done"),
        arrow("a3", "work", "work", label="again", back=True, limit=2, at_limit="a4"),
        arrow("a4", "work", "end"),
    ],
)
_PLAIN = workflow_text(
    [start(), step("work"), step("ship"), end()],
    [arrow("a1", "start", "work"), arrow("a2", "work", "ship"), arrow("a3", "ship", "end")],
)


@pytest.mark.parametrize(
    ("text", "slot", "label", "opened"),
    [
        pytest.param(_FORKED, SLOT, "broken", "fix||", id="labelled"),
        pytest.param(_LOOPED, "work||a3:1:0", "again", "work||a3:2", id="labelled_back"),
        pytest.param(_PLAIN, SLOT, None, "ship||", id="unlabelled"),
    ],
)
def test_resume_routes_a_step_that_closed_while_paused(
    text: str, slot: str, label: str | None, opened: str
) -> None:
    graph = _graph(text)
    paused = _closed_while_paused(graph, slot, label, after=drive(graph, [RUN]))
    assert paused.state.slots[0].status == "closed"
    assert all(item.id != opened for item in paused.state.activations)

    resumed = drive(graph, [ResumeRun()], after=paused, auto_ack=False)
    assert resumed.log[-1].rejection is None
    assert resumed.state.status == "running"
    assert [(effect.kind, effect.subject) for effect in resumed.log[-1].effects] == [
        ("create_session", f"{opened}:0")
    ]
    started = [item.id for item in resumed.state.activations if item.status != "closed"]
    assert started == [opened]

    again = drive(
        graph,
        [PauseRun(reason="user", detail="again"), ResumeRun()],
        after=resumed,
        auto_ack=False,
    )
    assert again.log[-1].rejection is None
    assert again.log[-1].effects == ()
    assert again.state.activations == resumed.state.activations
    assert again.state.loop_counters == resumed.state.loop_counters


def test_resume_at_the_loop_limit_redirects_a_labelled_back_arrow_once() -> None:
    graph = _graph(_LOOPED)
    first_pass = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id="work||a3:1:0", body="done", label="again"),
            HandoffEvaluated(slot_id="work||a3:1:0", outcome="accepted"),
        ],
    )
    paused = _closed_while_paused(graph, "work||a3:2:0", "again", after=first_pass)
    assert paused.state.status == "paused"
    assert all(item.key != "loop:a3||" for item in paused.state.receipts)

    resumed = drive(graph, [ResumeRun()], after=paused, auto_ack=False)
    assert resumed.log[-1].rejection is None
    assert resumed.log[-1].effects == ()
    assert resumed.state.status == "completed"
    assert all(item.iteration_path != ("a3:3",) for item in resumed.state.activations)
    receipts = [(item.key, item.payload) for item in resumed.state.receipts]
    assert ("loop:a3||", {"code": "loop.limit_reached", "redirected": True}) in receipts
    routes = [key for key, _payload in receipts if key.startswith("route:")]
    assert routes == ["route:work||a3:1:1", "route:work||a3:2:1"]
    assert [item.pass_index for item in resumed.state.loop_counters] == [2]


def test_cancel_after_a_labelled_step_closed_while_paused_opens_nothing() -> None:
    graph = _graph(_FORKED)
    paused = _closed_while_paused(graph, SLOT, "broken", after=drive(graph, [RUN]))
    cancelled = drive(graph, [CancelRun(), ResumeRun()], after=paused, auto_ack=False)
    cancel, resume = cancelled.log[-2:]
    assert cancel.rejection is None
    assert [effect.kind for effect in cancel.effects] == ["notify"]
    assert resume.rejection is not None
    assert resume.rejection.code == "run_terminal"
    assert cancelled.state.status == "cancelled"
    assert {item.node_id for item in cancelled.state.activations} == {"start", "work"}
    assert all(not item.key.startswith("route:") for item in cancelled.state.receipts)


def test_activation_cap_on_a_label_route_opens_its_target_once_on_resume() -> None:
    graph = _graph(_FORKED)
    config = EngineConfig(max_activations=2)
    paused = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="done", label="broken"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        config=config,
    )
    assert paused.state.causes == (
        PauseCause(reason="budget", detail="activation_cap", subject="fix"),
    )
    keys = {item.key for item in paused.state.receipts}
    assert {"pending:fix||", "route:work||:1", "skipped:work||:a2"} <= keys

    resumed = drive(graph, [ResumeRun(cap=10)], config=config, after=paused, auto_ack=False)
    assert [(effect.kind, effect.subject) for effect in resumed.log[-1].effects] == [
        ("create_session", "fix||:0")
    ]
    again = drive(
        graph,
        [PauseRun(reason="user", detail="again"), ResumeRun()],
        config=config,
        after=resumed,
        auto_ack=False,
    )
    assert again.log[-1].rejection is None
    assert again.log[-1].effects == ()
    assert again.state.activations == resumed.state.activations
    assert all(item.node_id != "ship" for item in again.state.activations)


def test_nudge_from_before_a_retry_leaves_the_retried_slot_pending() -> None:
    graph = _step_graph()
    ended = drive(graph, [RUN, TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:resp-1")])
    nudge = next(effect for effect in ended.log[-1].effects if effect.kind == "nudge")
    retried = drive(
        graph,
        [PauseRun(reason="failure_path", detail="stuck"), RetryStep(node_id="work")],
        after=ended,
    )
    late = drive(graph, [EffectCompleted(effect_key=nudge.effect_key)], after=retried)
    assert late.log[-1].rejection is None
    assert late.log[-1].receipt_key == nudge.effect_key
    assert late.log[-1].effects == ()
    slot = late.state.slots[0]
    assert (slot.status, slot.session_generation, slot.handoff) == ("pending", 2, None)


@pytest.mark.parametrize("paused", [False, True], ids=["closes_running", "closes_paused"])
def test_retried_step_routes_again_when_its_new_generation_closes(paused: bool) -> None:
    graph = _graph(_FORKED)
    retried = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="done", label="ok"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
            PauseRun(reason="failure_path", detail="redo"),
            RetryStep(node_id="work"),
        ],
    )
    assert retried.state.slots[0].session_generation == 2
    state, entries = _apply(
        graph,
        _briefed_retry(retried.state),
        [
            HandoffReceived(slot_id=SLOT, body="again", label="broken", session_generation=2),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted", session_generation=2),
        ],
    )
    close = [effect for effect in state.effects if effect.kind == "close_slot"][-1]
    closed = EffectCompleted(effect_key=close.effect_key, payload={"pending_input": False})
    steps = [PauseRun(reason="user", detail="hold"), closed, ResumeRun()] if paused else [closed]
    state, more = _apply(graph, state, steps)
    assert all(entry.rejection is None for entry in (*entries, *more))
    routes = [(item.key, item.payload) for item in state.receipts if item.key.startswith("route:")]
    assert routes == [
        ("route:work||:1", {"label": "ok"}),
        ("route:work||:2", {"label": "broken"}),
    ]
    assert [item.id for item in state.activations if item.node_id == "fix"] == ["fix||"]

    again, last = _apply(graph, state, [PauseRun(reason="user", detail="again"), ResumeRun()])
    assert last[-1].effects == ()
    assert again.activations == state.activations


def test_nudge_from_an_older_generation_only_records_its_receipt() -> None:
    graph = _step_graph()
    ended = drive(graph, [RUN, TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:resp-1")])
    old = next(effect for effect in ended.log[-1].effects if effect.kind == "nudge")
    retried = drive(
        graph,
        [PauseRun(reason="failure_path", detail="stuck"), RetryStep(node_id="work")],
        after=ended,
    )
    waiting, entries = _apply(
        graph,
        _briefed_retry(retried.state),
        [TurnEnded(slot_id=SLOT, fact_key="turn:sess-2:2:resp-1")],
    )
    new = next(effect for effect in entries[-1].effects if effect.kind == "nudge")
    assert waiting.slots[0].status == "evaluating"

    stale, receipted = _apply(graph, waiting, [EffectCompleted(effect_key=old.effect_key)])
    assert receipted[-1].rejection is None
    assert receipted[-1].receipt_key == old.effect_key
    assert stale.slots == waiting.slots
    assert stale.seq == waiting.seq + 1

    current, _ = _apply(graph, stale, [EffectCompleted(effect_key=new.effect_key)])
    assert current.slots[0].status == "working"


_SIDE = workflow_text(
    [start(), step("side"), step("work"), step("ship"), step("fix"), step("merge"), end()],
    [
        arrow("a1", "start", "side"),
        arrow("a2", "start", "work"),
        arrow("a3", "work", "ship", label="ok"),
        arrow("a4", "work", "fix", label="broken"),
        arrow("a5", "ship", "merge"),
        arrow("a6", "fix", "merge"),
        arrow("a7", "side", "end"),
        arrow("a8", "merge", "end"),
    ],
)


@pytest.mark.parametrize(
    "pause",
    [
        PauseRun(reason="failure_path", detail="stuck"),
        UsageLimited(slot_id="side||:0", fact_key="turn:sess-9:1:resp-1"),
    ],
    ids=["retry_step", "plan_probe"],
)
def test_retry_and_plan_probe_also_route_a_step_that_closed_while_paused(pause: Input) -> None:
    graph = _graph(_SIDE)
    closing = drive(
        graph,
        [
            HandoffReceived(slot_id=SLOT, body="done", label="broken"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        after=drive(graph, [RUN]),
        auto_ack=False,
    )
    close = next(effect for effect in closing.state.effects if effect.kind == "close_slot")
    paused = drive(
        graph,
        [pause, EffectCompleted(effect_key=close.effect_key, payload={"pending_input": False})],
        after=closing,
        auto_ack=False,
    )
    assert paused.state.status == "paused"
    assert all(item.node_id != "fix" for item in paused.state.activations)

    unpause: Input = RetryStep(node_id="side")
    at = NOW
    if isinstance(pause, UsageLimited):
        probe = next(timer for timer in paused.state.timers if timer.kind == "plan_probe")
        unpause = TimerDue(timer_key=probe.key)
        at = probe.due_at
    resumed = drive(graph, [unpause], after=paused, auto_ack=False, now=at)
    assert resumed.log[-1].rejection is None
    assert resumed.state.status == "running"
    created = [
        (effect.kind, effect.subject)
        for effect in resumed.log[-1].effects
        if effect.kind == "create_session"
    ]
    assert created == [("create_session", "fix||:0")]
    assert all(item.node_id != "ship" for item in resumed.state.activations)
    assert any(item.key == "route:work||:1" for item in resumed.state.receipts)


def _briefed_retry(state: RunState) -> RunState:
    """Stand in for a retried session's brief ack, which the reducer does not model yet."""
    return state.model_copy(
        update={
            "slots": tuple(
                slot.model_copy(update={"status": "working"}) if slot.status == "pending" else slot
                for slot in state.slots
            )
        }
    )


def _apply(
    graph: CompiledGraph, state: RunState, commands: Sequence[Input]
) -> tuple[RunState, tuple[LogEntry, ...]]:
    """Apply ``commands`` without effect acks to a state that no log reaches."""
    entries: list[LogEntry] = []
    for command in commands:
        result = transition(graph, state, command, NOW)
        assert_handoff_bodies_settled(result.state)
        entries.append(result.entry)
        state = result.state
    return state, tuple(entries)


def _closed_while_paused(
    graph: CompiledGraph, slot: str, label: str | None, *, after: Driven
) -> Driven:
    """Accept ``slot``'s handoff, pause the run, then complete the slot's close."""
    closing = drive(
        graph,
        [
            HandoffReceived(slot_id=slot, body="done", label=label),
            HandoffEvaluated(slot_id=slot, outcome="accepted"),
        ],
        after=after,
        auto_ack=False,
    )
    close = next(
        effect
        for effect in closing.state.effects
        if effect.kind == "close_slot" and effect.subject == slot
    )
    return drive(
        graph,
        [
            PauseRun(reason="user", detail="hold"),
            EffectCompleted(effect_key=close.effect_key, payload={"pending_input": False}),
        ],
        after=closing,
        auto_ack=False,
    )


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


def test_the_rejected_call_limit_is_the_count_that_pauses() -> None:
    graph = _step_graph()
    observed = RejectionObserved(slot_id=SLOT, code="handoff.invalid")
    assert drive(graph, [RUN]).state.rejected_call_limit == 3
    config = EngineConfig(rejected_call_limit=2)
    below = drive(graph, [RUN, observed], config=config)
    assert below.state.rejected_call_limit == 2
    assert below.state.status == "running"
    # The limit the run started with counts, not the config a later input sees.
    at = transition(graph, below.state, observed, NOW)
    assert at.state.status == "paused"
    assert at.state.reject_streaks == (RejectStreak(slot_id=SLOT, count=2),)


@pytest.mark.parametrize("field", ["rejected_call_limit", "nudge_limit"])
def test_the_limits_must_be_at_least_one(field: str) -> None:
    with pytest.raises(ValidationError):
        EngineConfig.model_validate({field: 0})


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
        EffectFailed,
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
        EffectFailed(effect_key="run-1:1:create_session:work||:0", code="session.not_ready"),
    )
    for command in commands:
        result = transition(graph, drive(graph, []).state, command, NOW)
        assert result.entry.rejection is not None
        assert result.entry.rejection.code == "rejected"
        assert result.entry.rejection.allowed_values == ("start_run",)
        assert result.state.status is None


PAIR = "work||:1"
FACT_A = "turn:sess-1:1:msg:a"
FACT_B = "turn:sess-2:1:msg:b"


def _pair_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), step("work", roster=["implementer", "reviewer"]), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )


def _turn_end_and_nudge(graph: CompiledGraph, driven: Driven, fact_key: str) -> Driven:
    """End a turn without a handoff, then deliver the nudge it emitted."""
    ended = drive(graph, [TurnEnded(slot_id=SLOT, fact_key=fact_key)], after=driven)
    (nudge,) = ended.log[-1].effects
    return drive(graph, [EffectCompleted(effect_key=nudge.effect_key)], after=ended)


def test_a_second_identical_pause_changes_nothing() -> None:
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason="user", detail="hold")])
    again = transition(graph, paused.state, PauseRun(reason="user", detail="hold"), NOW)
    assert again.state == paused.state
    assert (again.entry.rejection, again.entry.effects, again.entry.patch) == (None, (), ())
    assert fold(graph, (*paused.log, again.entry)) == paused.state

    other = transition(graph, paused.state, PauseRun(reason="user", detail="later"), NOW)
    assert other.state.causes == (
        PauseCause(reason="user", detail="hold", subject=""),
        PauseCause(reason="user", detail="later", subject=""),
    )
    assert other.state.seq == paused.state.seq + 1


def test_resume_reprompts_failed_and_stopped_slots_once() -> None:
    graph = _pair_graph()
    paused = drive(
        graph,
        [
            RUN,
            TurnEnded(slot_id=PAIR, fact_key=FACT_B, origin="user"),
            SessionFailed(slot_id=SLOT, failure_class="auth", cause="401", fact_key=FACT_A),
        ],
    )
    assert paused.state.status == "paused"
    assert [slot.status for slot in paused.state.slots] == ["working", "evaluating"]
    assert paused.state.slots[0].failed_turn == FACT_A

    resumed = drive(graph, [ResumeRun()], after=paused)
    assert resumed.state.status == "running"
    assert [
        (effect.kind, effect.subject, effect.payload) for effect in resumed.log[-1].effects
    ] == [
        ("nudge", SLOT, {"fact_key": FACT_A, "reason": "resume"}),
        ("nudge", PAIR, {"fact_key": "", "reason": "resume"}),
    ]
    assert [slot.failed_turn for slot in resumed.state.slots] == [None, None]

    # Their nudges are still undelivered, so a second resume adds none.
    again = drive(graph, [PauseRun(reason="user", detail="hold"), ResumeRun()], after=resumed)
    assert again.log[-1].effects == ()
    delivered = drive(
        graph,
        [EffectCompleted(effect_key=effect.effect_key) for effect in resumed.log[-1].effects],
        after=again,
    )
    assert [slot.status for slot in delivered.state.slots] == ["working", "working"]
    third = drive(graph, [PauseRun(reason="user", detail="hold"), ResumeRun()], after=delivered)
    assert third.log[-1].effects == ()


def test_a_resume_that_leaves_the_run_paused_reprompts_nothing() -> None:
    graph = _pair_graph()
    paused = drive(
        graph,
        [
            RUN,
            SessionFailed(slot_id=SLOT, failure_class="auth", cause="401", fact_key=FACT_A),
            SessionFailed(
                slot_id=PAIR, failure_class="agent.failed", cause="agent.failed", fact_key=FACT_B
            ),
        ],
    )
    resumed = drive(graph, [ResumeRun()], after=paused)
    assert resumed.log[-1].rejection is None
    assert resumed.log[-1].effects == ()
    assert resumed.state.status == "paused"
    assert [cause.reason for cause in resumed.state.causes] == ["failure_path"]
    assert [slot.failed_turn for slot in resumed.state.slots] == [FACT_A, FACT_B]


def test_the_nudge_cap_pauses_rejected_calls_and_resume_resets_it() -> None:
    graph = _step_graph()
    nudged = drive(graph, [RUN])
    for index in range(3):
        nudged = _turn_end_and_nudge(graph, nudged, f"turn:sess-1:1:msg:{index}")
    assert nudged.state.slots[0].nudges == 3
    assert nudged.state.status == "running"

    capped = drive(graph, [TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:msg:3")], after=nudged)
    assert capped.log[-1].rejection is None
    assert capped.log[-1].effects == ()
    assert capped.state.status == "paused"
    assert capped.state.causes == (
        PauseCause(reason="rejected_calls", detail="nudge_limit", subject=SLOT),
    )
    assert capped.state.slots[0].status == "evaluating"

    resumed = drive(graph, [ResumeRun()], after=capped)
    assert resumed.state.status == "running"
    assert resumed.state.slots[0].nudges == 0
    assert [(effect.kind, effect.payload) for effect in resumed.log[-1].effects] == [
        ("nudge", {"fact_key": "", "reason": "resume"})
    ]


def test_a_handoff_resets_the_nudge_count_and_paused_turn_ends_do_not_count() -> None:
    graph = _step_graph()
    nudged = drive(graph, [RUN])
    for index in range(2):
        nudged = _turn_end_and_nudge(graph, nudged, f"turn:sess-1:1:msg:{index}")
    assert nudged.state.slots[0].nudges == 2

    missed = drive(
        graph,
        [
            HandoffReceived(slot_id=SLOT, body="partial"),
            HandoffEvaluated(slot_id=SLOT, outcome="evidence_missing", missing=("spec",)),
        ],
        after=nudged,
    )
    assert (missed.state.slots[0].status, missed.state.slots[0].nudges) == ("working", 0)

    paused = drive(graph, [PauseRun(reason="user", detail="hold")], after=missed)
    held = drive(graph, [TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:msg:9")], after=paused)
    assert [effect.kind for effect in held.log[-1].effects] == ["nudge"]
    assert held.state.slots[0].nudges == 0


@pytest.mark.parametrize(
    "failure_class",
    ["agent.failed", "infra.transient", "plan.usage_limit", "auth", "infra.runner_lost"],
)
@pytest.mark.parametrize("closed", [False, True], ids=["closing", "closed"])
def test_a_failed_turn_after_an_accepted_handoff_is_refused(
    failure_class: str, closed: bool
) -> None:
    graph = _graph(_PLAIN)
    accepted = drive(graph, _finish(SLOT), after=drive(graph, [RUN]), auto_ack=closed)
    assert accepted.state.slots[0].status == ("closed" if closed else "closing")
    assert accepted.state.status == "running"
    for command in (
        SessionFailed(slot_id=SLOT, failure_class=failure_class, cause="x", fact_key=FACT_A),
        UsageLimited(slot_id=SLOT, fact_key=FACT_A),
    ):
        refused = transition(graph, accepted.state, command, NOW)
        assert refused.entry.rejection == Rejection(code="slot.closed")
        assert refused.state == accepted.state
        assert refused.entry.effects == ()


def test_infra_stages_of_a_slot_that_handed_off_only_disarm() -> None:
    graph = _graph(_PLAIN)
    failed = drive(
        graph,
        [
            RUN,
            SessionFailed(
                slot_id=SLOT, failure_class="infra.transient", cause="529", fact_key=FACT_A
            ),
        ],
    )
    first, _second, third = failed.state.timers
    closing = drive(graph, _finish(SLOT), after=failed, auto_ack=False)
    assert closing.state.slots[0].status == "closing"
    fired = drive(
        graph, [TimerDue(timer_key=first.key)], after=closing, auto_ack=False, now=first.due_at
    )
    last = drive(
        graph, [TimerDue(timer_key=third.key)], after=fired, auto_ack=False, now=third.due_at
    )
    assert [entry.effects for entry in last.log[-2:]] == [(), ()]
    assert last.state.status == "running"
    assert last.state.causes == ()
    assert [timer.stage for timer in last.state.timers] == [2]


def test_a_pending_close_waits_for_every_cause_and_a_retry_finishes_it() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("side"), step("work"), step("ship"), end()],
            [
                arrow("a1", "start", "side"),
                arrow("a2", "start", "work"),
                arrow("a3", "work", "ship"),
                arrow("a4", "side", "end"),
                arrow("a5", "ship", "end"),
            ],
        )
    )
    closing = drive(graph, _finish(SLOT), after=drive(graph, [RUN]), auto_ack=False)
    close = next(effect for effect in closing.state.effects if effect.kind == "close_slot")
    paused = drive(
        graph,
        [
            SessionFailed(
                slot_id="side||:0",
                failure_class="agent.failed",
                cause="agent.failed",
                fact_key=FACT_B,
            ),
            EffectCompleted(effect_key=close.effect_key, payload={"pending_input": True}),
        ],
        after=closing,
        auto_ack=False,
    )
    assert [(cause.reason, cause.detail) for cause in paused.state.causes] == [
        ("failure_path", "agent.failed"),
        ("drift", "pending_input"),
    ]

    resumed = drive(graph, [ResumeRun()], after=paused, auto_ack=False)
    assert resumed.log[-1].effects == ()
    assert resumed.state.status == "paused"
    work = next(slot for slot in resumed.state.slots if slot.id == SLOT)
    assert (work.status, work.pending_input) == ("closing", True)
    assert all(item.node_id != "ship" for item in resumed.state.activations)

    retried = drive(graph, [RetryStep(node_id="side")], after=resumed, auto_ack=False)
    assert retried.state.status == "running"
    assert [(effect.kind, effect.subject) for effect in retried.log[-1].effects] == [
        ("retry_step", "side||:0"),
        ("create_session", "ship||:0"),
    ]
    work = next(slot for slot in retried.state.slots if slot.id == SLOT)
    assert (work.status, work.pending_input) == ("closed", False)
    owner = next(item for item in retried.state.activations if item.node_id == "work")
    assert (owner.status, owner.outcome) == ("closed", "completed")


_SIDE_WORK = workflow_text(
    [start(), step("side"), step("work"), step("ship"), end()],
    [
        arrow("a1", "start", "side"),
        arrow("a2", "start", "work"),
        arrow("a3", "work", "ship"),
        arrow("a4", "side", "end"),
        arrow("a5", "ship", "end"),
    ],
)


def test_re_fed_causes_of_one_reason_write_nothing_and_keep_their_order() -> None:
    graph = _graph(_SIDE_WORK)
    pending = drive(graph, [RUN], auto_ack=False)
    creates = {effect.subject: effect.effect_key for effect in pending.log[-1].effects}
    feeds: list[Input] = [
        EffectFailed(effect_key=creates[SLOT], code="session.not_ready", retryable=True),
        EffectFailed(effect_key=creates["side||:0"], code="session.host_offline", retryable=True),
        PauseRun(reason="infra", detail="orchestrator:c2"),
        PauseRun(reason="infra", detail="anchor:c1"),
    ]
    expected = (
        PauseCause(reason="infra", detail="anchor:c1", subject=""),
        PauseCause(reason="infra", detail="orchestrator:c2", subject=""),
        PauseCause(reason="infra", detail="session.host_offline", subject="side||:0"),
        PauseCause(reason="infra", detail="session.not_ready", subject=SLOT),
    )
    for order in (feeds, feeds[::-1]):
        fed = drive(graph, order, after=pending, auto_ack=False)
        assert all(entry.rejection is None and entry.patch for entry in fed.log[-4:])
        assert fed.state.causes == expected
        state = fed.state
        # The resync feeds the same failures again and again: nothing changes.
        for round_no in range(6):
            refeed = transition(graph, state, order[round_no % len(order)], NOW)
            assert refeed.state == state
            assert (refeed.entry.rejection, refeed.entry.effects, refeed.entry.patch) == (
                None,
                (),
                (),
            )


def test_a_retry_that_returns_the_run_to_running_reprompts_failed_slots() -> None:
    graph = _graph(_SIDE_WORK)
    paused = drive(
        graph,
        [
            RUN,
            SessionFailed(slot_id=SLOT, failure_class="auth", cause="401", fact_key=FACT_A),
            SessionFailed(
                slot_id="side||:0",
                failure_class="agent.failed",
                cause="agent.failed",
                fact_key=FACT_B,
            ),
            ResumeRun(),
        ],
    )
    assert paused.state.status == "paused"
    assert paused.log[-1].effects == ()

    retried = drive(graph, [RetryStep(node_id="side")], after=paused, auto_ack=False)
    assert retried.state.status == "running"
    assert [(effect.kind, effect.subject) for effect in retried.log[-1].effects] == [
        ("retry_step", "side||:0"),
        ("nudge", SLOT),
    ]
    assert retried.log[-1].effects[1].payload == {"fact_key": FACT_A, "reason": "resume"}
    work = next(slot for slot in retried.state.slots if slot.id == SLOT)
    assert work.failed_turn is None


def test_a_retry_clears_the_pending_input_of_the_slot_it_replaces() -> None:
    graph = _graph(_PLAIN)
    closing = drive(graph, _finish(SLOT), after=drive(graph, [RUN]), auto_ack=False)
    close = next(effect for effect in closing.state.effects if effect.kind == "close_slot")
    held = drive(
        graph,
        [
            PauseRun(reason="failure_path", detail="stuck"),
            EffectCompleted(effect_key=close.effect_key, payload={"pending_input": True}),
            RetryStep(node_id="work"),
        ],
        after=closing,
        auto_ack=False,
    )
    slot = held.state.slots[0]
    assert (slot.status, slot.session_generation, slot.pending_input) == ("pending", 2, False)
    resumed = drive(graph, [ResumeRun()], after=held, auto_ack=False)
    assert resumed.state.status == "running"
    assert resumed.state.slots[0].status == "pending"
    assert all(item.node_id != "ship" for item in resumed.state.activations)


@pytest.mark.parametrize("failure_class", ["infra.transient", "infra.runner_lost"])
def test_a_failure_receipted_before_the_handoff_answers_with_its_receipt(
    failure_class: str,
) -> None:
    graph = _graph(_PLAIN)
    failure = SessionFailed(slot_id=SLOT, failure_class=failure_class, cause="x", fact_key=FACT_A)
    failed = drive(graph, [RUN, failure])
    closing = drive(graph, _finish(SLOT), after=failed, auto_ack=False)
    refeed = transition(graph, closing.state, failure, NOW)
    assert (refeed.entry.rejection, refeed.entry.receipt_key) == (None, FACT_A)
    assert refeed.state == closing.state
