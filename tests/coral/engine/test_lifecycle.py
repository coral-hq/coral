"""Pause, resume, cancel, retry, restarts, wakes, holds, activation cap, and rejected calls."""

from __future__ import annotations

import itertools
import typing
from collections.abc import Sequence
from datetime import timedelta

import pytest
from pydantic import JsonValue, ValidationError

from coral.engine import fold, transition
from coral.engine.lifecycle import retryable_activations
from coral.engine.types import (
    PREVIOUS_RULES,
    RULES,
    AnswerGate,
    CancelRun,
    ChooseArrow,
    Effect,
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
    RunnerHeld,
    RunnerHoldEnded,
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

RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1", rules=RULES)
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
# What a restart row reports when it salvaged nothing.
NO_SALVAGE: dict[str, JsonValue] = {
    "salvage_ref": None,
    "salvage_commit": None,
    "head_verified": True,
}


def _restarting(slot_id: str) -> PauseCause:
    return PauseCause(reason="infra", detail="recovery.restarting", subject=slot_id)


def _host_offline(slot_id: str) -> PauseCause:
    return PauseCause(reason="infra", detail="infra.host_offline", subject=slot_id)


def _with_causes(state: RunState, *causes: PauseCause) -> RunState:
    """Pause ``state`` for ``causes``, as the rule under test reads them."""
    return state.model_copy(update={"status": "paused", "causes": causes})


def _blocked(slot_id: str, generation: int = 1) -> list[HandoffReceived | HandoffEvaluated]:
    return [
        HandoffReceived(slot_id=slot_id, body="cannot", session_generation=generation),
        HandoffEvaluated(slot_id=slot_id, outcome="blocked", session_generation=generation),
    ]


def _restarts(state: RunState) -> list[Effect]:
    """``retry_step`` effects no completion or failure has receipted yet, oldest first."""
    done = {item.key for item in state.receipts}
    return [
        effect
        for effect in state.effects
        if effect.kind == "retry_step" and effect.effect_key not in done
    ]


def _finish_restarts(
    graph: CompiledGraph,
    driven: Driven,
    payload: dict[str, JsonValue] | None = None,
    *,
    auto_ack: bool = True,
) -> Driven:
    """Complete every pending restart as the restart row does once it fenced and reset."""
    completions = [
        EffectCompleted(effect_key=effect.effect_key, payload=payload or NO_SALVAGE)
        for effect in _restarts(driven.state)
    ]
    assert completions
    return drive(graph, completions, after=driven, auto_ack=auto_ack)


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
    assert retry.entry.rejection.code == "retry_not_allowed"
    assert retry.state == paused.state
    assert retry.entry.effects == ()
    assert fold(graph, (*paused.log, retry.entry)) == paused.state


@pytest.mark.parametrize("reason", (*_RETRY_ONLY, "infra"))
def test_retry_clears_its_steps_cause_of_each_retry_reason_and_keeps_the_run_paused(
    reason: PauseReason,
) -> None:
    graph = _step_graph()
    paused = _with_causes(
        drive(graph, [RUN]).state, PauseCause(reason=reason, detail="hold", subject=SLOT)
    )
    assert retryable_activations(paused) == ("work||",)
    retried = transition(graph, paused, RetryStep(node_id="work"), NOW)
    assert retried.entry.rejection is None
    assert (retried.state.status, retried.state.causes) == ("paused", (_restarting(SLOT),))
    assert all(item.node_id != "end" for item in retried.state.activations)
    if reason != "infra":
        resume = transition(graph, paused, ResumeRun(), NOW)
        assert resume.entry.rejection is not None
        assert resume.entry.rejection.code == "resume_not_allowed"
        assert resume.state == paused


@pytest.mark.parametrize(
    "subject",
    ["", "ghost", "ghost||:0"],
    ids=["run_level", "unknown_node", "unknown_slot"],
)
def test_a_cause_no_step_owns_is_not_retryable(subject: str) -> None:
    graph = _step_graph()
    paused = _with_causes(
        drive(graph, [RUN]).state,
        PauseCause(reason="failure_path", detail="anchor:dispatch.failed", subject=subject),
    )
    assert retryable_activations(paused) == ()
    refused = transition(graph, paused, RetryStep(node_id="work"), NOW)
    assert refused.entry.rejection == Rejection(code="retry_not_allowed")
    assert refused.state == paused


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
    assert retry.entry.rejection.code == "retry_not_allowed"
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
    assert retry.entry.rejection.code == "retry_not_allowed"
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
            *_blocked(SLOT),
            RetryStep(node_id="work"),
        ],
    )
    assert driven.state.status == "paused"
    assert driven.state.causes == (_restarting(SLOT),)
    slot = driven.state.slots[0]
    assert (slot.session_generation, slot.status, slot.wakes) == (2, "pending", 0)
    assert driven.state.attempts[0].used == 0
    work = next(item for item in driven.state.activations if item.node_id == "work")
    assert work.status == "starting"
    assert work.outcome is None
    assert all(item.node_id != "end" for item in driven.state.activations)
    effect = driven.log[-1].effects[0]
    assert [item.kind for item in driven.log[-1].effects] == ["retry_step"]
    assert effect.payload == {
        "generation": 2,
        "phases": ["fence_stop", "salvage_reset", "create_unbriefed", "brief"],
        "expected_head": None,
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
            HandoffEvaluated(slot_id=SLOT, outcome="blocked"),
            RetryStep(node_id="work"),
        ],
    )
    slot = retried.state.slots[0]
    assert (slot.status, slot.session_generation) == ("pending", 2)
    assert (slot.handoff, slot.handoff_label) == (None, None)

    working = _finish_restarts(graph, retried).state
    assert (working.slots[0].status, working.slots[0].handoff) == ("working", None)
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
        graph,
        failed.state,
        SessionFailed(
            slot_id=SLOT,
            failure_class="agent.failed",
            cause="agent.failed",
            fact_key="turn:sess-1:1:resp-2",
        ),
        NOW,
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
        [InfraBackoffExhausted(slot_id=SLOT), RetryStep(node_id="work")],
        after=ended,
    )
    late = drive(graph, [EffectCompleted(effect_key=nudge.effect_key)], after=retried)
    assert late.log[-1].rejection is None
    assert late.log[-1].receipt_key == nudge.effect_key
    assert late.log[-1].effects == ()
    slot = late.state.slots[0]
    assert (slot.status, slot.session_generation, slot.handoff) == ("pending", 2, None)


