"""Core Coral relational ORM models (tables 1-14)."""

from __future__ import annotations

import builtins

from sqlalchemy import (
    BigInteger,
    Boolean,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from coral.db.base import CoralBase
from coral.db.enum_codecs import (
    ACTIVATION_OUTCOME,
    ACTIVATION_STATUS,
    ACTOR_KIND,
    BLOB_REF_KIND,
    GATE_VISIT_STATUS,
    HANDOFF_EVIDENCE_OUTCOME,
    HANDOFF_REJECTION_CODE,
    HANDOFF_STATUS,
    HANDOFF_SUBMIT_STATUS,
    JOIN_ARRIVAL_OUTCOME,
    LOG_KIND,
    RUN_AUTH_MODE,
    RUN_EXECUTION_TARGET,
    RUN_PAUSE_REASON,
    RUN_STATUS,
    RUN_TRIGGER_KIND,
    SIMULATION_CASE_STATUS,
    SLOT_ROLE,
    SLOT_STATUS,
    SLOT_TURN_ORIGIN,
    WORKFLOW_SOURCE_KIND,
    WORKFLOW_VERSION_ORIGIN,
    WORKFLOW_VERSION_STATUS,
    make_enum_check_constraint,
)
from coral.db.types import CAPPED_TEXT, CHECKSUM32, CaseSensitiveString


class WorkflowRow(CoralBase):
    """Workflow definition row with dual metadata support."""

    __tablename__ = "coral_workflows"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workflow_key: Mapped[str] = mapped_column(CaseSensitiveString(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    account_generation: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    description: Mapped[str | None] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    source_kind: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    source_host_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    source_repo_path: Mapped[str | None] = mapped_column(String(2048), nullable=True, default=None)
    source_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    latest_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    layout_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    yaml_text: Mapped[str] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    compiled_json: Mapped[str] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    content_hash: Mapped[bytes] = mapped_column(CHECKSUM32, nullable=True, default=None)
    validation_state: Mapped[str] = mapped_column(String(16), nullable=True, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("source_kind", 1)
        super().__init__(**kwargs)

    __table_args__ = (
        UniqueConstraint("workspace_id", "workflow_key", name="uq_coral_workflows_key"),
        Index("ix_coral_workflows_owner", "workspace_id", "user_id", "created_at", "id"),
        make_enum_check_constraint(
            "source_kind", WORKFLOW_SOURCE_KIND, name="ck_coral_workflows_source_kind"
        ),
    )


class WorkflowVersionRow(CoralBase):
    """Immutable compiled workflow version."""

    __tablename__ = "coral_workflow_versions"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[bytes] = mapped_column(CHECKSUM32, nullable=False)
    yaml_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    yaml_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    compiled_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    compiler_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    origin: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    source_commit: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    source_dirty: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    validation_state: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    diagnostics_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    command_patterns_hash: Mapped[bytes | None] = mapped_column(
        CHECKSUM32, nullable=True, default=None
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index(
            "ix_coral_workflow_versions_workflow",
            "workspace_id",
            "workflow_id",
            "created_at",
            "id",
        ),
        make_enum_check_constraint(
            "origin", WORKFLOW_VERSION_ORIGIN, name="ck_coral_workflow_versions_origin"
        ),
        make_enum_check_constraint(
            "validation_state",
            WORKFLOW_VERSION_STATUS,
            name="ck_coral_workflow_versions_validation_state",
        ),
    )


class WorkflowDraftRow(CoralBase):
    """Editable uncompiled workflow draft with revision tracking."""

    __tablename__ = "coral_workflow_drafts"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    base_sha256: Mapped[bytes] = mapped_column(CHECKSUM32, nullable=False)
    yaml_text: Mapped[str] = mapped_column(CAPPED_TEXT, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RunRow(CoralBase):
    """Workflow execution run instance with optimistic version counter."""

    __tablename__ = "coral_runs"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    account_generation: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    pause_reason: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    next_log_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    activation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    orchestrator_session_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    engine_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    state_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    log_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    finished_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)

    __table_args__ = (
        Index("ix_coral_runs_owner", "workspace_id", "user_id", "created_at", "id"),
        Index("ix_coral_runs_workflow", "workspace_id", "workflow_id", "created_at", "id"),
        Index("ix_coral_runs_active", "status", "workspace_id", "id"),
        Index("ix_coral_runs_version", "workspace_id", "version_id", "id"),
        make_enum_check_constraint("status", RUN_STATUS, name="ck_coral_runs_status"),
        # Renamed when widened: a distinct name lets CockroachDB replace it in one transaction.
        make_enum_check_constraint(
            "pause_reason",
            RUN_PAUSE_REASON,
            name="ck_coral_runs_pause_reason_v2",
            nullable=True,
        ),
    )


class RunSpecRow(CoralBase):
    """Static input and configuration parameters for a run."""

    __tablename__ = "coral_run_specs"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    start_key: Mapped[str | None] = mapped_column(
        CaseSensitiveString(256), nullable=True, default=None
    )
    request_preview: Mapped[str] = mapped_column(String(512), nullable=False)
    request_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    trigger_kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    execution_target: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    host_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    repository_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    repo_path: Mapped[str | None] = mapped_column(String(2048), nullable=True, default=None)
    worktree_path: Mapped[str | None] = mapped_column(String(2048), nullable=True, default=None)
    base_ref: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    base_commit: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    run_branch: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    auth_mode: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(256), nullable=True, default=None)
    max_activations: Mapped[int] = mapped_column(Integer, nullable=False)
    refresh_threshold_bp: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rejected_call_limit: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        make_enum_check_constraint(
            "trigger_kind", RUN_TRIGGER_KIND, name="ck_coral_run_specs_trigger_kind"
        ),
        make_enum_check_constraint(
            "execution_target",
            RUN_EXECUTION_TARGET,
            name="ck_coral_run_specs_execution_target",
        ),
        make_enum_check_constraint(
            "auth_mode", RUN_AUTH_MODE, name="ck_coral_run_specs_auth_mode"
        ),
    )


class ActivationRow(CoralBase):
    """Step node activation within a run."""

    __tablename__ = "coral_activations"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    node_id: Mapped[str] = mapped_column(CaseSensitiveString(64), nullable=False)
    scope_key: Mapped[str] = mapped_column(CaseSensitiveString(512), nullable=False)
    parent_activation_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    outcome: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    chosen_label: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    taken_over_by: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    start_commit: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    start_fingerprint: Mapped[bytes | None] = mapped_column(
        CHECKSUM32, nullable=True, default=None
    )
    items_total: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    items_closed: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    closed_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_coral_activations_status", "workspace_id", "run_id", "status", "id"),
        Index("ix_coral_activations_created", "workspace_id", "run_id", "created_at", "id"),
        make_enum_check_constraint(
            "status", ACTIVATION_STATUS, name="ck_coral_activations_status"
        ),
        make_enum_check_constraint(
            "outcome", ACTIVATION_OUTCOME, name="ck_coral_activations_outcome", nullable=True
        ),
    )


class JoinArrivalRow(CoralBase):
    """Arrival record for an incoming edge to a join node."""

    __tablename__ = "coral_join_arrivals"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    activation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    arrow_id: Mapped[str] = mapped_column(CaseSensitiveString(64), primary_key=True)
    source_activation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    handoff_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    outcome: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    arrived_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        make_enum_check_constraint(
            "outcome", JOIN_ARRIVAL_OUTCOME, name="ck_coral_join_arrivals_outcome"
        ),
    )


