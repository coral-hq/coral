"""coral_0003 on every DB lane: upgrading populated databases, refusing downgrade."""

from __future__ import annotations

import hashlib
from io import StringIO

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from coral.db import (
    AgentSlotRow,
    RunLogRow,
    RunRow,
    RunSpecRow,
    SessionBindingRow,
    ToolReplyRow,
    WorkflowVersionRow,
    WorkRow,
)
from coral.db.enum_codecs import (
    ActorKind,
    LogKind,
    RunAuthMode,
    RunExecutionTarget,
    RunPauseReason,
    RunStatus,
    RunTriggerKind,
    SessionBindingProgress,
    SessionBindingRole,
    SlotRole,
    SlotStatus,
    WorkflowVersionOrigin,
    WorkflowVersionStatus,
    WorkKind,
    WorkStatus,
)
from coral.db.migrate import _build_coral_alembic_config
from tests.db.coral._migration_support import (
    coral_revision,
    insert_row,
    migrate_coral,
    reflected_schema,
    run_values,
)

_CORE = "coral_0001_core"
_SESSION_FACADE = "coral_0002_session_facade"
_ENGINE_BRIDGE = "coral_0003_engine_bridge"
_WORKSPACE = 1
_RUN = "r" * 32
_OTHER_RUN = "o" * 32
_STEP_SLOT = "implement||:0"
_PAUSED = int(RunStatus.PAUSED)
_RUNS = RunRow.__table__
_SPECS = RunSpecRow.__table__
_SLOTS = AgentSlotRow.__table__
_LOG = RunLogRow.__table__
_VERSIONS = WorkflowVersionRow.__table__
_BINDINGS = SessionBindingRow.__table__
_WORK = WorkRow.__table__
_REPLIES = ToolReplyRow.__table__
# MySQL reports CHECK violations as OperationalError (3819).
_CHECK_VIOLATION = (IntegrityError, OperationalError)
_REFUSED = "Cancel and delete engine runs before downgrading"


@pytest.fixture
def coral_session_facade_engine(coral_scratch_engine: Engine) -> Engine:
    """A scratch database on the active lane with the Coral chain at coral_0002."""
    migrate_coral(coral_scratch_engine, "upgrade", _SESSION_FACADE)
    return coral_scratch_engine


def _spec(run_id: str, **changes: object) -> dict[str, object]:
    return {
        "workspace_id": _WORKSPACE,
        "run_id": run_id,
        "request_preview": "build the feature",
        "trigger_kind": int(RunTriggerKind.MANUAL),
        "execution_target": int(RunExecutionTarget.CONNECTED_HOST),
        "auth_mode": int(RunAuthMode.SUBSCRIPTION),
        "max_activations": 100,
        "refresh_threshold_bp": 8000,
        "rejected_call_limit": 3,
        "created_at": 0,
        **changes,
    }


def _slot(slot_id: str, status: int) -> dict[str, object]:
    return {
        "workspace_id": _WORKSPACE,
        "run_id": _RUN,
        "id": slot_id,
        "activation_id": "a" * 32,
        "node_id": "implement",
        "scope_key": _STEP_SLOT,
        "roster_index": 0,
        "role": int(SlotRole.STEP_AGENT),
        "session_generation": 1,
        "status": status,
        "created_at": 0,
        "updated_at": 0,
    }


def _log(seq: int, kind: int) -> dict[str, object]:
    return {
        "workspace_id": _WORKSPACE,
        "run_id": _RUN,
        "seq": seq,
        "run_version": 1,
        "log_version": 1,
        "kind": kind,
        "actor_kind": int(ActorKind.ENGINE),
        "body": "{}",
        "created_at_us": 0,
    }


def _version(version_id: str, **changes: object) -> dict[str, object]:
    return {
        "workspace_id": _WORKSPACE,
        "id": version_id,
        "workflow_id": "w" * 32,
        "content_hash": b"\x01" * 32,
        "yaml_ref": "blob/workflow.yaml",
        "yaml_bytes": 9,
        "compiled_ref": "blob/compiled.json",
        "compiler_version": 1,
        "origin": int(WorkflowVersionOrigin.SAVED),
        "validation_state": int(WorkflowVersionStatus.VALID),
        "created_at": 0,
        **changes,
    }


def _binding(
    session_id: str,
    run_id: str,
    *,
    slot_id: str | None,
    generation: int = 1,
    workspace_id: int = _WORKSPACE,
) -> dict[str, object]:
    step = slot_id is not None
    return {
        "workspace_id": workspace_id,
        "session_id": session_id,
        "run_id": run_id,
        "role": int(SessionBindingRole.STEP if step else SessionBindingRole.ANCHOR),
        "slot_id": slot_id,
        "slot_role": int(SlotRole.STEP_AGENT) if step else None,
        # Each binding has its own effect, so only the slot index can refuse it.
        "effect_cksum": hashlib.sha256(session_id.encode()).digest(),
        "session_generation": generation,
        "progress": int(SessionBindingProgress.RESERVED),
        "created_at": 0,
        "updated_at": 0,
    }


