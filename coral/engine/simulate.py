"""Simulate a workflow: the real reducer with stub effects, answered from a script.

Every log entry comes from ``transition``. Session effects are acknowledged at once;
what an agent, the orchestrator or a person would supply (a handoff label, a done-when
result, a choice, a gate answer) comes from per-node queues in the script. When a
queue runs out the simulation stops and asks for that value; it never guesses.

One driver step takes the first applicable action in this order: acknowledge the
oldest stubbed effect, hand off the first working slot, choose for the first open
decision, answer the first open gate. In a parallel region the branch whose slot comes
first in the run state goes first. Nothing reads a clock or iterates a set for order,
so equal graphs and scripts give equal logs in any process.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from coral.engine.machines.activation import (
    choosable_labels,
    find_activation,
    find_node,
    routes_by_label,
)
from coral.engine.projection import RunView, project
from coral.engine.reducer import transition
from coral.engine.types import (
    RULES,
    Activation,
    AnswerGate,
    ChooseArrow,
    Effect,
    EffectCompleted,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    LogEntry,
    Rejection,
    RunState,
    Slot,
    StartRun,
    empty_state,
    loop_limit_key,
)
from coral.model.canonical import canonical_json
from coral.model.ids import MAX_SLUG_LENGTH
from coral.model.ir import CompiledGraph, CompiledNode

SIMULATION_RUN_ID: Final = "simulation"
# The one clock value every entry carries; nothing sleeps.
SIMULATED_AT: Final = datetime(2026, 1, 1, tzinfo=UTC)
SIMULATED_BY: Final = "simulation"
SIMULATED_HANDOFF: Final = "Simulated handoff."
SIMULATED_REASON: Final = "Simulated choice."
DONE_WHEN_VALUES: Final = ("pass", "fail")
MAX_SCRIPT_INPUTS: Final = 200
MAX_INPUT_VALUES: Final = 100
MAX_SCRIPT_VALUES: Final = 1000
MAX_VALUE_CHARS: Final = 255
# A script's node id is a node id: a slug.
MAX_NODE_ID_CHARS: Final = MAX_SLUG_LENGTH
DEFAULT_MAX_TRANSITIONS: Final = 5000
# Work approximates what transitions cost: each one copies and projects the run state and
# scans the graph, and copies the receipts again for every receipt it adds (a choice
# receipts each labelled arrow it skips). It is checked between transitions, so it cannot
# stop one costly transition; the caps below, checked before the run starts, bound those.
DEFAULT_MAX_WORK: Final = 1_000_000
# Opening a step compares each of its seats with every slot so far, in one transition.
MAX_STEP_SEATS: Final = 16
MAX_GRAPH_SEATS: Final = 64
# A waiting AND join's liveness check walks the graph from every open branch, in one
# transition; its cost grows with the open branches and the graph's nodes and arrows.
MAX_SIMULATED_NODES: Final = 96
MAX_SIMULATED_ARROWS: Final = 192

# Effects a simulation acknowledges at once, with the payload their executor would report.
STUBBED_EFFECTS: Final[Mapping[str, Mapping[str, JsonValue]]] = MappingProxyType(
    {
        "create_session": MappingProxyType({}),
        "send_input": MappingProxyType({}),
        "close_slot": MappingProxyType({"pending_input": False}),
        "nudge": MappingProxyType({}),
        "steer": MappingProxyType({}),
    }
)
# Effects that need no answer: a gate waits for its answer, alerts and timers do not report.
UNANSWERED_EFFECTS: Final = frozenset({"publish_gate", "withdraw_gate", "notify", "arm_timer"})
# Effects a simulation cannot model yet; meeting one, or a kind in no table, ends it.
UNSUPPORTED_EFFECTS: Final = frozenset(
    {
        "retry_step",
        "runner_lost",
        "cancel_sessions",
        "structure.start_item",
        "structure.cancel_region",
    }
)

EffectClass = Literal["stubbed", "unanswered", "unsupported"]
SimInputKind = Literal["label", "done_when", "gate"]
SimOutcome = Literal[
    "completed",
    "failed",
    "cancelled",
    "paused",
    "needs_input",
    "rejected",
    "stalled",
    "step_limit",
    "unsupported",
]
# The bound that ended a ``step_limit`` simulation. The last three refuse a graph before
# its run starts.
SimLimit = Literal["transitions", "work", "step_seats", "graph_seats", "graph_size"]

# C0 and C1 controls, bidirectional controls, and surrogates: in a str, any surrogate is
# unpaired, and no response or row can carry one.
_UNSAFE_TEXT = re.compile(
    "[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ud800-\udfff]"
)
# A run that stopped on its own ends the simulation with its status.
_OUTCOME_OF_STATUS: Final[Mapping[str, SimOutcome]] = MappingProxyType(
    {"completed": "completed", "failed": "failed", "cancelled": "cancelled", "paused": "paused"}
)


def check_script_text(value: str) -> str:
    """Refuse control, bidirectional-control and surrogate characters.

    The message names the rule, never the value, which a refusal must not echo.
    """
    if _UNSAFE_TEXT.search(value) is not None:
        raise ValueError(
            "must not hold control characters, bidirectional controls or unpaired surrogates"
        )
    return value


ScriptNodeId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_NODE_ID_CHARS),
    AfterValidator(check_script_text),
]
ScriptValue = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_VALUE_CHARS),
    AfterValidator(check_script_text),
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SimInput(_Frozen):
    """The values one node supplies for one kind of question, consumed in order."""

    node_id: ScriptNodeId
    kind: SimInputKind
    values: tuple[ScriptValue, ...] = Field(min_length=1, max_length=MAX_INPUT_VALUES)

    @model_validator(mode="after")
    def _done_when_values(self) -> SimInput:
        if self.kind == "done_when" and any(item not in DONE_WHEN_VALUES for item in self.values):
            raise ValueError("done_when values must be pass or fail")
        return self


class SimScript(_Frozen):
    """What a simulation answers with: at most one input per node and kind."""

    inputs: tuple[SimInput, ...] = Field(default=(), max_length=MAX_SCRIPT_INPUTS)

    @model_validator(mode="after")
    def _bounded_and_unique(self) -> SimScript:
        pairs = [(item.node_id, item.kind) for item in self.inputs]
        if len(set(pairs)) != len(pairs):
            raise ValueError("each node and kind may appear in one input")
        if sum(len(item.values) for item in self.inputs) > MAX_SCRIPT_VALUES:
            raise ValueError(f"a script holds at most {MAX_SCRIPT_VALUES} values")
        return self


class SimStep(_Frozen):
    """One answered step, decision or gate.

    ``result`` is a step's label, ``done`` or ``evidence_missing``; a decision's label;
    a gate's outcome.
    """

    node_id: str
    activation_id: str
    kind: Literal["step", "decision", "gate"]
    result: str


class SimLoop(_Frozen):
    """One loop counter. ``iteration_path`` is its enclosing loops' passes; ``()`` outside."""

    back_arrow_id: str
    iteration_path: tuple[str, ...]
    passes: int
    limit: int | None
    limit_hit: bool


