"""The dispatcher decides each operation id once, and the decision port's contract."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable, Iterator

import pytest

from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.engine.types import HandoffEvaluated, HandoffReceived, PauseRun, RejectionObserved
from coral.model.ir import CompiledGraph
from coral.tools.catalog import CHOOSE_ARROW, SUBMIT_HANDOFF
from coral.tools.dispatch import EngineToolCall, ToolDispatcher, TransportError, operation_checksum
from coral.tools.handlers import PLANNERS
from coral.tools.handlers.submit_handoff import plan as plan_submit
from coral.tools.port import Commit, Plan, Planner, Reply, RunSnapshot
from coral.tools.replies import STOP, stop_paused
from coral.tools.schemas import ToolReply
from tests._helpers.polling import poll_until_async
from tests.coral.tools.fake_decision_port import InMemoryDecisionPort, step_binding
from tests.coral.workflow_builders import arrow, compile_text, end, start, step, workflow_text

SUBMIT = SUBMIT_HANDOFF.name
DISPATCH_LOGGER = "coral.tools.dispatch"
SLOT = "work||:0"
ARGUMENTS: dict[str, object] = {"activation_id": "work||", "status": "done", "report": "Done."}
# The canonical body ARGUMENTS commit.
BODY = json.dumps(ARGUMENTS, sort_keys=True, separators=(",", ":"))


def _graph(*, roster: list[str] | None = None, labelled: bool = False) -> CompiledGraph:
    arrows = [arrow("a1", "start", "work"), arrow("a3", "ship", "end")]
    if labelled:
        arrows += [
            arrow("a2", "work", "ship", label="ok"),
            arrow("a4", "work", "end", label="broken"),
        ]
    else:
        arrows.append(arrow("a2", "work", "ship"))
    return compile_text(
        workflow_text([start(), step("work", roster=roster), step("ship"), end()], arrows)
    )[0]


@pytest.fixture
def port() -> Iterator[InMemoryDecisionPort]:
    port = InMemoryDecisionPort()
    yield port
    port.assert_folds()


def _call(
    *, op: str = "op-1", session: str = "sess-1", slot: str = SLOT, tool: str = SUBMIT
) -> EngineToolCall:
    return EngineToolCall(
        binding=step_binding(slot, session_id=session),
        tool=tool,
        arguments=ARGUMENTS,
        operation_id=op,
    )


class _HeldPort:
    """The fake port, with ``decide`` held until the test releases it."""

    def __init__(self, inner: InMemoryDecisionPort) -> None:
        self.inner = inner
        self.entered = threading.Event()
        self.release = threading.Event()

    def find_reply(self, workspace_id: int, run_id: str, cksum: bytes) -> ToolReply | None:
        return self.inner.find_reply(workspace_id, run_id, cksum)

    def decide(self, workspace_id: int, run_id: str, planner: Planner, cksum: bytes) -> ToolReply:
        self.entered.set()
        assert self.release.wait(10)
        return self.inner.decide(workspace_id, run_id, planner, cksum)


def _planner(planned: Plan) -> dict[str, Callable[..., Plan]]:
    def fixed(snapshot: RunSnapshot, *, call: EngineToolCall) -> Plan:
        del snapshot, call
        return planned

    return {SUBMIT: fixed}


async def test_one_operation_id_runs_the_planner_once(port: InMemoryDecisionPort) -> None:
    port.add_run(_graph())
    dispatcher = ToolDispatcher(port, PLANNERS)

    first = await dispatcher.dispatch(_call())
    again = await dispatcher.dispatch(_call())
    # A restarted server builds a new dispatcher; the stored reply still answers.
    restarted = await ToolDispatcher(port, PLANNERS).dispatch(_call())

    assert first == again == restarted == ToolReply(accepted=True, next=STOP)
    assert (port.decide_calls, port.plan_calls, port.find_reply_calls) == (1, 1, 3)
    stored = port.stored_replies()
    assert list(stored.values()) == [first.to_json()]
    assert list(stored) == [operation_checksum("run-1", "sess-1", SUBMIT, "op-1")]
    assert sum(entry.input.kind == "handoff_received" for entry in port.log()) == 1


async def test_concurrent_duplicates_share_one_decision(port: InMemoryDecisionPort) -> None:
    port.add_run(_graph())
    held = _HeldPort(port)
    dispatcher = ToolDispatcher(held, PLANNERS)

    first = asyncio.create_task(dispatcher.dispatch(_call()))
    resent = asyncio.create_task(dispatcher.dispatch(_call()))
    assert await asyncio.to_thread(held.entered.wait, 10)
    # The caller that started the decision goes away; the decision still finishes.
    first.cancel()
    held.release.set()
    reply = await resent
    with pytest.raises(asyncio.CancelledError):
        await first

    assert reply == ToolReply(accepted=True, next=STOP)
    assert (port.decide_calls, port.find_reply_calls) == (1, 1)
    assert await dispatcher.dispatch(_call()) == reply
    assert port.decide_calls == 1


async def test_operation_id_reused_by_another_session_is_a_new_key(
    port: InMemoryDecisionPort,
) -> None:
    port.add_run(_graph(roster=["implementer", "reviewer"]))
    probe = ToolReply(accepted=False, reason="not_run_member", next="Stop.")
    planners = {**PLANNERS, "coral_probe": _planner(Reply(probe))[SUBMIT]}
    dispatcher = ToolDispatcher(port, planners)

    mine = await dispatcher.dispatch(_call(session="sess-a", slot="work||:0"))
    theirs = await dispatcher.dispatch(_call(session="sess-b", slot="work||:1"))
    other_tool = await dispatcher.dispatch(_call(session="sess-a", tool="coral_probe"))

    assert mine == theirs == ToolReply(accepted=True, next=STOP)
    assert other_tool == probe
    assert port.decide_calls == 3
    assert len(port.stored_replies()) == 2
    keys = {
        operation_checksum("run-1", "sess-a", SUBMIT, "op-1"),
        operation_checksum("run-1", "sess-b", SUBMIT, "op-1"),
        operation_checksum("run-1", "sess-a", CHOOSE_ARROW.name, "op-1"),
        operation_checksum("run-2", "sess-a", SUBMIT, "op-1"),
        operation_checksum("run-1", "sess-a", SUBMIT, "op-2"),
        # Only the operation id is caller-chosen; any text, unpaired surrogates included.
        operation_checksum("run-1", "sess-a", SUBMIT, "op-\ud800"),
    }
    assert len(keys) == 6
    assert all(len(key) == 32 for key in keys)


async def test_a_lost_compare_and_swap_replans_and_commits_once(
    port: InMemoryDecisionPort,
) -> None:
    port.add_run(_graph())
    port.lose_next_commits(1)

    reply = await ToolDispatcher(port, PLANNERS).dispatch(_call())

    assert reply == ToolReply(accepted=True, next=STOP)
    assert (port.decide_calls, port.plan_calls) == (1, 2)
    assert sum(entry.input.kind == "handoff_received" for entry in port.log()) == 1


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (BODY, ToolReply(accepted=True, next=STOP, duplicate=True)),
        ("another body", None),
    ],
    ids=["same_handoff", "other_handoff"],
)
async def test_a_racing_submit_replans_to_the_receipt_or_slot_closed(
    port: InMemoryDecisionPort, body: str, expected: ToolReply | None
) -> None:
    port.add_run(_graph())
    # Another call commits a handoff between this call's snapshot and its write.
    port.lose_next_commits(
        1,
        HandoffReceived(slot_id=SLOT, body=body),
        HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
    )

    reply = await ToolDispatcher(port, PLANNERS).dispatch(_call())

    if expected is None:
        assert (reply.accepted, reply.reason) == (False, "slot_closed")
    else:
        assert reply == expected
    assert port.plan_calls == 2
    assert sum(entry.input.kind == "handoff_received" for entry in port.log()) == 1
    assert port.stored_replies() == {}


async def test_a_run_that_keeps_changing_is_a_transport_error(
    port: InMemoryDecisionPort, caplog: pytest.LogCaptureFixture
) -> None:
    port.add_run(_graph())
    port.lose_next_commits(5)

    with caplog.at_level(logging.WARNING, logger=DISPATCH_LOGGER):
        with pytest.raises(TransportError):
            await ToolDispatcher(port, PLANNERS).dispatch(_call())

    assert port.plan_calls == 5
    assert not any(entry.input.kind == "handoff_received" for entry in port.log())
    assert ["kept changing" in record.getMessage() for record in caplog.records] == [True]


async def test_a_missing_run_is_not_run_member(port: InMemoryDecisionPort) -> None:
    port.add_run(_graph())
    call = EngineToolCall(
        binding=step_binding(SLOT, run_id="run-gone"),
        tool=SUBMIT,
        arguments=ARGUMENTS,
        operation_id="op-1",
    )

    reply = await ToolDispatcher(port, PLANNERS).dispatch(call)

    assert (reply.accepted, reply.reason, reply.allowed_values) == (False, "not_run_member", ())


async def test_an_unknown_tool_is_a_transport_error(port: InMemoryDecisionPort) -> None:
    port.add_run(_graph())

    with pytest.raises(TransportError):
        await ToolDispatcher(port, PLANNERS).dispatch(_call(tool="coral_unknown"))

    assert port.decide_calls == 0


async def test_an_engine_refused_handoff_writes_none_of_it_and_is_counted(
    port: InMemoryDecisionPort, caplog: pytest.LogCaptureFixture
) -> None:
    port.add_run(_graph(labelled=True))
    version, log_length = port.row().version, len(port.log())
    # A done handoff without its label: the engine accepts the first input, not the second.
    unlabelled = Commit(
        (
            HandoffReceived(slot_id=SLOT, body=BODY),
            HandoffEvaluated(slot_id=SLOT, outcome="accepted"),
        ),
        ToolReply(accepted=True, next=STOP),
    )

    with caplog.at_level(logging.INFO, logger=DISPATCH_LOGGER):
        reply = await ToolDispatcher(port, _planner(unlabelled)).dispatch(_call())

    assert (reply.accepted, reply.reason) == (False, "handoff.invalid")
    assert (reply.field, reply.allowed_values) == ("label", ("ok", "broken"))
    # Nothing of the handoff is written; the refusal is counted as the planner's are.
    assert [entry.input for entry in port.log()[log_length:]] == [
        RejectionObserved(slot_id=SLOT, code="handoff.invalid")
    ]
    assert port.row().version == version + 1
    slot = port.state().slots[0]
    assert (slot.status, slot.handoff) == ("working", None)
    assert port.state().reject_streaks[0].count == 1
    assert list(port.stored_replies().values()) == [reply.to_json()]
    levels = [record.levelno for record in caplog.records if record.name == DISPATCH_LOGGER]
    assert levels == [logging.WARNING]


async def test_an_unknown_engine_code_is_a_transport_error(
    port: InMemoryDecisionPort, caplog: pytest.LogCaptureFixture
) -> None:
    port.add_run(_graph())
    version = port.row().version
    # The reducer answers an evaluation of a working slot with a generic refusal.
    early = Commit(
        (HandoffEvaluated(slot_id=SLOT, outcome="accepted"),), ToolReply(accepted=True, next=STOP)
    )

    with caplog.at_level(logging.WARNING, logger="coral.tools.dispatch"):
        with pytest.raises(TransportError) as refused:
            await ToolDispatcher(port, _planner(early)).dispatch(_call())

    assert "effect_completed" not in str(refused.value)
    assert port.row().version == version
    assert any("rejected" in record.getMessage() for record in caplog.records)


async def test_a_refused_observation_still_answers_its_reply(port: InMemoryDecisionPort) -> None:
    port.add_run(_graph(), [PauseRun(reason="user", detail="")])
    version, log_length = port.row().version, len(port.log())
    invalid = ToolReply(
        accepted=False, reason="handoff.invalid", next="Fix status.", field="status"
    )
    observed = Commit(
        (RejectionObserved(slot_id=SLOT, code="handoff.invalid"),), invalid, observation=True
    )

    reply = await ToolDispatcher(port, _planner(observed)).dispatch(_call())

    assert reply == invalid
    assert (port.row().version, len(port.log())) == (version, log_length)
    assert port.stored_replies() == {}


async def test_a_slow_decision_times_out_and_its_retry_gets_the_reply(
    port: InMemoryDecisionPort,
) -> None:
    port.add_run(_graph())
    held = _HeldPort(port)

    with pytest.raises(TransportError):
        await ToolDispatcher(held, PLANNERS, wait_s=0.01).dispatch(_call())
    held.release.set()
    await poll_until_async(port.stored_replies)

    # The resend (here through another server's dispatcher) reads the stored reply.
    assert await ToolDispatcher(held, PLANNERS).dispatch(_call()) == ToolReply(
        accepted=True, next=STOP
    )
    assert port.decide_calls == 1


def test_the_submit_planner_is_registered() -> None:
    assert PLANNERS[SUBMIT] is plan_submit


class _ReplicaPort:
    """The fake port seen from one server replica; its first plan waits for the other replica's."""

    def __init__(self, inner: InMemoryDecisionPort, barrier: threading.Barrier) -> None:
        self.inner = inner
        self.barrier = barrier

    def find_reply(self, workspace_id: int, run_id: str, cksum: bytes) -> ToolReply | None:
        return self.inner.find_reply(workspace_id, run_id, cksum)

    def decide(self, workspace_id: int, run_id: str, planner: Planner, cksum: bytes) -> ToolReply:
        waited = False

        def together(snapshot: RunSnapshot) -> Plan:
            nonlocal waited
            if not waited:
                waited = True
                self.barrier.wait()
            return planner(snapshot)

        return self.inner.decide(workspace_id, run_id, together, cksum)


