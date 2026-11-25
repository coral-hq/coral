"""Filesystem paths shared by host and harness-process lifecycle code."""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

from omnigent._platform import IS_WINDOWS

HARNESS_TMP_PARENT_ENV_VAR = "OMNIGENT_HARNESS_TMP_PARENT"


def harness_tmp_parent(env: Mapping[str, str] | None = None) -> Path:
    """Return the configured harness socket root without changing relativity."""
    source = os.environ if env is None else env
    configured = source.get(HARNESS_TMP_PARENT_ENV_VAR)
    if configured:
        return Path(configured).expanduser()
    if IS_WINDOWS:
        return Path(tempfile.gettempdir()) / "omnigent"
    return Path(f"/tmp/omnigent-{os.getuid()}")


def absolute_harness_tmp_parent(path: Path) -> Path:
    """Make a harness socket root absolute without resolving symlinks."""
    return Path(os.path.abspath(path.expanduser()))


def resolve_harness_tmp_parent(env: Mapping[str, str] | None = None) -> Path:
    """Return one short absolute socket root for cross-process propagation."""
    return absolute_harness_tmp_parent(harness_tmp_parent(env))


# CORAL(S130)
def private_dir_problem(info: os.stat_result) -> str | None:
    if stat.S_ISLNK(info.st_mode):
        return "is a symlink (a symlinked harness socket root is refused; set the real path)"
    if not stat.S_ISDIR(info.st_mode):
        return "is not a directory"
    if info.st_uid != os.geteuid():
        return f"is owned by uid {info.st_uid}, not this user"
    if info.st_mode & 0o022:
        return f"is writable by group or other (mode {stat.S_IMODE(info.st_mode):#o})"
    return None


# CORAL(S130)
def ensure_private_dir(path: Path) -> None:
    if IS_WINDOWS:
        path.mkdir(parents=True, exist_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileExistsError):
        os.mkdir(path, 0o700)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    try:
        try:
            fd = os.open(path, flags)
        except PermissionError:
            info = os.lstat(path)
            if private_dir_problem(info) is None and not info.st_mode & 0o077:
                return
            raise
    except OSError as exc:
        problem = f"cannot be opened ({exc.strerror})"
        with contextlib.suppress(OSError):
            problem = private_dir_problem(os.lstat(path)) or problem
        raise RuntimeError(f"Refusing harness directory {path}: it {problem}") from exc
    try:
        info = os.fstat(fd)
        problem = private_dir_problem(info)
        if problem is not None:
            raise RuntimeError(f"Refusing harness directory {path}: it {problem}")
        if info.st_mode & 0o077:
            os.fchmod(fd, 0o700)
    finally:
        os.close(fd)
