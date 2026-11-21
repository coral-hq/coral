"""A bridge over stores, with a manual clock, for the bridge's write-side tests.

``World.fake`` runs on the in-memory stores; ``World.sql`` on one database URI.
Both pin workflow versions in SQL, the only version store there is.
:func:`serving` adds the session side: the real executors over fake sessions,
a drainer with the bridge's hook and hold policy, and the engine tools, which a
scripted :class:`Agent` and :class:`Orchestrator` call. Gate prompts go to a
:class:`RecordingGatePublisher`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import itertools
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from sqlalchemy import create_engine

from coral.bridge.bound_sessions import BoundSessions
from coral.bridge.codec import decode_entries
from coral.bridge.config import ENGINE_LOG_PAGE, freeze_engine_config
from coral.bridge.executors import (
    BridgeThreads,
    LivenessCheck,
    bridge_hold_policy,
    crosses_host_wait,
    run_resync_executor,
    timer_executor,
    turn_fact_executor,
)
from coral.bridge.keys import slot_session_id, store_activation_id
from coral.bridge.mapping import RECOVERY_RESTART, RECOVERY_WAKE, RUN_RESYNC, TIMER, TURN_FACT
from coral.bridge.port import StoreDecisionPort
from coral.bridge.service import BridgeCommit, EngineBridge
from coral.bridge.start import start_engine_run
from coral.db import CoralBase
from coral.db.enum_codecs import SessionBindingProgress, WorkKind, WorkStatus
from coral.engine import fold
from coral.engine.machines.slot import find_slot
from coral.engine.types import HandoffEvaluated, HandoffReceived, Input, RunState, TurnEnded
from coral.gates.executors import gate_publish_executor, gate_withdraw_executor
from coral.gates.ids import GATE_PUBLISH, GATE_WITHDRAW
from coral.model.ids import derived_id
from coral.omni.protocols import (
    CoralSessionError,
    SessionCreateRequest,
    SessionRef,
    SessionState,
    TrackedPrompt,
)
from coral.omni.server.turn_facts import BoundSessionRefresher, TurnFactRecorder
from coral.queue import FinishedWork, SqlAlchemyCoralQueueStore
from coral.queue.drainer import WorkDrainer
from coral.queue.executors import EffectExecutor, register_executor, unregister_executor
from coral.reconcile.startup import startup_recovery_sweep
from coral.recovery.drift import DriftPauser
from coral.recovery.ladder import restart_executor
from coral.recovery.relaunch import wake_executor
from coral.slots.close import ConfirmedStops
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
from coral.stores.fakes import FakeQueueStore, FakeRunStore
from coral.stores.protocols import (
    CoralRun,
    QueueStore,
    RunLogEntry,
    RunStartSpec,
    RunStore,
    WorkItem,
)
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.stores.session_bindings import SessionBindingDraft, SqlAlchemySessionBindingStore
from coral.stores.stable_ids import SqlAlchemyStableIdStore, StableIds
from coral.stores.workflow_versions import SqlAlchemyWorkflowVersionStore
from coral.stores.workspace_op_intents import SqlAlchemyWorkspaceOpIntentStore, WorkspaceOpIntents
from coral.tools.catalog import CHOOSE_ARROW, SUBMIT_HANDOFF
from coral.tools.dispatch import EngineToolCall, ToolDispatcher
from coral.tools.handlers import PLANNERS
from coral.tools.schemas import ToolReply
from coral.workspace.ops import HostChannelBackend
from coral.workspace.run_worktree import run_branch_name
from omnigent.server.session_live_state import SessionStatusEdge
from tests.coral.omni.fakes import FakeRelauncher, FakeSessionFacade
from tests.coral.slots._close_fakes import FakeDispatch, FakeEdgeWatcher, FakeStableIds
from tests.coral.workflow_builders import compile_text, fixture_text
from tests.coral.workspace._executor_fakes import (
    FakeBindings,
    FakeChannels,
    FakeHostChannel,
    FakeIntents,
    RecordingScopeRunner,
)
from tests.stores.coral._faults import evict_cached_engine

# A non-zero workspace, so a missing workspace argument cannot pass by default.
WORKSPACE = 7
START = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
USER = "alice"
START_KEY = "start-1"
DEFINITION = "d" * 32
IMPLEMENT = "implement||:0"
REVIEW = "review||:0"


class ManualClock:
    """A UTC clock the test moves."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now

    @property
    def epoch(self) -> int:
        return int(self.now.timestamp())


