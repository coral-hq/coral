"""The runs API: owner-only run reads on their own bounded thread pool, fair between users.

Every call names a run through :meth:`RunsApi.owned_run` first: the id's format, the
row and its owner, before any load, log, graph or spend read, so a run the caller may
not see is one fixed 404 that did no other work. Blocking store and bridge calls run
on the ``coral-api`` pool through :class:`InFlight`, which admits one call per thread
and at most half of them per user, and gives each one 30 seconds.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, NoReturn, ParamSpec, Protocol, TypeVar

from coral.alerts.types import is_owner, normalize_owner
from coral.api.errors import CoralApiError, run_not_found
from coral.api.run_models import (
    RUN_ID,
    LogPage,
    RunDetail,
    RunPage,
    format_run_cursor,
    invalid_run_cursor,
    list_item_actions,
    log_page,
    run_detail,
    run_spend,
    run_summary,
)
from coral.api.spend import DETAIL_SPEND_WAIT_S, SpendCache
from coral.bridge.executors import BoundedThreads, PoolClosed
from coral.bridge.graphs import PinnedGraphError
from coral.bridge.service import RunRead
from coral.db.enum_codecs import encode_run_status
from coral.model.ir import CompiledGraph
from coral.omni.protocols import Viewer
from coral.queue.run_effects import describe_exception
from coral.runview.types import RunStatusName
from coral.stores.protocols import CoralRun, InvalidRunCursor, RunNotFound, RunStore

_logger = logging.getLogger(__name__)

# Calls in flight at once for one user; each waits this long.
MAX_API_CALLS_PER_USER = 8
API_CALL_TIMEOUT_S = 30.0
# Twice one user's share, so one user's slow calls never hold every thread. The
# process admits one call per thread, so an admitted call never queues for one.
API_THREADS = 2 * MAX_API_CALLS_PER_USER
MAX_API_CALLS = API_THREADS
API_THREAD_NAME = "coral-api"
BUSY_RETRY_AFTER_S = 1
_BUSY_TEXT = "The server is busy; try again."
_GRAPH_UNREADABLE_TEXT = "The run's workflow graph cannot be read."

_P = ParamSpec("_P")
_T = TypeVar("_T")
# A caller's share of the calls in flight: its normalized owner id and generation.
_CallerKey = tuple[str | None, str | None]


def server_busy() -> CoralApiError:
    """The refusal for a call the pool cannot take now; the caller retries."""
    return CoralApiError(
        "server_busy", _BUSY_TEXT, 503, headers={"Retry-After": str(BUSY_RETRY_AFTER_S)}
    )


def _caller_key(viewer: Viewer) -> _CallerKey:
    return normalize_owner(viewer.user_id), viewer.account_generation


class InFlight:
    """
    Runs blocking calls on a bounded pool, at most so many in flight in all and per user.

    A call past the limits is refused at once as busy. One that runs past its timeout
    is refused as busy too, but keeps its slot until its thread finishes, so work that
    timed out still counts against the pool. Use it on one event loop.
    """

    def __init__(
        self,
        threads: BoundedThreads,
        *,
        max_calls: int | None = None,
        max_per_caller: int = MAX_API_CALLS_PER_USER,
        timeout_s: float = API_CALL_TIMEOUT_S,
    ) -> None:
        """:param max_calls: Calls in flight in all; one per thread when not given, so a
        full pool refuses at once instead of queueing a call until its timeout."""
        self._threads = threads
        self._max_calls = threads.max_workers if max_calls is None else max_calls
        self._max_per_caller = max_per_caller
        self._timeout_s = timeout_s
        self._by_caller: dict[_CallerKey, int] = {}
        # Calls whose threads still run, held so none is collected before it ends.
        self._calls: set[asyncio.Task[Any]] = set()

    @property
    def in_flight(self) -> int:
        """Calls holding a slot: running, waiting for a thread, or timed out but running."""
        return len(self._calls)

    @property
    def closed(self) -> bool:
        return self._threads.closed

    async def run(
        self, viewer: Viewer, fn: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs
    ) -> _T:
        """
        ``fn(*args, **kwargs)`` on the pool for ``viewer``.

        :raises CoralApiError: 503 ``server_busy`` when the pool is closed or full, the
            caller has its share in flight, or the call runs past its timeout.
        """
        key = _caller_key(viewer)
        held = self._by_caller.get(key, 0)
        if self._threads.closed or len(self._calls) >= self._max_calls:
            raise server_busy()
        if held >= self._max_per_caller:
            _logger.debug("Coral refused a runs-API call: the caller has %d in flight", held)
            raise server_busy()
        self._by_caller[key] = held + 1
        call = asyncio.get_running_loop().create_task(self._threads.run(fn, *args, **kwargs))
        self._calls.add(call)
        call.add_done_callback(partial(self._finished, key))
        # asyncio.wait neither raises on a timeout nor cancels the call.
        done, _pending = await asyncio.wait({call}, timeout=self._timeout_s)
        if not done:
            _logger.warning("Coral refused a runs-API call: it ran past %.0f s", self._timeout_s)
            raise server_busy()
        try:
            return call.result()
        except PoolClosed:
            raise server_busy() from None
        except RuntimeError:
            # A pool that closed before the call was submitted refuses it.
            if self._threads.closed:
                raise server_busy() from None
            raise

    def _finished(self, key: _CallerKey, call: asyncio.Task[Any]) -> None:
        self._calls.discard(call)
        held = self._by_caller.get(key, 0) - 1
        if held > 0:
            self._by_caller[key] = held
        else:
            self._by_caller.pop(key, None)
        # Marks an error seen even when the request gave up before reading it.
        if not call.cancelled():
            call.exception()


class RunReads(Protocol):
    """The bridge's reads the runs API uses; neither ever writes."""

    def read(self, *, workspace_id: int, run_id: str) -> RunRead: ...

    def pinned_graph(self, *, workspace_id: int, version_id: str) -> CompiledGraph: ...


