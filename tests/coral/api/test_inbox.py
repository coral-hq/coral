"""Workflow Inbox routes on a bare app: the owner's feed, its paging, ack, and who may call."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import HTTPConnection

from coral.alerts.rules import alert_id
from coral.api.inbox import create_inbox_router
from coral.db.enum_codecs import AlertKind, AlertPriority, AlertStatus
from coral.db.migrate import ensure_coral_schema
from coral.model.ids import anchor_session_id
from coral.omni.server.access import request_viewer
from coral.stores.alerts import SqlAlchemyAlertStore
from coral.stores.protocols import AlertDraft, CoralRun
from coral.stores.runs import SqlAlchemyCoralRunStore
from omnigent.db.account_authority import bind_account_authority, clear_account_authority
from omnigent.server.auth import AuthProvider, UnifiedAuthProvider
from tests.coral.bridge._gates import APPROVE_TOKEN, GATE_ONLY, GateIds, answer, gate_rows
from tests.coral.bridge._world import World, start
from tests.stores.coral._alerts import (
    ALICE,
    BOB,
    NOW,
    WORKSPACE,
    alert_draft,
    commit_alert_changes,
    start_owned_run,
)

HEADER = "X-Forwarded-Email"
HEADER_AUTH = UnifiedAuthProvider(source="header", local_single_user=False, header_name=HEADER)
INBOX = "/v1/coral/inbox"
ACKED_AT = NOW + 100
UNKNOWN_ID = "f" * 32


class _AccountHeaders(AuthProvider):
    """Accounts sign-in as headers: ``X-User`` signs in, proving ``X-Generation`` for
    ``X-Account`` (the user itself unless given), as an accounts session binds it."""

    def get_user_id(self, request: HTTPConnection) -> str | None:
        clear_account_authority()
        user = request.headers.get("X-User")
        generation = request.headers.get("X-Generation")
        if user is not None and generation is not None:
            bind_account_authority(request.headers.get("X-Account", user), generation)
        return user


ACCOUNTS = _AccountHeaders()


@pytest.fixture
def coral_uri(db_uri: str) -> str:
    ensure_coral_schema(db_uri)
    return db_uri


def _app(
    coral_uri: str | None,
    auth_provider: AuthProvider | None = HEADER_AUTH,
    **app_options: Any,
) -> FastAPI:
    """The inbox router alone, authenticating through ``auth_provider``; no store without a URI."""
    app = FastAPI(**app_options)
    app.include_router(
        create_inbox_router(
            viewer_dependency=request_viewer(auth_provider),
            workspace_id_dependency=lambda: WORKSPACE,
            clock=lambda: ACKED_AT,
        ),
        prefix="/v1/coral",
    )
    if coral_uri is not None:
        app.state.coral_alert_store = SqlAlchemyAlertStore(coral_uri)
    return app


def _as(user: str) -> dict[str, str]:
    return {HEADER: user}


def _ack(
    client: TestClient,
    alert: str,
    user: str = ALICE,
    *,
    headers: dict[str, str] | None = None,
    **body: Any,
) -> Any:
    """Mark ``alert`` read as ``user``, sending ``body`` (``json=``, ``content=``, ``data=``)."""
    return client.post(f"{INBOX}/{alert}/ack", headers={**_as(user), **(headers or {})}, **body)


def _ids(client: TestClient, headers: dict[str, str], **params: Any) -> list[str]:
    response = client.get(INBOX, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return [item["alert_id"] for item in response.json()["data"]]


def _alerts_of(
    coral_uri: str, *drafts: Callable[[CoralRun], AlertDraft], user: str | None = ALICE, **run: Any
) -> tuple[CoralRun, list[AlertDraft]]:
    """A run of ``user`` committing one alert per builder, in one transition."""
    runs = SqlAlchemyCoralRunStore(coral_uri)
    started = start_owned_run(runs, run.pop("key", "inbox"), user_id=user, **run)
    raised = [build(started) for build in drafts]
    commit_alert_changes(runs, started, raises=raised)
    return started, raised


def _pause(key: str, created_at: int = NOW) -> Callable[[CoralRun], AlertDraft]:
    return lambda run: alert_draft(run, AlertKind.PAUSE, key, created_at=created_at)


def _done(key: str, created_at: int = NOW) -> Callable[[CoralRun], AlertDraft]:
    return lambda run: alert_draft(
        run, AlertKind.RUN_COMPLETED, key, priority=AlertPriority.LOW, created_at=created_at
    )


def _ack_run(client: TestClient, run_id: str, user: str = ALICE) -> Any:
    """Mark ``run_id``'s low-priority alerts read as ``user``."""
    return client.post(f"{INBOX}/ack", headers=_as(user), json={"run_id": run_id})


