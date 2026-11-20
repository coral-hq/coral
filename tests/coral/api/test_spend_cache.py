"""The run spend cache: lists never wait, the detail waits a bounded time, reads are shared."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator

import pytest

from coral.api.spend import (
    FINISH_SETTLE_S,
    MAX_PENDING_REFRESHES,
    MAX_SPEND_ENTRIES,
    SPEND_THREAD_NAME,
    SPEND_THREADS,
    CachedSpend,
    SpendCache,
)
from coral.bridge.executors import BoundedThreads
from coral.omni.protocols import RunSpendTotals
from tests._helpers.polling import poll_until_async

WORKSPACE = 7
OTHER_WORKSPACE = 8
RUN = "a" * 32
TOTALS = RunSpendTotals(
    usd=1.25,
    live_usd=1.5,
    input_tokens=10,
    output_tokens=2,
    total_tokens=12,
    cache_read_tokens=0,
    cache_creation_tokens=0,
    unpriced_models=(),
    sessions=3,
)


class _Clock:
    """One injected time for the cache's expiry and its ``as_of`` stamps."""

    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


class _Reader:
    """A run spend reader that records its calls and blocks while its gate is closed."""

    def __init__(self) -> None:
        self.gate = threading.Event()
        self.gate.set()
        # The runs the gate holds; None holds every run.
        self.held: set[str] | None = None
        self.results: dict[str, RunSpendTotals | Exception | None] = {}
        self._lock = threading.Lock()
        self._calls: list[tuple[int, str]] = []

    @property
    def calls(self) -> list[tuple[int, str]]:
        with self._lock:
            return list(self._calls)

    def run_spend(self, *, workspace_id: int, run_id: str) -> RunSpendTotals | None:
        with self._lock:
            self._calls.append((workspace_id, run_id))
        # Bounded, so a failing test cannot leave a pool thread waiting forever.
        if self.held is None or run_id in self.held:
            assert self.gate.wait(timeout=30)
        result = self.results.get(run_id, TOTALS)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def reader() -> Iterator[_Reader]:
    reader = _Reader()
    yield reader
    reader.gate.set()


@pytest.fixture
def threads() -> Iterator[BoundedThreads]:
    pool = BoundedThreads(max_workers=SPEND_THREADS, thread_name_prefix=SPEND_THREAD_NAME)
    yield pool
    pool.close()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


def _cache(reader: _Reader, threads: BoundedThreads, clock: _Clock, **limits: int) -> SpendCache:
    return SpendCache(reader, threads, clock=clock, wall_clock=clock, **limits)


def _peek(
    cache: SpendCache, run_id: str = RUN, *, finished_at: int | None = None
) -> CachedSpend | None:
    return cache.peek(workspace_id=WORKSPACE, run_id=run_id, finished_at=finished_at)


async def _get(
    cache: SpendCache,
    run_id: str = RUN,
    *,
    finished_at: int | None = None,
    wait_s: float = 10.0,
    workspace_id: int = WORKSPACE,
) -> CachedSpend | None:
    return await cache.get(
        workspace_id=workspace_id, run_id=run_id, finished_at=finished_at, wait_s=wait_s
    )


def test_the_cache_limits_are_the_designed_ones() -> None:
    assert (MAX_SPEND_ENTRIES, MAX_PENDING_REFRESHES, SPEND_THREADS) == (1024, 64, 2)
    assert SPEND_THREAD_NAME == "coral-spend"


async def test_peek_returns_at_once_and_schedules_one_shared_read(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock)
    reader.gate.clear()

    assert [_peek(cache) for _ in range(3)] == [None, None, None]
    assert cache.pending == 1
    await poll_until_async(lambda: reader.calls == [(WORKSPACE, RUN)])
    reader.gate.set()
    await poll_until_async(lambda: _peek(cache) is not None)

    assert _peek(cache) == CachedSpend(totals=TOTALS, as_of=int(clock.now))
    assert (reader.calls, cache.pending) == ([(WORKSPACE, RUN)], 0)


async def test_get_waits_at_most_wait_s_then_returns_what_the_cache_holds(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock)
    reader.gate.clear()

    assert await _get(cache, wait_s=0.05) is None
    # The read goes on in the background and fills the cache when it ends.
    assert cache.pending == 1
    reader.gate.set()
    await poll_until_async(lambda: _peek(cache) is not None)
    first = _peek(cache)

    clock.now += 16
    reader.gate.clear()
    # Expired: the stale figure is what the cache holds while the refresh runs.
    assert await _get(cache, wait_s=0.05) == first
    reader.gate.set()
    await poll_until_async(lambda: _peek(cache) == CachedSpend(TOTALS, int(clock.now)))
    assert len(reader.calls) == 2


async def test_get_returns_a_read_that_ends_in_time_and_keys_by_workspace(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock)

    assert await _get(cache) == CachedSpend(TOTALS, int(clock.now))
    assert await _get(cache) == CachedSpend(TOTALS, int(clock.now))
    assert await _get(cache, workspace_id=OTHER_WORKSPACE) == CachedSpend(TOTALS, int(clock.now))
    assert reader.calls == [(WORKSPACE, RUN), (OTHER_WORKSPACE, RUN)]


async def test_concurrent_misses_share_one_read(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock)
    reader.gate.clear()

    waiting = [asyncio.create_task(_get(cache)) for _ in range(5)]
    await poll_until_async(lambda: len(reader.calls) == 1)
    assert _peek(cache) is None
    reader.gate.set()

    assert await asyncio.gather(*waiting) == [CachedSpend(TOTALS, int(clock.now))] * 5
    assert reader.calls == [(WORKSPACE, RUN)]


