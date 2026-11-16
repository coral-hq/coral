"""Find and pin the worktree an op acts on, and refuse repositories K13 cannot run safely.

Git never finds the repository through the worktree's ``.git`` file, which an
agent can rewrite. ``resolve_pinned`` checks that ``root`` is in the bound
repository's own worktree list, finds the admin dir whose ``gitdir`` names
``<root>/.git`` (and whose ``commondir`` leads back to the repository) and pins
``GIT_DIR``/``GIT_WORK_TREE`` to it. Pinning skips git's own ``safe.directory``
check, so the host checks ownership itself. It then reads config (which runs
no program) and refuses, permanently: repository hooks, repo-declared filters
or merge drivers, ``filter=`` attributes, ``attr.tree``, sparse checkouts and,
on git older than 2.44, partial clones. A global filter definition alone is
allowed: the op's isolated config never loads it (K13 security requirement 1).
"""

from __future__ import annotations

import contextlib
import functools
import os
import posixpath
import re
import shutil
import stat
import tempfile
import time
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace

from coral.omni.host.ops._aside import aside_path, move_aside_enabled, moved_aside, recover
from coral.omni.host.ops._files import (
    UnreadableFile,
    lstat_in_root,
    read_in_root,
    read_small_file,
)
from coral.omni.host.ops._git import (
    BACKEND_UNAVAILABLE,
    CAPABILITY_UNAVAILABLE,
    INVALID_PARAMS,
    NO_LAZY_FETCH_VERSION,
    TARGET_MISMATCH,
    TIMEOUT,
    Git,
    check_deadline,
    host_git,
    printable,
    require_git_outside,
    require_posix,
)
from coral.omni.host.ops._jail import (
    Jail,
    JailUnavailable,
    checked_jail_tool,
    home_directory,
    log_unjailed_reads,
)
from coral.workspace.ops import (
    FALLBACK_IDENTITY_EMAIL,
    FALLBACK_IDENTITY_NAME,
    validate_commit_id,
    validate_coral_ref,
    validate_op_key,
)
from omnigent.host.workspace_ops import WorkspaceOpHandlerError, WorkspaceOpRequest

# Params every op carries: the bound repository's main worktree and the run branch.
COMMON_PARAMS = frozenset({"repo_root", "branch"})
# What a WRITE op's git writes in the common dir, besides its own admin dir:
# objects, the coral/ refs and their reflogs. Never hooks/, config, info/ or other refs.
_WRITABLE_GIT_DIRS = (
    "objects",
    "refs/heads/coral",
    "refs/coral",
    "logs/refs/heads/coral",
    "logs/refs/coral",
)
_WRITABLE_GIT_FILES = ("packed-refs", "packed-refs.lock")
# Repository-level keys read under the isolated config (global and system off).
_REFUSED_REPO_CONFIG = (
    r"^(hook\..*\.command|filter\..*|merge\..*\.driver|core\.sparsecheckout|attr\.tree"
    r"|extensions\.partialclone|remote\..*\.promisor)$"
)
# Settings read from the user's full config: the identity, and what the op
# receives as -c so it ignores and converts files as the user's git does.
_FULL_CONFIG_SETTINGS = (
    r"^(user\.name|user\.email|core\.excludesfile|core\.attributesfile|core\.autocrlf|core\.eol)$"
)
_PASSED_SETTINGS = (
    ("core.excludesfile", "core.excludesFile"),
    ("core.attributesfile", "core.attributesFile"),
    ("core.autocrlf", "core.autocrlf"),
    ("core.eol", "core.eol"),
)
_MAX_GITDIR_FILE_BYTES = 64 * 1024
# A larger attributes file is refused; scanning it would cost the op's deadline.
MAX_ATTRIBUTES_FILE_BYTES = 1024 * 1024
# Git opens .gitattributes case-insensitively on a case-folding file system.
_ATTRIBUTES_PATHSPEC = ":(glob,icase)**/.gitattributes"
# Listing attributes files walks the tree; git blocks there on a FIFO an agent planted
# (a nested .git/HEAD or a .gitignore), so the walk gets less than a whole op's time.
ATTRIBUTES_LISTING_LIMIT_S = 30.0
# Git splits attribute lines on LF and tokens on these blanks.
_ATTRIBUTE_BLANKS = re.compile(rb"[ \t\r]+")


