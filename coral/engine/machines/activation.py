"""Open an activation and advance along its outgoing arrows."""

from __future__ import annotations

from coral.engine.machines.decision import open_decision, take_labelled_arrow
from coral.engine.machines.gate import open_gate
from coral.engine.types import (
    Activation,
    ActivationOutcome,
    ActivationStatus,
    Effect,
    Receipt,
    RunState,
    Slot,
    SlotHandoff,
    activation_id,
    effect_key,
    slot_id,
)
from coral.model.ir import CompiledArrow, CompiledGraph, CompiledNode


def open_node(
    state: RunState,
    graph: CompiledGraph,
    node_id: str,
    *,
    item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
) -> tuple[RunState, tuple[Effect, ...]]:
    """Open ``node_id`` at one scope. A start node closes and advances in the same call."""
    node = find_node(graph, node_id)
    run_id = state.run_id
    if node is None or not isinstance(run_id, str) or state.status != "running":
        return state, ()
    from coral.engine.control import prepare_loop_head

    state, item_path, iteration_path = prepare_loop_head(
        state, graph, node, item_path, iteration_path
    )
    if node.kind == "end":
        activated, installed = _install(
            state,
            _activation(
                node,
                status="closed",
                outcome="completed",
                item_path=item_path,
                iteration_path=iteration_path,
            ),
        )
        if not installed:
            return activated, ()
        return activated.model_copy(update={"status": "completed"}), ()
    if node.kind == "step" and node.roster:
        owner = _activation(
            node, status="starting", item_path=item_path, iteration_path=iteration_path
        )
        opened, installed = _install(state, owner)
        if not installed:
            return opened, ()
        slots = tuple(
            Slot(
                id=slot_id(owner.id, index),
                activation_id=owner.id,
                profile=profile,
                status="pending",
            )
            for index, profile in enumerate(node.roster)
            if not any(slot.id == slot_id(owner.id, index) for slot in opened.slots)
        )
        effects = tuple(_create_session(run_id, opened.seq, slot, node) for slot in slots)
        opened = opened.model_copy(
            update={
                "slots": (*opened.slots, *slots),
                "effects": (*opened.effects, *effects),
            }
        )
        return opened, effects
    if node.kind == "decision":
        # No roster: stay requested until ChooseArrow. Do not auto-advance.
        placed = _place_running(state, node, item_path, iteration_path)
        if not _is_running(placed, node, item_path, iteration_path):
            return placed, ()
        return open_decision(placed, node, item_path=item_path, iteration_path=iteration_path)
    if node.kind == "gate":
        # No roster: stay open until AnswerGate. A revisit supersedes the prior visit.
        placed = _place_running(state, node, item_path, iteration_path)
        if not _is_running(placed, node, item_path, iteration_path):
            return placed, ()
        return open_gate(placed, node, item_path=item_path, iteration_path=iteration_path)
    if node.kind in {"start", "step"}:
        closed, installed = _install(
            state,
            _activation(
                node,
                status="closed",
                outcome="completed",
                item_path=item_path,
                iteration_path=iteration_path,
            ),
        )
        if not installed:
            return closed, ()
        return advance(closed, graph, node.id, item_path=item_path, iteration_path=iteration_path)
    return state, ()


def advance(
    state: RunState,
    graph: CompiledGraph,
    node_id: str,
    *,
    item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
) -> tuple[RunState, tuple[Effect, ...]]:
    """Open every unlabelled forward successor. A non-decision tail also takes its back arrow."""
    if state.status != "running":
        return state, ()
    effects: list[Effect] = []
    for arrow in graph.arrows:
        if arrow.source != node_id or arrow.kind != "forward" or arrow.label is not None:
            continue
        state, spawned, _ = traverse_arrow(
            state, graph, arrow, item_path=item_path, iteration_path=iteration_path
        )
        effects.extend(spawned)
        if state.status != "running":
            return state, tuple(effects)
    node = find_node(graph, node_id)
    if node is not None and node.kind not in {"decision", "gate"}:
        for arrow in graph.arrows:
            if arrow.source != node_id or arrow.kind != "back":
                continue
            state, spawned, _ = traverse_arrow(
                state, graph, arrow, item_path=item_path, iteration_path=iteration_path
            )
            effects.extend(spawned)
            if state.status != "running":
                break
    return state, tuple(effects)


