"""Coral notices a working step whose runner is gone, and wakes it in the same session.

**The liveness pass** runs after each resync.

The server clears a runner's liveness stamp when its tunnel drops and, while the
runner's host is offline, holds the turn without publishing any edge, so the edge path
alone never sees such a loss. The pass starts a clock at this process's own first
sighting of a working slot's runner being neither connected nor fresh, and once the
reconnect grace has passed it reports the loss as a liveness-only turn fact
(``runner_last_seen`` is when the clock started), which the engine turns into one
``RunnerLost`` keyed by the runner it lost.

The stamp's age is never used: a restarted server, and a replica that starts leading
again, starts every clock afresh, so a runner still reconnecting gets the full grace
whatever the outage or the leader lease was. A clock watches one outage: the session,
its runner and the slot's connection epoch, which the engine advances when it records
the outage as over (a wake that saw the runner back, say). A clock ends when its runner
is connected or fresh again, the engine ends its outage, its slot stops working, its
session or runner changes, or its run stops running. While a clock runs, the pass names
when the grace ends, so the run's resync runs again then instead of at the next tick. A
report counts once the engine holds the loss; one it dropped is made again next pass.

**The wake** is each ``runner_lost`` effect's ``recovery.wake`` row. A slot that moved
on, or a session archived or deleted, is skipped (drift pauses the run); a session
someone closed fails the wake for a Retry. It waits while its run is paused for
anything but host-offline holds. Otherwise it brings the runner back through Coral's
relaunch path (:class:`~coral.omni.protocols.StepRelauncher`): a runner found connected,
or kept by the launch, is ``runner_back``, a new one in the same session ``relaunched``,
and the engine re-prompts the step unless it already runs a turn. A host that is
offline holds the slot (``RunnerHeld``: Cancel only) and the row checks again every
30 s; any other answer ends the hold (``RunnerHoldEnded``) before the wake goes on. A
host that says the old runner is alive holds the row too, so that runner is never
superseded. While the wake is in flight no infra stage re-prompts the step.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from coral.bridge.commit import EngineSnapshot
from coral.bridge.config import MAX_LIVE_SLOTS, ceil_epoch_seconds
from coral.bridge.executors import BridgeThreads
from coral.bridge.keys import slot_session_id
from coral.bridge.service import LOAD_FAILED_DETAIL, EngineLoadFailed
from coral.db.enum_codecs import RunStatus
from coral.engine import types as engine
from coral.engine.facts import TurnFact, runner_loss_key
from coral.engine.lifecycle import HOST_OFFLINE_DETAIL
from coral.engine.machines.slot import find_slot
from coral.engine.reconcile import awaiting_effect
from coral.engine.types import RunState, Slot
from coral.omni.protocols import (
    CoralSessionError,
    RunScopeRunner,
    SessionDispatch,
    SessionFacade,
    StepRelauncher,
)
from coral.queue.executors import EffectExecutor, EffectOutcome, ExecutionContext
from coral.queue.run_effects import (
    EffectRefused,
    invalid_payload,
    optional_text,
    required_text,
    run_effect,
    session_id_field,
)
from coral.recovery.drift import DriftDetected, DriftPauser, classify_step
from coral.slots.executors import MAX_GENERATION
from coral.stores import protocols as store
from coral.stores.protocols import RunContended, RunNotFound

_logger = logging.getLogger(__name__)

# Server config: how long a working step's runner may stay missing before it is lost.
DEFAULT_RECONNECT_GRACE_S = 90

# A clock's key: the session, the runner incarnation and the slot's connection epoch,
# which together name one outage.
_Watched = tuple[str, str | None, int]


@dataclass
class _Clock:
    since: datetime
    reported: bool = False


@dataclass(frozen=True)
class _Lost:
    slot: Slot
    session_id: str
    runner_id: str | None
    clock: _Clock


class LivenessPass:
    """
    Watches the runners of a running run's working slots, one run at a time.

    :param threads: The bridge's pool, which loads runs and commits the facts.
    :param dispatch: Reads each session's runner liveness.
    :param grace_s: How long a runner may stay missing, from this process's first
        sighting, before its loss is reported.
    :param clock: The time the clocks are read on; the bridge's by default.
    """

    def __init__(
        self,
        threads: BridgeThreads,
        dispatch: SessionDispatch,
        *,
        grace_s: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._threads = threads
        self._dispatch = dispatch
        self._grace = timedelta(seconds=grace_s)
        self._clock = clock if clock is not None else threads.bridge.now
        self._clocks: dict[tuple[int, str], dict[_Watched, _Clock]] = {}

    @property
    def grace_s(self) -> int:
        return int(self._grace.total_seconds())

    def reset(self) -> None:
        """Drop every clock: the next pass starts each from its own sighting."""
        self._clocks.clear()

    async def check_run(self, *, workspace_id: int, run_id: str) -> int | None:
        """
        Read the run's working runners, start or end their clocks and report each grace
        that has run out.

        A read that fails is logged and the slot keeps its clock until the next pass;
        a report that cannot be committed is tried again then.

        :returns: The epoch second the soonest running grace ends, or ``None``.
        """
        run_key = (workspace_id, run_id)
        try:
            snapshot = await self._threads.run(
                self._threads.bridge.load, workspace_id=workspace_id, run_id=run_id
            )
        except (EngineLoadFailed, RunNotFound):
            self._clocks.pop(run_key, None)
            return None
        state = snapshot.state
        if state.status != "running" or snapshot.store.status != int(RunStatus.RUNNING):
            self._clocks.pop(run_key, None)
            return None
        before = self._clocks.get(run_key, {})
        clocks: dict[_Watched, _Clock] = {}
        lost: list[_Lost] = []
        started = 0
        now = self._clock()
        for slot, session_id in _watched_slots(workspace_id, state):
            try:
                live = await self._dispatch.runner_liveness(
                    workspace_id=workspace_id, session_id=session_id
                )
            except Exception as exc:  # noqa: BLE001 -- logged; the slot is read next pass
                _logger.warning(
                    "Coral could not read a runner's liveness for run %s: %s",
                    run_id,
                    type(exc).__name__,
                )
                clocks.update(
                    (key, clock) for key, clock in before.items() if key[0] == session_id
                )
                continue
            if live.connected or live.fresh:
                continue
            # Every outage end the engine records (a wake's result, a resume of the
            # fourth-loss pause) advances the epoch, so a later drop is a new clock.
            key = (session_id, live.runner_id, slot.connection_epoch)
            clock = before.get(key)
            if clock is None:
                clock = _Clock(since=now)
                started += 1
            clocks[key] = clock
            if not clock.reported and now - clock.since >= self._grace:
                lost.append(_Lost(slot, session_id, live.runner_id, clock))
        if clocks:
            self._clocks[run_key] = clocks
        else:
            self._clocks.pop(run_key, None)
        counts = await self._report_all(workspace_id, run_id, lost)
        if started or any(counts.values()):
            _logger.info(
                "Coral liveness of run %s: %d runner clock(s) started, %d runner(s) lost, "
                "%d loss(es) already recorded, %d report(s) to make again",
                run_id,
                started,
                counts["lost"],
                counts["known"],
                counts["again"],
            )
        ends = [
            clock.since + self._grace
            for clock in clocks.values()
            if not clock.reported and clock.since + self._grace > now
        ]
        return ceil_epoch_seconds(min(ends)) if ends else None

    async def _report_all(
        self, workspace_id: int, run_id: str, lost: list[_Lost]
    ) -> dict[str, int]:
        """
        Report each lost runner, then count what the engine now holds.

        ``lost``: the report recorded the loss; ``known``: the engine already held it (the
        edge reported the same runner, say); ``again``: it holds nothing yet, so the clock
        reports again at the next pass.
        """
        counts = {"lost": 0, "known": 0, "again": 0}
        if not lost:
            return counts
        applied = [await self._report(workspace_id, run_id, item) for item in lost]
        try:
            after = await self._threads.run(
                self._threads.bridge.load, workspace_id=workspace_id, run_id=run_id
            )
        except (EngineLoadFailed, RunNotFound):
            counts["again"] = len(lost)
            return counts
        receipted = {receipt.key for receipt in after.state.receipts}
        for item, outcome in zip(lost, applied, strict=True):
            if outcome is None or _loss_key(item) not in receipted:
                counts["again"] += 1
                continue
            item.clock.reported = True
            counts["lost" if outcome == "applied" else "known"] += 1
        return counts

    async def _report(self, workspace_id: int, run_id: str, item: _Lost) -> str | None:
        """Commit the loss; its result, or ``None`` when the commit failed."""
        fact = TurnFact(
            slot_id=item.slot.id,
            session_id=item.session_id,
            generation=item.slot.session_generation,
            runner_id=item.runner_id,
            runner_last_seen=item.clock.since,
        )
        try:
            applied = await self._threads.run(
                self._threads.bridge.apply_turn_fact,
                workspace_id=workspace_id,
                run_id=run_id,
                fact=fact,
            )
        except (EngineLoadFailed, RunNotFound, RunContended) as exc:
            _logger.warning(
                "Coral could not report a lost runner of run %s: %s", run_id, type(exc).__name__
            )
            return None
        return applied


class LivenessRef:
    """
    The liveness pass a resync runs, set once the session engine is wired.

    Until then, and after it is cleared, a check does nothing.
    """

    def __init__(self) -> None:
        self.current: LivenessPass | None = None

    async def check_run(self, *, workspace_id: int, run_id: str) -> int | None:
        current = self.current
        if current is None:
            return None
        return await current.check_run(workspace_id=workspace_id, run_id=run_id)

    def reset(self) -> None:
        """Drop the current pass's clocks, when this replica starts leading."""
        if self.current is not None:
            self.current.reset()


