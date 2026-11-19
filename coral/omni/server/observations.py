"""Done-when evidence on the server: capture each step call, then judge it at handoff (K11).

:class:`EvidenceCapture` is a tool-call observer (S105). For a bound step session whose
step has ``done_when`` commands, it records each ``sys_os_*`` shell, write and edit call
before the result reaches the agent. A shell run also gets the worktree's L1 fingerprint
after it. :class:`EvidenceChecker` answers ``coral_submit_handoff``:

1. It waits a bounded time for the session's earlier calls to be recorded.
2. It fingerprints the worktree.
3. It evaluates the stored observations.

Any call still in flight or started during the check, a record that failed moments ago,
or a fingerprint that cannot be read gives "in progress", never "missing". "In progress"
lasts at most ``IN_PROGRESS_LIMIT_S`` for a session; after that, and at once for a run
with no worktree, the commands are "missing" as ``unverified``, which spends an attempt.
A shell run that overlapped another call of the session is stored with no command, so
it can never be evidence.

The in-flight set is per process: a call made on another replica, or before a restart,
is covered only by its stored row (TLD-08).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from coral.bridge.bound_sessions import BoundSessions
from coral.bridge.commit import EngineSnapshot
from coral.engine.machines.activation import find_activation, find_node
from coral.engine.machines.slot import find_slot
from coral.evidence.capture import observation_from_tool, observed_tool, op_key_for
from coral.evidence.evaluate import evaluate
from coral.evidence.ir import (
    EvidenceRequirement,
    EvidenceVerdict,
    InProgress,
    Missing,
    MissingItem,
)
from coral.omni.protocols import HostWorkspaceChannels
from coral.queue.run_effects import EffectRefused
from coral.stores import protocols as store
from coral.stores.observations import ObservationStore
from coral.stores.session_bindings import SessionBinding
from coral.workspace.executors import RunTarget, run_target, workspace_for
from coral.workspace.ops import StepSession
from omnigent.db.db_models import current_workspace_id
from omnigent.server.tool_result_observers import ObservedToolCall

_logger = logging.getLogger(__name__)
_T = TypeVar("_T")

OBSERVER_NAME = "coral.evidence"
# The probe after each shell run; past it the tree reads as changed, which is safe.
COMMAND_FINGERPRINT_TIMEOUT_S = 5.0
SUBMIT_FINGERPRINT_TIMEOUT_S = 10.0
# How long a submit waits for the session's earlier calls to be recorded.
COVER_WAIT_S = 10.0
COVER_POLL_S = 0.05
# A failed record answers submits "in progress" for this long, then they are judged.
LAG_GRACE_S = 30.0
# An entered call older than this is forgotten: longer than the MCP proxy's own forward
# timeout (``MCP_PROXY_FORWARD_TIMEOUT_S``, 7,230 s).
IN_FLIGHT_EXPIRY_S = 7_500.0
# One record's whole budget, well under S105's 30 s bound on ``complete``.
RECORD_TIMEOUT_S = 20.0
# How long a session's submits may be answered "in progress" before they count as missing.
IN_PROGRESS_LIMIT_S = 120.0
_STEP_CACHE_MAX = 1_024


class RunInThread(Protocol):
    def __call__(self, fn: Callable[..., _T], /, *args: object) -> Awaitable[_T]: ...


SnapshotLoader = Callable[[int, str], EngineSnapshot]
# ``(step, session_id, timeout_s)`` to the run worktree's L1 digest, ``None`` if unreadable.
L1Reader = Callable[["StepEvidence", str, float], Awaitable[str | None]]


@dataclass(frozen=True)
class StepEvidence:
    """A step's requirement and where its worktree is; a run's pinned graph never changes."""

    requirement: EvidenceRequirement
    run: store.RunState
    target: RunTarget | None


class StepEvidenceLookup:
    """The requirement of the step a slot serves, cached per ``(workspace, run, slot)``."""

    def __init__(self, load: SnapshotLoader) -> None:
        self._load = load
        self._cache: OrderedDict[tuple[int, str, str], StepEvidence | None] = OrderedDict()
        self._lock = threading.Lock()

    def find(self, workspace_id: int, run_id: str, slot_id: str) -> StepEvidence | None:
        """Blocking: loads the run once per slot. ``None`` when the step has no requirement."""
        key = (workspace_id, run_id, slot_id)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        snapshot = self._load(workspace_id, run_id)
        slot = find_slot(snapshot.state, slot_id)
        if slot is None:
            # Not created yet in this snapshot: look again on the next call.
            return None
        owner = find_activation(snapshot.state, slot.activation_id)
        node = find_node(snapshot.graph, owner.node_id) if owner is not None else None
        found = None
        if node is not None and node.evidence is not None:
            found = StepEvidence(
                requirement=node.evidence, run=snapshot.store, target=_target(snapshot.store)
            )
        with self._lock:
            self._cache[key] = found
            while len(self._cache) > _STEP_CACHE_MAX:
                self._cache.popitem(last=False)
        return found


def _target(run: store.RunState) -> RunTarget | None:
    try:
        return run_target(run)
    except EffectRefused:
        return None


class InFlightCalls:
    """Observed calls not yet recorded, and sessions whose last record failed, per process."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._open: dict[tuple[int, str], dict[int, float]] = {}
        self._overlapped: set[int] = set()
        self._last_entered: dict[tuple[int, str], float] = {}
        self._lagging: dict[tuple[int, str], float] = {}
        self._waiting_since: dict[tuple[int, str], float] = {}

    def now(self) -> float:
        return self._clock()

    def enter(self, workspace_id: int, session_id: str) -> int:
        """Track a call; every call of the session open with it is marked overlapped."""
        call_id = next(self._ids)
        key = (workspace_id, session_id)
        with self._lock:
            now = self._clock()
            calls = self._open.setdefault(key, {})
            if calls:
                self._overlapped.update(calls)
                self._overlapped.add(call_id)
            calls[call_id] = now
            self._last_entered[key] = now
        return call_id

    def overlapped(self, call_id: int) -> bool:
        """Whether another call of the same session ran at any time during this one."""
        with self._lock:
            return call_id in self._overlapped

    def leave(self, workspace_id: int, session_id: str, call_id: int) -> None:
        key = (workspace_id, session_id)
        with self._lock:
            self._overlapped.discard(call_id)
            calls = self._open.get(key)
            if calls is not None:
                calls.pop(call_id, None)
                if not calls:
                    del self._open[key]

    def entered_after(self, workspace_id: int, session_id: str, mark: float) -> bool:
        """Whether a call of the session started after ``mark``."""
        with self._lock:
            return self._last_entered.get((workspace_id, session_id), float("-inf")) > mark

    def open_before(self, workspace_id: int, session_id: str, mark: float) -> int:
        """Calls of the session entered at or before ``mark`` and not yet expired."""
        oldest = self._clock() - IN_FLIGHT_EXPIRY_S
        with self._lock:
            calls = self._open.get((workspace_id, session_id), {})
            return sum(1 for entered in calls.values() if oldest < entered <= mark)

    def mark_lagging(self, workspace_id: int, session_id: str) -> None:
        with self._lock:
            self._lagging[(workspace_id, session_id)] = self._clock() + LAG_GRACE_S

    def lagging(self, workspace_id: int, session_id: str) -> bool:
        key = (workspace_id, session_id)
        with self._lock:
            until = self._lagging.get(key)
            if until is None:
                return False
            if until <= self._clock():
                del self._lagging[key]
                return False
            return True

    def waited_too_long(self, workspace_id: int, session_id: str) -> bool:
        """Note an "in progress" answer; true once they have lasted ``IN_PROGRESS_LIMIT_S``."""
        key = (workspace_id, session_id)
        with self._lock:
            since = self._waiting_since.setdefault(key, self._clock())
            if self._clock() - since < IN_PROGRESS_LIMIT_S:
                return False
            del self._waiting_since[key]
            return True

    def judged(self, workspace_id: int, session_id: str) -> None:
        """A submit got a verdict: the next "in progress" starts a new wait."""
        with self._lock:
            self._waiting_since.pop((workspace_id, session_id), None)


