"""Outcome table for 529, 429, and 401. The reducer emits that list and fold matches."""

from __future__ import annotations

from datetime import timedelta

from coral.engine import fold, transition
from coral.engine.classify import classify_failure
from coral.engine.facts import TurnSnapshot
from coral.engine.types import (
    EngineConfig,
    PauseCause,
    SessionFailed,
    StartRun,
    TimerDue,
    TimerPolicy,
    effect_key,
)
from coral.signals.facts import PLACEHOLDER_RUN_ID, PLACEHOLDER_SEQ, assign_effect_keys
from coral.signals.outcomes import outcomes
from tests.coral.engine.drive import NOW, drive
from tests.coral.workflow_builders import compile_text, fixture_text

RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1")
SLOT = "work||:0"
POLICY = TimerPolicy()
CFG = EngineConfig(timer_policy=POLICY)


def _started():
    graph = compile_text(fixture_text("minimal"))[0]
    assert not graph.analysis.unresolved, graph.analysis.unresolved
    return graph, drive(graph, [RUN], config=CFG)


def _no_account_switch(effects: tuple[object, ...]) -> None:
    for effect in effects:
        kind = effect.kind
        payload = effect.payload
        assert "account" not in kind
        assert all("account" not in key and "reset" not in key for key in payload)


def test_outcome_table_for_529_429_and_401() -> None:
    assert POLICY.infra_backoff == (
        timedelta(seconds=30),
        timedelta(minutes=2),
        timedelta(minutes=8),
    )
    cases = (
        (TurnSnapshot(status_code=529), "infra.transient", "529"),
        (TurnSnapshot(status_code=429), "plan.usage_limit", "429"),
        (TurnSnapshot(status_code=401), "auth", "401"),
    )
    for snapshot, name, cause in cases:
        assert classify_failure(snapshot).name == name
        assert classify_failure(snapshot).cause == cause
        table = outcomes(name, SLOT, NOW, POLICY)
        assert all(
            effect.effect_key
            == effect_key(PLACEHOLDER_RUN_ID, PLACEHOLDER_SEQ, effect.kind, effect.subject)
            for effect in table
        )
        _no_account_switch(table)

    transient = outcomes("infra.transient", SLOT, NOW, POLICY)
    assert [effect.kind for effect in transient] == ["arm_timer", "arm_timer", "arm_timer"]
    assert [effect.payload["kind"] for effect in transient] == ["infra_backoff"] * 3
    assert [effect.payload["stage"] for effect in transient] == [1, 2, 3]
    assert [effect.payload["due_at"] for effect in transient] == [
        (NOW + delay).isoformat() for delay in POLICY.infra_backoff
    ]

    limited = outcomes("plan.usage_limit", SLOT, NOW, POLICY)
    assert [effect.kind for effect in limited] == ["arm_timer"]
    assert limited[0].payload == {
        "kind": "plan_probe",
        "stage": 1,
        "due_at": (NOW + POLICY.plan_probe_start).isoformat(),
    }

    auth = outcomes("auth", SLOT, NOW, POLICY)
    assert [effect.kind for effect in auth] == ["notify"]
    assert auth[0].subject == SLOT
    assert auth[0].payload == {"kind": "pause"}


def test_spend_cap_matches_the_usage_limit_probe() -> None:
    classified = classify_failure(
        TurnSnapshot(error_text="credit balance is too low", status_code=429)
    )
    assert classified.name == "plan.spend_cap"
    assert outcomes("plan.spend_cap", SLOT, NOW, POLICY) == outcomes(
        "plan.usage_limit", SLOT, NOW, POLICY
    )
    graph, running = _started()
    applied = transition(
        graph,
        running.state,
        SessionFailed(
            slot_id=SLOT,
            failure_class="plan.spend_cap",
            cause=classified.cause,
            fact_key="turn:spend",
        ),
        NOW,
        CFG,
    )
    assert applied.entry.rejection is None
    run_id = applied.state.run_id
    assert isinstance(run_id, str)
    assert applied.entry.effects == assign_effect_keys(
        outcomes("plan.spend_cap", SLOT, NOW, POLICY), run_id, applied.state.seq
    )
    assert applied.state.status == "paused"
    assert applied.state.causes == (
        PauseCause(reason="plan_limit", detail="plan.spend_cap", subject=SLOT),
    )
    probes = [timer for timer in applied.state.timers if timer.kind == "plan_probe"]
    assert len(probes) == 1
    assert probes[0].due_at == NOW + POLICY.plan_probe_start
    _no_account_switch(applied.entry.effects)
    assert fold(graph, (*running.log, applied.entry), CFG) == applied.state


