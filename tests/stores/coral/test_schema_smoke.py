"""Smoke tests for Coral schema creation and S31 truncation preservation."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from coral.db.migrate import current_coral_revision, ensure_coral_schema
from coral.db.models.core import WorkflowRow
from coral.db.models.work import WorkRow
from omnigent.db.utils import get_or_create_engine


def test_ensure_coral_schema_creates_all_tables_and_allows_row_insertion(db_uri: str) -> None:
    """ensure_coral_schema creates every Coral table and allows inserting/querying models."""
    ensure_coral_schema(db_uri)

    engine = get_or_create_engine(db_uri)
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())

    expected_tables = {
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

    coral_tables = {
        name
        for name in existing_tables
        if name.startswith("coral_") and name != "coral_alembic_version"
    }
    assert coral_tables == expected_tables
    assert len(coral_tables) == 21
    assert "coral_alembic_version" in existing_tables

    current, head = current_coral_revision(db_uri)
    assert current == head == "coral_0004_alerts_and_gates"

    # Insert a WorkflowRow
    with Session(engine) as session:
        wf = WorkflowRow(
            workspace_id=1,
            id="wf_smoke_test_0123456789abcdef",
            workflow_key="smoke_test_key",
            name="Smoke Test Workflow",
            created_at=1700000000,
            updated_at=1700000000,
        )
        session.add(wf)
        session.commit()

    # Query it back
    with Session(engine) as session:
        queried = session.get(WorkflowRow, (1, "wf_smoke_test_0123456789abcdef"))
        assert queried is not None
        assert queried.workflow_key == "smoke_test_key"
        assert queried.name == "Smoke Test Workflow"
        assert queried.source_kind == 1


def test_s31_truncation_preserves_coral_version_and_clears_data(db_uri: str) -> None:
    """Seam S31: Multi-DB test truncation clears coral data while keeping version tables."""
    ensure_coral_schema(db_uri)
    engine = get_or_create_engine(db_uri)

    # 1. Insert data rows across core and work tables
    with Session(engine) as session:
        wf = WorkflowRow(
            workspace_id=42,
            id="wf_trunc_0123456789abcdef0123",
            workflow_key="trunc_test_key",
            name="Truncation Test Workflow",
            created_at=1700000000,
            updated_at=1700000000,
        )
        work = WorkRow(
            workspace_id=42,
            id="wk_trunc_0123456789abcdef0123",
            run_id="rn_trunc_0123456789abcdef0123",
            kind=1,
            status=1,
            payload="test_payload",
            attempts=0,
            available_at=1700000000,
            idempotency_cksum=b"x" * 32,
            created_at_us=1700000000000000,
        )
        session.add(wf)
        session.add(work)
        session.commit()

    # Verify rows exist
    with Session(engine) as session:
        assert session.get(WorkflowRow, (42, "wf_trunc_0123456789abcdef0123")) is not None
        assert session.get(WorkRow, (42, "wk_trunc_0123456789abcdef0123")) is not None

    # 2. Simulate S31 truncation filter exactly as defined in tests/conftest.py:
    # tables = [t for t in inspect(engine).get_table_names() if not t.endswith("alembic_version")]
    dialect = engine.dialect.name
    tables_to_truncate = [
        t for t in sa.inspect(engine).get_table_names() if not t.endswith("alembic_version")
    ]
    operation = "DELETE FROM" if dialect in {"cockroachdb", "sqlite"} else "TRUNCATE TABLE"

    with engine.begin() as conn:
        for table in tables_to_truncate:
            q = f"`{table}`" if dialect == "mysql" else f'"{table}"'
            conn.execute(sa.text(f"{operation} {q}"))

    # 3. Verify data was wiped
    with Session(engine) as session:
        assert session.get(WorkflowRow, (42, "wf_trunc_0123456789abcdef0123")) is None
        assert session.get(WorkRow, (42, "wk_trunc_0123456789abcdef0123")) is None

    # 4. Verify version tables are intact
    inspector = sa.inspect(engine)
    all_tables = set(inspector.get_table_names())
    assert "coral_alembic_version" in all_tables
    assert "alembic_version" in all_tables

    current, head = current_coral_revision(db_uri)
    assert current == head == "coral_0004_alerts_and_gates"
