"""A retried step restarts in process: fenced, salvaged and reset, then briefed, across crashes.

L3 on the CRL-149 world (``tests/coral/bridge/_world.py``) over a SQL database: the
real bridge, drainer, hold policy and executors, the restart among them. The sessions
are the world's fakes (its binding facade over ``FakeSessionFacade`` and the fake
dispatch); the run worktree is a real linked git worktree served by Coral's own host
handlers through the in-process host channel. A crash is a ``SimulatedCrash``, and the
restart is a new process on the same database (``restarted``) whose sessions and host
outlived the old one. Tool-call verdicts are the run guard's over the stored run row
and the session's closed label, as Coral's policy provider builds them.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from coral.bridge.codec import decode_entries
from coral.bridge.keys import slot_session_id, store_activation_id
from coral.bridge.mapping import RECOVERY_RESTART, resync_draft
from coral.db import WorkRow
from coral.db.enum_codecs import RunStatus, SlotRole, WorkStatus
from coral.db.migrate import ensure_coral_schema
from coral.engine.lifecycle import retryable_activations
from coral.engine.types import RunnerLost, SessionFailed
from coral.model.ids import effect_session_id
from coral.omni.host.ops import workspace_op_handlers
from coral.omni.host.ops._git import Git
from coral.omni.policies.run_guard import run_guard
from coral.omni.policies.state import RunStatusCache
from coral.omni.protocols import CoralSessionError, SessionCreateRequest, SessionState
from coral.omni.server.dispatch import OmnigentSessionDispatch
from coral.omni.server.sessions import session_state_of
from coral.omni.server.status_edges import CoralStatusEdges
from coral.queue import FinishedWork
from coral.queue.executors import EffectCompleted, EffectOutcome
from coral.recovery.ladder import restart_executor
from coral.recovery.relaunch import LivenessPass, LivenessRef
from coral.slots.close import CloseBounds
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun
from coral.tools.catalog import SUBMIT_HANDOFF
from coral.tools.dispatch import EngineToolCall
from coral.tools.schemas import ToolReply
from coral.workspace.ops import OpName, WorkspaceOpError
from coral.workspace.run_worktree import run_branch_name
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID, workspace_scope
from omnigent.policies.schema import PolicyEvent
from omnigent.runtime import get_conversation_store
from omnigent.server import session_live_state, shutdown_state
from omnigent.server.routes import sessions as omnigent_sessions
from omnigent.server.session_live_state import SessionStatusEdge
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.bridge._world import (
    IMPLEMENT,
    REVIEW,
    WORKSPACE,
    Agent,
    Orchestrator,
    Sessions,
    World,
    blocked,
    restarted,
    run_id_for,
    run_spec,
    serving,
    start,
)
from tests.coral.omni._runner_tunnel import (
    TunnelServer,
    runner_tunnel,
    tunnel_server,  # noqa: F401 -- pytest injects the imported fixture
)
from tests.coral.omni.host.ops._worktrees import (
    LinkedWorktree,
    isolate_git_home,
    make_linked_worktree,
    run_git,
)
from tests.coral.omni.test_ac2_stop_cancel_end_to_end import _bound_session, _session_running
from tests.coral.workflow_builders import arrow, end, fixture_text, step, workflow_text
from tests.coral.workflow_builders import start as start_node
from tests.coral.workspace._executor_fakes import (
    FakeBindings,
    FakeChannels,
    FakeHostChannel,
    FakeIntents,
    InProcessHostChannel,
    RecordingScopeRunner,
    effect_context,
    start_run,
)
from tests.coral.workspace._executor_fakes import step_binding as executor_step_binding
from tests.server.integration.test_sessions_tunnel_three_layer import (
    _TunnelStack,
    tunnel_three_layer_stack,  # noqa: F401 -- pytest injects the imported fixture
)
from tests.stores.coral._faults import SimulatedCrash, crash_around_async, fresh_process

RUN_ID = run_id_for()
# Each scripted call's operation id; the Agent's are ``op-<n>``, and a repeated id of one
# session is answered from its record.
_OPERATIONS = itertools.count(1)
HOST = "host-1"
# The world drainer's work lease.
LEASE_S = 60
# A step of two slots: a writer and a reader, both retried together.
PAIR = workflow_text(
    [start_node(), step("work", roster=["implementer", "reviewer"]), end()],
    [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
)
WRITER, READER = "work||:0", "work||:1"
# The workspace and slot of the fence over the real dispatch (no Coral world there).
AC2_WORKSPACE = DEFAULT_WORKSPACE_ID
SLOT_OF_THE_FENCE = "review||:0"
# The review loop's work step, on its first pass and on the pass the decision sent back.
LOOP_PASS_ONE, LOOP_PASS_TWO = "work||a4:1:0", "work||a4:2:0"


@dataclass
class _Host:
    """The run worktree's host: Coral's real handlers in process, each request recorded."""

    channel: InProcessHostChannel
    requests: list[tuple[str, str | None]] = field(default_factory=list)
    # An op that fails as scripted, after it was recorded.
    fail: dict[str, WorkspaceOpError] = field(default_factory=dict)

    async def request(
        self,
        host_id: str,
        op: OpName,
        *,
        root: str,
        params: Mapping[str, object],
        timeout_s: float,
        op_key: str | None,
    ) -> Mapping[str, object]:
        self.requests.append((op, op_key))
        if op in self.fail:
            raise self.fail[op]
        return await self.channel.request(
            host_id, op, root=root, params=params, timeout_s=timeout_s, op_key=op_key
        )

    def ops(self, *names: str) -> list[str]:
        return [op for op, _key in self.requests if op in names]


@pytest.fixture
def worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LinkedWorktree:
    """The run's worktree on its own branch, under a git home with no user settings."""
    isolate_git_home(monkeypatch, tmp_path / "home")
    return make_linked_worktree(tmp_path / "work", branch=run_branch_name(RUN_ID))


@pytest.fixture
def host() -> _Host:
    return _Host(InProcessHostChannel(host_id=HOST, handlers=workspace_op_handlers()))


@pytest.fixture
def world(db_uri: str) -> World:
    ensure_coral_schema(db_uri)
    return World.sql(db_uri)


def _start(world: World, worktree: LinkedWorktree, yaml_text: str) -> None:
    spec = run_spec(
        host_id=HOST,
        repo_path=str(worktree.repo_root),
        worktree_path=str(worktree.root),
        base_commit=worktree.base,
    )
    start(world, yaml_text, spec=spec)


async def _submit(sessions: Sessions, session_id: str, **fields: object) -> ToolReply:
    """One ``coral_submit_handoff`` from ``session_id``, as its runner would send it."""
    binding = await asyncio.to_thread(sessions.bindings.find_by_session, WORKSPACE, session_id)
    assert binding is not None
    activation = (binding.slot_id or "").rsplit(":", 1)[0]
    arguments: dict[str, object] = {
        "activation_id": activation,
        "status": "done",
        "report": "Worked on it.",
        **fields,
    }
    call = EngineToolCall(
        binding=binding,
        tool=SUBMIT_HANDOFF.name,
        arguments=arguments,
        operation_id=f"scripted-{next(_OPERATIONS)}",
    )
    return await sessions.dispatcher.dispatch(call)


