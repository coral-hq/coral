"""Coral's mutation guard over HTTP: run sessions refuse client changes; others never wait on it.

Tier A: the real app with every optional store, the MCP registry and the Coral
plugin; alice's sessions, host, task and agent from
``tests/server/test_mutation_guards.py``; a stub runner that records what is
forwarded; Coral's guard over a fake binding lookup. A session is bound the way
the engine binds one: a ``coral.run_id`` label written through the store, and a
binding row.
"""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, WebSocket
from fastapi.routing import APIRoute, APIWebSocketRoute

from coral.db.enum_codecs import SessionBindingRole, SlotRole
from coral.omni._upstream import CLIENT_SESSION_EVENT_TYPES
from coral.omni.server.gates import GateAnswering
from coral.omni.server.mutation_guard import MUTATION_GUARD, STOP_EVENTS, CoralMutationGuard
from coral.omni.server.sessions import RUN_ID_LABEL_KEY
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID
from omnigent.entities import Conversation
from omnigent.runner.identity import (
    OMNIGENT_INTERNAL_WS_ORIGIN,
    ORCHESTRATION_SOURCE_HEADER,
    RUNNER_TUNNEL_TOKEN_HEADER,
    token_bound_runner_id,
)
from omnigent.server.auth import LEVEL_READ, RESERVED_USER_PUBLIC
from omnigent.server.elicitation_hooks import (
    ElicitationVerdict,
    VerdictDecision,
    register_elicitation_verdict_handler,
)
from omnigent.server.feature_flags import resolve_feature_flags
from omnigent.server.mutation_guards import (
    ACTIONS,
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
    register_mutation_guard,
)
from omnigent.server.schemas import SessionEventInput
from omnigent.server.startup_inputs import EngineEventContext
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE
from tests.coral.tools.fake_decision_port import FakeBindingLookup, step_binding
from tests.server.conftest import ControllableMockClient, _app_client
from tests.server.integration.test_engine_event_dispatch import _brief
from tests.server.integration.test_scheduled_tasks_routes import _owned_session
from tests.server.integration.test_sessions_web_send_stable_id import _stub_runner
from tests.server.test_mutation_guards import (
    ALICE,
    BOB,
    MutationTargets,
    guarded_app,
    mutation_targets,
    record_check_hops,
)

pytestmark = pytest.mark.usefixtures("frozen_recurrence_clock")

