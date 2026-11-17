"""Decisions, gate tokens, attempt consumption, and drift on a closed slot."""

from __future__ import annotations

from coral.engine import fold, transition
from coral.engine.types import (
    AnswerGate,
    AttemptCount,
    ChooseArrow,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    PauseCause,
    PostCloseActivity,
    Rejection,
    StartRun,
    activation_id,
)
from coral.model.ir import CompiledGraph
from tests.coral.engine.drive import NOW, drive
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    fixture_text,
    gate,
    start,
    step,
    workflow_text,
)

CONFIG = EngineConfig()
RUN = StartRun(run_id="run-1", start_key="start-1", version_hash="hash-1")
SLOT = "work||:0"


def _graph(text: str) -> CompiledGraph:
    graph = compile_text(text)[0]
    assert not graph.analysis.unresolved
    return graph


def _decision_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), decision("choose"), end()],
            [
                arrow("a1", "start", "choose"),
                arrow("a2", "choose", "end", label="approved"),
                arrow("a3", "choose", "end", label="rejected"),
            ],
        )
    )


def _gate_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), gate("hold", outcomes=["approve", "again"]), end()],
            [
                arrow("a1", "start", "hold"),
                arrow("a2", "hold", "end", label="approve"),
                arrow("a3", "hold", "hold", label="again", back=True, limit=3, at_limit="a2"),
            ],
        )
    )


def _attempt_graph() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), step("work", attempts=2), step("bail"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "end"),
                arrow("a3", "work", "bail", label="failure"),
            ],
        )
    )


def _step_then_decision() -> CompiledGraph:
    return _graph(
        workflow_text(
            [start(), step("work"), decision("choose"), end()],
            [
                arrow("a1", "start", "work"),
                arrow("a2", "work", "choose"),
                arrow("a3", "choose", "end", label="approved"),
            ],
        )
    )


def test_illegal_decision_label_lists_allowed_labels() -> None:
    graph = _decision_graph()
    opened = drive(graph, [RUN], config=CONFIG)
    result = transition(
        graph,
        opened.state,
        ChooseArrow(node_id="choose", label="nope", reason="because"),
        NOW,
        CONFIG,
    )
    assert result.state == opened.state
    assert result.entry.rejection is not None
    assert result.entry.rejection.code == "tool.illegal"
    assert result.entry.rejection.allowed_values == ("approved", "rejected")
    assert result.entry.effects == ()
    assert fold(graph, (*opened.log, result.entry), CONFIG) == opened.state


def test_empty_decision_reason_is_illegal() -> None:
    graph = _decision_graph()
    opened = drive(graph, [RUN], config=CONFIG)
    result = transition(
        graph,
        opened.state,
        ChooseArrow(node_id="choose", label="approved", reason=""),
        NOW,
        CONFIG,
    )
    assert result.state == opened.state
    assert result.entry.rejection is not None
    assert result.entry.rejection.code == "tool.illegal"
    assert result.entry.rejection.allowed_values == ("approved", "rejected")
    assert fold(graph, (*opened.log, result.entry), CONFIG) == opened.state


def test_choice_after_decision_is_decision_closed() -> None:
    into_steps = _graph(
        workflow_text(
            [start(), decision("choose"), step("work"), step("other"), end()],
            [
                arrow("a1", "start", "choose"),
                arrow("a2", "choose", "work", label="approved"),
                arrow("a3", "choose", "other", label="rejected"),
                arrow("a4", "work", "end"),
                arrow("a5", "other", "end"),
            ],
        )
    )
    approve = ChooseArrow(node_id="choose", label="approved", reason="ship it")
    for graph, status in ((into_steps, "running"), (_decision_graph(), "completed")):
        decided = drive(graph, [RUN, approve], config=CONFIG)
        assert decided.state.status == status
        other = transition(
            graph,
            decided.state,
            ChooseArrow(node_id="choose", label="rejected", reason="changed my mind"),
            NOW,
            CONFIG,
        )
        assert other.entry.rejection == Rejection(code="decision_closed")
        assert other.entry.effects == ()
        assert other.state == decided.state
        same = transition(
            graph,
            decided.state,
            ChooseArrow(node_id="choose", label="approved", reason="again"),
            NOW,
            CONFIG,
        )
        assert same.entry.rejection is None
        assert same.entry.receipt_key == "choice:choose||:approved"
        assert same.state == decided.state
        assert fold(graph, (*decided.log, other.entry, same.entry), CONFIG) == decided.state


