"""Templates router on a bare app: the built-in list, and ``:use`` making the caller's own copy."""

from __future__ import annotations

import re
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

import coral.api.templates as templates_api
import coral.stores.workflows as workflow_store
from coral.api.run_service import InFlight
from coral.api.templates import (
    MAX_TEMPLATE_COPIES,
    MAX_USE_ATTEMPTS,
    create_templates_router,
    free_key,
)
from coral.api.workflows import create_workflows_router
from coral.db.models_workflows import CoralBase
from coral.omni.server.access import request_viewer
from coral.omni.server.openapi import coral_openapi
from coral.stores.workflows import SqlWorkflowDefinitionStore, WorkflowDefinition
from coral.templates import BuiltinTemplate, TemplateError, builtin_template, builtin_templates
from coral.templates import with_workflow_id as rewrite_id
from omnigent.server.auth import AuthProvider, UnifiedAuthProvider
from tests.coral.api._auth import CROSSED_ACCOUNT, HEADER
from tests.coral.workflow_builders import fixture_text

HEADER_AUTH = UnifiedAuthProvider(source="header", local_single_user=False, header_name=HEADER)
ALICE = "alice"
BOB = "bob"
WORKSPACE = 7
SAVED_AT = 1_000
TEMPLATE_ID = "implement-review-loop"
TEMPLATES = "/v1/coral/templates"
USE = f"{TEMPLATES}/{TEMPLATE_ID}:use"
WORKFLOWS = "/v1/coral/workflows"
TEMPLATE_NOT_FOUND = {
    "error": {"code": "not_found", "message": "Template not found.", "details": None}
}
NO_FREE_KEY_BODY = {
    "error": {
        "code": "workflow_key_taken",
        "message": "No free workflow key could be chosen for a copy of this template.",
        "details": None,
    }
}
RANDOM_KEY = re.compile(rf"{TEMPLATE_ID}-[0-9a-f]{{6}}")


class _RecordingStore(SqlWorkflowDefinitionStore):
    """
    The SQL store, recording each key read and insert.

    ``stale_reads`` key reads miss ``hidden``, as a read made before another user's
    save of those keys committed would.
    """

    def __init__(self, engine: Engine, *, hidden: frozenset[str] = frozenset()) -> None:
        super().__init__(engine, clock=lambda: SAVED_AT)
        self.hidden = hidden
        self.stale_reads = 1
        self.key_reads = 0
        self.creates: list[str] = []

    def workflow_keys(self, *, workspace_id: int, prefix: str) -> frozenset[str]:
        self.key_reads += 1
        keys = super().workflow_keys(workspace_id=workspace_id, prefix=prefix)
        return keys - self.hidden if self.key_reads <= self.stale_reads else keys

    def create(self, **fields: Any) -> WorkflowDefinition:
        self.creates.append(fields["workflow_key"])
        return super().create(**fields)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    sqlite_engine = create_engine(f"sqlite:///{tmp_path / 'coral.db'}")
    CoralBase.metadata.create_all(sqlite_engine)
    yield sqlite_engine
    sqlite_engine.dispose()


@pytest.fixture
def store(engine: Engine) -> _RecordingStore:
    return _RecordingStore(engine)


def _no_simulations(_request: Request) -> InFlight:
    raise AssertionError("these tests do not simulate")


def _client(
    store: SqlWorkflowDefinitionStore,
    user: str | None = ALICE,
    auth_provider: AuthProvider | None = HEADER_AUTH,
) -> TestClient:
    """The templates and workflows routers, authenticating as ``user``."""
    viewer = request_viewer(auth_provider)
    app = FastAPI()
    app.include_router(
        create_templates_router(
            store, viewer_dependency=viewer, workspace_id_dependency=lambda: WORKSPACE
        ),
        prefix="/v1/coral",
    )
    app.include_router(
        create_workflows_router(
            store,
            viewer_dependency=viewer,
            workspace_id_dependency=lambda: WORKSPACE,
            simulations=_no_simulations,
        ),
        prefix="/v1/coral",
    )
    return TestClient(app, headers={} if user is None else {HEADER: user})


def _template() -> BuiltinTemplate:
    template = builtin_template(TEMPLATE_ID)
    assert template is not None
    return template


