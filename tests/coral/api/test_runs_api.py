"""The runs API on a bare app: owner-only reads and writes, one 404, paging, fairness.

Runs are made by the bridge over the in-memory stores (``World.fake``); requests go
through the router with header authentication, or none. Starts reach a scripted host
repository (:class:`FakeHost`). The lifespan test at the end mounts the routes through
the real server plugin.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import shutil
import subprocess
import threading
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn, cast, get_args

import httpx
import pytest
import zstandard
from fastapi import FastAPI
from sqlalchemy import Engine, create_engine, delete
from sqlalchemy.exc import StatementError

import coral.api.run_service as run_service
from coral.api.errors import CoralApiError
from coral.api.outcome import OutcomeDiffs
from coral.api.run_models import (
    MAX_LOG_BODY_BYTES,
    MAX_LOG_PAGE_BYTES,
    SlotRoleName,
    SlotStatusName,
    StartRunRequest,
)
from coral.api.run_service import (
    API_CALL_TIMEOUT_S,
    API_THREADS,
    MAX_API_CALLS,
    MAX_API_CALLS_PER_USER,
    MAX_STARTS,
    MAX_STARTS_PER_USER,
    START_HEAD_DEADLINE_S,
    START_HEAD_TIMEOUT_S,
    InFlight,
    RunsApi,
    StartSlots,
)
from coral.api.runs import create_runs_router
from coral.api.spend import SPEND_THREADS, SpendCache
from coral.bridge.executors import BoundedThreads, BridgeThreads
from coral.bridge.keys import store_activation_id
from coral.bridge.mapping import RECOVERY_RESTART, RECOVERY_WAKE
from coral.bridge.service import USER_PAUSE_DETAIL, GateAnswerResult
from coral.db.enum_codecs import (
    SLOT_ROLE,
    SLOT_STATUS,
    LogKind,
    RunPauseReason,
    RunStatus,
    WorkStatus,
)
from coral.db.models_workflows import CoralBase, WorkflowRow
from coral.engine.lifecycle import retryable_activations
from coral.engine.types import (
    HandoffEvaluated,
    Input,
    PauseRun,
    RunnerHeld,
    RunnerHoldEnded,
    RunnerLost,
)
from coral.gates.prompt import gate_params
from coral.gates.verdict import GateAnswers
from coral.model.ids import anchor_session_id, derived_id
from coral.model.ir import CompiledGraph
from coral.omni._upstream import canonical_host_id
from coral.omni.host.ops import workspace_op_handlers
from coral.omni.protocols import (
    HostAccessRefused,
    HostWorkspaceChannels,
    RunSpendTotals,
    Viewer,
)
from coral.omni.server import coral_lifespan
from coral.omni.server.access import request_viewer
from coral.omni.server.workspace_ops import OmnigentHostWorkspaceChannels
from coral.profiles.spec import ProfileSpec
from coral.recovery.cancel import cancel_run_row
from coral.recovery.pause import pause_run_once
from coral.stores.fakes import FakeRunStore
from coral.stores.profiles import revision_id
from coral.stores.protocols import CoralRun, RunLogEntry, RunNotFound, WorkItem
from coral.stores.workflows import SqlWorkflowDefinitionStore, WorkflowDefinition
from coral.validate.pipeline import check_text
from coral.workspace.host_backend import host_capability_unavailable
from coral.workspace.ops import HostChannelBackend, WorkspaceOpError
from coral.workspace.run_worktree import (
    CreatedRunWorktree,
    HostPathStat,
    HostWorktreeEntry,
    RunWorktreeError,
    RunWorktreeHost,
    WorktreeCreateFailed,
    run_branch_name,
)
from omnigent.runtime import pending_elicitations
from omnigent.server import elicitation_hooks
from omnigent.server.auth import AuthProvider, UnifiedAuthProvider
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
    CHANGE_TOKEN,
    GATE_ONLY,
    GATED,
    IMPLEMENT_AGAIN,
    IMPLEMENT_FIRST,
    answer,
    before_next_commit,
    brief,
    complete,
    effects,
    hand_off,
    payload,
    work_for,
)
from tests.coral.bridge._scripted_runs import accept
from tests.coral.bridge._world import (
    DEFINITION,
    IMPLEMENT,
    REVIEW,
    WORKSPACE,
    RecordingGatePublisher,
    World,
    blocked,
    finished,
    run_id_for,
    run_spec,
    settle,
    start,
    start_without_engine,
)
from tests.coral.omni._gate_server import (
    CORAL_SERVER_PLUGIN,
    coral_server,
    gate_run,
    run_status,
)
from tests.coral.omni.host.ops._worktrees import isolate_git_home, make_repository, run_git
from tests.coral.workflow_builders import arrow, fixture_text, step, workflow_text
from tests.coral.workflow_builders import end as end_node
from tests.coral.workflow_builders import gate as gate_node
from tests.coral.workflow_builders import start as start_node
from tests.coral.workspace._executor_fakes import (
    ChannelRequest,
    FakeBindings,
    FakeChannels,
    FakeHostChannel,
    HeldChannels,
    InProcessHostChannel,
    RecordingScopeRunner,
    StalledHost,
)

HEADER = "X-Forwarded-Email"
HEADER_AUTH = UnifiedAuthProvider(source="header", local_single_user=False, header_name=HEADER)
ALICE, BOB = "alice", "bob"
RUNS = "/v1/coral/runs"
UNKNOWN_RUN = "f" * 32
OTHER_WORKFLOW = "e" * 32
# Unknown, malformed and other users' runs all answer exactly these bytes.
NOT_FOUND = b'{"error":{"code":"not_found","message":"Run not found.","details":null}}'
TOTALS = RunSpendTotals(
    usd=1.25,
    live_usd=1.5,
    input_tokens=100,
    output_tokens=50,
    total_tokens=150,
    cache_read_tokens=10,
    cache_creation_tokens=5,
    unpriced_models=("unpriced-local",),
    sessions=3,
)
SPEND_JSON = {
    "estimate": True,
    "usd": 1.25,
    "live_usd": 1.5,
    "tokens": {"input": 100, "output": 50, "total": 150, "cache_read": 10, "cache_creation": 5},
    "unpriced_models": ["unpriced-local"],
    "sessions": 3,
}


@dataclass
class SpendReader:
    """Answers every run's spend with ``totals``, recording each read; a read of a run in
    ``held`` waits until ``release`` is set."""

    totals: RunSpendTotals | None = TOTALS
    reads: list[tuple[int, str]] = field(default_factory=list)
    held: set[str] = field(default_factory=set)
    release: threading.Event = field(default_factory=threading.Event)

    def run_spend(self, *, workspace_id: int, run_id: str) -> RunSpendTotals | None:
        self.reads.append((workspace_id, run_id))
        if run_id in self.held:
            self.release.wait(timeout=budget(30))
        return self.totals


class Recorder:
    """``target`` with every method call recorded in ``calls`` as ``<name>.<method>``."""

    def __init__(self, target: object, name: str, calls: list[str]) -> None:
        self._target, self._name, self._calls = target, name, calls

    def __getattr__(self, attribute: str) -> Any:
        value = getattr(self._target, attribute)
        if not callable(value):
            return value

        def call(*args: Any, **kwargs: Any) -> Any:
            self._calls.append(f"{self._name}.{attribute}")
            return value(*args, **kwargs)

        return call


class HeldRuns:
    """The run store, whose ``get_run`` of a run in ``held`` waits until ``release`` is set."""

    def __init__(self, runs: object) -> None:
        self._runs = runs
        self.held: set[str] = set()
        self.release = threading.Event()
        self._lock = threading.Lock()
        self.waiting = 0

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self._runs, attribute)

    def get_run(self, run_id: str, **kwargs: Any) -> CoralRun | None:
        if run_id in self.held:
            with self._lock:
                self.waiting += 1
            self.release.wait(timeout=budget(30))
        return cast(Any, self._runs).get_run(run_id, **kwargs)


REPO = "/repo/coral"
TWO_STEPS = fixture_text("two_steps")
# Created by the scripted host; a 40-hex commit id.
HEAD = "1" * 40


@dataclass
class FakeHost(RunWorktreeHost):
    """
    A repository on a connected host, answered as git would: its main worktree and the
    run worktrees made in it.

    A create of a branch in ``held`` waits for ``release``; meanwhile git lists that
    worktree as locked, as ``git worktree add`` holds it while it checks the tree out.

    :ivar refuse: Raised when the host is connected, as a refused or offline host is.
    :ivar failing: Every create fails as git would.
    :ivar before_list: Runs before each listing, as another replica's work would.
    :ivar head_commit: What a create reports as the new worktree's HEAD; an older host
        reports none.
    """

    root: str = REPO
    worktrees: dict[str, str] = field(default_factory=dict)
    held: set[str] = field(default_factory=set)
    creating: set[str] = field(default_factory=set)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    calls: list[tuple[str, ...]] = field(default_factory=list)
    connected: list[dict[str, object]] = field(default_factory=list)
    refuse: RunWorktreeError | None = None
    failing: bool = False
    before_list: Callable[[], object] | None = None
    head_commit: str | None = HEAD

    async def connect(
        self,
        *,
        user_id: str | None,
        account_generation: str | None,
        host_id: str,
        workspace_id: int,
    ) -> RunWorktreeHost:
        self.connected.append(
            {
                "user_id": user_id,
                "account_generation": account_generation,
                "host_id": host_id,
                "workspace_id": workspace_id,
            }
        )
        if self.refuse is not None:
            raise self.refuse
        return self

    def path_of(self, branch: str) -> str:
        return f"{self.root}-worktrees/{branch.replace('/', '-')}"

    async def stat(self, path: str) -> HostPathStat:
        if path in (self.root, f"{self.root}/.git"):
            return HostPathStat(exists=True, is_directory=True, canonical_path=path)
        for worktree in self.worktrees.values():
            if path == worktree:
                return HostPathStat(exists=True, is_directory=True, canonical_path=path)
            if path == f"{worktree}/.git":
                return HostPathStat(exists=True, is_directory=False, canonical_path=None)
        return HostPathStat(exists=False, is_directory=False, canonical_path=None)

    async def list_worktrees(self, repo_root: str) -> Sequence[HostWorktreeEntry]:
        self.calls.append(("list", repo_root))
        if self.before_list is not None:
            self.before_list()
        return [
            HostWorktreeEntry(path=self.root, branch="main", is_main=True),
            *(
                HostWorktreeEntry(
                    path=path, branch=branch, is_main=False, locked=branch in self.creating
                )
                for branch, path in self.worktrees.items()
            ),
        ]

    async def create_worktree(
        self, repo_root: str, branch: str, base_ref: str | None, *, existing_branch: bool
    ) -> CreatedRunWorktree:
        self.calls.append(("create", branch, base_ref or ""))
        if self.failing:
            raise WorktreeCreateFailed("fatal: could not create the worktree")
        path = self.path_of(branch)
        self.worktrees[branch] = path
        if branch in self.held:
            self.creating.add(branch)
            await self.release.wait()
            self.creating.discard(branch)
        return CreatedRunWorktree(path=path, branch=branch, head_commit=self.head_commit)

    def creates(self) -> int:
        return sum(1 for call in self.calls if call[0] == "create")


@dataclass
class Definitions:
    """Workflow definitions in a SQLite file, which the API's threads share."""

    store: SqlWorkflowDefinitionStore
    engine: Engine

    def save(self, owner: str | None = ALICE, yaml_text: str = TWO_STEPS) -> WorkflowDefinition:
        checked = check_text(yaml_text, None)
        assert checked.graph is not None and checked.report is not None
        return self.store.save(
            workspace_id=WORKSPACE,
            workflow_key=checked.graph.workflow_id,
            name=checked.graph.name,
            yaml_text=yaml_text,
            compiled=checked.graph,
            runnable=checked.report.runnable,
            owner=owner,
        )

    def delete_all(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(WorkflowRow))


@dataclass
class Writes:
    """What the write routes reach: definitions, the host, gate answers and prompts."""

    definitions: Definitions
    host: FakeHost
    publisher: RecordingGatePublisher
    answers: GateAnswers
    threads: BridgeThreads
    bindings: FakeBindings = field(default_factory=FakeBindings)


@dataclass
class Api:
    """The runs API over a world, with its pools and what it called."""

    world: World
    api: RunsApi
    spend: SpendCache
    reader: SpendReader
    calls: list[str]
    in_flight: InFlight
    writes: Writes | None = None

    @property
    def services(self) -> Writes:
        assert self.writes is not None
        return self.writes

    def app(self, auth_provider: AuthProvider | None = HEADER_AUTH) -> FastAPI:
        """The routes over this API and its definitions; ``None`` turns authentication off."""
        assert self.writes is not None
        return _app(self.api, auth_provider, definitions=self.writes.definitions.store)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


@pytest.fixture
def held(world: World) -> Iterator[HeldRuns]:
    runs = HeldRuns(world.runs)
    yield runs
    # Never leave a pool thread waiting past the test.
    runs.release.set()


def _build(
    world: World,
    *,
    run_store: object | None = None,
    writes: Writes | None = None,
    requires_generation: bool = False,
    starts: StartSlots | None = None,
    with_host: bool = True,
    channels: HostWorkspaceChannels | None = None,
    outcome_diffs: OutcomeDiffs | None = None,
    canonical_host_id: Callable[[str], str] | None = None,
    **in_flight_options: Any,
) -> tuple[Api, list[BoundedThreads]]:
    api_threads = BoundedThreads(max_workers=API_THREADS, thread_name_prefix="test-coral-api")
    spend_threads = BoundedThreads(max_workers=SPEND_THREADS, thread_name_prefix="test-spend")
    reader = SpendReader()
    spend = SpendCache(reader, spend_threads)
    calls: list[str] = []
    in_flight = InFlight(api_threads, **in_flight_options)
    api = RunsApi(
        bridge=cast(Any, Recorder(world.bridge, "bridge", calls)),
        run_store=cast(Any, Recorder(run_store or world.runs, "runs", calls)),
        spend=cast(Any, Recorder(spend, "spend", calls)),
        in_flight=in_flight,
        gate_answers=None if writes is None else writes.answers,
        gate_publisher=None if writes is None else writes.publisher,
        connect_host=None if writes is None or not with_host else writes.host.connect,
        requires_generation=requires_generation,
        starts=starts,
        workspace_channels=channels,
        outcome_diffs=outcome_diffs,
        canonical_host_id=canonical_host_id,
    )
    built = Api(world, api, spend, reader, calls, in_flight, writes)
    return built, [api_threads, spend_threads]


def _writes(world: World, tmp_path: Path, **answer_options: Any) -> Writes:
    engine = create_engine(f"sqlite:///{tmp_path / 'definitions.db'}")
    CoralBase.metadata.create_all(engine)
    threads = BridgeThreads(world.bridge)
    bindings = FakeBindings()
    return Writes(
        definitions=Definitions(SqlWorkflowDefinitionStore(engine), engine),
        host=FakeHost(),
        publisher=RecordingGatePublisher(),
        answers=GateAnswers(
            threads=threads, bindings=bindings, run_store=world.runs, **answer_options
        ),
        threads=threads,
        bindings=bindings,
    )


def _close(built: Api, pools: Sequence[BoundedThreads]) -> None:
    built.reader.release.set()
    built.spend.close()
    for pool in pools:
        pool.close()
    if built.writes is not None:
        built.writes.host.release.set()
        built.writes.threads.close()
        built.writes.definitions.engine.dispose()


@pytest.fixture
async def runs_api(world: World) -> AsyncIterator[Api]:
    built, pools = _build(world)
    yield built
    _close(built, pools)


@pytest.fixture
async def writes(world: World, tmp_path: Path) -> AsyncIterator[Api]:
    built, pools = _build(world, writes=_writes(world, tmp_path))
    yield built
    _close(built, pools)


# Read routes never touch definitions; an in-memory store is enough for them.
_NO_DEFINITIONS = SqlWorkflowDefinitionStore(create_engine("sqlite://"))


def _app(
    api: RunsApi | None,
    auth_provider: AuthProvider | None = HEADER_AUTH,
    *,
    definitions: SqlWorkflowDefinitionStore = _NO_DEFINITIONS,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_runs_router(
            definitions=definitions,
            viewer_dependency=request_viewer(auth_provider),
            workspace_id_dependency=lambda: WORKSPACE,
        ),
        prefix="/v1/coral",
    )
    if api is not None:
        app.state.coral_runs_api = api
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _as(user: str) -> dict[str, str]:
    return {HEADER: user}


def _start(world: World, key: str, user: str | None = ALICE, **spec: Any) -> CoralRun:
    """A started two-step run of ``user``, one second after the previous one."""
    world.clock.advance(1)
    return start(
        world,
        spec=run_spec(user=user, start_key=key, **spec),
        start_key=key,
        actor=None if user is None else f"user:{user}",
        allow_ownerless=user is None,
    )


def _fake_runs(world: World) -> FakeRunStore:
    assert isinstance(world.runs, FakeRunStore)
    return world.runs


def _pause_on_row(world: World, run: CoralRun, reason: RunPauseReason) -> None:
    """A pause written on the run row alone, as drift and failed loads write one."""
    pause_run_once(
        world.runs,
        workspace_id=WORKSPACE,
        run_id=run.id,
        reason=reason,
        body={"kind": "pause_run", "reason": reason.name.lower()},
        checksum_parts=("runs-api-test", run.id),
        now_us=world.clock.epoch * 1_000_000,
    )


def _config_missing(world: World, run: CoralRun) -> None:
    """The run's frozen engine config is gone, so its engine cannot be loaded."""
    specs = _fake_runs(world).specs
    specs[(WORKSPACE, run.id)] = dataclasses.replace(
        specs[(WORKSPACE, run.id)], engine_config=None
    )


def _rows_undecodable(world: World, run: CoralRun, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _fake_runs(world)
    load = runs.load_run_state

    def failing(run_id: str, **kwargs: Any) -> Any:
        if run_id == run.id:
            raise zstandard.ZstdError("not a zstd frame")
        return load(run_id, **kwargs)

    monkeypatch.setattr(runs, "load_run_state", failing)


async def _ids(client: httpx.AsyncClient, user: str = ALICE, **params: Any) -> list[str]:
    response = await client.get(RUNS, headers=_as(user), params=params)
    assert response.status_code == 200, response.text
    return [item["run_id"] for item in response.json()["data"]]


def _refusal(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


# ── The list ────────────────────────────────────────────────────────────────


async def test_the_owner_lists_only_their_runs_newest_first_with_the_row_s_actions(
    runs_api: Api,
) -> None:
    world = runs_api.world
    running = _start(world, "running")
    user_paused = _start(world, "user-paused")
    world.bridge.pause_run(workspace_id=WORKSPACE, run_id=user_paused.id, actor="user:alice")
    drift = _start(world, "drift")
    _pause_on_row(world, drift, RunPauseReason.DRIFT)
    cancelled = _start(world, "cancelled")
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=cancelled.id, actor="user:alice")
    bobs = _start(world, "bobs", user=BOB)

    async with _client(_app(runs_api.api)) as client:
        response = await client.get(RUNS, headers=_as(ALICE))
        bob_ids = await _ids(client, BOB)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    page = response.json()
    assert page["next_cursor"] is None
    listed = {item["run_id"]: item for item in page["data"]}
    assert list(listed) == [cancelled.id, drift.id, user_paused.id, running.id]
    assert {run_id: item["allowed_actions"] for run_id, item in listed.items()} == {
        running.id: ["pause", "cancel"],
        user_paused.id: ["resume", "cancel"],
        # A pause on the row alone may sit on an engine paused for budget: Cancel only.
        drift.id: ["cancel"],
        cancelled.id: [],
    }
    stored = world.run(cancelled.id)
    assert listed[cancelled.id] == {
        "run_id": cancelled.id,
        "workflow_id": stored.workflow_id,
        "version_id": stored.version_id,
        "title": "Ship the bridge",
        "status": "cancelled",
        "pause_reason": None,
        "created_at": stored.created_at,
        "updated_at": stored.updated_at,
        "finished_at": stored.finished_at,
        "activation_count": stored.activation_count,
        "allowed_actions": [],
        "spend": None,
        "run_branch": run_branch_name(cancelled.id),
    }
    assert listed[drift.id]["pause_reason"] == "drift"
    assert bob_ids == [bobs.id]


async def test_the_list_filters_by_status_and_workflow(runs_api: Api) -> None:
    world = runs_api.world
    running = _start(world, "running")
    paused = _start(world, "paused")
    world.bridge.pause_run(workspace_id=WORKSPACE, run_id=paused.id, actor="user:alice")
    other = _start(world, "other", workflow_id=OTHER_WORKFLOW)
    cancelled = _start(world, "cancelled")
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=cancelled.id, actor="user:alice")

    async with _client(_app(runs_api.api)) as client:
        by_status = await _ids(client, status="paused")
        by_statuses = await _ids(client, status=["running", "cancelled", "running"])
        # The cap counts distinct values, so repeats are taken.
        repeated = await _ids(client, status=["paused"] * 7)
        by_workflow = await _ids(client, workflow_id=OTHER_WORKFLOW)
        both = await _ids(client, workflow_id=OTHER_WORKFLOW, status="paused")

    assert by_status == repeated == [paused.id]
    assert by_statuses == [cancelled.id, other.id, running.id]
    assert (by_workflow, both) == ([other.id], [])


