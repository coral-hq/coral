"""K13 WRITE ops on the host channel: ``commit``, ``salvage`` and ``reset``.

Each handler holds its worktree for the op (a busy worktree refuses at once),
re-validates its params and pins a WRITE target: a linked worktree that is its
own toplevel, with its ``coral/`` branch checked out, in a repository with no
hooks, declared filters or sparse checkout (``_target``).

``commit`` and ``salvage`` stage on a private copy of the index, so the real
index changes only through ``reset -q`` once the branch has moved. They record
the tree ``add -A`` would, except that an untracked nested repository is left
out (git would store it as a gitlink, or fail on one without a commit, and
later git calls could reach into it). ``add -A`` itself is never run: it
starts ``git status`` inside every populated submodule, whose config and
attributes the agent can write. Instead the paths the shared status lists are
restaged with ``update-index`` in two passes (see :func:`_recordable_tree`).
Messages are composed here and fed to ``commit-tree`` on stdin; records are
read back with ``cat-file``, which never runs a signature program. Writes that
take ``index.lock`` or a ref lock retry within the lock budget and never
remove a lock. Nothing recurses into submodules, and ``clean`` never takes
``-x``. Every git process runs in the op's write jail (``_jail``) and, on
macOS, in the worktree moved aside for the op (``_aside``).
"""

from __future__ import annotations

import contextlib
import functools
import os
import shutil
import stat
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace

from coral.omni.host.ops._files import UnreadableFile, lstat_in_root
from coral.omni.host.ops._git import (
    GIT_FAILED,
    MAX_STDOUT_BYTES,
    TARGET_MISMATCH,
    TIMEOUT,
    WORKSPACE_STATUS_ARGV,
    Git,
    OutputTooLarge,
    capped,
    head_commit,
    printable,
    resolve_commit,
    status_records,
    unfinished_operations,
)
from coral.omni.host.ops._locks import one_op_per_worktree
from coral.omni.host.ops._target import (
    PinnedTarget,
    commit_param,
    invalid_params,
    op_params,
    pinned,
    temp_dir_unavailable,
)
from coral.workspace.ops import (
    CLEAN_EXCLUDE,
    HOOKS_TRAILER_KEY,
    HOOKS_TRAILER_VALUE,
    OP_PARAMS_TRAILER_KEY,
    OP_TRAILER_KEY,
    commit_params_digest,
    commit_record_trailers,
    salvage_ref_name,
    validate_commit_message,
    validate_record_id,
    validate_trailers,
)
from omnigent.host.workspace_ops import (
    WorkspaceOpHandler,
    WorkspaceOpHandlerError,
    WorkspaceOpRequest,
)

OP_KEY_CONFLICT = "workspace.op_key_conflict"
_SALVAGE_SUBJECT = "Coral salvage"
# Status walks the tree, and git blocks there on a FIFO an agent planted (a
# submodule's .git/HEAD), so a write op's status gets less than its deadline.
STATUS_LIMIT_S = 30.0
# Most status output read; reset reads more than this as "not clean" and resets anyway.
STATUS_OUTPUT_BYTES = MAX_STDOUT_BYTES
# A larger file is refused instead of being copied into the user's repository.
MAX_STAGED_FILE_BYTES = 100 * 1024 * 1024

Sleep = Callable[[float], None]


def write_handlers(*, sleep: Sleep = time.sleep) -> dict[str, WorkspaceOpHandler]:
    """
    The WRITE handlers by op name.

    :param sleep: Waits between lock retries; tests inject one so contention is deterministic.
    """
    return {
        "commit": one_op_per_worktree(functools.partial(_commit, sleep=sleep)),
        "salvage": one_op_per_worktree(functools.partial(_salvage, sleep=sleep)),
        "reset": one_op_per_worktree(functools.partial(_reset, sleep=sleep)),
    }


