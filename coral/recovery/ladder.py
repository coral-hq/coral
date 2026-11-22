"""The restart ladder: a retried step's ``recovery.restart`` row, run while its run is paused.

One row per ``retry_step``, fenced by the slot's new generation, does in order:

1. **Fence** the old session (:func:`coral.slots.executors.fence_session`): end a
   running turn, label it ``omnigent.closed`` and stop its runner. The stop returns
   only once confirmed, and the host ends a Coral step runner's process group before
   it confirms. An unconfirmed stop fails retryably with nothing salvaged.
2. A **reader** is done: it never wrote the run worktree.
3. **Head check**: HEAD must be the expected head, the newest commit the run recorded
   (a close's, or a restart's kept head), else the run's base commit. A commit this
   step's own close made but never reported also passes: its op intent names the head
   it started from, and the close's own commit op, retried, answers with it as its
   record. Anything else is ``workspace.head_moved``, with nothing salvaged. With no
   expected head the restart resets to HEAD unverified. The head is recorded (an op
   intent) before anything is salvaged.
4. **Salvage, then reset under the salvage**, in rounds. Each round records the tree
   at ``refs/coral/salvage/<op key>`` and resets only while the host finds HEAD still
   the salvage's parent and every changed path as the salvage recorded it. A tree
   changed in between is salvaged again; after :data:`MAX_SALVAGE_ROUNDS` the restart
   fails ``workspace.tree_changed`` without a reset. Nothing is salvaged after a reset.

Every phase is safe to repeat. The stop and the label are idempotent; each round's
reset is recorded (an op intent) before it is sent, and the finished restart's salvage
once it ends, so a repeat resumes at the last round and a finished one names the same
ref. A write that lands while the host itself resets is not recorded; once the
runner's group is gone only a person can write there. Logs carry the run id, the
phase and codes only.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from coral.db.enum_codecs import WorkspaceOpIntentOp
from coral.model.ids import effect_op_key
from coral.omni.protocols import (
    HostWorkspaceChannels,
    RunScopeRunner,
    SessionDispatch,
    SessionEdgeWatcher,
)
from coral.queue.executors import EffectExecutor, EffectOutcome, ExecutionContext
from coral.queue.run_effects import (
    MAX_EFFECT_KEY_CHARS,
    EffectRefused,
    invalid_payload,
    optional_text,
    session_id_field,
)
from coral.slots.close import DEFAULT_BOUNDS, CloseBounds
from coral.slots.executors import (
    MAX_GENERATION,
    close_commit_op_key,
    close_commit_params,
    fence_session,
)
from coral.stores.protocols import RunState, RunStore
from coral.stores.session_bindings import SessionBindings
from coral.stores.workspace_op_intents import WorkspaceOpIntent, WorkspaceOpIntents
from coral.workspace.executors import (
    WRITER_SLOT_ROLES,
    RunTarget,
    commit_id_field,
    refused_params,
    run_target,
    run_workspace_effect,
    workspace_for,
)
from coral.workspace.ops import (
    HEAD_MOVED,
    TREE_CHANGED,
    HostChannel,
    SalvageResult,
    WorkspaceOpError,
    WorkspaceOps,
    salvage_ref_name,
)

_logger = logging.getLogger(__name__)

# Salvage-and-reset rounds before a tree that keeps changing fails the restart.
MAX_SALVAGE_ROUNDS = 3
_OP_KEY_CONFLICT = "workspace.op_key_conflict"
_TARGET_MISMATCH = "workspace.target_mismatch"


def restart_executor(
    *,
    dispatch: SessionDispatch,
    edges: SessionEdgeWatcher,
    channels: HostWorkspaceChannels,
    bindings: SessionBindings,
    intents: WorkspaceOpIntents,
    run_store: RunStore,
    scope_runner: RunScopeRunner,
    bounds: CloseBounds = DEFAULT_BOUNDS,
) -> EffectExecutor:
    """
    The ``recovery.restart`` executor.

    Payload: ``effect_key``, ``generation``, ``session_id`` (required; ``null`` for a
    slot with no session), ``writer``, ``expected_head`` and ``close_key`` (the slot's
    newest close whose commit no receipt names), both nullable. Result:
    ``{salvage_ref, salvage_commit, head_verified, head}``: both salvage fields are
    ``null`` when nothing was salvaged, ``head`` is the commit the worktree was reset to
    (``null`` for a reader), and ``head_verified`` says it was checked against an
    expected head. It runs whether or not its run is paused.
    """

    async def execute(ctx: ExecutionContext) -> EffectOutcome:
        body = functools.partial(
            _restart,
            ctx,
            dispatch=dispatch,
            edges=edges,
            channels=channels,
            bindings=bindings,
            intents=intents,
            bounds=bounds,
        )
        return await run_workspace_effect(ctx, run_store, scope_runner, _restart_payload, body)

    return execute


def _restart_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    # Only an explicit null means "no session": a payload that lost the key fences nothing.
    if "session_id" not in payload:
        raise invalid_payload("session_id is required: null for a slot with no session")
    writer = payload.get("writer")
    if not isinstance(writer, bool):
        raise invalid_payload("writer must be true or false")
    generation = payload.get("generation")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or not 1 <= generation <= MAX_GENERATION
    ):
        raise invalid_payload(f"generation must be an integer from 1 to {MAX_GENERATION}")
    close_key = optional_text(payload, "close_key")
    if close_key is not None and (len(close_key) > MAX_EFFECT_KEY_CHARS or "\0" in close_key):
        raise invalid_payload(
            f"close_key must be at most {MAX_EFFECT_KEY_CHARS} characters, without NUL"
        )
    return {
        "session_id": None if payload["session_id"] is None else session_id_field(payload),
        "writer": writer,
        "expected_head": commit_id_field(payload, "expected_head"),
        "generation": generation,
        "close_key": close_key,
    }


@dataclass(frozen=True)
class _Keys:
    """The op keys a restart records under; each derives from the restart's effect key."""

    workspace_id: int
    effect_key: str

    def op(self, qualifier: str) -> str:
        return effect_op_key(self.workspace_id, self.effect_key, qualifier)

    @property
    def head(self) -> str:
        return self.op("reset-target")

    @property
    def done(self) -> str:
        return self.op("salvaged")

    def salvage(self, round_no: int) -> str:
        return self.op("salvage" if round_no == 1 else f"salvage-{round_no}")

    def reset(self, round_no: int) -> str:
        return self.op(f"reset-{round_no}")


