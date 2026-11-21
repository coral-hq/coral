"""K4 session access adapter wrapping Omnigent permission primitives."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request
from starlette.requests import HTTPConnection

from coral.omni.protocols import Viewer
from omnigent.db.account_authority import account_generation, current_account_user
from omnigent.entities import Conversation
from omnigent.server.auth import (
    LEVEL_EDIT,
    LEVEL_MANAGE,
    LEVEL_READ,
    RESERVED_USER_LOCAL,
    AuthProvider,
    authentication_requires_identity,
    local_single_user_enabled,
)
from omnigent.server.permissions import check_session_access
from omnigent.stores.conversation_store import ConversationStore
from omnigent.stores.permission_store import PermissionStore

CORAL_LEVEL_READ = LEVEL_READ
CORAL_LEVEL_EDIT = LEVEL_EDIT
CORAL_LEVEL_MANAGE = LEVEL_MANAGE


def resolve_user_id(
    connection: HTTPConnection,
    auth_provider: AuthProvider | None,
) -> str | None:
    """Extract the authenticated user id from *connection*, if auth is configured."""
    if auth_provider is None:
        return None
    return auth_provider.get_user_id(connection)


def ownerless_runs_allowed() -> bool:
    """Whether a run without an owner may make sessions: only on a single-user server."""
    return local_single_user_enabled()


def omnigent_owner(user_id: str | None) -> str | None:
    """
    The name Omnigent's own checks know a run owner by.

    Coral stores the single local user as no owner (:func:`viewer_for`). A single-user
    server's grants, hosts, user agents and request-free events name that user
    ``"local"``, so an ownerless run acts as ``"local"`` there. Elsewhere an ownerless
    run is refused before it acts, and ``None`` stays ``None``.
    """
    if user_id is None and ownerless_runs_allowed():
        return RESERVED_USER_LOCAL
    return user_id


def viewer_for(user_id: str | None, auth_provider: AuthProvider | None) -> Viewer | None:
    """
    The authenticated caller as a :class:`Viewer`, or ``None`` to refuse it.

    Call in the request's task right after authentication, before any thread hop,
    where the request's account authority is still set. A caller naming no user (or
    the local user) is the single local user only where the server requires no
    identity. A request whose account authority names another user is refused;
    one with an authority proves that authority's generation.
    """
    if user_id is None or user_id == RESERVED_USER_LOCAL:
        return None if authentication_requires_identity(auth_provider) else Viewer(user_id=None)
    authority = current_account_user()
    if authority is not None and authority != user_id:
        return None
    return Viewer(
        user_id=user_id,
        account_generation=account_generation(user_id),
        check_generation=authority is not None,
    )


def request_viewer(
    auth_provider: AuthProvider | None,
) -> Callable[[Request], Awaitable[Viewer]]:
    """
    A FastAPI dependency giving the request's caller as a :class:`Viewer`.

    It authenticates and builds the Viewer in one call, in the request's task, so
    ``viewer_for`` reads the account authority this authentication bound.
    A configured provider that finds no user is a 401, as in Omnigent's routes; a
    caller ``viewer_for`` refuses is a 403.
    """

    async def viewer(request: Request) -> Viewer:
        user_id = resolve_user_id(request, auth_provider)
        if auth_provider is not None and user_id is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        found = viewer_for(user_id, auth_provider)
        if found is None:
            raise HTTPException(status_code=403, detail="Not permitted")
        return found

    return viewer


def account_still_valid(auth_provider: AuthProvider | None) -> Callable[[Viewer], bool]:
    """
    Whether a caller's proven account generation is still current, read uncached: the
    account still exists and its generation has not moved. A provider that cannot tell
    answers no, so a stream relying on it ends rather than outlives a revocation.
    """
    check = getattr(auth_provider, "accepts_account_generation", None)

    def still_valid(viewer: Viewer) -> bool:
        if check is None or viewer.user_id is None:
            return False
        return bool(check(viewer.user_id, viewer.account_generation))

    return still_valid


def has_session_access(
    user_id: str | None,
    conversation_id: str,
    required_level: int,
    permission_store: PermissionStore,
    conversation_store: ConversationStore,
    conversation: Conversation | None = None,
) -> bool:
    """Delegate Coral session permission checks to ``check_session_access``."""
    return check_session_access(
        user_id=user_id,
        conversation_id=conversation_id,
        required_level=required_level,
        permission_store=permission_store,
        conversation_store=conversation_store,
        conversation=conversation,
    )
