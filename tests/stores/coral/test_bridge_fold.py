"""A run's stored engine log folds to its stored state, on every DB lane.

Property-style, one run per seed (the seed is in the test id): the run, on SQL
stores, goes through a random interleaving of drains, handoffs, choices, duplicate
feeds, resyncs, completed and failed turns (529, 429, 401), user pauses and resumes,
clock jumps, process restarts and the odd cancel, and then to its end. After every
step the log read back from the database replays entry by entry to the state the
bridge loads, and the run and slot rows equal its projection; a restart folds the
same state from a cold cache. A version of the workflow pinned after the start does
not change what the run folds. The golden log, stored through the run store, still
folds to its recorded state.
"""

from __future__ import annotations

import dataclasses
import json
import os
import random
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from coral.bridge.codec import decode_entries
from coral.bridge.commit import build_commit
from coral.bridge.config import engine_config_for
from coral.bridge.fold import EngineStateCache
from coral.db import WorkRow
from coral.db.enum_codecs import WorkKind, WorkStatus
from coral.engine import empty_state
from coral.engine.types import TERMINAL_STATUSES, PauseRun, RunState, SessionFailed
from coral.model.ir import CompiledGraph
from coral.omni.server.turn_facts import BoundSessionRefresher
from coral.stores.protocols import LogEntryDraft, RunLogEntry, Transition
from coral.stores.runs import SqlAlchemyCoralRunStore
from omnigent.db.utils import get_or_create_engine
from tests.coral.bridge._scripted_runs import replay
from tests.coral.bridge._world import (
    DEFINITION,
    START_KEY,
    USER,
    WORKSPACE,
    Agent,
    Orchestrator,
    Sessions,
    World,
    finished,
    run_id_for,
    run_spec,
    serving,
    start,
)
from tests.coral.workflow_builders import compile_text, fixture_text
from tests.stores.coral._faults import fresh_process

RUN_ID = run_id_for()
GOLDEN = Path(__file__).parents[2] / "coral" / "bridge" / "fixtures" / "engine_log_v1.json"
# The external lanes, where each run costs more, run five seeds picked for what they
# reach: choices, user pauses, failed turns (529, 429, 401), timers, failure pauses and a
# cancel. A seed that stops reaching what it was picked for fails, so the set is picked again.
EXTERNAL_SEEDS: dict[int, frozenset[str]] = {
    1: frozenset({"choose_arrow", "paused:user", "resume_run"}),
    6: frozenset({"session_failed:infra.transient", "timer_due", "paused:plan_limit"}),
    15: frozenset({"choose_arrow", "session_failed:plan.usage_limit", "timer_due"}),
    16: frozenset({"session_failed:auth", "paused:auth", "resume_run", "turn_ended"}),
    17: frozenset({"session_failed:auth", "paused:auth", "cancel_run"}),
}
SEEDS = sorted(EXTERNAL_SEEDS) if os.environ.get("OMNIGENT_TEST_DB_URI") else range(20)
STEPS = 40
# Failed turns as claude-sdk reports them: a code and the error text.
FAILURES = (
    ("RuntimeError", 'API Error: 529 {"type":"error","error":{"type":"overloaded_error"}}'),
    ("RuntimeError", 'API Error: 429 {"type":"error","error":{"type":"rate_limit_error"}}'),
    ("claude_sdk_auth_failed", "Invalid API key · Please run /login"),
)
CHOICES = [("revise", "Add the missing tests."), ("approved", "The tests cover it.")]


