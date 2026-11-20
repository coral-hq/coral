"""The per-process prompt sweep: a tracked prompt stays only while it is a live visit's."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from coral.bridge.executors import BridgeThreads
from coral.db.enum_codecs import SessionBindingRole, SlotRole
from coral.gates.sweep import GatePromptSweeper
from coral.model.ids import anchor_session_id
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
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
    start,
)
from tests.coral.tools.fake_decision_port import step_binding
from tests.coral.workspace._executor_fakes import FakeBindings, RecordingScopeRunner


@dataclass
class Sweep:
    world: World
    bindings: FakeBindings
    gates: RecordingGatePublisher
    prompts: FakeGatePrompts
    scope: RecordingScopeRunner
    sweeper: GatePromptSweeper

    def open(self, yaml_text: str = GATE_ONLY, *, start_key: str = "start-1") -> tuple[str, str]:
        """A run at its gate with its anchor bound; its id and its anchor."""
        run = start(self.world, yaml_text, spec=run_spec(start_key=start_key), start_key=start_key)
        anchor = anchor_session_id(WORKSPACE, run.id)
        self.bindings.rows[(WORKSPACE, anchor)] = step_binding(
            None,
            session_id=anchor,
            run_id=run.id,
            workspace_id=WORKSPACE,
            role=SessionBindingRole.ANCHOR,
            slot_role=None,
        )
        return run.id, anchor

    def prompt_of(self, run_id: str, index: int = -1) -> str:
        elicitation_id = gate_rows(self.world, run_id)[index].elicitation_id
        assert elicitation_id is not None
        return elicitation_id


@pytest_asyncio.fixture
async def sweep(tmp_path: Path) -> AsyncIterator[Sweep]:
    world = World.fake(tmp_path, gate_ids=GateIds())
    threads = BridgeThreads(world.bridge)
    bindings, gates, scope = FakeBindings(), RecordingGatePublisher(), RecordingScopeRunner()
    prompts = FakeGatePrompts(gates)
    sweeper = GatePromptSweeper(
        threads=threads,
        run_store=world.runs,
        bindings=bindings,
        publisher=gates,
        prompts=prompts,
        scope_runner=scope,
        interval_s=0.01,
    )
    try:
        yield Sweep(world, bindings, gates, prompts, scope, sweeper)
    finally:
        threads.close()


def _no_engine_loads(sweep: Sweep, monkeypatch: pytest.MonkeyPatch) -> None:
    """From here on, loading any run's engine state fails the test."""

    def load(**_kwargs: object) -> None:
        raise AssertionError("the sweep loaded engine state")

    monkeypatch.setattr(sweep.world.bridge, "load", load)


async def test_a_prompt_answered_elsewhere_is_withdrawn_and_a_live_one_stays(
    sweep: Sweep, monkeypatch: pytest.MonkeyPatch
) -> None:
    answered_run, answered_anchor = sweep.open()
    live_run, live_anchor = sweep.open(start_key="start-2")
    answered = sweep.prompts.track(answered_anchor, sweep.prompt_of(answered_run))
    live = sweep.prompts.track(live_anchor, sweep.prompt_of(live_run))
    # Committed on another replica: no fan-out reached this process's prompt.
    assert answer(sweep.world, answered_run, APPROVE_TOKEN, "approve").outcome == "accepted"
    # WHY: the gate rows alone tell live from dead; the sweep loads no engine state.
    _no_engine_loads(sweep, monkeypatch)

    withdrawn = await sweep.sweeper.sweep_once()

    assert withdrawn == 1
    assert sweep.gates.calls == [
        ("withdraw", answered_anchor, answered.elicitation_id),
    ]
    assert sweep.prompts.prompts == [live]
    assert (live_anchor, live.elicitation_id) in sweep.gates.pending
    # Each withdraw ran in its prompt's workspace.
    assert [scope["workspace_id"] for scope in sweep.scope.entered] == [WORKSPACE, WORKSPACE]


async def test_a_prompt_no_longer_pending_is_untracked_without_a_withdraw(sweep: Sweep) -> None:
    run_id, anchor = sweep.open()
    prompt = sweep.prompts.track(anchor, sweep.prompt_of(run_id))
    # Resolved without an event the observer saw.
    del sweep.gates.pending[(anchor, prompt.elicitation_id)]

    assert await sweep.sweeper.sweep_once() == 0
    assert sweep.prompts.prompts == []
    assert sweep.gates.calls == []


async def test_prompts_off_a_runs_anchor_are_withdrawn(sweep: Sweep) -> None:
    run_id, anchor = sweep.open()
    real = sweep.prompt_of(run_id)
    step, unbound = "s" * 32, "u" * 32
    sweep.bindings.rows[(WORKSPACE, step)] = step_binding(
        "approve||:0",
        session_id=step,
        run_id=run_id,
        workspace_id=WORKSPACE,
        role=SessionBindingRole.STEP,
        slot_role=SlotRole.STEP_AGENT,
    )
    sweep.prompts.track(step, real)
    sweep.prompts.track(unbound, real)
    kept = sweep.prompts.track(anchor, real)

    assert await sweep.sweeper.sweep_once() == 2
    assert sweep.gates.calls == [("withdraw", step, real), ("withdraw", unbound, real)]
    assert sweep.prompts.prompts == [kept]