async def test_pages_round_trip_through_the_cursor_with_no_gap_or_repeat(runs_api: Api) -> None:
    world = runs_api.world
    started = [_start(world, f"run-{index}") for index in range(5)]
    _start(world, "bobs", user=BOB)

    pages: list[list[str]] = []
    cursors: list[str | None] = []
    async with _client(_app(runs_api.api)) as client:
        params: dict[str, Any] = {"limit": 2}
        while True:
            response = await client.get(RUNS, headers=_as(ALICE), params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            pages.append([item["run_id"] for item in page["data"]])
            cursors.append(page["next_cursor"])
            if page["next_cursor"] is None:
                break
            params["after"] = page["next_cursor"]

    newest_first = [run.id for run in reversed(started)]
    assert pages == [newest_first[0:2], newest_first[2:4], newest_first[4:]]
    last_of_first = world.run(newest_first[1])
    assert (cursors[0], cursors[-1]) == (f"{last_of_first.created_at}:{last_of_first.id}", None)


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"after": "not-a-cursor"}, id="malformed-cursor"),
        pytest.param({"after": f"1:{'A' * 32}"}, id="upper-case-cursor-id"),
        pytest.param({"after": f"1:{'a' * 31}"}, id="short-cursor-id"),
        pytest.param({"after": f"{2**63}:{'a' * 32}"}, id="cursor-time-past-the-column"),
        pytest.param({"after": f"{'0' * 32}:{'a' * 32}"}, id="cursor-over-64-characters"),
        pytest.param({"limit": 0}, id="limit-0"),
        pytest.param({"limit": 51}, id="limit-51"),
        pytest.param({"status": "asleep"}, id="unknown-status"),
        pytest.param({"workflow_id": "not-a-workflow"}, id="malformed-workflow"),
    ],
)
async def test_the_list_refuses_bad_cursors_limits_and_filters(
    runs_api: Api, params: dict[str, Any]
) -> None:
    async with _client(_app(runs_api.api)) as client:
        response = await client.get(RUNS, headers=_as(ALICE), params=params)

    assert _refusal(response) == (422, "validation_failed")
    # Refusals never echo what was sent, and nothing is read before them.
    assert "not-a-" not in response.text
    assert runs_api.calls == []


async def test_a_cold_cache_lists_spend_as_null_at_once_and_a_later_list_shows_it(
    runs_api: Api,
) -> None:
    run = _start(runs_api.world, "spend")

    async with _client(_app(runs_api.api)) as client:
        first = (await client.get(RUNS, headers=_as(ALICE))).json()["data"]
        await poll_until_async(
            lambda: runs_api.reader.reads and runs_api.spend.pending == 0, timeout_s=budget(10)
        )
        later = (await client.get(RUNS, headers=_as(ALICE))).json()["data"]

    assert [item["spend"] for item in first] == [None]
    [item] = later
    assert {key: value for key, value in item["spend"].items() if key != "as_of"} == SPEND_JSON
    assert runs_api.reader.reads == [(WORKSPACE, run.id)]


# ── The detail ──────────────────────────────────────────────────────────────


async def test_a_running_run_s_detail_holds_its_view_target_slots_and_spend(
    runs_api: Api,
) -> None:
    world = runs_api.world
    run = _start(world, "running")
    stored = world.run(run.id)
    state, _version = world.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    [slot] = state.agent_slots

    async with _client(_app(runs_api.api)) as client:
        response = await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    detail = response.json()
    assert {key: detail[key] for key in ("status", "pause_reason", "allowed_actions")} == {
        "status": "running",
        "pause_reason": None,
        "allowed_actions": ["pause", "cancel"],
    }
    assert detail["version"] == stored.version
    assert detail["head_seq"] == stored.next_log_seq - 1
    assert (detail["max_activations"], detail["request_preview"]) == (100, "Make runs advance")
    assert detail["target"] == {
        "host_id": "host-1",
        "repo_path": "/repo/coral",
        "worktree_path": "/repo/coral-worktrees/r1",
        "run_branch": state.spec.run_branch,
        "base_ref": None,
        "base_commit": None,
    }
    assert detail["anchor_session_id"] == anchor_session_id(WORKSPACE, run.id)
    assert detail["orchestrator_session_id"] is None
    assert detail["run_branch"] == run_branch_name(run.id)
    assert (detail["causes"], detail["load_error"], detail["gates"]) == ([], None, [])
    assert detail["retry_activation_ids"] == []
    assert detail["view"]["status"] == "running"
    assert detail["slots"] == [
        {
            "slot_id": slot.id,
            "node_id": "implement",
            "activation_id": slot.activation_id,
            "role": "step_agent",
            "status": "pending",
            "session_id": None,
            "session_generation": 1,
            "engine_slot_id": slot.scope_key,
        }
    ]
    # The view names a slot by its engine id, as the detail's slot does.
    assert [view_slot["id"] for view_slot in detail["view"]["slots"]] == [slot.scope_key]
    # The detail waits for the spend read a cold cache starts.
    assert {key: value for key, value in detail["spend"].items() if key != "as_of"} == SPEND_JSON


async def test_a_run_paused_for_its_user_offers_resume_and_shows_the_cause(
    runs_api: Api,
) -> None:
    world = runs_api.world
    run = _start(world, "paused")
    world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")

    async with _client(_app(runs_api.api)) as client:
        detail = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()

    assert (detail["status"], detail["pause_reason"]) == ("paused", "user")
    assert detail["allowed_actions"] == ["resume", "cancel"]
    assert [cause["reason"] for cause in detail["causes"]] == ["user"]
    assert detail["view"]["status"] == "paused"


async def test_a_pause_on_the_row_alone_offers_resume_in_the_detail_and_cancel_in_the_list(
    runs_api: Api,
) -> None:
    world = runs_api.world
    run = _start(world, "drift")
    _pause_on_row(world, run, RunPauseReason.DRIFT)

    async with _client(_app(runs_api.api)) as client:
        detail = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        [item] = (await client.get(RUNS, headers=_as(ALICE))).json()["data"]

    assert (detail["status"], detail["pause_reason"], detail["causes"]) == ("paused", "drift", [])
    assert detail["view"]["status"] == "running"
    assert detail["allowed_actions"] == ["resume", "cancel"]
    assert set(item["allowed_actions"]) <= set(detail["allowed_actions"])


async def test_a_run_at_its_gate_lists_the_open_visit_with_its_outcomes_and_prompt(
    runs_api: Api,
) -> None:
    world = runs_api.world
    world.clock.advance(1)
    run = start(world, GATE_ONLY, start_key="gate")
    state, _version = world.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    [row] = state.gate_visits
    snapshot = world.bridge.read(workspace_id=WORKSPACE, run_id=run.id).snapshot
    assert snapshot is not None
    [visit] = snapshot.state.gates
    anchor_prompt = gate_params(snapshot.graph, snapshot.state, world.run(run.id), visit, row)

    async with _client(_app(runs_api.api)) as client:
        detail = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        # A stored visit the engine state does not hold, as when rows and log disagree.
        visits = _fake_runs(world).gate_visits
        visits[(WORKSPACE, run.id, row.id)] = dataclasses.replace(row, token="unmatched")
        unmatched = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        visits[(WORKSPACE, run.id, row.id)] = row
        _config_missing(world, run)
        unloadable = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()

    assert detail["gates"] == [
        {
            "visit_id": row.id,
            "node_id": "approve",
            "token": row.token,
            "visit_no": 1,
            "elicitation_id": row.elicitation_id,
            "opened_at": row.opened_at,
            "outcomes": ["approve", "reject"],
            # What the anchor's approval prompt asks, so the run view shows the same text.
            "context": anchor_prompt["message"],
        }
    ]
    assert "Ship it?" in detail["gates"][0]["context"]
    # The graph loaded, so the outcomes show; the state has no such visit, so no prompt.
    [gate] = unmatched["gates"]
    assert (gate["token"], gate["context"], gate["outcomes"]) == (
        "unmatched",
        None,
        ["approve", "reject"],
    )
    # Without the engine state there is no prompt to show, but the visit is still listed.
    [gate] = unloadable["gates"]
    assert (gate["token"], gate["context"], gate["outcomes"]) == (row.token, None, [])


async def test_a_finished_run_offers_nothing(runs_api: Api) -> None:
    world = runs_api.world
    run = _start(world, "cancelled")
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")

    async with _client(_app(runs_api.api)) as client:
        detail = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()

    finished_at = world.run(run.id).finished_at
    assert (detail["status"], detail["allowed_actions"]) == ("cancelled", [])
    assert finished_at is not None
    assert detail["finished_at"] == finished_at


async def test_a_run_that_cannot_load_shows_the_load_failure_offers_cancel_and_stays_unchanged(
    runs_api: Api,
) -> None:
    world = runs_api.world
    run = _start(world, "broken")
    _config_missing(world, run)
    before = (world.run(run.id), tuple(_fake_runs(world).logs[(WORKSPACE, run.id)]))

    async with _client(_app(runs_api.api)) as client:
        detail = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        [item] = (await client.get(RUNS, headers=_as(ALICE))).json()["data"]

    assert (detail["status"], detail["load_error"], detail["view"]) == (
        "running",
        "engine.load_failed",
        None,
    )
    assert detail["causes"] == [
        {"reason": "failure_path", "detail": "engine.load_failed", "subject": ""}
    ]
    assert detail["allowed_actions"] == ["cancel"]
    # Its rows still read, so its target and slots are shown.
    assert detail["target"]["host_id"] == "host-1"
    assert len(detail["slots"]) == 1
    # A read never pauses the run it could not load.
    assert (world.run(run.id), tuple(_fake_runs(world).logs[(WORKSPACE, run.id)])) == before
    # The list reads the row alone, which shows no failure until a write pauses the run.
    assert item["allowed_actions"] == ["pause", "cancel"]


async def test_a_run_whose_rows_do_not_decode_shows_its_row_alone(
    runs_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = runs_api.world
    run = _start(world, "undecodable")
    _rows_undecodable(world, run, monkeypatch)

    async with _client(_app(runs_api.api)) as client:
        detail = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()

    assert (detail["load_error"], detail["allowed_actions"]) == ("engine.load_failed", ["cancel"])
    assert (detail["target"], detail["max_activations"], detail["request_preview"]) == (
        None,
        None,
        None,
    )
    assert (detail["slots"], detail["gates"]) == ([], [])


# ── The pinned graph ────────────────────────────────────────────────────────


async def test_the_graph_is_the_pinned_version_with_its_etag_and_revalidates_to_304(
    runs_api: Api,
) -> None:
    world = runs_api.world
    run = _start(world, "graph")
    pinned = world.versions.load(workspace_id=WORKSPACE, version_id=run.version_id)
    assert pinned is not None
    etag = f'"{run.version_id}"'
    url = f"{RUNS}/{run.id}/graph"

    async with _client(_app(runs_api.api)) as client:
        fetched = await client.get(url, headers=_as(ALICE))
        revalidated = [
            await client.get(url, headers={**_as(ALICE), "If-None-Match": value})
            for value in (etag, f"W/{etag}", f'"other", {etag}', "*")
        ]
        changed = await client.get(url, headers={**_as(ALICE), "If-None-Match": '"other"'})

    assert fetched.status_code == 200, fetched.text
    assert CompiledGraph.model_validate(fetched.json()) == pinned.graph
    assert (fetched.headers["etag"], fetched.headers["cache-control"]) == (
        etag,
        "private, no-cache",
    )
    for response in revalidated:
        assert (response.status_code, response.content) == (304, b"")
        assert (response.headers["etag"], response.headers["cache-control"]) == (
            etag,
            "private, no-cache",
        )
    assert changed.status_code == 200
    assert runs_api.calls.count("bridge.pinned_graph") == 2


async def test_the_graph_of_a_run_whose_pinned_version_is_gone_is_a_declared_404(
    runs_api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    world = runs_api.world
    run = _start(world, "no-version")
    runs = _fake_runs(world)
    runs.runs[(WORKSPACE, run.id)] = dataclasses.replace(run, version_id="0" * 32)

    with caplog.at_level(logging.DEBUG, logger="coral.api.run_service"):
        async with _client(_app(runs_api.api)) as client:
            responses = [
                await client.get(f"{RUNS}/{run.id}/graph", headers=_as(ALICE)) for _ in range(2)
            ]
            detail = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {
            "error": {
                "code": "not_found",
                "message": "The run's workflow graph cannot be read.",
                "details": {"load_error": "engine.load_failed"},
            }
        }
    assert detail["load_error"] == "engine.load_failed"
    # Warned once, then debug: the owner cannot fill the log with it.
    levels = [record.levelno for record in caplog.records if "pinned graph" in record.message]
    assert levels == [logging.WARNING, logging.DEBUG]


# ── The log ─────────────────────────────────────────────────────────────────


def _log_rows(world: World, run: CoralRun) -> list[RunLogEntry]:
    return _fake_runs(world).logs[(WORKSPACE, run.id)]


def _add_rows(world: World, run: CoralRun, bodies: list[str]) -> None:
    """Append ``ALERT`` rows holding ``bodies`` after the run's last row."""
    rows = _log_rows(world, run)
    template = rows[-1]
    for body in bodies:
        rows.append(
            dataclasses.replace(
                template,
                seq=rows[-1].seq + 1,
                kind=int(LogKind.ALERT),
                body=body,
                view_patch=None,
                audit_only=False,
            )
        )


async def test_the_log_sends_every_row_with_its_kind_patch_and_body(runs_api: Api) -> None:
    world = runs_api.world
    run = _start(world, "log")
    # An input about no slot is refused, an audit-only row with no patch; the pause is not.
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (
            HandoffEvaluated(slot_id="no-such-slot", outcome="accepted"),
            PauseRun(reason="user", detail="user"),
        ),
        actor="user:alice",
    )
    rows = _log_rows(world, run)

    async with _client(_app(runs_api.api)) as client:
        response = await client.get(f"{RUNS}/{run.id}/log", headers=_as(ALICE))

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    page = response.json()
    assert page["next_after_seq"] is None
    started, refused, paused = page["data"]
    assert {key: started[key] for key in ("seq", "kind", "actor_kind", "actor", "rejected")} == {
        "seq": 1,
        "kind": "engine.start_run",
        "actor_kind": "user",
        "actor": "user:alice",
        "rejected": None,
    }
    assert started["patch"] == json.loads(rows[0].view_patch or "[]")
    assert started["body"] == json.loads(rows[0].body)
    assert started["body_truncated"] is False
    assert started["at_us"] == rows[0].created_at_us
    assert (refused["seq"], refused["kind"], refused["patch"]) == (
        2,
        "engine.handoff_evaluated",
        [],
    )
    assert refused["rejected"] == json.loads(rows[1].body)["rejection"]["code"]
    assert (paused["seq"], paused["kind"], paused["rejected"]) == (3, "engine.pause_run", None)
    assert paused["patch"] == json.loads(rows[2].view_patch or "[]") != []


async def test_the_log_pages_after_a_seq(runs_api: Api) -> None:
    world = runs_api.world
    run = _start(world, "log")
    _add_rows(world, run, [json.dumps({"n": index}) for index in range(3)])
    url = f"{RUNS}/{run.id}/log"

    async with _client(_app(runs_api.api)) as client:
        first = (await client.get(url, headers=_as(ALICE), params={"limit": 2})).json()
        rest = (
            await client.get(url, headers=_as(ALICE), params={"after_seq": 2, "limit": 2})
        ).json()

    assert ([row["seq"] for row in first["data"]], first["next_after_seq"]) == ([1, 2], 2)
    assert ([row["seq"] for row in rest["data"]], rest["next_after_seq"]) == ([3, 4], None)
    assert [row["kind"] for row in rest["data"]] == ["log.alert", "log.alert"]
    assert [row["body"] for row in rest["data"]] == [{"n": 1}, {"n": 2}]


@pytest.mark.parametrize("fault", ["undecodable", "not_a_patch"])
async def test_an_unreadable_log_row_is_a_placeholder_between_readable_ones(
    runs_api: Api, fault: str
) -> None:
    world = runs_api.world
    run = _start(world, "log")
    _add_rows(world, run, ['{"n": 1}', '{"n": 2}'])
    if fault == "undecodable":
        _fake_runs(world).undecodable_logs.add((WORKSPACE, run.id, 2))
    else:
        # Stored patch text that is JSON but not a patch.
        rows = _log_rows(world, run)
        rows[1] = dataclasses.replace(rows[1], view_patch='{"op": "add"}')

    async with _client(_app(runs_api.api)) as client:
        page = (await client.get(f"{RUNS}/{run.id}/log", headers=_as(ALICE))).json()

    assert [(row["seq"], row["kind"]) for row in page["data"]] == [
        (1, "engine.start_run"),
        (2, "log.unreadable"),
        (3, "log.alert"),
    ]
    unreadable = page["data"][1]
    assert (unreadable["body"], unreadable["body_truncated"], unreadable["patch"]) == (
        None,
        False,
        [],
    )


@pytest.mark.parametrize("field", ["kind", "actor_kind"])
async def test_a_log_row_with_a_code_this_server_cannot_read_is_a_placeholder(
    runs_api: Api, field: str
) -> None:
    world = runs_api.world
    run = _start(world, "log")
    _add_rows(world, run, ['{"n": 1}', '{"n": 2}', '{"n": 3}'])
    rows = _log_rows(world, run)
    # A code a newer server wrote, which this one does not know.
    rows[2] = dataclasses.replace(rows[2], **{field: 250})
    url = f"{RUNS}/{run.id}/log"

    async with _client(_app(runs_api.api)) as client:
        page = (await client.get(url, headers=_as(ALICE))).json()
        after = (
            await client.get(url, headers=_as(ALICE), params={"after_seq": 2, "limit": 2})
        ).json()

    assert [(row["seq"], row["kind"]) for row in page["data"]] == [
        (1, "engine.start_run"),
        (2, "log.alert"),
        (3, "log.unreadable"),
        (4, "log.alert"),
    ]
    placeholder = page["data"][2]
    assert (placeholder["body"], placeholder["patch"], placeholder["rejected"]) == (None, [], None)
    readable_actor = page["data"][1]["actor_kind"]
    assert placeholder["actor_kind"] == (None if field == "actor_kind" else readable_actor)
    # Paging goes on past it.
    assert [row["seq"] for row in after["data"]] == [3, 4]


async def test_the_log_leaves_out_a_body_too_large_and_stops_at_its_byte_cap(
    runs_api: Api,
) -> None:
    world = runs_api.world
    run = _start(world, "log")
    big = json.dumps({"text": "x" * (MAX_LOG_BODY_BYTES - 64)})
    too_big = json.dumps({"text": "x" * MAX_LOG_BODY_BYTES})
    # The start row's body and patch count too; a left-out body does not.
    start_row = _log_rows(world, run)[0]
    room = MAX_LOG_PAGE_BYTES - len(start_row.body.encode())
    room -= len((start_row.view_patch or "").encode())
    fits = room // len(big)
    _add_rows(world, run, [too_big, *[big] * (fits + 1)])

    async with _client(_app(runs_api.api)) as client:
        page = (await client.get(f"{RUNS}/{run.id}/log", headers=_as(ALICE))).json()

    rows = page["data"]
    assert (rows[1]["seq"], rows[1]["body"], rows[1]["body_truncated"]) == (2, None, True)
    assert [row["body"] is not None for row in rows] == [True, False, *[True] * fits]
    assert page["next_after_seq"] == rows[-1]["seq"] == 2 + fits


async def test_the_log_s_byte_cap_counts_patches(runs_api: Api) -> None:
    world = runs_api.world
    run = _start(world, "log")
    patch = json.dumps([{"op": "add", "path": "/note", "value": "x" * (MAX_LOG_BODY_BYTES - 64)}])
    rows = _log_rows(world, run)
    for _ in range(MAX_LOG_PAGE_BYTES // len(patch) + 1):
        rows.append(
            dataclasses.replace(
                rows[-1],
                seq=rows[-1].seq + 1,
                kind=int(LogKind.ALERT),
                body="{}",
                view_patch=patch,
            )
        )

    async with _client(_app(runs_api.api)) as client:
        page = (await client.get(f"{RUNS}/{run.id}/log", headers=_as(ALICE))).json()

    sent = page["data"]
    assert len(sent) < len(rows)
    assert sum(len(json.dumps(row["patch"])) for row in sent[1:]) <= MAX_LOG_PAGE_BYTES
    assert page["next_after_seq"] == sent[-1]["seq"]


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"after_seq": -1}, id="negative-seq"),
        pytest.param({"after_seq": 2**63}, id="seq-past-the-column"),
        pytest.param({"limit": 0}, id="limit-0"),
        pytest.param({"limit": 101}, id="limit-101"),
    ],
)
async def test_the_log_refuses_bad_paging(runs_api: Api, params: dict[str, Any]) -> None:
    run = _start(runs_api.world, "log")

    async with _client(_app(runs_api.api)) as client:
        response = await client.get(f"{RUNS}/{run.id}/log", headers=_as(ALICE), params=params)

    assert _refusal(response) == (422, "validation_failed")


