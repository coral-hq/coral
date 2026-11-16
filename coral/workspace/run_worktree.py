"""Create or adopt a run's git worktree on a host, and validate a repo binding.

App tier: no Omnigent imports. The host is reached through ``RunWorktreeHost``;
``coral.omni.server.worktrees`` implements it over a live host connection.

Each run gets one worktree on the branch ``coral/r-<run12>/base``, which the host
places in ``<repo-parent>/<repo>-worktrees/``. A call creates that worktree, or
adopts it when an earlier call (or a concurrent one) already made it, so it can
be retried freely. No host error text is interpreted: after a failed create the
algorithm lists the worktrees again and adopts what it finds. Liveness follows
git's own rule: a linked worktree is live while ``<path>/.git`` (a file) exists.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal, Protocol

from coral.workspace.ops import validate_commit_id

RUN_BRANCH_PREFIX = "coral/r-"
# Host error text carried in a Coral error is cut to this many UTF-8 bytes.
MAX_HOST_MESSAGE_BYTES = 2048
# Longer paths are refused rather than echoed (Linux PATH_MAX).
_MAX_PATH_LENGTH = 4096

RunWorktreeErrorCode = Literal[
    "host_offline", "not_permitted", "not_a_git_repo", "worktree_failed"
]


def run_branch_name(run_id: str) -> str:
    """
    Name a run's base branch. A hash prefix is always a valid ref component.

    :param run_id: The run's id, in any format.
    :returns: ``"coral/r-<run12>/base"``, where ``run12`` is the first 12 hex
        digits of the id's SHA-256, e.g. ``"coral/r-0a1b2c3d4e5f/base"``.
    """
    run12 = hashlib.sha256(run_id.encode()).hexdigest()[:12]
    return f"{RUN_BRANCH_PREFIX}{run12}/base"


def git_marker_path(path: str) -> str:
    """``<path>/.git``: a directory in a main worktree, a file in a linked one."""
    return path.rstrip("/\\") + "/.git"


def truncate_host_message(message: str) -> str:
    """Cut host-supplied text to ``MAX_HOST_MESSAGE_BYTES`` of UTF-8."""
    encoded = message.encode()
    if len(encoded) <= MAX_HOST_MESSAGE_BYTES:
        return message
    return encoded[:MAX_HOST_MESSAGE_BYTES].decode(errors="ignore") + " [truncated]"


@dataclass(frozen=True)
class HostPathStat:
    """
    What the host reports for one path.

    :param exists: The path exists and the host may read it.
    :param is_directory: It is a directory (symlinks are followed).
    :param canonical_path: The host's realpath of it, or ``None`` when unknown.
    """

    exists: bool
    is_directory: bool
    canonical_path: str | None


@dataclass(frozen=True)
class HostWorktreeEntry:
    """
    One worktree of a repository, as listed by the host.

    :param path: Absolute worktree directory. A listed entry may be stale: its
        directory can be gone while git still records it.
    :param branch: Checked-out branch, e.g. ``"coral/r-0a1b2c3d4e5f/base"``;
        ``None`` when detached.
    :param is_main: The repository's main worktree.
    """

    path: str
    branch: str | None
    is_main: bool


@dataclass(frozen=True)
class CreatedRunWorktree:
    """
    A worktree the host just created.

    :param path: Absolute worktree directory.
    :param branch: The branch checked out there.
    :param head_commit: Its HEAD, a full commit id; ``None`` on older hosts or
        when the host could not read it.
    """

    path: str
    branch: str
    head_commit: str | None


@dataclass(frozen=True)
class RunWorktree:
    """
    A run's worktree, created or adopted.

    :param path: Absolute worktree directory on the host. It can differ from an
        earlier call's path when the worktree had to be recreated beside a
        leftover directory (``…-base-2``), so callers compare it with the path
        they recorded.
    :param branch: The run's base branch.
    :param start_commit: The commit the worktree was created at. ``None`` on
        adoption, because that was recorded when the branch was first made, and
        when an older host does not report a full commit id.
    :param adopted: The worktree or its branch existed before this call.
    """

    path: str
    branch: str
    start_commit: str | None
    adopted: bool


@dataclass(frozen=True)
class RepoBinding:
    """
    A user's git repository on one host, validated but not persisted.

    :param user_id: The user who bound it, or ``None`` when auth is disabled.
    :param host_id: The host that holds the repository.
    :param repo_root: The main worktree's root, as the host lists it.
    :param default_base_ref: The ref new runs branch from, or ``None`` for the
        main worktree's HEAD.
    """

    user_id: str | None
    host_id: str
    repo_root: str
    default_base_ref: str | None


class RunWorktreeError(Exception):
    """A run worktree could not be created, adopted or bound."""

    def __init__(self, code: RunWorktreeErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code: RunWorktreeErrorCode = code
        self.message = message


class WorktreeCreateFailed(Exception):
    """The host ran git and could not create the worktree; ``message`` is its error."""

    def __init__(self, message: str) -> None:
        self.message = truncate_host_message(message)
        super().__init__(self.message)


class RunWorktreeHost(Protocol):
    """
    One user's host, as the algorithm needs it.

    Every method raises ``RunWorktreeError`` for an offline host, a refused host
    or a path that is not in a git repository; ``create_worktree`` raises
    ``WorktreeCreateFailed`` when git itself fails.
    """

    async def stat(self, path: str) -> HostPathStat:
        """Stat an absolute path on the host, following symlinks."""
        ...

    async def list_worktrees(self, repo_root: str) -> Sequence[HostWorktreeEntry]:
        """List every worktree of the repository that contains ``repo_root``, main first."""
        ...

    async def create_worktree(
        self, repo_root: str, branch: str, base_ref: str | None, *, existing_branch: bool
    ) -> CreatedRunWorktree:
        """
        Create a worktree of ``repo_root`` in its sibling ``<repo>-worktrees/`` directory.

        :param existing_branch: Check out ``branch``, which must exist, instead
            of creating it from ``base_ref``; ``base_ref`` is then ``None``.
        """
        ...


async def create_or_adopt_run_worktree(
    host: RunWorktreeHost, *, repo_root: str, run_id: str, base_ref: str | None
) -> RunWorktree:
    """
    Create the run's worktree, or adopt the one an earlier or concurrent call made.

    Paths compare exactly on a POSIX host, so on a case-insensitive macOS volume
    ``repo_root`` must be spelled as git lists the repository.

    :param host: The run owner's host.
    :param repo_root: Absolute local root of a worktree of the repository
        (normally the binding's ``repo_root``). Network (UNC) and device paths
        are refused.
    :param run_id: The run's id; it names the branch (``run_branch_name``).
    :param base_ref: Ref a new branch starts from, or ``None`` for the main
        worktree's HEAD.
    :returns: The worktree. ``start_commit`` is set only when this call created
        both the branch and the worktree.
    :raises RunWorktreeError: ``not_a_git_repo`` for a root that is not an
        absolute local path or not a worktree root; ``worktree_failed`` when the
        run's worktree is detached, when the host's answers are unusable, or
        (with both host errors) when neither a create nor its retry worked and
        no worktree can be adopted; or the host's own error.
    """
    branch = run_branch_name(run_id)
    root, entries = await _worktree_root(host, repo_root)
    adopted = await _adoptable(host, entries, branch)
    if adopted is not None:
        return adopted
    try:
        created = await host.create_worktree(root, branch, base_ref, existing_branch=False)
    except WorktreeCreateFailed as first_failure:
        return await _recover_failed_create(host, root, branch, first_failure)
    return _checked_creation(created, branch, adopted=False)


async def bind_repo(
    host: RunWorktreeHost,
    *,
    user_id: str | None,
    host_id: str,
    repo_root: str,
    default_base_ref: str | None,
) -> RepoBinding:
    """
    Validate that ``repo_root`` is a git repository on the host, and bind its main root.

    :param host: The binding user's host (``host_id``).
    :param repo_root: Absolute root of the repository's main or a linked worktree.
    :raises RunWorktreeError: ``not_a_git_repo`` as for
        ``create_or_adopt_run_worktree``, or the host's own error.
    """
    _, entries = await _worktree_root(host, repo_root)
    main = next((entry for entry in entries if entry.is_main), None)
    if main is None:
        raise RunWorktreeError(
            "not_a_git_repo", f"the host listed no main worktree for {repo_root}"
        )
    return RepoBinding(
        user_id=user_id,
        host_id=host_id,
        repo_root=_checked_host_path(main.path, "main worktree"),
        default_base_ref=default_base_ref,
    )


async def _worktree_root(
    host: RunWorktreeHost, repo_root: str
) -> tuple[str, Sequence[HostWorktreeEntry]]:
    """Return ``repo_root``'s canonical path and its repository's worktrees."""
    problem = _path_problem(repo_root)
    if problem is not None:
        raise RunWorktreeError(
            "not_a_git_repo",
            f"repo root must be an absolute local path; {truncate_host_message(repo_root)!r} "
            f"{problem}",
        )
    # Stat first: listing a missing path walks up to an enclosing repository.
    found = await host.stat(repo_root)
    if not found.exists:
        raise RunWorktreeError("not_a_git_repo", f"repo root does not exist: {repo_root}")
    if not found.is_directory:
        raise RunWorktreeError("not_a_git_repo", f"repo root is not a directory: {repo_root}")
    root = _checked_host_path(found.canonical_path or repo_root, "canonical repo root")
    # ``C:/repo`` on a POSIX host is relative to the host's working directory.
    if _has_drive(root) != _has_drive(repo_root):
        raise RunWorktreeError(
            "not_a_git_repo", f"repo root {repo_root!r} is not an absolute path on this host"
        )
    entries = await host.list_worktrees(root)
    # A plain directory inside a repository lists that repository's worktrees.
    if not any(_same_path(entry.path, root) for entry in entries):
        raise RunWorktreeError("not_a_git_repo", _not_a_root_message(root, entries))
    return root, entries


async def _adoptable(
    host: RunWorktreeHost, entries: Sequence[HostWorktreeEntry], branch: str
) -> RunWorktree | None:
    """
    Adopt the run's live linked worktree, or refuse one that was detached.

    Git checks a branch out in at most one worktree, and the run's worktree
    directory names one worktree, so only the first matching entry of each
    kind is considered.
    """
    run_dirname = re.compile(re.escape(branch.replace("/", "-")) + r"(-[0-9]+)?")
    detached = next(
        (
            entry
            for entry in entries
            if entry.branch is None
            and not entry.is_main
            and run_dirname.fullmatch(_basename(entry.path))
        ),
        None,
    )
    # Recreating the branch elsewhere would strand the detached worktree's work.
    if detached is not None and await _is_live_worktree(host, detached.path):
        raise RunWorktreeError(
            "worktree_failed",
            f"run worktree is detached; repair it: {truncate_host_message(detached.path)}",
        )
    on_branch = next(
        (entry for entry in entries if entry.branch == branch and not entry.is_main), None
    )
    if on_branch is not None and await _is_live_worktree(host, on_branch.path):
        return RunWorktree(path=on_branch.path, branch=branch, start_commit=None, adopted=True)
    return None


async def _is_live_worktree(host: RunWorktreeHost, path: str) -> bool:
    """A listed linked worktree is live while it is a directory holding a ``.git`` file."""
    _checked_host_path(path, "listed worktree")
    # A path replaced by a file cannot hold a marker; the retry recreates the worktree.
    entry = await host.stat(path)
    if not (entry.exists and entry.is_directory):
        return False
    marker = await host.stat(git_marker_path(path))
    return marker.exists and not marker.is_directory


async def _recover_failed_create(
    host: RunWorktreeHost, root: str, branch: str, first_failure: WorktreeCreateFailed
) -> RunWorktree:
    """Retry on the existing branch, then adopt whatever a concurrent call created."""
    try:
        # Recreates a worktree whose directory was deleted; git prunes the stale entry.
        recreated = await host.create_worktree(root, branch, None, existing_branch=True)
    except WorktreeCreateFailed as retry_failure:
        adopted = await _adoptable(host, await host.list_worktrees(root), branch)
        if adopted is not None:
            return adopted
        raise RunWorktreeError(
            "worktree_failed",
            f"could not create a worktree for {branch} in {root}: {first_failure.message}; "
            f"retry on the existing branch: {retry_failure.message}",
        ) from retry_failure
    return _checked_creation(recreated, branch, adopted=True)


def _checked_creation(created: CreatedRunWorktree, branch: str, *, adopted: bool) -> RunWorktree:
    """Accept only the requested branch at a usable path; keep only a full commit id."""
    if created.branch != branch:
        raise RunWorktreeError(
            "worktree_failed",
            f"the host created {truncate_host_message(created.branch)!r} instead of {branch}",
        )
    path = _checked_host_path(created.path, "created worktree")
    start_commit = None if adopted else _full_commit_id(created.head_commit)
    return RunWorktree(path=path, branch=branch, start_commit=start_commit, adopted=adopted)


def _full_commit_id(commit: str | None) -> str | None:
    """Defence in depth for DD-17: anything but a full hex id reads as unknown."""
    if commit is None:
        return None
    try:
        validate_commit_id(commit)
    except ValueError:
        return None
    return commit


def _checked_host_path(path: str, what: str) -> str:
    """Return a host-supplied path, or raise ``worktree_failed`` when it is unusable."""
    problem = _path_problem(path)
    if problem is not None:
        shown = truncate_host_message(path)
        raise RunWorktreeError(
            "worktree_failed", f"the host returned an unusable {what} path; {shown!r} {problem}"
        )
    return path


def _path_problem(path: str) -> str | None:
    """Why ``path`` is not an absolute local path on a POSIX or Windows host, if it is not."""
    if len(path) > _MAX_PATH_LENGTH:
        return f"is longer than {_MAX_PATH_LENGTH} characters"
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in path):
        return "contains control characters"
    # Two leading separators name a network share or a Win32 device (``\\?\``, ``\\.\``);
    # stating one makes a Windows host authenticate to that server.
    if len(path) >= 2 and path[0] in "/\\" and path[1] in "/\\":
        return "is a network (UNC) or device path"
    if not (PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()):
        return "is not absolute"
    return None


def _has_drive(path: str) -> bool:
    return bool(PureWindowsPath(path).drive)


def _same_path(listed: str, canonical: str) -> bool:
    """Compare a git-listed path with a realpath; git prints Windows paths with ``/``."""
    if _has_drive(canonical):
        return PureWindowsPath(listed) == PureWindowsPath(canonical)
    return listed.rstrip("/") == canonical.rstrip("/")


def _is_inside(path: str, ancestor: str) -> bool:
    if _has_drive(path):
        return PureWindowsPath(path).is_relative_to(PureWindowsPath(ancestor))
    return PurePosixPath(path).is_relative_to(PurePosixPath(ancestor))


def _basename(path: str) -> str:
    return re.split(r"[/\\]", path.rstrip("/\\"))[-1]


def _not_a_root_message(root: str, entries: Sequence[HostWorktreeEntry]) -> str:
    """Explain why a listed repository does not have ``root`` as one of its worktrees."""
    for entry in entries:
        listed = truncate_host_message(entry.path)
        if entry.path.rstrip("/").casefold() == root.rstrip("/").casefold():
            return f"{root} differs only in letter case from the repository root {listed}"
        if _is_inside(root, entry.path):
            return f"{root} is inside the git repository at {listed}, not at its root"
    # Git lists a submodule's or a symlinked .git's directory as the main worktree.
    return (
        f"{root} is a git work tree whose repository is stored elsewhere (a submodule or "
        "a symlinked .git); run worktrees need the repository's own checkout"
    )