@pytest.mark.parametrize("paused", [False, True], ids=["closes_running", "closes_paused"])
def test_a_retried_step_routes_when_its_new_generation_closes(paused: bool) -> None:
    graph = _graph(_FORKED)
    retried = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="cannot", label="ok"),
            HandoffEvaluated(slot_id=SLOT, outcome="blocked"),
            RetryStep(node_id="work"),
        ],
    )
    assert retried.state.slots[0].session_generation == 2
    state, entries = _apply(
        graph,
        _finish_restarts(graph, retried).state,
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
    assert routes == [("route:work||:2", {"label": "broken"})]
    assert [item.id for item in state.activations if item.node_id == "fix"] == ["fix||"]
    assert all(item.node_id != "ship" for item in state.activations)

    again, last = _apply(graph, state, [PauseRun(reason="user", detail="again"), ResumeRun()])
    assert last[-1].effects == ()
    assert again.activations == state.activations


def test_nudge_from_an_older_generation_only_records_its_receipt() -> None:
    graph = _step_graph()
    ended = drive(graph, [RUN, TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:resp-1")])
    old = next(effect for effect in ended.log[-1].effects if effect.kind == "nudge")
    retried = drive(
        graph,
        [InfraBackoffExhausted(slot_id=SLOT), RetryStep(node_id="work")],
        after=ended,
    )
    waiting, entries = _apply(
        graph,
        _finish_restarts(graph, retried).state,
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
        InfraBackoffExhausted(slot_id="side||:0"),
        UsageLimited(slot_id="side||:0", fact_key="turn:sess-9:1:resp-1"),
    ],
    ids=["retry_step", "plan_probe"],
)
def test_a_finished_restart_and_a_plan_probe_also_route_a_step_that_closed_while_paused(
    pause: Input,
) -> None:
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

    expected = [("create_session", "fix||:0")]
    if isinstance(pause, UsageLimited):
        probe = next(timer for timer in paused.state.timers if timer.kind == "plan_probe")
        resumed = drive(
            graph, [TimerDue(timer_key=probe.key)], after=paused, auto_ack=False, now=probe.due_at
        )
    else:
        retried = drive(graph, [RetryStep(node_id="side")], after=paused, auto_ack=False)
        # The restart runs while the run stays paused, so nothing is routed yet.
        assert retried.state.status == "paused"
        assert all(item.node_id != "fix" for item in retried.state.activations)
        resumed = _finish_restarts(graph, retried, auto_ack=False)
        expected = [("create_session", "side||:0"), *expected]
    assert resumed.log[-1].rejection is None
    assert resumed.state.status == "running"
    created = [
        (effect.kind, effect.subject)
        for effect in resumed.log[-1].effects
        if effect.kind == "create_session"
    ]
    assert created == expected
    assert all(item.node_id != "ship" for item in resumed.state.activations)
    assert any(item.key == "route:work||:1" for item in resumed.state.receipts)


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
        RunnerHeld,
        RunnerHoldEnded,
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
        RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1),
        RunnerHoldEnded(slot_id=SLOT, generation=1),
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
            # A permanent failure only a retry clears.
            PauseRun(reason="failure_path", detail="dispatch.policy_denied"),
        ],
    )
    resumed = drive(graph, [ResumeRun()], after=paused)
    assert resumed.log[-1].rejection is None
    assert resumed.log[-1].effects == ()
    assert resumed.state.status == "paused"
    assert [cause.reason for cause in resumed.state.causes] == ["failure_path"]
    assert [slot.failed_turn for slot in resumed.state.slots] == [FACT_A, None]


def test_resume_never_clears_a_steps_failed_turn_and_a_retry_restarts_the_step() -> None:
    graph = _pair_graph()
    paused = drive(
        graph,
        [
            RUN,
            SessionFailed(
                slot_id=PAIR, failure_class="agent.failed", cause="agent.failed", fact_key=FACT_B
            ),
        ],
    )
    assert paused.state.causes == (
        PauseCause(reason="failure_path", detail="agent.failed", subject=PAIR),
    )

    refused = transition(graph, paused.state, ResumeRun(), NOW)
    assert refused.entry.rejection == Rejection(code="resume_not_allowed")
    assert refused.state == paused.state
    assert retryable_activations(paused.state) == ("work||",)

    retried = drive(graph, [RetryStep(node_id="work")], after=paused)
    # Every slot of the step gets a new generation and is held until its restart finishes.
    assert retried.state.causes == (_restarting(SLOT), _restarting(PAIR))
    restarted = _finish_restarts(graph, retried)
    assert (restarted.state.status, restarted.state.causes) == ("running", ())
    assert [(slot.status, slot.session_generation) for slot in restarted.state.slots] == [
        ("working", 2),
        ("working", 2),
    ]
    assert [slot.failed_turn for slot in restarted.state.slots] == [None, None]
    assert fold(graph, restarted.log) == restarted.state


@pytest.mark.parametrize(
    "other",
    [
        PauseRun(reason="failure_path", detail="agent.failed"),
        PauseRun(reason="failure_path", detail="transition_too_large"),
    ],
    ids=["run_level_same_detail", "unbuildable_commit"],
)
def test_resume_clears_no_failure_path_cause(other: PauseRun) -> None:
    graph = _pair_graph()
    paused = drive(
        graph,
        [
            RUN,
            SessionFailed(
                slot_id=PAIR, failure_class="agent.failed", cause="agent.failed", fact_key=FACT_B
            ),
            other,
        ],
    )

    resumed = transition(graph, paused.state, ResumeRun(), NOW)

    assert resumed.entry.rejection == Rejection(code="resume_not_allowed")
    assert resumed.state == paused.state
    assert [(cause.detail, cause.subject) for cause in paused.state.causes] == [
        (other.detail, ""),
        ("agent.failed", PAIR),
    ]


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
            # A failed turn only a retry clears.
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
    assert retried.state.status == "paused"
    assert [(effect.kind, effect.subject) for effect in retried.log[-1].effects] == [
        ("retry_step", "side||:0"),
    ]
    finished = _finish_restarts(graph, retried, auto_ack=False)
    assert finished.state.status == "running"
    assert [(effect.kind, effect.subject) for effect in finished.log[-1].effects] == [
        ("create_session", "side||:0"),
        ("create_session", "ship||:0"),
    ]
    work = next(slot for slot in finished.state.slots if slot.id == SLOT)
    assert (work.status, work.pending_input) == ("closed", False)
    owner = next(item for item in finished.state.activations if item.node_id == "work")
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


def test_a_finished_restart_that_returns_the_run_to_running_reprompts_failed_slots() -> None:
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
    assert retried.state.status == "paused"
    assert [(effect.kind, effect.subject) for effect in retried.log[-1].effects] == [
        ("retry_step", "side||:0"),
    ]
    finished = _finish_restarts(graph, retried, auto_ack=False)
    assert finished.state.status == "running"
    assert [(effect.kind, effect.subject) for effect in finished.log[-1].effects] == [
        ("create_session", "side||:0"),
        ("nudge", SLOT),
    ]
    assert finished.log[-1].effects[1].payload == {"fact_key": FACT_A, "reason": "resume"}
    work = next(slot for slot in finished.state.slots if slot.id == SLOT)
    assert work.failed_turn is None


