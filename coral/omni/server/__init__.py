"""Coral server adapters backed by Omnigent server primitives."""

from __future__ import annotations

from coral.omni.server.plugin import coral_lifespan, register
from coral.omni.server.scopes import OmnigentRunScopeRunner

__all__ = [
    "OmnigentRunScopeRunner",
    "coral_lifespan",
    "register",
]