def _invalid_call(op: str) -> EngineToolCall:
    return EngineToolCall(
        binding=step_binding(SLOT),
        tool=SUBMIT,
        arguments={**ARGUMENTS, "status": "maybe"},
        operation_id=op,
    )


async def test_a_resent_invalid_call_is_counted_once(port: InMemoryDecisionPort) -> None:
    port.add_run(_graph())
    dispatcher = ToolDispatcher(port, PLANNERS)

    first = await dispatcher.dispatch(_invalid_call("op-1"))
    again = await dispatcher.dispatch(_invalid_call("op-1"))
    restarted = await ToolDispatcher(port, PLANNERS).dispatch(_invalid_call("op-1"))

    assert first == again == restarted
    assert (first.reason, first.field) == ("handoff.invalid", "status")
    assert port.decide_calls == 1
    assert sum(entry.input.kind == "rejection_observed" for entry in port.log()) == 1


async def test_two_replicas_sending_one_operation_id_commit_once(
    port: InMemoryDecisionPort,
) -> None:
    port.add_run(_graph())
    barrier = threading.Barrier(2, timeout=10)
    replicas = [ToolDispatcher(_ReplicaPort(port, barrier), PLANNERS) for _ in range(2)]

    # Both plan from one snapshot; the loser's next attempt finds the winner's stored reply.
    replies = await asyncio.gather(*(replica.dispatch(_call()) for replica in replicas))

    assert replies == [ToolReply(accepted=True, next=STOP)] * 2
    assert (port.decide_calls, port.plan_calls) == (2, 2)
    assert len(port.stored_replies()) == 1
    assert sum(entry.input.kind == "handoff_received" for entry in port.log()) == 1


