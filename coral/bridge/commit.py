"""The one commit path: engine entries and everything they imply as one run-store transition.

The transition carries the entries as ENGINE log rows, the work their effects
queue (transactional outbox), timer rows for new armings, the run and slot
projections, and on a return to running the release of held rows and the
revival of exhausted effects.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import get_args

from coral.bridge.codec import entry_draft
from coral.bridge.config import MAX_COMMIT_ROWS, epoch_seconds
from coral.bridge.keys import anchor_effect_key, effect_work_id
from coral.bridge.mapping import (
    FED_KINDS,
    UNMAPPED_KINDS,
    MapContext,
    anchor_create_draft,
    map_effect,
    timer_draft,
)
from coral.bridge.projection import project_run, project_slots
from coral.db.enum_codecs import RunStatus
from coral.engine import types as engine
from coral.model.ir import CompiledGraph
from coral.recovery.drift import DriftCause
from coral.stores import protocols as store

_logger = logging.getLogger(__name__)

# Executors refuse with these while a run is paused or drifted; a resume releases them.
DRIFT_EFFECT_CODES = tuple(f"drift.{cause}" for cause in get_args(DriftCause))
RESUME_RELEASE_CODES = ("run.paused", *DRIFT_EFFECT_CODES)
_SETTLED = frozenset({"paused", *engine.TERMINAL_STATUSES})


@dataclass(frozen=True)
class EngineSnapshot:
    """A run as loaded: its rows, pinned graph, frozen config and the folded engine state."""

    store: store.RunState
    graph: CompiledGraph
    config: engine.EngineConfig
    state: engine.RunState
    last_engine_seq: int

    @property
    def version(self) -> int:
        return self.store.version


@dataclass(frozen=True)
class Applied:
    """One input's log entry with the engine state before and after it."""

    entry: engine.LogEntry
    before: engine.RunState
    after: engine.RunState

    @property
    def accepted(self) -> bool:
        return (
            self.entry.rejection is None
            and self.after is not self.before
            and (self.after != self.before)
        )

    @property
    def stored(self) -> bool:
        """Refused entries are kept for audit; an entry that changed nothing is not."""
        return self.entry.rejection is not None or self.accepted


@dataclass(frozen=True)
class CommitExtras:
    """Rows a caller adds to an engine commit."""

    logs: Sequence[store.LogEntryDraft] = ()
    outbox: Sequence[store.WorkItemDraft] = ()
    tool_reply: store.ToolReplyDraft | None = None
    release_held_codes: Sequence[str] = ()


def build_commit(
    snapshot: EngineSnapshot,
    applied: Sequence[Applied],
    *,
    now: datetime,
    actor: str | None = None,
    extra_logs: Sequence[store.LogEntryDraft] = (),
    extra_outbox: Sequence[store.WorkItemDraft] = (),
    tool_reply: store.ToolReplyDraft | None = None,
    release_held_codes: Sequence[str] = (),
    lift_store_pause: bool = False,
) -> store.Transition:
    """
    The transition that records ``applied`` against ``snapshot``; empty when it changes nothing.

    A commit whose entries are all refused and that changes nothing else is empty.
    A run row paused outside the engine (its engine state runs) keeps that pause
    unless ``lift_store_pause``, which only a resume passes.

    :raises TransitionTooLarge: when the rows exceed the store's cap after timer
        rows, which the resync adds again, were dropped.
    :raises UnsupportedStance: for a create whose profile has no step stance.
    """
    run = snapshot.store.run
    first = applied[0].before if applied else snapshot.state
    final = applied[-1].after if applied else snapshot.state
    stored = [item for item in applied if item.stored]
    accepted = [item for item in stored if item.entry.rejection is None]
    logs = [
        *(
            entry_draft(item.entry, run_id=run.id, before=item.before, actor=actor)
            for item in stored
        ),
        *extra_logs,
    ]
    outbox = _dedupe([*_effect_rows(snapshot, accepted, now), *extra_outbox])
    timers = _new_timer_rows(run.id, first, final)
    room = MAX_COMMIT_ROWS - len(outbox)
    if len(timers) > room:
        _logger.info(
            "Coral run %s defers %d timer rows to its resync: the commit is full",
            run.id,
            len(timers) - max(room, 0),
        )
        timers = timers[: max(room, 0)]
    outbox.extend(timers)
    if len(outbox) > MAX_COMMIT_ROWS or len(logs) > MAX_COMMIT_ROWS:
        raise store.TransitionTooLarge(
            f"run {run.id} commit has {len(logs)} log rows and {len(outbox)} work rows"
        )

    now_s = epoch_seconds(now)
    projected = project_run(run, final, now=now_s)
    lifted = lift_store_pause and run.status == int(RunStatus.PAUSED) and final.status == "running"
    if run.status == int(RunStatus.PAUSED) and final.status not in _SETTLED and not lifted:
        # Paused by the store only: the engine runs, but the row stays paused.
        projected = replace(projected, status=None, pause_reason=None, clear_pause_reason=False)
    resumed = (first.status == "paused" and final.status == "running") or lifted
    release = tuple(
        dict.fromkeys((*(RESUME_RELEASE_CODES if resumed else ()), *release_held_codes))
    )
    changes = store.Transition(
        status=projected.status,
        pause_reason=projected.pause_reason,
        clear_pause_reason=projected.clear_pause_reason,
        activation_count_delta=projected.activation_count_delta,
        finished_at=projected.finished_at,
        agent_slots=project_slots(run.id, final, snapshot.store.agent_slots, now=now_s),
        logs=tuple(extra_logs),
        outbox_work=tuple(outbox),
        tool_reply=tool_reply,
        revive_work_ids=_revivable(run.id, final) if resumed else (),
        release_held_codes=release,
    )
    if not accepted and changes.is_empty:
        return store.Transition.empty()
    return replace(changes, logs=tuple(logs))


