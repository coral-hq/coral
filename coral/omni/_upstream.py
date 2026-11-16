"""Controlled access point for private Omnigent symbols needed by Coral."""

from __future__ import annotations

from pathlib import Path

from omnigent.runtime.workflow import _build_claude_sdk_spawn_env
from omnigent.version import VERSION as OMNIGENT_VERSION

__all__ = ["OMNIGENT_VERSION", "_build_claude_sdk_spawn_env", "_tar_gz_dir"]


def _tar_gz_dir(bundle_dir: Path) -> bytes:
    """Pack *bundle_dir* with the server's tarball packer, imported on first use."""
    from omnigent.server.app import _tar_gz_dir as server_tar_gz_dir

    return server_tar_gz_dir(bundle_dir)
