"""Who may answer a gate and read its alerts on a multi-user server with header auth.

alice owns the run. bob holds an edit grant on its anchor, written to the store
(a client cannot grant on a run session); carol is an admin. Omnigent lets all
three post to the anchor; the gate handler takes alice's answer alone, refusing
the others with the prompt left pending, and only alice sees or acks her alerts.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from coral.db.enum_codecs import RunStatus
from coral.omni.server import coral_lifespan
from omnigent.runtime import pending_elicitations
from omnigent.server import elicitation_hooks
from omnigent.server.auth import LEVEL_EDIT, UnifiedAuthProvider
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.omni._gate_server import (
    CORAL_SERVER_PLUGIN,
    CoralServer,
    ack,
    coral_server,
    gate_answers,
    gate_run,
    inbox,
    pending_prompts,
    prompt_shown,
    resolve_gate,
    run_status,
)

ALICE = "alice@example.com"
BOB = "bob@example.com"
CAROL = "carol@example.com"
HEADER = "X-Forwarded-Email"
NOT_PERMITTED = "[not_permitted] Only the run owner can answer this gate."


def _as(user: str) -> dict[str, str]:
    return {HEADER: user}


@pytest.fixture
def permissions(db_uri: str) -> SqlAlchemyPermissionStore:
    store = SqlAlchemyPermissionStore(db_uri)
    store.ensure_user(CAROL, is_admin=True)
    return store


@pytest.fixture
def server(
    db_uri: str, tmp_path: Path, permissions: SqlAlchemyPermissionStore
) -> Iterator[CoralServer]:
    yield coral_server(
        db_uri,
        tmp_path,
        auth_provider=UnifiedAuthProvider(
            source="header", local_single_user=False, header_name=HEADER
        ),
        permission_store=permissions,
        server_plugins=[CORAL_SERVER_PLUGIN],
    )
    # Prompts and the verdict handler outlive a lifespan in this process's registries.
    pending_elicitations.reset_for_tests()
    elicitation_hooks.reset_for_tests()


async def test_only_the_run_owner_answers_the_gate_and_sees_its_alerts(
    server: CoralServer, permissions: SqlAlchemyPermissionStore
) -> None:
    world, run, anchor, prompt = gate_run(server.db_uri, user=ALICE)
    transport = httpx.ASGITransport(app=server.app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
        coral_lifespan(server.app, server.services),
    ):
        await poll_until_async(lambda: prompt_shown(server, anchor, prompt), timeout_s=budget(30))
        permissions.grant(BOB, anchor, LEVEL_EDIT)
        shown = await pending_prompts(client, anchor, _as(ALICE))
        [gate_alert] = await inbox(client, _as(ALICE))
        refused = [
            await resolve_gate(client, anchor, prompt, headers=_as(user)) for user in (BOB, CAROL)
        ]
        still_pending = await pending_prompts(client, anchor, _as(ALICE))
        bob_feed = await inbox(client, _as(BOB))
        bob_ack_gate = await ack(client, gate_alert["alert_id"], _as(BOB))
        first = await resolve_gate(client, anchor, prompt, headers=_as(ALICE))
        repeat = await resolve_gate(client, anchor, prompt, headers=_as(ALICE))
        late = await resolve_gate(client, anchor, prompt, headers=_as(BOB))
        [ended] = await inbox(client, _as(ALICE))
        bob_ack_end = await ack(client, ended["alert_id"], _as(BOB))
        alice_ack_end = await ack(client, ended["alert_id"], _as(ALICE))
        alice_feed_at_end = await inbox(client, _as(ALICE))

    assert [item["elicitation_id"] for item in shown] == [prompt]
    assert (gate_alert["kind"], gate_alert["elicitation_id"]) == ("gate", prompt)
    # The editor and the admin reach the handler and are refused; the gate still waits.
    assert [
        (response.status_code, response.json()["error"]["message"]) for response in refused
    ] == [(403, NOT_PERMITTED)] * 2
    assert still_pending == shown
    assert (bob_feed, bob_ack_gate.status_code) == ([], 404)
    assert (first.status_code, first.json()) == (202, {"queued": False})
    assert (repeat.status_code, repeat.json()) == (202, {"queued": False, "duplicate": True})
    assert (late.status_code, late.json()["error"]["message"]) == (403, NOT_PERMITTED)
    assert [(answer.label, answer.by) for answer in gate_answers(world, run.id)] == [
        ("approve", ALICE)
    ]
    assert run_status(world, run) == int(RunStatus.COMPLETED)
    # The gate's alert cleared with the answer; only alice may mark the run's end read.
    assert ended["kind"] == "run_completed"
    assert (bob_ack_end.status_code, alice_ack_end.status_code) == (404, 204)
    assert alice_feed_at_end == []
