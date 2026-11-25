"""
Cross-backend behavioral parity tests for the spawn-time sandboxes.

These tests assert the observable contract every active sandbox
backend must uphold, run through the live
:func:`omnigent.inner.os_env.create_os_environment` path so they
exercise the helper subprocess end-to-end. They are parametrized
over the active backend on the current host
(:func:`tests.inner.sandbox.conftest.active_sandbox_type`):

- ``linux_bwrap`` when the host is Linux + ``bwrap`` is on ``PATH``,
- ``darwin_seatbelt`` when the host is macOS + ``sandbox-exec`` is
  on ``PATH``.

A regression that violates the contract on either backend fails the
*same* test on the platform that runs the broken backend. The tests
do not branch on ``sys.platform`` — the fixture handles skip/run.

Tests intentionally check **observable** properties (exit codes,
stdout/stderr text, host filesystem state) and never reach into
backend internals (``--bind`` argv tokens, SBPL profile shape).
Backend-specific emit assertions live in the per-backend modules
(``tests/inner/test_bwrap_sandbox.py``,
``tests/inner/test_seatbelt_sandbox.py``).
"""

from __future__ import annotations

import asyncio  # CORAL(S116)
import contextlib
import functools
import hashlib  # CORAL(S128)
import json
import os
import plistlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import psutil
import pytest

from omnigent.host.service import _wait_for_launchd_unload
from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec
from omnigent.inner.os_env import create_os_environment
from omnigent.inner.sandbox import create_exec_launcher, resolve_sandbox
from tests.inner.sandbox.conftest import run_async

# ---------------------------------------------------------------------------
# Filesystem isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("launch_path", ["helper", "launcher"])
def test_sandbox_uses_private_desktop_runtime(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
    launch_path: str,
) -> None:
    desktop = tmp_path / "desktop"
    desktop.mkdir(mode=0o700)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={desktop}/bus")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(desktop))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = OSEnvSpec(
        type="caller_process",
        cwd=str(workspace),
        sandbox=active_sandbox_spec_factory(
            env_passthrough=["DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR"]
        ),
    )
    probe = """
import json, os, socket, stat
from pathlib import Path
runtime = Path(os.environ['XDG_RUNTIME_DIR'])
with socket.socket(socket.AF_UNIX) as sock:
    sock.bind(str(runtime / 'probe.sock'))
print(json.dumps({
    'runtime': str(runtime),
    'mode': stat.S_IMODE(runtime.stat().st_mode),
    'bus': os.environ.get('DBUS_SESSION_BUS_ADDRESS'),
}))
"""
    if launch_path == "helper":
        helper = create_os_environment(spec)
        try:
            result = run_async(helper.shell(shlex.join([sys.executable, "-c", probe])))
        finally:
            helper.close()
        assert result["exit_code"] == 0, result
        output = str(result["stdout"])
    else:
        launcher = create_exec_launcher(sys.executable, resolve_sandbox(spec, workspace))
        try:
            completed = subprocess.run(
                [launcher, "-c", probe], cwd=workspace, capture_output=True, text=True, timeout=30
            )
        finally:
            Path(launcher).unlink(missing_ok=True)
        assert completed.returncode == 0, completed.stderr
        output = completed.stdout
    observed = json.loads(output)
    assert observed["bus"] is None
    assert observed["runtime"] != str(desktop)
    assert observed["mode"] == 0o700
    assert os.environ["XDG_RUNTIME_DIR"] == str(desktop)
    assert not (desktop / "probe.sock").exists()


def test_sandbox_launcher_ignores_workspace_modules(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """Neither launcher pass, on the host or inside the wrap, imports workspace modules."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("logging", "json", "base64"):
        (workspace / f"{name}.py").write_text(f"raise ImportError('{name} loaded from the cwd')\n")
    spec = OSEnvSpec(
        type="caller_process", cwd=str(workspace), sandbox=active_sandbox_spec_factory()
    )
    launcher = create_exec_launcher(sys.executable, resolve_sandbox(spec, workspace))
    try:
        completed = subprocess.run(
            [launcher, "-c", "print('target ran')"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        Path(launcher).unlink(missing_ok=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "target ran"


def test_sandbox_blocks_shell_write_outside_cwd(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    A write to a parent-created path outside cwd / scratch fails.

    The strong shape of this test: create a sibling directory in
    the parent shell so we know it IS writable on the host (the
    parent puts a marker file there to prove it), then confirm the
    sandboxed helper cannot write to it. The assertion covers both
    the helper's exit code and the host filesystem (no new file
    appeared at the target path).

    Failure here means the backend leaked write access to an
    arbitrary host path — either by binding too much (bwrap) or by
    emitting too broad an ``allow file-write*`` rule (seatbelt).
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    # Sanity: the parent CAN write here, so a failed write inside
    # the sandbox is unambiguously the sandbox's doing.
    (outside_dir / "marker").write_text("parent-can-write")
    outside_target = outside_dir / "pwned.txt"

    os_env = create_os_environment(
        OSEnvSpec(
            type="caller_process",
            cwd=str(workspace),
            sandbox=active_sandbox_spec_factory(),
        )
    )
    try:
        result = run_async(os_env.shell(f"printf nope > {outside_target}"))
    finally:
        os_env.close()
    assert result["exit_code"] != 0, (
        f"Write to {outside_target!r} (a sibling of cwd, parent-writable) "
        "returned exit_code=0; the backend leaked an unexpected write surface. "
        f"stdout={result.get('stdout')!r} stderr={result.get('stderr')!r}"
    )
    assert not outside_target.exists(), (
        f"Host filesystem mutated at {outside_target!r}; the sandbox failed "
        "to block the write end-to-end."
    )


def test_sandbox_provides_writable_scratch_tmpdir(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    ``$TMPDIR`` resolves to a real writable directory inside the
    helper, the agent can write+read a probe file there, and the
    helper exits cleanly.

    The per-helper scratch tmpdir is the one always-writable surface
    under the spawn-time backends; regression here would break every
    "write a temp file" pattern in agent code.
    """
    os_env = create_os_environment(
        OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=active_sandbox_spec_factory(),
        )
    )
    try:
        result = run_async(
            os_env.shell(
                'printf "%s\\n" "$TMPDIR"; printf hi > "$TMPDIR/probe"; cat "$TMPDIR/probe"'
            )
        )
    finally:
        os_env.close()
    assert result["exit_code"] == 0, f"$TMPDIR write/read failed: stderr={result.get('stderr')!r}"
    lines = result["stdout"].splitlines()
    assert len(lines) >= 2
    assert lines[0].startswith("/")
    assert lines[1] == "hi"


def test_sandbox_empty_write_paths_blocks_cwd_writes_but_allows_tmpdir(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    With ``write_paths`` unset (the documented backend default), cwd
    is read-only but the scratch ``$TMPDIR`` is still writable.

    The "you wanted hermetic, here's hermetic" contract — flipping
    cwd to writable would silently undo the user's explicit choice
    of an active sandbox backend.
    """
    os_env = create_os_environment(
        OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=active_sandbox_spec_factory(),
        )
    )
    try:
        blocked = run_async(os_env.shell("printf nope > blocked.txt"))
        allowed = run_async(os_env.shell('printf ok > "$TMPDIR/probe"; cat "$TMPDIR/probe"'))
    finally:
        os_env.close()
    assert blocked["exit_code"] != 0, (
        "Write to cwd succeeded under the default (write_paths=None) — cwd should be RO."
    )
    assert allowed["exit_code"] == 0
    assert allowed["stdout"] == "ok"
    assert not (tmp_path / "blocked.txt").exists()


# ---------------------------------------------------------------------------
# S5: HOME-anchored sensitive subpath denial + read_paths dotfile masking.
#
# These are *behavioral* tests — they spawn a real sandboxed helper and
# attempt the read so a regression where the profile says "deny" but the
# kernel doesn't enforce it (wrong SBPL syntax, wrong path
# canonicalisation, wrong bwrap mount shape) fails here. The
# profile-shape unit tests in ``tests/inner/test_seatbelt_sandbox.py`` /
# ``tests/inner/test_bwrap_sandbox.py`` catch profile-generation bugs;
# these catch kernel-enforcement bugs.
# ---------------------------------------------------------------------------


def test_sandbox_blocks_home_library_when_home_read_granted_without_optin(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    S5 (darwin_seatbelt): granting ``$HOME`` in ``read_paths`` does
    NOT silently expose ``$HOME/Library`` — the kernel denies reads
    under it even though a broader allow covers the subtree.

    Spawns a real sandboxed helper, drops a known secret into
    ``$HOME/Library/Preferences/<file>``, and verifies the helper
    cannot read the secret content. A control read of a non-Library
    path under the same HOME grant succeeds — proves the deny is
    targeted and didn't accidentally lock down everything.

    Skipped on Linux because the macOS-specific ``$HOME/Library``
    layout doesn't exist there; the cross-platform dotfile defence
    is covered by the next two tests.
    """
    if active_sandbox_type != "darwin_seatbelt":
        pytest.skip(
            "$HOME/Library default-deny is macOS-specific; Linux relies "
            "on dotfile masking for credential paths (~/.aws etc.)."
        )

    fake_home = tmp_path / "home"
    (fake_home / "Library" / "Preferences").mkdir(parents=True)
    (fake_home / "Library" / "Preferences" / "com.example.creds.plist").write_text(
        "OMNI_S5_LIBRARY_SECRET=must-never-leak"
    )
    (fake_home / "Library" / "Cookies").mkdir()
    (fake_home / "Library" / "Cookies" / "Cookies.binarycookies").write_text(
        "OMNI_S5_COOKIES_SECRET=must-never-leak"
    )
    (fake_home / "Documents").mkdir()
    (fake_home / "Documents" / "report.txt").write_text(
        "OMNI_S5_DOCUMENTS_OK=visible-control-string"
    )
    monkeypatch.setenv("HOME", str(fake_home))

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = active_sandbox_spec_factory(extra_read_paths=[str(fake_home)])
    os_env = create_os_environment(
        OSEnvSpec(type="caller_process", cwd=str(workspace), sandbox=spec)
    )
    try:
        preferences_read = run_async(
            os_env.shell(
                f"cat {fake_home}/Library/Preferences/com.example.creds.plist 2>&1; echo END=$?"
            )
        )
        cookies_read = run_async(
            os_env.shell(
                f"cat {fake_home}/Library/Cookies/Cookies.binarycookies 2>&1; echo END=$?"
            )
        )
        documents_read = run_async(
            os_env.shell(f"cat {fake_home}/Documents/report.txt 2>&1; echo END=$?")
        )
    finally:
        os_env.close()

    assert "OMNI_S5_LIBRARY_SECRET=must-never-leak" not in (
        preferences_read.get("stdout", "") + preferences_read.get("stderr", "")
    ), (
        "$HOME/Library/Preferences was readable despite the default-deny. "
        f"Helper saw: stdout={preferences_read.get('stdout')!r} "
        f"stderr={preferences_read.get('stderr')!r}"
    )
    assert "OMNI_S5_COOKIES_SECRET=must-never-leak" not in (
        cookies_read.get("stdout", "") + cookies_read.get("stderr", "")
    ), (
        "$HOME/Library/Cookies was readable — the Library deny is too "
        "narrow (should cover all of Library, not specific subdirs)."
    )
    assert "OMNI_S5_DOCUMENTS_OK=visible-control-string" in documents_read.get("stdout", ""), (
        "$HOME/Documents control read failed — the Library deny is too "
        "broad and locked down the rest of HOME as a side effect. "
        f"stdout={documents_read.get('stdout')!r} stderr={documents_read.get('stderr')!r}"
    )


def test_sandbox_allows_home_library_when_explicit_optin(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    S5 (darwin_seatbelt): explicitly naming ``$HOME/Library`` (or a
    subtree under it) in ``read_paths`` opts the operator in — the
    default-deny is suppressed and reads under Library succeed.

    This is the escape hatch for legitimate workloads
    (``~/Library/Logs`` debugging tools, app-specific data analysis,
    etc.). Without this assertion a too-aggressive default could
    refuse explicit grants and break operator-intended behaviour.
    """
    if active_sandbox_type != "darwin_seatbelt":
        pytest.skip("$HOME/Library default-deny is macOS-specific.")

    fake_home = tmp_path / "home"
    (fake_home / "Library" / "Logs").mkdir(parents=True)
    (fake_home / "Library" / "Logs" / "app.log").write_text(
        "OMNI_S5_LOGS_VISIBLE=opted-in-content"
    )
    monkeypatch.setenv("HOME", str(fake_home))

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = active_sandbox_spec_factory(
        extra_read_paths=[str(fake_home), str(fake_home / "Library")]
    )
    os_env = create_os_environment(
        OSEnvSpec(type="caller_process", cwd=str(workspace), sandbox=spec)
    )
    try:
        logs_read = run_async(
            os_env.shell(f"cat {fake_home}/Library/Logs/app.log 2>&1; echo END=$?")
        )
    finally:
        os_env.close()

    assert "OMNI_S5_LOGS_VISIBLE=opted-in-content" in logs_read.get("stdout", ""), (
        "Explicit ~/Library opt-in didn't take effect. The helper should "
        "be able to read this file. "
        f"stdout={logs_read.get('stdout')!r} stderr={logs_read.get('stderr')!r}"
    )


def test_sandbox_blocks_credential_dotfiles_under_granted_read_path(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    S5 (cross-platform): granting a directory in ``read_paths`` does
    NOT expose dotfile-shaped credentials inside it — the dotfile
    masker walks every ``read_paths`` root, not just ``cwd``.

    Pre-fix behaviour: the dotfile masker was cwd-only, so
    ``read_paths: ["~/"]`` (the common shape for an agent that needs
    project siblings) silently leaked ``~/.aws/credentials`` and
    similar. This test creates a fake "home" tree at a controlled
    tmp_path location, grants it via ``read_paths``, and verifies
    that ``.aws/credentials`` is unreachable while a sibling
    non-dotfile path remains readable.
    """
    fake_tree = tmp_path / "tree"
    (fake_tree / ".aws").mkdir(parents=True)
    (fake_tree / ".aws" / "credentials").write_text(
        "[default]\naws_access_key_id=OMNI_S5_AWS_SECRET_LEAK_CANARY"
    )
    (fake_tree / ".ssh").mkdir()
    (fake_tree / ".ssh" / "id_ed25519").write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nOMNI_S5_SSH_SECRET_LEAK_CANARY\n-----END"
    )
    (fake_tree / "code").mkdir()
    (fake_tree / "code" / "app.py").write_text("OMNI_S5_NON_DOTFILE_OK=visible-control")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec = active_sandbox_spec_factory(extra_read_paths=[str(fake_tree)])
    os_env = create_os_environment(
        OSEnvSpec(type="caller_process", cwd=str(workspace), sandbox=spec)
    )
    try:
        aws_read = run_async(os_env.shell(f"cat {fake_tree}/.aws/credentials 2>&1; echo END=$?"))
        ssh_read = run_async(os_env.shell(f"cat {fake_tree}/.ssh/id_ed25519 2>&1; echo END=$?"))
        code_read = run_async(os_env.shell(f"cat {fake_tree}/code/app.py 2>&1; echo END=$?"))
    finally:
        os_env.close()

    assert "OMNI_S5_AWS_SECRET_LEAK_CANARY" not in (
        aws_read.get("stdout", "") + aws_read.get("stderr", "")
    ), (
        ".aws/credentials under a read_paths grant was readable — the "
        "dotfile masker did not walk the read_paths root. "
        f"stdout={aws_read.get('stdout')!r} stderr={aws_read.get('stderr')!r}"
    )
    assert "OMNI_S5_SSH_SECRET_LEAK_CANARY" not in (
        ssh_read.get("stdout", "") + ssh_read.get("stderr", "")
    ), ".ssh/id_ed25519 under a read_paths grant was readable — same regression as the .aws case."
    assert "OMNI_S5_NON_DOTFILE_OK=visible-control" in code_read.get("stdout", ""), (
        "Non-dotfile under the granted read_paths root was unreadable — "
        "the dotfile masker is too broad and masked code/app.py too. "
        f"stdout={code_read.get('stdout')!r} stderr={code_read.get('stderr')!r}"
    )


def test_sandbox_allows_dotfile_under_read_path_when_allowlisted(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    S5 (cross-platform): the ``cwd_allow_hidden`` opt-in extends to
    ``read_paths`` roots — naming a dotfile basename in
    ``cwd_allow_hidden`` lets the helper read that dotfile under any
    granted root, while OTHER dotfiles in the same tree stay masked.

    This is the documented escape hatch for legitimate dotfile
    workloads (an agent that has to read ``.aws/config`` for a
    region check, for example). Without this assertion a
    too-aggressive masker would refuse the operator's explicit
    opt-in and break workflows.
    """
    fake_tree = tmp_path / "tree"
    (fake_tree / ".aws").mkdir(parents=True)
    (fake_tree / ".aws" / "credentials").write_text(
        "OMNI_S5_AWS_OPTIN_VISIBLE=allowlisted-content"
    )
    (fake_tree / ".ssh").mkdir()  # NOT on the allowlist; must stay masked
    (fake_tree / ".ssh" / "id_ed25519").write_text("OMNI_S5_SSH_STILL_MASKED=must-never-leak")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # ``cwd_allow_hidden`` replaces the default ``[".venv"]`` rather
    # than merging with it (spec-self-containment), so we have to
    # re-include ``.venv`` here — without it the masker hides the
    # repo's ``.venv`` and the helper subprocess can't ``execvp``
    # its own Python interpreter.
    spec = active_sandbox_spec_factory(
        extra_read_paths=[str(fake_tree)],
        cwd_allow_hidden=[".venv", ".aws"],
    )
    os_env = create_os_environment(
        OSEnvSpec(type="caller_process", cwd=str(workspace), sandbox=spec)
    )
    try:
        aws_read = run_async(os_env.shell(f"cat {fake_tree}/.aws/credentials 2>&1; echo END=$?"))
        ssh_read = run_async(os_env.shell(f"cat {fake_tree}/.ssh/id_ed25519 2>&1; echo END=$?"))
    finally:
        os_env.close()

    assert "OMNI_S5_AWS_OPTIN_VISIBLE=allowlisted-content" in aws_read.get("stdout", ""), (
        ".aws was in cwd_allow_hidden but the helper couldn't read "
        ".aws/credentials. The allowlist is not being applied to "
        "read_paths roots — operator opt-in is broken. "
        f"stdout={aws_read.get('stdout')!r} stderr={aws_read.get('stderr')!r}"
    )
    assert "OMNI_S5_SSH_STILL_MASKED=must-never-leak" not in (
        ssh_read.get("stdout", "") + ssh_read.get("stderr", "")
    ), (
        ".ssh was NOT on the allowlist but the helper could read it — "
        "the allowlist filter is silently allowing everything."
    )


def test_sandbox_hides_user_dotfiles_in_cwd(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    The backend hides hidden files / dirs in cwd unless they're on
    the allowlist:

    - ``.env`` (file): no read of the secret content.
    - ``.aws`` (dir): credentials inside are not retrievable.
    - ``.venv`` (default allowlist entry): real content shows through.

    The two backends mask via different mechanisms (bwrap binds
    ``/dev/null`` over the path so the file looks empty; Seatbelt
    rejects reads with EPERM), but neither permits the secret string
    to surface. The assertion is on *content absence*, not on a
    specific error mode.
    """
    (tmp_path / ".env").write_text("OMNI_TEST_SECRET=super-secret-value-12345")
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "credentials").write_text(
        "[default]\naws_access_key_id=AKIA-PROBE-FAIL-IF-LEAKED"
    )
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "marker").write_text("venv-allowed")

    os_env = create_os_environment(
        OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=active_sandbox_spec_factory(),
        )
    )
    try:
        env_read = run_async(os_env.shell("cat .env 2>&1; echo END=$?"))
        aws_read = run_async(os_env.shell("cat .aws/credentials 2>&1; echo END=$?"))
        venv_read = run_async(os_env.shell("cat .venv/marker"))
    finally:
        os_env.close()

    assert "super-secret-value-12345" not in env_read.get("stdout", "")
    assert "super-secret-value-12345" not in env_read.get("stderr", "")
    assert "AKIA-PROBE-FAIL-IF-LEAKED" not in aws_read.get("stdout", "")
    assert "AKIA-PROBE-FAIL-IF-LEAKED" not in aws_read.get("stderr", "")
    assert venv_read["exit_code"] == 0
    assert venv_read["stdout"] == "venv-allowed"


