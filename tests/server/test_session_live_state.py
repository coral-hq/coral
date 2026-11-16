"""Tests for the session live-state persistence chokepoint.

Covers ``omnigent.server.session_live_state``: writes are deduplicated,
ordered, and best-effort, and the pending-elicitations index drives the
persisted count through its hook. These writes are what let a replica
that does NOT hold a session's runner tunnel serve the sidebar's live
fields, so the contract under test is "every real transition reaches the
store exactly once".

Writes land on a background single-worker executor, so each test waits
on the observable effect (the recording store's captured writes) with a
short polling deadline — the same shape as the host-tunnel route tests'
``_wait_*`` helpers — rather than reaching into the module's executor.
"""

from __future__ import annotations

# CORAL(S1): asyncio, dataclasses, logging, uuid, Iterator, SimpleNamespace, Any, AsyncMock,
# session_stream, ErrorDetail and the relay fakes serve the status-edge tests below.
import asyncio
import dataclasses
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from omnigent.runtime import pending_elicitations, session_stream
from omnigent.server import session_live_state
from omnigent.server.schemas import ErrorDetail
from tests.server.routes.test_sessions_runner_relay import (
    _RecordingLabelStore,
    _ScriptedRunnerClient,
    _TunnelCloseRunnerClient,
)


def _wait_until(predicate, *, timeout_s: float = 10.0) -> None:
    """Poll until *predicate* holds or the deadline elapses.

    The live-state writes are applied on a background executor thread, so
    a test asserting on their effect must wait for that thread rather than
    read synchronously. Returning on timeout (instead of raising) lets the
    caller's own assertion produce the informative failure — including the
    "should NOT have happened" cases where the predicate never becomes
    true by design.

    A passing predicate returns immediately, so the ceiling is only hit on
    a genuine failure; it's set generously (not ~2s) so a loaded CI runner
    doesn't spuriously time out before the background worker drains.

    :param predicate: Zero-arg callable returning truthy when done.
    :param timeout_s: Max seconds to poll before giving up.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)


class _RecordingStore:
    """Conversation-store stand-in that records live-state writes."""

    def __init__(self) -> None:
        self.status_writes: list[tuple[str, str]] = []
        self.pending_writes: list[tuple[str, int]] = []
        self.background_writes: list[tuple[str, bool]] = []
        self.blocked_writes: list[tuple[str, str | None]] = []
        self.touches: list[list[str]] = []
        self.clears: list[tuple[str, int | None]] = []

    def set_session_live_status(self, conversation_id: str, status: str) -> None:
        self.status_writes.append((conversation_id, status))

    def set_pending_elicitation_count(self, conversation_id: str, count: int) -> None:
        self.pending_writes.append((conversation_id, count))

    def set_background_work_running(
        self,
        conversation_id: str,
        running: bool,
        *,
        runner_id: str | None = None,
        unseen_since: int | None = None,
        reported_at: int | None = None,
    ) -> None:
        guard = () if runner_id is None else (runner_id, unseen_since)
        stamp = () if reported_at is None else (reported_at,)
        self.background_writes.append((conversation_id, running, *guard, *stamp))

    def set_blocked_on(self, conversation_id: str, blocked_on: str | None) -> None:
        self.blocked_writes.append((conversation_id, blocked_on))

    def touch_runner_liveness(self, runner_ids: list[str], now: int) -> None:
        del now
        self.touches.append(runner_ids)

    def clear_runner_liveness(self, runner_id: str, not_after: int | None = None) -> None:
        self.clears.append((runner_id, not_after))


@pytest.fixture()
def recording_store() -> _RecordingStore:
    """Wire a recording store into the module; unwire on teardown."""
    store = _RecordingStore()
    session_live_state.configure(store)  # type: ignore[arg-type]
    yield store
    session_live_state.configure(None)
    pending_elicitations.set_count_persist_hook(None)


def test_persist_live_status_dedupes_transitions(recording_store: _RecordingStore) -> None:
    """Only actual transitions reach the store; re-publishes are dropped.

    The SSE relay republishes statuses freely (e.g. a PTY watcher's
    repeated ``idle``); without dedupe every list tick would turn into
    row churn on the conversations table.
    """
    session_live_state.persist_live_status("conv_1", "running")
    session_live_state.persist_live_status("conv_1", "running")
    session_live_state.persist_live_status("conv_1", "idle")
    session_live_state.persist_live_status("conv_2", "idle")
    _wait_until(lambda: len(recording_store.status_writes) >= 3)
    assert recording_store.status_writes == [
        ("conv_1", "running"),
        ("conv_1", "idle"),
        ("conv_2", "idle"),
    ]


def test_every_background_report_is_written_with_its_runner_and_time(
    recording_store: _RecordingStore,
) -> None:
    """
    Each report reaches the store, which keeps the newest by its time.

    A replica cannot know what other replicas wrote since, so nothing is skipped
    as a repeat. The write's future says that it ran.
    """
    first = session_live_state.persist_background_work_running(
        "conv_1", True, runner_id="runner_a", reported_at=1
    )
    session_live_state.persist_background_work_running(
        "conv_1", True, runner_id="runner_a", reported_at=2
    )
    assert first is not None and first.result(timeout=10) is True
    _wait_until(lambda: len(recording_store.background_writes) >= 2)
    assert recording_store.background_writes == [
        ("conv_1", True, "runner_a", None, 1),
        ("conv_1", True, "runner_a", None, 2),
    ]


def test_clearing_a_departed_runners_flag_is_guarded(
    recording_store: _RecordingStore,
) -> None:
    """The clear names the departed runner, and the runner's next report is written again."""
    session_live_state.persist_background_work_running("conv_1", True)
    session_live_state.clear_background_work_running("conv_1", "runner_gone", unseen_since=1_000)
    session_live_state.persist_background_work_running("conv_1", True)
    _wait_until(lambda: len(recording_store.background_writes) >= 3)
    assert recording_store.background_writes == [
        ("conv_1", True),
        ("conv_1", False, "runner_gone", 1_000),
        ("conv_1", True),
    ]