@dataclass
class World:
    runs: RunStore
    queue: QueueStore
    versions: SqlAlchemyWorkflowVersionStore
    clock: ManualClock
    bridge: EngineBridge
    # The bridge's bound-session index, which its create feedback fills.
    bound: BoundSessions
    # The database of a SQL world; ``None`` on the in-memory stores.
    db_uri: str | None = None

    @classmethod
    def fake(cls, tmp_path: Path, *, gate_ids: Callable[[], str] | None = None) -> World:
        """:param gate_ids: The bridge's gate elicitation ids; random when not given."""
        engine = create_engine(f"sqlite:///{tmp_path / 'versions.db'}")
        CoralBase.metadata.create_all(engine)
        runs = FakeRunStore(default_workspace_id=WORKSPACE)
        return cls._build(
            runs,
            FakeQueueStore(run_store=runs),
            SqlAlchemyWorkflowVersionStore(engine),
            gate_ids=gate_ids,
        )

    @classmethod
    def sql(cls, db_uri: str, *, gate_ids: Callable[[], str] | None = None) -> World:
        return cls._build(
            SqlAlchemyCoralRunStore(db_uri),
            SqlAlchemyCoralQueueStore(db_uri),
            SqlAlchemyWorkflowVersionStore(db_uri),
            db_uri=db_uri,
            gate_ids=gate_ids,
        )

    @classmethod
    def _build(
        cls,
        runs: RunStore,
        queue: QueueStore,
        versions: SqlAlchemyWorkflowVersionStore,
        *,
        db_uri: str | None = None,
        gate_ids: Callable[[], str] | None = None,
    ) -> World:
        clock = ManualClock()
        bound = BoundSessions()
        bridge = EngineBridge(
            run_store=runs,
            queue_store=queue,
            versions=versions,
            clock=clock,
            bound_sessions=bound,
            **({} if gate_ids is None else {"gate_elicitation_ids": gate_ids}),
        )
        return cls(
            runs=runs,
            queue=queue,
            versions=versions,
            clock=clock,
            bridge=bridge,
            bound=bound,
            db_uri=db_uri,
        )

    def run(self, run_id: str) -> CoralRun:
        run = self.runs.get_run(run_id, workspace_id=WORKSPACE)
        assert run is not None
        return run

    def work(self, run_id: str) -> list[WorkItem]:
        """Every work row of the run, oldest due first (fake stores; SQL reads rows by id)."""
        assert isinstance(self.queue, FakeQueueStore)
        return sorted(
            (item for item in self.queue.work.values() if item.run_id == run_id),
            key=lambda item: (item.available_at, item.id),
        )

    def engine_log(self, run_id: str) -> list[RunLogEntry]:
        version = self.run(run_id).version
        rows: list[RunLogEntry] = []
        while True:
            page = self.runs.read_engine_log(
                run_id,
                workspace_id=WORKSPACE,
                after_seq=rows[-1].seq if rows else 0,
                max_run_version=version,
                limit=ENGINE_LOG_PAGE,
            )
            rows.extend(page)
            if len(page) < ENGINE_LOG_PAGE:
                return rows

    def assert_fold_matches(self, run_id: str) -> RunState:
        """The stored log, decoded and replayed, is the state the bridge loads."""
        snapshot = self.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
        replayed = fold(snapshot.graph, decode_entries(self.engine_log(run_id)), snapshot.config)
        assert replayed == snapshot.state
        return snapshot.state


def run_id_for(user: str | None = USER, start_key: str = START_KEY) -> str:
    return derived_id("coral-run", user or "", start_key)


def run_spec(
    *, user: str | None = USER, start_key: str = START_KEY, **fields: Any
) -> RunStartSpec:
    """A spec whose run target is valid for the run ``user`` and ``start_key`` make."""
    values: dict[str, Any] = {
        "workflow_id": DEFINITION,
        "version_id": "0" * 32,
        "title": "Ship the bridge",
        "request_preview": "Make runs advance",
        "workspace_id": WORKSPACE,
        "user_id": user,
        "host_id": "host-1",
        "repo_path": "/repo/coral",
        "worktree_path": "/repo/coral-worktrees/r1",
        "run_branch": run_branch_name(run_id_for(user, start_key)),
        "max_activations": 100,
    }
    values.update(fields)
    return RunStartSpec(**values)


def start(
    world: World,
    yaml_text: str | None = None,
    *,
    spec: RunStartSpec | None = None,
    start_key: str = START_KEY,
    actor: str | None = "user:alice",
    **options: Any,
) -> CoralRun:
    return start_engine_run(
        world.bridge,
        spec=spec if spec is not None else run_spec(start_key=start_key),
        yaml_text=yaml_text if yaml_text is not None else fixture_text("two_steps"),
        start_key=start_key,
        actor=actor,
        **options,
    )


