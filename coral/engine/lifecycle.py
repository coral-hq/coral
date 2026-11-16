"""Pause, resume, cancel, retry, and timer deadlines."""

from __future__ import annotations

from datetime import datetime

from pydantic import JsonValue

from coral.engine.facts import turn_key_generation
from coral.engine.machines.activation import (
    activation_id,
    find_activation,
    replace_activation,
    traverse_arrow,
)
from coral.engine.machines.run import record_pause, refuse, refuse_unknown
from coral.engine.machines.slot import find_slot
from coral.engine.timers import (
    INFRA_BACKOFF,
    PLAN_PROBE,
    WATCHDOG_KINDS,
    arm_infra_backoff,
    arm_plan_probe,
    find_timer,
    rearm_plan_probe,
)
from coral.engine.types import (
    Activation,
    ApplyResult,
    AttemptCount,
    Decision,
    Effect,
    InfraBackoffExhausted,
    PauseReason,
    PauseRun,
    Receipt,
    RejectionObserved,
    ResumeRun,
    RetryStep,
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
_COUNTED_REJECTIONS = frozenset({"handoff.invalid", "tool.illegal"})
_RETRY_PHASES: tuple[str, ...] = (
    "fence_stop",
    "create_unbriefed",
    "salvage_reset",
    "brief",
)


def pause_run(state: RunState, command: PauseRun) -> ApplyResult:
    """Record ``command`` with an empty subject. Priority order lives in ``record_pause``."""
    paused = record_pause(state, command.reason, command.detail, "")
    return ApplyResult(state=paused.model_copy(update={"seq": state.seq + 1}))


def resume_run(graph: CompiledGraph, state: RunState, command: ResumeRun) -> ApplyResult:
    """Clear the causes ResumeRun is allowed to clear. A miss changes nothing."""
    reasons: set[PauseReason] = set()
    for cause in state.causes:
        if cause.reason in _RESUME_REASONS:
            reasons.add(cause.reason)
    store_cap: int | None = None
    if any(cause.reason == "budget" for cause in state.causes):
        if command.cap is not None and command.cap > state.max_activations:
            reasons.add("budget")
            store_cap = command.cap
    if not reasons:
        return refuse(state, "resume_not_allowed")
    updated = _drop_causes(state, reasons)
    changes: dict[str, object] = {"seq": state.seq + 1}
    if store_cap is not None:
        changes["max_activations"] = store_cap
    if "rejected_calls" in reasons:
        changes["reject_streaks"] = tuple(
            item.model_copy(update={"count": 0}) for item in updated.reject_streaks
        )
    updated = updated.model_copy(update=changes)
    effects: tuple[Effect, ...] = ()
    if updated.status == "running":
        updated, effects = _advance_closed(graph, updated)
    return ApplyResult(state=updated, effects=effects)


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


def retry_step(graph: CompiledGraph, state: RunState, command: RetryStep) -> ApplyResult:
    """Reopen one activation. The retry phases are named, not run."""
    owner_id = activation_id(command.node_id, command.item_path, command.iteration_path)
    if find_activation(state, owner_id) is None:
        return refuse_unknown(state)
    if not any(cause.reason in _RETRY_REASONS for cause in state.causes):
        return refuse(state, "resume_not_allowed")
    cleared = _drop_causes(state, _RETRY_REASONS)
    slot_ids = {slot.id for slot in state.slots if slot.activation_id == owner_id}
    cleared = _drop_slot_backoff(cleared, slot_ids)
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
    if retried.status == "running":
        retried, spawned = _advance_closed(graph, retried)
        effects = (*effects, *spawned)
    return ApplyResult(state=retried, effects=effects)


def note_rejection(state: RunState, command: RejectionObserved) -> ApplyResult:
    """Count ``handoff.invalid`` and ``tool.illegal``. The third pauses ``rejected_calls``."""
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if state.status != "running":
        return refuse(state, "run_paused")
    if command.code not in _COUNTED_REJECTIONS:
        return ApplyResult(state=state)
    count = _streak(state, slot.id) + 1
    updated = _set_streak(state, slot.id, count)
    if count >= 3:
        updated = record_pause(updated, "rejected_calls", command.code, slot.id)
    return ApplyResult(state=updated.model_copy(update={"seq": state.seq + 1}))


def note_runner_lost(state: RunState, command: RunnerLost) -> ApplyResult:
    """Emit one ``runner_lost`` effect. Does not pause."""
    key = f"runner:{command.session_id}:{command.generation}"
    if _has_receipt(state, key):
        return ApplyResult(state=state, receipt_key=key)
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if command.generation < slot.session_generation:
        return refuse(state, "slot.superseded")
    payload: dict[str, JsonValue] = {
        "session_id": command.session_id,
        "generation": command.generation,
    }
    return _emit_runner_lost(state, command.slot_id, payload, (key,))


def note_usage_limited(
    state: RunState, command: UsageLimited, now: datetime, policy: TimerPolicy
) -> ApplyResult:
    """Pause ``plan_limit`` and arm the ``plan.usage_limit`` probe. No account switch."""
    if _has_receipt(state, command.fact_key):
        return ApplyResult(state=state, receipt_key=command.fact_key)
    slot = find_slot(state, command.slot_id)
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
    """Emit the outcome-table effects and apply that class's pause.

    Runner loss already emits one ``runner_lost`` effect. ``outcomes`` describes that
    same kind, and this path does not emit a second copy.
    """
    if command.failure_class == "infra.runner_lost":
        return _session_runner_lost(state, command)
    if _has_receipt(state, command.fact_key):
        return ApplyResult(state=state, receipt_key=command.fact_key)
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if _fact_is_stale(slot, command.fact_key):
        return refuse(state, "slot.superseded")
    cause = pause_for(command.failure_class, slot.id)
    if cause is None and command.failure_class != "infra.transient":
        return refuse(state, "not_supported")
    table = outcomes(command.failure_class, slot.id, now, policy)
    updated = state
    if command.failure_class == "infra.transient":
        updated = arm_infra_backoff(updated, slot.id, slot.session_generation, now, policy)
    elif cause is not None and cause.reason == "plan_limit":
        updated = arm_plan_probe(updated, slot.id, slot.session_generation, now, policy)
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
    """Fire one due timer. An unknown or disarmed key is an audit no-op."""
    timer = find_timer(state, command.timer_key)
    if timer is None:
        return ApplyResult(state=state)
    if timer.kind in {INFRA_BACKOFF, PLAN_PROBE} and _timer_is_stale(state, timer):
        kept = tuple(item for item in state.timers if item.key != timer.key)
        dropped = state.model_copy(update={"timers": kept, "seq": state.seq + 1})
        return ApplyResult(state=dropped)
    if timer.kind in WATCHDOG_KINDS:
        return _watchdog_due(state, timer)
    if timer.kind == INFRA_BACKOFF:
        return _infra_due(state, timer)
    if timer.kind == PLAN_PROBE:
        return _plan_due(graph, state, timer, now, policy)
    return ApplyResult(state=state)


def _advance_closed(graph: CompiledGraph, state: RunState) -> tuple[RunState, tuple[Effect, ...]]:
    """Open targets the cap refused, then unlabelled forwards of closed activations.

    A choice, a gate answer, and a join arrival are already recorded when the cap
    pauses, so those opens are replayed from that receipt. Back arrows and failure
    arrows are left alone: a back arrow would bump its loop counter. A target that
    already has an activation at this scope is not opened again.
    """
    if state.status != "running":
        return state, ()
    state, effects_list = _open_refused(graph, state)
    effects: list[Effect] = list(effects_list)
    sources = tuple(
        item
        for item in state.activations
        if item.status == "closed" and item.outcome == "completed"
    )
    for source in sources:
        if state.status != "running":
            break
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


def _watchdog_due(state: RunState, timer: Timer) -> ApplyResult:
    """Emit the newest armed stage once and disarm every watchdog for that subject."""
    armed = [
        item
        for item in state.timers
        if item.subject == timer.subject and item.kind in WATCHDOG_KINDS
    ]
    newest = max(armed, key=lambda item: item.stage)
    stage_name = "alert" if newest.stage >= 2 else "reminder"
    seq = state.seq + 1
    effect = _effect(
        state,
        seq,
        "notify",
        timer.subject,
        {"kind": "watchdog", "stage": stage_name},
    )
    kept = tuple(
        item
        for item in state.timers
        if item.subject != timer.subject or item.kind not in WATCHDOG_KINDS
    )
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
    """Stages 1 and 2 disarm only themselves. Stage 3 pauses ``infra``."""
    kept = tuple(item for item in state.timers if item.key != timer.key)
    base = state.model_copy(update={"timers": kept})
    if timer.stage < 3:
        return ApplyResult(state=base.model_copy(update={"seq": state.seq + 1}))
    paused = record_pause(base, "infra", "infra.transient", timer.subject)
    return ApplyResult(state=paused.model_copy(update={"seq": state.seq + 1}))


def _plan_due(
    graph: CompiledGraph, state: RunState, timer: Timer, now: datetime, policy: TimerPolicy
) -> ApplyResult:
    """Clear ``plan_limit`` and arm the next probe. A due with no such cause is a no-op.

    The due row is disarmed only when it clears the pause. The next probe does not
    fire another one after the pause is gone.
    """
    if not any(cause.reason == "plan_limit" for cause in state.causes):
        return ApplyResult(state=state)
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
    return ApplyResult(state=cleared, effects=(*probe, *spawned))


def _mark_decision(state: RunState, subject: str, stage: int) -> tuple[Decision, ...]:
    """Move an open decision to ``reminded`` or ``escalated``. Gates have no such status."""
    status = "escalated" if stage >= 2 else "reminded"
    return tuple(
        item.model_copy(update={"status": status})
        if item.activation_id == subject and item.status != "decided"
        else item
        for item in state.decisions
    )


def _drop_causes(state: RunState, reasons: frozenset[str] | set[str]) -> RunState:
    remaining = tuple(cause for cause in state.causes if cause.reason not in reasons)
    status = "running" if not remaining and state.status == "paused" else state.status
    if remaining == state.causes and status == state.status:
        return state
    return state.model_copy(update={"causes": remaining, "status": status})


def _retry_slots(state: RunState, owner_id: str, seq: int) -> tuple[RunState, tuple[Effect, ...]]:
    slots = []
    effects: list[Effect] = []
    for slot in state.slots:
        if slot.activation_id != owner_id:
            slots.append(slot)
            continue
        generation = slot.session_generation + 1
        slots.append(
            slot.model_copy(update={"status": "pending", "session_generation": generation})
        )
        effects.append(
            _effect(
                state,
                seq,
                "retry_step",
                slot.id,
                {"generation": generation, "phases": list(_RETRY_PHASES)},
            )
        )
    return state.model_copy(update={"slots": tuple(slots)}), tuple(effects)


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
    if not isinstance(value, list) or any(not isinstance(part, str) for part in value):
        return ()
    return tuple(value)


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


def _drop_slot_backoff(state: RunState, slot_ids: set[str]) -> RunState:
    """Drop infra and plan timers for slots a retry is replacing."""
    kept = tuple(
        timer
        for timer in state.timers
        if timer.kind not in {INFRA_BACKOFF, PLAN_PROBE} or timer.subject not in slot_ids
    )
    if kept == state.timers:
        return state
    return state.model_copy(update={"timers": kept})


def _fact_is_stale(slot: Slot, fact_key: str) -> bool:
    """True when the turn key names an older session generation."""
    generation = turn_key_generation(fact_key)
    return generation is not None and generation < slot.session_generation


def _timer_is_stale(state: RunState, timer: Timer) -> bool:
    """True when this slot timer belongs to a generation retry already replaced."""
    slot = find_slot(state, timer.subject)
    return slot is not None and timer.generation < slot.session_generation


def _receipt_only(state: RunState, key: str, payload: dict[str, JsonValue]) -> ApplyResult:
    """Store ``key`` and emit nothing. A second call returns the receipt."""
    if _has_receipt(state, key):
        return ApplyResult(state=state, receipt_key=key)
    receipt = Receipt(key=key, payload=payload)
    updated = state.model_copy(
        update={"seq": state.seq + 1, "receipts": (*state.receipts, receipt)}
    )
    return ApplyResult(state=updated, receipt_key=key)


def _session_runner_lost(state: RunState, command: SessionFailed) -> ApplyResult:
    """Receipt the turn and the runner key so one loss emits one effect."""
    if _has_receipt(state, command.fact_key):
        return ApplyResult(state=state, receipt_key=command.fact_key)
    slot = find_slot(state, command.slot_id)
    if slot is None:
        return refuse_unknown(state)
    if _fact_is_stale(slot, command.fact_key):
        return refuse(state, "slot.superseded")
    session_id, generation = _session_from_turn_key(command.fact_key, slot.session_generation)
    runner_key = f"runner:{session_id}:{generation}"
    payload: dict[str, JsonValue] = {"session_id": session_id, "generation": generation}
    if _has_receipt(state, runner_key):
        return _receipt_only(state, command.fact_key, {"failure_class": "infra.runner_lost"})
    return _emit_runner_lost(state, slot.id, payload, (runner_key, command.fact_key))


def _emit_runner_lost(
    state: RunState,
    slot_id: str,
    payload: dict[str, JsonValue],
    receipt_keys: tuple[str, ...],
) -> ApplyResult:
    seq = state.seq + 1
    effect = _effect(state, seq, "runner_lost", slot_id, payload)
    receipts = tuple(
        Receipt(key=key, payload=dict(payload)) for key in dict.fromkeys(receipt_keys)
    )
    updated = state.model_copy(
        update={
            "seq": seq,
            "effects": (*state.effects, effect),
            "receipts": (*state.receipts, *receipts),
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