class AgentSlotRow(CoralBase):
    """Agent execution slot associated with an activation."""

    __tablename__ = "coral_agent_slots"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    activation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    node_id: Mapped[str] = mapped_column(CaseSensitiveString(64), nullable=False)
    scope_key: Mapped[str] = mapped_column(CaseSensitiveString(512), nullable=False)
    roster_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    role: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    profile_revision_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    session_generation: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    closing_code: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    post_close_activity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lease_expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    lease_holder: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    hold_seen_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    restart_attempt_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    last_edge_status: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    last_turn_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    last_edge_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    worktree_path: Mapped[str | None] = mapped_column(String(2048), nullable=True, default=None)
    last_turn_origin: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    nudges: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    consecutive_rejections: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    context_used_bp: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("post_close_activity", False)
        kwargs.setdefault("nudges", 0)
        kwargs.setdefault("consecutive_rejections", 0)
        super().__init__(**kwargs)

    __table_args__ = (
        Index(
            "ix_coral_agent_slots_activation",
            "workspace_id",
            "run_id",
            "activation_id",
            "roster_index",
            "id",
        ),
        Index(
            "ix_coral_agent_slots_expired",
            "status",
            "lease_expires_at",
            "workspace_id",
            "run_id",
            "id",
        ),
        make_enum_check_constraint("role", SLOT_ROLE, name="ck_coral_agent_slots_role"),
        make_enum_check_constraint("status", SLOT_STATUS, name="ck_coral_agent_slots_status"),
        make_enum_check_constraint(
            "last_turn_origin",
            SLOT_TURN_ORIGIN,
            name="ck_coral_agent_slots_last_turn_origin",
            nullable=True,
        ),
    )


