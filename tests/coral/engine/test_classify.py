"""Failure classes. Spend-cap text wins over 429 and over 403. Causes are fixed tokens."""

from __future__ import annotations

import pytest

from coral.engine.classify import Class, classify_failure
from coral.engine.facts import TurnSnapshot

_RUNNER_CODES = (
    "runner_offline_sweep",
    "runner_disconnected_mid_turn",
    "runner_disconnected",
    "runner_interrupted",
    "runner_process_crash",
)


@pytest.mark.parametrize(
    ("fields", "cause"),
    [
        ({"error_code": "budget_exhausted", "status_code": 429}, "budget_exhausted"),
        ({"error_text": "budget_exhausted", "status_code": 403}, "budget_exhausted"),
        ({"error_text": "spend limit hit", "error_code": "budget_exhausted"}, "spend_phrase"),
        ({"error_text": "spend limit", "status_code": 429}, "spend_phrase"),
        ({"error_text": "credit balance is too low", "status_code": 403}, "spend_phrase"),
        ({"error_text": "team has reached its limit", "status_code": 429}, "spend_phrase"),
        ({"error_code": "has reached its limit", "status_code": 403}, "spend_phrase"),
        ({"error_text": "API Error: 429 credit balance is too low"}, "spend_phrase"),
    ],
)
def test_spend_cap_wins_over_429_and_403(fields: dict[str, object], cause: str) -> None:
    assert classify_failure(TurnSnapshot.model_validate(fields)) == Class(
        name="plan.spend_cap", cause=cause
    )


@pytest.mark.parametrize("code", _RUNNER_CODES)
def test_runner_codes_are_runner_lost(code: str) -> None:
    by_origin = classify_failure(TurnSnapshot(failure_origin=code, status_code=500))
    by_code = classify_failure(TurnSnapshot(error_code=code))
    assert by_origin == Class(name="infra.runner_lost", cause=code)
    assert by_code == Class(name="infra.runner_lost", cause=code)


def test_auth_status_and_code() -> None:
    assert classify_failure(TurnSnapshot(status_code=401)) == Class(name="auth", cause="401")
    assert classify_failure(TurnSnapshot(status_code=403)) == Class(name="auth", cause="403")
    assert classify_failure(
        TurnSnapshot(status_code=401, error_code="authentication_failed")
    ) == Class(name="auth", cause="authentication_failed")


def test_usage_limit_status_and_codes() -> None:
    assert classify_failure(TurnSnapshot(status_code=429)) == Class(
        name="plan.usage_limit", cause="429"
    )
    assert classify_failure(TurnSnapshot(error_code="usage_limited", status_code=429)) == Class(
        name="plan.usage_limit", cause="usage_limited"
    )
    assert classify_failure(TurnSnapshot(error_code="rate_limit_exceeded")) == Class(
        name="plan.usage_limit", cause="rate_limit_exceeded"
    )


@pytest.mark.parametrize(
    ("fields", "cause"),
    [
        ({"status_code": 529}, "529"),
        ({"status_code": 500}, "500"),
        ({"status_code": 502}, "502"),
        ({"error_code": "overloaded", "status_code": 500}, "overloaded"),
        ({"error_code": "transient_upstream_error"}, "transient_upstream_error"),
        ({"failure_origin": "host_launch_failed"}, "host_launch_failed"),
        ({"failure_origin": "native_terminal_boot_failed"}, "native_terminal_boot_failed"),
        ({"origin": "runner_failed_to_start"}, "runner_failed_to_start"),
    ],
)
def test_transient_status_code_and_origin(fields: dict[str, object], cause: str) -> None:
    assert classify_failure(TurnSnapshot.model_validate(fields)) == Class(
        name="infra.transient", cause=cause
    )


@pytest.mark.parametrize(
    "fields",
    [{}, {"error_text": "boom"}, {"status_code": 400}, {"error_code": "something_else"}],
)
def test_anything_else_is_agent_failed(fields: dict[str, object]) -> None:
    assert classify_failure(TurnSnapshot.model_validate(fields)) == Class(
        name="agent.failed", cause="agent.failed"
    )


# Synthetic claude-sdk texts: the shapes are traced in code, not yet captured from the real CLI.
_SDK_TEXT = "inner executor error: "


