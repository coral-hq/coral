"""K17 process capability token map for Coral host and runner processes."""

from __future__ import annotations

import os
from collections.abc import Mapping

# Version 2 hosts offer the engine tools; a host on an older Coral is refused for steps.
CORAL_RUNNER_TOKEN = "coral_runner:2"
DISABLE_HOST_ENTRY_POINTS_ENV = "CORAL_DISABLE_HOST_ENTRY_POINTS"


def host_entry_points_disabled(env: Mapping[str, str] | None = None) -> bool:
    """Return True when Coral host/runner entry points are explicitly suppressed."""
    source = os.environ if env is None else env
    raw = source.get(DISABLE_HOST_ENTRY_POINTS_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def host_tokens(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """The tokens a Coral host adds to its hello; none while Coral's entry points are disabled."""
    if host_entry_points_disabled(env):
        return ()
    return (CORAL_RUNNER_TOKEN,)
