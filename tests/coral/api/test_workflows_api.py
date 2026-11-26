"""Workflow router on a bare app: validate, save, get and list, each scoped to its caller."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, cast, get_args

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

import coral
import coral.api.workflows as workflows_api
import coral.stores.workflows as workflow_store
from coral.api.run_service import InFlight, server_busy
from coral.api.workflows import (
    MAX_LOAD_ISSUES,
    MAX_LOAD_TEXT_CHARS,
    MAX_SIMULATIONS,
    MAX_SIMULATIONS_PER_USER,
    create_workflows_router,
)
from coral.bridge.config import DEFAULT_RUN_ACTIVATIONS
from coral.bridge.executors import BoundedThreads
from coral.db.models_workflows import CoralBase
from coral.engine.simcase import MAX_EXPECTED_ITEMS
from coral.engine.simulate import MAX_SCRIPT_INPUTS, MAX_STEP_SEATS, SimLimit, simulate
from coral.model import LoadError, load
from coral.omni.server.access import request_viewer
from coral.omni.server.openapi import coral_openapi
from coral.omni.server.openapi_ts import TS_PATH
from coral.stores.workflows import MAX_WORKFLOW_CASES, SqlWorkflowDefinitionStore
from coral.templates import builtin_template
from coral.validate import ValidateContext
from coral.validate.pipeline import CheckResult
from omnigent.server.auth import AuthProvider, UnifiedAuthProvider
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.api import simulate_contract
from tests.coral.api._auth import CROSSED_ACCOUNT, HEADER
from tests.coral.api.run_view_contract import checked_in
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    end,
    fixture_text,
    start,
    step,
    workflow_text,
)

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
SIMULATE = f"{WORKFLOWS}:simulate"
SIMULATE_THREADS = "test-simulate"
TEMPLATE_ID = "implement-review-loop"
# Every field a simulation sends, null or empty ones included.
SIMULATION_FIELDS = {
    "outcome",
    "steps",
    "loops",
    "gates_reached",
    "limits_hit",
    "step_activations",
    "sessions",
    "needs_input",
    "rejection",
    "unsupported_effect",
    "stall_code",
    "stopped_by",
    "unconsumed",
    "view",
    "trace_digest",
    "entries",
}
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


def _context() -> ValidateContext:
    return ValidateContext(harnesses={"claude": True})


def _app(
    store: SqlWorkflowDefinitionStore,
    auth_provider: AuthProvider | None = HEADER_AUTH,
    simulations: InFlight | None = None,
    validate_context: Any = _context,
) -> FastAPI:
    """The workflows router alone; without ``simulations`` a simulation is refused as busy."""

    def published(_request: Request) -> InFlight:
        if simulations is None:
            raise server_busy()
        return simulations

    app = FastAPI()
    app.include_router(
        create_workflows_router(
            store,
            viewer_dependency=request_viewer(auth_provider),
            workspace_id_dependency=lambda: WORKSPACE,
            simulations=published,
            validate_context=validate_context,
        ),
        prefix="/v1/coral",
    )
    return app


def _client(
    store: SqlWorkflowDefinitionStore,
    user: str | None = ALICE,
    auth_provider: AuthProvider | None = HEADER_AUTH,
    simulations: InFlight | None = None,
) -> TestClient:
    """The workflows router alone, authenticating through ``auth_provider`` as ``user``."""
    return TestClient(
        _app(store, auth_provider, simulations), headers={} if user is None else {HEADER: user}
    )


@pytest.fixture
def client(store: SqlWorkflowDefinitionStore) -> TestClient:
    return _client(store)


@pytest.fixture
def simulations() -> Iterator[InFlight]:
    """A simulate pool with the plugin's caps."""
    threads = BoundedThreads(max_workers=MAX_SIMULATIONS, thread_name_prefix=SIMULATE_THREADS)
    yield InFlight(threads, max_per_caller=MAX_SIMULATIONS_PER_USER)
    threads.close()


