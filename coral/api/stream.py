"""
The run stream: a resumable server-sent event stream of one run's view, for its owner.

A stream sends a ``snapshot`` of the view at its head seq, then one ``entry`` per run-log
row with the row's stored view patch, so a client applying them in seq order holds the
server's view. ``Last-Event-ID`` (else ``after_seq``) resumes after the last seq a client
holds; a cursor the stream cannot replay gets a ``resync`` and a fresh snapshot. ``run``
frames carry row changes no patch shows, heartbeats keep an idle stream open, and
``data: [DONE]`` ends the stream of a finished run once every row is sent.

One :class:`RunWatcher` per workspace and run reads the run row when a commit's hook pokes
it and every poll, so other processes' commits arrive too; each stream reads its own log
rows. Reads run on the ``coral-stream`` pool. :class:`RunStreamHub` caps streams per run
and user, per user and per process, and rate-limits connects. :class:`CoralEventStream`
sends under a timeout, bounds the response's life and releases its slot however it ends.
Every stream ends after five minutes; one whose caller proved an account generation
re-checks that account every minute.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, ParamSpec, Protocol, TypeVar

import anyio
from pydantic import JsonValue
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse
from starlette.types import Message, Receive, Scope, Send

from coral.alerts.types import CallerKey, caller_key, is_owner
from coral.api.errors import CoralApiError
from coral.api.run_models import MAX_STORED_INT, entry_frame, run_header
from coral.api.run_service import server_busy
from coral.bridge.executors import BoundedThreads
from coral.bridge.service import RunRead
from coral.engine.projection import project
from coral.engine.types import JsonPatch
from coral.limits import Slot, Slots, WarnOnce
from coral.omni.protocols import Viewer
from coral.queue.run_effects import describe_exception
from coral.runview.actions import RunViewFacts
from coral.runview.patch import ViewPatchError, apply_view_patch
from coral.runview.types import (
    DONE_FRAME,
    FINISHED_RUN_STATUSES,
    HeartbeatFrame,
    ResyncFrame,
    ResyncReason,
    RunFrame,
    RunHeader,
    SnapshotFrame,
    StreamFrame,
    format_sse,
)
from coral.stores.protocols import CoralRun, RunNotFound, RunStore

_logger = logging.getLogger(__name__)

STREAM_THREADS = 8
STREAM_THREAD_NAME = "coral-stream"
# Every stream ends after this long; clients resume with Last-Event-ID, as through an
# ingress that cuts long responses.
MAX_STREAM_S = 300.0
HEARTBEAT_S = 15.0
# A stream wakes at least this often, and a watcher reads its run row this often.
POLL_S = 0.5
RECHECK_S = 60.0
SEND_TIMEOUT_S = 30.0
# A slot no response claimed is freed after this long.
RESERVATION_LAPSE_S = 10.0
# A longer backlog is answered with a snapshot instead of its rows.
REPLAY_MAX_ROWS = 1000
PAGE_ROWS = 100
MAX_STREAMS_PER_RUN_USER = 8
MAX_STREAMS_PER_USER = 32
MAX_STREAMS = 200
# Snapshot loads of one user running at once; a connect past it is refused as busy.
MAX_LOADS_PER_USER = 4
# Connects of one user to one run: a burst, then one a second.
CONNECT_BURST = 8
CONNECT_RATE_PER_S = 1.0
STREAM_RETRY_AFTER_S = 5
# A seq has at most 19 digits; a longer Last-Event-ID is not read.
MAX_LAST_EVENT_ID_CHARS = 20
_SEQ = re.compile(r"[0-9]{1,19}")
# Connect buckets kept before full ones are dropped.
_MAX_CONNECT_KEYS = 4096
_STREAM_LIMIT_TEXT = "Too many run streams are open; poll the run's log or try again shortly."
_SHUTTING_DOWN_TEXT = "The server is shutting down; poll the run's log or try again shortly."
_LOADS_BUSY_TEXT = "Too many of your run streams are starting; try again."

_P = ParamSpec("_P")
_T = TypeVar("_T")
Wait = Callable[[asyncio.Event, float], Awaitable[None]]


async def wait_for_change(event: asyncio.Event, timeout: float) -> None:
    """Wait until ``event`` is set or ``timeout`` seconds pass."""
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(timeout):
            await event.wait()


def _never_valid(_viewer: Viewer) -> bool:
    # Without a way to check an account, a proven generation cannot stay proven.
    return False


def _not_shutting_down() -> bool:
    return False


def stream_limit() -> CoralApiError:
    """The refusal for a stream past a cap or the connect rate; the client polls instead."""
    return CoralApiError(
        "stream_limit",
        _STREAM_LIMIT_TEXT,
        429,
        headers={"Retry-After": str(STREAM_RETRY_AFTER_S)},
    )


@dataclass(frozen=True)
class StreamCursor:
    """The last seq a client holds, if any; ``invalid`` for a ``Last-Event-ID`` that is none."""

    seq: int | None = None
    invalid: bool = False


def stream_cursor(last_event_id: str | None, after_seq: int | None) -> StreamCursor:
    """
    The cursor a connect names: ``Last-Event-ID`` when it is sent, else ``after_seq``.

    An empty header counts as not sent, as a browser sends none without an event id.
    """
    if last_event_id is None:
        return StreamCursor(seq=after_seq)
    if len(last_event_id) > MAX_LAST_EVENT_ID_CHARS:
        return StreamCursor(invalid=True)
    value = last_event_id.strip()
    if not value:
        return StreamCursor(seq=after_seq)
    if _SEQ.fullmatch(value) is None or int(value) > MAX_STORED_INT:
        return StreamCursor(invalid=True)
    return StreamCursor(seq=int(value))


class RunReader(Protocol):
    """The bridge's read of a run, which never writes."""

    def read(self, *, workspace_id: int, run_id: str) -> RunRead: ...


