"""Fixtures for Coral's omni-tier tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from omnigent.policies.registry import load_registry

CORAL_POLICY_MODULES = ("coral.omni.policies.hygiene", "coral.omni.policies.guards")


@pytest.fixture
def coral_policy_registry() -> Iterator[None]:
    """Load the policy registry as the Coral server plugin does, then restore the built-ins."""
    load_registry(extra_modules=list(CORAL_POLICY_MODULES))
    yield
    load_registry()