def test_choice_and_skip_receipts_keep_their_keys_and_payloads() -> None:
    graph = _graph(fixture_text("loop"))

    def work(iteration: str) -> list[HandoffReceived | HandoffEvaluated]:
        slot = f"{activation_id('work', (), (iteration,))}:0"
        return [
            HandoffReceived(slot_id=slot, body="done"),
            HandoffEvaluated(slot_id=slot, outcome="accepted"),
        ]

    def revise(iteration: str, reason: str) -> ChooseArrow:
        return ChooseArrow(
            node_id="review", label="revise", reason=reason, iteration_path=(iteration,)
        )

    driven = drive(
        graph,
        [
            RUN,
            *work("a4:1"),
            revise("a4:1", "once"),
            *work("a4:2"),
            revise("a4:2", "twice"),
            *work("a4:3"),
            revise("a4:3", "third"),
        ],
        config=CONFIG,
    )
    choice_receipts = [
        (item.key, item.payload)
        for item in driven.state.receipts
        if item.key.startswith(("choice:", "skipped:", "loop:"))
    ]
    skipped = {"code": "arrow.skipped", "arrow_id": "a3"}
    assert choice_receipts == [
        ("skipped:review||a4:1:a3", skipped),
        (
            "choice:review||a4:1:revise",
            {"label": "revise", "reason": "once", "code": "decision.made"},
        ),
        ("skipped:review||a4:2:a3", skipped),
        (
            "choice:review||a4:2:revise",
            {"label": "revise", "reason": "twice", "code": "decision.made"},
        ),
        ("loop:a4||", {"code": "loop.limit_reached", "redirected": True, "decision.made": True}),
        ("skipped:review||a4:3:a3", skipped),
        (
            "choice:review||a4:3:revise",
            {
                "label": "revise",
                "reason": "third",
                "code": "loop.limit_reached",
                "redirected": True,
                "decision.made": True,
            },
        ),
    ]
    chosen = [entry for entry in driven.log if isinstance(entry.input, ChooseArrow)]
    assert [
        (entry.receipt_key, [effect.kind for effect in entry.effects]) for entry in chosen
    ] == [
        ("choice:review||a4:1:revise", ["create_session"]),
        ("choice:review||a4:2:revise", ["create_session"]),
        ("choice:review||a4:3:revise", []),
    ]


def test_legal_decision_reaches_end_and_fold_matches() -> None:
    graph = _decision_graph()
    driven = drive(
        graph,
        [RUN, ChooseArrow(node_id="choose", label="approved", reason="ship it")],
        config=CONFIG,
    )
    assert driven.state.status == "completed"
    assert any(
        item.node_id == "end" and item.status == "closed" for item in driven.state.activations
    )
    chosen = driven.state.decisions[0]
    assert chosen.status == "decided"
    assert chosen.label == "approved"
    assert chosen.reason == "ship it"
    assert fold(graph, driven.log, CONFIG) == driven.state


def test_gate_answer_resolves_and_duplicate_returns_receipt() -> None:
    graph = _gate_graph()
    opened = drive(graph, [RUN], config=CONFIG)
    visit = opened.state.gates[0]
    assert visit.status == "open"
    assert visit.visit_no == 1
    assert visit.token == f"{visit.activation_id}:1"
    assert [effect.kind for effect in opened.log[0].effects] == ["publish_gate"]
    assert opened.log[0].effects[0].subject == visit.token

    answer = AnswerGate(token=visit.token, label="approve", by="sam", note="ok")
    answered = transition(graph, opened.state, answer, NOW, CONFIG)
    assert answered.entry.rejection is None
    assert answered.entry.effects == ()
    assert answered.state.status == "completed"
    resolved = next(item for item in answered.state.gates if item.token == visit.token)
    assert resolved.status == "resolved"
    assert resolved.label == "approve"
    assert answered.entry.receipt_key == visit.token

    duplicate = transition(
        graph,
        answered.state,
        AnswerGate(token=visit.token, label="approve", by="other", note="again"),
        NOW,
        CONFIG,
    )
    assert duplicate.state == answered.state
    assert duplicate.entry.effects == ()
    assert duplicate.entry.patch == ()
    assert duplicate.entry.rejection is None
    assert duplicate.entry.receipt_key == answered.entry.receipt_key
    stored = [item for item in duplicate.state.receipts if item.key == visit.token]
    assert len(stored) == 1
    assert fold(graph, (*opened.log, answered.entry, duplicate.entry), CONFIG) == answered.state


