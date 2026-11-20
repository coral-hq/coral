"""Answers to gate prompts: only the run owner, only on the run's anchor, one advance per visit."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import threading
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.exc import StatementError

from coral.bridge.executors import BridgeThreads
from coral.bridge.mapping import UnsupportedStance
from coral.bridge.service import EngineLoadFailed, GateAnswerResult
from coral.db.enum_codecs import GateVisitStatus, LogKind, SessionBindingRole, SlotRole
from coral.engine.types import GateStatus, GateVisit, PauseRun
from coral.gates.verdict import (
    GateAnswer,
    GateAnswers,
    GateVerdict,
    VisitAnswer,
    closed_visit_verdict,
    result_verdict,
)
from coral.model.ids import anchor_session_id
from coral.omni.protocols import Viewer
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import RunContended
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.bridge._gates import (
    APPROVE_TOKEN,
    ASKED_AGAIN,
    CHANGE_TOKEN,
    GATE_ONLY,
    GATED,
    GateIds,
    answer,
    before_next_commit,
    gate_rows,
    hand_off,
    visit,
)
from tests.coral.bridge._world import WORKSPACE, World, run_spec, start
from tests.coral.tools.fake_decision_port import step_binding
from tests.coral.workflow_builders import arrow, end, gate, workflow_text
from tests.coral.workflow_builders import start as start_node
from tests.coral.workspace._executor_fakes import FakeBindings

ALICE = Viewer(user_id="alice")
NOT_PERMITTED = GateVerdict(
    status="refused", reason="not_permitted", message="Only the run owner can answer this gate."
)
NO_LONGER_WAITING = GateVerdict(
    status="refused",
    reason="no_longer_waiting",
    message="This gate is no longer waiting.",
    clear_pending=True,
)
RUN_PAUSED = GateVerdict(
    status="refused", reason="run_paused", message="The run is paused; resume it, then answer."
)
RUN_BUSY = GateVerdict(status="refused", reason="run_busy", message="The run is busy; try again.")
ACCEPTED = GateVerdict(status="accepted")
DUPLICATE = GateVerdict(status="duplicate", clear_pending=True)
CHOOSE = GateVerdict(
    status="refused", reason="invalid_answer", message="Choose one of: approve, reject."
)
# A gate with three outcomes, which a plain approval cannot answer.
PICK = workflow_text(
    [start_node(), gate("pick", outcomes=["approve", "reject", "defer"]), end()],
    [
        arrow("a1", "start", "pick"),
        arrow("a2", "pick", "end", label="approve"),
        arrow("a3", "pick", "end", label="reject"),
        arrow("a4", "pick", "end", label="defer"),
    ],
)


def already_answered(label: str) -> GateVerdict:
    return GateVerdict(
        status="refused",
        reason="already_answered",
        message=f"Already answered: {label}.",
        clear_pending=True,
    )


@dataclass
class Gates:
    """A world whose runs' anchors are bound, and the answers over it."""

    world: World
    bindings: FakeBindings
    answers: GateAnswers

    def open(
        self,
        yaml_text: str = GATE_ONLY,
        *,
        owner: str | None = "alice",
        generation: str | None = None,
        start_key: str = "start-1",
    ) -> tuple[str, str]:
        """Start a run at its gate and bind its anchor; its id and the gate's prompt id."""
        run = start(
            self.world,
            yaml_text,
            spec=run_spec(user=owner, start_key=start_key, account_generation=generation),
            start_key=start_key,
            allow_ownerless=owner is None,
        )
        if yaml_text == GATED:
            hand_off(self.world, run.id)
        self.bind(anchor_session_id(WORKSPACE, run.id), run.id, SessionBindingRole.ANCHOR)
        return run.id, self.prompt(run.id)

    def prompt(self, run_id: str, index: int = -1) -> str:
        elicitation_id = gate_rows(self.world, run_id)[index].elicitation_id
        assert elicitation_id is not None
        return elicitation_id

    def bind(self, session_id: str, run_id: str, role: SessionBindingRole) -> None:
        anchor = role == SessionBindingRole.ANCHOR
        self.bindings.rows[(WORKSPACE, session_id)] = step_binding(
            None if anchor else "approve||:0",
            session_id=session_id,
            run_id=run_id,
            workspace_id=WORKSPACE,
            role=role,
            slot_role=None if anchor else SlotRole.STEP_AGENT,
        )

    async def answer(
        self,
        run_id: str,
        elicitation_id: str,
        *,
        viewer: Viewer = ALICE,
        action: str = "accept",
        content: Mapping[str, object] | None = None,
        session_id: str | None = None,
    ) -> GateVerdict:
        return await self.answers.answer(
            GateAnswer(
                workspace_id=WORKSPACE,
                session_id=session_id or anchor_session_id(WORKSPACE, run_id),
                elicitation_id=elicitation_id,
                action=action,  # type: ignore[arg-type]
                content={"decision": "approve"} if content is None else content,
                viewer=viewer,
            )
        )


