"""Republish: every live visit's prompt is back on its anchor, as it was first shown, once."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from coral.bridge.executors import BridgeThreads
from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole
from coral.gates.republish import GateRepublisher
from coral.model.ids import anchor_session_id
from coral.reconcile import startup_recovery_sweep
from coral.stores.session_bindings import SessionBinding
from tests.coral.bridge._gates import (
    CHANGE_TOKEN,
    GATE_ONLY,
    GATED,
    GateIds,
    answer,
    gate_rows,
    hand_off,
)
from tests.coral.bridge._world import (
    WORKSPACE,
    FakeGatePrompts,
    RecordingGatePublisher,
    World,
    run_spec,
    serving,
    start,
)
from tests.coral.tools.fake_decision_port import step_binding
from tests.coral.workspace._executor_fakes import FakeBindings, RecordingScopeRunner


def _anchor(
    run_id: str, progress: SessionBindingProgress = SessionBindingProgress.INITIALIZED
) -> SessionBinding:
    return step_binding(
        None,
        session_id=anchor_session_id(WORKSPACE, run_id),
        run_id=run_id,
        workspace_id=WORKSPACE,
        role=SessionBindingRole.ANCHOR,
        slot_role=None,
        progress=progress,
    )


@dataclass
class Restart:
    """A new process: its own empty prompt index, the stores and bindings that survived."""

    world: World
    gates: RecordingGatePublisher
    bindings: FakeBindings
    republisher: GateRepublisher

    def bind(self, run_id: str, **progress: Any) -> None:
        self.bindings.rows[(WORKSPACE, anchor_session_id(WORKSPACE, run_id))] = _anchor(
            run_id, **progress
        )

    async def sweep(self) -> tuple[int, int, int]:
        report = await startup_recovery_sweep(
            self.world.runs,
            self.world.queue,
            scope_runner=RecordingScopeRunner(),
            gate_republisher=self.republisher,
        )
        return report.open_gates_scanned, report.open_gates_republished, report.errors


@pytest_asyncio.fixture
async def restart(tmp_path: Path) -> AsyncIterator[Restart]:
    world = World.fake(tmp_path, gate_ids=GateIds())
    threads = BridgeThreads(world.bridge)
    gates, bindings = RecordingGatePublisher(), FakeBindings()
    republisher = GateRepublisher(
        threads, gates, bindings=bindings, prompts=FakeGatePrompts(gates)
    )
    try:
        yield Restart(world, gates, bindings, republisher)
    finally:
        threads.close()


async def test_the_republish_shows_the_same_id_and_params_the_first_publish_showed(
    restart: Restart,
) -> None:
    world = restart.world
    run = start(world, GATE_ONLY)
    async with serving(world) as sessions:
        await sessions.drain()
    first = dict(sessions.gates.pending)
    restart.bind(run.id)

    # The process died: its prompts are gone; the startup sweep republishes from the rows.
    swept = await restart.sweep()

    assert restart.gates.pending == first
    assert list(first) == [
        (anchor_session_id(WORKSPACE, run.id), gate_rows(world, run.id)[0].elicitation_id)
    ]
    assert swept == (1, 1, 0)


async def test_each_runs_live_visits_are_republished_and_closed_ones_are_not(
    restart: Restart,
) -> None:
    world = restart.world
    live = start(world, GATE_ONLY, spec=run_spec(start_key="live"), start_key="live")
    answered = start(world, GATED, spec=run_spec(start_key="answered"), start_key="answered")
    hand_off(world, answered.id)
    restart.bind(live.id)
    restart.bind(answered.id)
    stale_row = gate_rows(world, answered.id)[0]
    assert answer(world, answered.id, CHANGE_TOKEN, "approve").outcome == "accepted"

    await restart.republisher(gate_rows(world, live.id))
    # A row the sweep listed as open, whose visit was answered since.
    await restart.republisher([stale_row])

    assert list(restart.gates.pending) == [
        (anchor_session_id(WORKSPACE, live.id), gate_rows(world, live.id)[0].elicitation_id)
    ]


async def test_a_prompt_still_shown_here_is_never_sent_again(restart: Restart) -> None:
    """The resync tick runs the same hook every minute; only lost prompts are republished."""
    world = restart.world
    run = start(world, GATE_ONLY)
    restart.bind(run.id)

    assert await restart.sweep() == (1, 1, 0)
    assert await restart.sweep() == (1, 1, 0)

    elicitation_id = gate_rows(world, run.id)[0].elicitation_id
    assert restart.gates.calls == [
        ("publish", anchor_session_id(WORKSPACE, run.id), elicitation_id)
    ]


async def test_a_failed_republish_is_repaired_by_the_next_sweep(
    restart: Restart, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = restart.world
    run = start(world, GATE_ONLY)
    restart.bind(run.id)
    publish = restart.gates.publish
    failures = [RuntimeError("index unavailable")]

    async def flaky(**kwargs: Any) -> None:
        if failures:
            raise failures.pop()
        await publish(**kwargs)

    monkeypatch.setattr(restart.gates, "publish", flaky)

    assert await restart.sweep() == (1, 0, 1)
    assert restart.gates.pending == {}
    assert await restart.sweep() == (1, 1, 0)
    assert list(restart.gates.pending) == [
        (anchor_session_id(WORKSPACE, run.id), gate_rows(world, run.id)[0].elicitation_id)
    ]


@pytest.mark.parametrize(
    "progress", [None, SessionBindingProgress.RESERVED, SessionBindingProgress.ROW_CREATED]
)
async def test_a_run_whose_anchor_is_not_created_is_left_to_its_publish_row(
    restart: Restart, progress: SessionBindingProgress | None
) -> None:
    """The prompt sweep withdraws prompts off a run's anchor; a republish must not fight it."""
    run = start(restart.world, GATE_ONLY)
    if progress is not None:
        restart.bind(run.id, progress=progress)

    await restart.republisher(gate_rows(restart.world, run.id))

    assert restart.gates.calls == []


async def test_a_batch_holds_one_runs_rows(restart: Restart) -> None:
    world = restart.world
    first = start(world, GATE_ONLY, spec=run_spec(start_key="a"), start_key="a")
    second = start(world, GATE_ONLY, spec=run_spec(start_key="b"), start_key="b")

    with pytest.raises(ValueError, match="one run"):
        await restart.republisher([*gate_rows(world, first.id), *gate_rows(world, second.id)])
    await restart.republisher([])
    assert restart.gates.calls == []
