"""Coral's stop, cancel and close reach Coral as a cancelled turn, end to end.

Tier A, the production path with no hand-written turn fields: the engine's
brief goes through ``OmnigentSessionDispatch`` and the real ``_post_event_impl``
to an in-process ``create_runner_app`` over the WS tunnel (the three-layer
harness). Coral's ``stop``, ``cancel_session`` and a reader's ``close_session``
end the turn through the same route. The runner reports each turn end (S43),
the server relays it, and S1 hands the edge to ``CoralStatusEdges``. Only the
harness is a stub, so a turn can be held open until the runner ends it. A close
after a server restart mid-turn is the same stack with the server's status caches
emptied and the rest of the turn stored under a new id, as a restarted server leaves
them.

Not covered here: the session is hostless and bound with ``PATCH runner_id``,
not a facade step, so the host-owner runner kill and the server's own inferred
``cancelled`` edge are covered only by component tests
(``tests/server/routes/test_intentional_runner_stop.py``,
``tests/coral/omni/test_status_edges.py``). A writer's close and its commit are
covered by ``tests/coral/slots/test_close.py`` and the AC3 host-channel test.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI

from coral.engine.facts import TurnFact
from coral.engine.turn_end import evaluate
from coral.omni.protocols import LiveStatus, engine_message_text
from coral.omni.server.dispatch import OmnigentSessionDispatch
from coral.omni.server.status_edges import CoralStatusEdges
from coral.slots.close import (
    CloseBounds,
    CloseOutcome,
    ConfirmedStops,
    cancel_session,
    close_session,
    outcome_for,
)
from coral.stores.stable_ids import content_checksum
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID
from omnigent.entities import MessageData, NewConversationItem
from omnigent.runtime import get_conversation_store
from omnigent.server import session_live_state
from omnigent.server.routes import sessions as sessions_module
from omnigent.server.schemas import ErrorDetail
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.omni.test_status_edges import COMPLETION_FIELDS

# These names of an Omnigent test module, and its fake process manager's
# ``_clients``, are this test's upstream dependency: check them on a sync.
from tests.server.integration.test_sessions_tunnel_three_layer import (
    _RUNNER_ID,
    _build_harness_agent_bundle,
    _TunnelStack,
    tunnel_three_layer_stack,  # noqa: F401 — pytest injects the imported fixture
)

WS = DEFAULT_WORKSPACE_ID
SLOT = "review/item-0/m0"
OBSERVER = "coral-ac2-end-to-end-test"
BOUNDS = CloseBounds(turn_end_s=budget(30), interrupt_settle_s=budget(30))
# The held turn never ends by itself, so a close's wait for it runs to this bound.
CLOSE_BOUNDS = CloseBounds(turn_end_s=0.5, interrupt_settle_s=budget(30))
BRIEF = "Review the parser."


def _sse(event_type: str, response_id: str, status: str) -> str:
    """One SSE frame a harness streams for its response."""
    response = {
        "id": response_id,
        "status": status,
        "model": "echo-tunnel-test",
        "created_at": int(time.time()),
    }
    payload = json.dumps({"type": event_type, "response": response})
    return f"event: {event_type}\ndata: {payload}\n\n"


class _GatedHarness:
    """
    The step's harness: each turn opens its response, then ends as its script says.

    - ``honors_interrupt``: waits for the interrupt, then ends cancelled. Its
      reply to the interrupt waits until the runner has taken that turn end,
      as a harness that winds its turn down before answering does.
    - ``ignores_interrupt``: never ends on its own; only the runner cancelling
      the turn's task ends it.
    - ``completes``: completes at once.
    - ``completes_on_release``: completes once the test calls :meth:`release`.
    """

    def __init__(self, runner_app: FastAPI, session_id: str, turns: Sequence[str]) -> None:
        self._runner_app = runner_app
        self.session_id = session_id
        self._turns = tuple(turns)
        self.response_ids: list[str] = []
        self.interrupts = 0
        self._interrupted: dict[str, asyncio.Event] = {}
        self._released = asyncio.Event()

    def release(self) -> None:
        self._released.set()

    def stream(self, method: str, url: str, *, json: dict[str, Any], timeout: Any) -> Any:
        del method, url, json, timeout
        script = self._turns[len(self.response_ids)]
        response_id = f"resp_turn_{len(self.response_ids) + 1}"
        self.response_ids.append(response_id)
        interrupted = self._interrupted.setdefault(response_id, asyncio.Event())

        async def aiter_text() -> AsyncIterator[str]:
            yield _sse("response.created", response_id, "queued")
            yield _sse("response.in_progress", response_id, "in_progress")
            if script == "completes":
                yield _sse("response.completed", response_id, "completed")
            elif script == "completes_on_release":
                await self._released.wait()
                yield _sse("response.completed", response_id, "completed")
            elif script == "honors_interrupt":
                await interrupted.wait()
                yield _sse("response.cancelled", response_id, "cancelled")
            else:
                await asyncio.Event().wait()

        @asynccontextmanager
        async def opened() -> AsyncIterator[SimpleNamespace]:
            yield SimpleNamespace(status_code=200, aiter_text=aiter_text)

        return opened()

    async def post(self, url: str, *, json: dict[str, Any], timeout: Any = None) -> Any:
        del url, timeout
        if json.get("type") == "interrupt":
            self.interrupts += 1
        if json.get("type") == "interrupt" and self.response_ids:
            current = self.response_ids[-1]
            if self._turns[len(self.response_ids) - 1] == "honors_interrupt":
                self._interrupted[current].set()
                live = self._runner_app.state.live_response_id
                await poll_until_async(
                    lambda: live.get(self.session_id) != current, timeout_s=budget(30)
                )
        return SimpleNamespace(status_code=204, headers={}, content=b"", json=dict)

    async def aclose(self) -> None:
        return None


class _Lease:
    """``ensure_lease`` for a cancel or close: the facts Coral had seen before each side effect."""

    def __init__(
        self,
        facts: list[TurnFact],
        *,
        before_close: Callable[[], Awaitable[object]] | None = None,
    ) -> None:
        self._facts = facts
        self._before_close = before_close
        self.seen: list[list[TurnFact]] = []

    async def __call__(self) -> None:
        self.seen.append(list(self._facts))
        # The second check comes right before ``set_closed``.
        if len(self.seen) == 2 and self._before_close is not None:
            await self._before_close()


async def _bound_session(stack: _TunnelStack, harness_turns: Sequence[str]) -> _GatedHarness:
    """A session on the tunneled runner whose harness is the gated one, bound as a user would."""
    created = await stack.ap_client.post(
        "/v1/sessions",
        data={"metadata": json.dumps({})},
        files={"bundle": ("agent.tar.gz", _build_harness_agent_bundle(), "application/gzip")},
    )
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    harness = _GatedHarness(stack.runner_app, session_id, harness_turns)
    # The fake process manager serves one client per session; this session's is the gated one.
    stack.fake_pm._clients[session_id] = harness  # type: ignore[assignment]
    bound = await stack.ap_client.patch(
        f"/v1/sessions/{session_id}", json={"runner_id": _RUNNER_ID}
    )
    assert bound.status_code == 200, bound.text
    return harness


def _session_running(session_id: str, response_id: str) -> Callable[[], bool]:
    """The server's live status shows ``response_id`` running, as Coral's dispatch reads it."""

    def running() -> bool:
        return (
            sessions_module._session_status_cache.get(session_id) == "running"
            and sessions_module._session_active_response_cache.get(session_id) == response_id
        )

    return running


def _as_successful(fact: TurnFact) -> TurnFact:
    """The fact beside every other field of a successful turn, a completed response included."""
    return fact.model_copy(update=COMPLETION_FIELDS)


def _beside_a_successful_turn(fact: TurnFact) -> TurnFact:
    """
    The fact as observed, beside every field a reducer learns elsewhere for a successful turn.

    The edge's own origin is kept. An edge never reports a completed response,
    so that stays false unless the observer filled it in.
    """
    others = {
        name: value
        for name, value in COMPLETION_FIELDS.items()
        if name not in ("saw_response_completed", "origin")
    }
    saw_completed = bool(fact.saw_response_completed)
    return fact.model_copy(update={**others, "saw_response_completed": saw_completed})


@pytest.mark.parametrize("ending", ["interrupted", "buffered", "drain_cancel", "b1", "close"])
async def test_coral_stop_and_cancel_reach_coral_as_cancelled(
    tunnel_three_layer_stack: _TunnelStack,  # noqa: F811 — pytest injects the imported fixture
    ending: str,
) -> None:
    stack = tunnel_three_layer_stack
    turns = {
        "interrupted": ["honors_interrupt"],
        "buffered": ["honors_interrupt", "completes"],
        "drain_cancel": ["ignores_interrupt"],
        "b1": ["ignores_interrupt"],
        "close": ["honors_interrupt"],
    }[ending]
    harness = await _bound_session(stack, turns)
    session_id = harness.session_id
    store = get_conversation_store()
    facts: list[TurnFact] = []
    edges = CoralStatusEdges(asyncio.get_running_loop(), sink=facts.append)
    dispatch = OmnigentSessionDispatch(
        stack.ap_app, store, stack.ap_app.state.runner_router, pre_send_hooks=()
    )
    cancelled_turn = "resp_turn_1"
    stable_id = uuid.uuid4().hex
    lease: _Lease | None = None
    closed_by: CloseOutcome | None = None
    stops = ConfirmedStops()
    unregister = session_live_state.register_status_edge_observer(OBSERVER, edges.observe)
    try:
        async with edges.watch(session_id, workspace_id=WS, slot_id=SLOT) as watch:
            receipt = await dispatch.send_message(
                workspace_id=WS,
                run_id=uuid.uuid4().hex,
                session_id=session_id,
                user_id=None,
                stable_id=stable_id,
                text=BRIEF,
            )
            assert receipt.delivery == "sent"
            await poll_until_async(
                _session_running(session_id, cancelled_turn), timeout_s=budget(30)
            )

            if ending == "drain_cancel":
                # The harness ignores the forwarded interrupt; the runner cancels the turn's task.
                await dispatch.stop(session_id=session_id, user_id=None)
                stopped = await watch.wait_for(outcome_for(cancelled_turn), timeout_s=budget(30))
                assert stopped is not None
            elif ending == "close":
                # A reader's close: the turn outlives the bound, so the close interrupts it.
                lease = _Lease(facts)
                closed_by = await close_session(
                    workspace_id=WS,
                    session_id=session_id,
                    user_id=None,
                    slot_id=SLOT,
                    interrupt=True,
                    closed_label=True,
                    commit=None,
                    engine_messages={stable_id: content_checksum(engine_message_text(BRIEF))},
                    dispatch=dispatch,
                    edges=edges,
                    ensure_lease=lease,
                    bounds=CLOSE_BOUNDS,
                    stops=stops,
                )
                ended = await watch.wait_for(outcome_for(cancelled_turn), timeout_s=budget(30))
                assert ended is not None
            else:
                before_close: Callable[[], Awaitable[object]] | None = None
                if ending == "buffered":
                    # A message the user typed during the turn waits at the runner.
                    typed = await stack.ap_client.post(
                        f"/v1/sessions/{session_id}/events",
                        json={
                            "type": "message",
                            "data": {
                                "role": "user",
                                "content": [{"type": "input_text", "text": "Check the lexer."}],
                            },
                        },
                    )
                    assert typed.status_code == 202, typed.text
                    buffers = stack.runner_app.state.session_message_buffers
                    await poll_until_async(
                        lambda: bool(buffers.get(session_id)), timeout_s=budget(30)
                    )

                    # Let the continuation finish before the stop, as a quick answer would.
                    async def continuation_ended() -> object:
                        return await watch.wait_for(
                            outcome_for("resp_turn_2"), timeout_s=budget(30)
                        )

                    before_close = continuation_ended

                if ending == "b1":
                    # The server already wrote the turn off as a runner drop that the
                    # runner survived, as a transient disconnect leaves it. The cancel
                    # then reads the turn as ended and only closes and stops it.
                    sessions_module._session_status_cache[session_id] = "failed"
                    await sessions_module._persist_session_status_error_labels(
                        session_id,
                        ErrorDetail(code="runner_disconnected", message="Runner disconnected."),
                        store,
                    )
                lease = _Lease(facts, before_close=before_close)
                await cancel_session(
                    workspace_id=WS,
                    session_id=session_id,
                    user_id=None,
                    slot_id=SLOT,
                    closed_label=True,
                    dispatch=dispatch,
                    edges=edges,
                    ensure_lease=lease,
                    bounds=BOUNDS,
                )
                ended = await watch.wait_for(outcome_for(cancelled_turn), timeout_s=budget(30))
                assert ended is not None
    finally:
        unregister()

    reported = [
        fact
        for fact in facts
        if fact.response_id == cancelled_turn and fact.turn_outcome is not None
    ]
    assert reported, facts
    assert {fact.turn_outcome for fact in reported} == {"cancelled"}, facts
    # Even beside every other fact of a successful turn, each report is a cancelled turn.
    assert {evaluate(_as_successful(fact)) for fact in reported} == {"cancelled"}
    assert all(fact.slot_id == SLOT for fact in facts)
    # No fact evaluates completed, beside everything else a successful turn has,
    # but the user's own continuation, under its own response.
    verdicts = [(fact.response_id, evaluate(_beside_a_successful_turn(fact))) for fact in facts]
    assert {verdict for response, verdict in verdicts if response == cancelled_turn} <= {
        "cancelled",
        "not_ended",
    }
    completed = [response for response, verdict in verdicts if verdict == "completed"]
    assert completed == (["resp_turn_2"] if ending == "buffered" else [])

    endings = [(fact.live_status, fact.origin) for fact in reported]
    if ending == "interrupted":
        assert ("idle", "unknown") in endings
    elif ending == "buffered":
        # The interrupted turn's outcome rides the continuation's running edge.
        assert endings[0] == ("running", "unknown")
        assert harness.response_ids == ["resp_turn_1", "resp_turn_2"]
    elif ending == "drain_cancel":
        assert endings[0] == ("idle", "unknown")
    elif ending == "b1":
        # The recovered idle (B1) carries the runner's own outcome.
        assert ("idle", "relay_turn_end") in endings
    else:
        assert ("idle", "unknown") in endings
        # The interrupt came after the bound, while the turn still ran; nothing
        # was queued after the brief; the stop was confirmed and recorded.
        assert closed_by == CloseOutcome(
            pending_input=False,
            queued_input=False,
            post_accept_edits=False,
            commit=None,
            empty=None,
            diff_stat=None,
            forced_stop=False,
        )
        assert lease is not None and len(lease.seen) == 3
        assert not any(fact.turn_outcome for fact in lease.seen[0])
        assert stops.confirmed(WS, session_id)
        assert session_id not in stack.runner_app.state.active_turns

    def cancelled_before(seen: list[TurnFact]) -> bool:
        return any(
            fact.response_id == cancelled_turn and fact.turn_outcome == "cancelled"
            for fact in seen
        )

    if lease is not None and ending != "b1":
        # The wait ended on the runner's report, before the session was closed.
        assert cancelled_before(lease.seen[1])
    closed = store.get_conversation(session_id)
    assert closed is not None
    assert (closed.labels or {}).get(CLOSED_LABEL_KEY) == (CLOSED_LABEL_VALUE if lease else None)


class _ReadsLive(OmnigentSessionDispatch):
    """The real dispatch, keeping each live status the close read."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reads: list[LiveStatus] = []
        self.read = asyncio.Event()

    async def live_status(self, *, session_id: str) -> LiveStatus:
        live = await super().live_status(session_id=session_id)
        self.reads.append(live)
        self.read.set()
        return live


