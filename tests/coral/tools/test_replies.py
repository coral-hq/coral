"""Engine tool replies: the JSON envelope and how engine rejections become replies."""

from __future__ import annotations

import typing

import pytest

from coral.engine import transition
from coral.engine.types import (
    RULES,
    ChooseArrow,
    EffectCompleted,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    PauseRun,
    Rejection,
    RejectionObserved,
    RunState,
    StartRun,
    TurnEnded,
)
from coral.tools.catalog import CHOOSE_ARROW, SUBMIT_HANDOFF
from coral.tools.port import EngineRefused
from coral.tools.replies import (
    RETRY_SHORTLY,
    STOP,
    reply_for_engine_rejection,
    stop_paused,
)
from coral.tools.schemas import REASONS, LoopUse, ToolReply
from tests.coral.engine.drive import NOW, drive
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    start,
    step,
    workflow_text,
)

SUBMIT = SUBMIT_HANDOFF.name
CHOOSE = CHOOSE_ARROW.name
# Every reducer input kind: none of them may reach an agent as an allowed value.
INPUT_KINDS = frozenset(
    typing.get_args(member.model_fields["kind"].annotation)[0]
    for member in typing.get_args(typing.get_args(Input)[0])
)


def test_reply_json_has_sorted_keys_and_only_the_fields_set() -> None:
    accepted = ToolReply(accepted=True, next="Stop.")
    assert (
        accepted.to_json() == '{"accepted":true,"allowed_values":[],"next":"Stop.","reason":null}'
    )

    refused = ToolReply(
        accepted=False,
        reason="handoff.invalid",
        allowed_values=("ok", "broken"),
        next="Fix label.",
        field="label",
        message="choose one",
    )
    assert refused.to_json() == (
        '{"accepted":false,"allowed_values":["ok","broken"],"field":"label",'
        '"message":"choose one","next":"Fix label.","reason":"handoff.invalid"}'
    )

    chosen = ToolReply(
        accepted=True,
        next="ship",
        duplicate=True,
        loop=LoopUse(used=2, limit=None),
        redirected=True,
    )
    assert chosen.to_json() == (
        '{"accepted":true,"allowed_values":[],"duplicate":true,'
        '"loop":{"limit":null,"used":2},"next":"ship","reason":null,"redirected":true}'
    )
    for reply in (accepted, refused, chosen):
        assert ToolReply.from_json(reply.to_json()) == reply


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        '{"accepted":true,"allowed_values":[],"next":""}',
        '{"accepted":true,"allowed_values":[],"next":"","reason":null,"extra":1}',
        '{"accepted":1,"allowed_values":[],"next":"","reason":null}',
        '{"accepted":false,"allowed_values":[],"next":"","reason":"made_up"}',
        '{"accepted":true,"allowed_values":[1],"next":"","reason":null}',
        '{"accepted":true,"allowed_values":[],"next":"","reason":null,"loop":{"used":true,"limit":1}}',
    ],
)
def test_text_that_is_not_a_reply_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        ToolReply.from_json(text)


def test_a_reply_states_its_reason_exactly_when_refused() -> None:
    with pytest.raises(ValueError):
        ToolReply(accepted=True, reason="slot_closed")
    with pytest.raises(ValueError):
        ToolReply(accepted=False)
    with pytest.raises(ValueError):
        ToolReply(accepted=False, reason="rejected")


@pytest.mark.parametrize(
    ("tool", "code", "reason", "next_text"),
    [
        (SUBMIT, "slot.superseded", "slot.superseded", None),
        (SUBMIT, "slot.closed", "slot_closed", None),
        (SUBMIT, "run_paused", "run.paused", stop_paused(None)),
        # An orchestrator has no step to resume.
        (CHOOSE, "run_paused", "run.paused", "The run is paused. Stop now and end your turn."),
        (SUBMIT, "run_cancelled", "run_cancelled", None),
        (SUBMIT, "run_terminal", "slot_closed", None),
        (CHOOSE, "run_terminal", "decision_closed", None),
        (SUBMIT, "evaluation_in_progress", "evaluation_in_progress", None),
        (SUBMIT, "slot.not_ready", "evaluation_in_progress", RETRY_SHORTLY),
        (CHOOSE, "decision_closed", "decision_closed", None),
    ],
)
def test_engine_codes_map_to_reasons_without_values(
    tool: str, code: str, reason: str, next_text: str | None
) -> None:
    reply = reply_for_engine_rejection(
        tool, Rejection(code=code, allowed_values=("effect_completed", "pause_run"))
    )
    assert (reply.accepted, reply.reason, reply.allowed_values) == (False, reason, ())
    assert reply.next
    if next_text is not None:
        assert reply.next == next_text


