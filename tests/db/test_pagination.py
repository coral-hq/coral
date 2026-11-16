"""Tests for keyset pagination helper (omnigent.db.pagination)."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.dialects import mysql, postgresql, sqlite

from omnigent.db.pagination import keyset_after

_metadata = MetaData()
_sample_table = Table(
    "pagination_test",
    _metadata,
    Column("id", Integer, primary_key=True),
    Column("score", Integer),
    Column("name", String),
)


def _compile(expr, dialect) -> str:
    return str(expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def test_keyset_after_validation() -> None:
    """keyset_after fails loud when columns is empty or lengths mismatch."""
    with pytest.raises(ValueError, match="at least one column"):
        keyset_after((), ())

    with pytest.raises(ValueError, match="mismatch"):
        keyset_after((_sample_table.c.id,), (1, 2))

    with pytest.raises(ValueError, match="mismatch"):
        keyset_after((_sample_table.c.id, _sample_table.c.score), (1,))


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect(), mysql.dialect()])
def test_keyset_after_single_column_dialects(dialect) -> None:
    """Single column cursor produces scalar comparison across all dialects."""
    # Ascending, exclusive
    expr_asc = keyset_after((_sample_table.c.score,), (10,))
    sql = _compile(expr_asc, dialect)
    assert sql == "pagination_test.score > 10"

    # Ascending, inclusive
    expr_asc_inc = keyset_after((_sample_table.c.score,), (10,), inclusive=True)
    sql = _compile(expr_asc_inc, dialect)
    assert sql == "pagination_test.score >= 10"

    # Descending, exclusive
    expr_desc = keyset_after((_sample_table.c.score,), (10,), descending=True)
    sql = _compile(expr_desc, dialect)
    assert sql == "pagination_test.score < 10"

    # Descending, inclusive
    expr_desc_inc = keyset_after((_sample_table.c.score,), (10,), descending=True, inclusive=True)
    sql = _compile(expr_desc_inc, dialect)
    assert sql == "pagination_test.score <= 10"


def test_keyset_after_multi_column_non_mysql() -> None:
    """Multi-column cursor on non-MySQL produces tuple comparisons."""
    cols = (_sample_table.c.score, _sample_table.c.name)
    cursor = (100, "alice")

    # Ascending, exclusive
    expr_asc = keyset_after(cols, cursor, dialect_name="postgresql")
    expected = "(pagination_test.score, pagination_test.name) > (100, 'alice')"
    assert _compile(expr_asc, postgresql.dialect()) == expected

    # Ascending, inclusive
    expr_asc_inc = keyset_after(cols, cursor, inclusive=True, dialect_name="sqlite")
    expected_inc = "(pagination_test.score, pagination_test.name) >= (100, 'alice')"
    assert _compile(expr_asc_inc, sqlite.dialect()) == expected_inc

    # Descending, exclusive
    expr_desc = keyset_after(cols, cursor, descending=True, dialect_name=None)
    expected_desc = "(pagination_test.score, pagination_test.name) < (100, 'alice')"
    assert _compile(expr_desc, postgresql.dialect()) == expected_desc

    # Descending, inclusive
    expr_desc_inc = keyset_after(
        cols, cursor, descending=True, inclusive=True, dialect_name="postgresql"
    )
    expected_desc_inc = "(pagination_test.score, pagination_test.name) <= (100, 'alice')"
    assert _compile(expr_desc_inc, postgresql.dialect()) == expected_desc_inc


def test_keyset_after_multi_column_mysql() -> None:
    """Multi-column cursor on MySQL produces scalar lexicographic expansion."""
    cols = (_sample_table.c.score, _sample_table.c.name)
    cursor = (100, "alice")
    d = mysql.dialect()

    # Ascending, exclusive
    expr_asc = keyset_after(cols, cursor, dialect_name="mysql")
    sql_asc = _compile(expr_asc, d)
    expected_asc = (
        "pagination_test.score > 100 OR "
        "pagination_test.score = 100 AND pagination_test.name > 'alice'"
    )
    assert sql_asc == expected_asc

    # Ascending, inclusive (inclusive only on final column)
    expr_asc_inc = keyset_after(cols, cursor, inclusive=True, dialect_name="mysql")
    sql_asc_inc = _compile(expr_asc_inc, d)
    expected_asc_inc = (
        "pagination_test.score > 100 OR "
        "pagination_test.score = 100 AND pagination_test.name >= 'alice'"
    )
    assert sql_asc_inc == expected_asc_inc

    # Descending, exclusive
    expr_desc = keyset_after(cols, cursor, descending=True, dialect_name="mysql")
    sql_desc = _compile(expr_desc, d)
    expected_desc = (
        "pagination_test.score < 100 OR "
        "pagination_test.score = 100 AND pagination_test.name < 'alice'"
    )
    assert sql_desc == expected_desc

    # Descending, inclusive
    expr_desc_inc = keyset_after(
        cols, cursor, descending=True, inclusive=True, dialect_name="mysql"
    )
    sql_desc_inc = _compile(expr_desc_inc, d)
    expected_desc_inc = (
        "pagination_test.score < 100 OR "
        "pagination_test.score = 100 AND pagination_test.name <= 'alice'"
    )
    assert sql_desc_inc == expected_desc_inc


def test_keyset_after_three_columns_mysql() -> None:
    """Three-column expansion on MySQL correctly chains equality prefixes."""
    cols = (_sample_table.c.id, _sample_table.c.score, _sample_table.c.name)
    cursor = (1, 50, "bob")
    d = mysql.dialect()

    expr = keyset_after(cols, cursor, dialect_name="mysql")
    sql = _compile(expr, d)
    expected = (
        "pagination_test.id > 1 OR "
        "pagination_test.id = 1 AND pagination_test.score > 50 OR "
        "pagination_test.id = 1 AND pagination_test.score = 50 AND pagination_test.name > 'bob'"
    )
    assert sql == expected


def test_keyset_after_sqlite_execution() -> None:
    """Verify keyset pagination filters rows accurately when executed in SQLite."""
    engine = create_engine("sqlite:///:memory:")
    _metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            _sample_table.insert(),
            [
                {"id": 1, "score": 10, "name": "a"},
                {"id": 2, "score": 10, "name": "b"},
                {"id": 3, "score": 20, "name": "a"},
                {"id": 4, "score": 20, "name": "b"},
                {"id": 5, "score": 30, "name": "a"},
            ],
        )

    cols = (_sample_table.c.score, _sample_table.c.name)

    # After (10, 'b'), ascending, exclusive -> (20, 'a'), (20, 'b'), (30, 'a')
    with engine.connect() as conn:
        stmt = (
            select(_sample_table.c.id)
            .where(keyset_after(cols, (10, "b")))
            .order_by(_sample_table.c.score.asc(), _sample_table.c.name.asc())
        )
        assert conn.scalars(stmt).all() == [3, 4, 5]

        # After (10, 'b'), ascending, inclusive -> (10, 'b'), (20, 'a'), (20, 'b'), (30, 'a')
        stmt_inc = (
            select(_sample_table.c.id)
            .where(keyset_after(cols, (10, "b"), inclusive=True))
            .order_by(_sample_table.c.score.asc(), _sample_table.c.name.asc())
        )
        assert conn.scalars(stmt_inc).all() == [2, 3, 4, 5]

        # Before (20, 'a'), descending, exclusive -> (10, 'b'), (10, 'a')
        stmt_desc = (
            select(_sample_table.c.id)
            .where(keyset_after(cols, (20, "a"), descending=True))
            .order_by(_sample_table.c.score.desc(), _sample_table.c.name.desc())
        )
        assert conn.scalars(stmt_desc).all() == [2, 1]

        # Before (20, 'a'), descending, inclusive -> (20, 'a'), (10, 'b'), (10, 'a')
        stmt_desc_inc = (
            select(_sample_table.c.id)
            .where(keyset_after(cols, (20, "a"), descending=True, inclusive=True))
            .order_by(_sample_table.c.score.desc(), _sample_table.c.name.desc())
        )
        assert conn.scalars(stmt_desc_inc).all() == [3, 2, 1]
