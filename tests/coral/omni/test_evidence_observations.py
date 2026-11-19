"""Done-when evidence on the server: capture through the S105 observer, then the submit check."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any, TypeVar

import pytest

from coral.bridge.bound_sessions import BoundSession, BoundSessions
from coral.evidence.fakes import InMemoryObservationLog
from coral.evidence.ir import EvidenceRequirement, InProgress, Missing, Pass, RequiredCommand
from coral.omni.server.observations import (
    IN_PROGRESS_LIMIT_S,
    OBSERVER_NAME,
    EvidenceCapture,
    EvidenceChecker,
    InFlightCalls,
    StepEvidence,
    StepEvidenceLookup,
)
from omnigent.db.db_models import workspace_scope
from omnigent.server.tool_result_observers import (
    ObservedToolCall,
    complete_tool_call,
    register_tool_call_observer,
    tool_call_scope,
)
from tests._helpers.polling import poll_until_async
from tests.coral.tools.fake_decision_port import RUN_ID, WORKSPACE, step_binding

_T = TypeVar("_T")
SLOT = "work||:0"
SESSION = "sess-1"
REQUIREMENT = EvidenceRequirement(items=(RequiredCommand(item_id="c1", run="pytest -q"),))


async def _inline(fn: Callable[..., _T], /, *args: object) -> _T:
    return fn(*args)


class _Steps(StepEvidenceLookup):
    """Every slot of the run serves a step that requires ``pytest -q``."""

    def __init__(self, requirement: EvidenceRequirement | None = REQUIREMENT) -> None:
        super().__init__(lambda _workspace_id, _run_id: pytest.fail("no load expected"))
        self.requirement = requirement

    def find(self, workspace_id: int, run_id: str, slot_id: str) -> StepEvidence | None:
        del workspace_id, run_id, slot_id
        if self.requirement is None:
            return None
        return StepEvidence(requirement=self.requirement, run=Any, target=Any)  # type: ignore[arg-type]


class _Tree:
    """A worktree whose L1 digest changes on every write."""

    def __init__(self) -> None:
        self.version = 0
        self.readable = True

    async def read_l1(self, step: StepEvidence, session_id: str, timeout_s: float) -> str | None:
        del step, session_id, timeout_s
        return f"{self.version:064d}" if self.readable else None


class _Harness:
    def __init__(self, *, requirement: EvidenceRequirement | None = REQUIREMENT) -> None:
        self.bound = BoundSessions()
        self.bound.push(WORKSPACE, SESSION, BoundSession.of(RUN_ID, SLOT, 1))
        self.log = InMemoryObservationLog()
        self.in_flight = InFlightCalls()
        self.tree = _Tree()
        steps = _Steps(requirement)
        self.capture = EvidenceCapture(
            bound=self.bound,
            steps=steps,
            observations=self.log,
            in_flight=self.in_flight,
            read_l1=self.tree.read_l1,
            run_in_thread=_inline,
        )
        self.checker = EvidenceChecker(
            steps=steps,
            observations=self.log,
            in_flight=self.in_flight,
            read_l1=self.tree.read_l1,
            run_in_thread=_inline,
            cover_wait_s=0.2,
        )
        self._op = 0

    async def call(
        self, tool: str, arguments: dict[str, object], output: str, *, session: str = SESSION
    ) -> None:
        """One MCP-proxied call: the scope, the tool's own effect, then the observers."""
        self._op += 1
        operation = f"mcpop_{self._op}"
        with workspace_scope(WORKSPACE), tool_call_scope(session, tool, operation):
            if tool.endswith(("sys_os_write", "sys_os_edit")):
                self.tree.version += 1
            await complete_tool_call(
                session, tool, arguments, output, is_error=False, operation_id=operation
            )

    async def shell(self, command: str, exit_code: int | None = 0) -> None:
        envelope = {"stdout": "", "stderr": "", "exit_code": exit_code, "timed_out": False}
        await self.call("mcp__omnigent__sys_os_shell", {"command": command}, json.dumps(envelope))

    async def edit(self, path: str) -> None:
        await self.call("mcp__omnigent__sys_os_edit", {"path": path, "old": "a", "new": "b"}, "ok")

    async def verdict(self) -> object:
        return await self.checker.verdict(step_binding(SLOT, session_id=SESSION))


@pytest.fixture
def harness() -> Iterator[_Harness]:
    harness = _Harness()
    unregister = register_tool_call_observer(OBSERVER_NAME, harness.capture)
    yield harness
    unregister()


async def test_a_test_run_before_an_edit_is_refused_until_it_runs_again(
    harness: _Harness,
) -> None:
    await harness.shell("pytest -q")
    await harness.edit("api/users.py")

    stale = await harness.verdict()
    assert isinstance(stale, Missing)
    assert [(item.reason, item.changed_path) for item in stale.items] == [
        ("predates_change", "api/users.py")
    ]

    await harness.shell("pytest -q")
    assert await harness.verdict() == Pass()


