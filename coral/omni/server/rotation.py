"""Follow native ``/clear`` supersession for Coral-bound step sessions (HRN-07)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from coral.bridge.bound_sessions import BoundSession, BoundSessions
from coral.stores.session_bindings import BindingNotFound, SessionBinding, SessionBindings
from omnigent.db.db_models import workspace_scope

_logger = logging.getLogger("coral.omni.server.rotation")

# Deterministic policy ids for re-attach after /clear (K10).
_POLICY_NAMESPACE = uuid.UUID("6f1c0a2e-9b4d-4e7a-8c3f-1d2e5a7b9c0d")


class _PolicyStore(Protocol):
    def list_for_session(self, session_id: str) -> list[Any]: ...

    def create(
        self,
        policy_id: str,
        session_id: str,
        name: str,
        type: str,
        handler: str,
        factory_params: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> Any: ...


class _Conversations(Protocol):
    def get_conversation(self, conversation_id: str) -> Any: ...

    def set_labels(self, conversation_id: str, updates: dict[str, str]) -> None: ...


def _carry_coral_labels(
    workspace_id: int, old_id: str, new_id: str, conversations: _Conversations
) -> None:
    """Give *new_id* the ``coral.`` labels by which the server knows a session is Coral's."""
    try:
        with workspace_scope(workspace_id):
            old = conversations.get_conversation(old_id)
            labels = {
                key: value
                for key, value in (getattr(old, "labels", None) or {}).items()
                if key.startswith("coral.")
            }
            if labels:
                conversations.set_labels(new_id, labels)
    except Exception:
        _logger.exception("coral labels not carried old=%s new=%s", old_id, new_id)


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


def _reattach_session_policies(old_id: str, new_id: str, policy_store: _PolicyStore | None) -> int:
    """Copy session-scoped policies onto *new_id* with deterministic ids. Returns count."""
    if policy_store is None:
        return 0
    try:
        policies = policy_store.list_for_session(old_id)
    except Exception:
        _logger.exception("list policies failed for supersession old=%s", old_id)
        return 0
    attached = 0
    for policy in policies:
        name = getattr(policy, "name", None)
        handler = getattr(policy, "handler", None)
        policy_type = getattr(policy, "type", None)
        if (
            not isinstance(name, str)
            or not isinstance(handler, str)
            or not isinstance(policy_type, str)
        ):
            continue
        policy_id = "pol_" + uuid.uuid5(_POLICY_NAMESPACE, f"{new_id}:{name}").hex
        try:
            policy_store.create(
                policy_id,
                new_id,
                name,
                policy_type,
                handler,
                factory_params=getattr(policy, "factory_params", None),
                enabled=bool(getattr(policy, "enabled", True)),
            )
            attached += 1
        except Exception:
            _logger.exception(
                "policy re-attach failed old=%s new=%s name=%s", old_id, new_id, name
            )
    return attached


def follow_bound_supersession(
    *,
    old_id: str,
    new_id: str,
    bound: BoundSessions,
    bindings: SessionBindings,
    policy_store: _PolicyStore | None = None,
    conversations: _Conversations | None = None,
) -> list[RotationFollowResult]:
    """Rebind every Coral workspace entry for *old_id* onto *new_id*.

    Transfers ``coral_session_bindings`` at the same generation, rekeys the
    in-memory bound-session index, and best-effort carries the ``coral.``
    labels and re-attaches session policies.
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
        if conversations is not None:
            _carry_coral_labels(workspace_id, old_id, new_id, conversations)
        attached = _reattach_session_policies(old_id, new_id, policy_store)
        results.append(RotationFollowResult(workspace_id=workspace_id, binding=moved, bound=entry))
        _logger.info(
            "coral supersession rebound old=%s new=%s run=%s slot=%s gen=%s policies=%s",
            old_id,
            new_id,
            moved.run_id,
            moved.slot_id,
            moved.session_generation,
            attached,
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
