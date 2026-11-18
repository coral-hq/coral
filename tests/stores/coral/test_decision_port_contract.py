"""The ``RunDecisionPort`` contract, run against the in-memory fake and the SQL port.

Each contract case gets a harness: a port over one started two-step run whose
implementer is working, and what other writers do to that run (an engine commit,
a change no planner reads, a drift pause). The SQL harness runs on every DB
lane, reads its state back through a fresh bridge and replays its log. Cases
that only the store can show (one database version, the reply-key conflict,
backoff, a commit that cannot be built, a graph that cannot load) follow the
contract cases.
"""

from __future__ import annotations

import hashlib
import random
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.bridge.codec import decode_entries
from coral.bridge.keys import effect_work_id
from coral.bridge.mapping import UnsupportedStance
from coral.bridge.port import StoreDecisionPort
from coral.bridge.service import LOAD_FAILED_DETAIL, EngineLoadFailed
from coral.db import ToolReplyRow, WorkflowVersionRow
from coral.db.enum_codecs import (
    ActorKind,
    LogKind,
    RunPauseReason,
    RunStatus,
    SessionBindingRole,
    SlotRole,
    WorkStatus,
)
from coral.engine.types import (
    EffectCompleted,
    HandoffEvaluated,
    HandoffReceived,
    Input,
    PauseRun,
    RejectionObserved,
    RunState,
)
from coral.model.ir import CompiledGraph
from coral.stores.protocols import LogEntryDraft, RunContended, RunNotFound, Transition
from coral.stores.session_bindings import (
    BindingConflict,
    SessionBindingDraft,
    SessionBindings,
    SqlAlchemySessionBindingStore,
)
from coral.tools.catalog import SUBMIT_HANDOFF
from coral.tools.dispatch import EngineToolCall, ToolDispatcher
from coral.tools.handlers import PLANNERS
from coral.tools.handlers.submit_handoff import plan as plan_submit
from coral.tools.port import (
    MAX_DECIDE_ATTEMPTS,
    Commit,
    EngineRefused,
    Plan,
    Planner,
    Reply,
    RunDecisionPort,
    RunSnapshot,
)
from coral.tools.replies import STOP, run_paused
from coral.tools.schemas import HANDOFF_BODY_MAX_BYTES, ToolReply
from omnigent.db.utils import get_or_create_engine
from tests.coral.bridge._scripted_runs import handoff_body
from tests.coral.bridge._world import IMPLEMENT, WORKSPACE, World, start
from tests.coral.tools.fake_decision_port import InMemoryDecisionPort, step_binding
from tests.coral.workflow_builders import compile_text, fixture_text
from tests.coral.workspace._executor_fakes import FakeBindings
from tests.stores.coral._faults import fresh_process, run_racing

SESSION = "s" * 32
ACTIVATION = IMPLEMENT.rsplit(":", 1)[0]
# The two-step workflow after its author edited it; later runs pin this one.
EDITED_TWO_STEPS = fixture_text("two_steps").replace(
    "Implement the change", "Implement the edited change"
)


def _cksum(name: str) -> bytes:
    return hashlib.sha256(name.encode()).digest()


class PortHarness(Protocol):
    """A port over one started run, and the other writers of that run."""

    port: RunDecisionPort
    run_id: str
    graph: CompiledGraph
    bindings: SessionBindings

    def version(self) -> int: ...

    def state(self) -> RunState: ...

    def kinds(self) -> list[str]:
        """The input kind of every stored engine entry, in log order."""
        ...

    def actors(self) -> list[tuple[str, str | None]]:
        """Every stored engine entry's input kind and who asked for it."""
        ...

    def apply(self, *inputs: Input) -> None:
        """Another writer commits engine inputs."""
        ...

    def bump(self) -> None:
        """Another writer commits a change no planner reads."""
        ...

    def drift_pause(self) -> None: ...

    def reopened(self) -> RunDecisionPort:
        """A port in a new process over the same storage."""
        ...

    def replica(self) -> RunDecisionPort:
        """Another server's port over the same storage."""
        ...

    def start_other_run(self, yaml_text: str) -> CompiledGraph:
        """A later run of the same definition; returns the graph it pinned."""
        ...


