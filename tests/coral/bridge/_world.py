"""A bridge over stores, with a manual clock, for the bridge's write-side tests.

``World.fake`` runs on the in-memory stores; ``World.sql`` on one database URI.
Both pin workflow versions in SQL, the only version store there is.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from coral.bridge.codec import decode_entries
from coral.bridge.config import ENGINE_LOG_PAGE, freeze_engine_config
from coral.bridge.service import EngineBridge
from coral.bridge.start import start_engine_run
from coral.db import CoralBase
from coral.db.enum_codecs import WorkStatus
from coral.engine import fold
from coral.engine.types import RunState
from coral.model.ids import derived_id
from coral.queue import FinishedWork, SqlAlchemyCoralQueueStore
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
from coral.stores.workflow_versions import SqlAlchemyWorkflowVersionStore
from coral.workspace.run_worktree import run_branch_name
from tests.coral.workflow_builders import compile_text, fixture_text

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
        )

    @classmethod
    def _build(
        cls, runs: RunStore, queue: QueueStore, versions: SqlAlchemyWorkflowVersionStore
    ) -> World:
        clock = ManualClock()
        bridge = EngineBridge(run_store=runs, queue_store=queue, versions=versions, clock=clock)
        return cls(runs=runs, queue=queue, versions=versions, clock=clock, bridge=bridge)

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
    world: World, *, start_key: str = "bare", yaml_text: str | None = None
) -> CoralRun:
    """A run whose ``start_run`` committed and whose ``StartRun`` did not: a crash between."""
    text = yaml_text if yaml_text is not None else fixture_text("two_steps")
    pinned = world.versions.pin(
        workspace_id=WORKSPACE,
        workflow_id=DEFINITION,
        graph=compile_text(text)[0],
        yaml_text=text,
        created_by=USER,
    )
    spec = run_spec(
        start_key=start_key,
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
