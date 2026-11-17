"""Store-only run pauses: a live run pauses once per pause epoch, with one engine ``PAUSED`` entry.

Drift and a session's spend cap pause a run straight through the run store,
without the engine. A starting or running run moves to ``paused(<reason>)``
with one ``PAUSED`` log entry; a paused or finished run is left as it is. The
entry's identity hashes the caller's parts plus the run version, so it is
unique per pause epoch: a run resumed while the cause remains pauses again on
the next detection, and compare-and-swap keeps concurrent callers to one pause.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from coral.db.enum_codecs import ActorKind, LogKind, RunPauseReason, RunStatus
from coral.stores.protocols import (
    CommitOutcome,
    CoralRun,
    LogEntryDraft,
    RunState,
    RunStore,
    Transition,
)
from coral.stores.run_commit import commit_with_retry

_PAUSABLE_STATUSES = frozenset({int(RunStatus.STARTING), int(RunStatus.RUNNING)})


@dataclass(frozen=True)
class PauseResult:
    """
    A store pause's commit and the run's pause reason after it.

    :param pause_reason: The reason this call paused the run for, the stored
        reason of a run that was already paused, or ``None`` for a run that is
        not paused (finished).
    """

    commit: CommitOutcome
    pause_reason: int | None

    @property
    def applied(self) -> bool:
        """Whether this call paused the run."""
        return self.commit.applied


def pause_log_checksum(checksum_parts: Sequence[str], run_version: int) -> bytes:
    """The pause entry's identity: *checksum_parts* in the run version's pause epoch."""
    return hashlib.sha256("\0".join((*checksum_parts, str(run_version))).encode()).digest()


def pause_run_once(
    run_store: RunStore,
    *,
    workspace_id: int,
    run_id: str,
    reason: RunPauseReason,
    body: dict[str, object],
    checksum_parts: Sequence[str],
    now_us: int,
) -> PauseResult:
    """
    Pause a starting or running run for *reason*; leave a paused or finished run as is.

    :param body: The ``PAUSED`` entry's body, stored as sorted JSON.
    :param checksum_parts: What names the cause in the entry's identity; the
        run version is appended.
    :param now_us: The entry's timestamp, in microseconds.
    :returns: The commit (``applied`` is false when the run was not live) and
        the run's pause reason after the call.
    """
    found: list[CoralRun] = []

    def reduce(state: RunState) -> Transition:
        found[:] = [state.run]
        if state.status not in _PAUSABLE_STATUSES:
            return Transition.empty()
        entry = LogEntryDraft(
            kind=int(LogKind.PAUSED),
            actor_kind=int(ActorKind.ENGINE),
            body=json.dumps(body, sort_keys=True),
            idempotency_cksum=pause_log_checksum(checksum_parts, state.version),
            created_at_us=now_us,
        )
        return Transition(status=int(RunStatus.PAUSED), pause_reason=int(reason), logs=(entry,))

    commit = commit_with_retry(
        run_store=run_store,
        workspace_id=workspace_id,
        run_id=run_id,
        reduce_fn=reduce,
        now=now_us // 1_000_000,
    )
    if commit.applied:
        return PauseResult(commit, int(reason))
    # Not applied: the run last read was not live; report its reason if it is paused.
    run = found[-1] if found else None
    if run is None or run.status != int(RunStatus.PAUSED):
        return PauseResult(commit, None)
    return PauseResult(commit, run.pause_reason)


def pause_run_for_session_cap(
    run_store: RunStore,
    *,
    workspace_id: int,
    run_id: str,
    session_id: str,
    spent_usd: float,
    cap_usd: float,
    now_us: int,
) -> PauseResult:
    """
    Pause a live run as ``paused(budget)`` because *session_id* spent its cap.

    ``budget`` is also the engine's activation-cap pause reason; the entry's
    ``"cause": "session_cap"`` tells this pause apart.

    One pause per epoch and session: a run resumed without a raised cap pauses
    again on that session's next denied tool call.
    """
    return pause_run_once(
        run_store,
        workspace_id=workspace_id,
        run_id=run_id,
        reason=RunPauseReason.BUDGET,
        body={
            "kind": "pause_run",
            "reason": "budget",
            "cause": "session_cap",
            "session_id": session_id,
            "spent_usd": spent_usd,
            "cap_usd": cap_usd,
        },
        checksum_parts=("coral-budget", run_id, "session_cap", session_id),
        now_us=now_us,
    )


__all__ = [
    "PauseResult",
    "pause_log_checksum",
    "pause_run_for_session_cap",
    "pause_run_once",
]
