"""Coral server plugin implementation."""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy import Engine, create_engine

from coral.api.info import create_info_router
from coral.api.sub_features import resolve_sub_features
from coral.api.workflows import create_workflows_router
from coral.db.migrate import ensure_coral_schema
from coral.db.models_workflows import CoralBase
from coral.omni.protocols import RunScopeRunner
from coral.omni.server.scopes import OmnigentRunScopeRunner
from coral.queue.store import SqlAlchemyCoralQueueStore
from coral.stores.protocols import RunStore
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.stores.session_bindings import FreshBindingLookup, SqlAlchemySessionBindingStore
from coral.stores.workflows import SqlWorkflowDefinitionStore
from coral.workers.supervisor import WorkerSupervisor
from omnigent.process_logging import data_dir
from omnigent.server.server_plugins import ServerPluginRegistration, ServerServices

_logger = logging.getLogger(__name__)

# Workspaces are not modelled yet, so every request shares one workflow library.
_SINGLE_WORKSPACE_ID = 0
_CORAL_DB_FILENAME = "coral.db"
# Status-edge observer names: watched sessions' edges, and the confirmed-stop record.
STATUS_EDGE_OBSERVER = "coral"
CONFIRMED_STOPS_OBSERVER = "coral.confirmed_stops"
# The name Coral's policies for bound sessions are registered under (S52).
REQUIRED_POLICY_PROVIDER = "coral"
# The server stores the session engine builds on; anchors need the project store.
_ENGINE_SERVICES = (
    "agent_store",
    "agent_cache",
    "artifact_store",
    "host_store",
    "host_registry",
    "project_store",
    "runner_router",
)


def _single_workspace_id() -> int:
    return _SINGLE_WORKSPACE_ID


def _create_workflow_engine() -> Engine:
    """Open the SQLite file next to the Omnigent data and ensure the slim table exists."""
    data_path = data_dir()
    data_path.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data_path / _CORAL_DB_FILENAME}")
    CoralBase.metadata.create_all(engine)
    return engine


def _is_usable_operational_db_uri(db_uri: str | None) -> bool:
    """Return True when db_uri is a persistent/shared operational DB suitable for Coral."""
    if not db_uri or not isinstance(db_uri, str):
        return False
    stripped = db_uri.strip()
    if not stripped or "cloudflare_d1" in stripped:
        return False
    if stripped in {"sqlite://", "sqlite:///:memory:"}:
        return False
    return not (":memory:" in stripped and "cache=shared" not in stripped)


def _missing_engine_input(app: Any, services: ServerServices) -> str | None:
    """The first server input the session engine needs that is absent, else ``None``."""
    state = getattr(app, "state", None)
    if state is None or getattr(state, "session_event_dispatch", None) is None:
        return "app.state.session_event_dispatch"
    for name in ("conversation_store", *_ENGINE_SERVICES):
        if getattr(services, name, None) is None:
            return f"services.{name}"
    return None


def _wire_guards(
    *,
    run_store: RunStore,
    bindings: FreshBindingLookup,
    session_cap_usd: float,
    stack: AsyncExitStack,
) -> None:
    """
    Register what protects bound sessions, whether or not the session engine is wired.

    The engine tools register from the production catalog with no decision
    port: nothing while the catalog is empty, and once it lists a tool each
    call answers that the engine is not running. They read bindings fresh.
    Coral's required-policy provider reads them through a cache of found rows
    and reads run status through a cache each run-store commit clears. Its cost
    backstop pauses a run through ``run_store`` once a session spends
    ``session_cap_usd``. The S53 mutation guard reads the same cache of found
    rows and refuses clients' changes to bound sessions and engine agents.
    Every registration's undo goes on ``stack``.
    """
    from coral.omni.policies.bindings_cache import CachedBindingLookup
    from coral.omni.policies.cost_backstop import install_budget_pauser
    from coral.omni.policies.provider import CoralPolicyProvider
    from coral.omni.policies.state import RunStatusCache
    from coral.omni.server.mutation_guard import MUTATION_GUARD, CoralMutationGuard
    from coral.omni.server.tool_bridge import register_engine_tools
    from coral.recovery.pause import pause_run_for_session_cap
    from coral.tools.catalog import CATALOG
    from omnigent.runtime.policies.required_providers import register_required_policy_provider
    from omnigent.server.mutation_guards import register_mutation_guard

    register_engine_tools(catalog=CATALOG, port=None, bindings=bindings, stack=stack)
    statuses = RunStatusCache(run_store)
    stack.callback(run_store.register_post_commit(statuses.invalidate))
    stack.callback(install_budget_pauser(functools.partial(pause_run_for_session_cap, run_store)))
    # One cache of found bindings for every guard that classifies sessions.
    found_bindings = CachedBindingLookup(bindings)
    provider = CoralPolicyProvider(
        bindings=found_bindings, statuses=statuses, session_cap_usd=session_cap_usd
    )
    stack.callback(register_required_policy_provider(REQUIRED_POLICY_PROVIDER, provider))
    stack.callback(register_mutation_guard(MUTATION_GUARD, CoralMutationGuard(found_bindings)))


