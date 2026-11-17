"""The planners of Coral's engine tools, by tool name."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from coral.tools.catalog import CHOOSE_ARROW, SUBMIT_HANDOFF
from coral.tools.handlers import choose_arrow, submit_handoff
from coral.tools.port import Plan

PLANNERS: Mapping[str, Callable[..., Plan]] = MappingProxyType(
    {SUBMIT_HANDOFF.name: submit_handoff.plan, CHOOSE_ARROW.name: choose_arrow.plan}
)