def start_without_engine(
    world: World,
    *,
    start_key: str = "bare",
    yaml_text: str | None = None,
    workspace_id: int = WORKSPACE,
    user: str | None = USER,
) -> CoralRun:
    """A run whose ``start_run`` committed and whose ``StartRun`` did not: a crash between."""
    text = yaml_text if yaml_text is not None else fixture_text("two_steps")
    pinned = world.versions.pin(
        workspace_id=workspace_id,
        workflow_id=DEFINITION,
        graph=compile_text(text)[0],
        yaml_text=text,
        created_by=user,
    )
    spec = run_spec(
        user=user,
        start_key=start_key,
        workspace_id=workspace_id,
        version_id=pinned.id,
        rejected_call_limit=3,
        engine_config=freeze_engine_config(max_activations=100, rejected_call_limit=3),
    )
    return world.runs.start_run(spec, start_key=start_key, now=world.clock.epoch)


def row_of(
    world: World, run_id: str, effect_type: str, *, engine_kind: str | None = None
) -> WorkItem:
    """The run's one row of ``effect_type`` (and engine kind), oldest first if several."""
    rows = [
        item
        for item in world.work(run_id)
        if json.loads(item.payload).get("effect_type") == effect_type
        and (engine_kind is None or json.loads(item.payload).get("engine_kind") == engine_kind)
    ]
    assert rows, f"no {effect_type} row"
    return rows[0]


def settle(
    world: World,
    item: WorkItem,
    status: WorkStatus,
    *,
    error_code: str | None = None,
    result: dict[str, Any] | None = None,
    held_since: int | None = None,
    available_at: int | None = None,
) -> WorkItem:
    """Write an outcome onto a fake row, as a drainer that finished it would."""
    assert isinstance(world.queue, FakeQueueStore)
    finished = status not in (WorkStatus.PENDING, WorkStatus.CLAIMED)
    updated = dataclasses.replace(
        item,
        status=int(status),
        error_code=error_code,
        result=None if result is None else json.dumps(result, sort_keys=True),
        finished_at=world.clock.epoch if finished else None,
        held_since=held_since,
        available_at=item.available_at if available_at is None else available_at,
    )
    world.queue.work[(item.workspace_id, item.id)] = updated
    return updated


def finished(item: WorkItem) -> FinishedWork:
    """The drainer's view of a finished row."""
    result = None if item.result is None else json.loads(item.result)
    return FinishedWork(item=item, status=item.status, error_code=item.error_code, result=result)


def ids(items: Sequence[WorkItem]) -> set[str]:
    return {item.id for item in items}


def blocked(slot_id: str, report: str = "Cannot go on.") -> tuple[Input, ...]:
    """A blocked handoff of ``slot_id``; with no failure arrow the run pauses for a retry."""
    activation = slot_id.rsplit(":", 1)[0]
    body = json.dumps(
        {"activation_id": activation, "report": report, "status": "blocked"},
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        HandoffReceived(slot_id=slot_id, body=body),
        HandoffEvaluated(slot_id=slot_id, outcome="blocked"),
    )


def briefed(world: World) -> str:
    """A started two-step run whose implementer's session was created and briefed."""
    run = start(world)
    session = {"session_id": "s" * 32, "role": "step", "generation": 1}
    create = row_of(world, run.id, "create_session", engine_kind="create_session")
    world.bridge.feed(finished(settle(world, create, WorkStatus.SUCCEEDED, result=session)))
    sent = {"session_id": "s" * 32, "stable_id": "m1"}
    brief = row_of(world, run.id, "send_input")
    world.bridge.feed(finished(settle(world, brief, WorkStatus.SUCCEEDED, result=sent)))
    return run.id


def retried(world: World, slot_id: str = IMPLEMENT) -> str:
    """A briefed run whose ``slot_id`` blocked and was retried: its restart is queued."""
    run_id = briefed(world)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: blocked(slot_id)
    )
    activation = slot_id.rsplit(":", 1)[0]
    result = world.bridge.retry_activation(
        workspace_id=WORKSPACE,
        run_id=run_id,
        actor="user:alice",
        activation_id=store_activation_id(run_id, activation),
    )
    assert (result.outcome, result.code) == ("retried", None), result
    return run_id


# ── the session side ────────────────────────────────────────────────────────


@dataclass
class RecordingGatePublisher:
    """
    A ``GatePublisher`` over a dict of pending prompts, recording each call in order.

    :ivar after_publish: Runs after each publish is recorded, e.g. to commit a cancel
        between the executor's two loads.
    """

    calls: list[tuple[str, str, str]] = field(default_factory=list)
    pending: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    after_publish: Callable[[], object] | None = None

    async def publish(
        self, *, session_id: str, elicitation_id: str, params: Mapping[str, Any]
    ) -> None:
        self.calls.append(("publish", session_id, elicitation_id))
        self.pending[(session_id, elicitation_id)] = dict(params)
        if self.after_publish is not None:
            self.after_publish()

    async def withdraw(self, *, session_id: str, elicitation_id: str) -> bool:
        self.calls.append(("withdraw", session_id, elicitation_id))
        return self.pending.pop((session_id, elicitation_id), None) is not None


