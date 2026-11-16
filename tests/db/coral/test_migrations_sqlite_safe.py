"""Guard that every Coral Alembic migration is SQLite-compatible and matches metadata."""

from __future__ import annotations

import ast
import tempfile
import warnings
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

import coral.db.models  # noqa: F401
from coral.db.base import CoralBase

_SQLITE_UNSAFE_OPS = frozenset(
    {
        "drop_column",
        "alter_column",
        "drop_constraint",
        "create_foreign_key",
        "create_unique_constraint",
        "create_check_constraint",
    }
)

_VERSIONS_DIR = Path(__file__).resolve().parents[3] / "coral" / "db" / "migrations" / "versions"
_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "coral" / "db" / "alembic.ini"
_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "coral" / "db" / "migrations"


def _raw_unsafe_op_calls(source: str) -> list[tuple[str, int]]:
    """Return (op_name, lineno) for raw op.<unsafe>(...) calls in source."""
    tree = ast.parse(source)
    offenders: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _SQLITE_UNSAFE_OPS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
        ):
            offenders.append((node.func.attr, node.lineno))
    return offenders


def test_no_coral_migration_uses_sqlite_unsafe_raw_ddl() -> None:
    """Every Coral migration must avoid calling SQLite-unsafe DDL on bare op."""
    version_files = sorted(_VERSIONS_DIR.glob("*.py"))
    assert len(version_files) >= 2, (
        f"Expected at least 2 migration versions, found {len(version_files)} at {_VERSIONS_DIR}"
    )
    offenders: dict[str, list[tuple[str, int]]] = {}
    for path in version_files:
        if path.name == "__init__.py":
            continue
        raw = _raw_unsafe_op_calls(path.read_text(encoding="utf-8"))
        if raw:
            offenders[path.name] = raw
    assert offenders == {}, (
        f"Coral migrations call SQLite-unsafe DDL on bare op proxy: {offenders}"
    )


def test_coral_migration_chain_round_trips_and_has_zero_drift_on_sqlite() -> None:
    """Upgrade head -> downgrade coral_0000_base -> upgrade head with zero schema drift."""
    with tempfile.TemporaryDirectory() as tmp:
        uri = f"sqlite:///{Path(tmp) / 'coral_chain.db'}"
        config = Config(str(_ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", uri)
        config.set_main_option("script_location", str(_MIGRATIONS_DIR))

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # 1. Upgrade to head
            command.upgrade(config, "head")

            engine = sa.create_engine(uri)
            try:
                # 2. Check compare_metadata has zero drift against CoralBase.metadata
                with engine.connect() as conn:
                    mc = MigrationContext.configure(
                        conn, opts={"version_table": "coral_alembic_version"}
                    )
                    diff = compare_metadata(mc, CoralBase.metadata)
                    assert diff == [], (
                        f"Alembic schema drift detected against CoralBase.metadata: {diff}"
                    )

                # 3. Downgrade to base
                command.downgrade(config, "coral_0000_base")

                with engine.connect() as conn:
                    inspector = sa.inspect(conn)
                    data_tables = [
                        t
                        for t in inspector.get_table_names()
                        if t.startswith("coral_") and t != "coral_alembic_version"
                    ]
                    assert data_tables == [], (
                        f"Data tables remained after downgrade to coral_0000_base: {data_tables}"
                    )

                # 4. Re-upgrade to head
                command.upgrade(config, "head")

                with engine.connect() as conn:
                    mc = MigrationContext.configure(
                        conn, opts={"version_table": "coral_alembic_version"}
                    )
                    diff_after = compare_metadata(mc, CoralBase.metadata)
                    assert diff_after == [], (
                        f"Alembic schema drift detected after re-upgrade: {diff_after}"
                    )

                    # Ensure every model table exists
                    inspector = sa.inspect(conn)
                    tables = set(inspector.get_table_names())
                    for expected_table in CoralBase.metadata.tables:
                        assert expected_table in tables, f"Expected table {expected_table} missing"
            finally:
                engine.dispose()


def test_coral_migration_chain_revisions_and_lineage() -> None:
    """Validate Coral migration chain has single head, lineage, and coral_ prefixes."""
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert heads == ["coral_0002_session_facade"]

    rev_sessions = script.get_revision("coral_0002_session_facade")
    assert rev_sessions is not None
    assert rev_sessions.down_revision == "coral_0001_core"
    assert len(rev_sessions.revision) <= 32

    rev_core = script.get_revision("coral_0001_core")
    assert rev_core is not None
    assert rev_core.down_revision == "coral_0000_base"
    assert len(rev_core.revision) <= 32
    assert rev_core.revision.startswith("coral_")

    rev_base = script.get_revision("coral_0000_base")
    assert rev_base is not None
    assert rev_base.down_revision is None
    assert len(rev_base.revision) <= 32
    assert rev_base.revision.startswith("coral_")


def test_migrated_check_constraints_match_the_models_on_sqlite() -> None:
    """compare_metadata skips CHECK constraints, so compare their names and SQL directly."""
    with tempfile.TemporaryDirectory() as tmp:
        uri = f"sqlite:///{Path(tmp) / 'coral_checks.db'}"
        config = Config(str(_ALEMBIC_INI))
        config.set_main_option("sqlalchemy.url", uri)
        config.set_main_option("script_location", str(_MIGRATIONS_DIR))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            command.upgrade(config, "head")

        engine = sa.create_engine(uri)
        try:
            inspector = sa.inspect(engine)
            for table in CoralBase.metadata.sorted_tables:
                expected = {
                    constraint.name: str(constraint.sqltext)
                    for constraint in table.constraints
                    if isinstance(constraint, sa.CheckConstraint)
                }
                migrated = {
                    check["name"]: check["sqltext"]
                    for check in inspector.get_check_constraints(table.name)
                }
                assert migrated == expected, table.name
        finally:
            engine.dispose()
