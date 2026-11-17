"""The run-status cache: short-lived entries, dropped on each commit, a bounded stale fallback."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import pytest

from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.omni.policies.state import RunStateUnavailable, RunStatusCache, RunStatusView
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun, RunStartSpec, Transition

WORKSPACE = 7


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Store:
    """The fake run store's ``get_run``, counted, with an injectable error and in-read action."""

    def __init__(self) -> None:
        self.runs = FakeRunStore(default_workspace_id=WORKSPACE)
        self.reads = 0
        self.error: Exception | None = None
        self.during_read: Callable[[], None] | None = None

    def get_run(self, run_id: str, *, workspace_id: int | None = None) -> CoralRun | None:
        self.reads += 1
        if self.error is not None:
            raise self.error
        run = self.runs.get_run(run_id, workspace_id=workspace_id)
        if self.during_read is not None:
            # Something happens between the row read and the cache update.
            action, self.during_read = self.during_read, None
            action()
        return run

    def start(
        self, status: RunStatus = RunStatus.RUNNING, *, workspace_id: int = WORKSPACE
    ) -> str:
        run = self.runs.start_run(RunStartSpec("wf", "v1", "Run", "", workspace_id=workspace_id))
        self.set(run.id, status, workspace_id=workspace_id)
        return run.id

    def set(
        self,
        run_id: str,
        status: RunStatus,
        *,
        reason: RunPauseReason | None = None,
        workspace_id: int = WORKSPACE,
    ) -> None:
        _, version = self.runs.load_run_state(run_id, workspace_id=workspace_id)
        self.runs.apply_transition(
            run_id,
            version,
            Transition(
                status=int(status),
                pause_reason=None if reason is None else int(reason),
                clear_pause_reason=reason is None,
            ),
            workspace_id=workspace_id,
        )


def _cache(store: _Store, clock: _Clock, **options: int) -> RunStatusCache:
    return RunStatusCache(store, clock=clock, **options)


RUNNING = RunStatusView("running", None)
PAUSED_DRIFT = RunStatusView("paused", "drift")


