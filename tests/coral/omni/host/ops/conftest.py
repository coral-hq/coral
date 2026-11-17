"""Fixtures for Coral's host workspace-op handlers: an isolated git home and a real worktree."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from coral.omni.host.ops import workspace_op_handlers
from omnigent.host.workspace_ops import WorkspaceOpHandler
from tests.coral.omni.host.ops._worktrees import (
    LinkedWorktree,
    isolate_git_home,
    make_linked_worktree,
)


@pytest.fixture(autouse=True)
def git_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty ``HOME`` with no inherited git settings (see ``isolate_git_home``)."""
    return isolate_git_home(monkeypatch, tmp_path / "home")


@pytest.fixture
def worktree(tmp_path: Path, git_home: Path) -> LinkedWorktree:
    return make_linked_worktree(tmp_path / "work")


@pytest.fixture
def handlers() -> Mapping[str, WorkspaceOpHandler]:
    return workspace_op_handlers()
