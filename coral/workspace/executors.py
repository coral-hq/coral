"""K21 executors for engine git in a run worktree: ``workspace.commit``, ``.salvage``, ``.reset``.

Each executor takes its identity and its target from the stored run (the run
row's owner and account registration, the spec's host, repository, worktree
and the run's own branch), never from the payload, and runs inside the run's
own scopes. Its effect key must be one of the run's. It reaches the user's host
through ``HostWorkspaceChannels`` and Coral's K13 host backend. Results hold
only values a repeat reproduces, bounded for the queue.

``workspace.commit`` acts for a step session. Only the current session of a
writer slot (``step_agent``, ``merge_resolver``, read from its stored binding),
bound on the run's host and at its turn end, may commit; anything else gets
``workspace.op_host_violation``. The HEAD the commit must sit on is recorded in
the op-intent store before the first try, so a retry after this op's own commit
landed returns that commit, and a branch someone else moved is a permanent
``workspace.target_mismatch``.

``workspace.salvage`` and ``workspace.reset`` use the host channel with no
session: they are the sessionless restart step, run after the old session is
fenced. The reset never salvages; its caller enqueues it only after a salvage
completed, and a salvage that fails on the tree (``git_failed``) fails
permanently, so it is not retried into a reset.
"""

from __future__ import annotations

import asyncio
import functools
import re
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from coral.db.enum_codecs import SlotRole, WorkspaceOpIntentOp
from coral.model.ids import effect_op_key
from coral.omni.protocols import (
    HostAccessRefused,
    HostWorkspaceChannels,
    RunScopeRunner,
)
from coral.queue.executors import (
    EffectExecutor,
    EffectFailed,
    EffectOutcome,
    ExecutionContext,
)
from coral.queue.run_effects import (
    MAX_FAILURE_MESSAGE_CHARS,
    EffectBody,
    EffectRefused,
    PayloadParser,
    echoed_text,
    invalid_payload,
    optional_text,
    required_text,
    run_effect,
    session_id_field,
    trim_message,
)
from coral.stores.protocols import RunState, RunStore
from coral.stores.session_bindings import SessionBinding, SessionBindings
from coral.stores.workspace_op_intents import OpIntentConflict, WorkspaceOpIntents
from coral.workspace.host_backend import ALWAYS_PERMANENT_CODES, HostWorkspaceOps
from coral.workspace.ops import (
    CommitResult,
    DiffStat,
    HostChannel,
    StepSession,
    WorkspaceOpError,
    WorkspaceOps,
    WorkspaceRef,
    check_op_host,
    validate_commit_id,
    validate_commit_message,
    validate_record_id,
)
from coral.workspace.run_worktree import run_branch_name

WORKSPACE_COMMIT = "workspace.commit"
WORKSPACE_SALVAGE = "workspace.salvage"
WORKSPACE_RESET = "workspace.reset"
# Slot roles whose session writes the run worktree; reviewers never commit.
WRITER_SLOT_ROLES: frozenset[SlotRole] = frozenset({SlotRole.STEP_AGENT, SlotRole.MERGE_RESOLVER})
# The longest wait for a turn-end answer; no answer in time is an unknown state.
TURN_END_CHECK_TIMEOUT_S = 30.0
TURN_STATE_UNKNOWN = "session.turn_state_unknown"
# Stored bytes the commit result may spend on the echoed engine ids.
NODE_ID_MAX_BYTES = 128
ITEM_PATH_MAX_BYTES = 1_024
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class TurnEndCheck(Protocol):
    """
    Whether a step session's turn has ended and the session is closed or confirmed stopped.

    Return ``True`` only then. Return ``False`` when the session is known to be
    mid-turn or still live: the commit is refused permanently
    (``workspace.op_host_violation``). When the state is unknown or cannot be
    read (a cold status cache after a restart, an unreachable runner), raise
    ``CoralSessionError`` with ``retryable=True``; any other exception also
    reaches the drainer as a retryable failure. A check that does not answer
    within the executor's timeout counts as unknown.
    """

    async def __call__(self, *, workspace_id: int, run_id: str, session_id: str) -> bool: ...


