"""Alerts the bridge's commits raise and resolve: gates, pauses, decision watchdogs, run ends."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any, get_args

import pytest

from coral.alerts.rules import PAUSE_MESSAGES, alert_id, alert_subject
from coral.alerts.types import AlertPayload
from coral.db.enum_codecs import AlertKind, AlertPriority, AlertStatus, RunPauseReason, RunStatus
from coral.engine.timers import WATCHDOG_ALERT, WATCHDOG_REMIND
from coral.engine.types import ChooseArrow, Input, PauseReason, PauseRun, TimerDue
from coral.model.ids import anchor_session_id
from coral.recovery.pause import pause_run_once
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import AlertRecord, AlertResolution, CommitOutcome, Transition
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
    ASKED_AGAIN,
    CHANGE_TOKEN,
    GATE_ONLY,
    GATED,
    HOLD_TOKEN,
    IMPLEMENT_AGAIN,
    GateIds,
    answer,
    before_next_commit,
    gate_rows,
    hand_off,
)
from tests.coral.bridge._world import USER, WORKSPACE, World, run_spec, start
from tests.coral.workflow_builders import fixture_text

LOOP = fixture_text("loop")
WORK_1 = "work||a4:1:0"
DECISION_1 = "review||a4:1"
GENERATION = "gen-1"


@pytest.fixture
def gate_ids() -> GateIds:
    return GateIds()


@pytest.fixture
def world(tmp_path: Path, gate_ids: GateIds) -> World:
    return World.fake(tmp_path, gate_ids=gate_ids)


def _alerts(world: World, run_id: str) -> list[AlertRecord]:
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    return runs.list_alerts(run_id, workspace_id=WORKSPACE)


def _of_kind(world: World, run_id: str, kind: AlertKind) -> list[AlertRecord]:
    return [alert for alert in _alerts(world, run_id) if alert.kind == int(kind)]


def _status(alert: AlertRecord) -> AlertStatus:
    return AlertStatus(alert.status)


def _payload(alert: AlertRecord) -> AlertPayload:
    return AlertPayload.model_validate_json(alert.payload)


def _table(world: World, run_id: str) -> list[tuple[AlertKind, AlertStatus, AlertPriority]]:
    """The run's alerts as kind, status and priority, in that order."""
    return sorted(
        (AlertKind(alert.kind), _status(alert), AlertPriority(alert.priority))
        for alert in _alerts(world, run_id)
    )


def _owners(world: World, run_id: str) -> set[tuple[str | None, str | None]]:
    return {(alert.owner_user_id, alert.account_generation) for alert in _alerts(world, run_id)}


def _commit(world: World, run_id: str, *inputs: Input) -> None:
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: inputs
    )


def _pause_row(world: World, run_id: str, reason: RunPauseReason) -> bool:
    """A store-only pause, as drift and an unloadable run make it; once per pause epoch."""
    return pause_run_once(
        world.runs,
        workspace_id=WORKSPACE,
        run_id=run_id,
        reason=reason,
        body={"kind": "pause_run", "reason": reason.name.lower(), "detail": "test"},
        checksum_parts=("test-pause", run_id),
        now_us=world.clock.epoch * 1_000_000,
    ).applied


def _applied_commits(monkeypatch: pytest.MonkeyPatch, world: World) -> list[Transition]:
    """Every transition the run store applies from now on, in order."""
    applied: list[Transition] = []
    apply = world.runs.apply_transition

    def recording(
        run_id: str, expected_version: int, transition: Transition, **options: Any
    ) -> CommitOutcome:
        outcome = apply(run_id, expected_version, transition, **options)
        if outcome.applied:
            applied.append(transition)
        return outcome

    monkeypatch.setattr(world.runs, "apply_transition", recording)
    return applied


def test_an_open_gate_raises_one_alert_naming_its_row_s_prompt(
    world: World, gate_ids: GateIds
) -> None:
    run = start(world, GATE_ONLY)

    (row,) = gate_rows(world, run.id)
    (alert,) = _alerts(world, run.id)
    anchor = anchor_session_id(WORKSPACE, run.id)
    assert (alert.id, alert.kind, alert.priority, alert.status, alert.subject_id) == (
        alert_id(WORKSPACE, run.id, "gate", row.id),
        int(AlertKind.GATE),
        int(AlertPriority.NORMAL),
        int(AlertStatus.OPEN),
        row.id,
    )
    assert (alert.owner_user_id, alert.created_at) == (USER, world.clock.epoch)
    payload = _payload(alert)
    assert (payload.elicitation_id, payload.session_id) == (gate_ids.issued[0], anchor)
    assert payload.approve_link == f"/approve/{anchor}/{gate_ids.issued[0]}"
    assert (payload.node_id, payload.outcomes) == ("approve", ("approve", "reject"))

    # A repeated start, resyncs, a user pause and its resume raise nothing more.
    world.clock.advance(60)
    start(world, GATE_ONLY)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    _commit(world, run.id, PauseRun(reason="user", detail="look"))
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    assert _alerts(world, run.id) == [alert]


