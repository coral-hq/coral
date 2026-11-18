"""Live CockroachDB compatibility checks selected by OMNIGENT_TEST_DB_URI."""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect, make_url, text

from omnigent.db.cockroachdb import (
    _CRDB_BOOTSTRAP_MARKER_TABLE,
    _CRDB_BOOTSTRAP_MARKER_TOKEN,
    CRDB_BASELINE_REVISION,
    _crdb_server_version,
    _prepare_crdb_schema_transaction,
)
from omnigent.db.utils import (
    _build_alembic_config,
    _engine_cache,
    _engine_lock,
    _get_current_db_revision,
    _get_head_db_revision,
    _initialize_or_verify_schema,
    get_or_create_engine,
    is_cockroachdb,
    normalize_database_url,
)


def _crdb_engine(db_uri: str) -> Engine:
    engine = get_or_create_engine(db_uri)
    if not is_cockroachdb(engine.dialect.name):
        pytest.skip("requires OMNIGENT_TEST_DB_URI pointing to CockroachDB")
    return engine


# CORAL(S104): tests that rewrite the schema revision get a database of their own
@pytest.fixture
def scratch_crdb_uri() -> Iterator[str]:
    """A new CockroachDB database, dropped afterwards, for a test that rewrites schema state.

    The shared worker database can hold other suites' tables (Coral's persist between
    tests), and a rewrite that fails there breaks every later test on the worker.
    """
    root_uri = os.environ.get("OMNIGENT_TEST_DB_URI", "")
    if not root_uri or not is_cockroachdb(make_url(root_uri).get_backend_name()):
        pytest.skip("requires OMNIGENT_TEST_DB_URI pointing to CockroachDB")
    admin = create_engine(root_uri, isolation_level="AUTOCOMMIT")
    name = f"crdb_scratch_{uuid4().hex}"
    uri = admin.url.set(database=name).render_as_string(hide_password=False)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        yield uri
    finally:
        with _engine_lock:
            engine = _engine_cache.pop(normalize_database_url(uri), None)
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" CASCADE'))
        admin.dispose()


def test_cockroachdb_bootstrap_is_at_head(db_uri: str) -> None:
    engine = _crdb_engine(db_uri)
    assert _get_current_db_revision(engine) == _get_head_db_revision(db_uri)


def test_cockroachdb_uses_read_committed(db_uri: str) -> None:
    engine = _crdb_engine(db_uri)
    with engine.connect() as connection:
        isolation = connection.execute(text("SHOW transaction_isolation")).scalar_one()
    assert str(isolation).lower() == "read committed"


def test_cockroachdb_search_indexes_exist(db_uri: str) -> None:
    engine = _crdb_engine(db_uri)
    expected = {"ix_conversations_title_trgm"}
    found: set[str] = set()
    with engine.connect() as connection:
        for table in ("conversation_items", "conversations"):
            found.update(
                str(row["index_name"])
                for row in connection.execute(text(f"SHOW INDEXES FROM {table}")).mappings()
            )
    assert expected <= found
    assert "ix_conversation_items_search_text_trgm" not in found


def test_cockroachdb_upgrades_from_supported_baseline(scratch_crdb_uri: str) -> None:
    engine = _crdb_engine(scratch_crdb_uri)
    head = _get_head_db_revision(scratch_crdb_uri)
    if head == CRDB_BASELINE_REVISION:
        pytest.skip("requires a migration after the CRDB baseline")

    config = _build_alembic_config(scratch_crdb_uri)
    with engine.connect() as connection:
        _prepare_crdb_schema_transaction(connection, _crdb_server_version(engine))
        config.attributes["connection"] = connection
        command.downgrade(config, CRDB_BASELINE_REVISION)
        connection.commit()

    assert _get_current_db_revision(engine) == CRDB_BASELINE_REVISION

    _initialize_or_verify_schema(engine, scratch_crdb_uri)

    assert _get_current_db_revision(engine) == head


def test_cockroachdb_resumes_empty_revision_and_repairs_indexes(scratch_crdb_uri: str) -> None:
    engine = _crdb_engine(scratch_crdb_uri)
    version = _crdb_server_version(engine)
    head = _get_head_db_revision(scratch_crdb_uri)
    index_name = "ix_agents_created_at"
    with engine.connect() as connection:
        _prepare_crdb_schema_transaction(connection, version)
        connection.execute(
            text(
                f"CREATE TABLE {_CRDB_BOOTSTRAP_MARKER_TABLE} "
                "(token STRING PRIMARY KEY, target_revision STRING NOT NULL)"
            )
        )
        connection.commit()
        _prepare_crdb_schema_transaction(connection, version)
        connection.execute(text(f"DROP INDEX IF EXISTS {index_name}"))
        connection.commit()
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {_CRDB_BOOTSTRAP_MARKER_TABLE} "
                "(token, target_revision) VALUES (:token, :target_revision)"
            ),
            {"token": _CRDB_BOOTSTRAP_MARKER_TOKEN, "target_revision": head},
        )
        connection.execute(text("DELETE FROM alembic_version"))

    _initialize_or_verify_schema(engine, scratch_crdb_uri)

    with engine.connect() as connection:
        found = {
            str(row["index_name"])
            for row in connection.execute(text("SHOW INDEXES FROM agents")).mappings()
        }
    assert _get_current_db_revision(engine) == head
    assert _CRDB_BOOTSTRAP_MARKER_TABLE not in inspect(engine).get_table_names()
    assert index_name in found