_PAIR_PLAIN = workflow_text(
    [start(), step("work", roster=["implementer", "reviewer"]), step("ship"), end()],
    [arrow("a1", "start", "work"), arrow("a2", "work", "ship"), arrow("a3", "ship", "end")],
)


def _pending_close_beside_a_blocked_slot(graph: CompiledGraph) -> Driven:
    """Slot 0's close reports pending input while slot 1 of the same step is blocked."""
    closing = drive(graph, _finish(SLOT), after=drive(graph, [RUN]), auto_ack=False)
    close = next(effect for effect in closing.state.effects if effect.kind == "close_slot")
    held = drive(
        graph,
        [
            *_blocked(PAIR),
            EffectCompleted(effect_key=close.effect_key, payload={"pending_input": True}),
        ],
        after=closing,
        auto_ack=False,
    )
    assert [(cause.reason, cause.detail, cause.subject) for cause in held.state.causes] == [
        ("failure_path", "blocked", PAIR),
        ("drift", "pending_input", SLOT),
    ]
    return held


def test_a_retry_clears_the_pending_input_of_the_slot_it_replaces() -> None:
    graph = _graph(_PAIR_PLAIN)
    held = _pending_close_beside_a_blocked_slot(graph)
    retried = drive(graph, [RetryStep(node_id="work")], after=held, auto_ack=False)
    slot = retried.state.slots[0]
    assert (slot.status, slot.session_generation, slot.pending_input) == ("pending", 2, False)
    finished = _finish_restarts(graph, retried, auto_ack=False)
    assert finished.state.status == "running"
    assert [slot.status for slot in finished.state.slots] == ["pending", "pending"]
    assert all(item.node_id != "ship" for item in finished.state.activations)


def test_a_retry_drops_the_pending_input_pause_of_the_slot_it_replaces() -> None:
    graph = _graph(_PAIR_PLAIN)
    held = _pending_close_beside_a_blocked_slot(graph)
    retried = drive(graph, [RetryStep(node_id="work")], after=held, auto_ack=False)
    # The retried slot's pending input is gone, so its drift cause goes with it.
    assert retried.state.causes == (_restarting(SLOT), _restarting(PAIR))
    finished = _finish_restarts(graph, retried, auto_ack=False)
    assert (finished.state.status, finished.state.causes) == ("running", ())


def test_a_retry_keeps_the_pending_input_pause_of_another_slot() -> None:
    graph = _graph(_PAIR_PLAIN)
    held = _pending_close_beside_a_blocked_slot(graph)
    other = PauseCause(reason="drift", detail="pending_input", subject="elsewhere||:0")
    with_other = held.state.model_copy(update={"causes": (*held.state.causes, other)})
    retried = transition(graph, with_other, RetryStep(node_id="work"), NOW)
    assert retried.state.causes == (_restarting(SLOT), _restarting(PAIR), other)
    completions = [
        EffectCompleted(effect_key=effect.effect_key, payload=NO_SALVAGE)
        for effect in _restarts(retried.state)
    ]
    finished, _entries = _apply(graph, retried.state, completions)
    assert (finished.status, finished.causes) == ("paused", (other,))


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