class StreamReservation:
    """
    One stream's slots under the hub's caps, released once by its response or its lapse,
    and the slot of the user's snapshot loads its opening load takes.
    """

    def __init__(self, slots: tuple[Slot, ...], *, opening_load: Slot) -> None:
        self._slots = slots
        self._opening_load: Slot | None = opening_load
        self._released = False
        self._lapse: asyncio.TimerHandle | None = None

    @property
    def released(self) -> bool:
        return self._released

    def lapse_after(self, seconds: float) -> None:
        """Release the slot after ``seconds`` unless a response claims it first."""
        self._lapse = asyncio.get_running_loop().call_later(seconds, self.release)

    def claim(self) -> None:
        """A response holds the slot now: it no longer lapses."""
        if self._lapse is not None:
            self._lapse.cancel()
            self._lapse = None

    def take_opening_load(self) -> Slot | None:
        """The opening load's slot, handed once to the load that uses it, which frees it."""
        load, self._opening_load = self._opening_load, None
        return load

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self.claim()
        load = self.take_opening_load()
        if load is not None:
            load.release()
        for slot in self._slots:
            slot.release()


class _ConnectBuckets:
    """A token bucket per key: ``burst`` connects at once, refilled at ``per_s`` a second."""

    def __init__(self, *, burst: int, per_s: float, clock: Callable[[], float]) -> None:
        self._burst = burst
        self._per_s = per_s
        self._clock = clock
        self._buckets: dict[Any, tuple[float, float]] = {}

    def take(self, key: object) -> bool:
        now = self._clock()
        tokens, at = self._buckets.get(key, (float(self._burst), now))
        tokens = min(float(self._burst), tokens + (now - at) * self._per_s)
        if tokens < 1:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1, now)
        if len(self._buckets) > _MAX_CONNECT_KEYS:
            self._drop_full(now)
        return True

    def _drop_full(self, now: float) -> None:
        # A bucket that has refilled is the same as no bucket.
        for key, (tokens, at) in list(self._buckets.items()):
            if tokens + (now - at) * self._per_s >= self._burst:
                del self._buckets[key]


