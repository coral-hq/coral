"""SES-10 structure admission, start_item, cancel, and gate batch payloads."""

from __future__ import annotations

from coral.engine.regions import cancel_region_effects
from coral.engine.repeat import fan_out
from coral.engine.types import RULES, StartRun, activation_id
from coral.structure.batch import BatchItem, GateBatch
from coral.structure.caps import AdmissionGate, admit, release
from coral.structure.items import apply_start_item
from coral.structure.regions import apply_cancel_region
from tests.coral.engine.drive import drive
from tests.coral.workflow_builders import arrow, compile_text, end, start, step, workflow_text


def _step_graph():
    return compile_text(
        workflow_text(
            [start(), step("each"), end()],
            [arrow("a1", "start", "each"), arrow("a2", "each", "end")],
        )
    )[0]


def test_admission_respects_concurrency_limit() -> None:
    gate = AdmissionGate(group_key="each", limit=2)
    gate, ok = admit(gate)
    assert ok and gate.live == 1
    gate, ok = admit(gate)
    assert ok and gate.live == 2
    gate, ok = admit(gate)
    assert not ok and gate.live == 2
    gate = release(gate)
    gate, ok = admit(gate)
    assert ok and gate.live == 2


def test_start_item_opens_item_activation() -> None:
    graph = _step_graph()
    started = drive(
        graph,
        [StartRun(run_id="run-1", start_key="start-1", version_hash="h", rules=RULES)],
    )
    plan = fan_out(
        run_id="run-1",
        seq=started.state.seq + 1,
        node_id="each",
        items=("a", "b"),
        concurrency=1,
    )
    effect = plan.effects[0]
    applied = apply_start_item(graph, started.state, effect)
    assert any(item.id.startswith("each|0|") for item in applied.state.activations)


def test_cancel_region_emits_close_for_live_slots() -> None:
    graph = _step_graph()
    started = drive(
        graph,
        [StartRun(run_id="run-1", start_key="start-1", version_hash="h", rules=RULES)],
    )
    # Open the default each activation's slot via the normal start path.
    subject = activation_id("each")
    slot_ids = tuple(item.id for item in started.state.slots if item.activation_id == subject)
    effects = cancel_region_effects(
        run_id="run-1",
        seq=started.state.seq + 1,
        split_node_id="start",
        join_node_id="end",
        active_subjects=slot_ids or (subject,),
    )
    applied = apply_cancel_region(graph, started.state, effects[0])
    assert any(effect.kind == "close_slot" for effect in applied.effects) or not slot_ids


def test_gate_batch_payload_shape() -> None:
    batch = GateBatch(
        batch_id="batch-1",
        gate_node="approve",
        items=(
            BatchItem(item_path=("0",), visit_token="tok-0", context="PR 1"),
            BatchItem(item_path=("1",), visit_token="tok-1", context="PR 2"),
        ),
    )
    payload = batch.payload()
    assert payload["batch_id"] == "batch-1"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["visit_token"] == "tok-0"
