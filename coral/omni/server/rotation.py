"""Follow native ``/clear`` supersession for Coral-bound step sessions (HRN-07)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

_logger = logging.getLogger("coral.omni.server.rotation")


@dataclass
class SupersessionFollower:
    """O(1) lookup of bound sessions; hands work off the event loop via *enqueue*."""

    bound_session_ids: Callable[[], set[str]]
    enqueue: Callable[[str, str, str], None]
    _seen: set[tuple[str, str]] = field(default_factory=set)

    def observe(self, old_id: str, new_id: str, reason: str) -> None:
        """If *old_id* is Coral-bound, enqueue re-attach work for *new_id*."""
        if (old_id, new_id) in self._seen:
            return
        try:
            bound = self.bound_session_ids()
        except Exception:
            _logger.exception("bound session lookup failed for supersession %s", old_id)
            return
        if old_id not in bound:
            return
        self._seen.add((old_id, new_id))
        try:
            self.enqueue(old_id, new_id, reason)
        except Exception:
            _logger.exception("failed to enqueue rotation follow old=%s new=%s", old_id, new_id)


def register_follower(follower: SupersessionFollower) -> Callable[[], None]:
    """Register *follower* on Omnigent's supersession observer list."""
    from coral.omni._upstream import register_supersession_observer

    return register_supersession_observer(follower.observe)


__all__ = ["SupersessionFollower", "register_follower"]
