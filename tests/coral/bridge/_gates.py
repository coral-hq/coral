"""Gate runs for the bridge tests, on the in-memory stores or a DB lane alike.

Work rows are found by the id their effect key derives, so the helpers need no
queue listing; a finished row is fed as the drainer would hand it over.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from coral.bridge.keys import effect_work_id
from coral.bridge.service import GateAnswerResult
from coral.db.enum_codecs import WorkStatus
from coral.engine import types as engine
from coral.model.ids import effect_session_id
from coral.queue import FinishedWork
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import GateVisitState, WorkItem
from tests.coral.bridge._scripted_runs import accept
from tests.coral.bridge._world import WORKSPACE, World
from tests.coral.workflow_builders import arrow, end, fixture_text, gate, workflow_text
from tests.coral.workflow_builders import start as start_node

GATED = fixture_text("gated")
GATE_ONLY = fixture_text("gate_only")
# ``gated`` loops from its gate back to the step: both are on pass 1 of loop a4, and a
# rejection sends the run to pass 2.
IMPLEMENT_FIRST = "implement||a4:1:0"
IMPLEMENT_AGAIN = "implement||a4:2:0"
CHANGE_TOKEN = "approve_change||a4:1:1"
CHANGE_TOKEN_AGAIN = "approve_change||a4:2:2"
APPROVE_TOKEN = "approve||:1"
# A gate whose rejection asks it again in the same transition.
ASKED_AGAIN = workflow_text(
    [start_node(), gate("hold", outcomes=["approve", "reject"]), end()],
    [
        arrow("a1", "start", "hold"),
        arrow("a2", "hold", "end", label="approve"),
        arrow("a3", "hold", "hold", label="reject", back=True, limit=3, at_limit="a2"),
    ],
)
HOLD_TOKEN = "hold||a3:1:1"
HOLD_TOKEN_AGAIN = "hold||a3:2:2"


class GateIds:
    """Elicitation ids a test can predict: ``coral_gate_`` and a counter in 32 hex."""

    def __init__(self) -> None:
        self.issued: list[str] = []

    def __call__(self) -> str:
        value = f"coral_gate_{len(self.issued) + 1:032x}"
        self.issued.append(value)
        return value


def before_next_commit(world: World, action: Callable[[], object]) -> None:
    """Run ``action`` once, just before the next commit lands, so that commit loses its CAS."""
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    fired: list[bool] = []

    def first(_run_id: str, _expected_version: int) -> None:
        if not fired:
            fired.append(True)
            action()

    runs.before_apply_hook = first


def gate_rows(world: World, run_id: str) -> list[GateVisitState]:
    """The run's ``coral_gate_visits`` rows, oldest visit first."""
    state, _version = world.runs.load_run_state(run_id, workspace_id=WORKSPACE)
    return sorted(state.gate_visits, key=lambda row: (row.node_id, row.visit_no))


def effects(
    world: World, run_id: str, kind: str, *, workspace_id: int = WORKSPACE
) -> list[engine.Effect]:
    """The run's engine effects of ``kind``, in the order they were emitted."""
    state = world.bridge.load(workspace_id=workspace_id, run_id=run_id).state
    return [effect for effect in state.effects if effect.kind == kind]


def work_for(
    world: World, run_id: str, effect_key: str, *, workspace_id: int = WORKSPACE
) -> WorkItem | None:
    """The work row an effect key queued, if any."""
    rows = world.queue.get_work([effect_work_id(run_id, effect_key)], workspace_id=workspace_id)
    return rows[0] if rows else None


def payload(item: WorkItem) -> dict[str, Any]:
    return json.loads(item.payload)


def complete(
    world: World,
    run_id: str,
    kind: str,
    subject: str,
    result: dict[str, Any] | None = None,
    *,
    workspace_id: int = WORKSPACE,
) -> None:
    """Feed a success of the latest ``kind`` effect about ``subject``, as the drainer would."""
    (effect, *_older) = reversed(
        [
            effect
            for effect in effects(world, run_id, kind, workspace_id=workspace_id)
            if effect.subject == subject
        ]
    )
    item = work_for(world, run_id, effect.effect_key, workspace_id=workspace_id)
    assert item is not None, f"no row for {effect.effect_key}"
    world.bridge.feed(
        FinishedWork(item=item, status=int(WorkStatus.SUCCEEDED), error_code=None, result=result)
    )


def brief(world: World, run_id: str, slot: str, *, workspace_id: int = WORKSPACE) -> str:
    """The slot's latest session is created and briefed, so its step works; its session id."""
    (create, *_older) = reversed(
        [
            effect
            for effect in effects(world, run_id, "create_session", workspace_id=workspace_id)
            if effect.subject == slot
        ]
    )
    session_id = effect_session_id(workspace_id, create.effect_key)
    # A first generation's create names no generation; a retried one names its own.
    generation = create.payload.get("generation", 1)
    created = {"session_id": session_id, "role": "step", "generation": generation}
    complete(world, run_id, "create_session", slot, created, workspace_id=workspace_id)
    sent = {"session_id": session_id, "stable_id": "m1"}
    complete(world, run_id, "send_input", slot, sent, workspace_id=workspace_id)
    return session_id


def hand_off(
    world: World, run_id: str, slot: str = IMPLEMENT_FIRST, report: str = "Done."
) -> None:
    """The slot's session is created and briefed, it hands off done, and it closes."""
    session = {"session_id": "s" * 32, "role": "step", "generation": 1}
    complete(world, run_id, "create_session", slot, session)
    complete(world, run_id, "send_input", slot, {"session_id": "s" * 32, "stable_id": "m1"})
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE, run_id=run_id, inputs=lambda _snapshot: accept(slot, report)
    )
    complete(world, run_id, "close_slot", slot, {})


def answer(
    world: World,
    run_id: str,
    token: str,
    label: str,
    *,
    note: str = "",
    actor: str = "alice",
) -> GateAnswerResult:
    return world.bridge.answer_gate(
        workspace_id=WORKSPACE, run_id=run_id, token=token, label=label, note=note, actor=actor
    )


def visit(world: World, run_id: str, token: str) -> engine.GateVisit:
    state = world.bridge.load(workspace_id=WORKSPACE, run_id=run_id).state
    (found,) = (item for item in state.gates if item.token == token)
    return found
