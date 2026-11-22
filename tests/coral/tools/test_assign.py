"""coral_assign_agents and coral_assign_task through the decision port."""

from __future__ import annotations

import pytest

from coral.db.enum_codecs import RunStatus, SessionBindingProgress, SlotRole
from coral.engine.types import AwaitAssignment, RecordMergeConflict
from coral.tools.catalog import ASSIGN_AGENTS, ASSIGN_TASK
from coral.tools.dispatch import EngineToolCall, ToolDispatcher
from coral.tools.handlers import PLANNERS
from coral.tools.schemas import TOOL_ILLEGAL
from tests.coral.tools.fake_decision_port import InMemoryDecisionPort, step_binding
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    end,
    start,
    step,
    workflow_text,
)

ORCHESTRATOR = "orch-1"


def _graph():
    return compile_text(
        workflow_text(
            [start(), step("work"), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )[0]


def _port() -> InMemoryDecisionPort:
    port = InMemoryDecisionPort()
    port.add_run(_graph(), auto_ack=True)
    port.set_row(status=RunStatus.RUNNING, orchestrator_session_id=ORCHESTRATOR)
    return port


def _orch_call(tool: str, arguments: dict[str, object], *, op: str = "op-1") -> EngineToolCall:
    return EngineToolCall(
        binding=step_binding(
            "orchestrator",
            session_id=ORCHESTRATOR,
            slot_role=SlotRole.ORCHESTRATOR,
            progress=SessionBindingProgress.INITIALIZED,
        ),
        tool=tool,
        arguments=arguments,
        operation_id=op,
    )


def _open_merge_conflict(port: InMemoryDecisionPort) -> str:
    work = next(item for item in port.state().activations if item.node_id == "work")
    port.apply(
        RecordMergeConflict(activation_id=work.id, files=("src/a.py",)),
        auto_ack=False,
    )
    return work.id


@pytest.mark.asyncio
async def test_assign_task_retasks_merge_conflict_member() -> None:
    port = _port()
    activation_id = _open_merge_conflict(port)
    member = next(slot.id for slot in port.state().slots if slot.activation_id == activation_id)
    dispatcher = ToolDispatcher(port, PLANNERS)
    reply = await dispatcher.dispatch(
        _orch_call(
            ASSIGN_TASK.name,
            {
                "activation_id": activation_id,
                "member": member,
                "task": "Resolve the conflict markers and re-submit.",
                "reason": "Serial merge hit a conflict.",
            },
        )
    )
    assert reply.accepted is True
    steer = next(effect for effect in reversed(port.state().effects) if effect.kind == "steer")
    assert steer.subject == member
    assert "[Coral task]" in str(steer.payload.get("text"))
    owner = next(item for item in port.state().activations if item.id == activation_id)
    assert owner.resolver_slot_id == member


@pytest.mark.asyncio
async def test_assign_task_refuses_without_merge_conflict() -> None:
    port = _port()
    work = next(item for item in port.state().activations if item.node_id == "work")
    member = next(slot.id for slot in port.state().slots if slot.activation_id == work.id)
    dispatcher = ToolDispatcher(port, PLANNERS)
    reply = await dispatcher.dispatch(
        _orch_call(
            ASSIGN_TASK.name,
            {
                "activation_id": work.id,
                "member": member,
                "task": "Do something",
                "reason": "no conflict",
            },
        )
    )
    assert reply.accepted is False
    assert reply.reason == TOOL_ILLEGAL


@pytest.mark.asyncio
async def test_assign_agents_staffs_awaiting_assignment() -> None:
    port = _port()
    work = next(item for item in port.state().activations if item.node_id == "work")
    port.apply(AwaitAssignment(activation_id=work.id), auto_ack=False)
    dispatcher = ToolDispatcher(port, PLANNERS)
    reply = await dispatcher.dispatch(
        _orch_call(
            ASSIGN_AGENTS.name,
            {
                "activation_id": work.id,
                "assignments": [{"profile": "implementer", "count": 2}],
                "reason": "Staff the up-to roster.",
            },
        )
    )
    assert reply.accepted is True
    assert reply.members == ("implementer#1", "implementer#2")
    owner = next(item for item in port.state().activations if item.id == work.id)
    assert owner.sub_state is None
