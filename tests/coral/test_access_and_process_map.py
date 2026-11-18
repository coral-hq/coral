"""Tests for ``coral.omni.server.access`` and ``coral.omni.process_map``."""

from __future__ import annotations

import pytest
from starlette.requests import HTTPConnection

from coral.omni.process_map import CORAL_RUNNER_TOKEN, host_entry_points_disabled, host_tokens
from coral.omni.server.access import CORAL_LEVEL_READ, has_session_access, resolve_user_id
from omnigent.entities import Conversation
from omnigent.server.auth import AuthProvider


class _StubAuthProvider(AuthProvider):
    def get_user_id(self, request: HTTPConnection) -> str | None:
        return request.headers.get("x-user")


class _StubPermissionStore:
    def is_admin(self, user_id: str) -> bool:
        return user_id == "admin@example.com"

    def check_access(self, _user_id: str, _conversation_id: str, _level: int) -> bool:
        return False


class _StubConversationStore:
    def get_conversation(self, conversation_id: str) -> Conversation | None:
        return None if conversation_id == "missing" else Conversation(id=conversation_id)


def test_access_adapter_delegates_auth_and_permissions() -> None:
    conn = HTTPConnection({"type": "http", "headers": [(b"x-user", b"admin@example.com")]})
    user = resolve_user_id(conn, _StubAuthProvider())
    assert user == "admin@example.com"
    assert resolve_user_id(conn, None) is None
    assert (
        has_session_access(
            user,
            "conv-1",
            CORAL_LEVEL_READ,
            _StubPermissionStore(),  # type: ignore[arg-type]
            _StubConversationStore(),  # type: ignore[arg-type]
        )
        is True
    )
    assert (
        has_session_access(
            "nobody@example.com",
            "missing",
            CORAL_LEVEL_READ,
            _StubPermissionStore(),  # type: ignore[arg-type]
            _StubConversationStore(),  # type: ignore[arg-type]
        )
        is False
    )


def test_process_map_constants_and_disable_flag() -> None:
    # Version 2: the host's Coral offers the engine tools.
    assert CORAL_RUNNER_TOKEN == "coral_runner:2"
    assert host_entry_points_disabled({}) is False
    assert host_entry_points_disabled({"CORAL_DISABLE_HOST_ENTRY_POINTS": "1"}) is True
    assert host_entry_points_disabled({"CORAL_DISABLE_HOST_ENTRY_POINTS": "false"}) is False


def test_host_tokens_follow_the_disable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    assert host_tokens({}) == ("coral_runner:2",)
    assert host_tokens({"CORAL_DISABLE_HOST_ENTRY_POINTS": "1"}) == ()
    # Without an explicit environment the process's own is read.
    monkeypatch.setenv("CORAL_DISABLE_HOST_ENTRY_POINTS", "true")
    assert host_tokens() == ()
    monkeypatch.delenv("CORAL_DISABLE_HOST_ENTRY_POINTS")
    assert host_tokens() == (CORAL_RUNNER_TOKEN,)