@dataclass(frozen=True)
class RunTarget:
    """The run worktree an op acts on, from the run's spec."""

    host_id: str
    repo_root: str
    ref: WorkspaceRef


def workspace_failure(exc: WorkspaceOpError) -> EffectFailed:
    """
    The effect failure for a K13 error.

    ``workspace.timeout`` (a busy worktree or the lock budget included) is
    retryable, and so is ``workspace.backend_unavailable`` unless the host
    marked it permanent (a hook, a declared filter, an old git). Every other
    code, ``git_failed`` among them, means the same op fails again.
    """
    return EffectFailed(
        error_code=exc.code,
        message=trim_message(exc.message, MAX_FAILURE_MESSAGE_CHARS),
        retryable=_retryable(exc),
    )


def _retryable(exc: WorkspaceOpError, *, read_after_commit: bool = False) -> bool:
    """
    Whether a later try of the op may succeed.

    :param read_after_commit: The failed op is a READ after a recorded commit: a
        retry reaches it again and returns the same commit, so any failure the
        host did not mark permanent is retried.
    """
    if exc.code == "workspace.timeout":
        return True
    if exc.permanent or exc.code in ALWAYS_PERMANENT_CODES:
        return False
    return read_after_commit or exc.code == "workspace.backend_unavailable"


def commit_executor(
    channels: HostWorkspaceChannels,
    intents: WorkspaceOpIntents,
    bindings: SessionBindings,
    run_store: RunStore,
    scope_runner: RunScopeRunner,
    *,
    turn_ended: TurnEndCheck,
    turn_end_timeout_s: float = TURN_END_CHECK_TIMEOUT_S,
) -> EffectExecutor:
    """
    The ``workspace.commit`` executor.

    Payload: ``effect_key``, ``session_id``, ``message``, ``attempt_id``; optional
    ``expected_head``, ``diff_from``, ``node_id``, ``item_path``. Result:
    ``{commit, empty, subject, diff_stat, node_id, item_path}``.

    :param turn_ended: The other half of the writer interlock; see
        :class:`TurnEndCheck` for what it must answer and raise.
    :param turn_end_timeout_s: How long ``turn_ended`` may take; longer is a
        retryable ``session.turn_state_unknown``.
    """

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(
            _commit,
            ctx,
            channels=channels,
            intents=intents,
            bindings=bindings,
            turn_ended=turn_ended,
            turn_end_timeout_s=turn_end_timeout_s,
        )
        return await run_workspace_effect(ctx, run_store, scope_runner, _commit_payload, body)

    return execute


def salvage_executor(
    channels: HostWorkspaceChannels, run_store: RunStore, scope_runner: RunScopeRunner
) -> EffectExecutor:
    """The ``workspace.salvage`` executor. Payload: ``effect_key``. Result: ``{ref, commit}``."""

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(_salvage, ctx, channels=channels)
        return await run_workspace_effect(ctx, run_store, scope_runner, _no_params, body)

    return execute


def reset_executor(
    channels: HostWorkspaceChannels, run_store: RunStore, scope_runner: RunScopeRunner
) -> EffectExecutor:
    """The ``workspace.reset`` executor. Payload: ``effect_key``, ``commit``; result ``{head}``."""

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(_reset, ctx, channels=channels)
        return await run_workspace_effect(ctx, run_store, scope_runner, _reset_payload, body)

    return execute


# ── Shared steps ────────────────────────────────────────────────────────────


async def run_workspace_effect(
    ctx: ExecutionContext,
    run_store: RunStore,
    scope_runner: RunScopeRunner,
    parse: PayloadParser,
    body: EffectBody,
) -> EffectOutcome:
    """The shared effect steps (:func:`run_effect`), with workspace and host failures mapped."""
    try:
        return await run_effect(ctx, run_store, scope_runner, parse, body)
    except WorkspaceOpError as exc:
        return workspace_failure(exc)
    except HostAccessRefused as exc:
        if exc.code == "host_offline":
            return EffectRefused(
                "workspace.backend_unavailable", exc.message, retryable=True
            ).outcome()
        return EffectRefused("workspace.host_not_permitted", exc.message).outcome()
    except OpIntentConflict as exc:
        return EffectRefused("workspace.op_key_conflict", str(exc)).outcome()


