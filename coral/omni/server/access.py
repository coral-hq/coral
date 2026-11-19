"""K4 session access adapter wrapping Omnigent permission primitives."""

from __future__ import annotations

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
