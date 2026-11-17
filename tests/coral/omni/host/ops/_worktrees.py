"""Real git worktrees and op requests for Coral's host workspace-op handler tests."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from coral.omni.host.ops._git import Git, GitResult
from coral.omni.process_map import DISABLE_HOST_ENTRY_POINTS_ENV
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


def run_git(
    cwd: Path, *args: str, env: Mapping[str, str] | None = None, input: bytes | None = None
) -> str:
    """Run test-setup git in ``cwd`` (with the test's isolated ``HOME``) and return stdout.

    :param env: Extra variables, e.g. ``GIT_INDEX_FILE``.
    :param input: Bytes for stdin.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env={**os.environ, **_SETUP_ENV, **(env or {})},
        input=input,
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


def make_repository(path: Path, files: Mapping[str, bytes] = INITIAL_FILES) -> str:
    """Create a repository at ``path`` with ``files`` committed on ``main``."""
    path.mkdir(parents=True)
    run_git(path, "init", "-q", "-b", "main")
    for name, content in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(content)
    run_git(path, "add", "-A")
    run_git(path, "commit", "-q", "-m", "initial")
    return run_git(path, "rev-parse", "HEAD").strip()


def make_linked_worktree(
    parent: Path, files: Mapping[str, bytes] = INITIAL_FILES, *, branch: str = BRANCH
) -> LinkedWorktree:
    """Lay out ``<parent>/repo``, with ``files`` at ``base``, and its linked worktree.

    The worktree is ``<parent>/repo-worktrees/coral-r-test-base`` on ``branch``.
    """
    parent = parent.resolve()
    repo_root = parent / "repo"
    base = make_repository(repo_root, files)
    root = parent / "repo-worktrees" / "coral-r-test-base"
    run_git(repo_root, "worktree", "add", "-q", "-b", branch, str(root))
    return LinkedWorktree(repo_root=repo_root, root=root, branch=branch, base=base)


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


def isolate_git_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> Path:
    """Point ``HOME`` at ``home`` (created) and drop inherited git settings.

    The handlers read the user's full git config from ``HOME``, so the
    developer's own ignores, attributes or identity must not reach the tests.
    """
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    for name in list(os.environ):
        if name.startswith("GIT_") or name == "XDG_CONFIG_HOME":
            monkeypatch.delenv(name)
    monkeypatch.delenv(DISABLE_HOST_ENTRY_POINTS_ENV, raising=False)
    return home


def add_submodule(worktree: LinkedWorktree) -> Path:
    """Record ``sub``, a repository inside the worktree, as a gitlink in the superproject."""
    sub = worktree.root / "sub"
    sub.mkdir()
    run_git(sub, "init", "-q", "-b", "main")
    (sub / "file.txt").write_bytes(b"one\n")
    run_git(sub, "add", "-A")
    run_git(sub, "commit", "-qm", "sub")
    # An agent's .gitmodules cannot turn the submodule check back on.
    worktree.write(
        ".gitmodules", b'[submodule "sub"]\n\tpath = sub\n\turl = ./sub\n\tignore = none\n'
    )
    worktree.commit("gitlink")
    return sub


def trace_git(monkeypatch: pytest.MonkeyPatch, trace: Path) -> None:
    """Record every git command the ops run, including any child git, in ``trace``.

    Git traces to its stderr, which the runner captures: a jailed git could not
    write a trace file outside the paths its jail allows.
    """
    environment = Git.environment
    run = Git.run
    monkeypatch.setattr(Git, "environment", lambda self: {**environment(self), "GIT_TRACE": "2"})

    def traced_run(self: Git, *argv: str | bytes, **kwargs: Any) -> GitResult:
        result = run(self, *argv, **kwargs)
        with trace.open("ab") as stream:
            stream.write(result.stderr)
        return result

    monkeypatch.setattr(Git, "run", traced_run)


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


def requests_for_every_op(
    worktree: LinkedWorktree, *, timeout_s: float = 60.0
) -> dict[str, WorkspaceOpRequest]:
    """One valid request per op Coral's handlers serve; each changes nothing on a clean tree."""
    return {
        "head": op_request("head", worktree, timeout_s=timeout_s),
        "diff_stat": op_request(
            "diff_stat", worktree, from_commit=worktree.base, to_commit=None, timeout_s=timeout_s
        ),
        "read": op_request(
            "read", worktree, path="README.md", at_commit=None, timeout_s=timeout_s
        ),
        "fingerprint": op_request("fingerprint", worktree, level="L1", timeout_s=timeout_s),
        "commit": op_request(
            "commit",
            worktree,
            op_key="k-commit",
            expected_head=worktree.base,
            message="m",
            timeout_s=timeout_s,
        ),
        "salvage": op_request("salvage", worktree, op_key="k-salvage", timeout_s=timeout_s),
        "reset": op_request(
            "reset", worktree, op_key="k-reset", commit=worktree.base, timeout_s=timeout_s
        ),
    }


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
