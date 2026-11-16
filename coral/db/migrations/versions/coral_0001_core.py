"""Core Coral schema migration matching CoralBase.metadata.

Revision ID: coral_0001_core
Revises: coral_0000_base
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from coral.db.types import CAPPED_TEXT, CHECKSUM32, CaseSensitiveString

revision: str = "coral_0001_core"
down_revision: str | None = "coral_0000_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coral_workflows",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("workflow_key", CaseSensitiveString(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("account_generation", sa.String(32), nullable=True),
        sa.Column("description", CAPPED_TEXT, nullable=True),
        sa.Column("source_kind", sa.SmallInteger(), nullable=False),
        sa.Column("source_host_id", sa.String(64), nullable=True),
        sa.Column("source_repo_path", sa.String(2048), nullable=True),
        sa.Column("source_file_path", sa.String(1024), nullable=True),
        sa.Column("latest_version_id", sa.String(32), nullable=True),
        sa.Column("layout_ref", sa.String(512), nullable=True),
        sa.Column("yaml_text", CAPPED_TEXT, nullable=True),
        sa.Column("compiled_json", CAPPED_TEXT, nullable=True),
        sa.Column("content_hash", CHECKSUM32, nullable=True),
        sa.Column("validation_state", sa.String(16), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_coral_workflows",
        ),
        sa.CheckConstraint(
            "source_kind IN (1, 2, 3)",
            name="ck_coral_workflows_source_kind",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "workflow_key",
            name="uq_coral_workflows_key",
        ),
    )
    op.create_index(
        "ix_coral_workflows_owner",
        "coral_workflows",
        ["workspace_id", "user_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "coral_workflow_versions",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("workflow_id", sa.String(32), nullable=False),
        sa.Column("content_hash", CHECKSUM32, nullable=False),
        sa.Column("yaml_ref", sa.String(512), nullable=False),
        sa.Column("yaml_bytes", sa.Integer(), nullable=False),
        sa.Column("compiled_ref", sa.String(512), nullable=False),
        sa.Column("compiler_version", sa.SmallInteger(), nullable=False),
        sa.Column("origin", sa.SmallInteger(), nullable=False),
        sa.Column("parent_version_id", sa.String(32), nullable=True),
        sa.Column("source_commit", sa.String(64), nullable=True),
        sa.Column("source_dirty", sa.Boolean(), nullable=True),
        sa.Column("validation_state", sa.SmallInteger(), nullable=False),
        sa.Column("diagnostics_ref", sa.String(512), nullable=True),
        sa.Column("command_patterns_hash", CHECKSUM32, nullable=True),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_coral_workflow_versions",
        ),
        sa.CheckConstraint(
            "validation_state IN (1, 2)",
            name="ck_coral_workflow_versions_validation_state",
        ),
        sa.CheckConstraint(
            "origin IN (1, 2, 3, 4)",
            name="ck_coral_workflow_versions_origin",
        ),
    )
    op.create_index(
        "ix_coral_workflow_versions_workflow",
        "coral_workflow_versions",
        ["workspace_id", "workflow_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "coral_workflow_drafts",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("workflow_id", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("base_sha256", CHECKSUM32, nullable=False),
        sa.Column("yaml_text", CAPPED_TEXT, nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "workflow_id",
            name="pk_coral_workflow_drafts",
        ),
    )
    op.create_table(
        "coral_runs",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("workflow_id", sa.String(32), nullable=False),
        sa.Column("version_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("account_generation", sa.String(32), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("pause_reason", sa.SmallInteger(), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("next_log_seq", sa.BigInteger(), nullable=False),
        sa.Column("activation_count", sa.Integer(), nullable=False),
        sa.Column("orchestrator_session_id", sa.String(64), nullable=True),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("engine_version", sa.SmallInteger(), nullable=False),
        sa.Column("state_version", sa.SmallInteger(), nullable=False),
        sa.Column("log_version", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.Column("finished_at", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "status IN (1, 2, 3, 4, 5, 6)",
            name="ck_coral_runs_status",
        ),
        sa.CheckConstraint(
            "pause_reason IS NULL OR pause_reason IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)",
            name="ck_coral_runs_pause_reason",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_coral_runs",
        ),
    )
    op.create_index(
        "ix_coral_runs_workflow",
        "coral_runs",
        ["workspace_id", "workflow_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_coral_runs_version",
        "coral_runs",
        ["workspace_id", "version_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_coral_runs_active",
        "coral_runs",
        ["status", "workspace_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_coral_runs_owner",
        "coral_runs",
        ["workspace_id", "user_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "coral_run_specs",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("start_key", CaseSensitiveString(256), nullable=True),
        sa.Column("request_preview", sa.String(512), nullable=False),
        sa.Column("request_ref", sa.String(512), nullable=True),
        sa.Column("trigger_kind", sa.SmallInteger(), nullable=False),
        sa.Column("execution_target", sa.SmallInteger(), nullable=False),
        sa.Column("host_id", sa.String(64), nullable=True),
        sa.Column("repository_id", sa.String(64), nullable=True),
        sa.Column("repo_path", sa.String(2048), nullable=True),
        sa.Column("worktree_path", sa.String(2048), nullable=True),
        sa.Column("base_ref", sa.String(255), nullable=True),
        sa.Column("base_commit", sa.String(64), nullable=True),
        sa.Column("run_branch", sa.String(255), nullable=True),
        sa.Column("auth_mode", sa.SmallInteger(), nullable=False),
        sa.Column("credential_ref", sa.String(256), nullable=True),
        sa.Column("max_activations", sa.Integer(), nullable=False),
        sa.Column("refresh_threshold_bp", sa.SmallInteger(), nullable=False),
        sa.Column("rejected_call_limit", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "run_id",
            name="pk_coral_run_specs",
        ),
        sa.CheckConstraint(
            "trigger_kind IN (1, 2, 3, 4)",
            name="ck_coral_run_specs_trigger_kind",
        ),
        sa.CheckConstraint(
            "execution_target IN (1, 2)",
            name="ck_coral_run_specs_execution_target",
        ),
        sa.CheckConstraint(
            "auth_mode IN (1, 2, 3)",
            name="ck_coral_run_specs_auth_mode",
        ),
    )
    op.create_table(
        "coral_activations",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("node_id", CaseSensitiveString(64), nullable=False),
        sa.Column("scope_key", CaseSensitiveString(512), nullable=False),
        sa.Column("parent_activation_id", sa.String(32), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("outcome", sa.SmallInteger(), nullable=True),
        sa.Column("attempt", sa.SmallInteger(), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), nullable=False),
        sa.Column("chosen_label", sa.String(128), nullable=True),
        sa.Column("taken_over_by", sa.String(128), nullable=True),
        sa.Column("start_commit", sa.String(64), nullable=True),
        sa.Column("start_fingerprint", CHECKSUM32, nullable=True),
        sa.Column("items_total", sa.Integer(), nullable=True),
        sa.Column("items_closed", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=True),
        sa.Column("closed_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN (1, 2, 3, 4, 5, 6, 7)",
            name="ck_coral_activations_outcome",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "run_id",
            "id",
            name="pk_coral_activations",
        ),
        sa.CheckConstraint(
            "status IN (1, 2, 3, 4, 5, 6, 7, 8, 9)",
            name="ck_coral_activations_status",
        ),
    )
    op.create_index(
        "ix_coral_activations_status",
        "coral_activations",
        ["workspace_id", "run_id", "status", "id"],
        unique=False,
    )
    op.create_index(
        "ix_coral_activations_created",
        "coral_activations",
        ["workspace_id", "run_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "coral_join_arrivals",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("activation_id", sa.String(32), nullable=False),
        sa.Column("arrow_id", CaseSensitiveString(64), nullable=False),
        sa.Column("source_activation_id", sa.String(32), nullable=False),
        sa.Column("handoff_id", sa.String(32), nullable=True),
        sa.Column("outcome", sa.SmallInteger(), nullable=False),
        sa.Column("arrived_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "outcome IN (1, 2, 3)",
            name="ck_coral_join_arrivals_outcome",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "run_id",
            "activation_id",
            "arrow_id",
            name="pk_coral_join_arrivals",
        ),
    )
    op.create_table(
        "coral_agent_slots",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("activation_id", sa.String(32), nullable=False),
        sa.Column("node_id", CaseSensitiveString(64), nullable=False),
        sa.Column("scope_key", CaseSensitiveString(512), nullable=False),
        sa.Column("roster_index", sa.SmallInteger(), nullable=False),
        sa.Column("role", sa.SmallInteger(), nullable=False),
        sa.Column("profile_revision_id", sa.String(64), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("session_generation", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("closing_code", sa.SmallInteger(), nullable=True),
        sa.Column("post_close_activity", sa.Boolean(), nullable=False),
        sa.Column("lease_expires_at", sa.BigInteger(), nullable=True),
        sa.Column("lease_holder", sa.String(64), nullable=True),
        sa.Column("hold_seen_at", sa.BigInteger(), nullable=True),
        sa.Column("restart_attempt_id", sa.String(64), nullable=True),
        sa.Column("last_edge_status", sa.String(32), nullable=True),
        sa.Column("last_turn_outcome", sa.String(32), nullable=True),
        sa.Column("last_edge_at", sa.BigInteger(), nullable=True),
        sa.Column("branch", sa.String(255), nullable=True),
        sa.Column("worktree_path", sa.String(2048), nullable=True),
        sa.Column("last_turn_origin", sa.SmallInteger(), nullable=True),
        sa.Column("nudges", sa.SmallInteger(), nullable=False),
        sa.Column("consecutive_rejections", sa.SmallInteger(), nullable=False),
        sa.Column("context_used_bp", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "run_id",
            "id",
            name="pk_coral_agent_slots",
        ),
        sa.CheckConstraint(
            "last_turn_origin IS NULL OR last_turn_origin IN (1, 2)",
            name="ck_coral_agent_slots_last_turn_origin",
        ),
        sa.CheckConstraint(
            "status IN (1, 2, 3, 4, 5, 6, 7, 8, 9)",
            name="ck_coral_agent_slots_status",
        ),
        sa.CheckConstraint(
            "role IN (1, 2, 3, 4)",
            name="ck_coral_agent_slots_role",
        ),
    )
    op.create_index(
        "ix_coral_agent_slots_expired",
        "coral_agent_slots",
        ["status", "lease_expires_at", "workspace_id", "run_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_coral_agent_slots_activation",
        "coral_agent_slots",
        ["workspace_id", "run_id", "activation_id", "roster_index", "id"],
        unique=False,
    )
    op.create_table(
        "coral_handoffs",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("activation_id", sa.String(32), nullable=False),
        sa.Column("slot_id", sa.String(32), nullable=True),
        sa.Column("node_id", CaseSensitiveString(64), nullable=False),
        sa.Column("scope_key", CaseSensitiveString(512), nullable=False),
        sa.Column("attempt", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("submit_status", sa.SmallInteger(), nullable=False),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=True),
        sa.Column("summary", CAPPED_TEXT, nullable=True),
        sa.Column("report_ref", sa.String(512), nullable=True),
        sa.Column("report_bytes", sa.Integer(), nullable=True),
        sa.Column("blocked_reason", CAPPED_TEXT, nullable=True),
        sa.Column("evidence_outcome", sa.SmallInteger(), nullable=True),
        sa.Column("evidence_ref", sa.String(512), nullable=True),
        sa.Column("rejection_code", sa.SmallInteger(), nullable=True),
        sa.Column("rejection_message", CAPPED_TEXT, nullable=True),
        sa.Column("idempotency_cksum", CHECKSUM32, nullable=False),
        sa.Column("submitted_by_session_id", sa.String(64), nullable=True),
        sa.Column("submitted_at_us", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "evidence_outcome IS NULL OR evidence_outcome IN (1, 2, 3, 4)",
            name="ck_coral_handoffs_evidence_outcome",
        ),
        sa.CheckConstraint(
            "rejection_code IS NULL OR rejection_code IN (1, 2, 3, 4, 5, 6)",
            name="ck_coral_handoffs_rejection_code",
        ),
        sa.CheckConstraint(
            "status IN (1, 2, 3)",
            name="ck_coral_handoffs_status",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "run_id",
            "id",
            name="pk_coral_handoffs",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "run_id",
            "idempotency_cksum",
            name="uq_coral_handoffs_idempotency",
        ),
        sa.CheckConstraint(
            "submit_status IN (1, 2)",
            name="ck_coral_handoffs_submit_status",
        ),
    )
    op.create_index(
        "ix_coral_handoffs_activation",
        "coral_handoffs",
        ["workspace_id", "run_id", "activation_id", "submitted_at_us", "id"],
        unique=False,
    )
    op.create_table(
        "coral_handoff_items",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("handoff_id", sa.String(32), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("item_key", CaseSensitiveString(128), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("payload", CAPPED_TEXT, nullable=True),
        sa.Column("payload_ref", sa.String(512), nullable=True),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "run_id",
            "handoff_id",
            "item_index",
            name="pk_coral_handoff_items",
        ),
    )
    op.create_table(
        "coral_gate_visits",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("activation_id", sa.String(32), nullable=False),
        sa.Column("node_id", CaseSensitiveString(64), nullable=False),
        sa.Column("scope_key", CaseSensitiveString(512), nullable=False),
        sa.Column("visit_no", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.String(128), nullable=True),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("elicitation_id", sa.String(64), nullable=True),
        sa.Column("elicitation_session_id", sa.String(64), nullable=True),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("prompt_ref", sa.String(512), nullable=True),
        sa.Column("answer_label", sa.String(128), nullable=True),
        sa.Column("answered_by", sa.String(128), nullable=True),
        sa.Column("note", CAPPED_TEXT, nullable=True),
        sa.Column("opened_at", sa.BigInteger(), nullable=False),
        sa.Column("reminded_at", sa.BigInteger(), nullable=True),
        sa.Column("resolved_at", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "status IN (1, 2, 3, 4)",
            name="ck_coral_gate_visits_status",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "run_id",
            "id",
            name="pk_coral_gate_visits",
        ),
    )
    op.create_index(
        "ix_coral_gate_visits_open",
        "coral_gate_visits",
        ["status", "workspace_id", "run_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_coral_gate_visits_inbox",
        "coral_gate_visits",
        ["workspace_id", "owner_user_id", "status", "opened_at", "id"],
        unique=False,
    )
    op.create_table(
        "coral_run_log",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("run_version", sa.BigInteger(), nullable=False),
        sa.Column("log_version", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.SmallInteger(), nullable=False),
        sa.Column("audit_only", sa.Boolean(), nullable=False),
        sa.Column("actor_kind", sa.SmallInteger(), nullable=False),
        sa.Column("actor_ref", sa.String(128), nullable=True),
        sa.Column("activation_id", sa.String(32), nullable=True),
        sa.Column("node_id", CaseSensitiveString(64), nullable=True),
        sa.Column("scope_key", CaseSensitiveString(512), nullable=True),
        sa.Column("idempotency_cksum", CHECKSUM32, nullable=True),
        sa.Column("body", CAPPED_TEXT, nullable=False),
        sa.Column("body_ref", sa.String(512), nullable=True),
        sa.Column("view_patch", CAPPED_TEXT, nullable=True),
        sa.Column("view_patch_ref", sa.String(512), nullable=True),
        sa.Column("created_at_us", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "run_id",
            "idempotency_cksum",
            name="uq_coral_run_log_idempotency",
        ),
        sa.CheckConstraint(
            "kind IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)",
            name="ck_coral_run_log_kind",
        ),
        sa.CheckConstraint(
            "actor_kind IN (1, 2, 3, 4, 5)",
            name="ck_coral_run_log_actor_kind",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "run_id",
            "seq",
            name="pk_coral_run_log",
        ),
    )
    op.create_index(
        "ix_coral_run_log_activation",
        "coral_run_log",
        ["workspace_id", "run_id", "activation_id", "seq"],
        unique=False,
    )
    op.create_table(
        "coral_simulation_cases",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("workflow_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("script", CAPPED_TEXT, nullable=False),
        sa.Column("expectation", CAPPED_TEXT, nullable=True),
        sa.Column("last_version_id", sa.String(32), nullable=True),
        sa.Column("last_result", sa.SmallInteger(), nullable=True),
        sa.Column("last_run_at", sa.BigInteger(), nullable=True),
        sa.Column("last_report_ref", sa.String(512), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "last_result IS NULL OR last_result IN (1, 2, 3)",
            name="ck_coral_simulation_cases_last_result",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_coral_simulation_cases",
        ),
    )
    op.create_index(
        "ix_coral_simulation_cases_workflow",
        "coral_simulation_cases",
        ["workspace_id", "workflow_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "coral_blob_refs",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("scope_id", sa.String(32), nullable=False),
        sa.Column("key_cksum", CHECKSUM32, nullable=False),
        sa.Column("scope_kind", sa.SmallInteger(), nullable=False),
        sa.Column("artifact_key", sa.String(512), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", CHECKSUM32, nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "scope_kind IN (1, 2, 3, 4)",
            name="ck_coral_blob_refs_scope_kind",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "scope_id",
            "key_cksum",
            name="pk_coral_blob_refs",
        ),
    )
    op.create_table(
        "coral_work",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("node_id", CaseSensitiveString(64), nullable=True),
        sa.Column("scope_key", CaseSensitiveString(512), nullable=True),
        sa.Column("slot_generation", sa.SmallInteger(), nullable=True),
        sa.Column("payload", CAPPED_TEXT, nullable=False),
        sa.Column("owner_key", CaseSensitiveString(64), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("available_at", sa.BigInteger(), nullable=False),
        sa.Column("lease_expires_at", sa.BigInteger(), nullable=True),
        sa.Column("lease_holder", sa.String(64), nullable=True),
        sa.Column("result", CAPPED_TEXT, nullable=True),
        sa.Column("result_ref", sa.String(512), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("idempotency_cksum", CHECKSUM32, nullable=False),
        sa.Column("created_at_us", sa.BigInteger(), nullable=False),
        sa.Column("finished_at", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "status IN (1, 2, 3, 4, 5)",
            name="ck_coral_work_status",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "run_id",
            "idempotency_cksum",
            name="uq_coral_work_idempotency",
        ),
        sa.CheckConstraint(
            "kind IN (1, 2, 3)",
            name="ck_coral_work_kind",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "id",
            name="pk_coral_work",
        ),
    )
    op.create_index(
        "ix_coral_work_ready",
        "coral_work",
        ["status", "available_at", "workspace_id", "run_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_coral_work_run",
        "coral_work",
        ["workspace_id", "run_id", "status", "id"],
        unique=False,
    )
    op.create_index(
        "ix_coral_work_expired",
        "coral_work",
        ["status", "lease_expires_at", "workspace_id", "run_id", "id"],
        unique=False,
    )
    op.create_table(
        "coral_worker_leases",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("name", CaseSensitiveString(64), nullable=False),
        sa.Column("holder_id", sa.String(64), nullable=False),
        sa.Column("acquired_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "name",
            name="pk_coral_worker_leases",
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_coral_work_expired", table_name="coral_work")
    op.drop_index("ix_coral_work_run", table_name="coral_work")
    op.drop_index("ix_coral_work_ready", table_name="coral_work")
    op.drop_index("ix_coral_simulation_cases_workflow", table_name="coral_simulation_cases")
    op.drop_index("ix_coral_run_log_activation", table_name="coral_run_log")
    op.drop_index("ix_coral_gate_visits_inbox", table_name="coral_gate_visits")
    op.drop_index("ix_coral_gate_visits_open", table_name="coral_gate_visits")
    op.drop_index("ix_coral_handoffs_activation", table_name="coral_handoffs")
    op.drop_index("ix_coral_agent_slots_activation", table_name="coral_agent_slots")
    op.drop_index("ix_coral_agent_slots_expired", table_name="coral_agent_slots")
    op.drop_index("ix_coral_activations_created", table_name="coral_activations")
    op.drop_index("ix_coral_activations_status", table_name="coral_activations")
    op.drop_index("ix_coral_runs_owner", table_name="coral_runs")
    op.drop_index("ix_coral_runs_active", table_name="coral_runs")
    op.drop_index("ix_coral_runs_version", table_name="coral_runs")
    op.drop_index("ix_coral_runs_workflow", table_name="coral_runs")
    op.drop_index("ix_coral_workflow_versions_workflow", table_name="coral_workflow_versions")
    op.drop_index("ix_coral_workflows_owner", table_name="coral_workflows")
    op.drop_table("coral_worker_leases")
    op.drop_table("coral_work")
    op.drop_table("coral_blob_refs")
    op.drop_table("coral_simulation_cases")
    op.drop_table("coral_run_log")
    op.drop_table("coral_gate_visits")
    op.drop_table("coral_handoff_items")
    op.drop_table("coral_handoffs")
    op.drop_table("coral_agent_slots")
    op.drop_table("coral_join_arrivals")
    op.drop_table("coral_activations")
    op.drop_table("coral_run_specs")
    op.drop_table("coral_runs")
    op.drop_table("coral_workflow_drafts")
    op.drop_table("coral_workflow_versions")
    op.drop_table("coral_workflows")