async def worktree_l1(
    channels: HostWorkspaceChannels | None,
    step: StepEvidence,
    session_id: str,
    *,
    timeout_s: float,
) -> str | None:
    """The run worktree's L1 digest through the owner's host channel; ``None`` if unreadable."""
    if channels is None or step.target is None:
        return None
    try:
        workspace = await asyncio.wait_for(
            workspace_for(channels, step.run, step.target), timeout_s
        )
        reader = StepSession(session_id, writable=False, at_turn_end=False)
        found = await asyncio.wait_for(
            workspace.fingerprint(step.target.ref, reader, level="L1"), timeout_s
        )
    except Exception:
        _logger.warning(
            "Coral evidence: no L1 fingerprint for session %s", session_id, exc_info=True
        )
        return None
    return found.digest


@dataclass(frozen=True)
class _Token:
    workspace_id: int
    session_id: str
    run_id: str
    slot_id: str
    call_id: int


class ChannelsRef:
    """The host channels, set once the session engine is wired."""

    def __init__(self) -> None:
        self.channels: HostWorkspaceChannels | None = None

    async def read_l1(self, step: StepEvidence, session_id: str, timeout_s: float) -> str | None:
        return await worktree_l1(self.channels, step, session_id, timeout_s=timeout_s)


class EvidenceCapture:
    """The S105 observer that records a bound step session's shell, write and edit calls."""

    def __init__(
        self,
        *,
        bound: BoundSessions,
        steps: StepEvidenceLookup,
        observations: ObservationStore,
        in_flight: InFlightCalls,
        read_l1: L1Reader,
        run_in_thread: RunInThread,
        clock_us: Callable[[], int] = lambda: time.time_ns() // 1_000,
    ) -> None:
        self._bound = bound
        self._steps = steps
        self._observations = observations
        self._in_flight = in_flight
        self._read_l1 = read_l1
        self._run_in_thread = run_in_thread
        self._clock_us = clock_us

    def enter(
        self,
        session_id: str,
        tool_name: str,
        operation_id: str | None,  # noqa: ARG002 - the op key is read at complete
    ) -> object | None:
        if observed_tool(tool_name) is None:
            return None
        workspace_id = current_workspace_id()
        bound = self._bound.lookup(workspace_id, session_id)
        if bound is None or bound.orchestrator:
            return None
        call_id = self._in_flight.enter(workspace_id, session_id)
        return _Token(workspace_id, session_id, bound.run_id, bound.engine_slot_id, call_id)

    async def complete(self, token: object, call: ObservedToolCall) -> None:
        if not isinstance(token, _Token):
            return
        try:
            await asyncio.wait_for(self._record(token, call), RECORD_TIMEOUT_S)
        except BaseException as exc:
            # A cancel (S105's own timeout) loses the record too: the submit must wait.
            self._in_flight.mark_lagging(token.workspace_id, token.session_id)
            if not isinstance(exc, Exception):
                raise
            _logger.exception(
                "Coral evidence: could not record a %s call of session %s",
                call.tool_name,
                token.session_id,
            )

    def release(self, token: object) -> None:
        if isinstance(token, _Token):
            self._in_flight.leave(token.workspace_id, token.session_id, token.call_id)

    async def _record(self, token: _Token, call: ObservedToolCall) -> None:
        step = await self._run_in_thread(
            self._steps.find, token.workspace_id, token.run_id, token.slot_id
        )
        if step is None:
            return
        l1_after = None
        if observed_tool(call.tool_name) == "shell":
            l1_after = await self._read_l1(step, token.session_id, COMMAND_FINGERPRINT_TIMEOUT_S)
        arguments = call.arguments
        if self._in_flight.overlapped(token.call_id):
            # Another call may have changed the tree while this one ran: not evidence.
            arguments = {name: value for name, value in arguments.items() if name != "command"}
        observation = observation_from_tool(
            session_id=token.session_id,
            op_key=op_key_for(call.operation_id, f"server:{token.call_id}:{self._clock_us()}"),
            obs_seq=self._clock_us(),
            tool_name=call.tool_name,
            arguments=arguments,
            output=call.output,
            l1_after=l1_after,
        )
        if observation is not None:
            await self._run_in_thread(
                self._observations.record, token.workspace_id, token.run_id, observation
            )