def _commit(request: WorkspaceOpRequest, *, sleep: Sleep) -> Mapping[str, object]:
    """``{commit, empty}``: record the tree on ``expected_head``, or return the op's record."""
    params = op_params(
        request,
        required=("expected_head", "message"),
        optional=("trailers", "run_id", "attempt_id"),
    )
    op_key = _op_key(request)
    expected_head = str(commit_param(params, "expected_head", required=True))
    message = _message(params["message"])
    trailers = _caller_trailers(params.get("trailers"))
    run_id = _record_id(params, "run_id")
    attempt_id = _record_id(params, "attempt_id")
    digest = commit_params_digest(message, trailers, run_id=run_id, attempt_id=attempt_id)
    record_trailers = commit_record_trailers(
        op_key=op_key, params_digest=digest, run_id=run_id, attempt_id=attempt_id
    )
    body = _message_bytes(message, (*trailers.items(), *record_trailers))
    with pinned(request, params, write=True) as target:
        git = replace(target.git, sleep=sleep)
        head = head_commit(git)
        record = _read_commit(git, head)
        # A record counts only on the pre-op HEAD; only then are its params compared.
        if record.trailer(OP_TRAILER_KEY) == op_key and record.parents == (expected_head,):
            if record.trailer(OP_PARAMS_TRAILER_KEY) != digest:
                raise WorkspaceOpHandlerError(
                    OP_KEY_CONFLICT, f"op key {op_key} already committed {head} with other params"
                )
            # A first try that stopped after moving the branch left the index stale.
            _sync_index(git)
            return {"commit": head, "empty": False}
        if head != expected_head:
            raise WorkspaceOpHandlerError(TARGET_MISMATCH, f"HEAD is {head}, not {expected_head}")
        tree = _recordable_tree(target, git)
        if tree == _tree_of(git, head):
            return {"commit": head, "empty": True}
        commit = _commit_tree(target, git, tree, parent=head, message=body)
        _move_branch(git, f"refs/heads/{params['branch']}", commit, expected_head, op_key)
        _sync_index(git)
        return {"commit": commit, "empty": False}


def _salvage(request: WorkspaceOpRequest, *, sleep: Sleep) -> Mapping[str, object]:
    """``{ref, commit}``: record the tree on HEAD at ``refs/coral/salvage/<op_key>``."""
    params = op_params(request)
    op_key = _op_key(request)
    ref = salvage_ref_name(op_key)
    with pinned(request, params, write=True) as target:
        git = replace(target.git, sleep=sleep)
        head = head_commit(git)
        existing = _ref_commit(git, ref)
        if existing is not None:
            if existing.parents != (head,):
                raise WorkspaceOpHandlerError(OP_KEY_CONFLICT, f"{ref} exists but is not on HEAD")
            return {"ref": ref, "commit": existing.commit}
        tree = _recordable_tree(target, git)
        if tree == _tree_of(git, head):
            return {"ref": ref, "commit": None}
        body = _message_bytes(
            f"{_SALVAGE_SUBJECT} {op_key}", ((HOOKS_TRAILER_KEY, HOOKS_TRAILER_VALUE),)
        )
        commit = _commit_tree(target, git, tree, parent=head, message=body)
        # The all-zero old value creates the ref only while it is absent.
        git.run_locking("update-ref", ref, commit, "0" * len(head))
        return {"ref": ref, "commit": commit}


def _reset(request: WorkspaceOpRequest, *, sleep: Sleep) -> Mapping[str, object]:
    """``{head}``: restore ``commit`` and remove untracked files that are not ignored."""
    params = op_params(request, required=("commit",))
    _op_key(request)
    commit = str(commit_param(params, "commit", required=True))
    with pinned(request, params, write=True) as target:
        git = replace(target.git, sleep=sleep)
        resolved = resolve_commit(git, commit)
        if _already_at(git, target.root, resolved):
            return {"head": resolved}
        # "--" makes the id a revision even when a file of that name exists.
        git.run_locking("reset", "--hard", "-q", "--no-recurse-submodules", resolved, "--")
        # Never -x: ignored files stay, and the exclude keeps .coral/runtime/.
        git.run("clean", "-fdq", *CLEAN_EXCLUDE, "--", ".")
        return {"head": resolved}