@dataclass(frozen=True)
class PinnedTarget:
    """
    A verified worktree and the git that acts on it.

    :param git: Git with ``GIT_DIR``/``GIT_WORK_TREE`` pinned, ``cwd`` at
        ``root`` and the user's settings as ``-c`` args.
    :param git_dir: The worktree's own git dir: ``<common>/worktrees/<name>``,
        or the common dir for the main worktree.
    :param common_dir: ``<repo_root>/.git``.
    :param identity: ``(name, email)`` from the full config, else Coral's fallback.
    :param temp_dir: The op's private temp dir, canonical, removed when the op ends.
    """

    git: Git
    repo_root: str
    root: str
    git_dir: str
    common_dir: str
    identity: tuple[str, str]
    temp_dir: str | None = None


def op_params(
    request: WorkspaceOpRequest,
    *,
    required: Collection[str] = (),
    optional: Collection[str] = (),
) -> Mapping[str, object]:
    """
    Check the host is POSIX and re-validate the request before any git runs.

    :param required: Op params that must be present, besides ``COMMON_PARAMS``.
    :param optional: Op params that may be present.
    :returns: The params; ``repo_root`` and ``branch`` are strings.
    :raises WorkspaceOpHandlerError: ``workspace.backend_unavailable`` on a
        non-POSIX host; ``workspace.invalid_params`` (permanent) for a missing,
        unknown or ill-typed param, a non-canonical ``root`` or ``repo_root``,
        or a malformed ``op_key``.
    """
    require_posix()
    params = request.params
    allowed = COMMON_PARAMS | set(required) | set(optional)
    unknown = sorted(set(params) - allowed)
    missing = sorted((COMMON_PARAMS | set(required)) - set(params))
    if unknown or missing:
        raise invalid_params(f"unknown params {unknown} or missing params {missing}")
    for name, value in (("root", request.root), ("repo_root", params["repo_root"])):
        if not _is_canonical_absolute(value):
            raise invalid_params(f"{name} must be a canonical absolute path")
    if not isinstance(params["branch"], str):
        raise invalid_params("branch must be a string")
    if request.op_key is not None:
        try:
            validate_op_key(request.op_key)
        except ValueError as exc:
            raise invalid_params(str(exc)) from None
    return params


@contextmanager
def pinned(
    request: WorkspaceOpRequest, params: Mapping[str, object], *, write: bool
) -> Iterator[PinnedTarget]:
    """
    The request's target, resolved after :func:`op_params`, with its git jailed.

    The op's private temp dir lives until the block ends. A WRITE op without a
    working jail is refused (``_jail``). On macOS a WRITE op's worktree is moved
    aside for the block (``_aside``), and any op first brings back a worktree an
    interrupted op left aside.
    """
    repo_root = str(params["repo_root"])
    root = request.root
    branch = str(params["branch"])
    if move_aside_enabled():
        recover(root)
    # Git inside this op's worktree or repository must not run, even to print its version.
    git = host_git(request.deadline, outside=(repo_root, root))
    with op_temp_dir() as temp_dir:
        if not write:
            jail = op_jail(git, root=root, repo_root=repo_root, temp_dir=temp_dir)
            yield resolve_pinned(
                git,
                repo_root=repo_root,
                root=root,
                branch=branch,
                write=False,
                jail=jail,
                temp_dir=temp_dir,
            )
            return
        admin_dir = linked_worktree_admin_dir(repo_root, root, request.deadline)
        # The jail, and its tool's check, come before the worktree moves.
        jail = op_jail(
            git,
            root=root,
            repo_root=repo_root,
            temp_dir=temp_dir,
            admin_dir=admin_dir,
            work_root=aside_path(root) if move_aside_enabled() else root,
        )
        with _work_root(root) as work_root:
            yield resolve_pinned(
                git,
                repo_root=repo_root,
                root=root,
                branch=branch,
                write=True,
                jail=jail,
                temp_dir=temp_dir,
                work_root=work_root,
            )


