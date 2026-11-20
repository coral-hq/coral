"""coral_0005 on every DB lane: alerts, full engine gate tokens, and a guarded downgrade."""

from __future__ import annotations

from io import StringIO

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from coral.db import AlertRow, GateVisitRow, RunRow
from coral.db.enum_codecs import (
    AlertKind,
    AlertPriority,
    AlertStatus,
    GateVisitStatus,
    RunStatus,
)
from coral.db.migrate import _build_coral_alembic_config
from omnigent.db.utils import is_cockroachdb
from tests.db.coral._migration_support import (
    coral_revision,
    insert_row,
    insert_run,
    migrate_coral,
    reflected_schema,
)

_ENGINE_BRIDGE = "coral_0003_engine_bridge"
_ALERTS_AND_GATES = "coral_0005_alerts_and_gates"
_WORKSPACE = 1
_RUN = "r" * 32
_ALERTS = AlertRow.__table__
_VISITS = GateVisitRow.__table__
_RUNS = RunRow.__table__
_OPEN = int(GateVisitStatus.OPEN)
# Run start bounds gate tokens at 512 characters, the widened column's width.
_LONG_TOKEN = "A" * 512
# MySQL reports CHECK violations as OperationalError (3819).
_CHECK_VIOLATION = (IntegrityError, OperationalError)


@pytest.fixture
def coral_engine_bridge_engine(coral_scratch_engine: Engine) -> Engine:
    """A scratch database on the active lane with the Coral chain at coral_0003."""
    migrate_coral(coral_scratch_engine, "upgrade", _ENGINE_BRIDGE)
    return coral_scratch_engine


def _visit(
    visit_id: str, *, status: int, token: str | None, **changes: object
) -> dict[str, object]:
    return {
        "workspace_id": _WORKSPACE,
        "run_id": _RUN,
        "id": visit_id,
        "activation_id": "a" * 32,
        "node_id": "approve",
        "scope_key": "approve||:0",
        "visit_no": 1,
        "owner_user_id": "alice@example.com",
        "token": token,
        "elicitation_id": None,
        "elicitation_session_id": None,
        "status": status,
        "prompt_ref": None,
        "answer_label": None,
        "answered_by": None,
        "note": None,
        "opened_at": 1_700_000_000,
        "reminded_at": None,
        "resolved_at": None,
        **changes,
    }


def _alert(alert_id: str, **changes: object) -> dict[str, object]:
    return {
        "workspace_id": _WORKSPACE,
        "id": alert_id,
        "run_id": _RUN,
        "owner_user_id": "alice@example.com",
        "account_generation": None,
        "kind": int(AlertKind.GATE),
        "priority": int(AlertPriority.NORMAL),
        "subject_id": "s" * 32,
        "status": int(AlertStatus.OPEN),
        "payload": '{"title": "Approval needed"}',
        "created_at": 1_700_000_000,
        "acked_at": None,
        "acked_by": None,
        "resolved_at": None,
        **changes,
    }


def _populate(engine: Engine) -> None:
    """Gate visits a coral_0003 deployment holds: one per status, and a 64-character token."""
    insert_run(engine, _RUN, status=int(RunStatus.RUNNING), pause_reason=None)
    for status in GateVisitStatus:
        visit = _visit(
            f"visit-{int(status)}", status=int(status), token=f"approve||:0:{int(status)}"
        )
        insert_row(engine, _VISITS, visit)
    answered = _visit(
        "visit-answered",
        status=int(GateVisitStatus.RESOLVED),
        # 64 characters in 128 UTF-8 bytes: the downgrade limit counts characters.
        token="é" * 64,
        elicitation_id="coral_gate_" + "e" * 32,
        elicitation_session_id="anchor-session",
        answer_label="approve",
        answered_by="alice@example.com",
        note="Looks good.",
        reminded_at=1_700_000_100,
        resolved_at=1_700_000_200,
    )
    insert_row(engine, _VISITS, answered)


def _stored(engine: Engine) -> dict[str, list[tuple[object, ...]]]:
    """Every column of the populated gate visits, and the run they belong to."""
    with engine.connect() as conn:
        return {
            "visits": [tuple(row) for row in conn.execute(sa.select(_VISITS).order_by("id"))],
            "runs": [tuple(row) for row in conn.execute(sa.select(_RUNS.c.id, _RUNS.c.status))],
        }


