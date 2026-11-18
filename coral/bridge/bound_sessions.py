"""Which sessions are bound to an engine slot of an unfinished run, answered in one dict read.

The status-edge recorder asks on every published edge, on the publishing thread, so
a lookup takes no lock and does no I/O. The index is rebuilt from the binding store
every minute, so finished runs drop out, and a create's feedback pushes its session
at once. A push made while a rebuild reads the store is kept by that rebuild.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from coral.bridge.keys import ORCHESTRATOR_SLOT_ID, store_slot_id
from coral.db.enum_codecs import SessionBindingRole, WorkKind, WorkStatus
from coral.queue.drainer import FinishedWork
from coral.slots.executors import CREATE_SESSION
from coral.stores.session_bindings import SessionBinding

SessionKey = tuple[int, str]


@dataclass(frozen=True)
class BoundSession:
    """
    The engine slot a session serves.

    :param engine_slot_id: The engine's slot id; ``orchestrator`` for the run's orchestrator.
    :param store_slot_id: The ``coral_agent_slots`` id, which fences stale signals.
    """

    run_id: str
    engine_slot_id: str
    store_slot_id: str
    generation: int
    orchestrator: bool = False

    @classmethod
    def of(cls, run_id: str, engine_slot_id: str, generation: int) -> BoundSession:
        return cls(
            run_id=run_id,
            engine_slot_id=engine_slot_id,
            store_slot_id=store_slot_id(run_id, engine_slot_id),
            generation=generation,
            orchestrator=engine_slot_id == ORCHESTRATOR_SLOT_ID,
        )

    @classmethod
    def from_binding(cls, binding: SessionBinding) -> BoundSession | None:
        """The slot a step binding names; ``None`` for an anchor or a binding without a slot."""
        if binding.role is not SessionBindingRole.STEP or not binding.slot_id:
            return None
        return cls.of(binding.run_id, binding.slot_id, binding.session_generation)


class BoundSessionSource(Protocol):
    """The binding store's listing of bound sessions of unfinished runs, keyset-paged."""

    def list_bound_sessions(
        self, *, cursor: tuple[int, str] | None = None, limit: int = 500
    ) -> list[SessionBinding]: ...


class BoundSessions:
    """``(workspace_id, session_id)`` to the slot it serves; thread-safe, lookups lock-free."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[SessionKey, BoundSession] = {}
        self._pushes = 0
        # Pushes since a rebuild began reading, with their count, so it can keep them.
        self._rebuilding = False
        self._recent: list[tuple[int, SessionKey, BoundSession]] = []

    def __len__(self) -> int:
        return len(self._entries)

    def lookup(self, workspace_id: int, session_id: str) -> BoundSession | None:
        """One dict read; safe on any thread, never blocks."""
        return self._entries.get((workspace_id, session_id))

    def push(self, workspace_id: int, session_id: str, bound: BoundSession) -> None:
        """Index a session whose create just completed."""
        key = (workspace_id, session_id)
        with self._lock:
            self._pushes += 1
            if self._rebuilding:
                self._recent.append((self._pushes, key, bound))
            self._entries[key] = bound

    def begin_rebuild(self) -> int:
        """
        Mark the start of a rebuild's read; pass the result to :meth:`replace`.

        Pushes before it are in the store the rebuild reads, so only later ones are kept.
        """
        with self._lock:
            self._rebuilding = True
            self._recent = []
            return self._pushes

    def replace(self, entries: Mapping[SessionKey, BoundSession], *, since: int) -> None:
        """Swap in a rebuilt index, keeping the pushes made after ``since``."""
        with self._lock:
            rebuilt = dict(entries)
            for count, key, bound in self._recent:
                if count > since:
                    rebuilt[key] = bound
            self._recent = []
            self._rebuilding = False
            self._entries = rebuilt


def created_session(finished: FinishedWork) -> tuple[int, str, BoundSession] | None:
    """
    The step or orchestrator session a finished create made, keyed by its workspace.

    ``None`` for any other row: another kind, a failure, the anchor, or a result
    without a session id.
    """
    item = finished.item
    if item.kind != int(WorkKind.EFFECT) or finished.status != int(WorkStatus.SUCCEEDED):
        return None
    payload = _object(item.payload)
    session_id = (finished.result or {}).get("session_id")
    engine_slot_id = payload.get("engine_slot_id")
    generation = payload.get("generation")
    if (
        payload.get("effect_type") != CREATE_SESSION
        or payload.get("role") != "step"
        or not isinstance(session_id, str)
        or not session_id
        or not isinstance(engine_slot_id, str)
        or not engine_slot_id
        or not isinstance(generation, int)
        or isinstance(generation, bool)
    ):
        return None
    return item.workspace_id, session_id, BoundSession.of(item.run_id, engine_slot_id, generation)


def _object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text) if text else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


__all__ = [
    "BoundSession",
    "BoundSessionSource",
    "BoundSessions",
    "SessionKey",
    "created_session",
]
