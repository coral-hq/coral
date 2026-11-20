"""Gates on Omnigent: the caller as a Viewer, the verdict handler, prompt tracking, publishing."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from coral.gates.verdict import GateAnswer, GateAnswers, GateVerdict
from coral.omni.protocols import TrackedPrompt, Viewer
from coral.omni.server.access import viewer_for
from coral.omni.server.gates import (
    GateAnswering,
    LocalGatePrompts,
    OmnigentGatePublisher,
    gate_verdict_handler,
)
from omnigent.db.account_authority import account_authority_scope
from omnigent.db.db_models import workspace_scope
from omnigent.runtime import pending_elicitations, session_stream
from omnigent.server import elicitation_hooks
from omnigent.server.auth import UnifiedAuthProvider
from omnigent.server.elicitation_hooks import (
    ElicitationVerdict,
    VerdictDecision,
    register_elicitation_verdict_handler,
)
from omnigent.server.schemas import ElicitationResult

PROMPT = "coral_gate_" + "a" * 32
OTHER_PROMPT = "coral_gate_" + "b" * 32
WORKSPACE = 5
MULTI_USER = UnifiedAuthProvider(source="header", local_single_user=False)
SINGLE_USER = UnifiedAuthProvider(source="header", local_single_user=True)
PARAMS = {
    "mode": "form",
    "message": "Ship it?",
    "requestedSchema": {"type": "object", "properties": {}},
}


@pytest.fixture(autouse=True)
def clean_elicitations() -> Iterator[None]:
    yield
    pending_elicitations.reset_for_tests()
    elicitation_hooks.reset_for_tests()


async def _refuse_all(_verdict: ElicitationVerdict) -> VerdictDecision:
    return VerdictDecision(accepted=False, reason="no_longer_waiting", message="gone")


@pytest.mark.parametrize(
    ("user_id", "provider", "expected"),
    [
        (None, None, Viewer(user_id=None)),
        ("local", SINGLE_USER, Viewer(user_id=None)),
        (None, SINGLE_USER, Viewer(user_id=None)),
        (None, MULTI_USER, None),
        ("local", MULTI_USER, None),
        ("alice@example.com", MULTI_USER, Viewer(user_id="alice@example.com")),
    ],
    ids=[
        "auth_off",
        "single_user_local",
        "single_user_no_name",
        "identity_required_no_name",
        "identity_required_local",
        "header_user",
    ],
)
def test_a_caller_is_the_local_user_only_where_no_identity_is_required(
    user_id: str | None, provider: UnifiedAuthProvider | None, expected: Viewer | None
) -> None:
    assert viewer_for(user_id, provider) == expected


def test_an_account_caller_proves_its_generation_and_another_accounts_context_is_refused() -> None:
    with workspace_scope(WORKSPACE), account_authority_scope("alice@example.com", "gen-1"):
        proven = viewer_for("alice@example.com", MULTI_USER)
        wrong_context = viewer_for("bob@example.com", MULTI_USER)

    assert proven == Viewer(
        user_id="alice@example.com", account_generation="gen-1", check_generation=True
    )
    assert wrong_context is None


@dataclass
class FakeAnswers:
    """Records each answer and gives a fixed verdict."""

    verdict: GateVerdict
    answers: list[GateAnswer] = field(default_factory=list)

    async def answer(self, answer: GateAnswer) -> GateVerdict:
        self.answers.append(answer)
        return self.verdict


def _answering() -> GateAnswering:
    answering = GateAnswering()
    answering.enable()
    return answering


def _verdict(resolved_by: str | None, **result: Any) -> ElicitationVerdict:
    return ElicitationVerdict(
        session_id="anchor-1",
        elicitation_id=PROMPT,
        result=ElicitationResult.model_validate(result or {"action": "accept"}),
        resolved_by=resolved_by,
    )


async def test_the_handler_builds_the_viewer_in_the_callers_task_before_answering() -> None:
    answers = FakeAnswers(GateVerdict(status="accepted"))
    handler = gate_verdict_handler(cast(GateAnswers, answers), MULTI_USER, _answering())

    with workspace_scope(WORKSPACE), account_authority_scope("alice@example.com", "gen-1"):
        decision = await handler(
            _verdict(
                "alice@example.com",
                action="accept",
                content={"decision": "approve", "note": "ok"},
            )
        )

    assert decision == VerdictDecision(accepted=True)
    assert answers.answers == [
        GateAnswer(
            workspace_id=WORKSPACE,
            session_id="anchor-1",
            elicitation_id=PROMPT,
            action="accept",
            content={"decision": "approve", "note": "ok"},
            viewer=Viewer("alice@example.com", "gen-1", check_generation=True),
        )
    ]


async def test_a_caller_with_no_usable_identity_is_refused_without_an_answer() -> None:
    answers = FakeAnswers(GateVerdict(status="accepted"))

    decision = await gate_verdict_handler(cast(GateAnswers, answers), MULTI_USER, _answering())(
        _verdict(None)
    )

    assert decision == VerdictDecision(
        accepted=False,
        forbidden=True,
        reason="not_permitted",
        message="Only the run owner can answer this gate.",
    )
    assert answers.answers == []


@pytest.mark.parametrize(
    ("verdict", "decision"),
    [
        (GateVerdict(status="accepted"), VerdictDecision(accepted=True)),
        (
            GateVerdict(status="duplicate", clear_pending=True),
            VerdictDecision(accepted=True, duplicate=True, clear_pending=True),
        ),
        (
            GateVerdict(
                status="refused", reason="stale_visit", message="Asked again.", clear_pending=True
            ),
            VerdictDecision(
                accepted=False, clear_pending=True, reason="stale_visit", message="Asked again."
            ),
        ),
        (
            GateVerdict(status="refused", reason="not_permitted", message="Owner only."),
            VerdictDecision(
                accepted=False, forbidden=True, reason="not_permitted", message="Owner only."
            ),
        ),
        (
            GateVerdict(status="refused", reason="run_paused", message="Paused."),
            VerdictDecision(accepted=False, reason="run_paused", message="Paused."),
        ),
    ],
)
async def test_a_gate_verdict_maps_to_the_seams_decision(
    verdict: GateVerdict, decision: VerdictDecision
) -> None:
    handler = gate_verdict_handler(cast(GateAnswers, FakeAnswers(verdict)), None, _answering())

    assert await handler(_verdict(None)) == decision


async def test_an_answer_reaching_the_handler_while_gates_are_closed_is_retried() -> None:
    """Admitted just before the lifespan's exit: refused as retryable, never dropped."""
    answers = FakeAnswers(GateVerdict(status="accepted"))

    decision = await gate_verdict_handler(cast(GateAnswers, answers), None, GateAnswering())(
        _verdict(None)
    )

    assert decision == VerdictDecision(
        accepted=False,
        reason="run_busy",
        message="Coral is not taking gate answers right now; try again.",
    )
    assert answers.answers == []


