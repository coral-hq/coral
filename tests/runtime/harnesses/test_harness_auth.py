from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from omnigent.runtime.harnesses._runner import _BearerGate
from tests.runtime.harnesses._test_scaffold_harnesses import _EchoHarness

_URL = "/v1/sessions/conv_x/events"
_BODY = {"type": "interrupt"}  # simplest inbound event; needs no in-flight turn


def _build_app() -> FastAPI:
    app = _EchoHarness().build()
    app.state.conversation_id = "conv_x"
    return app


def test_v1_is_inert_without_a_configured_token() -> None:
    """No token on app.state (direct embedder) -> /v1 is not gated."""
    app = _build_app()
    with TestClient(app) as client:
        # Reaches the handler (404: interrupt with no in-flight turn), not 401.
        assert client.post(_URL, json=_BODY).status_code != 401


def test_v1_requires_the_bearer_token_when_configured() -> None:
    """Token on app.state -> /v1 demands a matching bearer token."""
    app = _build_app()
    app.state.harness_auth_token = "s3cret-token"
    with TestClient(app) as client:
        # Missing and wrong tokens are rejected before any turn logic runs.
        assert client.post(_URL, json=_BODY).status_code == 401
        assert (
            client.post(_URL, json=_BODY, headers={"Authorization": "Bearer nope"}).status_code
            == 401
        )
        # A bad scheme is rejected too.
        assert (
            client.post(_URL, json=_BODY, headers={"Authorization": "s3cret-token"}).status_code
            == 401
        )
        # The correct token passes the gate (404 from the handler, not 401).
        ok = client.post(_URL, json=_BODY, headers={"Authorization": "Bearer s3cret-token"})
        assert ok.status_code != 401


# CORAL(S129)


@pytest.mark.parametrize(
    "header",
    [None, "Basic s3cret-token", "Bearer nope", "Bearer", "s3cret-token"],
)
def test_gate_refuses_before_the_app_runs(header: str | None) -> None:
    gated = _BearerGate(_build_app(), "s3cret-token")
    headers = {"Content-Type": "application/json"}
    if header is not None:
        headers["Authorization"] = header
    with TestClient(gated) as client:
        assert client.get("/health", headers=headers).status_code == 401
        response = client.post(_URL, content=b"{not json", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"detail": "unauthorized"}


def test_gate_passes_a_matching_bearer_with_any_scheme_case() -> None:
    gated = _BearerGate(_build_app(), "s3cret-token")
    with TestClient(gated) as client:
        headers = {"Authorization": "bearer s3cret-token"}
        assert client.get("/health", headers=headers).status_code == 200
        response = client.post(
            _URL,
            content=b"{not json",
            headers={**headers, "Content-Type": "application/json"},
        )
        assert response.status_code == 422


def test_gate_passes_lifespan_and_closes_an_unauthenticated_websocket() -> None:
    events: list[str] = []

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        events.append("startup")
        yield
        events.append("shutdown")

    app = FastAPI(lifespan=lifespan)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        events.append("ws")
        await websocket.accept()
        await websocket.close()

    with TestClient(_BearerGate(app, "s3cret-token")) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass
        with client.websocket_connect("/ws", headers={"Authorization": "Bearer s3cret-token"}):
            pass
    assert events == ["startup", "ws", "shutdown"]