class _MemoryHarness:
    def __init__(self) -> None:
        self.graph = compile_text(fixture_text("two_steps"))[0]
        self.fake = InMemoryDecisionPort()
        self.fake.add_run(self.graph)
        self.port: RunDecisionPort = self.fake
        self.run_id = "run-1"
        self.bindings: SessionBindings = FakeBindings(reservable=True)

    def version(self) -> int:
        return self.fake.row().version

    def state(self) -> RunState:
        return self.fake.state()

    def kinds(self) -> list[str]:
        return [entry.input.kind for entry in self.fake.log()]

    def actors(self) -> list[tuple[str, str | None]]:
        return self.fake.actors()

    def apply(self, *inputs: Input) -> None:
        self.fake.apply(*inputs)

    def bump(self) -> None:
        self.fake.apply()

    def drift_pause(self) -> None:
        self.fake.set_row(status=RunStatus.PAUSED, pause_reason=RunPauseReason.DRIFT)

    def reopened(self) -> RunDecisionPort:
        # Everything the fake stores lives in this one object.
        return self.fake

    def replica(self) -> RunDecisionPort:
        return self.fake

    def start_other_run(self, yaml_text: str) -> CompiledGraph:
        graph = compile_text(yaml_text)[0]
        self.fake.add_run(graph, run_id="run-2")
        return graph

    def close(self) -> None:
        self.fake.assert_folds()


class _StoreHarness:
    def __init__(self, db_uri: str) -> None:
        self.db_uri = db_uri
        self.world = World.sql(db_uri)
        self.run_id = start(self.world).id
        self._complete("create_session", {"session_id": SESSION, "role": "step", "generation": 1})
        self._complete("send_input", {"session_id": SESSION, "stable_id": "m1"})
        self.sleeps: list[float] = []
        self.port: RunDecisionPort = StoreDecisionPort(self.world.bridge, sleep=self.sleeps.append)
        self.graph = self.world.bridge.load(workspace_id=WORKSPACE, run_id=self.run_id).graph
        self.bindings: SessionBindings = SqlAlchemySessionBindingStore(db_uri)

    def _complete(self, kind: str, payload: dict[str, object]) -> None:
        def inputs(snapshot: Any) -> tuple[Input, ...]:
            receipted = {receipt.key for receipt in snapshot.state.receipts}
            return tuple(
                EffectCompleted(effect_key=effect.effect_key, payload=payload)
                for effect in snapshot.state.effects
                if effect.kind == kind and effect.effect_key not in receipted
            )

        self.world.bridge.commit_inputs(workspace_id=WORKSPACE, run_id=self.run_id, inputs=inputs)

    def version(self) -> int:
        return self.world.run(self.run_id).version

    def state(self) -> RunState:
        return self.world.assert_fold_matches(self.run_id)

    def kinds(self) -> list[str]:
        return [entry.input.kind for entry in decode_entries(self.world.engine_log(self.run_id))]

    def actors(self) -> list[tuple[str, str | None]]:
        rows = [row for row in self.world.engine_log(self.run_id) if not row.audit_only]
        entries = decode_entries(rows)
        return [
            (entry.input.kind, row.actor_ref) for entry, row in zip(entries, rows, strict=True)
        ]

    def apply(self, *inputs: Input) -> None:
        commit = self.world.bridge.commit_inputs(
            workspace_id=WORKSPACE, run_id=self.run_id, inputs=lambda _snapshot: inputs
        )
        assert commit.outcome.applied

    def bump(self) -> None:
        # A row the engine log skips: it moves the version and nothing a planner reads.
        noted = LogEntryDraft(
            kind=int(LogKind.SIGNAL_IGNORED), actor_kind=int(ActorKind.ENGINE), body="{}"
        )
        self.world.runs.apply_transition(
            self.run_id, self.version(), Transition(logs=(noted,)), workspace_id=WORKSPACE
        )

    def drift_pause(self) -> None:
        self.world.bridge.pause_for_drift(
            workspace_id=WORKSPACE,
            run_id=self.run_id,
            cause="session_archived",
            body={"kind": "pause_run", "reason": "drift", "cause": "session_archived"},
            checksum_parts=("coral-drift", self.run_id, "session_archived", SESSION),
            now_us=self.world.clock.epoch * 1_000_000,
        )

    def reopened(self) -> RunDecisionPort:
        fresh_process(self.db_uri)
        return StoreDecisionPort(World.sql(self.db_uri).bridge, sleep=self.sleeps.append)

    def replica(self) -> RunDecisionPort:
        return StoreDecisionPort(World.sql(self.db_uri).bridge, sleep=self.sleeps.append)

    def start_other_run(self, yaml_text: str) -> CompiledGraph:
        run = start(self.world, yaml_text, start_key="start-2")
        return self.world.bridge.load(workspace_id=WORKSPACE, run_id=run.id).graph

    def close(self) -> None:
        self.state()


