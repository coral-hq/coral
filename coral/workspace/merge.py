"""WSP-03 pure serial-merge state machine (no host I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MergeStatus = Literal["pending", "merging", "conflict", "resolving", "checking", "done", "failed"]


@dataclass(frozen=True)
class MergeMember:
    """One writer to merge into the run worktree, in roster order."""

    slot_id: str
    source_ref: str
    order: int


@dataclass(frozen=True)
class MergeState:
    """Serial merge of writers for one activation."""

    activation_id: str
    target_branch: str
    members: tuple[MergeMember, ...]
    position: int = 0
    status: MergeStatus = "pending"
    conflict_paths: tuple[str, ...] = ()
    resolver_slot_id: str | None = None
    merge_commits: tuple[str, ...] = ()
    attempts: int = 0


@dataclass(frozen=True)
class MergeAdvance:
    """Result of advancing the serial merge one step."""

    state: MergeState
    # When status becomes conflict, open K2 merge_conflict with these files.
    open_conflict: bool = False


def open_merge(
    *,
    activation_id: str,
    target_branch: str,
    members: tuple[MergeMember, ...],
) -> MergeState:
    """Start a serial merge; members must already be sorted by roster order."""
    ordered = tuple(sorted(members, key=lambda item: item.order))
    if not ordered:
        return MergeState(
            activation_id=activation_id,
            target_branch=target_branch,
            members=(),
            status="done",
        )
    return MergeState(
        activation_id=activation_id,
        target_branch=target_branch,
        members=ordered,
        status="merging",
    )


def record_clean(state: MergeState, merge_commit: str) -> MergeAdvance:
    """Record a clean merge of the current member and advance."""
    if state.status not in {"merging", "checking"}:
        raise ValueError(f"cannot record clean merge from {state.status}")
    commits = (*state.merge_commits, merge_commit)
    next_position = state.position + 1
    if next_position >= len(state.members):
        return MergeAdvance(
            state=MergeState(
                activation_id=state.activation_id,
                target_branch=state.target_branch,
                members=state.members,
                position=next_position,
                status="done",
                merge_commits=commits,
                attempts=state.attempts,
            )
        )
    return MergeAdvance(
        state=MergeState(
            activation_id=state.activation_id,
            target_branch=state.target_branch,
            members=state.members,
            position=next_position,
            status="merging",
            merge_commits=commits,
            attempts=state.attempts,
        )
    )


def record_conflict(state: MergeState, paths: tuple[str, ...]) -> MergeAdvance:
    """Abort into conflict; assign_task re-tasks the current member."""
    if state.status != "merging":
        raise ValueError(f"cannot record conflict from {state.status}")
    if not paths:
        raise ValueError("conflict paths are required")
    member = state.members[state.position]
    return MergeAdvance(
        state=MergeState(
            activation_id=state.activation_id,
            target_branch=state.target_branch,
            members=state.members,
            position=state.position,
            status="conflict",
            conflict_paths=tuple(sorted(paths)),
            resolver_slot_id=member.slot_id,
            merge_commits=state.merge_commits,
            attempts=state.attempts + 1,
        ),
        open_conflict=True,
    )


def begin_resolving(state: MergeState) -> MergeState:
    """Mark that coral_assign_task handed the conflict to the resolver."""
    if state.status != "conflict":
        raise ValueError(f"cannot begin resolving from {state.status}")
    return MergeState(
        activation_id=state.activation_id,
        target_branch=state.target_branch,
        members=state.members,
        position=state.position,
        status="resolving",
        conflict_paths=state.conflict_paths,
        resolver_slot_id=state.resolver_slot_id,
        merge_commits=state.merge_commits,
        attempts=state.attempts,
    )


def resume_after_resolve(state: MergeState) -> MergeState:
    """Resolver handed off cleanly; retry the same member's merge."""
    if state.status != "resolving":
        raise ValueError(f"cannot resume from {state.status}")
    return MergeState(
        activation_id=state.activation_id,
        target_branch=state.target_branch,
        members=state.members,
        position=state.position,
        status="merging",
        conflict_paths=(),
        resolver_slot_id=None,
        merge_commits=state.merge_commits,
        attempts=state.attempts,
    )


def fail_merge(state: MergeState) -> MergeState:
    """Attempts exhausted or unrecoverable merge failure."""
    return MergeState(
        activation_id=state.activation_id,
        target_branch=state.target_branch,
        members=state.members,
        position=state.position,
        status="failed",
        conflict_paths=state.conflict_paths,
        resolver_slot_id=state.resolver_slot_id,
        merge_commits=state.merge_commits,
        attempts=state.attempts,
    )
