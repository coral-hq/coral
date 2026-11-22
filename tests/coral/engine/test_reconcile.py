"""Level-triggered reconcile. The same fact multiset reaches one state."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue

from coral.engine import empty_state, fold, transition
from coral.engine.facts import TurnFact
from coral.engine.reconcile import awaiting_effect, reconcile
from coral.engine.types import (
    RULES,
    EffectCompleted,
    EffectFailed,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    PauseCause,
    ResumeRun,
    RetryStep,
    RunnerHeld,
    RunnerHoldEnded,
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
RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1", rules=RULES)
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
    lost = RunnerLost(
        slot_id=SLOT,
        session_id="sess-1",
        generation=1,
        fact_key="turn:sess-1:1:None",
        observed_at=stale.runner_last_seen,
    )
    assert reconcile(running.state, (stale,), NOW, CFG) == (lost,)
    assert reconcile(running.state, (fresh,), NOW, CFG) == ()
    assert reconcile(running.state, (boundary,), NOW, CFG) == ()

    applied = transition(graph, running.state, lost, NOW, CFG)
    assert applied.entry.rejection is None
    assert [effect.kind for effect in applied.entry.effects] == ["runner_lost"]
    assert applied.entry.effects[0].subject == SLOT
    assert applied.entry.effects[0].payload == {
        "session_id": "sess-1",
        "generation": 1,
        "runner_id": None,
    }
    assert applied.state.status == "running"
    assert applied.state.causes == ()
    slot = applied.state.slots[0]
    # Like an edge, the loss marks the turn it interrupted; its wake replaces the ladder.
    assert (slot.status, slot.failed_turn, slot.wakes) == ("working", "turn:sess-1:1:None", 1)
    assert applied.state.timers == ()
    assert fold(graph, (*running.log, applied.entry), CFG) == applied.state
    assert reconcile(applied.state, (stale,), NOW, CFG) == ()

    duplicate = transition(graph, applied.state, lost, NOW, CFG)
    assert duplicate.state == applied.state
    assert duplicate.entry.effects == ()
    assert duplicate.entry.receipt_key == "runner:sess-1:1:turn:None:0"
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


def test_usage_limited_with_resets_at_pins_plan_probe_due() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    resets_at = NOW.timestamp() + 3600
    command = UsageLimited(slot_id=SLOT, fact_key=FACT_KEY, resets_at=resets_at)
    paused = transition(graph, running.state, command, NOW, CFG)
    probe = next(timer for timer in paused.state.timers if timer.kind == "plan_probe")
    assert probe.due_at == datetime.fromtimestamp(resets_at, tz=UTC) + timedelta(seconds=60)


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
    assert lost.entry.effects[0].payload == {
        "session_id": "sess-1",
        "generation": 1,
        "runner_id": None,
    }
    assert lost.state.status == "running"
    assert lost.state.causes == ()
    assert [timer for timer in lost.state.timers if timer.kind == "infra_backoff"] == []
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
    assert parsed.entry.effects[0].payload == {
        "session_id": "sess-9",
        "generation": 4,
        "runner_id": None,
    }
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
        "runner_id": None,
    }
    assert kept.entry.receipt_key == (
        "runner:11111111-1111-1111-1111-111111111111:2:turn:kimi:turn:0:0"
    )
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


def test_a_runner_reported_again_while_its_wake_is_out_arms_nothing_and_a_later_loss_wakes() -> (
    None
):
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    lost = _at(graph, running, [_runner_lost("a")], NOW)
    (wake,) = lost.log[-1].effects
    assert wake.kind == "runner_lost"
    assert (lost.state.slots[0].failed_turn, lost.state.timers) == ("turn:sess-1:1:msg:a", ())

    # The same runner is reported again while its wake is out: only the fact's receipt.
    again = _at(graph, lost, [_runner_lost("c")], NOW + timedelta(seconds=5))
    entry = again.log[-1]
    assert (entry.rejection, entry.effects, entry.receipt_key) == (
        None,
        (),
        "turn:sess-1:1:msg:c",
    )
    assert (again.state.slots[0].failed_turn, again.state.timers) == ("turn:sess-1:1:msg:c", ())

    # The wake finds the runner back and idle: one re-prompt, then a later loss is new.
    back = {"outcome": "runner_back", "turn_running": False}
    woken = _at(graph, again, [EffectCompleted(effect_key=wake.effect_key, payload=back)], NOW)
    assert [effect.kind for effect in woken.log[-1].effects] == ["nudge"]
    later = _at(
        graph, _delivered(graph, woken, NOW), [_runner_lost("d")], NOW + timedelta(hours=1)
    )
    assert [effect.kind for effect in later.log[-1].effects] == ["runner_lost"]
    assert later.state.timers == ()


def _runner_lost(tail: str, runner_id: str | None = "runner-1") -> SessionFailed:
    return SessionFailed(
        slot_id=SLOT,
        failure_class="infra.runner_lost",
        cause="runner_disconnected",
        fact_key=f"turn:sess-1:1:msg:{tail}",
        runner_id=runner_id,
    )


def _at(graph: CompiledGraph, driven: Driven, commands: Sequence[Input], now: datetime) -> Driven:
    return drive(graph, commands, config=CFG, after=driven, now=now)


def _delivered(graph: CompiledGraph, driven: Driven, now: datetime) -> Driven:
    """Complete the newest nudge, as its send would."""
    nudge = next(effect for effect in reversed(driven.state.effects) if effect.kind == "nudge")
    return _at(graph, driven, [EffectCompleted(effect_key=nudge.effect_key)], now)


def _liveness(runner_id: str | None) -> TurnFact:
    """A liveness-only fact: the pass saw the slot's runner missing past its grace."""
    return TurnFact(
        slot_id=SLOT,
        session_id="sess-1",
        generation=1,
        runner_id=runner_id,
        runner_last_seen=NOW - timedelta(seconds=91),
    )


