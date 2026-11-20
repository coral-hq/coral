"""Status edges become turn facts. This test does not boot a server."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from coral.bridge.bound_sessions import BoundSession, BoundSessions
from coral.bridge.config import MAX_PAYLOAD_BYTES
from coral.bridge.keys import ORCHESTRATOR_SLOT_ID, store_slot_id
from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole, WorkKind
from coral.engine.facts import TurnSnapshot
from coral.engine.turn_end import evaluate
from coral.omni.protocols import TranscriptItem, TurnTranscript, turn_transcript_of
from coral.omni.server.observers import observe_status_edge
from coral.omni.server.turn_facts import BoundSessionRefresher, TurnFactRecorder
from coral.signals.nudge import decide
from coral.signals.turn_facts import EdgeFacts
from coral.stores.fakes import FakeQueueStore
from coral.stores.protocols import WorkItem
from coral.stores.session_bindings import SessionBinding, SessionBindingDraft, binding_from_draft
from omnigent.server.session_live_state import SessionStatusEdge

ENGINE_ID = "e" * 32


def _completed(**overrides: object) -> TurnSnapshot:
    payload: dict[str, object] = {
        "live_status": "idle",
        "engine_stable_id_present": True,
        "newest_substantive_item_is_assistant": True,
        "turn_outcome": "completed",
        "saw_response_completed": True,
        "background_tasks": 0,
        "pending_elicitation_count": 0,
        "engine_pending_input": False,
        "origin": "engine",
        "engine_started": True,
    }
    payload.update(overrides)
    return TurnSnapshot(**payload)


def test_unbound_edge_returns_none() -> None:
    assert observe_status_edge({}) is None
    assert observe_status_edge({"session_id": ""}) is None
    assert observe_status_edge({"session_id": None}) is None
    assert observe_status_edge({"status": "idle"}) is None


def test_idle_without_turn_outcome_is_not_completed() -> None:
    edge = {
        "session_id": "sess-1",
        "slot_id": "work||:0",
        "status": "idle",
        "origin": "engine",
        "previous_status": {"raw": True},
        "observed_at_ms": "not-a-timestamp",
    }
    fact = observe_status_edge(edge)
    assert fact is not None
    assert fact.live_status == "idle"
    assert fact.turn_outcome is None
    assert fact.slot_id == "work||:0"
    assert fact.session_id == "sess-1"
    filled = fact.model_copy(
        update={
            "engine_stable_id_present": True,
            "newest_substantive_item_is_assistant": True,
            "saw_response_completed": False,
            "background_tasks": 0,
            "pending_elicitation_count": 0,
            "engine_pending_input": False,
            "engine_started": True,
        }
    )
    assert evaluate(filled) != "completed"
    assert decide(filled, "working", fact_key="turn:sess-1") is False


def test_observer_copies_present_fields_and_keeps_no_memory() -> None:
    edge = {
        "session_id": "sess-1",
        "status": "idle",
        "turn_outcome": "failed",
        "failure_origin": "runner_disconnected",
        "origin": "nightly-archive",
        "previous_status": "working",
        "observed_at_ms": 1_700_000_000_000,
        "slot_id": "",
    }
    first = observe_status_edge(edge)
    second = observe_status_edge(edge)
    assert first == second
    assert first is not second
    assert first is not None
    assert first.live_status == "idle"
    assert first.turn_outcome == "failed"
    assert first.failure_origin == "runner_disconnected"
    assert first.origin == "archive"
    assert first.slot_id == ""
    assert observe_status_edge({"session_id": "sess-1"}).origin is None
    assert observe_status_edge({"session_id": "sess-1", "origin": "engine"}).origin == "engine"
    assert observe_status_edge({"session_id": "sess-1", "origin": "user"}).origin == "user"
    assert observe_status_edge({"session_id": "sess-1", "slot_id": 3}).slot_id == ""


def test_the_fact_names_the_response_its_outcome_reports_on() -> None:
    # A continuation's running edge opens resp_2 and reports resp_1's outcome.
    carried = observe_status_edge(
        {
            "session_id": "sess-1",
            "status": "running",
            "response_id": "resp_2",
            "turn_outcome": "cancelled",
            "turn_response_id": "resp_1",
        }
    )
    assert carried is not None
    assert (carried.turn_outcome, carried.response_id) == ("cancelled", "resp_1")
    opened = observe_status_edge({"session_id": "sess-1", "status": "running", "response_id": "r"})
    assert opened is not None and opened.response_id == "r"
    for missing in ({}, {"response_id": ""}, {"turn_response_id": "", "response_id": 7}):
        fact = observe_status_edge({"session_id": "sess-1", "status": "idle", **missing})
        assert fact is not None and fact.response_id is None


def test_user_and_archive_origins_do_not_nudge() -> None:
    key = "turn:sess-1"
    assert decide(_completed(origin="user"), "working", fact_key=key) is False
    assert decide(_completed(origin="archive"), "working", fact_key=key) is False
    assert decide(_completed(), "working", fact_key=key) is True
    assert decide(_completed(), "working", fact_key=key) is True
    assert decide(_completed(), "working", fact_key=key, seen=frozenset({key})) is False
    assert decide(_completed(), "closing", fact_key=key) is False
    assert decide(_completed(), "closed", fact_key=key) is False
    assert decide(_completed(), "working", fact_key=key, taken_over=True) is False
    assert decide(_completed(turn_outcome="cancelled"), "working", fact_key=key) is False
    assert decide(_completed(engine_started=False), "working", fact_key=key) is False


def test_signal_modules_import_before_the_engine_package() -> None:
    modules = ("coral.signals.facts", "coral.signals.nudge", "coral.signals.outcomes")
    for module in modules:
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_signal_packages_do_not_import_omnigent() -> None:
    code = (
        "import sys\n"
        "import coral.engine\n"
        "import coral.signals\n"
        "import coral.omni.server.observers\n"
        "bad = sorted(\n"
        "    name for name in sys.modules\n"
        "    if name == 'omnigent' or name.startswith('omnigent.')\n"
        ")\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


# ── the transcript walk ─────────────────────────────────────────────────────


def _engine(item_id: str = ENGINE_ID, *, pending: bool = False) -> TranscriptItem:
    return TranscriptItem(item_id, engine=True, client_input=False, pending=pending)


def _client(item_id: str = "typed", *, pending: bool = False) -> TranscriptItem:
    return TranscriptItem(item_id, engine=False, client_input=True, pending=pending)


def _runner(item_id: str, *, assistant: bool = False) -> TranscriptItem:
    return TranscriptItem(
        item_id, engine=False, client_input=False, runner=True, assistant=assistant
    )


BOOKKEEPING = TranscriptItem("resource", engine=False, client_input=False, bookkeeping=True)
# A server item that is no runner output, such as the interrupt marker.
MARKER = TranscriptItem("marker", engine=False, client_input=False)


@pytest.mark.parametrize(
    ("newest_first", "expected"),
    [
        (
            [BOOKKEEPING, _runner("reply", assistant=True), _runner("call"), _engine()],
            TurnTranscript("engine", ENGINE_ID, True, True, False),
        ),
        (
            [_runner("output"), _runner("reply", assistant=True), _engine()],
            TurnTranscript("engine", ENGINE_ID, False, True, False),
        ),
        ([MARKER, _engine()], TurnTranscript("engine", ENGINE_ID, False, False, False)),
        ([_engine()], TurnTranscript("engine", ENGINE_ID, False, False, False)),
        (
            [_runner("reply", assistant=True), _client(), _engine()],
            TurnTranscript("user", ENGINE_ID, True, True, False),
        ),
        (
            [_engine("b" * 32, pending=True), _runner("reply", assistant=True), _engine()],
            TurnTranscript("engine", "b" * 32, False, False, True),
        ),
        (
            [_client(pending=True), _runner("reply", assistant=True), _engine()],
            TurnTranscript("user", ENGINE_ID, False, True, False),
        ),
        (
            [_runner("reply", assistant=True), _client()],
            TurnTranscript("user", None, True, True, False),
        ),
        ([_runner("reply", assistant=True)], TurnTranscript(None, None, True, True, False)),
        ([], TurnTranscript(None, None, False, False, False)),
    ],
    ids=[
        "reply_after_bookkeeping",
        "tool_output_newest",
        "marker_newest",
        "nothing_after_the_engine_message",
        "typed_after_the_engine_message",
        "engine_message_queued",
        "typed_message_queued",
        "typed_without_an_engine_message",
        "undecided",
        "empty",
    ],
)
def test_the_transcript_walk_reads_the_turn_the_newest_input_started(
    newest_first: list[TranscriptItem], expected: TurnTranscript
) -> None:
    assert turn_transcript_of(newest_first) == expected


# ── the recorder and the bound-session index ────────────────────────────────

RUN_ID = "r" * 32
BOUND_SESSION = "s" * 32
ORCHESTRATOR_SESSION = "o" * 32
WORKSPACE = 7
NOW = 1_700_000_000
BOUND = BoundSession(
    run_id=RUN_ID,
    engine_slot_id="implement||:0",
    store_slot_id=store_slot_id(RUN_ID, "implement||:0"),
    generation=2,
)


def _status_edge(
    status: str = "idle",
    *,
    session_id: str = BOUND_SESSION,
    workspace_id: int = WORKSPACE,
    observed_at_ms: int = NOW * 1000,
    **fields: Any,
) -> SessionStatusEdge:
    if status in {"idle", "failed"}:
        fields.setdefault("turn_outcome", "completed" if status == "idle" else "failed")
    fields.setdefault("origin", "relayed_runner_status")
    return SessionStatusEdge(
        session_id=session_id,
        status=status,
        previous_status="running",
        workspace_id=workspace_id,
        observed_at_ms=observed_at_ms,
        **fields,
    )


class _ThreadRecordingQueue(FakeQueueStore):
    """The fake queue store, recording the thread of each write and failing on request."""

    def __init__(self, *, failures: int = 0) -> None:
        super().__init__()
        self.threads: list[str] = []
        self.failures = failures
        self.attempts = 0

    def enqueue_work(self, items: Any, **kwargs: Any) -> list[str]:
        self.attempts += 1
        self.threads.append(threading.current_thread().name)
        if self.failures:
            self.failures -= 1
            raise OperationalError("INSERT", {}, RuntimeError("database is down"))
        return super().enqueue_work(items, **kwargs)


def _index(*entries: tuple[int, str, BoundSession]) -> BoundSessions:
    index = BoundSessions()
    for workspace_id, session_id, bound in entries:
        index.push(workspace_id, session_id, bound)
    return index


@pytest.fixture
def queue() -> _ThreadRecordingQueue:
    return _ThreadRecordingQueue()


@pytest.fixture
def recorder(queue: _ThreadRecordingQueue) -> Iterator[TurnFactRecorder]:
    index = _index(
        (WORKSPACE, BOUND_SESSION, BOUND),
        (
            WORKSPACE,
            ORCHESTRATOR_SESSION,
            dataclasses.replace(
                BOUND, engine_slot_id="orchestrator", generation=1, orchestrator=True
            ),
        ),
    )
    recording = TurnFactRecorder(index, queue, clock=lambda: NOW, sleep=lambda _s: None)
    recording.start()
    try:
        yield recording
    finally:
        recording.close()


def _signals(queue: FakeQueueStore) -> list[WorkItem]:
    return sorted(queue.work.values(), key=lambda item: item.id)


def test_a_bound_turn_end_is_one_signal_row_written_off_the_publishing_thread(
    recorder: TurnFactRecorder, queue: _ThreadRecordingQueue
) -> None:
    recorder.observe(_status_edge(turn_response_id="resp_1"))
    recorder.observe(_status_edge(turn_response_id="resp_1"))
    recorder.wait_idle()

    [row] = _signals(queue)
    payload = json.loads(row.payload)
    assert (row.workspace_id, row.run_id, row.kind) == (WORKSPACE, RUN_ID, int(WorkKind.SIGNAL))
    assert (row.slot_generation, row.available_at) == (2, NOW)
    assert payload["effect_type"] == "turn_fact"
    assert (payload["session_id"], payload["engine_slot_id"], payload["generation"]) == (
        BOUND_SESSION,
        "implement||:0",
        2,
    )
    assert payload["slot_id"] == BOUND.store_slot_id
    assert EdgeFacts.from_payload(payload["edge"]).response_id == "resp_1"
    assert queue.threads and threading.current_thread().name not in queue.threads
    # The duplicate edge reached the store and wrote nothing new.
    assert recorder.written == 2


@pytest.mark.parametrize(
    "edge",
    [
        _status_edge(session_id="u" * 32),
        _status_edge(workspace_id=WORKSPACE + 1),
        _status_edge("running"),
        _status_edge("waiting"),
    ],
    ids=["unbound_session", "same_session_other_workspace", "running", "waiting"],
)
def test_edges_that_cannot_end_a_bound_turn_are_dropped_on_the_publishing_thread(
    recorder: TurnFactRecorder, queue: _ThreadRecordingQueue, edge: SessionStatusEdge
) -> None:
    recorder.observe(edge)
    recorder.wait_idle()

    assert (queue.attempts, recorder.written) == (0, 0)


def test_a_running_edge_that_reports_the_previous_turns_outcome_is_kept(
    recorder: TurnFactRecorder, queue: _ThreadRecordingQueue
) -> None:
    recorder.observe(
        _status_edge("running", turn_outcome="cancelled", turn_response_id="r1", response_id="r2")
    )
    recorder.wait_idle()

    assert len(_signals(queue)) == 1


def test_only_failed_and_archive_edges_of_an_orchestrator_are_recorded(
    recorder: TurnFactRecorder, queue: _ThreadRecordingQueue
) -> None:
    recorder.observe(_status_edge(session_id=ORCHESTRATOR_SESSION))
    recorder.observe(_status_edge("idle", session_id=ORCHESTRATOR_SESSION, turn_outcome=None))
    recorder.observe(_status_edge("failed", session_id=ORCHESTRATOR_SESSION))
    recorder.observe(
        _status_edge(
            "idle", session_id=ORCHESTRATOR_SESSION, turn_outcome=None, origin="archive_idle"
        )
    )
    recorder.wait_idle()

    payloads = [json.loads(row.payload) for row in _signals(queue)]
    assert [
        (payload["engine_slot_id"], payload["edge"]["status"], payload["edge"]["origin"])
        for payload in payloads
    ] == [
        ("orchestrator", "failed", "relayed_runner_status"),
        ("orchestrator", "idle", "archive_idle"),
    ]


def test_a_long_astral_error_message_is_cut_so_the_signal_fits(
    recorder: TurnFactRecorder, queue: _ThreadRecordingQueue
) -> None:
    recorder.observe(
        _status_edge(
            "failed",
            error_code="\U0001f600" * 128,
            error_message="\U0001f600" * 4_500,
            failure_origin="relayed_runner_status",
        )
    )
    recorder.wait_idle()

    [row] = _signals(queue)
    edge = EdgeFacts.from_payload(json.loads(row.payload)["edge"])
    assert len(row.payload.encode()) <= MAX_PAYLOAD_BYTES
    assert edge.error_message is not None and 0 < len(edge.error_message) <= 1_000
    assert set(edge.error_message) == {"\U0001f600"}


def test_a_store_error_is_retried_twice_then_the_edge_is_dropped() -> None:
    failing = _ThreadRecordingQueue(failures=5)
    recording = TurnFactRecorder(
        _index((WORKSPACE, BOUND_SESSION, BOUND)),
        failing,
        clock=lambda: NOW,
        sleep=lambda _s: None,
    )
    recording.start()
    try:
        recording.observe(_status_edge())
        recording.wait_idle()
        assert (failing.attempts, recording.dropped_failed, recording.written) == (3, 1, 0)
        # Back up: the next edge is written.
        failing.failures = 0
        recording.observe(_status_edge(observed_at_ms=NOW * 1000 + 1))
        recording.wait_idle()
    finally:
        recording.close()

    assert (recording.written, len(failing.work)) == (1, 1)


def test_an_edge_that_cannot_become_a_signal_does_not_stop_the_worker(
    queue: _ThreadRecordingQueue,
) -> None:
    # A slot id far past what a signal payload holds.
    oversized = dataclasses.replace(BOUND, engine_slot_id="x" * 20_000)
    recording = TurnFactRecorder(
        _index((WORKSPACE, BOUND_SESSION, BOUND), (WORKSPACE, "h" * 32, oversized)),
        queue,
        clock=lambda: NOW,
    )
    recording.start()
    try:
        recording.observe(_status_edge(session_id="h" * 32))
        recording.observe(_status_edge())
        recording.wait_idle()
    finally:
        recording.close()

    assert (recording.dropped_failed, recording.written, len(_signals(queue))) == (1, 1, 1)


def test_a_full_queue_drops_the_edge_without_blocking_the_publisher(
    queue: _ThreadRecordingQueue,
) -> None:
    # Not started: nothing takes the edges off the queue.
    recording = TurnFactRecorder(
        _index((WORKSPACE, BOUND_SESSION, BOUND)), queue, clock=lambda: NOW, max_pending=2
    )
    for offset in range(3):
        recording.observe(_status_edge(observed_at_ms=NOW * 1000 + offset))

    assert recording.dropped_full == 1
    recording.start()
    recording.wait_idle()
    recording.close()
    assert len(_signals(queue)) == 2


def test_a_stuck_store_never_blocks_the_publisher_and_keeps_the_backlog_bounded() -> None:
    in_store = threading.Event()
    release = threading.Event()

    class StuckQueue(_ThreadRecordingQueue):
        def enqueue_work(self, items: Any, **kwargs: Any) -> list[str]:
            in_store.set()
            assert release.wait(10)
            return super().enqueue_work(items, **kwargs)

    stuck = StuckQueue()
    recording = TurnFactRecorder(
        _index((WORKSPACE, BOUND_SESSION, BOUND)), stuck, clock=lambda: NOW, max_pending=4
    )
    recording.start()
    try:
        recording.observe(_status_edge())
        assert in_store.wait(10)

        def publish() -> None:
            for offset in range(1, 101):
                recording.observe(_status_edge(observed_at_ms=NOW * 1000 + offset))

        # The server keeps publishing while the worker is stuck in the store.
        publisher = threading.Thread(target=publish)
        publisher.start()
        publisher.join(10)
        assert not publisher.is_alive()
        assert recording.dropped_full == 96
        release.set()
        recording.wait_idle()
    finally:
        release.set()
        recording.close()

    assert (recording.written, len(_signals(stuck))) == (5, 5)


def test_one_busy_session_cannot_fill_the_queue_for_other_runs(
    queue: _ThreadRecordingQueue,
) -> None:
    other_session = "t" * 32
    other_run = dataclasses.replace(BOUND, run_id="q" * 32)
    recording = TurnFactRecorder(
        _index((WORKSPACE, BOUND_SESSION, BOUND), (WORKSPACE, other_session, other_run)),
        queue,
        clock=lambda: NOW,
        max_pending_per_session=2,
    )
    # Not started: the busy session's edges wait, and its third one on is dropped.
    for offset in range(5):
        recording.observe(_status_edge(observed_at_ms=NOW * 1000 + offset))
    recording.observe(_status_edge(session_id=other_session))
    assert (recording.dropped_busy, recording.dropped_full) == (3, 0)
    recording.start()
    recording.wait_idle()
    # Once written, the session may queue again.
    recording.observe(_status_edge(observed_at_ms=NOW * 1000 + 10))
    recording.wait_idle()
    recording.close()

    assert {row.run_id for row in _signals(queue)} == {RUN_ID, "q" * 32}
    assert (recording.written, len(_signals(queue))) == (4, 4)


def test_an_edge_handed_off_as_the_recorder_closes_never_blocks_a_wait(
    queue: _ThreadRecordingQueue,
) -> None:
    class ClosingRecorder(TurnFactRecorder):
        def _take(self, key: tuple[int, str]) -> bool:
            # The close lands after the observer's check and before its hand-off.
            taken = super()._take(key)
            self.close()
            return taken

    recording = ClosingRecorder(
        _index((WORKSPACE, BOUND_SESSION, BOUND)), queue, clock=lambda: NOW
    )
    recording.start()
    recording.observe(_status_edge())
    recording.wait_idle()

    assert (queue.attempts, recording.written) == (0, 0)


def test_an_observer_failure_never_reaches_the_publisher(queue: _ThreadRecordingQueue) -> None:
    class BrokenIndex(BoundSessions):
        def lookup(self, workspace_id: int, session_id: str) -> BoundSession | None:
            raise RuntimeError("index bug")

    recording = TurnFactRecorder(BrokenIndex(), queue, clock=lambda: NOW)
    recording.observe(_status_edge())

    assert queue.attempts == 0


def _binding(
    session_id: str,
    *,
    slot_id: str = "implement||:0",
    run_id: str = RUN_ID,
    workspace_id: int = WORKSPACE,
    generation: int = 1,
) -> SessionBinding:
    return binding_from_draft(
        SessionBindingDraft(
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=run_id,
            role="step",
            effect_key=f"{run_id}:1:create_session:{session_id}",
            slot_id=slot_id,
            slot_role="orchestrator" if slot_id == ORCHESTRATOR_SLOT_ID else "step_agent",
            session_generation=generation,
            progress=SessionBindingProgress.INITIALIZED,
        ),
        NOW,
    )


class _ListedBindings:
    """``list_bound_sessions`` over a list the test changes, keyset-paged like the store."""

    def __init__(self, bindings: list[SessionBinding]) -> None:
        self.bindings = bindings
        self.pages = 0
        self.during_read: Callable[[], None] | None = None

    def list_bound_sessions(
        self, *, cursor: tuple[int, str] | None = None, limit: int = 500
    ) -> list[SessionBinding]:
        self.pages += 1
        if self.during_read is not None:
            self.during_read()
        ordered = sorted(self.bindings, key=lambda item: (item.workspace_id, item.session_id))
        after = [
            item
            for item in ordered
            if cursor is None or (item.workspace_id, item.session_id) > cursor
        ]
        return after[:limit]


def test_the_refresher_rebuilds_the_index_with_orchestrators_and_drops_finished_runs() -> None:
    step = _binding("s1" * 16, generation=2)
    orchestrator = _binding("o1" * 16, slot_id=ORCHESTRATOR_SLOT_ID)
    other_workspace = _binding("s1" * 16, workspace_id=WORKSPACE + 1, run_id="q" * 32)
    source = _ListedBindings([step, orchestrator, other_workspace])
    index = BoundSessions()
    refresher = BoundSessionRefresher(source, index, page_size=2)

    assert refresher.refresh() == 3

    assert source.pages == 2
    assert index.lookup(WORKSPACE, "s1" * 16) == BoundSession(
        run_id=RUN_ID,
        engine_slot_id="implement||:0",
        store_slot_id=store_slot_id(RUN_ID, "implement||:0"),
        generation=2,
    )
    found = index.lookup(WORKSPACE, "o1" * 16)
    assert found is not None and found.orchestrator
    assert index.lookup(WORKSPACE + 1, "s1" * 16) is not None
    # The run finished, so the store stops listing its sessions.
    source.bindings = [other_workspace]
    refresher.refresh()
    assert index.lookup(WORKSPACE, "s1" * 16) is None
    assert index.lookup(WORKSPACE, "o1" * 16) is None
    assert len(index) == 1


def test_a_session_pushed_while_the_index_is_rebuilt_is_kept() -> None:
    source = _ListedBindings([])
    index = BoundSessions()
    late = (WORKSPACE, "late" * 8, BOUND)
    source.during_read = lambda: index.push(*late)

    BoundSessionRefresher(source, index).refresh()

    assert index.lookup(WORKSPACE, "late" * 8) == BOUND


def test_a_rebuild_drops_a_session_pushed_before_it_read_the_store() -> None:
    # Pushed before the read began, then its run finished: the read is the truth.
    index = _index((WORKSPACE, "early" * 6 + "ab", BOUND))
    source = _ListedBindings([])

    BoundSessionRefresher(source, index).refresh()

    assert len(index) == 0


def test_a_rebuild_whose_read_fails_leaves_the_index_as_it_was() -> None:
    index = _index((WORKSPACE, BOUND_SESSION, BOUND))

    class Down(_ListedBindings):
        def list_bound_sessions(self, **_page: Any) -> list[SessionBinding]:
            raise OperationalError("SELECT", {}, RuntimeError("database is down"))

    with pytest.raises(OperationalError):
        BoundSessionRefresher(Down([]), index).refresh()

    # No rebuild is left open to collect pushes, and the entries stand.
    assert not index.rebuilding
    assert index.lookup(WORKSPACE, BOUND_SESSION) == BOUND


def test_bindings_without_an_engine_slot_are_not_indexed() -> None:
    step = _binding("a" * 32)
    anchor = dataclasses.replace(
        step, role=SessionBindingRole.ANCHOR, slot_id=None, slot_role=None
    )

    assert BoundSession.from_binding(anchor) is None
    assert BoundSession.from_binding(dataclasses.replace(step, slot_id=None)) is None


async def test_the_refresher_fills_the_index_at_start_and_stops_its_task() -> None:
    source = _ListedBindings([_binding("s1" * 16)])
    index = BoundSessions()
    refresher = BoundSessionRefresher(source, index)

    await refresher.start()
    try:
        assert index.lookup(WORKSPACE, "s1" * 16) is not None
    finally:
        await refresher.stop()
    assert refresher.stopped
