"""Tests for OmnigentRunScopeRunner and coral_lifespan server plugin integration."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from coral.bridge.bound_sessions import BoundSessions
from coral.bridge.codec import decode_entries
from coral.bridge.executors import (
    DECISION_THREAD_NAME,
    BoundedThreads,
    BridgeThreads,
    bridge_hold_policy,
)
from coral.bridge.mapping import RUN_RESYNC, TIMER, TURN_FACT
from coral.bridge.port import StoreDecisionPort
from coral.bridge.service import EngineBridge
from coral.db import WorkRow
from coral.db.enum_codecs import RunPauseReason, RunStatus, SessionBindingProgress, WorkStatus
from coral.db.migrate import ensure_coral_schema
from coral.model.ids import anchor_session_id
from coral.omni.policies.state import RunStatusCache
from coral.omni.protocols import CoralSessionError, SendReceipt, SessionCreateRequest, SessionRef
from coral.omni.server import OmnigentRunScopeRunner, coral_lifespan
from coral.omni.server import plugin as plugin_module
from coral.omni.server.dispatch import OmnigentSessionDispatch
from coral.omni.server.mutation_guard import MUTATION_GUARD, CoralMutationGuard
from coral.omni.server.sessions import RUN_ID_LABEL_KEY, OmnigentSessionFacade
from coral.omni.server.turn_facts import BoundSessionRefresher, TurnFactRecorder
from coral.omni.server.workspace_ops import OmnigentHostWorkspaceChannels
from coral.queue import executors as queue_executors
from coral.queue.executors import (
    EffectCompleted,
    EffectFailed,
    EffectOutcome,
    get_executor,
    get_registration,
    registered_executor_kinds,
)
from coral.queue.store import SqlAlchemyCoralQueueStore
from coral.slots.executors import CANCEL_SESSIONS, CLOSE_SLOT, CREATE_SESSION, SEND_INPUT
from coral.stores.protocols import RunStartSpec, Transition, WorkItemDraft
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.stores.session_bindings import SessionBindingDraft, SqlAlchemySessionBindingStore
from coral.tools import catalog as tool_catalog
from coral.tools.catalog import ENGINE_TOOLS, SUBMIT_HANDOFF
from coral.tools.replies import not_run_member
from coral.tools.schemas import ToolReply
from coral.workers.supervisor import WorkerSupervisor
from coral.workspace.executors import WORKSPACE_COMMIT, WORKSPACE_RESET, WORKSPACE_SALVAGE
from omnigent.db.account_authority import account_generation, current_account_user
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID, current_workspace_id
from omnigent.db.utils import _run_migrations as run_omni_migrations
from omnigent.db.utils import create_db_engine, get_or_create_engine
from omnigent.entities import Conversation
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.policies.types import EvaluationContext, PolicyResult
from omnigent.runtime.agent_cache import AgentCache
from omnigent.runtime.policies.builder import build_policy_engine
from omnigent.runtime.policies.required_providers import required_policies_apply
from omnigent.server import mutation_guards, session_live_state
from omnigent.server.app import create_app
from omnigent.server.host_registry import _expected_host_owner
from omnigent.server.mutation_guards import SESSION_UPDATE, MutationAttempt, check_mutation
from omnigent.server.routes._sessions import helpers as session_helpers
from omnigent.server.server_plugins import ServerServices
from omnigent.server.server_tools import ServerToolCall, server_tool
from omnigent.spec import AgentSpec
from omnigent.spec.types import Phase, PolicyAction
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.bridge._world import (
    USER,
    BindingFacade,
    World,
    activation_in,
    run_spec,
    start,
    start_without_engine,
)
from tests.coral.slots._close_fakes import FakeDispatch
from tests.coral.workspace._executor_fakes import (
    FakeHostChannel,
    add_slot,
    effect_context,
    start_run,
)
from tests.server.helpers import create_session_for_agent, create_test_agent
from tests.tools.test_extensions import installed_tool_providers

ENGINE_EFFECT_TYPES = frozenset(
    {
        CREATE_SESSION,
        SEND_INPUT,
        CLOSE_SLOT,
        CANCEL_SESSIONS,
        WORKSPACE_COMMIT,
        WORKSPACE_SALVAGE,
        WORKSPACE_RESET,
        TURN_FACT,
    }
)
# The bridge's own executors: they need only the Coral stores.
BRIDGE_EFFECT_TYPES = frozenset({TIMER, RUN_RESYNC})
# The status-edge observer, the confirmed-stop record's observer and the turn-fact recorder.
ENGINE_OBSERVERS = frozenset({"coral", "coral.confirmed_stops", "coral.turn_facts"})
NOTHING: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset())
ENGINE_TOOL_NAMES = frozenset(decl.name for decl in ENGINE_TOOLS)


def _engine_registrations() -> tuple[frozenset[str], frozenset[str]]:
    """The session engine's effect executors and status-edge observers registered now."""
    observers = frozenset(session_live_state._status_edge_observers) & ENGINE_OBSERVERS
    return registered_executor_kinds() & ENGINE_EFFECT_TYPES, observers


def _bridge_registrations() -> frozenset[str]:
    """The bridge's executors registered now."""
    return registered_executor_kinds() & BRIDGE_EFFECT_TYPES


def _engine_tools() -> frozenset[str]:
    """Coral's engine tools registered as server tools now."""
    return frozenset(name for name in ENGINE_TOOL_NAMES if server_tool(name) is not None)


def _coral_policies_registered() -> bool:
    """Whether Coral's required-policy provider claims a Coral bundle's sessions now."""
    return required_policies_apply(AgentSpec(spec_version=1, params={"coral": {}}), None)


def _coral_mutation_guard() -> object | None:
    """Coral's S53 mutation guard as registered now, if any."""
    return dict(mutation_guards._registered()).get(MUTATION_GUARD)


