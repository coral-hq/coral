"""K21 executor for ``create_session``: the run's anchor and its step sessions.

The executor acts as the stored run's owner and account registration, takes a
step's host and run worktree from the run spec (never from the payload), and
asks the session facade inside the run's own scopes, which makes a
redelivered effect reuse one session. Drift the facade finds (the anchor
archived, deleted or bound, or this step deleted) pauses the run, and the
effect fails permanently as ``drift.<cause>``. The result holds only what a
repeat reproduces; whether this try created the session is logged instead.
A paused run holds the effect (retryable ``run.paused``).
"""

from __future__ import annotations

import functools
import logging
import re
from collections.abc import Mapping
from typing import Any, get_args

from coral.omni.protocols import (
    RunScopeRunner,
    SessionCreateRequest,
    SessionFacade,
    SlotRoleName,
)
from coral.queue.executors import EffectExecutor, EffectOutcome, ExecutionContext
from coral.queue.run_effects import (
    EffectRefused,
    invalid_payload,
    optional_text,
    refuse_paused_run,
    required_text,
    run_effect,
)
from coral.recovery.drift import DriftDetected, DriftPauser
from coral.stores.protocols import RunState, RunStore

_logger = logging.getLogger(__name__)

CREATE_SESSION = "create_session"
SLOT_ROLE_NAMES: frozenset[str] = frozenset(get_args(SlotRoleName))
# The bindings table keeps 512 characters of an engine slot id.
MAX_ENGINE_SLOT_ID_CHARS = 512
# Omnigent's limit for a user-given session title.
MAX_TITLE_CHARS = 200
MAX_NODE_ID_CHARS = 128
# A session generation is stored as a small integer.
MAX_GENERATION = 32_767
_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def create_session_executor(
    facade: SessionFacade,
    run_store: RunStore,
    drift: DriftPauser,
    scope_runner: RunScopeRunner,
) -> EffectExecutor:
    """
    The ``create_session`` executor.

    Payload: ``effect_key`` and ``role`` (``anchor`` or ``step``); a step also
    carries ``agent_id``, ``engine_slot_id`` and ``slot_role``, and optionally
    ``title``, ``node_id`` and ``generation``. Result: ``{session_id, role,
    generation}``.

    :param drift: Pauses the run when the facade finds drift.
    """

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(_create, ctx, facade=facade, drift=drift)
        return await run_effect(ctx, run_store, scope_runner, _create_payload, body)

    return execute


async def _create(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    facade: SessionFacade,
    drift: DriftPauser,
) -> dict[str, Any]:
    refuse_paused_run(state)
    request = _request(state, payload)
    try:
        ref = await facade.create_session(request, ensure_lease=ctx.ensure_lease)
    except DriftDetected as exc:
        await drift.pause(
            workspace_id=state.workspace_id, run_id=state.run_id, finding=exc.finding
        )
        raise EffectRefused(exc.finding.effect_code, exc.message) from exc
    _logger.info(
        "create_session for run %s: %s session %s",
        state.run_id,
        "created" if ref.created else "reused",
        ref.session_id,
    )
    return {"session_id": ref.session_id, "role": ref.role, "generation": request.generation}


def _request(state: RunState, payload: Mapping[str, Any]) -> SessionCreateRequest:
    identity = {
        "workspace_id": state.workspace_id,
        "run_id": state.run_id,
        "effect_key": payload["effect_key"],
        "user_id": state.run.user_id,
        "account_generation": state.run.account_generation,
    }
    if payload["role"] == "anchor":
        return SessionCreateRequest(**identity, role="anchor", title=state.run.title)
    spec = state.spec
    if not (spec.host_id and spec.worktree_path):
        raise EffectRefused(
            "session.invalid", f"run {state.run_id} has no run worktree on a host for its steps"
        )
    generation = payload["generation"]
    return SessionCreateRequest(
        **identity,
        role="step",
        title=payload["title"] or _slot_title(payload["engine_slot_id"], generation),
        agent_id=payload["agent_id"],
        host_id=spec.host_id,
        workspace=spec.worktree_path,
        engine_slot_id=payload["engine_slot_id"],
        slot_role=payload["slot_role"],
        node_id=payload["node_id"],
        generation=generation,
    )


def _slot_title(engine_slot_id: str, generation: int) -> str:
    """A step's default title: unique under the anchor, so a later generation adds its attempt."""
    return engine_slot_id if generation == 1 else f"{engine_slot_id} (attempt {generation})"


def _create_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    role = payload.get("role")
    if role == "anchor":
        return {"role": "anchor"}
    if role != "step":
        raise invalid_payload("role must be 'anchor' or 'step'")
    agent_id = required_text(payload, "agent_id")
    if not _AGENT_ID.fullmatch(agent_id):
        raise invalid_payload("agent_id must be 1-64 of A-Z, a-z, 0-9, '_' or '-'")
    slot_role = payload.get("slot_role")
    if slot_role not in SLOT_ROLE_NAMES:
        raise invalid_payload(f"slot_role must be one of {', '.join(sorted(SLOT_ROLE_NAMES))}")
    return {
        "role": "step",
        "agent_id": agent_id,
        "engine_slot_id": _bounded_text(
            payload, "engine_slot_id", max_chars=MAX_ENGINE_SLOT_ID_CHARS, required=True
        ),
        "slot_role": slot_role,
        "title": _bounded_text(payload, "title", max_chars=MAX_TITLE_CHARS),
        "node_id": _bounded_text(payload, "node_id", max_chars=MAX_NODE_ID_CHARS),
        "generation": _generation(payload),
    }


def _bounded_text(
    payload: Mapping[str, Any], name: str, *, max_chars: int, required: bool = False
) -> str | None:
    value = required_text(payload, name) if required else optional_text(payload, name)
    if value is not None and (not value or len(value) > max_chars or _CONTROL.search(value)):
        raise invalid_payload(
            f"{name} must be 1-{max_chars} characters without control characters"
        )
    return value


def _generation(payload: Mapping[str, Any]) -> int:
    value = payload.get("generation", 1)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_GENERATION:
        raise invalid_payload(f"generation must be an integer from 1 to {MAX_GENERATION}")
    return value


__all__ = ["CREATE_SESSION", "create_session_executor"]
