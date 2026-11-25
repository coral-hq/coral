"""Tests for ``coral.omni.server.access`` and ``coral.omni.process_map``."""

from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path

import pytest
from starlette.requests import HTTPConnection

from coral.omni.process_map import (
    CLAUDE_SDK_NO_SANDBOX_ENV,
    CORAL_RUNNER_TOKEN,
    CORAL_SANDBOX_POLICY_TOKEN,
    SANDBOX_POLICY_REVISION,
    host_entry_points_disabled,
    host_tokens,
)
from coral.omni.server.access import CORAL_LEVEL_READ, has_session_access, resolve_user_id
from coral.profiles.bundle_spec import Stance
from omnigent.entities import Conversation
from omnigent.inner import claude_sdk_executor, seatbelt_sandbox
from omnigent.server.auth import AuthProvider
from tests.coral.omni.test_reviewer_sandbox import _step_os_env


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
    # The step sandbox rules the gate label's table was measured at.
    assert CORAL_SANDBOX_POLICY_TOKEN == "coral_sandbox_policy:3"
    assert host_entry_points_disabled({}) is False
    assert host_entry_points_disabled({"CORAL_DISABLE_HOST_ENTRY_POINTS": "1"}) is True
    assert host_entry_points_disabled({"CORAL_DISABLE_HOST_ENTRY_POINTS": "false"}) is False


def test_host_tokens_follow_the_disable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLAUDE_SDK_NO_SANDBOX_ENV, raising=False)
    assert host_tokens({}) == ("coral_runner:2", "coral_sandbox_policy:3")
    assert host_tokens({"CORAL_DISABLE_HOST_ENTRY_POINTS": "1"}) == ()
    # Without an explicit environment the process's own is read.
    monkeypatch.setenv("CORAL_DISABLE_HOST_ENTRY_POINTS", "true")
    assert host_tokens() == ()
    monkeypatch.delenv("CORAL_DISABLE_HOST_ENTRY_POINTS")
    assert host_tokens() == (CORAL_RUNNER_TOKEN, CORAL_SANDBOX_POLICY_TOKEN)


def _step_profile_lines(
    stance: Stance, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """A generated step's macOS profile for ``workspace``, as text built on any platform."""
    os_env = _step_os_env(stance, workspace)
    assert os_env.sandbox is not None
    seatbelt = dataclasses.replace(os_env.sandbox, type="darwin_seatbelt")
    backend = seatbelt_sandbox.SeatbeltSandboxBackend()
    with monkeypatch.context() as on_macos:
        # The resolver refuses other platforms; the profile it leads to is text, built anywhere.
        on_macos.setattr(seatbelt_sandbox.sys, "platform", "darwin")
        on_macos.setattr(seatbelt_sandbox.shutil, "which", lambda name: f"/usr/bin/{name}")
        policy = backend.resolve(dataclasses.replace(os_env, sandbox=seatbelt), workspace)
    return seatbelt_sandbox._build_profile(policy, workspace).splitlines()


@pytest.mark.usefixtures("coral_policy_registry")
@pytest.mark.parametrize("stance", [Stance.IMPLEMENTER, Stance.REVIEWER])
def test_a_host_reports_revision_2_exactly_when_its_step_profiles_refuse_unix_sockets(
    stance: Stance, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The revision a host reports is a constant, and the rule it stands for is built elsewhere:
    from revision 2 on, a generated step's macOS profile shares the host network and refuses
    every Unix-domain socket before it allows any. Neither may change without the other.
    """
    lines = _step_profile_lines(stance, tmp_path, monkeypatch)

    # Both generated stances run with the network on: the profile the gate rows are about.
    shared = lines.index("(allow network*)")
    unix_socket_rules = [line for line in lines if "(remote unix-socket" in line]
    refused_first = "(deny network-outbound (remote unix-socket))"
    refuses = lines[shared + 1] == refused_first and unix_socket_rules[0] == refused_first
    assert refuses is (int(SANDBOX_POLICY_REVISION) >= 2), (
        f"revision {SANDBOX_POLICY_REVISION} is reported by a host whose step profile "
        f"{'refuses' if refuses else 'does not refuse'} other programs' Unix-domain sockets"
    )


@pytest.mark.usefixtures("coral_policy_registry")
@pytest.mark.parametrize("stance", [Stance.IMPLEMENTER, Stance.REVIEWER])
def test_a_host_reports_revision_3_exactly_when_its_step_profiles_keep_masked_entries_in_place(
    stance: Stance, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    From revision 3 on, a generated step's macOS profile also keeps the workspace that holds a
    masked dotfile in place and uncloned, so the file cannot reach a path no deny names.
    Revision 3 stands for both rules; the socket rule is bound by the test above.
    """
    (tmp_path / ".env").write_text(f"fake-{uuid.uuid4().hex}")
    lines = _step_profile_lines(stance, tmp_path, monkeypatch)

    workspace = seatbelt_sandbox._quote(str(tmp_path.resolve()))
    keeps = f"(deny file-write-unlink file-clone (literal {workspace}))" in lines
    assert keeps is (int(SANDBOX_POLICY_REVISION) >= 3), (
        f"revision {SANDBOX_POLICY_REVISION} is reported by a host whose step profile "
        f"{'keeps' if keeps else 'does not keep'} a dir holding a masked entry in place"
    )


@pytest.mark.parametrize("value", ["1", "0", "true"])
def test_a_host_that_runs_steps_unsandboxed_claims_no_sandbox_policy(value: str) -> None:
    # Any value the executor reads as its bypass: the gate label then reads the host unknown.
    assert host_tokens({CLAUDE_SDK_NO_SANDBOX_ENV: value}) == (CORAL_RUNNER_TOKEN,)
    assert host_tokens({CLAUDE_SDK_NO_SANDBOX_ENV: ""}) == (
        CORAL_RUNNER_TOKEN,
        CORAL_SANDBOX_POLICY_TOKEN,
    )
    assert CLAUDE_SDK_NO_SANDBOX_ENV == claude_sdk_executor._NO_SANDBOX_ENV
