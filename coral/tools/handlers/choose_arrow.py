"""``coral_choose_arrow``: a pure planner over one run snapshot.

Checks run in a fixed order, first match wins: the caller is the run's current
orchestrator, the run takes choices, the arguments are known, the decision id
names a decision, a decided decision answers with its receipt or
``decision_closed``, then the reason and the label. No refusal is counted or
written; the dispatcher logs each one. A valid choice commits ``ChooseArrow``.
"""

from __future__ import annotations

from collections.abc import Mapping

from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole, SlotRole
from coral.engine.machines.activation import (
    arrow_by_label,
    choosable_labels,
    find_activation,
    find_node,
)
from coral.engine.machines.decision import choose_arrow
from coral.engine.types import Activation, ChooseArrow, Decision, RunState
from coral.model.ir import CompiledArrow, CompiledGraph, LoopInfo
from coral.tools import replies
from coral.tools.dispatch import EngineToolCall
from coral.tools.handlers.common import (
    pause_reason,
    run_stop,
    text_argument,
    unknown_arguments_message,
)
from coral.tools.port import Commit, Plan, Reply, RunSnapshot
from coral.tools.schemas import CHOOSE_ARROW_PARAMETERS, REASON_MAX, LoopUse, ToolReply

_PROPERTIES = CHOOSE_ARROW_PARAMETERS["properties"]
_FIELDS = frozenset(_PROPERTIES) if isinstance(_PROPERTIES, Mapping) else frozenset()


def plan(snapshot: RunSnapshot, *, call: EngineToolCall) -> Plan:
    """
    Answer one ``coral_choose_arrow`` call against ``snapshot``.

    :returns: A :class:`Reply` that writes nothing, or a :class:`Commit` of the
        ``ChooseArrow`` whose reply names where the run goes next.
    """
    refused = _not_orchestrator(snapshot, call)
    if refused is not None:
        return refused
    fenced = _run_fence(snapshot)
    if fenced is not None:
        return fenced
    arguments = call.arguments
    unknown = [name for name in arguments if name not in _FIELDS]
    if unknown:
        message = unknown_arguments_message(unknown, _FIELDS)
        return Reply(replies.illegal_choice("arguments", message), log="unknown arguments")
    found = _decision(snapshot, arguments.get("decision_id"))
    if found is None:
        open_ids = _open_decision_ids(snapshot)
        return Reply(replies.unknown_decision(open_ids), log="unknown decision id")
    owner, decision = found
    label = arguments.get("label")
    if decision.status == "decided":
        if decision.label is not None and label == decision.label:
            return Reply(_receipt(snapshot, owner, decision.label))
        return Reply(replies.decision_closed(), log="decision already made")
    reason = text_argument(arguments.get("reason"), REASON_MAX)
    if reason is None:
        message = f"Give a reason of 1 to {REASON_MAX} characters."
        return Reply(replies.illegal_choice("reason", message), log="no usable reason")
    labels = choosable_labels(snapshot.graph, owner.node_id)
    if not isinstance(label, str) or label not in labels:
        message = "Use one of the decision's labels."
        return Reply(replies.illegal_choice("label", message, labels), log="illegal label")
    command = ChooseArrow(
        node_id=owner.node_id,
        label=label,
        reason=reason,
        item_path=owner.item_path,
        iteration_path=owner.iteration_path,
    )
    return Commit((command,), _chosen(snapshot, owner, command))


def _not_orchestrator(snapshot: RunSnapshot, call: EngineToolCall) -> Reply | None:
    """Refuse a caller that is not this run's current orchestrator session."""
    binding = call.binding
    if (
        binding.role is not SessionBindingRole.STEP
        or binding.slot_role is not SlotRole.ORCHESTRATOR
        or binding.progress < SessionBindingProgress.ROW_CREATED
        or binding.run_id != snapshot.run.id
        or binding.workspace_id != snapshot.run.workspace_id
    ):
        return Reply(replies.not_orchestrator(), log="not an orchestrator of this run")
    current = snapshot.run.orchestrator_session_id
    if current != binding.session_id:
        detail = "no orchestrator recorded" if current is None else "replaced orchestrator"
        return Reply(replies.not_orchestrator(), log=detail)
    return None


