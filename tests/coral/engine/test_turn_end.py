"""Turn-end rule. A missing fact is not_ended and does not raise."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from coral.engine.facts import TurnFact, TurnSnapshot
from coral.engine.turn_end import evaluate
from tests.coral.engine.drive import NOW

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


def _snapshot(**overrides: object) -> TurnSnapshot:
    payload: dict[str, object] = {
        "live_status": "idle",
        "engine_stable_id_present": True,
        "newest_substantive_item_is_assistant": True,
        "turn_outcome": "completed",
        "saw_response_completed": True,
        "background_tasks": 0,
        "pending_elicitation_count": 0,
        "engine_pending_input": False,
        "origin": "engine",
        "engine_started": True,
    }
    payload.update(overrides)
    return TurnSnapshot.model_validate(payload)


def test_a_complete_turn_is_completed() -> None:
    assert evaluate(_snapshot()) == "completed"
    completed = _snapshot(turn_outcome="completed", saw_response_completed=False)
    assert evaluate(completed) == "completed"
    assert evaluate(_snapshot(origin="user")) == "completed"


def test_absent_outcome_with_response_completed_is_completed() -> None:
    assert evaluate(_snapshot(turn_outcome=None, saw_response_completed=True)) == "completed"


@pytest.mark.parametrize("field", _REQUIRED)
def test_a_missing_required_fact_is_not_ended(field: str) -> None:
    assert evaluate(_snapshot(**{field: None})) == "not_ended"


def test_a_missing_fact_beats_archive_and_does_not_raise() -> None:
    assert evaluate(_snapshot(origin="archive", engine_started=None)) == "not_ended"


def test_archive_and_a_stopped_engine_are_ignored() -> None:
    assert evaluate(_snapshot(origin="archive", turn_outcome="failed")) == "ignored"
    assert evaluate(_snapshot(engine_started=False, turn_outcome="cancelled")) == "ignored"
    assert evaluate(_snapshot(origin="user", engine_started=False)) == "ignored"


def test_waiting_is_not_ended_even_when_the_turn_looks_complete() -> None:
    assert evaluate(_snapshot(live_status="waiting")) == "not_ended"
    assert evaluate(_snapshot(live_status="waiting", turn_outcome="cancelled")) == "not_ended"
    assert evaluate(_snapshot(live_status="waiting", turn_outcome="failed")) == "not_ended"


def test_cancelled_and_failed_outcomes() -> None:
    assert evaluate(_snapshot(turn_outcome="cancelled")) == "cancelled"
    assert evaluate(_snapshot(turn_outcome="failed")) == "failed"


def test_idle_without_a_completed_response_is_not_ended() -> None:
    assert evaluate(_snapshot(turn_outcome=None, saw_response_completed=False)) == "not_ended"
    bare = TurnSnapshot(live_status="idle")
    assert evaluate(bare) == "not_ended"


@pytest.mark.parametrize(
    "overrides",
    [
        {"live_status": "running"},
        {"engine_stable_id_present": False},
        {"newest_substantive_item_is_assistant": False},
        {"background_tasks": 1},
        {"pending_elicitation_count": 1},
        {"engine_pending_input": True},
        {"turn_outcome": "running"},
    ],
)
def test_incomplete_idle_is_not_ended(overrides: dict[str, object]) -> None:
    assert evaluate(_snapshot(**overrides)) == "not_ended"


def test_a_naive_runner_timestamp_raises() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TurnFact(slot_id="work||:0", runner_last_seen=_naive())
    seen = TurnFact(slot_id="work||:0", runner_last_seen=NOW)
    assert seen.runner_last_seen == NOW
    assert TurnFact(slot_id="work||:0").runner_last_seen is None


def _naive() -> datetime:
    """A timestamp with no timezone, built from an aware value so the call itself stays aware."""
    return datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)