@pytest_asyncio.fixture
async def gates(tmp_path: Path) -> AsyncIterator[Gates]:
    world = World.fake(tmp_path, gate_ids=GateIds())
    threads = BridgeThreads(world.bridge)
    bindings = FakeBindings()
    try:
        yield Gates(
            world, bindings, GateAnswers(threads=threads, bindings=bindings, run_store=world.runs)
        )
    finally:
        threads.close()


def _answer_entries(world: World, run_id: str) -> list[dict[str, Any]]:
    """The run's ``answer_gate`` log entries, refused ones included."""
    runs = world.runs
    assert isinstance(runs, FakeRunStore)
    bodies = [
        json.loads(log.body)
        for log in runs.logs[(WORKSPACE, run_id)]
        if log.kind == int(LogKind.ENGINE)
    ]
    return [body["input"] for body in bodies if body["input"]["kind"] == "answer_gate"]


def _no_engine_load(monkeypatch: pytest.MonkeyPatch, world: World) -> None:
    def unexpected(**_kwargs: object) -> None:
        raise AssertionError("the answer loaded the run before checking its owner")

    monkeypatch.setattr(world.bridge, "load", unexpected)


async def test_the_owners_answer_is_accepted_once_and_recorded_as_theirs(gates: Gates) -> None:
    run_id, prompt = gates.open()

    first = await gates.answer(run_id, prompt, content={"decision": "approve", "note": "LGTM"})
    again = await gates.answer(run_id, prompt)

    assert (first, again) == (ACCEPTED, DUPLICATE)
    assert _answer_entries(gates.world, run_id) == [
        {
            "kind": "answer_gate",
            "token": APPROVE_TOKEN,
            "label": "approve",
            "by": "alice",
            "note": "LGTM",
        }
    ]
    (row,) = gate_rows(gates.world, run_id)
    assert (row.status, row.answer_label, row.answered_by) == (
        int(GateVisitStatus.RESOLVED),
        "approve",
        "alice",
    )


async def test_another_answer_after_the_first_is_told_the_first(gates: Gates) -> None:
    run_id, prompt = gates.open()
    assert await gates.answer(run_id, prompt) == ACCEPTED

    refused = await gates.answer(run_id, prompt, content={"decision": "reject"})

    assert refused == already_answered("approve")
    assert len(_answer_entries(gates.world, run_id)) == 1


@pytest.mark.parametrize(
    ("label", "expected"),
    [("reject", DUPLICATE), ("approve", already_answered("reject"))],
    ids=["same_label", "other_label"],
)
async def test_an_answer_that_loses_the_race_to_another_is_told_which_won(
    gates: Gates, label: str, expected: GateVerdict
) -> None:
    """Both callers saw the visit live; the other commit landed first."""
    run_id, prompt = gates.open()
    before_next_commit(
        gates.world,
        lambda: answer(gates.world, run_id, APPROVE_TOKEN, "reject", actor="alice"),
    )

    verdict = await gates.answer(run_id, prompt, content={"decision": label})

    assert verdict == expected
    assert [entry["label"] for entry in _answer_entries(gates.world, run_id)] == ["reject"]


async def test_a_repeat_after_the_answer_asked_the_gate_again_is_a_duplicate(
    gates: Gates,
) -> None:
    run_id, first = gates.open(ASKED_AGAIN)
    assert await gates.answer(run_id, first, content={"decision": "reject"}) == ACCEPTED
    second = gates.prompt(run_id)
    assert second != first

    repeat = await gates.answer(run_id, first, content={"decision": "reject"})
    other = await gates.answer(run_id, first, content={"decision": "approve"})
    latest = await gates.answer(run_id, second, content={"decision": "approve"})

    assert (repeat, other, latest) == (DUPLICATE, already_answered("reject"), ACCEPTED)


