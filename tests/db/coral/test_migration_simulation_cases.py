"""coral_0007 on every DB lane: saved cases matching the model, and a clean downgrade."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from coral.db import SimulationCaseRow
from tests.db.coral._migration_support import (
    coral_revision,
    insert_row,
    migrate_coral,
    reflected_schema,
)

_PROFILES = "coral_0006_profiles"
_CASES = "coral_0007_simulation_cases"
_TABLE = SimulationCaseRow.__table__


def _case(case_id: str, name: str) -> dict[str, object]:
    return {
        "workspace_id": 1,
        "id": case_id,
        "workflow_id": "w" * 32,
        "name": name,
        "script": "{}",
        "created_at": 1,
    }


def test_upgrade_matches_the_model_and_downgrade_restores_coral_0006(
    coral_scratch_engine: Engine,
) -> None:
    engine = coral_scratch_engine
    migrate_coral(engine, "upgrade", _PROFILES)
    before = reflected_schema(engine)

    migrate_coral(engine, "upgrade", _CASES)
    assert coral_revision(engine) == _CASES
    inspector = sa.inspect(engine)
    columns = {column["name"]: column["nullable"] for column in inspector.get_columns(_TABLE.name)}
    assert columns == {column.name: column.nullable for column in _TABLE.columns}
    indexes = {
        index["name"]: (index["column_names"], bool(index["unique"]))
        for index in inspector.get_indexes(_TABLE.name)
    }
    for index in _TABLE.indexes:
        assert indexes.get(index.name) == (
            [column.name for column in index.columns],
            bool(index.unique),
        ), index.name
    upgraded = reflected_schema(engine)

    migrate_coral(engine, "downgrade", _PROFILES)
    assert coral_revision(engine) == _PROFILES
    assert reflected_schema(engine) == before

    migrate_coral(engine, "upgrade", _CASES)
    assert reflected_schema(engine) == upgraded


def test_names_are_unique_per_workflow_and_case_sensitive(coral_scratch_engine: Engine) -> None:
    engine = coral_scratch_engine
    migrate_coral(engine, "upgrade", _CASES)
    insert_row(engine, _TABLE, _case("a" * 32, "happy path"))
    insert_row(engine, _TABLE, _case("b" * 32, "Happy path"))
    with pytest.raises(sa.exc.IntegrityError):
        insert_row(engine, _TABLE, _case("c" * 32, "happy path"))


def _rows(engine: Engine) -> list[tuple[object, ...]]:
    table = sa.Table(_TABLE.name, sa.MetaData(), autoload_with=engine)
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(sa.select(table.c.id, table.c.name))]


def test_existing_cases_survive_the_upgrade_and_the_downgrade(
    coral_scratch_engine: Engine,
) -> None:
    engine = coral_scratch_engine
    migrate_coral(engine, "upgrade", _PROFILES)
    insert_row(engine, _TABLE, _case("a" * 32, "happy path"))

    migrate_coral(engine, "upgrade", _CASES)
    assert _rows(engine) == [("a" * 32, "happy path")]
    with engine.connect() as conn:
        assert conn.execute(sa.select(_TABLE.c.last_mismatches)).scalar_one() is None

    migrate_coral(engine, "downgrade", _PROFILES)
    assert _rows(engine) == [("a" * 32, "happy path")]
