"""One workspace op at a time per worktree on this host, READ and WRITE alike.

An op on a worktree that is already busy fails at once with a retryable
``workspace.timeout``; it never waits. A waiting op would hold one of the host's
op slots, so a worktree whose git stalls (for example on a FIFO its agent
planted) could take every slot; failing fast keeps any one worktree to one
slot. The lock is taken inside the guarded worker thread, so it outlives a
cancelled frame task: a retry fails fast until the first try's git has ended.
"""

from __future__ import annotations

import functools
import os
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from coral.omni.host.ops._git import TIMEOUT, printable
from omnigent.host.workspace_ops import (
    WorkspaceOpHandler,
    WorkspaceOpHandlerError,
    WorkspaceOpRequest,
)

# custom-lint: disable-next=workspace-scoped-cache -- keyed by a directory on this host
_root_locks: dict[tuple[int, int] | str, threading.Lock] = {}
_root_locks_guard = threading.Lock()


@contextmanager
def root_lock(root: str) -> Iterator[None]:
    """
    Hold the worktree at ``root`` until the block exits, or refuse at once.

    Another spelling of the same directory (a symlink, a case variant) is the same worktree.

    :raises WorkspaceOpHandlerError: ``workspace.timeout`` (retryable) while
        another op holds it.
    """
    key = _root_key(root)
    with _root_locks_guard:
        lock = _root_locks.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        raise WorkspaceOpHandlerError(
            TIMEOUT,
            f"another workspace op is still running on this worktree ({printable(root)}); "
            "retry when it ends",
        )
    try:
        yield
    finally:
        lock.release()


def one_op_per_worktree(handler: WorkspaceOpHandler) -> WorkspaceOpHandler:
    """Run ``handler`` while holding its request's worktree (:func:`root_lock`)."""

    @functools.wraps(handler)
    def run(request: WorkspaceOpRequest) -> Mapping[str, Any]:
        with root_lock(request.root):
            return handler(request)

    return run


def _root_key(root: str) -> tuple[int, int] | str:
    """The directory's ``(st_dev, st_ino)``; the path itself when it cannot be stat'ed."""
    try:
        info = os.stat(root)
    except OSError:
        return root
    return info.st_dev, info.st_ino