async def _block(sessions: Sessions, slot_id: str) -> str:
    """The slot's session hands off blocked: with no failure arrow the run pauses."""
    session_id = sessions.session_of(RUN_ID, slot_id)
    reply = await _submit(
        sessions, session_id, status="blocked", blocked_reason="The tests do not build."
    )
    assert reply.accepted, reply
    return session_id


def _retry(world: World, activation: str) -> None:
    result = world.bridge.retry_activation(
        workspace_id=WORKSPACE,
        run_id=RUN_ID,
        actor="user:alice",
        activation_id=store_activation_id(RUN_ID, activation),
    )
    assert (result.outcome, result.code) == ("retried", None), result


def _causes(world: World) -> list[tuple[str, str, str]]:
    state = world.bridge.load(workspace_id=WORKSPACE, run_id=RUN_ID).state
    return [(cause.reason, cause.detail, cause.subject) for cause in state.causes]


def _verdict(world: World, sessions: Sessions, session_id: str) -> str:
    """What the run guard answers a ``sys_os_shell`` call of the session: ALLOW, or the deny."""
    view = RunStatusCache(world.runs, ttl_s=0).status(WORKSPACE, RUN_ID)
    guard = run_guard(
        run_status=view.status,
        pause_reason=view.pause_reason,
        closed=sessions.dispatch.sessions[session_id].closed,
    )
    name = "mcp__omnigent__sys_os_shell"
    event = cast(PolicyEvent, {"type": "tool_call", "target": name, "data": {"name": name}})
    verdict = guard(event)
    return str(verdict.get("reason", verdict["result"]))


def _salvage_refs(worktree: LinkedWorktree) -> dict[str, str]:
    listed = run_git(
        worktree.repo_root, "for-each-ref", "--format=%(refname) %(objectname)", "refs/coral/"
    )
    return dict(line.split(" ", 1) for line in listed.splitlines())


def _step_creates(sessions: Sessions) -> dict[tuple[str | None, int | None], set[str]]:
    creates: dict[tuple[str | None, int | None], set[str]] = {}
    for request in sessions.facade.requests:
        if request.role == "step":
            creates.setdefault((request.engine_slot_id, request.generation), set()).add(
                request.effect_key
            )
    return creates


def _rows(world: World, effect_type: str) -> list[dict[str, Any]]:
    assert world.db_uri is not None
    rows = []
    for row in world.queue.get_work(_work_ids(world), workspace_id=WORKSPACE):
        payload = json.loads(row.payload)
        if payload.get("effect_type") == effect_type:
            rows.append(
                {
                    "status": row.status,
                    "error_code": row.error_code,
                    "result": row.result,
                    **payload,
                }
            )
    return rows


def _work_ids(world: World) -> list[str]:
    """Every work row id of the run, as a new process reads them."""
    assert world.db_uri is not None
    with Session(fresh_process(world.db_uri)) as db:
        return list(db.execute(select(WorkRow.id).where(WorkRow.run_id == RUN_ID)).scalars())


async def _blocked_and_retried(
    world: World, sessions: Sessions, worktree: LinkedWorktree, yaml_text: str
) -> str:
    """The implementer writes, its turn still running, blocks, and a person retries it."""
    _start(world, worktree, yaml_text)
    await sessions.drain()
    old = await _block(sessions, IMPLEMENT)
    live = sessions.dispatch.sessions[old]
    live.status, live.response_id = "running", "resp-1"
    worktree.write("README.md", b"edited\n")
    worktree.write("draft.txt", b"half done\n")
    _retry(world, "implement||")
    return old


def _assert_restarted_once(
    world: World, sessions: Sessions, worktree: LinkedWorktree, old: str
) -> None:
    """Generation 2 ran once, briefed with the one salvage ref, and the run completed."""
    assert world.run(RUN_ID).status == int(RunStatus.COMPLETED)
    creates = _step_creates(sessions)
    assert set(creates) == {(IMPLEMENT, 1), (IMPLEMENT, 2), (REVIEW, 1)}
    assert all(len(keys) == 1 for keys in creates.values())
    # One salvage ref, holding the old attempt's work; the branch ends at its base,
    # with the draft gone from the worktree.
    (salvage_ref, salvaged), *more = _salvage_refs(worktree).items()
    assert more == []
    assert run_git(worktree.root, "show", f"{salvaged}:draft.txt") == "half done\n"
    assert run_git(worktree.root, "show", f"{salvaged}:README.md") == "edited\n"
    assert not (worktree.root / "draft.txt").exists()
    assert (worktree.root / "README.md").read_bytes() == b"hello\n"
    assert run_git(worktree.root, "status", "--porcelain") == ""
    # Generation 2's session is bound at generation 2 and was briefed with the ref.
    new = sessions.session_of(RUN_ID, IMPLEMENT)
    assert new != old
    binding = sessions.bindings.find_by_session(WORKSPACE, new)
    assert binding is not None and binding.session_generation == 2
    # Exactly one brief, delivered once even when its send ran twice.
    briefs = [send for send in sessions.messages(new) if "Coral step brief." in str(send["text"])]
    assert len({send["stable_id"] for send in briefs}) == 1
    transcript = sessions.dispatch.sessions[new].transcript
    assert [item.item_id for item in transcript].count(briefs[0]["stable_id"]) == 1
    assert f"saved at {salvage_ref} (commit {salvaged[:12]})" in str(briefs[0]["text"])
    # The old session is closed and was stopped; the restart ran once to success.
    assert sessions.dispatch.sessions[old].closed
    assert old in {session_id for session_id, _user in sessions.dispatch.stops}
    restarts = _rows(world, RECOVERY_RESTART)
    assert [(row["status"], row["session_id"]) for row in restarts] == [
        (int(WorkStatus.SUCCEEDED), old)
    ]
    assert json.loads(restarts[0]["result"])["head"] == worktree.base


async def test_a_retried_writer_is_fenced_salvaged_reset_and_briefed_at_generation_two(
    world: World, worktree: LinkedWorktree, host: _Host
) -> None:
    async with serving(world, channel=host) as sessions:
        old = await _blocked_and_retried(world, sessions, worktree, fixture_text("two_steps"))
        # From the retry until the restart is claimed, the old session's tools are denied
        # by the paused run, also while the fence waits for its interrupted turn to settle.
        paused = _verdict(world, sessions, old)
        assert paused.startswith("[run.paused] The Coral run is paused (infra)"), paused
        settling: list[str] = []
        sessions.dispatch.settle_on_interrupt = lambda session_id: settling.append(
            _verdict(world, sessions, session_id)
        )
        superseded = await _submit(sessions, old)
        assert (superseded.accepted, superseded.reason) == (False, "slot.superseded")

        await sessions.drain()

        assert sessions.dispatch.interrupts == ["resp-1"]
        assert [verdict[:12] for verdict in settling] == ["[run.paused]"]
        assert _causes(world) == []
        # After the restart, a call the old session still makes meets its closed label.
        assert _verdict(world, sessions, old).startswith("[session.closed]")
        # One salvage, one reset: nothing is salvaged after the reset.
        assert host.ops("head", "salvage", "reset") == ["head", "salvage", "reset"]
        await sessions.run(Agent(sessions))
        _assert_restarted_once(world, sessions, worktree, old)


