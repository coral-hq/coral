"""Controlled access point for private Omnigent symbols needed by Coral."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# omnigent/runtime/pending_elicitations.py: a session's open approvals, read by dispatch.py.
from omnigent.runtime.pending_elicitations import count_for as pending_elicitation_count

# omnigent/runtime/workflow.py: claude-sdk CLI env, used by coral/omni/server/preflight.py.
from omnigent.runtime.workflow import _build_claude_sdk_spawn_env

# omnigent/server/routes/_auth_helpers.py: the created_by the server stamps, used by dispatch.py.
from omnigent.server.routes._auth_helpers import attribution_user

# Session create and launch without a request, used by coral/omni/server/sessions.py.
# omnigent/server/routes/_host_launch.py: authorizes a runner launch for the session owner.
from omnigent.server.routes._host_launch import resolve_host_launch

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
from omnigent.server.routes._session_create_validation import (
    # omnigent/server/routes/_session_create_validation.py: canonical workspace on the host.
    validate_existing_host_workspace,
    # omnigent/server/routes/_session_create_validation.py: a bindable agent for the owner.
    validate_session_agent,
    # omnigent/server/routes/_session_create_validation.py: persisted model and effort.
    validate_session_model_metadata,
)

# omnigent/server/routes/_session_harness_readiness.py: the host reports the harness set up.
from omnigent.server.routes._session_harness_readiness import validate_create_harness_readiness

# omnigent/server/routes/_sessions/orchestration.py: the harness a create will run on.
from omnigent.server.routes._sessions.orchestration import _create_resolved_harness

# Host stat round trip, used by coral/omni/server/worktrees.py.
from omnigent.server.routes._workspace_validation import (
    # omnigent/server/routes/_workspace_validation.py: stat timed out, failed or lost its host.
    WorkspaceValidationError,
    # omnigent/server/routes/_workspace_validation.py: request-free host.stat.
    _ask_host_stat,
)

# Session facade names; the status caches are read by coral/omni/server/dispatch.py.
from omnigent.server.routes.sessions import (
    # omnigent/server/routes/_sessions/helpers.py: pushes a new session to the owner's tabs.
    _announce_session_added,
    # omnigent/server/routes/_sessions/orchestration.py: the runner's session-init handshake.
    _ensure_runner_session_initialized,
    # omnigent/server/routes/_sessions/helpers.py: the terminal-view label a REPL session gets.
    _repl_terminal_ui_labels,
    # omnigent/server/routes/_sessions/common.py: the turn this replica saw open, by session.
    _session_active_response_cache,
    # omnigent/server/routes/_sessions/common.py: why a running session is parked ("" if not).
    _session_blocked_on_cache,
    # omnigent/server/routes/_sessions/common.py: the last status edge this replica published.
    _session_status_cache,
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
    "_announce_session_added",
    "_ask_host_stat",
    "_build_claude_sdk_spawn_env",
    "_create_resolved_harness",
    "_ensure_builtin_agent",
    "_ensure_runner_session_initialized",
    "_repl_terminal_ui_labels",
    "_session_active_response_cache",
    "_session_blocked_on_cache",
    "_session_status_cache",
    "_tar_gz_dir",
    "attribution_user",
    "create_worktree_on_host",
    "list_worktrees_on_host",
    "pending_elicitation_count",
    "request_workspace_op_on_host",
    "resolve_host_launch",
    "validate_create_harness_readiness",
    "validate_existing_host_workspace",
    "validate_session_agent",
    "validate_session_model_metadata",
]


def _tar_gz_dir(bundle_dir: Path) -> bytes:
    """Pack *bundle_dir* with the server's tarball packer, imported on first use."""
    from omnigent.server.app import _tar_gz_dir as server_tar_gz_dir

    return server_tar_gz_dir(bundle_dir)


def _ensure_builtin_agent(
    agent_store: Any,
    artifact_store: Any,
    agent_cache: Any,
    *,
    name: str,
    bundle_bytes: bytes,
) -> None:
    """Register or refresh a server agent row named *name*, imported on first use."""
    from omnigent.server.app import _ensure_builtin_agent as server_ensure_builtin_agent

    server_ensure_builtin_agent(
        agent_store, artifact_store, agent_cache, name=name, bundle_bytes=bundle_bytes
    )