def test_account_generation_backfill_resumes_after_schema_commit(scratch_crdb_uri) -> None:
    from sqlalchemy import event

    from omnigent.server.accounts_store import SqlAlchemyAccountStore
    from omnigent.server.device_grant_store import DeviceGrantStore

    engine = _crdb_engine(scratch_crdb_uri)
    accounts = SqlAlchemyAccountStore(scratch_crdb_uri)
    accounts.create_user_with_password("migration-user", "existing-password-hash")
    grants = DeviceGrantStore(scratch_crdb_uri)
    grants.create_redeemed_grant(
        "migration-grant",
        user_id="migration-user",
        client_id="cli",
        refresh_token_hash="existing-refresh-hash",
        created_at=100,
    )
    config = _build_alembic_config(scratch_crdb_uri)
    with engine.connect() as connection:
        _prepare_crdb_schema_transaction(connection, _crdb_server_version(engine))
        config.attributes["connection"] = connection
        command.downgrade(config, "hh1b2c3d4e5f")
        connection.commit()

    def interrupt_backfill(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE users SET account_generation"):
            raise RuntimeError("injected backfill interruption")

    event.listen(engine, "before_cursor_execute", interrupt_backfill)
    try:
        with pytest.raises(RuntimeError, match="schema migration failed"):
            _initialize_or_verify_schema(engine, scratch_crdb_uri)
    finally:
        event.remove(engine, "before_cursor_execute", interrupt_backfill)
    assert _get_current_db_revision(engine) == "hh1b2c3d4e5f"
    assert "account_generation" in {c["name"] for c in inspect(engine).get_columns("users")}

    _initialize_or_verify_schema(engine, scratch_crdb_uri)
    account = accounts.get_user("migration-user")
    assert account is not None and len(account.account_generation) == 32
    assert accounts.get_password_hash("migration-user") == "existing-password-hash"
    grant = grants.authorize_access("migration-grant")
    assert grant is not None and grant.account_generation == account.account_generation
    assert _get_current_db_revision(engine) == _get_head_db_revision(scratch_crdb_uri)


@pytest.mark.parametrize("failed_attempts", [2, 3])
def test_project_preferences_copy_retries_serialization_failures(
    scratch_crdb_uri: str, failed_attempts: int, capfd: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy import event

    from omnigent.server.accounts_store import SqlAlchemyAccountStore

    engine = _crdb_engine(scratch_crdb_uri)
    accounts = SqlAlchemyAccountStore(scratch_crdb_uri)
    accounts.create_user_with_password("ordering-user", "existing-password-hash")
    config = _build_alembic_config(scratch_crdb_uri)
    with engine.connect() as connection:
        _prepare_crdb_schema_transaction(connection, _crdb_server_version(engine))
        config.attributes["connection"] = connection
        command.downgrade(config, "ii1a2b3c4d5e")
        connection.commit()

    payload = b"legacy project order bytes"
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET project_order = :value WHERE id = 'ordering-user'"),
            {"value": payload},
        )

    attempts = 0

    def fail_copy(conn, cursor, statement, parameters, context, executemany):
        nonlocal attempts
        if statement.startswith("INSERT INTO preferences"):
            attempts += 1
            if attempts <= failed_attempts:
                # Observed results prevent transparent server retries of a fresh transaction.
                cursor.execute("SELECT id FROM users WHERE id = 'ordering-user'")
                cursor.fetchone()
                return "SELECT crdb_internal.force_retry('10s')", ()
        return statement, parameters

    event.listen(engine, "before_cursor_execute", fail_copy, retval=True)
    try:
        _initialize_or_verify_schema(engine, scratch_crdb_uri)
    finally:
        event.remove(engine, "before_cursor_execute", fail_copy)

    assert attempts == 3
    assert _get_current_db_revision(engine) == _get_head_db_revision(scratch_crdb_uri)
    assert "project_order" not in {c["name"] for c in inspect(engine).get_columns("users")}
    with engine.connect() as connection:
        saved = connection.execute(
            text(
                "SELECT value FROM preferences "
                "WHERE user_id = 'ordering-user' AND key = 'project_order'"
            )
        ).scalar_one_or_none()
    assert saved == (payload if failed_attempts == 2 else None)
    warning = "Could not migrate project order preferences after 3 attempts"
    assert (warning in capfd.readouterr().err) == (failed_attempts == 3)
