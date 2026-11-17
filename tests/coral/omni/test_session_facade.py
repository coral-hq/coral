"""Coral's session facade creates the run's anchor and step sessions without an HTTP request.

Tier A: a real app (``create_app``) and its stores, a mock host on the real
host tunnel (``_connect_host``) that answers stats and launches and connects
each launched runner, and the real ``create_session`` executor over the
facade. The runner itself is an ``httpx`` mock behind ``_get_runner_client``,
as the host-launch integration tests do, so the session-init handshake is the
real one up to the runner's reply.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
import yaml
from asgiref.testing import ApplicationCommunicator
from fastapi import FastAPI, HTTPException
from sqlalchemy import delete, insert, update

from coral.db import SessionBindingRow
from coral.db.enum_codecs import LogKind, RunPauseReason, RunStatus, SessionBindingProgress
from coral.db.migrate import ensure_coral_schema
from coral.model.ids import anchor_session_id, derived_id, effect_session_id
from coral.omni.process_map import CORAL_RUNNER_TOKEN
from coral.omni.runner.tool_provider import tool_provider
from coral.omni.server import sessions as facade_module
from coral.omni.server.bundles import materialize, pack_bundle
from coral.omni.server.scopes import OmnigentRunScopeRunner
from coral.omni.server.sessions import (
    ANCHOR_AGENT_NAME,
    CORAL_RUNS_PROJECT_NAME,
    TITLE_ID_SUFFIX_CHARS,
    OmnigentSessionFacade,
)
from coral.profiles.bundle_spec import Stance, StepRef, build_step_bundle_yaml
from coral.queue import StartupLeaseLost
from coral.queue.conformance import run_executor_conformance
from coral.queue.executors import EffectCompleted, EffectFailed, EffectOutcome
from coral.recovery.drift import DriftPauser
from coral.slots.executors import CREATE_SESSION, create_session_executor
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun, Transition
from coral.stores.session_bindings import SqlAlchemySessionBindingStore
from omnigent.db.account_authority import account_authority_scope
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID, SqlUser, current_workspace_id
from omnigent.db.utils import builtin_agent_id, get_or_create_engine
from omnigent.entities import Conversation, MessageData, NewConversationItem
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.host.frames import (
    HostHelloFrame,
    HostLaunchRunnerFrame,
    HostLaunchRunnerResultFrame,
    HostRunnerStatusFrame,
    HostRunnerStatusResultFrame,
    HostStatFrame,
    HostStatResultFrame,
    HostStopRunnerFrame,
    HostStopRunnerResultFrame,
    decode_host_frame,
    encode_host_frame,
    host_capabilities,
)
from omnigent.runner.identity import token_bound_runner_id
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.auth import (
    LEVEL_OWNER,
    RESERVED_USER_LOCAL,
    RESERVED_USER_PUBLIC,
    AuthProvider,
)
from omnigent.server.host_registry import (
    HostConnection,
    _expected_host_owner,
    _host_owner_scope_active,
)
from omnigent.server.routes import _workspace_validation
from omnigent.server.routes import sessions as sessions_module
from omnigent.server.server_plugins import ServerServices
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.comment_store.sqlalchemy_store import SqlAlchemyCommentStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from tests.budgets import budget
from tests.coral.workspace._executor_fakes import effect_context, start_run
from tests.server.integration.test_session_host_launch import (
    _HOST_ID,
    _WORKSPACE,
    _connect_host,
    _NoopRunnerWS,
    _runner_hello,
)
from tests.server.routes.test_host_worktree import _FakeWebSocket
from tests.stores.coral._faults import SimulatedCrash, crash_around
from tests.tools.test_extensions import installed_tool_providers

WORKSPACE = DEFAULT_WORKSPACE_ID
STEP_AGENT_NAME = "coral-test-step"
NATIVE_AGENT_NAME = "coral-test-native"
SLOT = "review/item-0/m0"
# Each slot holds one session per generation, so a second step session needs its own slot.
OTHER_SLOT = "review/item-1/m0"


@dataclass
class _Stores:
    conversation: SqlAlchemyConversationStore
    agent: SqlAlchemyAgentStore
    artifact: LocalArtifactStore
    agent_cache: AgentCache
    host: HostStore
    project: SqlAlchemyProjectStore
    permission: SqlAlchemyPermissionStore
    file: SqlAlchemyFileStore
    comment: SqlAlchemyCommentStore


@pytest.fixture
def stores(db_uri: str, tmp_path: Path) -> _Stores:
    artifact = LocalArtifactStore(str(tmp_path / "artifacts"))
    return _Stores(
        conversation=SqlAlchemyConversationStore(db_uri),
        agent=SqlAlchemyAgentStore(db_uri),
        artifact=artifact,
        agent_cache=AgentCache(artifact_store=artifact, cache_dir=tmp_path / "cache"),
        host=HostStore(db_uri),
        project=SqlAlchemyProjectStore(db_uri),
        permission=SqlAlchemyPermissionStore(db_uri),
        file=SqlAlchemyFileStore(db_uri),
        comment=SqlAlchemyCommentStore(db_uri),
    )


@pytest.fixture
def app(stores: _Stores, db_uri: str) -> FastAPI:
    """
    An auth-less app with hosts and projects, as the host-launch tests use.

    It has no permission store, so ``POST /v1/sessions`` creates a child
    without grants; the facade gets its own permission store below.
    """
    app = create_app(
        agent_store=stores.agent,
        file_store=stores.file,
        conversation_store=stores.conversation,
        artifact_store=stores.artifact,
        agent_cache=stores.agent_cache,
        comment_store=stores.comment,
        host_store=stores.host,
        project_store=stores.project,
    )
    ensure_coral_schema(db_uri)
    return app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class _Host:
    """The user's host on the tunnel: answers stats, stops and launches; connects each runner."""

    def __init__(self, app: FastAPI, comm: ApplicationCommunicator) -> None:
        self._app = app
        self._comm = comm
        self.launch_frames: list[HostLaunchRunnerFrame] = []
        self.frames_seen = 0
        # Paths the host reports as missing.
        self.missing: set[str] = set()
        # While set, stat requests get no answer, as from a host that is slow or asleep.
        self.silent_stats = False
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> _Host:
        self._task = asyncio.create_task(self._serve())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        assert self._task is not None
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await self._task

    def launches_for(self, session_id: str) -> int:
        return sum(frame.session_id == session_id for frame in self.launch_frames)

    async def _serve(self) -> None:
        while True:
            output = await self._comm.receive_output(timeout=budget(60.0))
            if output["type"] != "websocket.send":
                continue
            try:
                frame = decode_host_frame(output["text"])
            except ValueError:
                continue
            self.frames_seen += 1
            reply: object
            if isinstance(frame, HostStatFrame) and self.silent_stats:
                continue
            if isinstance(frame, HostStatFrame):
                exists = frame.path not in self.missing
                reply = HostStatResultFrame(
                    request_id=frame.request_id,
                    status="ok",
                    exists=exists,
                    type="directory" if exists else None,
                    canonical_path=frame.path if exists else None,
                )
            elif isinstance(frame, HostStopRunnerFrame):
                reply = HostStopRunnerResultFrame(request_id=frame.request_id, status="stopped")
            elif isinstance(frame, HostRunnerStatusFrame):
                reply = HostRunnerStatusResultFrame(request_id=frame.request_id, status="alive")
            elif isinstance(frame, HostLaunchRunnerFrame):
                self.launch_frames.append(frame)
                runner_id = token_bound_runner_id(frame.binding_token)
                self._app.state.tunnel_registry.register(
                    runner_id, _NoopRunnerWS(), _runner_hello()
                )
                reply = HostLaunchRunnerResultFrame(
                    request_id=frame.request_id, status="launched", runner_id=runner_id
                )
            else:
                continue
            await self._comm.send_input(
                {"type": "websocket.receive", "text": encode_host_frame(reply)}
            )


@pytest_asyncio.fixture
async def host(app: FastAPI) -> AsyncIterator[_Host]:
    comm = await _connect_host(app, [CORAL_RUNNER_TOKEN])
    async with _Host(app, comm) as host:
        yield host


@dataclass
class _Runner:
    """The launched runners' HTTP side: records each session-init handshake."""

    inits: list[str] = field(default_factory=list)

    def inits_for(self, session_id: str) -> int:
        return self.inits.count(session_id)


@pytest_asyncio.fixture
async def runner(
    app: FastAPI, stores: _Stores, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[_Runner]:
    recorded = _Runner()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/sessions":
            recorded.inits.append(json.loads(request.content)["session_id"])
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://runner"
    ) as runner_client:

        async def connected_runner(
            session_id: str, *_args: object, conversation: Conversation | None = None
        ) -> Any:
            # Routed by the row the caller hands in, as the runner router does.
            conv = conversation or await asyncio.to_thread(
                stores.conversation.get_conversation, session_id
            )
            if conv is None or conv.runner_id is None:
                return None
            return runner_client if app.state.tunnel_registry.get(conv.runner_id) else None

        monkeypatch.setattr(sessions_module, "_get_runner_client", connected_runner)
        monkeypatch.setattr(sessions_module, "_ensure_runner_relay_ready", AsyncMock())
        yield recorded


