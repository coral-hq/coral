"""Run-status commits racing Coral's policy builds: every commit applies to the next call.

A build that read the run before a commit may still answer from that read, but
nothing it read is kept, so the next call sees the commit. The SQL case runs
the read on a worker thread, as every enforcement path does, against the real
run and binding stores wired by ``_wire_guards``. The storms use a frozen clock,
so a status that should have been dropped would be served for the rest of the
test instead of expiring.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import pytest

from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.db.migrate import ensure_coral_schema
from coral.omni.policies.bindings_cache import CachedBindingLookup
from coral.omni.policies.state import RunStatusCache, RunStatusView
from coral.omni.server.plugin import _wire_guards
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun, RunStartSpec, Transition
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.stores.session_bindings import SessionBindingDraft, SqlAlchemySessionBindingStore
from omnigent.db.db_models import workspace_scope
from omnigent.policies.types import PolicyResult
from omnigent.runtime.policies.builder import build_policy_engine
from omnigent.runtime.policies.engine import PolicyEngine
from omnigent.spec.types import PolicyAction
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests.coral.omni.policies.conftest import CoralPolicies, coral_spec, tool_call
from tests.coral.tools.fake_decision_port import WORKSPACE, FakeBindingLookup, step_binding

WAIT_S = 30.0


def _transition(status: RunStatus, reason: RunPauseReason | None) -> Transition:
    return Transition(
        status=int(status),
        pause_reason=None if reason is None else int(reason),
        clear_pause_reason=reason is None,
    )


@dataclass
class _SqlCoral:
    """Coral's guards over the real run and binding stores, one step session per run."""

    conversations: SqlAlchemyConversationStore
    runs: SqlAlchemyCoralRunStore
    bindings: SqlAlchemySessionBindingStore

    def start_run(self) -> str:
        run = self.runs.start_run(RunStartSpec("review", "v1", "Run", "", workspace_id=WORKSPACE))
        self.set_status(run.id, RunStatus.RUNNING)
        return run.id

    def set_status(
        self, run_id: str, status: RunStatus, reason: RunPauseReason | None = None
    ) -> None:
        _, version = self.runs.load_run_state(run_id, workspace_id=WORKSPACE)
        self.runs.apply_transition(
            run_id, version, _transition(status, reason), workspace_id=WORKSPACE
        )

    def bound_step(self, run_id: str) -> str:
        with workspace_scope(WORKSPACE):
            session_id = self.conversations.create_conversation().id
        self.bindings.reserve(
            SessionBindingDraft(
                workspace_id=WORKSPACE,
                session_id=session_id,
                run_id=run_id,
                role="step",
                effect_key=f"{run_id}:2:create_session:review/item-0/m0",
                slot_id="review/item-0/m0",
                slot_role="step_agent",
            )
        )
        return session_id

    def engine(self, session_id: str) -> PolicyEngine:
        with workspace_scope(WORKSPACE):
            return build_policy_engine(
                spec=coral_spec(),
                conversation_id=session_id,
                conversation_store=self.conversations,
            )


@pytest.fixture
async def sql_coral(db_uri: str) -> AsyncIterator[_SqlCoral]:
    ensure_coral_schema(db_uri)
    coral = _SqlCoral(
        conversations=SqlAlchemyConversationStore(db_uri),
        runs=SqlAlchemyCoralRunStore(db_uri),
        bindings=SqlAlchemySessionBindingStore(db_uri),
    )
    async with AsyncExitStack() as stack:
        _wire_guards(run_store=coral.runs, bindings=coral.bindings, stack=stack)
        yield coral