def test_a_flag_write_queued_before_a_handoff_never_lands(
    recording_store: _RecordingStore,
) -> None:
    """A write still queued when the session moves away cannot overwrite the new owner's."""
    release = threading.Event()
    session_live_state.submit("hold", release.wait, 10)
    session_live_state.persist_background_work_running("conv_1", True)
    session_live_state.forget_live_status("conv_1")
    session_live_state.persist_background_work_running("conv_2", True)
    release.set()
    _wait_until(lambda: bool(recording_store.background_writes))
    assert recording_store.background_writes == [("conv_2", True)]


def test_a_report_begun_before_a_handoff_never_lands(
    recording_store: _RecordingStore,
) -> None:
    """A report that arrived before the session moved away is not written, even if queued after."""
    began = session_live_state.handoff_count("conv_1")
    session_live_state.forget_live_status("conv_1")
    skipped = session_live_state.persist_background_work_running("conv_1", True, handoffs=began)
    session_live_state.persist_background_work_running("conv_2", True)
    assert skipped is not None and skipped.result(timeout=10) is None
    _wait_until(lambda: bool(recording_store.background_writes))
    assert recording_store.background_writes == [("conv_2", True)]


def test_persist_blocked_on_dedupes_changes(recording_store: _RecordingStore) -> None:
    """Every status edge reports its reason; only a change reaches the store."""
    session_live_state.persist_blocked_on("conv_1", "permission prompt")
    session_live_state.persist_blocked_on("conv_1", "permission prompt")
    session_live_state.persist_blocked_on("conv_1", None)
    session_live_state.persist_blocked_on("conv_1", None)
    _wait_until(lambda: len(recording_store.blocked_writes) >= 2)
    assert recording_store.blocked_writes == [("conv_1", "permission prompt"), ("conv_1", None)]


def test_a_reason_queued_before_a_handoff_cannot_restore_a_cleared_prompt(
    recording_store: _RecordingStore,
) -> None:
    """The new owner clears the prompt; this replica's delayed write must not bring it back."""
    release = threading.Event()
    session_live_state.submit("hold", release.wait, 10)
    session_live_state.persist_blocked_on("conv_1", "permission prompt")
    session_live_state.forget_live_status("conv_1")
    session_live_state.persist_blocked_on("conv_2", "question")
    release.set()
    _wait_until(lambda: bool(recording_store.blocked_writes))
    assert recording_store.blocked_writes == [("conv_2", "question")]


def test_status_edges_set_and_clear_the_parked_reason() -> None:
    """A parked edge records its reason; the next edge without one clears it."""
    from omnigent.server.routes import sessions as sessions_module

    session_id = "conv_parked"
    try:
        sessions_module._publish_status(session_id, "running", blocked_on="x" * 200)
        assert sessions_module._blocked_on_for(session_id, None) == "x" * 128
        sessions_module._publish_status(session_id, "running")
        # This replica's edge wins over a stale row from another replica.
        assert sessions_module._blocked_on_for(session_id, "permission prompt") is None
    finally:
        sessions_module._session_blocked_on_cache.pop(session_id, None)
        sessions_module._session_status_cache.pop(session_id, None)
    assert sessions_module._blocked_on_for(session_id, "permission prompt") == "permission prompt"


def test_forget_live_status_drops_dedupe_state() -> None:
    """A replica handing off a session must not keep its stale dedupe state."""
    session_live_state._last_status["conv_1"] = "running"
    session_live_state._last_blocked_on["conv_1"] = "permission prompt"
    session_live_state.forget_live_status("conv_1")
    assert "conv_1" not in session_live_state._last_status
    assert "conv_1" not in session_live_state._last_blocked_on


def test_pending_count_hook_persists_publish_and_resolve(
    recording_store: _RecordingStore,
) -> None:
    """The elicitation index drives the persisted count through its hook.

    A publish bumps the count, a duplicate publish of the same id does
    not (same count → deduped), and a resolve writes the decrement —
    including the direct-``resolve`` path the approval dispatch uses,
    which never flows through ``record_publish``.
    """
    pending_elicitations.set_count_persist_hook(session_live_state.persist_pending_count)
    request = {"type": "response.elicitation_request", "elicitation_id": "elicit_1"}
    pending_elicitations.record_publish("conv_1", request)
    pending_elicitations.record_publish("conv_1", request)  # idempotent re-publish
    pending_elicitations.record_publish(
        "conv_1", {"type": "response.elicitation_request", "elicitation_id": "elicit_2"}
    )
    pending_elicitations.resolve("conv_1", "elicit_1")
    pending_elicitations.resolve("conv_1", "elicit_1")  # idempotent re-resolve
    pending_elicitations.resolve("conv_1", "elicit_2")
    _wait_until(lambda: len(recording_store.pending_writes) >= 4)
    assert recording_store.pending_writes == [
        ("conv_1", 1),
        ("conv_1", 2),
        ("conv_1", 1),
        ("conv_1", 0),
    ]