@contextmanager
def _work_root(root: str) -> Iterator[str]:
    """Where a WRITE op's git works: ``root`` moved aside on macOS, else ``root`` itself."""
    if not move_aside_enabled():
        yield root
        return
    with moved_aside(root) as aside:
        yield aside


def linked_worktree_admin_dir(repo_root: str, root: str, deadline: float) -> str:
    """
    The admin dir of the linked worktree ``root``, verified without running git.

    A WRITE op calls this before it moves the worktree or runs git: both paths
    canonical, the common dir and ``root`` real directories owned by the host
    user, ``root`` not the main worktree, and one admin dir whose ``gitdir``
    names ``<root>/.git`` and whose ``commondir`` leads back.

    :raises WorkspaceOpHandlerError: ``workspace.target_mismatch`` or, for
        another user's files, ``workspace.backend_unavailable`` (permanent).
    """
    for name, path in (("repo_root", repo_root), ("root", root)):
        if "\n" in path or os.path.realpath(path) != path:
            raise _mismatch(f"{name} {printable(path)} is not a canonical path")
    if root == repo_root:
        raise _mismatch(
            f"{printable(root)} is the main worktree; WRITE ops run in linked worktrees only"
        )
    common_dir = os.path.join(repo_root, ".git")
    for path in (common_dir, root):
        try:
            is_directory = stat.S_ISDIR(os.lstat(path).st_mode)
        except FileNotFoundError:
            is_directory = False
        if not is_directory:
            raise _mismatch(f"{printable(path)} is not a directory")
        _require_owned(path)
    return _admin_dir(common_dir, root, deadline)


@contextmanager
def op_temp_dir() -> Iterator[str]:
    """
    A fresh private (0700) temp dir, canonical, removed afterwards.

    :raises WorkspaceOpHandlerError: ``workspace.backend_unavailable``, retryable,
        when the host's temp dir is full or unwritable.
    """
    try:
        directory = os.path.realpath(tempfile.mkdtemp(prefix="coral-op-"))
    except OSError as exc:
        raise temp_dir_unavailable(exc) from None
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def temp_dir_unavailable(exc: OSError) -> WorkspaceOpHandlerError:
    """A retryable failure of the host's temp dir, e.g. a full disk."""
    return WorkspaceOpHandlerError(
        BACKEND_UNAVAILABLE,
        f"the host's temp dir {printable(tempfile.gettempdir())} failed: "
        f"{exc.strerror or type(exc).__name__}",
    )


def op_jail(
    git: Git,
    *,
    root: str,
    repo_root: str,
    temp_dir: str,
    admin_dir: str | None = None,
    work_root: str | None = None,
) -> Jail | None:
    """
    The jail this op's git runs in; ``None`` for a READ op on a host without one.

    A WRITE op (``admin_dir`` given) may write the worktree where it will be
    (``work_root``, else ``root``), the objects, the ``coral/`` refs and their
    logs, ``packed-refs``, its own admin dir and ``temp_dir``; a READ op
    ``temp_dir`` only. Under the home directory both may read only those
    paths, the repository and git's install (the config includes and global
    ignore and attribute files join once known). The tool must sit outside
    ``root`` and ``repo_root`` before it first runs.

    :raises WorkspaceOpHandlerError: for a WRITE op, ``workspace.capability_unavailable``
        (permanent) when no jail works on this host, and
        ``workspace.backend_unavailable`` (permanent) without a home directory.
    """
    write = admin_dir is not None
    try:
        tool = checked_jail_tool(
            functools.partial(_jailed_version_failure, git),
            refuse_inside=lambda found: require_git_outside(
                found.executable, (repo_root, root), what=found.name
            ),
        )
    except JailUnavailable as exc:
        if write:
            raise WorkspaceOpHandlerError(
                CAPABILITY_UNAVAILABLE,
                f"Coral workspace WRITE ops run git in a write jail, and {exc}",
                permanent=True,
            ) from None
        log_unjailed_reads(str(exc))
        return None
    home = home_directory()
    if write and home is None:
        raise WorkspaceOpHandlerError(
            BACKEND_UNAVAILABLE,
            "Coral workspace WRITE ops need $HOME set to the host user's home directory: "
            "the write jail keeps git from reading the rest of it",
            permanent=True,
        )
    common_dir = os.path.join(repo_root, ".git")
    work_root = root if work_root is None else work_root
    readable = (work_root, common_dir, temp_dir, *_install_paths(git, home))
    jail = Jail(tool=tool, writable=(temp_dir,), home=home).allowing_reads(*readable)
    if admin_dir is None:
        return jail
    return replace(
        jail,
        writable=(work_root, *_writable_git_dirs(common_dir), admin_dir, temp_dir),
        writable_files=tuple(os.path.join(common_dir, name) for name in _WRITABLE_GIT_FILES),
    )


