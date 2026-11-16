"""Unified async work queue drainer with lease heartbeat, fencing, and backoff."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from coral.db.enum_codecs import RunStatus, WorkKind, WorkStatus
from coral.omni.protocols import RunScopeRunner
from coral.queue.backoff import compute_effect_backoff
from coral.queue.executors import (
    EffectCompleted,
    EffectExecutor,
    EffectFailed,
    EffectOutcome,
    ExecutionContext,
    StartupLeaseLost,
    get_executor,
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


def _resolve_executor(item: WorkItem, payload_dict: dict[str, Any]) -> EffectExecutor | None:
    for candidate in (
        payload_dict.get("effect_type"),
        payload_dict.get("kind"),
        item.owner_key,
        _KIND_NAMES.get(item.kind),
        str(item.kind),
    ):
        if isinstance(candidate, str) and candidate:
            executor = get_executor(candidate)
            if executor is not None:
                return executor
    return None


class WorkDrainer:
    """Drains ready work items from QueueStore with lease fencing and retry backoff."""

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
    ) -> None:
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

    async def drain_once(self) -> WorkItem | None:
        """Claim and execute at most one ready work item."""
        if not self._kinds:
            return None

        claimed = await asyncio.to_thread(
            self._queue_store.claim_work,
            self._worker_id,
            kinds=self._kinds,
            lease_seconds=self._lease_seconds,
            workspace_id=self._workspace_id,
            now_fn=self._clock,
        )
        if claimed is None:
            return None

        current_lease_expires_at = (
            claimed.lease_expires_at
            if claimed.lease_expires_at is not None
            else int(self._clock()) + self._lease_seconds
        )
        payload_dict = _parse_payload_dict(claimed.payload)

        run_status = await asyncio.to_thread(
            self._queue_store.get_run_status,
            claimed.run_id,
            workspace_id=claimed.workspace_id,
        )
        if run_status in _TERMINAL_RUN_STATUSES:
            await asyncio.to_thread(
                self._queue_store.finish_work,
                claimed.id,
                worker_id=self._worker_id,
                expected_lease_expires_at=current_lease_expires_at,
                status=int(WorkStatus.ABANDONED),
                error_code="run.terminal",
                workspace_id=claimed.workspace_id,
                now_fn=self._clock,
            )
            return claimed

        if claimed.slot_generation is not None:
            slot_id = _extract_slot_id(claimed, payload_dict)
            if slot_id is not None:
                current_gen = await asyncio.to_thread(
                    self._queue_store.get_slot_generation,
                    claimed.run_id,
                    slot_id,
                    workspace_id=claimed.workspace_id,
                )
                if current_gen is not None and current_gen != claimed.slot_generation:
                    await asyncio.to_thread(
                        self._queue_store.finish_work,
                        claimed.id,
                        worker_id=self._worker_id,
                        expected_lease_expires_at=current_lease_expires_at,
                        status=int(WorkStatus.ABANDONED),
                        error_code="slot.generation_mismatch",
                        workspace_id=claimed.workspace_id,
                        now_fn=self._clock,
                    )
                    return claimed

        executor = _resolve_executor(claimed, payload_dict)
        if executor is None:
            await asyncio.to_thread(
                self._queue_store.finish_work,
                claimed.id,
                worker_id=self._worker_id,
                expected_lease_expires_at=current_lease_expires_at,
                status=int(WorkStatus.FAILED),
                error_code="executor.missing",
                workspace_id=claimed.workspace_id,
                now_fn=self._clock,
            )
            return claimed

        lease_lock = asyncio.Lock()
        ctx = ExecutionContext(
            work=claimed,
            workspace_id=claimed.workspace_id,
            run_id=claimed.run_id,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
            _lease_expires_at=current_lease_expires_at,
        )

        async def _renew_lease() -> bool:
            nonlocal current_lease_expires_at
            async with lease_lock:
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

        ctx._ensure_lease_fn = _renew_lease

        async def _heartbeat_loop() -> None:
            while True:
                await asyncio.sleep(self._heartbeat_interval_s)
                ok = await _renew_lease()
                if not ok:
                    return

        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        try:
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
                outcome: EffectOutcome = await executor(ctx)
        except StartupLeaseLost:
            _logger.info(
                "Work item %s lost lease during execution on worker %s",
                claimed.id,
                self._worker_id,
            )
            return claimed
        except Exception as exc:
            _logger.warning(
                "Unhandled exception in effect executor for work_id=%s: %s",
                claimed.id,
                exc,
                exc_info=True,
            )
            outcome = EffectFailed(
                error_code="executor.unhandled_exception",
                message=str(exc),
                retryable=True,
            )
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

        if isinstance(outcome, EffectCompleted):
            await asyncio.to_thread(
                self._queue_store.finish_work,
                claimed.id,
                worker_id=self._worker_id,
                expected_lease_expires_at=current_lease_expires_at,
                status=int(WorkStatus.SUCCEEDED),
                result=outcome.result,
                workspace_id=claimed.workspace_id,
                now_fn=self._clock,
            )
        elif outcome.retryable:
            backoff_s = compute_effect_backoff(
                claimed.attempts,
                base_s=self._base_backoff_s,
                max_s=self._max_backoff_s,
                max_attempts=self._max_attempts,
                rng=self._rng,
            )
            finish_now = int(self._clock())
            if backoff_s is not None:
                await asyncio.to_thread(
                    self._queue_store.finish_work,
                    claimed.id,
                    worker_id=self._worker_id,
                    expected_lease_expires_at=current_lease_expires_at,
                    status=int(WorkStatus.PENDING),
                    error_code=outcome.error_code,
                    next_available_at=finish_now + backoff_s,
                    workspace_id=claimed.workspace_id,
                    now_fn=lambda: float(finish_now),
                )
            else:
                await asyncio.to_thread(
                    self._queue_store.finish_work,
                    claimed.id,
                    worker_id=self._worker_id,
                    expected_lease_expires_at=current_lease_expires_at,
                    status=int(WorkStatus.FAILED),
                    error_code="infra.transient",
                    result={
                        "last_error_code": outcome.error_code,
                        "message": outcome.message,
                    },
                    workspace_id=claimed.workspace_id,
                    now_fn=lambda: float(finish_now),
                )
        else:
            await asyncio.to_thread(
                self._queue_store.finish_work,
                claimed.id,
                worker_id=self._worker_id,
                expected_lease_expires_at=current_lease_expires_at,
                status=int(WorkStatus.FAILED),
                error_code=outcome.error_code,
                result={"message": outcome.message} if outcome.message else None,
                workspace_id=claimed.workspace_id,
                now_fn=self._clock,
            )

        return claimed

    async def drain_until_empty(self, *, max_items: int = 100) -> int:
        """Drain ready work items sequentially up to max_items."""
        processed = 0
        for _ in range(max_items):
            item = await self.drain_once()
            if item is None:
                break
            processed += 1
        return processed


__all__ = ["WorkDrainer"]
