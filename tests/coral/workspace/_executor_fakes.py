"""Protocol fakes and a started run for the workspace executor tests."""

from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any

from coral.db.enum_codecs import (
    SessionBindingProgress,
    SessionBindingRole,
    SlotRole,
    WorkKind,
    WorkspaceOpIntentOp,
    WorkStatus,
    encode_session_binding_progress,
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
from coral.stores.session_bindings import (
    BindingNotFound,
    SessionBinding,
    SessionBindingDraft,
    adopt_binding,
    binding_from_draft,
    effect_checksum,
    effect_taken,
    is_listed_bound_session,
    slot_generation_taken,
)
from coral.stores.workspace_op_intents import OpIntentConflict, WorkspaceOpIntent
from coral.workspace.host_backend import map_host_reply
from coral.workspace.ops import HostChannelBackend, OpName, WorkspaceOpError
from coral.workspace.run_worktree import run_branch_name
from omnigent.host.frames import decode_host_frame, encode_host_frame
from omnigent.host.workspace_ops import (
    HostWorkspaceOpFrame,
    HostWorkspaceOpResultFrame,
    WorkspaceOpHandler,
    dispatch_workspace_op,
)

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
    """
    The session binding store over a dict, with its reserve rules.

    A run binds one session per effect and one per step slot and generation.

    :param run_store: Run statuses for ``list_bound_sessions``.
    :param reservable: Allow ``reserve`` and ``record_progress``; executor tests
        leave it off, so an executor that writes a binding fails its test.
    """

    # Every lookup reads the dict: nothing is cached.
    reads_fresh = True

    def __init__(
        self,
        bindings: Iterable[SessionBinding] = (),
        *,
        run_store: RunStore | None = None,
        clock: Callable[[], float] = time.time,
        reservable: bool = False,
    ) -> None:
        self.rows = {(binding.workspace_id, binding.session_id): binding for binding in bindings}
        self._run_store = run_store
        self._clock = clock
        self._reservable = reservable

    def _require_reservable(self) -> None:
        if not self._reservable:
            raise AssertionError("this test's executors never write a binding")

    def get(self, workspace_id: int, session_id: str, *, run_id: str) -> SessionBinding | None:
        binding = self.rows.get((workspace_id, session_id))
        return binding if binding is not None and binding.run_id == run_id else None

    def find_by_session(self, workspace_id: int, session_id: str) -> SessionBinding | None:
        return self.rows.get((workspace_id, session_id))

    def list_for_run(self, workspace_id: int, run_id: str) -> list[SessionBinding]:
        return sorted(
            (
                binding
                for (ws, _), binding in self.rows.items()
                if ws == workspace_id and binding.run_id == run_id
            ),
            key=lambda binding: (binding.role, binding.session_id),
        )

    def reserve(self, draft: SessionBindingDraft) -> SessionBinding:
        self._require_reservable()
        wanted = binding_from_draft(draft, int(self._clock()))
        stored = self.rows.get((wanted.workspace_id, wanted.session_id))
        if stored is not None:
            return adopt_binding(stored, wanted)
        same_run = [
            binding
            for binding in self.rows.values()
            if binding.workspace_id == wanted.workspace_id and binding.run_id == wanted.run_id
        ]
        if any(binding.effect_cksum == wanted.effect_cksum for binding in same_run):
            raise effect_taken(wanted)
        if wanted.slot_id is not None and any(
            (binding.slot_id, binding.session_generation)
            == (wanted.slot_id, wanted.session_generation)
            for binding in same_run
        ):
            raise slot_generation_taken(wanted)
        self.rows[(wanted.workspace_id, wanted.session_id)] = wanted
        return wanted

    def record_progress(
        self, workspace_id: int, session_id: str, progress: SessionBindingProgress | str
    ) -> SessionBinding:
        self._require_reservable()
        stored = self.rows.get((workspace_id, session_id))
        if stored is None:
            raise BindingNotFound(f"no binding for session {session_id}")
        target = SessionBindingProgress(encode_session_binding_progress(progress))
        if target > stored.progress:
            stored = replace(stored, progress=target, updated_at=int(self._clock()))
            self.rows[(workspace_id, session_id)] = stored
        return stored

    def list_bound_sessions(
        self, *, cursor: tuple[int, str] | None = None, limit: int = 500
    ) -> list[SessionBinding]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if self._run_store is None:
            raise AssertionError("list_bound_sessions reads run statuses: pass run_store")
        found: list[SessionBinding] = []
        for key, binding in sorted(self.rows.items()):
            if cursor is not None and key <= cursor:
                continue
            run = self._run_store.get_run(binding.run_id, workspace_id=binding.workspace_id)
            if is_listed_bound_session(binding, None if run is None else run.status):
                found.append(binding)
            if len(found) == limit:
                break
        return found


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


@dataclass(frozen=True)
class InProcessHostChannel:
    """A ``HostChannelBackend`` that serves one host's ops in this process.

    Each request and result crosses the host channel's real frame codec, and
    the host's real dispatcher runs the handler in a worker thread; replies map
    through ``map_host_reply``, as the server adapter's do.
    """

    host_id: str
    handlers: Mapping[str, WorkspaceOpHandler]

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
        if host_id != self.host_id:
            raise WorkspaceOpError("workspace.backend_unavailable", f"host {host_id} is offline")
        sent = HostWorkspaceOpFrame(
            request_id=secrets.token_hex(16),
            op=op,
            root=root,
            params=dict(params),
            timeout_s=timeout_s,
            op_key=op_key,
        )
        frame = decode_host_frame(encode_host_frame(sent))
        assert isinstance(frame, HostWorkspaceOpFrame)
        result = await dispatch_workspace_op(
            frame, run_guarded=asyncio.to_thread, handlers=self.handlers
        )
        reply = decode_host_frame(encode_host_frame(result))
        assert isinstance(reply, HostWorkspaceOpResultFrame)
        return map_host_reply(
            {
                "status": reply.status,
                "payload": reply.payload,
                "error_code": reply.error_code,
                "error": reply.error,
                "exit_code": reply.exit_code,
                "permanent": reply.permanent,
            },
            host_id=host_id,
        )


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