def _writable_git_dirs(common_dir: str) -> tuple[str, ...]:
    """The common-dir directories a WRITE op's git writes, created when missing."""
    directories = tuple(os.path.join(common_dir, name) for name in _WRITABLE_GIT_DIRS)
    for directory in directories:
        # bwrap binds only what exists; git would otherwise create these itself. A
        # reftable store has a file at refs/heads: the write-target check refuses it.
        with contextlib.suppress(OSError):
            os.makedirs(directory, exist_ok=True)
    return directories


def _jailed_version_failure(git: Git, jail: Jail) -> str | None:
    try:
        replace(git, cwd="/", jail=jail).run("--version")
    except WorkspaceOpHandlerError as exc:
        return exc.message
    return None


# The exec path of each git installed under a home directory, read once.
# custom-lint: disable-next=workspace-scoped-cache -- keyed by an executable on this host
_exec_paths: dict[str, str] = {}


def _install_paths(git: Git, home: str | None) -> tuple[str, ...]:
    """
    What jailed git needs readable of its install: nothing outside the home dir.

    A git installed under the home dir needs its own directory and its exec path,
    and nothing else there.
    """
    directory = os.path.dirname(os.path.realpath(git.executable))
    if home is None or not directory.startswith(home + "/"):
        return ()
    if git.executable not in _exec_paths:
        output = replace(git, cwd="/", jail=None).run("--exec-path").stdout
        _exec_paths[git.executable] = os.fsdecode(output.strip())
    return (directory, _exec_paths[git.executable])


def invalid_params(message: str) -> WorkspaceOpHandlerError:
    return WorkspaceOpHandlerError(INVALID_PARAMS, message, permanent=True)


def commit_param(params: Mapping[str, object], name: str, *, required: bool = False) -> str | None:
    """A full hex commit id param; ``None`` when an optional one is absent or null."""
    value = params.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise invalid_params(f"{name} must be a full hex commit id")
    try:
        validate_commit_id(value)
    except ValueError as exc:
        raise invalid_params(f"{name}: {exc}") from None
    return value