def _work(work_id: str) -> dict[str, object]:
    return {
        "workspace_id": _WORKSPACE,
        "id": work_id,
        "run_id": _RUN,
        "kind": int(WorkKind.EFFECT),
        "status": int(WorkStatus.PENDING),
        "payload": '{"effect_type": "send_input"}',
        "available_at": 0,
        "idempotency_cksum": hashlib.sha256(work_id.encode()).digest(),
        "created_at_us": 0,
    }


def _reply(cksum: bytes) -> dict[str, object]:
    return {
        "workspace_id": _WORKSPACE,
        "run_id": _RUN,
        "cksum": cksum,
        "reply": '{"accepted": true}',
        "run_version": 2,
        "created_at_us": 0,
    }


def _populate(engine: Engine, revision: str = _SESSION_FACADE) -> None:
    """Rows a deployment at ``revision`` can hold, with every code its checks allow."""
    # coral_0002 added the drift pause reason and the session bindings.
    session_facade = revision == _SESSION_FACADE
    last_reason = RunPauseReason.DRIFT if session_facade else RunPauseReason.ENGINE_UPGRADE
    for reason in range(1, int(last_reason) + 1):
        insert_row(
            engine, _RUNS, run_values(f"paused-{reason}", status=_PAUSED, pause_reason=reason)
        )
    insert_row(engine, _RUNS, run_values(_RUN, status=int(RunStatus.RUNNING), pause_reason=None))
    insert_row(engine, _SPECS, _spec(_RUN))
    for status in range(1, int(SlotStatus.CLOSED) + 1):
        insert_row(engine, _SLOTS, _slot(f"slot-{status}", status))
    # Each kind at its own sequence number, leaving the engine kind's number free.
    for kind in range(1, int(LogKind.COMMAND_REJECTED) + 1):
        insert_row(engine, _LOG, _log(kind, kind))
    insert_row(engine, _VERSIONS, _version("v" * 32))
    insert_row(engine, _WORK, _work("k" * 32))
    if session_facade:
        insert_row(engine, _BINDINGS, _binding("anchor-run", _RUN, slot_id=None))
        insert_row(engine, _BINDINGS, _binding("anchor-other-run", _OTHER_RUN, slot_id=None))
        insert_row(engine, _BINDINGS, _binding("step", _RUN, slot_id=_STEP_SLOT))


def _stored(engine: Engine, *, bindings: bool = True) -> dict[str, list[tuple[object, ...]]]:
    """The populated rows, read through columns that exist before and after coral_0003."""
    selects: dict[str, sa.Select[tuple[object, ...]]] = {
        "runs": sa.select(_RUNS.c.id, _RUNS.c.status, _RUNS.c.pause_reason),
        "specs": sa.select(_SPECS.c.run_id, _SPECS.c.request_preview),
        "slots": sa.select(_SLOTS.c.id, _SLOTS.c.status),
        "log": sa.select(_LOG.c.seq, _LOG.c.kind, _LOG.c.body),
        "versions": sa.select(_VERSIONS.c.id, _VERSIONS.c.yaml_ref, _VERSIONS.c.compiled_ref),
        "work": sa.select(_WORK.c.id, _WORK.c.status, _WORK.c.payload),
    }
    if bindings:
        selects["bindings"] = sa.select(
            _BINDINGS.c.session_id, _BINDINGS.c.slot_id, _BINDINGS.c.session_generation
        )
    with engine.connect() as conn:
        return {
            name: sorted(tuple(row) for row in conn.execute(select))
            for name, select in selects.items()
        }


def _new_codes() -> list[tuple[sa.Table, dict[str, object]]]:
    return [
        (_RUNS, run_values("auth", status=_PAUSED, pause_reason=int(RunPauseReason.AUTH))),
        (_SLOTS, _slot("e" * 32, int(SlotStatus.EVALUATING))),
        (_SLOTS, _slot("c" * 32, int(SlotStatus.CLOSING))),
        (_LOG, _log(int(LogKind.ENGINE), int(LogKind.ENGINE))),
    ]


