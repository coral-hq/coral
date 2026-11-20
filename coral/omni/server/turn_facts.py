"""Status edges of bound engine sessions become durable ``turn_fact`` signals, off the hot path.

Omnigent hands every published edge to :meth:`TurnFactRecorder.observe` on the
publishing thread. An edge of a session no engine slot holds costs one dict read;
an edge that can end a bound turn is handed to one worker thread through a bounded
queue, which writes the signal row. The observer never blocks, never raises and
never does I/O. An edge lost to a full queue or a store outage is recovered by the
run's next re-gather. :class:`BoundSessionRefresher` rebuilds the index every minute.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import queue
import threading
import time
from collections.abc import Awaitable, Callable

from coral.bridge.bound_sessions import (
    BoundSession,
    BoundSessions,
    BoundSessionSource,
    SessionKey,
)
from coral.bridge.config import BOUND_SESSIONS_REFRESH_S
from coral.bridge.mapping import edge_signal_key, turn_signal_draft
from coral.queue.run_effects import describe_exception
from coral.signals.turn_facts import EdgeFacts, is_archive_origin
from coral.stores.protocols import QueueStore
from omnigent.server.session_live_state import SessionStatusEdge

_logger = logging.getLogger(__name__)

# The S1 observer name the recorder registers under.
TURN_FACTS_OBSERVER = "coral.turn_facts"
# Edges waiting for the worker; more are dropped and counted.
MAX_PENDING_EDGES = 1_024
# Edges one session may have waiting, so a session that publishes fast cannot fill the
# queue for every other run; its own later edges wait for the re-gather.
MAX_PENDING_PER_SESSION = 16
# Store attempts after the first before an edge is dropped.
WRITE_RETRIES = 2
WRITE_RETRY_DELAY_S = 0.1
# Bindings read per page while the index is rebuilt.
REFRESH_PAGE = 500
_TURN_END_STATUSES = frozenset({"idle", "failed"})
# An edge to record, or ``None`` to stop the worker.
_Pending = tuple[SessionStatusEdge, BoundSession] | None


def ends_turn(edge: SessionStatusEdge, bound: BoundSession) -> bool:
    """
    Whether the edge can end the bound session's turn.

    An orchestrator's counts only when it failed, or when an archive published it.
    """
    if bound.orchestrator:
        failed = edge.status == "failed" or edge.turn_outcome == "failed"
        return failed or is_archive_origin(edge.origin)
    return edge.turn_outcome is not None or edge.status in _TURN_END_STATUSES


class TurnFactRecorder:
    """
    The S1 observer that records turn ends of bound sessions as ``turn_fact`` signals.

    :param clock: Epoch seconds; a signal is due when it is written.
    :param max_pending_per_session: Edges of one session waiting at once; more are
        dropped and counted in ``dropped_busy``.
    :param sleep: Waits between store attempts, on the worker thread.
    """

    def __init__(
        self,
        index: BoundSessions,
        queue_store: QueueStore,
        *,
        clock: Callable[[], float] = time.time,
        max_pending: int = MAX_PENDING_EDGES,
        max_pending_per_session: int = MAX_PENDING_PER_SESSION,
        retries: int = WRITE_RETRIES,
        retry_delay_s: float = WRITE_RETRY_DELAY_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._index = index
        self._queue_store = queue_store
        self._clock = clock
        self._retries = retries
        self._retry_delay_s = retry_delay_s
        self._sleep = sleep
        self._pending: queue.Queue[_Pending] = queue.Queue(maxsize=max_pending)
        self._max_per_session = max_pending_per_session
        self._per_session: dict[SessionKey, int] = {}
        self._per_session_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._closed = False
        self._observer_failed = False
        # Set once the worker has left: an edge handed off later is dropped at once.
        self._stopped = False
        self._stop_lock = threading.Lock()
        self.written = 0
        self.dropped_full = 0
        self.dropped_busy = 0
        self.dropped_failed = 0

    @property
    def closed(self) -> bool:
        return self._closed

    def start(self) -> None:
        """Start the one worker thread that writes the signals."""
        if self._worker is not None:
            return
        self._worker = threading.Thread(target=self._work, name="coral-turn-facts", daemon=True)
        self._worker.start()

    def observe(self, edge: SessionStatusEdge) -> None:
        """The S1 observer: one dict read, then at most a non-blocking hand-off."""
        try:
            bound = self._index.lookup(edge.workspace_id, edge.session_id)
            if bound is None or self._closed or not ends_turn(edge, bound):
                return
            key = (edge.workspace_id, edge.session_id)
            if not self._take(key):
                self.dropped_busy += 1
                _log_every_hundredth(self.dropped_busy, "one session has too many edges waiting")
                return
            try:
                self._pending.put_nowait((edge, bound))
            except queue.Full:
                self._release(key)
                self.dropped_full += 1
                _log_every_hundredth(self.dropped_full, "the turn-fact queue is full")
                return
            if self._closed:
                # A close raced this hand-off: no worker may be left to take the edge.
                with self._stop_lock:
                    if self._stopped:
                        self._drop_pending()
        except Exception:  # an observer bug must not break the publish
            # One traceback; repeats go to debug.
            first, self._observer_failed = not self._observer_failed, True
            if first:
                _logger.warning("Coral turn-fact observer failed", exc_info=True)
            else:
                _logger.debug("Coral turn-fact observer failed again")

    def _take(self, key: SessionKey) -> bool:
        """Count one more waiting edge of the session; ``False`` when it has too many."""
        with self._per_session_lock:
            waiting = self._per_session.get(key, 0)
            if waiting >= self._max_per_session:
                return False
            self._per_session[key] = waiting + 1
            return True

    def _release(self, key: SessionKey) -> None:
        with self._per_session_lock:
            waiting = self._per_session.get(key, 0) - 1
            if waiting > 0:
                self._per_session[key] = waiting
            else:
                self._per_session.pop(key, None)

    def wait_idle(self) -> None:
        """Block until every edge handed off so far is written or dropped."""
        self._pending.join()

    def close(self, *, timeout_s: float = 2.0) -> None:
        """Take no more edges and stop the worker; edges still queued are dropped."""
        self._closed = True
        worker = self._worker
        if worker is None:
            with self._stop_lock:
                self._stopped = True
                self._drop_pending()
            return
        while True:
            try:
                self._pending.put_nowait(None)
                break
            except queue.Full:
                # Make room for the stop: the queued edges are dropped anyway.
                self._drop_pending(limit=1)
        worker.join(timeout_s)

    def _drop_pending(self, *, limit: int | None = None) -> None:
        """Take queued edges off the queue unwritten, all of them or ``limit``."""
        dropped = 0
        while limit is None or dropped < limit:
            try:
                item = self._pending.get_nowait()
            except queue.Empty:
                return
            if item is not None:
                self._release((item[0].workspace_id, item[0].session_id))
            self._pending.task_done()
            dropped += 1

    def _work(self) -> None:
        while True:
            item = self._pending.get()
            try:
                if item is None:
                    with self._stop_lock:
                        self._stopped = True
                        self._drop_pending()
                    return
                if not self._closed:
                    self._record(*item)
            except Exception as exc:  # noqa: BLE001 -- the worker outlives one bad edge
                self.dropped_failed += 1
                _logger.warning("Coral could not record a turn end: %s", describe_exception(exc))
            finally:
                if item is not None:
                    self._release((item[0].workspace_id, item[0].session_id))
                self._pending.task_done()

    def _record(self, edge: SessionStatusEdge, bound: BoundSession) -> None:
        facts = EdgeFacts.from_edge(dataclasses.asdict(edge))
        now = int(self._clock())
        draft = turn_signal_draft(
            run_id=bound.run_id,
            session_id=edge.session_id,
            engine_slot_id=bound.engine_slot_id,
            generation=bound.generation,
            idempotency_key=edge_signal_key(edge.session_id, facts),
            edge=facts,
            available_at=now,
        )
        for attempt in range(self._retries + 1):
            try:
                self._queue_store.enqueue_work([draft], workspace_id=edge.workspace_id, now=now)
            except Exception as exc:  # noqa: BLE001 -- retried, then dropped for the re-gather
                if attempt < self._retries:
                    self._sleep(self._retry_delay_s * (attempt + 1))
                    continue
                self.dropped_failed += 1
                _logger.warning(
                    "Coral could not record a turn end of run %s; its re-gather recovers it: %s",
                    bound.run_id,
                    describe_exception(exc),
                )
                return
            self.written += 1
            return


def _log_every_hundredth(dropped: int, why: str) -> None:
    if dropped == 1 or dropped % 100 == 0:
        _logger.warning("Coral dropped a turn end (%s); %d dropped so far", why, dropped)


class BoundSessionRefresher:
    """
    Rebuilds the bound-session index from the binding store, at start and every minute.

    Every process runs one, leader or not: each replica records its own edges.
    """

    def __init__(
        self,
        source: BoundSessionSource,
        index: BoundSessions,
        *,
        interval_s: float = BOUND_SESSIONS_REFRESH_S,
        page_size: int = REFRESH_PAGE,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._source = source
        self._index = index
        self._interval_s = interval_s
        self._page_size = page_size
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    @property
    def stopped(self) -> bool:
        return self._stopped

    def refresh(self) -> int:
        """Rebuild the index in one paged read; returns how many sessions it holds."""
        since = self._index.begin_rebuild()
        try:
            entries = self._read()
        except BaseException:
            self._index.abandon_rebuild()
            raise
        self._index.replace(entries, since=since)
        return len(entries)

    def _read(self) -> dict[SessionKey, BoundSession]:
        entries: dict[SessionKey, BoundSession] = {}
        cursor: tuple[int, str] | None = None
        while True:
            page = self._source.list_bound_sessions(cursor=cursor, limit=self._page_size)
            for binding in page:
                bound = BoundSession.from_binding(binding)
                if bound is not None:
                    entries[(binding.workspace_id, binding.session_id)] = bound
            if len(page) < self._page_size:
                return entries
            cursor = (page[-1].workspace_id, page[-1].session_id)

    async def start(self) -> None:
        """Fill the index once, then keep rebuilding it in the background."""
        await self._refresh_logged()
        self._task = asyncio.create_task(self._loop(), name="coral-bound-sessions")

    async def stop(self) -> None:
        self._stopped = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _loop(self) -> None:
        while True:
            await self._sleep(self._interval_s)
            await self._refresh_logged()

    async def _refresh_logged(self) -> None:
        try:
            await asyncio.to_thread(self.refresh)
        except Exception as exc:  # noqa: BLE001 -- the next interval retries
            _logger.warning(
                "Coral could not rebuild its bound-session index: %s", describe_exception(exc)
            )


__all__ = [
    "MAX_PENDING_EDGES",
    "TURN_FACTS_OBSERVER",
    "BoundSessionRefresher",
    "TurnFactRecorder",
    "ends_turn",
]