@pytest.fixture
def simulator(store: SqlWorkflowDefinitionStore, simulations: InFlight) -> TestClient:
    return _client(store, simulations=simulations)


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
        anonymous.post(SIMULATE, json=yaml),
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


def test_a_caller_the_server_refuses_is_forbidden_before_any_simulation(
    store: SqlWorkflowDefinitionStore, simulations: InFlight
) -> None:
    crossed = _client(store, auth_provider=CROSSED_ACCOUNT, simulations=simulations)

    for response in (
        crossed.post(f"{WORKFLOWS}:validate", json={"yaml": fixture_text("minimal")}),
        crossed.post(SIMULATE, json={"yaml": fixture_text("minimal")}),
    ):
        assert (response.status_code, response.json()) == (
            403,
            {"error": {"code": "not_permitted", "message": "Not permitted", "details": None}},
        )
    assert simulations.in_flight == 0


# ── Simulate ────────────────────────────────────────────────────────────────


def _template_text() -> str:
    template = builtin_template(TEMPLATE_ID)
    assert template is not None
    return template.yaml_text


def _simulation(client: TestClient, yaml_text: str, script: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"yaml": yaml_text}
    if script is not None:
        body["script"] = script
    response = client.post(SIMULATE, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_simulate_with_no_script_stops_at_the_first_question(simulator: TestClient) -> None:
    body = _simulation(simulator, _template_text())

    assert (body["valid"], body["runnable"], body["problems"]) == (True, True, [])
    assert body["compiled"]["workflow_id"] == TEMPLATE_ID
    assert body["content_hash"] == body["compiled"]["content_hash"]
    simulation = body["simulation"]
    assert set(simulation) == SIMULATION_FIELDS
    assert simulation["outcome"] == "needs_input"
    needs_input = simulation["needs_input"]
    assert set(needs_input) == {"node_id", "activation_id", "kind", "allowed_values"}
    assert (needs_input["node_id"], needs_input["kind"], needs_input["allowed_values"]) == (
        "review",
        "label",
        ["approved", "changes_requested"],
    )
    assert [f"{item['node_id']}:{item['result']}" for item in simulation["steps"]] == [
        "implement:done"
    ]
    assert (simulation["rejection"], simulation["stopped_by"], simulation["unconsumed"]) == (
        None,
        None,
        [],
    )


def test_simulate_answers_each_saved_case_of_the_template_as_the_engine_does(
    simulator: TestClient,
) -> None:
    template = builtin_template(TEMPLATE_ID)
    assert template is not None and template.cases

    for case in template.cases:
        body = _simulation(simulator, template.yaml_text, case.script.model_dump(mode="json"))

        simulation = body["simulation"]
        expect = case.expect
        assert simulation["outcome"] == expect.outcome, case.name
        assert [f"{item['node_id']}:{item['result']}" for item in simulation["steps"]] == list(
            expect.steps or ()
        ), case.name
        assert simulation["gates_reached"] == list(expect.gates_reached or ()), case.name
        assert simulation["limits_hit"] == list(expect.limits_hit or ()), case.name
        assert simulation["sessions"]["total"] == expect.sessions, case.name
        # The route runs the engine with the server's own bounds, never the client's.
        engine = simulate(template.graph, case.script, max_activations=DEFAULT_RUN_ACTIVATIONS)
        assert simulation == engine.result.model_dump(mode="json"), case.name


def test_the_web_fixture_holds_what_simulate_sends_for_the_template(
    simulator: TestClient,
) -> None:
    # WHY: the web panel tests replay this recording; an engine or template change must
    # update it rather than leave the panel tested against an older response.
    # On a mismatch: uv run --no-sync python -m tests.coral.api.simulate_contract --write
    recorded = checked_in(simulate_contract.CONTRACT_PATH)
    assert recorded == simulate_contract.build_contract()
    assert set(recorded["simulations"]) == set(simulate_contract.SCRIPTS)

    for case, inputs in simulate_contract.SCRIPTS.items():
        body = _simulation(simulator, _template_text(), {"inputs": inputs})

        assert body["compiled"] == recorded["compiled"], case
        assert body["simulation"] == recorded["simulations"][case], case


def test_simulate_reports_a_rejected_value_with_the_reducers_code(simulator: TestClient) -> None:
    script = {"inputs": [{"node_id": "review", "kind": "label", "values": ["maybe"]}]}

    simulation = _simulation(simulator, _template_text(), script)["simulation"]

    assert simulation["outcome"] == "rejected"
    assert simulation["rejection"] == {
        "node_id": "review",
        "kind": "label",
        "value": "maybe",
        "code": "handoff.invalid",
        "allowed_values": ["approved", "changes_requested"],
    }


def test_simulate_names_the_bound_that_stopped_a_graph_before_its_run_started(
    simulator: TestClient,
) -> None:
    text = workflow_text(
        [start(), step("work", roster=["implementer"] * (MAX_STEP_SEATS + 1)), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )

    body = _simulation(simulator, text)

    assert body["runnable"] is True
    simulation = body["simulation"]
    assert (simulation["outcome"], simulation["stopped_by"], simulation["entries"]) == (
        "step_limit",
        "step_seats",
        0,
    )
    assert simulation["sessions"]["total"] == 0


def test_simulate_reports_a_document_that_does_not_load_as_validate_does(
    simulator: TestClient,
) -> None:
    response = simulator.post(SIMULATE, json={"yaml": "a: 1\na: 2\n"})

    assert response.status_code == 200
    body = response.json()
    assert (body["valid"], body["runnable"], body["load_error"]["code"]) == (
        False,
        False,
        "duplicate_key",
    )
    assert body == simulator.post(f"{WORKFLOWS}:validate", json={"yaml": "a: 1\na: 2\n"}).json()


def test_simulate_reports_blocking_problems_without_simulating(simulator: TestClient) -> None:
    body = _simulation(simulator, fixture_text("deadlock_join"))

    assert (body["valid"], body["runnable"], body["simulation"]) == (True, False, None)
    assert body["problems"][0]["rule"] == "V2"
    assert body["compiled"]["nodes"]


def _input(**fields: Any) -> dict[str, Any]:
    return {"node_id": "review", "kind": "label", "values": ["approved"], **fields}


MARKER = "zz-refused-zz"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"script": {"inputs": [_input(kind="list_len")]}}, id="unknown-kind"),
        pytest.param(
            {"script": {"inputs": [_input(kind="done_when", values=[MARKER])]}},
            id="done-when-not-pass-or-fail",
        ),
        pytest.param(
            {
                "script": {
                    "inputs": [_input(node_id=f"n{n}") for n in range(MAX_SCRIPT_INPUTS + 1)]
                }
            },
            id="too-many-inputs",
        ),
        pytest.param({"script": {"inputs": [_input(), _input()]}}, id="duplicate-pair"),
        pytest.param({"script": {"inputs": [_input(values=[MARKER * 20])]}}, id="value-too-long"),
        pytest.param({"script": {"inputs": [_input(values=[])]}}, id="no-values"),
        pytest.param({"script": {"inputs": [_input(values=[f"a\x00{MARKER}"])]}}, id="nul"),
        pytest.param({"script": {"inputs": [_input(values=[f"‮{MARKER}"])]}}, id="bidi"),
        pytest.param({"script": {"inputs": [_input(extra=MARKER)]}}, id="extra-input-field"),
        pytest.param({"scripts": {"inputs": []}}, id="mistyped-script-field"),
        pytest.param({"script": [MARKER]}, id="script-not-an-object"),
    ],
)
def test_simulate_refuses_a_malformed_or_oversized_script_without_echoing_it(
    simulator: TestClient, simulations: InFlight, body: dict[str, Any]
) -> None:
    response = simulator.post(SIMULATE, json={"yaml": _template_text(), **body})

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("validation_failed", "The request is invalid.")
    assert all(set(item) == {"loc", "msg", "type"} for item in error["details"]["errors"])
    assert MARKER not in response.text
    assert simulations.in_flight == 0


