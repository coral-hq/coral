"""SES-10 admission caps for concurrent structure.start_item effects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdmissionGate:
    """In-memory concurrency window for one repeat group (tests / single worker)."""

    group_key: str
    limit: int
    live: int = 0


def admit(gate: AdmissionGate) -> tuple[AdmissionGate, bool]:
    """Try to admit one more item. Returns (next_gate, admitted)."""
    if gate.limit < 1:
        raise ValueError("admission limit must be at least 1")
    if gate.live >= gate.limit:
        return gate, False
    return AdmissionGate(group_key=gate.group_key, limit=gate.limit, live=gate.live + 1), True


def release(gate: AdmissionGate) -> AdmissionGate:
    """Free one admission slot after an item finishes or is cancelled."""
    live = max(0, gate.live - 1)
    return AdmissionGate(group_key=gate.group_key, limit=gate.limit, live=live)
