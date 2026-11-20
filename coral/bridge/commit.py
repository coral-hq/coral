"""The one commit path: engine entries and everything they imply as one run-store transition.

The transition carries the entries as ENGINE log rows, the work their effects
queue (transactional outbox), the orchestrator's rows, timer rows for new
armings, the run, slot and gate-visit projections, the alerts they raise and
resolve, and on a return to running the release of held rows and the revival
of exhausted effects.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import get_args

from coral.alerts.rules import commit_alerts
from coral.bridge.codec import entry_draft
from coral.bridge.config import MAX_COMMIT_ROWS, epoch_seconds
from coral.bridge.gate_rows import live_publish_effects, project_gates
from coral.bridge.keys import anchor_effect_key, effect_work_id
from coral.bridge.mapping import (
    FED_KINDS,
    UNMAPPED_KINDS,
    MapContext,
    anchor_create_draft,
    map_effect,
    timer_draft,
)
from coral.bridge.orchestrator import is_decision_reminder, orchestrator_rows, revivable_work_ids
from coral.bridge.projection import RunProjection, project_run, project_slots
from coral.db.enum_codecs import RUN_PAUSE_REASON, RunStatus
from coral.engine import types as engine
from coral.gates.ids import new_gate_elicitation_id
from coral.model.ir import CompiledGraph
from coral.recovery.drift import DriftCause
from coral.stores import protocols as store

_logger = logging.getLogger(__name__)

# Executors refuse with these while a run is paused or drifted; a resume releases them.
DRIFT_EFFECT_CODES = tuple(f"drift.{cause}" for cause in get_args(DriftCause))
RESUME_RELEASE_CODES = ("run.paused", *DRIFT_EFFECT_CODES)


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
    gate_elicitation_ids: Callable[[], str] = new_gate_elicitation_id,
) -> store.Transition:
    """
    The transition that records ``applied`` against ``snapshot``; empty when it changes nothing.

    A commit whose entries are all refused and that changes nothing else is empty.
    A run row paused while its engine ran keeps that pause and its reason, also when the
    engine then pauses, unless ``lift_store_pause``, which only a resume passes. A row
    that shows the engine's own pause follows the engine: a resume, a retry or a plan
    probe that clears it also lifts the row's. The commit that opens the run's first
    decision also names its orchestrator session and queues its create (see
    :mod:`coral.bridge.orchestrator`). Gate-visit rows follow the final state, so
    any commit, an empty resync one too, writes a missing or diverged row. Alerts
    follow those rows, the run row's status and the entries' effects (see
    :mod:`coral.alerts.rules`).

    :param gate_elicitation_ids: Draws the prompt id of a visit row written for the
        first time.

    :raises TransitionTooLarge: when the rows exceed the store's cap after timer
        rows (which the resync adds again) and the orchestrator's re-asks were dropped.
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
    now_s = epoch_seconds(now)
    projected = project_run(run, final, now=now_s)
    row_paused = run.status == int(RunStatus.PAUSED)
    lifted = lift_store_pause and row_paused and final.status == "running"
    # The row shows the engine's pause when its reason is the engine's first cause.
    engine_owned = (
        first.status == "paused"
        and bool(first.causes)
        and run.pause_reason == RUN_PAUSE_REASON[first.causes[0].reason]
    )
    # The row's own pause stands: made while the engine ran, or it is not the pause the
    # engine is leaving now. A row showing another engine cause is repaired instead.
    row_only = (
        row_paused
        and not lifted
        and (first.status != "paused" or (final.status == "running" and not engine_owned))
    )
    if row_only and final.status not in engine.TERMINAL_STATUSES:
        projected = replace(projected, status=None, pause_reason=None, clear_pause_reason=False)
    resumed = not row_only and final.status == "running" and (first.status == "paused" or lifted)
    orchestrator = orchestrator_rows(
        _map_context(snapshot, final, now),
        run,
        first=first,
        effects=(effect for item in accepted for effect in item.entry.effects),
        resumed=resumed,
        run_version=snapshot.version + 1,
    )
    outbox = _dedupe([*_effect_rows(snapshot, accepted, now), *orchestrator.outbox, *extra_outbox])
    # A full commit drops timer rows first (the resync adds them again), then re-asks
    # (each decision already had its request).
    outbox.extend(_fitting(run.id, "orchestrator re-asks", orchestrator.asks, len(outbox)))
    timers = _new_timer_rows(run.id, first, final)
    outbox.extend(_fitting(run.id, "timer rows for the resync", timers, len(outbox)))
    if len(outbox) > MAX_COMMIT_ROWS or len(logs) > MAX_COMMIT_ROWS:
        raise store.TransitionTooLarge(
            f"run {run.id} commit has {len(logs)} log rows and {len(outbox)} work rows"
        )
    release = tuple(
        dict.fromkeys((*(RESUME_RELEASE_CODES if resumed else ()), *release_held_codes))
    )
    gate_visits = project_gates(
        run,
        final,
        snapshot.store.gate_visits,
        workspace_id=run.workspace_id,
        now=now_s,
        new_elicitation_id=gate_elicitation_ids,
    )
    alerts = commit_alerts(
        run,
        snapshot.graph,
        first=first,
        final=final,
        effects=(effect for item in accepted for effect in item.entry.effects),
        loaded_gates=snapshot.store.gate_visits,
        gate_drafts=gate_visits,
        status=run.status if projected.status is None else projected.status,
        pause_reason=_pause_reason_after(run, projected),
    )
    changes = store.Transition(
        status=projected.status,
        pause_reason=projected.pause_reason,
        clear_pause_reason=projected.clear_pause_reason,
        orchestrator_session_id=orchestrator.session_id,
        activation_count_delta=projected.activation_count_delta,
        finished_at=projected.finished_at,
        agent_slots=project_slots(run.id, final, snapshot.store.agent_slots, now=now_s),
        gate_visits=gate_visits,
        alert_raises=alerts.raises,
        alert_resolutions=alerts.resolutions,
        logs=tuple(extra_logs),
        outbox_work=tuple(outbox),
        tool_reply=tool_reply,
        revive_work_ids=_revivable(run, final) if resumed else (),
        release_held_codes=release,
    )
    if not accepted and changes.is_empty:
        return store.Transition.empty()
    return replace(changes, logs=tuple(logs))