async def test_a_close_after_a_restart_mid_turn_ends_at_the_turns_own_end_edge(
    tunnel_three_layer_stack: _TunnelStack,  # noqa: F811 — pytest injects the imported fixture
) -> None:
    stack = tunnel_three_layer_stack
    harness = await _bound_session(stack, ["completes_on_release"])
    session_id = harness.session_id
    store = get_conversation_store()
    edges = CoralStatusEdges(asyncio.get_running_loop())
    dispatch = _ReadsLive(stack.ap_app, store, stack.ap_app.state.runner_router, pre_send_hooks=())
    stable_id = uuid.uuid4().hex
    unregister = session_live_state.register_status_edge_observer(OBSERVER, edges.observe)
    try:
        receipt = await dispatch.send_message(
            workspace_id=WS,
            run_id=uuid.uuid4().hex,
            session_id=session_id,
            user_id=None,
            stable_id=stable_id,
            text=BRIEF,
        )
        assert receipt.delivery == "sent"
        await poll_until_async(_session_running(session_id, "resp_turn_1"), timeout_s=budget(30))
        # The server restarts mid-turn: its caches are cold, and the rest of the turn is
        # stored under an id of the restarted server's own.
        for cache in (
            sessions_module._session_status_cache,
            sessions_module._session_active_response_cache,
            sessions_module._session_blocked_on_cache,
        ):
            cache.pop(session_id, None)
        working = MessageData(
            role="assistant", content=[{"type": "output_text", "text": "Working."}], agent="a"
        )
        store.append(
            session_id,
            [NewConversationItem(type="message", response_id="turn_after_restart", data=working)],
        )
        dispatch.reads.clear()
        close = asyncio.create_task(
            close_session(
                workspace_id=WS,
                session_id=session_id,
                user_id=None,
                slot_id=SLOT,
                interrupt=True,
                closed_label=True,
                commit=None,
                engine_messages={stable_id: content_checksum(engine_message_text(BRIEF))},
                dispatch=dispatch,
                edges=edges,
                ensure_lease=_Lease([]),
                bounds=BOUNDS,
                stops=ConfirmedStops(),
            )
        )
        await asyncio.wait_for(dispatch.read.wait(), timeout=budget(30))
        # The close is watching; the turn the old server saw start now ends.
        harness.release()
        released = time.monotonic()
        outcome = await asyncio.wait_for(close, timeout=budget(60))
        took = time.monotonic() - released
    finally:
        unregister()

    first = dispatch.reads[0]
    assert (first.status, first.response_id, first.response_observed) == (
        "running",
        "turn_after_restart",
        False,
    )
    # The turn's own end ended the wait, long before the bound a guessed id would sit out.
    assert took < BOUNDS.turn_end_s / 2, took
    assert harness.interrupts == 0
    assert outcome.forced_stop is False
