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

import contextlib
import functools
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


# ---------------------------------------------------------------------------
# Control sockets
# ---------------------------------------------------------------------------

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
        os.rmdir(os.path.join(directory, 'root'))
        return True
    except OSError:
        return False

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
"""


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
    work, another terminal's ``clip.sock`` stays reachable, neither a deny-listed socket nor
    its dir can be renamed out of its deny while files in that dir stay editable, and
    ``netstat`` lists nothing. The pane dir sits in the launcher's ``$TMPDIR``, ahead of its
    scratch, as a terminal pane's does. bwrap's private ``/tmp`` hides every one of them.
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
    seatbelt = active_sandbox_type == "darwin_seatbelt"
    kept = {"own", "nested", "under_root", "launch_dir", "pane_files"} | (
        {"clip"} if seatbelt else set()
    )
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
