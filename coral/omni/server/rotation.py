"""Follow native ``/clear`` supersession for Coral-bound step sessions (HRN-07)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from coral.bridge.bound_sessions import BoundSession, BoundSessions
from coral.stores.session_bindings import BindingNotFound, SessionBinding, SessionBindings

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


@dataclass(frozen=True)
class RotationFollowResult:
    """Outcome of transferring a Coral binding after supersession."""

    workspace_id: int
    binding: SessionBinding
    bound: BoundSession


def follow_bound_supersession(
    *,
    old_id: str,
    new_id: str,
    bound: BoundSessions,
    bindings: SessionBindings,
) -> list[RotationFollowResult]:
    """Rebind every Coral workspace entry for *old_id* onto *new_id*.

    Transfers ``coral_session_bindings`` at the same generation and rekeys the
    in-memory bound-session index. Callers that need policies, labels, or a
    re-brief layer those on after this returns.
    """
    if old_id == new_id:
        return []
    results: list[RotationFollowResult] = []
    for workspace_id, entry in bound.entries_for(old_id):
        try:
            moved = bindings.transfer(workspace_id, old_id, new_id)
        except BindingNotFound:
            _logger.info(
                "no binding to transfer for supersession old=%s workspace=%s",
                old_id,
                workspace_id,
            )
            continue
        except Exception:
            _logger.exception(
                "binding transfer failed old=%s new=%s workspace=%s",
                old_id,
                new_id,
                workspace_id,
            )
            continue
        bound.rekey(workspace_id, old_id, new_id)
        results.append(RotationFollowResult(workspace_id=workspace_id, binding=moved, bound=entry))
        _logger.info(
            "coral supersession rebound old=%s new=%s run=%s slot=%s gen=%s",
            old_id,
            new_id,
            moved.run_id,
            moved.slot_id,
            moved.session_generation,
        )
    return results


def register_follower(follower: SupersessionFollower) -> Callable[[], None]:
    """Register *follower* on Omnigent's supersession observer list."""
    from coral.omni._upstream import register_supersession_observer

    return register_supersession_observer(follower.observe)


__all__ = [
    "RotationFollowResult",
    "SupersessionFollower",
    "follow_bound_supersession",
    "register_follower",
]
