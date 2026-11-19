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

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from coral.db.enum_codecs import RunStatus
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID
from omnigent.runtime import pending_elicitations
from omnigent.server import elicitation_hooks
from omnigent.server.auth import LEVEL_EDIT
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from tests._helpers.polling import poll_until
from tests.budgets import budget
from tests.coral.omni._gate_server import (
    CORAL_SERVER_PLUGIN,
    INBOX,
    gate_answers,
    gate_run,
    pending_here,
    run_status,
)
from tests.server.test_accounts import _build_accounts_app, _login

ADMIN_PASSWORD = "admin-pw-12345"
NOT_PERMITTED = "[not_permitted] Only the run owner can answer this gate."


@dataclass
class _Accounts:
    admin: TestClient
    alice: TestClient
    # ``create_app``'s keyword arguments: the server's stores and auth provider.
    stores: dict[str, Any]


def _register(admin: TestClient, username: str, password: str) -> TestClient:
    """A new client signed in as ``username``, registered through an admin's invite."""
    invite = admin.post("/auth/invite", json={}).json()["token"]
    client = TestClient(admin.app)
    response = client.post(
        "/auth/register", json={"invite": invite, "username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, coral_policy_registry: None
) -> Iterator[_Accounts]:
    import omnigent.server.app as app_module

    original = app_module.create_app
    captured: dict[str, Any] = {}

    def with_coral(**kwargs: Any) -> FastAPI:
        # Run anchors are filed in their owner's project, so the session engine needs one.
        db_uri = kwargs["conversation_store"].storage_location
        kwargs["project_store"] = SqlAlchemyProjectStore(db_uri)
        captured.update(kwargs)
        return original(**kwargs, server_plugins=[CORAL_SERVER_PLUGIN])

    monkeypatch.setattr(app_module, "create_app", with_coral)
    clients = _build_accounts_app(tmp_path, monkeypatch, init_admin_password=ADMIN_PASSWORD)
    admin = next(clients)
    try:
        _login(admin, "admin", ADMIN_PASSWORD)
        yield _Accounts(admin, _register(admin, "alice", "alice-pw-1234"), captured)
    finally:
        # Resuming the builder past its yield shuts the app down.
        next(clients, None)
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
    accounts: _Accounts,
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
    replacement = _register(accounts.admin, "alice", "alice-new-pw-1234")
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


def test_a_password_change_keeps_the_owner_s_gates_and_alerts(accounts: _Accounts) -> None:
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
        json={"old_password": "alice-pw-1234", "new_password": "alice-new-pw-1234"},
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
