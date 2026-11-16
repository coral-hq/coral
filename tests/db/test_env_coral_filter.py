"""Tests for Alembic env filter (S30) and DB revision helpers (S58)."""

from __future__ import annotations

import sys
import tempfile
from unittest.mock import MagicMock

import pytest
from alembic import context
from sqlalchemy import inspect

from omnigent.db.utils import create_db_engine, get_db_revision_state, get_or_create_engine


def test_env_include_name_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """_include_name in env.py excludes Coral tables while keeping Omnigent tables."""
    # Ensure sys.modules does not retain mock-loaded env.py before or after the test
    monkeypatch.delitem(sys.modules, "omnigent.db.migrations.env", raising=False)

    mock_proxy = MagicMock()
    mock_proxy.is_offline_mode.return_value = True
    mock_proxy.begin_transaction.return_value.__enter__ = MagicMock()
    mock_proxy.begin_transaction.return_value.__exit__ = MagicMock()
    monkeypatch.setattr(context, "_proxy", mock_proxy, raising=False)

    mock_config = MagicMock()
    mock_config.config_file_name = None
    mock_config.attributes = {}
    monkeypatch.setattr(context, "config", mock_config, raising=False)

    try:
        import omnigent.db.migrations.env as env

        # Excluded: Coral tables and coral_alembic_version
        assert not env._include_name("coral_workflows", "table", None)
        assert not env._include_name("coral_tasks", "table", None)
        assert not env._include_name("coral_alembic_version", "table", None)

        # Included: Omnigent core tables and alembic_version
        assert env._include_name("agents", "table", None)
        assert env._include_name("conversations", "table", None)
        assert env._include_name("scheduled_tasks", "table", None)
        assert env._include_name("alembic_version", "table", None)

        # Included: Non-table types (indexes, columns, foreign keys) even if prefixed
        assert env._include_name("coral_workflow_id", "column", None)
        assert env._include_name("idx_coral_runs", "index", None)
        assert env._include_name(None, "table", None)

        # Verify context.configure received include_name=_include_name
        mock_proxy.configure.assert_called()
        call_kwargs = mock_proxy.configure.call_args.kwargs
        assert call_kwargs.get("include_name") is env._include_name
    finally:
        sys.modules.pop("omnigent.db.migrations.env", None)


def test_create_db_engine_and_revision_state() -> None:
    """create_db_engine creates an unmigrated engine; get_db_revision_state inspects revisions."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        db_path = f.name
    uri = f"sqlite:///{db_path}"

    # create_db_engine does NOT automatically run migrations
    engine = create_db_engine(uri)
    try:
        tables = inspect(engine).get_table_names()
        assert "alembic_version" not in tables
        current, head = get_db_revision_state(engine, uri)
        assert current is None
        assert head is not None and isinstance(head, str)
    finally:
        engine.dispose()

    # get_or_create_engine runs migrations to head
    migrated_engine = get_or_create_engine(uri)
    try:
        tables = inspect(migrated_engine).get_table_names()
        assert "alembic_version" in tables
        current, head = get_db_revision_state(migrated_engine, uri)
        assert current == head
    finally:
        migrated_engine.dispose()
