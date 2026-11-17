"""Unit and conformance tests for effect backoff, executor registry, and conformance harness."""

from __future__ import annotations

import pytest

from coral.queue import (
    EffectCompleted,
    EffectFailed,
    ExecutionContext,
    StartupLeaseLost,
    clear_executors,
    compute_effect_backoff,
    get_executor,
    register_executor,
    registered_executor_kinds,
    run_executor_conformance,
    unregister_executor,
)


def test_compute_effect_backoff_bounds_and_exhaustion() -> None:
    """Verify exponential growth, jitter bounds [0.5x, 1.5x], cap at 300s, and exhaustion at 8."""
    # Attempt 1 with u=0.5 -> jitter=1.0 -> 1s
    assert compute_effect_backoff(1, rng=lambda: 0.5) == 1
    # Attempt 2 with u=0.5 -> jitter=1.0 -> 2s
    assert compute_effect_backoff(2, rng=lambda: 0.5) == 2
    # Attempt 5 with u=0.5 -> 16s
    assert compute_effect_backoff(5, rng=lambda: 0.5) == 16
    # Attempt 7 with u=1.0 -> raw=64 * 1.5 = 96s
    assert compute_effect_backoff(7, rng=lambda: 1.0) == 96
    # Capped at max_s=300 even with max jitter
    assert compute_effect_backoff(7, base_s=100.0, max_s=300.0, rng=lambda: 1.0) == 300
    # Attempt >= 8 returns None (terminal exhaustion)
    assert compute_effect_backoff(8) is None
    assert compute_effect_backoff(9) is None


def test_executor_registry_rejects_duplicate_registration() -> None:
    """Verify register_executor, duplicate rejection, and clear_executors."""
    clear_executors()
    try:

        async def _dummy(ctx: ExecutionContext) -> EffectCompleted:
            return EffectCompleted(result={"work_id": ctx.work.id})

        register_executor("git.prepare", _dummy)
        assert get_executor("git.prepare") is _dummy
        assert "git.prepare" in registered_executor_kinds()

        with pytest.raises(ValueError, match="already registered"):
            register_executor("git.prepare", _dummy)

        with pytest.raises(ValueError, match="non-empty"):
            register_executor("", _dummy)
    finally:
        clear_executors()


def test_unregister_executor_removes_only_the_function_it_names() -> None:
    clear_executors()
    try:

        async def _first(ctx: ExecutionContext) -> EffectCompleted:
            return EffectCompleted()

        async def _replacement(ctx: ExecutionContext) -> EffectCompleted:
            return EffectCompleted()

        register_executor("workspace.commit", _first)
        register_executor("workspace.commit", _replacement, replace=True)

        # A stale owner cannot remove the executor that replaced its own.
        assert unregister_executor("workspace.commit", _first) is False
        assert get_executor("workspace.commit") is _replacement

        assert unregister_executor("workspace.commit", _replacement) is True
        assert get_executor("workspace.commit") is None
        assert "workspace.commit" not in registered_executor_kinds()
        # Repeat-safe: a second exit finds nothing to remove.
        assert unregister_executor("workspace.commit", _replacement) is False
    finally:
        clear_executors()


async def test_run_executor_conformance_passes_for_compliant_executors() -> None:
    """Verify run_executor_conformance validates idempotent and lease-fenced executors."""

    async def _compliant_success(ctx: ExecutionContext) -> EffectCompleted:
        await ctx.ensure_lease()
        return EffectCompleted(result={"run_id": ctx.run_id, "ok": True})

    async def _compliant_failure(ctx: ExecutionContext) -> EffectFailed:
        await ctx.ensure_lease()
        return EffectFailed(error_code="perm.invalid_repo", message="bad repo", retryable=False)

    await run_executor_conformance(_compliant_success, effect_type="test.success")
    await run_executor_conformance(_compliant_failure, effect_type="test.failure")
    assert StartupLeaseLost is not None
