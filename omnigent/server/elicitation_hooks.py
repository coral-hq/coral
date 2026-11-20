# CORAL(S6a, S6b): request-free elicitations and stable-id verdict handlers (new file).
"""Elicitations a server component owns: published with no request, answered by its handler.

A component registers a verdict handler for an id prefix (S6b). It can then
publish and withdraw form elicitations with ids under that prefix on any
session, with no HTTP request behind them (S6a), and every answer to such an id,
through the resolve URL or an ``approval`` event, goes to its handler alone:
no harness Future, tombstone or runner forward is involved, and only the
answered session is told. Ids no handler claims, including every ``elicit_`` id
Omnigent mints, keep the existing path.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from pydantic import ValidationError

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runtime import pending_elicitations, session_stream
from omnigent.server.routes._sessions.helpers import _publish_elicitation_resolved
from omnigent.server.schemas import (
    ElicitationRequestEvent,
    ElicitationRequestParams,
    ElicitationResult,
)

ELICIT_PREFIX = "elicit_"  # Omnigent's own ids; never claimable
_PREFIX = re.compile(r"[a-z][a-z0-9_]{0,31}_")
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


# CORAL(S6b): verdict handler registry and the answer path.


class NoCaller(Enum):
    """``_resolve_elicitation`` was called without naming who answers."""

    NO_CALLER = auto()


NO_CALLER = NoCaller.NO_CALLER


@dataclass(frozen=True)
class ElicitationVerdict:
    """
    One answer to a claimed elicitation.

    :param session_id: The session the answer was posted to.
    :param elicitation_id: The claimed id, e.g. ``"coral_gate_<32 hex>"``.
    :param result: The validated MCP result (``action`` and optional ``content``).
    :param resolved_by: The route's authenticated user, e.g. ``"alice@example.com"``;
        ``None`` when the request carried no identity, e.g. with no auth provider.
    """

    session_id: str
    elicitation_id: str
    result: ElicitationResult
    resolved_by: str | None


@dataclass(frozen=True)
class VerdictDecision:
    """
    A handler's answer to one verdict.

    :param accepted: The answer was taken (now or earlier).
    :param duplicate: It was taken earlier: answer 202 with no second fan-out.
    :param forbidden: Refused because of who answered: 403, otherwise 409.
    :param clear_pending: Drop the prompt from this session if it is still
        pending; ignored when ``forbidden``, so a refused caller never clears it.
    :param reason: Stable slug for a refusal, e.g. ``"stale_visit"``.
    :param message: Human-readable text for a refusal.
    """

    accepted: bool
    duplicate: bool = False
    forbidden: bool = False
    clear_pending: bool = False
    reason: str | None = None
    message: str | None = None


VerdictHandler = Callable[[ElicitationVerdict], Awaitable[VerdictDecision]]

# Process-wide handlers keyed by id prefix, never by session; each entry carries
# its registration's own marker so a stale uninstaller cannot remove a later one.
# custom-lint: disable-next=workspace-scoped-cache -- keyed by id prefix, not a tenant id
_handlers: dict[str, tuple[object, VerdictHandler]] = {}
_handlers_lock = threading.Lock()


def register_elicitation_verdict_handler(
    prefix: str, handler: VerdictHandler
) -> Callable[[], None]:
    """
    Claim every elicitation id that starts with *prefix* for *handler*.

    :param prefix: Lower-case id prefix ending in ``_``, e.g. ``"coral_gate_"``.
    :param handler: Awaited once per answer to a claimed id, in the request's
        task with no timeout, so it must bound its own waits.
    :returns: An idempotent uninstaller that removes this registration only.
    :raises ValueError: *prefix* is not ``[a-z][a-z0-9_]{0,31}_``, starts with
        ``elicit_``, or is a prefix of (or prefixed by) a registered prefix.
    """
    if not _PREFIX.fullmatch(prefix) or prefix.startswith(ELICIT_PREFIX):
        raise ValueError(f"invalid elicitation verdict handler prefix {prefix!r}")
    registration = object()
    with _handlers_lock:
        for registered in _handlers:
            if registered.startswith(prefix) or prefix.startswith(registered):
                raise ValueError(
                    f"prefix {prefix!r} overlaps the registered prefix {registered!r}"
                )
        _handlers[prefix] = (registration, handler)

    def unregister() -> None:
        with _handlers_lock:
            entry = _handlers.get(prefix)
            if entry is not None and entry[0] is registration:
                del _handlers[prefix]

    return unregister


def claimed_handler(elicitation_id: str) -> VerdictHandler | None:
    """
    Return the handler that claims *elicitation_id*, if any.

    :param elicitation_id: The id to look up, e.g. ``"coral_gate_<32 hex>"``.
    :returns: The handler whose prefix starts the id, or ``None``.
    """
    with _handlers_lock:
        for prefix, (_registration, handler) in _handlers.items():
            if elicitation_id.startswith(prefix):
                return handler
    return None


async def resolve_claimed_elicitation(
    session_id: str, data: Mapping[str, Any], *, resolved_by: str | NoCaller | None
) -> VerdictDecision | None:
    """
    Answer a claimed elicitation through its handler.

    Without the handler, a claimed id is refused with ``NO_CALLER`` (forbidden,
    ``"no_caller"``) and when the id is not 1-64 of ``A-Za-z0-9_-`` or the
    result is invalid (``"invalid_answer"``). Otherwise the handler decides; a
    non-duplicate acceptance then publishes ``response.elicitation_resolved``
    with the verdict, and ``clear_pending`` on a refusal that is not
    ``forbidden`` withdraws a still-pending prompt. Both touch this session
    only, never its ancestors, and nothing else is published. The handler's
    outcome stands even if it is unregistered while it runs.

    :param session_id: The session the answer was posted to.
    :param data: The approval payload: ``elicitation_id`` plus the MCP result
        fields, e.g. ``{"elicitation_id": "coral_gate_…", "action": "accept"}``.
    :param resolved_by: The authenticated caller, ``None`` with no identity, or
        ``NO_CALLER`` when the caller did not say.
    :returns: The decision, or ``None`` when no handler claims the id.
    """
    elicitation_id = data.get("elicitation_id")
    if not isinstance(elicitation_id, str):
        return None
    handler = claimed_handler(elicitation_id)
    if handler is None:
        return None
    if isinstance(resolved_by, NoCaller):
        return VerdictDecision(
            accepted=False,
            forbidden=True,
            reason="no_caller",
            message="Only a request that names its caller can answer this prompt.",
        )
    invalid = VerdictDecision(
        accepted=False, reason="invalid_answer", message="The answer is not valid."
    )
    if not _ID.fullmatch(elicitation_id):
        return invalid
    try:
        result = ElicitationResult.model_validate(
            {key: value for key, value in data.items() if key != "elicitation_id"}
        )
    except ValidationError:
        return invalid
    decision = await handler(ElicitationVerdict(session_id, elicitation_id, result, resolved_by))
    if decision.accepted and not decision.duplicate:
        _publish_elicitation_resolved(session_id, elicitation_id, action=result.action)
    if decision.clear_pending and not decision.forbidden:
        _withdraw_pending(session_id, elicitation_id)
    return decision


def verdict_response(decision: VerdictDecision) -> dict[str, bool]:
    """
    Turn a decision into the resolve routes' response.

    :param decision: The handler's decision.
    :returns: ``{"queued": False}``, plus ``"duplicate": True`` for a duplicate.
    :raises OmnigentError: A refusal: ``FORBIDDEN`` when ``forbidden``, else
        ``CONFLICT``, with the message ``"[<reason>] <message>"``.
    """
    if decision.accepted:
        return {"queued": False, "duplicate": True} if decision.duplicate else {"queued": False}
    raise OmnigentError(
        f"[{decision.reason or 'refused'}] {decision.message or 'The answer was refused.'}",
        code=ErrorCode.FORBIDDEN if decision.forbidden else ErrorCode.CONFLICT,
    )


def reset_for_tests() -> None:
    """Drop every registered handler. For test isolation only."""
    with _handlers_lock:
        _handlers.clear()


# CORAL(S6a): request-free publish and withdraw of claimed ids.


def _require_claimed(elicitation_id: str) -> None:
    """Refuse an id that is malformed, Omnigent's own, or claimed by no handler."""
    if (
        not _ID.fullmatch(elicitation_id)
        or elicitation_id.startswith(ELICIT_PREFIX)
        or claimed_handler(elicitation_id) is None
    ):
        raise ValueError("elicitation id is malformed or not claimed by a verdict handler")


