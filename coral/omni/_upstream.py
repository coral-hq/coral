"""Controlled access point for private Omnigent symbols needed by Coral."""

from __future__ import annotations

# Host worktree proxies, used by coral/omni/server/worktrees.py.
from omnigent.server.routes._host_worktree import (
    # omnigent/server/routes/_host_worktree.py: the host could not be reached.
    WorktreeHostUnavailableError,
    # omnigent/server/routes/_host_worktree.py: the host reported a worktree failure.
    WorktreeProxyError,
    # omnigent/server/routes/_host_worktree.py: request-free host.create_worktree.
    create_worktree_on_host,
    # omnigent/server/routes/_host_worktree.py: request-free host.list_worktrees.
    list_worktrees_on_host,
)

# Host stat round trip, used by coral/omni/server/worktrees.py.
from omnigent.server.routes._workspace_validation import (
    # omnigent/server/routes/_workspace_validation.py: stat timed out, failed or lost its host.
    WorkspaceValidationError,
    # omnigent/server/routes/_workspace_validation.py: request-free host.stat.
    _ask_host_stat,
)
from omnigent.version import VERSION as OMNIGENT_VERSION

__all__ = [
    "OMNIGENT_VERSION",
    "WorkspaceValidationError",
    "WorktreeHostUnavailableError",
    "WorktreeProxyError",
    "_ask_host_stat",
    "create_worktree_on_host",
    "list_worktrees_on_host",
]
