"""Coral notices a working step whose runner is gone: the liveness pass after each resync.

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
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from coral.bridge.config import MAX_LIVE_SLOTS, ceil_epoch_seconds
from coral.bridge.executors import BridgeThreads
from coral.bridge.keys import slot_session_id
from coral.bridge.service import EngineLoadFailed
from coral.db.enum_codecs import RunStatus
from coral.engine.facts import TurnFact, runner_loss_key
from coral.engine.reconcile import awaiting_effect
from coral.engine.types import RunState, Slot
from coral.omni.protocols import SessionDispatch
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


__all__ = ["DEFAULT_RECONNECT_GRACE_S", "LivenessPass", "LivenessRef"]
