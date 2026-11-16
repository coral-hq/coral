"""Failure classes. Text and code are matched before status."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from coral.engine.facts import TurnSnapshot

_SPEND_PHRASES = ("spend limit", "credit balance is too low", "has reached its limit")
_RUNNER_CODES = frozenset(
    {
        "runner_offline_sweep",
        "runner_disconnected_mid_turn",
        "runner_disconnected",
        "runner_interrupted",
        "runner_process_crash",
    }
)
_LIMIT_CODES = frozenset({"rate_limit_exceeded", "usage_limited"})
_TRANSIENT_CODES = frozenset({"overloaded", "transient_upstream_error"})
_TRANSIENT_ORIGINS = frozenset(
    {
        "host_launch_failed",
        "native_terminal_boot_failed",
        "runner_failed_to_start",
    }
)


class Class(BaseModel):
    """A failure class. ``cause`` is the matched text or code, or the class name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    cause: str


def classify_failure(snapshot: TurnSnapshot) -> Class:
    """Classify one failure. Spend-cap text wins over HTTP 429 and over 403."""
    spend = _spend_cause(snapshot.error_text, snapshot.error_code)
    if spend is not None:
        return Class(name="plan.spend_cap", cause=spend)
    runner = _named(snapshot.failure_origin, snapshot.error_code, _RUNNER_CODES)
    if runner is not None:
        return Class(name="infra.runner_lost", cause=runner)
    if snapshot.error_code == "authentication_failed":
        return Class(name="auth", cause=snapshot.error_code)
    if snapshot.status_code in {401, 403}:
        return Class(name="auth", cause=str(snapshot.status_code))
    limited = _named(snapshot.error_code, None, _LIMIT_CODES)
    if limited is not None:
        return Class(name="plan.usage_limit", cause=limited)
    if snapshot.status_code == 429:
        return Class(name="plan.usage_limit", cause="429")
    transient_code = _named(snapshot.error_code, None, _TRANSIENT_CODES)
    if transient_code is not None:
        return Class(name="infra.transient", cause=transient_code)
    transient_origin = _named(snapshot.failure_origin, snapshot.origin, _TRANSIENT_ORIGINS)
    if transient_origin is not None:
        return Class(name="infra.transient", cause=transient_origin)
    if _server_error(snapshot.status_code):
        return Class(name="infra.transient", cause=str(snapshot.status_code))
    return Class(name="agent.failed", cause="agent.failed")


def _spend_cause(text: str | None, code: str | None) -> str | None:
    """The full text or code that matched, with text winning when both match."""
    for value in (text, code):
        if value is None:
            continue
        if value == "budget_exhausted" or any(phrase in value for phrase in _SPEND_PHRASES):
            return value
    return None


def _named(first: str | None, second: str | None, names: frozenset[str]) -> str | None:
    if first in names:
        return first
    if second in names:
        return second
    return None


def _server_error(status: int | None) -> bool:
    return status is not None and (status == 529 or 500 <= status <= 599)
