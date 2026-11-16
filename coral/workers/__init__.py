"""Coral background worker lease manager and supervisor."""

from __future__ import annotations

from coral.workers.supervisor import WorkerSupervisor
from coral.workers.worker_lease import (
    DEFAULT_WORKER_LEASE_NAME,
    DEFAULT_WORKER_LEASE_SECONDS,
    DEFAULT_WORKER_RENEW_INTERVAL_S,
    WorkerLeaseManager,
)

__all__ = [
    "DEFAULT_WORKER_LEASE_NAME",
    "DEFAULT_WORKER_LEASE_SECONDS",
    "DEFAULT_WORKER_RENEW_INTERVAL_S",
    "WorkerLeaseManager",
    "WorkerSupervisor",
]