def _loss_key(item: _Lost) -> str:
    """The receipt key the engine keeps for the outage the clock watched."""
    return runner_loss_key(
        item.session_id,
        item.slot.session_generation,
        item.runner_id,
        None,
        item.slot.connection_epoch,
    )


def _watched_slots(workspace_id: int, state: RunState) -> list[tuple[Slot, str]]:
    """The working slots whose runner is watched, with their sessions, up to the live cap."""
    watched: list[tuple[Slot, str]] = []
    for slot in state.slots:
        if slot.status != "working" or awaiting_effect(state, slot.id):
            continue
        session_id = slot_session_id(workspace_id, state, slot.id)
        if session_id is not None:
            watched.append((slot, session_id))
    return watched[:MAX_LIVE_SLOTS]


# The wake's hold codes (the bridge's hold rules): the host is offline, or says the old
# runner is alive.
HOST_OFFLINE_HOLD = "recovery.host_offline"
RUNNER_ALIVE_HOLD = "recovery.runner_alive"
_SKIPPED = {"outcome": "skipped", "turn_running": False}


def wake_executor(
    *,
    threads: BridgeThreads,
    relauncher: StepRelauncher,
    dispatch: SessionDispatch,
    facade: SessionFacade,
    drift: DriftPauser,
    run_store: store.RunStore,
    scope_runner: RunScopeRunner,
) -> EffectExecutor:
    """
    The ``recovery.wake`` executor.

    Payload: ``effect_key``, ``engine_slot_id``, ``generation``, ``session_id`` and
    ``runner_id`` (nullable). Result: ``{outcome, turn_running, seen_at}``, where
    ``outcome`` is ``skipped``, ``runner_back`` or ``relaunched``, ``turn_running`` says
    the runner already runs a turn, and ``seen_at`` (absent when skipped) is when the
    runner was back. A relaunch that left the session on the lost runner is
    ``runner_back``. Refusals: retryable ``run.paused``, ``recovery.host_offline`` (the
    slot is held), ``recovery.runner_alive`` and ``session.runner_status_unknown``;
    permanent ``session.closed`` for a step session someone closed; a relaunch's other
    refusals keep their own code and retryability. Any refusal but the host being
    offline ends the slot's hold first: the host answered, or nothing waits on it.
    """

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(
            _wake,
            ctx,
            threads=threads,
            relauncher=relauncher,
            dispatch=dispatch,
            facade=facade,
            drift=drift,
        )
        return await run_effect(ctx, run_store, scope_runner, _wake_payload, body)

    return execute