CORAL_PLUGIN = {"server_plugins": ["coral.server_plugin"]}
RUN_ID = "run-1"
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_RUNNER_TYPES = frozenset({"message", "interrupt", "stop_session"})
# Residuals are listed in docs/coral/contracts/session-facade.md, "Run protection".
_WORKSPACE = "workspace routes are a recorded residual"
_RESIDUAL = f"allowed: {_WORKSPACE}"
_HARNESS_HOOK = "allowed: a harness hook asking the session's user; policy decides first"
_COMMENTS = "allowed: review comments on the transcript; sending only formats text"
_GITHUB = "allowed: acts on the session's pull request, not on the session"
_BROWSER = "allowed: the runner's browser tool relay; its tool calls are policed"
_CODEX_GOAL = (
    "allowed: only for sessions labelled omnigent.wrapper=codex-native-ui, a label clients "
    "cannot write to a run session"
)
_POLICIES = "allowed: session policies stay editable, a recorded residual"
# Every mutating route in scope: the action it asks the guards about, or why it does not.
ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/v1/agents"): AGENT_INSTALL,
    ("PATCH", "/v1/agents/{agent_id}"): AGENT_UPDATE,
    ("DELETE", "/v1/agents/{agent_id}"): AGENT_REMOVE,
    ("POST", "/v1/hosts/{host_id}/runners"): SESSION_LAUNCH_RUNNER,
    (
        "POST",
        "/v1/mcp/{service_id}",
    ): "allowed: the MCP registry gateway; policy decides its calls",
    ("POST", "/v1/scheduled-tasks"): SESSION_SCHEDULE,
    ("PATCH", "/v1/scheduled-tasks/{scheduled_task_id}"): SESSION_SCHEDULE,
    ("DELETE", "/v1/scheduled-tasks/{scheduled_task_id}"): "allowed: touches no session",
    ("POST", "/v1/scheduled-tasks/{scheduled_task_id}/run"): (
        "allowed: fires a task whose session was checked at create and PATCH; "
        "a firing-time check is a recorded residual"
    ),
    ("POST", "/v1/sessions"): SESSION_CREATE_CHILD,
    ("POST", "/v1/sessions/orchestrated"): SESSION_CREATE_CHILD,
    ("PATCH", "/v1/sessions/{session_id}"): SESSION_UPDATE,
    ("DELETE", "/v1/sessions/{session_id}"): "allowed: a user action; the run pauses on drift",
    ("PUT", "/v1/sessions/{session_id}/agent"): SESSION_AGENT_REPLACE,
    ("POST", "/v1/sessions/{session_id}/agent-title"): SESSION_UPDATE,
    ("POST", "/v1/sessions/{session_id}/agent/mcp-servers"): SESSION_MCP_CHANGE,
    ("PUT", "/v1/sessions/{session_id}/agent/mcp-servers/{server_name}"): SESSION_MCP_CHANGE,
    ("DELETE", "/v1/sessions/{session_id}/agent/mcp-servers/{server_name}"): SESSION_MCP_CHANGE,
    ("POST", "/v1/sessions/{session_id}/auto-title"): SESSION_UPDATE,
    ("POST", "/v1/sessions/{session_id}/browser/action_claim/{action_id}"): _BROWSER,
    ("POST", "/v1/sessions/{session_id}/browser/action_request"): _BROWSER,
    ("POST", "/v1/sessions/{session_id}/browser/action_result/{action_id}"): _BROWSER,
    ("DELETE", "/v1/sessions/{session_id}/codex_goal"): _CODEX_GOAL,
    ("PUT", "/v1/sessions/{session_id}/codex_goal"): _CODEX_GOAL,
    ("PATCH", "/v1/sessions/{session_id}/codex_goal/status"): _CODEX_GOAL,
    ("POST", "/v1/sessions/{session_id}/comments"): _COMMENTS,
    ("POST", "/v1/sessions/{session_id}/comments/send"): _COMMENTS,
    ("DELETE", "/v1/sessions/{session_id}/comments/{comment_id}"): _COMMENTS,
    ("PATCH", "/v1/sessions/{session_id}/comments/{comment_id}"): _COMMENTS,
    ("POST", "/v1/sessions/{session_id}/elicitations/{elicitation_id}/resolve"): SESSION_EVENT,
    ("POST", "/v1/sessions/{session_id}/events"): SESSION_EVENT,
    ("POST", "/v1/sessions/{session_id}/hooks/antigravity-elicitation-request"): _HARNESS_HOOK,
    ("POST", "/v1/sessions/{session_id}/hooks/codex-elicitation-request"): _HARNESS_HOOK,
    ("POST", "/v1/sessions/{session_id}/hooks/cursor-permission-request"): _HARNESS_HOOK,
    ("POST", "/v1/sessions/{session_id}/hooks/native-permission-request"): _HARNESS_HOOK,
    ("POST", "/v1/sessions/{session_id}/hooks/permission-request"): _HARNESS_HOOK,
    ("POST", "/v1/sessions/{session_id}/hooks/pi-extension-ui"): _HARNESS_HOOK,
    ("POST", "/v1/sessions/{session_id}/hooks/route-subagent"): (
        "allowed: routes only when subagent_routing_override is on, which run sessions never "
        "have and PATCH cannot set"
    ),
    ("POST", "/v1/sessions/{session_id}/hooks/route-turn"): (
        "allowed: pins a model only when cost_control_mode_override (the session's or its "
        "parent's) turns routing on, which run sessions never have and PATCH cannot set"
    ),
    ("POST", "/v1/sessions/{session_id}/mcp"): "allowed: the runner's MCP proxy; policy decides",
    ("POST", "/v1/sessions/{session_id}/model-override/reset"): (
        "allowed: clears model_override only when it equals the caller's value; run "
        "sessions have none and PATCH cannot set one"
    ),
    ("PUT", "/v1/sessions/{session_id}/permissions"): SESSION_GRANT,
    ("DELETE", "/v1/sessions/{session_id}/permissions/{target_user_id}"): (
        "allowed: revoking access narrows who sees the run"
    ),
    ("POST", "/v1/sessions/{session_id}/policies"): _POLICIES,
    ("POST", "/v1/sessions/{session_id}/policies/evaluate"): "allowed: evaluates; writes nothing",
    ("DELETE", "/v1/sessions/{session_id}/policies/{policy_id}"): _POLICIES,
    ("PATCH", "/v1/sessions/{session_id}/policies/{policy_id}"): _POLICIES,
    ("DELETE", "/v1/sessions/{session_id}/pull-requests"): "allowed: unlinks a display record",
    ("PUT", "/v1/sessions/{session_id}/read-state"): "allowed: the caller's own read marker",
    (
        "DELETE",
        "/v1/sessions/{session_id}/resources/environments/{environment_id}/filesystem/"
        "{relative_path:path}",
    ): _RESIDUAL,
    (
        "PATCH",
        "/v1/sessions/{session_id}/resources/environments/{environment_id}/filesystem/"
        "{relative_path:path}",
    ): _RESIDUAL,
    (
        "PUT",
        "/v1/sessions/{session_id}/resources/environments/{environment_id}/filesystem/"
        "{relative_path:path}",
    ): _RESIDUAL,
    ("POST", "/v1/sessions/{session_id}/resources/environments/{environment_id}/shell"): (
        _RESIDUAL
    ),
    ("POST", "/v1/sessions/{session_id}/resources/files"): _RESIDUAL,
    ("DELETE", "/v1/sessions/{session_id}/resources/files/{file_id}"): _RESIDUAL,
    ("POST", "/v1/sessions/{session_id}/resources/files:copy"): _RESIDUAL,
    ("POST", "/v1/sessions/{session_id}/resources/github/attachments"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/github/comments"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/github/details"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/github/disable-auto-merge"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/github/labels"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/github/merge"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/github/preferences"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/github/prs"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/github/review-threads"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/github/review-threads/{thread_id}/replies"): (
        _GITHUB
    ),
    ("POST", "/v1/sessions/{session_id}/resources/github/reviewers"): _GITHUB,
    ("POST", "/v1/sessions/{session_id}/resources/terminals"): _RESIDUAL,
    ("DELETE", "/v1/sessions/{session_id}/resources/terminals/{terminal_id}"): _RESIDUAL,
    ("POST", "/v1/sessions/{session_id}/resources/terminals/{terminal_id}/transfer"): _RESIDUAL,
    ("POST", "/v1/sessions/{session_id}/switch-agent"): "allowed: always answers 410",
    ("POST", "/v1/sessions/{session_id}/ui/open-file"): "allowed: opens a file in the viewer",
    ("POST", "/v1/sessions/{source_id}/fork"): (
        "allowed: a fork is a plain session (no coral.*); a side chat also uses the step's "
        "runner and workspace outside the run's policies, a recorded residual"
    ),
}
WEBSOCKETS: dict[str, str] = {
    "/v1/sessions/updates": "streams session updates; changes nothing",
    "/v1/dictation/stream": "speech to text for the composer; touches no session",
    "/v1/sessions/{session_id}/resources/terminals/{terminal_id}/attach": _WORKSPACE,
    "/v1/runners/{runner_id}/tunnel": (
        "events from the session's own runner (checked against its runner_id); never asked"
    ),
    "/v1/hosts/{host_id}/tunnel": "host frames are server-internal",
}
# One path from each router that create_app mounts only when its store or registry is given.
CONDITIONAL_PATHS = frozenset(
    {
        "/v1/sessions/{session_id}/comments",
        "/v1/sessions/{session_id}/policies",
        "/v1/scheduled-tasks",
        "/v1/projects",
        "/v1/preferences/configuration",
        "/v1/mcp-registry/services",
        "/v1/mcp/{service_id}",
        "/v1/hosts/{host_id}/runners",
        "/v1/coral/info",
    }
)


