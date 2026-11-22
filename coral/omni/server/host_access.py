"""Whether a run owner may use a host, and the live connection and scope to reach it.

Engine work on the user's host (run worktrees, workspace ops) has no HTTP
request, so the run owner is authorized from the stored host row before any
frame is sent: the owner's own host, from the same account registration, not
a managed sandbox. Every later frame looks the live connection up again,
refuses one another owner or registration holds, and is sent under
Omnigent's ``host_owner_scope``, so a replaced connection never receives it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from coral.omni.protocols import HostAccessRefused
from coral.omni.server.access import omnigent_owner
from omnigent.db.db_models import workspace_scope
from omnigent.server.host_registry import HostConnection, HostRegistry, host_owner_scope
from omnigent.stores.host_store import Host, HostStore
from omnigent.util.uuid import InvalidUuidError, uuid_to_bytes


class HostAccessError(HostAccessRefused):
    """A host-access check failed: ``not_permitted`` or ``host_offline``."""


async def authorize_owner_host(
    *,
    host_store: HostStore,
    user_id: str | None,
    account_generation: str | None,
    host_id: str,
    workspace_id: int,
) -> Host:
    """
    Check from the stored host row that the run owner may use ``host_id``.

    Callers take ``user_id``, ``account_generation`` and ``workspace_id`` from
    the stored run, never from a request or payload.

    :param user_id: The run owner. ``None`` is the single local user, checked as
        :func:`omnigent_owner` names it; only a server with no single local user,
        where no ownerless run can act, skips the owner and generation checks.
    :param account_generation: The owner's account registration saved with the
        run. A host row from another registration of the same user id is
        refused, as ``fire.py`` refuses it for scheduled tasks.
    :param workspace_id: The tenant partition the host row lives in.
    :raises HostAccessError: ``not_permitted`` for an unknown host (an id no
        host row can have included), another user's or registration's host, or
        a managed sandbox host.
    """
    try:
        # The store raises an untyped error for an id that is not a uuid.
        uuid_to_bytes(host_id)
    except InvalidUuidError:
        raise HostAccessError("not_permitted", host_not_available(host_id)) from None
    with workspace_scope(workspace_id):
        host = await asyncio.to_thread(host_store.get_host, host_id)
    owner = omnigent_owner(user_id)
    # One message for unknown and foreign hosts, so neither is revealed.
    if host is None or (
        owner is not None
        and (host.user_id != owner or host.account_generation != account_generation)
    ):
        raise HostAccessError("not_permitted", host_not_available(host_id))
    if host.sandbox_provider is not None:
        raise HostAccessError(
            "not_permitted",
            f"host {host_id!r} is a managed sandbox; run worktrees need the user's host",
        )
    return host


def host_not_available(host_id: str) -> str:
    return f"host {host_id!r} is not available to this user"


@dataclass(frozen=True)
class OwnerHost:
    """
    One host, as an authorized run owner reaches it.

    Build it only after :func:`authorize_owner_host` accepted the same owner.
    """

    host_registry: HostRegistry
    host_id: str
    workspace_id: int
    user_id: str | None
    account_generation: str | None

    def current(self) -> HostConnection | None:
        """The host's live connection in the run's workspace, whoever holds it."""
        return self.host_registry.get(self.host_id, workspace_id=self.workspace_id)

    def connection(self) -> HostConnection:
        """
        The host's live connection, if the authorized owner still holds it.

        :raises HostAccessError: ``host_offline`` when there is none;
            ``not_permitted`` when another owner or registration holds it.
        """
        conn = self.current()
        if conn is None:
            raise HostAccessError("host_offline", f"host {self.host_id!r} is not connected")
        owner = omnigent_owner(self.user_id)
        if owner is not None and (conn.owner, conn.account_generation) != (
            owner,
            self.account_generation,
        ):
            raise HostAccessError("not_permitted", host_not_available(self.host_id))
        return conn

    @contextmanager
    def owner_scope(self) -> Iterator[None]:
        """Make ``HostRegistry.send_text`` refuse any connection but the authorized owner's."""
        with (
            workspace_scope(self.workspace_id),
            host_owner_scope(omnigent_owner(self.user_id), self.account_generation),
        ):
            yield
