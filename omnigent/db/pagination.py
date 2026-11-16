"""Keyset pagination utilities for SQLAlchemy queries."""

from __future__ import annotations

from operator import ge, gt, le, lt
from typing import Any

from sqlalchemy import and_, or_, tuple_
from sqlalchemy.sql.elements import ColumnElement

__all__ = ["keyset_after"]


# CORAL(S58): shared keyset pagination helper extracted from scheduled_task_store
def keyset_after(
    columns: tuple[Any, ...],
    cursor: tuple[Any, ...],
    *,
    inclusive: bool = False,
    descending: bool = False,
    dialect_name: str | None = None,
) -> ColumnElement[bool]:
    """
    Build a SQLAlchemy WHERE clause that seeks past a composite cursor.

    On MySQL, row-value comparisons ``(c1, c2) > (v1, v2)`` prevent index range
    scans; we expand lexicographically into scalar ranges. On other dialects,
    SQLAlchemy's ``tuple_`` construct generates standard composite tuple comparisons.
    For single-column cursors, scalar comparison is used on all dialects.

    :param columns: Tuple of SQLAlchemy column expressions.
    :param cursor: Tuple of cursor values corresponding to *columns*.
    :param inclusive: If ``True``, include the boundary point (>= or <= on last column).
    :param descending: If ``True``, order is descending (< or <=), otherwise ascending.
    :param dialect_name: SQLAlchemy engine dialect name (e.g. ``"mysql"``).
    :returns: A :class:`ColumnElement[bool]` filter expression.
    :raises ValueError: If *columns* is empty or if *columns* and *cursor* have different lengths.
    """
    if not columns:
        raise ValueError("keyset pagination requires at least one column")
    if len(columns) != len(cursor):
        raise ValueError(f"columns and cursor length mismatch: {len(columns)} != {len(cursor)}")

    compare = lt if descending else gt
    compare_inclusive = le if descending else ge

    if len(columns) == 1:
        return (compare_inclusive if inclusive else compare)(columns[0], cursor[0])

    if dialect_name != "mysql":
        return (compare_inclusive if inclusive else compare)(tuple_(*columns), cursor)

    return or_(
        *(
            and_(
                *(columns[previous] == cursor[previous] for previous in range(index)),
                (compare_inclusive if inclusive and index == len(columns) - 1 else compare)(
                    column, cursor[index]
                ),
            )
            for index, column in enumerate(columns)
        )
    )
