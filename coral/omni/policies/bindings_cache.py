"""A binding lookup that keeps the rows it found, for checks made on every policy build.

A binding never changes its run, role, slot or generation once reserved and is
never deleted, so a found row can be reused for those. Its ``progress`` does
change, so this cache never declares ``reads_fresh``: the engine-tool bridge
refuses it. A miss always reads the store, so a binding reserved a moment ago
is never hidden.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from coral.stores.session_bindings import SessionBinding, SessionBindingLookup


class CachedBindingLookup:
    """A :class:`SessionBindingLookup` that keeps found rows, least recently read evicted."""

    def __init__(self, lookup: SessionBindingLookup, *, max_entries: int = 4096) -> None:
        """
        :param lookup: The store to read.
        :param max_entries: How many found rows to keep, at least 1.
        :raises ValueError: For ``max_entries`` below 1.
        """
        if max_entries < 1:
            raise ValueError(f"max_entries must be at least 1, not {max_entries}")
        self._lookup = lookup
        self._max_entries = max_entries
        self._lock = threading.Lock()
        # Keyed by (workspace id, session id), like the bindings table.
        self._found: OrderedDict[tuple[int, str], SessionBinding] = OrderedDict()

    def find_by_session(self, workspace_id: int, session_id: str) -> SessionBinding | None:
        """The session's binding in *workspace_id*, from the cache when found before.

        A store error propagates, and nothing is kept for that read.
        """
        key = (workspace_id, session_id)
        with self._lock:
            found = self._found.get(key)
            if found is not None:
                self._found.move_to_end(key)
                return found
        binding = self._lookup.find_by_session(workspace_id, session_id)
        if binding is not None:
            with self._lock:
                self._found[key] = binding
                self._found.move_to_end(key)
                while len(self._found) > self._max_entries:
                    self._found.popitem(last=False)
        return binding