def _status(coral_uri: str, run: CoralRun) -> dict[str, tuple[int, int | None, str | None]]:
    records = SqlAlchemyAlertStore(coral_uri).list_for_run(workspace_id=WORKSPACE, run_id=run.id)
    return {record.id: (record.status, record.acked_at, record.acked_by) for record in records}


# ── The feed ────────────────────────────────────────────────────────────────


def test_an_open_gate_is_listed_with_every_field_until_its_answer_clears_it(
    coral_uri: str,
) -> None:
    gate_ids = GateIds()
    world = World.sql(coral_uri, gate_ids=gate_ids)
    run = start(world, GATE_ONLY)
    (row,) = gate_rows(world, run.id)
    anchor = anchor_session_id(WORKSPACE, run.id)
    (prompt_id,) = gate_ids.issued
    client = TestClient(_app(coral_uri))

    page = client.get(INBOX, headers=_as(ALICE))

    assert page.status_code == 200
    assert page.headers["cache-control"] == "private, no-store"
    assert page.json() == {
        "data": [
            {
                "alert_id": alert_id(WORKSPACE, run.id, "gate", row.id),
                "run_id": run.id,
                "run_title": "Ship the bridge",
                "kind": "gate",
                "priority": "normal",
                "created_at": world.clock.epoch,
                "title": "Approval needed",
                "message": "Ship it?",
                "step_label": "Approve",
                "node_id": "approve",
                "actions": ["answer", "open_run"],
                "deep_link": f"/workflows/runs/{run.id}?node=approve&panel=gate",
                "approve_link": f"/approve/{anchor}/{prompt_id}",
                "elicitation_id": prompt_id,
                "session_id": anchor,
                "outcomes": ["approve", "reject"],
                "pause_reason": None,
            }
        ],
        "next_cursor": None,
    }

    assert answer(world, run.id, APPROVE_TOKEN, "approve").outcome == "accepted"
    (done,) = client.get(INBOX, headers=_as(ALICE)).json()["data"]
    assert (done["kind"], done["priority"], done["actions"]) == (
        "run_completed",
        "low",
        ["open_run", "mark_read"],
    )


def test_normal_alerts_page_newest_first_before_low_ones(coral_uri: str) -> None:
    # The low alerts are the newest, yet they are listed after every normal one.
    _run, (old, middle, new, low_old, low_new) = _alerts_of(
        coral_uri,
        _pause("1", NOW + 1),
        _pause("2", NOW + 2),
        _pause("3", NOW + 3),
        _done("done-1", NOW + 10),
        _done("done-2", NOW + 11),
    )
    client = TestClient(_app(coral_uri))

    pages: list[tuple[list[str], str | None]] = []
    after: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2, **({"after": after} if after else {})}
        body = client.get(INBOX, headers=_as(ALICE), params=params).json()
        pages.append(([item["alert_id"] for item in body["data"]], body["next_cursor"]))
        after = body["next_cursor"]
        if after is None:
            break

    assert pages == [
        ([new.id, middle.id], f"1:{NOW + 2}:{middle.id}"),
        ([old.id, low_new.id], f"2:{NOW + 11}:{low_new.id}"),
        ([low_old.id], None),
    ]
    assert _ids(client, _as(ALICE)) == [new.id, middle.id, old.id, low_new.id, low_old.id]


def test_a_page_of_rows_the_caller_may_not_see_is_empty_and_paging_goes_on(
    coral_uri: str,
) -> None:
    # The newest alert was recorded under an account generation this request does not prove.
    _alerts_of(coral_uri, _pause("1", NOW + 5), key="proved", generation="g1")
    _run, (visible,) = _alerts_of(coral_uri, _pause("1", NOW), key="plain")
    client = TestClient(_app(coral_uri))

    first = client.get(INBOX, headers=_as(ALICE), params={"limit": 1}).json()
    assert first["data"] == []
    assert first["next_cursor"] is not None
    second = client.get(
        INBOX, headers=_as(ALICE), params={"limit": 1, "after": first["next_cursor"]}
    ).json()
    assert ([item["alert_id"] for item in second["data"]], second["next_cursor"]) == (
        [visible.id],
        None,
    )


