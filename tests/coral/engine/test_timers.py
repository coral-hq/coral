"""Watchdogs, infra backoff, and timer no-ops. Due times come from the transition clock."""

from __future__ import annotations

from datetime import timedelta

from coral.engine import fold, transition
from coral.engine.types import (
    AnswerGate,
    EngineConfig,
    InfraBackoffExhausted,
    PauseCause,
    PauseRun,
    SessionFailed,
    StartRun,
    Timer,
    TimerDue,
    TimerPolicy,
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
SHORT = TimerPolicy(
    watchdog=timedelta(seconds=5),
    infra_backoff=(timedelta(seconds=1), timedelta(seconds=2), timedelta(seconds=4)),
    plan_probe_start=timedelta(seconds=3),
    plan_probe_cap=timedelta(seconds=9),
)
CFG = EngineConfig(timer_policy=SHORT)


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


def test_late_reminder_fires_the_alert_once_and_does_not_decide() -> None:
    graph = _decision_graph()
    opened = drive(graph, [RUN], config=CFG)
    remind = next(timer for timer in opened.state.timers if timer.kind == "watchdog_remind")
    due = transition(graph, opened.state, TimerDue(timer_key=remind.key), NOW, CFG)
    assert due.entry.rejection is None
    assert [effect.kind for effect in due.entry.effects] == ["notify"]
    assert due.entry.effects[0].payload == {"kind": "watchdog", "stage": "alert"}
    decision = due.state.decisions[0]
    assert decision.status == "escalated"
    assert decision.label is None
    assert decision.reason is None
    assert due.state.timers == ()
    assert due.state.status == "running"
    assert all(item.node_id != "end" for item in due.state.activations)
    assert all(item.payload.get("code") != "decision.made" for item in due.state.receipts)
    assert all(item.payload.get("decision.made") is not True for item in due.state.receipts)
    assert fold(graph, (*opened.log, due.entry), CFG) == due.state


def test_watchdog_due_does_not_resolve_a_gate() -> None:
    graph = _gate_graph()
    opened = drive(graph, [RUN], config=CFG)
    visit = opened.state.gates[0]
    remind = next(timer for timer in opened.state.timers if timer.kind == "watchdog_remind")
    due = transition(graph, opened.state, TimerDue(timer_key=remind.key), NOW, CFG)
    assert [effect.kind for effect in due.entry.effects] == ["notify"]
    assert due.entry.effects[0].payload == {"kind": "watchdog", "stage": "alert"}
    current = next(item for item in due.state.gates if item.token == visit.token)
    assert current.status == "open"
    assert current.label is None
    assert due.state.timers == ()
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


def test_infra_stages_one_and_two_leave_stage_three_armed() -> None:
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

    due_first = transition(graph, failed.state, TimerDue(timer_key=timers[0].key), NOW, CFG)
    assert due_first.entry.effects == ()
    assert due_first.state.status == "running"
    assert [timer.stage for timer in due_first.state.timers] == [2, 3]

    due_second = transition(graph, due_first.state, TimerDue(timer_key=timers[1].key), NOW, CFG)
    assert due_second.state.status == "running"
    assert [timer.stage for timer in due_second.state.timers] == [3]
    repeat = transition(graph, due_second.state, TimerDue(timer_key=timers[0].key), NOW, CFG)
    assert repeat.entry.rejection is None
    assert repeat.entry.effects == ()
    assert repeat.state == due_second.state

    due_third = transition(graph, due_second.state, TimerDue(timer_key=timers[2].key), NOW, CFG)
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
    stage_three = failed.state.timers[2].key
    exhausted = transition(graph, failed.state, InfraBackoffExhausted(slot_id=SLOT), NOW, CFG)
    assert exhausted.entry.effects == ()
    assert exhausted.state.status == "paused"
    assert exhausted.state.causes == (
        PauseCause(reason="infra", detail="infra.transient", subject=SLOT),
    )
    assert exhausted.state.timers == ()
    repeat = transition(graph, exhausted.state, TimerDue(timer_key=stage_three), NOW, CFG)
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
    due = transition(graph, armed, TimerDue(timer_key=probe.key), NOW, CFG)
    next_due = NOW + min(SHORT.plan_probe_start * 2, SHORT.plan_probe_cap)
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
    again = transition(graph, due.state, TimerDue(timer_key=nxt.key), NOW, CFG)
    assert again.state == due.state
    assert again.entry.rejection is None
    assert again.entry.effects == ()

    idle = drive(graph, [RUN], config=CFG).state
    still = idle.model_copy(update={"timers": (probe,)})
    noop = transition(graph, still, TimerDue(timer_key=probe.key), NOW, CFG)
    assert noop.state == still
    assert noop.entry.rejection is None
    assert noop.entry.effects == ()


def test_plan_probe_due_caps_the_doubled_delay() -> None:
    graph = _step_graph()
    paused = drive(graph, [RUN, PauseRun(reason="plan_limit", detail="limited")], config=CFG)
    probe = _probe().model_copy(update={"stage": 3, "key": "plan_probe::3"})
    held = paused.state.model_copy(update={"timers": (probe,)})
    due = transition(graph, held, TimerDue(timer_key=probe.key), NOW, CFG)
    assert due.entry.effects[0].payload["stage"] == 4
    assert due.entry.effects[0].payload["due_at"] == (NOW + SHORT.plan_probe_cap).isoformat()
    assert due.state.timers[0].due_at == NOW + SHORT.plan_probe_cap
    assert due.state.timers[0].stage == 4
    assert due.state.causes == ()


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