def test_second_gate_opening_makes_the_old_token_stale() -> None:
    graph = _gate_graph()
    opened = drive(graph, [RUN], config=CONFIG)
    token = opened.state.gates[0].token
    revisited = transition(
        graph,
        opened.state,
        AnswerGate(token=token, label="again", by="sam", note="loop"),
        NOW,
        CONFIG,
    )
    assert revisited.entry.rejection is None
    assert revisited.state.status == "running"
    assert [effect.kind for effect in revisited.entry.effects] == ["withdraw_gate", "publish_gate"]
    old = next(item for item in revisited.state.gates if item.token == token)
    assert old.status == "superseded"
    fresh = next(item for item in revisited.state.gates if item.status == "open")
    assert fresh.visit_no == 2
    assert fresh.token != token
    assert any(
        item.node_id == "hold" and item.status == "running" for item in revisited.state.activations
    )

    stale = transition(
        graph,
        revisited.state,
        AnswerGate(token=token, label="again", by="sam", note="late"),
        NOW,
        CONFIG,
    )
    assert stale.state == revisited.state
    assert stale.entry.effects == ()
    assert stale.entry.rejection is not None
    assert stale.entry.rejection.code == "gate.stale"
    assert fold(graph, (*opened.log, revisited.entry, stale.entry), CONFIG) == revisited.state


def test_evidence_missing_below_cap_returns_to_working() -> None:
    graph = _attempt_graph()
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="partial"),
            HandoffEvaluated(slot_id=SLOT, outcome="evidence_missing", missing=("spec",)),
        ],
        config=CONFIG,
    )
    assert driven.state.status == "running"
    assert driven.state.slots[0].status == "working"
    assert driven.state.attempts == (AttemptCount(activation_id="work||", used=1),)
    entry = driven.log[-1]
    assert entry.rejection is None
    assert entry.effects == ()
    assert isinstance(entry.input, HandoffEvaluated)
    assert entry.input.missing == ("spec",)
    assert all(effect.kind != "close_slot" for effect in driven.state.effects)
    work = next(item for item in driven.state.activations if item.node_id == "work")
    assert work.status == "running"
    assert fold(graph, driven.log, CONFIG) == driven.state


def test_evidence_missing_at_cap_follows_the_failure_arrow() -> None:
    graph = _attempt_graph()
    missing = HandoffEvaluated(slot_id=SLOT, outcome="evidence_missing", missing=("spec",))
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="partial"),
            missing,
            HandoffReceived(slot_id=SLOT, body="still partial"),
            missing,
        ],
        config=CONFIG,
    )
    assert driven.state.status == "running"
    assert driven.state.causes == ()
    assert driven.state.attempts == (AttemptCount(activation_id="work||", used=2),)
    work = next(item for item in driven.state.activations if item.node_id == "work")
    assert work.status == "closed"
    assert work.outcome == "failed"
    bail = next(item for item in driven.state.activations if item.node_id == "bail")
    assert bail.status != "closed"
    assert all(item.node_id != "end" for item in driven.state.activations)
    assert driven.state.slots[0].status == "closed"
    closes = [
        effect
        for entry in driven.log
        if entry.rejection is None
        for effect in entry.effects
        if effect.kind == "close_slot" and effect.subject == SLOT
    ]
    assert len(closes) == 1
    assert closes[0].payload == {"interrupt": True, "closed_label": True}
    assert fold(graph, driven.log, CONFIG) == driven.state