def _raw_post(client: TestClient, path: str, raw: str) -> httpx.Response:
    return client.post(path, content=raw.encode(), headers={"content-type": "application/json"})


@pytest.mark.parametrize(
    "field",
    [pytest.param("node_id", id="node-id"), pytest.param("values", id="value")],
)
def test_a_lone_surrogate_in_a_script_is_refused_not_a_server_error(
    simulator: TestClient, field: str
) -> None:
    script_input = _input(**{field: "SURROGATE" if field == "node_id" else ["SURROGATE"]})
    raw = json.dumps({"yaml": _template_text(), "script": {"inputs": [script_input]}})

    response = _raw_post(simulator, SIMULATE, raw.replace("SURROGATE", "\\ud800"))

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_failed"


def test_a_lone_surrogate_in_the_document_is_a_load_error_not_a_server_error(
    simulator: TestClient,
) -> None:
    raw = json.dumps({"yaml": "id: aSURROGATE\n"}).replace("SURROGATE", "\\ud800")

    response = _raw_post(simulator, SIMULATE, raw)

    assert response.status_code == 200, response.text
    assert response.json()["load_error"]["code"] == "invalid_text"


def _ts_members(ts: str, interface: str, field: str) -> list[str]:
    """A field's union members in a generated interface, however prettier wraps the union."""
    body = ts.split(f"export interface {interface} {{\n", 1)[1].split("\n}", 1)[0]
    declared = body.split(f"\n  {field}:", 1)[1].split(";", 1)[0]
    return [member.strip() for member in declared.split("|") if member.strip()]


