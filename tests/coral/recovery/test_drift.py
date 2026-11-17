"""Drift baseline: an archived, deleted or bound session pauses its run once per pause epoch."""

from __future__ import annotations

import hashlib
import json

import pytest

from coral.db.enum_codecs import (
    ActorKind,
    LogKind,
    RunPauseReason,
    RunStatus,
    SessionBindingProgress,
    SessionBindingRole,
    SlotRole,
)
from coral.model.ids import anchor_session_id
from coral.omni.protocols import SessionState
from coral.recovery.drift import (
    DriftDetected,
    DriftFinding,
    DriftPauser,
    classify_anchor,
    classify_step,
    find_drift,
    pause_run_for_drift,
)
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun, Transition
from coral.stores.session_bindings import SessionBinding, effect_checksum
from tests.coral.omni.fakes import FakeSessionFacade, present
from tests.coral.workspace._executor_fakes import FakeBindings, start_run, step_binding

WORKSPACE = 3
STEP = "5" * 32
NOW_US = 1_700_000_000_000_000
ARCHIVED_AT = "1700000000"


def _run(store: FakeRunStore, status: RunStatus = RunStatus.RUNNING) -> CoralRun:
    run = start_run(
        store,
        workspace_id=WORKSPACE,
        user_id="alice",
        account_generation="gen-1",
        host_id=None,
        repo_path=None,
        worktree_path=None,
        run_branch=None,
    )
    if status is not RunStatus.STARTING:
        _apply(store, run, Transition(status=int(status)))
    return run


def _apply(store: FakeRunStore, run: CoralRun, transition: Transition) -> None:
    _, version = store.load_run_state(run.id, workspace_id=WORKSPACE)
    store.apply_transition(run.id, version, transition, workspace_id=WORKSPACE)


def _resume(store: FakeRunStore, run: CoralRun) -> None:
    _apply(store, run, Transition(status=int(RunStatus.RUNNING), clear_pause_reason=True))


def _archived_anchor(run: CoralRun) -> DriftFinding:
    finding = classify_anchor(
        present(anchor_session_id(WORKSPACE, run.id), archived=True, archived_at=ARCHIVED_AT)
    )
    assert finding is not None
    return finding


def _drift_logs(store: FakeRunStore, run: CoralRun) -> list[dict[str, object]]:
    return [
        json.loads(entry.body)
        for entry in store.logs[(WORKSPACE, run.id)]
        if entry.kind == int(LogKind.PAUSED)
    ]


def _anchor_binding(run_id: str, progress: SessionBindingProgress) -> SessionBinding:
    return SessionBinding(
        workspace_id=WORKSPACE,
        session_id=anchor_session_id(WORKSPACE, run_id),
        run_id=run_id,
        role=SessionBindingRole.ANCHOR,
        slot_id=None,
        slot_role=None,
        effect_cksum=effect_checksum(f"{run_id}:0:create_session:anchor"),
        session_generation=1,
        host_id=None,
        progress=progress,
        created_at=0,
        updated_at=0,
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (present("a", exists=False), ("anchor_deleted", "deleted")),
        (present("a", archived=True, archived_at=ARCHIVED_AT), ("anchor_archived", ARCHIVED_AT)),
        (present("a", archived=True), ("anchor_archived", "archived")),
        (present("a", runner_id="runner-1"), ("anchor_bound", "runner-1")),
        (present("a", host_id="host-1"), ("anchor_bound", "host-1")),
        (present("a", closed=True), None),
        (present("a"), None),
    ],
)
def test_classify_anchor(state: SessionState, expected: tuple[str, str] | None) -> None:
    finding = classify_anchor(state)
    assert (None if finding is None else (finding.cause, finding.occurrence)) == expected
    if finding is not None:
        assert finding.session_id == "a"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (present("s", exists=False), ("session_deleted", "deleted")),
        (present("s", archived=True, archived_at=ARCHIVED_AT), ("session_archived", ARCHIVED_AT)),
        # A step runs on its own host and runner.
        (present("s", runner_id="runner-1", host_id="host-1"), None),
        (present("s", closed=True), None),
    ],
)
def test_classify_step(state: SessionState, expected: tuple[str, str] | None) -> None:
    finding = classify_step(state)
    assert (None if finding is None else (finding.cause, finding.occurrence)) == expected


