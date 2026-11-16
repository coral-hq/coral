"""Coral's host READ ops on a real linked worktree: head, diff_stat, read and fingerprint(L1)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from coral.omni.host.ops import _locks, _read_ops, _target
from coral.omni.host.ops._files import read_in_root
from coral.omni.host.ops._locks import root_lock
from coral.workspace.ops import MAX_READ_BYTES
from omnigent.host.workspace_ops import (
    MAX_CONCURRENT_WORKSPACE_OPS,
    HostWorkspaceOpFrame,
    WorkspaceOpHandler,
    decode_workspace_op_frame,
    dispatch_workspace_op,
    encode_workspace_op_frame,
)
from tests._helpers.polling import poll_until_async
from tests.coral.omni.host.ops._worktrees import (
    LinkedWorktree,
    add_submodule,
    expect_op_error,
    make_linked_worktree,
    make_partial_clone_worktree,
    op_request,
    requests_for_every_op,
    run_git,
    trace_git,
)

Handlers = Mapping[str, WorkspaceOpHandler]
UNKNOWN_COMMIT = "0" * 40


def _head(handlers: Handlers, worktree: LinkedWorktree) -> Mapping[str, object]:
    return handlers["head"](op_request("head", worktree))


def _diff(handlers: Handlers, worktree: LinkedWorktree, **params: object) -> Mapping[str, object]:
    return handlers["diff_stat"](op_request("diff_stat", worktree, to_commit=None, **params))


def _read(
    handlers: Handlers, worktree: LinkedWorktree, path: object, at_commit: str | None = None
) -> Mapping[str, object]:
    return handlers["read"](op_request("read", worktree, path=path, at_commit=at_commit))


def _l1(handlers: Handlers, worktree: LinkedWorktree) -> Mapping[str, object]:
    return handlers["fingerprint"](op_request("fingerprint", worktree, level="L1"))


def _content(payload: Mapping[str, object]) -> bytes:
    content = base64.b64decode(str(payload["content_b64"]), validate=True)
    assert payload["sha256"] == hashlib.sha256(content).hexdigest()
    return content


# ── head ────────────────────────────────────────────────────────────────────


def test_head_reports_the_checked_out_branch_its_commit_and_an_unfinished_merge(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    assert _head(handlers, worktree) == {
        "head": worktree.base,
        "branch": "coral/r-test/base",
        "merge_in_progress": False,
    }

    # Someone else's unfinished merge leaves MERGE_HEAD in the worktree's own git dir.
    (worktree.admin_dir / "MERGE_HEAD").write_text(f"{worktree.base}\n")
    assert _head(handlers, worktree)["merge_in_progress"] is True
    (worktree.admin_dir / "MERGE_HEAD").unlink()

    run_git(worktree.root, "checkout", "-q", "--detach")
    assert _head(handlers, worktree) == {
        "head": worktree.base,
        "branch": None,
        "merge_in_progress": False,
    }


# ── diff_stat ───────────────────────────────────────────────────────────────


def test_diff_stat_counts_lines_between_commits_and_defaults_to_head(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    worktree.write("README.md", b"hello\nmore\n")
    worktree.write("docs/new.md", b"one\ntwo\n")
    # Coral's own runtime files never count, even when committed.
    worktree.write(".coral/runtime/state.json", b"{}\n")
    assert _diff(handlers, worktree, from_commit=worktree.base)["files_changed"] == 0
    first = worktree.commit("docs")

    to_head = _diff(handlers, worktree, from_commit=worktree.base)
    between = handlers["diff_stat"](
        op_request("diff_stat", worktree, from_commit=worktree.base, to_commit=first)
    )
    assert (
        to_head
        == between
        == {
            "files_changed": 2,
            "insertions": 3,
            "deletions": 0,
            "paths": ["README.md", "docs/new.md"],
        }
    )

    (worktree.root / "src/app.py").unlink()
    # A binary file counts as changed with 0 lines.
    worktree.write("image.bin", b"\x00\x01\x02\n")
    worktree.commit("delete")
    assert _diff(handlers, worktree, from_commit=first) == {
        "files_changed": 2,
        "insertions": 0,
        "deletions": 1,
        "paths": ["image.bin", "src/app.py"],
    }


def test_diff_stat_of_an_unknown_commit_fails(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    expect_op_error(
        lambda: _diff(handlers, worktree, from_commit=UNKNOWN_COMMIT), "workspace.git_failed"
    )


# ── read ────────────────────────────────────────────────────────────────────


def test_read_returns_exact_bytes_in_the_working_tree_and_at_a_commit(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    worktree.write("data.bin", b"\x00\xff\r\n")
    committed = worktree.commit("data")
    worktree.write("data.bin", b"changed")

    at_commit = _read(handlers, worktree, "data.bin", committed)
    working = _read(handlers, worktree, "data.bin")

    assert at_commit["path"] == working["path"] == "data.bin"
    assert _content(at_commit) == b"\x00\xff\r\n"
    assert _content(working) == b"changed"
    for at in (None, committed):
        expect_op_error(
            lambda at=at: _read(handlers, worktree, "absent.txt", at),
            "workspace.git_failed",
            permanent=False,
        )
    expect_op_error(
        lambda: _read(handlers, worktree, "README.md", UNKNOWN_COMMIT), "workspace.git_failed"
    )


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "/etc/passwd",
        "src/../../outside",
        "",
        "./README.md",
        "src//app.py",
        "src/",
        7,
        "a\0b",
        # Anything git keeps in a .git directory, however a file system spells it.
        ".git/config",
        "src/.GIT/HEAD",
        "nested/.Git/config",
        ".git./config",
        "git~1/config",
        ".g\u200cit/config",
    ],
)
def test_read_refuses_unsafe_paths_before_touching_the_tree(
    worktree: LinkedWorktree,
    handlers: Handlers,
    monkeypatch: pytest.MonkeyPatch,
    path: object,
) -> None:
    (worktree.root.parent / "outside").write_bytes(b"outside the root")

    def walk_must_not_run(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("an unsafe path reached the file walk")

    monkeypatch.setattr(_read_ops, "read_in_root", walk_must_not_run)
    for at in (None, worktree.base):
        expect_op_error(
            lambda at=at: _read(handlers, worktree, path, at),
            "workspace.invalid_params",
            permanent=True,
        )


def test_read_serves_names_that_only_start_like_git(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    for name in (".gitignore", ".github/workflows/ci.yml", ".gitx/file"):
        worktree.write(name, b"not git internals\n")
        assert _content(_read(handlers, worktree, name)) == b"not git internals\n"


def test_read_escapes_file_names_in_errors(worktree: LinkedWorktree, handlers: Handlers) -> None:
    error = expect_op_error(
        lambda: _read(handlers, worktree, "bad\x1b[31m\nFAKE: forged line"),
        "workspace.git_failed",
    )
    assert error.message.isprintable()
    assert "bad\\x1b[31m\\nFAKE: forged line" in error.message


def test_the_file_walk_stops_at_the_deadline(worktree: LinkedWorktree) -> None:
    expect_op_error(
        lambda: read_in_root(
            str(worktree.root), "src/app.py", max_bytes=100, deadline=time.monotonic() - 1
        ),
        "workspace.timeout",
    )


@pytest.mark.parametrize("kind", ["symlinked-directory", "symlinked-file", "fifo", "directory"])
def test_read_refuses_anything_but_a_regular_file_inside_the_root(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, kind: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"top secret")
    if kind == "symlinked-directory":
        (worktree.root / "escape").symlink_to(outside, target_is_directory=True)
        path = "escape/secret.txt"
    elif kind == "symlinked-file":
        (worktree.root / "link.txt").symlink_to(outside / "secret.txt")
        path = "link.txt"
    elif kind == "fifo":
        os.mkfifo(worktree.root / "pipe")
        path = "pipe"
    else:
        path = "src"

    error = expect_op_error(lambda: _read(handlers, worktree, path), "workspace.git_failed")
    assert "top secret" not in error.message


@pytest.mark.parametrize("path", ["link.txt", "src", "nested"])
def test_read_at_a_commit_refuses_anything_but_a_regular_file(
    worktree: LinkedWorktree, handlers: Handlers, path: str
) -> None:
    (worktree.root / "link.txt").symlink_to("README.md")
    # A gitlink: a commit of an embedded repository recorded in the tree.
    nested = worktree.root / "nested"
    nested.mkdir()
    run_git(nested, "init", "-q")
    run_git(nested, "commit", "-q", "--allow-empty", "-m", "nested")
    committed = worktree.commit("links")

    error = expect_op_error(
        lambda: _read(handlers, worktree, path, committed), "workspace.git_failed"
    )
    assert "is not a regular file" in error.message


def test_read_is_capped_so_its_result_fits_the_host_channel(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    cap = _read_ops.MAX_HOST_READ_BYTES
    assert cap < MAX_READ_BYTES
    worktree.write("big.bin", b"x" * (cap + 1))
    worktree.write("at-cap.bin", b"y" * cap)
    committed = worktree.commit("big")

    for at in (None, committed):
        error = expect_op_error(
            lambda at=at: _read(handlers, worktree, "big.bin", at),
            "workspace.git_failed",
            permanent=True,
        )
        assert str(cap) in error.message
        # A file of exactly the cap is served from the tree and from a commit.
        assert _content(_read(handlers, worktree, "at-cap.bin", at)) == b"y" * cap


def test_read_diff_stat_and_l1_handle_names_with_spaces_newlines_dashes_and_unicode(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    names = [
        "with space.txt",
        "new\nline.txt",
        "tab\tname",
        "-rf",
        "--help",
        "é.txt",
        "日本語/ファイル.txt",
        "*glob*",
        ":(top)magic",
        'quote"d',
    ]
    for index, name in enumerate(names):
        worktree.write(name, b"committed %d\n" % index)
    committed = worktree.commit("odd names")
    for index, name in enumerate(names):
        worktree.write(name, b"edited %d\n" % index)

    for index, name in enumerate(names):
        assert _content(_read(handlers, worktree, name, committed)) == b"committed %d\n" % index
        assert _content(_read(handlers, worktree, name)) == b"edited %d\n" % index
    diff = handlers["diff_stat"](
        op_request("diff_stat", worktree, from_commit=worktree.base, to_commit=committed)
    )
    assert diff["paths"] == sorted(names)
    assert diff["insertions"] == len(names)
    first = _l1(handlers, worktree)
    assert first["dirty_count"] == len(names)
    assert _l1(handlers, worktree) == first


async def test_a_read_at_the_cap_crosses_the_host_channel(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    content = os.urandom(_read_ops.MAX_HOST_READ_BYTES)
    # The longest single name a common filesystem allows, all multi-byte characters.
    path = "é" * 127
    worktree.write(path, content)
    frame = HostWorkspaceOpFrame(
        request_id="r" * 32,
        op="read",
        root=str(worktree.root),
        params={"repo_root": str(worktree.repo_root), "branch": worktree.branch, "path": path},
        timeout_s=60.0,
    )

    result = await dispatch_workspace_op(frame, run_guarded=asyncio.to_thread, handlers=handlers)
    decoded = decode_workspace_op_frame(json.loads(encode_workspace_op_frame(result, json.dumps)))

    assert result.status == "ok", result.error
    assert decoded.payload is not None
    assert _content(decoded.payload) == content


# ── READ ops never write .git ───────────────────────────────────────────────


def _snapshot(directory: Path) -> dict[str, tuple[int, int, int, str | None]]:
    """Every entry under ``directory`` with its mode, size, mtime and file content hash."""
    entries: dict[str, tuple[int, int, int, str | None]] = {}
    for parent, dirnames, filenames in os.walk(directory):
        for name in [*dirnames, *filenames]:
            path = Path(parent, name)
            stat = path.lstat()
            is_file = path.is_file() and not path.is_symlink()
            entries[str(path.relative_to(directory))] = (
                stat.st_mode,
                stat.st_size,
                stat.st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest() if is_file else None,
            )
    return entries


@pytest.mark.parametrize("target", ["linked-worktree", "main-worktree"])
def test_read_ops_write_nothing_under_git(
    worktree: LinkedWorktree, handlers: Handlers, target: str
) -> None:
    # Index extensions git keeps up to date whenever it may write the index.
    run_git(worktree.repo_root, "config", "core.untrackedCache", "true")
    run_git(worktree.repo_root, "config", "core.splitIndex", "true")
    root = worktree.root if target == "linked-worktree" else worktree.repo_root
    overrides = {} if target == "linked-worktree" else {"root": root, "branch": "main"}
    (root / "README.md").write_bytes(b"edited\n")
    (root / "notes").mkdir()
    (root / "notes/new.txt").write_bytes(b"untracked\n")
    # A tracked file whose stat no longer matches the index tempts git to refresh the index.
    os.utime(root / "src/app.py", ns=(1_000_000_000, 1_000_000_000))
    before = _snapshot(worktree.common_dir)

    handlers["head"](op_request("head", worktree, **overrides))
    handlers["diff_stat"](
        op_request("diff_stat", worktree, from_commit=worktree.base, to_commit=None, **overrides)
    )
    for at in (None, worktree.base):
        handlers["read"](op_request("read", worktree, path="README.md", at_commit=at, **overrides))
    handlers["fingerprint"](op_request("fingerprint", worktree, level="L1", **overrides))

    assert _snapshot(worktree.common_dir) == before
    # The snapshot does see an index refresh, which an ordinary status makes here.
    run_git(root, "status", "--porcelain")
    assert _snapshot(worktree.common_dir) != before


def test_read_ops_neither_need_nor_remove_a_held_index_lock(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    lock = worktree.admin_dir / "index.lock"
    lock.write_bytes(b"another git process")
    worktree.write("README.md", b"edited\n")

    assert _head(handlers, worktree)["head"] == worktree.base
    assert _diff(handlers, worktree, from_commit=worktree.base)["files_changed"] == 0
    assert _content(_read(handlers, worktree, "README.md", worktree.base)) == b"hello\n"
    assert _l1(handlers, worktree)["dirty_count"] == 1

    assert lock.read_bytes() == b"another git process"


def test_a_partial_clone_never_fetches_missing_objects(tmp_path: Path, handlers: Handlers) -> None:
    worktree, older = make_partial_clone_worktree(tmp_path / "partial")
    objects = worktree.common_dir / "objects"
    before = _snapshot(objects)

    # The older README blob is missing: reading or counting it would need a fetch.
    expect_op_error(lambda: _diff(handlers, worktree, from_commit=older), "workspace.git_failed")
    error = expect_op_error(
        lambda: _read(handlers, worktree, "README.md", older), "workspace.git_failed"
    )
    assert "partial clone" in error.message
    assert _l1(handlers, worktree)["head"] == worktree.base

    assert _snapshot(objects) == before
    # The snapshot does see a lazy fetch, which an ordinary diff makes here.
    run_git(worktree.root, "diff", "--numstat", older, "HEAD")
    assert _snapshot(objects) != before


# ── One op per worktree ─────────────────────────────────────────────────────


def _plant_blocking_fifo(worktree: LinkedWorktree) -> None:
    """A nested repository whose HEAD is a FIFO: git's own walk blocks opening it."""
    git_dir = worktree.root / "x" / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "refs").mkdir()
    os.mkfifo(git_dir / "HEAD")