def _in_scope(path: str) -> bool:
    """Routes that can name a session or an agent: every one under ``/v1/sessions`` and more."""
    return (
        "{session_id}" in path
        or "{source_id}" in path
        or path in ("/v1/sessions", "/v1/agents", "/v1/scheduled-tasks")
        or path == "/v1/hosts/{host_id}/runners"
        or path.startswith(
            ("/v1/sessions/", "/v1/sessions:", "/v1/agents/", "/v1/scheduled-tasks/", "/v1/mcp/")
        )
    )


@dataclass
class _Run:
    """
    Alice's targets, a run's bindings in a fake lookup, and what the stub runner received.

    ``answering`` is the guard's gate-handler flag, off unless a test turns it on.
    """

    targets: MutationTargets
    lookup: FakeBindingLookup
    forwarded: list[dict[str, Any]]
    db_uri: str
    app: FastAPI
    answering: GateAnswering

    def bind(self, session_id: str, kind: str = "step") -> None:
        """Bind *session_id* to the run as ``step``, ``closed step`` or ``anchor``."""
        labels = {RUN_ID_LABEL_KEY: RUN_ID}
        if kind == "closed step":
            labels[CLOSED_LABEL_KEY] = CLOSED_LABEL_VALUE
        self.targets.conversations.set_labels(session_id, labels)
        anchor = kind == "anchor"
        self.lookup.add(
            step_binding(
                None if anchor else "work||:0",
                session_id=session_id,
                run_id=RUN_ID,
                workspace_id=DEFAULT_WORKSPACE_ID,
                role=SessionBindingRole.ANCHOR if anchor else SessionBindingRole.STEP,
                slot_role=None if anchor else SlotRole.STEP_AGENT,
            )
        )

    def row(self, session_id: str | None = None) -> Conversation:
        row = self.targets.conversations.get_conversation(session_id or self.targets.session_id)
        assert row is not None
        return row

    def forwarded_types(self) -> list[str]:
        """The turns and stops the runner received, in order."""
        return [body["type"] for body in self.forwarded if body.get("type") in _RUNNER_TYPES]

    def runner(self, session_id: str) -> dict[str, str]:
        """Alice's headers as the session's own runner: its row now names the token's runner."""
        token = f"runner-token-{session_id}"
        self.targets.conversations.set_runner_id(session_id, token_bound_runner_id(token))
        return {**ALICE, RUNNER_TUNNEL_TOKEN_HEADER: token}


@pytest_asyncio.fixture
async def run(db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_Run]:
    app = guarded_app(db_uri, tmp_path, **CORAL_PLUGIN)
    forwarded: list[dict[str, Any]] = []
    runner = _stub_runner(monkeypatch, forwarded)
    lookup = FakeBindingLookup()
    try:
        async with _app_client(app, ControllableMockClient(), tmp_path) as client:
            client.headers["origin"] = OMNIGENT_INTERNAL_WS_ORIGIN
            targets = await mutation_targets(app, client, db_uri)
            answering = GateAnswering()
            unregister = register_mutation_guard(
                MUTATION_GUARD, CoralMutationGuard(lookup, gate_answering=answering)
            )
            try:
                yield _Run(targets, lookup, forwarded, db_uri, app, answering)
            finally:
                unregister()
    finally:
        await runner.aclose()


# PATCH bodies a run session refuses: each protected field, and lifecycle labels in any value.
REFUSED_PATCHES: list[dict[str, Any]] = [
    {"runner_id": "runner-x"},
    {"model_override": "test-model"},
    {"reasoning_effort": "high"},
    {"collaboration_mode": "plan"},
    {"permission_mode": "default"},
    {"approval_mode": "never"},
    {"cost_control_mode_override": "on"},
    {"subagent_routing_override": "on"},
    {"external_session_id": "ext-1"},
    {"terminal_launch_args": ["--verbose"]},
    {"project_id": ""},
    {"share_workspace_files": True},
    {"share_workspace_files": False},
    {"labels": {CLOSED_LABEL_KEY: "false"}},
    {"labels": {CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE}},
    {"labels": {"Omnigent.Closed": "false"}},
    {"labels": {"omnigent.parent_wake": "on"}},
    {"title": "renamed", "model_override": "test-model"},
]


def _assert_refused(response: httpx.Response, session_id: str) -> None:
    assert response.status_code == 409, response.text
    message = response.json()["error"]["message"]
    assert message.startswith(f"Session {session_id} is part of a Coral workflow run, so "), (
        message
    )
    assert message.endswith("You can rename, archive, delete, fork or stop it.")


def _items(run: _Run, session_id: str) -> list[str]:
    return [item.type for item in run.targets.conversations.list_items(session_id).data]


