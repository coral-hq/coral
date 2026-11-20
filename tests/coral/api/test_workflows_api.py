"""Workflow router on a bare app: validate, save, get and list, each scoped to its caller."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import coral
from coral.api.workflows import MAX_LOAD_ISSUES, MAX_LOAD_TEXT_CHARS, create_workflows_router
from coral.db.models_workflows import CoralBase
from coral.model import LoadError, load
from coral.omni.server.access import request_viewer
from coral.stores.workflows import SqlWorkflowDefinitionStore
from coral.validate import ValidateContext
from omnigent.server.auth import AuthProvider, UnifiedAuthProvider
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    end,
    fixture_text,
    start,
    step,
    workflow_text,
)

HEADER = "X-Forwarded-Email"
HEADER_AUTH = UnifiedAuthProvider(source="header", local_single_user=False, header_name=HEADER)
ALICE = "alice"
BOB = "bob"
WORKSPACE = 7
WORKFLOWS = "/v1/coral/workflows"
SAVED_AT = 1_000
# The 2xx bodies the untyped routes served, captured before the typed models replaced them.
GOLDEN = Path(__file__).with_name("workflows_golden.json")
GOLDEN_ID = "<definition id>"
NOT_FOUND = {"error": {"code": "not_found", "message": "Workflow not found.", "details": None}}
KEY_TAKEN = {
    "error": {
        "code": "workflow_key_taken",
        "message": "A workflow with this key already exists.",
        "details": None,
    }
}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqlWorkflowDefinitionStore]:
    engine = create_engine(f"sqlite:///{tmp_path / 'coral.db'}")
    CoralBase.metadata.create_all(engine)
    yield SqlWorkflowDefinitionStore(engine, clock=lambda: SAVED_AT)
    engine.dispose()


def _client(
    store: SqlWorkflowDefinitionStore,
    user: str | None = ALICE,
    auth_provider: AuthProvider | None = HEADER_AUTH,
) -> TestClient:
    """The workflows router alone, authenticating through ``auth_provider`` as ``user``."""
    app = FastAPI()
    app.include_router(
        create_workflows_router(
            store,
            viewer_dependency=request_viewer(auth_provider),
            workspace_id_dependency=lambda: WORKSPACE,
            validate_context=lambda: ValidateContext(harnesses={"claude": True}),
        ),
        prefix="/v1/coral",
    )
    return TestClient(app, headers={} if user is None else {HEADER: user})


@pytest.fixture
def client(store: SqlWorkflowDefinitionStore) -> TestClient:
    return _client(store)


def _save_legacy(store: SqlWorkflowDefinitionStore, yaml_text: str) -> str:
    """Save ``yaml_text`` with no owner, as definitions were saved before they had owners."""
    graph, _source_map = compile_text(yaml_text)
    return store.save(
        workspace_id=WORKSPACE,
        workflow_key=graph.workflow_id,
        name=graph.name,
        yaml_text=yaml_text,
        compiled=graph,
        runnable=True,
        owner=None,
    ).id


def _ids(client: TestClient) -> list[str]:
    response = client.get(WORKFLOWS)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()]


def test_the_owner_gets_the_same_2xx_bodies_the_untyped_routes_served(client: TestClient) -> None:
    bodies = {
        name: client.post(f"{WORKFLOWS}:validate", json={"yaml": yaml}).json()
        for name, yaml in (
            ("validate_runnable", fixture_text("minimal")),
            ("validate_with_problems", fixture_text("deadlock_join")),
            ("validate_load_error", "a: 1\na: 2\n"),
        )
    }
    bodies["save"] = client.post(WORKFLOWS, json={"yaml": fixture_text("minimal")}).json()
    definition_id = bodies["save"]["id"]
    bodies["list"] = client.get(WORKFLOWS).json()
    bodies["get"] = client.get(f"{WORKFLOWS}/{definition_id}").json()

    captured = json.dumps(bodies, sort_keys=True).replace(definition_id, GOLDEN_ID)
    assert json.loads(captured) == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_validate_reports_runnable_workflow(client: TestClient) -> None:
    body = client.post(f"{WORKFLOWS}:validate", json={"yaml": fixture_text("loop")}).json()
    assert body["valid"] and body["runnable"] and body["problems"] == []
    assert len(body["content_hash"]) == 64
    assert body["compiled"]["content_hash"] == body["content_hash"]
    assert {node["kind"] for node in body["compiled"]["nodes"]} >= {"start", "end"}
    assert body["compiled"]["arrows"]


def test_validate_reports_problems_with_paths_and_ranges(client: TestClient) -> None:
    body = client.post(
        f"{WORKFLOWS}:validate", json={"yaml": fixture_text("deadlock_join")}
    ).json()
    assert body["valid"] and not body["runnable"]
    assert body["compiled"]["nodes"]
    problem = body["problems"][0]
    assert problem["rule"] == "V2" and problem["yaml_path"] and problem["range"]["start_line"] >= 1


def test_validate_reports_load_errors_without_failing_the_request(client: TestClient) -> None:
    response = client.post(f"{WORKFLOWS}:validate", json={"yaml": "a: 1\na: 2\n"})
    assert response.status_code == 200
    assert response.json()["load_error"]["code"] == "duplicate_key"
    assert "compiled" not in response.json()


def test_save_then_get_and_list(client: TestClient) -> None:
    saved = client.post(WORKFLOWS, json={"yaml": fixture_text("minimal")}).json()
    assert saved["runnable"] and saved["workflow_key"] == "demo"
    fetched = client.get(f"{WORKFLOWS}/{saved['id']}").json()
    assert fetched["yaml"] == fixture_text("minimal")
    assert fetched["compiled"]["content_hash"] == saved["content_hash"]
    assert _ids(client) == [saved["id"]]


def test_save_keeps_non_runnable_drafts(client: TestClient) -> None:
    saved = client.post(WORKFLOWS, json={"yaml": fixture_text("deadlock_join")}).json()
    assert saved["runnable"] is False and saved["problems"]


def test_save_rejects_documents_that_do_not_load(client: TestClient) -> None:
    response = client.post(WORKFLOWS, json={"yaml": "id: [oops"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["code"], error["details"]["load_error"]["code"]) == (
        "validation_failed",
        "invalid_yaml",
    )


def test_a_refused_save_describes_its_document_within_a_bounded_size(client: TestClient) -> None:
    # Each issue quotes the document: here a 5,000-character id and 300 unknown kinds.
    text = (
        f'id: "{"x" * 5_000}"\nname: n\nnodes:\n'
        + "".join(f"  - id: n{index}\n    kind: bogus{index}\n" for index in range(300))
        + "arrows: []\n"
    )
    loaded = load(text)
    assert isinstance(loaded, LoadError) and len(loaded.issues) > MAX_LOAD_ISSUES

    response = client.post(WORKFLOWS, json={"yaml": text})

    assert response.status_code == 422
    details = response.json()["error"]["details"]
    load_error = details["load_error"]
    assert (load_error["code"], len(load_error["issues"]), details["issues_omitted"]) == (
        "invalid_document",
        MAX_LOAD_ISSUES,
        len(loaded.issues) - MAX_LOAD_ISSUES,
    )
    texts = [load_error["message"], *(issue["message"] for issue in load_error["issues"])]
    assert max(len(text) for text in texts) == MAX_LOAD_TEXT_CHARS
    assert len(response.content) < 32_000


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("id: [oops", id="invalid-yaml"),
        pytest.param("a: 1\na: 2\n", id="duplicate-key"),
        pytest.param("!!python/object/apply:os.system ['true']\n", id="python-tag"),
        pytest.param("id: demo\nnodes: 3\n", id="wrong-shape"),
        pytest.param("x: &a 1\ny: *a\n", id="alias"),
    ],
)
def test_a_refused_save_names_no_server_path(client: TestClient, text: str) -> None:
    response = client.post(WORKFLOWS, json={"yaml": text})

    assert response.status_code == 422
    assert response.json()["error"]["details"]["load_error"]["code"]
    server_paths = (str(Path(coral.__file__).resolve().parents[1]), str(Path.home()))
    for marker in (*server_paths, "site-packages", "Traceback", 'File "'):
        assert marker not in response.text


def test_save_rejects_oversize_documents(client: TestClient) -> None:
    text = workflow_text(
        [start(), step("work", goal=os.urandom(20_000).hex()), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )
    response = client.post(WORKFLOWS, json={"yaml": text})
    assert (response.status_code, response.json()["error"]["code"]) == (413, "payload_too_large")


def test_get_unknown_workflow_is_404(client: TestClient) -> None:
    response = client.get(f"{WORKFLOWS}/{'0' * 32}")
    assert (response.status_code, response.json()) == (404, NOT_FOUND)


def test_validate_context_controls_harness_rule(client: TestClient) -> None:
    text = workflow_text(
        [start(), step("work", harness="codex"), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )
    body = client.post(f"{WORKFLOWS}:validate", json={"yaml": text}).json()
    assert [p["rule"] for p in body["problems"]] == ["V10"]


# ── Who may call, and whose workflows they see ──────────────────────────────


def test_every_route_needs_a_signed_in_caller(store: SqlWorkflowDefinitionStore) -> None:
    anonymous = _client(store, user=None)
    yaml = {"yaml": fixture_text("minimal")}

    for response in (
        anonymous.post(f"{WORKFLOWS}:validate", json=yaml),
        anonymous.post(WORKFLOWS, json=yaml),
        anonymous.get(WORKFLOWS),
        anonymous.get(f"{WORKFLOWS}/{'0' * 32}"),
    ):
        assert (response.status_code, response.json()["error"]["code"]) == (
            401,
            "unauthenticated",
        )
    assert store.list_definitions(workspace_id=WORKSPACE, owner=None) == []


def test_another_users_save_of_a_taken_key_is_refused_and_the_owners_row_is_unchanged(
    store: SqlWorkflowDefinitionStore,
) -> None:
    alice, bob = _client(store), _client(store, BOB)
    saved = alice.post(WORKFLOWS, json={"yaml": fixture_text("minimal")}).json()
    rewritten = fixture_text("minimal").replace("Do the thing", "Run whatever B wants")

    refused = bob.post(WORKFLOWS, json={"yaml": rewritten})

    assert (refused.status_code, refused.json()) == (409, KEY_TAKEN)
    assert alice.get(f"{WORKFLOWS}/{saved['id']}").json()["yaml"] == fixture_text("minimal")


def test_another_users_workflow_is_not_found_and_not_listed(
    store: SqlWorkflowDefinitionStore,
) -> None:
    alice, bob = _client(store), _client(store, BOB)
    saved = alice.post(WORKFLOWS, json={"yaml": fixture_text("minimal")}).json()

    hidden = bob.get(f"{WORKFLOWS}/{saved['id']}")
    unknown = bob.get(f"{WORKFLOWS}/{'0' * 32}")

    assert (hidden.status_code, hidden.content) == (unknown.status_code, unknown.content)
    assert hidden.json() == NOT_FOUND
    assert _ids(bob) == []
    assert _ids(alice) == [saved["id"]]


def test_a_legacy_unowned_workflow_is_readable_until_its_first_saver_claims_it(
    store: SqlWorkflowDefinitionStore,
) -> None:
    legacy_id = _save_legacy(store, fixture_text("minimal"))
    alice, bob = _client(store), _client(store, BOB)
    assert _ids(alice) == _ids(bob) == [legacy_id]
    assert bob.get(f"{WORKFLOWS}/{legacy_id}").status_code == 200

    claimed = alice.post(WORKFLOWS, json={"yaml": fixture_text("minimal")})

    assert (claimed.status_code, claimed.json()["id"]) == (200, legacy_id)
    assert _ids(bob) == []
    assert bob.get(f"{WORKFLOWS}/{legacy_id}").json() == NOT_FOUND
    assert bob.post(WORKFLOWS, json={"yaml": fixture_text("minimal")}).json() == KEY_TAKEN


def test_with_auth_off_the_local_user_owns_legacy_and_new_workflows(
    store: SqlWorkflowDefinitionStore,
) -> None:
    legacy_id = _save_legacy(store, fixture_text("minimal"))
    local = _client(store, user=None, auth_provider=None)

    edited = local.post(WORKFLOWS, json={"yaml": "# note\n" + fixture_text("minimal")})
    added = local.post(WORKFLOWS, json={"yaml": fixture_text("loop")})

    assert (edited.status_code, edited.json()["id"]) == (200, legacy_id)
    assert added.status_code == 200
    assert sorted(_ids(local)) == sorted([legacy_id, added.json()["id"]])
    assert {
        definition.user_id
        for definition in store.list_definitions(workspace_id=WORKSPACE, owner=None)
    } == {None}
