"""The host workspace-op channel for engine work, without an HTTP request.

``OmnigentHostWorkspaceChannels.channel`` authorizes the run owner for the host
from its stored row (``host_access``) before any frame is sent, and returns a
``HostChannelBackend`` for ``coral.workspace.host_backend.HostWorkspaceOps``.
Each request looks the live connection up again, refuses one another owner or
registration holds, and sends ``host.workspace_op`` through Omnigent's request
helper inside the owner's ``host_owner_scope``. Replies map through
``map_host_reply``, as the in-process conformance channel's do, and
``HostWorkspaceOps`` then checks each op's payload shape. A lost tunnel or a
missed deadline leaves the outcome unknown; callers retry with the same op key.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import override

from coral.omni._upstream import (
    HostWorkspaceOpNotPermittedError,
    HostWorkspaceOpsUnsupportedError,
    HostWorkspaceOpUnavailableError,
    request_workspace_op_on_host,
)
from coral.omni.protocols import HostWorkspaceChannels
from coral.omni.server.host_access import (
    HostAccessError,
    OwnerHost,
    authorize_owner_host,
    host_not_available,
)
from coral.workspace.host_backend import host_capability_unavailable, map_host_reply
from coral.workspace.ops import HostChannelBackend, OpName, WorkspaceErrorCode, WorkspaceOpError
from omnigent.server.host_registry import HostRegistry
from omnigent.stores.host_store import HostStore


class OmnigentHostWorkspaceChannels(HostWorkspaceChannels):
    """Host workspace-op channels on this server's live host connections."""

    def __init__(self, *, host_registry: HostRegistry, host_store: HostStore) -> None:
        self._host_registry = host_registry
        self._host_store = host_store

    @override
    async def channel(
        self,
        *,
        workspace_id: int,
        user_id: str | None,
        account_generation: str | None,
        host_id: str,
    ) -> HostChannelBackend:
        await authorize_owner_host(
            host_store=self._host_store,
            user_id=user_id,
            account_generation=account_generation,
            host_id=host_id,
            workspace_id=workspace_id,
        )
        return _OwnerHostChannel(
            OwnerHost(
                host_registry=self._host_registry,
                host_id=host_id,
                workspace_id=workspace_id,
                user_id=user_id,
                account_generation=account_generation,
            )
        )


class _OwnerHostChannel(HostChannelBackend):
    """
    The workspace-op channel to one authorized owner's host.

    Private: only ``OmnigentHostWorkspaceChannels.channel`` builds it, after the
    ownership check.
    """

    def __init__(self, owner_host: OwnerHost) -> None:
        self._owner_host = owner_host

    @override
    async def request(
        self,
        host_id: str,
        op: OpName,
        *,
        root: str,
        params: Mapping[str, object],
        timeout_s: float,
        op_key: str | None,
    ) -> Mapping[str, object]:
        """
        Run ``op`` on the authorized host and return its payload.

        :raises WorkspaceOpError: ``backend_unavailable`` (retryable) when the
            host is offline or the tunnel dropped; ``timeout`` (retryable) when no
            reply came in time; ``capability_unavailable`` (permanent) when the
            host cannot serve Coral's ops; otherwise as :func:`map_host_reply`.
        :raises HostAccessError: ``not_permitted`` for another host than the one
            authorized, or a connection another owner or registration holds;
            nothing is sent.
        :raises ValueError: for params the host refused, or a frame it would drop.
        """
        if host_id != self._owner_host.host_id:
            raise HostAccessError("not_permitted", host_not_available(host_id))
        try:
            conn = self._owner_host.connection()
        except HostAccessError as exc:
            if exc.code != "host_offline":
                raise
            raise WorkspaceOpError("workspace.backend_unavailable", exc.message) from exc
        try:
            with self._owner_host.owner_scope():
                reply = await request_workspace_op_on_host(
                    host_registry=self._owner_host.host_registry,
                    host_conn=conn,
                    op=op,
                    root=root,
                    params=params,
                    timeout_s=timeout_s,
                    op_key=op_key,
                )
        except HostWorkspaceOpsUnsupportedError as exc:
            raise host_capability_unavailable(host_id) from exc
        except HostWorkspaceOpNotPermittedError as exc:
            # Auth is off here but the connection has an owner: never send to it.
            raise HostAccessError("not_permitted", host_not_available(host_id)) from exc
        except HostWorkspaceOpUnavailableError as exc:
            code: WorkspaceErrorCode = (
                "workspace.timeout" if exc.timed_out else "workspace.backend_unavailable"
            )
            raise WorkspaceOpError(code, exc.message) from exc
        return map_host_reply(dataclasses.asdict(reply), host_id=host_id)