Install = Callable[[pytest.MonkeyPatch, Sessions, _Host, str], None]


def _restart_row(finished: FinishedWork) -> bool:
    return json.loads(finished.item.payload).get("effect_type") == RECOVERY_RESTART


def _crash_before_clean(patch: pytest.MonkeyPatch) -> None:
    run = Git.run

    def crashing(git: Git, *argv: str | bytes, **kwargs: Any) -> Any:
        if argv and argv[0] == "clean":
            raise SimulatedCrash("the host died before clean")
        return run(git, *argv, **kwargs)

    patch.setattr(Git, "run", crashing)


def _second_generation(request: SessionCreateRequest, **_: object) -> bool:
    return request.generation == 2


def _second_create_row(finished: FinishedWork) -> bool:
    payload = json.loads(finished.item.payload)
    return payload.get("engine_kind") == "create_session" and payload.get("generation") == 2


def _brief_to_another_than(finished: FinishedWork, session_id: str) -> bool:
    payload = json.loads(finished.item.payload)
    return payload.get("kind") == "brief" and payload.get("session_id") != session_id


CRASHES: dict[str, tuple[Install, bool]] = {
    # The fence has interrupted and labelled the old session, and has not stopped it.
    "before-the-stop": (
        lambda patch, sessions, _host, old: crash_around_async(
            patch,
            sessions.dispatch,
            "stop",
            when="before",
            matching=lambda **call: call["session_id"] == old,
        ),
        True,
    ),
    "after-the-stop": (
        lambda patch, sessions, _host, old: crash_around_async(
            patch,
            sessions.dispatch,
            "stop",
            when="after",
            matching=lambda **call: call["session_id"] == old,
        ),
        True,
    ),
    "after-the-salvage": (
        lambda patch, _sessions, host, _old: crash_around_async(
            patch, host, "request", when="after", matching=lambda _host, op, **_: op == "salvage"
        ),
        True,
    ),
    "after-the-reset": (
        lambda patch, _sessions, host, _old: crash_around_async(
            patch, host, "request", when="after", matching=lambda _host, op, **_: op == "reset"
        ),
        True,
    ),
    # The restart row finished; its feed, which creates generation 2, never ran.
    "before-the-restart-feed": (
        lambda patch, sessions, _host, _old: crash_around_async(
            patch, sessions.threads, "feed", when="before", matching=_restart_row
        ),
        False,
    ),
    # The feed committed generation 2's create; the process died before running it.
    "after-the-restart-feed": (
        lambda patch, sessions, _host, _old: crash_around_async(
            patch, sessions.threads, "feed", when="after", matching=_restart_row
        ),
        False,
    ),
    # Generation 2's session was created and bound; its create row is still claimed.
    "after-the-second-create": (
        lambda patch, sessions, _host, _old: crash_around_async(
            patch, sessions.facade, "create_session", when="after", matching=_second_generation
        ),
        True,
    ),
    # Generation 2's brief reached its session; the send row is still claimed.
    "after-the-second-brief": (
        lambda patch, sessions, _host, old: crash_around_async(
            patch,
            sessions.dispatch,
            "send_message",
            when="after",
            matching=lambda **send: send["session_id"] != old,
        ),
        True,
    ),
    # Generation 2's create finished; its feed, which queues the brief, never ran.
    "before-the-second-create-feed": (
        lambda patch, sessions, _host, _old: crash_around_async(
            patch, sessions.threads, "feed", when="before", matching=_second_create_row
        ),
        False,
    ),
    # The host's reset restored the tracked files and died before its ``clean``.
    "inside-the-reset": (
        lambda patch, _sessions, _host, _old: _crash_before_clean(patch),
        True,
    ),
    # Generation 2's brief was sent; its feed, which puts the slot to work, never ran.
    "before-the-second-brief-feed": (
        lambda patch, sessions, _host, old: crash_around_async(
            patch,
            sessions.threads,
            "feed",
            when="before",
            matching=lambda finished: _brief_to_another_than(finished, old),
        ),
        False,
    ),
}


@pytest.mark.parametrize("crash", list(CRASHES))
async def test_a_crash_at_any_restart_phase_still_reaches_generation_two_once(
    world: World,
    worktree: LinkedWorktree,
    host: _Host,
    monkeypatch: pytest.MonkeyPatch,
    crash: str,
) -> None:
    install, claims = CRASHES[crash]
    async with serving(world, channel=host) as sessions:
        old = await _blocked_and_retried(world, sessions, worktree, fixture_text("two_steps"))
        with monkeypatch.context() as patch:
            install(patch, sessions, host, old)
            with pytest.raises(SimulatedCrash):
                await sessions.drain()
    claimed = [
        row
        for row in world.queue.get_work(_work_ids(world), workspace_id=WORKSPACE)
        if row.status == int(WorkStatus.CLAIMED)
    ]
    assert len(claimed) == int(claims)

    async with restarted(sessions, lease_s=LEASE_S) as again:
        agent = Agent(again)
        # The clock stands still: a restart whose feed the crash lost goes on at once,
        # because the new process resyncs the paused run as soon as it starts.
        await again.run(agent)
        _assert_restarted_once(again.world, again, worktree, old)
        # The old session's handoffs were refused as superseded; generation 2's accepted.
        replies = {(call.session_id, call.reply.accepted) for call in agent.calls}
        assert (old, False) in replies and (old, True) not in replies


async def test_the_restarting_pause_lifts_only_after_the_old_session_is_closed_and_stopped(
    world: World, worktree: LinkedWorktree, host: _Host
) -> None:
    async with serving(world, channel=host) as sessions:
        old = await _blocked_and_retried(world, sessions, worktree, fixture_text("two_steps"))
        seen: list[tuple[bool, bool, list[tuple[str, str, str]]]] = []

        async def before_feed(finished: FinishedWork) -> None:
            if _restart_row(finished):
                stopped = old in {session_id for session_id, _ in sessions.dispatch.stops}
                seen.append((sessions.dispatch.sessions[old].closed, stopped, _causes(world)))

        sessions.before_feed = before_feed
        await sessions.drain()

    assert seen == [(True, True, [("infra", "recovery.restarting", IMPLEMENT)])]
    assert _causes(world) == []