async def test_a_cancelled_runs_prompt_is_withdrawn_and_a_paused_runs_stays(
    sweep: Sweep, monkeypatch: pytest.MonkeyPatch
) -> None:
    # WHY: a paused run's gate is still live and answerable; a finished run's is not.
    cancelled_run, cancelled_anchor = sweep.open()
    paused_run, paused_anchor = sweep.open(start_key="start-2")
    cancelled = sweep.prompts.track(cancelled_anchor, sweep.prompt_of(cancelled_run))
    paused = sweep.prompts.track(paused_anchor, sweep.prompt_of(paused_run))
    sweep.world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=cancelled_run, actor="alice")
    sweep.world.bridge.pause_for_drift(
        workspace_id=WORKSPACE,
        run_id=paused_run,
        cause="session_archived",
        body={"kind": "pause_run", "reason": "drift", "cause": "session_archived"},
        checksum_parts=("coral-drift", paused_run, "session_archived", "s" * 32),
        now_us=0,
    )
    _no_engine_loads(sweep, monkeypatch)

    assert await sweep.sweeper.sweep_once() == 1
    assert sweep.gates.calls == [("withdraw", cancelled_anchor, cancelled.elicitation_id)]
    assert sweep.prompts.prompts == [paused]


async def test_a_run_whose_gate_rows_cannot_be_read_keeps_its_prompts(
    sweep: Sweep, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, anchor = sweep.open()
    prompt = sweep.prompts.track(anchor, sweep.prompt_of(run_id))

    def unreadable(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(sweep.world.runs, "list_open_gates", unreadable)

    assert await sweep.sweeper.sweep_once() == 0
    assert sweep.prompts.prompts == [prompt]
    assert sweep.gates.calls == []


async def test_the_tracked_prompts_are_listed_before_any_gate_rows_are_read(
    sweep: Sweep, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prompt published after the rows were read is never judged by that older read."""
    run = start(sweep.world, GATED)
    anchor = anchor_session_id(WORKSPACE, run.id)
    sweep.bindings.rows[(WORKSPACE, anchor)] = step_binding(
        None,
        session_id=anchor,
        run_id=run.id,
        workspace_id=WORKSPACE,
        role=SessionBindingRole.ANCHOR,
        slot_role=None,
    )
    stale = sweep.prompts.track(anchor, "coral_gate_" + "e" * 32)
    read = sweep.world.runs.list_open_gates
    opened: list[str] = []

    def read_then_open(*args: Any, **kwargs: Any) -> Any:
        rows = read(*args, **kwargs)
        if not opened:
            opened.append("")
            # The gate opens and its prompt is published just after this read.
            hand_off(sweep.world, run.id)
            opened[0] = sweep.prompts.track(anchor, sweep.prompt_of(run.id)).elicitation_id
        return rows

    monkeypatch.setattr(sweep.world.runs, "list_open_gates", read_then_open)

    assert await sweep.sweeper.sweep_once() == 1
    assert sweep.gates.calls == [("withdraw", anchor, stale.elicitation_id)]
    assert sweep.prompts.listed == 1
    # The next sweep sees the gate open and keeps its prompt.
    assert await sweep.sweeper.sweep_once() == 0
    assert [prompt.elicitation_id for prompt in sweep.prompts.prompts] == opened


async def test_a_failed_withdraw_is_logged_once_and_the_sweep_goes_on(
    sweep: Sweep, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    run_id, _anchor = sweep.open()
    first = sweep.prompts.track("u" * 32, sweep.prompt_of(run_id))
    second = sweep.prompts.track("v" * 32, sweep.prompt_of(run_id))
    withdraw = sweep.gates.withdraw

    async def failing(*, session_id: str, elicitation_id: str) -> bool:
        if session_id == first.session_id:
            raise RuntimeError("index unavailable")
        return await withdraw(session_id=session_id, elicitation_id=elicitation_id)

    monkeypatch.setattr(sweep.gates, "withdraw", failing)

    with caplog.at_level(logging.DEBUG, logger="coral.gates.sweep"):
        assert await sweep.sweeper.sweep_once() == 1
        assert await sweep.sweeper.sweep_once() == 0

    assert sweep.prompts.prompts == [first]
    assert (second.session_id, second.elicitation_id) not in sweep.gates.pending
    errors = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(errors) == 1 and "index unavailable" in errors[0].getMessage()


async def test_the_sweep_runs_while_prompts_are_tracked_until_it_is_stopped(
    sweep: Sweep,
) -> None:
    run_id, anchor = sweep.open()
    prompt = sweep.prompts.track(anchor, sweep.prompt_of(run_id))
    stop = asyncio.Event()
    task = asyncio.create_task(sweep.sweeper.run(stop))
    try:
        assert answer(sweep.world, run_id, APPROVE_TOKEN, "approve").outcome == "accepted"
        await poll_until_async(lambda: not sweep.prompts.prompts, timeout_s=budget(30))
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=budget(30))

    assert sweep.gates.calls == [("withdraw", anchor, prompt.elicitation_id)]
