"""Engine state projected onto the run row and the agent-slot rows executors read."""

from __future__ import annotations

import dataclasses
from typing import get_args

import pytest

from coral.bridge.keys import store_activation_id, store_slot_id
from coral.bridge.projection import RunProjection, project_run, project_slots, slot_role
from coral.db.enum_codecs import (
    RUN_PAUSE_REASON,
    SLOT_STATUS,
    RunPauseReason,
    RunStatus,
    SlotRole,
)
from coral.engine.types import (
    EffectCompleted,
    EffectFailed,
    PauseCause,
    PauseReason,
    RejectionObserved,
    RunState,
    SlotStatus,
)
from coral.stores.protocols import AgentSlotDraft, AgentSlotState, CoralRun
from tests.coral.bridge._scripted_runs import (
    IMPLEMENT,
    RUN_ID,
    WORKSPACE,
    accept,
    fixture_graph,
    start_run,
)
from tests.coral.engine.drive import drive

GRAPH = fixture_graph("two_steps")
NOW_S = 1_800_000_000


def _run(**changes: object) -> CoralRun:
    run = CoralRun(
        workspace_id=WORKSPACE,
        id=RUN_ID,
        workflow_id="f" * 32,
        version_id="e" * 32,
        status=int(RunStatus.RUNNING),
        version=3,
        next_log_seq=4,
        activation_count=0,
        title="Ship",
        engine_version=1,
        state_version=1,
        log_version=1,
        created_at=100,
        updated_at=100,
    )
    return dataclasses.replace(run, **changes)


def _stored(draft: AgentSlotDraft) -> AgentSlotState:
    """The row a store keeps for ``draft``."""
    fields = {field.name: getattr(draft, field.name) for field in dataclasses.fields(draft)}
    return AgentSlotState(workspace_id=WORKSPACE, run_id=RUN_ID, **fields)


@pytest.mark.parametrize(
    ("engine_status", "store_status"),
    [
        (None, RunStatus.STARTING),
        ("running", RunStatus.RUNNING),
        ("paused", RunStatus.PAUSED),
        ("completed", RunStatus.COMPLETED),
        ("failed", RunStatus.FAILED),
        ("cancelled", RunStatus.CANCELLED),
    ],
)
def test_the_run_row_follows_the_engine_status(
    engine_status: str | None, store_status: RunStatus
) -> None:
    causes = (PauseCause(reason="user", detail="look", subject=""),)
    state = RunState(status=engine_status, causes=causes if engine_status == "paused" else ())
    other = RunStatus.CANCELLED if store_status != RunStatus.CANCELLED else RunStatus.RUNNING
    moved = project_run(_run(status=int(other)), state, now=NOW_S)
    assert moved.status == int(store_status)
    same = project_run(
        _run(status=int(store_status), pause_reason=int(RunPauseReason.USER)), state, now=NOW_S
    )
    assert same.status is None


@pytest.mark.parametrize("reason", get_args(PauseReason))
def test_a_paused_run_shows_its_first_cause_for_every_reason(reason: PauseReason) -> None:
    causes = (
        PauseCause(reason=reason, detail="d", subject="a"),
        PauseCause(reason="user", detail="look", subject="z"),
    )
    state = RunState(status="paused", causes=causes)
    projected = project_run(_run(), state, now=NOW_S)
    assert projected.pause_reason == RUN_PAUSE_REASON[reason]
    assert projected.clear_pause_reason is False
    unchanged = project_run(
        _run(status=int(RunStatus.PAUSED), pause_reason=RUN_PAUSE_REASON[reason]),
        state,
        now=NOW_S,
    )
    assert unchanged == RunProjection()


def test_the_auth_pause_has_its_own_code() -> None:
    state = RunState(
        status="paused", causes=(PauseCause(reason="auth", detail="401", subject=""),)
    )
    assert project_run(_run(), state, now=NOW_S).pause_reason == int(RunPauseReason.AUTH)


def test_a_running_run_clears_the_rows_pause_reason() -> None:
    row = _run(status=int(RunStatus.PAUSED), pause_reason=int(RunPauseReason.INFRA))
    projected = project_run(row, RunState(status="running"), now=NOW_S)
    assert projected.status == int(RunStatus.RUNNING)
    assert projected.clear_pause_reason is True
    assert projected.pause_reason is None
    assert project_run(_run(), RunState(status="running"), now=NOW_S) == RunProjection()


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_a_finished_run_records_its_finish_time_once(status: str) -> None:
    state = RunState(status=status)
    assert project_run(_run(), state, now=NOW_S).finished_at == NOW_S
    finished = _run(status=int(RunStatus[status.upper()]), finished_at=5)
    assert project_run(finished, state, now=NOW_S) == RunProjection()
    assert project_run(_run(), RunState(status="running"), now=NOW_S).finished_at is None


def test_the_activation_count_moves_by_the_activations_opened() -> None:
    started = drive(GRAPH, [start_run(GRAPH)])
    opened = len(started.state.activations)
    assert opened == 2
    assert project_run(_run(), started.state, now=NOW_S).activation_count_delta == opened
    counted = _run(activation_count=opened)
    assert project_run(counted, started.state, now=NOW_S).activation_count_delta == 0


