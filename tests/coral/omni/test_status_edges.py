"""Coral's narrow status-edge observer hands a watched session's edges to its waiters.

The observer is registered on Omnigent's real S1 registry, and edges come from
``_publish_status`` or ``notify_status_edge``. No server boots.
"""

from __future__ import annotations

import asyncio
import tracemalloc
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from coral.engine.facts import TurnFact
from coral.engine.turn_end import evaluate
from coral.omni.protocols import ObservedEdge
from coral.omni.server import status_edges as status_edges_module
from coral.omni.server.status_edges import CoralStatusEdges
from coral.slots.close import ConfirmedStops, outcome_for, turn_ended
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID, workspace_scope
from omnigent.runtime import session_stream
from omnigent.server import session_live_state
from omnigent.server.session_live_state import SessionStatusEdge, notify_status_edge

SESSION = "5e55a7e0c0de4d1e8a0b1c2d3e4f5a01"
# The workspace the server's edges carry outside any workspace scope.
WS = DEFAULT_WORKSPACE_ID
OBSERVER = "coral-status-edges-test"
# A short bound for waits that must not match; nothing here sleeps.
NO_MATCH_S = 0.05

# Every other fact a reducer reads, set the way a successful turn would be.
COMPLETION_FIELDS: dict[str, Any] = {
    "engine_stable_id_present": True,
    "newest_substantive_item_is_assistant": True,
    "saw_response_completed": True,
    "background_tasks": 0,
    "pending_elicitation_count": 0,
    "engine_pending_input": False,
    "engine_started": True,
    "origin": "engine",
}


@pytest.fixture
async def running_edges() -> CoralStatusEdges:
    """Coral's observer on this test's loop; tests register it on the real registry."""
    return CoralStatusEdges(asyncio.get_running_loop())


def _registered(observer: CoralStatusEdges) -> Callable[[], None]:
    return session_live_state.register_status_edge_observer(OBSERVER, observer.observe)


def _filled(fact: TurnFact) -> TurnFact:
    return fact.model_copy(update=COMPLETION_FIELDS)


def _publish(session_id: str, status: str, **fields: Any) -> None:
    from omnigent.server.routes._sessions import helpers

    helpers._publish_status(session_id, status, **fields)


def _forget(session_id: str) -> None:
    from omnigent.server.routes._sessions import helpers

    helpers._session_status_cache.pop(session_id, None)
    helpers._session_active_response_cache.pop(session_id, None)
    helpers._session_blocked_on_cache.pop(session_id, None)
    session_live_state.forget_turn_outcomes(session_id)
    session_stream.close(session_id)


async def test_stop_edge_reaches_coral_as_cancelled_never_completed(
    running_edges: CoralStatusEdges,
) -> None:
    unregister = _registered(running_edges)
    try:
        async with running_edges.watch(
            SESSION, workspace_id=WS, slot_id="review/item-0/m0"
        ) as watch:
            _publish(SESSION, "running", response_id="resp_1")
            # The stop's idle edge, as the server settles an intentionally stopped turn.
            _publish(
                SESSION,
                "idle",
                persist_live_status=False,
                turn_outcome="cancelled",
                turn_response_id="resp_1",
            )
            _publish(SESSION, "idle", persist_live_status=False)
            stopped = await watch.wait_for(outcome_for("resp_1"), timeout_s=5)
            plain_idle = await watch.wait_for(
                lambda seen: seen.edge.status == "idle" and seen.edge.turn_outcome is None,
                timeout_s=5,
            )
    finally:
        unregister()
        _forget(SESSION)

    assert stopped is not None and plain_idle is not None
    fact = stopped.fact
    assert (fact.session_id, fact.slot_id, fact.response_id) == (
        SESSION,
        "review/item-0/m0",
        "resp_1",
    )
    assert (fact.live_status, fact.turn_outcome) == ("idle", "cancelled")
    # Even with every other completion field true, a stop is a cancelled turn.
    assert evaluate(_filled(fact)) == "cancelled"
    # An idle edge without an outcome never reads as completed: the edge has no
    # word on whether a response completed, so that fact stays unknown.
    assert plain_idle.fact.turn_outcome is None
    assert plain_idle.fact.saw_response_completed is None
    others = {
        key: value for key, value in COMPLETION_FIELDS.items() if key != "saw_response_completed"
    }
    assert evaluate(plain_idle.fact.model_copy(update=others)) != "completed"