def _use(client: TestClient, template_id: str = TEMPLATE_ID) -> dict[str, Any]:
    response = client.post(f"{TEMPLATES}/{template_id}:use", json={})
    assert response.status_code == 201, response.text
    return response.json()


def _yaml(client: TestClient, definition_id: str) -> str:
    response = client.get(f"{WORKFLOWS}/{definition_id}")
    assert response.status_code == 200, response.text
    return response.json()["yaml"]


def _row_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(text("SELECT COUNT(*) FROM coral_workflows")).scalar_one()


def _hold(store: SqlWorkflowDefinitionStore, key: str, owner: str | None) -> WorkflowDefinition:
    """A row of ``owner``'s under ``key``, made directly in the store."""
    template = _template()
    return store.save(
        workspace_id=WORKSPACE,
        workflow_key=key,
        name=template.name,
        yaml_text=template.yaml_text,
        compiled=template.graph,
        runnable=True,
        owner=owner,
    )


# ── The list ────────────────────────────────────────────────────────────────


def test_the_list_holds_the_registered_templates_with_their_packaged_text(
    store: SqlWorkflowDefinitionStore,
) -> None:
    response = _client(store).get(TEMPLATES)

    assert response.status_code == 200, response.text
    packaged = resources.files("coral.templates").joinpath("implement_review_loop.yaml")
    assert response.json() == [
        {
            "id": TEMPLATE_ID,
            "name": "Implement with review loop",
            "description": _template().description,
            "yaml": packaged.read_text("utf-8"),
        }
    ]
    assert [item["id"] for item in response.json()] == [item.id for item in builtin_templates()]


# ── Use ─────────────────────────────────────────────────────────────────────


def test_a_first_use_makes_the_callers_workflow_under_the_templates_id(
    store: _RecordingStore,
) -> None:
    alice = _client(store)

    used = _use(alice)
    saved = alice.post(WORKFLOWS, json={"yaml": fixture_text("minimal")})

    # The same body a save answers.
    assert set(used) == set(saved.json())
    assert (used["workflow_key"], used["valid"], used["runnable"], used["problems"]) == (
        TEMPLATE_ID,
        True,
        True,
        [],
    )
    assert used["compiled"] == _template().graph.model_dump(mode="json")
    assert used["content_hash"] == _template().graph.content_hash
    assert _yaml(alice, used["id"]) == _template().yaml_text
    assert [item["id"] for item in _client(store, BOB).get(WORKFLOWS).json()] == []
    assert (store.key_reads, store.creates) == (1, [TEMPLATE_ID])
    assert saved.status_code == 200, saved.text


def test_another_use_makes_a_new_copy_and_never_replaces_the_edited_one(
    store: _RecordingStore,
) -> None:
    alice = _client(store)
    first = _use(alice)
    edited = _template().yaml_text.replace("Make the change", "Make a careful change")
    assert edited != _template().yaml_text
    resaved = alice.post(WORKFLOWS, json={"yaml": edited})
    assert (resaved.status_code, resaved.json()["id"]) == (200, first["id"])

    second, third = _use(alice), _use(alice)

    assert (second["workflow_key"], third["workflow_key"]) == (
        f"{TEMPLATE_ID}-2",
        f"{TEMPLATE_ID}-3",
    )
    assert _yaml(alice, first["id"]) == edited
    assert _yaml(alice, second["id"]) == rewrite_id(_template(), f"{TEMPLATE_ID}-2")
    assert second["compiled"]["workflow_id"] == f"{TEMPLATE_ID}-2"
    # The copy differs from the template only in its id's line.
    changed = [
        (old, new)
        for old, new in zip(
            _template().yaml_text.splitlines(),
            _yaml(alice, second["id"]).splitlines(),
            strict=True,
        )
        if old != new
    ]
    assert changed == [(f"id: {TEMPLATE_ID}", f"id: {TEMPLATE_ID}-2")]
    assert store.creates == [TEMPLATE_ID, f"{TEMPLATE_ID}-2", f"{TEMPLATE_ID}-3"]