def test_the_ts_union_reader_ignores_how_a_union_is_wrapped() -> None:
    one_line = 'export interface X {\n  a: string;\n  stopped_by: "t" | "w" | null;\n}\n'
    wrapped = (
        'export interface X {\n  a: string;\n  stopped_by:\n    | "t"\n    | "w"\n    | null;\n}\n'
    )

    for ts in (one_line, wrapped):
        assert _ts_members(ts, "X", "stopped_by") == ['"t"', '"w"', "null"]


def test_the_simulation_schema_sends_every_field_and_names_the_bound() -> None:
    spec = coral_openapi()
    schema = spec["components"]["schemas"]["SimResult"]

    assert set(schema["properties"]) == SIMULATION_FIELDS
    assert set(schema["required"]) == SIMULATION_FIELDS
    bounds = [member for member in schema["properties"]["stopped_by"]["anyOf"] if "enum" in member]
    assert [tuple(member["enum"]) for member in bounds] == [get_args(SimLimit)]
    bound = [*(f'"{name}"' for name in get_args(SimLimit)), "null"]
    assert _ts_members(TS_PATH.read_text(encoding="utf-8"), "SimResult", "stopped_by") == bound
    responses = spec["paths"]["/v1/coral/workflows:simulate"]["post"]["responses"]
    assert set(responses) == {"200", "401", "403", "422", "503"}


# ── Simulate: in flight ─────────────────────────────────────────────────────


def test_the_simulate_caps_are_small() -> None:
    assert (MAX_SIMULATIONS_PER_USER, MAX_SIMULATIONS) == (1, 4)


class _HeldValidation:
    """A validate context whose first ``hold`` uses wait for ``release``, as slow checks would."""

    def __init__(self, hold: int) -> None:
        self.hold = hold
        self.entered = 0
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self) -> ValidateContext:
        with self._lock:
            self.entered += 1
            waits = self.entered <= self.hold
        if waits:
            self.release.wait(timeout=budget(30))
        return _context()


@pytest.fixture
async def async_simulations() -> AsyncIterator[InFlight]:
    threads = BoundedThreads(max_workers=MAX_SIMULATIONS, thread_name_prefix=SIMULATE_THREADS)
    yield InFlight(threads, max_per_caller=MAX_SIMULATIONS_PER_USER)
    threads.close()