_DEAD_JOIN = workflow_text(
    [start(), step("plan"), step("build"), step("docs"), step("merge"), step("bail"), end()],
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
_REVIEW_LOOP = workflow_text(
    [start(), step("implement"), step("review", roster=["reviewer"]), end()],
    [
        arrow("a1", "start", "implement"),
        arrow("a2", "implement", "review"),
        arrow("a3", "review", "end", label="approved"),
        arrow(
            "a4",
            "review",
            "implement",
            label="changes_requested",
            back=True,
            limit=2,
            at_limit="a5",
        ),
        arrow("a5", "review", "end"),
    ],
)
# Inside a loop even a first pass's activation names its iteration: ``implement||a4:1``.
IMPLEMENT_1 = "implement||a4:1:0"
REVIEW_1 = "review||a4:1:0"
IMPLEMENT_2 = "implement||a4:2:0"
SIDE = "side||:0"
LATER = NOW + timedelta(hours=1)
# Every reducer input kind.
INPUT_KINDS = frozenset(
    typing.get_args(member.model_fields["kind"].annotation)[0]
    for member in typing.get_args(typing.get_args(Input)[0])
)


def test_retry_refuses_a_completed_step_a_gate_and_a_decision() -> None:
    plain, gates, choices = _graph(_PLAIN), _gate_graph(), _decision_graph()
    done = drive(plain, [RUN, *_finish(SLOT)]).state
    owner = next(item for item in done.activations if item.id == "work||")
    assert (owner.status, owner.outcome) == ("closed", "completed")
    cases = [
        (plain, done, "work", (SLOT, "work||", "work")),
        (gates, drive(gates, [RUN]).state, "hold", ("hold||", "hold")),
        (choices, drive(choices, [RUN]).state, "choose", ("choose||", "choose")),
    ]
    for graph, state, node_id, subjects in cases:
        causes = [
            PauseCause(reason=reason, detail="hold", subject=subject)
            for reason, subject in itertools.product(
                ("infra", "failure_path", "liveness"), subjects
            )
        ]
        paused = _with_causes(state, *causes)
        assert retryable_activations(paused) == ()
        refused = transition(graph, paused, RetryStep(node_id=node_id), NOW)
        assert refused.entry.rejection == Rejection(code="retry_not_allowed")
        assert refused.state == paused


def test_retrying_one_of_two_failed_steps_clears_only_its_cause() -> None:
    graph = _graph(_SIDE_WORK)
    side_failed = PauseCause(reason="failure_path", detail="agent.failed", subject=SIDE)
    paused = drive(
        graph,
        [
            RUN,
            *_blocked(SLOT),
            SessionFailed(
                slot_id=SIDE, failure_class="agent.failed", cause="agent.failed", fact_key=FACT_B
            ),
        ],
    )
    assert paused.state.causes == (
        side_failed,
        PauseCause(reason="failure_path", detail="blocked", subject=SLOT),
    )
    assert retryable_activations(paused.state) == ("side||", "work||")

    retried = drive(graph, [RetryStep(node_id="work")], after=paused, auto_ack=False)
    assert retried.state.causes == (_restarting(SLOT), side_failed)
    assert retryable_activations(retried.state) == ()
    side = next(slot for slot in retried.state.slots if slot.id == SIDE)
    assert (side.session_generation, side.failed_turn) == (1, FACT_B)

    finished = _finish_restarts(graph, retried, auto_ack=False)
    # The other step's cause keeps the run paused, and its slot is not re-prompted.
    assert (finished.state.status, finished.state.causes) == ("paused", (side_failed,))
    assert [(effect.kind, effect.subject) for effect in finished.log[-1].effects] == [
        ("create_session", SLOT)
    ]
    assert retryable_activations(finished.state) == ("side||",)


def test_a_closed_failed_step_named_by_a_liveness_cause_is_retryable() -> None:
    graph = _graph(_DEAD_JOIN)
    dead = drive(
        graph,
        [
            RUN,
            *_finish("plan||:0"),
            *_blocked("build||:0"),
            *_finish("bail||:0"),
            *_finish("docs||:0"),
        ],
    )
    build = next(item for item in dead.state.activations if item.id == "build||")
    assert (build.status, build.outcome) == ("closed", "failed")
    assert [(cause.reason, cause.subject) for cause in dead.state.causes] == [
        ("liveness", "build")
    ]
    assert retryable_activations(dead.state) == ("build||",)

    retried = drive(graph, [RetryStep(node_id="build")], after=dead)
    build = next(item for item in retried.state.activations if item.id == "build||")
    assert (build.status, build.outcome) == ("starting", None)
    assert retried.state.causes == (_restarting("build||:0"),)

    rebuilt = drive(
        graph,
        [
            HandoffReceived(slot_id="build||:0", body="done", session_generation=2),
            HandoffEvaluated(slot_id="build||:0", outcome="accepted", session_generation=2),
        ],
        after=_finish_restarts(graph, retried),
    )
    assert rebuilt.state.status == "running"
    assert any(slot.id == "merge||:0" for slot in rebuilt.state.slots)


def _close_with_commit(
    graph: CompiledGraph,
    driven: Driven,
    slot_id: str,
    commit: str | None,
    *,
    label: str | None = None,
) -> Driven:
    """Accept ``slot_id``'s handoff and complete its close with the commit the close made."""
    closing = drive(
        graph,
        [
            HandoffReceived(slot_id=slot_id, body="done", label=label),
            HandoffEvaluated(slot_id=slot_id, outcome="accepted"),
        ],
        after=driven,
        auto_ack=False,
    )
    close = next(
        effect
        for effect in reversed(closing.state.effects)
        if effect.kind == "close_slot" and effect.subject == slot_id
    )
    payload: dict[str, JsonValue] = {"pending_input": False, "commit": commit}
    return drive(
        graph, [EffectCompleted(effect_key=close.effect_key, payload=payload)], after=closing
    )


def test_a_retry_expects_the_newest_written_commit_as_its_head() -> None:
    graph = _graph(_REVIEW_LOOP)
    implemented = _close_with_commit(graph, drive(graph, [RUN]), IMPLEMENT_1, "c0ffee1")
    # A reader's close carries no commit, so the second pass still expects the writer's.
    reviewed = _close_with_commit(graph, implemented, REVIEW_1, None, label="changes_requested")
    blocked = drive(graph, _blocked(IMPLEMENT_2), after=reviewed)
    assert retryable_activations(blocked.state) == ("implement||a4:2",)

    retried = drive(
        graph, [RetryStep(node_id="implement", iteration_path=("a4:2",))], after=blocked
    )

    (effect,) = retried.log[-1].effects
    assert (effect.kind, effect.subject) == ("retry_step", IMPLEMENT_2)
    assert effect.payload["expected_head"] == "c0ffee1"


def test_a_retry_after_a_finished_restart_expects_the_head_that_restart_kept() -> None:
    # The restart kept a commit no close receipt names (its close never reported it).
    graph = _graph(_PLAIN)
    retried = drive(graph, [RUN, *_blocked(SLOT), RetryStep(node_id="work")])
    (restart,) = [effect for effect in retried.log[-1].effects if effect.kind == "retry_step"]
    kept = {"salvage_ref": None, "salvage_commit": None, "head_verified": True, "head": "c1"}
    finished = drive(
        graph, [EffectCompleted(effect_key=restart.effect_key, payload=kept)], after=retried
    )
    again = drive(graph, [*_blocked(SLOT, 2), RetryStep(node_id="work")], after=finished)

    (effect,) = [effect for effect in again.log[-1].effects if effect.kind == "retry_step"]
    assert (effect.payload["generation"], effect.payload["expected_head"]) == (3, "c1")


def test_a_retry_after_closes_without_a_written_commit_expects_no_head() -> None:
    graph = _graph(_PLAIN)
    closed = _close_with_commit(graph, drive(graph, [RUN]), SLOT, None)
    retried = drive(graph, [*_blocked("ship||:0"), RetryStep(node_id="ship")], after=closed)
    (effect,) = retried.log[-1].effects
    assert effect.payload["expected_head"] is None


def test_a_retry_while_a_restart_or_a_host_hold_stands_is_refused() -> None:
    graph = _graph(_SIDE_WORK)
    retried = drive(graph, [RUN, *_blocked(SLOT), RetryStep(node_id="work")])
    side_failed = drive(
        graph,
        [SessionFailed(slot_id=SIDE, failure_class="auth", cause="401", fact_key=FACT_B)],
        after=retried,
    )
    for state in (retried.state, side_failed.state):
        assert retryable_activations(state) == ()
        for node_id in ("work", "side"):
            refused = transition(graph, state, RetryStep(node_id=node_id), NOW)
            assert refused.entry.rejection == Rejection(code="restart_in_progress")
            assert refused.state == state

    held = drive(
        graph,
        [
            RUN,
            SessionFailed(
                slot_id=SIDE, failure_class="agent.failed", cause="agent.failed", fact_key=FACT_B
            ),
            RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1),
        ],
    )
    assert held.state.causes[0] == _host_offline(SLOT)
    assert retryable_activations(held.state) == ()
    refused = transition(graph, held.state, RetryStep(node_id="side"), NOW)
    assert refused.entry.rejection == Rejection(code="host_offline_hold")
    assert refused.state == held.state


@pytest.mark.parametrize("hold", ["host_offline", "restarting"])
def test_a_gate_beside_a_two_slot_step_waits_until_both_slots_stop_holding(hold: str) -> None:
    graph = _fan_graph()
    running = drive(graph, [RUN])
    (visit,) = running.state.gates
    answer = AnswerGate(token=visit.token, label="approve", by="sam")
    if hold == "host_offline":
        held = drive(
            graph,
            [
                RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1),
                RunnerHeld(slot_id=PAIR, session_id="sess-2", generation=1),
            ],
            after=running,
        )
        expected = (_host_offline(SLOT), _host_offline(PAIR))
        ends: list[Input] = [
            RunnerHoldEnded(slot_id=SLOT, generation=1),
            RunnerHoldEnded(slot_id=PAIR, generation=1),
        ]
    else:
        held = drive(graph, [*_blocked(PAIR), RetryStep(node_id="work")], after=running)
        expected = (_restarting(SLOT), _restarting(PAIR))
        ends = [
            EffectCompleted(effect_key=effect.effect_key, payload=NO_SALVAGE)
            for effect in _restarts(held.state)
        ]
    assert held.state.causes == expected

    # One slot that stops holding leaves the run paused for the other, and the gate waits.
    first = drive(graph, ends[:1], after=held, auto_ack=False)
    assert (first.state.status, first.state.causes) == ("paused", expected[1:])
    finished = [("create_session", SLOT)] if hold == "restarting" else []
    assert [(effect.kind, effect.subject) for effect in first.log[-1].effects] == finished
    for state in (held.state, first.state):
        refused = transition(graph, state, answer, NOW)
        assert refused.entry.rejection == Rejection(code="run_paused")
        assert transition(graph, state, ResumeRun(), NOW).entry.rejection == Rejection(
            code="resume_not_allowed"
        )

    done = drive(graph, [*ends[1:], answer], after=first)
    assert done.log[-1].rejection is None
    assert (done.state.status, done.state.gates[0].status) == ("running", "resolved")


