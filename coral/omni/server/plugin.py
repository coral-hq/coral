"""Coral server plugin implementation."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, FastAPI
from sqlalchemy import Engine, create_engine

from coral.api.inbox import create_inbox_router
from coral.api.info import create_info_router
from coral.api.run_service import API_THREAD_NAME, API_THREADS, InFlight, RunsApi
from coral.api.runs import create_runs_router
from coral.api.spend import SPEND_THREAD_NAME, SPEND_THREADS, SpendCache
from coral.api.stream import STREAM_THREAD_NAME, STREAM_THREADS, RunStreamHub
from coral.api.sub_features import resolve_sub_features
from coral.api.workflows import create_workflows_router
from coral.bridge.bound_sessions import BoundSessions
from coral.bridge.config import RESYNC_INTERVAL_S
from coral.bridge.executors import (
    BRIDGE_THREADS,
    DECISION_THREAD_NAME,
    DECISION_THREADS,
    BoundedThreads,
    BridgeThreads,
    bridge_hold_policy,
)
from coral.bridge.port import StoreDecisionPort
from coral.bridge.service import EngineBridge
from coral.db.migrate import ensure_coral_schema
from coral.db.models_workflows import CoralBase
from coral.gates.republish import GateRepublisher
from coral.omni.protocols import GatePublisher, RunScopeRunner
from coral.omni.server.access import account_still_valid, request_viewer
from coral.omni.server.observations import ChannelsRef, EvidenceChecker
from coral.omni.server.scopes import OmnigentRunScopeRunner
from coral.omni.server.usage import OmnigentRunSpend
from coral.queue.executors import EffectExecutor
from coral.queue.store import SqlAlchemyCoralQueueStore
from coral.stores.protocols import QueueStore, RunStore
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.stores.session_bindings import FreshBindingLookup, SqlAlchemySessionBindingStore
from coral.stores.workflow_versions import SqlAlchemyWorkflowVersionStore
from coral.stores.workflows import SqlWorkflowDefinitionStore, WorkflowDefinitionStore
from coral.tools.dispatch import ThreadRunner
from coral.tools.port import RunDecisionPort
from coral.workers.supervisor import MAX_DRAIN_CONCURRENCY, WorkerSupervisor
from omnigent.db.db_models import current_workspace_id
from omnigent.process_logging import data_dir
from omnigent.server.server_plugins import ServerPluginRegistration, ServerServices

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from coral.api.run_service import HostConnector
    from coral.gates.verdict import GateAnswers
    from coral.omni.server.gates import GateAnswering, LocalGatePrompts
    from coral.omni.server.turn_facts import BoundSessionRefresher
    from omnigent.server.auth import AuthProvider

_logger = logging.getLogger(__name__)

# A router, the prefix it is mounted under, and its OpenAPI tags.
RouterSpec = tuple[APIRouter, str, list[str]]
CORAL_API_PREFIX = "/v1/coral"
_CORAL_DB_FILENAME = "coral.db"
# The task that withdraws this process's stale gate prompts.
GATE_SWEEP_TASK = "coral-gate-prompt-sweep"
# Status-edge observer names: watched sessions' edges, and the confirmed-stop record.
STATUS_EDGE_OBSERVER = "coral"
CONFIRMED_STOPS_OBSERVER = "coral.confirmed_stops"
# The name Coral's policies for bound sessions are registered under (S52).
REQUIRED_POLICY_PROVIDER = "coral"
# Recording step commands and judging handoffs; apart from the decision pool, so neither starves.
EVIDENCE_THREADS = 4
EVIDENCE_THREAD_NAME = "coral-evidence"
# Server config: drain workers, at most one item per run in flight each, so this many
# runs advance at once (1 to MAX_DRAIN_CONCURRENCY).
DRAIN_CONCURRENCY_CONFIG_KEY = "coral_drain_concurrency"
DEFAULT_DRAIN_CONCURRENCY = 4
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


class _ProcessLifespan:
    """Admits one Coral lifespan per process: its executors and observers are process-wide."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False

    def claim(self) -> Callable[[], None]:
        """
        Claim the process for a lifespan; the returned callable releases it.

        :raises RuntimeError: when another lifespan holds it.
        """
        with self._lock:
            if self._active:
                raise RuntimeError(
                    "Coral's lifespan is already running in this process; "
                    "a second one would share its executors and observers"
                )
            self._active = True
        return self._release

    def _release(self) -> None:
        with self._lock:
            self._active = False