def test_runner_liveness_touch_and_clear_pass_through(
    recording_store: _RecordingStore,
) -> None:
    """Touches and clears reach the store; empty touch is a no-op."""
    session_live_state.touch_runner_liveness(["runner_a", "runner_b"])
    session_live_state.touch_runner_liveness([])
    session_live_state.clear_runner_liveness("runner_a")
    _wait_until(lambda: recording_store.touches and recording_store.clears)
    assert recording_store.touches == [["runner_a", "runner_b"]]
    stamp = session_live_state.last_liveness_stamp("runner_a")
    assert recording_store.clears == [("runner_a", stamp)]


def test_touch_records_stamp_and_clear_forwards_it_as_not_after(
    recording_store: _RecordingStore,
) -> None:
    """``touch`` remembers its own stamp; ``clear`` forwards it as ``not_after``.

    The disconnect handler relies on this stamp surviving the clear itself
    (never erased here — only :func:`session_live_state.configure` resets
    it), so a later cross-replica check still has something to compare
    against.
    """
    assert session_live_state.last_liveness_stamp("runner_c") is None

    before = int(time.time())
    session_live_state.touch_runner_liveness(["runner_c"])
    stamp = session_live_state.last_liveness_stamp("runner_c")
    assert stamp is not None and stamp >= before

    session_live_state.clear_runner_liveness("runner_c")
    _wait_until(lambda: bool(recording_store.clears))
    assert recording_store.clears == [("runner_c", stamp)]

    # The clear call itself never erases the process's own record of it.
    assert session_live_state.last_liveness_stamp("runner_c") == stamp


def test_unconfigured_module_is_a_no_op() -> None:
    """Without a wired store (runner process, most tests) nothing runs.

    No store means no executor work is enqueued; the calls simply return.
    """
    session_live_state.configure(None)
    session_live_state.persist_live_status("conv_1", "running")
    session_live_state.persist_pending_count("conv_1", 1)
    session_live_state.touch_runner_liveness(["runner_a"])
    session_live_state.clear_runner_liveness("runner_a")


def test_write_runs_in_callers_workspace_scope(recording_store: _RecordingStore) -> None:
    """The store write inherits the caller's ``workspace_scope``.

    The store filters every query on ``current_workspace_id()`` — a
    ``ContextVar`` the multi-tenant middleware binds per request. The
    write runs on a background ``ThreadPoolExecutor``; a bare
    ``submit`` would run it at the default workspace (0), so on a
    multi-tenant replica every ``WHERE workspace_id == …`` would match
    no rows and the whole mirror would silently no-op. Copying the
    caller's context (as ``_submit`` does) is what carries the bound
    workspace to the worker thread. This test binds a non-default
    workspace and asserts the write thread observes it.
    """
    from omnigent.db.db_models import current_workspace_id, workspace_scope

    seen: list[int] = []

    def _record_ws(conversation_id: str, status: str) -> None:
        del conversation_id, status
        seen.append(current_workspace_id())

    recording_store.set_session_live_status = _record_ws  # type: ignore[method-assign]

    with workspace_scope(4242):
        session_live_state.persist_live_status("conv_1", "running")
    # The scope is left BEFORE the worker runs (the ``with`` block is
    # already closed here), so a passing assertion proves the value was
    # captured at submit time rather than read live off the worker thread
    # (which is always at the default workspace).
    _wait_until(lambda: bool(seen))

    assert seen == [4242], "write thread did not observe the caller's bound workspace"


def test_dropped_write_evicts_dedupe_entry_for_retry() -> None:
    """A dropped best-effort write must not pin a stale dedupe entry.

    ``persist_live_status`` records the value in its dedupe cache before
    enqueueing the (best-effort) write. If that write is dropped, a later
    *identical* publish would be deduped away and the row would stay stale
    until a different value arrived. On failure the entry is evicted, so
    the next identical publish re-attempts the write.
    """
    calls: list[tuple[str, str]] = []

    class _FlakyStore(_RecordingStore):
        def set_session_live_status(self, conversation_id: str, status: str) -> None:
            calls.append((conversation_id, status))
            if len(calls) == 1:
                raise RuntimeError("boom")  # first attempt fails
            super().set_session_live_status(conversation_id, status)

    store = _FlakyStore()
    session_live_state.configure(store)  # type: ignore[arg-type]
    try:
        session_live_state.persist_live_status("conv_1", "running")
        # Wait for the EVICTION, not just the first call: the worker
        # appends to ``calls`` and only then runs the failure callback that
        # drops the dedupe entry. Gating the retry on "conv_1" leaving the
        # dedupe map (the exact contract under test) removes the race where
        # the second publish races the eviction and gets deduped away.
        _wait_until(lambda: "conv_1" not in session_live_state._last_status)
        assert "conv_1" not in session_live_state._last_status, "dropped write did not evict"

        # Same value again: without the eviction above this would dedupe to
        # a no-op; because the entry was cleared, the retry re-attempts.
        session_live_state.persist_live_status("conv_1", "running")
        _wait_until(lambda: bool(store.status_writes))
    finally:
        session_live_state.configure(None)

    assert calls == [("conv_1", "running"), ("conv_1", "running")]
    assert store.status_writes == [("conv_1", "running")], "retry never landed"


