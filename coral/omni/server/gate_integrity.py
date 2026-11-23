"""The gate label's facts on an Omnigent server: its startup config, and the run owner's host.

The server's facts are read once, when the runs API is built. The host's sandbox policy is
read on each run detail from the live connection, only when the run's own owner and account
registration hold it; anything that cannot be read stays unknown, so it never verifies.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Any

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from coral.api.sub_features import resolve_sub_features
from coral.gates.integrity import GateIntegrityFacts, HostSandboxPolicy, ServerConfigFacts
from coral.limits import WarnOnce
from coral.omni._upstream import seatbelt_default_read_roots
from coral.omni.process_map import sandbox_policy_revision
from coral.omni.server.host_access import HostAccessError, OwnerHost
from coral.validate.preflight import sandbox_from_capabilities
from omnigent.host.frames import CAP_OS_SANDBOX_PREFIX
from omnigent.process_logging import data_dir
from omnigent.server.auth import auth_mode, env_var_is_truthy, local_single_user_enabled
from omnigent.server.server_config import resolve_config_path

if TYPE_CHECKING:
    from coral.api.run_service import HostSandboxReader
    from omnigent.server.host_registry import HostRegistry
    from omnigent.server.server_plugins import ServerServices

_logger = logging.getLogger(__name__)

DEVICE_GRANT_ENV = "OMNIGENT_DEVICE_GRANT_ENABLED"
# The artifact store the server builds as a remote UC Volume; any other location is local.
REMOTE_ARTIFACTS_PREFIX = "dbfs:/Volumes/"
# macOS volumes are case-insensitive by default, and seatbelt matches the path a file opens as.
FOLD_PATH_CASE = sys.platform == "darwin"


def server_gate_facts(app: Any, services: ServerServices) -> GateIntegrityFacts:
    """The server's own facts for the gate label; the run's host is left unknown."""
    return GateIntegrityFacts(
        server_mode=auth_mode(services.auth_provider),
        native_steps_enabled=bool(
            resolve_sub_features(services.server_config).get("claude_native_steps")
        ),
        server_config=ServerConfigFacts(
            runner_token_allow_listed=_runner_token_allow_listed(app),
            machine_client=_machine_client(),
            device_grant=env_var_is_truthy(DEVICE_GRANT_ENV, default=False),
            state_under_step_read_root=_state_under_step_read_roots(services),
            local_single_user=local_single_user_enabled(),
        ),
    )


def _runner_token_allow_listed(app: Any) -> bool | None:
    """Whether the server accepts an allow-listed runner token; ``None`` when unrecorded."""
    state = getattr(app, "state", None)
    if state is None or not hasattr(state, "runner_tunnel_tokens"):
        return None
    return state.runner_tunnel_tokens is not None


def _machine_client() -> bool | None:
    """Whether a machine client is configured; ``None`` for a config the server refuses."""
    from omnigent.server.routes.client_credentials import MachineClientConfig

    try:
        return MachineClientConfig.from_env() is not None
    except RuntimeError:
        return None


def _state_under_step_read_roots(services: ServerServices) -> bool | None:
    """Whether any file the server keeps state in is under a seatbelt read root."""
    paths = _state_paths(services)
    return None if paths is None else _under_step_read_roots(paths)


def _state_paths(services: ServerServices) -> list[str] | None:
    """
    The server's data dir, config file, artifact location (its cookie secret) and database
    files (sign-in tokens, password hashes); ``None`` when one of them cannot be placed.
    """
    paths = [str(data_dir())]
    config = resolve_config_path()
    if config is not None:
        paths.append(str(config))
    location = getattr(getattr(services, "artifact_store", None), "storage_location", None)
    if isinstance(location, str) and not location.startswith(REMOTE_ARTIFACTS_PREFIX):
        # The local store would take a URL as a relative directory: unplaced.
        if "://" in location:
            return None
        paths.append(location)
    databases = _database_files(services)
    return None if databases is None else [*paths, *databases]


def _database_files(services: ServerServices) -> list[str] | None:
    """The local files of the server's databases; ``None`` for a database it cannot place."""
    conversations = getattr(services, "conversation_store", None)
    uris = {
        getattr(conversations, "storage_location", None),
        getattr(conversations, "conversation_storage_location", None),
        getattr(getattr(services, "permission_store", None), "storage_location", None),
    }
    files: list[str] = []
    for uri in sorted(uri for uri in uris if isinstance(uri, str)):
        try:
            url = make_url(uri)
        except (ArgumentError, ValueError):
            return None
        if url.get_backend_name() != "sqlite":
            # A database server on a network host is no file a step reads; anything else is.
            if not url.host:
                return None
            continue
        database = url.database or ""
        if database.startswith("file:"):
            return None
        if database not in ("", ":memory:"):
            files.append(database)
    return files


def _under_step_read_roots(paths: Iterable[str]) -> bool | None:
    """Whether a path, as given or with its links followed, is under a seatbelt read root."""
    roots = [_comparable(Path(root)) for root in seatbelt_default_read_roots]
    try:
        forms = {
            _comparable(form)
            for path in paths
            for form in (Path(path).expanduser().absolute(), Path(path).expanduser().resolve())
        }
    except (OSError, RuntimeError):
        return None
    return any(form.is_relative_to(root) for form in forms for root in roots)


def _comparable(path: Path) -> PurePath:
    return PurePath(str(path).casefold()) if FOLD_PATH_CASE else path


def sandbox_policy(capabilities: Iterable[str]) -> HostSandboxPolicy | None:
    """
    The sandbox policy a host's hello reports: its own reserved backend token and exactly
    one policy revision; ``None`` when either is missing.
    """
    tokens = tuple(capabilities)
    # A host sends one; two can only come from a changed host, so neither is believed.
    backends = [token for token in tokens if token.startswith(CAP_OS_SANDBOX_PREFIX)]
    backend = sandbox_from_capabilities(backends) if len(backends) == 1 else None
    revision = sandbox_policy_revision(tokens)
    if backend is None or revision is None:
        return None
    return HostSandboxPolicy(backend, revision)


def host_sandbox_reader(registry: HostRegistry) -> HostSandboxReader:
    """Reads a run's host's sandbox policy from ``registry``, scoped to the run's owner."""
    unreadable = WarnOnce()

    def read(
        *, user_id: str | None, account_generation: str | None, host_id: str, workspace_id: int
    ) -> HostSandboxPolicy | None:
        # An ownerless run names no owner its host could be held by.
        if user_id is None:
            return None
        # No authorize_owner_host: the run's start checked the stored host row, and a read
        # needs only that the run's owner and registration still hold the live connection.
        owner_host = OwnerHost(registry, host_id, workspace_id, user_id, account_generation)
        try:
            return sandbox_policy(owner_host.connection().hello.capabilities)
        except HostAccessError:
            return None
        except Exception as exc:  # noqa: BLE001 -- the label reads unknown; logged by type
            _logger.log(
                unreadable.level(),
                "Coral could not read a host's sandbox for the gate label: %s",
                type(exc).__name__,
            )
            return None

    return read
