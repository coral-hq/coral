"""In-memory K13 backend for tests and engine fakes (app tier: no Omnigent imports).

``FakeWorkspaceOps`` keeps one worktree per ``(host_id, root)`` and follows the
contract's observable behaviour, including its git-side idempotency records: a
retried commit trusts HEAD only when HEAD carries the op's ``Coral-Op`` trailer
and its parent is the expected HEAD, then compares ``Coral-Op-Params``; a
retried salvage trusts its ref only when the ref's commit sits on HEAD. It is
deliberately simple:

- commits snapshot whole files and have one parent; a commit id is the sha1 of
  the parent, the sorted files and the message, so ids are deterministic;
- refs are kept per worktree, where git shares them across a repository;
- it has no index, config or identity, so it cannot model the driver refusal,
  the isolated git environment or the index refresh on a commit retry;
- merge supports ``already_applied``, a fast-forward onto a ref ahead of HEAD
  and a scripted conflict, and raises ``NotImplementedError`` where git would
  need a three-way merge;
- digests are not git's: L1 hashes HEAD and the dirty paths' content, L2 hashes
  the tree ``commit`` would record.

The methods that are not ``WorkspaceOps`` methods are test-only setup.
"""

from __future__ import annotations

import difflib
import hashlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import override

from coral.workspace.ops import (
    HOOKS_TRAILER_KEY,
    HOOKS_TRAILER_VALUE,
    MAX_READ_BYTES,
    OP_PARAMS_TRAILER_KEY,
    OP_TRAILER_KEY,
    RUNTIME_DIR,
    CheckResult,
    CommitResult,
    DiffStat,
    Fingerprint,
    FingerprintLevel,
    HeadResult,
    HostChannel,
    MergeResult,
    OpExecutor,
    ReadResult,
    ResetResult,
    SalvageResult,
    WorkspaceOpError,
    WorkspaceOps,
    WorkspaceRef,
    check_op_host,
    commit_params_digest,
    salvage_ref_name,
    validate_commit_id,
    validate_commit_message,
    validate_coral_ref,
    validate_op_key,
    validate_timeout,
    validate_trailers,
)

_SALVAGE_MESSAGE = "Coral salvage"


@dataclass(frozen=True)
class _Commit:
    parent: str | None
    files: Mapping[str, bytes]
    message: str
    trailers: tuple[tuple[str, str], ...]


@dataclass
class _Worktree:
    branch: str
    head: str
    files: dict[str, bytes]
    ignored: set[str] = field(default_factory=set)
    refs: dict[str, str] = field(default_factory=dict)
    merge_conflicts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    checks: dict[tuple[str, ...], CheckResult] = field(default_factory=dict)


