"""Pure turn-end rule. Missing facts are ``not_ended``. This does not raise."""

from __future__ import annotations

from typing import Literal

from coral.engine.facts import TurnSnapshot

TurnVerdict = Literal["completed", "cancelled", "failed", "not_ended", "ignored"]

# ``turn_outcome``, status, error text, error code, failure origin, and response id may be absent.
_REQUIRED = (
    "live_status",
    "engine_stable_id_present",
    "newest_substantive_item_is_assistant",
    "saw_response_completed",
    "background_tasks",
    "pending_elicitation_count",
    "engine_pending_input",
    "origin",
    "engine_started",
)


def evaluate(snapshot: TurnSnapshot) -> TurnVerdict:
    """Decide whether a turn ended. User origin is not ignored, and idle alone is not success."""
    if any(getattr(snapshot, name) is None for name in _REQUIRED):
        return "not_ended"
    if snapshot.origin == "archive" or snapshot.engine_started is False:
        return "ignored"
    if snapshot.live_status == "waiting":
        return "not_ended"
    if snapshot.turn_outcome == "cancelled":
        return "cancelled"
    if snapshot.turn_outcome == "failed":
        return "failed"
    outcome_completed = snapshot.turn_outcome == "completed" or (
        snapshot.turn_outcome is None and snapshot.saw_response_completed is True
    )
    if (
        snapshot.live_status == "idle"
        and snapshot.engine_stable_id_present is True
        and snapshot.newest_substantive_item_is_assistant is True
        and outcome_completed
        and snapshot.background_tasks == 0
        and snapshot.pending_elicitation_count == 0
        and snapshot.engine_pending_input is False
    ):
        return "completed"
    return "not_ended"