class SimSessions(_Frozen):
    """An estimate of the sessions a real run would start.

    The run's turnless anchor, an orchestrator once any decision opens, and one per
    step session created; a done-when retry reuses its session.
    """

    anchor: int
    orchestrator: int
    steps: int
    total: int


class SimNeedsInput(_Frozen):
    """The value a simulation stopped to ask for, and the values the reducer would take."""

    node_id: str
    activation_id: str
    kind: SimInputKind
    allowed_values: tuple[str, ...]


class SimRejection(_Frozen):
    """A script value the reducer refused, with the reducer's own code and choices."""

    node_id: str
    kind: SimInputKind
    value: str
    code: str
    allowed_values: tuple[str, ...]


class SimUnconsumed(_Frozen):
    """Script values no question used, in their input's order."""

    node_id: str
    kind: SimInputKind
    values: tuple[str, ...]


class SimResult(_Frozen):
    """What a simulation did: its outcome, the answered path, and the run it left."""

    outcome: SimOutcome
    steps: tuple[SimStep, ...]
    loops: tuple[SimLoop, ...]
    # Gate node ids, one per visit, in visit order.
    gates_reached: tuple[str, ...]
    # Back-arrow ids whose limit redirected, in order.
    limits_hit: tuple[str, ...]
    step_activations: int
    sessions: SimSessions
    needs_input: SimNeedsInput | None = None
    rejection: SimRejection | None = None
    # The effect kind an ``unsupported`` simulation met.
    unsupported_effect: str | None = None
    # The reducer's code when it refused an input the simulation made, not a script value.
    stall_code: str | None = None
    # The bound that ended a ``step_limit`` simulation.
    limit: SimLimit | None = None
    unconsumed: tuple[SimUnconsumed, ...] = ()
    view: RunView
    # SHA-256 of the canonical log; comparable only within one engine and log version.
    trace_digest: str
    # Log length, rejected entries included.
    entries: int