class RunWatcher:
    """
    The newest row of one run its streams have seen, and a count of its changes.

    A stream notes :attr:`counter` and :attr:`changed` before it looks at :attr:`row`,
    and waits only while the counter is unchanged, so a change published before it
    waits is never missed. A row older than the one held is ignored, so a stream's
    headers never go back. The watcher reads the row when poked and every poll.
    Use it on one event loop; :meth:`poke_threadsafe` may be called from any thread.
    """

    def __init__(self, hub: RunStreamHub, workspace_id: int, run_id: str) -> None:
        self.workspace_id = workspace_id
        self.run_id = run_id
        self.row: CoralRun | None = None
        self.gone = False
        self.counter = 0
        # Replaced at each change, after the old one is set.
        self.changed = asyncio.Event()
        self.subscribers = 0
        self._hub = hub
        self._loop = asyncio.get_running_loop()
        self._poked = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._read_failed = WarnOnce()

    def offer(self, row: CoralRun) -> None:
        """Hold ``row`` when it is newer than, or as new as and unlike, the held one."""
        held = self.row
        if held is not None and (row.version < held.version or row == held):
            return
        self.row = row
        self.publish()

    def publish(self) -> None:
        """Count a change and wake every stream waiting for one."""
        self.counter += 1
        changed, self.changed = self.changed, asyncio.Event()
        changed.set()

    def poke_threadsafe(self) -> None:
        """Ask for a read of the row soon; a closed loop is ignored."""
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(self._poked.set)

    def start(self) -> None:
        self._task = self._loop.create_task(
            self._watch(), name=f"coral-run-watcher-{self.run_id[:8]}"
        )

    def stop(self) -> asyncio.Task[None] | None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
        return task

    async def _watch(self) -> None:
        hub = self._hub
        while True:
            await wait_for_change(self._poked, hub.poll_s)
            self._poked.clear()
            try:
                row = await hub.threads.run(
                    hub.run_store.get_run, self.run_id, workspace_id=self.workspace_id
                )
            except Exception as exc:  # noqa: BLE001 -- logged once, read again next poll
                if self._read_failed.first():
                    _logger.warning(
                        "Coral cannot read run %s for its streams: %s",
                        self.run_id,
                        describe_exception(exc),
                    )
                continue
            if row is not None:
                self.offer(row)
            elif not self.gone:
                self.gone = True
                self.publish()


