"""The Coral plugin mounts the workflows and workflow Inbox routers under /v1/coral."""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

import coral.api.run_service as run_service
from coral.api.errors import CoralApiError
from coral.api.run_service import InFlight
from coral.api.workflows import MAX_SIMULATIONS, MAX_SIMULATIONS_PER_USER
from coral.db.enum_codecs import AlertKind
from coral.db.migrate import ensure_coral_schema
from coral.omni.protocols import Viewer
from coral.omni.server.plugin import register, simulations_lifespan
from coral.stores.alerts import SqlAlchemyAlertStore
from coral.stores.runs import SqlAlchemyCoralRunStore
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID, workspace_scope
from omnigent.process_logging import DATA_DIR_ENV_VAR
from omnigent.server.auth import UnifiedAuthProvider
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.workflow_builders import fixture_text
from tests.stores.coral._alerts import (
    OTHER_WORKSPACE,
    alert_draft,
    commit_alert_changes,
    start_owned_run,
)


def _plugin_app(*, auth_provider: object) -> FastAPI:
    """An app with the plugin's routers only: no lifespan, so no operational stores."""
    services = cast(
        Any, SimpleNamespace(host_sharded=False, server_config={}, auth_provider=auth_provider)
    )
    app = FastAPI()
    for router, prefix, tags in register(services).routers:
        app.include_router(router, prefix=prefix, tags=tags)
    return app


def test_plugin_mounts_workflows_router_backed_by_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    client = TestClient(_plugin_app(auth_provider=None))

    validated = client.post("/v1/coral/workflows:validate", json={"yaml": fixture_text("minimal")})
    assert validated.json()["compiled"]["workflow_id"] == "demo"
    saved = client.post("/v1/coral/workflows", json={"yaml": fixture_text("minimal")}).json()
    [template] = client.get("/v1/coral/templates").json()
    used = client.post(f"/v1/coral/templates/{template['id']}:use", json={})
    assert used.status_code == 201, used.text
    assert sorted(item["id"] for item in client.get("/v1/coral/workflows").json()) == sorted(
        [saved["id"], used.json()["id"]]
    )
    assert (tmp_path / "coral.db").exists()


async def test_the_plugin_simulates_only_while_its_lifespan_holds_the_simulate_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    services = cast(Any, SimpleNamespace(host_sharded=False, server_config={}, auth_provider=None))
    # The server enters the hooks the plugin registers.
    assert simulations_lifespan in register(services).lifespan_hooks
    app = _plugin_app(auth_provider=None)
    body = {"yaml": fixture_text("minimal")}
    simulate = "/v1/coral/workflows:simulate"
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        before = await client.post(simulate, json=body)
        async with simulations_lifespan(app, services):
            in_flight = app.state.coral_simulations
            during = await client.post(simulate, json=body)
        after = await client.post(simulate, json=body)

    for refused in (before, after):
        assert (refused.status_code, refused.json()["error"]["code"]) == (503, "server_busy")
    assert during.status_code == 200, during.text
    assert during.json()["simulation"]["outcome"] == "completed"
    assert isinstance(in_flight, InFlight) and in_flight.closed


async def test_the_plugins_simulate_pool_takes_one_per_user_and_four_in_all(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=run_service.__name__)
    services = cast(Any, SimpleNamespace(host_sharded=False, server_config={}, auth_provider=None))
    app = FastAPI()
    release = threading.Event()
    held: list[asyncio.Task[bool]] = []
    assert (MAX_SIMULATIONS_PER_USER, MAX_SIMULATIONS) == (1, 4)

    async with simulations_lifespan(app, services):
        pool: InFlight = app.state.coral_simulations

        async def hold(*users: str) -> None:
            for user in users:
                held.append(asyncio.create_task(pool.run(Viewer(user), release.wait, budget(30))))
            await poll_until_async(lambda: pool.in_flight == len(held), timeout_s=budget(10))

        try:
            await hold("alice")
            # The pool has room, but not for a second of one user's.
            with pytest.raises(CoralApiError) as alices_second:
                await pool.run(Viewer("alice"), lambda: None)
            await hold("bob", "carol", "dave")
            with pytest.raises(CoralApiError) as a_fifth:
                await pool.run(Viewer("erin"), lambda: None)
        finally:
            release.set()
            finished = await asyncio.gather(*held)

    assert (alices_second.value.status, a_fifth.value.status) == (503, 503)
    assert finished == [True] * MAX_SIMULATIONS
    messages = [record.getMessage() for record in caplog.records]
    refusals = [message for message in messages if "refused" in message]
    assert len(refusals) == 2
    assert all(message.startswith("Coral refused a simulation:") for message in refusals)


def _in_workspace(app: ASGIApp, workspace_id: int) -> ASGIApp:
    """``app`` behind a multi-tenant deployment's middleware binding each request's workspace."""

    async def scoped(scope: Scope, receive: Receive, send: Send) -> None:
        with workspace_scope(workspace_id):
            await app(scope, receive, send)

    return scoped


