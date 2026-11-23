"""Loop counters, join arrivals, failure routing, and join liveness.

``traverse_arrow`` delegates here so a decision, a gate answer, and a finished
step share one arrival rule. Choosing a label stays in the decision and gate
machines.
"""

from __future__ import annotations

from typing import NamedTuple

from pydantic import JsonValue

from coral.engine.machines.run import record_pause
from coral.engine.types import (
    Arrival,
    Effect,
    LoopCounter,
    Receipt,
    RunState,
    loop_limit_key,
)
from coral.model.ir import CompiledArrow, CompiledGraph, CompiledNode, JoinInfo, LoopInfo

_STRUCTURAL = frozenset({"forward", "at_limit"})


class Traversal(NamedTuple):
    """One arrow walk: the next state, effects it opened, and a receipt key."""

    state: RunState
    effects: tuple[Effect, ...] = ()
    receipt_key: str | None = None


def prepare_loop_head(
    state: RunState,
    graph: CompiledGraph,
    node: CompiledNode,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> tuple[RunState, tuple[str, ...], tuple[str, ...]]:
    """Create pass 1 when this head's counter is missing. Never lower a later pass.

    An entry whose path does not already name this loop adopts the current index,
    so a second input of a loop-head join uses the same iteration path as the first.
    """
    loop = _loop_for_head(graph, node.id)
    if loop is None:
        return state, item_path, iteration_path
    prefix = f"{loop.back_arrow_id}:"
    enclosing = _strip(iteration_path, loop.back_arrow_id)
    named = next((part for part in iteration_path if part.startswith(prefix)), None)
    current = _find_counter(state, loop.back_arrow_id, item_path, enclosing)
    if named is not None:
        if current is not None:
            return state, item_path, iteration_path
        index = _pass_number(named)
        updated = _set_counter(state, loop.back_arrow_id, item_path, enclosing, index)
        return updated, item_path, iteration_path
    if current is not None:
        return state, item_path, (*enclosing, f"{loop.back_arrow_id}:{current.pass_index}")
    updated = _set_counter(state, loop.back_arrow_id, item_path, enclosing, 1)
    return updated, item_path, (*enclosing, f"{loop.back_arrow_id}:1")


def failure_arrow(graph: CompiledGraph, node_id: str) -> CompiledArrow | None:
    """The node's failure arrow, if it has one."""
    for arrow in graph.arrows:
        if arrow.source == node_id and arrow.kind == "failure":
            return arrow
    return None


def note_skipped(
    state: RunState,
    graph: CompiledGraph,
    node_id: str,
    owner_id: str,
    taken_ids: frozenset[str],
) -> RunState:
    """Log each labelled arrow this choice did not take. Those arrows do not arrive."""
    updated = state
    for arrow in graph.arrows:
        if arrow.source != node_id or arrow.id in taken_ids or arrow.label is None:
            continue
        if arrow.kind == "failure":
            continue
        key = f"skipped:{owner_id}:{arrow.id}"
        updated = _add_receipt(updated, key, {"code": "arrow.skipped", "arrow_id": arrow.id})
    return updated


def traverse(
    state: RunState,
    graph: CompiledGraph,
    arrow: CompiledArrow,
    *,
    item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
) -> Traversal:
    """Apply the loop, join, or direct-open rule for one arrow."""
    if state.status != "running":
        return Traversal(state)
    if arrow.kind == "failure":
        path = _exit_path(graph, arrow, iteration_path)
        return _open_target(state, graph, arrow, item_path, path)
    if arrow.kind == "back":
        return _take_back(state, graph, arrow, item_path, iteration_path)
    return _join_or_open(state, graph, arrow, item_path, _exit_path(graph, arrow, iteration_path))


def check_liveness(state: RunState, graph: CompiledGraph) -> RunState:
    """Pause when a waiting AND join has a predecessor that can no longer arrive."""
    if state.status != "running":
        return state
    joins = {item.node_id: item for item in graph.analysis.join_types if item.join_type == "and"}
    arrows = {arrow.id: arrow for arrow in graph.arrows}
    for activation in state.activations:
        if activation.status != "waiting_join":
            continue
        join = joins.get(activation.node_id)
        if join is None:
            continue
        arrived = _arrived_ids(state, activation.item_path, activation.iteration_path)
        for arrow_id in join.arrow_ids:
            if arrow_id in arrived:
                continue
            arrow = arrows.get(arrow_id)
            if arrow is None or _source_can_fire(
                state,
                graph,
                arrow.source,
                activation.item_path,
                activation.iteration_path,
            ):
                continue
            detail = (
                f"{activation.node_id} is waiting for {arrow.source}, which can no longer run."
            )
            return record_pause(state, "liveness", detail, arrow.source)
    return state


def _take_back(
    state: RunState,
    graph: CompiledGraph,
    arrow: CompiledArrow,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> Traversal:
    loop = _loop_for_back(graph, arrow.id)
    limit = loop.limit if loop is not None else arrow.limit
    at_limit_id = loop.at_limit_arrow_id if loop is not None else arrow.at_limit
    enclosing = _strip(iteration_path, arrow.id)
    current = _find_counter(state, arrow.id, item_path, enclosing)
    pass_index = 1 if current is None else current.pass_index
    if limit is not None and pass_index + 1 > limit:
        return _redirect(state, graph, arrow, item_path, enclosing, at_limit_id)
    nxt = pass_index + 1
    updated = _set_counter(state, arrow.id, item_path, enclosing, nxt)
    return _open_target(
        updated,
        graph,
        arrow,
        item_path,
        (*enclosing, f"{arrow.id}:{nxt}"),
    )


def _redirect(
    state: RunState,
    graph: CompiledGraph,
    arrow: CompiledArrow,
    item_path: tuple[str, ...],
    enclosing: tuple[str, ...],
    at_limit_id: str | None,
) -> Traversal:
    """Arrive on the at-limit arrow. The pass counter stays where it is."""
    source = _node(graph, arrow.source)
    payload: dict[str, JsonValue] = {"code": "loop.limit_reached", "redirected": True}
    if source is not None and source.kind in {"decision", "gate"}:
        payload["decision.made"] = True
    key = loop_limit_key(arrow.id, item_path, enclosing)
    updated = _add_receipt(state, key, payload)
    limit_arrow = _arrow(graph, at_limit_id) if at_limit_id is not None else None
    if limit_arrow is None:
        return Traversal(check_liveness(updated, graph), (), key)
    opened = _join_or_open(
        updated,
        graph,
        limit_arrow,
        item_path,
        _exit_path(graph, limit_arrow, enclosing),
    )
    return Traversal(opened.state, opened.effects, key)


def _join_or_open(
    state: RunState,
    graph: CompiledGraph,
    arrow: CompiledArrow,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> Traversal:
    target = _node(graph, arrow.target)
    if target is not None:
        state, item_path, iteration_path = prepare_loop_head(
            state, graph, target, item_path, iteration_path
        )
    join = _join_for(graph, arrow.target)
    if join is None or arrow.id not in join.arrow_ids:
        return _open_target(state, graph, arrow, item_path, iteration_path)
    existing = _find_arrival(state, item_path, iteration_path, arrow.id)
    if existing is not None:
        return Traversal(state, (), existing.receipt_key)
    key = f"arrival:{arrow.id}|{'/'.join(item_path)}|{'/'.join(iteration_path)}"
    prior = _scope_arrivals(state, join, item_path, iteration_path)
    payload: dict[str, JsonValue] = {"arrow_id": arrow.id}
    if join.join_type == "xor" and prior:
        payload["code"] = "arrow.logged"
    updated = _add_receipt(state, key, payload)
    updated = updated.model_copy(
        update={
            "arrivals": (
                *updated.arrivals,
                Arrival(
                    item_path=item_path,
                    iteration_path=iteration_path,
                    arrow_id=arrow.id,
                    receipt_key=key,
                ),
            )
        }
    )
    if join.join_type == "xor" and prior:
        return Traversal(check_liveness(updated, graph), (), key)
    if join.join_type == "and" and not _and_satisfied(updated, join, item_path, iteration_path):
        waiting = _ensure_waiting(updated, graph, arrow.target, item_path, iteration_path)
        return Traversal(check_liveness(waiting, graph), (), key)
    return _open_target(updated, graph, arrow, item_path, iteration_path)


def _open_target(
    state: RunState,
    graph: CompiledGraph,
    arrow: CompiledArrow,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> Traversal:
    from coral.engine.machines.activation import open_node

    opened, effects = open_node(
        state, graph, arrow.target, item_path=item_path, iteration_path=iteration_path
    )
    return Traversal(check_liveness(opened, graph), effects, None)


def _source_can_fire(
    state: RunState,
    graph: CompiledGraph,
    source_id: str,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> bool:
    """True when this predecessor can still produce its join arrow in this scope.

    A closed activation from another pass is not "started" here, so it does not
    hide a predecessor this pass can still reach.
    """
    started = [
        item
        for item in state.activations
        if item.node_id == source_id
        and item.item_path == item_path
        and item.iteration_path == iteration_path
    ]
    if any(item.status != "closed" for item in started):
        return True
    if started:
        return False
    return any(
        item.status != "closed" and _reaches(graph, item.node_id, source_id)
        for item in state.activations
    )


def _reaches(graph: CompiledGraph, origin: str, target: str) -> bool:
    """Structural reachability, counting a node as reaching itself."""
    seen: set[str] = set()
    queue = [origin]
    while queue:
        node_id = queue.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        if node_id == target:
            return True
        queue.extend(
            arrow.target
            for arrow in graph.arrows
            if arrow.source == node_id and arrow.kind in _STRUCTURAL
        )
    return False


def _exit_path(
    graph: CompiledGraph, arrow: CompiledArrow, iteration_path: tuple[str, ...]
) -> tuple[str, ...]:
    """Drop a loop component when the arrow leaves that loop's body."""
    path = iteration_path
    for loop in graph.analysis.loops:
        body = set(loop.body)
        if arrow.source in body and arrow.target not in body:
            path = _strip(path, loop.back_arrow_id)
    return path


def _ensure_waiting(
    state: RunState,
    graph: CompiledGraph,
    node_id: str,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> RunState:
    from coral.engine.types import Activation, activation_id

    node = _node(graph, node_id)
    if node is None:
        return state
    owner_id = activation_id(node.id, item_path, iteration_path)
    if any(item.id == owner_id for item in state.activations):
        return state
    from coral.engine.machines.activation import _cap_pause

    paused = _cap_pause(state, node.id, item_path, iteration_path, waiting=True)
    if paused is not None:
        return paused
    waiting = Activation(
        id=owner_id,
        node_id=node.id,
        item_path=item_path,
        iteration_path=iteration_path,
        status="waiting_join",
    )
    return state.model_copy(update={"activations": (*state.activations, waiting)})


def _and_satisfied(
    state: RunState,
    join: JoinInfo,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> bool:
    arrived = _arrived_ids(state, item_path, iteration_path)
    return all(arrow_id in arrived for arrow_id in join.arrow_ids)


def _scope_arrivals(
    state: RunState,
    join: JoinInfo,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> tuple[Arrival, ...]:
    wanted = set(join.arrow_ids)
    return tuple(
        item
        for item in state.arrivals
        if item.item_path == item_path
        and item.iteration_path == iteration_path
        and item.arrow_id in wanted
    )


def _arrived_ids(
    state: RunState, item_path: tuple[str, ...], iteration_path: tuple[str, ...]
) -> set[str]:
    return {
        item.arrow_id
        for item in state.arrivals
        if item.item_path == item_path and item.iteration_path == iteration_path
    }


def _find_arrival(
    state: RunState,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
    arrow_id: str,
) -> Arrival | None:
    for item in state.arrivals:
        if (
            item.arrow_id == arrow_id
            and item.item_path == item_path
            and item.iteration_path == iteration_path
        ):
            return item
    return None


def _join_for(graph: CompiledGraph, node_id: str) -> JoinInfo | None:
    for join in graph.analysis.join_types:
        if join.node_id == node_id:
            return join
    return None


def _loop_for_head(graph: CompiledGraph, node_id: str) -> LoopInfo | None:
    for loop in graph.analysis.loops:
        if loop.head == node_id:
            return loop
    return None


def _loop_for_back(graph: CompiledGraph, arrow_id: str) -> LoopInfo | None:
    for loop in graph.analysis.loops:
        if loop.back_arrow_id == arrow_id:
            return loop
    return None


def _find_counter(
    state: RunState,
    back_arrow_id: str,
    item_path: tuple[str, ...],
    enclosing: tuple[str, ...],
) -> LoopCounter | None:
    for item in state.loop_counters:
        if (
            item.back_arrow_id == back_arrow_id
            and item.item_path == item_path
            and item.iteration_path == enclosing
        ):
            return item
    return None


def _set_counter(
    state: RunState,
    back_arrow_id: str,
    item_path: tuple[str, ...],
    enclosing: tuple[str, ...],
    pass_index: int,
) -> RunState:
    row = LoopCounter(
        back_arrow_id=back_arrow_id,
        item_path=item_path,
        iteration_path=enclosing,
        pass_index=pass_index,
    )
    rows: list[LoopCounter] = []
    found = False
    for item in state.loop_counters:
        if (
            item.back_arrow_id == back_arrow_id
            and item.item_path == item_path
            and item.iteration_path == enclosing
        ):
            rows.append(row)
            found = True
        else:
            rows.append(item)
    if not found:
        rows.append(row)
    return state.model_copy(update={"loop_counters": tuple(rows)})


def _add_receipt(state: RunState, key: str, payload: dict[str, JsonValue]) -> RunState:
    if any(item.key == key for item in state.receipts):
        return state
    receipt = Receipt(key=key, payload=payload)
    return state.model_copy(update={"receipts": (*state.receipts, receipt)})


def _strip(iteration_path: tuple[str, ...], back_arrow_id: str) -> tuple[str, ...]:
    prefix = f"{back_arrow_id}:"
    return tuple(part for part in iteration_path if not part.startswith(prefix))


def _pass_number(component: str) -> int:
    _, _, raw = component.rpartition(":")
    if raw.isdigit():
        return int(raw)
    return 1


def _node(graph: CompiledGraph, node_id: str) -> CompiledNode | None:
    for node in graph.nodes:
        if node.id == node_id:
            return node
    return None


def _arrow(graph: CompiledGraph, arrow_id: str) -> CompiledArrow | None:
    for arrow in graph.arrows:
        if arrow.id == arrow_id:
            return arrow
    return None