def test_an_answer_resolves_the_gate_alert_and_the_finished_run_raises_its_own(
    world: World,
) -> None:
    run = start(world, GATE_ONLY)
    world.clock.advance(30)

    assert answer(world, run.id, APPROVE_TOKEN, "approve").outcome == "accepted"

    (gate_alert,) = _of_kind(world, run.id, AlertKind.GATE)
    (completed,) = _of_kind(world, run.id, AlertKind.RUN_COMPLETED)
    assert (_status(gate_alert), gate_alert.resolved_at) == (
        AlertStatus.RESOLVED,
        world.clock.epoch,
    )
    assert (_status(completed), completed.priority, completed.subject_id) == (
        AlertStatus.OPEN,
        int(AlertPriority.LOW),
        alert_subject(run.id, "run"),
    )
    assert _payload(completed).title == "Run completed"
    # A repeated answer and a resync change nothing.
    alerts = _alerts(world, run.id)
    assert answer(world, run.id, APPROVE_TOKEN, "approve").outcome == "duplicate"
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    assert _alerts(world, run.id) == alerts
    world.assert_fold_matches(run.id)


def test_an_answer_that_asks_the_gate_again_resolves_and_raises_in_one_commit(
    world: World, gate_ids: GateIds, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world, ASKED_AGAIN)
    commits = _applied_commits(monkeypatch, world)

    assert answer(world, run.id, HOLD_TOKEN, "reject").outcome == "accepted"

    (commit,) = commits
    first, second = gate_rows(world, run.id)
    assert [draft.subject_id for draft in commit.alert_raises] == [second.id]
    assert list(commit.alert_resolutions) == [AlertResolution(subject_id=first.id)]
    by_subject = {alert.subject_id: alert for alert in _of_kind(world, run.id, AlertKind.GATE)}
    assert _status(by_subject[first.id]) == AlertStatus.RESOLVED
    assert _status(by_subject[second.id]) == AlertStatus.OPEN
    assert _payload(by_subject[second.id]).elicitation_id == gate_ids.issued[1]


def test_a_loop_back_through_the_step_raises_the_next_visit_s_alert(world: World) -> None:
    run = start(world, GATED)
    hand_off(world, run.id)
    (asked,) = _of_kind(world, run.id, AlertKind.GATE)

    assert answer(world, run.id, CHANGE_TOKEN, "reject").outcome == "accepted"
    assert [_status(alert) for alert in _of_kind(world, run.id, AlertKind.GATE)] == [
        AlertStatus.RESOLVED
    ]
    hand_off(world, run.id, IMPLEMENT_AGAIN)

    first, second = gate_rows(world, run.id)
    by_subject = {alert.subject_id: alert for alert in _of_kind(world, run.id, AlertKind.GATE)}
    assert set(by_subject) == {first.id, second.id} and asked.subject_id == first.id
    assert _status(by_subject[first.id]) == AlertStatus.RESOLVED
    assert _status(by_subject[second.id]) == AlertStatus.OPEN
    assert _payload(by_subject[second.id]).elicitation_id == second.elicitation_id


def test_a_cancel_at_an_open_gate_resolves_its_alert_and_raises_run_cancelled(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world, GATE_ONLY)
    commits = _applied_commits(monkeypatch, world)

    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")

    (commit,) = commits
    assert [draft.kind for draft in commit.alert_raises] == [int(AlertKind.RUN_CANCELLED)]
    assert commit.alert_resolutions
    (gate_alert,) = _of_kind(world, run.id, AlertKind.GATE)
    (cancelled,) = _of_kind(world, run.id, AlertKind.RUN_CANCELLED)
    assert _status(gate_alert) == AlertStatus.RESOLVED
    assert (_status(cancelled), cancelled.priority) == (AlertStatus.OPEN, int(AlertPriority.LOW))
    assert _payload(cancelled).message == "The run was cancelled."