class RunStreamHub:
    """
    Every run stream of this process: their slots, their watchers and their wake-ups.

    Slots are capped per run and user, per user and in all, and connects per user and
    run are rate-limited; caps are per process. Use it on one event loop, except
    :meth:`notify`, which a committing thread calls.
    """

    def __init__(
        self,
        *,
        bridge: RunReader,
        run_store: RunStore,
        threads: BoundedThreads,
        still_valid: Callable[[Viewer], bool] = _never_valid,
        shutting_down: Callable[[], bool] = _not_shutting_down,
        clock: Callable[[], float] = time.monotonic,
        wait: Wait = wait_for_change,
        poll_s: float = POLL_S,
        lapse_s: float = RESERVATION_LAPSE_S,
    ) -> None:
        """
        :param bridge: Loads a run's snapshot without writing.
        :param threads: The pool every stream and watcher read runs on.
        :param still_valid: Whether a caller's proven account generation is still current;
            called every minute for such a caller, off the event loop.
        :param shutting_down: Whether the server is going down; streams then end.
        :param clock: Monotonic seconds, for lifetimes, heartbeats and connect rates.
        :param wait: How a stream waits for a change, at most the given seconds.
        :param poll_s: How often a watcher reads its row and a stream wakes.
        :param lapse_s: How long a slot waits for its response to claim it.
        """
        self.bridge = bridge
        self.run_store = run_store
        self.threads = threads
        self.still_valid = still_valid
        self.shutting_down = shutting_down
        self.clock = clock
        self.wait = wait
        self.poll_s = poll_s
        self._lapse_s = lapse_s
        self._closed = False
        self._watchers: dict[tuple[int, str], RunWatcher] = {}
        # Watchers by run id alone, which the commit hook names; read on other threads.
        self._by_run: dict[str, set[RunWatcher]] = {}
        self._lock = threading.Lock()
        self._user_streams = Slots[tuple[int, CallerKey]](
            per_key=MAX_STREAMS_PER_USER, total=MAX_STREAMS
        )
        self._run_streams = Slots[tuple[int, str, CallerKey]](per_key=MAX_STREAMS_PER_RUN_USER)
        # Snapshot loads by user, each counted until its thread call ends.
        self.loads = Slots[CallerKey](per_key=MAX_LOADS_PER_USER)
        self._undecodable = WarnOnce()
        self._connects = _ConnectBuckets(
            burst=CONNECT_BURST, per_s=CONNECT_RATE_PER_S, clock=clock
        )

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def streams(self) -> int:
        """Slots held: streams open, and reserved ones no response has ended yet."""
        return self._user_streams.held

    @property
    def watchers(self) -> int:
        return len(self._watchers)

    def watcher(self, workspace_id: int, run_id: str) -> RunWatcher | None:
        return self._watchers.get((workspace_id, run_id))

    def reserve(self, viewer: Viewer, workspace_id: int, run_id: str) -> StreamReservation:
        """
        A slot for one stream of ``viewer``'s on the run, which lapses unless a response
        claims it, with a slot of the user's snapshot loads for its opening load.

        :raises CoralApiError: 503 ``server_busy`` while the server shuts down, once the
            hub is closed, or while the user has :data:`MAX_LOADS_PER_USER` loads running;
            429 ``stream_limit`` past a cap or the connect rate.
        """
        if self._closed or self.shutting_down():
            raise server_busy(_SHUTTING_DOWN_TEXT, retry_after_s=STREAM_RETRY_AFTER_S)
        caller = caller_key(viewer)
        user, run_user = (workspace_id, caller), (workspace_id, run_id, caller)
        if self._user_streams.full(user) or self._run_streams.full(run_user):
            _logger.debug("Coral refused a run stream: %d open", self.streams)
            raise stream_limit()
        if self.loads.full(caller):
            _logger.debug("Coral refused a run stream: the caller's loads are running")
            raise server_busy(_LOADS_BUSY_TEXT)
        if not self._connects.take(run_user):
            raise stream_limit()
        reservation = StreamReservation(
            (self._user_streams.take(user), self._run_streams.take(run_user)),
            opening_load=self.loads.take(caller),
        )
        reservation.lapse_after(self._lapse_s)
        return reservation

    def note_undecodable(self, run_id: str, exc: Exception) -> None:
        """A run row holds a code this server does not know: logged once, then at debug."""
        _logger.log(
            self._undecodable.level(),
            "Coral ended a stream of run %s: its row holds a code this server cannot read: %s",
            run_id,
            describe_exception(exc),
        )

    def stream(
        self,
        viewer: Viewer,
        workspace_id: int,
        run_id: str,
        *,
        cursor: StreamCursor,
        is_disconnected: Callable[[], Awaitable[bool]],
        reservation: StreamReservation | None = None,
    ) -> RunStream:
        """
        A stream of the run for ``viewer``, who must own it; nothing is read until it runs.

        :param reservation: The stream's slots; its opening load takes the reservation's
            load slot.
        """
        return RunStream(
            self,
            viewer,
            workspace_id,
            run_id,
            cursor=cursor,
            is_disconnected=is_disconnected,
            reservation=reservation,
        )

    def notify(self, run_id: str, version: int) -> None:
        """
        A commit's hook: wake the watchers of ``run_id`` in every workspace, since the
        hook names none. Called on the committing thread.
        """
        del version
        with self._lock:
            watchers = tuple(self._by_run.get(run_id, ()))
        for watcher in watchers:
            watcher.poke_threadsafe()

    def subscribe(self, workspace_id: int, run_id: str) -> RunWatcher:
        key = (workspace_id, run_id)
        watcher = self._watchers.get(key)
        if watcher is None:
            watcher = RunWatcher(self, workspace_id, run_id)
            self._watchers[key] = watcher
            with self._lock:
                self._by_run.setdefault(run_id, set()).add(watcher)
            watcher.start()
        watcher.subscribers += 1
        return watcher

    def unsubscribe(self, watcher: RunWatcher) -> None:
        watcher.subscribers -= 1
        if watcher.subscribers > 0:
            return
        self._watchers.pop((watcher.workspace_id, watcher.run_id), None)
        with self._lock:
            others = self._by_run.get(watcher.run_id)
            if others is not None:
                others.discard(watcher)
                if not others:
                    del self._by_run[watcher.run_id]
        watcher.stop()

    async def close(self) -> None:
        """End every stream at its next wake-up, which this causes, and stop the watchers."""
        self._closed = True
        tasks = []
        for watcher in list(self._watchers.values()):
            watcher.publish()
            task = watcher.stop()
            if task is not None:
                tasks.append(task)
        await asyncio.gather(*tasks, return_exceptions=True)


