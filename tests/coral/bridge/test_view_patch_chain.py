"""Stored view patches replayed from a snapshot reproduce the engine's projection exactly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue

from coral.bridge.config import epoch_us
from coral.db.enum_codecs import LogKind, RunPauseReason, RunStatus
from coral.engine import empty_state
from coral.engine.projection import RunView, project
from coral.engine.types import HandoffEvaluated, PauseRun
from coral.recovery.pause import pause_run_once
from coral.runview.patch import apply_view_patch, stored_view_patch
from coral.stores.protocols import RunLogEntry
from tests.coral.bridge._gates import CHANGE_TOKEN, GATED, IMPLEMENT_AGAIN, answer, hand_off
from tests.coral.bridge._world import WORKSPACE, World, start


@dataclass(frozen=True)
class Head:
    """What a stream's snapshot holds after one commit: the head seq and the projected view."""

    version: int
    seq: int
    view: dict[str, JsonValue]


def _rows(world: World, run_id: str) -> list[RunLogEntry]:
    rows: list[RunLogEntry] = []
    while page := world.runs.read_log(
        run_id, workspace_id=WORKSPACE, after_seq=rows[-1].seq if rows else 0, limit=10
    ):
        rows.extend(page)
    return rows


def _run_through_a_gate_a_refusal_pauses_and_a_cancel(world: World) -> tuple[str, list[Head]]:
    """Start, a step, a rejected gate, a refusal with a user pause, a resume, the step again,
    a pause on the row alone and a cancel, capturing the loaded projection after each commit."""
    heads: list[Head] = []

    def capture(run_id: str, version: int) -> None:
        snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
        assert snapshot.version == version
        heads.append(
            Head(
                version=version,
                seq=snapshot.store.run.next_log_seq - 1,
                view=project(snapshot.state).model_dump(mode="json"),
            )
        )

    world.runs.register_post_commit(capture)
    run_id = start(world, GATED).id
    hand_off(world, run_id)
    assert answer(world, run_id, CHANGE_TOKEN, "reject").outcome == "accepted"
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (
            HandoffEvaluated(slot_id="no-such-slot", outcome="accepted"),
            PauseRun(reason="user", detail="user"),
        ),
        actor="alice",
    )
    world.bridge.resume_run(workspace_id=WORKSPACE, run_id=run_id, actor="alice")
    hand_off(world, run_id, IMPLEMENT_AGAIN)
    pause_run_once(
        world.runs,
        workspace_id=WORKSPACE,
        run_id=run_id,
        reason=RunPauseReason.DRIFT,
        body={"kind": "pause_run", "reason": "drift", "detail": "drift"},
        checksum_parts=("chain-test-drift", run_id),
        now_us=epoch_us(world.clock.now),
    )
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run_id, actor="alice")
    return run_id, heads


def test_stored_patches_rebuild_the_view_from_the_empty_view_and_from_every_head(
    tmp_path: Path,
) -> None:
    world = World.fake(tmp_path)
    run_id, heads = _run_through_a_gate_a_refusal_pauses_and_a_cancel(world)
    run = world.run(run_id)
    rows = _rows(world, run_id)
    final = project(world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state)

    # Every commit was captured, every seq is stored, and the run has every kind of row.
    assert [head.version for head in heads] == list(range(heads[0].version, run.version + 1))
    assert [row.seq for row in rows] == list(range(1, run.next_log_seq))
    assert (run.status, final.status) == (int(RunStatus.CANCELLED), "cancelled")
    assert any(row.audit_only and row.view_patch is None for row in rows)
    assert any(row.kind == int(LogKind.PAUSED) and row.view_patch is None for row in rows)
    assert any(row.view_patch is not None for row in rows)
    assert project(empty_state()) == RunView()

    empty = Head(version=0, seq=0, view=RunView().model_dump(mode="json"))
    for origin in (empty, *heads):
        view = origin.view
        for row in rows:
            if row.seq <= origin.seq:
                continue
            view = apply_view_patch(view, stored_view_patch(row.view_patch))
            for later in heads:
                if later.seq == row.seq:
                    assert view == later.view, (origin.seq, later.version)
        assert view == final.model_dump(mode="json"), origin.seq
        assert RunView.model_validate(view) == final
