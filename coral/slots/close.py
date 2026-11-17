"""Close and cancel a step session, closed-first and bounded (``close_slot``, ``cancel_sessions``).

A close finishes an accepted handoff in this order, each step safe to repeat:

1. Wait for the turn to end: at most ``turn_end_s``, then interrupt the turn
   and wait ``interrupt_settle_s``; past that the stop below ends it. An open
   prompt (a pending approval, or a running turn parked on a terminal prompt)
   is never interrupted: the close is refused as retryable ``slot.close_blocked``.
2. Fingerprint the worktree (L1) at the turn end (writers only).
3. Close the session to new user messages (``omnigent.closed``).
4. Stop its runner, confirmed: no agent process or runner-owned git is left.
5. Writers only: fingerprint again, check that the session has not restarted
   since the stop (retryable ``slot.close_restarted``), then commit at the HEAD
   recorded before the first try. The commit acts at a turn end only because
   this close just confirmed its own stop; the ``omnigent.closed`` label alone
   proves nothing, and a writer's close always sets it.
6. Measure the commit (``diff_stat``); a failure is retryable.
7. Look for client input after the engine's last message; the closed label
   makes the answer complete.

``pending_input`` is true when client input is queued or the tree changed after
the turn end, so the user reviews before the run goes on. A message accepted
between the turn end and the close is queued input; edits its turn made before
the stop are in the commit, flagged by ``post_accept_edits``.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol

from coral.omni.protocols import (
    CoralSessionError,
    EdgePredicate,
    EdgeWatch,
    LiveStatus,
    ObservedEdge,
    SessionDispatch,
    SessionEdgeWatcher,
)
from coral.stores.workspace_op_intents import WorkspaceOpIntents
from coral.workspace.executors import TURN_STATE_UNKNOWN, commit_and_diff, recorded_head
from coral.workspace.ops import CommitResult, DiffStat, StepSession, WorkspaceOps, WorkspaceRef

TurnState = Literal["prompt_open", "running", "ended"]
# Statuses with no turn running: ``waiting`` has only background work left.
ENDED_STATUSES = frozenset({"idle", "failed", "waiting"})
TURN_END_S = 120.0
INTERRUPT_SETTLE_S = 30.0
# Statuses of a session whose runner may still be at work.
LIVE_STATUSES = frozenset({"running", "waiting"})
EnsureLease = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class CloseBounds:
    """How long a close waits for the turn to end, then for an interrupt to settle."""

    turn_end_s: float = TURN_END_S
    interrupt_settle_s: float = INTERRUPT_SETTLE_S


DEFAULT_BOUNDS = CloseBounds()


@dataclass(frozen=True)
class CommitSpec:
    """
    The commit a writer's close makes in the run worktree.

    :param expected_head: The HEAD the payload recorded, used when no intent is stored yet.
    :param diff_from: The commit ``diff_stat`` starts at; the recorded HEAD by default.
    """

    workspace: WorkspaceOps
    ref: WorkspaceRef
    intents: WorkspaceOpIntents
    workspace_id: int
    run_id: str
    op_key: str
    message: str
    attempt_id: str
    expected_head: str | None = None
    diff_from: str | None = None


@dataclass(frozen=True)
class CloseOutcome:
    """
    What a close found and did.

    :param pending_input: ``queued_input`` or ``post_accept_edits``: the user reviews first.
    :param forced_stop: The turn had not ended when the stop ended it (logged, not returned).
    """

    pending_input: bool
    queued_input: bool
    post_accept_edits: bool
    commit: str | None
    empty: bool | None
    diff_stat: DiffStat | None
    forced_stop: bool


class CloseBlocked(CoralSessionError):
    """A prompt is open; the close waits for the user instead of interrupting it."""

    def __init__(self, session_id: str) -> None:
        super().__init__(
            "slot.close_blocked",
            f"step session {session_id} waits on an open prompt; it is not interrupted",
            retryable=True,
        )


class CloseRestarted(CoralSessionError):
    """The session ran again after the close's stop; the retry stops it again."""

    def __init__(self, session_id: str) -> None:
        super().__init__(
            "slot.close_restarted",
            f"step session {session_id} restarted after the close stopped it; not committed",
            retryable=True,
        )


