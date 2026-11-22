"""Tests for the inner sandbox launcher."""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import json
import logging
import os
import pathlib
import re
import shlex
import stat  # CORAL(S115)
import subprocess
import sys
from unittest import mock

import pytest

from omnigent.inner.sandbox import (
    HOST_SANDBOX_BACKEND_ENV,
    SandboxPolicy,
    _launcher_inline_source,
    create_exec_launcher,
    run_launcher,
)
from omnigent.runner.identity import RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR


def _noop_policy() -> SandboxPolicy:
    """A ``backend_type="none"`` / ``active=False`` policy.

    Skips kernel-level activation so tests don't need bwrap.

    :returns: An inactive :class:`SandboxPolicy`.
    """
    return SandboxPolicy(
        backend_type="none",
        active=False,
        read_roots=None,
        write_roots=[],
        write_files=[],
        allow_network=True,
    )


def _noop_policy_arg() -> str:
    """The no-op policy in ``run_launcher``'s wire format
    (base64-encoded JSON, matching ``_encode_json_arg``).
    """
    raw = json.dumps(_noop_policy().to_jsonable(), separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return base64.urlsafe_b64encode(raw).decode("ascii")


@pytest.mark.parametrize("grant_field", ["write_roots", "write_files"])
@pytest.mark.parametrize("grant_parent", [False, True])
def test_exec_launcher_rejects_writable_launcher_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, grant_field: str, grant_parent: bool
) -> None:
    launcher_dir = tmp_path / "launchers"
    launcher_dir.mkdir()
    monkeypatch.setattr("omnigent.inner.sandbox.tempfile.tempdir", str(launcher_dir))
    policy = dataclasses.replace(_noop_policy(), active=True, backend_type="linux_bwrap")
    setattr(policy, grant_field, [tmp_path if grant_parent else launcher_dir])

    with pytest.raises(ValueError, match="Grant a dedicated scratch directory"):
        create_exec_launcher(sys.executable, policy)
    assert list(launcher_dir.iterdir()) == []


