"""K17 process capability token map for Coral host and runner processes."""

from __future__ import annotations

import os
from collections.abc import Mapping

CORAL_RUNNER_TOKEN = "coral_runner:1"
DISABLE_HOST_ENTRY_POINTS_ENV = "CORAL_DISABLE_HOST_ENTRY_POINTS"


def host_entry_points_disabled(env: Mapping[str, str] | None = None) -> bool:
    """Return True when Coral host/runner entry points are explicitly suppressed."""
    source = os.environ if env is None else env
    raw = source.get(DISABLE_HOST_ENTRY_POINTS_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