def test_an_alert_whose_payload_cannot_be_read_is_skipped_and_logged_once(
    coral_uri: str, caplog: pytest.LogCaptureFixture
) -> None:
    def unreadable(run: CoralRun) -> AlertDraft:
        draft = alert_draft(run, AlertKind.PAUSE, "broken", created_at=NOW + 1)
        return dataclasses.replace(draft, payload='{"title": "Run paused"}')

    _run, (broken, readable) = _alerts_of(coral_uri, unreadable, _pause("ok"))
    client = TestClient(_app(coral_uri))

    with caplog.at_level(logging.DEBUG, logger="coral.api.inbox"):
        assert _ids(client, _as(ALICE)) == [readable.id]
        assert _ids(client, _as(ALICE)) == [readable.id]

    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert broken.id in warnings[0].getMessage()
    # Payload text never reaches the log.
    assert "Run paused" not in caplog.text


@pytest.mark.parametrize(
    "after",
    [
        pytest.param("nonsense", id="not-a-cursor"),
        pytest.param(f"3:1:{'a' * 32}", id="unknown-priority"),
        pytest.param(f"1:-1:{'a' * 32}", id="negative-time"),
        pytest.param(f"1:{2**63}:{'a' * 32}", id="time-past-int64"),
        pytest.param(f"1:1:{'A' * 32}", id="upper-case-id"),
        pytest.param(f"1:1:{'a' * 31}", id="short-id"),
        pytest.param(f"1:1:{'a' * 32}\n", id="trailing-newline"),
        pytest.param(f"1:{'1' * 30}:{'a' * 32}", id="longer-than-64"),
    ],
)
def test_a_bad_cursor_is_refused_as_invalid(coral_uri: str, after: str) -> None:
    _alerts_of(coral_uri, _pause("1"))
    client = TestClient(_app(coral_uri))

    response = client.get(INBOX, headers=_as(ALICE), params={"after": after})

    assert (response.status_code, response.json()) == (
        422,
        {
            "error": {
                "code": "validation_failed",
                "message": "Invalid workflow inbox cursor",
                "details": None,
            }
        },
    )


@pytest.mark.parametrize("limit", [0, 101])
def test_a_limit_outside_1_to_100_is_refused(coral_uri: str, limit: int) -> None:
    client = TestClient(_app(coral_uri))

    response = client.get(INBOX, headers=_as(ALICE), params={"limit": limit})

    assert response.status_code == 422


def test_a_cursor_at_the_largest_time_is_accepted(coral_uri: str) -> None:
    client = TestClient(_app(coral_uri))

    response = client.get(INBOX, headers=_as(ALICE), params={"after": f"2:{2**63 - 1}:{'a' * 32}"})

    assert response.json() == {"data": [], "next_cursor": None}


# ── Marking read ────────────────────────────────────────────────────────────


def test_an_alert_marked_read_on_one_client_leaves_the_others_feed(coral_uri: str) -> None:
    run, (pause,) = _alerts_of(coral_uri, _pause("1"))
    app = _app(coral_uri)
    phone, laptop = TestClient(app), TestClient(app)
    assert _ids(laptop, _as(ALICE)) == [pause.id]

    acked = _ack(phone, pause.id, json={})

    assert (acked.status_code, acked.content) == (204, b"")
    assert _ids(laptop, _as(ALICE)) == []
    assert _status(coral_uri, run) == {pause.id: (int(AlertStatus.ACKED), ACKED_AT, ALICE)}
    # Marking it read again changes nothing.
    assert _ack(laptop, pause.id, json={}).status_code == 204
    assert _status(coral_uri, run) == {pause.id: (int(AlertStatus.ACKED), ACKED_AT, ALICE)}


def test_an_open_gate_alert_is_answered_not_marked_read(coral_uri: str) -> None:
    run, (gate,) = _alerts_of(coral_uri, lambda run: alert_draft(run, AlertKind.GATE, "visit"))
    client = TestClient(_app(coral_uri))

    refused = _ack(client, gate.id, json={})

    assert (refused.status_code, refused.json()) == (
        409,
        {
            "error": {
                "code": "illegal_transition",
                "message": "Answer the gate to clear this alert.",
                "details": None,
            }
        },
    )
    assert _ids(client, _as(ALICE)) == [gate.id]
    assert _status(coral_uri, run)[gate.id][0] == int(AlertStatus.OPEN)


