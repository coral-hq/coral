"""Protocol fakes for the close, cancel and send tests: a session server and its edges."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from coral.db.enum_codecs import StableIdKind, encode_stable_id_kind
from coral.engine.facts import TurnFact
from coral.omni.protocols import (
    CoralSessionError,
    LiveStatus,
    ObservedEdge,
    SendReceipt,
    StatusEdgeView,
    TranscriptItem,
    engine_message_text,
    queued_input_decision,
)
from coral.stores.session_bindings import effect_checksum
from coral.stores.stable_ids import (
    StableIdConflict,
    StableIdRecord,
    content_checksum,
)

OWNER = "alice"
# What a test hooks: a callback the fake runs right after the named action.
Hooks = dict[str, Callable[[], None]]


def observed(
    session_id: str,
    status: str,
    *,
    outcome: str | None = None,
    turn_response_id: str | None = None,
    response_id: str | None = None,
) -> ObservedEdge:
    """One status edge as the edge watcher hands it to a waiter."""
    view = StatusEdgeView(
        session_id=session_id,
        status=status,
        previous_status=None,
        origin="unknown",
        turn_outcome=outcome,
        turn_response_id=turn_response_id,
        response_id=response_id,
        blocked_on=None,
        observed_at_ms=0,
    )
    fact = TurnFact(
        slot_id="",
        session_id=session_id,
        live_status=status,
        turn_outcome=outcome,
        response_id=turn_response_id or response_id,
    )
    return ObservedEdge(edge=view, fact=fact)


@dataclass(frozen=True)
class FakeItem:
    """
    A transcript item: its author and text, and whether a client created it.

    :param client_input: ``False`` for runner and server items, e.g. the interrupt marker.
    """

    item_id: str
    author: str | None
    text: str
    client_input: bool = True


@dataclass
class FakeSession:
    """A session as the server holds it: live state, labels, runner and transcript."""

    status: str | None = "idle"
    response_id: str | None = None
    blocked_on: str | None = None
    pending_elicitations: int = 0
    background_work: bool = False
    closed: bool = False
    runner_alive: bool = True
    # Oldest first.
    transcript: list[FakeItem] = field(default_factory=list)


class FakeDispatch:
    """
    ``SessionDispatch`` over in-memory sessions, recording each action in ``events``.

    It refuses a user message to a closed session as the server does, and
    answers ``queued_user_input`` with the production decision rule: an item
    is the engine's when its id, author and text checksum match a recorded send.

    :param hooks: Run right after an action of that name, e.g. ``"set_closed"``.
    """

    def __init__(self, events: list[str], *, owner: str | None = OWNER) -> None:
        self.events = events
        self.owner = owner
        self.sessions: dict[str, FakeSession] = {}
        self.hooks: Hooks = {}
        self.unconfirmed_stops = 0
        # Raised once, before the action of that name runs.
        self.refusals: dict[str, BaseException] = {}
        self.sends: list[dict[str, object]] = []
        self.interrupts: list[str | None] = []
        # Each stop that reached a session: its id and the user it ran as.
        self.stops: list[tuple[str, str | None]] = []
        self.settle_on_interrupt: Callable[[str], None] | None = None

    def session(self, session_id: str, **state: object) -> FakeSession:
        session = FakeSession(**state)  # type: ignore[arg-type]
        self.sessions[session_id] = session
        return session

    def post_user_message(
        self, session_id: str, item_id: str, *, author: str | None, text: str = "One more thing."
    ) -> None:
        """A person posts a message; refused once the session is closed."""
        session = self.sessions[session_id]
        if session.closed:
            raise CoralSessionError("dispatch.session_closed", f"session {session_id} is closed")
        session.transcript.append(FakeItem(item_id, author, text))

    def _act(self, name: str, session_id: str) -> FakeSession:
        self.events.append(name)
        refusal = self.refusals.pop(name, None)
        if refusal is not None:
            raise refusal
        return self.sessions[session_id]

    def _after(self, name: str) -> None:
        hook = self.hooks.get(name)
        if hook is not None:
            hook()

    async def send_message(
        self,
        *,
        workspace_id: int,
        run_id: str,
        session_id: str,
        user_id: str | None,
        stable_id: str,
        text: str,
    ) -> SendReceipt:
        session = self._act("send_message", session_id)
        self.sends.append(
            {"workspace_id": workspace_id, "run_id": run_id, "stable_id": stable_id, "text": text}
        )
        if any(item.item_id == stable_id for item in session.transcript):
            return SendReceipt(item_id=stable_id, delivery="already_persisted")
        session.transcript.append(FakeItem(stable_id, user_id, engine_message_text(text)))
        self._after("send_message")
        return SendReceipt(item_id=stable_id, delivery="sent")

    async def interrupt(
        self, *, session_id: str, user_id: str | None, response_id: str | None = None
    ) -> bool:
        session = self._act("interrupt", session_id)
        if session.status != "running" or (
            response_id is not None and session.response_id != response_id
        ):
            return False
        self.interrupts.append(response_id)
        if self.settle_on_interrupt is not None:
            self.settle_on_interrupt(session_id)
        self._after("interrupt")
        return True

    async def stop(self, *, session_id: str, user_id: str | None) -> None:
        session = self._act("stop", session_id)
        self.stops.append((session_id, user_id))
        if self.unconfirmed_stops:
            self.unconfirmed_stops -= 1
            raise CoralSessionError(
                "dispatch.stop_unconfirmed", "the runner did not confirm the stop", retryable=True
            )
        session.status = "idle"
        session.runner_alive = False
        session.background_work = False
        self._after("stop")

    async def set_closed(self, *, session_id: str) -> None:
        self._act("set_closed", session_id).closed = True
        self._after("set_closed")

    async def live_status(self, *, session_id: str) -> LiveStatus:
        session = self._act("live_status", session_id)
        live = LiveStatus(
            status=session.status,
            response_id=session.response_id,
            blocked_on=session.blocked_on,
            pending_elicitations=session.pending_elicitations,
            background_work=session.background_work,
        )
        self._after("live_status")
        return live

    async def queued_user_input(
        self, *, session_id: str, user_id: str | None, engine_messages: Mapping[str, bytes]
    ) -> bool:
        session = self._act("queued_user_input", session_id)
        decision = queued_input_decision(
            TranscriptItem(
                item.item_id,
                engine=item.author == user_id
                and engine_messages.get(item.item_id) == content_checksum(item.text),
                client_input=item.client_input,
            )
            for item in reversed(session.transcript)
        )
        return True if decision is None else decision


class FakeWatch:
    """
    One watch: waits see the edges delivered so far, then the ones ``arriving``.

    A wait that finds nothing returns ``None`` at once and records its timeout,
    as if the bound passed; nothing here sleeps.
    """

    def __init__(self, watcher: FakeEdgeWatcher, session_id: str) -> None:
        self._watcher = watcher
        self._session_id = session_id

    async def wait_for(
        self, predicate: Callable[[ObservedEdge], bool], *, timeout_s: float
    ) -> ObservedEdge | None:
        watcher = self._watcher
        watcher.events.append("wait_for")
        history = watcher.delivered.setdefault(self._session_id, [])
        for edge in history:
            if predicate(edge):
                return edge
        arriving = watcher.arriving.pop(self._session_id, [])
        for edge in arriving:
            history.append(edge)
            if predicate(edge):
                return edge
        watcher.timeouts.append(timeout_s)
        return None


class FakeEdgeWatcher:
    """``SessionEdgeWatcher`` whose edges a test delivers or schedules for the next wait."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.delivered: dict[str, list[ObservedEdge]] = {}
        self.arriving: dict[str, list[ObservedEdge]] = {}
        self.timeouts: list[float] = []
        self.watching: list[tuple[str, int, str]] = []

    def deliver(self, edge: ObservedEdge) -> None:
        self.delivered.setdefault(edge.edge.session_id, []).append(edge)

    def arrive_during_next_wait(self, edge: ObservedEdge) -> None:
        self.arriving.setdefault(edge.edge.session_id, []).append(edge)

    @asynccontextmanager
    async def watch(
        self, session_id: str, *, workspace_id: int, slot_id: str = ""
    ) -> AsyncIterator[FakeWatch]:
        self.events.append("watch")
        self.watching.append((session_id, workspace_id, slot_id))
        try:
            yield FakeWatch(self, session_id)
        finally:
            self.events.append("unwatch")


