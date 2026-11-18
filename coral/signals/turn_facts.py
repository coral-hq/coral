"""Turn facts from a status edge, the session's live state and its transcript. Pure.

A fact is keyed by the engine message that started the turn, so the edge path and a
re-gather without an edge build the same key. The turn's origin comes from the
transcript, never from the edge, whose ``origin`` names the publishing path.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Literal

from pydantic import JsonValue

from coral.engine.facts import TurnFact

# A failed turn rebuilt without its edge; the classifier reads it as transient.
EDGE_LOST = "edge_lost"
# A turn that is over but too long for the walk to find its engine message; transient,
# so the step is re-prompted with a message the next walk reaches.
TURN_UNREADABLE = "turn_unreadable"
_TURN_OVER = frozenset({"idle", "failed"})
# Edge text kept in a signal: codes and ids, and the error message.
MAX_EDGE_CODE_CHARS = 128
MAX_EDGE_MESSAGE_CHARS = 1_000
# Lone surrogates cannot be stored as UTF-8.
_SURROGATES = re.compile("[\ud800-\udfff]")

TurnInput = Literal["engine", "user"]


@dataclass(frozen=True)
class TurnTranscript:
    """
    What a session's transcript shows about the turn its newest input started.

    :param newest_input: Who wrote the newest input; ``None`` when the walk could not
        decide within its reach.
    :param newest_engine_input_id: The primary stable id of the newest engine message.
    :param newest_substantive_item_is_assistant: After that message, the newest item
        that is not runner bookkeeping is an assistant reply.
    :param runner_item_after_engine_input: A reply, reasoning, tool call, tool output
        or error item is newer than that message: the runner took it.
    :param engine_pending_input: That message is queued, not yet persisted.
    :param beyond_reach: The walk read its whole reach without finding an engine
        message or client input: the turn's message is older than that.
    """

    newest_input: TurnInput | None
    newest_engine_input_id: str | None
    newest_substantive_item_is_assistant: bool
    runner_item_after_engine_input: bool
    engine_pending_input: bool
    beyond_reach: bool = False


UNDECIDED = TurnTranscript(None, None, False, False, False)


@dataclass(frozen=True)
class LiveFacts:
    """The session's live state when the facts were gathered."""

    status: str | None
    pending_elicitations: int
    background_work: bool


