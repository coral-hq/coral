"""Coral's mutation guard: which client changes a run session or an engine agent refuses.

Pure tests of both phases over a fake binding lookup; the HTTP matrix is in
``test_mutation_guard_routes.py``.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable

import pytest

from coral.db.enum_codecs import SessionBindingRole, SlotRole
from coral.omni._upstream import CLIENT_SESSION_EVENT_TYPES, RUNNER_SESSION_EVENT_TYPES
from coral.omni.server.mutation_guard import (
    STOP_EVENTS,
    UPDATABLE_FIELDS,
    CoralMutationGuard,
)
from coral.omni.server.sessions import RUN_ID_LABEL_KEY
from omnigent.db.db_models import workspace_scope
from omnigent.entities import Conversation
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
from omnigent.server.schemas import UpdateSessionRequest
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE
from tests.coral.tools.fake_decision_port import WORKSPACE, FakeBindingLookup, step_binding

SESSION = "conv_bound"
# The contract's field table: what a client may not change on a run session.
PROTECTED_FIELDS = frozenset(
    {
        "runner_id",
        "model_override",
        "reasoning_effort",
        "collaboration_mode",
        "permission_mode",
        "approval_mode",
        "cost_control_mode_override",
        "subagent_routing_override",
        "external_session_id",
        "terminal_launch_args",
        "project_id",
        "share_workspace_files",
    }
)
ALWAYS_REFUSED = {
    SESSION_LAUNCH_RUNNER: "attaching a runner to it",
    SESSION_GRANT: "sharing it",
    SESSION_CREATE_CHILD: "starting a session under or beside it",
    SESSION_AGENT_REPLACE: "replacing its agent",
    SESSION_MCP_CHANGE: "changing its MCP servers",
    SESSION_SCHEDULE: "scheduling a task to continue it",
}
# An event type a future Omnigent might add for clients.
NEW_CLIENT_EVENT = "future_client_event"
# Binding kinds: open steps (any slot role) and the inert anchor and closed step.
OPEN = ("step", "orchestrator")
INERT = ("anchor", "closed step")


def _row(*, labelled: bool = True, closed: bool = False, **labels: str) -> Conversation:
    if labelled:
        labels[RUN_ID_LABEL_KEY] = "run-1"
    if closed:
        labels[CLOSED_LABEL_KEY] = CLOSED_LABEL_VALUE
    return Conversation(
        id=SESSION, created_at=0, updated_at=0, root_conversation_id=SESSION, labels=labels
    )


def _bound(
    kind: str | None, *, gate_answering: Callable[[], bool] | None = None
) -> tuple[CoralMutationGuard, FakeBindingLookup, Conversation]:
    """A guard over a lookup that binds ``SESSION`` as *kind* (``None``: unbound), and its row.

    :param gate_answering: The guard's gate-handler flag; by default it is never set.
    """
    lookup = FakeBindingLookup()
    if kind == "anchor":
        lookup.add(
            step_binding(None, session_id=SESSION, role=SessionBindingRole.ANCHOR, slot_role=None)
        )
    elif kind is not None:
        slot_role = SlotRole.ORCHESTRATOR if kind == "orchestrator" else SlotRole.STEP_AGENT
        lookup.add(step_binding("work||:0", session_id=SESSION, slot_role=slot_role))
    guard = (
        CoralMutationGuard(lookup)
        if gate_answering is None
        else CoralMutationGuard(lookup, gate_answering=gate_answering)
    )
    return guard, lookup, _row(closed=kind == "closed step")


def _decide(guard: CoralMutationGuard, attempt: MutationAttempt) -> str | None:
    """Run both phases as the registry does; the refusal, or ``None`` when allowed."""
    verdict = guard.screen(attempt)
    if isinstance(verdict, str):
        return verdict
    if verdict is Screen.CHECK:
        with workspace_scope(WORKSPACE):
            return guard.check(attempt)
    assert verdict is Screen.ALLOW
    return None


def _update(
    row: Conversation | None, *fields: str, labels: tuple[str, ...] = ()
) -> MutationAttempt:
    names = set(fields) | ({"labels"} if labels else set())
    return MutationAttempt(
        SESSION_UPDATE,
        session_id=SESSION,
        conversation=row,
        fields=frozenset(names),
        label_keys=frozenset(labels),
    )


def _event(
    row: Conversation | None, event_type: str, *, runner_proven: bool = False
) -> MutationAttempt:
    return MutationAttempt(
        SESSION_EVENT,
        session_id=SESSION,
        conversation=row,
        event_type=event_type,
        runner_proven=runner_proven,
    )


def _refusal(what: str) -> str:
    return (
        f"Session {SESSION} is part of a Coral workflow run, so {what} can't be done here. "
        "You can rename, archive, delete, fork or stop it."
    )


def test_the_event_sets_hold_the_types_the_rules_name() -> None:
    assert {"interrupt", "stop_session", "clear", "message"} <= CLIENT_SESSION_EVENT_TYPES
    assert not CLIENT_SESSION_EVENT_TYPES & RUNNER_SESSION_EVENT_TYPES
    assert "session_message" not in CLIENT_SESSION_EVENT_TYPES | RUNNER_SESSION_EVENT_TYPES
    assert frozenset({"interrupt", "stop_session"}) == STOP_EVENTS


def test_unlabelled_sessions_are_screened_without_io() -> None:
    """Only a row labelled with a run id is ever looked up; nothing else waits on Coral's store."""
    lookup = FakeBindingLookup(error=RuntimeError("store down"))
    guard = CoralMutationGuard(lookup)
    refusable = [
        _update(None, "model_override"),
        _update(None, labels=(CLOSED_LABEL_KEY,)),
        _update(None, labels=("omnigent.wrapper",)),
        dataclasses.replace(_update(None, "title"), title="work:closed:x"),
        _event(None, "message"),
        _event(None, "session_message"),
        # Omnigent lets owners post runner-only types too.
        *(_event(None, kind) for kind in sorted(RUNNER_SESSION_EVENT_TYPES)),
        *(MutationAttempt(action, session_id=SESSION) for action in ALWAYS_REFUSED),
    ]
    for attempt in refusable:
        assert guard.screen(attempt) is Screen.NEEDS_ROW, attempt
        unlabelled = dataclasses.replace(attempt, conversation=_row(labelled=False))
        assert guard.screen(unlabelled) is Screen.ALLOW, attempt
        labelled = dataclasses.replace(attempt, conversation=_row())
        assert guard.screen(labelled) is Screen.CHECK, attempt

    # Changes no rule could refuse need neither the row nor its label.
    harmless = [
        _update(None, "title", "archived", "delete_worktree", "family_pinned", "silent"),
        dataclasses.replace(_update(None, "title"), title="work: closed x"),
        _update(None, labels=("omnigent.pinned", "team")),
        _update(None),
        *(_event(None, kind) for kind in sorted(STOP_EVENTS)),
        *(_event(None, kind, runner_proven=True) for kind in sorted(RUNNER_SESSION_EVENT_TYPES)),
    ]
    for attempt in harmless:
        assert guard.screen(attempt) is Screen.ALLOW, attempt
        labelled = dataclasses.replace(attempt, conversation=_row())
        assert guard.screen(labelled) is Screen.ALLOW, attempt
    assert lookup.reads == []


