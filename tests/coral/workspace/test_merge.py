"""WSP-03 serial merge state machine."""

from __future__ import annotations

import pytest

from coral.workspace.agent_worktrees import agent_worktree_key
from coral.workspace.merge import (
    MergeMember,
    begin_resolving,
    fail_merge,
    open_merge,
    record_clean,
    record_conflict,
    resume_after_resolve,
)


def test_agent_worktree_branch_is_stable() -> None:
    key = agent_worktree_key(
        run_id="run-abcdef",
        node_id="implement",
        item_path=("0",),
        agent="implementer",
        roster_index=0,
        attempt=2,
    )
    assert key.branch_name().startswith("coral/r-")
    assert "-m0-t2" in key.branch_name()
    assert key.full_ref().startswith("refs/heads/coral/")
    again = agent_worktree_key(
        run_id="run-abcdef",
        node_id="implement",
        item_path=("0",),
        agent="implementer",
        roster_index=0,
        attempt=2,
    )
    assert again.branch_name() == key.branch_name()


def test_serial_merge_clean_path() -> None:
    members = (
        MergeMember(slot_id="a:0", source_ref="refs/heads/coral/a", order=0),
        MergeMember(slot_id="a:1", source_ref="refs/heads/coral/b", order=1),
    )
    state = open_merge(activation_id="work||", target_branch="coral/run", members=members)
    assert state.status == "merging"
    first = record_clean(state, "commit-a")
    assert first.state.position == 1
    assert first.state.merge_commits == ("commit-a",)
    second = record_clean(first.state, "commit-b")
    assert second.state.status == "done"
    assert second.state.merge_commits == ("commit-a", "commit-b")


def test_serial_merge_conflict_opens_resolver() -> None:
    members = (MergeMember(slot_id="a:0", source_ref="refs/heads/coral/a", order=0),)
    state = open_merge(activation_id="work||", target_branch="coral/run", members=members)
    conflicted = record_conflict(state, ("src/a.py", "src/b.py"))
    assert conflicted.open_conflict is True
    assert conflicted.state.status == "conflict"
    assert conflicted.state.resolver_slot_id == "a:0"
    assert conflicted.state.conflict_paths == ("src/a.py", "src/b.py")
    resolving = begin_resolving(conflicted.state)
    assert resolving.status == "resolving"
    resumed = resume_after_resolve(resolving)
    assert resumed.status == "merging"
    assert resumed.resolver_slot_id is None


def test_fail_merge_is_terminal() -> None:
    members = (MergeMember(slot_id="a:0", source_ref="refs/heads/coral/a", order=0),)
    state = open_merge(activation_id="work||", target_branch="coral/run", members=members)
    failed = fail_merge(record_conflict(state, ("x.py",)).state)
    assert failed.status == "failed"


def test_record_conflict_requires_paths() -> None:
    members = (MergeMember(slot_id="a:0", source_ref="refs/heads/coral/a", order=0),)
    state = open_merge(activation_id="work||", target_branch="coral/run", members=members)
    with pytest.raises(ValueError, match="conflict paths"):
        record_conflict(state, ())