@pytest.fixture(params=["memory", "store"])
def harness(request: pytest.FixtureRequest) -> Iterator[_MemoryHarness | _StoreHarness]:
    built = (
        _MemoryHarness()
        if request.param == "memory"
        else _StoreHarness(request.getfixturevalue("coral_db_uri"))
    )
    yield built
    built.close()


@dataclass
class _Counted:
    """A planner that counts its calls and runs ``before_answer`` after the first ``times``."""

    inner: Planner
    before_answer: Callable[[], object] | None = None
    times: int = 1
    calls: int = 0
    graphs: list[CompiledGraph] = field(default_factory=list)

    def __call__(self, snapshot: RunSnapshot) -> Plan:
        self.calls += 1
        self.graphs.append(snapshot.graph)
        plan = self.inner(snapshot)
        if self.before_answer is not None and self.calls <= self.times:
            # Another writer commits between this plan and the port's write.
            self.before_answer()
        return plan


def _submit(
    run_id: str, arguments: dict[str, object] | None = None, *, session: str = SESSION
) -> Planner:
    """The real submit planner for the implementer's session."""
    call = EngineToolCall(
        binding=step_binding(IMPLEMENT, session_id=session, run_id=run_id),
        tool=SUBMIT_HANDOFF.name,
        arguments=arguments or {"activation_id": ACTIVATION, "status": "done", "report": "Done."},
        operation_id="op-1",
    )
    return lambda snapshot: plan_submit(snapshot, call=call)


def _never(snapshot: RunSnapshot) -> Plan:
    raise AssertionError("a stored reply must answer without planning")


def _handoffs(harness: PortHarness) -> int:
    return harness.kinds().count("handoff_received")


ACCEPTED = ToolReply(accepted=True, next=STOP)


# ── contract cases ───────────────────────────────────────────────────────────


def test_a_stored_reply_answers_without_planning(harness: PortHarness) -> None:
    cksum = _cksum("stored")
    assert harness.port.find_reply(WORKSPACE, harness.run_id, cksum) is None

    reply = harness.port.decide(WORKSPACE, harness.run_id, _submit(harness.run_id), cksum)
    version = harness.version()

    assert reply == ACCEPTED
    assert harness.port.find_reply(WORKSPACE, harness.run_id, cksum) == reply
    assert harness.port.decide(WORKSPACE, harness.run_id, _never, cksum) == reply
    # A restarted server reads the same reply back.
    reopened = harness.reopened()
    assert reopened.find_reply(WORKSPACE, harness.run_id, cksum) == reply
    assert reopened.decide(WORKSPACE, harness.run_id, _never, cksum) == reply
    assert harness.version() == version
    assert _handoffs(harness) == 1
    # After the run moves on, the resend still gets its first reply, not a new plan's.
    harness.apply(PauseRun(reason="user", detail="look"))
    assert reopened.decide(WORKSPACE, harness.run_id, _never, cksum) == reply


