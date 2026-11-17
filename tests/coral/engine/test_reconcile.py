"""Level-triggered reconcile. The same fact multiset reaches one state."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from coral.engine import empty_state, fold, transition
from coral.engine.facts import TurnFact
from coral.engine.reconcile import awaiting_effect, reconcile
from coral.engine.types import (
    EffectCompleted,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    PauseCause,
    ResumeRun,
    RunnerLost,
    SessionFailed,
    StartRun,
    TimerDue,
    TurnEnded,
    UsageLimited,
    WaitingWithoutElicitation,
)
from coral.model.ir import CompiledGraph
from tests.coral.engine.drive import NOW, Driven, drive
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


@pytest.mark.parametrize("kind", ["send_input", "nudge"])
def test_an_unacked_leased_effect_suppresses_the_slot_until_it_completes(kind: str) -> None:
    graph = _graph()
    if kind == "send_input":
        started = transition(graph, empty_state(), RUN, NOW, CFG)
        create = started.entry.effects[0]
        assert create.kind == "create_session"
        created = transition(
            graph, started.state, EffectCompleted(effect_key=create.effect_key), NOW, CFG
        )
        log = [started.entry, created.entry]
        state = created.state
        fact = _fact()
    else:
        ended = drive(graph, [RUN, TurnEnded(slot_id=SLOT, fact_key=FACT_KEY)], config=CFG)
        log = list(ended.log)
        state = ended.state
        fact = _fact(response_id="resp-2")
    leased = next(effect for effect in reversed(state.effects) if effect.kind == kind)
    assert awaiting_effect(state, SLOT)
    assert reconcile(state, (fact,), NOW, CFG) == ()

    working = transition(graph, state, EffectCompleted(effect_key=leased.effect_key), NOW, CFG)
    assert working.state.slots[0].status == "working"
    assert not awaiting_effect(working.state, SLOT)
    emitted = reconcile(working.state, (fact,), NOW, CFG)
    fact_key = f"turn:sess-1:1:{fact.response_id}"
    assert emitted == (TurnEnded(slot_id=SLOT, fact_key=fact_key),)
    applied = transition(graph, working.state, emitted[0], NOW, CFG)
    assert fold(graph, (*log, working.entry, applied.entry), CFG) == applied.state


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
    assert [timer.stage for timer in lost.state.timers if timer.kind == "infra_backoff"] == [
        1,
        2,
        3,
    ]
    assert lost.state.slots[0].failed_turn == FACT_KEY
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
    stage_one = failed.state.timers[0]
    due = transition(graph, failed.state, TimerDue(timer_key=stage_one.key), stage_one.due_at, CFG)
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


def test_a_second_runner_loss_of_one_session_arms_the_ladder_again() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    lost = _at(graph, running, [_runner_lost("a")], NOW)
    assert [effect.kind for effect in lost.log[-1].effects] == ["runner_lost"]
    assert lost.state.slots[0].failed_turn == "turn:sess-1:1:msg:a"
    first, _second, _third = lost.state.timers

    # Stage 1 re-prompts, and the re-prompted turn completes: a recovery.
    nudged = _at(graph, lost, [TimerDue(timer_key=first.key)], first.due_at)
    recovered = _at(
        graph,
        _delivered(graph, nudged, first.due_at),
        [TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:msg:b")],
        first.due_at,
    )
    assert recovered.state.timers == ()
    assert recovered.state.slots[0].failed_turn is None
    working = _delivered(graph, recovered, first.due_at)

    # The same session and generation is lost again later: only the fact's receipt, no second
    # runner_lost, but the ladder is armed and the slot marked like the first time.
    later = first.due_at + timedelta(hours=1)
    again = _at(graph, working, [_runner_lost("c")], later)
    entry = again.log[-1]
    assert (entry.rejection, entry.effects, entry.receipt_key) == (
        None,
        (),
        "turn:sess-1:1:msg:c",
    )
    assert again.state.slots[0].failed_turn == "turn:sess-1:1:msg:c"
    first, second, third = again.state.timers
    assert [timer.due_at for timer in (first, second, third)] == [
        later + delay for delay in CFG.timer_policy.infra_backoff
    ]

    # The slot keeps failing after each re-prompt, so stage 3 pauses infra.
    retried = _delivered(
        graph, _at(graph, again, [TimerDue(timer_key=first.key)], first.due_at), first.due_at
    )
    failing = _at(graph, retried, [_runner_lost("d")], first.due_at + timedelta(seconds=1))
    assert failing.log[-1].effects == ()
    assert failing.state.timers == (second, third)
    retried = _delivered(
        graph, _at(graph, failing, [TimerDue(timer_key=second.key)], second.due_at), second.due_at
    )
    failing = _at(graph, retried, [_runner_lost("e")], second.due_at + timedelta(seconds=1))
    paused = _at(graph, failing, [TimerDue(timer_key=third.key)], third.due_at)
    assert paused.state.status == "paused"
    assert paused.state.causes == (
        PauseCause(reason="infra", detail="infra.transient", subject=SLOT),
    )

    resumed = _at(graph, paused, [ResumeRun()], third.due_at)
    assert [(effect.kind, effect.payload) for effect in resumed.log[-1].effects] == [
        ("nudge", {"fact_key": "turn:sess-1:1:msg:e", "reason": "resume"})
    ]


def _runner_lost(tail: str) -> SessionFailed:
    return SessionFailed(
        slot_id=SLOT,
        failure_class="infra.runner_lost",
        cause="runner_disconnected",
        fact_key=f"turn:sess-1:1:msg:{tail}",
    )


def _at(graph: CompiledGraph, driven: Driven, commands: Sequence[Input], now: datetime) -> Driven:
    return drive(graph, commands, config=CFG, after=driven, now=now)


def _delivered(graph: CompiledGraph, driven: Driven, now: datetime) -> Driven:
    """Complete the newest nudge, as its send would."""
    nudge = next(effect for effect in reversed(driven.state.effects) if effect.kind == "nudge")
    return _at(graph, driven, [EffectCompleted(effect_key=nudge.effect_key)], now)
