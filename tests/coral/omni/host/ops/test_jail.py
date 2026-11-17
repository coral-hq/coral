"""The write jail around every git process of Coral's host ops.

Unit tests build the jail commands for both platforms and the jail an op
gets. The rest run real git in this host's jail (``sandbox-exec`` on macOS,
``bwrap`` on Linux): a symlinked directory inside the worktree must not let
git write, delete or read outside the paths the op needs, even when an agent
process swaps one in while the op runs. They skip only on a developer host
without a working jail tool; under CI they fail instead, so CI proves the jail.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from coral.omni.host.ops import _git, _jail, _target
from coral.omni.host.ops._git import Git, host_git
from coral.omni.host.ops._jail import Jail, JailTool, JailUnavailable, locate_jail_tool
from coral.workspace.ops import WORKSPACE_ERROR_CODES
from omnigent.host.workspace_ops import WorkspaceOpHandler, WorkspaceOpHandlerError
from tests._helpers.polling import poll_until
from tests.coral.omni.host.ops._worktrees import (
    INITIAL_FILES,
    LinkedWorktree,
    expect_op_error,
    op_request,
    requests_for_every_op,
    run_git,
    write_stub_git,
)

Handlers = Mapping[str, WorkspaceOpHandler]
SANDBOX_EXEC = JailTool("sandbox-exec", "/usr/bin/sandbox-exec")
BWRAP = JailTool("bwrap", "/usr/bin/bwrap")
_WRITABLE_GIT_DIRS = (
    "objects",
    "refs/heads/coral",
    "refs/coral",
    "logs/refs/heads/coral",
    "logs/refs/coral",
)


def _working_jail_tool() -> JailTool:
    """This host's jail tool once it has run git; without one the test skips, or fails on CI."""
    git = host_git(time.monotonic() + 60)

    def version_failure(jail: Jail) -> str | None:
        ran = replace(git, cwd="/", jail=jail).run("--version", check=False)
        return None if ran.exit_code == 0 else ran.stderr.decode(errors="replace")

    try:
        return _jail.checked_jail_tool(version_failure, refuse_inside=lambda tool: None)
    except JailUnavailable as exc:
        if os.environ.get("CI"):
            pytest.fail(f"CI must run the write jail: {exc}")
        pytest.skip(f"this host has no working write jail: {exc}")


def _op_git(worktree: LinkedWorktree, temp_dir: Path) -> Git:
    """Host git pinned to ``worktree`` in the jail a WRITE op would get (not moved aside)."""
    git = host_git(time.monotonic() + 60)
    jail = _target.op_jail(
        git,
        root=str(worktree.root),
        repo_root=str(worktree.repo_root),
        temp_dir=str(temp_dir.resolve()),
        admin_dir=str(worktree.admin_dir),
    )
    assert jail is not None
    return replace(
        git,
        cwd=str(worktree.root),
        git_dir=str(worktree.admin_dir),
        work_tree=str(worktree.root),
        jail=jail,
    )


