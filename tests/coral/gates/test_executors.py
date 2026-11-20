"""Gate delivery executors: a live visit's prompt reaches the anchor; a closed one's leaves it."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from coral.bridge.executors import BridgeThreads
from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole, WorkStatus
from coral.gates.executors import gate_publish_executor, gate_withdraw_executor
from coral.gates.ids import GATE_PUBLISH, GATE_WITHDRAW
from coral.gates.prompt import gate_params
from coral.model.ids import anchor_session_id
from coral.queue.executors import (
    EffectCompleted,
    EffectFailed,
    EffectOutcome,
    StartupLeaseLost,
    get_registration,
)
from coral.stores.fakes import FakeRunStore
from coral.stores.session_bindings import SessionBinding
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
    CHANGE_TOKEN,
    CHANGE_TOKEN_AGAIN,
    GATE_ONLY,
    GATED,
    IMPLEMENT_AGAIN,
    GateIds,
    answer,
    effects,
    gate_rows,
    hand_off,
    payload,
    work_for,
)
from tests.coral.bridge._world import (
    WORKSPACE,
    RecordingGatePublisher,
    World,
    serving,
    start,
)
from tests.coral.tools.fake_decision_port import step_binding
from tests.coral.workspace._executor_fakes import (
    FakeBindings,
    RecordingScopeRunner,
    effect_context,
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path, gate_ids=GateIds())


def anchor_binding(
    run_id: str, progress: SessionBindingProgress = SessionBindingProgress.INITIALIZED
) -> SessionBinding:
    """The run's anchor binding, as the session facade writes it."""
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
class Delivery:
    """The two gate executors over a recording publisher, called as the drainer would."""

    world: World
    gates: RecordingGatePublisher
    bindings: FakeBindings
    scope: RecordingScopeRunner
    threads: BridgeThreads

    async def deliver(
        self,
        effect_type: str,
        run_id: str,
        token: str,
        *,
        kind: str | None = None,
        ensure_lease: Callable[[], Awaitable[bool]] | None = None,
        **overrides: Any,
    ) -> EffectOutcome:
        """
        Run the executor of ``effect_type`` on the newest row queued for the visit ``token``.

        :param kind: The engine effect whose row is used; by default the one
            ``effect_type`` delivers.
        """
        kind = kind or ("publish_gate" if effect_type == GATE_PUBLISH else "withdraw_gate")
        (effect, *_older) = reversed(
            [item for item in effects(self.world, run_id, kind) if item.subject == token]
        )
        row = work_for(self.world, run_id, effect.effect_key)
        assert row is not None
        executor = (
            gate_publish_executor(
                self.threads, self.gates, self.bindings, self.world.runs, self.scope
            )
            if effect_type == GATE_PUBLISH
            else gate_withdraw_executor(self.threads, self.gates, self.world.runs, self.scope)
        )
        context = effect_context(
            workspace_id=WORKSPACE,
            run_id=run_id,
            payload={**payload(row), **overrides},
            ensure_lease=ensure_lease,
        )
        return await executor(context)


@pytest_asyncio.fixture
async def delivery(world: World) -> AsyncIterator[Delivery]:
    threads = BridgeThreads(world.bridge)
    try:
        yield Delivery(
            world, RecordingGatePublisher(), FakeBindings(), RecordingScopeRunner(), threads
        )
    finally:
        threads.close()


def _expected_params(world: World, run_id: str, token: str) -> tuple[str, dict[str, Any]]:
    """The row's prompt id and the K14 params a publish of the visit ``token`` shows."""
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id)
    (visit,) = (item for item in snapshot.state.gates if item.token == token)
    (row,) = (item for item in snapshot.store.gate_visits if item.token == token)
    assert row.elicitation_id is not None
    return row.elicitation_id, gate_params(
        snapshot.graph, snapshot.state, snapshot.store.run, visit, row
    )


def _completed(outcome: EffectOutcome) -> dict[str, Any]:
    assert isinstance(outcome, EffectCompleted), outcome
    assert outcome.result is not None
    return outcome.result


