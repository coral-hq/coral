"""The owner's workflow Inbox: open alerts, normal priority first, and marking one read.

Unmounted: the Coral server plugin mounts it under ``/v1/coral`` with its own caller
and workspace dependencies. The alert store is read per request from
``app.state.coral_alert_store``; without one both routes answer 404, which clients
take as "no workflow feed".
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from coral.alerts.types import AlertAction, AlertKindName, AlertPayload
from coral.api.errors import CoralApiError, CoralRoute, error_responses
from coral.db.enum_codecs import decode_alert_kind, decode_alert_priority
from coral.limits import WarnOnce
from coral.omni.protocols import Viewer
from coral.queue.run_effects import describe_exception
from coral.stores.alerts import MAX_INBOX_LIMIT, InboxCursor, SqlAlchemyAlertStore
from coral.stores.protocols import AlertRecord

_logger = logging.getLogger(__name__)

# ``<priority>:<created_at>:<alert id>`` of the last alert a page read.
_CURSOR = re.compile(r"([12]):([0-9]{1,19}):([0-9a-f]{32})")
_ALERT_ID = re.compile(r"[0-9a-f]{32}")
MAX_CURSOR_CHARS = 64
_MAX_CREATED_AT = 2**63 - 1

AlertPriorityName = Literal["normal", "low"]


class WorkflowAlertOut(BaseModel):
    """One open alert as the Inbox lists it: its row's fields merged with its payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_id: str
    run_id: str
    run_title: str
    kind: AlertKindName
    priority: AlertPriorityName
    created_at: int
    title: str
    message: str
    step_label: str | None
    node_id: str | None
    actions: tuple[AlertAction, ...]
    deep_link: str
    approve_link: str | None
    elicitation_id: str | None
    session_id: str | None
    outcomes: tuple[str, ...]
    pause_reason: str | None


class WorkflowInboxPage(BaseModel):
    """
    One feed page. A page can be empty and still carry ``next_cursor``: keep paging
    until it is null.
    """

    data: list[WorkflowAlertOut]
    next_cursor: str | None


class AckRequest(BaseModel):
    """The body of a "mark as read": the empty JSON object."""

    model_config = ConfigDict(extra="forbid")


def alert_item(alert: AlertRecord) -> WorkflowAlertOut:
    """
    ``alert`` as the feed lists it.

    :raises ValueError: its payload or one of its codes cannot be read.
    """
    payload = AlertPayload.model_validate_json(alert.payload)
    return WorkflowAlertOut.model_validate(
        {
            "alert_id": alert.id,
            "run_id": alert.run_id,
            "kind": decode_alert_kind(alert.kind),
            "priority": decode_alert_priority(alert.priority),
            "created_at": alert.created_at,
            **payload.model_dump(),
        }
    )


def parse_inbox_cursor(after: str) -> InboxCursor:
    """
    The cursor a page's ``next_cursor`` named.

    :raises ValueError: longer than 64 characters, or not
        ``<1|2>:<0..2^63-1>:<32 lowercase hex>``.
    """
    match = _CURSOR.fullmatch(after) if len(after) <= MAX_CURSOR_CHARS else None
    if match is None or int(match[2]) > _MAX_CREATED_AT:
        raise ValueError("invalid workflow inbox cursor")
    return int(match[1]), int(match[2]), match[3]


def format_inbox_cursor(cursor: InboxCursor | None) -> str | None:
    return None if cursor is None else f"{cursor[0]}:{cursor[1]}:{cursor[2]}"


class _UnreadableAlerts:
    """Warns about the first alert the feed cannot read; the later ones go to debug."""

    def __init__(self) -> None:
        self._warned = WarnOnce()

    def skipped(self, alert: AlertRecord, exc: Exception) -> None:
        first = self._warned.first()
        # Only ids and error locations: payloads hold run titles and prompts.
        _logger.log(
            logging.WARNING if first else logging.DEBUG,
            "workflow inbox skipped alert %s of run %s: %s%s",
            alert.id,
            alert.run_id,
            describe_exception(exc),
            "; later unreadable alerts are logged at debug" if first else "",
        )


