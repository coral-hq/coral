"""V1-V4: graph shape, block structure, and arrow labelling."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from coral.model.ir import CompiledGraph
from coral.validate.problems import Problem
from coral.validate.registry import RuleInput, register_rule

_STRUCTURE_FACT_CODES = ("ambiguous_join", "split_without_join", "region_not_closed")


def _reachable(start_ids: Iterable[str], neighbours: dict[str, list[str]]) -> set[str]:
    seen = set(start_ids)
    queue = deque(seen)
    while queue:
        for neighbour in neighbours.get(queue.popleft(), ()):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


def _adjacency(graph: CompiledGraph) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    known = {node.id for node in graph.nodes}
    forward: dict[str, list[str]] = {}
    backward: dict[str, list[str]] = {}
    for arrow in graph.arrows:
        if arrow.source in known and arrow.target in known:
            forward.setdefault(arrow.source, []).append(arrow.target)
            backward.setdefault(arrow.target, []).append(arrow.source)
    return forward, backward


@register_rule("V1", fact_codes=("dangling_arrow",))
def check_start_end_reachability(inp: RuleInput) -> Iterable[Problem]:
    """Exactly one start, at least one end, and every node on a start-to-end path."""
    graph = inp.graph
    starts = [n for n in graph.nodes if n.kind == "start"]
    ends = [n for n in graph.nodes if n.kind == "end"]
    if not starts:
        yield inp.problem(
            "V1",
            "The workflow has no start node. Add one node with kind: start.",
            yaml_path="nodes",
        )
    for extra in starts[1:]:
        yield inp.problem(
            "V1",
            f"'{extra.id}' is a second start node. A workflow has exactly one start; "
            "remove it or change its kind.",
            node_ids=(extra.id,),
        )
    if not ends:
        yield inp.problem(
            "V1", "The workflow has no end node. Add a node with kind: end.", yaml_path="nodes"
        )
    for fact in graph.analysis.unresolved:
        if fact.code == "dangling_arrow":
            yield inp.problem("V1", fact.message, arrow_ids=fact.arrow_ids)
    start_ids = {n.id for n in starts}
    end_ids = {n.id for n in ends}
    for arrow in graph.arrows:
        if arrow.target in start_ids:
            yield inp.problem(
                "V1",
                f"Arrow '{arrow.id}' enters the start node '{arrow.target}'. "
                "Nothing may lead into the start; remove the arrow.",
                arrow_ids=(arrow.id,),
            )
        if arrow.source in end_ids:
            yield inp.problem(
                "V1",
                f"Arrow '{arrow.id}' leaves the end node '{arrow.source}'. "
                "An end has no outgoing arrows; remove the arrow.",
                arrow_ids=(arrow.id,),
            )
    forward, backward = _adjacency(graph)
    if len(starts) == 1:
        from_start = _reachable(start_ids, forward)
        for node in graph.nodes:
            if node.id not in from_start:
                yield inp.problem(
                    "V1",
                    f"'{node.id}' cannot be reached from the start. "
                    "Connect it with an arrow or delete it.",
                    node_ids=(node.id,),
                )
    if ends:
        to_end = _reachable(end_ids, backward)
        for node in graph.nodes:
            if node.id not in to_end:
                yield inp.problem(
                    "V1",
                    f"'{node.id}' cannot reach an end node. Add an arrow that leads onward.",
                    node_ids=(node.id,),
                )


@register_rule("V2", fact_codes=_STRUCTURE_FACT_CODES)
def check_block_structure(inp: RuleInput) -> Iterable[Problem]:
    """Parallel branches must form closed regions that meet at a matching AND-join."""
    for fact in inp.graph.analysis.unresolved:
        if fact.code in _STRUCTURE_FACT_CODES:
            yield inp.problem("V2", fact.message, node_ids=fact.node_ids, arrow_ids=fact.arrow_ids)


@register_rule("V3")
def check_mixed_labels(inp: RuleInput) -> Iterable[Problem]:
    """A node's outgoing arrows are all labelled (alternatives) or all unlabelled (parallel)."""
    for label_set in inp.graph.analysis.label_sets:
        if label_set.labelled_arrow_ids and label_set.unlabelled_arrow_ids:
            yield inp.problem(
                "V3",
                f"'{label_set.node_id}' has both labelled and unlabelled outgoing arrows "
                f"({', '.join(label_set.unlabelled_arrow_ids)} lack a label). "
                "Label every arrow for alternatives, or none for parallel branches.",
                node_ids=(label_set.node_id,),
                arrow_ids=label_set.unlabelled_arrow_ids,
            )


@register_rule("V4")
def check_label_sources(inp: RuleInput) -> Iterable[Problem]:
    """Only decisions, gates and single-agent steps may choose between arrows by label."""
    nodes = {node.id: node for node in reversed(inp.graph.nodes)}
    for label_set in inp.graph.analysis.label_sets:
        node = nodes[label_set.node_id]
        can_label = node.kind in ("decision", "gate") or (
            node.kind == "step" and len(node.roster) == 1
        )
        if label_set.labelled_arrow_ids and not can_label:
            reason = (
                "a step with several agents cannot pick one outcome"
                if node.kind == "step"
                else f"a {node.kind} node cannot choose between arrows"
            )
            yield inp.problem(
                "V4",
                f"'{node.id}' has labelled arrows, but {reason}. "
                "Remove the labels or use a decision node.",
                node_ids=(node.id,),
                arrow_ids=label_set.labelled_arrow_ids,
            )
        if (
            node.kind in ("decision", "gate")
            and not label_set.labelled_arrow_ids
            and len(label_set.unlabelled_arrow_ids) >= 2
        ):
            yield inp.problem(
                "V4",
                f"{node.kind.capitalize()} '{node.id}' has several outgoing arrows without "
                "labels. Give each arrow a label.",
                node_ids=(node.id,),
                arrow_ids=label_set.unlabelled_arrow_ids,
            )
        duplicates = sorted(
            {label for label in label_set.labels if label_set.labels.count(label) > 1}
        )
        for label in duplicates:
            yield inp.problem(
                "V4",
                f"'{node.id}' uses the label '{label}' on more than one arrow. "
                "Labels must be unique per node.",
                node_ids=(node.id,),
            )