async def test_a_live_visit_is_published_on_the_anchor_with_its_rows_id_and_params(
    world: World,
) -> None:
    run = start(world, GATE_ONLY)
    anchor = anchor_session_id(WORKSPACE, run.id)
    elicitation_id, params = _expected_params(world, run.id, APPROVE_TOKEN)

    async with serving(world) as sessions:
        await sessions.drain()

    assert sessions.gates.pending == {(anchor, elicitation_id): params}
    assert sessions.gates.calls == [("publish", anchor, elicitation_id)]
    (effect,) = effects(world, run.id, "publish_gate")
    row = work_for(world, run.id, effect.effect_key)
    assert row is not None and row.status == int(WorkStatus.SUCCEEDED)
    assert payload(row)["visit_id"] == gate_rows(world, run.id)[0].id
    assert row.result is not None
    assert '"published": true' in row.result and elicitation_id in row.result


async def test_a_visit_that_is_no_longer_live_is_not_published(delivery: Delivery) -> None:
    world = delivery.world
    run = start(world, GATED)
    hand_off(world, run.id)
    delivery.bindings.rows[(WORKSPACE, anchor_session_id(WORKSPACE, run.id))] = anchor_binding(
        run.id
    )
    # The rejection resolves the first visit; the run goes back to the step.
    assert answer(world, run.id, CHANGE_TOKEN, "reject").outcome == "accepted"

    outcome = await delivery.deliver(GATE_PUBLISH, run.id, CHANGE_TOKEN)

    assert _completed(outcome) == {"elicitation_id": None, "published": False}
    assert delivery.gates.calls == []


@pytest.mark.parametrize(
    "progress", [None, SessionBindingProgress.RESERVED, SessionBindingProgress.ROW_CREATED]
)
async def test_a_publish_waits_for_the_anchor_to_be_created(
    delivery: Delivery, progress: SessionBindingProgress | None
) -> None:
    world = delivery.world
    run = start(world, GATE_ONLY)
    if progress is not None:
        delivery.bindings.rows[(WORKSPACE, anchor_session_id(WORKSPACE, run.id))] = anchor_binding(
            run.id, progress
        )

    outcome = await delivery.deliver(GATE_PUBLISH, run.id, APPROVE_TOKEN)

    assert isinstance(outcome, EffectFailed)
    assert (outcome.error_code, outcome.retryable) == ("session.anchor_missing", True)
    assert delivery.gates.calls == []


def _cancel(world: World, run_id: str) -> None:
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run_id, actor="alice")


def _answer(world: World, run_id: str) -> None:
    assert answer(world, run_id, APPROVE_TOKEN, "approve").outcome == "accepted"


@pytest.mark.parametrize("racer", [_cancel, _answer], ids=["cancel", "answer"])
async def test_a_commit_between_the_two_loads_withdraws_the_prompt_it_published(
    delivery: Delivery, racer: Callable[[World, str], None]
) -> None:
    world = delivery.world
    run = start(world, GATE_ONLY)
    anchor = anchor_session_id(WORKSPACE, run.id)
    delivery.bindings.rows[(WORKSPACE, anchor)] = anchor_binding(run.id)
    elicitation_id = gate_rows(world, run.id)[0].elicitation_id
    assert elicitation_id is not None
    delivery.gates.after_publish = lambda: racer(world, run.id)

    outcome = await delivery.deliver(GATE_PUBLISH, run.id, APPROVE_TOKEN)

    assert _completed(outcome) == {"elicitation_id": elicitation_id, "published": False}
    assert delivery.gates.calls == [
        ("publish", anchor, elicitation_id),
        ("withdraw", anchor, elicitation_id),
    ]
    assert delivery.gates.pending == {}


async def test_a_live_visit_whose_row_is_not_written_yet_is_retried(delivery: Delivery) -> None:
    """A resync queues the publish before the commit that writes its row; a crash between."""
    world = delivery.world
    run = start(world, GATE_ONLY)
    delivery.bindings.rows[(WORKSPACE, anchor_session_id(WORKSPACE, run.id))] = anchor_binding(
        run.id
    )
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    (row,) = gate_rows(world, run.id)
    del runs.gate_visits[(WORKSPACE, run.id, row.id)]

    outcome = await delivery.deliver(GATE_PUBLISH, run.id, APPROVE_TOKEN)

    assert isinstance(outcome, EffectFailed)
    assert (outcome.error_code, outcome.retryable) == ("gate.row_missing", True)
    assert delivery.gates.calls == []


@pytest.mark.parametrize("visit_id", ["", "x" * 32, "A" * 32, "a" * 31, 7])
async def test_a_payload_without_a_visit_row_id_is_refused(
    delivery: Delivery, visit_id: object
) -> None:
    world = delivery.world
    run = start(world, GATE_ONLY)

    for effect_type in (GATE_PUBLISH, GATE_WITHDRAW):
        outcome = await delivery.deliver(
            effect_type, run.id, APPROVE_TOKEN, kind="publish_gate", visit_id=visit_id
        )
        assert isinstance(outcome, EffectFailed)
        assert (outcome.error_code, outcome.retryable) == ("effect.invalid_payload", False)
    assert delivery.gates.calls == []


