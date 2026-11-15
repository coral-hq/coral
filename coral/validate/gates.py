"""V7: gate outcomes and arrow labels agree, and rejection is handled."""

from __future__ import annotations

from collections.abc import Iterable

from coral.model.ir import FAILURE_LABEL
from coral.validate.problems import Problem
from coral.validate.registry import RuleInput, register_rule

_APPROVE = "approve"
_REJECT = "reject"


@register_rule("V7")
def check_gates(inp: RuleInput) -> Iterable[Problem]:
    graph = inp.graph
    for node in graph.nodes:
        if node.kind != "gate":
            continue
        outcomes = set(node.outcomes)
        if len(outcomes) != len(node.outcomes):
            yield inp.problem(
                "V7", f"Gate '{node.id}' lists the same outcome twice.", node_ids=(node.id,)
            )
        if _APPROVE not in outcomes:
            yield inp.problem(
                "V7",
                f"Gate '{node.id}' has no 'approve' outcome. Add it so the workflow can proceed.",
                node_ids=(node.id,),
            )
        outgoing = [a for a in graph.arrows if a.source == node.id]
        arrow_labels = {a.label for a in outgoing if a.label is not None}
        for arrow in outgoing:
            if arrow.label is not None and arrow.label not in outcomes | {FAILURE_LABEL}:
                yield inp.problem(
                    "V7",
                    f"Arrow '{arrow.id}' is labelled '{arrow.label}', which is not an outcome "
                    f"of gate '{node.id}' ({', '.join(node.outcomes)}).",
                    node_ids=(node.id,),
                    arrow_ids=(arrow.id,),
                )
        for outcome in node.outcomes:
            if outcome not in arrow_labels:
                yield inp.problem(
                    "V7",
                    f"Gate '{node.id}' has the outcome '{outcome}' but no arrow with that label. "
                    "Add an arrow or remove the outcome.",
                    node_ids=(node.id,),
                )
        handles_rejection = (
            _REJECT in outcomes or FAILURE_LABEL in arrow_labels or outcomes == {_APPROVE}
        )
        if not handles_rejection:
            yield inp.problem(
                "V7",
                f"Gate '{node.id}' has no way to reject. Add a 'reject' outcome, a failure arrow, "
                "or make approve the only outcome.",
                node_ids=(node.id,),
            )
