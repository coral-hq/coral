"""The checked-in patch cases are what ``apply_view_patch`` decides, for the web to match."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.coral.api import run_view_contract
from tests.coral.api._stream_client import StreamClient
from tests.coral.runview.view_patch_contract import CONTRACT_PATH, build_contract


@pytest.fixture(scope="module")
def cases() -> list[dict[str, Any]]:
    return run_view_contract.checked_in(CONTRACT_PATH)["cases"]


def test_the_checked_in_cases_equal_what_the_python_applier_decides() -> None:
    # On a mismatch: uv run --no-sync python -m tests.coral.runview.view_patch_contract --write
    live = run_view_contract.checked_in(run_view_contract.CONTRACT_PATH)["live"]
    assert run_view_contract.checked_in(CONTRACT_PATH) == build_contract(live)


def test_each_case_has_one_outcome_and_a_client_error_keeps_pythons_result(
    cases: list[dict[str, Any]],
) -> None:
    # The builder checks each rule case against the verdict declared beside it.
    for case in cases:
        assert set(case) <= {"name", "view", "patch", "result", "error", "client_error"}
        assert ("result" in case) != (case.get("error") is True), case["name"]
        if "client_error" in case:
            assert case["client_error"] is True and "result" in case, case["name"]

    marked = {"client_error" in case or "error" in case for case in cases}
    assert marked == {True, False}
    assert any("client_error" in case for case in cases)


def test_every_patch_of_the_live_tail_is_a_case_on_the_view_it_was_sent_to(
    cases: list[dict[str, Any]],
) -> None:
    live = run_view_contract.checked_in(run_view_contract.CONTRACT_PATH)["live"]
    client = StreamClient()
    expected: list[dict[str, Any]] = []
    for event in live:
        before = client.view
        client.take(run_view_contract.wire_event(event))
        if event["event"] == "entry" and json.loads(event["data"])["patch"]:
            data = json.loads(event["data"])
            name = f"live entry {data['seq']} ({data['kind']})"
            expected.append(
                {"name": name, "view": before, "patch": data["patch"], "result": client.view}
            )

    entries = [case for case in cases if case["name"].startswith("live")]
    assert entries == expected
    assert len(entries) >= 10
