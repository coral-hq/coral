"""
The checked-in Coral OpenAPI document and the web's types for it: current, complete for
every mounted route, and typed.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import create_engine

from coral.api.schemas import CORAL_API_VERSION
from coral.api.sub_features import resolve_sub_features
from coral.omni.server import openapi as coral_openapi
from coral.omni.server.openapi_ts import TS_PATH, render_coral_api_types
from coral.omni.server.plugin import RouterSpec, coral_routers, register
from coral.stores.workflows import SqlWorkflowDefinitionStore
from dev.lint.lint_no_hardcoded_models import MODEL_ID_RE
from omnigent.process_logging import DATA_DIR_ENV_VAR

SPEC_PATH = Path(__file__).resolve().parents[3] / "coral" / "api" / "openapi.json"
ERROR_SCHEMA = {"$ref": "#/components/schemas/CoralErrorResponse"}
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
MAX_DIFF_LINES = 60
# Top-level lines a module of type declarations may hold.
TYPE_DECLARATION = re.compile(r"(export (interface|type) |}|/\*\*|\*|//)")


def _spec() -> dict[str, Any]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _operations(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method.upper(), path): operation
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def _mounted(routers: tuple[RouterSpec, ...]) -> set[tuple[str, str, tuple[str, ...]]]:
    return {
        (method, prefix + route.path, tuple(tags))
        for router, prefix, tags in routers
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


@pytest.mark.parametrize(
    ("path", "render"),
    [
        pytest.param(SPEC_PATH, coral_openapi.render_openapi, id="openapi.json"),
        pytest.param(TS_PATH, render_coral_api_types, id="coralApi.ts"),
    ],
)
def test_the_checked_in_file_is_current(
    path: Path, render: Callable[[dict[str, Any]], str]
) -> None:
    expected = render(coral_openapi.coral_openapi())
    current = path.read_text(encoding="utf-8")

    if current != expected:
        diff = list(
            difflib.unified_diff(
                current.splitlines(), expected.splitlines(), "checked in", "generated", lineterm=""
            )
        )
        pytest.fail(
            f"{path.name} is stale; run `just coral openapi`.\n" + "\n".join(diff[:MAX_DIFF_LINES])
        )


def test_check_refuses_stale_files_and_accepts_current_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_path, ts_path = tmp_path / "openapi.json", tmp_path / "coralApi.ts"
    spec_path.write_text("{}\n", encoding="utf-8")
    ts_path.write_text("", encoding="utf-8")

    assert coral_openapi.export(spec_path, ts_path, check=True) == 1
    assert capsys.readouterr().err.count("run `just coral openapi`") == 2
    assert (spec_path.read_text(encoding="utf-8"), ts_path.read_text(encoding="utf-8")) == (
        "{}\n",
        "",
    )

    assert coral_openapi.export(spec_path, ts_path) == 0
    assert coral_openapi.export(spec_path, ts_path, check=True) == 0
    assert spec_path.read_text(encoding="utf-8") == SPEC_PATH.read_text(encoding="utf-8")
    assert ts_path.read_text(encoding="utf-8") == TS_PATH.read_text(encoding="utf-8")


def test_the_generated_types_declare_types_only() -> None:
    top_level = [
        line
        for line in TS_PATH.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith(" ")
    ]

    assert [line for line in top_level if not TYPE_DECLARATION.match(line)] == []
    assert "export interface CoralOperations {" in top_level


def test_the_plugin_mounts_exactly_the_router_table_and_the_spec_lists_every_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DATA_DIR_ENV_VAR, str(tmp_path))
    services = cast(Any, SimpleNamespace(host_sharded=False, server_config={}, auth_provider=None))
    table = coral_routers(
        sub_features=resolve_sub_features(None),
        definitions=SqlWorkflowDefinitionStore(create_engine("sqlite://")),
        auth_provider=None,
    )

    registered = _mounted(register(services).routers)

    assert registered == _mounted(table)
    assert {(method, path) for method, path, _tags in registered} == set(_operations(_spec()))
    assert {tags for _method, _path, tags in registered} == {("coral",)}


def test_every_operation_is_named_and_typed() -> None:
    spec = _spec()
    operations = _operations(spec)
    operation_ids = [operation["operationId"] for operation in operations.values()]

    assert all(name.startswith("coral_") for name in operation_ids)
    assert len(set(operation_ids)) == len(operation_ids)
    # Every refusal is the Coral envelope, so FastAPI's own 422 body never appears.
    assert "HTTPValidationError" not in spec["components"]["schemas"]
    for (method, path), operation in operations.items():
        for status, response in operation["responses"].items():
            content = response.get("content", {})
            if status.startswith(("4", "5")):
                assert content["application/json"]["schema"] == ERROR_SCHEMA, (method, path)
            elif status in ("204", "304"):
                assert content == {}, (method, path)
            else:
                schema = content["application/json"]["schema"]
                assert _is_typed(schema), (method, path, status, schema)


def _is_typed(schema: dict[str, Any]) -> bool:
    """A named model, a list of them, or a choice between them; never a free-form object."""
    if set(schema) == {"$ref"}:
        return True
    if schema.get("type") == "array":
        return _is_typed(schema["items"])
    if "anyOf" in schema:
        return all(_is_typed(member) for member in schema["anyOf"])
    return False


def test_the_spec_is_oas_3_1_at_the_contract_version_with_no_servers_or_model_ids() -> None:
    spec = _spec()

    assert spec["openapi"].startswith("3.1.")
    assert spec["info"] == {"title": "Coral API", "version": CORAL_API_VERSION}
    assert "servers" not in spec
    assert MODEL_ID_RE.findall(SPEC_PATH.read_text(encoding="utf-8")) == []
