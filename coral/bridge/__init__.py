"""The engine-to-queue bridge: engine state from the run log, effects as queued work.

Public names load on first use, so importing one bridge module does not load
the others (the mapper imports the session executors, which other modules use).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from coral.bridge.codec import EngineLogDecodeError as EngineLogDecodeError
    from coral.bridge.codec import decode_entries as decode_entries
    from coral.bridge.codec import entry_draft as entry_draft
    from coral.bridge.commit import Applied as Applied
    from coral.bridge.commit import CommitExtras as CommitExtras
    from coral.bridge.commit import EngineSnapshot as EngineSnapshot
    from coral.bridge.commit import build_commit as build_commit
    from coral.bridge.config import FrozenConfigMissing as FrozenConfigMissing
    from coral.bridge.config import engine_config_for as engine_config_for
    from coral.bridge.config import freeze_engine_config as freeze_engine_config
    from coral.bridge.config import utc_now as utc_now
    from coral.bridge.executors import BoundedThreads as BoundedThreads
    from coral.bridge.executors import BridgeThreads as BridgeThreads
    from coral.bridge.executors import bridge_hold_policy as bridge_hold_policy
    from coral.bridge.executors import run_resync_executor as run_resync_executor
    from coral.bridge.executors import timer_executor as timer_executor
    from coral.bridge.fold import EngineStateCache as EngineStateCache
    from coral.bridge.fold import FoldedRun as FoldedRun
    from coral.bridge.graphs import PinnedGraphError as PinnedGraphError
    from coral.bridge.graphs import PinnedGraphMismatch as PinnedGraphMismatch
    from coral.bridge.graphs import PinnedGraphs as PinnedGraphs
    from coral.bridge.keys import ORCHESTRATOR_SLOT_ID as ORCHESTRATOR_SLOT_ID
    from coral.bridge.mapping import FED_KINDS as FED_KINDS
    from coral.bridge.mapping import MapContext as MapContext
    from coral.bridge.mapping import map_effect as map_effect
    from coral.bridge.port import StoreDecisionPort as StoreDecisionPort
    from coral.bridge.projection import project_run as project_run
    from coral.bridge.projection import project_slots as project_slots
    from coral.bridge.service import BridgeCommit as BridgeCommit
    from coral.bridge.service import EngineBridge as EngineBridge
    from coral.bridge.service import EngineLoadFailed as EngineLoadFailed
    from coral.bridge.service import ResyncReport as ResyncReport
    from coral.bridge.start import RunNotRunnable as RunNotRunnable
    from coral.bridge.start import start_engine_run as start_engine_run

_MODULES: dict[str, str] = {
    "EngineLogDecodeError": "coral.bridge.codec",
    "Applied": "coral.bridge.commit",
    "CommitExtras": "coral.bridge.commit",
    "EngineSnapshot": "coral.bridge.commit",
    "build_commit": "coral.bridge.commit",
    "decode_entries": "coral.bridge.codec",
    "entry_draft": "coral.bridge.codec",
    "FrozenConfigMissing": "coral.bridge.config",
    "engine_config_for": "coral.bridge.config",
    "freeze_engine_config": "coral.bridge.config",
    "utc_now": "coral.bridge.config",
    "BoundedThreads": "coral.bridge.executors",
    "BridgeThreads": "coral.bridge.executors",
    "bridge_hold_policy": "coral.bridge.executors",
    "run_resync_executor": "coral.bridge.executors",
    "timer_executor": "coral.bridge.executors",
    "EngineStateCache": "coral.bridge.fold",
    "FoldedRun": "coral.bridge.fold",
    "PinnedGraphError": "coral.bridge.graphs",
    "PinnedGraphMismatch": "coral.bridge.graphs",
    "PinnedGraphs": "coral.bridge.graphs",
    "ORCHESTRATOR_SLOT_ID": "coral.bridge.keys",
    "FED_KINDS": "coral.bridge.mapping",
    "MapContext": "coral.bridge.mapping",
    "map_effect": "coral.bridge.mapping",
    "StoreDecisionPort": "coral.bridge.port",
    "project_run": "coral.bridge.projection",
    "project_slots": "coral.bridge.projection",
    "BridgeCommit": "coral.bridge.service",
    "EngineBridge": "coral.bridge.service",
    "EngineLoadFailed": "coral.bridge.service",
    "ResyncReport": "coral.bridge.service",
    "RunNotRunnable": "coral.bridge.start",
    "start_engine_run": "coral.bridge.start",
}

__all__ = sorted(_MODULES)


def __getattr__(name: str) -> Any:
    module = _MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
