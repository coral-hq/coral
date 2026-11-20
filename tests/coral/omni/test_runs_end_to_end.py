"""The runs API end to end through the real server: authentication off, header auth and accounts.

A gate run started through the bridge is listed, read, started again with its start
key, followed live, paused, resumed and answered through the runs routes until its
stream ends with ``[DONE]``; a second run is cancelled. After the end, the stream is
read again from ``Last-Event-ID`` and from ``after_seq``. Opening the finished run marks
its run-end alert read and leaves every gate's alert. Another user's request on every
runs route gets the same 404 bytes and marks none of the owner's alerts read. A restart
on the same database resumes a stream with no gap or repeat, and in accounts mode a
deleted account's open stream ends at its next re-check and cannot reconnect.

Live streams are served by the app on the test's event loop with their events taken
as they are sent (an httpx client holds a body until the response ends), so they pass
through the route's own dependencies. A :class:`StreamClient` applies each event and
fails on a gap or a repeat.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message

from coral.api.stream import RECHECK_S, RunStreamHub
from coral.omni.protocols import Viewer
from coral.omni.server import coral_lifespan
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID
from omnigent.runtime import pending_elicitations
from omnigent.server import elicitation_hooks
from omnigent.server.auth import UnifiedAuthProvider
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.api._stream_client import (
    DONE,
    FakeTime,
    StreamClient,
    parse_body,
    pump,
    read_until,
)
from tests.coral.bridge._gates import APPROVE_TOKEN
from tests.coral.bridge._world import World
from tests.coral.omni._gate_server import (
    CORAL_SERVER_PLUGIN,
    AccountsServer,
    CoralServer,
    accounts_server,
    ack_run,
    coral_server,
    gate_run,
    inbox,
    pending_here,
    pending_prompts,
)

RUNS = "/v1/coral/runs"
HEADER = "X-Forwarded-Email"
NOT_FOUND = b'{"error":{"code":"not_found","message":"Run not found.","details":null}}'
APPROVE = {"visit_token": APPROVE_TOKEN, "outcome": "approve"}
# A hang guard for every wait on a stream.
TIMEOUT_S = budget(30)


# ── A stream served live ────────────────────────────────────────────────────


class _LiveStream:
    """
    One stream request the app serves on this event loop; :attr:`frames` yields each
    event as the app sends it. The client goes away when the stream is closed.
    """

    def __init__(self, app: FastAPI, path: str, headers: Mapping[str, str]) -> None:
        self.status: int | None = None
        self.headers: dict[str, str] = {}
        self._app = app
        self._path = path
        self._request_headers = headers
        self._started = asyncio.Event()
        self._gone = asyncio.Event()
        self._events: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.frames = self._frames()

    async def open(self) -> None:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "root_path": "",
            "path": self._path,
            "raw_path": self._path.encode(),
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                *(
                    (name.lower().encode("latin-1"), value.encode("latin-1"))
                    for name, value in self._request_headers.items()
                ),
            ],
        }
        self._task = asyncio.create_task(self._serve(scope))
        async with asyncio.timeout(TIMEOUT_S):
            await self._started.wait()

    async def close(self) -> None:
        self._gone.set()
        if self._task is not None:
            async with asyncio.timeout(TIMEOUT_S):
                await self._task

    async def _serve(self, scope: dict[str, Any]) -> None:
        try:
            await self._app(scope, self._receive, self._send)
        finally:
            self._started.set()
            self._events.put_nowait(None)

    async def _receive(self) -> Message:
        await self._gone.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = {
                name.decode("latin-1"): value.decode("latin-1")
                for name, value in message["headers"]
            }
            self._started.set()
        elif message["type"] == "http.response.body" and message.get("body"):
            self._events.put_nowait(message["body"].decode())

    async def _frames(self) -> AsyncIterator[str]:
        while (event := await self._events.get()) is not None:
            yield event


@asynccontextmanager
async def _live(
    app: FastAPI, run_id: str, headers: Mapping[str, str]
) -> AsyncIterator[_LiveStream]:
    stream = _LiveStream(app, f"{RUNS}/{run_id}/stream", headers)
    await stream.open()
    try:
        yield stream
    finally:
        await stream.close()


async def _to_end(stream: _LiveStream, client: StreamClient) -> None:
    async with asyncio.timeout(TIMEOUT_S):
        await pump(stream.frames, client)


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


def _hub(app: FastAPI) -> RunStreamHub:
    hub = app.state.coral_run_stream_hub
    assert isinstance(hub, RunStreamHub)
    return hub


def _head(world: World, run_id: str) -> int:
    run = world.runs.get_run(run_id, workspace_id=DEFAULT_WORKSPACE_ID)
    assert run is not None
    return run.next_log_seq - 1


def _start_request(world: World, run_id: str, start_key: str, **changes: Any) -> dict[str, Any]:
    """The start request the run's stored spec records, with ``changes``."""
    state, _version = world.runs.load_run_state(run_id, workspace_id=DEFAULT_WORKSPACE_ID)
    spec = state.spec
    return {
        "workflow_id": spec.workflow_id,
        "start_key": start_key,
        "host_id": spec.host_id,
        "repo_path": spec.repo_path,
        "request": spec.request_preview,
        "max_activations": spec.max_activations,
        **changes,
    }


