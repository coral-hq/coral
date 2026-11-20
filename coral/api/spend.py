"""Cached run spend: lists read only the cache, the detail waits a bounded time for a read.

Spend is one session-tree read per run, on its own small thread pool so it never
holds API threads. Reads are shared per run, failures are remembered briefly, and
nothing here caps spending. Background refreshes run one at a time, so a detail's
read always has a thread of its own and never queues behind them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from coral.bridge.executors import BoundedThreads, PoolClosed
from coral.omni.protocols import RunSpendReader, RunSpendTotals
from coral.queue.run_effects import describe_exception

_logger = logging.getLogger(__name__)

# One thread for background refreshes, the other for the detail's reads.
SPEND_THREADS = 2
SPEND_THREAD_NAME = "coral-spend"
# How long a read stays fresh: an unfinished run still spends, a finished one barely.
UNFINISHED_SPEND_TTL_S = 15.0
FINISHED_SPEND_TTL_S = 300.0
# Spend still lands just after a run finishes (its sessions' last turns and cancels), so
# a run finished less than this long ago keeps the unfinished lifetime.
FINISH_SETTLE_S = 60.0
# How long a failed read is shown as unknown before the next read.
FAILED_SPEND_TTL_S = 5.0
MAX_SPEND_ENTRIES = 1024
# Refreshes a list may queue while others are pending; the rest are dropped.
MAX_PENDING_REFRESHES = 64
DETAIL_SPEND_WAIT_S = 10.0

_SpendKey = tuple[int, str]


@dataclass(frozen=True)
class CachedSpend:
    """A run's spend and when it was read (epoch seconds)."""

    totals: RunSpendTotals
    as_of: int


@dataclass(frozen=True)
class _Entry:
    # None: unknown (the read failed, or the run has no sessions yet).
    spend: CachedSpend | None
    expires_at: float
    failed: bool
    # The run's finished_at when it was read; an entry read before the run finished is stale.
    finished_at: int | None


