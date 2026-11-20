"""Gate rows, their delivery rows and answers on every DB lane, read back by a fresh process."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from coral.alerts.rules import alert_subject
from coral.alerts.types import AlertPayload
from coral.bridge.commit import Applied, build_commit
from coral.bridge.executors import BridgeThreads
from coral.bridge.mapping import UnsupportedStance
from coral.bridge.service import GateAnswerResult
from coral.db.enum_codecs import (
    AlertKind,
    AlertPriority,
    AlertStatus,
    GateVisitStatus,
    RunPauseReason,
    RunStatus,
    SessionBindingProgress,
)
from coral.engine import transition
from coral.engine.types import PauseRun
from coral.gates.executors import publish_live
from coral.gates.ids import gate_visit_id
from coral.gates.republish import GateRepublisher
from coral.gates.verdict import GateAnswer, GateAnswers, GateVerdict
from coral.model.ids import anchor_session_id
from coral.omni.protocols import Viewer
from coral.reconcile import startup_recovery_sweep
from coral.stores.alerts import SqlAlchemyAlertStore
from coral.stores.protocols import AlertRecord, RunVersionConflict
from coral.stores.session_bindings import SessionBindingDraft, SqlAlchemySessionBindingStore
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
from tests.coral.bridge._world import (
    USER,
    WORKSPACE,
    FakeGatePrompts,
    RecordingGatePublisher,
    World,
    run_id_for,
    run_spec,
    start,
)
from tests.stores.coral._faults import SimulatedCrash, crash_around, fresh_process, run_racing


def _reopened(coral_db_uri: str) -> World:
    fresh_process(coral_db_uri)
    return World.sql(coral_db_uri)


def _alerts(coral_db_uri: str, run_id: str) -> list[tuple[int, int, int, str]]:
    """The run's alerts as committed: kind, priority, status and subject, by kind."""
    records = SqlAlchemyAlertStore(coral_db_uri).list_for_run(
        workspace_id=WORKSPACE, run_id=run_id
    )
    return sorted(
        (alert.kind, alert.priority, alert.status, alert.subject_id) for alert in records
    )


def _gate_alert(coral_db_uri: str, run_id: str) -> AlertRecord:
    records = SqlAlchemyAlertStore(coral_db_uri).list_for_run(
        workspace_id=WORKSPACE, run_id=run_id
    )
    (alert,) = [record for record in records if record.kind == int(AlertKind.GATE)]
    return alert


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
    # The gate's alert committed with its row and names the row's prompt.
    alert = _gate_alert(coral_db_uri, run.id)
    assert (alert.status, alert.subject_id, alert.owner_user_id) == (
        int(AlertStatus.OPEN),
        row.id,
        USER,
    )
    assert AlertPayload.model_validate_json(alert.payload).elicitation_id == row.elicitation_id

    # A repeated start and a resync keep the row and its stored id; nothing new is queued.
    version = world.run(run.id).version
    start(world, GATE_ONLY)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    world = _reopened(coral_db_uri)
    assert gate_rows(world, run.id) == [row]
    assert world.run(run.id).version == version
    assert len(gate_ids.issued) == 1
    assert _alerts(coral_db_uri, run.id) == [
        (int(AlertKind.GATE), int(AlertPriority.NORMAL), int(AlertStatus.OPEN), row.id)
    ]
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
    # The cancel resolved the gate's alert and raised the run's own, low one.
    assert _alerts(coral_db_uri, run.id) == [
        (int(AlertKind.GATE), int(AlertPriority.NORMAL), int(AlertStatus.RESOLVED), row.id),
        (
            int(AlertKind.RUN_CANCELLED),
            int(AlertPriority.LOW),
            int(AlertStatus.OPEN),
            alert_subject(run.id, "run"),
        ),
    ]


def test_a_commit_that_loses_its_version_writes_neither_its_entry_nor_its_alert(
    coral_db_uri: str,
) -> None:
    world = World.sql(coral_db_uri)
    run = start(world, GATE_ONLY)
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    paused = transition(
        snapshot.graph,
        snapshot.state,
        PauseRun(reason="infra", detail="stale"),
        world.clock(),
        snapshot.config,
    )
    stale = build_commit(
        snapshot,
        (Applied(entry=paused.entry, before=snapshot.state, after=paused.state),),
        now=world.clock(),
    )
    assert [draft.kind for draft in stale.alert_raises] == [int(AlertKind.PAUSE)]
    # Another commit moves the run first.
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )

    with pytest.raises(RunVersionConflict):
        world.runs.apply_transition(run.id, snapshot.version, stale, workspace_id=WORKSPACE)

    world = _reopened(coral_db_uri)
    assert [kind for kind, *_rest in _alerts(coral_db_uri, run.id)] == [int(AlertKind.GATE)]
    assert [cause.reason for cause in world.assert_fold_matches(run.id).causes] == ["user"]