def _wire_session_engine(
    app: Any,
    services: ServerServices,
    *,
    db_uri: str,
    run_store: RunStore,
    bindings: SqlAlchemySessionBindingStore,
    scope_runner: RunScopeRunner,
    stack: AsyncExitStack,
) -> None:
    """
    Build the session engine and register its seven executors, then its status-edge observers.

    Each registration pushes its own unregister onto ``stack`` at once, so a
    failure part-way leaves nothing behind. One lifespan per process: a second
    one entered while the first runs takes the registrations over at once (the
    first's watches and stop record stop seeing edges), and whichever exits
    first removes only its own registrations, so an inner exit leaves the outer
    lifespan with none.
    """
    from coral.omni.server.dispatch import OmnigentSessionDispatch
    from coral.omni.server.sessions import OmnigentSessionFacade
    from coral.omni.server.status_edges import CoralStatusEdges
    from coral.omni.server.workspace_ops import OmnigentHostWorkspaceChannels
    from coral.queue.executors import EffectExecutor, register_executor, unregister_executor
    from coral.recovery.drift import DriftPauser, DriftPreSendHook
    from coral.slots.close import ConfirmedStops, StopConfirmedTurnEnd
    from coral.slots.executors import (
        CANCEL_SESSIONS,
        CLOSE_SLOT,
        CREATE_SESSION,
        SEND_INPUT,
        cancel_sessions_executor,
        close_slot_executor,
        create_session_executor,
        send_input_executor,
    )
    from coral.stores.stable_ids import SqlAlchemyStableIdStore
    from coral.stores.workspace_op_intents import SqlAlchemyWorkspaceOpIntentStore
    from coral.workspace.executors import (
        WORKSPACE_COMMIT,
        WORKSPACE_RESET,
        WORKSPACE_SALVAGE,
        commit_executor,
        reset_executor,
        salvage_executor,
    )
    from omnigent.server.session_live_state import register_status_edge_observer

    host_store = services.host_store
    assert host_store is not None  # checked by _missing_engine_input
    stable_ids = SqlAlchemyStableIdStore(db_uri)
    intents = SqlAlchemyWorkspaceOpIntentStore(db_uri)
    pauser = DriftPauser(run_store)
    facade = OmnigentSessionFacade(app, services, bindings)
    dispatch = OmnigentSessionDispatch(
        app,
        services.conversation_store,
        services.runner_router,
        pre_send_hooks=(DriftPreSendHook(facade, bindings, pauser),),
    )
    channels = OmnigentHostWorkspaceChannels(
        host_registry=services.host_registry, host_store=host_store
    )
    edges = CoralStatusEdges(asyncio.get_running_loop())
    # One record: the close writes each confirmed stop, workspace.commit reads it.
    stops = ConfirmedStops()
    executors: dict[str, EffectExecutor] = {
        CREATE_SESSION: create_session_executor(facade, run_store, pauser, scope_runner),
        SEND_INPUT: send_input_executor(dispatch, stable_ids, bindings, run_store, scope_runner),
        CLOSE_SLOT: close_slot_executor(
            dispatch,
            edges,
            channels,
            intents,
            stable_ids,
            bindings,
            run_store,
            scope_runner,
            stops=stops,
        ),
        CANCEL_SESSIONS: cancel_sessions_executor(
            dispatch, edges, bindings, run_store, scope_runner
        ),
        WORKSPACE_COMMIT: commit_executor(
            channels,
            intents,
            bindings,
            run_store,
            scope_runner,
            turn_ended=StopConfirmedTurnEnd(dispatch, stops),
        ),
        WORKSPACE_SALVAGE: salvage_executor(channels, run_store, scope_runner),
        WORKSPACE_RESET: reset_executor(channels, run_store, scope_runner),
    }
    for effect_type, executor in executors.items():
        # A cancelled run is finished when its cancel_sessions items are claimed.
        register_executor(
            effect_type,
            executor,
            replace=True,
            runs_after_terminal=effect_type == CANCEL_SESSIONS,
        )
        stack.callback(unregister_executor, effect_type, executor)
    stack.callback(register_status_edge_observer(STATUS_EDGE_OBSERVER, edges.observe))
    stack.callback(register_status_edge_observer(CONFIRMED_STOPS_OBSERVER, stops.observe))
    app.state.coral_session_facade = facade
    app.state.coral_session_dispatch = dispatch
    app.state.coral_status_edges = edges
    app.state.coral_confirmed_stops = stops