async def test_a_failed_run_is_missing_and_a_never_run_step_is_missing(
    harness: _Harness,
) -> None:
    never = await harness.verdict()
    assert isinstance(never, Missing) and never.items[0].reason == "never_ran"

    await harness.shell("pytest -q", exit_code=1)
    failed = await harness.verdict()
    assert isinstance(failed, Missing) and failed.items[0].reason == "failed"


async def test_only_bound_step_sessions_are_recorded(harness: _Harness) -> None:
    await harness.call(
        "mcp__omnigent__sys_os_shell", {"command": "pytest -q"}, "{}", session="other"
    )
    harness.bound.push(WORKSPACE, "orch", BoundSession.of(RUN_ID, "orchestrator", 1))
    await harness.call(
        "mcp__omnigent__sys_os_shell", {"command": "pytest -q"}, "{}", session="orch"
    )
    await harness.call("mcp__omnigent__sys_os_read", {"path": "a"}, "text")

    assert harness.log.list_for_session(WORKSPACE, "other") == []
    assert harness.log.list_for_session(WORKSPACE, "orch") == []
    assert harness.log.list_for_session(WORKSPACE, SESSION) == []


async def test_a_step_without_done_when_records_nothing_and_has_no_verdict() -> None:
    harness = _Harness(requirement=None)
    unregister = register_tool_call_observer(OBSERVER_NAME, harness.capture)
    try:
        await harness.shell("pytest -q")
        assert harness.log.list_for_session(WORKSPACE, SESSION) == []
        assert await harness.verdict() is None
    finally:
        unregister()


async def test_an_unreadable_tree_is_never_a_pass(harness: _Harness) -> None:
    await harness.shell("pytest -q")
    harness.tree.readable = False

    assert isinstance(await harness.verdict(), InProgress)


async def test_a_failed_record_answers_in_progress_for_a_while(harness: _Harness) -> None:
    harness.log.fail_next = RuntimeError("database is locked")
    await harness.shell("pytest -q")

    assert isinstance(await harness.verdict(), InProgress)


async def test_a_call_still_running_holds_the_submit_then_it_is_judged(
    harness: _Harness,
) -> None:
    release = asyncio.Event()

    async def slow_shell() -> None:
        with workspace_scope(WORKSPACE), tool_call_scope(SESSION, "sys_os_shell", "mcpop_slow"):
            await release.wait()
            envelope = json.dumps({"exit_code": 0, "timed_out": False})
            await complete_tool_call(
                SESSION,
                "sys_os_shell",
                {"command": "pytest -q"},
                envelope,
                is_error=False,
                operation_id="mcpop_slow",
            )

    task = asyncio.create_task(slow_shell())
    await poll_until_async(lambda: harness.in_flight.open_before(WORKSPACE, SESSION, 1e18) == 1)
    assert isinstance(await harness.verdict(), InProgress)

    waiting = asyncio.Event()

    async def noting_sleep(seconds: float) -> None:
        waiting.set()
        await asyncio.sleep(seconds)

    checker = EvidenceChecker(
        steps=_Steps(),
        observations=harness.log,
        in_flight=harness.in_flight,
        read_l1=harness.tree.read_l1,
        run_in_thread=_inline,
        cover_wait_s=5.0,
        sleep=noting_sleep,
    )
    pending = asyncio.create_task(checker.verdict(step_binding(SLOT, session_id=SESSION)))
    await waiting.wait()
    release.set()
    await task
    assert await pending == Pass()


async def test_a_retried_call_is_recorded_once(harness: _Harness) -> None:
    envelope = json.dumps({"exit_code": 0, "timed_out": False})
    for _ in range(2):
        with workspace_scope(WORKSPACE), tool_call_scope(SESSION, "sys_os_shell", "mcpop_same"):
            await complete_tool_call(
                SESSION,
                "sys_os_shell",
                {"command": "pytest -q"},
                envelope,
                is_error=False,
                operation_id="mcpop_same",
            )

    assert len(harness.log.list_for_session(WORKSPACE, SESSION)) == 1
    assert harness.log.run_ids[(WORKSPACE, SESSION, "mcpop_same")] == RUN_ID


def test_in_flight_calls_expire_and_lagging_clears() -> None:
    now = [0.0]
    calls = InFlightCalls(clock=lambda: now[0])
    call_id = calls.enter(WORKSPACE, SESSION)
    assert calls.open_before(WORKSPACE, SESSION, now[0]) == 1
    now[0] = 10_000.0
    assert calls.open_before(WORKSPACE, SESSION, now[0]) == 0
    calls.leave(WORKSPACE, SESSION, call_id)

    calls.mark_lagging(WORKSPACE, SESSION)
    assert calls.lagging(WORKSPACE, SESSION)
    now[0] += 31.0
    assert not calls.lagging(WORKSPACE, SESSION)