async def _held_simulations(
    store: SqlWorkflowDefinitionStore,
    simulations: InFlight,
    holders: list[str],
    caller: str,
) -> tuple[httpx.Response, list[httpx.Response]]:
    """``caller``'s simulation while each of ``holders`` has one waiting in its validation."""
    held = _HeldValidation(hold=len(holders))
    app = _app(store, simulations=simulations, validate_context=held)
    body = {"yaml": fixture_text("minimal")}
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            waiting = [
                asyncio.create_task(client.post(SIMULATE, json=body, headers={HEADER: user}))
                for user in holders
            ]
            await poll_until_async(
                lambda: held.entered == len(holders) == simulations.in_flight,
                timeout_s=budget(10),
            )
            response = await client.post(SIMULATE, json=body, headers={HEADER: caller})
            held.release.set()
            finished = await asyncio.gather(*waiting)
    finally:
        held.release.set()
    return response, finished


async def test_a_simulation_past_the_callers_share_is_busy(
    store: SqlWorkflowDefinitionStore, async_simulations: InFlight
) -> None:
    response, finished = await _held_simulations(
        store, async_simulations, [ALICE] * MAX_SIMULATIONS_PER_USER, ALICE
    )

    assert (response.status_code, response.json()["error"]["code"]) == (503, "server_busy")
    assert response.headers["retry-after"] == "1"
    assert [held.status_code for held in finished] == [200] * MAX_SIMULATIONS_PER_USER


async def test_another_user_simulates_while_one_user_holds_their_share(
    store: SqlWorkflowDefinitionStore, async_simulations: InFlight
) -> None:
    response, _finished = await _held_simulations(
        store, async_simulations, [ALICE] * MAX_SIMULATIONS_PER_USER, BOB
    )

    assert response.status_code == 200, response.text
    assert response.json()["simulation"]["outcome"] == "completed"