def _token_column(schema: dict[str, dict[str, object]]) -> object:
    columns = schema["coral_gate_visits"]["columns"]
    assert isinstance(columns, dict)
    return columns["token"]


def _assert_matches_models(engine: Engine) -> None:
    """The lane's alert and gate tables have the models' columns, keys, indexes and checks."""
    inspector = sa.inspect(engine)
    for table in (_ALERTS, _VISITS):
        columns = {
            column["name"]: column["nullable"] for column in inspector.get_columns(table.name)
        }
        assert columns == {column.name: column.nullable for column in table.columns}, table.name
        primary_key = inspector.get_pk_constraint(table.name)["constrained_columns"]
        assert primary_key == [column.name for column in table.primary_key.columns], table.name
        indexes = {
            index["name"]: index["column_names"] for index in inspector.get_indexes(table.name)
        }
        for index in table.indexes:
            assert indexes.get(index.name) == [column.name for column in index.columns], index.name
        try:
            checks = {check["name"] for check in inspector.get_check_constraints(table.name)}
        except NotImplementedError:
            continue
        expected = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        }
        assert expected <= checks, table.name


def test_upgrade_keeps_gate_visits_and_stores_alerts_and_full_tokens(
    coral_engine_bridge_engine: Engine,
) -> None:
    engine = coral_engine_bridge_engine
    _populate(engine)
    stored = _stored(engine)

    # The token column changes on a table committed before the upgrade, as in a deployment.
    migrate_coral(engine, "upgrade", _ALERTS_AND_GATES)

    assert coral_revision(engine) == _ALERTS_AND_GATES
    assert _stored(engine) == stored
    _assert_matches_models(engine)
    valid = [
        *(_alert(f"kind-{int(kind)}", kind=int(kind)) for kind in AlertKind),
        *(
            _alert(f"priority-{int(priority)}", priority=int(priority))
            for priority in AlertPriority
        ),
        *(_alert(f"status-{int(status)}", status=int(status)) for status in AlertStatus),
    ]
    for alert in valid:
        insert_row(engine, _ALERTS, alert)
    unknown_codes = [
        _alert("unknown-kind", kind=len(AlertKind) + 1),
        _alert("unknown-priority", priority=len(AlertPriority) + 1),
        _alert("unknown-status", status=len(AlertStatus) + 1),
    ]
    for alert in unknown_codes:
        with pytest.raises(_CHECK_VIOLATION):
            insert_row(engine, _ALERTS, alert)

    insert_row(engine, _VISITS, _visit("visit-long", status=_OPEN, token=_LONG_TOKEN))
    with engine.connect() as conn:
        token = conn.execute(
            sa.select(_VISITS.c.token).where(_VISITS.c.id == "visit-long")
        ).scalar_one()
        # Tokens compare case-sensitively on every lane, MySQL included.
        other_case = conn.execute(
            sa.select(_VISITS.c.id).where(_VISITS.c.token == _LONG_TOKEN.lower())
        ).all()
    assert token == _LONG_TOKEN
    assert other_case == []
    # The widened column stays NOT NULL, and its table keeps the status check.
    with pytest.raises(_CHECK_VIOLATION):
        insert_row(engine, _VISITS, _visit("visit-null", status=_OPEN, token=None))
    with pytest.raises(_CHECK_VIOLATION):
        insert_row(
            engine, _VISITS, _visit("visit-bad", status=len(GateVisitStatus) + 1, token="t")
        )


def test_alerts_are_keyed_by_workspace_and_id(coral_scratch_engine: Engine) -> None:
    engine = coral_scratch_engine
    migrate_coral(engine, "upgrade", _ALERTS_AND_GATES)
    insert_row(engine, _ALERTS, _alert("a" * 32))

    with pytest.raises(IntegrityError):
        insert_row(engine, _ALERTS, _alert("a" * 32, kind=int(AlertKind.PAUSE)))

    # The same derived id in another workspace is that workspace's alert.
    insert_row(engine, _ALERTS, _alert("a" * 32, workspace_id=2))
    # Each pause of a run raises a new alert on the run's one pause subject.
    insert_row(engine, _ALERTS, _alert("b" * 32, kind=int(AlertKind.PAUSE)))
    insert_row(engine, _ALERTS, _alert("c" * 32, kind=int(AlertKind.PAUSE)))
    insert_row(engine, _ALERTS, _alert("d" * 32, run_id="o" * 32))
    with engine.connect() as conn:
        stored = conn.execute(sa.select(sa.func.count()).select_from(_ALERTS)).scalar_one()
    assert stored == 5