def test_upgrade_keeps_rows_and_stores_engine_bridge_data(
    coral_session_facade_engine: Engine,
) -> None:
    engine = coral_session_facade_engine
    _populate(engine)
    stored = _stored(engine)
    for table, values in _new_codes():
        with pytest.raises(_CHECK_VIOLATION):
            insert_row(engine, table, values)

    # The checks are replaced on tables committed before the upgrade, as in a deployment.
    migrate_coral(engine, "upgrade", _ENGINE_BRIDGE)

    assert coral_revision(engine) == _ENGINE_BRIDGE
    assert _stored(engine) == stored
    for table, values in _new_codes():
        insert_row(engine, table, values)
    unknown_codes = [
        (_RUNS, run_values("unknown", status=_PAUSED, pause_reason=int(RunPauseReason.AUTH) + 1)),
        (_SLOTS, _slot("u" * 32, int(SlotStatus.CLOSING) + 1)),
        (_LOG, _log(int(LogKind.ENGINE) + 1, int(LogKind.ENGINE) + 1)),
    ]
    for table, values in unknown_codes:
        with pytest.raises(_CHECK_VIOLATION):
            insert_row(engine, table, values)
    # A version stores each artifact by blob ref or inline, never neither.
    for missing in (
        {"yaml_ref": None},
        {"compiled_ref": None},
        {"yaml_ref": None, "compiled_ref": None, "compiled_json": "{}"},
    ):
        with pytest.raises(_CHECK_VIOLATION):
            insert_row(engine, _VERSIONS, _version("x" * 32, **missing))

    # A pinned graph inline, a frozen engine config, a hold start and a tool reply.
    pinned = _version(
        "p" * 32,
        yaml_ref=None,
        compiled_ref=None,
        yaml_text="nodes: []",
        compiled_json='{"nodes": []}',
    )
    insert_row(engine, _VERSIONS, pinned)
    insert_row(engine, _SPECS, _spec(_OTHER_RUN, engine_config='{"max_activations": 100}'))
    with engine.begin() as conn:
        conn.execute(_WORK.update().values(held_since=1_700_000_000))
    insert_row(engine, _REPLIES, _reply(b"\x07" * 32))
    with pytest.raises(IntegrityError):
        insert_row(engine, _REPLIES, {**_reply(b"\x07" * 32), "reply": "{}"})
    # The same call checksum in another run is that run's own reply.
    insert_row(engine, _REPLIES, {**_reply(b"\x07" * 32), "run_id": _OTHER_RUN})
    with engine.connect() as conn:
        version = conn.execute(
            sa.select(
                _VERSIONS.c.yaml_ref,
                _VERSIONS.c.compiled_ref,
                _VERSIONS.c.yaml_text,
                _VERSIONS.c.compiled_json,
            ).where(_VERSIONS.c.id == "p" * 32)
        ).one()
        configs = dict(conn.execute(sa.select(_SPECS.c.run_id, _SPECS.c.engine_config)).all())
        held_since = conn.execute(sa.select(_WORK.c.held_since)).scalar_one()
        replies = conn.execute(
            sa.select(_REPLIES.c.run_id, _REPLIES.c.reply, _REPLIES.c.run_version).order_by(
                _REPLIES.c.run_id
            )
        ).all()
    assert tuple(version) == (None, None, "nodes: []", '{"nodes": []}')
    assert configs == {_RUN: None, _OTHER_RUN: '{"max_activations": 100}'}
    assert held_since == 1_700_000_000
    assert [tuple(reply) for reply in replies] == [
        (_OTHER_RUN, '{"accepted": true}', 2),
        (_RUN, '{"accepted": true}', 2),
    ]


def test_upgrade_from_coral_0001_to_head_and_back_keeps_rows(
    coral_scratch_engine: Engine,
) -> None:
    engine = coral_scratch_engine
    migrate_coral(engine, "upgrade", _CORE)
    _populate(engine, _CORE)
    stored = _stored(engine, bindings=False)

    # coral_0002 adds the pause-reason check that coral_0003 replaces, in one run.
    migrate_coral(engine, "upgrade", _ENGINE_BRIDGE)

    assert coral_revision(engine) == _ENGINE_BRIDGE
    assert _stored(engine, bindings=False) == stored
    for table, values in _new_codes():
        insert_row(engine, table, values)
        key = sa.and_(*(column == values[column.name] for column in table.primary_key.columns))
        with engine.begin() as conn:
            conn.execute(table.delete().where(key))

    # The downgrade adds back the check that coral_0002's downgrade then drops.
    migrate_coral(engine, "downgrade", _CORE)

    assert coral_revision(engine) == _CORE
    assert _stored(engine, bindings=False) == stored


