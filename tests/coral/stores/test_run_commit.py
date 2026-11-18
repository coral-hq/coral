"""Unit tests for the optimistic CAS commit_with_retry loop and in-memory fakes."""

from __future__ import annotations

import hashlib

import pytest

from coral.stores.fakes import FakeQueueStore, FakeRunStore
from coral.stores.protocols import (
    CommitOutcome,
    LogEntryDraft,
    QueueStore,
    RunContended,
    RunStartSpec,
    RunState,
    RunStatus,
    RunStore,
    Transition,
)
from coral.stores.run_commit import commit_with_retry


def test_fake_stores_satisfy_protocols() -> None:
    """Verify that FakeRunStore and FakeQueueStore satisfy the runtime Protocol checks."""
    run_store = FakeRunStore()
    queue_store = FakeQueueStore()
    assert isinstance(run_store, RunStore)
    assert isinstance(queue_store, QueueStore)


def test_empty_transition_is_noop() -> None:
    """An empty transition does not bump version or write logs."""
    store = FakeRunStore()
    spec = RunStartSpec(
        workflow_id="wf_test",
        version_id="ver_1",
        title="Test Run",
        request_preview="Preview",
    )
    run = store.start_run(spec)

    reduce_calls = 0

    def reduce_fn(state: RunState) -> Transition:
        nonlocal reduce_calls
        reduce_calls += 1
        return Transition.empty()

    outcome = commit_with_retry(
        run_store=store,
        workspace_id=run.workspace_id,
        run_id=run.id,
        reduce_fn=reduce_fn,
    )

    assert outcome.applied is False
    assert outcome.version == 1
    assert reduce_calls == 1

    stored_run = store.get_run(run.id, workspace_id=run.workspace_id)
    assert stored_run is not None
    assert stored_run.version == 1


def test_critic_r1_receipt_found_on_retry_never_reinvokes_reducer() -> None:
    """A concurrent commit with the same receipt key is detected on retry without re-reducing."""
    store = FakeRunStore()
    spec = RunStartSpec(
        workflow_id="wf_test",
        version_id="ver_1",
        title="Test Run",
        request_preview="Preview",
    )
    run = store.start_run(spec)
    cmd_cksum = hashlib.sha256(b"cmd:action_123").digest()

    reduce_calls = 0

    def reduce_fn(state: RunState) -> Transition:
        nonlocal reduce_calls
        reduce_calls += 1
        return Transition(
            status=int(RunStatus.RUNNING),
            logs=(
                LogEntryDraft(
                    kind=1,
                    actor_kind=1,
                    body='{"step": 1}',
                    idempotency_cksum=cmd_cksum,
                ),
            ),
        )

    # Inject a concurrent writer during caller's first apply_transition attempt
    hook_fired = False

    def on_before_apply(run_id: str, expected_version: int) -> None:
        nonlocal hook_fired
        if not hook_fired:
            hook_fired = True
            # Simulate a concurrent worker committing the same command at expected_version
            store.apply_transition(
                run_id=run_id,
                expected_version=expected_version,
                transition=Transition(
                    status=int(RunStatus.RUNNING),
                    logs=(
                        LogEntryDraft(
                            kind=1,
                            actor_kind=1,
                            body='{"step": 1, "worker": "concurrent"}',
                            idempotency_cksum=cmd_cksum,
                        ),
                    ),
                ),
                workspace_id=run.workspace_id,
            )

    store.before_apply_hook = on_before_apply

    no_sleeps = 0

    def fake_sleep(dur: float) -> None:
        nonlocal no_sleeps
        no_sleeps += 1

    outcome = commit_with_retry(
        run_store=store,
        workspace_id=run.workspace_id,
        run_id=run.id,
        reduce_fn=reduce_fn,
        command_idempotency_cksum=cmd_cksum,
        sleep=fake_sleep,
    )

    # First attempt: load_state (v1) -> reduce_fn (call 1) -> hook commits (v2) ->
    # apply_transition raises RunVersionConflict (expected 1, actual 2) ->
    # retry loop sleeps -> iteration 2 starts -> find_receipt returns receipt committed by hook ->
    # returns immediately WITHOUT calling reduce_fn a second time!
    assert hook_fired is True
    assert outcome.applied is False
    assert outcome.version == 2
    assert outcome.receipt is not None
    assert outcome.receipt.idempotency_cksum == cmd_cksum
    assert reduce_calls == 1  # Crucial R1 assertion!
    assert no_sleeps == 1


