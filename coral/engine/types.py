"""Frozen run state, inputs, and log records for the workflow reducer."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

RunStatus = Literal["running", "paused", "completed", "failed", "cancelled"]
PauseReason = Literal[
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
]
ActivationStatus = Literal["waiting_join", "ready", "starting", "running", "evaluating", "closed"]
ActivationOutcome = Literal["completed", "skipped", "failed"]
SlotStatus = Literal[
    "pending", "session_created", "briefed", "working", "evaluating", "closing", "closed"
]
DecisionStatus = Literal["requested", "reminded", "escalated", "decided"]
GateStatus = Literal["open", "resolved", "superseded"]
HandoffOutcome = Literal["accepted", "evidence_missing", "blocked"]
TERMINAL_STATUSES: frozenset[RunStatus] = frozenset({"completed", "failed", "cancelled"})
# The reducer rules a run folds with, named by its start entry. A start entry without a
# marker was written before markers existed and keeps folding with the previous rules; an
# unknown marker fails to decode rather than fold with the wrong rules.
Rules = Literal[1, 2]
PREVIOUS_RULES: Final = 1
RULES: Final = 2


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TimerPolicy(_Frozen):
    """Deadlines for watchdogs, infra backoff, and plan probes.

    A plan probe starts at ``plan_probe_start`` and doubles until ``plan_probe_cap``.
    Due times are ``now + delay``. Nothing sleeps.
    """

    watchdog: timedelta = timedelta(minutes=30)
    infra_backoff: tuple[timedelta, timedelta, timedelta] = (
        timedelta(seconds=30),
        timedelta(minutes=2),
        timedelta(minutes=8),
    )
    plan_probe_start: timedelta = timedelta(minutes=5)
    plan_probe_cap: timedelta = timedelta(hours=1)


class EngineConfig(_Frozen):
    max_activations: int = 10_000
    timer_policy: TimerPolicy = Field(default_factory=TimerPolicy)
    runner_grace: timedelta = timedelta(seconds=30)
    # Counted rejections in a row that pause ``rejected_calls``; copied into the run at start.
    rejected_call_limit: int = Field(default=3, ge=1)
    # Turn-end nudges in a row without a handoff before the run pauses ``rejected_calls``.
    nudge_limit: int = Field(default=3, ge=1)


class PauseCause(_Frozen):
    reason: PauseReason
    detail: str
    subject: str


class SlotHandoff(_Frozen):
    slot_id: str
    profile: str
    handoff: str | None = None


class Activation(_Frozen):
    id: str
    node_id: str
    item_path: tuple[str, ...] = ()
    iteration_path: tuple[str, ...] = ()
    status: ActivationStatus
    outcome: ActivationOutcome | None = None
    handoffs: tuple[SlotHandoff, ...] = ()


class Slot(_Frozen):
    id: str
    activation_id: str
    profile: str
    status: SlotStatus
    session_generation: int = 1
    pending_input: bool = False
    drift: bool = False
    handoff: str | None = None
    handoff_label: str | None = None
    # The fact key of a failed turn not yet re-prompted, completed, handed off or retried.
    failed_turn: str | None = None
    # Turn-end nudges sent while running since the last handoff, resume or retry.
    nudges: int = 0
    # Runner losses this generation that emitted a wake; a retry resets it.
    wakes: int = 0
    # Which outage of the slot's runner a loss report is about. Each wake result, or a
    # Resume of the fourth-loss pause, ends one, so the same runner's next loss is new.
    connection_epoch: int = 0
    # Runners this generation's wakes relaunched away from, and when a wake last saw the
    # runner back: a loss report about either belongs to an outage that already ended.
    retired_runners: tuple[str, ...] = ()
    outage_ended_at: datetime | None = None


class Decision(_Frozen):
    activation_id: str
    node_id: str
    status: DecisionStatus
    label: str | None = None
    reason: str | None = None


class GateVisit(_Frozen):
    activation_id: str
    token: str
    visit_no: int
    status: GateStatus
    label: str | None = None
    by: str | None = None
    note: str | None = None


class Arrival(_Frozen):
    item_path: tuple[str, ...] = ()
    iteration_path: tuple[str, ...] = ()
    arrow_id: str
    receipt_key: str


class LoopCounter(_Frozen):
    back_arrow_id: str
    item_path: tuple[str, ...] = ()
    iteration_path: tuple[str, ...] = ()
    pass_index: int = 1


class AttemptCount(_Frozen):
    activation_id: str
    used: int = 0


class RejectStreak(_Frozen):
    slot_id: str
    count: int = 0


class Timer(_Frozen):
    key: str
    kind: str
    scope: str
    subject: str
    generation: int
    stage: int
    due_at: datetime


class Receipt(_Frozen):
    key: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class Effect(_Frozen):
    effect_key: str
    kind: str
    subject: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class RunState(_Frozen):
    status: RunStatus | None = None
    rules: Rules = PREVIOUS_RULES
    run_id: str | None = None
    start_key: str | None = None
    version_hash: str | None = None
    max_activations: int = 10_000
    rejected_call_limit: int = Field(default=3, ge=1)
    seq: int = 0
    causes: tuple[PauseCause, ...] = ()
    activations: tuple[Activation, ...] = ()
    slots: tuple[Slot, ...] = ()
    decisions: tuple[Decision, ...] = ()
    gates: tuple[GateVisit, ...] = ()
    arrivals: tuple[Arrival, ...] = ()
    loop_counters: tuple[LoopCounter, ...] = ()
    attempts: tuple[AttemptCount, ...] = ()
    reject_streaks: tuple[RejectStreak, ...] = ()
    timers: tuple[Timer, ...] = ()
    receipts: tuple[Receipt, ...] = ()
    effects: tuple[Effect, ...] = ()


def empty_state() -> RunState:
    """A run that has not accepted ``StartRun``."""
    return RunState()


def activation_id(
    node_id: str,
    item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
) -> str:
    """``{node}|{item}|{iteration}`` with each path joined by ``/``."""
    return f"{node_id}|{'/'.join(item_path)}|{'/'.join(iteration_path)}"


def slot_id(owner: str, index: int) -> str:
    """Roster slot ``index`` of an activation."""
    return f"{owner}:{index}"


def effect_key(run_id: str, seq: int, kind: str, subject: str) -> str:
    """``{run_id}:{seq}:{kind}:{subject}``."""
    return f"{run_id}:{seq}:{kind}:{subject}"


class StartRun(_Frozen):
    kind: Literal["start_run"] = "start_run"
    run_id: str
    start_key: str
    version_hash: str
    # New runs pass ``RULES``; absent, as in logs written before it, the previous rules.
    rules: Rules = PREVIOUS_RULES


class PauseRun(_Frozen):
    kind: Literal["pause_run"] = "pause_run"
    reason: PauseReason
    detail: str


class ResumeRun(_Frozen):
    kind: Literal["resume_run"] = "resume_run"
    cap: int | None = None


class CancelRun(_Frozen):
    kind: Literal["cancel_run"] = "cancel_run"


class RetryStep(_Frozen):
    kind: Literal["retry_step"] = "retry_step"
    node_id: str
    item_path: tuple[str, ...] = ()
    iteration_path: tuple[str, ...] = ()


class EffectCompleted(_Frozen):
    kind: Literal["effect_completed"] = "effect_completed"
    effect_key: str
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class EffectFailed(_Frozen):
    """An effect that failed for good: ``retryable`` when its retries ran out."""

    kind: Literal["effect_failed"] = "effect_failed"
    effect_key: str
    code: str
    retryable: bool = False


class HandoffReceived(_Frozen):
    kind: Literal["handoff_received"] = "handoff_received"
    slot_id: str
    body: str
    session_generation: int = 1
    # The arrow label a step routed by label chose. Checked when given; unused when blocked.
    label: str | None = None


class HandoffEvaluated(_Frozen):
    kind: Literal["handoff_evaluated"] = "handoff_evaluated"
    slot_id: str
    outcome: HandoffOutcome
    missing: tuple[str, ...] = ()
    session_generation: int = 1


class ChooseArrow(_Frozen):
    kind: Literal["choose_arrow"] = "choose_arrow"
    node_id: str
    label: str
    reason: str
    item_path: tuple[str, ...] = ()
    iteration_path: tuple[str, ...] = ()


class AnswerGate(_Frozen):
    kind: Literal["answer_gate"] = "answer_gate"
    token: str
    label: str
    by: str
    note: str = ""


class TimerDue(_Frozen):
    kind: Literal["timer_due"] = "timer_due"
    timer_key: str


class TurnEnded(_Frozen):
    kind: Literal["turn_ended"] = "turn_ended"
    slot_id: str
    fact_key: str
    origin: str = "engine"


class RunnerLost(_Frozen):
    """A working slot's runner stayed missing past its grace.

    ``fact_key`` is the turn key of the fact that showed it; without a ``runner_id`` its
    tail keys the loss.
    """

    kind: Literal["runner_lost"] = "runner_lost"
    slot_id: str
    session_id: str
    generation: int
    runner_id: str | None = None
    fact_key: str | None = None
    # When the runner was first seen missing.
    observed_at: datetime | None = None


class RunnerHeld(_Frozen):
    """The slot's host is offline: hold the slot until it returns."""

    kind: Literal["runner_held"] = "runner_held"
    slot_id: str
    session_id: str
    generation: int