def _result(
    salvaged: SalvageResult | None, *, head: str | None, head_verified: bool
) -> dict[str, Any]:
    return {
        "salvage_ref": None if salvaged is None else salvaged.ref,
        "salvage_commit": None if salvaged is None else salvaged.commit,
        "head_verified": head_verified,
        "head": head,
    }


@dataclass(frozen=True)
class _Ladder:
    """One restart's writer half: its run, worktree, records and the host it acts on."""

    ctx: ExecutionContext
    state: RunState
    target: RunTarget
    workspace: WorkspaceOps
    intents: WorkspaceOpIntents
    keys: _Keys

    @property
    def channel(self) -> HostChannel:
        return HostChannel(self.target.host_id)

    async def recorded(self, op_key: str) -> WorkspaceOpIntent | None:
        return await asyncio.to_thread(
            self.intents.get, self.ctx.workspace_id, op_key, run_id=self.state.run_id
        )

    async def record(self, op_key: str, commit: str | None) -> WorkspaceOpIntent:
        """Record ``commit`` under ``op_key`` before going on; a repeat gets the first one."""
        await self.ctx.ensure_lease()
        return await asyncio.to_thread(
            self.intents.reserve,
            self.ctx.workspace_id,
            op_key=op_key,
            run_id=self.state.run_id,
            op=WorkspaceOpIntentOp.RESET,
            host_id=self.target.host_id,
            root=self.target.ref.root,
            expected_head=commit,
        )


