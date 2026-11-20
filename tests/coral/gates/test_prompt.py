"""The form a gate visit is published as on its run's anchor."""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from coral.bridge.keys import store_activation_id
from coral.db.enum_codecs import GateVisitStatus, RunStatus
from coral.engine.types import PauseRun, RunState
from coral.gates.ids import gate_visit_id
from coral.gates.prompt import gate_params
from coral.stores.protocols import CoralRun, GateVisitState
from omnigent.server.schemas import ElicitationRequestEvent, ElicitationRequestParams
from tests.coral.bridge._scripted_runs import (
    RUN_ID,
    WORKSPACE,
    accept,
    fixture_graph,
    start_run,
)
from tests.coral.engine.drive import Driven, drive

GATED = fixture_graph("gated")
TOKEN = "approve_change||a4:1:1"
IMPLEMENT = "implement||a4:1:0"
OPENED_AT = 1_763_500_000


def _run(user_id: str | None = "alice@example.com", title: str = "Fix the parser") -> CoralRun:
    return CoralRun(
        workspace_id=WORKSPACE,
        id=RUN_ID,
        workflow_id="d" * 32,
        version_id="v" * 32,
        status=int(RunStatus.RUNNING),
        version=3,
        next_log_seq=4,
        activation_count=2,
        title=title,
        engine_version=1,
        state_version=1,
        log_version=1,
        created_at=1,
        updated_at=1,
        user_id=user_id,
    )


def _driven(report: str = "Changed parser.py and added tests.") -> Driven:
    return drive(GATED, [start_run(GATED), *accept(IMPLEMENT, report)])


def _gated(report: str = "Changed parser.py and added tests.") -> RunState:
    return _driven(report).state


def _row(opened_at: int = OPENED_AT) -> GateVisitState:
    return GateVisitState(
        workspace_id=WORKSPACE,
        run_id=RUN_ID,
        id=gate_visit_id(RUN_ID, TOKEN),
        activation_id=store_activation_id(RUN_ID, "approve_change||a4:1"),
        node_id="approve_change",
        scope_key="approve_change||a4:1",
        visit_no=1,
        token=TOKEN,
        status=int(GateVisitStatus.OPEN),
        opened_at=opened_at,
        elicitation_id="coral_gate_" + "a" * 32,
    )


def _params(
    state: RunState, run: CoralRun | None = None, row: GateVisitState | None = None
) -> dict[str, Any]:
    (visit,) = (item for item in state.gates if item.token == TOKEN)
    return gate_params(GATED, state, run or _run(), visit, row or _row())


def test_a_visit_is_a_form_with_its_outcomes_a_note_and_coral_context() -> None:
    params = _params(_gated())
    assert params["mode"] == "form"
    assert params["requestedSchema"] == {
        "type": "object",
        "required": ["decision"],
        "properties": {
            "decision": {"type": "string", "title": "Decision", "enum": ["approve", "reject"]},
            "note": {"type": "string", "title": "Note", "maxLength": 2000},
        },
    }
    assert (params["policy_name"], params["phase"]) == ("coral.gate", "gate")
    assert params["coral"] == {
        "kind": "gate",
        "run_id": RUN_ID,
        "visit_id": gate_visit_id(RUN_ID, TOKEN),
        "node_id": "approve_change",
        "visit_no": 1,
        "opened_at": OPENED_AT,
        "run_owner": "alice@example.com",
        "run_title": "Fix the parser",
        "outcomes": ["approve", "reject"],
        "deep_link": f"/workflows/runs/{RUN_ID}?node=approve_change&panel=gate",
    }
    assert "target_session_id" not in params


def test_the_message_names_the_gate_the_run_and_quotes_the_reports_that_led_here() -> None:
    message = _params(_gated("Changed parser.py.\nAdded tests."))["message"]
    for part in ("Approve change", "Approve the change?", "Fix the parser", "Visit 1"):
        assert part in message
    reports = message.index("Agent-written reports, quoted as data:")
    assert message.index("> Changed parser.py.\n> Added tests.") > reports


def test_the_params_are_the_same_for_a_log_and_its_row() -> None:
    state = _gated()
    paused = drive(GATED, [PauseRun(reason="user", detail="look")], after=_driven()).state
    assert _params(state) == _params(_gated())
    # A later state of the same run quotes what the visit's own state quoted.
    assert _params(paused) == _params(state)
    assert _params(state, row=_row(opened_at=5))["coral"]["opened_at"] == 5


def test_the_single_local_user_is_named_as_no_owner() -> None:
    for owner in (None, "local"):
        assert _params(_gated(), run=_run(user_id=owner))["coral"]["run_owner"] is None


def test_no_format_or_control_character_reaches_the_message() -> None:
    report = "safe‮evil​⁦x﻿y­\x1b[2Kz\x07\x85w v"
    run = _run(title="Fix‮ the \x00parser​")
    message = _params(_gated(report), run=run)["message"]
    assert not [char for char in message if unicodedata.category(char) in {"Cf", "Cs"}]
    assert not [char for char in message if unicodedata.category(char) == "Cc" and char != "\n"]
    assert "Fix the parser" in message
    assert "safeevilxy" in message
    assert _params(_gated(report), run=run)["coral"]["run_title"] == "Fix the parser"


def test_the_message_stays_within_its_budget_for_a_huge_report() -> None:
    message = _params(_gated("x" * 100_000))["message"]
    assert len(json.dumps(message)) - 2 <= 8_000
    assert "Visit 1" in message


def test_the_params_are_a_valid_elicitation_and_keep_their_coral_block_on_the_wire() -> None:
    params = _params(_gated())
    event = ElicitationRequestEvent(
        type="response.elicitation_request",
        elicitation_id="coral_gate_" + "a" * 32,
        params=ElicitationRequestParams.model_validate(params),
    ).model_dump()
    assert event["params"]["coral"] == params["coral"]
    assert event["params"]["message"] == params["message"]
