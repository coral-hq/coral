"""The runs API: the owner's run reads and writes on a bounded thread pool, fair between users.

Every call names a run through :meth:`RunsApi.owned_run` first: the id's format, the
row and its owner, before any load, log, graph, spend read, commit or gate answer, so
a run the caller may not see is one fixed 404 that did no other work. Blocking store
and bridge calls run on the ``coral-api`` pool through :class:`InFlight`, which admits
one call per thread and at most half of them per user, and gives each one 30 seconds.

A start takes its own slot (:class:`StartSlots`, 8 in all and 2 per user) for the
whole call and runs one at a time per run id; its host I/O holds no pool thread.
The bridge authorizes nothing: the owner, the account generation, the workflow text
and the run target come from the server, never from the request. A repeat of a start
is answered from the run it made, compared on the request alone, without reading the
workflow again or pausing the run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Literal, NoReturn, ParamSpec, Protocol, TypeVar

from coral.alerts.types import LOCAL_USER_ID, is_owner, normalize_owner
from coral.api.errors import CoralApiError, run_not_found
from coral.api.run_models import (
    RUN_ID,
    GateAnswerOut,
    GateAnswerRequest,
    LogPage,
    RunDetail,
    RunPage,
    RunSummary,
    StartRunRequest,
    default_title,
    format_run_cursor,
    invalid_run_cursor,
    list_item_actions,
    log_page,
    read_summary,
    row_pause_reason,
    row_status,
    run_detail,
    run_spend,
    run_summary,
)
from coral.api.spend import DETAIL_SPEND_WAIT_S, SpendCache
from coral.api.workflows import WORKFLOW_NOT_FOUND
from coral.bridge.config import LOCK_TIMEOUT_S, epoch_us
from coral.bridge.executors import BoundedThreads, PoolClosed
from coral.bridge.graphs import PinnedGraphError
from coral.bridge.service import (
    LOAD_FAILED_DETAIL,
    BridgeCommit,
    EngineBridge,
    EngineLoadFailed,
    RunNotRunnable,
    RunRead,
)
from coral.bridge.start import check_startable, replay_start, start_engine_run
from coral.db.enum_codecs import encode_run_status
from coral.engine import types as engine
from coral.gates.verdict import GateAnswers, GateVerdict, VisitAnswer
from coral.model.ids import derived_id
from coral.model.ir import CompiledGraph
from coral.omni.protocols import GatePublisher, Viewer
from coral.queue.run_effects import describe_exception
from coral.recovery.cancel import cancel_run_row, withdraw_local_prompts
from coral.runview.types import FINISHED_RUN_STATUSES, RunStatusName
from coral.stores.protocols import (
    CoralRun,
    GateVisitState,
    InvalidRunCursor,
    RunContended,
    RunNotFound,
    RunStartSpec,
    RunStore,
    StartKeyConflict,
)
from coral.stores.workflows import WorkflowDefinitionStore
from coral.workspace.run_worktree import (
    RunWorktree,
    RunWorktreeError,
    RunWorktreeHost,
    create_or_adopt_run_worktree,
)

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
# Starts in flight at once, in all and for one user.
MAX_STARTS = 8
MAX_STARTS_PER_USER = 2
# A worktree another start is checking out has no run yet; it takes a moment more.
LOCKED_WORKTREE_RETRY_AFTER_S = 2
_BUSY_TEXT = "The server is busy; try again."
_GRAPH_UNREADABLE_TEXT = "The run's workflow graph cannot be read."
_KEY_CONFLICT_TEXT = "This start key started a run with another request."
# Not a conflict a new key would fix: the key's run exists and is only unreadable.
_UNREADABLE_START_TEXT = (
    "This start key's run cannot be read back to compare the request; it can only be cancelled."
)
_NO_GENERATION_TEXT = "Starting a run needs a request that proves its account."
_NO_HOST_TEXT = "No host can be reached from this server."
_LOAD_FAILED_TEXT = "The run cannot be loaded; it can only be cancelled."
_NOT_PAUSABLE_TEXT = "The run cannot be paused now."
_NOT_RESUMABLE_TEXT = "The run cannot be resumed now."
_NOT_CANCELLABLE_TEXT = "The run cannot be cancelled now."
_RESUME_NOT_ALLOWED = "resume_not_allowed"
# The refusal each worktree failure is, by its code; a locked worktree is a start in flight.
_WORKTREE_REFUSALS: Mapping[str, tuple[Any, int]] = {
    "host_offline": ("host_offline", 503),
    "not_permitted": ("not_permitted", 403),
    "not_a_git_repo": ("not_a_git_repo", 400),
    "worktree_failed": ("worktree_failed", 409),
}

_P = ParamSpec("_P")
_T = TypeVar("_T")
# A caller's share of the calls in flight: its normalized owner id and generation.
_CallerKey = tuple[str | None, str | None]


def server_busy(
    message: str = _BUSY_TEXT,
    *,
    retry_after_s: int = BUSY_RETRY_AFTER_S,
    details: Mapping[str, Any] | None = None,
) -> CoralApiError:
    """The refusal for a call the server cannot take now; the caller retries."""
    return CoralApiError(
        "server_busy", message, 503, details=details, headers={"Retry-After": str(retry_after_s)}
    )


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _actor(viewer: Viewer) -> str:
    """Who a write's engine rows name: the user, or ``local`` for the single local user."""
    return viewer.user_id or LOCAL_USER_ID