class _HeldRead:
    """Makes the next run read wait, after loading the row, until the test releases it."""

    def __init__(self, runs: SqlAlchemyCoralRunStore, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        self.loaded = threading.Event()
        self.released = threading.Event()
        self._armed = False
        read = runs.get_run

        def get_run(run_id: str, *, workspace_id: int | None = None) -> CoralRun | None:
            self.count += 1
            row = read(run_id, workspace_id=workspace_id)
            if self._armed:
                self._armed = False
                self.loaded.set()
                assert self.released.wait(WAIT_S), "the test never released the held read"
            return row

        monkeypatch.setattr(runs, "get_run", get_run)

    def arm(self) -> None:
        self.loaded.clear()
        self.released.clear()
        self._armed = True


async def test_a_commit_while_a_build_reads_the_run_applies_to_the_next_call(
    sql_coral: _SqlCoral, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = sql_coral.start_run()
    step = sql_coral.bound_step(run_id)
    held = _HeldRead(sql_coral.runs, monkeypatch)
    paused = (RunStatus.PAUSED, RunPauseReason.DRIFT)
    running = (RunStatus.RUNNING, None)
    rounds = [
        # (state before, committed while the read is held, held build's verdict, next call's)
        (running, paused, PolicyAction.ALLOW, PolicyAction.DENY),
        (paused, running, PolicyAction.DENY, PolicyAction.ALLOW),
        (running, (RunStatus.CANCELLED, None), PolicyAction.ALLOW, PolicyAction.DENY),
    ]

    for count, (before, (status, reason), held_verdict, next_verdict) in enumerate(rounds):
        # Committing the state again drops any kept status, so the held build must read.
        sql_coral.set_status(run_id, *before)
        held.arm()
        build = asyncio.ensure_future(asyncio.to_thread(sql_coral.engine, step))
        assert await asyncio.to_thread(held.loaded.wait, WAIT_S)
        # The commit's hook runs while the build still holds the row it loaded.
        sql_coral.set_status(run_id, status, reason)
        held.released.set()
        engine = await build
        # The held build answers from the row it read before the commit ...
        assert (await engine.evaluate(tool_call("Bash"))).action == held_verdict
        # ... but kept nothing: the next call reads the store again and sees the commit.
        result = await sql_coral.engine(step).evaluate(tool_call("Bash"))
        assert result.action == next_verdict, status
        assert held.count == 2 * (count + 1)
        if next_verdict == PolicyAction.DENY:
            assert result.deciding_policies == ["__coral_run_guard"]


@dataclass
class _Commits:
    """The writer's progress; readers check only reads that no commit overlapped."""

    started: int = 0
    done: int = 0
    paused: dict[str, bool] = field(default_factory=dict)
    clean_reads: int = 0
    mismatches: list[tuple[str, bool, object]] = field(default_factory=list)
    errors: list[BaseException] = field(default_factory=list)
    checked: threading.Condition = field(default_factory=threading.Condition)
    stop: threading.Event = field(default_factory=threading.Event)

    def read(
        self, run_id: str, observe: Callable[[], object], is_paused: Callable[[Any], bool]
    ) -> None:
        """Observe *run_id*; when no commit overlapped, compare with the committed state."""
        before = (self.started, self.done)
        expected = self.paused[run_id]
        observed = observe()
        if (self.started, self.done) != before or before[0] != before[1]:
            return
        if is_paused(observed) != expected:
            self.mismatches.append((run_id, expected, observed))
        with self.checked:
            self.clean_reads += 1
            self.checked.notify_all()

    def commit(self, run_id: str, paused: bool, apply: Callable[[], None], readers: int) -> None:
        """Commit through *apply*, then wait until *readers* clean reads have checked it."""
        self.started += 1
        apply()
        self.paused[run_id] = paused
        self.done += 1
        with self.checked:
            target = self.clean_reads + readers
            assert self.checked.wait_for(
                lambda: self.clean_reads >= target or bool(self.errors), WAIT_S
            ), "readers made no clean read after a commit"

    def reader(self, body: Callable[[], None]) -> Callable[[], None]:
        def run() -> None:
            try:
                while not self.stop.is_set():
                    body()
            except BaseException as exc:  # reported by the test
                self.errors.append(exc)
                with self.checked:
                    self.checked.notify_all()

        return run


@pytest.fixture
def fast_thread_switches() -> Iterator[None]:
    """Switch threads every microsecond, so reads interleave with commits far more often."""
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(interval)


def _run_threads(
    commits: _Commits, readers: list[Callable[[], None]], write: Callable[[], None]
) -> None:
    threads = [threading.Thread(target=commits.reader(body)) for body in readers]
    for thread in threads:
        thread.start()
    try:
        write()
    finally:
        commits.stop.set()
        for thread in threads:
            thread.join(WAIT_S)
    assert not any(thread.is_alive() for thread in threads)
    assert commits.errors == []
    assert commits.mismatches == []


def test_threads_building_policies_see_each_pause_and_resume_on_their_next_call(
    wired_policies: CoralPolicies,
) -> None:
    runs = [wired_policies.run(RunStatus.RUNNING) for _ in range(3)]
    sessions = dict(zip(runs, (wired_policies.session(run_id) for run_id in runs), strict=True))
    spec = coral_spec()
    commits = _Commits(paused=dict.fromkeys(runs, False))
    builds = 0

    def build_and_call(session_id: str, loop: asyncio.AbstractEventLoop) -> PolicyResult:
        nonlocal builds
        builds += 1
        engine = wired_policies.engine(spec, session_id)
        return loop.run_until_complete(engine.evaluate(tool_call("Bash")))

    def reader() -> None:
        loop = asyncio.new_event_loop()
        try:
            for run_id, session_id in sessions.items():
                commits.read(
                    run_id,
                    lambda session_id=session_id: build_and_call(session_id, loop),
                    lambda result: result.action == PolicyAction.DENY,
                )
        finally:
            loop.close()

    def write() -> None:
        for index in range(30):
            run_id = runs[index % len(runs)]
            paused = not commits.paused[run_id]
            commits.commit(
                run_id,
                paused,
                lambda run_id=run_id, paused=paused: wired_policies.set_status(
                    run_id,
                    RunStatus.PAUSED if paused else RunStatus.RUNNING,
                    reason=RunPauseReason.DRIFT if paused else None,
                ),
                readers=6,
            )

    _run_threads(commits, [reader] * 6, write)
    assert commits.clean_reads >= 30 * 6
    assert builds > commits.clean_reads  # some builds overlapped a commit
    # Every read released its in-flight mark.
    assert wired_policies.statuses._reads == {}


@pytest.mark.usefixtures("fast_thread_switches")
def test_status_reads_racing_commits_never_keep_a_replaced_status() -> None:
    runs = FakeRunStore(default_workspace_id=WORKSPACE)
    run_ids = []
    for _ in range(4):
        run = runs.start_run(RunStartSpec("wf", "v1", "Run", "", workspace_id=WORKSPACE))
        runs.apply_transition(
            run.id, 1, _transition(RunStatus.RUNNING, None), workspace_id=WORKSPACE
        )
        run_ids.append(run.id)
    # Frozen: only a commit can drop an entry, so a kept stale status would stay wrong.
    statuses = RunStatusCache(runs, clock=lambda: 1_000.0, max_entries=3)
    unhook = runs.register_post_commit(statuses.invalidate)
    commits = _Commits(paused=dict.fromkeys(run_ids, False))

    def reader() -> None:
        for run_id in run_ids:
            commits.read(
                run_id,
                lambda run_id=run_id: statuses.status(WORKSPACE, run_id),
                lambda view: view == RunStatusView("paused", "user"),
            )

    def write() -> None:
        for index in range(300):
            run_id = run_ids[index % len(run_ids)]
            paused = not commits.paused[run_id]

            def apply(run_id: str = run_id, paused: bool = paused) -> None:
                _, version = runs.load_run_state(run_id, workspace_id=WORKSPACE)
                runs.apply_transition(
                    run_id,
                    version,
                    _transition(
                        RunStatus.PAUSED if paused else RunStatus.RUNNING,
                        RunPauseReason.USER if paused else None,
                    ),
                    workspace_id=WORKSPACE,
                )

            commits.commit(run_id, paused, apply, readers=8)

    try:
        _run_threads(commits, [reader] * 8, write)
    finally:
        unhook()
    assert commits.clean_reads >= 300 * 8
    assert statuses._reads == {}


@pytest.mark.usefixtures("fast_thread_switches")
def test_the_binding_cache_answers_every_thread_correctly_while_evicting() -> None:
    lookup = FakeBindingLookup()
    bound = [f"bound-{index}" for index in range(12)]
    for session_id in bound:
        lookup.add(step_binding("work||:0", session_id=session_id, run_id=f"run-{session_id}"))
    cache = CachedBindingLookup(lookup, max_entries=4)
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            for _ in range(200):
                for session_id in (*bound, "unbound"):
                    found = cache.find_by_session(WORKSPACE, session_id)
                    expected = None if session_id == "unbound" else f"run-{session_id}"
                    assert (found.run_id if found else None) == expected, session_id
        except BaseException as exc:  # reported by the test
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT_S)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(cache._found) <= 4