@pytest.fixture
def without_move_aside(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the jail on its own: an unconfined racer would follow a moved tree anyway."""
    monkeypatch.setattr(_target, "move_aside_enabled", lambda: False)


# ── Commands ────────────────────────────────────────────────────────────────


def test_sandbox_exec_takes_every_path_as_a_parameter_never_as_profile_text() -> None:
    jail = Jail(
        tool=SANDBOX_EXEC,
        writable=('/w/ro"ot', "/w/repo/.git/objects", "/t/op"),
        writable_files=("/w/repo/.git/packed-refs",),
        home="/h",
        readable=("/h/code/root", "/t/op"),
    )

    command = jail.command(["/usr/bin/git", "status"], cwd="/h/code/root")

    profile = (
        "(version 1)(allow default)(deny file-write* (require-not (require-any"
        ' (literal "/dev/null")'
        ' (subpath (param "W0")) (subpath (param "W1")) (subpath (param "W2"))'
        ' (literal (param "F0")))))'
        '(deny file-read-data (require-all (subpath (param "HOME_DIR")) (require-not (require-any'
        ' (subpath (param "R0")) (subpath (param "R1")) (literal (param "A0"))'
        ' (literal (param "A1"))))))'
    )
    assert command == [
        "/usr/bin/sandbox-exec",
        *("-D", 'W0=/w/ro"ot', "-D", "W1=/w/repo/.git/objects", "-D", "W2=/t/op"),
        *("-D", "F0=/w/repo/.git/packed-refs"),
        *("-D", "HOME_DIR=/h", "-D", "R0=/h/code/root", "-D", "R1=/t/op"),
        # The directories above a readable path stay listable, so getcwd() works.
        *("-D", "A0=/h", "-D", "A1=/h/code"),
        "-p",
        profile,
        "/usr/bin/git",
        "status",
    ]


def test_sandbox_exec_without_a_home_limits_writes_only() -> None:
    jail = Jail(tool=SANDBOX_EXEC, writable=("/t/op",))

    assert jail.command(["git", "--version"], cwd=None) == [
        "/usr/bin/sandbox-exec",
        "-D",
        "W0=/t/op",
        "-p",
        "(version 1)(allow default)(deny file-write* (require-not (require-any"
        ' (literal "/dev/null") (subpath (param "W0")))))',
        "git",
        "--version",
    ]


def test_bwrap_binds_the_writable_paths_over_a_read_only_root_and_hides_home(
    tmp_path: Path,
) -> None:
    home = str(tmp_path / "h")
    op = str(tmp_path / "op")
    for directory in ("h/code/root", "h/code/repo/.git/objects", "h/dotfiles", "op"):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "h" / "dotfiles" / "gitignore").write_text("*.log\n")
    jail = Jail(
        tool=BWRAP,
        writable=(f"{home}/code/root", f"{home}/code/repo/.git/objects", op),
        writable_files=(f"{home}/code/repo/.git/packed-refs",),
        home=home,
        readable=(
            f"{home}/code/root",
            f"{home}/code/repo/.git",
            op,
            f"{home}/dotfiles/gitignore",
            "/opt/git",
        ),
        # ~/.gitignore_global is a symlink to ~/dotfiles/gitignore.
        aliases=((f"{home}/.gitignore_global", f"{home}/dotfiles/gitignore"),),
    )

    command = jail.command(["/usr/bin/git", "status"], cwd=f"{home}/code/root")

    assert command == [
        "/usr/bin/bwrap",
        *("--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", home),
        # Readable paths under home come back read-only, a symlinked one at both
        # its target and its spelling; writable ones get a read-write bind.
        *("--ro-bind-try", f"{home}/code/repo/.git", f"{home}/code/repo/.git"),
        *("--ro-bind-try", f"{home}/dotfiles/gitignore", f"{home}/dotfiles/gitignore"),
        *("--ro-bind-try", f"{home}/dotfiles/gitignore", f"{home}/.gitignore_global"),
        *("--bind-try", f"{home}/code/root", f"{home}/code/root"),
        *("--bind-try", f"{home}/code/repo/.git/objects", f"{home}/code/repo/.git/objects"),
        *("--bind-try", op, op),
        *("--chdir", f"{home}/code/root", "--"),
        "/usr/bin/git",
        "status",
    ]
    # No new session or pid namespace: git stays in the group the deadline kills.
    assert "--new-session" not in command
    assert "--unshare-pid" not in command


def test_bwrap_never_binds_a_missing_or_non_directory_path(tmp_path: Path) -> None:
    real = tmp_path / "refs-coral"
    real.mkdir()
    # A reftable store keeps a file at refs/heads, so refs/heads/coral is under a file.
    a_file = tmp_path / "refs-heads"
    a_file.write_text("this repository uses the reftable format\n")
    link = tmp_path / "linked"
    link.symlink_to(real)
    home = tmp_path / "h"
    writable = (real, a_file, a_file / "coral", link, tmp_path / "missing")
    jail = Jail(
        tool=BWRAP,
        writable=tuple(str(path) for path in writable),
        home=str(home),
        readable=(str(home / "gone"),),
    )

    command = jail.command(["/usr/bin/git", "status"], cwd=None)

    assert command == [
        "/usr/bin/bwrap",
        *("--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", str(home)),
        *("--bind-try", str(real), str(real)),
        "--",
        "/usr/bin/git",
        "status",
    ]


def test_a_symlinked_readable_path_keeps_its_spelling(tmp_path: Path) -> None:
    target = tmp_path / "dotfiles" / "gitignore"
    target.parent.mkdir()
    target.write_text("*.log\n")
    link = tmp_path / ".gitignore_global"
    link.symlink_to(target)

    jail = Jail(tool=BWRAP, writable=()).allowing_reads(str(link))

    canonical = os.path.realpath(target)
    assert jail.readable == (canonical,)
    assert jail.aliases == ((str(link), canonical),)


def test_each_system_has_its_jail_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_jail.os, "access", lambda path, mode: path == "/usr/bin/sandbox-exec")
    monkeypatch.setattr(_jail.shutil, "which", lambda name: "/usr/bin/bwrap")
    monkeypatch.setattr(_jail.os.path, "realpath", lambda path: path)

    assert locate_jail_tool("Darwin") == SANDBOX_EXEC
    assert locate_jail_tool("Linux") == BWRAP
    assert locate_jail_tool("Windows") is None
    monkeypatch.setattr(_jail.shutil, "which", lambda name: None)
    assert locate_jail_tool("Linux") is None
    assert "bubblewrap" in _jail.required_tool("Linux")
    assert "/usr/bin/sandbox-exec" in _jail.required_tool("Darwin")


def test_a_write_op_jail_opens_only_what_git_writes_and_reads(
    worktree: LinkedWorktree,
    tmp_path: Path,
    git_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_jail, "_checked_tool", BWRAP)
    temp_dir = tmp_path / "op"
    temp_dir.mkdir()
    git = host_git(time.monotonic() + 60)
    common = str(worktree.common_dir)

    write = _target.op_jail(
        git,
        root=str(worktree.root),
        repo_root=str(worktree.repo_root),
        temp_dir=str(temp_dir),
        admin_dir=str(worktree.admin_dir),
    )
    read = _target.op_jail(
        git, root=str(worktree.root), repo_root=str(worktree.repo_root), temp_dir=str(temp_dir)
    )

    assert write is not None and read is not None
    assert write.writable == (
        str(worktree.root),
        *(os.path.join(common, name) for name in _WRITABLE_GIT_DIRS),
        str(worktree.admin_dir),
        str(temp_dir),
    )
    assert write.writable_files == (
        os.path.join(common, "packed-refs"),
        os.path.join(common, "packed-refs.lock"),
    )
    for name in _WRITABLE_GIT_DIRS:
        assert (worktree.common_dir / name).is_dir(), name
    assert read.writable == (str(temp_dir),)
    assert read.writable_files == ()
    for jail in (write, read):
        assert jail.home == os.path.realpath(git_home)
        # Nothing of the user's own config: global config is /dev/null for the ops.
        assert not any(path.startswith(f"{jail.home}/") for path in jail.readable)


@pytest.mark.parametrize("planted", ["file", "symlink"])
def test_a_write_jail_refuses_a_ref_directory_that_is_not_a_real_directory(
    worktree: LinkedWorktree, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, planted: str
) -> None:
    monkeypatch.setattr(_jail, "_checked_tool", BWRAP)
    temp_dir = tmp_path / "op"
    temp_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # refs/coral is missing in a fresh repository; here something else holds its place.
    path = worktree.common_dir / "refs" / "coral"
    if planted == "file":
        path.write_text("not a directory\n")
    else:
        path.symlink_to(elsewhere)

    with pytest.raises(WorkspaceOpHandlerError) as caught:
        _target.op_jail(
            host_git(time.monotonic() + 60),
            root=str(worktree.root),
            repo_root=str(worktree.repo_root),
            temp_dir=str(temp_dir),
            admin_dir=str(worktree.admin_dir),
        )

    error = caught.value
    assert (error.code, error.permanent) == ("workspace.backend_unavailable", True)
    assert "refs/coral" in error.message
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize("home", [None, "/"], ids=["unset", "root"])
def test_write_ops_refuse_without_a_home_directory(
    worktree: LinkedWorktree,
    handlers: Handlers,
    monkeypatch: pytest.MonkeyPatch,
    home: str | None,
) -> None:
    _working_jail_tool()
    if home is None:
        monkeypatch.delenv("HOME")
    else:
        monkeypatch.setenv("HOME", home)
    worktree.write("README.md", b"edited\n")
    requests = requests_for_every_op(worktree)

    for op in ("commit", "salvage", "reset"):
        error = expect_op_error(
            lambda op=op: handlers[op](requests[op]),
            "workspace.backend_unavailable",
            permanent=True,
        )
        assert "$HOME" in error.message
    handlers["head"](requests["head"])

    assert run_git(worktree.repo_root, "rev-parse", worktree.branch).strip() == worktree.base
    assert (worktree.root / "README.md").read_bytes() == b"edited\n"


# ── Fail closed ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool", [None, JailTool("sandbox-exec", "/usr/bin/false")])
def test_write_ops_refuse_without_a_working_jail_and_read_ops_run_bare(
    worktree: LinkedWorktree,
    handlers: Handlers,
    monkeypatch: pytest.MonkeyPatch,
    tool: JailTool | None,
) -> None:
    monkeypatch.setattr(_jail, "_checked_tool", None)
    monkeypatch.setattr(_jail, "locate_jail_tool", lambda system=None: tool)
    worktree.write("README.md", b"edited\n")
    requests = requests_for_every_op(worktree)

    for op in ("commit", "salvage", "reset"):
        error = expect_op_error(
            lambda op=op: handlers[op](requests[op]),
            "workspace.capability_unavailable",
            permanent=True,
        )
        assert _jail.required_tool() in error.message
        assert ("cannot run git here" in error.message) is (tool is not None)
    for op in ("head", "diff_stat", "read", "fingerprint"):
        handlers[op](requests[op])

    assert run_git(worktree.root, "rev-parse", "HEAD").strip() == worktree.base
    assert (worktree.root / "README.md").read_bytes() == b"edited\n"


def test_a_jail_tool_inside_the_worktree_never_runs(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "ran"
    planted = write_stub_git(worktree.root / "bin", f'touch "{marker}"')
    monkeypatch.setattr(_jail, "_checked_tool", None)
    monkeypatch.setattr(
        _jail, "locate_jail_tool", lambda system=None: JailTool("bwrap", str(planted))
    )
    worktree.write("README.md", b"edited\n")

    error = expect_op_error(
        lambda: handlers["commit"](requests_for_every_op(worktree)["commit"]),
        "workspace.backend_unavailable",
        permanent=True,
    )

    assert "bwrap at" in error.message
    assert not marker.exists()
    assert run_git(worktree.repo_root, "rev-parse", worktree.branch).strip() == worktree.base


# ── Real jail ───────────────────────────────────────────────────────────────


def test_every_git_process_of_an_op_runs_in_its_jail(
    worktree: LinkedWorktree, handlers: Handlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _working_jail_tool()
    started: list[list[str | bytes]] = []
    jails: list[Jail] = []
    popen = _git.subprocess.Popen
    command = Jail.command

    def recording_popen(argv: list[str | bytes], *args: object, **kwargs: object) -> object:
        started.append(list(argv))
        return popen(argv, *args, **kwargs)  # type: ignore[call-overload]

    def recording_command(self: Jail, argv: list[str | bytes], *, cwd: str | None) -> list:
        jails.append(self)
        return command(self, argv, cwd=cwd)

    monkeypatch.setattr(_git.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(Jail, "command", recording_command)
    worktree.write("README.md", b"edited\n")
    common = str(worktree.common_dir)

    for op, request in requests_for_every_op(worktree).items():
        started.clear()
        jails.clear()
        handlers[op](request)
        assert started, op
        for argv in started:
            # Only the once-per-process version probe of the git binary runs bare.
            assert argv[0] == tool.executable or argv[-1] == "--version", (op, argv)
        limited = [jail for jail in jails if jail.home is not None]
        assert limited, op
        for jail in limited:
            # Never the whole common dir: no hooks/, config, info/ or other refs.
            assert common not in jail.writable, op
        # The refusal checks run in the READ jail (the temp dir only); a WRITE op's
        # write jail comes after them.
        writable_counts = [len(jail.writable) for jail in limited]
        if op in ("commit", "salvage", "reset"):
            checks = writable_counts.index(8)
            assert set(writable_counts[:checks]) == {1}, op
            assert set(writable_counts[checks:]) == {8}, op
        else:
            assert set(writable_counts) == {1}, op


def test_jailed_git_cannot_write_delete_or_read_through_a_symlinked_directory(
    worktree: LinkedWorktree, tmp_path: Path, git_home: Path
) -> None:
    _working_jail_tool()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("precious\n")
    (git_home / "secret.txt").write_text("secret\n")
    (worktree.root / "out").symlink_to(outside)
    (worktree.root / "home").symlink_to(git_home)
    temp_dir = tmp_path / "op"
    temp_dir.mkdir()
    git = _op_git(worktree, temp_dir)

    bare = replace(git, git_dir=None, work_tree=None)
    wrote = bare.run("init", "-q", str(worktree.root / "out" / "planted"), check=False)
    # A work tree reached through the link: clean would unlink outside's files.
    through = str(worktree.root / "out")
    deleted = replace(git, work_tree=through, cwd=through).run("clean", "-fdq", check=False)
    read = git.run("hash-object", str(worktree.root / "home" / "secret.txt"), check=False)

    assert wrote.exit_code != 0
    assert deleted.exit_code != 0
    assert read.exit_code != 0
    assert sorted(path.name for path in outside.iterdir()) == ["precious.txt"]
    assert (git_home / "secret.txt").read_text() == "secret\n"
    secret_blob = run_git(worktree.root, "hash-object", "--stdin", input=b"secret\n").strip()
    assert secret_blob.encode() not in read.stdout


def test_jailed_git_writes_only_the_repository_paths_a_write_op_needs(
    worktree: LinkedWorktree, tmp_path: Path
) -> None:
    tool = _working_jail_tool()
    temp_dir = tmp_path / "op"
    temp_dir.mkdir()
    git = _op_git(worktree, temp_dir)
    assert git.jail is not None
    common = worktree.common_dir
    config_before = (common / "config").read_bytes()

    tag = git.run("update-ref", "refs/tags/v1", worktree.base, check=False)
    other = git.run("update-ref", "refs/heads/main-copy", worktree.base, check=False)
    configured = git.run("config", "core.planted", "yes", check=False)
    hook = subprocess.run(
        git.jail.command(["/usr/bin/touch", str(common / "hooks" / "pre-commit")], cwd=None),
        capture_output=True,
        check=False,
    )
    coral_ref = git.run("update-ref", "refs/coral/salvage/k-1", worktree.base, check=False)
    branch = git.run("update-ref", f"refs/heads/{worktree.branch}", worktree.base, check=False)

    assert (tag.exit_code, other.exit_code, configured.exit_code) != (0, 0, 0)
    assert tag.exit_code != 0 and other.exit_code != 0 and configured.exit_code != 0
    assert hook.returncode != 0, tool
    assert not (common / "refs" / "tags" / "v1").exists()
    assert not (common / "refs" / "heads" / "main-copy").exists()
    assert not (common / "hooks" / "pre-commit").exists()
    assert (common / "config").read_bytes() == config_before
    assert (coral_ref.exit_code, branch.exit_code) == (0, 0)


def test_the_jail_keeps_git_exit_codes_and_the_deadline_kills_its_group(
    worktree: LinkedWorktree, tmp_path: Path
) -> None:
    _working_jail_tool()
    temp_dir = tmp_path / "op"
    temp_dir.mkdir()
    git = _op_git(worktree, temp_dir)

    quiet = git.run("rev-parse", "--verify", "--quiet", "refs/heads/none", check=False)
    loud = git.run("rev-parse", "--verify", "refs/heads/none", check=False)
    assert (quiet.exit_code, loud.exit_code) == (1, 128)

    # A stand-in git that outlives its deadline and leaves a child behind.
    child_file = temp_dir.resolve() / "child"
    stub = write_stub_git(tmp_path / "stub", f'sleep 300 & echo $! > "{child_file}"; wait')
    stuck = replace(git, executable=str(stub), deadline=time.monotonic() + 2)
    expect_op_error(lambda: stuck.run("status"), "workspace.timeout")

    child = int(child_file.read_text())
    poll_until(lambda: _process_gone(child), timeout_s=10, interval_s=0.05)


def test_the_jail_reads_only_the_user_files_git_consults(
    worktree: LinkedWorktree, git_home: Path
) -> None:
    _working_jail_tool()
    config_git = git_home / ".config" / "git"
    config_git.mkdir(parents=True)
    (config_git / "credentials").write_text("https://user:token@example.test\n")
    (config_git / "attributes").write_text("*.txt text\n")
    (git_home / "ignore-rules").write_text("*.log\n")
    (git_home / "repo-include").write_text("[core]\n\tabbrev = 12\n")
    (git_home / ".gitconfig").write_text(
        "[core]\n\texcludesFile = ~/ignore-rules\n[user]\n\ttoken = secret\n"
    )
    run_git(worktree.repo_root, "config", "include.path", str(git_home / "repo-include"))
    request = op_request("head", worktree)

    with _target.pinned(request, request.params, write=False) as target:
        jail = target.git.jail
        assert jail is not None
        home = os.path.realpath(git_home)
        under_home = sorted(
            os.path.relpath(path, home) for path in jail.readable if path.startswith(home + "/")
        )
        # The repository's include, the configured excludes file and the default
        # attributes file; never ~/.gitconfig or the rest of ~/.config/git.
        assert under_home == [".config/git/attributes", "ignore-rules", "repo-include"]
        for secret in (git_home / ".gitconfig", config_git / "credentials"):
            read = target.git.run("hash-object", str(secret), check=False)
            assert read.exit_code != 0, secret


def test_a_symlinked_global_excludes_file_still_applies_in_the_jail(
    worktree: LinkedWorktree, handlers: Handlers, git_home: Path
) -> None:
    _working_jail_tool()
    dotfiles = git_home / "dotfiles"
    dotfiles.mkdir()
    (dotfiles / "gitignore").write_text("*.log\n")
    (git_home / ".gitignore_global").symlink_to(dotfiles / "gitignore")
    (git_home / ".gitconfig").write_text("[core]\n\texcludesFile = ~/.gitignore_global\n")
    worktree.write("debug.log", b"ignored by the user's git\n")
    worktree.write("README.md", b"edited\n")

    committed = handlers["commit"](requests_for_every_op(worktree)["commit"])
    handlers["reset"](op_request("reset", worktree, op_key="k-r", commit=worktree.base))

    listed = run_git(worktree.root, "ls-tree", "-r", "--name-only", committed["commit"]).split()
    assert listed == sorted(INITIAL_FILES)
    assert (worktree.root / "debug.log").read_bytes() == b"ignored by the user's git\n"


# ── Races against a surviving agent process ─────────────────────────────────

# Swaps the directory git just created for a symlink to outside, again and again.
_CHECKOUT_RACER = """
import os, sys, time
d, outside, ready = sys.argv[1:4]
open(ready, "w").close()
end, count = time.monotonic() + 30, 0
while time.monotonic() < end:
    try:
        if os.path.isdir(d) and not os.path.islink(d):
            count += 1
            os.rename(d, f"{d}-moved-{count}")
            os.symlink(outside, d)
    except OSError:
        pass
"""

# Once clean has unlinked an entry of u/, swaps u/ for a symlink in one step.
_CLEAN_RACER = """
import ctypes, os, sys, time
u, outside, ready = sys.argv[1:4]
libc = ctypes.CDLL(None, use_errno=True)
link = os.path.join(os.path.dirname(u), ".coral", "runtime", "u.link")
os.makedirs(os.path.dirname(link), exist_ok=True)
os.symlink(outside, link)
def swap():
    if sys.platform == "darwin":
        return libc.renamex_np(u.encode(), link.encode(), 2)  # RENAME_SWAP
    return libc.renameat2(-100, u.encode(), -100, link.encode(), 2)  # RENAME_EXCHANGE
first = os.lstat(u).st_mtime_ns
open(ready, "w").close()
end = time.monotonic() + 30
while time.monotonic() < end:
    try:
        if os.lstat(u).st_mtime_ns != first:
            swap()
            break
    except OSError:
        pass
"""


def _race(
    racer: str, target: Path, outside: Path, tmp_path: Path, op: Callable[[], object]
) -> object:
    """Run ``op`` while ``racer`` swaps ``target`` for a symlink to ``outside``; its outcome."""
    tmp_path.mkdir(exist_ok=True)
    ready = tmp_path / "racer-ready"
    process = subprocess.Popen(
        [sys.executable, "-c", racer, str(target), str(outside), str(ready)]
    )
    try:
        poll_until(ready.exists, timeout_s=30, interval_s=0.01)
        # A raced op may fail; what it did outside the worktree is the question.
        try:
            return op()
        except WorkspaceOpHandlerError as exc:
            return exc
    finally:
        process.kill()
        process.wait()


def _assert_success_or_typed_failure(outcome: object, success: object) -> None:
    if isinstance(outcome, WorkspaceOpHandlerError):
        assert outcome.code in WORKSPACE_ERROR_CODES, outcome
    else:
        assert outcome == success


@pytest.mark.usefixtures("without_move_aside")
@pytest.mark.parametrize("into", ["outside", "hooks"])
def test_a_racing_symlink_swap_cannot_make_reset_write_outside_the_worktree(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, into: str
) -> None:
    _working_jail_tool()
    outside = tmp_path / "outside" if into == "outside" else worktree.common_dir / "hooks"
    outside.mkdir(exist_ok=True)
    before = sorted(os.listdir(outside))
    for index in range(3000):
        worktree.write(f"d/f{index:04}", b"PAYLOAD\n")
    # The executable hook the user's next commit would run, if it landed in hooks/.
    worktree.write("d/pre-commit", b"#!/bin/sh\ntouch planted\n")
    (worktree.root / "d" / "pre-commit").chmod(0o755)
    target = worktree.commit("target with d/")
    request = op_request("reset", worktree, op_key="k-r", commit=target)

    # The swap does not always land inside git's write loop (without the jail
    # about half of these runs write outside); the deterministic proof is
    # test_jailed_git_cannot_write_delete_or_read_through_a_symlinked_directory.
    for attempt in range(2):
        # Test setup only, after the last op returned: a raced git may leave its lock.
        (worktree.admin_dir / "index.lock").unlink(missing_ok=True)
        run_git(worktree.root, "reset", "-q", "--hard", worktree.base)
        run_git(worktree.root, "clean", "-fdq")
        outcome = _race(
            _CHECKOUT_RACER,
            worktree.root / "d",
            outside,
            tmp_path / f"attempt-{attempt}",
            lambda: handlers["reset"](request),
        )
        _assert_success_or_typed_failure(outcome, {"head": target})
        assert sorted(os.listdir(outside)) == before, attempt


@pytest.mark.usefixtures("without_move_aside")
@pytest.mark.parametrize("into", ["outside", "tags"])
def test_a_racing_symlink_swap_cannot_make_reset_delete_outside_the_worktree(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, into: str
) -> None:
    _working_jail_tool()
    outside = tmp_path / "outside" if into == "outside" else worktree.common_dir / "refs" / "tags"
    outside.mkdir(parents=True, exist_ok=True)
    names = [f"a{index:04}" for index in range(2000)]
    # As loose tags, the same names are the user's refs.
    content = f"{worktree.base}\n".encode() if into == "tags" else b"precious, outside\n"
    for name in names:
        worktree.write(f"u/{name}", b"untracked\n")
        (outside / name).write_bytes(content)
    request = op_request("reset", worktree, op_key="k-r", commit=worktree.base)

    reset = handlers["reset"]
    outcome = _race(_CLEAN_RACER, worktree.root / "u", outside, tmp_path, lambda: reset(request))

    _assert_success_or_typed_failure(outcome, {"head": worktree.base})
    assert sorted(os.listdir(outside)) == names
    assert {(outside / name).read_bytes() for name in names} == {content}


def _process_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False
