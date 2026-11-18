"""The bridge in the drain pool: its executors, its hold policy and its thread pool.

Every bridge call is synchronous and may wait on the run row's lock, so async
callers (executors, the finished hook, the resync reconciler, the drift pauser)
run it on a dedicated bounded thread pool instead of the event loop's default
executor. A call keeps running in its thread when its task is cancelled; bridge
commits are idempotent, so a repeat is safe.
"""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import ParamSpec, TypeVar

from coral.bridge.commit import DRIFT_EFFECT_CODES
from coral.bridge.config import DRIFT_HOLD, HOLD_RULES
from coral.bridge.service import LOAD_FAILED_DETAIL, EngineBridge, EngineLoadFailed
from coral.queue.drainer import FinishedWork
from coral.queue.executors import EffectCompleted, EffectExecutor, EffectFailed, ExecutionContext
from coral.queue.run_effects import (
    MAX_EFFECT_KEY_CHARS,
    EffectRefused,
    effect_payload,
    invalid_payload,
    required_text,
)
from coral.stores.protocols import CommitOutcome, CoralRun, RunContended, RunNotFound, WorkItem

_logger = logging.getLogger(__name__)

# Bridge calls in flight at once in one process.
BRIDGE_THREADS = 8
BRIDGE_THREAD_NAME = "coral-bridge"

_P = ParamSpec("_P")
_T = TypeVar("_T")


class BridgeThreads:
    """
    Runs the bridge's calls on its own bounded thread pool; owned and closed by the lifespan.

    Its methods are the async forms the drain pool and the drift pauser call: the
    finished hook (:meth:`feed`), the resync reconciler (:meth:`schedule_resync`) and
    the engine drift pause (:meth:`pause_for_drift`).
    """

    def __init__(self, bridge: EngineBridge, *, max_workers: int = BRIDGE_THREADS) -> None:
        self._bridge = bridge
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=BRIDGE_THREAD_NAME
        )
        self._closed = False

    @property
    def bridge(self) -> EngineBridge:
        return self._bridge

    @property
    def closed(self) -> bool:
        return self._closed

    async def run(self, fn: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """``fn(*args, **kwargs)`` on the pool, in a copy of the caller's context.

        :raises RuntimeError: once the pool is closed.
        """
        context = contextvars.copy_context()

        def call() -> _T:
            return context.run(fn, *args, **kwargs)

        return await asyncio.get_running_loop().run_in_executor(self._pool, call)

    def close(self) -> None:
        """Take no more calls; calls already running finish in their threads."""
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)

    async def feed(self, finished: FinishedWork) -> None:
        """The drainer's finished hook: fold the row's outcome into its run."""
        await self.run(self._bridge.feed, finished)

    async def schedule_resync(self, run: CoralRun) -> None:
        """The supervisor's run reconciler: make the run's resync row due."""
        await self.run(self._bridge.schedule_resync, run)

    async def pause_for_drift(
        self,
        *,
        workspace_id: int,
        run_id: str,
        cause: str,
        body: dict[str, object],
        checksum_parts: Sequence[str],
        now_us: int,
    ) -> CommitOutcome:
        """Pause the run ``drift`` through the engine, with the drift entry, in one commit."""
        commit = await self.run(
            self._bridge.pause_for_drift,
            workspace_id=workspace_id,
            run_id=run_id,
            cause=cause,
            body=body,
            checksum_parts=checksum_parts,
            now_us=now_us,
        )
        return commit.outcome


def bridge_hold_policy(item: WorkItem, failure: EffectFailed, now_s: int) -> int | None:
    """
    How long to hold a refused item without spending its attempt, or ``None`` to retry it.

    Domain waits are held; a wait with a horizon ends that long after its first
    refusal (``held_since``), and the item then takes the normal retries. Reads no store.
    """
    code = failure.error_code
    rule = HOLD_RULES.get(code)
    if rule is None and code in DRIFT_EFFECT_CODES:
        # Exactly the drift codes the resume commit releases.
        rule = DRIFT_HOLD
    if rule is None:
        return None
    delay, horizon = rule
    held_since = item.held_since if item.held_since is not None else now_s
    if horizon is not None and now_s - held_since >= horizon:
        return None
    return delay


