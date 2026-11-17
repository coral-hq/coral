"""Coral's host git runner: argv only, fresh environment, deadline, output caps, lock retries."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from coral.omni.host.ops import _git
from coral.omni.host.ops._git import Git, host_git, locate_git
from coral.omni.host.ops._locks import root_lock
from coral.omni.host.ops._target import resolve_pinned
from coral.workspace.ops import GIT_HARDENING_CONFIG
from omnigent.host.workspace_ops import WorkspaceOpHandlerError
from tests._helpers.polling import poll_until
from tests.coral.omni.host.ops._worktrees import (
    LinkedWorktree,
    expect_op_error,
    write_stub_git,
)


def _stub(tmp_path: Path, script: str, *, deadline_s: float = 30.0) -> Git:
    stub = write_stub_git(tmp_path / "stub-bin", script)
    return Git(executable=str(stub), deadline=time.monotonic() + deadline_s, cwd=str(tmp_path))


def _process_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


# ── Process and environment ─────────────────────────────────────────────────


def test_git_runs_by_argv_with_hardening_first_and_a_fresh_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_TRACE", "1")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.hookspath'='/tmp/evil'")
    monkeypatch.setenv("CORAL_TEST_INHERITED", "secret")
    git = replace(
        _stub(tmp_path, f'env > "{tmp_path}/env"; printf "%s\\n" "$@" > "{tmp_path}/argv"'),
        config_args=("-c", "core.eol=lf"),
        git_dir="/repo/.git/worktrees/w",
        work_tree="/repo-worktrees/w",
    )

    git.run("status", "--porcelain=v2", "a b; $(touch pwned)")

    argv = (tmp_path / "argv").read_text().splitlines()
    assert argv == [
        *_git.HOST_HARDENING_CONFIG,
        "-c",
        "core.eol=lf",
        "status",
        "--porcelain=v2",
        "a b; $(touch pwned)",
    ]
    assert not (tmp_path / "pwned").exists()
    # K13's hardening comes first, then the settings that keep git out of submodules.
    assert _git.HOST_HARDENING_CONFIG[: len(GIT_HARDENING_CONFIG)] == GIT_HARDENING_CONFIG
    for setting in (
        "submodule.recurse=false",
        "status.submoduleSummary=false",
        "diff.submodule=short",
        "log.showSignature=false",
    ):
        assert setting in _git.HOST_HARDENING_CONFIG
    env = dict(
        line.split("=", 1) for line in (tmp_path / "env").read_text().splitlines() if "=" in line
    )
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_ATTR_NOSYSTEM"] == "1"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert env["GIT_NO_LAZY_FETCH"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["LC_ALL"] == "C"
    assert env["GIT_DIR"] == "/repo/.git/worktrees/w"
    assert env["GIT_WORK_TREE"] == "/repo-worktrees/w"
    assert env["HOME"] == os.environ["HOME"]
    assert "GIT_TRACE" not in env
    assert "GIT_CONFIG_PARAMETERS" not in env
    assert "CORAL_TEST_INHERITED" not in env
    assert str(tmp_path / "stub-bin") in env["PATH"].split(":")


def test_a_failing_git_call_reports_its_exit_code_and_stderr_tail(tmp_path: Path) -> None:
    git = _stub(
        tmp_path,
        'printf "%05000d" 0 >&2; printf "\\033[31mforged\\n" >&2; '
        'echo "fatal: the real cause" >&2; exit 3',
    )

    error = expect_op_error(lambda: git.run("status"), "workspace.git_failed", permanent=False)

    assert error.exit_code == 3
    assert error.message.endswith("fatal: the real cause")
    assert len(error.message) <= 2100
    # Control characters from git's output are escaped, never passed on.
    assert "\\x1b[31mforged\\n" in error.message
    assert error.message.isprintable()
    assert git.run("status", ok_exit_codes=(3,)).exit_code == 3


def test_input_and_output_larger_than_a_pipe_buffer_do_not_deadlock(tmp_path: Path) -> None:
    git = _stub(tmp_path, "cat")
    message = os.urandom(1024 * 1024)

    assert git.run("commit-tree", input=message).stdout == message


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_over_its_cap_fails_the_call(tmp_path: Path, stream: str) -> None:
    size = _git.MAX_STDOUT_BYTES if stream == "stdout" else _git.MAX_STDERR_BYTES
    redirect = "" if stream == "stdout" else " >&2"
    git = _stub(tmp_path, f"head -c {size + 1} /dev/zero{redirect}")

    error = expect_op_error(lambda: git.run("cat-file"), "workspace.git_failed")
    assert stream in error.message


def test_the_deadline_stops_git_and_its_process_group(tmp_path: Path) -> None:
    # The stub outlives the deadline by far; only the outcome is asserted, not the timing.
    git = _stub(tmp_path, f'sleep 300 & echo $! > "{tmp_path}/child"; wait', deadline_s=2)

    expect_op_error(lambda: git.run("status"), "workspace.timeout")

    child = int((tmp_path / "child").read_text())
    poll_until(lambda: _process_gone(child), timeout_s=10, interval_s=0.05)


def test_a_timed_out_git_gets_sigterm_first_so_it_can_remove_its_lock(tmp_path: Path) -> None:
    lock = tmp_path / "index.lock"
    git = _stub(
        tmp_path,
        f'trap \'rm -f "{lock}"; exit 143\' TERM; : > "{lock}"; while :; do sleep 0.05; done',
        deadline_s=2,
    )

    expect_op_error(lambda: git.run("reset"), "workspace.timeout")

    assert not lock.exists()


def test_git_under_a_jail_that_exits_first_still_gets_its_sigterm_grace(tmp_path: Path) -> None:
    # As under bwrap: the direct child dies on SIGTERM at once, while git, its child
    # in the same process group, still needs a moment to remove its lock.
    lock, ready = tmp_path / "index.lock", tmp_path / "ready"
    git_like = f'trap \'sleep 0.5; rm -f "{lock}"; exit 143\' TERM; : > "{lock}"; : > "{ready}"'
    git = _stub(
        tmp_path,
        f"( {git_like}; while :; do sleep 0.05; done ) & wait",
        deadline_s=2,
    )

    expect_op_error(lambda: git.run("reset"), "workspace.timeout")

    assert ready.exists()
    assert not lock.exists()


def test_a_git_that_ignores_sigterm_is_killed(tmp_path: Path) -> None:
    git = _stub(
        tmp_path,
        f"trap '' TERM; echo $$ > \"{tmp_path}/pid\"; while :; do sleep 0.05; done",
        deadline_s=2,
    )

    expect_op_error(lambda: git.run("reset"), "workspace.timeout")

    pid = int((tmp_path / "pid").read_text())
    poll_until(lambda: _process_gone(pid), timeout_s=10, interval_s=0.05)


def test_a_call_after_the_deadline_never_starts_git(tmp_path: Path) -> None:
    git = _stub(tmp_path, f'touch "{tmp_path}/ran"', deadline_s=-1)

    expect_op_error(lambda: git.run("status"), "workspace.timeout")
    assert not (tmp_path / "ran").exists()


# ── Executable and version ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ('echo "git version 2.31.8"', "2.31.8"),
        ('echo "not git at all"', "version"),
    ],
    ids=["too-old", "unparseable"],
)
def test_locate_git_refuses_an_unusable_git(tmp_path: Path, script: str, reason: str) -> None:
    stub = write_stub_git(tmp_path / "bin", script)

    error = expect_op_error(
        lambda: locate_git(str(stub.parent), deadline=time.monotonic() + 30),
        "workspace.backend_unavailable",
        permanent=True,
    )
    assert reason in error.message


def test_locate_git_accepts_2_32_and_newer(tmp_path: Path) -> None:
    for version, parsed in (
        ("2.32.0", (2, 32)),
        ("2.54.0 (Apple Git-157)", (2, 54)),
        ("3.0.1.windows.1", (3, 0)),
    ):
        stub = write_stub_git(tmp_path / version.split()[0], f'echo "git version {version}"')
        located = locate_git(str(stub.parent), deadline=time.monotonic() + 30)
        assert located == (os.path.realpath(stub), parsed)


def test_a_git_inside_the_op_paths_never_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "worktree"
    marker = tmp_path / "ran"
    planted = write_stub_git(worktree / "bin", f'touch "{marker}"; echo "git version 2.54.0"')

    # Found on the search path: refused before even the version check runs it.
    expect_op_error(
        lambda: locate_git(
            str(planted.parent), deadline=time.monotonic() + 30, outside=(str(worktree),)
        ),
        "workspace.backend_unavailable",
        permanent=True,
    )
    # Cached for the process by an earlier op: every op checks it again.
    monkeypatch.setattr(_git, "_resolved_git", (str(planted), (2, 54)))
    with pytest.raises(WorkspaceOpHandlerError) as caught:
        host_git(time.monotonic() + 30, outside=(str(worktree),))
    assert caught.value.code == "workspace.backend_unavailable"
    assert not marker.exists()


def test_host_git_resolves_once_per_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = write_stub_git(
        tmp_path / "bin", f'echo x >> "{tmp_path}/calls"; echo "git version 2.40.0"'
    )
    monkeypatch.setenv("PATH", str(stub.parent))
    monkeypatch.setattr(_git, "_resolved_git", None)

    first = host_git(time.monotonic() + 30)
    second = host_git(time.monotonic() + 30)

    assert first.executable == second.executable == os.path.realpath(stub)
    assert first.version == (2, 40)
    assert (tmp_path / "calls").read_text() == "x\n"


# ── Lock contention ─────────────────────────────────────────────────────────


def _pinned(worktree: LinkedWorktree, *, deadline_s: float = 600.0) -> Git:
    return resolve_pinned(
        host_git(time.monotonic() + deadline_s),
        repo_root=str(worktree.repo_root),
        root=str(worktree.root),
        branch=worktree.branch,
        write=True,
    ).git


def test_a_held_lock_is_retried_until_it_is_released(worktree: LinkedWorktree) -> None:
    lock = worktree.common_dir / "refs" / "coral" / "held.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("")
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            lock.unlink()

    git = replace(_pinned(worktree), sleep=sleep)
    git.run_locking("update-ref", "refs/coral/held", worktree.base)

    assert sleeps == [0.25, 0.5]
    assert git.run("rev-parse", "refs/coral/held").stdout.decode().strip() == worktree.base


def test_a_lock_held_past_the_budget_times_out_and_is_never_removed(
    worktree: LinkedWorktree,
) -> None:
    lock = worktree.admin_dir / "index.lock"
    lock.write_text("")
    sleeps: list[float] = []
    git = replace(_pinned(worktree), sleep=sleeps.append)

    error = expect_op_error(lambda: git.run_locking("reset", "-q"), "workspace.timeout")

    assert lock.exists()
    assert str(lock) in error.message
    assert "remove it only if no git process is running" in error.message
    assert error.permanent is False
    assert sleeps[:5] == [0.25, 0.5, 1.0, 2.0, 2.0]
    assert sum(sleeps) == pytest.approx(_git.LOCK_BUDGET_S)


def test_the_lock_budget_never_outlasts_the_op_deadline(worktree: LinkedWorktree) -> None:
    lock = worktree.admin_dir / "index.lock"
    lock.write_text("")
    sleeps: list[float] = []
    git = replace(_pinned(worktree, deadline_s=5.0), sleep=sleeps.append)

    expect_op_error(lambda: git.run_locking("reset", "-q"), "workspace.timeout")

    assert 0 < sum(sleeps) <= 5.0
    assert lock.exists()


def test_failures_other_than_a_held_lock_are_not_retried(worktree: LinkedWorktree) -> None:
    sleeps: list[float] = []
    git = replace(_pinned(worktree), sleep=sleeps.append)

    expect_op_error(
        lambda: git.run_locking("update-ref", "refs/coral/x", "1" * 40), "workspace.git_failed"
    )
    assert sleeps == []


# ── One op per worktree ─────────────────────────────────────────────────────


def _enter(root: str) -> None:
    with root_lock(root):
        pass


def test_a_busy_worktree_refuses_another_op_at_once(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "alias").symlink_to(root, target_is_directory=True)
    holding = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with root_lock(str(root)):
            holding.set()
            release.wait(30)

    holder = threading.Thread(target=hold)
    holder.start()
    assert holding.wait(30)
    # The holder lets go after 2 s: an op that waited would get the worktree then.
    letting_go = threading.Timer(2.0, release.set)
    letting_go.start()
    try:
        # No waiting: a waiting op would hold one of the host's op slots.
        for spelling in (root, tmp_path / "alias"):
            error = expect_op_error(
                lambda spelling=spelling: _enter(str(spelling)), "workspace.timeout"
            )
            assert error.permanent is False
            assert "another workspace op is still running on this worktree" in error.message
        _enter(str(tmp_path / "other"))
    finally:
        letting_go.join(30)
        holder.join(30)
    _enter(str(root))