def resolve_pinned(
    git: Git,
    *,
    repo_root: str,
    root: str,
    branch: str,
    write: bool,
    jail: Jail | None = None,
    temp_dir: str | None = None,
    work_root: str | None = None,
) -> PinnedTarget:
    """
    Verify ``root`` against the repository at ``repo_root``, pin git to it and check its config.

    :param git: An unpinned git with the op's deadline.
    :param repo_root: The bound repository's main worktree, canonical.
    :param root: The worktree the op acts on, canonical.
    :param branch: The run branch; checked only when ``write``.
    :param write: Also require a linked worktree that is its own toplevel with
        ``refs/heads/<branch>`` checked out, ``branch`` under ``coral/``.
    :param jail: Every git call runs in it; the user's git files join its reads.
    :param temp_dir: The op's private temp dir, kept on the result.
    :param work_root: Where the worktree is now, when a WRITE op moved it aside;
        git works there, while ``root`` is still how the repository lists it.
    :raises WorkspaceOpHandlerError: ``workspace.target_mismatch`` for an
        unverified target; ``workspace.backend_unavailable`` (permanent) for a
        refused repository, another user's files or a git inside the worktree.
    """
    for name, path in (("repo_root", repo_root), ("root", root)):
        if "\n" in path or os.path.realpath(path) != path:
            raise _mismatch(f"{name} {printable(path)} is not a canonical path")
    work_root = root if work_root is None else work_root
    require_git_outside(git.executable, (repo_root, root, work_root))
    common_dir = os.path.join(repo_root, ".git")
    try:
        is_repository = stat.S_ISDIR(os.lstat(common_dir).st_mode)
    except FileNotFoundError:
        is_repository = False
    if not is_repository:
        raise _mismatch(f"{printable(repo_root)} is not a repository's main worktree")
    _require_owned(common_dir)
    if jail is not None:
        # The repository's config files, includes too, stay readable in the jail.
        reader = replace(
            git, cwd=repo_root, git_dir=common_dir, isolated=False, jail=jail.without_read_limits()
        )
        jail = jail.allowing_reads(*_repository_config_files(reader))
    git = replace(git, jail=jail)
    if root not in _listed_worktrees(replace(git, cwd=repo_root, git_dir=common_dir)):
        raise _mismatch(f"{printable(root)} is not a worktree of {printable(repo_root)}")
    if root == repo_root:
        if write:
            raise _mismatch(
                f"{printable(root)} is the main worktree; WRITE ops run in linked worktrees only"
            )
        git_dir = common_dir
    else:
        git_dir = _admin_dir(common_dir, root, git.deadline)
        _require_owned(git_dir)
    _require_owned(work_root)
    pinned = replace(git, cwd=work_root, git_dir=git_dir, work_tree=work_root)
    if write:
        _require_write_target(pinned, work_root, branch)
    _refuse_repository_config(pinned)
    # The user's own config, and whatever it includes, is read outside the read limits.
    config_reader = replace(
        pinned, isolated=False, jail=None if jail is None else jail.without_read_limits()
    )
    identity, config_args, attributes_file, user_files = _full_config_settings(config_reader)
    if jail is not None:
        jail = jail.allowing_reads(*user_files)
    pinned = replace(pinned, config_args=config_args, jail=jail)
    _refuse_declared_filters(pinned, work_root, common_dir, attributes_file)
    return PinnedTarget(
        git=pinned,
        repo_root=repo_root,
        root=work_root,
        git_dir=git_dir,
        common_dir=common_dir,
        identity=identity,
        temp_dir=temp_dir,
    )


def _is_canonical_absolute(path: object) -> bool:
    return (
        isinstance(path, str)
        and "\0" not in path
        and posixpath.isabs(path)
        and not path.startswith("//")
        and posixpath.normpath(path) == path
    )


def _mismatch(message: str) -> WorkspaceOpHandlerError:
    return WorkspaceOpHandlerError(TARGET_MISMATCH, message)


def _refused(message: str) -> WorkspaceOpHandlerError:
    return WorkspaceOpHandlerError(BACKEND_UNAVAILABLE, message, permanent=True)


def _require_owned(path: str) -> None:
    """Git's ``safe.directory`` rule, which a pinned ``GIT_DIR`` skips: the host user's only."""
    if os.lstat(path).st_uid != os.geteuid():
        raise _refused(
            f"{printable(path)} is not owned by the host user; Coral works only in "
            "repositories the host user owns"
        )


def _listed_worktrees(git: Git) -> set[str]:
    """Worktree paths from ``worktree list --porcelain`` (``-z`` needs git 2.36)."""
    output = git.run("worktree", "list", "--porcelain").stdout
    prefix = b"worktree "
    return {
        os.fsdecode(line[len(prefix) :]) for line in output.split(b"\n") if line.startswith(prefix)
    }