@contextmanager
def _write_errors(action: str, run_id: str) -> Iterator[None]:
    """
    Re-raise an unexpected error of a write without its cause.

    A store error's text and its cause hold the statement's parameters (a request's
    title, a note), so only its description is logged, and the server's own handler
    answers a cause-free error.
    """
    try:
        yield
    except CoralApiError:
        raise
    except Exception as exc:  # noqa: BLE001 -- logged, then raised without its cause
        _logger.error("Coral could not %s run %s: %s", action, run_id, describe_exception(exc))
        raise RuntimeError(f"Coral could not {action} the run.") from None


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


class HostConnector(Protocol):
    """Reaches the run owner's host once the owner may use it; raises ``RunWorktreeError``."""

    async def __call__(
        self,
        *,
        user_id: str | None,
        account_generation: str | None,
        host_id: str,
        workspace_id: int,
    ) -> RunWorktreeHost: ...


@dataclass
class _KeyLock:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class StartSlots:
    """
    Starts in flight, at most so many in all and per user, and one at a time per run.

    A start past either limit is refused at once as busy. Two starts of one run id
    (one user's one start key) run in turn, so the second finds the first's run.
    Use it on one event loop.
    """

    def __init__(
        self, *, max_starts: int = MAX_STARTS, max_per_caller: int = MAX_STARTS_PER_USER
    ) -> None:
        self._max_starts = max_starts
        self._max_per_caller = max_per_caller
        self._by_caller: dict[_CallerKey, int] = {}
        self._in_flight = 0
        self._locks: dict[tuple[int, str], _KeyLock] = {}

    @property
    def in_flight(self) -> int:
        """Starts holding a slot, running or waiting for their run's turn."""
        return self._in_flight

    @asynccontextmanager
    async def hold(self, viewer: Viewer, workspace_id: int, run_id: str) -> AsyncIterator[None]:
        """
        A start slot of ``viewer``'s, then the run's turn, for the ``async with`` block.

        :raises CoralApiError: 503 ``server_busy`` when the limits are reached.
        """
        key = _caller_key(viewer)
        held = self._by_caller.get(key, 0)
        if self._in_flight >= self._max_starts or held >= self._max_per_caller:
            _logger.debug(
                "Coral refused a start: %d in flight, %d of the caller's", self._in_flight, held
            )
            raise server_busy()
        self._by_caller[key] = held + 1
        self._in_flight += 1
        turn = self._locks.setdefault((workspace_id, run_id), _KeyLock())
        turn.users += 1
        try:
            async with turn.lock:
                yield
        finally:
            turn.users -= 1
            if turn.users == 0:
                self._locks.pop((workspace_id, run_id), None)
            self._in_flight -= 1
            remaining = self._by_caller.get(key, 0) - 1
            if remaining > 0:
                self._by_caller[key] = remaining
            else:
                self._by_caller.pop(key, None)


