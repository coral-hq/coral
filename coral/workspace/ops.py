"""K13 ``WorkspaceOps`` (draft v1): the git operations Coral's engine runs on a worktree.

Pure tier: standard library only. The contract text, with the reason for each
rule, is ``docs/coral/contracts/workspace-ops.md``. Backends prove they follow
it with ``tests/coral/workspace/conformance/``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol, get_args

OpName = Literal[
    "fingerprint", "commit", "salvage", "reset", "head", "diff_stat", "check", "merge", "read"
]
OP_NAMES: tuple[OpName, ...] = get_args(OpName)
FingerprintLevel = Literal["L1", "L2"]

# fingerprint is in neither set: it is READ at L1 and WRITE at L2, because L2
# writes tree objects into the git common dir.
READ_OPS: frozenset[OpName] = frozenset({"head", "diff_stat", "read"})
WRITE_OPS: frozenset[OpName] = frozenset({"commit", "salvage", "reset", "merge", "check"})

# ── Git defaults every backend applies ──────────────────────────────────────

# Mandatory on every engine git call: no hookdir hooks, fsmonitor, signing or
# auto-gc, and trailers always parse with ``:`` so the op record stays readable.
GIT_HARDENING_CONFIG: tuple[str, ...] = (
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "commit.gpgSign=false",
    "-c",
    "gc.auto=0",
    "-c",
    "trailer.separators=:",
)
# Every ``git diff`` skips external diff drivers and textconv filters.
GIT_DIFF_FLAGS: tuple[str, ...] = ("--no-ext-diff", "--no-textconv")
# The ops run with global and system config disabled, and READ ops never take
# optional locks, so they never write ``.git``. Driver and identity checks read
# the full config separately (reading config runs no program).
GIT_ENV: Mapping[str, str] = MappingProxyType(
    {
        "LC_ALL": "C",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
)
# Coral's own files in a worktree. No op records, fingerprints, diffs or cleans them.
RUNTIME_DIR = ".coral/runtime"
# Pathspec for ``git add -A``, ``git status`` and ``git diff``.
WORKSPACE_PATHSPEC: tuple[str, ...] = (".", f":(exclude){RUNTIME_DIR}/**")
# ``git clean -fd`` keeps the runtime dir through an exclude pattern; a pathspec
# exclusion would still remove a wholly untracked ``.coral/``.
CLEAN_EXCLUDE: tuple[str, ...] = ("-e", f"/{RUNTIME_DIR}/")
# Author and committer when the user's full config sets no ``user.name``/``user.email``.
FALLBACK_IDENTITY_NAME = "Coral"
FALLBACK_IDENTITY_EMAIL = "coral@localhost"
# Trailers the backend appends after the caller's. Only ``commit`` writes the run
# and attempt ids (when given) and the op record pair; every engine commit
# carries the hooks trailer.
RUN_TRAILER_KEY = "Coral-Run"
ATTEMPT_TRAILER_KEY = "Coral-Attempt"
OP_TRAILER_KEY = "Coral-Op"
OP_PARAMS_TRAILER_KEY = "Coral-Op-Params"
HOOKS_TRAILER_KEY = "Coral-Hooks"
HOOKS_TRAILER_VALUE = "skipped"
SALVAGE_REF_PREFIX = "refs/coral/salvage/"
# The only refs K13 accepts or writes.
CORAL_REF_PREFIXES: tuple[str, ...] = ("refs/heads/coral/", "refs/coral/")
# ``read`` refuses larger files, as Omnigent's own git reads do.
MAX_READ_BYTES = 10 * 1024 * 1024
# The longest ``check``, matching the runner's longest tool execution.
MAX_CHECK_TIMEOUT_S = 7200.0

_OP_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}")
_TRAILER_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,63}")
_RESERVED_TRAILER_PREFIX = "coral-"
# A full lowercase hex object id, SHA-1 or SHA-256.
COMMIT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_REF_COMPONENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
_MAX_REF_LENGTH = 255
# C0 control characters (terminal escapes among them); a message body keeps tabs and newlines.
_CONTROL = re.compile(r"[\x00-\x1f]")
_MESSAGE_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f]")

# ── Errors ──────────────────────────────────────────────────────────────────

WorkspaceErrorCode = Literal[
    "workspace.op_host_violation",
    "workspace.backend_unavailable",
    "workspace.git_failed",
    "workspace.timeout",
    "workspace.op_key_conflict",
    "workspace.target_mismatch",
    "workspace.capability_unavailable",
    "workspace.worktree_displaced",
    # A reset under a salvage: the tree changed since it, or HEAD is not its parent.
    "workspace.tree_changed",
    "workspace.head_moved",
    # WSP-07: push without per-run consent, or a ref outside the coral prefixes.
    "workspace.push_not_permitted",
    "workspace.invalid_ref",
]
WORKSPACE_ERROR_CODES: frozenset[str] = frozenset(get_args(WorkspaceErrorCode))
TREE_CHANGED: WorkspaceErrorCode = "workspace.tree_changed"
HEAD_MOVED: WorkspaceErrorCode = "workspace.head_moved"
PUSH_NOT_PERMITTED: WorkspaceErrorCode = "workspace.push_not_permitted"
INVALID_REF: WorkspaceErrorCode = "workspace.invalid_ref"


class WorkspaceOpError(Exception):
    """
    A K13 op failed with one of the contract's error codes.

    :param permanent: A retry cannot succeed, e.g. a repository with hooks, git
        older than 2.32 or a host that cannot serve the op. ``False`` leaves the
        decision to the code: a host that is offline now may be back later.
    """

    def __init__(self, code: WorkspaceErrorCode, message: str, *, permanent: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code: WorkspaceErrorCode = code
        self.message = message
        self.permanent = permanent


# ── Refs and executors ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class WorkspaceRef:
    """
    The worktree an op acts on.

    :param host_id: Host that holds the worktree.
    :param root: Absolute worktree path on that host.
    :param branch: Branch the engine checked out there, e.g. ``"coral/r-0a1b2c3d4e5f/base"``.
    """

    host_id: str
    root: str
    branch: str


@dataclass(frozen=True)
class StepSession:
    """
    An op addressed through a step session. Built by the engine from slot state only.

    :param session_id: The step session.
    :param writable: The session is its slot's writer, not a reviewer.
    :param at_turn_end: The engine detected a turn end, or the session is a new
        generation not yet briefed. The tree may still change.
    :raises TypeError: when a flag is not a ``bool``.
    :raises ValueError: when ``session_id`` is empty.
    """

    session_id: str
    writable: bool
    at_turn_end: bool

    def __post_init__(self) -> None:
        if type(self.writable) is not bool or type(self.at_turn_end) is not bool:
            raise TypeError("StepSession.writable and .at_turn_end must be bool")
        if not self.session_id:
            raise ValueError("StepSession.session_id must not be empty")


@dataclass(frozen=True)
class HostChannel:
    """An op sent through the host's workspace-ops channel, with no session."""

    host_id: str


