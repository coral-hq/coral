"""A real Omnigent app for Coral's lifespan, and gate runs answered through its routes.

The app is ``create_app`` with the stores the session engine needs, served
in-process; tests enter ``coral_lifespan`` themselves, so a restart is an exit and
a new entry on the same database. Gate prompts live in this process's index.
"""

from __future__ import annotations

from collections.abc import Awaitable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coral.bridge.codec import decode_entries
from coral.db.migrate import ensure_coral_schema
from coral.engine.types import AnswerGate
from coral.model.ids import anchor_session_id
from coral.stores.protocols import CoralRun
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID, workspace_scope
from omnigent.runtime import pending_elicitations
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.auth import AuthProvider
from omnigent.server.server_plugins import ServerServices
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from tests.coral.bridge._gates import GATE_ONLY
from tests.coral.bridge._world import World, run_spec, start

# Mounts Coral's routers, the workflow Inbox among them, as the server config does.
CORAL_SERVER_PLUGIN = "coral.server_plugin"
INBOX = "/v1/coral/inbox"
ADMIN_PASSWORD = "admin-pw-12345"
ALICE_PASSWORD = "alice-pw-1234"


@dataclass
class CoralServer:
    """A real app with the stores the session engine needs, and its plugin services."""

    app: FastAPI
    services: ServerServices
    db_uri: str


def coral_server(
    db_uri: str,
    tmp_path: Path,
    *,
    auth_provider: AuthProvider | None = None,
    permission_store: SqlAlchemyPermissionStore | None = None,
    server_plugins: Sequence[str] | None = None,
) -> CoralServer:
    """The app and the services ``coral_lifespan`` reads, sharing stores and provider."""
    artifact = LocalArtifactStore(str(tmp_path / "artifacts"))
    conversation = SqlAlchemyConversationStore(db_uri)
    agent = SqlAlchemyAgentStore(db_uri)
    agent_cache = AgentCache(artifact_store=artifact, cache_dir=tmp_path / "cache")
    host = HostStore(db_uri)
    project = SqlAlchemyProjectStore(db_uri)
    file = SqlAlchemyFileStore(db_uri)
    app = create_app(
        agent_store=agent,
        file_store=file,
        conversation_store=conversation,
        artifact_store=artifact,
        agent_cache=agent_cache,
        host_store=host,
        project_store=project,
        permission_store=permission_store,
        auth_provider=auth_provider,
        server_plugins=server_plugins,
    )
    services = ServerServices(
        agent_store=agent,
        file_store=file,
        conversation_store=conversation,
        artifact_store=artifact,
        agent_cache=agent_cache,
        comment_store=None,
        policy_store=None,
        permission_store=permission_store,
        scheduled_task_store=None,
        project_store=project,
        preference_store=None,
        host_store=host,
        account_store=None,
        auth_provider=auth_provider,
        runner_router=app.state.runner_router,
        host_registry=app.state.host_registry,
        tunnel_registry=app.state.tunnel_registry,
        server_config={},
        host_sharded=False,
    )
    return CoralServer(app=app, services=services, db_uri=db_uri)


@dataclass
class AccountsServer:
    """The real accounts-mode server with Coral mounted, its lifespan run by the app."""

    admin: TestClient
    alice: TestClient
    # ``create_app``'s keyword arguments: the server's stores and auth provider.
    stores: dict[str, Any]


