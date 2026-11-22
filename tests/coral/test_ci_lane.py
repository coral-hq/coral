"""The ``coral-e2e`` CI lane runs the walking-skeleton E2E with the pinned claude CLI."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import yaml

from tests.e2e.coral._skeleton import REQUIRE_CLI_ENV

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / ".github" / "scripts" / "ci" / "python-matrix.json"
CI = ROOT / ".github" / "workflows" / "ci.yml"
LANE = "coral-e2e"
# The server-SIGKILL proofs run in the lane; the live variant skips there without its opt-in.
SIGKILL_PROOFS = {
    "test_the_review_loop_survives_server_sigkills_mid_step_and_at_the_gate",
    "test_a_runner_reconnecting_after_a_default_lease_restart_is_not_relaunched",
}
# The live proxy's unit test needs no key, so the lane guards the proxy's refusals.
PROXY_UNIT_TEST = "tests/e2e/coral/test_live_proxy.py"
RUNNER_LOSS = "tests/e2e/coral/test_runner_loss.py"
# A killed step runner, an offline host's hold and return, and a retried step.
RUNNER_LOSS_PROOFS = {
    "test_a_killed_step_runner_is_relaunched_in_the_same_session",
    "test_an_offline_host_holds_the_step_and_its_return_relaunches_it",
    "test_retrying_a_blocked_step_fences_salvages_resets_and_briefs_a_new_session",
}


def _groups() -> dict[str, dict[str, str]]:
    return {row["group"]: row for row in json.loads(MATRIX.read_text())}


def _pytest_steps() -> list[dict[str, Any]]:
    return yaml.safe_load(CI.read_text())["jobs"]["pytest"]["steps"]


def test_the_lane_runs_the_coral_e2e_files_on_two_workers() -> None:
    lane = _groups()[LANE]

    # The proxy's quick tests first, so --dist=load spreads the stack tests over both
    # workers; this order is meant to keep the two longest, the default-lease proof and
    # the host outage, off the same worker.
    assert lane["paths"].split() == [
        PROXY_UNIT_TEST,
        "tests/e2e/coral/test_skeleton.py",
        RUNNER_LOSS,
    ]
    assert (lane["workers"], lane["dist"]) == ("2", "load")
    # misc never collects tests/e2e, so the lane is the only CI run of these files.
    assert "--ignore=tests/e2e" in _groups()["misc"]["paths"].split()


def test_the_lane_runs_the_sigkill_and_runner_loss_proofs_and_the_proxy_unit_test() -> None:
    paths = _groups()[LANE]["paths"].split()
    collected = {
        node.name
        for path in paths
        for node in ast.parse((ROOT / path).read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }

    assert collected >= SIGKILL_PROOFS | RUNNER_LOSS_PROOFS
    assert PROXY_UNIT_TEST in paths
    assert "test_a_failing_live_run_shows_its_key_nowhere_in_the_report" in collected


def test_the_lane_installs_the_pinned_claude_cli_from_the_in_repo_action() -> None:
    steps = _pytest_steps()
    [claude] = [step for step in steps if step.get("id") == "claude_cli"]
    [node] = [step for step in steps if str(step.get("uses", "")).startswith("actions/setup-node")]
    [summary] = [step for step in steps if "steps.claude_cli.outputs.version" in str(step)]

    assert claude["uses"] == "./.github/actions/setup-harness-cli"
    assert claude["with"] == {"harness": "claude"}
    assert claude["if"] == f"matrix.group == '{LANE}'"
    assert f"matrix.group == '{LANE}'" in node["if"]
    assert summary["if"] == f"matrix.group == '{LANE}'"
    assert "GITHUB_STEP_SUMMARY" in summary["run"]
    # The E2E then fails, rather than skips, on a CLI that installed but does not run.
    assert f"{REQUIRE_CLI_ENV}=1" in summary["run"] and "GITHUB_ENV" in summary["run"]
    # Both run before the tests.
    run_pytest = next(index for index, step in enumerate(steps) if step["name"] == "Run pytest")
    assert steps.index(node) < steps.index(claude) < steps.index(summary) < run_pytest
