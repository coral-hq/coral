"""Static graph analysis: joins, loops, parallel regions, labels and list references.

Analysis never raises. Anything it cannot resolve becomes an ``UnresolvedFact``
that the validator reports and that blocks running the workflow.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable

from coral.model.ir import (
    Analysis,
    CheckedPart,
    CompiledArrow,
    CompiledNode,
    JoinInfo,
    LabelSet,
    LoopInfo,
    Region,
    UnresolvedFact,
)


class _GraphIndex:
    """Adjacency views over the arrows whose endpoints both exist."""

    def __init__(self, nodes: tuple[CompiledNode, ...], arrows: tuple[CompiledArrow, ...]) -> None:
        self.nodes_by_id: dict[str, CompiledNode] = {}
        self.order: dict[str, int] = {}
        for position, node in enumerate(nodes):
            self.nodes_by_id.setdefault(node.id, node)
            self.order.setdefault(node.id, position)
        self.dangling: list[CompiledArrow] = []
        self.arrows: list[CompiledArrow] = []
        for arrow in arrows:
            connected = arrow.source in self.nodes_by_id and arrow.target in self.nodes_by_id
            (self.arrows if connected else self.dangling).append(arrow)
        self.structural_out = self._group(("forward", "at_limit"), by_source=True)
        self.structural_in = self._group(("forward", "at_limit"), by_source=False)
        self.non_back_out = self._group(("forward", "at_limit", "failure"), by_source=True)
        self.non_back_in = self._group(("forward", "at_limit", "failure"), by_source=False)
        self._reach_cache: dict[str, set[str]] = {}

    def _group(self, kinds: tuple[str, ...], *, by_source: bool) -> dict[str, list[CompiledArrow]]:
        grouped: dict[str, list[CompiledArrow]] = {node_id: [] for node_id in self.nodes_by_id}
        for arrow in self.arrows:
            if arrow.kind in kinds:
                grouped[arrow.source if by_source else arrow.target].append(arrow)
        return grouped

    def sorted_ids(self, node_ids: Iterable[str]) -> tuple[str, ...]:
        return tuple(sorted(set(node_ids), key=lambda node_id: self.order[node_id]))

    def reach(self, start: str) -> set[str]:
        """Nodes reachable from ``start`` (inclusive) over structural arrows."""
        cached = self._reach_cache.get(start)
        if cached is None:
            cached = _bfs(start, lambda node_id: (a.target for a in self.structural_out[node_id]))
            self._reach_cache[start] = cached
        return cached


def _bfs(start: str, neighbours: Callable[[str], Iterable[str]]) -> set[str]:
    seen = {start}
    queue = deque([start])
    while queue:
        for neighbour in neighbours(queue.popleft()):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


def _topological_index(graph: _GraphIndex) -> dict[str, int]:
    """Kahn order over structural arrows; nodes on cycles sort last."""
    in_degree = {node_id: len(arrows) for node_id, arrows in graph.structural_in.items()}
    queue = deque(sorted((n for n, d in in_degree.items() if d == 0), key=graph.order.__getitem__))
    index: dict[str, int] = {}
    while queue:
        node_id = queue.popleft()
        index[node_id] = len(index)
        for arrow in graph.structural_out[node_id]:
            in_degree[arrow.target] -= 1
            if in_degree[arrow.target] == 0:
                queue.append(arrow.target)
    for node_id in sorted(graph.nodes_by_id, key=graph.order.__getitem__):  # type: ignore[arg-type]
        index.setdefault(node_id, len(index))
    return index


def _cyclic_components(graph: _GraphIndex) -> list[tuple[str, ...]]:
    """Strongly connected components with a cycle, over all non-back arrows (iterative Tarjan)."""
    index_of: dict[str, int] = {}
    low_link: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[tuple[str, ...]] = []
    counter = 0
    for root in sorted(graph.nodes_by_id, key=graph.order.__getitem__):  # type: ignore[arg-type]
        if root in index_of:
            continue
        work = [(root, iter(graph.non_back_out[root]))]
        index_of[root] = low_link[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node_id, arrows = work[-1]
            advanced = False
            for arrow in arrows:
                target = arrow.target
                if target not in index_of:
                    index_of[target] = low_link[target] = counter
                    counter += 1
                    stack.append(target)
                    on_stack.add(target)
                    work.append((target, iter(graph.non_back_out[target])))
                    advanced = True
                    break
                if target in on_stack:
                    low_link[node_id] = min(low_link[node_id], index_of[target])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low_link[parent] = min(low_link[parent], low_link[node_id])
            if low_link[node_id] == index_of[node_id]:
                members = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    members.append(member)
                    if member == node_id:
                        break
                has_self_loop = any(a.target == node_id for a in graph.non_back_out[node_id])
                if len(members) > 1 or has_self_loop:
                    components.append(graph.sorted_ids(members))
    return components


def _analyze_loops(graph: _GraphIndex, facts: list[UnresolvedFact]) -> tuple[LoopInfo, ...]:
    loops = []
    for arrow in graph.arrows:
        if arrow.kind != "back":
            continue
        head, tail = arrow.target, arrow.source
        downstream = _bfs(head, lambda n: (a.target for a in graph.non_back_out[n]))
        if tail not in downstream:
            facts.append(
                UnresolvedFact(
                    code="back_arrow_not_cycle",
                    message=(
                        f"back arrow '{arrow.id}' goes to '{head}', which does not lead back to "
                        f"'{tail}'; point it at an earlier step of the same path"
                    ),
                    node_ids=(tail, head),
                    arrow_ids=(arrow.id,),
                )
            )
            body: tuple[str, ...] = ()
        else:
            upstream = _bfs(tail, lambda n: (a.source for a in graph.non_back_in[n]))
            body = graph.sorted_ids(downstream & upstream)
        body_set = set(body)
        entries = tuple(
            entry.id
            for entry in graph.arrows
            if entry.kind != "back" and entry.target in body_set and entry.source not in body_set
        )
        loops.append(
            LoopInfo(
                back_arrow_id=arrow.id,
                head=head,
                tail=tail,
                body=body,
                limit=arrow.limit,
                at_limit_arrow_id=arrow.at_limit,
                entry_arrow_ids=entries,
            )
        )
    return tuple(loops)


def _parallel_splits(graph: _GraphIndex) -> dict[str, list[CompiledArrow]]:
    """Nodes whose forward arrows are all unlabelled and number at least two."""
    splits: dict[str, list[CompiledArrow]] = {}
    for node_id in graph.nodes_by_id:
        forward = [a for a in graph.structural_out[node_id] if a.kind == "forward"]
        if len(forward) >= 2 and all(a.label is None for a in forward):
            splits[node_id] = forward
    return splits


def _analyze_joins(
    graph: _GraphIndex, facts: list[UnresolvedFact]
) -> tuple[tuple[JoinInfo, ...], dict[str, str]]:
    """Classify multi-input nodes; returns joins and a split-to-AND-join map."""
    topo = _topological_index(graph)
    splits = _parallel_splits(graph)
    closed_splits: dict[str, str] = {}
    joins = []
    candidates = sorted(
        (n for n, arrows in graph.structural_in.items() if len(arrows) >= 2),
        key=lambda n: topo[n],
    )
    for join_id in candidates:
        incoming = graph.structural_in[join_id]
        arrow_ids = tuple(a.id for a in incoming)
        verdict = "xor"
        split_id: str | None = None
        for split_candidate in sorted(splits, key=lambda n: -topo[n]):
            if split_candidate == join_id or split_candidate in closed_splits:
                continue
            if join_id not in graph.reach(split_candidate):
                continue
            branch_sets = [
                {
                    branch.id
                    for branch in splits[split_candidate]
                    if branch.id == arrow.id or arrow.source in graph.reach(branch.target)
                }
                for arrow in incoming
            ]
            covered = set().union(*branch_sets)
            if len(covered) < 2:
                continue
            singles = [next(iter(s)) for s in branch_sets if len(s) == 1]
            if len(singles) == len(branch_sets) and len(set(singles)) == len(singles):
                verdict, split_id = "and", split_candidate
            else:
                facts.append(
                    UnresolvedFact(
                        code="ambiguous_join",
                        message=(
                            f"'{join_id}' receives arrows from parallel branches of "
                            f"'{split_candidate}' mixed with other paths; merge each branch "
                            "into one node before joining"
                        ),
                        node_ids=(join_id, split_candidate),
                        arrow_ids=arrow_ids,
                    )
                )
            break
        if split_id is not None:
            closed_splits[split_id] = join_id
        joins.append(
            JoinInfo(
                node_id=join_id,
                join_type="and" if verdict == "and" else "xor",
                arrow_ids=arrow_ids,
                split_node_id=split_id,
            )
        )
    return tuple(joins), closed_splits


def _analyze_regions(
    graph: _GraphIndex,
    splits: dict[str, list[CompiledArrow]],
    and_joins: dict[str, str],
    facts: list[UnresolvedFact],
) -> tuple[Region, ...]:
    regions = []
    for split_id, join_id in and_joins.items():
        region: set[str] = set()
        queue = deque(a.target for a in splits[split_id])
        while queue:
            node_id = queue.popleft()
            if node_id in (join_id, split_id) or node_id in region:
                continue
            region.add(node_id)
            queue.extend(a.target for a in graph.structural_out[node_id])
        allowed_sources = region | {split_id}
        problems = []
        for node_id in graph.sorted_ids(region):
            if not graph.structural_out[node_id]:
                problems.append(f"'{node_id}' ends inside the region without reaching '{join_id}'")
            for arrow in graph.structural_in[node_id]:
                if arrow.source not in allowed_sources:
                    problems.append(
                        f"arrow '{arrow.id}' enters the region at '{node_id}' from outside"
                    )
        for arrow in graph.structural_in[join_id]:
            if arrow.source not in allowed_sources:
                problems.append(f"arrow '{arrow.id}' reaches '{join_id}' from outside the region")
        if problems:
            facts.append(
                UnresolvedFact(
                    code="region_not_closed",
                    message=(
                        f"parallel branches from '{split_id}' do not all meet at '{join_id}': "
                        + "; ".join(problems)
                        + ". Every path from the split must reach the join and nothing else may "
                        "enter the branches."
                    ),
                    node_ids=(split_id, join_id),
                )
            )
        else:
            regions.append(
                Region(
                    split_node_id=split_id, join_node_id=join_id, node_ids=graph.sorted_ids(region)
                )
            )
    return tuple(regions)


def _label_sets(graph: _GraphIndex) -> tuple[LabelSet, ...]:
    label_sets = []
    for node_id in sorted(graph.nodes_by_id, key=graph.order.__getitem__):  # type: ignore[arg-type]
        outgoing = [
            a for a in graph.arrows if a.source == node_id and a.kind in ("forward", "back")
        ]
        if not outgoing:
            continue
        label_sets.append(
            LabelSet(
                node_id=node_id,
                labels=tuple(a.label for a in outgoing if a.label is not None),
                labelled_arrow_ids=tuple(a.id for a in outgoing if a.label is not None),
                unlabelled_arrow_ids=tuple(a.id for a in outgoing if a.label is None),
            )
        )
    return tuple(label_sets)


def _checked_parts(graph: _GraphIndex) -> tuple[CheckedPart, ...]:
    checked = []
    for node_id, node in graph.nodes_by_id.items():
        if node.list_from is None:
            continue
        source_id, _, part_name = node.list_from.partition(".")
        source = graph.nodes_by_id.get(source_id)
        upstream = _bfs(node_id, lambda n: (a.source for a in graph.non_back_in[n]))
        checked.append(
            CheckedPart(
                node_id=node_id,
                reference=node.list_from,
                source_node_id=source_id or None,
                part_name=part_name or None,
                source_exists=source is not None,
                source_upstream=source is not None
                and source_id != node_id
                and source_id in upstream,
                part_is_list=source is not None
                and any(p.name == part_name and p.kind == "list" for p in source.parts),
            )
        )
    return tuple(checked)


def analyze(nodes: tuple[CompiledNode, ...], arrows: tuple[CompiledArrow, ...]) -> Analysis:
    """Compute the derived facts validators rely on."""
    graph = _GraphIndex(nodes, arrows)
    facts: list[UnresolvedFact] = []
    for arrow in graph.dangling:
        facts.append(
            UnresolvedFact(
                code="dangling_arrow",
                message=(
                    f"arrow '{arrow.id}' connects '{arrow.source}' to '{arrow.target}', "
                    "but one of them is not a node; fix the id"
                ),
                arrow_ids=(arrow.id,),
            )
        )
    for component in _cyclic_components(graph):
        facts.append(
            UnresolvedFact(
                code="cycle_without_back_arrow",
                message=(
                    f"nodes {', '.join(repr(n) for n in component)} form a cycle with no back "
                    "arrow; mark the arrow that closes the loop with back: true"
                ),
                node_ids=component,
            )
        )
    loops = _analyze_loops(graph, facts)
    joins, and_joins = _analyze_joins(graph, facts)
    regions = _analyze_regions(graph, _parallel_splits(graph), and_joins, facts)
    for split_id in _parallel_splits(graph):
        if split_id not in and_joins:
            facts.append(
                UnresolvedFact(
                    code="split_without_join",
                    message=(
                        f"'{split_id}' starts parallel branches that never meet; join them in one "
                        "node, or add labels to make the arrows alternatives"
                    ),
                    node_ids=(split_id,),
                )
            )
    # Repeat fan-out needs SES-10's structure.start_item executors. Parallel
    # AND-joins already run in the pure engine; cancel_region effects land later.
    needs_structure = any(node.list_from is not None for node in nodes)
    return Analysis(
        join_types=joins,
        loops=loops,
        regions=regions,
        unresolved=tuple(facts),
        label_sets=_label_sets(graph),
        checked_parts=_checked_parts(graph),
        requires_structure_runtime=needs_structure,
    )