@pytest.mark.parametrize("status", get_args(SlotStatus))
def test_every_engine_slot_status_has_a_slot_code(status: str) -> None:
    started = drive(GRAPH, [start_run(GRAPH)], auto_ack=False)
    state = started.state.model_copy(
        update={
            "slots": tuple(
                slot.model_copy(update={"status": status}) for slot in started.state.slots
            )
        }
    )
    (draft,) = project_slots(RUN_ID, state, (), now=NOW_S)
    assert draft.status == SLOT_STATUS[status]


def test_slot_drafts_carry_the_engine_fields_and_copy_every_other_column() -> None:
    started = drive(GRAPH, [start_run(GRAPH)], auto_ack=False)
    create = next(effect for effect in started.state.effects if effect.kind == "create_session")
    assert project_slots(RUN_ID, started.state, (), now=NOW_S)[0].session_id is None
    session = "s" * 32
    created = drive(
        GRAPH,
        [
            EffectCompleted(
                effect_key=create.effect_key,
                payload={"session_id": session, "role": "step", "generation": 1},
            )
        ],
        auto_ack=False,
        after=started,
    )
    (draft,) = project_slots(RUN_ID, created.state, (), now=NOW_S)
    assert draft == AgentSlotDraft(
        id=store_slot_id(RUN_ID, IMPLEMENT),
        activation_id=store_activation_id(RUN_ID, "implement||"),
        node_id="implement",
        scope_key=IMPLEMENT,
        roster_index=0,
        role=int(SlotRole.STEP_AGENT),
        session_generation=1,
        status=SLOT_STATUS["session_created"],
        session_id=session,
        nudges=0,
        consecutive_rejections=0,
        created_at=NOW_S,
        updated_at=NOW_S,
    )

    # Columns the engine does not own keep what the row holds.
    loaded = _stored(
        dataclasses.replace(
            draft,
            lease_holder="worker-1",
            lease_expires_at=99,
            branch="coral/run",
            worktree_path="/tmp/run",
            last_edge_status="idle",
            last_turn_origin=1,
            context_used_bp=1200,
            created_at=50,
            updated_at=60,
        )
    )
    assert project_slots(RUN_ID, created.state, (loaded,), now=NOW_S) == ()

    rejected = drive(
        GRAPH,
        [RejectionObserved(slot_id=IMPLEMENT, code="handoff.invalid")],
        after=drive(
            GRAPH,
            [EffectCompleted(effect_key=_brief_key(created.state))],
            auto_ack=False,
            after=created,
        ),
    )
    (moved,) = project_slots(RUN_ID, rejected.state, (loaded,), now=NOW_S)
    assert moved.status == SLOT_STATUS["working"]
    assert moved.consecutive_rejections == 1
    assert (moved.lease_holder, moved.branch, moved.context_used_bp) == (
        "worker-1",
        "coral/run",
        1200,
    )
    assert (moved.created_at, moved.updated_at) == (50, NOW_S)


def _brief_key(state: RunState) -> str:
    return next(effect.effect_key for effect in state.effects if effect.kind == "send_input")


def test_only_slots_that_differ_from_their_rows_are_written() -> None:
    driven = drive(GRAPH, [start_run(GRAPH), *accept(IMPLEMENT, "implemented")])
    first = project_slots(RUN_ID, driven.state, (), now=NOW_S)
    assert [draft.scope_key for draft in first] == [IMPLEMENT, "review||:0"]
    rows = tuple(_stored(draft) for draft in first)
    assert project_slots(RUN_ID, driven.state, rows, now=NOW_S + 5) == ()
    review_role = {draft.scope_key: draft.role for draft in first}["review||:0"]
    assert review_role == int(SlotRole.VERIFIER)
    nudged = driven.state.model_copy(
        update={
            "slots": tuple(
                slot.model_copy(update={"nudges": 2}) if slot.id == IMPLEMENT else slot
                for slot in driven.state.slots
            )
        }
    )
    (changed,) = project_slots(RUN_ID, nudged, rows, now=NOW_S + 5)
    assert (changed.scope_key, changed.nudges, changed.updated_at) == (IMPLEMENT, 2, NOW_S + 5)


def test_a_failed_create_names_no_session() -> None:
    started = drive(GRAPH, [start_run(GRAPH)], auto_ack=False)
    create = next(effect for effect in started.state.effects if effect.kind == "create_session")
    failed = drive(
        GRAPH,
        [EffectFailed(effect_key=create.effect_key, code="session.agent_not_supported")],
        auto_ack=False,
        after=started,
    )
    assert any(item.key == create.effect_key for item in failed.state.receipts)
    (draft,) = project_slots(RUN_ID, failed.state, (), now=NOW_S)
    assert draft.session_id is None


@pytest.mark.parametrize(
    ("profile", "role"),
    [
        ("implementer", SlotRole.STEP_AGENT),
        ("implementer/fast", SlotRole.STEP_AGENT),
        ("reviewer", SlotRole.VERIFIER),
        ("reviewer/strict-review", SlotRole.VERIFIER),
        ("implementer/Bad", SlotRole.VERIFIER),
        ("planner", SlotRole.VERIFIER),
    ],
)
def test_a_profile_slot_takes_its_stance_s_role(profile: str, role: SlotRole) -> None:
    assert slot_role(profile) == role
