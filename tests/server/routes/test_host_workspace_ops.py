# CORAL(S40): the server side of the host workspace-op channel.
"""Tests for ``omnigent.server.routes._host_workspace_ops``.

The request helper sends ``host.workspace_op`` only to a host advertising
``workspace_ops:1``, inside a matching host-owner scope, and only a frame the
host would accept. It fails at once when the tunnel drops, times out after the
op's own timeout plus a grace, and resolves with the six result fields the host
tunnel relays, bounding the host's text.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import re
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest
from asgiref.testing import ApplicationCommunicator
from fastapi import FastAPI

import omnigent.server.routes._host_workspace_ops as host_workspace_ops
from omnigent.db.account_authority import account_authority_scope
from omnigent.host.frames import decode_host_frame, encode_host_frame
from omnigent.host.workspace_ops import (
    CAP_WORKSPACE_OPS,
    HostWorkspaceOpFrame,
    HostWorkspaceOpResultFrame,
)
from omnigent.server.host_registry import HostConnection, HostRegistry, host_owner_scope
from omnigent.server.routes._host_workspace_ops import (
    WORKSPACE_OP_REPLY_GRACE_S,
    HostWorkspaceOpNotPermittedError,
    HostWorkspaceOpsUnsupportedError,
    HostWorkspaceOpUnavailableError,
    WorkspaceOpReply,
    request_workspace_op_on_host,
)
from omnigent.server.routes.host_tunnel import create_host_tunnel_router
from omnigent.stores.host_store import HostStore
from tests._helpers.polling import poll_until_async
from tests.server.helpers import websocket_scope
from tests.server.routes.test_host_worktree import _FakeWebSocket, _hello_frame

pytestmark = pytest.mark.asyncio

_HOST_ID = "host_workspace_ops"
_TUNNEL_HOST_ID = "5d0e3c9a1b7f4e2c8a6d0b3f9e1c7a54"
_ROOT = "/Users/a/repo-worktrees/coral-r-0a1b2c3d4e5f-base"
_PARAMS = {"repo_root": "/Users/a/repo", "branch": "coral/r-0a1b2c3d4e5f/base"}


def _register(registry: HostRegistry, capabilities: list[str] | None) -> HostConnection:
    return registry.register(
        host_id=_HOST_ID,
        ws=_FakeWebSocket(),  # type: ignore[arg-type] — duck-typed
        hello=_hello_frame(capabilities),
        owner=None,
    )


async def _request(
    conn: HostConnection, registry: HostRegistry, *, timeout_s: float, **fields: Any
) -> WorkspaceOpReply:
    """Send ``commit`` the way an authorized caller does: inside the owner's scope."""
    arguments: dict[str, Any] = {"op": "commit", "root": _ROOT, "op_key": "k" * 32, **fields}
    with host_owner_scope(conn.owner, conn.account_generation):
        return await request_workspace_op_on_host(
            host_registry=registry,
            host_conn=conn,
            params=_PARAMS,
            timeout_s=timeout_s,
            **arguments,
        )


async def test_host_without_the_token_is_refused_before_any_frame() -> None:
    registry = HostRegistry()
    conn = _register(registry, None)

    with pytest.raises(HostWorkspaceOpsUnsupportedError):
        await _request(conn, registry, timeout_s=600.0)

    assert conn.outbound_queue.empty()
    assert conn.pending_workspace_ops == {}


