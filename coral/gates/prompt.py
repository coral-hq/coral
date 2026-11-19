"""The form a gate visit is published as on its run's anchor session."""

from __future__ import annotations

from typing import Any

from coral.alerts.types import normalize_owner
from coral.bridge.messages import gate_prompt_text, strip_format_characters
from coral.engine import types as engine
from coral.gates.ids import GATE_POLICY_NAME, MAX_GATE_NOTE_CHARS, gate_node
from coral.model.ir import CompiledGraph
from coral.stores.protocols import CoralRun, GateVisitState


def gate_params(
    graph: CompiledGraph,
    state: engine.RunState,
    run: CoralRun,
    visit: engine.GateVisit,
    row: GateVisitState,
) -> dict[str, Any]:
    """
    The elicitation params of ``visit``: a form asking for one outcome and an optional note.

    The same log and row give the same params, so a republish shows what the first
    publish showed. ``coral`` names the run, the visit and its row's open time; the
    single local user is named as no owner. No text carries a format character.
    """
    node = gate_node(graph, visit)
    outcomes = list(node.outcomes) if node is not None else []
    return {
        "mode": "form",
        "message": gate_prompt_text(graph, state, visit, run_title=run.title),
        "requestedSchema": {
            "type": "object",
            "required": ["decision"],
            "properties": {
                "decision": {"type": "string", "title": "Decision", "enum": outcomes},
                "note": {"type": "string", "title": "Note", "maxLength": MAX_GATE_NOTE_CHARS},
            },
        },
        "policy_name": GATE_POLICY_NAME,
        "phase": "gate",
        "coral": {
            "kind": "gate",
            "run_id": run.id,
            "visit_id": row.id,
            "node_id": row.node_id,
            "visit_no": visit.visit_no,
            "opened_at": row.opened_at,
            "run_owner": normalize_owner(run.user_id),
            "run_title": strip_format_characters(run.title),
            "outcomes": outcomes,
            "deep_link": f"/workflows/runs/{run.id}?node={row.node_id}&panel=gate",
        },
    }


__all__ = ["gate_params"]
