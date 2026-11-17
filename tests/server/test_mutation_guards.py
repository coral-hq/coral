# CORAL(S53): mutation-guard registry and route call-site tests (new file).
"""Mutation guards: the registry's two phases, and every guarded route asking after authorization.

The app helpers here (:func:`guarded_app`, :func:`mutation_targets`) are shared
with the tests of guards that extensions register.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from omnigent.db.db_models import current_workspace_id, workspace_scope
from omnigent.entities import Conversation
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.host.frames import HostHelloFrame
from omnigent.runner.identity import RUNNER_TUNNEL_TOKEN_HEADER, token_bound_runner_id
from omnigent.runtime import init as init_runtime
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server import mutation_guards
from omnigent.server.app import _ensure_default_native_agents, create_app
from omnigent.server.auth import UnifiedAuthProvider
from omnigent.server.feature_flags import resolve_feature_flags
from omnigent.server.mcp_registry import McpRegistry, McpRegistryConfig
from omnigent.server.mutation_guards import (
    AGENT_INSTALL,
    AGENT_REMOVE,
    AGENT_UPDATE,
    SESSION_AGENT_REPLACE,
    SESSION_CREATE_CHILD,
    SESSION_EVENT,
    SESSION_GRANT,
    SESSION_LAUNCH_RUNNER,
    SESSION_MCP_CHANGE,
    SESSION_SCHEDULE,
    SESSION_UPDATE,
    MutationAttempt,
    MutationGuard,
    Screen,
    check_mutation,
    register_mutation_guard,
)
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.comment_store.sqlalchemy_store import SqlAlchemyCommentStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.credential_store.sqlalchemy_store import CredentialStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from omnigent.stores.policy_store.sqlalchemy_store import SqlAlchemyPolicyStore
from omnigent.stores.preference_store.sqlalchemy_store import SqlAlchemyPreferenceStore
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from omnigent.stores.scheduled_task_store.sqlalchemy_store import SqlAlchemyScheduledTaskStore
from tests.server.helpers import build_agent_bundle, create_test_agent
from tests.server.integration.test_scheduled_tasks_routes import (
    _HOST_ID,
    _create_body,
    _owned_session,
    _register_host,
)
from tests.server.test_credential_store import _FakeCipher

ALICE_EMAIL = "alice@example.com"
ALICE = {"X-Forwarded-Email": ALICE_EMAIL}
BOB = {"X-Forwarded-Email": "bob@example.com"}
NOBODY: dict[str, str] = {}
REFUSAL = "refused by the test guard"
# A tunnel token; the session it is bound to records the runner id it derives.
_TOKEN = "mutation-guards-runner-token"
_RUNNER = {RUNNER_TUNNEL_TOKEN_HEADER: _TOKEN}
_ROW = Conversation(
    id="conv_guarded", created_at=0, updated_at=0, root_conversation_id="conv_guarded"
)


def guarded_app(db_uri: str, tmp_path: Path, **extra: Any) -> FastAPI:
    """An app with every optional store and the MCP registry, multi-user header auth, runtime up.

    The native agents a lifespan would seed are seeded, so a task can name one
    without entering the lifespan.
    """
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    agents = SqlAlchemyAgentStore(db_uri)
    conversations = SqlAlchemyConversationStore(db_uri)
    files = SqlAlchemyFileStore(db_uri)
    cache = AgentCache(artifact_store=artifacts, cache_dir=tmp_path / "cache")
    _ensure_default_native_agents(agents, artifacts, cache)
    init_runtime(
        conversation_store=conversations,
        agent_store=agents,
        agent_cache=cache,
        file_store=files,
        artifact_store=artifacts,
    )
    return create_app(
        agent_store=agents,
        file_store=files,
        conversation_store=conversations,
        artifact_store=artifacts,
        agent_cache=cache,
        comment_store=SqlAlchemyCommentStore(db_uri),
        policy_store=SqlAlchemyPolicyStore(db_uri),
        permission_store=SqlAlchemyPermissionStore(db_uri),
        scheduled_task_store=SqlAlchemyScheduledTaskStore(db_uri),
        project_store=SqlAlchemyProjectStore(db_uri),
        host_store=HostStore(db_uri),
        preference_store=SqlAlchemyPreferenceStore(db_uri, authority_id="mutation-guards"),
        mcp_registry=McpRegistry(
            McpRegistryConfig(public_url="http://localhost", services=[]),
            CredentialStore(db_uri, _FakeCipher()),
        ),
        auth_provider=UnifiedAuthProvider(source="header", local_single_user=False),
        **extra,
    )


def _bundle_part(name: str) -> dict[str, tuple[str, bytes, str]]:
    return {"bundle": ("agent.tar.gz", build_agent_bundle(name), "application/gzip")}


@dataclass
class MutationTargets:
    """Alice's session, host, scheduled task and installed agent on a :func:`guarded_app`."""

    client: httpx.AsyncClient
    conversations: SqlAlchemyConversationStore
    # Top-level; runs its own session-scoped agent, so agent and MCP edits apply.
    session_id: str
    agent_id: str
    # Top-level on alice's host, running the agent the scheduled task uses.
    scheduled_session_id: str
    # A continue-mode task that has no session yet.
    task_id: str
    user_agent_id: str

    async def patch(self, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        return await self.client.patch(
            f"/v1/sessions/{self.session_id}", json=body, headers=headers
        )

    async def event(
        self, event_type: str, headers: dict[str, str], session_id: str | None = None
    ) -> httpx.Response:
        data = {"role": "user", "content": [{"type": "input_text", "text": "hi"}]}
        return await self.client.post(
            f"/v1/sessions/{session_id or self.session_id}/events",
            json={"type": event_type, "data": data},
            headers=headers,
        )

    async def launch(self, headers: dict[str, str]) -> httpx.Response:
        return await self.client.post(
            f"/v1/hosts/{_HOST_ID}/runners",
            json={"session_id": self.session_id, "workspace": "/repo"},
            headers=headers,
        )

    async def grant(
        self, headers: dict[str, str], user: str = "carol@example.com"
    ) -> httpx.Response:
        return await self.client.put(
            f"/v1/sessions/{self.session_id}/permissions",
            json={"user_id": user, "level": 1},
            headers=headers,
        )

    async def json_child(self, headers: dict[str, str]) -> httpx.Response:
        return await self.client.post(
            "/v1/sessions",
            json={"agent_id": self.agent_id, "parent_session_id": self.session_id},
            headers=headers,
        )

    async def bundle_child(self, headers: dict[str, str]) -> httpx.Response:
        return await self.client.post(
            "/v1/sessions",
            data={"metadata": json.dumps({"parent_session_id": self.session_id})},
            files=_bundle_part("child-agent"),
            headers=headers,
        )

    async def replace_agent(self, headers: dict[str, str]) -> httpx.Response:
        return await self.client.put(
            f"/v1/sessions/{self.session_id}/agent",
            files=_bundle_part("test-agent"),
            headers=headers,
        )

    async def add_mcp_server(self, headers: dict[str, str]) -> httpx.Response:
        return await self.client.post(
            f"/v1/sessions/{self.session_id}/agent/mcp-servers",
            json={"name": "notes", "transport": "stdio", "command": "echo"},
            headers=headers,
        )

    async def schedule(
        self, headers: dict[str, str], session_id: str | None = None
    ) -> httpx.Response:
        body = _create_body(
            session_mode="continue",
            session_id=session_id or self.scheduled_session_id,
            host_id=None,
            workspace=None,
        )
        return await self.client.post("/v1/scheduled-tasks", json=body, headers=headers)

    async def reschedule(self, headers: dict[str, str]) -> httpx.Response:
        return await self.client.patch(
            f"/v1/scheduled-tasks/{self.task_id}",
            json={"session_id": self.scheduled_session_id},
            headers=headers,
        )

    async def patch_agent(self, headers: dict[str, str]) -> httpx.Response:
        return await self.client.patch(
            f"/v1/agents/{self.user_agent_id}", json={"description": "edited"}, headers=headers
        )

    async def delete_agent(
        self, headers: dict[str, str], *, force: bool = False
    ) -> httpx.Response:
        return await self.client.delete(
            f"/v1/agents/{self.user_agent_id}",
            params={"force": "true"} if force else None,
            headers=headers,
        )

    async def install_agent(self, headers: dict[str, str], name: str = "orion") -> httpx.Response:
        return await self.client.post("/v1/agents", files=_bundle_part(name), headers=headers)

    async def bundle_create(self, headers: dict[str, str], name: str = "loose") -> httpx.Response:
        """A top-level session from an uploaded bundle, which stores it as the caller's agent."""
        return await self.client.post(
            "/v1/sessions",
            data={"metadata": json.dumps({})},
            files=_bundle_part(name),
            headers=headers,
        )

    async def sibling(
        self, headers: dict[str, str], source_id: str | None = None
    ) -> httpx.Response:
        """A nested agent beside the session (``sibling_sessions`` must be on)."""
        return await self.client.post(
            "/v1/sessions",
            json={"agent_id": self.agent_id, "sibling_source_id": source_id or self.session_id},
            headers=headers,
        )

    async def retitle(
        self, headers: dict[str, str], route: str, title: str = "Renamed"
    ) -> httpx.Response:
        """Rename through ``agent-title`` or ``auto-title``."""
        return await self.client.post(
            f"/v1/sessions/{self.session_id}/{route}", json={"title": title}, headers=headers
        )

    async def resolve_approval(
        self, headers: dict[str, str], session_id: str | None = None
    ) -> httpx.Response:
        return await self.client.post(
            f"/v1/sessions/{session_id or self.session_id}/elicitations/elicit_test/resolve",
            json={"action": "accept"},
            headers=headers,
        )

    async def post_transcript(
        self, headers: dict[str, str], session_id: str | None = None
    ) -> httpx.Response:
        """A batch of one transcript item, as a native forwarder posts them."""
        item = {
            "role": "assistant",
            "content": [{"type": "output_text", "text": "observed"}],
            "agent": "test-agent",
        }
        data = {"item_type": "message", "item_data": item, "response_id": "resp_1"}
        event = {"type": "external_conversation_item", "data": data}
        return await self.client.post(
            f"/v1/sessions/{session_id or self.session_id}/events",
            json=[event],
            headers=headers,
        )


async def mutation_targets(
    app: FastAPI, client: httpx.AsyncClient, db_uri: str
) -> MutationTargets:
    """Create alice's targets (bob exists too); no guard may be registered yet."""
    permissions = SqlAlchemyPermissionStore(db_uri)
    for headers in (ALICE, BOB):
        permissions.ensure_user(headers["X-Forwarded-Email"], is_admin=False)
    agent = await create_test_agent(client, user=ALICE_EMAIL)
    _register_host(app, _HOST_ID, ALICE_EMAIL)
    app.state.host_registry.register(
        _HOST_ID,
        AsyncMock(),
        HostHelloFrame(version="test", frame_protocol_version=1, name="laptop", runners=[]),
        owner=ALICE_EMAIL,
    )
    task = await client.post(
        "/v1/scheduled-tasks",
        json=_create_body(session_mode="continue", host_id=None, workspace=None),
        headers=ALICE,
    )
    assert task.status_code == 200, task.text
    installed = await client.post("/v1/agents", files=_bundle_part("orion"), headers=ALICE)
    assert installed.status_code == 200, installed.text
    return MutationTargets(
        client=client,
        conversations=SqlAlchemyConversationStore(db_uri),
        session_id=agent["_session_id"],
        agent_id=agent["id"],
        scheduled_session_id=_owned_session(db_uri),
        task_id=task.json()["id"],
        user_agent_id=installed.json()["id"],
    )


_Send = Callable[[MutationTargets, dict[str, str]], Awaitable[httpx.Response]]

# One request to every guarded route: the action it asks about, the request,
# and the identity that fails the route's own authorization.
GUARDED_REQUESTS: dict[str, tuple[str, _Send, dict[str, str]]] = {
    "session patch": (SESSION_UPDATE, lambda t, h: t.patch({"model_override": "m"}, h), BOB),
    "session event": (SESSION_EVENT, lambda t, h: t.event("message", h), BOB),
    "runner launch": (SESSION_LAUNCH_RUNNER, lambda t, h: t.launch(h), BOB),
    "grant": (SESSION_GRANT, lambda t, h: t.grant(h), BOB),
    "JSON child": (SESSION_CREATE_CHILD, lambda t, h: t.json_child(h), BOB),
    "bundle child": (SESSION_CREATE_CHILD, lambda t, h: t.bundle_child(h), BOB),
    "agent replace": (SESSION_AGENT_REPLACE, lambda t, h: t.replace_agent(h), BOB),
    "MCP server": (SESSION_MCP_CHANGE, lambda t, h: t.add_mcp_server(h), BOB),
    "task create": (SESSION_SCHEDULE, lambda t, h: t.schedule(h), BOB),
    "task patch": (SESSION_SCHEDULE, lambda t, h: t.reschedule(h), BOB),
    "agent patch": (AGENT_UPDATE, lambda t, h: t.patch_agent(h), BOB),
    "agent delete": (AGENT_REMOVE, lambda t, h: t.delete_agent(h), BOB),
    # Anyone signed in may install an agent, so only an anonymous caller is refused.
    "agent install": (AGENT_INSTALL, lambda t, h: t.install_agent(h), NOBODY),
    "bundle create": (AGENT_INSTALL, lambda t, h: t.bundle_create(h), NOBODY),
    "sibling create": (SESSION_CREATE_CHILD, lambda t, h: t.sibling(h), BOB),
    "agent title": (SESSION_UPDATE, lambda t, h: t.retitle(h, "agent-title"), BOB),
    "auto title": (SESSION_UPDATE, lambda t, h: t.retitle(h, "auto-title"), BOB),
    "approval resolve": (SESSION_EVENT, lambda t, h: t.resolve_approval(h), BOB),
    "transcript batch": (SESSION_EVENT, lambda t, h: t.post_transcript(h), BOB),
}


@dataclass
class _Guard:
    """A guard whose answers the test sets; it records what it was asked."""

    answer: Callable[[MutationAttempt], Screen | str] = lambda _attempt: Screen.ALLOW
    refusal: str | None = None
    error: Exception | None = None
    screened: list[MutationAttempt] = field(default_factory=list)
    checked: list[tuple[MutationAttempt, int, int]] = field(default_factory=list)

    def screen(self, attempt: MutationAttempt) -> Screen | str:
        self.screened.append(attempt)
        return self.answer(attempt)

    def check(self, attempt: MutationAttempt) -> str | None:
        self.checked.append((attempt, threading.get_ident(), current_workspace_id()))
        if self.error is not None:
            raise self.error
        return self.refusal


@dataclass
class _RefuseAll:
    """Refuses every attempt, after loading the session row when the route did not pass it."""

    refused: list[MutationAttempt] = field(default_factory=list)

    def screen(self, attempt: MutationAttempt) -> Screen | str:
        if attempt.session_id is not None and attempt.conversation is None:
            return Screen.NEEDS_ROW
        self.refused.append(attempt)
        return REFUSAL

    def check(self, attempt: MutationAttempt) -> str | None:
        raise AssertionError(f"no check expected for {attempt.action}")


@pytest.fixture
def register() -> Iterator[Callable[[str, MutationGuard], Callable[[], None]]]:
    """Register mutation guards for one test and unregister them afterwards."""
    unregisters: list[Callable[[], None]] = []

    def _register(name: str, guard: MutationGuard) -> Callable[[], None]:
        unregister = register_mutation_guard(name, guard)
        unregisters.append(unregister)
        return unregister

    yield _register
    for unregister in unregisters:
        unregister()


def record_check_hops(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record the worker thread of each hop ``check_mutation`` makes to run checks."""
    threads: list[int] = []
    run_checks = mutation_guards._run_checks

    def recording(*args: Any) -> str | None:
        threads.append(threading.get_ident())
        return run_checks(*args)

    monkeypatch.setattr(mutation_guards, "_run_checks", recording)
    return threads


@pytest.fixture
def hops(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    return record_check_hops(monkeypatch)


def _loader(
    row: Conversation | None, loads: list[int]
) -> Callable[[], Awaitable[Conversation | None]]:
    async def load() -> Conversation | None:
        loads.append(1)
        return row

    return load


async def test_no_guard_is_a_no_op(hops: list[int]) -> None:
    loads: list[int] = []
    await check_mutation(
        MutationAttempt(SESSION_UPDATE, session_id=_ROW.id, fields=frozenset({"model_override"})),
        load_conversation=_loader(_ROW, loads),
    )
    assert loads == [] and hops == []


async def test_no_thread_hop_without_a_check(register, hops: list[int]) -> None:
    allowing = _Guard()
    register("a.allow", allowing)
    await check_mutation(MutationAttempt(SESSION_EVENT, session_id=_ROW.id, conversation=_ROW))

    refusing = _Guard(answer=lambda _attempt: "not here")
    later = _Guard(answer=lambda _attempt: Screen.CHECK)
    register("b.refuse", refusing)
    register("c.check", later)
    with pytest.raises(OmnigentError) as refused:
        await check_mutation(MutationAttempt(AGENT_UPDATE, agent_name="x"))

    assert refused.value.code == ErrorCode.CONFLICT and refused.value.message == "not here"
    assert refused.value.http_status == 409
    assert hops == [] and later.checked == [] and later.screened == []
    assert len(allowing.screened) == 2


async def test_needs_row_loads_it_once_and_screens_again(register, hops: list[int]) -> None:
    def needs_row_then(after: Screen | str) -> Callable[[MutationAttempt], Screen | str]:
        return lambda attempt: Screen.NEEDS_ROW if attempt.conversation is None else after

    allowing = _Guard(answer=needs_row_then(Screen.ALLOW))
    checking = _Guard(answer=needs_row_then(Screen.CHECK), refusal="no model changes")
    register("a.allow", allowing)
    register("b.check", checking)
    loads: list[int] = []
    attempt = MutationAttempt(SESSION_UPDATE, session_id=_ROW.id, fields=frozenset({"x"}))

    with pytest.raises(OmnigentError) as refused:
        await check_mutation(attempt, load_conversation=_loader(_ROW, loads))

    assert refused.value.code == ErrorCode.CONFLICT and refused.value.message == "no model changes"
    assert loads == [1] and len(hops) == 1
    assert [a.conversation for a in allowing.screened] == [None, _ROW]
    assert [a.conversation for a, _, _ in checking.checked] == [_ROW]

    # A row that no longer exists allows: the route answers 404 itself.
    gone: list[int] = []
    await check_mutation(attempt, load_conversation=_loader(None, gone))
    assert gone == [1] and len(hops) == 1 and len(checking.checked) == 1


async def test_a_guard_asking_for_a_row_nobody_can_give_is_a_call_site_bug(register) -> None:
    register("a.row", _Guard(answer=lambda _attempt: Screen.NEEDS_ROW))
    with pytest.raises(ValueError, match="row"):
        await check_mutation(MutationAttempt(SESSION_GRANT, session_id=_ROW.id))


async def test_checks_run_together_in_one_worker_thread(register, hops: list[int]) -> None:
    first = _Guard(answer=lambda _attempt: Screen.CHECK)
    second = _Guard(answer=lambda _attempt: Screen.CHECK, refusal="second says no")
    third = _Guard(answer=lambda _attempt: Screen.CHECK, refusal="never asked")
    for name, guard in (("a", first), ("b", second), ("c", third)):
        register(name, guard)
    attempt = MutationAttempt(SESSION_EVENT, session_id=_ROW.id, conversation=_ROW)

    with workspace_scope(5), pytest.raises(OmnigentError) as refused:
        await check_mutation(attempt)

    assert refused.value.message == "second says no"
    assert len(hops) == 1 and hops[0] != threading.get_ident()
    assert [(thread, workspace) for _, thread, workspace in first.checked + second.checked] == [
        (hops[0], 5),
        (hops[0], 5),
    ]
    assert third.checked == []


async def test_guard_errors_propagate_and_other_failures_are_a_retryable_500(
    register, caplog: pytest.LogCaptureFixture
) -> None:
    guard = _Guard(answer=lambda _attempt: Screen.CHECK)
    register("a.broken", guard)
    attempt = MutationAttempt(SESSION_EVENT, session_id=_ROW.id, conversation=_ROW)

    guard.error = OmnigentError("store says no", code=ErrorCode.FORBIDDEN)
    with pytest.raises(OmnigentError) as own:
        await check_mutation(attempt)
    assert own.value.code == ErrorCode.FORBIDDEN

    guard.error = RuntimeError("boom")
    with caplog.at_level(logging.ERROR, logger=mutation_guards.__name__):
        with pytest.raises(OmnigentError) as failed:
            await check_mutation(attempt)
    assert failed.value.code == ErrorCode.INTERNAL_ERROR and failed.value.http_status == 500
    assert "retry" in failed.value.message and "boom" not in failed.value.message
    [record] = [r for r in caplog.records if r.name == mutation_guards.__name__]
    assert record.exc_info is not None and record.session_id == _ROW.id  # type: ignore[attr-defined]


def test_registration_is_by_name_and_unregister_removes_only_its_own(
    caplog: pytest.LogCaptureFixture,
) -> None:
    for bad in ("", "-x", "has space", "x" * 65):
        with pytest.raises(ValueError):
            register_mutation_guard(bad, _Guard())
    with pytest.raises(TypeError):
        register_mutation_guard("no.methods", object())  # type: ignore[arg-type]

    old, new = _Guard(), _Guard()
    unregister_old = register_mutation_guard("same", old)
    with caplog.at_level(logging.WARNING, logger=mutation_guards.__name__):
        unregister_new = register_mutation_guard("same", new)
    assert "replaced" in caplog.text
    unregister_old()
    assert mutation_guards._registered() == [("same", new)]
    unregister_new()
    unregister_new()
    assert mutation_guards._registered() == []


@pytest.mark.usefixtures("frozen_recurrence_clock")
async def test_guard_runs_after_authorization(db_uri: str, tmp_path: Path, register) -> None:
    """Each guarded route asks only an authorized caller, with the action and row it acts on."""
    app = guarded_app(db_uri, tmp_path)
    app.state.feature_flags = resolve_feature_flags({"OMNIGENT_FEATURES": "sibling_sessions"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        targets = await mutation_targets(app, client, db_uri)
        guard = _RefuseAll()
        register("refuse.all", guard)

        for name, (action, send, stranger) in GUARDED_REQUESTS.items():
            outsider = await send(targets, stranger)
            assert outsider.status_code in (401, 403, 404), (name, outsider.text)
            assert guard.refused == [], name

            owner = await send(targets, ALICE)
            assert owner.status_code == 409, (name, owner.text)
            assert owner.json()["error"]["message"] == REFUSAL
            [attempt] = guard.refused
            guard.refused.clear()
            assert attempt.action == action, name
            if attempt.session_id is not None:
                assert attempt.conversation is not None, name
                assert attempt.conversation.id == attempt.session_id, name

        tasks = (await client.get("/v1/scheduled-tasks", headers=ALICE)).json()["scheduled_tasks"]
        installed = await client.get("/v1/agents", params={"scope": "user"}, headers=ALICE)

    children = targets.conversations.list_conversations(
        limit=10, kind=None, parent_conversation_id=targets.session_id
    )
    assert children.data == []
    assert [task["session_id"] for task in tasks] == [None]
    assert sorted(agent["name"] for agent in installed.json()["data"]) == ["orion", "test-agent"]


@pytest.mark.usefixtures("frozen_recurrence_clock")
async def test_attempts_carry_what_each_route_changes(
    db_uri: str, tmp_path: Path, register
) -> None:
    """Fields, label keys, title, event type, runner proof, agent name and force arrive as sent."""
    app = guarded_app(db_uri, tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        targets = await mutation_targets(app, client, db_uri)
        targets.conversations.set_runner_id(targets.session_id, token_bound_runner_id(_TOKEN))
        guard = _RefuseAll()
        register("refuse.all", guard)
        await targets.patch(
            {"title": "t", "labels": {"omnigent.closed": "false", "a": "b"}}, ALICE
        )
        await targets.event("slash_command", ALICE)
        await targets.event("external_session_status", {**ALICE, **_RUNNER})
        await targets.post_transcript({**ALICE, **_RUNNER})
        another_runner = {RUNNER_TUNNEL_TOKEN_HEADER: "another-runner-token"}
        await targets.event("external_session_status", {**ALICE, **another_runner})
        await targets.retitle(ALICE, "agent-title", title="Work:closed:x")
        await targets.delete_agent(ALICE, force=True)
        await targets.install_agent(ALICE, name="coral__x")
        await targets.bundle_create(ALICE, name="coral__y")

    update, event, runner, batch, impostor, title, remove, install, bundle = guard.refused
    assert update.fields == frozenset({"title", "labels"})
    assert update.label_keys == frozenset({"omnigent.closed", "a"})
    assert update.title == "t"
    assert (event.event_type, event.runner_proven) == ("slash_command", False)
    assert (runner.event_type, runner.runner_proven) == ("external_session_status", True)
    assert (batch.event_type, batch.runner_proven) == ("external_conversation_item", True)
    assert (impostor.event_type, impostor.runner_proven) == ("external_session_status", False)
    assert (title.fields, title.title) == (frozenset({"title"}), "Work:closed:x")
    assert (remove.agent_name, remove.forced) == ("orion", True)
    assert (install.agent_name, install.forced) == ("coral__x", False)
    assert (bundle.action, bundle.agent_name) == (AGENT_INSTALL, "coral__y")
