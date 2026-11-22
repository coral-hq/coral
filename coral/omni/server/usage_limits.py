"""Map harness usage-limit signals into Coral ``UsageLimited`` commands."""

from __future__ import annotations

from coral.engine.types import UsageLimited
from omnigent.inner.executor import ExecutorError


def usage_limited_from_executor_error(
    *,
    slot_id: str,
    fact_key: str,
    error: ExecutorError,
) -> UsageLimited | None:
    """Build a ``UsageLimited`` command when *error* is a plan/usage limit."""
    if error.code != ExecutorError.USAGE_LIMITED_CODE and error.code not in {
        "rate_limit_exceeded",
        "rate_limit_error",
    }:
        return None
    return UsageLimited(
        slot_id=slot_id,
        fact_key=fact_key,
        resets_at=error.resets_at,
    )


__all__ = ["usage_limited_from_executor_error"]
