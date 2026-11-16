"""Failure classes. Spend-cap text wins over 429 and over 403."""

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
        (
            {"error_text": "spend limit hit", "error_code": "budget_exhausted"},
            "spend limit hit",
        ),
        ({"error_text": "spend limit", "status_code": 429}, "spend limit"),
        (
            {"error_text": "credit balance is too low", "status_code": 403},
            "credit balance is too low",
        ),
        (
            {"error_text": "team has reached its limit", "status_code": 429},
            "team has reached its limit",
        ),
        ({"error_code": "has reached its limit", "status_code": 403}, "has reached its limit"),
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
