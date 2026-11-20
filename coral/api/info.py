"""Coral server capability endpoint (`GET /v1/coral/info`)."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter
from pydantic import BaseModel

from coral.api.errors import CoralRoute
from coral.version import CORAL_VERSION


class CoralInfoResponse(BaseModel):
    """Response payload for ``GET /v1/coral/info``."""

    enabled: bool
    version: str
    sub_features: dict[str, bool]


def create_info_router(*, sub_features: Mapping[str, bool]) -> APIRouter:
    """Create the Coral capability router returning sub-feature availability."""
    router = APIRouter(route_class=CoralRoute)
    snapshot = dict(sub_features)

    @router.get("/v1/coral/info", operation_id="coral_get_info", response_model=CoralInfoResponse)
    async def coral_info() -> CoralInfoResponse:
        """Report whether Coral is enabled on this server and its sub-feature map."""
        return CoralInfoResponse(
            enabled=True,
            version=CORAL_VERSION,
            sub_features=dict(snapshot),
        )

    return router
