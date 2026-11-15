"""V13: ids are unique, and removed ids that look renamed are called out."""

from __future__ import annotations

from collections.abc import Iterable

from coral.model.sourcemap import arrow_path, node_path
from coral.validate.problems import Problem
from coral.validate.registry import RuleInput, register_rule


@register_rule("V13")
def check_ids(inp: RuleInput) -> Iterable[Problem]:
    graph = inp.graph
    seen_nodes: set[str] = set()
    for index, node in enumerate(graph.nodes):
        if node.id in seen_nodes:
            yield inp.problem(
                "V13",
                f"Node id '{node.id}' is used more than once. Give each node a unique id.",
                node_ids=(node.id,),
                yaml_path=f"{node_path(index)}.id",
            )
        seen_nodes.add(node.id)
    seen_arrows: set[str] = set()
    for index, arrow in enumerate(graph.arrows):
        if arrow.id in seen_arrows:
            yield inp.problem(
                "V13",
                f"Arrow id '{arrow.id}' is used more than once. Give each arrow a unique id.",
                arrow_ids=(arrow.id,),
                yaml_path=f"{arrow_path(index)}.id",
            )
        seen_arrows.add(arrow.id)
    previous = inp.ctx.previous
    if previous is None:
        return
    current_ids = {node.id for node in graph.nodes}
    previous_ids = {node.id for node in previous.nodes}
    added = [node for node in graph.nodes if node.id not in previous_ids]
    for old in previous.nodes:
        if old.id in current_ids:
            continue
        for new in added:
            if new.kind == old.kind and (
                (old.name is not None and new.name == old.name)
                or (old.goal is not None and new.goal == old.goal)
            ):
                yield inp.problem(
                    "V13",
                    f"Node '{old.id}' is gone and '{new.id}' looks like its replacement. "
                    f"If it was renamed, keep the id '{old.id}' so run history stays attached.",
                    severity="info",
                    node_ids=(new.id,),
                )
                break