class _Ended(Exception):
    """The stream ends here, without ``[DONE]``; the client resumes from its last seq."""


class _UndecodableRun(Exception):
    """The run row holds a status or pause-reason code this server does not know."""


@dataclass(frozen=True)
class _Opened:
    """
    A fresh load of the run and the frames that open on it, built on the pool.

    :param view: The stream's own copy of the view at ``head``; ``None`` when the run
        cannot be loaded.
    :param position: The last seq the client holds once ``events`` are sent.
    :param events: The opening frames as server-sent events.
    """

    run: CoralRun
    head: int
    view: dict[str, JsonValue] | None
    header: RunHeader
    position: int
    events: tuple[str, ...]


@dataclass(frozen=True)
class _PageRow:
    """
    One log row as the stream sends it, built on the pool; the body is not kept.

    :param patch: The row's view patch; ``None`` with ``event`` for a row that cannot be
        read.
    """

    seq: int
    run_version: int
    patch: tuple[JsonPatch, ...] | None
    event: str | None


def _resync_reason(cursor: StreamCursor, head: int) -> ResyncReason | None:
    if cursor.invalid:
        return "cursor_invalid"
    if cursor.seq is None:
        return None
    if cursor.seq > head:
        return "cursor_unknown"
    if head - cursor.seq > REPLAY_MAX_ROWS:
        return "replay_too_long"
    return None


def _header_of(run: CoralRun, view: RunViewFacts | None) -> RunHeader:
    try:
        return run_header(run, view)
    except ValueError as exc:
        raise _UndecodableRun(str(exc)) from None


