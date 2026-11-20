"""The checked-in workflow Inbox contract is what the backend and the live session routes give."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from coral.gates.ids import GATE_ELICITATION_ID
from omnigent.runtime import pending_elicitations
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server import elicitation_hooks
from omnigent.server.app import create_app
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store import ConversationStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from tests.coral.api.inbox_contract import CONTRACT_PATH, build_contract

ANCHOR_ROW_FIELDS = ("id", "labels", "pending_elicitations_count")


def _checked_in() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def clean_prompts() -> Iterator[None]:
    yield
    pending_elicitations.reset_for_tests()
    elicitation_hooks.reset_for_tests()


def test_the_checked_in_contract_equals_what_the_backend_builds() -> None:
    # On a mismatch: uv run --no-sync python -m tests.coral.api.inbox_contract --write
    assert _checked_in() == build_contract()


@pytest.mark.usefixtures("clean_prompts")
def test_the_session_routes_show_the_anchor_as_the_contract_does(
    db_uri: str, tmp_path: Path
) -> None:
    # The anchor's row and prompts read through the live routes, not the index they read.
    artifact = LocalArtifactStore(str(tmp_path / "artifacts"))
    conversations = SqlAlchemyConversationStore(db_uri)
    agents = SqlAlchemyAgentStore(db_uri)
    # Anchors are bound to Coral's hidden anchor agent; the list shows only bound sessions.
    anchor_agent = agents.create("ag_" + "a" * 32, "coral-anchor", "unused/bundle")
    app = create_app(
        agent_store=agents,
        file_store=SqlAlchemyFileStore(db_uri),
        conversation_store=conversations,
        artifact_store=artifact,
        agent_cache=AgentCache(artifact_store=artifact, cache_dir=tmp_path / "cache"),
        host_store=HostStore(db_uri),
        project_store=SqlAlchemyProjectStore(db_uri),
    )
    client = TestClient(app)

    def read_routes(
        _store: ConversationStore, anchor_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        listed = client.get("/v1/sessions", params={"limit": 100})
        assert listed.status_code == 200, listed.text
        (row,) = (row for row in listed.json()["data"] if row["id"] == anchor_id)
        snapshot = client.get(f"/v1/sessions/{anchor_id}")
        assert snapshot.status_code == 200, snapshot.text
        anchor_row = {field: row[field] for field in ANCHOR_ROW_FIELDS}
        return anchor_row, snapshot.json()["pending_elicitations"]

    built = build_contract(
        conversations=conversations, anchor_agent_id=anchor_agent.id, read_anchor=read_routes
    )

    assert built == _checked_in()


def test_the_contract_holds_one_joinable_gate_and_one_mirrored_step_prompt() -> None:
    contract = _checked_in()
    anchor = contract["anchor_row"]
    gate_alert, pause_alert = sorted(
        contract["inbox_page"]["data"], key=lambda alert: alert["kind"] != "gate"
    )
    gate_event, mirrored = contract["pending_elicitations"]

    assert (gate_alert["kind"], pause_alert["kind"]) == ("gate", "pause")
    assert pause_alert["elicitation_id"] is None
    # The gate's prompt and its alert join by prompt id on the run's anchor.
    assert GATE_ELICITATION_ID.fullmatch(gate_event["elicitation_id"])
    assert gate_alert["elicitation_id"] == gate_event["elicitation_id"]
    assert gate_alert["session_id"] == anchor["id"]
    assert gate_event["params"]["target_session_id"] is None
    assert gate_event["params"]["coral"]["run_id"] == anchor["labels"]["coral.run_id"]
    # A step's prompt mirrored onto the anchor names the step it is answered on.
    assert mirrored["elicitation_id"].startswith("elicit_")
    assert mirrored["params"]["target_session_id"] not in (None, anchor["id"])