def _effect_rows(
    snapshot: EngineSnapshot, accepted: Sequence[Applied], now: datetime
) -> list[store.WorkItemDraft]:
    run = snapshot.store.run
    rows: list[store.WorkItemDraft] = []
    for item in accepted:
        ctx = MapContext(
            workspace_id=run.workspace_id,
            run_id=run.id,
            graph=snapshot.graph,
            state=item.after,
            request_preview=snapshot.store.spec.request_preview,
            title=run.title,
            now=now,
        )
        if isinstance(item.entry.input, engine.StartRun):
            rows.append(anchor_create_draft(ctx))
        for effect in item.entry.effects:
            draft = map_effect(ctx, effect)
            if draft is not None:
                rows.append(draft)
                continue
            _logger.info(
                "Coral run %s committed %s effect %s without work: %s",
                run.id,
                effect.kind,
                effect.effect_key,
                UNMAPPED_KINDS.get(effect.kind, "no executor handles it"),
            )
    return rows


def _new_timer_rows(
    run_id: str, first: engine.RunState, final: engine.RunState
) -> list[store.WorkItemDraft]:
    """A row for each arming the commit made, earliest due first."""
    known = {(timer.key, timer.generation, timer.due_at) for timer in first.timers}
    armed = sorted(
        (
            timer
            for timer in final.timers
            if (timer.key, timer.generation, timer.due_at) not in known
        ),
        key=lambda timer: (timer.due_at, timer.key),
    )
    return [timer_draft(run_id, timer) for timer in armed]


def _revivable(run_id: str, state: engine.RunState) -> tuple[str, ...]:
    """Rows a resume may revive: every unreceipted fed effect's, and the anchor's."""
    receipted = {receipt.key for receipt in state.receipts}
    keys = [
        effect.effect_key
        for effect in state.effects
        if effect.kind in FED_KINDS and effect.effect_key not in receipted
    ]
    keys.append(anchor_effect_key(run_id))
    return tuple(dict.fromkeys(effect_work_id(run_id, key) for key in keys))


def _dedupe(rows: Sequence[store.WorkItemDraft]) -> list[store.WorkItemDraft]:
    seen: set[str] = set()
    kept: list[store.WorkItemDraft] = []
    for row in rows:
        if row.id not in seen:
            seen.add(row.id)
            kept.append(row)
    return kept


__all__ = [
    "DRIFT_EFFECT_CODES",
    "RESUME_RELEASE_CODES",
    "Applied",
    "CommitExtras",
    "EngineSnapshot",
    "build_commit",
]
