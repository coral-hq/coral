"""Omnigent ambient scope adapter for Coral background workers and reconciliation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from coral.omni.protocols import RunScopeRunner
from omnigent.db.account_authority import account_authority_scope
from omnigent.db.db_models import workspace_scope
from omnigent.server.host_registry import host_owner_scope


class OmnigentRunScopeRunner(RunScopeRunner):
    """Enters workspace_scope, account_authority_scope, and host_owner_scope for a run."""

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
        del run_id, host_id, owner_key
        with (
            workspace_scope(workspace_id),
            account_authority_scope(user_id, account_generation),
            host_owner_scope(user_id, account_generation),
        ):
            yield


__all__ = ["OmnigentRunScopeRunner"]
