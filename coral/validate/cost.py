"""V12: an upper bound on step activations stays within the configured budget."""

from __future__ import annotations

from collections.abc import Iterable

from coral.validate.problems import Problem
from coral.validate.registry import RuleInput, register_rule


def activation_upper_bound(inp: RuleInput) -> int:
    """Worst-case step activations: attempts times loop passes times list fan-out."""
    total = 0
    for node in inp.graph.nodes:
        if node.kind != "step":
            continue
        activations = node.attempts or 1
        for loop in inp.graph.analysis.loops:
            if node.id in loop.body and loop.limit is not None and loop.limit >= 1:
                activations *= loop.limit + 1
        if node.list_from is not None:
            activations *= inp.ctx.max_list_items
        total += activations
    return total


@register_rule("V12")
def check_activation_budget(inp: RuleInput) -> Iterable[Problem]:
    bound = activation_upper_bound(inp)
    limit = inp.ctx.max_activations
    if bound > limit:
        yield inp.problem(
            "V12",
            f"This workflow could run up to {bound} step activations, above the limit of "
            f"{limit}. Lower attempts or loop limits, or split the workflow.",
            yaml_path="",
        )
    elif bound > limit * inp.ctx.warn_ratio:
        yield inp.problem(
            "V12",
            f"This workflow could run up to {bound} step activations, close to the limit of "
            f"{limit}.",
            severity="warning",
            yaml_path="",
        )
