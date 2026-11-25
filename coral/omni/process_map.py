"""K17 process capability token map for Coral host and runner processes."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

# Version 2 hosts offer the engine tools; a host on an older Coral is refused for steps.
CORAL_RUNNER_TOKEN = "coral_runner:2"
# The step sandbox rules this host runs; a host on a revision with no rows reads as unknown. Bump
# it only for a change that alters a gate row: an in-sandbox pin's open or closed state or owner,
# or a probed sandbox rule. Outside change detectors and outside control maps never need a bump.
# From revision 2 a macOS step's profile refuses other programs' Unix-domain sockets. From
# revision 3 it also keeps every dir above a masked entry in place and uncloned.
SANDBOX_POLICY_REVISION = "3"
SANDBOX_POLICY_PREFIX = "coral_sandbox_policy:"
CORAL_SANDBOX_POLICY_TOKEN = f"{SANDBOX_POLICY_PREFIX}{SANDBOX_POLICY_REVISION}"
DISABLE_HOST_ENTRY_POINTS_ENV = "CORAL_DISABLE_HOST_ENTRY_POINTS"
# Any non-empty value leaves a step's CLI unsandboxed, as the claude-sdk executor reads it.
CLAUDE_SDK_NO_SANDBOX_ENV = "OMNIGENT_CLAUDE_SDK_NO_SANDBOX"


def host_entry_points_disabled(env: Mapping[str, str] | None = None) -> bool:
    """Return True when Coral host/runner entry points are explicitly suppressed."""
    source = os.environ if env is None else env
    raw = source.get(DISABLE_HOST_ENTRY_POINTS_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def host_tokens(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """The tokens a Coral host adds to its hello; none while Coral's entry points are disabled."""
    source = os.environ if env is None else env
    if host_entry_points_disabled(source):
        return ()
    # A host whose steps run unsandboxed claims no sandbox policy, so the gate label reads unknown.
    if source.get(CLAUDE_SDK_NO_SANDBOX_ENV):
        return (CORAL_RUNNER_TOKEN,)
    return (CORAL_RUNNER_TOKEN, CORAL_SANDBOX_POLICY_TOKEN)


def sandbox_policy_revision(capabilities: Iterable[str]) -> str | None:
    """The sandbox policy revision a host reported; ``None`` for none, or for two that differ."""
    revisions = {
        token.removeprefix(SANDBOX_POLICY_PREFIX)
        for token in capabilities
        if token.startswith(SANDBOX_POLICY_PREFIX)
    }
    return revisions.pop() if len(revisions) == 1 else None
