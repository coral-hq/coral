"""Coral version and process environment isolation helpers.

This module intentionally uses only the Python standard library so callers can
configure ``~/.coral`` paths before any ``omnigent`` module executes
import-time directory resolution.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

CORAL_VERSION = "0.1.0.dev0"
__version__ = CORAL_VERSION
DEFAULT_CORAL_SERVER_PLUGINS = "coral.server_plugin"


def coral_home_dir(*, home: Path | None = None) -> Path:
    """Return Coral's state/config home directory (``~/.coral``)."""
    base = Path.home() if home is None else home
    return base / ".coral"


def apply_coral_environment(
    env: MutableMapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> Path:
    """Populate Coral isolation defaults in *env* without overwriting overrides.

    Sets unset values for ``OMNIGENT_DATA_DIR``, ``OMNIGENT_CONFIG_HOME``,
    ``OMNIGENT_NO_UPDATE_CHECK``, and ``OMNIGENT_SERVER_PLUGINS``. Existing
    non-empty values supplied by the caller or test harness are preserved.
    """
    target = os.environ if env is None else env
    coral_dir = coral_home_dir(home=home)
    coral_dir_str = str(coral_dir)

    if not target.get("OMNIGENT_DATA_DIR"):
        target["OMNIGENT_DATA_DIR"] = coral_dir_str
    if not target.get("OMNIGENT_CONFIG_HOME"):
        target["OMNIGENT_CONFIG_HOME"] = coral_dir_str
    if not target.get("OMNIGENT_NO_UPDATE_CHECK"):
        target["OMNIGENT_NO_UPDATE_CHECK"] = "1"
    if not target.get("OMNIGENT_SERVER_PLUGINS"):
        target["OMNIGENT_SERVER_PLUGINS"] = DEFAULT_CORAL_SERVER_PLUGINS
    return coral_dir


def format_version(omnigent_version: str) -> str:
    """Format the ``coral --version`` banner."""
    return f"Coral {CORAL_VERSION} (Omnigent {omnigent_version})"
