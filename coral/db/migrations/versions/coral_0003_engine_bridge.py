"""Engine log rows, engine-bridge codes, pinned graphs, frozen configs, holds and tool replies.

Revision ID: coral_0003_engine_bridge
Revises: coral_0002_session_facade

Upgrade refuses, before any change, while two step sessions share a slot and generation.
Downgrade refuses while engine-run data exists; cancel and delete engine runs first.
Stop Coral servers before downgrading: the downgrade drops stored tool replies and hold starts.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import context, op

from coral.db.types import CAPPED_TEXT, CHECKSUM32

revision: str = "coral_0003_engine_bridge"
down_revision: str | None = "coral_0002_session_facade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUTH = 13
_EVALUATING = 10
_CLOSING = 11
_ENGINE = 22
_SLOT_GENERATION_INDEX = "uq_coral_session_bindings_slot_generation"
_VERSION_CONTENT_CHECK = "ck_coral_workflow_versions_content"
_VERSION_CONTENT_SQL = (
    "(yaml_ref IS NOT NULL OR yaml_text IS NOT NULL) "
    "AND (compiled_ref IS NOT NULL OR compiled_json IS NOT NULL)"
)
_REF = sa.String(512)
_LISTED_RUNS = 10


def _codes(last: int) -> str:
    return ", ".join(str(code) for code in range(1, last + 1))


class _WidenedCheck(NamedTuple):
    table: str
    old_name: str
    old_sql: str
    new_name: str
    new_sql: str


_WIDENED_CHECKS = (
    _WidenedCheck(
        "coral_runs",
        "ck_coral_runs_pause_reason_v2",
        f"pause_reason IS NULL OR pause_reason IN ({_codes(12)})",
        "ck_coral_runs_pause_reason_v3",
        f"pause_reason IS NULL OR pause_reason IN ({_codes(_AUTH)})",
    ),
    _WidenedCheck(
        "coral_agent_slots",
        "ck_coral_agent_slots_status",
        f"status IN ({_codes(9)})",
        "ck_coral_agent_slots_status_v2",
        f"status IN ({_codes(_CLOSING)})",
    ),
    _WidenedCheck(
        "coral_run_log",
        "ck_coral_run_log_kind",
        f"kind IN ({_codes(21)})",
        "ck_coral_run_log_kind_v2",
        f"kind IN ({_codes(_ENGINE)})",
    ),
)


def _replace_checks(*, widen: bool) -> None:
    for check in _WIDENED_CHECKS:
        drop = check.old_name if widen else check.new_name
        name, sql = (check.new_name, check.new_sql) if widen else (check.old_name, check.old_sql)
        with op.batch_alter_table(check.table) as batch_op:
            # A distinct name lets CockroachDB replace the check in one transaction.
            batch_op.drop_constraint(drop, type_="check")
            batch_op.create_check_constraint(name, sql)


def _runs_binding_one_slot_twice(bind: sa.Connection) -> list[str]:
    """Runs with two step bindings for one slot and generation, which the new index refuses."""
    bindings = sa.table(
        "coral_session_bindings",
        sa.column("workspace_id"),
        sa.column("run_id"),
        sa.column("slot_id"),
        sa.column("session_generation"),
    )
    shared = (
        sa.select(bindings.c.run_id)
        .where(bindings.c.slot_id.is_not(None))
        .group_by(
            bindings.c.workspace_id,
            bindings.c.run_id,
            bindings.c.slot_id,
            bindings.c.session_generation,
        )
        .having(sa.func.count() > 1)
    )
    return sorted({row.run_id for row in bind.execute(shared)})


def upgrade() -> None:
    # Checked before any DDL: MySQL commits each statement, so a late index failure would
    # leave this revision half applied.
    runs = [] if context.is_offline_mode() else _runs_binding_one_slot_twice(op.get_bind())
    if runs:
        more = f" and {len(runs) - _LISTED_RUNS} more" if len(runs) > _LISTED_RUNS else ""
        raise RuntimeError(
            f"Runs {', '.join(runs[:_LISTED_RUNS])}{more} bind two step sessions to one slot "
            "and generation; remove the extra session bindings before upgrading"
        )
    _replace_checks(widen=True)
    with op.batch_alter_table("coral_workflow_versions") as batch_op:
        batch_op.add_column(sa.Column("yaml_text", CAPPED_TEXT, nullable=True))
        batch_op.add_column(sa.Column("compiled_json", CAPPED_TEXT, nullable=True))
        batch_op.alter_column("yaml_ref", existing_type=_REF, nullable=True)
        batch_op.alter_column("compiled_ref", existing_type=_REF, nullable=True)
        # Each artifact is stored by blob ref or inline.
        batch_op.create_check_constraint(_VERSION_CONTENT_CHECK, _VERSION_CONTENT_SQL)
    with op.batch_alter_table("coral_run_specs") as batch_op:
        batch_op.add_column(sa.Column("engine_config", CAPPED_TEXT, nullable=True))
    with op.batch_alter_table("coral_work") as batch_op:
        batch_op.add_column(sa.Column("held_since", sa.BigInteger(), nullable=True))
    op.create_table(
        "coral_tool_replies",
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(32), nullable=False),
        sa.Column("cksum", CHECKSUM32, nullable=False),
        sa.Column("reply", CAPPED_TEXT, nullable=False),
        sa.Column("run_version", sa.BigInteger(), nullable=False),
        sa.Column("created_at_us", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "run_id",
            "cksum",
            name="pk_coral_tool_replies",
        ),
    )
    # NULL slot ids are distinct on every supported database, so anchors never collide.
    op.create_index(
        _SLOT_GENERATION_INDEX,
        "coral_session_bindings",
        ["workspace_id", "run_id", "slot_id", "session_generation"],
        unique=True,
    )


def _engine_run_data(bind: sa.Connection) -> list[str]:
    """Name each kind of stored data that only this revision's schema can hold."""
    runs = sa.table("coral_runs", sa.column("id"), sa.column("pause_reason"))
    slots = sa.table("coral_agent_slots", sa.column("id"), sa.column("status"))
    log = sa.table("coral_run_log", sa.column("seq"), sa.column("kind"))
    versions = sa.table(
        "coral_workflow_versions",
        sa.column("id"),
        sa.column("yaml_ref"),
        sa.column("compiled_ref"),
    )
    specs = sa.table("coral_run_specs", sa.column("run_id"), sa.column("engine_config"))
    probes = {
        "runs paused for auth": sa.select(runs.c.id).where(runs.c.pause_reason == _AUTH),
        "evaluating or closing slots": sa.select(slots.c.id).where(
            slots.c.status.in_((_EVALUATING, _CLOSING))
        ),
        "engine log rows": sa.select(log.c.seq).where(log.c.kind == _ENGINE),
        "workflow versions without blob refs": sa.select(versions.c.id).where(
            sa.or_(versions.c.yaml_ref.is_(None), versions.c.compiled_ref.is_(None))
        ),
        "run specs with an engine config": sa.select(specs.c.run_id).where(
            specs.c.engine_config.is_not(None)
        ),
    }
    return [name for name, probe in probes.items() if bind.execute(probe.limit(1)).first()]


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Downgrade requires a live connection to check for engine runs")
    found = _engine_run_data(op.get_bind())
    if found:
        raise RuntimeError(
            f"Cancel and delete engine runs before downgrading (found {', '.join(found)})"
        )

    # The checks can still fail on data, so restore them before dropping anything.
    _replace_checks(widen=False)
    op.drop_index(_SLOT_GENERATION_INDEX, table_name="coral_session_bindings")
    op.drop_table("coral_tool_replies")
    with op.batch_alter_table("coral_work") as batch_op:
        batch_op.drop_column("held_since")
    with op.batch_alter_table("coral_run_specs") as batch_op:
        batch_op.drop_column("engine_config")
    with op.batch_alter_table("coral_workflow_versions") as batch_op:
        batch_op.drop_constraint(_VERSION_CONTENT_CHECK, type_="check")
        batch_op.drop_column("compiled_json")
        batch_op.drop_column("yaml_text")
        batch_op.alter_column("yaml_ref", existing_type=_REF, nullable=False)
        batch_op.alter_column("compiled_ref", existing_type=_REF, nullable=False)