class SpendCache:
    """
    Run spend by ``(workspace_id, run_id)``, least recently used first out.

    Callers pass the run row's ``finished_at``, which sets how long a read stays fresh
    and invalidates a read taken before the run finished. Call it on the event loop:
    reads run on ``threads``, and all state changes on the loop. Callers check the
    run's owner before asking.
    """

    def __init__(
        self,
        reader: RunSpendReader,
        threads: BoundedThreads,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        max_entries: int = MAX_SPEND_ENTRIES,
        max_pending: int = MAX_PENDING_REFRESHES,
    ) -> None:
        self._reader = reader
        self._threads = threads
        self._clock = clock
        self._wall_clock = wall_clock
        self._max_entries = max_entries
        self._max_pending = max_pending
        self._entries: OrderedDict[_SpendKey, _Entry] = OrderedDict()
        # Reads running, shared by every caller of the key.
        self._reads: dict[_SpendKey, asyncio.Task[None]] = {}
        # Background refreshes not started yet, oldest first, with the finished_at seen.
        self._queued: OrderedDict[_SpendKey, int | None] = OrderedDict()
        self._refresher: asyncio.Task[None] | None = None

    @property
    def pending(self) -> int:
        """Reads queued or running."""
        return len(self._reads) + len(self._queued)

    def peek(
        self, *, workspace_id: int, run_id: str, finished_at: int | None
    ) -> CachedSpend | None:
        """What the cache holds, at once; a miss or a stale entry queues a background read.

        A list calls this for each run, so at most :data:`MAX_PENDING_REFRESHES` reads are
        pending; a run past that is read on a later call.
        """
        key = (workspace_id, run_id)
        entry = self._touch(key)
        if (
            not self._fresh(entry, finished_at)
            and key not in self._reads
            and key not in self._queued
            and self.pending < self._max_pending
            and not self._threads.closed
        ):
            self._queued[key] = finished_at
            if self._refresher is None or self._refresher.done():
                self._refresher = asyncio.get_running_loop().create_task(self._refresh_queued())
        return None if entry is None else entry.spend

    async def get(
        self,
        *,
        workspace_id: int,
        run_id: str,
        finished_at: int | None,
        wait_s: float = DETAIL_SPEND_WAIT_S,
    ) -> CachedSpend | None:
        """A fresh entry at once; otherwise wait up to ``wait_s`` for a read, then what the
        cache holds. The read starts at once, ahead of queued refreshes, and goes on in
        the background past ``wait_s``."""
        key = (workspace_id, run_id)
        entry = self._touch(key)
        if self._fresh(entry, finished_at):
            return None if entry is None else entry.spend
        read = self._reads.get(key)
        if read is None:
            self._queued.pop(key, None)
            read = self._start(key, finished_at)
        if read is not None:
            # asyncio.wait neither raises on a timeout nor cancels the read.
            await asyncio.wait({read}, timeout=wait_s)
        entry = self._touch(key)
        return None if entry is None else entry.spend

    def close(self) -> None:
        """Cancel queued and running reads; the owner closes the thread pool."""
        if self._refresher is not None:
            self._refresher.cancel()
        for read in self._reads.values():
            read.cancel()
        self._reads.clear()
        self._queued.clear()

    def _fresh(self, entry: _Entry | None, finished_at: int | None) -> bool:
        return (
            entry is not None
            and entry.finished_at == finished_at
            and entry.expires_at > self._clock()
        )

    def _touch(self, key: _SpendKey) -> _Entry | None:
        entry = self._entries.get(key)
        if entry is not None:
            self._entries.move_to_end(key)
        return entry

    async def _refresh_queued(self) -> None:
        """Run queued refreshes one at a time, leaving the other thread to the detail."""
        while self._queued:
            key, finished_at = self._queued.popitem(last=False)
            if key in self._reads or self._fresh(self._entries.get(key), finished_at):
                continue
            read = self._start(key, finished_at)
            if read is None:
                self._queued.clear()
                return
            await asyncio.wait({read})

    def _start(self, key: _SpendKey, finished_at: int | None) -> asyncio.Task[None] | None:
        if self._threads.closed:
            return None
        read = asyncio.get_running_loop().create_task(self._load(key, finished_at))
        self._reads[key] = read
        return read

    async def _load(self, key: _SpendKey, finished_at: int | None) -> None:
        workspace_id, run_id = key
        try:
            totals = await self._threads.run(
                self._reader.run_spend, workspace_id=workspace_id, run_id=run_id
            )
        except PoolClosed:
            self._reads.pop(key, None)
            return
        except Exception as exc:  # noqa: BLE001 -- logged once, shown as unknown
            previous = self._entries.get(key)
            if previous is None or not previous.failed:
                _logger.warning(
                    "Coral could not read the spend of run %s: %s",
                    run_id,
                    describe_exception(exc),
                )
            self._store(key, None, FAILED_SPEND_TTL_S, failed=True, finished_at=finished_at)
            return
        spend = None if totals is None else CachedSpend(totals, int(self._wall_clock()))
        self._store(key, spend, self._ttl_s(finished_at), failed=False, finished_at=finished_at)

    def _ttl_s(self, finished_at: int | None) -> float:
        if finished_at is None or self._wall_clock() - finished_at < FINISH_SETTLE_S:
            return UNFINISHED_SPEND_TTL_S
        return FINISHED_SPEND_TTL_S

    def _store(
        self,
        key: _SpendKey,
        spend: CachedSpend | None,
        ttl_s: float,
        *,
        failed: bool,
        finished_at: int | None,
    ) -> None:
        self._entries[key] = _Entry(spend, self._clock() + ttl_s, failed, finished_at)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        self._reads.pop(key, None)


__all__ = [
    "DETAIL_SPEND_WAIT_S",
    "FAILED_SPEND_TTL_S",
    "FINISHED_SPEND_TTL_S",
    "FINISH_SETTLE_S",
    "MAX_PENDING_REFRESHES",
    "MAX_SPEND_ENTRIES",
    "SPEND_THREADS",
    "SPEND_THREAD_NAME",
    "UNFINISHED_SPEND_TTL_S",
    "CachedSpend",
    "SpendCache",
]
