"""Move a worktree aside while a WRITE op's git works in it (macOS).

An agent process can outlive its session on macOS (a double-forked ``setsid``
process survives the session's teardown) and race host git through symlinks.
The agent's seatbelt profile grants writes by path, so once the worktree is
renamed to the sibling ``<root>.coral-op`` such a process can no longer write
anything in it, not even through a directory fd or cwd it already holds. The
sibling sits in ``<repo>-worktrees/``, which no agent can write.

Each WRITE op renames the worktree aside before its git runs, runs git there
with the pinned ``GIT_DIR``/``GIT_WORK_TREE``, and renames it back in
``finally``. An aside copy found when an op starts (a host that died mid-op)
is moved back first; if the worktree path exists too, nothing is guessed:
``workspace.worktree_displaced``, permanent. Linux needs none of this: agents
run in a pid namespace, so no agent process outlives the stop.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from coral.omni.host.ops._git import BACKEND_UNAVAILABLE, printable
from omnigent.host.workspace_ops import WorkspaceOpHandlerError

ASIDE_SUFFIX = ".coral-op"
WORKTREE_DISPLACED = "workspace.worktree_displaced"


def aside_path(root: str) -> str:
    """Where ``root`` waits while a WRITE op runs: ``<root>.coral-op``."""
    return root + ASIDE_SUFFIX


def move_aside_enabled() -> bool:
    """Only macOS needs it: a surviving agent process there is bound by path."""
    return sys.platform == "darwin"


def recover(root: str) -> None:
    """
    Move a worktree left aside by an interrupted op back to ``root``.

    An empty directory at ``root`` (all a surviving process can make there) is
    replaced, as the rename back does.

    :raises WorkspaceOpHandlerError: ``workspace.worktree_displaced``, permanent,
        when a non-empty directory, a file or a symlink is at ``root``.
    """
    aside = aside_path(root)
    if not os.path.lexists(aside):
        return
    if os.path.lexists(root) and not _is_empty_directory(root):
        raise _displaced(root, aside, "both exist")
    try:
        # Replaces an empty directory; fails if it gained an entry meanwhile.
        os.rename(aside, root)
    except OSError as exc:
        raise _displaced(root, aside, exc.strerror or type(exc).__name__) from None


@contextmanager
def moved_aside(root: str) -> Iterator[str]:
    """
    Rename ``root`` aside for the block, and back afterwards; yields the aside path.

    :raises WorkspaceOpHandlerError: ``workspace.backend_unavailable`` (retryable)
        when ``root`` cannot be renamed; ``workspace.worktree_displaced``
        (permanent) when something took ``root``'s place meanwhile and the tree
        cannot go back.
    """
    aside = aside_path(root)
    try:
        os.rename(root, aside)
    except OSError as exc:
        raise WorkspaceOpHandlerError(
            BACKEND_UNAVAILABLE,
            f"cannot move the worktree {printable(root)} aside: {exc.strerror or exc}",
        ) from None
    try:
        yield aside
    finally:
        try:
            # Replaces an empty directory a surviving process may have made at root.
            os.rename(aside, root)
        except OSError as exc:
            raise _displaced(root, aside, exc.strerror or type(exc).__name__) from None


def _is_empty_directory(path: str) -> bool:
    try:
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            return False
        with os.scandir(path) as entries:
            return next(entries, None) is None
    except OSError:
        return False


def _displaced(root: str, aside: str, why: str) -> WorkspaceOpHandlerError:
    return WorkspaceOpHandlerError(
        WORKTREE_DISPLACED,
        f"the worktree {printable(root)} and its aside copy {printable(aside)} need a person "
        f"({why}): keep the one with the work, remove the other",
        permanent=True,
    )
