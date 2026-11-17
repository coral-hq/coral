"""Drift baseline: a run whose anchor or step session the user archived, deleted or bound pauses.

Engine work on a drifted session is refused: the run's anchor archived,
deleted, or given a runner or host (a run anchor never runs), or a step
session archived or deleted. The run then pauses as ``paused(drift,
<cause>)``. The pause is decided from the stored run, not from a command
receipt: a starting or running run pauses with one ``PAUSED`` log entry; a
paused or finished run is left as it is. The entry's identity includes the
run version, so it is unique per pause epoch: a run resumed while the drift
remains pauses again on the next detection, and compare-and-swap keeps
concurrent detectors to one pause. Drift is detected when a step session is
created and, through :class:`DriftPreSendHook`, before each engine message.
After an ``anchor_bound`` pause, :class:`DriftPauser` can also stop the
anchor's runner, best effort.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from coral.db.enum_codecs import RunPauseReason, SessionBindingProgress
from coral.model.ids import anchor_session_id
from coral.omni.protocols import CoralSessionError, PreSendRequest, SessionFacade, SessionState
from coral.recovery.pause import pause_log_checksum, pause_run_once
from coral.stores.protocols import CommitOutcome, RunStore
from coral.stores.session_bindings import SessionBindings

_logger = logging.getLogger(__name__)

DriftCause = Literal[
    "anchor_archived", "anchor_deleted", "anchor_bound", "session_archived", "session_deleted"
]

# The facade's refusal code for each cause; the effect then fails as ``drift.<cause>``.
SESSION_CODES: dict[DriftCause, str] = {
    "anchor_archived": "session.anchor_archived",
    "anchor_deleted": "session.anchor_deleted",
    "anchor_bound": "session.anchor_bound",
    "session_archived": "session.archived",
    "session_deleted": "session.deleted",
}


@dataclass(frozen=True)
class DriftFinding:
    """
    One drifted session.

    :param occurrence: Diagnostic detail: the archive timestamp, ``"deleted"``,
        or the runner or host an anchor was bound to.
    """

    cause: DriftCause
    session_id: str
    occurrence: str

    @property
    def effect_code(self) -> str:
        """The permanent failure code of the effect that found it."""
        return f"drift.{self.cause}"


class DriftDetected(CoralSessionError):
    """A session operation found drift; the caller pauses the run with ``finding``."""

    def __init__(self, finding: DriftFinding) -> None:
        super().__init__(
            SESSION_CODES[finding.cause],
            f"session {finding.session_id} drifted ({finding.cause.replace('_', ' ')})",
        )
        self.finding = finding


def classify_anchor(state: SessionState) -> DriftFinding | None:
    """The anchor's drift, if any: deleted, archived, or bound to a runner or host."""
    if not state.exists:
        return DriftFinding("anchor_deleted", state.session_id, "deleted")
    if state.archived:
        return DriftFinding("anchor_archived", state.session_id, state.archived_at or "archived")
    bound_to = state.runner_id or state.host_id
    if bound_to:
        return DriftFinding("anchor_bound", state.session_id, bound_to)
    return None


def classify_step(state: SessionState) -> DriftFinding | None:
    """A step session's drift, if any: deleted or archived. Its own runner is expected."""
    if not state.exists:
        return DriftFinding("session_deleted", state.session_id, "deleted")
    if state.archived:
        return DriftFinding("session_archived", state.session_id, state.archived_at or "archived")
    return None


async def find_drift(
    facade: SessionFacade,
    bindings: SessionBindings,
    *,
    workspace_id: int,
    run_id: str,
    session_id: str | None,
) -> DriftFinding | None:
    """
    The run's anchor drift, else the target session's, else ``None``.

    Only sessions whose row this run created count: an anchor or step still
    being created has not drifted, and a session bound to another run is not
    this run's.

    :param session_id: The session an engine action targets; ``None`` checks the anchor only.
    """
    anchor = anchor_session_id(workspace_id, run_id)
    targets = [(anchor, classify_anchor)]
    if session_id is not None and session_id != anchor:
        targets.append((session_id, classify_step))
    for target, classify in targets:
        binding = await asyncio.to_thread(bindings.get, workspace_id, target, run_id=run_id)
        if binding is None or binding.progress < SessionBindingProgress.ROW_CREATED:
            continue
        state = await facade.session_state(workspace_id=workspace_id, session_id=target)
        finding = classify(state)
        if finding is not None:
            return finding
    return None