OpExecutor = StepSession | HostChannel

# ── Results ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Fingerprint:
    """
    :param level: ``"L1"`` or ``"L2"``.
    :param digest: L1: sha256 hex over HEAD, ``git status`` and each dirty path.
        L2: the git tree id of what ``commit`` would record now.
    :param head: HEAD commit when the digest was taken.
    :param dirty_count: Paths ``git status`` reports, outside ``RUNTIME_DIR``.
    """

    level: FingerprintLevel
    digest: str
    head: str
    dirty_count: int


@dataclass(frozen=True)
class CommitResult:
    """
    :param commit: The new commit, or HEAD when ``empty``.
    :param empty: Nothing was recorded because the tree matched HEAD.
    """

    commit: str
    empty: bool


@dataclass(frozen=True)
class SalvageResult:
    """
    :param ref: ``refs/coral/salvage/<op_key>``.
    :param commit: The commit at ``ref``; ``None`` when the tree was clean.
    """

    ref: str
    commit: str | None


@dataclass(frozen=True)
class ResetResult:
    head: str


@dataclass(frozen=True)
class HeadResult:
    """
    :param branch: Checked-out branch; ``None`` when HEAD is detached.
    :param merge_in_progress: A merge left unfinished in the worktree.
    """

    head: str
    branch: str | None
    merge_in_progress: bool


@dataclass(frozen=True)
class DiffStat:
    """
    :param files_changed: Changed paths in the whole diff, as are both line counts.
    :param paths: Changed paths, sorted. A rename counts as a delete and an add.
    :param paths_truncated: ``paths`` is a prefix of the sorted list, cut to a size bound.
    """

    files_changed: int
    insertions: int
    deletions: int
    paths: tuple[str, ...]
    paths_truncated: bool = False


