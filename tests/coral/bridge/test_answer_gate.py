"""``EngineBridge.answer_gate``: one engine advance per visit, and an outcome that says which."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from coral.bridge.mapping import UnsupportedStance
from coral.bridge.service import GateAnswerResult
from coral.db.enum_codecs import (
    ActorKind,
    GateVisitStatus,
    LogKind,
    RunPauseReason,
    RunStatus,
)
from coral.engine.types import PauseRun
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import RunContended, RunLogEntry, RunNotFound
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
    ASKED_AGAIN,
    CHANGE_TOKEN,
    GATE_ONLY,
    GATED,
    HOLD_TOKEN,
    IMPLEMENT_AGAIN,
    answer,
    before_next_commit,
    gate_rows,
    hand_off,
    visit,
)
from tests.coral.bridge._world import WORKSPACE, World, start


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


def _logs(world: World, run_id: str) -> list[RunLogEntry]:
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    return list(runs.logs[(WORKSPACE, run_id)])


def _answers(world: World, run_id: str) -> list[dict[str, Any]]:
    """The run's stored ``answer_gate`` entries, refused ones included."""
    bodies = [
        json.loads(log.body) for log in _logs(world, run_id) if log.kind == int(LogKind.ENGINE)
    ]
    return [body for body in bodies if body["input"]["kind"] == "answer_gate"]


def _at_gate(world: World) -> str:
    run = start(world, GATED)
    hand_off(world, run.id)
    return run.id


def test_an_answer_is_accepted_once_and_recorded_for_its_actor(world: World) -> None:
    run = start(world, GATE_ONLY)

    result = answer(world, run.id, APPROVE_TOKEN, "approve", note="Ship it.", actor="alice")

    assert result == GateAnswerResult(outcome="accepted")
    (entry,) = _answers(world, run.id)
    assert entry["input"] == {
        "kind": "answer_gate",
        "token": APPROVE_TOKEN,
        "label": "approve",
        "by": "alice",
        "note": "Ship it.",
    }
    (log,) = [log for log in _logs(world, run.id) if '"answer_gate"' in log.body]
    assert (log.actor_ref, log.actor_kind, log.audit_only) == ("alice", int(ActorKind.USER), False)
    resolved = visit(world, run.id, APPROVE_TOKEN)
    assert (resolved.status, resolved.label, resolved.by, resolved.note) == (
        "resolved",
        "approve",
        "alice",
        "Ship it.",
    )
    assert world.run(run.id).status == int(RunStatus.COMPLETED)
    world.assert_fold_matches(run.id)


def test_the_same_answer_again_is_a_duplicate_that_writes_nothing(world: World) -> None:
    run = start(world, GATE_ONLY)
    answer(world, run.id, APPROVE_TOKEN, "approve")
    version, logs = world.run(run.id).version, _logs(world, run.id)

    result = answer(world, run.id, APPROVE_TOKEN, "approve", note="again", actor="bob")

    assert result == GateAnswerResult(outcome="duplicate", answered_label="approve")
    assert (world.run(run.id).version, _logs(world, run.id)) == (version, logs)


def test_a_repeat_after_the_gate_was_asked_again_is_still_a_duplicate(world: World) -> None:
    run_id = _at_gate(world)
    assert answer(world, run_id, CHANGE_TOKEN, "reject").outcome == "accepted"
    hand_off(world, run_id, IMPLEMENT_AGAIN)
    assert visit(world, run_id, CHANGE_TOKEN).status == "superseded"
    version = world.run(run_id).version

    result = answer(world, run_id, CHANGE_TOKEN, "reject")

    assert result == GateAnswerResult(outcome="duplicate", answered_label="reject")
    assert world.run(run_id).version == version


def test_a_repeat_of_an_answer_that_asked_the_gate_again_at_once_is_a_duplicate(
    world: World,
) -> None:
    # The engine resolves and supersedes the visit in one transition; its receipt stands.
    run = start(world, ASKED_AGAIN)
    assert answer(world, run.id, HOLD_TOKEN, "reject").outcome == "accepted"
    assert visit(world, run.id, HOLD_TOKEN).status == "superseded"
    version = world.run(run.id).version

    result = answer(world, run.id, HOLD_TOKEN, "reject")

    assert result == GateAnswerResult(outcome="duplicate", answered_label="reject")
    assert world.run(run.id).version == version


