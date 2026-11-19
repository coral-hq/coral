"""
Integration tests for the elicitation REST API endpoints.

Covers the ``GET`` and ``POST`` elicitation endpoints exercised as a
standalone REST flow (no REPL, no SSE client). The companion file
``test_sessions_elicitation_resolve_url.py`` covers the round-trip
resolve path (park a real Future, resolve via URL, assert the hook
returns the correct decision). This file fills the remaining gaps:

- GET returns the correct pending-request shape (fields, types).
- POST resolve for an already-resolved elicitation is idempotent (202).
- GET after resolution returns ``status: "resolved"``.
- GET/POST against a valid session with a nonexistent elicitation id.

Uses the shared ``client`` fixture (real stores + mock LLM) and the
``_park_permission_hook`` helper from the resolve-URL module to create
real parked elicitations without duplicating the hook machinery.
"""

from __future__ import annotations

# CORAL(S6a, S6b): Iterator, Any, the hooks, the access levels and the permission store
# serve the claimed-id tests at the end of this file.
import asyncio
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from omnigent.runtime import pending_elicitations
from omnigent.server import _elicitation_registry
from omnigent.server.auth import LEVEL_EDIT, LEVEL_READ
from omnigent.server.elicitation_hooks import (
    ElicitationVerdict,
    VerdictDecision,
    publish_form_elicitation,
    register_elicitation_verdict_handler,
)
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from tests.server.helpers import create_test_agent

# Re-use the hook-parking helpers from the sibling module so we don't
# duplicate the SSE-drain + PermissionRequest machinery.
from tests.server.integration.test_sessions_elicitation_resolve_url import (
    _create_child_session,  # CORAL(S6b)
    _create_session,
    _park_permission_hook,
)

pytestmark = pytest.mark.asyncio


# ── GET /sessions/{id}/elicitations/{eid} ────────────────


