"""V10: steps only use harnesses the environment has enabled."""

from __future__ import annotations

from collections.abc import Iterable

from coral.validate.problems import Problem
from coral.validate.registry import RuleInput, register_rule


@register_rule("V10")
def check_harnesses(inp: RuleInput) -> Iterable[Problem]:
    for node in inp.graph.nodes:
        if node.harness is None:
            continue
        # Exact ``True`` only: truthy strings or numbers must not enable a harness.
        if inp.ctx.harnesses.get(node.harness) is not True:
            known = node.harness in inp.ctx.harnesses
            detail = (
                f"is set to {inp.ctx.harnesses[node.harness]!r}, not true"
                if known
                else "is not configured"
            )
            yield inp.problem(
                "V10",
                f"Step '{node.id}' uses harness '{node.harness}', which {detail}. "
                "Enable it in settings or choose another harness.",
                node_ids=(node.id,),
                field="harness",
            )
