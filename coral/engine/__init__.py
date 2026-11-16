"""Pure workflow reducer. Must not import ``omnigent``.

Public names load on first use. Importing an engine submodule must not load the
reducer: the reducer imports ``coral.signals``, and those modules import engine
submodules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from coral.engine.fold import fold as fold
    from coral.engine.reducer import transition as transition
    from coral.engine.types import empty_state as empty_state

__all__ = ["empty_state", "fold", "transition"]


def __getattr__(name: str) -> Any:
    if name == "empty_state":
        from coral.engine.types import empty_state

        value = empty_state
    elif name == "fold":
        from coral.engine.fold import fold

        value = fold
    elif name == "transition":
        from coral.engine.reducer import transition

        value = transition
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
