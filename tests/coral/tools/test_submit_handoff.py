"""coral_submit_handoff through the dispatcher and the in-memory decision port."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest

from coral.db.enum_codecs import (
    RunPauseReason,
    RunStatus,
    SessionBindingProgress,
    SessionBindingRole,
    SlotRole,
)
from coral.engine.lifecycle import REJECTED_CALL_LIMIT
from coral.engine.types import (
    CancelRun,
    EffectCompleted,
    HandoffEvaluated,
    HandoffReceived,
    PauseRun,
    RejectionObserved,
    RetryStep,
    Slot,
    TurnEnded,
)
from coral.model.ir import CompiledGraph
from coral.stores.session_bindings import SessionBinding
from coral.tools.catalog import SUBMIT_HANDOFF
from coral.tools.dispatch import EngineToolCall, ToolDispatcher
from coral.tools.handlers import PLANNERS
from coral.tools.handlers.submit_handoff import plan
from coral.tools.port import Commit, Reply, RunSnapshot
from coral.tools.replies import RETRY_SHORTLY, STOP, STOP_BLOCKED, stop_paused
from coral.tools.schemas import HANDOFF_BODY_MAX_BYTES, ToolReply
from tests.coral.tools.fake_decision_port import (
    RUN_ID,
    WORKSPACE,
    InMemoryDecisionPort,
    step_binding,
)
from tests.coral.workflow_builders import arrow, compile_text, end, start, step, workflow_text

SUBMIT = SUBMIT_HANDOFF.name
SLOT = "work||:0"
ACTIVATION = "work||"
SESSION = "sess-1"
REPORT = "Implemented the parser; tests pass."
DISPATCH_LOGGER = "coral.tools.dispatch"


def _graph(nodes: list[dict[str, object]], arrows: list[dict[str, object]]) -> CompiledGraph:
    graph = compile_text(workflow_text(nodes, arrows))[0]
    assert not graph.analysis.unresolved, graph.analysis.unresolved
    return graph


def _plain(*, failure: bool = False) -> CompiledGraph:
    """``work`` hands off to ``ship``; with ``failure``, a blocked handoff goes to ``bail``."""
    nodes = [start(), step("work"), step("ship"), end()]
    arrows = [
        arrow("a1", "start", "work"),
        arrow("a2", "work", "ship"),
        arrow("a4", "ship", "end"),
    ]
    if failure:
        nodes.insert(-1, step("bail"))
        arrows += [arrow("a6", "work", "bail", label="failure"), arrow("a7", "bail", "end")]
    return _graph(nodes, arrows)


def _labelled(*, failure: bool = False) -> CompiledGraph:
    """``work`` routes by its handoff label: ``ok`` to ``ship``, ``broken`` to ``fix``."""
    nodes = [start(), step("work"), step("ship"), step("fix"), end()]
    arrows = [
        arrow("a1", "start", "work"),
        arrow("a2", "work", "ship", label="ok"),
        arrow("a3", "work", "fix", label="broken"),
        arrow("a4", "ship", "end"),
        arrow("a5", "fix", "end"),
    ]
    if failure:
        nodes.insert(-1, step("bail"))
        arrows += [arrow("a6", "work", "bail", label="failure"), arrow("a7", "bail", "end")]
    return _graph(nodes, arrows)


def _back_label() -> CompiledGraph:
    """``work`` has one label, on a loop back arrow, so a done handoff may omit it."""
    return _graph(
        [start(), step("work"), end()],
        [
            arrow("a1", "start", "work"),
            arrow("a2", "work", "work", label="again", back=True, limit=1, at_limit="a3"),
            arrow("a3", "work", "end"),
        ],
    )


@pytest.fixture
def port() -> Iterator[InMemoryDecisionPort]:
    port = InMemoryDecisionPort()
    yield port
    port.assert_folds()


@pytest.fixture
def dispatcher(port: InMemoryDecisionPort) -> ToolDispatcher:
    return ToolDispatcher(port, PLANNERS)


def _done(**extra: object) -> dict[str, object]:
    return {"activation_id": ACTIVATION, "status": "done", "report": REPORT, **extra}


def _blocked(**extra: object) -> dict[str, object]:
    return {
        "activation_id": ACTIVATION,
        "status": "blocked",
        "report": "Tried the parser.",
        "blocked_reason": "The spec is missing.",
        **extra,
    }


def _call(
    arguments: dict[str, object], *, op: str = "op-1", binding: SessionBinding | None = None
) -> EngineToolCall:
    return EngineToolCall(
        binding=binding if binding is not None else step_binding(SLOT, session_id=SESSION),
        tool=SUBMIT,
        arguments=arguments,
        operation_id=op,
    )


def _slot(port: InMemoryDecisionPort, slot_id: str = SLOT) -> Slot:
    return next(slot for slot in port.state().slots if slot.id == slot_id)


def _streak(port: InMemoryDecisionPort, slot_id: str = SLOT) -> int:
    return next((item.count for item in port.state().reject_streaks if item.slot_id == slot_id), 0)


def _refused(reply: ToolReply, reason: str) -> None:
    assert (reply.accepted, reply.reason) == (False, reason), reply


def _untouched(port: InMemoryDecisionPort, version: int, log_length: int) -> None:
    assert port.row().version == version
    assert len(port.log()) == log_length


def _says_stop(reply: ToolReply) -> None:
    assert "Stop now and end your turn" in reply.next
    for text in (reply.next, reply.message or ""):
        assert "coral_submit_handoff" not in text
        assert "hand off" not in text.casefold()


def _refusal_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == DISPATCH_LOGGER and record.levelno == logging.INFO
    ]


async def test_done_handoff_commits_received_and_evaluated_with_its_label(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_labelled())
    version, before = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(_done(label="ok", artifacts=["src/parser.py"])))

    assert reply == ToolReply(accepted=True, next=STOP)
    assert port.row().version == version + 1
    received, evaluated = (entry.input for entry in port.log()[before:])
    body = {
        "activation_id": ACTIVATION,
        "artifacts": ["src/parser.py"],
        "label": "ok",
        "report": REPORT,
        "status": "done",
    }
    assert received == HandoffReceived(
        slot_id=SLOT, body=json.dumps(body, sort_keys=True, separators=(",", ":")), label="ok"
    )
    assert evaluated == HandoffEvaluated(slot_id=SLOT, outcome="accepted")
    assert (_slot(port).status, _slot(port).handoff_label) == ("closing", "ok")
    assert [effect.kind for effect in port.log()[-1].effects] == ["close_slot"]


def test_the_commit_carries_the_bindings_generation(port: InMemoryDecisionPort) -> None:
    port.add_run(_labelled())
    # A retried slot's new session (generation 2) is working; the engine models no brief ack yet.
    state = port.state()
    retried = state.model_copy(
        update={
            "slots": tuple(
                slot.model_copy(update={"session_generation": 2}) for slot in state.slots
            )
        }
    )
    snapshot = RunSnapshot(run=port.row(), graph=_labelled(), state=retried)
    binding = step_binding(SLOT, session_id="sess-2", generation=2)

    planned = plan(snapshot, call=_call(_done(label="broken"), binding=binding))

    assert isinstance(planned, Commit)
    received, evaluated = planned.inputs
    assert isinstance(received, HandoffReceived)
    assert (received.session_generation, received.label) == (2, "broken")
    assert evaluated == HandoffEvaluated(slot_id=SLOT, outcome="accepted", session_generation=2)


@pytest.mark.parametrize("failure", [True, False], ids=["failure_arrow", "no_failure_arrow"])
async def test_blocked_handoff_on_a_labelled_step_needs_no_label(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, failure: bool
) -> None:
    port.add_run(_labelled(failure=failure))

    labelled = await dispatcher.dispatch(_call(_blocked(label="ok"), op="op-1"))
    _refused(labelled, "handoff.invalid")
    assert (labelled.field, labelled.allowed_values) == ("label", ())

    reply = await dispatcher.dispatch(_call(_blocked(), op="op-2"))

    assert reply == ToolReply(accepted=True, next=STOP_BLOCKED)
    assert [entry.input.kind for entry in port.log()[-2:]] == [
        "handoff_received",
        "handoff_evaluated",
    ]
    assert port.log()[-1].input == HandoffEvaluated(slot_id=SLOT, outcome="blocked")
    assert port.state().attempts == ()
    work = next(item for item in port.state().activations if item.node_id == "work")
    if failure:
        assert (work.status, work.outcome) == ("closed", "failed")
        assert "bail" in {item.node_id for item in port.state().activations}
        assert port.state().status == "running"
    else:
        assert port.state().status == "paused"
        assert [cause.reason for cause in port.state().causes] == ["failure_path"]


async def test_bad_label_is_handoff_invalid_and_counted(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_labelled())

    unknown = await dispatcher.dispatch(_call(_done(label="nope"), op="op-1"))
    _refused(unknown, "handoff.invalid")
    assert (unknown.field, unknown.allowed_values) == ("label", ("ok", "broken"))
    assert port.log()[-1].input == RejectionObserved(slot_id=SLOT, code="handoff.invalid")
    assert _streak(port) == 1

    # A done handoff on a step that routes by label needs one; nothing of it is written.
    missing = await dispatcher.dispatch(_call(_done(), op="op-2"))
    _refused(missing, "handoff.invalid")
    assert (missing.field, missing.allowed_values) == ("label", ("ok", "broken"))
    assert _streak(port) == 2
    assert not any(entry.input.kind == "handoff_received" for entry in port.log())
    assert (_slot(port).status, _slot(port).handoff) == ("working", None)


async def test_a_label_on_an_unlabelled_step_is_refused(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain())

    reply = await dispatcher.dispatch(_call(_done(label="ok")))

    _refused(reply, "handoff.invalid")
    assert (reply.field, reply.allowed_values) == ("label", ())
    assert _streak(port) == 1


@pytest.mark.parametrize(("label", "accepted"), [(None, True), ("again", True), ("nope", False)])
async def test_a_step_whose_only_label_loops_back_may_omit_it(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, label: str | None, accepted: bool
) -> None:
    port.add_run(_back_label())
    first = "work||a2:1"
    arguments: dict[str, object] = {"activation_id": first, "status": "done", "report": REPORT}
    if label is not None:
        arguments["label"] = label

    reply = await dispatcher.dispatch(
        _call(arguments, binding=step_binding(f"{first}:0", session_id=SESSION))
    )

    assert reply.accepted is accepted
    if not accepted:
        assert (reply.field, reply.allowed_values) == ("label", ("again",))


async def test_stale_generation_is_rejected_cleanly_and_not_counted(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, caplog: pytest.LogCaptureFixture
) -> None:
    port.add_run(_plain())
    old = step_binding(SLOT, session_id=SESSION, generation=1)
    counted = await dispatcher.dispatch(_call(_done(status="maybe"), op="op-1", binding=old))
    _refused(counted, "handoff.invalid")
    blocked = await dispatcher.dispatch(_call(_blocked(), op="op-2", binding=old))
    assert blocked.accepted
    # The blocked step paused the run; the operator retries it with a new session.
    port.apply(RetryStep(node_id="work"))
    assert (_slot(port).session_generation, port.state().status, _streak(port)) == (
        2,
        "running",
        1,
    )
    version, log_length, stored = port.row().version, len(port.log()), port.stored_replies()
    caplog.set_level(logging.INFO, logger=DISPATCH_LOGGER)

    # The replaced session sends a malformed call: refused for its generation, not counted.
    reply = await dispatcher.dispatch(
        _call(_done(status="maybe", report="secret report text"), op="op-3", binding=old)
    )

    _refused(reply, "slot.superseded")
    assert (reply.allowed_values, reply.field) == ((), None)
    _says_stop(reply)
    _untouched(port, version, log_length)
    assert _streak(port) == 1
    assert port.stored_replies() == stored
    lines = _refusal_lines(caplog)
    assert len(lines) == 1
    for part in (RUN_ID, SESSION, SUBMIT, "slot.superseded", "superseded handoff"):
        assert part in lines[0]
    assert "secret" not in lines[0]


async def test_binding_ahead_of_the_engine_is_retried_not_accepted(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, caplog: pytest.LogCaptureFixture
) -> None:
    port.add_run(_plain())
    version, log_length = port.row().version, len(port.log())
    caplog.set_level(logging.INFO, logger=DISPATCH_LOGGER)

    reply = await dispatcher.dispatch(
        _call(_done(), binding=step_binding(SLOT, session_id=SESSION, generation=2))
    )

    _refused(reply, "evaluation_in_progress")
    assert (reply.next, reply.allowed_values) == (RETRY_SHORTLY, ())
    _untouched(port, version, log_length)
    assert _slot(port).status == "working"
    lines = _refusal_lines(caplog)
    assert len(lines) == 1
    assert "binding ahead of the engine" in lines[0]


async def test_new_operation_id_after_accept_returns_the_duplicate_receipt(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain())
    first = await dispatcher.dispatch(_call(_done(artifacts=[]), op="op-1"))
    assert first == ToolReply(accepted=True, next=STOP)
    version, log_length = port.row().version, len(port.log())

    # The same handoff again (an empty artifact list is the same body) is the receipt.
    again = await dispatcher.dispatch(_call(_done(), op="op-2"))
    assert again == ToolReply(accepted=True, next=STOP, duplicate=True)
    _untouched(port, version, log_length)

    other = await dispatcher.dispatch(_call(_done(report="Something else."), op="op-3"))
    _refused(other, "slot_closed")
    _says_stop(other)

    # Still the receipt once the slot has closed and the run moved on, and while paused.
    close = next(effect for effect in port.state().effects if effect.kind == "close_slot")
    port.apply(EffectCompleted(effect_key=close.effect_key, payload={"pending_input": False}))
    port.apply(PauseRun(reason="user", detail=""))
    assert _slot(port).status == "closed"
    late = await dispatcher.dispatch(_call(_done(), op="op-4"))
    assert late == ToolReply(accepted=True, next=STOP, duplicate=True)
    assert len(port.log()) == log_length + 2


async def test_a_repeated_blocked_handoff_returns_its_own_receipt(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain(failure=True))
    assert (await dispatcher.dispatch(_call(_blocked(), op="op-1"))).next == STOP_BLOCKED

    again = await dispatcher.dispatch(_call(_blocked(), op="op-2"))

    assert again == ToolReply(accepted=True, next=STOP_BLOCKED, duplicate=True)


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (RunPauseReason.DRIFT, "drift"),
        (RunPauseReason.BUDGET, "budget"),
        (None, "user"),
    ],
    ids=["store_drift", "store_budget", "engine_user"],
)
async def test_paused_reply_says_stop_and_never_hand_off(
    port: InMemoryDecisionPort,
    dispatcher: ToolDispatcher,
    row: RunPauseReason | None,
    reason: str,
) -> None:
    port.add_run(_plain())
    if row is None:
        port.apply(PauseRun(reason="user", detail="operator"))
    else:
        port.set_row(status=RunStatus.PAUSED, pause_reason=row)
    version, log_length = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(_done(), op="op-1"))
    malformed = await dispatcher.dispatch(_call(_done(status="maybe"), op="op-2"))

    for answer in (reply, malformed):
        _refused(answer, "run.paused")
        assert answer.next == stop_paused(reason)
        assert answer.allowed_values == ()
        _says_stop(answer)
    _untouched(port, version, log_length)
    assert _streak(port) == 0


async def test_cancelled_finished_and_unready_runs_commit_nothing(
    port: InMemoryDecisionPort, caplog: pytest.LogCaptureFixture
) -> None:
    cases = {
        "store_cancelled": "run_cancelled",
        "engine_cancelled": "run_cancelled",
        "store_completed": "slot_closed",
        "store_failed": "slot_closed",
        "pending": "evaluation_in_progress",
        "session_created": "evaluation_in_progress",
        "evaluating": "evaluation_in_progress",
    }
    caplog.set_level(logging.INFO, logger=DISPATCH_LOGGER)
    for index, (case, reason) in enumerate(cases.items()):
        run_id = f"run-{index}"
        port.add_run(_plain(), run_id=run_id, auto_ack=case not in {"pending", "session_created"})
        if case == "store_cancelled":
            port.set_row(status=RunStatus.CANCELLED, run_id=run_id)
        elif case == "engine_cancelled":
            port.apply(CancelRun(), run_id=run_id)
        elif case == "store_completed":
            port.set_row(status=RunStatus.COMPLETED, run_id=run_id)
        elif case == "store_failed":
            port.set_row(status=RunStatus.FAILED, run_id=run_id)
        elif case == "session_created":
            effects = port.state(run_id=run_id).effects
            create = next(effect for effect in effects if effect.kind == "create_session")
            port.apply(EffectCompleted(effect_key=create.effect_key), run_id=run_id)
        elif case == "evaluating":
            port.apply(HandoffReceived(slot_id=SLOT, body="earlier"), run_id=run_id)
        version, log_length = port.row(run_id=run_id).version, len(port.log(run_id=run_id))
        binding = step_binding(SLOT, session_id=f"sess-{index}", run_id=run_id)

        reply = await ToolDispatcher(port, PLANNERS).dispatch(_call(_done(), binding=binding))

        _refused(reply, reason)
        assert reply.allowed_values == (), case
        if case in {"pending", "session_created"}:
            assert reply.next == RETRY_SHORTLY
        elif case != "evaluating":
            _says_stop(reply)
        assert port.row(run_id=run_id).version == version, case
        assert len(port.log(run_id=run_id)) == log_length, case
    lines = _refusal_lines(caplog)
    assert len(lines) == len(cases)
    assert sum("handoff arrived after cancel" in line for line in lines) == 2


@pytest.mark.parametrize(
    ("arguments", "field", "allowed"),
    [
        (_done(kind="refresh_note"), "kind", ("handoff",)),
        (_done(items=[]), "arguments", ()),
        (_done(**{"x\ud800" + "y" * 100: 1}), "arguments", ()),
        ({"activation_id": ACTIVATION, "status": "done"}, "report", ()),
        ({"status": "done", "report": REPORT}, "activation_id", ()),
        (_done(activation_id="other||"), "activation_id", (ACTIVATION,)),
        (_done(activation_id=7), "activation_id", (ACTIVATION,)),
        (_done(status="maybe"), "status", ("done", "blocked")),
        (_done(status=["done"]), "status", ("done", "blocked")),
        (_done(report=""), "report", ()),
        (_done(report="   "), "report", ()),
        (_done(report="x" * 8001), "report", ()),
        (_done(report=12), "report", ()),
        (_done(report="bad \ud800 text"), "report", ()),
        (_blocked(blocked_reason=None), "blocked_reason", ()),
        (
            {key: value for key, value in _blocked().items() if key != "blocked_reason"},
            "blocked_reason",
            (),
        ),
        ({**_blocked(), "blocked_reason": "x" * 2001}, "blocked_reason", ()),
        (_done(blocked_reason="Not blocked."), "blocked_reason", ()),
        (_done(artifacts="src/parser.py"), "artifacts", ()),
        (_done(artifacts=["a"] * 51), "artifacts", ()),
        (_done(artifacts=[""]), "artifacts", ()),
        (_done(artifacts=["x" * 1025]), "artifacts", ()),
        (_done(artifacts=[3]), "artifacts", ()),
        (_done(report="€" * 8000), "report", ()),
    ],
)
async def test_each_invalid_field_is_counted_as_handoff_invalid(
    port: InMemoryDecisionPort,
    dispatcher: ToolDispatcher,
    arguments: dict[str, object],
    field: str,
    allowed: tuple[str, ...],
) -> None:
    port.add_run(_plain())
    version = port.row().version

    reply = await dispatcher.dispatch(_call(arguments))

    _refused(reply, "handoff.invalid")
    assert (reply.field, reply.allowed_values) == (field, allowed)
    assert reply.message
    assert ToolReply.from_json(reply.to_json().encode().decode()) == reply
    assert port.log()[-1].input == RejectionObserved(slot_id=SLOT, code="handoff.invalid")
    assert port.row().version == version + 1
    assert (_streak(port), _slot(port).status, _slot(port).handoff) == (1, "working", None)


async def test_a_body_at_the_size_limit_is_accepted(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain())
    base = json.dumps(_done(report=""), sort_keys=True, separators=(",", ":"))
    report = "é" * ((HANDOFF_BODY_MAX_BYTES - len(base.encode())) // 2)

    reply = await dispatcher.dispatch(_call(_done(report=report)))

    assert reply.accepted
    body = _slot(port).handoff
    assert body is not None
    assert HANDOFF_BODY_MAX_BYTES - 1 <= len(body.encode()) <= HANDOFF_BODY_MAX_BYTES


async def test_third_invalid_handoff_pauses_rejected_calls(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain())
    assert REJECTED_CALL_LIMIT == 3
    for number in (1, 2, 3):
        reply = await dispatcher.dispatch(_call(_done(status="maybe"), op=f"op-{number}"))
        _refused(reply, "handoff.invalid")
        assert (reply.field, reply.allowed_values) == ("status", ("done", "blocked"))
        assert _streak(port) == number
        if number < REJECTED_CALL_LIMIT:
            assert reply.next == "Fix status and call coral_submit_handoff again."
        else:
            # The refusal that pauses the run says stop instead of asking for a fix.
            assert reply.next == stop_paused("rejected_calls")
            _says_stop(reply)

    assert port.state().status == "paused"
    assert [cause.reason for cause in port.state().causes] == ["rejected_calls"]
    after = await dispatcher.dispatch(_call(_done(), op="op-4"))
    _refused(after, "run.paused")
    assert after.next == stop_paused("rejected_calls")


@pytest.mark.parametrize(
    "binding",
    [
        step_binding(None, role=SessionBindingRole.ANCHOR, slot_role=None),
        step_binding(SLOT, slot_role=SlotRole.ORCHESTRATOR),
        step_binding(SLOT, progress=SessionBindingProgress.RESERVED),
        step_binding("ship||:0"),
        step_binding(None),
        step_binding(SLOT, run_id="run-other"),
        step_binding(SLOT, workspace_id=WORKSPACE + 1),
    ],
    ids=[
        "anchor",
        "orchestrator",
        "reserved",
        "no_engine_slot",
        "no_slot",
        "other_run",
        "other_ws",
    ],
)
async def test_a_session_that_is_not_a_step_of_the_run_is_not_run_member(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, binding: SessionBinding
) -> None:
    port.add_run(_plain())
    version, log_length = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(_call(_done(), binding=binding))

    _refused(reply, "not_run_member")
    assert reply.allowed_values == ()
    _untouched(port, version, log_length)


def test_the_planner_checks_the_binding_names_the_snapshot_run(port: InMemoryDecisionPort) -> None:
    port.add_run(_plain())
    snapshot = RunSnapshot(run=port.row(), graph=_plain(), state=port.state())

    for binding in (
        step_binding(SLOT, run_id="run-other"),
        step_binding(SLOT, workspace_id=WORKSPACE + 1),
    ):
        planned = plan(snapshot, call=_call(_done(), binding=binding))
        assert isinstance(planned, Reply)
        _refused(planned.reply, "not_run_member")
    assert isinstance(plan(snapshot, call=_call(_done())), Commit)


def _one_labelled_forward() -> CompiledGraph:
    """``work`` has one labelled forward arrow beside an unlabelled one, so it routes by label."""
    return _graph(
        [start(), step("work"), step("ship"), step("fix"), end()],
        [
            arrow("a1", "start", "work"),
            arrow("a2", "work", "ship", label="ok"),
            arrow("a3", "work", "fix"),
            arrow("a4", "ship", "end"),
            arrow("a5", "fix", "end"),
        ],
    )


def _two_back_labels() -> CompiledGraph:
    """``work`` has two labelled back arrows: two choosable labels, so it routes by label."""
    return _graph(
        [start(), step("work"), end()],
        [
            arrow("a1", "start", "work"),
            arrow("a2", "work", "work", label="again", back=True, limit=1, at_limit="a4"),
            arrow("a3", "work", "work", label="redo", back=True, limit=1, at_limit="a4"),
            arrow("a4", "work", "end"),
        ],
    )


# A label argument that is left out; one sent as JSON null reads the same.
_ABSENT = "<absent>"


@pytest.mark.parametrize(
    ("graph", "status", "label", "allowed"),
    [
        (_plain(failure=True), "done", "failure", ()),
        (_plain(failure=True), "done", _ABSENT, None),
        (_back_label(), "blocked", "again", ()),
        (_plain(), "blocked", "ok", ()),
        (_plain(), "blocked", None, None),
        (_two_back_labels(), "done", _ABSENT, ("again", "redo")),
        (_two_back_labels(), "done", "redo", None),
        (_one_labelled_forward(), "done", _ABSENT, ("ok",)),
        (_one_labelled_forward(), "done", "ok", None),
        (_labelled(), "done", None, ("ok", "broken")),
    ],
    ids=[
        "failure_arrow_is_not_a_choice",
        "failure_only_step_needs_no_label",
        "blocked_on_a_back_label_step",
        "blocked_on_an_unlabelled_step",
        "blocked_with_null_label_is_left_out",
        "two_back_labels_need_one",
        "two_back_labels_take_one",
        "one_labelled_forward_needs_it",
        "one_labelled_forward_takes_it",
        "null_label_on_a_labelled_step_is_missing",
    ],
)
async def test_label_rules_follow_how_the_step_routes(
    port: InMemoryDecisionPort,
    dispatcher: ToolDispatcher,
    graph: CompiledGraph,
    status: str,
    label: str | None,
    allowed: tuple[str, ...] | None,
) -> None:
    port.add_run(graph)
    slot = next(item for item in port.state().slots if item.status == "working")
    arguments: dict[str, object] = {
        "activation_id": slot.activation_id,
        "status": status,
        "report": REPORT,
    }
    if status == "blocked":
        arguments["blocked_reason"] = "The spec is missing."
    if label != _ABSENT:
        arguments["label"] = label

    reply = await dispatcher.dispatch(
        _call(arguments, binding=step_binding(slot.id, session_id=SESSION))
    )

    if allowed is None:
        assert reply.accepted, reply
        assert _streak(port, slot.id) == 0
        return
    _refused(reply, "handoff.invalid")
    assert (reply.field, reply.allowed_values) == ("label", allowed)
    assert _streak(port, slot.id) == 1
    assert not any(entry.input.kind == "handoff_received" for entry in port.log())


async def test_an_old_session_is_superseded_after_its_accepted_step_is_retried(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, caplog: pytest.LogCaptureFixture
) -> None:
    port.add_run(_plain())
    accepted = await dispatcher.dispatch(_call(_done(), op="op-1"))
    assert accepted == ToolReply(accepted=True, next=STOP)
    close = next(effect for effect in port.state().effects if effect.kind == "close_slot")
    port.apply(EffectCompleted(effect_key=close.effect_key, payload={"pending_input": False}))
    # The next step blocks and pauses the run; the operator retries ``work`` with a new session.
    ship = "ship||:0"
    for kind in ("create_session", "send_input"):
        effects = port.state().effects
        started = next(item for item in effects if item.kind == kind and item.subject == ship)
        port.apply(EffectCompleted(effect_key=started.effect_key))
    port.apply(
        HandoffReceived(slot_id=ship, body="blocked"),
        HandoffEvaluated(slot_id=ship, outcome="blocked"),
    )
    port.apply(RetryStep(node_id="work"))
    assert (_slot(port).session_generation, _slot(port).handoff) == (2, None)
    version, log_length, stored = port.row().version, len(port.log()), port.stored_replies()
    caplog.set_level(logging.INFO, logger=DISPATCH_LOGGER)

    # The same handoff under a new op id is no receipt now; a malformed one is not counted.
    same = await dispatcher.dispatch(_call(_done(), op="op-2"))
    malformed = await dispatcher.dispatch(_call(_done(status="maybe"), op="op-3"))

    for reply in (same, malformed):
        _refused(reply, "slot.superseded")
        assert (reply.allowed_values, reply.field) == ((), None)
        _says_stop(reply)
    _untouched(port, version, log_length)
    assert _streak(port) == 0
    assert port.stored_replies() == stored
    lines = _refusal_lines(caplog)
    assert len(lines) == 2
    assert all("superseded handoff" in line for line in lines)
    # Its original call, resent under its own op id, still gets the reply it was given.
    assert await dispatcher.dispatch(_call(_done(), op="op-1")) == accepted


async def test_a_slot_whose_turn_ended_without_a_handoff_still_takes_one(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain(), [TurnEnded(slot_id=SLOT, fact_key="turn:sess-1:1:r1")])
    assert (_slot(port).status, _slot(port).handoff) == ("evaluating", None)

    reply = await dispatcher.dispatch(_call(_done()))

    assert reply == ToolReply(accepted=True, next=STOP)
    assert _slot(port).status == "closing"


async def test_an_early_submit_is_decided_again_once_the_slot_is_working(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain(), auto_ack=False)

    early = await dispatcher.dispatch(_call(_done(), op="op-1"))

    _refused(early, "evaluation_in_progress")
    assert early.next == RETRY_SHORTLY
    assert port.stored_replies() == {}
    for kind in ("create_session", "send_input"):
        started = next(item for item in port.state().effects if item.kind == kind)
        port.apply(EffectCompleted(effect_key=started.effect_key))
    # A refusal that wrote nothing is not stored, so the resent call is decided again.
    resent = await dispatcher.dispatch(_call(_done(), op="op-1"))
    assert resent == ToolReply(accepted=True, next=STOP)


@pytest.mark.parametrize(
    ("slot_status", "run_status", "reason"),
    [
        ("briefed", "running", "evaluation_in_progress"),
        ("working", "completed", "slot_closed"),
        ("working", "failed", "slot_closed"),
        ("working", "paused", "run.paused"),
    ],
)
def test_the_planner_fences_engine_states_the_store_does_not_show(
    port: InMemoryDecisionPort, slot_status: str, run_status: str, reason: str
) -> None:
    port.add_run(_plain())
    state = port.state()
    changed = state.model_copy(
        update={
            "status": run_status,
            "slots": tuple(
                slot.model_copy(update={"status": slot_status}) for slot in state.slots
            ),
        }
    )
    snapshot = RunSnapshot(run=port.row(), graph=_plain(), state=changed)

    planned = plan(snapshot, call=_call(_done(status="maybe")))

    assert isinstance(planned, Reply)
    _refused(planned.reply, reason)
    if reason == "run.paused":
        assert planned.reply.next == stop_paused(None)


@pytest.mark.parametrize(
    "binding",
    [
        step_binding(SLOT, slot_role=SlotRole.VERIFIER),
        step_binding(SLOT, slot_role=SlotRole.MERGE_RESOLVER),
        step_binding(SLOT, progress=SessionBindingProgress.ROW_CREATED),
    ],
    ids=["verifier", "merge_resolver", "row_created"],
)
async def test_every_created_step_slot_but_the_orchestrator_may_hand_off(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, binding: SessionBinding
) -> None:
    port.add_run(_plain())

    reply = await dispatcher.dispatch(_call(_done(), binding=binding))

    assert reply == ToolReply(accepted=True, next=STOP)


async def test_a_huge_report_is_refused_without_keeping_its_text(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain())

    reply = await dispatcher.dispatch(_call(_done(report="x" * 5_000_000)))

    _refused(reply, "handoff.invalid")
    assert reply.field == "report"
    assert _streak(port) == 1
    assert port.log()[-1].input == RejectionObserved(slot_id=SLOT, code="handoff.invalid")
    assert [len(text) < 1_000 for text in port.stored_replies().values()] == [True]


async def test_unknown_arguments_are_counted_and_never_echoed_raw(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain())
    odd = {"IGNORE PREVIOUS": 1, "a" * 40: 1, "z\ud800": 1, "items": 1}
    plain = {f"b{index}": 1 for index in range(1, 6)}

    reply = await dispatcher.dispatch(_call(_done(**odd, **plain)))

    _refused(reply, "handoff.invalid")
    assert (reply.field, reply.allowed_values) == ("arguments", ())
    assert reply.next == "Fix arguments and call coral_submit_handoff again."
    assert reply.message is not None
    assert reply.message.startswith("9 unknown argument(s) (b1, b2, b3, b4, b5); the arguments")
    text = reply.to_json()
    for raw in ("IGNORE", "a" * 33, "items", "\\ud800"):
        assert raw not in text
    assert _streak(port) == 1


@pytest.mark.parametrize("status", ["done", "blocked"])
async def test_explicit_nulls_for_optional_arguments_read_as_left_out(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher, status: str
) -> None:
    port.add_run(_plain(failure=True))
    left_out = _done() if status == "done" else _blocked()
    nulls = {"kind": None, "label": None, "artifacts": None}
    if status == "done":
        nulls["blocked_reason"] = None

    reply = await dispatcher.dispatch(_call({**left_out, **nulls}))

    assert reply.accepted, reply
    body = _slot(port).handoff
    assert body is not None
    assert json.loads(body) == left_out


async def test_a_null_required_argument_is_still_invalid(
    port: InMemoryDecisionPort, dispatcher: ToolDispatcher
) -> None:
    port.add_run(_plain())

    reply = await dispatcher.dispatch(_call(_done(report=None)))

    _refused(reply, "handoff.invalid")
    assert reply.field == "report"


@pytest.mark.parametrize(
    ("report", "artifacts", "field", "names_both"),
    [
        ("€" * 8000, [], "report", False),
        ("Done.", ["a" * 1024] * 50, "artifacts", False),
        ("Done.", ["a" * 1002] * 13, "artifacts", False),
        ("€" * 8000, ["a" * 1024] * 50, "report", True),
        # Each fits alone; together they are too big.
        ("é" * 4000, ["a" * 1000] * 5, "report", True),
    ],
    ids=["report", "many_artifacts", "some_long_artifacts", "both_too_big", "together"],
)
async def test_an_oversized_handoff_names_what_to_shrink(
    port: InMemoryDecisionPort,
    dispatcher: ToolDispatcher,
    report: str,
    artifacts: list[str],
    field: str,
    names_both: bool,
) -> None:
    port.add_run(_plain())

    reply = await dispatcher.dispatch(_call(_done(report=report, artifacts=artifacts)))

    _refused(reply, "handoff.invalid")
    assert reply.field == field
    assert reply.message is not None
    assert str(HANDOFF_BODY_MAX_BYTES) in reply.message
    mentions = ("report" in reply.message, "artifacts" in reply.message)
    assert mentions == ((True, True) if names_both else (field == "report", field == "artifacts"))
    assert _streak(port) == 1


@pytest.mark.parametrize(
    ("stop", "reason", "next_text"),
    [
        ("store_drift", "run.paused", stop_paused("drift")),
        ("engine_user", "run.paused", stop_paused("user")),
        ("store_cancelled", "run_cancelled", None),
    ],
)
async def test_a_binding_ahead_of_the_engine_on_a_stopped_run_is_told_to_stop(
    port: InMemoryDecisionPort,
    dispatcher: ToolDispatcher,
    stop: str,
    reason: str,
    next_text: str | None,
) -> None:
    port.add_run(_plain())
    if stop == "store_drift":
        port.set_row(status=RunStatus.PAUSED, pause_reason=RunPauseReason.DRIFT)
    elif stop == "engine_user":
        port.apply(PauseRun(reason="user", detail=""))
    else:
        port.set_row(status=RunStatus.CANCELLED)
    version, log_length = port.row().version, len(port.log())

    reply = await dispatcher.dispatch(
        _call(_done(), binding=step_binding(SLOT, session_id=SESSION, generation=2))
    )

    _refused(reply, reason)
    if next_text is not None:
        assert reply.next == next_text
    _says_stop(reply)
    _untouched(port, version, log_length)
