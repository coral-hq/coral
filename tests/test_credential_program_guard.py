"""The conftest guard stops tests from starting the real ``claude`` or ``security``."""

from __future__ import annotations

import os
import pwd
import subprocess
from pathlib import Path

import pytest


def _real_home_env() -> dict[str, str]:
    return {**os.environ, "HOME": pwd.getpwuid(os.getuid()).pw_dir}


def test_starting_security_against_the_real_home_fails_the_test() -> None:
    with pytest.raises(AssertionError, match="security"):
        subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials"],
            env=_real_home_env(),
            capture_output=True,
            check=False,
        )


def test_starting_claude_through_a_shell_line_fails_the_test() -> None:
    with pytest.raises(AssertionError, match="claude"):
        subprocess.run(
            "claude auth status",
            shell=True,
            env=_real_home_env(),
            capture_output=True,
            check=False,
        )


def test_a_stub_claude_in_a_temp_dir_still_runs(tmp_path: Path) -> None:
    stub = tmp_path / "claude"
    stub.write_text("#!/bin/sh\necho stub\n")
    stub.chmod(0o755)
    env = {**_real_home_env(), "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(["claude"], env=env, capture_output=True, text=True, check=True)

    assert result.stdout == "stub\n"


def test_login_probe_still_asks_a_stub_claude(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omnigent.onboarding.harness_install import harness_cli_logged_in

    stub = tmp_path / "claude"
    stub.write_text("#!/bin/sh\necho '{\"loggedIn\": true}'\n")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    assert harness_cli_logged_in("anthropic") is True