async def test_concurrent_handoffs_under_new_operation_ids_commit_once(
    port: InMemoryDecisionPort,
) -> None:
    port.add_run(_graph())
    dispatcher = ToolDispatcher(port, PLANNERS)

    replies = await asyncio.gather(
        *(dispatcher.dispatch(_call(op=f"op-{index}")) for index in range(8))
    )

    assert all(reply.accepted and reply.next == STOP for reply in replies)
    assert sorted(reply.duplicate for reply in replies) == [False] + [True] * 7
    assert len(port.stored_replies()) == 1
    assert sum(entry.input.kind == "handoff_received" for entry in port.log()) == 1


async def test_concurrent_invalid_calls_pause_the_run_after_exactly_three(
    port: InMemoryDecisionPort,
) -> None:
    port.add_run(_graph())
    dispatcher = ToolDispatcher(port, PLANNERS)

    replies = await asyncio.gather(
        *(dispatcher.dispatch(_invalid_call(f"op-{index}")) for index in range(6))
    )

    assert (
        sorted(str(reply.reason) for reply in replies)
        == ["handoff.invalid"] * 3 + ["run.paused"] * 3
    )
    assert sum(entry.input.kind == "rejection_observed" for entry in port.log()) == 3
    assert port.state().status == "paused"
    assert [cause.reason for cause in port.state().causes] == ["rejected_calls"]


