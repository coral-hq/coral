"""Fault and contention mechanics for Coral DB-lane tests; callers pick inputs and assert."""

from __future__ import annotations

import contextlib
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest
from sqlalchemy import Engine, event

from omnigent.db.utils import (
    _engine_cache,
    _engine_lock,
    get_or_create_engine,
    normalize_database_url,
)


class SimulatedCrash(BaseException):
    """Stands in for process death.

    A BaseException, so ``except Exception`` cleanup in the code under test cannot absorb it.
    """


def crash_around(
    monkeypatch: pytest.MonkeyPatch,
    owner: object,
    attr: str,
    *,
    when: Literal["before", "after"],
) -> None:
    """Make ``owner.attr`` raise SimulatedCrash before or after the real call runs."""
    original = getattr(owner, attr)

    def crashing(*args: Any, **kwargs: Any) -> Any:
        if when == "before":
            raise SimulatedCrash(f"crash before {attr}")
        original(*args, **kwargs)
        raise SimulatedCrash(f"crash after {attr}")

    monkeypatch.setattr(owner, attr, crashing)


def evict_cached_engine(uri: str) -> None:
    """Drop and dispose the process-wide cached engine for ``uri``, if any."""
    with _engine_lock:
        engine = _engine_cache.pop(normalize_database_url(uri), None)
    if engine is not None:
        engine.dispose()


def fresh_process(uri: str, *, connect: Callable[[str], Engine] = get_or_create_engine) -> Engine:
    """Evict the cached engine for ``uri`` and return a new one from ``connect``.

    Only committed state is visible through the new engine. Pass
    ``get_or_create_conversation_engine`` for a split conversation DB, which
    must not receive Omnigent migrations.
    """
    evict_cached_engine(uri)
    return connect(uri)


@dataclass(frozen=True)
class RaceOutcome:
    value: object | None
    error: BaseException | None


def run_racing(count: int, operation: Callable[[int], object]) -> list[RaceOutcome]:
    """Run ``operation(index)`` on ``count`` threads released together; outcomes in index order."""
    barrier = threading.Barrier(count)
    outcomes: list[RaceOutcome | None] = [None] * count

    def run(index: int) -> None:
        barrier.wait()
        try:
            outcomes[index] = RaceOutcome(value=operation(index), error=None)
        except BaseException as error:
            outcomes[index] = RaceOutcome(value=None, error=error)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return [outcome for outcome in outcomes if outcome is not None]


_BUSY_TIMEOUT_PRAGMA = re.compile(r"PRAGMA\s+busy_timeout\s*=\s*\d+", re.IGNORECASE)


@contextlib.contextmanager
def short_sqlite_busy(engine: Engine, milliseconds: int) -> Iterator[None]:
    """Rewrite the managed session's busy_timeout PRAGMA on ``engine`` to ``milliseconds``."""
    replacement = f"PRAGMA busy_timeout = {milliseconds}"

    def rewrite(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> tuple[str, object]:
        return _BUSY_TIMEOUT_PRAGMA.sub(replacement, statement), parameters

    event.listen(engine, "before_cursor_execute", rewrite, retval=True)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", rewrite)


@contextlib.contextmanager
def hold_sqlite_write_lock(database_path: Path) -> Iterator[None]:
    """Hold the SQLite write lock on ``database_path`` from a separate connection until exit."""
    connection = sqlite3.connect(database_path, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        yield
        connection.execute("ROLLBACK")
    finally:
        connection.close()
