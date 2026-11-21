"""Engine input to Omnigent sessions without an HTTP request (K4 ``SessionDispatch``).

Every engine event goes through ``app.state.session_event_dispatch`` (the
server's own event handler) as an ``EngineEventContext`` for the run owner,
so the server's access, closed-session, input-policy and relaunch checks
apply as for a person. The caller runs inside the run's scopes, so a relaunch
can only reach the owner's host.

A message is sent once under the stable id the engine recorded before
sending. Before each send the dispatch reads the item (or queued entry)
stored under that id and takes it as the engine's only when the run owner
wrote it with the exact engine text. An item someone else put under the id
does not suppress the message, which then goes under the id's fallback.

Omnigent saves a message before forwarding it, so a saved engine item does
not prove the runner got it. It counts as sent once the runner shows it took
it: the session is ``running`` or ``waiting``, or anything follows the item.
Otherwise the message is sent again under the same id, which Omnigent
forwards again as an exact retry. Every message starts with a fixed line, so
no harness reads it as a command.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Any, override

from coral.model.ids import fallback_message_id
from coral.omni._upstream import (
    _session_active_response_cache,
    _session_blocked_on_cache,
    _session_status_cache,
    attribution_user,
    pending_elicitation_count,
)
from coral.omni.protocols import (
    MAX_ENGINE_MESSAGE_BYTES,
    CoralSessionError,
    LiveStatus,
    PreSendHook,
    PreSendRequest,
    SendReceipt,
    SessionDispatch,
    TranscriptItem,
    TurnTranscript,
    TurnTranscripts,
    engine_message_text,
    queued_input_decision,
    turn_transcript_of,
)
from coral.omni.server.access import omnigent_owner
from coral.signals.turn_facts import UNDECIDED
from coral.stores.stable_ids import content_checksum
from omnigent.db.db_models import workspace_scope
from omnigent.entities import Conversation, ConversationItem, ErrorData, MessageData
from omnigent.errors import ErrorCode, OmnigentError, StaleCursorError
from omnigent.runtime import pending_inputs
from omnigent.server.routes.sessions import ensure_runner_connected
from omnigent.server.schemas import SessionEventInput
from omnigent.server.startup_inputs import EngineEventContext
from omnigent.stores.conversation_store import ConversationStore
from omnigent.util.session_lifecycle import (
    CLOSED_LABEL_KEY,
    CLOSED_LABEL_VALUE,
    is_session_closed,
)

_logger = logging.getLogger(__name__)

# The longest one engine event may take, a host relaunch included.
SEND_TIMEOUT_S = 120.0
# The queued-input check reads this many items per page, and at most this many in all.
QUEUED_INPUT_PAGE = 50
QUEUED_INPUT_SCAN_LIMIT = 1_000
# A session whose runner is at work: it took the last message.
_RUNNER_AT_WORK = frozenset({"running", "waiting"})
# Items only a person creates, whoever is recorded as their author.
_CLIENT_COMMAND_TYPES = frozenset({"slash_command", "terminal_command"})
# Items a turn writes besides its replies; the error is the one a failed turn records.
_RUNNER_ITEM_TYPES = frozenset(
    {"reasoning", "function_call", "function_call_output", "native_tool", "error"}
)
# Runner bookkeeping, which is no evidence of a reply.
_BOOKKEEPING_TYPES = frozenset({"resource_event", "routing_decision", "compaction"})
_NOT_PERMITTED = frozenset({ErrorCode.FORBIDDEN, ErrorCode.UNAUTHORIZED})
_UNAVAILABLE = frozenset(
    {
        ErrorCode.RUNNER_UNAVAILABLE,
        ErrorCode.HOST_OFFLINE,
        ErrorCode.WRONG_REPLICA,
        ErrorCode.CONFLICT,
    }
)


def _refused(code: str, message: str, *, retryable: bool = False) -> CoralSessionError:
    return CoralSessionError(code, message, retryable=retryable)


def _single_text(content: object) -> str | None:
    """The text of content that is exactly one ``input_text`` block, as engine messages are."""
    if (
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], dict)
        and content[0].get("type") == "input_text"
        and isinstance(text := content[0].get("text"), str)
    ):
        return text
    return None


def _checksum(text: str | None) -> bytes | None:
    if text is None:
        return None
    try:
        return content_checksum(text)
    except UnicodeEncodeError:
        return None


def _engine_item(item: ConversationItem, author: str | None, checksum: bytes | None) -> bool:
    """The item is the engine's message: a user message by the run owner with the recorded text."""
    data = item.data
    return (
        checksum is not None
        and item.type == "message"
        and isinstance(data, MessageData)
        and data.role == "user"
        and item.created_by == author
        and _checksum(_single_text(data.content)) == checksum
    )


