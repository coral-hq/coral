"""coral_0006 on every DB lane: profile tables matching the models, and a clean downgrade."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from coral.db import ProfileRevisionRow, RunProfilePinRow
from tests.db.coral._migration_support import coral_revision, migrate_coral, reflected_schema

_ALERTS_AND_GATES = "coral_0005_alerts_and_gates"
_PROFILES = "coral_0006_profiles"
_TABLES = (ProfileRevisionRow.__table__, RunProfilePinRow.__table__)


def _assert_matches_models(engine: Engine) -> None:
    """The lane's profile tables have the models' columns, keys, indexes and unique keys."""
    inspector = sa.inspect(engine)
    for table in _TABLES:
        columns = {
            column["name"]: column["nullable"] for column in inspector.get_columns(table.name)
        }
        assert columns == {column.name: column.nullable for column in table.columns}, table.name
        primary_key = inspector.get_pk_constraint(table.name)["constrained_columns"]
        assert primary_key == [column.name for column in table.primary_key.columns], table.name
        indexes = {
            index["name"]: index["column_names"] for index in inspector.get_indexes(table.name)
        }
        for index in table.indexes:
            assert indexes.get(index.name) == [column.name for column in index.columns], index.name
        uniques = {
            tuple(unique["column_names"])
            for unique in inspector.get_unique_constraints(table.name)
        } | {
            tuple(index["column_names"])
            for index in inspector.get_indexes(table.name)
            if index["unique"]
        }
        for constraint in table.constraints:
            if isinstance(constraint, sa.UniqueConstraint):
                assert tuple(column.name for column in constraint.columns) in uniques, table.name


def test_upgrade_matches_the_models_and_downgrade_restores_coral_0005(
    coral_scratch_engine: Engine,
) -> None:
    engine = coral_scratch_engine
    migrate_coral(engine, "upgrade", _ALERTS_AND_GATES)
    before = reflected_schema(engine)

    migrate_coral(engine, "upgrade", _PROFILES)
    assert coral_revision(engine) == _PROFILES
    _assert_matches_models(engine)
    upgraded = reflected_schema(engine)

    migrate_coral(engine, "downgrade", _ALERTS_AND_GATES)
    assert coral_revision(engine) == _ALERTS_AND_GATES
    assert reflected_schema(engine) == before

    migrate_coral(engine, "upgrade", _PROFILES)
    assert reflected_schema(engine) == upgraded
