"""Coral's mutation guard: clients cannot change what a workflow run relies on.

The lifespan registers :class:`CoralMutationGuard` as the S53 guard ``"coral"``.
A session is part of a run when it has a binding row, read by session id in the
request's workspace. The ``coral.run_id`` label is trusted only to say that a
session is *not* bound: clients can neither write nor remove ``coral.`` labels
(S46) and the session facade writes the label in the same create as the row. So
an unlabelled session is never looked up and never waits on Coral's store; a
labelled one still needs its binding row.

On a bound session a client may still rename, archive, pin, delete, fork, read
and stop it. It may not change the session's runner, model, modes, project or
``omnigent.*`` labels, close it through its title, share it, start sessions under
or beside it, replace its agent or MCP servers, or point a scheduled task at it.
The anchor and closed steps take only stop and interrupt events; an open step
also refuses ``clear`` and other agents' messages. Runner-only event types pass
only from the session's own runner, because Omnigent lets owners post them too.
Engine agents (``coral__*``) cannot be edited or installed by clients, and are
removed only with ``force=true``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from coral.db.enum_codecs import SessionBindingRole
from coral.omni._upstream import RUNNER_SESSION_EVENT_TYPES, label_key_skeleton
from coral.omni.policies.state import log_traceback_once
from coral.omni.server.sessions import RUN_ID_LABEL_KEY
from coral.profiles.bundle_spec import ENGINE_PREFIX
from omnigent.db.db_models import current_workspace_id
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.server.mutation_guards import (
    AGENT_INSTALL,
    AGENT_REMOVE,
    AGENT_UPDATE,
    SESSION_AGENT_REPLACE,
    SESSION_CREATE_CHILD,
    SESSION_EVENT,
    SESSION_GRANT,
    SESSION_LAUNCH_RUNNER,
    SESSION_MCP_CHANGE,
    SESSION_SCHEDULE,
    SESSION_UPDATE,
    MutationAttempt,
    Screen,
)
from omnigent.util.session_lifecycle import (
    CLOSED_LABEL_KEY,
    CLOSED_LABEL_VALUE,
    CLOSED_TITLE_INFIX,
    has_closed_title_marker,
)

if TYPE_CHECKING:
    from coral.stores.session_bindings import SessionBindingLookup

_logger = logging.getLogger(__name__)

# The name the guard is registered under (S53).
MUTATION_GUARD = "coral"
# PATCH fields a client may still send for a run session; every other field is refused.
UPDATABLE_FIELDS = frozenset(
    {"title", "archived", "delete_worktree", "family_pinned", "silent", "labels"}
)
# Omnigent's own labels steer how it handles a session (closed, wakes, wrappers, routing).
# A label is refused when its skeleton, as a case- and accent-insensitive collation
# compares keys, starts with this; only the bare pin key stays writable.
_OMNIGENT_LABEL_PREFIX = "omnigent."
_PIN_LABEL_KEY = "omnigent.pinned"
# The only client events the anchor and a closed step take.
STOP_EVENTS = frozenset({"interrupt", "stop_session"})
# claude-sdk's /clear moves a step into an unbound session; peer agents must not steer a step.
_OPEN_STEP_REFUSED_EVENTS = frozenset({"clear", "session_message"})
_SESSION_CHANGES = {
    SESSION_LAUNCH_RUNNER: "attaching a runner to it",
    SESSION_GRANT: "sharing it",
    SESSION_CREATE_CHILD: "starting a session under or beside it",
    SESSION_AGENT_REPLACE: "replacing its agent",
    SESSION_MCP_CHANGE: "changing its MCP servers",
    SESSION_SCHEDULE: "scheduling a task to continue it",
}
_AGENT_ACTIONS = frozenset({AGENT_UPDATE, AGENT_REMOVE, AGENT_INSTALL})
_SESSION_REFUSAL = (
    "Session {session_id} is part of a Coral workflow run, so {what} can't be done here. "
    "You can rename, archive, delete, fork or stop it."
)
_ENGINE_AGENT = "Agent {name!r} is managed by Coral's workflow engine"
_RESERVED_NAMES = f"Names starting with {ENGINE_PREFIX} are reserved for Coral's engine agents."
_LOOKUP_FAILED = "Coral could not check whether session {session_id} is in a workflow run; retry."


class CoralMutationGuard:
    """The S53 guard registered as ``"coral"``; thread-safe."""

    def __init__(self, bindings: SessionBindingLookup) -> None:
        """
        :param bindings: Finds a session's binding row (the positive-only cache
            the policy provider shares, in production).
        """
        self._bindings = bindings

    def screen(self, attempt: MutationAttempt) -> Screen | str:
        """Decide inline: agent names by their prefix, sessions by the run-id label only."""
        if attempt.action in _AGENT_ACTIONS:
            return _agent_refusal(attempt) or Screen.ALLOW
        # Nothing a run relies on would change, even on the anchor or a closed step.
        if _refused_change(attempt, inert=True) is None:
            return Screen.ALLOW
        conversation = attempt.conversation
        if conversation is None:
            return Screen.NEEDS_ROW
        if RUN_ID_LABEL_KEY not in (conversation.labels or {}):
            return Screen.ALLOW
        return Screen.CHECK

    def check(self, attempt: MutationAttempt) -> str | None:
        """Refuse the change when the session's binding row exists; a store error is a 500.

        :raises OmnigentError: ``INTERNAL_ERROR`` (retryable) when the binding
            cannot be read.
        """
        conversation = attempt.conversation
        if conversation is None:  # screen asks for a check only with the row
            return None
        try:
            binding = self._bindings.find_by_session(current_workspace_id(), conversation.id)
        except Exception as exc:
            log_traceback_once(_logger, "mutation guard binding lookup", exc)
            _logger.warning(
                "Coral could not look up session %s's binding (%s); refusing the change",
                conversation.id,
                type(exc).__name__,
                extra={"session_id": conversation.id},
            )
            raise OmnigentError(
                _LOOKUP_FAILED.format(session_id=conversation.id), code=ErrorCode.INTERNAL_ERROR
            ) from exc
        if binding is None:
            return None
        labels = conversation.labels or {}
        inert = (
            binding.role == SessionBindingRole.ANCHOR
            or labels.get(CLOSED_LABEL_KEY) == CLOSED_LABEL_VALUE
        )
        what = _refused_change(attempt, inert=inert)
        if what is None:
            return None
        return _SESSION_REFUSAL.format(session_id=conversation.id, what=what)


def _refused_change(attempt: MutationAttempt, *, inert: bool) -> str | None:
    """What a client may not do to a bound session in *attempt*, or ``None``.

    :param inert: The session is the anchor or a closed step, which take only
        stop events (and runner-only ones from its runner).
    """
    if attempt.action == SESSION_UPDATE:
        protected = [
            *sorted(attempt.fields - UPDATABLE_FIELDS),
            *(f"label {key!r}" for key in sorted(attempt.label_keys) if _omnigent_label(key)),
        ]
        if has_closed_title_marker(attempt.title):
            protected.append(f"its title to one containing {CLOSED_TITLE_INFIX!r}")
        return f"changing {', '.join(protected)}" if protected else None
    if attempt.action == SESSION_EVENT:
        event_type = attempt.event_type
        if event_type in STOP_EVENTS:
            return None
        if event_type in RUNNER_SESSION_EVENT_TYPES:
            refused = not attempt.runner_proven
        else:
            refused = inert or event_type in _OPEN_STEP_REFUSED_EVENTS
        return f"sending it a {event_type!r} event" if refused else None
    return _SESSION_CHANGES.get(attempt.action, "this change")


def _omnigent_label(key: str) -> bool:
    """Whether *key* collates as an Omnigent label other than the bare pin key."""
    return key != _PIN_LABEL_KEY and label_key_skeleton(key).startswith(_OMNIGENT_LABEL_PREFIX)


def _agent_refusal(attempt: MutationAttempt) -> str | None:
    """The refusal for an engine agent's name (``coral__`` in any case), else ``None``."""
    name = attempt.agent_name
    if name is None or not name.casefold().startswith(ENGINE_PREFIX):
        return None
    if attempt.action == AGENT_INSTALL:
        return _RESERVED_NAMES
    if attempt.action == AGENT_UPDATE:
        return _ENGINE_AGENT.format(name=name) + " and can't be edited."
    if attempt.forced:
        return None
    # Nothing pauses at once: its live steps lose their engine tools and stall on the nudge cap.
    return (
        _ENGINE_AGENT.format(name=name)
        + "; delete with force=true to remove it anyway (steps running it can no longer "
        "hand off, and their runs pause after repeated nudges)."
    )