def _alert_store(request: Request) -> SqlAlchemyAlertStore:
    store = getattr(request.app.state, "coral_alert_store", None)
    if store is None:
        raise CoralApiError("not_found", "Coral inbox is not available", 404)
    return store


def create_inbox_router(
    *,
    viewer_dependency: Callable[..., Viewer] | Callable[..., Awaitable[Viewer]],
    workspace_id_dependency: Callable[..., int],
    clock: Callable[[], int] = lambda: int(time.time()),
) -> APIRouter:
    """
    The Inbox routes, mounted by the caller under ``/v1/coral``.

    :param viewer_dependency: Resolves the caller, refusing with 401 or 403; it runs
        before the store is read, so an unauthenticated caller learns nothing.
    :param workspace_id_dependency: The request's workspace.
    :param clock: Epoch seconds an alert is marked read at.
    """
    # The route class refuses a body that is not JSON, as a cross-site form could send.
    router = APIRouter(route_class=CoralRoute)
    unreadable = _UnreadableAlerts()
    # Built once: each route's caller and workspace come from these.
    caller = Depends(viewer_dependency)
    workspace = Depends(workspace_id_dependency)

    @router.get(
        "/inbox",
        operation_id="coral_list_inbox",
        response_model=WorkflowInboxPage,
        responses=error_responses(401, 403, 404, 422),
    )
    def list_inbox(
        request: Request,
        response: Response,
        limit: int = Query(default=MAX_INBOX_LIMIT, ge=1, le=MAX_INBOX_LIMIT),
        # Its length is checked with its format, so both give the cursor's own 422.
        after: str | None = Query(default=None),
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> WorkflowInboxPage:
        """The caller's open alerts: normal priority first, newest first within each."""
        # The feed holds run titles and gate prompts: never kept by a cache.
        response.headers["Cache-Control"] = "private, no-store"
        try:
            cursor = None if after is None else parse_inbox_cursor(after)
        except ValueError as exc:
            raise CoralApiError("validation_failed", "Invalid workflow inbox cursor", 422) from exc
        alerts, next_cursor = _alert_store(request).list_inbox(
            workspace_id=workspace_id, viewer=viewer, after=cursor, limit=limit
        )
        items: list[WorkflowAlertOut] = []
        for alert in alerts:
            try:
                items.append(alert_item(alert))
            except ValueError as exc:
                unreadable.skipped(alert, exc)
        return WorkflowInboxPage(data=items, next_cursor=format_inbox_cursor(next_cursor))

    @router.post(
        "/inbox/{alert_id}/ack",
        operation_id="coral_ack_alert",
        status_code=204,
        response_class=Response,
        responses=error_responses(401, 403, 404, 409, 422),
    )
    def ack_alert(
        request: Request,
        alert_id: str,
        _body: AckRequest,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> Response:
        """Mark one of the caller's alerts read; marking it again changes nothing."""
        store = _alert_store(request)
        outcome = (
            store.ack(workspace_id=workspace_id, viewer=viewer, alert_id=alert_id, now=clock())
            if _ALERT_ID.fullmatch(alert_id)
            else "not_found"
        )
        if outcome == "not_found":
            raise CoralApiError("not_found", "alert not found", 404)
        if outcome == "not_ackable":
            raise CoralApiError("illegal_transition", "Answer the gate to clear this alert.", 409)
        return Response(status_code=204)

    return router


__all__ = [
    "MAX_CURSOR_CHARS",
    "AckRequest",
    "AlertPriorityName",
    "WorkflowAlertOut",
    "WorkflowInboxPage",
    "alert_item",
    "create_inbox_router",
    "format_inbox_cursor",
    "parse_inbox_cursor",
]
