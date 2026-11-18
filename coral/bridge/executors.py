"""The bridge in the drain pool: its executors, its hold policy and its thread pools.

Every bridge call is synchronous and may wait on the run row's lock, so async
callers (executors, the finished hook, the resync reconciler, the drift pauser)
run it on a dedicated bounded thread pool instead of the event loop's default
executor; engine tool decisions get a smaller pool of their own. A call keeps
running in its thread when its task is cancelled; bridge commits are idempotent,
so a repeat is safe. The ``turn_fact`` executor turns a status edge, or a
re-gather, into the turn fact the engine reconciles, and a failed turn of the
run's orchestrator into a pause.
"""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ParamSpec, TypeVar

from coral.bridge.commit import DRIFT_EFFECT_CODES, EngineSnapshot
from coral.bridge.config import DRIFT_HOLD, HOLD_RULES
from coral.bridge.keys import ORCHESTRATOR_SLOT_ID, slot_message_id
from coral.bridge.orchestrator import failure_inputs, failure_pause, open_decisions
from coral.bridge.service import LOAD_FAILED_DETAIL, EngineBridge, EngineLoadFailed
from coral.db.enum_codecs import RunStatus
from coral.engine import types as engine
from coral.engine.facts import TurnFact
from coral.engine.machines.slot import find_slot
from coral.engine.reconcile import awaiting_effect
from coral.omni.protocols import (
    CoralSessionError,
    RunScopeRunner,
    SessionDispatch,
    SessionFacade,
    TurnTranscripts,
)
from coral.queue.drainer import FinishedWork
from coral.queue.executors import EffectCompleted, EffectExecutor, EffectFailed, ExecutionContext
from coral.queue.run_effects import (
    MAX_EFFECT_KEY_CHARS,
    EffectRefused,
    effect_payload,
    invalid_payload,
    required_text,
    run_scope,
    session_id_field,
)
from coral.recovery.drift import DriftPauser, classify_step
from coral.signals.turn_facts import EdgeFacts, LiveFacts, build_turn_fact
from coral.stores.protocols import CommitOutcome, CoralRun, RunContended, RunNotFound, WorkItem
from coral.stores.session_bindings import SessionBindingLookup
from coral.stores.stable_ids import StableIds

_logger = logging.getLogger(__name__)

# Slots that handed off: no turn fact or session state of theirs reaches the engine.
_HANDED_OFF = frozenset({"closing", "closed"})
# Why a signal is the run's orchestrator's, whose turns the step rules do not read.
_ORCHESTRATOR = "orchestrator"
# Bridge calls in flight at once in one process.
BRIDGE_THREADS = 8
BRIDGE_THREAD_NAME = "coral-bridge"
# Engine tool decisions in flight at once in one process, on a pool of their own.
DECISION_THREADS = 4
DECISION_THREAD_NAME = "coral-decision"

_P = ParamSpec("_P")
_T = TypeVar("_T")


class PoolClosed(RuntimeError):
    """The pool closed before the call ran, so nothing ran; the caller may try again."""


class BoundedThreads:
    """A bounded thread pool for blocking calls from the event loop; closed by its owner."""

    def __init__(self, *, max_workers: int, thread_name_prefix: str) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix=thread_name_prefix
        )
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def run(self, fn: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
        """``fn(*args, **kwargs)`` on the pool, in a copy of the caller's context.

        :raises PoolClosed: when the pool closes while the call waits for a thread.
        :raises RuntimeError: when the pool is already closed.
        """
        context = contextvars.copy_context()

        def call() -> _T:
            return context.run(fn, *args, **kwargs)

        future = self._pool.submit(call)
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if future.cancelled() and self._closed and (task is None or not task.cancelling()):
                raise PoolClosed("the call was dropped when its thread pool closed") from None
            raise

    def close(self) -> None:
        """
        Take no more calls; calls already running finish in their threads.

        A call still waiting for a thread is dropped: its caller gets :class:`PoolClosed`.
        """
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)


class BridgeThreads(BoundedThreads):
    """
    Runs the bridge's calls on its own bounded thread pool; owned and closed by the lifespan.

    Its methods are the async forms the drain pool and the drift pauser call: the
    finished hook (:meth:`feed`), the resync reconciler (:meth:`schedule_resync`) and
    the engine drift pause (:meth:`pause_for_drift`).
    """

    def __init__(self, bridge: EngineBridge, *, max_workers: int = BRIDGE_THREADS) -> None:
        super().__init__(max_workers=max_workers, thread_name_prefix=BRIDGE_THREAD_NAME)
        self._bridge = bridge

    @property
    def bridge(self) -> EngineBridge:
        return self._bridge

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


@dataclass(frozen=True)
class _TurnSignal:
    """A ``turn_fact`` item: the session, the slot it served, and its edge, if any."""

    session_id: str
    engine_slot_id: str
    generation: int
    edge: EdgeFacts | None