@dataclass
class FakeGatePrompts:
    """``PendingGatePrompts`` over a recording publisher's pending prompts (one workspace)."""

    gates: RecordingGatePublisher
    prompts: list[TrackedPrompt] = field(default_factory=list)
    listed: int = 0

    def track(self, session_id: str, elicitation_id: str) -> TrackedPrompt:
        """Publish ``elicitation_id`` on the session and track it, as the S5 observer would."""
        self.gates.pending[(session_id, elicitation_id)] = {}
        prompt = TrackedPrompt(WORKSPACE, session_id, elicitation_id)
        self.prompts.append(prompt)
        return prompt

    def tracked(self) -> list[TrackedPrompt]:
        self.listed += 1
        return list(self.prompts)

    def forget(self, prompt: TrackedPrompt) -> None:
        if prompt in self.prompts:
            self.prompts.remove(prompt)

    def is_pending(self, prompt: TrackedPrompt) -> bool:
        return (prompt.session_id, prompt.elicitation_id) in self.gates.pending


# What the run worktree's host answers a writer's close: an unchanged tree, then one commit.
HOST_REPLIES: dict[str, Mapping[str, object]] = {
    "fingerprint": {"level": "L1", "digest": "d" * 64, "head": "1" * 40, "dirty_count": 1},
    "head": {"head": "1" * 40, "branch": None, "merge_in_progress": False},
    "commit": {"commit": "2" * 40, "empty": False},
    "diff_stat": {"files_changed": 1, "insertions": 1, "deletions": 0, "paths": ["a"]},
}
_ACTIVATION_ID = re.compile(r'activation_id ("(?:[^"\\]|\\.)*")')
_DECISION_ID = re.compile(r'decision_id ("(?:[^"\\]|\\.)*")')
# Replies an agent told to retry gets; it calls again on its next turn.
_RETRY_REASONS = frozenset({"evaluation_in_progress"})


def activation_in(text: str) -> str:
    """The activation id an engine message asks the agent to hand off for (its last mention)."""
    found = _ACTIVATION_ID.findall(text)
    assert found, "the engine message names no activation id"
    return json.loads(found[-1])


def decision_in(text: str) -> str:
    """The decision id a decision message asks the orchestrator to choose at."""
    found = _DECISION_ID.findall(text)
    assert found, "the decision message names no decision id"
    return json.loads(found[0])


class StanceAgents:
    """
    A ``StepAgentResolver`` that answers one agent per stance and records each step.

    :ivar refusals: Raised for every resolve of that stance while it is set.
    """

    def __init__(self) -> None:
        self.resolved: list[dict[str, Any]] = []
        self.refusals: dict[str, CoralSessionError] = {}

    async def resolve(self, **step: Any) -> str:
        self.resolved.append(step)
        refusal = self.refusals.get(step["stance"])
        if refusal is not None:
            raise refusal
        return f"{step['stance']}-agent"


@dataclass
class BindingFacade:
    """
    The fake facade, binding each session as the real one does and opening it on ``dispatch``.

    A step binds its engine slot, slot role, generation and host; each create records
    ``row_created`` and then ``initialized``.
    """

    bindings: FakeBindings | SqlAlchemySessionBindingStore
    dispatch: FakeDispatch
    sessions: FakeSessionFacade = field(default_factory=FakeSessionFacade)

    @property
    def requests(self) -> list[SessionCreateRequest]:
        return self.sessions.requests

    async def create_session(
        self,
        request: SessionCreateRequest,
        *,
        ensure_lease: Callable[[], Awaitable[None]],
    ) -> SessionRef:
        ref = await self.sessions.create_session(request, ensure_lease=ensure_lease)
        step = request.role == "step"
        draft = SessionBindingDraft(
            workspace_id=request.workspace_id,
            session_id=ref.session_id,
            run_id=request.run_id,
            role=request.role,
            effect_key=request.effect_key,
            slot_id=request.engine_slot_id if step else None,
            slot_role=request.slot_role if step else None,
            session_generation=request.generation if step else 1,
            host_id=request.host_id if step else None,
        )
        await asyncio.to_thread(self.bindings.reserve, draft)
        for progress in (SessionBindingProgress.ROW_CREATED, SessionBindingProgress.INITIALIZED):
            await asyncio.to_thread(
                self.bindings.record_progress, request.workspace_id, ref.session_id, progress
            )
        if ref.session_id not in self.dispatch.sessions:
            self.dispatch.session(ref.session_id)
        return ref

    async def session_state(self, *, workspace_id: int, session_id: str) -> SessionState:
        return await self.sessions.session_state(workspace_id=workspace_id, session_id=session_id)