def test_an_engine_pause_raises_an_alert_each_time_and_a_resume_resolves_it(
    world: World,
) -> None:
    run = start(world, GATE_ONLY)

    _commit(world, run.id, PauseRun(reason="infra", detail="look"))
    (paused,) = _of_kind(world, run.id, AlertKind.PAUSE)
    assert (_status(paused), _payload(paused).pause_reason) == (AlertStatus.OPEN, "infra")
    assert paused.subject_id == alert_subject(run.id, "pause")

    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")
    assert [_status(alert) for alert in _of_kind(world, run.id, AlertKind.PAUSE)] == [
        AlertStatus.RESOLVED
    ]

    # A user pause raises nothing; a later pause raises its own alert.
    _commit(world, run.id, PauseRun(reason="user", detail="look"))
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")
    world.clock.advance(60)
    _commit(world, run.id, PauseRun(reason="infra", detail="again"))
    first, again = _of_kind(world, run.id, AlertKind.PAUSE)
    assert first.id == paused.id != again.id
    assert (_status(first), _status(again)) == (AlertStatus.RESOLVED, AlertStatus.OPEN)
    world.assert_fold_matches(run.id)


@pytest.mark.parametrize(
    ("cause", "after_resume"),
    [
        pytest.param("failure_path", RunStatus.PAUSED, id="resume-keeps-it-paused"),
        pytest.param("infra", RunStatus.RUNNING, id="resume-continues"),
    ],
)
def test_a_cause_added_under_a_user_pause_raises_an_alert_the_usual_rules_resolve(
    world: World, cause: PauseReason, after_resume: RunStatus
) -> None:
    run = start(world, GATE_ONLY)
    _commit(world, run.id, PauseRun(reason="user", detail="look"))
    assert _of_kind(world, run.id, AlertKind.PAUSE) == []

    _commit(world, run.id, PauseRun(reason=cause, detail="effect.permanent"))

    (paused,) = _of_kind(world, run.id, AlertKind.PAUSE)
    assert (_status(paused), _payload(paused).pause_reason) == (AlertStatus.OPEN, cause)
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    assert _of_kind(world, run.id, AlertKind.PAUSE) == [paused]

    # The resume clears the user's cause; the alert stays while the run stays paused.
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")
    assert world.run(run.id).status == int(after_resume)
    (resumed,) = _of_kind(world, run.id, AlertKind.PAUSE)
    assert resumed.id == paused.id
    if after_resume == RunStatus.PAUSED:
        assert _status(resumed) == AlertStatus.OPEN
        world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")
    (resolved,) = _of_kind(world, run.id, AlertKind.PAUSE)
    assert _status(resolved) == AlertStatus.RESOLVED
    world.assert_fold_matches(run.id)


def test_a_store_only_pause_raises_its_alert_and_the_run_s_end_resolves_it(
    world: World,
) -> None:
    run = start(world, GATE_ONLY)
    version = world.run(run.id).version

    assert _pause_row(world, run.id, RunPauseReason.FAILURE_PATH)
    assert not _pause_row(world, run.id, RunPauseReason.FAILURE_PATH)
    (paused,) = _of_kind(world, run.id, AlertKind.PAUSE)
    assert paused.id == alert_id(WORKSPACE, run.id, "pause", str(version + 1))
    assert (_status(paused), _payload(paused).pause_reason) == (AlertStatus.OPEN, "failure_path")

    # The engine still runs, so the gate takes its answer and the run completes.
    assert answer(world, run.id, APPROVE_TOKEN, "approve").outcome == "accepted"
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    assert [_status(alert) for alert in _of_kind(world, run.id, AlertKind.PAUSE)] == [
        AlertStatus.RESOLVED
    ]
    assert [_status(alert) for alert in _of_kind(world, run.id, AlertKind.RUN_COMPLETED)] == [
        AlertStatus.OPEN
    ]