async def test_get_pending_elicitation_shape(client: httpx.AsyncClient) -> None:
    """
    GET on a pending elicitation returns status "pending" with the
    expected top-level keys and correct types.
    """
    from omnigent.runtime import pending_elicitations

    agent = await create_test_agent(client, "test-get-pending-shape")
    session_id = await _create_session(client, agent["id"])
    hook_task, elicitation_id = await _park_permission_hook(client, session_id)

    try:
        resp = await client.get(
            f"/v1/sessions/{session_id}/elicitations/{elicitation_id}",
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Shape assertions: every expected key present with correct type.
        assert data["status"] == "pending"
        assert isinstance(data["message"], str) and data["message"]
        assert isinstance(data["phase"], str)
        assert isinstance(data["policy_name"], str)
        assert isinstance(data["content_preview"], str)

        # Clean up: resolve so the hook doesn't leak.
        await client.post(
            f"/v1/sessions/{session_id}/elicitations/{elicitation_id}/resolve",
            json={"action": "decline"},
        )
        async with asyncio.timeout(5):
            _ = await hook_task
    finally:
        if not hook_task.done():
            hook_task.cancel()
            await asyncio.gather(hook_task, return_exceptions=True)
        pending_elicitations.reset_for_tests()


async def test_get_nonexistent_elicitation_on_valid_session(
    client: httpx.AsyncClient,
) -> None:
    """
    GET with a valid session but unknown elicitation id returns
    ``status: "resolved"`` (not 404), since the elicitation may have
    been resolved before the page loaded.
    """
    agent = await create_test_agent(client, "test-get-nonexistent-eid")
    session_id = await _create_session(client, agent["id"])

    resp = await client.get(
        f"/v1/sessions/{session_id}/elicitations/elicit_does_not_exist",
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "resolved"
    # Resolved responses must NOT leak pending-only fields.
    assert "message" not in data
    assert "phase" not in data
    assert "policy_name" not in data


async def test_get_nonexistent_session_returns_404(
    client: httpx.AsyncClient,
) -> None:
    """
    GET against a session that does not exist returns 404.
    """
    resp = await client.get(
        "/v1/sessions/conv_no_such_session/elicitations/elicit_irrelevant",
    )
    assert resp.status_code == 404, resp.text


async def test_get_after_resolution_returns_resolved(
    client: httpx.AsyncClient,
) -> None:
    """
    After resolving an elicitation, GET returns ``status: "resolved"``.

    Parks a real elicitation, resolves it, then asserts the GET
    endpoint no longer reports it as pending.
    """
    from omnigent.runtime import pending_elicitations

    agent = await create_test_agent(client, "test-get-after-resolve")
    session_id = await _create_session(client, agent["id"])
    hook_task, elicitation_id = await _park_permission_hook(client, session_id)

    try:
        # Resolve it.
        verdict = await client.post(
            f"/v1/sessions/{session_id}/elicitations/{elicitation_id}/resolve",
            json={"action": "accept"},
        )
        assert verdict.status_code == 202, verdict.text
        async with asyncio.timeout(5):
            _ = await hook_task

        # GET should now show resolved.
        resp = await client.get(
            f"/v1/sessions/{session_id}/elicitations/{elicitation_id}",
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "resolved"
    finally:
        if not hook_task.done():
            hook_task.cancel()
            await asyncio.gather(hook_task, return_exceptions=True)
        pending_elicitations.reset_for_tests()


# ── POST /sessions/{id}/elicitations/{eid}/resolve ───────


async def test_post_resolve_nonexistent_session_returns_404(
    client: httpx.AsyncClient,
) -> None:
    """
    POST resolve against a nonexistent session returns 404.
    """
    resp = await client.post(
        "/v1/sessions/conv_no_such_session/elicitations/elicit_irrelevant/resolve",
        json={"action": "accept"},
    )
    assert resp.status_code == 404, resp.text


async def test_post_resolve_already_resolved_is_idempotent(
    client: httpx.AsyncClient,
) -> None:
    """
    Resolving an already-resolved elicitation returns 202 (no-op).

    The ``_resolve_elicitation`` helper skips a done Future gracefully,
    so a double-submit from the UI must not error.
    """
    from omnigent.runtime import pending_elicitations

    agent = await create_test_agent(client, "test-double-resolve")
    session_id = await _create_session(client, agent["id"])
    hook_task, elicitation_id = await _park_permission_hook(client, session_id)

    try:
        # First resolve — actually wakes the hook.
        first = await client.post(
            f"/v1/sessions/{session_id}/elicitations/{elicitation_id}/resolve",
            json={"action": "accept"},
        )
        assert first.status_code == 202, first.text
        async with asyncio.timeout(5):
            _ = await hook_task

        # Second resolve — the Future is already done; should still 202.
        second = await client.post(
            f"/v1/sessions/{session_id}/elicitations/{elicitation_id}/resolve",
            json={"action": "decline"},
        )
        assert second.status_code == 202, second.text
        assert second.json() == {"queued": False}
    finally:
        if not hook_task.done():
            hook_task.cancel()
            await asyncio.gather(hook_task, return_exceptions=True)
        pending_elicitations.reset_for_tests()


async def test_post_resolve_nonexistent_elicitation_on_valid_session(
    client: httpx.AsyncClient,
) -> None:
    """
    POST resolve with a valid session but unknown elicitation id
    returns 202 (idempotent no-op) — the elicitation may have already
    been resolved by timeout or another tab.
    """
    agent = await create_test_agent(client, "test-resolve-unknown-eid")
    session_id = await _create_session(client, agent["id"])

    resp = await client.post(
        f"/v1/sessions/{session_id}/elicitations/elicit_does_not_exist/resolve",
        json={"action": "accept"},
    )
    assert resp.status_code == 202, resp.text
    assert resp.json() == {"queued": False}


async def test_post_resolve_invalid_action_returns_422(
    client: httpx.AsyncClient,
) -> None:
    """
    A body with an invalid ``action`` value is rejected with 422
    before any resolution logic runs.
    """
    agent = await create_test_agent(client, "test-resolve-bad-action")
    session_id = await _create_session(client, agent["id"])

    resp = await client.post(
        f"/v1/sessions/{session_id}/elicitations/elicit_whatever/resolve",
        json={"action": "yolo"},
    )
    assert resp.status_code == 422, resp.text


# CORAL(S6a, S6b): ids a verdict handler claims, published with no request behind them.

_GATE_ID = "test_gate_0123456789abcdef0123456789abcdef"


class _GateHandler:
    """A ``test_gate_`` verdict handler that records verdicts and returns a set decision."""

    def __init__(self) -> None:
        self.verdicts: list[ElicitationVerdict] = []
        self.decision = VerdictDecision(accepted=True)

    async def __call__(self, verdict: ElicitationVerdict) -> VerdictDecision:
        self.verdicts.append(verdict)
        return self.decision


@pytest.fixture
def gate_handler() -> Iterator[_GateHandler]:
    """Claim ``test_gate_`` ids for one test."""
    handler = _GateHandler()
    uninstall = register_elicitation_verdict_handler("test_gate_", handler)
    yield handler
    uninstall()


@pytest.fixture
def published() -> Iterator[list[dict[str, Any]]]:
    """Record every request and resolved event that reaches the pending index."""
    events: list[dict[str, Any]] = []
    remove = pending_elicitations.add_elicitation_observer(
        lambda _conversation_id, event: events.append(event)
    )
    yield events
    remove()


def _resolved_actions(events: list[dict[str, Any]], elicitation_id: str) -> list[str | None]:
    """Return the ``action`` of each resolved event published for *elicitation_id*."""
    return [
        event.get("action")
        for event in events
        if event["type"] == "response.elicitation_resolved"
        and event["elicitation_id"] == elicitation_id
    ]


async def _answer(
    client: httpx.AsyncClient,
    session_id: str,
    elicitation_id: str,
    *,
    route: str,
    verdict: dict[str, Any],
    user: str | None = None,
) -> httpx.Response:
    """Answer through the resolve URL (``route="resolve"``) or an ``approval`` event."""
    headers = {"X-Forwarded-Email": user} if user is not None else None
    if route == "resolve":
        return await client.post(
            f"/v1/sessions/{session_id}/elicitations/{elicitation_id}/resolve",
            json=verdict,
            headers=headers,
        )
    return await client.post(
        f"/v1/sessions/{session_id}/events",
        json={"type": "approval", "data": {"elicitation_id": elicitation_id, **verdict}},
        headers=headers,
    )


async def test_gate_published_prompt_is_pending_in_get_and_snapshot(
    client: httpx.AsyncClient, gate_handler: _GateHandler
) -> None:
    """A request-free prompt shows on the approve page and the snapshot; re-publish replaces it."""
    agent = await create_test_agent(client, "test-gate-publish")
    session_id = await _create_session(client, agent["id"])

    await publish_form_elicitation(session_id, {"message": "Approve v1?"}, elicitation_id=_GATE_ID)
    await publish_form_elicitation(session_id, {"message": "Approve v2?"}, elicitation_id=_GATE_ID)

    page = await client.get(f"/v1/sessions/{session_id}/elicitations/{_GATE_ID}")
    assert page.status_code == 200, page.text
    assert (page.json()["status"], page.json()["message"]) == ("pending", "Approve v2?")
    snapshot = await client.get(f"/v1/sessions/{session_id}")
    assert snapshot.status_code == 200, snapshot.text
    pending = snapshot.json()["pending_elicitations"]
    assert [(event["elicitation_id"], event["params"]["message"]) for event in pending] == [
        (_GATE_ID, "Approve v2?")
    ]


async def test_gate_answers_reach_the_handler_once_through_both_routes(
    client: httpx.AsyncClient, gate_handler: _GateHandler, published: list[dict[str, Any]]
) -> None:
    """The resolve URL and the approval event each reach the handler once, then fan out once."""
    agent = await create_test_agent(client, "test-gate-answer")
    session_id = await _create_session(client, agent["id"])
    event_id = "test_gate_answered_by_event"
    for elicitation_id in (_GATE_ID, event_id):
        await publish_form_elicitation(
            session_id, {"message": "Approve?"}, elicitation_id=elicitation_id
        )

    by_url = await _answer(
        client,
        session_id,
        _GATE_ID,
        route="resolve",
        verdict={"action": "accept", "content": {"decision": "approve"}},
    )
    by_event = await _answer(
        client, session_id, event_id, route="event", verdict={"action": "decline"}
    )
    # An unclaimed id keeps today's path and never reaches the handler.
    unclaimed = await _answer(
        client, session_id, "elicit_unclaimed", route="resolve", verdict={"action": "accept"}
    )

    assert [response.status_code for response in (by_url, by_event, unclaimed)] == [202] * 3
    assert by_url.json() == by_event.json() == {"queued": False}
    # Auth is off, so the route names no user.
    assert [
        (v.session_id, v.elicitation_id, v.result.action, v.result.content, v.resolved_by)
        for v in gate_handler.verdicts
    ] == [
        (session_id, _GATE_ID, "accept", {"decision": "approve"}, None),
        (session_id, event_id, "decline", None, None),
    ]
    assert _resolved_actions(published, _GATE_ID) == ["accept"]
    assert _resolved_actions(published, event_id) == ["decline"]
    assert pending_elicitations.count_for(session_id) == 0
    # Only the unclaimed answer leaves a harness tombstone.
    assert set(_elicitation_registry._harness_pre_resolved_elicitations) == {"elicit_unclaimed"}


@pytest.mark.parametrize("route", ["resolve", "event"])
async def test_gate_handler_receives_the_edit_shared_caller(
    auth_client: httpx.AsyncClient, db_uri: str, gate_handler: _GateHandler, route: str
) -> None:
    """Under header auth the handler is told which user answered; the body cannot say."""
    agent = await create_test_agent(auth_client, user="alice@example.com")
    session_id = await _create_session(auth_client, agent["id"], user="alice@example.com")
    permissions = SqlAlchemyPermissionStore(db_uri)
    permissions.ensure_user("bob@example.com")
    permissions.grant("bob@example.com", session_id, LEVEL_EDIT)
    await publish_form_elicitation(session_id, {"message": "Approve?"}, elicitation_id=_GATE_ID)

    response = await _answer(
        auth_client,
        session_id,
        _GATE_ID,
        route=route,
        verdict={"action": "accept", "resolved_by": "mallory@example.com"},
        user="bob@example.com",
    )

    assert response.status_code == 202, response.text
    assert [verdict.resolved_by for verdict in gate_handler.verdicts] == ["bob@example.com"]


@pytest.mark.parametrize("route", ["resolve", "event"])
@pytest.mark.parametrize("clear_pending", [False, True])
async def test_gate_duplicate_answer_has_no_second_fan_out(
    client: httpx.AsyncClient,
    gate_handler: _GateHandler,
    published: list[dict[str, Any]],
    route: str,
    clear_pending: bool,
) -> None:
    """A duplicate is a 202 receipt; only ``clear_pending`` drops a still-pending prompt."""
    agent = await create_test_agent(client, "test-gate-duplicate")
    session_id = await _create_session(client, agent["id"])
    await publish_form_elicitation(session_id, {"message": "Approve?"}, elicitation_id=_GATE_ID)
    gate_handler.decision = VerdictDecision(
        accepted=True, duplicate=True, clear_pending=clear_pending
    )

    response = await _answer(
        client, session_id, _GATE_ID, route=route, verdict={"action": "accept"}
    )

    assert response.status_code == 202, response.text
    assert response.json() == {"queued": False, "duplicate": True}
    # Withdrawing the stale prompt publishes a resolved event with no verdict.
    assert _resolved_actions(published, _GATE_ID) == ([None] if clear_pending else [])
    assert pending_elicitations.count_for(session_id) == (0 if clear_pending else 1)


@pytest.mark.parametrize(
    ("route", "forbidden", "clear_pending", "status", "reason"),
    [
        ("resolve", True, False, 403, "not_permitted"),
        # A caller refused for who they are never clears the prompt.
        ("event", True, True, 403, "not_permitted"),
        ("event", False, False, 409, "stale_visit"),
        ("resolve", False, True, 409, "no_longer_waiting"),
    ],
)
async def test_gate_refusal_answers_with_its_reason(
    client: httpx.AsyncClient,
    gate_handler: _GateHandler,
    published: list[dict[str, Any]],
    route: str,
    forbidden: bool,
    clear_pending: bool,
    status: int,
    reason: str,
) -> None:
    """A refusal is 403 or 409 with ``[reason] text``; only a 409's ``clear_pending`` drops it."""
    agent = await create_test_agent(client, "test-gate-refusal")
    session_id = await _create_session(client, agent["id"])
    await publish_form_elicitation(session_id, {"message": "Approve?"}, elicitation_id=_GATE_ID)
    gate_handler.decision = VerdictDecision(
        accepted=False,
        forbidden=forbidden,
        clear_pending=clear_pending,
        reason=reason,
        message="Refused for the test.",
    )

    response = await _answer(
        client, session_id, _GATE_ID, route=route, verdict={"action": "accept"}
    )

    assert response.status_code == status, response.text
    assert response.json()["error"]["message"] == f"[{reason}] Refused for the test."
    cleared = clear_pending and not forbidden
    assert _resolved_actions(published, _GATE_ID) == ([None] if cleared else [])
    assert pending_elicitations.count_for(session_id) == (0 if cleared else 1)


@pytest.mark.parametrize("route", ["resolve", "event"])
@pytest.mark.parametrize(("level", "status"), [(None, 404), (LEVEL_READ, 403)])
async def test_gate_caller_without_edit_access_never_reaches_the_handler(
    auth_client: httpx.AsyncClient,
    db_uri: str,
    gate_handler: _GateHandler,
    published: list[dict[str, Any]],
    route: str,
    level: int | None,
    status: int,
) -> None:
    """The session access check refuses before the handler; the prompt stays pending."""
    agent = await create_test_agent(auth_client, user="alice@example.com")
    session_id = await _create_session(auth_client, agent["id"], user="alice@example.com")
    permissions = SqlAlchemyPermissionStore(db_uri)
    permissions.ensure_user("carol@example.com")
    if level is not None:
        permissions.grant("carol@example.com", session_id, level)
    await publish_form_elicitation(session_id, {"message": "Approve?"}, elicitation_id=_GATE_ID)

    response = await _answer(
        auth_client,
        session_id,
        _GATE_ID,
        route=route,
        verdict={"action": "accept"},
        user="carol@example.com",
    )

    assert response.status_code == status, response.text
    assert gate_handler.verdicts == []
    assert _resolved_actions(published, _GATE_ID) == []
    assert pending_elicitations.count_for(session_id) == 1


@pytest.mark.parametrize("route", ["resolve", "event"])
@pytest.mark.parametrize("elicitation_id", ["test_gate_has.dot", "test_gate_" + "x" * 60])
async def test_gate_malformed_claimed_id_is_refused_before_the_handler(
    client: httpx.AsyncClient, gate_handler: _GateHandler, route: str, elicitation_id: str
) -> None:
    """A claimed prefix on an id outside ``[A-Za-z0-9_-]{1,64}`` is a 409 on both routes."""
    agent = await create_test_agent(client, "test-gate-malformed")
    session_id = await _create_session(client, agent["id"])
    gate_handler.decision = VerdictDecision(
        accepted=False, clear_pending=True, reason="no_longer_waiting"
    )

    response = await _answer(
        client, session_id, elicitation_id, route=route, verdict={"action": "accept"}
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["message"].startswith("[invalid_answer] ")
    assert gate_handler.verdicts == []


@pytest.mark.parametrize(
    "decision",
    [
        VerdictDecision(accepted=True),
        VerdictDecision(accepted=False, clear_pending=True, reason="no_longer_waiting"),
    ],
)
async def test_gate_answer_on_a_child_never_touches_its_parent(
    client: httpx.AsyncClient, db_uri: str, gate_handler: _GateHandler, decision: VerdictDecision
) -> None:
    """Only the handler clears a claimed prompt: a child's answer leaves the parent's copy."""
    agent = await create_test_agent(client, "test-gate-child")
    parent_id = await _create_session(client, agent["id"])
    child_id = _create_child_session(db_uri, parent_id=parent_id, agent_id=agent["id"])
    for session_id in (parent_id, child_id):
        await publish_form_elicitation(
            session_id, {"message": "Approve?"}, elicitation_id=_GATE_ID
        )
    seen_on: list[str] = []

    def _record_resolved(conversation_id: str, event: dict[str, Any]) -> None:
        if event["type"] == "response.elicitation_resolved":
            seen_on.append(conversation_id)

    remove = pending_elicitations.add_elicitation_observer(_record_resolved)
    gate_handler.decision = decision
    try:
        response = await _answer(
            client, child_id, _GATE_ID, route="resolve", verdict={"action": "accept"}
        )
    finally:
        remove()

    assert response.status_code == (202 if decision.accepted else 409), response.text
    assert seen_on == [child_id]
    assert pending_elicitations.count_for(child_id) == 0
    assert pending_elicitations.count_for(parent_id) == 1
