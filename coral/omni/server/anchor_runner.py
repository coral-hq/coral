"""Stop a runner someone attached to a run's anchor, once drift has paused the run.

A run's anchor never runs, so a runner attached to it (``anchor_bound``
drift) only serves its owner's chat outside the run. After the drift pause,
:class:`AnchorRunnerStopper` sends the anchor a ``stop_session`` through the
engine dispatch, as the run owner: that stops the anchor's session on the
runner, and Omnigent also ends the runner when the anchor owns a host runner.
The stop is best effort: the anchor's deny-all policy is the primary control,
and the runner stays bound, so the user can start it again. A runner any other
session also uses is left running, since ending it would take that session
down.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from coral.omni.protocols import SessionDispatch
from coral.stores.protocols import RunStore
from omnigent.db.db_models import workspace_scope
from omnigent.stores.conversation_store import ConversationStore

_logger = logging.getLogger(__name__)

# Sessions pinned to the runner read at once: the anchor and at most one other.
_RUNNER_SESSIONS_PAGE = 2


class AnchorRunnerStopper:
    """
    ``DriftPauser``'s ``on_anchor_bound`` hook: stop the anchor's runner, never unbind it.

    :param dispatch: Resolves the engine dispatch at stop time. The dispatch's
        drift pre-send hook holds the pauser that holds this stopper, so it
        cannot be passed in built.
    """

    def __init__(
        self,
        *,
        conversation_store: ConversationStore,
        run_store: RunStore,
        dispatch: Callable[[], SessionDispatch],
    ) -> None:
        self._conversations = conversation_store
        self._run_store = run_store
        self._dispatch = dispatch

    async def __call__(self, workspace_id: int, run_id: str, session_id: str) -> None:
        """
        Stop the runner of anchor ``session_id``, unless it has none or another session uses it.

        :raises CoralSessionError: The dispatch's stop failed; the pauser logs it.
        """
        # Not ``workspace_id``: the debug-log sink reads that as the deployment's workspace.
        extra = {"session_id": session_id, "coral_workspace_id": workspace_id}
        with workspace_scope(workspace_id):
            anchor = await asyncio.to_thread(self._conversations.get_conversation, session_id)
        runner_id = None if anchor is None else anchor.runner_id
        if not runner_id:
            # Deleted, or bound to a host only: there is no runner to stop.
            return
        sharing = await self._other_session_on_runner(workspace_id, session_id, runner_id)
        if sharing is not None:
            _logger.warning(
                "Coral leaves runner %s of run %s's anchor %s running: session %s also uses it",
                runner_id,
                run_id,
                session_id,
                sharing,
                extra=extra,
            )
            return
        run = await asyncio.to_thread(self._run_store.get_run, run_id, workspace_id=workspace_id)
        if run is None:
            _logger.warning(
                "Coral cannot stop runner %s of run %s's anchor %s: the run is gone",
                runner_id,
                run_id,
                session_id,
                extra=extra,
            )
            return
        await self._dispatch().stop(session_id=session_id, user_id=run.user_id)
        _logger.warning(
            "Coral stopped runner %s, which was attached to run %s's anchor %s",
            runner_id,
            run_id,
            session_id,
            extra=extra,
        )

    async def _other_session_on_runner(
        self, workspace_id: int, anchor_id: str, runner_id: str
    ) -> str | None:
        """
        A session other than the anchor pinned to ``runner_id``, archived ones too, else ``None``.

        It reads the index Omnigent's stop walks to carry a runner teardown to its sessions.
        """
        with workspace_scope(workspace_id):
            pinned = await asyncio.to_thread(
                self._conversations.list_runner_session_statuses,
                runner_id,
                limit=_RUNNER_SESSIONS_PAGE,
            )
        return next((pinned_id for pinned_id, _status in pinned if pinned_id != anchor_id), None)


__all__ = ["AnchorRunnerStopper"]
