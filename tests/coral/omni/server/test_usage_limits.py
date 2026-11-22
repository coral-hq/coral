"""Tests for structured usage-limit mapping."""

from __future__ import annotations

from coral.omni.server.usage_limits import usage_limited_from_executor_error
from omnigent.inner.executor import ExecutorError


def test_maps_usage_limited_with_resets_at() -> None:
    error = ExecutorError(
        message="limit",
        code=ExecutorError.USAGE_LIMITED_CODE,
        resets_at=1_700_000_000.0,
    )
    command = usage_limited_from_executor_error(slot_id="slot", fact_key="fact", error=error)
    assert command is not None
    assert command.resets_at == 1_700_000_000.0


def test_ignores_unrelated_errors() -> None:
    error = ExecutorError(message="boom", code="other")
    assert usage_limited_from_executor_error(slot_id="slot", fact_key="fact", error=error) is None