def _run_routes(run_id: str) -> list[tuple[str, str, dict[str, Any] | None]]:
    """Every runs route that names a run, with a body each POST accepts."""
    return [
        ("GET", f"{RUNS}/{run_id}", None),
        ("GET", f"{RUNS}/{run_id}/graph", None),
        ("GET", f"{RUNS}/{run_id}/log", None),
        ("GET", f"{RUNS}/{run_id}/stream", None),
        ("GET", f"{RUNS}/{run_id}/outcome", None),
        ("POST", f"{RUNS}/{run_id}:pause", {}),
        ("POST", f"{RUNS}/{run_id}:resume", {}),
        ("POST", f"{RUNS}/{run_id}:cancel", {}),
        ("POST", f"{RUNS}/{run_id}/activations/{'a' * 32}:retry", {}),
        ("POST", f"{RUNS}/{run_id}/gates/approve:answer", APPROVE),
    ]


def _actions(body: dict[str, Any]) -> tuple[str, str | None, list[str]]:
    return body["status"], body["pause_reason"], body["allowed_actions"]


def _entries(events: list[Any]) -> list[dict[str, Any]]:
    return [event.data for event in events if event.kind == "entry"]


# ── The owner's run, start to end ───────────────────────────────────────────


async def _follow_a_run(
    app: FastAPI,
    db_uri: str,
    *,
    user: str | None,
    generation: str | None,
    owner: Mapping[str, str],
    intruder: Mapping[str, str],
    foreign_run: str | None = None,
) -> None:
    """
    The owner's run through every runs route, and another user refused on each.

    :param foreign_run: The run the intruder tries; the owner's run when not given.
    """
    world, run, anchor, prompt = gate_run(
        db_uri, "gate-a", user=user, account_generation=generation
    )
    _, other, _, _ = gate_run(db_uri, "gate-b", user=user, account_generation=generation)
    target = foreign_run or run.id
    hub = _hub(app)

    async with _client(app) as client:
        # Another user: one 404 body on every route, and no slot taken.
        refused = [
            await client.request(method, path, json=body, headers=intruder)
            for method, path, body in _run_routes(target)
        ]
        intruder_list = await client.get(RUNS, headers=intruder)
        assert hub.streams == 0

        listed = await client.get(RUNS, headers=owner)
        detail = await client.get(f"{RUNS}/{run.id}", headers=owner)
        await poll_until_async(lambda: pending_here(anchor, prompt), timeout_s=TIMEOUT_S)
        [published] = await pending_prompts(client, anchor, owner)
        at_gate = await ack_run(client, run.id, owner)
        feed_at_gate = await inbox(client, owner)
        replayed = await client.post(
            RUNS, json=_start_request(world, run.id, "gate-a"), headers=owner
        )
        conflict = await client.post(
            RUNS,
            json=_start_request(world, run.id, "gate-a", request="Another request"),
            headers=owner,
        )

        live = StreamClient()
        async with _live(app, run.id, owner) as stream:
            await read_until(
                stream.frames, live, lambda c: c.view is not None, timeout_s=TIMEOUT_S
            )
            snapshot = live.events[0]
            paused = await client.post(f"{RUNS}/{run.id}:pause", json={}, headers=owner)
            await read_until(
                stream.frames,
                live,
                lambda c: c.header is not None and c.header["status"] == "paused",
                timeout_s=TIMEOUT_S,
            )
            resumed = await client.post(f"{RUNS}/{run.id}:resume", json={}, headers=owner)
            await read_until(
                stream.frames,
                live,
                lambda c: c.header is not None and c.header["status"] == "running",
                timeout_s=TIMEOUT_S,
            )
            answered = await client.post(
                f"{RUNS}/{run.id}/gates/approve:answer", json=APPROVE, headers=owner
            )
            repeated = await client.post(
                f"{RUNS}/{run.id}/gates/approve:answer", json=APPROVE, headers=owner
            )
            await _to_end(stream, live)

        final = (await client.get(f"{RUNS}/{run.id}", headers=owner)).json()
        intruder_acked = await ack_run(client, target, intruder)
        feed_at_end = await inbox(client, owner)
        end_acked = await ack_run(client, run.id, owner)
        feed_after_ack = await inbox(client, owner)
        # After the end: from the snapshot's seq, by header (which beats after_seq) and by query.
        by_header = await client.get(
            f"{RUNS}/{run.id}/stream",
            params={"after_seq": 0},
            headers={**owner, "Last-Event-ID": str(snapshot.id)},
        )
        by_query = await client.get(
            f"{RUNS}/{run.id}/stream", params={"after_seq": snapshot.id}, headers=owner
        )
        log = (
            await client.get(f"{RUNS}/{run.id}/log", params={"limit": 100}, headers=owner)
        ).json()
        graph = await client.get(f"{RUNS}/{run.id}/graph", headers=owner)
        revalidated = await client.get(
            f"{RUNS}/{run.id}/graph", headers={**owner, "If-None-Match": graph.headers["etag"]}
        )
        stubs = [
            await client.get(f"{RUNS}/{run.id}/outcome", headers=owner),
            await client.post(
                f"{RUNS}/{run.id}/activations/{'a' * 32}:retry", json={}, headers=owner
            ),
            await client.post(f"{RUNS}:preflight", json={}, headers=owner),
        ]

        cancelled = await client.post(f"{RUNS}/{other.id}:cancel", json={}, headers=owner)
        cancelled_again = await client.post(f"{RUNS}/{other.id}:cancel", json={}, headers=owner)
        pause_cancelled = await client.post(f"{RUNS}/{other.id}:pause", json={}, headers=owner)
        ended = {
            status: [
                item["run_id"]
                for item in (
                    await client.get(RUNS, params={"status": status}, headers=owner)
                ).json()["data"]
            ]
            for status in ("running", "completed", "cancelled")
        }

    assert [(response.status_code, response.content) for response in refused] == [
        (404, NOT_FOUND)
    ] * len(_run_routes(target))
    assert intruder_list.status_code == 200
    assert target not in [item["run_id"] for item in intruder_list.json()["data"]]

    # The intruder changed nothing: both runs were running before the owner acted.
    assert listed.status_code == 200, listed.text
    assert {item["run_id"]: _actions(item) for item in listed.json()["data"]} == {
        run.id: ("running", None, ["pause", "cancel"]),
        other.id: ("running", None, ["pause", "cancel"]),
    }
    assert detail.status_code == 200, detail.text
    assert _actions(detail.json()) == ("running", None, ["pause", "cancel"])
    assert [
        (gate["node_id"], gate["token"], gate["elicitation_id"], gate["outcomes"])
        for gate in detail.json()["gates"]
    ] == [("approve", APPROVE_TOKEN, prompt, ["approve", "reject"])]
    # The gate's context is the text its published prompt asks.
    [gate] = detail.json()["gates"]
    assert gate["context"] == published["params"]["message"]
    assert "Ship it?" in gate["context"]

    # Opening a run marks only its low-priority alerts read: an open gate waits for its
    # answer, and another user's request marks nothing.
    assert [
        (response.status_code, response.json())
        for response in (at_gate, intruder_acked, end_acked)
    ] == [(200, {"acked": 0}), (200, {"acked": 0}), (200, {"acked": 1})]
    assert sorted((alert["run_id"], alert["kind"]) for alert in feed_at_gate) == sorted(
        [(run.id, "gate"), (other.id, "gate")]
    )
    assert [(alert["run_id"], alert["kind"]) for alert in feed_at_end] == [
        (other.id, "gate"),
        (run.id, "run_completed"),
    ]
    assert [(alert["run_id"], alert["kind"]) for alert in feed_after_ack] == [(other.id, "gate")]

    # The same start key and request answer the run it started; another request is refused.
    assert (replayed.status_code, replayed.json()["run_id"]) == (200, run.id), replayed.text
    assert replayed.headers["location"] == f"{RUNS}/{run.id}"
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "start_key_conflict")

    assert (stream.status, stream.headers["cache-control"]) == (200, "no-store")
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert _actions(paused.json()) == ("paused", "user", ["resume", "cancel"]), paused.text
    assert _actions(resumed.json()) == ("running", None, ["pause", "cancel"]), resumed.text
    assert (answered.status_code, answered.json()) == (200, {"result": "accepted"})
    assert (repeated.status_code, repeated.json()) == (200, {"result": "duplicate"})
    # The live stream: every row once, in order, then the finished header and [DONE].
    assert live.done and live.kinds()[0] == "snapshot" and "resync" not in live.kinds()
    assert live.header is not None
    assert (live.header["status"], live.header["allowed_actions"]) == ("completed", [])
    assert live.last_seq == final["head_seq"]
    assert live.view == final["view"]

    replay_events = parse_body(by_header.text)
    assert [event.kind for event in replay_events] == [
        "run",
        *["entry"] * (final["head_seq"] - snapshot.id),
        DONE,
    ]
    assert replay_events == parse_body(by_query.text)
    # The replay holds exactly the rows the live client took after its snapshot.
    assert _entries(replay_events) == _entries(live.events)
    resumed_client = StreamClient(view=snapshot.data["view"], last_seq=snapshot.id)
    for event in by_header.text.split("\n\n")[:-1]:
        resumed_client.take(f"{event}\n\n")
    assert resumed_client.view == final["view"]

    assert [row["seq"] for row in log["data"]] == list(range(1, final["head_seq"] + 1))
    assert {"engine.start_run", "engine.pause_run", "engine.resume_run", "engine.answer_gate"} <= {
        row["kind"] for row in log["data"]
    }
    assert graph.status_code == 200 and graph.headers["etag"] == f'"{final["version_id"]}"'
    assert revalidated.status_code == 304
    assert [(response.status_code, response.json()["error"]["code"]) for response in stubs] == [
        (501, "not_implemented")
    ] * 3

    assert _actions(cancelled.json()) == ("cancelled", None, []), cancelled.text
    assert _actions(cancelled_again.json()) == ("cancelled", None, [])
    assert (pause_cancelled.status_code, pause_cancelled.json()["error"]["details"]) == (
        409,
        {"status": "cancelled", "pause_reason": None},
    )
    assert ended == {"running": [], "completed": [run.id], "cancelled": [other.id]}
    assert hub.streams == 0