def _pause_reason_after(run: store.CoralRun, projected: RunProjection) -> int | None:
    """The run row's pause reason once the commit's projection is written."""
    if projected.pause_reason is not None:
        return projected.pause_reason
    return None if projected.clear_pause_reason else run.pause_reason


def _effect_rows(
    snapshot: EngineSnapshot, accepted: Sequence[Applied], now: datetime
) -> list[store.WorkItemDraft]:
    run = snapshot.store.run
    rows: list[store.WorkItemDraft] = []
    for item in accepted:
        ctx = _map_context(snapshot, item.after, now)
        if isinstance(item.entry.input, engine.StartRun):
            rows.append(anchor_create_draft(ctx))
        for effect in item.entry.effects:
            draft = map_effect(ctx, effect)
            if draft is not None:
                rows.append(draft)
                continue
            if is_decision_reminder(item.after, effect):
                # The orchestrator's rules queue it as a reminder.
                continue
            _logger.info(
                "Coral run %s committed %s effect %s without work: %s",
                run.id,
                effect.kind,
                effect.effect_key,
                UNMAPPED_KINDS.get(effect.kind, "no executor handles it"),
            )
    return rows


def _fitting(
    run_id: str, what: str, rows: Sequence[store.WorkItemDraft], used: int
) -> Sequence[store.WorkItemDraft]:
    """The leading ``rows`` that still fit beside ``used`` rows; the rest are logged."""
    room = max(MAX_COMMIT_ROWS - used, 0)
    if len(rows) > room:
        _logger.info(
            "Coral run %s defers %d %s: the commit is full", run_id, len(rows) - room, what
        )
    return rows[:room]


def _map_context(snapshot: EngineSnapshot, state: engine.RunState, now: datetime) -> MapContext:
    run = snapshot.store.run
    return MapContext(
        workspace_id=run.workspace_id,
        run_id=run.id,
        graph=snapshot.graph,
        state=state,
        request_preview=snapshot.store.spec.request_preview,
        title=run.title,
        now=now,
    )


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


def _revivable(run: store.CoralRun, state: engine.RunState) -> tuple[str, ...]:
    """
    Rows a resume may revive: unreceipted fed effects', the anchor's, the orchestrator's
    and the publishes of live gate visits.
    """
    receipted = {receipt.key for receipt in state.receipts}
    keys = [
        effect.effect_key
        for effect in state.effects
        if effect.kind in FED_KINDS and effect.effect_key not in receipted
    ]
    keys.append(anchor_effect_key(run.id))
    keys.extend(effect.effect_key for effect in live_publish_effects(state))
    ids = (effect_work_id(run.id, key) for key in keys)
    return tuple(dict.fromkeys((*ids, *revivable_work_ids(run, state))))


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