class RunnerHoldEnded(_Frozen):
    """The held slot's host is back."""

    kind: Literal["runner_hold_ended"] = "runner_hold_ended"
    slot_id: str
    generation: int


class UsageLimited(_Frozen):
    kind: Literal["usage_limited"] = "usage_limited"
    slot_id: str
    fact_key: str
    # Unix epoch seconds when the plan limit lifts; None → backoff probe only.
    resets_at: float | None = None


class WaitingWithoutElicitation(_Frozen):
    kind: Literal["waiting_without_elicitation"] = "waiting_without_elicitation"
    slot_id: str
    fact_key: str


class SessionFailed(_Frozen):
    kind: Literal["session_failed"] = "session_failed"
    slot_id: str
    failure_class: str
    cause: str
    fact_key: str
    # The session's runner when the turn failed, and when the failure was observed.
    runner_id: str | None = None
    observed_at: datetime | None = None
    # Unix epoch seconds when a plan limit lifts; None → backoff probe only.
    resets_at: float | None = None


class PostCloseActivity(_Frozen):
    kind: Literal["post_close_activity"] = "post_close_activity"
    slot_id: str


class RejectionObserved(_Frozen):
    kind: Literal["rejection_observed"] = "rejection_observed"
    slot_id: str
    code: str


class InfraBackoffExhausted(_Frozen):
    kind: Literal["infra_backoff_exhausted"] = "infra_backoff_exhausted"
    slot_id: str