class StatusEdgeLike(Protocol):
    """The fields of a published status edge that clear a confirmed stop."""

    @property
    def workspace_id(self) -> int: ...

    @property
    def session_id(self) -> str: ...

    @property
    def status(self) -> str: ...


class ConfirmedStops:
    """
    Sessions a close stopped with a confirmed stop, keyed by workspace and session.

    A later ``running`` edge (the session ran again) clears the record:
    register :meth:`observe` as a status-edge observer. In memory only, so
    after a restart nothing is recorded and a check that needs a stop answers
    that the state is unknown. Safe from any thread.
    """

    def __init__(self, *, limit: int = 4096) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._stopped: OrderedDict[tuple[int, str], None] = OrderedDict()

    def record(self, workspace_id: int, session_id: str) -> None:
        key = (workspace_id, session_id)
        with self._lock:
            self._stopped[key] = None
            self._stopped.move_to_end(key)
            while len(self._stopped) > self._limit:
                self._stopped.popitem(last=False)

    def confirmed(self, workspace_id: int, session_id: str) -> bool:
        with self._lock:
            return (workspace_id, session_id) in self._stopped

    def observe(self, edge: StatusEdgeLike) -> None:
        """A status-edge observer: a ``running`` edge drops the session's record."""
        if edge.status != "running":
            return
        with self._lock:
            self._stopped.pop((edge.workspace_id, edge.session_id), None)


class StopConfirmedTurnEnd:
    """
    ``workspace.commit``'s turn-end check: the session is ``idle`` and a close confirmed its stop.

    ``False`` while the session runs a turn, has background work (``waiting``)
    or waits on a prompt, a relaunch after the stop included. Otherwise,
    without a recorded stop, the state is unknown: the closed label is
    client-settable, so it is never taken as one.
    """

    def __init__(self, dispatch: SessionDispatch, stops: ConfirmedStops) -> None:
        self._dispatch = dispatch
        self._stops = stops

    async def __call__(self, *, workspace_id: int, run_id: str, session_id: str) -> bool:
        live = await self._dispatch.live_status(session_id=session_id)
        if _restarted(live):
            return False
        if live.status == "idle" and self._stops.confirmed(workspace_id, session_id):
            return True
        raise CoralSessionError(
            TURN_STATE_UNKNOWN,
            f"no confirmed stop of idle step session {session_id} is recorded in run {run_id}",
            retryable=True,
        )


def turn_state(live: LiveStatus) -> TurnState:
    """
    Where a session's turn is.

    A prompt is open when an approval is pending, or when a running turn is
    parked on a terminal prompt. ``waiting`` is an ended turn with background
    work left; an unknown status counts as ended.
    """
    if live.pending_elicitations > 0 or (live.status == "running" and live.blocked_on):
        return "prompt_open"
    if live.status == "running":
        return "running"
    return "ended"


def outcome_for(response_id: str | None) -> EdgePredicate:
    """An edge reporting an outcome for ``response_id``; an outcome with no response never is."""

    def matches(observed: ObservedEdge) -> bool:
        edge = observed.edge
        return (
            response_id is not None
            and edge.turn_response_id == response_id
            and observed.fact.turn_outcome is not None
        )

    return matches


def turn_ended(response_id: str | None) -> EdgePredicate:
    """
    The turn of ``response_id`` ended: its outcome, or a status with no turn running.

    An outcome reported for another response names another turn, so it never
    ends this one. With the response unknown, the first terminal edge does.
    """

    def matches(observed: ObservedEdge) -> bool:
        edge = observed.edge
        if response_id is None:
            return edge.turn_outcome is not None or edge.status in ENDED_STATUSES
        if edge.turn_outcome is not None and edge.turn_response_id is not None:
            return edge.turn_response_id == response_id
        return edge.status in ENDED_STATUSES

    return matches


