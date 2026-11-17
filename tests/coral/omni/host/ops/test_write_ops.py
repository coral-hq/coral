"""Coral's host WRITE ops on a real linked worktree: commit, salvage and reset.

These cover the K13 obligations the conformance suite cannot see on a real
backend: hardening, identity, the user's global excludes, the private index,
the staged tree against ``add -A``, records that survive a new process, the
commit retry that syncs the index, lock contention and a branch moved under
the op, symlinks out of the root, and nested repositories and submodules.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from textwrap import dedent
from types import MappingProxyType

import pytest

from coral.omni.host.ops import _target, _write_ops
from coral.omni.host.ops._git import LOCK_BUDGET_S
from coral.omni.host.ops._write_ops import write_handlers
from coral.workspace.ops import (
    FALLBACK_IDENTITY_EMAIL,
    FALLBACK_IDENTITY_NAME,
    WORKSPACE_PATHSPEC,
    commit_params_digest,
)
from omnigent.host.workspace_ops import WorkspaceOpHandler, WorkspaceOpRequest
from tests.coral.omni.host.ops._worktrees import (
    INITIAL_FILES,
    LinkedWorktree,
    add_submodule,
    expect_op_error,
    make_repository,
    op_request,
    run_git,
    trace_git,
)
from tests.host.test_startup_imports import _run_without_database_imports

Handlers = Mapping[str, WorkspaceOpHandler]
RUN_ID = "0a1b2c3d" * 4
ATTEMPT_ID = "attempt-1"


def _commit_request(
    worktree: LinkedWorktree,
    op_key: str = "k-1",
    *,
    expected_head: str | None = None,
    message: str = "step 1",
    trailers: Sequence[tuple[str, str]] = (),
    run_id: str | None = None,
    attempt_id: str | None = None,
    root: Path | str | None = None,
) -> WorkspaceOpRequest:
    return op_request(
        "commit",
        worktree,
        root=root,
        op_key=op_key,
        expected_head=worktree.base if expected_head is None else expected_head,
        message=message,
        trailers=[list(pair) for pair in trailers],
        run_id=run_id,
        attempt_id=attempt_id,
    )


def _salvage_request(worktree: LinkedWorktree, op_key: str = "k-s") -> WorkspaceOpRequest:
    return op_request("salvage", worktree, op_key=op_key)


def _reset_request(
    worktree: LinkedWorktree, commit: str, op_key: str = "k-r"
) -> WorkspaceOpRequest:
    return op_request("reset", worktree, op_key=op_key, commit=commit)


def _head(worktree: LinkedWorktree) -> str:
    return run_git(worktree.root, "rev-parse", "HEAD").strip()


def _commit_object(worktree: LinkedWorktree, commit: str) -> tuple[list[str], str]:
    """A commit's header lines and its exact message."""
    raw = run_git(worktree.root, "cat-file", "commit", commit)
    header, _blank, message = raw.partition("\n\n")
    return header.split("\n"), message


def _tree_paths(worktree: LinkedWorktree, commit: str) -> list[str]:
    return run_git(worktree.root, "ls-tree", "-r", "--name-only", "--full-tree", commit).split()


def _staged(worktree: LinkedWorktree) -> str:
    """Paths whose real index entry differs from HEAD."""
    return run_git(worktree.root, "diff-index", "--cached", "--name-only", "HEAD")


def _tree(worktree: LinkedWorktree, commit: str) -> str:
    return run_git(worktree.root, "rev-parse", f"{commit}^{{tree}}").strip()


# ── commit ──────────────────────────────────────────────────────────────────