class SeededRun:
    """One run driven by one seed, through server processes that the run outlives."""

    def __init__(self, sessions: Sessions, stack: AsyncExitStack, rng: random.Random) -> None:
        self.sessions = sessions
        self.stack = stack
        self.rng = rng
        self.actors: list[Agent | Orchestrator] = [Agent(sessions)]
        # Each pause reason the run was seen paused for.
        self.paused: set[str] = set()

    @classmethod
    async def serve(cls, db_uri: str, rng: random.Random) -> SeededRun:
        stack = AsyncExitStack()
        return cls(await stack.enter_async_context(serving(World.sql(db_uri))), stack, rng)

    @property
    def world(self) -> World:
        return self.sessions.world

    def state(self) -> RunState:
        return self.world.bridge.load(workspace_id=WORKSPACE, run_id=RUN_ID).state

    def note(self, state: RunState) -> RunState:
        """Remember the reasons ``state`` is paused for."""
        self.paused.update(f"paused:{cause.reason}" for cause in state.causes)
        return state

    def reached(self) -> set[str]:
        """The kinds of the inputs the run took, failed turns by class, and its pauses."""
        reached = set(self.paused)
        for entry in decode_entries(self.world.engine_log(RUN_ID)):
            reached.add(entry.input.kind)
            if isinstance(entry.input, SessionFailed):
                reached.add(f"session_failed:{entry.input.failure_class}")
        return reached

    def working(self) -> list[str]:
        return [slot.id for slot in self.state().slots if slot.status == "working"]

    async def act(self) -> None:
        """One step of the run, chosen by the seed."""
        steps: dict[str, tuple[float, Callable[[], Awaitable[object]]]] = {
            "drain one": (5, self.sessions.drainer.drain_once),
            "drain": (2, self.sessions.drain),
            "actors act": (4, self._actors_act),
            "feed again": (1, self._feed_again),
            "resync": (1, self._resync),
            "turn completes": (1, self._turn_completes),
            "turn fails": (1, self._turn_fails),
            "pause": (1, self._pause),
            "resume": (2, self._resume),
            "time passes": (2, self._time_passes),
            "restart": (1, self.restart),
            # A cancel ends the run, so it comes rarely.
            "cancel": (0.2, self._cancel),
        }
        name = self.rng.choices(list(steps), [weight for weight, _ in steps.values()])[0]
        await steps[name][1]()

    async def finish(self) -> RunState:
        """Run to an end: resume every pause and let time pass until it completes."""
        for _ in range(12):
            state = self.note(self.state())
            if state.status in TERMINAL_STATUSES:
                return state
            if state.status == "paused":
                await self._resume()
            self.world.clock.advance(60)
            await self.sessions.run(*self.actors)
        raise AssertionError(f"run {RUN_ID} did not end: {self.state().status}")

    async def restart(self) -> None:
        """A new process on the same database: its fold of the run starts from nothing."""
        warm = self.state()
        crashed = self.sessions
        await self.stack.aclose()
        assert crashed.world.db_uri is not None
        fresh_process(crashed.world.db_uri)
        world = World.sql(crashed.world.db_uri)
        world.clock.now = crashed.world.clock.now
        self.stack = AsyncExitStack()
        self.sessions = await self.stack.enter_async_context(serving(world, after=crashed))
        BoundSessionRefresher(self.sessions.bindings, world.bound).refresh()
        for actor in self.actors:
            actor.reconnect(self.sessions)
        assert self.state() == warm

    async def _actors_act(self) -> None:
        for actor in self.actors:
            await actor.act()

    async def _feed_again(self) -> None:
        """The outcome of an effect already finished is fed once more."""
        assert self.world.db_uri is not None
        with Session(get_or_create_engine(self.world.db_uri)) as db:
            ids = sorted(
                db.scalars(
                    select(WorkRow.id).where(
                        WorkRow.workspace_id == WORKSPACE,
                        WorkRow.run_id == RUN_ID,
                        WorkRow.kind == int(WorkKind.EFFECT),
                        WorkRow.status.in_((int(WorkStatus.SUCCEEDED), int(WorkStatus.FAILED))),
                    )
                )
            )
        if ids:
            item = self.world.queue.get_work([self.rng.choice(ids)], workspace_id=WORKSPACE)[0]
            self.world.bridge.feed(finished(item))

    async def _resync(self) -> None:
        self.world.bridge.resync_run(workspace_id=WORKSPACE, run_id=RUN_ID)

    async def _turn_completes(self) -> None:
        working = self.working()
        if working:
            self.sessions.complete_turn(RUN_ID, self.rng.choice(working))

    async def _turn_fails(self) -> None:
        working = self.working()
        if working:
            code, message = self.rng.choice(FAILURES)
            self.sessions.fail_turn(RUN_ID, self.rng.choice(working), message, code=code)

    async def _pause(self) -> None:
        if self.state().status == "running":
            self.world.bridge.commit_inputs(
                workspace_id=WORKSPACE,
                run_id=RUN_ID,
                inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
                actor=USER,
            )

    async def _resume(self) -> None:
        if self.state().status == "paused":
            self.world.bridge.resume_run(workspace_id=WORKSPACE, run_id=RUN_ID, actor=USER)

    async def _time_passes(self) -> None:
        self.world.clock.advance(self.rng.choice((5, 30, 120, 600, 1900)))

    async def _cancel(self) -> None:
        self.world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=RUN_ID, actor=USER)