@dataclass
class Sessions:
    """
    A world's session side: the real executors over fake sessions, a drainer and the tools.

    The drainer runs every work kind on the world's clock, with the bridge's hold
    policy and its finished hook; ``before_feed`` runs first for each finished row.
    The engine tools are decided by the store port through the real dispatcher. Status
    edges go through the turn-fact recorder over the world's bound-session index. Gate
    prompts are published to ``gates``.
    """

    world: World
    events: list[str]
    bindings: FakeBindings | SqlAlchemySessionBindingStore
    stable_ids: StableIds
    intents: WorkspaceOpIntents
    dispatch: FakeDispatch
    edges: FakeEdgeWatcher
    host: FakeHostChannel
    facade: BindingFacade
    agents: StanceAgents
    threads: BridgeThreads
    dispatcher: ToolDispatcher
    recorder: TurnFactRecorder
    gates: RecordingGatePublisher = field(default_factory=RecordingGatePublisher)
    drainer: WorkDrainer = field(init=False)
    before_feed: Callable[[FinishedWork], Awaitable[None]] | None = None
    # The run worktree's host, when not ``host``'s canned replies (real git, say).
    channel: HostChannelBackend | None = None
    # The resync's runner liveness check, as the session engine wires it.
    liveness: LivenessCheck | None = None
    # The wake's relaunch path: by default a connected runner is back, else relaunched.
    relauncher: FakeRelauncher = field(init=False)

    def __post_init__(self) -> None:
        self.relauncher = FakeRelauncher(
            fallback=self._runner_back_or_relaunched, on_relaunch=self._relaunched
        )
        self.drainer = WorkDrainer(
            self.world.queue,
            worker_id="worker-1",
            kinds=(int(WorkKind.EFFECT), int(WorkKind.TIMER), int(WorkKind.SIGNAL)),
            clock=lambda: self.world.clock.now.timestamp(),
            rng=lambda: 0.5,
            hold_policy=bridge_hold_policy,
            hold_restart=crosses_host_wait,
            on_finished=self._finished,
        )

    def _runner_back_or_relaunched(self, session_id: str) -> Literal["connected", "relaunched"]:
        """A connected runner is back; any other is relaunched in place."""
        return "connected" if self.dispatch.sessions[session_id].runner_alive else "relaunched"

    def _relaunched(self, session_id: str) -> None:
        """A relaunch replaces a lost runner under a new id; a connected one is kept."""
        session = self.dispatch.sessions[session_id]
        if not session.runner_alive:
            session.runner_alive = True
            session.runner_id = f"{session.runner_id or 'runner'}-relaunched"

    async def _finished(self, finished: FinishedWork) -> None:
        if self.before_feed is not None:
            await self.before_feed(finished)
        await self.threads.feed(finished)

    def executors(self) -> dict[str, EffectExecutor]:
        """The session engine's executors and the bridge's own, as the lifespan registers them."""
        world, scope = self.world, RecordingScopeRunner()
        pauser = DriftPauser(world.runs, engine=self.threads)
        channels = FakeChannels(self.channel or self.host, scope)
        return {
            CREATE_SESSION: create_session_executor(
                self.facade, world.runs, pauser, scope, agents=self.agents
            ),
            SEND_INPUT: send_input_executor(
                self.dispatch, self.stable_ids, self.bindings, world.runs, scope
            ),
            CLOSE_SLOT: close_slot_executor(
                self.dispatch,
                self.edges,
                channels,
                self.intents,
                self.stable_ids,
                self.bindings,
                world.runs,
                scope,
                stops=ConfirmedStops(),
            ),
            CANCEL_SESSIONS: cancel_sessions_executor(
                self.dispatch, self.edges, self.bindings, world.runs, scope
            ),
            RECOVERY_RESTART: restart_executor(
                dispatch=self.dispatch,
                edges=self.edges,
                channels=channels,
                bindings=self.bindings,
                intents=self.intents,
                run_store=world.runs,
                scope_runner=scope,
            ),
            RECOVERY_WAKE: wake_executor(
                threads=self.threads,
                relauncher=self.relauncher,
                dispatch=self.dispatch,
                facade=self.facade,
                drift=pauser,
                run_store=world.runs,
                scope_runner=scope,
            ),
            TIMER: timer_executor(self.threads),
            RUN_RESYNC: run_resync_executor(self.threads, self.liveness),
            GATE_PUBLISH: gate_publish_executor(
                self.threads, self.gates, self.bindings, world.runs, scope
            ),
            GATE_WITHDRAW: gate_withdraw_executor(self.threads, self.gates, world.runs, scope),
            TURN_FACT: turn_fact_executor(
                self.threads,
                bindings=self.bindings,
                dispatch=self.dispatch,
                transcripts=self.dispatch,
                stable_ids=self.stable_ids,
                facade=self.facade,
                drift=pauser,
                scope_runner=scope,
            ),
        }

    async def drain(self) -> int:
        """Run every item due now, held ones excepted; returns how many ran."""
        ran = 0
        while await self.drainer.drain_once() is not None:
            ran += 1
        return ran

    async def run(self, *actors: Actor, rounds: int = 50) -> None:
        """Drain and let each actor act until none has anything left to do."""
        for _ in range(rounds):
            drained = await self.drain()
            acted = 0
            for actor in actors:
                acted += await actor.act()
            if not drained and not acted:
                return
        raise AssertionError(f"the run was still busy after {rounds} rounds")

    def messages(self, session_id: str | None = None) -> list[dict[str, object]]:
        """The engine messages sent so far, oldest first, to one session or to all."""
        return [
            send
            for send in self.dispatch.sends
            if session_id is None or send["session_id"] == session_id
        ]

    def session_of(self, run_id: str, engine_slot_id: str) -> str:
        state = self.world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state
        session_id = slot_session_id(WORKSPACE, state, engine_slot_id)
        assert session_id is not None, f"slot {engine_slot_id} has no session"
        return session_id

    def orchestrator_of(self, run_id: str) -> str:
        """The orchestrator session the run's row names."""
        session_id = self.world.run(run_id).orchestrator_session_id
        assert session_id is not None, f"run {run_id} has no orchestrator"
        return session_id

    def publish(self, run_id: str, engine_slot_id: str, status: str, **fields: Any) -> None:
        """Publish one status edge of the slot's session; see :meth:`publish_to`."""
        self.publish_to(self.session_of(run_id, engine_slot_id), status, **fields)

    def publish_to(self, session_id: str, status: str, **fields: Any) -> None:
        """
        Publish one status edge of a session, as the server does, and wait for its row.

        The session's live status follows the edge; the edge's time is the world's clock.
        """
        fields.setdefault("observed_at_ms", int(self.world.clock.now.timestamp() * 1000))
        fields.setdefault("origin", "relayed_runner_status")
        self.dispatch.sessions[session_id].status = status
        self.recorder.observe(
            SessionStatusEdge(
                session_id=session_id,
                status=status,
                previous_status="running",
                workspace_id=WORKSPACE,
                **fields,
            )
        )
        self.recorder.wait_idle()

    def complete_turn(self, run_id: str, engine_slot_id: str, **fields: Any) -> None:
        """The slot's agent replies and its turn completes without a handoff."""
        self.dispatch.reply(self.session_of(run_id, engine_slot_id))
        fields.setdefault("turn_outcome", "completed")
        self.publish(run_id, engine_slot_id, "idle", **fields)

    def fail_turn(
        self, run_id: str, engine_slot_id: str, message: str, *, code: str = "RuntimeError"
    ) -> None:
        """The slot's turn fails as claude-sdk reports it: a code and the error text."""
        self.fail_session(self.session_of(run_id, engine_slot_id), message, code=code)

    def fail_session(self, session_id: str, message: str, *, code: str = "RuntimeError") -> None:
        """The session's turn fails as claude-sdk reports it: a code and the error text."""
        self.publish_to(
            session_id,
            "failed",
            turn_outcome="failed",
            error_code=code,
            error_message=message,
            failure_origin="relayed_runner_status",
        )

    def end_turn(self, run_id: str, engine_slot_id: str) -> BridgeCommit:
        """
        The slot's turn ends: commit ``TurnEnded`` keyed by its session's newest engine message.

        A test ends a turn here instead of through the session's status edges.
        """
        session_id = self.session_of(run_id, engine_slot_id)
        stable_id = self.messages(session_id)[-1]["stable_id"]
        state = self.world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state
        slot = find_slot(state, engine_slot_id)
        assert slot is not None
        fact_key = f"turn:{session_id}:{slot.session_generation}:msg:{stable_id}"
        return self.world.bridge.commit_inputs(
            workspace_id=WORKSPACE,
            run_id=run_id,
            inputs=lambda _snapshot: (TurnEnded(slot_id=engine_slot_id, fact_key=fact_key),),
        )


