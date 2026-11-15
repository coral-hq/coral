"""Tests for ``coral.version``."""

from __future__ import annotations

from pathlib import Path

from coral.version import (
    CORAL_VERSION,
    DEFAULT_CORAL_SERVER_PLUGINS,
    apply_coral_environment,
    format_version,
)


def test_apply_coral_environment_sets_defaults_under_home(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    coral_dir = apply_coral_environment(env, home=tmp_path)

    expected = tmp_path / ".coral"
    assert coral_dir == expected
    assert env == {
        "OMNIGENT_DATA_DIR": str(expected),
        "OMNIGENT_CONFIG_HOME": str(expected),
        "OMNIGENT_NO_UPDATE_CHECK": "1",
        "OMNIGENT_SERVER_PLUGINS": DEFAULT_CORAL_SERVER_PLUGINS,
    }


def test_apply_coral_environment_preserves_existing_overrides(tmp_path: Path) -> None:
    env = {
        "OMNIGENT_DATA_DIR": "/custom/data",
        "OMNIGENT_CONFIG_HOME": "/custom/config",
        "OMNIGENT_NO_UPDATE_CHECK": "0",
        "OMNIGENT_SERVER_PLUGINS": "custom.plugin",
    }
    apply_coral_environment(env, home=tmp_path)

    assert env["OMNIGENT_DATA_DIR"] == "/custom/data"
    assert env["OMNIGENT_CONFIG_HOME"] == "/custom/config"
    assert env["OMNIGENT_NO_UPDATE_CHECK"] == "0"
    assert env["OMNIGENT_SERVER_PLUGINS"] == "custom.plugin"


def test_format_version_includes_coral_and_omnigent_versions() -> None:
    assert format_version("0.22.0.dev0") == f"Coral {CORAL_VERSION} (Omnigent 0.22.0.dev0)"
