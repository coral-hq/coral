"""coral_submit_handoff with the server's verdict on a step's done-when commands."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest

from coral.engine.types import HandoffEvaluated, HandoffReceived
from coral.evidence.ir import EvidenceVerdict, InProgress, Missing, MissingItem, Pass
from coral.model.ir import CompiledGraph
from coral.tools.catalog import SUBMIT_HANDOFF
from coral.tools.dispatch import EngineToolCall, ToolDispatcher
from coral.tools.handlers import PLANNERS
from coral.tools.replies import EVIDENCE_FINAL, EVIDENCE_RERUN, EVIDENCE_WAIT, STOP, STOP_BLOCKED
from coral.tools.schemas import EVALUATION_IN_PROGRESS, EVIDENCE_MISSING
from tests.coral.tools.fake_decision_port import InMemoryDecisionPort, step_binding
from tests.coral.workflow_builders import arrow, compile_text, end, start, step, workflow_text

SLOT = "work||:0"
ACTIVATION = "work||"
DONE_WHEN = {"commands": [{"run": "pytest -q"}]}
STALE = Missing(
    items=(
        MissingItem(
            item_id="c1", run="pytest -q", reason="predates_change", changed_path="api/users.py"
        ),
    )
)


def _graph(*, attempts: int = 3, failure: bool = False) -> CompiledGraph:
    nodes = [start(), step("work", attempts=attempts, done_when=DONE_WHEN), step("ship"), end()]
    arrows = [
        arrow("a1", "start", "work"),
        arrow("a2", "work", "ship"),
        arrow("a3", "ship", "end"),
    ]
    if failure:
        nodes.insert(-1, step("bail"))
        arrows += [arrow("a4", "work", "bail", label="failure"), arrow("a5", "bail", "end")]
    graph = compile_text(workflow_text(nodes, arrows))[0]
    assert not graph.analysis.unresolved, graph.analysis.unresolved
    return graph


@pytest.fixture
def port() -> Iterator[InMemoryDecisionPort]:
    port = InMemoryDecisionPort()
    yield port
    port.assert_folds()


@pytest.fixture
def dispatcher(port: InMemoryDecisionPort) -> ToolDispatcher:
    return ToolDispatcher(port, PLANNERS)


def _call(
    verdict: EvidenceVerdict | None, *, status: str = "done", op: str = "op-1"
) -> EngineToolCall:
    arguments: dict[str, object] = {"activation_id": ACTIVATION, "status": status, "report": "r"}
    if status == "blocked":
        arguments["blocked_reason"] = "stuck"
    return EngineToolCall(
        binding=step_binding(SLOT, session_id="sess-1"),
        tool=SUBMIT_HANDOFF.name,
        arguments=arguments,
        operation_id=op,
        evidence=verdict,
    )


def _slot_status(port: InMemoryDecisionPort) -> str:
    return next(slot.status for slot in port.state().slots if slot.id == SLOT)


def _used(port: InMemoryDecisionPort) -> int:
    counts = {item.activation_id: item.used for item in port.state().attempts}
    return counts.get(ACTIVATION, 0)


async def test_missing_evidence_is_counted_and_names_what_to_rerun(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_graph())
    before = len(port.log())

    reply = await dispatcher.dispatch(_call(STALE))

    assert (reply.accepted, reply.reason, reply.next) == (False, EVIDENCE_MISSING, EVIDENCE_RERUN)
    assert reply.message is not None
    assert "`pytest -q` ran before the last change to `api/users.py`" in reply.message
    received, evaluated = (entry.input for entry in port.log()[before:])
    assert isinstance(received, HandoffReceived)
    assert evaluated == HandoffEvaluated(slot_id=SLOT, outcome="evidence_missing", missing=("c1",))
    assert (_slot_status(port), _used(port)) == ("working", 1)


async def test_a_rerun_after_missing_evidence_is_accepted(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_graph())
    await dispatcher.dispatch(_call(STALE))

    reply = await dispatcher.dispatch(_call(Pass(), op="op-2"))

    assert reply.accepted and reply.next == STOP
    assert _slot_status(port) == "closing"


async def test_the_last_attempt_says_stop_and_takes_the_failure_arrow(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_graph(attempts=1, failure=True))

    reply = await dispatcher.dispatch(_call(STALE))

    assert (reply.reason, reply.next) == (EVIDENCE_MISSING, EVIDENCE_FINAL)
    assert reply.message is not None and "coral_submit_handoff" not in reply.message
    assert _slot_status(port) == "closing"
    assert any(item.node_id == "bail" for item in port.state().activations)


async def test_an_unfinished_check_writes_nothing_and_asks_to_retry(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_graph())
    version, before = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(InProgress(reason="a call is still running")))

    assert (reply.accepted, reply.reason, reply.next) == (
        False,
        EVALUATION_IN_PROGRESS,
        EVIDENCE_WAIT,
    )
    assert (port.row().version, len(port.log())) == (version, before)
    assert (_slot_status(port), _used(port)) == ("working", 0)


@pytest.mark.parametrize("verdict", [Pass(), None])
async def test_passing_or_absent_evidence_is_accepted(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, verdict: EvidenceVerdict | None
) -> None:
    port.add_run(_graph())

    reply = await dispatcher.dispatch(_call(verdict))

    assert reply.accepted and reply.next == STOP


async def test_a_blocked_handoff_skips_the_evidence_check(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_graph(failure=True))

    reply = await dispatcher.dispatch(_call(STALE, status="blocked"))

    assert reply.accepted and reply.next == STOP_BLOCKED
    assert _used(port) == 0


async def test_a_duplicate_after_acceptance_ignores_a_new_verdict(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_graph())
    first = await dispatcher.dispatch(_call(Pass()))

    again = await dispatcher.dispatch(dataclasses.replace(_call(STALE), operation_id="op-2"))

    assert first.accepted and again.accepted and again.duplicate