async def test_protection_matrix_over_http(run: _Run) -> None:
    t, client = run.targets, run.targets.client
    session = t.session_id
    run.bind(session)
    run.bind(t.scheduled_session_id)
    before = run.row()

    outsider = await t.patch({"model_override": "test-model"}, BOB)
    assert outsider.status_code in (403, 404) and run.lookup.reads == []

    for body in REFUSED_PATCHES:
        _assert_refused(await t.patch(body, ALICE), session)
    assert run.row() == before

    servers = f"/v1/sessions/{session}/agent/mcp-servers"
    stdio = {"name": "notes", "transport": "stdio", "command": "echo"}
    refused: list[Callable[[], Awaitable[httpx.Response]]] = [
        lambda: t.launch(ALICE),
        lambda: t.grant(ALICE),
        lambda: t.grant(ALICE, user=RESERVED_USER_PUBLIC),
        lambda: t.json_child(ALICE),
        lambda: t.bundle_child(ALICE),
        lambda: t.replace_agent(ALICE),
        lambda: t.add_mcp_server(ALICE),
        lambda: client.put(f"{servers}/notes", json=stdio, headers=ALICE),
        lambda: client.delete(f"{servers}/notes", headers=ALICE),
        lambda: client.post(
            servers, json={"name": "tracker", "transport": "registry"}, headers=ALICE
        ),
    ]
    for send in refused:
        _assert_refused(await send(), session)
    _assert_refused(await t.schedule(ALICE), t.scheduled_session_id)
    _assert_refused(await t.reschedule(ALICE), t.scheduled_session_id)

    assert run.row() == before
    children = t.conversations.list_conversations(
        limit=10, kind=None, parent_conversation_id=session
    )
    assert children.data == []
    grants = (await client.get(f"/v1/sessions/{session}/permissions", headers=ALICE)).json()
    assert [grant["user_id"] for grant in grants["permissions"]] == ["alice@example.com"]
    assert run.forwarded_types() == []

    # What a user may still do to a run session.
    renamed = await t.patch({"title": "renamed"}, ALICE)
    pinned = await t.patch({"labels": {"omnigent.pinned": "true", "team": "ml"}}, ALICE)
    seen = await client.put(
        f"/v1/sessions/{session}/read-state", json={"last_seen": 1, "unread": False}, headers=ALICE
    )
    revoked = await client.delete(
        f"/v1/sessions/{session}/permissions/carol@example.com", headers=ALICE
    )
    fork = await client.post(f"/v1/sessions/{session}/fork", json={}, headers=ALICE)
    archived = await t.patch({"archived": True}, ALICE)
    deleted = await client.delete(f"/v1/sessions/{t.scheduled_session_id}", headers=ALICE)
    assert [renamed.status_code, pinned.status_code, archived.status_code] == [200] * 3
    assert [seen.status_code, revoked.status_code] == [204, 204]
    assert fork.status_code == 201, fork.text
    assert deleted.status_code in (200, 204), deleted.text
    after = run.row()
    assert (after.title, after.archived, after.labels[RUN_ID_LABEL_KEY]) == (
        "renamed",
        True,
        RUN_ID,
    )
    assert after.labels["team"] == "ml"
    assert RUN_ID_LABEL_KEY not in run.row(fork.json()["id"]).labels


async def test_closed_step_and_anchor_events_follow_the_allowlist(run: _Run) -> None:
    t = run.targets
    closed, anchor = t.session_id, t.scheduled_session_id
    run.bind(closed, "closed step")
    run.bind(anchor, "anchor")
    # Items such as reasoning or function_call would start or relaunch a runner too.
    refused_types = sorted((CLIENT_SESSION_EVENT_TYPES | {"session_message"}) - STOP_EVENTS)
    assert {"reasoning", "function_call", "error", "retry_session", "compact"} <= set(
        refused_types
    )

    for session_id in (closed, anchor):
        for event_type in refused_types:
            _assert_refused(await t.event(event_type, ALICE, session_id=session_id), session_id)
        assert _items(run, session_id) == []
    assert run.forwarded_types() == []

    for session_id in (closed, anchor):
        _assert_refused(await t.resolve_approval(ALICE, session_id=session_id), session_id)
        for event_type in sorted(STOP_EVENTS):
            stopped = await t.event(event_type, ALICE, session_id=session_id)
            assert stopped.status_code < 400, (event_type, stopped.text)
    assert run.forwarded_types() == ["interrupt", "stop_session"] * 2
    for session_id in (closed, anchor):
        status = {"type": "external_session_status", "data": {"status": "idle"}}
        url = f"/v1/sessions/{session_id}/events"
        _assert_refused(await t.client.post(url, json=status, headers=ALICE), session_id)
        observed = await t.client.post(url, json=status, headers=run.runner(session_id))
        assert observed.status_code < 400, observed.text