@pytest.mark.parametrize(("finished_s_ago", "ttl_s"), [(None, 15), (3600, 300)])
async def test_spend_is_read_again_after_its_runs_ttl(
    reader: _Reader,
    threads: BoundedThreads,
    clock: _Clock,
    finished_s_ago: int | None,
    ttl_s: int,
) -> None:
    cache = _cache(reader, threads, clock)
    finished_at = None if finished_s_ago is None else int(clock.now) - finished_s_ago
    read_at = int(clock.now)
    await _get(cache, finished_at=finished_at)

    clock.now += ttl_s - 0.5
    assert _peek(cache, finished_at=finished_at) == CachedSpend(TOTALS, read_at)
    assert cache.pending == 0

    clock.now += 1
    assert await _get(cache, finished_at=finished_at) == CachedSpend(TOTALS, int(clock.now))
    assert len(reader.calls) == 2


async def test_a_run_that_finishes_is_read_again_and_kept_short_while_its_spend_settles(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock)
    await _get(cache)

    # The row now shows the run finished: the read taken while it ran is stale at once.
    finished_at = int(clock.now) + 1
    clock.now += 2
    assert _peek(cache, finished_at=finished_at) == CachedSpend(TOTALS, int(clock.now) - 2)
    assert cache.pending == 1
    await poll_until_async(lambda: cache.pending == 0)
    assert len(reader.calls) == 2

    # Spend still lands just after the finish, so reads stay short-lived for a while.
    clock.now += 15.5
    assert await _get(cache, finished_at=finished_at) == CachedSpend(TOTALS, int(clock.now))
    assert len(reader.calls) == 3

    # Settled: the next read is kept for the finished lifetime.
    clock.now = finished_at + FINISH_SETTLE_S + 16
    settled = await _get(cache, finished_at=finished_at)
    clock.now += 299
    assert await _get(cache, finished_at=finished_at) == settled
    assert len(reader.calls) == 4


async def test_a_detail_read_never_waits_behind_background_refreshes(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock)
    listed = [f"{index:032x}" for index in range(5)]
    detail = "d" * 32
    # Refreshes would fill both threads if they ran side by side.
    reader.held = set(listed[:2])
    reader.gate.clear()

    assert [_peek(cache, run_id) for run_id in listed] == [None] * 5
    await poll_until_async(lambda: len(reader.calls) == 1)
    # A run no list asked for, and a run whose refresh is still queued, are read at once.
    assert await _get(cache, detail) == CachedSpend(TOTALS, int(clock.now))
    assert await _get(cache, listed[3]) == CachedSpend(TOTALS, int(clock.now))
    assert reader.calls == [(WORKSPACE, listed[0]), (WORKSPACE, detail), (WORKSPACE, listed[3])]
    # The detail's read took that run out of the queue: one running, three queued.
    assert cache.pending == 4

    reader.gate.set()
    await poll_until_async(lambda: cache.pending == 0)
    assert sorted(run_id for _, run_id in reader.calls) == sorted([*listed, detail])


async def test_a_failed_read_is_unknown_for_five_seconds_and_logged_once(
    reader: _Reader,
    threads: BoundedThreads,
    clock: _Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache = _cache(reader, threads, clock)
    reader.results[RUN] = RuntimeError("conversation store unavailable")

    with caplog.at_level(logging.WARNING, logger="coral.api.spend"):
        assert await _get(cache) is None
        clock.now += 4.5
        assert await _get(cache) is None
        assert len(reader.calls) == 1
        clock.now += 1
        assert await _get(cache) is None
        assert len(reader.calls) == 2

    (record,) = caplog.records
    assert RUN in record.getMessage()
    assert "RuntimeError" in record.getMessage()
    reader.results[RUN] = TOTALS
    clock.now += 5.5
    assert await _get(cache) == CachedSpend(TOTALS, int(clock.now))


async def test_a_run_without_a_session_tree_is_unknown_not_zero(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock)
    reader.results[RUN] = None

    assert await _get(cache) is None
    assert _peek(cache) is None
    assert (len(reader.calls), cache.pending) == (1, 0)


async def test_background_refreshes_beyond_the_pending_limit_are_dropped(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock, max_pending=3)
    runs = [f"{index:032x}" for index in range(5)]
    reader.gate.clear()

    assert [_peek(cache, run_id) for run_id in runs] == [None] * 5
    assert cache.pending == 3
    reader.gate.set()
    await poll_until_async(lambda: cache.pending == 0)
    assert sorted(run_id for _, run_id in reader.calls) == runs[:3]

    assert _peek(cache, runs[3]) is None
    assert cache.pending == 1


async def test_the_least_recently_used_spend_is_evicted_past_the_entry_limit(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock, max_entries=2)
    first, second, third = (f"{index:032x}" for index in range(3))
    await _get(cache, first)
    await _get(cache, second)
    assert _peek(cache, first) is not None

    await _get(cache, third)

    assert _peek(cache, first) is not None
    assert _peek(cache, third) is not None
    assert _peek(cache, second) is None


async def test_a_closed_cache_drops_its_reads_and_schedules_no_more(
    reader: _Reader, threads: BoundedThreads, clock: _Clock
) -> None:
    cache = _cache(reader, threads, clock)
    reader.gate.clear()
    _peek(cache)

    cache.close()
    threads.close()

    assert cache.pending == 0
    assert _peek(cache, "b" * 32) is None
    assert await _get(cache, "c" * 32) is None
    assert cache.pending == 0