def paths_within(paths: Sequence[str], max_json_bytes: int) -> list[str]:
    """The longest prefix of ``paths`` whose ``json.dumps`` list fits ``max_json_bytes``."""
    kept: list[str] = []
    # "[]" around the items and ", " between them.
    used = 2
    for path in paths:
        cost = len(json.dumps(path)) + (2 if kept else 0)
        if used + cost > max_json_bytes:
            break
        kept.append(path)
        used += cost
    return kept


@dataclass(frozen=True)
class CheckResult:
    """
    :param exit_code: The command's exit code; ``None`` when it timed out.
    :param timed_out: The command overran its ``timeout_s`` and was killed.
    :param stdout_tail: The last 64 KiB of stdout, decoded as UTF-8 with replacement.
    :param stderr_tail: The same for stderr.
    """

    exit_code: int | None
    timed_out: bool
    stdout_tail: str
    stderr_tail: str
    duration_ms: int


MergeStatus = Literal["clean", "conflict", "already_applied"]


@dataclass(frozen=True)
class MergeResult:
    """
    :param merge_commit: HEAD after a clean merge (a new merge commit, or the source
        commit on a fast-forward); ``None`` otherwise.
    :param conflicts: Conflicting paths, sorted; empty unless ``status == "conflict"``.
    """

    status: MergeStatus
    merge_commit: str | None
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class ReadResult:
    """
    :param content: The file's exact bytes.
    :param sha256: Hex sha256 of ``content``.
    """

    path: str
    content: bytes
    sha256: str


# ── Rules ───────────────────────────────────────────────────────────────────


def check_op_host(
    op: OpName, executor: OpExecutor, *, level: FingerprintLevel | None = None
) -> None:
    """
    Refuse ``op`` when ``executor`` may not run it. Every backend calls this first.

    READ ops run for any step session or the host channel. WRITE ops need the
    host channel, or a writable step session at a detected turn end. This is an
    interlock against racing an agent, not authorization: K4 checks ownership.

    :param level: Required for ``fingerprint`` and refused for every other op.
    :raises WorkspaceOpError: ``workspace.op_host_violation`` when refused.
    :raises ValueError: for an unknown op or a misused ``level``.
    :raises TypeError: when ``executor`` is neither a ``StepSession`` nor a ``HostChannel``.
    """
    if not isinstance(executor, (StepSession, HostChannel)):
        raise TypeError(f"executor must be a StepSession or HostChannel, got {executor!r}")
    if op not in OP_NAMES:
        raise ValueError(f"unknown workspace op {op!r}")
    if (op == "fingerprint") != (level is not None) or level not in (None, "L1", "L2"):
        raise ValueError(f"only fingerprint takes a level, 'L1' or 'L2'; got {op} {level!r}")
    if not (op in WRITE_OPS or level == "L2") or isinstance(executor, HostChannel):
        return
    if executor.writable and executor.at_turn_end:
        return
    states = []
    if not executor.writable:
        states.append("read-only")
    if not executor.at_turn_end:
        states.append("mid-turn")
    name = f"{op}({level})" if level else op
    raise WorkspaceOpError(
        "workspace.op_host_violation",
        f"{name} needs a writable step session at a turn end or the host channel; "
        f"step session {executor.session_id} is {' and '.join(states)}",
    )


def validate_op_key(op_key: str) -> None:
    """
    Check that ``op_key`` can name a ref on a case-folding filesystem and a trailer value.

    :raises ValueError: unless it is 1-128 lowercase ASCII letters, digits, ``_`` or
        ``-``, starting with a letter or digit.
    """
    if not isinstance(op_key, str) or not _OP_KEY.fullmatch(op_key):
        raise ValueError(f"invalid op key {op_key!r}: use 1-128 of a-z, 0-9, '_' or '-'")


def validate_trailers(trailers: Mapping[str, str]) -> None:
    """
    Check caller trailers before a commit.

    :raises ValueError: for a non-string key or value, a key git would not parse as
        a trailer, any ``Coral-*`` key (in any case; the backend writes those), or a
        value with a C0 control character: a line break or NUL could forge another
        trailer, and ESC starts a terminal escape in ``git log``.
    """
    for key, value in trailers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"trailer {key!r} must map a string to a string")
        if not _TRAILER_KEY.fullmatch(key):
            raise ValueError(f"invalid trailer key {key!r}")
        if key.lower().startswith(_RESERVED_TRAILER_PREFIX):
            raise ValueError(f"trailer {key!r} is reserved for the backend")
        if _CONTROL.search(value):
            raise ValueError(f"trailer {key!r} has a control character in its value")


