"""Controlled access point for private Omnigent symbols needed by Coral."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# omnigent/runtime/pending_elicitations.py: a session's open approvals, read by dispatch.py.
from omnigent.runtime.pending_elicitations import count_for as pending_elicitation_count

# omnigent/runtime/workflow.py: claude-sdk CLI env, used by coral/omni/server/preflight.py.
from omnigent.runtime.workflow import _build_claude_sdk_spawn_env

# omnigent/server/host_registry.py: a host id as the registry keys it, used by plugin.py.
from omnigent.server.host_registry import _canonical_host_id as canonical_host_id

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

# Event types, used by coral/omni/server/mutation_guard.py.
from omnigent.server.routes._sessions.common import (
    # omnigent/server/routes/_sessions/common.py: the event a prompt's answer is posted as.
    _APPROVAL_TYPE as APPROVAL_EVENT_TYPE,
)
from omnigent.server.routes._sessions.common import (
    # omnigent/server/routes/_sessions/common.py: the event types only runners post.
    _RUNNER_SESSION_EVENT_TYPES as RUNNER_SESSION_EVENT_TYPES,
)
from omnigent.server.routes._sessions.common import (
    # omnigent/server/routes/_sessions/common.py: the event types clients post.
    CLIENT_SESSION_EVENT_TYPES,
)

# omnigent/server/routes/_sessions/helpers.py: a label key as a collation compares it;
# Coral also follows native /clear via register_supersession_observer (HRN-07), and
# owns its steps' runner launches via register_runner_launch_owner (S117).
from omnigent.server.routes._sessions.helpers import (
    _label_key_skeleton as label_key_skeleton,
)
from omnigent.server.routes._sessions.helpers import (
    register_runner_launch_owner,
    register_supersession_observer,
)

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
    "APPROVAL_EVENT_TYPE",
    "CLIENT_SESSION_EVENT_TYPES",
    "OMNIGENT_VERSION",
    "RUNNER_SESSION_EVENT_TYPES",
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
    "_get_runner_client",
    "_query_host_runner_status",
    "_repl_terminal_ui_labels",
    "_session_active_response_cache",
    "_session_blocked_on_cache",
    "_session_status_cache",
    "_stop_session_host_runner",
    "_tar_gz_dir",
    "attribution_user",
    "canonical_host_id",
    "create_worktree_on_host",
    "label_key_skeleton",
    "list_worktrees_on_host",
    "pending_elicitation_count",
    "register_runner_launch_owner",
    "register_supersession_observer",
    "request_workspace_op_on_host",
    "resolve_host_launch",
    "validate_create_harness_readiness",
    "validate_existing_host_workspace",
    "validate_session_agent",
    "validate_session_model_metadata",
]


async def _query_host_runner_status(
    host_conn: Any, host_registry: Any, runner_id: str
) -> str | None:
    """
    The host's answer about one runner: ``alive``, ``sign_in_pending``, ``dead``, ``unknown``.

    ``None`` when the host did not answer. Resolved on the sessions facade at call time,
    as Omnigent's own callers resolve it (omnigent/server/routes/_sessions/helpers.py).
    """
    from omnigent.server.routes import sessions as facade

    return await facade._query_host_runner_status(host_conn, host_registry, runner_id)


async def _get_runner_client(session_id: str, runner_router: Any, *, conversation: Any) -> Any:
    """
    A client for the session's connected runner, or ``None``; it never launches one.

    Resolved on the sessions facade at call time (omnigent/server/routes/_sessions/helpers.py).
    """
    from omnigent.server.routes import sessions as facade

    return await facade._get_runner_client(session_id, runner_router, conversation=conversation)


async def _stop_session_host_runner(
    session_id: str,
    host_id: str,
    runner_id: str,
    host_registry: Any,
    *,
    expect_already_stopped: bool = False,
    attempt: Any = None,
) -> bool:
    """
    Stop one runner by id through its host; ``True`` once the host acknowledged it.

    Resolved on the sessions facade at call time (omnigent/server/routes/_sessions/helpers.py).
    """
    from omnigent.server.routes import sessions as facade

    return await facade._stop_session_host_runner(
        session_id,
        host_id,
        runner_id,
        host_registry,
        expect_already_stopped=expect_already_stopped,
        attempt=attempt,
    )


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
