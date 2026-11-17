"""Name <-> int codecs for Coral database columns stored as SMALLINT."""

from __future__ import annotations

from enum import IntEnum, StrEnum

from sqlalchemy import CheckConstraint

from omnigent.db.enum_codecs import decode_enum, encode_enum

# ── Code Tables (name -> stable int code) ───────────────────────────────────

WORKFLOW_SOURCE_KIND: dict[str, int] = {
    "repo_file": 1,
    "uploaded": 2,
    "template": 3,
}

WORKFLOW_VERSION_ORIGIN: dict[str, int] = {
    "saved": 1,
    "amendment": 2,
    "imported": 3,
    "template": 4,
}

WORKFLOW_VERSION_STATUS: dict[str, int] = {
    "valid": 1,
    "invalid": 2,
}

RUN_STATUS: dict[str, int] = {
    "starting": 1,
    "running": 2,
    "paused": 3,
    "completed": 4,
    "failed": 5,
    "cancelled": 6,
}

RUN_PAUSE_REASON: dict[str, int] = {
    "gate": 1,
    "budget": 2,
    "plan_limit": 3,
    "rejected_calls": 4,
    "infra": 5,
    "liveness": 6,
    "user": 7,
    "authority_revoked": 8,
    "merge_conflict": 9,
    "failure_path": 10,
    "engine_upgrade": 11,
    "drift": 12,
}

RUN_TRIGGER_KIND: dict[str, int] = {
    "manual": 1,
    "api": 2,
    "schedule": 3,
    "webhook": 4,
}

RUN_EXECUTION_TARGET: dict[str, int] = {
    "connected_host": 1,
    "managed_sandbox": 2,
}

RUN_AUTH_MODE: dict[str, int] = {
    "subscription": 1,
    "api_key": 2,
    "mixed": 3,
}

ACTIVATION_STATUS: dict[str, int] = {
    "waiting_join": 1,
    "ready": 2,
    "starting": 3,
    "running": 4,
    "evaluating": 5,
    "closed": 6,
    "restarting": 7,
    "taken_over": 8,
    "paused": 9,
}

ACTIVATION_OUTCOME: dict[str, int] = {
    "done": 1,
    "blocked": 2,
    "failed": 3,
    "skipped": 4,
    "cancelled": 5,
    "superseded": 6,
    "at_limit": 7,
}

JOIN_ARRIVAL_OUTCOME: dict[str, int] = {
    "delivered": 1,
    "failed": 2,
    "skipped": 3,
}

SLOT_ROLE: dict[str, int] = {
    "step_agent": 1,
    "orchestrator": 2,
    "verifier": 3,
    "merge_resolver": 4,
}

SLOT_STATUS: dict[str, int] = {
    "pending": 1,
    "session_created": 2,
    "briefed": 3,
    "working": 4,
    "handoff_accepted": 5,
    "rejected": 6,
    "refreshing": 7,
    "restarting": 8,
    "closed": 9,
}

SLOT_TURN_ORIGIN: dict[str, int] = {
    "engine": 1,
    "user": 2,
}

HANDOFF_STATUS: dict[str, int] = {
    "accepted": 1,
    "rejected": 2,
    "superseded": 3,
}

HANDOFF_SUBMIT_STATUS: dict[str, int] = {
    "done": 1,
    "blocked": 2,
}

HANDOFF_EVIDENCE_OUTCOME: dict[str, int] = {
    "passed": 1,
    "failed": 2,
    "unknown": 3,
    "not_required": 4,
}

HANDOFF_REJECTION_CODE: dict[str, int] = {
    "missing_report": 1,
    "missing_label": 2,
    "invalid_label": 3,
    "missing_items": 4,
    "not_active": 5,
    "evidence_missing": 6,
}

GATE_VISIT_STATUS: dict[str, int] = {
    "open": 1,
    "resolved": 2,
    "superseded": 3,
    "cancelled": 4,
}