_PROCESS_LIFESPAN = _ProcessLifespan()


def drain_concurrency(server_config: Mapping[str, Any] | None) -> int:
    """
    The drain pool's size from ``coral_drain_concurrency``, or the default when unset.

    :raises ValueError: for a value that is not an integer from 1 to the pool's maximum.
    """
    value = (server_config or {}).get(DRAIN_CONCURRENCY_CONFIG_KEY)
    if value is None:
        return DEFAULT_DRAIN_CONCURRENCY
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{DRAIN_CONCURRENCY_CONFIG_KEY} must be an integer")
    if not 1 <= value <= MAX_DRAIN_CONCURRENCY:
        raise ValueError(
            f"{DRAIN_CONCURRENCY_CONFIG_KEY} must be from 1 to {MAX_DRAIN_CONCURRENCY}"
        )
    return value


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
    port: RunDecisionPort | None,
    stack: AsyncExitStack,
    run_in_thread: ThreadRunner = asyncio.to_thread,
    gate_answering: Callable[[], bool] | None = None,
    evidence: EvidenceChecker | None = None,
) -> None:
    """
    Register what protects bound sessions, whether or not the session engine is wired.

    The engine tools register from the production catalog, answered by
    ``port`` (``None`` answers that the engine is not running); they read
    bindings fresh and decide on ``run_in_thread``. Coral's required-policy
    provider reads bindings through a cache of found rows and reads run status
    through a cache each run-store commit clears. The S53 mutation guard reads
    the same cache of found rows and refuses clients' changes to bound sessions
    and engine agents; a run's anchor takes approvals while ``gate_answering``
    says gate answers reach their handler. A ``done`` handoff is judged by
    ``evidence`` when given. Every registration's undo goes on ``stack``.
    """
    from coral.omni.policies.bindings_cache import CachedBindingLookup
    from coral.omni.policies.provider import CoralPolicyProvider
    from coral.omni.policies.state import RunStatusCache
    from coral.omni.server.mutation_guard import MUTATION_GUARD, CoralMutationGuard
    from coral.omni.server.tool_bridge import register_engine_tools
    from coral.tools.catalog import CATALOG
    from omnigent.runtime.policies.required_providers import register_required_policy_provider
    from omnigent.server.mutation_guards import register_mutation_guard

    register_engine_tools(
        catalog=CATALOG,
        port=port,
        bindings=bindings,
        stack=stack,
        run_in_thread=run_in_thread,
        evidence=evidence,
    )
    statuses = RunStatusCache(run_store)
    stack.callback(run_store.register_post_commit(statuses.invalidate))
    # One cache of found bindings for every guard that classifies sessions.
    found_bindings = CachedBindingLookup(bindings)
    provider = CoralPolicyProvider(bindings=found_bindings, statuses=statuses)
    stack.callback(register_required_policy_provider(REQUIRED_POLICY_PROVIDER, provider))
    guard = (
        CoralMutationGuard(found_bindings)
        if gate_answering is None
        else CoralMutationGuard(found_bindings, gate_answering=gate_answering)
    )
    stack.callback(register_mutation_guard(MUTATION_GUARD, guard))