def _forget_prompts() -> None:
    # Prompts and the verdict handler outlive a lifespan in this process's registries.
    pending_elicitations.reset_for_tests()
    elicitation_hooks.reset_for_tests()


@pytest.fixture
def auth_off_server(db_uri: str, tmp_path: Path) -> Iterator[CoralServer]:
    yield coral_server(db_uri, tmp_path, server_plugins=[CORAL_SERVER_PLUGIN])
    _forget_prompts()


@pytest.fixture
def header_server(db_uri: str, tmp_path: Path) -> Iterator[CoralServer]:
    yield coral_server(
        db_uri,
        tmp_path,
        auth_provider=UnifiedAuthProvider(
            source="header", local_single_user=False, header_name=HEADER
        ),
        permission_store=SqlAlchemyPermissionStore(db_uri),
        server_plugins=[CORAL_SERVER_PLUGIN],
    )
    _forget_prompts()


async def test_the_local_user_follows_a_run_to_its_end_and_never_reaches_another_owner_s(
    auth_off_server: CoralServer,
) -> None:
    server = auth_off_server
    async with coral_lifespan(server.app, server.services):
        # Every request is the local user's: the other user is a run's recorded owner.
        _, foreign, _, _ = gate_run(server.db_uri, "foreign", user="alice@example.com")
        await _follow_a_run(
            server.app,
            server.db_uri,
            user=None,
            generation=None,
            owner={},
            intruder={},
            foreign_run=foreign.id,
        )


