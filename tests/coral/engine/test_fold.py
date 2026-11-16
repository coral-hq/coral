"""Skeleton replay: start, one step, end, and a duplicate effect completion."""

from __future__ import annotations

from coral.engine import empty_state, fold, transition
from coral.engine.types import (
    EffectCompleted,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    StartRun,
)
from tests.coral.engine.drive import NOW, drive
from tests.coral.workflow_builders import compile_text, fixture_text

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
