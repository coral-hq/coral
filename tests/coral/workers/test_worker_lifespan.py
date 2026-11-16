"""Tests for OmnigentRunScopeRunner and coral_lifespan server plugin integration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI

from coral.omni.server import OmnigentRunScopeRunner, coral_lifespan
from omnigent.db.account_authority import account_generation, current_account_user
from omnigent.db.db_models import current_workspace_id
from omnigent.db.utils import _run_migrations as run_omni_migrations
from omnigent.db.utils import create_db_engine
from omnigent.server.host_registry import _expected_host_owner
from omnigent.server.server_plugins import ServerServices


async def test_omnigent_run_scope_runner_sets_all_three_ambient_scopes() -> None:
    """Verify OmnigentRunScopeRunner enters workspace, account_authority, and host_owner scopes."""
    runner = OmnigentRunScopeRunner()
    async with runner.run_scope(
        workspace_id=42,
        run_id="run_42",
        user_id="user_alice",
        account_generation="gen_99",
        host_id="host_1",
        owner_key="slot:1",
    ):
        assert current_workspace_id() == 42
        assert current_account_user() == "user_alice"
        assert account_generation("user_alice") == "gen_99"
        host_owner = _expected_host_owner.get()
        assert host_owner is not None
        assert host_owner.user_id == "user_alice"
        assert host_owner.generation == "gen_99"
        assert host_owner.workspace_id == 42


async def test_coral_lifespan_skips_in_memory_or_d1_and_boots_on_operational_db(
    tmp_path: Path,
) -> None:
    """Verify coral_lifespan skips non-shared :memory:/D1 and boots WorkerSupervisor on real DB."""
    app = FastAPI()

    # 1. Non-shared :memory: SQLite is skipped cleanly without starting a supervisor
    in_mem_services = cast(
        ServerServices,
        SimpleNamespace(
            host_sharded=False,
            conversation_store=SimpleNamespace(storage_location="sqlite:///:memory:"),
        ),
    )
    async with coral_lifespan(app, in_mem_services):
        assert not hasattr(app.state, "coral_worker_supervisor")

    # 2. Cloudflare D1 is skipped cleanly
    d1_services = cast(
        ServerServices,
        SimpleNamespace(
            host_sharded=False,
            conversation_store=SimpleNamespace(storage_location="cloudflare_d1://acct/db"),
        ),
    )
    async with coral_lifespan(app, d1_services):
        assert not hasattr(app.state, "coral_worker_supervisor")

    # 3. Host-sharded raises RuntimeError
    sharded_services = cast(
        ServerServices,
        SimpleNamespace(
            host_sharded=True,
            conversation_store=SimpleNamespace(storage_location=None),
        ),
    )
    with pytest.raises(RuntimeError, match="host_sharded=True"):
        async with coral_lifespan(app, sharded_services):
            pass

    # 4. File-backed operational SQLite DB runs ensure_coral_schema and starts WorkerSupervisor
    db_file = tmp_path / "operational.db"
    db_uri = f"sqlite:///{db_file}"
    engine = create_db_engine(db_uri)
    run_omni_migrations(engine, db_uri)
    engine.dispose()

    real_services: Any = SimpleNamespace(
        host_sharded=False,
        conversation_store=SimpleNamespace(storage_location=db_uri),
    )
    async with coral_lifespan(app, cast(ServerServices, real_services)):
        sup = app.state.coral_worker_supervisor
        assert sup is not None
        await sup.leader_ready_event.wait()
        assert sup.is_leader
    assert not sup.is_leader