async def test_the_owner_follows_a_run_to_its_end_and_another_user_is_refused_everywhere(
    header_server: CoralServer,
) -> None:
    server = header_server
    async with coral_lifespan(server.app, server.services):
        await _follow_a_run(
            server.app,
            server.db_uri,
            user="alice@example.com",
            generation=None,
            owner={HEADER: "alice@example.com"},
            intruder={HEADER: "bob@example.com"},
        )


async def test_a_restart_resumes_a_stream_from_last_event_id_with_no_gap_or_repeat(
    auth_off_server: CoralServer,
) -> None:
    server = auth_off_server
    world, run, _anchor, _prompt = gate_run(server.db_uri, "gate-r")
    client = StreamClient()

    async with _client(server.app) as http:
        stream = _LiveStream(server.app, f"{RUNS}/{run.id}/stream", {})
        try:
            async with coral_lifespan(server.app, server.services):
                await stream.open()
                await read_until(
                    stream.frames, client, lambda c: c.view is not None, timeout_s=TIMEOUT_S
                )
                paused = await http.post(f"{RUNS}/{run.id}:pause", json={})
                await read_until(
                    stream.frames,
                    client,
                    lambda c: c.header is not None and c.header["status"] == "paused",
                    timeout_s=TIMEOUT_S,
                )
            # The server went down: its open stream ended without [DONE].
            await _to_end(stream, client)
        finally:
            await stream.close()
        held = client.last_seq
        assert held is not None and not client.done
        # While no server runs, another process resumes the run.
        world.bridge.resume_run(workspace_id=DEFAULT_WORKSPACE_ID, run_id=run.id, actor="local")
        missed = _head(world, run.id)

        async with coral_lifespan(server.app, server.services):
            async with _live(server.app, run.id, {"Last-Event-ID": str(held)}) as stream:
                reconnected = len(client.events)
                await read_until(
                    stream.frames,
                    client,
                    lambda c: c.header is not None and c.header["status"] == "running",
                    timeout_s=TIMEOUT_S,
                )
                answered = await http.post(f"{RUNS}/{run.id}/gates/approve:answer", json=APPROVE)
                await _to_end(stream, client)
            final = (await http.get(f"{RUNS}/{run.id}")).json()

    assert paused.status_code == 200 and answered.status_code == 200, answered.text
    assert missed > held
    # The reconnect opened with the header, then every row after the held seq.
    assert client.kinds()[reconnected] == "run"
    assert "snapshot" not in client.kinds()[reconnected:] and "resync" not in client.kinds()
    assert client.entries == list(range(client.events[0].id + 1, final["head_seq"] + 1))
    assert client.done and client.view == final["view"]


