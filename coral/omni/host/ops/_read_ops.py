"""K13 READ ops on the host channel: ``head``, ``diff_stat``, ``read`` and L1 ``fingerprint``.

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
import unicodedata
from collections.abc import Mapping

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
    printable,
    tree_diff_argv,
)
from coral.omni.host.ops._locks import one_op_per_worktree
from coral.omni.host.ops._target import invalid_params, op_params, pin
from coral.workspace.ops import (
    MAX_READ_BYTES,
    validate_commit_id,
    validate_workspace_path,
)
from omnigent.host.workspace_ops import WorkspaceOpHandlerError, WorkspaceOpRequest

# Base64 of this many bytes, plus the payload's other fields, stays under the
# host channel's 8 MiB result cap; larger files are refused permanently.
MAX_HOST_READ_BYTES = 6_000_000
MAX_DIFF_STAT_PAYLOAD_BYTES = 4 * 1024 * 1024
# Tree modes of a regular file; symlinks (120000) and gitlinks (160000) are refused.
_REGULAR_FILE_MODES = (b"100644", b"100755")
# Code points HFS+ ignores in names, so ".g\u200cit" opens ".git" there (git's is_hfs_dotgit).
_HFS_IGNORED = frozenset(
    [*range(0x200C, 0x2010), *range(0x202A, 0x202F), *range(0x206A, 0x2070), 0xFEFF]
)
# Interim L1 byte layout, until EVD-01's shared l1_digest(): digests compare
# only within this backend.
_L1_LAYOUT = b"coral-host-l1-interim-1\0"


@one_op_per_worktree
def head(request: WorkspaceOpRequest) -> Mapping[str, object]:
    """``{head, branch, merge_in_progress}``; ``branch`` is ``None`` when HEAD is detached."""
    target = pin(request, op_params(request), write=False)
    git = target.git
    commit = _head_commit(git)
    symbolic = git.run("symbolic-ref", "-q", "HEAD", ok_exit_codes=(0, 1))
    branch = None
    if symbolic.exit_code == 0:
        branch = symbolic.stdout.rstrip(b"\n").decode("utf-8", "replace")
        branch = branch.removeprefix("refs/heads/")
    merge_head = os.fsdecode(git.run("rev-parse", "--git-path", "MERGE_HEAD").stdout.rstrip(b"\n"))
    return {
        "head": commit,
        "branch": branch,
        "merge_in_progress": os.path.lexists(os.path.join(target.root, merge_head)),
    }


@one_op_per_worktree
def diff_stat(request: WorkspaceOpRequest) -> Mapping[str, object]:
    """``{files_changed, insertions, deletions, paths}`` between two commits (default HEAD)."""
    params = op_params(request, required=("from_commit",), optional=("to_commit",))
    from_commit = _commit_param(params, "from_commit", required=True)
    to_commit = _commit_param(params, "to_commit")
    git = pin(request, params, write=False).git
    start = _resolve_commit(git, str(from_commit))
    end = _head_commit(git) if to_commit is None else _resolve_commit(git, to_commit)
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
    payload = {
        "files_changed": len(paths),
        "insertions": insertions,
        "deletions": deletions,
        "paths": sorted(paths),
    }
    if len(json.dumps(payload)) > MAX_DIFF_STAT_PAYLOAD_BYTES:
        raise WorkspaceOpHandlerError(
            GIT_FAILED, f"the diff names too many paths to report ({len(paths)})"
        )
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
    at_commit = _commit_param(params, "at_commit")
    target = pin(request, params, write=False)
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
    L1: ``{level, digest, head, dirty_count}``; any other level is not served here.

    The digest covers HEAD, the raw ``WORKSPACE_STATUS_ARGV`` output (no stash
    header, submodules by commit only) and, per dirty path, its ``lstat`` type,
    size and ``mtime_ns`` plus a blob id computed in Python (regular files up
    to ``MAX_READ_BYTES``, and symlink text). It never follows a symlink.
    """
    params = op_params(request, required=("level",))
    level = params["level"]
    if not isinstance(level, str):
        raise invalid_params("level must be a string")
    if level != "L1":
        raise WorkspaceOpHandlerError(
            CAPABILITY_UNAVAILABLE,
            f"this host serves fingerprint level L1 only, not {level[:16]!r}",
            permanent=True,
        )
    target = pin(request, params, write=False)
    git = target.git
    object_format = git.run("rev-parse", "--show-object-format").stdout.decode().strip()
    if object_format not in ("sha1", "sha256"):
        raise WorkspaceOpHandlerError(GIT_FAILED, f"unknown object format {object_format!r}")
    commit = _head_commit(git)
    status = git.run(*WORKSPACE_STATUS_ARGV).stdout
    dirty_count, paths = _dirty_paths(status)
    digest = hashlib.sha256(_L1_LAYOUT)
    digest.update(commit.encode() + b"\0")
    digest.update(_framed(status))
    for path in paths:
        check_deadline(request.deadline, "fingerprint")
        digest.update(_framed(path))
        digest.update(_framed(_l1_entry(target.root, path, object_format, request.deadline)))
    return {
        "level": "L1",
        "digest": digest.hexdigest(),
        "head": commit,
        "dirty_count": dirty_count,
    }


