"""``StoreDecisionPort``: engine tool calls decided against the run store, once per checksum.

Each attempt reads the reply stored under the call's checksum, loads the run
through the bridge (its rows, pinned graph, frozen config and folded state),
runs the planner, applies the planned inputs and writes their entries, the work
their effects queue, the projections and the reply in one compare-and-swap
commit built by ``build_commit``. The port logs nothing: the dispatcher logs
refusals with the call's tool.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError

from coral.bridge.commit import Applied, build_commit
from coral.bridge.config import LOCK_TIMEOUT_S, epoch_seconds
from coral.bridge.service import UNBUILDABLE_ERRORS, EngineBridge
from coral.engine import transition
from coral.stores.protocols import RunContended, RunVersionConflict, ToolReplyDraft
from coral.tools.port import (
    MAX_DECIDE_ATTEMPTS,
    EngineRefused,
    Planner,
    Reply,
    RunSnapshot,
)
from coral.tools.schemas import ToolReply

# Each lost attempt waits about this long (jittered) before the next one.
DECIDE_BACKOFF_S = 0.01


class StoreDecisionPort:
    """
    The ``RunDecisionPort`` over the run store, through the engine bridge.

    A run that cannot be loaded raises the bridge's ``EngineLoadFailed`` after the
    bridge paused it; the tool call then fails as a transport error.

    :param lock_timeout_s: Bounds each commit's wait for the run row's lock.
    :param sleep: Waits between attempts; tests pass a recorder.
    """

    def __init__(
        self,
        bridge: EngineBridge,
        *,
        lock_timeout_s: float = LOCK_TIMEOUT_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if lock_timeout_s <= 0:
            raise ValueError("lock_timeout_s must be positive")
        self._bridge = bridge
        self._runs = bridge.run_store
        self._lock_timeout_s = lock_timeout_s
        self._sleep = sleep

    def find_reply(self, workspace_id: int, run_id: str, cksum: bytes) -> ToolReply | None:
        stored = self._runs.find_tool_reply(run_id, cksum, workspace_id=workspace_id)
        return None if stored is None else ToolReply.from_json(stored)

    def decide(
        self,
        workspace_id: int,
        run_id: str,
        planner: Planner,
        cksum: bytes,
        *,
        actor: str | None = None,
    ) -> ToolReply:
        """
        Decide one call at most once per ``cksum``; see ``RunDecisionPort``.

        :param actor: The calling session, recorded on every entry the commit writes.
        :raises RunNotFound: when the workspace has no such run.
        :raises EngineRefused: when the engine refuses a planned input that is not
            an observation; nothing is written.
        :raises RunContended: when other writers changed the run on every attempt.
        """
        for attempt in range(MAX_DECIDE_ATTEMPTS):
            if attempt:
                self._sleep(DECIDE_BACKOFF_S * random.uniform(0.5, 1.5))
            reply = self._attempt(workspace_id, run_id, planner, cksum, actor)
            if reply is not None:
                return reply
        raise RunContended(
            f"Run {run_id!r} changed on each of {MAX_DECIDE_ATTEMPTS} attempts to decide a call"
        )

    def _attempt(
        self,
        workspace_id: int,
        run_id: str,
        planner: Planner,
        cksum: bytes,
        actor: str | None,
    ) -> ToolReply | None:
        """One pass of the contract's steps; ``None`` when the run must be planned again."""
        stored = self.find_reply(workspace_id, run_id, cksum)
        if stored is not None:
            return stored
        snapshot = self._bridge.load(workspace_id=workspace_id, run_id=run_id)
        plan = planner(
            RunSnapshot(run=snapshot.store.run, graph=snapshot.graph, state=snapshot.state)
        )
        if isinstance(plan, Reply):
            return self._stored_or(workspace_id, run_id, cksum, plan.reply)
        now = self._bridge.now()
        state = snapshot.state
        applied: list[Applied] = []
        for command in plan.inputs:
            result = transition(snapshot.graph, state, command, now, snapshot.config)
            if result.entry.rejection is not None:
                if plan.observation:
                    return plan.reply
                raise EngineRefused(result.entry.rejection)
            applied.append(Applied(entry=result.entry, before=state, after=result.state))
            state = result.state
        reply = ToolReplyDraft(cksum=cksum, reply=plan.reply.to_json())
        try:
            changes = build_commit(snapshot, applied, now=now, actor=actor, tool_reply=reply)
        except UNBUILDABLE_ERRORS as exc:
            # Paused visibly instead; planned again, the call is answered as paused.
            self._bridge.pause_unbuildable(workspace_id=workspace_id, run_id=run_id, error=exc)
            return None
        try:
            self._runs.apply_transition(
                run_id,
                snapshot.version,
                changes,
                workspace_id=workspace_id,
                now=epoch_seconds(now),
                lock_timeout_s=self._lock_timeout_s,
            )
        except RunVersionConflict:
            return None
        except IntegrityError:
            # Only another writer's reply under this checksum is answered by retrying.
            if self._runs.find_tool_reply(run_id, cksum, workspace_id=workspace_id) is None:
                raise
            return None
        return plan.reply

    def _stored_or(
        self, workspace_id: int, run_id: str, cksum: bytes, reply: ToolReply
    ) -> ToolReply:
        """
        A planner's reply, unless this call's reply was stored since the check.

        Another server may commit the same call between the stored-reply check and the
        load; its stored reply answers the call, not this plan of the state after it.
        """
        stored = self.find_reply(workspace_id, run_id, cksum)
        return reply if stored is None else stored


__all__ = ["DECIDE_BACKOFF_S", "StoreDecisionPort"]