@asynccontextmanager
async def serving(
    world: World,
    *,
    after: Sessions | None = None,
    channel: HostChannelBackend | None = None,
    liveness: LivenessCheck | None = None,
) -> AsyncIterator[Sessions]:
    """
    The world's session side, its executors registered until the block ends.

    A SQL world keeps bindings, stable ids and op intents in its database; a fake one
    in memory.

    :param after: The session side of a process that died: the new one keeps its
        sessions and host, which outlive a server process, and on the in-memory
        stores its bindings, stable ids and op intents; its edge watchers and its
        published gate prompts are new.
    :param channel: The run worktree's host channel instead of the canned replies.
    :param liveness: The resync's runner liveness check; none by default.
    """
    events: list[str] = [] if after is None else after.events
    if after is not None and world.db_uri is None:
        bindings: FakeBindings | SqlAlchemySessionBindingStore = after.bindings
        stable_ids: StableIds = after.stable_ids
        intents: WorkspaceOpIntents = after.intents
    elif world.db_uri is None:
        bindings = FakeBindings(
            run_store=world.runs, clock=lambda: world.clock.epoch, reservable=True
        )
        stable_ids = FakeStableIds(events, clock=lambda: world.clock.epoch)
        intents = FakeIntents(events)
    else:
        bindings = SqlAlchemySessionBindingStore(world.db_uri)
        stable_ids = SqlAlchemyStableIdStore(world.db_uri, clock=lambda: world.clock.epoch)
        intents = SqlAlchemyWorkspaceOpIntentStore(world.db_uri)
    dispatch = FakeDispatch(events, owner=USER) if after is None else after.dispatch
    threads = BridgeThreads(world.bridge)
    recorder = TurnFactRecorder(world.bound, world.queue, clock=lambda: world.clock.epoch)
    sessions = Sessions(
        world=world,
        events=events,
        bindings=bindings,
        stable_ids=stable_ids,
        intents=intents,
        dispatch=dispatch,
        edges=FakeEdgeWatcher(events),
        host=FakeHostChannel(events, dict(HOST_REPLIES)) if after is None else after.host,
        facade=BindingFacade(
            bindings=bindings,
            dispatch=dispatch,
            sessions=FakeSessionFacade() if after is None else after.facade.sessions,
        ),
        agents=StanceAgents() if after is None else after.agents,
        threads=threads,
        dispatcher=ToolDispatcher(StoreDecisionPort(world.bridge), PLANNERS),
        recorder=recorder,
        channel=channel if channel is not None or after is None else after.channel,
        liveness=liveness,
    )
    executors = sessions.executors()
    recorder.start()
    try:
        for effect_type, executor in executors.items():
            register_executor(
                effect_type,
                executor,
                replace=True,
                runs_after_terminal=effect_type in (CANCEL_SESSIONS, GATE_WITHDRAW),
            )
        yield sessions
    finally:
        for effect_type, executor in executors.items():
            unregister_executor(effect_type, executor)
        recorder.close()
        threads.close()