def _run_fence(snapshot: RunSnapshot) -> Reply | None:
    """Refuse a cancelled, finished or paused run, by its store row or its engine state."""
    stop = run_stop(snapshot)
    if stop == "cancelled":
        return Reply(replies.run_cancelled(), log="choice arrived after cancel")
    if stop == "finished":
        return Reply(replies.decision_closed(), log="run finished")
    if stop == "paused":
        return Reply(replies.choice_paused(pause_reason(snapshot)))
    return None


def _decision(snapshot: RunSnapshot, decision_id: object) -> tuple[Activation, Decision] | None:
    """The decision activation ``decision_id`` names, if a choice can still reach it."""
    if not isinstance(decision_id, str):
        return None
    decision = next(
        (item for item in snapshot.state.decisions if item.activation_id == decision_id), None
    )
    owner = find_activation(snapshot.state, decision_id)
    node = None if decision is None else find_node(snapshot.graph, decision.node_id)
    if decision is None or owner is None or node is None or node.kind != "decision":
        return None
    if decision.status != "decided" and owner.status == "closed":
        return None
    return owner, decision


def _open_decision_ids(snapshot: RunSnapshot) -> tuple[str, ...]:
    """The decisions waiting for a choice, in the order they opened."""
    state = snapshot.state
    return tuple(
        item.activation_id
        for item in state.decisions
        if item.status != "decided" and _is_open(state, item.activation_id)
    )


def _is_open(state: RunState, owner_id: str) -> bool:
    owner = find_activation(state, owner_id)
    return owner is not None and owner.status != "closed"


def _chosen(snapshot: RunSnapshot, owner: Activation, command: ChooseArrow) -> ToolReply:
    """The reply to a choice, read from the engine applying it to this snapshot.

    The port applies the same input to the same state, so its result matches. If
    the engine refuses it, the port reports that refusal and this reply is unused.
    """
    graph = snapshot.graph
    applied = choose_arrow(graph, snapshot.state, command)
    after = snapshot.state if applied.rejection is not None else applied.state
    redirected = applied.rejection is None and _redirected(after, owner.id, command.label)
    arrow = arrow_by_label(graph, owner.node_id, command.label)
    loop = None
    if arrow is not None and arrow.kind == "back":
        info = _loop_info(graph, arrow.id)
        limit = info.limit if info is not None else arrow.limit
        loop = LoopUse(used=_pass_after(after, owner, arrow.id), limit=limit)
    return replies.choice_made(
        command.label, _target(graph, arrow, redirected), loop=loop, redirected=redirected
    )


def _receipt(snapshot: RunSnapshot, owner: Activation, label: str) -> ToolReply:
    """The reply to a choice already made, from its stored receipt.

    No loop pass is given: the loop may have moved on since the choice.
    """
    graph = snapshot.graph
    redirected = _redirected(snapshot.state, owner.id, label)
    arrow = arrow_by_label(graph, owner.node_id, label)
    return replies.choice_made(
        label, _target(graph, arrow, redirected), redirected=redirected, duplicate=True
    )


def _redirected(state: RunState, owner_id: str, label: str) -> bool:
    """Whether the choice's receipt records that a loop limit redirected it."""
    key = f"choice:{owner_id}:{label}"
    receipt = next((item for item in state.receipts if item.key == key), None)
    return receipt is not None and receipt.payload.get("redirected") is True


def _target(graph: CompiledGraph, arrow: CompiledArrow | None, redirected: bool) -> str | None:
    """The node the choice went to: the arrow's target, or its at-limit arrow's when redirected."""
    if arrow is None:
        return None
    if not redirected:
        return arrow.target
    info = _loop_info(graph, arrow.id)
    limit_id = info.at_limit_arrow_id if info is not None else arrow.at_limit
    limit_arrow = next((item for item in graph.arrows if item.id == limit_id), None)
    return None if limit_arrow is None else limit_arrow.target


def _loop_info(graph: CompiledGraph, back_arrow_id: str) -> LoopInfo | None:
    return next(
        (loop for loop in graph.analysis.loops if loop.back_arrow_id == back_arrow_id), None
    )


def _pass_after(state: RunState, owner: Activation, back_arrow_id: str) -> int:
    """The loop counter's pass after the choice, for the loop scope the decision runs in."""
    enclosing = tuple(
        part for part in owner.iteration_path if not part.startswith(f"{back_arrow_id}:")
    )
    return next(
        (
            item.pass_index
            for item in state.loop_counters
            if item.back_arrow_id == back_arrow_id
            and item.item_path == owner.item_path
            and item.iteration_path == enclosing
        ),
        1,
    )
