"""Workflow router: validate, save and get through a standalone FastAPI app."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from coral.api.workflows import create_workflows_router
from coral.db.models_workflows import CoralBase
from coral.stores.workflows import SqlWorkflowDefinitionStore
from coral.validate import ValidateContext
from tests.coral.workflow_builders import (
    arrow,
    end,
    fixture_text,
    start,
    step,
    workflow_text,
)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite:///{tmp_path / 'coral.db'}")
    CoralBase.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(
        create_workflows_router(
            SqlWorkflowDefinitionStore(engine),
            workspace_id_dependency=lambda: 7,
            validate_context=lambda: ValidateContext(harnesses={"claude": True}),
        ),
        prefix="/v1/coral",
    )
    yield TestClient(app)
    engine.dispose()


def test_validate_reports_runnable_workflow(client: TestClient) -> None:
    body = client.post("/v1/coral/workflows:validate", json={"yaml": fixture_text("loop")}).json()
    assert body["valid"] and body["runnable"] and body["problems"] == []
    assert len(body["content_hash"]) == 64


def test_validate_reports_problems_with_paths_and_ranges(client: TestClient) -> None:
    body = client.post(
        "/v1/coral/workflows:validate", json={"yaml": fixture_text("deadlock_join")}
    ).json()
    assert body["valid"] and not body["runnable"]
    problem = body["problems"][0]
    assert problem["rule"] == "V2" and problem["yaml_path"] and problem["range"]["start_line"] >= 1


def test_validate_reports_load_errors_without_failing_the_request(client: TestClient) -> None:
    response = client.post("/v1/coral/workflows:validate", json={"yaml": "a: 1\na: 2\n"})
    assert response.status_code == 200
    assert response.json()["load_error"]["code"] == "duplicate_key"


def test_save_then_get_and_list(client: TestClient) -> None:
    saved = client.post("/v1/coral/workflows", json={"yaml": fixture_text("minimal")}).json()
    assert saved["runnable"] and saved["workflow_key"] == "demo"
    fetched = client.get(f"/v1/coral/workflows/{saved['id']}").json()
    assert fetched["yaml"] == fixture_text("minimal")
    assert fetched["compiled"]["content_hash"] == saved["content_hash"]
    assert [item["id"] for item in client.get("/v1/coral/workflows").json()] == [saved["id"]]


def test_save_keeps_non_runnable_drafts(client: TestClient) -> None:
    saved = client.post("/v1/coral/workflows", json={"yaml": fixture_text("deadlock_join")}).json()
    assert saved["runnable"] is False and saved["problems"]


def test_save_rejects_documents_that_do_not_load(client: TestClient) -> None:
    response = client.post("/v1/coral/workflows", json={"yaml": "id: [oops"})
    assert response.status_code == 422
    assert response.json()["detail"]["load_error"]["code"] == "invalid_yaml"


def test_save_rejects_oversize_documents(client: TestClient) -> None:
    text = workflow_text(
        [start(), step("work", goal=os.urandom(20_000).hex()), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )
    assert client.post("/v1/coral/workflows", json={"yaml": text}).status_code == 413


def test_get_unknown_workflow_is_404(client: TestClient) -> None:
    assert client.get("/v1/coral/workflows/" + "0" * 32).status_code == 404


def test_validate_context_controls_harness_rule(client: TestClient) -> None:
    text = workflow_text(
        [start(), step("work", harness="codex"), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )
    body = client.post("/v1/coral/workflows:validate", json={"yaml": text}).json()
    assert [p["rule"] for p in body["problems"]] == ["V10"]
