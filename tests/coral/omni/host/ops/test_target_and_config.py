"""Pinned targets and config refusals of Coral's host workspace ops, on real git."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from coral.omni.host.ops import _git, _target
from coral.omni.host.ops._git import host_git
from coral.omni.host.ops._target import MAX_ATTRIBUTES_FILE_BYTES, PinnedTarget, resolve_pinned
from omnigent.host.workspace_ops import WorkspaceOpHandler
from tests._helpers.polling import poll_until
from tests.coral.omni.host.ops._worktrees import (
    LinkedWorktree,
    expect_op_error,
    make_partial_clone_worktree,
    make_repository,
    op_request,
    requests_for_every_op,
    run_git,
    write_stub_git,
)

Handlers = Mapping[str, WorkspaceOpHandler]
_LFS_LINE = "*.bin filter=lfs diff=lfs merge=lfs -text\n"


def _head(
    handlers: Handlers, worktree: LinkedWorktree, **overrides: object
) -> Mapping[str, object]:
    root = overrides.pop("root", None)
    return handlers["head"](op_request("head", worktree, root=root, **overrides))


def _resolve(worktree: LinkedWorktree, *, root: Path, branch: str, write: bool) -> PinnedTarget:
    return resolve_pinned(
        host_git(time.monotonic() + 60),
        repo_root=str(worktree.repo_root),
        root=str(root),
        branch=branch,
        write=write,
    )


def _commit_in(repo: Path, content: bytes) -> None:
    (repo / "README.md").write_bytes(content)
    run_git(repo, "commit", "-qam", "change")


# ── Pinned target ───────────────────────────────────────────────────────────


def test_a_rewritten_worktree_git_file_does_not_redirect_ops(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    make_repository(other)
    _commit_in(other, b"other repository\n")
    (worktree.root / ".git").write_text(f"gitdir: {other / '.git'}\n")

    assert _head(handlers, worktree)["head"] == worktree.base
    diff = handlers["diff_stat"](
        op_request("diff_stat", worktree, from_commit=worktree.base, to_commit=None)
    )
    assert diff["files_changed"] == 0
    assert handlers["fingerprint"](op_request("fingerprint", worktree, level="L1"))["head"] == (
        worktree.base
    )
    read = handlers["read"](
        op_request("read", worktree, path="README.md", at_commit=worktree.base)
    )
    assert read["content_b64"] == "aGVsbG8K"  # b"hello\n" from the bound repository


def test_a_listed_linked_worktree_pins_its_own_git_dir(worktree: LinkedWorktree) -> None:
    for write in (False, True):
        target = _resolve(worktree, root=worktree.root, branch=worktree.branch, write=write)
        assert target.git_dir == str(worktree.admin_dir)
        assert target.common_dir == str(worktree.common_dir)


def test_the_main_worktree_is_readable_but_never_a_write_target(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    head = _head(handlers, worktree, root=str(worktree.repo_root), branch="main")
    assert head["branch"] == "main"

    expect_op_error(
        lambda: _resolve(worktree, root=worktree.repo_root, branch="main", write=True),
        "workspace.target_mismatch",
    )


@pytest.mark.parametrize(
    "case",
    [
        "unlisted-directory",
        "another-repository",
        "symlinked-root",
        "linked-repo-root",
        "worktree-subdirectory",
        "nested-repository",
    ],
)
def test_ops_refuse_a_root_the_repository_does_not_list(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, case: str
) -> None:
    overrides: dict[str, object] = {}
    if case == "worktree-subdirectory":
        overrides["root"] = str(worktree.root / "src")
    elif case == "nested-repository":
        run_git(worktree.root, "init", "-q", "nested")
        overrides["root"] = str(worktree.root / "nested")
    elif case == "unlisted-directory":
        stray = tmp_path / "stray"
        stray.mkdir()
        overrides["root"] = str(stray.resolve())
    elif case == "another-repository":
        other = tmp_path / "other"
        make_repository(other)
        run_git(other, "worktree", "add", "-q", "-b", "coral/r-x/base", str(tmp_path / "other-wt"))
        overrides["root"] = str((tmp_path / "other-wt").resolve())
    elif case == "symlinked-root":
        alias = tmp_path / "alias"
        alias.symlink_to(worktree.root, target_is_directory=True)
        overrides["root"] = str(alias)
    else:
        # A linked worktree is not a repository's main worktree.
        overrides["repo_root"] = str(worktree.root)

    expect_op_error(lambda: _head(handlers, worktree, **overrides), "workspace.target_mismatch")


@pytest.mark.parametrize("case", ["branch-outside-coral", "another-branch", "detached-head"])
def test_write_targets_must_have_their_coral_branch_checked_out(
    worktree: LinkedWorktree, case: str
) -> None:
    branch = worktree.branch
    if case == "branch-outside-coral":
        run_git(worktree.root, "checkout", "-q", "-b", "feature/x")
        branch = "feature/x"
    elif case == "another-branch":
        run_git(worktree.root, "checkout", "-q", "-b", "coral/r-test/other")
    else:
        run_git(worktree.root, "checkout", "-q", "--detach")

    expect_op_error(
        lambda: _resolve(worktree, root=worktree.root, branch=branch, write=True),
        "workspace.target_mismatch",
    )


def test_a_worktree_registered_with_relative_paths_is_pinned(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    if _git.parse_git_version(run_git(worktree.repo_root, "--version")) < (2, 48):
        pytest.skip("git worktree add --relative-paths needs git 2.48")
    relative = worktree.repo_root.parent / "repo-worktrees" / "coral-r-test-relative"
    branch = "coral/r-test/relative"
    run_git(
        worktree.repo_root,
        "worktree",
        "add",
        "-q",
        "--relative-paths",
        "-b",
        branch,
        str(relative),
    )

    assert _head(handlers, worktree, root=str(relative), branch=branch)["branch"] == branch


@pytest.mark.parametrize("case", ["another-common-dir", "missing-commondir"])
def test_the_admin_dir_must_lead_back_to_the_repository(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, case: str
) -> None:
    commondir = worktree.admin_dir / "commondir"
    if case == "another-common-dir":
        other = tmp_path / "other"
        make_repository(other)
        commondir.write_text(f"{other / '.git'}\n")
    else:
        commondir.unlink()

    expect_op_error(lambda: _head(handlers, worktree), "workspace.target_mismatch")


@pytest.mark.parametrize("owned_path", ["root", "common-dir"])
def test_files_of_another_user_are_refused(
    worktree: LinkedWorktree,
    handlers: Handlers,
    monkeypatch: pytest.MonkeyPatch,
    owned_path: str,
) -> None:
    other_owner = str(worktree.root if owned_path == "root" else worktree.common_dir)
    real_lstat = os.lstat

    def lstat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        result = real_lstat(path, *args, **kwargs)  # type: ignore[arg-type]
        if os.fspath(path) == other_owner:  # type: ignore[arg-type]
            fields = list(result)
            fields[4] = result.st_uid + 1  # st_uid
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(_target.os, "lstat", lstat)
    error = expect_op_error(
        lambda: _head(handlers, worktree), "workspace.backend_unavailable", permanent=True
    )
    assert "not owned by the host user" in error.message


def _case_insensitive(directory: Path) -> bool:
    """Whether ``directory``'s file system folds case, found by probing it."""
    (directory / "case-probe").write_text("")
    return (directory / "CASE-PROBE").exists()