@pytest.mark.parametrize("missing", ["run", "workspace"])
def test_a_missing_run_raises_run_not_found(harness: PortHarness, missing: str) -> None:
    workspace_id, run_id = (
        (WORKSPACE, "0" * 32) if missing == "run" else (WORKSPACE + 1, harness.run_id)
    )
    planner = _Counted(_never)

    with pytest.raises(RunNotFound):
        harness.port.decide(workspace_id, run_id, planner, _cksum("missing"))

    assert planner.calls == 0
    assert harness.port.find_reply(workspace_id, run_id, _cksum("missing")) is None


def test_a_reply_plan_writes_nothing(harness: PortHarness) -> None:
    version, kinds = harness.version(), harness.kinds()
    answer = ToolReply(accepted=False, reason="evaluation_in_progress", next="Retry shortly.")

    reply = harness.port.decide(
        WORKSPACE, harness.run_id, lambda _snapshot: Reply(answer), _cksum("reply")
    )

    assert reply == answer
    assert (harness.version(), harness.kinds()) == (version, kinds)
    assert harness.port.find_reply(WORKSPACE, harness.run_id, _cksum("reply")) is None


def test_a_refused_input_writes_none_of_the_commit(harness: PortHarness) -> None:
    version, kinds = harness.version(), harness.kinds()
    # The engine accepts the handoff and refuses the evaluation of a slot it does not know.
    partly = Commit(
        (
            HandoffReceived(slot_id=IMPLEMENT, body=handoff_body(ACTIVATION, "Done.")),
            HandoffEvaluated(slot_id="no-such-slot", outcome="accepted"),
        ),
        ACCEPTED,
    )

    with pytest.raises(EngineRefused) as refused:
        harness.port.decide(WORKSPACE, harness.run_id, lambda _snapshot: partly, _cksum("refused"))

    assert refused.value.code == "rejected"
    assert (harness.version(), harness.kinds()) == (version, kinds)
    assert harness.port.find_reply(WORKSPACE, harness.run_id, _cksum("refused")) is None


def test_a_refused_observation_answers_its_reply_and_writes_nothing(
    harness: PortHarness,
) -> None:
    harness.apply(PauseRun(reason="user", detail="look"))
    version, kinds = harness.version(), harness.kinds()
    invalid = ToolReply(
        accepted=False, reason="handoff.invalid", next="Fix status.", field="status"
    )
    observed = Commit(
        (RejectionObserved(slot_id=IMPLEMENT, code="handoff.invalid"),), invalid, observation=True
    )

    reply = harness.port.decide(
        WORKSPACE, harness.run_id, lambda _snapshot: observed, _cksum("observed")
    )

    assert reply == invalid
    assert (harness.version(), harness.kinds()) == (version, kinds)
    assert harness.port.find_reply(WORKSPACE, harness.run_id, _cksum("observed")) is None


def _invalid(run_id: str) -> Planner:
    """The submit planner for a call with a bad status: a counted ``handoff.invalid``."""
    return _submit(run_id, {"activation_id": ACTIVATION, "status": "maybe", "report": "x"})


def test_a_counted_refusal_is_stored_and_a_resend_is_not_counted_again(
    harness: PortHarness,
) -> None:
    cksum = _cksum("counted")
    version = harness.version()
    planner = _Counted(_invalid(harness.run_id))

    reply = harness.port.decide(WORKSPACE, harness.run_id, planner, cksum, actor=SESSION)

    assert (reply.accepted, reply.reason, reply.field) == (False, "handoff.invalid", "status")
    assert harness.version() == version + 1
    assert harness.actors()[-1] == ("rejection_observed", SESSION)
    assert harness.port.find_reply(WORKSPACE, harness.run_id, cksum) == reply
    # Resent, also after a restart: answered from the store, never counted again.
    assert harness.port.decide(WORKSPACE, harness.run_id, _never, cksum) == reply
    assert harness.reopened().decide(WORKSPACE, harness.run_id, _never, cksum) == reply
    assert planner.calls == 1
    assert harness.kinds().count("rejection_observed") == 1
    assert harness.version() == version + 1


