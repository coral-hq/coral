"""Skeleton replay, a duplicate effect completion, and replaying a full log twice."""

from __future__ import annotations

from datetime import timedelta

from coral.engine import empty_state, fold, transition
from coral.engine.types import (
    EffectCompleted,
    EffectFailed,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    PauseRun,
    ResumeRun,
    SessionFailed,
    StartRun,
    TimerDue,
    TurnEnded,
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

CONFIG = EngineConfig()
RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1")
SLOT = "work||:0"


def test_skeleton_reaches_completed_and_fold_matches() -> None:
    graph = compile_text(fixture_text("minimal"))[0]
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="shipped"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        config=CONFIG,
    )
    assert driven.state.status == "completed"
    assert driven.state.max_activations == 10_000
    assert fold(graph, driven.log, CONFIG) == driven.state
    assert [entry.now for entry in driven.log] == [NOW] * len(driven.log)

    kinds = [
        (entry.input.kind, tuple(effect.kind for effect in entry.effects)) for entry in driven.log
    ]
    assert kinds == [
        ("start_run", ("create_session",)),
        ("effect_completed", ("send_input",)),
        ("effect_completed", ()),
        ("handoff_received", ()),
        ("handoff_evaluated", ("close_slot",)),
        ("effect_completed", ()),
    ]
    create = driven.log[0].effects[0]
    assert create.effect_key == f"run-1:{driven.log[0].seq}:create_session:{SLOT}"
    assert create.subject == SLOT
    brief = driven.log[1].effects[0]
    assert brief.kind == "send_input"
    assert brief.effect_key == f"run-1:{driven.log[1].seq}:send_input:{SLOT}"
    close = driven.log[4].effects[0]
    assert close.payload == {"interrupt": True, "closed_label": True}
    assert close.effect_key == f"run-1:{driven.log[4].seq}:close_slot:{SLOT}"
    assert driven.log[-1].effects == ()
    assert {item.id: (item.status, item.outcome) for item in driven.state.activations} == {
        "start||": ("closed", "completed"),
        "work||": ("closed", "completed"),
        "end||": ("closed", "completed"),
    }
    assert driven.state.slots[0].status == "closed"
    assert driven.log[0].patch
    assert all(op.path.startswith("/") for op in driven.log[0].patch)


