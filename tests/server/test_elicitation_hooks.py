# CORAL(S6a, S6b): request-free publish and stable-id verdict handler tests (new file).
"""Request-free elicitations and verdict handlers: prefix rules, publish, withdraw, no caller."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from omnigent.errors import ErrorCode, OmnigentError
from omnigent.runtime import pending_elicitations
from omnigent.server import elicitation_hooks
from omnigent.server.elicitation_hooks import (
    ElicitationVerdict,
    VerdictDecision,
    claimed_handler,
    publish_form_elicitation,
    register_elicitation_verdict_handler,
    resolve_claimed_elicitation,
    verdict_response,
    withdraw_elicitation,
)
from omnigent.server.routes import sessions as S
from omnigent.server.routes._sessions import orchestration

_SESSION = "conv_hooks"
_GATE_ID = "test_gate_0123456789abcdef"
_PARAMS = {"message": "Approve the change?", "requestedSchema": {"type": "object"}}


class _RecordingHandler:
    """A verdict handler that records each verdict and returns a fixed decision."""

    def __init__(self, decision: VerdictDecision | None = None) -> None:
        self.verdicts: list[ElicitationVerdict] = []
        self.decision = decision or VerdictDecision(accepted=True)

    async def __call__(self, verdict: ElicitationVerdict) -> VerdictDecision:
        self.verdicts.append(verdict)
        return self.decision


@pytest.fixture
def gate_handler() -> Iterator[_RecordingHandler]:
    """Claim ``test_gate_`` ids for one test."""
    handler = _RecordingHandler()
    uninstall = register_elicitation_verdict_handler("test_gate_", handler)
    yield handler
    uninstall()


@pytest.fixture
def published() -> Iterator[list[dict[str, Any]]]:
    """Record every request and resolved event that reaches the pending index."""
    events: list[dict[str, Any]] = []
    remove = pending_elicitations.add_elicitation_observer(
        lambda _conversation_id, event: events.append(event)
    )
    yield events
    remove()


@pytest.mark.parametrize(
    "prefix",
    ["gate", "Gate_", "_gate_", "9gate_", "gate-x_", "g" * 33 + "_", "elicit_", "elicit_more_"],
)
def test_register_refuses_a_malformed_or_reserved_prefix(prefix: str) -> None:
    with pytest.raises(ValueError):
        register_elicitation_verdict_handler(prefix, _RecordingHandler())
    assert claimed_handler(f"{prefix}x") is None


@pytest.mark.parametrize("prefix", ["test_gate_", "test_", "test_gate_extra_"])
def test_register_refuses_a_prefix_overlapping_a_registered_one(
    gate_handler: _RecordingHandler, prefix: str
) -> None:
    with pytest.raises(ValueError):
        register_elicitation_verdict_handler(prefix, _RecordingHandler())
    # The refused prefix claimed nothing; the registered one still claims its ids.
    assert claimed_handler("test_x") is None
    assert claimed_handler(_GATE_ID) is gate_handler


def test_claimed_handler_matches_only_registered_prefixes(gate_handler: _RecordingHandler) -> None:
    assert claimed_handler(_GATE_ID) is gate_handler
    assert claimed_handler("test_other_1") is None
    assert claimed_handler("elicit_0123") is None
    other = _RecordingHandler()
    uninstall_other = register_elicitation_verdict_handler("test_other_", other)
    try:
        assert claimed_handler("test_other_1") is other
    finally:
        uninstall_other()


def test_uninstaller_removes_only_its_own_registration() -> None:
    first = _RecordingHandler()
    uninstall_first = register_elicitation_verdict_handler("test_gate_", first)
    uninstall_first()
    uninstall_first()
    assert claimed_handler(_GATE_ID) is None

    # Registering the same handler again is a new registration: a stale
    # uninstaller leaves it alone.
    uninstall_again = register_elicitation_verdict_handler("test_gate_", first)
    try:
        uninstall_first()
        assert claimed_handler(_GATE_ID) is first
    finally:
        uninstall_again()
    assert claimed_handler(_GATE_ID) is None


async def test_publish_stores_the_prompt_and_withdraw_drops_it_once(
    gate_handler: _RecordingHandler, published: list[dict[str, Any]]
) -> None:
    await publish_form_elicitation(_SESSION, _PARAMS, elicitation_id=_GATE_ID)
    found = pending_elicitations.lookup(_GATE_ID, conversation_id=_SESSION)
    assert found is not None
    assert found[1]["params"]["message"] == "Approve the change?"

    assert withdraw_elicitation(_SESSION, _GATE_ID) is True
    assert pending_elicitations.count_for(_SESSION) == 0
    # A second withdraw finds nothing pending and publishes nothing.
    assert withdraw_elicitation(_SESSION, _GATE_ID) is False
    assert [(event["type"], event.get("action")) for event in published] == [
        ("response.elicitation_request", None),
        ("response.elicitation_resolved", None),
    ]


@pytest.mark.parametrize(
    "elicitation_id",
    ["test_other_1", "elicit_0123456789abcdef", "test_gate_has space", "test_gate_" + "x" * 60],
)
async def test_publish_refuses_an_unclaimed_reserved_or_malformed_id(
    gate_handler: _RecordingHandler, published: list[dict[str, Any]], elicitation_id: str
) -> None:
    with pytest.raises(ValueError):
        await publish_form_elicitation(_SESSION, _PARAMS, elicitation_id=elicitation_id)
    assert published == []


async def test_publish_refuses_params_that_do_not_validate(
    gate_handler: _RecordingHandler, published: list[dict[str, Any]]
) -> None:
    with pytest.raises(ValueError):
        await publish_form_elicitation(_SESSION, {"mode": "form"}, elicitation_id=_GATE_ID)
    assert published == []


def test_withdraw_refuses_an_unclaimed_id() -> None:
    with pytest.raises(ValueError):
        withdraw_elicitation(_SESSION, "elicit_0123456789abcdef")


async def test_resolve_without_a_named_caller_refuses_a_claimed_id(
    gate_handler: _RecordingHandler,
) -> None:
    await publish_form_elicitation(_SESSION, _PARAMS, elicitation_id=_GATE_ID)
    # The direct call names no caller, as the existing direct test calls do.
    decision = await S._resolve_elicitation(
        _SESSION, {"elicitation_id": _GATE_ID, "action": "accept"}, None
    )

    assert decision is not None
    assert (decision.accepted, decision.forbidden, decision.reason) == (False, True, "no_caller")
    assert gate_handler.verdicts == []
    assert pending_elicitations.count_for(_SESSION) == 1
    with pytest.raises(OmnigentError) as refused:
        verdict_response(decision)
    assert refused.value.code == ErrorCode.FORBIDDEN
    assert refused.value.message.startswith("[no_caller] ")


async def test_an_invalid_answer_is_refused_before_the_handler(
    gate_handler: _RecordingHandler,
) -> None:
    decision = await resolve_claimed_elicitation(
        _SESSION,
        {"elicitation_id": _GATE_ID, "action": "approve"},
        resolved_by=None,
    )

    assert decision is not None
    assert (decision.accepted, decision.forbidden, decision.reason) == (
        False,
        False,
        "invalid_answer",
    )
    assert gate_handler.verdicts == []


@pytest.mark.parametrize("elicitation_id", ["test_gate_has.dot", "test_gate_" + "x" * 60])
async def test_a_malformed_claimed_id_is_refused_before_the_handler(
    gate_handler: _RecordingHandler, elicitation_id: str
) -> None:
    gate_handler.decision = VerdictDecision(accepted=False, clear_pending=True)
    decision = await resolve_claimed_elicitation(
        _SESSION, {"elicitation_id": elicitation_id, "action": "accept"}, resolved_by=None
    )

    assert decision is not None
    assert (decision.accepted, decision.reason) == (False, "invalid_answer")
    assert gate_handler.verdicts == []
    with pytest.raises(OmnigentError) as refused:
        verdict_response(decision)
    assert refused.value.code == ErrorCode.CONFLICT


@pytest.mark.parametrize(
    "decision",
    [
        VerdictDecision(accepted=True, clear_pending=True),
        VerdictDecision(accepted=False, clear_pending=True, reason="stale_visit"),
    ],
)
async def test_a_handler_unregistered_while_it_runs_keeps_its_outcome(
    published: list[dict[str, Any]], decision: VerdictDecision
) -> None:
    """Teardown during an answer: the decision stands and the prompt is still dropped."""

    async def handler(_verdict: ElicitationVerdict) -> VerdictDecision:
        uninstall()
        return decision

    uninstall = register_elicitation_verdict_handler("test_gate_", handler)
    await publish_form_elicitation(_SESSION, _PARAMS, elicitation_id=_GATE_ID)
    returned = await resolve_claimed_elicitation(
        _SESSION, {"elicitation_id": _GATE_ID, "action": "accept"}, resolved_by=None
    )

    assert returned == decision
    assert claimed_handler(_GATE_ID) is None
    assert pending_elicitations.count_for(_SESSION) == 0
    expected_action = "accept" if decision.accepted else None
    assert [event.get("action") for event in published[1:]] == [expected_action]


async def test_a_claimed_answer_skips_the_tombstone_and_the_runner_forward(
    gate_handler: _RecordingHandler, monkeypatch: pytest.MonkeyPatch
) -> None:
    forwarded: list[str] = []

    async def record_forward(session_id: str, data: dict[str, Any], _router: Any) -> None:
        forwarded.append(data["elicitation_id"])

    monkeypatch.setattr(orchestration, "_forward_approval_to_runner", record_forward)
    for elicitation_id in (_GATE_ID, "elicit_0123456789abcdef"):
        await S._resolve_elicitation(
            _SESSION,
            {"elicitation_id": elicitation_id, "action": "accept"},
            None,
            resolved_by=None,
        )

    assert [verdict.elicitation_id for verdict in gate_handler.verdicts] == [_GATE_ID]
    assert forwarded == ["elicit_0123456789abcdef"]
    assert set(S._harness_pre_resolved_elicitations) == {"elicit_0123456789abcdef"}


async def test_a_raising_handler_publishes_nothing_and_keeps_the_prompt(
    published: list[dict[str, Any]],
) -> None:
    async def failing_handler(_verdict: ElicitationVerdict) -> VerdictDecision:
        raise RuntimeError("handler failed")

    uninstall = register_elicitation_verdict_handler("test_gate_", failing_handler)
    try:
        await publish_form_elicitation(_SESSION, _PARAMS, elicitation_id=_GATE_ID)
        with pytest.raises(RuntimeError, match="handler failed"):
            await resolve_claimed_elicitation(
                _SESSION,
                {"elicitation_id": _GATE_ID, "action": "accept"},
                resolved_by="alice@example.com",
            )
    finally:
        uninstall()

    assert [event["type"] for event in published] == ["response.elicitation_request"]
    assert pending_elicitations.count_for(_SESSION) == 1


async def test_publish_keeps_extra_params_and_nulls_unset_ones(
    gate_handler: _RecordingHandler,
) -> None:
    await publish_form_elicitation(
        _SESSION, {**_PARAMS, "coral": {"run_id": "run_1"}}, elicitation_id=_GATE_ID
    )

    found = pending_elicitations.lookup(_GATE_ID, conversation_id=_SESSION)
    assert found is not None
    params = found[1]["params"]
    assert (params["mode"], params["coral"], params["url"]) == ("form", {"run_id": "run_1"}, None)


async def test_an_unclaimed_id_is_left_to_the_existing_path(
    gate_handler: _RecordingHandler,
) -> None:
    decision = await resolve_claimed_elicitation(
        _SESSION,
        {"elicitation_id": "elicit_0123456789abcdef", "action": "accept"},
        resolved_by="alice@example.com",
    )
    assert decision is None
    assert gate_handler.verdicts == []


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (VerdictDecision(accepted=True), {"queued": False}),
        (VerdictDecision(accepted=True, duplicate=True), {"queued": False, "duplicate": True}),
    ],
)
def test_verdict_response_for_an_accepted_answer(
    decision: VerdictDecision, expected: dict[str, bool]
) -> None:
    assert verdict_response(decision) == expected


@pytest.mark.parametrize(
    ("forbidden", "code"), [(True, ErrorCode.FORBIDDEN), (False, ErrorCode.CONFLICT)]
)
def test_verdict_response_raises_a_refusal_with_its_reason(
    forbidden: bool, code: ErrorCode
) -> None:
    decision = VerdictDecision(
        accepted=False, forbidden=forbidden, reason="stale_visit", message="Too late."
    )
    with pytest.raises(OmnigentError) as refused:
        verdict_response(decision)
    assert refused.value.code == code
    assert refused.value.message == "[stale_visit] Too late."


def test_reset_for_tests_drops_every_handler() -> None:
    register_elicitation_verdict_handler("test_gate_", _RecordingHandler())
    elicitation_hooks.reset_for_tests()
    assert claimed_handler(_GATE_ID) is None
