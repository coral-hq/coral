"""Decide each engine tool call once per operation id, through the decision port.

A resent call (the runner reattaching, or retrying after its read timeout)
waits for the first one while it runs and gets the stored reply after it
committed, on this server or after a restart. The port re-checks the stored
reply on every attempt, which covers other replicas. Decisions on one run run
one at a time, and a process runs a bounded number at once, and fewer per run,
on the thread runner it is given.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import ParamSpec, Protocol, TypeVar

from coral.engine.machines.slot import find_slot
from coral.engine.types import RejectionObserved
from coral.evidence.ir import EvidenceVerdict
from coral.queue.run_effects import describe_exception
from coral.stores.session_bindings import SessionBinding
from coral.tools.port import (
    Commit,
    EngineRefused,
    Plan,
    Reply,
    RunContended,
    RunDecisionPort,
    RunNotFound,
    RunSnapshot,
)
from coral.tools.replies import busy, not_run_member, reply_for_engine_rejection
from coral.tools.schemas import COUNTED_REASONS, ToolReply

_logger = logging.getLogger(__name__)

# How long a caller waits for a decision before it is told to retry; the decision goes on.
DEFAULT_WAIT_S = 30.0
# Decisions one process runs or queues at once; more are answered "busy".
DEFAULT_MAX_IN_FLIGHT = 64
# Of those, decisions on one run: they run one at a time, so one run never takes the budget.
DEFAULT_MAX_IN_FLIGHT_PER_RUN = 4
# The /mcp route accepts operation ids of 1 to 128 characters.
OPERATION_ID_MAX = 128

_Key = tuple[int, str, bytes]
_RunKey = tuple[int, str]
_P = ParamSpec("_P")
_T = TypeVar("_T")


class ThreadRunner(Protocol):
    """Runs a blocking call off the event loop, e.g. ``asyncio.to_thread`` or a pool's ``run``."""

    def __call__(
        self, fn: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs
    ) -> Awaitable[_T]: ...


def operation_checksum(run_id: str, session_id: str, tool: str, operation_id: str) -> bytes:
    """
    The dedup key of one call: a session never reads or shares another's reply.

    Each part is length-prefixed, so no choice of parts collides with another.
    """
    digest = hashlib.sha256(b"coral-op")
    for part in (run_id, session_id, tool, operation_id):
        data = part.encode("utf-8", "surrogatepass")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.digest()


@dataclass(frozen=True)
class EngineToolCall:
    """
    One engine tool call from a bound session.

    The caller has already proved that the session's own runner sent the call
    and read ``binding`` by the authenticated session id, never from arguments
    or labels. The planners read ``binding.progress``, which grows after the
    binding is reserved, so ``binding`` must be a fresh read.

    :param binding: The session's stored binding; the run, role, slot and
        generation come only from it.
    :param arguments: The tool arguments, unvalidated.
    :param operation_id: The runner's id for this call, resent on retries;
        ``None`` when the call carried none, which is refused.
    :param evidence: For a ``done`` handoff on a step with ``done_when`` commands,
        the server's verdict on them; ``None`` when the step has none.
    """

    binding: SessionBinding
    tool: str
    arguments: Mapping[str, object]
    operation_id: str | None
    evidence: EvidenceVerdict | None = None


class TransportError(Exception):
    """Coral could not answer the call; the caller should retry. Never carries engine values."""


@dataclass
class _Decision:
    call: EngineToolCall
    task: asyncio.Task[ToolReply]
    waiters: int = 0