def test_unencodable_status_is_dropped_before_enqueue(
    recording_store: _RecordingStore,
) -> None:
    """A status the codec can't encode never reaches the store.

    ``SessionStatusEvent.status`` permits ``"launching"``, which the
    live-status codec (``SESSION_LIVE_STATUS``) can't encode, and the SSE
    relay forwards raw event statuses. Enqueueing it would make the store
    write raise, whose best-effort failure hook clears the dedupe entry, so
    every republish would re-attempt and re-warn. ``persist_live_status``
    instead drops an unknown status before the enqueue: no store write, and
    a later *known* status for the same session still persists normally.
    """
    session_live_state.persist_live_status("conv_1", "launching")  # unknown
    session_live_state.persist_live_status("conv_1", "launching")  # repeat, deduped
    session_live_state.persist_live_status("conv_1", "running")  # known → persists
    _wait_until(lambda: bool(recording_store.status_writes))

    # Only the encodable status was ever enqueued; "launching" never was.
    assert recording_store.status_writes == [("conv_1", "running")]


class _FakeScheduledTaskStore:
    """Scheduled-task-store stand-in recording the hook's lookup + update."""

    def __init__(self, running_by_conv: dict[str, str] | None = None) -> None:
        # conversation_id -> run_id for conversations that have a running run.
        self._running_by_conv = running_by_conv or {}
        self.lookup_calls: list[str] = []
        self.update_calls: list[tuple[str, str, str | None, str | None]] = []
        self.lookup_workspaces: list[int] = []

    def get_running_run_by_conversation(self, conversation_id: str):  # type: ignore[no-untyped-def]
        from omnigent.db.db_models import current_workspace_id

        self.lookup_calls.append(conversation_id)
        self.lookup_workspaces.append(current_workspace_id())
        run_id = self._running_by_conv.get(conversation_id)
        if run_id is None:
            return None
        # Minimal object carrying only the ``id`` the hook reads.
        return type("_Run", (), {"id": run_id})()

    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        finished_at: int,
        error: str | None = None,
        error_code: str | None = None,
    ):  # type: ignore[no-untyped-def]
        self.update_calls.append((run_id, status, error, error_code))
        return type("_Run", (), {"id": run_id, "status": status})()


def test_scheduled_run_completion_idle_transitions_to_succeeded() -> None:
    """A terminal ``idle`` edge flips the conversation's running run to succeeded."""
    sched = _FakeScheduledTaskStore({"conv_1": "run_1"})
    session_live_state.configure(_RecordingStore(), sched)  # type: ignore[arg-type]
    try:
        session_live_state.persist_scheduled_run_completion("conv_1", "succeeded")
        _wait_until(lambda: bool(sched.update_calls))
    finally:
        session_live_state.configure(None)
    assert sched.lookup_calls == ["conv_1"]
    assert len(sched.update_calls) == 1
    run_id, status, error, error_code = sched.update_calls[0]
    assert (run_id, status) == ("run_1", "succeeded")
    assert error is None and error_code is None


def test_scheduled_run_completion_failed_carries_error_code() -> None:
    """A terminal ``failed`` edge flips the run to failed with the error detail."""
    sched = _FakeScheduledTaskStore({"conv_1": "run_1"})
    session_live_state.configure(_RecordingStore(), sched)  # type: ignore[arg-type]
    try:
        session_live_state.persist_scheduled_run_completion(
            "conv_1", "failed", error_code="runner_disconnected", error="dropped"
        )
        _wait_until(lambda: bool(sched.update_calls))
    finally:
        session_live_state.configure(None)
    assert sched.update_calls == [("run_1", "failed", "dropped", "runner_disconnected")]


def test_scheduled_run_completion_noop_for_non_scheduled_conversation() -> None:
    """An interactive conversation has no running run → lookup only, no update.

    This is the common case: the hook fires on every terminal edge, and the
    cheap reverse lookup returning ``None`` keeps it a no-op for the vast
    majority of (non-scheduled) conversations.
    """
    sched = _FakeScheduledTaskStore({})  # no running runs
    session_live_state.configure(_RecordingStore(), sched)  # type: ignore[arg-type]
    try:
        session_live_state.persist_scheduled_run_completion("conv_x", "succeeded")
        _wait_until(lambda: bool(sched.lookup_calls))
    finally:
        session_live_state.configure(None)
    assert sched.lookup_calls == ["conv_x"]
    assert sched.update_calls == []


def test_scheduled_run_completion_noop_without_scheduled_store() -> None:
    """With only a conversation store wired the hook is a pure no-op.

    ``configure(store)`` (no scheduled-task store) must not enqueue any work —
    the runner process and most tests never wire one.
    """
    session_live_state.configure(_RecordingStore())  # type: ignore[arg-type]
    try:
        # No scheduled store => returns before touching the executor.
        session_live_state.persist_scheduled_run_completion("conv_1", "succeeded")
    finally:
        session_live_state.configure(None)