def test_drift_detected_names_the_session_code_and_keeps_the_finding() -> None:
    finding = DriftFinding(cause="session_deleted", session_id=STEP, occurrence="deleted")
    error = DriftDetected(finding)
    assert (error.code, error.retryable, error.finding) == ("session.deleted", False, finding)
    assert DriftDetected(DriftFinding("anchor_bound", STEP, "h")).code == "session.anchor_bound"


@pytest.mark.parametrize("status", [RunStatus.STARTING, RunStatus.RUNNING])
def test_drift_pauses_a_live_run_with_one_paused_log(status: RunStatus) -> None:
    store = FakeRunStore(default_workspace_id=WORKSPACE)
    run = _run(store, status)
    finding = _archived_anchor(run)
    _, version = store.load_run_state(run.id, workspace_id=WORKSPACE)

    outcome = pause_run_for_drift(
        store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=NOW_US
    )

    state, _ = store.load_run_state(run.id, workspace_id=WORKSPACE)
    assert outcome.applied
    assert (state.run.status, state.run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.DRIFT)
    [entry] = [e for e in store.logs[(WORKSPACE, run.id)] if e.kind == int(LogKind.PAUSED)]
    assert entry.actor_kind == int(ActorKind.ENGINE)
    assert entry.created_at_us == NOW_US
    assert json.loads(entry.body) == {
        "kind": "pause_run",
        "reason": "drift",
        "cause": "anchor_archived",
        "session_id": anchor_session_id(WORKSPACE, run.id),
        "detail": ARCHIVED_AT,
    }
    expected_cksum = hashlib.sha256(
        "\0".join(
            ("coral-drift", run.id, "anchor_archived", finding.session_id, str(version))
        ).encode()
    ).digest()
    assert entry.idempotency_cksum == expected_cksum


def test_a_second_detection_in_one_pause_epoch_adds_nothing() -> None:
    store = FakeRunStore(default_workspace_id=WORKSPACE)
    run = _run(store)
    finding = _archived_anchor(run)
    pause_run_for_drift(
        store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=NOW_US
    )
    _, version = store.load_run_state(run.id, workspace_id=WORKSPACE)

    again = pause_run_for_drift(
        store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=NOW_US + 1
    )

    assert not again.applied
    assert store.load_run_state(run.id, workspace_id=WORKSPACE)[1] == version
    assert len(_drift_logs(store, run)) == 1


def test_resume_without_unarchive_pauses_again() -> None:
    store = FakeRunStore(default_workspace_id=WORKSPACE)
    run = _run(store)
    finding = _archived_anchor(run)
    pause_run_for_drift(
        store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=NOW_US
    )

    # The user resumes the run but leaves the anchor archived.
    _resume(store, run)
    again = pause_run_for_drift(
        store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=NOW_US + 1
    )

    state, _ = store.load_run_state(run.id, workspace_id=WORKSPACE)
    assert again.applied
    assert (state.run.status, state.run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.DRIFT)
    entries = [e for e in store.logs[(WORKSPACE, run.id)] if e.kind == int(LogKind.PAUSED)]
    assert len(entries) == 2
    # Each pause epoch has its own log identity.
    assert entries[0].idempotency_cksum != entries[1].idempotency_cksum


def test_a_run_paused_for_another_reason_records_drift_only_after_resume() -> None:
    store = FakeRunStore(default_workspace_id=WORKSPACE)
    run = _run(store)
    _apply(
        store,
        run,
        Transition(status=int(RunStatus.PAUSED), pause_reason=int(RunPauseReason.GATE)),
    )
    finding = _archived_anchor(run)

    while_paused = pause_run_for_drift(
        store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=NOW_US
    )
    assert not while_paused.applied
    state, _ = store.load_run_state(run.id, workspace_id=WORKSPACE)
    assert state.run.pause_reason == RunPauseReason.GATE
    assert _drift_logs(store, run) == []

    _resume(store, run)
    assert pause_run_for_drift(
        store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=NOW_US
    ).applied
    assert len(_drift_logs(store, run)) == 1


