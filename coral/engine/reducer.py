"""Pure transition: copy state, dispatch, commit or reject."""

from __future__ import annotations

from datetime import datetime

from coral.engine.lifecycle import (
    apply_timer_due,
    cancel_run,
    complete_restart,
    complete_wake,
    fail_restart,
    fail_wake,
    note_infra_exhausted,
    note_rejection,
    note_runner_held,
    note_runner_hold_ended,
    note_runner_lost,
    note_session_failed,
    note_usage_limited,
    note_waiting_without_elicitation,
    orchestrator_turn,
    pause_run,
    resume_run,
    retry_run,
    retry_step,
)
from coral.engine.machines import (
    answer_gate,
    choose_arrow,
    complete_effect,
    evaluate_handoff,
    fail_effect,
    note_blocked,
    note_evidence_missing,
    note_post_close,
    receive_handoff,
    start_run,
)
from coral.engine.machines.run import receipt_only, refuse, refuse_unknown
from coral.engine.machines.slot import (
    find_slot,
    guard_handoff,
    is_stale_slot_effect,
    note_turn_ended,
)
from coral.engine.projection import project, view_patch
from coral.engine.timers import sync_watchdogs
from coral.engine.types import (
    TERMINAL_STATUSES,
    AnswerGate,
    ApplyResult,
    AssignAgents,
    AssignTask,
    AwaitAssignment,
    CancelRun,
    ChooseArrow,
    Effect,
    EffectCompleted,
    EffectFailed,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    InfraBackoffExhausted,
    Input,
    LogEntry,
    MessageAgent,
    OrchestratorTurn,
    PauseRun,
    PostCloseActivity,
    Receipt,
    RecordMergeConflict,
    RejectionObserved,
    ResumeRun,
    RetryRun,
    RetryStep,
    RunnerHeld,
    RunnerHoldEnded,
    RunnerLost,
    RunState,
    SessionFailed,
    StartRun,
    TimerDue,
    Transition,
    TurnEnded,
    UsageLimited,
    WaitingWithoutElicitation,
)
from coral.model.ir import CompiledGraph


def transition(
    graph: CompiledGraph,
    state: RunState,
    input: Input,
    now: datetime,
    config: EngineConfig | None = None,
) -> Transition:
    """Apply one input and return the next state plus its log entry."""
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("now must be timezone-aware")
    cfg = config if config is not None else EngineConfig()
    applied = _dispatch(graph, state, input, cfg, now)
    if applied.rejection is None:
        armed = sync_watchdogs(state, applied.state, now, cfg.timer_policy)
        if armed != applied.state:
            applied = ApplyResult(
                state=armed,
                effects=applied.effects,
                receipt_key=applied.receipt_key,
            )
    if applied.rejection is not None or applied.state == state:
        return Transition(
            state=state,
            entry=LogEntry(
                seq=state.seq + 1,
                input=input,
                now=now,
                rejection=applied.rejection,
                effects=(),
                receipt_key=applied.receipt_key,
                patch=(),
            ),
        )
    return Transition(
        state=applied.state,
        entry=LogEntry(
            seq=applied.state.seq,
            input=input,
            now=now,
            effects=applied.effects,
            receipt_key=applied.receipt_key,
            patch=view_patch(project(state), project(applied.state)),
        ),
    )