@pytest.mark.parametrize("kind", [*OPEN, *INERT])
def test_patch_fields_follow_the_table(kind: str) -> None:
    assert set(UpdateSessionRequest.model_fields) - UPDATABLE_FIELDS == PROTECTED_FIELDS
    guard, lookup, row = _bound(kind)
    for field in sorted(PROTECTED_FIELDS):
        assert _decide(guard, _update(row, field, "title")) == _refusal(f"changing {field}")
    assert _decide(guard, _update(row, "runner_id", "model_override")) == _refusal(
        "changing model_override, runner_id"
    )
    assert _decide(guard, _update(row, *UPDATABLE_FIELDS, labels=("team",))) is None
    assert lookup.reads == [(WORKSPACE, SESSION)] * (len(PROTECTED_FIELDS) + 1)


@pytest.mark.parametrize(
    "key",
    [
        "omnigent.wrapper",
        "omnigent.ui",
        "omnigent.side_chat",
        "Omnigent.Pinned",
        "omnigent.closed",
        "Omnigent.Closed",
        "ｏｍｎｉｇｅｎｔ.closed",
        "​omnigent.closed",
        " omnigent.closed",
        "omnigent.parent_wake",
        "OMNIGENT.PARENT_WAKE",
    ],
)
def test_omnigent_labels_are_refused_in_any_spelling_a_collation_equates(key: str) -> None:
    """No ``omnigent.*`` label (closed, wake, wrapper, UI) changes on a bound session."""
    for kind in (*OPEN, *INERT):
        guard, _, row = _bound(kind)
        refusal = _decide(guard, _update(row, labels=(key, "team")))
        assert refusal == _refusal(f"changing label {key!r}"), kind


