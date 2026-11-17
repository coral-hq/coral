"""Run status for Coral's policies: read through a short cache that each commit clears.

Every policy build rebuilds Coral's policies, so the run status they decide on
is read here: an entry serves for ``ttl_s`` seconds, and the run store's
post-commit hook drops a run's entries at once, so a status changed in this
process applies to the next tool call. The TTL bounds what other processes
commit. When the store cannot be read, an entry no older than ``stale_s``
serves; after that the caller is told the state is unavailable. A missing run
is never kept: creating a run fires no commit hook.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from coral.db.enum_codecs import RunStatus, decode_run_pause_reason, decode_run_status
from coral.stores.protocols import CoralRun
from omnigent.process_logging import log_once

_logger = logging.getLogger(__name__)

# The status of a run whose row does not exist.
MISSING = "missing"


class RunReader(Protocol):
    """The one run-store read the cache needs."""

    def get_run(self, run_id: str, *, workspace_id: int | None = None) -> CoralRun | None: ...


@dataclass(frozen=True)
class RunStatusView:
    """A run's stored status and, while it is paused, the reason when known."""

    status: str  # a RunStatusStr value, or MISSING
    pause_reason: str | None


class RunStateUnavailable(RuntimeError):
    """The run's status could not be read and no recent enough status is kept."""


@dataclass(frozen=True)
class _Entry:
    view: RunStatusView
    read_at: float


@dataclass(eq=False)
class _Read:
    """A store read in flight; a commit to its run meanwhile makes its answer unfit to keep."""

    invalidated: bool = False


class RunStatusCache:
    """Run status by ``(workspace_id, run_id)``; thread-safe, least recently read evicted."""

    def __init__(
        self,
        run_store: RunReader,
        *,
        ttl_s: float = 2.0,
        stale_s: float = 30.0,
        max_entries: int = 4096,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        :param run_store: The run store (only ``get_run`` is used).
        :param ttl_s: How long a read status serves without a new read.
        :param stale_s: How old a status may be to serve while the store fails.
        :param max_entries: How many statuses to keep, at least 1.
        :param clock: Monotonic seconds; tests pass their own.
        :raises ValueError: For ``max_entries`` below 1.
        """
        if max_entries < 1:
            raise ValueError(f"max_entries must be at least 1, not {max_entries}")
        self._run_store = run_store
        self._ttl_s = ttl_s
        self._stale_s = stale_s
        self._max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple[int, str], _Entry] = OrderedDict()
        # The workspaces holding an entry for each run: the commit hook names only the run.
        self._workspaces: dict[str, set[int]] = {}
        self._reads: dict[str, set[_Read]] = {}

    def status(self, workspace_id: int, run_id: str) -> RunStatusView:
        """
        The run's stored status, read again once the kept one is ``ttl_s`` old.

        :raises RunStateUnavailable: When the store read fails (or answers a
            status this server cannot decode) and no status younger than
            ``stale_s`` is kept.
        """
        key = (workspace_id, run_id)
        started = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and started - entry.read_at < self._ttl_s:
                self._entries.move_to_end(key)
                return entry.view
            read = _Read()
            self._reads.setdefault(run_id, set()).add(read)
        try:
            try:
                view = _view(self._run_store.get_run(run_id, workspace_id=workspace_id))
            except Exception as exc:  # noqa: BLE001 -- logged; a recent status or RunStateUnavailable
                return self._stale(key, started, exc)
            with self._lock:
                # A commit after this read began may have changed the status: keep nothing.
                # Nor keep "missing": the run row's insert fires no commit hook.
                if not read.invalidated and view.status != MISSING:
                    self._keep(key, _Entry(view, started))
            return view
        finally:
            with self._lock:
                readers = self._reads[run_id]
                readers.discard(read)
                if not readers:
                    del self._reads[run_id]

    def invalidate(self, run_id: str, _version: int) -> None:
        """Post-commit hook: drop the run's statuses and discard reads still in flight."""
        with self._lock:
            for workspace_id in self._workspaces.pop(run_id, ()):
                self._entries.pop((workspace_id, run_id), None)
            for read in self._reads.get(run_id, ()):
                read.invalidated = True

    def _stale(self, key: tuple[int, str], started: float, error: Exception) -> RunStatusView:
        """A kept status at most ``stale_s`` old, else ``RunStateUnavailable``; in ``except``."""
        workspace_id, run_id = key
        log_traceback_once(_logger, "run status read", error)
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or started - entry.read_at > self._stale_s:
            _logger.warning(
                "Coral run %s status unreadable (%s); denying its sessions' tool calls",
                run_id,
                type(error).__name__,
                extra={"coral_workspace_id": workspace_id},
            )
            raise RunStateUnavailable(f"run {run_id!r} status is unavailable") from error
        _logger.warning(
            "Coral run %s status unreadable (%s); using the one read %.1f s ago",
            run_id,
            type(error).__name__,
            started - entry.read_at,
            extra={"coral_workspace_id": workspace_id},
        )
        return entry.view

    def _keep(self, key: tuple[int, str], entry: _Entry) -> None:
        """Store *entry*; the caller holds the lock."""
        workspace_id, run_id = key
        self._entries[key] = entry
        self._entries.move_to_end(key)
        self._workspaces.setdefault(run_id, set()).add(workspace_id)
        while len(self._entries) > self._max_entries:
            (old_workspace, old_run), _ = self._entries.popitem(last=False)
            workspaces = self._workspaces[old_run]
            workspaces.discard(old_workspace)
            if not workspaces:
                del self._workspaces[old_run]


def log_traceback_once(logger: logging.Logger, what: str, error: BaseException) -> None:
    """
    Log *what*'s failure traceback once per process and exception class.

    Called while *error* is being handled. Callers log one line per failure
    as well, so a long store outage does not repeat the traceback on every
    policy build. The key names only the site and the class, never an id,
    because the seen-set is never cleared.
    """
    log_once(
        logger,
        logging.WARNING,
        "Coral %s failed with %s (traceback logged once per error type)",
        what,
        type(error).__name__,
        exc_info=True,
    )


def _view(run: CoralRun | None) -> RunStatusView:
    """The view of a stored row; raises ``ValueError`` for a code this server cannot decode."""
    if run is None:
        return RunStatusView(MISSING, None)
    status = decode_run_status(run.status)
    reason = None
    if run.status == RunStatus.PAUSED and run.pause_reason is not None:
        try:
            reason = decode_run_pause_reason(run.pause_reason)
        except ValueError:
            reason = None  # a reason this server cannot name still pauses the run
    return RunStatusView(status, reason)