@pytest.mark.parametrize("operation_id", [None, "", "x" * 129], ids=["none", "empty", "long"])
async def test_a_missing_or_malformed_operation_id_is_refused_uncounted(
    port: InMemoryDecisionPort, operation_id: str | None
) -> None:
    port.add_run(_graph())
    version = port.row().version
    call = EngineToolCall(
        binding=step_binding(SLOT), tool=SUBMIT, arguments=ARGUMENTS, operation_id=operation_id
    )

    with pytest.raises(TransportError, match="operation id"):
        await ToolDispatcher(port, PLANNERS).dispatch(call)

    assert (port.find_reply_calls, port.decide_calls, port.row().version) == (0, 0, version)
    longest = await ToolDispatcher(port, PLANNERS).dispatch(_call(op="x" * 128))
    assert longest.accepted


def test_checksum_parts_cannot_run_into_each_other() -> None:
    assert operation_checksum("r", "a:b", "t", "x") != operation_checksum("r", "a", "b:t", "x")
    assert operation_checksum("r", "a", "t", "b:x") != operation_checksum("r", "a:t", "b", "x")
    assert operation_checksum("r", "", "t", "x") != operation_checksum("r", "t", "", "x")


class _OverlapPort:
    """The fake port, noting how many decisions run at once.

    The first decision waits briefly for a second one to start beside it, so an
    overlap that the dispatcher allows is seen rather than missed.
    """

    def __init__(self, inner: InMemoryDecisionPort) -> None:
        self.inner = inner
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.overlapped = threading.Event()

    def find_reply(self, workspace_id: int, run_id: str, cksum: bytes) -> ToolReply | None:
        return self.inner.find_reply(workspace_id, run_id, cksum)

    def decide(self, workspace_id: int, run_id: str, planner: Planner, cksum: bytes) -> ToolReply:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            first = self.peak == 1
        if self.active >= 2:
            self.overlapped.set()
        if first:
            self.overlapped.wait(0.5)
        try:
            return self.inner.decide(workspace_id, run_id, planner, cksum)
        finally:
            with self._lock:
                self.active -= 1