# ---------------------------------------------------------------------------
# Network deny
# ---------------------------------------------------------------------------


def test_sandbox_allow_network_false_blocks_outbound_connect(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    With ``allow_network=false`` the helper cannot open an outbound
    TCP connection.

    The two backends enforce this very differently:

    - ``linux_bwrap`` adds ``--unshare-net`` so the namespace has no
      route to anywhere except loopback (and not even loopback to
      external hosts).
    - ``darwin_seatbelt`` emits ``(deny network*)`` so every
      ``connect(2)`` returns EPERM regardless of routing.

    The shared assertion is "a Python TCP connect to a routable
    public IP fails". We pick ``1.1.1.1:443`` (Cloudflare DNS) —
    it's globally reachable when network is allowed, so a clean
    "connected" return value proves the deny didn't engage.
    """
    probe = "\n".join(
        [
            "import socket, sys",
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
            "s.settimeout(3)",
            "ok = True",
            "try:",
            "    s.connect(('1.1.1.1', 443))",
            "    print('CONNECTED')",
            "except (PermissionError, OSError) as e:",
            "    print(f'BLOCKED:{type(e).__name__}')",
            "    ok = False",
            "finally:",
            "    s.close()",
            "sys.exit(0 if not ok else 1)",
        ]
    )
    spec = active_sandbox_spec_factory(allow_network=False)
    os_env = create_os_environment(
        OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=spec,
        )
    )
    try:
        result = run_async(os_env.shell(f"{sys.executable} -c {_shell_quote(probe)}"))
    finally:
        os_env.close()
    assert result["exit_code"] == 0, (
        "Outbound TCP connect succeeded under allow_network=False. The "
        "sandbox should have blocked it. "
        f"stdout={result.get('stdout')!r} stderr={result.get('stderr')!r}"
    )
    assert "BLOCKED:" in result.get("stdout", ""), (
        f"Expected BLOCKED:* sentinel, got stdout={result.get('stdout')!r}"
    )


def _shell_quote(value: str) -> str:
    """
    Quote *value* for safe inclusion in a POSIX shell command line.

    ``shlex.quote`` would do the job but pulls in a stdlib import we
    don't need elsewhere — the cases here are constrained to
    single-quoted strings with embedded newlines, so single-quoting
    plus a re-quote on any embedded quote works fine.

    :param value: Arbitrary string to embed in a shell command.
    :returns: Shell-safe single-quoted form of *value*.
    """
    return "'" + value.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------
# Process isolation
# ---------------------------------------------------------------------------

# Reads another process's arguments and environment seven ways, then its own; prints
# yes/no only. The markers come from a file, so no reader's command line holds one.
_PROCESS_READ_PROBE = """
import ctypes, pathlib, subprocess, psutil
pid, fd, env_marker, argv_marker, file_marker, service, job_marker = (
    pathlib.Path('markers').read_text().split()
)
pid, fd = int(pid), int(fd)
libc = ctypes.CDLL(None, use_errno=True)
argmax = ctypes.c_int(0)
libc.sysctlbyname(b'kern.argmax', ctypes.byref(argmax), ctypes.byref(ctypes.c_size_t(4)), None, 0)

def holds(data, *markers):
    return any(marker.encode() in data for marker in markers)

def procargs(oid):
    mib = (ctypes.c_int * 3)(1, oid, pid)  # CTL_KERN
    size = ctypes.c_size_t(argmax.value)
    data = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, data, ctypes.byref(size), None, 0) != 0:
        return False
    return holds(data.raw[: size.value], env_marker, argv_marker)

def psutil_read(read):
    try:
        return holds(repr(read()).encode(), env_marker, argv_marker)
    except psutil.Error:
        return False

def say(name, value):
    print(name, 'yes' if value else 'no')

target = psutil.Process(pid)
pgrep = subprocess.run(['pgrep', '-lf', argv_marker], capture_output=True, text=True)
job = subprocess.run(['launchctl', 'print', service], capture_output=True)
path = ctypes.create_string_buffer(1200)  # struct vnode_fdinfowithpath; vip_path at 176
count = libc.proc_listallpids(None, 0)
pids = (ctypes.c_int * (count + 64))()
count = libc.proc_listallpids(pids, ctypes.sizeof(pids))
me = psutil.Process()
say('procargs2', procargs(49))  # KERN_PROCARGS2
say('procargs', procargs(38))  # KERN_PROCARGS
say('environ', psutil_read(target.environ))
say('cmdline', psutil_read(target.cmdline))
say('pgrep', any(line.split(' ', 1)[0] == str(pid) for line in pgrep.stdout.splitlines()))
say('launchctl', holds(job.stdout, job_marker))
opened = libc.proc_pidfdinfo(pid, fd, 2, path, 1200) > 0  # PROC_PIDFDVNODEPATHINFO
say('fd_path', opened and holds(path.raw[176:], file_marker))
say('listpids', pid in pids[:count])
say('self', 'PATH' in me.environ() and bool(me.cmdline()))
"""
_OTHER_PROCESS_READS = (
    "procargs2",
    "procargs",
    "environ",
    "cmdline",
    "pgrep",
    "launchctl",
    "fd_path",
)


_LAUNCHD_LABEL = re.compile(r"test\.omnigent\.sandbox\.(\d{1,7})\.[0-9a-f]{32}")
_LAUNCHD_DIR = re.compile(r"sandbox-launchd-(\d{1,7})-[a-z0-9_]{8}")


def _sweep_stale_launchd_jobs() -> None:
    """
    Remove the launchd jobs and plist dirs of this test whose owning process is gone.

    Each name holds its owner's pid, so a killed run's leftovers go and a concurrent
    run's stay.
    """
    uid = os.getuid()
    listed = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=30)
    for line in listed.stdout.splitlines():
        label = line.rsplit("\t", 1)[-1]
        owner = _LAUNCHD_LABEL.fullmatch(label)
        if owner and not psutil.pid_exists(int(owner[1])):
            subprocess.run(
                ["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True, timeout=30
            )
    for plist_dir in Path("/private/tmp").glob("sandbox-launchd-*"):
        owner = _LAUNCHD_DIR.fullmatch(plist_dir.name)
        if not owner or psutil.pid_exists(int(owner[1])):
            continue
        with contextlib.suppress(FileNotFoundError):
            info = plist_dir.lstat()
            if stat.S_ISDIR(info.st_mode) and info.st_uid == uid:
                shutil.rmtree(plist_dir, ignore_errors=True)


@contextlib.contextmanager
def _launchd_job(marker: str) -> Iterator[str]:
    """
    Load a launchd job that never runs, with *marker* in its arguments and environment,
    and yield its service target.

    launchd refuses a plist on a volume that ignores ownership, where ``tmp_path`` can
    live, so the plist goes in a private directory under ``/private/tmp``.
    """
    owner = os.getpid()
    label = f"test.omnigent.sandbox.{owner}.{uuid.uuid4().hex}"
    domain = f"gui/{os.getuid()}"
    service_target = f"{domain}/{label}"
    plist_dir = Path(tempfile.mkdtemp(prefix=f"sandbox-launchd-{owner}-", dir="/private/tmp"))
    try:
        plist = plist_dir / f"{label}.plist"
        plist.write_bytes(
            plistlib.dumps(
                {
                    "Label": label,
                    "ProgramArguments": ["/usr/bin/true", marker],
                    "EnvironmentVariables": {"SANDBOX_TEST_MARKER": marker},
                    "RunAtLoad": False,
                }
            )
        )
        plist.chmod(0o644)
        bootstrap = subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if bootstrap.returncode != 0:
            pytest.fail(
                f"launchctl bootstrap {domain} rc={bootstrap.returncode}: "
                f"{bootstrap.stderr.strip()}; this test needs a GUI login session"
            )
        yield service_target
    finally:
        subprocess.run(["launchctl", "bootout", service_target], capture_output=True, timeout=30)
        shutil.rmtree(plist_dir, ignore_errors=True)
    # Checked only on a clean exit, so a failed unload cannot hide the test's own error.
    if not _wait_for_launchd_unload(service_target):
        pytest.fail(f"launchd still holds {label}")


# CORAL(S111): a sandboxed shell cannot read another process's command line or environment
@pytest.mark.parametrize("launch_path", ["helper", "launcher"])
def test_sandbox_cannot_read_another_process_command_line_or_environment(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    launch_path: str,
) -> None:
    """
    A seatbelt-sandboxed shell or CLI wrap cannot read a same-user process's arguments
    or environment through ``KERN_PROCARGS2``/``KERN_PROCARGS``, psutil, ``pgrep -lf``
    (sysmond), ``launchctl print`` or its fds, which all work outside the sandbox. It
    still reads its own and lists pids, and the target and the job outlive the reads.
    """
    if active_sandbox_type != "darwin_seatbelt":
        pytest.skip("procargs, sysmond, launchd and fd paths are macOS read paths")
    _sweep_stale_launchd_jobs()
    env_marker, argv_marker, file_marker, job_marker = (
        f"sandbox-{kind}-{uuid.uuid4().hex}" for kind in ("env", "argv", "file", "job")
    )
    held_file = tmp_path / f"held-{file_marker}"
    held_file.touch()
    (tmp_path / "probe.py").write_text(_PROCESS_READ_PROBE)
    probe = [sys.executable, "probe.py"]
    # The outside reader and the wrap get a minimal environment, so no real secret reaches them.
    reader_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": os.environ["PYTHONPATH"],
        "TMPDIR": tempfile.gettempdir(),
    }
    spec = OSEnvSpec(
        type="caller_process", cwd=str(tmp_path), sandbox=active_sandbox_spec_factory()
    )
    run_reader = functools.partial(
        subprocess.run, cwd=tmp_path, env=reader_env, capture_output=True, text=True, timeout=60
    )
    with contextlib.ExitStack() as cleanup:
        fd = os.open(held_file, os.O_RDONLY)
        cleanup.callback(os.close, fd)
        target = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)", argv_marker],
            env={"PATH": reader_env["PATH"], "SANDBOX_TEST_MARKER": env_marker},
            pass_fds=(fd,),
        )
        cleanup.callback(target.wait)
        cleanup.callback(target.kill)
        held = psutil.Process(target.pid)
        service = cleanup.enter_context(_launchd_job(job_marker))
        markers = (target.pid, fd, env_marker, argv_marker, file_marker, service, job_marker)
        (tmp_path / "markers").write_text(" ".join(map(str, markers)))
        outside = run_reader(probe)
        if launch_path == "helper":
            os_env = create_os_environment(spec)
            cleanup.callback(os_env.close)
            result = run_async(os_env.shell(shlex.join(probe)))
            inside, inside_detail = str(result.get("stdout", "")), result
        else:
            launcher = create_exec_launcher(sys.executable, resolve_sandbox(spec, tmp_path))
            cleanup.callback(Path(launcher).unlink, missing_ok=True)
            completed = run_reader([launcher, "probe.py"])
            inside, inside_detail = completed.stdout, completed.stderr
        job = subprocess.run(["launchctl", "print", service], capture_output=True, timeout=30)
        alive = held.is_running()
    kept = ["listpids yes", "self yes"]
    reached = [f"{read} yes" for read in _OTHER_PROCESS_READS] + kept
    refused = [f"{read} no" for read in _OTHER_PROCESS_READS] + kept
    observed_outside, observed_inside = outside.stdout.splitlines(), inside.splitlines()
    missing = [line for line in reached if line not in observed_outside]
    assert observed_outside == reached, f"failed outside: {missing}; {outside.stderr}"
    reopened = [line for line in observed_inside if line not in refused]
    assert observed_inside == refused, f"reopened inside: {reopened}; {inside_detail}"
    assert job.returncode == 0, "the launchd job was gone before the inside read ended"
    assert alive, "the target died during the reads, so a denied read proves nothing"


# CORAL(S121): looks up each Mach service, reads and writes a private named pasteboard and
# counts Spotlight's folders; prints yes/no only, never a query result.
_MACH_SERVICE_PROBE = """
import ctypes, pathlib, subprocess
board, marker = pathlib.Path('markers').read_text().split()
libc = ctypes.CDLL(None)
bootstrap = ctypes.c_uint32.in_dll(libc, 'bootstrap_port')

