"""Each engine gate visit as one ``coral_gate_visits`` row, and its delivery as bridge rows."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from coral.bridge.gate_rows import project_gates
from coral.bridge.keys import store_activation_id
from coral.db.enum_codecs import GateVisitStatus, RunStatus
from coral.engine.types import PauseRun, RunState
from coral.gates.ids import GATE_ELICITATION_ID, gate_visit_id
from coral.model.ids import anchor_session_id
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import GateVisitDraft, GateVisitState, RunVersionConflict
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
    ASKED_AGAIN,
    CHANGE_TOKEN,
    CHANGE_TOKEN_AGAIN,
    GATE_ONLY,
    GATED,
    HOLD_TOKEN,
    HOLD_TOKEN_AGAIN,
    IMPLEMENT_AGAIN,
    GateIds,
    answer,
    before_next_commit,
    effects,
    gate_rows,
    hand_off,
    payload,
    work_for,
)
from tests.coral.bridge._world import USER, WORKSPACE, World, start


@pytest.fixture
def gate_ids() -> GateIds:
    return GateIds()


@pytest.fixture
def world(tmp_path: Path, gate_ids: GateIds) -> World:
    return World.fake(tmp_path, gate_ids=gate_ids)


def _gate_work(world: World, run_id: str) -> set[str]:
    return {item.id for item in world.work(run_id) if payload(item).get("bridge_item") == "gate"}


def _no_new_id() -> str:
    raise AssertionError("a row that has an elicitation id keeps it")


def test_opening_a_visit_writes_one_open_row_and_one_publish_row(
    world: World, gate_ids: GateIds
) -> None:
    run = start(world, GATE_ONLY)
    opened_at = world.clock.epoch

    (row,) = gate_rows(world, run.id)
    assert row == GateVisitState(
        workspace_id=WORKSPACE,
        run_id=run.id,
        id=gate_visit_id(run.id, APPROVE_TOKEN),
        activation_id=store_activation_id(run.id, "approve||"),
        node_id="approve",
        scope_key="approve||",
        visit_no=1,
        token=APPROVE_TOKEN,
        status=int(GateVisitStatus.OPEN),
        opened_at=opened_at,
        owner_user_id=USER,
        elicitation_id=gate_ids.issued[0],
        elicitation_session_id=anchor_session_id(WORKSPACE, run.id),
    )
    assert len(gate_ids.issued) == 1 and GATE_ELICITATION_ID.fullmatch(gate_ids.issued[0])
    (publish,) = effects(world, run.id, "publish_gate")
    item = work_for(world, run.id, publish.effect_key)
    assert item is not None
    assert payload(item) == {
        "effect_type": "gate_publish",
        "effect_key": publish.effect_key,
        "bridge_item": "gate",
        "visit_id": row.id,
    }
    assert _gate_work(world, run.id) == {item.id}

    # A pause keeps the visit live; a repeated start and a resync change nothing.
    world.clock.advance(60)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )
    start(world, GATE_ONLY)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    rows = world.work(run.id)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    assert gate_rows(world, run.id) == [row]
    assert world.work(run.id) == rows
    assert len(gate_ids.issued) == 1
    world.assert_fold_matches(run.id)


def test_an_answer_resolves_the_row_and_keeps_its_id(world: World, gate_ids: GateIds) -> None:
    run = start(world, GATE_ONLY)
    opened_at = world.clock.epoch
    world.clock.advance(30)

    assert answer(world, run.id, APPROVE_TOKEN, "approve", note="Ship it.").outcome == "accepted"

    (row,) = gate_rows(world, run.id)
    assert (row.status, row.answer_label, row.answered_by, row.note) == (
        int(GateVisitStatus.RESOLVED),
        "approve",
        "alice",
        "Ship it.",
    )
    assert (row.opened_at, row.resolved_at, row.elicitation_id) == (
        opened_at,
        world.clock.epoch,
        gate_ids.issued[0],
    )
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    world.assert_fold_matches(run.id)


def test_a_loop_back_supersedes_the_first_visit_and_publishes_the_second(
    world: World, gate_ids: GateIds
) -> None:
    run = start(world, GATED)
    hand_off(world, run.id)
    (first,) = gate_rows(world, run.id)
    assert (first.token, first.status) == (CHANGE_TOKEN, int(GateVisitStatus.OPEN))

    assert answer(world, run.id, CHANGE_TOKEN, "reject").outcome == "accepted"
    assert gate_rows(world, run.id)[0].status == int(GateVisitStatus.RESOLVED)
    hand_off(world, run.id, IMPLEMENT_AGAIN)

    first, second = gate_rows(world, run.id)
    assert (first.status, first.answer_label, first.elicitation_id) == (
        int(GateVisitStatus.SUPERSEDED),
        "reject",
        gate_ids.issued[0],
    )
    assert (second.token, second.visit_no, second.status, second.elicitation_id) == (
        CHANGE_TOKEN_AGAIN,
        2,
        int(GateVisitStatus.OPEN),
        gate_ids.issued[1],
    )
    (withdraw,) = effects(world, run.id, "withdraw_gate")
    assert withdraw.subject == CHANGE_TOKEN
    withdrawn = work_for(world, run.id, withdraw.effect_key)
    assert withdrawn is not None
    assert (payload(withdrawn)["effect_type"], payload(withdrawn)["visit_id"]) == (
        "gate_withdraw",
        first.id,
    )
    publishes = effects(world, run.id, "publish_gate")
    assert [effect.subject for effect in publishes] == [CHANGE_TOKEN, CHANGE_TOKEN_AGAIN]
    published = work_for(world, run.id, publishes[1].effect_key)
    assert published is not None and payload(published)["visit_id"] == second.id
    assert len(_gate_work(world, run.id)) == 3
    world.assert_fold_matches(run.id)


def test_an_answer_that_asks_the_gate_again_at_once_supersedes_its_row_in_that_commit(
    world: World, gate_ids: GateIds
) -> None:
    run = start(world, ASKED_AGAIN)
    world.clock.advance(30)

    assert answer(world, run.id, HOLD_TOKEN, "reject").outcome == "accepted"

    first, second = gate_rows(world, run.id)
    assert (first.token, first.status, first.answer_label, first.resolved_at) == (
        HOLD_TOKEN,
        int(GateVisitStatus.SUPERSEDED),
        "reject",
        world.clock.epoch,
    )
    assert (second.token, second.visit_no, second.status, second.resolved_at) == (
        HOLD_TOKEN_AGAIN,
        2,
        int(GateVisitStatus.OPEN),
        None,
    )
    assert [first.elicitation_id, second.elicitation_id] == gate_ids.issued
    (withdraw,) = effects(world, run.id, "withdraw_gate")
    publish = effects(world, run.id, "publish_gate")[-1]
    assert (withdraw.subject, publish.subject) == (HOLD_TOKEN, HOLD_TOKEN_AGAIN)
    withdrawn = work_for(world, run.id, withdraw.effect_key)
    published = work_for(world, run.id, publish.effect_key)
    assert withdrawn is not None and published is not None
    assert (payload(withdrawn)["effect_type"], payload(withdrawn)["visit_id"]) == (
        "gate_withdraw",
        first.id,
    )
    assert (payload(published)["effect_type"], payload(published)["visit_id"]) == (
        "gate_publish",
        second.id,
    )
    world.assert_fold_matches(run.id)


def test_a_row_two_commits_race_to_write_keeps_the_winner_s_id(
    world: World, gate_ids: GateIds
) -> None:
    # As for two resyncs of a run whose gate opened before its rows were written.
    run = start(world, GATE_ONLY)
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    runs.gate_visits.clear()

    def repair() -> None:
        world.bridge.commit_inputs(
            workspace_id=WORKSPACE, run_id=run.id, inputs=lambda _snapshot: ()
        )

    before_next_commit(world, repair)
    repair()

    # The loser drew an id before it lost; its retry found the winner's row and kept it.
    _first, lost, won = gate_ids.issued
    (row,) = gate_rows(world, run.id)
    assert row.elicitation_id == won != lost
    world.assert_fold_matches(run.id)


def test_a_cancel_at_an_open_gate_cancels_its_row_and_queues_its_withdraw(
    world: World,
) -> None:
    run = start(world, GATE_ONLY)
    world.clock.advance(5)

    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")

    (row,) = gate_rows(world, run.id)
    assert (row.status, row.resolved_at, row.answer_label) == (
        int(GateVisitStatus.CANCELLED),
        world.clock.epoch,
        None,
    )
    (withdraw,) = effects(world, run.id, "withdraw_gate")
    assert withdraw.subject == APPROVE_TOKEN
    item = work_for(world, run.id, withdraw.effect_key)
    assert item is not None
    assert payload(item) == {
        "effect_type": "gate_withdraw",
        "effect_key": withdraw.effect_key,
        "bridge_item": "gate",
        "visit_id": row.id,
    }
    # The engine keeps the visit open; only a live run's open visit is an open row.
    state = world.assert_fold_matches(run.id)
    assert [visit.status for visit in state.gates] == ["open"]


def test_projection_keeps_the_columns_the_engine_does_not_own(world: World) -> None:
    run = start(world, GATE_ONLY)
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    (row,) = snapshot.store.gate_visits
    kept = dataclasses.replace(row, prompt_ref="ref", reminded_at=5)

    def project(
        state: RunState,
        loaded: Sequence[GateVisitState],
        new_id: Callable[[], str] = _no_new_id,
    ) -> tuple[GateVisitDraft, ...]:
        return project_gates(
            snapshot.store.run,
            state,
            loaded,
            workspace_id=WORKSPACE,
            now=999,
            new_elicitation_id=new_id,
        )

    assert project(snapshot.state, [row]) == ()
    assert project(snapshot.state, [kept]) == ()
    # An open visit of a finished run is not live: its row is cancelled.
    (draft,) = project(snapshot.state.model_copy(update={"status": "completed"}), [kept])
    assert (draft.status, draft.resolved_at, draft.prompt_ref, draft.reminded_at) == (
        int(GateVisitStatus.CANCELLED),
        999,
        "ref",
        5,
    )
    assert (draft.elicitation_id, draft.opened_at) == (row.elicitation_id, row.opened_at)
    (fresh,) = project(snapshot.state, [], lambda: "coral_gate_" + "f" * 32)
    assert (fresh.elicitation_id, fresh.opened_at, fresh.resolved_at) == (
        "coral_gate_" + "f" * 32,
        999,
        None,
    )
    answered = snapshot.state.model_copy(
        update={
            "gates": tuple(
                visit.model_copy(
                    update={"status": "resolved", "label": "approve", "by": "b" * 200, "note": ""}
                )
                for visit in snapshot.state.gates
            )
        }
    )
    (resolved,) = project(answered, [row])
    assert (resolved.status, resolved.answered_by, resolved.note) == (
        int(GateVisitStatus.RESOLVED),
        "b" * 128,
        None,
    )


def test_the_commit_that_first_writes_a_row_keeps_only_its_winning_attempt_s_id(
    world: World, gate_ids: GateIds
) -> None:
    runs = world.runs
    assert isinstance(runs, FakeRunStore)

    lost_once: list[bool] = []

    def lose_once(run_id: str, expected_version: int) -> None:
        if not lost_once:
            lost_once.append(True)
            raise RunVersionConflict(run_id, expected_version, expected_version + 1)

    # The start's commit opens the gate; its first attempt loses and is reduced again.
    runs.before_apply_hook = lose_once
    run = start(world, GATE_ONLY)

    lost, won = gate_ids.issued
    (row,) = gate_rows(world, run.id)
    assert row.elicitation_id == won != lost
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    assert gate_rows(world, run.id) == [row]
    assert gate_ids.issued == [lost, won]