@dataclass
class _Server:
    """A real app with the stores the session engine needs, and its plugin services."""

    app: FastAPI
    services: ServerServices
    db_uri: str


@pytest.fixture
def no_engine_resync(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep the supervisor's resync off the test's runs.

    These tests start runs on the store alone, or time an engine start themselves; the
    resync would start or pause them (a run without a frozen config cannot be loaded).
    """
    monkeypatch.setattr(EngineBridge, "schedule_resync", lambda _bridge, _run: None)


@pytest.fixture
def server(db_uri: str, tmp_path: Path) -> _Server:
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
    )
    services = ServerServices(
        agent_store=agent,
        file_store=file,
        conversation_store=conversation,
        artifact_store=artifact,
        agent_cache=agent_cache,
        comment_store=None,
        policy_store=None,
        permission_store=None,
        scheduled_task_store=None,
        project_store=project,
        preference_store=None,
        host_store=host,
        account_store=None,
        auth_provider=None,
        runner_router=app.state.runner_router,
        host_registry=app.state.host_registry,
        tunnel_registry=app.state.tunnel_registry,
        server_config={},
        host_sharded=False,
    )
    return _Server(app=app, services=services, db_uri=db_uri)


async def test_omnigent_run_scope_runner_sets_all_three_ambient_scopes() -> None:
    """Verify OmnigentRunScopeRunner enters workspace, account_authority, and host_owner scopes."""
    runner = OmnigentRunScopeRunner()
    async with runner.run_scope(
        workspace_id=42,
        run_id="run_42",
        user_id="user_alice",
        account_generation="gen_99",
        host_id="host_1",
        owner_key="slot:1",
    ):
        assert current_workspace_id() == 42
        assert current_account_user() == "user_alice"
        assert account_generation("user_alice") == "gen_99"
        host_owner = _expected_host_owner.get()
        assert host_owner is not None
        assert host_owner.user_id == "user_alice"
        assert host_owner.generation == "gen_99"
        assert host_owner.workspace_id == 42


async def test_coral_lifespan_skips_in_memory_or_d1_and_boots_on_operational_db(
    tmp_path: Path,
) -> None:
    """Verify coral_lifespan skips non-shared :memory:/D1 and boots WorkerSupervisor on real DB."""
    app = FastAPI()

    # 1. Non-shared :memory: SQLite is skipped cleanly without starting a supervisor
    in_mem_services = cast(
        ServerServices,
        SimpleNamespace(
            host_sharded=False,
            conversation_store=SimpleNamespace(storage_location="sqlite:///:memory:"),
        ),
    )
    async with coral_lifespan(app, in_mem_services):
        assert not hasattr(app.state, "coral_worker_supervisor")
        assert _engine_registrations() == NOTHING

    # 2. Cloudflare D1 is skipped cleanly
    d1_services = cast(
        ServerServices,
        SimpleNamespace(
            host_sharded=False,
            conversation_store=SimpleNamespace(storage_location="cloudflare_d1://acct/db"),
        ),
    )
    async with coral_lifespan(app, d1_services):
        assert not hasattr(app.state, "coral_worker_supervisor")
        assert _engine_registrations() == NOTHING

    # 3. Host-sharded raises RuntimeError
    sharded_services = cast(
        ServerServices,
        SimpleNamespace(
            host_sharded=True,
            conversation_store=SimpleNamespace(storage_location=None),
        ),
    )
    with pytest.raises(RuntimeError, match="host_sharded=True"):
        async with coral_lifespan(app, sharded_services):
            pass

    # 4. File-backed operational SQLite DB runs ensure_coral_schema and starts WorkerSupervisor
    db_file = tmp_path / "operational.db"
    db_uri = f"sqlite:///{db_file}"
    engine = create_db_engine(db_uri)
    run_omni_migrations(engine, db_uri)
    engine.dispose()

    real_services: Any = SimpleNamespace(
        host_sharded=False,
        conversation_store=SimpleNamespace(storage_location=db_uri),
    )
    async with coral_lifespan(app, cast(ServerServices, real_services)):
        sup = app.state.coral_worker_supervisor
        assert sup is not None
        await sup.leader_ready_event.wait()
        assert sup.is_leader
        # Without the server's stores the session engine stays unwired.
        assert _engine_registrations() == NOTHING
    assert not sup.is_leader


async def test_coral_lifespan_registers_and_unregisters_engine_executors(
    server: _Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    at_stop: list[tuple[frozenset[str], frozenset[str]]] = []
    stop = WorkerSupervisor.stop

    async def recording_stop(supervisor: WorkerSupervisor) -> None:
        at_stop.append(_engine_registrations())
        await stop(supervisor)

    monkeypatch.setattr(WorkerSupervisor, "stop", recording_stop)
    assert _engine_registrations() == NOTHING
    # A second lifespan in the same process registers again without a conflict.
    for _ in range(2):
        async with coral_lifespan(server.app, server.services):
            assert _engine_registrations() == (ENGINE_EFFECT_TYPES, ENGINE_OBSERVERS)
            observers = session_live_state._status_edge_observers
            state = server.app.state
            assert observers["coral"] == state.coral_status_edges.observe
            assert observers["coral.confirmed_stops"] == state.coral_confirmed_stops.observe
            assert observers["coral.turn_facts"] == state.coral_turn_fact_recorder.observe
            # Only cancel_sessions runs for a run that already ended (cancel_run ends it).
            registrations = {kind: get_registration(kind) for kind in ENGINE_EFFECT_TYPES}
            assert {
                kind
                for kind, registration in registrations.items()
                if registration is not None and registration.runs_after_terminal
            } == {CANCEL_SESSIONS}
        assert _engine_registrations() == NOTHING
    # The supervisor stopped while every executor was still registered, so no
    # item can be claimed and find its executor missing.
    assert at_stop == [(ENGINE_EFFECT_TYPES, ENGINE_OBSERVERS)] * 2

    # An app without ``state`` (no server around it) wires nothing.
    async with coral_lifespan(cast(FastAPI, SimpleNamespace()), server.services):
        assert _engine_registrations() == NOTHING


async def test_a_second_concurrent_lifespan_raises_before_registering_anything(
    server: _Server,
) -> None:
    kinds = ENGINE_EFFECT_TYPES | BRIDGE_EFFECT_TYPES
    with installed_tool_providers():
        async with coral_lifespan(server.app, server.services):
            state = server.app.state
            first = (
                state.coral_engine_bridge,
                state.coral_worker_supervisor,
                state.coral_run_store,
            )
            executors = {kind: get_executor(kind) for kind in kinds}
            handler = server_tool(SUBMIT_HANDOFF.name)

            with pytest.raises(RuntimeError, match="already running in this process"):
                async with coral_lifespan(server.app, server.services):
                    pass

            # The first lifespan keeps every registration and its state.
            assert {kind: get_executor(kind) for kind in kinds} == executors
            assert session_live_state._status_edge_observers["coral"] == (
                state.coral_status_edges.observe
            )
            assert server_tool(SUBMIT_HANDOFF.name) is handler
            assert _coral_policies_registered()
            assert (
                state.coral_engine_bridge,
                state.coral_worker_supervisor,
                state.coral_run_store,
            ) == first
            await poll_until_async(first[1].leader_ready_event.is_set, timeout_s=budget(30))
        assert _engine_registrations() == NOTHING
        assert _bridge_registrations() == frozenset()
        assert _engine_tools() == frozenset()
        assert not _coral_policies_registered()
        assert _coral_mutation_guard() is None

        # Once the first exits, a lifespan starts again.
        async with coral_lifespan(server.app, server.services):
            assert _engine_registrations() == (ENGINE_EFFECT_TYPES, ENGINE_OBSERVERS)
            assert server.app.state.coral_engine_bridge is not first[0]
    assert _engine_registrations() == NOTHING


@pytest.mark.parametrize(
    ("server_config", "workers"),
    [({}, 4), ({"coral_drain_concurrency": 2}, 2), ({"coral_drain_concurrency": 16}, 16)],
)
async def test_the_lifespan_wires_the_bridge_into_the_supervisor_and_unwires_it_on_exit(
    server: _Server,
    monkeypatch: pytest.MonkeyPatch,
    server_config: dict[str, Any],
    workers: int,
) -> None:
    built: list[dict[str, Any]] = []

    class RecordingSupervisor(WorkerSupervisor):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            built.append(kwargs)
            super().__init__(*args, **kwargs)

    at_stop: list[frozenset[str]] = []
    stop = WorkerSupervisor.stop

    async def recording_stop(supervisor: WorkerSupervisor) -> None:
        at_stop.append(_bridge_registrations())
        await stop(supervisor)

    monkeypatch.setattr(plugin_module, "WorkerSupervisor", RecordingSupervisor)
    monkeypatch.setattr(WorkerSupervisor, "stop", recording_stop)

    services = dataclasses.replace(server.services, server_config=server_config)
    async with coral_lifespan(server.app, services):
        bridge = server.app.state.coral_engine_bridge
        assert isinstance(bridge, EngineBridge)
        assert bridge.run_store is server.app.state.coral_run_store
        assert _bridge_registrations() == BRIDGE_EFFECT_TYPES
        assert _engine_registrations() == (ENGINE_EFFECT_TYPES, ENGINE_OBSERVERS)
        [wiring] = built
        threads = wiring["on_finished"].__self__
        assert isinstance(threads, BridgeThreads) and threads.bridge is bridge
        assert wiring["on_finished"] == threads.feed
        assert wiring["run_reconciler"] == threads.schedule_resync
        assert wiring["hold_policy"] is bridge_hold_policy
        assert (wiring["drain_concurrency"], wiring["resync_interval_s"]) == (workers, 60)
        # Never fewer bridge threads than drain workers.
        assert threads.max_workers == max(8, workers)
        assert not threads.closed

    # The supervisor stopped first, so no timer or resync item found its executor missing.
    assert at_stop == [BRIDGE_EFFECT_TYPES]
    assert _bridge_registrations() == frozenset()
    assert threads.closed


@pytest.mark.parametrize("value", [0, 65, True, "4", 2.0])
async def test_a_drain_concurrency_outside_1_to_64_fails_the_start_and_wires_nothing(
    server: _Server, value: object
) -> None:
    services = dataclasses.replace(
        server.services, server_config={"coral_drain_concurrency": value}
    )

    with pytest.raises(ValueError, match="coral_drain_concurrency"):
        async with coral_lifespan(server.app, services):
            pass

    assert _engine_registrations() == NOTHING
    assert _bridge_registrations() == frozenset()
    # The process is free again: a lifespan with a valid config starts.
    async with coral_lifespan(server.app, server.services):
        assert _bridge_registrations() == BRIDGE_EFFECT_TYPES


def test_the_drain_concurrency_defaults_to_four() -> None:
    assert plugin_module.drain_concurrency(None) == 4
    assert plugin_module.drain_concurrency({}) == 4
    assert plugin_module.drain_concurrency({"coral_drain_concurrency": None}) == 4
    assert plugin_module.drain_concurrency({"coral_drain_concurrency": 64}) == 64


async def test_the_supervisor_starts_a_run_whose_engine_start_was_lost(server: _Server) -> None:
    """The startup sweep schedules the run's resync; the pool drains it on the bridge."""
    ensure_coral_schema(server.db_uri)
    world = World.sql(server.db_uri)
    run = start_without_engine(world, workspace_id=DEFAULT_WORKSPACE_ID, user=None)

    def started() -> bool:
        return bool(
            world.runs.read_engine_log(
                run.id, workspace_id=DEFAULT_WORKSPACE_ID, max_run_version=2**31
            )
        )

    async with coral_lifespan(server.app, server.services):
        await poll_until_async(started, timeout_s=budget(30))


@pytest.mark.parametrize("engine", ["wired", "unwired", "no_database"])
async def test_engine_tools_are_wired_with_the_decision_port_and_removed_on_exit(
    server: _Server, monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    assert tool_catalog.CATALOG == ENGINE_TOOLS
    services: Any = server.services
    if engine == "unwired":
        monkeypatch.delattr(server.app.state, "session_event_dispatch")
    elif engine == "no_database":
        services = SimpleNamespace(
            host_sharded=False,
            conversation_store=SimpleNamespace(storage_location="sqlite:///:memory:"),
        )
    call = ServerToolCall(
        session_id="session-1",
        name=SUBMIT_HANDOFF.name,
        arguments={},
        operation_id="op-1",
        runner_proven=True,
        actor=None,
    )

    with installed_tool_providers():
        async with coral_lifespan(server.app, cast(ServerServices, services)):
            wired = engine == "wired"
            assert _engine_registrations() == (
                (ENGINE_EFFECT_TYPES, ENGINE_OBSERVERS) if wired else NOTHING
            )
            if engine == "no_database":
                assert _engine_tools() == frozenset()
            else:
                # Registered with or without the session engine; the runner's prefixed name
                # finds the same handler.
                assert _engine_tools() == ENGINE_TOOL_NAMES
                handler = server_tool(SUBMIT_HANDOFF.name)
                assert handler is not None
                assert server_tool(f"mcp__omnigent__{SUBMIT_HANDOFF.name}") is handler
                # The call passes the port check and the binding lookup; an unbound session is
                # not a run member.
                result = await handler(call)
                assert not result.is_error
                assert ToolReply.from_json(result.text) == not_run_member()
    assert _engine_tools() == frozenset()


@pytest.mark.parametrize(
    "exit_while_deciding", [False, True], ids=["call_then_exit", "exit_mid_call"]
)
@pytest.mark.usefixtures("coral_policy_registry")
async def test_a_live_handoff_call_commits_on_a_run_the_supervisor_started(
    server: _Server, monkeypatch: pytest.MonkeyPatch, exit_while_deciding: bool
) -> None:
    """
    The supervisor creates the anchor and the step and sends the brief; the step hands off.

    This server has no host or runner for the step, so its create and its brief stop at the
    facade's and the dispatch's boundary; the anchor is created for real. A decision still
    running when the lifespan exits finishes on its thread, commits and answers.
    """
    ensure_coral_schema(server.db_uri)
    world = World.sql(server.db_uri)
    bindings = SqlAlchemySessionBindingStore(server.db_uri)
    sessions = FakeDispatch([], owner=USER)
    steps = BindingFacade(bindings=bindings, dispatch=sessions)
    anchors: list[SessionRef] = []
    create = OmnigentSessionFacade.create_session

    async def create_session(
        facade: OmnigentSessionFacade,
        request: SessionCreateRequest,
        *,
        ensure_lease: Callable[[], Awaitable[None]],
    ) -> SessionRef:
        if request.role == "step":
            return await steps.create_session(request, ensure_lease=ensure_lease)
        anchors.append(await create(facade, request, ensure_lease=ensure_lease))
        return anchors[-1]

    async def send_message(_dispatch: OmnigentSessionDispatch, **message: Any) -> SendReceipt:
        return await sessions.send_message(**message)

    monkeypatch.setattr(OmnigentSessionFacade, "create_session", create_session)
    monkeypatch.setattr(OmnigentSessionDispatch, "send_message", send_message)
    # Where the tool call's store reads and decisions run.
    deciding = threading.Event()
    threads_used: list[str] = []
    for owner, name in (
        (SqlAlchemySessionBindingStore, "find_by_session"),
        (StoreDecisionPort, "find_reply"),
        (StoreDecisionPort, "decide"),
    ):
        monkeypatch.setattr(
            owner, name, _thread_recording(getattr(owner, name), deciding, threads_used)
        )
    held, release = threading.Event(), threading.Event()
    if exit_while_deciding:
        decide = StoreDecisionPort.decide

        def held_decide(port: StoreDecisionPort, *args: Any, **kwargs: Any) -> ToolReply:
            held.set()
            assert release.wait(budget(30))
            return decide(port, *args, **kwargs)

        monkeypatch.setattr(StoreDecisionPort, "decide", held_decide)
    pools: list[BoundedThreads] = []
    # The engine tools registered when the decision pool closed.
    tools_at_close: list[frozenset[str]] = []

    class RecordingPool(BoundedThreads):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            pools.append(self)

        def close(self) -> None:
            tools_at_close.append(_engine_tools())
            super().close()

    monkeypatch.setattr(plugin_module, "BoundedThreads", RecordingPool)
    run = start(world, spec=run_spec(workspace_id=DEFAULT_WORKSPACE_ID))

    def briefed() -> bool:
        state = world.bridge.load(workspace_id=DEFAULT_WORKSPACE_ID, run_id=run.id).state
        return [slot.status for slot in state.slots] == ["working"]

    try:
        with installed_tool_providers():
            async with coral_lifespan(server.app, server.services):
                await poll_until_async(briefed, timeout_s=budget(30))
                [brief] = sessions.sends
                session_id = str(brief["session_id"])
                handler = server_tool(SUBMIT_HANDOFF.name)
                assert handler is not None
                deciding.set()
                call = asyncio.ensure_future(
                    handler(
                        ServerToolCall(
                            session_id=session_id,
                            name=SUBMIT_HANDOFF.name,
                            arguments={
                                "activation_id": activation_in(str(brief["text"])),
                                "status": "done",
                                "report": "Implemented the change.",
                            },
                            operation_id="op-1",
                            runner_proven=True,
                            actor=None,
                        )
                    )
                )
                if exit_while_deciding:
                    assert await asyncio.to_thread(held.wait, budget(30))
                else:
                    await call
                assert [pool.closed for pool in pools] == [False]
        assert [pool.closed for pool in pools] == [True]
        # The tools were unregistered first, so no new call reached the closing pool.
        assert tools_at_close == [frozenset()]
    finally:
        release.set()
    result = await call
    deciding.clear()

    assert not result.is_error
    assert ToolReply.from_json(result.text).accepted
    # The supervisor ran the anchor's create and the step's, as the run owner's agent.
    assert [anchor.session_id for anchor in anchors] == [
        anchor_session_id(DEFAULT_WORKSPACE_ID, run.id)
    ]
    [step] = steps.requests
    assert (step.engine_slot_id, step.user_id) == ("implement||:0", USER)
    agent = server.services.agent_store.get(step.agent_id or "")
    assert agent is not None and agent.created_by == USER
    # The handoff committed with the calling session as its actor.
    rows = world.runs.read_engine_log(
        run.id, workspace_id=DEFAULT_WORKSPACE_ID, max_run_version=2**31
    )
    entries = decode_entries(rows)
    assert [
        (entry.input.kind, row.actor_ref)
        for row, entry in zip(rows, entries, strict=True)
        if entry.input.kind.startswith("handoff_")
    ] == [("handoff_received", session_id), ("handoff_evaluated", session_id)]
    # The lookup, the reply check and the decision ran on the decision pool.
    assert threads_used and all(name.startswith(DECISION_THREAD_NAME) for name in threads_used)
    assert {"find_by_session", "find_reply", "decide"} == {
        name.split("@", 1)[1] for name in threads_used
    }


def _thread_recording(
    method: Callable[..., Any], recording: threading.Event, threads_used: list[str]
) -> Callable[..., Any]:
    """``method``, recording the thread it ran on while ``recording`` is set."""

    def recorded(*args: Any, **kwargs: Any) -> Any:
        if recording.is_set():
            threads_used.append(f"{threading.current_thread().name}@{method.__name__}")
        return method(*args, **kwargs)

    return recorded


@pytest.mark.parametrize("engine", ["wired", "unwired"])
async def test_the_policy_provider_and_its_commit_hook_last_as_long_as_the_lifespan(
    server: _Server, monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    hooks: list[str] = []
    register_post_commit = SqlAlchemyCoralRunStore.register_post_commit

    def recording_register(
        store: SqlAlchemyCoralRunStore, callback: Callable[[str, int], None]
    ) -> Callable[[], None]:
        unregister = register_post_commit(store, callback)
        hooks.append("registered")

        def recording_unregister() -> None:
            hooks.append("unregistered")
            unregister()

        return recording_unregister

    monkeypatch.setattr(SqlAlchemyCoralRunStore, "register_post_commit", recording_register)
    if engine == "unwired":
        monkeypatch.delattr(server.app.state, "session_event_dispatch")

    assert not _coral_policies_registered()
    assert _coral_mutation_guard() is None
    async with coral_lifespan(server.app, server.services):
        # Bound sessions are guarded whether or not the session engine is wired.
        assert _coral_policies_registered()
        assert isinstance(_coral_mutation_guard(), CoralMutationGuard)
        assert hooks == ["registered"]
    assert not _coral_policies_registered()
    assert _coral_mutation_guard() is None
    assert hooks == ["registered", "unregistered"]


async def test_the_mutation_guard_refuses_changes_to_a_bound_session_while_the_lifespan_runs(
    server: _Server,
) -> None:
    """The registered guard reads the real binding store in the request's workspace."""
    bindings = SqlAlchemySessionBindingStore(server.db_uri)
    conversations = cast(SqlAlchemyConversationStore, server.services.conversation_store)
    bound = conversations.create_conversation(labels={RUN_ID_LABEL_KEY: "run-1"})
    unbound = conversations.create_conversation(labels={RUN_ID_LABEL_KEY: "run-1"})
    bindings.reserve(
        SessionBindingDraft(
            workspace_id=DEFAULT_WORKSPACE_ID,
            session_id=bound.id,
            run_id="run-1",
            role="step",
            effect_key="run-1:2:create_session:work",
            slot_id="work||:0",
            slot_role="step_agent",
        )
    )

    def model_change(row: Conversation) -> MutationAttempt:
        return MutationAttempt(
            SESSION_UPDATE,
            session_id=row.id,
            conversation=row,
            fields=frozenset({"model_override"}),
        )

    async with coral_lifespan(server.app, server.services):
        with pytest.raises(OmnigentError) as refused:
            await check_mutation(model_change(bound))
        await check_mutation(model_change(unbound))
    assert refused.value.code == ErrorCode.CONFLICT
    assert f"Session {bound.id} is part of a Coral workflow run" in refused.value.message
    # Without the lifespan nothing is guarded.
    await check_mutation(model_change(bound))


@pytest.mark.usefixtures("no_engine_resync")
async def test_each_lifespan_guards_bound_sessions_through_its_own_run_store_only(
    server: _Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    heard: list[tuple[int, str]] = []
    invalidate = RunStatusCache.invalidate

    def recording_invalidate(cache: RunStatusCache, run_id: str, version: int) -> None:
        heard.append((id(cache), run_id))
        invalidate(cache, run_id, version)

    monkeypatch.setattr(RunStatusCache, "invalidate", recording_invalidate)
    bindings = SqlAlchemySessionBindingStore(server.db_uri)
    conversations = cast(SqlAlchemyConversationStore, server.services.conversation_store)
    spec = AgentSpec(spec_version=1, params={"coral": {}})

    async def bash(session_id: str) -> PolicyResult:
        engine = await asyncio.to_thread(
            build_policy_engine,
            spec=spec,
            conversation_id=session_id,
            conversation_store=conversations,
        )
        call = EvaluationContext(
            phase=Phase.TOOL_CALL, content={"name": "Bash", "arguments": {}}, tool_name="Bash"
        )
        return await engine.evaluate(call)

    def set_status(run_store: SqlAlchemyCoralRunStore, run_id: str, status: RunStatus) -> None:
        _, version = run_store.load_run_state(run_id, workspace_id=DEFAULT_WORKSPACE_ID)
        reason = int(RunPauseReason.USER) if status == RunStatus.PAUSED else None
        transition = Transition(
            status=int(status), pause_reason=reason, clear_pause_reason=reason is None
        )
        run_store.apply_transition(run_id, version, transition, workspace_id=DEFAULT_WORKSPACE_ID)

    earlier: list[tuple[SqlAlchemyCoralRunStore, str]] = []
    # Enter, exit and enter again: each lifespan's provider hears its own store's commits.
    for _ in range(2):
        async with coral_lifespan(server.app, server.services):
            run_store: SqlAlchemyCoralRunStore = server.app.state.coral_run_store
            run = run_store.start_run(
                RunStartSpec("wf", "v1", "Run", "", workspace_id=DEFAULT_WORKSPACE_ID)
            )
            set_status(run_store, run.id, RunStatus.RUNNING)
            session_id = conversations.create_conversation().id
            bindings.reserve(
                SessionBindingDraft(
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    session_id=session_id,
                    run_id=run.id,
                    role="step",
                    effect_key=f"{run.id}:2:create_session:work",
                    slot_id="work||:0",
                    slot_role="step_agent",
                )
            )
            assert (await bash(session_id)).action == PolicyAction.ALLOW
            heard.clear()
            set_status(run_store, run.id, RunStatus.PAUSED)
            # One cache heard the commit: no earlier lifespan's hook is still attached.
            assert [run_id for _, run_id in heard] == [run.id]
            denied = await bash(session_id)
            assert denied.deciding_policies == ["__coral_run_guard"]
            for old_store, old_run in earlier:
                set_status(old_store, old_run, RunStatus.CANCELLED)
            earlier.append((run_store, run.id))
            assert [run_id for _, run_id in heard] == [run.id]

        assert not _coral_policies_registered()
        heard.clear()
        set_status(run_store, run.id, RunStatus.RUNNING)
        # After exit the commit reaches no cache and the session gets no Coral policy.
        assert heard == []
        set_status(run_store, run.id, RunStatus.PAUSED)
        unguarded = await bash(session_id)
        assert unguarded.action == PolicyAction.ALLOW


@pytest.mark.usefixtures("no_engine_resync")
async def test_the_lifespan_records_the_turn_ends_of_bound_sessions_from_a_refreshed_index(
    server: _Server,
) -> None:
    await asyncio.to_thread(ensure_coral_schema, server.db_uri)
    run_store = SqlAlchemyCoralRunStore(server.db_uri)
    run = run_store.start_run(
        RunStartSpec("wf", "v1", "Run", "", workspace_id=DEFAULT_WORKSPACE_ID)
    )
    _, version = run_store.load_run_state(run.id, workspace_id=DEFAULT_WORKSPACE_ID)
    run_store.apply_transition(
        run.id,
        version,
        Transition(status=int(RunStatus.RUNNING)),
        workspace_id=DEFAULT_WORKSPACE_ID,
    )
    session_id = "f" * 32
    bindings = SqlAlchemySessionBindingStore(server.db_uri)
    bindings.reserve(
        SessionBindingDraft(
            workspace_id=DEFAULT_WORKSPACE_ID,
            session_id=session_id,
            run_id=run.id,
            role="step",
            effect_key=f"{run.id}:2:create_session:work||:0",
            slot_id="work||:0",
            slot_role="step_agent",
            session_generation=1,
        )
    )
    bindings.record_progress(DEFAULT_WORKSPACE_ID, session_id, SessionBindingProgress.ROW_CREATED)
    queue_store = SqlAlchemyCoralQueueStore(server.db_uri)

    async with coral_lifespan(server.app, server.services):
        state = server.app.state
        index = state.coral_bound_sessions
        recorder = state.coral_turn_fact_recorder
        refresher = state.coral_bound_session_refresher
        assert isinstance(index, BoundSessions) and isinstance(recorder, TurnFactRecorder)
        assert isinstance(refresher, BoundSessionRefresher) and not refresher.stopped
        assert state.coral_engine_bridge.bound_sessions is index
        # The index was filled at start, before any create fed it.
        bound = index.lookup(DEFAULT_WORKSPACE_ID, session_id)
        assert bound is not None and (bound.run_id, bound.engine_slot_id) == (run.id, "work||:0")
        session_live_state.notify_status_edge(
            session_live_state.SessionStatusEdge(
                session_id=session_id,
                status="idle",
                previous_status="running",
                turn_outcome="completed",
                workspace_id=DEFAULT_WORKSPACE_ID,
                observed_at_ms=1_700_000_000_000,
            )
        )
        await asyncio.to_thread(recorder.wait_idle)
        signal = WorkItemDraft.signal(
            run_id=run.id,
            idempotency_key=f"sig:{session_id}:unknown:idle:1700000000000",
            payload="",
        )
        assert recorder.written == 1

    assert refresher.stopped and recorder.closed
    assert "coral.turn_facts" not in session_live_state._status_edge_observers
    [row] = queue_store.get_work([signal.id], workspace_id=DEFAULT_WORKSPACE_ID)
    payload = json.loads(row.payload)
    assert (payload["effect_type"], payload["session_id"]) == ("turn_fact", session_id)


@pytest.mark.parametrize("missing", ["session_event_dispatch", "project_store"])
async def test_a_server_without_an_engine_input_wires_nothing(
    server: _Server, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    services = server.services
    if missing == "session_event_dispatch":
        monkeypatch.delattr(server.app.state, "session_event_dispatch")
    else:
        services = dataclasses.replace(services, project_store=None)
    async with coral_lifespan(server.app, services):
        assert _engine_registrations() == NOTHING
        # Only the session engine is left out; the bridge and the supervisor still run.
        assert _bridge_registrations() == BRIDGE_EFFECT_TYPES
        supervisor = server.app.state.coral_worker_supervisor
        await poll_until_async(supervisor.leader_ready_event.is_set, timeout_s=budget(30))


def _fail_lifespan_start(patch: pytest.MonkeyPatch, failing: str) -> None:
    """Make the lifespan's start fail at ``failing``."""
    if failing == "schema":

        def failing_schema(_db_uri: str) -> None:
            raise RuntimeError("schema check failed")

        patch.setattr(plugin_module, "ensure_coral_schema", failing_schema)
    elif failing == "executor":
        register_executor = queue_executors.register_executor
        registered: list[str] = []

        def failing_register_executor(effect_type: str, fn: Any, **kwargs: Any) -> None:
            if len(registered) == 3:
                raise RuntimeError("executor registration failed")
            register_executor(effect_type, fn, **kwargs)
            registered.append(effect_type)

        patch.setattr(queue_executors, "register_executor", failing_register_executor)
    elif failing == "observer":
        register = session_live_state.register_status_edge_observer

        def failing_register(name: str, fn: Any) -> Callable[[], None]:
            if name == "coral.confirmed_stops":
                raise RuntimeError("observer registration failed")
            return register(name, fn)

        patch.setattr(session_live_state, "register_status_edge_observer", failing_register)
    else:

        async def failing_start(_supervisor: WorkerSupervisor) -> None:
            raise RuntimeError("supervisor start failed")

        patch.setattr(WorkerSupervisor, "start", failing_start)


@pytest.mark.parametrize("failing", ["schema", "executor", "observer", "supervisor_start"])
async def test_a_lifespan_that_fails_part_way_unregisters_what_it_registered(
    server: _Server, failing: str
) -> None:
    with pytest.MonkeyPatch.context() as patch:
        _fail_lifespan_start(patch, failing)
        with installed_tool_providers(), pytest.raises(RuntimeError, match="failed"):
            async with coral_lifespan(server.app, server.services):
                pass

    assert _engine_registrations() == NOTHING
    assert _bridge_registrations() == frozenset()
    assert _engine_tools() == frozenset()
    assert not _coral_policies_registered()
    assert _coral_mutation_guard() is None
    # The failed start released the process: the next lifespan starts.
    async with coral_lifespan(server.app, server.services):
        assert _engine_registrations() == (ENGINE_EFFECT_TYPES, ENGINE_OBSERVERS)
        assert _bridge_registrations() == BRIDGE_EFFECT_TYPES


@pytest.mark.usefixtures("no_engine_resync")
async def test_item_claimed_during_exit_is_retried_not_failed(
    server: _Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_store = SqlAlchemyCoralRunStore(server.db_uri)
    queue = SqlAlchemyCoralQueueStore(server.db_uri)
    run = run_store.start_run(
        RunStartSpec(
            workflow_id="review",
            version_id="v1",
            title="Review the change",
            request_preview="",
            workspace_id=DEFAULT_WORKSPACE_ID,
        )
    )
    item = WorkItemDraft.effect(
        run_id=run.id,
        idempotency_key="cancel-unbound-slot",
        payload={
            "effect_type": CANCEL_SESSIONS,
            "effect_key": f"{run.id}:4:cancel_sessions:review/item-0/m0",
            "session_id": None,
        },
    )
    # The executor's first run read blocks, so the item is in flight when the lifespan exits.
    in_flight = threading.Event()
    release = threading.Event()
    load_run_state = SqlAlchemyCoralRunStore.load_run_state

    def held_first_load(store: SqlAlchemyCoralRunStore, run_id: str, **kwargs: Any) -> Any:
        if run_id == run.id and not in_flight.is_set():
            in_flight.set()
            release.wait(timeout=budget(30))
        return load_run_state(store, run_id, **kwargs)

    monkeypatch.setattr(SqlAlchemyCoralRunStore, "load_run_state", held_first_load)

    def row() -> WorkRow:
        with Session(get_or_create_engine(server.db_uri)) as session:
            found = session.execute(select(WorkRow).where(WorkRow.id == item.id)).scalar_one()
            session.expunge(found)
            return found

    try:
        async with coral_lifespan(server.app, server.services):
            queue.enqueue_work([item], workspace_id=DEFAULT_WORKSPACE_ID)
            await poll_until_async(in_flight.is_set, timeout_s=budget(30))
    finally:
        release.set()

    claimed = row()
    # The exit cancelled the in-flight try; the item keeps its lease instead of failing.
    assert (claimed.status, claimed.attempts, claimed.error_code) == (
        int(WorkStatus.CLAIMED),
        1,
        None,
    )
    assert _engine_registrations() == NOTHING

    # Once its lease expires the item is reclaimed, and the next server runs it.
    assert queue.reclaim_expired_work(now_fn=lambda: time.time() + 3600) == 1
    async with coral_lifespan(server.app, server.services):
        await poll_until_async(
            lambda: row().status == int(WorkStatus.SUCCEEDED), timeout_s=budget(30)
        )

    done = row()
    assert (done.attempts, done.error_code) == (2, None)
    assert done.result is not None and json.loads(done.result) == {"session_id": None}


@pytest.mark.usefixtures("no_engine_resync")
async def test_a_close_and_a_commit_share_one_stop_record(
    server: _Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A close's confirmed stop lets a later commit past its turn check, until the step runs."""
    workspace_id = DEFAULT_WORKSPACE_ID
    slot = "review/item-0/m0"
    host_id = uuid.uuid4().hex
    # The run worktree's host answers each op from canned replies.
    host_ops: list[str] = []
    host = FakeHostChannel(
        host_ops,
        {
            "fingerprint": {"level": "L1", "digest": "d" * 64, "head": "1" * 40, "dirty_count": 1},
            "head": {"head": "1" * 40, "branch": None, "merge_in_progress": False},
            "commit": {"commit": "2" * 40, "empty": False},
            "diff_stat": {"files_changed": 1, "insertions": 1, "deletions": 0, "paths": ["a"]},
        },
    )

    async def host_channel(*_args: object, **_scope: object) -> FakeHostChannel:
        return host

    monkeypatch.setattr(OmnigentHostWorkspaceChannels, "channel", host_channel)
    run_store = SqlAlchemyCoralRunStore(server.db_uri)
    run = start_run(
        run_store,
        workspace_id=workspace_id,
        user_id=None,
        account_generation=None,
        host_id=host_id,
        repo_path="/work/repo",
        worktree_path="/work/repo-worktrees/coral-run",
    )
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        agent = await create_test_agent(client)
        session_id = await create_session_for_agent(client, agent["id"])
    bindings = SqlAlchemySessionBindingStore(server.db_uri)
    bindings.reserve(
        SessionBindingDraft(
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=run.id,
            role="step",
            effect_key=f"{run.id}:2:create_session:{slot}",
            slot_id=slot,
            slot_role="step_agent",
            host_id=host_id,
        )
    )
    for progress in (SessionBindingProgress.ROW_CREATED, SessionBindingProgress.INITIALIZED):
        bindings.record_progress(workspace_id, session_id, progress)

    async def deliver(effect_type: str, seq: int, **fields: object) -> EffectOutcome:
        executor = get_executor(effect_type)
        assert executor is not None
        payload = {
            "effect_type": effect_type,
            "effect_key": f"{run.id}:{seq}:{effect_type}:{slot}",
            "session_id": session_id,
            **fields,
        }
        return await executor(
            effect_context(workspace_id=workspace_id, run_id=run.id, payload=payload)
        )

    commit = {"message": "Review: done", "attempt_id": "attempt-1"}
    try:
        # The step's turn has ended.
        session_helpers._publish_status(session_id, "idle", persist_live_status=False)
        add_slot(run_store, run, session_id=session_id)
        async with coral_lifespan(server.app, server.services):
            closed = await deliver(CLOSE_SLOT, 5)
            after_close = await deliver(WORKSPACE_COMMIT, 6, **commit)
            # The session ran again: the record's observer drops the stop.
            session_helpers._publish_status(session_id, "running", persist_live_status=False)
            session_helpers._publish_status(session_id, "idle", persist_live_status=False)
            after_rerun = await deliver(WORKSPACE_COMMIT, 7, **commit)
    finally:
        session_helpers._session_status_cache.pop(session_id, None)
        session_helpers._session_active_response_cache.pop(session_id, None)

    assert isinstance(closed, EffectCompleted) and closed.result is not None
    assert closed.result["commit"] == "2" * 40
    # The close's own stop let the later commit past its turn check.
    assert isinstance(after_close, EffectCompleted), after_close
    assert host_ops.count("commit") == 2
    assert isinstance(after_rerun, EffectFailed)
    assert (after_rerun.error_code, after_rerun.retryable) == ("session.turn_state_unknown", True)


@pytest.mark.usefixtures("no_engine_resync")
async def test_an_anchor_bound_send_stops_the_anchor_runner_through_the_lifespans_dispatch(
    server: _Server, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The drift pause's stop reaches the dispatch the lifespan built, which holds the pauser."""
    stops: list[tuple[str, str | None]] = []
    real_stop = OmnigentSessionDispatch.stop

    async def recording_stop(
        dispatch: OmnigentSessionDispatch, *, session_id: str, user_id: str | None
    ) -> None:
        stops.append((session_id, user_id))
        await real_stop(dispatch, session_id=session_id, user_id=user_id)

    monkeypatch.setattr(OmnigentSessionDispatch, "stop", recording_stop)
    workspace_id = DEFAULT_WORKSPACE_ID
    run_store = SqlAlchemyCoralRunStore(server.db_uri)
    # An engine run whose start has not committed: the drift pause starts it first.
    ensure_coral_schema(server.db_uri)
    run = start_without_engine(World.sql(server.db_uri), workspace_id=workspace_id, user=None)
    # Someone attached a runner to the run's anchor.
    anchor = anchor_session_id(workspace_id, run.id)
    server.services.conversation_store.create_conversation(
        conversation_id=anchor, runner_id="runner-on-anchor"
    )
    bindings = SqlAlchemySessionBindingStore(server.db_uri)
    bindings.reserve(
        SessionBindingDraft(
            workspace_id=workspace_id,
            session_id=anchor,
            run_id=run.id,
            role="anchor",
            effect_key=f"{run.id}:0:create_session:anchor",
        )
    )
    bindings.record_progress(workspace_id, anchor, SessionBindingProgress.ROW_CREATED)

    with caplog.at_level(logging.WARNING, logger="coral.recovery.drift"):
        async with coral_lifespan(server.app, server.services):
            dispatch = server.app.state.coral_session_dispatch
            for attempt in range(2):
                with pytest.raises(CoralSessionError) as refused:
                    await dispatch.send_message(
                        workspace_id=workspace_id,
                        run_id=run.id,
                        session_id=uuid.uuid4().hex,
                        user_id=None,
                        stable_id=f"brief-{attempt}",
                        text="Review the parser.",
                    )
                assert refused.value.code == "drift.anchor_bound"

    # Each detection stopped the anchor, as the run owner, and the stop went through.
    assert stops == [(anchor, None)] * 2
    assert [r for r in caplog.records if r.name == "coral.recovery.drift"] == []
    stored = run_store.get_run(run.id, workspace_id=workspace_id)
    assert stored is not None
    assert (stored.status, stored.pause_reason) == (RunStatus.PAUSED, RunPauseReason.DRIFT)
    # The pause went through the engine: its state is paused for the same drift.
    state = World.sql(server.db_uri).bridge.load(workspace_id=workspace_id, run_id=run.id).state
    assert [(cause.reason, cause.detail) for cause in state.causes] == [("drift", "anchor_bound")]
