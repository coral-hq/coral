"""Coral server plugin implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from coral.api.info import create_info_router
from coral.api.sub_features import resolve_sub_features
from omnigent.server.server_plugins import ServerPluginRegistration, ServerServices


@asynccontextmanager
async def coral_lifespan(
    _app: FastAPI,
    services: ServerServices,
) -> AsyncIterator[None]:
    """Run Coral's startup and reverse-order shutdown checks."""
    if services.host_sharded:
        raise RuntimeError("Coral server plugin does not support host_sharded=True")
    yield


def register(services: ServerServices) -> ServerPluginRegistration:
    """Register Coral routers, policy modules, and lifespan hooks."""
    if services.host_sharded:
        raise RuntimeError("Coral server plugin does not support host_sharded=True")

    sub_features = resolve_sub_features(services.server_config)
    info_router = create_info_router(sub_features=sub_features)

    return ServerPluginRegistration(
        routers=((info_router, "", ["coral"]),),
        lifespan_hooks=(coral_lifespan,),
        policy_modules=(),
    )
