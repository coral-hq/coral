"""Protocols bridging Coral runtime components with the Omnigent host server."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable


@runtime_checkable
class RunScopeRunner(Protocol):
    """Protocol for entering host ambient scopes around background work or reconciliation."""

    def run_scope(
        self,
        *,
        workspace_id: int,
        run_id: str | None = None,
        user_id: str | None = None,
        account_generation: str | None = None,
        host_id: str | None = None,
        owner_key: str | None = None,
    ) -> AbstractAsyncContextManager[None]: ...


__all__ = ["RunScopeRunner"]