def test_a_status_is_read_once_per_ttl() -> None:
    store, clock = _Store(), _Clock()
    run_id = store.start()
    cache = _cache(store, clock)

    assert cache.status(WORKSPACE, run_id) == RUNNING
    clock.now += 1.5
    assert cache.status(WORKSPACE, run_id) == RUNNING
    assert store.reads == 1

    # The row changed with no commit seen in this process: the TTL bounds the staleness.
    store.set(run_id, RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    assert cache.status(WORKSPACE, run_id) == RUNNING
    clock.now += 0.5
    assert cache.status(WORKSPACE, run_id) == PAUSED_DRIFT
    assert store.reads == 2


def test_a_commit_drops_the_entry_through_the_post_commit_hook() -> None:
    store, clock = _Store(), _Clock()
    run_id = store.start()
    cache = _cache(store, clock)
    unregister = store.runs.register_post_commit(cache.invalidate)
    assert cache.status(WORKSPACE, run_id) == RUNNING

    # No clock movement: the next status read sees the commit at once.
    store.set(run_id, RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    assert cache.status(WORKSPACE, run_id) == PAUSED_DRIFT
    assert store.reads == 2

    unregister()
    store.set(run_id, RunStatus.RUNNING)
    assert cache.status(WORKSPACE, run_id) == PAUSED_DRIFT


def test_stale_fallback_is_bounded() -> None:
    store, clock = _Store(), _Clock()
    run_id = store.start()
    cache = _cache(store, clock)
    assert cache.status(WORKSPACE, run_id) == RUNNING

    store.error = RuntimeError("database is locked")
    # Past the TTL the store fails: the last status read serves for up to 30 s.
    clock.now += 30.0
    assert cache.status(WORKSPACE, run_id) == RUNNING
    clock.now += 0.001
    with pytest.raises(RunStateUnavailable) as unavailable:
        cache.status(WORKSPACE, run_id)
    assert "database is locked" not in str(unavailable.value)
    assert isinstance(unavailable.value.__cause__, RuntimeError)

    # A run never read successfully has nothing to fall back to.
    with pytest.raises(RunStateUnavailable):
        cache.status(WORKSPACE, "never-read")

    # The store recovers: a fresh read is cached again.
    store.error = None
    assert cache.status(WORKSPACE, run_id) == RUNNING


def test_an_invalidated_entry_is_no_stale_fallback() -> None:
    store, clock = _Store(), _Clock()
    run_id = store.start()
    cache = _cache(store, clock)
    assert cache.status(WORKSPACE, run_id) == RUNNING

    cache.invalidate(run_id, 3)
    store.error = RuntimeError("database is locked")
    # The status read before the commit may be the one the commit changed.
    with pytest.raises(RunStateUnavailable):
        cache.status(WORKSPACE, run_id)


def test_read_started_before_invalidation_is_not_cached() -> None:
    store, clock = _Store(), _Clock()
    run_id = store.start()
    cache = _cache(store, clock)
    unregister = store.runs.register_post_commit(cache.invalidate)

    # The read loads "running"; a pause commits before the read stores its result.
    store.during_read = lambda: store.set(run_id, RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    assert cache.status(WORKSPACE, run_id) == RUNNING
    # The old status was not stored: the next read goes to the store and sees the pause.
    assert cache.status(WORKSPACE, run_id) == PAUSED_DRIFT
    assert store.reads == 2
    assert cache.status(WORKSPACE, run_id) == PAUSED_DRIFT
    assert store.reads == 2

    # Another run's commit during a read does not discard that read.
    other = store.start()
    store.during_read = lambda: store.set(other, RunStatus.PAUSED)
    clock.now += 2.0
    assert cache.status(WORKSPACE, run_id) == PAUSED_DRIFT
    assert cache.status(WORKSPACE, run_id) == PAUSED_DRIFT
    assert store.reads == 3
    unregister()


@pytest.mark.parametrize(
    ("status", "reason", "view"),
    [
        (RunStatus.STARTING, None, RunStatusView("starting", None)),
        (RunStatus.PAUSED, RunPauseReason.BUDGET, RunStatusView("paused", "budget")),
        (RunStatus.PAUSED, None, RunStatusView("paused", None)),
        (RunStatus.CANCELLED, None, RunStatusView("cancelled", None)),
        (RunStatus.COMPLETED, None, RunStatusView("completed", None)),
        (RunStatus.FAILED, None, RunStatusView("failed", None)),
    ],
)
def test_the_view_names_the_status_and_a_paused_runs_reason(
    status: RunStatus, reason: RunPauseReason | None, view: RunStatusView
) -> None:
    store = _Store()
    run_id = store.start(status)
    if reason is not None:
        store.set(run_id, status, reason=reason)

    assert _cache(store, _Clock()).status(WORKSPACE, run_id) == view


def test_a_missing_run_is_never_kept() -> None:
    store, clock = _Store(), _Clock()
    cache = _cache(store, clock)
    unregister = store.runs.register_post_commit(cache.invalidate)
    started = store.runs.start_run(RunStartSpec("wf", "v1", "Run", "", workspace_id=WORKSPACE))
    row = store.runs.runs.pop((WORKSPACE, started.id))

    assert cache.status(WORKSPACE, started.id) == RunStatusView("missing", None)
    assert cache.status(WORKSPACE, started.id) == RunStatusView("missing", None)
    assert store.reads == 2
    # The row appears with no commit hook (as start_run inserts it): the next read sees it.
    store.runs.runs[(WORKSPACE, started.id)] = row
    assert cache.status(WORKSPACE, started.id) == RunStatusView("starting", None)
    assert cache.status(WORKSPACE, started.id) == RunStatusView("starting", None)
    assert store.reads == 3
    unregister()


def test_a_missing_run_or_an_unknown_status_is_never_running() -> None:
    store, clock = _Store(), _Clock()
    cache = _cache(store, clock)
    assert cache.status(WORKSPACE, "no-such-run") == RunStatusView("missing", None)

    run_id = store.start()
    row = store.runs.runs[(WORKSPACE, run_id)]
    # A row carrying a pause reason while running reads without one.
    store.runs.runs[(WORKSPACE, run_id)] = dataclasses.replace(
        row, pause_reason=int(RunPauseReason.DRIFT)
    )
    assert cache.status(WORKSPACE, run_id) == RUNNING

    # A status this server cannot decode is a store error: no entry yet, so unavailable.
    newer = store.start()
    store.runs.runs[(WORKSPACE, newer)] = dataclasses.replace(row, id=newer, status=99)
    with pytest.raises(RunStateUnavailable):
        cache.status(WORKSPACE, newer)


def test_entries_are_kept_per_workspace_and_evicted_least_recently_read_first() -> None:
    store, clock = _Store(), _Clock()
    first, second, third = store.start(), store.start(), store.start()
    cache = _cache(store, clock, max_entries=2)

    for run_id in (first, second, first, third):
        cache.status(WORKSPACE, run_id)
    assert store.reads == 3
    # ``second`` was read least recently when ``third`` arrived.
    for run_id in (first, third, second):
        cache.status(WORKSPACE, run_id)
    assert store.reads == 4

    with pytest.raises(ValueError, match="max_entries"):
        _cache(store, clock, max_entries=0)


def test_a_commit_drops_the_runs_entry_in_every_workspace() -> None:
    store, clock = _Store(), _Clock()
    shared, other = store.start(), store.start()
    row = store.runs.runs[(WORKSPACE, shared)]
    # The commit hook names only the run, so the same id in another workspace goes too.
    store.runs.runs[(WORKSPACE + 1, shared)] = dataclasses.replace(row, workspace_id=WORKSPACE + 1)
    cache = _cache(store, clock)
    keys = ((WORKSPACE, shared), (WORKSPACE + 1, shared), (WORKSPACE, other))

    for _ in range(2):
        for workspace_id, run_id in keys:
            assert cache.status(workspace_id, run_id) == RUNNING
    assert store.reads == 3

    cache.invalidate(shared, 9)
    for workspace_id, run_id in keys:
        cache.status(workspace_id, run_id)
    assert store.reads == 5