@pytest.mark.parametrize(
    ("owner", "generation", "viewer"),
    [
        ("alice", None, Viewer(user_id="bob")),
        ("alice", None, Viewer(user_id=None)),
        (None, None, Viewer(user_id="alice")),
        (
            "alice",
            "gen-1",
            Viewer(user_id="alice", account_generation="gen-2", check_generation=True),
        ),
        ("alice", "gen-1", Viewer(user_id="alice", account_generation="gen-1")),
        ("alice", "gen-1", Viewer(user_id="alice")),
    ],
    ids=[
        "another_user",
        "local_user_on_a_users_run",
        "a_user_on_the_local_run",
        "another_generation",
        "unproven_generation",
        "no_generation",
    ],
)
async def test_only_the_run_owner_may_answer_and_nothing_loads_before_that_check(
    gates: Gates,
    monkeypatch: pytest.MonkeyPatch,
    owner: str | None,
    generation: str | None,
    viewer: Viewer,
) -> None:
    run_id, prompt = gates.open(owner=owner, generation=generation)
    _no_engine_load(monkeypatch, gates.world)

    assert await gates.answer(run_id, prompt, viewer=viewer) == NOT_PERMITTED


@pytest.mark.parametrize(
    ("owner", "generation", "viewer"),
    [
        (None, None, Viewer(user_id=None)),
        ("local", None, Viewer(user_id=None)),
        (
            "alice",
            "gen-1",
            Viewer(user_id="alice", account_generation="gen-1", check_generation=True),
        ),
    ],
    ids=["local_run", "run_naming_the_local_user", "same_generation"],
)
async def test_the_owner_is_matched_after_normalizing_the_local_user_and_its_generation(
    gates: Gates, owner: str | None, generation: str | None, viewer: Viewer
) -> None:
    run_id, prompt = gates.open(owner=owner, generation=generation)

    assert await gates.answer(run_id, prompt, viewer=viewer) == ACCEPTED
    assert _answer_entries(gates.world, run_id)[0]["by"] == (viewer.user_id or "local")


async def test_only_a_prompt_on_its_own_runs_anchor_is_answered(gates: Gates) -> None:
    run_id, prompt = gates.open()
    other_run, other_prompt = gates.open(start_key="start-2")
    step = "s" * 32
    gates.bind(step, run_id, SessionBindingRole.STEP)

    refused = [
        # The real id relayed onto the run's own step session.
        await gates.answer(run_id, prompt, session_id=step),
        # An unbound session.
        await gates.answer(run_id, prompt, session_id="u" * 32),
        # Another run's anchor: its rows hold no such prompt.
        await gates.answer(other_run, prompt),
        # Ids the run never issued.
        await gates.answer(run_id, "coral_gate_" + "f" * 32),
        await gates.answer(run_id, "coral_gate_bad"),
    ]

    assert refused == [NO_LONGER_WAITING] * len(refused)
    assert _answer_entries(gates.world, run_id) == []
    assert await gates.answer(other_run, other_prompt) == ACCEPTED
    assert await gates.answer(run_id, prompt) == ACCEPTED


async def test_an_answer_to_a_paused_run_keeps_the_gate_open(gates: Gates) -> None:
    run_id, prompt = gates.open()
    gates.world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=run_id,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )

    assert await gates.answer(run_id, prompt) == RUN_PAUSED
    assert visit(gates.world, run_id, APPROVE_TOKEN).status == "open"


async def test_an_answer_to_a_cancelled_run_is_no_longer_waiting(gates: Gates) -> None:
    run_id, prompt = gates.open()
    gates.world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run_id, actor="alice")

    assert await gates.answer(run_id, prompt) == NO_LONGER_WAITING
    assert _answer_entries(gates.world, run_id) == []