def run(*argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout.strip()

def pasteboard(script):
    return run('osascript', '-l', 'JavaScript', '-e', "ObjC.import('AppKit');"
               f" var p = $.NSPasteboard.pasteboardWithName('{board}'); {script}")

def say(name, value):
    print(name, 'yes' if value else 'no')

say('osascript', run('osascript', '-l', 'JavaScript', '-e', '1+1') == '2')
for name in ('pasteboard.1', 'coreservices.uasharedpasteboardmanager.xpc', 'metadata.mds',
             'spotlight.SearchAgent', 'corespotlightservice', 'coreservices.appleevents'):
    say(name, libc.bootstrap_look_up(bootstrap, f'com.apple.{name}'.encode(),
                                     ctypes.byref(ctypes.c_uint32())) == 0)
say('board_read', pasteboard('ObjC.unwrap(p.stringForType($.NSPasteboardTypeString))') == marker)
say('board_write', pasteboard(
    f"p.clearContents; p.setStringForType('written-{marker}', $.NSPasteboardTypeString)"
) == 'true')
say('spotlight', run('mdfind', '-count', 'kMDItemContentType == "public.folder"') not in ('', '0'))
say('notifyd', libc.bootstrap_look_up(bootstrap, b'com.apple.system.notification_center',
                                      ctypes.byref(ctypes.c_uint32())) == 0)
"""


def _pasteboard(board: str, script: str) -> str:
    """Run *script* against the private named pasteboard *board*, outside any sandbox."""
    js = f"ObjC.import('AppKit'); var p = $.NSPasteboard.pasteboardWithName('{board}'); {script}"
    return subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", js], capture_output=True, text=True, timeout=30
    ).stdout.strip()


# CORAL(S121): a sandboxed shell reaches neither the pasteboard, Spotlight nor Apple Events
@pytest.mark.parametrize("launch_path", ["helper", "launcher"])
def test_sandbox_cannot_reach_the_pasteboard_spotlight_or_apple_events(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    launch_path: str,
) -> None:
    """
    A seatbelt-sandboxed shell or CLI wrap can neither look up the pasteboard, Spotlight
    or Apple Events services, read or write a private named pasteboard (served by the
    general pasteboard's service), nor list files through Spotlight, which all work
    outside the sandbox; notifyd stays reachable. The user's clipboard is never touched.
    """
    if active_sandbox_type != "darwin_seatbelt":
        pytest.skip("the pasteboard, Spotlight and Apple Events are macOS Mach services")
    board, marker = f"test.omnigent.sandbox.{uuid.uuid4().hex}", f"board-{uuid.uuid4().hex}"
    (tmp_path / "probe.py").write_text(_MACH_SERVICE_PROBE)
    (tmp_path / "markers").write_text(f"{board} {marker}")
    probe = [sys.executable, "probe.py"]
    run_probe = functools.partial(
        subprocess.run,
        cwd=tmp_path,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.environ["PYTHONPATH"],
            "TMPDIR": tempfile.gettempdir(),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    spec = OSEnvSpec(
        type="caller_process", cwd=str(tmp_path), sandbox=active_sandbox_spec_factory()
    )
    put = f"p.clearContents; p.setStringForType('{marker}', $.NSPasteboardTypeString)"
    get = "ObjC.unwrap(p.stringForType($.NSPasteboardTypeString))"
    with contextlib.ExitStack() as cleanup:
        cleanup.callback(_pasteboard, board, "p.releaseGlobally")
        _pasteboard(board, put)
        outside = run_probe(probe)
        written = _pasteboard(board, get)
        _pasteboard(board, put)
        if launch_path == "helper":
            os_env = create_os_environment(spec)
            cleanup.callback(os_env.close)
            result = run_async(os_env.shell(shlex.join(probe)))
            inside, inside_detail = str(result.get("stdout", "")), result
        else:
            launcher = create_exec_launcher(sys.executable, resolve_sandbox(spec, tmp_path))
            cleanup.callback(Path(launcher).unlink, missing_ok=True)
            completed = run_probe([launcher, "probe.py"])
            inside, inside_detail = completed.stdout, completed.stderr
        kept = _pasteboard(board, get)
    reads = ["pasteboard.1", "coreservices.uasharedpasteboardmanager.xpc", "metadata.mds"]
    reads += ["spotlight.SearchAgent", "corespotlightservice", "coreservices.appleevents"]
    reads += ["board_read", "board_write", "spotlight"]
    reached = ["osascript yes", *(f"{read} yes" for read in reads), "notifyd yes"]
    refused = ["osascript yes", *(f"{read} no" for read in reads), "notifyd yes"]
    # A Mac with Spotlight indexing off lists nothing outside either; the mds lookup row still
    # shows the deny, and the osascript row that a "no" inside is not a failed launch.
    observed_outside = [
        "spotlight yes" if line == "spotlight no" else line for line in outside.stdout.splitlines()
    ]
    assert observed_outside == reached, f"failed outside: {outside.stdout}; {outside.stderr}"
    assert written == f"written-{marker}", "the outside write did not land"
    assert inside.splitlines() == refused, f"reached inside: {inside_detail}"
    assert kept == marker, "the sandboxed write reached the pasteboard"


# CORAL(S122): five Pool exits, then signals to its parent shell and a process outside; the
# alarm bounds a hang.
_SIGNAL_PROBE = """
import multiprocessing, os, signal, sys
signal.alarm(60)
def square(x):
    return x * x
if __name__ == '__main__':
    multiprocessing.set_start_method('spawn')
    for _ in range(5):
        with multiprocessing.Pool(2) as pool:
            assert sum(pool.map(square, range(10))) == 285
    for name, pid in (('parent', os.getppid()), ('outside', int(sys.argv[1]))):
        try:
            os.kill(pid, signal.SIGTERM)
        except PermissionError:
            print(name, 'refused')
"""


# CORAL(S122): a sandboxed shell signals its own children, never its parent or one outside
def test_sandbox_shell_signals_its_own_children_only(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    A seatbelt-sandboxed shell's timeout kills its hung command and a ``multiprocessing.Pool``
    exits cleanly, while a signal to its parent in the same sandbox or to a process started
    outside it is refused.
    """
    if active_sandbox_type != "darwin_seatbelt":
        pytest.skip("the signal rule is a seatbelt profile rule")
    (tmp_path / "probe.py").write_text(_SIGNAL_PROBE)
    spec = OSEnvSpec(
        type="caller_process", cwd=str(tmp_path), sandbox=active_sandbox_spec_factory()
    )
    with contextlib.ExitStack() as cleanup:
        outside = subprocess.Popen(["sleep", "120"])
        cleanup.callback(outside.wait)
        cleanup.callback(outside.kill)
        os_env = create_os_environment(spec)
        cleanup.callback(os_env.close)
        hung = run_async(os_env.shell("sleep 60", timeout=2))
        probe = run_async(os_env.shell(shlex.join([sys.executable, "probe.py", str(outside.pid)])))
        alive = outside.poll() is None
    assert hung.get("timed_out") is True, f"the timeout could not kill the command: {hung}"
    assert (
        probe.get("exit_code") == 0 and probe.get("stdout") == "parent refused\noutside refused\n"
    ), probe
    assert alive, "the sandboxed shell signalled a process outside the sandbox"


# ---------------------------------------------------------------------------
# Control sockets
# ---------------------------------------------------------------------------

# CORAL(S112): probe helpers that move a path and connect at its new place, and edit a dir
_RENAME_PROBE_HELPERS = """
def renamed(source, target, sock):
    try:
        os.rename(source, target)
    except OSError:
        return False
    try:
        return reaches(sock)
    finally:
        os.rename(target, source)

def edits(directory):
    try:
        with open(os.path.join(directory, 'f'), 'w') as handle:
            handle.write('x')
        os.rename(os.path.join(directory, 'f'), os.path.join(directory, 'g'))
        os.unlink(os.path.join(directory, 'g'))
        os.mkdir(os.path.join(directory, 'root'))
        os.rename(os.path.join(directory, 'root'), os.path.join(directory, 'kept'))
        os.rmdir(os.path.join(directory, 'kept'))
        return True
    except OSError:
        return False
"""

# CORAL(S112): connects to each named throwaway socket, binds and connects its own, and renames
# a deny-listed one and its dir; prints yes/no only. The paths come from a file.
_CONTROL_SOCKET_PROBE = """
import json, os, socket, subprocess, sys
paths = json.load(open('sockets.json'))

def reaches(path):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10)
        try:
            sock.connect(path)
            return sock.recv(2) == b'ok'
        except OSError:
            return False

def owns(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with socket.socket(socket.AF_UNIX) as server, socket.socket(socket.AF_UNIX) as client:
        try:
            server.bind(path)
            server.listen()
            client.connect(path)
            return True
        except OSError:
            return False
        finally:
            if os.path.lexists(path):
                os.unlink(path)

__RENAME_PROBE_HELPERS__
def say(name, value):
    print(name, 'yes' if value else 'no')

for name in ('conv', 'mcp', 'default', 'tmux', 'replies', 'user_tmux', 'clip'):
    say(name, reaches(paths[name]))
say('own', owns(os.path.join(os.environ['TMPDIR'], 'own.sock')))
say('nested', owns(os.path.join(os.environ['TMPDIR'], 'omnigent-terminal-nest', 'tmux.sock')))
say('under_root', owns(os.path.join(paths['under_root'], 'own.sock')))
if 'SANDBOX_TEST_LAUNCH_DIR' in os.environ:
    say('launch_dir', owns(os.path.join(os.environ['SANDBOX_TEST_LAUNCH_DIR'], 'own.sock')))
pane = os.path.dirname(paths['pane'])
moved = os.path.join(pane, 'moved.sock')
say('rename', renamed(paths['pane'], moved, moved))
# Into a write root on the pane's volume (the helper's scratch can sit on another one).
moved = os.path.join(paths['under_root'], 'moved-pane')
say('dir_rename', renamed(pane, moved, os.path.join(moved, 'tmux.sock')))
say('pane_files', edits(pane))
if sys.platform == 'darwin':
    table = subprocess.run(['/usr/sbin/netstat', '-an', '-f', 'unix'], capture_output=True)
    say('listed', os.path.basename(paths['conv']).encode() in table.stdout)
""".replace("__RENAME_PROBE_HELPERS__", _RENAME_PROBE_HELPERS)


@contextlib.contextmanager
def _listening(*paths: Path) -> Iterator[None]:
    """CORAL(S112): answer ``ok`` on each throwaway AF_UNIX path until the block exits."""
    import select
    import socket
    import threading

    servers: list[socket.socket] = []
    bound: list[Path] = []
    stop = threading.Event()

    def answer() -> None:
        while not stop.is_set():
            ready, _, _ = select.select(servers, [], [], 0.1)
            for server in ready:
                with contextlib.suppress(OSError):
                    connection, _ = server.accept()
                    with connection:
                        connection.sendall(b"ok")

    try:
        for path in paths:
            servers.append(socket.socket(socket.AF_UNIX))
            servers[-1].bind(str(path))
            bound.append(path)
            servers[-1].listen()
        thread = threading.Thread(target=answer, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=10)
    finally:
        for server in servers:
            server.close()
        for path in bound:
            path.unlink(missing_ok=True)


def _shared_dir(path: Path) -> Path:
    """CORAL(S112): *path* as this user's dir, made if missing and never removed: it is shared."""
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(), f"{path} is not ours"
    return path


def _reaches(path: Path) -> bool:
    import socket

    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10)
        try:
            sock.connect(str(path))
            return sock.recv(2) == b"ok"
        except OSError:
            return False


# CORAL(S112): no sandboxed process reaches a harness socket or another terminal's tmux server
@pytest.mark.parametrize("launch_path", ["helper", "launcher"])
def test_sandbox_cannot_connect_to_omnigent_control_sockets(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
    launch_path: str,
) -> None:
    """
    Throwaway sockets under a configured harness root, under the per-user default root, at
    Omnigent's terminal and tmux-replies shapes and at the user's tmux shape answer outside
    and are refused inside. The process's own sockets in its scratch and in write roots
    under the harness root (a grant, and on the launcher path the CLI's launch dir) still
    work, neither a deny-listed socket nor its dir can be renamed out of its deny while files
    in that dir stay editable, and ``netstat`` lists nothing. The pane dir sits in the
    launcher's ``$TMPDIR``, ahead of its scratch, as a terminal pane's does. bwrap's private
    ``/tmp`` hides every one of them. CORAL(S127): another terminal's ``clip.sock`` is
    refused on seatbelt too, as every socket that is not the process's own now is.
    """
    from omnigent.inner.sandbox import (
        with_additional_write_roots,
        with_denied_unix_sockets,
        with_launch_tmpdir,
    )
    from omnigent.runtime.harnesses.paths import resolve_harness_tmp_parent

    with contextlib.ExitStack() as cleanup:

        def throwaway_dir(prefix: str, parent: Path = Path("/tmp")) -> Path:
            path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
            cleanup.callback(shutil.rmtree, path, ignore_errors=True)
            return path

        def subdir(parent: Path, name: str) -> Path:
            (parent / name).mkdir(mode=0o700)
            return parent / name

        harness_root = throwaway_dir("sbx-h-")
        monkeypatch.setenv("OMNIGENT_HARNESS_TMP_PARENT", str(harness_root))
        default_dir = throwaway_dir("sbx-", _shared_dir(resolve_harness_tmp_parent({})))
        under_root = subdir(harness_root, "cw")
        user_tmux = subdir(throwaway_dir("sbx-u-"), f"tmux-{os.getuid()}")
        reader_tmp = throwaway_dir("sbx-o-")
        other_terminal = throwaway_dir("omnigent-terminal-sbx-")
        pane = throwaway_dir("omnigent-terminal-sbx-", reader_tmp)
        conv = subdir(harness_root, f"ap-{uuid.uuid4().hex}") / f"conv-{uuid.uuid4().hex[:8]}.sock"
        sockets = {
            "conv": conv,
            "mcp": harness_root / "mcp-1.sock",
            "default": default_dir / "s",
            "tmux": other_terminal / "tmux.sock",
            "replies": throwaway_dir("omnigent-tmux-replies-sbx-") / "s",
            "user_tmux": user_tmux / "default",
            "clip": other_terminal / "clip.sock",
            "pane": pane / "tmux.sock",
        }
        paths = {name: str(path) for name, path in sockets.items()} | {
            "under_root": str(under_root)
        }
        (tmp_path / "sockets.json").write_text(json.dumps(paths))
        (tmp_path / "probe.py").write_text(_CONTROL_SOCKET_PROBE)
        spec = OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=active_sandbox_spec_factory(write_paths=[str(under_root)]),
        )
        policy = with_additional_write_roots(resolve_sandbox(spec, tmp_path), [pane])
        policy = with_denied_unix_sockets(policy, [sockets["pane"]])
        reader_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.environ["PYTHONPATH"],
            "TMPDIR": str(reader_tmp),
        }
        run_reader = functools.partial(
            subprocess.run,
            cwd=tmp_path,
            env=reader_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        cleanup.enter_context(_listening(*sockets.values()))
        outside = run_reader([sys.executable, "probe.py"])
        if launch_path == "helper":
            os_env = create_os_environment(spec, sandbox_policy=policy)
            cleanup.callback(os_env.close)
            result = run_async(os_env.shell(shlex.join([sys.executable, "probe.py"])))
            inside, inside_detail = str(result.get("stdout", "")), result
        else:
            policy = with_launch_tmpdir(policy, "SANDBOX_TEST_LAUNCH_DIR", harness_root)
            launcher = create_exec_launcher(sys.executable, policy)
            cleanup.callback(Path(launcher).unlink, missing_ok=True)
            completed = run_reader([launcher, "probe.py"])
            inside, inside_detail = completed.stdout, completed.stderr
        alive = _reaches(conv)
    kept = {"own", "nested", "under_root", "launch_dir", "pane_files"}  # CORAL(S127): no clip
    order = ["conv", "mcp", "default", "tmux", "replies", "user_tmux", "clip", "own", "nested"]
    tail = [
        "rename",
        "dir_rename",
        "pane_files",
        *(["listed"] if sys.platform == "darwin" else []),
    ]
    reached = [f"{name} yes" for name in [*order, "under_root", *tail]]
    # The launcher path must print its launch dir line, so a declined launch dir fails here.
    launch = ["launch_dir"] if launch_path == "launcher" else []
    refused = [
        f"{name} {'yes' if name in kept else 'no'}"
        for name in [*order, "under_root", *launch, *tail]
    ]
    observed_outside, observed_inside = outside.stdout.splitlines(), inside.splitlines()
    assert observed_outside == reached, f"failed outside: {outside.stdout}; {outside.stderr}"
    assert observed_inside == refused, f"inside: {observed_inside}; {inside_detail}"
    assert alive, "a listener died during the run, so a refused connect proves nothing"


# CORAL(S127): connects to each named throwaway socket (stream and datagram, through a symlink
# and a hard link it makes), binds and connects its own, reads descriptors it was handed, and
# moves a dir above a masked socket; prints yes/no only. The paths come from a file.
_OTHER_PROGRAMS_PROBE = """
import json, os, socket, sys
paths = json.load(open('sockets.json'))

def reaches(path, answers=True):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10)
        try:
            sock.connect(path)
            return not answers or sock.recv(2) == b'ok'
        except OSError:
            return False

def datagram(path, connect):
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        try:
            if connect:
                sock.connect(path)
            else:
                sock.sendto(b'x', path)
            return True
        except OSError:
            return False

def owns(path):
    with socket.socket(socket.AF_UNIX) as server, socket.socket(socket.AF_UNIX) as client:
        try:
            server.bind(path)
            server.listen()
            client.connect(path)
            return True
        except OSError:
            return False
        finally:
            if os.path.lexists(path):
                os.unlink(path)

def linked(link, target, name):
    try:
        link(target, name)
    except OSError:
        return False
    try:
        return reaches(name)
    finally:
        os.unlink(name)

def handed(path):
    fds = []
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10)
        try:
            sock.connect(path)
            fds = socket.recv_fds(sock, 1, 1)[1]
            return bool(fds) and os.read(fds[0], 2) == b'ok'
        except OSError:
            return False
        finally:
            for fd in fds:
                os.close(fd)
__RENAME_PROBE_HELPERS__
def say(name, value):
    print(name, 'yes' if value else 'no')

for name in paths['others']:
    say(name, reaches(paths[name]))
say('datagram_connect', datagram(paths['datagram'], True))
say('datagram_sendto', datagram(paths['datagram'], False))
# By relative names, so the paths fit sun_path wherever the cwd is.
say('symlink', linked(os.symlink, paths['docker'], 'l'))
say('own_scratch', owns(os.path.join(os.environ['TMPDIR'], 'o.sock')))
say('own_cwd', owns('o.sock'))
say('pane_clip', reaches(paths['pane_clip']))
if sys.platform == 'darwin':
    say('resolver', reaches('/var/run/mDNSResponder', answers=False))
    for name in paths['in_root']:
        say(name, reaches(paths[name]))
    say('hard_link', linked(os.link, paths['tmux'], os.path.join(paths['root'], 'h')))
    say('planted_link', reaches(paths['planted_link']))
    say('passed_fd', handed(paths['passer']))
    if 'SANDBOX_TEST_INHERITED_SOCKET' in os.environ:
        say('inherited_fd', os.read(0, 2) == b'ok')
    say('root_files', edits(paths['root']))
    say('root_own', owns(os.path.join(paths['root'], 'o.sock')))
    say('fork_root', owns(os.path.join(paths['fork_root'], 'o.sock')))
    for name, source, target, sock in paths['moves']:
        say(name, renamed(source, target, sock))
    say('masked_after', reaches(paths['masked']) or reaches(paths['masked_nested']))
""".replace("__RENAME_PROBE_HELPERS__", _RENAME_PROBE_HELPERS)


# CORAL(S127): confstr's number for the macOS per-user temp dir; Python has no name for it
_CS_DARWIN_USER_TEMP_DIR = 65537


@contextlib.contextmanager
def _passing_descriptors(path: Path, target: Path) -> Iterator[None]:
    """CORAL(S127): hand each client of *path* a descriptor already connected to *target*."""
    import socket
    import threading

    stop = threading.Event()
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        server.listen()
        server.settimeout(0.1)

        def serve() -> None:
            while not stop.is_set():
                with contextlib.suppress(OSError), contextlib.ExitStack() as opened:
                    connection = opened.enter_context(server.accept()[0])
                    peer = opened.enter_context(socket.socket(socket.AF_UNIX))
                    peer.connect(str(target))
                    socket.send_fds(connection, [b"f"], [peer.fileno()])
                    # macOS drops a descriptor in flight when its sender closes first.
                    connection.settimeout(10)
                    connection.recv(1)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=10)
            path.unlink(missing_ok=True)


