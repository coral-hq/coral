"""Protocol fakes and a started run for the workspace executor tests."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from coral.db.enum_codecs import (
    SessionBindingProgress,
    SessionBindingRole,
    SlotRole,
    WorkKind,
    WorkspaceOpIntentOp,
    WorkStatus,
    encode_workspace_op_intent_op,
)
from coral.model.ids import derived_id
from coral.omni.protocols import HostAccessRefused
from coral.queue.executors import ExecutionContext
from coral.stores.protocols import (
    AgentSlotDraft,
    CoralRun,
    RunStartSpec,
    RunStore,
    Transition,
    WorkItem,
)
from coral.stores.session_bindings import SessionBinding, SessionBindingDraft, effect_checksum
from coral.stores.workspace_op_intents import OpIntentConflict, WorkspaceOpIntent
from coral.workspace.ops import HostChannelBackend, OpName
from coral.workspace.run_worktree import run_branch_name

# Every event the fakes see, in order, so a test can assert what came first.
Events = list[str]


# ``start_run``'s default branch: the run's own, ``run_branch_name(run_id)``.
OWN_BRANCH = "<the run's own branch>"


def started_run_id(*, user_id: str | None, start_key: str) -> str:
    """The id a run store's ``start_run`` gives a run started with ``start_key``."""
    return derived_id("coral-run", user_id or "", start_key)


def start_run(
    run_store: RunStore,
    *,
    workspace_id: int,
    user_id: str | None,
    account_generation: str | None,
    host_id: str | None,
    repo_path: str | None,
    worktree_path: str | None,
    run_branch: str | None = OWN_BRANCH,
    start_key: str | None = None,
) -> CoralRun:
    """
    Start a run whose spec binds the run worktree the executors act on.

    :param run_branch: The spec's branch; by default the run's own branch.
    :param start_key: Fixes the run id (see :func:`started_run_id`); a fresh one by default.
    """
    key = start_key or uuid.uuid4().hex
    run_id = started_run_id(user_id=user_id, start_key=key)
    run = run_store.start_run(
        RunStartSpec(
            workflow_id="review",
            version_id="v1",
            title="Review the change",
            request_preview="",
            workspace_id=workspace_id,
            user_id=user_id,
            account_generation=account_generation,
            host_id=host_id,
            repo_path=repo_path,
            worktree_path=worktree_path,
            run_branch=run_branch_name(run_id) if run_branch == OWN_BRANCH else run_branch,
        ),
        start_key=key,
    )
    assert run.id == run_id
    return run


def add_slot(
    run_store: RunStore,
    run: CoralRun,
    *,
    session_id: str,
    session_generation: int = 1,
    slot_id: str = "slot-1",
) -> None:
    """Record ``session_id`` as the current session of one of ``run``'s agent slots."""
    state, version = run_store.load_run_state(run.id, workspace_id=run.workspace_id)
    run_store.apply_transition(
        run.id,
        version,
        Transition(
            agent_slots=(
                AgentSlotDraft(
                    id=slot_id,
                    activation_id="activation-1",
                    node_id="review",
                    scope_key="review||",
                    roster_index=0,
                    role=int(SlotRole.STEP_AGENT),
                    session_generation=session_generation,
                    session_id=session_id,
                ),
            )
        ),
        workspace_id=state.workspace_id,
    )


def effect_context(
    *,
    workspace_id: int,
    run_id: str,
    payload: Mapping[str, Any] | str,
    ensure_lease: Callable[[], Awaitable[bool]] | None = None,
) -> ExecutionContext:
    """The context the drainer hands an executor for one claimed effect."""
    work = WorkItem(
        workspace_id=workspace_id,
        id="work-1",
        run_id=run_id,
        kind=int(WorkKind.EFFECT),
        status=int(WorkStatus.CLAIMED),
        payload=payload if isinstance(payload, str) else json.dumps(payload),
        idempotency_cksum=b"\0" * 32,
        available_at=0,
        created_at_us=0,
    )
    return ExecutionContext(
        work=work,
        workspace_id=workspace_id,
        run_id=run_id,
        worker_id="worker-1",
        _ensure_lease_fn=ensure_lease,
    )


def step_binding(
    *,
    workspace_id: int,
    run_id: str,
    session_id: str,
    slot_role: SlotRole,
    host_id: str,
    session_generation: int = 1,
) -> SessionBinding:
    return SessionBinding(
        workspace_id=workspace_id,
        session_id=session_id,
        run_id=run_id,
        role=SessionBindingRole.STEP,
        slot_id="slot-1",
        slot_role=slot_role,
        effect_cksum=effect_checksum("create"),
        session_generation=session_generation,
        host_id=host_id,
        progress=SessionBindingProgress.INITIALIZED,
        created_at=0,
        updated_at=0,
    )