async def test_an_answer_whose_commit_cannot_be_built_is_refused_as_paused(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, prompt = gates.open(GATED)

    def refuse(*_args: object) -> None:
        raise UnsupportedStance("slot has no step stance")

    # The rejection reopens the step, whose create cannot be mapped.
    monkeypatch.setattr("coral.bridge.commit.map_effect", refuse)

    assert await gates.answer(run_id, prompt, content={"decision": "reject"}) == RUN_PAUSED
    assert visit(gates.world, run_id, CHANGE_TOKEN).status == "open"


async def test_a_run_that_cannot_be_loaded_is_refused_as_paused(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, prompt = gates.open()

    def unloadable(**_kwargs: object) -> None:
        raise EngineLoadFailed(WORKSPACE, run_id, ValueError("corrupt"))

    monkeypatch.setattr(gates.world.bridge, "load", unloadable)

    assert await gates.answer(run_id, prompt) == RUN_PAUSED


async def test_a_contended_answer_is_refused_as_busy(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, prompt = gates.open()

    def contended(**_kwargs: object) -> None:
        raise RunContended("other commits kept winning")

    monkeypatch.setattr(gates.world.bridge, "commit_inputs", contended)

    assert await gates.answer(run_id, prompt) == RUN_BUSY


async def test_an_answer_that_outlasts_its_bound_is_refused_as_busy(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, prompt = gates.open()
    held, release = threading.Event(), threading.Event()
    answer_gate = gates.world.bridge.answer_gate

    def slow(**kwargs: Any) -> GateAnswerResult:
        held.set()
        assert release.wait(30)
        return answer_gate(**kwargs)

    monkeypatch.setattr(gates.world.bridge, "answer_gate", slow)
    bounded = GateAnswers(
        threads=BridgeThreads(gates.world.bridge),
        bindings=gates.bindings,
        run_store=gates.world.runs,
        timeout_s=0.2,
    )
    try:
        verdict = await bounded.answer(
            GateAnswer(
                workspace_id=WORKSPACE,
                session_id=anchor_session_id(WORKSPACE, run_id),
                elicitation_id=prompt,
                action="accept",
                content={"decision": "approve"},
                viewer=ALICE,
            )
        )
    finally:
        release.set()

    assert held.is_set()
    assert verdict == RUN_BUSY


async def test_a_store_error_in_the_commit_is_refused_busy_and_logged_without_its_note(
    gates: Gates, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    run_id, prompt = gates.open()
    marker = "private-note-7f3a"

    def failing(**kwargs: Any) -> GateAnswerResult:
        raise StatementError(
            "write failed", "INSERT INTO coral_run_log", {"note": kwargs["note"]}, OSError()
        )

    monkeypatch.setattr(gates.world.bridge, "answer_gate", failing)

    with caplog.at_level(logging.DEBUG):
        verdict = await gates.answer(
            run_id, prompt, content={"decision": "approve", "note": marker}
        )

    assert verdict == RUN_BUSY
    assert marker not in caplog.text
    assert "StatementError" in caplog.text


CROWDED = GateVerdict(
    status="refused", reason="run_busy", message="Too many gate answers at once; try again."
)


@dataclass
class _Capped:
    """
    Answers that admit one at a time; once ``armed``, a run's load waits for ``release``.
    """

    answers: GateAnswers
    armed: threading.Event
    held: threading.Event
    release: threading.Event


@pytest_asyncio.fixture
async def capped(gates: Gates, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_Capped]:
    armed, held, release = threading.Event(), threading.Event(), threading.Event()
    load = gates.world.bridge.load

    def slow(**kwargs: Any) -> Any:
        if armed.is_set():
            held.set()
            assert release.wait(30)
        return load(**kwargs)

    monkeypatch.setattr(gates.world.bridge, "load", slow)
    threads = BridgeThreads(gates.world.bridge)
    try:
        yield _Capped(
            GateAnswers(
                threads=threads,
                bindings=gates.bindings,
                run_store=gates.world.runs,
                max_in_flight=1,
            ),
            armed,
            held,
            release,
        )
    finally:
        release.set()
        threads.close()


def _prompt_answer(run_id: str, prompt: str, viewer: Viewer = ALICE) -> GateAnswer:
    return GateAnswer(
        workspace_id=WORKSPACE,
        session_id=anchor_session_id(WORKSPACE, run_id),
        elicitation_id=prompt,
        action="accept",
        content={"decision": "approve"},
        viewer=viewer,
    )


async def test_answers_beyond_the_in_flight_cap_are_refused_busy_at_once(
    gates: Gates, capped: _Capped
) -> None:
    """A flood of answers cannot take the bridge's threads from the drain."""
    run_id, prompt = gates.open()
    capped.armed.set()
    first = asyncio.create_task(capped.answers.answer(_prompt_answer(run_id, prompt)))
    try:
        # The first answer holds the one admission while its run loads.
        await poll_until_async(capped.held.is_set, timeout_s=budget(30))
        crowded = await capped.answers.answer(_prompt_answer(run_id, prompt))
    finally:
        capped.release.set()
        verdict = await first

    assert crowded == CROWDED
    assert verdict == ACCEPTED


async def test_an_answer_is_identified_before_it_takes_an_admission(
    gates: Gates, capped: _Capped
) -> None:
    """Another user's answers, and answers on no run's anchor, take no admission."""
    run_id, prompt = gates.open()
    capped.armed.set()
    first = asyncio.create_task(capped.answers.answer(_prompt_answer(run_id, prompt)))
    try:
        await poll_until_async(capped.held.is_set, timeout_s=budget(30))
        from_bob = await capped.answers.answer(
            _prompt_answer(run_id, prompt, viewer=Viewer(user_id="bob"))
        )
        unbound = await capped.answers.answer(
            dataclasses.replace(_prompt_answer(run_id, prompt), session_id="u" * 32)
        )
    finally:
        capped.release.set()
        verdict = await first

    assert (from_bob, unbound, verdict) == (NOT_PERMITTED, NO_LONGER_WAITING, ACCEPTED)


# ── Answers to a visit, through the runs API ────────────────────────────────


def _visit_answer(
    run_id: str,
    *,
    outcome: str = "approve",
    node_id: str = "approve",
    token: str = APPROVE_TOKEN,
    note: str = "",
    viewer: Viewer = ALICE,
) -> VisitAnswer:
    return VisitAnswer(
        workspace_id=WORKSPACE,
        run_id=run_id,
        node_id=node_id,
        token=token,
        outcome=outcome,
        note=note,
        viewer=viewer,
    )


async def test_an_answer_to_a_visit_gets_the_prompt_answers_verdicts(gates: Gates) -> None:
    run_id, prompt = gates.open()

    first = await gates.answers.answer_visit(_visit_answer(run_id, note="Ship it."))
    again = await gates.answers.answer_visit(_visit_answer(run_id))
    other = await gates.answers.answer_visit(_visit_answer(run_id, outcome="reject"))

    assert (first.verdict, again.verdict, other.verdict) == (
        ACCEPTED,
        DUPLICATE,
        already_answered("approve"),
    )
    # Each names the visit's row, whose prompt the caller withdraws.
    assert {result.row.elicitation_id for result in (first, again, other) if result.row} == {
        prompt
    }
    assert _answer_entries(gates.world, run_id) == [
        {
            "kind": "answer_gate",
            "token": APPROVE_TOKEN,
            "label": "approve",
            "by": "alice",
            "note": "Ship it.",
        }
    ]


@pytest.mark.parametrize("first", ["prompt", "visit"])
async def test_the_prompt_and_the_runs_api_take_one_answer_between_them(
    gates: Gates, first: str
) -> None:
    run_id, prompt = gates.open()

    async def through(entry: str, label: str) -> GateVerdict | None:
        if entry == "prompt":
            return await gates.answer(run_id, prompt, content={"decision": label})
        return (await gates.answers.answer_visit(_visit_answer(run_id, outcome=label))).verdict

    second = "visit" if first == "prompt" else "prompt"
    taken = await through(first, "approve")
    repeat = await through(second, "approve")
    changed = await through(second, "reject")

    assert (taken, repeat, changed) == (ACCEPTED, DUPLICATE, already_answered("approve"))
    assert len(_answer_entries(gates.world, run_id)) == 1


async def test_an_outcome_the_gate_lacks_is_invalid_only_while_the_visit_is_live(
    gates: Gates,
) -> None:
    run_id, _prompt = gates.open()

    live = await gates.answers.answer_visit(_visit_answer(run_id, outcome="maybe"))
    long_note = await gates.answers.answer_visit(_visit_answer(run_id, note="x" * 2001))
    assert (await gates.answers.answer_visit(_visit_answer(run_id))).verdict == ACCEPTED
    closed = await gates.answers.answer_visit(_visit_answer(run_id, outcome="maybe"))

    assert live.verdict == CHOOSE
    assert long_note.verdict == GateVerdict(
        status="refused",
        reason="invalid_answer",
        message="The note must be text of at most 2,000 characters.",
    )
    # As on the prompt, a visit that can no longer be answered says so first.
    assert closed.verdict == already_answered("approve")


@pytest.mark.parametrize(
    ("node_id", "token"),
    [
        ("review", APPROVE_TOKEN),
        ("approve", "approve||:9"),
        ("approve", ""),
    ],
    ids=["another_node", "unknown_token", "empty_token"],
)
async def test_a_visit_is_named_by_its_gate_and_token(
    gates: Gates, node_id: str, token: str
) -> None:
    run_id, _prompt = gates.open()

    result = await gates.answers.answer_visit(_visit_answer(run_id, node_id=node_id, token=token))

    assert (result.verdict, result.row) == (None, None)
    assert _answer_entries(gates.world, run_id) == []


async def test_a_visit_answer_of_another_user_is_not_permitted(gates: Gates) -> None:
    run_id, _prompt = gates.open()

    result = await gates.answers.answer_visit(_visit_answer(run_id, viewer=Viewer(user_id="bob")))

    assert result.verdict == NOT_PERMITTED
    assert _answer_entries(gates.world, run_id) == []


async def test_a_visit_answer_to_a_paused_or_unloadable_run_is_refused_as_paused(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> None:
    paused, _prompt = gates.open()
    gates.world.bridge.commit_inputs(
        workspace_id=WORKSPACE,
        run_id=paused,
        inputs=lambda _snapshot: (PauseRun(reason="user", detail="look"),),
    )
    broken, _other = gates.open(start_key="start-2")
    load = gates.world.bridge.load

    def unloadable(**kwargs: Any) -> Any:
        if kwargs["run_id"] == broken:
            raise EngineLoadFailed(WORKSPACE, broken, ValueError("corrupt"))
        return load(**kwargs)

    monkeypatch.setattr(gates.world.bridge, "load", unloadable)

    assert (await gates.answers.answer_visit(_visit_answer(paused))).verdict == RUN_PAUSED
    assert (await gates.answers.answer_visit(_visit_answer(broken))).verdict == RUN_PAUSED
    assert visit(gates.world, paused, APPROVE_TOKEN).status == "open"


class _CountedLoads:
    """The bridge's ``load``, counted per run."""

    def __init__(self, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
        self.runs: list[str] = []
        load = world.bridge.load

        def counted(**kwargs: Any) -> Any:
            self.runs.append(kwargs["run_id"])
            return load(**kwargs)

        monkeypatch.setattr(world.bridge, "load", counted)


def _held_answers(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> tuple[threading.Event, threading.Event]:
    """Every commit of an answer waits for the second event; the first is set once one does."""
    held, release = threading.Event(), threading.Event()
    answer_gate = gates.world.bridge.answer_gate

    def slow(**kwargs: Any) -> GateAnswerResult:
        held.set()
        assert release.wait(30)
        return answer_gate(**kwargs)

    monkeypatch.setattr(gates.world.bridge, "answer_gate", slow)
    return held, release


async def test_a_visit_answer_past_the_cap_is_refused_before_any_load(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _prompt = gates.open()
    other_run, other_prompt = gates.open(start_key="start-2")
    held, release = _held_answers(gates, monkeypatch)
    threads = BridgeThreads(gates.world.bridge)
    answers = GateAnswers(
        threads=threads, bindings=gates.bindings, run_store=gates.world.runs, max_in_flight=1
    )
    first = asyncio.create_task(answers.answer_visit(_visit_answer(run_id)))
    try:
        await poll_until_async(held.is_set, timeout_s=budget(30))
        loads = _CountedLoads(gates.world, monkeypatch)
        crowded = await answers.answer_visit(_visit_answer(other_run))
        # Admitted before the visit is looked up: an unknown one is crowded out too.
        unknown = await answers.answer_visit(_visit_answer(other_run, token="approve||:9"))
        prompt = await answers.answer(_prompt_answer(other_run, other_prompt))
        from_bob = await answers.answer_visit(
            _visit_answer(other_run, viewer=Viewer(user_id="bob"))
        )
    finally:
        release.set()
        verdict = await first
        threads.close()

    assert verdict.verdict == ACCEPTED
    assert (crowded.verdict, unknown.verdict, prompt) == (CROWDED, CROWDED, CROWDED)
    assert from_bob.verdict == NOT_PERMITTED
    # A refused answer loads no engine state.
    assert loads.runs == []


async def test_one_user_s_answers_never_hold_every_admission(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> None:
    alices, alices_prompt = gates.open()
    alices_other, _prompt = gates.open(start_key="start-2")
    bobs, _bobs_prompt = gates.open(owner="bob", start_key="bob-1")
    held, release = _held_answers(gates, monkeypatch)
    threads = BridgeThreads(gates.world.bridge)
    answers = GateAnswers(
        threads=threads,
        bindings=gates.bindings,
        run_store=gates.world.runs,
        max_in_flight=2,
        max_per_user=1,
    )
    first = asyncio.create_task(answers.answer_visit(_visit_answer(alices_other)))
    try:
        await poll_until_async(held.is_set, timeout_s=budget(30))
        loads = _CountedLoads(gates.world, monkeypatch)
        # Her one admission is taken, on either route.
        alice_again = await answers.answer(_prompt_answer(alices, alices_prompt))
        loads_then = list(loads.runs)
        bob = asyncio.create_task(
            answers.answer_visit(_visit_answer(bobs, viewer=Viewer(user_id="bob")))
        )
        await poll_until_async(lambda: bobs in loads.runs, timeout_s=budget(30))
        release.set()
        bob_verdict = await bob
    finally:
        release.set()
        verdict = await first
        threads.close()

    assert (alice_again, loads_then) == (CROWDED, [])
    assert (bob_verdict.verdict, verdict.verdict) == (ACCEPTED, ACCEPTED)


async def test_an_answer_to_an_ended_run_that_cannot_load_is_no_longer_waiting(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, prompt = gates.open()
    gates.world.bridge.cancel_run(workspace_id=WORKSPACE, run_id=run_id, actor="alice")
    load = gates.world.bridge.load

    def unloadable(**kwargs: Any) -> Any:
        if kwargs["run_id"] == run_id:
            raise EngineLoadFailed(WORKSPACE, run_id, ValueError("corrupt"))
        return load(**kwargs)

    monkeypatch.setattr(gates.world.bridge, "load", unloadable)

    assert await gates.answer(run_id, prompt) == NO_LONGER_WAITING
    assert (await gates.answers.answer_visit(_visit_answer(run_id))).verdict == NO_LONGER_WAITING


async def test_a_note_holding_nul_is_refused_for_what_it_holds(gates: Gates) -> None:
    run_id, prompt = gates.open()
    refused = GateVerdict(
        status="refused",
        reason="invalid_answer",
        message="The note must not hold NUL or unpaired surrogate characters.",
    )

    on_prompt = await gates.answer(
        run_id, prompt, content={"decision": "approve", "note": "a\x00"}
    )
    on_visit = await gates.answers.answer_visit(_visit_answer(run_id, note="a\x00"))

    assert (on_prompt, on_visit.verdict) == (refused, refused)
    assert _answer_entries(gates.world, run_id) == []


async def test_a_visit_answer_that_outlasts_its_bound_is_refused_as_busy(
    gates: Gates, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _prompt = gates.open()
    release = threading.Event()
    load = gates.world.bridge.load

    def slow(**kwargs: Any) -> Any:
        assert release.wait(30)
        return load(**kwargs)

    monkeypatch.setattr(gates.world.bridge, "load", slow)
    threads = BridgeThreads(gates.world.bridge)
    bounded = GateAnswers(
        threads=threads, bindings=gates.bindings, run_store=gates.world.runs, timeout_s=0.2
    )
    try:
        result = await bounded.answer_visit(_visit_answer(run_id))
    finally:
        release.set()
        threads.close()

    assert result.verdict == RUN_BUSY


@pytest.mark.parametrize(
    ("action", "content", "expected", "label"),
    [
        ("accept", {}, ACCEPTED, "approve"),
        ("accept", {"decision": None}, ACCEPTED, "approve"),
        ("decline", {}, ACCEPTED, "reject"),
        ("accept", {"decision": "reject", "note": "Not yet."}, ACCEPTED, "reject"),
        ("cancel", {}, CHOOSE, None),
        ("accept", {"decision": "maybe"}, CHOOSE, None),
        ("accept", {"decision": ["approve"]}, CHOOSE, None),
        (
            "accept",
            {"decision": "approve", "note": "x" * 2001},
            GateVerdict(
                status="refused",
                reason="invalid_answer",
                message="The note must be text of at most 2,000 characters.",
            ),
            None,
        ),
        (
            "accept",
            {"decision": "approve", "note": 3},
            GateVerdict(
                status="refused",
                reason="invalid_answer",
                message="The note must be text of at most 2,000 characters.",
            ),
            None,
        ),
    ],
    ids=[
        "plain_approval",
        "null_decision",
        "decline",
        "decision_and_note",
        "cancel",
        "unknown_label",
        "list_label",
        "long_note",
        "note_not_text",
    ],
)
async def test_an_answer_maps_to_one_of_the_gates_outcomes(
    gates: Gates,
    action: str,
    content: dict[str, object],
    expected: GateVerdict,
    label: str | None,
) -> None:
    run_id, prompt = gates.open()

    verdict = await gates.answer(run_id, prompt, action=action, content=content)

    assert verdict == expected
    entries = _answer_entries(gates.world, run_id)
    assert [entry["label"] for entry in entries] == ([label] if label else [])


async def test_a_gate_with_more_than_two_outcomes_needs_a_decision(gates: Gates) -> None:
    run_id, prompt = gates.open(PICK)

    plain = await gates.answer(run_id, prompt, content={})
    chosen = await gates.answer(run_id, prompt, content={"decision": "defer"})

    choose = GateVerdict(
        status="refused",
        reason="invalid_answer",
        message="Choose one of: approve, reject, defer.",
    )
    assert (plain, chosen) == (choose, ACCEPTED)
    assert [entry["label"] for entry in _answer_entries(gates.world, run_id)] == ["defer"]


def _visit(status: GateStatus) -> GateVisit:
    return GateVisit(activation_id="approve||", token=APPROVE_TOKEN, visit_no=1, status=status)


@pytest.mark.parametrize(
    ("status", "answered", "label", "expected"),
    [
        ("resolved", "approve", "approve", DUPLICATE),
        ("superseded", "reject", "reject", DUPLICATE),
        ("resolved", "approve", None, already_answered("approve")),
        ("superseded", "reject", "approve", already_answered("reject")),
        (
            "superseded",
            None,
            "approve",
            GateVerdict(
                status="refused",
                reason="stale_visit",
                message="This gate was asked again; answer the latest one.",
                clear_pending=True,
            ),
        ),
        ("open", None, "approve", NO_LONGER_WAITING),
    ],
)
def test_a_visit_that_cannot_be_answered_is_classified_without_the_engine(
    status: GateStatus, answered: str | None, label: str | None, expected: GateVerdict
) -> None:
    assert closed_visit_verdict(_visit(status), answered, label) == expected


STALE = GateVerdict(
    status="refused",
    reason="stale_visit",
    message="This gate was asked again; answer the latest one.",
    clear_pending=True,
)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (GateAnswerResult(outcome="accepted"), ACCEPTED),
        (GateAnswerResult(outcome="duplicate", answered_label="approve"), DUPLICATE),
        (GateAnswerResult(outcome="refused", code="gate.stale"), STALE),
        (
            GateAnswerResult(outcome="refused", code="gate.stale", answered_label="reject"),
            already_answered("reject"),
        ),
        (
            GateAnswerResult(outcome="refused", code="rejected", answered_label="reject"),
            already_answered("reject"),
        ),
        (
            GateAnswerResult(outcome="refused", code="rejected"),
            GateVerdict(
                status="refused",
                reason="already_answered",
                message="This gate was already answered.",
                clear_pending=True,
            ),
        ),
        (
            GateAnswerResult(outcome="refused", code="run_terminal", answered_label="reject"),
            already_answered("reject"),
        ),
        (GateAnswerResult(outcome="refused", code="run_terminal"), NO_LONGER_WAITING),
        (GateAnswerResult(outcome="refused", code="run_cancelled"), NO_LONGER_WAITING),
        (GateAnswerResult(outcome="refused", code="run_paused"), RUN_PAUSED),
        (GateAnswerResult(outcome="refused", code="unbuildable"), RUN_PAUSED),
        (GateAnswerResult(outcome="refused", code="run.contended"), RUN_BUSY),
        (
            GateAnswerResult(
                outcome="refused", code="tool.illegal", allowed=("approve", "reject")
            ),
            CHOOSE,
        ),
        (
            GateAnswerResult(outcome="refused", code="invalid_answer"),
            GateVerdict(
                status="refused",
                reason="invalid_answer",
                message="The note must be text of at most 2,000 characters.",
            ),
        ),
    ],
)
def test_the_engines_outcome_maps_to_a_verdict(
    result: GateAnswerResult, expected: GateVerdict
) -> None:
    assert result_verdict(result, "approve", ("approve", "reject")) == expected