# ── Who may read ────────────────────────────────────────────────────────────

READ_ROUTES = ["", "/graph", "/log", "/outcome"]


@pytest.mark.parametrize("route", READ_ROUTES)
@pytest.mark.parametrize("case", ["unknown", "malformed", "upper-case", "other-user"])
async def test_every_read_route_answers_one_404_doing_no_work_for_a_run_it_may_not_show(
    runs_api: Api, route: str, case: str
) -> None:
    bobs = _start(runs_api.world, "bobs", user=BOB)
    run_id = {
        "unknown": UNKNOWN_RUN,
        "malformed": "not-a-run",
        "upper-case": bobs.id.upper(),
        "other-user": bobs.id,
    }[case]

    async with _client(_app(runs_api.api)) as client:
        response = await client.get(
            f"{RUNS}/{run_id}{route}",
            # A matching ETag must not turn into a 304 before the owner check.
            headers={**_as(ALICE), "If-None-Match": f'"{bobs.version_id}"'},
        )

    assert (response.status_code, response.content) == (404, NOT_FOUND)
    # A refusal of a run read is never cached either.
    assert response.headers["cache-control"] == "private, no-store"
    # Only the row lookup ran: no load, log, graph or spend read.
    assert runs_api.calls == ([] if case in ("malformed", "upper-case") else ["runs.get_run"])
    assert runs_api.reader.reads == []


# ── The outcome ─────────────────────────────────────────────────────────────

BASE = "2" * 40


def _outcome_host(
    head: str = HEAD,
) -> tuple[FakeHostChannel, FakeChannels]:
    """A host whose run worktrees are at ``head`` on their own branch, two files changed."""
    host = FakeHostChannel(
        [],
        {
            "head": lambda request: {
                "head": head,
                "branch": request.params["branch"],
                "merge_in_progress": False,
            },
            "diff_stat": {
                "files_changed": 2,
                "insertions": 5,
                "deletions": 1,
                "paths": ["src/app.py", "README.md"],
            },
        },
    )
    return host, FakeChannels(host, RecordingScopeRunner())


@pytest.fixture
async def outcomes(world: World) -> AsyncIterator[tuple[Api, FakeHostChannel, FakeChannels]]:
    host, channels = _outcome_host()
    built, pools = _build(world, channels=channels)
    yield built, host, channels
    _close(built, pools)


async def _outcome(api: RunsApi, run_id: str, user: str = ALICE) -> httpx.Response:
    async with _client(_app(api)) as client:
        return await client.get(f"{RUNS}/{run_id}/outcome", headers=_as(user))


async def test_a_finished_runs_outcome_is_its_branch_diff_and_checkout_command(
    outcomes: tuple[Api, FakeHostChannel, FakeChannels],
) -> None:
    runs_api, host, channels = outcomes
    run = _complete(runs_api.world, "finished", base_commit=BASE)
    branch = run_branch_name(run.id)

    response = await _outcome(runs_api.api, run.id)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "run_id": run.id,
        "status": "completed",
        "finished_at": run.finished_at,
        "branch": branch,
        "host_id": "host-1",
        "repo_path": REPO,
        "worktree_path": "/repo/coral-worktrees/r1",
        "base_commit": BASE,
        "head_commit": HEAD,
        "diff": {
            "from_commit": BASE,
            "to_commit": HEAD,
            "files_changed": 2,
            "insertions": 5,
            "deletions": 1,
            "paths": ["README.md", "src/app.py"],
            "paths_truncated": False,
        },
        "diff_unavailable": None,
        "checkout": {
            "command": f"git -C /repo/coral checkout --detach refs/heads/{branch}",
            "worktree_command": "cd /repo/coral-worktrees/r1",
            "unavailable": None,
        },
    }
    assert runs_api.calls == [
        "runs.get_run",
        "runs.load_run_state",
        "runs.unfinished_run_hosts",
    ]
    assert [call["user_id"] for call in channels.calls] == [ALICE]
    assert host.ops() == ["head", "diff_stat"]


def _outcome_case(world: World, case: str, monkeypatch: pytest.MonkeyPatch) -> CoralRun:
    """A run whose outcome needs no host: each reason the diff is not read."""
    if case == "running":
        return _start(world, case, base_commit=BASE)
    if case in ("no_worktree", "foreign_branch"):
        # A start refuses such a target; only a stored row can hold one.
        run = _complete(world, case, base_commit=BASE)
        specs = _fake_runs(world).specs
        changed = (
            {"worktree_path": None}
            if case == "no_worktree"
            else {"run_branch": run_branch_name("f" * 32)}
        )
        specs[(WORKSPACE, run.id)] = dataclasses.replace(specs[(WORKSPACE, run.id)], **changed)
        return run
    if case == "unreadable":
        run = _complete(world, case, base_commit=BASE)
        _rows_undecodable(world, run, monkeypatch)
        return run
    if case == "base_unknown":
        return _complete(world, case)
    if case == "host_busy":
        # Another run of the owner's still works on the same host.
        _start(world, "still-running")
        return _complete(world, case, base_commit=BASE)
    if case == "other_user":
        return _complete(world, case, user=BOB, base_commit=BASE)
    raise AssertionError(case)


NO_HOST_OUTCOMES = {
    "running": "run_not_finished",
    "no_worktree": "no_worktree",
    "foreign_branch": "no_worktree",
    "unreadable": "no_worktree",
    "base_unknown": "base_unknown",
    "host_busy": "host_busy",
}


@pytest.mark.parametrize("case", [*NO_HOST_OUTCOMES, "other_user"])
async def test_an_outcome_whose_diff_cannot_be_read_never_contacts_the_host(
    outcomes: tuple[Api, FakeHostChannel, FakeChannels],
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs_api, host, channels = outcomes
    run = _outcome_case(runs_api.world, case, monkeypatch)
    runs_api.calls.clear()

    response = await _outcome(runs_api.api, run.id)

    assert (channels.calls, host.requests) == ([], [])
    if case == "other_user":
        assert (response.status_code, response.content) == (404, NOT_FOUND)
        assert runs_api.calls == ["runs.get_run"]
        return
    body = response.json()
    assert response.status_code == 200, response.text
    assert (body["diff"], body["head_commit"], body["diff_unavailable"]) == (
        None,
        None,
        NO_HOST_OUTCOMES[case],
    )
    has_target = case in ("running", "base_unknown", "host_busy")
    assert body["branch"] == (run_branch_name(run.id) if has_target else None)
    assert (body["checkout"]["command"] is not None) is has_target
    assert body["checkout"]["unavailable"] == (None if has_target else "no_worktree")
    assert ("runs.unfinished_run_hosts" in runs_api.calls) is (case == "host_busy")


@pytest.mark.parametrize(
    "viewer",
    [
        pytest.param(
            Viewer(ALICE, account_generation="g2", check_generation=True), id="re-created-account"
        ),
        pytest.param(Viewer(ALICE), id="unproven-generation"),
    ],
)
async def test_an_outcome_reaches_the_host_only_for_the_runs_recorded_account_generation(
    outcomes: tuple[Api, FakeHostChannel, FakeChannels], viewer: Viewer
) -> None:
    runs_api, host, channels = outcomes
    run = _complete(runs_api.world, "generation", base_commit=BASE, account_generation="g1")
    runs_api.calls.clear()

    with pytest.raises(CoralApiError) as refused:
        await runs_api.api.outcome(viewer, WORKSPACE, run.id)
    refused_work = (list(runs_api.calls), list(channels.calls), list(host.requests))
    owner = Viewer(ALICE, account_generation="g1", check_generation=True)
    outcome = await runs_api.api.outcome(owner, WORKSPACE, run.id)

    assert (refused.value.status, refused.value.error.code) == (404, "not_found")
    assert refused_work == (["runs.get_run"], [], [])
    assert outcome.diff is not None
    assert [(call["user_id"], call["account_generation"]) for call in channels.calls] == [
        (ALICE, "g1")
    ]


HOST_HEX = "0123456789abcdef" * 2
HOST_DASHED = "-".join(
    (HOST_HEX[:8], HOST_HEX[8:12], HOST_HEX[12:16], HOST_HEX[16:20], HOST_HEX[20:])
)


@pytest.mark.parametrize(
    ("live", "finished"),
    [
        pytest.param(f"host_{HOST_HEX}", HOST_HEX, id="legacy-prefix"),
        pytest.param(HOST_DASHED, HOST_HEX, id="dashed"),
        pytest.param(HOST_HEX.upper(), HOST_HEX, id="uppercase"),
        pytest.param(HOST_HEX, f"host_{HOST_HEX.upper()}", id="finished-run-respelled"),
    ],
)
async def test_a_live_run_keeps_its_host_busy_under_any_spelling_of_the_host_id(
    world: World, live: str, finished: str
) -> None:
    host, channels = _outcome_host()
    built, pools = _build(world, channels=channels, canonical_host_id=canonical_host_id)
    try:
        _start(world, "live", host_id=live)
        run = _complete(world, "finished", host_id=finished, base_commit=BASE)
        response = await _outcome(built.api, run.id)
    finally:
        _close(built, pools)

    assert response.status_code == 200, response.text
    assert response.json()["diff_unavailable"] == "host_busy"
    assert (channels.calls, host.requests) == ([], [])


async def test_without_host_channels_a_finished_runs_host_is_offline(runs_api: Api) -> None:
    run = _complete(runs_api.world, "no-channels", base_commit=BASE)

    response = await _outcome(runs_api.api, run.id)

    assert response.status_code == 200, response.text
    assert (response.json()["diff_unavailable"], response.json()["head_commit"]) == (
        "host_offline",
        None,
    )
    assert "runs.unfinished_run_hosts" not in runs_api.calls


async def test_a_finished_runs_outcome_reads_its_diff_on_the_host_and_its_command_checks_it_out(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = shutil.which("git")
    assert git is not None
    isolate_git_home(monkeypatch, tmp_path / "home")
    key = "real-git"
    branch = run_branch_name(run_id_for(ALICE, key))
    # The repository's path holds a space, a quote, a dollar sign and a backtick.
    parent = tmp_path.resolve() / "team's $HOME `id` work"
    repo = parent / "repo"
    base = make_repository(repo)
    worktree = parent / "repo-worktrees" / "coral-run"
    run_git(repo, "worktree", "add", "-q", "-b", branch, str(worktree))
    (worktree / "src" / "app.py").write_bytes(b"print('changed')\nprint('twice')\n")
    (worktree / "NEW.md").write_bytes(b"new\n")
    run_git(worktree, "add", "-A")
    run_git(worktree, "commit", "-q", "-m", "the run's work")
    tip = run_git(worktree, "rev-parse", "HEAD").strip()
    # A tag of the branch's name elsewhere: the command must still name the branch.
    run_git(repo, "tag", branch, base)
    numstat = [
        line.split("\t") for line in run_git(repo, "diff", "--numstat", base, tip).splitlines()
    ]
    host = InProcessHostChannel(host_id="host-1", handlers=workspace_op_handlers())
    built, pools = _build(world, channels=FakeChannels(host, RecordingScopeRunner()))
    try:
        run = _complete(
            world, key, repo_path=str(repo), worktree_path=str(worktree), base_commit=base
        )
        response = await _outcome(built.api, run.id)
    finally:
        _close(built, pools)

    assert response.status_code == 200, response.text
    outcome = response.json()
    assert (outcome["head_commit"], outcome["diff_unavailable"]) == (tip, None)
    assert outcome["diff"] == {
        "from_commit": base,
        "to_commit": tip,
        "files_changed": len(numstat),
        "insertions": sum(int(added) for added, _deleted, _path in numstat),
        "deletions": sum(int(deleted) for _added, deleted, _path in numstat),
        "paths": sorted(path for _added, _deleted, path in numstat),
        "paths_truncated": False,
    }
    # While the run worktree holds the branch, a plain checkout is refused.
    plain = subprocess.run(
        [git, "-C", str(repo), "checkout", branch], capture_output=True, check=False
    )
    assert plain.returncode != 0
    assert run_git(repo, "rev-parse", "HEAD").strip() == base

    checked_out = subprocess.run(
        ["sh", "-c", outcome["checkout"]["command"]], capture_output=True, check=False
    )
    assert checked_out.returncode == 0, checked_out.stderr.decode(errors="replace")
    assert b"ambiguous" not in checked_out.stderr
    assert run_git(repo, "rev-parse", "HEAD").strip() == tip
    detached = subprocess.run(
        [git, "-C", str(repo), "symbolic-ref", "-q", "HEAD"], capture_output=True, check=False
    )
    assert detached.returncode == 1
    opened = subprocess.run(
        ["sh", "-c", f"{outcome['checkout']['worktree_command']} && pwd -P"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert (opened.returncode, opened.stdout.strip()) == (0, str(worktree))


@pytest.mark.parametrize("route", ["", *(f"/{UNKNOWN_RUN}{route}" for route in READ_ROUTES)])
async def test_without_the_runs_api_every_read_route_is_the_run_404_after_authentication(
    route: str,
) -> None:
    async with _client(_app(None)) as client:
        anonymous = await client.get(f"{RUNS}{route}")
        signed_in = await client.get(f"{RUNS}{route}", headers=_as(ALICE))

    assert _refusal(anonymous) == (401, "unauthenticated")
    assert (signed_in.status_code, signed_in.content) == (404, NOT_FOUND)
    assert [response.headers["cache-control"] for response in (anonymous, signed_in)] == [
        "private, no-store"
    ] * 2


async def test_with_authentication_off_the_local_user_reads_its_runs(runs_api: Api) -> None:
    world = runs_api.world
    run = _start(world, "local", user=None)
    _start(world, "alices")

    async with _client(_app(runs_api.api, auth_provider=None)) as client:
        listed = (await client.get(RUNS)).json()["data"]
        detail = await client.get(f"{RUNS}/{run.id}")

    assert [item["run_id"] for item in listed] == [run.id]
    assert detail.status_code == 200


# ── Fairness ────────────────────────────────────────────────────────────────


def test_the_caps_are_the_designed_ones() -> None:
    assert (MAX_API_CALLS_PER_USER, API_CALL_TIMEOUT_S) == (8, 30.0)
    # One user's calls can hold at most half the threads, so another user's call runs.
    assert API_THREADS == 2 * MAX_API_CALLS_PER_USER
    # One call per thread: an admitted call never queues for one.
    assert MAX_API_CALLS == API_THREADS


async def test_a_full_pool_refuses_another_user_at_once_instead_of_queueing_the_call(
    world: World, held: HeldRuns
) -> None:
    built, pools = _build(world, run_store=held)
    alices, carols = _start(world, "alices"), _start(world, "carols", user="carol")
    bobs = _start(world, "bobs", user=BOB)
    held.held.update({alices.id, carols.id})
    try:
        async with _client(_app(built.api)) as client:
            slow = [
                asyncio.create_task(client.get(f"{RUNS}/{run.id}", headers=_as(user)))
                for run, user in ((alices, ALICE), (carols, "carol"))
                for _ in range(MAX_API_CALLS_PER_USER)
            ]
            await poll_until_async(lambda: held.waiting == API_THREADS, timeout_s=budget(10))
            third_user = await client.get(f"{RUNS}/{bobs.id}", headers=_as(BOB))
            in_flight_then = built.in_flight.in_flight
            held.release.set()
            finished = await asyncio.gather(*slow)
            after = await client.get(f"{RUNS}/{bobs.id}", headers=_as(BOB))
    finally:
        held.release.set()
        built.spend.close()
        for pool in pools:
            pool.close()

    # Refused before taking a slot, with no wait for a thread.
    assert _refusal(third_user) == (503, "server_busy")
    assert third_user.headers["retry-after"] == "1"
    assert in_flight_then == API_THREADS
    assert [response.status_code for response in finished] == [200] * API_THREADS
    assert after.status_code == 200, after.text


async def test_a_ninth_call_of_one_user_is_busy_while_another_user_s_call_proceeds(
    world: World, held: HeldRuns
) -> None:
    built, pools = _build(world, run_store=held)
    alices, bobs = _start(world, "alices"), _start(world, "bobs", user=BOB)
    held.held.add(alices.id)
    try:
        async with _client(_app(built.api)) as client:
            slow = [
                asyncio.create_task(client.get(f"{RUNS}/{alices.id}", headers=_as(ALICE)))
                for _ in range(MAX_API_CALLS_PER_USER)
            ]
            await poll_until_async(
                lambda: held.waiting == MAX_API_CALLS_PER_USER, timeout_s=budget(10)
            )
            ninth = await client.get(f"{RUNS}/{alices.id}", headers=_as(ALICE))
            other_user = await client.get(f"{RUNS}/{bobs.id}", headers=_as(BOB))
            held.release.set()
            finished = await asyncio.gather(*slow)
    finally:
        held.release.set()
        built.spend.close()
        for pool in pools:
            pool.close()

    assert _refusal(ninth) == (503, "server_busy")
    assert ninth.headers["retry-after"] == "1"
    assert other_user.status_code == 200, other_user.text
    assert [response.status_code for response in finished] == [200] * MAX_API_CALLS_PER_USER
    assert held.waiting == MAX_API_CALLS_PER_USER


async def test_a_call_past_its_timeout_is_busy_and_holds_its_slot_until_its_thread_ends(
    world: World, held: HeldRuns
) -> None:
    built, pools = _build(world, run_store=held, max_per_caller=1, timeout_s=budget(1))
    run = _start(world, "slow")
    held.held.add(run.id)
    try:
        async with _client(_app(built.api)) as client:
            timed_out = await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))
            # The thread still runs the first call, so its slot is still held.
            refused = await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))
            waiting_then = held.waiting
            held.held.clear()
            held.release.set()
            await poll_until_async(lambda: built.in_flight.in_flight == 0, timeout_s=budget(10))
            after = await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))
    finally:
        held.release.set()
        built.spend.close()
        for pool in pools:
            pool.close()

    assert _refusal(timed_out) == (503, "server_busy")
    assert timed_out.headers["retry-after"] == "1"
    assert _refusal(refused) == (503, "server_busy")
    assert waiting_then == 1
    assert after.status_code == 200, after.text


async def test_the_process_cap_refuses_any_caller_past_it() -> None:
    threads = BoundedThreads(max_workers=2, thread_name_prefix="test-in-flight")
    in_flight = InFlight(threads, max_calls=2, max_per_caller=2)
    release = threading.Event()
    alice, bob = Viewer(user_id=ALICE), Viewer(user_id=BOB)
    try:
        held = [
            asyncio.create_task(in_flight.run(alice, release.wait, budget(10))) for _ in range(2)
        ]
        await poll_until_async(lambda: in_flight.in_flight == 2, timeout_s=budget(10))
        with pytest.raises(CoralApiError) as busy:
            await in_flight.run(bob, lambda: None)
        release.set()
        assert await asyncio.gather(*held) == [True, True]
    finally:
        release.set()
        threads.close()

    assert (busy.value.status, busy.value.error.code) == (503, "server_busy")
    assert in_flight.in_flight == 0


async def test_a_call_that_fails_gives_its_slot_back() -> None:
    threads = BoundedThreads(max_workers=1, thread_name_prefix="test-in-flight")
    in_flight = InFlight(threads, max_per_caller=1)
    alice = Viewer(user_id=ALICE)

    def store_fault() -> None:
        raise RuntimeError("store fault")

    try:
        # More failures than the caller's share: a slot kept by any of them refuses the next.
        for _ in range(3):
            with pytest.raises(RuntimeError, match="store fault"):
                await in_flight.run(alice, store_fault)
        read = await in_flight.run(alice, lambda: "read")
    finally:
        threads.close()

    assert read == "read"
    assert in_flight.in_flight == 0