def _wire_evidence(
    db_uri: str,
    bridge: EngineBridge,
    bound: BoundSessions,
    channels: ChannelsRef,
    threads: BoundedThreads,
    stack: AsyncExitStack,
) -> EvidenceChecker:
    """Register the observer that records step commands; return the handoff's checker."""
    from coral.omni.server.observations import (
        OBSERVER_NAME,
        EvidenceCapture,
        InFlightCalls,
        StepEvidenceLookup,
    )
    from coral.stores.observations import SqlAlchemyObservationStore
    from omnigent.server.tool_result_observers import register_tool_call_observer

    observations = SqlAlchemyObservationStore(db_uri)
    steps = StepEvidenceLookup(
        lambda workspace_id, run_id: bridge.load(workspace_id=workspace_id, run_id=run_id)
    )
    in_flight = InFlightCalls()
    capture = EvidenceCapture(
        bound=bound,
        steps=steps,
        observations=observations,
        in_flight=in_flight,
        read_l1=channels.read_l1,
        run_in_thread=threads.run,
    )
    stack.callback(register_tool_call_observer(OBSERVER_NAME, capture))
    return EvidenceChecker(
        steps=steps,
        observations=observations,
        in_flight=in_flight,
        read_l1=channels.read_l1,
        run_in_thread=threads.run,
    )


def _register_executors(
    executors: dict[str, EffectExecutor],
    stack: AsyncExitStack,
    *,
    runs_after_terminal: frozenset[str] = frozenset(),
) -> None:
    """Register each executor, pushing its unregister onto ``stack`` at once."""
    from coral.queue.executors import register_executor, unregister_executor

    for effect_type, executor in executors.items():
        register_executor(
            effect_type,
            executor,
            replace=True,
            runs_after_terminal=effect_type in runs_after_terminal,
        )
        stack.callback(unregister_executor, effect_type, executor)


def _wire_bridge(threads: BridgeThreads, stack: AsyncExitStack) -> None:
    """Register the bridge's own executors: its timers and its per-run resync."""
    from coral.bridge.executors import run_resync_executor, timer_executor
    from coral.bridge.mapping import RUN_RESYNC, TIMER

    _register_executors(
        {TIMER: timer_executor(threads), RUN_RESYNC: run_resync_executor(threads)}, stack
    )


def _wire_registration_carrier(stack: AsyncExitStack) -> None:
    """
    Carry the owner's Coral rows across a password change (S106).

    Omnigent calls the carrier inside the rotation's transaction on the operational
    database, which holds Coral's tables; an error aborts the rotation. Its undo goes
    on ``stack``.
    """
    from coral.stores.registration import carry_account_generation
    from omnigent.server.accounts_store import register_registration_carrier

    def carry(session: Session, user_id: str, old: str, new: str) -> None:
        carry_account_generation(
            session, workspace_id=current_workspace_id(), user_id=user_id, old=old, new=new
        )

    stack.callback(register_registration_carrier(carry))


def _host_connector(services: ServerServices) -> HostConnector | None:
    """Reaches a start's host through the server's host registry; ``None`` without one."""
    from coral.omni.server.worktrees import connect_run_worktree_host

    host_store = getattr(services, "host_store", None)
    host_registry = getattr(services, "host_registry", None)
    if host_store is None or host_registry is None:
        return None
    return partial(connect_run_worktree_host, host_registry=host_registry, host_store=host_store)


def _runs_api(
    bridge: EngineBridge,
    run_store: RunStore,
    services: ServerServices,
    stack: AsyncExitStack,
    *,
    gate_answers: GateAnswers,
    gate_publisher: GatePublisher,
) -> RunsApi:
    """
    The runs API over the bridge: route calls on their own pool, spend on another.

    Starts reach the owner's host through the server's registry, and need a proven
    account generation where users sign in to accounts. Closing ``stack`` cancels
    pending spend reads, then closes both pools; a request arriving after that is
    refused as busy.
    """
    from omnigent.server.auth import auth_mode

    api_threads = BoundedThreads(max_workers=API_THREADS, thread_name_prefix=API_THREAD_NAME)
    stack.callback(api_threads.close)
    spend_threads = BoundedThreads(max_workers=SPEND_THREADS, thread_name_prefix=SPEND_THREAD_NAME)
    stack.callback(spend_threads.close)
    spend = SpendCache(OmnigentRunSpend(services.conversation_store), spend_threads)
    stack.callback(spend.close)
    return RunsApi(
        bridge=bridge,
        run_store=run_store,
        spend=spend,
        in_flight=InFlight(api_threads),
        gate_answers=gate_answers,
        gate_publisher=gate_publisher,
        connect_host=_host_connector(services),
        requires_generation=auth_mode(services.auth_provider) == "accounts",
    )


