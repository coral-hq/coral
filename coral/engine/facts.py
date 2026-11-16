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


class TurnFact(TurnSnapshot):
    """A snapshot plus the slot it belongs to and when its runner was last seen."""

    slot_id: str
    runner_last_seen: datetime | None = None

    @field_validator("runner_last_seen")
    @classmethod
    def _aware_runner(cls, value: datetime | None) -> datetime | None:
        _require_aware_runner(value)
        return value


def _require_aware_runner(value: datetime | None) -> None:
    """Reject a naive timestamp the same way ``transition`` rejects a naive ``now``."""
    if value is None:
        return
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("runner_last_seen must be timezone-aware")


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
