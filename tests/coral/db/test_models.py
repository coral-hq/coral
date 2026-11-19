"""Comprehensive tests for Coral ORM models, types, enum codecs, and base."""

from __future__ import annotations

import pytest
from sqlalchemy import (
    BINARY,
    VARCHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.dialects.mysql import VARCHAR as MySQLVarchar
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.db import (
    AlertRow,
    CoralBase,
    GateVisitRow,
    RunRow,
    SessionBindingRow,
    StableIdRow,
    WorkflowRow,
    WorkRow,
    WorkspaceOpIntentRow,
)
from coral.db import enum_codecs as ec
from coral.db.types import CAPPED_TEXT, CHECKSUM32, MAX_STORED_BYTES, CaseSensitiveString
from omnigent.db.db_models import ConversationBase, OmnigentBase

EXPECTED_TABLE_NAMES = frozenset(
    {
        "coral_workflows",
        "coral_workflow_versions",
        "coral_workflow_drafts",
        "coral_runs",
        "coral_run_specs",
        "coral_activations",
        "coral_join_arrivals",
        "coral_agent_slots",
        "coral_handoffs",
        "coral_handoff_items",
        "coral_gate_visits",
        "coral_run_log",
        "coral_simulation_cases",
        "coral_blob_refs",
        "coral_work",
        "coral_worker_leases",
        "coral_session_bindings",
        "coral_stable_ids",
        "coral_workspace_op_intents",
        "coral_tool_replies",
        "coral_alerts",
    }
)


def _column_index_byte_length(col: Column) -> int:
    t = col.type
    if hasattr(t, "impl") and t.impl is not None:
        t = t.impl
    if hasattr(t, "_variant_mapping") and "mysql" in t._variant_mapping:
        t = t._variant_mapping["mysql"]

    if isinstance(t, (String, VARCHAR, MySQLVarchar)):
        length = t.length or 255
        return length * 4
    if isinstance(t, (LargeBinary, BINARY)):
        return t.length or 32
    if isinstance(t, BigInteger):
        return 8
    if isinstance(t, Integer):
        return 4
    if isinstance(t, SmallInteger):
        return 2
    if isinstance(t, Boolean):
        return 1
    return 8


def test_exactly_21_tables_registered_and_no_metadata_overlap() -> None:
    tables = CoralBase.metadata.tables
    assert set(tables.keys()) == EXPECTED_TABLE_NAMES
    assert len(tables) == 21

    omnigent_tables = set(OmnigentBase.metadata.tables.keys())
    conversation_tables = set(ConversationBase.metadata.tables.keys())

    assert tables.keys().isdisjoint(omnigent_tables)
    assert tables.keys().isdisjoint(conversation_tables)


def test_zero_foreign_keys_across_all_tables() -> None:
    for name, table in CoralBase.metadata.tables.items():
        assert len(table.foreign_keys) == 0, f"Table {name} has foreign keys: {table.foreign_keys}"


def test_primary_keys_lead_with_workspace_id() -> None:
    for name, table in CoralBase.metadata.tables.items():
        pk_cols = [c.name for c in table.primary_key.columns]
        assert len(pk_cols) >= 2, f"Table {name} PK too short: {pk_cols}"
        assert pk_cols[0] == "workspace_id", (
            f"Table {name} does not lead with workspace_id: {pk_cols}"
        )
        assert isinstance(table.c.workspace_id.type, BigInteger), (
            f"Table {name} workspace_id is not BigInteger"
        )


def test_constraint_and_index_naming_prefixes() -> None:
    for table_name, table in CoralBase.metadata.tables.items():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint):
                name = constraint.name
                assert isinstance(name, str), f"Unnamed check constraint in {table_name}"
                assert name.startswith("ck_coral_"), (
                    f"Check constraint {name} on {table_name} missing 'ck_coral_' prefix"
                )
            elif isinstance(constraint, UniqueConstraint):
                name = constraint.name
                assert isinstance(name, str), f"Unnamed unique constraint in {table_name}"
                assert name.startswith("uq_coral_"), (
                    f"Unique constraint {name} on {table_name} missing 'uq_coral_' prefix"
                )

        for index in table.indexes:
            ix_name = index.name
            assert isinstance(ix_name, str), f"Unnamed index in {table_name}"
            prefix = "uq_coral_" if index.unique else "ix_coral_"
            assert ix_name.startswith(prefix), (
                f"Index {ix_name} on {table_name} missing {prefix!r} prefix"
            )