# CORAL(S127): a networked sandbox reaches its own Unix-domain sockets and no other program's
@pytest.mark.parametrize("launch_path", ["helper", "launcher"])
def test_sandbox_cannot_connect_to_other_programs_sockets(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
    launch_path: str,
) -> None:
    """
    Throwaway listeners at the path shapes of a ``tmux -S`` server, Docker Desktop, OrbStack,
    both ssh-agent forms, Claude Code's inbox and daemon and another terminal's clipboard
    bridge, and a datagram socket, answer outside and are refused inside, also through a
    symlink in the cwd. The process's own sockets in its scratch and in its writable cwd,
    and a pane's own named ``clip.sock``, still connect. bwrap's private ``/tmp`` hides every
    other program's socket.

    On seatbelt also: the resolver's socket connects. Inside a write root a plain socket
    connects, while a direct connect to a tmux-shaped or a terminal-shaped one, to one under
    a masked entry, and to a hard link to another program's socket (made inside, or planted
    from outside) is refused. Neither the write root nor a dir above a masked entry can be
    moved into another own dir to shed that deny, while files, dirs and the process's own
    sockets in the root are still made, renamed and removed. The home dir granted as a write
    root in another letter case reopens nothing in it, nor does a dir standing in for the
    per-user temp dir (helper path, where this process builds the profile). A forked pane's
    tree, named as a socket root, keeps its own sockets. A descriptor a peer passes, or one
    inherited as stdin, still works: only ``connect`` is refused. Every listener sits under
    a throwaway dir, the Docker, OrbStack and Claude Code shapes under a throwaway home.
    """
    import dataclasses
    import pwd
    import socket

    from omnigent.inner.sandbox import (
        with_additional_write_roots,
        with_allowed_unix_sockets,
        with_denied_unix_sockets,
    )

    seatbelt = active_sandbox_type == "darwin_seatbelt"
    real_homes = {Path.home().resolve(), Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()}
    with contextlib.ExitStack() as cleanup:

        def throwaway_dir(prefix: str, parent: Path = Path("/tmp")) -> Path:
            path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
            cleanup.callback(shutil.rmtree, path, ignore_errors=True)
            return path

        def subdir(parent: Path, *names: str) -> Path:
            parent.joinpath(*names).mkdir(mode=0o700, parents=True)
            return parent.joinpath(*names)

        home, agents, root, spare = (throwaway_dir(f"sbx-{kind}-") for kind in "mawx")
        reader_tmp = throwaway_dir("sbx-o-")
        pane = throwaway_dir("omnigent-terminal-sbx-", reader_tmp)
        fork_root = subdir(pane, "root")
        # The helper path builds the profile in this process, so only it can be shown a
        # stand-in for the per-user temp dir.
        user_temp = throwaway_dir("sbx-s-") if seatbelt and launch_path == "helper" else None
        others = {
            "tmux": throwaway_dir("sbx-t-") / "custom.sock",
            "docker": subdir(home, ".docker", "run") / "docker.sock",
            "orbstack": subdir(home, ".orbstack", "run") / "docker.sock",
            "ssh_agent": subdir(agents, "ssh-AbCdEfGhIjKl") / "agent.12345",
            "launchd_agent": subdir(agents, "com.apple.launchd.AbCdEfGhIj") / "Listeners",
            "claude_inbox": subdir(home, ".claude", "cc-socks") / "12345.sock",
            "claude_daemon": subdir(agents, f"cc-daemon-{os.getuid()}", "x") / "control.sock",
            "other_clip": throwaway_dir("omnigent-terminal-sbx-") / "clip.sock",
        }
        in_root = {
            "root_socket": root / "svc.sock",
            "root_tmux": subdir(root, f"tmux-{os.getuid()}") / "default",
            "root_terminal": subdir(root, "sub", "omnigent-terminal-zz") / "tmux.sock",
            "masked": subdir(root, ".devenv", "state") / "pc.sock",
            "masked_nested": subdir(root, "sub", "keys") / "k.sock",
            "home_socket": subdir(home, "run") / "app.sock",
            **({"user_temp_socket": user_temp / "ipc.sock"} if user_temp else {}),
        }
        moves = [
            ("root_moved", root, spare / "w", spare / "w" / ".devenv" / "state" / "pc.sock"),
            ("parent_moved", root / "sub", spare / "s", spare / "s" / "keys" / "k.sock"),
        ]
        own = {"pane_clip": pane / "clip.sock", "pane": pane / "tmux.sock"}
        datagram, passer, planted = agents / "log", root / "fd.sock", root / "p"
        sockets = others | in_root | own | {"datagram": datagram, "passer": passer}
        assert not [
            path
            for path in sockets.values()
            if any(path.resolve().is_relative_to(real_home) for real_home in real_homes)
        ], "a test socket sits under the real home"
        paths = {name: str(path) for name, path in sockets.items()} | {
            "others": list(others),
            "in_root": list(in_root),
            "root": str(root),
            "planted_link": str(planted),
            "fork_root": str(fork_root),
            "moves": [[name, *map(str, move)] for name, *move in moves],
        }
        (tmp_path / "sockets.json").write_text(json.dumps(paths))
        (tmp_path / "probe.py").write_text(_OTHER_PROGRAMS_PROBE)
        reader_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.environ["PYTHONPATH"],
            "TMPDIR": str(reader_tmp),
        }
        write_paths = ["."]
        if seatbelt:
            # The profile builder reads the home from its environment on both launch paths.
            monkeypatch.setenv("HOME", str(home))
            reader_env["HOME"] = str(home)
            write_paths += [str(root), str(spare), str(home.parent / home.name.upper())]
        if user_temp is not None:
            write_paths.append(str(user_temp))
            real_confstr = os.confstr
            monkeypatch.setattr(
                os,
                "confstr",
                lambda name: (
                    f"{user_temp}/" if name == _CS_DARWIN_USER_TEMP_DIR else real_confstr(name)
                ),
            )
        spec = OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=active_sandbox_spec_factory(write_paths=write_paths),
        )
        policy = with_additional_write_roots(resolve_sandbox(spec, tmp_path), [pane])
        policy = with_denied_unix_sockets(policy, [own["pane"]])
        policy = with_allowed_unix_sockets(policy, [own["pane_clip"]], roots=[fork_root])
        if seatbelt:
            masked_dir = in_root["masked_nested"].parent.resolve()
            policy = dataclasses.replace(policy, mask_paths=[masked_dir])
        cleanup.enter_context(_listening(*others.values(), *in_root.values(), *own.values()))
        cleanup.enter_context(_passing_descriptors(passer, others["tmux"]))
        receiver = cleanup.enter_context(socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM))
        receiver.bind(str(datagram))
        if seatbelt:
            os.link(others["tmux"], planted)
        inherits = seatbelt and launch_path == "launcher"
        if inherits:
            reader_env["SANDBOX_TEST_INHERITED_SOCKET"] = "1"

        def run_reader(argv: list[str]) -> subprocess.CompletedProcess[str]:
            with socket.socket(socket.AF_UNIX) as connected:
                if inherits:
                    connected.connect(str(others["tmux"]))
                return subprocess.run(
                    argv,
                    cwd=tmp_path,
                    env=reader_env,
                    stdin=connected if inherits else subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

        outside = run_reader([sys.executable, "probe.py"])
        if launch_path == "helper":
            os_env = create_os_environment(spec, sandbox_policy=policy)
            cleanup.callback(os_env.close)
            result = run_async(os_env.shell(shlex.join([sys.executable, "probe.py"])))
            inside, inside_detail = str(result.get("stdout", "")), result
        else:
            launcher = create_exec_launcher(sys.executable, policy)
            cleanup.callback(Path(launcher).unlink, missing_ok=True)
            completed = run_reader([launcher, "probe.py"])
            inside, inside_detail = completed.stdout, completed.stderr
        alive = _reaches(others["tmux"]) and _reaches(own["pane_clip"])
    lines = [(name, False) for name in (*others, "datagram_connect", "datagram_sendto", "symlink")]
    lines += [(name, True) for name in ("own_scratch", "own_cwd", "pane_clip")]
    if seatbelt:
        refused = [name for name in in_root if name != "root_socket"]
        lines += [("resolver", True), ("root_socket", True)]
        lines += [(name, False) for name in (*refused, "hard_link", "planted_link")]
        lines += [("passed_fd", True), *([("inherited_fd", True)] if inherits else [])]
        lines += [(name, True) for name in ("root_files", "root_own", "fork_root")]
        lines += [(name, False) for name in ("root_moved", "parent_moved", "masked_after")]
    reached = [f"{name} yes" for name, _ in lines]
    kept = [f"{name} {'yes' if keeps else 'no'}" for name, keeps in lines]
    observed_outside, observed_inside = outside.stdout.splitlines(), inside.splitlines()
    assert observed_outside == reached, f"failed outside: {outside.stdout}; {outside.stderr}"
    assert observed_inside == kept, f"inside: {observed_inside}; {inside_detail}"
    assert alive, "a listener died during the run, so a refused connect proves nothing"


# CORAL(S128): reads each masked throwaway file (path and digest from a file) directly and after
# moving, swapping, linking, copying or cloning it or a dir above it, then does ordinary edits;
# prints yes, no or some. ``inside``, it also tries writes and leaves its last move in place.
_MASKED_ENTRY_PROBE = """
import contextlib, ctypes, hashlib, json, os, shutil, subprocess, sys
paths = json.load(open('paths.json'))
libc = ctypes.CDLL(None, use_errno=True)
join, darwin, inside = os.path.join, sys.platform == 'darwin', sys.argv[1:] == ['inside']
work, spare = paths['work'], paths['spare']

def reads(path, name):
    found = False
    with contextlib.suppress(OSError), open(path, 'rb') as handle:
        found = hashlib.sha256(handle.read()).hexdigest() == paths['digests'][name]
    if inside and name in paths['masked']:
        with contextlib.suppress(OSError):
            os.close(os.open(path, os.O_WRONLY | os.O_TRUNC))
    return found

def reaches(found):
    hits = [reads(path, name) for path, name in found]
    return all(hits) or (any(hits) and 'some')

def discard(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.lexists(path):
        os.unlink(path)

def swapped(first, second, found):
    os.mkdir(second)
    if darwin:  # RENAME_SWAP; elsewhere RENAME_EXCHANGE from AT_FDCWD
        swap, args = libc.renamex_np, (first.encode(), second.encode(), 2)
    else:
        swap, args = libc.renameat2, (-100, first.encode(), -100, second.encode(), 2)
    try:
        if swap(*args) != 0:
            return False
        try:
            return reaches(found)
        finally:
            swap(*args)
    finally:
        os.rmdir(second)

def linked(link, entry, name, found):
    try:
        link(entry, name)
    except OSError:
        return False
    try:
        return reaches(found)
    finally:
        os.unlink(name)

def copied(source, target, found):
    try:
        shutil.copytree(source, target, symlinks=True)
    except OSError:
        pass
    try:
        return reaches(found)
    finally:
        discard(target)

def cloned(source, target, found, by_fd=False):
    try:
        if by_fd:
            fd = os.open(source, os.O_RDONLY)
            made = libc.fclonefileat(fd, -2, target.encode(), 0) == 0  # into AT_FDCWD
            os.close(fd)
        else:
            made = libc.clonefile(source.encode(), target.encode(), 0) == 0
        return made and reaches(found)
    except OSError:
        return False
    finally:
        discard(target)

def saved(directory):
    target = join(directory, 'saved.txt')
    try:
        for text in ('one', 'two'):
            with open(target + '.tmp', 'w') as handle:
                handle.write(text)
            os.replace(target + '.tmp', target)
        os.unlink(target)
        return True
    except OSError:
        return False

def moves(source, target):
    try:
        os.rename(source, target)
        os.rename(target, source)
        return True
    except OSError:
        return False

def git_works(repo):
    quiet = ['-c', 'user.name=probe', '-c', 'user.email=probe@example.invalid', '-c', 'gc.auto=0']
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    steps = ['init -q -b main', 'add -A', 'commit -qm one', 'mv pkg lib', 'commit -qm two',
             'checkout -q -b side', 'rm -rq lib', 'commit -qm three', 'checkout -q main']
    try:
        os.makedirs(join(repo, 'pkg'))
        with open(join(repo, 'pkg', 'a.txt'), 'w') as handle:
            handle.write('a')
        return all(
            subprocess.run([paths['git'], *quiet, *step.split()], cwd=repo, env=env,
                           capture_output=True, timeout=60).returncode == 0
            for step in steps
        )
    except OSError:
        return False
    finally:
        shutil.rmtree(repo, ignore_errors=True)
__RENAME_PROBE_HELPERS__
def under(root):
    return [(join(root, inner), name) for name, inner in paths['in_work'].items()]

def say(name, value):
    print(name, {True: 'yes', False: 'no'}.get(value, 'some'))

sub, moved, clone = join(work, 'sub'), join(spare, 'w'), join(spare, 'c')
say('direct', reaches([(path, name) for name, path in paths['masked'].items()]))
say('root_moved', renamed(work, moved, under(moved)))
say('root_swapped', swapped(work, moved, under(moved)))
for name, target in (('parent_moved', sub + '.moved'), ('parent_moved_out', join(spare, 's'))):
    say(name, renamed(sub, target, [(join(target, 'keys', 'key.txt'), 'key')]))
for name, entry, inner in paths['entries']:
    aside = join(os.path.dirname(entry), 'aside-' + name)
    found = [(join(aside, inner) if inner else aside, name)]
    say('moved_' + name, renamed(entry, aside, found))
    say('linked_' + name, linked(os.symlink if inner else os.link, entry, aside, found))
say('copied', copied(sub, clone, [(join(clone, 'keys', 'key.txt'), 'key')]))
if darwin:
    say('root_cloned', cloned(work, clone, under(clone)))
    say('root_cloned_by_fd', cloned(work, clone, under(clone), by_fd=True))
    say('parent_cloned', cloned(sub, clone, [(join(clone, 'keys', 'key.txt'), 'key')]))
    for name, source, held in paths['clones']:
        say(name, cloned(source, clone, [(join(clone, inner), kind) for inner, kind in held]))
say('spare_files', edits(spare))
if paths['cwd_writable']:
    say('root_files', edits(work))
    say('parent_files', edits(sub) and edits(join(sub, 'keys')))
    say('atomic_save', saved(work) and saved(join(sub, 'keys')))
    say('plain_dir_renamed', moves(join(work, 'plain'), join(work, 'plain.moved')))
    say('sibling_dir_renamed', moves(join(sub, 'free'), join(sub, 'free.moved')))
    say('git_repo', git_works(join(work, 'repo')))
if darwin:
    plain = join(work, 'plain')
    say('plain_dir_cloned', cloned(plain, clone, [(join(clone, 'note.txt'), 'note')]))
    say('file_cloned', cloned(join(plain, 'note.txt'), clone, [(clone, 'note')]))
# Last: the dir above the nested masked file is moved aside and its path given a new file.
aside, key = sub + '.aside', join(sub, 'keys', 'key.txt')
replaced = planted = False
try:
    os.rename(sub, aside)
    replaced = True
    os.makedirs(os.path.dirname(key))
    with open(key, 'w') as handle:
        handle.write('planted')
    planted = True
except OSError:
    pass
say('parent_replaced', replaced and reads(join(aside, 'keys', 'key.txt'), 'key'))
say('planted_at_masked_path', planted)
if replaced and not inside:
    shutil.rmtree(sub, ignore_errors=True)
    os.rename(aside, sub)
""".replace("__RENAME_PROBE_HELPERS__", _RENAME_PROBE_HELPERS)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _masked_tree(base: Path) -> tuple[dict[str, Path], dict[str, str]]:
    """
    CORAL(S128): a throwaway tree of fake values under *base*; each file's path and digest.

    The bytes are not returned, so no assertion message or local holds one.
    """
    work, home = base / "wide" / "work", base / "home"
    files = {
        "env": work / ".env",
        "cred": work / ".secrets" / "cred",
        "key": work / "sub" / "keys" / "key.txt",
        "wide": work.parent / ".wide-secret",
        "tool": base / "tools" / ".tool-secret",
        "library": home / "Library" / "secret",
        "token": home / "creds" / "token.json",
        "note": work / "plain" / "note.txt",
    }
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fake-{uuid.uuid4().hex}")
    for plain in (work / "sub" / "free", base / "spare"):
        plain.mkdir()
    return files, {name: _digest(path) for name, path in files.items()}


def _sandbox_git() -> str:
    """CORAL(S128): a git that runs inside a sandbox; macOS's ``/usr/bin/git`` asks xcrun."""
    tools_git = "/Library/Developer/CommandLineTools/usr/bin/git"
    found = tools_git if os.path.exists(tools_git) else shutil.which("git")
    assert found, "git is not installed"
    return found


# CORAL(S128): a masked entry is neither read nor changed by moving or cloning a dir above it
@pytest.mark.parametrize(
    ("launch_path", "network", "cwd_is"),
    [
        ("helper", "network_on", "writable"),
        ("helper", "network_off", "writable"),
        ("launcher", "network_on", "writable"),
        ("launcher", "network_off", "writable"),
        ("helper", "network_on", "read_only"),
    ],
)
def test_sandbox_keeps_masked_entries_unread_after_moves_and_clones(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
    launch_path: str,
    network: str,
    cwd_is: str,
) -> None:
    """
    Fake values sit in a dotfile and a dot-directory of the cwd, in a ``mask_paths`` file two
    dirs down, in a dotfile of a read root and of a read root above the cwd, and on seatbelt
    under the home's ``Library`` and in a credential source. A probe run outside reads every
    one, directly and by each route. Inside it reads none: not directly, not after renaming
    or swapping the write root, renaming the dir above the nested file inside the root or
    into a second write root, renaming, linking or copying the entry, nor (seatbelt) after
    ``clonefile(2)`` of the root, of a dir above the nested file, of either read root, of the
    home or of the credential source's dir. Its attempts to change them leave every file's
    bytes as they were. Ordinary work still passes inside: files and dirs made, renamed and
    removed in the root and beside a masked file, atomic saves, renames of dirs that hold
    nothing masked, git in a throwaway repository, and clones of a plain dir and file.

    Last, the probe moves the dir above the nested file aside and plants a file at its path,
    and leaves that for the host to check. Seatbelt refuses the move. On Linux bwrap masks by
    a mount on the entry, which moves with the dir, so this launch still cannot read the
    file and leaves it unchanged. But once the dir above a ``mask_paths`` file is replaced, the
    real file is unmasked at its new path for every later launch, which masks only the old
    path. The row pins that as open.
    """
    import dataclasses

    seatbelt, writable = active_sandbox_type == "darwin_seatbelt", cwd_is == "writable"
    base = tmp_path.resolve()
    files, digests = _masked_tree(base)
    work, spare, home = files["env"].parent, base / "spare", base / "home"
    masked = ["env", "cred", "key", "wide", "tool", *(["library", "token"] if seatbelt else [])]
    clones = [
        ["read_root_cloned", files["tool"].parent, [[".tool-secret", "tool"]]],
        ["above_cwd_cloned", work.parent, [[".wide-secret", "wide"], ["work/.env", "env"]]],
        ["home_cloned", home, [["Library/secret", "library"]]],
        ["credential_dir_cloned", files["token"].parent, [["token.json", "token"]]],
    ]
    paths = {
        "work": str(work),
        "spare": str(spare),
        "cwd_writable": writable,
        "git": _sandbox_git(),
        "digests": digests,
        "masked": {name: str(files[name]) for name in masked},
        "in_work": {name: str(files[name].relative_to(work)) for name in ("env", "cred", "key")},
        "entries": [
            ["env", str(files["env"]), ""],
            ["cred", str(files["cred"].parent), "cred"],
            ["key", str(files["key"]), ""],
        ],
        "clones": [[name, str(source), held] for name, source, held in clones],
    }
    (work / "paths.json").write_text(json.dumps(paths))
    (work / "probe.py").write_text(_MASKED_ENTRY_PROBE)
    reader_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": os.environ["PYTHONPATH"],
        "TMPDIR": tempfile.gettempdir(),
    }
    read_paths = [str(work.parent), str(files["tool"].parent)]
    if seatbelt:
        # The profile builder reads the home from its environment on both launch paths.
        monkeypatch.setenv("HOME", str(home))
        reader_env["HOME"] = str(home)
        read_paths.append(str(home))
    spec = OSEnvSpec(
        type="caller_process",
        cwd=str(work),
        sandbox=active_sandbox_spec_factory(
            write_paths=[*(["."] if writable else []), str(spare)],
            allow_network=network == "network_on",
            extra_read_paths=read_paths,
        ),
    )
    policy = dataclasses.replace(resolve_sandbox(spec, work), mask_paths=[files["key"]])
    if seatbelt:  # bwrap has no home denial, and refuses a credential source it would mount
        policy = dataclasses.replace(policy, credential_source_paths=[files["token"]])
    run_reader = functools.partial(
        subprocess.run, cwd=work, env=reader_env, capture_output=True, text=True, timeout=120
    )

    def listing() -> list[str]:
        return sorted(str(path.relative_to(base)) for path in base.rglob("*"))

    before = listing()
    outside = run_reader([sys.executable, "probe.py"])
    left_as_found = listing() == before
    with contextlib.ExitStack() as cleanup:
        if launch_path == "helper":
            os_env = create_os_environment(spec, sandbox_policy=policy)
            cleanup.callback(os_env.close)
            result = run_async(os_env.shell(shlex.join([sys.executable, "probe.py", "inside"])))
            inside, inside_detail = str(result.get("stdout", "")), result
        else:
            launcher = create_exec_launcher(sys.executable, policy)
            cleanup.callback(Path(launcher).unlink, missing_ok=True)
            completed = run_reader([launcher, "probe.py", "inside"])
            inside, inside_detail = completed.stdout, completed.stderr

    leaks = ["direct", "root_moved", "root_swapped", "parent_moved", "parent_moved_out"]
    leaks += [f"{how}_{name}" for name in paths["in_work"] for how in ("moved", "linked")]
    leaks += ["copied"]
    ordinary = ["spare_files"]
    if seatbelt:
        leaks += ["root_cloned", "root_cloned_by_fd", "parent_cloned"]
        leaks += [str(name) for name, *_ in clones]
    if writable:
        ordinary += ["root_files", "parent_files", "atomic_save", "plain_dir_renamed"]
        ordinary += ["sibling_dir_renamed", "git_repo"]
    if seatbelt:
        ordinary += ["plain_dir_cloned", "file_cloned"]
    # Open on bwrap: its mask moves with the entry, and later launches mask only the old path.
    planted = writable and not seatbelt
    last = ["parent_replaced", "planted_at_masked_path"]
    reached = [f"{name} yes" for name in [*leaks, *ordinary, *last]]
    kept = [f"{name} no" for name in leaks] + [f"{name} yes" for name in ordinary]
    kept += ["parent_replaced no", f"planted_at_masked_path {'yes' if planted else 'no'}"]
    # CORAL(S131)
    in_root_repo = f"git_repo {'no' if seatbelt else 'yes'}"
    kept = [in_root_repo if line == "git_repo yes" else line for line in kept]
    observed_outside, observed_inside = outside.stdout.splitlines(), inside.splitlines()
    assert observed_outside == reached, f"failed outside: {outside.stdout}; {outside.stderr}"
    assert left_as_found, "the outside run did not undo its moves or remove its copies"
    assert observed_inside == kept, f"inside: {observed_inside}; {inside_detail}"
    # Checked as the probe left it: the nested file is under the dir bwrap let it move aside.
    moved_aside = work / "sub.aside"
    assert moved_aside.exists() == planted
    now_at = files | ({"key": moved_aside / "keys" / "key.txt"} if planted else {})
    changed = [name for name in files if _digest(now_at[name]) != digests[name]]
    assert not changed, f"changed from inside the sandbox: {changed}"


