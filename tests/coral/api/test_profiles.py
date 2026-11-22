"""Profiles and rule-template router on a bare app, each profile scoped to its owner."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from coral.api.profiles import create_profiles_router
from coral.db import RunRow, coral_engine
from coral.db.enum_codecs import RunStatus
from coral.db.migrate import ensure_coral_schema
from coral.omni.server.access import request_viewer
from coral.stores import profiles as profiles_module
from coral.stores.profiles import SqlProfileStore, revision_id
from coral.stores.workflows import SqlWorkflowDefinitionStore
from omnigent.server.auth import UnifiedAuthProvider
from tests.coral.workflow_builders import arrow, compile_text, end, start, step, workflow_text
from tests.db.coral._migration_support import insert_run

HEADER = "X-Forwarded-Email"
HEADER_AUTH = UnifiedAuthProvider(source="header", local_single_user=False, header_name=HEADER)
ALICE = "alice"
BOB = "bob"
# insert_run writes workspace 1.
WORKSPACE = 1
REF = "reviewer/strict-review"
PROFILES = "/v1/coral/profiles"
DETAIL = f"{PROFILES}/{REF}"
SPEC: dict[str, Any] = {
    "name": "Strict review",
    "instructions": "Be strict.",
    "model": "claude-opus-4",
    "rules": [
        {"template": "protect_paths", "params": {"paths": ["infra"]}, "strength": "required"}
    ],
}


class World:
    def __init__(self, uri: str) -> None:
        ensure_coral_schema(uri)
        self.engine = coral_engine(uri)
        self.profiles = SqlProfileStore(self.engine, clock=lambda: 1_000)
        self.definitions = SqlWorkflowDefinitionStore(self.engine)

    def client(self, user: str | None = ALICE, *, with_store: bool = True) -> TestClient:
        app = FastAPI()
        if with_store:
            app.state.coral_profile_store = self.profiles
        app.include_router(
            create_profiles_router(
                self.definitions,
                viewer_dependency=request_viewer(HEADER_AUTH),
                workspace_id_dependency=lambda: WORKSPACE,
            ),
            prefix="/v1/coral",
        )
        return TestClient(app, headers={} if user is None else {HEADER: user})

    def save_workflow(self, key: str, roster: list[str], owner: str = ALICE) -> None:
        graph, _source_map = compile_text(
            workflow_text(
                [start(), step("review", roster), end()],
                [arrow("a1", "start", "review"), arrow("a2", "review", "end")],
                id=key,
            )
        )
        self.definitions.save(
            workspace_id=WORKSPACE,
            workflow_key=key,
            name=key,
            yaml_text="",
            compiled=graph,
            runnable=True,
            owner=owner,
        )

    def start_run(self, run_id: str, owner: str = ALICE) -> None:
        insert_run(self.engine, run_id, status=int(RunStatus.RUNNING), pause_reason=None)
        self.profiles.pin_run(workspace_id=WORKSPACE, run_id=run_id, owner=owner, refs=[REF])


@pytest.fixture
def world(db_uri: str) -> World:
    return World(db_uri)


@pytest.fixture
def client(world: World) -> TestClient:
    return world.client()


def _create(client: TestClient, spec: dict[str, Any] = SPEC, ref: str = REF) -> Any:
    return client.post(PROFILES, json={"ref": ref, "spec": spec})


def _errors(response: Any) -> list[dict[str, str]]:
    assert response.status_code == 422, response.text
    body = response.json()["error"]
    assert body["code"] == "validation_failed"
    return body["details"]["errors"]


def test_the_list_starts_with_the_seeded_stances(world: World, client: TestClient) -> None:
    world.save_workflow("one", ["reviewer"])
    world.save_workflow("other", ["reviewer"], owner=BOB)

    rows = client.get(PROFILES).json()

    assert [(row["profile_ref"], row["source"], row["revision_no"]) for row in rows] == [
        ("implementer", "seeded", None),
        ("reviewer", "seeded", None),
    ]
    reviewer = rows[1]
    assert reviewer["harness"] == "claude-sdk"
    assert reviewer["capabilities"] == {
        "steering": "unknown",
        "tool_gating": "supported",
        "fs_read_only": "supported",
        "usage_reporting": "unknown",
    }
    assert reviewer["used_by"] == {"workflows": 1, "running_runs": 0}
    assert reviewer["description"].startswith("Coral reviewer.")


def test_create_returns_rev_1_with_the_rule_statement(client: TestClient) -> None:
    response = _create(client)

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["profile_ref"], body["stance"], body["source"]) == (REF, "reviewer", "user")
    assert (body["revision_no"], body["created"], body["model"]) == (1, True, "claude-opus-4")
    assert body["rules"] == [
        {
            "template": "protect_paths",
            "strength": "required",
            "statement": "Never change files under infra/.",
        }
    ]
    assert body["revisions"] == [
        {"id": revision_id(REF, 1), "revision_no": 1, "created_at": 1_000, "running_runs": 0}
    ]
    assert body["spec"]["instructions"] == "Be strict."
    assert client.get(DETAIL).json() == {**body, "created": False}


def test_create_refuses_an_existing_profile_and_another_owners_ref(world: World) -> None:
    assert _create(world.client()).status_code == 201

    again = _create(world.client())
    taken = _create(world.client(BOB))

    assert (again.status_code, again.json()["error"]["code"]) == (409, "profile_exists")
    assert (taken.status_code, taken.json()["error"]["code"]) == (409, "profile_key_taken")


@pytest.mark.parametrize(
    ("ref", "spec", "field"),
    [
        ("reviewer", SPEC, "ref"),
        ("orchestrator/x", SPEC, "ref"),
        ("reviewer/Bad", SPEC, "ref"),
        (REF, {**SPEC, "name": ""}, "name"),
        (REF, {**SPEC, "api_key": "x"}, "api_key"),
        (
            REF,
            {**SPEC, "rules": [{"template": "nope", "strength": "required"}]},
            "rules[0].template",
        ),
        (
            REF,
            {
                **SPEC,
                "rules": [
                    {"template": "stay_in_worktree", "strength": "guidance"},
                    {
                        "template": "protect_paths",
                        "params": {"paths": ["/etc"]},
                        "strength": "required",
                    },
                ],
            },
            "rules[1].params.paths[0]",
        ),
        (
            REF,
            {**SPEC, "rules": [{"template": "protect_paths", "strength": "required"}]},
            "rules[0].params.paths",
        ),
        (
            REF,
            {**SPEC, "rules": [{"template": "stay_in_worktree", "strength": "maybe"}]},
            "rules[0].strength",
        ),
    ],
)
def test_invalid_input_is_refused_naming_the_field(
    client: TestClient, ref: str, spec: dict[str, Any], field: str
) -> None:
    errors = _errors(_create(client, spec, ref))

    assert field in [error["field"] for error in errors], errors
    assert all(error["message"] for error in errors)
    assert client.get(PROFILES).json()[2:] == []


def test_a_spec_too_large_to_store_is_refused(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(profiles_module, "MAX_STORED_BYTES", 10)

    assert [error["field"] for error in _errors(_create(client))] == ["spec"]


def test_saving_revisions_changed_unchanged_and_stale(client: TestClient) -> None:
    _create(client)
    changed = {**SPEC, "instructions": "Be stricter."}

    second = client.post(f"{DETAIL}/revisions", json={"base_revision_no": 1, "spec": changed})
    same = client.post(f"{DETAIL}/revisions", json={"base_revision_no": 2, "spec": changed})
    stale = client.post(
        f"{DETAIL}/revisions", json={"base_revision_no": 1, "spec": {**SPEC, "name": "New"}}
    )

    assert second.status_code == 200, second.text
    assert (second.json()["revision_no"], second.json()["created"]) == (2, True)
    assert [rev["revision_no"] for rev in second.json()["revisions"]] == [2, 1]
    assert (same.json()["revision_no"], same.json()["created"]) == (2, False)
    assert (stale.status_code, stale.json()["error"]["code"]) == (412, "stale_revision")
    bad = client.post(
        f"{DETAIL}/revisions", json={"base_revision_no": 2, "spec": {**SPEC, "model": "-x"}}
    )
    assert [error["field"] for error in _errors(bad)] == ["model"]


def test_another_owner_cannot_see_or_save_a_profile(world: World) -> None:
    _create(world.client())
    world.start_run("a" * 32)
    bob = world.client(BOB)

    assert bob.get(DETAIL).status_code == 404
    refused = bob.post(f"{DETAIL}/revisions", json={"base_revision_no": 1, "spec": SPEC})
    assert (refused.status_code, refused.json()["error"]["code"]) == (404, "not_found")
    assert [row["profile_ref"] for row in bob.get(PROFILES).json()] == ["implementer", "reviewer"]
    assert bob.get(f"{PROFILES}/reviewer/missing").status_code == 404
    assert bob.get(f"{PROFILES}/orchestrator/x").status_code == 404


def test_used_by_counts_workflows_and_unfinished_runs_per_revision(world: World) -> None:
    client = world.client()
    _create(client)
    world.save_workflow("one", [REF])
    world.save_workflow("two", [REF, "reviewer"])
    world.save_workflow("bobs", [REF], owner=BOB)
    world.start_run("a" * 32)
    world.start_run("b" * 32)
    client.post(
        f"{DETAIL}/revisions", json={"base_revision_no": 1, "spec": {**SPEC, "name": "Two"}}
    )
    world.start_run("c" * 32)
    with world.engine.begin() as connection:
        connection.execute(update(RunRow).where(RunRow.id == "b" * 32).values(finished_at=5))

    detail = client.get(DETAIL).json()
    rows = {row["profile_ref"]: row for row in client.get(PROFILES).json()}

    assert detail["used_by"] == {"workflows": 2, "running_runs": 2}
    assert [(rev["revision_no"], rev["running_runs"]) for rev in detail["revisions"]] == [
        (2, 1),
        (1, 1),
    ]
    assert rows[REF]["used_by"] == detail["used_by"]
    assert rows[REF]["name"] == "Two"
    assert rows["reviewer"]["used_by"] == {"workflows": 1, "running_runs": 0}


@pytest.mark.parametrize(
    "body",
    [
        {"base_revision_no": 0, "spec": SPEC},
        {"base_revision_no": -1, "spec": SPEC},
        {"base_revision_no": 1, "spec": SPEC, "owner": BOB},
    ],
)
def test_a_revision_body_out_of_shape_is_refused(client: TestClient, body: Any) -> None:
    _create(client)

    response = client.post(f"{DETAIL}/revisions", json=body)

    assert (response.status_code, response.json()["error"]["code"]) == (422, "validation_failed")
    assert client.get(DETAIL).json()["revision_no"] == 1


def test_a_post_that_is_not_json_is_refused(client: TestClient) -> None:
    response = client.post(
        PROFILES, content='{"ref": "reviewer/x"}', headers={"content-type": "text/plain"}
    )

    assert (response.status_code, response.json()["error"]["code"]) == (422, "validation_failed")
    assert client.get(PROFILES).json()[2:] == []


def test_rule_templates_list_the_catalog(client: TestClient) -> None:
    templates = {row["id"]: row for row in client.get("/v1/coral/rule-templates").json()}

    assert set(templates) == {"limit_blast_radius", "stay_in_worktree", "protect_paths"}
    protect = templates["protect_paths"]
    assert protect["statement_example"] == "Never change files under infra/, secrets/."
    assert "paths" in protect["params_schema"]["properties"]
    assert all(row["bypasses"] and row["version"] == 1 for row in templates.values())


def test_every_route_needs_a_caller_and_profiles_need_the_store(world: World) -> None:
    anonymous = world.client(None)
    for response in (
        anonymous.get(PROFILES),
        anonymous.get(DETAIL),
        anonymous.post(PROFILES, json={"ref": REF, "spec": SPEC}),
        anonymous.post(f"{DETAIL}/revisions", json={"base_revision_no": 1, "spec": SPEC}),
        anonymous.get("/v1/coral/rule-templates"),
    ):
        assert response.status_code == 401

    storeless = world.client(with_store=False)
    assert storeless.get(PROFILES).status_code == 404
    assert _create(storeless).status_code == 404
    assert storeless.get("/v1/coral/rule-templates").status_code == 200