def _run_stream_hub(
    bridge: EngineBridge,
    run_store: RunStore,
    services: ServerServices,
    stack: AsyncExitStack,
) -> RunStreamHub:
    """
    The run streams over the bridge's reads, on their own pool.

    Each run-store commit wakes the streams of its run; a caller who proved an account
    generation is re-checked against the server's accounts; a server shutting down ends
    them. Closing ``stack`` closes the hub first, which ends every stream, then
    unregisters the hook and closes the pool.
    """
    from omnigent.server.shutdown_state import server_shutting_down

    threads = BoundedThreads(max_workers=STREAM_THREADS, thread_name_prefix=STREAM_THREAD_NAME)
    stack.callback(threads.close)
    hub = RunStreamHub(
        bridge=bridge,
        run_store=run_store,
        threads=threads,
        still_valid=account_still_valid(services.auth_provider),
        shutting_down=server_shutting_down,
    )
    stack.callback(run_store.register_post_commit(hub.notify))
    stack.push_async_callback(hub.close)
    return hub


def _wire_gates(
    app: Any,
    services: ServerServices,
    *,
    db_uri: str,
    threads: BridgeThreads,
    run_store: RunStore,
    bindings: SqlAlchemySessionBindingStore,
    scope_runner: RunScopeRunner,
    publisher: GatePublisher,
    answering: GateAnswering,
    prompts: LocalGatePrompts,
    stack: AsyncExitStack,
) -> GateAnswers:
    """
    Register gate delivery and gate answers, whether or not the session engine is wired.

    The publish and withdraw executors (withdraws run after their run ended), then
    the verdict handler, and only then the anchor's admission of approvals. On exit
    the admission ends first, then answers admitted just before get a moment to
    reach the handler, which refuses them as retryable, then the handler goes.
    ``prompts`` observes every publish, and the sweep task withdraws this process's
    stale prompts until exit. Every undo goes on ``stack``. The server's auth
    provider is required: a services object without one is not taken as auth off.

    :returns: The answers the verdict handler takes, which the runs API shares.
    """
    from coral.gates.executors import gate_publish_executor, gate_withdraw_executor
    from coral.gates.ids import GATE_ELICITATION_PREFIX, GATE_PUBLISH, GATE_WITHDRAW
    from coral.gates.sweep import GatePromptSweeper
    from coral.gates.verdict import GateAnswers
    from coral.omni.server.gates import ANSWER_GRACE_S, gate_verdict_handler
    from coral.stores.alerts import SqlAlchemyAlertStore
    from omnigent.runtime.pending_elicitations import add_elicitation_observer
    from omnigent.server.elicitation_hooks import register_elicitation_verdict_handler

    _register_executors(
        {
            GATE_PUBLISH: gate_publish_executor(
                threads, publisher, bindings, run_store, scope_runner
            ),
            GATE_WITHDRAW: gate_withdraw_executor(threads, publisher, run_store, scope_runner),
        },
        stack,
        runs_after_terminal=frozenset({GATE_WITHDRAW}),
    )
    answers = GateAnswers(threads=threads, bindings=bindings, run_store=run_store)
    handler = gate_verdict_handler(answers, services.auth_provider, answering)
    stack.callback(register_elicitation_verdict_handler(GATE_ELICITATION_PREFIX, handler))
    stack.push_async_callback(asyncio.sleep, ANSWER_GRACE_S)
    answering.enable()
    stack.callback(answering.disable)
    stack.callback(add_elicitation_observer(prompts.observe))
    sweeper = GatePromptSweeper(
        threads=threads,
        run_store=run_store,
        bindings=bindings,
        publisher=publisher,
        prompts=prompts,
        scope_runner=scope_runner,
    )
    stop = asyncio.Event()
    sweep = asyncio.create_task(sweeper.run(stop), name=GATE_SWEEP_TASK)
    stack.push_async_callback(_stop_task, stop, sweep)
    if hasattr(app, "state"):
        app.state.coral_gate_publisher = publisher
        app.state.coral_gate_prompts = prompts
        app.state.coral_alert_store = SqlAlchemyAlertStore(db_uri)
    return answers