@pytest.mark.parametrize("planted_in", ["root", "repo-root"])
@pytest.mark.parametrize("spelling", ["exact", "symlinked-path-entry", "case-variant"])
def test_a_git_inside_the_worktree_or_repository_never_runs(
    worktree: LinkedWorktree,
    handlers: Handlers,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    planted_in: str,
    spelling: str,
) -> None:
    marker = tmp_path / "ran"
    inside = worktree.root if planted_in == "root" else worktree.repo_root
    planted = write_stub_git(inside / "bin", f'touch "{marker}"; echo "git version 2.54.0"')
    # The PATH entry names the planted directory; directories compare by identity.
    if spelling == "exact":
        path_entry = inside / "bin"
    elif spelling == "symlinked-path-entry":
        (tmp_path / "alias").symlink_to(inside, target_is_directory=True)
        path_entry = tmp_path / "alias" / "bin"
    else:
        if not _case_insensitive(tmp_path):
            pytest.skip("this file system tells names apart by case")
        path_entry = inside.parent / inside.name.swapcase() / "bin"
    assert (path_entry / "git").samefile(planted)
    monkeypatch.setenv("PATH", str(path_entry))
    monkeypatch.setattr(_git, "_resolved_git", None)

    error = expect_op_error(
        lambda: _head(handlers, worktree), "workspace.backend_unavailable", permanent=True
    )
    assert "inside" in error.message
    assert not marker.exists()


# ── Config refusals ─────────────────────────────────────────────────────────