@pytest.mark.parametrize(
    "request_body",
    [
        pytest.param({}, id="no-body"),
        pytest.param({"content": b"{}"}, id="json-without-content-type"),
        pytest.param({"content": b"{}", "headers": {"content-type": "text/plain"}}, id="text"),
        pytest.param({"data": {"confirm": "1"}}, id="form"),
        pytest.param(
            {"content": b"{}", "headers": {"content-type": "multipart/form-data; boundary=x"}},
            id="multipart",
        ),
        pytest.param({"json": {"read": True}}, id="extra-field"),
        pytest.param({"json": []}, id="not-an-object"),
    ],
)
def test_marking_read_needs_an_empty_json_object(
    coral_uri: str, request_body: dict[str, Any]
) -> None:
    # A cross-site form can post text, form or multipart bodies without a preflight.
    run, (pause,) = _alerts_of(coral_uri, _pause("1"))
    client = TestClient(_app(coral_uri))

    response = _ack(client, pause.id, **request_body)

    assert response.status_code == 422
    assert _status(coral_uri, run)[pause.id][0] == int(AlertStatus.OPEN)


def test_a_body_with_no_media_type_is_refused_where_fastapi_would_read_it_as_json(
    coral_uri: str,
) -> None:
    # Older FastAPI releases, and apps that opt out of strict content types, parse it.
    run, (pause, done) = _alerts_of(coral_uri, _pause("1"), _done("run_completed"))
    client = TestClient(_app(coral_uri, strict_content_type=False))

    response = _ack(client, pause.id, content=b"{}")
    run_response = client.post(
        f"{INBOX}/ack", headers=_as(ALICE), content=f'{{"run_id": "{run.id}"}}'.encode()
    )

    for refused in (response, run_response):
        assert (refused.status_code, refused.json()) == (
            422,
            {
                "error": {
                    "code": "validation_failed",
                    "message": "The request body must be JSON.",
                    "details": None,
                }
            },
        )
    unchanged = (int(AlertStatus.OPEN), None, None)
    assert _status(coral_uri, run) == {pause.id: unchanged, done.id: unchanged}


def test_a_json_media_type_with_parameters_is_accepted(coral_uri: str) -> None:
    _run, (pause,) = _alerts_of(coral_uri, _pause("1"))
    client = TestClient(_app(coral_uri))

    response = _ack(
        client,
        pause.id,
        content=b"{}",
        headers={"content-type": "application/json; charset=utf-8"},
    )

    assert response.status_code == 204


# ── Marking a run's alerts read ─────────────────────────────────────────────


def test_opening_a_run_marks_its_run_end_alert_read_and_leaves_its_pause(coral_uri: str) -> None:
    run, (pause, done) = _alerts_of(coral_uri, _pause("1"), _done("run_completed"))
    client = TestClient(_app(coral_uri))

    acked = _ack_run(client, run.id)

    assert (acked.status_code, acked.json()) == (200, {"acked": 1})
    assert _status(coral_uri, run) == {
        pause.id: (int(AlertStatus.OPEN), None, None),
        done.id: (int(AlertStatus.ACKED), ACKED_AT, ALICE),
    }
    assert _ids(client, _as(ALICE)) == [pause.id]
    # Again, or as another user, or for an unknown run: nothing to mark, never a refusal.
    for user, run_id in ((ALICE, run.id), (BOB, run.id), (ALICE, UNKNOWN_ID)):
        again = _ack_run(client, run_id, user)
        assert (again.status_code, again.json()) == (200, {"acked": 0})


@pytest.mark.parametrize(
    "request_body",
    [
        pytest.param({"json": {}}, id="no-run-id"),
        pytest.param({"json": {"run_id": None}}, id="null-run-id"),
        pytest.param({"json": {"run_id": 7}}, id="number-run-id"),
        pytest.param({"json": {"run_id": "A" * 32}}, id="upper-case-run-id"),
        pytest.param({"json": {"run_id": "a" * 31}}, id="short-run-id"),
        pytest.param({"json": {"run_id": "a" * 32 + "\n"}}, id="trailing-newline"),
        pytest.param({"json": {"run_id": "a" * 32, "alert_ids": []}}, id="extra-field"),
        pytest.param({"json": []}, id="not-an-object"),
        pytest.param({"data": {"run_id": "a" * 32}}, id="form"),
    ],
)
def test_marking_a_runs_alerts_read_needs_exactly_its_run_id(
    coral_uri: str, request_body: dict[str, Any]
) -> None:
    run, (done,) = _alerts_of(coral_uri, _done("run_completed"))
    client = TestClient(_app(coral_uri))

    response = client.post(f"{INBOX}/ack", headers=_as(ALICE), **request_body)

    assert (response.status_code, response.json()["error"]["code"]) == (422, "validation_failed")
    assert _status(coral_uri, run)[done.id][0] == int(AlertStatus.OPEN)


