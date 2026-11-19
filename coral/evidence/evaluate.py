"""The pure done-when evaluator: each required command's last run passed after the last change.

One session's observations are walked in ``obs_seq`` order. A *change* is:

- a write or edit (its path is named);
- a shell run whose L1 after it is unknown, or differs from the last known L1;
- a submit-time L1 that differs from the last known L1.

A change made by a run that is only a ``may_modify`` command is a check change and is
ignored. A change found at a shell run is placed at that run, so the run itself predates
it: a test that rewrites tracked files must be ``may_modify``. A write or edit leaves the
L1 unknown, so the next shell run starts from its own L1 instead of reporting the write
again. An item passes when its latest matching run after the last change exited 0.
"""

from __future__ import annotations

from collections.abc import Iterable

from coral.evidence.ir import (
    CommandObservation,
    EvidenceRequirement,
    EvidenceVerdict,
    InProgress,
    Missing,
    MissingItem,
    Pass,
    RequiredCommand,
)
from coral.evidence.match import argv_matches, segments


def evaluate(
    requirement: EvidenceRequirement,
    observations: Iterable[CommandObservation],
    *,
    submit_l1: str | None,
    in_progress: str | None = None,
) -> EvidenceVerdict:
    """
    Judge one session's observations against ``requirement`` at submit.

    :param submit_l1: The worktree's L1 at submit; ``None`` when it could not be read.
    :param in_progress: Why capture may still lag (calls in flight, a failed record);
        ``None`` when every earlier call is recorded.
    """
    if in_progress is not None:
        return InProgress(reason=in_progress)
    if submit_l1 is None:
        return InProgress(reason="the workspace fingerprint at submit is not available yet")
    ordered = _unique_in_order(observations)
    runs: dict[str, list[tuple[int, CommandObservation]]] = {
        item.item_id: [] for item in requirement.items
    }
    known_l1: str | None = None
    last_change: tuple[int, str | None] | None = None
    for index, obs in enumerate(ordered):
        if obs.tool in ("write", "edit"):
            last_change = (index, obs.changed_path)
            known_l1 = None
            continue
        command = obs.command or ""
        matched, whole_line = _matched(requirement.items, command)
        for item in matched:
            runs[item.item_id].append((index, obs))
        changed = obs.l1_after is None or (known_l1 is not None and obs.l1_after != known_l1)
        known_l1 = obs.l1_after
        check_change = whole_line and all(item.may_modify for item in matched)
        if changed and not check_change:
            last_change = (index, None)
    if known_l1 is not None and submit_l1 != known_l1:
        last_change = (len(ordered), None)
    missing = tuple(
        found
        for found in (_judge(item, runs[item.item_id], last_change) for item in requirement.items)
        if found is not None
    )
    return Missing(items=missing) if missing else Pass()


def _matched(
    items: tuple[RequiredCommand, ...], command: str
) -> tuple[list[RequiredCommand], bool]:
    """
    The items a line ran, and whether the line is nothing but them.

    In an ``&&`` chain that exits 0 every command passed, but a command after a test
    could undo what the test saw, so only the trailing run of required commands counts.
    """
    found = segments(command)
    matched: list[RequiredCommand] = []
    count = 0
    for segment in reversed(found):
        hits = [
            item
            for item in items
            if argv_matches(item.run, segment.argv, allow_args=item.allow_args)
        ]
        if not hits:
            break
        matched.extend(item for item in hits if item not in matched)
        count += 1
    return matched, bool(found) and count == len(found)


def _judge(
    item: RequiredCommand,
    item_runs: list[tuple[int, CommandObservation]],
    last_change: tuple[int, str | None] | None,
) -> MissingItem | None:
    if not item_runs:
        return MissingItem(item_id=item.item_id, run=item.run, reason="never_ran")
    after = [obs for index, obs in item_runs if last_change is None or index > last_change[0]]
    if not after and last_change is not None:
        last_index, last_obs = item_runs[-1]
        if last_index == last_change[0] and last_obs.l1_after is None:
            # The run is the last change only because the tree could not be read after it.
            return MissingItem(item_id=item.item_id, run=item.run, reason="unverified")
    if not after:
        path = last_change[1] if last_change is not None else None
        return MissingItem(
            item_id=item.item_id, run=item.run, reason="predates_change", changed_path=path
        )
    latest = after[-1]
    if latest.timed_out or latest.exit_code is None:
        return MissingItem(item_id=item.item_id, run=item.run, reason="exit_unknown")
    if latest.exit_code != 0:
        return MissingItem(item_id=item.item_id, run=item.run, reason="failed")
    return None


def _unique_in_order(observations: Iterable[CommandObservation]) -> list[CommandObservation]:
    """Each op_key once (its first record), ordered by ``obs_seq`` then ``op_key``."""
    seen: dict[str, CommandObservation] = {}
    for obs in observations:
        seen.setdefault(obs.op_key, obs)
    return sorted(seen.values(), key=lambda obs: (obs.obs_seq, obs.op_key))


__all__ = ["evaluate"]