@dataclass(frozen=True)
class EdgeFacts:
    """
    The bounded fields of one status edge a signal keeps.

    :param origin: The publishing path, e.g. ``archive_idle``; not who started the turn.
    :param response_id: The response the edge's outcome reports on, else the one it opens.
    """

    status: str
    observed_at_ms: int
    origin: str = "unknown"
    turn_outcome: str | None = None
    turn_completed: bool = False
    response_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    failure_origin: str | None = None
    background_task_count: int | None = None

    def __post_init__(self) -> None:
        for name in ("status", "origin"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > MAX_EDGE_CODE_CHARS:
                raise ValueError(f"{name} must be a string of at most {MAX_EDGE_CODE_CHARS}")
        for name in ("turn_outcome", "response_id", "error_code", "failure_origin"):
            if not _bounded_or_none(getattr(self, name), MAX_EDGE_CODE_CHARS):
                raise ValueError(f"{name} must be a string of at most {MAX_EDGE_CODE_CHARS}")
        if not _bounded_or_none(self.error_message, MAX_EDGE_MESSAGE_CHARS):
            raise ValueError(f"error_message must be at most {MAX_EDGE_MESSAGE_CHARS} long")
        if not _integer(self.observed_at_ms):
            raise ValueError("observed_at_ms must be an integer")
        if self.background_task_count is not None and not _integer(self.background_task_count):
            raise ValueError("background_task_count must be an integer or null")
        if not isinstance(self.turn_completed, bool):
            raise ValueError("turn_completed must be true or false")

    @classmethod
    def from_edge(cls, edge: Mapping[str, object]) -> EdgeFacts:
        """An edge's fields, cut to what a signal keeps; never raises for odd values."""
        observed = edge.get("observed_at_ms")
        count = edge.get("background_task_count")
        return cls(
            status=clean_text(edge.get("status"), MAX_EDGE_CODE_CHARS) or "",
            observed_at_ms=observed if _integer(observed) else 0,  # type: ignore[arg-type]
            origin=clean_text(edge.get("origin"), MAX_EDGE_CODE_CHARS) or "unknown",
            turn_outcome=clean_text(edge.get("turn_outcome"), MAX_EDGE_CODE_CHARS),
            turn_completed=edge.get("turn_completed") is True,
            response_id=clean_text(edge_response_id(edge), MAX_EDGE_CODE_CHARS),
            error_code=clean_text(edge.get("error_code"), MAX_EDGE_CODE_CHARS),
            error_message=clean_text(edge.get("error_message"), MAX_EDGE_MESSAGE_CHARS),
            failure_origin=clean_text(edge.get("failure_origin"), MAX_EDGE_CODE_CHARS),
            background_task_count=count if _integer(count) else None,  # type: ignore[arg-type]
        )

    @classmethod
    def from_payload(cls, raw: object) -> EdgeFacts:
        """
        The edge a signal payload stores.

        :raises ValueError: for anything but an object of this shape.
        """
        if not isinstance(raw, Mapping):
            raise ValueError("an edge must be an object")
        known = {item.name for item in fields(cls)}
        if not {"status", "observed_at_ms"} <= raw.keys() or not raw.keys() <= known:
            raise ValueError("an edge needs status and observed_at_ms and nothing unknown")
        return cls(**{str(name): value for name, value in raw.items()})  # type: ignore[arg-type]

    def payload(self) -> dict[str, JsonValue]:
        return asdict(self)


def clean_text(value: object, limit: int) -> str | None:
    """``value`` without lone surrogates, cut to ``limit`` characters; ``None`` if not text."""
    if not isinstance(value, str):
        return None
    return _SURROGATES.sub("", value)[:limit]


def edge_response_id(edge: Mapping[str, object]) -> str | None:
    """The response an edge's outcome reports on (``turn_response_id``), else the one it opens."""
    for name in ("turn_response_id", "response_id"):
        value = edge.get(name)
        if isinstance(value, str) and value != "":
            return value
    return None


def edge_origin(edge: Mapping[str, object]) -> str | None:
    """``archive`` when the edge's origin mentions it, else the origin; ``None`` when absent."""
    value = edge.get("origin")
    if not isinstance(value, str):
        return None
    return "archive" if is_archive_origin(value) else value


def is_archive_origin(origin: str) -> bool:
    """An edge an archive published: its idle ends no turn of the agent's."""
    return "archive" in origin


def build_turn_fact(
    *,
    slot_id: str,
    session_id: str,
    generation: int,
    transcript: TurnTranscript,
    live: LiveFacts,
    edge: EdgeFacts | None,
    engine_stable_id_present: bool,
    engine_input_at_s: int | None,
    latest_engine_input_id: str | None = None,
) -> TurnFact | None:
    """
    The fact of the turn the newest engine message started, or ``None`` when there is none.

    An undecided walk, or no engine message, builds no fact. An edge older than that
    message (its record time is in seconds) is the previous turn's and is ignored.
    Without a current edge a live ``failed`` status is this turn's failure, as
    ``edge_lost``, only once a runner item follows the message; before that it is the
    previous turn's lingering status and builds no fact.

    A walk beyond its reach decides only a turn that is over (idle or failed, with no
    background work): it is
    keyed by the slot's latest engine message and is a failed turn, with a current
    edge's own error, else ``turn_unreadable``; a cancelled or archive edge still ends
    nothing.

    :param engine_input_at_s: When the turn's engine message was recorded; ``None``
        when unknown, which makes no edge current.
    :param latest_engine_input_id: The slot's latest engine message by the engine's
        own record, used when the walk is beyond its reach.
    """
    beyond = transcript.newest_input is None and transcript.beyond_reach
    engine_id = latest_engine_input_id if beyond else transcript.newest_engine_input_id
    if engine_id is None or (transcript.newest_input is None and not beyond):
        return None
    if beyond and (live.status not in _TURN_OVER or live.background_work):
        return None
    current = (
        edge
        if edge is not None
        and engine_input_at_s is not None
        and edge.observed_at_ms >= engine_input_at_s * 1000
        else None
    )
    engine_started = beyond or transcript.newest_input == "engine"
    replied = transcript.newest_substantive_item_is_assistant
    error_code = error_text = failure_origin = None
    background = 1 if live.background_work else 0
    if current is not None:
        outcome = current.turn_outcome or ("failed" if current.status == "failed" else None)
        saw_completed = current.turn_completed or current.turn_outcome == "completed" or replied
        error_code, error_text = current.error_code, current.error_message
        failure_origin = current.failure_origin
        background = max(background, current.background_task_count or 0)
    elif live.status == "failed":
        if not transcript.runner_item_after_engine_input:
            return None
        outcome, saw_completed, error_code = "failed", False, EDGE_LOST
    else:
        outcome, saw_completed = None, replied
    if beyond and outcome not in {"failed", "cancelled"}:
        # Its reply cannot be checked: the step is re-prompted instead of nudged.
        outcome, saw_completed = "failed", False
        error_code, error_text, failure_origin = TURN_UNREADABLE, None, None
    if current is not None and is_archive_origin(current.origin):
        origin = "archive"
    else:
        origin = "engine" if engine_started else "user"
    return TurnFact(
        slot_id=slot_id,
        session_id=session_id,
        generation=generation,
        response_id=f"msg:{engine_id}",
        live_status=live.status,
        engine_stable_id_present=engine_stable_id_present,
        newest_substantive_item_is_assistant=replied,
        turn_outcome=outcome,
        saw_response_completed=saw_completed,
        background_tasks=background,
        pending_elicitation_count=live.pending_elicitations,
        engine_pending_input=transcript.engine_pending_input,
        origin=origin,
        engine_started=engine_started,
        error_code=error_code,
        error_text=error_text,
        failure_origin=failure_origin,
    )


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bounded_or_none(value: object, limit: int) -> bool:
    return value is None or (isinstance(value, str) and len(value) <= limit)


__all__ = [
    "EDGE_LOST",
    "MAX_EDGE_CODE_CHARS",
    "MAX_EDGE_MESSAGE_CHARS",
    "TURN_UNREADABLE",
    "UNDECIDED",
    "EdgeFacts",
    "LiveFacts",
    "TurnInput",
    "TurnTranscript",
    "build_turn_fact",
    "clean_text",
    "edge_origin",
    "edge_response_id",
    "is_archive_origin",
]