# CORAL(S114): reaches each loopback harness listener, calls it without its secret, reads the
# secrets it can and calls with them; prints names and HTTP statuses only. Ports from a file.
_LOOPBACK_LISTENER_PROBE = """
import base64, http.client, json, os, socket
info = json.load(open('listeners.json'))

def status(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        return conn.getresponse().status
    except OSError:
        return 0
    finally:
        conn.close()

def upgrade(port, path, token=None):
    key = base64.b64encode(os.urandom(16)).decode()
    headers = {'Connection': 'Upgrade', 'Upgrade': 'websocket',
               'Sec-WebSocket-Version': '13', 'Sec-WebSocket-Key': key}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return status(port, 'GET', path, headers)

def relay(token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return status(info['relay'], 'POST', '/tool', headers, '{"name": "echo", "arguments": {}}')

def secret(path, field=None):
    try:
        with open(path) as handle:
            return json.load(handle)[field] if field else handle.read().strip()
    except OSError:
        return None

def tcp(port):
    try:
        socket.create_connection(('127.0.0.1', port), timeout=10).close()
        return True
    except OSError:
        return False

for name in ('relay', 'attach', 'opencode', 'codex'):
    print(name, 'tcp', 'yes' if tcp(info[name]) else 'no')
print('relay anon', relay())
print('attach anon', upgrade(info['attach'], '/probe'))
print('opencode anon', status(info['opencode'], 'GET', '/api/session'))
print('codex anon', upgrade(info['codex'], '/'))
relay_token = secret(info['bridge_json'], 'token')
print('relay secret', 'yes' if relay_token else 'no')
if relay_token:
    print('relay keyed', relay(relay_token))
codex_token = secret(info['codex_token'])
print('codex secret', 'yes' if codex_token else 'no')
if codex_token:
    print('codex keyed', upgrade(info['codex'], '/', codex_token))
"""