def _restarted(live: LiveStatus) -> bool:
    """The runner is at work again, or a prompt is open."""
    return live.status in LIVE_STATUSES or turn_state(live) == "prompt_open"


async def close_session(
    *,
    workspace_id: int,
    session_id: str,
    user_id: str | None,
    slot_id: str,
    interrupt: bool,
    closed_label: bool,
    commit: CommitSpec | None,
    engine_messages: Mapping[str, bytes],
    dispatch: SessionDispatch,
    edges: SessionEdgeWatcher,
    ensure_lease: EnsureLease,
    bounds: CloseBounds = DEFAULT_BOUNDS,
    stops: ConfirmedStops | None = None,
) -> CloseOutcome:
    """
    Close a step session in the order in the module docstring.

    :param commit: The writer's commit; ``None`` for a reader, which never commits.
    :param closed_label: ``False`` skips step 3 for a reader, so a user message
        can relaunch its runner after the stop. A writer's close must set it.
    :param engine_messages: The engine's stable ids for the session and the
        checksums of their texts, for the queued-input check.
    :param stops: Records the close's confirmed stop; a ``running`` edge it
        observes afterwards makes the commit refuse.
    :raises CloseBlocked: A prompt is open; nothing was changed.
    :raises CloseRestarted: The session ran again after the stop; nothing was committed.
    :raises CoralSessionError: From dispatch, e.g. retryable ``dispatch.stop_unconfirmed``.
    :raises ValueError: A writer's close without the closed label.
    """
    if commit is not None and not closed_label:
        raise ValueError("a writer's close sets the closed label")
    reader = StepSession(session_id, writable=commit is not None, at_turn_end=False)
    forced_stop = await _end_turn(
        edges.watch(session_id, workspace_id=workspace_id, slot_id=slot_id),
        session_id=session_id,
        user_id=user_id,
        interrupt=interrupt,
        dispatch=dispatch,
        ensure_lease=ensure_lease,
        bounds=bounds,
    )
    turn_end_tree = (
        await commit.workspace.fingerprint(commit.ref, reader, level="L1")
        if commit is not None
        else None
    )
    if closed_label:
        await ensure_lease()
        await dispatch.set_closed(session_id=session_id)
    await ensure_lease()
    await dispatch.stop(session_id=session_id, user_id=user_id)
    if stops is not None:
        stops.record(workspace_id, session_id)
    post_accept_edits = False
    result: CommitResult | None = None
    stat: DiffStat | None = None
    if commit is not None and turn_end_tree is not None:
        stopped_tree = await commit.workspace.fingerprint(commit.ref, reader, level="L1")
        post_accept_edits = stopped_tree.digest != turn_end_tree.digest
        # Nothing may run between the stop and the commit; a retry stops it again.
        if _restarted(await dispatch.live_status(session_id=session_id)) or (
            stops is not None and not stops.confirmed(workspace_id, session_id)
        ):
            raise CloseRestarted(session_id)
        result, stat = await _commit(commit, session_id, reader, ensure_lease)
    queued_input = await dispatch.queued_user_input(
        session_id=session_id, user_id=user_id, engine_messages=engine_messages
    )
    return CloseOutcome(
        pending_input=queued_input or post_accept_edits,
        queued_input=queued_input,
        post_accept_edits=post_accept_edits,
        commit=None if result is None else result.commit,
        empty=None if result is None else result.empty,
        diff_stat=stat,
        forced_stop=forced_stop,
    )


