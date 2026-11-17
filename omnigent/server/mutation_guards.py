# CORAL(S53): mutation guards an installed extension registers (new file).
"""Guards an installed extension registers to refuse client changes to what it manages.

A mutating route describes its change as a :class:`MutationAttempt` after its
own authorization (so a caller without access keeps its 403 or 404) and before
any side effect, and awaits :func:`check_mutation`. Only client requests are
checked: server-internal senders (an engine, saved startup inputs, a runner's
tunnel) never ask.

A guard answers in two phases. ``screen`` runs inline on the event loop, must
be O(1) with no I/O and must not raise: it allows, refuses with a message,
asks for the session row when the attempt has none, or asks to ``check``.
``check`` may read stores; every guard that asked for it runs in one worker
thread hop. So an attempt no guard needs to look up never waits on a store and
never fails because a store is down. A refusal is a 409 ``CONFLICT`` with the
guard's message; a guard's own :class:`~omnigent.errors.OmnigentError`
propagates; any other failure is logged and becomes a retryable 500. With no
guard registered, :func:`check_mutation` returns at once.

The registry is process-wide, keyed by guard name: the latest registration of a
name wins, as with the other server registries.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from omnigent.errors import ErrorCode, OmnigentError

if TYPE_CHECKING:
    from omnigent.entities import Conversation

_logger = logging.getLogger(__name__)

# Session actions: the attempt names the session and carries its row (or a loader).
SESSION_UPDATE = "session.update"
SESSION_EVENT = "session.event"
SESSION_LAUNCH_RUNNER = "session.launch_runner"
SESSION_GRANT = "session.grant"
SESSION_CREATE_CHILD = "session.create_child"
SESSION_AGENT_REPLACE = "session.agent_replace"
SESSION_MCP_CHANGE = "session.mcp_change"
SESSION_SCHEDULE = "session.schedule"
# Agent actions: the attempt names the agent.
AGENT_UPDATE = "agent.update"
AGENT_REMOVE = "agent.remove"
AGENT_INSTALL = "agent.install"
ACTIONS = frozenset(
    {
        SESSION_UPDATE,
        SESSION_EVENT,
        SESSION_LAUNCH_RUNNER,
        SESSION_GRANT,
        SESSION_CREATE_CHILD,
        SESSION_AGENT_REPLACE,
        SESSION_MCP_CHANGE,
        SESSION_SCHEDULE,
        AGENT_UPDATE,
        AGENT_REMOVE,
        AGENT_INSTALL,
    }
)

_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_UNAVAILABLE = "could not check whether this change is allowed; retry"


@dataclass(frozen=True)
class MutationAttempt:
    """One client change, as the route that will make it describes it.

    :param action: One of the action constants, e.g. ``SESSION_UPDATE``.
    :param session_id: The session changed, or the parent for
        ``SESSION_CREATE_CHILD``; ``None`` for agent actions.
    :param conversation: That session's row when the route already holds it.
    :param fields: The request fields set, e.g. ``{"model_override"}`` (PATCH).
    :param label_keys: The label keys written, e.g. ``{"omnigent.closed"}`` (PATCH).
    :param event_type: The event type posted, e.g. ``"message"`` (``SESSION_EVENT``).
    :param runner_proven: The event came from the session's own runner: its tunnel
        token is bound to the row's ``runner_id`` (``SESSION_EVENT``).
    :param title: The title being set, e.g. ``"Fix the build"`` (``SESSION_UPDATE``).
    :param agent_name: The agent's name (agent actions).
    :param forced: Whether ``force=true`` was given (``AGENT_REMOVE``).
    """

    action: str
    session_id: str | None = None
    conversation: Conversation | None = None
    fields: frozenset[str] = frozenset()
    label_keys: frozenset[str] = frozenset()
    event_type: str | None = None
    runner_proven: bool = False
    title: str | None = None
    agent_name: str | None = None
    forced: bool = False


class Screen(Enum):
    """What ``screen`` answers when it neither allows nor refuses outright."""

    ALLOW = "allow"
    # The guard needs the session row and the attempt has none.
    NEEDS_ROW = "needs_row"
    # The guard must read a store: run ``check`` in a worker thread.
    CHECK = "check"


class MutationGuard(Protocol):
    """A registered guard; both methods must be thread-safe."""

    def screen(self, attempt: MutationAttempt) -> Screen | str:
        """Decide inline, with no I/O and without raising; a string refuses with that message."""
        ...

    def check(self, attempt: MutationAttempt) -> str | None:
        """Decide after reading stores (worker thread, after ``CHECK``); a string refuses."""
        ...


@dataclass(frozen=True, eq=False)
class _Registration:
    """One registration; its identity lets an unregister remove only itself."""

    name: str
    guard: MutationGuard


# Process-wide registry keyed by guard name, never by session.
# custom-lint: disable-next=workspace-scoped-cache -- keyed by guard name, not a tenant id
_registrations: dict[str, _Registration] = {}
_registrations_lock = threading.Lock()


def register_mutation_guard(name: str, guard: MutationGuard) -> Callable[[], None]:
    """Ask *guard* about every client change to a session or an agent.

    Registering a name again replaces its guard and logs a warning when the
    guard changes.

    :param name: 1-64 letters, digits, ``_``, ``.`` or ``-``, starting with a
        letter or digit, e.g. ``"coral"``. Guards are asked in name order.
    :param guard: The guard; it must be thread-safe.
    :returns: An idempotent unregister function that removes this registration
        only while it is still the one registered under *name*.
    :raises ValueError: If *name* is not a valid guard name.
    :raises TypeError: If *guard* lacks a callable ``screen`` or ``check``.
    """
    if not isinstance(name, str) or _NAME_RE.fullmatch(name) is None:
        raise ValueError(f"invalid mutation guard name {name!r}")
    if not (callable(getattr(guard, "screen", None)) and callable(getattr(guard, "check", None))):
        raise TypeError(f"mutation guard {name!r} needs callable screen and check")
    registration = _Registration(name, guard)
    with _registrations_lock:
        replaced = _registrations.get(name)
        _registrations[name] = registration
    if replaced is not None and replaced.guard is not guard:
        _logger.warning("mutation guard %r replaced an earlier registration", name)

    def unregister() -> None:
        with _registrations_lock:
            if _registrations.get(name) is registration:
                del _registrations[name]

    return unregister


async def check_mutation(
    attempt: MutationAttempt,
    *,
    load_conversation: Callable[[], Awaitable[Conversation | None]] | None = None,
) -> None:
    """Ask every registered guard about *attempt*; return when all allow it.

    :param attempt: The change, described after the route's authorization.
    :param load_conversation: Reads the session row; awaited at most once, and
        only when a guard needs the row the attempt does not carry. A route
        that already holds the row passes it in the attempt instead.
    :raises OmnigentError: 409 ``CONFLICT`` with the first refusal; a guard's
        own error; 500 ``INTERNAL_ERROR`` when a guard fails otherwise.
    :raises ValueError: When a guard needs the row and the route gave neither
        the row nor a loader (a call-site bug).
    """
    registrations = _registrations_in_order()
    if not registrations:
        return
    needs_row: list[_Registration] = []
    checks: list[_Registration] = []
    for registration in registrations:
        verdict = _screen(registration, attempt)
        if verdict is Screen.NEEDS_ROW:
            needs_row.append(registration)
        elif verdict is Screen.CHECK:
            checks.append(registration)
    if needs_row:
        if load_conversation is None:
            raise ValueError(
                f"mutation guard {needs_row[0].name!r} needs the session row for "
                f"{attempt.action!r}; pass the row or a loader"
            )
        conversation = await load_conversation()
        if conversation is None:
            # The session is gone: the route answers 404 itself.
            needs_row = []
        else:
            attempt = replace(attempt, conversation=conversation)
        for registration in needs_row:
            verdict = _screen(registration, attempt)
            if verdict is Screen.CHECK:
                checks.append(registration)
            elif verdict is Screen.NEEDS_ROW:
                _logger.error(
                    "mutation guard %r asked for a session row it was given",
                    registration.name,
                    extra={"session_id": attempt.session_id},
                )
                raise OmnigentError(_UNAVAILABLE, code=ErrorCode.INTERNAL_ERROR)
    if checks:
        refusal = await asyncio.to_thread(_run_checks, checks, attempt)
        if refusal is not None:
            raise OmnigentError(refusal, code=ErrorCode.CONFLICT)


def _registrations_in_order() -> list[_Registration]:
    with _registrations_lock:
        return sorted(_registrations.values(), key=lambda registration: registration.name)


def _registered() -> list[tuple[str, MutationGuard]]:
    """The registered guards in name order, as ``(name, guard)``."""
    return [(registration.name, registration.guard) for registration in _registrations_in_order()]


def _screen(registration: _Registration, attempt: MutationAttempt) -> Screen:
    """Screen *attempt*; a refusal raises 409, a broken guard fails closed."""
    try:
        verdict = registration.guard.screen(attempt)
    except OmnigentError:
        raise
    except Exception as exc:  # a guard bug must fail closed, not open
        _logger.exception(
            "mutation guard %r failed on %s",
            registration.name,
            attempt.action,
            extra={"session_id": attempt.session_id},
        )
        raise OmnigentError(_UNAVAILABLE, code=ErrorCode.INTERNAL_ERROR) from exc
    if isinstance(verdict, str):
        raise OmnigentError(verdict, code=ErrorCode.CONFLICT)
    if not isinstance(verdict, Screen):
        _logger.error(
            "mutation guard %r screened %r: not a Screen or a refusal",
            registration.name,
            type(verdict).__name__,
            extra={"session_id": attempt.session_id},
        )
        raise OmnigentError(_UNAVAILABLE, code=ErrorCode.INTERNAL_ERROR)
    return verdict


def _run_checks(checks: Sequence[_Registration], attempt: MutationAttempt) -> str | None:
    """Run each guard's ``check`` in order (one worker thread); the first refusal, if any."""
    for registration in checks:
        try:
            refusal = registration.guard.check(attempt)
        except OmnigentError:
            raise
        except Exception as exc:  # a store or guard failure must fail closed
            _logger.exception(
                "mutation guard %r failed on %s",
                registration.name,
                attempt.action,
                extra={"session_id": attempt.session_id},
            )
            raise OmnigentError(_UNAVAILABLE, code=ErrorCode.INTERNAL_ERROR) from exc
        if refusal is None:
            continue
        if isinstance(refusal, str):
            return refusal
        _logger.error(
            "mutation guard %r checked %r: not a refusal or None",
            registration.name,
            type(refusal).__name__,
            extra={"session_id": attempt.session_id},
        )
        raise OmnigentError(_UNAVAILABLE, code=ErrorCode.INTERNAL_ERROR)
    return None