class FakeStableIds:
    """``StableIds`` with the store's insert-if-absent rule and its conflict on another send."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.rows: dict[tuple[int, str], StableIdRecord] = {}

    def record_send(
        self,
        workspace_id: int,
        *,
        stable_id: str,
        run_id: str,
        session_id: str,
        effect_key: str,
        kind: StableIdKind | str,
        generation: int,
        content: str,
    ) -> None:
        self.events.append("record_send")
        wanted = StableIdRecord(
            workspace_id=workspace_id,
            stable_id=stable_id,
            run_id=run_id,
            session_id=session_id,
            effect_cksum=effect_checksum(effect_key),
            content_cksum=content_checksum(content),
            kind=StableIdKind(encode_stable_id_kind(kind)),
            session_generation=generation,
            created_at=0,
        )
        stored = self.rows.setdefault((workspace_id, stable_id), wanted)
        if stored != wanted:
            raise StableIdConflict(f"stable id {stable_id} is recorded for another send")

    def lookup(self, workspace_id: int, stable_id: str, *, run_id: str) -> StableIdRecord | None:
        stored = self.rows.get((workspace_id, stable_id))
        return stored if stored is not None and stored.run_id == run_id else None

    def list_for_session(
        self, workspace_id: int, session_id: str, *, run_id: str
    ) -> frozenset[str]:
        return frozenset(self.checksums_for_session(workspace_id, session_id, run_id=run_id))

    def checksums_for_session(
        self, workspace_id: int, session_id: str, *, run_id: str
    ) -> dict[str, bytes]:
        return {
            record.stable_id: record.content_cksum
            for (ws, _), record in self.rows.items()
            if ws == workspace_id and record.session_id == session_id and record.run_id == run_id
        }
