"""The per-process gate prompt sweep: a tracked prompt stays only while it is a live visit's.

Every process sweeps the prompts it saw published, leader or not, because each
holds its own index of prompts. A prompt goes stale when its visit was answered
on another replica, when an answer committed but its reply never reached the
caller, or when a withdraw was missed; it is withdrawn here. A run's ``OPEN`` gate
rows are exactly its live visits, so the sweep reads those rows and loads no
engine state. The tracked prompts are listed before any rows are read, so a
prompt published after a read is never judged by that older read.
"""

from __future__ import annotations

import asyncio
import logging

from coral.bridge.executors import BridgeThreads
from coral.db.enum_codecs import SessionBindingRole
from coral.model.ids import anchor_session_id
from coral.omni.protocols import GatePublisher, PendingGatePrompts, RunScopeRunner, TrackedPrompt
from coral.queue.run_effects import describe_exception, raise_if_cancelling
from coral.stores.protocols import RunStore
from coral.stores.session_bindings import SessionBindingLookup

_logger = logging.getLogger(__name__)

SWEEP_INTERVAL_S = 60.0


class GatePromptSweeper:
    """Withdraws this process's tracked gate prompts that are no live visit's."""

    def __init__(
        self,
        *,
        threads: BridgeThreads,
        run_store: RunStore,
        bindings: SessionBindingLookup,
        publisher: GatePublisher,
        prompts: PendingGatePrompts,
        scope_runner: RunScopeRunner,
        interval_s: float = SWEEP_INTERVAL_S,
    ) -> None:
        self._threads = threads
        self._runs = run_store
        self._bindings = bindings
        self._publisher = publisher
        self._prompts = prompts
        self._scope = scope_runner
        self._interval_s = interval_s
        self._failures_logged: set[str] = set()

    async def sweep_once(self) -> int:
        """
        Withdraw each tracked prompt still pending that is no live visit's; untrack the rest.

        A prompt on a session that is not a run's anchor is stale. A run whose rows
        cannot be read keeps its prompts until a later sweep. Each run is read once.

        :returns: How many prompts were withdrawn.
        """
        tracked = self._prompts.tracked()
        live: dict[tuple[int, str], frozenset[str]] = {}
        withdrawn = 0
        for prompt in tracked:
            try:
                async with self._scope.run_scope(workspace_id=prompt.workspace_id):
                    if not self._prompts.is_pending(prompt):
                        self._prompts.forget(prompt)
                        continue
                    key = (prompt.workspace_id, prompt.session_id)
                    if key not in live:
                        live[key] = await self._live_prompts(prompt)
                    if prompt.elicitation_id in live[key]:
                        continue
                    if await self._publisher.withdraw(
                        session_id=prompt.session_id, elicitation_id=prompt.elicitation_id
                    ):
                        withdrawn += 1
                    self._prompts.forget(prompt)
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- retried next sweep
                raise_if_cancelling(exc)
                self._log_failure(exc)
        return withdrawn

    async def run(self, stop: asyncio.Event) -> None:
        """Sweep every interval until ``stop`` is set."""
        while not await _stopped_within(stop, self._interval_s):
            try:
                await self.sweep_once()
            except (Exception, asyncio.CancelledError) as exc:  # noqa: BLE001 -- retried
                raise_if_cancelling(exc)
                self._log_failure(exc)

    async def _live_prompts(self, prompt: TrackedPrompt) -> frozenset[str]:
        """
        The prompt ids of the live visits of the run whose anchor the session is.

        Empty when the session is no run's anchor or its run is gone.
        """
        workspace_id, session_id = prompt.workspace_id, prompt.session_id
        binding = await self._threads.run(self._bindings.find_by_session, workspace_id, session_id)
        if (
            binding is None
            or binding.role != SessionBindingRole.ANCHOR
            or anchor_session_id(workspace_id, binding.run_id) != session_id
        ):
            return frozenset()
        gates = await self._threads.run(
            self._runs.list_open_gates, binding.run_id, workspace_id=workspace_id
        )
        return frozenset(gate.elicitation_id for gate in gates if gate.elicitation_id is not None)

    def _log_failure(self, exc: BaseException) -> None:
        """Log a failure kind once with its cause; later ones of that kind at debug."""
        kind = type(exc).__name__
        if kind in self._failures_logged:
            _logger.debug("Coral's gate prompt sweep failed again: %s", describe_exception(exc))
            return
        self._failures_logged.add(kind)
        _logger.warning(
            "Coral's gate prompt sweep failed; retrying at the next sweep: %s",
            describe_exception(exc),
        )


async def _stopped_within(stop: asyncio.Event, timeout_s: float) -> bool:
    """Whether ``stop`` is set within ``timeout_s`` seconds."""
    try:
        await asyncio.wait_for(stop.wait(), timeout_s)
    except TimeoutError:
        return False
    return True


__all__ = ["SWEEP_INTERVAL_S", "GatePromptSweeper"]