Input = Annotated[
    StartRun
    | PauseRun
    | ResumeRun
    | CancelRun
    | RetryStep
    | EffectCompleted
    | EffectFailed
    | HandoffReceived
    | HandoffEvaluated
    | ChooseArrow
    | AnswerGate
    | TimerDue
    | TurnEnded
    | RunnerLost
    | RunnerHeld
    | RunnerHoldEnded
    | UsageLimited
    | WaitingWithoutElicitation
    | SessionFailed
    | PostCloseActivity
    | RejectionObserved
    | InfraBackoffExhausted,
    Field(discriminator="kind"),
]


class Rejection(_Frozen):
    code: str
    allowed_values: tuple[str, ...] = ()
    mutates: bool = False


class JsonPatch(_Frozen):
    """One JSON Patch operation addressed by a JSON pointer."""

    op: Literal["add", "remove", "replace"]
    path: str
    value: JsonValue | None = None


class LogEntry(_Frozen):
    seq: int
    input: Input
    now: datetime
    rejection: Rejection | None = None
    effects: tuple[Effect, ...] = ()
    receipt_key: str | None = None
    patch: tuple[JsonPatch, ...] = ()


class Transition(_Frozen):
    state: RunState
    entry: LogEntry


class ApplyResult(_Frozen):
    """What a machine handler returns before the reducer builds the log entry."""

    state: RunState
    effects: tuple[Effect, ...] = ()
    receipt_key: str | None = None
    rejection: Rejection | None = None
