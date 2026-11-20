"""An in-memory observation log, for tests of capture and of the submit check."""

from __future__ import annotations

import threading
from collections.abc import Sequence

from coral.evidence.ir import CommandObservation


class InMemoryObservationLog:
    """Rows keyed by ``(workspace_id, session_id, op_key)``; a repeated key is ignored."""

    def __init__(self) -> None:
        self._rows: dict[tuple[int, str, str], CommandObservation] = {}
        self.run_ids: dict[tuple[int, str, str], str] = {}
        self._lock = threading.Lock()
        self.fail_next: Exception | None = None

    def record(self, workspace_id: int, run_id: str, observation: CommandObservation) -> bool:
        """Store ``observation``; ``False`` when its key was already stored."""
        with self._lock:
            if self.fail_next is not None:
                error, self.fail_next = self.fail_next, None
                raise error
            key = (workspace_id, observation.session_id, observation.op_key)
            if key in self._rows:
                return False
            self._rows[key] = observation
            self.run_ids[key] = run_id
            return True

    def list_for_session(self, workspace_id: int, session_id: str) -> Sequence[CommandObservation]:
        with self._lock:
            return sorted(
                (
                    obs
                    for (workspace, session, _key), obs in self._rows.items()
                    if workspace == workspace_id and session == session_id
                ),
                key=lambda obs: (obs.obs_seq, obs.op_key),
            )


__all__ = ["InMemoryObservationLog"]