@dataclass(frozen=True)
class StartedRun:
    """A start's run; ``created`` is false for a repeat answered from the run it made."""

    created: bool
    summary: RunSummary


@dataclass(frozen=True)
class _Acted:
    """
    A write and the run as read after it.

    :param refusal: Why the write was not taken, as the engine or the API names it.
    """

    read: RunRead
    refusal: str | None = None
    gate_rows: tuple[GateVisitState, ...] = ()


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
        bridge: EngineBridge,
        run_store: RunStore,
        spend: SpendCache,
        in_flight: InFlight,
        gate_answers: GateAnswers | None = None,
        gate_publisher: GatePublisher | None = None,
        connect_host: HostConnector | None = None,
        requires_generation: bool = False,
        starts: StartSlots | None = None,
    ) -> None:
        """
        :param bridge: Loads runs (reads never write) and commits the owner's actions.
        :param spend: Run spend, read only after the owner check.
        :param in_flight: Runs every store and bridge call.
        :param gate_answers: Takes gate answers; without it they are refused as busy.
        :param gate_publisher: Withdraws this process's prompts of gates that closed.
        :param connect_host: Reaches a start's host; without it starts are refused as
            ``host_offline``.
        :param requires_generation: The server signs users in to accounts, so a start
            needs a request that proves its account generation.
        """
        self._bridge = bridge
        self._runs = run_store
        self._spend = spend
        self._in_flight = in_flight
        self._gate_answers = gate_answers
        self._publisher = gate_publisher
        self._connect_host = connect_host
        self._requires_generation = requires_generation
        self._starts = starts or StartSlots()
        # The first unreadable pinned graph is a warning; later ones go to debug.
        self._graph_warned = False

    @property
    def in_flight(self) -> InFlight:
        return self._in_flight

    @property
    def starts(self) -> StartSlots:
        return self._starts

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

    # ── start ────────────────────────────────────────────────────────────────

    async def start(
        self,
        viewer: Viewer,
        workspace_id: int,
        request: StartRunRequest,
        *,
        definitions: WorkflowDefinitionStore,
    ) -> StartedRun:
        """
        Start one of the caller's workflows, or answer the run its start key made.

        :param definitions: The workflows; only one the caller owns, in this
            workspace, starts.
        :raises CoralApiError: 403 in accounts mode without a proven generation; 404
            for a workflow the caller cannot start; 409 for a start key used with
            another request; 422 for a workflow that cannot run; the host's refusal;
            503 when busy.
        """
        if self._requires_generation and not viewer.check_generation:
            raise CoralApiError("not_permitted", _NO_GENERATION_TEXT, 403)
        run_id = derived_id("coral-run", viewer.user_id or "", request.start_key)
        with _write_errors("start", run_id):
            async with self._starts.hold(viewer, workspace_id, run_id):
                existing = await self._in_flight.run(
                    viewer, self._runs.get_run, run_id, workspace_id=workspace_id
                )
                if existing is not None:
                    return await self._replay(viewer, existing, request)
                return await self._first_start(viewer, workspace_id, run_id, request, definitions)

    async def _first_start(
        self,
        viewer: Viewer,
        workspace_id: int,
        run_id: str,
        request: StartRunRequest,
        definitions: WorkflowDefinitionStore,
    ) -> StartedRun:
        owner = normalize_owner(viewer.user_id)
        definition = await self._in_flight.run(
            viewer,
            definitions.get,
            workspace_id=workspace_id,
            workflow_id=request.workflow_id,
            owner=owner,
        )
        # Readable is not startable: a workflow no one owns starts only for the local user.
        if definition is None or definition.user_id != owner:
            raise CoralApiError("not_found", WORKFLOW_NOT_FOUND, 404)
        if not definition.runnable:
            raise _not_runnable(RunNotRunnable("workflow.invalid", "the workflow cannot run"))
        try:
            await self._in_flight.run(viewer, check_startable, definition.yaml_text, run_id=run_id)
        except RunNotRunnable as exc:
            raise _not_runnable(exc) from None
        generation = viewer.account_generation if viewer.check_generation else None
        try:
            worktree = await self._worktree(viewer, workspace_id, run_id, request, generation)
        except RunWorktreeError as exc:
            if not exc.locked:
                code, status = _WORKTREE_REFUSALS[exc.code]
                _logger.info("Coral refused a start of run %s: %s", run_id, exc.code)
                raise CoralApiError(code, _sentence(exc.message), status) from None
            # Another replica may be checking the worktree out for this very start.
            raced = await self._in_flight.run(
                viewer, self._runs.get_run, run_id, workspace_id=workspace_id
            )
            if raced is not None:
                return await self._replay(viewer, raced, request)
            raise server_busy(
                _sentence(exc.message), retry_after_s=LOCKED_WORKTREE_RETRY_AFTER_S
            ) from None
        spec = RunStartSpec(
            workflow_id=definition.id,
            version_id="",
            title=(
                request.title
                if request.title is not None
                else default_title(definition.name, definition.workflow_key)
            ),
            request_preview=request.request,
            workspace_id=workspace_id,
            user_id=viewer.user_id,
            account_generation=generation,
            host_id=request.host_id,
            repo_path=request.repo_path,
            worktree_path=worktree.path,
            base_ref=request.base_ref,
            base_commit=worktree.start_commit,
            run_branch=worktree.branch,
            max_activations=request.max_activations,
        )
        try:
            run = await self._in_flight.run(
                viewer,
                start_engine_run,
                self._bridge,
                spec=spec,
                yaml_text=definition.yaml_text,
                start_key=request.start_key,
                actor=_actor(viewer),
                allow_ownerless=viewer.user_id is None,
            )
        except RunNotRunnable as exc:
            raise _not_runnable(exc) from None
        except StartKeyConflict:
            # A start on another replica stored the run first, with its own fields.
            raced = await self._in_flight.run(
                viewer, self._runs.get_run, run_id, workspace_id=workspace_id
            )
            if raced is None:
                raise CoralApiError("start_key_conflict", _KEY_CONFLICT_TEXT, 409) from None
            return await self._replay(viewer, raced, request)
        except (RunContended, EngineLoadFailed):
            raise server_busy() from None
        summary = await self._summary(viewer, workspace_id, run.id)
        return StartedRun(created=True, summary=summary)

    async def _worktree(
        self,
        viewer: Viewer,
        workspace_id: int,
        run_id: str,
        request: StartRunRequest,
        generation: str | None,
    ) -> RunWorktree:
        if self._connect_host is None:
            raise CoralApiError("host_offline", _NO_HOST_TEXT, 503)
        host = await self._connect_host(
            user_id=viewer.user_id,
            account_generation=generation,
            host_id=request.host_id,
            workspace_id=workspace_id,
        )
        return await create_or_adopt_run_worktree(
            host, repo_root=request.repo_path, run_id=run_id, base_ref=request.base_ref
        )

    async def _replay(self, viewer: Viewer, run: CoralRun, request: StartRunRequest) -> StartedRun:
        """
        Answer the run a start key made, when the request is the one that made it.

        The workflow is not read again, so an edit, a rename or a deletion since never
        turns a retry into a refusal; a run that cannot be loaded is not paused.
        """
        # The same user id under an older account registration made it.
        if not is_owner(run.user_id, run.account_generation, viewer):
            raise CoralApiError("start_key_conflict", _KEY_CONFLICT_TEXT, 409)
        try:
            read = await self._in_flight.run(
                viewer, self._replayed, run.workspace_id, run.id, request, _actor(viewer)
            )
        except (RunContended, EngineLoadFailed):
            raise server_busy() from None
        except RunNotFound:
            raise run_not_found() from None
        if read == "unreadable":
            raise CoralApiError(
                "start_key_conflict",
                _UNREADABLE_START_TEXT,
                409,
                details={"reason": LOAD_FAILED_DETAIL},
            )
        if read == "other_request":
            raise CoralApiError("start_key_conflict", _KEY_CONFLICT_TEXT, 409)
        return StartedRun(
            created=False, summary=self._with_spend(run.workspace_id, read_summary(read))
        )

    def _replayed(
        self, workspace_id: int, run_id: str, request: StartRunRequest, actor: str
    ) -> RunRead | Literal["other_request", "unreadable"]:
        """
        The run after its replay; ``other_request`` when another request started it,
        ``unreadable`` when its stored request cannot be read to compare.
        """
        read = self._bridge.read(workspace_id=workspace_id, run_id=run_id)
        if read.rows is None:
            return "unreadable"
        if not _same_start(read.rows.spec, request):
            return "other_request"
        started = replay_start(self._bridge, read, actor=actor)
        if started.version == read.run.version:
            return read
        return self._bridge.read(workspace_id=workspace_id, run_id=run_id)

    # ── actions ──────────────────────────────────────────────────────────────

    async def pause(self, viewer: Viewer, workspace_id: int, run_id: str) -> RunSummary:
        """
        Pause the caller's run for them; a paused run is left as it is.

        :raises CoralApiError: 409 for a finished run, one that cannot be loaded or one
            whose engine refused the pause.
        """
        run = await self.owned_run(viewer, workspace_id, run_id)
        with _write_errors("pause", run_id):
            status = row_status(run)
            if status in FINISHED_RUN_STATUSES:
                raise _illegal(run, _NOT_PAUSABLE_TEXT)
            if status == "paused":
                return await self._summary(viewer, workspace_id, run_id)
            acted = await self._act(viewer, self._paused, workspace_id, run_id, _actor(viewer))
            if acted.refusal is not None:
                raise _illegal(acted.read.run, _NOT_PAUSABLE_TEXT, reason=acted.refusal)
            return self._with_spend(workspace_id, read_summary(acted.read))

    def _paused(self, workspace_id: int, run_id: str, actor: str) -> _Acted:
        try:
            result = self._bridge.pause_run(workspace_id=workspace_id, run_id=run_id, actor=actor)
        except EngineLoadFailed:
            refusal: str | None = LOAD_FAILED_DETAIL
        else:
            refusal = result.code if result.outcome == "refused" else None
        return _Acted(self._bridge.read(workspace_id=workspace_id, run_id=run_id), refusal)

    async def resume(
        self, viewer: Viewer, workspace_id: int, run_id: str, *, cap: int | None = None
    ) -> RunSummary:
        """
        Resume the caller's paused run; one not paused is left as it is.

        Taken when the engine took the resume or the run left its pause; a resume
        that clears one cause of several leaves the run paused for the others.

        :param cap: A higher activation cap, for a run paused at its cap.
        :raises CoralApiError: 409 for a finished run, one that cannot be loaded or one
            no cause of whose pause a resume clears; 422 for a cap out of bounds.
        """
        run = await self.owned_run(viewer, workspace_id, run_id)
        with _write_errors("resume", run_id):
            status = row_status(run)
            if status in FINISHED_RUN_STATUSES:
                raise _illegal(run, _NOT_RESUMABLE_TEXT)
            if status != "paused":
                return await self._summary(viewer, workspace_id, run_id)
            try:
                acted = await self._act(
                    viewer, self._resumed, workspace_id, run_id, _actor(viewer), cap
                )
            except RunNotRunnable as exc:
                raise CoralApiError("validation_failed", _sentence(_rule_text(exc)), 422) from None
            if acted.refusal is not None:
                raise _illegal(acted.read.run, _NOT_RESUMABLE_TEXT, reason=acted.refusal)
            return self._with_spend(workspace_id, read_summary(acted.read))

    def _resumed(self, workspace_id: int, run_id: str, actor: str, cap: int | None) -> _Acted:
        try:
            commit = self._bridge.resume_run(
                workspace_id=workspace_id, run_id=run_id, actor=actor, cap=cap
            )
        except EngineLoadFailed:
            return _Acted(
                self._bridge.read(workspace_id=workspace_id, run_id=run_id), LOAD_FAILED_DETAIL
            )
        read = self._bridge.read(workspace_id=workspace_id, run_id=run_id)
        status = row_status(read.run)
        if status in FINISHED_RUN_STATUSES:
            return _Acted(read, status)
        # Judged by the run's row, or by the engine's entry when causes remain.
        taken = status != "paused" or _resume_taken(commit)
        return _Acted(read, None if taken else _RESUME_NOT_ALLOWED)

    async def cancel(self, viewer: Viewer, workspace_id: int, run_id: str) -> RunSummary:
        """
        Cancel the caller's run; a cancelled run is left as it is.

        A run that cannot be loaded is cancelled on its row alone, and this process's
        prompts of its open gates are withdrawn.

        :raises CoralApiError: 409 for a run that completed or failed.
        """
        run = await self.owned_run(viewer, workspace_id, run_id)
        with _write_errors("cancel", run_id):
            status = row_status(run)
            if status == "cancelled":
                return await self._summary(viewer, workspace_id, run_id)
            if status in FINISHED_RUN_STATUSES:
                raise _illegal(run, _NOT_CANCELLABLE_TEXT)
            acted = await self._act(viewer, self._cancelled, workspace_id, run_id, _actor(viewer))
            if acted.gate_rows and self._publisher is not None:
                await withdraw_local_prompts(self._publisher, acted.gate_rows)
            if row_status(acted.read.run) != "cancelled":
                raise _illegal(acted.read.run, _NOT_CANCELLABLE_TEXT)
            return self._with_spend(workspace_id, read_summary(acted.read))

    def _cancelled(self, workspace_id: int, run_id: str, actor: str) -> _Acted:
        gate_rows: tuple[GateVisitState, ...] = ()
        try:
            self._bridge.cancel_run(workspace_id=workspace_id, run_id=run_id, actor=actor)
        except (EngineLoadFailed, RunNotFound):
            # Its engine cannot load, or its rows are gone while the row stands.
            cancelled = cancel_run_row(
                self._runs,
                workspace_id=workspace_id,
                run_id=run_id,
                actor=actor,
                now_us=epoch_us(self._bridge.now()),
                lock_timeout_s=LOCK_TIMEOUT_S,
            )
            gate_rows = cancelled.gate_rows
        read = self._bridge.read(workspace_id=workspace_id, run_id=run_id)
        return _Acted(read, gate_rows=gate_rows)

    async def retry(self, viewer: Viewer, workspace_id: int, run_id: str) -> NoReturn:
        """Not served yet; the caller's own runs answer 501, any other the run 404."""
        await self.owned_run(viewer, workspace_id, run_id)
        raise CoralApiError("not_implemented", "Retrying a step is not available yet.", 501)

    async def _act(
        self, viewer: Viewer, fn: Callable[_P, _Acted], /, *args: _P.args, **kwargs: _P.kwargs
    ) -> _Acted:
        """A write on the pool, mapping the bridge's busy and missing-run refusals."""
        try:
            return await self._in_flight.run(viewer, fn, *args, **kwargs)
        except RunContended:
            raise server_busy() from None
        except RunNotFound:
            raise run_not_found() from None

    # ── gate answers ─────────────────────────────────────────────────────────

    async def answer_gate(
        self,
        viewer: Viewer,
        workspace_id: int,
        run_id: str,
        node_id: str,
        request: GateAnswerRequest,
    ) -> GateAnswerOut:
        """
        Answer a visit of one of the caller's run's gates, as the gate's prompt would.

        The answer holds one of the caller's gate-answer admissions (per user and in
        all, shared with the prompt) from the owner check to its commit; one past them
        is refused as busy before the run is loaded.

        :raises CoralApiError: the run 404 for a visit the run does not have; 409 for a
            visit that can no longer take this answer; 422 for an outcome the gate
            lacks; 503 when busy.
        """
        await self.owned_run(viewer, workspace_id, run_id)
        if self._gate_answers is None:
            raise server_busy()
        with _write_errors("answer a gate of", run_id):
            answered = await self._gate_answers.answer_visit(
                VisitAnswer(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    node_id=node_id,
                    token=request.visit_token,
                    outcome=request.outcome,
                    note=request.note,
                    viewer=viewer,
                )
            )
            verdict = answered.verdict
            if verdict is None or verdict.reason == "not_permitted":
                raise run_not_found()
            if answered.row is not None and self._publisher is not None:
                # The prompt's resolve would drop it; an answer here does it itself.
                if verdict.status == "accepted" or verdict.clear_pending:
                    await withdraw_local_prompts(self._publisher, (answered.row,))
            if verdict.status == "refused":
                raise _gate_refusal(verdict)
            return GateAnswerOut(result=verdict.status)

    # ── shared ───────────────────────────────────────────────────────────────

    async def _summary(self, viewer: Viewer, workspace_id: int, run_id: str) -> RunSummary:
        try:
            read = await self._in_flight.run(
                viewer, self._bridge.read, workspace_id=workspace_id, run_id=run_id
            )
        except RunNotFound:
            raise run_not_found() from None
        return self._with_spend(workspace_id, read_summary(read))

    def _with_spend(self, workspace_id: int, summary: RunSummary) -> RunSummary:
        """``summary`` with the spend the cache holds; a miss refreshes in the background."""
        spend = self._spend.peek(
            workspace_id=workspace_id, run_id=summary.run_id, finished_at=summary.finished_at
        )
        return summary.model_copy(update={"spend": run_spend(spend)})


