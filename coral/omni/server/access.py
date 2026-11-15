"""K4 session access adapter wrapping Omnigent permission primitives."""

from __future__ import annotations

from starlette.requests import HTTPConnection

from omnigent.entities import Conversation
from omnigent.server.auth import LEVEL_EDIT, LEVEL_MANAGE, LEVEL_READ, AuthProvider
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