def test_scheduled_run_completion_runs_in_callers_workspace_scope() -> None:
    """The lookup + update inherit the caller's ``workspace_scope``.

    Same contract as the live_status mirror: the store filters on
    ``current_workspace_id()``, so the hook's reverse lookup must resolve to
    the fired run's workspace. Bind a non-default workspace, leave the scope
    before the worker runs, and assert the write thread still observed it.
    """
    from omnigent.db.db_models import workspace_scope

    sched = _FakeScheduledTaskStore({"conv_1": "run_1"})
    session_live_state.configure(_RecordingStore(), sched)  # type: ignore[arg-type]
    try:
        with workspace_scope(4242):
            session_live_state.persist_scheduled_run_completion("conv_1", "succeeded")
        _wait_until(lambda: bool(sched.lookup_workspaces))
    finally:
        session_live_state.configure(None)
    assert sched.lookup_workspaces == [4242]


@pytest.mark.asyncio
async def test_liveness_pass_zeroes_pending_count_for_offline_runner() -> None:
    """A stale persisted pending count can't light a phantom inbox badge.

    Nothing decrements the persisted ``pending_elicitation_count`` when a
    runner/host/replica crashes with prompts parked, so the row can outlive
    the prompts it counts. The liveness pass (shared by ``GET /v1/sessions``
    and the ``/v1/sessions/updates`` watched-items fetch) zeroes the count on
    rows whose runner is offline — dead runner means dead prompts — while an
    online runner's count passes through untouched.
    """
    from omnigent.server.routes.sessions import SessionLiveness, _apply_liveness_to_items
    from omnigent.server.schemas import SessionListItem

    def _item(session_id: str) -> SessionListItem:
        return SessionListItem(
            id=session_id,
            agent_id="ag_1",
            status="idle",
            created_at=1,
            updated_at=1,
            pending_elicitations_count=3,
            background_work_running=True,
            blocked_on="permission prompt",
        )

    items = [_item("conv_dead"), _item("conv_live")]
    liveness = {
        "conv_dead": SessionLiveness(runner_online=False, host_online=True),
        "conv_live": SessionLiveness(runner_online=True, host_online=True),
    }

    await _apply_liveness_to_items(items, lambda ids: {i: liveness[i] for i in ids})

    # A dead runner's background shells and terminal prompts died with it too.
    assert [
        (i.runner_online, i.pending_elicitations_count, i.background_work_running, i.blocked_on)
        for i in items
    ] == [
        (False, 0, False, None),
        (True, 3, True, "permission prompt"),
    ]


# CORAL(S1): in-process status-edge observers, their fields and the four origin sites.
@pytest.fixture()
def status_edges() -> Iterator[list[Any]]:
    """Record every status edge published while the test runs."""
    edges: list[Any] = []
    unregister = session_live_state.register_status_edge_observer("test-recorder", edges.append)
    yield edges
    unregister()


def _without_clock(edge: Any) -> Any:
    return dataclasses.replace(edge, observed_at_ms=0)


def test_status_edge_observers_replace_by_name_unregister_by_identity_and_are_isolated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[tuple[str, str]] = []
    # A fresh name: a failure is logged once per observer name for the whole process.
    failing_name = f"test-raising-{uuid.uuid4().hex}"

    def failing(_edge: Any) -> None:
        raise RuntimeError("observer bug")

    with caplog.at_level(logging.DEBUG, logger=session_live_state.__name__):
        # Registered first, so the observers after it prove a failure stops no one.
        remove_failing = session_live_state.register_status_edge_observer(failing_name, failing)
        stale = session_live_state.register_status_edge_observer(
            "test-a", lambda edge: seen.append(("first", edge.session_id))
        )
        current = session_live_state.register_status_edge_observer(
            "test-a", lambda edge: seen.append(("second", edge.session_id))
        )
        try:
            session_live_state.configure(None)
            for session_id in ("conv_a", "conv_a2"):
                session_live_state.notify_status_edge(
                    session_live_state.SessionStatusEdge(session_id, "idle", "running")
                )
            assert seen == [("second", "conv_a"), ("second", "conv_a2")]
            stale()
            session_live_state.notify_status_edge(
                session_live_state.SessionStatusEdge("conv_b", "running", None)
            )
            assert seen[-1] == ("second", "conv_b")
            current()
            current()
            session_live_state.notify_status_edge(
                session_live_state.SessionStatusEdge("conv_c", "idle", None)
            )
            assert seen[-1] == ("second", "conv_b")
        finally:
            current()
            remove_failing()

    replaced = [r for r in caplog.records if "'test-a' replaced" in r.getMessage()]
    assert [r.levelno for r in replaced] == [logging.WARNING]
    failures = [r for r in caplog.records if failing_name in r.getMessage()]
    # One traceback for the first failure; each of the four failures also at debug.
    assert [(r.levelno, r.exc_info is not None) for r in failures] == [
        (logging.WARNING, True),
        *[(logging.DEBUG, False)] * 4,
    ]


