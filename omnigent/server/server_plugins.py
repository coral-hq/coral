"""Server plugin seam for extending the FastAPI app at startup.

# CORAL(S32): Provides the typed services bundle, fail-fast plugin loader, and
# reverse-order lifespan context manager used by Coral (and test plugins).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from fastapi import FastAPI

    from omnigent.runner.routing import RunnerRouter
    from omnigent.runner.transports.ws_tunnel.registry import TunnelRegistry
    from omnigent.runtime.agent_cache import AgentCache
    from omnigent.server.auth import AuthProvider
    from omnigent.server.host_registry import HostRegistry
    from omnigent.stores import AgentStore, ArtifactStore, ConversationStore, FileStore
    from omnigent.stores.comment_store import CommentStore
    from omnigent.stores.host_store import HostStore
    from omnigent.stores.permission_store import PermissionStore
    from omnigent.stores.policy_store import PolicyStore
    from omnigent.stores.preference_store import PreferenceStore
    from omnigent.stores.project_store import ProjectStore
    from omnigent.stores.scheduled_task_store import ScheduledTaskStore


class ServerPluginError(RuntimeError):
    """Raised when a configured server plugin cannot be loaded or initialized."""


@dataclass(frozen=True)
class ServerServices:
    """Core server stores and registries passed to server plugins at startup."""

    agent_store: AgentStore
    file_store: FileStore
    conversation_store: ConversationStore
    artifact_store: ArtifactStore
    agent_cache: AgentCache
    comment_store: CommentStore | None
    policy_store: PolicyStore | None
    permission_store: PermissionStore | None
    scheduled_task_store: ScheduledTaskStore | None
    project_store: ProjectStore | None
    preference_store: PreferenceStore | None
    host_store: HostStore | None
    account_store: Any | None
    auth_provider: AuthProvider | None
    runner_router: RunnerRouter
    host_registry: HostRegistry
    tunnel_registry: TunnelRegistry
    server_config: Mapping[str, Any]
    host_sharded: bool


LifespanHook = Callable[["FastAPI", ServerServices], AbstractAsyncContextManager[None]]


@dataclass(frozen=True)
class ServerPluginRegistration:
    """Resources contributed by a server plugin during ``create_app``."""

    routers: tuple[tuple[Any, str, list[str]], ...] = ()
    lifespan_hooks: tuple[LifespanHook, ...] = ()
    policy_modules: tuple[str, ...] = ()


def _resolve_plugin_factory(spec: str) -> Callable[[ServerServices], ServerPluginRegistration]:
    module_path, _, attr = spec.partition(":")
    attr_name = attr or "register"
    try:
        module = import_module(module_path)
    except Exception as exc:
        raise ServerPluginError(f"Failed to import server plugin {spec!r}: {exc}") from exc
    factory = getattr(module, attr_name, None)
    if factory is None or not callable(factory):
        raise ServerPluginError(f"Server plugin {spec!r} does not define a callable {attr_name!r}")
    return cast("Callable[[ServerServices], ServerPluginRegistration]", factory)


def _validate_policy_modules(spec: str, policy_modules: Sequence[str]) -> None:
    """Eagerly import plugin policy modules so broken declarations abort boot.

    ``omnigent.policies.registry.load_registry`` intentionally logs and skips
    broken ``policy_modules`` entries; plugin-contributed policy modules must
    fail loudly instead of starting the server half-enabled.
    """
    for mod_path in policy_modules:
        try:
            mod = import_module(mod_path)
        except Exception as exc:
            raise ServerPluginError(
                f"Server plugin {spec!r} failed to import policy module {mod_path!r}: {exc}"
            ) from exc
        if not isinstance(getattr(mod, "POLICY_REGISTRY", None), list):
            raise ServerPluginError(
                f"Server plugin {spec!r} policy module {mod_path!r} must define "
                "a POLICY_REGISTRY list"
            )


def load_server_plugins(
    plugin_specs: Sequence[str] | None,
    services: ServerServices,
) -> list[ServerPluginRegistration]:
    """Import, register, and validate all configured server plugins."""
    registrations: list[ServerPluginRegistration] = []
    for raw_spec in plugin_specs or ():
        spec = raw_spec.strip()
        if not spec:
            continue
        factory = _resolve_plugin_factory(spec)
        try:
            reg = factory(services)
        except ServerPluginError:
            raise
        except Exception as exc:
            raise ServerPluginError(
                f"Server plugin {spec!r} failed during registration: {exc}"
            ) from exc
        if not isinstance(reg, ServerPluginRegistration):
            raise ServerPluginError(
                f"Server plugin {spec!r} returned {type(reg).__name__}, "
                "expected ServerPluginRegistration"
            )
        _validate_policy_modules(spec, reg.policy_modules)
        registrations.append(reg)
    return registrations


@asynccontextmanager
async def enter_lifespan_hooks(
    app: FastAPI,
    services: ServerServices,
    hooks: Sequence[LifespanHook],
) -> AsyncIterator[None]:
    """Enter plugin lifespan hooks in order and exit in reverse order."""
    async with AsyncExitStack() as stack:
        for hook in hooks:
            await stack.enter_async_context(hook(app, services))
        yield