@pytest.mark.parametrize("status", [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED])
def test_a_finished_run_is_never_paused(status: RunStatus) -> None:
    store = FakeRunStore(default_workspace_id=WORKSPACE)
    run = _run(store, status)

    outcome = pause_run_for_drift(
        store, workspace_id=WORKSPACE, run_id=run.id, finding=_archived_anchor(run), now_us=NOW_US
    )

    state, _ = store.load_run_state(run.id, workspace_id=WORKSPACE)
    assert not outcome.applied
    assert state.run.status == status
    assert _drift_logs(store, run) == []


def test_concurrent_detectors_pause_the_run_once() -> None:
    store = FakeRunStore(default_workspace_id=WORKSPACE)
    run = _run(store)
    finding = _archived_anchor(run)
    raced: list[bool] = []

    def other_detector_first(_run_id: str, _expected_version: int) -> None:
        if not raced:
            raced.append(True)
            pause_run_for_drift(
                store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=NOW_US
            )

    store.before_apply_hook = other_detector_first
    outcome = pause_run_for_drift(
        store, workspace_id=WORKSPACE, run_id=run.id, finding=finding, now_us=NOW_US
    )

    # This detector lost the compare-and-swap, reloaded and found the run paused.
    assert raced == [True]
    assert not outcome.applied
    assert len(_drift_logs(store, run)) == 1


async def test_drift_pauser_pauses_with_its_clock() -> None:
    store = FakeRunStore(default_workspace_id=WORKSPACE)
    run = _run(store)

    outcome = await DriftPauser(store, now_us=lambda: NOW_US).pause(
        workspace_id=WORKSPACE, run_id=run.id, finding=_archived_anchor(run)
    )

    assert outcome.applied
    [entry] = [e for e in store.logs[(WORKSPACE, run.id)] if e.kind == int(LogKind.PAUSED)]
    assert entry.created_at_us == NOW_US


async def test_find_drift_checks_the_anchor_then_the_bound_target() -> None:
    run_id = "r" * 32
    anchor = anchor_session_id(WORKSPACE, run_id)
    facade = FakeSessionFacade()
    bindings = FakeBindings()

    async def drift(session_id: str | None = STEP) -> DriftFinding | None:
        return await find_drift(
            facade, bindings, workspace_id=WORKSPACE, run_id=run_id, session_id=session_id
        )

    # No anchor binding yet: its create has not run, so nothing has drifted.
    facade.states[(WORKSPACE, anchor)] = present(anchor, exists=False)
    assert await drift(None) is None
    # A reserved anchor whose row is missing was never created.
    bindings.rows[(WORKSPACE, anchor)] = _anchor_binding(run_id, SessionBindingProgress.RESERVED)
    assert await drift(None) is None
    # Once its row was created, a missing row means the user deleted it.
    bindings.rows[(WORKSPACE, anchor)] = _anchor_binding(
        run_id, SessionBindingProgress.ROW_CREATED
    )
    finding = await drift(None)
    assert finding is not None
    assert (finding.cause, finding.session_id) == ("anchor_deleted", anchor)

    facade.states[(WORKSPACE, anchor)] = present(anchor)
    # A target with no binding in this run is not this run's session.
    facade.states[(WORKSPACE, STEP)] = present(STEP, archived=True)
    assert await drift() is None
    bindings.rows[(WORKSPACE, STEP)] = step_binding(
        workspace_id=WORKSPACE,
        run_id="another-run",
        session_id=STEP,
        slot_role=SlotRole.STEP_AGENT,
        host_id="host-1",
    )
    assert await drift() is None
    bindings.rows[(WORKSPACE, STEP)] = step_binding(
        workspace_id=WORKSPACE,
        run_id=run_id,
        session_id=STEP,
        slot_role=SlotRole.STEP_AGENT,
        host_id="host-1",
    )
    finding = await drift()
    assert finding is not None
    assert (finding.cause, finding.session_id) == ("session_archived", STEP)

    # The anchor is checked first.
    facade.states[(WORKSPACE, anchor)] = present(anchor, runner_id="runner-9")
    finding = await drift()
    assert finding is not None
    assert (finding.cause, finding.occurrence) == ("anchor_bound", "runner-9")