async def test_the_servers_own_stop_rule_reaches_coral_as_cancelled_and_ends_the_wait(
    running_edges: CoralStatusEdges,
) -> None:
    from omnigent.server.routes._sessions.orchestration import _stopped_turn

    unregister = _registered(running_edges)
    try:
        async with running_edges.watch(
            SESSION, workspace_id=WS, slot_id="build/item-0/m0"
        ) as watch:
            _publish(SESSION, "running", response_id="resp_1")
            # The intentional-stop settle publishes what the server's stop rule reports.
            outcome, stopped_turn_id = _stopped_turn(SESSION, None)
            _publish(
                SESSION,
                "idle",
                persist_live_status=False,
                turn_outcome=outcome,
                turn_response_id=stopped_turn_id,
            )
            # The runner's own turn end for that response is relayed after the stop.
            _publish(
                SESSION,
                "idle",
                persist_live_status=False,
                turn_outcome="completed",
                turn_response_id="resp_1",
            )
            seen = await _all(watch, 3)
            first = await watch.wait_for(outcome_for("resp_1"), timeout_s=5)
    finally:
        unregister()
        _forget(SESSION)

    assert (outcome, stopped_turn_id) == ("cancelled", "resp_1")
    _, stop, late = seen
    assert (stop.fact.turn_outcome, stop.fact.response_id) == ("cancelled", "resp_1")
    assert evaluate(_filled(stop.fact)) == "cancelled"
    # The first terminal outcome ends a close's or cancel's wait: the stop's.
    assert first is stop
    # The runner's own later report is the response's latest outcome (BA-11); the
    # server never infers one after a runner report, so "latest" is the runner's.
    assert (late.fact.turn_outcome, late.fact.response_id) == ("completed", "resp_1")


async def test_two_workspaces_watching_one_session_id_see_only_their_own_edges(
    running_edges: CoralStatusEdges,
) -> None:
    unregister = _registered(running_edges)
    try:
        with workspace_scope(7):
            ours = running_edges.watch(SESSION, workspace_id=7, slot_id="ws7")
            ours_watch = await ours.__aenter__()
        with workspace_scope(8):
            theirs = running_edges.watch(SESSION, workspace_id=8, slot_id="ws8")
            theirs_watch = await theirs.__aenter__()
        try:
            # The real publish takes its workspace from the caller's scope.
            with workspace_scope(7):
                _publish(SESSION, "running", response_id="resp_1")
                _publish(
                    SESSION,
                    "idle",
                    persist_live_status=False,
                    turn_outcome="cancelled",
                    turn_response_id="resp_1",
                )
            with workspace_scope(8):
                _publish(SESSION, "running", response_id="resp_1")
                _publish(
                    SESSION,
                    "idle",
                    persist_live_status=False,
                    turn_outcome="completed",
                    turn_response_id="resp_1",
                )
            ours_seen = await _all(ours_watch, 2)
            theirs_seen = await _all(theirs_watch, 2)
            # No edge crossed over: neither watch ever sees the other workspace's outcome.
            crossed_into_ours = await ours_watch.wait_for(
                lambda seen: seen.edge.turn_outcome == "completed", timeout_s=NO_MATCH_S
            )
            crossed_into_theirs = await theirs_watch.wait_for(
                lambda seen: seen.edge.turn_outcome == "cancelled", timeout_s=NO_MATCH_S
            )
        finally:
            await theirs.__aexit__(None, None, None)
            await ours.__aexit__(None, None, None)
    finally:
        unregister()
        for workspace in (7, 8):
            with workspace_scope(workspace):
                _forget(SESSION)

    assert (crossed_into_ours, crossed_into_theirs) == (None, None)
    assert [(seen.fact.slot_id, seen.fact.turn_outcome) for seen in ours_seen] == [
        ("ws7", None),
        ("ws7", "cancelled"),
    ]
    # ws7's cancelled outcome for resp_1 is not attributed to ws8's resp_1.
    assert [(seen.fact.slot_id, seen.fact.turn_outcome) for seen in theirs_seen] == [
        ("ws8", None),
        ("ws8", "completed"),
    ]