def test_status_edge_bounds_runner_supplied_values_without_raising() -> None:
    edge = session_live_state.SessionStatusEdge(
        "conv_bounds",
        "failed",
        "running",
        turn_outcome="cancelled",
        turn_response_id="r" * 129,
        response_id="r" * 128,
        error_code="c" * 200,
        error_message="m" * 5000,
        blocked_on="b" * 200,
    )
    assert (edge.turn_response_id, edge.response_id) == (None, "r" * 128)
    assert (edge.error_code, edge.blocked_on) == ("c" * 128, "b" * 128)
    assert edge.error_message == "m" * 4500
    odd = session_live_state.SessionStatusEdge(
        "conv_bounds",
        "idle",
        None,
        turn_outcome=["failed"],  # type: ignore[arg-type]
        response_id="",
        error_message=7,  # type: ignore[arg-type]
    )
    assert (odd.turn_outcome, odd.response_id, odd.error_message) == (None, None, None)


def test_status_edge_observers_may_change_the_registry_or_raise_mid_notify() -> None:
    """Observers run unlocked on a snapshot; one that raised still gets the next edge."""
    first, second = "conv_reentrant_a", "conv_reentrant_b"
    seen: list[tuple[str, str]] = []
    unregister_late: list[Any] = []

    def late(edge: Any) -> None:
        if edge.session_id in (first, second):
            seen.append(("late", edge.session_id))

    def leaving(edge: Any) -> None:
        if edge.session_id in (first, second):
            seen.append(("leaving", edge.session_id))
            unregister_leaving()
            unregister_late.append(
                session_live_state.register_status_edge_observer("test-late", late)
            )

    def flaky(edge: Any) -> None:
        if edge.session_id == first:
            raise RuntimeError("observer bug on one edge")
        if edge.session_id == second:
            seen.append(("flaky", second))

    # The raising observer runs first, so "leaving" proves the observers after it still run.
    unregister_flaky = session_live_state.register_status_edge_observer("test-flaky", flaky)
    unregister_leaving = session_live_state.register_status_edge_observer("test-leaving", leaving)
    try:
        for session_id in (first, second):
            session_live_state.notify_status_edge(
                session_live_state.SessionStatusEdge(session_id, "idle", None)
            )
    finally:
        unregister_leaving()
        unregister_flaky()
        for unregister in unregister_late:
            unregister()
    assert seen == [("leaving", first), ("flaky", second), ("late", second)]


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"turn_outcome": "cancelled", "turn_response_id": "resp_1"}, ("cancelled", "resp_1")),
        ({"turn_outcome": "failed", "turn_response_id": "r" * 128}, ("failed", "r" * 128)),
        ({"turn_outcome": "completed", "turn_response_id": 7}, ("completed", None)),
        ({"turn_outcome": "succeeded", "turn_response_id": ""}, (None, None)),
        ({"turn_outcome": ["failed"], "turn_response_id": "r" * 129}, (None, None)),
        # CORAL(S1): a response id travels only with a known outcome.
        ({"turn_outcome": "done", "turn_response_id": "resp_g"}, (None, None)),
        ({"turn_response_id": "resp_g"}, (None, None)),
        ({}, (None, None)),
    ],
)
def test_turn_fields_keep_only_known_outcomes_and_bounded_ids(
    event: dict[str, object], expected: tuple[str | None, str | None]
) -> None:
    assert session_live_state.turn_fields(event) == expected


def test_publish_status_notifies_one_edge_per_publish_after_the_stream(
    monkeypatch: pytest.MonkeyPatch, status_edges: list[Any]
) -> None:
    """Every publish past the sticky return reaches observers once, after SSE and caches."""
    from omnigent.server.routes._sessions import helpers

    session_id = "conv_edge_fields"
    calls: list[tuple[str, object]] = []
    publish = session_stream.publish

    def record_publish(key: str, payload: dict[str, Any]) -> None:
        calls.append(("publish", dict(payload)))
        publish(key, payload)

    def record_edge(edge: Any) -> None:
        cached = (
            helpers._session_status_cache.get(edge.session_id),
            helpers._session_active_response_cache.get(edge.session_id),
        )
        calls.append(("edge", cached))

    monkeypatch.setattr(session_stream, "publish", record_publish)
    unregister = session_live_state.register_status_edge_observer("test-order", record_edge)
    before_ms = int(time.time() * 1000)
    try:
        helpers._publish_status(
            session_id,
            "running",
            response_id="resp_1",
            background_task_count=2,
            blocked_on="permission prompt",
            failure_origin="dropped_on_non_failed_edges",
            origin="relay_turn_end",
        )
        helpers._publish_status(
            session_id,
            "failed",
            ErrorDetail(code="runner_error", message="boom"),
            failure_origin="runner_rejected_event",
            scheduled_run_outcome="failed",
            origin="runner_disconnect",
            turn_outcome="failed",
            turn_response_id="resp_1",
        )
        helpers._publish_status(session_id, "idle", turn_outcome="cancelled")  # sticky
        helpers._publish_status(
            session_id, "idle", persist_live_status=False, turn_completed=True, turn_outcome="odd"
        )
    finally:
        unregister()
        helpers._session_status_cache.pop(session_id, None)
        helpers._session_active_response_cache.pop(session_id, None)
        helpers._session_blocked_on_cache.pop(session_id, None)
        session_stream.close(session_id)

    edges = [edge for edge in status_edges if edge.session_id == session_id]
    assert all(before_ms <= edge.observed_at_ms <= int(time.time() * 1000) for edge in edges)
    edge_type = session_live_state.SessionStatusEdge
    assert [_without_clock(edge) for edge in edges] == [
        edge_type(
            session_id,
            "running",
            None,
            origin="relay_turn_end",
            response_id="resp_1",
            background_task_count=2,
            blocked_on="permission prompt",
            observed_at_ms=0,
        ),
        edge_type(
            session_id,
            "failed",
            "running",
            origin="runner_disconnect",
            turn_outcome="failed",
            turn_response_id="resp_1",
            error_code="runner_error",
            error_message="boom",
            failure_origin="runner_rejected_event",
            scheduled_run_outcome="failed",
            observed_at_ms=0,
        ),
        edge_type(
            session_id,
            "idle",
            "failed",
            turn_completed=True,
            persist_live_status=False,
            observed_at_ms=0,
        ),
    ]
    # Each edge follows its own stream publish, with every cache already written.
    assert [kind for kind, _ in calls] == ["publish", "edge", "publish", "edge", "publish", "edge"]
    assert [cached for kind, cached in calls if kind == "edge"] == [
        ("running", "resp_1"),
        ("failed", None),
        ("idle", None),
    ]
    payloads = [payload for kind, payload in calls if kind == "publish"]
    assert not any(
        key in payload
        for payload in payloads
        for key in ("origin", "turn_outcome", "turn_response_id")
    )


