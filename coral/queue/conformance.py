"""Reusable conformance harness for Coral effect executors."""

from __future__ import annotations

from typing import Any

import pytest

from coral.queue.executors import (
    EffectCompleted,
    EffectExecutor,
    EffectFailed,
    ExecutionContext,
    StartupLeaseLost,
)
from coral.stores.fakes import FakeQueueStore, FakeRunStore
from coral.stores.protocols import WorkItemDraft


async def run_executor_conformance(
    executor_fn: EffectExecutor,
    *,
    effect_type: str = "conformance.test",
    payload: dict[str, Any] | None = None,
    workspace_id: int = 1,
    run_id: str = "run-conformance-1",
) -> None:
    """Verify that an EffectExecutor obeys idempotency, outcome typing, and lease fencing."""
    run_store = FakeRunStore(default_workspace_id=workspace_id)
    queue_store = FakeQueueStore(run_store=run_store, default_workspace_id=workspace_id)

    body = dict(payload or {})
    body.setdefault("effect_type", effect_type)
    draft = WorkItemDraft.effect(
        run_id=run_id,
        idempotency_key=f"conformance:{effect_type}",
        payload=body,
    )
    queue_store.enqueue_work([draft], workspace_id=workspace_id, now=1000)
    claimed = queue_store.claim_work(
        "worker-conformance",
        workspace_id=workspace_id,
        lease_seconds=60,
        now_fn=lambda: 1000.0,
    )
    assert claimed is not None

    async def _valid_lease() -> bool:
        return queue_store.renew_lease(
            claimed.id,
            worker_id="worker-conformance",
            lease_seconds=60,
            workspace_id=workspace_id,
            now_fn=lambda: 1010.0,
        )

    ctx1 = ExecutionContext(
        work=claimed,
        workspace_id=workspace_id,
        run_id=run_id,
        worker_id="worker-conformance",
        lease_seconds=60,
        _ensure_lease_fn=_valid_lease,
        _lease_expires_at=claimed.lease_expires_at,
    )
    outcome1 = await executor_fn(ctx1)
    assert isinstance(outcome1, (EffectCompleted, EffectFailed))

    ctx2 = ExecutionContext(
        work=claimed,
        workspace_id=workspace_id,
        run_id=run_id,
        worker_id="worker-conformance",
        lease_seconds=60,
        _ensure_lease_fn=_valid_lease,
        _lease_expires_at=claimed.lease_expires_at,
    )
    outcome2 = await executor_fn(ctx2)
    assert isinstance(outcome2, type(outcome1))
    if isinstance(outcome1, EffectCompleted) and isinstance(outcome2, EffectCompleted):
        assert outcome2.result == outcome1.result
    elif isinstance(outcome1, EffectFailed) and isinstance(outcome2, EffectFailed):
        assert outcome2.error_code == outcome1.error_code
        assert outcome2.retryable == outcome1.retryable

    async def _expired_lease() -> bool:
        return queue_store.renew_lease(
            claimed.id,
            worker_id="worker-conformance",
            lease_seconds=60,
            workspace_id=workspace_id,
            now_fn=lambda: 5000.0,
        )

    expired_ctx = ExecutionContext(
        work=claimed,
        workspace_id=workspace_id,
        run_id=run_id,
        worker_id="worker-conformance",
        lease_seconds=60,
        _ensure_lease_fn=_expired_lease,
        _lease_expires_at=claimed.lease_expires_at,
    )
    with pytest.raises(StartupLeaseLost):
        await expired_ctx.ensure_lease()


__all__ = ["run_executor_conformance"]