@asynccontextmanager
async def restarted(
    crashed: Sessions, *, lease_s: int, liveness: LivenessCheck | None = None
) -> AsyncIterator[Sessions]:
    """
    A new process on the dead one's database, started as the Coral lifespan starts it.

    New engines, stores, bridge and drainer, its clock past the work lease
    (``lease_s``), the bound-session index refreshed and the startup sweep run.

    :param liveness: The new process's runner liveness check.
    """
    assert crashed.world.db_uri is not None
    evict_cached_engine(crashed.world.db_uri)
    world = World.sql(crashed.world.db_uri)
    world.clock.now = crashed.world.clock.now + timedelta(seconds=lease_s + 1)
    async with serving(world, after=crashed, liveness=liveness) as sessions:
        BoundSessionRefresher(sessions.bindings, world.bound).refresh()
        await startup_recovery_sweep(
            world.runs,
            world.queue,
            run_reconciler=sessions.threads.schedule_resync,
            clock=lambda: world.clock.now.timestamp(),
        )
        yield sessions


class Actor(Protocol):
    """A scripted session side that acts on the engine messages it got."""

    async def act(self) -> int: ...

    def reconnect(self, sessions: Sessions) -> None: ...


def is_orchestrator(world: World, run_id: str, session_id: str) -> bool:
    """Whether the session is the orchestrator the run's row names."""
    return world.run(run_id).orchestrator_session_id == session_id


@dataclass(frozen=True)
class Call:
    """One engine tool call the agent made and the reply it got."""

    session_id: str
    operation_id: str
    arguments: Mapping[str, object]
    reply: ToolReply