@dataclass(frozen=True)
class Simulation:
    """A result with the log, final state and config it came from.

    ``fold(graph, log, config) == state``.
    """

    result: SimResult
    log: tuple[LogEntry, ...]
    state: RunState
    config: EngineConfig


def classify_effect(kind: str) -> EffectClass:
    """How a simulation treats an effect kind; an unknown kind is unsupported."""
    if kind in STUBBED_EFFECTS:
        return "stubbed"
    if kind in UNANSWERED_EFFECTS:
        return "unanswered"
    return "unsupported"


def simulate(
    graph: CompiledGraph,
    script: SimScript,
    *,
    max_activations: int,
    max_transitions: int = DEFAULT_MAX_TRANSITIONS,
    max_work: int = DEFAULT_MAX_WORK,
) -> Simulation:
    """Run ``graph`` on the real reducer with stub effects, answering from ``script``.

    A graph with more roster seats than ``MAX_STEP_SEATS`` on one step or
    ``MAX_GRAPH_SEATS`` in all, or more than ``MAX_SIMULATED_NODES`` nodes or
    ``MAX_SIMULATED_ARROWS`` arrows, ends in ``step_limit`` before its run starts, with no
    entries and no sessions. So does a run that spends ``max_transitions`` inputs or
    ``max_work``. ``SimResult.limit`` names the bound.

    :raises ValueError: when ``graph.analysis.unresolved`` is not empty; callers validate first.
    """
    if graph.analysis.unresolved:
        raise ValueError("the graph has unresolved facts; validate it before simulating")
    config = EngineConfig(max_activations=max_activations)
    driver = _Driver(graph, script, config, max_transitions=max_transitions, max_work=max_work)
    refused = _refused_before_start(graph)
    if refused is not None:
        driver.stop = _Stop("step_limit", limit=refused)
    else:
        driver.run()
    return Simulation(
        result=driver.result(), log=tuple(driver.log), state=driver.state, config=config
    )


@dataclass(frozen=True)
class _Stop:
    outcome: SimOutcome
    needs_input: SimNeedsInput | None = None
    rejection: SimRejection | None = None
    unsupported_effect: str | None = None
    stall_code: str | None = None
    limit: SimLimit | None = None