def _every_kind(state: RunState) -> list[Input]:
    """Inputs of every reducer kind against a ``_SIDE_WORK`` run whose ``work`` restarts."""
    (restart,) = _restarts(state)
    brief = next(
        effect
        for effect in state.effects
        if effect.kind == "send_input" and effect.subject == SIDE
    )
    commands: list[Input] = [
        RUN,
        PauseRun(reason="user", detail="hold"),
        ResumeRun(),
        ResumeRun(cap=100_000),
        CancelRun(),
        RetryStep(node_id="work"),
        RetryStep(node_id="side"),
        EffectCompleted(effect_key=restart.effect_key, payload=NO_SALVAGE),
        EffectFailed(effect_key=restart.effect_key, code="dispatch.stop_unconfirmed"),
        EffectCompleted(effect_key=brief.effect_key),
        EffectFailed(effect_key=brief.effect_key, code="session.not_ready", retryable=True),
        HandoffReceived(slot_id=SIDE, body="done"),
        HandoffEvaluated(slot_id=SIDE, outcome="accepted"),
        HandoffReceived(slot_id=SLOT, body="late"),
        HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ChooseArrow(node_id="side", label="ok", reason="because"),
        AnswerGate(token="no-such-visit", label="approve", by="sam"),
        TurnEnded(slot_id=SIDE, fact_key="turn:sess-2:1:resp-9"),
        TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:resp-9"),
        RunnerLost(slot_id=SIDE, session_id="sess-2", generation=1, runner_id="r9"),
        RunnerLost(slot_id=SLOT, session_id="sess-1", generation=1, runner_id="r1"),
        UsageLimited(slot_id=SIDE, fact_key="turn:sess-2:1:resp-8"),
        WaitingWithoutElicitation(slot_id=SLOT, fact_key="turn:sess-1:1:resp-7"),
        SessionFailed(
            slot_id=SLOT,
            failure_class="agent.failed",
            cause="agent.failed",
            fact_key="turn:sess-1:1:resp-6",
        ),
        SessionFailed(slot_id=SIDE, failure_class="auth", cause="401", fact_key="turn:sess-2:1:r"),
        SessionFailed(
            slot_id=SIDE,
            failure_class="infra.runner_lost",
            cause="runner_disconnected",
            fact_key="turn:sess-2:1:resp-5",
            runner_id="r8",
        ),
        PostCloseActivity(slot_id=SLOT),
        RejectionObserved(slot_id=SIDE, code="tool.illegal"),
        InfraBackoffExhausted(slot_id=SLOT),
        InfraBackoffExhausted(slot_id=SIDE),
        RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=2),
        RunnerHeld(slot_id=SIDE, session_id="sess-2", generation=1),
        RunnerHoldEnded(slot_id=SLOT, generation=2),
        RunnerHoldEnded(slot_id=SIDE, generation=1),
        *(TimerDue(timer_key=timer.key) for timer in state.timers),
        TimerDue(timer_key="infra_backoff:work||:0:1"),
    ]
    assert {command.kind for command in commands} == INPUT_KINDS
    return commands


def _ends_the_restart(command: Input, restart: Effect) -> bool:
    if isinstance(command, CancelRun):
        return True
    return isinstance(command, (EffectCompleted, EffectFailed)) and (
        command.effect_key == restart.effect_key
    )


def test_only_finishing_or_failing_the_restart_or_a_terminal_input_ends_the_restarting_pause() -> (
    None
):
    graph = _graph(_SIDE_WORK)
    restarting = drive(
        graph,
        [
            RUN,
            SessionFailed(
                slot_id=SIDE, failure_class="infra.transient", cause="529", fact_key=FACT_B
            ),
            *_blocked(SLOT),
            RetryStep(node_id="work"),
        ],
    )
    held = drive(
        graph,
        [RunnerHeld(slot_id=SIDE, session_id="sess-2", generation=1)],
        after=restarting,
    )
    for base in (restarting.state, held.state):
        (restart,) = _restarts(base)
        commands = _every_kind(base)
        kept = [command for command in commands if not _ends_the_restart(command, restart)]
        for first in commands:
            state = transition(graph, base, first, LATER).state
            if _ends_the_restart(first, restart):
                assert _restarting(SLOT) not in state.causes or state.status == "cancelled"
                continue
            assert _restarting(SLOT) in state.causes, first
            removed = set(base.causes) - set(state.causes)
            # A hold that ends removes its own cause; nothing else removes one here.
            allowed = {_host_offline(SIDE)} if isinstance(first, RunnerHoldEnded) else set()
            assert removed <= allowed, (first, removed)
            for second in kept:
                after = transition(graph, state, second, LATER).state
                assert _restarting(SLOT) in after.causes, (first, second)


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        ("dispatch.stop_unconfirmed", True),
        ("workspace.head_moved", False),
        ("slot.generation_mismatch", False),
    ],
    ids=["retries_ran_out", "permanent", "abandoned_row"],
)
def test_a_failed_restart_pauses_retry_only_and_the_next_retry_fences_the_same_session(
    code: str, retryable: bool
) -> None:
    graph = _step_graph()
    retried = drive(graph, [RUN, *_blocked(SLOT), RetryStep(node_id="work")])
    (restart,) = _restarts(retried.state)
    failure = EffectFailed(effect_key=restart.effect_key, code=code, retryable=retryable)
    failed = drive(graph, [failure], after=retried)

    restart_failed = PauseCause(reason="failure_path", detail=f"restart:{code}", subject=SLOT)
    assert (failed.state.status, failed.state.causes) == ("paused", (restart_failed,))
    assert failed.log[-1].receipt_key == restart.effect_key
    assert transition(graph, failed.state, failure, NOW).state == failed.state
    refused = transition(graph, failed.state, ResumeRun(), NOW)
    assert refused.entry.rejection == Rejection(code="resume_not_allowed")
    assert retryable_activations(failed.state) == ("work||",)

    again = drive(graph, [RetryStep(node_id="work")], after=failed)
    assert again.state.causes == (_restarting(SLOT),)
    assert again.state.slots[0].session_generation == 3
    (restart,) = _restarts(again.state)
    assert restart.payload["generation"] == 3
    # No create ran for generation 2, so the newest session is still the first one's.
    creates = [effect for effect in again.state.effects if effect.kind == "create_session"]
    assert creates == [
        effect for effect in retried.state.effects if effect.kind == "create_session"
    ]
    assert [effect.payload.get("generation") for effect in creates] == [None]