def test_replaying_a_nudged_labelled_run_repeats_every_entry() -> None:
    graph = compile_text(
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
    )[0]
    ended = drive(graph, [RUN, TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:r1")])
    first_nudge = ended.log[-1].effects[0].effect_key
    nudged = drive(
        graph,
        [
            EffectCompleted(effect_key=first_nudge),
            TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:r2"),
        ],
        after=ended,
    )
    closing = drive(
        graph,
        [
            EffectCompleted(effect_key=nudged.log[-1].effects[0].effect_key),
            HandoffReceived(slot_id=SLOT, body="guess", label="nope"),
            HandoffReceived(slot_id=SLOT, body="partial", label="broken"),
            HandoffEvaluated(slot_id=SLOT, outcome="evidence_missing", missing=("tests",)),
            HandoffReceived(slot_id=SLOT, body="done", label="ok"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        after=nudged,
        auto_ack=False,
    )
    close = closing.log[-1].effects[0].effect_key
    finished = drive(
        graph,
        [
            PauseRun(reason="user", detail="hold"),
            EffectCompleted(effect_key=close, payload={"pending_input": False}),
            ResumeRun(),
            HandoffReceived(slot_id="ship||:0", body="shipped"),
            HandoffEvaluated(slot_id="ship||:0", outcome="accepted"),
        ],
        after=closing,
    )
    assert finished.state.status == "completed"
    assert [entry.rejection.code for entry in finished.log if entry.rejection] == [
        "handoff.invalid"
    ]

    for _replay in range(2):
        state = empty_state()
        replayed = []
        for entry in finished.log:
            result = transition(graph, state, entry.input, NOW, CONFIG)
            replayed.append(result.entry)
            state = result.state
        assert tuple(replayed) == finished.log
        assert state == finished.state
    assert fold(graph, finished.log, CONFIG) == fold(graph, finished.log, CONFIG)


def test_duplicate_effect_completed_returns_receipt() -> None:
    graph = compile_text(fixture_text("minimal"))[0]
    started = transition(graph, empty_state(), RUN, NOW, CONFIG)
    create = started.entry.effects[0]
    assert create.kind == "create_session"
    completed = transition(
        graph,
        started.state,
        EffectCompleted(effect_key=create.effect_key),
        NOW,
        CONFIG,
    )
    assert [effect.kind for effect in completed.entry.effects] == ["send_input"]
    duplicate = transition(
        graph,
        completed.state,
        EffectCompleted(effect_key=create.effect_key, payload={"pending_input": False}),
        NOW,
        CONFIG,
    )
    assert duplicate.entry.effects == ()
    assert duplicate.entry.rejection is None
    assert duplicate.entry.patch == ()
    assert duplicate.entry.receipt_key == completed.entry.receipt_key == create.effect_key
    assert duplicate.state == completed.state
    stored = [item for item in duplicate.state.receipts if item.key == create.effect_key]
    assert len(stored) == 1
    assert stored[0].payload == {}
    assert sum(effect.kind == "send_input" for effect in duplicate.state.effects) == 1
    log = (started.entry, completed.entry, duplicate.entry)
    assert fold(graph, log, CONFIG) == duplicate.state


def test_replaying_failures_reprompts_and_a_pending_close_repeats_every_entry() -> None:
    graph = compile_text(
        workflow_text(
            [start(), step("work"), step("ship"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "ship"),
                arrow("a3", "ship", "end"),
            ],
        )
    )[0]
    pending = drive(graph, [RUN], auto_ack=False)
    create = pending.log[-1].effects[0]
    working = drive(
        graph,
        [
            EffectFailed(effect_key=create.effect_key, code="session.not_ready", retryable=True),
            ResumeRun(),
            EffectCompleted(effect_key=create.effect_key),
        ],
        after=pending,
    )
    failed_at = NOW + timedelta(minutes=1)
    failed = drive(
        graph,
        [
            SessionFailed(
                slot_id=SLOT,
                failure_class="infra.transient",
                cause="529",
                fact_key="turn:sess-1:1:msg:a",
            )
        ],
        after=working,
        now=failed_at,
    )
    stage = failed.state.timers[0]
    early = drive(graph, [TimerDue(timer_key=stage.key)], after=failed, now=failed_at)
    nudged = drive(graph, [TimerDue(timer_key=stage.key)], after=early, now=stage.due_at)
    backoff = nudged.log[-1].effects[0]
    ended = drive(
        graph,
        [
            EffectCompleted(effect_key=backoff.effect_key),
            TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:msg:b"),
        ],
        after=nudged,
        now=stage.due_at,
    )
    turn_nudge = ended.log[-1].effects[0]
    later = stage.due_at + timedelta(minutes=1)
    closing = drive(
        graph,
        [
            EffectFailed(
                effect_key=turn_nudge.effect_key, code="session.host_offline", retryable=True
            ),
            ResumeRun(),
            EffectCompleted(effect_key=turn_nudge.effect_key),
            HandoffReceived(slot_id=SLOT, body="done"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        after=ended,
        now=later,
        auto_ack=False,
    )
    close = closing.log[-1].effects[0]
    finished = drive(
        graph,
        [
            EffectCompleted(effect_key=close.effect_key, payload={"pending_input": True}),
            ResumeRun(),
            PauseRun(reason="user", detail="hold"),
            PauseRun(reason="user", detail="hold"),
            ResumeRun(),
            HandoffReceived(slot_id="ship||:0", body="shipped"),
            HandoffEvaluated(slot_id="ship||:0", outcome="accepted"),
        ],
        after=closing,
        now=later + timedelta(minutes=1),
    )
    assert finished.state.status == "completed"
    assert all(entry.rejection is None for entry in finished.log)
    # Every effect key carries its entry's seq, so none repeats across the run.
    for entry in finished.log:
        assert all(effect.effect_key.startswith(f"run-1:{entry.seq}:") for effect in entry.effects)
    keys = [effect.effect_key for effect in finished.state.effects]
    assert len(keys) == len(set(keys))

    for _replay in range(2):
        state = empty_state()
        replayed = []
        for entry in finished.log:
            result = transition(graph, state, entry.input, entry.now, CONFIG)
            replayed.append(result.entry)
            state = result.state
        assert tuple(replayed) == finished.log
        assert state == finished.state
    assert fold(graph, finished.log, CONFIG) == finished.state