def register(admin: TestClient, username: str, password: str) -> TestClient:
    """A new client signed in as ``username``, registered through an admin's invite."""
    invite = admin.post("/auth/invite", json={}).json()["token"]
    client = TestClient(admin.app)
    response = client.post(
        "/auth/register", json={"invite": invite, "username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return client


@contextmanager
def accounts_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AccountsServer]:
    """
    An accounts-mode server with Coral's plugin, an admin signed in with
    :data:`ADMIN_PASSWORD` and ``alice`` registered with :data:`ALICE_PASSWORD`.

    The admin client holds the app's lifespan and its event loop (``admin.portal``).
    """
    import omnigent.server.app as app_module
    from tests.server.test_accounts import _build_accounts_app, _login

    original = app_module.create_app
    captured: dict[str, Any] = {}

    def with_coral(**kwargs: Any) -> FastAPI:
        # Run anchors are filed in their owner's project, so the session engine needs one.
        db_uri = kwargs["conversation_store"].storage_location
        kwargs["project_store"] = SqlAlchemyProjectStore(db_uri)
        captured.update(kwargs)
        return original(**kwargs, server_plugins=[CORAL_SERVER_PLUGIN])

    monkeypatch.setattr(app_module, "create_app", with_coral)
    clients = _build_accounts_app(tmp_path, monkeypatch, init_admin_password=ADMIN_PASSWORD)
    admin = next(clients)
    try:
        _login(admin, "admin", ADMIN_PASSWORD)
        yield AccountsServer(admin, register(admin, "alice", ALICE_PASSWORD), captured)
    finally:
        # Resuming the builder past its yield shuts the app down.
        next(clients, None)


def gate_run(
    db_uri: str,
    start_key: str = "gate-1",
    *,
    user: str | None = None,
    account_generation: str | None = None,
) -> tuple[World, CoralRun, str, str]:
    """
    A ``gate_only`` run at its gate; its anchor and prompt id.

    :param user: The run owner; ``None`` is the single local user of a server without
        authentication.
    :param account_generation: The owner's account generation the run records.
    """
    ensure_coral_schema(db_uri)
    world = World.sql(db_uri)
    spec = run_spec(
        user=user,
        start_key=start_key,
        workspace_id=DEFAULT_WORKSPACE_ID,
        account_generation=account_generation,
    )
    run = start(
        world, GATE_ONLY, spec=spec, start_key=start_key, allow_ownerless=user is None, actor=user
    )
    state, _version = world.runs.load_run_state(run.id, workspace_id=DEFAULT_WORKSPACE_ID)
    [row] = state.gate_visits
    assert row.elicitation_id is not None
    return world, run, anchor_session_id(DEFAULT_WORKSPACE_ID, run.id), row.elicitation_id


def run_status(world: World, run: CoralRun) -> int:
    stored = world.runs.get_run(run.id, workspace_id=DEFAULT_WORKSPACE_ID)
    assert stored is not None
    return stored.status


def pending_here(session_id: str, elicitation_id: str) -> bool:
    """Whether this process's index holds the prompt on the session."""
    with workspace_scope(DEFAULT_WORKSPACE_ID):
        found = pending_elicitations.lookup(elicitation_id, conversation_id=session_id)
    return found is not None


def prompt_shown(server: CoralServer, session_id: str, elicitation_id: str) -> bool:
    """Whether the session exists and holds the prompt; a startup republish precedes the create."""
    session = server.services.conversation_store.get_conversation(session_id)
    return session is not None and pending_here(session_id, elicitation_id)


def gate_answers(world: World, run_id: str) -> list[AnswerGate]:
    """The run's ``AnswerGate`` engine entries, in commit order."""
    rows = world.runs.read_engine_log(
        run_id, workspace_id=DEFAULT_WORKSPACE_ID, max_run_version=2**31
    )
    return [entry.input for entry in decode_entries(rows) if isinstance(entry.input, AnswerGate)]


async def pending_prompts(
    client: httpx.AsyncClient, session_id: str, headers: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """The session's pending prompts as ``GET /v1/sessions/{id}`` shows them."""
    response = await client.get(f"/v1/sessions/{session_id}", headers=headers)
    assert response.status_code == 200, response.text
    return list(response.json().get("pending_elicitations") or [])


def resolve_gate(
    client: httpx.AsyncClient,
    session_id: str,
    elicitation_id: str,
    label: str = "approve",
    headers: Mapping[str, str] | None = None,
) -> Awaitable[httpx.Response]:
    """Answer the prompt with ``label`` through the resolve URL."""
    return client.post(
        f"/v1/sessions/{session_id}/elicitations/{elicitation_id}/resolve",
        json={"action": "accept", "content": {"decision": label}},
        headers=headers,
    )


async def inbox(
    client: httpx.AsyncClient, headers: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    """The caller's whole workflow Inbox feed: one page, since tests stay under its limit."""
    response = await client.get(INBOX, headers=headers)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["next_cursor"] is None
    return list(page["data"])


def ack(
    client: httpx.AsyncClient, alert_id: str, headers: Mapping[str, str] | None = None
) -> Awaitable[httpx.Response]:
    """Mark a workflow alert read."""
    return client.post(f"{INBOX}/{alert_id}/ack", json={}, headers=headers)


def ack_run(
    client: httpx.AsyncClient, run_id: str, headers: Mapping[str, str] | None = None
) -> Awaitable[httpx.Response]:
    """Mark a run's low-priority workflow alerts read, as opening the run does."""
    return client.post(f"{INBOX}/ack", json={"run_id": run_id}, headers=headers)