def _dispatch(
    graph: CompiledGraph,
    state: RunState,
    command: Input,
    config: EngineConfig,
    now: datetime,
) -> ApplyResult:
    if isinstance(command, EffectCompleted):
        return _effect_completed(graph, state, command)
    if isinstance(command, EffectFailed):
        return _effect_failed(state, command)
    if isinstance(command, StartRun):
        return start_run(graph, state, command, config)
    if state.status == "cancelled" and isinstance(
        command,
        (
            AnswerGate,
            AssignAgents,
            AssignTask,
            AwaitAssignment,
            ChooseArrow,
            HandoffReceived,
            HandoffEvaluated,
            MessageAgent,
            RecordMergeConflict,
        ),
    ):
        return refuse(state, "run_cancelled")
    if isinstance(command, AnswerGate):
        return answer_gate(graph, state, command)
    if isinstance(command, ChooseArrow):
        return choose_arrow(graph, state, command)
    if isinstance(command, MessageAgent):
        from coral.engine.machines.message import message_agent

        return message_agent(graph, state, command, now)
    if isinstance(command, AssignAgents):
        from coral.engine.machines.message import assign_agents

        return assign_agents(state, command)
    if isinstance(command, AssignTask):
        from coral.engine.machines.message import assign_task

        return assign_task(state, command)
    if isinstance(command, RecordMergeConflict):
        from coral.engine.machines.message import record_merge_conflict

        return record_merge_conflict(state, command)
    if isinstance(command, AwaitAssignment):
        from coral.engine.machines.message import await_assignment

        return await_assignment(state, command)
    if state.status is None:
        return refuse_unknown(state)
    if isinstance(command, CancelRun):
        if state.status in {"completed", "failed"}:
            return refuse(state, "run_terminal")
        return cancel_run(state)
    if state.status in TERMINAL_STATUSES:
        return refuse(state, "run_terminal")
    if isinstance(command, HandoffReceived):
        return receive_handoff(graph, state, command)
    if isinstance(command, HandoffEvaluated):
        return _evaluate(graph, state, command)
    if isinstance(command, PostCloseActivity):
        return note_post_close(state, command)
    if isinstance(command, PauseRun):
        return pause_run(state, command)
    if isinstance(command, ResumeRun):
        return resume_run(graph, state, command)
    if isinstance(command, RetryStep):
        return retry_step(state, command)
    if isinstance(command, RetryRun):
        return retry_run(graph, state)
    if isinstance(command, OrchestratorTurn):
        return orchestrator_turn(state, command, now, config.timer_policy)
    if isinstance(command, TimerDue):
        return apply_timer_due(graph, state, command, now, config.timer_policy)
    if isinstance(command, RejectionObserved):
        return note_rejection(state, command)
    if isinstance(command, TurnEnded):
        return note_turn_ended(state, command, config)
    if isinstance(command, RunnerLost):
        return note_runner_lost(state, command)
    if isinstance(command, RunnerHeld):
        return note_runner_held(state, command)
    if isinstance(command, RunnerHoldEnded):
        return note_runner_hold_ended(graph, state, command)
    if isinstance(command, UsageLimited):
        return note_usage_limited(state, command, now, config.timer_policy)
    if isinstance(command, WaitingWithoutElicitation):
        return note_waiting_without_elicitation(state, command)
    if isinstance(command, SessionFailed):
        return note_session_failed(state, command, now, config.timer_policy)
    if isinstance(command, InfraBackoffExhausted):
        return note_infra_exhausted(state, command)
    return refuse_unknown(state)


def _evaluate(graph: CompiledGraph, state: RunState, command: HandoffEvaluated) -> ApplyResult:
    if command.outcome == "evidence_missing":
        return note_evidence_missing(graph, state, command)
    if command.outcome == "blocked":
        return note_blocked(graph, state, command)
    if command.outcome != "accepted":
        found = guard_handoff(state, command.slot_id, command.session_generation)
        if isinstance(found, ApplyResult):
            return found
        return refuse_unknown(state)
    return evaluate_handoff(graph, state, command)


def _effect_completed(
    graph: CompiledGraph, state: RunState, command: EffectCompleted
) -> ApplyResult:
    prior = _find_receipt(state, command.effect_key)
    if prior is not None:
        return ApplyResult(state=state, receipt_key=prior.key)
    if state.status is None:
        return refuse_unknown(state)
    if state.status in TERMINAL_STATUSES:
        return refuse(state, "run_terminal")
    effect = _find_effect(state, command.effect_key)
    if effect is None:
        return refuse_unknown(state)
    if effect.kind == "retry_step":
        return complete_restart(graph, state, effect, command)
    if effect.kind == "runner_lost":
        return complete_wake(graph, state, effect, command)
    if effect.kind == "structure.start_item":
        from coral.structure.items import apply_start_item

        return apply_start_item(graph, state, effect)
    if effect.kind == "structure.cancel_region":
        from coral.structure.regions import apply_cancel_region

        return apply_cancel_region(graph, state, effect)
    return complete_effect(graph, state, effect, command)


def _effect_failed(state: RunState, command: EffectFailed) -> ApplyResult:
    prior = _find_receipt(state, command.effect_key)
    if prior is not None:
        return ApplyResult(state=state, receipt_key=prior.key)
    if state.status is None:
        return refuse_unknown(state)
    if state.status in TERMINAL_STATUSES:
        return refuse(state, "run_terminal")
    effect = _find_effect(state, command.effect_key)
    if effect is None:
        return refuse_unknown(state)
    if effect.kind == "retry_step":
        return fail_restart(state, effect, command)
    slot = find_slot(state, effect.subject)
    if slot is not None and is_stale_slot_effect(state, effect, slot):
        # A failure of a generation a retry replaced is kept for audit and pauses nothing.
        return receipt_only(state, effect.effect_key, {"failed": command.code, "stale": True})
    if effect.kind == "runner_lost":
        return fail_wake(state, effect, command)
    return fail_effect(state, effect, command)


def _find_receipt(state: RunState, key: str) -> Receipt | None:
    for receipt in state.receipts:
        if receipt.key == key:
            return receipt
    return None


def _find_effect(state: RunState, key: str) -> Effect | None:
    for effect in state.effects:
        if effect.effect_key == key:
            return effect
    return None