class HandoffRow(CoralBase):
    """Structured output handoff delivered by an activation or slot."""

    __tablename__ = "coral_handoffs"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    activation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    slot_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    node_id: Mapped[str] = mapped_column(CaseSensitiveString(64), nullable=False)
    scope_key: Mapped[str] = mapped_column(CaseSensitiveString(512), nullable=False)
    attempt: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    submit_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    summary: Mapped[str | None] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    report_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    report_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    blocked_reason: Mapped[str | None] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    evidence_outcome: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    rejection_code: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    rejection_message: Mapped[str | None] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    idempotency_cksum: Mapped[bytes] = mapped_column(CHECKSUM32, nullable=False)
    submitted_by_session_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    submitted_at_us: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "run_id", "idempotency_cksum", name="uq_coral_handoffs_idempotency"
        ),
        Index(
            "ix_coral_handoffs_activation",
            "workspace_id",
            "run_id",
            "activation_id",
            "submitted_at_us",
            "id",
        ),
        make_enum_check_constraint("status", HANDOFF_STATUS, name="ck_coral_handoffs_status"),
        make_enum_check_constraint(
            "submit_status", HANDOFF_SUBMIT_STATUS, name="ck_coral_handoffs_submit_status"
        ),
        make_enum_check_constraint(
            "evidence_outcome",
            HANDOFF_EVIDENCE_OUTCOME,
            name="ck_coral_handoffs_evidence_outcome",
            nullable=True,
        ),
        make_enum_check_constraint(
            "rejection_code",
            HANDOFF_REJECTION_CODE,
            name="ck_coral_handoffs_rejection_code",
            nullable=True,
        ),
    )


class HandoffItemRow(CoralBase):
    """Granular work item associated with a handoff."""

    __tablename__ = "coral_handoff_items"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    handoff_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    item_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_key: Mapped[str] = mapped_column(CaseSensitiveString(128), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[str | None] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    payload_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)


class GateVisitRow(CoralBase):
    """Human/external approval or input gate checkpoint."""

    __tablename__ = "coral_gate_visits"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    activation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    node_id: Mapped[str] = mapped_column(CaseSensitiveString(64), nullable=False)
    scope_key: Mapped[str] = mapped_column(CaseSensitiveString(512), nullable=False)
    visit_no: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    elicitation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    elicitation_session_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    prompt_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    answer_label: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    answered_by: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    note: Mapped[str | None] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    opened_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reminded_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    resolved_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)

    __table_args__ = (
        Index(
            "ix_coral_gate_visits_inbox",
            "workspace_id",
            "owner_user_id",
            "status",
            "opened_at",
            "id",
        ),
        Index("ix_coral_gate_visits_open", "status", "workspace_id", "run_id", "id"),
        make_enum_check_constraint(
            "status", GATE_VISIT_STATUS, name="ck_coral_gate_visits_status"
        ),
    )


class RunLogRow(CoralBase):
    """Monotonically ordered append-only event log entry for a run."""

    __tablename__ = "coral_run_log"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    log_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    audit_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actor_kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    activation_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    node_id: Mapped[str | None] = mapped_column(
        CaseSensitiveString(64), nullable=True, default=None
    )
    scope_key: Mapped[str | None] = mapped_column(
        CaseSensitiveString(512), nullable=True, default=None
    )
    idempotency_cksum: Mapped[bytes | None] = mapped_column(
        CHECKSUM32, nullable=True, default=None
    )
    body: Mapped[str] = mapped_column(CAPPED_TEXT, nullable=False)
    body_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    view_patch: Mapped[str | None] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    view_patch_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    created_at_us: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("audit_only", False)
        super().__init__(**kwargs)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "run_id", "idempotency_cksum", name="uq_coral_run_log_idempotency"
        ),
        Index("ix_coral_run_log_activation", "workspace_id", "run_id", "activation_id", "seq"),
        make_enum_check_constraint("actor_kind", ACTOR_KIND, name="ck_coral_run_log_actor_kind"),
        make_enum_check_constraint("kind", LOG_KIND, name="ck_coral_run_log_kind"),
    )


class SimulationCaseRow(CoralBase):
    """Stored simulation case for workflow behavioral verification."""

    __tablename__ = "coral_simulation_cases"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    script: Mapped[str] = mapped_column(CAPPED_TEXT, nullable=False)
    expectation: Mapped[str | None] = mapped_column(CAPPED_TEXT, nullable=True, default=None)
    last_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    last_result: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, default=None)
    last_run_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    last_report_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)

    __table_args__ = (
        Index(
            "ix_coral_simulation_cases_workflow",
            "workspace_id",
            "workflow_id",
            "created_at",
            "id",
        ),
        make_enum_check_constraint(
            "last_result",
            SIMULATION_CASE_STATUS,
            name="ck_coral_simulation_cases_last_result",
            nullable=True,
        ),
    )


class BlobRefRow(CoralBase):
    """Reference tracking for content-addressed CAS external artifacts."""

    __tablename__ = "coral_blob_refs"

    workspace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    key_cksum: Mapped[bytes] = mapped_column(CHECKSUM32, primary_key=True)
    scope_kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(512), nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[builtins.bytes] = mapped_column(CHECKSUM32, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        make_enum_check_constraint(
            "scope_kind", BLOB_REF_KIND, name="ck_coral_blob_refs_scope_kind"
        ),
    )


__all__ = [
    "ActivationRow",
    "AgentSlotRow",
    "BlobRefRow",
    "GateVisitRow",
    "HandoffItemRow",
    "HandoffRow",
    "JoinArrivalRow",
    "RunLogRow",
    "RunRow",
    "RunSpecRow",
    "SimulationCaseRow",
    "WorkflowDraftRow",
    "WorkflowRow",
    "WorkflowVersionRow",
]
