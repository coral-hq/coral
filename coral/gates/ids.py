"""Gate ids, caps and the one rule that says whether a gate visit can still be answered."""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence

from coral.alerts.types import MAX_ALERT_OUTCOME_CHARS, MAX_ALERT_OUTCOMES
from coral.engine import types as engine
from coral.engine.machines.activation import find_node
from coral.model.ids import derived_id
from coral.model.ir import CompiledGraph, CompiledNode
from coral.stores.protocols import GateVisitState

GATE_ELICITATION_PREFIX = "coral_gate_"
GATE_ELICITATION_ID = re.compile(r"coral_gate_[0-9a-f]{32}")
# Work rows that publish and withdraw a visit's prompt, and their bridge item.
GATE_PUBLISH = "gate_publish"
GATE_WITHDRAW = "gate_withdraw"
GATE_ITEM = "gate"
# An alert lists every outcome of its gate, so a gate may have no more than it holds.
MAX_GATE_OUTCOMES = MAX_ALERT_OUTCOMES
MAX_GATE_OUTCOME_CHARS = MAX_ALERT_OUTCOME_CHARS
MAX_GATE_NOTE_CHARS = 2_000
GATE_POLICY_NAME = "coral.gate"
LIVE_RUN_STATUSES = frozenset({"running", "paused"})
_BINARY_OUTCOMES = (frozenset({"approve"}), frozenset({"approve", "reject"}))


def live_visit(state: engine.RunState, visit: engine.GateVisit) -> bool:
    """The visit can still be answered: open, in a run that has started and not finished."""
    return visit.status == "open" and state.status in LIVE_RUN_STATUSES


def live_visit_ids(state: engine.RunState, run_id: str) -> frozenset[str]:
    """The row ids of the run's live visits."""
    return frozenset(
        gate_visit_id(run_id, visit.token) for visit in state.gates if live_visit(state, visit)
    )


def gate_visit_id(run_id: str, token: str) -> str:
    """The 32-hex ``coral_gate_visits`` id of an engine visit."""
    return derived_id("coral-gate-visit", run_id, token)


def new_gate_elicitation_id() -> str:
    """A prompt id nobody can derive from the run: chosen once, stored on the visit's row."""
    return GATE_ELICITATION_PREFIX + secrets.token_hex(16)


def find_visit(state: engine.RunState, run_id: str, visit_id: str) -> engine.GateVisit | None:
    """The engine visit whose row id is ``visit_id``."""
    for visit in state.gates:
        if gate_visit_id(run_id, visit.token) == visit_id:
            return visit
    return None


def receipt_label(state: engine.RunState, token: str) -> str | None:
    """The label the receipt of the visit ``token`` records, if the state holds one."""
    receipt = next((item for item in state.receipts if item.key == token), None)
    label = receipt.payload.get("label") if receipt is not None else None
    return label if isinstance(label, str) else None


def row_by_elicitation(
    rows: Sequence[GateVisitState], elicitation_id: str
) -> GateVisitState | None:
    """The row whose stored prompt id is ``elicitation_id``."""
    for row in rows:
        if row.elicitation_id == elicitation_id:
            return row
    return None


def gate_node(graph: CompiledGraph, visit: engine.GateVisit) -> CompiledNode | None:
    """The gate node the visit belongs to."""
    node = find_node(graph, visit.activation_id.split("|", 1)[0])
    return node if node is not None and node.kind == "gate" else None


def is_binary_gate(node: CompiledNode) -> bool:
    """An approve-only or approve-or-reject gate, which a plain approval can answer."""
    return frozenset(node.outcomes) in _BINARY_OUTCOMES


__all__ = [
    "GATE_ELICITATION_ID",
    "GATE_ELICITATION_PREFIX",
    "GATE_ITEM",
    "GATE_POLICY_NAME",
    "GATE_PUBLISH",
    "GATE_WITHDRAW",
    "LIVE_RUN_STATUSES",
    "MAX_GATE_NOTE_CHARS",
    "MAX_GATE_OUTCOMES",
    "MAX_GATE_OUTCOME_CHARS",
    "find_visit",
    "gate_node",
    "gate_visit_id",
    "is_binary_gate",
    "live_visit",
    "live_visit_ids",
    "new_gate_elicitation_id",
    "receipt_label",
    "row_by_elicitation",
]
