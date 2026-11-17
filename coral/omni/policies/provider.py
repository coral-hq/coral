"""Coral's required-policy provider: the policies every session bound to a run gets.

The session's binding row, read by session id, decides: never its labels or
its bundle. A run's anchor gets a deny-all and nothing else. Every other bound
session gets the run guard, built from the run's stored status and the row's
``omnigent.closed`` label, then its role guard (the orchestrator allowlist or
the step roster). The run guard goes first, so on a stopped run every deny
says to stop; a role guard's text shows only while the run is live. The
policies go ahead of every other policy and decide tool calls only. A store
error never raises: the session's tool calls are denied until the state can
be read.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from coral.db.enum_codecs import SessionBindingRole, SlotRole
from coral.omni.policies.state import RunStateUnavailable, RunStatusCache, log_traceback_once
from coral.omni.server.sessions import RUN_ID_LABEL_KEY
from omnigent.db.db_models import current_workspace_id
from omnigent.spec.types import FunctionPolicySpec, FunctionRef
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE

if TYPE_CHECKING:
    from coral.stores.session_bindings import SessionBindingLookup
    from omnigent.entities import Conversation
    from omnigent.spec.types import AgentSpec, PolicySpec

_logger = logging.getLogger(__name__)

_GUARDS = "coral.omni.policies.guards"
_RUN_GUARD_PATH = "coral.omni.policies.run_guard.run_guard"
# S52's tool-call-only deny, reused for Coral's own unreadable-state deny.
_DENY_TOOL_CALLS_PATH = "omnigent.runtime.policies.required_providers.deny_tool_calls"
_STATE_UNAVAILABLE = (
    "[run.state_unavailable] Coral cannot read this session's run state right now, so its "
    "tool calls are denied. Stop now and end your turn."
)


class CoralPolicyProvider:
    """The S52 provider registered as ``"coral"``; thread-safe."""

    def __init__(self, *, bindings: SessionBindingLookup, statuses: RunStatusCache) -> None:
        """
        :param bindings: Finds a session's binding row (the shared positive-only
            cache in production).
        :param statuses: The run-status cache the run store's commits invalidate.
        """
        self._bindings = bindings
        self._statuses = statuses

    def applies(self, spec: AgentSpec, conversation: Conversation | None) -> bool:
        """Whether the session may be bound: a Coral bundle, or a ``coral.run_id`` label.

        A hint to look, never proof of membership. O(1), reads nothing, never raises.
        """
        params = getattr(spec, "params", None)
        if isinstance(params, Mapping) and "coral" in params:
            return True
        labels = getattr(conversation, "labels", None)
        return isinstance(labels, Mapping) and RUN_ID_LABEL_KEY in labels

    def specs(self, spec: AgentSpec, conversation: Conversation) -> list[PolicySpec]:  # noqa: ARG002
        """The bound session's policies, in evaluation order; none for an unbound session.

        The binding row decides, never the bundle, so ``spec`` is not read.
        """
        try:
            binding = self._bindings.find_by_session(current_workspace_id(), conversation.id)
        except Exception as exc:  # noqa: BLE001 -- logged; denies tool calls, never fails the build
            log_traceback_once(_logger, "binding lookup", exc)
            _logger.warning(
                "Coral could not look up session %s's binding (%s); denying its tool calls",
                conversation.id,
                type(exc).__name__,
                extra={"session_id": conversation.id},
            )
            return [_state_unavailable()]
        if binding is None:
            return []
        if binding.role == SessionBindingRole.ANCHOR:
            # Coral never runs the anchor: nothing else applies to it.
            return [_policy("__coral_anchor_deny_all", f"{_GUARDS}.deny_all_tools")]
        orchestrator = binding.slot_role == SlotRole.ORCHESTRATOR
        role_guard = (
            _policy("__coral_orchestrator_guard", f"{_GUARDS}.orchestrator_guard")
            if orchestrator
            else _policy("__coral_step_roster", f"{_GUARDS}.step_roster")
        )
        try:
            view = self._statuses.status(binding.workspace_id, binding.run_id)
        except RunStateUnavailable:
            return [_state_unavailable(), role_guard]
        labels = conversation.labels or {}
        run_guard = _policy(
            "__coral_run_guard",
            _RUN_GUARD_PATH,
            {
                "run_status": view.status,
                "pause_reason": view.pause_reason,
                # The label alone: a renamed title never makes a step inert.
                "closed": labels.get(CLOSED_LABEL_KEY) == CLOSED_LABEL_VALUE,
                "orchestrator": orchestrator,
            },
        )
        return [run_guard, role_guard]


def _policy(
    name: str, path: str, arguments: dict[str, object] | None = None
) -> FunctionPolicySpec:
    """A function policy on every event; each Coral evaluator decides tool calls only."""
    return FunctionPolicySpec(
        name=name, on=None, function=FunctionRef(path=path, arguments=arguments)
    )


def _state_unavailable() -> FunctionPolicySpec:
    return _policy(
        "__coral_state_unavailable", _DENY_TOOL_CALLS_PATH, {"reason": _STATE_UNAVAILABLE}
    )
