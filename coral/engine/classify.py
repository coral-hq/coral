"""Failure classes. Explicit codes, statuses and origins are matched before error text.

Spend-cap text is the one exception: it wins over a 429 or 403. ``cause`` is always a
fixed token of at most 64 characters, never error text.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from coral.engine.facts import TurnSnapshot

_SPEND_PHRASES = ("spend limit", "credit balance is too low", "has reached its limit")
_SPEND_CODE = "budget_exhausted"
_SPEND_PHRASE = "spend_phrase"
_RUNNER_CODES = frozenset(
    {
        "runner_offline_sweep",
        "runner_disconnected_mid_turn",
        "runner_disconnected",
        "runner_interrupted",
        "runner_process_crash",
    }
)
_AUTH_CODES = frozenset(
    {"authentication_failed", "claude_sdk_auth_failed", "coral_subscription_auth_refused"}
)
_LIMIT_CODES = frozenset({"rate_limit_exceeded", "usage_limited", "rate_limit_error"})
# ``edge_lost``: a failed turn whose status edge was lost, rebuilt from the transcript.
_TRANSIENT_CODES = frozenset(
    {"overloaded", "transient_upstream_error", "overloaded_error", "edge_lost"}
)
_TRANSIENT_ORIGINS = frozenset(
    {
        "host_launch_failed",
        "native_terminal_boot_failed",
        "runner_failed_to_start",
    }
)
# claude-sdk keeps the HTTP status only in its error text. Shapes traced in code, not yet
# captured from the real CLI: each marker maps to the fixed token stored as ``cause``.
_STATUS_IN_TEXT = re.compile(r"\b(?:API Error: |Error code: |status[_ ]code[=: ])(\d{3})\b")
_LIMIT_MARKERS = (
    ("rate_limit_error", "rate_limit_error"),
    ("usage limit reached", "usage_limit_phrase"),
)
_TRANSIENT_MARKERS = (("overloaded_error", "overloaded_error"),)
# A policy hook's denial quotes its own reason, which must not pick a failure class.
_POLICY_DENIALS = ("LLM call denied by policy:", "LLM response denied by policy:")


class Class(BaseModel):
    """A failure class. ``cause`` is a known code, a status, or a fixed phrase token."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    cause: str


def classify_failure(snapshot: TurnSnapshot) -> Class:
    """Classify one failure. Spend-cap text wins over HTTP 429 and over 403.

    Error text is read for a status or a marker only when no explicit code, status or
    origin decided the class and ``status_code`` is unset. A status is read only from
    the anchored shapes ``API Error: NNN``, ``Error code: NNN`` and
    ``status[_ ]code[=: ]NNN``. A policy denial's text is never read.
    """
    text = snapshot.error_text
    if text is not None and any(denial in text for denial in _POLICY_DENIALS):
        text = None
    spend = _spend_cause(text, snapshot.error_code)
    if spend is not None:
        return Class(name="plan.spend_cap", cause=spend)
    runner = _named(snapshot.failure_origin, snapshot.error_code, _RUNNER_CODES)
    if runner is not None:
        return Class(name="infra.runner_lost", cause=runner)
    auth = _named(snapshot.error_code, None, _AUTH_CODES)
    if auth is not None:
        return Class(name="auth", cause=auth)
    status = snapshot.status_code
    if status in {401, 403}:
        return Class(name="auth", cause=str(status))
    limited = _named(snapshot.error_code, None, _LIMIT_CODES)
    if limited is not None:
        return Class(name="plan.usage_limit", cause=limited)
    if status == 429:
        return Class(name="plan.usage_limit", cause="429")
    transient = _named(snapshot.error_code, None, _TRANSIENT_CODES)
    if transient is not None:
        return Class(name="infra.transient", cause=transient)
    transient_origin = _named(snapshot.failure_origin, snapshot.origin, _TRANSIENT_ORIGINS)
    if transient_origin is not None:
        return Class(name="infra.transient", cause=transient_origin)
    if _server_error(status):
        return Class(name="infra.transient", cause=str(status))
    if status is None:
        from_text = _classify_text(text)
        if from_text is not None:
            return from_text
    return Class(name="agent.failed", cause="agent.failed")


def _classify_text(text: str | None) -> Class | None:
    """The class the error text names, read only when no explicit field decided it."""
    if text is None:
        return None
    status = _status_in(text)
    if status in {401, 403}:
        return Class(name="auth", cause=str(status))
    limited = _marker(text, _LIMIT_MARKERS)
    if limited is not None:
        return Class(name="plan.usage_limit", cause=limited)
    if status == 429:
        return Class(name="plan.usage_limit", cause="429")
    transient = _marker(text, _TRANSIENT_MARKERS)
    if transient is not None:
        return Class(name="infra.transient", cause=transient)
    if _server_error(status):
        return Class(name="infra.transient", cause=str(status))
    return None


def _spend_cause(text: str | None, code: str | None) -> str | None:
    """``budget_exhausted`` or ``spend_phrase``, checking the text before the code."""
    for value in (text, code):
        if value is None:
            continue
        if value == _SPEND_CODE:
            return _SPEND_CODE
        if any(phrase in value for phrase in _SPEND_PHRASES):
            return _SPEND_PHRASE
    return None


def _status_in(text: str) -> int | None:
    found = _STATUS_IN_TEXT.search(text)
    return int(found.group(1)) if found is not None else None


def _marker(text: str | None, markers: tuple[tuple[str, str], ...]) -> str | None:
    """The token of the first marker found in ``text``, ignoring case."""
    if text is None:
        return None
    folded = text.casefold()
    for marker, token in markers:
        if marker in folded:
            return token
    return None


def _named(first: str | None, second: str | None, names: frozenset[str]) -> str | None:
    if first in names:
        return first
    if second in names:
        return second
    return None


def _server_error(status: int | None) -> bool:
    return status is not None and (status == 529 or 500 <= status <= 599)