def traverse_arrow(
    state: RunState,
    graph: CompiledGraph,
    arrow: CompiledArrow,
    *,
    item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
) -> tuple[RunState, tuple[Effect, ...], str | None]:
    """Walk one arrow through the loop, join, and failure rules."""
    from coral.engine.control import traverse

    walked = traverse(state, graph, arrow, item_path=item_path, iteration_path=iteration_path)
    return walked.state, walked.effects, walked.receipt_key


def finish_activation(
    state: RunState, graph: CompiledGraph, owner_id: str
) -> tuple[RunState, tuple[Effect, ...]]:
    """Close an activation whose slots are done and open its successor.

    A step routed by label follows the label its handoff chose. Other nodes advance.
    """
    owner = find_activation(state, owner_id)
    if owner is None or owner.status == "closed" or owner.outcome == "failed":
        return state, ()
    handed = tuple(
        SlotHandoff(slot_id=slot.id, profile=slot.profile, handoff=slot.handoff)
        for slot in state.slots
        if slot.activation_id == owner_id
    )
    closed = replace_activation(
        state, owner_id, status="closed", outcome="completed", handoffs=handed
    )
    if closed.status != "running":
        return closed, ()
    if routes_by_label(graph, owner.node_id):
        advanced, effects = _take_handoff_label(closed, graph, owner)
    else:
        advanced, effects = advance(
            closed,
            graph,
            owner.node_id,
            item_path=owner.item_path,
            iteration_path=owner.iteration_path,
        )
    from coral.engine.control import check_liveness

    return check_liveness(advanced, graph), effects


def route_closed_step(
    state: RunState, graph: CompiledGraph, owner: Activation
) -> tuple[RunState, tuple[Effect, ...]]:
    """Follow the stored label of a step routed by label that closed while the run was paused.

    Each session generation routes once: its ``route:`` receipt makes a later resume a
    no-op, and a retried step's new generation routes again.
    """
    if not routes_by_label(graph, owner.node_id):
        return state, ()
    slot = _owner_slot(state, owner.id)
    if slot is not None and _has_receipt(state, _route_key(owner.id, slot.session_generation)):
        return state, ()
    return _take_handoff_label(state, graph, owner)


def _owner_slot(state: RunState, owner_id: str) -> Slot | None:
    """The single slot of a step routed by label (single-agent by validation)."""
    return next((slot for slot in state.slots if slot.activation_id == owner_id), None)


def _route_key(owner_id: str, generation: int) -> str:
    return f"route:{owner_id}:{generation}"


def _has_receipt(state: RunState, key: str) -> bool:
    return any(item.key == key for item in state.receipts)


def _take_handoff_label(
    state: RunState, graph: CompiledGraph, owner: Activation
) -> tuple[RunState, tuple[Effect, ...]]:
    """Follow the arrow a single-agent step's accepted handoff named, and receipt the route.

    Validation keeps the label on the slot. A missing or unknown one means a corrupt
    log, so the run pauses rather than guess a route.
    """
    slot = _owner_slot(state, owner.id)
    label = slot.handoff_label if slot is not None else None
    if slot is None or label is None or label not in choosable_labels(graph, owner.node_id):
        from coral.engine.machines.run import record_pause

        return record_pause(state, "failure_path", "handoff_label_missing", owner.node_id), ()
    taken, effects, _redirected = take_labelled_arrow(
        state,
        graph,
        node_id=owner.node_id,
        owner_id=owner.id,
        label=label,
        item_path=owner.item_path,
        iteration_path=owner.iteration_path,
    )
    key = _route_key(owner.id, slot.session_generation)
    if _has_receipt(taken, key):
        return taken, effects
    route = Receipt(key=key, payload={"label": label})
    return taken.model_copy(update={"receipts": (*taken.receipts, route)}), effects


def replace_activation(state: RunState, owner_id: str, **changes: object) -> RunState:
    return state.model_copy(
        update={
            "activations": tuple(
                item.model_copy(update=changes) if item.id == owner_id else item
                for item in state.activations
            )
        }
    )


def choosable_labels(graph: CompiledGraph, node_id: str) -> tuple[str, ...]:
    """Labels on forward and back arrows. Failure and at-limit arrows are not choices."""
    return tuple(
        arrow.label
        for arrow in graph.arrows
        if arrow.source == node_id
        and arrow.kind in {"forward", "back"}
        and arrow.label is not None
    )