@pytest.mark.parametrize(
    ("fields", "name", "cause"),
    [
        (
            {
                "error_code": "RuntimeError",
                "error_text": _SDK_TEXT
                + 'API Error: 529 {"type":"error","error":{"type":"overloaded_error"}}',
            },
            "infra.transient",
            "overloaded_error",
        ),
        (
            {"error_code": "RuntimeError", "error_text": _SDK_TEXT + "API Error: 529 busy"},
            "infra.transient",
            "529",
        ),
        ({"error_text": "Error code: 529 - overloaded"}, "infra.transient", "529"),
        ({"error_text": "upstream failed: status_code=503"}, "infra.transient", "503"),
        ({"error_text": "upstream failed: status code 502"}, "infra.transient", "502"),
        (
            {"error_text": 'body {"type":"overloaded_error"}'},
            "infra.transient",
            "overloaded_error",
        ),
        ({"error_code": "overloaded_error"}, "infra.transient", "overloaded_error"),
        ({"error_code": "edge_lost"}, "infra.transient", "edge_lost"),
        (
            {"error_code": "RuntimeError", "error_text": _SDK_TEXT + "API Error: 429 slow down"},
            "plan.usage_limit",
            "429",
        ),
        (
            {"error_text": 'body {"type":"rate_limit_error"}'},
            "plan.usage_limit",
            "rate_limit_error",
        ),
        (
            {"error_text": "Claude AI usage limit reached|1760000000"},
            "plan.usage_limit",
            "usage_limit_phrase",
        ),
        ({"error_text": _SDK_TEXT + "API Error: 401 invalid x-api-key"}, "auth", "401"),
        ({"error_code": "claude_sdk_auth_failed"}, "auth", "claude_sdk_auth_failed"),
        (
            {"error_code": "coral_subscription_auth_refused"},
            "auth",
            "coral_subscription_auth_refused",
        ),
    ],
)
def test_claude_sdk_shapes_map_to_their_class(
    fields: dict[str, object], name: str, cause: str
) -> None:
    assert classify_failure(TurnSnapshot.model_validate(fields)) == Class(name=name, cause=cause)


@pytest.mark.parametrize(
    "text",
    [
        "the call took 529 ms",
        "line 401 of the patch",
        "api error: 529",
        "Error code:529",
        "status: 503",
        "API Error: 5290",
    ],
)
def test_a_status_is_read_only_from_the_anchored_shapes(text: str) -> None:
    assert classify_failure(TurnSnapshot(error_text=text)) == Class(
        name="agent.failed", cause="agent.failed"
    )


@pytest.mark.parametrize(
    ("fields", "name", "cause"),
    [
        ({"status_code": 529, "error_text": "API Error: 401"}, "infra.transient", "529"),
        (
            {"status_code": 503, "error_text": "Claude AI usage limit reached"},
            "infra.transient",
            "503",
        ),
        (
            {"status_code": 400, "error_text": "API Error: 529 overloaded_error"},
            "agent.failed",
            "agent.failed",
        ),
        (
            {"error_code": "overloaded", "error_text": "Claude AI usage limit reached"},
            "infra.transient",
            "overloaded",
        ),
        (
            {"error_code": "usage_limited", "error_text": "API Error: 529 overloaded_error"},
            "plan.usage_limit",
            "usage_limited",
        ),
        (
            {"error_code": "claude_sdk_auth_failed", "error_text": "API Error: 529"},
            "auth",
            "claude_sdk_auth_failed",
        ),
        (
            {"failure_origin": "host_launch_failed", "error_text": "API Error: 401"},
            "infra.transient",
            "host_launch_failed",
        ),
    ],
)
def test_an_explicit_status_or_code_wins_over_the_text(
    fields: dict[str, object], name: str, cause: str
) -> None:
    assert classify_failure(TurnSnapshot.model_validate(fields)) == Class(name=name, cause=cause)


@pytest.mark.parametrize(
    "text",
    [
        _SDK_TEXT + "LLM response denied by policy: matched 'Error code: 403'",
        "LLM call denied by policy: credit balance is too low",
        "LLM call denied by policy: API Error: 529 overloaded_error",
        "memory usage limit exceeded",
    ],
)
def test_policy_denials_and_unrelated_limit_text_are_agent_failed(text: str) -> None:
    assert classify_failure(TurnSnapshot(error_text=text)) == Class(
        name="agent.failed", cause="agent.failed"
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"error_text": "spend limit"},
        {"error_text": "API Error: 529"},
        {"error_text": "Claude AI usage limit reached"},
        {"error_text": "rate_limit_error"},
        {"error_text": "overloaded_error"},
        {"error_code": "claude_sdk_auth_failed"},
        {"error_code": "runner_disconnected"},
        {"failure_origin": "host_launch_failed"},
        {"status_code": 503},
        {},
    ],
)
def test_the_cause_is_a_fixed_token_never_the_error_text(fields: dict[str, object]) -> None:
    noisy = dict(fields)
    noisy["error_text"] = f"{fields.get('error_text', '')} {'secret-' * 700}"
    cause = classify_failure(TurnSnapshot.model_validate(noisy)).cause
    assert len(cause) <= 64
    assert "secret" not in cause
    assert " " not in cause