def test_mysql_innodb_index_width_under_3072_bytes() -> None:
    for table in CoralBase.metadata.sorted_tables:
        pk_width = sum(_column_index_byte_length(c) for c in table.primary_key.columns)
        assert pk_width <= 3072, f"PK for {table.name} exceeds 3072 bytes ({pk_width})"

        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                uq_width = sum(_column_index_byte_length(c) for c in constraint.columns)
                assert uq_width <= 3072, (
                    f"UQ {constraint.name} on {table.name} exceeds 3072 bytes ({uq_width})"
                )

        for index in table.indexes:
            ix_width = sum(_column_index_byte_length(c) for c in index.columns)
            assert ix_width <= 3072, (
                f"Index {index.name} on {table.name} exceeds 3072 bytes ({ix_width})"
            )


def test_exact_internal_and_external_id_lengths() -> None:
    internal_id_columns: dict[str, set[str]] = {
        "coral_workflows": {"id", "latest_version_id"},
        "coral_workflow_versions": {"id", "workflow_id", "parent_version_id"},
        "coral_workflow_drafts": {"workflow_id"},
        "coral_runs": {"id", "workflow_id", "version_id"},
        "coral_run_specs": {"run_id"},
        "coral_activations": {"id", "run_id", "parent_activation_id"},
        "coral_join_arrivals": {"run_id", "activation_id", "source_activation_id", "handoff_id"},
        "coral_agent_slots": {"id", "run_id", "activation_id"},
        "coral_handoffs": {"id", "run_id", "activation_id", "slot_id"},
        "coral_handoff_items": {"run_id", "handoff_id"},
        "coral_gate_visits": {"id", "run_id", "activation_id"},
        "coral_run_log": {"run_id", "activation_id"},
        "coral_simulation_cases": {"id", "workflow_id", "last_version_id"},
        "coral_blob_refs": {"scope_id"},
        "coral_work": {"id", "run_id"},
        "coral_session_bindings": {"run_id"},
        "coral_stable_ids": {"stable_id", "run_id"},
        "coral_workspace_op_intents": {"run_id"},
        "coral_tool_replies": {"run_id"},
        "coral_alerts": {"id", "run_id", "subject_id"},
    }

    external_ref_columns: dict[str, set[str]] = {
        "coral_workflows": {"source_host_id"},
        "coral_runs": {"orchestrator_session_id"},
        "coral_run_specs": {"host_id", "repository_id"},
        "coral_agent_slots": {
            "profile_revision_id",
            "session_id",
            "lease_holder",
            "restart_attempt_id",
        },
        "coral_handoffs": {"submitted_by_session_id"},
        "coral_gate_visits": {"elicitation_id", "elicitation_session_id"},
        "coral_work": {"lease_holder"},
        "coral_worker_leases": {"name", "holder_id"},
        "coral_session_bindings": {"session_id", "host_id"},
        "coral_stable_ids": {"session_id"},
        "coral_workspace_op_intents": {"host_id"},
    }

    for table_name, cols in internal_id_columns.items():
        table = CoralBase.metadata.tables[table_name]
        for col_name in cols:
            col = table.c[col_name]
            length = getattr(col.type, "length", None)
            assert length == 32, (
                f"Internal ID column {table_name}.{col_name} length {length} != 32"
            )

    for table_name, cols in external_ref_columns.items():
        table = CoralBase.metadata.tables[table_name]
        for col_name in cols:
            col = table.c[col_name]
            length = getattr(col.type, "length", None)
            assert length == 64, (
                f"External ref column {table_name}.{col_name} length {length} != 64"
            )


