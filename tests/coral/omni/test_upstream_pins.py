"""Every private Omnigent name Coral pins keeps the shape Coral calls it with.

``coral/omni/_upstream.py`` is the one place Coral reaches underscore Omnigent
names. An upstream sync that changes one of their signatures must fail here,
next to the snapshot, rather than at a call site in production.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

import coral.omni._upstream as upstream
from coral.alerts.types import LOCAL_USER_ID
from omnigent.db.workspace_cache import WorkspaceScopedCache
from omnigent.server.auth import RESERVED_USER_LOCAL

# name -> (the module that defines it, its signature as Coral calls it)
PINNED: dict[str, tuple[str, str]] = {
    "APPROVAL_EVENT_TYPE": ("omnigent.server.routes._sessions.common", ""),
    "CLIENT_SESSION_EVENT_TYPES": ("omnigent.server.routes._sessions.common", ""),
    "HostWorkspaceOpNotPermittedError": ("omnigent.server.routes._host_workspace_ops", ""),
    "HostWorkspaceOpUnavailableError": (
        "omnigent.server.routes._host_workspace_ops",
        "(message: 'str', *, timed_out: 'bool') -> 'None'",
    ),
    "HostWorkspaceOpsUnsupportedError": ("omnigent.server.routes._host_workspace_ops", ""),
    "RUNNER_SESSION_EVENT_TYPES": ("omnigent.server.routes._sessions.common", ""),
    "WorkspaceValidationError": (
        "omnigent.server.routes._workspace_validation",
        "(message: 'str') -> 'None'",
    ),
    "WorktreeHostUnavailableError": (
        "omnigent.server.routes._host_worktree",
        "(message: 'str') -> 'None'",
    ),
    "WorktreeProxyError": ("omnigent.server.routes._host_worktree", "(message: 'str') -> 'None'"),
    "_announce_session_added": (
        "omnigent.server.routes._sessions.helpers",
        "(user_id: 'str | None', session_id: 'str') -> 'None'",
    ),
    "_ask_host_stat": (
        "omnigent.server.routes._workspace_validation",
        "(*, host_registry: 'HostRegistry', host_conn: 'HostConnection', path: 'str')"
        " -> 'dict[str, Any]'",
    ),
    "_build_claude_sdk_spawn_env": (
        "omnigent.runtime.workflow",
        "(spec: 'AgentSpec', *, cwd: 'Path | None' = None, workdir: 'Path | None' = None)"
        " -> 'dict[str, str]'",
    ),
    "_create_resolved_harness": (
        "omnigent.server.routes._sessions.orchestration",
        "(agent: 'Agent', harness_override: 'str | None', agent_cache: 'AgentCache | None')"
        " -> 'str | None'",
    ),
    "_ensure_builtin_agent": (
        "omnigent.server.app",
        "(agent_store: omnigent.stores.agent_store.AgentStore, artifact_store:"
        " omnigent.stores.artifact_store.ArtifactStore, agent_cache: Any, *, name: str,"
        " bundle_bytes: bytes) -> None",
    ),
    "_get_runner_client": (
        "omnigent.server.routes._sessions.helpers",
        "(session_id: 'str', runner_router: 'RunnerRouter | None', *, conversation:"
        " 'Conversation | None' = None) -> 'httpx.AsyncClient | None'",
    ),
    "_query_host_runner_status": (
        "omnigent.server.routes._sessions.helpers",
        "(host_conn: 'HostConnection', host_registry: 'HostRegistry', runner_id: 'str')"
        " -> 'str | None'",
    ),
    "_ensure_runner_session_initialized": (
        "omnigent.server.routes._sessions.orchestration",
        "(session_id: 'str', conv: 'Conversation', runner_client: 'httpx.AsyncClient',"
        " conversation_store: 'ConversationStore', initializer: 'RunnerSessionInitializer | None'"
        " = None, *, suppress_recovery_turn: 'bool' = False, require_success: 'bool' = False,"
        " trigger: 'str' = 'session_ensure') -> 'bool'",
    ),
    "_repl_terminal_ui_labels": (
        "omnigent.server.routes._sessions.helpers",
        "(*, agent: 'Agent', agent_cache: 'AgentCache | None', harness_override: 'str | None')"
        " -> 'dict[str, str]'",
    ),
    "_session_active_response_cache": ("omnigent.server.routes._sessions.common", ""),
    "_session_blocked_on_cache": ("omnigent.server.routes._sessions.common", ""),
    "_session_status_cache": ("omnigent.server.routes._sessions.common", ""),
    "_stop_session_host_runner": (
        "omnigent.server.routes._sessions.helpers",
        "(session_id: 'str', host_id: 'str', runner_id: 'str', host_registry: 'Any', *,"
        " expect_already_stopped: 'bool' = False, attempt: '_HostRunnerStopAttempt | None' ="
        " None) -> 'bool'",
    ),
    "_tar_gz_dir": ("omnigent.server.app", "(bundle_dir: pathlib.Path) -> bytes"),
    "attribution_user": (
        "omnigent.server.routes._auth_helpers",
        "(user_id: 'str | None') -> 'str | None'",
    ),
    "canonical_host_id": ("omnigent.server.host_registry", "(host_id: 'str') -> 'str'"),
    "create_worktree_on_host": (
        "omnigent.server.routes._host_worktree",
        "(*, host_registry: 'HostRegistry', host_conn: 'HostConnection', repo_path: 'str',"
        " branch_name: 'str', base_branch: 'str | None', existing_branch: 'bool' = False)"
        " -> 'CreatedWorktree'",
    ),
    "label_key_skeleton": (
        "omnigent.server.routes._sessions.helpers",
        "(key: 'str') -> 'str'",
    ),
    "list_worktrees_on_host": (
        "omnigent.server.routes._host_worktree",
        "(*, host_registry: 'HostRegistry', host_conn: 'HostConnection', repo_path: 'str',"
        " for_cleanup: 'bool' = False) -> 'list[dict[str, object]]'",
    ),
    "pending_elicitation_count": (
        "omnigent.runtime.pending_elicitations",
        "(conversation_id: 'str') -> 'int'",
    ),
    "register_supersession_observer": (
        "omnigent.server.routes._sessions.helpers",
        "(observer: 'Callable[[str, str, str], None]') -> 'Callable[[], None]'",
    ),
    "request_workspace_op_on_host": (
        "omnigent.server.routes._host_workspace_ops",
        "(*, host_registry: 'HostRegistry', host_conn: 'HostConnection', op: 'str', root: 'str',"
        " params: 'Mapping[str, object]', timeout_s: 'float', op_key: 'str | None')"
        " -> 'WorkspaceOpReply'",
    ),
    "resolve_host_launch": (
        "omnigent.server.routes._host_launch",
        "(*, user_id: 'str | None', host_id: 'str', session_id: 'str', host_store: 'HostStore',"
        " host_registry: 'HostRegistry', conversation_store: 'ConversationStore',"
        " permission_store: 'PermissionStore | None', conversation: 'Conversation | None' = None,"
        " sandbox_profiles: 'SandboxProfileCatalog | None' = None) -> 'HostLaunchTarget'",
    ),
    "validate_create_harness_readiness": (
        "omnigent.server.routes._session_harness_readiness",
        "(*, harness: 'str | None', host_id: 'str | None', parent_session_id: 'str | None',"
        " inherited_runner_id: 'str | None', user_id: 'str | None', conversation_store:"
        " 'ConversationStore', host_store: 'HostStore | None', parent: 'Conversation | None'"
        " = None) -> 'None'",
    ),
    "validate_existing_host_workspace": (
        "omnigent.server.routes._session_create_validation",
        "(*, user_id: 'str | None', host_id: 'str', workspace: 'str | None', agent: 'Any',"
        " agent_cache: 'AgentCache | None', host_store: 'Any | None', host_registry:"
        " 'Any | None') -> 'str'",
    ),
    "validate_session_agent": (
        "omnigent.server.routes._session_create_validation",
        "(*, user_id: 'str | None', agent_id: 'str', agent_store: 'AgentStore', permission_store:"
        " 'PermissionStore | None', conversation_store: 'ConversationStore') -> 'Any'",
    ),
    "validate_session_model_metadata": (
        "omnigent.server.routes._session_create_validation",
        "(*, model_override: 'str | None', reasoning_effort: 'str | None')"
        " -> 'tuple[str | None, str | None]'",
    ),
}
# Pins wrapped so importing _upstream never loads the server app module.
LAZY = frozenset(
    {
        "_ensure_builtin_agent",
        "_get_runner_client",
        "_query_host_runner_status",
        "_stop_session_host_runner",
        "_tar_gz_dir",
    }
)
# Status caches Coral reads by key in the run's workspace scope.
CACHES = frozenset(
    {"_session_active_response_cache", "_session_blocked_on_cache", "_session_status_cache"}
)
# Event-type sets Coral classifies by membership; their members may change upstream.
TYPE_SETS = frozenset({"CLIENT_SESSION_EVENT_TYPES", "RUNNER_SESSION_EVENT_TYPES"})
# Constants Coral compares with; pin name -> the value it must keep.
VALUES = {"APPROVAL_EVENT_TYPE": "approval"}
# Pins whose name differs from their source's: pin name -> source attribute.
ALIASES = {
    "APPROVAL_EVENT_TYPE": "_APPROVAL_TYPE",
    "RUNNER_SESSION_EVENT_TYPES": "_RUNNER_SESSION_EVENT_TYPES",
    "_get_runner_client": "_get_runner_client_impl",
    "canonical_host_id": "_canonical_host_id",
    "label_key_skeleton": "_label_key_skeleton",
    "pending_elicitation_count": "count_for",
}
# Exceptions Coral raises or catches by type alone; they keep their base.
BASES: dict[str, type[BaseException]] = {
    "HostWorkspaceOpNotPermittedError": PermissionError,
    "HostWorkspaceOpsUnsupportedError": Exception,
}


def _signature(obj: object) -> str:
    return str(inspect.signature(obj))  # type: ignore[arg-type]


def test_every_pin_has_a_snapshot() -> None:
    pins = {name for name in upstream.__all__ if name != "OMNIGENT_VERSION"}
    assert pins == set(PINNED)


@pytest.mark.parametrize("name", sorted(PINNED))
def test_pin_keeps_its_upstream_source_and_signature(name: str) -> None:
    module_name, expected = PINNED[name]
    source = getattr(importlib.import_module(module_name), ALIASES.get(name, name))
    pinned = getattr(upstream, name)
    if name in LAZY:
        # The wrapper forwards every parameter to the server function it imports.
        assert list(inspect.signature(pinned).parameters) == list(
            inspect.signature(source).parameters
        )
    else:
        assert pinned is source
    if name in BASES:
        assert issubclass(source, BASES[name])
    elif name in CACHES:
        assert isinstance(source, WorkspaceScopedCache)
    elif name in TYPE_SETS:
        assert isinstance(source, frozenset) and all(isinstance(kind, str) for kind in source)
    elif name in VALUES:
        assert source == VALUES[name]
    else:
        assert _signature(source) == expected


def test_coral_names_the_local_user_as_omnigent_reserves_it() -> None:
    """Runs, alerts and gate answers treat this id and ``None`` as the single local user."""
    assert LOCAL_USER_ID == RESERVED_USER_LOCAL
