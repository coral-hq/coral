"""Gate ids, caps and the one rule that says whether a visit can still be answered."""

from __future__ import annotations

import pytest

from coral.alerts.types import MAX_ALERT_OUTCOME_CHARS, MAX_ALERT_OUTCOMES
from coral.engine.types import GateVisit, RunState
from coral.gates.ids import (
    GATE_ELICITATION_ID,
    GATE_ELICITATION_PREFIX,
    MAX_GATE_OUTCOME_CHARS,
    MAX_GATE_OUTCOMES,
    find_visit,
    gate_node,
    gate_visit_id,
    is_binary_gate,
    live_visit,
    live_visit_ids,
    new_gate_elicitation_id,
    row_by_elicitation,
)
from coral.model.ids import derived_id
from coral.stores.protocols import GateVisitState
from tests.coral.bridge._scripted_runs import fixture_graph

RUN = "r" * 32
OPEN = GateVisit(activation_id="approve||", token="approve||:1", visit_no=1, status="open")


@pytest.mark.parametrize(
    ("run_status", "visit_status", "live"),
    [
        ("running", "open", True),
        ("paused", "open", True),
        ("completed", "open", False),
        ("failed", "open", False),
        ("cancelled", "open", False),
        (None, "open", False),
        ("running", "resolved", False),
        ("paused", "superseded", False),
    ],
)
def test_a_visit_is_live_while_open_in_a_started_unfinished_run(
    run_status: str | None, visit_status: str, live: bool
) -> None:
    visit = OPEN.model_copy(update={"status": visit_status})
    state = RunState(status=run_status, gates=(visit,))  # type: ignore[arg-type]
    assert live_visit(state, visit) is live
    assert live_visit_ids(state, RUN) == (
        frozenset({gate_visit_id(RUN, visit.token)}) if live else frozenset()
    )


def test_elicitation_ids_are_random_and_claimable_by_the_gate_prefix() -> None:
    first, second = new_gate_elicitation_id(), new_gate_elicitation_id()
    assert first != second
    for value in (first, second):
        assert GATE_ELICITATION_ID.fullmatch(value)
        assert value.startswith(GATE_ELICITATION_PREFIX)
        assert len(value) <= 64


def test_a_visit_row_id_derives_from_the_run_and_the_whole_token() -> None:
    token = "approve||a4:1:2"
    assert gate_visit_id(RUN, token) == derived_id("coral-gate-visit", RUN, token)
    assert gate_visit_id(RUN, token) != gate_visit_id(RUN, "approve||a4:1:3")
    assert len(gate_visit_id(RUN, "x" * 512)) == 32


def test_lookups_find_a_visit_by_row_id_and_a_row_by_elicitation_id() -> None:
    later = GateVisit(activation_id="approve||", token="approve||:2", visit_no=2, status="open")
    state = RunState(status="running", gates=(OPEN, later))
    assert find_visit(state, RUN, gate_visit_id(RUN, later.token)) == later
    assert find_visit(state, RUN, "0" * 32) is None
    rows = [_row(gate_visit_id(RUN, OPEN.token), "coral_gate_" + "a" * 32)]
    assert row_by_elicitation(rows, "coral_gate_" + "a" * 32) == rows[0]
    assert row_by_elicitation(rows, "coral_gate_" + "b" * 32) is None


def test_the_gate_node_and_whether_it_is_binary() -> None:
    gated = fixture_graph("gated")
    node = gate_node(gated, OPEN.model_copy(update={"activation_id": "approve_change||a4:1"}))
    assert node is not None and node.id == "approve_change"
    assert is_binary_gate(node)
    assert gate_node(gated, OPEN) is None
    approve_only = node.model_copy(update={"outcomes": ("approve",)})
    assert is_binary_gate(approve_only)
    assert not is_binary_gate(node.model_copy(update={"outcomes": ("approve", "defer")}))


def test_gate_outcome_caps_match_what_an_alert_can_list() -> None:
    assert (MAX_GATE_OUTCOMES, MAX_GATE_OUTCOME_CHARS) == (
        MAX_ALERT_OUTCOMES,
        MAX_ALERT_OUTCOME_CHARS,
    )


def _row(row_id: str, elicitation_id: str) -> GateVisitState:
    return GateVisitState(
        workspace_id=7,
        run_id=RUN,
        id=row_id,
        activation_id="a" * 32,
        node_id="approve",
        scope_key="approve||",
        visit_no=1,
        token="approve||:1",
        status=1,
        opened_at=1,
        elicitation_id=elicitation_id,
    )