# ── Accounts mode ───────────────────────────────────────────────────────────


@pytest.fixture
def accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, coral_policy_registry: None
) -> Iterator[AccountsServer]:
    try:
        with accounts_server(tmp_path, monkeypatch) as built:
            yield built
    finally:
        _forget_prompts()


def _cookie(client: TestClient) -> dict[str, str]:
    """The client's sign-in as a header, for requests made outside it."""
    return {"Cookie": "; ".join(f"{name}={value}" for name, value in client.cookies.items())}


def _alice_generation(accounts: AccountsServer) -> tuple[str, str]:
    account_store = accounts.stores["account_store"]
    return account_store.storage_location, account_store.get_user("alice").account_generation


def _on_server_loop(accounts: AccountsServer, scenario: Any, *args: Any) -> Any:
    """Run ``scenario`` on the event loop that runs the app's lifespan and streams."""
    portal = accounts.admin.portal
    assert portal is not None
    return portal.call(scenario, *args)


def test_the_owner_follows_a_run_to_its_end_on_an_accounts_server(
    accounts: AccountsServer,
) -> None:
    db_uri, generation = _alice_generation(accounts)
    _on_server_loop(
        accounts,
        lambda: _follow_a_run(
            accounts.admin.app,
            db_uri,
            user="alice",
            generation=generation,
            owner=_cookie(accounts.alice),
            intruder=_cookie(accounts.admin),
        ),
    )