async def _restart(
    ctx: ExecutionContext,
    state: RunState,
    payload: Mapping[str, Any],
    *,
    dispatch: SessionDispatch,
    edges: SessionEdgeWatcher,
    channels: HostWorkspaceChannels,
    bindings: SessionBindings,
    intents: WorkspaceOpIntents,
    bounds: CloseBounds,
) -> dict[str, Any]:
    fenced = await fence_session(
        ctx,
        state,
        payload["session_id"],
        closed_label=True,
        dispatch=dispatch,
        edges=edges,
        bindings=bindings,
        bounds=bounds,
    )
    _logger.info("Coral restart of run %s: fence %s", state.run_id, fenced)
    if not payload["writer"]:
        return _result(None, head=None, head_verified=False)
    target = run_target(state)
    ladder = _Ladder(
        ctx=ctx,
        state=state,
        target=target,
        workspace=await workspace_for(channels, state, target),
        intents=intents,
        keys=_Keys(ctx.workspace_id, payload["effect_key"]),
    )
    expected = payload["expected_head"] or state.spec.base_commit
    head = await _verified_head(ladder, payload, bindings, expected)
    salvaged = await _salvage_and_reset(ladder, head)
    return _result(salvaged, head=head, head_verified=expected is not None)


def _head_moved(state: RunState, head: str, expected: str) -> EffectRefused:
    return EffectRefused(
        HEAD_MOVED,
        f"run {state.run_id}'s branch is at {head}, a commit Coral did not make on {expected}, "
        "the run's newest recorded commit; retry once the branch is back at a commit Coral "
        "made, or cancel the run",
    )


async def _verified_head(
    ladder: _Ladder, payload: Mapping[str, Any], bindings: SessionBindings, expected: str | None
) -> str:
    """
    The commit the restart resets to: HEAD, once it is checked and recorded.

    A repeat checks HEAD against the head the first try recorded.

    :raises EffectRefused: Permanent ``workspace.head_moved``.
    """
    with refused_params():
        head = (await ladder.workspace.head(ladder.target.ref, ladder.channel)).head
    recorded = await ladder.recorded(ladder.keys.head)
    if recorded is not None and recorded.expected_head is not None:
        if head != recorded.expected_head:
            raise _head_moved(ladder.state, head, recorded.expected_head)
        return head
    if (
        expected is not None
        and head != expected
        and not await _own_close_commit(ladder, payload, bindings, head=head, expected=expected)
    ):
        raise _head_moved(ladder.state, head, expected)
    recorded = await ladder.record(ladder.keys.head, head)
    if recorded.expected_head != head:
        raise _head_moved(ladder.state, head, recorded.expected_head or head)
    return head


async def _own_close_commit(
    ladder: _Ladder,
    payload: Mapping[str, Any],
    bindings: SessionBindings,
    *,
    head: str,
    expected: str,
) -> bool:
    """
    Whether HEAD is the commit this slot's own close made on ``expected`` and never reported.

    The close's op intent, which only Coral writes, must name ``expected`` as the head
    it started from on this worktree. The close's own commit op, retried with its
    params, then answers whether HEAD is its record: its ``Coral-Op`` trailer and its
    parent are checked under the worktree lock. HEAD is not ``expected``, so that op
    cannot record anything new.
    """
    close_key, session_id = payload["close_key"], payload["session_id"]
    state, ctx = ladder.state, ladder.ctx
    if close_key is None or session_id is None or not close_key.startswith(f"{state.run_id}:"):
        return False
    binding = await asyncio.to_thread(
        bindings.get, ctx.workspace_id, session_id, run_id=state.run_id
    )
    if binding is None or binding.slot_role not in WRITER_SLOT_ROLES:
        return False
    op_key = close_commit_op_key(ctx.workspace_id, close_key)
    intent = await ladder.recorded(op_key)
    if (
        intent is None
        or intent.op != WorkspaceOpIntentOp.COMMIT
        or intent.expected_head != expected
        or (intent.host_id, intent.root) != (ladder.target.host_id, ladder.target.ref.root)
    ):
        return False
    message, attempt_id = close_commit_params(state.run_id, binding)
    await ctx.ensure_lease()
    try:
        with refused_params():
            found = await ladder.workspace.commit(
                ladder.target.ref,
                ladder.channel,
                op_key=op_key,
                expected_head=expected,
                message=message,
                run_id=state.run_id,
                attempt_id=attempt_id,
            )
    except WorkspaceOpError as exc:
        if exc.code == _OP_KEY_CONFLICT:
            # HEAD is the close's record, committed with other params.
            return True
        if exc.code == _TARGET_MISMATCH:
            return False
        raise
    own = found.commit == head and not found.empty
    if own:
        _logger.info("Coral restart of run %s: HEAD is its step's own close", state.run_id)
    return own


