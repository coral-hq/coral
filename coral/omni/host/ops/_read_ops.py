"""K13 READ ops on the host channel: ``head``, ``diff_stat``, ``read`` and ``fingerprint``.

``fingerprint`` serves L1 (status digest) and L2 (recordable tree id). L2 stages on a
private index copy via :func:`coral.omni.host.ops._write_ops._recordable_tree` and
does not change the real index.

Each handler holds its worktree for the op (``_locks``: a busy worktree
refuses at once), re-validates its params, pins its target (``_target``) and
runs argv-only git (``_git``). READ ops write nothing under ``.git``: ``GIT_ENV``
sets ``GIT_OPTIONAL_LOCKS=0``, so ``git status`` never refreshes the index, and
``GIT_NO_LAZY_FETCH`` keeps a partial clone from fetching. Status and diff
never look inside a submodule or nested repository (``WORKSPACE_STATUS_ARGV``,
``tree_diff_argv``).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import time
import unicodedata
from collections.abc import Iterator, Mapping

from coral.evidence.fingerprint import blob_id, l1_digest
from coral.omni.host.ops._files import (
    UnreadableFile,
    lstat_in_root,
    read_in_root,
    readlink_in_root,
)
from coral.omni.host.ops._git import (
    CAPABILITY_UNAVAILABLE,
    GIT_FAILED,
    WORKSPACE_STATUS_ARGV,
    Git,
    check_deadline,
    head_commit,
    printable,
    resolve_commit,
    status_paths,
    status_records,
    tree_diff_argv,
    unfinished_operations,
)
from coral.omni.host.ops._locks import one_op_per_worktree
from coral.omni.host.ops._target import commit_param, invalid_params, op_params, pinned
from coral.omni.host.ops._write_ops import _recordable_tree
from coral.workspace.ops import MAX_READ_BYTES, paths_within, validate_workspace_path
from omnigent.host.workspace_ops import WorkspaceOpHandlerError, WorkspaceOpRequest

# Base64 of this many bytes, plus the payload's other fields, stays under the
# host channel's 8 MiB result cap; larger files are refused permanently.
MAX_HOST_READ_BYTES = 6_000_000
# Half the channel's result cap: past it the sorted path list is cut, never the counts.
MAX_DIFF_STAT_PAYLOAD_BYTES = 4 * 1024 * 1024
# Tree modes of a regular file; symlinks (120000) and gitlinks (160000) are refused.
_REGULAR_FILE_MODES = (b"100644", b"100755")
# Code points HFS+ ignores in names, so ".g\u200cit" opens ".git" there (git's is_hfs_dotgit).
_HFS_IGNORED = frozenset(
    [*range(0x200C, 0x2010), *range(0x202A, 0x202F), *range(0x206A, 0x2070), 0xFEFF]
)


@one_op_per_worktree
def head(request: WorkspaceOpRequest) -> Mapping[str, object]:
    """``{head, branch, merge_in_progress}``; ``branch`` is ``None`` when HEAD is detached."""
    with pinned(request, op_params(request), write=False) as target:
        git = target.git
        commit = head_commit(git)
        symbolic = git.run("symbolic-ref", "-q", "HEAD", ok_exit_codes=(0, 1))
        branch = None
        if symbolic.exit_code == 0:
            branch = symbolic.stdout.rstrip(b"\n").decode("utf-8", "replace")
            branch = branch.removeprefix("refs/heads/")
        return {
            "head": commit,
            "branch": branch,
            "merge_in_progress": "MERGE_HEAD" in unfinished_operations(git, target.root),
        }


@one_op_per_worktree
def diff_stat(request: WorkspaceOpRequest) -> Mapping[str, object]:
    """
    ``{files_changed, insertions, deletions, paths, paths_truncated}`` between two commits.

    ``to_commit`` defaults to HEAD. The counts cover the whole diff; a path list
    too large for the channel keeps its longest sorted prefix that fits.
    """
    params = op_params(request, required=("from_commit",), optional=("to_commit",))
    from_commit = commit_param(params, "from_commit", required=True)
    to_commit = commit_param(params, "to_commit")
    with pinned(request, params, write=False) as target:
        git = target.git
        start = resolve_commit(git, str(from_commit))
        end = head_commit(git) if to_commit is None else resolve_commit(git, to_commit)
        output = git.run(*tree_diff_argv(start, end)).stdout
        insertions = deletions = 0
        paths = []
        for record in output.split(b"\0"):
            if not record:
                continue
            fields = record.split(b"\t", 2)
            if len(fields) != 3:
                raise WorkspaceOpHandlerError(GIT_FAILED, "git diff --numstat output is malformed")
            added, removed, path = fields
            # A binary file reports "-" and counts 0 lines.
            insertions += 0 if added == b"-" else int(added)
            deletions += 0 if removed == b"-" else int(removed)
            paths.append(path.decode("utf-8", "replace"))
        paths.sort()
        payload: dict[str, object] = {
            "files_changed": len(paths),
            "insertions": insertions,
            "deletions": deletions,
            "paths": paths,
            "paths_truncated": False,
        }
        if len(json.dumps(payload)) > MAX_DIFF_STAT_PAYLOAD_BYTES:
            # A failure here would come after a commit landed, so cut the list instead.
            rest = len(json.dumps({**payload, "paths": [], "paths_truncated": True})) - 2
            payload["paths"] = paths_within(paths, MAX_DIFF_STAT_PAYLOAD_BYTES - rest)
            payload["paths_truncated"] = True
        return payload


@one_op_per_worktree
def read(request: WorkspaceOpRequest) -> Mapping[str, object]:
    """``{path, content_b64, sha256}`` of a regular file in the working tree or at a commit."""
    params = op_params(request, required=("path",), optional=("at_commit",))
    path = params["path"]
    if not isinstance(path, str) or "\0" in path:
        raise invalid_params("path must be a string without NUL")
    try:
        validate_workspace_path(path)
    except ValueError:
        raise invalid_params(f"path {printable(path)} must be relative to the worktree") from None
    if any(_is_dot_git(segment) for segment in path.split("/")):
        raise invalid_params(f"path {printable(path)} is inside a .git directory")
    at_commit = commit_param(params, "at_commit")
    with pinned(request, params, write=False) as target:
        if at_commit is None:
            content = _read_working_tree(target.root, path, request.deadline)
        else:
            content = _read_blob(target.git, path, at_commit)
        return {
            "path": path,
            "content_b64": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest(),
        }


@one_op_per_worktree
def fingerprint(request: WorkspaceOpRequest) -> Mapping[str, object]:
    """
    L1: status digest. L2: the tree id ``commit`` would record (private index).

    L1 covers HEAD, the raw ``WORKSPACE_STATUS_ARGV`` output and per-dirty-path
    ``lstat`` plus blob id (never following a symlink). L2 reuses the write
    path's private-index ``write-tree`` so staged and unstaged edits match, and
    the real index is unchanged.
    """
    params = op_params(request, required=("level",))
    level = params["level"]
    if not isinstance(level, str):
        raise invalid_params("level must be a string")
    if level == "L1":
        return _fingerprint_l1(request, params)
    if level == "L2":
        return _fingerprint_l2(request, params)
    raise WorkspaceOpHandlerError(
        CAPABILITY_UNAVAILABLE,
        f"this host serves fingerprint levels L1 and L2, not {level[:16]!r}",
        permanent=True,
    )


def _fingerprint_l1(
    request: WorkspaceOpRequest, params: Mapping[str, object]
) -> Mapping[str, object]:
    with pinned(request, params, write=False) as target:
        git = target.git
        object_format = git.run("rev-parse", "--show-object-format").stdout.decode().strip()
        if object_format not in ("sha1", "sha256"):
            raise WorkspaceOpHandlerError(GIT_FAILED, f"unknown object format {object_format!r}")
        commit = head_commit(git)
        status = git.run(*WORKSPACE_STATUS_ARGV).stdout
        dirty_count, paths = status_paths(status)

        def entries() -> Iterator[tuple[bytes, bytes]]:
            for path in paths:
                check_deadline(request.deadline, "fingerprint")
                yield path, _l1_entry(target.root, path, object_format, request.deadline)

        return {
            "level": "L1",
            "digest": l1_digest(commit, status, entries()),
            "head": commit,
            "dirty_count": dirty_count,
        }


def _fingerprint_l2(
    request: WorkspaceOpRequest, params: Mapping[str, object]
) -> Mapping[str, object]:
    # WRITE pin: private index lives under the op temp dir; real index stays put.
    t0 = time.monotonic()
    with pinned(request, params, write=True) as target:
        git = target.git
        commit = head_commit(git)
        status = git.run(*WORKSPACE_STATUS_ARGV).stdout
        dirty_count, _paths = status_paths(status)
        untracked_count = sum(1 for record in status_records(status) if record.kind == b"?")
        digest = _recordable_tree(target, git)
        return {
            "level": "L2",
            "digest": digest,
            "head": commit,
            "dirty_count": dirty_count,
            "untracked_count": untracked_count,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }


def _is_dot_git(segment: str) -> bool:
    """Whether some file system (case-folding, HFS+, NTFS) would open ``segment`` as ``.git``."""
    name = "".join(char for char in segment if ord(char) not in _HFS_IGNORED)
    name = unicodedata.normalize("NFC", name).casefold().rstrip(". ")
    return name in (".git", "git~1")


def _read_working_tree(root: str, path: str, deadline: float) -> bytes:
    try:
        return read_in_root(root, path, max_bytes=MAX_HOST_READ_BYTES, deadline=deadline)
    except UnreadableFile as exc:
        raise _unreadable(path, "the working tree", exc.reason) from None
    except OSError as exc:
        raise WorkspaceOpHandlerError(
            GIT_FAILED, f"cannot read {printable(path)}: {exc.strerror}"
        ) from None


def _read_blob(git: Git, path: str, at_commit: str) -> bytes:
    """The blob at ``<at_commit>:<path>``, when the tree records a regular file there."""
    commit = resolve_commit(git, at_commit)
    where = f"commit {at_commit}"
    # ls-tree -l names the entry's mode, type, id and size; the path is matched literally.
    listed = git.run(
        "--literal-pathspecs", "ls-tree", "-z", "-l", "--full-tree", commit, "--", path
    ).stdout
    entries = [entry for entry in listed.split(b"\0") if entry]
    if len(entries) != 1:
        raise _unreadable(path, where, "missing")
    described, _tab, name = entries[0].partition(b"\t")
    fields = described.split()
    if name != os.fsencode(path) or len(fields) != 4:
        raise _unreadable(path, where, "missing")
    mode, _kind, oid, size = fields
    if mode not in _REGULAR_FILE_MODES:
        raise _unreadable(path, where, "not_regular")
    if not size.isdigit():
        # ls-tree prints no size for an object a partial clone lacks; it is never fetched.
        raise _unreadable(path, where, "object_missing")
    if int(size) > MAX_HOST_READ_BYTES:
        raise _unreadable(path, where, "too_large")
    return git.run("cat-file", "blob", oid, stdout_cap=MAX_HOST_READ_BYTES).stdout


def _unreadable(path: str, where: str, reason: str) -> WorkspaceOpHandlerError:
    shown = printable(path)
    if reason == "too_large":
        return WorkspaceOpHandlerError(
            GIT_FAILED,
            f"{shown} in {where} is larger than the host read limit of {MAX_HOST_READ_BYTES} "
            "bytes",
            permanent=True,
        )
    detail = {
        "missing": "does not exist",
        "not_regular": "is not a regular file",
        "object_missing": "is not in this clone (a partial clone never fetches)",
    }.get(reason, "passes through a symlink or a non-directory")
    return WorkspaceOpHandlerError(GIT_FAILED, f"{shown} in {where} {detail}")


def _l1_entry(root: str, path: bytes, object_format: str, deadline: float) -> bytes:
    """One dirty path's L1 entry, from ``lstat``; nothing behind a symlink is ever read."""
    # git status names an embedded repository as "dir/".
    name = path.removesuffix(b"/")
    try:
        info = lstat_in_root(root, name, deadline=deadline)
    except UnreadableFile:
        # A parent directory became a symlink or a file: git sees the path as gone.
        return b"behind-a-symlink-or-file"
    except OSError:
        # A parent directory the walk cannot open, e.g. one made execute-only.
        return b"unreadable"
    if info is None:
        return b"missing"
    mode = info.st_mode
    if stat.S_ISREG(mode):
        blob = _file_blob(root, name, info.st_size, object_format, deadline)
        return b"file %d %d %s" % (info.st_size, info.st_mtime_ns, blob)
    if stat.S_ISLNK(mode):
        try:
            blob = blob_id(object_format, readlink_in_root(root, name, deadline=deadline))
        except (UnreadableFile, OSError):
            blob = b"changing"
        return b"symlink %d %d %s" % (info.st_size, info.st_mtime_ns, blob)
    if stat.S_ISDIR(mode):
        return b"directory"
    if stat.S_ISFIFO(mode):
        return b"fifo"
    return b"other"


def _file_blob(root: str, name: bytes, size: int, object_format: str, deadline: float) -> bytes:
    """The blob id of a regular file up to ``MAX_READ_BYTES``; ``-`` for a larger one."""
    if size > MAX_READ_BYTES:
        return b"-"
    try:
        content = read_in_root(root, name, max_bytes=MAX_READ_BYTES, deadline=deadline)
        return blob_id(object_format, content)
    except UnreadableFile:
        # It changed type or grew past the cap after lstat: an edit is under way.
        return b"changing"
    except OSError:
        return b"unreadable"