async def test_a_call_whose_client_went_away_holds_its_slot_until_its_thread_ends() -> None:
    # A spare thread, so a slot freed too early lets the next call run instead of refusing it.
    threads = BoundedThreads(max_workers=2, thread_name_prefix="test-in-flight")
    in_flight = InFlight(threads, max_per_caller=1)
    release = threading.Event()
    alice, bob = Viewer(user_id=ALICE), Viewer(user_id=BOB)
    try:
        request = asyncio.create_task(in_flight.run(alice, release.wait, budget(10)))
        await poll_until_async(lambda: in_flight.in_flight == 1, timeout_s=budget(10))
        # The request is cancelled; its thread call goes on.
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        # Another caller's call goes through a thread meanwhile.
        others = await in_flight.run(bob, lambda: "bob's")
        held_then = in_flight.in_flight
        with pytest.raises(CoralApiError) as busy:
            await in_flight.run(alice, lambda: None)
        release.set()
        await poll_until_async(lambda: in_flight.in_flight == 0, timeout_s=budget(10))
        read = await in_flight.run(alice, lambda: "read")
    finally:
        release.set()
        threads.close()

    assert (others, held_then) == ("bob's", 1)
    assert (busy.value.status, busy.value.error.code) == (503, "server_busy")
    assert read == "read"


async def test_a_closed_pool_is_busy() -> None:
    threads = BoundedThreads(max_workers=1, thread_name_prefix="test-in-flight")
    in_flight = InFlight(threads)
    threads.close()

    with pytest.raises(CoralApiError) as busy:
        await in_flight.run(Viewer(user_id=ALICE), lambda: None)

    assert (busy.value.status, busy.value.error.code) == (503, "server_busy")
    assert in_flight.in_flight == 0


async def test_one_user_s_detail_spend_reads_never_delay_another_user_s_detail(
    runs_api: Api,
) -> None:
    world = runs_api.world
    alices = [_start(world, f"alice-{index}") for index in range(3)]
    bobs = _start(world, "bobs", user=BOB)
    reader = runs_api.reader
    # Alice's spend reads are slow: each would hold a spend thread.
    reader.held.update(run.id for run in alices)

    async with _client(_app(runs_api.api)) as client:
        first = asyncio.create_task(client.get(f"{RUNS}/{alices[0].id}", headers=_as(ALICE)))
        await poll_until_async(lambda: len(reader.reads) == 1, timeout_s=budget(10))
        # Past her one detail read, her other details answer from the cache at once.
        others = [
            (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json() for run in alices[1:]
        ]
        bob = (await client.get(f"{RUNS}/{bobs.id}", headers=_as(BOB))).json()
        reader.release.set()
        alice = (await first).json()

    assert [detail["spend"] for detail in others] == [None, None]
    # Bob's read had a thread of its own: his detail shows his spend.
    assert bob["spend"] is not None
    assert alice["spend"] is not None


# ── Writes: shared steps ────────────────────────────────────────────────────


def _start_body(workflow_id: str, key: str = "start-1", **fields: Any) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "start_key": key,
        "host_id": "host-1",
        "repo_path": REPO,
        **fields,
    }


def _replay_body(key: str, **fields: Any) -> dict[str, Any]:
    """The request :func:`_start`'s spec stores, for a replay of that start."""
    return {**_start_body(DEFINITION, key, request="Make runs advance"), **fields}


def _branch(user: str | None, key: str) -> str:
    return run_branch_name(derived_id("coral-run", user or "", key))


def _row_state(world: World, run_id: str) -> tuple[str, str | None, int]:
    run = world.run(run_id)
    reason = None if run.pause_reason is None else RunPauseReason(run.pause_reason).name.lower()
    return RunStatus(run.status).name.lower(), reason, run.version


def _count_runs(world: World) -> int:
    return len(_fake_runs(world).runs)


def _anchor_prompt(world: World, run: CoralRun) -> tuple[str, str]:
    state, _version = world.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    [row] = state.gate_visits
    assert row.elicitation_id is not None
    return anchor_session_id(WORKSPACE, run.id), row.elicitation_id


# ── Preflight ───────────────────────────────────────────────────────────────


async def test_preflight_reports_an_offline_host_without_starting_a_run(
    writes: Api,
) -> None:
    from coral.omni.server.preflight import OmniWorkflowPreflight
    from omnigent.policies.registry import load_registry
    from omnigent.server.host_registry import HostRegistry

    # Bare app has no Coral plugin; register the handlers step bundles name.
    load_registry(extra_modules=["coral.omni.policies.hygiene", "coral.omni.policies.guards"])
    definition = writes.services.definitions.save()
    writes.api._workflow_preflight = OmniWorkflowPreflight(HostRegistry())
    body = {"workflow_id": definition.id, "host_id": "missing-host"}

    async with _client(writes.app()) as client:
        response = await client.post(f"{RUNS}:preflight", headers=_as(ALICE), json=body)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is False
    assert payload["estimate"]["sessions"] >= 2
    failures = {
        item["check"]: item["fix"]["target"]
        for item in payload["items"]
        if item["status"] == "fail" and item["fix"] is not None
    }
    assert failures["host_online"] == "connect_host"
    assert _count_runs(writes.world) == 0


async def test_preflight_of_another_users_workflow_is_not_found(writes: Api) -> None:
    definition = writes.services.definitions.save(owner=ALICE)
    body = {"workflow_id": definition.id, "host_id": "host-1"}

    async with _client(writes.app()) as client:
        response = await client.post(f"{RUNS}:preflight", headers=_as(BOB), json=body)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# ── Start ───────────────────────────────────────────────────────────────────


async def test_a_start_makes_the_run_on_its_worktree_and_a_retry_replays_it(
    writes: Api,
) -> None:
    world, host = writes.world, writes.services.host
    definition = writes.services.definitions.save()
    body = _start_body(
        definition.id,
        "ship",
        title="Ship it",
        request="Make it so.",
        base_ref="main",
        max_activations=50,
    )

    async with _client(writes.app()) as client:
        first = await client.post(RUNS, headers=_as(ALICE), json=body)
        again = await client.post(RUNS, headers=_as(ALICE), json=body)

    assert first.status_code == 201, first.text
    created = first.json()
    assert first.headers["location"] == f"/v1/coral/runs/{created['run_id']}"
    assert created["run_id"] == derived_id("coral-run", ALICE, "ship")
    assert (created["status"], created["title"], created["workflow_id"]) == (
        "running",
        "Ship it",
        definition.id,
    )
    assert created["allowed_actions"] == ["pause", "cancel"]
    assert again.status_code == 200, again.text
    assert again.json()["run_id"] == created["run_id"]
    assert again.headers["location"] == first.headers["location"]
    # One run on one worktree; the retry touched no host.
    assert (_count_runs(world), host.creates(), len(host.connected)) == (1, 1, 1)
    assert host.connected == [
        {
            "user_id": ALICE,
            "account_generation": None,
            "host_id": "host-1",
            "workspace_id": WORKSPACE,
        }
    ]
    state, _version = world.runs.load_run_state(created["run_id"], workspace_id=WORKSPACE)
    spec = state.spec
    branch = _branch(ALICE, "ship")
    assert (spec.user_id, spec.account_generation, spec.workflow_id) == (
        ALICE,
        None,
        definition.id,
    )
    assert (spec.host_id, spec.repo_path, spec.worktree_path, spec.run_branch) == (
        "host-1",
        REPO,
        host.path_of(branch),
        branch,
    )
    assert (spec.base_ref, spec.base_commit, spec.max_activations) == ("main", HEAD, 50)
    assert (spec.title, spec.request_preview) == ("Ship it", "Make it so.")
    assert ("create", branch, "main") in host.calls
    assert created["run_branch"] == again.json()["run_branch"] == branch


async def test_a_start_stores_its_host_id_in_canonical_form_and_replays_any_spelling(
    world: World, tmp_path: Path
) -> None:
    built, pools = _build(
        world, writes=_writes(world, tmp_path), canonical_host_id=canonical_host_id
    )
    try:
        definition = built.services.definitions.save()
        legacy = _start_body(definition.id, "spelled", host_id=f"host_{HOST_HEX.upper()}")
        dashed = {**legacy, "host_id": HOST_DASHED}
        async with _client(built.app()) as client:
            first = await client.post(RUNS, headers=_as(ALICE), json=legacy)
            again = await client.post(RUNS, headers=_as(ALICE), json=dashed)
            detail = await client.get(f"{RUNS}/{first.json()['run_id']}", headers=_as(ALICE))
    finally:
        _close(built, pools)

    assert first.status_code == 201, first.text
    assert (again.status_code, again.json()["run_id"]) == (200, first.json()["run_id"])
    assert detail.json()["target"]["host_id"] == HOST_HEX
    assert [call["host_id"] for call in built.services.host.connected] == [HOST_HEX]


async def test_a_start_without_a_title_takes_the_workflow_s_name(writes: Api) -> None:
    definition = writes.services.definitions.save()

    async with _client(writes.app()) as client:
        response = await client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id))

    assert response.status_code == 201, response.text
    assert response.json()["title"] == "Two steps"


async def test_a_default_title_holds_no_control_or_bidirectional_characters(
    writes: Api,
) -> None:
    named = TWO_STEPS.replace("name: Two steps", 'name: "Two \\u202e steps\\x1b[2J"')
    definition = writes.services.definitions.save(yaml_text=named)
    assert "\u202e" in definition.name

    async with _client(writes.app()) as client:
        response = await client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id))

    assert response.status_code == 201, response.text
    assert response.json()["title"] == "Two steps [2J"


@pytest.mark.parametrize(
    "change",
    [
        {"workflow_id": OTHER_WORKFLOW},
        {"host_id": "host-2"},
        {"repo_path": "/repo/other"},
        {"base_ref": "main"},
        {"request": "Something else"},
        {"max_activations": 99},
        {"title": "Another title"},
    ],
    ids=lambda change: next(iter(change)),
)
async def test_a_retry_with_another_request_is_a_conflict(
    writes: Api, change: dict[str, Any]
) -> None:
    run = _start(writes.world, "taken")

    async with _client(writes.app()) as client:
        conflict = await client.post(
            RUNS, headers=_as(ALICE), json=_replay_body("taken", **change)
        )
        same = await client.post(RUNS, headers=_as(ALICE), json=_replay_body("taken"))
        titled = await client.post(
            RUNS, headers=_as(ALICE), json=_replay_body("taken", title="Ship the bridge")
        )

    assert _refusal(conflict) == (409, "start_key_conflict")
    # No run data in the refusal.
    assert conflict.json()["error"]["details"] is None
    assert (same.status_code, titled.status_code) == (200, 200)
    assert same.json()["run_id"] == run.id
    assert writes.services.host.connected == []


async def test_a_replay_never_reads_the_workflow_again(writes: Api) -> None:
    definitions = writes.services.definitions
    definition = definitions.save()
    body = _start_body(definition.id, "ship")
    unrunnable = workflow_text(
        [start_node(), step("implement")], [arrow("a1", "start", "implement")], id="two-steps"
    )

    async with _client(writes.app()) as client:
        created = await client.post(RUNS, headers=_as(ALICE), json=body)
        definitions.save(yaml_text=TWO_STEPS.replace("Review the change", "Review it twice"))
        edited = await client.post(RUNS, headers=_as(ALICE), json=body)
        assert not definitions.save(yaml_text=unrunnable).runnable
        not_runnable = await client.post(RUNS, headers=_as(ALICE), json=body)
        definitions.delete_all()
        deleted = await client.post(RUNS, headers=_as(ALICE), json=body)

    assert created.status_code == 201, created.text
    assert [response.status_code for response in (edited, not_runnable, deleted)] == [200] * 3
    assert {response.json()["run_id"] for response in (edited, not_runnable, deleted)} == {
        created.json()["run_id"]
    }


async def test_a_replay_of_a_run_that_cannot_load_answers_it_and_never_pauses_it(
    writes: Api,
) -> None:
    world = writes.world
    run = _start(world, "broken")
    _config_missing(world, run)
    before = (world.run(run.id), tuple(_fake_runs(world).logs[(WORKSPACE, run.id)]))

    async with _client(writes.app()) as client:
        response = await client.post(RUNS, headers=_as(ALICE), json=_replay_body("broken"))

    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["allowed_actions"]) == (
        "running",
        ["cancel"],
    )
    assert (world.run(run.id), tuple(_fake_runs(world).logs[(WORKSPACE, run.id)])) == before


async def test_a_replay_of_a_run_left_starting_starts_its_engine(writes: Api) -> None:
    world = writes.world
    run = start_without_engine(world, start_key="bare")
    assert _row_state(world, run.id)[0] == "starting"

    async with _client(writes.app()) as client:
        response = await client.post(RUNS, headers=_as(ALICE), json=_replay_body("bare"))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    assert _row_state(world, run.id)[0] == "running"


async def test_a_replay_whose_stored_request_cannot_be_read_is_a_conflict(
    writes: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _start(writes.world, "undecodable")
    _rows_undecodable(writes.world, run, monkeypatch)

    async with _client(writes.app()) as client:
        response = await client.post(RUNS, headers=_as(ALICE), json=_replay_body("undecodable"))

    # The key's run exists: the answer says it is unreadable, so a client does not re-key.
    assert response.json()["error"] == {
        "code": "start_key_conflict",
        "message": (
            "This start key's run cannot be read back to compare the request; "
            "it can only be cancelled."
        ),
        "details": {"reason": "engine.load_failed"},
    }


async def test_concurrent_starts_of_one_key_make_one_run(writes: Api) -> None:
    host = writes.services.host
    definition = writes.services.definitions.save()
    host.held.add(_branch(ALICE, "once"))
    body = _start_body(definition.id, "once")

    async with _client(writes.app()) as client:
        first = asyncio.create_task(client.post(RUNS, headers=_as(ALICE), json=body))
        await poll_until_async(lambda: bool(host.creating), timeout_s=budget(10))
        second = asyncio.create_task(client.post(RUNS, headers=_as(ALICE), json=body))
        # The second waits for the first instead of reaching the host.
        await poll_until_async(lambda: writes.api.starts.in_flight == 2, timeout_s=budget(10))
        listings_then = len([call for call in host.calls if call[0] == "list"])
        host.release.set()
        responses = await asyncio.gather(first, second)

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert len({response.json()["run_id"] for response in responses}) == 1
    assert (listings_then, host.creates(), _count_runs(writes.world)) == (1, 1, 1)


async def test_a_worktree_another_replica_is_creating_is_busy_until_its_run_exists(
    writes: Api,
) -> None:
    host = writes.services.host
    definition = writes.services.definitions.save()
    host.held.add(_branch(ALICE, "shared"))
    body = _start_body(definition.id, "shared")
    # Another replica: its own start slots and per-key locks, the same stores and host.
    replica, pools = _build(writes.world, writes=writes.services)
    try:
        async with (
            _client(writes.app()) as here,
            _client(replica.app()) as there,
        ):
            first = asyncio.create_task(here.post(RUNS, headers=_as(ALICE), json=body))
            await poll_until_async(lambda: bool(host.creating), timeout_s=budget(10))
            busy = await there.post(RUNS, headers=_as(ALICE), json=body)
            host.release.set()
            created = await first
            replayed = await there.post(RUNS, headers=_as(ALICE), json=body)
    finally:
        replica.reader.release.set()
        replica.spend.close()
        for pool in pools:
            pool.close()

    assert _refusal(busy) == (503, "server_busy")
    assert busy.headers["retry-after"] == "2"
    # An interrupted checkout leaves the lock behind: the answer says how to repair it.
    assert "repair it" in busy.json()["error"]["message"]
    assert (created.status_code, replayed.status_code) == (201, 200)
    assert _count_runs(writes.world) == 1


async def test_a_locked_worktree_whose_run_appeared_meanwhile_is_a_replay(writes: Api) -> None:
    world, host = writes.world, writes.services.host
    definition = writes.services.definitions.save()
    branch = _branch(ALICE, "raced")
    body = _start_body(definition.id, "raced", request="Make runs advance")

    def other_replica_started() -> None:
        # Another replica stored the run and its checkout still holds the worktree's lock.
        if host.before_list is None:
            return
        host.before_list = None
        start(
            world,
            TWO_STEPS,
            spec=run_spec(
                user=ALICE,
                start_key="raced",
                workflow_id=definition.id,
                worktree_path=host.path_of(branch),
            ),
            start_key="raced",
            actor=ALICE,
        )
        host.worktrees[branch] = host.path_of(branch)
        host.creating.add(branch)

    host.before_list = other_replica_started

    async with _client(writes.app()) as client:
        response = await client.post(RUNS, headers=_as(ALICE), json=body)

    assert response.status_code == 200, response.text
    assert host.creates() == 0
    assert _count_runs(world) == 1


async def test_a_start_from_another_users_workflow_is_not_found(writes: Api) -> None:
    definition = writes.services.definitions.save(owner=ALICE)

    async with _client(writes.app()) as client:
        bobs = await client.post(RUNS, headers=_as(BOB), json=_start_body(definition.id))
        unknown = await client.post(RUNS, headers=_as(ALICE), json=_start_body(OTHER_WORKFLOW))

    for response in (bobs, unknown):
        assert (response.status_code, response.json()) == (
            404,
            {"error": {"code": "not_found", "message": "Workflow not found.", "details": None}},
        )
    assert writes.services.host.connected == []
    assert _count_runs(writes.world) == 0


async def test_a_workflow_with_no_owner_starts_only_on_a_single_user_server(
    writes: Api,
) -> None:
    legacy = writes.services.definitions.save(owner=None)

    async with _client(writes.app()) as signed_in, _client(writes.app(None)) as local:
        refused = await signed_in.post(RUNS, headers=_as(ALICE), json=_start_body(legacy.id))
        started = await local.post(RUNS, json=_start_body(legacy.id))

    assert _refusal(refused) == (404, "not_found")
    assert started.status_code == 201, started.text
    run = writes.world.run(started.json()["run_id"])
    assert (run.id, run.user_id) == (derived_id("coral-run", "", "start-1"), None)


async def test_a_workflow_that_cannot_run_is_refused_before_any_host_is_reached(
    writes: Api,
) -> None:
    definitions = writes.services.definitions
    unrunnable = definitions.save(
        yaml_text=workflow_text(
            [start_node(), step("implement")], [arrow("a1", "start", "implement")], id="stuck"
        )
    )
    two_writers = definitions.save(
        yaml_text=workflow_text(
            [start_node(), step("pair", ["implementer", "implementer"]), end_node()],
            [arrow("a1", "start", "pair"), arrow("a2", "pair", "end")],
            id="pair",
        )
    )
    assert two_writers.runnable

    async with _client(writes.app()) as client:
        responses = [
            await client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id, key))
            for definition, key in ((unrunnable, "stuck"), (two_writers, "pair"))
        ]

    assert [_refusal(response) for response in responses] == [(422, "not_runnable")] * 2
    assert [response.json()["error"]["details"]["rule"] for response in responses] == [
        "workflow.invalid",
        "graph.concurrent_writers",
    ]
    assert writes.services.host.connected == []


async def test_a_profile_the_starter_has_no_revision_of_is_refused_before_any_host_is_reached(
    writes: Api,
) -> None:
    world, host = writes.world, writes.services.host
    definition = writes.services.definitions.save(
        yaml_text=workflow_text(
            [start_node(), step("review", ["reviewer/strict"]), end_node()],
            [arrow("a1", "start", "review"), arrow("a2", "review", "end")],
            id="strict",
        )
    )
    assert definition.runnable

    async with _client(writes.app()) as client:
        missing = await client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id))
        world.profiles.save_revision(
            workspace_id=WORKSPACE,
            profile_ref="reviewer/strict",
            owner=ALICE,
            spec=ProfileSpec(name="Strict", instructions="Be strict."),
            base_revision_no=None,
        )
        # Refused with no worktree made, no host connected, and no run stored.
        assert (host.creates(), host.connected, _count_runs(world)) == (0, [], 0)
        started = await client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id, "2"))

    assert _refusal(missing) == (422, "not_runnable")
    assert missing.json()["error"]["details"]["rule"] == "profile.missing", missing.text
    assert started.status_code == 201, started.text
    assert world.profiles.run_pin(
        workspace_id=WORKSPACE, run_id=started.json()["run_id"], profile_ref="reviewer/strict"
    ) == revision_id("reviewer/strict", 1)


