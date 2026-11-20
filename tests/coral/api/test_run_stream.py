"""The run stream: snapshot, one entry per log row, replay from ``Last-Event-ID``, and its bounds.

The stream's frames are read straight from :meth:`RunStream.frames` (httpx buffers a
response body until it ends), with commits made meanwhile on another thread; HTTP tests
read runs that end with ``[DONE]``. Runs live in the in-memory stores (``World.fake``).
A :class:`StreamClient` applies each frame as a browser would and fails on a gap or a
repeat. Waits the test drives use :class:`FakeTime`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine

from coral.api.errors import CoralApiError
from coral.api.run_service import InFlight, RunsApi
from coral.api.runs import create_runs_router
from coral.api.spend import SPEND_THREADS, SpendCache
from coral.api.stream import (
    CONNECT_BURST,
    HEARTBEAT_S,
    MAX_LAST_EVENT_ID_CHARS,
    MAX_LOADS_PER_USER,
    MAX_STREAM_S,
    MAX_STREAMS,
    MAX_STREAMS_PER_RUN_USER,
    MAX_STREAMS_PER_USER,
    PAGE_ROWS,
    POLL_S,
    RECHECK_S,
    REPLAY_MAX_ROWS,
    SEND_TIMEOUT_S,
    STREAM_THREADS,
    CoralEventStream,
    RunStream,
    RunStreamHub,
    StreamCursor,
    stream_cursor,
)
from coral.bridge.executors import BoundedThreads
from coral.bridge.service import RunRead
from coral.db.enum_codecs import ActorKind, LogKind, RunPauseReason
from coral.engine.projection import project
from coral.engine.types import HandoffEvaluated, PauseRun
from coral.omni.protocols import Viewer
from coral.omni.server import coral_lifespan
from coral.omni.server.access import account_still_valid, request_viewer
from coral.recovery.cancel import cancel_run_row
from coral.recovery.pause import pause_run_once
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import LogEntryDraft, RunLogEntry, Transition
from coral.stores.run_commit import commit_on_run_row
from coral.stores.workflows import SqlWorkflowDefinitionStore
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID
from omnigent.runtime import pending_elicitations
from omnigent.server import elicitation_hooks
from omnigent.server.auth import UnifiedAuthProvider
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.api._stream_client import (
    DONE,
    FakeTime,
    StreamClient,
    never_disconnected,
    parse_body,
    pump,
    read_until,
)
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
    CHANGE_TOKEN,
    CHANGE_TOKEN_AGAIN,
    GATED,
    IMPLEMENT_AGAIN,
    answer,
    hand_off,
)
from tests.coral.bridge._world import WORKSPACE, World, run_spec, start
from tests.coral.omni._gate_server import CORAL_SERVER_PLUGIN, coral_server, gate_run

HEADER = "X-Forwarded-Email"
HEADER_AUTH = UnifiedAuthProvider(source="header", local_single_user=False, header_name=HEADER)
ALICE = Viewer(user_id="alice")
BOB = Viewer(user_id="bob")
OTHER_WORKSPACE = WORKSPACE + 1
RUNS = "/v1/coral/runs"
NOT_FOUND = b'{"error":{"code":"not_found","message":"Run not found.","details":null}}'
NO_CURSOR = StreamCursor()
# A hang guard for every wait on a stream.
TIMEOUT_S = budget(30)


# ── Setup ───────────────────────────────────────────────────────────────────


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


@pytest.fixture
async def threads() -> AsyncIterator[BoundedThreads]:
    pool = BoundedThreads(max_workers=STREAM_THREADS, thread_name_prefix="test-coral-stream")
    yield pool
    pool.close()


def _hub(
    world: World, threads: BoundedThreads, *, hooked: bool = True, **options: Any
) -> RunStreamHub:
    hub = RunStreamHub(bridge=world.bridge, run_store=world.runs, threads=threads, **options)
    if hooked:
        world.runs.register_post_commit(hub.notify)
    return hub


@pytest.fixture
async def hub(world: World, threads: BoundedThreads) -> AsyncIterator[RunStreamHub]:
    built = _hub(world, threads)
    yield built
    await built.close()


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


@pytest.fixture
async def timed_hub(
    world: World, threads: BoundedThreads, fake_time: FakeTime
) -> AsyncIterator[RunStreamHub]:
    built = _hub(world, threads, clock=fake_time, wait=fake_time.wait)
    yield built
    await built.close()


def _gated(world: World, key: str = "stream", **spec: Any) -> str:
    """A started ``gated`` run of Alice's."""
    return start(world, GATED, spec=run_spec(start_key=key, **spec), start_key=key).id


def _finish(world: World, run_id: str) -> None:
    """Alice rejects the change once and approves the second: the run completes."""
    hand_off(world, run_id)
    answer(world, run_id, CHANGE_TOKEN, "reject")
    hand_off(world, run_id, IMPLEMENT_AGAIN)
    answer(world, run_id, CHANGE_TOKEN_AGAIN, "approve")


def _head(world: World, run_id: str, workspace_id: int = WORKSPACE) -> int:
    run = world.runs.get_run(run_id, workspace_id=workspace_id)
    assert run is not None
    return run.next_log_seq - 1


def _view(world: World, run_id: str) -> dict[str, Any]:
    return project(world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state).model_dump(
        mode="json"
    )


def _notes(
    world: World,
    run_id: str,
    count: int,
    *,
    workspace_id: int = WORKSPACE,
    kind: int = int(LogKind.ALERT),
    actor_kind: int = int(ActorKind.ENGINE),
) -> None:
    """``count`` alert rows (or rows of other codes) on the run, at most 64 to a transition."""
    while count > 0:
        batch = min(count, 64)
        rows = tuple(
            LogEntryDraft(kind=kind, actor_kind=actor_kind, body="{}") for _ in range(batch)
        )
        commit_on_run_row(
            run_store=world.runs,
            workspace_id=workspace_id,
            run_id=run_id,
            reduce_fn=lambda _run, rows=rows: Transition(logs=rows),
        )
        count -= batch


def _stream(
    hub: RunStreamHub,
    run_id: str,
    cursor: StreamCursor = NO_CURSOR,
    *,
    viewer: Viewer = ALICE,
    workspace_id: int = WORKSPACE,
    is_disconnected: Callable[[], Any] = never_disconnected,
) -> RunStream:
    return hub.stream(viewer, workspace_id, run_id, cursor=cursor, is_disconnected=is_disconnected)


async def _all(frames: AsyncIterator[str], client: StreamClient) -> StreamClient:
    async with asyncio.timeout(TIMEOUT_S):
        await pump(frames, client)
    return client


async def _drop(reader: asyncio.Task[None]) -> None:
    """A forced drop: the reading task is cancelled where it waits, as a disconnect does."""
    reader.cancel()
    await asyncio.gather(reader, return_exceptions=True)


# ── Snapshot, live entries and replay ───────────────────────────────────────


