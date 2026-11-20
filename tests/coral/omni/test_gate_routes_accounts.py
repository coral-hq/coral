"""Gates and alerts follow the account registration: across a password change, not a re-creation.

The real accounts-mode server, with Coral's routers mounted and its lifespan run
by the app. A password change rotates alice's account generation and carries her
runs and alerts with it, so she still answers her gate and reads her alerts. A
deleted and re-registered ``alice`` is a new registration: it sees and acks none
of the old one's alerts. Omnigent refuses it the anchor (the deletion removed her
grants); with a grant written back to the store, the gate handler still refuses
it, since its generation is not the one the run recorded.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from coral.db.enum_codecs import RunStatus
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID
from omnigent.runtime import pending_elicitations
from omnigent.server import elicitation_hooks
from omnigent.server.auth import LEVEL_EDIT
from tests._helpers.polling import poll_until
from tests.budgets import budget
from tests.coral.omni._gate_server import (
    ALICE_PASSWORD,
    INBOX,
    AccountsServer,
    accounts_server,
    gate_answers,
    gate_run,
    pending_here,
    register,
    run_status,
)
from tests.coral.workflow_builders import fixture_text

NOT_PERMITTED = "[not_permitted] Only the run owner can answer this gate."
RUNS = "/v1/coral/runs"


@pytest.fixture
def accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, coral_policy_registry: None
) -> Iterator[AccountsServer]:
    try:
        with accounts_server(tmp_path, monkeypatch) as server:
            yield server
    finally:
        # Prompts and the verdict handler outlive a lifespan in this process's registries.
        pending_elicitations.reset_for_tests()
        elicitation_hooks.reset_for_tests()


def _resolve(client: TestClient, session_id: str, elicitation_id: str) -> Any:
    return client.post(
        f"/v1/sessions/{session_id}/elicitations/{elicitation_id}/resolve",
        json={"action": "accept", "content": {"decision": "approve"}},
    )


def _feed(client: TestClient) -> list[dict[str, Any]]:
    response = client.get(INBOX)
    assert response.status_code == 200, response.text
    assert response.json()["next_cursor"] is None
    return list(response.json()["data"])


def test_a_re_created_account_is_refused_the_gates_and_alerts_of_the_one_before(
    accounts: AccountsServer,
) -> None:
    account_store = accounts.stores["account_store"]
    db_uri = account_store.storage_location
    generation = account_store.get_user("alice").account_generation
    world, answered_run, answered_anchor, answered_prompt = gate_run(
        db_uri, "gate-a", user="alice", account_generation=generation
    )
    _, waiting_run, anchor, prompt = gate_run(
        db_uri, "gate-b", user="alice", account_generation=generation
    )
    poll_until(
        lambda: pending_here(answered_anchor, answered_prompt) and pending_here(anchor, prompt),
        timeout_s=budget(30),
        interval_s=0.05,
    )
    shown = accounts.alice.get(f"/v1/sessions/{anchor}").json()["pending_elicitations"]
    gates = _feed(accounts.alice)
    answered = _resolve(accounts.alice, answered_anchor, answered_prompt)
    before = {alert["kind"]: alert["alert_id"] for alert in _feed(accounts.alice)}

    assert accounts.admin.delete("/auth/users/alice").status_code == 204
    replacement = register(accounts.admin, "alice", "alice-new-pw-1234")
    assert account_store.get_user("alice").account_generation != generation
    feed = _feed(replacement)
    acks = [
        replacement.post(f"{INBOX}/{alert_id}/ack", json={}).status_code
        for alert_id in before.values()
    ]
    without_grant = _resolve(replacement, anchor, prompt)
    # As if a grant on the anchor had survived the deletion.
    accounts.stores["permission_store"].grant("alice", anchor, LEVEL_EDIT)
    with_grant = _resolve(replacement, anchor, prompt)

    assert [item["elicitation_id"] for item in shown] == [prompt]
    assert sorted((alert["kind"], alert["elicitation_id"]) for alert in gates) == sorted(
        [("gate", answered_prompt), ("gate", prompt)]
    )
    # The generation the runs recorded answers.
    assert (answered.status_code, answered.json()) == (202, {"queued": False})
    assert sorted(before) == ["gate", "run_completed"]
    assert (feed, acks) == ([], [404, 404])
    assert (without_grant.status_code, with_grant.status_code) == (404, 403)
    assert with_grant.json()["error"]["message"] == NOT_PERMITTED
    assert pending_here(anchor, prompt)
    assert [answer.by for answer in gate_answers(world, answered_run.id)] == ["alice"]
    assert (gate_answers(world, waiting_run.id), run_status(world, waiting_run)) == (
        [],
        int(RunStatus.RUNNING),
    )


def test_a_password_change_keeps_the_owner_s_gates_and_alerts(accounts: AccountsServer) -> None:
    account_store = accounts.stores["account_store"]
    db_uri = account_store.storage_location
    generation = account_store.get_user("alice").account_generation
    world, run, anchor, prompt = gate_run(
        db_uri, "gate-c", user="alice", account_generation=generation
    )
    poll_until(lambda: pending_here(anchor, prompt), timeout_s=budget(30), interval_s=0.05)
    before = _feed(accounts.alice)

    changed = accounts.alice.post(
        "/auth/users/me/password",
        json={"old_password": ALICE_PASSWORD, "new_password": "alice-new-pw-1234"},
    )
    rotated = account_store.get_user("alice").account_generation
    carried = world.runs.get_run(run.id, workspace_id=DEFAULT_WORKSPACE_ID)
    after = _feed(accounts.alice)
    answered = _resolve(accounts.alice, anchor, prompt)
    at_end = _feed(accounts.alice)

    assert changed.status_code == 204, changed.text
    assert rotated not in (None, generation)
    assert carried is not None and carried.account_generation == rotated
    # The same gate alert stays in her feed, and her answer is taken.
    assert [(alert["kind"], alert["elicitation_id"]) for alert in before] == [("gate", prompt)]
    assert after == before
    assert (answered.status_code, answered.json()) == (202, {"queued": False})
    assert [answer.by for answer in gate_answers(world, run.id)] == ["alice"]
    assert run_status(world, run) == int(RunStatus.COMPLETED)
    # The run's end, raised after the change, is hers too.
    assert [alert["kind"] for alert in at_end] == ["run_completed"]


def test_an_accounts_server_starts_a_run_only_for_a_request_that_proves_its_account(
    accounts: AccountsServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The plugin's definitions file is shared by this worker's tests: a key of its own.
    key = f"accounts-{uuid.uuid4().hex[:12]}"
    yaml_text = fixture_text("two_steps").replace("id: two-steps", f"id: {key}")
    saved = accounts.alice.post("/v1/coral/workflows", json={"yaml": yaml_text})
    assert saved.status_code == 200, saved.text
    body = {
        "workflow_id": saved.json()["id"],
        "start_key": "accounts",
        "host_id": "host-1",
        "repo_path": "/repo/coral",
    }

    proven = accounts.alice.post(RUNS, json=body)
    # As a request that reached the routes without an account authority would be.
    monkeypatch.setattr("coral.omni.server.access.current_account_user", lambda: None)
    unproven = accounts.alice.post(RUNS, json=body)

    # Her request passes the account check and reaches the host's, which knows no such host.
    assert proven.json()["error"] == {
        "code": "not_permitted",
        "message": "Host 'host-1' is not available to this user.",
        "details": None,
    }
    assert unproven.json()["error"] == {
        "code": "not_permitted",
        "message": "Starting a run needs a request that proves its account.",
        "details": None,
    }
