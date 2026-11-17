# CORAL(S41): the event handler stays reachable for in-process senders.
# CORAL(S42): an engine context passes the same gates as an HTTP sender.
"""An in-process engine sender posts session events with no HTTP request."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from starlette.datastructures import Headers

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.host.frames import HostHelloFrame
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.managed_hosts import parse_sandbox_config
from omnigent.server.routes._sessions.helpers import _HostLaunchAttempt
from omnigent.server.schemas import SessionEventInput
from omnigent.server.startup_inputs import STARTUP_LABEL, EngineEventContext
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE
from tests.server.conftest import ControllableMockClient, _app_client
from tests.server.helpers import create_session_for_agent, create_test_agent
from tests.server.integration.test_policy_deny_lifecycle_e2e import _attach_deny_policy
from tests.server.integration.test_sessions_web_send_stable_id import _stub_runner

pytestmark = pytest.mark.asyncio
_STABLE_ID = "5b0e3c7a9d1f4e6b8a2c0d4f6e8b1a3c"
_RUNNER_EVENT_TYPES = ("message", "interrupt", "stop_session")


def _brief(text: str, stable_id: str | None = None) -> SessionEventInput:
    """Return the user message an engine sends, under its pre-recorded stable id."""
    data: dict[str, Any] = {"role": "user", "content": [{"type": "input_text", "text": text}]}
    if stable_id is not None:
        data["stable_id"] = stable_id
    return SessionEventInput(type="message", data=data)


def _runner_events(forwarded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the turn and control events the runner received, in order."""
    return [body for body in forwarded if body.get("type") in _RUNNER_EVENT_TYPES]


@pytest_asyncio.fixture()
async def managed_app(runtime_init: None, db_uri: str, tmp_path: Path) -> AsyncIterator[FastAPI]:
    """An app configured for managed sandboxes, so startup inputs exist."""
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    app = create_app(
        agent_store=SqlAlchemyAgentStore(db_uri),
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=SqlAlchemyConversationStore(db_uri),
        artifact_store=artifact_store,
        agent_cache=AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache"),
        host_store=HostStore(db_uri),
        sandbox_config=parse_sandbox_config(
            {
                "provider": "modal",
                "server_url": "https://managed-test.example.com",
                "modal": {"image": "docker.io/test/omnigent-host:latest"},
            }
        ),
    )
    yield app
    await app.state.startup_inputs.shutdown()


async def test_session_event_dispatch_is_set_with_and_without_managed_sandboxes(
    app: FastAPI, managed_app: FastAPI
) -> None:
    """The handler is reachable on every server, and managed startup still shares it."""
    assert app.state.startup_inputs is None
    assert callable(app.state.session_event_dispatch)
    assert managed_app.state.session_event_dispatch is managed_app.state.startup_inputs.dispatch


