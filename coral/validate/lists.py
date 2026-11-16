"""V6: ``list_from`` points at a list part on an upstream node."""

from __future__ import annotations

from collections.abc import Iterable

from coral.validate.problems import Problem
from coral.validate.registry import RuleInput, register_rule


@register_rule("V6")
def check_list_from(inp: RuleInput) -> Iterable[Problem]:
    for checked in inp.graph.analysis.checked_parts:
        node_id, reference = checked.node_id, checked.reference
        problem = None
        if checked.part_name is None:
            problem = "use the form node_id.part_name, for example 'plan.items'"
        elif not checked.source_exists:
            problem = f"there is no node '{checked.source_node_id}'"
        elif not checked.source_upstream:
            problem = f"'{checked.source_node_id}' does not run before '{node_id}'"
        elif not checked.part_is_list:
            problem = (
                f"'{checked.source_node_id}' has no list part named '{checked.part_name}'; "
                "declare it under parts with kind: list"
            )
        if problem is not None:
            yield inp.problem(
                "V6",
                f"Step '{node_id}' has list_from '{reference}': {problem}.",
                node_ids=(node_id,),
                field="list_from",
            )