def test_workflow_row_backwards_compatibility() -> None:
    # Instantiate with the exact 10 arguments used by SqlWorkflowDefinitionStore.save
    row = WorkflowRow(
        workspace_id=42,
        id="a" * 32,
        workflow_key="my-key",
        name="My Workflow",
        yaml_text="steps: []",
        compiled_json='{"nodes": []}',
        content_hash=b"\x01" * 32,
        validation_state="runnable",
        created_at=1_000,
        updated_at=1_000,
    )
    assert row.workspace_id == 42
    assert row.id == "a" * 32
    assert row.workflow_key == "my-key"
    assert row.source_kind == 1
    assert row.source_host_id is None
    assert row.description is None
    assert row.latest_version_id is None


def test_workflow_row_db_nullability() -> None:
    t = CoralBase.metadata.tables["coral_workflows"]
    assert t.c.yaml_text.nullable is True
    assert t.c.compiled_json.nullable is True
    assert t.c.content_hash.nullable is True
    assert t.c.validation_state.nullable is True
    assert t.c.user_id.nullable is True
    assert t.c.description.nullable is True
    assert t.c.source_host_id.nullable is True
    assert t.c.source_repo_path.nullable is True
    assert t.c.source_file_path.nullable is True
    assert t.c.latest_version_id.nullable is True
    assert t.c.layout_ref.nullable is True
    assert t.c.source_kind.nullable is False
    assert t.c.workflow_key.nullable is False
    assert t.c.name.nullable is False