def _wake_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    # Only looked up in the run's own state, never acted on.
    engine_slot_id = required_text(payload, "engine_slot_id")
    generation = payload.get("generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or not 1 <= generation <= MAX_GENERATION
    ):
        raise invalid_payload(f"generation must be an integer from 1 to {MAX_GENERATION}")
    return {
        "engine_slot_id": engine_slot_id,
        "generation": generation,
        "session_id": session_id_field(payload),
        "runner_id": optional_text(payload, "runner_id"),
    }


async def _wake(
    ctx: ExecutionContext,
    state: store.RunState,
    payload: Mapping[str, Any],
    *,
    threads: BridgeThreads,
    relauncher: StepRelauncher,
    dispatch: SessionDispatch,
    facade: SessionFacade,
    drift: DriftPauser,
) -> dict[str, Any]:
    snapshot = await _load(threads, ctx)
    run, generation = snapshot.state, payload["generation"]
    slot = find_slot(run, payload["engine_slot_id"])
    if slot is None or slot.status != "working" or slot.session_generation != generation:
        return dict(_SKIPPED)
    if run.status == "paused" and not all(_host_offline(cause) for cause in run.causes):
        raise EffectRefused("run.paused", f"run {state.run_id} is paused", retryable=True)
    session_id = payload["session_id"]
    found = await facade.session_state(workspace_id=ctx.workspace_id, session_id=session_id)
    finding = classify_step(found)
    if finding is not None:
        await drift.pause(workspace_id=ctx.workspace_id, run_id=state.run_id, finding=finding)
        return dict(_SKIPPED)
    hold = engine.PauseCause(reason="infra", detail=HOST_OFFLINE_DETAIL, subject=slot.id)
    ended = engine.RunnerHoldEnded(slot_id=slot.id, generation=generation)
    try:
        if found.closed:
            # Someone closed the working step's session: only a Retry can go on from here.
            raise CoralSessionError("session.closed", f"step session {session_id} is closed")
        relaunch = await relauncher.ensure_runner(
            workspace_id=ctx.workspace_id,
            session_id=session_id,
            generation=generation,
            ensure_lease=ctx.ensure_lease,
        )
    except DriftDetected as exc:
        await drift.pause(workspace_id=ctx.workspace_id, run_id=state.run_id, finding=exc.finding)
        return dict(_SKIPPED)
    except CoralSessionError as exc:
        if exc.code != "session.host_offline":
            if hold in run.causes:
                await _commit_unless(threads, ctx, ended, done=lambda causes: hold not in causes)
            raise
        held = engine.RunnerHeld(slot_id=slot.id, session_id=session_id, generation=generation)
        await _commit_unless(threads, ctx, held, done=lambda causes: hold in causes)
        raise EffectRefused(
            HOST_OFFLINE_HOLD,
            f"run {state.run_id}'s step host is offline; the step is held until it returns",
            retryable=True,
        ) from exc
    if hold in run.causes:
        await _commit_unless(threads, ctx, ended, done=lambda causes: hold not in causes)
    if relaunch == "relaunched" and payload["runner_id"] is not None:
        live = await dispatch.runner_liveness(workspace_id=ctx.workspace_id, session_id=session_id)
        if live.runner_id == payload["runner_id"]:
            # The launch kept the lost runner, which came back: nothing was replaced.
            relaunch = "connected"
    # A relaunched runner may already run a turn too; either way it is not re-prompted.
    turn_running = (await dispatch.live_status(session_id=session_id)).status == "running"
    _logger.info("Coral woke run %s's step: %s", state.run_id, relaunch)
    return {
        "outcome": "runner_back" if relaunch == "connected" else "relaunched",
        "turn_running": turn_running,
        "seen_at": threads.bridge.now().isoformat(),
    }