def test_a_process_that_dies_after_a_gate_commit_leaves_one_alert_per_subject(
    coral_db_uri: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = World.sql(coral_db_uri)
    with monkeypatch.context() as patch:
        crash_around(patch, world.runs, "apply_transition", when="after")
        with pytest.raises(SimulatedCrash):
            start(world, GATE_ONLY)
    run_id = run_id_for()

    # A new process resyncs the run and the caller retries its start.
    world = _reopened(coral_db_uri)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    start(world, GATE_ONLY)
    (row,) = gate_rows(world, run_id)
    assert _alerts(coral_db_uri, run_id) == [
        (int(AlertKind.GATE), int(AlertPriority.NORMAL), int(AlertStatus.OPEN), row.id)
    ]

    with monkeypatch.context() as patch:
        crash_around(patch, world.runs, "apply_transition", when="after")
        with pytest.raises(SimulatedCrash):
            answer(world, run_id, APPROVE_TOKEN, "approve")

    world = _reopened(coral_db_uri)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run_id)
    assert answer(world, run_id, APPROVE_TOKEN, "approve").outcome == "duplicate"
    assert _alerts(coral_db_uri, run_id) == [
        (int(AlertKind.GATE), int(AlertPriority.NORMAL), int(AlertStatus.RESOLVED), row.id),
        (
            int(AlertKind.RUN_COMPLETED),
            int(AlertPriority.LOW),
            int(AlertStatus.OPEN),
            alert_subject(run_id, "run"),
        ),
    ]
    world.assert_fold_matches(run_id)


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
    # The pause raised its alert; the gate's stays open for the answer still to come.
    assert [
        (kind, status) for kind, _priority, status, _subject in _alerts(coral_db_uri, run.id)
    ] == [
        (int(AlertKind.GATE), int(AlertStatus.OPEN)),
        (int(AlertKind.PAUSE), int(AlertStatus.OPEN)),
    ]


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
    # One gate alert, resolved, and one run-end alert, whichever replica won.
    assert [
        (kind, status) for kind, _priority, status, _subject in _alerts(coral_db_uri, run.id)
    ] == [
        (int(AlertKind.GATE), int(AlertStatus.RESOLVED)),
        (int(AlertKind.RUN_COMPLETED), int(AlertStatus.OPEN)),
    ]
    world.assert_fold_matches(run.id)


async def test_a_restart_republishes_each_live_visit_as_first_shown_and_takes_its_answer(
    coral_db_uri: str,
) -> None:
    world = World.sql(coral_db_uri)
    live = start(world, GATE_ONLY, spec=run_spec(start_key="live"), start_key="live")
    answered = start(world, GATE_ONLY, spec=run_spec(start_key="answered"), start_key="answered")
    shown = RecordingGatePublisher()
    threads = BridgeThreads(world.bridge)
    try:
        for run in (live, answered):
            await publish_live(
                shown,
                threads,
                workspace_id=WORKSPACE,
                run_id=run.id,
                visit_ids=[row.id for row in gate_rows(world, run.id)],
            )
    finally:
        threads.close()
    assert answer(world, answered.id, APPROVE_TOKEN, "approve").outcome == "accepted"
    live_anchor = anchor_session_id(WORKSPACE, live.id)

    # A new process: no prompt survived; the startup sweep republishes from the rows.
    world = _reopened(coral_db_uri)
    republished = RecordingGatePublisher()
    threads = BridgeThreads(world.bridge)
    bindings = SqlAlchemySessionBindingStore(coral_db_uri)
    bindings.reserve(
        SessionBindingDraft(
            workspace_id=WORKSPACE,
            session_id=live_anchor,
            run_id=live.id,
            role="anchor",
            effect_key=f"{live.id}:0:create_session:anchor",
        )
    )
    for progress in (SessionBindingProgress.ROW_CREATED, SessionBindingProgress.INITIALIZED):
        bindings.record_progress(WORKSPACE, live_anchor, progress)
    republisher = GateRepublisher(
        threads, republished, bindings=bindings, prompts=FakeGatePrompts(republished)
    )
    try:
        report = await startup_recovery_sweep(
            world.runs, world.queue, gate_republisher=republisher
        )
        (elicitation_id,) = [row.elicitation_id for row in gate_rows(world, live.id)]
        assert elicitation_id is not None
        verdict = await GateAnswers(
            threads=threads, bindings=bindings, run_store=world.runs
        ).answer(
            GateAnswer(
                workspace_id=WORKSPACE,
                session_id=live_anchor,
                elicitation_id=elicitation_id,
                action="accept",
                content={"decision": "approve"},
                viewer=Viewer(user_id=USER),
            )
        )
    finally:
        threads.close()

    assert republished.pending == {
        (live_anchor, elicitation_id): shown.pending[(live_anchor, elicitation_id)]
    }
    assert (report.open_gates_scanned, report.open_gates_republished) == (1, 1)
    assert verdict == GateVerdict(status="accepted")
    assert _gate_alert(coral_db_uri, live.id).status == int(AlertStatus.RESOLVED)
