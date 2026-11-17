"""Watchdogs, infra backoff, and timer no-ops. Due times come from the transition clock."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from coral.engine import fold, transition
from coral.engine.reconcile import awaiting_effect
from coral.engine.types import (
    AnswerGate,
    EffectCompleted,
    EffectFailed,
    EngineConfig,
    InfraBackoffExhausted,
    PauseCause,
    PauseRun,
    ResumeRun,
    SessionFailed,
    StartRun,
    Timer,
    TimerDue,
    TimerPolicy,
    TurnEnded,
)
from coral.model.ir import CompiledGraph
from tests.coral.engine.drive import NOW, Driven, drive
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
SHORT = TimerPolicy(
    watchdog=timedelta(seconds=5),
    infra_backoff=(timedelta(seconds=1), timedelta(seconds=2), timedelta(seconds=4)),
    plan_probe_start=timedelta(seconds=3),
    plan_probe_cap=timedelta(seconds=9),
)
CFG = EngineConfig(timer_policy=SHORT)
FIRST = "turn:sess-1:1:msg:a"
SECOND = "turn:sess-1:1:msg:b"
THIRD = "turn:sess-1:1:msg:c"


def _graph(text: str) -> CompiledGraph:
    graph = compile_text(text)[0]
    assert not graph.analysis.unresolved, graph.analysis.unresolved
    return graph


def _decision_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), decision("choose"), end()],
            [
                arrow("a1", "start", "choose"),
                arrow("a2", "choose", "end", label="approved"),
                arrow("a3", "choose", "end", label="rejected"),
            ],
        )
    )


def _gate_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), gate("hold", outcomes=["approve", "again"]), end()],
            [
                arrow("a1", "start", "hold"),
                arrow("a2", "hold", "end", label="approve"),
                arrow("a3", "hold", "hold", label="again", back=True, limit=3, at_limit="a2"),
            ],
        )
    )


def _step_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), step("work"), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )


def test_default_timer_policy_matches_the_design() -> None:
    policy = EngineConfig().timer_policy
    assert policy.watchdog == timedelta(minutes=30)
    assert policy.infra_backoff == (
        timedelta(seconds=30),
        timedelta(minutes=2),
        timedelta(minutes=8),
    )
    assert policy.plan_probe_start == timedelta(minutes=5)
    assert policy.plan_probe_cap == timedelta(hours=1)


def test_opening_a_decision_arms_reminder_and_alert_without_effects() -> None:
    graph = _decision_graph()
    opened = drive(graph, [RUN], config=CFG)
    assert opened.log[0].effects == ()
    assert opened.state.decisions[0].status == "requested"
    _assert_watchdogs(opened.state.timers, opened.state.decisions[0].activation_id, generation=1)
    assert fold(graph, opened.log, CFG) == opened.state


def test_opening_a_gate_arms_watchdogs_beside_publish_only() -> None:
    graph = _gate_graph()
    opened = drive(graph, [RUN], config=CFG)
    visit = opened.state.gates[0]
    assert visit.status == "open"
    assert [effect.kind for effect in opened.log[0].effects] == ["publish_gate"]
    _assert_watchdogs(opened.state.timers, visit.activation_id, generation=visit.visit_no)


def test_watchdog_reminds_at_its_first_due_then_alerts() -> None:
    graph = _decision_graph()
    opened = drive(graph, [RUN], config=CFG)
    remind, alert = opened.state.timers
    reminded = drive(
        graph, [TimerDue(timer_key=remind.key)], config=CFG, after=opened, now=remind.due_at
    )
    entry = reminded.log[-1]
    assert entry.rejection is None
    assert [effect.kind for effect in entry.effects] == ["notify"]
    assert entry.effects[0].payload == {"kind": "watchdog", "stage": "reminder"}
    assert reminded.state.decisions[0].status == "reminded"
    assert reminded.state.timers == (alert,)

    alerted = drive(
        graph, [TimerDue(timer_key=alert.key)], config=CFG, after=reminded, now=alert.due_at
    )
    assert [effect.payload for effect in alerted.log[-1].effects] == [
        {"kind": "watchdog", "stage": "alert"}
    ]
    decision = alerted.state.decisions[0]
    assert decision.status == "escalated"
    assert decision.label is None
    assert decision.reason is None
    assert alerted.state.timers == ()
    assert alerted.state.status == "running"
    assert all(item.node_id != "end" for item in alerted.state.activations)
    assert all(item.payload.get("code") != "decision.made" for item in alerted.state.receipts)
    assert all(item.payload.get("decision.made") is not True for item in alerted.state.receipts)


def test_a_late_reminder_emits_the_alert_once() -> None:
    graph = _decision_graph()
    opened = drive(graph, [RUN], config=CFG)
    remind, alert = opened.state.timers
    late = drive(
        graph,
        [TimerDue(timer_key=remind.key), TimerDue(timer_key=alert.key)],
        config=CFG,
        after=opened,
        now=alert.due_at,
    )
    first, second = late.log[-2:]
    assert [effect.payload for effect in first.effects] == [{"kind": "watchdog", "stage": "alert"}]
    assert late.state.decisions[0].status == "escalated"
    assert late.state.timers == ()
    assert (second.rejection, second.effects, second.patch) == (None, (), ())


def test_watchdog_due_does_not_resolve_a_gate() -> None:
    graph = _gate_graph()
    opened = drive(graph, [RUN], config=CFG)
    visit = opened.state.gates[0]
    remind, alert = opened.state.timers
    due = transition(graph, opened.state, TimerDue(timer_key=remind.key), remind.due_at, CFG)
    assert [effect.kind for effect in due.entry.effects] == ["notify"]
    assert due.entry.effects[0].payload == {"kind": "watchdog", "stage": "reminder"}
    current = next(item for item in due.state.gates if item.token == visit.token)
    assert current.status == "open"
    assert current.label is None
    assert due.state.timers == (alert,)
    assert due.state.status == "running"
    assert all(item.node_id != "end" for item in due.state.activations)
    assert all(item.payload.get("decision.made") is not True for item in due.state.receipts)
    assert fold(graph, (*opened.log, due.entry), CFG) == due.state


def test_later_gate_pass_replaces_the_previous_watchdogs() -> None:
    graph = _gate_graph()
    opened = drive(graph, [RUN], config=CFG)
    previous = opened.state.gates[0]
    revisited = transition(
        graph,
        opened.state,
        AnswerGate(token=previous.token, label="again", by="sam", note="loop"),
        NOW,
        CFG,
    )
    assert [effect.kind for effect in revisited.entry.effects] == ["withdraw_gate", "publish_gate"]
    fresh = next(item for item in revisited.state.gates if item.status == "open")
    assert fresh.activation_id != previous.activation_id
    subjects = {timer.subject for timer in revisited.state.timers}
    assert subjects == {fresh.activation_id}
    assert all(timer.generation == fresh.visit_no for timer in revisited.state.timers)
    _assert_watchdogs(revisited.state.timers, fresh.activation_id, generation=fresh.visit_no)
    assert fold(graph, (*opened.log, revisited.entry), CFG) == revisited.state


def test_infra_stage_one_reprompts_and_an_undelivered_reprompt_pauses_at_stage_three() -> None:
    graph = _step_graph()
    running = drive(graph, [RUN], config=CFG)
    failed = transition(
        graph,
        running.state,
        SessionFailed(
            slot_id=SLOT,
            failure_class="infra.transient",
            cause="timeout",
            fact_key="fact-1",
        ),
        NOW,
        CFG,
    )
    assert failed.entry.rejection is None
    assert failed.state.status == "running"
    assert failed.state.causes == ()
    assert failed.state.slots[0].failed_turn == "fact-1"
    timers = failed.state.timers
    assert [effect.kind for effect in failed.entry.effects] == [
        "arm_timer",
        "arm_timer",
        "arm_timer",
    ]
    assert [effect.payload["kind"] for effect in failed.entry.effects] == ["infra_backoff"] * 3
    assert [effect.payload["stage"] for effect in failed.entry.effects] == [1, 2, 3]
    assert [effect.subject for effect in failed.entry.effects] == [timer.key for timer in timers]
    assert [effect.payload["due_at"] for effect in failed.entry.effects] == [
        timer.due_at.isoformat() for timer in timers
    ]
    assert [timer.stage for timer in timers] == [1, 2, 3]
    assert [timer.due_at for timer in timers] == [NOW + delay for delay in SHORT.infra_backoff]
    assert {timer.subject for timer in timers} == {SLOT}
    assert {timer.kind for timer in timers} == {"infra_backoff"}

    first_at, second_at, third_at = (timer.due_at for timer in timers)
    due_first = transition(graph, failed.state, TimerDue(timer_key=timers[0].key), first_at, CFG)
    assert [effect.kind for effect in due_first.entry.effects] == ["nudge"]
    assert due_first.entry.effects[0].subject == SLOT
    assert due_first.entry.effects[0].payload == {"fact_key": "fact-1", "reason": "backoff"}
    assert due_first.state.slots[0].failed_turn is None
    assert due_first.state.status == "running"
    assert [timer.stage for timer in due_first.state.timers] == [2, 3]

    # The re-prompt is still undelivered and the slot is not marked again, so stage 2 only disarms.
    due_second = transition(
        graph, due_first.state, TimerDue(timer_key=timers[1].key), second_at, CFG
    )
    assert due_second.entry.effects == ()
    assert due_second.state.status == "running"
    assert [timer.stage for timer in due_second.state.timers] == [3]
    repeat = transition(graph, due_second.state, TimerDue(timer_key=timers[0].key), second_at, CFG)
    assert repeat.entry.rejection is None
    assert repeat.entry.effects == ()
    assert repeat.state == due_second.state

    due_third = transition(
        graph, due_second.state, TimerDue(timer_key=timers[2].key), third_at, CFG
    )
    assert due_third.state.status == "paused"
    assert due_third.state.causes == (
        PauseCause(reason="infra", detail="infra.transient", subject=SLOT),
    )
    assert due_third.state.timers == ()
    assert due_third.entry.effects == ()
    logged = (
        *running.log,
        failed.entry,
        due_first.entry,
        due_second.entry,
        repeat.entry,
        due_third.entry,
    )
    assert fold(graph, logged, CFG) == due_third.state


def test_a_reprompted_turn_still_running_at_stage_three_is_not_paused() -> None:
    graph = _step_graph()
    failed = drive(graph, [RUN, _failed(FIRST)], config=CFG)
    first, second, third = failed.state.timers
    nudged = _fire(graph, failed, first)
    nudge = nudged.log[-1].effects[0]
    delivered = drive(
        graph,
        [EffectCompleted(effect_key=nudge.effect_key)],
        config=CFG,
        after=nudged,
        now=first.due_at,
    )
    quiet = _fire(graph, _fire(graph, delivered, second), third)
    assert [entry.effects for entry in quiet.log[-2:]] == [(), ()]
    assert quiet.state.status == "running"
    assert quiet.state.causes == ()
    assert quiet.state.timers == ()
    assert quiet.state.slots[0].status == "working"


def test_a_reprompted_turn_that_fails_again_keeps_the_ladder_and_stage_three_pauses() -> None:
    graph = _step_graph()
    failed = drive(graph, [RUN, _failed(FIRST)], config=CFG)
    first, second, third = failed.state.timers
    nudged = _delivered(graph, _fire(graph, failed, first), first.due_at)

    again = drive(
        graph,
        [_failed(SECOND)],
        config=CFG,
        after=nudged,
        now=first.due_at + timedelta(seconds=0.5),
    )
    assert again.log[-1].rejection is None
    assert again.log[-1].effects == ()
    assert again.state.timers == (second, third)
    assert again.state.slots[0].failed_turn == SECOND

    restaged = _fire(graph, again, second)
    assert [effect.payload for effect in restaged.log[-1].effects] == [
        {"fact_key": SECOND, "reason": "backoff"}
    ]
    retried = _delivered(graph, restaged, second.due_at)
    third_failure = drive(
        graph,
        [_failed(THIRD)],
        config=CFG,
        after=retried,
        now=second.due_at + timedelta(seconds=1),
    )
    assert third_failure.state.timers == (third,)

    paused = _fire(graph, third_failure, third)
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="infra", detail="infra.transient", subject=SLOT),
    )
    assert paused.state.slots[0].failed_turn == THIRD

    resumed = drive(graph, [ResumeRun()], config=CFG, after=paused, now=third.due_at)
    assert resumed.state.status == "running"
    assert [(effect.kind, effect.payload) for effect in resumed.log[-1].effects] == [
        ("nudge", {"fact_key": THIRD, "reason": "resume"})
    ]
    assert resumed.state.slots[0].failed_turn is None


@pytest.mark.parametrize("fired", [0, 1, 2, 3])
def test_a_completed_turn_disarms_the_ladder_at_any_stage(fired: int) -> None:
    """``fired`` stages run, each earlier re-prompt failing again, then a turn completes."""
    graph = _step_graph()
    current = drive(graph, [RUN, _failed(FIRST)], config=CFG)
    ladder = current.state.timers
    for timer in ladder[:fired]:
        current = _fire(graph, current, timer)
        if timer.stage < 3:
            current = _delivered(graph, current, timer.due_at)
        if timer.stage < fired:
            again = _failed(f"turn:sess-1:1:msg:again-{timer.stage}")
            current = drive(graph, [again], config=CFG, after=current, now=timer.due_at)
    assert current.state.status == ("paused" if fired == 3 else "running")

    at = current.log[-1].now + timedelta(seconds=0.5)
    ended = drive(
        graph, [TurnEnded(slot_id=SLOT, fact_key=SECOND)], config=CFG, after=current, now=at
    )
    assert ended.state.timers == ()
    assert ended.state.slots[0].failed_turn is None
    # A turn end while paused is held and not counted.
    assert ended.state.slots[0].nudges == (0 if fired == 3 else 1)
    assert [(effect.kind, effect.payload) for effect in ended.log[-1].effects] == [
        ("nudge", {"fact_key": SECOND})
    ]

    # Late stages and a repeated first failure neither re-mark the slot nor re-arm.
    late = ended
    for timer in ladder[fired:]:
        late = _fire(graph, late, timer)
    repeated = drive(graph, [_failed(FIRST)], config=CFG, after=late, now=late.log[-1].now)
    assert repeated.log[-1].receipt_key == FIRST
    assert all(entry.effects == () for entry in repeated.log[len(ended.log) :])
    assert repeated.state == ended.state

    if fired == 3:
        # The held turn-end nudge is the slot's re-prompt, so resume adds none.
        resumed = drive(graph, [ResumeRun()], config=CFG, after=repeated, now=at)
        assert resumed.state.status == "running"
        assert resumed.log[-1].effects == ()


def test_a_failure_after_the_ladder_ran_out_arms_a_fresh_one() -> None:
    graph = _step_graph()
    failed = drive(graph, [RUN, _failed(FIRST)], config=CFG)
    first, second, third = failed.state.timers
    spent = _fire(
        graph,
        _fire(graph, _delivered(graph, _fire(graph, failed, first), first.due_at), second),
        third,
    )
    assert spent.state.timers == ()
    assert spent.state.status == "running"

    later = third.due_at + timedelta(seconds=10)
    again = drive(graph, [_failed(SECOND)], config=CFG, after=spent, now=later)
    assert [effect.kind for effect in again.log[-1].effects] == ["arm_timer"] * 3
    assert [timer.due_at for timer in again.state.timers] == [
        later + delay for delay in SHORT.infra_backoff
    ]

    # The first ladder's stage-1 row delivered late finds its re-armed key not due yet.
    fresh = again.state.timers[0]
    assert fresh.key == first.key
    stale = drive(graph, [TimerDue(timer_key=first.key)], config=CFG, after=again, now=later)
    assert stale.state == again.state
    assert stale.log[-1].effects == ()
    restaged = _fire(graph, stale, fresh)
    assert [effect.payload for effect in restaged.log[-1].effects] == [
        {"fact_key": SECOND, "reason": "backoff"}
    ]


def test_infra_backoff_exhausted_pauses_and_disarms() -> None:
    graph = _step_graph()
    running = drive(graph, [RUN], config=CFG)
    failed = transition(
        graph,
        running.state,
        SessionFailed(
            slot_id=SLOT, failure_class="infra.transient", cause="timeout", fact_key="fact-1"
        ),
        NOW,
        CFG,
    )
    stage_three = failed.state.timers[2]
    exhausted = transition(graph, failed.state, InfraBackoffExhausted(slot_id=SLOT), NOW, CFG)
    assert exhausted.entry.effects == ()
    assert exhausted.state.status == "paused"
    assert exhausted.state.causes == (
        PauseCause(reason="infra", detail="infra.transient", subject=SLOT),
    )
    assert exhausted.state.timers == ()
    repeat = transition(
        graph, exhausted.state, TimerDue(timer_key=stage_three.key), stage_three.due_at, CFG
    )
    assert repeat.state == exhausted.state
    assert repeat.entry.rejection is None
    assert repeat.entry.effects == ()


def test_unknown_failure_class_is_not_supported() -> None:
    graph = _step_graph()
    running = drive(graph, [RUN], config=CFG)
    failed = transition(
        graph,
        running.state,
        SessionFailed(slot_id=SLOT, failure_class="nope", cause="nope", fact_key="fact-1"),
        NOW,
        CFG,
    )
    assert failed.state == running.state
    assert failed.entry.effects == ()
    assert failed.entry.rejection is not None
    assert failed.entry.rejection.code == "not_supported"


def test_unknown_timer_due_is_a_noop() -> None:
    graph = _step_graph()
    running = drive(graph, [RUN], config=CFG)
    due = transition(graph, running.state, TimerDue(timer_key="missing"), NOW, CFG)
    assert due.state == running.state
    assert due.entry.rejection is None
    assert due.entry.effects == ()
    assert due.entry.patch == ()
    assert fold(graph, (*running.log, due.entry), CFG) == running.state


def test_plan_probe_due_clears_plan_limit_and_arms_the_next_probe() -> None:
    """A due that clears ``plan_limit`` disarms that row and arms the next probe."""
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason="plan_limit", detail="limited")], config=CFG)
    probe = _probe()
    armed = paused.state.model_copy(update={"timers": (*paused.state.timers, probe)})
    at = probe.due_at
    due = transition(graph, armed, TimerDue(timer_key=probe.key), at, CFG)
    next_due = at + min(SHORT.plan_probe_start * 2, SHORT.plan_probe_cap)
    assert due.entry.rejection is None
    assert [effect.kind for effect in due.entry.effects] == ["arm_timer"]
    assert due.entry.effects[0].payload == {
        "kind": "plan_probe",
        "stage": 2,
        "due_at": next_due.isoformat(),
    }
    assert due.state.status == "running"
    assert due.state.causes == ()
    assert len(due.state.timers) == 1
    nxt = due.state.timers[0]
    assert nxt.kind == "plan_probe"
    assert nxt.stage == 2
    assert nxt.due_at == next_due
    assert nxt.key == due.entry.effects[0].subject
    assert probe.key not in {timer.key for timer in due.state.timers}
    assert all(effect.kind != "notify" for effect in due.state.effects)

    # With no plan_limit cause left, the next probe disarms its own key and does nothing else.
    again = transition(graph, due.state, TimerDue(timer_key=nxt.key), nxt.due_at, CFG)
    assert again.entry.rejection is None
    assert again.entry.effects == ()
    assert again.state.timers == ()
    assert again.state.status == "running"
    assert again.state == due.state.model_copy(update={"timers": (), "seq": due.state.seq + 1})

    idle = drive(graph, [RUN], config=CFG).state
    still = idle.model_copy(update={"timers": (probe,)})
    disarmed = transition(graph, still, TimerDue(timer_key=probe.key), at, CFG)
    assert disarmed.entry.rejection is None
    assert disarmed.entry.effects == ()
    assert disarmed.state == still.model_copy(update={"timers": (), "seq": still.seq + 1})


def test_plan_probe_due_caps_the_doubled_delay() -> None:
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason="plan_limit", detail="limited")], config=CFG)
    probe = _probe().model_copy(update={"stage": 3, "key": "plan_probe::3"})
    held = paused.state.model_copy(update={"timers": (probe,)})
    due = transition(graph, held, TimerDue(timer_key=probe.key), probe.due_at, CFG)
    capped = probe.due_at + SHORT.plan_probe_cap
    assert due.entry.effects[0].payload["stage"] == 4
    assert due.entry.effects[0].payload["due_at"] == capped.isoformat()
    assert due.state.timers[0].due_at == capped
    assert due.state.timers[0].stage == 4
    assert due.state.causes == ()


def test_a_plan_probe_clears_the_pause_and_reprompts_the_failed_turn() -> None:
    graph = _step_graph()
    limited = drive(graph, [RUN, _failed(FIRST, "plan.usage_limit", "429")], config=CFG)
    assert limited.state.causes == (
        PauseCause(reason="plan_limit", detail="plan.usage_limit", subject=SLOT),
    )
    (probe,) = limited.state.timers
    cleared = _fire(graph, limited, probe)
    assert cleared.state.status == "running"
    assert cleared.state.causes == ()
    assert [effect.kind for effect in cleared.log[-1].effects] == ["arm_timer", "nudge"]
    assert cleared.log[-1].effects[1].payload == {"fact_key": FIRST, "reason": "resume"}
    assert cleared.state.slots[0].failed_turn is None


def test_a_recovery_drops_the_next_probe_and_a_later_limit_clears_again() -> None:
    graph = _step_graph()
    limited = drive(graph, [RUN, _failed(FIRST, "plan.usage_limit", "429")], config=CFG)
    (probe,) = limited.state.timers
    cleared = _delivered(graph, _fire(graph, limited, probe), probe.due_at)
    assert [timer.stage for timer in cleared.state.timers] == [2]

    recovered = drive(
        graph,
        [TurnEnded(slot_id=SLOT, fact_key=SECOND)],
        config=CFG,
        after=cleared,
        now=probe.due_at + timedelta(seconds=1),
    )
    assert recovered.state.timers == ()
    working = _delivered(graph, recovered, probe.due_at + timedelta(seconds=1))

    later = probe.due_at + timedelta(hours=2)
    relimited = drive(
        graph, [_failed(THIRD, "plan.usage_limit", "429")], config=CFG, after=working, now=later
    )
    assert relimited.state.status == "paused"
    assert [effect.kind for effect in relimited.log[-1].effects] == ["arm_timer"]
    (fresh,) = relimited.state.timers
    assert (fresh.stage, fresh.due_at) == (1, later + SHORT.plan_probe_start)
    unpaused = _fire(graph, relimited, fresh)
    assert unpaused.state.status == "running"
    assert unpaused.state.causes == ()


def test_a_limit_while_the_next_probe_is_armed_keeps_that_probe() -> None:
    graph = _step_graph()
    limited = drive(graph, [RUN, _failed(FIRST, "plan.usage_limit", "429")], config=CFG)
    (probe,) = limited.state.timers
    cleared = _delivered(graph, _fire(graph, limited, probe), probe.due_at)
    (second_probe,) = cleared.state.timers

    again = drive(
        graph,
        [_failed(SECOND, "plan.usage_limit", "429")],
        config=CFG,
        after=cleared,
        now=probe.due_at + timedelta(seconds=1),
    )
    assert again.state.status == "paused"
    assert again.log[-1].effects == ()
    assert again.state.timers == (second_probe,)
    assert again.state.slots[0].failed_turn == SECOND

    unpaused = _fire(graph, again, second_probe)
    assert unpaused.state.status == "running"
    assert [effect.kind for effect in unpaused.log[-1].effects] == ["arm_timer", "nudge"]
    assert unpaused.log[-1].effects[1].payload == {"fact_key": SECOND, "reason": "resume"}


def test_a_completed_turn_while_paused_for_its_plan_limit_keeps_the_probe() -> None:
    graph = _step_graph()
    limited = drive(graph, [RUN, _failed(FIRST, "plan.usage_limit", "429")], config=CFG)
    (probe,) = limited.state.timers
    typed = drive(
        graph,
        [TurnEnded(slot_id=SLOT, fact_key=SECOND, origin="user")],
        config=CFG,
        after=limited,
        now=NOW + timedelta(seconds=1),
    )
    assert typed.state.status == "paused"
    assert typed.state.timers == (probe,)
    assert typed.state.slots[0].failed_turn is None

    cleared = _fire(graph, typed, probe)
    assert cleared.state.status == "running"
    assert [(effect.kind, effect.payload) for effect in cleared.log[-1].effects][1:] == [
        ("nudge", {"fact_key": "", "reason": "resume"})
    ]


def test_a_new_limit_drops_a_past_due_probe_of_the_slot() -> None:
    graph = _step_graph()
    limited = drive(graph, [RUN, _failed(FIRST, "plan.usage_limit", "429")], config=CFG)
    (probe,) = limited.state.timers
    cleared = _delivered(graph, _fire(graph, limited, probe), probe.due_at)
    (lagging,) = cleared.state.timers

    # The drainer is late: stage 2 is past due but has not fired when the next 429 lands.
    late = lagging.due_at + timedelta(seconds=1)
    relimited = drive(
        graph, [_failed(SECOND, "plan.usage_limit", "429")], config=CFG, after=cleared, now=late
    )
    (fresh,) = relimited.state.timers
    assert (fresh.stage, fresh.due_at) == (1, late + SHORT.plan_probe_start)
    assert [effect.kind for effect in relimited.log[-1].effects] == ["arm_timer"]
    stale = drive(graph, [TimerDue(timer_key=lagging.key)], config=CFG, after=relimited, now=late)
    assert stale.state == relimited.state
    assert stale.state.status == "paused"


def test_a_second_permanent_failure_with_the_same_cause_still_receipts_its_effect() -> None:
    graph = _step_graph()
    failed = drive(graph, [RUN, _failed(FIRST)], config=CFG)
    first, second, _third = failed.state.timers
    nudged = _fire(graph, failed, first)
    first_nudge = nudged.log[-1].effects[0]
    gone = drive(
        graph,
        [EffectFailed(effect_key=first_nudge.effect_key, code="session.gone")],
        config=CFG,
        after=nudged,
        now=first.due_at,
    )
    assert gone.state.causes == (
        PauseCause(reason="failure_path", detail="session.gone", subject=SLOT),
    )
    # Paused, the slot fails again and stage 2 re-prompts it; that nudge fails the same way.
    again = drive(
        graph,
        [_failed(SECOND), TimerDue(timer_key=second.key)],
        config=CFG,
        after=gone,
        now=second.due_at,
    )
    second_nudge = again.log[-1].effects[0]
    refused = EffectFailed(effect_key=second_nudge.effect_key, code="session.gone")
    receipted = drive(graph, [refused], config=CFG, after=again, now=second.due_at)
    entry = receipted.log[-1]
    assert (entry.rejection, entry.receipt_key) == (None, second_nudge.effect_key)
    assert receipted.state.causes == gone.state.causes
    assert not awaiting_effect(receipted.state, SLOT)

    repeat = transition(graph, receipted.state, refused, second.due_at, CFG)
    assert repeat.state == receipted.state
    assert repeat.entry.receipt_key == second_nudge.effect_key


@pytest.mark.parametrize("kind", ["watchdog_remind", "infra_backoff", "plan_probe"])
def test_a_timer_fired_before_its_due_time_changes_nothing(kind: str) -> None:
    graph, armed = _armed(kind)
    timer = next(item for item in armed.state.timers if item.kind == kind)
    early = drive(
        graph,
        [TimerDue(timer_key=timer.key)],
        config=CFG,
        after=armed,
        now=timer.due_at - timedelta(microseconds=1),
    )
    entry = early.log[-1]
    assert early.state == armed.state
    assert (entry.rejection, entry.effects, entry.patch) == (None, (), ())
    assert _fire(graph, armed, timer).state != armed.state


def test_plan_probe_due_without_the_timer_does_not_clear_plan_limit() -> None:
    graph = _step_graph()
    paused = drive(
        graph,
        [RUN, PauseRun(reason="plan_limit", detail="limited")],
        config=CFG,
    )
    due = transition(graph, paused.state, TimerDue(timer_key="plan_probe:"), NOW, CFG)
    assert due.state == paused.state
    assert due.entry.rejection is None
    assert due.entry.effects == ()
    assert fold(graph, (*paused.log, due.entry), CFG) == paused.state


def _failed(
    fact_key: str, failure_class: str = "infra.transient", cause: str = "529"
) -> SessionFailed:
    return SessionFailed(slot_id=SLOT, failure_class=failure_class, cause=cause, fact_key=fact_key)


def _fire(graph: CompiledGraph, driven: Driven, timer: Timer) -> Driven:
    """Fire ``timer`` at its own due time."""
    return drive(
        graph, [TimerDue(timer_key=timer.key)], config=CFG, after=driven, now=timer.due_at
    )


def _delivered(graph: CompiledGraph, driven: Driven, now: datetime) -> Driven:
    """Complete the newest nudge, as its send would."""
    nudge = next(effect for effect in reversed(driven.state.effects) if effect.kind == "nudge")
    return drive(
        graph, [EffectCompleted(effect_key=nudge.effect_key)], config=CFG, after=driven, now=now
    )


def _armed(kind: str) -> tuple[CompiledGraph, Driven]:
    """A run with a ``kind`` timer armed at ``NOW``."""
    if kind == "watchdog_remind":
        graph = _decision_graph()
        return graph, drive(graph, [RUN], config=CFG)
    graph = _step_graph()
    failure_class = "infra.transient" if kind == "infra_backoff" else "plan.usage_limit"
    return graph, drive(graph, [RUN, _failed(FIRST, failure_class)], config=CFG)


def _probe(key: str = "plan_probe:") -> Timer:
    return Timer(
        key=key,
        kind="plan_probe",
        scope="",
        subject="",
        generation=1,
        stage=1,
        due_at=NOW + SHORT.plan_probe_start,
    )


def _assert_watchdogs(timers: tuple[Timer, ...], subject: str, generation: int) -> None:
    assert [timer.kind for timer in timers] == ["watchdog_remind", "watchdog_alert"]
    assert [timer.stage for timer in timers] == [1, 2]
    assert [timer.due_at for timer in timers] == [NOW + SHORT.watchdog, NOW + (SHORT.watchdog * 2)]
    assert {timer.subject for timer in timers} == {subject}
    assert {timer.scope for timer in timers} == {subject}
    assert {timer.generation for timer in timers} == {generation}
    assert [timer.key for timer in timers] == [
        f"watchdog_remind:{subject}",
        f"watchdog_alert:{subject}",
    ]
