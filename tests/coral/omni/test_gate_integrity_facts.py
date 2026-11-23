"""The gate label's facts as the server reads them: its startup config and the owner's host."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from coral.gates.integrity import HostSandboxPolicy, ServerConfigFacts
from coral.omni.process_map import CORAL_SANDBOX_POLICY_TOKEN, SANDBOX_POLICY_REVISION
from coral.omni.server import gate_integrity
from coral.omni.server.gate_integrity import (
    host_sandbox_reader,
    sandbox_policy,
    server_gate_facts,
)
from omnigent.db.account_authority import account_authority_scope
from omnigent.host.frames import HostHelloFrame
from omnigent.server.auth import UnifiedAuthProvider
from omnigent.server.host_registry import HostRegistry
from tests.server.test_host_registry import FakeWebSocket

HOST_ID = "a" * 32
WORKSPACE = 0
SEATBELT = "os_sandbox:darwin_seatbelt"
POLICY = CORAL_SANDBOX_POLICY_TOKEN
REVISION = SANDBOX_POLICY_REVISION
MACHINE_CLIENT = {
    "OMNIGENT_MACHINE_CLIENT_ID": "coral-test-client",
    "OMNIGENT_MACHINE_CLIENT_SECRET_HASH": "0" * 64,
    "OMNIGENT_MACHINE_SUB": "coral-test-machine",
}
SERVER_ENV = (
    *MACHINE_CLIENT,
    "OMNIGENT_MACHINE_TOKEN_TTL",
    "OMNIGENT_DEVICE_GRANT_ENABLED",
    "OMNIGENT_LOCAL_SINGLE_USER",
    "OMNIGENT_CONFIG",
)
# An app whose state never recorded the runner-token allow-list.
NO_ALLOW_LIST = object()


@pytest.mark.parametrize(
    ("capabilities", "policy"),
    [
        ([SEATBELT, POLICY], HostSandboxPolicy("seatbelt", REVISION)),
        (["os_sandbox:linux_bwrap", "plugins", POLICY], HostSandboxPolicy("bwrap", REVISION)),
        (["os_sandbox:none", POLICY], HostSandboxPolicy("none", REVISION)),
        ([SEATBELT, "coral_sandbox_policy:7"], HostSandboxPolicy("seatbelt", "7")),
        # A policy revision without the host's own sandbox token, or the reverse.
        ([POLICY], None),
        ([SEATBELT], None),
        # Only the host's reserved token names the backend, never a provider's report.
        (["coral_host_sandbox:1:darwin:seatbelt:1", POLICY], None),
        # Two revisions disagree: neither is believed.
        ([SEATBELT, POLICY, "coral_sandbox_policy:other"], None),
        ([SEATBELT, POLICY, POLICY], HostSandboxPolicy("seatbelt", REVISION)),
        # Only a changed host sends two sandbox tokens: neither is believed.
        ([SEATBELT, "os_sandbox:none", POLICY], None),
        (["os_sandbox:none", SEATBELT, POLICY], None),
        ([SEATBELT, SEATBELT, POLICY], None),
    ],
)
def test_a_host_s_sandbox_policy_is_its_own_backend_and_one_revision(
    capabilities: list[str], policy: HostSandboxPolicy | None
) -> None:
    assert sandbox_policy(capabilities) == policy


def _registry(owner: str | None, generation: str | None, capabilities: list[str]) -> HostRegistry:
    registry = HostRegistry()
    hello = HostHelloFrame(
        version="0.22.0", frame_protocol_version=1, name="laptop", capabilities=capabilities
    )
    with account_authority_scope(owner, generation):
        registry.register(HOST_ID, FakeWebSocket(), hello, owner=owner, workspace_id=WORKSPACE)
    return registry


@pytest.mark.parametrize(
    ("asked", "policy"),
    [
        ({}, HostSandboxPolicy("seatbelt", REVISION)),
        ({"user_id": "bob"}, None),
        ({"account_generation": "gen-2"}, None),
        ({"account_generation": None}, None),
        ({"workspace_id": 7}, None),
        ({"host_id": "b" * 32}, None),
        # An ownerless run names no owner the host could belong to.
        ({"user_id": None}, None),
    ],
)
def test_only_the_run_owner_s_own_connected_host_gives_a_policy(
    asked: dict[str, Any], policy: HostSandboxPolicy | None
) -> None:
    read = host_sandbox_reader(_registry("alice", "gen-1", [SEATBELT, POLICY]))
    owner_host: dict[str, Any] = {
        "user_id": "alice",
        "account_generation": "gen-1",
        "host_id": HOST_ID,
        "workspace_id": WORKSPACE,
    }

    assert read(**{**owner_host, **asked}) == policy


def test_off_a_single_user_server_an_ownerless_run_still_gives_no_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # There the host's owner check passes for no owner, so the reader refuses it first.
    monkeypatch.delenv("OMNIGENT_LOCAL_SINGLE_USER", raising=False)
    read = host_sandbox_reader(_registry("alice", "gen-1", [SEATBELT, POLICY]))

    policy = read(
        user_id=None, account_generation="gen-1", host_id=HOST_ID, workspace_id=WORKSPACE
    )

    assert policy is None


def test_a_registry_that_fails_reads_as_unknown_and_logs_the_error_type_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenRegistry(HostRegistry):
        def get(self, host_id: str, workspace_id: int | None = None) -> Any:
            raise RuntimeError(f"registry detail for {host_id}")

    read = host_sandbox_reader(BrokenRegistry())
    owner_host = {
        "user_id": "alice",
        "account_generation": "gen-1",
        "host_id": HOST_ID,
        "workspace_id": WORKSPACE,
    }
    with caplog.at_level(logging.DEBUG, logger=gate_integrity.__name__):
        policies = [read(**owner_host), read(**owner_host)]

    assert policies == [None, None]
    assert "RuntimeError" in caplog.text
    assert "registry detail" not in caplog.text
    # The run page polls its detail: one warning, then debug lines.
    assert [record.levelno for record in caplog.records] == [logging.WARNING, logging.DEBUG]


def test_a_hello_the_reader_cannot_parse_reads_as_unknown(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def unparsable(_capabilities: object) -> None:
        raise ValueError("hello detail")

    monkeypatch.setattr(gate_integrity, "sandbox_policy", unparsable)
    read = host_sandbox_reader(_registry("alice", "gen-1", [SEATBELT, POLICY]))
    with caplog.at_level(logging.WARNING, logger=gate_integrity.__name__):
        policy = read(
            user_id="alice", account_generation="gen-1", host_id=HOST_ID, workspace_id=WORKSPACE
        )

    assert policy is None
    assert "ValueError" in caplog.text
    assert "hello detail" not in caplog.text


def _facts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    env: dict[str, str] | None = None,
    tokens: object = None,
    data_dir: str | None = None,
    artifacts: str | None = None,
    database: str | None = None,
    conversation_database: str | None = None,
    server_config: dict[str, Any] | None = None,
    auth_provider: object = None,
) -> Any:
    """The facts for a server built from these inputs; anything unset is a plain local one."""
    for name in SERVER_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("OMNIGENT_DATA_DIR", data_dir or str(tmp_path / "data"))
    state = (
        SimpleNamespace()
        if tokens is NO_ALLOW_LIST
        else SimpleNamespace(runner_tunnel_tokens=tokens)
    )
    conversations = SimpleNamespace(
        storage_location=database or f"sqlite:///{tmp_path / 'chat.db'}",
        conversation_storage_location=conversation_database,
    )
    services = SimpleNamespace(
        auth_provider=auth_provider,
        server_config=server_config or {},
        artifact_store=SimpleNamespace(storage_location=artifacts or str(tmp_path / "artifacts")),
        conversation_store=conversations,
        permission_store=SimpleNamespace(storage_location=conversations.storage_location),
    )
    return server_gate_facts(SimpleNamespace(state=state), cast(Any, services))


def test_a_plain_server_s_config_is_verified_and_its_mode_is_its_providers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    header = UnifiedAuthProvider(source="header", local_single_user=True)

    facts = _facts(monkeypatch, tmp_path, auth_provider=header)

    assert facts.server_mode == "header"
    assert facts.native_steps_enabled is False
    assert facts.server_config == ServerConfigFacts(
        runner_token_allow_listed=False,
        machine_client=False,
        device_grant=False,
        state_under_step_read_root=False,
        local_single_user=False,
    )
    assert facts.host_sandbox is None
    assert _facts(monkeypatch, tmp_path).server_mode == "none"


@pytest.mark.parametrize(
    ("inputs", "fact", "value"),
    [
        ({"tokens": frozenset({"allow-listed"})}, "runner_token_allow_listed", True),
        ({"tokens": NO_ALLOW_LIST}, "runner_token_allow_listed", None),
        ({"env": MACHINE_CLIENT}, "machine_client", True),
        # A partial machine client stops the server; the label calls it unknown.
        ({"env": {"OMNIGENT_MACHINE_CLIENT_ID": "half"}}, "machine_client", None),
        ({"env": {"OMNIGENT_DEVICE_GRANT_ENABLED": "1"}}, "device_grant", True),
        ({"data_dir": "/opt/homebrew/var/omnigent"}, "state_under_step_read_root", True),
        ({"data_dir": "/usr"}, "state_under_step_read_root", True),
        ({"artifacts": "/Library/Omnigent/artifacts"}, "state_under_step_read_root", True),
        # A UC Volume is remote; a URL the local store would take as a relative dir is unplaced.
        ({"artifacts": "dbfs:/Volumes/cat/schema/vol"}, "state_under_step_read_root", False),
        ({"artifacts": "s3://bucket/artifacts"}, "state_under_step_read_root", None),
        ({"data_dir": "/optional/omnigent"}, "state_under_step_read_root", False),
        # The databases the server opens, with their tokens and password hashes.
        (
            {"database": "sqlite:////opt/homebrew/var/omnigent/chat.db"},
            "state_under_step_read_root",
            True,
        ),
        (
            {"database": "sqlite:////usr/local/var/chat.db?check_same_thread=false"},
            "state_under_step_read_root",
            True,
        ),
        (
            {"conversation_database": "sqlite:////Library/Omnigent/conversations.db"},
            "state_under_step_read_root",
            True,
        ),
        ({"database": "sqlite://"}, "state_under_step_read_root", False),
        (
            {"database": "postgresql://coral@db.internal/omnigent"},
            "state_under_step_read_root",
            False,
        ),
        # A database the check cannot place: no host, or no URI at all.
        ({"database": "postgresql:///omnigent"}, "state_under_step_read_root", None),
        ({"database": "not a database uri"}, "state_under_step_read_root", None),
        # The server's -c config file, which may hold a database password.
        (
            {"env": {"OMNIGENT_CONFIG": "/usr/local/etc/omnigent/server.yaml"}},
            "state_under_step_read_root",
            True,
        ),
        # The single-user marker, which the identity probe never ran with.
        ({"env": {"OMNIGENT_LOCAL_SINGLE_USER": "1"}}, "local_single_user", True),
    ],
)
def test_each_server_config_fact_follows_its_setting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    inputs: dict[str, Any],
    fact: str,
    value: bool | None,
) -> None:
    config = _facts(monkeypatch, tmp_path, **inputs).server_config

    assert getattr(config, fact) is value
    others = {name: seen for name, seen in vars(config).items() if name != fact}
    assert set(others.values()) == {False}


def test_native_steps_follow_the_server_s_sub_feature(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    server_config = {"coral_sub_features": {"claude_native_steps": True}}

    assert _facts(monkeypatch, tmp_path, server_config=server_config).native_steps_enabled


def test_a_data_dir_reached_through_a_link_counts_where_the_link_leads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    link = tmp_path / "state"
    link.symlink_to("/usr/share")

    facts = _facts(monkeypatch, tmp_path, data_dir=str(link / "omnigent"))

    assert facts.server_config.state_under_step_read_root is True


def test_a_data_dir_named_under_a_read_root_counts_wherever_its_link_leads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "read-root"
    root.mkdir()
    (root / "state").symlink_to(tmp_path / "elsewhere")
    monkeypatch.setattr(
        "coral.omni.server.gate_integrity.seatbelt_default_read_roots", (str(root),)
    )

    facts = _facts(monkeypatch, tmp_path, data_dir=str(root / "state" / "omnigent"))

    assert facts.server_config.state_under_step_read_root is True


def test_a_data_dir_whose_links_loop_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loop = tmp_path / "loop"
    loop.symlink_to(loop)

    facts = _facts(monkeypatch, tmp_path, data_dir=str(loop / "omnigent"))

    assert facts.server_config.state_under_step_read_root is None


@pytest.mark.parametrize("fold_case", [True, False])
def test_on_a_case_insensitive_volume_a_path_in_other_letter_case_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fold_case: bool
) -> None:
    monkeypatch.setattr(gate_integrity, "FOLD_PATH_CASE", fold_case)

    facts = _facts(monkeypatch, tmp_path, data_dir="/OPT/Homebrew/var/omnigent")

    assert facts.server_config.state_under_step_read_root is fold_case


def test_paths_fold_case_on_macos_only() -> None:
    assert gate_integrity.FOLD_PATH_CASE is (sys.platform == "darwin")
