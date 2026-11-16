"""Coral DB-lane fixture and fault-primitive contracts, on every DB lane."""

from __future__ import annotations

from sqlalchemy import func, inspect, select

from coral.db.models_workflows import WorkflowRow
from omnigent.db.utils import get_or_create_engine
from tests.stores.coral._schema import ProbeRow


def test_coral_db_uri_has_coral_and_probe_tables_and_no_rows(coral_db_uri: str) -> None:
    engine = get_or_create_engine(coral_db_uri)

    tables = set(inspect(engine).get_table_names())

    assert {"agents", "coral_workflows", "coraltest_probe"} <= tables
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(WorkflowRow)) == 0
        assert connection.scalar(select(func.count()).select_from(ProbeRow)) == 0
