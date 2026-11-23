"""Tier B: real Coral harness processes against ``mock_llm_server`` only."""

from __future__ import annotations

from pathlib import Path

import pytest

# First runner version line that includes Coral.
CORAL_MIN_RUNNER_VERSION = "0.22.0"
CORAL_TIER_B_HARNESS = "claude-sdk"

_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # A conftest hook receives every collected item in the session, not only this directory's.
    for item in items:
        if _HERE in item.path.resolve().parents:
            item.add_marker(pytest.mark.min_runner_version(CORAL_MIN_RUNNER_VERSION))


@pytest.fixture(autouse=True)
def _tier_b_runs_the_real_claude_cli(real_claude_cli: None) -> None:
    """Tier B drives the real ``claude`` CLI on purpose, so opt out of the spawn guard.

    :param real_claude_cli: The root conftest's opt-in fixture.
    :returns: None.
    """
