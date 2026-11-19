"""The gate hook of the startup sweep and the resync tick: missing prompts are shown again.

Prompts live only in the process that published them, so the replica that holds
the worker lease shows every open visit's prompt from its row, with the id and
params it was first shown with: once when it takes the lease (a restart, a new
leader), and on every resync tick for prompts its index lost since (a failed
startup republish, a prompt cleared from outside). A prompt still pending here is
never sent again, and a run whose anchor is not created yet is left to its
publish row, so the prompt sweep never fights a republish.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from coral.bridge.executors import BridgeThreads
from coral.db.enum_codecs import SessionBindingProgress
from coral.gates.executors import publish_live
from coral.model.ids import anchor_session_id
from coral.omni.protocols import GatePublisher, PendingGatePrompts, TrackedPrompt
from coral.stores.protocols import GateVisitState
from coral.stores.session_bindings import SessionBindings

_logger = logging.getLogger(__name__)


class GateRepublisher:
    """Shows one run's open gate prompts that this process does not hold; a sweep hook."""

    def __init__(
        self,
        threads: BridgeThreads,
        publisher: GatePublisher,
        *,
        bindings: SessionBindings,
        prompts: PendingGatePrompts,
    ) -> None:
        """
        :param bindings: Reads the run's anchor binding.
        :param prompts: Says whether a prompt is still pending in this process.
        """
        self._threads = threads
        self._publisher = publisher
        self._bindings = bindings
        self._prompts = prompts

    async def __call__(self, gates: Sequence[GateVisitState]) -> None:
        """
        Publish the live visits among ``gates`` whose prompt is not pending here.

        Called in the run's workspace scope.

        :raises ValueError: when ``gates`` holds rows of more than one run.
        :raises EngineLoadFailed: when the run cannot be loaded; it is paused once.
        """
        if not gates:
            return
        first = gates[0]
        workspace_id, run_id = first.workspace_id, first.run_id
        if any((gate.workspace_id, gate.run_id) != (workspace_id, run_id) for gate in gates):
            raise ValueError("a republish batch holds one run's gate rows")
        anchor = anchor_session_id(workspace_id, run_id)
        missing = [
            gate.id
            for gate in gates
            if gate.elicitation_id is None
            or not self._prompts.is_pending(
                TrackedPrompt(workspace_id, anchor, gate.elicitation_id)
            )
        ]
        if not missing:
            return
        binding = await asyncio.to_thread(self._bindings.get, workspace_id, anchor, run_id=run_id)
        if binding is None or binding.progress < SessionBindingProgress.INITIALIZED:
            return
        report = await publish_live(
            self._publisher,
            self._threads,
            workspace_id=workspace_id,
            run_id=run_id,
            visit_ids=missing,
        )
        if report.published:
            _logger.info(
                "Republished %d gate prompts of run %s (%d closed since)",
                len(report.published),
                run_id,
                len(report.withdrawn),
            )


__all__ = ["GateRepublisher"]