async def test_an_accounts_server_starts_only_for_a_proven_account_generation(
    world: World, tmp_path: Path
) -> None:
    built, pools = _build(world, writes=_writes(world, tmp_path), requires_generation=True)
    host = built.services.host
    definition = built.services.definitions.save()
    proven = Viewer(user_id=ALICE, account_generation="gen-1", check_generation=True)
    try:
        async with _client(built.app()) as client:
            # A header-authenticated request proves no generation.
            refused = await client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id))
        started = await built.api.start(
            proven,
            WORKSPACE,
            StartRunRequest.model_validate(_start_body(definition.id)),
            definitions=built.services.definitions.store,
        )
    finally:
        _close(built, pools)

    assert _refusal(refused) == (403, "not_permitted")
    assert started.created
    assert host.connected[-1]["account_generation"] == "gen-1"
    assert world.run(started.summary.run_id).account_generation == "gen-1"


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        pytest.param(
            {"refuse": RunWorktreeError("host_offline", "host 'host-1' is not connected")},
            (503, "host_offline"),
            id="host-offline",
        ),
        pytest.param(
            {"refuse": RunWorktreeError("not_permitted", "host 'host-1' is not available")},
            (403, "not_permitted"),
            id="host-refused",
        ),
        pytest.param({"repo_path": "/not/a/repo"}, (400, "not_a_git_repo"), id="not-a-repo"),
        pytest.param({"failing": True}, (409, "worktree_failed"), id="worktree-failed"),
        pytest.param({"no_host": True}, (503, "host_offline"), id="no-host-connector"),
    ],
)
async def test_host_and_worktree_failures_map_to_their_refusals(
    world: World, tmp_path: Path, setup: dict[str, Any], expected: tuple[int, str]
) -> None:
    writes = _writes(world, tmp_path)
    built, pools = _build(world, writes=writes, with_host=not setup.get("no_host"))
    writes.host.refuse = setup.get("refuse")
    writes.host.failing = setup.get("failing", False)
    definition = writes.definitions.save()
    body = _start_body(definition.id, repo_path=setup.get("repo_path", REPO))
    try:
        async with _client(built.app()) as client:
            response = await client.post(RUNS, headers=_as(ALICE), json=body)
    finally:
        _close(built, pools)

    assert _refusal(response) == expected
    assert _count_runs(world) == 0
    # A refused start gives its slot back, so the user's next start is not busy.
    assert built.api.starts.in_flight == 0


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"unknown_field": 1}, id="extra-field"),
        pytest.param({"start_key": "has space"}, id="start-key-space"),
        pytest.param({"start_key": "k" * 65}, id="start-key-65"),
        pytest.param({"start_key": ""}, id="start-key-empty"),
        pytest.param({"workflow_id": "not-a-workflow"}, id="workflow-id"),
        pytest.param({"host_id": ""}, id="host-id-empty"),
        pytest.param({"host_id": "h" * 65}, id="host-id-65"),
        pytest.param({"host_id": "host\x00"}, id="host-id-nul"),
        pytest.param({"host_id": "not-a-\x1bhost"}, id="host-id-control"),
        pytest.param({"repo_path": ""}, id="repo-path-empty"),
        pytest.param({"repo_path": "/" + "r" * 2048}, id="repo-path-2049"),
        pytest.param({"repo_path": "/not-a-\x1brepo"}, id="repo-path-control"),
        pytest.param({"base_ref": "-main"}, id="base-ref-option"),
        pytest.param({"base_ref": ""}, id="base-ref-empty"),
        pytest.param({"base_ref": "b" * 256}, id="base-ref-256"),
        pytest.param({"base_ref": "not-a-\x1bref"}, id="base-ref-control"),
        pytest.param({"title": ""}, id="title-empty"),
        pytest.param({"title": "t" * 257}, id="title-257"),
        pytest.param({"title": "not-a-\x1b[2Jtitle"}, id="title-control"),
        pytest.param({"title": "not-a-\u202etitle"}, id="title-bidi"),
        pytest.param({"title": "not-a-\u200ftitle"}, id="title-bidi-mark"),
        pytest.param({"title": "not-a-\x7ftitle"}, id="title-del"),
        pytest.param({"title": "not-a-\x9btitle"}, id="title-c1"),
        pytest.param({"request": "r" * 513}, id="request-513"),
        pytest.param({"request": "not-a-\x07request"}, id="request-control"),
        pytest.param({"request": "not-a-\u2066request"}, id="request-bidi"),
        pytest.param({"request": "not-a-\x00request"}, id="request-nul"),
        pytest.param({"max_activations": 0}, id="max-activations-0"),
        pytest.param({"max_activations": 1001}, id="max-activations-1001"),
        # A count is a JSON integer: never a boolean, a string or a float.
        pytest.param({"max_activations": True}, id="max-activations-true"),
        pytest.param({"max_activations": "7"}, id="max-activations-string"),
        pytest.param({"max_activations": 2.0}, id="max-activations-float"),
    ],
)
async def test_a_start_body_out_of_bounds_is_refused_before_any_work(
    writes: Api, change: dict[str, Any]
) -> None:
    body = {**_start_body("a" * 32), **change}

    async with _client(writes.app()) as client:
        response = await client.post(RUNS, headers=_as(ALICE), json=body)

    assert _refusal(response) == (422, "validation_failed")
    # Refusals never echo what was sent.
    assert "not-a-" not in response.text
    assert writes.calls == []


async def test_a_start_body_with_a_lone_surrogate_is_refused(writes: Api) -> None:
    raw = json.dumps(_start_body("a" * 32)).replace(REPO, "/repo/\\ud800")

    async with _client(writes.app()) as client:
        response = await client.post(
            RUNS,
            headers={**_as(ALICE), "content-type": "application/json"},
            content=raw.encode(),
        )

    assert _refusal(response) == (422, "validation_failed")
    assert writes.calls == []


async def test_a_request_may_hold_line_breaks_and_tabs(writes: Api) -> None:
    definition = writes.services.definitions.save()
    text = "First line\n\tthen an indented one"

    async with _client(writes.app()) as client:
        response = await client.post(
            RUNS, headers=_as(ALICE), json=_start_body(definition.id, request=text)
        )

    assert response.status_code == 201, response.text
    state, _version = writes.world.runs.load_run_state(
        response.json()["run_id"], workspace_id=WORKSPACE
    )
    assert state.spec.request_preview == text


def test_the_start_caps_are_the_designed_ones() -> None:
    assert (MAX_STARTS, MAX_STARTS_PER_USER) == (8, 2)
    assert (START_HEAD_TIMEOUT_S, START_HEAD_DEADLINE_S) == (5.0, 10.0)


async def test_a_third_concurrent_start_of_one_user_is_busy_while_another_user_starts(
    writes: Api,
) -> None:
    host = writes.services.host
    definitions = writes.services.definitions
    alices, bobs = (
        definitions.save(owner=ALICE),
        definitions.save(
            owner=BOB, yaml_text=TWO_STEPS.replace("id: two-steps", "id: bobs-steps")
        ),
    )
    host.held.update({_branch(ALICE, "one"), _branch(ALICE, "two")})

    async with _client(writes.app()) as client:
        held = [
            asyncio.create_task(
                client.post(RUNS, headers=_as(ALICE), json=_start_body(alices.id, key))
            )
            for key in ("one", "two")
        ]
        await poll_until_async(lambda: len(host.creating) == 2, timeout_s=budget(10))
        third = await client.post(RUNS, headers=_as(ALICE), json=_start_body(alices.id, "three"))
        other_user = await client.post(RUNS, headers=_as(BOB), json=_start_body(bobs.id, "b"))
        host.release.set()
        finished = await asyncio.gather(*held)

    assert _refusal(third) == (503, "server_busy")
    assert third.headers["retry-after"] == "1"
    assert other_user.status_code == 201, other_user.text
    assert [response.status_code for response in finished] == [201, 201]
    assert writes.api.starts.in_flight == 0


# ── The start head ──────────────────────────────────────────────────────────

# What the scripted host channel reads as a run worktree's HEAD.
START_HEAD = "3" * 40
SECRET_PATH = "/home/alice/secret repo"


@pytest.fixture
async def start_heads(
    world: World, tmp_path: Path
) -> AsyncIterator[tuple[Api, FakeHostChannel, FakeChannels]]:
    host_channel, channels = _outcome_host(START_HEAD)
    built, pools = _build(world, writes=_writes(world, tmp_path), channels=channels)
    yield built, host_channel, channels
    _close(built, pools)


def _stored_base(world: World, run_id: str) -> str | None:
    state, _version = world.runs.load_run_state(run_id, workspace_id=WORKSPACE)
    return state.spec.base_commit


def _start_head_logs(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage() for record in caplog.records if record.name == run_service.__name__
    ]


def _crash(*_args: object, **_kwargs: object) -> NoReturn:
    raise RuntimeError("the server stopped before it stored the run")


async def test_a_retry_after_a_crash_between_the_worktree_and_its_run_stores_the_worktrees_head(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host_channel, channels = _outcome_host(START_HEAD)
    built, pools = _build(
        world,
        writes=_writes(world, tmp_path),
        channels=channels,
        canonical_host_id=canonical_host_id,
    )
    host, definitions = built.services.host, built.services.definitions
    owner = Viewer(ALICE, account_generation="g1", check_generation=True)
    request = StartRunRequest.model_validate(
        _start_body(definitions.save().id, "crashed", host_id=f"host_{HOST_HEX.upper()}")
    )
    branch = _branch(ALICE, "crashed")
    try:
        with monkeypatch.context() as patched:
            patched.setattr(run_service, "start_engine_run", _crash)
            with pytest.raises(RuntimeError):
                await built.api.start(owner, WORKSPACE, request, definitions=definitions.store)
        crashed = (_count_runs(world), host.creates(), list(host_channel.requests))
        retried = await built.api.start(owner, WORKSPACE, request, definitions=definitions.store)
        replayed = await built.api.start(owner, WORKSPACE, request, definitions=definitions.store)
    finally:
        _close(built, pools)

    # The crashed start created the worktree, which reported its commit, and stored no run.
    assert crashed == (0, 1, [])
    assert (retried.created, replayed.created) == (True, False)
    # The retry adopted it and read its head as the starting owner; the replay read nothing.
    assert host.creates() == 1
    assert channels.calls == [
        {
            "workspace_id": WORKSPACE,
            "user_id": ALICE,
            "account_generation": "g1",
            "host_id": HOST_HEX,
            "scope": None,
        }
    ]
    assert host_channel.requests == [
        ChannelRequest(
            HOST_HEX,
            "head",
            host.path_of(branch),
            {"repo_root": REPO, "branch": branch},
            START_HEAD_TIMEOUT_S,
            None,
        )
    ]
    assert _stored_base(world, retried.summary.run_id) == START_HEAD


async def test_an_adopted_worktrees_start_head_on_a_real_host_is_the_base_its_outcome_diffs_from(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate_git_home(monkeypatch, tmp_path / "home")
    repo = tmp_path.resolve() / "repo"
    base = make_repository(repo)
    host_channel = InProcessHostChannel(host_id="host-1", handlers=workspace_op_handlers())
    channels = FakeChannels(host_channel, RecordingScopeRunner())
    built, pools = _build(world, writes=_writes(world, tmp_path), channels=channels)
    host = built.services.host
    host.root = str(repo)
    # A crashed start left the run's worktree on its branch, at the repository's head.
    branch = _branch(ALICE, "adopted")
    worktree = Path(host.path_of(branch))
    run_git(repo, "worktree", "add", "-q", "-b", branch, str(worktree))
    host.worktrees[branch] = str(worktree)
    definition = built.services.definitions.save(yaml_text=GATE_ONLY)
    body = _start_body(definition.id, "adopted", repo_path=str(repo))
    try:
        async with _client(built.app()) as client:
            started = await client.post(RUNS, headers=_as(ALICE), json=body)
            run_id = started.json()["run_id"]
            # The run's work lands on its branch, then its gate is approved to the end.
            (worktree / "NEW.md").write_bytes(b"new\n")
            run_git(worktree, "add", "-A")
            run_git(worktree, "commit", "-q", "-m", "the run's work")
            tip = run_git(worktree, "rev-parse", "HEAD").strip()
            world.bridge.answer_gate(
                workspace_id=WORKSPACE,
                run_id=run_id,
                token=APPROVE_TOKEN,
                label="approve",
                note="",
                actor=ALICE,
            )
            outcome = await client.get(f"{RUNS}/{run_id}/outcome", headers=_as(ALICE))
    finally:
        _close(built, pools)

    assert started.status_code == 201, started.text
    assert host.creates() == 0
    assert _stored_base(world, run_id) == base
    assert outcome.status_code == 200, outcome.text
    assert (outcome.json()["status"], outcome.json()["diff_unavailable"]) == ("completed", None)
    assert outcome.json()["diff"] == {
        "from_commit": base,
        "to_commit": tip,
        "files_changed": 1,
        "insertions": 1,
        "deletions": 0,
        "paths": ["NEW.md"],
        "paths_truncated": False,
    }


@pytest.mark.parametrize(
    ("reported", "stored", "reads"),
    [
        pytest.param(HEAD, HEAD, [], id="created-at-its-commit"),
        pytest.param(None, START_HEAD, ["head"], id="older-host-reports-none"),
        pytest.param("abc1234", START_HEAD, ["head"], id="short-commit-id"),
    ],
)
async def test_a_new_worktrees_base_is_the_commit_its_create_reported_or_else_its_head(
    start_heads: tuple[Api, FakeHostChannel, FakeChannels],
    reported: str | None,
    stored: str,
    reads: list[str],
) -> None:
    built, host_channel, channels = start_heads
    built.services.host.head_commit = reported
    definition = built.services.definitions.save()

    async with _client(built.app()) as client:
        response = await client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id))

    assert response.status_code == 201, response.text
    assert _stored_base(built.world, response.json()["run_id"]) == stored
    assert (host_channel.ops(), len(channels.calls)) == (reads, len(reads))


START_HEAD_FAILURES = [
    pytest.param(
        "channel",
        HostAccessRefused("not_permitted", f"{SECRET_PATH} is not yours"),
        "HostAccessRefused not_permitted",
        id="refused",
    ),
    pytest.param(
        "channel",
        HostAccessRefused("host_offline", f"no connection for {SECRET_PATH}"),
        "HostAccessRefused host_offline",
        id="host-offline",
    ),
    pytest.param(
        "head",
        WorkspaceOpError("workspace.git_failed", f"fatal: bad HEAD in {SECRET_PATH}"),
        "WorkspaceOpError workspace.git_failed",
        id="git-failed",
    ),
    pytest.param(
        "head",
        WorkspaceOpError("workspace.timeout", f"{SECRET_PATH} is busy"),
        "WorkspaceOpError workspace.timeout",
        id="worktree-busy",
    ),
    pytest.param(
        "head",
        host_capability_unavailable("host-1", SECRET_PATH),
        "WorkspaceOpError workspace.capability_unavailable",
        id="older-host-without-head",
    ),
    pytest.param("head", ValueError(SECRET_PATH), "ValueError ", id="refused-params"),
    pytest.param("head", RuntimeError(SECRET_PATH), "RuntimeError ", id="unexpected"),
    pytest.param(
        "head",
        {"head": SECRET_PATH, "branch": None, "merge_in_progress": False},
        "WorkspaceOpError workspace.backend_unavailable",
        id="malformed",
    ),
    pytest.param(
        "head",
        {"head": START_HEAD, "branch": "main", "merge_in_progress": False},
        "its worktree holds another branch",
        id="another-branch",
    ),
    pytest.param(
        "head",
        {"head": START_HEAD, "branch": None, "merge_in_progress": False},
        "its worktree holds another branch",
        id="detached",
    ),
]


@pytest.mark.parametrize(("where", "failure", "logged"), START_HEAD_FAILURES)
async def test_a_start_whose_head_cannot_be_read_starts_with_no_base_and_logs_no_path(
    start_heads: tuple[Api, FakeHostChannel, FakeChannels],
    caplog: pytest.LogCaptureFixture,
    where: str,
    failure: Any,
    logged: str,
) -> None:
    built, host_channel, channels = start_heads
    built.services.host.head_commit = None
    if where == "channel":
        channels.refusal = failure
    else:
        host_channel.replies["head"] = failure
    definition = built.services.definitions.save()

    with caplog.at_level(logging.DEBUG):
        async with _client(built.app()) as client:
            response = await client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id))

    assert response.status_code == 201, response.text
    run_id = response.json()["run_id"]
    assert _stored_base(built.world, run_id) is None
    assert _start_head_logs(caplog) == [
        f"Coral could not read run {run_id}'s start head: {logged}"
    ]
    assert all(record.exc_info is None for record in caplog.records)
    assert SECRET_PATH not in caplog.text


async def test_without_host_channels_a_start_whose_worktree_reported_no_commit_has_no_base(
    writes: Api, caplog: pytest.LogCaptureFixture
) -> None:
    writes.services.host.head_commit = None
    definition = writes.services.definitions.save()

    with caplog.at_level(logging.DEBUG):
        async with _client(writes.app()) as client:
            response = await client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id))

    assert response.status_code == 201, response.text
    assert _stored_base(writes.world, response.json()["run_id"]) is None
    assert _start_head_logs(caplog) == []


@pytest.mark.parametrize("stall", ["channel", "head"])
async def test_a_start_head_read_past_its_deadline_starts_with_no_base(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stall: str,
) -> None:
    monkeypatch.setattr(run_service, "START_HEAD_DEADLINE_S", 0.05)
    stalled: HostWorkspaceChannels = (
        HeldChannels(FakeHostChannel([], {}))
        if stall == "channel"
        else FakeChannels(StalledHost(), RecordingScopeRunner())
    )
    built, pools = _build(world, writes=_writes(world, tmp_path), channels=stalled)
    built.services.host.head_commit = None
    definition = built.services.definitions.save()
    try:
        with caplog.at_level(logging.DEBUG):
            async with _client(built.app()) as client:
                response = await asyncio.wait_for(
                    client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id)),
                    budget(10),
                )
    finally:
        _close(built, pools)

    assert response.status_code == 201, response.text
    run_id = response.json()["run_id"]
    assert _stored_base(world, run_id) is None
    assert _start_head_logs(caplog) == [
        f"Coral could not read run {run_id}'s start head: TimeoutError "
    ]
    assert built.api.starts.in_flight == 0


async def test_a_start_holds_no_pool_thread_and_stores_no_run_while_it_reads_the_head(
    world: World, tmp_path: Path
) -> None:
    host_channel, _channels = _outcome_host(START_HEAD)
    held = HeldChannels(host_channel)
    built, pools = _build(world, writes=_writes(world, tmp_path), channels=held)
    built.services.host.head_commit = None
    definition = built.services.definitions.save()
    try:
        async with _client(built.app()) as client:
            started = asyncio.create_task(
                client.post(RUNS, headers=_as(ALICE), json=_start_body(definition.id))
            )
            await poll_until_async(lambda: held.entered == 1, timeout_s=budget(10))
            during = (built.in_flight.in_flight, built.api.starts.in_flight, _count_runs(world))
            held.release.set()
            response = await started
    finally:
        _close(built, pools)

    assert during == (0, 1, 0)
    assert response.status_code == 201, response.text
    assert _stored_base(world, response.json()["run_id"]) == START_HEAD
    assert host_channel.ops() == ["head"]


# ── Pause, resume and cancel ────────────────────────────────────────────────


def _complete(world: World, key: str, user: str = ALICE, **spec: Any) -> CoralRun:
    """A gate run of ``user``'s, started with ``spec``'s fields and approved to its end."""
    world.clock.advance(1)
    run = start(world, GATE_ONLY, spec=run_spec(user=user, start_key=key, **spec), start_key=key)
    world.bridge.answer_gate(
        workspace_id=WORKSPACE,
        run_id=run.id,
        token=APPROVE_TOKEN,
        label="approve",
        note="",
        actor=ALICE,
    )
    return world.run(run.id)


def _run_in_state(world: World, state: str) -> CoralRun:
    """A run of Alice's in the named state."""
    if state == "completed":
        return _complete(world, state)
    if state.startswith("starting"):
        run = start_without_engine(world, start_key=state)
    else:
        run = _start(world, state)
    bridge = world.bridge
    if state in ("user_paused", "paused_unloadable"):
        bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor=ALICE)
    elif state == "budget_paused":
        bridge.commit_inputs(
            workspace_id=WORKSPACE,
            run_id=run.id,
            inputs=lambda _snapshot: (PauseRun(reason="budget", detail="activations"),),
        )
    elif state == "row_paused":
        _pause_on_row(world, run, RunPauseReason.DRIFT)
    elif state == "cancelled":
        bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor=ALICE)
    elif state == "failed":
        runs = _fake_runs(world)
        current = world.run(run.id)
        runs.runs[(WORKSPACE, run.id)] = dataclasses.replace(
            current, status=int(RunStatus.FAILED), finished_at=world.clock.epoch
        )
    if state.endswith("unloadable"):
        _config_missing(world, run)
    return world.run(run.id)