def _edge(runner_id: str | None, tail: str = "resp-1") -> TurnFact:
    """An edge fact: Omnigent failed the turn because the runner disconnected."""
    return _fact(
        turn_outcome="failed",
        failure_origin="runner_disconnected",
        response_id=tail,
        runner_id=runner_id,
    )


def _observe(graph: CompiledGraph, driven: Driven, facts: Sequence[TurnFact]) -> Driven:
    """Reconcile each fact in turn and apply what it yields, as the bridge's resync does."""
    for fact in facts:
        driven = _at(graph, driven, reconcile(driven.state, (fact,), NOW, CFG), NOW)
    return driven


def _wakes(driven: Driven, since: int) -> list[dict[str, object]]:
    return [
        dict(effect.payload)
        for entry in driven.log[since:]
        for effect in entry.effects
        if effect.kind == "runner_lost"
    ]


@pytest.mark.parametrize("liveness_first", [True, False], ids=["liveness_then_edge", "edge_first"])
def test_a_liveness_loss_and_an_edge_for_one_runner_are_one_loss(liveness_first: bool) -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    facts = [_liveness("r1"), _edge("r1")]

    observed = _observe(graph, running, facts if liveness_first else facts[::-1])

    assert _wakes(observed, len(running.log)) == [
        {"session_id": "sess-1", "generation": 1, "runner_id": "r1"}
    ]
    assert observed.state.slots[0].wakes == 1
    assert any(item.key == "runner:sess-1:1:r1:0" for item in observed.state.receipts)
    assert all(reconcile(observed.state, (fact,), NOW, CFG) == () for fact in facts)


def test_a_loss_of_another_runner_in_the_same_generation_is_a_new_loss() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)

    observed = _observe(graph, running, [_liveness("r1"), _edge("r2"), _liveness("r2")])

    assert [wake["runner_id"] for wake in _wakes(observed, len(running.log))] == ["r1", "r2"]
    assert observed.state.slots[0].wakes == 2


def test_two_slots_losing_their_runners_in_one_pass_reach_one_log_in_any_fact_order() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work", roster=["implementer", "reviewer"]), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )
    running = drive(graph, [RUN], config=CFG)
    other = {"slot_id": "work||:1", "session_id": "sess-2"}
    # Each runner is reported by both detectors in the same pass.
    facts = [
        _liveness("r1"),
        _edge("r1"),
        _liveness("r2").model_copy(update=other),
        _edge("r2", "resp-2").model_copy(update=other),
    ]
    logs = set()
    for order in itertools.permutations(facts):
        applied = _at(graph, running, reconcile(running.state, order, NOW, CFG), NOW)
        logs.add(tuple(entry.model_dump_json() for entry in applied.log))

    assert len(logs) == 1
    assert sorted(
        (effect.subject, effect.payload["runner_id"])
        for effect in applied.state.effects
        if effect.kind == "runner_lost"
    ) == [(SLOT, "r1"), ("work||:1", "r2")]
    assert [slot.wakes for slot in applied.state.slots] == [1, 1]


def test_an_edge_without_a_runner_id_keys_its_loss_by_the_response_tail() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)

    observed = _observe(graph, running, [_edge(None, "resp-a"), _edge(None, "resp-b")])

    assert len(_wakes(observed, len(running.log))) == 2
    keys = {item.key for item in observed.state.receipts if item.key.startswith("runner:")}
    assert keys == {"runner:sess-1:1:turn:resp-a:0", "runner:sess-1:1:turn:resp-b:0"}