def test_a_failed_restarts_code_is_bounded() -> None:
    graph = _step_graph()
    retried = drive(graph, [RUN, *_blocked(SLOT), RetryStep(node_id="work")])
    (restart,) = _restarts(retried.state)
    failed = transition(
        graph, retried.state, EffectFailed(effect_key=restart.effect_key, code="x" * 300), NOW
    )
    assert [cause.detail for cause in failed.state.causes] == ["restart:" + "x" * 128]


def test_a_finished_restart_creates_the_next_generation_and_briefs_it_with_the_salvage_ref() -> (
    None
):
    graph = _step_graph()
    retried = drive(graph, [RUN, *_blocked(SLOT), RetryStep(node_id="work")])
    (restart,) = _restarts(retried.state)
    salvaged: dict[str, JsonValue] = {
        "salvage_ref": "refs/coral/salvage/key-1",
        "salvage_commit": "5a1e5a1e5a1e5a1e",
        "head_verified": True,
    }
    created = drive(
        graph,
        [EffectCompleted(effect_key=restart.effect_key, payload=salvaged)],
        after=retried,
        auto_ack=False,
    )

    entry = created.log[-1]
    assert (created.state.status, created.state.causes) == ("running", ())
    assert entry.receipt_key == restart.effect_key
    (create,) = entry.effects
    assert (create.kind, create.subject, create.payload) == (
        "create_session",
        SLOT,
        {
            "node_id": "work",
            "profile": "implementer",
            "goal": "Do work",
            "generation": 2,
            "salvage_ref": "refs/coral/salvage/key-1",
            "salvage_commit": "5a1e5a1e5a1e5a1e",
        },
    )
    repeat = transition(graph, created.state, EffectCompleted(effect_key=restart.effect_key), NOW)
    assert (repeat.state, repeat.entry.receipt_key) == (created.state, restart.effect_key)

    briefed = drive(
        graph,
        [EffectCompleted(effect_key=create.effect_key, payload={"generation": 2})],
        after=created,
        auto_ack=False,
    )
    (brief,) = briefed.log[-1].effects
    assert (brief.kind, brief.payload["salvage_ref"], brief.payload["salvage_commit"]) == (
        "send_input",
        "refs/coral/salvage/key-1",
        "5a1e5a1e5a1e5a1e",
    )
    done = drive(
        graph,
        [
            EffectCompleted(effect_key=brief.effect_key),
            HandoffReceived(slot_id=SLOT, body="done", session_generation=2),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted", session_generation=2),
        ],
        after=briefed,
    )
    assert done.state.status == "completed"


def test_a_finished_restart_that_salvaged_nothing_briefs_without_a_ref() -> None:
    graph = _step_graph()
    restarted = _finish_restarts(
        graph, drive(graph, [RUN, *_blocked(SLOT), RetryStep(node_id="work")]), auto_ack=False
    )
    (create,) = restarted.log[-1].effects
    assert create.payload == {
        "node_id": "work",
        "profile": "implementer",
        "goal": "Do work",
        "generation": 2,
    }
    briefed = drive(graph, [EffectCompleted(effect_key=create.effect_key)], after=restarted)
    brief = next(effect for effect in briefed.state.effects if effect.kind == "send_input")
    assert "salvage_ref" not in brief.payload


def test_a_restart_result_for_a_slot_that_moved_on_only_receipts() -> None:
    graph = _step_graph()
    retried = drive(graph, [RUN, *_blocked(SLOT), RetryStep(node_id="work")])
    (restart,) = _restarts(retried.state)
    slot = retried.state.slots[0]
    moved = retried.state.model_copy(
        update={"slots": (slot.model_copy(update={"session_generation": 3}),)}
    )
    for command in (
        EffectCompleted(effect_key=restart.effect_key, payload=NO_SALVAGE),
        EffectFailed(effect_key=restart.effect_key, code="workspace.head_moved"),
    ):
        stale = transition(graph, moved, command, NOW)
        assert (stale.entry.rejection, stale.entry.effects) == (None, ())
        assert stale.entry.receipt_key == restart.effect_key
        assert stale.state.causes == moved.causes


def _lost(graph: CompiledGraph) -> tuple[Driven, Effect]:
    """A working step whose runner ``r1`` was lost on an edge, and the wake it emitted."""
    lost = drive(
        graph,
        [
            RUN,
            SessionFailed(
                slot_id=SLOT,
                failure_class="infra.runner_lost",
                cause="runner_disconnected",
                fact_key=FACT_A,
                runner_id="r1",
            ),
        ],
    )
    (wake,) = lost.log[-1].effects
    assert (wake.kind, wake.payload) == (
        "runner_lost",
        {"session_id": "sess-1", "generation": 1, "runner_id": "r1"},
    )
    return lost, wake


@pytest.mark.parametrize(
    ("outcome", "turn_running", "nudged"),
    [
        ("relaunched", False, True),
        ("runner_back", False, True),
        ("runner_back", True, False),
        ("skipped", False, False),
    ],
)
def test_a_wake_result_re_prompts_the_step_unless_its_turn_survived(
    outcome: str, turn_running: bool, nudged: bool
) -> None:
    graph = _step_graph()
    lost, wake = _lost(graph)
    assert lost.state.slots[0].failed_turn == FACT_A
    result: dict[str, JsonValue] = {"outcome": outcome, "turn_running": turn_running}

    woken = drive(graph, [EffectCompleted(effect_key=wake.effect_key, payload=result)], after=lost)

    entry = woken.log[-1]
    assert (entry.rejection, entry.receipt_key) == (None, wake.effect_key)
    expected = [("nudge", SLOT, {"fact_key": FACT_A, "reason": "runner_lost"})] if nudged else []
    assert [(effect.kind, effect.subject, effect.payload) for effect in entry.effects] == expected
    slot = woken.state.slots[0]
    backoff = [timer for timer in woken.state.timers if timer.kind == "infra_backoff"]
    if outcome == "runner_back" and turn_running:
        assert (slot.failed_turn, backoff) == (None, [])
    elif outcome == "skipped":
        assert (slot.failed_turn, len(backoff)) == (FACT_A, 3)
    else:
        assert slot.failed_turn is None
    assert woken.state.status == "running"


def test_a_wake_result_only_receipts_for_a_slot_that_moved_on_or_holds() -> None:
    graph = _step_graph()
    lost, wake = _lost(graph)
    relaunched = EffectCompleted(
        effect_key=wake.effect_key, payload={"outcome": "relaunched", "turn_running": False}
    )
    evaluating = drive(graph, [HandoffReceived(slot_id=SLOT, body="done")], after=lost)
    held = drive(graph, [RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1)], after=lost)
    slot = lost.state.slots[0]
    retried = lost.state.model_copy(
        update={"slots": (slot.model_copy(update={"session_generation": 2}),)}
    )
    ended = {"connection_epoch": 1, "retired_runners": ("r1",)}
    for state, changes in ((evaluating.state, ended), (held.state, ended), (retried, {})):
        result = transition(graph, state, relaunched, NOW)
        assert (result.entry.rejection, result.entry.effects) == (None, ())
        assert result.entry.receipt_key == wake.effect_key
        assert result.state.causes == state.causes
        # A result of the slot's generation still ends the outage it was for.
        (after,) = result.state.slots
        assert after == state.slots[0].model_copy(update=changes)


