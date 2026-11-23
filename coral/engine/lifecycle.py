"""Pause, resume, cancel, retry and restarts, runner losses and holds, and timer deadlines."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import JsonValue

from coral.engine.facts import runner_loss_key, turn_key_generation
from coral.engine.machines.activation import (
    activation_id,
    create_session_effect,
    find_activation,
    find_node,
    replace_activation,
    route_closed_step,
    traverse_arrow,
)
from coral.engine.machines.run import receipt_only, record_pause, refuse, refuse_unknown
from coral.engine.machines.slot import (
    awaiting_effect,
    effect_generation,
    fail_effect,
    find_slot,
    finish_pending_closes,
    map_slot,
    mark_failed_turn,
    reports_an_ended_outage,
)
from coral.engine.timers import (
    INFRA_BACKOFF,
    ORCHESTRATOR_BACKOFF,
    ORCHESTRATOR_SUBJECT,
    PLAN_PROBE,
    WATCHDOG_KINDS,
    arm_infra_backoff,
    arm_plan_probe,
    drop_slot_backoff,
    find_timer,
    has_live_timer,
    rearm_plan_probe,
)
from coral.engine.types import (
    RULES,
    Activation,
    ApplyResult,
    AttemptCount,
    Decision,
    Effect,
    EffectCompleted,
    EffectFailed,
    InfraBackoffExhausted,
    OrchestratorTurn,
    PauseCause,
    PauseReason,
    PauseRun,
    Receipt,
    RejectionObserved,
    ResumeRun,
    RetryStep,
    RunnerHeld,
    RunnerHoldEnded,
    RunnerLost,
    RunState,
    SessionFailed,
    Slot,
    Timer,
    TimerDue,
    TimerPolicy,
    UsageLimited,
    WaitingWithoutElicitation,
    effect_key,
)
from coral.model.ir import CompiledArrow, CompiledGraph
from coral.signals.facts import assign_effect_keys
from coral.signals.outcomes import arm_timer_effect, outcomes, pause_for

# ResumeRun clears these. ``budget`` is separate: it needs a raised cap.
_RESUME_REASONS: frozenset[PauseReason] = frozenset(
    {
        "user",
        "rejected_calls",
        "infra",
        "auth",
        "drift",
        "plan_limit",
        "authority_revoked",
    }
)
_RETRY_REASONS: frozenset[PauseReason] = frozenset({"infra", "failure_path", "liveness"})
# ``infra`` details that hold a slot: neither Resume nor Retry clears them.
HOST_OFFLINE_DETAIL = "infra.host_offline"
RESTARTING_DETAIL = "recovery.restarting"
_HELD_DETAILS = frozenset({HOST_OFFLINE_DETAIL, RESTARTING_DETAIL})
# The fourth runner loss of one generation pauses with this detail instead of waking.
RUNNER_LOST_DETAIL = "infra.runner_lost"
MAX_WAKES = 3
# Wake outcomes that leave the slot on a connected runner.
_RUNNER_UP = frozenset({"runner_back", "relaunched"})
# A failed or abandoned restart pauses ``failure_path`` with this prefix and its code.
RESTART_FAILED_PREFIX = "restart:"
_MAX_RESTART_CODE_CHARS = 128
_COUNTED_REJECTIONS = frozenset({"handoff.invalid", "tool.illegal"})
# A failed turn of a slot in these states came after its accepted handoff.
_HANDED_OFF = frozenset({"closing", "closed"})
_RETRY_PHASES: tuple[str, ...] = (
    "fence_stop",
    "salvage_reset",
    "create_unbriefed",
    "brief",
)
# A closed step with one of these outcomes is done, so it is never retried.
_FINISHED_OUTCOMES = frozenset({"completed", "skipped"})
# A run-level retry of a cause with one of these prefixes replaces the orchestrator.
_ORCHESTRATOR_PREFIXES = ("orchestrator:", "decision:")
# The orchestrator create payload's generation bound (``coral.slots.executors.MAX_GENERATION``).
_MAX_ORCHESTRATOR_GENERATION = 32_767
# The previous rules let Resume clear a step's failed turn no rule names.
_UNNAMED_TURN_FAILURE = "agent.failed"


def pause_run(state: RunState, command: PauseRun) -> ApplyResult:
    """Record ``command`` with an empty subject. An identical cause already present is a no-op.

    Priority order lives in ``record_pause``.
    """
    if PauseCause(reason=command.reason, detail=command.detail, subject="") in state.causes:
        return ApplyResult(state=state)
    paused = record_pause(state, command.reason, command.detail, "")
    return ApplyResult(state=paused.model_copy(update={"seq": state.seq + 1}))


def resume_run(graph: CompiledGraph, state: RunState, command: ResumeRun) -> ApplyResult:
    """Clear the causes ResumeRun is allowed to clear. A miss changes nothing.

    That is every resumable reason except a hold or a restart, and ``budget`` given a
    higher cap. Clearing a slot's fourth-loss pause ends that runner outage. A run that
    is running again finishes pending closes, advances, and re-prompts its failed and
    stopped slots.
    """
    store_cap: int | None = None
    if any(cause.reason == "budget" for cause in state.causes):
        if command.cap is not None and command.cap > state.max_activations:
            store_cap = command.cap

    def cleared(cause: PauseCause) -> bool:
        if cause.reason == "budget" and store_cap is not None:
            return True
        return resume_clears(cause, rules=state.rules)

    reasons = {cause.reason for cause in state.causes if cleared(cause)}
    if not reasons:
        return refuse(state, "resume_not_allowed")
    lost = [
        cause.subject
        for cause in state.causes
        if cause.reason == "infra" and cause.detail == RUNNER_LOST_DETAIL
    ]
    updated = _without_causes(state, cleared)
    for slot_id in lost:
        updated = _end_outage(updated, slot_id)
    changes: dict[str, object] = {"seq": state.seq + 1}
    if store_cap is not None:
        changes["max_activations"] = store_cap
    if "rejected_calls" in reasons:
        changes["reject_streaks"] = tuple(
            item.model_copy(update={"count": 0}) for item in updated.reject_streaks
        )
        changes["slots"] = tuple(item.model_copy(update={"nudges": 0}) for item in updated.slots)
    updated = updated.model_copy(update=changes)
    effects: tuple[Effect, ...] = ()
    if updated.status == "running":
        updated, effects = _advance_closed(graph, updated)
    if updated.status == "running":
        updated, nudges = _reprompt(updated, "resume")
        effects = (*effects, *nudges)
    return ApplyResult(state=updated, effects=effects)


def resume_clears(cause: PauseCause, *, rules: int = RULES) -> bool:
    """A resumable reason, unless the cause holds its slot (a host hold or a restart).

    The previous rules also cleared a step's failed turn no rule names.
    """
    if rules < RULES and cause.reason == "failure_path":
        return cause.detail == _UNNAMED_TURN_FAILURE and cause.subject != ""
    return cause.reason in _RESUME_REASONS and not holds_slot(cause)


def holds_slot(cause: PauseCause) -> bool:
    """A host-offline hold or a restart in progress: only its own completion clears it."""
    return cause.reason == "infra" and cause.detail in _HELD_DETAILS


def retryable_activations(state: RunState) -> tuple[str, ...]:
    """The failed step activations a Retry may restart, in cause order.

    None while the run is not paused or a hold or a restart stands. Otherwise each
    ``infra``, ``failure_path`` or ``liveness`` cause names one through its subject (a
    slot, an activation, or a node's newest activation); only a step that has slots and
    did not close ``completed`` or ``skipped`` qualifies, so gates and decisions never do.
    """
    if state.status != "paused" or any(holds_slot(cause) for cause in state.causes):
        return ()
    found: list[str] = []
    for cause in state.causes:
        if cause.reason not in _RETRY_REASONS:
            continue
        owner = _cause_activation(state, cause.subject)
        if owner is None or owner.id in found:
            continue
        if not any(slot.activation_id == owner.id for slot in state.slots):
            continue
        if owner.status == "closed" and owner.outcome in _FINISHED_OUTCOMES:
            continue
        found.append(owner.id)
    return tuple(found)


def run_level_retryable(state: RunState) -> tuple[PauseCause, ...]:
    """The ``failure_path`` causes no step owns (subject ``""``) a run-level Retry clears.

    None while a hold or a restart stands.
    """
    if any(holds_slot(cause) for cause in state.causes):
        return ()
    return tuple(
        cause for cause in state.causes if cause.reason == "failure_path" and cause.subject == ""
    )


def retry_run(graph: CompiledGraph, state: RunState) -> ApplyResult:
    """Clear the run-level ``failure_path`` causes; a run running again resumes.

    An ``orchestrator:`` or ``decision:`` cause also moves the orchestrator to a new
    generation and drops its backoff ladder.
    """
    held = {cause.detail for cause in state.causes if holds_slot(cause)}
    if HOST_OFFLINE_DETAIL in held:
        return refuse(state, "host_offline_hold")
    if RESTARTING_DETAIL in held:
        return refuse(state, "restart_in_progress")
    causes = run_level_retryable(state)
    if not causes:
        return refuse(state, "retry_not_allowed")
    replace = any(cause.detail.startswith(_ORCHESTRATOR_PREFIXES) for cause in causes)
    changes: dict[str, object] = {"seq": state.seq + 1}
    updated = _without_causes(state, lambda cause: cause in causes)
    if replace:
        if state.orchestrator_generation >= _MAX_ORCHESTRATOR_GENERATION:
            return refuse(state, "retry_not_allowed")
        changes["orchestrator_generation"] = state.orchestrator_generation + 1
        updated = _drop_orchestrator_backoff(updated)
    updated = updated.model_copy(update=changes)
    effects: tuple[Effect, ...] = ()
    if updated.status == "running":
        updated, effects = _advance_closed(graph, updated)
    if updated.status == "running":
        updated, nudges = _reprompt(updated, "resume")
        effects = (*effects, *nudges)
    return ApplyResult(state=updated, effects=effects)


def orchestrator_turn(
    state: RunState, command: OrchestratorTurn, now: datetime, policy: TimerPolicy
) -> ApplyResult:
    """A transient failure of a running run arms the orchestrator's ladder once; no pause.

    A completed turn disarms it. Another failure class is refused ``not_supported``.
    """
    if not command.failed:
        dropped = _drop_orchestrator_backoff(state)
        if dropped == state:
            return ApplyResult(state=state)
        return ApplyResult(state=dropped.model_copy(update={"seq": state.seq + 1}))
    if command.failure != "infra.transient":
        return refuse(state, "not_supported")
    if state.status != "running" or has_live_timer(
        state, ORCHESTRATOR_BACKOFF, ORCHESTRATOR_SUBJECT, now
    ):
        return ApplyResult(state=state)
    armed = arm_infra_backoff(
        state,
        ORCHESTRATOR_SUBJECT,
        state.orchestrator_generation,
        now,
        policy,
        ORCHESTRATOR_BACKOFF,
    )
    return ApplyResult(state=armed.model_copy(update={"seq": state.seq + 1}))


def cancel_run(state: RunState) -> ApplyResult:
    """Cancel a live run once. A second call returns the receipt and emits nothing."""
    run_id = state.run_id if isinstance(state.run_id, str) else ""
    key = f"cancel:{run_id}"
    if any(item.key == key for item in state.receipts):
        return ApplyResult(state=state, receipt_key=key)
    seq = state.seq + 1
    effects: list[Effect] = [
        _effect(
            state,
            seq,
            "cancel_sessions",
            slot.id,
            {"interrupt": True, "closed_label": True},
        )
        for slot in state.slots
        if slot.status != "closed"
    ]
    effects.extend(
        _effect(state, seq, "withdraw_gate", visit.token, {"token": visit.token})
        for visit in state.gates
        if visit.status == "open"
    )
    effects.append(_effect(state, seq, "notify", run_id, {"kind": "run_cancelled"}))
    receipt = Receipt(key=key, payload={"status": "cancelled"})
    updated = state.model_copy(
        update={
            "status": "cancelled",
            "seq": seq,
            "timers": (),
            "effects": (*state.effects, *tuple(effects)),
            "receipts": (*state.receipts, receipt),
        }
    )
    return ApplyResult(state=updated, effects=tuple(effects), receipt_key=key)


def retry_step(state: RunState, command: RetryStep) -> ApplyResult:
    """Restart one failed step in a new session generation. The run stays paused.

    Only the step's own causes clear, plus its slots' pending-input drift. Each slot is
    bumped and held ``recovery.restarting`` until its ``retry_step`` effect completes or
    fails, so the old session cannot act between the retry and its fence.
    """
    owner_id = activation_id(command.node_id, command.item_path, command.iteration_path)
    if find_activation(state, owner_id) is None:
        return refuse_unknown(state)
    held = {cause.detail for cause in state.causes if holds_slot(cause)}
    if HOST_OFFLINE_DETAIL in held:
        return refuse(state, "host_offline_hold")
    if RESTARTING_DETAIL in held:
        return refuse(state, "restart_in_progress")
    if owner_id not in retryable_activations(state):
        return refuse(state, "retry_not_allowed")
    slot_ids = {slot.id for slot in state.slots if slot.activation_id == owner_id}
    # A retried slot's pending input goes with its session, and so does its drift cause.
    cleared = _without_causes(
        state,
        lambda cause: (
            (cause.reason in _RETRY_REASONS and _resolves_to(state, cause.subject, owner_id))
            or (
                cause.reason == "drift"
                and cause.detail == "pending_input"
                and cause.subject in slot_ids
            )
        ),
    )
    cleared = drop_slot_backoff(cleared, slot_ids)
    seq = state.seq + 1
    retried, effects = _retry_slots(cleared, owner_id, seq)
    retried = replace_activation(
        retried.model_copy(
            update={
                "seq": seq,
                "effects": (*retried.effects, *effects),
                "attempts": _reset_attempts(retried, owner_id),
            }
        ),
        owner_id,
        status="starting",
        outcome=None,
    )
    return ApplyResult(state=retried, effects=effects)


def complete_restart(
    graph: CompiledGraph, state: RunState, effect: Effect, command: EffectCompleted
) -> ApplyResult:
    """The restart fenced, salvaged and reset: create the new generation's session.

    The slot's restarting cause goes, and the create carries what was salvaged to the
    brief. A run running again finishes pending closes and re-prompts as a resume does.
    A result for a slot that moved on only records its receipt.
    """
    slot = find_slot(state, effect.subject)
    if slot is None:
        return refuse_unknown(state)
    owner = find_activation(state, slot.activation_id)
    node = find_node(graph, owner.node_id) if owner is not None else None
    if slot.status != "pending" or effect_generation(effect) != slot.session_generation:
        return receipt_only(state, effect.effect_key, dict(command.payload))
    if node is None:
        return refuse_unknown(state)
    seq = state.seq + 1
    extra: dict[str, JsonValue] = {}
    salvage_ref = command.payload.get("salvage_ref")
    if isinstance(salvage_ref, str):
        salvage_commit = command.payload.get("salvage_commit")
        extra = {
            "salvage_ref": salvage_ref,
            "salvage_commit": salvage_commit if isinstance(salvage_commit, str) else None,
        }
    create = create_session_effect(_run_id(state), seq, slot, node, extra)
    restarting = _restarting_cause(slot.id)
    cleared = _without_causes(state, lambda cause: cause == restarting)
    receipt = Receipt(key=effect.effect_key, payload=dict(command.payload))
    updated = cleared.model_copy(
        update={
            "seq": seq,
            "effects": (*cleared.effects, create),
            "receipts": (*cleared.receipts, receipt),
        }
    )
    effects: tuple[Effect, ...] = (create,)
    if updated.status == "running":
        updated, spawned = _advance_closed(graph, updated)
        effects = (*effects, *spawned)
    if updated.status == "running":
        updated, nudges = _reprompt(updated, "resume")
        effects = (*effects, *nudges)
    return ApplyResult(state=updated, effects=effects, receipt_key=effect.effect_key)


def fail_restart(state: RunState, effect: Effect, command: EffectFailed) -> ApplyResult:
    """A restart that failed or was abandoned leaves the step paused for a Retry only.

    Retryable and permanent failures alike replace the restarting cause with
    ``failure_path`` / ``restart:<code>`` and receipt the effect. A result for a slot that
    moved on only records its receipt.
    """
    slot = find_slot(state, effect.subject)
    if slot is None:
        return refuse_unknown(state)
    code = command.code[:_MAX_RESTART_CODE_CHARS]
    payload: dict[str, JsonValue] = {"failed": code}
    if slot.status != "pending" or effect_generation(effect) != slot.session_generation:
        return receipt_only(state, effect.effect_key, payload)
    restarting = _restarting_cause(slot.id)
    kept = state.model_copy(
        update={"causes": tuple(cause for cause in state.causes if cause != restarting)}
    )
    detail = RESTART_FAILED_PREFIX + code
    paused = record_pause(kept, "failure_path", detail, slot.id)
    receipt = Receipt(key=effect.effect_key, payload=payload)
    failed = paused.model_copy(
        update={"seq": state.seq + 1, "receipts": (*paused.receipts, receipt)}
    )
    return ApplyResult(state=failed, receipt_key=effect.effect_key)


def complete_wake(
    graph: CompiledGraph, state: RunState, effect: Effect, command: EffectCompleted
) -> ApplyResult:
    """The wake found the runner back, relaunched it, or skipped the slot.

    Any result of the slot's generation ends the outage it was for, so a later loss of
    the same runner is a new one. A runner back or relaunched with its turn already
    running only clears the failed turn and the slot's infra ladder; any other one
    re-prompts the slot once. A skipped wake ends the slot's host-offline hold, since
    nothing waits on the host any more. A slot that is no longer working, moved on, or
    holds only records the receipt.
    """
    slot = find_slot(state, effect.subject)
    if slot is None:
        return refuse_unknown(state)
    outcome = command.payload.get("outcome")
    receipt_payload = dict(command.payload)
    if effect_generation(effect) != slot.session_generation:
        return receipt_only(state, effect.effect_key, receipt_payload)
    ended = _record_wake(_end_outage(state, slot.id), slot.id, effect, command.payload)
    if outcome == "skipped":
        released = _release_hold(ended, slot.id)
        receipted = receipt_only(released, effect.effect_key, receipt_payload)
        if released.status == "running" and state.status != "running":
            advanced, effects = _advance_closed(graph, receipted.state)
            return receipted.model_copy(update={"state": advanced, "effects": effects})
        return receipted
    if slot.status != "working" or _slot_holds(state, slot.id):
        return receipt_only(ended, effect.effect_key, receipt_payload)
    receipt = Receipt(key=effect.effect_key, payload=receipt_payload)
    receipted_state = ended.model_copy(
        update={"seq": state.seq + 1, "receipts": (*ended.receipts, receipt)}
    )
    if outcome in _RUNNER_UP and command.payload.get("turn_running") is True:
        recovered = drop_slot_backoff(
            map_slot(receipted_state, slot.id, failed_turn=None), (slot.id,), (INFRA_BACKOFF,)
        )
        return ApplyResult(state=recovered, receipt_key=effect.effect_key)
    nudged, effects = _reprompt(receipted_state, "runner_lost", only=slot.id)
    return ApplyResult(state=nudged, effects=effects, receipt_key=effect.effect_key)


def fail_wake(state: RunState, effect: Effect, command: EffectFailed) -> ApplyResult:
    """A wake that gave up pauses as any effect does, ends the outage it was for, and ends
    the slot's host-offline hold: nothing waits on the host any more."""
    failed = fail_effect(state, effect, command)
    slot = find_slot(state, effect.subject)
    if slot is None or effect_generation(effect) != slot.session_generation:
        return failed
    ended = _release_hold(_end_outage(failed.state, slot.id), slot.id)
    return failed.model_copy(update={"state": ended.model_copy(update={"seq": state.seq + 1})})


def note_runner_held(state: RunState, command: RunnerHeld) -> ApplyResult:
    """Hold a working slot whose host is offline: Cancel only, and no infra re-prompts."""
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if command.generation != slot.session_generation:
        return refuse(state, "slot.superseded")
    cause = _host_offline_cause(slot.id)
    if slot.status != "working" or cause in state.causes:
        return ApplyResult(state=state)
    held = drop_slot_backoff(state, (slot.id,), (INFRA_BACKOFF,))
    paused = record_pause(held, cause.reason, cause.detail, cause.subject)
    return ApplyResult(state=paused.model_copy(update={"seq": state.seq + 1}))


def note_runner_hold_ended(
    graph: CompiledGraph, state: RunState, command: RunnerHoldEnded
) -> ApplyResult:
    """Drop the slot's hold. A run running again finishes closes; the wake re-prompts."""
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if command.generation != slot.session_generation:
        return refuse(state, "slot.superseded")
    cause = _host_offline_cause(slot.id)
    if cause not in state.causes:
        return ApplyResult(state=state)
    ended = _without_causes(state, lambda item: item == cause)
    ended = ended.model_copy(update={"seq": state.seq + 1})
    effects: tuple[Effect, ...] = ()
    if ended.status == "running":
        ended, effects = _advance_closed(graph, ended)
    return ApplyResult(state=ended, effects=effects)


def note_rejection(state: RunState, command: RejectionObserved) -> ApplyResult:
    """Count ``handoff.invalid`` and ``tool.illegal``.

    The run's ``rejected_call_limit``-th in a row pauses ``rejected_calls``.
    """
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if state.status != "running":
        return refuse(state, "run_paused")
    if command.code not in _COUNTED_REJECTIONS:
        return ApplyResult(state=state)
    count = _streak(state, slot.id) + 1
    updated = _set_streak(state, slot.id, count)
    if count >= state.rejected_call_limit:
        updated = record_pause(updated, "rejected_calls", command.code, slot.id)
    return ApplyResult(state=updated.model_copy(update={"seq": state.seq + 1}))


def note_runner_lost(state: RunState, command: RunnerLost) -> ApplyResult:
    """One loss per runner incarnation: mark the turn and wake the slot.

    A loss already receipted is answered with its receipt. The fourth loss of one
    generation pauses ``infra`` / ``infra.runner_lost`` instead of waking. Only a
    working slot of the loss's generation can lose its runner.
    """
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    key = runner_loss_key(
        command.session_id,
        command.generation,
        command.runner_id,
        command.fact_key,
        slot.connection_epoch,
    )
    if _has_receipt(state, key):
        return ApplyResult(state=state, receipt_key=key)
    if command.generation != slot.session_generation:
        return refuse(state, "slot.superseded")
    if slot.status in _HANDED_OFF:
        return refuse(state, "slot.closed")
    if slot.status != "working":
        return refuse(state, "slot.not_ready")
    if reports_an_ended_outage(slot, command.runner_id, command.observed_at):
        # The key stays free: it names this epoch's outage, which has not happened yet.
        return ApplyResult(state=state)
    failed_turn = command.fact_key or f"turn:{command.session_id}:{command.generation}:None"
    payload: dict[str, JsonValue] = {
        "session_id": command.session_id,
        "generation": command.generation,
        "runner_id": command.runner_id,
    }
    return _lose_runner(state, slot, failed_turn, payload, (key,))


def note_usage_limited(
    state: RunState, command: UsageLimited, now: datetime, policy: TimerPolicy
) -> ApplyResult:
    """Pause ``plan_limit`` and arm the ``plan.usage_limit`` probe. No account switch.

    A slot that already handed off refuses a fact it has not receipted: ``slot.closed``.
    """
    if _has_receipt(state, command.fact_key):
        return ApplyResult(state=state, receipt_key=command.fact_key)
    slot = find_slot(state, command.slot_id)
    if slot is not None and slot.status in _HANDED_OFF:
        return refuse(state, "slot.closed")
    if slot is None:
        return refuse_unknown(state)
    if _fact_is_stale(slot, command.fact_key):
        return refuse(state, "slot.superseded")
    cause = pause_for("plan.usage_limit", slot.id)
    if cause is None:
        return refuse(state, "not_supported")
    table = outcomes("plan.usage_limit", slot.id, now, policy)
    paused = record_pause(state, cause.reason, cause.detail, cause.subject)
    armed = arm_plan_probe(paused, slot.id, slot.session_generation, now, policy)
    armed = _pin_plan_probe_due(armed, slot.id, command.resets_at)
    return _commit_outbox(
        armed,
        base=state,
        table=table,
        receipt_key=command.fact_key,
        payload={"detail": "plan.usage_limit"},
    )


def note_waiting_without_elicitation(
    state: RunState, command: WaitingWithoutElicitation
) -> ApplyResult:
    """Audit no-op: same state, no rejection, no effects, and no pause."""
    del command
    return ApplyResult(state=state)


def note_session_failed(
    state: RunState, command: SessionFailed, now: datetime, policy: TimerPolicy
) -> ApplyResult:
    """Mark the slot's failed turn, keep or arm its ladder, and apply that class's pause.

    A receipted fact answers with its receipt. Otherwise a slot that already handed off
    refuses ``slot.closed``, runner loss included. A ladder still live after ``now`` is
    kept, so a re-prompted turn that fails again does not restart it; the ``arm_timer``
    effects are emitted only when arming. Runner loss already emits one ``runner_lost``
    effect. ``outcomes`` describes that same kind, and this path does not emit a second
    copy.
    """
    if _has_receipt(state, command.fact_key):
        return ApplyResult(state=state, receipt_key=command.fact_key)
    slot = find_slot(state, command.slot_id)
    if slot is not None and slot.status in _HANDED_OFF:
        return refuse(state, "slot.closed")
    if command.failure_class == "infra.runner_lost":
        if state.rules < RULES:
            from coral.engine.previous_rules import session_runner_lost

            return session_runner_lost(state, command, now, policy)
        return _session_runner_lost(state, command, now, policy)
    if slot is None:
        return refuse_unknown(state)
    if _fact_is_stale(slot, command.fact_key):
        return refuse(state, "slot.superseded")
    cause = pause_for(command.failure_class, slot.id)
    if cause is None and command.failure_class != "infra.transient":
        return refuse(state, "not_supported")
    table = outcomes(command.failure_class, slot.id, now, policy)
    updated = mark_failed_turn(state, slot.id, command.fact_key)
    armed = True
    if command.failure_class == "infra.transient":
        updated, armed = _arm_infra_unless_live(updated, slot, now, policy)
    elif cause is not None and cause.reason == "plan_limit":
        armed = not has_live_timer(updated, PLAN_PROBE, slot.id, now)
        if armed:
            # A past-due probe that has not fired yet must not clear the new pause at once.
            updated = drop_slot_backoff(updated, (slot.id,), (PLAN_PROBE,))
            updated = arm_plan_probe(updated, slot.id, slot.session_generation, now, policy)
            updated = _pin_plan_probe_due(updated, slot.id, command.resets_at)
    if not armed:
        table = tuple(effect for effect in table if effect.kind != "arm_timer")
    if cause is not None:
        updated = record_pause(updated, cause.reason, cause.detail, cause.subject)
    return _commit_outbox(
        updated,
        base=state,
        table=table,
        receipt_key=command.fact_key,
        payload={"failure_class": command.failure_class},
    )


def note_infra_exhausted(state: RunState, command: InfraBackoffExhausted) -> ApplyResult:
    """Pause ``infra`` and disarm that slot's backoff timers."""
    kept = tuple(
        timer
        for timer in state.timers
        if timer.kind != INFRA_BACKOFF or timer.subject != command.slot_id
    )
    paused = record_pause(
        state.model_copy(update={"timers": kept}),
        "infra",
        "infra.transient",
        command.slot_id,
    )
    return ApplyResult(state=paused.model_copy(update={"seq": state.seq + 1}))


def apply_timer_due(
    graph: CompiledGraph,
    state: RunState,
    command: TimerDue,
    now: datetime,
    policy: TimerPolicy,
) -> ApplyResult:
    """Fire one due timer. An unknown, disarmed or not yet due key is an audit no-op."""
    timer = find_timer(state, command.timer_key)
    if timer is None or timer.due_at > now:
        return ApplyResult(state=state)
    if timer.kind in {INFRA_BACKOFF, PLAN_PROBE} and _timer_is_stale(state, timer):
        kept = tuple(item for item in state.timers if item.key != timer.key)
        dropped = state.model_copy(update={"timers": kept, "seq": state.seq + 1})
        return ApplyResult(state=dropped)
    if timer.kind in WATCHDOG_KINDS:
        return _watchdog_due(state, timer, now)
    if timer.kind == INFRA_BACKOFF:
        return _infra_due(state, timer)
    if timer.kind == PLAN_PROBE:
        return _plan_due(graph, state, timer, now, policy)
    if timer.kind == ORCHESTRATOR_BACKOFF:
        return _orchestrator_due(state, timer)
    return ApplyResult(state=state)


def _advance_closed(graph: CompiledGraph, state: RunState) -> tuple[RunState, tuple[Effect, ...]]:
    """Finish pending closes, open targets the cap refused, then closed activations' forwards.

    A close that reported pending input finishes on every return to running. A choice,
    a gate answer, and a join arrival are already recorded when the cap pauses, so
    those opens are replayed from that receipt. Back arrows and failure arrows are left
    alone: a back arrow would bump its loop counter. A target that already has an
    activation at this scope is not opened again. A step routed by label that closed
    while paused follows its stored label once, back arrow included.
    """
    if state.status != "running":
        return state, ()
    state, finished = finish_pending_closes(graph, state)
    effects: list[Effect] = list(finished)
    if state.status != "running":
        return state, tuple(effects)
    state, opened = _open_refused(graph, state)
    effects.extend(opened)
    sources = tuple(
        item
        for item in state.activations
        if item.status == "closed" and item.outcome == "completed"
    )
    for source in sources:
        if state.status != "running":
            break
        state, routed = route_closed_step(state, graph, source)
        effects.extend(routed)
        for arrow in graph.arrows:
            if arrow.source != source.node_id:
                continue
            if arrow.kind != "forward" or arrow.label is not None:
                continue
            if _target_is_open(state, graph, arrow, source):
                continue
            state, spawned, _receipt = traverse_arrow(
                state,
                graph,
                arrow,
                item_path=source.item_path,
                iteration_path=source.iteration_path,
            )
            effects.extend(spawned)
            if state.status != "running":
                return state, tuple(effects)
    return state, tuple(effects)


def _watchdog_due(state: RunState, timer: Timer, now: datetime) -> ApplyResult:
    """Emit the newest stage already due once, and disarm only the stages already due.

    The reminder comes at its own due time and the alert at its own, later one.
    """
    due = [
        item
        for item in state.timers
        if item.subject == timer.subject and item.kind in WATCHDOG_KINDS and item.due_at <= now
    ]
    newest = max(due, key=lambda item: item.stage)
    stage_name = "alert" if newest.stage >= 2 else "reminder"
    seq = state.seq + 1
    effect = _effect(
        state,
        seq,
        "notify",
        timer.subject,
        {"kind": "watchdog", "stage": stage_name},
    )
    kept = tuple(item for item in state.timers if item not in due)
    decisions = _mark_decision(state, timer.subject, newest.stage)
    changes: dict[str, object] = {
        "timers": kept,
        "seq": seq,
        "effects": (*state.effects, effect),
    }
    if decisions != state.decisions:
        changes["decisions"] = decisions
    return ApplyResult(state=state.model_copy(update=changes), effects=(effect,))


def _infra_due(state: RunState, timer: Timer) -> ApplyResult:
    """Stages 1 and 2 re-prompt a failed turn. Stage 3 pauses ``infra`` if it keeps failing.

    A slot that is not working, that holds, or that waits on its fourth-loss pause only
    disarms the stage. Stage 3 pauses only while the slot is marked failed or its
    re-prompt is undelivered: a re-prompted turn that is still running is left alone.
    """
    kept = tuple(item for item in state.timers if item.key != timer.key)
    base = state.model_copy(update={"timers": kept, "seq": state.seq + 1})
    slot = find_slot(base, timer.subject)
    if slot is None or slot.status != "working" or not _ladder_allowed(base, slot.id):
        return ApplyResult(state=base)
    if timer.stage < 3:
        nudged, effects = _reprompt(base, "backoff", only=slot.id)
        return ApplyResult(state=nudged, effects=effects)
    if slot.failed_turn is None and not awaiting_effect(base, slot.id):
        return ApplyResult(state=base)
    return ApplyResult(state=record_pause(base, "infra", "infra.transient", timer.subject))


def _orchestrator_due(state: RunState, timer: Timer) -> ApplyResult:
    """Stages 1 and 2 ask for re-asks; stage 3 pauses ``infra`` for the run.

    A stage of a replaced generation, or of a run that is not running, only disarms.
    """
    kept = tuple(item for item in state.timers if item.key != timer.key)
    seq = state.seq + 1
    base = state.model_copy(update={"timers": kept, "seq": seq})
    if timer.generation < state.orchestrator_generation or state.status != "running":
        return ApplyResult(state=base)
    if timer.stage >= 3:
        return ApplyResult(state=record_pause(base, "infra", "orchestrator:infra.transient", ""))
    effect = _effect(
        state,
        seq,
        "notify",
        ORCHESTRATOR_SUBJECT,
        {"kind": "orchestrator_backoff", "stage": timer.stage},
    )
    notified = base.model_copy(update={"effects": (*base.effects, effect)})
    return ApplyResult(state=notified, effects=(effect,))


def _drop_orchestrator_backoff(state: RunState) -> RunState:
    return drop_slot_backoff(state, (ORCHESTRATOR_SUBJECT,), (ORCHESTRATOR_BACKOFF,))


def _plan_due(
    graph: CompiledGraph, state: RunState, timer: Timer, now: datetime, policy: TimerPolicy
) -> ApplyResult:
    """Clear ``plan_limit``, arm the next probe, and re-prompt once the run is running.

    A due with no such cause only disarms its own key, so a probe left from an earlier
    limit never blocks the next one.
    """
    if not any(cause.reason == "plan_limit" for cause in state.causes):
        kept = tuple(item for item in state.timers if item.key != timer.key)
        return ApplyResult(state=state.model_copy(update={"timers": kept, "seq": state.seq + 1}))
    rearmed, row = rearm_plan_probe(state, timer, now, policy)
    seq = state.seq + 1
    run_id = state.run_id if isinstance(state.run_id, str) else ""
    probe = assign_effect_keys(
        (arm_timer_effect(row.kind, row.subject, row.stage, row.due_at),),
        run_id,
        seq,
    )
    cleared = _drop_causes(rearmed, frozenset({"plan_limit"})).model_copy(
        update={"seq": seq, "effects": (*rearmed.effects, *probe)}
    )
    spawned: tuple[Effect, ...] = ()
    if cleared.status == "running":
        cleared, spawned = _advance_closed(graph, cleared)
    nudges: tuple[Effect, ...] = ()
    if cleared.status == "running":
        cleared, nudges = _reprompt(cleared, "resume")
    return ApplyResult(state=cleared, effects=(*probe, *spawned, *nudges))


def _mark_decision(state: RunState, subject: str, stage: int) -> tuple[Decision, ...]:
    """Move an open decision to ``reminded`` or ``escalated``. Gates have no such status."""
    status = "escalated" if stage >= 2 else "reminded"
    return tuple(
        item.model_copy(update={"status": status})
        if item.activation_id == subject and item.status != "decided"
        else item
        for item in state.decisions
    )


def _drop_causes(
    state: RunState, reasons: frozenset[PauseReason] | set[PauseReason] | frozenset[str] | set[str]
) -> RunState:
    return _without_causes(state, lambda cause: cause.reason in reasons)


def _without_causes(state: RunState, dropped: Callable[[PauseCause], bool]) -> RunState:
    """Drop the causes ``dropped`` selects; a paused run with none left runs again."""
    remaining = tuple(cause for cause in state.causes if not dropped(cause))
    status = "running" if not remaining and state.status == "paused" else state.status
    if remaining == state.causes and status == state.status:
        return state
    return state.model_copy(update={"causes": remaining, "status": status})


def _retry_slots(state: RunState, owner_id: str, seq: int) -> tuple[RunState, tuple[Effect, ...]]:
    """Bump each slot of ``owner_id`` and hold it ``recovery.restarting`` for its restart."""
    expected_head = _expected_head(state)
    slots = []
    effects: list[Effect] = []
    restarting: list[str] = []
    for slot in state.slots:
        if slot.activation_id != owner_id:
            slots.append(slot)
            continue
        generation = slot.session_generation + 1
        # The new session starts without the previous generation's handoff.
        slots.append(
            slot.model_copy(
                update={
                    "status": "pending",
                    "session_generation": generation,
                    "handoff": None,
                    "handoff_label": None,
                    "pending_input": False,
                    "failed_turn": None,
                    "nudges": 0,
                    "wakes": 0,
                    "connection_epoch": 0,
                    "retired_runners": (),
                    "outage_ended_at": None,
                }
            )
        )
        effects.append(
            _effect(
                state,
                seq,
                "retry_step",
                slot.id,
                {
                    "generation": generation,
                    "phases": [str(phase) for phase in _RETRY_PHASES],
                    "expected_head": expected_head,
                },
            )
        )
        restarting.append(slot.id)
    updated = state.model_copy(update={"slots": tuple(slots)})
    for slot_id in restarting:
        updated = record_pause(updated, "infra", RESTARTING_DETAIL, slot_id)
    return updated, tuple(effects)


def _expected_head(state: RunState) -> str | None:
    """The newest commit the run recorded: a close's commit, or the head a restart kept.

    A reader's close has none. A restart keeps the head it verified, which may be a commit
    its step's own close made but never reported.
    """
    fields = {
        effect.effect_key: "commit" if effect.kind == "close_slot" else "head"
        for effect in state.effects
        if effect.kind in ("close_slot", "retry_step")
    }
    for receipt in reversed(state.receipts):
        field = fields.get(receipt.key)
        commit = None if field is None else receipt.payload.get(field)
        if isinstance(commit, str) and commit:
            return commit
    return None


def _cause_activation(state: RunState, subject: str) -> Activation | None:
    """The activation a cause names: its slot's, itself, or its node's newest."""
    if not subject:
        return None
    slot = find_slot(state, subject)
    if slot is not None:
        return find_activation(state, slot.activation_id)
    owner = find_activation(state, subject)
    if owner is not None:
        return owner
    return next((item for item in reversed(state.activations) if item.node_id == subject), None)


def _resolves_to(state: RunState, subject: str, owner_id: str) -> bool:
    owner = _cause_activation(state, subject)
    return owner is not None and owner.id == owner_id


def _restarting_cause(slot_id: str) -> PauseCause:
    return PauseCause(reason="infra", detail=RESTARTING_DETAIL, subject=slot_id)


def _host_offline_cause(slot_id: str) -> PauseCause:
    return PauseCause(reason="infra", detail=HOST_OFFLINE_DETAIL, subject=slot_id)


def _release_hold(state: RunState, slot_id: str) -> RunState:
    """Drop the slot's host-offline hold, if it has one."""
    hold = _host_offline_cause(slot_id)
    return _without_causes(state, lambda cause: cause == hold)


def _wake_in_flight(state: RunState, slot_id: str) -> bool:
    """Whether a wake of the slot's current generation has no result yet."""
    slot = find_slot(state, slot_id)
    if slot is None:
        return False
    receipted = {receipt.key for receipt in state.receipts}
    return any(
        effect.kind == "runner_lost"
        and effect.subject == slot_id
        and effect.effect_key not in receipted
        and effect_generation(effect) == slot.session_generation
        for effect in state.effects
    )


def _slot_holds(state: RunState, slot_id: str) -> bool:
    return any(holds_slot(cause) and cause.subject == slot_id for cause in state.causes)


def _ladder_allowed(state: RunState, slot_id: str) -> bool:
    """No infra stage may re-prompt a held slot, one paused for its fourth loss, or one
    whose wake is in flight: the wake's own result decides what comes next."""
    lost = PauseCause(reason="infra", detail=RUNNER_LOST_DETAIL, subject=slot_id)
    if _slot_holds(state, slot_id) or lost in state.causes:
        return False
    return state.rules < RULES or not _wake_in_flight(state, slot_id)


def _record_wake(
    state: RunState, slot_id: str, effect: Effect, payload: dict[str, JsonValue]
) -> RunState:
    """Remember the runner a relaunch replaced and when the wake saw the runner back."""
    slot = find_slot(state, slot_id)
    outcome = payload.get("outcome")
    if slot is None or outcome not in {"runner_back", "relaunched"}:
        return state
    changes: dict[str, object] = {}
    lost = effect.payload.get("runner_id")
    if outcome == "relaunched" and isinstance(lost, str) and lost not in slot.retired_runners:
        changes["retired_runners"] = (*slot.retired_runners, lost)
    seen = _aware_time(payload.get("seen_at"))
    if seen is not None and (slot.outage_ended_at is None or seen > slot.outage_ended_at):
        changes["outage_ended_at"] = seen
    return map_slot(state, slot_id, **changes) if changes else state


def _aware_time(value: JsonValue | None) -> datetime | None:
    """An ISO-8601 time with a zone, or ``None`` for anything else."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return None
    return parsed


def _end_outage(state: RunState, slot_id: str) -> RunState:
    """Start the slot's next connection epoch: its runner's next loss is a new one."""
    slot = find_slot(state, slot_id)
    if slot is None:
        return state
    return map_slot(state, slot_id, connection_epoch=slot.connection_epoch + 1)


def _run_id(state: RunState) -> str:
    return state.run_id if isinstance(state.run_id, str) else ""


def _reset_attempts(state: RunState, owner_id: str) -> tuple[AttemptCount, ...]:
    return tuple(
        item.model_copy(update={"used": 0}) if item.activation_id == owner_id else item
        for item in state.attempts
    )


def _streak(state: RunState, slot_id: str) -> int:
    for item in state.reject_streaks:
        if item.slot_id == slot_id:
            return item.count
    return 0


def _set_streak(state: RunState, slot_id: str, count: int) -> RunState:
    found = False
    rows = []
    for item in state.reject_streaks:
        if item.slot_id == slot_id:
            rows.append(item.model_copy(update={"count": count}))
            found = True
        else:
            rows.append(item)
    if not found:
        from coral.engine.types import RejectStreak

        rows.append(RejectStreak(slot_id=slot_id, count=count))
    return state.model_copy(update={"reject_streaks": tuple(rows)})


def _open_refused(graph: CompiledGraph, state: RunState) -> tuple[RunState, tuple[Effect, ...]]:
    """Open each scope the activation cap refused and this resume can now afford."""
    from coral.engine.control import _ensure_waiting, check_liveness
    from coral.engine.machines.activation import open_node

    effects: list[Effect] = []
    for node_id, item_path, iteration_path, waiting in _refused_opens(state):
        if state.status != "running":
            break
        owner = activation_id(node_id, item_path, iteration_path)
        if any(item.id == owner for item in state.activations):
            continue
        if waiting:
            state = check_liveness(
                _ensure_waiting(state, graph, node_id, item_path, iteration_path),
                graph,
            )
            continue
        state, spawned = open_node(
            state,
            graph,
            node_id,
            item_path=item_path,
            iteration_path=iteration_path,
        )
        effects.extend(spawned)
    return state, tuple(effects)


def _refused_opens(
    state: RunState,
) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...], bool], ...]:
    rows: list[tuple[str, tuple[str, ...], tuple[str, ...], bool]] = []
    for receipt in state.receipts:
        if receipt.payload.get("code") != "activation_cap":
            continue
        node_id = receipt.payload.get("node_id")
        if not isinstance(node_id, str):
            continue
        rows.append(
            (
                node_id,
                _path(receipt.payload.get("item_path")),
                _path(receipt.payload.get("iteration_path")),
                receipt.payload.get("waiting") is True,
            )
        )
    return tuple(rows)


def _path(value: JsonValue | None) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    parts = tuple(part for part in value if isinstance(part, str))
    if len(parts) != len(value):
        return ()
    return parts


def _target_is_open(
    state: RunState, graph: CompiledGraph, arrow: CompiledArrow, source: Activation
) -> bool:
    from coral.engine.control import _exit_path

    path = _exit_path(graph, arrow, source.iteration_path)
    head = next((loop for loop in graph.analysis.loops if loop.head == arrow.target), None)
    if head is not None:
        prefix = f"{head.back_arrow_id}:"
        if not any(part.startswith(prefix) for part in path):
            return any(
                item.node_id == arrow.target
                and item.item_path == source.item_path
                and _loop_scope(item.iteration_path, path, prefix)
                for item in state.activations
            )
    owner = activation_id(arrow.target, source.item_path, path)
    return any(item.id == owner for item in state.activations)


def _loop_scope(actual: tuple[str, ...], base: tuple[str, ...], prefix: str) -> bool:
    if actual == base:
        return True
    return len(actual) == len(base) + 1 and actual[:-1] == base and actual[-1].startswith(prefix)


def _reprompt(
    state: RunState, reason: str, *, only: str | None = None
) -> tuple[RunState, tuple[Effect, ...]]:
    """Nudge each slot whose turn failed or that stopped without a handoff, once.

    That is a working slot with ``failed_turn``, or an evaluating slot with no handoff,
    whose latest nudge is delivered (``awaiting_effect``). Its mark is cleared. ``only``
    limits it to one slot.
    """
    effects: list[Effect] = []
    slots: list[Slot] = []
    for slot in state.slots:
        failed = slot.status == "working" and slot.failed_turn is not None
        stopped = slot.status == "evaluating" and slot.handoff is None
        if (only is not None and slot.id != only) or not (failed or stopped):
            slots.append(slot)
            continue
        if awaiting_effect(state, slot.id):
            slots.append(slot)
            continue
        payload: dict[str, JsonValue] = {"fact_key": slot.failed_turn or "", "reason": reason}
        effects.append(_effect(state, state.seq, "nudge", slot.id, payload))
        slots.append(slot.model_copy(update={"failed_turn": None}))
    if not effects:
        return state, ()
    updated = state.model_copy(
        update={"slots": tuple(slots), "effects": (*state.effects, *effects)}
    )
    return updated, tuple(effects)


def _arm_infra_unless_live(
    state: RunState, slot: Slot, now: datetime, policy: TimerPolicy
) -> tuple[RunState, bool]:
    """Arm stages 1-3 unless the slot's ladder still has a stage due after ``now``."""
    if has_live_timer(state, INFRA_BACKOFF, slot.id, now):
        return state, False
    return arm_infra_backoff(state, slot.id, slot.session_generation, now, policy), True


def _fact_is_stale(slot: Slot, fact_key: str) -> bool:
    """True when the turn key names an older session generation."""
    generation = turn_key_generation(fact_key)
    return generation is not None and generation < slot.session_generation


def _timer_is_stale(state: RunState, timer: Timer) -> bool:
    """True when this slot timer belongs to a generation retry already replaced."""
    slot = find_slot(state, timer.subject)
    return slot is not None and timer.generation < slot.session_generation


def _session_runner_lost(
    state: RunState, command: SessionFailed, now: datetime, policy: TimerPolicy
) -> ApplyResult:
    """Receipt the turn and the loss key so one lost runner emits one effect.

    Every loss marks the failed turn. A new loss wakes the slot and arms no infra stage:
    the wake's result re-prompts it. A loss of a runner already reported lost records
    only the turn's receipt, and arms the ladder (unless one is live) only when no wake
    of the slot is out.
    """
    if _has_receipt(state, command.fact_key):
        return ApplyResult(state=state, receipt_key=command.fact_key)
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if _fact_is_stale(slot, command.fact_key):
        return refuse(state, "slot.superseded")
    if reports_an_ended_outage(slot, command.runner_id, command.observed_at):
        return receipt_only(state, command.fact_key, {"failure_class": "infra.runner_lost"})
    session_id, generation = _session_from_turn_key(command.fact_key, slot.session_generation)
    key = runner_loss_key(
        session_id, generation, command.runner_id, command.fact_key, slot.connection_epoch
    )
    if _has_receipt(state, key):
        marked = mark_failed_turn(state, slot.id, command.fact_key)
        if _ladder_allowed(state, slot.id):
            marked, _armed = _arm_infra_unless_live(marked, slot, now, policy)
        return receipt_only(marked, command.fact_key, {"failure_class": "infra.runner_lost"})
    payload: dict[str, JsonValue] = {
        "session_id": session_id,
        "generation": generation,
        "runner_id": command.runner_id,
    }
    return _lose_runner(state, slot, command.fact_key, payload, (key, command.fact_key))


def _pin_plan_probe_due(state: RunState, slot_id: str, resets_at: float | None) -> RunState:
    """When the harness reported a reset time, fire the plan probe at ``resets_at + 60s``."""
    if resets_at is None:
        return state
    due = datetime.fromtimestamp(resets_at, tz=UTC) + timedelta(seconds=60)
    timers = []
    for timer in state.timers:
        if timer.kind == PLAN_PROBE and timer.subject == slot_id:
            timers.append(timer.model_copy(update={"due_at": due}))
        else:
            timers.append(timer)
    return state.model_copy(update={"timers": tuple(timers)})


def _lose_runner(
    state: RunState,
    slot: Slot,
    failed_turn: str,
    payload: dict[str, JsonValue],
    receipt_keys: tuple[str, ...],
) -> ApplyResult:
    """Mark the turn, then wake the slot, or pause once it used its wakes this generation.

    The wake, or the pause, replaces the infra ladder, so no stage re-prompts the slot
    while it waits: the wake's result re-prompts it.
    """
    seq = state.seq + 1
    receipts = tuple(
        Receipt(key=key, payload=dict(payload)) for key in dict.fromkeys(receipt_keys)
    )
    marked = mark_failed_turn(state, slot.id, failed_turn)
    if slot.wakes >= MAX_WAKES:
        unladdered = drop_slot_backoff(marked, (slot.id,), (INFRA_BACKOFF,))
        paused = record_pause(unladdered, "infra", RUNNER_LOST_DETAIL, slot.id)
        stopped = paused.model_copy(update={"seq": seq, "receipts": (*paused.receipts, *receipts)})
        return ApplyResult(state=stopped, receipt_key=receipt_keys[0])
    unladdered = drop_slot_backoff(marked, (slot.id,), (INFRA_BACKOFF,))
    woken = map_slot(unladdered, slot.id, wakes=slot.wakes + 1)
    effect = _effect(state, seq, "runner_lost", slot.id, payload)
    updated = woken.model_copy(
        update={
            "seq": seq,
            "effects": (*woken.effects, effect),
            "receipts": (*woken.receipts, *receipts),
        }
    )
    return ApplyResult(state=updated, effects=(effect,), receipt_key=receipt_keys[0])


def _session_from_turn_key(fact_key: str, fallback_generation: int) -> tuple[str, int]:
    """``turn:{session}:{generation}:{tail}``. The tail may contain colons.

    A non-integer generation uses the fallback. The session id is the first field.
    """
    prefix = "turn:"
    if not fact_key.startswith(prefix):
        return "", fallback_generation
    parts = fact_key[len(prefix) :].split(":", 2)
    if len(parts) != 3:
        return "", fallback_generation
    session_id, generation_text, _tail = parts
    if generation_text == "None":
        return session_id, fallback_generation
    try:
        return session_id, int(generation_text)
    except ValueError:
        return session_id, fallback_generation


def _commit_outbox(
    updated: RunState,
    *,
    base: RunState,
    table: tuple[Effect, ...],
    receipt_key: str,
    payload: dict[str, JsonValue],
) -> ApplyResult:
    """Store ``table`` with keys from ``base`` and receipt ``receipt_key``."""
    seq = base.seq + 1
    run_id = base.run_id if isinstance(base.run_id, str) else ""
    effects = assign_effect_keys(table, run_id, seq)
    receipt = Receipt(key=receipt_key, payload=payload)
    committed = updated.model_copy(
        update={
            "seq": seq,
            "effects": (*updated.effects, *effects),
            "receipts": (*updated.receipts, receipt),
        }
    )
    return ApplyResult(state=committed, effects=effects, receipt_key=receipt_key)


def _has_receipt(state: RunState, key: str) -> bool:
    return any(item.key == key for item in state.receipts)


def _effect(
    state: RunState, seq: int, kind: str, subject: str, payload: dict[str, JsonValue]
) -> Effect:
    run_id = state.run_id if isinstance(state.run_id, str) else ""
    return Effect(
        effect_key=effect_key(run_id, seq, kind, subject),
        kind=kind,
        subject=subject,
        payload=payload,
    )