def test_another_label_after_an_answer_is_refused_with_the_label_it_got(world: World) -> None:
    run_id = _at_gate(world)
    answer(world, run_id, CHANGE_TOKEN, "reject")
    version = world.run(run_id).version

    result = answer(world, run_id, CHANGE_TOKEN, "approve")

    assert (result.outcome, result.code, result.answered_label) == (
        "refused",
        "rejected",
        "reject",
    )
    # The engine lists its input kinds for this refusal; they are no labels to offer.
    assert result.allowed == ()
    assert world.run(run_id).version == version


# A note of 2,000 four-byte characters that compress poorly: the most a note may take.
LONGEST_NOTE = "".join(chr(0x20000 + (index * 7919) % 40_000) for index in range(2_000))


@pytest.mark.parametrize(
    ("label", "note"),
    [
        ("x" * 129, ""),
        ("approve", "n" * 2_001),
        ("approve\ud800", ""),
        ("approve\x00", ""),
        ("approve", "half \udfff a pair"),
        ("approve", "nul \x00 byte"),
    ],
    ids=["long_label", "long_note", "surrogate_label", "nul_label", "surrogate_note", "nul_note"],
)
def test_a_label_or_note_no_row_can_store_is_refused_before_anything_loads(
    world: World, monkeypatch: pytest.MonkeyPatch, label: str, note: str
) -> None:
    run = start(world, GATE_ONLY)
    version = world.run(run.id).version

    def unexpected(**_kwargs: object) -> None:
        raise AssertionError("an answer no row can store is never committed")

    monkeypatch.setattr(world.bridge, "commit_inputs", unexpected)
    assert answer(world, run.id, APPROVE_TOKEN, label, note=note) == GateAnswerResult(
        outcome="refused", code="invalid_answer"
    )
    monkeypatch.undo()
    assert world.run(run.id).version == version
    assert visit(world, run.id, APPROVE_TOKEN).status == "open"


def test_the_longest_note_is_accepted_with_its_lines(world: World) -> None:
    run = start(world, GATE_ONLY)
    note = f"line one\n\tline two {LONGEST_NOTE}"[:2_000]

    assert answer(world, run.id, APPROVE_TOKEN, "approve", note=note).outcome == "accepted"

    assert gate_rows(world, run.id)[0].note == note


def test_an_answer_to_an_earlier_visit_is_stale(world: World) -> None:
    run_id = _at_gate(world)
    answer(world, run_id, CHANGE_TOKEN, "reject")
    hand_off(world, run_id, IMPLEMENT_AGAIN)

    result = answer(world, run_id, CHANGE_TOKEN, "approve")

    assert (result.outcome, result.code, result.answered_label) == (
        "refused",
        "gate.stale",
        "reject",
    )


def test_an_answer_to_a_paused_run_is_refused_and_the_visit_stays_open(world: World) -> None:
    run = start(world, GATE_ONLY)
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run.id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )
    version = world.run(run.id).version

    result = answer(world, run.id, APPROVE_TOKEN, "approve")

    assert result == GateAnswerResult(outcome="refused", code="run_paused")
    assert world.run(run.id).version == version
    assert visit(world, run.id, APPROVE_TOKEN).status == "open"
    assert gate_rows(world, run.id)[0].status == int(GateVisitStatus.OPEN)


def test_an_answer_to_a_cancelled_run_is_refused(world: World) -> None:
    run = start(world, GATE_ONLY)
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run.id, actor="alice")

    result = answer(world, run.id, APPROVE_TOKEN, "approve")

    assert result == GateAnswerResult(outcome="refused", code="run_cancelled")


def _cancel(world: World, run_id: str) -> None:
    world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run_id, actor="bob")


def _pause(world: World, run_id: str) -> None:
    world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )


@pytest.mark.parametrize(
    ("first", "code", "row_status"),
    [
        (_cancel, "run_cancelled", GateVisitStatus.CANCELLED),
        (_pause, "run_paused", GateVisitStatus.OPEN),
    ],
    ids=["cancel", "pause"],
)
def test_an_answer_that_loses_to_a_cancel_or_a_pause_is_refused_by_its_retry(
    world: World,
    first: Callable[[World, str], None],
    code: str,
    row_status: GateVisitStatus,
) -> None:
    run = start(world, GATE_ONLY)
    before_next_commit(world, lambda: first(world, run.id))

    result = answer(world, run.id, APPROVE_TOKEN, "approve")

    assert result == GateAnswerResult(outcome="refused", code=code)
    assert visit(world, run.id, APPROVE_TOKEN).status == "open"
    assert gate_rows(world, run.id)[0].status == int(row_status)
    assert _answers(world, run.id) == []
    world.assert_fold_matches(run.id)