def validate_record_id(value: str) -> None:
    """
    Check a run or attempt id for the ``Coral-Run`` and ``Coral-Attempt`` trailers.

    :raises ValueError: unless it has the op-key format: 1-128 lowercase ASCII
        letters, digits, ``_`` or ``-``, starting with a letter or digit.
    """
    if not isinstance(value, str) or not _OP_KEY.fullmatch(value):
        raise ValueError(f"invalid record id {value!r}: use 1-128 of a-z, 0-9, '_' or '-'")


def validate_commit_message(message: str) -> None:
    """
    Check a ``commit`` or ``merge`` message.

    :raises ValueError: for a non-string, a blank message (git would read the
        trailer block as its subject), or a C0 control character other than a
        tab or newline: NUL, which git refuses, and ESC, which starts a terminal
        escape in ``git log``, among them.
    """
    if not isinstance(message, str) or not message.strip() or _MESSAGE_CONTROL.search(message):
        raise ValueError(
            "a commit message must be a non-blank string without control characters "
            "other than tabs and newlines"
        )


def commit_params_digest(
    message: str,
    trailers: Mapping[str, str],
    *,
    run_id: str | None = None,
    attempt_id: str | None = None,
) -> str:
    """
    Return the ``Coral-Op-Params`` value: sha256 hex of the canonical commit params.

    A retried commit compares this digest, never the stored message, which git may
    normalize. The run and attempt ids join the params only when either is set,
    so a commit without them keeps its earlier digest.
    """
    params: dict[str, object] = {"message": message, "trailers": sorted(trailers.items())}
    if run_id is not None or attempt_id is not None:
        params["record"] = [run_id, attempt_id]
    canonical = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def commit_record_trailers(
    *,
    op_key: str,
    params_digest: str,
    run_id: str | None = None,
    attempt_id: str | None = None,
) -> tuple[tuple[str, str], ...]:
    """The trailers a backend writes after the caller's on a ``commit``, in order."""
    record: list[tuple[str, str]] = []
    if run_id is not None:
        record.append((RUN_TRAILER_KEY, run_id))
    if attempt_id is not None:
        record.append((ATTEMPT_TRAILER_KEY, attempt_id))
    return (
        *record,
        (OP_TRAILER_KEY, op_key),
        (OP_PARAMS_TRAILER_KEY, params_digest),
        (HOOKS_TRAILER_KEY, HOOKS_TRAILER_VALUE),
    )


def salvage_ref_name(op_key: str) -> str:
    """
    Return the salvage ref for ``op_key``, e.g. ``"refs/coral/salvage/k-1"``.

    :raises ValueError: for an invalid op key.
    """
    validate_op_key(op_key)
    return SALVAGE_REF_PREFIX + op_key


def validate_commit_id(commit: str) -> None:
    """
    Check that ``commit`` is a full lowercase hex object id (SHA-1 or SHA-256).

    :raises ValueError: for anything else, including ``HEAD``, short or uppercase ids.
    """
    if not isinstance(commit, str) or not COMMIT_ID.fullmatch(commit):
        raise ValueError(f"expected a full hex commit id, got {commit!r}")


def validate_coral_ref(ref: str) -> None:
    """
    Check that ``ref`` is a full ref name under ``refs/heads/coral/`` or ``refs/coral/``.

    Each component is ASCII letters, digits, ``_``, ``.`` or ``-``, does not start
    with ``.`` or ``-``, and ends in neither ``.`` nor ``.lock`` (in any case);
    ``..`` is refused and the whole name is at most 255 characters. Refs that differ
    only in case collide on a case-folding filesystem, so never tell refs apart by
    case.

    :raises ValueError: for a short name, another namespace or revision syntax.
    """
    if (
        not isinstance(ref, str)
        or not ref.startswith(CORAL_REF_PREFIXES)
        or ".." in ref
        or len(ref) > _MAX_REF_LENGTH
    ):
        raise ValueError(f"expected a full ref under refs/heads/coral/ or refs/coral/: {ref!r}")
    for component in ref.split("/")[2:]:
        if (
            not _REF_COMPONENT.fullmatch(component)
            or component.endswith(".")
            or component.lower().endswith(".lock")
        ):
            raise ValueError(f"invalid ref component {component!r} in {ref!r}")


