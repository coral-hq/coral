"""The Coral plugin mounts the workflows and workflow Inbox routers under /v1/coral."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from coral.db.enum_codecs import AlertKind
from coral.db.migrate import ensure_coral_schema
from coral.omni.server.plugin import register
from coral.stores.alerts import SqlAlchemyAlertStore
from coral.stores.runs import SqlAlchemyCoralRunStore
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID, workspace_scope
from omnigent.process_logging import DATA_DIR_ENV_VAR
from omnigent.server.auth import UnifiedAuthProvider
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
    assert [item["id"] for item in client.get("/v1/coral/workflows").json()] == [saved["id"]]
    assert (tmp_path / "coral.db").exists()


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
            {"detail": "Coral inbox is not available"},
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