def test_downgrade_refuses_alerts_and_long_tokens_then_restores_coral_0003(
    coral_engine_bridge_engine: Engine,
) -> None:
    engine = coral_engine_bridge_engine
    _populate(engine)
    schema = reflected_schema(engine)
    stored = _stored(engine)
    migrate_coral(engine, "upgrade", _ALERTS_AND_GATES)
    upgraded = reflected_schema(engine)

    blockers = [
        (_ALERTS, _alert("a" * 32), "alerts"),
        (
            _VISITS,
            _visit("visit-long", status=_OPEN, token="t" * 65),
            "gate tokens longer than 64 characters",
        ),
    ]
    for table, values, found in blockers:
        insert_row(engine, table, values)
        with pytest.raises(RuntimeError, match=rf"before downgrading \(found {found}\)"):
            migrate_coral(engine, "downgrade", _ENGINE_BRIDGE)
        # Refused before any change, so no lane is left half downgraded.
        assert coral_revision(engine) == _ALERTS_AND_GATES
        assert reflected_schema(engine) == upgraded
        key = sa.and_(*(column == values[column.name] for column in table.primary_key.columns))
        with engine.begin() as conn:
            conn.execute(table.delete().where(key))

    # The populated 64-character token still fits the narrowed column.
    migrate_coral(engine, "downgrade", _ENGINE_BRIDGE)

    assert coral_revision(engine) == _ENGINE_BRIDGE
    restored = reflected_schema(engine)
    if is_cockroachdb(engine.dialect.name):
        # CockroachDB keeps the wide token column (see the migration); the rest is restored.
        assert _token_column(restored) == _token_column(upgraded)
        restored_columns = restored["coral_gate_visits"]["columns"]
        assert isinstance(restored_columns, dict)
        restored_columns["token"] = _token_column(schema)
    assert restored == schema
    assert _stored(engine) == stored

    # The downgraded database upgrades again to the same schema with its rows kept.
    migrate_coral(engine, "upgrade", _ALERTS_AND_GATES)
    assert coral_revision(engine) == _ALERTS_AND_GATES
    assert reflected_schema(engine) == upgraded
    assert _stored(engine) == stored


def _token_ddl(url: str) -> list[str]:
    """The upgrade's statements that touch the token column, rendered offline for ``url``."""
    config = _build_coral_alembic_config(url)
    config.output_buffer = StringIO()
    command.upgrade(config, f"{_ENGINE_BRIDGE}:{_ALERTS_AND_GATES}", sql=True)
    return [line for line in config.output_buffer.getvalue().splitlines() if "token" in line]


def test_token_widening_keeps_not_null_and_binary_collation() -> None:
    # MySQL's MODIFY restates the whole column, so it must repeat NOT NULL and the collation.
    assert _token_ddl("mysql://") == [
        "ALTER TABLE coral_gate_visits MODIFY token "
        "VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL;"
    ]
    # Postgres and CockroachDB change only the type, which leaves NOT NULL in place.
    assert _token_ddl("postgresql://") == [
        "ALTER TABLE coral_gate_visits ALTER COLUMN token TYPE VARCHAR(512);"
    ]


def test_alerts_downgrade_requires_a_live_connection() -> None:
    config = _build_coral_alembic_config("postgresql://")
    config.output_buffer = StringIO()

    with pytest.raises(RuntimeError, match="requires a live connection"):
        command.downgrade(config, f"{_ALERTS_AND_GATES}:{_ENGINE_BRIDGE}", sql=True)
    assert "ALTER TABLE" not in config.output_buffer.getvalue()
    assert "DROP" not in config.output_buffer.getvalue()