# ── Who may call ────────────────────────────────────────────────────────────


def test_another_users_alerts_are_neither_listed_nor_found(coral_uri: str) -> None:
    run, (pause, gate) = _alerts_of(
        coral_uri,
        _pause("1"),
        lambda run: alert_draft(run, AlertKind.GATE, "visit", created_at=NOW - 1),
    )
    client = TestClient(_app(coral_uri))

    assert _ids(client, _as(BOB)) == []
    # The same answer for another user's alert, an unknown id and a malformed one; a gate
    # alert of another user is not found either, never "answer the gate".
    for target in (pause.id, gate.id, UNKNOWN_ID, "not-an-alert", pause.id.upper()):
        refused = _ack(client, target, user=BOB, json={})
        assert (refused.status_code, refused.json()) == (
            404,
            {"error": {"code": "not_found", "message": "alert not found", "details": None}},
        )
    assert _ids(client, _as(ALICE)) == [pause.id, gate.id]
    assert {status for status, _at, _by in _status(coral_uri, run).values()} == {
        int(AlertStatus.OPEN)
    }


def test_a_request_with_no_identity_is_unauthenticated(coral_uri: str) -> None:
    run, (pause,) = _alerts_of(coral_uri, _pause("1"))
    client = TestClient(_app(coral_uri))

    listed = client.get(INBOX)
    acked = client.post(f"{INBOX}/{pause.id}/ack", json={})
    run_acked = client.post(f"{INBOX}/ack", json={"run_id": run.id})

    for response in (listed, acked, run_acked):
        assert (response.status_code, response.json()) == (
            401,
            {
                "error": {
                    "code": "unauthenticated",
                    "message": "Authentication required",
                    "details": None,
                }
            },
        )


def test_with_auth_off_the_local_user_sees_and_marks_its_own_runs_alerts(
    coral_uri: str,
) -> None:
    _run, (own,) = _alerts_of(coral_uri, _pause("1"), user=None, key="local")
    _alerts_of(coral_uri, _pause("1"), key="alice")
    client = TestClient(_app(coral_uri, auth_provider=None))

    assert _ids(client, {}) == [own.id]
    assert client.post(f"{INBOX}/{own.id}/ack", json={}).status_code == 204
    assert _ids(client, {}) == []


def test_a_recorded_generation_is_shown_only_to_a_request_that_proves_it(
    coral_uri: str,
) -> None:
    _run, (pause,) = _alerts_of(coral_uri, _pause("1"), generation="g1")
    accounts = TestClient(_app(coral_uri, auth_provider=ACCOUNTS))
    headers_only = TestClient(_app(coral_uri))
    recreated = {"X-User": ALICE, "X-Generation": "g2"}

    # Another generation of the same user id, and a request that proves none.
    assert _ids(accounts, recreated) == []
    assert _ack(accounts, pause.id, headers=recreated, json={}).status_code == 404
    assert _ids(headers_only, _as(ALICE)) == []
    assert _ack(headers_only, pause.id, json={}).status_code == 404

    original = {"X-User": ALICE, "X-Generation": "g1"}
    assert _ids(accounts, original) == [pause.id]
    assert _ack(accounts, pause.id, headers=original, json={}).status_code == 204


def test_a_request_whose_account_names_another_user_is_refused(coral_uri: str) -> None:
    run, (pause,) = _alerts_of(coral_uri, _pause("1"))
    client = TestClient(_app(coral_uri, auth_provider=ACCOUNTS))
    crossed = {"X-User": ALICE, "X-Account": BOB, "X-Generation": "g1"}

    listed = client.get(INBOX, headers=crossed)
    acked = client.post(f"{INBOX}/{pause.id}/ack", headers=crossed, json={})
    run_acked = client.post(f"{INBOX}/ack", headers=crossed, json={"run_id": run.id})

    for response in (listed, acked, run_acked):
        assert (response.status_code, response.json()) == (
            403,
            {"error": {"code": "not_permitted", "message": "Not permitted", "details": None}},
        )


def test_without_the_alert_store_every_route_is_not_found() -> None:
    client = TestClient(_app(None))

    for response in (
        client.get(INBOX, headers=_as(ALICE)),
        _ack(client, UNKNOWN_ID, json={}),
        _ack_run(client, UNKNOWN_ID),
    ):
        assert (response.status_code, response.json()) == (
            404,
            {
                "error": {
                    "code": "not_found",
                    "message": "Coral inbox is not available",
                    "details": None,
                }
            },
        )