async def _stop_task(stop: asyncio.Event, task: asyncio.Task[None]) -> None:
    stop.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def _wire_session_engine(
    app: Any,
    services: ServerServices,
    *,
    db_uri: str,
    run_store: RunStore,
    queue_store: QueueStore,
    bindings: SqlAlchemySessionBindingStore,
    bound: BoundSessions,
    scope_runner: RunScopeRunner,
    threads: BridgeThreads,
    stack: AsyncExitStack,
    evidence_channels: ChannelsRef | None = None,
) -> BoundSessionRefresher:
    """
    Build the session engine and register its executors, then its status-edge observers.

    Each registration pushes its own unregister onto ``stack`` at once, so a
    failure part-way leaves nothing behind. Step creates resolve their agent
    from the stance, and drift pauses go through the engine on ``threads``.
    The turn-fact recorder writes a signal for each turn end of a session in
    ``bound``; the returned refresher, which the caller starts, rebuilds it.
    The evidence check reads worktree fingerprints through the same host
    channels, set on ``evidence_channels``.
    """
    from coral.bridge.executors import turn_fact_executor
    from coral.bridge.mapping import TURN_FACT
    from coral.omni.server.anchor_runner import AnchorRunnerStopper
    from coral.omni.server.dispatch import OmnigentSessionDispatch
    from coral.omni.server.sessions import OmnigentSessionFacade
    from coral.omni.server.status_edges import CoralStatusEdges
    from coral.omni.server.step_agents import OmnigentStepAgents
    from coral.omni.server.turn_facts import (
        TURN_FACTS_OBSERVER,
        BoundSessionRefresher,
        TurnFactRecorder,
    )
    from coral.omni.server.workspace_ops import OmnigentHostWorkspaceChannels
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
    # Resolved at stop time: the dispatch's pre-send hook holds the pauser that holds the stopper.
    anchor_runner_stopper = AnchorRunnerStopper(
        conversation_store=services.conversation_store,
        run_store=run_store,
        dispatch=lambda: dispatch,
    )
    pauser = DriftPauser(run_store, engine=threads, on_anchor_bound=anchor_runner_stopper)
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
    if evidence_channels is not None:
        evidence_channels.channels = channels
    edges = CoralStatusEdges(asyncio.get_running_loop())
    # One record: the close writes each confirmed stop, workspace.commit reads it.
    stops = ConfirmedStops()
    agents = OmnigentStepAgents(
        services.agent_store,
        services.artifact_store,
        conversation_store=services.conversation_store,
    )
    executors: dict[str, EffectExecutor] = {
        CREATE_SESSION: create_session_executor(
            facade, run_store, pauser, scope_runner, agents=agents
        ),
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
        TURN_FACT: turn_fact_executor(
            threads,
            bindings=bindings,
            dispatch=dispatch,
            transcripts=dispatch,
            stable_ids=stable_ids,
            facade=facade,
            drift=pauser,
            scope_runner=scope_runner,
        ),
    }
    # A cancelled run is finished when its cancel_sessions items are claimed.
    _register_executors(executors, stack, runs_after_terminal=frozenset({CANCEL_SESSIONS}))
    recorder = TurnFactRecorder(bound, queue_store)
    recorder.start()
    # Pushed before the observer registers, so it closes after the observer is removed.
    stack.callback(recorder.close)
    stack.callback(register_status_edge_observer(STATUS_EDGE_OBSERVER, edges.observe))
    stack.callback(register_status_edge_observer(CONFIRMED_STOPS_OBSERVER, stops.observe))
    stack.callback(register_status_edge_observer(TURN_FACTS_OBSERVER, recorder.observe))
    refresher = BoundSessionRefresher(bindings, bound)
    app.state.coral_session_facade = facade
    app.state.coral_session_dispatch = dispatch
    app.state.coral_status_edges = edges
    app.state.coral_confirmed_stops = stops
    app.state.coral_turn_fact_recorder = recorder
    app.state.coral_bound_session_refresher = refresher
    return refresher