@contextmanager
def _refused_params() -> Iterator[None]:
    """A K13 validator or the host refused an op's params: the same op fails again."""
    try:
        yield
    except ValueError as exc:
        raise EffectRefused("workspace.invalid_params", str(exc)) from exc


def run_target(state: RunState) -> RunTarget:
    """
    The run worktree from the run's spec, on the run's own branch.

    :raises EffectRefused: Permanent ``workspace.target_mismatch`` when the spec
        names no host, repository, worktree or branch, or another run's branch.
    """
    spec = state.spec
    host_id, repo_root, root, branch = (
        spec.host_id,
        spec.repo_path,
        spec.worktree_path,
        spec.run_branch,
    )
    if not (host_id and repo_root and root and branch):
        raise EffectRefused(
            "workspace.target_mismatch", f"run {state.run_id} has no run worktree on a host"
        )
    if branch != run_branch_name(state.run_id):
        raise EffectRefused(
            "workspace.target_mismatch", f"run {state.run_id}'s spec names another run's branch"
        )
    return RunTarget(
        host_id=host_id,
        repo_root=repo_root,
        ref=WorkspaceRef(host_id=host_id, root=root, branch=branch),
    )


async def workspace_for(
    channels: HostWorkspaceChannels, state: RunState, target: RunTarget
) -> HostWorkspaceOps:
    """The K13 host backend for the run worktree, authorized for the run's owner."""
    channel = await channels.channel(
        workspace_id=state.workspace_id,
        user_id=state.run.user_id,
        account_generation=state.run.account_generation,
        host_id=target.host_id,
    )
    return HostWorkspaceOps(channel, repo_root=target.repo_root)


def _no_params(_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return {}


def _reset_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"commit": commit_id_field(payload, "commit", required=True)}


def commit_message_field(payload: Mapping[str, Any], *, required: bool) -> str | None:
    """
    The payload's commit ``message``.

    :raises EffectRefused: ``effect.invalid_payload`` unless it is a valid commit message.
    """
    message = required_text(payload, "message") if required else optional_text(payload, "message")
    if message is not None:
        try:
            validate_commit_message(message)
        except ValueError:
            raise invalid_payload(
                "message must be non-blank text without control characters other than tabs "
                "and newlines"
            ) from None
    return message


def attempt_id_field(payload: Mapping[str, Any], *, required: bool) -> str | None:
    """
    The payload's ``attempt_id``, written as the ``Coral-Attempt`` trailer.

    :raises EffectRefused: ``effect.invalid_payload`` unless it is a valid record id.
    """
    attempt_id = (
        required_text(payload, "attempt_id") if required else optional_text(payload, "attempt_id")
    )
    if attempt_id is not None:
        try:
            validate_record_id(attempt_id)
        except ValueError:
            raise invalid_payload("attempt_id must be 1-128 of a-z, 0-9, '_' or '-'") from None
    return attempt_id


def _commit_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "session_id": session_id_field(payload),
        "message": commit_message_field(payload, required=True),
        "attempt_id": attempt_id_field(payload, required=True),
        "expected_head": commit_id_field(payload, "expected_head"),
        "diff_from": commit_id_field(payload, "diff_from"),
        "node_id": echoed_text(payload, "node_id", max_stored_bytes=NODE_ID_MAX_BYTES),
        "item_path": echoed_text(payload, "item_path", max_stored_bytes=ITEM_PATH_MAX_BYTES),
    }


def commit_id_field(
    payload: Mapping[str, Any], name: str, *, required: bool = False
) -> str | None:
    """
    A full lowercase hex commit id field.

    :raises EffectRefused: ``effect.invalid_payload`` for anything else.
    """
    value = required_text(payload, name) if required else optional_text(payload, name)
    if value is not None:
        try:
            validate_commit_id(value)
        except ValueError:
            raise invalid_payload(f"{name} must be a full lowercase hex commit id") from None
    return value