def _drift_checksum_parts(run_id: str, finding: DriftFinding) -> tuple[str, ...]:
    return ("coral-drift", run_id, finding.cause, finding.session_id)


def drift_log_checksum(run_id: str, finding: DriftFinding, run_version: int) -> bytes:
    """The pause entry's identity: one per run, cause, session and pause epoch."""
    return pause_log_checksum(_drift_checksum_parts(run_id, finding), run_version)


def pause_run_for_drift(
    run_store: RunStore,
    *,
    workspace_id: int,
    run_id: str,
    finding: DriftFinding,
    now_us: int,
) -> CommitOutcome:
    """
    Pause a starting or running run for ``finding``; leave a paused or finished run as is.

    A run already paused for another reason records nothing now: the drift is
    found again by the first engine action after it resumes.
    """
    return pause_run_once(
        run_store,
        workspace_id=workspace_id,
        run_id=run_id,
        reason=RunPauseReason.DRIFT,
        body={
            "kind": "pause_run",
            "reason": "drift",
            "cause": finding.cause,
            "session_id": finding.session_id,
            "detail": finding.occurrence,
        },
        checksum_parts=_drift_checksum_parts(run_id, finding),
        now_us=now_us,
    )


def _now_us() -> int:
    return time.time_ns() // 1_000


class DriftPauser:
    """
    Pauses a run for a drift finding, with the store's sync work in a thread.

    :param on_anchor_bound: Awaited with ``(workspace_id, run_id, anchor_id)``
        after each ``anchor_bound`` pause, even when the run was paused already,
        because the anchor's runner may still be live. A failure is logged and
        the pause stands.
    """

    def __init__(
        self,
        run_store: RunStore,
        *,
        now_us: Callable[[], int] = _now_us,
        on_anchor_bound: Callable[[int, str, str], Awaitable[None]] | None = None,
    ) -> None:
        self._run_store = run_store
        self._now_us = now_us
        self._on_anchor_bound = on_anchor_bound

    async def pause(
        self, *, workspace_id: int, run_id: str, finding: DriftFinding
    ) -> CommitOutcome:
        outcome = await asyncio.to_thread(
            pause_run_for_drift,
            self._run_store,
            workspace_id=workspace_id,
            run_id=run_id,
            finding=finding,
            now_us=self._now_us(),
        )
        hook = self._on_anchor_bound
        if finding.cause != "anchor_bound" or hook is None:
            return outcome
        try:
            await hook(workspace_id, run_id, finding.session_id)
        except Exception:
            # Best effort: the run stays paused, and the next detection tries again.
            _logger.warning(
                "Coral paused run %s but could not stop the runner of its anchor %s",
                run_id,
                finding.session_id,
                exc_info=True,
                # Not ``workspace_id``: the debug-log sink reads that as the deployment's.
                extra={"session_id": finding.session_id, "coral_workspace_id": workspace_id},
            )
        return outcome


class DriftPreSendHook:
    """
    Refuses an engine message to a drifted run: its anchor, or the target step, archived,
    deleted or (the anchor) bound. The run pauses first, then the send fails as ``drift.<cause>``.
    """

    def __init__(
        self, facade: SessionFacade, bindings: SessionBindings, pauser: DriftPauser
    ) -> None:
        self._facade = facade
        self._bindings = bindings
        self._pauser = pauser

    async def __call__(self, request: PreSendRequest) -> None:
        """:raises CoralSessionError: Permanent ``drift.<cause>`` after pausing the run."""
        finding = await find_drift(
            self._facade,
            self._bindings,
            workspace_id=request.workspace_id,
            run_id=request.run_id,
            session_id=request.session_id,
        )
        if finding is None:
            return
        await self._pauser.pause(
            workspace_id=request.workspace_id, run_id=request.run_id, finding=finding
        )
        raise CoralSessionError(
            finding.effect_code,
            f"session {finding.session_id} drifted ({finding.cause.replace('_', ' ')}); "
            "the run is paused",
        )


__all__ = [
    "SESSION_CODES",
    "DriftCause",
    "DriftDetected",
    "DriftFinding",
    "DriftPauser",
    "DriftPreSendHook",
    "classify_anchor",
    "classify_step",
    "drift_log_checksum",
    "find_drift",
    "pause_run_for_drift",
]