async def test_status_edge_observer_runs_on_the_orphan_reconcile_worker_thread(
    status_edges: list[Any],
) -> None:
    from omnigent.db.db_models import workspace_scope
    from omnigent.server.routes._sessions import helpers

    session_id = "conv_orphan_edge"
    threads: list[int] = []
    unregister = session_live_state.register_status_edge_observer(
        "test-thread", lambda _edge: threads.append(threading.get_ident())
    )
    store = SimpleNamespace(settle_orphaned_live_status=lambda _session_id, _stale: True)
    try:
        with workspace_scope(4242):
            assert await asyncio.to_thread(
                helpers.reconcile_orphaned_running_status, session_id, store, 0
            )
    finally:
        unregister()
        with workspace_scope(4242):
            helpers._session_status_cache.pop(session_id, None)
        session_stream.close(session_id)

    [edge] = [edge for edge in status_edges if edge.session_id == session_id]
    assert (edge.status, edge.scheduled_run_outcome, edge.persist_live_status) == (
        "idle",
        "failed",
        False,
    )
    assert edge.workspace_id == 4242
    assert threads and threads[0] != threading.get_ident()


_SITE_SESSION = "5e55a7e0c0de4d1e8a0b1c2d3e4f5a6b"


async def _archive_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    from omnigent.server.routes import sessions
    from omnigent.server.routes._sessions import orchestration

    conv = SimpleNamespace(
        id=_SITE_SESSION,
        archived=True,
        host_id="host-site",
        runner_id="runner-site",
        parent_conversation_id=None,
    )
    store = SimpleNamespace(
        get_conversation=lambda _session_id: conv,
        list_runner_session_statuses=lambda _runner_id, **_page: [(conv.id, "running")],
        settle_intentionally_stopped_session=lambda _session_id, _runner_id: True,
    )
    monkeypatch.setattr(sessions, "_best_effort_stop", AsyncMock())
    monkeypatch.setattr(sessions, "_stop_session_host_runner", AsyncMock(return_value=True))
    sessions._session_status_cache[_SITE_SESSION] = "running"
    sessions._session_active_response_cache[_SITE_SESSION] = "resp_site"
    await orchestration._archive_stop(_SITE_SESSION, store, None, None)  # type: ignore[arg-type]


async def _runner_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    from omnigent.server.routes import sessions
    from omnigent.server.routes._sessions import orchestration

    monkeypatch.setattr(orchestration, "RUNNER_DISCONNECT_GRACE_S", 0.0)
    dropped = asyncio.Event()
    dropped.set()
    sessions._session_status_cache[_SITE_SESSION] = "running"
    sessions._session_active_response_cache[_SITE_SESSION] = "resp_site"
    await sessions._relay_runner_stream(
        _SITE_SESSION,
        _TunnelCloseRunnerClient(dropped),  # type: ignore[arg-type]
        _RecordingLabelStore(),  # type: ignore[arg-type]
    )


async def _relay_turn_end(monkeypatch: pytest.MonkeyPatch) -> None:
    from omnigent.server.routes import sessions

    del monkeypatch
    store = _RecordingLabelStore()
    store.set_labels(
        _SITE_SESSION,
        {
            sessions._LAST_TASK_ERROR_CODE_LABEL_KEY: "runner_disconnected",
            sessions._LAST_TASK_ERROR_MESSAGE_LABEL_KEY: "Runner disconnected unexpectedly.",
        },
    )
    sessions._session_status_cache[_SITE_SESSION] = "failed"
    released = asyncio.Event()
    released.set()
    turn_end = {
        "type": "session.status",
        "status": "idle",
        "turn_outcome": "completed",
        "turn_response_id": "resp_site",
    }
    await sessions._relay_runner_stream(
        _SITE_SESSION,
        _ScriptedRunnerClient(released, [turn_end]),  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
    )


async def _status_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    from omnigent.server.routes._sessions import orchestration

    del monkeypatch
    reply = SimpleNamespace(status_code=200, json=lambda: {"status": "running"})
    runner_client = SimpleNamespace(get=AsyncMock(return_value=reply))
    probed = await orchestration._probe_runner_live_status(
        runner_client,  # type: ignore[arg-type]
        _SITE_SESSION,
    )
    assert probed == "running"


