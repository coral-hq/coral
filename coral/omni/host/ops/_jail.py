"""The jail every git process of the host ops runs in.

An agent process that outlived its session can swap a directory in the
worktree for a symlink while host git is working, and git, which resolves
paths again on each open, then writes, deletes or reads through it. The jail
makes the kernel refuse that:

- git may write only the paths the op needs (``_target.op_jail``): for a WRITE
  op the worktree, the objects, the ``coral/`` refs and their logs,
  ``packed-refs``, the worktree's own admin dir and the op's private temp dir;
  for a READ op the temp dir alone. Never ``hooks/``, ``config``, ``info/`` or
  other refs;
- under the user's home directory git may read file data only of the paths
  the op names (the worktree, the repository, the temp dir, git's install, the
  repository's config includes and the global ignore and attribute files).

macOS: ``/usr/bin/sandbox-exec`` with an allow-default profile. Paths travel as
``-D`` parameters, never inside the profile text. Seatbelt checks the path a
symlink resolves to, so a raced link leads nowhere.

Linux: ``bwrap`` with the root file system bound read-only, a fresh ``/dev``,
the home directory replaced by an empty tmpfs (readable paths bound back, a
symlinked one at both its spelling and its target) and read-write binds of the
writable directories. No new session or pid namespace: the jail stays in git's
process group, so the deadline's group kill reaches git and git's exit code
passes through. Single writable files (``packed-refs``) cannot be bound before
they exist, so they stay read-only there.

The tool is checked once per process by running ``git --version`` inside a
jail, after it is checked to sit outside the op's worktree and repository.
Without a working tool WRITE ops refuse permanently; READ ops run unjailed
(they never write).
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Literal

_logger = logging.getLogger(__name__)

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
JailToolName = Literal["sandbox-exec", "bwrap"]

# Writes are refused outside the W* (directory) and F* (file) parameters; file
# data under HOME_DIR is unreadable outside the R* parameters. Only metadata
# (lstat, readlink) stays readable there, which git needs to resolve paths.
_PROFILE_HEAD = (
    '(version 1)(allow default)(deny file-write* (require-not (require-any (literal "/dev/null")'
)


@dataclass(frozen=True)
class JailTool:
    name: JailToolName
    executable: str


@dataclass(frozen=True)
class Jail:
    """
    Where jailed git may write, and which paths under ``home`` it may read.

    :param writable: Canonical directories git may write under.
    :param writable_files: Canonical single files git may write (macOS only).
    :param home: The user's home directory, canonical; ``None`` leaves reads open.
    :param readable: Canonical paths under ``home`` whose data git may read.
    :param aliases: ``(spelling, canonical)`` for a readable path reached
        through a symlink; bwrap binds it at both.
    """

    tool: JailTool
    writable: tuple[str, ...]
    writable_files: tuple[str, ...] = ()
    home: str | None = None
    readable: tuple[str, ...] = ()
    aliases: tuple[tuple[str, str], ...] = ()

    def allowing_reads(self, *paths: str) -> Jail:
        """This jail, also letting git read ``paths`` (absolute; symlinks resolved and kept)."""
        readable = list(self.readable)
        aliases = list(self.aliases)
        for path in paths:
            if not path:
                continue
            canonical = os.path.realpath(path)
            readable.append(canonical)
            if os.path.normpath(path) != canonical:
                aliases.append((os.path.normpath(path), canonical))
        return replace(
            self,
            readable=tuple(dict.fromkeys(readable)),
            aliases=tuple(dict.fromkeys(aliases)),
        )

    def without_read_limits(self) -> Jail:
        """This jail with reads open: for reading the user's own config and its includes."""
        return replace(self, home=None, readable=(), aliases=())

    def command(self, argv: Sequence[str | bytes], *, cwd: str | None) -> list[str | bytes]:
        """``argv`` run inside the jail."""
        if self.tool.name == "sandbox-exec":
            return [*self._sandbox_exec_prefix(), *argv]
        return [*self._bwrap_prefix(cwd), *argv]

    def _sandbox_exec_prefix(self) -> list[str]:
        params = []
        writes = []
        for index, path in enumerate(self.writable):
            params += ["-D", f"W{index}={path}"]
            writes.append(f'(subpath (param "W{index}"))')
        for index, path in enumerate(self.writable_files):
            params += ["-D", f"F{index}={path}"]
            writes.append(f'(literal (param "F{index}"))')
        profile = f"{_PROFILE_HEAD} {' '.join(writes)})))"
        if self.home is not None:
            params += ["-D", f"HOME_DIR={self.home}"]
            reads = []
            for index, path in enumerate(self.readable):
                params += ["-D", f"R{index}={path}"]
                reads.append(f'(subpath (param "R{index}"))')
            # Listing (not reading) each directory above a readable path lets
            # getcwd() and realpath() find their way down from the home directory.
            for index, directory in enumerate(_ancestors_within(self.readable, self.home)):
                params += ["-D", f"A{index}={directory}"]
                reads.append(f'(literal (param "A{index}"))')
            exceptions = f"(require-not (require-any {' '.join(reads)}))" if reads else ""
            profile += (
                f'(deny file-read-data (require-all (subpath (param "HOME_DIR")) {exceptions}))'
            )
        return [self.tool.executable, *params, "-p", profile]

    def _bwrap_prefix(self, cwd: str | None) -> list[str]:
        args = [self.tool.executable, "--ro-bind", "/", "/", "--dev", "/dev"]
        if self.home is not None:
            args += ["--tmpfs", self.home]
            for source, destination in self._home_binds():
                args += ["--ro-bind-try", source, destination]
        for path in self.writable:
            # A missing directory stays unwritable rather than failing every call.
            args += ["--bind-try", path, path]
        if cwd is not None:
            args += ["--chdir", cwd]
        return [*args, "--"]

    def _home_binds(self) -> Iterable[tuple[str, str]]:
        """Read-only binds back into the emptied home: each path, and each symlinked spelling."""
        assert self.home is not None
        for path in self.readable:
            if path not in self.writable and _is_within(path, self.home):
                yield path, path
        for spelling, canonical in self.aliases:
            if _is_within(spelling, self.home):
                yield canonical, spelling


