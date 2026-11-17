"""Fixtures for every Coral Tier A test."""

from __future__ import annotations

import pytest

# coral.omni.policies.cost_backstop.SESSION_CAP_ENV, named here so collection imports no Coral.
SESSION_CAP_ENV = "CORAL_SESSION_COST_CAP_USD"


@pytest.fixture(autouse=True)
def _no_session_cap_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cost cap the developer exported must not decide or break a test's Coral lifespan."""
    monkeypatch.delenv(SESSION_CAP_ENV, raising=False)
