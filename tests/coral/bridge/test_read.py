"""The bridge's read-only load: a run that cannot be loaded is shown, never paused."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest
import zstandard

from coral.bridge.config import LOCK_TIMEOUT_S
from coral.bridge.service import EngineBridge, EngineLoadFailed
from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.recovery.cancel import cancel_run_row
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import RunNotFound
from tests.coral.bridge._gates import APPROVE_TOKEN, GATE_ONLY, answer
from tests.coral.bridge._world import WORKSPACE, World, start, start_without_engine


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


def _runs(world: World) -> FakeRunStore:
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    return runs


def _graph_missing(world: World, run_id: str) -> None:
    key = (WORKSPACE, run_id)
    _runs(world).runs[key] = dataclasses.replace(_runs(world).runs[key], version_id="0" * 32)


def _config_missing(world: World, run_id: str) -> None:
    key = (WORKSPACE, run_id)
    _runs(world).specs[key] = dataclasses.replace(_runs(world).specs[key], engine_config=None)


def _log_corrupt(world: World, run_id: str) -> None:
    logs = _runs(world).logs[(WORKSPACE, run_id)]
    logs[0] = dataclasses.replace(logs[0], body="{}")


def _rows_failing(error: Exception) -> Callable[[World, str], None]:
    """The run's rows raise ``error`` when they are read."""

    def undecodable(world: World, run_id: str) -> None:
        runs = _runs(world)
        load = runs.load_run_state

        def failing(broken: str, **kwargs: object) -> object:
            if broken == run_id:
                raise error
            return load(broken, **kwargs)  # type: ignore[arg-type]

        runs.load_run_state = failing  # type: ignore[method-assign]

    return undecodable


UNLOADABLE: dict[str, Callable[[World, str], None]] = {
    "graph": _graph_missing,
    "config": _config_missing,
    "log": _log_corrupt,
    "rows": _rows_failing(zstandard.ZstdError("not a zstd frame")),
    # A frame cut short, of a codec this server does not know, or too large.
    "rows_unknown_codec": _rows_failing(ValueError("Unknown compression codec")),
}


def _stored(world: World, run_id: str) -> tuple[object, ...]:
    """Everything a read could have written for the run."""
    runs = _runs(world)
    return (
        runs.runs[(WORKSPACE, run_id)],
        tuple(runs.logs[(WORKSPACE, run_id)]),
        tuple(runs.list_alerts(run_id, workspace_id=WORKSPACE)),
        tuple(world.work(run_id)),
    )


def test_a_loadable_run_reads_as_its_rows_and_engine_state(world: World) -> None:
    run = start(world)
    before = _stored(world, run.id)

    read = world.bridge.read(workspace_id=WORKSPACE, run_id=run.id)

    loaded = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    assert read.loadable
    assert read.run == world.run(run.id)
    assert read.rows == loaded.store
    assert read.snapshot == loaded
    assert _stored(world, run.id) == before


@pytest.mark.parametrize("kind", list(UNLOADABLE))
def test_a_run_that_cannot_be_loaded_reads_as_its_row_and_writes_nothing(
    world: World, kind: str
) -> None:
    run = start(world)
    UNLOADABLE[kind](world, run.id)
    before = _stored(world, run.id)

    for _ in range(2):
        read = world.bridge.read(workspace_id=WORKSPACE, run_id=run.id)
        assert not read.loadable
        assert read.snapshot is None
        assert read.run == world.run(run.id)
        assert (read.rows is None) == kind.startswith("rows")
        if read.rows is not None:
            assert read.rows.run == read.run

    # WHY: a GET must not pause a run; the load the commands use still does.
    assert _stored(world, run.id) == before
    with pytest.raises(EngineLoadFailed):
        world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    paused = world.run(run.id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    # A command's commit fails the same way, so a cancel falls back to the row.
    with pytest.raises(EngineLoadFailed):
        world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")


def _paused(world: World) -> str:
    run = start(world)
    world.bridge.pause_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    return run.id


def _completed(world: World) -> str:
    run = start(world, GATE_ONLY)
    answer(world, run.id, APPROVE_TOKEN, "approve")
    return run.id


def _cancelled(world: World) -> str:
    run = start(world)
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")
    return run.id


def _cancelled_on_its_row(world: World) -> str:
    run = start(world)
    _config_missing(world, run.id)
    cancel_run_row(
        world.runs,
        workspace_id=WORKSPACE,
        run_id=run.id,
        actor="alice",
        now_us=world.clock.epoch * 1_000_000,
        lock_timeout_s=LOCK_TIMEOUT_S,
    )
    return run.id


IN_STATUS: dict[str, tuple[Callable[[World], str], RunStatus]] = {
    "starting": (lambda world: start_without_engine(world).id, RunStatus.STARTING),
    "paused": (_paused, RunStatus.PAUSED),
    "completed": (_completed, RunStatus.COMPLETED),
    "cancelled": (_cancelled, RunStatus.CANCELLED),
    "cancelled_on_its_row": (_cancelled_on_its_row, RunStatus.CANCELLED),
}


@pytest.mark.parametrize("status", list(IN_STATUS))
def test_a_run_in_any_status_reads_without_writing(world: World, status: str) -> None:
    make, expected = IN_STATUS[status]
    run_id = make(world)
    before = _stored(world, run_id)

    for _ in range(2):
        read = world.bridge.read(workspace_id=WORKSPACE, run_id=run_id)
        assert read.run == world.run(run_id)
        assert read.run.status == int(expected)
        assert read.loadable == (status != "cancelled_on_its_row")

    assert _stored(world, run_id) == before


def _not_utf_8(*_args: object, **_kwargs: object) -> object:
    raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


@pytest.mark.parametrize("part", ["log", "pinned_version"])
def test_stored_text_that_is_not_utf_8_reads_as_unloadable(
    world: World, monkeypatch: pytest.MonkeyPatch, part: str
) -> None:
    run = start(world)
    target, name = (world.runs, "read_engine_log") if part == "log" else (world.versions, "load")
    monkeypatch.setattr(target, name, _not_utf_8)
    # A new process: nothing of the run is folded or pinned in memory yet.
    cold = EngineBridge(
        run_store=world.runs, queue_store=world.queue, versions=world.versions, clock=world.clock
    )
    before = _stored(world, run.id)

    read = cold.read(workspace_id=WORKSPACE, run_id=run.id)

    assert (read.loadable, read.run, read.rows is not None) == (False, world.run(run.id), True)
    assert _stored(world, run.id) == before
    # The commands agree: the run cannot be loaded.
    with pytest.raises(EngineLoadFailed):
        cold.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="user:alice")


def test_a_run_whose_spec_row_is_missing_reads_as_its_row(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world)
    load = world.runs.load_run_state

    def spec_missing(run_id: str, **options: object) -> object:
        if run_id == run.id:
            raise RunNotFound(f"RunSpec for run {run_id!r} not found")
        return load(run_id, **options)  # type: ignore[arg-type]

    monkeypatch.setattr(world.runs, "load_run_state", spec_missing)
    before = _stored(world, run.id)

    read = world.bridge.read(workspace_id=WORKSPACE, run_id=run.id)

    assert (read.run, read.rows, read.snapshot) == (world.run(run.id), None, None)
    assert _stored(world, run.id) == before


def test_reading_a_run_the_workspace_does_not_have_raises_not_found(world: World) -> None:
    run = start(world)
    with pytest.raises(RunNotFound):
        world.bridge.read(workspace_id=WORKSPACE, run_id="f" * 32)
    with pytest.raises(RunNotFound):
        world.bridge.read(workspace_id=WORKSPACE + 1, run_id=run.id)