async def cancel_session(
    *,
    workspace_id: int,
    session_id: str,
    user_id: str | None,
    slot_id: str,
    closed_label: bool,
    dispatch: SessionDispatch,
    edges: SessionEdgeWatcher,
    ensure_lease: EnsureLease,
    bounds: CloseBounds = DEFAULT_BOUNDS,
) -> None:
    """
    End a session for a cancelled run: interrupt a running turn, close it, then stop it.

    An open prompt is not waited on and not interrupted; the stop ends it.
    """
    async with edges.watch(session_id, workspace_id=workspace_id, slot_id=slot_id) as watch:
        live = await dispatch.live_status(session_id=session_id)
        if turn_state(live) == "running":
            await ensure_lease()
            if await dispatch.interrupt(
                session_id=session_id, user_id=user_id, response_id=live.response_id
            ):
                await watch.wait_for(
                    turn_ended(live.response_id), timeout_s=bounds.interrupt_settle_s
                )
    if closed_label:
        await ensure_lease()
        await dispatch.set_closed(session_id=session_id)
    await ensure_lease()
    await dispatch.stop(session_id=session_id, user_id=user_id)


async def _end_turn(
    watching: AbstractAsyncContextManager[EdgeWatch],
    *,
    session_id: str,
    user_id: str | None,
    interrupt: bool,
    dispatch: SessionDispatch,
    ensure_lease: EnsureLease,
    bounds: CloseBounds,
) -> bool:
    """
    Wait for the running turn to end; ``True`` when the stop will have to end it.

    The watch starts before the live status is read, so no edge is missed.
    Every read decides three ways: an open prompt is never waited past.

    :raises CloseBlocked: A prompt is or becomes open.
    """
    async with watching as watch:
        live = await dispatch.live_status(session_id=session_id)
        if not _still_running(live, session_id):
            return False
        ended = await watch.wait_for(turn_ended(live.response_id), timeout_s=bounds.turn_end_s)
        if ended is not None:
            return False
        live = await dispatch.live_status(session_id=session_id)
        if not _still_running(live, session_id):
            return False
        if not interrupt:
            return True
        await ensure_lease()
        sent = await dispatch.interrupt(
            session_id=session_id, user_id=user_id, response_id=live.response_id
        )
        # The read after the bound may name the running response the first could not.
        settled = turn_ended(live.response_id)
        if sent and await watch.wait_for(settled, timeout_s=bounds.interrupt_settle_s) is not None:
            return False
        return _still_running(await dispatch.live_status(session_id=session_id), session_id)


def _still_running(live: LiveStatus, session_id: str) -> bool:
    """
    Whether the turn still runs; ``False`` once it ended.

    :raises CloseBlocked: A prompt is open.
    """
    state = turn_state(live)
    if state == "prompt_open":
        raise CloseBlocked(session_id)
    return state == "running"


async def _commit(
    spec: CommitSpec, session_id: str, reader: StepSession, ensure_lease: EnsureLease
) -> tuple[CommitResult, DiffStat]:
    """The writer's commit, at the turn end this close's own confirmed stop established."""

    async def read_head() -> str:
        return (await spec.workspace.head(spec.ref, reader)).head

    expected_head = await recorded_head(
        spec.intents,
        workspace_id=spec.workspace_id,
        run_id=spec.run_id,
        op_key=spec.op_key,
        ref=spec.ref,
        payload_head=spec.expected_head,
        read_head=read_head,
        ensure_lease=ensure_lease,
    )
    return await commit_and_diff(
        spec.workspace,
        spec.ref,
        StepSession(session_id, writable=True, at_turn_end=True),
        op_key=spec.op_key,
        expected_head=expected_head,
        message=spec.message,
        run_id=spec.run_id,
        attempt_id=spec.attempt_id,
        diff_from=spec.diff_from,
        ensure_lease=ensure_lease,
    )


__all__ = [
    "DEFAULT_BOUNDS",
    "ENDED_STATUSES",
    "LIVE_STATUSES",
    "CloseBlocked",
    "CloseBounds",
    "CloseOutcome",
    "CloseRestarted",
    "CommitSpec",
    "ConfirmedStops",
    "StatusEdgeLike",
    "StopConfirmedTurnEnd",
    "TurnState",
    "cancel_session",
    "close_session",
    "outcome_for",
    "turn_ended",
    "turn_state",
]