ACTOR_KIND: dict[str, int] = {
    "engine": 1,
    "orchestrator": 2,
    "step_agent": 3,
    "user": 4,
    "simulator": 5,
}

LOG_KIND: dict[str, int] = {
    "run_started": 1,
    "activation_started": 2,
    "handoff_submitted": 3,
    "handoff_rejected": 4,
    "evidence_result": 5,
    "decision": 6,
    "gate_opened": 7,
    "gate_answered": 8,
    "arrow_taken": 9,
    "timer_fired": 10,
    "effect_succeeded": 11,
    "effect_failed": 12,
    "paused": 13,
    "resumed": 14,
    "amendment_applied": 15,
    "signal_ignored": 16,
    "take_over": 17,
    "hand_back": 18,
    "alert": 19,
    "run_finished": 20,
    "command_rejected": 21,
}

SIMULATION_CASE_STATUS: dict[str, int] = {
    "passed": 1,
    "failed": 2,
    "error": 3,
}

BLOB_REF_KIND: dict[str, int] = {
    "run": 1,
    "workflow": 2,
    "profile": 3,
    "simulation": 4,
}

WORK_KIND: dict[str, int] = {
    "signal": 1,
    "timer": 2,
    "effect": 3,
}

WORK_STATUS: dict[str, int] = {
    "pending": 1,
    "claimed": 2,
    "succeeded": 3,
    "failed": 4,
    "abandoned": 5,
}

SESSION_BINDING_ROLE: dict[str, int] = {
    "anchor": 1,
    "step": 2,
}

SESSION_BINDING_PROGRESS: dict[str, int] = {
    "reserved": 1,
    "row_created": 2,
    "initialized": 3,
}

STABLE_ID_KIND: dict[str, int] = {
    "brief": 1,
    "steer": 2,
    "nudge": 3,
}

WORKSPACE_OP_INTENT_OP: dict[str, int] = {
    "commit": 1,
    "salvage": 2,
    "reset": 3,
}


# ── Python Enums (IntEnum & StrEnum) ────────────────────────────────────────


class WorkflowSourceKind(IntEnum):
    REPO_FILE = 1
    UPLOADED = 2
    TEMPLATE = 3


class WorkflowVersionOrigin(IntEnum):
    SAVED = 1
    AMENDMENT = 2
    IMPORTED = 3
    TEMPLATE = 4


class WorkflowVersionStatus(IntEnum):
    VALID = 1
    INVALID = 2


WorkflowValidationState = WorkflowVersionStatus


class RunStatus(IntEnum):
    STARTING = 1
    RUNNING = 2
    PAUSED = 3
    COMPLETED = 4
    FAILED = 5
    CANCELLED = 6


class RunPauseReason(IntEnum):
    GATE = 1
    BUDGET = 2
    PLAN_LIMIT = 3
    REJECTED_CALLS = 4
    INFRA = 5
    LIVENESS = 6
    USER = 7
    AUTHORITY_REVOKED = 8
    MERGE_CONFLICT = 9
    FAILURE_PATH = 10
    ENGINE_UPGRADE = 11
    DRIFT = 12


class RunTriggerKind(IntEnum):
    MANUAL = 1
    API = 2
    SCHEDULE = 3
    WEBHOOK = 4


class RunExecutionTarget(IntEnum):
    CONNECTED_HOST = 1
    MANAGED_SANDBOX = 2


class RunAuthMode(IntEnum):
    SUBSCRIPTION = 1
    API_KEY = 2
    MIXED = 3


class ActivationStatus(IntEnum):
    WAITING_JOIN = 1
    READY = 2
    STARTING = 3
    RUNNING = 4
    EVALUATING = 5
    CLOSED = 6
    RESTARTING = 7
    TAKEN_OVER = 8
    PAUSED = 9


class ActivationOutcome(IntEnum):
    DONE = 1
    BLOCKED = 2
    FAILED = 3
    SKIPPED = 4
    CANCELLED = 5
    SUPERSEDED = 6
    AT_LIMIT = 7


