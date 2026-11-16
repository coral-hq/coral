"""The Coral plugin mounts the workflows router under /v1/coral."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coral.omni.server.plugin import register
from omnigent.process_logging import DATA_DIR_ENV_VAR
from tests.coral.workflow_builders import fixture_text


def test_plugin_mounts_workflows_router_backed_by_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    services = cast(Any, SimpleNamespace(host_sharded=False, server_config={}))
    registration = register(services)
    app = FastAPI()
    for router, prefix, tags in registration.routers:
        app.include_router(router, prefix=prefix, tags=tags)
    client = TestClient(app)

    validated = client.post("/v1/coral/workflows:validate", json={"yaml": fixture_text("minimal")})
    assert validated.json()["compiled"]["workflow_id"] == "demo"
    saved = client.post("/v1/coral/workflows", json={"yaml": fixture_text("minimal")}).json()
    assert [item["id"] for item in client.get("/v1/coral/workflows").json()] == [saved["id"]]
    assert (tmp_path / "coral.db").exists()