def test_commit_with_retry_conflict_eventual_success() -> None:
    """When a version conflict occurs, backoff and retry succeed on subsequent attempts."""
    store = FakeRunStore()
    spec = RunStartSpec(
        workflow_id="wf_test",
        version_id="ver_1",
        title="Test Run",
        request_preview="Preview",
    )
    run = store.start_run(spec)

    attempts = 0

    def reduce_fn(state: RunState) -> Transition:
        nonlocal attempts
        attempts += 1
        return Transition(
            status=int(RunStatus.RUNNING),
            logs=(
                LogEntryDraft(
                    kind=1,
                    actor_kind=1,
                    body=f'{{"attempt": {attempts}}}',
                ),
            ),
        )

    conflict_injected = False

    def on_before_apply(run_id: str, expected_version: int) -> None:
        nonlocal conflict_injected
        if not conflict_injected:
            conflict_injected = True
            # Bump run version so first caller attempt conflicts
            store.apply_transition(
                run_id=run_id,
                expected_version=expected_version,
                transition=Transition(
                    status=int(RunStatus.RUNNING),
                    logs=(
                        LogEntryDraft(
                            kind=1,
                            actor_kind=1,
                            body='{"bump": true}',
                        ),
                    ),
                ),
                workspace_id=run.workspace_id,
            )

    store.before_apply_hook = on_before_apply

    outcome = commit_with_retry(
        run_store=store,
        workspace_id=run.workspace_id,
        run_id=run.id,
        reduce_fn=reduce_fn,
        sleep=lambda _: None,
    )

    assert outcome.applied is True
    assert outcome.version == 3  # v1 -> v2 (bump) -> v3 (caller)
    assert attempts == 2


def test_commit_with_retry_exhausted_raises_run_contended() -> None:
    """Exhausting max_attempts raises RunContended."""
    store = FakeRunStore()
    spec = RunStartSpec(
        workflow_id="wf_test",
        version_id="ver_1",
        title="Test Run",
        request_preview="Preview",
    )
    run = store.start_run(spec)

    def on_before_apply(run_id: str, expected_version: int) -> None:
        # Always bump version so every attempt conflicts
        store.apply_transition(
            run_id=run_id,
            expected_version=expected_version,
            transition=Transition(
                logs=(LogEntryDraft(kind=1, actor_kind=1, body="bump"),),
            ),
            workspace_id=run.workspace_id,
        )

    store.before_apply_hook = on_before_apply

    with pytest.raises(RunContended) as exc_info:
        commit_with_retry(
            run_store=store,
            workspace_id=run.workspace_id,
            run_id=run.id,
            reduce_fn=lambda state: Transition(status=int(RunStatus.RUNNING)),
            max_attempts=3,
            sleep=lambda _: None,
        )

    assert f"Run {run.id!r} version conflict after 3 attempts" in str(exc_info.value)


def test_account_checker_invoked_and_aborts_on_failure() -> None:
    """An account checker is invoked once before any reducer or store access."""
    store = FakeRunStore()
    checker_called = 0

    def bad_account() -> None:
        nonlocal checker_called
        checker_called += 1
        raise PermissionError("Account suspended")

    with pytest.raises(PermissionError, match="Account suspended"):
        commit_with_retry(
            run_store=store,
            workspace_id=1,
            run_id="run_123",
            reduce_fn=lambda state: Transition.empty(),
            account_checker=bad_account,
        )

    assert checker_called == 1


def test_lock_timeout_reaches_every_apply_attempt() -> None:
    """The lock timeout is passed to each CAS attempt, the retried one included."""

    class RecordingRunStore(FakeRunStore):
        lock_timeouts: list[float | None]

        def apply_transition(
            self,
            run_id: str,
            expected_version: int,
            transition: Transition,
            *,
            workspace_id: int | None = None,
            now: int | None = None,
            lock_timeout_s: float | None = None,
        ) -> CommitOutcome:
            self.lock_timeouts.append(lock_timeout_s)
            return super().apply_transition(
                run_id,
                expected_version,
                transition,
                workspace_id=workspace_id,
                now=now,
                lock_timeout_s=lock_timeout_s,
            )

    store = RecordingRunStore()
    store.lock_timeouts = []
    run = store.start_run(
        RunStartSpec(workflow_id="wf", version_id="v1", title="Run", request_preview="")
    )
    conflicted = False

    def conflict_once(run_id: str, expected_version: int) -> None:
        nonlocal conflicted
        if not conflicted:
            conflicted = True
            store.apply_transition(
                run_id, expected_version, Transition(status=int(RunStatus.RUNNING))
            )

    store.before_apply_hook = conflict_once

    outcome = commit_with_retry(
        run_store=store,
        workspace_id=run.workspace_id,
        run_id=run.id,
        reduce_fn=lambda state: Transition(logs=(LogEntryDraft(kind=1, actor_kind=1, body="x"),)),
        sleep=lambda _: None,
        lock_timeout_s=10,
    )

    assert outcome.applied is True
    # The caller's two attempts carry the timeout; the injected writer passed none.
    assert store.lock_timeouts == [10, None, 10]