def test_one_write_holds_the_entries_their_effects_and_the_reply(harness: PortHarness) -> None:
    version, kinds = harness.version(), harness.kinds()

    reply = harness.port.decide(WORKSPACE, harness.run_id, _submit(harness.run_id), _cksum("one"))

    assert reply == ACCEPTED
    assert harness.version() == version + 1
    assert harness.kinds() == [*kinds, "handoff_received", "handoff_evaluated"]
    state = harness.state()
    (slot,) = (slot for slot in state.slots if slot.id == IMPLEMENT)
    assert slot.status == "closing"
    receipted = {receipt.key for receipt in state.receipts}
    assert [
        effect.kind
        for effect in state.effects
        if effect.subject == IMPLEMENT and effect.effect_key not in receipted
    ] == ["close_slot"]
    assert harness.port.find_reply(WORKSPACE, harness.run_id, _cksum("one")) == reply


@pytest.mark.parametrize("competitor", ["unrelated", "same_handoff"])
def test_a_lost_compare_and_swap_replans(harness: PortHarness, competitor: str) -> None:
    def compete() -> None:
        if competitor == "unrelated":
            harness.bump()
        else:
            body = handoff_body(ACTIVATION, "Done.")
            harness.apply(
                HandoffReceived(slot_id=IMPLEMENT, body=body),
                HandoffEvaluated(slot_id=IMPLEMENT, outcome="accepted"),
            )

    planner = _Counted(_submit(harness.run_id), before_answer=compete)

    reply = harness.port.decide(WORKSPACE, harness.run_id, planner, _cksum("lost"))

    assert planner.calls == 2
    assert _handoffs(harness) == 1
    stored = harness.port.find_reply(WORKSPACE, harness.run_id, _cksum("lost"))
    if competitor == "unrelated":
        assert reply == stored == ACCEPTED
    else:
        # The other writer's handoff is this one: the replan answers its receipt.
        assert reply == ToolReply(accepted=True, next=STOP, duplicate=True)
        assert stored is None


def test_a_run_that_keeps_changing_raises_run_contended(harness: PortHarness) -> None:
    planner = _Counted(_submit(harness.run_id), before_answer=harness.bump, times=99)

    with pytest.raises(RunContended):
        harness.port.decide(WORKSPACE, harness.run_id, planner, _cksum("contended"))

    assert planner.calls == MAX_DECIDE_ATTEMPTS
    assert _handoffs(harness) == 0
    assert harness.port.find_reply(WORKSPACE, harness.run_id, _cksum("contended")) is None


def test_a_drift_pause_between_plan_and_write_forces_a_replan(harness: PortHarness) -> None:
    planner = _Counted(_submit(harness.run_id), before_answer=harness.drift_pause)

    reply = harness.port.decide(WORKSPACE, harness.run_id, planner, _cksum("drift"))

    assert reply == run_paused("drift")
    assert planner.calls == 2
    assert _handoffs(harness) == 0
    assert harness.port.find_reply(WORKSPACE, harness.run_id, _cksum("drift")) is None


