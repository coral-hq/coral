"""Tests for ``coral.workspace.run_worktree``: the create-or-adopt algorithm.

A scripted ``RunWorktreeHost`` answers each call from the test's script and
records it, so every test pins the exact host calls of one algorithm branch.
Real git and the Omnigent host adapter are covered in
``tests/coral/omni/test_run_worktree_host.py``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import override

import pytest

from coral.workspace.run_worktree import (
    CreatedRunWorktree,
    HostPathStat,
    HostWorktreeEntry,
    RepoBinding,
    RunWorktree,
    RunWorktreeError,
    RunWorktreeHost,
    WorktreeCreateFailed,
    bind_repo,
    create_or_adopt_run_worktree,
    run_branch_name,
)

_RUN_ID = "run-1"
_BRANCH = run_branch_name(_RUN_ID)
_ROOT = "/home/me/repo"
_WORKTREE = f"/home/me/repo-worktrees/{_BRANCH.replace('/', '-')}"
_MAIN = HostWorktreeEntry(path=_ROOT, branch="main", is_main=True)
_MISSING = HostPathStat(exists=False, is_directory=False, canonical_path=None)
_HEAD = "3f2a9c1e" * 5


def _directory(path: str) -> HostPathStat:
    return HostPathStat(exists=True, is_directory=True, canonical_path=path)


def _marker(worktree: str) -> str:
    return f"{worktree}/.git"


# A linked worktree's ``.git`` is a file.
_GIT_FILE = HostPathStat(exists=True, is_directory=False, canonical_path=None)


def _run_entry(path: str, *, locked: bool = False) -> HostWorktreeEntry:
    return HostWorktreeEntry(path=path, branch=_BRANCH, is_main=False, locked=locked)


def _detached(path: str, *, locked: bool = False) -> HostWorktreeEntry:
    return HostWorktreeEntry(path=path, branch=None, is_main=False, locked=locked)


def _created(
    path: str = _WORKTREE, branch: str = _BRANCH, head: str | None = _HEAD
) -> CreatedRunWorktree:
    return CreatedRunWorktree(path=path, branch=branch, head_commit=head)


@dataclass
class _ScriptedHost(RunWorktreeHost):
    """Answers from the script; an unscripted list or create fails the test."""

    stats: Mapping[str, HostPathStat]
    listings: list[Sequence[HostWorktreeEntry] | RunWorktreeError]
    creates: list[CreatedRunWorktree | Exception] = field(default_factory=list)
    calls: list[tuple[object, ...]] = field(default_factory=list)

    @override
    async def stat(self, path: str) -> HostPathStat:
        self.calls.append(("stat", path))
        return self.stats.get(path, _MISSING)

    @override
    async def list_worktrees(self, repo_root: str) -> Sequence[HostWorktreeEntry]:
        self.calls.append(("list", repo_root))
        listing = self.listings.pop(0)
        if isinstance(listing, RunWorktreeError):
            raise listing
        return listing

    @override
    async def create_worktree(
        self, repo_root: str, branch: str, base_ref: str | None, *, existing_branch: bool
    ) -> CreatedRunWorktree:
        self.calls.append(("create", repo_root, branch, base_ref, existing_branch))
        outcome = self.creates.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _create_or_adopt(host: _ScriptedHost, root: str = _ROOT) -> Awaitable[RunWorktree]:
    return create_or_adopt_run_worktree(host, repo_root=root, run_id=_RUN_ID, base_ref="main")


async def _failure(host: _ScriptedHost, root: str = _ROOT) -> RunWorktreeError:
    with pytest.raises(RunWorktreeError) as caught:
        await _create_or_adopt(host, root)
    return caught.value


def test_run_branch_name_is_a_deterministic_hash_prefix() -> None:
    run12 = hashlib.sha256(_RUN_ID.encode()).hexdigest()[:12]
    assert run_branch_name(_RUN_ID) == f"coral/r-{run12}/base"
    assert run_branch_name(_RUN_ID) == run_branch_name("run-1")
    assert run_branch_name("run-2") != _BRANCH
    assert re.fullmatch(r"coral/r-[0-9a-f]{12}/base", run_branch_name("ü/../~:"))


@pytest.mark.parametrize(
    ("given_root", "canonical_root", "listed_root"),
    [
        ("/home/me/repo-link", _ROOT, _ROOT),
        ("C:\\Users\\me\\repo", "C:\\Users\\me\\repo", "C:/Users/me/repo"),
    ],
    ids=["symlink-canonicalised", "windows-host"],
)
async def test_creates_worktree_on_the_canonical_root(
    given_root: str, canonical_root: str, listed_root: str
) -> None:
    host = _ScriptedHost(
        stats={given_root: _directory(canonical_root)},
        listings=[[HostWorktreeEntry(path=listed_root, branch="main", is_main=True)]],
        creates=[_created()],
    )

    result = await _create_or_adopt(host, given_root)

    assert result == RunWorktree(path=_WORKTREE, branch=_BRANCH, start_commit=_HEAD, adopted=False)
    assert host.calls == [
        ("stat", given_root),
        ("list", canonical_root),
        ("create", canonical_root, _BRANCH, "main", False),
    ]


async def test_adopts_a_live_worktree_at_a_suffixed_path() -> None:
    suffixed = f"{_WORKTREE}-2"
    host = _ScriptedHost(
        stats={
            _ROOT: _directory(_ROOT),
            suffixed: _directory(suffixed),
            _marker(suffixed): _GIT_FILE,
        },
        listings=[[_MAIN, HostWorktreeEntry("/x", "other", False), _run_entry(suffixed)]],
    )

    result = await _create_or_adopt(host)

    assert result == RunWorktree(path=suffixed, branch=_BRANCH, start_commit=None, adopted=True)
    assert host.calls == [
        ("stat", _ROOT),
        ("list", _ROOT),
        ("stat", suffixed),
        ("stat", _marker(suffixed)),
    ]


_ENTRY_STAT = ("stat", _WORKTREE)
_MARKER_STAT = ("stat", _marker(_WORKTREE))


@pytest.mark.parametrize(
    ("stale_stats", "liveness_calls"),
    [
        ({}, [_ENTRY_STAT]),
        (
            {_WORKTREE: HostPathStat(exists=True, is_directory=False, canonical_path=_WORKTREE)},
            [_ENTRY_STAT],
        ),
        ({_WORKTREE: _directory(_WORKTREE)}, [_ENTRY_STAT, _MARKER_STAT]),
        (
            {
                _WORKTREE: _directory(_WORKTREE),
                _marker(_WORKTREE): _directory(_marker(_WORKTREE)),
            },
            [_ENTRY_STAT, _MARKER_STAT],
        ),
    ],
    ids=["directory-deleted", "replaced-by-file", "plain-directory", "git-directory"],
)
async def test_recreates_a_stale_entry_through_the_existing_branch_retry(
    stale_stats: Mapping[str, HostPathStat], liveness_calls: list[tuple[object, ...]]
) -> None:
    recreated = f"{_WORKTREE}-2"
    host = _ScriptedHost(
        stats={_ROOT: _directory(_ROOT), **stale_stats},
        listings=[[_MAIN, _run_entry(_WORKTREE)]],
        creates=[WorktreeCreateFailed("a branch named it already exists"), _created(recreated)],
    )

    result = await _create_or_adopt(host)

    # The branch predates this call, so its start commit was recorded when it was made.
    assert result == RunWorktree(path=recreated, branch=_BRANCH, start_commit=None, adopted=True)
    assert host.calls == [
        ("stat", _ROOT),
        ("list", _ROOT),
        *liveness_calls,
        ("create", _ROOT, _BRANCH, "main", False),
        ("create", _ROOT, _BRANCH, None, True),
    ]


async def test_concurrent_create_adopts_the_winner_after_the_retry_fails() -> None:
    host = _ScriptedHost(
        stats={
            _ROOT: _directory(_ROOT),
            _WORKTREE: _directory(_WORKTREE),
            _marker(_WORKTREE): _GIT_FILE,
        },
        listings=[[_MAIN], [_MAIN, _run_entry(_WORKTREE)]],
        creates=[
            WorktreeCreateFailed("a branch named it already exists"),
            WorktreeCreateFailed("it is already checked out elsewhere"),
        ],
    )

    result = await _create_or_adopt(host)

    assert result == RunWorktree(path=_WORKTREE, branch=_BRANCH, start_commit=None, adopted=True)
    assert host.calls[-3:] == [("list", _ROOT), _ENTRY_STAT, _MARKER_STAT]


# Fully live, so only the lock can be the reason for the refusal.
_LIVE_WORKTREE_STATS = {
    _ROOT: _directory(_ROOT),
    _WORKTREE: _directory(_WORKTREE),
    _marker(_WORKTREE): _GIT_FILE,
}


@pytest.mark.parametrize("entry", [_run_entry, _detached], ids=["on-run-branch", "detached"])
async def test_a_locked_run_worktree_is_refused_not_adopted(
    entry: Callable[..., HostWorktreeEntry],
) -> None:
    host = _ScriptedHost(
        stats=_LIVE_WORKTREE_STATS, listings=[[_MAIN, entry(_WORKTREE, locked=True)]]
    )

    failure = await _failure(host)

    assert failure.code == "worktree_failed"
    # WHY: a start that meets a lock is another start's twin, which the caller replays.
    assert failure.locked
    assert "run worktree is locked; it may still be being created" in failure.message
    assert host.calls == [("stat", _ROOT), ("list", _ROOT)]


async def test_a_locked_worktree_listed_after_the_retry_fails_is_refused() -> None:
    # A concurrent call's create is still checking its worktree out.
    host = _ScriptedHost(
        stats=_LIVE_WORKTREE_STATS,
        listings=[[_MAIN], [_MAIN, _run_entry(_WORKTREE, locked=True)]],
        creates=[
            WorktreeCreateFailed("a branch named it already exists"),
            WorktreeCreateFailed("it is already checked out elsewhere"),
        ],
    )

    failure = await _failure(host)

    assert failure.code == "worktree_failed"
    assert failure.locked
    assert "run worktree is locked; it may still be being created" in failure.message
    assert host.calls[-1] == ("list", _ROOT)


async def test_failure_reports_both_host_messages_cut_to_size() -> None:
    long_detail = "x" * 3 * 2048
    host = _ScriptedHost(
        stats={_ROOT: _directory(_ROOT)},
        listings=[[_MAIN], [_MAIN]],
        creates=[
            WorktreeCreateFailed(f"cannot lock ref: 'refs/heads/coral' exists {long_detail}"),
            WorktreeCreateFailed("branch does not exist; cannot recreate its worktree"),
        ],
    )

    failure = await _failure(host)

    assert (failure.code, failure.locked) == ("worktree_failed", False)
    assert "cannot lock ref: 'refs/heads/coral' exists" in failure.message
    assert "branch does not exist; cannot recreate its worktree" in failure.message
    assert long_detail not in failure.message
    assert "[truncated]" in failure.message


async def test_main_worktree_on_the_run_branch_is_never_adopted() -> None:
    main_on_run_branch = HostWorktreeEntry(path=_ROOT, branch=_BRANCH, is_main=True)
    host = _ScriptedHost(
        stats={_ROOT: _directory(_ROOT), _marker(_ROOT): _directory(_marker(_ROOT))},
        listings=[[main_on_run_branch], [main_on_run_branch]],
        creates=[
            WorktreeCreateFailed("a branch named it already exists"),
            WorktreeCreateFailed(f"it is already checked out at {_ROOT}"),
        ],
    )

    failure = await _failure(host)

    assert failure.code == "worktree_failed"
    assert ("stat", _marker(_ROOT)) not in host.calls


@pytest.mark.parametrize("dirname_suffix", ["", "-3"], ids=["base", "suffixed"])
async def test_a_live_detached_run_worktree_is_refused_not_forked(dirname_suffix: str) -> None:
    detached = f"{_WORKTREE}{dirname_suffix}"
    host = _ScriptedHost(
        stats={
            _ROOT: _directory(_ROOT),
            detached: _directory(detached),
            _marker(detached): _GIT_FILE,
        },
        listings=[[_MAIN, _detached("/home/me/elsewhere"), _detached(detached)]],
    )

    failure = await _failure(host)

    assert (failure.code, failure.locked) == ("worktree_failed", False)
    assert "run worktree is detached; repair it" in failure.message
    assert host.calls == [
        ("stat", _ROOT),
        ("list", _ROOT),
        ("stat", detached),
        ("stat", _marker(detached)),
    ]


async def test_a_stale_detached_run_worktree_is_recreated() -> None:
    host = _ScriptedHost(
        stats={_ROOT: _directory(_ROOT)},
        listings=[[_MAIN, _detached(_WORKTREE)]],
        creates=[WorktreeCreateFailed("a branch named it already exists"), _created()],
    )

    result = await _create_or_adopt(host)

    assert result == RunWorktree(path=_WORKTREE, branch=_BRANCH, start_commit=None, adopted=True)


async def test_only_the_first_listed_entry_on_the_run_branch_is_considered() -> None:
    other = f"{_WORKTREE}-2"
    host = _ScriptedHost(
        stats={_ROOT: _directory(_ROOT), other: _directory(other), _marker(other): _GIT_FILE},
        listings=[[_MAIN, _run_entry(_WORKTREE), _run_entry(other)]],
        creates=[_created(head=None)],
    )

    await _create_or_adopt(host)

    # The first entry is gone, and the live second one is never looked at.
    assert [call for call in host.calls if call[0] == "stat"] == [("stat", _ROOT), _ENTRY_STAT]


@pytest.mark.parametrize(
    ("created", "expected"),
    [
        (_created(branch="main"), "worktree_failed"),
        (_created(path="repo-worktrees/x"), "worktree_failed"),
        (_created(head=_HEAD[:7]), None),
        (_created(head=_HEAD.upper()), None),
    ],
    ids=["other-branch", "relative-path", "abbreviated-head", "uppercase-head"],
)
async def test_untrustworthy_create_results_are_refused_or_dropped(
    created: CreatedRunWorktree, expected: str | None
) -> None:
    host = _ScriptedHost(stats={_ROOT: _directory(_ROOT)}, listings=[[_MAIN]], creates=[created])

    if expected is None:
        result = await _create_or_adopt(host)
        assert result.start_commit is None
    else:
        assert (await _failure(host)).code == expected


async def test_host_errors_during_create_propagate_without_a_retry() -> None:
    offline = RunWorktreeError("host_offline", "host went away")
    host = _ScriptedHost(stats={_ROOT: _directory(_ROOT)}, listings=[[_MAIN]], creates=[offline])

    assert await _failure(host) is offline
    assert [call[0] for call in host.calls] == ["stat", "list", "create"]


async def _bind(host: _ScriptedHost, root: str) -> RepoBinding:
    return await bind_repo(
        host, user_id="alice", host_id="h1", repo_root=root, default_base_ref="main"
    )


_NESTED = f"{_ROOT}/notes"
_FILE = f"{_ROOT}/README.md"
_PLAIN = "/home/me/plain"


@pytest.mark.parametrize("operation", [_create_or_adopt, _bind], ids=["create", "bind"])
@pytest.mark.parametrize(
    ("root", "stats", "listings", "expected_calls"),
    [
        ("repo", {}, [], []),
        ("~/repo", {}, [], []),
        ("", {}, [], []),
        ("\\\\attacker\\share\\repo", {}, [], []),
        ("//attacker/share/repo", {}, [], []),
        ("\\\\?\\C:\\repo", {}, [], []),
        ("\\\\.\\pipe\\x", {}, [], []),
        ("/home/me/a\nb", {}, [], []),
        ("/home/me/a\x00b", {}, [], []),
        ("/home/me/ghost", {}, [], [("stat", "/home/me/ghost")]),
        (
            _FILE,
            {_FILE: HostPathStat(exists=True, is_directory=False, canonical_path=_FILE)},
            [],
            [("stat", _FILE)],
        ),
        (
            "C:/repo",
            {"C:/repo": _directory("/srv/host-cwd/C:/repo")},
            [],
            [("stat", "C:/repo")],
        ),
        (
            _PLAIN,
            {_PLAIN: _directory(_PLAIN)},
            [RunWorktreeError("not_a_git_repo", "not a git repository")],
            [("stat", _PLAIN), ("list", _PLAIN)],
        ),
        (
            _NESTED,
            {_NESTED: _directory(_NESTED)},
            [[_MAIN]],
            [("stat", _NESTED), ("list", _NESTED)],
        ),
    ],
    ids=[
        "relative",
        "tilde",
        "empty",
        "unc-backslash",
        "unc-slash",
        "win32-file-namespace",
        "win32-device",
        "control-character",
        "nul",
        "missing",
        "file",
        "drive-path-on-posix-host",
        "not-git",
        "nested-plain-dir",
    ],
)
async def test_rejects_a_root_that_is_not_a_git_worktree_root(
    operation: Callable[[_ScriptedHost, str], Awaitable[object]],
    root: str,
    stats: Mapping[str, HostPathStat],
    listings: list[Sequence[HostWorktreeEntry] | RunWorktreeError],
    expected_calls: list[tuple[object, ...]],
) -> None:
    host = _ScriptedHost(stats=stats, listings=list(listings))

    with pytest.raises(RunWorktreeError) as caught:
        await operation(host, root)

    assert caught.value.code == "not_a_git_repo"
    assert host.calls == expected_calls


@pytest.mark.parametrize(
    ("root", "listed_main", "explanation"),
    [
        (_NESTED, _ROOT, f"is inside the git repository at {_ROOT}"),
        ("/home/me/Repo", _ROOT, f"differs only in letter case from the repository root {_ROOT}"),
        ("/home/me/super/sub", "/home/me/super/.git/modules/sub", "a submodule or a symlinked"),
    ],
    ids=["nested", "letter-case", "submodule"],
)
async def test_explains_why_a_listed_repository_does_not_have_the_root(
    root: str, listed_main: str, explanation: str
) -> None:
    host = _ScriptedHost(
        stats={root: _directory(root)},
        listings=[[HostWorktreeEntry(path=listed_main, branch="main", is_main=True)]],
    )

    failure = await _failure(host, root)

    assert failure.code == "not_a_git_repo"
    assert explanation in failure.message


@pytest.mark.parametrize("canonical", ["relative/repo", "//srv/share"], ids=["relative", "unc"])
async def test_an_unusable_canonical_path_from_the_host_is_a_worktree_failure(
    canonical: str,
) -> None:
    host = _ScriptedHost(stats={_ROOT: _directory(canonical)}, listings=[])

    assert (await _failure(host)).code == "worktree_failed"
    assert host.calls == [("stat", _ROOT)]


@pytest.mark.parametrize(
    "given_root", ["/home/me/repo-link", _WORKTREE], ids=["symlink", "linked"]
)
async def test_bind_repo_canonicalises_to_the_main_worktree_root(given_root: str) -> None:
    host = _ScriptedHost(
        stats={given_root: _directory(given_root.replace("-link", ""))},
        listings=[[_MAIN, _run_entry(_WORKTREE)]],
    )

    binding = await _bind(host, given_root)

    assert binding == RepoBinding(
        user_id="alice", host_id="h1", repo_root=_ROOT, default_base_ref="main"
    )