@pytest.mark.parametrize(("tool", "code"), [(SUBMIT, "handoff.invalid"), (CHOOSE, "tool.illegal")])
def test_label_refusals_keep_the_labels(tool: str, code: str) -> None:
    reply = reply_for_engine_rejection(tool, Rejection(code=code, allowed_values=("ok", "broken")))
    assert (reply.reason, reply.field, reply.allowed_values) == (code, "label", ("ok", "broken"))


@pytest.mark.parametrize("code", ["rejected", "resume_not_allowed", "not_supported", ""])
def test_other_engine_codes_are_transport_faults(code: str) -> None:
    with pytest.raises(EngineRefused) as refused:
        reply_for_engine_rejection(SUBMIT, Rejection(code=code, allowed_values=("pause_run",)))
    assert refused.value.code == code


def _rejections() -> list[Rejection]:
    """Real reducer rejections, including generic ``rejected`` ones that list input kinds."""
    graph = compile_text(
        workflow_text(
            [start(), step("work"), decision("choose"), step("ship"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "choose"),
                arrow("a3", "choose", "ship", label="yes"),
                arrow("a4", "choose", "end", label="no"),
                arrow("a5", "ship", "end"),
            ],
        )
    )[0]
    run = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1", rules=RULES)
    working = drive(graph, [run]).state
    pending = drive(graph, [run], auto_ack=False).state
    evaluating = drive(graph, [run, HandoffReceived(slot_id="work||:0", body="b")]).state
    paused = drive(graph, [run, PauseRun(reason="user", detail="")]).state
    attempts: list[tuple[RunState, Input]] = [
        (working, HandoffEvaluated(slot_id="work||:0", outcome="accepted")),
        (working, HandoffReceived(slot_id="work||:0", body="b", session_generation=0)),
        (working, HandoffReceived(slot_id="nope", body="b")),
        (working, HandoffReceived(slot_id="work||:0", body="b", label="yes")),
        (working, ChooseArrow(node_id="nope", label="x", reason="r")),
        (working, RejectionObserved(slot_id="nope", code="handoff.invalid")),
        (pending, HandoffReceived(slot_id="work||:0", body="b")),
        (evaluating, HandoffReceived(slot_id="work||:0", body="b")),
        (evaluating, TurnEnded(slot_id="work||:0", fact_key="turn:s:1:r")),
        (paused, HandoffReceived(slot_id="work||:0", body="b")),
        (paused, RejectionObserved(slot_id="work||:0", code="handoff.invalid")),
        (working, EffectCompleted(effect_key="nope")),
    ]
    found: list[Rejection] = []
    for state, item in attempts:
        entry = transition(graph, state, item, NOW).entry
        assert entry.rejection is not None, item
        found.append(entry.rejection)
    return found


def test_reducer_input_kinds_never_reach_allowed_values() -> None:
    rejections = _rejections()
    # The reducer does list input kinds on generic refusals; they must stop here.
    assert any(INPUT_KINDS & set(item.allowed_values) for item in rejections)
    for rejection in rejections:
        for tool in (SUBMIT, CHOOSE):
            try:
                reply = reply_for_engine_rejection(tool, rejection)
            except EngineRefused:
                continue
            assert not INPUT_KINDS & set(reply.allowed_values), rejection
            if rejection.code not in {"handoff.invalid", "tool.illegal"}:
                assert reply.allowed_values == ()
            assert reply.reason in REASONS


def test_stop_texts_never_invite_a_handoff() -> None:
    assert "Stop now and end your turn" in STOP
    assert stop_paused("budget") == (
        "The run is paused (budget). Stop now and end your turn; Coral resumes this step "
        "when the run resumes."
    )
    for code in ("run_paused", "run_cancelled", "run_terminal", "slot.closed", "slot.superseded"):
        reply = reply_for_engine_rejection(SUBMIT, Rejection(code=code))
        assert "Stop now and end your turn" in reply.next
        for text in (reply.next, reply.message or ""):
            assert "coral_submit_handoff" not in text
            assert "hand off" not in text.casefold()