def _move_branch(git: Git, ref: str, commit: str, expected_head: str, op_key: str) -> None:
    """Point ``ref`` at ``commit`` only while it is still at ``expected_head``."""
    try:
        git.run_locking("update-ref", "-m", f"coral commit {op_key}", ref, commit, expected_head)
    except WorkspaceOpHandlerError as exc:
        if exc.code != GIT_FAILED:
            raise
        moved = git.run("rev-parse", "--verify", "--quiet", ref, check=False)
        now = moved.stdout.decode().strip()
        if moved.exit_code == 0 and now != expected_head:
            raise WorkspaceOpHandlerError(
                TARGET_MISMATCH, f"{ref} moved to {now} while the commit was written"
            ) from None
        raise


def _already_at(git: Git, root: str, commit: str) -> bool:
    """HEAD is ``commit``, no merge or cherry-pick is pending and status lists nothing."""
    if head_commit(git) != commit or unfinished_operations(git, root):
        return False
    try:
        status = _status(git, stdout_cap=STATUS_OUTPUT_BYTES)
    except OutputTooLarge:
        return False  # too much to list is not clean: reset and clean it
    return not status


def _status(git: Git, *, stdout_cap: int = MAX_STDOUT_BYTES) -> bytes:
    """``WORKSPACE_STATUS_ARGV`` output, given at most ``STATUS_LIMIT_S``."""
    try:
        listed = capped(git, STATUS_LIMIT_S).run(*WORKSPACE_STATUS_ARGV, stdout_cap=stdout_cap)
    except WorkspaceOpHandlerError as exc:
        if exc.code != TIMEOUT:
            raise
        raise WorkspaceOpHandlerError(
            TIMEOUT,
            f"git status took over {STATUS_LIMIT_S:g} s or the op's deadline; git blocks on a "
            "FIFO named .gitignore or .git/HEAD, in the worktree or a submodule",
        ) from None
    return listed.stdout


# ── Params ──────────────────────────────────────────────────────────────────


def _op_key(request: WorkspaceOpRequest) -> str:
    """The request's op key; ``op_params`` has already checked its format."""
    if request.op_key is None:
        raise invalid_params(f"{request.op} needs an op_key")
    return request.op_key


def _message(value: object) -> str:
    if not isinstance(value, str):
        raise invalid_params("message must be a string")
    try:
        validate_commit_message(value)
    except ValueError as exc:
        raise invalid_params(str(exc)) from None
    _require_utf8(value)
    return value


def _caller_trailers(value: object) -> dict[str, str]:
    """``[[key, value], ...]`` as an ordered mapping, checked like the engine's."""
    if value is None:
        return {}
    if not isinstance(value, list | tuple):
        raise invalid_params("trailers must be a list of [key, value] pairs")
    trailers: dict[str, str] = {}
    for pair in value:
        if not isinstance(pair, list | tuple) or len(pair) != 2:
            raise invalid_params("trailers must be a list of [key, value] pairs")
        key, text = pair
        if not isinstance(key, str) or not isinstance(text, str):
            raise invalid_params("trailer keys and values must be strings")
        if key in trailers:
            raise invalid_params(f"trailer {key!r} is repeated")
        trailers[key] = text
    try:
        validate_trailers(trailers)
    except ValueError as exc:
        raise invalid_params(str(exc)) from None
    _require_utf8(*trailers, *trailers.values())
    return trailers


def _record_id(params: Mapping[str, object], name: str) -> str | None:
    value = params.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid_params(f"{name} must be a string")
    try:
        validate_record_id(value)
    except ValueError as exc:
        raise invalid_params(f"{name}: {exc}") from None
    return value