def test_an_offline_host_holds_its_slot_with_cancel_only_until_it_returns() -> None:
    graph = _step_graph()
    lost, _wake = _lost(graph)
    assert [timer.stage for timer in lost.state.timers] == [1, 2, 3]
    hold = RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1)

    held = drive(graph, [hold], after=lost)

    assert (held.state.status, held.state.causes) == ("paused", (_host_offline(SLOT),))
    assert held.state.timers == ()
    again = transition(graph, held.state, hold, NOW)
    assert (again.state, again.entry.patch, again.entry.rejection) == (held.state, (), None)
    resume = transition(graph, held.state, ResumeRun(), NOW)
    assert resume.entry.rejection == Rejection(code="resume_not_allowed")
    retry = transition(graph, held.state, RetryStep(node_id="work"), NOW)
    assert retry.entry.rejection == Rejection(code="host_offline_hold")
    assert retryable_activations(held.state) == ()
    assert transition(graph, held.state, CancelRun(), NOW).state.status == "cancelled"

    ended = drive(graph, [RunnerHoldEnded(slot_id=SLOT, generation=1)], after=held)
    assert (ended.state.status, ended.state.causes) == ("running", ())
    # The wake re-prompts the held slot itself once it relaunched the runner.
    assert ended.log[-1].effects == ()
    assert ended.state.slots[0].failed_turn == FACT_A


def test_a_hold_names_only_a_working_slot_of_its_generation() -> None:
    graph = _step_graph()
    running = drive(graph, [RUN])
    unknown = transition(
        graph, running.state, RunnerHeld(slot_id="ghost", session_id="s", generation=1), NOW
    )
    assert unknown.entry.rejection is not None
    assert unknown.entry.rejection.code == "rejected"
    for command in (
        RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=2),
        RunnerHoldEnded(slot_id=SLOT, generation=2),
    ):
        superseded = transition(graph, running.state, command, NOW)
        assert superseded.entry.rejection == Rejection(code="slot.superseded")
    ended = transition(graph, running.state, RunnerHoldEnded(slot_id=SLOT, generation=1), NOW)
    assert (ended.state, ended.entry.rejection) == (running.state, None)

    evaluating = drive(graph, [TurnEnded(slot_id=SLOT, fact_key=FACT_A)], after=running)
    idle = transition(
        graph, evaluating.state, RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1), NOW
    )
    assert (idle.state, idle.entry.rejection) == (evaluating.state, None)


def test_a_held_slot_arms_no_ladder_and_its_infra_stages_only_disarm() -> None:
    graph = _step_graph()
    lost, _wake = _lost(graph)
    held = drive(
        graph,
        [
            RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1),
            # A new runner's loss, and the same runner's edge, while held arm no ladder.
            RunnerLost(slot_id=SLOT, session_id="sess-1", generation=1, runner_id="r2"),
            SessionFailed(
                slot_id=SLOT,
                failure_class="infra.runner_lost",
                cause="runner_disconnected",
                fact_key="turn:sess-1:1:resp-2",
                runner_id="r1",
            ),
        ],
        after=lost,
    )
    assert held.state.timers == ()
    # A transient failure still arms its ladder, whose stages only disarm while held.
    transient = drive(
        graph,
        [
            SessionFailed(
                slot_id=SLOT,
                failure_class="infra.transient",
                cause="529",
                fact_key="turn:sess-1:1:resp-3",
            )
        ],
        after=held,
    )
    stages = transient.state.timers
    assert [timer.stage for timer in stages] == [1, 2, 3]
    state = transient
    for timer in stages:
        state = drive(graph, [TimerDue(timer_key=timer.key)], after=state, now=timer.due_at)
        assert state.log[-1].effects == ()
    assert state.state.timers == ()
    assert state.state.causes == (_host_offline(SLOT),)


def test_no_create_or_nudge_reaches_a_held_slot_under_any_sequence() -> None:
    graph = _step_graph()
    lost, wake = _lost(graph)
    held = drive(
        graph, [RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1)], after=lost
    ).state
    alphabet: list[Input] = [
        RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1),
        RunnerHoldEnded(slot_id=SLOT, generation=2),
        RunnerLost(slot_id=SLOT, session_id="sess-1", generation=1, runner_id="r2"),
        RunnerLost(slot_id=SLOT, session_id="sess-1", generation=1, runner_id="r3"),
        EffectCompleted(
            effect_key=wake.effect_key, payload={"outcome": "relaunched", "turn_running": False}
        ),
        ResumeRun(),
        RetryStep(node_id="work"),
        *(TimerDue(timer_key=f"infra_backoff:{SLOT}:{stage}") for stage in (1, 2, 3)),
    ]
    checked = 0
    for sequence in itertools.product(alphabet, repeat=3):
        state = held
        for command in sequence:
            result = transition(graph, state, command, LATER)
            if _host_offline(SLOT) in state.causes:
                assert all(
                    effect.subject != SLOT or effect.kind not in {"create_session", "nudge"}
                    for effect in result.entry.effects
                ), sequence
                checked += 1
            state = result.state
    assert checked == len(alphabet) ** 3 * 3


def test_an_old_wakes_mismatch_after_a_retry_leaves_the_restarted_step_healthy() -> None:
    graph = _step_graph()
    lost, wake = _lost(graph)
    failed = drive(
        graph,
        [
            SessionFailed(
                slot_id=SLOT,
                failure_class="agent.failed",
                cause="agent.failed",
                fact_key="turn:sess-1:1:resp-2",
            ),
            RetryStep(node_id="work"),
        ],
        after=lost,
    )
    restarted = _finish_restarts(graph, failed)
    assert (restarted.state.status, restarted.state.causes) == ("running", ())
    mismatch = EffectFailed(effect_key=wake.effect_key, code="slot.generation_mismatch")

    late = drive(graph, [mismatch], after=restarted)

    entry = late.log[-1]
    assert (entry.rejection, entry.effects, entry.receipt_key) == (None, (), wake.effect_key)
    assert (late.state.status, late.state.causes) == ("running", ())
    assert late.state.slots == restarted.state.slots
    receipt = next(item for item in late.state.receipts if item.key == wake.effect_key)
    assert receipt.payload == {"failed": "slot.generation_mismatch", "stale": True}
    assert transition(graph, late.state, mismatch, NOW).state == late.state