# CORAL(S114): no sandboxed process drives a loopback harness listener without its secret
@pytest.mark.parametrize("launch_path", ["helper", "launcher"])
def test_sandbox_cannot_drive_loopback_harness_listeners(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
    launch_path: str,
) -> None:
    """
    A networked sandboxed shell or CLI wrap reaches a throwaway claude-native tool relay,
    runner direct-attach listener, ``opencode serve`` and real ``codex app-server`` (started
    through the S114 argv) over TCP, and each refuses it without its secret. Outside, the
    same probe reads the relay's ``bridge.json`` and the codex token file and is let in;
    inside, it can read neither. Each listener answers its rightful client before and after.
    """
    import asyncio
    import base64
    import http.client
    import secrets
    import threading
    import time
    from collections.abc import Coroutine
    from typing import TypeVar

    from websockets.sync.client import connect as ws_connect

    from omnigent.harnesses.claude_native import bridge as claude_bridge
    from omnigent.harnesses.codex_native import bridge as codex_bridge
    from omnigent.harnesses.codex_native.app_server import (
        CodexAppServerClient,
        _allocate_loopback_port,
        _start_codex_model_discovery_process,
        _stop_codex_model_discovery_process,
        _wait_for_discovery_listener,
        codex_ws_token_path,
    )
    from omnigent.runner.direct_attach import (
        create_direct_attach_app,
        start_direct_attach_listener,
    )

    T = TypeVar("T")
    if active_sandbox_type != "darwin_seatbelt":
        pytest.skip("measured on macOS; bwrap's view of $HOME and /tmp is checked elsewhere")
    codex, opencode = shutil.which("codex"), shutil.which("opencode")
    if codex is None or opencode is None:
        pytest.skip("needs the codex and opencode CLIs on PATH")

    def http_status(port: int, method: str, path: str, headers: dict[str, str]) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            body = '{"name": "echo", "arguments": {}}' if method == "POST" else None
            conn.request(method, path, body=body, headers=headers)
            return conn.getresponse().status
        except OSError:
            return 0
        finally:
            conn.close()

    with contextlib.ExitStack() as cleanup:
        # Under $HOME and outside every read grant, as the real data dir is.
        home_dir = Path(tempfile.mkdtemp(prefix=".omnigent-sbx-", dir=Path.home()))
        cleanup.callback(shutil.rmtree, home_dir, ignore_errors=True)
        monkeypatch.setattr(codex_bridge, "_BRIDGE_ROOT", home_dir / "codex-native")
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        cleanup.callback(loop.close)
        cleanup.callback(thread.join, 10)
        cleanup.callback(loop.call_soon_threadsafe, loop.stop)

        def on_loop(coro: Coroutine[object, object, T]) -> T:
            return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=90)

        relay_token = secrets.token_urlsafe(16)

        async def echo(name: str, arguments: object) -> object:
            return {"content": [{"type": "text", "text": name}]}

        httpd, _ = claude_bridge._start_bridge_http_server(
            claude_bridge._tool_relay_handler_factory(relay_token, echo, loop)
        )
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        cleanup.callback(httpd.server_close)
        cleanup.callback(httpd.shutdown)
        bridge_dir = claude_bridge._BRIDGE_ROOT / f"sbx-{uuid.uuid4().hex}"
        cleanup.callback(shutil.rmtree, bridge_dir, ignore_errors=True)
        claude_bridge._write_json_file(bridge_dir / "bridge.json", {"token": relay_token})

        attach_token = secrets.token_urlsafe(16)

        async def no_attach(*args: object, **kwargs: object) -> None:
            return None

        app = create_direct_attach_app(no_attach, token=attach_token, allowed_origins=frozenset())
        attach = on_loop(start_direct_attach_listener(app))
        assert attach is not None
        cleanup.callback(lambda: on_loop(attach.stop()))

        oc_home = Path(tempfile.mkdtemp(prefix="sbx-oc-"))
        cleanup.callback(shutil.rmtree, oc_home, ignore_errors=True)
        oc_port, oc_password = _allocate_loopback_port(), secrets.token_urlsafe(16)
        oc = subprocess.Popen(
            [opencode, "serve", "--hostname", "127.0.0.1", "--port", str(oc_port)],
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(oc_home),
                "OPENCODE_PASSWORD": oc_password,
                **{
                    f"XDG_{k}_HOME": str(oc_home / k) for k in ("CONFIG", "DATA", "CACHE", "STATE")
                },
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        cleanup.callback(oc.wait, 10)
        cleanup.callback(oc.terminate)
        oc_auth = {
            "Authorization": "Basic "
            + base64.b64encode(f"opencode:{oc_password}".encode()).decode()
        }

        codex_home = home_dir / "codex-home"
        codex_home.mkdir(mode=0o700)
        codex_port = _allocate_loopback_port()
        codex_url = f"ws://127.0.0.1:{codex_port}"
        discovery = on_loop(
            _start_codex_model_discovery_process(
                codex_path=codex,
                listen_url=codex_url,
                env={
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "HOME": str(home_dir),
                    "CODEX_HOME": str(codex_home),
                },
                cwd=home_dir,
            )
        )
        cleanup.callback(lambda: on_loop(_stop_codex_model_discovery_process(discovery)))
        on_loop(_wait_for_discovery_listener(discovery, codex_port))

        async def codex_initializes() -> bool:
            client = CodexAppServerClient(ws_url=codex_url)
            await client.connect()
            await client.close()
            return True

        def rightful() -> dict[str, object]:
            with ws_connect(f"ws://127.0.0.1:{attach.port}/probe?token={attach_token}"):
                pass
            return {
                "relay": http_status(
                    httpd.server_address[1],
                    "POST",
                    "/tool",
                    {"Authorization": f"Bearer {relay_token}"},
                ),
                "attach": "accepted",
                "opencode": http_status(oc_port, "GET", "/api/session", oc_auth),
                "codex": on_loop(codex_initializes()),
            }

        deadline = time.monotonic() + 60
        while http_status(oc_port, "GET", "/api/session", oc_auth) != 200:
            assert time.monotonic() < deadline, "opencode serve never answered"
            time.sleep(0.5)
        expected_rightful = {"relay": 200, "attach": "accepted", "opencode": 200, "codex": True}
        before = rightful()
        listeners = {
            "relay": httpd.server_address[1],
            "attach": attach.port,
            "opencode": oc_port,
            "codex": codex_port,
            "bridge_json": str(bridge_dir / "bridge.json"),
            "codex_token": str(codex_ws_token_path(codex_port)),
        }
        (tmp_path / "listeners.json").write_text(json.dumps(listeners))
        (tmp_path / "probe.py").write_text(_LOOPBACK_LISTENER_PROBE)
        reader_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.environ["PYTHONPATH"],
            "TMPDIR": tempfile.gettempdir(),
        }
        run_reader = functools.partial(
            subprocess.run,
            cwd=tmp_path,
            env=reader_env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        spec = OSEnvSpec(
            type="caller_process", cwd=str(tmp_path), sandbox=active_sandbox_spec_factory()
        )
        outside = run_reader([sys.executable, "probe.py"])
        if launch_path == "helper":
            os_env = create_os_environment(spec)
            assert os_env is not None
            cleanup.callback(os_env.close)
            result = run_async(os_env.shell(shlex.join([sys.executable, "probe.py"])))
            inside, inside_detail = str(result.get("stdout", "")), result
        else:
            launcher = create_exec_launcher(sys.executable, resolve_sandbox(spec, tmp_path))
            cleanup.callback(Path(launcher).unlink, missing_ok=True)
            completed = run_reader([launcher, "probe.py"])
            inside, inside_detail = completed.stdout, completed.stderr
        after = rightful()
    common = [
        *(f"{name} tcp yes" for name in ("relay", "attach", "opencode", "codex")),
        "relay anon 401",
        # The direct-attach listener closes an unauthorized handshake with 1008 before
        # accepting it, which uvicorn answers as HTTP 403.
        "attach anon 403",
        "opencode anon 401",
        "codex anon 401",
    ]
    reached = [
        *common,
        "relay secret yes",
        "relay keyed 200",
        "codex secret yes",
        "codex keyed 101",
    ]
    refused = [*common, "relay secret no", "codex secret no"]
    assert before == expected_rightful, f"a rightful client failed before the run: {before}"
    assert outside.stdout.splitlines() == reached, f"outside: {outside.stdout}; {outside.stderr}"
    assert inside.splitlines() == refused, f"inside: {inside.splitlines()}; {inside_detail}"
    assert after == expected_rightful, f"a rightful client failed after the run: {after}"


# ---------------------------------------------------------------------------
# Claude config
# ---------------------------------------------------------------------------


def _report(path: Path) -> tuple[list[str], str]:
    """The probe's verdict lines, and the config dir it named."""
    *verdicts, named = path.read_text().splitlines()
    return verdicts, named.removeprefix("config_dir ")


# CORAL(S113): code inside a Coral CLI wrap cannot reach the user's Claude config home
# CORAL(S115): nor can a non-Coral one, whose dir starts from a read-only seed
@pytest.mark.parametrize("seeded", [False, True], ids=["coral", "seeded"])
def test_claude_cli_wrap_keeps_the_claude_config_out_of_the_home(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
    claude_config_seed_source: None,
    seeded: bool,
) -> None:
    """
    Outside, the probe writes a throwaway home's installed plugin hook, a new plugin,
    ``sessions``, ``session-env``, ``backups`` and ``.claude.json``, and reads the session key,
    ``.credentials.json`` and a keychain stand-in, directly and through hard links, a symlink
    and a rename. Inside an isolated CLI wrap every one fails, though a forwarded
    ``CLAUDE_CONFIG_DIR`` names that home, and the home is unchanged. The wrap's own config
    dir is a 0700 dir in its scratch, writable, without ``projects/``, named by both config
    variables over the forwarded values, and gone after the exit. A non-Coral wrap, isolated by
    default, holds a copy of the seed made from the home's ``.claude.json``, and cannot write
    the seed itself.
    """
    import tests.e2e.coral._claude_config_probe as probe
    from omnigent.inner.claude_sdk_executor import _claude_config_seed, prepare_claude_cli_path

    home, outside_home, workspace = (tmp_path / name for name in ("home", "outside", "work"))
    workspace.mkdir()
    shutil.copy(probe.__file__, workspace / "probe.py")
    for seeded_home in (home, outside_home):
        probe.seed_claude_home(seeded_home)
    # CORAL(S115): the seed the executor writes from this home's global config, after prepare
    seed = tmp_path / "seed" / "claude.json"
    if seeded:
        server = {"type": "stdio", "command": "true", "env": {"TOKEN": "throwaway"}}
        user_config = {"mcpServers": {probe.SEED_SERVER: server}, "oauthAccount": {"a": 1}}
        (home / ".claude.json").write_text(json.dumps(user_config))
    with contextlib.ExitStack() as cleanup:
        harness_root = Path(tempfile.mkdtemp(prefix="sbx-h-", dir="/tmp"))
        cleanup.callback(shutil.rmtree, harness_root, ignore_errors=True)
        monkeypatch.setenv("OMNIGENT_HARNESS_TMP_PARENT", str(harness_root))
        monkeypatch.setenv("HOME", str(home))
        spec = OSEnvSpec(
            type="caller_process",
            cwd=str(workspace),
            sandbox=active_sandbox_spec_factory(write_paths=["."]),
        )
        # CORAL(S115): Coral asks for isolation; any other caller gets it by default.
        options = {"config_seed": seed} if seeded else {"isolate_config": True}
        prepared = prepare_claude_cli_path(sys.executable, spec, **options)  # type: ignore[arg-type]
        assert prepared.config_isolated and prepared.cli_path is not None
        cleanup.callback(Path(prepared.cli_path).unlink, missing_ok=True)
        # CORAL(S115): as in production, the wrap is built before the seed exists
        assert not seed.parent.exists(), "the seed was made before the wrap"
        if seeded:
            seed.parent.mkdir(mode=0o700)
            seed.write_text(json.dumps(_claude_config_seed({"HOME": str(home)})))
            seed.chmod(0o600)
            assert "oauthAccount" not in seed.read_text()
        before, seed_before = probe.tree(home), probe.tree(seed.parent)

        def run_probe(command: list[str], probe_home: Path, report: str, *extra: str) -> Path:
            reader_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": os.environ["PYTHONPATH"],
                "TMPDIR": tempfile.gettempdir(),
                "HOME": str(probe_home),
                # Stand in for user values the host forwards.
                "CLAUDE_CONFIG_DIR": str(probe_home / ".claude"),
                "CLAUDE_SECURESTORAGE_CONFIG_DIR": str(probe_home),
            }
            argv = [*command, "probe.py", report, str(probe_home), *extra]  # CORAL(S115)
            done = subprocess.run(
                argv, cwd=workspace, env=reader_env, capture_output=True, text=True, timeout=60
            )
            assert done.returncode == 0, done.stderr
            return workspace / report

        outside, outside_dir = _report(run_probe([sys.executable], outside_home, "outside.txt"))
        source = (str(seed),) if seeded else ()  # CORAL(S115): the probe tries the seed
        inside, inside_dir = _report(run_probe([prepared.cli_path], home, "inside.txt", *source))
    own = ["config_private", "config_writable", "projects", "config_seeded"]
    own += ["seed_source_write", "securestorage_own"]
    outside_own = ("no", "yes", "yes", "no", "no", "no")
    inside_own = ("yes", "yes", "no", "yes" if seeded else "no", "no", "yes")
    reached = [f"{name} yes" for name in probe.HOME_CHECKS] + [
        f"{name} {verdict}" for name, verdict in zip(own, outside_own, strict=True)
    ]
    refused = [f"{name} no" for name in probe.HOME_CHECKS] + [
        f"{name} {verdict}" for name, verdict in zip(own, inside_own, strict=True)
    ]
    assert outside == reached, f"failed outside: {outside}"
    assert outside_dir == str(outside_home / ".claude")
    assert inside == refused, f"reached inside: {[v for v in inside if v not in refused]}"
    assert probe.tree(home) == before, "the wrap changed the home"
    assert probe.tree(seed.parent) == seed_before, "the wrap changed the seed"
    assert Path(inside_dir).name == "claude_config_dir" and not Path(inside_dir).exists()