async def _salvage_and_reset(ladder: _Ladder, head: str) -> SalvageResult | None:
    """
    Record the tree, then reset to ``head`` only under that record, in rounds.

    A repeat of a finished restart names the salvage it recorded; an unfinished one
    resumes at its last recorded round.

    :raises EffectRefused: Permanent ``workspace.tree_changed`` when every round's tree
        changed before its reset.
    """
    keys, state = ladder.keys, ladder.state
    done = await ladder.recorded(keys.done)
    if done is not None:
        return await _named(ladder, done.expected_head)
    start = 1
    for round_no in range(MAX_SALVAGE_ROUNDS, 1, -1):
        if await ladder.recorded(keys.reset(round_no)) is not None:
            start = round_no
            break
    latest: SalvageResult | None = None
    for round_no in range(start, MAX_SALVAGE_ROUNDS + 1):
        await ladder.ctx.ensure_lease()
        with refused_params():
            salvaged = await ladder.workspace.salvage(
                ladder.target.ref, ladder.channel, op_key=keys.salvage(round_no)
            )
        if salvaged.commit is None:
            # Nothing beyond HEAD to record, and no earlier try's record of this round.
            break
        latest = salvaged
        await ladder.record(keys.reset(round_no), salvaged.commit)
        try:
            # An older host refuses the precondition's param: the restart fails, unreset.
            with refused_params():
                await ladder.workspace.reset(
                    ladder.target.ref,
                    ladder.channel,
                    op_key=keys.reset(round_no),
                    commit=head,
                    salvage_commit=salvaged.commit,
                )
        except WorkspaceOpError as exc:
            if exc.code != TREE_CHANGED:
                raise
            _logger.info(
                "Coral restart of run %s: round %d found the tree changed", state.run_id, round_no
            )
            if round_no == MAX_SALVAGE_ROUNDS:
                raise EffectRefused(
                    TREE_CHANGED,
                    f"run {state.run_id}'s worktree changed before its reset in each of "
                    f"{MAX_SALVAGE_ROUNDS} rounds; each change is saved, and the worktree "
                    "was left as it is",
                ) from None
            continue
        break
    await ladder.record(keys.done, None if latest is None else latest.commit)
    _logger.info(
        "Coral restart of run %s: %s", state.run_id, "salvaged" if latest else "clean tree"
    )
    return latest


async def _named(ladder: _Ladder, commit: str | None) -> SalvageResult | None:
    """The finished restart's salvage: the round whose recorded reset names ``commit``."""
    if commit is None:
        return None
    for round_no in range(1, MAX_SALVAGE_ROUNDS + 1):
        recorded = await ladder.recorded(ladder.keys.reset(round_no))
        if recorded is not None and recorded.expected_head == commit:
            return SalvageResult(
                ref=salvage_ref_name(ladder.keys.salvage(round_no)), commit=commit
            )
    raise EffectRefused(
        "workspace.op_key_conflict",
        f"run {ladder.state.run_id}'s restart recorded salvage {commit} for no round",
    )


__all__ = [
    "MAX_SALVAGE_ROUNDS",
    "restart_executor",
]