def test_a_fourth_loss_of_one_generation_pauses_instead_of_waking() -> None:
    graph = _graph()
    driven = drive(graph, [RUN], config=CFG)
    for count, runner_id in enumerate(("r1", "r2", "r3"), start=1):
        driven = _observe(graph, driven, [_liveness(runner_id)])
        assert [effect.kind for effect in driven.log[-1].effects] == ["runner_lost"]
        assert driven.state.slots[0].wakes == count
    assert driven.state.status == "running"

    fourth = _observe(graph, driven, [_liveness("r4")])

    entry = fourth.log[-1]
    assert (entry.rejection, entry.effects, entry.receipt_key) == (
        None,
        (),
        "runner:sess-1:1:r4:0",
    )
    assert (fourth.state.status, fourth.state.causes) == (
        "paused",
        (PauseCause(reason="infra", detail="infra.runner_lost", subject=SLOT),),
    )
    slot = fourth.state.slots[0]
    assert (slot.wakes, slot.failed_turn) == (3, "turn:sess-1:1:None")
    # The pause replaces the ladder: no stage re-prompts the slot while it waits.
    assert all(timer.kind != "infra_backoff" for timer in fourth.state.timers)
    assert reconcile(fourth.state, (_liveness("r4"),), NOW, CFG) == ()

    resumed = _at(graph, fourth, [ResumeRun()], NOW)
    assert [(effect.kind, effect.payload) for effect in resumed.log[-1].effects] == [
        ("nudge", {"fact_key": "turn:sess-1:1:None", "reason": "resume"})
    ]
    retried = _at(graph, fourth, [RetryStep(node_id="work")], NOW)
    assert (retried.state.slots[0].wakes, retried.state.slots[0].session_generation) == (0, 2)


def _woken(
    graph: CompiledGraph,
    driven: Driven,
    outcome: str,
    *,
    running: bool,
    seen_at: datetime | None = None,
) -> Driven:
    """Complete the newest wake with ``outcome``, as the wake row reports it."""
    wake = next(
        effect for effect in reversed(driven.state.effects) if effect.kind == "runner_lost"
    )
    payload: dict[str, JsonValue] = {"outcome": outcome, "turn_running": running}
    if seen_at is not None:
        payload["seen_at"] = seen_at.isoformat()
    result = EffectCompleted(effect_key=wake.effect_key, payload=payload)
    return _at(graph, driven, [result], NOW)


def test_a_runner_lost_again_after_it_came_back_is_a_new_loss() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    lost = _observe(graph, running, [_liveness("r1")])
    back = _woken(graph, lost, "runner_back", running=True)
    assert back.state.slots[0].connection_epoch == 1
    # The same runner process reconnected; a second outage of it is not the first one.
    assert reconcile(back.state, (_liveness("r1"),), NOW, CFG) == (
        RunnerLost(
            slot_id=SLOT,
            session_id="sess-1",
            generation=1,
            runner_id="r1",
            fact_key="turn:sess-1:1:None",
            observed_at=NOW - timedelta(seconds=91),
        ),
    )

    again = _observe(graph, back, [_liveness("r1"), _edge("r1", "resp-2")])

    assert [wake["runner_id"] for wake in _wakes(again, len(running.log))] == ["r1", "r1"]
    assert again.state.slots[0].wakes == 2
    keys = [item.key for item in again.state.receipts if item.key.startswith("runner:")]
    assert keys == ["runner:sess-1:1:r1:0", "runner:sess-1:1:r1:1"]


def test_one_sleep_held_across_its_edge_is_one_loss_and_the_next_outage_is_new() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    asleep = _observe(graph, running, [_liveness("r1")])
    held = _at(graph, asleep, [RunnerHeld(slot_id=SLOT, session_id="sess-1", generation=1)], NOW)
    # The host comes back without the runner: Omnigent's edge reports the same outage.
    interrupted = _observe(graph, held, [_edge("r1", "resp-1")])
    assert len(_wakes(interrupted, len(running.log))) == 1
    assert interrupted.state.timers == ()
    woken = _woken(
        graph,
        _at(graph, interrupted, [RunnerHoldEnded(slot_id=SLOT, generation=1)], NOW),
        "relaunched",
        running=False,
    )
    assert [effect.kind for effect in woken.log[-1].effects] == ["nudge"]

    # The relaunched runner's own outage, once its re-prompt is delivered, is a new loss.
    later = _observe(graph, _delivered(graph, woken, NOW), [_liveness("r2")])

    assert len(_wakes(later, len(running.log))) == 2