async def test_concurrent_watches_share_edges_and_an_ended_watch_receives_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts: list[TurnFact] = []
    observer = CoralStatusEdges(asyncio.get_running_loop(), sink=facts.append)
    async with observer.watch(SESSION, workspace_id=WS, slot_id="close") as close_watch:
        async with observer.watch(SESSION, workspace_id=WS, slot_id="cancel") as cancel_watch:
            observer.observe(_edge("idle", outcome="cancelled", turn_response_id="resp_1"))
            by_cancel = await cancel_watch.wait_for(outcome_for("resp_1"), timeout_s=5)
        observer.observe(_edge("idle", outcome="completed", turn_response_id="resp_2"))
        by_close = await close_watch.wait_for(outcome_for("resp_2"), timeout_s=5)
        first = await close_watch.wait_for(outcome_for("resp_1"), timeout_s=NO_MATCH_S)
    # Every watch has ended: an edge now schedules nothing.
    loop = asyncio.get_running_loop()
    scheduled: list[object] = []
    monkeypatch.setattr(loop, "call_soon_threadsafe", lambda *args: scheduled.append(args))
    observer.observe(_edge("idle", outcome="failed", turn_response_id="resp_3"))

    assert by_cancel is not None and by_close is not None and first is not None
    assert scheduled == []
    # One fact per edge for the sink, whatever the number of watches.
    assert [(fact.response_id, fact.turn_outcome) for fact in facts] == [
        ("resp_1", "cancelled"),
        ("resp_2", "completed"),
    ]


def test_a_running_edge_published_by_the_server_clears_a_confirmed_stop() -> None:
    stops = ConfirmedStops()
    unregister = session_live_state.register_status_edge_observer(OBSERVER, stops.observe)
    try:
        stops.record(WS, SESSION)
        _publish(SESSION, "idle", persist_live_status=False)
        after_idle = stops.confirmed(WS, SESSION)
        # A user relaunched the stopped session and its turn started.
        _publish(SESSION, "running", response_id="resp_2", persist_live_status=False)
    finally:
        unregister()
        _forget(SESSION)

    assert after_idle is True
    assert stops.confirmed(WS, SESSION) is False


async def test_completed_edge_for_another_response_is_not_attributed_to_the_cancelled_turn(
    running_edges: CoralStatusEdges,
) -> None:
    unregister = _registered(running_edges)
    try:
        async with running_edges.watch(SESSION, workspace_id=WS) as late:
            # A watch that sees only the continuation's completion never finds resp_1's end.
            notify_status_edge(_edge("idle", outcome="completed", turn_response_id="resp_2"))
            assert await late.wait_for(outcome_for("resp_1"), timeout_s=NO_MATCH_S) is None
            assert await late.wait_for(turn_ended("resp_1"), timeout_s=NO_MATCH_S) is None
        async with running_edges.watch(SESSION, workspace_id=WS) as watch:
            # An interrupt with buffered input: the continuation's running edge carries
            # resp_1's outcome, then the continuation completes under resp_2.
            notify_status_edge(
                _edge(
                    "running", response_id="resp_2", outcome="cancelled", turn_response_id="resp_1"
                )
            )
            notify_status_edge(_edge("idle", outcome="completed", turn_response_id="resp_2"))
            cancelled = await watch.wait_for(outcome_for("resp_1"), timeout_s=5)
            completed = await watch.wait_for(outcome_for("resp_2"), timeout_s=5)
    finally:
        unregister()
        _forget(SESSION)

    assert cancelled is not None and completed is not None
    assert (cancelled.edge.status, cancelled.fact.turn_outcome) == ("running", "cancelled")
    assert cancelled.fact.response_id == "resp_1"
    assert evaluate(_filled(cancelled.fact)) == "cancelled"
    assert (completed.fact.turn_outcome, completed.fact.response_id) == ("completed", "resp_2")