class _Driver:
    """Feeds the reducer and keeps what the result reports."""

    def __init__(
        self,
        graph: CompiledGraph,
        script: SimScript,
        config: EngineConfig,
        *,
        max_transitions: int,
        max_work: int,
    ) -> None:
        self.graph = graph
        self.graph_size = len(graph.nodes) + len(graph.arrows)
        self.config = config
        self.max_transitions = max_transitions
        self.max_work = max_work
        self.order = tuple((item.node_id, item.kind) for item in script.inputs)
        self.queues = {(item.node_id, item.kind): deque(item.values) for item in script.inputs}
        self.state = empty_state()
        self.log: list[LogEntry] = []
        # Stubbed effects not yet acknowledged, oldest first: filled from accepted entries,
        # so no step rescans the run's effects against its receipts.
        self.pending: deque[Effect] = deque()
        self.steps: list[SimStep] = []
        self.step_sessions = 0
        self.work = 0
        self.stop: _Stop | None = None

    def run(self) -> None:
        start = StartRun(
            run_id=SIMULATION_RUN_ID,
            start_key=SIMULATION_RUN_ID,
            version_hash=self.graph.content_hash,
            rules=RULES,
        )
        refused = self._apply(start)
        if refused is not None:
            self._stall(refused)
        while self.stop is None and self.state.status == "running" and self._within_budget():
            if not (self._ack() or self._hand_off() or self._decide() or self._answer_gate()):
                self.stop = _Stop("stalled")

    def _within_budget(self) -> bool:
        return self._spent() is None

    def _spent(self) -> SimLimit | None:
        """The budget this run has used up, transitions first."""
        if len(self.log) >= self.max_transitions:
            return "transitions"
        if self.work >= self.max_work:
            return "work"
        return None

    def _apply(self, command: Input) -> Rejection | None:
        """Apply one input; on acceptance, queue its stubbed effects and stop on unsupported."""
        before = self.state
        applied = transition(self.graph, before, command, SIMULATED_AT, self.config)
        self.log.append(applied.entry)
        if applied.entry.rejection is None:
            self.state = applied.state
        receipts_added = len(self.state.receipts) - len(before.receipts)
        self.work += _state_size(self.state) * max(1, receipts_added) + self.graph_size
        if applied.entry.rejection is not None:
            return applied.entry.rejection
        for effect in applied.entry.effects:
            effect_class = classify_effect(effect.kind)
            if effect_class == "stubbed":
                self.pending.append(effect)
                if effect.kind == "create_session":
                    self.step_sessions += 1
            elif effect_class == "unsupported" and self.stop is None:
                self.stop = _Stop("unsupported", unsupported_effect=effect.kind)
        return None

    def _stall(self, refused: Rejection) -> None:
        self.stop = _Stop("stalled", stall_code=refused.code)

    def _ack(self) -> bool:
        if not self.pending:
            return False
        effect = self.pending.popleft()
        payload = dict(STUBBED_EFFECTS[effect.kind])
        refused = self._apply(EffectCompleted(effect_key=effect.effect_key, payload=payload))
        if refused is not None:
            self._stall(refused)
        return True

    def _hand_off(self) -> bool:
        slot = next((item for item in self.state.slots if item.status == "working"), None)
        if slot is None:
            return False
        owner = find_activation(self.state, slot.activation_id)
        node = find_node(self.graph, owner.node_id) if owner is not None else None
        if owner is None or node is None:
            self.stop = _Stop("stalled")
            return True
        # Peek every value this handoff needs before consuming any.
        done_when = self._queue(node.id, "done_when")
        if node.evidence is not None and not done_when:
            self._ask(node.id, owner.id, "done_when", DONE_WHEN_VALUES)
            return True
        accepted = node.evidence is None or done_when[0] == "pass"
        labels = self._queue(node.id, "label")
        needs_label = accepted and routes_by_label(self.graph, node.id)
        if needs_label and not labels:
            self._ask(node.id, owner.id, "label", choosable_labels(self.graph, node.id))
            return True
        # A handoff is two inputs; one that cannot fit under the cap consumes nothing.
        if len(self.log) + 2 > self.max_transitions:
            self.stop = _Stop("step_limit", limit="transitions")
            return True
        if node.evidence is not None:
            done_when.popleft()
        if not accepted:
            self._fail_done_when(slot, owner, node)
        else:
            self._accept(slot, owner, node, labels.popleft() if needs_label else None)
        return True

    def _fail_done_when(self, slot: Slot, owner: Activation, node: CompiledNode) -> None:
        missing = tuple(item.item_id for item in node.evidence.items) if node.evidence else ()
        received = HandoffReceived(
            slot_id=slot.id, body=SIMULATED_HANDOFF, session_generation=slot.session_generation
        )
        evaluated = HandoffEvaluated(
            slot_id=slot.id,
            outcome="evidence_missing",
            missing=missing,
            session_generation=slot.session_generation,
        )
        if self._apply_generated(received) and self._apply_generated(evaluated):
            self._record(node.id, owner.id, "step", "evidence_missing")

    def _accept(
        self, slot: Slot, owner: Activation, node: CompiledNode, label: str | None
    ) -> None:
        received = HandoffReceived(
            slot_id=slot.id,
            body=SIMULATED_HANDOFF,
            label=label,
            session_generation=slot.session_generation,
        )
        refused = self._apply(received)
        if refused is not None:
            if label is None:
                self._stall(refused)
            else:
                self._reject(node.id, "label", label, refused)
            return
        evaluated = HandoffEvaluated(
            slot_id=slot.id, outcome="accepted", session_generation=slot.session_generation
        )
        if self._apply_generated(evaluated):
            self._record(node.id, owner.id, "step", label or "done")

    def _apply_generated(self, command: Input) -> bool:
        """Apply an input the simulation made; False when the simulation stopped."""
        if self.stop is not None:
            return False
        refused = self._apply(command)
        if refused is not None:
            self._stall(refused)
        return self.stop is None

    def _decide(self) -> bool:
        decision = next((item for item in self.state.decisions if item.status != "decided"), None)
        if decision is None:
            return False
        owner = find_activation(self.state, decision.activation_id)
        if owner is None:
            self.stop = _Stop("stalled")
            return True
        labels = self._queue(decision.node_id, "label")
        if not labels:
            allowed = choosable_labels(self.graph, decision.node_id)
            self._ask(decision.node_id, owner.id, "label", allowed)
            return True
        label = labels.popleft()
        choice = ChooseArrow(
            node_id=decision.node_id,
            label=label,
            reason=SIMULATED_REASON,
            item_path=owner.item_path,
            iteration_path=owner.iteration_path,
        )
        refused = self._apply(choice)
        if refused is not None:
            self._reject(decision.node_id, "label", label, refused)
        else:
            self._record(decision.node_id, owner.id, "decision", label)
        return True

    def _answer_gate(self) -> bool:
        visit = next((item for item in self.state.gates if item.status == "open"), None)
        if visit is None:
            return False
        owner = find_activation(self.state, visit.activation_id)
        node = find_node(self.graph, owner.node_id) if owner is not None else None
        if owner is None or node is None:
            self.stop = _Stop("stalled")
            return True
        answers = self._queue(node.id, "gate")
        if not answers:
            # The labels the reducer accepts for this gate.
            allowed = node.outcomes or choosable_labels(self.graph, node.id)
            self._ask(node.id, owner.id, "gate", allowed)
            return True
        value = answers.popleft()
        refused = self._apply(AnswerGate(token=visit.token, label=value, by=SIMULATED_BY))
        if refused is not None:
            self._reject(node.id, "gate", value, refused)
        else:
            self._record(node.id, owner.id, "gate", value)
        return True

    def _queue(self, node_id: str, kind: SimInputKind) -> deque[str]:
        return self.queues.get((node_id, kind)) or deque()

    def _ask(
        self, node_id: str, owner_id: str, kind: SimInputKind, allowed: tuple[str, ...]
    ) -> None:
        asked = SimNeedsInput(
            node_id=node_id, activation_id=owner_id, kind=kind, allowed_values=allowed
        )
        self.stop = _Stop("needs_input", needs_input=asked)

    def _reject(self, node_id: str, kind: SimInputKind, value: str, refused: Rejection) -> None:
        rejection = SimRejection(
            node_id=node_id,
            kind=kind,
            value=value,
            code=refused.code,
            allowed_values=refused.allowed_values,
        )
        self.stop = _Stop("rejected", rejection=rejection)

    def _record(
        self,
        node_id: str,
        owner_id: str,
        kind: Literal["step", "decision", "gate"],
        result: str,
    ) -> None:
        self.steps.append(
            SimStep(node_id=node_id, activation_id=owner_id, kind=kind, result=result)
        )

    def _final_stop(self) -> _Stop:
        if self.stop is not None:
            return self.stop
        status = self.state.status
        ended = _OUTCOME_OF_STATUS.get(status) if status is not None else None
        if ended is not None:
            return _Stop(ended)
        spent = self._spent()
        if status == "running" and spent is not None:
            return _Stop("step_limit", limit=spent)
        return _Stop("stalled")

    def result(self) -> SimResult:
        state = self.state
        stop = self._final_stop()
        loops, limits_hit = _loops(self.graph, state)
        node_kinds = {node.id: node.kind for node in self.graph.nodes}
        nodes_by_activation = {item.id: item.node_id for item in state.activations}
        # A run that never started would start no session.
        started = state.status is not None
        anchor = 1 if started else 0
        orchestrator = 1 if state.decisions else 0
        return SimResult(
            outcome=stop.outcome,
            steps=tuple(self.steps),
            loops=loops,
            gates_reached=tuple(nodes_by_activation[visit.activation_id] for visit in state.gates),
            limits_hit=limits_hit,
            step_activations=sum(
                1 for item in state.activations if node_kinds.get(item.node_id) == "step"
            ),
            sessions=SimSessions(
                anchor=anchor,
                orchestrator=orchestrator,
                steps=self.step_sessions,
                total=anchor + orchestrator + self.step_sessions,
            ),
            needs_input=stop.needs_input,
            rejection=stop.rejection,
            unsupported_effect=stop.unsupported_effect,
            stall_code=stop.stall_code,
            limit=stop.limit,
            unconsumed=tuple(
                SimUnconsumed(node_id=node_id, kind=kind, values=tuple(self.queues[node_id, kind]))
                for node_id, kind in self.order
                if self.queues[node_id, kind]
            ),
            view=project(state),
            trace_digest=_trace_digest(self.log),
            entries=len(self.log),
        )