class Agent:
    """
    A scripted step agent: hands off for every engine message its sessions get.

    It reads the activation id from each message and calls ``coral_submit_handoff``
    through the dispatcher with a fresh operation id, as the session's runner would;
    its sessions call at once. A call told to retry is made again on its next turn;
    any other reply ends it. A call whose reply was lost (the server died) is resent
    under its operation id.

    :param reports: Each step's report by node id; a default names the node and the run.
    :param copies: How many times each call is sent at once under its operation id,
        as a runner resending it.
    """

    def __init__(
        self,
        sessions: Sessions,
        *,
        reports: Mapping[str, str] | None = None,
        copies: int = 1,
    ) -> None:
        self._sessions = sessions
        self._reports = dict(reports or {})
        self._copies = copies
        self._read = 0
        self._pending: dict[str, str] = {}
        self._operations = itertools.count(1)
        self._unanswered: dict[tuple[str, str], str] = {}
        self.calls: list[Call] = []

    def reconnect(self, sessions: Sessions) -> None:
        """Call through a restarted server's session side from now on."""
        self._sessions = sessions

    async def act(self) -> int:
        """Answer every message that arrived and retry calls told to; returns calls made."""
        sends = self._sessions.dispatch.sends
        for message in sends[self._read :]:
            session_id, run_id = str(message["session_id"]), str(message["run_id"])
            if is_orchestrator(self._sessions.world, run_id, session_id):
                continue
            self._pending[session_id] = activation_in(str(message["text"]))
        self._read = len(sends)
        pending = list(self._pending.items())
        replies = await asyncio.gather(
            *(self.submit(session_id, activation_id) for session_id, activation_id in pending)
        )
        for (session_id, _), reply in zip(pending, replies, strict=True):
            if reply.reason not in _RETRY_REASONS:
                del self._pending[session_id]
        return len(pending)

    async def submit(self, session_id: str, activation_id: str) -> ToolReply:
        """One ``coral_submit_handoff`` call from ``session_id``, reporting done."""
        binding = await asyncio.to_thread(
            self._sessions.bindings.find_by_session, WORKSPACE, session_id
        )
        assert binding is not None, f"session {session_id} is not bound"
        node_id = activation_id.split("|", 1)[0]
        arguments = {
            "activation_id": activation_id,
            "status": "done",
            "report": self._reports.get(node_id, f"Finished {node_id} in run {binding.run_id}."),
        }
        key = (session_id, activation_id)
        operation_id = self._unanswered.pop(key, None) or f"op-{next(self._operations)}"
        call = EngineToolCall(
            binding=binding,
            tool=SUBMIT_HANDOFF.name,
            arguments=arguments,
            operation_id=operation_id,
        )
        try:
            replies = await asyncio.gather(
                *(self._sessions.dispatcher.dispatch(call) for _ in range(self._copies))
            )
        except BaseException:
            self._unanswered[key] = operation_id
            raise
        self.calls.extend(
            Call(
                session_id=session_id, operation_id=operation_id, arguments=arguments, reply=reply
            )
            for reply in replies
        )
        return replies[0]


class Orchestrator:
    """
    A scripted orchestrator: chooses at each decision its run's messages ask about.

    It reads the decision id from each request, reminder or re-request sent to a
    run's orchestrator session and calls ``coral_choose_arrow`` through the
    dispatcher with the next scripted label and reason, as the session's runner
    would. Each decision is answered once, however often it is asked; a call told
    to retry is made again on its next turn, and one whose reply was lost is resent
    under its operation id. Past its script it answers nothing.

    :param choices: ``(label, reason)`` for each decision, in the order they are asked.
    """

    def __init__(self, sessions: Sessions, choices: Sequence[tuple[str, str]] = ()) -> None:
        self._sessions = sessions
        self._choices = list(choices)
        self._read = 0
        self._asked: set[str] = set()
        self._pending: dict[tuple[str, str], tuple[str, str]] = {}
        self._operations = itertools.count(1)
        self._unanswered: dict[tuple[str, str], str] = {}
        self.calls: list[Call] = []

    def reconnect(self, sessions: Sessions) -> None:
        """Call through a restarted server's session side from now on."""
        self._sessions = sessions

    async def act(self) -> int:
        """Answer every decision newly asked about and retry calls told to; returns calls made."""
        sends = self._sessions.dispatch.sends
        for message in sends[self._read :]:
            session_id, run_id = str(message["session_id"]), str(message["run_id"])
            if not is_orchestrator(self._sessions.world, run_id, session_id):
                continue
            decision_id = decision_in(str(message["text"]))
            if decision_id in self._asked or not self._choices:
                continue
            self._asked.add(decision_id)
            self._pending[(session_id, decision_id)] = self._choices.pop(0)
        self._read = len(sends)
        pending = list(self._pending.items())
        for (session_id, decision_id), (label, reason) in pending:
            reply = await self.choose(session_id, decision_id, label, reason)
            if reply.reason not in _RETRY_REASONS:
                del self._pending[(session_id, decision_id)]
        return len(pending)

    async def choose(
        self, session_id: str, decision_id: str, label: str, reason: str
    ) -> ToolReply:
        """One ``coral_choose_arrow`` call from ``session_id``."""
        binding = await asyncio.to_thread(
            self._sessions.bindings.find_by_session, WORKSPACE, session_id
        )
        assert binding is not None, f"session {session_id} is not bound"
        arguments = {"decision_id": decision_id, "label": label, "reason": reason}
        key = (session_id, decision_id)
        operation_id = self._unanswered.pop(key, None) or f"choice-{next(self._operations)}"
        call = EngineToolCall(
            binding=binding,
            tool=CHOOSE_ARROW.name,
            arguments=arguments,
            operation_id=operation_id,
        )
        try:
            reply = await self._sessions.dispatcher.dispatch(call)
        except BaseException:
            self._unanswered[key] = operation_id
            raise
        self.calls.append(
            Call(
                session_id=session_id, operation_id=operation_id, arguments=arguments, reply=reply
            )
        )
        return reply