async def test_a_failed_restart_stays_paused_for_a_retry_that_fences_the_same_session(
    world: World, worktree: LinkedWorktree, host: _Host
) -> None:
    async with serving(world, channel=host) as sessions:
        old = await _blocked_and_retried(world, sessions, worktree, fixture_text("two_steps"))
        # Someone commits on the run's branch outside Coral: the restart refuses to reset.
        moved = worktree.commit("outside Coral")
        await sessions.drain()

        assert _causes(world) == [("failure_path", "restart:workspace.head_moved", IMPLEMENT)]
        state = world.bridge.load(workspace_id=WORKSPACE, run_id=RUN_ID).state
        assert retryable_activations(state) == ("implement||",)
        assert run_git(worktree.root, "rev-parse", "HEAD").strip() == moved
        assert _salvage_refs(worktree) == {}
        # Resume cannot skip the restart.
        world.bridge.resume_run(workspace_id=WORKSPACE, run_id=RUN_ID, actor="user:alice")
        assert _causes(world) == [("failure_path", "restart:workspace.head_moved", IMPLEMENT)]

        # The branch is put back at its base, keeping the edits; the next retry makes
        # generation 3 and fences the same first session.
        run_git(worktree.root, "reset", "-q", "--soft", worktree.base)
        _retry(world, "implement||")
        await sessions.drain()

        restarts = _rows(world, RECOVERY_RESTART)
        assert sorted((row["generation"], row["session_id"]) for row in restarts) == [
            (2, old),
            (3, old),
        ]
        assert set(_step_creates(sessions)) == {(IMPLEMENT, 1), (IMPLEMENT, 3)}
        assert _causes(world) == []
        (salvaged,) = _salvage_refs(worktree).values()
        assert run_git(worktree.root, "show", f"{salvaged}:draft.txt") == "half done\n"


async def test_a_review_loops_second_pass_restarts_from_the_first_pass_commit(
    world: World, worktree: LinkedWorktree, host: _Host
) -> None:
    async with serving(world, channel=host) as sessions:
        _start(world, worktree, fixture_text("loop"))
        await sessions.drain()
        worktree.write("pass1.txt", b"first pass\n")
        reply = await _submit(sessions, sessions.session_of(RUN_ID, LOOP_PASS_ONE))
        assert reply.accepted, reply
        await sessions.run(Orchestrator(sessions, choices=[("revise", "One more pass.")]))
        first_commit = run_git(worktree.root, "rev-parse", "HEAD").strip()
        assert first_commit != worktree.base
        worktree.write("pass2.txt", b"second pass, half done\n")
        await _block(sessions, LOOP_PASS_TWO)

        _retry(world, LOOP_PASS_TWO.rsplit(":", 1)[0])
        await sessions.drain()

        # The expected head is the first pass's commit, not the base: HEAD matches, and
        # the reset keeps it while the second pass's work goes to the salvage.
        assert _causes(world) == []
        assert run_git(worktree.root, "rev-parse", "HEAD").strip() == first_commit
        (salvaged,) = _salvage_refs(worktree).values()
        assert (
            run_git(worktree.root, "show", f"{salvaged}:pass2.txt") == "second pass, half done\n"
        )
        assert (worktree.root / "pass1.txt").exists()
        assert not (worktree.root / "pass2.txt").exists()


@pytest.mark.parametrize("bound", [False, True], ids=["before-its-lease-check", "after-it-bound"])
async def test_a_create_in_flight_at_the_retry_never_leaves_a_live_unlabelled_session(
    world: World, worktree: LinkedWorktree, host: _Host, bound: bool
) -> None:
    async with serving(world, channel=host) as sessions:
        # The reader's first create waits on its host while the writer is created and briefed.
        offline = CoralSessionError("session.host_offline", "host offline", retryable=True)

        def offline_reader(request: SessionCreateRequest) -> None:
            if request.engine_slot_id == READER:
                raise offline

        sessions.facade.sessions.on_create = offline_reader
        _start(world, worktree, PAIR)
        await sessions.drain()
        reader_one = _session_of_create(world, READER)
        retried: list[str] = []

        def block_and_retry(request: SessionCreateRequest) -> None:
            # The reader's create is past its paused-run check: the writer blocks and a
            # person retries the step while the create runs.
            if request.engine_slot_id == READER and request.generation == 1 and not retried:
                retried.append("work||")
                world.bridge.commit_inputs(
                    workspace_id=WORKSPACE, run_id=RUN_ID, inputs=lambda _snap: blocked(WRITER)
                )
                _retry(world, "work||")

        if bound:
            create = sessions.facade.create_session

            async def create_then_retry(request: SessionCreateRequest, **kwargs: Any) -> Any:
                ref = await create(request, **kwargs)
                block_and_retry(request)
                return ref

            sessions.facade.sessions.on_create = None
            sessions.facade.create_session = create_then_retry  # type: ignore[method-assign]
        else:
            sessions.facade.sessions.on_create = block_and_retry
        sessions.world.clock.advance(31)
        await sessions.drain()

    assert retried == ["work||"]
    (first_create,) = [
        row
        for row in _rows(world, "create_session")
        if row.get("engine_slot_id") == READER and row.get("generation") in (None, 1)
    ]
    if bound:
        # The create finished; its completion only receipted, and the restart fenced it.
        assert first_create["status"] == int(WorkStatus.SUCCEEDED)
        assert sessions.dispatch.sessions[reader_one].closed
        assert reader_one in {session_id for session_id, _ in sessions.dispatch.stops}
    else:
        # Its lease check found the slot superseded: no session was created at all.
        assert (first_create["status"], first_create["error_code"]) == (
            int(WorkStatus.ABANDONED),
            "slot.generation_mismatch",
        )
        assert (WORKSPACE, reader_one) not in sessions.facade.sessions.created
        assert reader_one not in sessions.dispatch.sessions
    # Both slots went on at generation 2, each with a session of its own.
    assert {(slot, gen) for slot, gen in _step_creates(sessions) if gen == 2} == {
        (WRITER, 2),
        (READER, 2),
    }
    assert _causes(world) == []


def _session_of_create(world: World, slot_id: str) -> str:
    """The session the slot's first create derives, whether or not it ran."""
    (row,) = [
        row for row in _rows(world, "create_session") if row.get("engine_slot_id") == slot_id
    ]
    return effect_session_id(WORKSPACE, row["effect_key"])


def _head(worktree: LinkedWorktree) -> str:
    return run_git(worktree.root, "rev-parse", "HEAD").strip()


