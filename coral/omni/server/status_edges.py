"""Coral's narrow status-edge observer: the edges of sessions a close or cancel is watching.

Omnigent hands every published status edge, from every workspace and from any
thread, to :meth:`CoralStatusEdges.observe`. An edge of a session nobody
watches costs one dict read. A watched session's edge becomes a ``TurnFact``
(:func:`observe_status_edge`) on the watchers' event loop, where it resolves
the waiters it matches and reaches the ``TurnFactSink`` hook, when one is set.
Watchers key on ``(workspace_id, session_id)``: session ids repeat across
workspaces, so a watch names its workspace.

A response can be reported twice: the server may infer an outcome (a stop, a
runner drop) before the runner's own report arrives, and Omnigent never lets
an inference follow a runner report. So the latest outcome reported for a
response is its outcome, and each fact carries its own edge's outcome. A
waiter still ends at the first terminal outcome it sees.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import override

from coral.omni.protocols import (
    EdgePredicate,
    EdgeWatch,
    ObservedEdge,
    SessionEdgeWatcher,
    StatusEdgeView,
    TurnFactSink,
)
from coral.omni.server.observers import observe_status_edge
from omnigent.server.session_live_state import SessionStatusEdge

_logger = logging.getLogger(__name__)

# Edges one watch keeps for its waits; a close watches for at most a few minutes.
HISTORY_LIMIT = 256


class _Watch(EdgeWatch):
    """One close's or cancel's view of a session's edges since it started watching."""

    def __init__(self, loop: asyncio.AbstractEventLoop, slot_id: str) -> None:
        self.slot_id = slot_id
        self._loop = loop
        self._history: deque[ObservedEdge] = deque(maxlen=HISTORY_LIMIT)
        self._waiters: list[tuple[EdgePredicate, asyncio.Future[ObservedEdge]]] = []

    def deliver(self, observed: ObservedEdge) -> None:
        self._history.append(observed)
        for predicate, future in self._waiters:
            if future.done():
                continue
            try:
                if predicate(observed):
                    future.set_result(observed)
            except Exception as exc:  # noqa: BLE001 - the waiter sees its own predicate's bug
                future.set_exception(exc)

    @override
    async def wait_for(self, predicate: EdgePredicate, *, timeout_s: float) -> ObservedEdge | None:
        """The first edge since the watch began that matches; ``None`` after ``timeout_s``."""
        for observed in tuple(self._history):
            if predicate(observed):
                return observed
        waiter = (predicate, self._loop.create_future())
        self._waiters.append(waiter)
        try:
            async with asyncio.timeout(timeout_s):
                return await waiter[1]
        except TimeoutError:
            return None
        finally:
            self._waiters.remove(waiter)


class _WatchedSession:
    """The watches of one session in one workspace."""

    def __init__(self) -> None:
        self.watches: tuple[_Watch, ...] = ()


class CoralStatusEdges(SessionEdgeWatcher):
    """
    The S1 observer for sessions a close or cancel is watching.

    :param loop: The server's event loop; watches and waiters live on it.
    :param sink: Receives each watched session's ``TurnFact``; the server sets
        none, since turn facts persist through the ``coral.turn_facts`` observer.
    """

    def __init__(
        self, loop: asyncio.AbstractEventLoop, *, sink: TurnFactSink | None = None
    ) -> None:
        self._loop = loop
        self._sink = sink
        # session id -> workspace id -> its watches; changed only on ``loop``.
        self._sessions: dict[str, dict[int, _WatchedSession]] = {}

    @override
    @asynccontextmanager
    async def watch(
        self, session_id: str, *, workspace_id: int, slot_id: str = ""
    ) -> AsyncIterator[EdgeWatch]:
        """
        Watch the session of ``workspace_id`` until the block exits.

        :raises RuntimeError: when called off this observer's loop.
        """
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("a status-edge watch must run on the observer's event loop")
        watch = _Watch(self._loop, slot_id)
        watched = self._sessions.setdefault(session_id, {}).setdefault(
            workspace_id, _WatchedSession()
        )
        watched.watches = (*watched.watches, watch)
        try:
            yield watch
        finally:
            watched.watches = tuple(item for item in watched.watches if item is not watch)
            if not watched.watches:
                by_workspace = self._sessions.get(session_id, {})
                by_workspace.pop(workspace_id, None)
                if not by_workspace:
                    self._sessions.pop(session_id, None)

    def observe(self, edge: SessionStatusEdge) -> None:
        """The S1 observer: any thread, never blocks or raises."""
        try:
            by_workspace = self._sessions.get(edge.session_id)
            if by_workspace is None:
                return
            watched = by_workspace.get(edge.workspace_id)
            if watched is None or not watched.watches:
                return
            self._loop.call_soon_threadsafe(self._deliver, watched, edge)
        except RuntimeError:
            # The loop has closed: nobody is left to wait.
            return
        except Exception:  # an observer bug must not break the publish
            _logger.warning("Coral status-edge observer failed", exc_info=True)

    def _deliver(self, watched: _WatchedSession, edge: SessionStatusEdge) -> None:
        if not watched.watches:
            return
        view = _view(edge)
        raw = {**dataclasses.asdict(edge), "slot_id": watched.watches[0].slot_id}
        fact = observe_status_edge(raw)
        if fact is None:
            return
        observed = ObservedEdge(edge=view, fact=fact)
        for watch in watched.watches:
            watch.deliver(observed)
        if self._sink is not None:
            try:
                self._sink(fact)
            except Exception:  # the sink must not break the waiters
                _logger.warning("Coral turn-fact sink failed", exc_info=True)


def _view(edge: SessionStatusEdge) -> StatusEdgeView:
    return StatusEdgeView(
        session_id=edge.session_id,
        status=edge.status,
        previous_status=edge.previous_status,
        origin=edge.origin,
        turn_outcome=edge.turn_outcome,
        turn_response_id=edge.turn_response_id,
        response_id=edge.response_id,
        blocked_on=edge.blocked_on,
        observed_at_ms=edge.observed_at_ms,
    )


__all__ = ["HISTORY_LIMIT", "CoralStatusEdges"]
