"""Protocols bridging Coral runtime components with the Omnigent host server.

App-tier modules reach the server only through these names, so this module
imports nothing but the standard library and pure Coral modules.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from coral.engine.facts import TurnFact
from coral.signals.turn_facts import TurnTranscript
from coral.workspace.ops import HostChannelBackend

HostAccessCode = Literal["not_permitted", "host_offline"]
# K4 session roles: the run's one anchor, or a step of an engine slot.
SessionRole = Literal["anchor", "step"]
SlotRoleName = Literal["step_agent", "orchestrator", "verifier", "merge_resolver"]
# The first line of every engine message, so a harness never reads it as a command.
ENGINE_MESSAGE_FIRST_LINE = "Message from the Coral engine:"
# An engine message's UTF-8 size, first line included: far above a brief, below the HTTP cap.
MAX_ENGINE_MESSAGE_BYTES = 1_048_576


def engine_message_text(text: str) -> str:
    """The exact text an engine message carries: the fixed first line, then ``text``."""
    return f"{ENGINE_MESSAGE_FIRST_LINE}\n{text}"


@dataclass(frozen=True)
class TranscriptItem:
    """
    One transcript item, as the queued-input check and the turn transcript read it.

    :param engine: The engine's own message: an id it recorded, by the run
        owner, with the exact text it recorded.
    :param client_input: Anything a client created: a user message (meta
        ones too), a slash or terminal command, or any item a person authored.
        Runner and server items, the interrupt marker among them, are not.
    :param runner: Written for the turn: an assistant reply, reasoning, a tool call
        or its output, or the error the turn failed with.
    :param assistant: An assistant reply.
    :param bookkeeping: Runner bookkeeping, such as a resource event: no reply.
    :param pending: A message taken but not yet persisted, newer than every item.
    """

    item_id: str
    engine: bool
    client_input: bool
    runner: bool = False
    assistant: bool = False
    bookkeeping: bool = False
    pending: bool = False


def queued_input_decision(newest_first: Iterable[TranscriptItem]) -> bool | None:
    """
    Whether client input follows the engine's last message, reading items newest first.

    The first item that is the engine's or client input decides: client input
    → ``True``, the engine's → ``False``.

    :returns: ``None`` when no item here decides.
    """
    for item in newest_first:
        if item.engine:
            return False
        if item.client_input:
            return True
    return None


def turn_transcript_of(newest_first: Iterable[TranscriptItem]) -> TurnTranscript:
    """
    The turn the newest input started, reading items newest first, queued ones before.

    The walk stops at the first engine message. Client input before it makes the
    newest input the user's; without any engine message the walk decides only that.
    """
    newest_substantive: bool | None = None
    runner_after = client_after = False
    for item in newest_first:
        if item.engine:
            return TurnTranscript(
                newest_input="user" if client_after else "engine",
                newest_engine_input_id=item.item_id,
                newest_substantive_item_is_assistant=newest_substantive is True,
                runner_item_after_engine_input=runner_after,
                engine_pending_input=item.pending,
            )
        client_after = client_after or item.client_input
        runner_after = runner_after or item.runner
        if newest_substantive is None and not item.bookkeeping:
            newest_substantive = item.assistant
    return TurnTranscript(
        newest_input="user" if client_after else None,
        newest_engine_input_id=None,
        newest_substantive_item_is_assistant=newest_substantive is True,
        runner_item_after_engine_input=runner_after,
        engine_pending_input=False,
    )


@runtime_checkable
class RunScopeRunner(Protocol):
    """Protocol for entering host ambient scopes around background work or reconciliation."""

    def run_scope(
        self,
        *,
        workspace_id: int,
        run_id: str | None = None,
        user_id: str | None = None,
        account_generation: str | None = None,
        host_id: str | None = None,
        owner_key: str | None = None,
    ) -> AbstractAsyncContextManager[None]: ...


class NoOpScopeRunner:
    """Default no-op RunScopeRunner for standalone tests or environments without host scopes."""

    @asynccontextmanager
    async def run_scope(
        self,
        *,
        workspace_id: int,
        run_id: str | None = None,
        user_id: str | None = None,
        account_generation: str | None = None,
        host_id: str | None = None,
        owner_key: str | None = None,
    ) -> AsyncIterator[None]:
        del workspace_id, run_id, user_id, account_generation, host_id, owner_key
        yield


class CoralSessionError(Exception):
    """
    A Coral session operation failed with a typed code, e.g. ``session.deleted``.

    :param retryable: A later attempt may succeed, e.g. ``session.host_offline``.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


