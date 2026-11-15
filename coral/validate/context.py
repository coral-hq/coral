"""Inputs the validator needs besides the graph."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from coral.model.ir import CompiledGraph

DEFAULT_MAX_ACTIVATIONS = 200
DEFAULT_WARN_RATIO = 0.8
DEFAULT_MAX_LIST_ITEMS = 10


@dataclass(frozen=True)
class ValidateContext:
    """Environment facts for rules that depend on the deployment.

    ``harnesses`` maps harness name to its availability; only an exact ``True``
    counts as available. ``previous`` is the prior saved version, used for
    rename hints.
    """

    harnesses: Mapping[str, object] = field(default_factory=dict)
    max_activations: int = DEFAULT_MAX_ACTIVATIONS
    warn_ratio: float = DEFAULT_WARN_RATIO
    max_list_items: int = DEFAULT_MAX_LIST_ITEMS
    previous: CompiledGraph | None = None