def test_a_resume_lifts_a_store_only_pause_and_resolves_its_alert(world: World) -> None:
    run = start(world, GATE_ONLY, spec=run_spec(account_generation=GENERATION))
    assert _pause_row(world, run.id, RunPauseReason.DRIFT)
    (paused,) = _of_kind(world, run.id, AlertKind.PAUSE)
    assert paused.id == alert_id(WORKSPACE, run.id, "pause", str(world.run(run.id).version))

    # The engine never paused: the resume lifts the row's pause alone.
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")
    assert world.run(run.id).status == int(RunStatus.RUNNING)
    assert _table(world, run.id) == [
        (AlertKind.GATE, AlertStatus.OPEN, AlertPriority.NORMAL),
        (AlertKind.PAUSE, AlertStatus.RESOLVED, AlertPriority.NORMAL),
    ]

    # The next detection is a new pause with its own alert; the resolved one stays resolved.
    world.clock.advance(60)
    assert _pause_row(world, run.id, RunPauseReason.DRIFT)
    first, again = _of_kind(world, run.id, AlertKind.PAUSE)
    assert first.id == paused.id != again.id
    assert again.id == alert_id(WORKSPACE, run.id, "pause", str(world.run(run.id).version))
    assert (_status(first), _status(again)) == (AlertStatus.RESOLVED, AlertStatus.OPEN)
    assert _owners(world, run.id) == {(USER, GENERATION)}
    world.assert_fold_matches(run.id)


@pytest.mark.parametrize("reason", [item for item in get_args(PauseReason) if item != "user"])
def test_every_engine_pause_cause_raises_one_alert_that_the_cancel_resolves(
    world: World, reason: PauseReason
) -> None:
    run = start(world, GATE_ONLY, spec=run_spec(account_generation=GENERATION))

    _commit(world, run.id, PauseRun(reason=reason, detail="look"))

    (paused,) = _of_kind(world, run.id, AlertKind.PAUSE)
    assert paused.id == alert_id(WORKSPACE, run.id, "pause", str(world.run(run.id).version))
    assert (_payload(paused).pause_reason, _payload(paused).message) == (
        reason,
        PAUSE_MESSAGES[reason],
    )
    # Another cause while paused and a resync raise nothing more.
    _commit(world, run.id, PauseRun(reason="infra", detail="also"))
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    assert _of_kind(world, run.id, AlertKind.PAUSE) == [paused]

    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")

    assert _table(world, run.id) == [
        (AlertKind.GATE, AlertStatus.RESOLVED, AlertPriority.NORMAL),
        (AlertKind.PAUSE, AlertStatus.RESOLVED, AlertPriority.NORMAL),
        (AlertKind.RUN_CANCELLED, AlertStatus.OPEN, AlertPriority.LOW),
    ]
    assert _owners(world, run.id) == {(USER, GENERATION)}
    world.assert_fold_matches(run.id)


def test_a_decision_s_watchdog_alert_stage_raises_an_alert_its_choice_resolves(
    world: World,
) -> None:
    run = start(world, LOOP)
    hand_off(world, run.id, WORK_1)
    opened = world.clock.now

    world.clock.now = opened + timedelta(minutes=30)
    _commit(world, run.id, TimerDue(timer_key=f"{WATCHDOG_REMIND}:{DECISION_1}"))
    assert _of_kind(world, run.id, AlertKind.WATCHDOG) == []

    world.clock.now = opened + timedelta(minutes=60)
    _commit(world, run.id, TimerDue(timer_key=f"{WATCHDOG_ALERT}:{DECISION_1}"))
    world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
    (waiting,) = _of_kind(world, run.id, AlertKind.WATCHDOG)
    assert (_status(waiting), waiting.priority, waiting.subject_id) == (
        AlertStatus.OPEN,
        int(AlertPriority.NORMAL),
        alert_subject(run.id, "decision", DECISION_1),
    )
    assert _payload(waiting).message == "The orchestrator has not chosen at review for an hour."

    _commit(
        world,
        run.id,
        ChooseArrow(
            node_id="review", label="approved", reason="It is done.", iteration_path=("a4:1",)
        ),
    )

    assert [_status(alert) for alert in _of_kind(world, run.id, AlertKind.WATCHDOG)] == [
        AlertStatus.RESOLVED
    ]
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    world.assert_fold_matches(run.id)


def test_a_gate_s_watchdog_raises_no_alert_beyond_its_gate_alert(world: World) -> None:
    run = start(world, GATE_ONLY)
    world.clock.advance(3_600)

    _commit(world, run.id, TimerDue(timer_key=f"{WATCHDOG_ALERT}:approve||"))

    assert [alert.kind for alert in _alerts(world, run.id)] == [int(AlertKind.GATE)]


def test_a_commit_that_loses_its_compare_and_swap_raises_its_alert_once(world: World) -> None:
    run = start(world, GATE_ONLY)

    def pause() -> None:
        _commit(world, run.id, PauseRun(reason="infra", detail="look"))

    before_next_commit(world, pause)
    pause()

    assert [_status(alert) for alert in _of_kind(world, run.id, AlertKind.PAUSE)] == [
        AlertStatus.OPEN
    ]
