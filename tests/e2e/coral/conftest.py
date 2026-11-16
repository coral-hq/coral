"""Tier B: real Coral harness processes against ``mock_llm_server`` only."""

from __future__ import annotations

from pathlib import Path

import pytest

# The first version line that carries Coral; compat runs pin older runner tags.
CORAL_MIN_RUNNER_VERSION = "0.22.0"
# Spike 4 passed: docs/coral/decisions/probes/SPK-03-claude-sdk.md.
CORAL_TIER_B_HARNESS = "claude-sdk"

_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # A conftest hook receives every collected item in the session, not only this directory's.
    for item in items:
        if _HERE in item.path.resolve().parents:
            item.add_marker(pytest.mark.min_runner_version(CORAL_MIN_RUNNER_VERSION))
