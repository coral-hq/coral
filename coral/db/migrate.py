"""Isolated Alembic migration runner and schema gatekeeper for Coral."""

from __future__ import annotations

import argparse
import logging
import re
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from omnigent.db.query_context import query_name_scope
from omnigent.db.utils import (
    create_db_engine,
    get_db_revision_state,
    get_or_create_engine,
    is_cockroachdb,
    normalize_database_url,
)

_logger = logging.getLogger(__name__)

# custom-lint: disable-next=workspace-scoped-cache -- DB-URI schema cache
_migrated_uris: set[str] = set()
_migrated_lock = threading.Lock()


class CoralSchemaOrderError(RuntimeError):
    """Raised when Coral schema migrations are attempted before Omnigent reaches head."""


def clear_coral_schema_cache() -> None:
    """Clear the in-memory cache of migrated database URIs."""
    with _migrated_lock:
        _migrated_uris.clear()


def _is_memory_uri(uri: str) -> bool:
    return ":memory:" in uri or "mode=memory" in uri or uri in {"sqlite://", "sqlite:///"}


def _check_dispatch_support(db_uri: str) -> None:
    """Refuse unsupported databases such as Cloudflare D1."""
    url = make_url(db_uri)
    backend = url.get_backend_name()
    driver = url.drivername
    if backend in {"d1", "cloudflare_d1"} or driver in {"d1", "cloudflare_d1", "sqlite+d1"}:
        raise NotImplementedError(
            "Coral persistence does not support Cloudflare D1: its REST driver does not "
            "support the multi-statement transactions needed for schema migrations and "
            "leased state transitions. Use a supported database backend."
        )


def _build_coral_alembic_config(db_uri: str) -> Config:
    alembic_ini = Path(__file__).parent / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("sqlalchemy.url", db_uri.replace("%", "%%"))
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    return config


def _get_coral_head_revision(config: Config) -> str:
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if not heads or len(heads) != 1 or heads[0] is None:
        raise RuntimeError(
            f"Coral migration scripts must have exactly one head revision; found {heads!r}"
        )
    return heads[0]


def _crdb_version_tuple(engine: Engine) -> tuple[int, int] | None:
    with engine.connect() as conn:
        raw = str(conn.execute(text("SELECT version()")).scalar_one())
    match = re.search(r"CockroachDB(?: \w+)? v(\d+)\.(\d+)", raw)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)))


_SERIALIZABLE_TRANSACTION = "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"


def _prepare_crdb_ddl(conn: Connection, version: tuple[int, int] | None) -> None:
    if version is not None and version >= (24, 1):
        conn.execute(text("SET autocommit_before_ddl = true"))
        conn.commit()
    conn.execute(text(_SERIALIZABLE_TRANSACTION))


def commit_crdb_revision(conn: Connection) -> None:
    """Commit one revision's schema changes, then open the next SERIALIZABLE schema transaction."""
    conn.commit()
    conn.execute(text(_SERIALIZABLE_TRANSACTION))


def _get_current_coral_revision_on_engine(engine: Engine) -> str | None:
    with query_name_scope("coral.database.select_current_revision"), engine.connect() as conn:
        inspector = inspect(conn)
        if "coral_alembic_version" not in inspector.get_table_names():
            return None
        ctx = MigrationContext.configure(conn, opts={"version_table": "coral_alembic_version"})
        return ctx.get_current_revision()


def current_coral_revision(db_uri: str) -> tuple[str | None, str]:
    """Return the database's current Coral revision and head revision."""
    normalized = normalize_database_url(db_uri)
    _check_dispatch_support(normalized)
    config = _build_coral_alembic_config(normalized)
    head = _get_coral_head_revision(config)
    engine = create_db_engine(normalized)
    try:
        current = _get_current_coral_revision_on_engine(engine)
        return (current, head)
    finally:
        engine.dispose()