async def test_engine_context_message_interrupt_and_stop_pass_input_policy(
    policy_app: FastAPI,
    policy_client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brief persists under its stable id; deny, close, interrupt and stop act as for HTTP."""
    from omnigent.server.routes import session_policies

    registered = session_policies.is_registered_handler
    monkeypatch.setattr(
        session_policies,
        "is_registered_handler",
        lambda handler: (
            handler == "omnigent.policies.function.make_fixed_action_callable"
            or registered(handler)
        ),
    )
    forwarded: list[dict[str, Any]] = []
    runner = _stub_runner(monkeypatch, forwarded)
    dispatch = policy_app.state.session_event_dispatch
    engine = EngineEventContext(policy_app, None)
    try:
        agent = await create_test_agent(policy_client)
        session_id = await create_session_for_agent(policy_client, agent["id"])
        with contextlib.ExitStack() as in_flight:
            sent = await dispatch(
                engine, session_id, _brief("Do the step.", _STABLE_ID), in_flight
            )
        interrupted = await dispatch(engine, session_id, SessionEventInput(type="interrupt"), None)
        stopped = await dispatch(engine, session_id, SessionEventInput(type="stop_session"), None)

        await _attach_deny_policy(policy_client, session_id, reason="Engine brief blocked")
        denied = await dispatch(engine, session_id, _brief("A denied brief."), None)

        SqlAlchemyConversationStore(db_uri).set_labels(
            session_id, {CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE}
        )
        with pytest.raises(OmnigentError) as closed:
            await dispatch(engine, session_id, _brief("A brief after close."), None)
    finally:
        await runner.aclose()

    assert sent["queued"] is True
    items = (await policy_client.get(f"/v1/sessions/{session_id}/items")).json()["data"]
    assert next(item["id"] for item in items if item["type"] == "message") == _STABLE_ID
    events = _runner_events(forwarded)
    assert [event["type"] for event in events] == ["message", "interrupt", "stop_session"]
    assert events[0]["persisted_item_id"] == _STABLE_ID
    assert interrupted == stopped == {"queued": False}
    assert denied["queued"] is False and denied["denied"] is True
    assert "Engine brief blocked" in denied["reason"]
    assert closed.value.code == ErrorCode.CONFLICT


@pytest.mark.parametrize("sender", ["alice@example.test", "mallory@example.test"])
async def test_engine_context_acts_as_its_user(
    auth_app: FastAPI,
    auth_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    sender: str,
) -> None:
    """The engine is authorized as the user it names, never by request headers."""
    auth_client.headers["X-Forwarded-Email"] = "alice@example.test"
    agent = await create_test_agent(auth_client)
    session_id = await create_session_for_agent(auth_client, agent["id"])
    forwarded: list[dict[str, Any]] = []
    runner = _stub_runner(monkeypatch, forwarded)
    dispatch = auth_app.state.session_event_dispatch
    engine = EngineEventContext(auth_app, sender)
    try:
        if sender.startswith("alice"):
            await dispatch(engine, session_id, _brief("Owner brief.", _STABLE_ID), None)
            await dispatch(engine, session_id, SessionEventInput(type="stop_session"), None)
        else:
            with pytest.raises(OmnigentError) as refused:
                await dispatch(engine, session_id, _brief("Foreign brief."), None)
            assert refused.value.code in (ErrorCode.NOT_FOUND, ErrorCode.FORBIDDEN)
    finally:
        await runner.aclose()

    if sender.startswith("alice"):
        assert [event["type"] for event in _runner_events(forwarded)] == [
            "message",
            "stop_session",
        ]
        items = (await auth_client.get(f"/v1/sessions/{session_id}/items")).json()["data"]
        [brief] = [item for item in items if item["id"] == _STABLE_ID]
        assert brief["created_by"] == sender
    else:
        assert _runner_events(forwarded) == []


async def test_engine_message_skips_the_managed_startup_queue(
    managed_app: FastAPI,
    mock_llm: ControllableMockClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a managed server the engine's message is dispatched now, never saved for startup."""
    forwarded: list[dict[str, Any]] = []
    runner = _stub_runner(monkeypatch, forwarded)
    startup = managed_app.state.startup_inputs
    try:
        async with _app_client(managed_app, mock_llm, tmp_path) as client:
            agent = await create_test_agent(client)
            session_id = await create_session_for_agent(client, agent["id"])
            # A browser message would now wait behind the session's startup.
            startup.conversations.set_labels(session_id, {STARTUP_LABEL: "pending"})
            result = await managed_app.state.session_event_dispatch(
                EngineEventContext(managed_app, None),
                session_id,
                _brief("Engine brief.", _STABLE_ID),
                None,
            )
    finally:
        await runner.aclose()

    assert "pending_id" not in result
    assert startup.conversations.list_pending_inputs(session_id) == []
    [message] = _runner_events(forwarded)
    assert message["type"] == "message" and message["persisted_item_id"] == _STABLE_ID


async def test_engine_context_relaunch_refusal_is_typed(
    app: FastAPI,
    client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host refusing the relaunch raises for the engine instead of reporting ``queued``."""
    agent = await create_test_agent(client)
    session_id = await create_session_for_agent(client, agent["id"])
    store = SqlAlchemyConversationStore(db_uri)
    host_id = uuid4().hex
    store.set_host_id(session_id, host_id, "/tmp/engine-workspace")
    app.state.host_registry.register(
        host_id,
        AsyncMock(),
        HostHelloFrame(version="test", frame_protocol_version=1, name="engine-test", runners=[]),
        owner=None,
    )
    launch = AsyncMock(
        return_value=_HostLaunchAttempt(
            runner_id=uuid4().hex,
            error_code="harness_not_configured",
            error="harness is not configured on this host",
        )
    )
    monkeypatch.setattr(
        "omnigent.server.routes.sessions._get_runner_client", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("omnigent.server.routes.sessions._launch_runner_on_host", launch)

    with pytest.raises(OmnigentError) as refused:
        await app.state.session_event_dispatch(
            EngineEventContext(app, None), session_id, _brief("Engine brief."), None
        )

    assert refused.value.code == ErrorCode.RUNNER_UNAVAILABLE
    assert "harness is not configured on this host" in refused.value.message
    assert launch.await_count == 1
    # No failed turn is recorded for the engine: the caller retries the send.
    assert [item.type for item in store.list_items(session_id).data if item.type == "error"] == []


async def test_engine_context_carries_no_caller_headers(app: FastAPI) -> None:
    """No runner tunnel credential can ride an engine send: headers are always empty."""
    assert EngineEventContext(app, "alice@example.test").headers == Headers()
    with pytest.raises(TypeError):
        EngineEventContext(app, "alice@example.test", headers=Headers())  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "event",
    [
        SessionEventInput(
            type="approval", data={"elicitation_id": "elicit_1", "action": "accept"}
        ),
        SessionEventInput(type="retry_session"),
        SessionEventInput(type="external_session_status", data={"status": "idle"}),
        _brief("!ls"),
        _brief("  !ls -la"),
        _brief("/side x"),
        _brief("/login"),
    ],
    ids=["approval", "retry_session", "external_status", "shell", "spaced_shell", "side", "login"],
)
async def test_engine_context_refuses_events_beyond_briefs_interrupts_and_stops(
    app: FastAPI,
    client: httpx.AsyncClient,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
    event: SessionEventInput,
) -> None:
    """Other event types and command-shaped briefs are refused before anything acts on them."""
    forwarded: list[dict[str, Any]] = []
    runner = _stub_runner(monkeypatch, forwarded)
    try:
        agent = await create_test_agent(client)
        session_id = await create_session_for_agent(client, agent["id"])
        with pytest.raises(OmnigentError) as refused:
            await app.state.session_event_dispatch(
                EngineEventContext(app, None), session_id, event, None
            )
    finally:
        await runner.aclose()

    expected = ErrorCode.INVALID_INPUT if event.type == "message" else ErrorCode.FORBIDDEN
    assert refused.value.code == expected
    assert _runner_events(forwarded) == []
    assert SqlAlchemyConversationStore(db_uri).list_items(session_id).data == []
