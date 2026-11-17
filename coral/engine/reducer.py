"""Pure transition: copy state, dispatch, commit or reject."""

from __future__ import annotations

from datetime import datetime

from coral.engine.lifecycle import (
    apply_timer_due,
    cancel_run,
    note_infra_exhausted,
    note_rejection,
    note_runner_lost,
    note_session_failed,
    note_usage_limited,
    note_waiting_without_elicitation,
    pause_run,
    resume_run,
    retry_step,
)
from coral.engine.machines import (
    answer_gate,
    choose_arrow,
    complete_effect,
    evaluate_handoff,
    note_blocked,
    note_evidence_missing,
    note_post_close,
    receive_handoff,
    start_run,
)
from coral.engine.machines.run import refuse, refuse_unknown
from coral.engine.machines.slot import guard_handoff, note_turn_ended
from coral.engine.projection import project, view_patch
from coral.engine.timers import sync_watchdogs
from coral.engine.types import (
    TERMINAL_STATUSES,
    AnswerGate,
    ApplyResult,
    CancelRun,
    ChooseArrow,
    Effect,
    EffectCompleted,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    InfraBackoffExhausted,
    Input,
    LogEntry,
    PauseRun,
    PostCloseActivity,
    Receipt,
    RejectionObserved,
    ResumeRun,
    RetryStep,
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
    if isinstance(command, StartRun):
        return start_run(graph, state, command, config)
    if state.status == "cancelled" and isinstance(
        command, (AnswerGate, ChooseArrow, HandoffReceived, HandoffEvaluated)
    ):
        return refuse(state, "run_cancelled")
    if isinstance(command, AnswerGate):
        return answer_gate(graph, state, command)
    if isinstance(command, ChooseArrow):
        return choose_arrow(graph, state, command)
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
        return retry_step(graph, state, command)
    if isinstance(command, TimerDue):
        return apply_timer_due(graph, state, command, now, config.timer_policy)
    if isinstance(command, RejectionObserved):
        return note_rejection(state, command)
    if isinstance(command, TurnEnded):
        return note_turn_ended(state, command)
    if isinstance(command, RunnerLost):
        return note_runner_lost(state, command)
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
    return complete_effect(graph, state, effect, command)


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