@dataclass
class _RecordingLauncher:
    """A launcher that records the row and ambient scopes it was handed, and launches nothing."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    async def launch(self, conv: Conversation, *, user_id: str | None) -> None:
        owner = _expected_host_owner.get()
        self.calls.append(
            {
                "conv": conv,
                "user_id": user_id,
                "workspace_id": current_workspace_id(),
                # A host-owner scope with no owner (auth off) fences sends to ownerless hosts.
                "host_owner_scope": (
                    _host_owner_scope_active.get(),
                    None if owner is None else (owner.user_id, owner.workspace_id),
                ),
            }
        )


class _Coral:
    """One run, the create executor over the real facade, and its stores."""

    def __init__(
        self,
        app: FastAPI,
        stores: _Stores,
        db_uri: str,
        *,
        launcher: _RecordingLauncher | None = None,
        owner: str | None = None,
        generation: str | None = None,
        auth_on: bool = False,
        host_id: str = _HOST_ID,
    ) -> None:
        """
        :param owner: The run owner; ``None`` is the local user with auth off.
        :param auth_on: Give the facade an auth provider, as a multi-user server has.
        :param host_id: The host the run's spec names for its steps.
        """
        self.stores = stores
        self.bindings = SqlAlchemySessionBindingStore(db_uri)
        services = ServerServices(
            agent_store=stores.agent,
            file_store=stores.file,
            conversation_store=stores.conversation,
            artifact_store=stores.artifact,
            agent_cache=stores.agent_cache,
            comment_store=stores.comment,
            policy_store=None,
            permission_store=stores.permission,
            scheduled_task_store=None,
            project_store=stores.project,
            preference_store=None,
            host_store=stores.host,
            account_store=None,
            auth_provider=cast(AuthProvider, SimpleNamespace()) if auth_on else None,
            runner_router=app.state.runner_router,
            host_registry=app.state.host_registry,
            tunnel_registry=app.state.tunnel_registry,
            server_config={},
            host_sharded=False,
        )
        self.facade = OmnigentSessionFacade(app, services, self.bindings, launcher=launcher)
        self.run_store = FakeRunStore(default_workspace_id=WORKSPACE)
        self.run: CoralRun = start_run(
            self.run_store,
            workspace_id=WORKSPACE,
            user_id=owner,
            account_generation=generation,
            host_id=host_id,
            repo_path="/work",
            worktree_path=_WORKSPACE,
        )
        self.set_status(RunStatus.RUNNING, clear_pause=False)
        self.executor = create_session_executor(
            self.facade,
            self.run_store,
            DriftPauser(self.run_store),
            OmnigentRunScopeRunner(),
        )
        self.lease_checks = 0
        self.step_agent = _coral_agent(stores, Stance.IMPLEMENTER)

    @property
    def anchor_id(self) -> str:
        return anchor_session_id(WORKSPACE, self.run.id)

    def key(self, seq: int, subject: str) -> str:
        return f"{self.run.id}:{seq}:create_session:{subject}"

    def step_id(self, seq: int = 2, subject: str = SLOT) -> str:
        return effect_session_id(WORKSPACE, self.key(seq, subject))

    def anchor_payload(self, seq: int = 1) -> dict[str, Any]:
        return {
            "effect_type": CREATE_SESSION,
            "effect_key": self.key(seq, "anchor"),
            "role": "anchor",
        }

    def step_payload(self, seq: int = 2, subject: str = SLOT, **fields: object) -> dict[str, Any]:
        return {
            "effect_type": CREATE_SESSION,
            "effect_key": self.key(seq, subject),
            "role": "step",
            "agent_id": self.step_agent,
            "engine_slot_id": subject,
            "slot_role": "step_agent",
            "node_id": "review",
            **fields,
        }

    async def deliver(
        self, payload: dict[str, Any], *, lease_lost_at: int | None = None
    ) -> EffectOutcome:
        """Run the executor once; ``lease_lost_at`` is the lease check of this try that fails."""
        checks = 0

        async def ensure_lease() -> bool:
            nonlocal checks
            checks += 1
            self.lease_checks += 1
            return checks != lease_lost_at

        ctx = effect_context(
            workspace_id=WORKSPACE, run_id=self.run.id, payload=payload, ensure_lease=ensure_lease
        )
        return await self.executor(ctx)

    async def anchor(self) -> dict[str, Any]:
        return _completed(await self.deliver(self.anchor_payload()))

    def conversation(self, session_id: str) -> Conversation | None:
        return self.stores.conversation.get_conversation(session_id)

    def progress(self, session_id: str) -> SessionBindingProgress | None:
        binding = self.bindings.get(WORKSPACE, session_id, run_id=self.run.id)
        return None if binding is None else binding.progress

    def children(self) -> list[str]:
        by_parent = self.stores.conversation.list_child_conversation_ids_by_parent(
            [self.anchor_id]
        )
        return by_parent[self.anchor_id]

    def set_status(self, status: RunStatus, *, clear_pause: bool = True) -> None:
        _, version = self.run_store.load_run_state(self.run.id, workspace_id=WORKSPACE)
        self.run_store.apply_transition(
            self.run.id,
            version,
            Transition(status=int(status), clear_pause_reason=clear_pause),
            workspace_id=WORKSPACE,
        )

    def drift_pauses(self) -> list[dict[str, Any]]:
        return [
            json.loads(entry.body)
            for entry in self.run_store.logs[(WORKSPACE, self.run.id)]
            if entry.kind == int(LogKind.PAUSED)
        ]


def _server_agent(stores: _Stores, name: str, harness: str) -> str:
    """A plain agent on *harness*, not a Coral bundle."""
    return _stored_agent(
        stores,
        {
            "spec_version": 1,
            "name": name,
            "executor": {
                "type": "omnigent",
                "reasoning_effort": "high",
                "config": {"harness": harness},
            },
        },
    )


def _coral_agent(stores: _Stores, stance: Stance, **overrides: object) -> str:
    """A generated Coral bundle of *stance* pinning a high effort; *overrides* replace top keys."""
    ref = StepRef(workflow_id="demo-flow", node_id=stance.value, roster_index=0)
    config = yaml.safe_load(build_step_bundle_yaml(ref, stance, model=None, provider=None))
    config["executor"]["reasoning_effort"] = "high"
    config.update(overrides)
    return _stored_agent(stores, config)


def _stored_agent(stores: _Stores, config: dict[str, Any]) -> str:
    """Register an operator-authored agent, as the server's own agents are, once per name."""
    name = config["name"]
    existing = stores.agent.get_by_name(name)
    if existing is not None:
        return existing.id
    bundle = pack_bundle(yaml.safe_dump(config).encode())
    agent_id = derived_id("coral-test-agent", name)
    location = f"{agent_id}/{hashlib.sha256(bundle).hexdigest()}"
    stores.artifact.put(location, bundle)
    stores.agent.create(agent_id, name, location)
    return agent_id


@pytest.fixture
def coral(app: FastAPI, stores: _Stores, db_uri: str) -> _Coral:
    return _Coral(app, stores, db_uri)


@pytest.fixture
def launcher() -> _RecordingLauncher:
    return _RecordingLauncher()


@pytest.fixture
def unlaunched(app: FastAPI, stores: _Stores, db_uri: str, launcher: _RecordingLauncher) -> _Coral:
    return _Coral(app, stores, db_uri, launcher=launcher)


def _completed(outcome: EffectOutcome) -> dict[str, Any]:
    assert isinstance(outcome, EffectCompleted), outcome
    assert outcome.result is not None
    return outcome.result


def _failed(outcome: EffectOutcome) -> EffectFailed:
    assert isinstance(outcome, EffectFailed), outcome
    return outcome