def test_sqlite_schema_creation_and_check_constraints() -> None:
    engine = create_engine("sqlite:///:memory:")
    CoralBase.metadata.create_all(engine)

    with Session(engine) as session:
        # Valid insert
        wf = WorkflowRow(
            workspace_id=1,
            id="w" * 32,
            workflow_key="valid-flow",
            name="Valid Flow",
            created_at=100,
            updated_at=100,
            source_kind=ec.WorkflowSourceKind.REPO_FILE.value,
        )
        session.add(wf)
        session.commit()

        loaded = session.scalars(select(WorkflowRow).where(WorkflowRow.id == "w" * 32)).one()
        assert loaded.workflow_key == "valid-flow"
        assert loaded.source_kind == 1

        # Check constraint violation on invalid source_kind (e.g. 99)
        invalid_wf = WorkflowRow(
            workspace_id=1,
            id="x" * 32,
            workflow_key="invalid-flow",
            name="Invalid Flow",
            created_at=100,
            updated_at=100,
            source_kind=99,
        )
        session.add(invalid_wf)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Check constraint violation on invalid run status
        invalid_run = RunRow(
            workspace_id=1,
            id="r" * 32,
            workflow_id="w" * 32,
            version_id="v" * 32,
            status=999,
            version=1,
            next_log_seq=1,
            activation_count=0,
            title="Invalid Run",
            engine_version=1,
            state_version=1,
            log_version=1,
            created_at=100,
            updated_at=100,
        )
        session.add(invalid_run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        # Check constraint violation on invalid work status
        invalid_work = WorkRow(
            workspace_id=1,
            id="k" * 32,
            run_id="r" * 32,
            kind=ec.WorkKind.EFFECT.value,
            status=999,
            payload="{}",
            available_at=100,
            idempotency_cksum=b"\x00" * 32,
            created_at_us=100_000,
        )
        session.add(invalid_work)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_enum_codecs_roundtrip_and_errors() -> None:
    codecs_to_test = [
        (
            ec.WORKFLOW_SOURCE_KIND,
            ec.encode_workflow_source_kind,
            ec.decode_workflow_source_kind,
            ec.WorkflowSourceKind,
        ),
        (
            ec.WORKFLOW_VERSION_ORIGIN,
            ec.encode_workflow_version_origin,
            ec.decode_workflow_version_origin,
            ec.WorkflowVersionOrigin,
        ),
        (
            ec.WORKFLOW_VERSION_STATUS,
            ec.encode_workflow_version_status,
            ec.decode_workflow_version_status,
            ec.WorkflowVersionStatus,
        ),
        (
            ec.RUN_STATUS,
            ec.encode_run_status,
            ec.decode_run_status,
            ec.RunStatus,
        ),
        (
            ec.RUN_PAUSE_REASON,
            ec.encode_run_pause_reason,
            ec.decode_run_pause_reason,
            ec.RunPauseReason,
        ),
        (
            ec.RUN_TRIGGER_KIND,
            ec.encode_run_trigger_kind,
            ec.decode_run_trigger_kind,
            ec.RunTriggerKind,
        ),
        (
            ec.RUN_EXECUTION_TARGET,
            ec.encode_run_execution_target,
            ec.decode_run_execution_target,
            ec.RunExecutionTarget,
        ),
        (
            ec.RUN_AUTH_MODE,
            ec.encode_run_auth_mode,
            ec.decode_run_auth_mode,
            ec.RunAuthMode,
        ),
        (
            ec.ACTIVATION_STATUS,
            ec.encode_activation_status,
            ec.decode_activation_status,
            ec.ActivationStatus,
        ),
        (
            ec.ACTIVATION_OUTCOME,
            ec.encode_activation_outcome,
            ec.decode_activation_outcome,
            ec.ActivationOutcome,
        ),
        (
            ec.JOIN_ARRIVAL_OUTCOME,
            ec.encode_join_arrival_outcome,
            ec.decode_join_arrival_outcome,
            ec.JoinArrivalOutcome,
        ),
        (
            ec.SLOT_ROLE,
            ec.encode_slot_role,
            ec.decode_slot_role,
            ec.SlotRole,
        ),
        (
            ec.SLOT_STATUS,
            ec.encode_slot_status,
            ec.decode_slot_status,
            ec.SlotStatus,
        ),
        (
            ec.SLOT_TURN_ORIGIN,
            ec.encode_slot_turn_origin,
            ec.decode_slot_turn_origin,
            ec.SlotTurnOrigin,
        ),
        (
            ec.HANDOFF_STATUS,
            ec.encode_handoff_status,
            ec.decode_handoff_status,
            ec.HandoffStatus,
        ),
        (
            ec.HANDOFF_SUBMIT_STATUS,
            ec.encode_handoff_submit_status,
            ec.decode_handoff_submit_status,
            ec.HandoffSubmitStatus,
        ),
        (
            ec.HANDOFF_EVIDENCE_OUTCOME,
            ec.encode_handoff_evidence_outcome,
            ec.decode_handoff_evidence_outcome,
            ec.HandoffEvidenceOutcome,
        ),
        (
            ec.HANDOFF_REJECTION_CODE,
            ec.encode_handoff_rejection_code,
            ec.decode_handoff_rejection_code,
            ec.HandoffRejectionCode,
        ),
        (
            ec.GATE_VISIT_STATUS,
            ec.encode_gate_visit_status,
            ec.decode_gate_visit_status,
            ec.GateVisitStatus,
        ),
        (
            ec.ACTOR_KIND,
            ec.encode_actor_kind,
            ec.decode_actor_kind,
            ec.ActorKind,
        ),
        (
            ec.LOG_KIND,
            ec.encode_log_kind,
            ec.decode_log_kind,
            ec.LogKind,
        ),
        (
            ec.SIMULATION_CASE_STATUS,
            ec.encode_simulation_case_status,
            ec.decode_simulation_case_status,
            ec.SimulationCaseStatus,
        ),
        (
            ec.BLOB_REF_KIND,
            ec.encode_blob_ref_kind,
            ec.decode_blob_ref_kind,
            ec.BlobRefKind,
        ),
        (
            ec.WORK_KIND,
            ec.encode_work_kind,
            ec.decode_work_kind,
            ec.WorkKind,
        ),
        (
            ec.WORK_STATUS,
            ec.encode_work_status,
            ec.decode_work_status,
            ec.WorkStatus,
        ),
        (
            ec.SESSION_BINDING_ROLE,
            ec.encode_session_binding_role,
            ec.decode_session_binding_role,
            ec.SessionBindingRole,
        ),
        (
            ec.SESSION_BINDING_PROGRESS,
            ec.encode_session_binding_progress,
            ec.decode_session_binding_progress,
            ec.SessionBindingProgress,
        ),
        (
            ec.STABLE_ID_KIND,
            ec.encode_stable_id_kind,
            ec.decode_stable_id_kind,
            ec.StableIdKind,
        ),
        (
            ec.WORKSPACE_OP_INTENT_OP,
            ec.encode_workspace_op_intent_op,
            ec.decode_workspace_op_intent_op,
            ec.WorkspaceOpIntentOp,
        ),
        (
            ec.ALERT_KIND,
            ec.encode_alert_kind,
            ec.decode_alert_kind,
            ec.AlertKind,
        ),
        (
            ec.ALERT_PRIORITY,
            ec.encode_alert_priority,
            ec.decode_alert_priority,
            ec.AlertPriority,
        ),
        (
            ec.ALERT_STATUS,
            ec.encode_alert_status,
            ec.decode_alert_status,
            ec.AlertStatus,
        ),
    ]

    for table, encode_fn, decode_fn, enum_cls in codecs_to_test:
        for name, code in table.items():
            # Test string encode
            assert encode_fn(name) == code
            # Test uppercase name encode
            assert encode_fn(name.upper()) == code
            # Test enum member encode
            member = getattr(enum_cls, name.upper())
            assert encode_fn(member) == code
            # Test decode
            assert decode_fn(code) == name
            # Test enum constructor from int
            assert enum_cls(code) == member

        # Test invalid name encode error
        with pytest.raises(ValueError, match=r"unknown .* value"):
            encode_fn("non_existent_value_xyz")

        # Test invalid code decode error
        with pytest.raises(ValueError, match=r"unknown .* code"):
            decode_fn(99_999)

    with pytest.raises(ValueError, match=r"unknown coral_runs\.status code"):
        ec.encode_run_status(ec.WorkKind.SIGNAL)  # type: ignore[arg-type]
    assert ec.encode_run_status(ec.RunStatusStr.RUNNING) == ec.RunStatus.RUNNING


def test_stored_codes_for_drift_and_session_facade_enums() -> None:
    """Stored integers are a persistence contract; renumbering breaks existing rows."""
    assert ec.encode_run_pause_reason("drift") == 12
    assert ec.SESSION_BINDING_ROLE == {"anchor": 1, "step": 2}
    assert ec.SESSION_BINDING_PROGRESS == {"reserved": 1, "row_created": 2, "initialized": 3}
    assert ec.STABLE_ID_KIND == {"brief": 1, "steer": 2, "nudge": 3}
    assert ec.WORKSPACE_OP_INTENT_OP == {"commit": 1, "salvage": 2, "reset": 3}
    # Binding progress is compared for monotonic updates and "at least row_created" checks.
    assert (
        ec.SessionBindingProgress.RESERVED
        < ec.SessionBindingProgress.ROW_CREATED
        < ec.SessionBindingProgress.INITIALIZED
    )


def test_stored_codes_for_engine_bridge_enums() -> None:
    """Stored integers are a persistence contract; renumbering breaks existing rows."""
    assert ec.encode_run_pause_reason("auth") == ec.RunPauseReason.AUTH == 13
    assert ec.encode_slot_status("evaluating") == ec.SlotStatus.EVALUATING == 10
    assert ec.encode_slot_status("closing") == ec.SlotStatus.CLOSING == 11
    assert ec.encode_log_kind("engine") == ec.LogKind.ENGINE == 22


def test_engine_bridge_columns_table_and_binding_index() -> None:
    tables = CoralBase.metadata.tables
    versions = tables["coral_workflow_versions"]
    # A pinned version holds its graph inline, so the blob refs are optional.
    for name in ("yaml_ref", "compiled_ref", "yaml_text", "compiled_json"):
        assert versions.c[name].nullable is True, name
    assert versions.c.compiled_json.type.max_stored_bytes == MAX_STORED_BYTES
    assert tables["coral_run_specs"].c.engine_config.nullable is True
    assert isinstance(tables["coral_work"].c.held_since.type, BigInteger)
    assert tables["coral_work"].c.held_since.nullable is True
    (purge,) = [
        index for index in tables["coral_work"].indexes if index.name == "ix_coral_work_finished"
    ]
    assert [column.name for column in purge.columns] == [
        "kind",
        "status",
        "finished_at",
        "workspace_id",
        "id",
    ]

    replies = tables["coral_tool_replies"]
    assert [column.name for column in replies.primary_key.columns] == [
        "workspace_id",
        "run_id",
        "cksum",
    ]
    assert replies.primary_key.name == "pk_coral_tool_replies"
    for name in ("reply", "run_version", "created_at_us"):
        assert replies.c[name].nullable is False, name

    (index,) = [
        index
        for index in tables["coral_session_bindings"].indexes
        if index.name == "uq_coral_session_bindings_slot_generation"
    ]
    assert index.unique is True
    assert [column.name for column in index.columns] == [
        "workspace_id",
        "run_id",
        "slot_id",
        "session_generation",
    ]


def test_stored_codes_for_alert_enums() -> None:
    """Stored integers are a persistence contract; renumbering breaks existing rows."""
    assert ec.ALERT_KIND == {
        "gate": 1,
        "question": 2,
        "pause": 3,
        "watchdog": 4,
        "overdue": 5,
        "reaction": 6,
        "run_completed": 7,
        "run_failed": 8,
        "run_cancelled": 9,
    }
    # The inbox lists alerts in ascending priority code, so normal sorts before low.
    assert ec.ALERT_PRIORITY == {"normal": 1, "low": 2}
    assert ec.AlertPriority.NORMAL < ec.AlertPriority.LOW
    assert ec.ALERT_STATUS == {"open": 1, "acked": 2, "resolved": 3}


def test_alert_table_keys_indexes_and_checks() -> None:
    alerts = AlertRow.__table__
    assert alerts.primary_key.name == "pk_coral_alerts"
    assert [column.name for column in alerts.primary_key.columns] == ["workspace_id", "id"]
    nullable = {column.name for column in alerts.columns if column.nullable}
    assert nullable == {
        "owner_user_id",
        "account_generation",
        "acked_at",
        "acked_by",
        "resolved_at",
    }
    assert alerts.c.payload.type.max_stored_bytes == MAX_STORED_BYTES
    indexes = {index.name: [column.name for column in index.columns] for index in alerts.indexes}
    assert indexes == {
        # The owner's feed: open rows by priority, then newest first.
        "ix_coral_alerts_inbox": [
            "workspace_id",
            "owner_user_id",
            "status",
            "priority",
            "created_at",
            "id",
        ],
        # Resolutions match a run's alerts by what they point at.
        "ix_coral_alerts_subject": ["workspace_id", "run_id", "subject_id"],
    }
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in alerts.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert checks == {
        "ck_coral_alerts_kind": "kind IN (1, 2, 3, 4, 5, 6, 7, 8, 9)",
        "ck_coral_alerts_priority": "priority IN (1, 2)",
        "ck_coral_alerts_status": "status IN (1, 2, 3)",
    }


def test_gate_visit_token_holds_a_full_engine_token_case_sensitively() -> None:
    token = GateVisitRow.__table__.c.token
    assert token.type.length == 512
    assert token.nullable is False
    mysql_type = token.type._variant_mapping["mysql"]
    assert (mysql_type.length, mysql_type.collation) == (512, "utf8mb4_bin")


def test_session_facade_tables_enforce_their_enum_checks_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    CoralBase.metadata.create_all(engine)
    binding = {
        "workspace_id": 1,
        "session_id": "s" * 32,
        "run_id": "r" * 32,
        "role": int(ec.SessionBindingRole.ANCHOR),
        "slot_id": None,
        "slot_role": None,
        "effect_cksum": b"\x01" * 32,
        "session_generation": 1,
        "host_id": None,
        "progress": int(ec.SessionBindingProgress.RESERVED),
        "created_at": 100,
        "updated_at": 100,
    }
    stable_id = {
        "workspace_id": 1,
        "stable_id": "i" * 32,
        "run_id": "r" * 32,
        "session_id": "s" * 32,
        "effect_cksum": b"\x02" * 32,
        "content_cksum": b"\x04" * 32,
        "kind": int(ec.StableIdKind.BRIEF),
        "session_generation": 1,
        "created_at": 100,
    }
    intent = {
        "workspace_id": 1,
        "op_key": "k" * 32,
        "run_id": "r" * 32,
        "op": int(ec.WorkspaceOpIntentOp.COMMIT),
        "host_id": "h" * 32,
        "root": "/repo-worktrees/run",
        "expected_head": None,
        "created_at": 100,
    }
    valid_rows = [
        SessionBindingRow(**binding),
        StableIdRow(**stable_id),
        WorkspaceOpIntentRow(**intent),
    ]
    # Each invalid binding has its own effect checksum so only the enum check can fail.
    invalid_rows = [
        SessionBindingRow(**{**binding, "session_id": "a", "effect_cksum": b"a" * 32, "role": 9}),
        SessionBindingRow(
            **{**binding, "session_id": "b", "effect_cksum": b"b" * 32, "slot_role": 9}
        ),
        SessionBindingRow(
            **{**binding, "session_id": "c", "effect_cksum": b"c" * 32, "progress": 9}
        ),
        StableIdRow(**{**stable_id, "stable_id": "j" * 32, "kind": 9}),
        WorkspaceOpIntentRow(**{**intent, "op_key": "l" * 32, "op": 9}),
    ]
    with Session(engine) as session:
        session.add_all(valid_rows)
        session.commit()
        for row in invalid_rows:
            session.add(row)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()


def test_session_binding_effect_checksum_is_unique_within_a_run() -> None:
    engine = create_engine("sqlite:///:memory:")
    CoralBase.metadata.create_all(engine)
    row = {
        "workspace_id": 1,
        "run_id": "r" * 32,
        "role": int(ec.SessionBindingRole.STEP),
        "slot_id": "slot-a",
        "slot_role": int(ec.SlotRole.STEP_AGENT),
        "effect_cksum": b"\x03" * 32,
        "session_generation": 1,
        "host_id": "h" * 32,
        "progress": int(ec.SessionBindingProgress.RESERVED),
        "created_at": 100,
        "updated_at": 100,
    }
    with Session(engine) as session:
        session.add(SessionBindingRow(session_id="s" * 32, **row))
        session.commit()
        session.add(SessionBindingRow(session_id="t" * 32, **row))
        with pytest.raises(IntegrityError):
            session.commit()


def test_types_and_constants() -> None:
    assert MAX_STORED_BYTES == 16_383
    assert CAPPED_TEXT.max_stored_bytes == 16_383
    assert CHECKSUM32.length == 32
    cs = CaseSensitiveString(128)
    assert cs.length == 128