def _commit_param(
    params: Mapping[str, object], name: str, *, required: bool = False
) -> str | None:
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


def _head_commit(git: Git) -> str:
    result = git.run("rev-parse", "--verify", "--quiet", "HEAD^{commit}", check=False)
    if result.exit_code != 0:
        raise WorkspaceOpHandlerError(GIT_FAILED, "HEAD does not name a commit")
    return result.stdout.decode().strip()


def _resolve_commit(git: Git, commit: str) -> str:
    result = git.run(
        "rev-parse", "--verify", "--quiet", "--end-of-options", f"{commit}^{{commit}}", check=False
    )
    if result.exit_code != 0:
        raise WorkspaceOpHandlerError(GIT_FAILED, f"unknown commit {commit}")
    return result.stdout.decode().strip()


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
    commit = _resolve_commit(git, at_commit)
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


def _dirty_paths(status: bytes) -> tuple[int, list[bytes]]:
    """The number of ``git status`` records and the sorted paths they name (renames: both)."""
    fields = status.split(b"\0")
    if fields[-1] == b"":
        fields.pop()
    # Space-separated fields before the path in each porcelain v2 record kind.
    leading = {b"1": 8, b"2": 9, b"u": 10, b"?": 1}
    count = 0
    paths: set[bytes] = set()
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        kind = record[:1]
        parts = record.split(b" ", leading.get(kind, 0))
        if kind not in leading or len(parts) != leading[kind] + 1:
            raise WorkspaceOpHandlerError(GIT_FAILED, "git status output is malformed")
        paths.add(parts[-1])
        if kind == b"2":
            if index >= len(fields):
                raise WorkspaceOpHandlerError(GIT_FAILED, "git status output is malformed")
            paths.add(fields[index])  # the rename's original path
            index += 1
        count += 1
    return count, sorted(paths)


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
            blob = _blob_id(object_format, readlink_in_root(root, name, deadline=deadline))
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
        return _blob_id(object_format, content)
    except UnreadableFile:
        # It changed type or grew past the cap after lstat: an edit is under way.
        return b"changing"
    except OSError:
        return b"unreadable"


def _blob_id(object_format: str, content: bytes) -> bytes:
    """The id ``git hash-object --no-filters`` gives ``content`` in the repo's object format."""
    digest = hashlib.new(object_format, b"blob %d\0" % len(content))
    digest.update(content)
    return digest.hexdigest().encode()


def _framed(data: bytes) -> bytes:
    """``data`` behind its length, so adjacent fields cannot run together."""
    return b"%d:%s" % (len(data), data)
