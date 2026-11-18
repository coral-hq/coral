"""Steps every engine effect executor shares: its payload, its run and the run's scopes.

The drainer enters scopes from the payload's ``user_id`` and
``account_generation``, which the engine does not vouch for. So an executor
loads its run, refuses a payload identity that differs from the run row or an
effect key of another run, and runs its body inside scopes built from the run
row (:func:`run_scope`); :func:`run_effect` chains these steps. Payload fields
an executor echoes into its result are bounded here, so an oversized value
fails before any side effect.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError, StatementError

from coral.db.enum_codecs import RunStatus
from coral.omni.protocols import CoralSessionError, RunScopeRunner
from coral.queue.executors import EffectCompleted, EffectFailed, EffectOutcome, ExecutionContext
from coral.slots.results import ResultTooLarge, bound_result, stored_text_bytes
from coral.stores.protocols import RunNotFound, RunState, RunStore

# Payload fields the drainer builds scopes from; the run row must agree with them.
_IDENTITY_FIELDS = ("user_id", "account_generation")
MAX_EFFECT_KEY_CHARS = 512
MAX_FAILURE_MESSAGE_CHARS = 2000
# The work row's error-code column.
MAX_ERROR_CODE_CHARS = 64
MAX_INVALID_PAYLOAD_MESSAGE_CHARS = 500
# Session ids are derived ids, and the bindings table keeps 64 characters.
_SESSION_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
# C0, DEL and C1 control characters, which could drive a terminal; shared by the executors.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class EffectRefused(Exception):
    """An effect fails with a typed code; ``retryable`` says whether a later try may succeed."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        message = trim_message(message, MAX_FAILURE_MESSAGE_CHARS)
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable

    def outcome(self) -> EffectFailed:
        return EffectFailed(error_code=self.code, message=self.message, retryable=self.retryable)


def trim_message(message: str, limit: int) -> str:
    """``message`` cut to its last ``limit`` characters, where host errors keep their cause."""
    if len(message) <= limit:
        return message
    return "…" + message[-(limit - 1) :]


# Database drivers whose errors quote values (key values, MySQL's duplicate entry).
_DRIVER_MODULES = frozenset({"asyncpg", "MySQLdb", "psycopg", "psycopg2", "pymysql", "sqlite3"})
# Where quoted statement-error text starts: SQLAlchemy's ``(<module>.<Class>) `` prefix, the SQL
# and the parameters.
_QUOTED_DATABASE_TEXT = re.compile(r"\((?:[A-Za-z_]\w*\.)+[A-Za-z_]\w*\) |\[SQL: |\[parameters: ")


def _driver_code(error: BaseException) -> str | None:
    """A driver error's SQLSTATE (psycopg, psycopg2), SQLite error name or MySQL error number."""
    for name in ("sqlstate", "pgcode", "sqlite_errorname"):
        value = getattr(error, name, None)
        if isinstance(value, str) and value:
            return value
    number = error.args[0] if error.args else None
    return str(number) if type(number) is int else None


def _is_driver_error(error: BaseException) -> bool:
    if hasattr(error, "sqlstate") or hasattr(error, "pgcode"):
        return True
    return type(error).__module__.partition(".")[0] in _DRIVER_MODULES


def _validation_summary(exc: ValidationError) -> str:
    """Where and how validation failed; pydantic's own text repeats the input."""
    errors = exc.errors(include_input=False, include_url=False)
    places = "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or '<root>'} {error['type']}"
        for error in errors[:10]
    )
    return f"{len(errors)} errors: {places}" if len(errors) != 1 else f"1 error: {places}"


