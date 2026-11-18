"""Failure classes. Explicit codes, statuses and origins are matched before error text.

Spend-cap text is the one exception: it wins over a 429 or 403. Other error text is
read only at its start, after the runtime's wrapper, in the shapes claude-sdk reports.
``cause`` is always a fixed token of at most 64 characters, never error text.
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
# ``edge_lost``: a failed turn whose status edge was lost, rebuilt from the transcript;
# ``turn_unreadable``: a turn that is over but too long for its transcript walk.
_TRANSIENT_CODES = frozenset(
    {"overloaded", "transient_upstream_error", "overloaded_error", "edge_lost", "turn_unreadable"}
)
_TRANSIENT_ORIGINS = frozenset(
    {
        "host_launch_failed",
        "native_terminal_boot_failed",
        "runner_failed_to_start",
    }
)
# claude-sdk keeps the HTTP status only in its error text, which the runtime wraps once.
# Shapes traced in code, not yet captured from the real CLI; each is read only at the
# start of the text, so a tool's output quoted later in it picks no class.
_WRAPPER = re.compile(r"\s*(?:inner executor error:\s*)?")
_STATUS_AT_START = re.compile(r"(?:API Error: |Error code: |status[_ ]code[=: ])(\d{3})\b")
# Omnigent's runner names an HTTP status in its own failures: a harness that refused the
# turn, a runner request the server relays, and an agent spec it could not load.
_RUNNER_STATUS_AT_START = re.compile(
    r"(?:turn failed \(status |runner returned status "
    r"|Could not load the agent spec \([^()]{0,200}\bHTTP )(\d{3})\b"
)
# The API's error body, e.g. ``{"type":"error","error":{"type":"overloaded_error",...}}``.
_ERROR_BODY_AT_START = re.compile(
    r'\{\s*"type"\s*:\s*"error"\s*,\s*"error"\s*:\s*\{\s*"type"\s*:\s*"([a-z_]{1,64})"'
)
_LIMIT_BODY_TYPES = frozenset({"rate_limit_error"})
_TRANSIENT_BODY_TYPES = frozenset({"overloaded_error"})
# The subscription CLI's limit notice, e.g. ``Claude AI usage limit reached|1760000000``.
_USAGE_LIMIT_AT_START = re.compile(r"Claude AI usage limit reached\b")
# A policy hook's denial quotes its own reason, which must not pick a failure class.
_POLICY_DENIALS = ("LLM call denied by policy:", "LLM response denied by policy:")


class Class(BaseModel):
    """A failure class. ``cause`` is a known code, a status, or a fixed phrase token."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    cause: str


def classify_failure(snapshot: TurnSnapshot) -> Class:
    """Classify one failure. Spend-cap text wins over HTTP 429 and over 403.

    Error text is read only when no explicit code, status or origin decided the class
    and ``status_code`` is unset, and only at its start (after the runtime's
    ``inner executor error:`` wrapper): a status in the shapes ``API Error: NNN``,
    ``Error code: NNN`` and ``status[_ ]code[=: ]NNN``, or in the runner's own
    ``turn failed (status NNN)``, ``runner returned status NNN`` and
    ``Could not load the agent spec (... HTTP NNN)``; without one, the API's error
    body type or the usage-limit notice. A policy denial's text is never read.
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
    """The class the start of the error text names, read only when no explicit field decided it."""
    if text is None:
        return None
    wrapped = _WRAPPER.match(text)
    start = text[wrapped.end() :] if wrapped is not None else text
    found = _STATUS_AT_START.match(start) or _RUNNER_STATUS_AT_START.match(start)
    if found is not None:
        return _status_class(int(found.group(1)))
    body = _ERROR_BODY_AT_START.match(start)
    if body is not None and body.group(1) in _LIMIT_BODY_TYPES:
        return Class(name="plan.usage_limit", cause=body.group(1))
    if body is not None and body.group(1) in _TRANSIENT_BODY_TYPES:
        return Class(name="infra.transient", cause=body.group(1))
    if _USAGE_LIMIT_AT_START.match(start) is not None:
        return Class(name="plan.usage_limit", cause="usage_limit_phrase")
    return None


def _status_class(status: int) -> Class | None:
    """The class an HTTP status read from error text names, if any."""
    if status in {401, 403}:
        return Class(name="auth", cause=str(status))
    if status == 429:
        return Class(name="plan.usage_limit", cause="429")
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


def _named(first: str | None, second: str | None, names: frozenset[str]) -> str | None:
    if first in names:
        return first
    if second in names:
        return second
    return None


def _server_error(status: int | None) -> bool:
    return status is not None and (status == 529 or 500 <= status <= 599)
