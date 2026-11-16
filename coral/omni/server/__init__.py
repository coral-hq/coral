"""Coral server adapters backed by Omnigent server primitives.

Public names load on first use so ``coral.omni.server.observers`` can import
without pulling Omnigent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from coral.omni.server.plugin import coral_lifespan as coral_lifespan
    from coral.omni.server.plugin import register as register
    from coral.omni.server.scopes import OmnigentRunScopeRunner as OmnigentRunScopeRunner

__all__ = [
    "OmnigentRunScopeRunner",
    "coral_lifespan",
    "register",
]


def __getattr__(name: str) -> Any:
    if name == "OmnigentRunScopeRunner":
        from coral.omni.server.scopes import OmnigentRunScopeRunner

        value: Any = OmnigentRunScopeRunner
    elif name == "coral_lifespan":
        from coral.omni.server.plugin import coral_lifespan

        value = coral_lifespan
    elif name == "register":
        from coral.omni.server.plugin import register

        value = register
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
