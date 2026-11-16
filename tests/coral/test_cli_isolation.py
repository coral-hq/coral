"""Tests for Coral CLI isolation, version formatting, and passthrough."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from coral.cli import cli, main
from coral.version import CORAL_VERSION


def _isolated_home_env(home: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("OMNIGENT_") and not k.startswith("CORAL_")
    }
    env["HOME"] = str(home)
    return env


def test_importing_coral_loads_no_omnigent_module() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, coral; "
                "loaded = [m for m in sys.modules "
                "if m == 'omnigent' or m.startswith('omnigent.')]; "
                "assert not loaded, f'Unexpected omnigent modules: {loaded}'"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_coral_help_writes_nothing_to_omnigent_home_and_skips_omnigent_import(
    tmp_path: Path,
) -> None:
    env = _isolated_home_env(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from coral.cli import main; "
                "code = main(['--help']); "
                "loaded = [m for m in sys.modules "
                "if m == 'omnigent' or m.startswith('omnigent.')]; "
                "assert not loaded, f'Loaded omnigent modules: {loaded}'; "
                "raise SystemExit(code)"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Coral workflow orchestration CLI." in result.stdout
    assert not (tmp_path / ".omnigent").exists()


_CORAL_ENV_KEYS = (
    "OMNIGENT_DATA_DIR",
    "OMNIGENT_CONFIG_HOME",
    "OMNIGENT_NO_UPDATE_CHECK",
    "OMNIGENT_SERVER_PLUGINS",
)


def _clear_coral_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _CORAL_ENV_KEYS:
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key, raising=False)


def test_coral_version_and_upgrade_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_coral_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    runner = CliRunner()
    version_res = runner.invoke(cli, ["--version"])
    assert version_res.exit_code == 0, version_res.output
    assert f"Coral {CORAL_VERSION} (Omnigent " in version_res.output

    upgrade_res = runner.invoke(cli, ["upgrade"])
    assert upgrade_res.exit_code == 2
    assert "Coral's release channel" in upgrade_res.output
    assert not (tmp_path / ".omnigent").exists()


def test_coral_passthrough_sets_coral_env_before_calling_omnigent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_coral_env(monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    seen: dict[str, object] = {}

    def _fake_forward(argv: list[str], *, prog_name: str = "coral") -> None:
        seen["argv"] = list(argv)
        seen["prog_name"] = prog_name
        seen["data_dir"] = os.environ.get("OMNIGENT_DATA_DIR")
        seen["config_home"] = os.environ.get("OMNIGENT_CONFIG_HOME")
        seen["no_update"] = os.environ.get("OMNIGENT_NO_UPDATE_CHECK")
        seen["plugins"] = os.environ.get("OMNIGENT_SERVER_PLUGINS")

    monkeypatch.setattr("coral.omni.cli_passthrough.forward_to_omnigent", _fake_forward)
    code = main(["status", "--json"])
    assert code == 0
    assert seen == {
        "argv": ["status", "--json"],
        "prog_name": "coral",
        "data_dir": str(tmp_path / ".coral"),
        "config_home": str(tmp_path / ".coral"),
        "no_update": "1",
        "plugins": "coral.server_plugin",
    }