STATES = [
    "running",
    "user_paused",
    "budget_paused",
    "row_paused",
    "cancelled",
    "completed",
    "failed",
    "unloadable",
    "starting",
    "starting_unloadable",
    "paused_unloadable",
]
# (status, row status after) of each action on each state; ``None`` for a no-op.
OUTCOMES: dict[tuple[str, str], tuple[int, str]] = {
    ("running", "pause"): (200, "paused"),
    ("running", "resume"): (200, "running"),
    ("running", "cancel"): (200, "cancelled"),
    ("user_paused", "pause"): (200, "paused"),
    ("user_paused", "resume"): (200, "running"),
    ("user_paused", "cancel"): (200, "cancelled"),
    ("budget_paused", "pause"): (200, "paused"),
    ("budget_paused", "resume"): (409, "paused"),
    ("budget_paused", "cancel"): (200, "cancelled"),
    ("row_paused", "pause"): (200, "paused"),
    ("row_paused", "resume"): (200, "running"),
    ("row_paused", "cancel"): (200, "cancelled"),
    ("cancelled", "pause"): (409, "cancelled"),
    ("cancelled", "resume"): (409, "cancelled"),
    ("cancelled", "cancel"): (200, "cancelled"),
    ("completed", "pause"): (409, "completed"),
    ("completed", "resume"): (409, "completed"),
    ("completed", "cancel"): (409, "completed"),
    ("failed", "pause"): (409, "failed"),
    ("failed", "resume"): (409, "failed"),
    ("failed", "cancel"): (409, "failed"),
    # The failed load pauses the run, as any write does.
    ("unloadable", "pause"): (409, "paused"),
    ("unloadable", "resume"): (200, "running"),
    ("unloadable", "cancel"): (200, "cancelled"),
    # A crash left the run stored and its engine not started: a write starts it first.
    ("starting", "pause"): (200, "paused"),
    ("starting", "resume"): (200, "starting"),
    ("starting", "cancel"): (200, "cancelled"),
    ("starting_unloadable", "pause"): (409, "paused"),
    ("starting_unloadable", "resume"): (200, "starting"),
    ("starting_unloadable", "cancel"): (200, "cancelled"),
    ("paused_unloadable", "pause"): (200, "paused"),
    ("paused_unloadable", "resume"): (409, "paused"),
    ("paused_unloadable", "cancel"): (200, "cancelled"),
}
# Actions already in effect, or with nothing to do: 200 and no commit.
NO_OPS = {
    ("running", "resume"),
    ("user_paused", "pause"),
    ("budget_paused", "pause"),
    ("row_paused", "pause"),
    ("cancelled", "cancel"),
    ("unloadable", "resume"),
    ("starting", "resume"),
    ("starting_unloadable", "resume"),
    ("paused_unloadable", "pause"),
    ("paused_unloadable", "resume"),
}


@pytest.mark.parametrize("action", ["pause", "resume", "cancel"])
@pytest.mark.parametrize("state", STATES)
async def test_each_action_on_each_run_state(writes: Api, state: str, action: str) -> None:
    world = writes.world
    run = _run_in_state(world, state)
    before = _row_state(world, run.id)
    logs_before = len(_fake_runs(world).logs[(WORKSPACE, run.id)])

    async with _client(writes.app()) as client:
        offered = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        response = await client.post(f"{RUNS}/{run.id}:{action}", headers=_as(ALICE), json={})
        detail = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()

    status, row_after = OUTCOMES[(state, action)]
    after = _row_state(world, run.id)
    assert (response.status_code, after[0]) == (status, row_after), response.text
    if status == 200:
        # The answer is the run as its detail now shows it, actions included.
        assert response.json()["status"] == detail["status"] == row_after
        assert response.json()["allowed_actions"] == detail["allowed_actions"]
        assert response.json()["run_branch"] == detail["run_branch"] == run_branch_name(run.id)
    else:
        error = response.json()["error"]
        assert error["code"] == "illegal_transition"
        assert error["details"]["status"] == after[0]
    if (state, action) in NO_OPS:
        assert after == before
        assert len(_fake_runs(world).logs[(WORKSPACE, run.id)]) == logs_before
    # A route takes the action, changing the run, exactly when the run offered it.
    taken = status == 200 and after[:2] != before[:2]
    assert taken == (action in offered["allowed_actions"])


async def test_a_pause_of_a_run_that_cannot_load_says_so(writes: Api) -> None:
    run = _run_in_state(writes.world, "unloadable")

    async with _client(writes.app()) as client:
        response = await client.post(f"{RUNS}/{run.id}:pause", headers=_as(ALICE), json={})

    assert response.json()["error"]["details"] == {
        "status": "paused",
        "pause_reason": "failure_path",
        "reason": "engine.load_failed",
    }


async def test_a_pause_that_meets_a_cancel_on_the_row_is_refused(writes: Api) -> None:
    world = writes.world
    run = _start(world, "raced")
    # A store-only cancel lands just before the pause's commit, whose retry cancels the engine.
    before_next_commit(
        world,
        lambda: cancel_run_row(
            world.runs, workspace_id=WORKSPACE, run_id=run.id, actor=ALICE, now_us=1
        ),
    )

    async with _client(writes.app()) as client:
        response = await client.post(f"{RUNS}/{run.id}:pause", headers=_as(ALICE), json={})

    assert _refusal(response) == (409, "illegal_transition")
    assert response.json()["error"]["details"]["status"] == "cancelled"
    assert response.json()["error"]["details"]["reason"] == "run_terminal"


async def test_a_resume_that_clears_one_of_two_causes_succeeds_and_shows_the_other(
    writes: Api,
) -> None:
    world = writes.world
    run = _start(world, "two-causes")
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (
            PauseRun(reason="user", detail="user"),
            PauseRun(reason="budget", detail="activations"),
        ),
    )

    async with _client(writes.app()) as client:
        response = await client.post(f"{RUNS}/{run.id}:resume", headers=_as(ALICE), json={})

    # The resume was taken; the run stays paused for the cause it cannot clear.
    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["pause_reason"]) == ("paused", "budget")
    assert response.json()["allowed_actions"] == ["cancel"]


async def test_a_resume_with_a_higher_cap_clears_a_budget_pause(writes: Api) -> None:
    run = _run_in_state(writes.world, "budget_paused")

    async with _client(writes.app()) as client:
        refused = await client.post(f"{RUNS}/{run.id}:resume", headers=_as(ALICE), json={})
        too_high = await client.post(
            f"{RUNS}/{run.id}:resume", headers=_as(ALICE), json={"cap": 1001}
        )
        resumed = await client.post(
            f"{RUNS}/{run.id}:resume", headers=_as(ALICE), json={"cap": 200}
        )

    assert _refusal(refused) == (409, "illegal_transition")
    assert refused.json()["error"]["details"]["reason"] == "resume_not_allowed"
    assert _refusal(too_high) == (422, "validation_failed")
    assert (resumed.status_code, resumed.json()["status"]) == (200, "running")


@pytest.mark.parametrize("broken", ["config_missing", "spec_missing", "unknown_codec"])
async def test_a_cancel_of_a_run_that_cannot_load_ends_it_on_its_row_and_withdraws_its_prompt(
    writes: Api, broken: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, publisher = writes.world, writes.services.publisher
    world.clock.advance(1)
    run = start(world, GATE_ONLY, spec=run_spec(user=ALICE, start_key="gate"), start_key="gate")
    anchor, prompt = _anchor_prompt(world, run)
    publisher.pending[(anchor, prompt)] = {}
    if broken == "config_missing":
        _config_missing(world, run)
    else:
        load = world.runs.load_run_state
        error = (
            RunNotFound(f"RunSpec for run {run.id!r} not found")
            if broken == "spec_missing"
            else ValueError("Unknown compression codec")
        )

        def rows_failing(run_id: str, **options: Any) -> Any:
            if run_id == run.id:
                raise error
            return load(run_id, **options)

        monkeypatch.setattr(world.runs, "load_run_state", rows_failing)

    async with _client(writes.app()) as client:
        response = await client.post(f"{RUNS}/{run.id}:cancel", headers=_as(ALICE), json={})

    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["allowed_actions"]) == ("cancelled", [])
    finished = [
        json.loads(row.body)
        for row in _fake_runs(world).logs[(WORKSPACE, run.id)]
        if row.kind == int(LogKind.RUN_FINISHED)
    ]
    assert [body["store_only"] for body in finished] == [True]
    if broken != "spec_missing":
        # Its gate row closed, and this process's prompt went with it.
        assert ("withdraw", anchor, prompt) in publisher.calls
        assert publisher.pending == {}


async def test_an_action_without_a_json_object_body_is_refused(writes: Api) -> None:
    run = _start(writes.world, "bodies")

    async with _client(writes.app()) as client:
        missing = await client.post(
            f"{RUNS}/{run.id}:pause",
            headers={**_as(ALICE), "content-type": "application/json"},
        )
        extra = await client.post(
            f"{RUNS}/{run.id}:cancel", headers=_as(ALICE), json={"force": True}
        )
        not_json = await client.post(
            f"{RUNS}/{run.id}:cancel",
            headers={**_as(ALICE), "content-type": "text/plain"},
            content=b"{}",
        )

    assert [_refusal(response) for response in (missing, extra, not_json)] == [
        (422, "validation_failed")
    ] * 3
    assert _row_state(writes.world, run.id)[0] == "running"


async def test_an_unexpected_write_error_is_logged_without_its_parameters_or_cause(
    writes: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    run = _start(writes.world, "fault")
    marker = "statement-parameter-5e1d"

    def failing(**_kwargs: Any) -> None:
        raise StatementError("write failed", "UPDATE coral_runs", {"secret": marker}, OSError())

    monkeypatch.setattr(writes.world.bridge, "pause_run", failing)

    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as caught:
        await writes.api.pause(Viewer(user_id=ALICE), WORKSPACE, run.id)

    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert marker not in caplog.text
    assert "StatementError" in caplog.text


# ── Retry and preflight ─────────────────────────────────────────────────────


def _retry_url(run_id: str, activation_id: str) -> str:
    return f"{RUNS}/{run_id}/activations/{activation_id}:retry"


def _step_id(run: CoralRun, slot_id: str = IMPLEMENT) -> str:
    """The store activation id of the step ``slot_id`` works for."""
    return store_activation_id(run.id, slot_id.rsplit(":", 1)[0])


def _commit(world: World, run_id: str, *inputs: Input) -> None:
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: inputs
    )


def _blocked_run(world: World, key: str) -> CoralRun:
    """A two-step run of Alice's whose implementer handed off blocked: it pauses for a retry."""
    run = _start(world, key)
    brief(world, run.id, IMPLEMENT)
    _commit(world, run.id, *blocked(IMPLEMENT))
    return world.run(run.id)


def _retry_case(world: World, case: str) -> tuple[CoralRun, str]:
    """Alice's run in the named case, and the activation id a retry of it names."""
    if case == "completed":
        run = _complete(world, case)
        return run, store_activation_id(run.id, "approve||")
    if case == "not_started":
        run = start_without_engine(world, start_key=case)
        return run, _step_id(run)
    if case == "unknown":
        return _blocked_run(world, case), "a" * 32
    if case == "another_run":
        run, other = _blocked_run(world, case), _blocked_run(world, "other")
        return run, _step_id(other)
    if case == "gate":
        run = _gate_run(world, case)
        world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor=ALICE)
        return world.run(run.id), store_activation_id(run.id, "approve||")
    run = _start(world, case)
    session_id = brief(world, run.id, IMPLEMENT)
    if case == "held":
        _commit(world, run.id, RunnerHeld(slot_id=IMPLEMENT, session_id=session_id, generation=1))
    elif case == "cancelled":
        world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor=ALICE)
    elif case == "unloadable":
        _config_missing(world, run)
    return world.run(run.id), _step_id(run)


@dataclass(frozen=True)
class RetryRefusal:
    """
    What a retry the run cannot take answers: its reason (none for a finished run), its
    message, and the row's status and pause reason after it.
    """

    reason: str | None
    message: str
    status: str
    pause_reason: str | None = None


NO_SUCH_STEP = "The run has no such step."
NOT_RETRYABLE = "This step cannot be retried now."
RETRY_REFUSALS: dict[str, RetryRefusal] = {
    "completed": RetryRefusal(None, "The run is completed.", "completed"),
    "cancelled": RetryRefusal(None, "The run is cancelled.", "cancelled"),
    # The failed load pauses the run, as any write does.
    "unloadable": RetryRefusal(
        "engine.load_failed",
        "The run cannot be loaded; it can only be cancelled.",
        "paused",
        "failure_path",
    ),
    "unknown": RetryRefusal("unknown_activation", NO_SUCH_STEP, "paused", "failure_path"),
    # An activation of another of the caller's runs is not one of this run's.
    "another_run": RetryRefusal("unknown_activation", NO_SUCH_STEP, "paused", "failure_path"),
    "not_started": RetryRefusal("unknown_activation", NO_SUCH_STEP, "starting"),
    "running": RetryRefusal("retry_not_allowed", NOT_RETRYABLE, "running"),
    "gate": RetryRefusal("retry_not_allowed", NOT_RETRYABLE, "paused", "user"),
    "held": RetryRefusal(
        "host_offline_hold",
        "The run's machine is offline; steps can be retried once it is back.",
        "paused",
        "infra",
    ),
}


async def test_the_owner_retries_a_blocked_step_and_the_run_stays_paused_while_it_restarts(
    writes: Api, caplog: pytest.LogCaptureFixture
) -> None:
    world = writes.world
    run = _blocked_run(world, "blocked")
    activation = _step_id(run)

    async with _client(writes.app()) as client:
        before = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        with caplog.at_level(logging.DEBUG):
            retried = await client.post(
                _retry_url(run.id, activation), headers=_as(ALICE), json={}
            )
            again = await client.post(_retry_url(run.id, activation), headers=_as(ALICE), json={})
        after = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        [listed] = (await client.get(RUNS, headers=_as(ALICE))).json()["data"]

    # Blocked, the step is what the run can retry; Resume does not clear it.
    assert (before["status"], before["pause_reason"]) == ("paused", "failure_path")
    assert (before["retry_activation_ids"], before["allowed_actions"]) == (
        [activation],
        ["cancel"],
    )
    # Taken: the run stays paused while the old session is fenced and its work saved.
    assert retried.status_code == 200, retried.text
    assert retried.headers["cache-control"] == "private, no-store"
    summary = retried.json()
    assert (summary["run_id"], summary["status"], summary["pause_reason"]) == (
        run.id,
        "paused",
        "infra",
    )
    assert summary["allowed_actions"] == after["allowed_actions"] == ["cancel"]
    assert after["causes"] == [
        {"reason": "infra", "detail": "recovery.restarting", "subject": IMPLEMENT}
    ]
    assert after["retry_activation_ids"] == []
    assert [slot["session_generation"] for slot in after["slots"]] == [2]
    (restart,) = [
        item for item in world.work(run.id) if payload(item)["effect_type"] == RECOVERY_RESTART
    ]
    assert (restart.status, restart.slot_generation) == (int(WorkStatus.PENDING), 2)
    # Until it is done, a second retry is refused and the list offers Cancel only.
    assert _refusal(again) == (409, "illegal_transition")
    assert again.json()["error"] == {
        "code": "illegal_transition",
        "message": "A step of this run is restarting; try again when it is done.",
        "details": {"status": "paused", "pause_reason": "infra", "reason": "restart_in_progress"},
    }
    assert again.headers["cache-control"] == "private, no-store"
    assert listed["allowed_actions"] == ["cancel"]
    # The id is matched, never echoed or logged.
    assert activation not in retried.text + again.text + caplog.text


async def test_the_detail_names_only_the_failed_step_and_a_completed_one_is_not_retried(
    writes: Api,
) -> None:
    world = writes.world
    run = _start(world, "review")
    brief(world, run.id, IMPLEMENT)
    _commit(world, run.id, *accept(IMPLEMENT, "Implemented."))
    complete(world, run.id, "close_slot", IMPLEMENT, {})
    brief(world, run.id, REVIEW)
    _commit(world, run.id, *blocked(REVIEW))
    implement, review = _step_id(run, IMPLEMENT), _step_id(run, REVIEW)

    async with _client(writes.app()) as client:
        before = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        done = await client.post(_retry_url(run.id, implement), headers=_as(ALICE), json={})
        retried = await client.post(_retry_url(run.id, review), headers=_as(ALICE), json={})

    assert before["retry_activation_ids"] == [review]
    assert _refusal(done) == (409, "illegal_transition")
    assert done.json()["error"]["details"]["reason"] == "retry_not_allowed"
    assert retried.status_code == 200, retried.text
    review_slot = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id).state.slots[-1]
    assert (review_slot.id, review_slot.session_generation) == (REVIEW, 2)


@pytest.mark.parametrize("case", list(RETRY_REFUSALS))
async def test_a_retry_the_run_cannot_take_is_refused_with_its_reason(
    writes: Api, case: str
) -> None:
    world = writes.world
    run, activation = _retry_case(world, case)
    before = _row_state(world, run.id)
    logs_before = len(_fake_runs(world).logs[(WORKSPACE, run.id)])

    async with _client(writes.app()) as client:
        offered = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        response = await client.post(_retry_url(run.id, activation), headers=_as(ALICE), json={})

    expected = RETRY_REFUSALS[case]
    assert _refusal(response) == (409, "illegal_transition"), response.text
    assert response.headers["cache-control"] == "private, no-store"
    error = response.json()["error"]
    assert error["message"] == expected.message
    details = {"status": expected.status, "pause_reason": expected.pause_reason}
    assert error["details"] == (
        details if expected.reason is None else {**details, "reason": expected.reason}
    )
    assert _row_state(world, run.id)[:2] == (expected.status, expected.pause_reason)
    # A refusal commits nothing; only the failed load paused the run.
    if case != "unloadable":
        assert _row_state(world, run.id) == before
        assert len(_fake_runs(world).logs[(WORKSPACE, run.id)]) == logs_before
    # A step the detail does not name is never retried; a run running or held names none.
    assert activation not in offered["retry_activation_ids"]
    if case in ("running", "held"):
        assert offered["retry_activation_ids"] == []
    assert activation not in response.text


async def test_a_retry_naming_a_malformed_activation_is_refused_before_any_work(
    writes: Api,
) -> None:
    run = _start(writes.world, "retry")
    writes.calls.clear()

    async with _client(writes.app()) as client:
        malformed = await client.post(
            _retry_url(run.id, "not-an-activation"), headers=_as(ALICE), json={}
        )
        upper_case = await client.post(_retry_url(run.id, "A" * 32), headers=_as(ALICE), json={})

    assert _refusal(malformed) == _refusal(upper_case) == (422, "validation_failed")
    assert "not-an-" not in malformed.text
    assert "A" * 32 not in upper_case.text
    assert writes.calls == []


def _run_retry_url(run_id: str) -> str:
    return f"{RUNS}/{run_id}:retry"


ANCHOR_LOST = PauseRun(reason="failure_path", detail="anchor:dispatch.failed")
RUN_NOT_RETRYABLE = "This run cannot be retried now."


async def test_a_run_retry_clears_its_run_level_failure(writes: Api) -> None:
    world = writes.world
    run = _start(world, "anchor_lost")
    _commit(world, run.id, ANCHOR_LOST)

    async with _client(writes.app()) as client:
        before = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        [listed] = (await client.get(RUNS, headers=_as(ALICE))).json()["data"]
        bobs = await client.post(_run_retry_url(run.id), headers=_as(BOB), json={})
        retried = await client.post(_run_retry_url(run.id), headers=_as(ALICE), json={})
        again = await client.post(_run_retry_url(run.id), headers=_as(ALICE), json={})

    # Offered on the detail only; Resume never clears a failure_path cause.
    assert (before["pause_reason"], before["allowed_actions"]) == (
        "failure_path",
        ["retry", "cancel"],
    )
    assert listed["allowed_actions"] == ["cancel"]
    assert bobs.status_code == 404
    assert retried.status_code == 200, retried.text
    assert retried.headers["cache-control"] == "private, no-store"
    assert (retried.json()["status"], retried.json()["allowed_actions"]) == (
        "running",
        ["pause", "cancel"],
    )
    assert _refusal(again) == (409, "illegal_transition")
    assert again.json()["error"] == {
        "code": "illegal_transition",
        "message": RUN_NOT_RETRYABLE,
        "details": {"status": "running", "pause_reason": None, "reason": "retry_not_allowed"},
    }
    assert again.headers["cache-control"] == "private, no-store"


RUN_RETRY_REFUSALS: dict[str, RetryRefusal] = {
    "completed": RetryRefusal(None, "The run is completed.", "completed"),
    "cancelled": RetryRefusal(None, "The run is cancelled.", "cancelled"),
    "unloadable": RETRY_REFUSALS["unloadable"],
    "running": RetryRefusal("retry_not_allowed", RUN_NOT_RETRYABLE, "running"),
    "user_paused": RetryRefusal("retry_not_allowed", RUN_NOT_RETRYABLE, "paused", "user"),
    "held": RETRY_REFUSALS["held"],
}


@pytest.mark.parametrize("case", list(RUN_RETRY_REFUSALS))
async def test_a_run_retry_the_run_cannot_take_is_refused_with_its_reason(
    writes: Api, case: str
) -> None:
    world = writes.world
    if case == "held":
        run, _activation = _retry_case(world, case)
        _commit(world, run.id, ANCHOR_LOST)
    else:
        run = _run_in_state(world, case)
    before = _row_state(world, run.id)
    logs_before = len(_fake_runs(world).logs[(WORKSPACE, run.id)])

    async with _client(writes.app()) as client:
        offered = (await client.get(f"{RUNS}/{run.id}", headers=_as(ALICE))).json()
        response = await client.post(_run_retry_url(run.id), headers=_as(ALICE), json={})

    expected = RUN_RETRY_REFUSALS[case]
    assert "retry" not in offered["allowed_actions"]
    assert _refusal(response) == (409, "illegal_transition"), response.text
    assert response.headers["cache-control"] == "private, no-store"
    error = response.json()["error"]
    assert error["message"] == expected.message
    details = {"status": expected.status, "pause_reason": expected.pause_reason}
    assert error["details"] == (
        details if expected.reason is None else {**details, "reason": expected.reason}
    )
    if case != "unloadable":
        assert _row_state(world, run.id) == before
        assert len(_fake_runs(world).logs[(WORKSPACE, run.id)]) == logs_before


