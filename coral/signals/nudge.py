"""Whether a completed turn should emit a nudge. Pure. Does not send it."""

from __future__ import annotations

from coral.engine.facts import TurnSnapshot
from coral.engine.turn_end import evaluate

_NONE_SEEN: frozenset[str] = frozenset()


def decide(
    snapshot: TurnSnapshot,
    slot_status: str,
    *,
    fact_key: str,
    seen: frozenset[str] = _NONE_SEEN,
    taken_over: bool = False,
) -> bool:
    """True when this turn should nudge. The same arguments always return the same bool."""
    if evaluate(snapshot) != "completed":
        return False
    if snapshot.engine_started is not True:
        return False
    if snapshot.turn_outcome == "cancelled":
        return False
    if snapshot.origin in {"user", "archive"}:
        return False
    if slot_status in {"closing", "closed"}:
        return False
    if taken_over:
        return False
    return fact_key not in seen


def turn_ended_snapshot(origin: str) -> TurnSnapshot:
    """The completed turn ``TurnEnded`` stands in for.

    The command carries the fact key, the slot, and the origin, not the rest of the
    snapshot. Reconcile emits it only after ``evaluate`` returns ``completed``.
    """
    return TurnSnapshot(
        live_status="idle",
        engine_stable_id_present=True,
        newest_substantive_item_is_assistant=True,
        turn_outcome="completed",
        saw_response_completed=True,
        background_tasks=0,
        pending_elicitation_count=0,
        engine_pending_input=False,
        origin=origin,
        engine_started=True,
    )
