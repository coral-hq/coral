"""Pure-tier static validation of compiled workflows. Must not import ``omnigent``."""

from __future__ import annotations

from coral.model.ir import CompiledGraph
from coral.model.sourcemap import SourceMap

# Importing the rule modules registers V1-V7, V10, V12 and V13.
from coral.validate import cost, gates, ids, lists, loops, profiles, structure  # noqa: F401
from coral.validate.context import ValidateContext
from coral.validate.problems import Problem, Severity, ValidationReport
from coral.validate.registry import RuleInput, register_rule, registered_rules

__all__ = [
    "Problem",
    "RuleInput",
    "Severity",
    "ValidateContext",
    "ValidationReport",
    "register_rule",
    "registered_rules",
    "validate",
]

UNHANDLED_FACT_RULE = "A0"


def validate(
    graph: CompiledGraph, source_map: SourceMap, ctx: ValidateContext | None = None
) -> ValidationReport:
    """Run every registered rule and report all findings together."""
    inp = RuleInput(graph, source_map, ctx or ValidateContext())
    problems: list[Problem] = []
    claimed: set[str] = set()
    for spec in registered_rules():
        claimed |= spec.fact_codes
        problems.extend(spec.check(inp))
    # Analysis facts no rule reports on must still block running.
    for fact in graph.analysis.unresolved:
        if fact.code not in claimed:
            problems.append(
                inp.problem(
                    UNHANDLED_FACT_RULE,
                    fact.message,
                    node_ids=fact.node_ids,
                    arrow_ids=fact.arrow_ids,
                )
            )
    runnable = not any(problem.severity == "error" for problem in problems)
    return ValidationReport(problems=tuple(problems), runnable=runnable)