async def test_a_lost_lease_stops_a_publish_before_the_prompt(delivery: Delivery) -> None:
    world = delivery.world
    run = start(world, GATE_ONLY)
    delivery.bindings.rows[(WORKSPACE, anchor_session_id(WORKSPACE, run.id))] = anchor_binding(
        run.id
    )

    async def lost() -> bool:
        return False

    with pytest.raises(StartupLeaseLost):
        await delivery.deliver(GATE_PUBLISH, run.id, APPROVE_TOKEN, ensure_lease=lost)
    assert delivery.gates.calls == []


async def test_a_cancel_withdraws_the_prompt_after_the_run_has_ended(world: World) -> None:
    run = start(world, GATE_ONLY)
    anchor = anchor_session_id(WORKSPACE, run.id)
    elicitation_id = gate_rows(world, run.id)[0].elicitation_id

    async with serving(world) as sessions:
        await sessions.drain()
        assert sessions.gates.pending.keys() == {(anchor, elicitation_id)}
        _cancel(world, run.id)
        await sessions.drain()

    assert get_registration(GATE_WITHDRAW) is None
    assert sessions.gates.pending == {}
    assert sessions.gates.calls[-1] == ("withdraw", anchor, elicitation_id)
    (effect,) = effects(world, run.id, "withdraw_gate")
    row = work_for(world, run.id, effect.effect_key)
    assert row is not None and row.status == int(WorkStatus.SUCCEEDED)


async def test_a_withdraw_is_idempotent_and_leaves_a_live_visit_alone(
    delivery: Delivery,
) -> None:
    world = delivery.world
    run = start(world, GATED)
    hand_off(world, run.id)
    anchor = anchor_session_id(WORKSPACE, run.id)
    first = gate_rows(world, run.id)[0].elicitation_id
    assert first is not None
    delivery.gates.pending[(anchor, first)] = {}
    # The rejection asks the gate again: the first visit is superseded, the second is live.
    assert answer(world, run.id, CHANGE_TOKEN, "reject").outcome == "accepted"
    hand_off(world, run.id, IMPLEMENT_AGAIN)
    second = gate_rows(world, run.id)[1].elicitation_id

    withdrawn = await delivery.deliver(GATE_WITHDRAW, run.id, CHANGE_TOKEN)
    again = await delivery.deliver(GATE_WITHDRAW, run.id, CHANGE_TOKEN)
    # A withdraw naming the live visit, which the engine never queues, withdraws nothing.
    live = await delivery.deliver(GATE_WITHDRAW, run.id, CHANGE_TOKEN_AGAIN, kind="publish_gate")

    assert _completed(withdrawn) == {"elicitation_id": first, "withdrawn": True}
    assert _completed(again) == {"elicitation_id": first, "withdrawn": False}
    assert _completed(live) == {"elicitation_id": second, "withdrawn": False}
    assert delivery.gates.calls == [("withdraw", anchor, first), ("withdraw", anchor, first)]


async def test_a_gate_asked_again_withdraws_the_old_prompt_and_publishes_the_new_one(
    delivery: Delivery,
) -> None:
    world = delivery.world
    run = start(world, GATED)
    anchor = anchor_session_id(WORKSPACE, run.id)
    delivery.bindings.rows[(WORKSPACE, anchor)] = anchor_binding(run.id)
    hand_off(world, run.id)
    published = await delivery.deliver(GATE_PUBLISH, run.id, CHANGE_TOKEN)
    first = _completed(published)["elicitation_id"]

    assert answer(world, run.id, CHANGE_TOKEN, "reject").outcome == "accepted"
    hand_off(world, run.id, IMPLEMENT_AGAIN)
    await delivery.deliver(GATE_WITHDRAW, run.id, CHANGE_TOKEN)
    await delivery.deliver(GATE_PUBLISH, run.id, CHANGE_TOKEN_AGAIN)

    second, params = _expected_params(world, run.id, CHANGE_TOKEN_AGAIN)
    assert first != second
    assert delivery.gates.pending == {(anchor, second): params}
    assert delivery.gates.calls == [
        ("publish", anchor, first),
        ("withdraw", anchor, first),
        ("publish", anchor, second),
    ]