def _frame(worktree: LinkedWorktree, request_id: str, *, timeout_s: float) -> HostWorkspaceOpFrame:
    return HostWorkspaceOpFrame(
        request_id=request_id,
        op="head",
        root=str(worktree.root),
        params={"repo_root": str(worktree.repo_root), "branch": worktree.branch},
        timeout_s=timeout_s,
    )


def test_every_op_on_a_busy_worktree_fails_at_once(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    requests = requests_for_every_op(worktree)
    assert set(requests) == set(handlers)

    # As if another op on this worktree were still running.
    with root_lock(str(worktree.root)):
        for op, request in requests.items():
            error = expect_op_error(
                lambda op=op, request=request: handlers[op](request),
                "workspace.timeout",
                permanent=False,
            )
            assert "another workspace op is still running on this worktree" in error.message

    for op, request in requests_for_every_op(worktree).items():
        handlers[op](request)


async def test_a_stalled_worktree_holds_at_most_one_host_slot(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path
) -> None:
    hostile = make_linked_worktree(tmp_path / "hostile")
    _plant_blocking_fifo(hostile)
    slots = asyncio.Semaphore(MAX_CONCURRENT_WORKSPACE_OPS)

    def dispatch(frame: HostWorkspaceOpFrame) -> asyncio.Task[object]:
        return asyncio.ensure_future(
            dispatch_workspace_op(
                frame, run_guarded=asyncio.to_thread, handlers=handlers, slots=slots
            )
        )

    stalled = dispatch(_frame(hostile, "s" * 32, timeout_s=5))
    # Wait until the stalled op holds the worktree, inside git's blocked walk.
    key = _locks._root_key(str(hostile.root))
    await poll_until_async(
        lambda: key in _locks._root_locks and _locks._root_locks[key].locked(),
        timeout_s=10,
        interval_s=0.01,
    )

    # A second op on the stalled worktree gives its slot back at once; others run.
    again, other = await asyncio.gather(
        dispatch(_frame(hostile, "a" * 32, timeout_s=10)),
        dispatch(_frame(worktree, "o" * 32, timeout_s=10)),
    )
    assert stalled.done() is False
    assert (again.status, again.error_code, again.permanent) == (
        "failed",
        "workspace.timeout",
        False,
    )
    assert "another workspace op is still running" in str(again.error)
    assert other.status == "ok", other.error

    ended = await stalled
    assert (ended.status, ended.error_code) == ("failed", "workspace.timeout")


def test_listing_attributes_files_gives_up_long_before_the_op_deadline(
    worktree: LinkedWorktree, handlers: Handlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_blocking_fifo(worktree)
    monkeypatch.setattr(_target, "ATTRIBUTES_LISTING_LIMIT_S", 1.0)
    started = time.monotonic()

    error = expect_op_error(
        lambda: handlers["head"](op_request("head", worktree, timeout_s=20)),
        "workspace.timeout",
        permanent=False,
    )

    assert "listing" in error.message
    # The 1 s limit ends it, not the op's 20 s deadline.
    assert time.monotonic() - started < 15


# ── Submodules and nested repositories ──────────────────────────────────────


@pytest.mark.parametrize("layout", ["embedded-repository", "rewritten-submodule-gitfile"])
def test_read_ops_never_start_git_in_a_submodule_or_run_its_filter(
    worktree: LinkedWorktree,
    handlers: Handlers,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layout: str,
) -> None:
    sub = add_submodule(worktree)
    git_dir = sub / ".git"
    if layout == "rewritten-submodule-gitfile":
        # The agent keeps the submodule's repository elsewhere in its worktree.
        git_dir = worktree.root / "agent-gitdir"
        (sub / ".git").rename(git_dir)
        (sub / ".git").write_text(f"gitdir: {git_dir}\n")
    marker = tmp_path / "ran"
    with (git_dir / "config").open("a") as stream:
        stream.write(f'[filter "evil"]\n\tclean = "touch {marker}; cat"\n')
    (sub / ".gitattributes").write_text("* filter=evil\n")
    # A stat-dirty file makes a submodule status re-hash it through the filter.
    os.utime(sub / "file.txt", ns=(1_000_000_000, 1_000_000_000))
    trace = tmp_path / "trace"
    trace_git(monkeypatch, trace)
    requests = {
        "head": op_request("head", worktree),
        "diff_stat": op_request("diff_stat", worktree, from_commit=worktree.base, to_commit=None),
        "read": op_request("read", worktree, path="sub/file.txt", at_commit=None),
        "read at a commit": op_request(
            "read", worktree, path=".gitmodules", at_commit=_head(handlers, worktree)["head"]
        ),
        "fingerprint": op_request("fingerprint", worktree, level="L1"),
    }

    for name, request in requests.items():
        trace.write_text("")
        handlers[request.op](request)
        traced = trace.read_text()
        assert "built-in: git" in traced, name
        assert "run_command" not in traced, f"{name} started a child process: {traced}"
        assert not marker.exists(), f"{name} ran the submodule's filter"


def test_l1_still_reports_a_moved_submodule_commit(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    sub = add_submodule(worktree)
    recorded = _l1(handlers, worktree)
    assert recorded["dirty_count"] == 0

    (sub / "file.txt").write_bytes(b"two\n")
    run_git(sub, "commit", "-qam", "moved")
    moved = _l1(handlers, worktree)

    assert moved["dirty_count"] == 1
    assert moved["digest"] != recorded["digest"]


def test_l1_never_sees_the_stash_even_when_the_repository_shows_it(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    run_git(worktree.repo_root, "config", "status.showStash", "true")
    before = _l1(handlers, worktree)

    # The stash is shared by every worktree of the repository.
    (worktree.repo_root / "README.md").write_bytes(b"stashed in the main checkout\n")
    run_git(worktree.repo_root, "stash", "-q")

    assert _l1(handlers, worktree) == before


# ── fingerprint(L1) ─────────────────────────────────────────────────────────

_FIXED_TIME_NS = 1_700_000_000_000_000_000


def _write_with_fixed_mtime(worktree: LinkedWorktree, path: str, content: bytes) -> None:
    worktree.write(path, content)
    os.utime(worktree.root / path, ns=(_FIXED_TIME_NS, _FIXED_TIME_NS))


def test_l1_is_stable_without_edits_and_changes_on_every_edit(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    edits: list[Callable[[], None]] = [
        lambda: _write_with_fixed_mtime(worktree, "README.md", b"edit 1\n"),
        # Same size and mtime as the previous edit: only the content differs.
        lambda: _write_with_fixed_mtime(worktree, "README.md", b"edit 2\n"),
        lambda: worktree.write("new_dir/file.txt", b"untracked\n"),
        lambda: (worktree.root / "src/app.py").unlink(),
    ]
    seen = [_l1(handlers, worktree)]
    assert _l1(handlers, worktree) == seen[0]

    for edit in edits:
        edit()
        current = _l1(handlers, worktree)
        assert current["digest"] not in {earlier["digest"] for earlier in seen}
        assert _l1(handlers, worktree) == current
        seen.append(current)

    assert seen[-1]["level"] == "L1"
    assert seen[-1]["head"] == worktree.base
    assert seen[-1]["dirty_count"] == 3
    assert len(str(seen[-1]["digest"])) == 64


@pytest.mark.parametrize("source", ["info-exclude", "global-excludes-file", "default-xdg-ignore"])
def test_l1_skips_ignored_files_and_coral_runtime(
    worktree: LinkedWorktree, handlers: Handlers, git_home: Path, source: str
) -> None:
    before = _l1(handlers, worktree)
    if source == "info-exclude":
        exclude = worktree.common_dir / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        with exclude.open("a") as stream:
            stream.write("build/\n")
    elif source == "global-excludes-file":
        (git_home / "ignores").write_text("build/\n")
        (git_home / ".gitconfig").write_text("[core]\n\texcludesFile = ~/ignores\n")
    else:
        (git_home / ".config" / "git").mkdir(parents=True)
        (git_home / ".config" / "git" / "ignore").write_text("build/\n")
    worktree.write("build/out.bin", b"ignored")
    worktree.write(".coral/runtime/state.json", b"{}")

    assert _l1(handlers, worktree) == before


def test_l1_records_a_symlink_by_its_text_and_never_reads_its_target(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"one")
    (worktree.root / "link").symlink_to(secret)
    linked = _l1(handlers, worktree)

    secret.write_bytes(b"a different and longer secret")
    assert _l1(handlers, worktree) == linked

    (worktree.root / "link").unlink()
    (worktree.root / "link").symlink_to(tmp_path / "other.txt")
    assert _l1(handlers, worktree)["digest"] != linked["digest"]


def test_l1_never_walks_through_a_directory_replaced_by_a_symlink(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.py").write_bytes(b"outside one")
    # git reports src/app.py as deleted and src as a new symlink.
    for tracked in (worktree.root / "src").iterdir():
        tracked.unlink()
    (worktree.root / "src").rmdir()
    (worktree.root / "src").symlink_to(outside, target_is_directory=True)
    first = _l1(handlers, worktree)

    (outside / "app.py").write_bytes(b"outside two, longer")

    assert _l1(handlers, worktree) == first
    assert first["dirty_count"] == 2


def test_l1_records_only_the_type_of_a_fifo_or_nested_repository(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    (worktree.root / "src/app.py").unlink()
    os.mkfifo(worktree.root / "src/app.py")
    run_git(worktree.root, "init", "-q", "nested")
    (worktree.root / "nested" / "file.txt").write_bytes(b"inside a nested repository")

    first = _l1(handlers, worktree)

    assert first["dirty_count"] == 2
    assert _l1(handlers, worktree) == first


def test_l1_records_a_directory_it_cannot_open_instead_of_failing(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    worktree.write("locked/file.txt", b"one\n")
    worktree.commit("locked")
    worktree.write("locked/file.txt", b"two\n")
    # Execute-only: git can still reach the file by path, the walk cannot list it.
    (worktree.root / "locked").chmod(0o111)
    try:
        first = _l1(handlers, worktree)
        assert first["dirty_count"] == 1
        assert _l1(handlers, worktree) == first
    finally:
        (worktree.root / "locked").chmod(0o755)


def test_l1_hashes_files_up_to_the_read_cap_only(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    _write_with_fixed_mtime(worktree, "big.bin", b"a" * (MAX_READ_BYTES + 1))
    _write_with_fixed_mtime(worktree, "small.bin", b"a" * 64)
    before = _l1(handlers, worktree)

    # Same size and mtime: an oversized file is not hashed, so L1 cannot see the edit.
    _write_with_fixed_mtime(worktree, "big.bin", b"b" * (MAX_READ_BYTES + 1))
    assert _l1(handlers, worktree) == before

    _write_with_fixed_mtime(worktree, "small.bin", b"b" * 64)
    assert _l1(handlers, worktree)["digest"] != before["digest"]


@pytest.mark.parametrize("level", ["L2", "L9"])
def test_fingerprint_serves_only_l1(
    worktree: LinkedWorktree, handlers: Handlers, level: str
) -> None:
    expect_op_error(
        lambda: handlers["fingerprint"](op_request("fingerprint", worktree, level=level)),
        "workspace.capability_unavailable",
        permanent=True,
    )
