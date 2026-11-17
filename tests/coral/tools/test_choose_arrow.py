"""coral_choose_arrow through the dispatcher and the in-memory decision port."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence

import pytest

from coral.db.enum_codecs import (
    RunPauseReason,
    RunStatus,
    SessionBindingProgress,
    SessionBindingRole,
    SlotRole,
)
from coral.engine.types import (
    CancelRun,
    ChooseArrow,
    EffectCompleted,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    PauseRun,
    RunState,
)
from coral.model.ir import CompiledGraph
from coral.stores.session_bindings import SessionBinding
from coral.tools.catalog import CHOOSE_ARROW
from coral.tools.dispatch import EngineToolCall, ToolDispatcher
from coral.tools.handlers import PLANNERS
from coral.tools.handlers.choose_arrow import plan
from coral.tools.port import Commit, Reply, RunSnapshot
from coral.tools.schemas import LoopUse, ToolReply
from tests.coral.tools.fake_decision_port import (
    RUN_ID,
    WORKSPACE,
    InMemoryDecisionPort,
    step_binding,
)
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    start,
    step,
    workflow_text,
)

CHOOSE = CHOOSE_ARROW.name
ORCHESTRATOR = "orch-1"
DECISION = "choose||"
REASON = "The change is small and its tests pass."
DISPATCH_LOGGER = "coral.tools.dispatch"


def _graph(nodes: list[dict[str, object]], arrows: list[dict[str, object]]) -> CompiledGraph:
    graph = compile_text(workflow_text(nodes, arrows))[0]
    assert not graph.analysis.unresolved, graph.analysis.unresolved
    return graph


def _decision_first() -> CompiledGraph:
    """The run opens ``choose`` at once: ``approved`` goes to ``ship``, ``rejected`` ends."""
    return _graph(
        [start(), decision("choose"), step("ship"), end()],
        [
            arrow("a1", "start", "choose"),
            arrow("a2", "choose", "ship", label="approved"),
            arrow("a3", "choose", "end", label="rejected"),
            arrow("a4", "ship", "end"),
        ],
    )


def _review_loop() -> CompiledGraph:
    """``review`` sends ``work`` back at most twice; at the limit it goes to ``escalate``."""
    return _graph(
        [start(), step("work"), decision("review"), step("ship"), step("escalate"), end()],
        [
            arrow("a1", "start", "work"),
            arrow("a2", "work", "review"),
            arrow("a3", "review", "ship", label="approved"),
            arrow("a4", "review", "work", label="revise", back=True, limit=2, at_limit="a5"),
            arrow("a5", "review", "escalate"),
            arrow("a6", "ship", "end"),
            arrow("a7", "escalate", "end"),
        ],
    )


def _finish_work(iteration: str) -> list[Input]:
    slot = f"work||{iteration}:0"
    return [
        HandoffReceived(slot_id=slot, body="done"),
        HandoffEvaluated(slot_id=slot, outcome="accepted"),
    ]


@pytest.fixture
def port() -> Iterator[InMemoryDecisionPort]:
    port = InMemoryDecisionPort()
    yield port
    port.assert_folds()


@pytest.fixture
def dispatcher(port: InMemoryDecisionPort) -> ToolDispatcher:
    return ToolDispatcher(port, PLANNERS)


def _start(port: InMemoryDecisionPort, graph: CompiledGraph, inputs: Sequence[Input] = ()) -> None:
    """Start a run whose store row names ``ORCHESTRATOR`` as its orchestrator."""
    port.add_run(graph, inputs)
    port.set_row(status=RunStatus.RUNNING, orchestrator_session_id=ORCHESTRATOR)


def _next_pass(port: InMemoryDecisionPort, iteration: str) -> None:
    """Brief ``work``'s new pass and finish it, which opens that pass's ``review``."""
    slot = f"work||{iteration}:0"
    created = [
        EffectCompleted(effect_key=effect.effect_key)
        for effect in port.state().effects
        if effect.kind == "create_session" and effect.subject == slot
    ]
    port.apply(*created, auto_ack=True)
    port.apply(*_finish_work(iteration), auto_ack=True)


def _orchestrator(
    session_id: str = ORCHESTRATOR,
    *,
    run_id: str = RUN_ID,
    workspace_id: int = WORKSPACE,
    progress: SessionBindingProgress = SessionBindingProgress.INITIALIZED,
) -> SessionBinding:
    return step_binding(
        "orchestrator",
        session_id=session_id,
        run_id=run_id,
        workspace_id=workspace_id,
        slot_role=SlotRole.ORCHESTRATOR,
        progress=progress,
    )


def _choice(**changes: object) -> dict[str, object]:
    return {"decision_id": DECISION, "label": "approved", "reason": REASON, **changes}


def _call(
    arguments: dict[str, object], *, op: str = "op-1", binding: SessionBinding | None = None
) -> EngineToolCall:
    return EngineToolCall(
        binding=binding if binding is not None else _orchestrator(),
        tool=CHOOSE,
        arguments=arguments,
        operation_id=op,
    )


def _refused(reply: ToolReply, reason: str) -> None:
    assert (reply.accepted, reply.reason) == (False, reason), reply


def _untouched(port: InMemoryDecisionPort, version: int, log_length: int) -> None:
    assert port.row().version == version
    assert len(port.log()) == log_length
    assert port.stored_replies() == {}


def _says_stop(reply: ToolReply) -> None:
    assert "Stop now and end your turn" in reply.next
    assert "coral_submit_handoff" not in reply.next


def _refusal_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == DISPATCH_LOGGER and record.levelno == logging.INFO
    ]


def _counter(state: RunState, back_arrow_id: str) -> int:
    return next(
        item.pass_index for item in state.loop_counters if item.back_arrow_id == back_arrow_id
    )


def _decision_status(port: InMemoryDecisionPort, decision_id: str = DECISION) -> str:
    return next(
        item.status for item in port.state().decisions if item.activation_id == decision_id
    )


async def test_legal_label_commits_the_choice_and_names_the_target(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    _start(port, _decision_first())
    version, before = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(_choice()))

    assert (reply.accepted, reply.reason, reply.allowed_values) == (True, None, ())
    assert (reply.duplicate, reply.loop, reply.redirected) == (False, None, False)
    assert "'approved'" in reply.next and "'ship'" in reply.next
    assert reply.next.endswith("then end your turn.")
    assert [entry.input for entry in port.log()[before:]] == [
        ChooseArrow(node_id="choose", label="approved", reason=REASON)
    ]
    assert port.row().version == version + 1
    assert _decision_status(port) == "decided"
    assert "ship" in {item.node_id for item in port.state().activations}


async def test_a_back_arrow_reports_its_pass_and_the_limit_redirects(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    _start(port, _review_loop(), _finish_work("a4:1"))

    revised = await dispatcher.dispatch(
        _call(_choice(decision_id="review||a4:1", label="revise"), op="op-1")
    )

    assert revised.accepted and not revised.redirected
    # The pass now running is the loop counter after the commit.
    assert revised.loop == LoopUse(used=2, limit=2) == LoopUse(_counter(port.state(), "a4"), 2)
    assert "'work'" in revised.next and "pass 2 of 2" in revised.next
    _next_pass(port, "a4:2")

    redirected = await dispatcher.dispatch(
        _call(_choice(decision_id="review||a4:2", label="revise"), op="op-2")
    )

    assert redirected.accepted and redirected.redirected
    assert redirected.loop == LoopUse(used=2, limit=2)
    assert "'escalate'" in redirected.next and "limit" in redirected.next
    assert _counter(port.state(), "a4") == 2
    assert "escalate" in {item.node_id for item in port.state().activations}


async def test_illegal_label_lists_the_choosable_labels(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, caplog: pytest.LogCaptureFixture
) -> None:
    _start(port, _decision_first())
    version, log_length = port.row().version, len(port.log())
    caplog.set_level(logging.INFO, logger=DISPATCH_LOGGER)

    for index, label in enumerate(["nope", None, 5, "x" * 201]):
        reply = await dispatcher.dispatch(_call(_choice(label=label), op=f"op-{index}"))
        _refused(reply, "tool.illegal")
        assert (reply.field, reply.allowed_values) == ("label", ("approved", "rejected"))
        assert reply.next == "Fix label and call coral_choose_arrow again."

    missing = await dispatcher.dispatch(
        _call({"decision_id": DECISION, "reason": REASON}, op="op-missing")
    )
    _refused(missing, "tool.illegal")
    assert missing.field == "label"
    # Not counted: nothing is written, and each refusal is one info line.
    _untouched(port, version, log_length)
    assert port.state().reject_streaks == ()
    lines = _refusal_lines(caplog)
    assert len(lines) == 5
    assert all("tool.illegal (illegal label)" in line and ORCHESTRATOR in line for line in lines)
    assert not any("x" * 201 in line for line in lines)


@pytest.mark.parametrize(
    "reason",
    ["", "   \n", "x" * 4001, None, 7, "bad \ud800 text"],
    ids=["empty", "blank", "too_long", "null", "not_text", "surrogate"],
)
async def test_an_empty_or_oversize_reason_is_illegal(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, reason: object
) -> None:
    _start(port, _decision_first())
    version, log_length = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(_choice(reason=reason)))

    _refused(reply, "tool.illegal")
    assert (reply.field, reply.allowed_values) == ("reason", ())
    _untouched(port, version, log_length)


async def test_a_reason_at_the_limit_is_taken(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    _start(port, _decision_first())

    reply = await dispatcher.dispatch(_call(_choice(reason="x" * 4000)))

    assert reply.accepted
    assert _decision_status(port) == "decided"


@pytest.mark.parametrize(
    "decision_id",
    ["nope", None, 3, "work||a4:1", "review||a4:2", "review|item|a4:1"],
    ids=["unknown", "null", "not_text", "a_step", "next_pass", "other_scope"],
)
async def test_an_unknown_decision_id_lists_the_open_decisions(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, decision_id: object
) -> None:
    _start(port, _review_loop(), _finish_work("a4:1"))
    version, log_length = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(_choice(decision_id=decision_id, label="revise")))

    _refused(reply, "tool.illegal")
    assert (reply.field, reply.allowed_values) == ("decision_id", ("review||a4:1",))
    assert reply.next == "Fix decision_id and call coral_choose_arrow again."
    _untouched(port, version, log_length)


async def test_with_no_open_decision_an_unknown_id_says_stop(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    _start(port, _review_loop())

    # ``work`` is still running, so no decision is open yet.
    reply = await dispatcher.dispatch(_call(_choice(decision_id="review||a4:1")))

    _refused(reply, "tool.illegal")
    assert (reply.field, reply.allowed_values) == ("decision_id", ())
    _says_stop(reply)


async def test_unknown_arguments_are_refused_and_never_echoed(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    _start(port, _decision_first())
    version, log_length = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(_choice(items=["a"], **{"<script>" * 20: 1})))

    _refused(reply, "tool.illegal")
    assert (reply.field, reply.allowed_values) == ("arguments", ())
    assert reply.message is not None
    assert "2 unknown argument(s) (items)" in reply.message
    assert "<script>" not in reply.to_json()
    _untouched(port, version, log_length)


async def test_a_decided_decision_returns_its_receipt_or_decision_closed(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    _start(port, _decision_first())
    first = await dispatcher.dispatch(_call(_choice(), op="op-1"))
    assert first.accepted
    version, log_length = port.row().version, len(port.log())
    stored = port.stored_replies()

    again = await dispatcher.dispatch(_call(_choice(reason="Restated."), op="op-2"))
    other = await dispatcher.dispatch(_call(_choice(label="rejected"), op="op-3"))

    assert (again.accepted, again.duplicate, again.loop) == (True, True, None)
    assert "'ship'" in again.next and "already" in again.next
    _refused(other, "decision_closed")
    assert other.allowed_values == ()
    _says_stop(other)
    assert (port.row().version, len(port.log()), port.stored_replies()) == (
        version,
        log_length,
        stored,
    )


async def test_a_redirected_choice_repeated_says_so(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    graph = _review_loop()
    _start(port, graph, _finish_work("a4:1"))
    port.apply(ChooseArrow(node_id="review", label="revise", reason="r", iteration_path=("a4:1",)))
    _next_pass(port, "a4:2")
    port.apply(ChooseArrow(node_id="review", label="revise", reason="r", iteration_path=("a4:2",)))

    reply = await dispatcher.dispatch(_call(_choice(decision_id="review||a4:2", label="revise")))

    assert (reply.accepted, reply.duplicate, reply.redirected) == (True, True, True)
    assert "'escalate'" in reply.next


@pytest.mark.parametrize("same_label", [True, False], ids=["same_label", "other_label"])
async def test_a_choice_that_loses_the_race_replans(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, same_label: bool
) -> None:
    _start(port, _decision_first())
    winner = "approved" if same_label else "rejected"
    port.lose_next_commits(1, ChooseArrow(node_id="choose", label=winner, reason="first"))

    reply = await dispatcher.dispatch(_call(_choice()))

    if same_label:
        assert (reply.accepted, reply.duplicate) == (True, True)
    else:
        _refused(reply, "decision_closed")
    assert [entry.input.kind for entry in port.log()].count("choose_arrow") == 1


async def test_replaced_orchestrator_is_not_orchestrator(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, caplog: pytest.LogCaptureFixture
) -> None:
    _start(port, _decision_first())
    port.set_row(status=RunStatus.RUNNING, orchestrator_session_id="orch-2")
    version, log_length = port.row().version, len(port.log())
    caplog.set_level(logging.INFO, logger=DISPATCH_LOGGER)

    replaced = await dispatcher.dispatch(_call(_choice(), op="op-1"))
    current = await dispatcher.dispatch(
        _call(_choice(), op="op-1", binding=_orchestrator("orch-2"))
    )

    _refused(replaced, "not_orchestrator")
    assert replaced.allowed_values == ()
    _says_stop(replaced)
    assert current.accepted
    assert len(port.log()) == log_length + 1 and port.row().version == version + 1
    (line,) = _refusal_lines(caplog)
    assert "not_orchestrator (replaced orchestrator)" in line


async def test_a_run_without_an_orchestrator_takes_no_choice(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_decision_first())
    version, log_length = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(_choice()))

    _refused(reply, "not_orchestrator")
    _untouched(port, version, log_length)


@pytest.mark.parametrize(
    "binding",
    [
        step_binding("choose||:0", session_id=ORCHESTRATOR),
        step_binding(
            None, session_id=ORCHESTRATOR, role=SessionBindingRole.ANCHOR, slot_role=None
        ),
        _orchestrator(progress=SessionBindingProgress.RESERVED),
        step_binding("orchestrator", session_id=ORCHESTRATOR, slot_role=SlotRole.VERIFIER),
    ],
    ids=["step", "anchor", "reserved", "verifier"],
)
async def test_a_session_that_is_not_an_orchestrator_is_not_orchestrator(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, binding: SessionBinding
) -> None:
    # The store row names the caller, so only its binding refuses it.
    _start(port, _decision_first())
    version, log_length = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(_choice(), binding=binding))

    _refused(reply, "not_orchestrator")
    _untouched(port, version, log_length)


def test_the_planner_checks_the_binding_names_the_snapshot_run(
    port: InMemoryDecisionPort,
) -> None:
    _start(port, _decision_first())
    snapshot = RunSnapshot(run=port.row(), graph=_decision_first(), state=port.state())

    for binding in (_orchestrator(run_id="run-other"), _orchestrator(workspace_id=WORKSPACE + 1)):
        planned = plan(snapshot, call=_call(_choice(), binding=binding))
        assert isinstance(planned, Reply)
        _refused(planned.reply, "not_orchestrator")
    assert isinstance(plan(snapshot, call=_call(_choice())), Commit)


@pytest.mark.parametrize(
    ("stop", "reason", "next_text"),
    [
        ("store_drift", "run.paused", "The run is paused (drift). Stop now and end your turn."),
        ("engine_user", "run.paused", "The run is paused (user). Stop now and end your turn."),
        ("store_cancelled", "run_cancelled", None),
        ("engine_cancelled", "run_cancelled", None),
        ("store_completed", "decision_closed", None),
        ("store_failed", "decision_closed", None),
    ],
)
async def test_a_stopped_run_takes_no_choice(
    port: InMemoryDecisionPort,
    dispatcher: ToolDispatcher,
    caplog: pytest.LogCaptureFixture,
    stop: str,
    reason: str,
    next_text: str | None,
) -> None:
    _start(port, _decision_first())
    if stop == "store_drift":
        port.set_row(
            status=RunStatus.PAUSED,
            pause_reason=RunPauseReason.DRIFT,
            orchestrator_session_id=ORCHESTRATOR,
        )
    elif stop == "engine_user":
        port.apply(PauseRun(reason="user", detail="hold"))
    elif stop == "engine_cancelled":
        port.apply(CancelRun())
    else:
        status = {
            "store_cancelled": RunStatus.CANCELLED,
            "store_completed": RunStatus.COMPLETED,
            "store_failed": RunStatus.FAILED,
        }[stop]
        port.set_row(status=status, orchestrator_session_id=ORCHESTRATOR)
    version, log_length = port.row().version, len(port.log())
    caplog.set_level(logging.INFO, logger=DISPATCH_LOGGER)

    # A malformed call gets the same answer: the run's state comes first.
    for index, arguments in enumerate([_choice(), _choice(label="nope", reason="")]):
        reply = await dispatcher.dispatch(_call(arguments, op=f"op-{index}"))
        _refused(reply, reason)
        assert reply.allowed_values == ()
        _says_stop(reply)
        if next_text is not None:
            assert reply.next == next_text
    _untouched(port, version, log_length)
    if stop.endswith("cancelled"):
        assert all("choice arrived after cancel" in line for line in _refusal_lines(caplog))


async def test_a_finished_run_answers_decision_closed_even_for_its_own_choice(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    _start(port, _decision_first())
    first = await dispatcher.dispatch(_call(_choice(label="rejected"), op="op-1"))
    assert first.accepted
    assert port.state().status == "completed"

    reply = await dispatcher.dispatch(_call(_choice(label="rejected"), op="op-2"))

    _refused(reply, "decision_closed")


def test_the_choose_planner_is_registered() -> None:
    assert PLANNERS[CHOOSE] is plan


async def test_an_orchestrator_replaced_while_its_choice_commits_is_refused(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    _start(port, _decision_first())
    log_length = len(port.log())
    # The run takes a new orchestrator between this choice's plan and its write.
    port.before_next_write(
        lambda: port.set_row(status=RunStatus.RUNNING, orchestrator_session_id="orch-2")
    )

    reply = await dispatcher.dispatch(_call(_choice()))

    _refused(reply, "not_orchestrator")
    assert len(port.log()) == log_length
    assert port.stored_replies() == {}
    assert _decision_status(port) != "decided"


async def test_an_orchestrator_binding_with_its_row_created_may_choose(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    _start(port, _decision_first())

    reply = await dispatcher.dispatch(
        _call(_choice(), binding=_orchestrator(progress=SessionBindingProgress.ROW_CREATED))
    )

    assert reply.accepted
    assert _decision_status(port) == "decided"
