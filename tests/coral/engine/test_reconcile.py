"""Level-triggered reconcile. The same fact multiset reaches one state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from coral.engine import empty_state, fold, transition
from coral.engine.facts import TurnFact
from coral.engine.reconcile import reconcile
from coral.engine.types import (
    EffectCompleted,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    PauseCause,
    RunnerLost,
    SessionFailed,
    StartRun,
    TimerDue,
    TurnEnded,
    UsageLimited,
    WaitingWithoutElicitation,
)
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

CFG = EngineConfig()
RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1")
SLOT = "work||:0"
FACT_KEY = "turn:sess-1:1:resp-1"


def _graph(text: str | None = None):
    graph = compile_text(text if text is not None else fixture_text("minimal"))[0]
    assert not graph.analysis.unresolved, graph.analysis.unresolved
    return graph


def _fact(**overrides: object) -> TurnFact:
    payload: dict[str, object] = {
        "slot_id": SLOT,
        "live_status": "idle",
        "engine_stable_id_present": True,
        "newest_substantive_item_is_assistant": True,
        "turn_outcome": "completed",
        "saw_response_completed": True,
        "background_tasks": 0,
        "pending_elicitation_count": 0,
        "engine_pending_input": False,
        "origin": "engine",
        "engine_started": True,
        "session_id": "sess-1",
        "generation": 1,
        "response_id": "resp-1",
    }
    payload.update(overrides)
    return TurnFact(**payload)


def test_runner_grace_defaults_to_thirty_seconds() -> None:
    assert EngineConfig().runner_grace == timedelta(seconds=30)


def test_two_facts_with_one_key_are_one_turn_ended() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    alpha = _fact(error_text="alpha")
    beta = _fact(error_text="beta")
    forward = reconcile(running.state, (alpha, beta), NOW, CFG)
    backward = reconcile(running.state, (beta, alpha), NOW, CFG)
    ended = TurnEnded(slot_id=SLOT, fact_key=FACT_KEY)
    assert forward == backward == (ended,)
    assert running.state == drive(graph, [RUN], config=CFG).state

    def reach(commands: tuple[TurnEnded, ...]):
        state = running.state
        log = list(running.log)
        for command in commands:
            result = transition(graph, state, command, NOW, CFG)
            assert result.entry.rejection is None
            assert [effect.kind for effect in result.entry.effects] == ["nudge"]
            assert result.entry.effects[0].subject == command.slot_id
            assert result.entry.effects[0].payload == {"fact_key": command.fact_key}
            log.append(result.entry)
            state = result.state
            assert fold(graph, log, CFG) == state
        return state, tuple(log)

    left, left_log = reach(forward)
    right, _right_log = reach(backward)
    assert left == right
    slot = left.slots[0]
    assert slot.status == "evaluating"
    assert slot.handoff is None
    owner = next(item for item in left.activations if item.id == slot.activation_id)
    assert owner.status == "evaluating"
    assert left.status == "running"
    assert left.causes == ()

    assert reconcile(left, (alpha, beta), NOW, CFG) == ()
    assert reconcile(left, (beta, alpha), NOW, CFG) == ()
    second = transition(graph, left, ended, NOW, CFG)
    assert second.state == left
    assert second.entry.rejection is None
    assert second.entry.effects == ()
    assert second.entry.receipt_key == FACT_KEY
    assert fold(graph, (*left_log, second.entry), CFG) == left


def test_a_missing_generation_is_the_string_none() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    fact = _fact(generation=None, response_id=None, origin="user")
    command = TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:None:user", origin="user")
    assert reconcile(running.state, (fact,), NOW, CFG) == (command,)
    applied = transition(graph, running.state, command, NOW, CFG)
    assert applied.entry.rejection is None
    assert applied.entry.effects == ()
    assert applied.state.slots[0].status == "evaluating"
    assert fold(graph, (*running.log, applied.entry), CFG) == applied.state


def test_a_slot_with_no_session_effect_is_not_skipped() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    bare = running.state.model_copy(update={"effects": ()})
    assert reconcile(bare, (_fact(),), NOW, CFG) == (TurnEnded(slot_id=SLOT, fact_key=FACT_KEY),)


def test_unacked_send_input_suppresses_the_slot_until_it_completes() -> None:
    graph = _graph()
    started = transition(graph, empty_state(), RUN, NOW, CFG)
    create = started.entry.effects[0]
    assert create.kind == "create_session"
    created = transition(
        graph, started.state, EffectCompleted(effect_key=create.effect_key), NOW, CFG
    )
    brief = created.entry.effects[0]
    assert brief.kind == "send_input"
    assert reconcile(created.state, (_fact(),), NOW, CFG) == ()

    working = transition(
        graph, created.state, EffectCompleted(effect_key=brief.effect_key), NOW, CFG
    )
    assert working.state.slots[0].status == "working"
    emitted = reconcile(working.state, (_fact(),), NOW, CFG)
    assert emitted == (TurnEnded(slot_id=SLOT, fact_key=FACT_KEY),)
    applied = transition(graph, working.state, emitted[0], NOW, CFG)
    log = (started.entry, created.entry, working.entry, applied.entry)
    assert fold(graph, log, CFG) == applied.state


def test_a_stale_runner_emits_one_runner_lost_and_does_not_pause() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    stale = TurnFact(
        slot_id=SLOT,
        session_id="sess-1",
        generation=1,
        runner_last_seen=NOW - timedelta(seconds=31),
    )
    fresh = TurnFact(
        slot_id=SLOT,
        session_id="sess-1",
        generation=1,
        runner_last_seen=NOW,
    )
    boundary = TurnFact(
        slot_id=SLOT,
        session_id="sess-1",
        generation=1,
        runner_last_seen=NOW - CFG.runner_grace,
    )
    lost = RunnerLost(slot_id=SLOT, session_id="sess-1", generation=1)
    assert reconcile(running.state, (stale,), NOW, CFG) == (lost,)
    assert reconcile(running.state, (fresh,), NOW, CFG) == ()
    assert reconcile(running.state, (boundary,), NOW, CFG) == ()

    applied = transition(graph, running.state, lost, NOW, CFG)
    assert applied.entry.rejection is None
    assert [effect.kind for effect in applied.entry.effects] == ["runner_lost"]
    assert applied.entry.effects[0].subject == SLOT
    assert applied.entry.effects[0].payload == {"session_id": "sess-1", "generation": 1}
    assert applied.state.status == "running"
    assert applied.state.causes == ()
    assert applied.state.slots[0].status == "working"
    assert fold(graph, (*running.log, applied.entry), CFG) == applied.state
    assert reconcile(applied.state, (stale,), NOW, CFG) == ()

    duplicate = transition(graph, applied.state, lost, NOW, CFG)
    assert duplicate.state == applied.state
    assert duplicate.entry.effects == ()
    assert duplicate.entry.receipt_key == "runner:sess-1:1"
    assert fold(graph, (*running.log, applied.entry, duplicate.entry), CFG) == applied.state

    evaluating = drive(graph, [RUN, HandoffReceived(slot_id=SLOT, body="shipped")], config=CFG)
    assert evaluating.state.slots[0].status == "evaluating"
    assert reconcile(evaluating.state, (stale,), NOW, CFG) == ()


def test_usage_limited_pauses_plan_limit_and_arms_a_probe() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    command = UsageLimited(slot_id=SLOT, fact_key=FACT_KEY)
    paused = transition(graph, running.state, command, NOW, CFG)
    assert paused.entry.rejection is None
    assert [effect.kind for effect in paused.entry.effects] == ["arm_timer"]
    probe = next(timer for timer in paused.state.timers if timer.kind == "plan_probe")
    assert probe.stage == 1
    assert probe.subject == SLOT
    assert probe.due_at == NOW + CFG.timer_policy.plan_probe_start
    assert paused.entry.effects[0].payload == {
        "kind": "plan_probe",
        "stage": 1,
        "due_at": probe.due_at.isoformat(),
    }
    assert paused.entry.effects[0].subject == probe.key
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="plan_limit", detail="plan.usage_limit", subject=SLOT),
    )
    assert all(effect.kind != "notify" for effect in paused.state.effects)
    assert fold(graph, (*running.log, paused.entry), CFG) == paused.state

    duplicate = transition(graph, paused.state, command, NOW, CFG)
    assert duplicate.state == paused.state
    assert duplicate.entry.effects == ()
    assert duplicate.entry.receipt_key == FACT_KEY


def test_waiting_without_elicitation_is_an_audit_noop() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    waited = transition(
        graph,
        running.state,
        WaitingWithoutElicitation(slot_id=SLOT, fact_key=FACT_KEY),
        NOW,
        CFG,
    )
    assert waited.state == running.state
    assert waited.entry.rejection is None
    assert waited.entry.effects == ()
    assert waited.state.status == "running"
    assert waited.state.causes == ()
    assert fold(graph, (*running.log, waited.entry), CFG) == running.state


def test_runner_lost_emits_one_effect_and_agent_failed_pauses() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    fact = _fact(turn_outcome="failed", failure_origin="runner_disconnected")
    failure = SessionFailed(
        slot_id=SLOT,
        failure_class="infra.runner_lost",
        cause="runner_disconnected",
        fact_key=FACT_KEY,
    )
    assert reconcile(running.state, (fact,), NOW, CFG) == (failure,)
    lost = transition(graph, running.state, failure, NOW, CFG)
    assert lost.entry.rejection is None
    assert [effect.kind for effect in lost.entry.effects] == ["runner_lost"]
    assert lost.entry.effects[0].subject == SLOT
    assert lost.entry.effects[0].payload == {"session_id": "sess-1", "generation": 1}
    assert lost.state.status == "running"
    assert lost.state.causes == ()
    assert all(timer.kind != "infra_backoff" for timer in lost.state.timers)
    assert fold(graph, (*running.log, lost.entry), CFG) == lost.state
    assert reconcile(lost.state, (fact,), NOW, CFG) == ()
    duplicate = transition(graph, lost.state, failure, NOW, CFG)
    assert duplicate.state == lost.state
    assert duplicate.entry.effects == ()
    assert duplicate.entry.receipt_key == FACT_KEY

    parsed = transition(
        graph,
        running.state,
        SessionFailed(
            slot_id=SLOT,
            failure_class="infra.runner_lost",
            cause="runner_disconnected",
            fact_key="turn:sess-9:4:engine",
        ),
        NOW,
        CFG,
    )
    assert parsed.entry.effects[0].payload == {"session_id": "sess-9", "generation": 4}
    assert parsed.state.status == "running"
    assert parsed.state.causes == ()

    colon_tail = _fact(
        turn_outcome="failed",
        failure_origin="runner_disconnected",
        session_id="11111111-1111-1111-1111-111111111111",
        generation=2,
        response_id="kimi:turn:0",
    )
    emitted = reconcile(running.state, (colon_tail,), NOW, CFG)
    assert len(emitted) == 1
    command = emitted[0]
    assert isinstance(command, SessionFailed)
    assert command.fact_key == "turn:11111111-1111-1111-1111-111111111111:2:kimi:turn:0"
    kept = transition(graph, running.state, command, NOW, CFG)
    assert kept.entry.effects[0].payload == {
        "session_id": "11111111-1111-1111-1111-111111111111",
        "generation": 2,
    }
    assert kept.state.status == "running"
    assert kept.state.causes == ()
    assert fold(graph, (*running.log, kept.entry), CFG) == kept.state

    failed = transition(
        graph,
        running.state,
        SessionFailed(
            slot_id=SLOT, failure_class="agent.failed", cause="agent.failed", fact_key="other"
        ),
        NOW,
        CFG,
    )
    assert failed.entry.rejection is None
    assert failed.entry.effects == ()
    assert failed.state.status == "paused"
    assert failed.state.causes == (
        PauseCause(reason="failure_path", detail="agent.failed", subject=SLOT),
    )
    assert failed.entry.receipt_key == "other"
    assert fold(graph, (*running.log, failed.entry), CFG) == failed.state
    duplicate_failure = transition(
        graph,
        failed.state,
        SessionFailed(
            slot_id=SLOT, failure_class="agent.failed", cause="agent.failed", fact_key="other"
        ),
        NOW,
        CFG,
    )
    assert duplicate_failure.state == failed.state
    assert duplicate_failure.entry.effects == ()
    assert duplicate_failure.entry.receipt_key == "other"


def test_one_runner_loss_fact_emits_one_effect() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    fact = _fact(
        turn_outcome="failed",
        failure_origin="runner_disconnected",
        runner_last_seen=NOW - timedelta(seconds=31),
        response_id="kimi:turn:0",
    )
    emitted = reconcile(running.state, (fact,), NOW, CFG)
    assert [command.kind for command in emitted] == ["runner_lost", "session_failed"]

    def apply(commands: tuple[object, ...]) -> list[str]:
        state = running.state
        log = list(running.log)
        kinds: list[str] = []
        for command in commands:
            result = transition(graph, state, command, NOW, CFG)
            assert result.entry.rejection is None
            kinds.extend(effect.kind for effect in result.entry.effects)
            log.append(result.entry)
            state = result.state
            assert fold(graph, log, CFG) == state
        assert reconcile(state, (fact,), NOW, CFG) == ()
        return kinds

    assert apply(emitted) == ["runner_lost"]
    assert apply(tuple(reversed(emitted))) == ["runner_lost"]


def test_turn_ended_refuses_a_closed_or_unknown_slot() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work", roster=["implementer", "reviewer"]), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )
    closed = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="shipped"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        config=CFG,
    )
    assert closed.state.status == "running"
    assert closed.state.slots[0].status == "closed"
    refused = transition(graph, closed.state, TurnEnded(slot_id=SLOT, fact_key=FACT_KEY), NOW, CFG)
    assert refused.state == closed.state
    assert refused.entry.rejection is not None
    assert refused.entry.rejection.code == "slot.closed"

    running = drive(graph, [RUN], config=CFG)
    missing = transition(
        graph, running.state, TurnEnded(slot_id="missing", fact_key=FACT_KEY), NOW, CFG
    )
    assert missing.state == running.state
    assert missing.entry.rejection is not None
    assert missing.entry.rejection.code == "rejected"

    evaluating = drive(graph, [RUN, HandoffReceived(slot_id=SLOT, body="shipped")], config=CFG)
    assert evaluating.state.slots[0].status == "evaluating"
    busy = transition(
        graph, evaluating.state, TurnEnded(slot_id=SLOT, fact_key="turn:other"), NOW, CFG
    )
    assert busy.state == evaluating.state
    assert busy.entry.rejection is not None
    assert busy.entry.rejection.code == "rejected"


def test_transient_failure_receipts_the_fact_so_reconcile_goes_empty() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    fact = _fact(turn_outcome="failed", status_code=529)
    command = SessionFailed(
        slot_id=SLOT, failure_class="infra.transient", cause="529", fact_key=FACT_KEY
    )
    assert reconcile(running.state, (fact,), NOW, CFG) == (command,)
    failed = transition(graph, running.state, command, NOW, CFG)
    assert failed.entry.rejection is None
    assert failed.state.status == "running"
    assert [timer.stage for timer in failed.state.timers] == [1, 2, 3]
    assert reconcile(failed.state, (fact,), NOW, CFG) == ()
    due = transition(graph, failed.state, TimerDue(timer_key=failed.state.timers[0].key), NOW, CFG)
    assert [timer.stage for timer in due.state.timers] == [2, 3]
    later = NOW + timedelta(hours=1)
    again = transition(graph, due.state, command, later, CFG)
    assert again.entry.receipt_key == FACT_KEY
    assert again.entry.effects == ()
    assert again.state == due.state
    assert reconcile(again.state, (fact,), later, CFG) == ()
    assert fold(graph, (*running.log, failed.entry, due.entry, again.entry), CFG) == again.state


def test_a_naive_now_raises() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    with pytest.raises(ValueError, match="timezone-aware"):
        reconcile(running.state, (), datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None), CFG)