@pytest.mark.parametrize(
    "holder", [pytest.param(BOB, id="other"), pytest.param(None, id="legacy")]
)
def test_a_key_someone_else_holds_is_skipped_in_one_insert_and_left_as_it_was(
    store: _RecordingStore, holder: str | None
) -> None:
    held = _hold(store, TEMPLATE_ID, holder)

    used = _use(_client(store))

    assert used["workflow_key"] == f"{TEMPLATE_ID}-2"
    assert (store.key_reads, store.creates) == (1, [f"{TEMPLATE_ID}-2"])
    assert store.get(workspace_id=WORKSPACE, workflow_id=held.id, owner=holder) == held


def test_squatted_numbered_keys_give_a_random_suffix_instead_of_a_refusal(
    store: _RecordingStore,
) -> None:
    keys = [TEMPLATE_ID, *(f"{TEMPLATE_ID}-{n}" for n in range(2, MAX_TEMPLATE_COPIES + 2))]
    for key in keys:
        _hold(store, key, BOB)
    alice = _client(store)

    used = _use(alice)

    key = used["workflow_key"]
    assert RANDOM_KEY.fullmatch(key), key
    assert key not in keys
    assert used["compiled"]["workflow_id"] == key
    assert _yaml(alice, used["id"]) == rewrite_id(_template(), key)
    assert (store.key_reads, store.creates) == (1, [key])


@pytest.mark.parametrize("racer", [pytest.param(BOB, id="other"), pytest.param(ALICE, id="own")])
def test_a_use_that_loses_a_race_for_its_key_takes_the_next_free_one(
    engine: Engine, racer: str
) -> None:
    store = _RecordingStore(engine, hidden=frozenset({TEMPLATE_ID}))
    held = _hold(store, TEMPLATE_ID, racer)

    used = _use(_client(store))

    assert used["workflow_key"] == f"{TEMPLATE_ID}-2"
    assert (store.key_reads, store.creates) == (2, [TEMPLATE_ID, f"{TEMPLATE_ID}-2"])
    # Even the caller's own row that won the race is left as it was.
    assert store.get(workspace_id=WORKSPACE, workflow_id=held.id, owner=racer) == held


def test_a_use_that_keeps_losing_races_takes_a_random_key_on_its_last_insert(
    engine: Engine,
) -> None:
    # Every read misses the racer's key, as concurrent uses that read the same keys would.
    store = _RecordingStore(engine, hidden=frozenset({TEMPLATE_ID}))
    store.stale_reads = MAX_USE_ATTEMPTS
    _hold(store, TEMPLATE_ID, BOB)

    used = _use(_client(store))

    *raced, last = store.creates
    assert raced == [TEMPLATE_ID] * (MAX_USE_ATTEMPTS - 1)
    assert RANDOM_KEY.fullmatch(last) and used["workflow_key"] == last
    assert _row_count(engine) == 2


def test_a_use_with_no_free_key_is_refused_without_naming_a_key(
    store: _RecordingStore, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(templates_api, "free_key", lambda *_args, **_kwargs: None)

    response = _client(store).post(USE, json={})

    assert (response.status_code, response.json()) == (409, NO_FREE_KEY_BODY)
    assert "this key" not in response.text
    assert (store.creates, _row_count(engine)) == ([], 0)


def test_a_copy_too_large_to_store_is_refused_and_stores_nothing(
    store: _RecordingStore, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workflow_store, "MAX_STORED_BYTES", 64)

    response = _client(store).post(USE, json={})

    assert (response.status_code, response.json()["error"]["code"]) == (413, "payload_too_large")
    assert (store.creates, _row_count(engine)) == ([TEMPLATE_ID], 0)


def test_use_checks_the_rewritten_workflow_names_the_chosen_key_before_storing(
    store: _RecordingStore, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hold(store, TEMPLATE_ID, BOB)
    # A rewrite that left the template's own id in place.
    monkeypatch.setattr(
        templates_api, "with_workflow_id", lambda template, _key: template.yaml_text
    )

    with pytest.raises(TemplateError):
        _client(store).post(USE, json={})

    assert store.creates == []
    assert _row_count(engine) == 1


@pytest.mark.parametrize(
    "template_id",
    [
        "implement_review_loop",
        "implement-review-loop.yaml",
        "IMPLEMENT-REVIEW-LOOP",
        "pr-review-loop",
        "pr_review_loop",
        "single_agent_steps",
        "..",
        "%2e%2e",
        "%00",
        "%ED%A0%80",
        "x" * 300,
    ],
)
def test_an_unknown_template_is_one_404_that_names_nothing_and_stores_nothing(
    store: _RecordingStore, engine: Engine, template_id: str
) -> None:
    client = _client(store)

    used = client.post(f"{TEMPLATES}/{template_id}:use", json={})

    assert (used.status_code, used.json()) == (404, TEMPLATE_NOT_FOUND)
    assert (store.key_reads, store.creates, _row_count(engine)) == (0, [], 0)


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        pytest.param(b"", "application/json", id="no-body"),
        pytest.param(b'{"parameters": {"limit": 2}}', "application/json", id="unknown-field"),
        pytest.param(b"[]", "application/json", id="not-an-object"),
        pytest.param(b'{"\\ud800": 1}', "application/json", id="lone-surrogate-key"),
        pytest.param(b"{}", "text/plain", id="not-json"),
    ],
)
def test_use_takes_the_empty_json_object_and_refuses_any_other_body(
    store: _RecordingStore, engine: Engine, content: bytes, content_type: str
) -> None:
    response = _client(store).post(USE, content=content, headers={"content-type": content_type})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_failed"
    assert (store.key_reads, store.creates, _row_count(engine)) == (0, [], 0)


