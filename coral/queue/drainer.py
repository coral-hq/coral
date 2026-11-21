"""Unified async work queue drainer with lease heartbeat, fencing, holds, and backoff."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable, Collection, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import DBAPIError, SQLAlchemyError, StatementError

from coral.db.enum_codecs import RunStatus, WorkKind, WorkStatus
from coral.omni.protocols import RunScopeRunner
from coral.queue.backoff import compute_effect_backoff
from coral.queue.executors import (
    EffectCompleted,
    EffectFailed,
    EffectOutcome,
    ExecutionContext,
    ExecutorRegistration,
    StartupLeaseLost,
    get_registration,
)
from coral.queue.run_effects import (
    MAX_ERROR_CODE_CHARS,
    MAX_FAILURE_MESSAGE_CHARS,
    describe_exception,
    raise_if_cancelling,
    trim_message,
)
from coral.stores.protocols import QueueStore, WorkItem

_logger = logging.getLogger(__name__)

_TERMINAL_RUN_STATUSES: frozenset[int] = frozenset(
    {
        int(RunStatus.COMPLETED),
        int(RunStatus.FAILED),
        int(RunStatus.CANCELLED),
    }
)

_KIND_NAMES: dict[int, str] = {
    int(WorkKind.SIGNAL): "signal",
    int(WorkKind.TIMER): "timer",
    int(WorkKind.EFFECT): "effect",
}

# Held and retried like any domain wait: a leader can lack executors during an upgrade.
_MISSING_EXECUTOR = EffectFailed(
    error_code="executor.missing",
    message="no executor is registered for this item",
    retryable=True,
)
# The longest hold, so the fences see a held item at least hourly.
MAX_HOLD_DELAY_S = 3600
# How long one attempt may run before it is cancelled and retried: far above the
# longest wait an executor makes (a close's 150 s, a send's 120 s).
DEFAULT_EXECUTION_LIMIT_S = 900.0
# An item claimed this many times the attempt limit without settling (each crash,
# lost lease or error after the claim spends an attempt) fails without running again.
_CLAIMS_PER_ATTEMPT_LIMIT = 2
GENERATION_MISMATCH = "slot.generation_mismatch"


class SlotSuperseded(Exception):
    """A lease check found the row's slot at another generation: the row acts no further."""


# What ``_execute`` returns for a row a lease check found superseded.
_SUPERSEDED = EffectFailed(error_code=GENERATION_MISMATCH, message="the slot moved on")


@dataclass(frozen=True)
class FinishedWork:
    """
    An item the drainer finished SUCCEEDED or FAILED, as the outcome hook sees it.

    :param item: The item as claimed.
    :param status: ``WorkStatus.SUCCEEDED`` or ``WorkStatus.FAILED``.
    :param error_code: The stored code: ``None`` on success, ``infra.transient``
        once retries are exhausted (``result["last_error_code"]`` names the cause).
    :param result: The stored result.
    """

    item: WorkItem
    status: int
    error_code: str | None
    result: dict[str, Any] | None


# Runs after a finish to SUCCEEDED or FAILED committed; never for a hold, a retry or an
# abandon. It is awaited while its run is busy, so it must finish in bounded time.
WorkFinishedHook = Callable[[FinishedWork], Awaitable[None]]
# ``(item, failure, now_s)``: seconds to hold a failed item without spending its
# attempt, or ``None`` for the normal retry. ``item.held_since`` starts a horizon. It
# runs on the event loop, so it must not block (no store reads).
HoldPolicy = Callable[[WorkItem, EffectFailed, int], int | None]


def _bounded(failure: EffectFailed) -> EffectFailed:
    """``failure`` with its code and message cut to what the work row stores."""
    return EffectFailed(
        error_code=failure.error_code[:MAX_ERROR_CODE_CHARS],
        message=trim_message(failure.message, MAX_FAILURE_MESSAGE_CHARS),
        retryable=failure.retryable,
    )


def _result_refused(exc: Exception) -> bool:
    """Whether a finish failed on its result itself: not serializable, or over the column cap."""
    if isinstance(exc, DBAPIError):
        return False
    if isinstance(exc, StatementError):
        # A bind-time refusal, such as the compressed column's size check.
        return isinstance(exc.orig, (TypeError, ValueError))
    return isinstance(exc, (TypeError, ValueError)) and not isinstance(exc, SQLAlchemyError)