def _report_filling_the_body() -> str:
    """A report with non-ASCII text and CRLF whose canonical body is exactly the byte cap.

    Random two-byte characters keep the stored log row from compressing below its cap.
    """
    head = "Ünïcødé 😀 report\r\nsecond line\r\n"
    room = HANDOFF_BODY_MAX_BYTES - len(handoff_body(ACTIVATION, head).encode())
    chooser = random.Random(0)
    filler = "".join(chr(chooser.randrange(0xA0, 0x800)) for _ in range(room // 2))
    report = head + filler + "x" * (room % 2)
    assert len(handoff_body(ACTIVATION, report).encode()) == HANDOFF_BODY_MAX_BYTES
    return report


def test_a_handoff_body_round_trips_byte_for_byte(harness: PortHarness) -> None:
    report = _report_filling_the_body()
    arguments: dict[str, object] = {
        "activation_id": ACTIVATION,
        "status": "done",
        "report": report,
    }
    body = handoff_body(ACTIVATION, report)

    first = harness.port.decide(
        WORKSPACE, harness.run_id, _submit(harness.run_id, arguments), _cksum("body-1")
    )

    assert first == ACCEPTED
    (slot,) = (slot for slot in harness.state().slots if slot.id == IMPLEMENT)
    assert slot.handoff is not None
    assert slot.handoff.encode() == body.encode()
    # Resent under a new operation id after a restart: the stored body still compares equal.
    reopened = harness.reopened()
    again = reopened.decide(
        WORKSPACE, harness.run_id, _submit(harness.run_id, arguments), _cksum("body-2")
    )
    assert again == ToolReply(accepted=True, next=STOP, duplicate=True)
    other = reopened.decide(
        WORKSPACE,
        harness.run_id,
        _submit(harness.run_id, {**arguments, "report": report[:-1] + "y"}),
        _cksum("body-3"),
    )
    assert (other.accepted, other.reason) == (False, "slot_closed")
    assert _handoffs(harness) == 1


def test_two_ports_racing_one_checksum_commit_once(harness: PortHarness) -> None:
    ports = [harness.port, harness.replica()]
    barrier = threading.Barrier(2, timeout=10)
    planners = [
        _Counted(_submit(harness.run_id), before_answer=barrier.wait),
        _Counted(_submit(harness.run_id), before_answer=barrier.wait),
    ]
    version = harness.version()

    outcomes = run_racing(
        2,
        lambda index: ports[index].decide(
            WORKSPACE, harness.run_id, planners[index], _cksum("race")
        ),
    )

    # Both planned from one snapshot; the loser's next attempt finds the winner's reply.
    assert [(outcome.value, outcome.error) for outcome in outcomes] == [(ACCEPTED, None)] * 2
    assert [planner.calls for planner in planners] == [1, 1]
    assert harness.version() == version + 1
    assert _handoffs(harness) == 1
    assert harness.port.find_reply(WORKSPACE, harness.run_id, _cksum("race")) == ACCEPTED


def test_the_snapshot_graph_is_the_pinned_one_after_the_definition_changes(
    harness: PortHarness,
) -> None:
    edited = harness.start_other_run(EDITED_TWO_STEPS)
    assert edited.content_hash != harness.graph.content_hash
    answer = ToolReply(accepted=False, reason="evaluation_in_progress", next="Retry shortly.")
    planner = _Counted(lambda _snapshot: Reply(answer))

    harness.reopened().decide(WORKSPACE, harness.run_id, planner, _cksum("graph"))

    assert planner.graphs == [harness.graph]


def test_a_second_binding_for_one_slot_and_generation_is_refused(harness: PortHarness) -> None:
    def draft(session_id: str, effect_key: str, generation: int = 1) -> SessionBindingDraft:
        return SessionBindingDraft(
            workspace_id=WORKSPACE,
            session_id=session_id,
            run_id=harness.run_id,
            role=SessionBindingRole.STEP,
            effect_key=effect_key,
            slot_id=IMPLEMENT,
            slot_role=SlotRole.STEP_AGENT,
            session_generation=generation,
            host_id="host-1",
        )

    harness.bindings.reserve(draft("a" * 32, "create-1"))

    with pytest.raises(BindingConflict) as conflict:
        harness.bindings.reserve(draft("b" * 32, "create-2"))

    assert conflict.value.fields == ("slot_id", "session_generation")
    # The retried slot's next generation binds.
    assert harness.bindings.reserve(draft("b" * 32, "create-2", 2)).session_generation == 2


async def test_a_dispatched_commit_records_the_calling_session(harness: PortHarness) -> None:
    caller = "c" * 32
    call = EngineToolCall(
        binding=step_binding(IMPLEMENT, session_id=caller, run_id=harness.run_id),
        tool=SUBMIT_HANDOFF.name,
        arguments={"activation_id": ACTIVATION, "status": "done", "report": "Done."},
        operation_id="op-1",
    )

    reply = await ToolDispatcher(harness.port, PLANNERS).dispatch(call)

    assert reply == ACCEPTED
    assert harness.actors()[-2:] == [("handoff_received", caller), ("handoff_evaluated", caller)]


# ── the SQL port only ────────────────────────────────────────────────────────


@pytest.fixture
def store(coral_db_uri: str) -> Iterator[_StoreHarness]:
    built = _StoreHarness(coral_db_uri)
    yield built
    built.close()


def test_the_store_commit_is_one_version_with_its_work_row_and_reply(
    store: _StoreHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    applied: list[dict[str, object]] = []
    real_apply = store.world.runs.apply_transition

    def recording(*args: Any, **kwargs: Any) -> Any:
        applied.append(kwargs)
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(store.world.runs, "apply_transition", recording)
    store.port.decide(WORKSPACE, store.run_id, _submit(store.run_id), _cksum("one"), actor=SESSION)

    version = store.version()
    assert [kwargs["lock_timeout_s"] for kwargs in applied] == [10.0]
    rows = store.world.engine_log(store.run_id)[-2:]
    assert [(row.run_version, row.actor_kind, row.actor_ref) for row in rows] == [
        (version, int(ActorKind.STEP_AGENT), SESSION)
    ] * 2
    with Session(get_or_create_engine(store.db_uri)) as session:
        stored = session.get(ToolReplyRow, (WORKSPACE, store.run_id, _cksum("one")))
        assert stored is not None and stored.run_version == version
    (close,) = (effect for effect in store.state().effects if effect.kind == "close_slot")
    (work,) = store.world.queue.get_work(
        [effect_work_id(store.run_id, close.effect_key)], workspace_id=WORKSPACE
    )
    assert work.status == int(WorkStatus.PENDING)


@pytest.mark.parametrize("stored_first", [True, False], ids=["reply_stored", "other_conflict"])
def test_a_reply_key_conflict_answers_the_stored_reply(
    store: _StoreHarness, monkeypatch: pytest.MonkeyPatch, stored_first: bool
) -> None:
    cksum = _cksum("conflict")
    version = store.version()
    winner = ToolReply(accepted=True, next=STOP, duplicate=True)
    real_apply = store.world.runs.apply_transition
    calls: list[int] = []

    def conflicting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        if len(calls) > 1:
            return real_apply(*args, **kwargs)
        if not stored_first:
            raise IntegrityError("INSERT INTO coral_something", None, Exception("other key"))
        # Another writer's reply under this checksum, at this version.
        with Session(get_or_create_engine(store.db_uri)) as session:
            session.add(
                ToolReplyRow(
                    workspace_id=WORKSPACE,
                    run_id=store.run_id,
                    cksum=cksum,
                    reply=winner.to_json(),
                    run_version=version,
                    created_at_us=0,
                )
            )
            session.commit()
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(store.world.runs, "apply_transition", conflicting)

    if stored_first:
        reply = store.port.decide(WORKSPACE, store.run_id, _submit(store.run_id), cksum)
        assert reply == winner
        assert store.sleeps and len(store.sleeps) == 1
    else:
        with pytest.raises(IntegrityError):
            store.port.decide(WORKSPACE, store.run_id, _submit(store.run_id), cksum)
    assert len(calls) == 1
    assert store.version() == version
    assert _handoffs(store) == 0


def _commit_before_the_first_load(
    store: _StoreHarness, monkeypatch: pytest.MonkeyPatch, other_server: Callable[[], object]
) -> None:
    """Run ``other_server`` after the port's stored-reply check and before its first load."""
    real_load = store.world.bridge.load
    fired: list[bool] = []

    def load(**kwargs: Any) -> Any:
        if not fired:
            fired.append(True)
            other_server()
        return real_load(**kwargs)

    monkeypatch.setattr(store.world.bridge, "load", load)


@pytest.mark.parametrize("call", ["accepted", "third_invalid"])
def test_the_same_call_committed_after_the_reply_check_answers_the_stored_reply(
    store: _StoreHarness, monkeypatch: pytest.MonkeyPatch, call: str
) -> None:
    planner = _submit if call == "accepted" else _invalid
    if call == "third_invalid":
        for index in range(2):
            store.port.decide(
                WORKSPACE, store.run_id, _invalid(store.run_id), _cksum(f"bad{index}")
            )
    cksum = _cksum("window")
    other = store.replica()
    won: list[ToolReply] = []
    _commit_before_the_first_load(
        store,
        monkeypatch,
        lambda: won.append(other.decide(WORKSPACE, store.run_id, planner(store.run_id), cksum)),
    )

    # Planned after the other server's commit, this call must still answer its stored reply.
    reply = store.port.decide(WORKSPACE, store.run_id, planner(store.run_id), cksum)

    assert reply == won[0] == store.port.find_reply(WORKSPACE, store.run_id, cksum)
    if call == "accepted":
        assert _handoffs(store) == 1
    else:
        assert store.kinds().count("rejection_observed") == 3


def test_each_lost_attempt_backs_off_about_10_ms(store: _StoreHarness) -> None:
    planner = _Counted(_submit(store.run_id), before_answer=store.bump, times=99)

    with pytest.raises(RunContended):
        store.port.decide(WORKSPACE, store.run_id, planner, _cksum("contended"))

    assert len(store.sleeps) == MAX_DECIDE_ATTEMPTS - 1
    assert all(0.005 <= delay <= 0.015 for delay in store.sleeps)


def test_a_commit_that_cannot_be_built_pauses_the_run_and_answers_paused(
    store: _StoreHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object) -> None:
        raise UnsupportedStance("slot has no step stance")

    monkeypatch.setattr("coral.bridge.commit.map_effect", refuse)

    reply = store.port.decide(WORKSPACE, store.run_id, _submit(store.run_id), _cksum("unbuilt"))

    assert reply == run_paused("failure_path")
    run = store.world.run(store.run_id)
    assert (run.status, run.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    causes = [(cause.reason, cause.detail) for cause in store.state().causes]
    assert causes == [("failure_path", "unsupported_stance")]
    assert _handoffs(store) == 0
    assert store.port.find_reply(WORKSPACE, store.run_id, _cksum("unbuilt")) is None


def test_a_run_whose_pinned_graph_cannot_load_raises_unplanned_and_pauses_once(
    store: _StoreHarness,
) -> None:
    version_id = store.world.run(store.run_id).version_id
    pinned = (WorkflowVersionRow.workspace_id == WORKSPACE, WorkflowVersionRow.id == version_id)

    def set_compiled(compiled_json: str) -> None:
        with Session(get_or_create_engine(store.db_uri)) as session:
            session.execute(
                update(WorkflowVersionRow).where(*pinned).values(compiled_json=compiled_json)
            )
            session.commit()

    with Session(get_or_create_engine(store.db_uri)) as session:
        original = session.get(WorkflowVersionRow, (WORKSPACE, version_id))
        assert original is not None
        compiled = original.compiled_json
    set_compiled('{"broken": true}')
    port = store.reopened()
    planner = _Counted(_never)

    for _ in range(2):
        with pytest.raises(EngineLoadFailed):
            port.decide(WORKSPACE, store.run_id, planner, _cksum("unloadable"))

    set_compiled(compiled)
    assert planner.calls == 0
    run = store.world.run(store.run_id)
    assert (run.status, run.pause_reason) == (
        int(RunStatus.PAUSED),
        int(RunPauseReason.FAILURE_PATH),
    )
    paused = [
        row
        for row in store.world.runs.read_log(store.run_id, workspace_id=WORKSPACE)
        if row.kind == int(LogKind.PAUSED)
    ]
    assert [LOAD_FAILED_DETAIL in row.body for row in paused] == [True]
    assert store.port.find_reply(WORKSPACE, store.run_id, _cksum("unloadable")) is None