def _require_utf8(*values: str) -> None:
    """Refuse text JSON allows but a commit cannot hold, e.g. a lone surrogate."""
    for value in values:
        try:
            value.encode()
        except UnicodeEncodeError:
            raise invalid_params("the commit message and trailers must be valid UTF-8") from None


def _message_bytes(message: str, trailers: Sequence[tuple[str, str]]) -> bytes:
    """``message``, a blank line, then one trailer block: the commit message git stores."""
    block = "".join(f"{key}: {value}\n" for key, value in trailers)
    return f"{message.rstrip()}\n\n{block}".encode()


# ── Records ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _CommitRecord:
    """A commit's parents and the trailers in its message's last paragraph."""

    commit: str
    parents: tuple[str, ...]
    trailers: tuple[tuple[str, str], ...]

    def trailer(self, key: str) -> str | None:
        """The value of ``key`` when it appears exactly once; otherwise ``None``."""
        values = [value for name, value in self.trailers if name == key]
        return values[0] if len(values) == 1 else None


def _read_commit(git: Git, commit: str) -> _CommitRecord:
    """Parse ``cat-file commit``; unlike ``log``, it runs no signature program or mailmap."""
    raw = git.run("cat-file", "commit", commit).stdout
    header, _blank, message = raw.partition(b"\n\n")
    parents = tuple(
        line.removeprefix(b"parent ").decode("ascii", "replace")
        for line in header.split(b"\n")
        if line.startswith(b"parent ")
    )
    return _CommitRecord(commit=commit, parents=parents, trailers=_last_trailer_block(message))


def _last_trailer_block(message: bytes) -> tuple[tuple[str, str], ...]:
    """The ``Key: value`` lines of the last paragraph, when every line is one."""
    paragraph = message.rstrip(b"\n").rsplit(b"\n\n", 1)[-1]
    trailers = []
    for line in paragraph.split(b"\n"):
        key, separator, value = line.partition(b": ")
        if not separator or not key:
            return ()
        trailers.append((key.decode("utf-8", "replace"), value.decode("utf-8", "replace")))
    return tuple(trailers)


def _ref_commit(git: Git, ref: str) -> _CommitRecord | None:
    """The commit at the full ref name ``ref``; ``None`` when the ref does not exist."""
    listed = git.run("for-each-ref", "--format=%(refname)%00%(objectname)%00%(objecttype)", ref)
    for line in listed.stdout.split(b"\n"):
        name, _nul, rest = line.partition(b"\0")
        if name.decode("utf-8", "replace") != ref:
            continue
        oid, _nul, kind = rest.partition(b"\0")
        if kind != b"commit":
            raise WorkspaceOpHandlerError(OP_KEY_CONFLICT, f"{ref} exists but is not a commit")
        return _read_commit(git, oid.decode("ascii", "replace"))
    return None


# ── Staging and writing ─────────────────────────────────────────────────────