def test_a_deleted_account_s_stream_ends_at_its_next_recheck_and_cannot_reconnect(
    accounts: AccountsServer,
) -> None:
    db_uri, generation = _alice_generation(accounts)
    _world, run, _anchor, _prompt = gate_run(
        db_uri, "gate-d", user="alice", account_generation=generation
    )
    app = accounts.admin.app
    alice, admin = _cookie(accounts.alice), _cookie(accounts.admin)
    hub = _hub(app)
    fake_time = FakeTime()
    checks: list[bool] = []
    account_still_valid = hub.still_valid

    def still_valid(viewer: Viewer) -> bool:
        valid = account_still_valid(viewer)
        checks.append(valid)
        return valid

    hub.clock, hub.still_valid = fake_time, still_valid

    async def scenario() -> tuple[StreamClient, httpx.Response, httpx.Response]:
        client = StreamClient()
        async with _client(app) as http:
            async with _live(app, run.id, alice) as stream:
                await read_until(
                    stream.frames, client, lambda c: c.view is not None, timeout_s=TIMEOUT_S
                )
                # A minute on, the account still checks out: the stream goes on.
                fake_time.advance(RECHECK_S)
                await read_until(
                    stream.frames,
                    client,
                    lambda c: c.kinds()[-1] == "heartbeat",
                    timeout_s=TIMEOUT_S,
                )
                deleted = await http.delete("/auth/users/alice", headers=admin)
                fake_time.advance(RECHECK_S)
                await _to_end(stream, client)
            reconnect = await http.get(
                f"{RUNS}/{run.id}/stream",
                headers={**alice, "Last-Event-ID": str(client.last_seq)},
            )
        return client, deleted, reconnect

    client, deleted, reconnect = _on_server_loop(accounts, scenario)

    assert deleted.status_code == 204, deleted.text
    # One check passed, and the first after the deletion ended the stream.
    assert checks == [True, False]
    assert client.kinds() == ["snapshot", "heartbeat"] and not client.done
    assert reconnect.status_code == 401, reconnect.text
    assert reconnect.json()["error"]["code"] == "unauthenticated"
    assert hub.streams == 0
