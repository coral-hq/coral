"""Effect executor contract, outcomes, lease fencing context, and process registry."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from coral.stores.protocols import WorkItem


class StartupLeaseLost(RuntimeError):
    """Raised when a worker loses its work-item lease before or during side-effect execution."""


@dataclass(frozen=True, slots=True)
class EffectCompleted:
    """Successful effect outcome with an optional structured result payload."""

    result: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EffectFailed:
    """Failed effect outcome classified as transient (retryable) or permanent."""

    error_code: str
    message: str = ""
    retryable: bool = False


EffectOutcome = EffectCompleted | EffectFailed


@dataclass(slots=True)
class ExecutionContext:
    """Execution context passed to an effect executor with lease-fencing verification."""

    work: WorkItem
    workspace_id: int
    run_id: str
    worker_id: str
    lease_seconds: int = 60
    _ensure_lease_fn: Callable[[], Awaitable[bool]] | None = None
    _lease_expires_at: int | None = None

    @property
    def lease_expires_at(self) -> int | None:
        return (
            self._lease_expires_at
            if self._lease_expires_at is not None
            else self.work.lease_expires_at
        )

    async def ensure_lease(self) -> None:
        """Verify and renew the work item lease immediately before external side effects.

        Raises ``StartupLeaseLost`` if the lease has expired or been lost.
        """
        if self._ensure_lease_fn is None:
            return
        ok = await self._ensure_lease_fn()
        if not ok:
            raise StartupLeaseLost(
                f"Work lease lost for work_id={self.work.id} on worker={self.worker_id}"
            )


EffectExecutor = Callable[[ExecutionContext], Awaitable[EffectOutcome]]

# custom-lint: disable-next=workspace-scoped-cache -- process-level effect executor registry
_EXECUTORS: dict[str, EffectExecutor] = {}


def register_executor(
    effect_type: str,
    fn: EffectExecutor,
    *,
    replace: bool = False,
) -> None:
    """Register an async effect executor for the given effect_type."""
    if not effect_type:
        raise ValueError("effect_type must be a non-empty string")
    if effect_type in _EXECUTORS and not replace:
        raise ValueError(f"Effect executor already registered for {effect_type!r}")
    _EXECUTORS[effect_type] = fn


def unregister_executor(effect_type: str, fn: EffectExecutor) -> bool:
    """
    Remove the executor for ``effect_type`` if it is still ``fn``.

    :returns: ``False`` when another executor replaced ``fn`` (it stays) or none is registered.
    """
    if _EXECUTORS.get(effect_type) is not fn:
        return False
    del _EXECUTORS[effect_type]
    return True


def get_executor(effect_type: str) -> EffectExecutor | None:
    """Look up a registered effect executor by effect_type."""
    return _EXECUTORS.get(effect_type)


def clear_executors() -> None:
    """Clear all registered effect executors (used in tests)."""
    _EXECUTORS.clear()


def registered_executor_kinds() -> frozenset[str]:
    """Return the set of currently registered effect types."""
    return frozenset(_EXECUTORS.keys())


__all__ = [
    "EffectCompleted",
    "EffectExecutor",
    "EffectFailed",
    "EffectOutcome",
    "ExecutionContext",
    "StartupLeaseLost",
    "clear_executors",
    "get_executor",
    "register_executor",
    "registered_executor_kinds",
    "unregister_executor",
]
