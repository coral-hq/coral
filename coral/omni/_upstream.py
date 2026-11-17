"""Controlled access point for private Omnigent symbols needed by Coral."""

from __future__ import annotations

from pathlib import Path

# omnigent/runtime/workflow.py: claude-sdk CLI env, used by coral/omni/server/preflight.py.
from omnigent.runtime.workflow import _build_claude_sdk_spawn_env

# Host workspace-op channel, used by coral/omni/server/workspace_ops.py.
from omnigent.server.routes._host_workspace_ops import (
    # omnigent/server/routes/_host_workspace_ops.py: no owner scope matched; nothing was sent.
    HostWorkspaceOpNotPermittedError,
    # omnigent/server/routes/_host_workspace_ops.py: the host lacks workspace_ops:1.
    HostWorkspaceOpsUnsupportedError,
    # omnigent/server/routes/_host_workspace_ops.py: lost or timed out; outcome unknown.
    HostWorkspaceOpUnavailableError,
    # omnigent/server/routes/_host_workspace_ops.py: request-free host.workspace_op.
    request_workspace_op_on_host,
)

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
    "HostWorkspaceOpNotPermittedError",
    "HostWorkspaceOpUnavailableError",
    "HostWorkspaceOpsUnsupportedError",
    "WorkspaceValidationError",
    "WorktreeHostUnavailableError",
    "WorktreeProxyError",
    "_ask_host_stat",
    "_build_claude_sdk_spawn_env",
    "_tar_gz_dir",
    "create_worktree_on_host",
    "list_worktrees_on_host",
    "request_workspace_op_on_host",
]


def _tar_gz_dir(bundle_dir: Path) -> bytes:
    """Pack *bundle_dir* with the server's tarball packer, imported on first use."""
    from omnigent.server.app import _tar_gz_dir as server_tar_gz_dir

    return server_tar_gz_dir(bundle_dir)
