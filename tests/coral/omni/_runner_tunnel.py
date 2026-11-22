"""A real server with runner tunnels and a host store, for Coral's runner-loss L3 tests.

The server is Omnigent's own app. A runner tunnel connects and drops through its
``/v1/runners/{runner_id}/tunnel`` route (one ``ApplicationCommunicator`` per tunnel,
whose frames are pumped into an in-process runner app), so a close runs the server's
own disconnect handling: it clears the runner's liveness stamp, then holds a mid-turn
session's turn while the session's host row is offline, or fails it with
``runner_disconnected`` while the host is online.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest_asyncio
from asgiref.testing import ApplicationCommunicator
from fastapi import FastAPI

from omnigent.runner.app import create_runner_app
from omnigent.runtime import init as init_runtime
from omnigent.runtime import set_runner_router
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server import shutdown_state
from omnigent.server.app import create_app
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.runner.helpers import NullServerClient
from tests.server.integration.test_sessions_tunnel_three_layer import (
    _TEST_HARNESS_NAME,
    FakeProcessManager,
    _connect_runner_tunnel,
    _forward_requests_to_runner,
    _send_hello_and_wait,
)

# Background tasks of the server's disconnect handling and stream relays, which
# the app's lifespan would own.
_SERVER_TASK_PREFIXES = ("runner-disconnect-grace-", "runner-relay-")


@dataclass
class TunnelServer:
    """The server, its conversation and host stores, and the runner app its tunnels reach."""

    app: FastAPI
    store: SqlAlchemyConversationStore
    hosts: HostStore
    runner_app: FastAPI

    async def runner_stamp(self, session_id: str) -> tuple[str | None, int | None] | None:
        """The session's bound runner and liveness stamp, as the server stored them."""
        return await asyncio.to_thread(self.store.get_runner_liveness, session_id)

    def connected(self, runner_id: str) -> bool:
        return self.app.state.tunnel_registry.get(runner_id) is not None


@dataclass
class RunnerTunnel:
    """One runner's open tunnel to the server."""

    server: TunnelServer
    runner_id: str
    communicator: ApplicationCommunicator
    forwarder: asyncio.Task[None]
    closed: bool = False

    async def close(self) -> None:
        """Drop the tunnel as a runner's socket closes, and wait until the server sees it."""
        if self.closed:
            return
        self.closed = True
        await self.communicator.send_input({"type": "websocket.disconnect", "code": 1006})
        with contextlib.suppress(asyncio.TimeoutError, Exception):
            await self.communicator.wait(timeout=budget(5))
        self.forwarder.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self.forwarder
        await poll_until_async(
            lambda: not self.server.connected(self.runner_id), timeout_s=budget(10)
        )


@contextlib.asynccontextmanager
async def runner_tunnel(server: TunnelServer, runner_id: str) -> AsyncIterator[RunnerTunnel]:
    """Connect ``runner_id``'s tunnel; it is closed at the end unless the caller closed it."""
    communicator = await _connect_runner_tunnel(server.app, runner_id)
    await _send_hello_and_wait(communicator, server.app, runner_id, harnesses=[_TEST_HARNESS_NAME])
    forwarder = asyncio.create_task(
        _forward_requests_to_runner(communicator, server.runner_app),
        name=f"coral-test-tunnel-{runner_id}",
    )
    tunnel = RunnerTunnel(server, runner_id, communicator, forwarder)
    try:
        yield tunnel
    finally:
        await tunnel.close()


@pytest_asyncio.fixture()
async def tunnel_server(tmp_path: Path) -> AsyncIterator[TunnelServer]:
    """The server over one SQLite file, with a host store; no runner is connected yet."""
    db_uri = f"sqlite:///{tmp_path / 'omnigent.db'}"
    agent_store = SqlAlchemyAgentStore(db_uri)
    store = SqlAlchemyConversationStore(db_uri)
    file_store = SqlAlchemyFileStore(db_uri)
    hosts = HostStore(db_uri)
    artifact_store = LocalArtifactStore(str(tmp_path / "artifacts"))
    agent_cache = AgentCache(artifact_store=artifact_store, cache_dir=tmp_path / "cache")
    init_runtime(
        conversation_store=store,
        agent_store=agent_store,
        agent_cache=agent_cache,
        file_store=file_store,
        artifact_store=artifact_store,
    )
    fake_pm = FakeProcessManager()

    async def resolve_spec(agent_id: str, session_id: str | None = None) -> Any:
        record = agent_store.get(agent_id)
        return None if record is None else agent_cache.load(agent_id, record.bundle_location).spec

    runner_app = create_runner_app(
        process_manager=fake_pm,
        spec_resolver=resolve_spec,
        server_client=NullServerClient(),  # type: ignore[arg-type]
    )
    app = create_app(
        agent_store=agent_store,
        file_store=file_store,
        conversation_store=store,
        artifact_store=artifact_store,
        agent_cache=agent_cache,
        host_store=hosts,
    )
    set_runner_router(app.state.runner_router)
    try:
        yield TunnelServer(app=app, store=store, hosts=hosts, runner_app=runner_app)
    finally:
        tasks = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name().startswith(_SERVER_TASK_PREFIXES)
        ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        with contextlib.suppress(Exception):
            await app.state.runner_router.aclose()
        await fake_pm.shutdown()
        set_runner_router(None)
        shutdown_state.reset_for_tests()