def _withdraw_pending(session_id: str, elicitation_id: str) -> bool:
    """Drop *elicitation_id* if it is pending on *session_id*; report whether it was."""
    if pending_elicitations.lookup(elicitation_id, conversation_id=session_id) is None:
        return False
    _publish_elicitation_resolved(session_id, elicitation_id)
    return True


async def publish_form_elicitation(
    session_id: str, params: Mapping[str, Any], *, elicitation_id: str
) -> None:
    """
    Publish a form elicitation on one session with no request behind it.

    Re-publishing an id replaces the stored prompt; the pending count is
    unchanged. Call inside the session's workspace scope. Ancestors get no
    mirror. ``params`` is not forced to form mode; callers pass form params.

    :param session_id: The session to publish on.
    :param params: ``ElicitationRequestParams`` fields, e.g.
        ``{"message": "Approve?", "requestedSchema": {...}}``; extra keys are kept.
    :param elicitation_id: A claimed id, 1-64 of ``A-Za-z0-9_-``.
    :raises ValueError: The id is unclaimed, starts with ``elicit_`` or is
        malformed, or *params* does not validate as ``ElicitationRequestParams``.
    """
    _require_claimed(elicitation_id)
    payload = ElicitationRequestEvent(
        type="response.elicitation_request",
        elicitation_id=elicitation_id,
        params=ElicitationRequestParams.model_validate(dict(params)),
    ).model_dump()
    session_stream.publish(session_id, payload)


def withdraw_elicitation(session_id: str, elicitation_id: str) -> bool:
    """
    Drop a claimed prompt still pending on this session and tell its subscribers.

    :param session_id: The session the prompt was published on.
    :param elicitation_id: The claimed id.
    :returns: ``True`` when a pending prompt was withdrawn; ``False``, publishing
        nothing, when none is pending here.
    :raises ValueError: The id is malformed or not claimed.
    """
    _require_claimed(elicitation_id)
    return _withdraw_pending(session_id, elicitation_id)
