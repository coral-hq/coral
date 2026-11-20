"""
The Coral API's one error shape and the route class that answers every refusal with it.

Every Coral router uses :class:`CoralRoute`: a refusal raised by a route or its
dependencies, and request validation, become ``{"error": {"code", "message",
"details"}}`` with the same status. Starlette's own 404 and 405 for paths and methods
no route matches are outside it.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from typing import Any, Final, Literal

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException

ErrorCode = Literal[
    "unauthenticated",
    "not_permitted",
    "not_found",
    "validation_failed",
    "not_runnable",
    "not_a_git_repo",
    "start_key_conflict",
    "workflow_key_taken",
    "illegal_transition",
    "stale_visit",
    "worktree_failed",
    "payload_too_large",
    "stream_limit",
    "not_implemented",
    "host_offline",
    "server_busy",
]

# The code an HTTPException's status maps to; any other 4xx is a validation failure.
_HTTP_CODES: Final[Mapping[int, ErrorCode]] = {
    401: "unauthenticated",
    403: "not_permitted",
    404: "not_found",
    409: "illegal_transition",
    413: "payload_too_large",
    422: "validation_failed",
    429: "stream_limit",
    501: "not_implemented",
    503: "server_busy",
}
# Fixed here rather than taken from ``http.HTTPStatus``, whose phrases change between
# Python releases (3.13 renamed 413 and 422) and would change the OpenAPI document.
_STATUS_PHRASES: Final[Mapping[int, str]] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    413: "Content Too Large",
    422: "Unprocessable Content",
    429: "Too Many Requests",
    501: "Not Implemented",
    503: "Service Unavailable",
}
_REFUSED = "The request was refused."
_INVALID_REQUEST = "The request is invalid."
_NOT_JSON = "The request body must be JSON."


class CoralError(BaseModel):
    """What was refused: a stable ``code``, a message for people, and machine-readable details."""

    # ``details`` is always sent, so the schema lists it as required.
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_serialization_defaults_required=True
    )

    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class CoralErrorResponse(BaseModel):
    """The body of every Coral refusal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error: CoralError


# Unknown, malformed and other users' runs all answer this one body.
NOT_FOUND_RUN: Final = CoralError(code="not_found", message="Run not found.")


class CoralApiError(Exception):
    """A refusal a Coral route raises; :class:`CoralRoute` answers it as the envelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status: int,
        details: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if not 400 <= status <= 599:
            raise ValueError(f"a refusal needs a 4xx or 5xx status, not {status}")
        super().__init__(message)
        self.error = CoralError(
            code=code, message=message, details=None if details is None else dict(details)
        )
        self.status = status
        self.headers = dict(headers or {})

    def response(self) -> JSONResponse:
        body = CoralErrorResponse(error=self.error).model_dump(mode="json")
        return JSONResponse(body, status_code=self.status, headers=self.headers)


def run_not_found() -> CoralApiError:
    """The refusal for any run the caller may not see, with the fixed body."""
    return CoralApiError(NOT_FOUND_RUN.code, NOT_FOUND_RUN.message, 404)


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` declaring that each of ``statuses`` answers the envelope."""
    return {
        status: {"model": CoralErrorResponse, "description": _STATUS_PHRASES[status]}
        for status in statuses
    }


def _is_json(request: Request) -> bool:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    subtype = media_type.removeprefix("application/")
    return subtype != media_type and (subtype == "json" or subtype.endswith("+json"))


def _enveloped(status: int) -> bool:
    """A 4xx, 501 or 503 is a refusal; a 304 has no body and other 5xx are server errors."""
    return 400 <= status < 500 or status in (501, 503)


def _from_http_exception(exc: HTTPException) -> CoralApiError:
    code = _HTTP_CODES.get(exc.status_code, "validation_failed")
    message = (
        exc.detail
        if isinstance(exc.detail, str)
        else _STATUS_PHRASES.get(exc.status_code, _REFUSED)
    )
    return CoralApiError(code, message, exc.status_code, headers=exc.headers)


def _from_validation_error(exc: RequestValidationError) -> CoralApiError:
    # Location, message and type only: the input and its context can hold what was sent.
    errors = [
        {"loc": list(error.get("loc", ())), "msg": error.get("msg", ""), "type": error.get("type")}
        for error in exc.errors()
    ]
    return CoralApiError("validation_failed", _INVALID_REQUEST, 422, details={"errors": errors})


class CoralRoute(APIRoute):
    """
    A route answering refusals as :class:`CoralErrorResponse` and POSTs only as JSON.

    A POST whose media type is not ``application/json`` or ``+json`` is refused first:
    a cross-site form can send text, form and multipart bodies, or none, without a
    preflight. Then a :class:`CoralApiError`, an ``HTTPException`` with a 4xx, 501 or
    503 status and request validation become the envelope. Anything else, a 304 or
    another server error among them, is left to the server's own handlers.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()
        json_only = "POST" in self.methods

        async def coral_handler(request: Request) -> Response:
            try:
                if json_only and not _is_json(request):
                    raise CoralApiError("validation_failed", _NOT_JSON, 422)
                return await handle(request)
            except CoralApiError as exc:
                return exc.response()
            except RequestValidationError as exc:
                return _from_validation_error(exc).response()
            except HTTPException as exc:
                if not _enveloped(exc.status_code):
                    raise
                return _from_http_exception(exc).response()

        return coral_handler


__all__ = [
    "NOT_FOUND_RUN",
    "CoralApiError",
    "CoralError",
    "CoralErrorResponse",
    "CoralRoute",
    "ErrorCode",
    "error_responses",
    "run_not_found",
]