def test_exec_launcher_accepts_dedicated_scratch_directory(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher_dir = tmp_path / "launchers"
    launcher_dir.mkdir()
    scratch = launcher_dir / "scratch"
    scratch.mkdir()
    monkeypatch.setattr("omnigent.inner.sandbox.tempfile.tempdir", str(launcher_dir))
    policy = dataclasses.replace(
        _noop_policy(), active=True, backend_type="linux_bwrap", write_roots=[scratch]
    )

    path = pathlib.Path(create_exec_launcher(sys.executable, policy, cwd=str(scratch)))
    try:
        assert path.parent == launcher_dir
        assert path.stat().st_mode & 0o777 == 0o700
    finally:
        path.unlink()


def test_exec_launcher_freezes_phoenix_proc_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A filtered child launcher does not need the Phoenix marker."""
    captured: list[SandboxPolicy] = []
    policy = dataclasses.replace(_noop_policy(), active=True, backend_type="linux_bwrap")
    monkeypatch.setenv(HOST_SANDBOX_BACKEND_ENV, "phoenix-kubernetes")
    monkeypatch.setattr(
        "omnigent.inner.sandbox._launcher_inline_source",
        lambda _target, resolved, *, cwd=None: captured.append(resolved) or "pass",
    )

    path = pathlib.Path(create_exec_launcher(sys.executable, policy))
    path.unlink()

    assert captured[0].bind_host_proc is True


def test_run_launcher_emits_logger_checkpoints(caplog) -> None:
    """
    ``run_launcher`` logs three INFO records around the
    sandbox-activation and target-spawn steps. Dropping any of them
    erases the diagnostic signal the claude-sdk leg relies on to
    pinpoint a silent connect hang.
    """
    with caplog.at_level(logging.INFO, logger="omnigent.inner.sandbox"):
        rc = run_launcher(_noop_policy_arg(), sys.executable, ["-c", "pass"])
    assert rc == 0

    messages = [record.getMessage() for record in caplog.records]
    # Absent: wrapper never entered the body.
    assert any("[omnigent-sandbox] activating backend=none active=False" in m for m in messages), (
        messages
    )
    # Absent on an active policy: activation hung.
    assert any("[omnigent-sandbox] activated; spawning target=" in m for m in messages), messages
    # Absent: spawned target hung (the claude-sdk symptom).
    assert any("[omnigent-sandbox] target exited rc=0" in m for m in messages), messages


def test_run_launcher_strips_runner_binding_token_from_target_env(monkeypatch) -> None:
    """The runner tunnel binding token never reaches the spawned target.

    The launcher inherited the runner's full environment and
    ``subprocess.run`` passed it straight to the sandboxed target, so
    agent code could read the runner's control-plane auth secret and
    impersonate the runner. The probe target exits 0 only when the
    token is ABSENT from its inherited ``os.environ``; a non-zero rc
    means the leak is back.

    Spawns a real subprocess (no mocking of ``subprocess.run``) so the
    assertion covers the actual env inheritance the vulnerability used.

    :param monkeypatch: Pytest monkeypatch fixture used to seed the
        binding token into the launcher process's environment.
    """
    monkeypatch.setenv(RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR, "bug-binding-token-secret")
    probe = (
        "import os, sys; "
        f"sys.exit(3 if {RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR!r} in os.environ else 0)"
    )

    rc = run_launcher(_noop_policy_arg(), sys.executable, ["-c", probe])

    assert rc == 0, "binding token leaked into the sandboxed target environment"
    # The launcher also drops it from its own process env so any later
    # inheritor (bwrap re-exec) is covered too.
    assert RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR not in os.environ


def test_run_launcher_propagates_target_returncode(caplog) -> None:
    """``run_launcher`` returns the spawned target's exit code verbatim."""
    with caplog.at_level(logging.INFO, logger="omnigent.inner.sandbox"):
        rc = run_launcher(
            _noop_policy_arg(),
            sys.executable,
            ["-c", "raise SystemExit(7)"],
        )
    assert rc == 7
    messages = [record.getMessage() for record in caplog.records]
    assert any("[omnigent-sandbox] target exited rc=7" in m for m in messages), messages


@pytest.mark.parametrize("without_site_packages", [False, True])
def test_exec_launcher_wrapper_subprocess_emits_markers_to_stderr(
    without_site_packages: bool,
) -> None:
    """
    The generated wrapper script must configure logging so
    ``run_launcher``'s INFO records reach stderr when invoked as a
    subprocess. ``caplog`` alone can't catch a regression in the
    ``basicConfig`` line of the generated script.
    """
    wrapper_path = create_exec_launcher(sys.executable, _noop_policy())
    try:
        launcher = (
            [
                sys.executable,
                "-S",
                "-P",
                "-c",
                _launcher_inline_source(sys.executable, _noop_policy()),
            ]
            if without_site_packages
            else [wrapper_path]
        )
        result = subprocess.run(
            [*launcher, "-c", "pass"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(wrapper_path)

    assert result.returncode == 0, result
    assert "[omnigent-sandbox] activating backend=none active=False" in result.stderr, (
        result.stderr
    )
    assert "[omnigent-sandbox] activated; spawning target=" in result.stderr, result.stderr
    assert "[omnigent-sandbox] target exited rc=0" in result.stderr, result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX launcher script")
def test_exec_launcher_ignores_workspace_modules(tmp_path: pathlib.Path) -> None:
    """Modules in the spawner's cwd never replace the launcher's own imports."""
    for name in ("logging", "json", "base64"):
        (tmp_path / f"{name}.py").write_text(f"raise ImportError('{name} loaded from the cwd')\n")
    wrapper_path = create_exec_launcher(sys.executable, _noop_policy())
    try:
        result = subprocess.run(
            [wrapper_path, "-c", "print('target ran')"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(wrapper_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "target ran"


def test_run_launcher_wraps_target_with_strace_when_env_set(monkeypatch, caplog) -> None:
    """
    ``OMNIGENT_SANDBOX_STRACE=1`` must prepend ``strace -f -y -e
    trace=file`` to the spawned target's argv so the wrapper's stderr
    captures file-syscall denials (EACCES) from the sandbox.
    """
    from omnigent.inner import sandbox as sb

    captured: list[list[str]] = []

    class _FakeCompleted:
        returncode = 0

    def _fake_run(argv, **kwargs):
        captured.append(list(argv))
        return _FakeCompleted()

    monkeypatch.setattr(sb.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        sb.shutil,
        "which",
        lambda name: "/usr/bin/strace" if name == "strace" else None,
    )
    monkeypatch.setenv("OMNIGENT_SANDBOX_STRACE", "1")

    with caplog.at_level(logging.WARNING, logger="omnigent.inner.sandbox"):
        rc = sb.run_launcher(_noop_policy_arg(), "/bin/echo", ["hi"])

    assert rc == 0
    assert captured == [
        ["/usr/bin/strace", "-f", "-y", "-e", "trace=file", "--", "/bin/echo", "hi"]
    ], captured
    # WARNING emitted so CI logs unambiguously confirm strace was active.
    assert any("strace active" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_run_launcher_skips_strace_when_binary_missing(monkeypatch, caplog) -> None:
    """If ``OMNIGENT_SANDBOX_STRACE`` is set but strace is not on
    PATH, the wrapper must log a warning and run the target unwrapped
    rather than failing the spawn.
    """
    from omnigent.inner import sandbox as sb

    captured: list[list[str]] = []

    class _FakeCompleted:
        returncode = 0

    def _fake_run(argv, **kwargs):
        captured.append(list(argv))
        return _FakeCompleted()

    monkeypatch.setattr(sb.subprocess, "run", _fake_run)
    monkeypatch.setattr(sb.shutil, "which", lambda name: None)
    monkeypatch.setenv("OMNIGENT_SANDBOX_STRACE", "1")

    with caplog.at_level(logging.WARNING, logger="omnigent.inner.sandbox"):
        rc = sb.run_launcher(_noop_policy_arg(), "/bin/echo", ["hi"])

    assert rc == 0
    # Target ran unwrapped (no strace prefix), proving the missing-binary
    # path falls back gracefully instead of erroring or hanging.
    assert captured == [["/bin/echo", "hi"]], captured
    assert any("strace is not on PATH" in r.getMessage() for r in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


# ---------------------------------------------------------------------------
# spawn_env_allowlist tests
# ---------------------------------------------------------------------------


def test_sandbox_policy_round_trips_spawn_env_allowlist() -> None:
    """``spawn_env_allowlist`` survives the launcher wire encoding.

    The policy crosses the parent/launcher boundary as JSON baked into
    the generated wrapper script; a field missing from ``to_jsonable``
    or ``from_jsonable`` silently decodes as ``None`` and the launcher
    prune becomes a no-op — the sandbox would quietly lose its env
    containment layer.
    """
    policy = _noop_policy()
    policy.spawn_env_allowlist = ["HOME", "PATH", "PI_CODING_AGENT_DIR"]
    policy.bind_host_proc = True

    decoded = SandboxPolicy.from_jsonable(policy.to_jsonable())

    assert decoded.spawn_env_allowlist == ["HOME", "PATH", "PI_CODING_AGENT_DIR"]
    assert decoded.bind_host_proc is True
    assert SandboxPolicy.from_jsonable({}).bind_host_proc is None
    assert SandboxPolicy.from_jsonable({"bind_host_proc": "false"}).bind_host_proc is None
    assert SandboxPolicy.from_jsonable({"bind_host_proc": False}).bind_host_proc is False
    # Old payloads (no key) and unset policies must decode to None —
    # "no prune", not "prune everything".
    assert SandboxPolicy.from_jsonable(_noop_policy().to_jsonable()).spawn_env_allowlist is None


def test_credential_source_paths_survive_serialization_and_cloning(tmp_path: pathlib.Path) -> None:
    from omnigent.inner.sandbox import with_additional_read_roots, with_additional_write_roots

    policy = _noop_policy()
    protected = (tmp_path / "token.sock").resolve()
    policy.credential_source_paths = [protected]
    decoded = SandboxPolicy.from_jsonable(policy.to_jsonable())
    cloned = with_additional_read_roots(decoded, [tmp_path / "tools"])
    cloned = with_additional_write_roots(cloned, [tmp_path / "scratch"])
    assert cloned.credential_source_paths == [protected]
    assert cloned.credential_source_paths is not decoded.credential_source_paths
    assert SandboxPolicy.from_jsonable({}).credential_source_paths is None


def test_sandbox_policy_round_trips_deny_unix_socket_paths() -> None:
    """``deny_unix_socket_paths`` survives the launcher wire encoding.

    The seatbelt backend reads this list from the *decoded* policy to
    emit its ``(deny network-outbound (remote unix-socket ...))`` rules.
    If the field dropped out of ``to_jsonable`` / ``from_jsonable`` it
    would decode as ``None``, the deny rule would never be emitted, and
    the sandboxed pane could reach the unsandboxed tmux control socket.
    """
    from pathlib import Path

    policy = _noop_policy()
    policy.deny_unix_socket_paths = [Path("/tmp/inst/tmux.sock")]

    decoded = SandboxPolicy.from_jsonable(policy.to_jsonable())

    assert decoded.deny_unix_socket_paths == [Path("/tmp/inst/tmux.sock")]
    # Old payloads (no key) and unset policies decode to None — "no
    # deny", not an empty-but-present list.
    assert SandboxPolicy.from_jsonable(_noop_policy().to_jsonable()).deny_unix_socket_paths is None


def test_sandbox_policy_round_trips_mask_and_recursive_fields() -> None:
    """``cwd_hidden_scan_recursive`` + ``mask_paths`` survive the wire.

    Both fields cross the parent/helper boundary as JSON. If either
    dropped out of ``to_jsonable`` / ``from_jsonable`` the helper would
    decode the recursive flag as ``False`` and the explicit masks as
    ``None`` — silently weakening the sandbox view.
    """
    from pathlib import Path

    policy = _noop_policy()
    policy.cwd_hidden_scan_recursive = True
    policy.mask_paths = [Path("/work/config/production.key")]

    decoded = SandboxPolicy.from_jsonable(policy.to_jsonable())

    assert decoded.cwd_hidden_scan_recursive is True
    assert decoded.mask_paths == [Path("/work/config/production.key")]
    # Old payloads (no key) and unset policies must decode to the safe
    # defaults: non-recursive and no explicit masks.
    baseline = SandboxPolicy.from_jsonable(_noop_policy().to_jsonable())
    assert baseline.cwd_hidden_scan_recursive is False
    assert baseline.mask_paths is None


def test_with_additional_write_roots_records_mask_scan_skip_roots() -> None:
    """A framework write root added post-resolve is excluded from the
    dotfile mask scan.

    The per-helper scratch tmpdir (holding the egress ``.egress.sock``,
    CA bundle, credential-proxy files) is folded into ``write_roots`` via
    :func:`with_additional_write_roots`. It must also land in
    ``mask_scan_skip_roots`` so the scan never masks ``.egress.sock`` and
    breaks the egress relay. The source policy stays untouched (builders
    are chained off a shared base).
    """
    from pathlib import Path

    from omnigent.inner.sandbox import with_additional_write_roots

    policy = _noop_policy()
    scratch = Path("/tmp/omnigent-helper-ab12")

    augmented = with_additional_write_roots(policy, [scratch])

    resolved = scratch.resolve(strict=False)
    assert resolved in augmented.write_roots
    assert augmented.mask_scan_skip_roots == [resolved]
    # Source policy not mutated.
    assert policy.mask_scan_skip_roots is None
    assert augmented is not policy


def test_with_denied_unix_sockets_resolves_dedupes_and_is_pure() -> None:
    """``with_denied_unix_sockets`` resolves + de-duplicates the socket
    paths and never mutates the input policy.

    The terminal calls this once per instance with the single tmux
    socket, but the helper must be safe to chain (it sits next to the
    other ``with_*`` policy builders) — so we assert it returns a fresh
    policy and leaves the source untouched, and that a repeated path
    collapses to one entry (a duplicate /dev/null mask is harmless but
    a duplicate seatbelt deny line is noise).
    """
    from pathlib import Path

    from omnigent.inner.sandbox import with_denied_unix_sockets

    policy = _noop_policy()
    sock = Path("/tmp/inst/tmux.sock")

    augmented = with_denied_unix_sockets(policy, [sock, sock])

    assert augmented.deny_unix_socket_paths == [sock.resolve(strict=False)]
    # Source policy is not mutated — builders are chained off a shared
    # base policy.
    assert policy.deny_unix_socket_paths is None
    assert augmented is not policy


# CORAL(S112): the harness socket roots every resolved policy denies
def _with_every_clone(policy: SandboxPolicy, paths: list[pathlib.Path]) -> list[SandboxPolicy]:
    from omnigent.inner.sandbox import (
        with_additional_read_roots,
        with_additional_write_files,
        with_additional_write_roots,
    )

    return [
        with_additional_read_roots(policy, paths),
        with_additional_write_roots(policy, paths),
        with_additional_write_files(policy, paths),
    ]


def test_sandbox_policy_round_trips_deny_unix_socket_roots(tmp_path: pathlib.Path) -> None:
    """The roots survive the launcher wire and every clone; an old payload has none."""
    roots = [pathlib.Path("/private/tmp/crl-x"), pathlib.Path("/private/tmp/omnigent-1")]
    policy = dataclasses.replace(_noop_policy(), deny_unix_socket_roots=roots)
    decoded = SandboxPolicy.from_jsonable(policy.to_jsonable())
    assert decoded.deny_unix_socket_roots == roots
    for clone in _with_every_clone(decoded, [tmp_path]):
        assert clone.deny_unix_socket_roots == roots
        assert clone.deny_unix_socket_roots is not decoded.deny_unix_socket_roots
    assert SandboxPolicy.from_jsonable(_noop_policy().to_jsonable()).deny_unix_socket_roots is None
    assert SandboxPolicy.from_jsonable({}).deny_unix_socket_roots is None


def test_policy_clones_keep_every_field(tmp_path: pathlib.Path) -> None:
    """A field the clone forgets to copy fails here, whichever field is added next."""
    from omnigent.inner.datamodel import CredentialProxySpec, GitSshBinding

    path = tmp_path.resolve() / "p"
    binding = GitSshBinding("h", 22, "git", "r", frozenset({"fetch"}), "/i", "/k")
    values = {
        "backend_type": "darwin_seatbelt",
        "active": True,
        "read_roots": [path / "r"],
        "write_roots": [path / "w"],
        "write_files": [path / "f"],
        "allow_network": False,
        "copy_on_write_roots": [path / "c"],
        "copy_on_write_namespace": (1, 2, 3),
        "cwd_allow_hidden": [".venv"],
        "cwd_hidden_scan_max_entries": 7,
        "cwd_hidden_scan_overflow": "error",
        "cwd_hidden_scan_recursive": True,
        "mask_paths": [path / "m"],
        "env_passthrough": ["A"],
        "spawn_env_allowlist": ["B"],
        "bind_host_proc": True,
        "egress_relay_port": 9,
        "egress_socket_path": "/e.sock",
        "git_ssh_socket_path": "/g.sock",
        "deny_unix_socket_paths": [path / "d.sock"],
        "deny_unix_socket_roots": [path / "root"],
        "credential_source_paths": [path / "s"],
        "launch_tmpdir_env": "X",
        "launch_tmpdir_parent": path / "l",
        "scratch_dir_env": "CLAUDE_CONFIG_DIR",  # CORAL(S113)
        "scratch_dir_files": ("z",),
        "scratch_dir_extra_envs": ("CLAUDE_SECURESTORAGE_CONFIG_DIR",),
        "scratch_dir_seed": ((".claude.json", str(path / "seed")),),  # CORAL(S115)
        "credential_proxy": CredentialProxySpec(entries=[]),
        "git_ssh": [binding],
        "mask_scan_skip_roots": [path / "w"],
        "private_tmpdir": path / "t",
    }
    assert set(values) == {field.name for field in dataclasses.fields(SandboxPolicy)}
    policy = SandboxPolicy(**values)  # type: ignore[arg-type]
    for clone in _with_every_clone(policy, []):
        assert clone == policy
        assert clone is not policy


def test_with_denied_unix_socket_roots_resolves_dedupes_and_is_pure() -> None:
    from omnigent.inner.sandbox import with_denied_unix_socket_roots, with_denied_unix_sockets

    policy = _noop_policy()
    root = pathlib.Path("/tmp/crl-x")

    augmented = with_denied_unix_socket_roots(policy, [root, root])

    assert augmented.deny_unix_socket_roots == [root.resolve(strict=False)]
    assert augmented.deny_unix_socket_paths is None
    assert policy.deny_unix_socket_roots is None
    assert augmented is not policy
    # Both deny lists keep their earlier entries when extended (the shared merge step).
    other = pathlib.Path("/tmp/crl-y")
    extended = with_denied_unix_sockets(with_denied_unix_sockets(augmented, [root]), [other, root])
    extended = with_denied_unix_socket_roots(extended, [other, root])
    both = [root.resolve(strict=False), other.resolve(strict=False)]
    assert extended.deny_unix_socket_roots == both
    assert extended.deny_unix_socket_paths == both


def _resolved_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, setting: str | None, kind: str
) -> list[pathlib.Path] | None:
    return _resolved_policy(monkeypatch, tmp_path, setting, kind).deny_unix_socket_roots


def _resolved_policy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, setting: str | None, kind: str
) -> SandboxPolicy:
    from omnigent.inner import sandbox
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    class _ActiveBackend:
        def resolve(self, spec: OSEnvSpec, cwd: pathlib.Path) -> SandboxPolicy:
            return dataclasses.replace(_noop_policy(), backend_type="darwin_seatbelt", active=True)

    monkeypatch.setattr(sandbox, "_get_backend", lambda name: _ActiveBackend())
    monkeypatch.setattr(sandbox, "_WARNED_ROOT_SETTINGS", set())
    if setting is None:
        monkeypatch.delenv("OMNIGENT_HARNESS_TMP_PARENT", raising=False)
    else:
        monkeypatch.setenv("OMNIGENT_HARNESS_TMP_PARENT", setting)
    spec = OSEnvSpec(type="caller_process", sandbox=OSEnvSandboxSpec(type=kind))
    return sandbox.resolve_sandbox(spec, tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX harness socket roots")
def test_resolve_sandbox_denies_the_harness_socket_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    default = pathlib.Path(f"/tmp/omnigent-{os.getuid()}").resolve(strict=False)
    configured = pathlib.Path("/tmp/crl-roots-test")

    roots = _resolved_roots(monkeypatch, tmp_path, str(configured), "darwin_seatbelt")

    assert roots == [configured.resolve(strict=False), default]
    assert _resolved_roots(monkeypatch, tmp_path, None, "darwin_seatbelt") == [default]
    assert _resolved_roots(monkeypatch, tmp_path, str(default), "darwin_seatbelt") == [default]
    assert _resolved_roots(monkeypatch, tmp_path, str(configured), "none") is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX harness socket roots")
@pytest.mark.parametrize("setting", ["loop", "~nosuchuser_omnigent/x", "deleted_cwd", "rel", "/"])
def test_harness_socket_roots_never_raise_and_keep_the_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    setting: str,
) -> None:
    """A bad setting cannot fail ``resolve_sandbox`` into an unsandboxed run; it warns."""
    default = pathlib.Path(f"/tmp/omnigent-{os.getuid()}").resolve(strict=False)
    kept = {"rel": [(tmp_path / "rel").resolve()], "/": [pathlib.Path("/")]}.get(setting, [])
    if setting == "loop":
        setting = str(tmp_path / "loop")
        pathlib.Path(setting).symlink_to(setting)
    elif setting == "deleted_cwd":
        gone = tmp_path / "gone"
        gone.mkdir()
        monkeypatch.chdir(gone)
        gone.rmdir()
        setting = "rel"
    else:
        monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING, logger="omnigent.inner.sandbox"):
        roots = _resolved_roots(monkeypatch, tmp_path, setting, "darwin_seatbelt")

    assert roots == [*kept, default]
    warnings = [record.getMessage() for record in caplog.records]
    assert any("harness socket root" in message for message in warnings), warnings
    assert not any(str(tmp_path) in message for message in warnings), warnings
    caplog.clear()
    from omnigent.inner.sandbox import _harness_socket_roots

    assert _harness_socket_roots() == roots
    assert not caplog.records, "the same setting warned twice in one process"


@pytest.mark.skipif(os.name == "nt", reason="POSIX harness socket roots")
def test_resolve_sandbox_stays_confined_when_realpath_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A root swapped mid-resolve (``realpath`` does not guard ``readlink``) keeps its spelling."""
    from omnigent.inner import sandbox

    real_realpath = os.path.realpath

    def swapped(path: object, *args: object, **kwargs: object) -> str:
        if "crl-roots-test" in str(path) or "omnigent-" in str(path):
            raise FileNotFoundError(2, "swapped while resolving")
        return real_realpath(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sandbox.os.path, "realpath", swapped)
    policy = _resolved_policy(monkeypatch, tmp_path, "/tmp/crl-roots-test", "darwin_seatbelt")
    monkeypatch.undo()

    default = pathlib.Path(f"/tmp/omnigent-{os.getuid()}")
    assert (policy.active, policy.backend_type) == (True, "darwin_seatbelt")
    assert policy.deny_unix_socket_roots == [pathlib.Path("/tmp/crl-roots-test"), default]


def test_with_private_tmpdir_grants_and_records_the_scratch(tmp_path: pathlib.Path) -> None:
    """CORAL(S112): the scratch is a write root and named, but never sent over the wire."""
    from omnigent.inner.sandbox import with_private_tmpdir

    policy = with_private_tmpdir(_noop_policy(), tmp_path / "scratch")

    resolved = (tmp_path / "scratch").resolve(strict=False)
    assert (policy.private_tmpdir, policy.write_roots) == (resolved, [resolved])
    assert "private_tmpdir" not in policy.to_jsonable()
    assert _noop_policy().private_tmpdir is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX harness socket roots")
def test_harness_socket_roots_never_raise_on_a_looping_default_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A symlink loop at the per-user default root, which anyone can plant in ``/tmp``, is kept."""
    from omnigent.runtime.harnesses import paths

    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    monkeypatch.setattr(paths, "harness_tmp_parent", lambda env=None: loop)

    assert _resolved_roots(monkeypatch, tmp_path, None, "darwin_seatbelt") == [loop]


# CORAL(S112): a failed import of the harness paths leaves the default to the profile builder
def test_harness_socket_roots_never_raise_when_the_harness_paths_cannot_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omnigent.inner.sandbox import _harness_socket_roots

    monkeypatch.setitem(sys.modules, "omnigent.runtime.harnesses.paths", None)

    assert _harness_socket_roots() == []


def test_with_spawn_env_allowlist_sets_sorted_deduped_copy() -> None:
    """``with_spawn_env_allowlist`` normalizes names and never mutates
    the input policy; ``None`` means "didn't opt in" and returns the
    policy unchanged rather than attaching an empty allowlist (which
    would prune EVERYTHING in the launcher).
    """
    from omnigent.inner.sandbox import with_spawn_env_allowlist

    policy = _noop_policy()

    untouched = with_spawn_env_allowlist(policy, None)
    # Same object back: None must not be coerced into a prune-all list.
    assert untouched is policy
    assert policy.spawn_env_allowlist is None

    augmented = with_spawn_env_allowlist(policy, ["PATH", "HOME", "PATH"])
    assert augmented.spawn_env_allowlist == ["HOME", "PATH"]
    # The source policy is not mutated — executors reuse it across
    # with_additional_* chains.
    assert policy.spawn_env_allowlist is None


def test_exec_launcher_prunes_inherited_env_to_spawn_allowlist(tmp_path) -> None:
    """The launcher chain drops env vars outside ``spawn_env_allowlist``
    before the target runs (defense in depth).

    Simulates the regression the field guards against: the launcher
    subprocess is spawned with the FULL host environment (plus a seeded
    ``FAKE_HOST_SECRET``). The real generated wrapper script must hand
    the target only the allowlisted names — if the prune in
    ``run_launcher`` is dropped, the secret shows up in the target's
    dumped environment and this test fails.
    """
    policy = _noop_policy()
    policy.spawn_env_allowlist = ["HOME", "PATH", "KEEP_ME"]
    out_file = tmp_path / "child_env.json"

    wrapper_path = create_exec_launcher(sys.executable, policy)
    dump_code = "import json,os,sys; open(sys.argv[1],'w').write(json.dumps(dict(os.environ)))"
    try:
        result = subprocess.run(
            [wrapper_path, "-c", dump_code, str(out_file)],
            capture_output=True,
            text=True,
            timeout=30,
            # The full-inheritance regression: everything the test
            # process has, plus a recognizable secret.
            env={**os.environ, "FAKE_HOST_SECRET": "PWNED", "KEEP_ME": "yes"},
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(wrapper_path)

    assert result.returncode == 0, result
    child_env = json.loads(out_file.read_text())
    # The seeded secret was pruned — the launcher enforced containment
    # even though its own environment carried the full host env.
    assert "FAKE_HOST_SECRET" not in child_env, sorted(child_env)
    # Allowlisted names still pass with their values intact (an empty
    # child env would also satisfy the absence check above).
    assert child_env.get("KEEP_ME") == "yes"
    assert child_env.get("PATH") == os.environ["PATH"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="bubblewrap is Linux-only")
def test_run_launcher_keeps_resolved_proc_bind_after_env_pruning(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proc choice survives launcher environment pruning."""
    from omnigent.inner.bwrap_sandbox import BwrapSandboxBackend
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    monkeypatch.setattr("omnigent.inner.bwrap_sandbox._LAKEBOX_MARKER", tmp_path / "absent")
    monkeypatch.setenv(HOST_SANDBOX_BACKEND_ENV, "phoenix-kubernetes")
    monkeypatch.setattr(
        "omnigent.inner.bwrap_sandbox.shutil.which", lambda _name: "/usr/bin/bwrap"
    )
    policy = BwrapSandboxBackend().resolve(
        OSEnvSpec(type="caller_process", sandbox=OSEnvSandboxSpec(type="linux_bwrap")),
        tmp_path,
    )
    policy = dataclasses.replace(policy, spawn_env_allowlist=["PATH"])
    raw = json.dumps(policy.to_jsonable(), separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode("ascii")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    captured: list[str] = []

    def _capture_exec(_file: str, argv: list[str]) -> None:
        captured.extend(argv)
        raise SystemExit

    monkeypatch.setattr("omnigent.inner.sandbox.create_private_tmpdir", lambda: scratch)
    monkeypatch.setattr(os, "execvp", _capture_exec)

    with mock.patch.dict(os.environ):
        with pytest.raises(SystemExit):
            run_launcher(encoded, sys.executable, ["-c", "pass"], cwd=str(tmp_path))
        assert HOST_SANDBOX_BACKEND_ENV not in os.environ
    assert any(
        captured[index : index + 3] == ["--bind", "/proc", "/proc"]
        for index in range(len(captured) - 2)
    )


def test_exec_launcher_without_allowlist_keeps_inherited_env(tmp_path) -> None:
    """A policy with ``spawn_env_allowlist=None`` (spawner didn't opt
    in) must NOT prune — existing launcher users (claude-sdk, terminal)
    deliberately pass rich environments at spawn time, and a prune-by-
    default would strip them and break those harnesses.
    """
    out_file = tmp_path / "child_env.json"

    wrapper_path = create_exec_launcher(sys.executable, _noop_policy())
    dump_code = "import json,os,sys; open(sys.argv[1],'w').write(json.dumps(dict(os.environ)))"
    try:
        result = subprocess.run(
            [wrapper_path, "-c", dump_code, str(out_file)],
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                "DELIBERATE_EXTRA": "kept",
                HOST_SANDBOX_BACKEND_ENV: "phoenix-kubernetes",
            },
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(wrapper_path)

    assert result.returncode == 0, result
    child_env = json.loads(out_file.read_text())
    # Opt-in contract: no allowlist, no prune.
    assert child_env.get("DELIBERATE_EXTRA") == "kept"
    assert child_env[HOST_SANDBOX_BACKEND_ENV] == "phoenix-kubernetes"


def _read_launcher(target: str) -> tuple[str, str]:
    """Create a launcher for ``target`` and return ``(path, contents)``."""
    path = create_exec_launcher(target, _noop_policy())
    return path, pathlib.Path(path).read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="POSIX shebang behaviour")
def test_exec_launcher_shebang_is_bin_sh_not_sys_executable() -> None:
    """The launcher must not name ``sys.executable`` in its shebang.

    Spawners such as the Claude Agent SDK ``execve`` this file directly.
    A ``#!<python>`` line is only executable when that python is itself
    a native binary reachable within the kernel's shebang buffer; when
    it is not, the spawn fails with an opaque ENOEXEC. ``/bin/sh`` is
    the one interpreter that always satisfies the kernel.
    """
    wrapper_path, script = _read_launcher(sys.executable)
    try:
        assert script.startswith("#!/bin/sh\n"), script
        assert f"#!{sys.executable}" not in script, script
    finally:
        with contextlib.suppress(OSError):
            os.unlink(wrapper_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX shebang behaviour")
def test_exec_launcher_runs_when_sys_executable_is_a_shell_script(tmp_path, monkeypatch) -> None:
    """A shim interpreter must still produce a runnable launcher.

    macOS refuses to run a script whose shebang interpreter is itself a
    ``#!`` script, so a python installed behind a wrapper (pyenv-style
    shims, vendored launchers) used to make every wrapped harness
    startup fail with ENOEXEC. Invoking the interpreter as an argument
    of ``/bin/sh`` removes the nesting entirely.
    """
    shim = tmp_path / "python-shim"
    shim.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(shim))

    wrapper_path, script = _read_launcher(sys.executable)
    try:
        assert script.startswith("#!/bin/sh\n"), script
        result = subprocess.run(
            [wrapper_path, "-c", "pass"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(wrapper_path)

    assert result.returncode == 0, result


@pytest.mark.skipif(os.name == "nt", reason="POSIX shebang behaviour")
def test_exec_launcher_runs_when_interpreter_path_has_a_space(tmp_path, monkeypatch) -> None:
    """A space in the interpreter path must not split the exec.

    A shebang line is split on whitespace, so ``/Applications/My
    Python/bin/python3`` resolved to ``/Applications/My``. The shell
    wrapper quotes the interpreter instead.
    """
    spaced_dir = tmp_path / "My Python"
    spaced_dir.mkdir()
    shim = spaced_dir / "python3"
    shim.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(shim))

    wrapper_path, _script = _read_launcher(sys.executable)
    try:
        result = subprocess.run(
            [wrapper_path, "-c", "pass"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(wrapper_path)

    assert result.returncode == 0, result


def test_exec_launcher_rejects_an_unnameable_interpreter(monkeypatch) -> None:
    """An empty ``sys.executable`` must fail loudly, not silently.

    Embedded interpreters leave ``sys.executable`` empty; writing the
    launcher anyway yields a file no kernel can run, and the caller
    only learns about it as ENOEXEC from an unrelated spawn.
    """
    monkeypatch.setattr(sys, "executable", "")
    with pytest.raises(OSError, match=re.escape("sys.executable is empty")):
        create_exec_launcher("/bin/true", _noop_policy())


# CORAL(S109): a target's own temp dir per launch, granted by the host pass, removed in-wrap
def _launch_policy(parent: pathlib.Path) -> SandboxPolicy:
    from omnigent.inner.sandbox import with_launch_tmpdir

    policy = dataclasses.replace(_noop_policy(), backend_type="darwin_seatbelt", active=True)
    return with_launch_tmpdir(policy, "CLAUDE_CODE_TMPDIR", parent)


def _encoded(policy: SandboxPolicy) -> str:
    raw = json.dumps(policy.to_jsonable(), separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def test_launch_tmpdir_fields_survive_the_wire_and_clones(tmp_path: pathlib.Path) -> None:
    from omnigent.inner.sandbox import with_additional_write_roots

    policy = _launch_policy(tmp_path / "h")
    for copy in (
        SandboxPolicy.from_jsonable(policy.to_jsonable()),
        with_additional_write_roots(policy, [tmp_path / "w"]),
    ):
        assert (copy.launch_tmpdir_env, copy.launch_tmpdir_parent) == (
            "CLAUDE_CODE_TMPDIR",
            tmp_path / "h",
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_create_launch_tmpdir_makes_a_fresh_private_dir_or_none(tmp_path: pathlib.Path) -> None:
    from omnigent.inner.sandbox import create_launch_tmpdir

    assert create_launch_tmpdir(_noop_policy()) is None
    first = create_launch_tmpdir(_launch_policy(tmp_path / "h"))
    second = create_launch_tmpdir(_launch_policy(tmp_path / "h"))
    assert first is not None and second is not None and first != second
    assert first.parent == tmp_path / "h"
    assert (first.stat().st_mode & 0o777) == 0o700
    assert ((tmp_path / "h").stat().st_mode & 0o777) == 0o700


def _refused(parent: pathlib.Path, caplog: pytest.LogCaptureFixture) -> bool:
    """Whether ``create_launch_tmpdir`` refused ``parent``, logging no path."""
    from omnigent.inner.sandbox import create_launch_tmpdir

    with caplog.at_level(logging.WARNING, logger="omnigent.inner.sandbox"):
        made = create_launch_tmpdir(_launch_policy(parent))
    messages = [record.getMessage() for record in caplog.records]
    assert all(str(parent) not in message for message in messages), messages
    return made is None and any("not a private directory" in m for m in messages)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
@pytest.mark.parametrize("mode", [0o777, 0o1777, 0o755, 0o750])
def test_create_launch_tmpdir_refuses_a_parent_that_is_not_mode_0700(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, mode: int
) -> None:
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(mode)

    assert _refused(parent, caplog)
    assert not list(parent.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_create_launch_tmpdir_refuses_a_planted_symlink_parent(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Even a link to a private dir is refused: whoever planted it can repoint it."""
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    (tmp_path / "planted").symlink_to(target)

    assert _refused(tmp_path / "planted", caplog)
    assert not list(target.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_create_launch_tmpdir_refuses_a_parent_another_uid_owns(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "theirs"
    parent.mkdir(mode=0o700)
    monkeypatch.setattr(os, "getuid", lambda: parent.stat().st_uid + 1)

    assert _refused(parent, caplog)
    assert not list(parent.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_create_launch_tmpdir_removes_only_its_own_orphaned_siblings(
    tmp_path: pathlib.Path,
) -> None:
    """A launch dir whose launcher is gone goes; live, unclaimed and foreign entries stay."""
    from omnigent.inner.sandbox import create_launch_tmpdir
    from omnigent.native.owner_claim import current_boot_id, current_pid_namespace

    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()

    def claimed_dir(name: str, pid: int) -> pathlib.Path:
        path = parent / name
        path.mkdir(mode=0o700)
        boot = current_boot_id()
        claim = f"{pid}\npid_ns={current_pid_namespace()}\n" + (f"boot={boot}\n" if boot else "")
        (path / ".launch-owner").write_text(claim)
        return path

    parent = tmp_path / "h"
    parent.mkdir(mode=0o700)
    orphan = claimed_dir("cdeadbeef", finished.pid)
    live = claimed_dir("clive0000", os.getpid())
    foreign = claimed_dir("ap-deadbeef", finished.pid)
    unclaimed = parent / "cnoclaim1"
    unclaimed.mkdir(mode=0o700)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (elsewhere / "keep").write_text("x")
    (parent / "csymlink1").symlink_to(elsewhere)

    made = create_launch_tmpdir(_launch_policy(parent))

    assert made is not None and made.parent == parent
    assert (made / ".launch-owner").read_text().split()[0] == str(os.getpid())
    assert not orphan.exists()
    assert live.is_dir() and foreign.is_dir() and unclaimed.is_dir()
    assert (parent / "csymlink1").is_symlink() and (elsewhere / "keep").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_run_launcher_grants_and_exports_the_launch_dir_before_the_wrap(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host pass grants only the fresh dir and names it to the target, then execs the wrap."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    seen: dict[str, object] = {}

    class _Backend:
        def prepare_launcher_policy(self, policy: SandboxPolicy) -> SandboxPolicy:
            return policy

        def wrap_launcher_argv(self, argv, policy, cwd, chdir=None, target=None):
            seen["policy"] = policy
            return ["sandbox-exec", *argv]

    def _capture_exec(_file: str, _argv: list[str]) -> None:
        launch_dir = pathlib.Path(os.environ["CLAUDE_CODE_TMPDIR"])
        seen["dir"] = launch_dir
        seen["mode"] = launch_dir.stat().st_mode & 0o777
        seen["marker"] = os.environ["OMNIGENT_LAUNCHER_LAUNCH_TMPDIR"]
        raise SystemExit

    monkeypatch.setattr("omnigent.inner.sandbox.get_backend", lambda _name: _Backend())
    monkeypatch.setattr("omnigent.inner.sandbox.create_private_tmpdir", lambda: scratch)
    monkeypatch.setattr(os, "execvp", _capture_exec)
    with mock.patch.dict(os.environ):
        with pytest.raises(SystemExit):
            run_launcher(_encoded(_launch_policy(tmp_path / "h")), "/bin/true", [])

    launch_dir = seen["dir"]
    assert isinstance(launch_dir, pathlib.Path) and launch_dir.parent == tmp_path / "h"
    assert seen["mode"] == 0o700 and seen["marker"] == str(launch_dir)
    policy = seen["policy"]
    assert isinstance(policy, SandboxPolicy)
    assert launch_dir.resolve() in policy.write_roots
    assert not [root for root in policy.write_roots if root.name.startswith("claude-")]
    # An exec that never hands off leaves nothing behind.
    assert not launch_dir.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
@pytest.mark.parametrize("target_fails", [False, True])
def test_run_launcher_removes_the_launch_dir_when_the_target_exits(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, target_fails: bool
) -> None:
    """The in-wrap pass hands the dir to the target and removes it after the target exits."""
    scratch = tmp_path / "scratch"
    launch_dir = tmp_path / "h" / "cabcdefgh"
    for path in (scratch, launch_dir / "claude-1"):
        path.mkdir(parents=True)
    (launch_dir / "claude-1" / "state.json").write_text("{}")
    seen: dict[str, str] = {}

    def _run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        seen["tmpdir"] = os.environ["CLAUDE_CODE_TMPDIR"]
        if target_fails:
            raise OSError("target vanished")
        return subprocess.CompletedProcess(argv, 3)

    monkeypatch.setattr("omnigent.inner.sandbox.activate_sandbox", lambda _policy: None)
    monkeypatch.setattr("omnigent.inner.sandbox.subprocess.run", _run)
    wrapped_env = {
        "OMNIGENT_LAUNCHER_SPAWN_WRAPPED": "1",
        "OMNIGENT_LAUNCHER_SPAWN_PRIVATE_TMPDIR": str(scratch),
        "OMNIGENT_LAUNCHER_LAUNCH_TMPDIR": str(launch_dir),
        "CLAUDE_CODE_TMPDIR": str(launch_dir),
    }
    with mock.patch.dict(os.environ, wrapped_env):
        encoded = _encoded(_launch_policy(tmp_path / "h"))
        if target_fails:
            with pytest.raises(OSError):
                run_launcher(encoded, "/bin/true", [])
        else:
            assert run_launcher(encoded, "/bin/true", []) == 3

    assert seen["tmpdir"] == str(launch_dir)
    assert not launch_dir.exists() and not scratch.exists()
    assert (tmp_path / "h").is_dir()


# CORAL(S113): the launcher gives the target a private dir in its scratch, removed with it
# CORAL(S115): seeded with copies of the given files
def _scratch_dir_policy(seed: tuple[tuple[str, pathlib.Path], ...] = ()) -> SandboxPolicy:
    from omnigent.inner.sandbox import with_scratch_dir_env

    policy = dataclasses.replace(_noop_policy(), backend_type="darwin_seatbelt", active=True)
    return with_scratch_dir_env(
        policy,
        "CLAUDE_CONFIG_DIR",
        files=["projects"],
        extra_envs=["CLAUDE_SECURESTORAGE_CONFIG_DIR"],
        seed=seed,
    )


def test_scratch_dir_fields_survive_the_wire_and_clones(tmp_path: pathlib.Path) -> None:
    """The fields travel the launcher wire and every clone; an old payload asks for no dir."""
    # CORAL(S115): the seed too, which is also a read root
    fields = ("scratch_dir_env", "scratch_dir_files", "scratch_dir_extra_envs", "scratch_dir_seed")
    seed = str(tmp_path.resolve() / "claude.json")
    policy = _scratch_dir_policy(seed=((".claude.json", tmp_path / "claude.json"),))
    assert policy.read_roots == [pathlib.Path(seed)], "the seed is not readable in the sandbox"
    decoded = SandboxPolicy.from_jsonable(policy.to_jsonable())
    for copy in (decoded, *_with_every_clone(decoded, [tmp_path])):
        assert [getattr(copy, name) for name in fields] == [
            "CLAUDE_CONFIG_DIR",
            ("projects",),
            ("CLAUDE_SECURESTORAGE_CONFIG_DIR",),
            ((".claude.json", seed),),
        ]
    for old in (_noop_policy().to_jsonable(), {}):
        for name in fields:
            old.pop(name, None)
        decoded = SandboxPolicy.from_jsonable(old)
        assert [getattr(decoded, name) for name in fields] == [None, (), (), ()]


@pytest.mark.parametrize(
    "fields",
    [
        {"scratch_dir_env": ""},
        {"scratch_dir_env": "claude_config_dir"},
        {"scratch_dir_env": "../X"},
        {"scratch_dir_env": 7},
        {"scratch_dir_env": "CLAUDE_CONFIG_DIR", "scratch_dir_files": ["../projects"]},
        {"scratch_dir_env": "CLAUDE_CONFIG_DIR", "scratch_dir_files": [".."]},
        {"scratch_dir_env": "CLAUDE_CONFIG_DIR", "scratch_dir_files": "projects"},
        {"scratch_dir_env": "CLAUDE_CONFIG_DIR", "scratch_dir_files": None},
        {"scratch_dir_env": None, "scratch_dir_files": ["projects"]},
        {"scratch_dir_env": "CLAUDE_CONFIG_DIR", "scratch_dir_extra_envs": ["lower"]},
        {"scratch_dir_env": "CLAUDE_CONFIG_DIR", "scratch_dir_extra_envs": ["../X"]},
        {"scratch_dir_env": "CLAUDE_CONFIG_DIR", "scratch_dir_extra_envs": "Y"},
        {"scratch_dir_env": None, "scratch_dir_extra_envs": ["Y"]},
        {"scratch_dir_env": "PATH"},
        {"scratch_dir_env": "CLAUDE_CONFIG_DIR", "scratch_dir_extra_envs": ["HOME"]},
    ],
)
def test_a_malformed_scratch_dir_field_is_refused(fields: dict[str, object]) -> None:
    """A payload that names its private dir wrongly fails the launch instead of losing the dir."""
    from omnigent.inner.sandbox import with_scratch_dir_env

    with pytest.raises(ValueError, match="scratch_dir"):
        SandboxPolicy.from_jsonable({**_noop_policy().to_jsonable(), **fields})
    env_name = fields["scratch_dir_env"]
    files = fields.get("scratch_dir_files", [])
    extra_envs = fields.get("scratch_dir_extra_envs", [])
    with pytest.raises(ValueError, match="scratch_dir"):
        with_scratch_dir_env(_noop_policy(), env_name, files=files, extra_envs=extra_envs)  # type: ignore[arg-type]


# CORAL(S115): a seed names distinct plain files with absolute sources; the helper normalizes
# a source, so a non-normal one is refused on the wire only
@pytest.mark.parametrize(
    ("seed", "files", "helper_refuses"),
    [
        ([["claude.json", "relative.json"]], [], True),
        ([["claude.json", "/seed/../x.json"]], [], False),
        ([["claude.json", "/seed/"]], [], False),
        ([["a/b", "/seed"]], [], True),
        ([[".", "/seed"]], [], True),
        ([["..", "/seed"]], [], True),
        ([["", "/seed"]], [], True),
        ([["a", "/seed"], ["a", "/other"]], [], True),
        ([["projects", "/seed"]], ["projects"], True),
        ([["a"]], [], None),
        ([["a", "/seed", "b"]], [], None),
        (["a"], [], None),
        ([[1, "/seed"]], [], None),
        ("a", [], None),
    ],
)
def test_a_malformed_scratch_dir_seed_is_refused(
    seed: object, files: list[str], helper_refuses: bool | None
) -> None:
    """A payload whose seed could name a path, clash or point anywhere fails the launch."""
    from omnigent.inner.sandbox import with_scratch_dir_env

    fields = {"scratch_dir_env": "CLAUDE_CONFIG_DIR", "scratch_dir_files": files}
    with pytest.raises(ValueError, match="scratch_dir_seed"):
        SandboxPolicy.from_jsonable(
            {**_noop_policy().to_jsonable(), **fields, "scratch_dir_seed": seed}
        )
    without_env = {"scratch_dir_env": None, "scratch_dir_seed": [["a", "/seed"]]}
    with pytest.raises(ValueError, match="scratch_dir"):
        SandboxPolicy.from_jsonable({**_noop_policy().to_jsonable(), **without_env})
    if helper_refuses is None:  # not a sequence of pairs, which the helper's type rules out
        return
    pairs = [tuple(pair) for pair in seed]  # type: ignore[union-attr]
    with (
        pytest.raises(ValueError, match="scratch_dir_seed")
        if helper_refuses
        else contextlib.nullcontext()
    ):
        with_scratch_dir_env(_noop_policy(), "CLAUDE_CONFIG_DIR", files=files, seed=pairs)  # type: ignore[arg-type]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
@pytest.mark.parametrize("seeded", [False, True])  # CORAL(S115)
@pytest.mark.parametrize("target_fails", [False, True])
def test_run_launcher_gives_the_target_a_private_dir_in_its_scratch(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, target_fails: bool, seeded: bool
) -> None:
    """
    The in-wrap pass overrides inherited values, and the dir goes with the scratch. A seeded
    dir holds a fresh 0600 copy of the seed, and an inherited empty secure-storage name, which
    would select the default keychain item, is overridden too.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    source = tmp_path / "seed" / "claude.json"
    source.parent.mkdir()
    source.write_text('{"mcpServers": {}}')
    source.chmod(0o644)
    seen: dict[str, object] = {}

    def _run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        private = pathlib.Path(os.environ["CLAUDE_CONFIG_DIR"])
        seen["dir"] = str(private)
        seen["store"] = os.environ["CLAUDE_SECURESTORAGE_CONFIG_DIR"]
        seen["mode"] = private.stat().st_mode & 0o777
        seen["projects_is_file"] = (private / "projects").is_file()
        copy = private / ".claude.json"  # CORAL(S115)
        if copy.exists():
            info = copy.lstat()
            seen["copy"] = (stat.S_ISREG(info.st_mode), info.st_mode & 0o777, copy.read_bytes())
        with contextlib.suppress(OSError):
            (private / "projects" / "key").mkdir(parents=True)
            seen["projects_creatable"] = True
        if target_fails:
            raise OSError("target vanished")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr("omnigent.inner.sandbox.activate_sandbox", lambda _policy: None)
    monkeypatch.setattr("omnigent.inner.sandbox.subprocess.run", _run)
    wrapped_env = {
        "OMNIGENT_LAUNCHER_SPAWN_WRAPPED": "1",
        "OMNIGENT_LAUNCHER_SPAWN_PRIVATE_TMPDIR": str(scratch),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "home" / ".claude"),
        # CORAL(S115): an empty name would select the default keychain item
        "CLAUDE_SECURESTORAGE_CONFIG_DIR": "" if seeded else str(tmp_path / "home"),
    }
    with mock.patch.dict(os.environ, wrapped_env):
        encoded = _encoded(_scratch_dir_policy(((".claude.json", source),) if seeded else ()))
        with pytest.raises(OSError) if target_fails else contextlib.nullcontext():
            assert run_launcher(encoded, "/bin/true", []) == 0

    assert seen["dir"] == seen["store"] == str(scratch.absolute() / "claude_config_dir")
    assert os.path.isabs(str(seen["dir"]))
    assert seen["mode"] == 0o700 and seen["projects_is_file"] is True
    assert "projects_creatable" not in seen
    # CORAL(S115): the copy is fresh, and the source is untouched
    assert seen.get("copy") == ((True, 0o600, source.read_bytes()) if seeded else None)
    assert not scratch.exists()
    assert not (tmp_path / "home").exists()
    assert source.read_text() == '{"mcpServers": {}}'


# CORAL(S115): a seed that is not this user's own regular file fails the launch first
@pytest.mark.skipif(os.name == "nt", reason="POSIX file types")
@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "kind", ["missing", "symlink", "fifo", "directory", "group-writable", "foreign-owner"]
)
def test_run_launcher_refuses_a_seed_that_is_not_a_regular_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """
    A FIFO is refused without waiting for a writer, so the launch fails instead of hanging. A
    seed another account owns or can write could have been planted by it, so it is refused too.
    """
    scratch, source = tmp_path / "scratch", tmp_path / "seed" / "claude.json"
    scratch.mkdir()
    source.parent.mkdir()
    # Built before the seed exists, as the executor builds it, so nothing is resolved through it.
    policy = _scratch_dir_policy(((".claude.json", source),))
    if kind == "symlink":
        (tmp_path / "real.json").write_text("{}")
        source.symlink_to(tmp_path / "real.json")
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "directory":
        source.mkdir()
    elif kind in ("group-writable", "foreign-owner"):
        source.write_text("{}")
        source.chmod(0o620 if kind == "group-writable" else 0o600)
    if kind == "foreign-owner":
        uid = os.getuid()
        monkeypatch.setattr("omnigent.inner.sandbox.os.getuid", lambda: uid + 1)
    target_runs: list[list[str]] = []

    def _run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
        target_runs.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr("omnigent.inner.sandbox.activate_sandbox", lambda _policy: None)
    monkeypatch.setattr("omnigent.inner.sandbox.subprocess.run", _run)
    wrapped_env = {
        "OMNIGENT_LAUNCHER_SPAWN_WRAPPED": "1",
        "OMNIGENT_LAUNCHER_SPAWN_PRIVATE_TMPDIR": str(scratch),
    }

    with mock.patch.dict(os.environ, wrapped_env), pytest.raises(OSError):
        run_launcher(_encoded(policy), "/bin/true", [])
    assert target_runs == [], "the target ran on a refused seed"
    assert not scratch.exists()


# CORAL(S115): the copy makes a new file, so a name already in the private dir is never reused
@pytest.mark.skipif(os.name == "nt", reason="POSIX file types")
@pytest.mark.parametrize("planted", ["file", "symlink"])
def test_a_seed_copy_never_writes_through_an_existing_target(
    tmp_path: pathlib.Path, planted: str
) -> None:
    from omnigent.inner.sandbox import _copy_seed_file

    source, outside = tmp_path / "seed.json", tmp_path / "outside.json"
    target = tmp_path / "private" / ".claude.json"
    source.write_text('{"mcpServers": {}}')
    outside.write_text("untouched")
    target.parent.mkdir()
    if planted == "file":
        target.write_text("planted")
    else:
        target.symlink_to(outside)

    with pytest.raises(FileExistsError):
        _copy_seed_file(source, target)
    assert outside.read_text() == "untouched"
    assert target.is_symlink() if planted == "symlink" else target.read_text() == "planted"


def test_run_launcher_refuses_a_private_dir_without_a_scratch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no scratch to hold it, the target never starts on a default config dir."""
    target_runs: list[list[str]] = []
    monkeypatch.setattr("omnigent.inner.sandbox.subprocess.run", target_runs.append)
    policy = dataclasses.replace(_scratch_dir_policy(), backend_type="none", active=False)

    with mock.patch.dict(os.environ), pytest.raises(RuntimeError, match="no scratch dir"):
        run_launcher(_encoded(policy), "/bin/true", [])
    assert target_runs == []