class FakeWorkspaceOps(WorkspaceOps):
    """Deterministic in-memory ``WorkspaceOps``; see the module docstring for its limits."""

    def __init__(self) -> None:
        self._commits: dict[str, _Commit] = {}
        self._worktrees: dict[tuple[str, str], _Worktree] = {}

    # ── Test-only setup ─────────────────────────────────────────────────────

    def add_workspace(self, ref: WorkspaceRef, files: Mapping[str, bytes]) -> str:
        """Create the worktree at ``ref`` with ``files`` committed; return that commit."""
        commit = self._store(None, dict(files), "initial", ())
        self._worktrees[(ref.host_id, ref.root)] = _Worktree(
            branch=ref.branch, head=commit, files=dict(files)
        )
        return commit

    def write_file(self, ref: WorkspaceRef, path: str, content: bytes) -> None:
        self._worktree(ref).files[_checked_path(path)] = content

    def delete_file(self, ref: WorkspaceRef, path: str) -> None:
        del self._worktree(ref).files[path]

    def ignore(self, ref: WorkspaceRef, path: str) -> None:
        """Ignore ``path`` as an ``info/exclude`` line would: only while it is untracked."""
        self._worktree(ref).ignored.add(_checked_path(path))

    def add_ref(self, ref: WorkspaceRef, name: str, files: Mapping[str, bytes]) -> str:
        """Point the full ref ``name`` at a new commit on HEAD with ``files`` written."""
        validate_coral_ref(name)
        worktree = self._worktree(ref)
        tree = {**self._commits[worktree.head].files, **files}
        commit = self._store(worktree.head, tree, f"update {name}", ())
        worktree.refs[name] = commit
        return commit

    def script_check(self, ref: WorkspaceRef, argv: Sequence[str], result: CheckResult) -> None:
        """Make ``check`` with ``argv`` return ``result``."""
        self._worktree(ref).checks[tuple(argv)] = result

    def script_merge_conflict(
        self, ref: WorkspaceRef, source_ref: str, paths: Sequence[str]
    ) -> None:
        """Make every merge of ``source_ref`` conflict on ``paths``."""
        self._worktree(ref).merge_conflicts[source_ref] = tuple(sorted(paths))

    # ── READ ops ────────────────────────────────────────────────────────────

    @override
    async def fingerprint(
        self, ref: WorkspaceRef, executor: OpExecutor, *, level: FingerprintLevel
    ) -> Fingerprint:
        check_op_host("fingerprint", executor, level=level)
        worktree = self._target(ref, executor) if level == "L2" else self._worktree(ref, executor)
        dirty = self._dirty(worktree)
        if level == "L1":
            digest = hashlib.sha256(worktree.head.encode())
            for path in sorted(dirty):
                content = dirty[path]
                state = "deleted" if content is None else hashlib.sha256(content).hexdigest()
                digest.update(f"\0{path}\0{state}".encode())
            value = digest.hexdigest()
        else:
            value = _tree_id(self._recordable(worktree))
        return Fingerprint(level=level, digest=value, head=worktree.head, dirty_count=len(dirty))

    @override
    async def head(self, ref: WorkspaceRef, executor: OpExecutor) -> HeadResult:
        check_op_host("head", executor)
        worktree = self._worktree(ref, executor)
        return HeadResult(head=worktree.head, branch=worktree.branch, merge_in_progress=False)

    @override
    async def diff_stat(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        from_commit: str,
        to_commit: str | None = None,
    ) -> DiffStat:
        check_op_host("diff_stat", executor)
        validate_commit_id(from_commit)
        if to_commit is not None:
            validate_commit_id(to_commit)
        worktree = self._worktree(ref, executor)
        before = self._commit(from_commit).files
        after = self._commit(worktree.head if to_commit is None else to_commit).files
        paths = tuple(
            sorted(
                path
                for path in set(before) | set(after)
                if not _in_runtime_dir(path) and before.get(path) != after.get(path)
            )
        )
        insertions = deletions = 0
        for path in paths:
            added, removed = _line_counts(before.get(path, b""), after.get(path, b""))
            insertions += added
            deletions += removed
        return DiffStat(
            files_changed=len(paths), insertions=insertions, deletions=deletions, paths=paths
        )

    @override
    async def read(
        self, ref: WorkspaceRef, executor: OpExecutor, *, path: str, at_commit: str | None = None
    ) -> ReadResult:
        check_op_host("read", executor)
        path = _checked_path(path)
        if at_commit is not None:
            validate_commit_id(at_commit)
        worktree = self._worktree(ref, executor)
        files = worktree.files if at_commit is None else self._commit(at_commit).files
        content = files.get(path)
        where = "the working tree" if at_commit is None else at_commit
        if content is None:
            raise WorkspaceOpError("workspace.git_failed", f"{path} does not exist in {where}")
        if len(content) > MAX_READ_BYTES:
            raise WorkspaceOpError("workspace.git_failed", f"{path} in {where} is too large")
        return ReadResult(path=path, content=content, sha256=hashlib.sha256(content).hexdigest())

    # ── WRITE ops ───────────────────────────────────────────────────────────

    @override
    async def commit(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        expected_head: str,
        message: str,
        trailers: Mapping[str, str] | None = None,
    ) -> CommitResult:
        check_op_host("commit", executor)
        validate_op_key(op_key)
        validate_commit_id(expected_head)
        validate_commit_message(message)
        caller_trailers = dict(trailers or {})
        validate_trailers(caller_trailers)
        worktree = self._target(ref, executor)
        params = commit_params_digest(message, caller_trailers)
        head = self._commits[worktree.head]
        recorded = dict(head.trailers)
        # A record counts only on the pre-op HEAD; only then are its params compared.
        if recorded.get(OP_TRAILER_KEY) == op_key and head.parent == expected_head:
            if recorded.get(OP_PARAMS_TRAILER_KEY) != params:
                raise WorkspaceOpError(
                    "workspace.op_key_conflict",
                    f"op key {op_key} already committed {worktree.head} with other params",
                )
            return CommitResult(commit=worktree.head, empty=False)
        if worktree.head != expected_head:
            raise WorkspaceOpError(
                "workspace.target_mismatch", f"HEAD is {worktree.head}, not {expected_head}"
            )
        tree = self._recordable(worktree)
        if tree == head.files:
            return CommitResult(commit=worktree.head, empty=True)
        all_trailers = (
            *caller_trailers.items(),
            (OP_TRAILER_KEY, op_key),
            (OP_PARAMS_TRAILER_KEY, params),
            (HOOKS_TRAILER_KEY, HOOKS_TRAILER_VALUE),
        )
        worktree.head = self._store(worktree.head, tree, message, all_trailers)
        return CommitResult(commit=worktree.head, empty=False)

    @override
    async def salvage(
        self, ref: WorkspaceRef, executor: OpExecutor, *, op_key: str
    ) -> SalvageResult:
        check_op_host("salvage", executor)
        ref_name = salvage_ref_name(op_key)
        worktree = self._target(ref, executor)
        if ref_name in worktree.refs:
            recorded = worktree.refs[ref_name]
            if self._commits[recorded].parent != worktree.head:
                raise WorkspaceOpError(
                    "workspace.op_key_conflict", f"{ref_name} exists but is not on HEAD"
                )
            return SalvageResult(ref=ref_name, commit=recorded)
        tree = self._recordable(worktree)
        if tree == self._commits[worktree.head].files:
            return SalvageResult(ref=ref_name, commit=None)
        hooks_trailer = ((HOOKS_TRAILER_KEY, HOOKS_TRAILER_VALUE),)
        commit = self._store(worktree.head, tree, _SALVAGE_MESSAGE, hooks_trailer)
        worktree.refs[ref_name] = commit
        return SalvageResult(ref=ref_name, commit=commit)

    @override
    async def reset(
        self, ref: WorkspaceRef, executor: OpExecutor, *, op_key: str, commit: str
    ) -> ResetResult:
        check_op_host("reset", executor)
        validate_op_key(op_key)
        validate_commit_id(commit)
        worktree = self._target(ref, executor)
        self._commit(commit)
        self._checkout(worktree, commit)
        return ResetResult(head=commit)

    @override
    async def merge(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        source_ref: str,
        message: str,
    ) -> MergeResult:
        check_op_host("merge", executor)
        validate_op_key(op_key)
        validate_coral_ref(source_ref)
        validate_commit_message(message)
        worktree = self._target(ref, executor)
        source = worktree.refs.get(source_ref)
        if source is None:
            raise WorkspaceOpError("workspace.git_failed", f"unknown ref {source_ref}")
        if self._is_ancestor(source, worktree.head):
            return MergeResult(status="already_applied", merge_commit=None, conflicts=())
        if self._dirty(worktree):
            raise WorkspaceOpError(
                "workspace.git_failed", "the working tree has changes; commit or reset first"
            )
        if source_ref in worktree.merge_conflicts:
            conflicts = worktree.merge_conflicts[source_ref]
            return MergeResult(status="conflict", merge_commit=None, conflicts=conflicts)
        if not self._is_ancestor(worktree.head, source):
            raise NotImplementedError(
                f"the fake merges only by fast-forward; {source_ref} diverged"
            )
        self._checkout(worktree, source)
        return MergeResult(status="clean", merge_commit=source, conflicts=())

    @override
    async def check(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        argv: Sequence[str],
        timeout_s: float,
    ) -> CheckResult:
        check_op_host("check", executor)
        validate_op_key(op_key)
        validate_timeout(timeout_s)
        worktree = self._target(ref, executor)
        try:
            return worktree.checks[tuple(argv)]
        except KeyError:
            raise LookupError(f"no scripted check result for {list(argv)!r}") from None

    # ── Internals ───────────────────────────────────────────────────────────

    def _worktree(self, ref: WorkspaceRef, executor: OpExecutor | None = None) -> _Worktree:
        """The worktree at ``ref``; a host channel must be the ref's own host."""
        if isinstance(executor, HostChannel) and executor.host_id != ref.host_id:
            raise WorkspaceOpError(
                "workspace.target_mismatch", f"{ref.root} is not on host {executor.host_id}"
            )
        worktree = self._worktrees.get((ref.host_id, ref.root))
        if worktree is None:
            raise WorkspaceOpError("workspace.target_mismatch", f"no worktree at {ref.root}")
        return worktree

    def _target(self, ref: WorkspaceRef, executor: OpExecutor) -> _Worktree:
        """The worktree a WRITE op may change: known, and on its ``coral/`` ``ref.branch``."""
        worktree = self._worktree(ref, executor)
        try:
            validate_coral_ref(f"refs/heads/{ref.branch}")
        except ValueError:
            raise WorkspaceOpError(
                "workspace.target_mismatch", f"{ref.branch} is not a coral/ branch"
            ) from None
        if worktree.branch != ref.branch:
            raise WorkspaceOpError(
                "workspace.target_mismatch",
                f"{ref.root} is on {worktree.branch}, not {ref.branch}",
            )
        return worktree

    def _commit(self, commit: str) -> _Commit:
        found = self._commits.get(commit)
        if found is None:
            raise WorkspaceOpError("workspace.git_failed", f"unknown commit {commit}")
        return found

    def _store(
        self,
        parent: str | None,
        files: Mapping[str, bytes],
        message: str,
        trailers: tuple[tuple[str, str], ...],
    ) -> str:
        trailer_block = "\n".join(f"{key}: {value}" for key, value in trailers)
        full_message = f"{message}\n\n{trailer_block}" if trailers else message
        commit = hashlib.sha1(
            f"{parent or ''}\0{_tree_id(files)}\0{full_message}".encode()
        ).hexdigest()
        self._commits[commit] = _Commit(parent, dict(files), message, trailers)
        return commit

    def _ancestry(self, commit: str | None) -> Iterator[str]:
        while commit is not None:
            yield commit
            commit = self._commits[commit].parent

    def _is_ancestor(self, ancestor: str, commit: str) -> bool:
        return ancestor in self._ancestry(commit)

    def _recordable(self, worktree: _Worktree) -> dict[str, bytes]:
        """The tree ``git add -A -- WORKSPACE_PATHSPEC`` would stage."""
        tracked = self._commits[worktree.head].files
        tree = {path: content for path, content in tracked.items() if _in_runtime_dir(path)}
        tree.update(
            (path, content)
            for path, content in worktree.files.items()
            if not _in_runtime_dir(path) and not _is_ignored(worktree, path, tracked)
        )
        return tree

    def _dirty(self, worktree: _Worktree) -> dict[str, bytes | None]:
        """Paths ``git status`` would report, with their content (``None`` when deleted)."""
        tracked = self._commits[worktree.head].files
        tree = self._recordable(worktree)
        return {
            path: tree.get(path)
            for path in set(tracked) | set(tree)
            if tree.get(path) != tracked.get(path)
        }

    def _checkout(self, worktree: _Worktree, commit: str) -> None:
        """``reset --hard``, then ``clean -fd`` with ``CLEAN_EXCLUDE``.

        Untracked files that are ignored or under ``RUNTIME_DIR`` stay.
        """
        old = self._commits[worktree.head].files
        target = self._commits[commit].files
        kept = {
            path: content
            for path, content in worktree.files.items()
            if path not in target
            and path not in old
            and (_in_runtime_dir(path) or _is_ignored(worktree, path, target))
        }
        worktree.head = commit
        worktree.files = {**target, **kept}


def _is_ignored(worktree: _Worktree, path: str, tracked: Mapping[str, bytes]) -> bool:
    return path in worktree.ignored and path not in tracked


def _in_runtime_dir(path: str) -> bool:
    return path.startswith(f"{RUNTIME_DIR}/")


def _checked_path(path: str) -> str:
    parts = path.split("/")
    if path.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"path must be relative to the worktree root: {path!r}")
    return path


def _tree_id(files: Mapping[str, bytes]) -> str:
    digest = hashlib.sha1()
    for path in sorted(files):
        digest.update(f"{path}\0{hashlib.sha1(files[path]).hexdigest()}\0".encode())
    return digest.hexdigest()


def _lines(data: bytes) -> list[bytes]:
    """Split on ``\\n`` only, keeping each line's newline, as git's diff does."""
    parts = data.split(b"\n")
    return [part + b"\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _line_counts(before: bytes, after: bytes) -> tuple[int, int]:
    """Lines added and removed, as ``git diff --numstat`` counts them (binary counts 0)."""
    if b"\0" in before or b"\0" in after:
        return 0, 0
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, _lines(before), _lines(after), autojunk=False)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += old_end - old_start
        if tag in ("replace", "insert"):
            added += new_end - new_start
    return added, removed