# ── Retry under races, loops, generations and holds ─────────────────────────

PLAN, BUILD, DOCS = "plan||:0", "build||:0", "docs||:0"
# A plan, then two steps side by side, so two steps can fail in one run.
FAN_OUT = workflow_text(
    [start_node(), step("plan"), step("build"), step("docs", roster=["reviewer"]), end_node()],
    [
        arrow("a1", "start", "plan"),
        arrow("a2", "plan", "build"),
        arrow("a3", "plan", "docs"),
        arrow("a4", "build", "end"),
        arrow("a5", "docs", "end"),
    ],
)
# A step beside a gate, so the gate is open while the step fails and is retried.
STEP_BESIDE_GATE = workflow_text(
    [
        start_node(),
        step("build"),
        gate_node("approve", prompt="Ship it?", outcomes=["approve"]),
        step("finish", roster=["reviewer"]),
        end_node(),
    ],
    [
        arrow("a1", "start", "build"),
        arrow("a2", "start", "approve"),
        arrow("a3", "build", "finish"),
        arrow("a4", "approve", "finish", label="approve"),
        arrow("a5", "finish", "end"),
    ],
)
RESTARTED = {"salvage_ref": None, "salvage_commit": None, "head_verified": True}
RESTARTING = {"reason": "infra", "detail": "recovery.restarting"}


def _start_text(world: World, key: str, yaml_text: str) -> CoralRun:
    world.clock.advance(1)
    return start(world, yaml_text, spec=run_spec(user=ALICE, start_key=key), start_key=key)


def _restarts(world: World, run_id: str) -> list[WorkItem]:
    """The run's ``recovery.restart`` rows, oldest generation first."""
    rows = [
        item for item in world.work(run_id) if payload(item)["effect_type"] == RECOVERY_RESTART
    ]
    return sorted(rows, key=lambda item: (item.slot_generation or 0, item.available_at))


def _fail(world: World, run_id: str, kind: str, subject: str, error_code: str) -> None:
    """Fail the latest ``kind`` effect about ``subject`` for good, as a drainer would."""
    (effect, *_older) = reversed(
        [effect for effect in effects(world, run_id, kind) if effect.subject == subject]
    )
    item = work_for(world, run_id, effect.effect_key)
    assert item is not None
    world.bridge.feed(finished(settle(world, item, WorkStatus.FAILED, error_code=error_code)))


async def _detail(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    response = await client.get(f"{RUNS}/{run_id}", headers=_as(ALICE))
    assert response.status_code == 200, response.text
    detail: dict[str, Any] = response.json()
    # Every id the detail offers names one of its slots, so a page can label its button.
    labelled = {slot["activation_id"] for slot in detail["slots"]}
    assert set(detail["retry_activation_ids"]) <= labelled
    return detail


async def _retry_as_offered(
    client: httpx.AsyncClient, run_id: str, activation: str
) -> tuple[dict[str, Any], httpx.Response]:
    """The detail just before, and the retry: the route takes exactly what the detail offers."""
    offered = await _detail(client, run_id)
    response = await client.post(_retry_url(run_id, activation), headers=_as(ALICE), json={})
    taken = response.status_code == 200
    assert taken == (activation in offered["retry_activation_ids"]), (offered, response.text)
    if not taken:
        assert _refusal(response) == (409, "illegal_transition"), response.text
    return offered, response


def _reason(response: httpx.Response) -> str | None:
    details: dict[str, Any] = response.json()["error"]["details"]
    return details.get("reason")


@pytest.mark.parametrize("race", ["together", "interleaved"])
async def test_two_retries_of_one_step_at_once_queue_one_restart(writes: Api, race: str) -> None:
    world = writes.world
    run = _blocked_run(world, "twice")
    activation = _step_id(run)
    url = _retry_url(run.id, activation)

    async with _client(writes.app()) as client:
        if race == "together":
            answers = list(
                await asyncio.gather(
                    client.post(url, headers=_as(ALICE), json={}),
                    client.post(url, headers=_as(ALICE), json={}),
                )
            )
        else:
            # Another replica's retry lands just before this one's commit.
            before_next_commit(
                world,
                lambda: world.bridge.retry_activation(
                    workspace_id=WORKSPACE, run_id=run.id, actor=ALICE, activation_id=activation
                ),
            )
            answers = [await client.post(url, headers=_as(ALICE), json={})]
        after = await _detail(client, run.id)

    taken = [response for response in answers if response.status_code == 200]
    refused = [response for response in answers if response.status_code != 200]
    assert len(taken) == (1 if race == "together" else 0)
    (refusal,) = refused
    assert _refusal(refusal) == (409, "illegal_transition"), refusal.text
    assert _reason(refusal) == "restart_in_progress"
    (restart,) = _restarts(world, run.id)
    assert (restart.status, restart.slot_generation) == (int(WorkStatus.PENDING), 2)
    assert len(effects(world, run.id, "retry_step")) == 1
    state = world.assert_fold_matches(run.id)
    assert [slot.session_generation for slot in state.slots] == [2]
    assert after["causes"] == [{**RESTARTING, "subject": IMPLEMENT}]
    assert after["retry_activation_ids"] == []


@pytest.mark.parametrize("cancel", ["engine", "row"])
async def test_a_retry_that_meets_a_cancel_is_refused_and_queues_no_restart(
    writes: Api, cancel: str
) -> None:
    world = writes.world
    run = _blocked_run(world, "raced")
    activation = _step_id(run)

    def cancelled() -> object:
        if cancel == "engine":
            return world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor=ALICE)
        # A cancel on the row alone; the retry's commit cancels the engine first.
        return cancel_run_row(
            world.runs, workspace_id=WORKSPACE, run_id=run.id, actor=ALICE, now_us=1
        )

    async with _client(writes.app()) as client:
        offered = await _detail(client, run.id)
        before_next_commit(world, cancelled)
        response = await client.post(_retry_url(run.id, activation), headers=_as(ALICE), json={})
        after = await _detail(client, run.id)

    assert offered["retry_activation_ids"] == [activation]
    assert _refusal(response) == (409, "illegal_transition"), response.text
    assert response.json()["error"]["message"] == "The run is cancelled."
    assert _reason(response) == "run_terminal"
    assert _restarts(world, run.id) == []
    assert effects(world, run.id, "retry_step") == []
    assert world.assert_fold_matches(run.id).status == "cancelled"
    assert (after["status"], after["retry_activation_ids"], after["allowed_actions"]) == (
        "cancelled",
        [],
        [],
    )


@pytest.mark.parametrize("ended", ["cancelled", "completed", "failed", "failed_while_blocked"])
async def test_a_retry_after_the_run_ended_is_refused_before_the_engine_is_asked(
    writes: Api, ended: str
) -> None:
    world = writes.world
    if ended == "failed_while_blocked":
        # The row failed while its engine still holds a step a retry would restart.
        run = _blocked_run(world, ended)
        runs = _fake_runs(world)
        runs.runs[(WORKSPACE, run.id)] = dataclasses.replace(
            run, status=int(RunStatus.FAILED), finished_at=world.clock.epoch
        )
        state = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id).state
        assert retryable_activations(state) == ("implement||",)
        ended = "failed"
    else:
        run = _run_in_state(world, ended)
    activation = (
        store_activation_id(run.id, "approve||") if ended == "completed" else _step_id(run)
    )
    writes.calls.clear()

    async with _client(writes.app()) as client:
        offered, response = await _retry_as_offered(client, run.id, activation)

    assert offered["retry_activation_ids"] == offered["allowed_actions"] == []
    assert response.json()["error"]["message"] == f"The run is {ended}."
    assert _reason(response) is None
    assert "bridge.retry_activation" not in writes.calls


async def test_only_the_newest_loop_pass_of_a_blocked_step_is_retried(writes: Api) -> None:
    world = writes.world
    run = _start_text(world, "loop", GATED)
    hand_off(world, run.id, IMPLEMENT_FIRST)
    answer(world, run.id, CHANGE_TOKEN, "reject", note="Again.")
    brief(world, run.id, IMPLEMENT_AGAIN)
    _commit(world, run.id, *blocked(IMPLEMENT_AGAIN))
    state = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id).state
    newest = _step_id(run, IMPLEMENT_AGAIN)
    others = [
        store_activation_id(run.id, activation.id)
        for activation in state.activations
        if store_activation_id(run.id, activation.id) != newest
    ]

    async with _client(writes.app()) as client:
        refused = [await _retry_as_offered(client, run.id, other) for other in others]
        offered, taken = await _retry_as_offered(client, run.id, newest)

    # The first pass, its gate visit, and the start: none is a failed step of this pass.
    assert _step_id(run, IMPLEMENT_FIRST) in others and len(others) >= 3
    assert [_reason(response) for _offered, response in refused] == ["retry_not_allowed"] * len(
        others
    )
    assert offered["retry_activation_ids"] == [newest]
    assert taken.status_code == 200, taken.text
    slots = {slot.id: slot.session_generation for slot in world.assert_fold_matches(run.id).slots}
    assert (slots[IMPLEMENT_FIRST], slots[IMPLEMENT_AGAIN]) == (1, 2)


@pytest.mark.parametrize(
    "ended", ["restarted_then_blocked", "restart_failed", "restart_abandoned"]
)
async def test_a_step_retried_before_is_retried_again_and_fences_its_latest_session(
    writes: Api, ended: str
) -> None:
    world = writes.world
    run = _start(world, ended)
    first_session = brief(world, run.id, IMPLEMENT)
    _commit(world, run.id, *blocked(IMPLEMENT))
    activation = _step_id(run)
    retried = world.bridge.retry_activation(
        workspace_id=WORKSPACE, run_id=run.id, actor=ALICE, activation_id=activation
    )
    assert retried.outcome == "retried", retried
    if ended == "restarted_then_blocked":
        complete(world, run.id, "retry_step", IMPLEMENT, RESTARTED)
        fenced = brief(world, run.id, IMPLEMENT)
        _commit(world, run.id, *blocked(IMPLEMENT, session_generation=2))
    elif ended == "restart_failed":
        _fail(world, run.id, "retry_step", IMPLEMENT, "workspace.head_moved")
        fenced = first_session
    else:
        # A drainer gave the restart row up; the resync feeds that as the restart's failure.
        (row,) = _restarts(world, run.id)
        settle(world, row, WorkStatus.ABANDONED, error_code="effect.abandoned")
        world.bridge.resync_run(workspace_id=WORKSPACE, run_id=run.id)
        fenced = first_session

    async with _client(writes.app()) as client:
        offered, response = await _retry_as_offered(client, run.id, activation)
        after = await _detail(client, run.id)

    assert offered["retry_activation_ids"] == [activation]
    assert offered["allowed_actions"] == ["cancel"]
    assert response.status_code == 200, response.text
    assert after["causes"] == [{**RESTARTING, "subject": IMPLEMENT}]
    assert [slot["session_generation"] for slot in after["slots"]] == [3]
    restarts = _restarts(world, run.id)
    assert [item.slot_generation for item in restarts] == [2, 3]
    # A restart that created nothing leaves the first session the one to fence.
    assert payload(restarts[-1])["session_id"] == fenced
    assert (fenced == first_session) == (ended != "restarted_then_blocked")


async def test_two_failed_steps_are_retried_one_restart_at_a_time(writes: Api) -> None:
    world = writes.world
    run = _start_text(world, "two-failed", FAN_OUT)
    brief(world, run.id, PLAN)
    _commit(world, run.id, *accept(PLAN, "Planned."))
    complete(world, run.id, "close_slot", PLAN, {})
    brief(world, run.id, BUILD)
    _commit(world, run.id, *blocked(BUILD))
    # The paused run's other step cannot start: its session is never created.
    _fail(world, run.id, "create_session", DOCS, "session.create_failed")
    build, docs = _step_id(run, BUILD), _step_id(run, DOCS)

    async with _client(writes.app()) as client:
        both, first = await _retry_as_offered(client, run.id, build)
        during, waiting = await _retry_as_offered(client, run.id, docs)
        complete(world, run.id, "retry_step", BUILD, RESTARTED)
        between, again = await _retry_as_offered(client, run.id, build)
        _offered, second = await _retry_as_offered(client, run.id, docs)
        after = await _detail(client, run.id)

    assert both["retry_activation_ids"] == [build, docs]
    assert first.status_code == 200, first.text
    # While one step restarts, the other's failure stands but no retry is offered or taken.
    assert {(cause["detail"], cause["subject"]) for cause in during["causes"]} == {
        ("recovery.restarting", BUILD),
        ("session.create_failed", DOCS),
    }
    assert during["retry_activation_ids"] == []
    assert _reason(waiting) == "restart_in_progress"
    # Once it has restarted, only the other step is offered.
    assert between["retry_activation_ids"] == [docs]
    assert _reason(again) == "retry_not_allowed"
    assert second.status_code == 200, second.text
    assert after["causes"] == [{**RESTARTING, "subject": DOCS}]
    slots = {slot.id: slot.session_generation for slot in world.assert_fold_matches(run.id).slots}
    assert (slots[BUILD], slots[DOCS]) == (2, 2)
    assert sorted(payload(item)["engine_slot_id"] for item in _restarts(world, run.id)) == [
        BUILD,
        DOCS,
    ]


async def test_a_step_beside_an_open_gate_is_retried_and_the_gate_stays_open(
    writes: Api,
) -> None:
    world = writes.world
    run = _start_text(world, "beside", STEP_BESIDE_GATE)
    brief(world, run.id, BUILD)
    _commit(world, run.id, *blocked(BUILD))
    (visit,) = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id).state.gates
    gate_activation = store_activation_id(run.id, visit.activation_id)

    async with _client(writes.app()) as client:
        refused_offer, refused = await _retry_as_offered(client, run.id, gate_activation)
        offered, taken = await _retry_as_offered(client, run.id, _step_id(run, BUILD))
        after = await _detail(client, run.id)

    assert visit.status == "open"
    assert offered["retry_activation_ids"] == [_step_id(run, BUILD)]
    assert _reason(refused) == "retry_not_allowed"
    assert taken.status_code == 200, taken.text
    # The open visit is untouched: same token, still waiting for its answer.
    assert [gate["token"] for gate in after["gates"]] == [visit.token]
    assert after["gates"] == refused_offer["gates"]
    (still,) = world.assert_fold_matches(run.id).gates
    assert (still.token, still.status) == (visit.token, "open")


async def test_a_host_hold_on_one_step_keeps_another_failed_step_from_its_retry(
    writes: Api,
) -> None:
    world = writes.world
    run = _start_text(world, "held-beside", FAN_OUT)
    brief(world, run.id, PLAN)
    _commit(world, run.id, *accept(PLAN, "Planned."))
    complete(world, run.id, "close_slot", PLAN, {})
    held_session = brief(world, run.id, BUILD)
    _commit(world, run.id, RunnerHeld(slot_id=BUILD, session_id=held_session, generation=1))
    _fail(world, run.id, "create_session", DOCS, "session.create_failed")
    build, docs = _step_id(run, BUILD), _step_id(run, DOCS)

    async with _client(writes.app()) as client:
        held_offer, held_docs = await _retry_as_offered(client, run.id, docs)
        _offered, held_build = await _retry_as_offered(client, run.id, build)
        listed_held = (await client.get(RUNS, headers=_as(ALICE))).json()["data"]
        _commit(world, run.id, RunnerHoldEnded(slot_id=BUILD, generation=1))
        _back, not_failed = await _retry_as_offered(client, run.id, build)
        back_offer, taken = await _retry_as_offered(client, run.id, docs)

    assert held_offer["retry_activation_ids"] == []
    assert held_offer["allowed_actions"] == ["cancel"]
    assert [item["allowed_actions"] for item in listed_held] == [["cancel"]]
    assert _reason(held_docs) == _reason(held_build) == "host_offline_hold"
    # Back online, the held step was never failed; the other is retried.
    assert back_offer["retry_activation_ids"] == [docs]
    assert _reason(not_failed) == "retry_not_allowed"
    assert taken.status_code == 200, taken.text


async def test_a_step_whose_wake_found_its_session_closed_is_offered_and_retried(
    writes: Api,
) -> None:
    world = writes.world
    run = _start(world, "closed")
    session_id = brief(world, run.id, IMPLEMENT)
    _commit(
        world,
        run.id,
        RunnerLost(slot_id=IMPLEMENT, session_id=session_id, generation=1, runner_id="r1"),
    )
    (wake,) = [
        item for item in world.work(run.id) if payload(item)["effect_type"] == RECOVERY_WAKE
    ]
    # The wake found the step's session closed, so it fails for good.
    closed = settle(world, wake, WorkStatus.FAILED, error_code="session.closed")
    world.bridge.feed(finished(closed))
    activation = _step_id(run)

    async with _client(writes.app()) as client:
        offered, response = await _retry_as_offered(client, run.id, activation)
        after = await _detail(client, run.id)

    assert offered["causes"] == [
        {"reason": "failure_path", "detail": "session.closed", "subject": IMPLEMENT}
    ]
    assert (offered["retry_activation_ids"], offered["allowed_actions"]) == (
        [activation],
        ["cancel"],
    )
    assert response.status_code == 200, response.text
    assert after["causes"] == [{**RESTARTING, "subject": IMPLEMENT}]
    (restart,) = _restarts(world, run.id)
    assert (restart.slot_generation, payload(restart)["session_id"]) == (2, session_id)


@pytest.mark.parametrize(
    ("case", "listed", "offered"),
    [
        pytest.param("host_offline", ["cancel"], ["cancel"], id="held"),
        pytest.param("restarting", ["cancel"], ["cancel"], id="restarting"),
        # Resume clears an infra pause no step holds, but the list cannot tell it apart.
        pytest.param("infra", ["cancel"], ["resume", "cancel"], id="infra"),
        pytest.param("user", ["resume", "cancel"], ["resume", "cancel"], id="user"),
        pytest.param("blocked", ["cancel"], ["cancel"], id="blocked"),
    ],
)
async def test_a_list_item_paused_infra_offers_cancel_only_and_other_pauses_are_unchanged(
    writes: Api, case: str, listed: list[str], offered: list[str]
) -> None:
    world = writes.world
    run = _start(world, case)
    session_id = brief(world, run.id, IMPLEMENT)
    if case == "host_offline":
        _commit(world, run.id, RunnerHeld(slot_id=IMPLEMENT, session_id=session_id, generation=1))
    elif case == "infra":
        _commit(world, run.id, PauseRun(reason="infra", detail="infra.transient"))
    elif case == "user":
        world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor=ALICE)
    else:
        _commit(world, run.id, *blocked(IMPLEMENT))
        if case == "restarting":
            world.bridge.retry_activation(
                workspace_id=WORKSPACE, run_id=run.id, actor=ALICE, activation_id=_step_id(run)
            )

    async with _client(writes.app()) as client:
        detail = await _detail(client, run.id)
        [item] = (await client.get(RUNS, headers=_as(ALICE))).json()["data"]

    reason = {"user": "user", "blocked": "failure_path"}.get(case, "infra")
    assert (item["status"], item["pause_reason"]) == ("paused", reason)
    assert item["allowed_actions"] == listed
    assert detail["allowed_actions"] == offered


@pytest.mark.parametrize(
    "activation",
    [
        pytest.param("a" * 31, id="short"),
        pytest.param("a" * 33, id="long"),
        pytest.param("a" * 20_000, id="very-long"),
        pytest.param("g" * 32, id="not-hex"),
        pytest.param("a" * 31 + "%C3%A9", id="non-ascii"),
        pytest.param("a" * 32 + "%0A", id="trailing-newline"),
        pytest.param("a" * 32 + "%00", id="trailing-nul"),
        pytest.param("a" * 16 + "%2F" + "a" * 16, id="encoded-slash"),
        pytest.param("%20" + "a" * 31, id="leading-space"),
    ],
)
async def test_a_malformed_activation_id_is_refused_alike_for_any_run_and_never_echoed(
    writes: Api, activation: str, caplog: pytest.LogCaptureFixture
) -> None:
    world = writes.world
    alices = _blocked_run(world, "malformed")
    bobs = _start(world, "bobs", user=BOB)
    writes.calls.clear()

    with caplog.at_level(logging.DEBUG):
        async with _client(writes.app()) as client:
            answers = [
                await client.post(_retry_url(run_id, activation), headers=_as(ALICE), json={})
                for run_id in (alices.id, bobs.id, UNKNOWN_RUN)
            ]

    # The answer never depends on whose run it is, so it reveals none.
    assert len({(response.status_code, response.content) for response in answers}) == 1
    (answer_status,) = {response.status_code for response in answers}
    # An encoded slash splits the path, so no route matches; any other form is refused.
    assert answer_status == (404 if "%2F" in activation else 422), answers[0].text
    if answer_status == 422:
        assert _refusal(answers[0]) == (422, "validation_failed")
        assert answers[0].headers["cache-control"] == "private, no-store"
    seen = answers[0].text + caplog.text
    assert "a" * 16 not in seen and "g" * 16 not in seen
    assert writes.calls == []
    assert _restarts(world, alices.id) == []


