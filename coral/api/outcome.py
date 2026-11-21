"""A finished run's outcome: its diff through the owner's host, and how to check it out.

The server never runs git. :class:`OutcomeDiffs` reads the run worktree's ``head`` and
``diff_stat`` through the owner's host channel; the caller asks only for a finished run
whose host no unfinished run of the workspace uses. Reads are admitted one per user and
four in all, shared by every caller of one run, bounded by a 5 s host deadline per op
and one 12 s deadline, and cached trimmed. :func:`checkout_commands` builds the shell
commands from the run's stored paths, or none when a path could be misread. Failures
log the run id and the exception's type and code, never its text, which can hold paths.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import shlex
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PureWindowsPath

from coral.alerts.types import CallerKey, caller_key
from coral.api.run_models import (
    OutcomeCheckout,
    OutcomeDiff,
    OutcomeUnavailable,
    RunOutcome,
    row_status,
)
from coral.limits import Slots
from coral.omni.protocols import HostAccessRefused, HostWorkspaceChannels, Viewer
from coral.queue.run_effects import EffectRefused
from coral.stores.protocols import CoralRun, RunState
from coral.workspace.executors import RunTarget, run_target, workspace_for
from coral.workspace.ops import DiffStat, HostChannel, WorkspaceOpError

_logger = logging.getLogger(__name__)

# The host's deadline for each READ op, and one deadline over the channel lookup and both ops.
OUTCOME_HOST_TIMEOUT_S = 5.0
OUTCOME_DEADLINE_S = 12.0
# Reads admitted at once in the process, and for one user.
MAX_OUTCOME_READS = 4
MAX_OUTCOME_READS_PER_USER = 1
# Trimmed diffs kept by (workspace, run, base, head), least recently used first out, and
# the UTF-8 bytes of their paths in all.
OUTCOME_CACHE_ENTRIES = 256
OUTCOME_CACHE_BYTES = 2 << 20
MAX_OUTCOME_PATHS = 100
MAX_OUTCOME_PATH_CHARS = 512

# Control (C0, C1, DEL), format (bidi marks, embeddings, overrides, isolates, zero-width),
# surrogate, private-use, unassigned, line and paragraph separators.
UNSAFE_CATEGORIES: frozenset[str] = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
# Letters and marks that render as nothing: Hangul fillers, Khmer inherent vowels, Mongolian
# variation selectors, variation selectors, the combining grapheme joiner, the Braille blank.
INVISIBLE_CODE_POINTS: frozenset[int] = frozenset(
    {
        0x034F,
        0x115F,
        0x1160,
        0x17B4,
        0x17B5,
        *range(0x180B, 0x1810),
        0x2800,
        0x3164,
        *range(0xFE00, 0xFE10),
        0xFFA0,
        *range(0xE0100, 0xE01F0),
    }
)
# Host codes that say the run's worktree is not where its spec says, or not as it was.
_WORKTREE_GONE = frozenset({"workspace.target_mismatch", "workspace.worktree_displaced"})


def _unsafe(character: str) -> bool:
    return (
        unicodedata.category(character) in UNSAFE_CATEGORIES
        or ord(character) in INVISIBLE_CODE_POINTS
    )


def display_path(path: str) -> str:
    """
    ``path`` with each backslash and each unsafe or invisible character as ``\\u{XXXX}``,
    so every backslash shown starts an escape, cut at 512 characters between escapes.
    """
    pieces: list[str] = []
    length = 0
    for ch in path:
        piece = f"\\u{{{ord(ch):04X}}}" if ch == "\\" or _unsafe(ch) else ch
        pieces.append(piece)
        length += len(piece)
        if length > MAX_OUTCOME_PATH_CHARS:
            # Room for the ellipsis, never half an escape.
            while length > MAX_OUTCOME_PATH_CHARS - 1:
                length -= len(pieces.pop())
            return f"{''.join(pieces)}…"
    return "".join(pieces)


@dataclass(frozen=True)
class OutcomeTarget:
    """The run's own worktree, from its spec, and the commit the run started from."""

    worktree: RunTarget
    base_commit: str | None

    @property
    def host_id(self) -> str:
        return self.worktree.host_id

    @property
    def repo_path(self) -> str:
        return self.worktree.repo_root

    @property
    def worktree_path(self) -> str:
        return self.worktree.ref.root

    @property
    def branch(self) -> str:
        return self.worktree.ref.branch


def outcome_target(state: RunState) -> OutcomeTarget | None:
    """
    The run's worktree; ``None`` when its spec names no host, repository, worktree or
    branch, or another run's branch (:func:`coral.workspace.executors.run_target`).
    """
    try:
        worktree = run_target(state)
    except EffectRefused:
        return None
    return OutcomeTarget(worktree=worktree, base_commit=state.spec.base_commit)


def _posix_absolute(path: str) -> bool:
    return path.startswith("/") and not PureWindowsPath(path).drive