def _printable(path: str) -> str:
    """A host-reported path with control characters escaped, so it cannot drive a terminal."""
    return _CONTROL.sub(lambda match: f"\\x{ord(match.group()):02x}", path)


# ── Ops ─────────────────────────────────────────────────────────────────────


async def _salvage(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    channels: HostWorkspaceChannels,
) -> dict[str, Any]:
    target = run_target(state)
    workspace = await workspace_for(channels, state, target)
    await ctx.ensure_lease()
    with _refused_params():
        result = await workspace.salvage(
            target.ref,
            HostChannel(target.host_id),
            op_key=effect_op_key(ctx.workspace_id, payload["effect_key"]),
        )
    return {"ref": result.ref, "commit": result.commit}


async def _reset(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    channels: HostWorkspaceChannels,
) -> dict[str, Any]:
    target = run_target(state)
    workspace = await workspace_for(channels, state, target)
    await ctx.ensure_lease()
    with _refused_params():
        result = await workspace.reset(
            target.ref,
            HostChannel(target.host_id),
            op_key=effect_op_key(ctx.workspace_id, payload["effect_key"]),
            commit=payload["commit"],
        )
    return {"head": result.head}


async def _commit(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    channels: HostWorkspaceChannels,
    intents: WorkspaceOpIntents,
    bindings: SessionBindings,
    turn_ended: TurnEndCheck,
    turn_end_timeout_s: float,
) -> dict[str, Any]:
    target = run_target(state)
    binding = await _writer_binding(ctx, state, target, payload["session_id"], bindings)
    session = StepSession(
        session_id=binding.session_id,
        writable=True,
        at_turn_end=await _turn_has_ended(
            ctx, state, binding.session_id, turn_ended, turn_end_timeout_s
        ),
    )
    check_op_host("commit", session)
    workspace = await workspace_for(channels, state, target)
    op_key = effect_op_key(ctx.workspace_id, payload["effect_key"])

    async def read_head() -> str:
        return (await workspace.head(target.ref, session)).head

    expected_head = await recorded_head(
        intents,
        workspace_id=ctx.workspace_id,
        run_id=state.run_id,
        op_key=op_key,
        ref=target.ref,
        payload_head=payload["expected_head"],
        read_head=read_head,
        ensure_lease=ctx.ensure_lease,
    )
    result, stat = await commit_and_diff(
        workspace,
        target.ref,
        session,
        op_key=op_key,
        expected_head=expected_head,
        message=payload["message"],
        run_id=state.run_id,
        attempt_id=payload["attempt_id"],
        diff_from=payload["diff_from"],
        ensure_lease=ctx.ensure_lease,
    )
    return {
        "commit": result.commit,
        "empty": result.empty,
        "subject": payload["message"].strip().splitlines()[0],
        "diff_stat": diff_stat_result(stat),
        "node_id": payload["node_id"],
        "item_path": payload["item_path"],
    }


def writer_refusal(
    binding: SessionBinding | None, state: RunState, target: RunTarget, session_id: str
) -> str | None:
    """
    Why the session may not write the run worktree, or ``None`` when it may.

    Only its slot's current session, bound on the run worktree's host, in a
    writer slot role, writes; a missing binding never does.
    """
    if binding is None:
        return "is not bound to this run"
    if binding.host_id != target.host_id:
        return "is bound on another host than the run worktree's"
    if not any(
        slot.session_id == session_id and slot.session_generation == binding.session_generation
        for slot in state.agent_slots
    ):
        return "is not its slot's current session"
    if binding.slot_role not in WRITER_SLOT_ROLES:
        return "is read-only: its slot role never commits"
    return None


async def _writer_binding(
    ctx: ExecutionContext,
    state: RunState,
    target: RunTarget,
    session_id: str,
    bindings: SessionBindings,
) -> SessionBinding:
    """
    The binding of the session the commit acts for, if it may write the run worktree.

    :raises WorkspaceOpError: ``workspace.op_host_violation`` when :func:`writer_refusal` refuses.
    """
    binding = await asyncio.to_thread(
        bindings.get, ctx.workspace_id, session_id, run_id=state.run_id
    )
    reason = writer_refusal(binding, state, target, session_id)
    if binding is None or reason is not None:
        raise WorkspaceOpError(
            "workspace.op_host_violation",
            f"step session {session_id} {reason}, so it may not commit",
        )
    return binding