def _admin_dir(common_dir: str, root: str, deadline: float) -> str:
    """
    The admin dir under ``<common>/worktrees`` whose ``gitdir`` names ``<root>/.git``.

    Its ``commondir`` must lead back to ``common_dir``: git follows that file
    even with ``GIT_DIR`` pinned.
    """
    expected = os.path.join(root, ".git")
    matches = []
    try:
        entries = list(os.scandir(os.path.join(common_dir, "worktrees")))
    except FileNotFoundError:
        entries = []
    for entry in entries:
        check_deadline(deadline, "finding the worktree's admin dir")
        if not entry.is_dir(follow_symlinks=False):
            continue
        # A worktree added with --relative-paths records gitdir relative to its admin dir.
        if _recorded_path(entry.path, "gitdir", deadline) == expected:
            matches.append(entry.path)
    if len(matches) != 1:
        raise _mismatch(
            f"no single admin dir in {printable(common_dir)}/worktrees names {printable(expected)}"
        )
    recorded = _recorded_path(matches[0], "commondir", deadline)
    if recorded is None or os.path.realpath(recorded) != common_dir:
        raise _mismatch(f"the admin dir of {printable(root)} names another common dir")
    return matches[0]


def _recorded_path(admin_dir: str, name: str, deadline: float) -> str | None:
    """The path in an admin dir's ``gitdir`` or ``commondir`` file, resolved against it."""
    try:
        recorded = read_small_file(
            os.path.join(admin_dir, name),
            max_bytes=_MAX_GITDIR_FILE_BYTES,
            follow_symlinks=False,
            deadline=deadline,
        )
    except UnreadableFile:
        return None
    if recorded is None:
        return None
    return os.path.normpath(os.path.join(admin_dir, os.fsdecode(recorded.rstrip(b"\n"))))


def _require_write_target(git: Git, root: str, branch: str) -> None:
    try:
        validate_coral_ref(f"refs/heads/{branch}")
    except ValueError:
        raise _mismatch(f"branch {printable(branch)} is not a coral/ branch") from None
    toplevel = git.run("rev-parse", "--show-toplevel").stdout.rstrip(b"\n")
    if os.fsdecode(toplevel) != root:
        raise _mismatch(f"{printable(root)} is not its own toplevel")
    head = git.run("symbolic-ref", "-q", "HEAD", ok_exit_codes=(0, 1))
    if head.exit_code != 0 or head.stdout.rstrip(b"\n") != os.fsencode(f"refs/heads/{branch}"):
        raise _mismatch(f"{printable(root)} does not have {printable(branch)} checked out")
    storage = git.run("config", "--get", "extensions.refstorage", ok_exit_codes=(0, 1)).stdout
    if storage.strip() not in (b"", b"files"):
        # The write jail opens the coral/ refs as files; a reftable store is one table.
        raise _refused(
            "the repository keeps its refs in a reftable; Coral's write jail needs the "
            "files ref store"
        )


def _repository_config_files(git: Git) -> list[str]:
    """
    The repository's own config files and their includes; never global or system config.

    Isolated ops read only these (``GIT_CONFIG_GLOBAL=/dev/null``, ``GIT_CONFIG_NOSYSTEM``).
    """
    listed = git.run("config", "--list", "--show-scope", "--show-origin", "-z").stdout
    fields = listed.split(b"\0")
    files = []
    # Records are "<scope>", "<origin>", "<key>\n<value>"; an include keeps its file's scope.
    for scope, origin in zip(fields[0::3], fields[1::3], strict=False):
        if scope in (b"local", b"worktree") and origin.startswith(b"file:"):
            files.append(os.path.join(git.cwd or "", os.fsdecode(origin[len(b"file:") :])))
    return files


def _config_entries(git: Git, pattern: str) -> list[tuple[str, bytes | None]]:
    """``(key, value)`` pairs from ``config -z --get-regexp``; ``None`` for a key with no value."""
    output = git.run("config", "-z", "--get-regexp", pattern, ok_exit_codes=(0, 1)).stdout
    entries = []
    for item in output.split(b"\0"):
        if item:
            key, has_value, value = item.partition(b"\n")
            entries.append((key.decode("utf-8", "replace"), value if has_value else None))
    return entries


