"""Moving a worktree aside while a WRITE op's git works in it.

The first test is macOS's reason for it: a seatbelt-confined agent process
that outlived its session, with its cwd and a directory fd inside the
worktree, can write nothing in it once it is moved. The rest pin the
mechanics on any platform: recovery after an interrupted op, the refusal when
both copies exist, the tree back at its path after success, failure and
timeout, and the worktree lock following the moved tree.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from coral.omni.host.ops import _locks, _target, _write_ops
from coral.omni.host.ops._aside import aside_path, moved_aside
from coral.omni.host.ops._git import Git, GitResult
from coral.omni.host.ops._locks import root_lock
from omnigent.host.workspace_ops import WorkspaceOpHandler
from tests._helpers.polling import poll_until
from tests.coral.omni.host.ops._worktrees import (
    LinkedWorktree,
    add_submodule,
    expect_op_error,
    op_request,
    requests_for_every_op,
    run_git,
)

Handlers = Mapping[str, WorkspaceOpHandler]

# The agent's own sandbox, reduced to what matters here: writes only under its worktree.
_AGENT_PROFILE = (
    '(version 1)(allow default)(deny file-write* (require-not (subpath (param "ROOT"))))'
)
_AGENT = textwrap.dedent("""\
    import json, os, sys, time
    root = sys.argv[1]
    held = os.open("sub", os.O_RDONLY | os.O_DIRECTORY)
    open("ready", "w").close()
    while not os.path.exists("go"):
        time.sleep(0.02)
    attempts = {
        "new file by cwd": lambda: open("new.txt", "w").close(),
        "symlink by cwd": lambda: os.symlink("/etc", "link"),
        "new file by a held dir fd": lambda: os.close(
            os.open("planted", os.O_WRONLY | os.O_CREAT, 0o644, dir_fd=held)
        ),
        "symlink by a held dir fd": lambda: os.symlink("/etc", "link", dir_fd=held),
        "new file by the old path": lambda: open(os.path.join(root, "late.txt"), "w").close(),
    }
    results = {}
    for name, attempt in attempts.items():
        try:
            attempt()
            results[name] = "allowed"
        except OSError:
            results[name] = "refused"
    print(json.dumps(results))
    """)


@pytest.fixture
def move_aside(monkeypatch: pytest.MonkeyPatch) -> None:
    """Move WRITE ops' worktrees aside on this platform too (macOS does by default)."""
    monkeypatch.setattr(_target, "move_aside_enabled", lambda: True)


