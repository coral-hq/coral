"""Tests for Coral migration gatekeeper, CLI, and schema ordering."""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import OperationalError

from coral.db.migrate import (
    CoralSchemaOrderError,
    clear_coral_schema_cache,
    coral_engine,
    current_coral_revision,
    ensure_coral_schema,
    main,
    run_coral_migrations_with_retry,
)
from omnigent.db import ConversationBase, OmnigentBase
from omnigent.db.utils import _run_migrations as run_omni_migrations


def _load_omni_include_name() -> Callable[[str | None, str, object], bool]:
    env_path = Path(__file__).resolve().parents[3] / "omnigent" / "db" / "migrations" / "env.py"
    tree = ast.parse(env_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_include_name":
            module_ast = ast.Module(body=[node], type_ignores=[])
            code = compile(module_ast, str(env_path), "exec")
            ns: dict[str, object] = {}
            exec(code, ns)
            return ns["_include_name"]  # type: ignore[return-value]
    raise RuntimeError("_include_name not found in omnigent/db/migrations/env.py")


@pytest.fixture(autouse=True)
def _reset_schema_cache() -> None:
    clear_coral_schema_cache()
    yield
    clear_coral_schema_cache()


def test_empty_db_raises_coral_schema_order_error_and_creates_zero_tables() -> None:
    """Coral migrations must refuse an unmigrated DB without creating tables."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "empty.db"
        uri = f"sqlite:///{db_path}"

        with pytest.raises(CoralSchemaOrderError, match="Omnigent database schema is not at head"):
            ensure_coral_schema(uri)

        engine = sa.create_engine(uri)
        try:
            inspector = sa.inspect(engine)
            tables = inspector.get_table_names()
            assert tables == [], f"Expected zero tables in empty DB, found {tables}"
        finally:
            engine.dispose()


def test_behind_head_omnigent_raises_coral_schema_order_error() -> None:
    """When Omnigent is behind head, Coral raises without creating coral_* tables."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "stale_omni.db"
        uri = f"sqlite:///{db_path}"

        engine = sa.create_engine(uri)
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
            conn.execute(sa.text("INSERT INTO alembic_version VALUES ('c9d3a1f2e4b5')"))
        engine.dispose()

        with pytest.raises(CoralSchemaOrderError, match="Omnigent database schema is not at head"):
            ensure_coral_schema(uri)

        engine = sa.create_engine(uri)
        try:
            inspector = sa.inspect(engine)
            tables = set(inspector.get_table_names())
            coral_tables = [t for t in tables if t.startswith("coral_")]
            assert coral_tables == [], f"No coral tables should be created, found {coral_tables}"
            assert "coral_alembic_version" not in tables
        finally:
            engine.dispose()


def test_d1_database_raises_not_implemented_error() -> None:
    """Cloudflare D1 is rejected with NotImplementedError."""
    for d1_uri in (
        "sqlite+d1://account:token@database",
        "d1://account:token@database",
        "cloudflare_d1://account:token@database",
    ):
        with pytest.raises(NotImplementedError, match="Cloudflare D1"):
            ensure_coral_schema(d1_uri)


def test_newer_coral_schema_raises_runtime_error() -> None:
    """Coral refuses schemas newer than this build."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "newer_coral.db"
        uri = f"sqlite:///{db_path}"

        # Bring Omnigent to head first
        omni_engine = sa.create_engine(uri)
        run_omni_migrations(omni_engine, uri)

        # Stamp a future Coral revision
        with omni_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "CREATE TABLE coral_alembic_version "
                    "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
            conn.execute(sa.text("INSERT INTO coral_alembic_version VALUES ('coral_9999_future')"))
        omni_engine.dispose()

        with pytest.raises(RuntimeError, match="Upgrade Coral before using this database"):
            ensure_coral_schema(uri)


def test_multiple_coral_heads_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Coral scripts report multiple heads, fail with RuntimeError."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "heads.db"
        uri = f"sqlite:///{db_path}"

        omni_engine = sa.create_engine(uri)
        run_omni_migrations(omni_engine, uri)
        omni_engine.dispose()

        from alembic.script import ScriptDirectory

        real_from_config = ScriptDirectory.from_config

        def _mock_from_config(cfg: object) -> MagicMock:
            script_loc = str(
                getattr(cfg, "get_main_option", lambda _: "")("script_location") or ""
            )
            if script_loc.endswith("coral/db/migrations") or "/coral/db/migrations" in script_loc:
                mock_script = MagicMock()
                mock_script.get_heads.return_value = ["coral_head_1", "coral_head_2"]
                return mock_script
            return real_from_config(cfg)

        monkeypatch.setattr(ScriptDirectory, "from_config", _mock_from_config)

        with pytest.raises(
            RuntimeError, match="Coral migration scripts must have exactly one head revision"
        ):
            ensure_coral_schema(uri)


def test_schema_cache_and_clear_cache() -> None:
    """Migrated URIs are cached in memory; clear_coral_schema_cache resets it."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cached.db"
        uri = f"sqlite:///{db_path}"

        omni_engine = sa.create_engine(uri)
        run_omni_migrations(omni_engine, uri)
        omni_engine.dispose()

        clear_coral_schema_cache()

        # First call migrates
        ensure_coral_schema(uri)
        current, head = current_coral_revision(uri)
        assert current == head == "coral_0002_session_facade"

        # Second call returns early via cache
        ensure_coral_schema(uri)

        # Clear cache and verify still valid at head
        clear_coral_schema_cache()
        ensure_coral_schema(uri)


def test_memory_sqlite_is_never_cached() -> None:
    """In-memory SQLite URIs are never cached."""
    # An in-memory DB has no Omnigent head, so it must raise CoralSchemaOrderError
    # on every call rather than returning early from cache.
    clear_coral_schema_cache()
    with pytest.raises(CoralSchemaOrderError):
        ensure_coral_schema("sqlite:///:memory:")

    with pytest.raises(CoralSchemaOrderError):
        ensure_coral_schema("sqlite:///:memory:")


def test_run_coral_migrations_with_retry_retries_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_coral_migrations_with_retry retries OperationalError and succeeds."""
    import coral.db.migrate as migrate_mod

    attempts = 0

    def _flaky_ensure(uri: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("connection failed", None, Exception("starting up"))

    monkeypatch.setattr(migrate_mod, "ensure_coral_schema", _flaky_ensure)

    run_coral_migrations_with_retry("sqlite:///dummy.db", max_attempts=5, backoff_seconds=0.0)
    assert attempts == 3


def test_run_coral_migrations_with_retry_fails_immediately_on_non_operational(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-operational errors (CoralSchemaOrderError, NotImplementedError) fail without retry."""
    import coral.db.migrate as migrate_mod

    attempts = 0

    def _order_err(uri: str) -> None:
        nonlocal attempts
        attempts += 1
        raise CoralSchemaOrderError("Omnigent not at head")

    monkeypatch.setattr(migrate_mod, "ensure_coral_schema", _order_err)

    with pytest.raises(CoralSchemaOrderError):
        run_coral_migrations_with_retry("sqlite:///dummy.db", max_attempts=5, backoff_seconds=0.0)

    assert attempts == 1


def test_run_coral_migrations_with_retry_exhausts_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OperationalError re-raises after exhausting max_attempts."""
    import coral.db.migrate as migrate_mod

    attempts = 0

    def _always_fail(uri: str) -> None:
        nonlocal attempts
        attempts += 1
        raise OperationalError("connection failed", None, Exception("dead host"))

    monkeypatch.setattr(migrate_mod, "ensure_coral_schema", _always_fail)

    with pytest.raises(OperationalError):
        run_coral_migrations_with_retry("sqlite:///dummy.db", max_attempts=3, backoff_seconds=0.0)

    assert attempts == 3


def test_coral_engine_helper() -> None:
    """coral_engine returns pooled Engine with migrated schema."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "engine_test.db"
        uri = f"sqlite:///{db_path}"

        omni_engine = sa.create_engine(uri)
        run_omni_migrations(omni_engine, uri)
        omni_engine.dispose()

        eng = coral_engine(uri)
        try:
            inspector = sa.inspect(eng)
            tables = set(inspector.get_table_names())
            assert "coral_workflows" in tables
            assert "coral_work" in tables
            assert "coral_alembic_version" in tables
        finally:
            eng.dispose()


def test_cli_upgrade_and_current() -> None:
    """python -m coral.db.migrate upgrade and current commands."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cli_test.db"
        uri = f"sqlite:///{db_path}"

        omni_engine = sa.create_engine(uri)
        run_omni_migrations(omni_engine, uri)
        omni_engine.dispose()

        # In-process main
        code = main(["upgrade", uri])
        assert code == 0

        code = main(["current", uri])
        assert code == 0

        # Subprocess invocation
        res = subprocess.run(
            [sys.executable, "-m", "coral.db.migrate", "current", uri],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, res.stderr
        assert "Current Coral revision: coral_0002_session_facade" in res.stdout


def test_s30_omnigent_autogenerate_ignores_coral_tables() -> None:
    """Seam S30: Omnigent autogenerate emits zero remove_table ops for coral tables."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "s30_test.db"
        uri = f"sqlite:///{db_path}"

        omni_engine = sa.create_engine(uri)
        run_omni_migrations(omni_engine, uri)
        omni_engine.dispose()

        # Migrate Coral
        ensure_coral_schema(uri)

        omni_include_name = _load_omni_include_name()
        engine = sa.create_engine(uri)
        try:
            with engine.connect() as conn:
                mc = MigrationContext.configure(
                    conn,
                    opts={
                        "include_name": omni_include_name,
                        "render_as_batch": True,
                    },
                )
                target_metadata = [OmnigentBase.metadata, ConversationBase.metadata]
                diff = compare_metadata(mc, target_metadata)

                # Check if any diff op is a remove_table for coral_*
                dropped_tables: list[str] = []
                for op_tuple in diff:
                    if op_tuple[0] == "remove_table":
                        table_name = op_tuple[1].name
                        if (
                            table_name.startswith("coral_")
                            or table_name == "coral_alembic_version"
                        ):
                            dropped_tables.append(table_name)

                assert dropped_tables == [], (
                    "S30 violation: Omnigent autogenerate attempted to drop Coral tables: "
                    f"{dropped_tables}"
                )
        finally:
            engine.dispose()


def test_crdb_ddl_prep_respects_server_version() -> None:
    """_prepare_crdb_ddl enables autocommit_before_ddl only on CRDB >= 24.1."""
    from coral.db.migrate import _prepare_crdb_ddl

    old_conn = MagicMock()
    _prepare_crdb_ddl(old_conn, (23, 2))
    executed_old = [str(call.args[0]) for call in old_conn.execute.call_args_list]
    assert executed_old == ["SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"]
    old_conn.commit.assert_not_called()

    new_conn = MagicMock()
    _prepare_crdb_ddl(new_conn, (24, 1))
    executed_new = [str(call.args[0]) for call in new_conn.execute.call_args_list]
    assert executed_new == [
        "SET autocommit_before_ddl = true",
        "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE",
    ]
    new_conn.commit.assert_called_once()


def test_standalone_alembic_cli_upgrade_and_env_populates_models() -> None:
    """Running alembic -c coral/db/alembic.ini upgrade head populates every Coral table."""
    repo_root = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "alembic_cli.db"
        uri = f"sqlite:///{db_path}"
        env = {"CORAL_DB_URL": uri, "PATH": ""}
        res = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "coral/db/alembic.ini", "upgrade", "head"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=env,
            check=False,
        )
        assert res.returncode == 0, res.stderr
        engine = sa.create_engine(uri)
        try:
            tables = set(sa.inspect(engine).get_table_names())
            assert "coral_workflows" in tables
            assert "coral_work" in tables
            assert "coral_worker_leases" in tables
            assert "coral_alembic_version" in tables
        finally:
            engine.dispose()