class ToolDispatcher:
    """
    Runs engine tool calls through ``port`` with the tool's planner.

    :param planners: Tool name to ``plan(snapshot, *, call)``.
    :param wait_s: How long a call waits for its decision before
        :class:`TransportError`; the decision keeps going and a resent call
        gets its reply.
    :param max_in_flight: Decisions running or queued at once; a new one past
        it is answered with an uncounted "busy" reply.
    :param max_in_flight_per_run: The same bound for the decisions on one run.
    :param run_in_thread: Runs each blocking port call; a server passes its own
        bounded pool, so tool calls never wait on other work's threads.
    """

    def __init__(
        self,
        port: RunDecisionPort,
        planners: Mapping[str, Callable[..., Plan]],
        *,
        wait_s: float = DEFAULT_WAIT_S,
        max_in_flight: int = DEFAULT_MAX_IN_FLIGHT,
        max_in_flight_per_run: int = DEFAULT_MAX_IN_FLIGHT_PER_RUN,
        run_in_thread: ThreadRunner = asyncio.to_thread,
    ) -> None:
        self._port = port
        self._planners = planners
        self._wait_s = wait_s
        self._max_in_flight = max_in_flight
        self._max_in_flight_per_run = max_in_flight_per_run
        self._run_in_thread = run_in_thread
        self._in_flight: dict[_Key, _Decision] = {}
        self._run_in_flight: dict[_RunKey, int] = {}
        self._run_locks: dict[_RunKey, asyncio.Lock] = {}
        self._run_users: dict[_RunKey, int] = {}

    async def dispatch(self, call: EngineToolCall) -> ToolReply:
        """
        Answer ``call``, deciding it at most once per operation id.

        :raises TransportError: For an unknown tool, a missing or malformed
            operation id, a run other writers keep changing, an engine refusal
            no reply covers, or a decision that takes longer than ``wait_s``.
        """
        planner = self._planners.get(call.tool)
        if planner is None:
            raise TransportError(f"{call.tool!r} is not one of Coral's engine tools")
        operation_id = call.operation_id
        if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= OPERATION_ID_MAX:
            raise TransportError("Coral tools need the runner's operation id")
        binding = call.binding
        cksum = operation_checksum(binding.run_id, binding.session_id, call.tool, operation_id)
        key = (binding.workspace_id, binding.run_id, cksum)
        decision = self._in_flight.get(key)
        if decision is None:
            run_key = (binding.workspace_id, binding.run_id)
            on_run = self._run_in_flight.get(run_key, 0)
            if len(self._in_flight) >= self._max_in_flight:
                return self._busy(call, "too many decisions in flight")
            if on_run >= self._max_in_flight_per_run:
                return self._busy(call, "too many decisions in flight on this run")
            task = asyncio.get_running_loop().create_task(self._decide(call, planner, cksum))
            decision = _Decision(call=call, task=task)
            self._in_flight[key] = decision
            self._run_in_flight[run_key] = on_run + 1
            task.add_done_callback(functools.partial(self._settled, key, decision))
        decision.waiters += 1
        try:
            # Shielded: a caller that goes away does not cancel a decision a resent call awaits.
            return await asyncio.wait_for(asyncio.shield(decision.task), self._wait_s)
        except TimeoutError:
            _logger.warning(
                "Coral %s from session %s in run %s: no decision after %ss; asked to retry",
                call.tool,
                binding.session_id,
                binding.run_id,
                self._wait_s,
            )
            raise TransportError("Coral is still deciding this call; retry shortly") from None
        finally:
            decision.waiters -= 1

    async def _decide(
        self, call: EngineToolCall, planner: Callable[..., Plan], cksum: bytes
    ) -> ToolReply:
        """Decide under the run's lock, so this process never races itself on one run."""
        run_key = (call.binding.workspace_id, call.binding.run_id)
        lock = self._run_locks.get(run_key)
        if lock is None:
            lock = self._run_locks[run_key] = asyncio.Lock()
        self._run_users[run_key] = self._run_users.get(run_key, 0) + 1
        try:
            async with lock:
                return await self._decide_locked(call, planner, cksum)
        finally:
            users = self._run_users[run_key] - 1
            if users:
                self._run_users[run_key] = users
            else:
                del self._run_users[run_key]
                del self._run_locks[run_key]

    async def _decide_locked(
        self, call: EngineToolCall, planner: Callable[..., Plan], cksum: bytes
    ) -> ToolReply:
        binding = call.binding
        workspace_id, run_id = binding.workspace_id, binding.run_id
        plans: list[Plan] = []

        def planned(snapshot: RunSnapshot) -> Plan:
            result = planner(snapshot, call=call)
            plans.append(result)
            return result

        try:
            stored = await self._run_in_thread(self._port.find_reply, workspace_id, run_id, cksum)
            if stored is not None:
                return stored
            try:
                reply = await self._run_in_thread(
                    self._port.decide,
                    workspace_id,
                    run_id,
                    planned,
                    cksum,
                    actor=binding.session_id,
                )
            except EngineRefused as refused:
                reply = self._engine_reply(call, refused)
                if reply.reason in COUNTED_REASONS:
                    # Counted like the planner's own refusals: observed, stored, not info-logged.
                    observe = functools.partial(_observe, binding=binding, reply=reply)
                    return await self._run_in_thread(
                        self._port.decide,
                        workspace_id,
                        run_id,
                        observe,
                        cksum,
                        actor=binding.session_id,
                    )
                detail = f"engine refused {refused.code}"
            else:
                last = plans[-1] if plans else None
                detail = last.log if isinstance(last, Reply) and last.reply == reply else None
        except RunNotFound:
            reply, detail = not_run_member(), "run not found"
        except RunContended as exc:
            _logger.warning(
                "Coral %s from session %s in run %s: the run kept changing; asked to retry",
                call.tool,
                binding.session_id,
                run_id,
            )
            raise TransportError("Coral is busy with this run; retry shortly") from exc
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001 -- answered as a retryable transport error
            # A store or load failure: named by its type, never with SQL text or values.
            _logger.warning(
                "Coral %s from session %s in run %s could not be decided (%s); asked to retry",
                call.tool,
                binding.session_id,
                run_id,
                describe_exception(exc),
            )
            raise TransportError("Coral could not answer this call; retry shortly") from None
        self._log_refusal(call, reply, detail)
        return reply

    @staticmethod
    def _engine_reply(call: EngineToolCall, refused: EngineRefused) -> ToolReply:
        try:
            reply = reply_for_engine_rejection(call.tool, refused.rejection)
        except EngineRefused:
            _logger.warning(
                "Coral %s from session %s in run %s: the engine refused a planned input "
                "with code %r",
                call.tool,
                call.binding.session_id,
                call.binding.run_id,
                refused.code,
            )
            raise TransportError("Coral could not apply this call; retry shortly") from None
        if reply.reason in COUNTED_REASONS:
            _logger.warning(
                "Coral %s from session %s in run %s: the engine refused a planned input as "
                "%s, which the planner let through; counting it",
                call.tool,
                call.binding.session_id,
                call.binding.run_id,
                refused.code,
            )
        return reply

    @staticmethod
    def _log_refusal(call: EngineToolCall, reply: ToolReply, detail: str | None) -> None:
        """One info line per uncounted refusal; counted ones are in the run's log."""
        if reply.accepted or reply.reason in COUNTED_REASONS:
            return
        _logger.info(
            "Coral %s from session %s in run %s refused: %s%s",
            call.tool,
            call.binding.session_id,
            call.binding.run_id,
            reply.reason,
            f" ({detail})" if detail else "",
        )

    def _busy(self, call: EngineToolCall, detail: str) -> ToolReply:
        reply = busy()
        self._log_refusal(call, reply, detail)
        return reply

    def _settled(self, key: _Key, decision: _Decision, task: asyncio.Task[ToolReply]) -> None:
        if self._in_flight.get(key) is decision:
            del self._in_flight[key]
        run_key = (key[0], key[1])
        on_run = self._run_in_flight[run_key] - 1
        if on_run:
            self._run_in_flight[run_key] = on_run
        else:
            del self._run_in_flight[run_key]
        if task.cancelled():
            return
        error = task.exception()
        # Callers still waiting get the error; one every caller gave up on is logged here.
        if error is not None and decision.waiters == 0 and not isinstance(error, TransportError):
            _logger.error(
                "Coral %s from session %s in run %s: the decision failed after its callers "
                "stopped waiting (%s)",
                decision.call.tool,
                decision.call.binding.session_id,
                decision.call.binding.run_id,
                describe_exception(error),
            )


def _observe(snapshot: RunSnapshot, *, binding: SessionBinding, reply: ToolReply) -> Plan:
    """Count a refusal against the caller's slot, if it is still that session's slot."""
    slot = None if binding.slot_id is None else find_slot(snapshot.state, binding.slot_id)
    if slot is None or slot.session_generation != binding.session_generation:
        return Reply(reply)
    observed = RejectionObserved(slot_id=slot.id, code=str(reply.reason))
    return Commit((observed,), reply, observation=True)
