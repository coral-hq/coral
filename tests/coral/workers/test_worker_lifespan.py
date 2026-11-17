"""Tests for OmnigentRunScopeRunner and coral_lifespan server plugin integration."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from coral.db import WorkRow
from coral.db.enum_codecs import RunPauseReason, RunStatus, SessionBindingProgress, WorkStatus
from coral.omni.policies.state import RunStatusCache
from coral.omni.server import OmnigentRunScopeRunner, coral_lifespan
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
from coral.workers.supervisor import WorkerSupervisor
from coral.workspace.executors import WORKSPACE_COMMIT, WORKSPACE_RESET, WORKSPACE_SALVAGE
from omnigent.db.account_authority import account_generation, current_account_user
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID, current_workspace_id
from omnigent.db.utils import _run_migrations as run_omni_migrations
from omnigent.db.utils import create_db_engine, get_or_create_engine
from omnigent.policies.types import EvaluationContext, PolicyResult
from omnigent.runtime.agent_cache import AgentCache
from omnigent.runtime.policies.builder import build_policy_engine
from omnigent.runtime.policies.required_providers import required_policies_apply
from omnigent.server import session_live_state
from omnigent.server.app import create_app
from omnigent.server.host_registry import _expected_host_owner
from omnigent.server.routes._sessions import helpers as session_helpers
from omnigent.server.server_plugins import ServerServices
from omnigent.server.server_tools import ServerToolCall, ServerToolResult, server_tool
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
    }
)
# The status-edge observer and the confirmed-stop record's observer.
ENGINE_OBSERVERS = frozenset({"coral", "coral.confirmed_stops"})
NOTHING: tuple[frozenset[str], frozenset[str]] = (frozenset(), frozenset())
ENGINE_TOOL_NAMES = frozenset(decl.name for decl in ENGINE_TOOLS)


def _engine_registrations() -> tuple[frozenset[str], frozenset[str]]:
    """The session engine's effect executors and status-edge observers registered now."""
    observers = frozenset(session_live_state._status_edge_observers) & ENGINE_OBSERVERS
    return registered_executor_kinds() & ENGINE_EFFECT_TYPES, observers


def _engine_tools() -> frozenset[str]:
    """Coral's engine tools registered as server tools now."""
    return frozenset(name for name in ENGINE_TOOL_NAMES if server_tool(name) is not None)


def _coral_policies_registered() -> bool:
    """Whether Coral's required-policy provider claims a Coral bundle's sessions now."""
    return required_policies_apply(AgentSpec(spec_version=1, params={"coral": {}}), None)


@dataclass
class _Server:
    """A real app with the stores the session engine needs, and its plugin services."""

    app: FastAPI
    services: ServerServices
    db_uri: str


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


async def test_an_overlapping_lifespan_takes_over_and_outlives_the_earlier_exit(
    server: _Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool_catalog, "CATALOG", ENGINE_TOOLS)
    with installed_tool_providers():
        async with AsyncExitStack() as later:
            async with coral_lifespan(server.app, server.services):
                # Entered while the first still runs: it replaces the registrations, no conflict.
                await later.enter_async_context(coral_lifespan(server.app, server.services))
                edges = server.app.state.coral_status_edges
                handler = server_tool(SUBMIT_HANDOFF.name)
            # The earlier exit removes only its own registrations.
            assert _engine_registrations() == (ENGINE_EFFECT_TYPES, ENGINE_OBSERVERS)
            assert session_live_state._status_edge_observers["coral"] == edges.observe
            assert _engine_tools() == ENGINE_TOOL_NAMES
            assert server_tool(SUBMIT_HANDOFF.name) is handler
            assert _coral_policies_registered()
    assert _engine_registrations() == NOTHING
    assert _engine_tools() == frozenset()
    assert not _coral_policies_registered()


@pytest.mark.parametrize("engine", ["wired", "unwired"])
async def test_the_production_catalog_registers_no_engine_tool(
    server: _Server, monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    assert tool_catalog.CATALOG == ()
    if engine == "unwired":
        monkeypatch.delattr(server.app.state, "session_event_dispatch")
    async with coral_lifespan(server.app, server.services):
        assert _engine_registrations() == (
            (ENGINE_EFFECT_TYPES, ENGINE_OBSERVERS) if engine == "wired" else NOTHING
        )
        assert _engine_tools() == frozenset()
        assert all(server_tool(f"mcp__omnigent__{name}") is None for name in ENGINE_TOOL_NAMES)


@pytest.mark.parametrize("engine", ["wired", "unwired", "no_database"])
async def test_engine_tools_are_wired_without_the_session_engine_and_removed_on_exit(
    server: _Server, monkeypatch: pytest.MonkeyPatch, engine: str
) -> None:
    # A catalog that lists the tools; without a decision port each answers "not running".
    monkeypatch.setattr(tool_catalog, "CATALOG", ENGINE_TOOLS)
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
                assert _engine_tools() == ENGINE_TOOL_NAMES
                handler = server_tool(SUBMIT_HANDOFF.name)
                assert handler is not None
                assert await handler(call) == ServerToolResult(
                    "Coral's workflow engine is not running on this server", is_error=True
                )
    assert _engine_tools() == frozenset()


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
    async with coral_lifespan(server.app, server.services):
        # Bound sessions are guarded whether or not the session engine is wired.
        assert _coral_policies_registered()
        assert hooks == ["registered"]
    assert not _coral_policies_registered()
    assert hooks == ["registered", "unregistered"]


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
        # Only the session engine is left out; the supervisor still runs.
        supervisor = server.app.state.coral_worker_supervisor
        await poll_until_async(supervisor.leader_ready_event.is_set, timeout_s=budget(30))


@pytest.mark.parametrize("failing", ["executor", "observer", "supervisor_start"])
async def test_a_lifespan_that_fails_part_way_unregisters_what_it_registered(
    server: _Server, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    monkeypatch.setattr(tool_catalog, "CATALOG", ENGINE_TOOLS)
    if failing == "executor":
        register_executor = queue_executors.register_executor
        registered: list[str] = []

        def failing_register_executor(effect_type: str, fn: Any, **kwargs: Any) -> None:
            if len(registered) == 3:
                raise RuntimeError("executor registration failed")
            register_executor(effect_type, fn, **kwargs)
            registered.append(effect_type)

        monkeypatch.setattr(queue_executors, "register_executor", failing_register_executor)
    elif failing == "observer":
        register = session_live_state.register_status_edge_observer

        def failing_register(name: str, fn: Any) -> Callable[[], None]:
            if name == "coral.confirmed_stops":
                raise RuntimeError("observer registration failed")
            return register(name, fn)

        monkeypatch.setattr(session_live_state, "register_status_edge_observer", failing_register)
    else:

        async def failing_start(_supervisor: WorkerSupervisor) -> None:
            raise RuntimeError("supervisor start failed")

        monkeypatch.setattr(WorkerSupervisor, "start", failing_start)

    with installed_tool_providers(), pytest.raises(RuntimeError, match="failed"):
        async with coral_lifespan(server.app, server.services):
            pass

    assert _engine_registrations() == NOTHING
    assert _engine_tools() == frozenset()
    assert not _coral_policies_registered()


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