def test_the_same_runners_edge_after_the_fourth_loss_arms_no_ladder_and_adds_no_cause() -> None:
    graph = _graph()
    driven = drive(graph, [RUN], config=CFG)
    for runner_id in ("r1", "r2", "r3", "r4"):
        driven = _observe(graph, driven, [_liveness(runner_id)])
    paused = driven.state
    lost = PauseCause(reason="infra", detail="infra.runner_lost", subject=SLOT)
    assert paused.causes == (lost,)
    assert all(timer.kind != "infra_backoff" for timer in paused.timers)

    edged = _observe(graph, driven, [_edge("r4", "resp-4")])

    assert edged.log[-1].effects == ()
    assert edged.state.causes == (lost,)
    assert all(timer.kind != "infra_backoff" for timer in edged.state.timers)
    assert edged.state.slots[0].failed_turn == "turn:sess-1:1:resp-4"


def test_resuming_the_fourth_loss_pause_or_a_wake_that_gave_up_ends_the_outage() -> None:
    graph = _graph()
    driven = drive(graph, [RUN], config=CFG)
    for runner_id in ("r1", "r2", "r3", "r4"):
        driven = _observe(graph, driven, [_liveness(runner_id)])
    resumed = _delivered(graph, _at(graph, driven, [ResumeRun()], NOW), NOW)
    assert resumed.state.slots[0].connection_epoch == 1
    # The same runner missing again after its re-prompt pauses again, not silently.
    again = _observe(graph, resumed, [_liveness("r4")])
    assert again.state.causes == (
        PauseCause(reason="infra", detail="infra.runner_lost", subject=SLOT),
    )

    running = drive(graph, [RUN], config=CFG)
    lost = _observe(graph, running, [_liveness("r1")])
    wake = next(effect for effect in lost.state.effects if effect.kind == "runner_lost")
    gave_up = _at(
        graph,
        lost,
        [EffectFailed(effect_key=wake.effect_key, code="recovery.runner_alive", retryable=True)],
        NOW,
    )
    assert gave_up.state.slots[0].connection_epoch == 1
    assert gave_up.state.causes == (
        PauseCause(reason="infra", detail="recovery.runner_alive", subject=SLOT),
    )
    resumed = _delivered(graph, _at(graph, gave_up, [ResumeRun()], NOW), NOW)
    rewoken = _observe(graph, resumed, [_liveness("r1")])
    assert len(_wakes(rewoken, len(running.log))) == 2


def test_an_edge_that_lands_after_its_wake_saw_the_runner_back_is_not_a_second_loss() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    lost = _observe(graph, running, [_liveness("r1")])
    back = _delivered(graph, _woken(graph, lost, "runner_back", running=False, seen_at=NOW), NOW)
    late = _edge("r1", "resp-1").model_copy(update={"observed_at": NOW - timedelta(seconds=30)})

    landed = _observe(graph, back, [late])

    # Omnigent's edge for the outage the wake already handled only records its receipt.
    assert len(_wakes(landed, len(running.log))) == 1
    assert landed.state.slots == back.state.slots
    assert landed.state.timers == back.state.timers
    # The same runner's edge observed after it came back is a new outage.
    later = _edge("r1", "resp-2").model_copy(update={"observed_at": NOW + timedelta(seconds=60)})
    assert len(_wakes(_observe(graph, landed, [later]), len(running.log))) == 2


def test_a_lost_runners_report_that_lands_after_its_relaunch_is_not_a_second_loss() -> None:
    graph = _graph()
    running = drive(graph, [RUN], config=CFG)
    lost = _observe(graph, running, [_liveness("r1")])
    relaunched = _delivered(
        graph, _woken(graph, lost, "relaunched", running=False, seen_at=NOW), NOW
    )
    assert relaunched.state.slots[0].retired_runners == ("r1",)

    # A liveness read of the old runner taken before the relaunch, then its edge, both land late.
    late = [_liveness("r1"), _edge("r1", "resp-9")]
    assert reconcile(relaunched.state, late[:1], NOW, CFG) == ()
    landed = _observe(graph, relaunched, late)

    assert len(_wakes(landed, len(running.log))) == 1
    assert landed.state.slots == relaunched.state.slots
    # The relaunched runner's own outage, seen after the relaunch, still wakes the step.
    missing = _liveness("r2").model_copy(update={"runner_last_seen": NOW + timedelta(seconds=10)})
    later = NOW + timedelta(seconds=120)
    found = reconcile(landed.state, (missing,), later, CFG)
    assert len(_wakes(_at(graph, landed, found, later), len(running.log))) == 2