def _tracker(limit: int = 10_000) -> LocalGatePrompts:
    tracker = LocalGatePrompts(limit=limit)
    pending_elicitations.add_elicitation_observer(tracker.observe)
    return tracker


async def test_the_tracker_follows_gate_prompts_published_and_withdrawn_in_their_workspace() -> (
    None
):
    register_elicitation_verdict_handler("coral_gate_", _refuse_all)
    tracker = _tracker()
    publisher = OmnigentGatePublisher()

    with workspace_scope(WORKSPACE):
        await publisher.publish(session_id="anchor-1", elicitation_id=PROMPT, params=PARAMS)
        # Re-publishing the same id tracks it once.
        await publisher.publish(session_id="anchor-1", elicitation_id=PROMPT, params=PARAMS)
        tracked = tracker.tracked()
        pending = tracker.is_pending(tracked[0])
        withdrawn = await publisher.withdraw(session_id="anchor-1", elicitation_id=PROMPT)
        again = await publisher.withdraw(session_id="anchor-1", elicitation_id=PROMPT)
    with workspace_scope(WORKSPACE + 1):
        elsewhere = tracker.is_pending(TrackedPrompt(WORKSPACE + 1, "anchor-1", PROMPT))

    assert tracked == [TrackedPrompt(WORKSPACE, "anchor-1", PROMPT)]
    assert (pending, withdrawn, again, elsewhere) == (True, True, False, False)
    assert tracker.tracked() == []


async def test_the_tracker_ignores_mirrored_and_other_prompts_and_tolerates_a_late_call() -> None:
    tracker = _tracker()
    mirrored = {
        "type": "response.elicitation_request",
        "elicitation_id": PROMPT,
        "params": {**PARAMS, "target_session_id": "step-1"},
    }
    with workspace_scope(WORKSPACE):
        session_stream.publish("anchor-1", mirrored)
        for elicitation_id in ("elicit_" + "c" * 32, "coral_gate_short", "coral_gate_" + "A" * 32):
            session_stream.publish(
                "anchor-1",
                {
                    "type": "response.elicitation_request",
                    "elicitation_id": elicitation_id,
                    "params": dict(PARAMS),
                },
            )
        # A call after the uninstaller returned, from a publish already under way.
        tracker.observe("anchor-1", {"type": "response.elicitation_resolved"})

    assert tracker.tracked() == []


async def test_a_prompt_resolved_without_an_event_is_still_tracked_but_not_pending() -> None:
    register_elicitation_verdict_handler("coral_gate_", _refuse_all)
    tracker = _tracker()
    with workspace_scope(WORKSPACE):
        await OmnigentGatePublisher().publish(
            session_id="anchor-1", elicitation_id=PROMPT, params=PARAMS
        )
        pending_elicitations.resolve("anchor-1", PROMPT)
        (prompt,) = tracker.tracked()
        assert not tracker.is_pending(prompt)
    tracker.forget(prompt)
    assert tracker.tracked() == []


async def test_the_tracker_keeps_its_newest_prompts_and_warns_once_when_full(
    caplog: pytest.LogCaptureFixture,
) -> None:
    register_elicitation_verdict_handler("coral_gate_", _refuse_all)
    tracker = _tracker(limit=2)
    prompts = [f"coral_gate_{index:032x}" for index in range(4)]

    with (
        caplog.at_level(logging.WARNING, logger="coral.omni.server.gates"),
        workspace_scope(WORKSPACE),
    ):
        for prompt in prompts:
            await OmnigentGatePublisher().publish(
                session_id="anchor-1", elicitation_id=prompt, params=PARAMS
            )

    assert [item.elicitation_id for item in tracker.tracked()] == prompts[2:]
    assert len([record for record in caplog.records if record.name.endswith("gates")]) == 1


def test_the_admission_flag_says_whether_gates_are_answered() -> None:
    answering = GateAnswering()
    seen = [answering()]
    answering.enable()
    seen.append(answering())
    answering.disable()
    seen.append(answering())
    assert seen == [False, True, False]
