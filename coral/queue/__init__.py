"""Coral leased work queue, effect executor registry, backoff, and drainer."""

from __future__ import annotations

from coral.queue.backoff import compute_effect_backoff
from coral.queue.conformance import run_executor_conformance
from coral.queue.drainer import FinishedWork, HoldPolicy, WorkDrainer, WorkFinishedHook
from coral.queue.executors import (
    EffectCompleted,
    EffectExecutor,
    EffectFailed,
    EffectOutcome,
    ExecutionContext,
    StartupLeaseLost,
    clear_executors,
    get_executor,
    register_executor,
    registered_executor_kinds,
    unregister_executor,
)
from coral.queue.store import SqlAlchemyCoralQueueStore

__all__ = [
    "EffectCompleted",
    "EffectExecutor",
    "EffectFailed",
    "EffectOutcome",
    "ExecutionContext",
    "FinishedWork",
    "HoldPolicy",
    "SqlAlchemyCoralQueueStore",
    "StartupLeaseLost",
    "WorkDrainer",
    "WorkFinishedHook",
    "clear_executors",
    "compute_effect_backoff",
    "get_executor",
    "register_executor",
    "registered_executor_kinds",
    "run_executor_conformance",
    "unregister_executor",
]
