"""Preflight engine: each failing fact names one fix, in a fixed check order."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from coral.validate.preflight import (
    API_KEY_REQUIRED_MESSAGE,
    SANDBOX_UNREPORTED_MESSAGE,
    SYSTEM_CLAUDE_MISSING_MESSAGE,
    PreflightFacts,
    PreflightItem,
    PreflightReport,
    StepNeeds,
    run_preflight,
    sandbox_from_capabilities,
)

SDK_SANDBOXED = StepNeeds(step_ref="review", harness="claude-sdk", needs_fs_sandbox=True)
SDK_PLAIN = StepNeeds(step_ref="plan", harness="claude-sdk", needs_fs_sandbox=False)
OTHER_PLAIN = StepNeeds(step_ref="note", harness="codex", needs_fs_sandbox=False)


def _facts(**overrides: object) -> PreflightFacts:
    values: dict[str, object] = {
        "credential": "api_key",
        "host_online": True,
        "sandbox": "seatbelt",
        "system_claude": True,
        "steps": (SDK_SANDBOXED,),
    }
    values.update(overrides)
    return PreflightFacts.model_validate(values)


def _item(report: PreflightReport, check: str) -> PreflightItem:
    matches = [item for item in report.items if item.check == check]
    assert len(matches) == 1
    return matches[0]


def test_subscription_only_fails_auth_with_add_api_key() -> None:
    report = run_preflight(_facts(credential="none"))

    auth = _item(report, "auth")
    assert auth.status == "fail"
    assert auth.fix is not None and auth.fix.target == "add_api_key"
    assert auth.message == API_KEY_REQUIRED_MESSAGE
    assert "Claude Code" not in auth.message
    assert report.ok is False


def test_failing_credential_names_its_step() -> None:
    report = run_preflight(_facts(credential="none", credential_step_ref="implement"))

    auth = _item(report, "auth")
    assert auth.status == "fail"
    assert auth.message == f"{API_KEY_REQUIRED_MESSAGE} (step implement)"


def test_invalid_credential_carries_the_detail() -> None:
    report = run_preflight(
        _facts(credential="invalid", credential_detail="provider 'team' is not declared")
    )

    auth = _item(report, "auth")
    assert auth.status == "fail"
    assert auth.fix is not None and auth.fix.target == "add_api_key"
    assert "provider 'team' is not declared" in auth.message


def test_offline_host_fails_host_sandbox_and_system_claude_with_connect_host() -> None:
    report = run_preflight(_facts(host_online=False, sandbox=None, system_claude=None))

    for check in ("host_online", "sandbox", "system_claude"):
        item = _item(report, check)
        assert item.status == "fail"
        assert item.fix is not None and item.fix.target == "connect_host"
    assert report.ok is False


def test_sandboxed_step_on_a_host_without_a_backend_needs_bwrap() -> None:
    report = run_preflight(_facts(sandbox="none"))

    sandbox = _item(report, "sandbox")
    assert sandbox.status == "fail"
    assert sandbox.fix is not None and sandbox.fix.target == "install_bwrap"


def test_sandboxed_step_on_a_host_that_reports_no_sandbox_needs_a_host_update() -> None:
    report = run_preflight(_facts(sandbox=None))

    sandbox = _item(report, "sandbox")
    assert sandbox.status == "fail"
    assert sandbox.message == SANDBOX_UNREPORTED_MESSAGE
    assert sandbox.fix is not None and sandbox.fix.target == "update_host"


def test_no_sandboxed_step_skips_the_sandbox_check() -> None:
    report = run_preflight(_facts(sandbox=None, steps=(SDK_PLAIN,)))

    assert [item.check for item in report.items] == ["auth", "host_online"]
    assert report.ok is True


def test_no_claude_sdk_step_skips_the_auth_check() -> None:
    report = run_preflight(_facts(credential="none", steps=(OTHER_PLAIN,)))

    assert [item.check for item in report.items] == ["host_online"]
    assert report.ok is True


def test_all_good_reports_every_check_ok_in_order() -> None:
    report = run_preflight(_facts(steps=(SDK_PLAIN, SDK_SANDBOXED)))

    assert [item.check for item in report.items] == [
        "auth",
        "host_online",
        "sandbox",
        "system_claude",
    ]
    assert all(item.status == "ok" and item.fix is None for item in report.items)
    assert report.ok is True


def test_missing_system_claude_fails_sandboxed_claude_steps() -> None:
    report = run_preflight(_facts(system_claude=False))

    item = _item(report, "system_claude")
    assert item.status == "fail"
    assert item.message == SYSTEM_CLAUDE_MISSING_MESSAGE
    assert item.fix is not None and item.fix.target == "install_harness"
    assert "Claude Code" not in item.message


def test_plain_claude_steps_skip_system_claude_check() -> None:
    report = run_preflight(_facts(system_claude=False, steps=(SDK_PLAIN,)))

    assert [item.check for item in report.items] == ["auth", "host_online"]
    assert report.ok is True


def test_report_serializes_ok_with_the_items() -> None:
    payload = run_preflight(_facts(credential="none")).model_dump(mode="json")

    assert payload["ok"] is False
    assert payload["items"][0] == {
        "check": "auth",
        "status": "fail",
        "message": API_KEY_REQUIRED_MESSAGE,
        "fix": {"target": "add_api_key", "href": None},
    }


def test_facts_are_frozen_and_reject_unknown_fields() -> None:
    facts = _facts()
    with pytest.raises(ValidationError):
        facts.host_online = False  # type: ignore[misc]
    with pytest.raises(ValidationError):
        _facts(account="me@example.test")


@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [
        (["host_hello_v1", "os_sandbox:linux_bwrap"], "bwrap"),
        (["os_sandbox:darwin_seatbelt"], "seatbelt"),
        (["coral_host_sandbox:1:linux:bwrap:1"], "bwrap"),
        (["coral_host_sandbox:1:darwin:seatbelt:1"], "seatbelt"),
        (["os_sandbox:none"], "none"),
        (["os_sandbox:windows_jobobject"], "none"),
        (["coral_host_sandbox:1:linux:bwrap:0"], "none"),
        (["coral_host_sandbox:2:linux:bwrap:1", "coral_host_sandbox:1:linux:jail:1"], "none"),
        (["coral_host_sandbox:2:linux:bwrap:1"], None),
        (["host_hello_v1"], None),
        ([], None),
    ],
)
def test_sandbox_from_capabilities(capabilities: list[str], expected: str | None) -> None:
    """``None`` means the host sent no sandbox token, so it predates them."""
    assert sandbox_from_capabilities(capabilities) == expected
