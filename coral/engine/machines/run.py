"""Run-level start rules and which input kinds a state accepts."""

from __future__ import annotations

from coral.engine.machines.activation import open_node
from coral.engine.types import (
    TERMINAL_STATUSES,
    ApplyResult,
    EngineConfig,
    PauseCause,
    PauseReason,
    Receipt,
    Rejection,
    RunState,
    StartRun,
)
from coral.model.ir import CompiledGraph

# Highest priority first. The displayed cause is ``causes[0]``.
_PAUSE_ORDER: tuple[PauseReason, ...] = (
    "auth",
    "plan_limit",
    "infra",
    "budget",
    "liveness",
    "failure_path",
    "drift",
    "rejected_calls",
    "authority_revoked",
    "engine_upgrade",
    "user",
)


def start_run(
    graph: CompiledGraph, state: RunState, command: StartRun, config: EngineConfig
) -> ApplyResult:
    """Start an empty run, or return the receipt for the same start key."""
    if state.start_key is not None:
        return _repeat_start(state, command)
    if graph.analysis.unresolved:
        return refuse(state, "graph.unresolved")
    start = next((node for node in graph.nodes if node.kind == "start"), None)
    if start is None:
        return refuse(state, "not_supported")
    receipt = Receipt(
        key=command.start_key,
        payload={"run_id": command.run_id, "version_hash": command.version_hash},
    )
    started = state.model_copy(
        update={
            "seq": state.seq + 1,
            "status": "running",
            "run_id": command.run_id,
            "start_key": command.start_key,
            "version_hash": command.version_hash,
            "max_activations": config.max_activations,
            "receipts": (*state.receipts, receipt),
        }
    )
    opened, effects = open_node(started, graph, start.id)
    return ApplyResult(state=opened, effects=effects, receipt_key=receipt.key)


def accepted_kinds(state: RunState) -> tuple[str, ...]:
    """Input kinds this state can accept. Empty once the run is terminal."""
    if state.status is None:
        return ("start_run",)
    if state.status in TERMINAL_STATUSES:
        return ()
    kinds: list[str] = []
    if _has_pending_effect(state):
        kinds.append("effect_completed")
    if state.status == "running":
        if any(slot.status in {"working", "evaluating"} for slot in state.slots):
            kinds.append("handoff_received")
        if any(slot.status == "evaluating" for slot in state.slots):
            kinds.append("handoff_evaluated")
        if any(decision.status != "decided" for decision in state.decisions):
            kinds.append("choose_arrow")
        if any(visit.status == "open" for visit in state.gates):
            kinds.append("answer_gate")
        if any(slot.status == "closed" for slot in state.slots):
            kinds.append("post_close_activity")
        if state.slots:
            kinds.append("rejection_observed")
    kinds.extend(
        ["pause_run", "cancel_run", "timer_due", "session_failed", "infra_backoff_exhausted"]
    )
    if state.status == "paused":
        kinds.extend(["resume_run", "retry_step"])
    return tuple(kinds)


def record_pause(state: RunState, reason: PauseReason, detail: str, subject: str) -> RunState:
    """Pause with ``reason``. Replace that reason in place, or insert a new one by priority."""
    cause = PauseCause(reason=reason, detail=detail, subject=subject)
    for index, existing in enumerate(state.causes):
        if existing.reason == reason:
            replaced = list(state.causes)
            replaced[index] = cause
            return state.model_copy(update={"status": "paused", "causes": tuple(replaced)})
    rank = _PAUSE_ORDER.index(reason)
    causes: list[PauseCause] = []
    placed = False
    for existing in state.causes:
        if not placed and _PAUSE_ORDER.index(existing.reason) > rank:
            causes.append(cause)
            placed = True
        causes.append(existing)
    if not placed:
        causes.append(cause)
    return state.model_copy(update={"status": "paused", "causes": tuple(causes)})


def refuse(state: RunState, code: str, allowed: tuple[str, ...] = ()) -> ApplyResult:
    return ApplyResult(state=state, rejection=Rejection(code=code, allowed_values=allowed))


def refuse_unknown(state: RunState) -> ApplyResult:
    return refuse(state, "rejected", accepted_kinds(state))


def _repeat_start(state: RunState, command: StartRun) -> ApplyResult:
    if state.start_key == command.start_key and state.version_hash == command.version_hash:
        return ApplyResult(state=state, receipt_key=state.start_key)
    if state.start_key == command.start_key:
        return refuse(state, "start_key_conflict")
    if state.status in TERMINAL_STATUSES:
        return refuse(state, "run_terminal")
    return refuse_unknown(state)


def _has_pending_effect(state: RunState) -> bool:
    done = {receipt.key for receipt in state.receipts}
    return any(effect.effect_key not in done for effect in state.effects)