class JoinArrivalOutcome(IntEnum):
    DELIVERED = 1
    FAILED = 2
    SKIPPED = 3


class SlotRole(IntEnum):
    STEP_AGENT = 1
    ORCHESTRATOR = 2
    VERIFIER = 3
    MERGE_RESOLVER = 4


LeaseOwnerRole = SlotRole


class SlotStatus(IntEnum):
    PENDING = 1
    SESSION_CREATED = 2
    BRIEFED = 3
    WORKING = 4
    HANDOFF_ACCEPTED = 5
    REJECTED = 6
    REFRESHING = 7
    RESTARTING = 8
    CLOSED = 9


class SlotTurnOrigin(IntEnum):
    ENGINE = 1
    USER = 2


class HandoffStatus(IntEnum):
    ACCEPTED = 1
    REJECTED = 2
    SUPERSEDED = 3


class HandoffSubmitStatus(IntEnum):
    DONE = 1
    BLOCKED = 2


class HandoffEvidenceOutcome(IntEnum):
    PASSED = 1
    FAILED = 2
    UNKNOWN = 3
    NOT_REQUIRED = 4


class HandoffRejectionCode(IntEnum):
    MISSING_REPORT = 1
    MISSING_LABEL = 2
    INVALID_LABEL = 3
    MISSING_ITEMS = 4
    NOT_ACTIVE = 5
    EVIDENCE_MISSING = 6


class GateVisitStatus(IntEnum):
    OPEN = 1
    RESOLVED = 2
    SUPERSEDED = 3
    CANCELLED = 4


class ActorKind(IntEnum):
    ENGINE = 1
    ORCHESTRATOR = 2
    STEP_AGENT = 3
    USER = 4
    SIMULATOR = 5


class LogKind(IntEnum):
    RUN_STARTED = 1
    ACTIVATION_STARTED = 2
    HANDOFF_SUBMITTED = 3
    HANDOFF_REJECTED = 4
    EVIDENCE_RESULT = 5
    DECISION = 6
    GATE_OPENED = 7
    GATE_ANSWERED = 8
    ARROW_TAKEN = 9
    TIMER_FIRED = 10
    EFFECT_SUCCEEDED = 11
    EFFECT_FAILED = 12
    PAUSED = 13
    RESUMED = 14
    AMENDMENT_APPLIED = 15
    SIGNAL_IGNORED = 16
    TAKE_OVER = 17
    HAND_BACK = 18
    ALERT = 19
    RUN_FINISHED = 20
    COMMAND_REJECTED = 21


class SimulationCaseStatus(IntEnum):
    PASSED = 1
    FAILED = 2
    ERROR = 3


class BlobRefKind(IntEnum):
    RUN = 1
    WORKFLOW = 2
    PROFILE = 3
    SIMULATION = 4


class WorkKind(IntEnum):
    SIGNAL = 1
    TIMER = 2
    EFFECT = 3


class WorkStatus(IntEnum):
    PENDING = 1
    CLAIMED = 2
    SUCCEEDED = 3
    FAILED = 4
    ABANDONED = 5


class SessionBindingRole(IntEnum):
    ANCHOR = 1
    STEP = 2


class SessionBindingProgress(IntEnum):
    """Ordered create progress; stored progress only ever increases."""

    RESERVED = 1
    ROW_CREATED = 2
    INITIALIZED = 3


class StableIdKind(IntEnum):
    BRIEF = 1
    STEER = 2
    NUDGE = 3


class WorkspaceOpIntentOp(IntEnum):
    COMMIT = 1
    SALVAGE = 2
    RESET = 3


# ── StrEnum Variants ─────────────────────────────────────────────────────────


class WorkflowSourceKindStr(StrEnum):
    REPO_FILE = "repo_file"
    UPLOADED = "uploaded"
    TEMPLATE = "template"


