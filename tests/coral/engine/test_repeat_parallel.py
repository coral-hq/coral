"""ENG-08 pure fan-out and region cancel (dark until SES-10)."""

from __future__ import annotations

import pytest

from coral.engine.regions import CANCEL_REGION, cancel_region_effects
from coral.engine.repeat import START_ITEM, fan_out, freeze_item_ids, repeat_progress
from coral.engine.types import RULES, StartRun, activation_id
from tests.coral.engine.drive import drive
from tests.coral.workflow_builders import arrow, compile_text, end, start, step, workflow_text


def test_freeze_item_ids_are_decimal_indices_in_order() -> None:
    assert freeze_item_ids(("x", "y", "z")) == ("0", "1", "2")
    assert freeze_item_ids(()) == ()


def test_fan_out_empty_list_emits_no_effects() -> None:
    plan = fan_out(run_id="run", seq=1, node_id="review", items=(), concurrency=2)
    assert plan.item_ids == ()
    assert plan.effects == ()


def test_fan_out_opens_concurrency_window_only() -> None:
    plan = fan_out(
        run_id="run",
        seq=10,
        node_id="review",
        items=("a", "b", "c"),
        concurrency=2,
    )
    assert plan.item_ids == ("0", "1", "2")
    assert len(plan.effects) == 2
    assert all(effect.kind == START_ITEM for effect in plan.effects)
    assert plan.effects[0].subject == activation_id("review", ("0",))
    assert plan.effects[1].subject == activation_id("review", ("1",))
    assert plan.effects[0].payload["item_id"] == "0"


def test_fan_out_rejects_non_positive_concurrency() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        fan_out(run_id="run", seq=1, node_id="n", items=("a",), concurrency=0)


def test_repeat_progress_shape() -> None:
    assert repeat_progress(done=2, failed=1, total=3) == {
        "done": 2,
        "failed": 1,
        "total": 3,
    }
    with pytest.raises(ValueError):
        repeat_progress(done=2, failed=2, total=3)


def test_cancel_region_one_effect_per_active_subject() -> None:
    subjects = (
        activation_id("work", ("left",)),
        activation_id("work", ("right",)),
    )
    effects = cancel_region_effects(
        run_id="run",
        seq=5,
        split_node_id="split",
        join_node_id="join",
        active_subjects=subjects,
    )
    assert len(effects) == 2
    assert all(effect.kind == CANCEL_REGION for effect in effects)
    assert effects[0].subject == subjects[0]
    assert effects[1].payload["split_node_id"] == "split"


def test_list_from_graphs_set_structure_runtime_and_refuse_start() -> None:
    graph, _ = compile_text(
        workflow_text(
            [
                start(),
                step("plan", parts=[{"name": "items", "kind": "list"}]),
                step("each", list_from="plan.items"),
                end(),
            ],
            [
                arrow("a1", "start", "plan"),
                arrow("a2", "plan", "each"),
                arrow("a3", "each", "end"),
            ],
        )
    )
    assert graph.analysis.requires_structure_runtime is True
    started = drive(
        graph,
        [StartRun(run_id="run-1", start_key="start-1", version_hash="h", rules=RULES)],
    )
    assert started.state.status is None
    assert started.log[-1].rejection is not None
    assert started.log[-1].rejection.code == "structure.runtime_required"