def _loops(graph: CompiledGraph, state: RunState) -> tuple[tuple[SimLoop, ...], tuple[str, ...]]:
    """Each loop counter with its limit, and the back arrows whose limit redirected, in order.

    Only a redirect at the limit writes a counter's loop-limit receipt.
    """
    limits = {loop.back_arrow_id: loop.limit for loop in graph.analysis.loops}
    receipt_keys = {item.key for item in state.receipts}
    hit_by_key: dict[str, str] = {}
    loops: list[SimLoop] = []
    for counter in state.loop_counters:
        arrow_id = counter.back_arrow_id
        key = loop_limit_key(arrow_id, counter.item_path, counter.iteration_path)
        hit = key in receipt_keys
        if hit:
            hit_by_key[key] = arrow_id
        limit = limits[arrow_id] if arrow_id in limits else _arrow_limit(graph, arrow_id)
        loops.append(
            SimLoop(
                back_arrow_id=arrow_id,
                iteration_path=counter.iteration_path,
                passes=counter.pass_index,
                limit=limit,
                limit_hit=hit,
            )
        )
    limits_hit = tuple(hit_by_key[item.key] for item in state.receipts if item.key in hit_by_key)
    return tuple(loops), limits_hit


def _arrow_limit(graph: CompiledGraph, arrow_id: str) -> int | None:
    return next((arrow.limit for arrow in graph.arrows if arrow.id == arrow_id), None)


