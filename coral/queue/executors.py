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


@dataclass(frozen=True, slots=True)
class ExecutorRegistration:
    """
    A registered effect executor and how the drainer fences its items.

    :param runs_after_terminal: Items of a finished run still run instead of
        being abandoned as ``run.terminal``; the slot-generation fence still applies.
    """

    fn: EffectExecutor
    runs_after_terminal: bool = False


# custom-lint: disable-next=workspace-scoped-cache -- process-level effect executor registry
_EXECUTORS: dict[str, ExecutorRegistration] = {}


def register_executor(
    effect_type: str,
    fn: EffectExecutor,
    *,
    replace: bool = False,
    runs_after_terminal: bool = False,
) -> None:
    """
    Register an async effect executor for the given effect_type.

    :param runs_after_terminal: For effects that wind a finished run down, such
        as stopping its sessions: the drainer runs them after the run ended.
    """
    if not effect_type:
        raise ValueError("effect_type must be a non-empty string")
    if effect_type in _EXECUTORS and not replace:
        raise ValueError(f"Effect executor already registered for {effect_type!r}")
    _EXECUTORS[effect_type] = ExecutorRegistration(fn, runs_after_terminal=runs_after_terminal)


def unregister_executor(effect_type: str, fn: EffectExecutor) -> bool:
    """
    Remove the executor for ``effect_type`` if it is still ``fn``.

    :returns: ``False`` when another executor replaced ``fn`` (it stays) or none is registered.
    """
    registration = _EXECUTORS.get(effect_type)
    if registration is None or registration.fn is not fn:
        return False
    del _EXECUTORS[effect_type]
    return True


def get_registration(effect_type: str) -> ExecutorRegistration | None:
    """Look up the registration of an effect type: its executor and its fencing."""
    return _EXECUTORS.get(effect_type)


def get_executor(effect_type: str) -> EffectExecutor | None:
    """Look up a registered effect executor by effect_type."""
    registration = _EXECUTORS.get(effect_type)
    return None if registration is None else registration.fn


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
    "ExecutorRegistration",
    "StartupLeaseLost",
    "clear_executors",
    "get_executor",
    "get_registration",
    "register_executor",
    "registered_executor_kinds",
    "unregister_executor",
]
