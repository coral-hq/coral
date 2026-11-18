"""A bridge over stores, with a manual clock, for the bridge's write-side tests.

``World.fake`` runs on the in-memory stores; ``World.sql`` on one database URI.
Both pin workflow versions in SQL, the only version store there is.
:func:`serving` adds the session side: the real executors over fake sessions,
a drainer with the bridge's hook and hold policy, and the engine tools, which a
scripted :class:`Agent` calls.
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
from typing import Any

from sqlalchemy import create_engine

from coral.bridge.codec import decode_entries
from coral.bridge.config import ENGINE_LOG_PAGE, freeze_engine_config
from coral.bridge.executors import (
    BridgeThreads,
    bridge_hold_policy,
    run_resync_executor,
    timer_executor,
)
from coral.bridge.keys import slot_session_id
from coral.bridge.mapping import RUN_RESYNC, TIMER
from coral.bridge.port import StoreDecisionPort
from coral.bridge.service import BridgeCommit, EngineBridge
from coral.bridge.start import start_engine_run
from coral.db import CoralBase
from coral.db.enum_codecs import SessionBindingProgress, WorkKind, WorkStatus
from coral.engine import fold
from coral.engine.machines.slot import find_slot
from coral.engine.types import RunState, TurnEnded
from coral.model.ids import derived_id
from coral.omni.protocols import SessionCreateRequest, SessionRef, SessionState
from coral.queue import FinishedWork, SqlAlchemyCoralQueueStore
from coral.queue.drainer import WorkDrainer
from coral.queue.executors import EffectExecutor, register_executor, unregister_executor
from coral.recovery.drift import DriftPauser
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
from coral.tools.catalog import SUBMIT_HANDOFF
from coral.tools.dispatch import EngineToolCall, ToolDispatcher
from coral.tools.handlers import PLANNERS
from coral.tools.schemas import ToolReply
from coral.workspace.run_worktree import run_branch_name
from tests.coral.omni.fakes import FakeSessionFacade
from tests.coral.slots._close_fakes import FakeDispatch, FakeEdgeWatcher, FakeStableIds
from tests.coral.workflow_builders import compile_text, fixture_text
from tests.coral.workspace._executor_fakes import (
    FakeBindings,
    FakeChannels,
    FakeHostChannel,
    FakeIntents,
    RecordingScopeRunner,
)

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
    # The database of a SQL world; ``None`` on the in-memory stores.
    db_uri: str | None = None

    @classmethod
    def fake(cls, tmp_path: Path) -> World:
        engine = create_engine(f"sqlite:///{tmp_path / 'versions.db'}")
        CoralBase.metadata.create_all(engine)
        runs = FakeRunStore(default_workspace_id=WORKSPACE)
        return cls._build(
            runs, FakeQueueStore(run_store=runs), SqlAlchemyWorkflowVersionStore(engine)
        )

    @classmethod
    def sql(cls, db_uri: str) -> World:
        return cls._build(
            SqlAlchemyCoralRunStore(db_uri),
            SqlAlchemyCoralQueueStore(db_uri),
            SqlAlchemyWorkflowVersionStore(db_uri),
            db_uri=db_uri,
        )

    @classmethod
    def _build(
        cls,
        runs: RunStore,
        queue: QueueStore,
        versions: SqlAlchemyWorkflowVersionStore,
        *,
        db_uri: str | None = None,
    ) -> World:
        clock = ManualClock()
        bridge = EngineBridge(run_store=runs, queue_store=queue, versions=versions, clock=clock)
        return cls(
            runs=runs, queue=queue, versions=versions, clock=clock, bridge=bridge, db_uri=db_uri
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


# ── the session side ────────────────────────────────────────────────────────

# What the run worktree's host answers a writer's close: an unchanged tree, then one commit.
HOST_REPLIES: dict[str, Mapping[str, object]] = {
    "fingerprint": {"level": "L1", "digest": "d" * 64, "head": "1" * 40, "dirty_count": 1},
    "head": {"head": "1" * 40, "branch": None, "merge_in_progress": False},
    "commit": {"commit": "2" * 40, "empty": False},
    "diff_stat": {"files_changed": 1, "insertions": 1, "deletions": 0, "paths": ["a"]},
}
_ACTIVATION_ID = re.compile(r'activation_id ("(?:[^"\\]|\\.)*")')
# Replies an agent told to retry gets; it calls again on its next turn.
_RETRY_REASONS = frozenset({"evaluation_in_progress"})


def activation_in(text: str) -> str:
    """The activation id an engine message asks the agent to hand off for (its last mention)."""
    found = _ACTIVATION_ID.findall(text)
    assert found, "the engine message names no activation id"
    return json.loads(found[-1])


class StanceAgents:
    """A ``StepAgentResolver`` that answers one agent per stance and records each step."""

    def __init__(self) -> None:
        self.resolved: list[dict[str, Any]] = []

    async def resolve(self, **step: Any) -> str:
        self.resolved.append(step)
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
    The engine tools are decided by the store port through the real dispatcher.
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
    drainer: WorkDrainer = field(init=False)
    before_feed: Callable[[FinishedWork], Awaitable[None]] | None = None

    def __post_init__(self) -> None:
        self.drainer = WorkDrainer(
            self.world.queue,
            worker_id="worker-1",
            kinds=(int(WorkKind.EFFECT), int(WorkKind.TIMER), int(WorkKind.SIGNAL)),
            clock=lambda: self.world.clock.now.timestamp(),
            rng=lambda: 0.5,
            hold_policy=bridge_hold_policy,
            on_finished=self._finished,
        )

    async def _finished(self, finished: FinishedWork) -> None:
        if self.before_feed is not None:
            await self.before_feed(finished)
        await self.threads.feed(finished)

    def executors(self) -> dict[str, EffectExecutor]:
        """The session engine's executors and the bridge's own, as the lifespan registers them."""
        world, scope = self.world, RecordingScopeRunner()
        pauser = DriftPauser(world.runs, engine=self.threads)
        channels = FakeChannels(self.host, scope)
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
            TIMER: timer_executor(self.threads),
            RUN_RESYNC: run_resync_executor(self.threads),
        }

    async def drain(self) -> int:
        """Run every item due now, held ones excepted; returns how many ran."""
        ran = 0
        while await self.drainer.drain_once() is not None:
            ran += 1
        return ran

    async def run(self, agent: Agent | None = None, *, rounds: int = 50) -> None:
        """Drain and let ``agent`` act until neither has anything left to do."""
        for _ in range(rounds):
            drained = await self.drain()
            acted = 0 if agent is None else await agent.act()
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
async def serving(world: World) -> AsyncIterator[Sessions]:
    """
    The world's session side, its executors registered until the block ends.

    A SQL world keeps bindings, stable ids and op intents in its database; a fake one
    in memory.
    """
    events: list[str] = []
    if world.db_uri is None:
        bindings: FakeBindings | SqlAlchemySessionBindingStore = FakeBindings(
            run_store=world.runs, clock=lambda: world.clock.epoch, reservable=True
        )
        stable_ids: StableIds = FakeStableIds(events)
        intents: WorkspaceOpIntents = FakeIntents(events)
    else:
        bindings = SqlAlchemySessionBindingStore(world.db_uri)
        stable_ids = SqlAlchemyStableIdStore(world.db_uri)
        intents = SqlAlchemyWorkspaceOpIntentStore(world.db_uri)
    dispatch = FakeDispatch(events, owner=USER)
    threads = BridgeThreads(world.bridge)
    sessions = Sessions(
        world=world,
        events=events,
        bindings=bindings,
        stable_ids=stable_ids,
        intents=intents,
        dispatch=dispatch,
        edges=FakeEdgeWatcher(events),
        host=FakeHostChannel(events, dict(HOST_REPLIES)),
        facade=BindingFacade(bindings=bindings, dispatch=dispatch),
        agents=StanceAgents(),
        threads=threads,
        dispatcher=ToolDispatcher(StoreDecisionPort(world.bridge), PLANNERS),
    )
    executors = sessions.executors()
    try:
        for effect_type, executor in executors.items():
            register_executor(
                effect_type,
                executor,
                replace=True,
                runs_after_terminal=effect_type == CANCEL_SESSIONS,
            )
        yield sessions
    finally:
        for effect_type, executor in executors.items():
            unregister_executor(effect_type, executor)
        threads.close()


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
    any other reply ends it.

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
        self.calls: list[Call] = []

    async def act(self) -> int:
        """Answer every message that arrived and retry calls told to; returns calls made."""
        sends = self._sessions.dispatch.sends
        for message in sends[self._read :]:
            self._pending[str(message["session_id"])] = activation_in(str(message["text"]))
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
        operation_id = f"op-{next(self._operations)}"
        call = EngineToolCall(
            binding=binding,
            tool=SUBMIT_HANDOFF.name,
            arguments=arguments,
            operation_id=operation_id,
        )
        replies = await asyncio.gather(
            *(self._sessions.dispatcher.dispatch(call) for _ in range(self._copies))
        )
        self.calls.extend(
            Call(
                session_id=session_id, operation_id=operation_id, arguments=arguments, reply=reply
            )
            for reply in replies
        )
        return replies[0]
