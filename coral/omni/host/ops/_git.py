"""Argv-only git for Coral's host workspace ops.

Each call runs git by absolute path, never through a shell, with K13's
hardening flags (plus the host's submodule and signature settings) first and
an environment built from scratch: no inherited ``GIT_*`` variable can point
it at another repository or inject config. A monotonic deadline stops the
whole process group (SIGTERM, then SIGKILL), and output is capped.
``Git.run_locking`` retries a write while another git process holds a
``*.lock`` file, within a lock budget, and never removes the lock.

Git never looks inside a submodule or a nested repository: their config and
attributes sit in the agent-writable worktree, so a child git started there
could run the agent's filters. Status and diff calls go through
``WORKSPACE_STATUS_ARGV`` and ``tree_diff_argv``; no READ op uses a
``--recurse-submodules`` option, and none may.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import selectors
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import IO, cast

from coral.workspace.ops import GIT_DIFF_FLAGS, GIT_ENV, GIT_HARDENING_CONFIG, WORKSPACE_PATHSPEC
from omnigent.host.workspace_ops import WorkspaceOpHandlerError

_logger = logging.getLogger(__name__)

# Failure codes: K13's ``workspace.*`` codes plus the host's ``invalid_params``.
BACKEND_UNAVAILABLE = "workspace.backend_unavailable"
CAPABILITY_UNAVAILABLE = "workspace.capability_unavailable"
GIT_FAILED = "workspace.git_failed"
INVALID_PARAMS = "workspace.invalid_params"
TARGET_MISMATCH = "workspace.target_mismatch"
TIMEOUT = "workspace.timeout"

# GIT_CONFIG_GLOBAL, which isolates the op's config, arrived in git 2.32.
MIN_GIT_VERSION = (2, 32)
# GIT_NO_LAZY_FETCH arrived in git 2.44; older git would fetch for a partial clone.
NO_LAZY_FETCH_VERSION = (2, 44)
# K13's hardening, plus settings that keep git out of submodules and signature programs.
HOST_HARDENING_CONFIG: tuple[str, ...] = (
    *GIT_HARDENING_CONFIG,
    "-c",
    "submodule.recurse=false",
    "-c",
    "status.submoduleSummary=false",
    "-c",
    "diff.submodule=short",
    "-c",
    "log.showSignature=false",
)
# The command-line option wins over config and an agent-written .gitmodules.
NO_SUBMODULE_STATUS = "--ignore-submodules=dirty"
# L1's status: submodule commits still show, their contents are never examined.
WORKSPACE_STATUS_ARGV: tuple[str, ...] = (
    "status",
    "--porcelain=v2",
    "-z",
    "--untracked-files=all",
    "--no-show-stash",
    NO_SUBMODULE_STATUS,
    "--",
    *WORKSPACE_PATHSPEC,
)
MAX_STDOUT_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
STDERR_TAIL_CHARS = 2000
# How long a write waits in all for another git process's lock.
LOCK_BUDGET_S = 30.0
_FIRST_LOCK_BACKOFF_S = 0.25
_MAX_LOCK_BACKOFF_S = 2.0
# After SIGTERM, git gets this long to remove its lock files before SIGKILL.
_TERM_GRACE_S = 2.0
# How long to wait for a killed git; one stuck in the kernel is then left to the reaper.
_KILL_WAIT_S = 2.0
# Directories git may need besides its own; the host's PATH is never passed on.
_SAFE_PATH_DIRS = ("/usr/bin", "/bin")
# Inherited variables git keeps: where the user's own config, ignores and attributes live.
_PASSED_THROUGH_ENV = ("HOME", "XDG_CONFIG_HOME")
_READ_CHUNK_BYTES = 64 * 1024
_LOCK_HELD = re.compile(rb"Unable to create '([^'\n]+\.lock)': File exists")
_VERSION = re.compile(r"git version (\d+)\.(\d+)")

# The host's git (realpath) and version, found and checked once per process.
_resolved_git: tuple[str, tuple[int, int]] | None = None
_resolve_lock = threading.Lock()


@dataclass(frozen=True)
class GitResult:
    exit_code: int
    stdout: bytes
    stderr: bytes


class _DeadlinePassed(Exception):
    pass


class _OutputTooLarge(Exception):
    def __init__(self, stream: str, cap: int) -> None:
        super().__init__(stream)
        self.stream = stream
        self.cap = cap


@dataclass(frozen=True)
class Git:
    """
    Runs git for one op: by absolute path, with a fresh environment, until ``deadline``.

    :param executable: Absolute path of the checked git.
    :param deadline: The op's ``time.monotonic()`` deadline.
    :param version: ``(major, minor)`` of ``executable``; ``None`` when unknown.
    :param cwd: Working directory of every call.
    :param git_dir: ``GIT_DIR`` once the target is pinned.
    :param work_tree: ``GIT_WORK_TREE`` once the target is pinned.
    :param config_args: ``-c`` settings read from the user's full config.
    :param isolated: Run under K13's ``GIT_ENV``, so global and system config
        are off. ``False`` only to read settings from the user's full config.
    :param extra_env: More variables, e.g. ``GIT_INDEX_FILE`` or the identity.
    :param sleep: Waits between lock retries; injectable for tests.
    """

    executable: str
    deadline: float
    version: tuple[int, int] | None = None
    cwd: str | None = None
    git_dir: str | None = None
    work_tree: str | None = None
    config_args: tuple[str, ...] = ()
    isolated: bool = True
    extra_env: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    sleep: Callable[[float], None] = time.sleep

    def environment(self) -> dict[str, str]:
        """The child's whole environment; nothing else is inherited."""
        path_dirs = (os.path.dirname(self.executable), *_SAFE_PATH_DIRS)
        env = {"PATH": os.pathsep.join(dict.fromkeys(path_dirs))}
        for name in _PASSED_THROUGH_ENV:
            value = os.environ.get(name)
            if value:
                env[name] = value
        if self.isolated:
            env.update(GIT_ENV)
            # GIT_CONFIG_NOSYSTEM leaves the system-wide attributes file on.
            env["GIT_ATTR_NOSYSTEM"] = "1"
        else:
            env.update({k: v for k, v in GIT_ENV.items() if not k.startswith("GIT_CONFIG_")})
        # A partial clone must not fetch missing objects: no network, nothing written.
        env["GIT_NO_LAZY_FETCH"] = "1"
        if self.git_dir is not None:
            env["GIT_DIR"] = self.git_dir
        if self.work_tree is not None:
            env["GIT_WORK_TREE"] = self.work_tree
        env.update(self.extra_env)
        return env

    def run(
        self,
        *argv: str | bytes,
        input: bytes | None = None,
        ok_exit_codes: Collection[int] = (0,),
        check: bool = True,
        stdout_cap: int = MAX_STDOUT_BYTES,
    ) -> GitResult:
        """
        Run ``git <hardening> <config_args> <argv>`` and return its output.

        :param input: Bytes for stdin; stdin is ``/dev/null`` without it.
        :param ok_exit_codes: Exit codes that are not a failure.
        :param check: ``False`` returns any exit code instead of raising.
        :param stdout_cap: Most stdout bytes accepted.
        :raises WorkspaceOpHandlerError: ``workspace.timeout`` at the deadline
            (the process group is stopped), ``workspace.git_failed`` for another
            exit code or output over its cap, ``workspace.backend_unavailable``
            when git cannot start.
        """
        name = _subcommand(argv)
        if self.deadline - time.monotonic() <= 0:
            raise _timed_out(name)
        try:
            process = subprocess.Popen(
                [self.executable, *HOST_HARDENING_CONFIG, *self.config_args, *argv],
                cwd=self.cwd,
                env=self.environment(),
                stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise WorkspaceOpHandlerError(
                BACKEND_UNAVAILABLE, f"cannot start git {name}: {exc.strerror or exc}"
            ) from None
        try:
            stdout, stderr = _communicate(process, input, self.deadline, stdout_cap)
            exit_code = process.wait(timeout=max(0.0, self.deadline - time.monotonic()))
        except (_DeadlinePassed, subprocess.TimeoutExpired):
            _stop_group(process)
            raise _timed_out(name) from None
        except _OutputTooLarge as exc:
            _stop_group(process)
            raise WorkspaceOpHandlerError(
                GIT_FAILED, f"git {name} wrote more than {exc.cap} bytes to {exc.stream}"
            ) from None
        except BaseException:
            _stop_group(process)
            raise
        finally:
            _close_pipes(process)
        result = GitResult(exit_code=exit_code, stdout=stdout, stderr=stderr)
        if check and exit_code not in ok_exit_codes:
            raise git_failure(name, result)
        return result

    def run_locking(self, *argv: str | bytes, input: bytes | None = None) -> GitResult:
        """
        Run a write, retrying while another git process holds a ``*.lock`` file.

        Retries back off from 0.25 s, doubling up to 2 s, until a budget of
        ``min(LOCK_BUDGET_S, time left)`` is spent. The lock is never removed:
        it may belong to a live git process.

        :raises WorkspaceOpHandlerError: ``workspace.timeout`` (retryable) naming
            the lock when the budget is spent; otherwise as :meth:`run`.
        """
        budget = min(LOCK_BUDGET_S, max(0.0, self.deadline - time.monotonic()))
        waited = 0.0
        delay = _FIRST_LOCK_BACKOFF_S
        while True:
            result = self.run(*argv, input=input, check=False)
            if result.exit_code == 0:
                return result
            held = _LOCK_HELD.search(result.stderr)
            if held is None:
                raise git_failure(_subcommand(argv), result)
            if waited >= budget:
                raise WorkspaceOpHandlerError(
                    TIMEOUT,
                    f"{printable(held.group(1))} is still held by another git process after "
                    f"{waited:g} s; remove it only if no git process is running",
                )
            pause = min(delay, budget - waited)
            self.sleep(pause)
            waited += pause
            delay = min(delay * 2, _MAX_LOCK_BACKOFF_S)


def tree_diff_argv(start: str, end: str) -> tuple[str, ...]:
    """``diff --numstat`` between two commits, never looking inside a submodule."""
    return (
        "diff",
        "--numstat",
        "-z",
        "--no-renames",
        NO_SUBMODULE_STATUS,
        *GIT_DIFF_FLAGS,
        "--end-of-options",
        start,
        end,
        "--",
        *WORKSPACE_PATHSPEC,
    )


def git_failure(name: str, result: GitResult) -> WorkspaceOpHandlerError:
    """``workspace.git_failed`` with the exit code and the escaped tail of stderr."""
    tail = printable(result.stderr.strip())[-STDERR_TAIL_CHARS:]
    return WorkspaceOpHandlerError(
        GIT_FAILED,
        f"git {name} failed with exit {result.exit_code}: {tail}",
        exit_code=result.exit_code,
    )


def printable(value: str | bytes) -> str:
    """
    Text safe for a message: UTF-8 (invalid bytes replaced) with control characters escaped.

    File names and git output come from the worktree, so an agent chooses them.
    """
    if isinstance(value, bytes):
        text = value.decode("utf-8", "replace")
    else:
        text = value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    # repr() of one character escapes it, e.g. "\x1b", "\n" or "​".
    return "".join(char if char.isprintable() else repr(char)[1:-1] for char in text)


def check_deadline(deadline: float, what: str) -> None:
    """Raise ``workspace.timeout`` once the op's deadline has passed."""
    if time.monotonic() >= deadline:
        raise WorkspaceOpHandlerError(TIMEOUT, f"{what} did not finish before the op's deadline")


def require_posix() -> None:
    """Refuse on a non-POSIX host: the group kill and the ``O_NOFOLLOW`` walk need POSIX."""
    if os.name != "posix":
        raise WorkspaceOpHandlerError(
            BACKEND_UNAVAILABLE, "Coral workspace ops need a POSIX host", permanent=True
        )


def require_git_outside(executable: str, roots: Sequence[str]) -> None:
    """
    Refuse a git whose path, or real path, passes through a directory in ``roots``.

    Directories compare by device and inode, not by spelling: a case variant on
    a case-folding disk, or a symlink, names the same directory.

    :raises WorkspaceOpHandlerError: ``workspace.backend_unavailable``, permanent.
    """
    forbidden = {_identity(root): root for root in roots}
    forbidden.pop(None, None)
    if not forbidden:
        return
    for path in dict.fromkeys((os.path.abspath(executable), os.path.realpath(executable))):
        directory = os.path.dirname(path)
        while True:
            root = forbidden.get(_identity(directory))
            if root is not None:
                raise WorkspaceOpHandlerError(
                    BACKEND_UNAVAILABLE,
                    f"git at {printable(executable)} is inside {printable(root)}; "
                    "Coral runs git only from outside the worktree",
                    permanent=True,
                )
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent


def _identity(path: str) -> tuple[int, int] | None:
    """``(st_dev, st_ino)`` of ``path``, following symlinks; ``None`` when it cannot be stat'ed."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_dev, info.st_ino


def parse_git_version(text: str) -> tuple[int, int]:
    """
    Read ``(major, minor)`` from ``git --version`` output, e.g. ``"git version 2.54.0"``.

    :raises ValueError: when the text names no version.
    """
    match = _VERSION.search(text)
    if match is None:
        raise ValueError(f"no git version in {text!r}")
    return int(match[1]), int(match[2])


def locate_git(
    search_path: str | None, *, deadline: float, outside: Sequence[str] = ()
) -> tuple[str, tuple[int, int]]:
    """
    Find git on ``search_path`` (the host's ``PATH`` when ``None``) and check its version.

    The found binary is checked against ``outside`` before it runs at all.

    :returns: The git's real path and its ``(major, minor)``, at least ``MIN_GIT_VERSION``.
    :raises WorkspaceOpHandlerError: ``workspace.backend_unavailable``, permanent,
        when git is missing, inside ``outside``, older than 2.32 or reports no version.
    """
    found = shutil.which("git", path=search_path)
    if found is None or not os.path.isabs(found):
        raise WorkspaceOpHandlerError(
            BACKEND_UNAVAILABLE, "git was not found on the host's PATH", permanent=True
        )
    require_git_outside(found, outside)
    executable = os.path.realpath(found)
    text = Git(executable=executable, deadline=deadline, cwd="/").run("--version").stdout
    reported = printable(text.strip())[:200]
    try:
        version = parse_git_version(reported)
    except ValueError:
        raise WorkspaceOpHandlerError(
            BACKEND_UNAVAILABLE,
            f"cannot read the version of {printable(executable)}: {reported}",
            permanent=True,
        ) from None
    if version < MIN_GIT_VERSION:
        raise WorkspaceOpHandlerError(
            BACKEND_UNAVAILABLE,
            f"Coral workspace ops need git 2.32 or newer; {printable(executable)} reports "
            f"{reported}",
            permanent=True,
        )
    return executable, version


def host_git(deadline: float, *, outside: Sequence[str] = ()) -> Git:
    """
    Return an unpinned ``Git`` for one op.

    Git is found and version-checked once per process; every op checks it
    against its own ``outside`` paths before running it.
    """
    global _resolved_git
    with _resolve_lock:
        if _resolved_git is None:
            _resolved_git = locate_git(None, deadline=deadline, outside=outside)
        executable, version = _resolved_git
    require_git_outside(executable, outside)
    return Git(executable=executable, deadline=deadline, version=version)


def _subcommand(argv: tuple[str | bytes, ...]) -> str:
    """The git subcommand in ``argv`` for messages, skipping global ``-c`` options."""
    args = iter(argv)
    for arg in args:
        text = os.fsdecode(arg)
        if text == "-c":
            next(args, None)
        elif not text.startswith("-"):
            return text
    return os.fsdecode(argv[0]) if argv else "git"


def _timed_out(name: str) -> WorkspaceOpHandlerError:
    return WorkspaceOpHandlerError(TIMEOUT, f"git {name} did not finish before the op's deadline")


def _communicate(
    process: subprocess.Popen[bytes], input: bytes | None, deadline: float, stdout_cap: int
) -> tuple[bytes, bytes]:
    """Feed stdin and drain both pipes until EOF, enforcing the deadline and caps."""
    assert process.stdout is not None and process.stderr is not None
    caps: dict[IO[bytes], tuple[str, int]] = {
        process.stdout: ("stdout", stdout_cap),
        process.stderr: ("stderr", MAX_STDERR_BYTES),
    }
    output: dict[IO[bytes], bytearray] = {process.stdout: bytearray(), process.stderr: bytearray()}
    pending = memoryview(input or b"")
    stdin = process.stdin
    with selectors.DefaultSelector() as selector:
        for stream in output:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        if stdin is not None:
            if pending:
                os.set_blocking(stdin.fileno(), False)
                selector.register(stdin, selectors.EVENT_WRITE)
            else:
                stdin.close()
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _DeadlinePassed
            for key, _events in selector.select(remaining):
                stream = cast("IO[bytes]", key.fileobj)
                if stdin is not None and stream is stdin:
                    pending = _write_some(stdin, pending)
                    if not pending:
                        selector.unregister(stdin)
                        with contextlib.suppress(BrokenPipeError):
                            stdin.close()
                    continue
                try:
                    data = os.read(stream.fileno(), _READ_CHUNK_BYTES)
                except BlockingIOError:
                    continue
                if not data:
                    selector.unregister(stream)
                    continue
                buffer = output[stream]
                buffer += data
                stream_name, cap = caps[stream]
                if len(buffer) > cap:
                    raise _OutputTooLarge(stream_name, cap)
    return bytes(output[process.stdout]), bytes(output[process.stderr])


def _write_some(stdin: IO[bytes], pending: memoryview) -> memoryview:
    """Write what the pipe takes now; git closing stdin early drops the rest."""
    try:
        written = os.write(stdin.fileno(), pending[:_READ_CHUNK_BYTES])
    except BlockingIOError:
        return pending
    except BrokenPipeError:
        return pending[len(pending) :]
    return pending[written:]


def _stop_group(process: subprocess.Popen[bytes]) -> None:
    """
    Stop git and every process it started (it leads its own session).

    SIGTERM first, so git removes its lock and temp files; SIGKILL after a
    grace for whatever is left. Each wait is bounded: a process stuck in the
    kernel (a hung mount) is left for the reaper instead of holding the thread.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=_TERM_GRACE_S)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=_KILL_WAIT_S)
    except subprocess.TimeoutExpired:
        _logger.warning("git process %d did not exit after SIGKILL; leaving it", process.pid)


def _close_pipes(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            with contextlib.suppress(OSError):
                stream.close()