def test_the_pin_and_user_labels_stay_writable_on_a_bound_session() -> None:
    guard, _, row = _bound("closed step")
    for key in ("omnigent.pinned", "team", "my.omnigent.closed", "omnigentx.note"):
        assert _decide(guard, _update(row, labels=(key,))) is None, key


@pytest.mark.parametrize("kind", [*OPEN, *INERT])
def test_a_title_cannot_close_a_bound_session(kind: str) -> None:
    """Omnigent also reads ``:closed:`` in a title as closed; only Coral may close a step."""
    guard, _, row = _bound(kind)
    for title in ("work:closed:x", ":closed:"):
        refusal = _decide(guard, dataclasses.replace(_update(row, "title"), title=title))
        assert refusal == _refusal("changing its title to one containing ':closed:'"), title
    for title in ("work: closed", "Closed", None):
        assert _decide(guard, dataclasses.replace(_update(row, "title"), title=title)) is None


@pytest.mark.parametrize("kind", INERT)
def test_the_anchor_and_a_closed_step_take_only_stop_and_runner_events(kind: str) -> None:
    guard, _, row = _bound(kind)
    for event_type in sorted(CLIENT_SESSION_EVENT_TYPES | {"session_message", NEW_CLIENT_EVENT}):
        refusal = _decide(guard, _event(row, event_type))
        if event_type in STOP_EVENTS:
            assert refusal is None, event_type
        else:
            assert refusal == _refusal(f"sending it a {event_type!r} event"), event_type
    for event_type in sorted(RUNNER_SESSION_EVENT_TYPES):
        assert _decide(guard, _event(row, event_type, runner_proven=True)) is None, event_type


@pytest.mark.parametrize("kind", [*OPEN, *INERT])
def test_the_anchor_takes_approvals_only_while_the_gate_handler_is_registered(kind: str) -> None:
    """Approvals answer gates on the anchor; a closed step refuses them whatever the flag."""
    answering = [False]
    guard, _, row = _bound(kind, gate_answering=lambda: answering[0])
    approval = _event(row, "approval")
    refused = _refusal("sending it a 'approval' event")
    without_handler = _decide(guard, approval)
    answering[0] = True

    assert guard.screen(approval) is Screen.CHECK
    if kind == "anchor":
        assert (without_handler, _decide(guard, approval)) == (refused, None)
        # Every other event keeps the anchor's allowlist.
        assert _decide(guard, _event(row, "message")) == _refusal("sending it a 'message' event")
    elif kind == "closed step":
        assert (without_handler, _decide(guard, approval)) == (refused, refused)
    else:
        assert (without_handler, _decide(guard, approval)) == (None, None)


@pytest.mark.parametrize("kind", OPEN)
def test_an_open_step_refuses_only_clear_and_peer_messages(kind: str) -> None:
    guard, _, row = _bound(kind)
    every_type = CLIENT_SESSION_EVENT_TYPES | {NEW_CLIENT_EVENT, "session_message"}
    for event_type in sorted(every_type):
        refusal = _decide(guard, _event(row, event_type))
        if event_type in ("clear", "session_message"):
            assert refusal == _refusal(f"sending it a {event_type!r} event"), event_type
        else:
            assert refusal is None, event_type