def test_the_step_lookup_reads_the_slot_s_node_once() -> None:
    from coral.engine.machines.slot import find_slot  # noqa: F401 - the lookup's own path
    from tests.coral.tools.fake_decision_port import InMemoryDecisionPort
    from tests.coral.workflow_builders import arrow, compile_text, end, start, step, workflow_text

    graph = compile_text(
        workflow_text(
            [start(), step("work", done_when={"commands": [{"run": "pytest -q"}]}), end()],
            [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
        )
    )[0]
    port = InMemoryDecisionPort()
    port.add_run(graph)
    spec = SimpleNamespace(host_id=None, repo_path=None, worktree_path=None, run_branch=None)
    snapshot = SimpleNamespace(
        state=port.state(), graph=graph, store=SimpleNamespace(spec=spec, run_id=RUN_ID)
    )
    loads: list[tuple[int, str]] = []

    def load(workspace_id: int, run_id: str) -> Any:
        loads.append((workspace_id, run_id))
        return snapshot

    lookup = StepEvidenceLookup(load)
    found = lookup.find(WORKSPACE, RUN_ID, SLOT)
    assert found is not None and found.requirement.items[0].run == "pytest -q"
    assert found.target is None
    assert lookup.find(WORKSPACE, RUN_ID, SLOT) is found
    assert lookup.find(WORKSPACE, RUN_ID, "missing||:0") is None
    assert loads == [(WORKSPACE, RUN_ID), (WORKSPACE, RUN_ID)]


async def test_a_run_that_overlapped_another_call_is_not_evidence(harness: _Harness) -> None:
    release = asyncio.Event()
    envelope = json.dumps({"exit_code": 0, "timed_out": False})

    async def test_run() -> None:
        with workspace_scope(WORKSPACE), tool_call_scope(SESSION, "sys_os_shell", "mcpop_t"):
            await release.wait()
            await complete_tool_call(
                SESSION,
                "sys_os_shell",
                {"command": "pytest -q"},
                envelope,
                is_error=False,
                operation_id="mcpop_t",
            )

    task = asyncio.create_task(test_run())
    await poll_until_async(lambda: harness.in_flight.open_before(WORKSPACE, SESSION, 1e18) == 1)
    await harness.edit("src/app.py")
    release.set()
    await task

    found = await harness.verdict()
    assert isinstance(found, Missing) and found.items[0].reason == "never_ran"


async def test_in_progress_turns_into_unverified_after_the_limit() -> None:
    now = [0.0]
    harness = _Harness()
    harness.in_flight = InFlightCalls(clock=lambda: now[0])
    checker = EvidenceChecker(
        steps=_Steps(),
        observations=harness.log,
        in_flight=harness.in_flight,
        read_l1=harness.tree.read_l1,
        run_in_thread=_inline,
    )
    harness.tree.readable = False
    binding = step_binding(SLOT, session_id=SESSION)

    assert isinstance(await checker.verdict(binding), InProgress)
    now[0] = IN_PROGRESS_LIMIT_S + 1
    late = await checker.verdict(binding)
    assert isinstance(late, Missing) and late.items[0].reason == "unverified"


async def test_a_run_without_a_worktree_is_unverified_at_once() -> None:
    class _NoWorktree(_Steps):
        def find(self, workspace_id: int, run_id: str, slot_id: str) -> StepEvidence | None:
            found = super().find(workspace_id, run_id, slot_id)
            assert found is not None
            return StepEvidence(requirement=found.requirement, run=found.run, target=None)

    harness = _Harness()
    checker = EvidenceChecker(
        steps=_NoWorktree(),
        observations=harness.log,
        in_flight=harness.in_flight,
        read_l1=harness.tree.read_l1,
        run_in_thread=_inline,
    )
    found = await checker.verdict(step_binding(SLOT, session_id=SESSION))
    assert isinstance(found, Missing) and found.items[0].reason == "unverified"


async def test_a_cancelled_record_marks_the_session_lagging(harness: _Harness) -> None:
    started = asyncio.Event()

    async def stuck(*_args: object) -> None:
        started.set()
        await asyncio.Event().wait()

    harness.capture._run_in_thread = stuck  # type: ignore[assignment]
    call = ObservedToolCall(
        session_id=SESSION,
        tool_name="sys_os_shell",
        arguments={"command": "pytest -q"},
        output="{}",
        is_error=False,
        operation_id="mcpop_c",
    )
    with workspace_scope(WORKSPACE):
        token = harness.capture.enter(SESSION, "sys_os_shell", "mcpop_c")
        assert token is not None
        task = asyncio.create_task(harness.capture.complete(token, call))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    harness.capture.release(token)
    assert harness.in_flight.lagging(WORKSPACE, SESSION)