def validate_workspace_path(path: str) -> None:
    """
    Check a ``read`` path: relative POSIX, with no empty, ``.`` or ``..`` segment.

    :raises ValueError: for anything else, including an absolute path, a trailing
        ``/`` or a non-string.
    """
    if not isinstance(path, str) or any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError(f"path must be relative to the worktree root: {path!r}")


def validate_timeout(timeout_s: float) -> None:
    """
    Check a ``check`` timeout: a number from 1 to ``MAX_CHECK_TIMEOUT_S`` seconds.

    :raises ValueError: for a bool or a value out of range, NaN and infinities included.
    """
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, int | float)
        or not 1 <= timeout_s <= MAX_CHECK_TIMEOUT_S
    ):
        raise ValueError(f"timeout_s must be 1-{MAX_CHECK_TIMEOUT_S:g} seconds, got {timeout_s!r}")


# ── Interfaces ──────────────────────────────────────────────────────────────


class WorkspaceOps(Protocol):
    """
    K13 draft v1: nine async ops on one worktree.

    WRITE ops take an ``op_key``, unique per repository across ops and runs; READ
    ops take none, and neither does ``fingerprint`` at L2, which writes only
    content-addressed objects. Commits and refs are full hex ids and full
    ``CORAL_REF_PREFIXES`` names. Every op calls ``check_op_host`` first, and
    every WRITE op then verifies its target (``workspace.target_mismatch``).
    """

    async def fingerprint(
        self, ref: WorkspaceRef, executor: OpExecutor, *, level: FingerprintLevel
    ) -> Fingerprint: ...

    async def head(self, ref: WorkspaceRef, executor: OpExecutor) -> HeadResult: ...

    # ``to_commit=None`` means HEAD.
    async def diff_stat(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        from_commit: str,
        to_commit: str | None = None,
    ) -> DiffStat: ...

    # ``at_commit=None`` reads the working tree; ``path`` is relative to ``ref.root``.
    async def read(
        self, ref: WorkspaceRef, executor: OpExecutor, *, path: str, at_commit: str | None = None
    ) -> ReadResult: ...

    # ``expected_head`` is HEAD as the op's K21 effect recorded it before the first try.
    # ``run_id``/``attempt_id`` become ``Coral-Run``/``Coral-Attempt`` and join the digest.
    async def commit(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        expected_head: str,
        message: str,
        trailers: Mapping[str, str] | None = None,
        run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> CommitResult: ...

    async def salvage(
        self, ref: WorkspaceRef, executor: OpExecutor, *, op_key: str
    ) -> SalvageResult: ...

    async def reset(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        commit: str,
        salvage_commit: str | None = None,
    ) -> ResetResult:
        """
        Restore ``commit`` and remove untracked files that are not ignored.

        With ``salvage_commit`` (a salvage ref's commit), HEAD must be ``commit`` and that
        salvage's parent (``workspace.head_moved``), and every path the tree records
        differently from HEAD must be as the salvage recorded it (``workspace.tree_changed``),
        checked under the op's own lock.
        """
        ...

    async def merge(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        source_ref: str,
        message: str,
    ) -> MergeResult: ...

    # ``op_key`` names the job (the host channel's exec job); a repeat runs again.
    async def check(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        argv: Sequence[str],
        timeout_s: float,
    ) -> CheckResult: ...


@dataclass(frozen=True)
class ShellOutcome:
    """
    One session-shell command's outcome.

    :param exit_code: ``None`` when the command timed out.
    """

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class SessionShellBackend(Protocol):
    """Runs one POSIX shell command in a step session's environment."""

    async def run(self, session_id: str, command: str, *, timeout_s: float) -> ShellOutcome: ...


class HostChannelBackend(Protocol):
    """Sends one op to a host's workspace-ops channel and returns its payload."""

    # ``op_key`` is ``None`` for ops that take none.
    async def request(
        self,
        host_id: str,
        op: OpName,
        *,
        root: str,
        params: Mapping[str, object],
        timeout_s: float,
        op_key: str | None,
    ) -> Mapping[str, object]: ...
