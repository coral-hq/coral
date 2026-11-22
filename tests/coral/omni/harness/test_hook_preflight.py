"""Tests for native fail-closed launch preflight."""

from __future__ import annotations

import pytest

from coral.omni.harness.hook_preflight import check_fail_closed_launch


def test_ask_mode_always_ok() -> None:
    result = check_fail_closed_launch(
        harness_key="claude-native",
        policy_failure_mode="ask",
        ap_server_url=None,
    )
    assert result.ok


def test_fail_closed_requires_server_url() -> None:
    result = check_fail_closed_launch(
        harness_key="claude-native",
        policy_failure_mode="fail_closed",
        ap_server_url=None,
    )
    assert not result.ok
    assert result.reason is not None
    assert "ap_server_url" in result.reason


def test_fail_closed_with_server_url_checks_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "coral.omni.harness.hook_preflight.harness_cli_version",
        lambda _key: ("2.1.300", "2.1.295"),
    )
    result = check_fail_closed_launch(
        harness_key="claude-native",
        policy_failure_mode="fail_closed",
        ap_server_url="http://127.0.0.1:8787",
    )
    assert result.ok


def test_fail_closed_below_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "coral.omni.harness.hook_preflight.harness_cli_version",
        lambda _key: ("2.0.0", "2.1.295"),
    )
    result = check_fail_closed_launch(
        harness_key="claude-native",
        policy_failure_mode="fail_closed",
        ap_server_url="http://127.0.0.1:8787",
    )
    assert not result.ok
    assert result.reason is not None
    assert "floor" in result.reason