class FakeBindings:
    """``SessionBindings`` reads; the workspace executors never reserve."""

    def __init__(self, bindings: Iterable[SessionBinding] = ()) -> None:
        self.rows = {(binding.workspace_id, binding.session_id): binding for binding in bindings}

    def get(self, workspace_id: int, session_id: str, *, run_id: str) -> SessionBinding | None:
        binding = self.rows.get((workspace_id, session_id))
        return binding if binding is not None and binding.run_id == run_id else None

    def list_for_run(self, workspace_id: int, run_id: str) -> list[SessionBinding]:
        return [
            binding
            for (ws, _), binding in self.rows.items()
            if ws == workspace_id and binding.run_id == run_id
        ]

    def reserve(self, draft: SessionBindingDraft) -> SessionBinding:
        raise AssertionError("workspace executors never reserve a binding")

    def record_progress(
        self, workspace_id: int, session_id: str, progress: SessionBindingProgress | str
    ) -> SessionBinding:
        raise AssertionError("workspace executors never record progress")


class FakeIntents:
    """``WorkspaceOpIntents`` with the store's insert-if-absent and conflict rules."""

    def __init__(self, events: Events) -> None:
        self.rows: dict[tuple[int, str], WorkspaceOpIntent] = {}
        self._events = events

    def reserve(
        self,
        workspace_id: int,
        *,
        op_key: str,
        run_id: str,
        op: WorkspaceOpIntentOp | str,
        host_id: str,
        root: str,
        expected_head: str | None,
    ) -> WorkspaceOpIntent:
        self._events.append("reserve")
        wanted = WorkspaceOpIntent(
            workspace_id=workspace_id,
            op_key=op_key,
            run_id=run_id,
            op=WorkspaceOpIntentOp(encode_workspace_op_intent_op(op)),
            host_id=host_id,
            root=root,
            expected_head=expected_head,
            created_at=0,
        )
        stored = self.rows.setdefault((workspace_id, op_key), wanted)
        differs = tuple(
            name
            for name in ("run_id", "op", "host_id", "root")
            if getattr(stored, name) != getattr(wanted, name)
        )
        if differs:
            raise OpIntentConflict(f"op key {op_key} is recorded elsewhere", fields=differs)
        return stored

    def get(self, workspace_id: int, op_key: str, *, run_id: str) -> WorkspaceOpIntent | None:
        stored = self.rows.get((workspace_id, op_key))
        return stored if stored is not None and stored.run_id == run_id else None


@dataclass(frozen=True)
class ChannelRequest:
    host_id: str
    op: OpName
    root: str
    params: Mapping[str, object]
    timeout_s: float
    op_key: str | None


# A canned payload, an exception to raise, or a function of the request.
Reply = Mapping[str, object] | BaseException | Callable[[ChannelRequest], Mapping[str, object]]


class FakeHostChannel(HostChannelBackend):
    """A host channel that answers each op from ``replies`` and records every request."""

    def __init__(self, events: Events, replies: dict[str, Reply]) -> None:
        self.replies = replies
        self.requests: list[ChannelRequest] = []
        self._events = events

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
        self._events.append(op)
        request = ChannelRequest(host_id, op, root, dict(params), timeout_s, op_key)
        self.requests.append(request)
        reply = self.replies[op]
        if isinstance(reply, BaseException):
            raise reply
        return reply(request) if callable(reply) else reply

    def ops(self) -> list[str]:
        return [request.op for request in self.requests]


@dataclass
class RecordingScopeRunner:
    """``RunScopeRunner`` that records each scope and which one is open."""

    entered: list[dict[str, object]] = field(default_factory=list)
    active: dict[str, object] | None = None

    @asynccontextmanager
    async def run_scope(self, **scope: object) -> AsyncIterator[None]:
        self.entered.append(scope)
        outer, self.active = self.active, scope
        try:
            yield
        finally:
            self.active = outer


@dataclass
class FakeChannels:
    """``HostWorkspaceChannels`` handing out one channel, or refusing the host."""

    channel_backend: HostChannelBackend
    scope: RecordingScopeRunner
    refusal: HostAccessRefused | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    async def channel(
        self,
        *,
        workspace_id: int,
        user_id: str | None,
        account_generation: str | None,
        host_id: str,
    ) -> HostChannelBackend:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
                "account_generation": account_generation,
                "host_id": host_id,
                "scope": self.scope.active,
            }
        )
        if self.refusal is not None:
            raise self.refusal
        return self.channel_backend