@dataclass(frozen=True)
class _Sources:
    """What a turn-fact gather reads, and the drift pause it may make."""

    bindings: SessionBindingLookup
    dispatch: SessionDispatch
    transcripts: TurnTranscripts
    stable_ids: StableIds
    facade: SessionFacade
    drift: DriftPauser
    scope_runner: RunScopeRunner


def turn_fact_executor(
    threads: BridgeThreads,
    *,
    bindings: SessionBindingLookup,
    dispatch: SessionDispatch,
    transcripts: TurnTranscripts,
    stable_ids: StableIds,
    facade: SessionFacade,
    drift: DriftPauser,
    scope_runner: RunScopeRunner,
) -> EffectExecutor:
    """
    The ``turn_fact`` executor: gather a slot's turn facts and fold what they mean.

    Payload: ``session_id``, ``slot_id`` (the store slot), ``engine_slot_id``,
    ``generation`` and, for an edge's signal, the bounded ``edge``. The item completes
    without a commit for a finished run, a session the slot no longer holds, or facts
    that do not decide a turn (result ``{"turn_fact": <why>}``). A slot still waiting on
    its leased effect holds the item (``signal.awaiting_effect``, or ``run.paused`` while
    its run is paused), so the edge applies after the receipt. An archived or deleted
    session pauses the run ``drift`` instead of being read; a closed one is not read.
    While a decision waits on the run's orchestrator, an archived or deleted
    orchestrator pauses the run ``drift`` and a failed turn of it pauses the run
    (``orchestrator_paused``); its other turns change nothing (``orchestrator_turn``).
    """
    sources = _Sources(
        bindings=bindings,
        dispatch=dispatch,
        transcripts=transcripts,
        stable_ids=stable_ids,
        facade=facade,
        drift=drift,
        scope_runner=scope_runner,
    )

    async def execute(ctx: ExecutionContext) -> EffectCompleted | EffectFailed:
        try:
            signal = _turn_signal(ctx)
        except EffectRefused as exc:
            return exc.outcome()
        bridge = threads.bridge
        try:
            snapshot = await threads.run(
                bridge.load, workspace_id=ctx.workspace_id, run_id=ctx.run_id
            )
            why = await _unheld_reason(snapshot, signal, bindings)
            if why == _ORCHESTRATOR:
                return _turn_result(await _orchestrator_turn(threads, snapshot, signal, sources))
            if why is not None:
                return _turn_result(why)
            if awaiting_effect(snapshot.state, signal.engine_slot_id):
                return _awaiting(snapshot)
            async with run_scope(scope_runner, snapshot.store):
                why = await _session_gone(snapshot, signal, sources)
                if why is not None:
                    return _turn_result(why)
                fact, why = await _gather(snapshot, signal, sources)
            if fact is None:
                if why == "undecided":
                    _logger.info(
                        "Coral cannot tell who started the newest turn of run %s slot %s",
                        ctx.run_id,
                        signal.engine_slot_id,
                    )
                return _turn_result(why)
            applied = await threads.run(
                bridge.apply_turn_fact,
                workspace_id=ctx.workspace_id,
                run_id=ctx.run_id,
                fact=fact,
            )
        except EngineLoadFailed:
            return _turn_result("run_unloadable")
        except RunNotFound:
            return _turn_result("run_missing")
        except RunContended:
            return _contended(ctx)
        except CoralSessionError as exc:
            if exc.code == "session.deleted":
                return _turn_result("session_deleted")
            return EffectFailed(error_code=exc.code, message=exc.message, retryable=exc.retryable)
        if applied == "awaiting_effect":
            return _awaiting(snapshot)
        return _turn_result(applied)

    return execute


async def _unheld_reason(
    snapshot: EngineSnapshot, signal: _TurnSignal, bindings: SessionBindingLookup
) -> str | None:
    """Why the signal changes nothing whatever its facts, or ``None`` when it may."""
    if snapshot.state.status is None:
        return "run_not_started"
    if snapshot.state.status in engine.TERMINAL_STATUSES:
        return "run_finished"
    store = snapshot.store
    binding = await asyncio.to_thread(
        bindings.find_by_session, store.workspace_id, signal.session_id
    )
    if (
        binding is None
        or binding.run_id != store.run_id
        or binding.slot_id != signal.engine_slot_id
        or binding.session_generation != signal.generation
    ):
        return "unbound"
    if signal.engine_slot_id == ORCHESTRATOR_SLOT_ID:
        # Only the orchestrator the run's row names speaks for the run.
        named = store.run.orchestrator_session_id == signal.session_id
        return _ORCHESTRATOR if named else "unbound"
    slot = find_slot(snapshot.state, signal.engine_slot_id)
    if slot is None or slot.session_generation != signal.generation:
        return "stale"
    if slot.status in _HANDED_OFF:
        # Its turns change nothing now, and archiving a finished step is no drift.
        return "slot_closed"
    return None