async def test_redelivered_create_session_effect_reuses_one_session(
    coral: _Coral, host: _Host, runner: _Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    await coral.anchor()
    step_id = coral.step_id()

    # The first delivery dies right after the session row is written.
    with monkeypatch.context() as crash:
        crash_around(crash, coral.stores.conversation, "create_conversation", when="after")
        with pytest.raises(SimulatedCrash):
            await coral.deliver(coral.step_payload())
    assert coral.progress(step_id) == SessionBindingProgress.RESERVED
    assert host.launches_for(step_id) == 0

    redelivered = _completed(await coral.deliver(coral.step_payload()))
    before_again = (host.frames_seen, coral.lease_checks)
    again = _completed(await coral.deliver(coral.step_payload()))

    assert redelivered == again == {"session_id": step_id, "role": "step", "generation": 1}
    assert coral.children() == [step_id]
    assert coral.progress(step_id) == SessionBindingProgress.INITIALIZED
    assert len(coral.bindings.list_for_run(WORKSPACE, coral.run.id)) == 2
    # One launch and one session-init handshake; the last delivery returned at once,
    # with no host round trip and no side effect to fence.
    assert host.launches_for(step_id) == 1
    assert runner.inits_for(step_id) == 1
    assert (host.frames_seen, coral.lease_checks) == before_again
    step = coral.conversation(step_id)
    assert step is not None
    assert step.runner_id == token_bound_runner_id(host.launch_frames[-1].binding_token)


async def test_reemitted_anchor_effect_adopts_the_run_anchor(coral: _Coral) -> None:
    first = _completed(await coral.deliver(coral.anchor_payload(seq=1)))
    # A retried run start re-keys the anchor effect; the run keeps one anchor.
    rekeyed = _completed(await coral.deliver(coral.anchor_payload(seq=9)))

    assert first == rekeyed == {"session_id": coral.anchor_id, "role": "anchor", "generation": 1}
    [binding] = coral.bindings.list_for_run(WORKSPACE, coral.run.id)
    assert (binding.session_id, binding.progress) == (
        coral.anchor_id,
        SessionBindingProgress.INITIALIZED,
    )
    anchor = coral.conversation(coral.anchor_id)
    assert anchor is not None
    listed = coral.stores.conversation.list_conversations(
        limit=100, kind=None, include_archived=True
    ).data
    assert [conv.id for conv in listed if conv.project_id == anchor.project_id] == [
        coral.anchor_id
    ]


async def test_anchor_is_filed_in_coral_runs_with_only_an_owner_grant(
    coral: _Coral, client: httpx.AsyncClient
) -> None:
    await coral.anchor()

    anchor = coral.conversation(coral.anchor_id)
    assert anchor is not None
    assert (anchor.host_id, anchor.runner_id, anchor.workspace, anchor.parent_conversation_id) == (
        None,
        None,
        None,
        None,
    )
    assert anchor.title == coral.run.title
    assert {key: value for key, value in anchor.labels.items() if key.startswith("coral.")} == {
        "coral.run_id": coral.run.id,
        "coral.role": "run",
    }
    project = coral.stores.project.get(anchor.project_id or "", user_id=None)
    assert project is not None
    assert project.name == CORAL_RUNS_PROJECT_NAME
    assert project.id == derived_id("coral-runs-project", str(WORKSPACE), "")
    # The run owner (the local user, auth being off) owns it; it is not public.
    grant = coral.stores.permission.get(RESERVED_USER_LOCAL, coral.anchor_id)
    assert grant is not None and grant.level == LEVEL_OWNER
    assert coral.stores.permission.get(RESERVED_USER_PUBLIC, coral.anchor_id) is None
    # The interim anchor agent is a hidden, operator-authored row.
    agent = coral.stores.agent.get(anchor.agent_id or "")
    assert agent is not None
    assert (agent.id, agent.name, agent.operator_authored) == (
        builtin_agent_id(ANCHOR_AGENT_NAME),
        ANCHOR_AGENT_NAME,
        True,
    )
    listed = (await client.get("/v1/agents")).json()["data"]
    assert ANCHOR_AGENT_NAME not in {item["name"] for item in listed}
    # The session page still loads the anchor and its agent.
    snapshot = await client.get(f"/v1/sessions/{coral.anchor_id}")
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["agent_id"] == agent.id


async def test_coral_runs_project_survives_a_rename_and_adopts_an_existing_name(
    app: FastAPI, stores: _Stores, db_uri: str
) -> None:
    # The owner already has a folder with that name, made by hand.
    stores.project.create("d" * 32, CORAL_RUNS_PROJECT_NAME, None)
    first = _Coral(app, stores, db_uri)
    await first.anchor()
    first_anchor = first.conversation(first.anchor_id)
    assert first_anchor is not None and first_anchor.project_id == "d" * 32

    stores.project.update("d" * 32, user_id=None, name="Workflow runs")
    second = _Coral(app, stores, db_uri)
    await second.anchor()
    second_anchor = second.conversation(second.anchor_id)
    assert second_anchor is not None
    # The derived project is created beside the renamed one, which keeps its sessions.
    derived = derived_id("coral-runs-project", str(WORKSPACE), "")
    assert second_anchor.project_id == derived
    assert stores.project.get(derived, user_id=None) is not None


async def test_step_child_is_bound_but_unlaunched_until_the_owner_scoped_launch(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()

    _completed(await unlaunched.deliver(unlaunched.step_payload()))

    [call] = launcher.calls
    conv: Conversation = call["conv"]
    assert conv.id == unlaunched.step_id()
    assert (conv.parent_conversation_id, conv.kind) == (unlaunched.anchor_id, "sub_agent")
    assert (conv.host_id, conv.workspace, conv.git_branch, conv.runner_id) == (
        _HOST_ID,
        _WORKSPACE,
        None,
        None,
    )
    assert conv.labels["omnigent.parent_wake"] == "off"
    assert {key: value for key, value in conv.labels.items() if key.startswith("coral.")} == {
        "coral.run_id": unlaunched.run.id,
        "coral.role": "step",
        "coral.node_id": "review",
    }
    assert conv.title == f"{SLOT} · {conv.id[:TITLE_ID_SUFFIX_CHARS]}"
    assert conv.reasoning_effort == "high"
    assert (call["workspace_id"], call["host_owner_scope"], call["user_id"]) == (
        WORKSPACE,
        (True, None),
        None,
    )
    grant = unlaunched.stores.permission.get(RESERVED_USER_LOCAL, conv.id)
    assert grant is not None and grant.level == LEVEL_OWNER
    assert unlaunched.stores.permission.get(RESERVED_USER_PUBLIC, conv.id) is None
    assert unlaunched.progress(conv.id) == SessionBindingProgress.INITIALIZED


async def test_step_child_row_matches_post_sessions_except_the_allowed_fields(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host, client: httpx.AsyncClient
) -> None:
    await unlaunched.anchor()
    _completed(await unlaunched.deliver(unlaunched.step_payload()))
    response = await client.post(
        "/v1/sessions",
        json={
            "agent_id": unlaunched.step_agent,
            "host_id": _HOST_ID,
            "workspace": _WORKSPACE,
            "parent_session_id": unlaunched.anchor_id,
            "title": "created over HTTP",
        },
    )
    assert response.status_code == 201, response.text

    facade_row = unlaunched.conversation(unlaunched.step_id())
    http_row = unlaunched.conversation(response.json()["id"])
    assert facade_row is not None and http_row is not None
    allowed = {
        "id": "each session has its own id",
        "title": "a step is titled by its slot and id, the HTTP child by its request",
        # Equal to the second unless the two creates straddle a second boundary.
        "created_at": "created one after the other",
        "updated_at": "updated one after the other",
        "runner_id": "a step is launched by its own create, after this row is written",
    }
    label_prefixes = {
        "coral.": "the engine's ownership labels",
        "omnigent.parent_wake": "a step never wakes the anchor",
        "omnigent.client_surface": "the HTTP request names its client; the engine has none",
    }

    def compared(conv: Conversation) -> dict[str, Any]:
        row = {k: v for k, v in dataclasses.asdict(conv).items() if k not in allowed}
        row["labels"] = {
            key: value
            for key, value in conv.labels.items()
            if not any(key.startswith(prefix) for prefix in label_prefixes)
        }
        return row

    assert compared(facade_row) == compared(http_row)


async def test_squatted_title_is_a_title_conflict_and_nothing_launches(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()
    store = unlaunched.stores.conversation
    # A child taking the slot's bare title does not block the step: its title ends with its id.
    store.create_conversation(
        kind="sub_agent", title=SLOT, parent_conversation_id=unlaunched.anchor_id
    )
    _completed(await unlaunched.deliver(unlaunched.step_payload()))
    # Only the exact title, with that id part, can still be taken first.
    later = unlaunched.step_id(seq=3, subject=OTHER_SLOT)
    store.create_conversation(
        kind="sub_agent",
        title=f"{OTHER_SLOT} · {later[:TITLE_ID_SUFFIX_CHARS]}",
        parent_conversation_id=unlaunched.anchor_id,
    )

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload(seq=3, subject=OTHER_SLOT)))

    assert (failure.error_code, failure.retryable) == ("session.title_conflict", False)
    assert unlaunched.conversation(later) is None
    assert len(launcher.calls) == 1


async def test_native_harness_step_is_refused_before_anything_is_created(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()
    native = _server_agent(unlaunched.stores, NATIVE_AGENT_NAME, "claude-native")

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload(agent_id=native)))

    assert (failure.error_code, failure.retryable) == ("session.harness_not_supported", False)
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert unlaunched.conversation(unlaunched.step_id()) is None
    assert launcher.calls == []


@pytest.mark.parametrize(
    "capabilities",
    [None, ["coral_runner:2", "os_sandbox:none"], ["CORAL_RUNNER:1"]],
    ids=["none", "another-version", "other-case"],
)
async def test_a_host_without_the_coral_runner_token_is_refused(
    unlaunched: _Coral, launcher: _RecordingLauncher, app: FastAPI, capabilities: list[str] | None
) -> None:
    await unlaunched.anchor()
    step_id = unlaunched.step_id()

    async with _Host(app, await _connect_host(app, capabilities)) as host:
        failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.host_unsupported", False)
    assert failure.message == (
        f"host {_HOST_ID!r} cannot run Coral steps: update Coral on that host, "
        "or unset CORAL_DISABLE_HOST_ENTRY_POINTS"
    )
    assert unlaunched.progress(step_id) is None
    assert unlaunched.conversation(step_id) is None
    assert unlaunched.stores.permission.get(RESERVED_USER_LOCAL, step_id) is None
    assert (launcher.calls, host.frames_seen, host.launch_frames) == ([], 0, [])