def _refused_before_start(graph: CompiledGraph) -> SimLimit | None:
    """The cap a graph exceeds; one transition of its run could cost more than any budget."""
    seats = [len(node.roster) for node in graph.nodes if node.kind == "step"]
    if any(count > MAX_STEP_SEATS for count in seats):
        return "step_seats"
    if sum(seats) > MAX_GRAPH_SEATS:
        return "graph_seats"
    if len(graph.nodes) > MAX_SIMULATED_NODES or len(graph.arrows) > MAX_SIMULATED_ARROWS:
        return "graph_size"
    return None


def _state_size(state: RunState) -> int:
    """The rows a transition over ``state`` copies, compares and projects."""
    return (
        len(state.activations)
        + len(state.slots)
        + len(state.decisions)
        + len(state.gates)
        + len(state.arrivals)
        + len(state.loop_counters)
        + len(state.attempts)
        + len(state.timers)
        + len(state.receipts)
        + len(state.effects)
    )


def _trace_digest(log: Sequence[LogEntry]) -> str:
    """SHA-256 of each entry's canonical JSON line by line, never the whole log at once.

    Canonical JSON escapes newlines, so the line breaks keep entries apart.
    """
    digest = hashlib.sha256()
    for entry in log:
        digest.update(canonical_json(entry.model_dump(mode="json")))
        digest.update(b"\n")
    return digest.hexdigest()