class RunStream:
    """
    One client's stream of one run: one loop sends the replay and then the live rows.

    It keeps its own copy of the view at its snapshot's seq and applies only the rows
    above it: rows from the cursor up to the snapshot are sent but already in the copy.
    Reads, projections and frame encoding run on the stream pool.
    """

    def __init__(
        self,
        hub: RunStreamHub,
        viewer: Viewer,
        workspace_id: int,
        run_id: str,
        *,
        cursor: StreamCursor,
        is_disconnected: Callable[[], Awaitable[bool]],
        reservation: StreamReservation | None = None,
    ) -> None:
        self._hub = hub
        self._viewer = viewer
        self._workspace_id = workspace_id
        self._run_id = run_id
        self._cursor = cursor
        self._is_disconnected = is_disconnected
        self._reservation = reservation
        self._view: dict[str, JsonValue] | None = None
        self._facts: tuple[Mapping[str, JsonValue], RunViewFacts] | None = None
        self._snapshot_seq = 0
        self._position = 0
        self._sent: RunHeader | None = None
        # The newest run version among the entries sent.
        self._rows_version = 0
        self._started = self._last_frame = self._recheck_at = 0.0

    @property
    def view(self) -> dict[str, JsonValue] | None:
        """The stream's own copy of the run's view, as of the last entry it sent."""
        return self._view

    async def frames(self) -> AsyncIterator[str]:
        """
        The stream's events, each one whole ``text/event-stream`` event.

        It ends after ``data: [DONE]`` once the run is finished and every row is sent,
        or without it when the stream's time is up, its caller lost access, the request
        went away, the server is closing, a read failed or the run row holds a code this
        server cannot read.
        """
        hub = self._hub
        watcher = hub.subscribe(self._workspace_id, self._run_id)
        self._started = self._last_frame = hub.clock()
        self._recheck_at = self._started + RECHECK_S
        try:
            for event in (await self._load(watcher, self._cursor)).events:
                yield self._sent_event(event)
            while True:
                seen, changed = watcher.counter, watcher.changed
                row = await self._checked(watcher)
                if self._position < row.next_log_seq - 1:
                    page = await self._call(self._read_page, self._position)
                    resynced = False
                    for page_row in page:
                        if not self._advance(page_row):
                            # Past the row at a fresh head, so no reconnect meets it again.
                            yield self._send(ResyncFrame(reason="row_unreadable"))
                            for event in (await self._load(watcher, StreamCursor())).events:
                                yield self._sent_event(event)
                            resynced = True
                            break
                        assert page_row.event is not None
                        yield self._sent_event(page_row.event)
                    if resynced or len(page) >= PAGE_ROWS:
                        # Drain before waiting.
                        continue
                header = self._header(row)
                if header is not None:
                    yield self._send(RunFrame(**dict(header)))
                if self._finished_and_sent(row):
                    yield DONE_FRAME
                    return
                if hub.clock() - self._last_frame >= HEARTBEAT_S:
                    yield self._send(HeartbeatFrame())
                if watcher.counter == seen:
                    await hub.wait(changed, self._timeout())
        except _Ended:
            return
        finally:
            hub.unsubscribe(watcher)

    def _send(self, frame: StreamFrame) -> str:
        return self._sent_event(format_sse(frame))

    def _sent_event(self, event: str) -> str:
        self._last_frame = self._hub.clock()
        return event

    def _header(self, row: CoralRun) -> RunHeader | None:
        """
        The row's header when it is news: it differs from the last one sent in more than
        its version, and is as new as every entry sent, so a header never goes back.

        Live headers wait until the stream holds the row's head. The opening header of a
        replay is the exception: it is the header at the snapshot head, sent before the
        rows from the cursor up to that head.

        :raises _Ended: the row holds a code this server cannot read.
        """
        sent = self._sent
        assert sent is not None
        if self._position < row.next_log_seq - 1:
            return None
        try:
            header = _header_of(row, self._view_facts())
        except _UndecodableRun as exc:
            self._hub.note_undecodable(self._run_id, exc)
            raise _Ended from None
        if header.version < max(sent.version, self._rows_version):
            return None
        if header.model_copy(update={"version": sent.version}) == sent:
            return None
        self._sent = header
        return header

    def _finished_and_sent(self, row: CoralRun) -> bool:
        """The client was told the run finished, and holds every row of the row's head."""
        assert self._sent is not None
        return (
            self._sent.status in FINISHED_RUN_STATUSES and self._position >= row.next_log_seq - 1
        )

    def _view_facts(self) -> RunViewFacts | None:
        view = self._view
        if view is None:
            return None
        if self._facts is None or self._facts[0] is not view:
            self._facts = (view, RunViewFacts.of(view))
        return self._facts[1]

    def _advance(self, page_row: _PageRow) -> bool:
        """
        Move the stream's view and position past the row; ``False`` for a row that cannot
        be read or whose patch does not apply, which needs a fresh snapshot.
        """
        if page_row.patch is None:
            _logger.warning(
                "Coral resyncs a stream of run %s: log row %d cannot be read",
                self._run_id,
                page_row.seq,
            )
            return False
        if page_row.seq > self._snapshot_seq and self._view is not None and page_row.patch:
            try:
                self._view = apply_view_patch(self._view, page_row.patch)
            except ViewPatchError as exc:
                _logger.warning(
                    "Coral resyncs a stream of run %s: the patch of row %d does not apply: %s",
                    self._run_id,
                    page_row.seq,
                    describe_exception(exc),
                )
                return False
        self._position = page_row.seq
        self._rows_version = max(self._rows_version, page_row.run_version)
        return True

    async def _load(self, watcher: RunWatcher, cursor: StreamCursor) -> _Opened:
        """
        A fresh load of the run and its opening frames; the stream's view, snapshot seq
        and position come from it.

        :raises _Ended: the loaded row is no longer the caller's, or holds a code this
            server cannot read.
        """
        opening = None if self._reservation is None else self._reservation.take_opening_load()
        load = opening or self._hub.loads.take(caller_key(self._viewer))
        call = asyncio.get_running_loop().create_task(self._hub.threads.run(self._open, cursor))
        # A stream that goes away leaves the load running, and counted, until its thread ends.
        load.release_when_done(call)
        opened = await self._mapped(asyncio.shield(call))
        run = opened.run
        if not is_owner(run.user_id, run.account_generation, self._viewer):
            raise _Ended
        watcher.offer(run)
        self._snapshot_seq = opened.head
        self._view = opened.view
        self._sent = opened.header
        self._position = opened.position
        return opened

    def _open(self, cursor: StreamCursor) -> _Opened:
        """On the pool: read the run, project it, and build the frames that open on it."""
        read = self._hub.bridge.read(workspace_id=self._workspace_id, run_id=self._run_id)
        run, head = read.run, read.run.next_log_seq - 1
        view = None if read.snapshot is None else project(read.snapshot.state)
        header = _header_of(run, None if view is None else RunViewFacts.of(view))
        view_json = None if view is None else view.model_dump(mode="json")
        resync = _resync_reason(cursor, head)
        if cursor.seq is not None and resync is None:
            event = format_sse(RunFrame(**dict(header)))
            return _Opened(run, head, view_json, header, cursor.seq, (event,))
        snapshot = SnapshotFrame(
            seq=head,
            run_version=run.version,
            log_version=run.log_version,
            run=header,
            view=view,
            view_error=None if view is not None else "engine.load_failed",
        )
        events = (format_sse(snapshot),)
        if resync is not None:
            events = (format_sse(ResyncFrame(reason=resync)), *events)
        return _Opened(run, head, view_json, header, head, events)

    def _read_page(self, after_seq: int) -> list[_PageRow]:
        """On the pool: the next page of rows after ``after_seq``, encoded as entries."""
        rows = self._hub.run_store.read_log(
            self._run_id,
            workspace_id=self._workspace_id,
            after_seq=after_seq,
            limit=PAGE_ROWS,
            tolerant=True,
        )
        page: list[_PageRow] = []
        for row in rows:
            entry = entry_frame(row)
            page.append(
                _PageRow(
                    seq=row.seq,
                    run_version=row.run_version,
                    patch=None if entry is None else entry.patch,
                    event=None if entry is None else format_sse(entry),
                )
            )
        return page

    async def _checked(self, watcher: RunWatcher) -> CoralRun:
        """
        The watcher's row, once the stream may go on.

        :raises _Ended: the hub closed, the server is going down, the stream's time is
            up, the request went away, the run is gone or no longer the caller's, or the
            caller's account failed its re-check.
        """
        hub = self._hub
        now = hub.clock()
        if hub.closed or hub.shutting_down() or now - self._started >= MAX_STREAM_S:
            raise _Ended
        if await self._is_disconnected():
            raise _Ended
        row = watcher.row
        if watcher.gone or row is None:
            raise _Ended
        if not is_owner(row.user_id, row.account_generation, self._viewer):
            raise _Ended
        if self._viewer.check_generation and now >= self._recheck_at:
            if not await self._still_valid():
                raise _Ended
            self._recheck_at = now + RECHECK_S
        return row

    async def _still_valid(self) -> bool:
        try:
            return bool(await self._hub.threads.run(self._hub.still_valid, self._viewer))
        except Exception as exc:  # noqa: BLE001 -- a check that fails ends the stream
            _logger.warning(
                "Coral ended a stream of run %s: its account check failed: %s",
                self._run_id,
                describe_exception(exc),
            )
            return False

    def _timeout(self) -> float:
        """Until the next poll, heartbeat, end of life or re-check, whichever is first."""
        now = self._hub.clock()
        deadlines = [self._last_frame + HEARTBEAT_S, self._started + MAX_STREAM_S]
        if self._viewer.check_generation:
            deadlines.append(self._recheck_at)
        return max(0.0, min(self._hub.poll_s, *(deadline - now for deadline in deadlines)))

    async def _call(self, fn: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """``fn`` on the stream pool; a failure ends the stream."""
        return await self._mapped(self._hub.threads.run(fn, *args, **kwargs))

    async def _mapped(self, pending: Awaitable[_T]) -> _T:
        """The result of a pool call; a failure ends the stream."""
        try:
            return await pending
        except RunNotFound:
            raise _Ended from None
        except _UndecodableRun as exc:
            self._hub.note_undecodable(self._run_id, exc)
            raise _Ended from None
        except Exception as exc:  # noqa: BLE001 -- logged, then the stream ends
            level = logging.DEBUG if self._hub.threads.closed else logging.WARNING
            _logger.log(
                level, "Coral ended a stream of run %s: %s", self._run_id, describe_exception(exc)
            )
            raise _Ended from None


class CoralEventStream(StreamingResponse):
    """
    A ``text/event-stream`` response that never pins its stream's slot.

    Starlette awaits each send with no timeout and never closes the body iterator, so
    this response does both: a send that waits past ``send_timeout_s`` (a client that
    stopped reading) ends it, the whole response is cut after ``max_s`` (a backstop to
    the stream's own lifetime), and however it ends the body is closed and the
    reservation released.
    """

    media_type = "text/event-stream"

    def __init__(
        self,
        content: AsyncIterator[str],
        *,
        reservation: StreamReservation,
        headers: Mapping[str, str] | None = None,
        send_timeout_s: float = SEND_TIMEOUT_S,
        max_s: float = MAX_STREAM_S + SEND_TIMEOUT_S,
    ) -> None:
        super().__init__(content, headers=headers, media_type=self.media_type)
        self._reservation = reservation
        self._send_timeout_s = send_timeout_s
        self._max_s = max_s

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self._reservation.claim()
        send_timeout_s = self._send_timeout_s

        async def timed_send(message: Message) -> None:
            with anyio.fail_after(send_timeout_s):
                await send(message)

        try:
            with anyio.move_on_after(self._max_s):
                await super().__call__(scope, receive, timed_send)
        except (TimeoutError, ClientDisconnect):
            # Starlette reports a send that timed out as a disconnect on newer servers.
            _logger.debug("Coral ended a run stream whose client stopped reading")
        finally:
            try:
                with anyio.CancelScope(shield=True):
                    await self._close_body()
            finally:
                self._reservation.release()

    async def _close_body(self) -> None:
        close = getattr(self.body_iterator, "aclose", None)
        if close is None:
            return
        try:
            await close()
        except Exception as exc:  # noqa: BLE001 -- closing must not hide how the stream ended
            _logger.debug("Coral could not close a run stream: %s", describe_exception(exc))


__all__ = [
    "CONNECT_BURST",
    "CONNECT_RATE_PER_S",
    "HEARTBEAT_S",
    "MAX_LAST_EVENT_ID_CHARS",
    "MAX_LOADS_PER_USER",
    "MAX_STREAMS",
    "MAX_STREAMS_PER_RUN_USER",
    "MAX_STREAMS_PER_USER",
    "MAX_STREAM_S",
    "PAGE_ROWS",
    "POLL_S",
    "RECHECK_S",
    "REPLAY_MAX_ROWS",
    "RESERVATION_LAPSE_S",
    "SEND_TIMEOUT_S",
    "STREAM_RETRY_AFTER_S",
    "STREAM_THREADS",
    "STREAM_THREAD_NAME",
    "CoralEventStream",
    "RunReader",
    "RunStream",
    "RunStreamHub",
    "RunWatcher",
    "StreamCursor",
    "StreamReservation",
    "Wait",
    "stream_cursor",
    "stream_limit",
    "wait_for_change",
]