@pytest.mark.parametrize(
    ("timeout_s", "fields"),
    [
        pytest.param(0.0, {}, id="timeout-zero"),
        pytest.param(-1.0, {}, id="timeout-negative"),
        pytest.param(900.5, {}, id="timeout-over-cap"),
        pytest.param(math.nan, {}, id="timeout-nan"),
        pytest.param(math.inf, {}, id="timeout-inf"),
        pytest.param(True, {}, id="timeout-bool"),
        pytest.param(10**400, {}, id="timeout-overflows-float"),
        pytest.param(600.0, {"op": None}, id="op-not-str"),
        pytest.param(600.0, {"root": None}, id="root-not-str"),
        pytest.param(600.0, {"root": "repo-worktrees/run"}, id="root-relative"),
        pytest.param(600.0, {"root": "/repo/../etc"}, id="root-dot-dot"),
        pytest.param(600.0, {"root": "//server/share"}, id="root-double-slash"),
        pytest.param(600.0, {"root": "/repo/r\x00un"}, id="root-nul"),
        pytest.param(600.0, {"op_key": 5}, id="op-key-not-str"),
        pytest.param(600.0, {"op_key": "Key 1"}, id="op-key-malformed"),
        pytest.param(600.0, {"op_key": "k" * 129}, id="op-key-too-long"),
    ],
)
async def test_frame_the_host_would_refuse_is_refused_before_any_frame(
    timeout_s: float, fields: dict[str, Any]
) -> None:
    """The host drops or refuses these frames, so the caller learns at once and nothing is sent."""
    registry = HostRegistry()
    conn = _register(registry, [CAP_WORKSPACE_OPS])

    with pytest.raises(ValueError):
        await _request(conn, registry, timeout_s=timeout_s, **fields)

    assert conn.outbound_queue.empty()
    assert conn.pending_workspace_ops == {}


@pytest.mark.parametrize(
    ("scope", "sent"),
    [
        pytest.param(None, False, id="no-scope"),
        pytest.param(("bob@example.com", "gen-1"), False, id="another-owner"),
        pytest.param(("alice@example.com", "gen-0"), False, id="older-registration"),
        pytest.param((None, None), False, id="ownerless-scope"),
        pytest.param(("alice@example.com", "gen-1"), True, id="owner-scope"),
    ],
)
async def test_send_requires_a_host_owner_scope_naming_the_connection(
    scope: tuple[str | None, str | None] | None, sent: bool
) -> None:
    registry = HostRegistry()
    with account_authority_scope("alice@example.com", "gen-1"):
        conn = registry.register(
            host_id=_HOST_ID,
            ws=_FakeWebSocket(),  # type: ignore[arg-type] — duck-typed
            hello=_hello_frame([CAP_WORKSPACE_OPS]),
            owner="alice@example.com",
        )
    assert conn.account_generation == "gen-1"

    async def send() -> WorkspaceOpReply:
        return await request_workspace_op_on_host(
            host_registry=registry,
            host_conn=conn,
            op="commit",
            root=_ROOT,
            params=_PARAMS,
            timeout_s=600.0,
            op_key="k" * 32,
        )

    if scope is None:
        request = asyncio.create_task(send())
    else:
        with host_owner_scope(*scope):
            request = asyncio.create_task(send())
    try:
        if sent:
            await poll_until_async(
                lambda: conn.pending_workspace_ops or request.done(), timeout_s=5
            )
            assert not request.done()
            assert not conn.outbound_queue.empty()
        else:
            with pytest.raises(HostWorkspaceOpNotPermittedError):
                await asyncio.wait_for(request, timeout=5.0)
            assert conn.outbound_queue.empty()
    finally:
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
    assert conn.pending_workspace_ops == {}


async def test_cancelled_request_leaves_no_pending_entry() -> None:
    """The caller gave up; the late result then finds nothing to resolve."""
    registry = HostRegistry()
    conn = _register(registry, [CAP_WORKSPACE_OPS])
    request = asyncio.create_task(_request(conn, registry, timeout_s=600.0))
    await poll_until_async(lambda: conn.pending_workspace_ops or request.done(), timeout_s=5)
    assert not request.done()

    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request

    assert conn.pending_workspace_ops == {}


@pytest.mark.parametrize("drop", ["deregister", "replace"])
async def test_dropped_tunnel_fails_a_pending_op_at_once(drop: str) -> None:
    registry = HostRegistry()
    conn = _register(registry, [CAP_WORKSPACE_OPS])
    request = asyncio.create_task(_request(conn, registry, timeout_s=600.0))
    try:
        await poll_until_async(lambda: conn.pending_workspace_ops or request.done(), timeout_s=5)
        assert not request.done()
        if drop == "deregister":
            registry.deregister(_HOST_ID)
        else:
            _register(registry, [CAP_WORKSPACE_OPS])

        with pytest.raises(HostWorkspaceOpUnavailableError) as exc:
            await asyncio.wait_for(request, timeout=5.0)
    finally:
        request.cancel()

    assert exc.value.timed_out is False
    assert "connection lost" in exc.value.message
    assert conn.pending_workspace_ops == {}