@asynccontextmanager
async def coral_lifespan(
    app: FastAPI,
    services: ServerServices,
) -> AsyncIterator[None]:
    """
    Run Coral's startup migration check, worker supervisor, and reverse-order shutdown.

    On a usable operational database the guards for bound sessions are
    registered, and with the server's stores present also the session engine's
    executors and status-edge observers, all before the supervisor starts. Both
    share one binding store. Nothing enqueues engine effects yet. Exit stops the
    supervisor first, so no item is claimed while its executor is missing (an
    item in flight keeps its lease and is reclaimed), then unregisters in
    reverse order, also after a failed start. An invalid per-session cost cap
    aborts startup before anything runs.
    """
    from coral.omni.policies.cost_backstop import resolve_session_cap_usd

    if services.host_sharded:
        raise RuntimeError("Coral server plugin does not support host_sharded=True")
    session_cap_usd = resolve_session_cap_usd(getattr(services, "server_config", None))

    conv_store = getattr(services, "conversation_store", None)
    storage_location: str | None = getattr(conv_store, "storage_location", None)

    async with AsyncExitStack() as stack:
        if _is_usable_operational_db_uri(storage_location):
            assert storage_location is not None
            await asyncio.to_thread(ensure_coral_schema, storage_location)
            run_store = SqlAlchemyCoralRunStore(storage_location)
            queue_store = SqlAlchemyCoralQueueStore(storage_location)
            scope_runner = OmnigentRunScopeRunner()
            supervisor = WorkerSupervisor(
                run_store,
                queue_store,
                scope_runner=scope_runner,
            )
            if hasattr(app, "state"):
                app.state.coral_run_store = run_store
                app.state.coral_queue_store = queue_store
                app.state.coral_worker_supervisor = supervisor
            bindings = SqlAlchemySessionBindingStore(storage_location)
            _wire_guards(
                run_store=run_store,
                bindings=bindings,
                session_cap_usd=session_cap_usd,
                stack=stack,
            )
            missing = _missing_engine_input(app, services)
            if missing is None:
                _wire_session_engine(
                    app,
                    services,
                    db_uri=storage_location,
                    run_store=run_store,
                    bindings=bindings,
                    scope_runner=scope_runner,
                    stack=stack,
                )
            else:
                # Engine effects would then fail permanently as ``executor.missing``.
                _logger.warning("Coral session engine not wired: %s is missing", missing)
            # Pushed last, so it runs first on exit.
            stack.push_async_callback(supervisor.stop)
            await supervisor.start()
        yield


def register(services: ServerServices) -> ServerPluginRegistration:
    """Register Coral routers, policy modules, and lifespan hooks."""
    if services.host_sharded:
        raise RuntimeError("Coral server plugin does not support host_sharded=True")

    sub_features = resolve_sub_features(services.server_config)
    info_router = create_info_router(sub_features=sub_features)
    engine = _create_workflow_engine()
    workflows_router = create_workflows_router(
        SqlWorkflowDefinitionStore(engine),
        workspace_id_dependency=_single_workspace_id,
    )

    @asynccontextmanager
    async def workflow_engine_lifespan(
        _app: FastAPI,
        _services: ServerServices,
    ) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()

    return ServerPluginRegistration(
        routers=((info_router, "", ["coral"]), (workflows_router, "/v1/coral", ["coral"])),
        lifespan_hooks=(coral_lifespan, workflow_engine_lifespan),
        policy_modules=("coral.omni.policies.hygiene", "coral.omni.policies.guards"),
    )
