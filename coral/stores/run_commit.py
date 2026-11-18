"""Optimistic concurrency compare-and-swap (CAS) commit loop for Coral runs."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from coral.stores.protocols import (
    CommitOutcome,
    CoralRun,
    RunContended,
    RunNotFound,
    RunState,
    RunStore,
    RunVersionConflict,
    Transition,
)


def commit_with_retry(
    *,
    run_store: RunStore,
    workspace_id: int,
    run_id: str,
    reduce_fn: Callable[[RunState], Transition],
    command_idempotency_cksum: bytes | None = None,
    max_attempts: int = 5,
    base_backoff_s: float = 0.01,
    sleep: Callable[[float], None] = time.sleep,
    account_checker: Callable[[], None] | None = None,
    now: int | None = None,
    lock_timeout_s: float | None = None,
) -> CommitOutcome:
    """Execute a pure reducer and apply its transition under optimistic CAS with retries.

    If command_idempotency_cksum is supplied, checks for an existing receipt at the start
    of EVERY attempt. If another worker already committed the command, returns the receipt
    immediately without invoking reduce_fn. ``lock_timeout_s`` is passed to every
    ``apply_transition`` attempt.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    if account_checker is not None:
        account_checker()

    for attempt in range(1, max_attempts + 1):
        if command_idempotency_cksum is not None:
            receipt = run_store.find_receipt(
                run_id,
                command_idempotency_cksum,
                workspace_id=workspace_id,
            )
            if receipt is not None:
                return CommitOutcome(
                    run_id=run_id,
                    version=receipt.run_version,
                    applied=False,
                    receipt=receipt,
                    work_ids=(),
                    log_seqs=(receipt.log_seq,),
                )

        state, version = run_store.load_run_state(run_id, workspace_id=workspace_id)
        outcome = _attempt(
            run_store, workspace_id, run_id, version, reduce_fn(state), now, lock_timeout_s
        )
        if isinstance(outcome, CommitOutcome):
            return outcome
        _back_off(run_id, attempt, max_attempts, base_backoff_s, sleep, outcome)

    raise RunContended(f"Run {run_id!r} version conflict after {max_attempts} attempts")


def commit_on_run_row(
    *,
    run_store: RunStore,
    workspace_id: int,
    run_id: str,
    reduce_fn: Callable[[CoralRun], Transition],
    max_attempts: int = 5,
    base_backoff_s: float = 0.01,
    sleep: Callable[[float], None] = time.sleep,
    now: int | None = None,
    lock_timeout_s: float | None = None,
) -> CommitOutcome:
    """Like :func:`commit_with_retry`, but the reducer sees the run row alone.

    For writes that need nothing else, such as pausing a run whose other rows
    cannot be read back.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    for attempt in range(1, max_attempts + 1):
        run = run_store.get_run(run_id, workspace_id=workspace_id)
        if run is None:
            raise RunNotFound(f"Run {run_id!r} not found in workspace {workspace_id}")
        outcome = _attempt(
            run_store, workspace_id, run_id, run.version, reduce_fn(run), now, lock_timeout_s
        )
        if isinstance(outcome, CommitOutcome):
            return outcome
        _back_off(run_id, attempt, max_attempts, base_backoff_s, sleep, outcome)
    raise RunContended(f"Run {run_id!r} version conflict after {max_attempts} attempts")


def _attempt(
    run_store: RunStore,
    workspace_id: int,
    run_id: str,
    version: int,
    transition: Transition,
    now: int | None,
    lock_timeout_s: float | None,
) -> CommitOutcome | RunVersionConflict:
    """Apply one attempt; the conflict when another commit moved the run first."""
    if transition.is_empty:
        return CommitOutcome(
            run_id=run_id,
            version=version,
            applied=False,
            receipt=None,
            work_ids=(),
            log_seqs=(),
        )
    try:
        return run_store.apply_transition(
            run_id,
            expected_version=version,
            transition=transition,
            workspace_id=workspace_id,
            now=now,
            lock_timeout_s=lock_timeout_s,
        )
    except RunVersionConflict as exc:
        return exc


def _back_off(
    run_id: str,
    attempt: int,
    max_attempts: int,
    base_backoff_s: float,
    sleep: Callable[[float], None],
    conflict: RunVersionConflict,
) -> None:
    if attempt == max_attempts:
        raise RunContended(
            f"Run {run_id!r} version conflict after {max_attempts} attempts "
            f"(expected {conflict.expected_version}, actual {conflict.actual_version})"
        ) from conflict
    jitter = random.uniform(0.5, 1.5)
    sleep(base_backoff_s * (2 ** (attempt - 1)) * jitter)


__all__ = ["commit_on_run_row", "commit_with_retry"]