def _rule_text(exc: RunNotRunnable) -> str:
    """The refusal's message without the ``[code]`` prefix its text carries."""
    return str(exc).removeprefix(f"[{exc.code}] ")


def _not_runnable(exc: RunNotRunnable) -> CoralApiError:
    return CoralApiError(
        "not_runnable", _sentence(_rule_text(exc)), 422, details={"rule": exc.code}
    )


def _illegal(run: CoralRun, message: str, *, reason: str | None = None) -> CoralApiError:
    """The refusal of an action the run cannot take, naming its row's state and why."""
    status = row_status(run)
    details: dict[str, Any] = {"status": status, "pause_reason": row_pause_reason(run)}
    if reason is not None:
        details["reason"] = reason
    if status in FINISHED_RUN_STATUSES:
        message = f"The run is {status}."
    elif reason == LOAD_FAILED_DETAIL:
        message = _LOAD_FAILED_TEXT
    return CoralApiError("illegal_transition", message, 409, details=details)


def _resume_taken(commit: BridgeCommit) -> bool:
    """The engine took a ``ResumeRun`` in ``commit``, which cleared a cause."""
    return commit.unbuildable is None and any(
        isinstance(entry.input, engine.ResumeRun) and entry.rejection is None
        for entry in commit.entries
    )