async def test_without_a_cursor_the_stream_sends_the_snapshot_then_live_entries(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    head = _head(world, run_id)
    stream = _stream(hub, run_id)
    frames, client = stream.frames(), StreamClient()

    await read_until(frames, client, lambda c: c.view is not None, timeout_s=TIMEOUT_S)
    driver = asyncio.create_task(asyncio.to_thread(hand_off, world, run_id))
    await driver
    await read_until(
        frames, client, lambda c: c.last_seq == _head(world, run_id), timeout_s=TIMEOUT_S
    )
    await frames.aclose()

    snapshot = client.events[0]
    assert (snapshot.kind, snapshot.id, snapshot.data["seq"]) == ("snapshot", head, head)
    assert snapshot.data["protocol"] == 1 and snapshot.data["view_version"] == 1
    assert snapshot.data["run"]["allowed_actions"] == ["pause", "cancel"]
    assert client.entries == list(range(head + 1, _head(world, run_id) + 1))
    assert client.view == stream.view == _view(world, run_id)
    assert hub.watchers == 0


async def test_a_dropped_stream_resumes_from_last_event_id_with_every_missed_patch_once(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    first_head = _head(world, run_id)
    client = StreamClient()

    # Connected while the step hands off.
    reader = asyncio.create_task(pump(_stream(hub, run_id).frames(), client))
    await poll_until_async(lambda: client.view is not None, timeout_s=TIMEOUT_S)
    assert client.last_seq == first_head
    await asyncio.to_thread(hand_off, world, run_id)
    await poll_until_async(lambda: client.last_seq == _head(world, run_id), timeout_s=TIMEOUT_S)
    await _drop(reader)
    held = client.last_seq
    assert held is not None and held > first_head

    # Disconnected while the change is rejected and the step runs again.
    await asyncio.to_thread(answer, world, run_id, CHANGE_TOKEN, "reject")
    await asyncio.to_thread(hand_off, world, run_id, IMPLEMENT_AGAIN)
    missed = _head(world, run_id)

    # Reconnected while the change is approved and the run completes.
    resumed = _stream(hub, run_id, stream_cursor(str(held), None))
    reading = asyncio.create_task(_all(resumed.frames(), client))
    await asyncio.to_thread(answer, world, run_id, CHANGE_TOKEN_AGAIN, "approve")
    await reading

    final = _view(world, run_id)
    assert client.done and client.kinds()[-1] == DONE
    assert client.entries == list(range(first_head + 1, _head(world, run_id) + 1))
    assert missed < _head(world, run_id)
    assert client.view == resumed.view == final
    assert final["status"] == "completed"
    assert client.header is not None and client.header["status"] == "completed"
    assert client.header["allowed_actions"] == []
    # Headers never go back in version.
    versions = [event.data["version"] for event in client.of_kind("run")]
    assert versions == sorted(versions)
    assert client.of_kind("resync") == []
    assert hub.watchers == 0


async def test_last_event_id_wins_over_after_seq(world: World, hub: RunStreamHub) -> None:
    run_id = _gated(world)
    hand_off(world, run_id)
    head = _head(world, run_id)
    client = StreamClient(view=None, last_seq=2)

    frames = _stream(hub, run_id, stream_cursor("2", 0)).frames()
    await read_until(frames, client, lambda c: c.last_seq == head, timeout_s=TIMEOUT_S)
    await frames.aclose()

    assert client.kinds() == ["run", *["entry"] * (head - 2)]
    assert client.entries == list(range(3, head + 1))


@pytest.mark.parametrize(
    ("header", "after_seq", "expected"),
    [
        (None, None, StreamCursor()),
        (None, 4, StreamCursor(seq=4)),
        ("7", 4, StreamCursor(seq=7)),
        (" 7 ", None, StreamCursor(seq=7)),
        ("", 4, StreamCursor(seq=4)),
        ("0", None, StreamCursor(seq=0)),
        (str(2**63 - 1), None, StreamCursor(seq=2**63 - 1)),
        (str(2**63), 4, StreamCursor(invalid=True)),
        ("-1", 4, StreamCursor(invalid=True)),
        ("seven", 4, StreamCursor(invalid=True)),
        ("1.5", None, StreamCursor(invalid=True)),
        ("0" * (MAX_LAST_EVENT_ID_CHARS + 1), 4, StreamCursor(invalid=True)),
    ],
)
def test_the_cursor_is_the_header_when_present_else_after_seq(
    header: str | None, after_seq: int | None, expected: StreamCursor
) -> None:
    assert stream_cursor(header, after_seq) == expected


@pytest.mark.parametrize("cursor", [NO_CURSOR, StreamCursor(seq=2)], ids=["snapshot", "replay"])
async def test_commits_between_the_snapshot_and_the_first_page_are_sent_and_applied_once(
    world: World, threads: BoundedThreads, cursor: StreamCursor
) -> None:
    run_id = _gated(world)
    hand_off(world, run_id)
    head_before = _head(world, run_id)
    reads = _CommitAfterRead(world, run_id, armed=True)
    hub = RunStreamHub(bridge=reads, run_store=world.runs, threads=threads)
    client = StreamClient(last_seq=cursor.seq)
    stream = _stream(hub, run_id, cursor)
    frames = stream.frames()
    try:
        await read_until(
            frames,
            client,
            lambda c: c.header is not None and c.header["pause_reason"] == "budget",
            timeout_s=TIMEOUT_S,
        )
        await frames.aclose()
    finally:
        await hub.close()

    assert not reads.armed
    # The pause landed after the stream's load: one entry above its snapshot. Rows
    # replayed up to the snapshot were sent but not applied again.
    assert client.last_seq == head_before + 1 == _head(world, run_id)
    assert client.entries[-1] == head_before + 1
    assert stream.view == _view(world, run_id)
    assert stream.view is not None and stream.view["status"] == "paused"
    # A budget pause needs a cap to resume: the stream's own view says so.
    assert client.header is not None and client.header["allowed_actions"] == ["cancel"]
    if cursor.seq is None:
        assert client.view == _view(world, run_id)
    else:
        assert client.entries == list(range(cursor.seq + 1, head_before + 2))


@dataclasses.dataclass
class _CommitAfterRead:
    """The bridge's read, and once armed, a budget pause committed right after it returns."""

    world: World
    run_id: str
    armed: bool = False

    def read(self, *, workspace_id: int, run_id: str) -> RunRead:
        found = self.world.bridge.read(workspace_id=workspace_id, run_id=run_id)
        if self.armed:
            self.armed = False
            self.world.bridge.commit_inputs(
                workspace_id=WORKSPACE,
                run_id=self.run_id,
                inputs=lambda _snapshot: (PauseRun(reason="budget", detail="budget"),),
            )
        return found


async def test_refused_and_view_neutral_rows_are_entries_with_an_empty_patch(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    head = _head(world, run_id)
    client = StreamClient()
    frames = _stream(hub, run_id).frames()
    await read_until(frames, client, lambda c: c.view is not None, timeout_s=TIMEOUT_S)

    # A refused input with a user pause, then a pause written on the run row alone.
    await asyncio.to_thread(
        world.bridge.commit_inputs,
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (
            HandoffEvaluated(slot_id="no-such-slot", outcome="accepted"),
            PauseRun(reason="user", detail="user"),
        ),
    )
    await read_until(frames, client, lambda c: c.last_seq == head + 2, timeout_s=TIMEOUT_S)
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor="alice")
    await asyncio.to_thread(_pause_on_row, world, run_id)
    await read_until(
        frames,
        client,
        lambda c: c.header is not None and c.header["pause_reason"] == "drift",
        timeout_s=TIMEOUT_S,
    )
    row_paused_at, row_paused = _head(world, run_id), client.header
    row_paused_kinds, row_paused_version = client.kinds()[-2:], world.run(run_id).version
    # Resuming lifts the row's pause: its entry, then a run frame shows it running.
    await asyncio.to_thread(
        world.bridge.resume_run, workspace_id=WORKSPACE, run_id=run_id, actor="alice"
    )
    await read_until(
        frames,
        client,
        lambda c: c.header is not None and c.header["status"] == "running",
        timeout_s=TIMEOUT_S,
    )
    await frames.aclose()

    entries = {event.data["seq"]: event.data for event in client.of_kind("entry")}
    refused, paused = entries[head + 1], entries[head + 2]
    assert (refused["kind"], refused["patch"]) == ("engine.handoff_evaluated", [])
    assert refused["rejected"] is not None
    assert paused["kind"] == "engine.pause_run" and paused["patch"] != []
    row_pause = entries[row_paused_at]
    assert (row_pause["kind"], row_pause["patch"], row_pause["rejected"]) == (
        "log.paused",
        [],
        None,
    )
    # The row-only pause shows as a run frame after its entry; the view still runs.
    assert row_paused_kinds == ["entry", "run"]
    assert row_paused == {
        "status": "paused",
        "pause_reason": "drift",
        "version": row_paused_version,
        "finished_at": None,
        "allowed_actions": ["resume", "cancel"],
        "load_error": None,
    }
    assert client.kinds()[-2:] == ["entry", "run"]
    assert client.header == {
        "status": "running",
        "pause_reason": None,
        "version": world.run(run_id).version,
        "finished_at": None,
        "allowed_actions": ["pause", "cancel"],
        "load_error": None,
    }
    assert client.view == _view(world, run_id) and client.view["status"] == "running"
    assert client.entries == list(range(head + 1, _head(world, run_id) + 1))


def _pause_on_row(world: World, run_id: str) -> None:
    pause_run_once(
        world.runs,
        workspace_id=WORKSPACE,
        run_id=run_id,
        reason=RunPauseReason.DRIFT,
        body={"kind": "pause_run", "reason": "drift", "detail": "drift"},
        checksum_parts=("stream-test-drift", run_id),
        now_us=world.clock.epoch * 1_000_000,
    )


# ── Resync ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("header", "backlog", "reason"),
    [
        ("not-a-seq", 0, "cursor_invalid"),
        ("9" * (MAX_LAST_EVENT_ID_CHARS + 1), 0, "cursor_invalid"),
        ("ahead", 0, "cursor_unknown"),
        ("0", REPLAY_MAX_ROWS + 1, "replay_too_long"),
    ],
)
async def test_an_unusable_cursor_or_a_long_backlog_resyncs_to_a_snapshot(
    world: World, hub: RunStreamHub, header: str, backlog: int, reason: str
) -> None:
    run_id = _gated(world)
    _notes(world, run_id, backlog - _head(world, run_id) if backlog else 0)
    head = _head(world, run_id)
    sent = str(head + 1) if header == "ahead" else header
    client = StreamClient()

    frames = _stream(hub, run_id, stream_cursor(sent, 0)).frames()
    await read_until(frames, client, lambda c: len(c.events) == 2, timeout_s=TIMEOUT_S)
    await frames.aclose()

    resync, snapshot = client.events
    assert (resync.kind, resync.data, resync.id) == (
        "resync",
        {"type": "resync", "reason": reason},
        None,
    )
    assert (snapshot.kind, snapshot.id) == ("snapshot", head)
    assert client.view == _view(world, run_id)


async def test_a_backlog_at_the_replay_cap_is_replayed_page_by_page(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    held = _head(world, run_id)
    _notes(world, run_id, REPLAY_MAX_ROWS)
    head = _head(world, run_id)
    assert head - held == REPLAY_MAX_ROWS > PAGE_ROWS
    client = StreamClient(last_seq=held)

    frames = _stream(hub, run_id, StreamCursor(seq=held)).frames()
    await read_until(frames, client, lambda c: c.last_seq == head, timeout_s=TIMEOUT_S)
    await frames.aclose()

    assert client.kinds() == ["run", *["entry"] * REPLAY_MAX_ROWS]
    assert {event.data["kind"] for event in client.of_kind("entry")} == {"log.alert"}


async def test_an_unreadable_row_resyncs_and_the_stream_continues_past_it(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    held = _head(world, run_id)
    _notes(world, run_id, 3)
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    runs.undecodable_logs.add((WORKSPACE, run_id, held + 2))
    head = _head(world, run_id)
    client = StreamClient(last_seq=held)

    frames = _stream(hub, run_id, StreamCursor(seq=held)).frames()
    await read_until(frames, client, lambda c: c.last_seq == head, timeout_s=TIMEOUT_S)
    # The stream goes on past it: a later row arrives as an entry.
    _notes(world, run_id, 1)
    await read_until(frames, client, lambda c: c.last_seq == head + 1, timeout_s=TIMEOUT_S)
    await frames.aclose()

    assert client.kinds() == ["run", "entry", "resync", "snapshot", "entry"]
    assert client.events[2].data["reason"] == "row_unreadable"
    assert client.events[3].id == head

    # A reconnect from the last seq never meets the unreadable row again.
    again = StreamClient(last_seq=client.last_seq)
    frames = _stream(hub, run_id, StreamCursor(seq=client.last_seq)).frames()
    await read_until(frames, again, lambda c: len(c.events) == 1, timeout_s=TIMEOUT_S)
    await frames.aclose()
    assert again.kinds() == ["run"]


# A code no release of this server has: a newer server wrote it, or the row is corrupt.
UNKNOWN_CODE = 250


@pytest.mark.parametrize("field", ["kind", "actor_kind"])
async def test_a_row_with_a_code_this_server_cannot_read_resyncs_past_it(
    world: World, hub: RunStreamHub, field: str
) -> None:
    run_id = _gated(world)
    held = _head(world, run_id)
    _notes(world, run_id, 1)
    _notes(world, run_id, 1, **{field: UNKNOWN_CODE})
    _notes(world, run_id, 1)
    head = _head(world, run_id)
    client = StreamClient(last_seq=held)

    frames = _stream(hub, run_id, StreamCursor(seq=held)).frames()
    await read_until(frames, client, lambda c: c.last_seq == head, timeout_s=TIMEOUT_S)
    await frames.aclose()

    assert client.kinds() == ["run", "entry", "resync", "snapshot"]
    assert client.events[2].data["reason"] == "row_unreadable"
    assert client.events[3].id == head
    # A reconnect from the last seq never meets the row again.
    again = StreamClient(last_seq=client.last_seq)
    frames = _stream(hub, run_id, StreamCursor(seq=client.last_seq)).frames()
    await read_until(frames, again, lambda c: len(c.events) == 1, timeout_s=TIMEOUT_S)
    await frames.aclose()
    assert again.kinds() == ["run"]


def _recode(world: World, run_id: str, **fields: Any) -> None:
    """The run row now holds ``fields``, as another server could write them; no hook runs."""
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    with runs._lock:
        run = runs.runs[(WORKSPACE, run_id)]
        runs.runs[(WORKSPACE, run_id)] = dataclasses.replace(
            run, version=run.version + 1, **fields
        )


async def test_a_run_row_with_a_code_this_server_cannot_read_ends_the_stream_logged_once(
    world: World, hub: RunStreamHub, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="coral.api.stream")
    opening = _gated(world, key="opening")
    _recode(world, opening, status=UNKNOWN_CODE)
    live = _gated(world, key="live")
    client = StreamClient()
    reader = asyncio.create_task(pump(_stream(hub, live).frames(), client))
    await poll_until_async(lambda: client.view is not None, timeout_s=TIMEOUT_S)

    openings = [await _all(_stream(hub, opening).frames(), StreamClient()) for _ in range(2)]
    _recode(world, live, pause_reason=UNKNOWN_CODE)
    _notes(world, live, 1)
    async with asyncio.timeout(TIMEOUT_S):
        await reader

    assert [opened.kinds() for opened in openings] == [[], []]
    # The live stream sends the row it read, then ends at the header it cannot build.
    assert client.kinds() == ["snapshot", "entry"]
    unreadable = [record for record in caplog.records if "cannot read" in record.getMessage()]
    assert [record.levelno for record in unreadable] == [
        logging.WARNING,
        logging.DEBUG,
        logging.DEBUG,
    ]
    assert hub.watchers == 0


async def test_a_load_whose_row_is_no_longer_the_caller_s_ends_the_stream_unsent(
    world: World, threads: BoundedThreads
) -> None:
    proving = Viewer(user_id="alice", account_generation="g1", check_generation=True)
    moved = _gated(world, key="moved", account_generation="g2")
    run_id = _gated(world, key="resync", account_generation="g1")
    held = _head(world, run_id)
    _notes(world, run_id, 2)
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    runs.undecodable_logs.add((WORKSPACE, run_id, held + 2))
    reads = _MoveOnReread(world, run_id)
    hub = RunStreamHub(bridge=reads, run_store=world.runs, threads=threads)
    try:
        opening = await _all(_stream(hub, moved, viewer=proving).frames(), StreamClient())
        resynced = await _all(
            _stream(hub, run_id, StreamCursor(seq=held), viewer=proving).frames(),
            StreamClient(last_seq=held),
        )
    finally:
        await hub.close()

    # The generation moved between the owner check and the load: nothing of it is sent.
    assert opening.kinds() == []
    # It moved before the snapshot after a resync: the stream ends before that snapshot.
    assert resynced.kinds() == ["run", "entry", "resync"]


@dataclasses.dataclass
class _MoveOnReread:
    """The bridge's read; the run's second read finds its owner's generation moved."""

    world: World
    run_id: str
    reads: int = 0

    def read(self, *, workspace_id: int, run_id: str) -> RunRead:
        if run_id == self.run_id:
            self.reads += 1
            if self.reads == 2:
                _recode(self.world, run_id, account_generation="g2")
        return self.world.bridge.read(workspace_id=workspace_id, run_id=run_id)


@pytest.mark.parametrize(
    "view_patch",
    [json.dumps([{"op": "remove", "path": "/no_such_member"}]), json.dumps({"op": "remove"})],
    ids=["does_not_apply", "not_a_patch"],
)
async def test_a_live_row_whose_patch_cannot_be_used_resyncs_to_a_fresh_snapshot(
    world: World, hub: RunStreamHub, view_patch: str
) -> None:
    run_id = _gated(world)
    stream = _stream(hub, run_id)
    frames, client = stream.frames(), StreamClient()
    await read_until(frames, client, lambda c: c.view is not None, timeout_s=TIMEOUT_S)

    # A row whose patch the stream's own view cannot take, and a good row, in one commit.
    bad = LogEntryDraft(
        kind=int(LogKind.ALERT), actor_kind=int(ActorKind.ENGINE), body="{}", view_patch=view_patch
    )
    rows = (bad, dataclasses.replace(bad, view_patch=None))
    commit_on_run_row(
        run_store=world.runs,
        workspace_id=WORKSPACE,
        run_id=run_id,
        reduce_fn=lambda _run: Transition(logs=rows),
    )
    head = _head(world, run_id)
    await read_until(frames, client, lambda c: c.last_seq == head, timeout_s=TIMEOUT_S)
    _notes(world, run_id, 1)
    await read_until(frames, client, lambda c: c.last_seq == head + 1, timeout_s=TIMEOUT_S)
    await frames.aclose()

    assert client.kinds() == ["snapshot", "resync", "snapshot", "entry"]
    assert client.events[1].data == {"type": "resync", "reason": "row_unreadable"}
    assert client.events[2].id == head
    assert client.view == stream.view == _view(world, run_id)


# ── Wake-ups ────────────────────────────────────────────────────────────────


async def test_a_commit_without_the_post_commit_hook_arrives_through_the_poll(
    world: World, threads: BoundedThreads
) -> None:
    # As a commit made by another process: nothing calls this hub's notify.
    hub = _hub(world, threads, hooked=False, poll_s=0.05)
    try:
        run_id = _gated(world)
        client = StreamClient()
        frames = _stream(hub, run_id).frames()
        await read_until(frames, client, lambda c: c.view is not None, timeout_s=TIMEOUT_S)
        _notes(world, run_id, 1)
        await read_until(
            frames, client, lambda c: c.last_seq == _head(world, run_id), timeout_s=TIMEOUT_S
        )
        await frames.aclose()
    finally:
        await hub.close()


async def test_a_change_published_before_the_stream_waits_is_not_missed(
    world: World, threads: BoundedThreads
) -> None:
    run_id = _gated(world)
    runs = _PublishDuringRead(world, run_id)

    async def only_a_change(event: asyncio.Event, _timeout: float) -> None:
        # Never times out: a stream that waits past a published change hangs here.
        await event.wait()

    hub = RunStreamHub(bridge=world.bridge, run_store=runs, threads=threads, wait=only_a_change)
    world.runs.register_post_commit(hub.notify)
    try:
        client = StreamClient()
        frames = _stream(hub, run_id).frames()
        await read_until(frames, client, lambda c: c.view is not None, timeout_s=TIMEOUT_S)
        watcher = hub.watcher(WORKSPACE, run_id)
        assert watcher is not None
        before = watcher.counter
        runs.armed = True
        _notes(world, run_id, 1)
        reading = asyncio.create_task(
            read_until(
                frames,
                client,
                lambda c: c.last_seq == _head(world, run_id) and not runs.armed,
                timeout_s=TIMEOUT_S,
            )
        )
        # The second row is committed while the stream reads the first, and its change
        # is published before the stream is done reading.
        await poll_until_async(lambda: watcher.counter >= before + 2, timeout_s=TIMEOUT_S)
        runs.published.set()
        await reading
        await frames.aclose()
    finally:
        runs.published.set()
        await hub.close()
    assert client.kinds() == ["snapshot", "entry", "entry"]


class _PublishDuringRead:
    """
    The run store; once armed, its next log read commits another row and returns only
    after ``published`` is set, holding the rows it read before that commit.
    """

    def __init__(self, world: World, run_id: str) -> None:
        self._world = world
        self._run_id = run_id
        self.armed = False
        self.published = threading.Event()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._world.runs, name)

    def read_log(self, run_id: str, **kwargs: Any) -> list[RunLogEntry]:
        rows = self._world.runs.read_log(run_id, **kwargs)
        if self.armed:
            _notes(self._world, self._run_id, 1)
            self.published.wait(timeout=TIMEOUT_S)
            self.armed = False
        return rows


async def test_a_header_older_than_the_rows_already_sent_is_never_sent(
    world: World, threads: BoundedThreads
) -> None:
    run_id = _gated(world)
    runs = _CommitBeforeRead(
        world,
        lambda: world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor="alice"),
    )
    hub = RunStreamHub(bridge=world.bridge, run_store=runs, threads=threads)
    world.runs.register_post_commit(hub.notify)
    try:
        client = StreamClient()
        frames = _stream(hub, run_id).frames()
        await read_until(frames, client, lambda c: c.view is not None, timeout_s=TIMEOUT_S)
        # The stream wakes for the pause; the resume lands as it reads the pause's row.
        runs.armed = True
        world.bridge.commit_inputs(
            workspace_id=WORKSPACE,
            run_id=run_id,
            inputs=lambda _snapshot: (PauseRun(reason="user", detail="user"),),
        )
        await read_until(frames, client, lambda c: len(c.entries) == 2, timeout_s=TIMEOUT_S)
        _pause_on_row(world, run_id)
        await read_until(
            frames,
            client,
            lambda c: c.header is not None and c.header["pause_reason"] == "drift",
            timeout_s=TIMEOUT_S,
        )
        await frames.aclose()
    finally:
        await hub.close()

    assert not runs.armed
    # The paused row was older than the resume already sent: only the drift pause shows.
    assert [event.data["pause_reason"] for event in client.of_kind("run")] == ["drift"]
    assert [event.data["kind"] for event in client.of_kind("entry")] == [
        "engine.pause_run",
        "engine.resume_run",
        "log.paused",
    ]


class _CommitBeforeRead:
    """The run store; once armed, its next log read first commits ``commit``."""

    def __init__(self, world: World, commit: Callable[[], object]) -> None:
        self._world = world
        self._commit = commit
        self.armed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._world.runs, name)

    def read_log(self, run_id: str, **kwargs: Any) -> list[RunLogEntry]:
        if self.armed:
            self.armed = False
            self._commit()
        return self._world.runs.read_log(run_id, **kwargs)