def _assert_log_folds(world: World, *, version_id: str, content_hash: str) -> RunState:
    """Replaying the stored log reproduces each entry and the loaded state; rows match it."""
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=RUN_ID)
    assert (snapshot.store.run.version_id, snapshot.graph.content_hash) == (
        version_id,
        content_hash,
    )
    steps = replay(snapshot.graph, decode_entries(world.engine_log(RUN_ID)), snapshot.config)
    assert (steps[-1].after if steps else empty_state()) == snapshot.state
    assert build_commit(snapshot, (), now=world.clock()).is_empty
    return snapshot.state


@pytest.mark.parametrize("seed", SEEDS, ids=lambda seed: f"seed-{seed}")
async def test_a_runs_stored_log_folds_to_its_state_through_any_interleaving(
    coral_db_uri: str, seed: int
) -> None:
    workflow = ("two_steps", "loop")[seed % 2]
    driven = await SeededRun.serve(coral_db_uri, random.Random(seed))
    try:
        if workflow == "loop":
            driven.actors.append(Orchestrator(driven.sessions, CHOICES))
        text = fixture_text(workflow)
        run = start(driven.world, text)
        pinned = {"version_id": run.version_id, "content_hash": compile_text(text)[0].content_hash}
        # A later save of the workflow pins another version; the run keeps its own.
        edited = text.replace("goal: Implement the change", "goal: Implement it differently")
        assert edited != text
        later = driven.world.versions.pin(
            workspace_id=WORKSPACE,
            workflow_id=DEFINITION,
            graph=compile_text(edited)[0],
            yaml_text=edited,
            created_by=USER,
        )
        assert later.id != run.version_id
        for _ in range(STEPS):
            await driven.act()
            state = driven.note(_assert_log_folds(driven.world, **pinned))
            if state.status in TERMINAL_STATUSES:
                break
        final = await driven.finish()
        assert _assert_log_folds(driven.world, **pinned) == final
        await driven.restart()
        _assert_log_folds(driven.world, **pinned)
        assert EXTERNAL_SEEDS.get(seed, frozenset()) <= driven.reached()
    finally:
        await driven.stack.aclose()


def test_the_golden_log_stored_through_the_run_store_folds_to_its_recorded_state(
    coral_db_uri: str,
) -> None:
    golden = json.loads(GOLDEN.read_text())
    graph = CompiledGraph.model_validate_json(golden["pinned_graph"]["compiled_json"])
    spec = run_spec(engine_config=golden["engine_config"])
    runs = SqlAlchemyCoralRunStore(coral_db_uri)
    run = runs.start_run(spec, start_key=START_KEY, now=1)
    assert (run.workspace_id, run.id) == (golden["workspace_id"], golden["run_id"])
    rows = [RunLogEntry(**row) for row in golden["log"]]
    # One row per commit, as the bridge wrote them.
    for row in rows:
        draft = LogEntryDraft(
            **{field.name: getattr(row, field.name) for field in dataclasses.fields(LogEntryDraft)}
        )
        runs.apply_transition(
            run.id, row.run_version - 1, Transition(logs=(draft,)), workspace_id=WORKSPACE
        )

    fresh_process(coral_db_uri)
    reread = SqlAlchemyCoralRunStore(coral_db_uri)
    stored = reread.read_engine_log(
        run.id, workspace_id=WORKSPACE, max_run_version=golden["version"]
    )
    assert stored == rows
    folded = EngineStateCache(reread).fold(
        workspace_id=WORKSPACE,
        run_id=run.id,
        version=golden["version"],
        graph=graph,
        config=engine_config_for(spec),
    )
    assert folded.state == RunState.model_validate(golden["state"])
    assert folded.last_seq == rows[-1].seq