def _restart_result(world: World, generation: int, slot: str = IMPLEMENT) -> dict[str, Any]:
    (row,) = [
        row
        for row in _rows(world, RECOVERY_RESTART)
        if (row["generation"], row["engine_slot_id"]) == (generation, slot)
    ]
    assert row["status"] == int(WorkStatus.SUCCEEDED), row
    return json.loads(row["result"])


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(
            WorkspaceOpError("workspace.git_failed", "diff failed", permanent=True),
            id="diff-stat-fails-for-good",
        ),
        pytest.param(
            WorkspaceOpError("workspace.backend_unavailable", "host offline"),
            id="host-drops-after-the-commit",
        ),
    ],
)
async def test_a_retry_after_a_close_that_committed_and_then_failed_keeps_that_commit(
    world: World, worktree: LinkedWorktree, host: _Host, failure: WorkspaceOpError
) -> None:
    async with serving(world, channel=host) as sessions:
        _start(world, worktree, fixture_text("two_steps"))
        await sessions.drain()
        implementer = sessions.session_of(RUN_ID, IMPLEMENT)
        worktree.write("work.txt", b"the step's work\n")
        # The close's commit lands; what follows it fails until the close gives up.
        host.fail["diff_stat"] = failure
        reply = await _submit(sessions, implementer)
        assert reply.accepted, reply
        for _ in range(30):
            await sessions.drain()
            if _causes(world):
                break
            world.clock.advance(301)
        host.fail.clear()
        committed = _head(worktree)
        assert committed != worktree.base
        assert [subject for _reason, _detail, subject in _causes(world)] == [IMPLEMENT]

        _retry(world, "implement||")
        await sessions.drain()

        # The close's commit is the step's own: the restart keeps it and goes on.
        assert _causes(world) == []
        assert _head(worktree) == committed
        result = _restart_result(world, 2)
        assert (result["head"], result["head_verified"]) == (committed, True)
        assert run_git(worktree.root, "show", f"{committed}:work.txt") == "the step's work\n"
        # The engine now records that commit: the next retry expects it as its head.
        await _block(sessions, IMPLEMENT)
        _retry(world, "implement||")
        state = world.bridge.load(workspace_id=WORKSPACE, run_id=RUN_ID).state
        (newest, *_older) = [
            effect for effect in reversed(state.effects) if effect.kind == "retry_step"
        ]
        assert newest.payload["expected_head"] == committed
        await sessions.run(Agent(sessions))
        assert world.run(RUN_ID).status == int(RunStatus.COMPLETED)
        assert run_git(worktree.root, "merge-base", "--is-ancestor", committed, "HEAD") == ""


async def test_a_retry_after_an_accepted_close_and_a_failure_restarts_from_that_close(
    world: World, worktree: LinkedWorktree, host: _Host
) -> None:
    async with serving(world, channel=host) as sessions:
        _start(world, worktree, PAIR)
        await sessions.drain()
        worktree.write("work.txt", b"the writer's work\n")
        reply = await _submit(sessions, sessions.session_of(RUN_ID, WRITER))
        assert reply.accepted, reply
        await sessions.drain()
        accepted = _head(worktree)
        assert accepted != worktree.base
        # The reader then cannot go on: the step is retried as a whole.
        await _block(sessions, READER)
        _retry(world, "work||")
        await sessions.drain()

        assert _causes(world) == []
        assert _head(worktree) == accepted
        assert _restart_result(world, 2, WRITER)["head"] == accepted
        assert {(slot, gen) for slot, gen in _step_creates(sessions) if gen == 2} == {
            (WRITER, 2),
            (READER, 2),
        }


FENCE_CRASHES = [
    pytest.param(None, None, id="no-crash"),
    *(
        pytest.param(name, when, id=f"{when}-{name.replace('_', '-')}")
        for name in ("interrupt", "set_closed", "stop")
        for when in ("before", "after")
    ),
]


@pytest.mark.parametrize(("call", "when"), FENCE_CRASHES)
async def test_a_restarts_fence_over_the_real_dispatch_survives_a_crash_at_each_call(
    tunnel_three_layer_stack: _TunnelStack,  # noqa: F811 -- pytest injects the imported fixture
    monkeypatch: pytest.MonkeyPatch,
    call: str | None,
    when: Literal["before", "after"] | None,
) -> None:
    stack = tunnel_three_layer_stack
    harness = await _bound_session(stack, ["honors_interrupt"])
    session_id = harness.session_id
    store = get_conversation_store()
    edges = CoralStatusEdges(asyncio.get_running_loop())
    dispatch = OmnigentSessionDispatch(
        stack.ap_app, store, stack.ap_app.state.runner_router, pre_send_hooks=()
    )
    run_store = FakeRunStore(default_workspace_id=AC2_WORKSPACE)
    run = start_run(
        run_store,
        workspace_id=AC2_WORKSPACE,
        user_id=None,
        account_generation=None,
        host_id=HOST,
        repo_path="/work",
        worktree_path="/work-worktrees/coral-r-base",
    )
    binding = executor_step_binding(
        workspace_id=AC2_WORKSPACE,
        run_id=run.id,
        session_id=session_id,
        slot_role=SlotRole.VERIFIER,
        host_id=HOST,
    )
    scope = RecordingScopeRunner()
    executor = restart_executor(
        dispatch=dispatch,
        edges=edges,
        channels=FakeChannels(FakeHostChannel([], {}), scope),
        bindings=FakeBindings([binding]),
        intents=FakeIntents([]),
        run_store=run_store,
        scope_runner=scope,
        bounds=CloseBounds(turn_end_s=budget(30), interrupt_settle_s=budget(30)),
    )
    payload = {
        "effect_type": RECOVERY_RESTART,
        "effect_key": f"{run.id}:7:retry_step:{SLOT_OF_THE_FENCE}",
        "engine_kind": "retry_step",
        "engine_slot_id": SLOT_OF_THE_FENCE,
        "generation": 2,
        "session_id": session_id,
        "writer": False,
        "expected_head": None,
    }

    async def deliver() -> EffectOutcome:
        ctx = effect_context(workspace_id=AC2_WORKSPACE, run_id=run.id, payload=payload)
        return await executor(ctx)

    unregister = session_live_state.register_status_edge_observer(
        "coral-recovery-fence-test", edges.observe
    )
    try:
        receipt = await dispatch.send_message(
            workspace_id=AC2_WORKSPACE,
            run_id=run.id,
            session_id=session_id,
            user_id=None,
            stable_id=uuid.uuid4().hex,
            text="Review the parser.",
        )
        assert receipt.delivery == "sent"
        await poll_until_async(_session_running(session_id, "resp_turn_1"), timeout_s=budget(30))
        if call is not None and when is not None:
            with monkeypatch.context() as patch:
                crash_around_async(patch, dispatch, call, when=when)
                with pytest.raises(SimulatedCrash):
                    await deliver()
        outcome = await deliver()
        repeat = await deliver()
    finally:
        unregister()

    reader = {"salvage_ref": None, "salvage_commit": None, "head_verified": False, "head": None}
    assert isinstance(outcome, EffectCompleted) and outcome.result == reader
    assert isinstance(repeat, EffectCompleted) and repeat.result == reader
    # The old session is closed, its turn ended cancelled, and its runner holds no turn.
    closed = store.get_conversation(session_id)
    assert closed is not None
    assert (closed.labels or {}).get(CLOSED_LABEL_KEY) == CLOSED_LABEL_VALUE
    await poll_until_async(
        lambda: session_id not in stack.runner_app.state.active_turns, timeout_s=budget(30)
    )
    assert harness.response_ids == ["resp_turn_1"]