@pytest.mark.parametrize(
    ("label", "outcome", "code"),
    [("reject", "duplicate", None), ("approve", "refused", "rejected")],
    ids=["same_label", "other_label"],
)
def test_of_two_answers_at_once_one_is_accepted_and_the_other_told_its_label(
    world: World, label: str, outcome: str, code: str | None
) -> None:
    run_id = _at_gate(world)
    winner: list[GateAnswerResult] = []
    before_next_commit(
        world, lambda: winner.append(answer(world, run_id, CHANGE_TOKEN, "reject", actor="alice"))
    )

    result = answer(world, run_id, CHANGE_TOKEN, label, actor="bob")

    assert winner == [GateAnswerResult(outcome="accepted")]
    assert (result.outcome, result.code, result.answered_label) == (outcome, code, "reject")
    answered = visit(world, run_id, CHANGE_TOKEN)
    assert (answered.status, answered.label, answered.by) == ("resolved", "reject", "alice")
    assert [entry["input"]["by"] for entry in _answers(world, run_id)] == ["alice"]
    world.assert_fold_matches(run_id)


def test_an_answer_after_the_run_completed_commits_nothing(world: World) -> None:
    run = start(world, GATE_ONLY)
    answer(world, run.id, APPROVE_TOKEN, "approve")
    version, logs = world.run(run.id).version, _logs(world, run.id)

    result = answer(world, run.id, APPROVE_TOKEN, "reject")

    assert (result.outcome, result.code, result.answered_label) == (
        "refused",
        "run_terminal",
        "approve",
    )
    assert (world.run(run.id).version, _logs(world, run.id)) == (version, logs)


def test_an_answer_named_in_another_workspace_finds_no_run(world: World) -> None:
    run = start(world, GATE_ONLY)
    version = world.run(run.id).version

    with pytest.raises(RunNotFound):
        world.bridge.answer_gate(
            workspace_id=WORKSPACE + 1,
            run_id=run.id,
            token=APPROVE_TOKEN,
            label="approve",
            note="",
            actor="eve",
        )

    assert world.run(run.id).version == version
    assert visit(world, run.id, APPROVE_TOKEN).status == "open"


def test_a_label_that_is_not_an_outcome_is_refused_with_the_outcomes(world: World) -> None:
    run = start(world, GATE_ONLY)

    result = answer(world, run.id, APPROVE_TOKEN, "maybe")

    assert result == GateAnswerResult(
        outcome="refused", code="tool.illegal", allowed=("approve", "reject")
    )
    assert visit(world, run.id, APPROVE_TOKEN).status == "open"


def test_an_unknown_token_is_refused(world: World) -> None:
    run = start(world, GATE_ONLY)
    assert answer(world, run.id, "approve||:9", "approve").code == "rejected"


def test_an_answer_whose_commit_cannot_be_built_pauses_the_run_and_is_never_accepted(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _at_gate(world)

    def refuse(*_args: object) -> None:
        raise UnsupportedStance("slot has no step stance")

    # The rejection reopens the step, whose create cannot be mapped.
    monkeypatch.setattr("coral.bridge.commit.map_effect", refuse)
    result = answer(world, run_id, CHANGE_TOKEN, "reject")

    assert result == GateAnswerResult(outcome="refused", code="unbuildable")
    paused = world.run(run_id)
    assert (paused.status, paused.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    assert visit(world, run_id, CHANGE_TOKEN).status == "open"
    assert gate_rows(world, run_id)[0].status == int(GateVisitStatus.OPEN)
    assert not [entry for entry in _answers(world, run_id) if entry.get("rejection") is None]


def test_a_contended_answer_is_refused_as_busy(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = start(world, GATE_ONLY)

    def contended(**_kwargs: object) -> None:
        raise RunContended("other commits kept winning")

    monkeypatch.setattr(world.bridge, "commit_inputs", contended)

    assert answer(world, run.id, APPROVE_TOKEN, "approve") == GateAnswerResult(
        outcome="refused", code="run.contended"
    )