def _host_offline(cause: engine.PauseCause) -> bool:
    return cause.reason == "infra" and cause.detail == HOST_OFFLINE_DETAIL


async def _load(threads: BridgeThreads, ctx: ExecutionContext) -> EngineSnapshot:
    try:
        return await threads.run(
            threads.bridge.load, workspace_id=ctx.workspace_id, run_id=ctx.run_id
        )
    except EngineLoadFailed:
        raise EffectRefused(
            LOAD_FAILED_DETAIL, f"run {ctx.run_id} cannot be loaded; it is paused"
        ) from None


async def _commit_unless(
    threads: BridgeThreads,
    ctx: ExecutionContext,
    command: engine.Input,
    *,
    done: Callable[[tuple[engine.PauseCause, ...]], bool],
) -> None:
    """
    Commit ``command`` unless the run already shows it (``done`` on its causes), so a
    hold checked again and again is committed once.

    :raises EffectRefused: Retryable ``run.contended`` when other commits kept winning.
    """

    def inputs(snapshot: EngineSnapshot) -> tuple[engine.Input, ...]:
        return () if done(snapshot.state.causes) else (command,)

    try:
        await threads.run(
            threads.bridge.commit_inputs,
            workspace_id=ctx.workspace_id,
            run_id=ctx.run_id,
            inputs=inputs,
        )
    except RunContended:
        raise EffectRefused(
            "run.contended", f"run {ctx.run_id}'s other commits kept winning", retryable=True
        ) from None
    except EngineLoadFailed:
        raise EffectRefused(
            LOAD_FAILED_DETAIL, f"run {ctx.run_id} cannot be loaded; it is paused"
        ) from None


__all__ = [
    "DEFAULT_RECONNECT_GRACE_S",
    "HOST_OFFLINE_HOLD",
    "RUNNER_ALIVE_HOLD",
    "LivenessPass",
    "LivenessRef",
    "wake_executor",
]