async def test_unanswered_op_times_out_after_its_timeout_plus_the_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert WORKSPACE_OP_REPLY_GRACE_S == 15.0
    monkeypatch.setattr(host_workspace_ops, "WORKSPACE_OP_REPLY_GRACE_S", 0.1)
    registry = HostRegistry()
    conn = _register(registry, [CAP_WORKSPACE_OPS])

    started = time.monotonic()
    with pytest.raises(HostWorkspaceOpUnavailableError) as exc:
        await asyncio.wait_for(_request(conn, registry, timeout_s=0.1), timeout=5.0)
    elapsed = time.monotonic() - started

    assert exc.value.timed_out is True
    assert "did not respond" in exc.value.message
    # The host advertised the token, so it is not described as outdated.
    assert "older version" not in exc.value.message
    # Never earlier than the op's own timeout plus the grace (with timer slack).
    assert elapsed >= 0.2 - 0.02
    assert conn.pending_workspace_ops == {}


@pytest.fixture()
async def tunnel(db_uri: str) -> AsyncIterator[tuple[HostRegistry, ApplicationCommunicator]]:
    """A host connected through the real host tunnel route, advertising the token."""
    registry = HostRegistry()
    app = FastAPI()
    app.include_router(create_host_tunnel_router(registry, HostStore(db_uri)), prefix="/v1")
    comm = ApplicationCommunicator(app, websocket_scope(f"/v1/hosts/{_TUNNEL_HOST_ID}/tunnel"))
    await comm.send_input({"type": "websocket.connect"})
    accepted = await comm.receive_output(timeout=1.0)
    assert accepted["type"] == "websocket.accept"
    hello = encode_host_frame(_hello_frame([CAP_WORKSPACE_OPS]))
    await comm.send_input({"type": "websocket.receive", "text": hello})
    await poll_until_async(lambda: registry.get(_TUNNEL_HOST_ID) is not None, timeout_s=5)
    try:
        yield registry, comm
    finally:
        await comm.send_input({"type": "websocket.disconnect", "code": 1000})
        await comm.wait(timeout=5.0)


async def _next_workspace_op(comm: ApplicationCommunicator) -> HostWorkspaceOpFrame:
    """Read the server's outbound frames until the workspace-op request arrives."""
    while True:
        output = await comm.receive_output(timeout=5.0)
        text = output.get("text") if output.get("type") == "websocket.send" else None
        if not isinstance(text, str):
            continue
        try:
            frame = decode_host_frame(text)
        except ValueError:
            continue  # a runner-encoded keepalive ping
        if isinstance(frame, HostWorkspaceOpFrame):
            return frame


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(
            HostWorkspaceOpResultFrame(
                request_id="", status="ok", payload={"commit": "c" * 40, "empty": False}
            ),
            id="ok",
        ),
        pytest.param(
            HostWorkspaceOpResultFrame(
                request_id="",
                status="failed",
                payload={"partial": True},
                error_code="workspace.git_failed",
                error="git commit-tree failed",
                exit_code=128,
                permanent=True,
            ),
            id="failed-every-field-set",
        ),
    ],
)
async def test_routed_result_resolves_the_request_with_all_six_fields(
    tunnel: tuple[HostRegistry, ApplicationCommunicator],
    reply: HostWorkspaceOpResultFrame,
) -> None:
    registry, comm = tunnel
    conn = registry.get(_TUNNEL_HOST_ID)
    assert conn is not None
    request = asyncio.create_task(_request(conn, registry, timeout_s=600.0))
    try:
        sent = await _next_workspace_op(comm)
        assert re.fullmatch(r"[0-9a-f]{32}", sent.request_id)
        assert sent == HostWorkspaceOpFrame(
            request_id=sent.request_id,
            op="commit",
            root=_ROOT,
            params=_PARAMS,
            timeout_s=600.0,
            op_key="k" * 32,
        )
        answer = dataclasses.replace(reply, request_id=sent.request_id)
        await comm.send_input({"type": "websocket.receive", "text": encode_host_frame(answer)})

        result = await asyncio.wait_for(request, timeout=5.0)
    finally:
        request.cancel()

    assert result == WorkspaceOpReply(
        status=reply.status,
        payload=reply.payload,
        error_code=reply.error_code,
        error=reply.error,
        exit_code=reply.exit_code,
        permanent=reply.permanent,
    )
    assert conn.pending_workspace_ops == {}