async def test_an_unwatched_sessions_edge_allocates_nothing(
    running_edges: CoralStatusEdges, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = asyncio.get_running_loop()
    scheduled: list[object] = []
    monkeypatch.setattr(loop, "call_soon_threadsafe", lambda *args: scheduled.append(args))
    edge = _edge("idle", outcome="completed", turn_response_id="resp_1")
    async with running_edges.watch("another-session", workspace_id=WS):
        tracemalloc.start()
        try:
            before = tracemalloc.take_snapshot()
            for _ in range(200):
                running_edges.observe(edge)
            after = tracemalloc.take_snapshot()
        finally:
            tracemalloc.stop()
    only_here = [tracemalloc.Filter(True, status_edges_module.__file__)]
    growth = after.filter_traces(only_here).compare_to(before.filter_traces(only_here), "lineno")
    assert sum(stat.count_diff for stat in growth) == 0
    assert scheduled == []


async def test_watchers_key_on_workspace_and_session(running_edges: CoralStatusEdges) -> None:
    unregister = _registered(running_edges)
    try:
        with workspace_scope(7):
            async with running_edges.watch(SESSION, workspace_id=7) as watch:
                # The same session id in another workspace is another session.
                notify_status_edge(
                    _edge("idle", outcome="completed", turn_response_id="resp_1", ws=8)
                )
                assert await watch.wait_for(turn_ended("resp_1"), timeout_s=NO_MATCH_S) is None
                notify_status_edge(
                    _edge("idle", outcome="cancelled", turn_response_id="resp_1", ws=7)
                )
                own = await watch.wait_for(turn_ended("resp_1"), timeout_s=5)
    finally:
        unregister()

    assert own is not None and own.fact.turn_outcome == "cancelled"


async def test_an_edge_published_off_the_loop_reaches_the_waiter(
    running_edges: CoralStatusEdges,
) -> None:
    unregister = _registered(running_edges)
    try:
        async with running_edges.watch(SESSION, workspace_id=WS) as watch:
            # Omnigent publishes some edges from a worker thread (orphan reconcile).
            await asyncio.to_thread(
                notify_status_edge, _edge("idle", outcome="cancelled", turn_response_id="resp_1")
            )
            seen = await watch.wait_for(outcome_for("resp_1"), timeout_s=5)
    finally:
        unregister()
        session_live_state.forget_turn_outcomes(SESSION)

    assert seen is not None and seen.fact.turn_outcome == "cancelled"


async def test_the_latest_outcome_for_a_response_wins_and_the_first_ends_the_wait(
    running_edges: CoralStatusEdges,
) -> None:
    async with running_edges.watch(SESSION, workspace_id=WS) as watch:
        # A runner drop is inferred as failed; the runner then reports the turn completed.
        running_edges.observe(
            _edge("failed", outcome="failed", turn_response_id="r1", origin="runner_disconnect")
        )
        running_edges.observe(
            _edge("idle", outcome="completed", turn_response_id="r1", origin="relay_turn_end")
        )
        # A continuation's running edge carries the previous turn's outcome.
        running_edges.observe(
            _edge("running", response_id="r2", outcome="cancelled", turn_response_id="r1")
        )
        seen = await _all(watch, 3)
        first = await watch.wait_for(outcome_for("r1"), timeout_s=5)

    # Every fact carries its own edge's outcome, so the newest one for r1 is r1's outcome.
    assert [(item.fact.response_id, item.fact.turn_outcome) for item in seen] == [
        ("r1", "failed"),
        ("r1", "completed"),
        ("r1", "cancelled"),
    ]
    assert [item.edge.turn_outcome for item in seen] == ["failed", "completed", "cancelled"]
    # A waiter ends at the first terminal outcome it sees.
    assert first is seen[0]


async def test_an_outcome_without_a_response_never_matches_a_response_waiter(
    running_edges: CoralStatusEdges,
) -> None:
    async with running_edges.watch(SESSION, workspace_id=WS) as watch:
        # A teardown's second idle names no response; it ends no response-keyed wait.
        running_edges.observe(_edge("running", outcome="cancelled", response_id="resp_1"))
        assert await watch.wait_for(outcome_for("resp_1"), timeout_s=NO_MATCH_S) is None
        assert await watch.wait_for(outcome_for(None), timeout_s=NO_MATCH_S) is None
        # A running edge is no turn end either, whatever response it opens.
        assert await watch.wait_for(turn_ended("resp_1"), timeout_s=NO_MATCH_S) is None


async def test_the_sink_gets_each_watched_fact_and_its_failure_is_isolated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    facts: list[TurnFact] = []

    def sink(fact: TurnFact) -> None:
        facts.append(fact)
        raise RuntimeError("sink is down")

    observer = CoralStatusEdges(asyncio.get_running_loop(), sink=sink)
    observer.observe(_edge("idle", outcome="completed", turn_response_id="unwatched"))
    async with observer.watch(SESSION, workspace_id=WS, slot_id="slot-a") as watch:
        observer.observe(_edge("idle", outcome="cancelled", turn_response_id="resp_1"))
        seen = await watch.wait_for(outcome_for("resp_1"), timeout_s=5)

    assert seen is not None
    assert [(fact.slot_id, fact.response_id) for fact in facts] == [("slot-a", "resp_1")]
    assert "sink" in caplog.text


async def test_a_watch_on_another_loop_is_refused() -> None:
    other = asyncio.new_event_loop()
    try:
        with pytest.raises(RuntimeError):
            async with CoralStatusEdges(other).watch(SESSION, workspace_id=WS):
                pass
    finally:
        other.close()


def test_observe_never_raises_and_drops_edges_for_a_closed_loop() -> None:
    loop = asyncio.new_event_loop()
    observer = CoralStatusEdges(loop)
    loop.run_until_complete(observer.watch(SESSION, workspace_id=WS).__aenter__())
    loop.close()
    # The watcher's loop is gone: the edge is dropped, and the publisher is unharmed.
    observer.observe(_edge("idle", outcome="cancelled", turn_response_id="resp_1"))
    # Neither does a malformed edge reach the publisher as an exception.
    observer.observe(SimpleNamespace(session_id=SESSION))  # type: ignore[arg-type]


async def test_an_edge_delivered_before_the_wait_is_not_missed(
    running_edges: CoralStatusEdges,
) -> None:
    async with running_edges.watch(SESSION, workspace_id=WS) as watch:
        running_edges.observe(_edge("idle", outcome="cancelled", turn_response_id="resp_1"))
        # Let the delivery run before anyone waits, as when a close reads live status.
        await asyncio.sleep(0)
        seen = await watch.wait_for(turn_ended("resp_1"), timeout_s=NO_MATCH_S)

    assert seen is not None and seen.fact.turn_outcome == "cancelled"


async def _all(watch: Any, count: int) -> list[ObservedEdge]:
    """The first ``count`` edges the watch delivered, in order."""
    seen: list[ObservedEdge] = []

    def collect(observed: ObservedEdge) -> bool:
        seen.append(observed)
        return len(seen) >= count

    assert await watch.wait_for(collect, timeout_s=5) is not None
    return seen


def _edge(
    status: str,
    *,
    outcome: str | None = None,
    turn_response_id: str | None = None,
    response_id: str | None = None,
    origin: str = "unknown",
    ws: int | None = None,
) -> SessionStatusEdge:
    fields: dict[str, Any] = {
        "origin": origin,
        "turn_outcome": outcome,
        "turn_response_id": turn_response_id,
        "response_id": response_id,
    }
    if ws is not None:
        fields["workspace_id"] = ws
    return SessionStatusEdge(SESSION, status, None, **fields)
