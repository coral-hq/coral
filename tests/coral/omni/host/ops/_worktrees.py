"""Real git worktrees and op requests for Coral's host workspace-op handler tests."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pytest

from omnigent.host.workspace_ops import WorkspaceOpHandlerError, WorkspaceOpRequest

INITIAL_FILES: Mapping[str, bytes] = {
    "README.md": b"hello\n",
    "src/app.py": b"print('app')\n",
}
BRANCH = "coral/r-test/base"
# Test setup commits under a fixed identity, never the developer's.
_SETUP_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.test",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.test",
}


def run_git(cwd: Path, *args: str) -> str:
    """Run test-setup git in ``cwd`` (with the test's isolated ``HOME``) and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **_SETUP_ENV},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout.decode()


@dataclass(frozen=True)
class LinkedWorktree:
    """A repository with ``INITIAL_FILES`` at ``base`` and one linked worktree on ``BRANCH``.

    :param repo_root: The main worktree, canonical.
    :param root: The linked worktree the ops act on, canonical.
    :param base: The initial commit.
    """

    repo_root: Path
    root: Path
    branch: str
    base: str

    @property
    def common_dir(self) -> Path:
        return self.repo_root / ".git"

    @property
    def admin_dir(self) -> Path:
        """``<common>/worktrees/<name>``, the linked worktree's own git dir."""
        return self.common_dir / "worktrees" / self.root.name

    def write(self, path: str, content: bytes) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def commit(self, message: str) -> str:
        """Commit every change in the worktree with test setup git; return the commit."""
        run_git(self.root, "add", "-A")
        run_git(self.root, "commit", "-q", "--no-verify", "-m", message)
        return run_git(self.root, "rev-parse", "HEAD").strip()


def make_repository(path: Path) -> str:
    """Create a repository at ``path`` with ``INITIAL_FILES`` committed on ``main``."""
    path.mkdir(parents=True)
    run_git(path, "init", "-q", "-b", "main")
    for name, content in INITIAL_FILES.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(content)
    run_git(path, "add", "-A")
    run_git(path, "commit", "-q", "-m", "initial")
    return run_git(path, "rev-parse", "HEAD").strip()


def make_linked_worktree(parent: Path) -> LinkedWorktree:
    """Lay out ``<parent>/repo`` and ``<parent>/repo-worktrees/coral-r-test-base``."""
    parent = parent.resolve()
    repo_root = parent / "repo"
    base = make_repository(repo_root)
    root = parent / "repo-worktrees" / "coral-r-test-base"
    run_git(repo_root, "worktree", "add", "-q", "-b", BRANCH, str(root))
    return LinkedWorktree(repo_root=repo_root, root=root, branch=BRANCH, base=base)


def make_partial_clone_worktree(parent: Path) -> tuple[LinkedWorktree, str]:
    """A blobless clone of a local repository, with Coral's linked worktree.

    :returns: The worktree, and an older commit whose blobs the clone lacks.
    """
    parent = parent.resolve()
    source = parent / "source"
    older = make_repository(source)
    (source / "README.md").write_bytes(b"changed upstream\n")
    run_git(source, "commit", "-qam", "change")
    run_git(source, "config", "uploadpack.allowFilter", "true")
    repo_root = parent / "clone"
    run_git(parent, "clone", "-q", "--filter=blob:none", f"file://{source}", str(repo_root))
    root = parent / "repo-worktrees" / "coral-r-test-base"
    run_git(repo_root, "worktree", "add", "-q", "-b", BRANCH, str(root))
    base = run_git(repo_root, "rev-parse", "HEAD").strip()
    return LinkedWorktree(repo_root=repo_root, root=root, branch=BRANCH, base=base), older


def op_request(
    op: str,
    worktree: LinkedWorktree,
    *,
    root: Path | str | None = None,
    timeout_s: float = 60.0,
    op_key: str | None = None,
    **params: object,
) -> WorkspaceOpRequest:
    """Build the request the host dispatcher would hand a handler for ``worktree``."""
    wire_params = {"repo_root": str(worktree.repo_root), "branch": worktree.branch, **params}
    return WorkspaceOpRequest(
        op=op,
        root=str(worktree.root if root is None else root),
        params=MappingProxyType(wire_params),
        timeout_s=timeout_s,
        op_key=op_key,
        deadline=time.monotonic() + timeout_s,
    )


def expect_op_error(
    call: Callable[[], object], code: str, *, permanent: bool | None = None
) -> WorkspaceOpHandlerError:
    """Run ``call`` and return the handler error it raises with ``code``."""
    with pytest.raises(WorkspaceOpHandlerError) as caught:
        call()
    error = caught.value
    assert error.code == code, error.message
    if permanent is not None:
        assert error.permanent is permanent, error.message
    return error


def write_stub_git(directory: Path, script: str) -> Path:
    """Write an executable ``git`` stand-in running the POSIX shell ``script``."""
    directory.mkdir(parents=True, exist_ok=True)
    stub = directory / "git"
    stub.write_text(f"#!/bin/sh\n{script}\n")
    stub.chmod(0o755)
    return stub