@pytest.mark.parametrize("kind", [*OPEN, *INERT])
def test_runner_only_events_need_the_sessions_own_runner(kind: str) -> None:
    """Owners may post these too, and some write the session (effort, launch args, children)."""
    guard, _, row = _bound(kind)
    for event_type in sorted(RUNNER_SESSION_EVENT_TYPES):
        refusal = _decide(guard, _event(row, event_type))
        assert refusal == _refusal(f"sending it a {event_type!r} event"), event_type
        assert _decide(guard, _event(row, event_type, runner_proven=True)) is None, event_type
    # The proof is about runner-only types; a client type keeps its own rule.
    if kind in INERT:
        assert _decide(guard, _event(row, "message", runner_proven=True)) is not None


@pytest.mark.parametrize("kind", [*OPEN, *INERT])
def test_other_session_changes_are_refused_on_every_bound_session(kind: str) -> None:
    guard, _, row = _bound(kind)
    for action, what in ALWAYS_REFUSED.items():
        attempt = MutationAttempt(action, session_id=SESSION, conversation=row)
        assert _decide(guard, attempt) == _refusal(what), action


def test_a_labelled_session_without_a_binding_is_ordinary() -> None:
    guard, lookup, row = _bound(None)
    attempts = [
        _update(row, "model_override", labels=(CLOSED_LABEL_KEY,)),
        _event(row, "session_message"),
        *(
            MutationAttempt(action, session_id=SESSION, conversation=row)
            for action in ALWAYS_REFUSED
        ),
    ]
    assert [_decide(guard, attempt) for attempt in attempts] == [None] * len(attempts)
    assert len(lookup.reads) == len(attempts)


def test_bindings_are_read_in_the_requests_workspace() -> None:
    guard, lookup, row = _bound("step")
    attempt = _update(row, "model_override")
    with workspace_scope(WORKSPACE + 1):
        assert guard.check(attempt) is None
    assert lookup.reads == [(WORKSPACE + 1, SESSION)]


def test_a_store_error_fails_closed_with_a_retryable_500(caplog: pytest.LogCaptureFixture) -> None:
    lookup = FakeBindingLookup(error=RuntimeError("bindings table locked"))
    guard = CoralMutationGuard(lookup)
    attempt = _update(_row(), "model_override")
    with caplog.at_level(logging.WARNING, logger="coral.omni.server.mutation_guard"):
        for _ in range(2):
            with workspace_scope(WORKSPACE), pytest.raises(OmnigentError) as failed:
                guard.check(attempt)
            assert failed.value.code == ErrorCode.INTERNAL_ERROR
            assert "retry" in failed.value.message and "locked" not in failed.value.message
    # One line per failure names the session; the traceback is logged once per process.
    lines = [record for record in caplog.records if record.exc_info is None]
    assert [getattr(record, "session_id", None) for record in lines] == [SESSION, SESSION]


@pytest.mark.parametrize("name", ["coral__step", "Coral__X", "CORAL__anchor"])
def test_engine_agents_cannot_be_edited_installed_or_quietly_removed(name: str) -> None:
    lookup = FakeBindingLookup(error=AssertionError("agent rules read nothing"))
    guard = CoralMutationGuard(lookup)

    def screen(action: str, *, forced: bool = False) -> Screen | str:
        return guard.screen(MutationAttempt(action, agent_name=name, forced=forced))

    assert screen(AGENT_UPDATE) == (
        f"Agent {name!r} is managed by Coral's workflow engine and can't be edited."
    )
    assert screen(AGENT_REMOVE) == (
        f"Agent {name!r} is managed by Coral's workflow engine; delete with force=true to "
        "remove it anyway (steps running it can no longer hand off, and their runs pause "
        "after repeated nudges)."
    )
    assert screen(AGENT_REMOVE, forced=True) is Screen.ALLOW
    assert (
        screen(AGENT_INSTALL)
        == "Names starting with coral__ are reserved for Coral's engine agents."
    )


def test_other_agents_are_unchanged() -> None:
    guard = CoralMutationGuard(FakeBindingLookup(error=AssertionError("no reads")))
    for name in ("orion", "coral_x", "coralx__y", "my_coral__x", None):
        for action in (AGENT_UPDATE, AGENT_REMOVE, AGENT_INSTALL):
            assert guard.screen(MutationAttempt(action, agent_name=name)) is Screen.ALLOW
