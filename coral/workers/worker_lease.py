"""Singleton worker replica lease manager backed by coral_worker_leases."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable

from coral.stores.protocols import QueueStore

DEFAULT_WORKER_LEASE_NAME = "coral.worker.primary"
DEFAULT_WORKER_LEASE_SECONDS = 120
DEFAULT_WORKER_RENEW_INTERVAL_S = 30.0


class WorkerLeaseManager:
    """Manages acquisition, renewal, and release of the singleton Coral worker lease."""

    def __init__(
        self,
        queue_store: QueueStore,
        *,
        worker_id: str | None = None,
        lease_name: str = DEFAULT_WORKER_LEASE_NAME,
        lease_seconds: int = DEFAULT_WORKER_LEASE_SECONDS,
        renew_interval_s: float = DEFAULT_WORKER_RENEW_INTERVAL_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._queue_store = queue_store
        self._worker_id = worker_id or f"coral-worker-{uuid.uuid4().hex[:12]}"
        self._lease_name = lease_name
        self._lease_seconds = lease_seconds
        self._renew_interval_s = renew_interval_s
        self._clock = clock
        self._is_leader = False
        self._lease_lost_event = asyncio.Event()
        # This replica's clock when the store last confirmed the lease, read before the call.
        self._confirmed_at: float | None = None

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def lease_name(self) -> str:
        return self._lease_name

    @property
    def lease_seconds(self) -> int:
        return self._lease_seconds

    @property
    def renew_interval_s(self) -> float:
        return self._renew_interval_s

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def lease_lost_event(self) -> asyncio.Event:
        return self._lease_lost_event

    @property
    def confirmed_until(self) -> float | None:
        """The latest the held lease can last by this replica's clock; ``None`` when not leader."""
        if not self._is_leader or self._confirmed_at is None:
            return None
        return self._confirmed_at + self._lease_seconds

    def mark_lost(self) -> None:
        """Stop leading without the store, when the lease could not be confirmed in time."""
        self._is_leader = False
        self._lease_lost_event.set()

    async def try_acquire(self) -> bool:
        """Attempt to acquire the worker lease; clears lease_lost_event on success."""
        started = self._clock()
        acquired = await asyncio.to_thread(
            self._queue_store.acquire_worker_lease,
            self._lease_name,
            self._worker_id,
            lease_seconds=self._lease_seconds,
            now_fn=self._clock,
        )
        if acquired:
            self._is_leader = True
            self._confirmed_at = started
            self._lease_lost_event.clear()
        else:
            self._is_leader = False
        return acquired

    async def renew_once(self) -> bool:
        """Renew the held worker lease; sets lease_lost_event if renewal fails."""
        if not self._is_leader:
            return False
        started = self._clock()
        renewed = await asyncio.to_thread(
            self._queue_store.renew_worker_lease,
            self._lease_name,
            self._worker_id,
            lease_seconds=self._lease_seconds,
            now_fn=self._clock,
        )
        if renewed:
            self._confirmed_at = started
        else:
            self._is_leader = False
            self._lease_lost_event.set()
        return renewed

    async def release(self) -> bool:
        """Release the held worker lease immediately on shutdown."""
        was_leader = self._is_leader
        self._is_leader = False
        self._lease_lost_event.set()
        if not was_leader:
            return False
        return await asyncio.to_thread(
            self._queue_store.release_worker_lease,
            self._lease_name,
            self._worker_id,
        )


__all__ = [
    "DEFAULT_WORKER_LEASE_NAME",
    "DEFAULT_WORKER_LEASE_SECONDS",
    "DEFAULT_WORKER_RENEW_INTERVAL_S",
    "WorkerLeaseManager",
]
