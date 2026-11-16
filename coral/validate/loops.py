"""V5: loops have one back-arrow, a limit, an exit outside the body, and a single entry."""

from __future__ import annotations

from collections.abc import Iterable

from coral.validate.problems import Problem
from coral.validate.registry import RuleInput, register_rule

_LOOP_FACT_CODES = ("cycle_without_back_arrow", "back_arrow_not_cycle")


@register_rule("V5", fact_codes=_LOOP_FACT_CODES)
def check_loops(inp: RuleInput) -> Iterable[Problem]:
    graph = inp.graph
    for fact in graph.analysis.unresolved:
        if fact.code in _LOOP_FACT_CODES:
            yield inp.problem("V5", fact.message, node_ids=fact.node_ids, arrow_ids=fact.arrow_ids)
    for arrow in graph.arrows:
        if arrow.kind != "back" and (arrow.limit is not None or arrow.at_limit is not None):
            yield inp.problem(
                "V5",
                f"Arrow '{arrow.id}' sets limit or at_limit but is not a back arrow. "
                "Remove them or add back: true.",
                arrow_ids=(arrow.id,),
            )
    arrows_by_id = {arrow.id: arrow for arrow in reversed(graph.arrows)}
    loops = graph.analysis.loops
    for loop in loops:
        back = arrows_by_id[loop.back_arrow_id]
        if back.label is None:
            yield inp.problem(
                "V5",
                f"Back arrow '{back.id}' has no label. Give it the label that selects the retry.",
                arrow_ids=(back.id,),
            )
        if back.limit is None or back.limit < 1:
            yield inp.problem(
                "V5",
                f"Back arrow '{back.id}' needs limit: 1 or more so the loop always ends.",
                arrow_ids=(back.id,),
                field="limit" if back.limit is not None else None,
            )
        body = set(loop.body)
        if back.at_limit is None:
            yield inp.problem(
                "V5",
                f"Back arrow '{back.id}' needs at_limit naming the arrow taken when the "
                "limit is reached.",
                arrow_ids=(back.id,),
            )
        else:
            exit_arrow = arrows_by_id.get(back.at_limit)
            if exit_arrow is None:
                yield inp.problem(
                    "V5",
                    f"Back arrow '{back.id}' names at_limit '{back.at_limit}', which is not "
                    "an arrow id.",
                    arrow_ids=(back.id,),
                    field="at_limit",
                )
            elif exit_arrow.source != back.source:
                yield inp.problem(
                    "V5",
                    f"at_limit arrow '{exit_arrow.id}' must leave '{back.source}', "
                    f"the same node as back arrow '{back.id}'.",
                    arrow_ids=(back.id, exit_arrow.id),
                )
            elif body and exit_arrow.target in body:
                yield inp.problem(
                    "V5",
                    f"at_limit arrow '{exit_arrow.id}' leads back into the loop. "
                    "It must exit to a node outside the loop body.",
                    arrow_ids=(back.id, exit_arrow.id),
                )
        for entry_id in loop.entry_arrow_ids:
            entry = arrows_by_id[entry_id]
            if entry.target != loop.head:
                yield inp.problem(
                    "V5",
                    f"Arrow '{entry.id}' enters the loop at '{entry.target}'. "
                    f"A loop must be entered only at its first node '{loop.head}'.",
                    node_ids=(entry.target,),
                    arrow_ids=(entry.id,),
                )
    for position, loop in enumerate(loops):
        for other in loops[position + 1 :]:
            if loop.head == other.head:
                yield inp.problem(
                    "V5",
                    f"Back arrows '{loop.back_arrow_id}' and '{other.back_arrow_id}' both return "
                    f"to '{loop.head}'. Use one back arrow per loop.",
                    arrow_ids=(other.back_arrow_id,),
                )
                continue
            body, other_body = set(loop.body), set(other.body)
            if body & other_body and not (body <= other_body or other_body <= body):
                yield inp.problem(
                    "V5",
                    f"Loops closed by '{loop.back_arrow_id}' and '{other.back_arrow_id}' overlap "
                    "without one containing the other. Nest them or separate them.",
                    arrow_ids=(other.back_arrow_id,),
                )
