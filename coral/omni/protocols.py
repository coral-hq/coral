"""Protocols bridging Coral runtime components with the Omnigent host server.

App-tier modules reach the server only through these names, so this module
imports nothing but the standard library and pure Coral modules.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Literal, Protocol, runtime_checkable

from coral.workspace.ops import HostChannelBackend

HostAccessCode = Literal["not_permitted", "host_offline"]


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


class CoralSessionError(Exception):
    """
    A Coral session operation failed with a typed code, e.g. ``session.deleted``.

    :param retryable: A later attempt may succeed, e.g. ``session.host_offline``.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


class HostAccessRefused(Exception):
    """
    The run owner may not use the host now.

    :param code: ``not_permitted``: an unknown host, another user's or account
        registration's host, a managed sandbox, or a connection another owner
        holds; retrying cannot help. ``host_offline``: no live connection yet.
    :param message: Names only the caller's own host.
    """

    def __init__(self, code: HostAccessCode, message: str) -> None:
        super().__init__(message)
        self.code: HostAccessCode = code
        self.message = message


@runtime_checkable
class HostWorkspaceChannels(Protocol):
    """Hands out the host workspace-op channel for a run owner's host."""

    async def channel(
        self,
        *,
        workspace_id: int,
        user_id: str | None,
        account_generation: str | None,
        host_id: str,
    ) -> HostChannelBackend:
        """
        Authorize the run owner for ``host_id`` from its stored row, before any frame.

        Callers take every argument from the stored run, never from a payload.

        :param user_id: ``None`` only when auth is off, which skips the owner checks.
        :raises HostAccessRefused: ``not_permitted`` when the owner may not use the host.
        """
        ...


__all__ = [
    "CoralSessionError",
    "HostAccessCode",
    "HostAccessRefused",
    "HostWorkspaceChannels",
    "NoOpScopeRunner",
    "RunScopeRunner",
]