def test_a_close_that_lands_after_its_step_was_retried_is_kept_for_the_next_head() -> None:
    graph = _graph(_PAIR_PLAIN)
    closing = drive(graph, _finish(SLOT), after=drive(graph, [RUN]), auto_ack=False)
    close = next(effect for effect in closing.state.effects if effect.kind == "close_slot")
    retried = drive(
        graph, [*_blocked(PAIR), RetryStep(node_id="work")], after=closing, auto_ack=False
    )
    landed = EffectCompleted(
        effect_key=close.effect_key, payload={"pending_input": False, "commit": "abc123"}
    )

    late = drive(graph, [landed], after=retried, auto_ack=False)

    assert (late.log[-1].rejection, late.log[-1].effects) == (None, ())
    assert late.state.slots == retried.state.slots
    # Both restarts fail; the next Retry expects the commit the late close made.
    failures = [
        EffectFailed(effect_key=effect.effect_key, code="dispatch.stop_unconfirmed")
        for effect in _restarts(late.state)
    ]
    again = drive(graph, [*failures, RetryStep(node_id="work")], after=late, auto_ack=False)
    assert [effect.payload["expected_head"] for effect in again.log[-1].effects] == [
        "abc123",
        "abc123",
    ]


_GATED_RESTART = workflow_text(
    [
        start(),
        step("work"),
        step("side"),
        gate("hold", outcomes=["approve"]),
        decision("choose"),
        step("yes"),
        step("no"),
        step("after"),
        step("merge"),
        end(),
    ],
    [
        arrow("a1", "start", "work"),
        arrow("a2", "start", "side"),
        arrow("a3", "start", "hold"),
        arrow("a4", "start", "choose"),
        arrow("a5", "work", "merge"),
        arrow("a6", "side", "merge"),
        arrow("a7", "hold", "merge", label="approve"),
        arrow("a8", "choose", "yes", label="yes"),
        arrow("a9", "choose", "no", label="no"),
        arrow("a10", "yes", "after"),
        arrow("a11", "no", "after"),
        arrow("a12", "after", "merge"),
        arrow("a13", "merge", "end"),
    ],
)


def test_the_restarting_pause_holds_beside_an_open_gate_a_decision_and_its_old_effects() -> None:
    graph = _graph(_GATED_RESTART)
    restarting = drive(
        graph,
        [
            RUN,
            UsageLimited(slot_id=SIDE, fact_key="turn:sess-2:1:resp-1"),
            ResumeRun(),
            TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:resp-1"),
            *_blocked(SLOT),
            RetryStep(node_id="work"),
        ],
    )
    state = restarting.state
    assert _restarting(SLOT) in state.causes
    (restart,) = _restarts(state)
    (visit,) = state.gates
    old = [effect for effect in state.effects if effect.subject == SLOT and effect is not restart]
    assert {effect.kind for effect in old} >= {"create_session", "send_input", "nudge"}
    probe = next(timer for timer in state.timers if timer.kind == "plan_probe")
    commands: list[Input] = [
        AnswerGate(token=visit.token, label="approve", by="sam"),
        ChooseArrow(node_id="choose", label="yes", reason="because"),
        TimerDue(timer_key=probe.key),
        *(TimerDue(timer_key=timer.key) for timer in state.timers),
        *(EffectCompleted(effect_key=effect.effect_key) for effect in old),
        *(EffectFailed(effect_key=effect.effect_key, code="session.not_ready") for effect in old),
        *(
            EffectFailed(effect_key=effect.effect_key, code="session.lost", retryable=True)
            for effect in old
        ),
        ResumeRun(),
        PauseRun(reason="user", detail="hold"),
        RetryStep(node_id="work"),
        TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:resp-2"),
    ]
    for first, second in itertools.product(commands, repeat=2):
        current = state
        for command in (first, second):
            result = transition(graph, current, command, LATER)
            assert all(
                effect.subject != SLOT or effect.kind not in {"create_session", "nudge"}
                for effect in result.entry.effects
            ), (first, second)
            assert _restarting(SLOT) in result.state.causes, (first, second)
            current = result.state
    answered = transition(graph, state, commands[0], LATER)
    assert answered.entry.rejection == Rejection(code="run_paused")


# A run started before start entries named their rules.
UNMARKED = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1")


def test_an_unmarked_live_run_retries_behind_the_restart_fence() -> None:
    graph = _step_graph()
    assert UNMARKED.rules == PREVIOUS_RULES

    retried = drive(graph, [UNMARKED, *_blocked(SLOT), RetryStep(node_id="work")])

    # No stored log holds a Retry, so an unmarked run retries by the current rules.
    assert (retried.state.rules, retried.state.status) == (PREVIOUS_RULES, "paused")
    assert retried.state.causes == (_restarting(SLOT),)
    (effect,) = retried.log[-1].effects
    assert effect.payload["phases"] == ["fence_stop", "salvage_reset", "create_unbriefed", "brief"]
    refused = transition(graph, retried.state, RetryStep(node_id="work"), NOW)
    assert refused.entry.rejection == Rejection(code="restart_in_progress")
    # Stored logs do hold a Resume of a failed turn, so that rule stays.
    failed = drive(
        graph,
        [
            UNMARKED,
            SessionFailed(
                slot_id=SLOT, failure_class="agent.failed", cause="agent.failed", fact_key=FACT_A
            ),
        ],
    )
    resumed = transition(graph, failed.state, ResumeRun(), NOW)
    assert (resumed.entry.rejection, resumed.state.status) == (None, "running")


def test_an_unmarked_live_runs_liveness_loss_re_prompts_its_relaunched_runner() -> None:
    graph = _step_graph()
    loss = RunnerLost(
        slot_id=SLOT, session_id="sess-1", generation=1, runner_id="r1", fact_key=FACT_A
    )

    lost = drive(graph, [UNMARKED, loss])

    (wake,) = lost.log[-1].effects
    assert wake.payload == {"session_id": "sess-1", "generation": 1, "runner_id": "r1"}
    slot = lost.state.slots[0]
    assert (slot.failed_turn, slot.wakes) == (FACT_A, 1)
    assert [timer.stage for timer in lost.state.timers] == [1, 2, 3]
    relaunched = EffectCompleted(
        effect_key=wake.effect_key, payload={"outcome": "relaunched", "turn_running": False}
    )
    woken = drive(graph, [relaunched], after=lost)
    (nudge,) = woken.log[-1].effects
    assert (nudge.kind, nudge.payload["reason"]) == ("nudge", "runner_lost")
    delivered = drive(graph, [EffectCompleted(effect_key=nudge.effect_key)], after=woken)
    # The relaunched runner's own loss is a new one, not hidden under one key per generation.
    again = drive(
        graph,
        [RunnerLost(slot_id=SLOT, session_id="sess-1", generation=1, runner_id="r2")],
        after=delivered,
    )
    assert [effect.kind for effect in again.log[-1].effects] == ["runner_lost"]