async def test_host_error_text_is_cut_and_a_malformed_code_reads_as_handler_failed(
    tunnel: tuple[HostRegistry, ApplicationCommunicator],
) -> None:
    """A buggy or modified host cannot hand the caller unbounded text or an odd code."""
    registry, comm = tunnel
    conn = registry.get(_TUNNEL_HOST_ID)
    assert conn is not None
    request = asyncio.create_task(_request(conn, registry, timeout_s=600.0))
    try:
        sent = await _next_workspace_op(comm)
        answer = HostWorkspaceOpResultFrame(
            request_id=sent.request_id,
            status="failed",
            error_code="Workspace Failed!",
            error="x" * 5000 + " fatal: the real cause",
            exit_code=1,
        )
        await comm.send_input({"type": "websocket.receive", "text": encode_host_frame(answer)})
        result = await asyncio.wait_for(request, timeout=5.0)
    finally:
        request.cancel()

    assert result.error_code == "handler_failed"
    assert result.error is not None
    assert len(result.error) == 2000
    assert result.error.endswith(" fatal: the real cause")
    assert (result.status, result.exit_code, result.permanent) == ("failed", 1, False)


def _ok_result(request_id: str, answer: str) -> str:
    return encode_host_frame(
        HostWorkspaceOpResultFrame(request_id=request_id, status="ok", payload={"answer": answer})
    )


async def test_results_reach_their_own_requests_and_stray_results_are_dropped(
    tunnel: tuple[HostRegistry, ApplicationCommunicator],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent requests match replies by id; late, unknown, malformed and duplicate
    results are dropped without resolving anything or closing the tunnel."""
    registry, comm = tunnel
    conn = registry.get(_TUNNEL_HOST_ID)
    assert conn is not None
    monkeypatch.setattr(host_workspace_ops, "WORKSPACE_OP_REPLY_GRACE_S", 0.05)
    with pytest.raises(HostWorkspaceOpUnavailableError):
        await asyncio.wait_for(_request(conn, registry, timeout_s=0.05), timeout=5.0)
    late_id = (await _next_workspace_op(comm)).request_id

    earlier = asyncio.create_task(_request(conn, registry, timeout_s=600.0))
    earlier_id = (await _next_workspace_op(comm)).request_id
    later = asyncio.create_task(_request(conn, registry, timeout_s=600.0))
    later_id = (await _next_workspace_op(comm)).request_id
    malformed = {"kind": "host.workspace_op_result", "request_id": later_id, "status": "maybe"}
    try:
        # The tunnel reads in order: once `earlier` resolves, every text before it was handled.
        for text in (
            _ok_result(late_id, "late"),
            _ok_result("f" * 32, "unknown"),
            json.dumps(malformed),
            _ok_result(later_id, "later"),
            _ok_result(later_id, "duplicate"),
            _ok_result(earlier_id, "earlier"),
        ):
            await comm.send_input({"type": "websocket.receive", "text": text})
        earlier_reply = await asyncio.wait_for(earlier, timeout=5.0)
        later_reply = await asyncio.wait_for(later, timeout=5.0)
    finally:
        earlier.cancel()
        later.cancel()

    assert earlier_reply.payload == {"answer": "earlier"}
    assert later_reply.payload == {"answer": "later"}
    assert registry.get(_TUNNEL_HOST_ID) is conn
    assert conn.pending_workspace_ops == {}
