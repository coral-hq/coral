"""File access inside a worktree that never follows a symlink (K13 security requirement 7).

Paths are walked one component at a time from a directory handle on the
worktree root, each opened ``O_NOFOLLOW``, so a symlinked directory an agent
planted cannot lead outside the root. A file is opened ``O_NOFOLLOW |
O_NONBLOCK`` (a FIFO never blocks) and checked with ``S_ISREG`` after
``fstat``. Callers validate paths first: empty, ``.`` and ``..`` segments are
refused here too. Every function takes the op's deadline and checks it at each
component and each chunk read.
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from coral.omni.host.ops._git import check_deadline

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
# A symlink or a non-directory where the walk needs a directory.
_NOT_A_DIRECTORY = (errno.ELOOP, errno.ENOTDIR)
# Opening the last component: a symlink (ELOOP) or a socket (ENXIO, EOPNOTSUPP).
_NOT_A_FILE = (errno.ELOOP, errno.ENXIO, errno.EOPNOTSUPP)
_READ_CHUNK_BYTES = 1024 * 1024

UnreadableReason = Literal["missing", "not_regular", "too_large", "unsafe_path"]


class UnreadableFile(Exception):
    """A path that cannot be read safely; ``reason`` says why."""

    def __init__(self, reason: UnreadableReason, path: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.reason: UnreadableReason = reason
        self.path = path


def read_in_root(root: str, relpath: str | bytes, *, max_bytes: int, deadline: float) -> bytes:
    """
    Return the bytes of the regular file at ``relpath`` under ``root``.

    :raises UnreadableFile: ``missing``; ``not_regular`` (a symlink, FIFO,
        directory or other type); ``too_large`` over ``max_bytes``;
        ``unsafe_path`` for a symlinked or non-directory component, or an
        empty, ``.`` or ``..`` segment.
    :raises WorkspaceOpHandlerError: ``workspace.timeout`` past ``deadline``.
    """
    parts = _parts(relpath)
    try:
        with _parent_directory(root, parts, relpath, deadline) as parent:
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
    except FileNotFoundError:
        raise UnreadableFile("missing", _shown(relpath)) from None
    except OSError as exc:
        if exc.errno in _NOT_A_FILE:
            raise UnreadableFile("not_regular", _shown(relpath)) from None
        raise
    try:
        return _read_regular(fd, relpath, max_bytes, deadline)
    finally:
        os.close(fd)


def lstat_in_root(root: str, relpath: str | bytes, *, deadline: float) -> os.stat_result | None:
    """
    ``lstat`` the entry at ``relpath`` under ``root``; ``None`` when it does not exist.

    :raises UnreadableFile: ``unsafe_path`` for a symlinked or non-directory component.
    """
    parts = _parts(relpath)
    try:
        with _parent_directory(root, parts, relpath, deadline) as parent:
            return os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def readlink_in_root(root: str, relpath: str | bytes, *, deadline: float) -> bytes:
    """
    Return the link text of the symlink at ``relpath`` under ``root``.

    :raises UnreadableFile: ``unsafe_path`` for a symlinked or non-directory component.
    :raises OSError: when the entry is not a symlink.
    """
    parts = _parts(relpath)
    with _parent_directory(root, parts, relpath, deadline) as parent:
        return os.readlink(parts[-1], dir_fd=parent)


def read_small_file(
    path: str, *, max_bytes: int, follow_symlinks: bool, deadline: float
) -> bytes | None:
    """
    Return the bytes of the regular file at the absolute ``path``; ``None`` when absent.

    :param follow_symlinks: ``False`` refuses a symlink at the last component.
    :raises UnreadableFile: ``not_regular`` or ``too_large``.
    """
    flags = _FILE_FLAGS if not follow_symlinks else _FILE_FLAGS & ~os.O_NOFOLLOW
    check_deadline(deadline, "a file read")
    try:
        fd = os.open(path, flags)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        if exc.errno in _NOT_A_FILE:
            raise UnreadableFile("not_regular", path) from None
        raise
    try:
        return _read_regular(fd, path, max_bytes, deadline)
    finally:
        os.close(fd)


def _parts(relpath: str | bytes) -> list[bytes]:
    parts = os.fsencode(relpath).split(b"/")
    if any(part in (b"", b".", b"..") for part in parts):
        raise UnreadableFile("unsafe_path", _shown(relpath))
    return parts


@contextmanager
def _parent_directory(
    root: str, parts: list[bytes], relpath: str | bytes, deadline: float
) -> Iterator[int]:
    """Yield a handle on the directory holding ``parts[-1]``, walked without following links."""
    check_deadline(deadline, "the file walk")
    fd = _open_directory(root, None, relpath)
    try:
        for part in parts[:-1]:
            check_deadline(deadline, "the file walk")
            child = _open_directory(part, fd, relpath)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _open_directory(name: str | bytes, dir_fd: int | None, relpath: str | bytes) -> int:
    try:
        return os.open(name, _DIRECTORY_FLAGS, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in _NOT_A_DIRECTORY:
            raise UnreadableFile("unsafe_path", _shown(relpath)) from None
        raise


def _read_regular(fd: int, path: str | bytes, max_bytes: int, deadline: float) -> bytes:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise UnreadableFile("not_regular", _shown(path))
    if info.st_size > max_bytes:
        raise UnreadableFile("too_large", _shown(path))
    chunks: list[bytes] = []
    total = 0
    while chunk := os.read(fd, _READ_CHUNK_BYTES):
        check_deadline(deadline, "a file read")
        total += len(chunk)
        # The file may grow after fstat.
        if total > max_bytes:
            raise UnreadableFile("too_large", _shown(path))
        chunks.append(chunk)
    return b"".join(chunks)


def _shown(path: str | bytes) -> str:
    return os.fsdecode(path)