def test_upgrade_refuses_two_step_sessions_for_one_slot_before_any_change(
    coral_session_facade_engine: Engine,
) -> None:
    engine = coral_session_facade_engine
    _populate(engine)
    insert_row(engine, _BINDINGS, _binding("second-step", _RUN, slot_id=_STEP_SLOT))
    schema = reflected_schema(engine)
    stored = _stored(engine)

    with pytest.raises(RuntimeError, match=f"Runs {_RUN} bind two step sessions to one slot"):
        migrate_coral(engine, "upgrade", _ENGINE_BRIDGE)

    # Nothing changed, so removing the extra binding lets the same upgrade run.
    assert coral_revision(engine) == _SESSION_FACADE
    assert reflected_schema(engine) == schema
    assert _stored(engine) == stored
    with engine.begin() as conn:
        conn.execute(_BINDINGS.delete().where(_BINDINGS.c.session_id == "second-step"))
    migrate_coral(engine, "upgrade", _ENGINE_BRIDGE)
    assert coral_revision(engine) == _ENGINE_BRIDGE


def test_one_step_binding_per_run_slot_and_generation(coral_scratch_engine: Engine) -> None:
    engine = coral_scratch_engine
    migrate_coral(engine, "upgrade", _ENGINE_BRIDGE)
    insert_row(engine, _BINDINGS, _binding("step", _RUN, slot_id=_STEP_SLOT))

    with pytest.raises(IntegrityError):
        insert_row(engine, _BINDINGS, _binding("second-step", _RUN, slot_id=_STEP_SLOT))

    # Another generation, run or workspace is another binding.
    insert_row(
        engine, _BINDINGS, _binding("next-generation", _RUN, slot_id=_STEP_SLOT, generation=2)
    )
    insert_row(engine, _BINDINGS, _binding("other-run", _OTHER_RUN, slot_id=_STEP_SLOT))
    insert_row(engine, _BINDINGS, _binding("step", _RUN, slot_id=_STEP_SLOT, workspace_id=2))
    # Anchors have no slot, and the index never compares slotless rows.
    insert_row(engine, _BINDINGS, _binding("anchor-run", _RUN, slot_id=None))
    insert_row(engine, _BINDINGS, _binding("anchor-other-run", _OTHER_RUN, slot_id=None))
    insert_row(engine, _BINDINGS, _binding("second-anchor-run", _RUN, slot_id=None))
    with engine.connect() as conn:
        stored = conn.execute(sa.select(sa.func.count()).select_from(_BINDINGS)).scalar_one()
    assert stored == 7


def test_downgrade_refuses_engine_bridge_data_then_restores_coral_0002(
    coral_session_facade_engine: Engine,
) -> None:
    engine = coral_session_facade_engine
    _populate(engine)
    schema = reflected_schema(engine)
    stored = _stored(engine)
    migrate_coral(engine, "upgrade", _ENGINE_BRIDGE)
    upgraded = reflected_schema(engine)

    engine_bridge_rows = [
        *_new_codes(),
        (_VERSIONS, _version("y" * 32, yaml_ref=None, yaml_text="nodes: []")),
        (_VERSIONS, _version("j" * 32, compiled_ref=None, compiled_json="{}")),
        (_SPECS, _spec(_OTHER_RUN, engine_config="{}")),
    ]
    for table, values in engine_bridge_rows:
        insert_row(engine, table, values)
        with pytest.raises(RuntimeError, match=_REFUSED):
            migrate_coral(engine, "downgrade", _SESSION_FACADE)
        assert coral_revision(engine) == _ENGINE_BRIDGE
        key = sa.and_(*(column == values[column.name] for column in table.primary_key.columns))
        with engine.begin() as conn:
            conn.execute(table.delete().where(key))

    # Replies and hold starts belong to the dropped schema only, so they never block.
    insert_row(engine, _REPLIES, _reply(b"\x07" * 32))
    with engine.begin() as conn:
        conn.execute(_WORK.update().values(held_since=1_700_000_000))
    migrate_coral(engine, "downgrade", _SESSION_FACADE)

    assert coral_revision(engine) == _SESSION_FACADE
    assert reflected_schema(engine) == schema
    assert _stored(engine) == stored
    for table, values in _new_codes():
        with pytest.raises(_CHECK_VIOLATION):
            insert_row(engine, table, values)

    # The downgraded database upgrades again to the same schema with its rows kept.
    migrate_coral(engine, "upgrade", _ENGINE_BRIDGE)
    assert coral_revision(engine) == _ENGINE_BRIDGE
    assert reflected_schema(engine) == upgraded
    assert _stored(engine) == stored
    for table, values in _new_codes():
        insert_row(engine, table, values)


def test_engine_bridge_downgrade_requires_a_live_connection() -> None:
    config = _build_coral_alembic_config("postgresql://")
    config.output_buffer = StringIO()

    with pytest.raises(RuntimeError, match="requires a live connection"):
        command.downgrade(config, f"{_ENGINE_BRIDGE}:{_SESSION_FACADE}", sql=True)
    assert "ALTER TABLE" not in config.output_buffer.getvalue()
    assert "DROP" not in config.output_buffer.getvalue()