def _repo_config(key: str, value: str) -> Callable[[LinkedWorktree, Path], None]:
    def setup(worktree: LinkedWorktree, _home: Path) -> None:
        run_git(worktree.repo_root, "config", key, value)

    return setup


def _write(template: str, text: str) -> Callable[[LinkedWorktree, Path], None]:
    def setup(worktree: LinkedWorktree, home: Path) -> None:
        target = Path(template.format(root=worktree.root, common=worktree.common_dir, home=home))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    return setup


def _configured_attributes_file(worktree: LinkedWorktree, home: Path) -> None:
    (home / "attributes").write_text(_LFS_LINE)
    (home / ".gitconfig").write_text("[core]\n\tattributesFile = ~/attributes\n")


def _deleted_tracked_attributes(worktree: LinkedWorktree, _home: Path) -> None:
    # Git falls back to the index copy of a .gitattributes missing from the tree.
    worktree.write(".gitattributes", _LFS_LINE.encode())
    worktree.commit("attributes")
    (worktree.root / ".gitattributes").unlink()


def _committed_nested_attributes(worktree: LinkedWorktree, _home: Path) -> None:
    worktree.write("assets/raw/.gitattributes", _LFS_LINE.encode())
    worktree.commit("nested attributes")


def _worktree_config_filter(worktree: LinkedWorktree, _home: Path) -> None:
    # Per-worktree config lives in the linked worktree's own git dir.
    run_git(worktree.repo_root, "config", "extensions.worktreeConfig", "true")
    run_git(worktree.root, "config", "--worktree", "filter.lfs.clean", "git-lfs clean -- %f")


def _included_config_hook(worktree: LinkedWorktree, home: Path) -> None:
    (home / "included").write_text('[hook "audit"]\n\tcommand = echo audited\n')
    run_git(worktree.repo_root, "config", "include.path", str(home / "included"))


def _sparse_checkout_command(worktree: LinkedWorktree, _home: Path) -> None:
    # In a linked worktree this writes core.sparseCheckout to its config.worktree.
    run_git(worktree.root, "sparse-checkout", "set", "src")


def _replace_tracked_attributes(content: bytes, replacement: str) -> Callable[..., None]:
    def setup(worktree: LinkedWorktree, _home: Path) -> None:
        worktree.write(".gitattributes", content)
        worktree.commit("attributes")
        target = worktree.root / ".gitattributes"
        target.unlink()
        if replacement == "symlink":
            # Git does not follow it and reads the index copy instead.
            target.symlink_to("README.md")
        else:
            os.mkfifo(target)

    return setup


def _oversized_attributes(worktree: LinkedWorktree, _home: Path) -> None:
    worktree.write(".gitattributes", b"#" * (MAX_ATTRIBUTES_FILE_BYTES + 1))