def test_started_run_applies_529_429_and_401_and_folds() -> None:
    graph, running = _started()
    run_id = running.state.run_id
    assert isinstance(run_id, str)

    transient = transition(
        graph,
        running.state,
        SessionFailed(
            slot_id=SLOT, failure_class="infra.transient", cause="529", fact_key="turn:529"
        ),
        NOW,
        CFG,
    )
    assert transient.entry.rejection is None
    assert transient.state.status == "running"
    assert transient.state.causes == ()
    assert transient.entry.effects == assign_effect_keys(
        outcomes("infra.transient", SLOT, NOW, POLICY), run_id, transient.state.seq
    )
    assert [timer.due_at.isoformat() for timer in transient.state.timers] == [
        effect.payload["due_at"] for effect in transient.entry.effects
    ]
    assert [timer.key for timer in transient.state.timers] == [
        effect.subject for effect in transient.entry.effects
    ]
    assert fold(graph, (*running.log, transient.entry), CFG) == transient.state

    limited = transition(
        graph,
        running.state,
        SessionFailed(
            slot_id=SLOT, failure_class="plan.usage_limit", cause="429", fact_key="turn:429"
        ),
        NOW,
        CFG,
    )
    assert limited.entry.rejection is None
    assert limited.state.status == "paused"
    assert limited.state.causes == (
        PauseCause(reason="plan_limit", detail="plan.usage_limit", subject=SLOT),
    )
    assert limited.entry.effects == assign_effect_keys(
        outcomes("plan.usage_limit", SLOT, NOW, POLICY), run_id, limited.state.seq
    )
    probes = [timer for timer in limited.state.timers if timer.kind == "plan_probe"]
    assert len(probes) == 1
    assert probes[0].stage == 1
    assert probes[0].due_at == NOW + POLICY.plan_probe_start
    _no_account_switch(limited.entry.effects)
    assert fold(graph, (*running.log, limited.entry), CFG) == limited.state

    cleared_at = probes[0].due_at
    due = transition(graph, limited.state, TimerDue(timer_key=probes[0].key), cleared_at, CFG)
    assert due.entry.rejection is None
    assert due.state.status == "running"
    assert due.state.causes == ()
    # The clear re-prompts the turn that hit the limit.
    assert [effect.kind for effect in due.entry.effects] == ["arm_timer", "nudge"]
    assert due.entry.effects[1].payload == {"fact_key": "turn:429", "reason": "resume"}
    nxt = next(timer for timer in due.state.timers if timer.kind == "plan_probe")
    assert nxt.stage == 2
    assert nxt.due_at == cleared_at + min(POLICY.plan_probe_start * 2, POLICY.plan_probe_cap)
    assert due.entry.effects[0].payload["due_at"] == nxt.due_at.isoformat()
    assert probes[0].key not in {timer.key for timer in due.state.timers}
    # With the pause gone, the next probe only disarms itself.
    stopped = transition(graph, due.state, TimerDue(timer_key=nxt.key), nxt.due_at, CFG)
    assert stopped.entry.effects == ()
    assert stopped.state.timers == ()
    assert stopped.state.status == "running"
    assert (
        fold(graph, (*running.log, limited.entry, due.entry, stopped.entry), CFG) == stopped.state
    )

    auth = transition(
        graph,
        running.state,
        SessionFailed(slot_id=SLOT, failure_class="auth", cause="401", fact_key="turn:401"),
        NOW,
        CFG,
    )
    assert auth.entry.rejection is None
    assert auth.state.status == "paused"
    assert auth.state.causes == (PauseCause(reason="auth", detail="auth", subject=SLOT),)
    assert auth.entry.effects == assign_effect_keys(
        outcomes("auth", SLOT, NOW, POLICY), run_id, auth.state.seq
    )
    assert [effect.kind for effect in auth.entry.effects] == ["notify"]
    assert auth.entry.effects[0].payload == {"kind": "pause"}
    _no_account_switch(auth.entry.effects)
    assert fold(graph, (*running.log, auth.entry), CFG) == auth.state
    duplicate = transition(
        graph,
        auth.state,
        SessionFailed(slot_id=SLOT, failure_class="auth", cause="401", fact_key="turn:401"),
        NOW,
        CFG,
    )
    assert duplicate.state == auth.state
    assert duplicate.entry.effects == ()
    assert duplicate.entry.receipt_key == "turn:401"


def test_agent_failed_pauses_failure_path_without_an_outbox_effect() -> None:
    assert outcomes("agent.failed", SLOT, NOW, POLICY) == ()
    graph, running = _started()
    applied = transition(
        graph,
        running.state,
        SessionFailed(
            slot_id=SLOT, failure_class="agent.failed", cause="agent.failed", fact_key="turn:agent"
        ),
        NOW,
        CFG,
    )
    assert applied.entry.rejection is None
    assert applied.entry.effects == ()
    assert applied.state.status == "paused"
    assert applied.state.causes == (
        PauseCause(reason="failure_path", detail="agent.failed", subject=SLOT),
    )
    assert fold(graph, (*running.log, applied.entry), CFG) == applied.state


def test_runner_lost_table_is_one_placeholder_the_reducer_does_not_copy() -> None:
    table = outcomes("infra.runner_lost", SLOT, NOW, POLICY)
    assert [effect.kind for effect in table] == ["runner_lost"]
    assert table[0].payload == {"session_id": "", "generation": 0}
