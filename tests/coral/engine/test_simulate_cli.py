"""The Simulate CLI prints the body ``POST /v1/coral/workflows:simulate`` returns."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from coral.api.run_service import InFlight
from coral.api.workflows import create_workflows_router
from coral.bridge.executors import BoundedThreads
from coral.db.models_workflows import CoralBase
from coral.engine.simulate import main
from coral.omni.server.access import request_viewer
from coral.stores.workflows import SqlWorkflowDefinitionStore
from coral.templates import builtin_templates
from omnigent.server.auth import UnifiedAuthProvider
from tests.coral.api._auth import HEADER
from tests.coral.workflow_builders import fixture_text

TEMPLATE = builtin_templates()[0]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    engine = create_engine(f"sqlite:///{tmp_path / 'coral.db'}")
    CoralBase.metadata.create_all(engine)
    threads = BoundedThreads(max_workers=1, thread_name_prefix="test-simulate-cli")
    pool = InFlight(threads, max_per_caller=1)
    app = FastAPI()
    app.include_router(
        create_workflows_router(
            SqlWorkflowDefinitionStore(engine),
            viewer_dependency=request_viewer(
                UnifiedAuthProvider(source="header", local_single_user=False, header_name=HEADER)
            ),
            workspace_id_dependency=lambda: 1,
            simulations=lambda _request: pool,
        ),
        prefix="/v1/coral",
    )
    yield TestClient(app, headers={HEADER: "alice"})
    threads.close()
    engine.dispose()


def _route(client: TestClient, text: str, script: Any) -> Any:
    response = client.post("/v1/coral/workflows:simulate", json={"yaml": text, "script": script})
    assert response.status_code == 200, response.text
    return response.json()


def _cli(tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, script: Any) -> Any:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(text, encoding="utf-8")
    script_file = tmp_path / "script.json"
    script_file.write_text(json.dumps(script), encoding="utf-8")
    assert main([str(workflow), "--script", str(script_file)]) == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize(
    ("text", "script"),
    [
        *(
            pytest.param(TEMPLATE.yaml_text, case.script.model_dump(mode="json"), id=case.name)
            for case in TEMPLATE.cases
        ),
        pytest.param(TEMPLATE.yaml_text, {}, id="needs input"),
        pytest.param(fixture_text("deadlock_join"), {}, id="not runnable"),
        pytest.param("id: [oops", {}, id="does not load"),
        pytest.param("id: x\n#" + "a" * 256 * 1024 + "\n", {}, id="oversized"),
    ],
)
def test_the_cli_prints_what_the_route_returns(
    client: TestClient,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    text: str,
    script: Any,
) -> None:
    assert _cli(tmp_path, capsys, text, script) == _route(client, text, script)


def test_without_a_script_the_cli_simulates_with_an_empty_one(
    client: TestClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(TEMPLATE.yaml_text, encoding="utf-8")

    assert main([str(workflow)]) == 0
    body = json.loads(capsys.readouterr().out)

    assert body == _route(client, TEMPLATE.yaml_text, {})
    assert body["simulation"]["outcome"] == "needs_input"


def test_a_yaml_script_is_read_like_a_json_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(TEMPLATE.yaml_text, encoding="utf-8")
    script = tmp_path / "script.yaml"
    script.write_text("inputs:\n  - {node_id: review, kind: label, values: [approved]}\n")

    assert main([str(workflow), "--script", str(script)]) == 0

    simulation = json.loads(capsys.readouterr().out)["simulation"]
    assert simulation["needs_input"]["node_id"] == "approve_change"


@pytest.mark.parametrize(
    "script",
    [
        None,
        b"",
        b"inputs: [",
        b"\xff\xfe",
        b"inputs: 3",
        b'{"inputs": [], "extra": "secret-value"}',
        b"inputs: []\nextra: !!binary c2VjcmV0LXZhbHVl\n",
        b"base: &x []\ninputs: *x\n",
    ],
)
def test_an_unreadable_file_or_invalid_script_exits_2_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], script: bytes | None
) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(TEMPLATE.yaml_text, encoding="utf-8")
    script_file = tmp_path / "script.json"
    if script is not None:
        script_file.write_bytes(script)

    assert main([str(workflow), "--script", str(script_file)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.strip().splitlines()) == 1
    assert "secret-value" not in captured.err


def test_a_missing_or_non_utf8_workflow_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    binary = tmp_path / "binary.yaml"
    binary.write_bytes(b"\xff\xfe")

    for path in (tmp_path / "missing.yaml", binary):
        assert main([str(path)]) == 2
        captured = capsys.readouterr()
        assert (captured.out, len(captured.err.strip().splitlines())) == ("", 1)


def test_python_dash_m_runs_the_cli(tmp_path: Path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(TEMPLATE.yaml_text, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-m", "coral.engine.simulate", str(workflow)],
        capture_output=True,
        check=True,
        text=True,
    )

    assert json.loads(completed.stdout)["simulation"]["outcome"] == "needs_input"