async def test_a_full_simulate_pool_refuses_every_caller(
    store: SqlWorkflowDefinitionStore, async_simulations: InFlight
) -> None:
    holders = [
        f"user-{index}"
        for index in range(MAX_SIMULATIONS // MAX_SIMULATIONS_PER_USER)
        for _ in range(MAX_SIMULATIONS_PER_USER)
    ]
    assert len(holders) == MAX_SIMULATIONS

    response, finished = await _held_simulations(store, async_simulations, holders, BOB)

    assert (response.status_code, response.json()["error"]["code"]) == (503, "server_busy")
    assert [held.status_code for held in finished] == [200] * MAX_SIMULATIONS
    assert async_simulations.in_flight == 0


def test_simulate_validates_the_document_on_the_simulate_pool(
    simulator: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[str] = []
    check_text = workflows_api.check_text

    def recording(text: str, context: ValidateContext | None = None) -> CheckResult:
        threads.append(threading.current_thread().name)
        return check_text(text, context)

    monkeypatch.setattr(workflows_api, "check_text", recording)

    _simulation(simulator, fixture_text("minimal"))

    assert len(threads) == 1 and threads[0].startswith(SIMULATE_THREADS)


def test_without_a_simulate_pool_a_signed_in_simulation_is_busy(client: TestClient) -> None:
    response = client.post(SIMULATE, json={"yaml": fixture_text("minimal")})

    assert (response.status_code, response.json()["error"]["code"]) == (503, "server_busy")


class _NoStore:
    """A store any call of which fails the test."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the store was called: {name}")


def test_simulate_reads_and_writes_no_stored_workflow(simulations: InFlight) -> None:
    app = _app(cast(SqlWorkflowDefinitionStore, _NoStore()), simulations=simulations)

    body = _simulation(TestClient(app, headers={HEADER: ALICE}), fixture_text("minimal"))

    assert body["simulation"]["outcome"] == "completed"


CASE_NOT_FOUND = {"error": {"code": "not_found", "message": "Case not found.", "details": None}}
SAVED_CASE_FIELDS = {
    "id",
    "name",
    "script",
    "expect",
    "last_result",
    "mismatches",
    "last_run_at",
    "created_at",
}


def _one_step() -> str:
    return workflow_text(
        [start(), step("work"), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )


def _two_steps() -> str:
    return workflow_text(
        [start(), step("work"), step("check"), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "check"), arrow("a3", "check", "end")],
    )


def _case(name: str = "one step", **expect: Any) -> dict[str, Any]:
    return {
        "name": name,
        "script": {"inputs": []},
        "expect": {"outcome": "completed", "steps": ["work:done"], **expect},
    }


def _cases_path(workflow_id: str) -> str:
    return f"{WORKFLOWS}/{workflow_id}/cases"


def _saved(client: TestClient, yaml_text: str) -> str:
    response = client.post(WORKFLOWS, json={"yaml": yaml_text})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _cases(client: TestClient, workflow_id: str) -> list[dict[str, Any]]:
    response = client.get(_cases_path(workflow_id))
    assert response.status_code == 200, response.text
    return response.json()


def test_a_posted_case_runs_and_fails_once_an_edit_changes_its_path(client: TestClient) -> None:
    workflow_id = _saved(client, _one_step())

    posted = client.post(_cases_path(workflow_id), json=_case())

    assert posted.status_code == 201, posted.text
    body = posted.json()
    assert set(body) == SAVED_CASE_FIELDS
    assert (body["name"], body["last_result"], body["mismatches"]) == ("one step", "passed", [])
    assert (body["last_run_at"], body["created_at"]) == (SAVED_AT, SAVED_AT)
    assert body["expect"]["steps"] == ["work:done"]
    assert _cases(client, workflow_id) == [body]

    assert _saved(client, _two_steps()) == workflow_id

    [failed] = _cases(client, workflow_id)
    assert (failed["id"], failed["last_result"]) == (body["id"], "failed")
    assert failed["mismatches"] == ["steps: expected [work:done], got [work:done, check:done]"]

    assert _saved(client, _one_step()) == workflow_id
    assert _cases(client, workflow_id)[0]["last_result"] == "passed"


def test_a_case_on_a_workflow_that_is_not_runnable_is_an_error_and_never_simulates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        workflows_api, "check_case", lambda *_args, **_kwargs: pytest.fail("simulated")
    )
    workflow_id = _saved(client, fixture_text("deadlock_join"))

    body = client.post(_cases_path(workflow_id), json=_case()).json()

    assert (body["last_result"], body["mismatches"]) == ("error", ["workflow: not runnable"])
    _saved(client, fixture_text("deadlock_join"))
    assert _cases(client, workflow_id)[0]["mismatches"] == ["workflow: not runnable"]


def test_a_mismatch_line_is_clipped_before_it_is_stored(client: TestClient) -> None:
    workflow_id = _saved(client, _one_step())
    long_steps = ["x" * 300] * 3

    body = client.post(_cases_path(workflow_id), json=_case(steps=long_steps)).json()

    [line] = body["mismatches"]
    assert body["last_result"] == "failed"
    assert len(line) == MAX_LOAD_TEXT_CHARS and line.endswith("…")


def test_a_deleted_case_is_gone_and_a_second_delete_is_not_found(client: TestClient) -> None:
    workflow_id = _saved(client, _one_step())
    kept = client.post(_cases_path(workflow_id), json=_case("kept")).json()
    dropped = client.post(_cases_path(workflow_id), json=_case("dropped")).json()

    deleted = client.delete(f"{_cases_path(workflow_id)}/{dropped['id']}")
    again = client.delete(f"{_cases_path(workflow_id)}/{dropped['id']}")

    assert (deleted.status_code, deleted.content) == (204, b"")
    assert (again.status_code, again.json()) == (404, CASE_NOT_FOUND)
    assert [item["id"] for item in _cases(client, workflow_id)] == [kept["id"]]


def test_a_duplicate_name_and_a_case_past_the_cap_are_conflicts(client: TestClient) -> None:
    workflow_id = _saved(client, _one_step())
    for index in range(MAX_WORKFLOW_CASES):
        assert client.post(_cases_path(workflow_id), json=_case(f"c{index}")).status_code == 201

    duplicate = client.post(_cases_path(workflow_id), json=_case("c0"))
    over = client.post(_cases_path(workflow_id), json=_case("extra"))

    assert (duplicate.status_code, duplicate.json()["error"]["code"]) == (409, "case_exists")
    assert (over.status_code, over.json()["error"]["code"]) == (409, "case_limit_reached")
    assert len(_cases(client, workflow_id)) == MAX_WORKFLOW_CASES


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="empty"),
        pytest.param({**_case(), "extra": 1}, id="unknown-field"),
        pytest.param(_case(name=""), id="empty-name"),
        pytest.param(_case(name="x" * 121), id="long-name"),
        pytest.param({**_case(), "expect": {"outcome": "done"}}, id="bad-outcome"),
        pytest.param(_case(steps=["a:done"] * (MAX_EXPECTED_ITEMS + 1)), id="many-steps"),
        pytest.param(_case(gates_reached=["g" * 1000]), id="long-gate"),
    ],
)
def test_a_malformed_or_oversized_case_is_refused_and_stores_nothing(
    client: TestClient, body: dict[str, Any]
) -> None:
    workflow_id = _saved(client, _one_step())

    response = client.post(_cases_path(workflow_id), json=body)

    assert (response.status_code, response.json()["error"]["code"]) == (422, "validation_failed")
    assert _cases(client, workflow_id) == []


def test_a_case_too_large_to_store_is_refused_with_a_fixed_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_id = _saved(client, _one_step())
    monkeypatch.setattr(workflow_store, "MAX_STORED_BYTES", 16)

    response = client.post(_cases_path(workflow_id), json=_case())

    assert (response.status_code, response.json()) == (
        413,
        {
            "error": {
                "code": "payload_too_large",
                "message": "The case is too large to store.",
                "details": None,
            }
        },
    )
    monkeypatch.undo()
    assert _cases(client, workflow_id) == []


@pytest.mark.parametrize("workflow_id", ["0" * 32, "x" * 300, "%00"])
def test_the_case_routes_of_an_unknown_workflow_are_not_found(
    client: TestClient, workflow_id: str
) -> None:
    for response in (
        client.get(_cases_path(workflow_id)),
        client.post(_cases_path(workflow_id), json=_case()),
        client.delete(f"{_cases_path(workflow_id)}/{'0' * 32}"),
    ):
        assert (response.status_code, response.json()) == (404, NOT_FOUND)


def test_another_users_workflow_cases_are_not_found_on_every_case_route(
    store: SqlWorkflowDefinitionStore,
) -> None:
    alice, bob = _client(store), _client(store, BOB)
    workflow_id = _saved(alice, _one_step())
    case_id = alice.post(_cases_path(workflow_id), json=_case()).json()["id"]

    for response in (
        bob.get(_cases_path(workflow_id)),
        bob.post(_cases_path(workflow_id), json=_case("bobs")),
        bob.delete(f"{_cases_path(workflow_id)}/{case_id}"),
    ):
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert [item["id"] for item in _cases(alice, workflow_id)] == [case_id]


def test_a_case_of_another_workflow_is_not_found_through_this_one(client: TestClient) -> None:
    first = _saved(client, _one_step())
    other = _saved(client, fixture_text("loop"))
    case_id = client.post(_cases_path(first), json=_case()).json()["id"]

    for case_path in (case_id, "x" * 300):
        response = client.delete(f"{_cases_path(other)}/{case_path}")
        assert (response.status_code, response.json()) == (404, CASE_NOT_FOUND)
    assert len(_cases(client, first)) == 1


def test_every_case_route_needs_a_permitted_caller(store: SqlWorkflowDefinitionStore) -> None:
    workflow_id = _saved(_client(store), _one_step())
    path = _cases_path(workflow_id)

    for client, status, code in (
        (_client(store, user=None), 401, "unauthenticated"),
        (_client(store, auth_provider=CROSSED_ACCOUNT), 403, "not_permitted"),
    ):
        for response in (
            client.get(path),
            client.post(path, json=_case()),
            client.delete(f"{path}/{'0' * 32}"),
        ):
            assert (response.status_code, response.json()["error"]["code"]) == (status, code)
    assert _cases(_client(store), workflow_id) == []


def test_the_case_routes_declare_their_refusals() -> None:
    paths = coral_openapi()["paths"]
    cases = paths[f"{WORKFLOWS}/{{workflow_id}}/cases"]
    one = paths[f"{WORKFLOWS}/{{workflow_id}}/cases/{{case_id}}"]

    assert {
        cases["get"]["operationId"]: set(cases["get"]["responses"]),
        cases["post"]["operationId"]: set(cases["post"]["responses"]),
        one["delete"]["operationId"]: set(one["delete"]["responses"]),
    } == {
        "coral_list_workflow_cases": {"200", "401", "403", "404", "422"},
        "coral_save_workflow_case": {"201", "401", "403", "404", "409", "413", "422"},
        "coral_delete_workflow_case": {"204", "401", "403", "404", "422"},
    }


def test_an_unchanged_resave_keeps_each_cases_result(client: TestClient) -> None:
    workflow_id = _saved(client, _one_step())
    passing = client.post(_cases_path(workflow_id), json=_case("passing")).json()
    failing = client.post(_cases_path(workflow_id), json=_case("failing", steps=[])).json()

    assert _saved(client, _one_step()) == workflow_id

    assert _cases(client, workflow_id) == [failing, passing]
    assert failing["last_result"] == "failed"


def test_cases_are_listed_by_creation_then_name(store: SqlWorkflowDefinitionStore) -> None:
    now = [SAVED_AT]
    store._clock = lambda: now[0]
    client = _client(store)
    workflow_id = _saved(client, _one_step())
    for at, name in ((SAVED_AT, "zeta"), (SAVED_AT + 1, "beta"), (SAVED_AT + 1, "alpha")):
        now[0] = at
        assert client.post(_cases_path(workflow_id), json=_case(name)).status_code == 201

    assert [item["name"] for item in _cases(client, workflow_id)] == ["zeta", "alpha", "beta"]


def test_a_draft_that_cannot_run_marks_its_cases_error_until_a_fix_passes_them(
    client: TestClient,
) -> None:
    workflow_id = _saved(client, _one_step())
    case_id = client.post(_cases_path(workflow_id), json=_case()).json()["id"]
    broken = workflow_text([start(), step("work"), end()], [arrow("a1", "start", "work")])

    assert _saved(client, broken) == workflow_id
    [errored] = _cases(client, workflow_id)
    assert (errored["id"], errored["last_result"]) == (case_id, "error")
    assert errored["mismatches"] == ["workflow: not runnable"]

    assert _saved(client, _one_step()) == workflow_id
    [fixed] = _cases(client, workflow_id)
    assert (fixed["id"], fixed["last_result"], fixed["mismatches"]) == (case_id, "passed", [])


def test_a_save_whose_case_rerun_fails_in_the_store_still_answers_its_save(
    store: SqlWorkflowDefinitionStore, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_id = _saved(client, _one_step())
    client.post(_cases_path(workflow_id), json=_case())

    def refuse(**_kwargs: object) -> None:
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    monkeypatch.setattr(store, "record_case_runs", refuse)

    assert _saved(client, _one_step()) == workflow_id


def test_a_refused_case_is_refused_before_it_is_simulated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow_id = _saved(client, _one_step())
    assert client.post(_cases_path(workflow_id), json=_case()).status_code == 201
    runs: list[object] = []
    monkeypatch.setattr(workflows_api, "check_case", lambda *args, **kwargs: runs.append(args))

    response = client.post(_cases_path(workflow_id), json=_case())

    assert (response.status_code, response.json()["error"]["code"]) == (409, "case_exists")
    assert runs == []