async def test_decisions_on_one_run_take_turns_and_other_runs_do_not_wait(
    port: InMemoryDecisionPort,
) -> None:
    port.add_run(_graph(roster=["implementer", "reviewer"]))
    port.add_run(_graph(), run_id="run-2")
    same_run = _OverlapPort(port)
    dispatcher = ToolDispatcher(same_run, PLANNERS)

    replies = await asyncio.gather(
        dispatcher.dispatch(_call(session="sess-a", slot="work||:0", op="op-a")),
        dispatcher.dispatch(_call(session="sess-b", slot="work||:1", op="op-b")),
    )

    assert all(reply.accepted for reply in replies)
    assert same_run.peak == 1
    assert port.plan_calls == 2

    other_runs = _OverlapPort(port)
    dispatcher = ToolDispatcher(other_runs, PLANNERS)
    other = EngineToolCall(
        binding=step_binding(SLOT, run_id="run-2", session_id="sess-c"),
        tool=SUBMIT,
        arguments=ARGUMENTS,
        operation_id="op-c",
    )
    await asyncio.gather(
        dispatcher.dispatch(_call(session="sess-a", slot="work||:0", op="op-d")),
        dispatcher.dispatch(other),
    )
    assert other_runs.peak == 2


async def test_past_the_in_flight_cap_a_new_call_is_told_busy_uncounted(
    port: InMemoryDecisionPort, caplog: pytest.LogCaptureFixture
) -> None:
    port.add_run(_graph())
    held = _HeldPort(port)
    dispatcher = ToolDispatcher(held, PLANNERS, max_in_flight=1)
    caplog.set_level(logging.INFO, logger=DISPATCH_LOGGER)

    first = asyncio.create_task(dispatcher.dispatch(_call(op="op-1")))
    assert await asyncio.to_thread(held.entered.wait, 10)
    busy = await dispatcher.dispatch(_invalid_call("op-2"))
    # A resend of the call in flight joins it instead of counting against the cap.
    resent = asyncio.create_task(dispatcher.dispatch(_call(op="op-1")))
    held.release.set()

    assert (busy.accepted, busy.reason, busy.allowed_values) == (
        False,
        "evaluation_in_progress",
        (),
    )
    assert "again" in busy.next
    assert await first == await resent == ToolReply(accepted=True, next=STOP)
    assert port.decide_calls == 1
    assert not any(entry.input.kind == "rejection_observed" for entry in port.log())
    assert any("too many decisions in flight" in record.getMessage() for record in caplog.records)
    # The cap frees up once the decision is done: the next call is decided (the slot closed).
    assert (await dispatcher.dispatch(_invalid_call("op-3"))).reason == "slot_closed"
    assert port.decide_calls == 2