async def test_a_host_that_loses_the_token_before_the_launch_is_refused(
    unlaunched: _Coral,
    launcher: _RecordingLauncher,
    host: _Host,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await unlaunched.anchor()
    registry = app.state.host_registry
    grant_owner = unlaunched.facade._grant_owner

    async def grant_then_reconnect_without_the_token(user_id: str | None, session_id: str) -> None:
        await grant_owner(user_id, session_id)
        # Between the row write and the launch, the host comes back with an older Coral.
        conn = registry.get(_HOST_ID)
        registry.register(
            host_id=_HOST_ID,
            ws=_FakeWebSocket(),
            hello=HostHelloFrame(version="0.1.0-test", frame_protocol_version=1, name="laptop"),
            owner=conn.owner,
            workspace_id=conn.workspace_id,
        )

    monkeypatch.setattr(unlaunched.facade, "_grant_owner", grant_then_reconnect_without_the_token)

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.host_unsupported", False)
    assert unlaunched.progress(unlaunched.step_id()) == SessionBindingProgress.ROW_CREATED
    assert unlaunched.conversation(unlaunched.step_id()) is not None
    assert (launcher.calls, host.launch_frames) == ([], [])


@pytest.mark.parametrize(("disabled", "accepted"), [("", True), ("1", False)])
async def test_a_hello_built_with_coral_installed_carries_the_token_unless_disabled(
    unlaunched: _Coral,
    launcher: _RecordingLauncher,
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    disabled: str,
    accepted: bool,
) -> None:
    monkeypatch.setenv("CORAL_DISABLE_HOST_ENTRY_POINTS", disabled)
    with installed_tool_providers(tool_provider()):
        capabilities = host_capabilities()
    await unlaunched.anchor()

    async with _Host(app, await _connect_host(app, capabilities)):
        outcome = await unlaunched.deliver(unlaunched.step_payload())

    if accepted:
        _completed(outcome)
        assert len(launcher.calls) == 1
    else:
        assert _failed(outcome).error_code == "session.host_unsupported"
        assert launcher.calls == []


@pytest.mark.parametrize(
    ("make_agent", "code", "rule"),
    [
        (
            lambda stores: _server_agent(stores, "coral-test-codex", "codex"),
            "session.agent_not_supported",
            "it runs on codex, not claude-sdk",
        ),
        (
            lambda stores: _server_agent(stores, STEP_AGENT_NAME, "claude-sdk"),
            "session.agent_not_supported",
            "it has no params.coral.generated.stance",
        ),
        (
            lambda stores: _coral_agent(
                stores, Stance.IMPLEMENTER, name="coral__test-unhygienic", timers=True
            ),
            "session.agent_not_supported",
            "breaks: timers is false",
        ),
        # A Coral bundle's params do not make another harness acceptable.
        (
            lambda stores: _coral_agent(
                stores,
                Stance.IMPLEMENTER,
                name="coral__test-codex-bundle",
                executor={"type": "omnigent", "config": {"harness": "codex"}},
            ),
            "session.agent_not_supported",
            "it runs on codex, not claude-sdk",
        ),
        # Forged params naming the anchor or an unknown stance, or no stance string.
        (
            lambda stores: _coral_agent(
                stores,
                Stance.IMPLEMENTER,
                name="coral__test-anchor-stance",
                params={"coral": {"generated": {"stance": "anchor"}}},
            ),
            "session.agent_not_supported",
            "its stance is 'anchor'",
        ),
        (
            lambda stores: _coral_agent(
                stores,
                Stance.IMPLEMENTER,
                name="coral__test-planner-stance",
                params={"coral": {"generated": {"stance": "planner"}}},
            ),
            "session.agent_not_supported",
            "its stance is 'planner'",
        ),
        (
            lambda stores: _coral_agent(
                stores,
                Stance.IMPLEMENTER,
                name="coral__test-list-stance",
                params={"coral": {"generated": {"stance": ["implementer"]}}},
            ),
            "session.agent_not_supported",
            "it has no params.coral.generated.stance",
        ),
        # The native refusal comes first, even for a Coral bundle.
        (
            lambda stores: _coral_agent(
                stores,
                Stance.IMPLEMENTER,
                name="coral__test-native",
                executor={"type": "omnigent", "config": {"harness": "claude-native"}},
            ),
            "session.harness_not_supported",
            "runs on claude-native",
        ),
    ],
    ids=[
        "codex",
        "claude_sdk_without_params_coral",
        "coral_bundle_failing_hygiene",
        "coral_bundle_on_codex",
        "forged_anchor_stance",
        "unknown_stance",
        "stance_not_a_string",
        "native",
    ],
)
async def test_non_coral_or_non_claude_sdk_step_agents_are_refused(
    unlaunched: _Coral,
    launcher: _RecordingLauncher,
    host: _Host,
    make_agent: Callable[[_Stores], str],
    code: str,
    rule: str,
) -> None:
    await unlaunched.anchor()
    agent_id = make_agent(unlaunched.stores)
    frames_before = host.frames_seen

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload(agent_id=agent_id)))

    assert (failure.error_code, failure.retryable) == (code, False)
    assert rule in failure.message
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert unlaunched.conversation(unlaunched.step_id()) is None
    assert (launcher.calls, host.frames_seen) == ([], frames_before)


async def test_orchestrator_slot_needs_an_orchestrator_bundle(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()
    agents = {
        stance: _coral_agent(unlaunched.stores, stance)
        for stance in Stance
        if stance is not Stance.ANCHOR
    }
    refused = [
        (Stance.IMPLEMENTER, "orchestrator"),
        (Stance.REVIEWER, "orchestrator"),
        (Stance.ORCHESTRATOR, "step_agent"),
        (Stance.ORCHESTRATOR, "verifier"),
    ]
    accepted = [
        (Stance.ORCHESTRATOR, "orchestrator"),
        (Stance.REVIEWER, "verifier"),
        (Stance.IMPLEMENTER, "merge_resolver"),
    ]

    for seq, (stance, slot_role) in enumerate(refused, start=2):
        payload = unlaunched.step_payload(seq, agent_id=agents[stance], slot_role=slot_role)
        failure = _failed(await unlaunched.deliver(payload))
        assert (failure.error_code, failure.retryable) == ("session.agent_not_supported", False)
        assert f"for slot role {slot_role}: its stance is {stance.value!r}" in failure.message
        assert unlaunched.progress(unlaunched.step_id(seq)) is None
    assert launcher.calls == []

    for seq, (stance, slot_role) in enumerate(accepted, start=10):
        # One session per slot and generation: each accepted role gets its own slot.
        payload = unlaunched.step_payload(
            seq, f"{SLOT}/{slot_role}", agent_id=agents[stance], slot_role=slot_role
        )
        _completed(await unlaunched.deliver(payload))
    assert [
        (call["conv"].agent_id, call["conv"].labels["coral.role"]) for call in launcher.calls
    ] == [
        (agents[Stance.ORCHESTRATOR], "orchestrator"),
        (agents[Stance.REVIEWER], "step"),
        (agents[Stance.IMPLEMENTER], "step"),
    ]


async def test_another_users_agent_is_not_permitted(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()
    foreign = derived_id("coral-test-agent", "bob")
    bundle = pack_bundle(
        yaml.safe_dump(
            {"spec_version": 1, "name": "bobs", "executor": {"config": {"harness": "claude-sdk"}}}
        ).encode()
    )
    location = f"{foreign}/{hashlib.sha256(bundle).hexdigest()}"
    unlaunched.stores.artifact.put(location, bundle)
    unlaunched.stores.agent.create_user_agent(foreign, "bobs", location, owner="bob")

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload(agent_id=foreign)))

    assert (failure.error_code, failure.retryable) == ("session.agent_not_permitted", False)
    assert unlaunched.progress(unlaunched.step_id()) is None


async def test_an_agent_id_no_agent_row_can_have_is_not_permitted(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    # The real agent store raises for an id that is not a uuid; it is never asked.
    await unlaunched.anchor()

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload(agent_id="reviewer")))

    assert (failure.error_code, failure.retryable) == ("session.agent_not_permitted", False)
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert launcher.calls == []


