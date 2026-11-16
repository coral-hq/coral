"""Optimistic concurrency compare-and-swap (CAS) commit loop for Coral runs."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from coral.stores.protocols import (
    CommitOutcome,
    RunContended,
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
) -> CommitOutcome:
    """Execute a pure reducer and apply its transition under optimistic CAS with retries.

    If command_idempotency_cksum is supplied, checks for an existing receipt at the start
    of EVERY attempt. If another worker already committed the command, returns the receipt
    immediately without invoking reduce_fn.
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
        transition = reduce_fn(state)
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
            )
        except RunVersionConflict as exc:
            if attempt == max_attempts:
                raise RunContended(
                    f"Run {run_id!r} version conflict after {max_attempts} attempts "
                    f"(expected {exc.expected_version}, actual {exc.actual_version})"
                ) from exc
            jitter = random.uniform(0.5, 1.5)
            backoff = base_backoff_s * (2 ** (attempt - 1)) * jitter
            sleep(backoff)

    raise RunContended(f"Run {run_id!r} version conflict after {max_attempts} attempts")


__all__ = ["commit_with_retry"]
