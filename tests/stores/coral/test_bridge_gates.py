"""Gate rows, their delivery rows and answers on every DB lane, read back by a fresh process."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from coral.bridge.mapping import UnsupportedStance
from coral.bridge.service import GateAnswerResult
from coral.db.enum_codecs import GateVisitStatus, RunPauseReason, RunStatus
from coral.engine.types import PauseRun
from coral.gates.ids import gate_visit_id
from coral.model.ids import anchor_session_id
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
    CHANGE_TOKEN,
    GATE_ONLY,
    GATED,
    GateIds,
    answer,
    effects,
    gate_rows,
    hand_off,
    payload,
    visit,
    work_for,
)
from tests.coral.bridge._world import USER, WORKSPACE, World, start
from tests.stores.coral._faults import fresh_process, run_racing


def _reopened(coral_db_uri: str) -> World:
    fresh_process(coral_db_uri)
    return World.sql(coral_db_uri)


def _first_load_waits(
    monkeypatch: pytest.MonkeyPatch, world: World, barrier: threading.Barrier
) -> None:
    """The replica's first run load waits at ``barrier``, so racers reduce one snapshot."""
    load = world.runs.load_run_state
    waited: list[bool] = []

    def load_then_wait(*args: Any, **kwargs: Any) -> Any:
        loaded = load(*args, **kwargs)
        if not waited:
            waited.append(True)
            barrier.wait()
        return loaded

    monkeypatch.setattr(world.runs, "load_run_state", load_then_wait)


def test_an_open_visit_is_one_open_row_and_one_publish_row(coral_db_uri: str) -> None:
    gate_ids = GateIds()
    run = start(World.sql(coral_db_uri, gate_ids=gate_ids), GATE_ONLY)

    world = _reopened(coral_db_uri)
    (row,) = gate_rows(world, run.id)
    assert (row.id, row.token, row.scope_key, row.node_id, row.visit_no) == (
        gate_visit_id(run.id, APPROVE_TOKEN),
        APPROVE_TOKEN,
        "approve||",
        "approve",
        1,
    )
    assert (row.status, row.owner_user_id, row.elicitation_id, row.elicitation_session_id) == (
        int(GateVisitStatus.OPEN),
        USER,
        gate_ids.issued[0],
        anchor_session_id(WORKSPACE, run.id),
    )
    (publish,) = effects(world, run.id, "publish_gate")
    item = work_for(world, run.id, publish.effect_key)
    assert item is not None
    assert payload(item) == {
        "effect_type": "gate_publish",
        "effect_key": publish.effect_key,
        "bridge_item": "gate",
        "visit_id": row.id,
    }

    # A repeated start and a resync keep the row and its stored id; nothing new is queued.
    version = world.run(run.id).version
    start(world, GATE_ONLY)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    world = _reopened(coral_db_uri)
    assert gate_rows(world, run.id) == [row]
    assert world.run(run.id).version == version
    assert len(gate_ids.issued) == 1
    world.assert_fold_matches(run.id)


def test_a_cancel_at_an_open_gate_cancels_its_row_and_queues_its_withdraw(
    coral_db_uri: str,
) -> None:
    world = World.sql(coral_db_uri)
    run = start(world, GATE_ONLY)
    world.clock.advance(5)

    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")

    world = _reopened(coral_db_uri)
    (row,) = gate_rows(world, run.id)
    assert row.status == int(GateVisitStatus.CANCELLED)
    assert row.resolved_at is not None
    (withdraw,) = effects(world, run.id, "withdraw_gate")
    item = work_for(world, run.id, withdraw.effect_key)
    assert item is not None
    assert (payload(item)["effect_type"], payload(item)["visit_id"]) == ("gate_withdraw", row.id)
    assert world.run(run.id).status == int(RunStatus.CANCELLED)


def test_an_answer_is_accepted_once_and_later_ones_are_told_why(coral_db_uri: str) -> None:
    world = World.sql(coral_db_uri)
    run = start(world, GATED)
    hand_off(world, run.id)

    assert answer(world, run.id, CHANGE_TOKEN, "reject", note="Add tests.").outcome == "accepted"
    world = _reopened(coral_db_uri)
    version = world.run(run.id).version
    assert answer(world, run.id, CHANGE_TOKEN, "reject") == GateAnswerResult(
        outcome="duplicate", answered_label="reject"
    )
    refused = answer(world, run.id, CHANGE_TOKEN, "approve")
    assert (refused.outcome, refused.code, refused.answered_label) == (
        "refused",
        "rejected",
        "reject",
    )
    assert world.run(run.id).version == version
    (row,) = gate_rows(world, run.id)
    assert (row.status, row.answer_label, row.answered_by, row.note) == (
        int(GateVisitStatus.RESOLVED),
        "reject",
        "alice",
        "Add tests.",
    )
    world.assert_fold_matches(run.id)