def describe_exception(exc: BaseException) -> str:
    """
    ``exc`` described for logs and stored messages, in at most
    :data:`MAX_FAILURE_MESSAGE_CHARS` characters, without control characters.

    SQLAlchemy puts a statement's bound parameters (payloads, briefs, handoff
    bodies) into ``str()``, drivers quote key values and pydantic repeats its
    input, so a database error is named by its type, its driver error's class
    and its code, and a validation error by its error locations. Other errors
    keep their text, cut where quoted database text starts. Never raises.
    """
    name = type(exc).__name__
    if isinstance(exc, StatementError):
        if exc.orig is None:
            return name
        code = _driver_code(exc.orig)
        detail = f"orig {type(exc.orig).__name__}" + (f", code {code}" if code else "")
        described = f"{name} ({detail})"
    elif isinstance(exc, SQLAlchemyError):
        described = name
    elif _is_driver_error(exc):
        code = _driver_code(exc)
        described = f"{name} (code {code})" if code else name
    elif isinstance(exc, ValidationError):
        described = f"{name} ({_validation_summary(exc)})"
    else:
        try:
            text = str(exc)
        except Exception:  # noqa: BLE001 -- an unprintable error is named by its type
            text = ""
        quoted = _QUOTED_DATABASE_TEXT.search(text)
        if quoted is not None:
            text = text[: quoted.start()].rstrip()
        described = f"{name}: {text}" if text else name
    described = CONTROL_CHARACTERS.sub(" ", described)
    if len(described) <= MAX_FAILURE_MESSAGE_CHARS:
        return described
    return described[: MAX_FAILURE_MESSAGE_CHARS - 1] + "…"


def raise_if_cancelling(exc: BaseException) -> None:
    """
    Re-raise ``exc`` when it is the running task's own cancellation.

    A ``CancelledError`` caught while the task is not being cancelled came from
    awaiting something another task cancelled; callers handle it as a failure.
    """
    if isinstance(exc, asyncio.CancelledError):
        task = asyncio.current_task()
        if task is None or task.cancelling():
            raise exc


def invalid_payload(message: str) -> EffectRefused:
    """The permanent ``effect.invalid_payload`` failure; callers name fields, never values."""
    return EffectRefused(
        "effect.invalid_payload", trim_message(message, MAX_INVALID_PAYLOAD_MESSAGE_CHARS)
    )


def effect_payload(ctx: ExecutionContext) -> dict[str, Any]:
    """
    The claimed work item's payload.

    :raises EffectRefused: ``effect.invalid_payload`` unless it is a JSON object.
    """
    try:
        payload = json.loads(ctx.work.payload)
    except ValueError:
        raise invalid_payload("the payload is not JSON") from None
    if not isinstance(payload, dict):
        raise invalid_payload("the payload is not a JSON object")
    return payload


def run_effect_key(ctx: ExecutionContext, payload: Mapping[str, Any]) -> str:
    """
    The payload's ``effect_key``, which must be one of the claimed run's.

    Engine keys are ``<run_id>:<seq>:<kind>:<subject>``; ids derived from a key
    (op keys, session and message ids) must never reach another run's.

    :raises EffectRefused: ``effect.invalid_payload`` when it is missing, longer
        than :data:`MAX_EFFECT_KEY_CHARS` or holds a NUL (the derivation's
        separator); ``effect.identity_mismatch`` when it names another run.
    """
    key = required_text(payload, "effect_key")
    if len(key) > MAX_EFFECT_KEY_CHARS or "\0" in key:
        raise invalid_payload(
            f"effect_key must be at most {MAX_EFFECT_KEY_CHARS} characters, without NUL"
        )
    if not key.startswith(f"{ctx.run_id}:"):
        raise EffectRefused(
            "effect.identity_mismatch",
            f"the payload's effect_key is not one of run {ctx.run_id}'s",
        )
    return key


def required_text(payload: Mapping[str, Any], name: str) -> str:
    """
    A non-empty string field.

    :raises EffectRefused: ``effect.invalid_payload`` when it is missing or not one.
    """
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise invalid_payload(f"{name} must be a non-empty string")
    return value


def optional_text(payload: Mapping[str, Any], name: str) -> str | None:
    """
    A string field that may be absent or null.

    :raises EffectRefused: ``effect.invalid_payload`` when it is another type.
    """
    value = payload.get(name)
    if value is not None and not isinstance(value, str):
        raise invalid_payload(f"{name} must be a string or null")
    return value


def session_id_field(payload: Mapping[str, Any], name: str = "session_id") -> str:
    """
    A session id: 1-64 of ``a-z``, ``0-9``, ``_`` or ``-``, starting with a letter or digit.

    :raises EffectRefused: ``effect.invalid_payload`` otherwise.
    """
    value = required_text(payload, name)
    if not _SESSION_ID.fullmatch(value):
        raise invalid_payload(f"{name} must be 1-64 of a-z, 0-9, '_' or '-'")
    return value