REFUSALS: dict[str, Callable[[LinkedWorktree, Path], None]] = {
    "repo-hook": _repo_config("hook.audit.command", "echo audited"),
    "included-config-hook": _included_config_hook,
    "repo-filter": _repo_config("filter.lfs.clean", "git-lfs clean -- %f"),
    "worktree-config-filter": _worktree_config_filter,
    "repo-merge-driver": _repo_config("merge.ours.driver", "true"),
    "sparse-checkout": _repo_config("core.sparseCheckout", "true"),
    "sparse-checkout-command": _sparse_checkout_command,
    "nested-gitattributes": _write("{root}/assets/raw/.gitattributes", _LFS_LINE),
    "committed-nested-gitattributes": _committed_nested_attributes,
    "deleted-tracked-gitattributes": _deleted_tracked_attributes,
    "info-attributes": _write("{common}/info/attributes", _LFS_LINE),
    "configured-attributes-file": _configured_attributes_file,
    "default-attributes-file": _write("{home}/.config/git/attributes", _LFS_LINE),
    # Git splits tokens on CR too.
    "carriage-return-before-filter": _write("{root}/.gitattributes", "*.bin text\rfilter=lfs\n"),
    "attribute-macro-with-filter": _write(
        "{root}/.gitattributes", "[attr]big filter=lfs diff=lfs\n*.bin big\n"
    ),
    "upper-case-gitattributes": _write("{root}/assets/.GITATTRIBUTES", _LFS_LINE),
    "symlinked-tracked-gitattributes": _replace_tracked_attributes(_LFS_LINE.encode(), "symlink"),
    # A FIFO would block git's own read; refused before git runs.
    "fifo-tracked-gitattributes": _replace_tracked_attributes(b"*.txt text\n", "fifo"),
    "oversized-gitattributes": _oversized_attributes,
    "repo-attr-tree": _repo_config("attr.tree", "HEAD"),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_repositories_that_declare_hooks_filters_or_sparse_checkout_are_refused(
    worktree: LinkedWorktree, handlers: Handlers, git_home: Path, case: str
) -> None:
    REFUSALS[case](worktree, git_home)

    for op, params in (("head", {}), ("fingerprint", {"level": "L1"})):
        expect_op_error(
            lambda op=op, params=params: handlers[op](op_request(op, worktree, **params)),
            "workspace.backend_unavailable",
            permanent=True,
        )


def test_an_untracked_symlinked_gitattributes_is_not_read(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path
) -> None:
    outside = tmp_path / "outside-attributes"
    outside.write_text(_LFS_LINE)
    # Git never follows an in-tree .gitattributes symlink, and the index has no copy.
    (worktree.root / ".gitattributes").symlink_to(outside)

    assert _head(handlers, worktree)["branch"] == worktree.branch


def test_refusals_escape_the_file_names_they_name(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    worktree.write("bad\x1b[31m\nFAKE: forged line/.gitattributes", _LFS_LINE.encode())

    error = expect_op_error(
        lambda: _head(handlers, worktree), "workspace.backend_unavailable", permanent=True
    )

    assert error.message.isprintable()
    assert "bad\\x1b[31m\\nFAKE: forged line/.gitattributes" in error.message


def test_the_attributes_check_stops_at_the_deadline(
    worktree: LinkedWorktree, handlers: Handlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    for directory in ("a", "b", "c"):
        worktree.write(f"{directory}/.gitattributes", b"*.txt text\n")
    request = op_request("head", worktree, timeout_s=3)
    read_in_root = _target.read_in_root
    reads: list[bytes] = []

    def slow_read(root: str, relpath: bytes, **kwargs: object) -> bytes:
        # The first file takes until the op's deadline.
        reads.append(relpath)
        poll_until(lambda: time.monotonic() > request.deadline, timeout_s=10, interval_s=0.01)
        return read_in_root(root, relpath, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_target, "read_in_root", slow_read)

    expect_op_error(lambda: handlers["head"](request), "workspace.timeout")
    assert reads == [b"a/.gitattributes"]


@pytest.mark.parametrize(("version", "served"), [((2, 43), False), ((2, 44), True)])
def test_a_partial_clone_needs_git_that_cannot_fetch_lazily(
    tmp_path: Path,
    handlers: Handlers,
    monkeypatch: pytest.MonkeyPatch,
    version: tuple[int, int],
    served: bool,
) -> None:
    worktree, _older = make_partial_clone_worktree(tmp_path / "partial")
    executable = host_git(time.monotonic() + 30).executable
    monkeypatch.setattr(_git, "_resolved_git", (executable, version))

    if served:
        assert _head(handlers, worktree)["head"] == worktree.base
    else:
        error = expect_op_error(
            lambda: _head(handlers, worktree), "workspace.backend_unavailable", permanent=True
        )
        assert "partial clone" in error.message


def test_old_git_still_serves_a_full_clone(
    worktree: LinkedWorktree, handlers: Handlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = host_git(time.monotonic() + 30).executable
    monkeypatch.setattr(_git, "_resolved_git", (executable, (2, 32)))

    assert _head(handlers, worktree)["head"] == worktree.base


def test_a_global_lfs_install_alone_is_allowed(
    worktree: LinkedWorktree, handlers: Handlers, git_home: Path
) -> None:
    (git_home / ".gitconfig").write_text(
        '[filter "lfs"]\n'
        "\tclean = git-lfs clean -- %f\n"
        "\tsmudge = git-lfs smudge -- %f\n"
        "\tprocess = git-lfs filter-process\n"
        "\trequired = true\n"
    )
    # Attributes that name no filter are fine.
    worktree.write(".gitattributes", b"*.txt text eol=lf\n*.bin -filter binary\n")

    assert _head(handlers, worktree)["branch"] == worktree.branch
    fingerprint = handlers["fingerprint"](op_request("fingerprint", worktree, level="L1"))
    assert fingerprint["dirty_count"] == 1


def test_git_older_than_2_32_is_refused(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub = write_stub_git(tmp_path / "old-git", 'echo "git version 2.31.8"')
    monkeypatch.setenv("PATH", str(stub.parent))
    monkeypatch.setattr(_git, "_resolved_git", None)

    error = expect_op_error(
        lambda: _head(handlers, worktree), "workspace.backend_unavailable", permanent=True
    )
    assert "2.31.8" in error.message


def test_a_host_without_git_is_refused(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "empty-bin").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.setattr(_git, "_resolved_git", None)

    expect_op_error(
        lambda: _head(handlers, worktree), "workspace.backend_unavailable", permanent=True
    )


def test_non_posix_hosts_refuse_every_op(
    worktree: LinkedWorktree, handlers: Handlers, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = requests_for_every_op(worktree)
    assert set(requests) == set(handlers)
    monkeypatch.setattr(os, "name", "nt")

    for op, request in requests.items():
        error = expect_op_error(
            lambda op=op, request=request: handlers[op](request),
            "workspace.backend_unavailable",
            permanent=True,
        )
        assert "POSIX" in error.message


# ── Params and environment ──────────────────────────────────────────────────

_MISSING = object()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("repo_root", _MISSING),
        ("repo_root", "relative/repo"),
        ("repo_root", "/a/../repo"),
        ("repo_root", "/repo/"),
        ("repo_root", "/re\0po"),
        ("repo_root", 5),
        ("branch", _MISSING),
        ("branch", ["coral/x"]),
        ("unexpected", "value"),
    ],
    ids=[
        "missing-repo-root",
        "relative-repo-root",
        "dot-dot-repo-root",
        "trailing-slash-repo-root",
        "nul-repo-root",
        "repo-root-not-a-string",
        "missing-branch",
        "branch-not-a-string",
        "unknown-param",
    ],
)
def test_params_are_revalidated_on_the_host(
    worktree: LinkedWorktree, handlers: Handlers, key: str, value: object
) -> None:
    request = op_request("head", worktree)
    params = dict(request.params)
    if value is _MISSING:
        del params[key]
    else:
        params[key] = value

    expect_op_error(
        lambda: handlers["head"](replace(request, params=params)),
        "workspace.invalid_params",
        permanent=True,
    )


@pytest.mark.parametrize("root", ["relative/root", "/a/../root", "/root/"])
def test_a_non_canonical_root_is_refused_even_past_the_dispatcher(
    worktree: LinkedWorktree, handlers: Handlers, root: str
) -> None:
    expect_op_error(
        lambda: handlers["head"](op_request("head", worktree, root=root)),
        "workspace.invalid_params",
        permanent=True,
    )


def test_a_malformed_op_key_is_refused_before_any_use(
    worktree: LinkedWorktree, handlers: Handlers
) -> None:
    expect_op_error(
        lambda: handlers["head"](op_request("head", worktree, op_key="../../escape")),
        "workspace.invalid_params",
        permanent=True,
    )


def test_inherited_git_environment_cannot_redirect_or_reconfigure_ops(
    worktree: LinkedWorktree, handlers: Handlers, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    make_repository(other)
    _commit_in(other, b"other\n")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    # Config injected through the environment would declare a hook.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "hook.injected.command")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "echo injected")

    assert _head(handlers, worktree)["head"] == worktree.base


# ── Settings from the full config ───────────────────────────────────────────


def test_identity_and_conversion_settings_come_from_the_full_config(
    worktree: LinkedWorktree, git_home: Path
) -> None:
    (git_home / ".gitconfig").write_text(
        "[user]\n\tname = Global User\n\temail = global@example.test\n"
        "[core]\n\tautocrlf = input\n\texcludesFile = ~/ignores\n"
    )
    run_git(worktree.repo_root, "config", "user.email", "repo@example.test")
    run_git(worktree.repo_root, "config", "core.eol", "lf")

    target = _resolve(worktree, root=worktree.root, branch=worktree.branch, write=True)

    assert target.identity == ("Global User", "repo@example.test")
    assert target.git.config_args == (
        "-c",
        "core.excludesFile=~/ignores",
        "-c",
        "core.autocrlf=input",
        "-c",
        "core.eol=lf",
    )
    # Every pinned call carries them, on top of the hardening flags.
    assert target.git.run("config", "--get", "core.autocrlf").stdout == b"input\n"
    assert target.git.run("config", "--get", "core.hooksPath").stdout == b"/dev/null\n"


def test_identity_falls_back_to_coral_when_unset(worktree: LinkedWorktree) -> None:
    target = _resolve(worktree, root=worktree.root, branch=worktree.branch, write=True)
    assert target.identity == ("Coral", "coral@localhost")
