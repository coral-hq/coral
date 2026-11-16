"""Domain protocols, exceptions, and frozen dataclasses for Coral persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from coral.db.enum_codecs import RunStatus, WorkKind, WorkStatus
from coral.model.ids import derived_id

# ── Domain Exceptions ────────────────────────────────────────────────────────


class StartKeyConflict(Exception):
    """Start key already exists with a different run spec digest."""


class RunNotFound(LookupError):
    """The requested run was not found in the workspace."""


class RunVersionConflict(Exception):
    """Optimistic concurrency check failed; expected_version != actual_version."""

    def __init__(
        self,
        run_id: str,
        expected_version: int,
        actual_version: int,
        message: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            message
            or (
                f"Run {run_id!r} version conflict: "
                f"expected {expected_version}, got {actual_version}"
            )
        )


class TransitionTooLarge(ValueError):
    """Transition exceeds the per-commit cap (64 logs or 64 outbox items)."""


class RunContended(RuntimeError):
    """Optimistic concurrency retry attempts were exhausted without committing."""


# ── Frozen Domain Dataclasses ────────────────────────────────────────────────


@dataclass(frozen=True)
class CoralRun:
    """Read-only domain representation of a workflow execution run."""

    workspace_id: int
    id: str
    workflow_id: str
    version_id: str
    status: int
    version: int
    next_log_seq: int
    activation_count: int
    title: str
    engine_version: int
    state_version: int
    log_version: int
    created_at: int
    updated_at: int
    user_id: str | None = None
    account_generation: str | None = None
    pause_reason: int | None = None
    orchestrator_session_id: str | None = None
    finished_at: int | None = None


@dataclass(frozen=True)
class RunStartSpec:
    """Specification inputs required to initiate a run."""

    workflow_id: str
    version_id: str
    title: str
    request_preview: str
    workspace_id: int | None = None
    user_id: str | None = None
    account_generation: str | None = None
    request_ref: str | None = None
    trigger_kind: int = 1
    execution_target: int = 1
    host_id: str | None = None
    repository_id: str | None = None
    repo_path: str | None = None
    worktree_path: str | None = None
    base_ref: str | None = None
    base_commit: str | None = None
    run_branch: str | None = None
    auth_mode: int = 1
    credential_ref: str | None = None
    max_activations: int = 100
    refresh_threshold_bp: int = 8000
    rejected_call_limit: int = 5
    engine_version: int = 1
    state_version: int = 1
    log_version: int = 1
    orchestrator_session_id: str | None = None


@dataclass(frozen=True)
class ActivationDraft:
    """Draft activation to create or update during a transition."""

    id: str
    node_id: str
    scope_key: str
    status: int
    attempt: int = 1
    max_attempts: int = 3
    parent_activation_id: str | None = None
    outcome: int | None = None
    chosen_label: str | None = None
    taken_over_by: str | None = None
    start_commit: str | None = None
    start_fingerprint: bytes | None = None
    items_total: int | None = None
    items_closed: int | None = None
    created_at: int = 0
    started_at: int | None = None
    closed_at: int | None = None
    updated_at: int = 0


@dataclass(frozen=True)
class ActivationState:
    """Frozen state snapshot of a step activation."""

    workspace_id: int
    run_id: str
    id: str
    node_id: str
    scope_key: str
    status: int
    attempt: int
    max_attempts: int
    created_at: int
    updated_at: int
    parent_activation_id: str | None = None
    outcome: int | None = None
    chosen_label: str | None = None
    taken_over_by: str | None = None
    start_commit: str | None = None
    start_fingerprint: bytes | None = None
    items_total: int | None = None
    items_closed: int | None = None
    started_at: int | None = None
    closed_at: int | None = None


@dataclass(frozen=True)
class JoinArrivalDraft:
    """Draft edge arrival at a join node."""

    activation_id: str
    arrow_id: str
    source_activation_id: str
    outcome: int
    handoff_id: str | None = None
    arrived_at: int = 0


@dataclass(frozen=True)
class JoinArrivalState:
    """Frozen state of an edge arrival at a join node."""

    workspace_id: int
    run_id: str
    activation_id: str
    arrow_id: str
    source_activation_id: str
    outcome: int
    arrived_at: int
    handoff_id: str | None = None


@dataclass(frozen=True)
class AgentSlotDraft:
    """Draft agent slot assignment to create or update."""

    id: str
    activation_id: str
    node_id: str
    scope_key: str
    roster_index: int
    role: int
    session_generation: int = 1
    status: int = 1
    profile_revision_id: str | None = None
    session_id: str | None = None
    closing_code: int | None = None
    post_close_activity: bool = False
    lease_expires_at: int | None = None
    lease_holder: str | None = None
    hold_seen_at: int | None = None
    restart_attempt_id: str | None = None
    last_edge_status: str | None = None
    last_turn_outcome: str | None = None
    last_edge_at: int | None = None
    branch: str | None = None
    worktree_path: str | None = None
    last_turn_origin: int | None = None
    nudges: int = 0
    consecutive_rejections: int = 0
    context_used_bp: int | None = None
    created_at: int = 0
    updated_at: int = 0


@dataclass(frozen=True)
class AgentSlotState:
    """Frozen state of an agent execution slot."""

    workspace_id: int
    run_id: str
    id: str
    activation_id: str
    node_id: str
    scope_key: str
    roster_index: int
    role: int
    session_generation: int
    status: int
    post_close_activity: bool
    nudges: int
    consecutive_rejections: int
    created_at: int
    updated_at: int
    profile_revision_id: str | None = None
    session_id: str | None = None
    closing_code: int | None = None
    lease_expires_at: int | None = None
    lease_holder: str | None = None
    hold_seen_at: int | None = None
    restart_attempt_id: str | None = None
    last_edge_status: str | None = None
    last_turn_outcome: str | None = None
    last_edge_at: int | None = None
    branch: str | None = None
    worktree_path: str | None = None
    last_turn_origin: int | None = None
    context_used_bp: int | None = None


@dataclass(frozen=True)
class HandoffDraft:
    """Draft structured output handoff record."""

    id: str
    activation_id: str
    node_id: str
    scope_key: str
    attempt: int
    status: int
    submit_status: int
    idempotency_cksum: bytes
    slot_id: str | None = None
    label: str | None = None
    item_count: int | None = None
    summary: str | None = None
    report_ref: str | None = None
    report_bytes: int | None = None
    blocked_reason: str | None = None
    evidence_outcome: int | None = None
    evidence_ref: str | None = None
    rejection_code: int | None = None
    rejection_message: str | None = None
    submitted_by_session_id: str | None = None
    submitted_at_us: int = 0


@dataclass(frozen=True)
class HandoffState:
    """Frozen state of a structured output handoff."""

    workspace_id: int
    run_id: str
    id: str
    activation_id: str
    node_id: str
    scope_key: str
    attempt: int
    status: int
    submit_status: int
    idempotency_cksum: bytes
    submitted_at_us: int
    slot_id: str | None = None
    label: str | None = None
    item_count: int | None = None
    summary: str | None = None
    report_ref: str | None = None
    report_bytes: int | None = None
    blocked_reason: str | None = None
    evidence_outcome: int | None = None
    evidence_ref: str | None = None
    rejection_code: int | None = None
    rejection_message: str | None = None
    submitted_by_session_id: str | None = None


@dataclass(frozen=True)
class HandoffItemDraft:
    """Draft granular work item associated with a handoff."""

    handoff_id: str
    item_index: int
    item_key: str
    title: str
    payload: str | None = None
    payload_ref: str | None = None


@dataclass(frozen=True)
class HandoffItemState:
    """Frozen state of a granular handoff item."""

    workspace_id: int
    run_id: str
    handoff_id: str
    item_index: int
    item_key: str
    title: str
    payload: str | None = None
    payload_ref: str | None = None


@dataclass(frozen=True)
class GateVisitDraft:
    """Draft gate visit checkpoint."""

    id: str
    activation_id: str
    node_id: str
    scope_key: str
    visit_no: int
    token: str
    status: int
    owner_user_id: str | None = None
    elicitation_id: str | None = None
    elicitation_session_id: str | None = None
    prompt_ref: str | None = None
    answer_label: str | None = None
    answered_by: str | None = None
    note: str | None = None
    opened_at: int = 0
    reminded_at: int | None = None
    resolved_at: int | None = None


@dataclass(frozen=True)
class GateVisitState:
    """Frozen state of a gate visit checkpoint."""

    workspace_id: int
    run_id: str
    id: str
    activation_id: str
    node_id: str
    scope_key: str
    visit_no: int
    token: str
    status: int
    opened_at: int
    owner_user_id: str | None = None
    elicitation_id: str | None = None
    elicitation_session_id: str | None = None
    prompt_ref: str | None = None
    answer_label: str | None = None
    answered_by: str | None = None
    note: str | None = None
    reminded_at: int | None = None
    resolved_at: int | None = None


@dataclass(frozen=True)
class LogEntryDraft:
    """Draft append-only event log row to persist."""

    kind: int
    actor_kind: int
    body: str
    audit_only: bool = False
    actor_ref: str | None = None
    activation_id: str | None = None
    node_id: str | None = None
    scope_key: str | None = None
    idempotency_cksum: bytes | None = None
    body_ref: str | None = None
    view_patch: str | None = None
    view_patch_ref: str | None = None
    created_at_us: int | None = None


@dataclass(frozen=True)
class RunLogEntry:
    """Frozen append-only event log entry."""

    workspace_id: int
    run_id: str
    seq: int
    run_version: int
    log_version: int
    kind: int
    actor_kind: int
    body: str
    created_at_us: int
    audit_only: bool = False
    actor_ref: str | None = None
    activation_id: str | None = None
    node_id: str | None = None
    scope_key: str | None = None
    idempotency_cksum: bytes | None = None
    body_ref: str | None = None
    view_patch: str | None = None
    view_patch_ref: str | None = None


@dataclass(frozen=True)
class RunReceipt:
    """Durable receipt proving an idempotent operation was committed."""

    workspace_id: int
    run_id: str
    seq: int
    run_version: int
    idempotency_cksum: bytes
    created_at_us: int

    @property
    def log_seq(self) -> int:
        return self.seq


@dataclass(frozen=True)
class WorkItemDraft:
    """Draft work item to enqueue into coral_work."""

    id: str
    run_id: str
    kind: int
    payload: str
    idempotency_cksum: bytes
    node_id: str | None = None
    scope_key: str | None = None
    slot_generation: int | None = None
    owner_key: str | None = None
    available_at: int = 0

    @classmethod
    def signal(
        cls,
        *,
        run_id: str,
        idempotency_key: str,
        payload: str | dict[str, Any],
        node_id: str | None = None,
        scope_key: str | None = None,
        owner_key: str | None = None,
        slot_generation: int | None = None,
        available_at: int = 0,
    ) -> WorkItemDraft:
        payload_str = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else payload
        kind_str = "signal"
        item_id = derived_id("coral-work", run_id, kind_str, idempotency_key)
        cksum = hashlib.sha256(f"{kind_str}\0{idempotency_key}".encode()).digest()
        return cls(
            id=item_id,
            run_id=run_id,
            kind=int(WorkKind.SIGNAL),
            payload=payload_str,
            idempotency_cksum=cksum,
            node_id=node_id,
            scope_key=scope_key,
            slot_generation=slot_generation,
            owner_key=owner_key,
            available_at=available_at,
        )

    @classmethod
    def timer(
        cls,
        *,
        run_id: str,
        idempotency_key: str,
        available_at: int,
        payload: str | dict[str, Any] = "",
        node_id: str | None = None,
        scope_key: str | None = None,
        owner_key: str | None = None,
        slot_generation: int | None = None,
    ) -> WorkItemDraft:
        payload_str = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else payload
        kind_str = "timer"
        item_id = derived_id("coral-work", run_id, kind_str, idempotency_key)
        cksum = hashlib.sha256(f"{kind_str}\0{idempotency_key}".encode()).digest()
        return cls(
            id=item_id,
            run_id=run_id,
            kind=int(WorkKind.TIMER),
            payload=payload_str,
            idempotency_cksum=cksum,
            node_id=node_id,
            scope_key=scope_key,
            slot_generation=slot_generation,
            owner_key=owner_key,
            available_at=available_at,
        )

    @classmethod
    def effect(
        cls,
        *,
        run_id: str,
        idempotency_key: str,
        payload: str | dict[str, Any],
        node_id: str | None = None,
        scope_key: str | None = None,
        owner_key: str | None = None,
        slot_generation: int | None = None,
        available_at: int = 0,
    ) -> WorkItemDraft:
        payload_str = json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else payload
        kind_str = "effect"
        item_id = derived_id("coral-work", run_id, kind_str, idempotency_key)
        cksum = hashlib.sha256(f"{kind_str}\0{idempotency_key}".encode()).digest()
        return cls(
            id=item_id,
            run_id=run_id,
            kind=int(WorkKind.EFFECT),
            payload=payload_str,
            idempotency_cksum=cksum,
            node_id=node_id,
            scope_key=scope_key,
            slot_generation=slot_generation,
            owner_key=owner_key,
            available_at=available_at,
        )


@dataclass(frozen=True)
class WorkItem:
    """Frozen state of a work item in coral_work."""

    workspace_id: int
    id: str
    run_id: str
    kind: int
    status: int
    payload: str
    idempotency_cksum: bytes
    available_at: int
    created_at_us: int
    attempts: int = 0
    node_id: str | None = None
    scope_key: str | None = None
    slot_generation: int | None = None
    owner_key: str | None = None
    lease_expires_at: int | None = None
    lease_holder: str | None = None
    result: str | None = None
    result_ref: str | None = None
    error_code: str | None = None
    finished_at: int | None = None


@dataclass(frozen=True)
class RunState:
    """Aggregate snapshot of a run and all child entities loaded outside a write lock."""

    run: CoralRun
    spec: RunStartSpec
    activations: tuple[ActivationState, ...] = ()
    join_arrivals: tuple[JoinArrivalState, ...] = ()
    agent_slots: tuple[AgentSlotState, ...] = ()
    handoffs: tuple[HandoffState, ...] = ()
    handoff_items: tuple[HandoffItemState, ...] = ()
    gate_visits: tuple[GateVisitState, ...] = ()

    @property
    def run_id(self) -> str:
        return self.run.id

    @property
    def workspace_id(self) -> int:
        return self.run.workspace_id

    @property
    def status(self) -> int:
        return self.run.status

    @property
    def version(self) -> int:
        return self.run.version


@dataclass(frozen=True)
class Transition:
    """Mutations to apply atomically against a run at expected_version."""

    status: int | None = None
    pause_reason: int | None = None
    clear_pause_reason: bool = False
    orchestrator_session_id: str | None = None
    activation_count_delta: int = 0
    finished_at: int | None = None
    activations: Sequence[ActivationDraft] = ()
    join_arrivals: Sequence[JoinArrivalDraft] = ()
    agent_slots: Sequence[AgentSlotDraft] = ()
    handoffs: Sequence[HandoffDraft] = ()
    handoff_items: Sequence[HandoffItemDraft] = ()
    gate_visits: Sequence[GateVisitDraft] = ()
    logs: Sequence[LogEntryDraft] = ()
    outbox_work: Sequence[WorkItemDraft] = ()
    consumed_work_ids: Sequence[str] = ()

    @classmethod
    def empty(cls) -> Transition:
        return cls()

    @property
    def is_empty(self) -> bool:
        return (
            self.status is None
            and self.pause_reason is None
            and not self.clear_pause_reason
            and self.orchestrator_session_id is None
            and self.activation_count_delta == 0
            and self.finished_at is None
            and len(self.activations) == 0
            and len(self.join_arrivals) == 0
            and len(self.agent_slots) == 0
            and len(self.handoffs) == 0
            and len(self.handoff_items) == 0
            and len(self.gate_visits) == 0
            and len(self.logs) == 0
            and len(self.outbox_work) == 0
            and len(self.consumed_work_ids) == 0
        )


@dataclass(frozen=True)
class CommitOutcome:
    """Result of an optimistic CAS transition commit."""

    run_id: str
    version: int
    applied: bool = True
    receipt: RunReceipt | None = None
    work_ids: tuple[str, ...] = ()
    log_seqs: tuple[int, ...] = ()


# ── Store Protocols ──────────────────────────────────────────────────────────


@runtime_checkable
class RunStore(Protocol):
    """Domain protocol for run persistence and optimistic concurrency transitions."""

    def start_run(
        self,
        spec: RunStartSpec,
        *,
        start_key: str | None = None,
        now: int | None = None,
    ) -> CoralRun: ...

    def load_run_state(
        self,
        run_id: str,
        *,
        workspace_id: int | None = None,
    ) -> tuple[RunState, int]: ...

    def apply_transition(
        self,
        run_id: str,
        expected_version: int,
        transition: Transition,
        *,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> CommitOutcome: ...

    def get_run(
        self,
        run_id: str,
        *,
        workspace_id: int | None = None,
    ) -> CoralRun | None: ...

    def list_runs(
        self,
        *,
        workspace_id: int | None = None,
        cursor: tuple[int, str] | None = None,
        limit: int = 100,
        descending: bool = True,
    ) -> list[CoralRun]: ...

    def read_log(
        self,
        run_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
        workspace_id: int | None = None,
    ) -> list[RunLogEntry]: ...

    def find_receipt(
        self,
        run_id: str,
        idempotency_cksum: bytes,
        *,
        workspace_id: int | None = None,
    ) -> RunReceipt | None: ...

    def list_active_runs_all_workspaces(
        self,
        *,
        cursor: tuple[int, str] | None = None,
        limit: int = 100,
    ) -> list[CoralRun]: ...

    def list_open_gates_all_workspaces(
        self,
        *,
        cursor: tuple[int, str, str] | None = None,
        limit: int = 100,
    ) -> list[GateVisitState]: ...

    def register_post_commit(
        self,
        callback: Callable[[str, int], None],
    ) -> None: ...


@runtime_checkable
class QueueStore(Protocol):
    """Domain protocol for leased work queue and worker coordination."""

    def enqueue_work(
        self,
        items: Sequence[WorkItemDraft],
        *,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[str]: ...

    def claim_work(
        self,
        worker_id: str,
        *,
        kinds: Sequence[int] = (3,),
        lease_seconds: int = 60,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> WorkItem | None: ...

    def renew_lease(
        self,
        work_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> bool: ...

    def finish_work(
        self,
        work_id: str,
        *,
        worker_id: str,
        expected_lease_expires_at: int,
        status: int,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        next_available_at: int | None = None,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> bool: ...

    def reclaim_expired_work(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> int: ...

    def discover_ready_signals(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[WorkItem]: ...

    def discover_due_timers(
        self,
        *,
        now: int,
        limit: int = 100,
        workspace_id: int | None = None,
    ) -> list[WorkItem]: ...

    def discover_ready_effects(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[WorkItem]: ...

    def discover_expired_effects(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[WorkItem]: ...

    def get_run_status(
        self,
        run_id: str,
        *,
        workspace_id: int | None = None,
    ) -> int | None: ...

    def get_slot_generation(
        self,
        run_id: str,
        slot_id: str,
        *,
        workspace_id: int | None = None,
    ) -> int | None: ...

    def acquire_worker_lease(
        self,
        name: str,
        worker_id: str,
        *,
        lease_seconds: int = 120,
        now_fn: Callable[[], float] | None = None,
    ) -> bool: ...

    def renew_worker_lease(
        self,
        name: str,
        worker_id: str,
        *,
        lease_seconds: int = 120,
        now_fn: Callable[[], float] | None = None,
    ) -> bool: ...

    def release_worker_lease(
        self,
        name: str,
        worker_id: str,
    ) -> bool: ...


__all__ = [
    "ActivationDraft",
    "ActivationState",
    "AgentSlotDraft",
    "AgentSlotState",
    "CommitOutcome",
    "CoralRun",
    "GateVisitDraft",
    "GateVisitState",
    "HandoffDraft",
    "HandoffItemDraft",
    "HandoffItemState",
    "HandoffState",
    "JoinArrivalDraft",
    "JoinArrivalState",
    "LogEntryDraft",
    "QueueStore",
    "RunContended",
    "RunLogEntry",
    "RunNotFound",
    "RunReceipt",
    "RunStartSpec",
    "RunState",
    "RunStatus",
    "RunStore",
    "RunVersionConflict",
    "StartKeyConflict",
    "Transition",
    "TransitionTooLarge",
    "WorkItem",
    "WorkItemDraft",
    "WorkKind",
    "WorkStatus",
]