async def _orchestrator_turn(
    threads: BridgeThreads, snapshot: EngineSnapshot, signal: _TurnSignal, sources: _Sources
) -> str:
    """
    Pause the run for its orchestrator, while a decision waits on it.

    An archived or deleted orchestrator pauses ``drift``, as a step does; a failed turn
    is classified as a step's is, and its pause is re-checked in the commit.
    """
    if not open_decisions(snapshot.state):
        return "no_input"
    async with run_scope(sources.scope_runner, snapshot.store):
        gone = await _session_gone(snapshot, signal, sources)
    if gone is not None:
        return gone
    pause = failure_pause(signal.edge)
    if pause is None:
        return "orchestrator_turn"
    store = snapshot.store
    commit = await threads.run(
        threads.bridge.commit_inputs,
        workspace_id=store.workspace_id,
        run_id=store.run_id,
        inputs=lambda current: failure_inputs(
            current.state, current.store.run, signal.session_id, pause
        ),
    )
    return "orchestrator_paused" if commit.outcome.applied else "no_input"


async def _session_gone(
    snapshot: EngineSnapshot, signal: _TurnSignal, sources: _Sources
) -> str | None:
    """
    ``drift`` after pausing the run for an archived or deleted session, ``session_closed``
    for a closed one, else ``None``: only a live session's transcript is a turn's.
    """
    store = snapshot.store
    state = await sources.facade.session_state(
        workspace_id=store.workspace_id, session_id=signal.session_id
    )
    finding = classify_step(state)
    if finding is not None:
        await sources.drift.pause(
            workspace_id=store.workspace_id, run_id=store.run_id, finding=finding
        )
        return "drift"
    return "session_closed" if state.closed else None


async def _gather(
    snapshot: EngineSnapshot, signal: _TurnSignal, sources: _Sources
) -> tuple[TurnFact | None, str]:
    """
    The slot's turn fact from the stable-id store, the transcript and the live status,
    or ``None`` with why there is none.

    The transcript is read before the live status: a status read first could be the
    previous turn's while the transcript already shows the next turn running.
    """
    store = snapshot.store
    engine_messages = await asyncio.to_thread(
        sources.stable_ids.checksums_for_session,
        store.workspace_id,
        signal.session_id,
        run_id=store.run_id,
    )
    if not engine_messages:
        return None, "no_engine_message"
    transcript = await sources.transcripts.turn_transcript(
        session_id=signal.session_id, user_id=store.run.user_id, engine_messages=engine_messages
    )
    live = await sources.dispatch.live_status(session_id=signal.session_id)
    latest = slot_message_id(store.workspace_id, snapshot.state, signal.engine_slot_id)
    newest = transcript.newest_engine_input_id or (latest if transcript.beyond_reach else None)
    record = (
        None
        if newest is None
        else await asyncio.to_thread(
            sources.stable_ids.lookup, store.workspace_id, newest, run_id=store.run_id
        )
    )
    fact = build_turn_fact(
        slot_id=signal.engine_slot_id,
        session_id=signal.session_id,
        generation=signal.generation,
        transcript=transcript,
        live=LiveFacts(
            status=live.status,
            pending_elicitations=live.pending_elicitations,
            background_work=live.background_work,
        ),
        edge=signal.edge,
        engine_stable_id_present=True,
        engine_input_at_s=None if record is None else record.created_at,
        latest_engine_input_id=latest,
    )
    if fact is not None:
        return fact, "fact"
    undecided = transcript.newest_input is None and not transcript.beyond_reach
    return None, "undecided" if undecided else "no_fact"


def _turn_signal(ctx: ExecutionContext) -> _TurnSignal:
    payload = effect_payload(ctx)
    engine_slot_id = required_text(payload, "engine_slot_id")
    if len(engine_slot_id) > MAX_EFFECT_KEY_CHARS or "\0" in engine_slot_id:
        raise invalid_payload(
            f"engine_slot_id must be at most {MAX_EFFECT_KEY_CHARS} characters, without NUL"
        )
    generation = payload.get("generation")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise invalid_payload("generation must be a positive integer")
    raw_edge = payload.get("edge")
    try:
        edge = None if raw_edge is None else EdgeFacts.from_payload(raw_edge)
    except ValueError:
        raise invalid_payload("edge must be a status edge's bounded fields") from None
    return _TurnSignal(
        session_id=session_id_field(payload),
        engine_slot_id=engine_slot_id,
        generation=generation,
        edge=edge,
    )


def _awaiting(snapshot: EngineSnapshot) -> EffectFailed:
    """Hold the signal until its slot's effect is receipted, or the run resumes."""
    if snapshot.store.status == int(RunStatus.PAUSED):
        return EffectFailed(
            error_code="run.paused",
            message=f"run {snapshot.store.run_id} is paused",
            retryable=True,
        )
    return EffectFailed(
        error_code="signal.awaiting_effect",
        message="the slot's last effect has no receipt yet",
        retryable=True,
    )


def _turn_result(outcome: str) -> EffectCompleted:
    result: dict[str, Any] = {"turn_fact": outcome}
    return EffectCompleted(result=result)


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
    "DECISION_THREADS",
    "DECISION_THREAD_NAME",
    "BoundedThreads",
    "BridgeThreads",
    "PoolClosed",
    "bridge_hold_policy",
    "run_resync_executor",
    "timer_executor",
    "turn_fact_executor",
]