# ── liveness: a lost runner seen from a real tunnel drop ─────────────────────

# The tunnel server's one workspace, which its tunnels stamp and clear in.
LIVE_WORKSPACE = DEFAULT_WORKSPACE_ID
RUNNER = "runner-coral-liveness"
LIVE_HOST = "4" * 32
LIVE_WORKTREE = "/repo/coral-worktrees/r1"
# The production defaults: Omnigent's 90 s stamp TTL as the grace, the 120 s leader lease.
GRACE_S = 90
# A server SIGKILL at the default lease: the new leader's first pass comes this long after.
OUTAGE_S = 150


@pytest.fixture
def omnigent_decides_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server's disconnect handling decides without waiting out its 90 s reconnect grace."""
    monkeypatch.setattr(omnigent_sessions, "RUNNER_DISCONNECT_GRACE_S", 0.0)


def _live_dispatch(server: TunnelServer, world: World) -> OmnigentSessionDispatch:
    """The server's dispatch, judging stamps on the world's clock."""
    return OmnigentSessionDispatch(
        server.app,
        server.store,
        server.app.state.runner_router,
        pre_send_hooks=(),
        clock=lambda: world.clock.now.timestamp(),
    )


async def _working_on_the_server(
    world: World, sessions: Sessions, server: TunnelServer
) -> tuple[str, str]:
    """
    A two-step run whose implementer works on its brief, its session bound to ``RUNNER``.

    The session's server row is mid-turn on ``LIVE_HOST``, as the server holds a step's
    running turn.
    """
    spec = run_spec(workspace_id=LIVE_WORKSPACE, host_id=LIVE_HOST, worktree_path=LIVE_WORKTREE)
    run = start(world, spec=spec)
    await sessions.drain()
    state = world.bridge.load(workspace_id=LIVE_WORKSPACE, run_id=run.id).state
    session_id = slot_session_id(LIVE_WORKSPACE, state, IMPLEMENT)
    assert session_id is not None and len(sessions.messages(session_id)) == 1
    await _bind_on_the_server(sessions, server, session_id, RUNNER)
    return run.id, session_id


async def _bind_on_the_server(
    sessions: Sessions, server: TunnelServer, session_id: str, runner_id: str
) -> None:
    """The session's server row, bound to ``runner_id`` and mid-turn on ``LIVE_HOST``."""
    sessions.dispatch.sessions[session_id].status = "running"
    await asyncio.to_thread(
        server.store.create_conversation,
        conversation_id=session_id,
        runner_id=runner_id,
        host_id=LIVE_HOST,
        workspace=LIVE_WORKTREE,
    )
    await asyncio.to_thread(server.store.set_session_live_status, session_id, "running")


def _stamp(server: TunnelServer, session_id: str) -> int | None:
    found = server.store.get_runner_liveness(session_id)
    assert found is not None and found[0] == RUNNER
    return found[1]


def _live_run(world: World, run_id: str) -> CoralRun:
    run = world.runs.get_run(run_id, workspace_id=LIVE_WORKSPACE)
    assert run is not None
    return run


def _live_losses(world: World, run_id: str) -> list[RunnerLost]:
    rows = world.runs.read_engine_log(
        run_id,
        workspace_id=LIVE_WORKSPACE,
        max_run_version=_live_run(world, run_id).version,
        limit=10_000,
    )
    return [entry.input for entry in decode_entries(rows) if isinstance(entry.input, RunnerLost)]


def _live_wakes(world: World, run_id: str) -> list[dict[str, Any]]:
    state = world.bridge.load(workspace_id=LIVE_WORKSPACE, run_id=run_id).state
    return [dict(effect.payload) for effect in state.effects if effect.kind == "runner_lost"]


async def _tick(world: World, sessions: Sessions, run_id: str) -> None:
    """The supervisor's resync tick for the run, then everything due."""
    world.bridge.schedule_resync(_live_run(world, run_id))
    await sessions.drain()


def _resync_due(world: World, run_id: str) -> int | None:
    """When the run's resync row runs next; ``None`` once it ran with nothing to come."""
    (row,) = world.queue.get_work([resync_draft(run_id).id], workspace_id=LIVE_WORKSPACE)
    return row.available_at if row.status == int(WorkStatus.PENDING) else None