# CORAL(S115): the Agent SDK's version check kills the wrapped CLI before the launcher cleans up
# CORAL(S116): as does the executor's signal to the whole tree, which this stand-in ignores
@pytest.mark.timeout(120)
@pytest.mark.parametrize("signalled", ["launcher", "tree"])
def test_a_killed_version_check_leaves_no_copy_of_the_seed(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
    signalled: str,
) -> None:
    """
    As the SDK does, run the wrapped CLI with ``-v``, read one line, then terminate it. The
    stand-in CLI prints a version and its config dir, then waits for its input to close, so
    the kill always lands before the launcher's cleanup.

    CORAL(S116): the scratch names the launcher as its owner. While the stand-in, which ignores
    SIGTERM, still runs in the sweeper's pid namespace (seatbelt), a sweep keeps the scratch;
    once it has exited, a sweep removes it.
    """
    from omnigent.inner import _proc
    from omnigent.inner.claude_sdk_executor import prepare_claude_cli_path
    from omnigent.inner.sandbox import PRIVATE_TMPDIR_NAME, _remove_orphaned_launch_tmpdirs
    from omnigent.native.owner_claim import read_owner_claim
    from tests._helpers.polling import poll_until

    workspace, scratch_parent, seed = tmp_path / "work", tmp_path / "tmp", tmp_path / "seed"
    for path in (workspace, scratch_parent):
        path.mkdir()
    cli = workspace / "claude"
    cli.write_text(
        "#!/bin/sh\ntrap '' TERM\n"  # CORAL(S116)
        'printf "2.1.325 (Claude Code) %s\\n" "$CLAUDE_CONFIG_DIR"\nread _\n'
    )
    cli.chmod(0o700)
    with contextlib.ExitStack() as cleanup:
        harness_root = Path(tempfile.mkdtemp(prefix="sbx-h-", dir="/tmp"))
        cleanup.callback(shutil.rmtree, harness_root, ignore_errors=True)
        monkeypatch.setenv("OMNIGENT_HARNESS_TMP_PARENT", str(harness_root))
        sandbox = active_sandbox_spec_factory(write_paths=["."])
        spec = OSEnvSpec(type="caller_process", cwd=str(workspace), sandbox=sandbox)
        prepared = prepare_claude_cli_path(str(cli), spec, config_seed=seed / "claude.json")
        assert prepared.config_isolated and prepared.cli_path is not None
        cleanup.callback(Path(prepared.cli_path).unlink, missing_ok=True)
        seed.mkdir(mode=0o700)
        (seed / "claude.json").write_text('{"mcpServers": {}}')
        (seed / "claude.json").chmod(0o600)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": os.environ["PYTHONPATH"],
            "TMPDIR": str(scratch_parent),
            "HOME": str(tmp_path / "home"),
        }
        check = subprocess.Popen(
            [prepared.cli_path, "-v"],
            cwd=workspace,
            env=env,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert check.stdout is not None
        line = check.stdout.readline()
        if signalled == "tree":  # CORAL(S116): as the executor's teardown does
            _proc.terminate_tree(check)
        else:
            check.terminate()
        check.wait(timeout=30)
        # CORAL(S116): checked while the stand-in still waits for its input, so no cleanup has
        # run: bwrap's sandbox can outlive its monitor long enough to clean up on an EOF
        version, _, config_dir = line.rstrip("\n").partition(" (Claude Code) ")
        assert version == "2.1.325", line
        private = Path(config_dir)
        scratch = private.parent
        assert private.name == "claude_config_dir", line
        assert scratch.parent.resolve() == scratch_parent.resolve(), config_dir
        assert private.is_dir(), "the launcher cleaned up before the kill landed"
        assert not (private / ".claude.json").exists(), "the version check left a seed copy"
        # CORAL(S116): the host pass, outside any pid namespace the wrap makes, named the launcher
        claim = read_owner_claim(scratch, filename=".launch-owner")
        assert claim is not None and claim.pid == check.pid, (
            "the scratch does not name its launcher"
        )
        if active_sandbox_type == "darwin_seatbelt":
            _remove_orphaned_launch_tmpdirs(scratch_parent, PRIVATE_TMPDIR_NAME)
            assert scratch.is_dir(), "a sweep removed the scratch under its running CLI"
        # Closing its input lets a stand-in that outlived the launcher exit.
        check.communicate(timeout=30)

    def _swept() -> bool:
        _remove_orphaned_launch_tmpdirs(scratch_parent, PRIVATE_TMPDIR_NAME)
        return not scratch.exists()

    poll_until(_swept, timeout_s=10, interval_s=0.1)


# CORAL(S116): a stand-in CLI that answers the Agent SDK's control requests, POSIX sh builtins only
_CONTROL_REQUEST_CLI = """#!/bin/sh
case "$1" in -v|--version) printf '2.1.325 (Claude Code)\\n'; exit 0;; esac
while IFS= read -r line; do
  case "$line" in
    *'"control_request"'*)
      rest=${line#*'"request_id": "'}
      printf '{"type":"control_response","response":'
      printf '{"subtype":"success","request_id":"%s","response":{}}}\\n' "${rest%%'"'*}";;
  esac
done
"""
# CORAL(S116): one that outlives its input and SIGTERM, as a CLI busy shutting down would
_OUTLIVING_CLI = _CONTROL_REQUEST_CLI.replace("#!/bin/sh\n", "#!/bin/sh\ntrap '' TERM\n") + (
    "exec sleep 600\n"
)


# CORAL(S116): every launch dir and process a closed executor's CLI launches made is gone
@pytest.mark.timeout(180)
@pytest.mark.parametrize("cli_exit", ["on-eof", "never"])
def test_a_closed_executor_leaves_no_launch_scratch(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
    claude_config_seed_source: None,
    cli_exit: str,
) -> None:
    """
    Two sessions connect a seeded, sandboxed stand-in CLI through the real Agent SDK and
    launcher. Each connect's version check leaves its launch behind, and the executor removes
    it. One session closes from another task (a force close), the other in place by
    ``close()``; each one's scratch, holding the seed copy, is then gone, and so are the profile
    and launch dirs of every launch. A dead process's leftover goes; a live executor's seed stays.

    CORAL(S116): so is every process of each CLI's tree, even one that ignores its input
    closing and SIGTERM, which outlives the SDK's own close.
    """
    from omnigent.inner import _proc
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor, _ensure_sdk
    from omnigent.native.owner_claim import read_owner_claim, write_owner_claim

    workspace, temp_root, home = (tmp_path / name for name in ("work", "tmp", "home"))
    for path in (workspace, temp_root, home):
        path.mkdir()
    server = {"command": "true", "env": {"TOKEN": "throwaway"}}
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"probe": server}}))
    cli = workspace / "claude"
    cli.write_text(_CONTROL_REQUEST_CLI if cli_exit == "on-eof" else _OUTLIVING_CLI)  # CORAL(S116)
    cli.chmod(0o700)
    trees: dict[int, float] = {}  # CORAL(S116)
    dead = temp_root / "omnigent-osenv-deadbeef"
    live_seed = temp_root / "omnigent-claude-seed-0123456789abcdef"
    for path in (dead, live_seed):
        path.mkdir(mode=0o700)
    # A process that claims the dir and exits, as a killed launch does; the seed is this one's.
    claim = "import sys; from pathlib import Path; from omnigent.native.owner_claim import "
    claim += "write_owner_claim as w; w(Path(sys.argv[1]), filename='.launch-owner')"
    subprocess.run([sys.executable, "-c", claim, str(dead)], check=True, timeout=60)
    write_owner_claim(live_seed, filename=".launch-owner")
    (dead / "claude_config_dir").mkdir()
    (dead / "claude_config_dir" / ".claude.json").write_text("{}")
    scratches: dict[str, Path] = {}
    seen: dict[str, object] = {}
    with contextlib.ExitStack() as cleanup:
        harness_root = Path(tempfile.mkdtemp(prefix="sbx-h-", dir="/tmp"))
        cleanup.callback(shutil.rmtree, harness_root, ignore_errors=True)
        env = {"HOME": home, "TMPDIR": temp_root, "OMNIGENT_CLAUDE_PATH": cli}
        for name, value in {**env, "OMNIGENT_HARNESS_TMP_PARENT": harness_root}.items():
            monkeypatch.setenv(name, str(value))
        for name in (
            "CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK",
            "CLAUDE_CONFIG_DIR",
            "CLAUDE_SECURESTORAGE_CONFIG_DIR",
            "OMNIGENT_CLAUDE_SDK_NO_SANDBOX",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(tempfile, "tempdir", None)
        monkeypatch.setattr(
            "omnigent.inner.claude_sdk_executor._find_system_claude", lambda: str(cli)
        )
        spec = OSEnvSpec(
            type="caller_process",
            cwd=str(workspace),
            sandbox=active_sandbox_spec_factory(write_paths=["."]),
        )
        executor = ClaudeSDKExecutor(cwd=str(workspace), os_env=spec)
        assert executor._claude_config_isolated and executor._claude_config_seed_path is not None
        assert executor._cli_path is not None and executor._cli_path != str(cli)
        sdk = _ensure_sdk()

        async def _connect_then_close() -> None:
            try:
                for session in ("graceful", "forced"):
                    before = set(temp_root.glob("omnigent-osenv-*"))
                    options = sdk.ClaudeAgentOptions(
                        cli_path=executor._cli_path,
                        cwd=str(workspace),
                        env=dict(executor._extra_env),
                        stderr=lambda _line: None,
                    )
                    await executor._get_or_create_client(
                        sdk, session_key=session, options=options, model=None
                    )
                    new = set(temp_root.glob("omnigent-osenv-*")) - before
                    assert len(new) == 1, f"the version check's launch stayed: {len(new)} new"
                    [scratches[session]] = new
                    process = executor._clients[session].client._transport._process  # CORAL(S116)
                    trees.update(_proc.snapshot_child_tree(process))
                seen["dead"] = dead.exists()
                seen["seed copies"] = sorted(
                    (path / "claude_config_dir" / ".claude.json").is_file()
                    for path in scratches.values()
                )
                await asyncio.create_task(executor.close_session("forced"))
                seen["forced"] = scratches["forced"].exists()
                seen["graceful"] = scratches["graceful"].exists()
            finally:
                await executor.close()

        # CORAL(S116): whatever outlived the close is killed after the check
        cleanup.callback(_proc.kill_members, trees)
        run_async(_connect_then_close())
        left = _proc.live_members(trees)  # CORAL(S116)
        launch_dirs = [
            p.name for p in harness_root.iterdir() if re.fullmatch(r"c[a-z0-9_]{8}", p.name)
        ]

    assert len(trees) >= 4 and not left, f"{len(left)} of the CLIs' processes outlived close()"
    assert seen == {"dead": False, "seed copies": [True, True], "forced": False, "graceful": True}
    assert not scratches["graceful"].exists(), "the in-place close left its scratch"
    assert not list(temp_root.glob("omnigent-osenv-*"))
    assert list(temp_root.glob("omnigent-claude-seed-*")) == [live_seed]
    profiles = list(temp_root.glob("omnigent-seatbelt-profiles-*"))
    owners = [read_owner_claim(path, filename=".launch-owner") for path in profiles]
    assert [getattr(owner, "pid", None) for owner in owners] == [os.getpid()] * len(profiles)
    assert launch_dirs == []


# ---------------------------------------------------------------------------
# Env passthrough
# ---------------------------------------------------------------------------


def test_sandbox_helper_does_not_inherit_unallowlisted_env_vars(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Credentials set in the parent's environment are NOT visible to
    the helper subprocess unless the spec opts them in via
    ``env_passthrough``.

    End-to-end version of the ``build_helper_env`` unit tests in
    :mod:`tests.inner.test_os_env`: spawns a real helper through the
    active backend and reads ``env`` from inside, so a regression
    anywhere in the spawn path (parent env build, ``Popen`` env
    handling, backend env filtering) surfaces here.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA-LEAK-IF-FAILS")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-if-fails")
    monkeypatch.setenv("AWS_PROFILE", "should-be-dropped-without-passthrough")

    os_env = create_os_environment(
        OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=active_sandbox_spec_factory(),
        )
    )
    try:
        result = run_async(os_env.shell("env"))
    finally:
        os_env.close()

    out = result.get("stdout", "") + result.get("stderr", "")
    assert "AKIA-LEAK-IF-FAILS" not in out, (
        "AWS_ACCESS_KEY_ID leaked into the helper's environment. "
        "build_helper_env should have stripped it from the spawn env."
    )
    assert "sk-leak-if-fails" not in out
    assert "should-be-dropped-without-passthrough" not in out


