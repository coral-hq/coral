"""Coral server plugin implementation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine, create_engine

from coral.api.info import create_info_router
from coral.api.sub_features import resolve_sub_features
from coral.api.workflows import create_workflows_router
from coral.db.models_workflows import CoralBase
from coral.stores.workflows import SqlWorkflowDefinitionStore
from omnigent.process_logging import data_dir
from omnigent.server.server_plugins import ServerPluginRegistration, ServerServices

# Workspaces are not modelled yet, so every request shares one workflow library.
_SINGLE_WORKSPACE_ID = 0
_CORAL_DB_FILENAME = "coral.db"


def _single_workspace_id() -> int:
    return _SINGLE_WORKSPACE_ID


def _create_workflow_engine() -> Engine:
    """Open the SQLite file next to the Omnigent data and ensure the slim table exists."""
    data_path = data_dir()
    data_path.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{data_path / _CORAL_DB_FILENAME}")
    CoralBase.metadata.create_all(engine)
    return engine


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
    engine = _create_workflow_engine()
    workflows_router = create_workflows_router(
        SqlWorkflowDefinitionStore(engine),
        workspace_id_dependency=_single_workspace_id,
    )

    @asynccontextmanager
    async def workflow_engine_lifespan(
        _app: FastAPI,
        _services: ServerServices,
    ) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()

    return ServerPluginRegistration(
        routers=((info_router, "", ["coral"]), (workflows_router, "/v1/coral", ["coral"])),
        lifespan_hooks=(coral_lifespan, workflow_engine_lifespan),
        policy_modules=(),
    )
