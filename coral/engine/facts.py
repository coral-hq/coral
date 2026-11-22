"""Turn facts the reducer can see. A missing fact is ``None`` and never raises."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class TurnSnapshot(BaseModel):
    """One observed turn. Every field is optional so a partial observation is ``None``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    live_status: str | None = None
    engine_stable_id_present: bool | None = None
    newest_substantive_item_is_assistant: bool | None = None
    turn_outcome: str | None = None
    saw_response_completed: bool | None = None
    background_tasks: int | None = None
    pending_elicitation_count: int | None = None
    engine_pending_input: bool | None = None
    origin: str | None = None
    engine_started: bool | None = None
    status_code: int | None = None
    error_text: str | None = None
    error_code: str | None = None
    failure_origin: str | None = None
    session_id: str | None = None
    generation: int | None = None
    response_id: str | None = None
    # Unix epoch seconds when a plan/usage limit lifts, when the harness reported one.
    resets_at: float | None = None


class TurnFact(TurnSnapshot):
    """A snapshot plus the slot it belongs to and when its runner was last seen.

    ``runner_id`` names the runner incarnation the fact is about, so a loss is keyed by it.
    """

    slot_id: str
    runner_last_seen: datetime | None = None
    runner_id: str | None = None
    # When the edge the fact came from was observed.
    observed_at: datetime | None = None

    @field_validator("runner_last_seen", "observed_at")
    @classmethod
    def _aware_runner(cls, value: datetime | None) -> datetime | None:
        _require_aware_runner(value)
        return value


def _require_aware_runner(value: datetime | None) -> None:
    """Reject a naive timestamp the same way ``transition`` rejects a naive ``now``."""
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("fact timestamps must be timezone-aware")


def turn_key_generation(fact_key: str) -> int | None:
    """Generation in ``turn:{session}:{generation}:{tail}``.

    The tail may contain colons. A key of another shape, or a generation that is
    not an integer, is ``None``.
    """
    prefix = "turn:"
    if not fact_key.startswith(prefix):
        return None
    parts = fact_key[len(prefix) :].split(":", 2)
    if len(parts) != 3:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def turn_key_tail(fact_key: str | None) -> str:
    """Tail of ``turn:{session}:{generation}:{tail}``, or ``"None"`` for another shape."""
    if fact_key is None or not fact_key.startswith("turn:"):
        return "None"
    parts = fact_key[len("turn:") :].split(":", 2)
    return parts[2] if len(parts) == 3 else "None"


def runner_loss_key(
    session_id: str,
    generation: int,
    runner_id: str | None,
    fact_key: str | None,
    epoch: int,
) -> str:
    """One key per outage of a runner: ``runner:{session}:{generation}:{runner_id}:{epoch}``.

    ``epoch`` is the slot's ``connection_epoch``. Without a runner id the key falls back
    to the turn's response tail, ``runner:{session}:{generation}:turn:{tail}:{epoch}``.
    """
    runner = runner_id if runner_id else f"turn:{turn_key_tail(fact_key)}"
    return f"runner:{session_id}:{generation}:{runner}:{epoch}"


def previous_runner_loss_key(session_id: str, generation: int) -> str:
    """The loss key of the previous rules: one per session generation."""
    return f"runner:{session_id}:{generation}"