def ensure_coral_schema(db_uri: str) -> None:
    """Ensure that Coral database schema is migrated to head.

    1. Normalize URL and check cache (never cache :memory: SQLite).
    2. Refuse Cloudflare D1 databases.
    3. Verify Omnigent schema is at head. If not, raise CoralSchemaOrderError.
    4. Verify Coral migration scripts have a single head revision.
    5. Verify current Coral revision is not newer than this build.
    6. Apply migrations to head on a single connection.
    7. Verify current revision equals head and cache URL.
    """
    normalized = normalize_database_url(db_uri)
    is_memory = _is_memory_uri(normalized)
    if not is_memory:
        with _migrated_lock:
            if normalized in _migrated_uris:
                return

    _check_dispatch_support(normalized)

    engine = create_db_engine(normalized)
    try:
        # Step 3: Require Omnigent schema to be at head
        omni_current, omni_head = get_db_revision_state(engine, normalized)
        if omni_current != omni_head:
            raise CoralSchemaOrderError(
                f"Omnigent database schema is not at head (current: {omni_current!r}, "
                f"expected head: {omni_head!r}). "
                "Omnigent migrations must run strictly before Coral."
            )

        # Step 4: Verify single head revision
        config = _build_coral_alembic_config(normalized)
        head = _get_coral_head_revision(config)
        script = ScriptDirectory.from_config(config)

        # Step 5: Verify current Coral revision is supported
        current = _get_current_coral_revision_on_engine(engine)
        if current is not None:
            try:
                script.get_revision(current)
            except CommandError as exc:
                raise RuntimeError(
                    "Coral database schema is newer than this version of Coral "
                    f"(found revision {current!r}, latest supported revision {head!r}). "
                    "Upgrade Coral before using this database."
                ) from exc

        # Step 6: Apply upgrade if not already at head
        if current != head:
            with query_name_scope("coral.database.run_migrations"):
                crdb = is_cockroachdb(engine.dialect.name)
                crdb_version = _crdb_version_tuple(engine) if crdb else None
                with engine.connect() as conn:
                    if crdb:
                        _prepare_crdb_ddl(conn, crdb_version)
                    config.attributes["connection"] = conn
                    command.upgrade(config, "head")
                    if conn.in_transaction():
                        conn.commit()

        # Step 7: Verify post-migration revision equals head
        current_after = _get_current_coral_revision_on_engine(engine)
        if current_after != head:
            raise RuntimeError(
                f"Coral database migration did not reach head (started at {current!r}, "
                f"now at {current_after!r}, expected {head!r})."
            )

        if not is_memory:
            with _migrated_lock:
                _migrated_uris.add(normalized)
    finally:
        engine.dispose()


def coral_engine(db_uri: str) -> Engine:
    """Return pooled operational database engine after verifying Coral schema."""
    ensure_coral_schema(db_uri)
    return get_or_create_engine(db_uri)


def run_coral_migrations_with_retry(
    db_uri: str,
    *,
    max_attempts: int = 5,
    retry_delay_s: float | None = None,
    backoff_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run Coral migrations with retry for cold databases."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    base_backoff = retry_delay_s if retry_delay_s is not None else backoff_seconds

    for attempt in range(1, max_attempts + 1):
        try:
            ensure_coral_schema(db_uri)
            return
        except (CoralSchemaOrderError, NotImplementedError, RuntimeError):
            raise
        except OperationalError as exc:
            if attempt == max_attempts:
                _logger.error(
                    "Coral database not reachable after %d attempt(s); giving up",
                    max_attempts,
                )
                raise
            delay = base_backoff * attempt if base_backoff > 0 else 0.0
            _logger.warning(
                "Coral DB connect/migrate attempt %d/%d failed (%s); retrying in %.1fs",
                attempt,
                max_attempts,
                type(exc).__name__,
                delay,
            )
            if delay > 0:
                sleep(delay)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for manual recovery and schema inspection."""
    parser = argparse.ArgumentParser(
        prog="python -m coral.db.migrate",
        description="Coral database schema migration management tool",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    upgrade_parser = subparsers.add_parser("upgrade", help="Upgrade Coral schema to head")
    upgrade_parser.add_argument("uri", help="Database connection URL")

    current_parser = subparsers.add_parser("current", help="Inspect current Coral schema revision")
    current_parser.add_argument("uri", help="Database connection URL")

    args = parser.parse_args(argv)

    if args.subcommand == "upgrade":
        ensure_coral_schema(args.uri)
        current, head = current_coral_revision(args.uri)
        print(f"Coral schema upgraded to revision {current} (head: {head})")
        return 0
    if args.subcommand == "current":
        current, head = current_coral_revision(args.uri)
        print(f"Current Coral revision: {current} (head: {head})")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