def _engine_entry(entry: Mapping[str, Any], author: str | None, checksum: bytes) -> bool:
    """A queued entry is the engine's: by the run owner, with the recorded text."""
    return entry.get("created_by") == author and (
        _checksum(_single_text(entry.get("content"))) == checksum
    )


def _client_input(item: ConversationItem) -> bool:
    """Anything a client created: a person's item, a command, or a user message, meta or not."""
    if item.created_by is not None or item.type in _CLIENT_COMMAND_TYPES:
        return True
    data = item.data
    return (
        isinstance(data, MessageData)
        and data.role == "user"
        and (data.user_authored or data.is_meta)
    )


def _transcript_item(
    item: ConversationItem, author: str | None, candidates: Mapping[str, bytes]
) -> TranscriptItem:
    """How the queued-input check and the turn transcript read one item."""
    client_input = _client_input(item)
    assistant = (
        item.type == "message"
        and isinstance(item.data, MessageData)
        and item.data.role == "assistant"
    )
    # A server notice, such as a recreated workspace, says nothing about the turn.
    notice = (
        item.type == "error" and isinstance(item.data, ErrorData) and item.data.level == "info"
    )
    return TranscriptItem(
        item.id,
        engine=_engine_item(item, author, candidates.get(item.id)),
        client_input=client_input,
        runner=not client_input and not notice and (assistant or item.type in _RUNNER_ITEM_TYPES),
        assistant=assistant,
        bookkeeping=notice or item.type in _BOOKKEEPING_TYPES,
    )


def _engine_candidates(engine_messages: Mapping[str, bytes]) -> dict[str, bytes]:
    """The engine's ids and their fallbacks: a message sent under a fallback carries its text."""
    candidates = dict(engine_messages)
    for stable_id, checksum in engine_messages.items():
        candidates.setdefault(fallback_message_id(stable_id), checksum)
    return candidates


def _pending_entry(session_id: str, stable_id: str) -> Mapping[str, Any] | None:
    """The queued (not yet persisted) entry under ``stable_id``, if any."""
    pending_id = pending_inputs.pending_id_for_stable_id(session_id, stable_id)
    if pending_id is None:
        return None
    for entry in pending_inputs.snapshot_for(session_id):
        if entry.get("pending_id") == pending_id:
            return entry
    return None


def _engine_context(app: Any, user_id: str | None) -> EngineEventContext:
    """
    The run owner as the server's access checks read it (:func:`omnigent_owner`).

    The local user is usually an admin, so an ownerless run's reach rests on its
    session ids, which come only from the run's own bindings.
    """
    return EngineEventContext(app, omnigent_owner(user_id))