async def test_the_watcher_keeps_the_newest_row_and_counts_each_change(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    older = world.run(run_id)
    hand_off(world, run_id)
    newer = world.run(run_id)
    client = StreamClient()
    frames = _stream(hub, run_id).frames()
    await read_until(frames, client, lambda c: c.view is not None, timeout_s=TIMEOUT_S)
    watcher = hub.watcher(WORKSPACE, run_id)
    assert watcher is not None and watcher.row == newer
    counter = watcher.counter

    watcher.offer(older)
    watcher.offer(newer)

    assert (watcher.row, watcher.counter) == (newer, counter)
    await frames.aclose()
    assert hub.watcher(WORKSPACE, run_id) is None


async def test_closing_the_hub_or_a_shutdown_ends_a_waiting_stream_without_done(
    world: World, threads: BoundedThreads
) -> None:
    run_id = _gated(world)
    stopping = False
    hub = _hub(world, threads, shutting_down=lambda: stopping)
    try:
        for end in ("shutdown", "close"):
            client = StreamClient()
            reader = asyncio.create_task(pump(_stream(hub, run_id).frames(), client))
            await poll_until_async(lambda c=client: c.view is not None, timeout_s=TIMEOUT_S)
            if end == "shutdown":
                stopping = True
            else:
                stopping = False
                await hub.close()
            # Within one poll, never after a heartbeat's wait.
            async with asyncio.timeout(budget(POLL_S * 4)):
                await reader
            assert client.kinds() == ["snapshot"]
    finally:
        await hub.close()
    with pytest.raises(CoralApiError) as refused:
        hub.reserve(ALICE, WORKSPACE, run_id)
    assert _refusal(refused) == SHUTTING_DOWN


# ── Time: heartbeats, the lifetime and the access re-check ──────────────────


async def test_an_idle_stream_sends_a_heartbeat_every_15_seconds(
    world: World, timed_hub: RunStreamHub, fake_time: FakeTime
) -> None:
    run_id = _gated(world)
    client = StreamClient()
    beats: list[float] = []
    frames = _stream(timed_hub, run_id).frames()

    async with asyncio.timeout(TIMEOUT_S):
        while len(beats) < 2:
            if client.take(await anext(frames)).kind == "heartbeat":
                beats.append(fake_time.elapsed)
    await frames.aclose()

    assert HEARTBEAT_S == 15
    assert beats == [HEARTBEAT_S, 2 * HEARTBEAT_S]
    assert client.kinds() == ["snapshot", "heartbeat", "heartbeat"]
    assert client.of_kind("heartbeat")[0].data == {"type": "heartbeat"}


async def test_every_stream_ends_after_five_minutes_without_done(
    world: World, threads: BoundedThreads, fake_time: FakeTime
) -> None:
    checked: list[Viewer] = []

    def still_valid(viewer: Viewer) -> bool:
        checked.append(viewer)
        return True

    hub = _hub(world, threads, clock=fake_time, wait=fake_time.wait, still_valid=still_valid)
    try:
        client = await _all(_stream(hub, _gated(world)).frames(), StreamClient())
    finally:
        await hub.close()

    assert MAX_STREAM_S == 300
    assert MAX_STREAM_S <= fake_time.elapsed < MAX_STREAM_S + POLL_S
    assert not client.done and client.kinds()[-1] == "heartbeat"
    # A caller that proved no account generation is never re-checked.
    assert checked == []


@pytest.mark.parametrize("answers", [[True, False], ["raise"]])
async def test_an_account_no_longer_valid_ends_the_stream_within_one_recheck(
    world: World, threads: BoundedThreads, fake_time: FakeTime, answers: list[Any]
) -> None:
    proving = Viewer(user_id="alice", account_generation="g1", check_generation=True)
    calls: list[float] = []

    def still_valid(viewer: Viewer) -> bool:
        assert viewer == proving
        calls.append(fake_time.elapsed)
        answer_now = answers[len(calls) - 1]
        if answer_now == "raise":
            raise RuntimeError("accounts store unavailable")
        return bool(answer_now)

    hub = _hub(world, threads, clock=fake_time, wait=fake_time.wait, still_valid=still_valid)
    run_id = _gated(world, account_generation="g1")
    try:
        client = await _all(_stream(hub, run_id, viewer=proving).frames(), StreamClient())
    finally:
        await hub.close()

    assert RECHECK_S == 60
    assert calls == [RECHECK_S * (index + 1) for index in range(len(answers))]
    assert fake_time.elapsed < calls[-1] + POLL_S
    assert not client.done


def test_the_account_check_follows_the_server_s_accounts_and_fails_closed() -> None:
    accounts = {"alice": "g1"}
    provider = UnifiedAuthProvider(source="header", local_single_user=False, header_name=HEADER)
    provider.set_account_check(lambda user, generation: accounts.get(user) == generation)
    proving = Viewer(user_id="alice", account_generation="g1", check_generation=True)
    still_valid = account_still_valid(provider)

    assert still_valid(proving)
    accounts["alice"] = "g2"
    assert not still_valid(proving)
    del accounts["alice"]
    assert not still_valid(proving)
    # Without a provider that can check accounts, a proven generation stays unproven.
    assert not account_still_valid(None)(proving)
    assert not account_still_valid(cast(Any, object()))(proving)


async def test_a_moved_account_generation_ends_the_stream_at_once(
    world: World, hub: RunStreamHub
) -> None:
    proving = Viewer(user_id="alice", account_generation="g1", check_generation=True)
    run_id = _gated(world, account_generation="g1")
    client = StreamClient()
    reader = asyncio.create_task(pump(_stream(hub, run_id, viewer=proving).frames(), client))
    await poll_until_async(lambda: client.view is not None, timeout_s=TIMEOUT_S)

    # The owner's password changed: their Coral rows carry the new generation.
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    with runs._lock:
        run = runs.runs[(WORKSPACE, run_id)]
        runs.runs[(WORKSPACE, run_id)] = dataclasses.replace(
            run, account_generation="g2", version=run.version + 1
        )
    runs.post_commit_hooks.run(run_id, run.version + 1)

    async with asyncio.timeout(TIMEOUT_S):
        await reader
    assert client.kinds() == ["snapshot"]


async def test_the_stream_ends_with_done_once_the_run_finishes(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    client = StreamClient()
    reading = asyncio.create_task(_all(_stream(hub, run_id).frames(), client))
    await poll_until_async(lambda: client.view is not None, timeout_s=TIMEOUT_S)

    await asyncio.to_thread(
        world.bridge.cancel_run, workspace_id=WORKSPACE, run_id=run_id, actor="alice"
    )
    await reading

    assert client.kinds()[-2:] == ["run", DONE]
    assert client.header is not None and client.header["status"] == "cancelled"
    assert client.last_seq == _head(world, run_id)
    assert client.view == _view(world, run_id)


async def test_a_run_that_cannot_load_streams_its_row_until_a_row_cancel_ends_it(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    # The run's frozen engine config is gone, so its engine cannot be loaded.
    key = (WORKSPACE, run_id)
    runs.specs[key] = dataclasses.replace(runs.specs[key], engine_config=None)
    client = StreamClient()
    reading = asyncio.create_task(_all(_stream(hub, run_id).frames(), client))
    await poll_until_async(lambda: client.header is not None, timeout_s=TIMEOUT_S)

    await asyncio.to_thread(
        cancel_run_row,
        runs,
        workspace_id=WORKSPACE,
        run_id=run_id,
        actor="alice",
        now_us=world.clock.epoch * 1_000_000,
    )
    await reading

    snapshot = client.events[0].data
    assert (snapshot["view"], snapshot["view_error"]) == (None, "engine.load_failed")
    assert snapshot["run"]["load_error"] == "engine.load_failed"
    assert snapshot["run"]["allowed_actions"] == ["cancel"]
    assert client.kinds() == ["snapshot", "entry", "run", DONE]
    assert client.of_kind("entry")[0].data["kind"] == "log.run_finished"
    assert client.of_kind("entry")[0].data["patch"] == []
    assert client.last_seq == _head(world, run_id) and client.view is None
    assert client.header is not None
    assert (client.header["status"], client.header["allowed_actions"]) == ("cancelled", [])
    assert client.header["load_error"] == "engine.load_failed"


async def test_a_disconnected_request_ends_the_stream(world: World, hub: RunStreamHub) -> None:
    gone = False

    async def is_disconnected() -> bool:
        return gone

    run_id = _gated(world)
    client = StreamClient()
    reader = asyncio.create_task(
        pump(_stream(hub, run_id, is_disconnected=is_disconnected).frames(), client)
    )
    await poll_until_async(lambda: client.view is not None, timeout_s=TIMEOUT_S)
    gone = True
    async with asyncio.timeout(budget(POLL_S * 4)):
        await reader
    assert client.kinds() == ["snapshot"] and hub.watchers == 0


# ── Workspaces ──────────────────────────────────────────────────────────────


async def test_two_workspaces_with_one_run_id_never_see_each_other_s_rows(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    assert _gated(world, workspace_id=OTHER_WORKSPACE) == run_id
    _notes(world, run_id, 2, workspace_id=OTHER_WORKSPACE)
    clients = {WORKSPACE: StreamClient(), OTHER_WORKSPACE: StreamClient()}
    frames = {
        workspace: _stream(hub, run_id, workspace_id=workspace).frames() for workspace in clients
    }
    for workspace, client in clients.items():
        await read_until(
            frames[workspace], client, lambda c: c.view is not None, timeout_s=TIMEOUT_S
        )
    assert hub.watchers == 2

    _notes(world, run_id, 3, workspace_id=OTHER_WORKSPACE)
    other_head = _head(world, run_id, OTHER_WORKSPACE)
    await read_until(
        frames[OTHER_WORKSPACE],
        clients[OTHER_WORKSPACE],
        lambda c: c.last_seq == other_head,
        timeout_s=TIMEOUT_S,
    )
    _notes(world, run_id, 1)
    head = _head(world, run_id)
    await read_until(
        frames[WORKSPACE], clients[WORKSPACE], lambda c: c.last_seq == head, timeout_s=TIMEOUT_S
    )
    for stream in frames.values():
        await stream.aclose()

    assert clients[WORKSPACE].entries == [head]
    assert clients[OTHER_WORKSPACE].entries == list(range(other_head - 2, other_head + 1))
    assert clients[WORKSPACE].events[0].id == head - 1
    assert clients[OTHER_WORKSPACE].events[0].id == other_head - 3


# ── Caps and reservations ───────────────────────────────────────────────────


def _run(index: int) -> str:
    return f"{index:032x}"


def _viewer(index: int) -> Viewer:
    return Viewer(user_id=f"user-{index}")


def _refusal(refused: pytest.ExceptionInfo[CoralApiError]) -> tuple[int, str, dict[str, str]]:
    error = refused.value
    return error.status, error.error.code, error.headers


STREAM_LIMIT = (429, "stream_limit", {"Retry-After": "5"})
LOADS_BUSY = (503, "server_busy", {"Retry-After": "1"})
SHUTTING_DOWN = (503, "server_busy", {"Retry-After": "5"})


def _opened(hub: RunStreamHub, viewer: Viewer, workspace_id: int, run_id: str) -> Any:
    """A slot whose stream has loaded: it no longer counts as a load starting."""
    reservation = hub.reserve(viewer, workspace_id, run_id)
    share = reservation.take_opening_load()
    assert share is not None
    share.release()
    return reservation


async def test_a_ninth_stream_of_one_run_is_refused_while_another_user_connects(
    world: World, timed_hub: RunStreamHub, fake_time: FakeTime
) -> None:
    held = [_opened(timed_hub, ALICE, WORKSPACE, _run(1)) for _ in range(MAX_STREAMS_PER_RUN_USER)]

    with pytest.raises(CoralApiError) as refused:
        timed_hub.reserve(ALICE, WORKSPACE, _run(1))
    other = timed_hub.reserve(BOB, WORKSPACE, _run(1))
    held[0].release()
    held[0].release()

    assert MAX_STREAMS_PER_RUN_USER == 8
    assert _refusal(refused) == STREAM_LIMIT
    assert timed_hub.streams == MAX_STREAMS_PER_RUN_USER
    # The slot is free again, but the run's connects are spent until a second passes.
    with pytest.raises(CoralApiError) as too_fast:
        timed_hub.reserve(ALICE, WORKSPACE, _run(1))
    assert _refusal(too_fast) == STREAM_LIMIT
    fake_time.advance(1)
    timed_hub.reserve(ALICE, WORKSPACE, _run(1))
    other.release()


async def test_a_user_holds_at_most_32_streams_while_another_user_connects(
    timed_hub: RunStreamHub,
) -> None:
    for index in range(MAX_STREAMS_PER_USER):
        _opened(timed_hub, ALICE, WORKSPACE, _run(index // MAX_STREAMS_PER_RUN_USER))

    with pytest.raises(CoralApiError) as refused:
        timed_hub.reserve(ALICE, WORKSPACE, _run(99))
    timed_hub.reserve(BOB, WORKSPACE, _run(99))

    assert MAX_STREAMS_PER_USER == 32
    assert _refusal(refused) == STREAM_LIMIT
    # Another workspace is another share.
    timed_hub.reserve(ALICE, OTHER_WORKSPACE, _run(99))


async def test_the_process_holds_at_most_200_streams(timed_hub: RunStreamHub) -> None:
    for index in range(MAX_STREAMS):
        _opened(timed_hub, _viewer(index // MAX_STREAMS_PER_RUN_USER), WORKSPACE, _run(1))

    with pytest.raises(CoralApiError) as refused:
        timed_hub.reserve(_viewer(999), WORKSPACE, _run(2))

    assert MAX_STREAMS == 200
    assert _refusal(refused) == STREAM_LIMIT
    assert timed_hub.streams == MAX_STREAMS


async def test_connects_are_rate_limited_per_user_and_run(
    timed_hub: RunStreamHub, fake_time: FakeTime
) -> None:
    for _ in range(CONNECT_BURST):
        timed_hub.reserve(ALICE, WORKSPACE, _run(1)).release()

    with pytest.raises(CoralApiError) as refused:
        timed_hub.reserve(ALICE, WORKSPACE, _run(1))
    timed_hub.reserve(ALICE, WORKSPACE, _run(2)).release()
    fake_time.advance(1)
    timed_hub.reserve(ALICE, WORKSPACE, _run(1)).release()

    assert CONNECT_BURST == 8
    assert _refusal(refused) == STREAM_LIMIT
    assert timed_hub.streams == 0


async def test_a_user_starting_four_loads_is_busy_while_another_user_connects(
    world: World, threads: BoundedThreads
) -> None:
    run_ids = [_gated(world, key=f"load-{index}") for index in range(MAX_LOADS_PER_USER)]
    reads = _HeldReads(world)
    hub = RunStreamHub(bridge=reads, run_store=world.runs, threads=threads)
    try:
        reserved = [hub.reserve(ALICE, WORKSPACE, run_id) for run_id in run_ids]
        with pytest.raises(CoralApiError) as before_loading:
            hub.reserve(ALICE, WORKSPACE, run_ids[0])
        streams = [
            hub.stream(
                ALICE,
                WORKSPACE,
                run_id,
                cursor=NO_CURSOR,
                is_disconnected=never_disconnected,
                reservation=reservation,
            ).frames()
            for run_id, reservation in zip(run_ids, reserved, strict=True)
        ]
        loads = [asyncio.create_task(anext(frames)) for frames in streams]
        await poll_until_async(lambda: reads.waiting == MAX_LOADS_PER_USER, timeout_s=TIMEOUT_S)
        with pytest.raises(CoralApiError) as while_loading:
            hub.reserve(ALICE, WORKSPACE, run_ids[0])
        _opened(hub, BOB, WORKSPACE, run_ids[0]).release()
        reads.release.set()
        snapshots = await asyncio.gather(*loads)
        # Loaded streams free their loads: the user may start another.
        hub.reserve(ALICE, WORKSPACE, run_ids[0]).release()
        for frames in streams:
            await frames.aclose()
        for reservation in reserved:
            reservation.release()
    finally:
        reads.release.set()
        await hub.close()

    assert MAX_LOADS_PER_USER == 4
    assert _refusal(before_loading) == _refusal(while_loading) == LOADS_BUSY
    assert all(chunk.startswith("event: snapshot") for chunk in snapshots)
    assert hub.streams == 0


async def test_a_stream_dropped_during_its_load_keeps_the_load_counted_until_its_read_ends(
    world: World, threads: BoundedThreads
) -> None:
    run_ids = [_gated(world, key=f"drop-{index}") for index in range(MAX_LOADS_PER_USER)]
    reads = _HeldReads(world)
    hub = RunStreamHub(bridge=reads, run_store=world.runs, threads=threads)

    def admitted() -> bool:
        try:
            hub.reserve(ALICE, WORKSPACE, run_ids[0]).release()
        except CoralApiError:
            return False
        return True

    try:
        reserved = [hub.reserve(ALICE, WORKSPACE, run_id) for run_id in run_ids]
        loads = [
            asyncio.create_task(
                anext(
                    hub.stream(
                        ALICE,
                        WORKSPACE,
                        run_id,
                        cursor=NO_CURSOR,
                        is_disconnected=never_disconnected,
                        reservation=reservation,
                    ).frames()
                )
            )
            for run_id, reservation in zip(run_ids, reserved, strict=True)
        ]
        await poll_until_async(lambda: reads.waiting == MAX_LOADS_PER_USER, timeout_s=TIMEOUT_S)
        # Every client goes away mid-load; each response frees its slot.
        for load in loads:
            load.cancel()
        await asyncio.gather(*loads, return_exceptions=True)
        for reservation in reserved:
            reservation.release()
        dropped_while_folding = admitted()
        reads.release.set()
        await poll_until_async(admitted, timeout_s=TIMEOUT_S)
    finally:
        reads.release.set()
        await hub.close()

    # The folds kept their loads counted until their threads ended.
    assert not dropped_while_folding
    assert hub.streams == 0 and hub.watchers == 0


class _HeldReads:
    """The bridge's reads, each waiting for ``release`` once it starts."""

    def __init__(self, world: World) -> None:
        self._world = world
        self.release = threading.Event()
        self.waiting = 0
        self._lock = threading.Lock()

    def read(self, *, workspace_id: int, run_id: str) -> RunRead:
        with self._lock:
            self.waiting += 1
        self.release.wait(timeout=TIMEOUT_S)
        return self._world.bridge.read(workspace_id=workspace_id, run_id=run_id)


async def test_a_slot_released_or_lapsed_before_its_load_frees_the_load(
    world: World, threads: BoundedThreads
) -> None:
    hub = _hub(world, threads, lapse_s=0.01)
    try:
        for _ in range(MAX_LOADS_PER_USER):
            hub.reserve(ALICE, WORKSPACE, _run(1)).release()
        lapsing = [hub.reserve(ALICE, WORKSPACE, _run(2)) for _ in range(MAX_LOADS_PER_USER)]
        with pytest.raises(CoralApiError) as refused:
            hub.reserve(ALICE, WORKSPACE, _run(3))
        await poll_until_async(
            lambda: all(reservation.released for reservation in lapsing), timeout_s=TIMEOUT_S
        )
        hub.reserve(ALICE, WORKSPACE, _run(3)).release()
    finally:
        await hub.close()

    assert _refusal(refused) == LOADS_BUSY
    assert hub.streams == 0


async def test_no_stream_is_admitted_while_the_server_shuts_down(
    world: World, threads: BoundedThreads
) -> None:
    stopping = True
    hub = _hub(world, threads, shutting_down=lambda: stopping)
    try:
        with pytest.raises(CoralApiError) as refused:
            hub.reserve(ALICE, WORKSPACE, _run(1))
        stopping = False
        hub.reserve(ALICE, WORKSPACE, _run(1)).release()
    finally:
        await hub.close()

    assert _refusal(refused) == SHUTTING_DOWN
    assert hub.streams == 0


async def test_a_reservation_no_response_claims_lapses(
    world: World, threads: BoundedThreads
) -> None:
    hub = _hub(world, threads, lapse_s=0.01)
    try:
        claimed = hub.reserve(ALICE, WORKSPACE, _run(1))
        claimed.claim()
        unclaimed = hub.reserve(ALICE, WORKSPACE, _run(2))
        await poll_until_async(lambda: unclaimed.released, timeout_s=TIMEOUT_S)
        assert not claimed.released and hub.streams == 1
        claimed.release()
    finally:
        await hub.close()
    assert hub.streams == 0


# ── The response class ──────────────────────────────────────────────────────


class _Closing:
    """An endless body that records being closed."""

    def __init__(self) -> None:
        self.closed = False

    async def frames(self) -> AsyncIterator[str]:
        try:
            while True:
                yield "event: heartbeat\ndata: {}\n\n"
                await asyncio.sleep(0)
        finally:
            self.closed = True


async def _never_disconnects() -> dict[str, Any]:
    await asyncio.Event().wait()
    return {"type": "http.disconnect"}


@pytest.mark.parametrize("spec_version", ["2.0", "2.4"])
async def test_a_client_that_stops_reading_releases_its_slot_after_the_send_timeout(
    world: World, hub: RunStreamHub, spec_version: str
) -> None:
    body = _Closing()
    reservation = hub.reserve(ALICE, WORKSPACE, _run(1))
    sent: list[dict[str, Any]] = []

    async def stuck(message: dict[str, Any]) -> None:
        sent.append(message)
        if message["type"] == "http.response.body":
            await asyncio.Event().wait()

    response = CoralEventStream(body.frames(), reservation=reservation, send_timeout_s=0.05)
    scope = {"type": "http", "asgi": {"spec_version": spec_version}}
    async with asyncio.timeout(TIMEOUT_S):
        await response(scope, _never_disconnects, stuck)

    assert SEND_TIMEOUT_S == 30
    assert reservation.released and hub.streams == 0
    assert body.closed
    assert [message["type"] for message in sent] == ["http.response.start", "http.response.body"]
    headers = dict(sent[0]["headers"])
    assert headers[b"content-type"].startswith(b"text/event-stream")


async def test_a_stream_past_its_backstop_is_cut_and_releases_its_slot(
    world: World, hub: RunStreamHub
) -> None:
    body = _Closing()
    reservation = hub.reserve(ALICE, WORKSPACE, _run(1))

    async def accept(_message: dict[str, Any]) -> None:
        await asyncio.sleep(0)

    response = CoralEventStream(body.frames(), reservation=reservation, max_s=0.05)
    async with asyncio.timeout(TIMEOUT_S):
        await response(
            {"type": "http", "asgi": {"spec_version": "2.4"}}, _never_disconnects, accept
        )

    assert reservation.released and body.closed and hub.streams == 0


@pytest.mark.parametrize("spec_version", ["2.0", "2.4"])
async def test_a_body_that_raises_frees_its_slot(
    world: World, hub: RunStreamHub, spec_version: str
) -> None:
    closed: list[bool] = []

    async def failing() -> AsyncIterator[str]:
        try:
            yield "event: heartbeat\ndata: {}\n\n"
            raise RuntimeError("the store went away")
        finally:
            closed.append(True)

    async def accept(_message: dict[str, Any]) -> None:
        await asyncio.sleep(0)

    reservation = hub.reserve(ALICE, WORKSPACE, _run(1))
    response = CoralEventStream(failing(), reservation=reservation)
    with pytest.raises(RuntimeError, match="the store went away"):
        async with asyncio.timeout(TIMEOUT_S):
            await response(
                {"type": "http", "asgi": {"spec_version": spec_version}},
                _never_disconnects,
                accept,
            )

    assert reservation.released and closed == [True] and hub.streams == 0


async def test_a_disconnect_while_the_stream_waits_cancels_it_and_frees_its_slot(
    world: World, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    reservation = hub.reserve(ALICE, WORKSPACE, run_id)
    stream = hub.stream(
        ALICE,
        WORKSPACE,
        run_id,
        cursor=NO_CURSOR,
        is_disconnected=never_disconnected,
        reservation=reservation,
    )
    gone = asyncio.Event()
    bodies: list[bytes] = []

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body":
            bodies.append(message["body"])
            gone.set()

    async def receive() -> dict[str, Any]:
        await gone.wait()
        return {"type": "http.disconnect"}

    # Below ASGI 2.4, Starlette listens for the disconnect and cancels the body.
    response = CoralEventStream(stream.frames(), reservation=reservation)
    async with asyncio.timeout(TIMEOUT_S):
        await response({"type": "http", "asgi": {"spec_version": "2.0"}}, receive, send)

    assert len(bodies) == 1 and bodies[0].startswith(b"event: snapshot")
    assert reservation.released and hub.streams == 0 and hub.watchers == 0


# ── Over HTTP ───────────────────────────────────────────────────────────────


@pytest.fixture
async def http(world: World, hub: RunStreamHub) -> AsyncIterator[FastAPI]:
    api_threads = BoundedThreads(max_workers=4, thread_name_prefix="test-coral-api")
    spend_threads = BoundedThreads(max_workers=SPEND_THREADS, thread_name_prefix="test-spend")
    spend = SpendCache(_NoSpend(), spend_threads)
    app = _app()
    app.state.coral_runs_api = RunsApi(
        bridge=world.bridge, run_store=world.runs, spend=spend, in_flight=InFlight(api_threads)
    )
    app.state.coral_run_stream_hub = hub
    yield app
    spend.close()
    api_threads.close()
    spend_threads.close()


class _NoSpend:
    def run_spend(self, *, workspace_id: int, run_id: str) -> None:
        return None


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_runs_router(
            definitions=SqlWorkflowDefinitionStore(create_engine("sqlite://")),
            viewer_dependency=request_viewer(HEADER_AUTH),
            workspace_id_dependency=lambda: WORKSPACE,
        ),
        prefix="/v1/coral",
    )
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _as(viewer: Viewer, **headers: str) -> dict[str, str]:
    assert viewer.user_id is not None
    return {HEADER: viewer.user_id, **headers}


async def test_a_finished_run_streams_from_last_event_id_to_done_over_http(
    world: World, http: FastAPI, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    _finish(world, run_id)
    head = _head(world, run_id)

    async with _client(http) as client:
        response = await client.get(
            f"{RUNS}/{run_id}/stream",
            params={"after_seq": 0},
            headers=_as(ALICE, **{"Last-Event-ID": "3"}),
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    events = parse_body(response.text)
    assert [event.kind for event in events] == ["run", *["entry"] * (head - 3), DONE]
    assert [event.id for event in events[1:-1]] == list(range(4, head + 1))
    assert events[0].data["status"] == "completed"
    assert hub.streams == 0 and hub.watchers == 0


async def test_without_a_cursor_a_finished_run_is_its_snapshot_then_done(
    world: World, http: FastAPI
) -> None:
    run_id = _gated(world)
    _finish(world, run_id)

    async with _client(http) as client:
        response = await client.get(f"{RUNS}/{run_id}/stream", headers=_as(ALICE))

    events = parse_body(response.text)
    assert [event.kind for event in events] == ["snapshot", DONE]
    assert events[0].data["view"] == _view(world, run_id)


@pytest.mark.parametrize("case", ["other_user", "unknown", "malformed"])
async def test_a_stream_the_caller_may_not_see_is_the_run_404_and_takes_no_slot(
    world: World, http: FastAPI, hub: RunStreamHub, case: str
) -> None:
    run_id = {"other_user": _gated(world), "unknown": _run(7), "malformed": "NOT-A-RUN"}[case]

    async with _client(http) as client:
        response = await client.get(f"{RUNS}/{run_id}/stream", headers=_as(BOB))

    assert (response.status_code, response.content) == (404, NOT_FOUND)
    assert hub.streams == 0 and hub.watchers == 0


@pytest.mark.parametrize("after_seq", ["-1", str(2**63), "x"])
async def test_a_bad_after_seq_is_refused(world: World, http: FastAPI, after_seq: str) -> None:
    run_id = _gated(world)
    async with _client(http) as client:
        response = await client.get(
            f"{RUNS}/{run_id}/stream", params={"after_seq": after_seq}, headers=_as(ALICE)
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"
    assert after_seq not in response.text


async def test_a_stream_past_the_caps_is_429_with_retry_after(
    world: World, http: FastAPI, hub: RunStreamHub
) -> None:
    run_id = _gated(world)
    for _ in range(MAX_STREAMS_PER_RUN_USER):
        _opened(hub, ALICE, WORKSPACE, run_id)

    async with _client(http) as client:
        response = await client.get(f"{RUNS}/{run_id}/stream", headers=_as(ALICE))

    assert response.status_code == 429
    assert response.headers["retry-after"] == "5"
    assert response.json()["error"]["code"] == "stream_limit"


async def test_without_the_stream_hub_the_stream_is_the_run_404(world: World) -> None:
    run_id = _gated(world)
    async with _client(_app()) as client:
        refused = await client.get(f"{RUNS}/{run_id}/stream")
        response = await client.get(f"{RUNS}/{run_id}/stream", headers=_as(ALICE))
    assert refused.status_code == 401
    assert (response.status_code, response.content) == (404, NOT_FOUND)


# ── Through the server's lifespan ───────────────────────────────────────────


async def test_the_lifespan_publishes_the_stream_hub_and_closes_it(
    db_uri: str, tmp_path: Path
) -> None:
    server = coral_server(db_uri, tmp_path, server_plugins=[CORAL_SERVER_PLUGIN])
    world, run, _anchor, _prompt = gate_run(server.db_uri)
    try:
        async with _client(server.app) as client:
            async with coral_lifespan(server.app, server.services):
                hub = server.app.state.coral_run_stream_hub
                answered = await client.post(
                    f"{RUNS}/{run.id}/gates/approve:answer",
                    json={"visit_token": APPROVE_TOKEN, "outcome": "approve"},
                )
                streamed = await client.get(f"{RUNS}/{run.id}/stream")
    finally:
        pending_elicitations.reset_for_tests()
        elicitation_hooks.reset_for_tests()

    assert isinstance(hub, RunStreamHub)
    assert answered.status_code == 200, answered.text
    events = parse_body(streamed.text)
    assert [event.kind for event in events] == ["snapshot", DONE]
    assert events[0].data["run"]["status"] == "completed"
    assert hub.closed and hub.streams == 0
    stored = world.runs.get_run(run.id, workspace_id=DEFAULT_WORKSPACE_ID)
    assert stored is not None and stored.next_log_seq - 1 == events[0].id
