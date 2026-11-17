"""Open a decision and choose one of its labelled arrows."""

from __future__ import annotations

from pydantic import JsonValue

from coral.engine.types import (
    TERMINAL_STATUSES,
    ApplyResult,
    ChooseArrow,
    Decision,
    Effect,
    Receipt,
    RunState,
    activation_id,
)
from coral.model.ir import CompiledGraph, CompiledNode


def open_decision(
    state: RunState,
    node: CompiledNode,
    *,
    item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
) -> tuple[RunState, tuple[Effect, ...]]:
    """Record a requested decision. The activation is already running."""
    owner_id = activation_id(node.id, item_path, iteration_path)
    requested = Decision(activation_id=owner_id, node_id=node.id, status="requested")
    found = False
    rows: list[Decision] = []
    for item in state.decisions:
        if item.activation_id == owner_id:
            rows.append(requested)
            found = True
        else:
            rows.append(item)
    if not found:
        rows.append(requested)
    return state.model_copy(update={"decisions": tuple(rows)}), ()


def choose_arrow(graph: CompiledGraph, state: RunState, command: ChooseArrow) -> ApplyResult:
    """Mark the open decision decided and open the chosen arrow's target."""
    from coral.engine.machines.activation import (
        choosable_labels,
        find_activation,
        find_node,
        replace_activation,
    )
    from coral.engine.machines.run import refuse, refuse_unknown

    owner_id = activation_id(command.node_id, command.item_path, command.iteration_path)
    choice_key = f"choice:{owner_id}:{command.label}"
    if _has_receipt(state, choice_key):
        return ApplyResult(state=state, receipt_key=choice_key)
    if _is_decided(state, owner_id):
        return refuse(state, "decision_closed")
    node = find_node(graph, command.node_id)
    owner = find_activation(state, owner_id)
    decision = _open_decision(state, owner_id)
    if (
        node is None
        or node.kind != "decision"
        or owner is None
        or owner.status == "closed"
        or decision is None
    ):
        if state.status in TERMINAL_STATUSES:
            return refuse(state, "run_terminal")
        return refuse_unknown(state)
    if state.status != "running":
        return refuse(state, "run_paused")
    labels = choosable_labels(graph, node.id)
    if command.label not in labels or not command.reason:
        return refuse(state, "tool.illegal", labels)
    decided = tuple(
        item.model_copy(
            update={"status": "decided", "label": command.label, "reason": command.reason}
        )
        if item.activation_id == owner_id
        else item
        for item in state.decisions
    )
    closed = replace_activation(state, owner_id, status="closed", outcome="completed")
    closed = closed.model_copy(update={"seq": state.seq + 1, "decisions": decided})
    opened, effects, redirected = take_labelled_arrow(
        closed,
        graph,
        node_id=node.id,
        owner_id=owner_id,
        label=command.label,
        item_path=command.item_path,
        iteration_path=command.iteration_path,
    )
    payload: dict[str, JsonValue] = {
        "label": command.label,
        "reason": command.reason,
        "code": "loop.limit_reached" if redirected else "decision.made",
    }
    if redirected:
        payload["redirected"] = True
        payload["decision.made"] = True
    receipt = Receipt(key=choice_key, payload=payload)
    opened = opened.model_copy(update={"receipts": (*opened.receipts, receipt)})
    return ApplyResult(state=opened, effects=effects, receipt_key=choice_key)


def take_labelled_arrow(
    state: RunState,
    graph: CompiledGraph,
    *,
    node_id: str,
    owner_id: str,
    label: str,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> tuple[RunState, tuple[Effect, ...], bool]:
    """Walk the arrow ``label`` names and log the labelled arrows not taken.

    ``label`` must be one of ``choosable_labels``. Returns whether a loop limit
    redirected the walk onto its at-limit arrow.
    """
    from coral.engine.control import note_skipped
    from coral.engine.machines.activation import arrow_by_label, traverse_arrow

    arrow = arrow_by_label(graph, node_id, label)
    if arrow is None:
        return state, (), False
    opened, effects, walked = traverse_arrow(
        state,
        graph,
        arrow,
        item_path=item_path,
        iteration_path=iteration_path,
    )
    redirected = _receipt_redirected(opened, walked)
    taken = {arrow.id}
    if redirected:
        limit_id = _at_limit_id(graph, arrow.id)
        if limit_id is not None:
            taken.add(limit_id)
    opened = note_skipped(opened, graph, node_id, owner_id, frozenset(taken))
    return opened, effects, redirected


def _open_decision(state: RunState, owner_id: str) -> Decision | None:
    for item in state.decisions:
        if item.activation_id == owner_id and item.status != "decided":
            return item
    return None


def _is_decided(state: RunState, owner_id: str) -> bool:
    return any(
        item.activation_id == owner_id and item.status == "decided" for item in state.decisions
    )


def _has_receipt(state: RunState, key: str) -> bool:
    return any(item.key == key for item in state.receipts)


def _receipt_redirected(state: RunState, key: str | None) -> bool:
    if key is None:
        return False
    for item in state.receipts:
        if item.key == key and item.payload.get("redirected") is True:
            return True
    return False


def _at_limit_id(graph: CompiledGraph, arrow_id: str) -> str | None:
    for loop in graph.analysis.loops:
        if loop.back_arrow_id == arrow_id:
            return loop.at_limit_arrow_id
    for arrow in graph.arrows:
        if arrow.id == arrow_id:
            return arrow.at_limit
    return None
