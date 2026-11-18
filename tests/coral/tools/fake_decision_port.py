"""In-memory ``RunDecisionPort``: the real reducer, one log per run, the port contract as written.

Tests set the store row (status, pause reason, orchestrator) apart from the
engine state, as drift and budget pauses do, and can make the next commits lose
their compare-and-swap. Each entry ``decide`` commits records its ``actor``.
:class:`FakeBindingLookup` serves the bindings the calls name.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from coral.db.enum_codecs import (
    RunPauseReason,
    RunStatus,
    SessionBindingProgress,
    SessionBindingRole,
    SlotRole,
)
from coral.engine import fold, transition
from coral.engine.types import Input, LogEntry, RunState, StartRun
from coral.model.ir import CompiledGraph
from coral.stores.protocols import CoralRun, RunContended, RunNotFound
from coral.stores.session_bindings import SessionBinding
from coral.tools.port import MAX_DECIDE_ATTEMPTS, EngineRefused, Planner, Reply, RunSnapshot
from coral.tools.schemas import ToolReply
from tests.coral.engine.drive import NOW, Driven, drive

WORKSPACE = 7
RUN_ID = "run-1"


def step_binding(
    slot_id: str | None,
    *,
    session_id: str = "sess-1",
    run_id: str = RUN_ID,
    workspace_id: int = WORKSPACE,
    generation: int = 1,
    role: SessionBindingRole = SessionBindingRole.STEP,
    slot_role: SlotRole | None = SlotRole.STEP_AGENT,
    progress: SessionBindingProgress = SessionBindingProgress.INITIALIZED,
) -> SessionBinding:
    """A stored binding of ``session_id`` to engine slot ``slot_id``."""
    return SessionBinding(
        workspace_id=workspace_id,
        session_id=session_id,
        run_id=run_id,
        role=role,
        slot_id=slot_id,
        slot_role=slot_role,
        effect_cksum=b"\x00" * 32,
        session_generation=generation,
        host_id="host-1",
        progress=progress,
        created_at=0,
        updated_at=0,
    )


@dataclass
class FakeBindingLookup:
    """``FreshBindingLookup`` over stored bindings; ``error`` makes every read raise it."""

    # Every read looks at ``rows``: nothing found earlier is kept.
    reads_fresh = True
    rows: dict[tuple[int, str], SessionBinding] = field(default_factory=dict)
    error: Exception | None = None
    reads: list[tuple[int, str]] = field(default_factory=list)

    def add(self, binding: SessionBinding) -> None:
        self.rows[(binding.workspace_id, binding.session_id)] = binding

    def find_by_session(self, workspace_id: int, session_id: str) -> SessionBinding | None:
        self.reads.append((workspace_id, session_id))
        if self.error is not None:
            raise self.error
        return self.rows.get((workspace_id, session_id))


@dataclass
class _Run:
    row: CoralRun
    graph: CompiledGraph
    driven: Driven
    replies: dict[bytes, str] = field(default_factory=dict)
    # Who asked for each logged entry: the calling session for ``decide``, else None.
    actors: list[str | None] = field(default_factory=list)


class InMemoryDecisionPort:
    """Decides through the real ``transition`` and checks ``fold(log) == state`` on every write."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[tuple[int, str], _Run] = {}
        self._conflicts = 0
        self._competing: tuple[Input, ...] = ()
        self._before_write: Callable[[], None] | None = None
        self.find_reply_calls = 0
        self.decide_calls = 0
        self.plan_calls = 0

    def add_run(
        self,
        graph: CompiledGraph,
        inputs: Iterable[Input] = (),
        *,
        run_id: str = RUN_ID,
        workspace_id: int = WORKSPACE,
        auto_ack: bool = True,
    ) -> None:
        """Start a run (store row RUNNING, version 1) and apply ``inputs``."""
        start = StartRun(run_id=run_id, start_key=f"start-{run_id}", version_hash="hash-1")
        driven = _accepted(drive(graph, [start, *inputs], auto_ack=auto_ack), after=None)
        row = CoralRun(
            workspace_id=workspace_id,
            id=run_id,
            workflow_id="demo",
            version_id="version-1",
            status=int(RunStatus.RUNNING),
            version=1,
            next_log_seq=len(driven.log) + 1,
            activation_count=len(driven.state.activations),
            title="Demo",
            engine_version=1,
            state_version=1,
            log_version=1,
            created_at=0,
            updated_at=0,
        )
        with self._lock:
            self._runs[(workspace_id, run_id)] = _Run(
                row=row, graph=graph, driven=driven, actors=[None] * len(driven.log)
            )

    def apply(
        self,
        *inputs: Input,
        run_id: str = RUN_ID,
        workspace_id: int = WORKSPACE,
        auto_ack: bool = False,
    ) -> None:
        """Commit engine inputs as another writer would (the bridge, a timer, an operator)."""
        with self._lock:
            run = self._run(workspace_id, run_id)
            self._drive(run, inputs, auto_ack=auto_ack)

    def set_row(
        self,
        *,
        status: RunStatus,
        pause_reason: RunPauseReason | None = None,
        orchestrator_session_id: str | None = None,
        run_id: str = RUN_ID,
        workspace_id: int = WORKSPACE,
    ) -> None:
        """Change the store row only, as a drift or budget pause does; it bumps the version."""
        with self._lock:
            run = self._run(workspace_id, run_id)
            run.row = dataclasses.replace(
                run.row,
                status=int(status),
                pause_reason=None if pause_reason is None else int(pause_reason),
                orchestrator_session_id=orchestrator_session_id,
            )
            self._bump(run)

    def before_next_write(self, action: Callable[[], None]) -> None:
        """Run ``action`` (say, ``set_row``) between the next commit's plan and its write."""
        with self._lock:
            self._before_write = action

    def lose_next_commits(self, count: int = 1, *competing: Input) -> None:
        """The next ``count`` commits find the run changed; ``competing`` is applied first."""
        with self._lock:
            self._conflicts = count
            self._competing = competing

    def row(self, *, run_id: str = RUN_ID, workspace_id: int = WORKSPACE) -> CoralRun:
        with self._lock:
            return self._run(workspace_id, run_id).row

    def state(self, *, run_id: str = RUN_ID, workspace_id: int = WORKSPACE) -> RunState:
        with self._lock:
            return self._run(workspace_id, run_id).driven.state

    def log(self, *, run_id: str = RUN_ID, workspace_id: int = WORKSPACE) -> tuple[LogEntry, ...]:
        with self._lock:
            return self._run(workspace_id, run_id).driven.log

    def stored_replies(
        self, *, run_id: str = RUN_ID, workspace_id: int = WORKSPACE
    ) -> dict[bytes, str]:
        with self._lock:
            return dict(self._run(workspace_id, run_id).replies)

    def actors(
        self, *, run_id: str = RUN_ID, workspace_id: int = WORKSPACE
    ) -> list[tuple[str, str | None]]:
        """Each logged entry's input kind and who asked for it."""
        with self._lock:
            run = self._run(workspace_id, run_id)
            return [
                (entry.input.kind, actor)
                for entry, actor in zip(run.driven.log, run.actors, strict=True)
            ]

    def assert_folds(self) -> None:
        """Every run's state is its log replayed."""
        with self._lock:
            for run in self._runs.values():
                assert fold(run.graph, run.driven.log) == run.driven.state

    def find_reply(self, workspace_id: int, run_id: str, cksum: bytes) -> ToolReply | None:
        with self._lock:
            self.find_reply_calls += 1
            run = self._runs.get((workspace_id, run_id))
            stored = None if run is None else run.replies.get(cksum)
        return None if stored is None else ToolReply.from_json(stored)

    def decide(
        self,
        workspace_id: int,
        run_id: str,
        planner: Planner,
        cksum: bytes,
        *,
        actor: str | None = None,
    ) -> ToolReply:
        with self._lock:
            self.decide_calls += 1
        for _ in range(MAX_DECIDE_ATTEMPTS):
            with self._lock:
                run = self._run(workspace_id, run_id)
                stored = run.replies.get(cksum)
                if stored is not None:
                    return ToolReply.from_json(stored)
                snapshot = RunSnapshot(run=run.row, graph=run.graph, state=run.driven.state)
                self.plan_calls += 1
            plan = planner(snapshot)
            if isinstance(plan, Reply):
                return plan.reply
            state = snapshot.state
            entries: list[LogEntry] = []
            for item in plan.inputs:
                moved = transition(snapshot.graph, state, item, NOW)
                if moved.entry.rejection is not None:
                    if plan.observation:
                        return plan.reply
                    raise EngineRefused(moved.entry.rejection)
                entries.append(moved.entry)
                state = moved.state
            with self._lock:
                action, self._before_write = self._before_write, None
            if action is not None:
                action()
            with self._lock:
                run = self._run(workspace_id, run_id)
                if self._conflicts:
                    self._conflicts -= 1
                    self._drive(run, self._competing, auto_ack=False)
                    self._competing = ()
                if run.row.version != snapshot.run.version:
                    continue
                run.driven = Driven(state=state, log=(*run.driven.log, *entries))
                run.actors.extend([actor] * len(entries))
                assert fold(run.graph, run.driven.log) == state
                self._bump(run)
                run.replies[cksum] = plan.reply.to_json()
                return plan.reply
        raise RunContended(f"run {run_id!r} kept changing")

    def _run(self, workspace_id: int, run_id: str) -> _Run:
        run = self._runs.get((workspace_id, run_id))
        if run is None:
            raise RunNotFound(f"Run {run_id!r} not found in workspace {workspace_id}")
        return run

    def _drive(self, run: _Run, inputs: Iterable[Input], *, auto_ack: bool) -> None:
        run.driven = _accepted(
            drive(run.graph, list(inputs), auto_ack=auto_ack, after=run.driven), after=run.driven
        )
        run.actors.extend([None] * (len(run.driven.log) - len(run.actors)))
        self._bump(run)

    @staticmethod
    def _bump(run: _Run) -> None:
        run.row = dataclasses.replace(
            run.row,
            version=run.row.version + 1,
            next_log_seq=len(run.driven.log) + 1,
            activation_count=len(run.driven.state.activations),
        )


def _accepted(driven: Driven, *, after: Driven | None) -> Driven:
    """Test setup must not be refused by the engine."""
    added = driven.log[len(after.log) if after is not None else 0 :]
    refused = [entry for entry in added if entry.rejection is not None]
    assert not refused, refused
    return driven