class OmnigentSessionDispatch(SessionDispatch, TurnTranscripts):
    """
    The engine's session events on this server.

    :param pre_send_hooks: Run before a message is sent, never before an
        interrupt, stop or close; one raising ``CoralSessionError`` refuses it.
        Required, so a server never forgets the drift hook.
    :param send_timeout_s: The longest one event may take.
    """

    def __init__(
        self,
        app: Any,
        conversation_store: ConversationStore,
        runner_router: Any,
        *,
        pre_send_hooks: Sequence[PreSendHook],
        send_timeout_s: float = SEND_TIMEOUT_S,
    ) -> None:
        self._app = app
        self._store = conversation_store
        self._runner_router = runner_router
        self._hooks = tuple(pre_send_hooks)
        self._send_timeout_s = send_timeout_s

    @override
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
        message = engine_message_text(text)
        checksum = _checksum(message)
        if checksum is None:
            raise _refused("dispatch.invalid_input", "the engine message is not valid UTF-8 text")
        if len(message.encode()) > MAX_ENGINE_MESSAGE_BYTES:
            raise _refused(
                "dispatch.message_too_large",
                f"an engine message is at most {MAX_ENGINE_MESSAGE_BYTES} bytes",
            )
        with workspace_scope(workspace_id):
            conv = await asyncio.to_thread(self._store.get_conversation, session_id)
            send_id = stable_id
            if conv is not None:
                found = await self._prior_send(
                    session_id, stable_id, attribution_user(user_id), checksum
                )
                if isinstance(found, SendReceipt):
                    return found
                send_id = found
            request = PreSendRequest(
                workspace_id=workspace_id, run_id=run_id, session_id=session_id, user_id=user_id
            )
            for hook in self._hooks:
                await hook(request)
            if conv is None:
                raise _refused("session.deleted", f"session {session_id} no longer exists")
            if is_session_closed(conv.labels, conv.title):
                raise _refused("dispatch.session_closed", f"session {session_id} is closed")
            event = SessionEventInput(
                type="message",
                data={
                    "role": "user",
                    "content": [{"type": "input_text", "text": message}],
                    "stable_id": send_id,
                },
            )
            result = await self._send(conv, user_id, event)
        if result.get("denied") is True:
            raise _refused(
                "dispatch.policy_denied",
                f"the session's input policy refused the message: {result.get('reason') or ''}",
            )
        item_id = result.get("item_id")
        pending_id = result.get("pending_id")
        return SendReceipt(
            item_id=item_id if isinstance(item_id, str) else None,
            delivery="sent",
            pending_id=pending_id if isinstance(pending_id, str) else None,
        )

    async def _prior_send(
        self, session_id: str, stable_id: str, author: str | None, checksum: bytes
    ) -> SendReceipt | str:
        """
        The receipt of an earlier send the runner took, or the id to send under now.

        :raises CoralSessionError: Permanent ``dispatch.stable_id_taken`` when
            other items hold both the id and its fallback.
        """
        for candidate in (stable_id, fallback_message_id(stable_id)):
            item = await asyncio.to_thread(self._store.get_item, session_id, candidate)
            if item is not None:
                if _engine_item(item, author, checksum):
                    if await self._taken_by_runner(session_id, item.id):
                        return SendReceipt(item_id=item.id, delivery="already_persisted")
                    _logger.info(
                        "Engine message %s in session %s was saved but not delivered; resending",
                        candidate,
                        session_id,
                        extra={"session_id": session_id},
                    )
                    return candidate
            else:
                entry = _pending_entry(session_id, candidate)
                if entry is None:
                    return candidate
                if _engine_entry(entry, author, checksum):
                    return SendReceipt(
                        item_id=None,
                        delivery="already_persisted",
                        pending_id=str(entry["pending_id"]),
                    )
            _logger.warning(
                "Engine message id %s in session %s holds another item; trying its fallback",
                candidate,
                session_id,
                extra={"session_id": session_id},
            )
        raise _refused(
            "dispatch.stable_id_taken",
            f"other items hold engine message {stable_id} and its fallback "
            f"in session {session_id}",
        )

    async def _taken_by_runner(self, session_id: str, item_id: str) -> bool:
        """The runner took the saved item: it is at work, or anything follows the item."""
        if (await self.live_status(session_id=session_id)).status in _RUNNER_AT_WORK:
            return True
        newest = await asyncio.to_thread(self._store.list_items, session_id, limit=1, order="desc")
        return not newest.data or newest.data[0].id != item_id

    async def _send(
        self, conv: Conversation, user_id: str | None, event: SessionEventInput
    ) -> dict[str, Any]:
        session_id = conv.id
        try:
            async with asyncio.timeout(self._send_timeout_s):
                await self._connect_runner(conv)
                with contextlib.ExitStack() as in_flight:
                    return await self._app.state.session_event_dispatch(
                        _engine_context(self._app, user_id), session_id, event, in_flight
                    )
        except TimeoutError:
            raise _refused(
                "dispatch.runner_unavailable",
                f"session {session_id} did not take the message within {self._send_timeout_s:g} s",
                retryable=True,
            ) from None
        except OmnigentError as exc:
            if exc.code == ErrorCode.CONFLICT:
                current = await asyncio.to_thread(self._store.get_conversation, session_id)
                if current is not None and is_session_closed(current.labels, current.title):
                    raise _refused(
                        "dispatch.session_closed", f"session {session_id} is closed"
                    ) from exc
            raise await self._failure(exc, session_id) from exc

    async def _connect_runner(self, conv: Conversation) -> None:
        """Wake the session's runner as a message would; a host refusal is permanent."""
        try:
            await ensure_runner_connected(
                session_id=conv.id,
                conv=conv,
                app_state=self._app.state,
                conversation_store=self._store,
                runner_router=self._runner_router,
                raise_host_refusal=True,
            )
        except OmnigentError as exc:
            if exc.code == ErrorCode.HARNESS_NOT_CONFIGURED:
                raise _refused("session.harness_not_configured", str(exc)) from exc
            if exc.code == ErrorCode.WORKSPACE_MISSING:
                raise _refused("session.workspace_missing", str(exc)) from exc
            raise

    @override
    async def interrupt(
        self, *, session_id: str, user_id: str | None, response_id: str | None = None
    ) -> bool:
        live = await self.live_status(session_id=session_id)
        if live.status != "running" or (
            response_id is not None and live.response_id != response_id
        ):
            return False
        await self._control(session_id, user_id, "interrupt")
        return True

    @override
    async def stop(self, *, session_id: str, user_id: str | None) -> None:
        """
        Stop the session's runner, as its owner.

        :raises CoralSessionError: Retryable ``dispatch.stop_unconfirmed`` when
            the server could not confirm that no runner of the session is alive.
        """
        await self._control(session_id, user_id, "stop_session")

    async def _control(self, session_id: str, user_id: str | None, event_type: str) -> None:
        unavailable = "dispatch.stop_unconfirmed" if event_type == "stop_session" else None
        try:
            async with asyncio.timeout(self._send_timeout_s):
                await self._app.state.session_event_dispatch(
                    _engine_context(self._app, user_id),
                    session_id,
                    SessionEventInput(type=event_type),
                    None,
                )
        except TimeoutError:
            raise _refused(
                unavailable or "dispatch.runner_unavailable",
                f"session {session_id} did not answer {event_type} in {self._send_timeout_s:g} s",
                retryable=True,
            ) from None
        except OmnigentError as exc:
            raise await self._failure(exc, session_id, unavailable=unavailable) from exc

    async def _failure(
        self, exc: OmnigentError, session_id: str, *, unavailable: str | None = None
    ) -> CoralSessionError:
        """The typed refusal for a server error; host text reaches only the run owner's record."""
        message = str(exc)
        if exc.code == ErrorCode.NOT_FOUND:
            # The server hides a session the user may not see behind a 404 too.
            current = await asyncio.to_thread(self._store.get_conversation, session_id)
            if current is None:
                return _refused("session.deleted", f"session {session_id} no longer exists")
            return _refused("dispatch.not_permitted", message)
        if exc.code in _NOT_PERMITTED:
            return _refused("dispatch.not_permitted", message)
        if exc.code == ErrorCode.INVALID_INPUT:
            return _refused("dispatch.invalid_input", message)
        if exc.code in _UNAVAILABLE:
            return _refused(unavailable or "dispatch.runner_unavailable", message, retryable=True)
        return _refused("dispatch.failed", message, retryable=True)

    @override
    async def set_closed(self, *, session_id: str) -> None:
        """
        Write ``omnigent.closed``, which makes the server refuse new user messages.

        The label is written directly, with no server access check: callers act
        only on a step session their run bound.
        """
        await asyncio.to_thread(
            self._store.set_labels, session_id, {CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE}
        )

    @override
    async def live_status(self, *, session_id: str) -> LiveStatus:
        """
        The status this replica's last edge published, else the row's.

        A running turn's response id comes from this replica's cache, else from
        the store: the newest item's, unless that is a user message (its turn
        has written nothing yet), when it stays unknown.

        :raises CoralSessionError: ``session.deleted`` when the row is gone.
        """
        conv = await asyncio.to_thread(self._store.get_conversation, session_id)
        if conv is None:
            raise _refused("session.deleted", f"session {session_id} no longer exists")
        status = _session_status_cache.get(session_id)
        warm = status is not None
        blocked_on = _session_blocked_on_cache.get(session_id)
        pending = pending_elicitation_count(session_id)
        response_id = _session_active_response_cache.get(session_id) if warm else None
        live = LiveStatus(
            status=status if warm else conv.live_status,
            response_id=response_id,
            blocked_on=(blocked_on or None) if blocked_on is not None else conv.blocked_on,
            pending_elicitations=pending or (0 if warm else conv.pending_elicitation_count or 0),
            background_work=bool(conv.background_work_running),
        )
        if live.status == "running" and response_id is None:
            return dataclasses.replace(
                live, response_id=await self._stored_response_id(session_id)
            )
        return live

    async def _stored_response_id(self, session_id: str) -> str | None:
        newest = await asyncio.to_thread(self._store.list_items, session_id, limit=1, order="desc")
        if not newest.data:
            return None
        item = newest.data[0]
        if isinstance(item.data, MessageData) and item.data.role == "user":
            return None
        return item.response_id or None

    async def _newest_first(
        self, session_id: str, author: str | None, candidates: Mapping[str, bytes]
    ) -> AsyncGenerator[list[TranscriptItem]]:
        """
        The session's items newest first, a page at a time, up to the scan limit.

        :raises StaleCursorError: when the transcript changed under the walk's cursor.
        """
        cursor: str | None = None
        scanned = 0
        while scanned < QUEUED_INPUT_SCAN_LIMIT:
            page = await asyncio.to_thread(
                self._store.list_items,
                session_id,
                limit=min(QUEUED_INPUT_PAGE, QUEUED_INPUT_SCAN_LIMIT - scanned),
                after=cursor,
                order="desc",
            )
            yield [_transcript_item(item, author, candidates) for item in page.data]
            if not page.has_more or not page.data:
                return
            scanned += len(page.data)
            cursor = page.last_id

    @override
    async def queued_user_input(
        self, *, session_id: str, user_id: str | None, engine_messages: Mapping[str, bytes]
    ) -> bool:
        author = attribution_user(user_id)
        candidates = _engine_candidates(engine_messages)
        if any(item.client_input for item in self._queued_items(session_id, candidates, author)):
            return True
        try:
            async with contextlib.aclosing(
                self._newest_first(session_id, author, candidates)
            ) as pages:
                async for page in pages:
                    decision = queued_input_decision(page)
                    if decision is not None:
                        return decision
        except StaleCursorError:
            return True
        # No engine message found where one should be: assume input is waiting.
        return True

    @override
    async def turn_transcript(
        self, *, session_id: str, user_id: str | None, engine_messages: Mapping[str, bytes]
    ) -> TurnTranscript:
        """
        The turn the newest input started: queued messages first, then pages of items.

        A walk that loses its cursor is undecided. One that reads its whole reach
        without an engine message or client input is ``beyond_reach``. A message the
        engine sent under a fallback id is reported by its primary id.
        """
        author = attribution_user(user_id)
        candidates = _engine_candidates(engine_messages)
        items = self._queued_items(session_id, candidates, author)
        read = 0
        if not any(item.engine for item in items):
            try:
                async with contextlib.aclosing(
                    self._newest_first(session_id, author, candidates)
                ) as pages:
                    async for page in pages:
                        items.extend(page)
                        read += len(page)
                        if any(item.engine for item in page):
                            break
            except StaleCursorError:
                return UNDECIDED
        transcript = turn_transcript_of(items)
        if transcript.newest_input is None and read >= QUEUED_INPUT_SCAN_LIMIT:
            transcript = dataclasses.replace(transcript, beyond_reach=True)
        primary = {fallback_message_id(stable_id): stable_id for stable_id in engine_messages}
        found = transcript.newest_engine_input_id
        if found in primary:
            return dataclasses.replace(transcript, newest_engine_input_id=primary[found])
        return transcript

    @staticmethod
    def _queued_items(
        session_id: str, candidates: Mapping[str, bytes], author: str | None
    ) -> list[TranscriptItem]:
        """Messages queued for the session, newest first; an engine one names its stable id."""
        engine_ids = {
            pending_id: stable_id
            for stable_id in candidates
            if (pending_id := pending_inputs.pending_id_for_stable_id(session_id, stable_id))
        }
        items: list[TranscriptItem] = []
        for entry in reversed(pending_inputs.snapshot_for(session_id)):
            pending_id = str(entry.get("pending_id"))
            stable_id = engine_ids.get(pending_id)
            engine = stable_id is not None and _engine_entry(entry, author, candidates[stable_id])
            items.append(
                TranscriptItem(
                    stable_id if engine and stable_id is not None else pending_id,
                    engine=engine,
                    client_input=not engine,
                    pending=True,
                )
            )
        return items


__all__ = [
    "QUEUED_INPUT_SCAN_LIMIT",
    "SEND_TIMEOUT_S",
    "OmnigentSessionDispatch",
]