class _FailingPort(_HeldPort):
    """The held fake port whose decision fails once released."""

    def decide(self, workspace_id: int, run_id: str, planner: Planner, cksum: bytes) -> ToolReply:
        self.entered.set()
        assert self.release.wait(10)
        raise RuntimeError("database went away")


async def test_a_failure_no_caller_waits_for_is_logged(
    port: InMemoryDecisionPort, caplog: pytest.LogCaptureFixture
) -> None:
    port.add_run(_graph())
    failing = _FailingPort(port)
    caplog.set_level(logging.WARNING, logger=DISPATCH_LOGGER)

    with pytest.raises(TransportError):
        await ToolDispatcher(failing, PLANNERS, wait_s=0.01).dispatch(_call())
    failing.release.set()

    def failure_logged() -> bool:
        return any(record.levelno == logging.ERROR for record in caplog.records)

    await poll_until_async(failure_logged)
    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert "sess-1" in errors[0].getMessage()


async def test_a_store_pause_that_wins_the_race_is_answered_not_counted(
    port: InMemoryDecisionPort,
) -> None:
    port.add_run(_graph())
    # A drift pause commits between this call's plan and its write.
    port.before_next_write(
        lambda: port.set_row(status=RunStatus.PAUSED, pause_reason=RunPauseReason.DRIFT)
    )

    reply = await ToolDispatcher(port, PLANNERS).dispatch(_invalid_call("op-1"))

    assert (reply.reason, reply.next) == ("run.paused", stop_paused("drift"))
    assert port.plan_calls == 2
    assert not any(entry.input.kind == "rejection_observed" for entry in port.log())
    assert port.stored_replies() == {}