def _same_start(spec: RunStartSpec, request: StartRunRequest) -> bool:
    """The request is the one that started the run; a title counts only when given."""
    return (
        spec.workflow_id == request.workflow_id
        and spec.host_id == request.host_id
        and spec.repo_path == request.repo_path
        and spec.base_ref == request.base_ref
        and spec.request_preview == request.request
        and spec.max_activations == request.max_activations
        and (request.title is None or spec.title == request.title)
    )


def _gate_refusal(verdict: GateVerdict) -> CoralApiError:
    """A refused gate answer as the runs API answers it, with the verdict's own text."""
    reason = verdict.reason
    message = verdict.message or _BUSY_TEXT
    details = {"reason": reason}
    if reason == "run_busy":
        return server_busy(message, details=details)
    if reason == "invalid_answer":
        return CoralApiError("validation_failed", message, 422, details=details)
    if reason == "stale_visit":
        return CoralApiError("stale_visit", message, 409, details=details)
    return CoralApiError("illegal_transition", message, 409, details=details)


__all__ = [
    "API_CALL_TIMEOUT_S",
    "API_THREADS",
    "API_THREAD_NAME",
    "BUSY_RETRY_AFTER_S",
    "LOCKED_WORKTREE_RETRY_AFTER_S",
    "MAX_API_CALLS",
    "MAX_API_CALLS_PER_USER",
    "MAX_STARTS",
    "MAX_STARTS_PER_USER",
    "GraphRead",
    "HostConnector",
    "InFlight",
    "RunReads",
    "RunsApi",
    "StartSlots",
    "StartedRun",
    "server_busy",
]