@asynccontextmanager
async def coral_lifespan(
    app: FastAPI,
    services: ServerServices,
) -> AsyncIterator[None]:
    """
    Run Coral's startup migration check, worker supervisor, and reverse-order shutdown.

    One lifespan per process: on a usable operational database it first claims
    the process, and a second one entered meanwhile raises before registering
    anything. Then the guards for bound sessions, the engine tools with the
    decision port, the engine bridge's executors, the carrier that moves the
    owner's Coral rows across a password change, and gate delivery and answers
    are registered, and with the server's stores present also the session
    engine's executors, its status-edge observers and the bound-session index
    the turn-fact recorder reads, all before the supervisor starts, whose
    startup sweep republishes open gates, whose finished items feed the bridge
    and whose resync tick repairs each active run and shows again any gate
    prompt this process lost. They share one
    binding store. Bridge calls run on the bridge's own thread pool,
    tool decisions on a smaller one. Exit stops the supervisor first, so no
    item is claimed while its executor is missing (an item in flight keeps its
    lease and is reclaimed), then unregisters in reverse order, also after a
    failed start.
    """
    if services.host_sharded:
        raise RuntimeError("Coral server plugin does not support host_sharded=True")

    conv_store = getattr(services, "conversation_store", None)
    storage_location: str | None = getattr(conv_store, "storage_location", None)

    async with AsyncExitStack() as stack:
        if _is_usable_operational_db_uri(storage_location):
            from coral.omni.server.gates import (
                GateAnswering,
                LocalGatePrompts,
                OmnigentGatePublisher,
            )

            assert storage_location is not None
            stack.callback(_PROCESS_LIFESPAN.claim())
            await asyncio.to_thread(ensure_coral_schema, storage_location)
            run_store = SqlAlchemyCoralRunStore(storage_location)
            queue_store = SqlAlchemyCoralQueueStore(storage_location)
            scope_runner = OmnigentRunScopeRunner()
            bound = BoundSessions()
            bridge = EngineBridge(
                run_store=run_store,
                queue_store=queue_store,
                versions=SqlAlchemyWorkflowVersionStore(storage_location),
                bound_sessions=bound,
            )
            workers = drain_concurrency(getattr(services, "server_config", None))
            # Each drain worker may wait on one bridge call; the pool never starves them.
            threads = BridgeThreads(bridge, max_workers=max(BRIDGE_THREADS, workers))
            stack.callback(threads.close)
            decisions = BoundedThreads(
                max_workers=DECISION_THREADS, thread_name_prefix=DECISION_THREAD_NAME
            )
            # Pushed before the engine tools register, so it closes after they are removed.
            stack.callback(decisions.close)
            publisher = OmnigentGatePublisher()
            # Off until the gate verdict handler registers; off again before it is removed.
            answering = GateAnswering()
            # The gate prompts this process shows, which the republisher does not re-send.
            prompts = LocalGatePrompts()
            bindings = SqlAlchemySessionBindingStore(storage_location)
            supervisor = WorkerSupervisor(
                run_store,
                queue_store,
                scope_runner=scope_runner,
                gate_republisher=GateRepublisher(
                    threads, publisher, bindings=bindings, prompts=prompts
                ),
                run_reconciler=threads.schedule_resync,
                on_finished=threads.feed,
                hold_policy=bridge_hold_policy,
                drain_concurrency=workers,
                resync_interval_s=RESYNC_INTERVAL_S,
            )
            if hasattr(app, "state"):
                app.state.coral_run_store = run_store
                app.state.coral_queue_store = queue_store
                app.state.coral_worker_supervisor = supervisor
                app.state.coral_engine_bridge = bridge
                app.state.coral_bound_sessions = bound
            evidence_threads = BoundedThreads(
                max_workers=EVIDENCE_THREADS, thread_name_prefix=EVIDENCE_THREAD_NAME
            )
            stack.callback(evidence_threads.close)
            evidence_channels = ChannelsRef()
            evidence = _wire_evidence(
                storage_location, bridge, bound, evidence_channels, evidence_threads, stack
            )
            _wire_guards(
                run_store=run_store,
                bindings=bindings,
                port=StoreDecisionPort(bridge),
                stack=stack,
                run_in_thread=decisions.run,
                gate_answering=answering,
                evidence=evidence,
            )
            _wire_bridge(threads, stack)
            _wire_registration_carrier(stack)
            answers = _wire_gates(
                app,
                services,
                db_uri=storage_location,
                threads=threads,
                run_store=run_store,
                bindings=bindings,
                scope_runner=scope_runner,
                publisher=publisher,
                answering=answering,
                prompts=prompts,
                stack=stack,
            )
            if hasattr(app, "state"):
                # Its pools close before the gates are unregistered.
                app.state.coral_runs_api = _runs_api(
                    bridge,
                    run_store,
                    services,
                    stack,
                    gate_answers=answers,
                    gate_publisher=publisher,
                )
                app.state.coral_run_stream_hub = _run_stream_hub(
                    bridge, run_store, services, stack
                )
            missing = _missing_engine_input(app, services)
            if missing is None:
                refresher = _wire_session_engine(
                    app,
                    services,
                    db_uri=storage_location,
                    run_store=run_store,
                    queue_store=queue_store,
                    bindings=bindings,
                    bound=bound,
                    scope_runner=scope_runner,
                    threads=threads,
                    stack=stack,
                    evidence_channels=evidence_channels,
                )
                stack.push_async_callback(refresher.stop)
                await refresher.start()
            else:
                # Session effects are then held as ``executor.missing``, then pause their run.
                _logger.warning("Coral session engine not wired: %s is missing", missing)
            # Pushed last, so it runs first on exit.
            stack.push_async_callback(supervisor.stop)
            await supervisor.start()
        yield