def _refuse_repository_config(git: Git) -> None:
    lazy_fetch_off = git.version is not None and git.version >= NO_LAZY_FETCH_VERSION
    for key, value in _config_entries(git, _REFUSED_REPO_CONFIG):
        shown = printable(key)
        if key == "core.sparsecheckout":
            if _config_true(value):
                raise _refused("the repository uses a sparse checkout, which Coral cannot commit")
        elif key == "attr.tree":
            raise _refused(
                "the repository config sets attr.tree; Coral checks worktree attributes"
            )
        elif key == "extensions.partialclone" or key.endswith(".promisor"):
            if not lazy_fetch_off and (key == "extensions.partialclone" or _config_true(value)):
                raise _refused(
                    "the repository is a partial clone; Coral needs git 2.44 or newer so that "
                    "reads never fetch missing objects"
                )
        elif key.startswith("hook."):
            raise _refused(f"the repository config sets {shown}; Coral runs no repository hooks")
        else:
            raise _refused(
                f"the repository config sets {shown}; repositories that declare filters or "
                "merge drivers are not supported"
            )


def _config_true(value: bytes | None) -> bool:
    """Git's boolean reading; a value git would reject counts as true (refused)."""
    if value is None:
        return True
    text = value.decode("utf-8", "replace").strip().lower()
    if text in ("false", "no", "off", ""):
        return False
    if text in ("true", "yes", "on"):
        return True
    try:
        return int(text) != 0
    except ValueError:
        return True


def _full_config_settings(
    git: Git,
) -> tuple[tuple[str, str], tuple[str, ...], str | None, tuple[str, ...]]:
    """
    Read the identity and the passed settings from the user's full config.

    :returns: ``(identity, -c args, the attributes file git reads, if any, and
        the user's files ops read: the global attributes and excludes files)``.
    """
    values: dict[str, str] = {}
    for key, value in _config_entries(git, _FULL_CONFIG_SETTINGS):
        values[key] = "true" if value is None else os.fsdecode(value)
    identity = (
        values.get("user.name") or FALLBACK_IDENTITY_NAME,
        values.get("user.email") or FALLBACK_IDENTITY_EMAIL,
    )
    config_args: list[str] = []
    for key, spelled in _PASSED_SETTINGS:
        if key in values:
            config_args += ["-c", f"{spelled}={values[key]}"]
    attributes_file = _attributes_file(git, configured="core.attributesfile" in values)
    # Exactly the global ignore and attribute files git consults; not the XDG dir,
    # which can hold the credential store.
    if "core.excludesfile" in values:
        excludes_file = _configured_path(git, "core.excludesfile")
    else:
        xdg_git_dir = _xdg_git_dir()
        excludes_file = os.path.join(xdg_git_dir, "ignore") if xdg_git_dir else None
    user_files = [attributes_file, excludes_file]
    return (
        identity,
        tuple(config_args),
        attributes_file,
        tuple(path for path in user_files if path),
    )


def _attributes_file(git: Git, *, configured: bool) -> str | None:
    """The global attributes file git reads: the configured one, else the XDG default."""
    if configured:
        return _configured_path(git, "core.attributesfile")
    xdg_git_dir = _xdg_git_dir()
    return os.path.join(xdg_git_dir, "attributes") if xdg_git_dir else None


def _configured_path(git: Git, key: str) -> str | None:
    """A path setting as git expands it (``~``), relative ones against the worktree."""
    expanded = git.run("config", "--type=path", "--get", key).stdout
    path = os.fsdecode(expanded.rstrip(b"\n"))
    return os.path.join(git.cwd or "", path) if path else None


def _xdg_git_dir() -> str | None:
    """Where git looks for the user's default ignore and attributes files."""
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return os.path.join(xdg_config_home, "git")
    home = os.environ.get("HOME")
    return os.path.join(home, ".config", "git") if home else None


