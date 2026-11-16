"""Coral server plugin implementation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine, create_engine

from coral.api.info import create_info_router
from coral.api.sub_features import resolve_sub_features
from coral.api.workflows import create_workflows_router
from coral.db.migrate import ensure_coral_schema
from coral.db.models_workflows import CoralBase
from coral.omni.server.scopes import OmnigentRunScopeRunner
from coral.queue.store import SqlAlchemyCoralQueueStore
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.stores.workflows import SqlWorkflowDefinitionStore
from coral.workers.supervisor import WorkerSupervisor
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


def _is_usable_operational_db_uri(db_uri: str | None) -> bool:
    """Return True when db_uri is a persistent/shared operational DB suitable for Coral."""
    if not db_uri or not isinstance(db_uri, str):
        return False
    stripped = db_uri.strip()
    if not stripped or "cloudflare_d1" in stripped:
        return False
    if stripped in {"sqlite://", "sqlite:///:memory:"}:
        return False
    return not (":memory:" in stripped and "cache=shared" not in stripped)


@asynccontextmanager
async def coral_lifespan(
    app: FastAPI,
    services: ServerServices,
) -> AsyncIterator[None]:
    """Run Coral's startup migration check, worker supervisor, and reverse-order shutdown."""
    if services.host_sharded:
        raise RuntimeError("Coral server plugin does not support host_sharded=True")

    conv_store = getattr(services, "conversation_store", None)
    storage_location: str | None = getattr(conv_store, "storage_location", None)

    supervisor: WorkerSupervisor | None = None
    if _is_usable_operational_db_uri(storage_location):
        assert storage_location is not None
        await asyncio.to_thread(ensure_coral_schema, storage_location)
        run_store = SqlAlchemyCoralRunStore(storage_location)
        queue_store = SqlAlchemyCoralQueueStore(storage_location)
        scope_runner = OmnigentRunScopeRunner()
        supervisor = WorkerSupervisor(
            run_store,
            queue_store,
            scope_runner=scope_runner,
        )
        if hasattr(app, "state"):
            app.state.coral_run_store = run_store
            app.state.coral_queue_store = queue_store
            app.state.coral_worker_supervisor = supervisor
        await supervisor.start()

    try:
        yield
    finally:
        if supervisor is not None:
            await supervisor.stop()


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