def routes_by_label(graph: CompiledGraph, node_id: str) -> bool:
    """True when a step's handoff label picks its successor.

    That is a step with a labelled forward arrow, which ``advance`` never opens, or with
    more than one choosable label. A step whose single label loops back keeps ``advance``.
    """
    node = find_node(graph, node_id)
    if node is None or node.kind != "step":
        return False
    labelled_forward = any(
        arrow.source == node_id and arrow.kind == "forward" and arrow.label is not None
        for arrow in graph.arrows
    )
    return labelled_forward or len(choosable_labels(graph, node_id)) > 1


def arrow_by_label(graph: CompiledGraph, node_id: str, label: str) -> CompiledArrow | None:
    """The outgoing arrow with ``label``, whatever its kind."""
    for arrow in graph.arrows:
        if arrow.source == node_id and arrow.label == label:
            return arrow
    return None


def find_node(graph: CompiledGraph, node_id: str) -> CompiledNode | None:
    for node in graph.nodes:
        if node.id == node_id:
            return node
    return None


def find_activation(state: RunState, owner_id: str) -> Activation | None:
    for activation in state.activations:
        if activation.id == owner_id:
            return activation
    return None


def _activation(
    node: CompiledNode,
    *,
    status: ActivationStatus,
    outcome: ActivationOutcome | None = None,
    item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
) -> Activation:
    return Activation(
        id=activation_id(node.id, item_path, iteration_path),
        node_id=node.id,
        item_path=item_path,
        iteration_path=iteration_path,
        status=status,
        outcome=outcome,
    )


def _place_running(
    state: RunState,
    node: CompiledNode,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> RunState:
    """Open ``node`` as running. A closed row with this id stays closed."""
    running = _activation(
        node, status="running", item_path=item_path, iteration_path=iteration_path
    )
    replaced = False
    activations: list[Activation] = []
    for item in state.activations:
        if item.id != running.id:
            activations.append(item)
            continue
        replaced = True
        activations.append(item if item.status == "closed" else running)
    if not replaced:
        paused = _cap_pause(state, node.id, item_path, iteration_path)
        if paused is not None:
            return paused
        activations.append(running)
    return state.model_copy(update={"activations": tuple(activations)})


def _install(state: RunState, activation: Activation) -> tuple[RunState, bool]:
    """Append ``activation``, or turn a waiting join into it. Refuse an id that already exists.

    Replacing a waiting join is not a new activation. Any other append past the cap pauses
    ``budget`` and leaves the row unopened.
    """
    for index, item in enumerate(state.activations):
        if item.id != activation.id:
            continue
        if item.status != "waiting_join":
            return state, False
        activations = list(state.activations)
        activations[index] = activation
        return state.model_copy(update={"activations": tuple(activations)}), True
    paused = _cap_pause(state, activation.node_id, activation.item_path, activation.iteration_path)
    if paused is not None:
        return paused, False
    return state.model_copy(update={"activations": (*state.activations, activation)}), True


def _is_running(
    state: RunState,
    node: CompiledNode,
    item_path: tuple[str, ...],
    iteration_path: tuple[str, ...],
) -> bool:
    owner = find_activation(state, activation_id(node.id, item_path, iteration_path))
    return owner is not None and owner.status != "closed"


def _cap_pause(
    state: RunState,
    node_id: str,
    item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
    *,
    waiting: bool = False,
) -> RunState | None:
    """Pause ``budget`` and remember the scope ``ResumeRun`` should open."""
    if len(state.activations) < state.max_activations:
        return None
    from coral.engine.machines.run import record_pause
    from coral.engine.types import Receipt

    paused = record_pause(state, "budget", "activation_cap", node_id)
    key = f"pending:{activation_id(node_id, item_path, iteration_path)}"
    if any(item.key == key for item in paused.receipts):
        return paused
    receipt = Receipt(
        key=key,
        payload={
            "code": "activation_cap",
            "node_id": node_id,
            "item_path": list(item_path),
            "iteration_path": list(iteration_path),
            "waiting": waiting,
        },
    )
    return paused.model_copy(update={"receipts": (*paused.receipts, receipt)})


def _create_session(run_id: str, seq: int, slot: Slot, node: CompiledNode) -> Effect:
    return Effect(
        effect_key=effect_key(run_id, seq, "create_session", slot.id),
        kind="create_session",
        subject=slot.id,
        payload={
            "node_id": node.id,
            "profile": slot.profile,
            "goal": node.goal or "",
        },
    )