def coral_routers(
    *,
    sub_features: Mapping[str, bool],
    definitions: WorkflowDefinitionStore,
    auth_provider: AuthProvider | None,
) -> tuple[RouterSpec, ...]:
    """
    Every Coral router with its prefix and tags: the plugin mounts these, and the
    OpenAPI export documents them.

    Each route resolves its caller through ``auth_provider`` and reads the request's
    workspace; the Inbox reads the alert store the lifespan publishes, the runs routes
    its runs API and run-stream hub, and a start the caller's workflow from ``definitions``.
    """
    viewer = request_viewer(auth_provider)
    return (
        (create_info_router(sub_features=sub_features), "", ["coral"]),
        (
            create_workflows_router(
                definitions,
                viewer_dependency=viewer,
                workspace_id_dependency=current_workspace_id,
            ),
            CORAL_API_PREFIX,
            ["coral"],
        ),
        (
            create_inbox_router(
                viewer_dependency=viewer, workspace_id_dependency=current_workspace_id
            ),
            CORAL_API_PREFIX,
            ["coral"],
        ),
        (
            create_runs_router(
                definitions=definitions,
                viewer_dependency=viewer,
                workspace_id_dependency=current_workspace_id,
            ),
            CORAL_API_PREFIX,
            ["coral"],
        ),
    )


def register(services: ServerServices) -> ServerPluginRegistration:
    """Register Coral routers, policy modules, and lifespan hooks."""
    if services.host_sharded:
        raise RuntimeError("Coral server plugin does not support host_sharded=True")

    sub_features = resolve_sub_features(services.server_config)
    engine = _create_workflow_engine()

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
        routers=coral_routers(
            sub_features=sub_features,
            definitions=SqlWorkflowDefinitionStore(engine),
            auth_provider=services.auth_provider,
        ),
        lifespan_hooks=(coral_lifespan, workflow_engine_lifespan),
        policy_modules=("coral.omni.policies.hygiene", "coral.omni.policies.guards"),
    )