class HostAccessRefused(Exception):
    """
    The run owner may not use the host now.

    :param code: ``not_permitted``: an unknown host, another user's or account
        registration's host, a managed sandbox, or a connection another owner
        holds; retrying cannot help. ``host_offline``: no live connection yet.
    :param message: Names only the caller's own host.
    """

    def __init__(self, code: HostAccessCode, message: str) -> None:
        super().__init__(message)
        self.code: HostAccessCode = code
        self.message = message


@runtime_checkable
class HostWorkspaceChannels(Protocol):
    """Hands out the host workspace-op channel for a run owner's host."""

    async def channel(
        self,
        *,
        workspace_id: int,
        user_id: str | None,
        account_generation: str | None,
        host_id: str,
    ) -> HostChannelBackend:
        """
        Authorize the run owner for ``host_id`` from its stored row, before any frame.

        Callers take every argument from the stored run, never from a payload.

        :param user_id: ``None`` only when auth is off, which skips the owner checks.
        :raises HostAccessRefused: ``not_permitted`` when the owner may not use the host.
        """
        ...


@dataclass(frozen=True)
class SessionCreateRequest:
    """
    One ``create_session`` effect, with its identity taken from the stored run.

    :param effect_key: Derives a step's session id; an anchor's id comes from ``run_id``.
    :param user_id: The run owner, or ``None`` when auth is off.
    :param title: The session title; a step's is unique under the anchor.
    :param host_id: A step's host, from the run spec.
    :param workspace: A step's canonical run worktree, from the run spec.
    :param engine_slot_id: The engine slot a step serves.
    :param slot_role: Decides whether the step may commit; required for steps.
    :param generation: The slot's session generation, from 1.
    """

    workspace_id: int
    run_id: str
    effect_key: str
    user_id: str | None
    account_generation: str | None
    role: SessionRole
    title: str
    agent_id: str | None = None
    host_id: str | None = None
    workspace: str | None = None
    engine_slot_id: str | None = None
    slot_role: SlotRoleName | None = None
    node_id: str | None = None
    generation: int = 1


@dataclass(frozen=True)
class SessionRef:
    """A created or adopted session; ``created`` is ``False`` when an earlier try made it."""

    session_id: str
    role: SessionRole
    created: bool


@dataclass(frozen=True)
class SessionState:
    """
    What drift checks read about one session.

    :param exists: ``False`` once the session row is gone.
    :param archived_at: The archive timestamp label, when archived.
    :param closed: ``omnigent.closed`` is set.
    """

    session_id: str
    exists: bool
    archived: bool
    archived_at: str | None
    closed: bool
    runner_id: str | None
    host_id: str | None


@dataclass(frozen=True)
class LiveStatus:
    """A session's live status, as a close or cancel reads it."""

    status: str | None
    response_id: str | None
    blocked_on: str | None
    pending_elicitations: int
    background_work: bool


@dataclass(frozen=True)
class SendReceipt:
    """How a message reached its session: sent now, or found already persisted."""

    item_id: str | None
    delivery: Literal["sent", "already_persisted"]
    pending_id: str | None = None


@dataclass(frozen=True)
class StatusEdgeView:
    """
    The fields of a status edge a close or cancel waits on.

    :param turn_response_id: The response ``turn_outcome`` reports on.
    :param response_id: The response a ``running`` edge opens.
    """

    session_id: str
    status: str
    previous_status: str | None
    origin: str
    turn_outcome: str | None
    turn_response_id: str | None
    response_id: str | None
    blocked_on: str | None
    observed_at_ms: int


@dataclass(frozen=True)
class ObservedEdge:
    """A watched session's status edge and the turn fact made from it."""

    edge: StatusEdgeView
    fact: TurnFact


@dataclass(frozen=True)
class PreSendRequest:
    """An engine message about to be sent, checked by each ``PreSendHook``."""

    workspace_id: int
    run_id: str
    session_id: str
    user_id: str | None


@runtime_checkable
class SessionFacade(Protocol):
    """Creates the run's anchor and step sessions without an HTTP request (K4 subset)."""

    async def create_session(
        self,
        request: SessionCreateRequest,
        *,
        ensure_lease: Callable[[], Awaitable[None]],
    ) -> SessionRef:
        """
        Create the session ``request`` names, or adopt the one an earlier try made.

        A redelivery reuses one session; a deleted one is never created again.

        :param ensure_lease: Called before every external side effect.
        :raises CoralSessionError: With a ``session.*`` code and its retryability.
        """
        ...

    async def session_state(self, *, workspace_id: int, session_id: str) -> SessionState:
        """Read one session's state for drift checks."""
        ...