@pytest.mark.usefixtures("omnigent_decides_at_once")
async def test_a_runner_whose_tunnel_dropped_while_its_host_is_offline_is_lost_once_at_its_grace(
    world: World,
    tunnel_server: TunnelServer,  # noqa: F811 -- pytest injects the imported fixture
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = tunnel_server
    world.clock.now = datetime.now(UTC).replace(microsecond=0)
    server.hosts.upsert_on_connect(LIVE_HOST, "laptop", "local")
    server.hosts.set_offline(LIVE_HOST)
    edges: list[SessionStatusEdge] = []
    unregister = session_live_state.register_status_edge_observer(
        "coral-liveness-test", edges.append
    )
    ref = LivenessRef()
    try:
        async with serving(world, liveness=ref) as sessions:
            run_id, session_id = await _working_on_the_server(world, sessions, server)
            ref.current = LivenessPass(
                sessions.threads, _live_dispatch(server, world), grace_s=GRACE_S
            )
            async with runner_tunnel(server, RUNNER) as tunnel:
                await poll_until_async(lambda: _stamp(server, session_id), timeout_s=budget(10))
                # While the tunnel is open the pass starts no clock.
                await _tick(world, sessions, run_id)
                assert _resync_due(world, run_id) is None
                with caplog.at_level(logging.INFO, logger="omnigent.server.app"):
                    await tunnel.close()
                    # The server's hold has no other observable state; an upstream reword
                    # of this line fails the wait loudly, it never passes it.
                    await poll_until_async(
                        lambda: "host offline, holding session" in caplog.text,
                        timeout_s=budget(10),
                    )
            # The server cleared the stamp and holds the turn without an edge.
            assert _stamp(server, session_id) is None
            world.clock.advance(30)
            first_sighting = world.clock.now
            await _tick(world, sessions, run_id)
            grace_end = int(first_sighting.timestamp()) + GRACE_S
            assert _resync_due(world, run_id) == grace_end

            world.clock.advance(GRACE_S - 1)
            await sessions.drain()
            assert _live_losses(world, run_id) == []
            world.clock.advance(1)
            # No tick: the rescheduled resync itself reports the loss.
            await sessions.drain()
            [lost] = _live_losses(world, run_id)
            world.clock.advance(120)
            await _tick(world, sessions, run_id)
    finally:
        unregister()

    assert (lost.runner_id, lost.observed_at) == (RUNNER, first_sighting)
    assert _live_losses(world, run_id) == [lost]
    [wake] = _live_wakes(world, run_id)
    assert (wake["session_id"], wake["runner_id"]) == (session_id, RUNNER)
    assert [edge.status for edge in edges if edge.session_id == session_id] == []


@pytest.mark.usefixtures("omnigent_decides_at_once")
async def test_a_runner_whose_tunnel_dropped_on_an_online_host_is_lost_by_its_edge_once(
    world: World,
    tunnel_server: TunnelServer,  # noqa: F811 -- pytest injects the imported fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = tunnel_server
    world.clock.now = datetime.now(UTC).replace(microsecond=0)
    server.hosts.upsert_on_connect(LIVE_HOST, "laptop", "local")
    ref = LivenessRef()
    async with serving(world, liveness=ref) as sessions:
        run_id, session_id = await _working_on_the_server(world, sessions, server)
        liveness = LivenessPass(sessions.threads, _live_dispatch(server, world), grace_s=GRACE_S)

        async def server_row(*, workspace_id: int, session_id: str) -> SessionState:
            with workspace_scope(workspace_id):
                conv = await asyncio.to_thread(server.store.get_conversation, session_id)
            return session_state_of(session_id, conv)

        # The turn-fact executor reads the session as the real facade does: from its row.
        monkeypatch.setattr(sessions.facade, "session_state", server_row)
        edges: list[SessionStatusEdge] = []
        unregisters = [
            session_live_state.register_status_edge_observer("coral-liveness-test", edges.append),
            session_live_state.register_status_edge_observer(
                "coral-liveness-turn-facts", sessions.recorder.observe
            ),
        ]
        try:
            async with runner_tunnel(server, RUNNER) as tunnel:
                await poll_until_async(lambda: _stamp(server, session_id), timeout_s=budget(10))
                await tunnel.close()
                await poll_until_async(
                    lambda: any(edge.session_id == session_id for edge in edges),
                    timeout_s=budget(10),
                )
            sessions.recorder.wait_idle()
            await sessions.drain()
        finally:
            for unregister in unregisters:
                unregister()
        # The liveness pass watches the same runner missing and reports the same loss.
        first_sighting = world.clock.epoch
        watching = await liveness.check_run(workspace_id=LIVE_WORKSPACE, run_id=run_id)
        assert watching == first_sighting + GRACE_S
        world.clock.advance(GRACE_S)
        due = await liveness.check_run(workspace_id=LIVE_WORKSPACE, run_id=run_id)

    [edge] = [edge for edge in edges if edge.session_id == session_id]
    assert (edge.status, edge.error_code) == ("failed", "runner_disconnected")
    # The row keeps its runner after the drop, so the edge's fact names it.
    assert server.store.get_runner_liveness(session_id) == (RUNNER, None)
    failed = [
        entry.input
        for entry in decode_entries(
            world.runs.read_engine_log(
                run_id,
                workspace_id=LIVE_WORKSPACE,
                max_run_version=_live_run(world, run_id).version,
                limit=10_000,
            )
        )
        if isinstance(entry.input, SessionFailed)
    ]
    assert [(item.failure_class, item.runner_id) for item in failed] == [
        ("infra.runner_lost", RUNNER)
    ]
    [wake] = _live_wakes(world, run_id)
    assert (wake["session_id"], wake["runner_id"]) == (session_id, RUNNER)
    assert _live_losses(world, run_id) == [] and due is None


@pytest.mark.parametrize("comes_back", [True, False], ids=["reconnects", "never_returns"])
async def test_a_restart_at_the_production_defaults_gives_a_reconnecting_runner_its_full_grace(
    world: World,
    tunnel_server: TunnelServer,  # noqa: F811 -- pytest injects the imported fixture
    comes_back: bool,
) -> None:
    server = tunnel_server
    world.clock.now = datetime.now(UTC).replace(microsecond=0)
    server.hosts.upsert_on_connect(LIVE_HOST, "laptop", "local")
    async with serving(world) as sessions:
        run_id, session_id = await _working_on_the_server(world, sessions, server)
        async with runner_tunnel(server, RUNNER) as tunnel:
            await poll_until_async(lambda: _stamp(server, session_id), timeout_s=budget(10))
            # The server dies: the runner's tunnel drops, and a dead server clears nothing.
            shutdown_state.mark_runner_handed_off(RUNNER, reason="coral-test-server-sigkill")
            await tunnel.close()
    stamp = _stamp(server, session_id)
    assert stamp is not None

    ref = LivenessRef()
    async with restarted(sessions, lease_s=OUTAGE_S - 1, liveness=ref) as again:
        later = again.world
        dispatch = _live_dispatch(server, later)
        ref.current = LivenessPass(again.threads, dispatch, grace_s=GRACE_S)
        # The stamp is past the server's 90 s TTL, which a stamp rule would read as lost.
        assert later.clock.epoch - stamp >= OUTAGE_S - 2
        seen = await dispatch.runner_liveness(workspace_id=LIVE_WORKSPACE, session_id=session_id)
        assert (seen.runner_id, seen.connected, seen.fresh) == (RUNNER, False, False)
        # The startup sweep made the resync due: the new leader's first pass.
        await again.drain()
        first_pass = later.clock.now
        assert _resync_due(later, run_id) == int(first_pass.timestamp()) + GRACE_S
        if comes_back:
            later.clock.advance(8)
            async with runner_tunnel(server, RUNNER):
                await poll_until_async(lambda: server.connected(RUNNER), timeout_s=budget(10))
                for _ in range(3):
                    later.clock.advance(60)
                    await _tick(later, again, run_id)
        else:
            later.clock.advance(GRACE_S - 1)
            await again.drain()
            assert _live_losses(later, run_id) == []
            later.clock.advance(1)
            await again.drain()

    if comes_back:
        assert _live_losses(later, run_id) == []
        assert _live_wakes(later, run_id) == []
        assert _resync_due(later, run_id) is None
    else:
        [lost] = _live_losses(later, run_id)
        assert (lost.runner_id, lost.observed_at) == (RUNNER, first_pass)
        assert len(_live_wakes(later, run_id)) == 1
    assert server.store.get_runner_liveness(session_id)[0] == RUNNER  # type: ignore[index]


def _offline_host(server: TunnelServer, world: World) -> None:
    """The world's clock on wall time; the session's host row known and offline."""
    world.clock.now = datetime.now(UTC).replace(microsecond=0)
    server.hosts.upsert_on_connect(LIVE_HOST, "laptop", "local")
    server.hosts.set_offline(LIVE_HOST)


@pytest.mark.usefixtures("omnigent_decides_at_once")
@pytest.mark.parametrize(
    "back_after_s", [GRACE_S - 1, GRACE_S + 1], ids=["back-inside-the-grace", "back-past-it"]
)
async def test_a_flapping_runner_is_lost_only_when_one_outage_outlasts_its_grace(
    world: World,
    tunnel_server: TunnelServer,  # noqa: F811 -- pytest injects the imported fixture
    back_after_s: int,
) -> None:
    server = tunnel_server
    _offline_host(server, world)
    ref = LivenessRef()
    async with serving(world, liveness=ref) as sessions:
        run_id, session_id = await _working_on_the_server(world, sessions, server)
        ref.current = LivenessPass(
            sessions.threads, _live_dispatch(server, world), grace_s=GRACE_S
        )
        # Three drops 50 s apart, each back 30 s later: every pass that sees the runner
        # back ends its clock, so the first drop's grace ends with no loss.
        for _ in range(3):
            async with runner_tunnel(server, RUNNER):
                await poll_until_async(lambda: _stamp(server, session_id), timeout_s=budget(10))
                await _tick(world, sessions, run_id)
                assert _resync_due(world, run_id) is None
                world.clock.advance(20)
            last_sighting = world.clock.now
            await _tick(world, sessions, run_id)
            assert _resync_due(world, run_id) == int(last_sighting.timestamp()) + GRACE_S
            world.clock.advance(30)
        assert _live_losses(world, run_id) == []

        # The last outage: the runner is back just inside its grace, or just past it.
        grace_end = last_sighting + timedelta(seconds=GRACE_S)
        if back_after_s > GRACE_S:
            # The rescheduled resync at the grace's end runs before the runner is back.
            world.clock.now = grace_end
            await sessions.drain()
        world.clock.now = last_sighting + timedelta(seconds=back_after_s)
        async with runner_tunnel(server, RUNNER):
            await poll_until_async(lambda: server.connected(RUNNER), timeout_s=budget(10))
            if back_after_s < GRACE_S:
                world.clock.now = grace_end
                await sessions.drain()
            for _ in range(2):
                world.clock.advance(60)
                await _tick(world, sessions, run_id)
            losses = _live_losses(world, run_id)

    if back_after_s < GRACE_S:
        assert losses == [] and _live_wakes(world, run_id) == []
    else:
        [lost] = losses
        assert (lost.runner_id, lost.observed_at) == (RUNNER, last_sighting)
        assert len(_live_wakes(world, run_id)) == 1


@pytest.mark.usefixtures("omnigent_decides_at_once")
async def test_a_restart_mid_grace_gives_the_missing_runner_a_full_grace_from_the_first_pass(
    world: World,
    tunnel_server: TunnelServer,  # noqa: F811 -- pytest injects the imported fixture
) -> None:
    server = tunnel_server
    _offline_host(server, world)
    ref = LivenessRef()
    async with serving(world, liveness=ref) as sessions:
        run_id, session_id = await _working_on_the_server(world, sessions, server)
        ref.current = LivenessPass(
            sessions.threads, _live_dispatch(server, world), grace_s=GRACE_S
        )
        async with runner_tunnel(server, RUNNER):
            await poll_until_async(lambda: _stamp(server, session_id), timeout_s=budget(10))
        await _tick(world, sessions, run_id)
        world.clock.advance(60)
        await _tick(world, sessions, run_id)
    # The server dies 60 s into the grace; the new leader leads after the default lease,
    # well past the old clock's grace end.
    again_ref = LivenessRef()
    async with restarted(sessions, lease_s=120, liveness=again_ref) as again:
        later = again.world
        again_ref.current = LivenessPass(
            again.threads, _live_dispatch(server, later), grace_s=GRACE_S
        )
        await again.drain()
        first_pass = later.clock.now
        assert _live_losses(later, run_id) == []
        assert _resync_due(later, run_id) == int(first_pass.timestamp()) + GRACE_S
        later.clock.advance(GRACE_S - 1)
        await again.drain()
        assert _live_losses(later, run_id) == []
        later.clock.advance(1)
        await again.drain()

    [lost] = _live_losses(later, run_id)
    assert (lost.runner_id, lost.observed_at) == (RUNNER, first_pass)


# A step of three slots on one host, each with its own session and runner.
TRIO = workflow_text(
    [start_node(), step("work", roster=["implementer", "reviewer", "reviewer"]), end()],
    [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
)
TRIO_SLOTS = ("work||:0", "work||:1", "work||:2")


@pytest.mark.usefixtures("omnigent_decides_at_once")
async def test_a_host_that_goes_offline_with_three_runners_loses_each_once_and_pauses_nothing(
    world: World,
    tunnel_server: TunnelServer,  # noqa: F811 -- pytest injects the imported fixture
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = tunnel_server
    _offline_host(server, world)
    ref = LivenessRef()
    async with serving(world, liveness=ref) as sessions:
        spec = run_spec(
            workspace_id=LIVE_WORKSPACE, host_id=LIVE_HOST, worktree_path=LIVE_WORKTREE
        )
        run_id = start(world, TRIO, spec=spec).id
        await sessions.drain()
        state = world.bridge.load(workspace_id=LIVE_WORKSPACE, run_id=run_id).state
        runners = {slot_id: f"{RUNNER}-{index}" for index, slot_id in enumerate(TRIO_SLOTS)}
        for slot_id, runner_id in runners.items():
            session_id = slot_session_id(LIVE_WORKSPACE, state, slot_id)
            assert session_id is not None
            await _bind_on_the_server(sessions, server, session_id, runner_id)
        ref.current = LivenessPass(
            sessions.threads, _live_dispatch(server, world), grace_s=GRACE_S
        )
        async with contextlib.AsyncExitStack() as stack:
            tunnels = [
                await stack.enter_async_context(runner_tunnel(server, runner_id))
                for runner_id in runners.values()
            ]
            await poll_until_async(
                lambda: all(server.connected(runner_id) for runner_id in runners.values()),
                timeout_s=budget(10),
            )
            await _tick(world, sessions, run_id)
            # The host goes away: every one of its runners' tunnels drops.
            for tunnel in tunnels:
                await tunnel.close()
        with caplog.at_level(logging.INFO, logger="coral.recovery.relaunch"):
            await _tick(world, sessions, run_id)
            world.clock.advance(GRACE_S)
            await sessions.drain()
            world.clock.advance(60)
            await _tick(world, sessions, run_id)

    losses = _live_losses(world, run_id)
    assert sorted((lost.slot_id, lost.runner_id) for lost in losses) == sorted(runners.items())
    state = world.bridge.load(workspace_id=LIVE_WORKSPACE, run_id=run_id).state
    assert (state.status, state.causes) == ("running", ())
    assert [slot.wakes for slot in state.slots if slot.id in runners] == [1, 1, 1]
    lines = [r.getMessage() for r in caplog.records if r.name == "coral.recovery.relaunch"]
    tail = "loss(es) already recorded, 0 report(s) to make again"
    assert lines == [
        f"Coral liveness of run {run_id}: 3 runner clock(s) started, 0 runner(s) lost, 0 {tail}",
        f"Coral liveness of run {run_id}: 0 runner clock(s) started, 3 runner(s) lost, 0 {tail}",
    ]