async def test_the_anchor_takes_gate_answers_only_while_the_gate_handler_is_registered(
    run: _Run,
) -> None:
    """Both answer routes reach the handler on the anchor once admitted; a closed step never."""
    t = run.targets
    closed, anchor = t.session_id, t.scheduled_session_id
    run.bind(closed, "closed step")
    run.bind(anchor, "anchor")
    prompt = "coral_gate_" + "a" * 32
    verdicts: list[ElicitationVerdict] = []

    async def handler(verdict: ElicitationVerdict) -> VerdictDecision:
        verdicts.append(verdict)
        return VerdictDecision(accepted=True)

    def resolve(session_id: str) -> Awaitable[httpx.Response]:
        return t.client.post(
            f"/v1/sessions/{session_id}/elicitations/{prompt}/resolve",
            json={"action": "accept", "content": {"decision": "approve"}},
            headers=ALICE,
        )

    def approval(session_id: str) -> Awaitable[httpx.Response]:
        data = {"elicitation_id": prompt, "action": "accept"}
        return t.client.post(
            f"/v1/sessions/{session_id}/events",
            json={"type": "approval", "data": data},
            headers=ALICE,
        )

    unregister = register_elicitation_verdict_handler("coral_gate_", handler)
    try:
        # The handler alone does not open the anchor: the flag does, once it is registered.
        for send in (resolve, approval):
            _assert_refused(await send(anchor), anchor)
        run.answering.enable()
        for send in (resolve, approval):
            answered = await send(anchor)
            assert answered.status_code == 202, answered.text
            _assert_refused(await send(closed), closed)
        run.answering.disable()
        for send in (resolve, approval):
            _assert_refused(await send(anchor), anchor)
    finally:
        run.answering.disable()
        unregister()

    assert [(item.session_id, item.elicitation_id, item.resolved_by) for item in verdicts] == [
        (anchor, prompt, "alice@example.com")
    ] * 2
    assert run.forwarded_types() == []


async def test_peer_session_message_into_a_bound_session_is_refused(run: _Run) -> None:
    """Other agents cannot steer an open step; its user still can."""
    t = run.targets
    run.bind(t.session_id)
    peer = {**ALICE, ORCHESTRATION_SOURCE_HEADER: t.scheduled_session_id}

    _assert_refused(await t.event("session_message", peer), t.session_id)
    _assert_refused(await t.event("clear", ALICE), t.session_id)
    assert run.forwarded_types() == []

    message = await t.event("message", ALICE)
    assert message.status_code == 202, message.text
    assert run.forwarded_types() == ["message"]

    # The same peer message to an ordinary session gets Omnigent's own answer.
    unbound = await t.event("session_message", peer, session_id=t.scheduled_session_id)
    assert "Coral workflow run" not in unbound.text


async def test_scheduled_task_cannot_continue_a_bound_session(run: _Run) -> None:
    """The anchor is a root session a task could continue; no bound session can be one."""
    t = run.targets
    run.bind(t.scheduled_session_id, "anchor")

    _assert_refused(await t.schedule(ALICE), t.scheduled_session_id)
    _assert_refused(await t.reschedule(ALICE), t.scheduled_session_id)
    tasks = (await t.client.get("/v1/scheduled-tasks", headers=ALICE)).json()["scheduled_tasks"]
    assert [task["session_id"] for task in tasks] == [None]

    ordinary = _owned_session(run.db_uri)
    created = await t.schedule(ALICE, session_id=ordinary)
    assert created.status_code == 200, created.text
    assert created.json()["session_id"] == ordinary


async def test_coral_store_failure_never_affects_an_unlabelled_session(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = run.targets
    run.lookup.error = RuntimeError("bindings table locked")
    hops = record_check_hops(monkeypatch)

    message = await t.event("message", ALICE)
    child = await t.json_child(ALICE)
    model = await t.patch({"model_override": "test-model"}, ALICE)
    grant = await t.grant(ALICE)
    task = await t.schedule(ALICE)
    assert message.status_code == 202, message.text
    assert child.status_code == 201, child.text
    assert [model.status_code, grant.status_code, task.status_code] == [200] * 3, (
        model.text,
        grant.text,
        task.text,
    )
    assert run.lookup.reads == [] and hops == []

    # A labelled session whose binding cannot be read refuses only what a rule could refuse.
    t.conversations.set_labels(t.session_id, {RUN_ID_LABEL_KEY: RUN_ID})
    failed = await t.patch({"model_override": "other-model"}, ALICE)
    assert failed.status_code == 500, failed.text
    assert "retry" in failed.json()["error"]["message"]
    assert len(hops) == 1
    for body in ({"title": "kept"}, {"labels": {"omnigent.pinned": "true"}}, {"archived": True}):
        response = await t.patch(body, ALICE)
        assert response.status_code == 200, (body, response.text)
    assert len(hops) == 1 and run.lookup.reads == [(DEFAULT_WORKSPACE_ID, t.session_id)]


def test_every_mutating_route_is_classified(db_uri: str, tmp_path: Path) -> None:
    """A new upstream route that could change a session or an agent fails here until classified."""
    app = guarded_app(db_uri, tmp_path, **CORAL_PLUGIN)
    paths = {getattr(route, "path", None) for route in app.routes}
    assert paths >= CONDITIONAL_PATHS, sorted(CONDITIONAL_PATHS - paths)

    found = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and _in_scope(route.path)
        for method in route.methods & MUTATING
    }
    assert sorted(found - ROUTES.keys()) == [], "classify these routes in ROUTES"
    assert sorted(ROUTES.keys() - found) == [], "these classified routes no longer exist"
    sockets = {route.path for route in app.routes if isinstance(route, APIWebSocketRoute)}
    assert sorted(sockets ^ WEBSOCKETS.keys()) == [], "classify WebSocket routes in WEBSOCKETS"

    guarded = {kind for kind in ROUTES.values() if not kind.startswith("allowed: ")}
    assert guarded == ACTIONS
    assert all(len(reason) > len("allowed: ") for reason in ROUTES.values())


# Lifecycle-label values and spellings that a case- or accent-insensitive collation would merge.
LIFECYCLE_LABEL_PATCHES: list[dict[str, str]] = [
    *({CLOSED_LABEL_KEY: value} for value in ("", "TRUE", "1", "closed")),
    *(
        {key: "false"}
        for key in (
            "OMNIGENT.CLOSED",
            " omnigent.closed",
            "omnigent.closed ",
            "omnigent.closed\u200b",
            "\ufeffomnigent.closed",
            "\uff4f\uff4d\uff4e\uff49\uff47\uff45\uff4e\uff54.closed",
            "omnig\u00e9nt.closed",
            "Omnigent.Parent_Wake",
            "omnigent.parent_wake\u200d",
        )
    ),
]


