"""Turn facts built from a status edge, the session's live state and its transcript. Pure."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from coral.engine.classify import classify_failure
from coral.engine.turn_end import evaluate
from coral.signals.turn_facts import (
    EDGE_LOST,
    MAX_EDGE_CODE_CHARS,
    MAX_EDGE_MESSAGE_CHARS,
    EdgeFacts,
    LiveFacts,
    TurnTranscript,
    build_turn_fact,
    edge_origin,
    edge_response_id,
)

SESSION = "s" * 32
SLOT = "implement||:0"
ENGINE_ID = "a" * 32
# The engine message's record time, in seconds; edges are in milliseconds.
SENT_AT_S = 1_700_000_000
AFTER_MS = SENT_AT_S * 1000 + 2_500

ENGINE_TURN = TurnTranscript(
    newest_input="engine",
    newest_engine_input_id=ENGINE_ID,
    newest_substantive_item_is_assistant=True,
    runner_item_after_engine_input=True,
    engine_pending_input=False,
)
IDLE = LiveFacts(status="idle", pending_elicitations=0, background_work=False)
FAILED = LiveFacts(status="failed", pending_elicitations=0, background_work=False)


def _edge(status: str = "idle", **fields: object) -> EdgeFacts:
    values: dict[str, object] = {
        "status": status,
        "observed_at_ms": AFTER_MS,
        "origin": "relayed_runner_status",
        "turn_outcome": "completed" if status == "idle" else "failed",
    }
    values.update(fields)
    return EdgeFacts(**values)  # type: ignore[arg-type]


def _fact(
    transcript: TurnTranscript = ENGINE_TURN,
    live: LiveFacts = IDLE,
    edge: EdgeFacts | None = None,
    *,
    sent_at_s: int | None = SENT_AT_S,
):
    return build_turn_fact(
        slot_id=SLOT,
        session_id=SESSION,
        generation=2,
        transcript=transcript,
        live=live,
        edge=edge,
        engine_stable_id_present=True,
        engine_input_at_s=sent_at_s,
    )


def test_an_engine_turn_that_completed_is_keyed_by_the_engine_message_that_started_it() -> None:
    with_edge = _fact(edge=_edge())
    without_edge = _fact()

    assert with_edge is not None and without_edge is not None
    assert evaluate(with_edge) == "completed"
    assert (with_edge.slot_id, with_edge.session_id, with_edge.generation) == (SLOT, SESSION, 2)
    assert (with_edge.origin, with_edge.engine_started) == ("engine", True)
    # The edge path and the re-gather build the same key for one engine-started turn.
    assert with_edge.response_id == without_edge.response_id == f"msg:{ENGINE_ID}"
    assert evaluate(without_edge) == "completed"


@pytest.mark.parametrize(
    ("transcript", "edge", "verdict"),
    [
        (replace(ENGINE_TURN, newest_input="user"), _edge(), "ignored"),
        (ENGINE_TURN, _edge(origin="archive_idle"), "ignored"),
        (ENGINE_TURN, _edge(turn_outcome="cancelled"), "cancelled"),
        (replace(ENGINE_TURN, newest_substantive_item_is_assistant=False), None, "not_ended"),
        (replace(ENGINE_TURN, engine_pending_input=True), _edge(), "not_ended"),
    ],
    ids=["user_typed", "archive", "cancelled", "no_reply_yet", "engine_input_queued"],
)
def test_turns_that_must_not_nudge(
    transcript: TurnTranscript, edge: EdgeFacts | None, verdict: str
) -> None:
    fact = _fact(transcript, edge=edge)

    assert fact is not None
    assert evaluate(fact) == verdict
    if verdict == "ignored":
        assert fact.origin in {"user", "archive"}


@pytest.mark.parametrize(
    "live",
    [
        LiveFacts(status="idle", pending_elicitations=1, background_work=False),
        LiveFacts(status="idle", pending_elicitations=0, background_work=True),
        LiveFacts(status="waiting", pending_elicitations=0, background_work=False),
        LiveFacts(status=None, pending_elicitations=0, background_work=False),
    ],
    ids=["elicitation", "background_work", "waiting", "status_unknown"],
)
def test_a_turn_still_waiting_on_something_has_not_ended(live: LiveFacts) -> None:
    fact = _fact(live=live, edge=_edge())

    assert fact is not None and evaluate(fact) == "not_ended"


def test_background_tasks_the_edge_reported_also_hold_the_turn_open() -> None:
    fact = _fact(edge=_edge(background_task_count=2))

    assert fact is not None
    assert (fact.background_tasks, evaluate(fact)) == (2, "not_ended")


@pytest.mark.parametrize(
    "transcript",
    [
        TurnTranscript(None, None, False, False, False),
        TurnTranscript("user", None, True, True, False),
    ],
    ids=["undecided_walk", "no_engine_input"],
)
def test_no_fact_is_built_without_the_engine_message_that_started_the_turn(
    transcript: TurnTranscript,
) -> None:
    assert _fact(transcript, edge=_edge()) is None
    assert _fact(transcript, live=FAILED) is None


@pytest.mark.parametrize(
    ("message", "code", "failure_class", "cause"),
    [
        ("API Error: 529 Overloaded", "RuntimeError", "infra.transient", "529"),
        ("API Error: 429 rate_limit_error: slow down", "RuntimeError", "plan.usage_limit", None),
        ("Claude Code is not logged in", "claude_sdk_auth_failed", "auth", None),
    ],
    ids=["529", "429", "401"],
)
def test_a_failed_edge_carries_its_error_to_the_classifier(
    message: str, code: str, failure_class: str, cause: str | None
) -> None:
    fact = _fact(live=FAILED, edge=_edge("failed", error_code=code, error_message=message))

    assert fact is not None and evaluate(fact) == "failed"
    failure = classify_failure(fact)
    assert failure.name == failure_class
    if cause is not None:
        assert failure.cause == cause
    # A fixed token, never the error text.
    assert message not in failure.cause


def test_a_failed_edge_without_an_outcome_still_reports_a_failed_turn() -> None:
    fact = _fact(live=IDLE, edge=_edge("failed", turn_outcome=None))

    assert fact is not None and evaluate(fact) == "failed"


def test_an_edge_older_than_the_engine_message_is_ignored() -> None:
    stale = _edge("failed", observed_at_ms=SENT_AT_S * 1000 - 1, error_code="RuntimeError")
    same_second = _edge("failed", observed_at_ms=SENT_AT_S * 1000, error_code="RuntimeError")

    gathered_without = _fact(edge=stale)
    current = _fact(live=IDLE, edge=same_second)
    unknown_send_time = _fact(edge=same_second, sent_at_s=None)

    # The previous turn's failure does not mark the turn the engine message started.
    assert gathered_without is not None and evaluate(gathered_without) == "completed"
    assert gathered_without.error_code is None
    # An edge in the engine message's own second counts as current.
    assert current is not None and evaluate(current) == "failed"
    assert unknown_send_time is not None and evaluate(unknown_send_time) == "completed"


def test_a_fact_from_a_current_edge_carries_when_the_edge_was_observed() -> None:
    from_edge = _fact(live=FAILED, edge=_edge("failed", error_code="RuntimeError"))
    without_edge = _fact(
        replace(ENGINE_TURN, newest_substantive_item_is_assistant=False), live=FAILED
    )

    # A runner loss reported after its wake's result is told apart by this time.
    assert from_edge is not None
    assert from_edge.observed_at == datetime.fromtimestamp(AFTER_MS / 1000, tz=UTC)
    assert without_edge is not None and without_edge.observed_at is None


def test_a_failed_turn_whose_edge_was_lost_is_a_transient_edge_lost_failure() -> None:
    fact = _fact(replace(ENGINE_TURN, newest_substantive_item_is_assistant=False), live=FAILED)

    assert fact is not None and evaluate(fact) == "failed"
    assert (fact.error_code, fact.error_text) == (EDGE_LOST, None)
    assert classify_failure(fact).name == "infra.transient"


@pytest.mark.parametrize("queued", [False, True], ids=["delivered", "still_queued"])
def test_a_lingering_failed_status_before_the_re_prompt_ran_builds_no_fact(queued: bool) -> None:
    # The re-prompt is the newest engine message and nothing of the runner follows it.
    reprompted = TurnTranscript(
        newest_input="engine",
        newest_engine_input_id="b" * 32,
        newest_substantive_item_is_assistant=False,
        runner_item_after_engine_input=False,
        engine_pending_input=queued,
    )

    assert _fact(reprompted, live=FAILED) is None
    # Once a runner item follows it, the failed status is this turn's.
    ran = _fact(replace(reprompted, runner_item_after_engine_input=True), live=FAILED)
    assert ran is not None and ran.error_code == EDGE_LOST


def test_a_completed_turn_whose_edge_was_lost_is_rebuilt_from_the_transcript() -> None:
    fact = _fact(live=IDLE)

    assert fact is not None and evaluate(fact) == "completed"
    assert (fact.turn_outcome, fact.saw_response_completed) == (None, True)


def test_edge_facts_are_bounded_and_round_trip_through_a_payload() -> None:
    astral = "\U0001f600" * 4_500
    edge = EdgeFacts.from_edge(
        {
            "status": "failed",
            "observed_at_ms": AFTER_MS,
            "origin": "relayed_runner_status",
            "turn_outcome": "failed",
            "turn_response_id": "resp_2",
            "response_id": "resp_1",
            "error_code": "E" * 400,
            # A lone surrogate cannot be stored as UTF-8.
            "error_message": "\ud800" + astral,
            "failure_origin": "relayed_runner_status",
            "background_task_count": 0,
            "turn_completed": True,
            "previous_status": "running",
        }
    )

    assert edge.error_message == astral[:MAX_EDGE_MESSAGE_CHARS]
    assert edge.error_code == "E" * MAX_EDGE_CODE_CHARS
    assert edge.response_id == "resp_2"
    assert (edge.turn_completed, edge.background_task_count) == (True, 0)
    payload = edge.payload()
    json.dumps(payload).encode()
    assert EdgeFacts.from_payload(json.loads(json.dumps(payload))) == edge


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"status": "idle"},
        {"status": "idle", "observed_at_ms": "soon"},
        {"status": "idle", "observed_at_ms": True},
        {"status": 3, "observed_at_ms": 1},
        {"status": "idle", "observed_at_ms": 1, "error_code": 7},
        {"status": "idle", "observed_at_ms": 1, "turn_completed": "yes"},
        {"status": "idle", "observed_at_ms": 1, "background_task_count": "2"},
        {"status": "idle", "observed_at_ms": 1, "error_message": "x" * 1_001},
        {"status": "i" * 129, "observed_at_ms": 1},
        {"status": "idle", "observed_at_ms": 1, "origin": "o" * 129},
    ],
)
def test_an_edge_payload_of_the_wrong_shape_is_refused(payload: object) -> None:
    with pytest.raises(ValueError):
        EdgeFacts.from_payload(payload)


def test_the_edge_helpers_prefer_the_reported_response_and_keep_archive_origins() -> None:
    assert edge_response_id({"turn_response_id": "r2", "response_id": "r1"}) == "r2"
    assert edge_response_id({"turn_response_id": "", "response_id": "r1"}) == "r1"
    assert edge_response_id({"response_id": 7}) is None
    assert edge_origin({"origin": "nightly-archive_idle"}) == "archive"
    assert edge_origin({"origin": "relay_turn_end"}) == "relay_turn_end"
    assert edge_origin({"origin": 3}) is None
    assert edge_origin({}) is None


BEYOND = TurnTranscript(None, None, True, True, False, beyond_reach=True)
LATEST = "c" * 32


@pytest.mark.parametrize(
    ("live", "edge", "expected"),
    [
        (IDLE, None, ("failed", "turn_unreadable")),
        (IDLE, _edge(), ("failed", "turn_unreadable")),
        (
            FAILED,
            _edge("failed", error_code="RuntimeError", error_message="API Error: 529 Overloaded"),
            ("failed", "RuntimeError"),
        ),
        (FAILED, None, ("failed", "edge_lost")),
        (IDLE, _edge(turn_outcome="cancelled"), ("cancelled", None)),
    ],
    ids=["idle", "completed_edge", "failed_edge", "failed_without_edge", "cancelled_edge"],
)
def test_a_turn_beyond_the_walks_reach_that_is_over_is_keyed_by_the_slots_latest_message(
    live: LiveFacts, edge: EdgeFacts | None, expected: tuple[str, str | None]
) -> None:
    fact = build_turn_fact(
        slot_id=SLOT,
        session_id=SESSION,
        generation=2,
        transcript=BEYOND,
        live=live,
        edge=edge,
        engine_stable_id_present=True,
        engine_input_at_s=SENT_AT_S,
        latest_engine_input_id=LATEST,
    )

    assert fact is not None
    assert (fact.turn_outcome, fact.error_code) == expected
    assert (fact.response_id, fact.origin, fact.engine_started) == (
        f"msg:{LATEST}",
        "engine",
        True,
    )
    if expected[0] == "failed":
        assert evaluate(fact) == "failed"
        assert classify_failure(fact).name == "infra.transient"


@pytest.mark.parametrize(
    ("live", "latest"),
    [
        (LiveFacts(status="running", pending_elicitations=0, background_work=False), LATEST),
        (LiveFacts(status="waiting", pending_elicitations=0, background_work=False), LATEST),
        (IDLE, None),
        (LiveFacts(status="idle", pending_elicitations=0, background_work=True), LATEST),
    ],
    ids=["still_running", "waiting", "no_engine_message_on_record", "background_work"],
)
def test_a_turn_beyond_reach_that_runs_or_has_no_message_builds_no_fact(
    live: LiveFacts, latest: str | None
) -> None:
    fact = build_turn_fact(
        slot_id=SLOT,
        session_id=SESSION,
        generation=2,
        transcript=BEYOND,
        live=live,
        edge=None,
        engine_stable_id_present=True,
        engine_input_at_s=SENT_AT_S,
        latest_engine_input_id=latest,
    )

    assert fact is None