@pytest.mark.parametrize(
    ("label", "note"),
    [("approve", "n" * 2_001), ("approve\ud800", ""), ("approve", "nul \x00 byte")],
    ids=["long_note", "surrogate_label", "nul_note"],
)
def test_an_answer_no_row_can_store_is_refused_and_writes_nothing(
    coral_db_uri: str, label: str, note: str
) -> None:
    world = World.sql(coral_db_uri)
    run = start(world, GATE_ONLY)
    version = world.run(run.id).version

    assert answer(world, run.id, APPROVE_TOKEN, label, note=note) == GateAnswerResult(
        outcome="refused", code="invalid_answer"
    )

    world = _reopened(coral_db_uri)
    assert world.run(run.id).version == version
    assert visit(world, run.id, APPROVE_TOKEN).status == "open"


def test_the_longest_note_is_stored(coral_db_uri: str) -> None:
    # 2,000 four-byte characters that compress poorly fit the row's and the log's columns.
    note = "".join(chr(0x20000 + (index * 7919) % 40_000) for index in range(2_000))
    world = World.sql(coral_db_uri)
    run = start(world, GATE_ONLY)

    assert answer(world, run.id, APPROVE_TOKEN, "approve", note=note).outcome == "accepted"

    world = _reopened(coral_db_uri)
    assert gate_rows(world, run.id)[0].note == note
    assert visit(world, run.id, APPROVE_TOKEN).note == note


def test_an_answer_to_a_paused_run_is_refused(coral_db_uri: str) -> None:
    world = World.sql(coral_db_uri)
    run = start(world, GATE_ONLY)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )
    assert answer(world, run.id, APPROVE_TOKEN, "approve") == GateAnswerResult(
        outcome="refused", code="run_paused"
    )
    assert visit(_reopened(coral_db_uri), run.id, APPROVE_TOKEN).status == "open"


def test_an_unbuildable_answer_pauses_the_run_and_is_never_accepted(
    coral_db_uri: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World.sql(coral_db_uri)
    run = start(world, GATED)
    hand_off(world, run.id)

    def refuse(*_args: object) -> None:
        raise UnsupportedStance("slot has no step stance")

    monkeypatch.setattr("coral.bridge.commit.map_effect", refuse)
    result = answer(world, run.id, CHANGE_TOKEN, "reject")

    assert result == GateAnswerResult(outcome="refused", code="unbuildable")
    world = _reopened(coral_db_uri)
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    assert visit(world, run.id, CHANGE_TOKEN).status == "open"
    assert gate_rows(world, run.id)[0].status == int(GateVisitStatus.OPEN)


def test_two_replicas_answering_at_once_commit_one_answer(
    coral_db_uri: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(World.sql(coral_db_uri), GATE_ONLY)
    replicas = [World.sql(coral_db_uri), World.sql(coral_db_uri)]
    barrier = threading.Barrier(2, timeout=10)
    for replica in replicas:
        _first_load_waits(monkeypatch, replica, barrier)

    outcomes = run_racing(
        2,
        lambda index: answer(
            replicas[index], run.id, APPROVE_TOKEN, "approve", actor=f"user-{index}"
        ),
    )

    # Both reduced one snapshot; the loser's retry found the winner's receipt.
    assert [outcome.error for outcome in outcomes] == [None, None]
    results = [outcome.value for outcome in outcomes]
    assert sorted(
        result.outcome for result in results if isinstance(result, GateAnswerResult)
    ) == [
        "accepted",
        "duplicate",
    ]
    (winner,) = [
        index
        for index, result in enumerate(results)
        if isinstance(result, GateAnswerResult) and result.outcome == "accepted"
    ]
    world = _reopened(coral_db_uri)
    (row,) = gate_rows(world, run.id)
    assert (row.status, row.answer_label, row.answered_by) == (
        int(GateVisitStatus.RESOLVED),
        "approve",
        f"user-{winner}",
    )
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    world.assert_fold_matches(run.id)