@contextlib.asynccontextmanager
async def _lenient(run: _Run) -> AsyncIterator[MutationTargets]:
    """Alice's targets over a client that returns an app error as a 500 instead of raising it."""
    transport = httpx.ASGITransport(app=run.app, raise_app_exceptions=False)
    headers = {"origin": OMNIGENT_INTERNAL_WS_ORIGIN}
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as client:
        yield dataclasses.replace(run.targets, client=client)


def _coral_answered(response: httpx.Response) -> bool:
    """Whether Coral's guard refused or failed the request (409 refusal or retryable 500)."""
    return "Coral" in response.text or "whether this change is allowed" in response.text


async def test_an_open_step_takes_every_client_event_but_clear(run: _Run) -> None:
    """Turns, slash commands, /compact, retries, approvals, items and stops reach an open step."""
    run.bind(run.targets.session_id)
    allowed = sorted(CLIENT_SESSION_EVENT_TYPES - {"clear"})
    assert {
        "message",
        "slash_command",
        "compact",
        "retry_session",
        "approval",
        "function_call_output",
        "interrupt",
        "stop_session",
    } <= set(allowed)

    async with _lenient(run) as t:
        for event_type in allowed:
            response = await t.event(event_type, ALICE)
            assert not _coral_answered(response), (event_type, response.text)
    # Each event the anchor would refuse was checked against the step's binding, then allowed.
    assert len(run.lookup.reads) == len(set(allowed) - STOP_EVENTS)
    assert {"message", "interrupt", "stop_session"} <= set(run.forwarded_types())


@pytest.mark.parametrize("kind", ["step", "anchor", "closed step"])
async def test_every_bound_session_refuses_session_changes_in_any_spelling(
    run: _Run, kind: str
) -> None:
    t, client = run.targets, run.targets.client
    session = t.session_id
    run.bind(session, kind)
    run.bind(t.scheduled_session_id, kind)
    before = run.row()

    for body in [*REFUSED_PATCHES, *({"labels": labels} for labels in LIFECYCLE_LABEL_PATCHES)]:
        _assert_refused(await t.patch(body, ALICE), session)
    servers = f"/v1/sessions/{session}/agent/mcp-servers"
    refused: list[Callable[[], Awaitable[httpx.Response]]] = [
        lambda: t.launch(ALICE),
        lambda: t.grant(ALICE),
        lambda: t.grant(ALICE, user=RESERVED_USER_PUBLIC),
        lambda: t.json_child(ALICE),
        lambda: t.bundle_child(ALICE),
        lambda: t.replace_agent(ALICE),
        lambda: t.add_mcp_server(ALICE),
        lambda: client.delete(f"{servers}/notes", headers=ALICE),
    ]
    for send in refused:
        _assert_refused(await send(), session)
    _assert_refused(await t.schedule(ALICE), t.scheduled_session_id)
    _assert_refused(await t.reschedule(ALICE), t.scheduled_session_id)
    assert run.row() == before
    children = t.conversations.list_conversations(
        limit=10, kind=None, parent_conversation_id=session
    )
    assert children.data == []

    # What a user may still do to any run session.
    for body in ({"title": "kept"}, {"labels": {"omnigent.pinned": "true", "team": "ml"}}):
        response = await t.patch(body, ALICE)
        assert response.status_code == 200, (body, response.text)
    for body in ({"family_pinned": True}, {"silent": True, "title": "quiet"}):
        assert not _coral_answered(await t.patch(body, ALICE)), body
    for event_type in sorted(STOP_EVENTS):
        stopped = await t.event(event_type, ALICE)
        assert stopped.status_code < 400, (event_type, stopped.text)
    assert run.forwarded_types() == ["interrupt", "stop_session"]
    fork = await client.post(f"/v1/sessions/{session}/fork", json={}, headers=ALICE)
    archived = await t.patch({"archived": True}, ALICE)
    deleted = await client.delete(f"/v1/sessions/{session}", headers=ALICE)
    assert (fork.status_code, archived.status_code) == (201, 200), (fork.text, archived.text)
    assert deleted.status_code in (200, 204), deleted.text


