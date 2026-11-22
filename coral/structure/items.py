"""SES-10 structure.start_item: open one repeat item's activation."""

from __future__ import annotations

from coral.engine.machines.activation import open_node
from coral.engine.repeat import START_ITEM
from coral.engine.types import ApplyResult, Effect, RunState, activation_id, effect_key
from coral.model.ir import CompiledGraph

__all__ = ["START_ITEM", "apply_start_item", "plan_next_start"]


def apply_start_item(
    graph: CompiledGraph,
    state: RunState,
    effect: Effect,
) -> ApplyResult:
    """Open the item activation named by a ``structure.start_item`` effect payload."""
    if effect.kind != START_ITEM:
        return ApplyResult(state=state)
    node_id = effect.payload.get("node_id")
    raw_path = effect.payload.get("item_path")
    raw_iter = effect.payload.get("iteration_path")
    if not isinstance(node_id, str) or not isinstance(raw_path, list):
        return ApplyResult(state=state)
    item_path = tuple(str(part) for part in raw_path)
    iteration_path = tuple(str(part) for part in raw_iter) if isinstance(raw_iter, list) else ()
    opened, effects = open_node(
        state, graph, node_id, item_path=item_path, iteration_path=iteration_path
    )
    return ApplyResult(state=opened, effects=effects, receipt_key=effect.effect_key)


def plan_next_start(
    *,
    run_id: str,
    seq: int,
    node_id: str,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...] = (),
) -> Effect:
    """Build one deferred ``structure.start_item`` after a concurrency slot frees."""
    subject_id = activation_id(node_id, item_path, iteration_path)
    return Effect(
        effect_key=effect_key(run_id, seq, START_ITEM, subject_id),
        kind=START_ITEM,
        subject=subject_id,
        payload={
            "node_id": node_id,
            "item_path": list(item_path),
            "iteration_path": list(iteration_path),
            "item_id": item_path[-1] if item_path else "0",
        },
    )