def _refuse_declared_filters(
    git: Git, root: str, common_dir: str, attributes_file: str | None
) -> None:
    """Refuse when an attribute source the op reads names ``filter=<driver>``."""
    listing_deadline = time.monotonic() + ATTRIBUTES_LISTING_LIMIT_S
    try:
        listed = (
            replace(git, deadline=min(git.deadline, listing_deadline))
            .run(
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
                "--",
                _ATTRIBUTES_PATHSPEC,
            )
            .stdout
        )
    except WorkspaceOpHandlerError as exc:
        if exc.code != TIMEOUT:
            raise
        raise WorkspaceOpHandlerError(
            TIMEOUT,
            f"listing the worktree's attributes files took over {ATTRIBUTES_LISTING_LIMIT_S:g} s "
            "or the op's deadline; git blocks on a FIFO named .gitignore or .git/HEAD",
        ) from None
    for relpath in sorted({path for path in listed.split(b"\0") if path}):
        check_deadline(git.deadline, "the attributes check")
        text = _tree_attributes(git, root, relpath)
        if text is not None and _names_a_filter(text):
            raise _refused(
                f"{printable(relpath)} declares a filter; repositories with filters are not "
                "supported"
            )
    for source in (os.path.join(common_dir, "info", "attributes"), attributes_file):
        if source is None:
            continue
        # Git follows symlinks for these two, unlike an in-tree .gitattributes.
        try:
            text = read_small_file(
                source,
                max_bytes=MAX_ATTRIBUTES_FILE_BYTES,
                follow_symlinks=True,
                deadline=git.deadline,
            )
        except UnreadableFile as exc:
            raise _unchecked(printable(source), exc.reason) from None
        except OSError:
            raise _unchecked(printable(source), "unreadable") from None
        if text is not None and _names_a_filter(text):
            raise _refused(
                f"{printable(source)} declares a filter; repositories with filters are not "
                "supported"
            )


def _tree_attributes(git: Git, root: str, relpath: bytes) -> bytes | None:
    """The attributes git reads for a listed in-tree ``.gitattributes``; ``None`` for none."""
    shown = printable(relpath)
    try:
        info = lstat_in_root(root, relpath, deadline=git.deadline)
    except (UnreadableFile, OSError):
        raise _unchecked(shown, "unreadable") from None
    if info is None or stat.S_ISLNK(info.st_mode):
        # Git does not follow an in-tree symlink; then, as for a missing file, it reads the index.
        return _index_attributes(git, relpath)
    # A FIFO or other non-regular file is refused here; it would block git's own read.
    try:
        return read_in_root(
            root, relpath, max_bytes=MAX_ATTRIBUTES_FILE_BYTES, deadline=git.deadline
        )
    except UnreadableFile as exc:
        raise _unchecked(shown, exc.reason) from None
    except OSError:
        raise _unchecked(shown, "unreadable") from None


def _index_attributes(git: Git, relpath: bytes) -> bytes | None:
    """The stage-0 index copy of ``relpath``; ``None`` when the index has none."""
    entry = b":0:" + relpath
    size = git.run("cat-file", "-s", entry, check=False)
    if size.exit_code != 0:
        if b"in the index" in size.stderr:
            return None  # e.g. "does not exist (neither on disk nor in the index)"
        raise _unchecked(printable(relpath), "unreadable")  # e.g. a partial clone lacks it
    if int(size.stdout) > MAX_ATTRIBUTES_FILE_BYTES:
        raise _unchecked(printable(relpath), "too_large")
    return git.run("cat-file", "blob", entry, stdout_cap=MAX_ATTRIBUTES_FILE_BYTES).stdout


def _unchecked(shown: str, reason: str) -> WorkspaceOpHandlerError:
    detail = {
        "too_large": f"is larger than {MAX_ATTRIBUTES_FILE_BYTES} bytes",
        "not_regular": "is not a regular file",
    }.get(reason, "cannot be read")
    return _refused(f"attributes file {shown} {detail}, so Coral cannot check it for filters")


def _names_a_filter(text: bytes) -> bool:
    """Whether any attribute line (``[attr]`` macros included) sets ``filter=<driver>``."""
    for line in text.split(b"\n"):
        tokens = [token for token in _ATTRIBUTE_BLANKS.split(line) if token]
        if tokens and not tokens[0].startswith(b"#"):
            if any(token.startswith(b"filter=") for token in tokens[1:]):
                return True
    return False
