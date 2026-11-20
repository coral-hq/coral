"""Engine gate visits as ``coral_gate_visits`` rows, and their delivery as bridge rows.

A row is ``OPEN`` exactly while its visit is live (:func:`coral.gates.ids.live_visit`);
an open visit of a finished run is ``CANCELLED``. A row's elicitation id is drawn
once, when the row is first written, and kept from then on. Publish and withdraw
rows name only the visit; their executors read everything else from the run.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from coral.bridge.config import MAX_ACTOR_REF_CHARS, epoch_seconds
from coral.bridge.keys import store_activation_id
from coral.db.enum_codecs import GateVisitStatus
from coral.engine import types as engine
from coral.gates.ids import (
    GATE_ITEM,
    GATE_PUBLISH,
    GATE_WITHDRAW,
    gate_visit_id,
    live_visit,
    new_gate_elicitation_id,
)
from coral.model.ids import anchor_session_id
from coral.stores.protocols import CoralRun, GateVisitDraft, GateVisitState, WorkItemDraft

if TYPE_CHECKING:
    from coral.bridge.mapping import MapContext

_ENGINE_STATUSES = {
    "resolved": GateVisitStatus.RESOLVED,
    "superseded": GateVisitStatus.SUPERSEDED,
}


def project_gates(
    run: CoralRun,
    state: engine.RunState,
    loaded: Sequence[GateVisitState],
    *,
    workspace_id: int,
    now: int,
    new_elicitation_id: Callable[[], str] = new_gate_elicitation_id,
) -> tuple[GateVisitDraft, ...]:
    """
    A draft for every engine visit whose row is missing or shows something else.

    The engine owns the ids, scope, token, status and answer; the elicitation id, the
    open and resolve times, the prompt ref and the reminder time keep what the loaded
    row holds, and are set only when the row has none.
    """
    rows = {row.id: row for row in loaded}
    anchor = anchor_session_id(workspace_id, run.id)
    drafts: list[GateVisitDraft] = []
    for visit in state.gates:
        row_id = gate_visit_id(run.id, visit.token)
        row = rows.get(row_id)
        stored = _as_draft(row) if row is not None else None
        status = _ENGINE_STATUSES.get(
            visit.status,
            GateVisitStatus.OPEN if live_visit(state, visit) else GateVisitStatus.CANCELLED,
        )
        resolved_at = row.resolved_at if row is not None else None
        projected = GateVisitDraft(
            id=row_id,
            activation_id=store_activation_id(run.id, visit.activation_id),
            node_id=visit.activation_id.split("|", 1)[0],
            scope_key=visit.activation_id,
            visit_no=visit.visit_no,
            token=visit.token,
            status=int(status),
            owner_user_id=run.user_id,
            elicitation_id=(
                row.elicitation_id
                if row is not None and row.elicitation_id is not None
                else new_elicitation_id()
            ),
            elicitation_session_id=anchor,
            prompt_ref=row.prompt_ref if row is not None else None,
            answer_label=visit.label,
            answered_by=visit.by[:MAX_ACTOR_REF_CHARS] if visit.by else None,
            note=visit.note or None,
            opened_at=row.opened_at if row is not None else now,
            reminded_at=row.reminded_at if row is not None else None,
            resolved_at=(
                resolved_at if resolved_at is not None or status == GateVisitStatus.OPEN else now
            ),
        )
        if projected != stored:
            drafts.append(projected)
    return tuple(drafts)


def gate_publish_draft(ctx: MapContext, effect: engine.Effect) -> WorkItemDraft:
    """The row that publishes a visit's prompt on the run's anchor, due now."""
    return _gate_draft(ctx, effect, GATE_PUBLISH)


def gate_withdraw_draft(ctx: MapContext, effect: engine.Effect) -> WorkItemDraft:
    """The row that withdraws a superseded or cancelled visit's prompt, due now."""
    return _gate_draft(ctx, effect, GATE_WITHDRAW)


def live_publish_effects(state: engine.RunState) -> tuple[engine.Effect, ...]:
    """The ``publish_gate`` effects of the run's live visits."""
    live = {visit.token for visit in state.gates if live_visit(state, visit)}
    return tuple(
        effect
        for effect in state.effects
        if effect.kind == "publish_gate" and effect.subject in live
    )


def _gate_draft(ctx: MapContext, effect: engine.Effect, effect_type: str) -> WorkItemDraft:
    # The subject is the visit's token, ``{activation}:{visit_no}``.
    payload = {
        "effect_type": effect_type,
        "effect_key": effect.effect_key,
        "bridge_item": GATE_ITEM,
        "visit_id": gate_visit_id(ctx.run_id, effect.subject),
    }
    return WorkItemDraft.effect(
        run_id=ctx.run_id,
        idempotency_key=effect.effect_key,
        payload=payload,
        node_id=effect.subject.split("|", 1)[0],
        available_at=epoch_seconds(ctx.now),
    )


def _as_draft(row: GateVisitState) -> GateVisitDraft:
    names = {field.name for field in dataclasses.fields(GateVisitDraft)}
    return GateVisitDraft(**{name: getattr(row, name) for name in names})


__all__ = [
    "gate_publish_draft",
    "gate_withdraw_draft",
    "live_publish_effects",
    "project_gates",
]
