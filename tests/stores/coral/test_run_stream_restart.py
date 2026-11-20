"""The run stream on every DB lane: a client resumes across a server restart with no gap or repeat.

The first server process streams a run and stops; commits land while no server streams;
a restarted process serves the reconnect from ``Last-Event-ID``, and a commit made by
another process (no hook reaches this one) arrives through the watcher's poll.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from coral.api.stream import STREAM_THREADS, RunStreamHub, stream_cursor
from coral.bridge.executors import BoundedThreads
from coral.engine.projection import project
from coral.omni.protocols import Viewer
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.api._stream_client import DONE, StreamClient, never_disconnected, pump
from tests.coral.bridge._gates import (
    CHANGE_TOKEN,
    CHANGE_TOKEN_AGAIN,
    GATED,
    IMPLEMENT_AGAIN,
    answer,
    hand_off,
)
from tests.coral.bridge._world import WORKSPACE, World, run_spec, start
from tests.stores.coral._faults import fresh_process

ALICE = Viewer(user_id="alice")
TIMEOUT_S = budget(30)
# A short poll, so the commit no hook announces arrives quickly.
POLL_S = 0.05


@pytest.fixture
async def threads() -> AsyncIterator[BoundedThreads]:
    pool = BoundedThreads(max_workers=STREAM_THREADS, thread_name_prefix="test-coral-stream")
    yield pool
    pool.close()


def _head(world: World, run_id: str) -> int:
    run = world.runs.get_run(run_id, workspace_id=WORKSPACE)
    assert run is not None
    return run.next_log_seq - 1


def _serve(world: World, threads: BoundedThreads) -> RunStreamHub:
    """One server process's streams over ``world``'s stores, woken by its commits."""
    hub = RunStreamHub(bridge=world.bridge, run_store=world.runs, threads=threads, poll_s=POLL_S)
    world.runs.register_post_commit(hub.notify)
    return hub


async def test_a_client_resumes_across_a_restart_with_every_row_once(
    coral_db_uri: str, threads: BoundedThreads
) -> None:
    world = World.sql(coral_db_uri)
    run_id = start(world, GATED, spec=run_spec(start_key="restart"), start_key="restart").id
    first_head = _head(world, run_id)
    client = StreamClient()

    hub = _serve(world, threads)
    stream = hub.stream(
        ALICE,
        WORKSPACE,
        run_id,
        cursor=stream_cursor(None, None),
        is_disconnected=never_disconnected,
    )
    reader = asyncio.create_task(pump(stream.frames(), client))
    await poll_until_async(lambda: client.view is not None, timeout_s=TIMEOUT_S)
    await asyncio.to_thread(hand_off, world, run_id)
    await poll_until_async(lambda: client.last_seq == _head(world, run_id), timeout_s=TIMEOUT_S)
    # The server stops: the stream is cut where it waits, and the hub holds nothing.
    reader.cancel()
    await asyncio.gather(reader, return_exceptions=True)
    await hub.close()
    held = client.last_seq
    assert held is not None and held > first_head

    # Commits land while no server streams; the restarted process reads them from the DB.
    fresh_process(coral_db_uri)
    restarted = World.sql(coral_db_uri)
    await asyncio.to_thread(answer, restarted, run_id, CHANGE_TOKEN, "reject")
    await asyncio.to_thread(hand_off, restarted, run_id, IMPLEMENT_AGAIN)
    hub = _serve(restarted, threads)
    try:
        resumed = hub.stream(
            ALICE,
            WORKSPACE,
            run_id,
            cursor=stream_cursor(str(held), None),
            is_disconnected=never_disconnected,
        )
        reading = asyncio.create_task(pump(resumed.frames(), client))
        await poll_until_async(
            lambda: client.last_seq == _head(restarted, run_id), timeout_s=TIMEOUT_S
        )
        # Another process approves the change: no hook of this one sees that commit.
        other = World.sql(coral_db_uri)
        await asyncio.to_thread(answer, other, run_id, CHANGE_TOKEN_AGAIN, "approve")
        async with asyncio.timeout(TIMEOUT_S):
            await reading
    finally:
        await hub.close()

    final = project(restarted.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state)
    assert client.done and client.kinds()[-1] == DONE
    assert client.entries == list(range(first_head + 1, _head(restarted, run_id) + 1))
    assert client.view == resumed.view == final.model_dump(mode="json")
    assert final.status == "completed"
    assert client.header is not None and client.header["status"] == "completed"
