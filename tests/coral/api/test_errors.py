"""The Coral route class: one error envelope for every refusal, and JSON-only POST bodies."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine

from coral.api.errors import (
    NOT_FOUND_RUN,
    CoralApiError,
    CoralRoute,
    error_responses,
    run_not_found,
)
from coral.api.sub_features import resolve_sub_features
from coral.omni.server.plugin import coral_routers
from coral.stores.workflows import SqlWorkflowDefinitionStore

FIXED_RUN_404 = b'{"error":{"code":"not_found","message":"Run not found.","details":null}}'


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=8)


async def _signed_in(request: Request) -> str:
    user = request.headers.get("X-User")
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _probe_router() -> APIRouter:
    router = APIRouter(route_class=CoralRoute)

    @router.get("/raise/{status}", responses=error_responses(401, 404))
    def raise_http(status: int, detail: str = "Plain words") -> None:
        raise HTTPException(status_code=status, detail=detail, headers={"Retry-After": "3"})

    @router.get("/coral")
    def raise_coral() -> None:
        raise CoralApiError(
            "server_busy",
            "Too many requests are running.",
            503,
            details={"reason": "in_flight"},
            headers={"Retry-After": "1"},
        )

    @router.get("/run")
    def missing_run() -> None:
        raise run_not_found()

    @router.get("/structured")
    def structured_detail() -> None:
        raise HTTPException(status_code=409, detail={"nested": "value"})

    @router.get("/crash")
    def crash() -> None:
        raise RuntimeError("not an API refusal")

    @router.get("/me")
    def me(user: str = Depends(_signed_in)) -> dict[str, str]:
        return {"user": user}

    @router.post("/echo")
    def echo(body: _Body, user: str = Depends(_signed_in)) -> dict[str, str]:
        return {"name": body.name, "user": user}

    return router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(_probe_router(), prefix="/v1/coral")
    return TestClient(app)


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "validation_failed"),
        (401, "unauthenticated"),
        (403, "not_permitted"),
        (404, "not_found"),
        (409, "illegal_transition"),
        (413, "payload_too_large"),
        (418, "validation_failed"),
        (422, "validation_failed"),
        (429, "stream_limit"),
        (501, "not_implemented"),
        (503, "server_busy"),
    ],
)
def test_an_http_exception_becomes_the_envelope_with_its_status_and_headers(
    client: TestClient, status: int, code: str
) -> None:
    response = client.get(f"/v1/coral/raise/{status}")

    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": "Plain words", "details": None}}
    assert response.headers["Retry-After"] == "3"


@pytest.mark.parametrize("status", [500, 502])
def test_a_server_error_is_left_to_the_servers_own_handler(
    client: TestClient, status: int
) -> None:
    response = client.get(f"/v1/coral/raise/{status}")

    assert (response.status_code, response.json()) == (status, {"detail": "Plain words"})


def test_a_not_modified_answer_keeps_its_empty_body(client: TestClient) -> None:
    response = client.get("/v1/coral/raise/304")

    assert (response.status_code, response.content) == (304, b"")


def test_a_refusal_needs_an_error_status() -> None:
    with pytest.raises(ValueError, match="4xx or 5xx"):
        CoralApiError("not_found", "Gone", 304)


def test_declared_descriptions_do_not_depend_on_the_python_release() -> None:
    # http.HTTPStatus renamed these in Python 3.13.
    assert {
        status: entry["description"] for status, entry in error_responses(413, 422).items()
    } == {
        413: "Content Too Large",
        422: "Unprocessable Content",
    }


def test_a_structured_detail_is_not_echoed(client: TestClient) -> None:
    response = client.get("/v1/coral/structured")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "illegal_transition",
        "message": "Conflict",
        "details": None,
    }


def test_a_coral_api_error_keeps_its_code_details_and_headers(client: TestClient) -> None:
    response = client.get("/v1/coral/coral")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.json() == {
        "error": {
            "code": "server_busy",
            "message": "Too many requests are running.",
            "details": {"reason": "in_flight"},
        }
    }


def test_the_run_not_found_body_is_fixed_to_the_byte(client: TestClient) -> None:
    response = client.get("/v1/coral/run")

    assert (response.status_code, response.content) == (404, FIXED_RUN_404)
    assert NOT_FOUND_RUN.model_dump() == {
        "code": "not_found",
        "message": "Run not found.",
        "details": None,
    }


def test_a_refusal_raised_by_a_dependency_is_enveloped(client: TestClient) -> None:
    for response in (
        client.get("/v1/coral/me"),
        client.post("/v1/coral/echo", json={"name": "a"}),
    ):
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


def test_other_exceptions_are_not_caught(client: TestClient) -> None:
    with pytest.raises(RuntimeError, match="not an API refusal"):
        client.get("/v1/coral/crash")


def test_request_validation_keeps_location_message_and_type_but_never_the_input(
    client: TestClient,
) -> None:
    secret = "do-not-echo-this-value"
    response = client.post(
        "/v1/coral/echo", json={"name": secret, "extra": secret}, headers={"X-User": "alice"}
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert (error["code"], error["message"]) == ("validation_failed", "The request is invalid.")
    assert sorted(tuple(item) for item in error["details"]["errors"]) == [
        ("loc", "msg", "type"),
        ("loc", "msg", "type"),
    ]
    assert {tuple(item["loc"]) for item in error["details"]["errors"]} == {
        ("body", "name"),
        ("body", "extra"),
    }
    assert secret not in response.text


@pytest.mark.parametrize(
    "request_body",
    [
        pytest.param({"content": b'{"name": "a"}'}, id="no-media-type"),
        pytest.param(
            {"content": b'{"name": "a"}', "headers": {"content-type": "text/plain"}}, id="text"
        ),
        pytest.param({"data": {"name": "a"}}, id="form"),
        pytest.param(
            {
                "content": b'{"name": "a"}',
                "headers": {"content-type": "multipart/form-data; boundary=x"},
            },
            id="multipart",
        ),
        pytest.param(
            {"content": b'{"name": "a"}', "headers": {"content-type": "application/jsonp"}},
            id="json-prefix",
        ),
    ],
)
def test_a_post_without_a_json_media_type_is_refused(
    request_body: dict[str, Any],
) -> None:
    # A cross-site form can post these without a preflight; FastAPI's own check is
    # optional per app, so the route class refuses them itself.
    app = FastAPI(strict_content_type=False)
    app.include_router(_probe_router(), prefix="/v1/coral")
    client = TestClient(app)
    headers = {"X-User": "alice", **request_body.pop("headers", {})}

    response = client.post("/v1/coral/echo", headers=headers, **request_body)

    assert (response.status_code, response.json()) == (
        422,
        {
            "error": {
                "code": "validation_failed",
                "message": "The request body must be JSON.",
                "details": None,
            }
        },
    )


@pytest.mark.parametrize(
    "media_type",
    ["application/json", "application/json; charset=utf-8", "Application/merge-patch+json"],
)
def test_a_json_media_type_is_accepted(client: TestClient, media_type: str) -> None:
    response = client.post(
        "/v1/coral/echo",
        content=b'{"name": "a"}',
        headers={"X-User": "alice", "content-type": media_type},
    )

    assert (response.status_code, response.json()) == (200, {"name": "a", "user": "alice"})


def test_declared_refusals_reference_the_envelope_in_openapi() -> None:
    app = FastAPI()
    app.include_router(_probe_router(), prefix="/v1/coral")

    responses = app.openapi()["paths"]["/v1/coral/raise/{status}"]["get"]["responses"]

    for status in ("401", "404"):
        assert responses[status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/CoralErrorResponse"
        }


def _coral_app() -> FastAPI:
    """Every Coral router on a bare app that, like older FastAPI releases, parses any body."""
    routers = coral_routers(
        sub_features=resolve_sub_features(None),
        definitions=SqlWorkflowDefinitionStore(create_engine("sqlite://")),
        auth_provider=None,
    )
    app = FastAPI(strict_content_type=False)
    for router, prefix, tags in routers:
        app.include_router(router, prefix=prefix, tags=tags)
    return app


CORAL_POST_PATHS = sorted(
    route.path
    for route in _coral_app().routes
    if isinstance(route, APIRoute) and "POST" in route.methods
)


@pytest.mark.parametrize("path", CORAL_POST_PATHS)
@pytest.mark.parametrize("media_type", [None, "text/plain"])
def test_every_coral_post_route_refuses_a_body_that_is_not_json(
    path: str, media_type: str | None
) -> None:
    headers = {} if media_type is None else {"content-type": media_type}
    # Path parameters get a well-formed value, so only the media type is at fault.
    target = re.sub(r"\{[^}]+\}", "a" * 32, path)

    response = TestClient(_coral_app()).post(target, content=b"{}", headers=headers)

    assert (response.status_code, response.json()["error"]) == (
        422,
        {
            "code": "validation_failed",
            "message": "The request body must be JSON.",
            "details": None,
        },
    )