class EvidenceChecker:
    """Judges a step session's done-when commands when it submits a ``done`` handoff."""

    def __init__(
        self,
        *,
        steps: StepEvidenceLookup,
        observations: ObservationStore,
        in_flight: InFlightCalls,
        read_l1: L1Reader,
        run_in_thread: RunInThread,
        cover_wait_s: float = COVER_WAIT_S,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        self._steps = steps
        self._observations = observations
        self._in_flight = in_flight
        self._read_l1 = read_l1
        self._run_in_thread = run_in_thread
        self._cover_wait_s = cover_wait_s
        self._sleep = sleep

    async def verdict(self, binding: SessionBinding) -> EvidenceVerdict | None:
        """The verdict for the binding's step, or ``None`` when it has no done-when commands."""
        if binding.slot_id is None:
            return None
        try:
            step = await self._run_in_thread(
                self._steps.find, binding.workspace_id, binding.run_id, binding.slot_id
            )
        except Exception:
            _logger.exception("Coral evidence: cannot load run %s", binding.run_id)
            return InProgress(reason="the run's step could not be read yet")
        if step is None:
            return None
        workspace_id, session_id = binding.workspace_id, binding.session_id
        if step.target is None:
            return _unverified(step.requirement)
        found = await self._judge(step, workspace_id, session_id)
        if not isinstance(found, InProgress):
            self._in_flight.judged(workspace_id, session_id)
            return found
        if self._in_flight.waited_too_long(workspace_id, session_id):
            _logger.warning(
                "Coral evidence: session %s stayed unverifiable (%s); counting it missing",
                session_id,
                found.reason,
            )
            return _unverified(step.requirement)
        return found

    async def _judge(
        self, step: StepEvidence, workspace_id: int, session_id: str
    ) -> EvidenceVerdict:
        mark = self._in_flight.now()
        in_progress = await self._wait_for_cover(workspace_id, session_id, mark)
        if in_progress is None and self._in_flight.lagging(workspace_id, session_id):
            in_progress = "a recent tool call has not been recorded yet"
        if in_progress is not None:
            return InProgress(reason=in_progress)
        submit_l1 = await self._read_l1(step, session_id, SUBMIT_FINGERPRINT_TIMEOUT_S)
        try:
            observations = await self._run_in_thread(
                self._observations.list_for_session, workspace_id, session_id
            )
        except Exception:
            _logger.exception("Coral evidence: cannot read session %s observations", session_id)
            return InProgress(reason="the recorded commands could not be read yet")
        if self._in_flight.entered_after(workspace_id, session_id, mark):
            return InProgress(reason="a tool call started while the handoff was checked")
        return evaluate(step.requirement, observations, submit_l1=submit_l1)

    async def _wait_for_cover(self, workspace_id: int, session_id: str, mark: float) -> str | None:
        deadline = mark + self._cover_wait_s
        while self._in_flight.open_before(workspace_id, session_id, mark):
            if self._in_flight.now() >= deadline:
                return "earlier tool calls are still running or being recorded"
            await self._sleep(COVER_POLL_S)
        return None


def _unverified(requirement: EvidenceRequirement) -> Missing:
    return Missing(
        items=tuple(
            MissingItem(item_id=item.item_id, run=item.run, reason="unverified")
            for item in requirement.items
        )
    )


__all__ = [
    "OBSERVER_NAME",
    "ChannelsRef",
    "EvidenceCapture",
    "EvidenceChecker",
    "InFlightCalls",
    "StepEvidence",
    "StepEvidenceLookup",
    "worktree_l1",
]
