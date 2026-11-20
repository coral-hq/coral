"""Unit and conformance tests for effect backoff, executor registry, and conformance harness."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError, NoResultFound, OperationalError

from coral.queue import (
    EffectCompleted,
    EffectFailed,
    ExecutionContext,
    StartupLeaseLost,
    clear_executors,
    compute_effect_backoff,
    get_executor,
    register_executor,
    registered_executor_kinds,
    run_executor_conformance,
    unregister_executor,
)
from coral.queue.run_effects import describe_exception

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_compute_effect_backoff_bounds_and_exhaustion() -> None:
    """Verify exponential growth, jitter bounds [0.5x, 1.5x], cap at 300s, and exhaustion at 8."""
    # Attempt 1 with u=0.5 -> jitter=1.0 -> 1s
    assert compute_effect_backoff(1, rng=lambda: 0.5) == 1
    # Attempt 2 with u=0.5 -> jitter=1.0 -> 2s
    assert compute_effect_backoff(2, rng=lambda: 0.5) == 2
    # Attempt 5 with u=0.5 -> 16s
    assert compute_effect_backoff(5, rng=lambda: 0.5) == 16
    # Attempt 7 with u=1.0 -> raw=64 * 1.5 = 96s
    assert compute_effect_backoff(7, rng=lambda: 1.0) == 96
    # Capped at max_s=300 even with max jitter
    assert compute_effect_backoff(7, base_s=100.0, max_s=300.0, rng=lambda: 1.0) == 300
    # Attempt >= 8 returns None (terminal exhaustion)
    assert compute_effect_backoff(8) is None
    assert compute_effect_backoff(9) is None


def test_executor_registry_rejects_duplicate_registration() -> None:
    """Verify register_executor, duplicate rejection, and clear_executors."""
    clear_executors()
    try:

        async def _dummy(ctx: ExecutionContext) -> EffectCompleted:
            return EffectCompleted(result={"work_id": ctx.work.id})

        register_executor("git.prepare", _dummy)
        assert get_executor("git.prepare") is _dummy
        assert "git.prepare" in registered_executor_kinds()

        with pytest.raises(ValueError, match="already registered"):
            register_executor("git.prepare", _dummy)

        with pytest.raises(ValueError, match="non-empty"):
            register_executor("", _dummy)
    finally:
        clear_executors()


def test_unregister_executor_removes_only_the_function_it_names() -> None:
    clear_executors()
    try:

        async def _first(ctx: ExecutionContext) -> EffectCompleted:
            return EffectCompleted()

        async def _replacement(ctx: ExecutionContext) -> EffectCompleted:
            return EffectCompleted()

        register_executor("workspace.commit", _first)
        register_executor("workspace.commit", _replacement, replace=True)

        # A stale owner cannot remove the executor that replaced its own.
        assert unregister_executor("workspace.commit", _first) is False
        assert get_executor("workspace.commit") is _replacement

        assert unregister_executor("workspace.commit", _replacement) is True
        assert get_executor("workspace.commit") is None
        assert "workspace.commit" not in registered_executor_kinds()
        # Repeat-safe: a second exit finds nothing to remove.
        assert unregister_executor("workspace.commit", _replacement) is False
    finally:
        clear_executors()


async def test_run_executor_conformance_passes_for_compliant_executors() -> None:
    """Verify run_executor_conformance validates idempotent and lease-fenced executors."""

    async def _compliant_success(ctx: ExecutionContext) -> EffectCompleted:
        await ctx.ensure_lease()
        return EffectCompleted(result={"run_id": ctx.run_id, "ok": True})

    async def _compliant_failure(ctx: ExecutionContext) -> EffectFailed:
        await ctx.ensure_lease()
        return EffectFailed(error_code="perm.invalid_repo", message="bad repo", retryable=False)

    await run_executor_conformance(_compliant_success, effect_type="test.success")
    await run_executor_conformance(_compliant_failure, effect_type="test.failure")
    assert StartupLeaseLost is not None


def test_coral_queue_imports_without_pytest() -> None:
    blocked = "import sys; sys.modules['pytest'] = sys.modules['_pytest'] = None; "
    for module in ("coral.queue", "coral.workers"):
        completed = subprocess.run(
            [sys.executable, "-c", f"{blocked}import {module}"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr


class _DriverError(Exception):
    """A driver error carrying a SQLSTATE, as psycopg's errors do."""

    sqlstate = "23505"


class _LegacyDriverError(Exception):
    """A driver error carrying its SQLSTATE as ``pgcode``, as psycopg2's errors do."""

    pgcode = "40001"


def test_describe_exception_names_database_errors_without_their_text() -> None:
    sentinel = "SENTINEL-bound-parameter"
    unique = IntegrityError(
        "INSERT INTO coral_work (payload) VALUES (%(payload)s)",
        {"payload": sentinel},
        _DriverError(f"duplicate key value: Key (payload)=({sentinel})"),
    )
    serialization = OperationalError("SELECT 1", (sentinel,), _LegacyDriverError(sentinel))
    mysql = IntegrityError("INSERT", (sentinel,), Exception(1062, f"Duplicate entry '{sentinel}'"))
    sqlite_error = IntegrityError("INSERT", (sentinel,), sqlite3.IntegrityError(sentinel))
    assert all(sentinel in str(exc) for exc in (unique, serialization, mysql, sqlite_error))

    assert describe_exception(unique) == "IntegrityError (orig _DriverError, code 23505)"
    assert describe_exception(serialization) == (
        "OperationalError (orig _LegacyDriverError, code 40001)"
    )
    assert describe_exception(mysql) == "IntegrityError (orig Exception, code 1062)"
    assert describe_exception(sqlite_error) == "IntegrityError (orig IntegrityError)"
    # A driver error that escaped SQLAlchemy, and SQLAlchemy's own errors, keep only their type.
    assert describe_exception(_DriverError(sentinel)) == "_DriverError (code 23505)"
    assert describe_exception(NoResultFound(sentinel)) == "NoResultFound"
    # Text that quotes a statement error is cut where the driver's text starts.
    assert describe_exception(RuntimeError(f"commit failed: {unique}")) == (
        "RuntimeError: commit failed:"
    )


def test_describe_exception_keeps_no_validation_input_or_control_characters() -> None:
    class Handoff(BaseModel):
        seq: int

    try:
        Handoff.model_validate({"seq": "SENTINEL handoff body"})
    except ValidationError as exc:
        assert "SENTINEL" in str(exc)
        assert describe_exception(exc) == "ValidationError (1 error: seq int_parsing)"
    assert describe_exception(ValueError("one\nforged line \x1b[31m")) == (
        "ValueError: one forged line  [31m"
    )


class _Unprintable(Exception):
    def __str__(self) -> str:
        raise ValueError("no text")


def test_describe_exception_keeps_other_errors_text_within_bounds() -> None:
    assert describe_exception(ValueError("bad value")) == "ValueError: bad value"
    assert describe_exception(_Unprintable()) == "_Unprintable"
    assert describe_exception(TimeoutError()) == "TimeoutError"
    described = describe_exception(RuntimeError("x" * 5000))
    assert len(described) == 2000
    assert described.startswith("RuntimeError: xxx") and described.endswith("…")