def test_evidence_missing_at_cap_pauses_when_failure_arrow_is_absent() -> None:
    graph = _graph(
        workflow_text(
            [start(), step("work", attempts=2), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )
    missing = HandoffEvaluated(slot_id=SLOT, outcome="evidence_missing", missing=("spec", "tests"))
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="partial"),
            missing,
            HandoffReceived(slot_id=SLOT, body="still partial"),
            missing,
        ],
        config=CONFIG,
    )
    assert driven.state.status == "paused"
    assert driven.state.causes == (
        PauseCause(reason="failure_path", detail="attempts_exhausted", subject="spec, tests"),
    )
    assert driven.state.attempts == (AttemptCount(activation_id="work||", used=2),)
    assert driven.state.slots[0].status == "evaluating"
    assert driven.log[-1].effects == ()
    assert all(effect.kind != "close_slot" for effect in driven.state.effects)
    assert fold(graph, driven.log, CONFIG) == driven.state
    again = transition(graph, driven.state, missing, NOW, CONFIG)
    assert again.state == driven.state
    assert again.entry.rejection is not None
    assert again.entry.rejection.code == "run_paused"
    assert again.state.attempts == (AttemptCount(activation_id="work||", used=2),)


def test_closed_slot_handoff_does_not_change_attempts() -> None:
    graph = _step_then_decision()
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="shipped"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        config=CONFIG,
    )
    assert driven.state.status == "running"
    assert driven.state.slots[0].status == "closed"
    assert driven.state.attempts == ()
    for command in (
        HandoffReceived(slot_id=SLOT, body="late"),
        HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        HandoffEvaluated(slot_id=SLOT, outcome="evidence_missing", missing=("spec",)),
    ):
        result = transition(graph, driven.state, command, NOW, CONFIG)
        assert result.state == driven.state
        assert result.entry.rejection is not None
        assert result.entry.rejection.code == "slot.closed"
        assert result.state.attempts == ()


def test_older_session_generation_does_not_spend_an_attempt() -> None:
    graph = _attempt_graph()
    working = drive(graph, [RUN], config=CONFIG)
    stale_handoff = transition(
        graph,
        working.state,
        HandoffReceived(slot_id=SLOT, body="old", session_generation=0),
        NOW,
        CONFIG,
    )
    assert stale_handoff.state == working.state
    assert stale_handoff.entry.rejection is not None
    assert stale_handoff.entry.rejection.code == "slot.superseded"
    assert stale_handoff.state.attempts == ()

    evaluating = drive(graph, [RUN, HandoffReceived(slot_id=SLOT, body="partial")], config=CONFIG)
    stale_eval = transition(
        graph,
        evaluating.state,
        HandoffEvaluated(
            slot_id=SLOT, outcome="evidence_missing", missing=("spec",), session_generation=0
        ),
        NOW,
        CONFIG,
    )
    assert stale_eval.state == evaluating.state
    assert stale_eval.entry.rejection is not None
    assert stale_eval.entry.rejection.code == "slot.superseded"
    assert stale_eval.state.attempts == ()
    assert stale_eval.state.slots[0].status == "evaluating"


def test_post_close_activity_pauses_drift() -> None:
    graph = _step_then_decision()
    driven = drive(
        graph,
        [
            RUN,
            HandoffReceived(slot_id=SLOT, body="shipped"),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ],
        config=CONFIG,
    )
    assert driven.state.status == "running"
    assert driven.state.slots[0].drift is False
    assert any(item.status == "requested" for item in driven.state.decisions)
    result = transition(graph, driven.state, PostCloseActivity(slot_id=SLOT), NOW, CONFIG)
    assert result.entry.rejection is None
    assert result.state.status == "paused"
    assert result.state.causes == (PauseCause(reason="drift", detail="post_close", subject=SLOT),)
    assert result.state.causes[0].reason == "drift"
    assert result.state.slots[0].drift is True
    assert any(item.status == "requested" for item in result.state.decisions)
    assert fold(graph, (*driven.log, result.entry), CONFIG) == result.state
    choice = transition(
        graph,
        result.state,
        ChooseArrow(node_id="choose", label="approved", reason="ship it"),
        NOW,
        CONFIG,
    )
    assert choice.state == result.state
    assert choice.entry.rejection is not None
    assert choice.entry.rejection.code == "run_paused"
    assert any(item.status == "requested" for item in choice.state.decisions)