class JailUnavailable(Exception):
    """No jail tool works on this host; the message names the tool and why."""


def locate_jail_tool(system: str | None = None) -> JailTool | None:
    """The jail tool for ``system`` (this host's when ``None``), or ``None`` when absent."""
    system = platform.system() if system is None else system
    if system == "Darwin":
        if os.access(SANDBOX_EXEC, os.X_OK):
            return JailTool("sandbox-exec", SANDBOX_EXEC)
        return None
    if system == "Linux":
        found = shutil.which("bwrap")
        if found is not None and os.path.isabs(found):
            return JailTool("bwrap", os.path.realpath(found))
    return None


def required_tool(system: str | None = None) -> str:
    """The jail tool WRITE ops need on ``system``, as named in refusals."""
    system = platform.system() if system is None else system
    if system == "Darwin":
        return f"sandbox-exec ({SANDBOX_EXEC})"
    if system == "Linux":
        return "bubblewrap (bwrap)"
    return f"a write jail, which Coral has none of for {system or 'this system'}"


# The tool that passed its check, once per process.
_checked_tool: JailTool | None = None
_check_lock = threading.Lock()


def checked_jail_tool(
    run_version: Callable[[Jail], str | None], *, refuse_inside: Callable[[JailTool], None]
) -> JailTool:
    """
    This host's jail tool, after ``git --version`` ran inside a jail once per process.

    :param run_version: Runs ``git --version`` in the given jail; returns why it
        failed, or ``None``.
    :param refuse_inside: Raises when the tool sits inside the op's worktree or
        repository; called before the tool first runs, and on every op.
    :raises JailUnavailable: when the tool is missing or does not work here.
    """
    global _checked_tool
    with _check_lock:
        tool = _checked_tool
        if tool is None:
            tool = locate_jail_tool()
            if tool is None:
                raise JailUnavailable(f"{required_tool()} is not installed")
            refuse_inside(tool)
            probe_dir = os.path.realpath(tempfile.mkdtemp(prefix="coral-jail-check-"))
            try:
                failure = run_version(Jail(tool=tool, writable=(probe_dir,)))
            finally:
                shutil.rmtree(probe_dir, ignore_errors=True)
            if failure is not None:
                raise JailUnavailable(f"{required_tool()} cannot run git here: {failure}")
            _checked_tool = tool
    refuse_inside(tool)
    return tool


def home_directory() -> str | None:
    """The user's home directory, canonical; ``None`` when unset or the root."""
    home = os.environ.get("HOME")
    if not home or not os.path.isabs(home):
        return None
    home = os.path.realpath(home)
    return None if home == "/" else home


_warned_unjailed = False


def log_unjailed_reads(reason: str) -> None:
    """Warn once per process that READ ops run without a jail."""
    global _warned_unjailed
    if not _warned_unjailed:
        _warned_unjailed = True
        _logger.warning("Coral workspace READ ops run without a write jail: %s", reason)


def _ancestors_within(paths: Sequence[str], home: str) -> list[str]:
    """The directories from ``home`` down to each path's parent, for paths under ``home``."""
    ancestors: dict[str, None] = {}
    for path in paths:
        if not _is_within(path, home) or path == home:
            continue
        directory = os.path.dirname(path)
        while _is_within(directory, home):
            ancestors[directory] = None
            if directory == home:
                break
            directory = os.path.dirname(directory)
    return sorted(ancestors)


def _is_within(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory.rstrip("/") + "/")
