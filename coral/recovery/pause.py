"""Store-only run pauses: a live run pauses once per pause epoch, with one engine ``PAUSED`` entry.

Drift pauses a run straight through the run store, without the engine. A
starting or running run moves to ``paused(<reason>)`` with one ``PAUSED`` log
entry; a paused or finished run is left as it is. The entry's identity hashes
the caller's parts plus the run version, so it is unique per pause epoch: a run
resumed while the cause remains pauses again on the next detection, and
compare-and-swap keeps concurrent callers to one pause.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from coral.db.enum_codecs import ActorKind, LogKind, RunPauseReason, RunStatus
from coral.stores.protocols import CommitOutcome, LogEntryDraft, RunState, RunStore, Transition
from coral.stores.run_commit import commit_with_retry

_PAUSABLE_STATUSES = frozenset({int(RunStatus.STARTING), int(RunStatus.RUNNING)})


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
) -> CommitOutcome:
    """
    Pause a starting or running run for *reason*; leave a paused or finished run as is.

    :param body: The ``PAUSED`` entry's body, stored as sorted JSON.
    :param checksum_parts: What names the cause in the entry's identity; the
        run version is appended.
    :param now_us: The entry's timestamp, in microseconds.
    :returns: The commit; ``applied`` is false when the run was not live.
    """

    def reduce(state: RunState) -> Transition:
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

    return commit_with_retry(
        run_store=run_store,
        workspace_id=workspace_id,
        run_id=run_id,
        reduce_fn=reduce,
        now=now_us // 1_000_000,
    )


__all__ = [
    "pause_log_checksum",
    "pause_run_once",
]