def _command_safe(path: str) -> bool:
    # Without a backslash, shlex.quote's output reads the same in sh, bash, zsh and fish.
    return not any(ch == "\\" or _unsafe(ch) for ch in path)


def checkout_commands(target: OutcomeTarget | None) -> OutcomeCheckout:
    """
    The commands that check the run's branch out: ``git -C <repo> checkout --detach
    refs/heads/<branch>``, and ``cd <worktree>``, every argument quoted for a POSIX shell.

    No command when the run has no worktree of its own, a path is not an absolute POSIX
    path (so ``-C`` and ``cd`` never take it as an option), or a path holds a backslash
    or a character that is unsafe or invisible, which a shell or a reader could misread.
    """
    if target is None:
        return OutcomeCheckout(command=None, worktree_command=None, unavailable="no_worktree")
    paths = (target.repo_path, target.worktree_path)
    if not all(_posix_absolute(path) for path in paths):
        return OutcomeCheckout(command=None, worktree_command=None, unavailable="non_posix_path")
    if not all(_command_safe(path) for path in paths):
        return OutcomeCheckout(command=None, worktree_command=None, unavailable="unsafe_path")
    # The full ref, so a tag of the branch's name never stands in for it.
    ref = shlex.quote(f"refs/heads/{target.branch}")
    return OutcomeCheckout(
        command=f"git -C {shlex.quote(target.repo_path)} checkout --detach {ref}",
        worktree_command=f"cd {shlex.quote(target.worktree_path)}",
        unavailable=None,
    )


@dataclass(frozen=True)
class DiffRead:
    """The head the worktree holds now, when read, and the run's diff or why there is none."""

    head: str | None
    diff: OutcomeDiff | None
    unavailable: OutcomeUnavailable | None

    def __post_init__(self) -> None:
        if (self.diff is None) == (self.unavailable is None):
            raise ValueError("a diff read holds a diff or why there is none, never both")


def no_diff(code: OutcomeUnavailable) -> DiffRead:
    """A read that never reached the host, or learned no head."""
    return DiffRead(None, None, code)


def run_outcome(run: CoralRun, target: OutcomeTarget | None, read: DiffRead) -> RunOutcome:
    """``run``'s outcome: its stored target, the diff read and its checkout commands."""
    checkout = checkout_commands(target)
    shown = target if checkout.unavailable not in ("unsafe_path", "non_posix_path") else None
    return RunOutcome(
        run_id=run.id,
        status=row_status(run),
        finished_at=run.finished_at,
        branch=None if target is None else target.branch,
        host_id=None if target is None else target.host_id,
        repo_path=None if shown is None else shown.repo_path,
        worktree_path=None if shown is None else shown.worktree_path,
        base_commit=None if target is None else target.base_commit,
        head_commit=read.head,
        diff=read.diff,
        diff_unavailable=read.unavailable,
        checkout=checkout,
    )


def failure_code(exc: BaseException) -> str:
    """A host read failure's fixed code for a log line, else ``""``: messages can hold paths."""
    return exc.code if isinstance(exc, (HostAccessRefused, WorkspaceOpError)) else ""


def _failure(exc: Exception, *, comparing: bool) -> OutcomeUnavailable:
    """
    Why a read that raised ``exc`` has no diff. Git's failure or refused params count as
    a failed comparison only once ``diff_stat`` was sent; before it nothing was compared.
    """
    if isinstance(exc, HostAccessRefused):
        return "host_offline"
    if isinstance(exc, WorkspaceOpError):
        if exc.code == "workspace.backend_unavailable" and not exc.permanent:
            return "host_offline"
        if exc.code == "workspace.timeout":
            return "busy"
        if exc.code in _WORKTREE_GONE:
            return "worktree_missing"
        if exc.code == "workspace.git_failed" and comparing:
            return "compare_failed"
        return "failed"
    if isinstance(exc, TimeoutError):
        return "busy"
    if isinstance(exc, ValueError) and comparing:
        # Params the host refused, such as a base the repository lacks.
        return "compare_failed"
    return "failed"


def _trimmed(stat: DiffStat, base: str, head: str) -> OutcomeDiff:
    """The diff kept and sent: its counts and its first sorted paths, each shown safely."""
    first = heapq.nsmallest(MAX_OUTCOME_PATHS, stat.paths)
    return OutcomeDiff(
        from_commit=base,
        to_commit=head,
        files_changed=stat.files_changed,
        insertions=stat.insertions,
        deletions=stat.deletions,
        paths=tuple(display_path(path) for path in first),
        paths_truncated=stat.paths_truncated or len(stat.paths) > MAX_OUTCOME_PATHS,
    )


def _weight(diff: OutcomeDiff) -> int:
    return sum(len(path.encode()) for path in diff.paths)