def _checked_outcome(returned: object) -> EffectOutcome:
    """The executor's outcome; anything else is its bug, a permanent failure."""
    if isinstance(returned, (EffectCompleted, EffectFailed)):
        return returned
    return EffectFailed(
        error_code="executor.invalid_outcome",
        message=f"the executor returned {type(returned).__name__}, not an outcome",
    )


def _parse_payload_dict(payload: str) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _extract_slot_id(item: WorkItem, payload_dict: dict[str, Any]) -> str | None:
    slot_id = payload_dict.get("slot_id")
    if isinstance(slot_id, str) and slot_id:
        return slot_id
    if item.owner_key:
        if item.owner_key.startswith("slot:"):
            return item.owner_key.removeprefix("slot:")
        return item.owner_key
    return None


def _resolve_executor(item: WorkItem, payload_dict: dict[str, Any]) -> ExecutorRegistration | None:
    for candidate in (
        payload_dict.get("effect_type"),
        payload_dict.get("kind"),
        item.owner_key,
        _KIND_NAMES.get(item.kind),
        str(item.kind),
    ):
        if isinstance(candidate, str) and candidate:
            registration = get_registration(candidate)
            if registration is not None:
                return registration
    return None


class WorkDrainer:
    """
    Drains ready work items from QueueStore with lease fencing, holds and retry backoff.

    :param on_finished: Called after each finish to SUCCEEDED or FAILED; its errors are logged.
    :param hold_policy: Asked first for every failure, a missing executor included.
    :param execution_limit_s: An attempt still running after this long is cancelled
        and ends as a retryable ``executor.timeout``; ``None`` sets no limit.
    :param sleep: The timed sleep of the heartbeat and the limit; tests pass a virtual one.
    """

    def __init__(
        self,
        queue_store: QueueStore,
        *,
        worker_id: str,
        kinds: Sequence[int] = (int(WorkKind.EFFECT),),
        lease_seconds: int = 60,
        heartbeat_interval_s: float | None = None,
        scope_runner: RunScopeRunner | None = None,
        workspace_id: int | None = None,
        clock: Callable[[], float] = time.time,
        rng: Callable[[], float] | None = None,
        max_attempts: int = 8,
        base_backoff_s: float = 1.0,
        max_backoff_s: float = 300.0,
        on_finished: WorkFinishedHook | None = None,
        hold_policy: HoldPolicy | None = None,
        execution_limit_s: float | None = DEFAULT_EXECUTION_LIMIT_S,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        if execution_limit_s is not None and execution_limit_s <= 0:
            raise ValueError("execution_limit_s must be positive")
        self._queue_store = queue_store
        self._worker_id = worker_id
        self._kinds = tuple(int(k) for k in kinds)
        self._lease_seconds = lease_seconds
        self._heartbeat_interval_s = (
            heartbeat_interval_s
            if heartbeat_interval_s is not None
            else max(1.0, lease_seconds / 2.0)
        )
        self._scope_runner = scope_runner
        self._workspace_id = workspace_id
        self._clock = clock
        self._rng = rng
        self._max_attempts = max_attempts
        self._base_backoff_s = base_backoff_s
        self._max_backoff_s = max_backoff_s
        self._on_finished = on_finished
        self._hold_policy = hold_policy
        self._execution_limit_s = execution_limit_s
        self._sleep = sleep

    async def drain_once(self, *, exclude_run_ids: Collection[str] = ()) -> WorkItem | None:
        """Claim and execute at most one ready work item of a run not in ``exclude_run_ids``."""
        claimed = await self.claim(exclude_run_ids=exclude_run_ids)
        if claimed is not None:
            await self.run_claimed(claimed)
        return claimed

    async def claim(self, *, exclude_run_ids: Collection[str] = ()) -> WorkItem | None:
        """Claim the next ready item of a run not in ``exclude_run_ids``."""
        if not self._kinds:
            return None
        return await asyncio.to_thread(
            self._queue_store.claim_work,
            self._worker_id,
            kinds=self._kinds,
            lease_seconds=self._lease_seconds,
            workspace_id=self._workspace_id,
            now_fn=self._clock,
            exclude_run_ids=tuple(exclude_run_ids),
        )

    async def run_claimed(self, claimed: WorkItem) -> None:
        """Fence, execute and finish one claimed item, then run the outcome hook."""
        lease_expires_at = (
            claimed.lease_expires_at
            if claimed.lease_expires_at is not None
            else int(self._clock()) + self._lease_seconds
        )
        payload_dict = _parse_payload_dict(claimed.payload)
        registration = _resolve_executor(claimed, payload_dict)

        run_status = await asyncio.to_thread(
            self._queue_store.get_run_status,
            claimed.run_id,
            workspace_id=claimed.workspace_id,
        )
        if run_status in _TERMINAL_RUN_STATUSES and not (
            registration is not None and registration.runs_after_terminal
        ):
            await self._finish(
                claimed, lease_expires_at, WorkStatus.ABANDONED, error_code="run.terminal"
            )
            return

        fenced_slot = (
            _extract_slot_id(claimed, payload_dict)
            if claimed.slot_generation is not None
            else None
        )
        if fenced_slot is not None and await self._superseded(claimed, fenced_slot):
            await self._finish(
                claimed, lease_expires_at, WorkStatus.ABANDONED, error_code=GENERATION_MISMATCH
            )
            return

        if claimed.attempts > _CLAIMS_PER_ATTEMPT_LIMIT * self._max_attempts:
            _logger.warning(
                "Work item %s was claimed %d times without settling; failing it",
                claimed.id,
                claimed.attempts,
            )
            await self._finish_terminal(
                claimed,
                lease_expires_at,
                WorkStatus.FAILED,
                error_code="infra.transient",
                result={
                    "last_error_code": "work.attempts_exceeded",
                    "message": f"claimed {claimed.attempts} times without settling",
                },
            )
            return
        if registration is None:
            outcome: EffectOutcome = _MISSING_EXECUTOR
        else:
            executed = await self._execute(
                claimed, registration, payload_dict, lease_expires_at, fenced_slot=fenced_slot
            )
            if executed is None:
                return
            outcome, lease_expires_at = executed
            if outcome is _SUPERSEDED:
                await self._finish(
                    claimed, lease_expires_at, WorkStatus.ABANDONED, error_code=GENERATION_MISMATCH
                )
                return
        await self._settle(
            claimed,
            outcome,
            lease_expires_at,
            paused_at_claim=run_status == int(RunStatus.PAUSED),
        )

    async def _superseded(self, claimed: WorkItem, slot_id: str) -> bool:
        """Whether the row's slot is now at another generation than the row names."""
        current = await asyncio.to_thread(
            self._queue_store.get_slot_generation,
            claimed.run_id,
            slot_id,
            workspace_id=claimed.workspace_id,
        )
        return current is not None and current != claimed.slot_generation

    async def _execute(
        self,
        claimed: WorkItem,
        registration: ExecutorRegistration,
        payload_dict: dict[str, Any],
        lease_expires_at: int,
        *,
        fenced_slot: str | None = None,
    ) -> tuple[EffectOutcome, int] | None:
        """
        Run the executor under a lease heartbeat and the execution limit.

        :param fenced_slot: The slot whose generation each ``ensure_lease`` re-reads, so
            a row a retry superseded after its claim acts no further.
        :returns: The outcome and the lease the finish must name (``_SUPERSEDED`` for a
            superseded row); ``None`` when the lease was lost.
        """
        current_lease_expires_at = lease_expires_at
        lease_lock = asyncio.Lock()
        renewals_stopped = False
        ctx = ExecutionContext(
            work=claimed,
            workspace_id=claimed.workspace_id,
            run_id=claimed.run_id,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
            _lease_expires_at=current_lease_expires_at,
        )

        async def _renew_and_record() -> bool:
            nonlocal current_lease_expires_at
            async with lease_lock:
                if renewals_stopped:
                    return False
                renew_now = int(self._clock())
                ok = await asyncio.to_thread(
                    self._queue_store.renew_lease,
                    claimed.id,
                    worker_id=self._worker_id,
                    lease_seconds=self._lease_seconds,
                    workspace_id=claimed.workspace_id,
                    now_fn=lambda: float(renew_now),
                )
                if ok:
                    current_lease_expires_at = renew_now + self._lease_seconds
                    ctx._lease_expires_at = current_lease_expires_at
                return ok

        async def _renew_lease() -> bool:
            # Shielded: a renewal whose caller is cancelled still records the lease its
            # thread committed, so the finish names it.
            return await asyncio.shield(_renew_and_record())

        async def _ensure_lease() -> bool:
            if not await _renew_lease():
                return False
            if fenced_slot is not None and await self._superseded(claimed, fenced_slot):
                raise SlotSuperseded(f"work {claimed.id}'s slot moved to another generation")
            return True

        ctx._ensure_lease_fn = _ensure_lease

        async def _heartbeat_loop() -> None:
            while True:
                await self._sleep(self._heartbeat_interval_s)
                try:
                    ok = await _renew_lease()
                except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- fenced finish
                    raise_if_cancelling(exc)
                    _logger.warning(
                        "Lease heartbeat failed for work_id=%s: %s",
                        claimed.id,
                        describe_exception(exc),
                    )
                    continue
                if not ok:
                    return

        async def _run() -> EffectOutcome:
            async with contextlib.AsyncExitStack() as stack:
                if self._scope_runner is not None:
                    await stack.enter_async_context(
                        self._scope_runner.run_scope(
                            workspace_id=claimed.workspace_id,
                            run_id=claimed.run_id,
                            user_id=payload_dict.get("user_id"),
                            account_generation=payload_dict.get("account_generation"),
                            host_id=payload_dict.get("host_id"),
                            owner_key=claimed.owner_key,
                        )
                    )
                returned = await registration.fn(ctx)
            return _checked_outcome(returned)

        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        try:
            outcome = await self._within_limit(claimed, _run())
        except SlotSuperseded:
            _logger.info(
                "Work item %s stopped at a lease check: its slot moved to another generation",
                claimed.id,
            )
            outcome = _SUPERSEDED
        except StartupLeaseLost:
            _logger.info(
                "Work item %s lost lease during execution on worker %s",
                claimed.id,
                self._worker_id,
            )
            return None
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- a retryable failure
            # A stray cancellation (the executor awaited something cancelled) is one too.
            raise_if_cancelling(exc)
            description = describe_exception(exc)
            _logger.warning(
                "Unhandled exception in effect executor for work_id=%s: %s",
                claimed.id,
                description,
            )
            outcome = EffectFailed(
                error_code=(
                    "executor.cancelled"
                    if isinstance(exc, asyncio.CancelledError)
                    else "executor.unhandled_exception"
                ),
                message=description,
                retryable=True,
            )
        finally:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                heartbeat_task.cancel()
            else:
                # A renewal in flight finishes and is recorded before the finish reads
                # the lease; none starts after.
                async with lease_lock:
                    renewals_stopped = True
                    heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        return outcome, current_lease_expires_at

    async def _within_limit(
        self, claimed: WorkItem, run: Coroutine[Any, Any, EffectOutcome]
    ) -> EffectOutcome:
        """``run``'s outcome, or a retryable ``executor.timeout`` once the limit passes."""
        limit_s = self._execution_limit_s
        if limit_s is None:
            return await run
        execution = asyncio.ensure_future(run)
        timer = asyncio.ensure_future(self._sleep(limit_s))
        returned = False
        try:
            await asyncio.wait({execution, timer}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            returned = execution.done()
            execution.cancel()
            timer.cancel()
            await asyncio.gather(execution, timer, return_exceptions=True)
        if returned:
            # The executor's own exception, a stray cancellation included, reaches the caller.
            return execution.result()
        _logger.warning(
            "Effect executor for work_id=%s ran longer than %d s; cancelled it",
            claimed.id,
            limit_s,
        )
        return EffectFailed(
            error_code="executor.timeout",
            message=f"the executor ran longer than {limit_s:g} s",
            retryable=True,
        )

    async def _settle(
        self,
        claimed: WorkItem,
        outcome: EffectOutcome,
        lease_expires_at: int,
        *,
        paused_at_claim: bool,
    ) -> None:
        """Finish the item by its outcome: success, hold, retry, or failure."""
        if isinstance(outcome, EffectCompleted):
            await self._finish_terminal(
                claimed, lease_expires_at, WorkStatus.SUCCEEDED, result=outcome.result
            )
            return
        failure = _bounded(outcome)
        finish_now = int(self._clock())
        hold_s = self._hold_delay(claimed, failure, finish_now)
        if hold_s is not None:
            if paused_at_claim and await self._left_pause(claimed):
                # The resume's release ran while this item was claimed and could not
                # see it, so it comes back at the store's minimum hold delay.
                hold_s = 0
            await self._finish(
                claimed,
                lease_expires_at,
                WorkStatus.PENDING,
                error_code=failure.error_code,
                next_available_at=finish_now + hold_s,
                hold=True,
                now_s=finish_now,
            )
            return
        if not failure.retryable:
            await self._finish_terminal(
                claimed,
                lease_expires_at,
                WorkStatus.FAILED,
                error_code=failure.error_code,
                result={"message": failure.message} if failure.message else None,
            )
            return
        backoff_s = compute_effect_backoff(
            claimed.attempts,
            base_s=self._base_backoff_s,
            max_s=self._max_backoff_s,
            max_attempts=self._max_attempts,
            rng=self._rng,
        )
        if backoff_s is not None:
            await self._finish(
                claimed,
                lease_expires_at,
                WorkStatus.PENDING,
                error_code=failure.error_code,
                next_available_at=finish_now + backoff_s,
                now_s=finish_now,
            )
            return
        await self._finish_terminal(
            claimed,
            lease_expires_at,
            WorkStatus.FAILED,
            error_code="infra.transient",
            result={"last_error_code": failure.error_code, "message": failure.message},
            now_s=finish_now,
        )

    def _hold_delay(self, claimed: WorkItem, failure: EffectFailed, now_s: int) -> int | None:
        if self._hold_policy is None:
            return None
        try:
            delay = self._hold_policy(claimed, failure, now_s)
            if delay is None:
                return None
            if not math.isfinite(delay):
                raise ValueError(f"hold delay {delay!r} is not finite")
            return min(max(0, int(delay)), MAX_HOLD_DELAY_S)
        except Exception as exc:  # noqa: BLE001 -- logged; the item falls back to retries
            _logger.warning(
                "Hold policy failed for work_id=%s: %s", claimed.id, describe_exception(exc)
            )
            return None

    async def _left_pause(self, claimed: WorkItem) -> bool:
        status = await asyncio.to_thread(
            self._queue_store.get_run_status, claimed.run_id, workspace_id=claimed.workspace_id
        )
        return status != int(RunStatus.PAUSED)

    async def _finish(
        self,
        claimed: WorkItem,
        lease_expires_at: int,
        status: WorkStatus,
        *,
        error_code: str | None = None,
        result: dict[str, Any] | None = None,
        next_available_at: int | None = None,
        hold: bool = False,
        now_s: int | None = None,
    ) -> bool:
        """Finish the claimed item; ``False`` when its lease was fenced off."""
        finished = await asyncio.to_thread(
            self._queue_store.finish_work,
            claimed.id,
            worker_id=self._worker_id,
            expected_lease_expires_at=lease_expires_at,
            status=int(status),
            result=result,
            error_code=error_code,
            next_available_at=next_available_at,
            workspace_id=claimed.workspace_id,
            now_fn=self._clock if now_s is None else functools.partial(float, now_s),
            hold=hold,
        )
        if not finished:
            _logger.warning(
                "Finish of work_id=%s was fenced off: a reclaim or another worker has it",
                claimed.id,
            )
        return finished

    async def _finish_terminal(
        self,
        claimed: WorkItem,
        lease_expires_at: int,
        status: WorkStatus,
        *,
        error_code: str | None = None,
        result: dict[str, Any] | None = None,
        now_s: int | None = None,
    ) -> None:
        """Finish SUCCEEDED or FAILED, then tell the hook if this worker's finish committed."""
        try:
            finished = await self._finish(
                claimed,
                lease_expires_at,
                status,
                error_code=error_code,
                result=result,
                now_s=now_s,
            )
        except Exception as exc:
            # Only a result the store refuses is a permanent failure; a store error is retried.
            if result is None or not _result_refused(exc):
                raise
            _logger.warning(
                "Work item %s has a result that cannot be stored: %s",
                claimed.id,
                describe_exception(exc),
            )
            if status == WorkStatus.SUCCEEDED:
                status, error_code = WorkStatus.FAILED, "effect.result_unstorable"
            result = None
            finished = await self._finish(
                claimed, lease_expires_at, status, error_code=error_code, now_s=now_s
            )
        if not finished or self._on_finished is None:
            return
        try:
            await self._on_finished(FinishedWork(claimed, int(status), error_code, result))
        except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- logged; item finished
            raise_if_cancelling(exc)
            _logger.warning(
                "Work finished hook failed for work_id=%s: %s",
                claimed.id,
                describe_exception(exc),
            )

    async def drain_until_empty(self, *, max_items: int = 100) -> int:
        """Drain ready work items sequentially up to max_items."""
        processed = 0
        for _ in range(max_items):
            item = await self.drain_once()
            if item is None:
                break
            processed += 1
        return processed


__all__ = [
    "DEFAULT_EXECUTION_LIMIT_S",
    "GENERATION_MISMATCH",
    "FinishedWork",
    "HoldPolicy",
    "WorkDrainer",
    "WorkFinishedHook",
]
