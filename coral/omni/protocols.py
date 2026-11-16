"""Protocols bridging Coral runtime components with the Omnigent host server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
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


class NoOpScopeRunner:
    """Default no-op RunScopeRunner for standalone tests or environments without host scopes."""

    @asynccontextmanager
    async def run_scope(
        self,
        *,
        workspace_id: int,
        run_id: str | None = None,
        user_id: str | None = None,
        account_generation: str | None = None,
        host_id: str | None = None,
        owner_key: str | None = None,
    ) -> AsyncIterator[None]:
        del workspace_id, run_id, user_id, account_generation, host_id, owner_key
        yield


__all__ = ["NoOpScopeRunner", "RunScopeRunner"]