async def test_a_host_id_no_host_row_can_have_is_not_permitted(
    app: FastAPI, stores: _Stores, db_uri: str, launcher: _RecordingLauncher
) -> None:
    # The real host store raises for an id that is not a uuid; it is never asked.
    coral = _Coral(app, stores, db_uri, launcher=launcher, host_id="laptop-1")
    await coral.anchor()

    failure = _failed(await coral.deliver(coral.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.host_not_permitted", False)
    assert coral.progress(coral.step_id()) is None
    assert coral.conversation(coral.step_id()) is None
    assert launcher.calls == []


async def test_a_missing_run_worktree_is_permanent_and_nothing_is_created(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()
    host.missing.add(_WORKSPACE)

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.workspace_missing", False)
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert launcher.calls == []


async def test_a_redelivery_that_rebinds_the_session_is_a_binding_conflict(
    coral: _Coral, host: _Host, runner: _Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    await coral.anchor()

    async def no_runner(*_args: object, **_kwargs: object) -> object:
        return None, coral.conversation(coral.step_id())

    with monkeypatch.context() as patched:
        patched.setattr(facade_module, "ensure_runner_connected", no_runner)
        _failed(await coral.deliver(coral.step_payload()))
    assert coral.progress(coral.step_id()) == SessionBindingProgress.ROW_CREATED

    # The same effect, now naming another slot role, must not take the bound session over.
    failure = _failed(await coral.deliver(coral.step_payload(slot_role="verifier")))

    assert (failure.error_code, failure.retryable) == ("session.binding_conflict", False)
    assert "slot_role" in failure.message
    assert host.launches_for(coral.step_id()) == 0


async def test_a_step_before_its_anchor_is_retryable(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.anchor_missing", True)
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert launcher.calls == []
    # Once the anchor exists, the same effect goes through.
    await unlaunched.anchor()
    _completed(await unlaunched.deliver(unlaunched.step_payload()))


async def test_an_offline_host_is_retryable_and_launches_nothing(
    unlaunched: _Coral, launcher: _RecordingLauncher, app: FastAPI
) -> None:
    await unlaunched.anchor()
    comm = await _connect_host(app, [CORAL_RUNNER_TOKEN])
    await comm.send_input({"type": "websocket.disconnect", "code": 1001})
    await comm.wait(timeout=budget(5.0))

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.host_offline", True)
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert launcher.calls == []


async def _archive(client: httpx.AsyncClient, session_id: str) -> None:
    response = await client.patch(f"/v1/sessions/{session_id}", json={"archived": True})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("change", ["archived", "deleted", "bound"])
async def test_anchor_drift_pauses_the_run_and_creates_no_child(
    unlaunched: _Coral,
    launcher: _RecordingLauncher,
    host: _Host,
    client: httpx.AsyncClient,
    change: str,
) -> None:
    await unlaunched.anchor()
    store = unlaunched.stores.conversation
    if change == "archived":
        await _archive(client, unlaunched.anchor_id)
    elif change == "deleted":
        await store.delete_conversation(unlaunched.anchor_id)
    else:
        store.set_runner_id(unlaunched.anchor_id, "runner-the-user-attached")

    first = _failed(await unlaunched.deliver(unlaunched.step_payload()))
    second = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    cause = f"anchor_{change}"
    assert (first.error_code, first.retryable) == (f"drift.{cause}", False)
    # The run is paused now, so a repeat waits for the resume.
    assert (second.error_code, second.retryable) == ("run.paused", True)
    assert unlaunched.children() == []
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert launcher.calls == []
    state, _ = unlaunched.run_store.load_run_state(unlaunched.run.id, workspace_id=WORKSPACE)
    assert (state.run.status, state.run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.DRIFT)
    [pause] = unlaunched.drift_pauses()
    assert (pause["cause"], pause["session_id"], pause["reason"]) == (
        cause,
        unlaunched.anchor_id,
        "drift",
    )

    # Resumed without fixing the anchor, the next create pauses the run again.
    unlaunched.set_status(RunStatus.RUNNING)
    _failed(await unlaunched.deliver(unlaunched.step_payload()))
    assert len(unlaunched.drift_pauses()) == 2


async def test_deleted_session_is_never_recreated(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()
    _completed(await unlaunched.deliver(unlaunched.step_payload()))
    step_id = unlaunched.step_id()
    await unlaunched.stores.conversation.delete_conversation(step_id)

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("drift.session_deleted", False)
    assert unlaunched.conversation(step_id) is None
    assert unlaunched.progress(step_id) == SessionBindingProgress.INITIALIZED
    assert len(launcher.calls) == 1
    [pause] = unlaunched.drift_pauses()
    assert (pause["cause"], pause["session_id"]) == ("session_deleted", step_id)

    # A deleted anchor is not created again either.
    await unlaunched.stores.conversation.delete_conversation(unlaunched.anchor_id)
    unlaunched.set_status(RunStatus.RUNNING)
    anchor_failure = _failed(await unlaunched.deliver(unlaunched.anchor_payload(seq=5)))
    assert anchor_failure.error_code == "drift.anchor_deleted"
    assert unlaunched.conversation(unlaunched.anchor_id) is None


def _http_error(status: int) -> HTTPException:
    return HTTPException(status_code=status, detail="denied")


@pytest.mark.parametrize(
    ("patch", "error", "code", "retryable"),
    [
        ("resolve_host_launch", _http_error(404), "session.host_not_permitted", False),
        ("resolve_host_launch", _http_error(403), "session.host_not_permitted", False),
        (
            "resolve_host_launch",
            OmnigentError("host is offline", code=ErrorCode.CONFLICT),
            "session.host_offline",
            True,
        ),
        ("ensure_runner_connected", None, "session.runner_unavailable", True),
        (
            "ensure_runner_connected",
            OmnigentError("not set up", code=ErrorCode.HARNESS_NOT_CONFIGURED),
            "session.harness_not_configured",
            False,
        ),
        (
            "ensure_runner_connected",
            OmnigentError("gone", code=ErrorCode.WORKSPACE_MISSING),
            "session.workspace_missing",
            False,
        ),
        (
            "_ensure_runner_session_initialized",
            OmnigentError("no init", code=ErrorCode.RUNNER_UNAVAILABLE),
            "session.runner_unavailable",
            True,
        ),
    ],
)
async def test_launch_failures_are_typed_and_resume_from_the_written_row(
    coral: _Coral,
    host: _Host,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
    patch: str,
    error: BaseException | None,
    code: str,
    retryable: bool,
) -> None:
    await coral.anchor()
    real = getattr(facade_module, patch)

    async def failing(*_args: object, **_kwargs: object) -> object:
        if error is None:
            return None, coral.conversation(coral.step_id())
        raise error

    def failing_sync(*_args: object, **_kwargs: object) -> object:
        assert error is not None
        raise error

    with monkeypatch.context() as patched:
        patched.setattr(
            facade_module, patch, failing_sync if patch == "resolve_host_launch" else failing
        )
        failure = _failed(await coral.deliver(coral.step_payload()))

    assert (failure.error_code, failure.retryable) == (code, retryable)
    assert getattr(facade_module, patch) is real
    assert coral.progress(coral.step_id()) == SessionBindingProgress.ROW_CREATED
    # The next delivery resumes from the written row and finishes the launch.
    _completed(await coral.deliver(coral.step_payload()))
    assert coral.progress(coral.step_id()) == SessionBindingProgress.INITIALIZED
    assert coral.children() == [coral.step_id()]


def _crash_after_async(patched: pytest.MonkeyPatch, owner: object, attr: str) -> None:
    """Make the coroutine ``owner.attr`` finish its real work, then die."""
    real = getattr(owner, attr)

    async def crashing(*args: Any, **kwargs: Any) -> Any:
        await real(*args, **kwargs)
        raise SimulatedCrash(f"crash after {attr}")

    patched.setattr(owner, attr, crashing)


def _crash_after_progress(
    patched: pytest.MonkeyPatch, coral: _Coral, progress: SessionBindingProgress
) -> None:
    """Die right after the binding records ``progress``."""
    real = coral.bindings.record_progress

    def crashing(workspace_id: int, session_id: str, recorded: Any) -> Any:
        stored = real(workspace_id, session_id, recorded)
        if recorded == progress:
            raise SimulatedCrash(f"crash after recording {progress.name}")
        return stored

    patched.setattr(coral.bindings, "record_progress", crashing)


def _install_crash(phase: str, patched: pytest.MonkeyPatch, coral: _Coral) -> None:
    if phase == "row_created":
        _crash_after_progress(patched, coral, SessionBindingProgress.ROW_CREATED)
    elif phase == "grant":
        crash_around(patched, coral.stores.permission, "grant", when="after")
    elif phase == "announce":
        crash_around(patched, facade_module, "_announce_session_added", when="after")
    elif phase == "launch":
        _crash_after_async(patched, facade_module, "ensure_runner_connected")
    elif phase == "init":
        _crash_after_async(patched, facade_module, "_ensure_runner_session_initialized")
    else:
        _crash_after_progress(patched, coral, SessionBindingProgress.INITIALIZED)


@pytest.mark.parametrize(
    ("phase", "progress_after_crash"),
    [
        ("row_created", SessionBindingProgress.ROW_CREATED),
        ("grant", SessionBindingProgress.ROW_CREATED),
        ("announce", SessionBindingProgress.ROW_CREATED),
        ("launch", SessionBindingProgress.ROW_CREATED),
        # The runner session initializer answers a repeat for the same runner itself.
        ("init", SessionBindingProgress.ROW_CREATED),
        ("initialized", SessionBindingProgress.INITIALIZED),
    ],
)
async def test_a_crash_after_each_create_phase_still_yields_one_launched_session(
    coral: _Coral,
    host: _Host,
    runner: _Runner,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    progress_after_crash: SessionBindingProgress,
) -> None:
    await coral.anchor()
    step_id = coral.step_id()

    with monkeypatch.context() as patched:
        _install_crash(phase, patched, coral)
        with pytest.raises(SimulatedCrash):
            await coral.deliver(coral.step_payload())
    assert coral.progress(step_id) == progress_after_crash

    redelivered = _completed(await coral.deliver(coral.step_payload()))
    before_again = (host.frames_seen, coral.lease_checks, len(runner.inits))
    again = _completed(await coral.deliver(coral.step_payload()))

    assert redelivered == again == {"session_id": step_id, "role": "step", "generation": 1}
    assert coral.children() == [step_id]
    assert coral.progress(step_id) == SessionBindingProgress.INITIALIZED
    assert (host.launches_for(step_id), runner.inits_for(step_id)) == (1, 1)
    assert (host.frames_seen, coral.lease_checks, len(runner.inits)) == before_again
    grant = coral.stores.permission.get(RESERVED_USER_LOCAL, step_id)
    assert grant is not None and grant.level == LEVEL_OWNER


@pytest.mark.parametrize(
    ("role", "lost_at", "row_written", "progress"),
    [
        ("anchor", 1, False, SessionBindingProgress.RESERVED),
        ("step", 1, False, SessionBindingProgress.RESERVED),
        ("step", 2, True, SessionBindingProgress.ROW_CREATED),
    ],
)
async def test_a_lost_lease_stops_the_create_before_its_next_side_effect(
    coral: _Coral,
    host: _Host,
    runner: _Runner,
    role: str,
    lost_at: int,
    row_written: bool,
    progress: SessionBindingProgress,
) -> None:
    if role == "step":
        await coral.anchor()
    payload = coral.anchor_payload() if role == "anchor" else coral.step_payload()
    session_id = coral.anchor_id if role == "anchor" else coral.step_id()

    with pytest.raises(StartupLeaseLost):
        await coral.deliver(payload, lease_lost_at=lost_at)

    assert (coral.conversation(session_id) is not None) is row_written
    assert coral.progress(session_id) == progress
    assert host.launch_frames == []
    # The next lease holder finishes the same create with one launch.
    _completed(await coral.deliver(payload))
    assert coral.progress(session_id) == SessionBindingProgress.INITIALIZED
    if role == "step":
        assert coral.children() == [session_id]
        assert (host.launches_for(session_id), runner.inits_for(session_id)) == (1, 1)


async def test_racing_deliveries_of_one_step_effect_make_one_session(
    coral: _Coral, host: _Host, runner: _Runner
) -> None:
    await coral.anchor()
    step_id = coral.step_id()

    outcomes = await asyncio.gather(
        coral.deliver(coral.step_payload()), coral.deliver(coral.step_payload())
    )
    # A try that finds the other's row half written backs off; the next delivery finishes.
    for outcome in outcomes:
        if isinstance(outcome, EffectFailed):
            assert (outcome.error_code, outcome.retryable) == ("session.row_incomplete", True)
    final = _completed(await coral.deliver(coral.step_payload()))

    assert final == {"session_id": step_id, "role": "step", "generation": 1}
    assert coral.children() == [step_id]
    assert coral.progress(step_id) == SessionBindingProgress.INITIALIZED
    assert len(coral.bindings.list_for_run(WORKSPACE, coral.run.id)) == 2
    assert (host.launches_for(step_id), runner.inits_for(step_id)) == (1, 1)


async def test_racing_anchor_effects_with_different_keys_make_one_anchor(coral: _Coral) -> None:
    outcomes = await asyncio.gather(
        coral.deliver(coral.anchor_payload(seq=1)), coral.deliver(coral.anchor_payload(seq=9))
    )
    for outcome in outcomes:
        if isinstance(outcome, EffectFailed):
            assert (outcome.error_code, outcome.retryable) == ("session.row_incomplete", True)
    final = _completed(await coral.deliver(coral.anchor_payload(seq=1)))

    assert final == {"session_id": coral.anchor_id, "role": "anchor", "generation": 1}
    [binding] = coral.bindings.list_for_run(WORKSPACE, coral.run.id)
    assert binding.progress == SessionBindingProgress.INITIALIZED
    anchor = coral.conversation(coral.anchor_id)
    assert anchor is not None and anchor.project_id is not None
    listed = coral.stores.conversation.list_conversations(
        limit=100, kind=None, include_archived=True
    ).data
    assert [conv.id for conv in listed if conv.project_id == anchor.project_id] == [
        coral.anchor_id
    ]


class _DiesOnUse:
    """A session maker whose transaction never starts: the process dies first."""

    def __init__(self, maker: object) -> None:
        self._maker = maker

    def __getattr__(self, name: str) -> object:
        return getattr(self._maker, name)

    def __call__(self, *_args: object, **_kwargs: object) -> object:
        raise SimulatedCrash("crash before the metadata phase")


async def test_torn_step_row_is_repaired_once_and_launched_once(
    coral: _Coral, host: _Host, runner: _Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    await coral.anchor()
    step_id = coral.step_id()
    store = coral.stores.conversation

    # The conversation row commits; the metadata (host, workspace) never does.
    with monkeypatch.context() as crash:
        crash.setattr(store, "_session_immediate", _DiesOnUse(store._session_immediate))
        with pytest.raises(SimulatedCrash):
            await coral.deliver(coral.step_payload())
    torn = coral.conversation(step_id)
    assert torn is not None and torn.host_id is None
    assert coral.progress(step_id) == SessionBindingProgress.RESERVED

    deletes: list[str] = []
    real_delete = store.delete_conversation

    async def counted_delete(conversation_id: str, **kwargs: Any) -> bool:
        deletes.append(conversation_id)
        return await real_delete(conversation_id, **kwargs)

    monkeypatch.setattr(store, "delete_conversation", counted_delete)
    # A try whose lease is gone leaves the torn row for the next lease holder.
    with pytest.raises(StartupLeaseLost):
        await coral.deliver(coral.step_payload(), lease_lost_at=1)
    assert deletes == []
    _completed(await coral.deliver(coral.step_payload()))
    _completed(await coral.deliver(coral.step_payload()))

    assert deletes == [step_id]
    assert coral.children() == [step_id]
    repaired = coral.conversation(step_id)
    assert repaired is not None and (repaired.host_id, repaired.workspace) == (
        _HOST_ID,
        _WORKSPACE,
    )
    assert (host.launches_for(step_id), runner.inits_for(step_id)) == (1, 1)


async def test_a_crash_inside_the_torn_row_repair_recreates_the_row_once(
    coral: _Coral, host: _Host, runner: _Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    await coral.anchor()
    step_id = coral.step_id()
    store = coral.stores.conversation
    with monkeypatch.context() as crash:
        crash.setattr(store, "_session_immediate", _DiesOnUse(store._session_immediate))
        with pytest.raises(SimulatedCrash):
            await coral.deliver(coral.step_payload())

    # The repair deletes the torn row, then dies before writing it again.
    with monkeypatch.context() as crash:
        _crash_after_async(crash, store, "delete_conversation")
        with pytest.raises(SimulatedCrash):
            await coral.deliver(coral.step_payload())
    assert coral.conversation(step_id) is None
    assert coral.progress(step_id) == SessionBindingProgress.RESERVED

    _completed(await coral.deliver(coral.step_payload()))
    assert coral.children() == [step_id]
    assert host.launches_for(step_id) == 1


async def test_a_step_deleted_after_its_row_was_written_is_never_recreated(
    coral: _Coral, host: _Host, runner: _Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    await coral.anchor()
    step_id = coral.step_id()

    async def no_runner(*_args: object, **_kwargs: object) -> object:
        return None, coral.conversation(step_id)

    with monkeypatch.context() as patched:
        patched.setattr(facade_module, "ensure_runner_connected", no_runner)
        failure = _failed(await coral.deliver(coral.step_payload()))
    assert failure.error_code == "session.runner_unavailable"
    assert coral.progress(step_id) == SessionBindingProgress.ROW_CREATED
    await coral.stores.conversation.delete_conversation(step_id)

    first = _failed(await coral.deliver(coral.step_payload()))
    second = _failed(await coral.deliver(coral.step_payload()))

    assert (first.error_code, first.retryable) == ("drift.session_deleted", False)
    assert (second.error_code, second.retryable) == ("run.paused", True)
    assert coral.conversation(step_id) is None
    assert coral.children() == []
    assert host.launches_for(step_id) == 0
    assert [(pause["cause"], pause["session_id"]) for pause in coral.drift_pauses()] == [
        ("session_deleted", step_id)
    ]


async def test_an_anchor_deleted_after_its_row_was_written_is_never_recreated(
    coral: _Coral, host: _Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patched:
        crash_around(patched, coral.stores.permission, "grant", when="after")
        with pytest.raises(SimulatedCrash):
            await coral.deliver(coral.anchor_payload())
    assert coral.progress(coral.anchor_id) == SessionBindingProgress.ROW_CREATED
    await coral.stores.conversation.delete_conversation(coral.anchor_id)

    anchor_failure = _failed(await coral.deliver(coral.anchor_payload(seq=7)))
    step_failure = _failed(await coral.deliver(coral.step_payload()))

    assert (anchor_failure.error_code, anchor_failure.retryable) == ("drift.anchor_deleted", False)
    # The anchor's drift paused the run; the step waits for the resume.
    assert (step_failure.error_code, step_failure.retryable) == ("run.paused", True)
    assert coral.conversation(coral.anchor_id) is None
    assert coral.progress(coral.step_id()) is None
    assert host.launch_frames == []
    assert [pause["cause"] for pause in coral.drift_pauses()] == ["anchor_deleted"]
    # Resumed, the step finds the anchor deleted too.
    coral.set_status(RunStatus.RUNNING)
    resumed = _failed(await coral.deliver(coral.step_payload()))
    assert (resumed.error_code, resumed.retryable) == ("drift.anchor_deleted", False)


async def test_an_anchor_bound_to_a_host_pauses_the_run_and_creates_no_child(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()
    unlaunched.stores.conversation.set_host_id(
        unlaunched.anchor_id, _HOST_ID, workspace=_WORKSPACE
    )

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("drift.anchor_bound", False)
    assert unlaunched.children() == []
    assert launcher.calls == []
    [pause] = unlaunched.drift_pauses()
    assert (pause["cause"], pause["detail"]) == ("anchor_bound", _HOST_ID)


async def test_rearchiving_the_anchor_after_an_unarchive_pauses_the_run_again(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host, client: httpx.AsyncClient
) -> None:
    await unlaunched.anchor()
    await _archive(client, unlaunched.anchor_id)
    assert _failed(await unlaunched.deliver(unlaunched.step_payload())).error_code == (
        "drift.anchor_archived"
    )

    # The user unarchives the anchor and resumes; the step goes through.
    response = await client.patch(f"/v1/sessions/{unlaunched.anchor_id}", json={"archived": False})
    assert response.status_code == 200, response.text
    unlaunched.set_status(RunStatus.RUNNING)
    _completed(await unlaunched.deliver(unlaunched.step_payload()))
    assert len(launcher.calls) == 1

    # Archived again, the next step create pauses the run in a new epoch.
    await _archive(client, unlaunched.anchor_id)
    second = _failed(await unlaunched.deliver(unlaunched.step_payload(seq=3, title="second")))

    assert second.error_code == "drift.anchor_archived"
    state, _ = unlaunched.run_store.load_run_state(unlaunched.run.id, workspace_id=WORKSPACE)
    assert (state.run.status, state.run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.DRIFT)
    assert [pause["cause"] for pause in unlaunched.drift_pauses()] == [
        "anchor_archived",
        "anchor_archived",
    ]
    assert len(launcher.calls) == 1
    assert unlaunched.children() == [unlaunched.step_id()]


@pytest.mark.parametrize(
    ("name", "harness"),
    [
        ("coral-test-native-alias", "native-pi"),
        # A bare ``opencode`` is an alias of the native OpenCode harness.
        ("coral-test-opencode", "opencode"),
        # A native wrapper's agent name decides the harness whatever its spec says.
        ("codex-native-ui", "claude-sdk"),
    ],
)
async def test_native_harness_aliases_and_wrapper_names_are_refused(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host, name: str, harness: str
) -> None:
    await unlaunched.anchor()
    native = _server_agent(unlaunched.stores, name, harness)
    frames_before = host.frames_seen

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload(agent_id=native)))

    assert (failure.error_code, failure.retryable) == ("session.harness_not_supported", False)
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert unlaunched.conversation(unlaunched.step_id()) is None
    assert (launcher.calls, host.frames_seen) == ([], frames_before)


async def test_a_rekeyed_anchor_effect_adopts_a_row_its_crashed_first_try_wrote(
    coral: _Coral, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as crash:
        crash_around(crash, coral.stores.conversation, "create_conversation", when="after")
        with pytest.raises(SimulatedCrash):
            await coral.deliver(coral.anchor_payload(seq=1))
    assert coral.progress(coral.anchor_id) == SessionBindingProgress.RESERVED

    rekeyed = _completed(await coral.deliver(coral.anchor_payload(seq=9)))

    assert rekeyed == {"session_id": coral.anchor_id, "role": "anchor", "generation": 1}
    [binding] = coral.bindings.list_for_run(WORKSPACE, coral.run.id)
    assert binding.progress == SessionBindingProgress.INITIALIZED
    anchor = coral.conversation(coral.anchor_id)
    assert anchor is not None and anchor.project_id is not None


@pytest.mark.parametrize("role", ["anchor", "step"])
async def test_create_session_conformance_over_the_real_facade(
    coral: _Coral, host: _Host, runner: _Runner, role: str
) -> None:
    if role == "step":
        await coral.anchor()
    payload = coral.anchor_payload() if role == "anchor" else coral.step_payload()

    await run_executor_conformance(
        coral.executor,
        effect_type=CREATE_SESSION,
        payload=payload,
        workspace_id=WORKSPACE,
        run_id=coral.run.id,
    )

    session_id = coral.anchor_id if role == "anchor" else coral.step_id()
    assert coral.progress(session_id) == SessionBindingProgress.INITIALIZED
    assert host.launches_for(session_id) == (1 if role == "step" else 0)


async def test_an_anchor_archived_while_its_step_is_written_stops_the_launch(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    await unlaunched.anchor()
    real_announce = facade_module._announce_session_added

    def announce_then_archive(user_id: str | None, session_id: str) -> None:
        real_announce(user_id, session_id)
        if session_id == unlaunched.step_id():
            unlaunched.stores.conversation.update_conversation(unlaunched.anchor_id, archived=True)

    monkeypatch.setattr(facade_module, "_announce_session_added", announce_then_archive)
    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("drift.anchor_archived", False)
    assert launcher.calls == []
    assert unlaunched.progress(unlaunched.step_id()) == SessionBindingProgress.ROW_CREATED
    assert [pause["cause"] for pause in unlaunched.drift_pauses()] == ["anchor_archived"]


async def test_the_owner_grant_is_written_before_the_launch(
    app: FastAPI, stores: _Stores, db_uri: str, host: _Host
) -> None:
    grants_at_launch: list[Any] = []

    class _GrantCheckingLauncher(_RecordingLauncher):
        async def launch(self, conv: Conversation, *, user_id: str | None) -> None:
            grants_at_launch.append(stores.permission.get(RESERVED_USER_LOCAL, conv.id))
            await super().launch(conv, user_id=user_id)

    coral = _Coral(app, stores, db_uri, launcher=_GrantCheckingLauncher())
    await coral.anchor()

    _completed(await coral.deliver(coral.step_payload()))

    [grant] = grants_at_launch
    assert grant is not None and grant.level == LEVEL_OWNER


# ── Review fixes: host checks, auth on, stored identity ─────────────────────


async def test_a_host_that_never_answers_the_stat_is_retryable(
    unlaunched: _Coral,
    launcher: _RecordingLauncher,
    host: _Host,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await unlaunched.anchor()
    monkeypatch.setattr(_workspace_validation, "_STAT_TIMEOUT_S", 0.2)
    host.silent_stats = True

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.workspace_unverified", True)
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert unlaunched.conversation(unlaunched.step_id()) is None
    assert launcher.calls == []
    # Once the host answers again, the same effect goes through.
    host.silent_stats = False
    _completed(await unlaunched.deliver(unlaunched.step_payload()))
    assert len(launcher.calls) == 1


OWNER = "alice@example.test"
OWNER_GENERATION = "g1"


class _OwnedHost:
    """The owner's host connection on the app's registry, answered in process (auth on)."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self.launch_frames: list[HostLaunchRunnerFrame] = []
        self._answering: list[asyncio.Task[None]] = []

    def connect(self, generation: str) -> None:
        """Register a connection held by ``generation`` of the owner, replacing any earlier one."""
        with account_authority_scope(OWNER, generation):
            conn = self._app.state.host_registry.register(
                host_id=_HOST_ID,
                ws=_FakeWebSocket(),  # type: ignore[arg-type]
                hello=HostHelloFrame(
                    version="0.1.0-test",
                    frame_protocol_version=1,
                    name="laptop",
                    capabilities=[CORAL_RUNNER_TOKEN],
                ),
                owner=OWNER,
                workspace_id=WORKSPACE,
            )
        self._answering.append(asyncio.create_task(self._answer(conn)))

    async def close(self) -> None:
        self._app.state.host_registry.deregister(_HOST_ID, workspace_id=WORKSPACE)
        await asyncio.wait_for(asyncio.gather(*self._answering), timeout=budget(10.0))

    async def _answer(self, conn: HostConnection) -> None:
        # Results go straight to the pending futures, as the host tunnel route relays them.
        while (outbound := await conn.outbound_queue.get()) is not None:
            frame = decode_host_frame(outbound.data)
            if isinstance(frame, HostStatFrame):
                conn.pending_stats.pop(frame.request_id).set_result(
                    {
                        "status": "ok",
                        "exists": True,
                        "type": "directory",
                        "canonical_path": frame.path,
                        "error": None,
                    }
                )
            elif isinstance(frame, HostRunnerStatusFrame):
                conn.pending_runner_status.pop(frame.request_id).set_result({"status": "alive"})
            elif isinstance(frame, HostLaunchRunnerFrame):
                self.launch_frames.append(frame)
                runner_id = token_bound_runner_id(frame.binding_token)
                self._app.state.tunnel_registry.register(
                    runner_id, _NoopRunnerWS(), _runner_hello()
                )
                conn.pending_launches.pop(frame.request_id).set_result(
                    {
                        "status": "launched",
                        "runner_id": runner_id,
                        "error": None,
                        "error_code": None,
                        "workspace_recreated": False,
                    }
                )


def _add_account(db_uri: str, user_id: str, generation: str) -> None:
    with get_or_create_engine(db_uri).begin() as connection:
        connection.execute(
            insert(SqlUser).values(
                workspace_id=WORKSPACE, id=user_id, account_generation=generation
            )
        )


def _reregister_account(db_uri: str, user_id: str, generation: str) -> None:
    with get_or_create_engine(db_uri).begin() as connection:
        connection.execute(
            update(SqlUser)
            .where(SqlUser.workspace_id == WORKSPACE, SqlUser.id == user_id)
            .values(account_generation=generation)
        )


@pytest_asyncio.fixture
async def owned_host(app: FastAPI, stores: _Stores, db_uri: str) -> AsyncIterator[_OwnedHost]:
    _add_account(db_uri, OWNER, OWNER_GENERATION)
    with account_authority_scope(OWNER, OWNER_GENERATION):
        stores.host.upsert_on_connect(host_id=_HOST_ID, name="laptop", user_id=OWNER)
    host = _OwnedHost(app)
    host.connect(OWNER_GENERATION)
    try:
        yield host
    finally:
        await host.close()


async def test_with_auth_on_the_owner_holds_the_grants_and_omnigent_checks_them_at_launch(
    app: FastAPI,
    stores: _Stores,
    db_uri: str,
    owned_host: _OwnedHost,
    runner: _Runner,
) -> None:
    coral = _Coral(app, stores, db_uri, owner=OWNER, generation=OWNER_GENERATION, auth_on=True)
    await coral.anchor()
    step = _completed(await coral.deliver(coral.step_payload()))["session_id"]

    permission = stores.permission
    for session_id in (coral.anchor_id, step):
        grant = permission.get(OWNER, session_id)
        assert grant is not None and grant.level == LEVEL_OWNER
        assert permission.get(RESERVED_USER_LOCAL, session_id) is None
        assert permission.get(RESERVED_USER_PUBLIC, session_id) is None
    # Omnigent's launch check let the owner bind a runner through the anchor's grant.
    assert [frame.session_id for frame in owned_host.launch_frames] == [step]
    assert coral.progress(step) == SessionBindingProgress.INITIALIZED
    assert runner.inits_for(step) == 1

    # Without the anchor's grant, that check refuses the launch of the next step.
    permission.revoke(OWNER, coral.anchor_id)
    refused = _failed(await coral.deliver(coral.step_payload(seq=3, subject=OTHER_SLOT)))
    assert (refused.error_code, refused.retryable) == ("session.host_not_permitted", False)
    assert coral.progress(coral.step_id(seq=3, subject=OTHER_SLOT)) == (
        SessionBindingProgress.ROW_CREATED
    )
    assert len(owned_host.launch_frames) == 1

    # A connection held by another registration of the owner is refused before any write.
    permission.grant(OWNER, coral.anchor_id, LEVEL_OWNER)
    owned_host.connect("g2")
    other = _failed(await coral.deliver(coral.step_payload(seq=4)))
    assert (other.error_code, other.retryable) == ("session.host_not_permitted", False)
    assert coral.progress(coral.step_id(seq=4)) is None
    assert coral.conversation(coral.step_id(seq=4)) is None
    assert len(owned_host.launch_frames) == 1


@pytest.mark.usefixtures("coral_policy_registry")
async def test_a_bundle_the_owner_materialized_runs_as_a_step(
    app: FastAPI,
    stores: _Stores,
    db_uri: str,
    owned_host: _OwnedHost,
    runner: _Runner,
) -> None:
    # The production path: a user agent of the owner, not operator-authored, its env unexpanded.
    agent = materialize(
        stores.agent,
        stores.artifact,
        owner=OWNER,
        config_yaml=build_step_bundle_yaml(
            StepRef(workflow_id="demo-flow", node_id="check", roster_index=0),
            Stance.REVIEWER,
            model=None,
            provider=None,
        ),
        stance=Stance.REVIEWER,
    )
    coral = _Coral(app, stores, db_uri, owner=OWNER, generation=OWNER_GENERATION, auth_on=True)
    await coral.anchor()

    payload = coral.step_payload(agent_id=agent.agent_id, slot_role="verifier")
    step = _completed(await coral.deliver(payload))["session_id"]

    conv = coral.conversation(step)
    assert conv is not None and conv.agent_id == agent.agent_id
    assert [frame.session_id for frame in owned_host.launch_frames] == [step]
    assert coral.progress(step) == SessionBindingProgress.INITIALIZED


async def test_with_auth_on_a_run_without_an_owner_is_refused(
    app: FastAPI, stores: _Stores, db_uri: str
) -> None:
    coral = _Coral(app, stores, db_uri, auth_on=True)

    failure = _failed(await coral.deliver(coral.anchor_payload()))

    assert (failure.error_code, failure.retryable) == ("session.invalid", False)
    assert coral.progress(coral.anchor_id) is None
    assert coral.conversation(coral.anchor_id) is None


async def test_a_revoked_owner_is_refused_permanently(
    app: FastAPI, stores: _Stores, db_uri: str
) -> None:
    _add_account(db_uri, OWNER, OWNER_GENERATION)
    coral = _Coral(app, stores, db_uri, owner=OWNER, generation=OWNER_GENERATION, auth_on=True)
    # The owner deleted and re-created the account after the run started.
    _reregister_account(db_uri, OWNER, "g2")

    failure = _failed(await coral.deliver(coral.anchor_payload()))

    assert (failure.error_code, failure.retryable) == ("session.owner_revoked", False)
    assert coral.progress(coral.anchor_id) is None
    assert stores.permission.get(OWNER, coral.anchor_id) is None


async def test_an_agent_whose_stored_spec_no_longer_validates_is_refused(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()
    # A stored bundle whose spec no longer validates (here, an unknown harness name).
    broken = _server_agent(unlaunched.stores, "coral-test-bad-spec", "native-codex")

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload(agent_id=broken)))

    assert (failure.error_code, failure.retryable) == ("session.harness_not_supported", False)
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert unlaunched.conversation(unlaunched.step_id()) is None
    assert launcher.calls == []


async def test_the_anchor_agent_is_never_a_step_agent(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host
) -> None:
    await unlaunched.anchor()
    anchor = unlaunched.conversation(unlaunched.anchor_id)
    assert anchor is not None and anchor.agent_id is not None

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload(agent_id=anchor.agent_id)))

    assert (failure.error_code, failure.retryable) == ("session.agent_not_permitted", False)
    assert unlaunched.progress(unlaunched.step_id()) is None
    assert launcher.calls == []


async def test_an_archived_step_is_never_launched_and_pauses_the_run(
    coral: _Coral,
    host: _Host,
    runner: _Runner,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await coral.anchor()
    step_id = coral.step_id()

    async def no_runner(*_args: object, **_kwargs: object) -> object:
        return None, coral.conversation(step_id)

    with monkeypatch.context() as patched:
        patched.setattr(facade_module, "ensure_runner_connected", no_runner)
        _failed(await coral.deliver(coral.step_payload()))
    assert coral.progress(step_id) == SessionBindingProgress.ROW_CREATED
    await _archive(client, step_id)
    frames_before = host.frames_seen

    failure = _failed(await coral.deliver(coral.step_payload()))

    assert (failure.error_code, failure.retryable) == ("drift.session_archived", False)
    # Refused from the stored row, before any host round trip.
    assert host.frames_seen == frames_before
    assert host.launches_for(step_id) == 0
    assert coral.progress(step_id) == SessionBindingProgress.ROW_CREATED
    [pause] = coral.drift_pauses()
    assert (pause["cause"], pause["session_id"]) == ("session_archived", step_id)


@pytest.mark.parametrize("with_step", [True, False])
async def test_a_row_this_run_never_reserved_is_never_deleted(
    unlaunched: _Coral,
    launcher: _RecordingLauncher,
    host: _Host,
    client: httpx.AsyncClient,
    with_step: bool,
) -> None:
    await unlaunched.anchor()
    if with_step:
        _completed(await unlaunched.deliver(unlaunched.step_payload()))
    step_id = unlaunched.step_id()
    # The owner unfiles the anchor, and the anchor's binding is lost (say, a downgrade).
    response = await client.patch(f"/v1/sessions/{unlaunched.anchor_id}", json={"project_id": ""})
    assert response.status_code == 200, response.text
    with get_or_create_engine(unlaunched.stores.conversation.storage_location).begin() as db:
        db.execute(
            delete(SessionBindingRow).where(
                SessionBindingRow.workspace_id == WORKSPACE,
                SessionBindingRow.session_id == unlaunched.anchor_id,
            )
        )

    failure = _failed(await unlaunched.deliver(unlaunched.anchor_payload()))

    assert (failure.error_code, failure.retryable) == ("session.identity_conflict", False)
    anchor = unlaunched.conversation(unlaunched.anchor_id)
    # Not deleted and re-created: the row keeps its grant, and no binding is reserved.
    assert anchor is not None and anchor.project_id is None
    assert unlaunched.progress(unlaunched.anchor_id) is None
    assert unlaunched.children() == ([step_id] if with_step else [])


@pytest.mark.parametrize("use", ["child", "item"])
async def test_a_torn_row_that_was_used_is_never_deleted(
    coral: _Coral, host: _Host, runner: _Runner, monkeypatch: pytest.MonkeyPatch, use: str
) -> None:
    await coral.anchor()
    step_id = coral.step_id()
    store = coral.stores.conversation
    with monkeypatch.context() as crash:
        crash.setattr(store, "_session_immediate", _DiesOnUse(store._session_immediate))
        with pytest.raises(SimulatedCrash):
            await coral.deliver(coral.step_payload())
    if use == "child":
        store.create_conversation(kind="sub_agent", title="child", parent_conversation_id=step_id)
    else:
        store.append(
            step_id,
            [
                NewConversationItem(
                    type="message",
                    response_id="resp_1",
                    data=MessageData(role="user", content=[{"type": "input_text", "text": "hi"}]),
                )
            ],
        )

    failure = _failed(await coral.deliver(coral.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.identity_conflict", False)
    assert {"child": "children", "item": "items"}[use] in failure.message
    torn = coral.conversation(step_id)
    assert torn is not None and torn.host_id is None
    assert host.launches_for(step_id) == 0


@pytest.mark.parametrize("tamper", ["host", "owner"])
async def test_an_adopted_row_must_match_before_any_grant_or_launch(
    unlaunched: _Coral,
    launcher: _RecordingLauncher,
    host: _Host,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    await unlaunched.anchor()
    step_id = unlaunched.step_id()
    store = unlaunched.stores.conversation
    with monkeypatch.context() as crash:
        crash_around(crash, store, "create_conversation", when="after")
        with pytest.raises(SimulatedCrash):
            await unlaunched.deliver(unlaunched.step_payload())
    permission = unlaunched.stores.permission
    if tamper == "host":
        store.set_host_id(step_id, "e" * 32, workspace="/somewhere/else")
    else:
        permission.ensure_user("mallory@example.test")
        permission.grant("mallory@example.test", step_id, LEVEL_OWNER)

    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.identity_conflict", False)
    assert permission.get(RESERVED_USER_LOCAL, step_id) is None
    assert unlaunched.progress(step_id) == SessionBindingProgress.RESERVED
    assert launcher.calls == []


async def test_a_launch_that_finds_the_step_deleted_pauses_the_run(
    coral: _Coral, host: _Host, runner: _Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    await coral.anchor()
    step_id = coral.step_id()
    loop = asyncio.get_running_loop()
    store = coral.stores.conversation

    def delete_then_refuse(**_kwargs: object) -> object:
        # The owner deletes the step just as its launch is authorized.
        asyncio.run_coroutine_threadsafe(store.delete_conversation(step_id), loop).result(
            timeout=budget(10.0)
        )
        raise HTTPException(status_code=404, detail="session not found")

    monkeypatch.setattr(facade_module, "resolve_host_launch", delete_then_refuse)
    failure = _failed(await coral.deliver(coral.step_payload()))

    assert (failure.error_code, failure.retryable) == ("drift.session_deleted", False)
    [pause] = coral.drift_pauses()
    assert (pause["cause"], pause["session_id"]) == ("session_deleted", step_id)


async def test_an_anchor_deleted_while_its_step_row_is_written_pauses_the_run(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    await unlaunched.anchor()
    loop = asyncio.get_running_loop()
    store = unlaunched.stores.conversation
    real_reserve = unlaunched.bindings.reserve

    def reserve_then_delete_anchor(draft: Any) -> Any:
        binding = real_reserve(draft)
        if draft.role == "step":
            asyncio.run_coroutine_threadsafe(
                store.delete_conversation(unlaunched.anchor_id), loop
            ).result(timeout=budget(10.0))
        return binding

    monkeypatch.setattr(unlaunched.bindings, "reserve", reserve_then_delete_anchor)
    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    # The store refuses a child of a missing parent; the facade reports the anchor's drift.
    assert (failure.error_code, failure.retryable) == ("drift.anchor_deleted", False)
    assert unlaunched.conversation(unlaunched.step_id()) is None
    assert launcher.calls == []


async def test_a_step_archived_while_it_is_created_is_not_launched(
    unlaunched: _Coral, launcher: _RecordingLauncher, host: _Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    await unlaunched.anchor()
    real_announce = facade_module._announce_session_added

    def announce_then_archive(user_id: str | None, session_id: str) -> None:
        real_announce(user_id, session_id)
        if session_id == unlaunched.step_id():
            unlaunched.stores.conversation.update_conversation(session_id, archived=True)

    monkeypatch.setattr(facade_module, "_announce_session_added", announce_then_archive)
    failure = _failed(await unlaunched.deliver(unlaunched.step_payload()))

    assert (failure.error_code, failure.retryable) == ("drift.session_archived", False)
    assert launcher.calls == []
    assert unlaunched.progress(unlaunched.step_id()) == SessionBindingProgress.ROW_CREATED