def test_plugin_mounts_the_inbox_behind_the_servers_authentication_and_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_uri: str
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    auth = UnifiedAuthProvider(
        source="header", local_single_user=False, header_name="X-Forwarded-Email"
    )
    app = _plugin_app(auth_provider=auth)
    client = TestClient(app)
    signed_in = {"X-Forwarded-Email": "alice"}

    assert client.get("/v1/coral/inbox").status_code == 401
    # Before the lifespan publishes the alert store there is no feed.
    for response in (
        client.get("/v1/coral/inbox", headers=signed_in),
        client.post(f"/v1/coral/inbox/{'a' * 32}/ack", headers=signed_in, json={}),
    ):
        assert (response.status_code, response.json()) == (
            404,
            {
                "error": {
                    "code": "not_found",
                    "message": "Coral inbox is not available",
                    "details": None,
                }
            },
        )

    # Once the store is published, each request reads only its own workspace's alerts.
    ensure_coral_schema(db_uri)
    runs = SqlAlchemyCoralRunStore(db_uri)
    alerts: list[str] = []
    for workspace_id in (DEFAULT_WORKSPACE_ID, OTHER_WORKSPACE):
        run = start_owned_run(runs, "inbox", workspace_id=workspace_id)
        draft = alert_draft(run, AlertKind.PAUSE, "1")
        commit_alert_changes(runs, run, raises=[draft])
        alerts.append(draft.id)
    app.state.coral_alert_store = SqlAlchemyAlertStore(db_uri)
    first, second = alerts
    for workspace_id, own, other in (
        (DEFAULT_WORKSPACE_ID, first, second),
        (OTHER_WORKSPACE, second, first),
    ):
        scoped = TestClient(_in_workspace(app, workspace_id))
        listed = scoped.get("/v1/coral/inbox", headers=signed_in).json()["data"]
        assert [item["alert_id"] for item in listed] == [own]
        refused = scoped.post(f"/v1/coral/inbox/{other}/ack", headers=signed_in, json={})
        assert refused.status_code == 404


def test_plugin_scopes_workflows_to_the_signed_in_caller_and_the_requests_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    auth = UnifiedAuthProvider(
        source="header", local_single_user=False, header_name="X-Forwarded-Email"
    )
    app = _plugin_app(auth_provider=auth)
    alice, bob = {"X-Forwarded-Email": "alice"}, {"X-Forwarded-Email": "bob"}
    yaml = {"yaml": fixture_text("minimal")}
    assert TestClient(app).post("/v1/coral/workflows", json=yaml).status_code == 401

    home, other = TestClient(app), TestClient(_in_workspace(app, OTHER_WORKSPACE))
    saved = home.post("/v1/coral/workflows", json=yaml, headers=alice).json()

    assert [item["id"] for item in home.get("/v1/coral/workflows", headers=alice).json()] == [
        saved["id"]
    ]
    assert home.get("/v1/coral/workflows", headers=bob).json() == []
    assert other.get("/v1/coral/workflows", headers=alice).json() == []
    assert other.get(f"/v1/coral/workflows/{saved['id']}", headers=alice).status_code == 404
    # The same key is free in another workspace.
    assert other.post("/v1/coral/workflows", json=yaml, headers=bob).status_code == 200


def test_plugin_mounts_the_run_reads_behind_authentication_with_one_404_before_the_lifespan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    header = UnifiedAuthProvider(
        source="header", local_single_user=False, header_name="X-Forwarded-Email"
    )
    signed_in = {"X-Forwarded-Email": "alice"}
    run = "f" * 32
    routes = ["/v1/coral/runs", *(f"/v1/coral/runs/{run}{route}" for route in ("", "/graph"))]
    routes += [f"/v1/coral/runs/{run}/{route}" for route in ("log", "outcome", "stream")]
    not_found = b'{"error":{"code":"not_found","message":"Run not found.","details":null}}'

    with_auth = TestClient(_plugin_app(auth_provider=header))
    without_auth = TestClient(_plugin_app(auth_provider=None))

    for route in routes:
        assert with_auth.get(route).status_code == 401
        # The lifespan publishes the runs API; until then no run is found.
        for response in (with_auth.get(route, headers=signed_in), without_auth.get(route)):
            assert (response.status_code, response.content) == (404, not_found)


def test_plugin_mounts_the_run_writes_behind_authentication_with_one_404_before_the_lifespan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    header = UnifiedAuthProvider(
        source="header", local_single_user=False, header_name="X-Forwarded-Email"
    )
    signed_in = {"X-Forwarded-Email": "alice"}
    run = "f" * 32
    writes = [
        (
            "/v1/coral/runs",
            {"workflow_id": "a" * 32, "start_key": "k", "host_id": "h", "repo_path": "/r"},
        ),
        *((f"/v1/coral/runs/{run}:{action}", {}) for action in ("pause", "resume", "cancel")),
        (f"/v1/coral/runs/{run}/activations/{'a' * 32}:retry", {}),
        (f"/v1/coral/runs/{run}/gates/approve:answer", {"visit_token": "t", "outcome": "approve"}),
    ]
    not_found = b'{"error":{"code":"not_found","message":"Run not found.","details":null}}'

    with_auth = TestClient(_plugin_app(auth_provider=header))
    without_auth = TestClient(_plugin_app(auth_provider=None))

    for route, body in writes:
        assert with_auth.post(route, json=body).status_code == 401
        for response in (
            with_auth.post(route, json=body, headers=signed_in),
            without_auth.post(route, json=body),
        ):
            assert (response.status_code, response.content) == (404, not_found)
    # Preflight names no run but still needs the runs API; before the lifespan it is 404.
    preflight_body = {"workflow_id": "a" * 32, "host_id": "h"}
    assert with_auth.post("/v1/coral/runs:preflight", json=preflight_body).status_code == 401
    for response in (
        with_auth.post("/v1/coral/runs:preflight", json=preflight_body, headers=signed_in),
        without_auth.post("/v1/coral/runs:preflight", json=preflight_body),
    ):
        assert (response.status_code, response.content) == (404, not_found)