def test_sandbox_helper_inherits_explicit_env_passthrough(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Names listed in ``OSEnvSandboxSpec.env_passthrough`` reach the
    helper subprocess; an unrelated unallowlisted variable is still
    stripped at the same time.

    End-to-end counterpart of the unit test in
    :mod:`tests.inner.test_os_env`: confirms the spec → policy →
    spawn-env plumbing actually carries user-declared passthroughs
    through to the helper without widening the allowlist as a side
    effect.
    """
    monkeypatch.setenv("AWS_PROFILE", "explicit-passthrough-value")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-still-blocked")

    spec = active_sandbox_spec_factory(env_passthrough=["AWS_PROFILE"])
    os_env = create_os_environment(
        OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=spec,
        )
    )
    try:
        result = run_async(os_env.shell('printf "%s\\n" "${AWS_PROFILE:-MISSING}"'))
        leak_check = run_async(os_env.shell("env"))
    finally:
        os_env.close()

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "explicit-passthrough-value", (
        "AWS_PROFILE was listed in env_passthrough but did not reach the helper: "
        f"stdout={result['stdout']!r} stderr={result.get('stderr')!r}"
    )
    assert "sk-still-blocked" not in (leak_check.get("stdout", "") + leak_check.get("stderr", ""))


# ---------------------------------------------------------------------------
# start_in_scratch
# ---------------------------------------------------------------------------


def test_sandbox_start_in_scratch_helper_starts_in_scratch_tmpdir(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    ``start_in_scratch=True`` lands the helper in the per-helper
    scratch tmpdir, so ``./relative`` writes from the shell tool
    naturally land in the writable scratch dir without prefixing
    every path with ``$TMPDIR``.

    The workspace cwd stays bound at its real absolute path on both
    backends so the agent can still read project files; the
    behavior here is the chdir override, not the bind set.
    """
    os_env = create_os_environment(
        OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=active_sandbox_spec_factory(),
            start_in_scratch=True,
        )
    )
    try:
        pwd_result = run_async(os_env.shell("pwd"))
        write_result = run_async(
            os_env.shell("printf scratch-write > ./probe.txt; cat ./probe.txt")
        )
    finally:
        os_env.close()

    assert pwd_result["exit_code"] == 0
    pwd_out = pwd_result["stdout"].strip()
    assert pwd_out.startswith(("/tmp", tempfile.gettempdir())), (
        f"Helper started outside the system tempdir: pwd={pwd_out!r}. "
        "start_in_scratch should chdir into the per-helper scratch dir."
    )
    assert pwd_out != str(tmp_path.resolve(strict=False)), (
        "Helper still started in the workspace cwd; --chdir override did not take effect."
    )
    assert write_result["exit_code"] == 0, (
        f"Relative write inside scratch failed: stderr={write_result.get('stderr')!r}"
    )
    assert write_result["stdout"] == "scratch-write"
    assert not (tmp_path / "probe.txt").exists(), (
        "./probe.txt leaked back into the workspace cwd; the helper's "
        "cwd was not actually relocated to the scratch dir."
    )


def test_sandbox_start_in_scratch_workspace_remains_readable(
    tmp_path: Path,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
) -> None:
    """
    Even when the helper starts in scratch, the workspace cwd is
    still bound for reads. Without this, ``start_in_scratch`` would
    trade write ergonomics for read access — agents would lose
    every absolute-path read into the project tree.
    """
    (tmp_path / "README.md").write_text("hello-from-workspace")

    os_env = create_os_environment(
        OSEnvSpec(
            type="caller_process",
            cwd=str(tmp_path),
            sandbox=active_sandbox_spec_factory(),
            start_in_scratch=True,
        )
    )
    try:
        absolute_read = run_async(os_env.shell(f"cat {tmp_path.resolve(strict=False)}/README.md"))
    finally:
        os_env.close()

    assert absolute_read["exit_code"] == 0, (
        "Workspace file unreachable from scratch-cwd helper: "
        f"stderr={absolute_read.get('stderr')!r}. The launcher must keep "
        "cwd bound for reads even when --chdir points elsewhere."
    )
    assert absolute_read["stdout"] == "hello-from-workspace"


# CORAL(S131)
_PROJECT_CONFIG_PROBE = """
import os, subprocess, sys, tempfile
scratch = tempfile.mkdtemp()

def write(path, text="planted"):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)

def moved(source, target):
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    os.rename(source, target)

def linked():
    os.mkdir("linked")
    os.symlink(scratch, "linked/.mcp.json")

def built(name):
    write(os.path.join(scratch, name, ".git", "config"))
    return os.path.join(scratch, name)

home = {**os.environ, "HOME": scratch, "GIT_CONFIG_NOSYSTEM": "1"}
routes = {
    "top_git": lambda: write(".git/config", "[core]\\n\\tfsmonitor = ./hook\\n"),
    "top_claude_settings": lambda: write(".claude/settings.json"),
    "top_claude_local": lambda: write(".claude/settings.local.json"),
    "top_mcp": lambda: write(".mcp.json"),
    "nested_git_config": lambda: write("a/.git/config"),
    "nested_git_hook": lambda: write("b/.git/hooks/pre-commit"),
    "nested_gitfile": lambda: write("c/.git", "gitdir: ../agent"),
    "nested_claude": lambda: write("d/e/.claude/settings.json"),
    "nested_mcp": lambda: write("f/.mcp.json"),
    "upper_case": lambda: write("g/.GIT/config"),
    "renamed_onto": lambda: moved(built("h"), "h/.claude"),
    "linked": linked,
    "moved_in": lambda: moved(built("i"), "moved"),
    "ordinary": lambda: [
        write(path)
        for path in ("CLAUDE.md", ".envrc", ".gitignore", ".github/x", "j.git/x", "k/.mcp.jsonx")
    ],
    "scratch_repo": lambda: subprocess.run(
        [sys.argv[1], "init", "-q", os.path.join(scratch, "repo")], check=True, env=home
    ),
}
for name, route in routes.items():
    try:
        route()
        print(name, "yes")
    except (OSError, subprocess.CalledProcessError) as error:
        print(name, "no")
        print(name, repr(error), file=sys.stderr)
"""


# CORAL(S131)
@pytest.mark.parametrize("launch_path", ["helper", "launcher"])
def test_sandbox_refuses_git_dirs_and_claude_project_config_in_a_write_root(
    tmp_path: Path,
    active_sandbox_type: str,
    active_sandbox_spec_factory: Callable[..., OSEnvSandboxSpec],
    sandbox_pythonpath_env: None,
    launch_path: str,
) -> None:
    """
    Every route plants outside. Seatbelt refuses each one inside but a repository built under
    ``$TMPDIR`` and moved in; ordinary files and a repository under ``$TMPDIR`` still work.
    Bwrap's mounts cannot name a path that does not exist yet: every route is pinned open.
    """
    seatbelt = active_sandbox_type == "darwin_seatbelt"
    base = tmp_path.resolve()
    argv = [sys.executable, "probe.py", _sandbox_git()]
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONPATH": os.environ["PYTHONPATH"]}
    run = functools.partial(subprocess.run, env=env, capture_output=True, text=True, timeout=60)
    for directory in (base / "outside", base / "work"):
        directory.mkdir()
        (directory / "probe.py").write_text(_PROJECT_CONFIG_PROBE)
    outside = run(argv, cwd=base / "outside")
    spec = OSEnvSpec(
        type="caller_process",
        cwd=str(base / "work"),
        sandbox=active_sandbox_spec_factory(write_paths=["."]),
    )
    with contextlib.ExitStack() as cleanup:
        if launch_path == "helper":
            os_env = create_os_environment(spec)
            cleanup.callback(os_env.close)
            result = run_async(os_env.shell(shlex.join(argv)))
            inside, detail = str(result.get("stdout", "")), result
        else:
            launcher = create_exec_launcher(sys.executable, resolve_sandbox(spec, base / "work"))
            cleanup.callback(Path(launcher).unlink, missing_ok=True)
            completed = run([launcher, *argv[1:]], cwd=base / "work")
            inside, detail = completed.stdout, completed.stderr

    reached = dict(line.split() for line in outside.stdout.splitlines())
    observed = dict(line.split() for line in inside.splitlines())
    assert set(reached.values()) == {"yes"}, outside.stderr
    plants = set(reached) - {"moved_in", "ordinary", "scratch_repo"}
    refused = dict.fromkeys(plants, "no" if seatbelt else "yes")
    assert observed == {**reached, **refused}, detail
    if seatbelt:
        names = {".git", ".claude", ".mcp.json"}
        left = [path for path in (base / "work").rglob("*") if path.name.casefold() in names]
        assert [str(path.relative_to(base / "work")) for path in left] == ["moved/.git"]
