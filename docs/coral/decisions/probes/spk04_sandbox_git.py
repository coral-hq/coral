"""SPK-04 spike 8: can a sandboxed shell run git write ops in a linked worktree?

A standalone script, not a test: pytest does not collect it, nothing imports it
and no CI job runs it. Rerun it from the repository root on each sandbox
backend (it uses the platform default: ``darwin_seatbelt`` on macOS,
``linux_bwrap`` on Linux):

    uv run --no-sync python docs/coral/decisions/probes/spk04_sandbox_git.py

Pass ``--git /opt/homebrew/bin/git`` to probe another git binary, such as
Homebrew's in place of the Xcode shim at ``/usr/bin/git``.

It builds a throwaway repo with a linked worktree on ``coral/r-probe/base`` and
checks, outside any sandbox, where that worktree's index and common dir live.
It then runs git through Omnigent's ``create_os_environment`` with the default
sandbox and no network, as a writer (``write_paths: ["."]`` plus a probe-only
directory outside the worktree for the temporary index) and as a reviewer
(``write_paths: []``), each under two read configurations:

- ``default``: what a step session gets today, with no git-specific grants;
- ``git_dirs_readable``: the worktree's ``.git`` file unmasked and the common
  dir readable, so only write access is left in question. This answers a
  question; it is not a configuration to deploy, since a writer could then
  rewrite ``.git``.

Each run tries status, hash-object without ``-w`` (only "does git run"; L1 itself
hashes in Python), ``mktemp``, add, commit, a temp-index ``write-tree``,
``reset --hard`` and the contract's ``clean -fd``, all with K13's mandatory
``-c`` hardening. The ``omnigent`` package directory is
an extra read root, so an editable checkout outside the sandbox's default read
roots can start its helper.

A run's verdict is ``pass`` when every git command exits 0, ``blocked`` when
even ``git status`` fails, and ``fail`` otherwise; the ``mktemp`` row reports
``$TMPDIR`` and is left out of the verdict. The top-level verdict is the
writer's under ``git_dirs_readable``: whether sandboxed commits are possible at
all. The JSON names no machine paths or user names.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import getpass
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The probe imports Omnigent's sandbox from this checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

import omnigent
from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec
from omnigent.inner.os_env import create_os_environment
from omnigent.inner.sandbox import _default_sandbox_for_platform

_REPO_ROOT = Path(__file__).resolve().parents[4]
_RERUN = "uv run --no-sync python docs/coral/decisions/probes/spk04_sandbox_git.py"
_BRANCH = "coral/r-probe/base"
_PATHSPEC = ". ':(exclude).coral/runtime/**'"
_HARDENING = (
    "-c core.hooksPath=/dev/null -c core.fsmonitor=false -c commit.gpgSign=false -c gc.auto=0 "
    "-c trailer.separators=:"
)
# Setup git outside the sandbox reads no global or system config.
_SETUP_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
_ROLES = {"writer": ["."], "reviewer": []}
_READ_CONFIGS = ("default", "git_dirs_readable")
_TIMEOUT_S = 60


def _commands(git_binary: str, index_dir: Path) -> dict[str, str]:
    git = f"{git_binary} {_HARDENING}"
    identity = "-c user.name=probe -c user.email=probe@example.invalid"
    # Probe only: a fresh file in the probe's index dir, so $TMPDIR cannot decide the row.
    template = shlex.quote(str(index_dir / "index.XXXXXX"))
    temp_index = (
        f'idx=$(mktemp {template}) && cp "$({git} rev-parse --git-path index)" "$idx" && '
        f'GIT_INDEX_FILE="$idx" {git} add -A -- {_PATHSPEC} && '
        f'GIT_INDEX_FILE="$idx" {git} write-tree >/dev/null; rc=$?; rm -f "$idx"; exit $rc'
    )
    return {
        "status": f"{git} status --porcelain=v2 -z --untracked-files=all >/dev/null",
        "hash_object": f"{git} hash-object --no-filters -- file.txt >/dev/null",
        "mktemp": "mktemp >/dev/null",
        "add": f"{git} add -A -- {_PATHSPEC}",
        "commit": f"{git} {identity} commit -q -m probe",
        "temp_index_write_tree": temp_index,
        "reset_hard": f"{git} reset -q --hard HEAD",
        "clean_fd": f"{git} clean -q -fd -e /.coral/runtime/ -- .",
    }


class _Scrubber:
    """Replace machine paths and the user name in probe output."""

    def __init__(self, root: Path) -> None:
        pairs = [
            (root, "<tmp>"),
            (Path(tempfile.gettempdir()), "<TMPDIR>"),
            (Path(omnigent.__file__).parent, "<omnigent>"),
            (_REPO_ROOT, "<repo>"),
            (Path.home(), "~"),
        ]
        self._pairs: list[tuple[str, str]] = []
        # Most specific first; the longer form first, so /private/var wins over /var.
        for path, placeholder in pairs:
            for form in sorted({str(path.resolve()), str(path)}, key=len, reverse=True):
                self._pairs.append((form, placeholder))
        self._pairs.append((getpass.getuser(), "<user>"))

    def __call__(self, text: str) -> str:
        for value, placeholder in self._pairs:
            text = text.replace(value, placeholder)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return " | ".join(line[:300] for line in lines[-2:])


def _git(cwd: Path, git: str, *argv: str) -> str:
    return subprocess.run(
        [git, "-c", "core.hooksPath=/dev/null", *argv],
        cwd=cwd,
        env=_SETUP_ENV,
        check=True,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
    ).stdout.strip()


def _make_repo(root: Path, git: str) -> tuple[Path, Path]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, git, "init", "-q", "-b", "main")
    (repo / "file.txt").write_text("one\n")
    _git(repo, git, "add", "file.txt")
    identity = ["-c", "user.name=probe", "-c", "user.email=probe@example.invalid"]
    _git(repo, git, *identity, "commit", "-qm", "init")
    worktree = root / "repo-worktrees" / "coral-r-probe-base"
    _git(repo, git, "worktree", "add", "-q", "-b", _BRANCH, str(worktree))
    return repo, worktree


def _structure(repo: Path, worktree: Path, git: str, scrub: _Scrubber) -> dict[str, object]:
    """Where a linked worktree keeps its index and objects, read without a sandbox."""
    index = (worktree / _git(worktree, git, "rev-parse", "--git-path", "index")).resolve()
    common = (worktree / _git(worktree, git, "rev-parse", "--git-common-dir")).resolve()
    main_git = (repo / ".git").resolve()
    return {
        "git_path_index": scrub(str(index)),
        "git_common_dir": scrub(str(common)),
        "index_inside_main_git_dir": index.is_relative_to(main_git),
        "index_inside_worktree": index.is_relative_to(worktree.resolve()),
        "common_dir_is_main_git_dir": common == main_git,
    }


async def _run_matrix(
    worktree: Path,
    common_dir: Path,
    index_dir: Path,
    role: str,
    read_config: str,
    git: str,
    scrub: _Scrubber,
) -> dict[str, object]:
    readable = read_config == "git_dirs_readable"
    sandbox = OSEnvSandboxSpec(
        type=_default_sandbox_for_platform().type,
        write_paths=[*_ROLES[role], str(index_dir)] if role == "writer" else [],
        read_paths=[str(common_dir)] if readable else None,
        cwd_allow_hidden=[".git"] if readable else None,
        allow_network=False,
    )
    package_root = Path(omnigent.__file__).resolve().parent
    try:
        env = create_os_environment(
            OSEnvSpec(cwd=str(worktree), sandbox=sandbox), additional_read_roots=[package_root]
        )
    except (OSError, RuntimeError, ValueError) as exc:  # e.g. no bwrap on PATH
        return {"verdict": "blocked", "missing": scrub(f"{type(exc).__name__}: {exc}")}
    assert env is not None
    results: dict[str, dict[str, object]] = {}
    try:
        for name, command in _commands(shlex.quote(git), index_dir).items():
            (worktree / "file.txt").write_text(f"edit for {name}\n")
            (worktree / "untracked_dir").mkdir(exist_ok=True)
            (worktree / "untracked_dir" / "new.txt").write_text("new\n")
            outcome = await env.shell(command, timeout=_TIMEOUT_S)
            results[name] = {
                "exit_code": outcome.get("exit_code"),
                "timed_out": outcome.get("timed_out"),
                "stderr": scrub(str(outcome.get("stderr") or outcome.get("error") or "")),
            }
    finally:
        env.close()
    git_rows = [entry for name, entry in results.items() if name != "mktemp"]
    if all(entry["exit_code"] == 0 for entry in git_rows):
        verdict = "pass"
    elif results["status"]["exit_code"] != 0:
        verdict = "blocked"
    else:
        verdict = "fail"
    return {"verdict": verdict, "commands": results}


async def _run_all(
    worktree: Path, common_dir: Path, index_dir: Path, git: str, scrub: _Scrubber
) -> dict[str, dict[str, object]]:
    return {
        f"{role}/{read_config}": await _run_matrix(
            worktree, common_dir, index_dir, role, read_config, git, scrub
        )
        for read_config in _READ_CONFIGS
        for role in _ROLES
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--git", default="git", help="git binary to probe (default: git on PATH)")
    args = parser.parse_args()
    git = shutil.which(args.git)
    if git is None:
        print(json.dumps({"spike": 8, "verdict": "blocked", "missing": f"{args.git} not found"}))
        return 0
    root = Path(tempfile.mkdtemp(prefix="spk04-"))
    try:
        scrub = _Scrubber(root)
        repo, worktree = _make_repo(root, git)
        structure = _structure(repo, worktree, git, scrub)
        index_dir = root / "probe-index"
        index_dir.mkdir()
        runs = asyncio.run(_run_all(worktree, (repo / ".git").resolve(), index_dir, git, scrub))
        report = {
            "spike": 8,
            "verdict": runs["writer/git_dirs_readable"]["verdict"],
            "backend": _default_sandbox_for_platform().type,
            "platform": f"{platform.system()} {platform.machine()}",
            "git": scrub(_git(root, git, "--version")),
            "git_binary": scrub(git),
            "date": datetime.datetime.now(datetime.UTC).date().isoformat(),
            "structure": structure,
            "runs": runs,
            "rerun": _RERUN,
        }
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