_SITES = {
    "archive_idle": _archive_idle,
    "runner_disconnect": _runner_disconnect,
    "relay_turn_end": _relay_turn_end,
    "status_probe": _status_probe,
}


@pytest.mark.parametrize(
    ("site", "expected"),
    [
        (
            "archive_idle",
            {
                "status": "idle",
                "previous_status": "running",
                "turn_outcome": "cancelled",
                "turn_response_id": "resp_site",
                "persist_live_status": False,
            },
        ),
        (
            "runner_disconnect",
            {
                "status": "failed",
                "previous_status": "running",
                "turn_outcome": "failed",
                "turn_response_id": "resp_site",
                "error_code": "runner_disconnected",
                "error_message": "Runner disconnected unexpectedly.",
                "failure_origin": "runner_disconnected_mid_turn",
            },
        ),
        (
            "relay_turn_end",
            {
                "status": "idle",
                "previous_status": "failed",
                "turn_outcome": "completed",
                "turn_response_id": "resp_site",
            },
        ),
        ("status_probe", {"status": "running", "previous_status": None}),
    ],
)
async def test_observer_sees_every_edge_with_origin_at_the_four_sites(
    monkeypatch: pytest.MonkeyPatch,
    status_edges: list[Any],
    site: str,
    expected: dict[str, Any],
) -> None:
    from omnigent.server.routes import sessions

    try:
        await _SITES[site](monkeypatch)
    finally:
        for cache in (
            sessions._session_status_cache,
            sessions._session_active_response_cache,
            sessions._intentional_stop_sessions,
            sessions._runner_status_probe_backoff,
        ):
            cache.pop(_SITE_SESSION, None)
        session_live_state.forget_turn_outcomes(_SITE_SESSION)
        session_stream.close(_SITE_SESSION)

    edges = [edge for edge in status_edges if edge.session_id == _SITE_SESSION]
    assert [_without_clock(edge) for edge in edges] == [
        session_live_state.SessionStatusEdge(
            session_id=_SITE_SESSION, origin=site, observed_at_ms=0, **expected
        )
    ]


# CORAL(S1): reported turn outcomes are kept per (workspace, session), bounded.
def test_reported_turn_outcomes_are_bounded_and_scoped_to_their_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omnigent.db.db_models import workspace_scope

    edge = session_live_state.SessionStatusEdge
    reported = session_live_state.turn_outcome_reported
    session_id = f"conv_reported_{uuid.uuid4().hex}"
    evicted = [f"{session_id}_{index}" for index in range(3)]
    try:
        # Only an edge with both an outcome and a response id counts.
        session_live_state.notify_status_edge(
            edge(session_id, "idle", None, turn_response_id="resp_no_outcome")
        )
        session_live_state.notify_status_edge(
            edge(session_id, "failed", None, turn_outcome="failed")
        )
        for index in range(9):
            session_live_state.notify_status_edge(
                edge(
                    session_id,
                    "idle",
                    None,
                    turn_outcome="completed",
                    turn_response_id=f"r{index}",
                )
            )
        assert not reported(session_id, "resp_no_outcome")
        assert not reported(session_id, None)
        # A session keeps its last eight reported responses.
        assert [reported(session_id, f"r{index}") for index in range(9)] == [False] + [True] * 8
        with workspace_scope(4242):
            assert not reported(session_id, "r8")
        session_live_state.forget_turn_outcomes(session_id)
        assert not reported(session_id, "r8")

        # Past the session bound, the least recently reported session goes first.
        monkeypatch.setattr(session_live_state, "_REPORTED_TURN_SESSIONS_MAX", 2)
        for evicted_id in evicted:
            session_live_state.notify_status_edge(
                edge(evicted_id, "idle", None, turn_outcome="cancelled", turn_response_id="r")
            )
        assert [reported(evicted_id, "r") for evicted_id in evicted] == [False, True, True]
    finally:
        for forgotten in (session_id, *evicted):
            session_live_state.forget_turn_outcomes(forgotten)


async def test_deleting_a_session_forgets_its_reported_turn_outcomes(
    client: Any, db_uri: str
) -> None:
    from omnigent.stores.conversation_store.sqlalchemy_store import (
        SqlAlchemyConversationStore,
    )
    from tests.server.helpers import create_session_for_agent, create_test_agent

    agent = await create_test_agent(client)
    session_id = await create_session_for_agent(client, agent["id"])
    # Its sub-agent descendants are deleted with it.
    child = SqlAlchemyConversationStore(db_uri).create_conversation(
        kind="sub_agent", title="worker:a", parent_conversation_id=session_id
    )
    deleted_ids = (session_id, child.id)
    for deleted_id in deleted_ids:
        session_live_state.notify_status_edge(
            session_live_state.SessionStatusEdge(
                deleted_id, "idle", None, turn_outcome="completed", turn_response_id="resp_deleted"
            )
        )
        assert session_live_state.turn_outcome_reported(deleted_id, "resp_deleted")

    response = await client.delete(f"/v1/sessions/{session_id}")

    assert response.status_code < 300, response.text
    for deleted_id in deleted_ids:
        assert not session_live_state.turn_outcome_reported(deleted_id, "resp_deleted")