async def test_a_failed_step_of_a_run_its_user_paused_is_retried_and_the_user_s_pause_stays(
    writes: Api,
) -> None:
    world = writes.world
    run = _start(world, "user-paused")
    world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor=ALICE)
    # While paused, the step's session cannot be created.
    _fail(world, run.id, "create_session", IMPLEMENT, "session.create_failed")
    activation = _step_id(run)

    async with _client(writes.app()) as client:
        offered, response = await _retry_as_offered(client, run.id, activation)
        restarting = await _detail(client, run.id)
        complete(world, run.id, "retry_step", IMPLEMENT, RESTARTED)
        restarted = await _detail(client, run.id)

    assert {cause["reason"] for cause in offered["causes"]} == {"user", "failure_path"}
    assert offered["retry_activation_ids"] == [activation]
    assert response.status_code == 200, response.text
    assert {cause["detail"] for cause in restarting["causes"]} == {
        "recovery.restarting",
        USER_PAUSE_DETAIL,
    }
    # The restart ends only its own pause: the person's pause stays, with Resume.
    assert (restarted["status"], restarted["pause_reason"]) == ("paused", "user")
    assert [cause["detail"] for cause in restarted["causes"]] == [USER_PAUSE_DETAIL]
    assert restarted["allowed_actions"] == ["resume", "cancel"]
    assert restarted["retry_activation_ids"] == []


async def test_an_empty_or_digit_only_activation_id_is_no_step_of_the_run(writes: Api) -> None:
    world = writes.world
    run = _blocked_run(world, "edges")
    writes.calls.clear()

    async with _client(writes.app()) as client:
        empty = await client.post(_retry_url(run.id, ""), headers=_as(ALICE), json={})
        empty_unknown = await client.post(_retry_url(UNKNOWN_RUN, ""), headers=_as(ALICE), json={})
        digits = await client.post(_retry_url(run.id, "1" * 32), headers=_as(ALICE), json={})

    # An empty id matches no route; the answer is the same for a run that does not exist.
    assert empty.status_code == 404
    assert (empty.status_code, empty.content) == (empty_unknown.status_code, empty_unknown.content)
    # Thirty-two digits are a well-formed id that no activation of the run has.
    assert _refusal(digits) == (409, "illegal_transition")
    assert _reason(digits) == "unknown_activation"
    assert "1" * 32 not in digits.text
    assert _restarts(world, run.id) == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"activation_id": 5}, id="id-as-number"),
        pytest.param({"activation_id": ["a" * 32]}, id="id-as-list"),
        pytest.param({"activation_id": None}, id="id-as-null"),
        pytest.param([], id="list"),
        pytest.param(None, id="null"),
        pytest.param(5, id="number"),
        pytest.param("x", id="string"),
        pytest.param(True, id="bool"),
    ],
)
async def test_a_retry_whose_body_is_not_an_empty_object_is_refused_before_any_work(
    writes: Api, body: Any
) -> None:
    world = writes.world
    run = _blocked_run(world, "body")
    activation = _step_id(run)
    writes.calls.clear()

    async with _client(writes.app()) as client:
        response = await client.post(
            _retry_url(run.id, activation),
            headers={**_as(ALICE), "content-type": "application/json"},
            content=json.dumps(body),
        )

    assert _refusal(response) == (422, "validation_failed"), response.text
    assert activation not in response.text
    assert writes.calls == []
    assert _restarts(world, run.id) == []


async def test_preflight_needs_a_body_and_the_runs_api_after_the_caller_check() -> None:
    body = {"workflow_id": "a" * 32, "host_id": "host-1"}
    async with _client(_app(None)) as client:
        anonymous = await client.post(f"{RUNS}:preflight", json=body)
        empty = await client.post(f"{RUNS}:preflight", headers=_as(ALICE), json={})
        signed_in = await client.post(f"{RUNS}:preflight", headers=_as(ALICE), json=body)

    assert _refusal(anonymous) == (401, "unauthenticated")
    assert _refusal(empty) == (422, "validation_failed")
    assert _refusal(signed_in) == (404, "not_found")


# ── Gate answers ────────────────────────────────────────────────────────────


def _gate_run(world: World, key: str = "gate", user: str = ALICE) -> CoralRun:
    world.clock.advance(1)
    return start(world, GATE_ONLY, spec=run_spec(user=user, start_key=key), start_key=key)


def _answer_url(run_id: str, node_id: str = "approve") -> str:
    return f"{RUNS}/{run_id}/gates/{node_id}:answer"


def _answer_body(outcome: str = "approve", token: str = APPROVE_TOKEN, **fields: Any) -> Any:
    return {"visit_token": token, "outcome": outcome, **fields}


async def test_the_owner_answers_a_gate_once_and_its_prompt_is_withdrawn_here(
    writes: Api,
) -> None:
    world, publisher = writes.world, writes.services.publisher
    run = _gate_run(world)
    anchor, prompt = _anchor_prompt(world, run)
    publisher.pending[(anchor, prompt)] = {}

    async with _client(writes.app()) as client:
        accepted = await client.post(
            _answer_url(run.id), headers=_as(ALICE), json=_answer_body(note="Ship it.")
        )
        withdrawn_then = dict(publisher.pending)
        duplicate = await client.post(_answer_url(run.id), headers=_as(ALICE), json=_answer_body())
        other = await client.post(
            _answer_url(run.id), headers=_as(ALICE), json=_answer_body("reject")
        )
        not_an_outcome = await client.post(
            _answer_url(run.id), headers=_as(ALICE), json=_answer_body("maybe")
        )

    assert (accepted.status_code, accepted.json()) == (200, {"result": "accepted"})
    assert withdrawn_then == {}
    assert ("withdraw", anchor, prompt) in publisher.calls
    assert (duplicate.status_code, duplicate.json()) == (200, {"result": "duplicate"})
    for refused in (other, not_an_outcome):
        assert refused.json() == {
            "error": {
                "code": "illegal_transition",
                "message": "Already answered: approve.",
                "details": {"reason": "already_answered"},
            }
        }
    assert _row_state(world, run.id)[0] == "completed"


async def test_a_gate_answer_on_a_live_visit_names_one_of_its_outcomes(writes: Api) -> None:
    run = _gate_run(writes.world)

    async with _client(writes.app()) as client:
        response = await client.post(
            _answer_url(run.id), headers=_as(ALICE), json=_answer_body("maybe")
        )

    assert response.json() == {
        "error": {
            "code": "validation_failed",
            "message": "Choose one of: approve, reject.",
            "details": {"reason": "invalid_answer"},
        }
    }
    assert _row_state(writes.world, run.id)[0] == "running"


async def test_a_gate_answer_to_a_paused_run_keeps_its_prompt(writes: Api) -> None:
    world, publisher = writes.world, writes.services.publisher
    run = _gate_run(world)
    anchor, prompt = _anchor_prompt(world, run)
    publisher.pending[(anchor, prompt)] = {}
    world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor=ALICE)

    async with _client(writes.app()) as client:
        response = await client.post(_answer_url(run.id), headers=_as(ALICE), json=_answer_body())

    assert _refusal(response) == (409, "illegal_transition")
    assert response.json()["error"]["details"] == {"reason": "run_paused"}
    assert publisher.pending == {(anchor, prompt): {}}


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (GateAnswerResult(outcome="refused", code="gate.stale"), (409, "stale_visit")),
        (GateAnswerResult(outcome="refused", code="run.contended"), (503, "server_busy")),
    ],
    ids=["stale", "busy"],
)
async def test_a_stale_or_busy_gate_answer_is_refused_with_its_code(
    writes: Api,
    monkeypatch: pytest.MonkeyPatch,
    result: GateAnswerResult,
    expected: tuple[int, str],
) -> None:
    run = _gate_run(writes.world)
    monkeypatch.setattr(writes.world.bridge, "answer_gate", lambda **_kwargs: result)

    async with _client(writes.app()) as client:
        response = await client.post(_answer_url(run.id), headers=_as(ALICE), json=_answer_body())

    assert _refusal(response) == expected
    if expected[0] == 503:
        assert response.headers["retry-after"] == "1"


@pytest.mark.parametrize(
    "case", ["wrong-node", "unknown-token", "other-user", "unknown-run", "malformed-run"]
)
async def test_a_gate_answer_the_caller_cannot_give_is_the_run_404(writes: Api, case: str) -> None:
    world = writes.world
    run = _gate_run(world)
    bobs = _gate_run(world, "bobs-gate", user=BOB)
    run_id, node_id, body = run.id, "approve", _answer_body()
    if case == "wrong-node":
        node_id = "end"
    elif case == "unknown-token":
        body = _answer_body(token="approve||:9")
    elif case == "other-user":
        run_id = bobs.id
    elif case == "unknown-run":
        run_id = UNKNOWN_RUN
    else:
        run_id = "not-a-run"

    async with _client(writes.app()) as client:
        response = await client.post(_answer_url(run_id, node_id), headers=_as(ALICE), json=body)

    assert (response.status_code, response.content) == (404, NOT_FOUND)
    assert _row_state(world, run.id)[0] == _row_state(world, bobs.id)[0] == "running"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(_answer_body(token=""), id="empty-token"),
        pytest.param(_answer_body(token="t" * 513), id="token-513"),
        pytest.param(_answer_body(""), id="empty-outcome"),
        pytest.param(_answer_body("o" * 129), id="outcome-129"),
        pytest.param(_answer_body(note="n" * 2001), id="note-2001"),
        pytest.param(_answer_body(note="not-a-\x00note"), id="note-nul"),
        pytest.param({**_answer_body(), "label": "approve"}, id="extra-field"),
    ],
)
async def test_a_gate_answer_out_of_bounds_is_refused(writes: Api, body: Any) -> None:
    run = _gate_run(writes.world)

    async with _client(writes.app()) as client:
        response = await client.post(_answer_url(run.id), headers=_as(ALICE), json=body)

    assert _refusal(response) == (422, "validation_failed")
    assert writes.calls == []


async def test_another_user_never_takes_a_gate_answer_admission(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, pools = _build(world, writes=_writes(world, tmp_path, max_in_flight=1))
    first, second = _gate_run(world, "first"), _gate_run(world, "second")
    held, release = threading.Event(), threading.Event()
    answer_gate = world.bridge.answer_gate

    def slow(**kwargs: Any) -> GateAnswerResult:
        held.set()
        assert release.wait(30)
        return answer_gate(**kwargs)

    monkeypatch.setattr(world.bridge, "answer_gate", slow)
    loads: list[str] = []
    try:
        async with _client(built.app()) as client:
            holding = asyncio.create_task(
                client.post(_answer_url(first.id), headers=_as(ALICE), json=_answer_body())
            )
            await poll_until_async(held.is_set, timeout_s=budget(10))
            load = world.bridge.load
            monkeypatch.setattr(
                world.bridge,
                "load",
                lambda **kwargs: loads.append(kwargs["run_id"]) or load(**kwargs),
            )
            from_bob = await client.post(
                _answer_url(second.id), headers=_as(BOB), json=_answer_body()
            )
            crowded = await client.post(
                _answer_url(second.id), headers=_as(ALICE), json=_answer_body()
            )
            release.set()
            accepted = await holding
    finally:
        release.set()
        _close(built, pools)

    assert (from_bob.status_code, from_bob.content) == (404, NOT_FOUND)
    assert _refusal(crowded) == (503, "server_busy")
    assert accepted.json() == {"result": "accepted"}
    # Refused before the run was loaded.
    assert loads == []


async def test_one_user_s_gate_answers_never_hold_every_admission(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, pools = _build(world, writes=_writes(world, tmp_path, max_per_user=2))
    alices = [_gate_run(world, f"alice-{index}") for index in range(3)]
    bobs = _gate_run(world, "bobs", user=BOB)
    held, release = threading.Event(), threading.Event()
    answer_gate = world.bridge.answer_gate
    waiting: list[str] = []

    def slow(**kwargs: Any) -> GateAnswerResult:
        if kwargs["actor"] == ALICE:
            waiting.append(kwargs["run_id"])
            held.set()
            assert release.wait(30)
        return answer_gate(**kwargs)

    monkeypatch.setattr(world.bridge, "answer_gate", slow)
    try:
        async with _client(built.app()) as client:
            holding = [
                asyncio.create_task(
                    client.post(_answer_url(run.id), headers=_as(ALICE), json=_answer_body())
                )
                for run in alices[:2]
            ]
            await poll_until_async(lambda: len(waiting) == 2, timeout_s=budget(10))
            third = await client.post(
                _answer_url(alices[2].id), headers=_as(ALICE), json=_answer_body()
            )
            bob = await client.post(_answer_url(bobs.id), headers=_as(BOB), json=_answer_body())
            release.set()
            accepted = await asyncio.gather(*holding)
    finally:
        release.set()
        _close(built, pools)

    assert _refusal(third) == (503, "server_busy")
    assert third.json()["error"]["message"] == "Too many gate answers at once; try again."
    assert bob.json() == {"result": "accepted"}
    assert [response.json() for response in accepted] == [{"result": "accepted"}] * 2


async def test_a_gate_answer_to_an_ended_run_that_cannot_load_is_no_longer_waiting(
    writes: Api,
) -> None:
    run = _gate_run(writes.world)
    _config_missing(writes.world, run)

    async with _client(writes.app()) as client:
        cancelled = await client.post(f"{RUNS}/{run.id}:cancel", headers=_as(ALICE), json={})
        response = await client.post(_answer_url(run.id), headers=_as(ALICE), json=_answer_body())

    assert cancelled.json()["status"] == "cancelled"
    assert response.json()["error"] == {
        "code": "illegal_transition",
        "message": "This gate is no longer waiting.",
        "details": {"reason": "no_longer_waiting"},
    }


# ── Who may write ───────────────────────────────────────────────────────────

WRITE_ROUTES = [
    pytest.param(":pause", {}, id="pause"),
    pytest.param(":resume", {}, id="resume"),
    pytest.param(":cancel", {}, id="cancel"),
    # An activation the other user's run has: the 404 never depends on the id.
    pytest.param(
        f"/activations/{store_activation_id(run_id_for(BOB, 'bobs'), 'approve||')}:retry",
        {},
        id="retry",
    ),
    pytest.param("/gates/approve:answer", _answer_body(), id="answer"),
]


@pytest.mark.parametrize(("route", "body"), WRITE_ROUTES)
@pytest.mark.parametrize("case", ["unknown", "malformed", "upper-case", "other-user"])
async def test_every_write_route_answers_one_404_doing_no_work_for_a_run_it_may_not_change(
    writes: Api, route: str, body: dict[str, Any], case: str
) -> None:
    bobs = _gate_run(writes.world, "bobs", user=BOB)
    before = _row_state(writes.world, bobs.id)
    run_id = {
        "unknown": UNKNOWN_RUN,
        "malformed": "not-a-run",
        "upper-case": bobs.id.upper(),
        "other-user": bobs.id,
    }[case]

    async with _client(writes.app()) as client:
        response = await client.post(f"{RUNS}/{run_id}{route}", headers=_as(ALICE), json=body)

    assert (response.status_code, response.content) == (404, NOT_FOUND)
    assert writes.calls == ([] if case in ("malformed", "upper-case") else ["runs.get_run"])
    assert _row_state(writes.world, bobs.id) == before


@pytest.mark.parametrize(("route", "body"), WRITE_ROUTES)
async def test_without_the_runs_api_every_write_route_is_the_run_404_after_authentication(
    route: str, body: dict[str, Any]
) -> None:
    async with _client(_app(None)) as client:
        anonymous = await client.post(f"{RUNS}/{UNKNOWN_RUN}{route}", json=body)
        signed_in = await client.post(
            f"{RUNS}/{UNKNOWN_RUN}{route}", headers=_as(ALICE), json=body
        )
        start_anonymous = await client.post(RUNS, json=_start_body("a" * 32))
        start_signed_in = await client.post(RUNS, headers=_as(ALICE), json=_start_body("a" * 32))

    assert _refusal(anonymous) == _refusal(start_anonymous) == (401, "unauthenticated")
    assert (signed_in.status_code, signed_in.content) == (404, NOT_FOUND)
    assert (start_signed_in.status_code, start_signed_in.content) == (404, NOT_FOUND)


async def test_with_authentication_off_the_local_user_changes_its_runs(writes: Api) -> None:
    run = _start(writes.world, "local", user=None)

    async with _client(writes.app(None)) as client:
        paused = await client.post(f"{RUNS}/{run.id}:pause", json={})
        resumed = await client.post(f"{RUNS}/{run.id}:resume", json={})
        cancelled = await client.post(f"{RUNS}/{run.id}:cancel", json={})

    assert [response.json()["status"] for response in (paused, resumed, cancelled)] == [
        "paused",
        "running",
        "cancelled",
    ]


# ── Models ──────────────────────────────────────────────────────────────────


def test_slot_names_are_the_stored_codes_names() -> None:
    assert sorted(get_args(SlotRoleName)) == sorted(SLOT_ROLE)
    assert sorted(get_args(SlotStatusName)) == sorted(SLOT_STATUS)


# ── Through the server's lifespan ───────────────────────────────────────────


async def test_the_lifespan_publishes_the_runs_api_and_closes_its_pools(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[OmnigentHostWorkspaceChannels] = []
    asked: list[OmnigentHostWorkspaceChannels] = []
    host, _channels = _outcome_host()
    make_channels = OmnigentHostWorkspaceChannels.__init__

    def recording_init(self: OmnigentHostWorkspaceChannels, **stores: Any) -> None:
        built.append(self)
        make_channels(self, **stores)

    async def host_channel(
        self: OmnigentHostWorkspaceChannels, **_owner: Any
    ) -> HostChannelBackend:
        asked.append(self)
        return host

    monkeypatch.setattr(OmnigentHostWorkspaceChannels, "__init__", recording_init)
    monkeypatch.setattr(OmnigentHostWorkspaceChannels, "channel", host_channel)
    server = coral_server(db_uri, tmp_path, server_plugins=[CORAL_SERVER_PLUGIN])
    world, run, _anchor, _prompt = gate_run(server.db_uri, base_commit=BASE)
    # The plugin's definitions file is shared by this worker's tests: a key of its own.
    yaml_text = TWO_STEPS.replace("id: two-steps", f"id: lifespan-{run.id[:12]}")
    try:
        async with _client(server.app) as client:
            async with coral_lifespan(server.app, server.services):
                api = server.app.state.coral_runs_api
                detail = await client.get(f"{RUNS}/{run.id}")
                listed = (await client.get(RUNS)).json()["data"]
                answered = await client.post(
                    f"{RUNS}/{run.id}/gates/approve:answer", json=_answer_body()
                )
                await poll_until_async(
                    lambda: run_status(world, run) == int(RunStatus.COMPLETED),
                    timeout_s=budget(30),
                )
                outcome = await client.get(f"{RUNS}/{run.id}/outcome")
                engine_wired = hasattr(server.app.state, "coral_session_facade")
                saved = (await client.post("/v1/coral/workflows", json={"yaml": yaml_text})).json()
                # No host with this id is registered: the host check refuses before any frame.
                started = await client.post(RUNS, json=_start_body(saved["id"]))
            closed = await client.get(f"{RUNS}/{run.id}")
    finally:
        pending_elicitations.reset_for_tests()
        elicitation_hooks.reset_for_tests()

    assert isinstance(api, RunsApi)
    assert detail.status_code == 200, detail.text
    assert [gate["node_id"] for gate in detail.json()["gates"]] == ["approve"]
    assert [item["run_id"] for item in listed] == [run.id]
    assert (answered.status_code, answered.json()) == (200, {"result": "accepted"})
    assert run_status(world, run) == int(RunStatus.COMPLETED)
    # The runs API reads the diff through the one host-channels object the engine uses.
    assert outcome.status_code == 200, outcome.text
    assert (outcome.json()["head_commit"], outcome.json()["diff_unavailable"]) == (HEAD, None)
    assert engine_wired
    assert len(built) == 1 and asked == built
    assert host.ops() == ["head", "diff_stat"]
    assert _refusal(started) == (403, "not_permitted")
    # After exit its pools are closed: a call is refused as busy, never run.
    assert _refusal(closed) == (503, "server_busy")
    assert api.in_flight.closed