@dataclass(frozen=True)
class GraphRead:
    """A run's pinned graph and its entity tag; ``graph`` is ``None`` when not modified."""

    etag: str
    graph: CompiledGraph | None


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    if if_none_match is None:
        return False
    tags = {tag.strip().removeprefix("W/") for tag in if_none_match.split(",")}
    return "*" in tags or etag in tags


class RunsApi:
    """The owner's run reads; safe to share between requests on one event loop."""

    def __init__(
        self,
        *,
        bridge: RunReads,
        run_store: RunStore,
        spend: SpendCache,
        in_flight: InFlight,
    ) -> None:
        """
        :param bridge: Loads runs without writing, and their pinned graphs.
        :param spend: Run spend, read only after the owner check.
        :param in_flight: Runs every store and bridge call.
        """
        self._bridge = bridge
        self._runs = run_store
        self._spend = spend
        self._in_flight = in_flight
        # The first unreadable pinned graph is a warning; later ones go to debug.
        self._graph_warned = False

    @property
    def in_flight(self) -> InFlight:
        return self._in_flight

    async def owned_run(self, viewer: Viewer, workspace_id: int, run_id: str) -> CoralRun:
        """
        The caller's run, checked before any other work.

        :raises CoralApiError: the fixed run 404 for a malformed id, an unknown run or
            another owner's.
        """
        if not RUN_ID.fullmatch(run_id):
            raise run_not_found()
        run = await self._in_flight.run(
            viewer, self._runs.get_run, run_id, workspace_id=workspace_id
        )
        if run is None or not is_owner(run.user_id, run.account_generation, viewer):
            raise run_not_found()
        return run

    async def list_runs(
        self,
        viewer: Viewer,
        workspace_id: int,
        *,
        statuses: Sequence[RunStatusName],
        workflow_id: str | None,
        after: tuple[int, str] | None,
        limit: int,
    ) -> RunPage:
        """The caller's runs, newest first, with cached spend only."""
        codes = list(dict.fromkeys(encode_run_status(status) for status in statuses))
        try:
            runs, cursor = await self._in_flight.run(
                viewer,
                self._runs.list_owned_runs,
                workspace_id=workspace_id,
                viewer=viewer,
                statuses=codes,
                workflow_id=workflow_id,
                after=after,
                limit=limit,
            )
        except InvalidRunCursor:
            raise invalid_run_cursor() from None
        items = tuple(
            run_summary(
                run,
                actions=list_item_actions(run),
                spend=self._spend.peek(
                    workspace_id=workspace_id, run_id=run.id, finished_at=run.finished_at
                ),
            )
            for run in runs
        )
        return RunPage(data=items, next_cursor=format_run_cursor(cursor))

    async def detail(self, viewer: Viewer, workspace_id: int, run_id: str) -> RunDetail:
        """The caller's run in full, read without writing; spend waits up to 10 s."""
        await self.owned_run(viewer, workspace_id, run_id)
        try:
            detail = await self._in_flight.run(viewer, self._read_detail, workspace_id, run_id)
        except RunNotFound:
            raise run_not_found() from None
        spend = await self._spend.get(
            workspace_id=workspace_id,
            run_id=run_id,
            finished_at=detail.finished_at,
            caller=_caller_key(viewer),
            wait_s=DETAIL_SPEND_WAIT_S,
        )
        return detail.model_copy(update={"spend": run_spend(spend)})

    def _read_detail(self, workspace_id: int, run_id: str) -> RunDetail:
        return run_detail(self._bridge.read(workspace_id=workspace_id, run_id=run_id))

    async def graph(
        self, viewer: Viewer, workspace_id: int, run_id: str, *, if_none_match: str | None
    ) -> GraphRead:
        """
        The caller's run's pinned graph, or not modified when ``if_none_match`` names it.

        :raises CoralApiError: 404 with ``details.load_error`` when the pinned version is
            missing or cannot be read, as the detail shows such a run.
        """
        run = await self.owned_run(viewer, workspace_id, run_id)
        etag = f'"{run.version_id}"'
        if _etag_matches(if_none_match, etag):
            return GraphRead(etag=etag, graph=None)
        try:
            graph = await self._in_flight.run(
                viewer,
                self._bridge.pinned_graph,
                workspace_id=workspace_id,
                version_id=run.version_id,
            )
        except PinnedGraphError as exc:
            first, self._graph_warned = not self._graph_warned, True
            _logger.log(
                logging.WARNING if first else logging.DEBUG,
                "Coral cannot read the pinned graph of run %s: %s",
                run_id,
                describe_exception(exc),
            )
            raise CoralApiError(
                "not_found",
                _GRAPH_UNREADABLE_TEXT,
                404,
                details={"load_error": "engine.load_failed"},
            ) from None
        return GraphRead(etag=etag, graph=graph)

    async def log(
        self, viewer: Viewer, workspace_id: int, run_id: str, *, after_seq: int, limit: int
    ) -> LogPage:
        """The caller's run's log rows after ``after_seq``; an unreadable row is a placeholder."""
        await self.owned_run(viewer, workspace_id, run_id)
        return await self._in_flight.run(
            viewer, self._read_log_page, workspace_id, run_id, after_seq, limit
        )

    def _read_log_page(
        self, workspace_id: int, run_id: str, after_seq: int, limit: int
    ) -> LogPage:
        # One row past the page says whether more follow.
        rows = self._runs.read_log(
            run_id, workspace_id=workspace_id, after_seq=after_seq, limit=limit + 1, tolerant=True
        )
        return log_page(rows, limit=limit)

    async def outcome(self, viewer: Viewer, workspace_id: int, run_id: str) -> NoReturn:
        """Not served yet; the caller's own runs answer 501, any other the run 404."""
        await self.owned_run(viewer, workspace_id, run_id)
        raise CoralApiError("not_implemented", "A run's outcome is not available yet.", 501)


__all__ = [
    "API_CALL_TIMEOUT_S",
    "API_THREADS",
    "API_THREAD_NAME",
    "BUSY_RETRY_AFTER_S",
    "MAX_API_CALLS",
    "MAX_API_CALLS_PER_USER",
    "GraphRead",
    "InFlight",
    "RunReads",
    "RunsApi",
    "server_busy",
]
