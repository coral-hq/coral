"""On Linux, no agent process outlives its sandbox: why WRITE ops need no move-aside there.

On macOS a double-forked ``setsid`` process survives an agent's teardown, so
WRITE ops move the worktree aside. On Linux Coral relies on Omnigent's bwrap
sandbox instead: the agent's shell runs in a PID namespace that dies with the
sandbox's process. This test runs that path itself, with no runner: Omnigent's
``create_os_environment`` with a ``linux_bwrap`` sandbox starts the same
sandboxed helper process a runner starts for an agent's shell, a shell command
there double-forks a ``setsid`` daemon, and the environment's ``close()``, the
teardown of that helper, stops it. The daemon must be gone afterwards.

Linux only. Without a working bwrap the test fails under ``CI`` (CI must prove
this) and skips elsewhere.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import sys
import uuid
from pathlib import Path
from typing import NoReturn

import psutil
import pytest

import omnigent
from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec
from omnigent.inner.os_env import create_os_environment
from tests._helpers.polling import poll_until_async

# Double-forks, leaves the session and sleeps: what an agent's background job can do.
_DAEMON = """\
import os, time
if os.fork():
    os._exit(0)
os.setsid()
if os.fork():
    os._exit(0)
time.sleep(300)
"""


def _unavailable(reason: str) -> NoReturn:
    if os.environ.get("CI"):
        pytest.fail(f"CI must prove the agent sandbox ends every agent process: {reason}")
    pytest.skip(reason)


def _processes_with(token: str) -> list[psutil.Process]:
    found = []
    for process in psutil.process_iter(["cmdline"]):
        with contextlib.suppress(psutil.Error):
            if token in (process.info.get("cmdline") or []):
                found.append(process)
    return found


async def test_a_setsid_daemon_dies_with_the_agent_sandbox(tmp_path: Path) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux agents run under bwrap; macOS is covered by the move-aside tests")
    if shutil.which("bwrap") is None:
        _unavailable("bwrap is not installed")
    workdir = tmp_path / "agent"
    workdir.mkdir()
    sandbox = OSEnvSandboxSpec(type="linux_bwrap", write_paths=["."], allow_network=False)
    try:
        env = create_os_environment(
            OSEnvSpec(cwd=str(workdir), sandbox=sandbox),
            # An editable checkout may live outside the sandbox's default read roots.
            additional_read_roots=[Path(omnigent.__file__).resolve().parent],
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _unavailable(f"the bwrap sandbox cannot start: {exc}")
    assert env is not None
    # The token marks the daemon's command line; its pid inside the namespace differs.
    token = f"coral-daemon-{uuid.uuid4().hex}"
    command = (
        f"{shlex.quote(sys.executable)} -c {shlex.quote(_DAEMON)} {token} "
        "</dev/null >/dev/null 2>&1"
    )
    try:
        try:
            try:
                outcome = await env.shell(command, timeout=30)
            except (OSError, RuntimeError) as exc:
                _unavailable(f"the sandboxed helper did not start: {exc}")
            if outcome.get("exit_code") != 0:
                _unavailable(f"the agent's shell did not run in the sandbox: {outcome}")
            await poll_until_async(lambda: bool(_processes_with(token)), timeout_s=10)
        finally:
            env.close()

        await poll_until_async(lambda: not _processes_with(token), timeout_s=15)
    finally:
        for process in _processes_with(token):
            with contextlib.suppress(psutil.Error):
                process.kill()
