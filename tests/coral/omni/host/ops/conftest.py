"""Fixtures for Coral's host workspace-op handlers: an isolated git home and a real worktree."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from coral.omni.host.ops import workspace_op_handlers
from coral.omni.process_map import DISABLE_HOST_ENTRY_POINTS_ENV
from omnigent.host.workspace_ops import WorkspaceOpHandler
from tests.coral.omni.host.ops._worktrees import LinkedWorktree, make_linked_worktree


@pytest.fixture(autouse=True)
def git_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``HOME`` at an empty directory and drop inherited git settings.

    The handlers read the user's full git config from ``HOME``, so the
    developer's own ignores, attributes or identity must not reach the tests.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in list(os.environ):
        if name.startswith("GIT_") or name == "XDG_CONFIG_HOME":
            monkeypatch.delenv(name)
    monkeypatch.delenv(DISABLE_HOST_ENTRY_POINTS_ENV, raising=False)
    return home


@pytest.fixture
def worktree(tmp_path: Path, git_home: Path) -> LinkedWorktree:
    return make_linked_worktree(tmp_path / "work")


@pytest.fixture
def handlers() -> Mapping[str, WorkspaceOpHandler]:
    return workspace_op_handlers()
