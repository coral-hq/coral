"""K21 executors for a run's sessions: create, send input, close and cancel.

Each executor acts as the stored run's owner and account registration, takes
hosts and worktrees from the run spec (never from the payload), and runs
inside the run's own scopes. Results hold only what a repeat reproduces;
whether a try created a session, sent a message or forced a stop is logged.

``create_session`` asks the session facade, so a redelivered effect reuses one
session. A step create names its agent, or the stance and step whose bundle
the executor resolves as the run owner's agent. Drift the facade finds (the
anchor archived, deleted or bound, or this step deleted) pauses the run, and
the effect fails permanently as ``drift.<cause>``. ``send_input`` records the
message's stable id before sending, so a redelivery never sends twice; the
dispatch's drift hook pauses a drifted run the same way. ``close_slot`` and
``cancel_sessions`` act only on a step session this run bound, and a cancel
counts a session this run never bound as cancelled; a send or close waits
(retryable ``session.not_ready``) until the session's row exists, and a
writer's close also until a slot of the run names the session. A close commits
only for its slot's current writer session, and a writer's close must set the
closed label.

A paused run holds ``create_session`` and ``send_input`` (retryable
``run.paused``); a close still finishes an accepted handoff, and a cancel is
how a paused run ends.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
from collections.abc import Mapping
from typing import Any, get_args

from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole
from coral.model.ids import (
    MAX_SLUG_LENGTH,
    derived_id,
    effect_message_id,
    effect_op_key,
    effect_session_id,
)
from coral.omni.protocols import (
    MAX_ENGINE_MESSAGE_BYTES,
    CoralSessionError,
    HostWorkspaceChannels,
    RunScopeRunner,
    SessionCreateRequest,
    SessionDispatch,
    SessionEdgeWatcher,
    SessionFacade,
    SlotRoleName,
    StepAgentResolver,
    engine_message_text,
)
from coral.queue.executors import EffectExecutor, EffectOutcome, ExecutionContext
from coral.queue.run_effects import (
    CONTROL_CHARACTERS,
    EffectRefused,
    invalid_payload,
    optional_text,
    refuse_paused_run,
    required_text,
    run_effect,
    session_id_field,
)
from coral.recovery.drift import DriftDetected, DriftPauser
from coral.slots.close import (
    DEFAULT_BOUNDS,
    AcceptedEdits,
    CloseBounds,
    CommitSpec,
    ConfirmedStops,
    cancel_session,
    close_session,
)
from coral.stores.protocols import RunState, RunStore
from coral.stores.session_bindings import SessionBinding, SessionBindings
from coral.stores.stable_ids import StableIdConflict, StableIds
from coral.stores.workspace_op_intents import WorkspaceOpIntents
from coral.tools.catalog import ORCHESTRATOR_STANCE, TOOL_STANCES
from coral.workspace.executors import (
    WRITER_SLOT_ROLES,
    attempt_id_field,
    commit_id_field,
    commit_message_field,
    diff_stat_result,
    run_target,
    run_workspace_effect,
    workspace_for,
    writer_refusal,
)

_logger = logging.getLogger(__name__)

CREATE_SESSION = "create_session"
SEND_INPUT = "send_input"
CLOSE_SLOT = "close_slot"
CANCEL_SESSIONS = "cancel_sessions"
MESSAGE_KINDS: frozenset[str] = frozenset({"brief", "steer", "nudge"})
SLOT_ROLE_NAMES: frozenset[str] = frozenset(get_args(SlotRoleName))
# The bindings table keeps 512 characters of an engine slot id.
MAX_ENGINE_SLOT_ID_CHARS = 512
# Omnigent's limit for a user-given session title.
MAX_TITLE_CHARS = 200
MAX_NODE_ID_CHARS = 128
# A session generation is stored as a small integer.
MAX_GENERATION = 32_767
# A roster position; start refuses more than 32 live slots, so far fewer are used.
MAX_ROSTER_INDEX = 999
_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def create_session_executor(
    facade: SessionFacade,
    run_store: RunStore,
    drift: DriftPauser,
    scope_runner: RunScopeRunner,
    *,
    agents: StepAgentResolver | None = None,
) -> EffectExecutor:
    """
    The ``create_session`` executor.

    Payload: ``effect_key`` and ``role`` (``anchor`` or ``step``); a step also
    carries ``engine_slot_id`` and ``slot_role``, and optionally ``title``,
    ``node_id`` and ``generation``. Its agent is ``agent_id``, or else
    ``stance`` with ``workflow_slug``, ``node_id`` and ``roster_index`` (the
    orchestrator's stance alone), resolved by ``agents``. Result:
    ``{session_id, role, generation}``.

    :param drift: Pauses the run when the facade finds drift.
    :param agents: Resolves a stance to the run owner's agent; without it a
        stance payload is invalid.
    """

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(_create, ctx, facade=facade, drift=drift, agents=agents)
        return await run_effect(ctx, run_store, scope_runner, _create_payload, body)

    return execute


async def _create(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    facade: SessionFacade,
    drift: DriftPauser,
    agents: StepAgentResolver | None,
) -> dict[str, Any]:
    refuse_paused_run(state)
    if payload["role"] == "step":
        _require_run_worktree(state)
        if payload["agent_id"] is None:
            payload = {**payload, "agent_id": await _resolved_agent(agents, state, payload)}
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


def _require_run_worktree(state: RunState) -> None:
    """:raises EffectRefused: Permanent ``session.invalid`` when steps have no worktree."""
    if not (state.spec.host_id and state.spec.worktree_path):
        raise EffectRefused(
            "session.invalid", f"run {state.run_id} has no run worktree on a host for its steps"
        )


async def _resolved_agent(
    agents: StepAgentResolver | None, state: RunState, payload: Mapping[str, Any]
) -> str:
    """The run owner's agent for the payload's stance, resolved inside the run's scopes."""
    if agents is None:
        raise invalid_payload("a step needs agent_id: this server resolves no stance")
    return await agents.resolve(
        workspace_id=state.workspace_id,
        owner=state.run.user_id,
        stance=payload["stance"],
        workflow_slug=payload["workflow_slug"],
        node_id=payload["node_id"],
        roster_index=payload["roster_index"],
        # The facade derives the same id, so a retry keeps the agent its session runs.
        session_id=effect_session_id(state.workspace_id, payload["effect_key"]),
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
    slot_role = payload.get("slot_role")
    if slot_role not in SLOT_ROLE_NAMES:
        raise invalid_payload(f"slot_role must be one of {', '.join(sorted(SLOT_ROLE_NAMES))}")
    step = {
        "role": "step",
        "engine_slot_id": _bounded_text(
            payload, "engine_slot_id", max_chars=MAX_ENGINE_SLOT_ID_CHARS, required=True
        ),
        "slot_role": slot_role,
        "title": _bounded_text(payload, "title", max_chars=MAX_TITLE_CHARS),
        "node_id": _bounded_text(payload, "node_id", max_chars=MAX_NODE_ID_CHARS),
        "generation": _generation(payload),
    }
    agent_id = optional_text(payload, "agent_id")
    if agent_id is not None:
        if not _AGENT_ID.fullmatch(agent_id):
            raise invalid_payload("agent_id must be 1-64 of A-Z, a-z, 0-9, '_' or '-'")
        return {**step, "agent_id": agent_id}
    return {**step, **_stance_fields(payload, node_id=step["node_id"]), "agent_id": None}


def _stance_fields(payload: Mapping[str, Any], *, node_id: str | None) -> dict[str, Any]:
    """The stance and step a step's agent is resolved from, when no ``agent_id`` names it."""
    stance = payload.get("stance")
    if not isinstance(stance, str) or stance not in TOOL_STANCES:
        raise invalid_payload(
            f"a step needs agent_id or a stance: one of {', '.join(sorted(TOOL_STANCES))}"
        )
    if stance == ORCHESTRATOR_STANCE:
        return {"stance": stance, "workflow_slug": None, "roster_index": None}
    if node_id is None:
        raise invalid_payload("a step stance needs node_id")
    roster_index = payload.get("roster_index")
    if (
        isinstance(roster_index, bool)
        or not isinstance(roster_index, int)
        or not 0 <= roster_index <= MAX_ROSTER_INDEX
    ):
        raise invalid_payload(f"roster_index must be an integer from 0 to {MAX_ROSTER_INDEX}")
    return {
        "stance": stance,
        "workflow_slug": _bounded_text(
            payload, "workflow_slug", max_chars=MAX_SLUG_LENGTH, required=True
        ),
        "roster_index": roster_index,
    }


def _bounded_text(
    payload: Mapping[str, Any], name: str, *, max_chars: int, required: bool = False
) -> str | None:
    value = required_text(payload, name) if required else optional_text(payload, name)
    if value is not None and (
        not value or len(value) > max_chars or CONTROL_CHARACTERS.search(value)
    ):
        raise invalid_payload(
            f"{name} must be 1-{max_chars} characters without control characters"
        )
    return value


def _generation(payload: Mapping[str, Any]) -> int:
    value = payload.get("generation", 1)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_GENERATION:
        raise invalid_payload(f"generation must be an integer from 1 to {MAX_GENERATION}")
    return value


# ── send_input, close_slot, cancel_sessions ─────────────────────────────────


def send_input_executor(
    dispatch: SessionDispatch,
    stable_ids: StableIds,
    bindings: SessionBindings,
    run_store: RunStore,
    scope_runner: RunScopeRunner,
) -> EffectExecutor:
    """
    The ``send_input`` executor.

    Payload: ``effect_key``, ``session_id``, ``text``, ``kind`` (``brief``,
    ``steer`` or ``nudge``). Result: ``{session_id, stable_id}``.
    """

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(
            _send, ctx, dispatch=dispatch, stable_ids=stable_ids, bindings=bindings
        )
        return await run_effect(ctx, run_store, scope_runner, _send_payload, body)

    return execute


def close_slot_executor(
    dispatch: SessionDispatch,
    edges: SessionEdgeWatcher,
    channels: HostWorkspaceChannels,
    intents: WorkspaceOpIntents,
    stable_ids: StableIds,
    bindings: SessionBindings,
    run_store: RunStore,
    scope_runner: RunScopeRunner,
    *,
    bounds: CloseBounds = DEFAULT_BOUNDS,
    stops: ConfirmedStops | None = None,
) -> EffectExecutor:
    """
    The ``close_slot`` executor (:func:`coral.slots.close.close_session`).

    Payload: ``effect_key``, ``session_id``; optional ``interrupt`` and
    ``closed_label`` (default ``true``), ``message``, ``attempt_id`` and
    ``diff_from``. Result: ``{pending_input, queued_input, post_accept_edits,
    commit, empty, diff_stat}``; the last three are ``null`` for a reader.

    :param stops: Records each confirmed stop for ``workspace.commit``'s turn-end check.
    """
    # One per executor: a redelivered close in this process repeats its first answer.
    accepted_edits = AcceptedEdits()

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(
            _close,
            ctx,
            dispatch=dispatch,
            edges=edges,
            channels=channels,
            intents=intents,
            stable_ids=stable_ids,
            bindings=bindings,
            bounds=bounds,
            stops=stops,
            accepted_edits=accepted_edits,
        )
        return await run_workspace_effect(ctx, run_store, scope_runner, _close_payload, body)

    return execute


def cancel_sessions_executor(
    dispatch: SessionDispatch,
    edges: SessionEdgeWatcher,
    bindings: SessionBindings,
    run_store: RunStore,
    scope_runner: RunScopeRunner,
    *,
    bounds: CloseBounds = DEFAULT_BOUNDS,
) -> EffectExecutor:
    """
    The ``cancel_sessions`` executor (:func:`coral.slots.close.cancel_session`).

    Payload: ``effect_key``, ``session_id`` (required; ``null`` for a slot with
    no session yet), optional ``closed_label`` (default ``true``). Result:
    ``{session_id}``. A session already deleted, or never bound in this run,
    counts as cancelled.
    """

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(
            _cancel, ctx, dispatch=dispatch, edges=edges, bindings=bindings, bounds=bounds
        )
        return await run_effect(ctx, run_store, scope_runner, _cancel_payload, body)

    return execute


async def _send(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    dispatch: SessionDispatch,
    stable_ids: StableIds,
    bindings: SessionBindings,
) -> dict[str, Any]:
    refuse_paused_run(state)
    session_id = payload["session_id"]
    binding = await _bound_step(bindings, state, session_id, created=True)
    stable_id = effect_message_id(ctx.workspace_id, payload["effect_key"])
    try:
        # Recorded before the send, so a crash after it still names the engine's item.
        await asyncio.to_thread(
            stable_ids.record_send,
            ctx.workspace_id,
            stable_id=stable_id,
            run_id=state.run_id,
            session_id=session_id,
            effect_key=payload["effect_key"],
            kind=payload["kind"],
            generation=binding.session_generation,
            content=engine_message_text(payload["text"]),
        )
    except StableIdConflict as exc:
        raise EffectRefused(
            "effect.identity_mismatch",
            f"engine message {stable_id} is recorded for another send of this effect",
        ) from exc
    await ctx.ensure_lease()
    receipt = await dispatch.send_message(
        workspace_id=ctx.workspace_id,
        run_id=state.run_id,
        session_id=session_id,
        user_id=state.run.user_id,
        stable_id=stable_id,
        text=payload["text"],
    )
    _logger.info(
        "send_input for run %s: message %s %s to session %s",
        state.run_id,
        receipt.item_id or receipt.pending_id,
        receipt.delivery,
        session_id,
    )
    return {"session_id": session_id, "stable_id": stable_id}


async def _close(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    dispatch: SessionDispatch,
    edges: SessionEdgeWatcher,
    channels: HostWorkspaceChannels,
    intents: WorkspaceOpIntents,
    stable_ids: StableIds,
    bindings: SessionBindings,
    bounds: CloseBounds,
    stops: ConfirmedStops | None,
    accepted_edits: AcceptedEdits,
) -> dict[str, Any]:
    session_id = payload["session_id"]
    binding = await _bound_step(bindings, state, session_id, created=True)
    commit = await _commit_spec(ctx, state, payload, binding, channels, intents)
    if commit is not None and not payload["closed_label"]:
        # Without the label a user message could relaunch the writer before its commit.
        raise invalid_payload("a writer's close must set closed_label")
    engine_messages = await asyncio.to_thread(
        stable_ids.checksums_for_session, ctx.workspace_id, session_id, run_id=state.run_id
    )
    outcome = await close_session(
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        user_id=state.run.user_id,
        slot_id=binding.slot_id or "",
        interrupt=payload["interrupt"],
        closed_label=payload["closed_label"],
        commit=commit,
        engine_messages=engine_messages,
        dispatch=dispatch,
        edges=edges,
        ensure_lease=ctx.ensure_lease,
        bounds=bounds,
        stops=stops,
        accepted_edits=accepted_edits,
    )
    if outcome.forced_stop:
        _logger.info(
            "close_slot for run %s: the stop ended session %s's turn", state.run_id, session_id
        )
    return {
        "pending_input": outcome.pending_input,
        "queued_input": outcome.queued_input,
        "post_accept_edits": outcome.post_accept_edits,
        "commit": outcome.commit,
        "empty": outcome.empty,
        "diff_stat": None if outcome.diff_stat is None else diff_stat_result(outcome.diff_stat),
    }


async def _commit_spec(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    binding: SessionBinding,
    channels: HostWorkspaceChannels,
    intents: WorkspaceOpIntents,
) -> CommitSpec | None:
    """
    The close's commit, only for its slot's current writer session; readers never commit.

    :raises EffectRefused: Retryable ``session.not_ready`` while no slot of the
        run names the writer's session: closing then would drop its commit.
    """
    if binding.slot_role not in WRITER_SLOT_ROLES:
        return None
    # The bridge records a slot's session once its create completes.
    if not any(slot.session_id == binding.session_id for slot in state.agent_slots):
        raise EffectRefused(
            "session.not_ready",
            f"no slot of run {state.run_id} names step session {binding.session_id} yet",
            retryable=True,
        )
    target = run_target(state)
    reason = writer_refusal(binding, state, target, binding.session_id)
    if reason is not None:
        _logger.info(
            "close_slot for run %s: session %s %s; closing without a commit",
            state.run_id,
            binding.session_id,
            reason,
        )
        return None
    slot_id = binding.slot_id or ""
    return CommitSpec(
        workspace=await workspace_for(channels, state, target),
        ref=target.ref,
        intents=intents,
        workspace_id=ctx.workspace_id,
        run_id=state.run_id,
        op_key=effect_op_key(ctx.workspace_id, payload["effect_key"], "commit"),
        message=payload["message"] or f"Coral: {slot_id}",
        attempt_id=payload["attempt_id"]
        or derived_id("coral-attempt", state.run_id, slot_id, str(binding.session_generation)),
        diff_from=payload["diff_from"],
    )


async def _cancel(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    dispatch: SessionDispatch,
    edges: SessionEdgeWatcher,
    bindings: SessionBindings,
    bounds: CloseBounds,
) -> dict[str, Any]:
    session_id = payload["session_id"]
    if session_id is None:
        return {"session_id": None}
    found = await asyncio.to_thread(
        bindings.get, state.workspace_id, session_id, run_id=state.run_id
    )
    if found is None:
        # The slot's create never bound it in this run: nothing was created to cancel.
        _logger.info(
            "cancel_sessions for run %s: session %s was never bound", state.run_id, session_id
        )
        return {"session_id": session_id}
    binding = _step_binding(found, state, session_id)
    try:
        await cancel_session(
            workspace_id=ctx.workspace_id,
            session_id=session_id,
            user_id=state.run.user_id,
            slot_id=binding.slot_id or "",
            closed_label=payload["closed_label"],
            dispatch=dispatch,
            edges=edges,
            ensure_lease=ctx.ensure_lease,
            bounds=bounds,
        )
    except CoralSessionError as exc:
        if exc.code != "session.deleted":
            raise
        _logger.info("cancel_sessions for run %s: session %s is gone", state.run_id, session_id)
    return {"session_id": session_id}


async def _bound_step(
    bindings: SessionBindings, state: RunState, session_id: str, *, created: bool = False
) -> SessionBinding:
    """
    The binding of a step session this run created.

    :param created: Also require the session's row: its create got past ``reserved``.
    :raises EffectRefused: Permanent ``session.identity_conflict`` for any other
        session; retryable ``session.not_ready`` while its create is unfinished,
        including the run's orchestrator before its create bound it.
    """
    binding = await asyncio.to_thread(
        bindings.get, state.workspace_id, session_id, run_id=state.run_id
    )
    return _step_binding(binding, state, session_id, created=created)


def _step_binding(
    binding: SessionBinding | None, state: RunState, session_id: str, *, created: bool = False
) -> SessionBinding:
    """``binding`` when it is a step session of the run, past ``reserved`` if ``created``."""
    if binding is None and session_id == state.run.orchestrator_session_id:
        # The bridge names the run's orchestrator before its create binds the session.
        raise EffectRefused(
            "session.not_ready",
            f"orchestrator session {session_id} is still being created",
            retryable=True,
        )
    if binding is None or binding.role is not SessionBindingRole.STEP:
        raise EffectRefused(
            "session.identity_conflict",
            f"session {session_id} is not a step session of run {state.run_id}",
        )
    if created and binding.progress < SessionBindingProgress.ROW_CREATED:
        raise EffectRefused(
            "session.not_ready",
            f"step session {session_id} is still being created",
            retryable=True,
        )
    return binding


def _send_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    kind = payload.get("kind")
    if kind not in MESSAGE_KINDS:
        raise invalid_payload(f"kind must be one of {', '.join(sorted(MESSAGE_KINDS))}")
    text = required_text(payload, "text")
    try:
        size = len(engine_message_text(text).encode())
    except UnicodeEncodeError:
        raise invalid_payload("text must be valid Unicode text") from None
    if "\0" in text or size > MAX_ENGINE_MESSAGE_BYTES:
        raise invalid_payload(
            f"text must be at most {MAX_ENGINE_MESSAGE_BYTES} bytes as sent, without NUL"
        )
    return {"session_id": session_id_field(payload), "text": text, "kind": kind}


def _close_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "session_id": session_id_field(payload),
        "interrupt": _flag(payload, "interrupt"),
        "closed_label": _flag(payload, "closed_label"),
        "message": commit_message_field(payload, required=False),
        "attempt_id": attempt_id_field(payload, required=False),
        "diff_from": commit_id_field(payload, "diff_from"),
    }


def _cancel_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    # Only an explicit null means "no session yet": a payload that lost the key cancels nothing.
    if "session_id" not in payload:
        raise invalid_payload("session_id is required: null for a slot with no session yet")
    session_id = None if payload["session_id"] is None else session_id_field(payload)
    return {"session_id": session_id, "closed_label": _flag(payload, "closed_label")}


def _flag(payload: Mapping[str, Any], name: str) -> bool:
    """A boolean field that defaults to ``true``, as the engine emits it."""
    value = payload.get(name, True)
    if not isinstance(value, bool):
        raise invalid_payload(f"{name} must be true or false")
    return value


__all__ = [
    "CANCEL_SESSIONS",
    "CLOSE_SLOT",
    "CREATE_SESSION",
    "MAX_ROSTER_INDEX",
    "MESSAGE_KINDS",
    "SEND_INPUT",
    "cancel_sessions_executor",
    "close_slot_executor",
    "create_session_executor",
    "send_input_executor",
]
