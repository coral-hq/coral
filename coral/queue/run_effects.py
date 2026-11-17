"""Steps every engine effect executor shares: its payload, its run and the run's scopes.

The drainer enters scopes from the payload's ``user_id`` and
``account_generation``, which the engine does not vouch for. So an executor
loads its run, refuses a payload identity that differs from the run row or an
effect key of another run, and runs its body inside scopes built from the run
row (:func:`run_scope`). Payload fields an executor echoes into its result are
bounded here, so an oversized value fails before any side effect.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any

from coral.omni.protocols import RunScopeRunner
from coral.queue.executors import EffectFailed, ExecutionContext
from coral.slots.results import stored_text_bytes
from coral.stores.protocols import RunNotFound, RunState, RunStore

# Payload fields the drainer builds scopes from; the run row must agree with them.
_IDENTITY_FIELDS = ("user_id", "account_generation")
MAX_EFFECT_KEY_CHARS = 512
MAX_FAILURE_MESSAGE_CHARS = 2000
MAX_INVALID_PAYLOAD_MESSAGE_CHARS = 500
# Session ids are derived ids, and the bindings table keeps 64 characters.
_SESSION_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


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
        _CONTROL.search(value) or stored_text_bytes(value) > max_stored_bytes
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


def run_scope(scope_runner: RunScopeRunner, state: RunState) -> AbstractAsyncContextManager[None]:
    """The run's workspace, account-authority and host-owner scopes, from its row and spec."""
    return scope_runner.run_scope(
        workspace_id=state.workspace_id,
        run_id=state.run_id,
        user_id=state.run.user_id,
        account_generation=state.run.account_generation,
        host_id=state.spec.host_id,
    )