def test_every_template_route_needs_a_signed_in_caller(
    store: _RecordingStore, engine: Engine
) -> None:
    anonymous = _client(store, user=None)
    crossed = _client(store, auth_provider=CROSSED_ACCOUNT)

    for client, status, code in (
        (anonymous, 401, "unauthenticated"),
        (crossed, 403, "not_permitted"),
    ):
        for response in (client.get(TEMPLATES), client.post(USE, json={})):
            assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert (store.key_reads, store.creates, _row_count(engine)) == (0, [], 0)


def test_with_authentication_off_the_local_user_owns_its_copy(store: _RecordingStore) -> None:
    local = _client(store, user=None, auth_provider=None)

    used = _use(local)

    [definition] = store.list_definitions(workspace_id=WORKSPACE, owner=None)
    assert (definition.id, definition.user_id) == (used["id"], None)


def test_the_template_routes_declare_their_refusals() -> None:
    paths = coral_openapi()["paths"]

    listing = paths[TEMPLATES]["get"]
    use = paths[f"{TEMPLATES}/{{template_id}}:use"]["post"]
    assert (listing["operationId"], use["operationId"]) == (
        "coral_list_templates",
        "coral_use_template",
    )
    assert set(listing["responses"]) == {"200", "401", "403"}
    assert set(use["responses"]) == {"201", "401", "403", "404", "409", "413", "422"}
    assert use["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EmptyRequest"
    }


@pytest.mark.parametrize(
    ("template_id", "taken", "expected"),
    [
        pytest.param("t", set(), "t", id="free"),
        pytest.param("t", {"t", "t-2"}, "t-3", id="numbered"),
        pytest.param(
            "t",
            {"t", *(f"t-{number}" for number in range(2, MAX_TEMPLATE_COPIES + 1))},
            f"t-{MAX_TEMPLATE_COPIES + 1}",
            id="last-numbered",
        ),
        pytest.param("new", set(), "new-2", id="reserved-id-skipped"),
        pytest.param("x" * 64, {"x" * 64}, None, id="no-usable-key"),
    ],
)
def test_free_key_takes_the_first_usable_key_nobody_holds(
    template_id: str, taken: set[str], expected: str | None
) -> None:
    assert free_key(template_id, taken) == expected


def test_free_key_draws_another_random_suffix_when_one_is_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draws = iter(["aaaaaa", "bbbbbb"])
    monkeypatch.setattr(templates_api.secrets, "token_hex", lambda _bytes: next(draws))

    assert free_key("t", {"t-aaaaaa"}, numbered=False) == "t-bbbbbb"


def test_free_key_skips_whatever_the_workflow_id_rule_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validate = templates_api.validate_workflow_id

    def also_reserved(value: str) -> str:
        if value == "t":
            raise ValueError("reserved")
        return validate(value)

    monkeypatch.setattr(templates_api, "validate_workflow_id", also_reserved)

    assert free_key("t", set()) == "t-2"