def timer_executor(threads: BridgeThreads) -> EffectExecutor:
    """
    The ``timer`` executor: fire an armed timer's ``TimerDue`` once its time has come.

    Payload: ``timer_key`` and ``due_at`` (ISO 8601 with a zone). Before ``due_at`` by
    the bridge clock it fails retryable ``timer.early``, which the hold policy holds, so
    the row is never spent early. It fails permanently when the run cannot be loaded
    (``engine.load_failed``) or the firing cannot be committed and the run is paused
    instead (``engine.commit_unbuildable``): the resync revives the failed row of a
    still-armed timer, so the timer fires once its run can take it.
    """

    async def execute(ctx: ExecutionContext) -> EffectCompleted | EffectFailed:
        try:
            timer_key, due_at = _timer_payload(ctx)
        except EffectRefused as exc:
            return exc.outcome()
        bridge = threads.bridge
        if bridge.now() < due_at:
            return EffectFailed(error_code="timer.early", message="not due yet", retryable=True)
        try:
            commit = await threads.run(
                bridge.fire_timer,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                timer_key=timer_key,
            )
        except EngineLoadFailed:
            return EffectFailed(
                error_code=LOAD_FAILED_DETAIL,
                message=f"run {ctx.run_id} cannot be loaded; it is paused",
            )
        except RunNotFound:
            return _run_missing(ctx)
        except RunContended:
            return _contended(ctx)
        if commit.unbuildable is not None:
            return EffectFailed(
                error_code="engine.commit_unbuildable",
                message=f"run {ctx.run_id} is paused instead ({commit.unbuildable})",
            )
        return EffectCompleted()

    return execute


def run_resync_executor(threads: BridgeThreads) -> EffectExecutor:
    """
    The ``run_resync`` executor: repair the item's run level-triggered.

    Result: what the repair did. A run that cannot be loaded is paused once and the item
    completes; its next resync comes with the paused run's slower schedule.
    """

    async def execute(ctx: ExecutionContext) -> EffectCompleted | EffectFailed:
        bridge = threads.bridge
        try:
            report = await threads.run(
                bridge.resync_run, workspace_id=ctx.workspace_id, run_id=ctx.run_id
            )
        except EngineLoadFailed:
            return EffectCompleted()
        except RunNotFound:
            return _run_missing(ctx)
        except RunContended:
            return _contended(ctx)
        return EffectCompleted(result=dataclasses.asdict(report))

    return execute


def _run_missing(ctx: ExecutionContext) -> EffectFailed:
    return EffectFailed(
        error_code="effect.run_missing", message=f"run {ctx.run_id} is not in this workspace"
    )


def _contended(ctx: ExecutionContext) -> EffectFailed:
    return EffectFailed(
        error_code="run.contended",
        message=f"other commits to run {ctx.run_id} kept winning",
        retryable=True,
    )


def _timer_payload(ctx: ExecutionContext) -> tuple[str, datetime]:
    payload = effect_payload(ctx)
    timer_key = required_text(payload, "timer_key")
    if len(timer_key) > MAX_EFFECT_KEY_CHARS or "\0" in timer_key:
        raise invalid_payload(
            f"timer_key must be at most {MAX_EFFECT_KEY_CHARS} characters, without NUL"
        )
    try:
        due_at = datetime.fromisoformat(required_text(payload, "due_at"))
    except ValueError:
        raise invalid_payload("due_at must be an ISO 8601 time") from None
    if due_at.tzinfo is None or due_at.utcoffset() is None:
        raise invalid_payload("due_at must name its time zone")
    return timer_key, due_at


__all__ = [
    "BRIDGE_THREADS",
    "BRIDGE_THREAD_NAME",
    "BridgeThreads",
    "bridge_hold_policy",
    "run_resync_executor",
    "timer_executor",
]