async def _turn_has_ended(
    ctx: ExecutionContext,
    state: RunState,
    session_id: str,
    turn_ended: TurnEndCheck,
    timeout_s: float,
) -> bool:
    """The injected turn-end answer; anything but a plain ``True`` counts as mid-turn."""
    try:
        async with asyncio.timeout(timeout_s):
            answer = await turn_ended(
                workspace_id=ctx.workspace_id, run_id=state.run_id, session_id=session_id
            )
    except TimeoutError:
        raise EffectRefused(
            TURN_STATE_UNKNOWN,
            f"the turn state of step session {session_id} was not known within {timeout_s:g} s",
            retryable=True,
        ) from None
    return answer is True


async def recorded_head(
    intents: WorkspaceOpIntents,
    *,
    workspace_id: int,
    run_id: str,
    op_key: str,
    ref: WorkspaceRef,
    payload_head: str | None,
    read_head: Callable[[], Awaitable[str]],
    ensure_lease: Callable[[], Awaitable[None]],
) -> str:
    """
    The HEAD a commit must sit on: the first try's, recorded before anything writes.

    The stored intent wins over ``payload_head``, which wins over ``read_head()``.

    :raises EffectRefused: ``workspace.op_key_conflict`` for an intent without a HEAD.
    """
    stored = await asyncio.to_thread(intents.get, workspace_id, op_key, run_id=run_id)
    if stored is not None and stored.expected_head is not None:
        head = stored.expected_head
    elif payload_head is not None:
        head = payload_head
    else:
        with _refused_params():
            head = await read_head()
    await ensure_lease()
    intent = await asyncio.to_thread(
        intents.reserve,
        workspace_id,
        op_key=op_key,
        run_id=run_id,
        op=WorkspaceOpIntentOp.COMMIT,
        host_id=ref.host_id,
        root=ref.root,
        expected_head=head,
    )
    if intent.expected_head is None:
        raise EffectRefused(
            "workspace.op_key_conflict", f"op key {op_key} is recorded without a HEAD"
        )
    return intent.expected_head


async def commit_and_diff(
    workspace: WorkspaceOps,
    ref: WorkspaceRef,
    session: StepSession,
    *,
    op_key: str,
    expected_head: str,
    message: str,
    run_id: str,
    attempt_id: str,
    diff_from: str | None,
    ensure_lease: Callable[[], Awaitable[None]],
) -> tuple[CommitResult, DiffStat]:
    """
    Commit at ``expected_head`` for ``session``, then measure it from ``diff_from`` or that HEAD.

    A retry after this op's own commit landed returns that commit.

    :raises EffectRefused: ``workspace.invalid_params`` for refused params; a
        ``diff_stat`` failure keeps its code and is retryable unless permanent.
    :raises WorkspaceOpError: The commit's own K13 failure.
    """
    await ensure_lease()
    with _refused_params():
        result = await workspace.commit(
            ref,
            session,
            op_key=op_key,
            expected_head=expected_head,
            message=message,
            run_id=run_id,
            attempt_id=attempt_id,
        )
    try:
        with _refused_params():
            stat = await workspace.diff_stat(
                ref, session, from_commit=diff_from or expected_head, to_commit=result.commit
            )
    except WorkspaceOpError as exc:
        retryable = _retryable(exc, read_after_commit=True)
        raise EffectRefused(exc.code, exc.message, retryable=retryable) from exc
    return result, stat


def diff_stat_result(stat: DiffStat) -> dict[str, Any]:
    """A ``diff_stat`` as an effect result holds it, with paths that cannot drive a terminal."""
    return {
        "files_changed": stat.files_changed,
        "insertions": stat.insertions,
        "deletions": stat.deletions,
        "paths": [_printable(path) for path in stat.paths],
    }