class OutcomeDiffs:
    """
    Runs' diffs read through their owners' hosts: admitted, shared per run, bounded and
    cached. Use it on one event loop.
    """

    def __init__(
        self,
        *,
        max_reads: int = MAX_OUTCOME_READS,
        max_per_user: int = MAX_OUTCOME_READS_PER_USER,
        host_timeout_s: float = OUTCOME_HOST_TIMEOUT_S,
        deadline_s: float = OUTCOME_DEADLINE_S,
        cache_entries: int = OUTCOME_CACHE_ENTRIES,
        cache_bytes: int = OUTCOME_CACHE_BYTES,
    ) -> None:
        self._slots = Slots[CallerKey](per_key=max_per_user, total=max_reads)
        self._host_timeout_s = host_timeout_s
        self._deadline_s = deadline_s
        self._cache_entries = cache_entries
        self._cache_bytes = cache_bytes
        self._flights: dict[tuple[int, str], asyncio.Task[DiffRead]] = {}
        self._cache: OrderedDict[tuple[int, str, str, str], OutcomeDiff] = OrderedDict()
        self._cached_bytes = 0

    async def read(
        self,
        viewer: Viewer,
        *,
        state: RunState,
        target: OutcomeTarget,
        channels: HostWorkspaceChannels,
    ) -> DiffRead:
        """
        The run's diff from its base to the head its worktree holds now.

        Every caller of one run shares one read, and only the first takes an admission;
        one past the limits is ``busy`` at once. A caller that goes away leaves the read
        to the others. Every channel argument comes from the stored run.
        """
        base = target.base_commit
        if base is None:
            return no_diff("base_unknown")
        key = (state.workspace_id, state.run_id)
        flight = self._flights.get(key)
        if flight is None:
            slot = self._slots.acquire(caller_key(viewer))
            if slot is None:
                _logger.debug(
                    "Coral refused an outcome read of run %s: %d in flight",
                    state.run_id,
                    self._slots.held,
                )
                return no_diff("busy")
            flight = asyncio.get_running_loop().create_task(
                self._read(state, target, channels, base)
            )
            slot.release_when_done(flight)
            self._flights[key] = flight
            flight.add_done_callback(lambda done: self._landed(key, done))
        return await asyncio.shield(flight)

    def _landed(self, key: tuple[int, str], flight: asyncio.Task[DiffRead]) -> None:
        if self._flights.get(key) is flight:
            del self._flights[key]

    async def _read(
        self,
        state: RunState,
        target: OutcomeTarget,
        channels: HostWorkspaceChannels,
        base: str,
    ) -> DiffRead:
        head: str | None = None
        try:
            async with asyncio.timeout(self._deadline_s):
                ops = await workspace_for(
                    channels, state, target.worktree, read_timeout_s=self._host_timeout_s
                )
                ref = target.worktree.ref
                executor = HostChannel(ref.host_id)
                found = await ops.head(ref, executor)
                if found.branch != ref.branch:
                    _logger.info(
                        "Coral could not read run %s's outcome: its worktree holds another branch",
                        state.run_id,
                    )
                    return no_diff("worktree_missing")
                head = found.head
                key = (state.workspace_id, state.run_id, base, head)
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
                    return DiffRead(head, cached, None)
                stat = await ops.diff_stat(ref, executor, from_commit=base, to_commit=head)
        except Exception as exc:  # noqa: BLE001 -- every failure answers a code
            _logger.info(
                "Coral could not read run %s's outcome: %s %s",
                state.run_id,
                type(exc).__name__,
                failure_code(exc),
            )
            # The head is known exactly when diff_stat was sent.
            return DiffRead(head, None, _failure(exc, comparing=head is not None))
        diff = _trimmed(stat, base, head)
        self._remember(key, diff)
        return DiffRead(head, diff, None)

    def _remember(self, key: tuple[int, str, str, str], diff: OutcomeDiff) -> None:
        previous = self._cache.pop(key, None)
        if previous is not None:
            self._cached_bytes -= _weight(previous)
        self._cache[key] = diff
        self._cached_bytes += _weight(diff)
        while self._cache and (
            len(self._cache) > self._cache_entries or self._cached_bytes > self._cache_bytes
        ):
            _oldest, evicted = self._cache.popitem(last=False)
            self._cached_bytes -= _weight(evicted)


__all__ = [
    "INVISIBLE_CODE_POINTS",
    "MAX_OUTCOME_PATHS",
    "MAX_OUTCOME_PATH_CHARS",
    "MAX_OUTCOME_READS",
    "MAX_OUTCOME_READS_PER_USER",
    "OUTCOME_CACHE_BYTES",
    "OUTCOME_CACHE_ENTRIES",
    "OUTCOME_DEADLINE_S",
    "OUTCOME_HOST_TIMEOUT_S",
    "UNSAFE_CATEGORIES",
    "DiffRead",
    "OutcomeDiffs",
    "OutcomeTarget",
    "checkout_commands",
    "display_path",
    "failure_code",
    "no_diff",
    "outcome_target",
    "run_outcome",
]