def echoed_text(payload: Mapping[str, Any], name: str, *, max_stored_bytes: int) -> str | None:
    """
    Optional text an executor repeats in its result, bounded by its stored size.

    :raises EffectRefused: ``effect.invalid_payload`` for a control character or
        more than ``max_stored_bytes`` bytes as the queue stores it.
    """
    value = optional_text(payload, name)
    if value is not None and (
        CONTROL_CHARACTERS.search(value) or stored_text_bytes(value) > max_stored_bytes
    ):
        raise invalid_payload(
            f"{name} must be text without control characters, at most {max_stored_bytes} "
            "bytes as stored"
        )
    return value


async def load_effect_run(
    run_store: RunStore, ctx: ExecutionContext, payload: Mapping[str, Any]
) -> RunState:
    """
    Load the effect's run, whose row decides the identity the effect acts as.

    :raises EffectRefused: ``effect.run_missing`` when the run is not in the
        item's workspace; ``effect.identity_mismatch`` when the payload carries
        a ``user_id`` or ``account_generation`` the run row does not have. Both
        are permanent, and neither message repeats the payload's values.
    """
    try:
        state, _version = await asyncio.to_thread(
            run_store.load_run_state, ctx.run_id, workspace_id=ctx.workspace_id
        )
    except RunNotFound:
        raise EffectRefused(
            "effect.run_missing", f"run {ctx.run_id} is not in this workspace"
        ) from None
    for name in _IDENTITY_FIELDS:
        if name in payload and payload[name] != getattr(state.run, name):
            raise EffectRefused(
                "effect.identity_mismatch",
                f"the payload's {name} is not the one run {ctx.run_id} was started with",
            )
    return state


def refuse_paused_run(state: RunState) -> None:
    """
    Refuse a session effect while its run is paused.

    The drainer retries with backoff only up to its attempt cap (minutes), so a
    longer pause fails the effect unless the engine bridge holds it until a resume.

    :raises EffectRefused: Retryable ``run.paused``.
    """
    if state.status == int(RunStatus.PAUSED):
        raise EffectRefused("run.paused", f"run {state.run_id} is paused", retryable=True)


def run_scope(scope_runner: RunScopeRunner, state: RunState) -> AbstractAsyncContextManager[None]:
    """The run's workspace, account-authority and host-owner scopes, from its row and spec."""
    return scope_runner.run_scope(
        workspace_id=state.workspace_id,
        run_id=state.run_id,
        user_id=state.run.user_id,
        account_generation=state.run.account_generation,
        host_id=state.spec.host_id,
    )


# An executor's work inside the run's scopes, and its payload parser.
EffectBody = Callable[[RunState, Mapping[str, Any]], Awaitable[dict[str, Any]]]
PayloadParser = Callable[[Mapping[str, Any]], Mapping[str, Any]]


async def run_effect(
    ctx: ExecutionContext,
    run_store: RunStore,
    scope_runner: RunScopeRunner,
    parse: PayloadParser,
    body: EffectBody,
) -> EffectOutcome:
    """
    Parse the payload, load the run, run ``body`` inside the run's scopes and bound its result.

    ``body`` gets the run and the parsed payload with its checked ``effect_key``.
    ``EffectRefused`` and ``CoralSessionError`` become failures with their own
    code and retryability, and an over-budget result a permanent
    ``effect.result_too_large``; anything else, a lost lease included, reaches
    the drainer.
    """
    try:
        raw = effect_payload(ctx)
        payload = {**parse(raw), "effect_key": run_effect_key(ctx, raw)}
        state = await load_effect_run(run_store, ctx, raw)
        async with run_scope(scope_runner, state):
            result = await body(state, payload)
        return EffectCompleted(result=bound_result(result))
    except EffectRefused as exc:
        return exc.outcome()
    except CoralSessionError as exc:
        return EffectRefused(exc.code, exc.message, retryable=exc.retryable).outcome()
    except ResultTooLarge as exc:
        return EffectRefused("effect.result_too_large", str(exc)).outcome()