def test_commit_writes_its_trailers_in_order_and_moves_the_branch_from_expected_head(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    worktree.write("README.md", b"edited\n")
    worktree.write("docs/new.md", b"new\n")
    trailers = (("Reviewed-By", "x"), ("Run", "r"))

    first = handlers["commit"](
        _commit_request(
            worktree,
            "k-1",
            message="Review: done",
            trailers=trailers,
            run_id=RUN_ID,
            attempt_id=ATTEMPT_ID,
        )
    )

    header, message = _commit_object(worktree, str(first["commit"]))
    digest = commit_params_digest(
        "Review: done", dict(trailers), run_id=RUN_ID, attempt_id=ATTEMPT_ID
    )
    assert first == {"commit": _head(worktree), "empty": False}
    assert [line for line in header if line.startswith("parent ")] == [f"parent {worktree.base}"]
    assert message == (
        "Review: done\n\nReviewed-By: x\nRun: r\n"
        f"Coral-Run: {RUN_ID}\nCoral-Attempt: {ATTEMPT_ID}\n"
        f"Coral-Op: k-1\nCoral-Op-Params: {digest}\nCoral-Hooks: skipped\n"
    )
    # Git itself reads the block as the commit's trailers.
    parsed = run_git(worktree.root, "log", "-1", "--format=%(trailers:only,unfold)", "HEAD")
    assert parsed.rstrip("\n").splitlines()[-3:] == [
        "Coral-Op: k-1",
        f"Coral-Op-Params: {digest}",
        "Coral-Hooks: skipped",
    ]
    assert (
        run_git(worktree.root, "rev-parse", f"refs/heads/{worktree.branch}").strip()
        == (first["commit"])
    )
    assert _staged(worktree) == ""
    assert (worktree.root / "README.md").read_bytes() == b"edited\n"

    # Without run and attempt ids the record is the op trailers alone.
    worktree.write("README.md", b"again\n")
    second = handlers["commit"](
        _commit_request(worktree, "k-2", expected_head=str(first["commit"]))
    )
    _header, message = _commit_object(worktree, str(second["commit"]))
    assert message == (
        "step 1\n\nCoral-Op: k-2\n"
        f"Coral-Op-Params: {commit_params_digest('step 1', {})}\nCoral-Hooks: skipped\n"
    )


@pytest.mark.parametrize("configured", [True, False], ids=["repository-config", "fallback"])
def test_commit_and_salvage_use_the_repository_identity_or_the_fallback(
    worktree: LinkedWorktree, handlers: Handlers, configured: bool
) -> None:
    expected = f"{FALLBACK_IDENTITY_NAME} <{FALLBACK_IDENTITY_EMAIL}>"
    if configured:
        run_git(worktree.repo_root, "config", "user.name", "Ada Lovelace")
        run_git(worktree.repo_root, "config", "user.email", "ada@example.test")
        expected = "Ada Lovelace <ada@example.test>"
    worktree.write("README.md", b"edited\n")

    salvaged = handlers["salvage"](_salvage_request(worktree))
    committed = handlers["commit"](_commit_request(worktree))

    for commit in (salvaged["commit"], committed["commit"]):
        identities = run_git(worktree.root, "log", "-1", "--format=%an <%ae>|%cn <%ce>", commit)
        assert identities.strip() == f"{expected}|{expected}"


def test_write_ops_run_no_hook_fsmonitor_or_signing_program(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path
) -> None:
    markers = tmp_path / "markers"
    markers.mkdir()

    def program(directory: Path, name: str) -> Path:
        script = directory / name
        script.write_text(f'#!/bin/sh\ntouch "{markers}/{directory.name}-{name}"\n')
        script.chmod(0o755)
        return script

    configured_hooks = tmp_path / "configured-hooks"
    configured_hooks.mkdir()
    for directory in (worktree.common_dir / "hooks", configured_hooks):
        directory.mkdir(exist_ok=True)
        for hook in (
            "pre-commit",
            "prepare-commit-msg",
            "commit-msg",
            "post-commit",
            "reference-transaction",
            "post-index-change",
            "post-checkout",
            "post-rewrite",
        ):
            program(directory, hook)
    settings = {
        "core.hooksPath": str(configured_hooks),
        "core.fsmonitor": str(program(tmp_path, "fsmonitor")),
        "commit.gpgSign": "true",
        "gpg.program": str(program(tmp_path, "gpg")),
        "log.showSignature": "true",
    }
    for key, value in settings.items():
        run_git(worktree.repo_root, "config", key, value)

    worktree.write("README.md", b"salvaged\n")
    handlers["salvage"](_salvage_request(worktree))
    committed = handlers["commit"](_commit_request(worktree))
    worktree.write("README.md", b"dirty\n")
    handlers["reset"](_reset_request(worktree, worktree.base))

    assert sorted(path.name for path in markers.iterdir()) == []
    header, _message = _commit_object(worktree, str(committed["commit"]))
    assert not any(line.startswith("gpgsig") for line in header)


def test_global_excludes_file_is_honoured_by_commit_and_salvage_and_kept_by_reset(
    worktree: LinkedWorktree, handlers: Handlers, git_home: Path
) -> None:
    (git_home / ".gitconfig").write_text("[core]\n\texcludesFile = ~/.gitignore_global\n")
    (git_home / ".gitignore_global").write_text("*.log\n")
    worktree.write("debug.log", b"ignored by the user's git\n")
    worktree.write("README.md", b"edited\n")

    salvaged = handlers["salvage"](_salvage_request(worktree))
    committed = handlers["commit"](_commit_request(worktree))
    handlers["reset"](_reset_request(worktree, worktree.base))

    for commit in (str(salvaged["commit"]), str(committed["commit"])):
        assert _tree_paths(worktree, commit) == ["README.md", "src/app.py"]
    assert (worktree.root / "debug.log").read_bytes() == b"ignored by the user's git\n"
    assert (worktree.root / "README.md").read_bytes() == INITIAL_FILES["README.md"]


def test_salvage_leaves_head_the_real_index_and_the_working_tree_byte_identical(
    worktree: LinkedWorktree,
) -> None:
    worktree.write("staged.txt", b"staged\n")
    run_git(worktree.root, "add", "staged.txt")
    worktree.write("README.md", b"unstaged\n")
    index = worktree.admin_dir / "index"
    before = index.read_bytes()
    before_mtime = index.stat().st_mtime_ns
    # Salvage never writes the real index: another git's index.lock does not delay it.
    lock = worktree.admin_dir / "index.lock"
    lock.write_text("")
    waits: list[float] = []

    result = write_handlers(sleep=waits.append)["salvage"](_salvage_request(worktree, "k-1"))

    commit = str(result["commit"])
    assert waits == []
    assert lock.exists()
    assert result["ref"] == "refs/coral/salvage/k-1"
    assert run_git(worktree.root, "rev-parse", "refs/coral/salvage/k-1").strip() == commit
    assert index.read_bytes() == before
    assert index.stat().st_mtime_ns == before_mtime
    assert _head(worktree) == worktree.base
    assert (worktree.root / "README.md").read_bytes() == b"unstaged\n"
    assert _tree_paths(worktree, commit) == ["README.md", "src/app.py", "staged.txt"]
    assert run_git(worktree.root, "show", f"{commit}:README.md") == "unstaged\n"
    header, message = _commit_object(worktree, commit)
    assert [line for line in header if line.startswith("parent ")] == [f"parent {worktree.base}"]
    assert message == "Coral salvage k-1\n\nCoral-Hooks: skipped\n"


def _add_all_tree(worktree: LinkedWorktree) -> str:
    """The tree ``git add -A`` would record now, staged by test git on a copy of the index."""
    index = worktree.repo_root.parent / "add-all-index"
    # copy2 keeps the index's mtime, so git's racy-entry check behaves as on the real one.
    shutil.copy2(worktree.admin_dir / "index", index)
    env = {"GIT_INDEX_FILE": str(index)}
    run_git(worktree.root, "add", "-A", "--", *WORKSPACE_PATHSPEC, env=env)
    return run_git(worktree.root, "write-tree", env=env).strip()


def _replace_with_symlink(path: Path, target: str) -> None:
    path.unlink()
    path.symlink_to(target)


def _replace_with_directory(worktree: LinkedWorktree) -> None:
    (worktree.root / "README.md").unlink()
    worktree.write("README.md/inner.txt", b"inner\n")


def _write_odd_names(worktree: LinkedWorktree) -> None:
    for name in ("-rf", "--", "a\nb", "tab\tname", ":(top)magic", "*", "[ab]", "back\\slash", "ü"):
        worktree.write(name, b"odd\n")
    worktree.write("-dir/--file", b"odd\n")


def _write_symlinks(worktree: LinkedWorktree) -> None:
    (worktree.root / "link").symlink_to("README.md")
    (worktree.root / "dangling").symlink_to("/nonexistent/target")
    (worktree.root / "outside").symlink_to(worktree.repo_root)


def _add_intent_to_add(worktree: LinkedWorktree) -> None:
    worktree.write("later.txt", b"later\n")
    run_git(worktree.root, "add", "-N", "later.txt")


def _replace_src_directory(worktree: LinkedWorktree, *, link: bool) -> None:
    shutil.rmtree(worktree.root / "src")
    if link:
        (worktree.root / "src").symlink_to(worktree.repo_root / "src")
    else:
        worktree.write("src", b"now a file\n")


def _untrack_and_ignore(worktree: LinkedWorktree) -> None:
    # How a user stops tracking a local file: it stays deleted from the commit.
    run_git(worktree.root, "rm", "-q", "--cached", "README.md")
    exclude = run_git(worktree.root, "rev-parse", "--git-path", "info/exclude").strip()
    with (worktree.root / exclude).open("a") as stream:
        stream.write("/README.md\n")
    worktree.write("README.md", b"local secret\n")


def _leave_a_deleted_by_us_conflict(worktree: LinkedWorktree) -> None:
    # Stages 1 and 3 only ("DU"): the index still holds the path, as a conflict.
    root = worktree.root
    base = run_git(root, "rev-parse", "HEAD:README.md").strip()
    theirs = run_git(root, "hash-object", "-w", "--stdin", input=b"theirs\n").strip()
    entries = (
        f"0 {'0' * 40}\tREADME.md\n100644 {base} 1\tREADME.md\n100644 {theirs} 3\tREADME.md\n"
    )
    run_git(root, "update-index", "--index-info", input=entries.encode())
    worktree.write("README.md", b"theirs\n")


_TREE_CHANGES: dict[str, Callable[[LinkedWorktree], object]] = {
    "unstaged-rename": lambda worktree: (worktree.root / "src/app.py").rename(
        worktree.root / "src/main.py"
    ),
    "staged-rename": lambda worktree: run_git(worktree.root, "mv", "src/app.py", "src/moved.py"),
    "executable-bit": lambda worktree: (worktree.root / "src/app.py").chmod(0o755),
    "symlinks": _write_symlinks,
    "file-replaced-by-symlink": lambda worktree: _replace_with_symlink(
        worktree.root / "README.md", "src/app.py"
    ),
    "file-replaced-by-directory": _replace_with_directory,
    "odd-names": _write_odd_names,
    "intent-to-add": _add_intent_to_add,
    "directory-replaced-by-file": lambda worktree: _replace_src_directory(worktree, link=False),
    "directory-replaced-by-symlink": lambda worktree: _replace_src_directory(worktree, link=True),
    "untracked-and-ignored": _untrack_and_ignore,
    "conflict-deleted-by-us": _leave_a_deleted_by_us_conflict,
}


@pytest.mark.parametrize("change", list(_TREE_CHANGES.values()), ids=list(_TREE_CHANGES))
def test_commit_and_salvage_record_exactly_the_tree_add_all_would(
    worktree: LinkedWorktree, handlers: Handlers, change: Callable[[LinkedWorktree], object]
) -> None:
    change(worktree)
    expected = _add_all_tree(worktree)
    index = worktree.admin_dir / "index"
    before = index.read_bytes()

    salvaged = handlers["salvage"](_salvage_request(worktree))
    assert index.read_bytes() == before
    committed = handlers["commit"](_commit_request(worktree))

    assert expected != _tree(worktree, worktree.base)
    assert _tree(worktree, str(salvaged["commit"])) == expected
    assert _tree(worktree, str(committed["commit"])) == expected
    assert _staged(worktree) == ""


def test_commit_and_salvage_records_are_found_by_a_fresh_process(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path
) -> None:
    worktree.write("README.md", b"committed\n")
    commit_request = _commit_request(worktree, "k-1", trailers=(("Run", "r"),), run_id=RUN_ID)
    committed = handlers["commit"](commit_request)
    worktree.write("README.md", b"salvaged\n")
    salvage_request = _salvage_request(worktree, "k-2")
    salvaged = handlers["salvage"](salvage_request)
    worktree.write("README.md", b"later\n")
    calls = [
        [request.op, request.root, dict(request.params), request.op_key]
        for request in (commit_request, salvage_request)
    ]
    # A new interpreter has no state of the first: only git's records answer.
    code = dedent("""\
        import json
        import time
        from types import MappingProxyType

        from coral.omni.host.ops import workspace_op_handlers
        from omnigent.host.workspace_ops import WorkspaceOpRequest

        calls, expected = json.loads(sys.argv[1]), json.loads(sys.argv[2])
        handlers = workspace_op_handlers()
        for (op, root, params, op_key), first in zip(calls, expected, strict=True):
            request = WorkspaceOpRequest(
                op=op,
                root=root,
                params=MappingProxyType(params),
                timeout_s=60.0,
                op_key=op_key,
                deadline=time.monotonic() + 60.0,
            )
            repeat = dict(handlers[op](request))
            assert repeat == first, (op, repeat, first)
        """)

    _run_without_database_imports(
        tmp_path, code, json.dumps(calls), json.dumps([dict(committed), dict(salvaged)])
    )

    assert _head(worktree) == committed["commit"]
    assert (worktree.root / "README.md").read_bytes() == b"later\n"


def test_staging_sees_a_same_size_edit_that_only_the_racy_check_catches(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    # Git trusts an entry's stat data unless the entry is as new as the index
    # file ("racily clean"); then it compares content. A private copy of the
    # index must keep that timestamp, or the edit below is staged as unchanged.
    run_git(worktree.repo_root, "config", "core.trustctime", "false")
    readme = worktree.root / "README.md"
    then = 1_000_000_000 * 10**9
    os.utime(readme, ns=(then, then))
    run_git(worktree.root, "update-index", "--refresh")
    readme.write_bytes(b"first\n")  # the size of "hello\n"
    os.utime(readme, ns=(then, then))
    os.utime(worktree.admin_dir / "index", ns=(then, then))
    status = run_git(worktree.root, "status", "--porcelain", env={"GIT_OPTIONAL_LOCKS": "0"})
    assert status == " M README.md\n"

    salvaged = handlers["salvage"](_salvage_request(worktree))
    committed = handlers["commit"](_commit_request(worktree))

    for commit in (salvaged["commit"], committed["commit"]):
        assert run_git(worktree.root, "show", f"{commit}:README.md") == "first\n"


def test_lock_contention_retries_then_times_out_without_deleting_the_lock(
    worktree: LinkedWorktree,
) -> None:
    worktree.write("README.md", b"edited\n")
    lock = worktree.admin_dir / "index.lock"
    lock.write_text("")
    request = _commit_request(worktree)
    waits: list[float] = []

    # Held throughout: update-ref moves the branch, then reset -q spends the whole
    # budget in injected sleeps waiting for index.lock, and the lock stays.
    error = expect_op_error(
        lambda: write_handlers(sleep=waits.append)["commit"](request),
        "workspace.timeout",
        permanent=False,
    )
    assert lock.exists()
    assert str(lock) in error.message
    assert "remove it only if no git process is running" in error.message
    assert sum(waits) == LOCK_BUDGET_S

    # The retry finds its record on HEAD, so it only syncs the index: the lock is
    # released after two waits, and the op succeeds without touching the lock itself.
    retry_waits: list[float] = []

    def release_after_two_waits(seconds: float) -> None:
        retry_waits.append(seconds)
        if len(retry_waits) == 2:
            lock.unlink()

    result = write_handlers(sleep=release_after_two_waits)["commit"](request)

    assert retry_waits == [0.25, 0.5]
    assert result == {"commit": _head(worktree), "empty": False}
    assert _staged(worktree) == ""


def test_a_branch_moved_while_commit_waits_for_its_lock_is_never_overwritten(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    worktree.write("README.md", b"edited\n")
    request = _commit_request(worktree)
    branch_ref = f"refs/heads/{worktree.branch}"
    lock = worktree.common_dir / f"{branch_ref}.lock"
    lock.write_text("")
    waits: list[float] = []

    # Another git holds the branch throughout: the op times out and the branch stays.
    error = expect_op_error(
        lambda: write_handlers(sleep=waits.append)["commit"](request),
        "workspace.timeout",
        permanent=False,
    )
    assert str(lock) in error.message
    assert lock.exists()
    assert sum(waits) == LOCK_BUDGET_S
    assert _head(worktree) == worktree.base

    # It releases the lock having moved the branch: the op must not commit over that.
    tree = _tree(worktree, worktree.base)
    theirs = run_git(worktree.root, "commit-tree", "-p", worktree.base, "-m", "theirs", tree)

    def move_the_branch(_seconds: float) -> None:
        lock.unlink()
        # From the main checkout: on macOS the worktree is moved aside while the op runs.
        run_git(worktree.repo_root, "update-ref", branch_ref, theirs.strip(), worktree.base)

    error = expect_op_error(
        lambda: write_handlers(sleep=move_the_branch)["commit"](request),
        "workspace.target_mismatch",
        permanent=False,
    )
    assert "moved to" in error.message
    assert _head(worktree) == theirs.strip()

    expect_op_error(lambda: handlers["commit"](request), "workspace.target_mismatch")
    assert _head(worktree) == theirs.strip()


def test_commit_retry_after_the_branch_moved_syncs_the_index_and_returns_the_same_commit(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    worktree.write("README.md", b"edited\n")
    worktree.write("docs/new.md", b"new\n")
    request = _commit_request(worktree)
    lock = worktree.admin_dir / "index.lock"
    lock.write_text("")
    # The first try moves the branch, then cannot take index.lock to sync the index.
    expect_op_error(
        lambda: write_handlers(sleep=lambda _seconds: None)["commit"](request),
        "workspace.timeout",
    )
    moved = _head(worktree)
    assert moved != worktree.base
    assert sorted(_staged(worktree).split()) == ["README.md", "docs/new.md"]
    lock.unlink()

    retried = handlers["commit"](request)

    assert retried == {"commit": moved, "empty": False}
    assert _staged(worktree) == ""
    assert run_git(worktree.root, "rev-list", "--count", f"{worktree.base}..HEAD").strip() == "1"


# ── reset ───────────────────────────────────────────────────────────────────


def test_reset_clears_an_unfinished_merge(worktree: LinkedWorktree, handlers: Handlers) -> None:
    (worktree.repo_root / "README.md").write_bytes(b"theirs\n")
    run_git(worktree.repo_root, "commit", "-qam", "theirs")
    worktree.write("README.md", b"ours\n")
    ours = worktree.commit("ours")
    merge = subprocess.run(
        ["git", "merge", "--no-edit", "main"],
        cwd=worktree.root,
        env={**os.environ, "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "t@example.test"},
        capture_output=True,
        check=False,
    )
    assert merge.returncode != 0, merge.stdout
    assert handlers["head"](op_request("head", worktree))["merge_in_progress"] is True

    result = handlers["reset"](_reset_request(worktree, ours))

    assert result == {"head": ours}
    assert handlers["head"](op_request("head", worktree))["merge_in_progress"] is False
    assert (worktree.root / "README.md").read_bytes() == b"ours\n"
    assert run_git(worktree.root, "status", "--porcelain") == ""


def test_reset_at_its_commit_on_a_clean_tree_writes_nothing(worktree: LinkedWorktree) -> None:
    # Any write would need index.lock; a clean tree at the commit needs none.
    lock = worktree.admin_dir / "index.lock"
    lock.write_text("")
    waits: list[float] = []

    result = write_handlers(sleep=waits.append)["reset"](_reset_request(worktree, worktree.base))

    assert result == {"head": worktree.base}
    assert waits == []
    assert lock.exists()


def test_reset_never_reads_a_file_named_like_the_commit_as_a_path(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    worktree.write(worktree.base, b"planted\n")
    worktree.write("README.md", b"dirty\n")

    result = handlers["reset"](_reset_request(worktree, worktree.base))

    assert result == {"head": worktree.base}
    assert (worktree.root / "README.md").read_bytes() == INITIAL_FILES["README.md"]
    assert not (worktree.root / worktree.base).exists()


def test_reset_never_follows_a_symlink_out_of_the_worktree(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    for name in ("app.py", "README.md", "notes.txt"):
        (outside / name).write_bytes(b"outside\n")
        (outside / "sub" / name).write_bytes(b"outside\n")
    before = {path: path.read_bytes() for path in outside.rglob("*") if path.is_file()}
    # A tracked directory and a tracked file replaced by links out of the root.
    shutil.rmtree(worktree.root / "src")
    (worktree.root / "src").symlink_to(outside)
    _replace_with_symlink(worktree.root / "README.md", str(outside / "README.md"))
    # Untracked links out of the root, one inside an untracked directory.
    (worktree.root / "escape").symlink_to(outside)
    (worktree.root / "scratch").mkdir()
    (worktree.root / "scratch" / "up").symlink_to("../..")

    result = handlers["reset"](_reset_request(worktree, worktree.base))

    assert result == {"head": worktree.base}
    assert {path: path.read_bytes() for path in outside.rglob("*") if path.is_file()} == before
    assert sorted(os.listdir(worktree.root)) == [".git", "README.md", "src"]
    for path, content in INITIAL_FILES.items():
        assert not (worktree.root / path).is_symlink()
        assert (worktree.root / path).read_bytes() == content


def test_reset_aborts_a_pending_merge_even_when_the_tree_already_matches(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    (worktree.repo_root / "README.md").write_bytes(b"theirs\n")
    run_git(worktree.repo_root, "commit", "-qam", "theirs")
    # Keeps our tree but leaves MERGE_HEAD: status is clean and HEAD is unchanged.
    run_git(worktree.root, "merge", "-q", "-s", "ours", "--no-commit", "main")
    assert run_git(worktree.root, "status", "--porcelain") == ""
    assert handlers["head"](op_request("head", worktree))["merge_in_progress"] is True

    result = handlers["reset"](_reset_request(worktree, worktree.base))

    assert result == {"head": worktree.base}
    assert handlers["head"](op_request("head", worktree))["merge_in_progress"] is False


def test_reset_reads_status_over_its_cap_as_not_clean_and_resets(
    worktree: LinkedWorktree, handlers: Handlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_write_ops, "STATUS_OUTPUT_BYTES", 64)
    for index in range(20):
        worktree.write(f"untracked/u{index:02}.txt", b"untracked\n")

    result = handlers["reset"](_reset_request(worktree, worktree.base))

    assert result == {"head": worktree.base}
    assert not (worktree.root / "untracked").exists()


def test_write_ops_bound_a_status_stalled_on_a_submodule_fifo(
    worktree: LinkedWorktree, handlers: Handlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = add_submodule(worktree)
    gitlink = _head(worktree)
    # Git opens a submodule's HEAD with a blocking open(); the pin's listing never enters it.
    (sub / ".git" / "HEAD").unlink()
    os.mkfifo(sub / ".git" / "HEAD")
    worktree.write("README.md", b"edited\n")
    monkeypatch.setattr(_write_ops, "STATUS_LIMIT_S", 1.0)
    requests = {
        "commit": replace(_commit_request(worktree, expected_head=gitlink), timeout_s=20),
        "reset": replace(_reset_request(worktree, gitlink), timeout_s=20),
    }

    for name, request in requests.items():
        started = time.monotonic()
        request = replace(request, deadline=started + 20)
        error = expect_op_error(
            lambda request=request, name=name: handlers[name](request),
            "workspace.timeout",
            permanent=False,
        )
        assert "git status took over 1 s" in error.message, name
        # The 1 s limit ends it, not the op's 20 s deadline.
        assert time.monotonic() - started < 15, name
    assert _head(worktree) == gitlink


def test_staging_refuses_a_file_over_the_size_limit(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    with (worktree.root / "huge.bin").open("wb") as stream:
        stream.truncate(_write_ops.MAX_STAGED_FILE_BYTES + 1)  # sparse: no data written
    objects = sorted(path.name for path in (worktree.common_dir / "objects").iterdir())

    for request in (_salvage_request(worktree), _commit_request(worktree)):
        error = expect_op_error(
            lambda request=request: handlers[request.op](request),
            "workspace.git_failed",
            permanent=True,
        )
        assert "huge.bin" in error.message

    assert _head(worktree) == worktree.base
    assert sorted(path.name for path in (worktree.common_dir / "objects").iterdir()) == objects
    assert run_git(worktree.root, "for-each-ref", "refs/coral") == ""


@pytest.mark.parametrize("op", ["commit", "salvage", "reset"])
def test_write_ops_refuse_a_hook_defined_in_the_repository_config(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, op: str
) -> None:
    # core.hooksPath=/dev/null does not turn off config-defined hooks; the refusal must.
    marker = tmp_path / "ran"
    hook = tmp_path / "hook.sh"
    hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    hook.chmod(0o755)
    for event in ("reference-transaction", "post-index-change"):
        run_git(worktree.repo_root, "config", f"hook.coral-{event}.command", str(hook))
        run_git(worktree.repo_root, "config", f"hook.coral-{event}.event", event)
    worktree.write("README.md", b"edited\n")
    requests = {
        "commit": _commit_request(worktree),
        "salvage": _salvage_request(worktree),
        "reset": _reset_request(worktree, worktree.base),
    }

    error = expect_op_error(
        lambda: handlers[op](requests[op]), "workspace.backend_unavailable", permanent=True
    )

    assert "hook" in error.message
    assert not marker.exists()
    assert _head(worktree) == worktree.base
    assert (worktree.root / "README.md").read_bytes() == b"edited\n"
    assert run_git(worktree.root, "for-each-ref", "refs/coral") == ""


@pytest.mark.parametrize("where", ["op-temp-dir", "index-copy"])
def test_a_full_temp_disk_is_retryable(
    worktree: LinkedWorktree, handlers: Handlers, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    def disk_full(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    if where == "op-temp-dir":
        monkeypatch.setattr(_target.tempfile, "mkdtemp", disk_full)
    else:
        monkeypatch.setattr(_write_ops.shutil, "copyfileobj", disk_full)
    worktree.write("README.md", b"edited\n")

    for request in (_salvage_request(worktree), _commit_request(worktree)):
        error = expect_op_error(
            lambda request=request: handlers[request.op](request),
            "workspace.backend_unavailable",
            permanent=False,
        )
        assert "temp dir" in error.message

    assert _head(worktree) == worktree.base


def test_write_ops_work_on_a_packed_branch(worktree: LinkedWorktree, handlers: Handlers) -> None:
    # The jail opens only the coral/ refs, their logs and packed-refs in the common dir.
    (worktree.repo_root / "README.md").write_bytes(b"theirs\n")
    run_git(worktree.repo_root, "commit", "-qam", "theirs")
    run_git(worktree.repo_root, "pack-refs", "--all")
    branch_ref = worktree.common_dir / "refs" / "heads" / worktree.branch
    assert not branch_ref.exists()
    worktree.write("README.md", b"salvaged\n")

    salvaged = handlers["salvage"](_salvage_request(worktree))
    committed = handlers["commit"](_commit_request(worktree))
    run_git(worktree.root, "merge", "-q", "-s", "ours", "--no-commit", "main")
    reset = handlers["reset"](_reset_request(worktree, worktree.base))

    assert salvaged["commit"] is not None
    assert (
        run_git(worktree.repo_root, "rev-parse", "refs/coral/salvage/k-s").strip()
        == (salvaged["commit"])
    )
    assert committed["empty"] is False
    assert reset == {"head": worktree.base}
    assert _head(worktree) == worktree.base
    orig_head = worktree.admin_dir / "ORIG_HEAD"
    assert orig_head.read_text().strip() == committed["commit"]
    assert handlers["head"](op_request("head", worktree))["merge_in_progress"] is False


def test_write_ops_refuse_a_reftable_ref_store(
    handlers: Handlers, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_root = (tmp_path / "reftable").resolve() / "repo"
    repo_root.mkdir(parents=True)
    created = subprocess.run(
        ["git", "init", "-q", "-b", "main", "--ref-format=reftable"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip(f"this git has no reftable ref store: {created.stderr!r}")
    (repo_root / "README.md").write_bytes(b"hello\n")
    run_git(repo_root, "add", "-A")
    run_git(repo_root, "commit", "-q", "-m", "initial")
    root = repo_root.parent / "repo-worktrees" / "coral-r-test-base"
    run_git(repo_root, "worktree", "add", "-q", "-b", "coral/r-test/base", str(root))
    base = run_git(repo_root, "rev-parse", "HEAD").strip()
    worktree = LinkedWorktree(
        repo_root=repo_root, root=root, branch="coral/r-test/base", base=base
    )
    worktree.write("README.md", b"edited\n")

    # refs/heads is a file here: the refusal must come before the write jail binds refs.
    def no_write_jail(common_dir: str) -> tuple[str, ...]:
        raise AssertionError("the write jail was built for a reftable repository")

    monkeypatch.setattr(_target, "_writable_git_dirs", no_write_jail)
    error = expect_op_error(
        lambda: handlers["commit"](_commit_request(worktree)),
        "workspace.backend_unavailable",
        permanent=True,
    )

    assert "reftable" in error.message
    assert run_git(repo_root, "rev-parse", "coral/r-test/base").strip() == base


# ── Nested repositories and submodules ──────────────────────────────────────


def test_commit_and_salvage_leave_out_nested_repositories_the_agent_made(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path
) -> None:
    marker = tmp_path / "ran"
    vendored = worktree.root / "vendor" / "lib"
    make_repository(vendored)
    with (vendored / ".git" / "config").open("a") as stream:
        stream.write(f'[filter "evil"]\n\tclean = "touch {marker}; cat"\n')
    (vendored / ".gitattributes").write_text("* filter=evil\n")
    # A repository without a commit makes ``git add -A`` fail outright.
    unborn = worktree.root / "scratch"
    unborn.mkdir()
    run_git(unborn, "init", "-q")
    (unborn / "notes.txt").write_text("unborn\n")
    worktree.write("new.txt", b"new\n")

    salvaged = handlers["salvage"](_salvage_request(worktree))
    committed = handlers["commit"](_commit_request(worktree))

    for commit in (str(salvaged["commit"]), str(committed["commit"])):
        assert _tree_paths(worktree, commit) == ["README.md", "new.txt", "src/app.py"]
        assert "160000" not in run_git(worktree.root, "ls-tree", "-r", commit)
    assert "160000" not in run_git(worktree.root, "ls-files", "--stage")
    assert not marker.exists()
    assert (vendored / "README.md").exists()
    assert (unborn / "notes.txt").exists()


@pytest.mark.parametrize("layout", ["embedded-repository", "rewritten-submodule-gitfile"])
def test_write_ops_never_start_git_in_a_submodule_or_run_its_filter(
    worktree: LinkedWorktree,
    handlers: Handlers,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layout: str,
) -> None:
    sub = add_submodule(worktree)
    gitlink = _head(worktree)
    # The submodule's own commit moves too; commit and salvage record it from outside.
    (sub / "file.txt").write_bytes(b"two\n")
    run_git(sub, "commit", "-qam", "two")
    moved = run_git(sub, "rev-parse", "HEAD").strip()
    git_dir = sub / ".git"
    if layout == "rewritten-submodule-gitfile":
        # The agent keeps the submodule's repository elsewhere in its worktree. The
        # link is relative, so it still resolves while a WRITE op moves the tree aside.
        git_dir = worktree.root / "agent-gitdir"
        (sub / ".git").rename(git_dir)
        (sub / ".git").write_text("gitdir: ../agent-gitdir\n")
    marker = tmp_path / "ran"
    with (git_dir / "config").open("a") as stream:
        stream.write(f'[filter "evil"]\n\tclean = "touch {marker}; cat"\n')
    (sub / ".gitattributes").write_text("* filter=evil\n")
    # A stat-dirty file makes a submodule status re-hash it through the filter.
    os.utime(sub / "file.txt", ns=(1_000_000_000, 1_000_000_000))
    trace = tmp_path / "trace"
    trace_git(monkeypatch, trace)
    worktree.write("README.md", b"edited\n")
    requests = {
        "salvage": _salvage_request(worktree),
        "commit": _commit_request(worktree, expected_head=gitlink),
        "reset": _reset_request(worktree, gitlink),
    }

    results = {}
    for name, request in requests.items():
        trace.write_text("")
        results[name] = handlers[name](request)
        traced = trace.read_text()
        assert "built-in: git" in traced, name
        assert "run_command" not in traced, f"{name} started a child process: {traced}"
        assert not marker.exists(), f"{name} ran the submodule's filter"
    for name in ("salvage", "commit"):
        recorded = run_git(worktree.root, "rev-parse", f"{results[name]['commit']}:sub")
        assert recorded.strip() == moved, name


# ── Targets and params ──────────────────────────────────────────────────────


def test_write_ops_refuse_the_main_worktree(worktree: LinkedWorktree, handlers: Handlers) -> None:
    main = worktree.repo_root
    (main / "README.md").write_bytes(b"edited in the main checkout\n")
    requests = {
        "commit": _commit_request(worktree, root=main),
        "salvage": op_request("salvage", worktree, root=main, op_key="k-s"),
        "reset": op_request("reset", worktree, root=main, op_key="k-r", commit=worktree.base),
    }

    for op, request in requests.items():
        expect_op_error(
            lambda op=op, request=request: handlers[op](request), "workspace.target_mismatch"
        )

    assert run_git(main, "rev-parse", "HEAD").strip() == worktree.base
    assert (main / "README.md").read_bytes() == b"edited in the main checkout\n"
    assert run_git(main, "for-each-ref", "refs/coral") == ""


_BAD_COMMIT_PARAMS: dict[str, dict[str, object]] = {
    "expected-head-short": {"expected_head": "abc1234"},
    "message-blank": {"message": " \n"},
    "message-nul": {"message": "a\0b"},
    "message-lone-surrogate": {"message": "a\ud800b"},
    "message-not-a-string": {"message": 5},
    "trailers-not-a-list": {"trailers": "Run: r"},
    "trailer-not-a-pair": {"trailers": [["Run"]]},
    "trailer-repeated": {"trailers": [["Run", "a"], ["Run", "b"]]},
    "trailer-reserved": {"trailers": [["Coral-Op", "forged"]]},
    "trailer-line-break": {"trailers": [["Run", "a\nCoral-Op: forged"]]},
    "trailer-lone-surrogate": {"trailers": [["Run", "\udc80"]]},
    "trailer-key-not-a-string": {"trailers": [[["Run"], "r"]]},
    "trailer-value-not-a-string": {"trailers": [["Run", 5]]},
    "message-escape": {"message": "subject \x1b]0;title\x07"},
    "message-carriage-return": {"message": "a\r\nb"},
    "trailer-escape": {"trailers": [["Run", "\x1b[31mred"]]},
    "run-id-malformed": {"run_id": "Not An Id"},
    "attempt-id-not-a-string": {"attempt_id": 5},
    "unknown-param": {"amend": True},
}


@pytest.mark.parametrize("change", list(_BAD_COMMIT_PARAMS.values()), ids=list(_BAD_COMMIT_PARAMS))
def test_commit_params_are_revalidated_on_the_host(
    worktree: LinkedWorktree, handlers: Handlers, change: dict[str, object]
) -> None:
    worktree.write("README.md", b"edited\n")
    request = _commit_request(worktree)
    request = replace(request, params=MappingProxyType({**request.params, **change}))

    expect_op_error(
        lambda: handlers["commit"](request), "workspace.invalid_params", permanent=True
    )

    assert _head(worktree) == worktree.base


_BAD_REQUESTS: dict[str, Callable[[LinkedWorktree], WorkspaceOpRequest]] = {
    "commit-without-op-key": lambda worktree: replace(_commit_request(worktree), op_key=None),
    "salvage-without-op-key": lambda worktree: op_request("salvage", worktree),
    "reset-without-op-key": lambda worktree: op_request("reset", worktree, commit=worktree.base),
    "reset-commit-not-hex": lambda worktree: _reset_request(worktree, "HEAD"),
    "reset-without-commit": lambda worktree: op_request("reset", worktree, op_key="k-r"),
    "salvage-unknown-param": lambda worktree: op_request(
        "salvage", worktree, op_key="k-s", commit=worktree.base
    ),
}


@pytest.mark.parametrize("build", list(_BAD_REQUESTS.values()), ids=list(_BAD_REQUESTS))
def test_write_ops_need_their_op_key_and_params(
    worktree: LinkedWorktree,
    handlers: Handlers,
    build: Callable[[LinkedWorktree], WorkspaceOpRequest],
) -> None:
    worktree.write("README.md", b"edited\n")
    request = build(worktree)

    expect_op_error(
        lambda: handlers[request.op](request), "workspace.invalid_params", permanent=True
    )

    assert _head(worktree) == worktree.base
    assert (worktree.root / "README.md").read_bytes() == b"edited\n"
    assert run_git(worktree.root, "for-each-ref", "refs/coral") == ""