def _git_work_trees(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """The ``GIT_WORK_TREE`` of every git call the ops make from now on."""
    seen: list[str | None] = []
    run = Git.run

    def recording_run(self: Git, *argv: str | bytes, **kwargs: Any) -> GitResult:
        seen.append(self.work_tree)
        return run(self, *argv, **kwargs)

    monkeypatch.setattr(Git, "run", recording_run)
    return seen


def test_a_confined_process_loses_write_access_once_the_worktree_is_moved_aside(
    worktree: LinkedWorktree,
) -> None:
    if not os.access("/usr/bin/sandbox-exec", os.X_OK):
        pytest.skip("this test models macOS's seatbelt agent sandbox")
    root = worktree.root
    (root / "sub").mkdir()
    agent = subprocess.Popen(
        [
            "/usr/bin/sandbox-exec",
            *("-D", f"ROOT={root}", "-p", _AGENT_PROFILE),
            sys.executable,
            "-c",
            _AGENT,
            str(root),
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        poll_until((root / "ready").exists, timeout_s=30, interval_s=0.02)
        with moved_aside(str(root)) as aside:
            Path(aside, "go").write_text("")
            output, _ = agent.communicate(timeout=30)
    finally:
        agent.kill()
        agent.wait()

    assert json.loads(output) == {
        "new file by cwd": "refused",
        "symlink by cwd": "refused",
        "new file by a held dir fd": "refused",
        "symlink by a held dir fd": "refused",
        "new file by the old path": "refused",
    }
    assert sorted(os.listdir(root)) == [".git", "README.md", "go", "ready", "src", "sub"]
    assert os.listdir(root / "sub") == []


def test_write_ops_run_git_in_the_moved_worktree_and_put_it_back(
    worktree: LinkedWorktree,
    handlers: Handlers,
    monkeypatch: pytest.MonkeyPatch,
    move_aside: None,
) -> None:
    work_trees = _git_work_trees(monkeypatch)
    aside = aside_path(str(worktree.root))
    worktree.write("README.md", b"edited\n")

    # Success.
    committed = handlers["commit"](requests_for_every_op(worktree)["commit"])
    assert committed["empty"] is False
    assert {path for path in work_trees if path is not None} == {aside}
    assert worktree.root.is_dir() and not os.path.lexists(aside)

    # Failure.
    unknown = op_request("reset", worktree, op_key="k-r", commit="0" * 40)
    expect_op_error(lambda: handlers["reset"](unknown), "workspace.git_failed")
    assert worktree.root.is_dir() and not os.path.lexists(aside)

    # Timeout: a submodule's FIFO HEAD stalls status past its limit.
    sub = add_submodule(worktree)
    gitlink = run_git(worktree.repo_root, "rev-parse", worktree.branch).strip()
    (sub / ".git" / "HEAD").unlink()
    os.mkfifo(sub / ".git" / "HEAD")
    monkeypatch.setattr(_write_ops, "STATUS_LIMIT_S", 1.0)
    stalled = op_request("commit", worktree, op_key="k-c2", expected_head=gitlink, message="m")
    stalled = replace(stalled, deadline=time.monotonic() + 20)
    expect_op_error(lambda: handlers["commit"](stalled), "workspace.timeout")
    assert worktree.root.is_dir() and not os.path.lexists(aside)


def test_an_op_brings_back_a_worktree_an_interrupted_op_left_aside(
    worktree: LinkedWorktree, handlers: Handlers, move_aside: None
) -> None:
    aside = aside_path(str(worktree.root))
    requests = requests_for_every_op(worktree)

    for op in ("head", "commit"):
        os.rename(worktree.root, aside)  # as a host that died mid-op leaves it
        handlers[op](requests[op])
        assert worktree.root.is_dir(), op
        assert not os.path.lexists(aside), op


def _take_the_old_path(root: Path, kind: str) -> None:
    """Put what a surviving process (or a person) could at the worktree's old path."""
    if kind == "empty-directory":
        root.mkdir()
    elif kind == "directory-with-a-file":
        root.mkdir()
        (root / "planted.txt").write_text("planted\n")
    elif kind == "file":
        root.write_text("planted\n")
    else:
        root.symlink_to(root.parent)


def test_recovery_replaces_an_empty_directory_at_the_old_path(
    worktree: LinkedWorktree, handlers: Handlers, move_aside: None
) -> None:
    aside = aside_path(str(worktree.root))
    os.rename(worktree.root, aside)
    _take_the_old_path(worktree.root, "empty-directory")

    handlers["head"](op_request("head", worktree))

    assert sorted(os.listdir(worktree.root)) == [".git", "README.md", "src"]
    assert not os.path.lexists(aside)


@pytest.mark.parametrize("kind", ["directory-with-a-file", "file", "symlink"])
def test_anything_else_at_the_old_path_is_left_to_a_person(
    worktree: LinkedWorktree, handlers: Handlers, move_aside: None, kind: str
) -> None:
    aside = aside_path(str(worktree.root))
    os.rename(worktree.root, aside)
    _take_the_old_path(worktree.root, kind)
    requests = requests_for_every_op(worktree)

    for op in ("commit", "head"):
        error = expect_op_error(
            lambda op=op: handlers[op](requests[op]),
            "workspace.worktree_displaced",
            permanent=True,
        )
        assert str(worktree.root) in error.message
        assert aside in error.message

    assert os.path.lexists(worktree.root)
    assert sorted(os.listdir(aside)) == [".git", "README.md", "src"]


@pytest.mark.parametrize("old_path", ["missing", "empty-directory"])
def test_a_worktree_moved_aside_keeps_its_lock(
    worktree: LinkedWorktree, handlers: Handlers, move_aside: None, old_path: str
) -> None:
    aside = aside_path(str(worktree.root))
    os.rename(worktree.root, aside)
    if old_path == "empty-directory":
        _take_the_old_path(worktree.root, old_path)
    aside_identity = (os.stat(aside).st_dev, os.stat(aside).st_ino)

    assert _locks._root_key(str(worktree.root)) == aside_identity
    # An op running on the moved tree holds its lock: another op neither runs nor moves it back.
    with root_lock(str(worktree.root)):
        expect_op_error(
            lambda: handlers["head"](op_request("head", worktree)), "workspace.timeout"
        )
        assert os.path.isdir(aside)


def test_moving_back_replaces_an_empty_directory_but_never_a_new_tree(
    worktree: LinkedWorktree,
) -> None:
    root = str(worktree.root)

    with moved_aside(root):
        os.mkdir(root)  # what a surviving process can still do at the old path
    assert sorted(os.listdir(root)) == [".git", "README.md", "src"]

    error = expect_op_error(lambda: _recreate_during(root), "workspace.worktree_displaced")
    assert error.permanent is True
    assert os.listdir(root) == ["planted.txt"]
    assert sorted(os.listdir(aside_path(root))) == [".git", "README.md", "src"]


def _recreate_during(root: str) -> None:
    with moved_aside(root):
        os.mkdir(root)
        Path(root, "planted.txt").write_text("planted\n")
