"""Publish a gate visit and resolve it with an answer."""

from __future__ import annotations

from coral.engine.types import (
    TERMINAL_STATUSES,
    AnswerGate,
    ApplyResult,
    Effect,
    GateVisit,
    Receipt,
    RunState,
    activation_id,
    effect_key,
)
from coral.model.ir import CompiledGraph, CompiledNode


def open_gate(
    state: RunState,
    node: CompiledNode,
    *,
    item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
) -> tuple[RunState, tuple[Effect, ...]]:
    """Publish the next visit. A previous visit of this activation is withdrawn."""
    run_id = state.run_id
    if not isinstance(run_id, str):
        return state, ()
    owner_id = activation_id(node.id, item_path, iteration_path)
    visits: list[GateVisit] = []
    previous: list[str] = []
    for visit in state.gates:
        # A later pass of this gate has a new activation id. Supersede the visit it replaces.
        if _same_gate(visit.activation_id, node.id) and visit.status != "superseded":
            visits.append(visit.model_copy(update={"status": "superseded"}))
            previous.append(visit.token)
        else:
            visits.append(visit)
    visit_no = 1 + max(
        (visit.visit_no for visit in visits if _same_gate(visit.activation_id, node.id)),
        default=0,
    )
    token = f"{owner_id}:{visit_no}"
    visits.append(GateVisit(activation_id=owner_id, token=token, visit_no=visit_no, status="open"))
    effects = (
        *(_withdraw(run_id, state.seq, old) for old in previous),
        _publish(run_id, state.seq, token, node.id, owner_id, visit_no),
    )
    updated = state.model_copy(
        update={
            "gates": tuple(visits),
            "effects": (*state.effects, *effects),
        }
    )
    return updated, effects


def answer_gate(graph: CompiledGraph, state: RunState, command: AnswerGate) -> ApplyResult:
    """Resolve the open visit, or return the earlier receipt for the same answer."""
    from coral.engine.control import note_skipped
    from coral.engine.machines.activation import (
        arrow_by_label,
        choosable_labels,
        find_activation,
        find_node,
        replace_activation,
        traverse_arrow,
    )
    from coral.engine.machines.run import refuse, refuse_unknown

    visit = _visit(state, command.token)
    if visit is None:
        if state.status in TERMINAL_STATUSES:
            return refuse(state, "run_terminal")
        return refuse_unknown(state)
    if visit.status == "superseded":
        return refuse(state, "gate.stale")
    if visit.status == "resolved" and visit.label == command.label:
        return ApplyResult(state=state, receipt_key=visit.token)
    if state.status == "paused":
        return refuse(state, "run_paused")
    if state.status in TERMINAL_STATUSES:
        return refuse(state, "run_terminal")
    if visit.status != "open":
        return refuse_unknown(state)
    owner = find_activation(state, visit.activation_id)
    node = find_node(graph, owner.node_id) if owner is not None else None
    if owner is None or node is None:
        return refuse_unknown(state)
    labels = node.outcomes if node.outcomes else choosable_labels(graph, node.id)
    if command.label not in labels:
        return refuse(state, "tool.illegal", labels)
    arrow = arrow_by_label(graph, node.id, command.label)
    if arrow is None:
        return refuse(state, "tool.illegal", labels)
    receipt = Receipt(
        key=visit.token,
        payload={"label": command.label, "by": command.by, "note": command.note},
    )
    resolved = tuple(
        item.model_copy(
            update={
                "status": "resolved",
                "label": command.label,
                "by": command.by,
                "note": command.note,
            }
        )
        if item.token == visit.token
        else item
        for item in state.gates
    )
    closed = replace_activation(state, owner.id, status="closed", outcome="completed")
    closed = closed.model_copy(
        update={
            "seq": state.seq + 1,
            "gates": resolved,
            "receipts": (*closed.receipts, receipt),
        }
    )
    opened, effects, walked = traverse_arrow(
        closed,
        graph,
        arrow,
        item_path=owner.item_path,
        iteration_path=owner.iteration_path,
    )
    taken = {arrow.id}
    if walked is not None and any(
        item.key == walked and item.payload.get("redirected") is True for item in opened.receipts
    ):
        for loop in graph.analysis.loops:
            if loop.back_arrow_id == arrow.id and loop.at_limit_arrow_id is not None:
                taken.add(loop.at_limit_arrow_id)
    opened = note_skipped(opened, graph, node.id, owner.id, frozenset(taken))
    return ApplyResult(state=opened, effects=effects, receipt_key=receipt.key)


def _same_gate(activation_id: str, node_id: str) -> bool:
    return activation_id.split("|", 1)[0] == node_id


def _visit(state: RunState, token: str) -> GateVisit | None:
    for visit in state.gates:
        if visit.token == token:
            return visit
    return None


def _withdraw(run_id: str, seq: int, token: str) -> Effect:
    return Effect(
        effect_key=effect_key(run_id, seq, "withdraw_gate", token),
        kind="withdraw_gate",
        subject=token,
        payload={"token": token},
    )


def _publish(
    run_id: str, seq: int, token: str, node_id: str, owner_id: str, visit_no: int
) -> Effect:
    return Effect(
        effect_key=effect_key(run_id, seq, "publish_gate", token),
        kind="publish_gate",
        subject=token,
        payload={
            "token": token,
            "node_id": node_id,
            "activation_id": owner_id,
            "visit_no": visit_no,
        },
    )