@runtime_checkable
class StepAgentResolver(Protocol):
    """Turns a step's stance into the agent its session runs, materialized as the run owner's."""

    async def resolve(
        self,
        *,
        workspace_id: int,
        owner: str | None,
        stance: str,
        workflow_slug: str | None,
        node_id: str | None,
        roster_index: int | None,
        session_id: str | None = None,
    ) -> str:
        """
        The agent id of the stance's Coral bundle; the orchestrator's needs no step reference.

        Runs inside the run's scopes; a repeat for the same bundle returns the same agent.

        :param owner: The run's user, or ``None`` for an ownerless run (single-user servers).
        :param session_id: The session the create makes: when an earlier try wrote it,
            its agent is kept while it is still this stance's bundle of the owner.
        :raises CoralSessionError: Permanent ``session.agent_not_supported`` when no
            bundle can be built for the stance and step; permanent ``session.invalid``
            for an ownerless run on a server that is not single-user.
        """
        ...


@runtime_checkable
class SessionDispatch(Protocol):
    """
    Sends engine input to a session and reads its live state (K4 subset).

    Every method runs inside the caller's run scope and acts as the run owner
    (``user_id``); failures raise ``CoralSessionError`` with a typed code.
    """

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
        """
        Send ``engine_message_text(text)`` once under ``stable_id``, recorded beforehand.

        The engine's message saved under the id counts as sent once the runner
        took it (the session is ``running`` or ``waiting``, or anything follows
        it); until then it is sent again under the same id.
        """
        ...

    async def interrupt(
        self, *, session_id: str, user_id: str | None, response_id: str | None = None
    ) -> bool:
        """Interrupt the running turn (``response_id``'s, when given); ``False`` if none runs."""
        ...

    async def stop(self, *, session_id: str, user_id: str | None) -> None:
        """Stop the session's runner; returns only once no runner of it is alive."""
        ...

    async def set_closed(self, *, session_id: str) -> None:
        """Close the session to new user messages."""
        ...

    async def live_status(self, *, session_id: str) -> LiveStatus: ...

    async def queued_user_input(
        self, *, session_id: str, user_id: str | None, engine_messages: Mapping[str, bytes]
    ) -> bool:
        """
        Whether client input follows the engine's last message (:func:`queued_input_decision`).

        :param engine_messages: Each stable id the engine recorded for the session
            and the sha256 of the exact text it sent under it.
        """
        ...


@runtime_checkable
class TurnTranscripts(Protocol):
    """Reads what a session's transcript shows about its newest turn (K4 subset)."""

    async def turn_transcript(
        self, *, session_id: str, user_id: str | None, engine_messages: Mapping[str, bytes]
    ) -> TurnTranscript:
        """
        :func:`turn_transcript_of` over the session's queued messages and its newest
        items, read in pages up to a bound; undecided past it.

        :param engine_messages: Each stable id the engine recorded for the session
            and the sha256 of the exact text it sent under it.
        """
        ...


# Matches a watched session's edge, e.g. the end of one turn.
EdgePredicate = Callable[[ObservedEdge], bool]


class EdgeWatch(Protocol):
    """Waits for a watched session's next matching status edge."""

    async def wait_for(
        self, predicate: EdgePredicate, *, timeout_s: float
    ) -> ObservedEdge | None: ...


class SessionEdgeWatcher(Protocol):
    """Watches one session's status edges while a close or cancel waits on them."""

    def watch(
        self, session_id: str, *, workspace_id: int, slot_id: str = ""
    ) -> AbstractAsyncContextManager[EdgeWatch]:
        """Watch ``session_id`` of ``workspace_id``; session ids repeat across workspaces."""
        ...


# Receives each turn fact of a watched session; the server sets none (turn facts persist
# through the ``coral.turn_facts`` observer).
TurnFactSink = Callable[[TurnFact], None]
# Runs before an engine message is sent; raises CoralSessionError to refuse it.
PreSendHook = Callable[[PreSendRequest], Awaitable[None]]


__all__ = [
    "ENGINE_MESSAGE_FIRST_LINE",
    "MAX_ENGINE_MESSAGE_BYTES",
    "CoralSessionError",
    "EdgePredicate",
    "EdgeWatch",
    "HostAccessCode",
    "HostAccessRefused",
    "HostWorkspaceChannels",
    "LiveStatus",
    "NoOpScopeRunner",
    "ObservedEdge",
    "PreSendHook",
    "PreSendRequest",
    "RunScopeRunner",
    "SendReceipt",
    "SessionCreateRequest",
    "SessionDispatch",
    "SessionEdgeWatcher",
    "SessionFacade",
    "SessionRef",
    "SessionRole",
    "SessionState",
    "SlotRoleName",
    "StatusEdgeView",
    "StepAgentResolver",
    "TranscriptItem",
    "TurnFactSink",
    "TurnTranscript",
    "TurnTranscripts",
    "engine_message_text",
    "queued_input_decision",
    "turn_transcript_of",
]