async def test_ordinary_sessions_never_consult_coral(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With Coral's store down, guarded routes on an unlabelled session answer as Omnigent."""
    run.lookup.error = RuntimeError("bindings table locked")
    hops = record_check_hops(monkeypatch)
    servers = f"/v1/sessions/{run.targets.session_id}/agent/mcp-servers"

    async with _lenient(run) as t:
        responses = [await t.patch(body, ALICE) for body in REFUSED_PATCHES]
        responses += [
            await t.patch({"labels": labels}, ALICE) for labels in LIFECYCLE_LABEL_PATCHES
        ]
        responses += [
            await t.event(event_type, ALICE)
            for event_type in sorted(CLIENT_SESSION_EVENT_TYPES | {"session_message"})
        ]
        for send in (
            lambda: t.launch(ALICE),
            lambda: t.grant(ALICE),
            lambda: t.grant(ALICE, user=RESERVED_USER_PUBLIC),
            lambda: t.json_child(ALICE),
            lambda: t.bundle_child(ALICE),
            lambda: t.replace_agent(ALICE),
            lambda: t.add_mcp_server(ALICE),
            lambda: t.client.delete(f"{servers}/notes", headers=ALICE),
            lambda: t.schedule(ALICE),
            lambda: t.reschedule(ALICE),
        ):
            responses.append(await send())

    assert [response.text for response in responses if _coral_answered(response)] == []
    assert run.lookup.reads == [] and hops == []
    # Omnigent's own lifecycle labels stay client-writable outside runs.
    closed = await run.targets.patch({"labels": {CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE}}, ALICE)
    assert closed.status_code == 200, closed.text
    assert run.row().labels[CLOSED_LABEL_KEY] == CLOSED_LABEL_VALUE


async def test_callers_without_access_get_omnigents_answer_before_corals(run: _Run) -> None:
    """A reader or a stranger is turned away by the route; the binding is never read."""
    t = run.targets
    session = t.session_id
    carol_email = "carol@example.com"
    carol = {"X-Forwarded-Email": carol_email}
    permissions = SqlAlchemyPermissionStore(run.db_uri)
    permissions.ensure_user(carol_email, is_admin=False)
    permissions.grant(carol_email, session, LEVEL_READ)
    run.bind(session)
    servers = f"/v1/sessions/{session}/agent/mcp-servers"
    sends: dict[str, Callable[[dict[str, str]], Awaitable[httpx.Response]]] = {
        "model PATCH": lambda h: t.patch({"model_override": "test-model"}, h),
        "closed label PATCH": lambda h: t.patch({"labels": {CLOSED_LABEL_KEY: "false"}}, h),
        "message": lambda h: t.event("message", h),
        "clear": lambda h: t.event("clear", h),
        "grant": lambda h: t.grant(h),
        "launch": lambda h: t.launch(h),
        "agent replace": lambda h: t.replace_agent(h),
        "MCP create": lambda h: t.add_mcp_server(h),
        "MCP delete": lambda h: t.client.delete(f"{servers}/notes", headers=h),
        "task create": lambda h: t.schedule(h, session_id=session),
    }

    for name, send in sends.items():
        for headers in (carol, BOB):
            response = await send(headers)
            assert response.status_code in (401, 403, 404), (name, headers, response.text)
    assert run.lookup.reads == []

    # A reader may pin it, and may start a child under it, which Coral then refuses.
    pinned = await t.patch({"labels": {"omnigent.pinned": "true"}}, carol)
    assert pinned.status_code == 200, pinned.text
    _assert_refused(await t.json_child(carol), session)


async def test_a_failing_coral_store_still_lets_users_stop_a_run_session(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = run.targets
    run.bind(t.session_id, "closed step")
    run.lookup.error = RuntimeError("bindings table locked")
    hops = record_check_hops(monkeypatch)

    for event_type in sorted(STOP_EVENTS):
        stopped = await t.event(event_type, ALICE)
        assert stopped.status_code < 400, (event_type, stopped.text)
    assert hops == [] and run.lookup.reads == []

    for send in (
        lambda: t.event("message", ALICE),
        lambda: t.patch({"labels": {CLOSED_LABEL_KEY: "false"}}, ALICE),
        lambda: t.json_child(ALICE),
    ):
        failed = await send()
        assert failed.status_code == 500, failed.text
        error = failed.json()["error"]
        assert error["code"] == "internal_error", error
        assert error["message"] == (
            f"Coral could not check whether session {t.session_id} is in a workflow run; retry."
        )
    assert len(hops) == 3
    assert run.row().labels[CLOSED_LABEL_KEY] == CLOSED_LABEL_VALUE
    assert run.forwarded_types() == ["interrupt", "stop_session"]


async def test_engine_sends_reach_run_sessions_without_asking_coral(run: _Run) -> None:
    """The engine briefs and stops sessions in-process; only the client's brief is refused."""
    t = run.targets
    anchor, closed = t.scheduled_session_id, t.session_id
    run.bind(anchor, "anchor")
    run.bind(closed, "closed step")
    engine = EngineEventContext(run.app, ALICE["X-Forwarded-Email"])
    dispatch = run.app.state.session_event_dispatch

    await dispatch(engine, anchor, _brief("Engine brief."), None)
    for session_id in (anchor, closed):
        for event_type in ("interrupt", "stop_session"):
            await dispatch(engine, session_id, SessionEventInput(type=event_type), None)

    assert run.lookup.reads == []
    assert run.forwarded_types() == ["message"] + ["interrupt", "stop_session"] * 2
    _assert_refused(await t.event("message", ALICE, session_id=anchor), anchor)


async def test_engine_agent_names_are_reserved_in_any_case(run: _Run) -> None:
    t = run.targets
    for name in ("CORAL__X", "coral__", "Coral__Review"):
        refused = await t.install_agent(ALICE, name=name)
        assert refused.status_code == 409, (name, refused.text)
        assert "reserved for Coral's engine agents" in refused.json()["error"]["message"]
    for name in ("coral_x", "my-coral__x", "coralx__"):
        installed = await t.install_agent(ALICE, name=name)
        assert installed.status_code == 200, (name, installed.text)
    assert run.lookup.reads == []


async def _throwaway(session_id: str) -> None:
    """A mutating route an upstream change might add."""


async def _throwaway_socket(websocket: WebSocket) -> None:
    """A WebSocket route an upstream change might add."""


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/v1/sessions/{session_id}/throwaway"),
        ("PUT", "/v1/sessions/{source_id}/throwaway"),
        ("POST", "/v1/sessions/{conversation_id}/throwaway"),
        ("POST", "/v1/sessions:bulk-throwaway"),
        ("DELETE", "/v1/sessions/throwaway"),
        ("PATCH", "/v1/agents/{agent_id}/throwaway"),
        ("DELETE", "/v1/scheduled-tasks/{scheduled_task_id}/throwaway"),
        ("POST", "/v1/mcp/{service_id}/throwaway"),
        ("WEBSOCKET", "/v1/sessions/{session_id}/throwaway"),
    ],
)
def test_the_inventory_names_an_unclassified_route(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    build = guarded_app

    def app_with_throwaway(*args: Any, **kwargs: Any) -> FastAPI:
        app = build(*args, **kwargs)
        if method == "WEBSOCKET":
            app.add_api_websocket_route(path, _throwaway_socket)
        else:
            app.add_api_route(path, _throwaway, methods=[method])
        return app

    monkeypatch.setitem(globals(), "guarded_app", app_with_throwaway)
    with pytest.raises(AssertionError) as unclassified:
        test_every_mutating_route_is_classified(db_uri, tmp_path)

    expected = repr(path) if method == "WEBSOCKET" else repr((method, path))
    assert expected in str(unclassified.value)


def test_the_inventory_names_a_classified_route_that_is_gone(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gone = "/v1/sessions/{session_id}/switch-agent"

    build = guarded_app

    def app_without_route(*args: Any, **kwargs: Any) -> FastAPI:
        app = build(*args, **kwargs)
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != gone]
        return app

    monkeypatch.setitem(globals(), "guarded_app", app_without_route)
    with pytest.raises(AssertionError, match="no longer exist") as stale:
        test_every_mutating_route_is_classified(db_uri, tmp_path)
    assert repr(("POST", gone)) in str(stale.value)


# Runner-only types that write the session: effort, launch args and mode labels, a child.
RUNNER_WRITES: dict[str, dict[str, Any]] = {
    "external_reasoning_effort_change": {"reasoning_effort": "high"},
    "external_permission_mode_change": {
        "permission_mode": "bypassPermissions",
        "initial_observation": False,
    },
    "external_codex_approval_mode_change": {"terminal_launch_args": ["--full-auto"]},
    "external_subagent_start": {"subagent_id": "a1", "agent_type": "Explore", "description": "x"},
}


@pytest.mark.parametrize("kind", ["step", "anchor", "closed step"])
async def test_runner_only_events_need_the_sessions_own_runner(run: _Run, kind: str) -> None:
    """Omnigent lets an owner post runner-only types; on a run session only its runner may."""
    t = run.targets
    session = t.session_id
    run.bind(session, kind)
    url = f"/v1/sessions/{session}/events"
    before = run.row()

    for event_type, data in RUNNER_WRITES.items():
        posted = await t.client.post(url, json={"type": event_type, "data": data}, headers=ALICE)
        _assert_refused(posted, session)
    _assert_refused(await t.post_transcript(ALICE), session)
    assert run.row() == before
    assert _items(run, session) == []
    children = t.conversations.list_conversations(
        limit=10, kind=None, parent_conversation_id=session
    )
    assert children.data == []

    runner = run.runner(session)
    for event_type, data in RUNNER_WRITES.items():
        posted = await t.client.post(url, json={"type": event_type, "data": data}, headers=runner)
        assert posted.status_code < 400, (event_type, posted.text)
    transcript = await t.post_transcript(runner)
    assert transcript.status_code < 400, transcript.text
    after = run.row()
    assert after.reasoning_effort == "high"
    assert after.terminal_launch_args
    assert "message" in _items(run, session)
    children = t.conversations.list_conversations(
        limit=10, kind=None, parent_conversation_id=session
    )
    assert len(children.data) == 1


async def test_omnigent_labels_and_closing_titles_are_refused(run: _Run) -> None:
    """A wrapper label reroutes a step's turns; a ``:closed:`` title closes it for Omnigent."""
    t, client = run.targets, run.targets.client
    session = t.session_id
    run.bind(session, "closed step")
    before = run.row()

    for labels in ({"omnigent.wrapper": "codex-native-ui"}, {"Omnigent.UI": "terminal"}):
        _assert_refused(await t.patch({"labels": labels}, ALICE), session)
    for title in ("work:closed:x", ":closed:"):
        _assert_refused(await t.patch({"title": title}, ALICE), session)
        _assert_refused(await t.retitle(ALICE, "agent-title", title=title), session)
        _assert_refused(await t.retitle(ALICE, "auto-title", title=title), session)
    goal = await client.put(
        f"/v1/sessions/{session}/codex_goal", json={"objective": "x"}, headers=ALICE
    )
    assert goal.status_code == 400, goal.text
    assert run.row() == before
    assert run.forwarded == []

    # The bare pin and the user's own labels and titles stay writable.
    for body in (
        {"labels": {"omnigent.pinned": "true"}},
        {"labels": {"team": "ml"}},
        {"title": "Done"},
    ):
        response = await t.patch(body, ALICE)
        assert response.status_code == 200, (body, response.text)


async def test_siblings_and_uploaded_agents_cannot_join_a_run(run: _Run) -> None:
    """A sibling joins a run session's family; a ``coral__`` upload poses as an engine agent."""
    t = run.targets
    run.app.state.feature_flags = resolve_feature_flags({"OMNIGENT_FEATURES": "sibling_sessions"})
    run.bind(t.session_id, "anchor")

    _assert_refused(await t.sibling(ALICE), t.session_id)
    for name in ("coral__loose", "Coral__Loose"):
        uploaded = await t.bundle_create(ALICE, name=name)
        assert uploaded.status_code == 409, (name, uploaded.text)
        assert "reserved for Coral's engine agents" in uploaded.json()["error"]["message"]
    row = run.row()
    assert row.family_id is None

    ordinary = await t.sibling(ALICE, source_id=t.scheduled_session_id)
    assert ordinary.status_code == 201, ordinary.text
    assert (await t.bundle_create(ALICE, name="loose")).status_code == 201