class RunStatusStr(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkKindStr(StrEnum):
    SIGNAL = "signal"
    TIMER = "timer"
    EFFECT = "effect"


class WorkStatusStr(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABANDONED = "abandoned"


# ── Check Constraint Generator ──────────────────────────────────────────────


def make_enum_check_constraint(
    column_name: str,
    table: dict[str, int],
    *,
    name: str,
    nullable: bool = False,
) -> CheckConstraint:
    """Generate a named CheckConstraint for an integer enum column."""
    codes_str = ", ".join(str(c) for c in sorted(table.values()))
    sql = f"{column_name} IN ({codes_str})"
    if nullable:
        sql = f"{column_name} IS NULL OR {sql}"
    return CheckConstraint(sql, name=name)


# ── Encode / Decode Functions ───────────────────────────────────────────────


def _encode_val(
    table: dict[str, int],
    val: str | IntEnum,
    field: str,
    *,
    expected_enum: type[IntEnum],
) -> int:
    if isinstance(val, IntEnum):
        if isinstance(val, expected_enum) and val.value in table.values():
            return int(val.value)
        raise ValueError(f"unknown {field} code: {val!r}")
    return encode_enum(table, str(val).lower(), field=field)


def encode_workflow_source_kind(val: str | WorkflowSourceKind) -> int:
    return _encode_val(
        WORKFLOW_SOURCE_KIND,
        val,
        "coral_workflows.source_kind",
        expected_enum=WorkflowSourceKind,
    )


def decode_workflow_source_kind(code: int) -> str:
    return decode_enum(WORKFLOW_SOURCE_KIND, code, field="coral_workflows.source_kind")


def encode_workflow_version_origin(val: str | WorkflowVersionOrigin) -> int:
    return _encode_val(
        WORKFLOW_VERSION_ORIGIN,
        val,
        "coral_workflow_versions.origin",
        expected_enum=WorkflowVersionOrigin,
    )


def decode_workflow_version_origin(code: int) -> str:
    return decode_enum(WORKFLOW_VERSION_ORIGIN, code, field="coral_workflow_versions.origin")


def encode_workflow_version_status(val: str | WorkflowVersionStatus) -> int:
    return _encode_val(
        WORKFLOW_VERSION_STATUS,
        val,
        "coral_workflow_versions.validation_state",
        expected_enum=WorkflowVersionStatus,
    )


def decode_workflow_version_status(code: int) -> str:
    return decode_enum(
        WORKFLOW_VERSION_STATUS, code, field="coral_workflow_versions.validation_state"
    )


def encode_run_status(val: str | RunStatus) -> int:
    return _encode_val(RUN_STATUS, val, "coral_runs.status", expected_enum=RunStatus)


def decode_run_status(code: int) -> str:
    return decode_enum(RUN_STATUS, code, field="coral_runs.status")


def encode_run_pause_reason(val: str | RunPauseReason) -> int:
    return _encode_val(
        RUN_PAUSE_REASON, val, "coral_runs.pause_reason", expected_enum=RunPauseReason
    )


def decode_run_pause_reason(code: int) -> str:
    return decode_enum(RUN_PAUSE_REASON, code, field="coral_runs.pause_reason")


def encode_run_trigger_kind(val: str | RunTriggerKind) -> int:
    return _encode_val(
        RUN_TRIGGER_KIND, val, "coral_run_specs.trigger_kind", expected_enum=RunTriggerKind
    )


def decode_run_trigger_kind(code: int) -> str:
    return decode_enum(RUN_TRIGGER_KIND, code, field="coral_run_specs.trigger_kind")


def encode_run_execution_target(val: str | RunExecutionTarget) -> int:
    return _encode_val(
        RUN_EXECUTION_TARGET,
        val,
        "coral_run_specs.execution_target",
        expected_enum=RunExecutionTarget,
    )


def decode_run_execution_target(code: int) -> str:
    return decode_enum(RUN_EXECUTION_TARGET, code, field="coral_run_specs.execution_target")


def encode_run_auth_mode(val: str | RunAuthMode) -> int:
    return _encode_val(RUN_AUTH_MODE, val, "coral_run_specs.auth_mode", expected_enum=RunAuthMode)


def decode_run_auth_mode(code: int) -> str:
    return decode_enum(RUN_AUTH_MODE, code, field="coral_run_specs.auth_mode")


def encode_activation_status(val: str | ActivationStatus) -> int:
    return _encode_val(
        ACTIVATION_STATUS, val, "coral_activations.status", expected_enum=ActivationStatus
    )


def decode_activation_status(code: int) -> str:
    return decode_enum(ACTIVATION_STATUS, code, field="coral_activations.status")


def encode_activation_outcome(val: str | ActivationOutcome) -> int:
    return _encode_val(
        ACTIVATION_OUTCOME, val, "coral_activations.outcome", expected_enum=ActivationOutcome
    )


def decode_activation_outcome(code: int) -> str:
    return decode_enum(ACTIVATION_OUTCOME, code, field="coral_activations.outcome")


def encode_join_arrival_outcome(val: str | JoinArrivalOutcome) -> int:
    return _encode_val(
        JOIN_ARRIVAL_OUTCOME,
        val,
        "coral_join_arrivals.outcome",
        expected_enum=JoinArrivalOutcome,
    )


def decode_join_arrival_outcome(code: int) -> str:
    return decode_enum(JOIN_ARRIVAL_OUTCOME, code, field="coral_join_arrivals.outcome")


def encode_slot_role(val: str | SlotRole) -> int:
    return _encode_val(SLOT_ROLE, val, "coral_agent_slots.role", expected_enum=SlotRole)


def decode_slot_role(code: int) -> str:
    return decode_enum(SLOT_ROLE, code, field="coral_agent_slots.role")


def encode_slot_status(val: str | SlotStatus) -> int:
    return _encode_val(SLOT_STATUS, val, "coral_agent_slots.status", expected_enum=SlotStatus)


def decode_slot_status(code: int) -> str:
    return decode_enum(SLOT_STATUS, code, field="coral_agent_slots.status")


def encode_slot_turn_origin(val: str | SlotTurnOrigin) -> int:
    return _encode_val(
        SLOT_TURN_ORIGIN,
        val,
        "coral_agent_slots.last_turn_origin",
        expected_enum=SlotTurnOrigin,
    )


def decode_slot_turn_origin(code: int) -> str:
    return decode_enum(SLOT_TURN_ORIGIN, code, field="coral_agent_slots.last_turn_origin")


def encode_handoff_status(val: str | HandoffStatus) -> int:
    return _encode_val(HANDOFF_STATUS, val, "coral_handoffs.status", expected_enum=HandoffStatus)


def decode_handoff_status(code: int) -> str:
    return decode_enum(HANDOFF_STATUS, code, field="coral_handoffs.status")


def encode_handoff_submit_status(val: str | HandoffSubmitStatus) -> int:
    return _encode_val(
        HANDOFF_SUBMIT_STATUS,
        val,
        "coral_handoffs.submit_status",
        expected_enum=HandoffSubmitStatus,
    )


def decode_handoff_submit_status(code: int) -> str:
    return decode_enum(HANDOFF_SUBMIT_STATUS, code, field="coral_handoffs.submit_status")


def encode_handoff_evidence_outcome(val: str | HandoffEvidenceOutcome) -> int:
    return _encode_val(
        HANDOFF_EVIDENCE_OUTCOME,
        val,
        "coral_handoffs.evidence_outcome",
        expected_enum=HandoffEvidenceOutcome,
    )


def decode_handoff_evidence_outcome(code: int) -> str:
    return decode_enum(HANDOFF_EVIDENCE_OUTCOME, code, field="coral_handoffs.evidence_outcome")


def encode_handoff_rejection_code(val: str | HandoffRejectionCode) -> int:
    return _encode_val(
        HANDOFF_REJECTION_CODE,
        val,
        "coral_handoffs.rejection_code",
        expected_enum=HandoffRejectionCode,
    )


def decode_handoff_rejection_code(code: int) -> str:
    return decode_enum(HANDOFF_REJECTION_CODE, code, field="coral_handoffs.rejection_code")


def encode_gate_visit_status(val: str | GateVisitStatus) -> int:
    return _encode_val(
        GATE_VISIT_STATUS, val, "coral_gate_visits.status", expected_enum=GateVisitStatus
    )


def decode_gate_visit_status(code: int) -> str:
    return decode_enum(GATE_VISIT_STATUS, code, field="coral_gate_visits.status")


def encode_actor_kind(val: str | ActorKind) -> int:
    return _encode_val(ACTOR_KIND, val, "coral_run_log.actor_kind", expected_enum=ActorKind)


def decode_actor_kind(code: int) -> str:
    return decode_enum(ACTOR_KIND, code, field="coral_run_log.actor_kind")


def encode_log_kind(val: str | LogKind) -> int:
    return _encode_val(LOG_KIND, val, "coral_run_log.kind", expected_enum=LogKind)


def decode_log_kind(code: int) -> str:
    return decode_enum(LOG_KIND, code, field="coral_run_log.kind")


def encode_simulation_case_status(val: str | SimulationCaseStatus) -> int:
    return _encode_val(
        SIMULATION_CASE_STATUS,
        val,
        "coral_simulation_cases.last_result",
        expected_enum=SimulationCaseStatus,
    )


def decode_simulation_case_status(code: int) -> str:
    return decode_enum(SIMULATION_CASE_STATUS, code, field="coral_simulation_cases.last_result")


def encode_blob_ref_kind(val: str | BlobRefKind) -> int:
    return _encode_val(BLOB_REF_KIND, val, "coral_blob_refs.scope_kind", expected_enum=BlobRefKind)


def decode_blob_ref_kind(code: int) -> str:
    return decode_enum(BLOB_REF_KIND, code, field="coral_blob_refs.scope_kind")


def encode_work_kind(val: str | WorkKind) -> int:
    return _encode_val(WORK_KIND, val, "coral_work.kind", expected_enum=WorkKind)


def decode_work_kind(code: int) -> str:
    return decode_enum(WORK_KIND, code, field="coral_work.kind")


def encode_work_status(val: str | WorkStatus) -> int:
    return _encode_val(WORK_STATUS, val, "coral_work.status", expected_enum=WorkStatus)


def decode_work_status(code: int) -> str:
    return decode_enum(WORK_STATUS, code, field="coral_work.status")


def encode_session_binding_role(val: str | SessionBindingRole) -> int:
    return _encode_val(
        SESSION_BINDING_ROLE,
        val,
        "coral_session_bindings.role",
        expected_enum=SessionBindingRole,
    )


def decode_session_binding_role(code: int) -> str:
    return decode_enum(SESSION_BINDING_ROLE, code, field="coral_session_bindings.role")


def encode_session_binding_progress(val: str | SessionBindingProgress) -> int:
    return _encode_val(
        SESSION_BINDING_PROGRESS,
        val,
        "coral_session_bindings.progress",
        expected_enum=SessionBindingProgress,
    )


def decode_session_binding_progress(code: int) -> str:
    return decode_enum(SESSION_BINDING_PROGRESS, code, field="coral_session_bindings.progress")


def encode_stable_id_kind(val: str | StableIdKind) -> int:
    return _encode_val(STABLE_ID_KIND, val, "coral_stable_ids.kind", expected_enum=StableIdKind)


def decode_stable_id_kind(code: int) -> str:
    return decode_enum(STABLE_ID_KIND, code, field="coral_stable_ids.kind")


def encode_workspace_op_intent_op(val: str | WorkspaceOpIntentOp) -> int:
    return _encode_val(
        WORKSPACE_OP_INTENT_OP,
        val,
        "coral_workspace_op_intents.op",
        expected_enum=WorkspaceOpIntentOp,
    )


def decode_workspace_op_intent_op(code: int) -> str:
    return decode_enum(WORKSPACE_OP_INTENT_OP, code, field="coral_workspace_op_intents.op")
