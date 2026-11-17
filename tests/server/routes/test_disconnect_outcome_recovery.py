"""Disconnect-failure outcome logging on the real reconnect recovery path."""

from __future__ import annotations

import pytest

from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests.debug_log_helpers import capture_debug_rows


@pytest.mark.asyncio
# CORAL(S1): the sweep fails a known interrupted turn; with no turn id there is none to fail,
# and a turn the runner already reported keeps its one outcome.
@pytest.mark.parametrize(
    ("turn_id", "reported"), [("resp-dropped", False), (None, False), ("resp-dropped", True)]
)
@pytest.mark.parametrize(
    ("passive", "next_step", "expected"),
    [
        (True, "resume", ["turn_resumed"]),
        (True, "user_turn", ["superseded_by_user_turn"]),
        # An explicit rebind is already a user action; the old turn can't resume.
        (False, "resume", []),
    ],
)
async def test_disconnect_failure_outcome_after_reconnect(
    db_uri: str,
    passive: bool,
    next_step: str,
    expected: list[str],
    turn_id: str | None,
    reported: bool,
) -> None:
    """A reconnect-cleared disconnect failure records whether its turn resumed."""
    from omnigent.runtime import disconnect_outcome, session_stream
    from omnigent.server import session_live_state  # CORAL(S1): status-edge observer
    from omnigent.server.routes import sessions as sessions_module
    from omnigent.server.schemas import ErrorDetail

    disconnect_outcome.reset_for_tests()
    store = SqlAlchemyConversationStore(db_uri)
    conv = store.create_conversation(runner_id="runner-outcome")
    session_id = conv.id
    store.set_session_live_status(session_id, "running")
    sessions_module._session_status_cache[session_id] = "running"
    if turn_id is not None:
        sessions_module._session_active_response_cache[session_id] = turn_id
    snapshot = store.get_conversation(session_id)
    assert snapshot is not None
    if reported:  # CORAL(S1): the runner already reported this turn's outcome.
        session_live_state.notify_status_edge(
            session_live_state.SessionStatusEdge(
                session_id, "running", None, turn_outcome="completed", turn_response_id=turn_id
            )
        )
    # CORAL(S1): one failed edge for the dropped turn, then one recovered idle edge.
    edges: list[session_live_state.SessionStatusEdge] = []
    unregister = session_live_state.register_status_edge_observer("test-recovery", edges.append)
    try:
        await sessions_module._mark_runner_sessions_offline(
            [snapshot],
            ErrorDetail(code="runner_disconnected", message="Runner disconnected unexpectedly."),
            store,
        )
        assert sessions_module._session_status_cache.get(session_id) == "failed"
        with capture_debug_rows("server") as rows:
            await sessions_module._publish_runner_recovered_status(
                session_id, store, require_disconnect_code=passive
            )
            if next_step == "user_turn":
                disconnect_outcome.note_user_turn(session_id)
            session_stream.publish(
                session_id, {"type": "response.output_text.delta", "delta": "still working"}
            )
        assert sessions_module._session_status_cache.get(session_id) == "idle"
        outcomes = [
            row["attributes"]["outcome"]
            for row in rows
            if row["event_name"] == "session_turn_failure_outcome"
        ]
        assert outcomes == expected
        assert [
            (
                edge.status,
                edge.previous_status,
                edge.origin,
                edge.turn_outcome,
                edge.turn_response_id,
            )
            for edge in edges
            if edge.session_id == session_id
        ] == [
            (
                "failed",
                "running",
                "unknown",
                *(("failed", turn_id) if turn_id and not reported else (None, None)),
            ),
            ("idle", "failed", "unknown", None, None),
        ]
    finally:
        unregister()
        disconnect_outcome.reset_for_tests()
        sessions_module._session_status_cache.pop(session_id, None)
        sessions_module._session_active_response_cache.pop(session_id, None)
        session_stream.close(session_id)


@pytest.mark.asyncio
async def test_passive_reconnect_keeps_genuine_failure_unwatched(db_uri: str) -> None:
    """A real task failure survives a reconnect and is never marked resumed."""
    from omnigent.runtime import disconnect_outcome, session_stream
    from omnigent.server import session_live_state  # CORAL(S1): status-edge observer
    from omnigent.server.routes import sessions as sessions_module

    disconnect_outcome.reset_for_tests()
    store = SqlAlchemyConversationStore(db_uri)
    conv = store.create_conversation(runner_id="runner-genuine")
    store.set_labels(
        conv.id,
        {
            "omnigent.last_task_error_code": "native_turn_error",
            "omnigent.last_task_error_message": "Synthetic provider rejection",
        },
    )
    # CORAL(S1): neither early return (not failed; a genuine failure) reports an edge.
    edges: list[session_live_state.SessionStatusEdge] = []
    unregister = session_live_state.register_status_edge_observer("test-recovery", edges.append)
    try:
        await sessions_module._publish_runner_recovered_status(conv.id, store)
        sessions_module._session_status_cache[conv.id] = "failed"
        with capture_debug_rows("server") as rows:
            await sessions_module._publish_runner_recovered_status(
                conv.id, store, require_disconnect_code=True
            )
            session_stream.publish(conv.id, {"type": "session.status", "status": "running"})
        assert sessions_module._session_status_cache.get(conv.id) == "failed"
        assert not any(
            row["event_name"] in ("session_turn_failure_cleared", "session_turn_failure_outcome")
            for row in rows
        )
        assert not [edge for edge in edges if edge.session_id == conv.id]
    finally:
        unregister()
        disconnect_outcome.reset_for_tests()
        sessions_module._session_status_cache.pop(conv.id, None)
        session_stream.close(conv.id)