def _recordable_tree(target: PinnedTarget, git: Git) -> str:
    """
    The tree ``add -A -- WORKSPACE_PATHSPEC`` would record now, staged on a private index copy.

    Only paths the index still has, or that status lists as untracked, are
    restaged, so a file the user untracked and ignored stays out. Pass one
    force-removes those that are gone, or sit behind a symlink or a file (a
    directory replaced by either); pass two restages the rest from the working
    tree with ``--replace``, so a file may take a directory's place and the
    other way round. A submodule whose commit moved is re-read in-process.
    """
    gone: list[bytes] = []
    present: list[bytes] = []
    for path in _restage_paths(_status(git)):
        try:
            info = lstat_in_root(target.root, path, deadline=git.deadline)
        except UnreadableFile:
            info = None  # behind a symlink or a non-directory: git sees it as gone
        except OSError as exc:
            raise WorkspaceOpHandlerError(
                GIT_FAILED, f"cannot stat {printable(path)}: {exc.strerror}"
            ) from None
        if info is None:
            gone.append(path)
            continue
        if stat.S_ISREG(info.st_mode) and info.st_size > MAX_STAGED_FILE_BYTES:
            raise WorkspaceOpHandlerError(
                GIT_FAILED,
                f"{printable(path)} is {info.st_size} bytes; Coral records files of at most "
                f"{MAX_STAGED_FILE_BYTES} bytes",
                permanent=True,
            )
        present.append(path)
    with _private_index(target) as index_file:
        staging = replace(git, extra_env={**git.extra_env, "GIT_INDEX_FILE": index_file})
        passes = ((("--force-remove",), gone), (("--add", "--remove", "--replace"), present))
        for flags, paths in passes:
            if paths:
                stdin = b"".join(path + b"\0" for path in paths)
                staging.run("update-index", *flags, "-z", "--stdin", input=stdin)
        return staging.run("write-tree").stdout.decode().strip()


def _restage_paths(status: bytes) -> list[bytes]:
    """
    The paths ``add -A`` would restage: listed ones the index still has, and untracked ones.

    A path deleted from the index (a ``1`` record with ``D`` in ``X``) comes back
    only if it is also untracked and not ignored; a rename's original path, the
    same. An untracked nested repository (a ``?`` path ending in ``/``) is left out.
    """
    paths = set()
    for record in status_records(status):
        if record.kind == b"?":
            if not record.path.endswith(b"/"):
                paths.add(record.path)
        elif record.kind != b"1" or record.index_status != b"D":
            # An unmerged path stays in the index (as stages) even when one side deleted it.
            paths.add(record.path)
    return sorted(paths)


@contextmanager
def _private_index(target: PinnedTarget) -> Iterator[str]:
    """A copy of the worktree's index in the op's private temp dir, removed afterwards."""
    if target.temp_dir is None:
        raise WorkspaceOpHandlerError(GIT_FAILED, "the op has no private temp dir")
    copy = os.path.join(target.temp_dir, "index")
    try:
        try:
            _copy_index(os.path.join(target.git_dir, "index"), copy)
        except OSError as exc:
            raise temp_dir_unavailable(exc) from None
        yield copy
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(copy)


def _copy_index(source: str, destination: str) -> None:
    """
    Copy the index without following a symlink; a missing one leaves git to start empty.

    The copy keeps the index's mtime: git trusts an entry's stat data unless
    the entry is as new as the index file, so a newer copy would hide a
    same-size edit made in the second the index was written.
    """
    try:
        source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise WorkspaceOpHandlerError(
            GIT_FAILED, f"cannot read the worktree's index: {exc.strerror}"
        ) from None
    with open(source_fd, "rb") as reader:
        info = os.fstat(reader.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceOpHandlerError(GIT_FAILED, "the worktree's index is not a regular file")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        with open(os.open(destination, flags, 0o600), "wb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.utime(writer.fileno(), ns=(info.st_atime_ns, info.st_mtime_ns))


def _tree_of(git: Git, commit: str) -> str:
    result = git.run("rev-parse", "--verify", "--quiet", "--end-of-options", f"{commit}^{{tree}}")
    return result.stdout.decode().strip()


def _commit_tree(target: PinnedTarget, git: Git, tree: str, *, parent: str, message: bytes) -> str:
    """A new unsigned commit of ``tree`` on ``parent``, by the user's identity."""
    name, email = target.identity
    identity = {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }
    author = replace(git, extra_env={**git.extra_env, **identity})
    created = author.run("commit-tree", "--no-gpg-sign", "-p", parent, tree, input=message)
    return created.stdout.decode().strip()


def _sync_index(git: Git) -> None:
    """Make the real index match HEAD, leaving the working tree as it is."""
    git.run_locking("reset", "-q", "--no-recurse-submodules")
