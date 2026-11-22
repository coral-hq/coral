"""The planners of Coral's engine tools, by tool name."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from coral.tools.catalog import (
    ASSIGN_AGENTS,
    ASSIGN_TASK,
    CHOOSE_ARROW,
    MESSAGE_AGENT,
    SUBMIT_HANDOFF,
)
from coral.tools.handlers import assign, choose_arrow, message_agent, submit_handoff
from coral.tools.port import Plan

PLANNERS: Mapping[str, Callable[..., Plan]] = MappingProxyType(
    {
        SUBMIT_HANDOFF.name: submit_handoff.plan,
        CHOOSE_ARROW.name: choose_arrow.plan,
        MESSAGE_AGENT.name: message_agent.plan,
        ASSIGN_AGENTS.name: assign.plan_assign_agents,
        ASSIGN_TASK.name: assign.plan_assign_task,
    }
)
