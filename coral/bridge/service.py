"""``EngineBridge``: commits engine inputs for runs, feeds work outcomes back, repairs runs.

Every write goes through ``commit_inputs``: load the run, apply the inputs to its
folded engine state, build one transition and apply it under compare-and-swap.
A run that cannot be loaded, or whose commit cannot be built, is paused visibly
instead of being retried.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import zstandard
from pydantic import ValidationError

from coral.bridge.bound_sessions import BoundSessions, created_session
from coral.bridge.codec import EngineLogDecodeError, decode_entries
from coral.bridge.commit import (
    RESUME_RELEASE_CODES,
    Applied,
    CommitExtras,
    EngineSnapshot,
    build_commit,
)
from coral.bridge.config import (
    FEED_BATCH,
    FOLD_CACHE_BYTES,
    FOLD_CACHE_RUNS,
    LOCK_TIMEOUT_S,
    MAX_RUN_ACTIVATIONS,
    PAUSED_RESYNC_DELAY_S,
    FrozenConfigMissing,
    ceil_epoch_seconds,
    engine_config_for,
    epoch_seconds,
    epoch_us,
    utc_now,
)
from coral.bridge.feedback import decision_of, feedback_input, finished_from_row
from coral.bridge.fold import EngineStateCache
from coral.bridge.graphs import PinnedGraphError, PinnedGraphs
from coral.bridge.keys import (
    ORCHESTRATOR_GENERATION,
    ORCHESTRATOR_SLOT_ID,
    anchor_effect_key,
    effect_work_id,
    slot_session_id,
)
from coral.bridge.mapping import (
    FED_KINDS,
    MapContext,
    MappedPayloadTooLarge,
    UnsupportedStance,
    anchor_create_draft,
    map_effect,
    regather_key,
    resync_draft,
    timer_draft,
    turn_signal_draft,
)
from coral.bridge.orchestrator import open_decisions, regather_session, repair_drafts
from coral.db.enum_codecs import ActorKind, LogKind, RunPauseReason, RunStatus, WorkStatus
from coral.engine import transition
from coral.engine import types as engine
from coral.engine.facts import TurnFact
from coral.engine.reconcile import awaiting_effect, reconcile
from coral.queue.drainer import FinishedWork
from coral.queue.run_effects import describe_exception
from coral.recovery.pause import pause_log_checksum, pause_run_once
from coral.stores.protocols import (
    UNFINISHED_RUN_STATUSES,
    CommitOutcome,
    CoralRun,
    LogEntryDraft,
    QueueStore,
    RunContended,
    RunNotFound,
    RunState,
    RunStore,
    Transition,
    TransitionTooLarge,
    WorkItem,
    WorkItemDraft,
)
from coral.stores.run_commit import commit_with_retry
from coral.stores.workflow_versions import SqlAlchemyWorkflowVersionStore

_logger = logging.getLogger(__name__)

# A run whose rows, pinned graph, frozen config or log cannot be read or decoded. Any
# other error (a reducer defect while folding, say) is raised as is, not filed as an
# unloadable run, which nothing can resume or cancel.
_LOAD_ERRORS = (
    PinnedGraphError,
    FrozenConfigMissing,
    EngineLogDecodeError,
    zstandard.ZstdError,
    ValidationError,
    json.JSONDecodeError,
)
# Stored text that does not decode while the run's rows load.
_STORED_TEXT_ERRORS = (zstandard.ZstdError, UnicodeDecodeError)
# Commits that fail the same way every time: the run pauses with this detail instead.
_UNBUILDABLE: tuple[tuple[type[Exception], str], ...] = (
    (TransitionTooLarge, "transition_too_large"),
    (UnsupportedStance, "unsupported_stance"),
    (MappedPayloadTooLarge, "payload_too_large"),
)
UNBUILDABLE_ERRORS = tuple(kind for kind, _detail in _UNBUILDABLE)
LOAD_FAILED_DETAIL = "engine.load_failed"
# Rows read at a time while looking for a run's start entry.
_START_SCAN_ROWS = 8

Inputs = Callable[[EngineSnapshot], Sequence[engine.Input]]
Extras = Callable[[EngineSnapshot, Sequence[Applied]], CommitExtras]
# ``applied``: the fact's inputs were committed; ``awaiting_effect``: its slot waits on
# a leased effect, so nothing was written; ``no_input``: the fact changes nothing.
TurnFactResult = Literal["applied", "awaiting_effect", "no_input"]


class RunNotRunnable(ValueError):
    """A start or a command refused before anything was written; ``code`` names the rule."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"[{code}] {message}")


class EngineLoadFailed(RuntimeError):
    """A run's engine state cannot be loaded; the run is paused ``failure_path`` once."""

    def __init__(self, workspace_id: int, run_id: str, cause: BaseException) -> None:
        self.workspace_id = workspace_id
        self.run_id = run_id
        super().__init__(
            f"the engine state of run {run_id} cannot be loaded ({type(cause).__name__})"
        )


@dataclass(frozen=True)
class BridgeCommit:
    """
    A commit's outcome and every entry its inputs produced, refused ones included.

    :param unbuildable: Set when the inputs could not be committed: the detail the run
        was paused ``failure_path`` with instead.
    """

    outcome: CommitOutcome
    entries: tuple[engine.LogEntry, ...]
    unbuildable: str | None = None


@dataclass(frozen=True)
class _Fed:
    """
    An outcome to feed, and whether it reports a failure of its row.

    :param decision_id: For a message to the orchestrator, the decision it is about.
    """

    work_id: str
    failed: bool
    command: engine.Input
    decision_id: str | None = None


@dataclass(frozen=True)
class ResyncReport:
    """What one level-triggered repair of a run did."""

    started: bool = False
    fed: int = 0
    enqueued: int = 0
    timers: int = 0
    released: bool = False
    repaired: bool = False
    regathered: int = 0


class EngineBridge:
    """Commits engine inputs for runs. Authorizes nothing: callers check the actor.

    Every method is synchronous; async callers run it on a dedicated thread pool.
    """

    def __init__(
        self,
        *,
        run_store: RunStore,
        queue_store: QueueStore,
        versions: SqlAlchemyWorkflowVersionStore,
        clock: Callable[[], datetime] = utc_now,
        fold_cache_size: int = FOLD_CACHE_RUNS,
        fold_cache_bytes: int = FOLD_CACHE_BYTES,
        bound_sessions: BoundSessions | None = None,
    ) -> None:
        """
        :param bound_sessions: The status-edge recorder's index; each completed create's
            session is pushed into it.
        """
        self._runs = run_store
        self._queue = queue_store
        self._versions = versions
        self._clock = clock
        self._bound = bound_sessions
        self._graphs = PinnedGraphs(versions, max_entries=fold_cache_size)
        self._states = EngineStateCache(
            run_store, max_runs=fold_cache_size, max_bytes=fold_cache_bytes
        )
        self._start_hashes: OrderedDict[tuple[int, str], str] = OrderedDict()
        self._max_start_hashes = fold_cache_size
        self._lock = threading.Lock()

    @property
    def run_store(self) -> RunStore:
        return self._runs

    @property
    def versions(self) -> SqlAlchemyWorkflowVersionStore:
        return self._versions

    @property
    def bound_sessions(self) -> BoundSessions | None:
        return self._bound

    def now(self) -> datetime:
        return self._clock()

    def start_input(self, snapshot: EngineSnapshot) -> engine.StartRun:
        """The run's one ``StartRun``, derived from what its rows store."""
        run_id = snapshot.store.run_id
        # The run id derives from the caller's start key, so it is as idempotent a key.
        return engine.StartRun(
            run_id=run_id, start_key=run_id, version_hash=snapshot.graph.content_hash
        )

    # ── loading ──────────────────────────────────────────────────────────────

    def load(self, *, workspace_id: int, run_id: str) -> EngineSnapshot:
        """
        The run's rows, pinned graph, frozen config and engine state at one version.

        :raises RunNotFound: when the workspace has no such run.
        :raises EngineLoadFailed: when the run cannot be loaded; it is paused once.
        """
        try:
            return self._snapshot(self._load_rows(workspace_id, run_id))
        except EngineLoadFailed as exc:
            self._pause_unloadable(exc)
            raise

    def _load_rows(self, workspace_id: int, run_id: str) -> RunState:
        try:
            state, _version = self._runs.load_run_state(run_id, workspace_id=workspace_id)
        except _STORED_TEXT_ERRORS as exc:
            raise EngineLoadFailed(workspace_id, run_id, exc) from exc
        return state

    def _snapshot(self, rows: RunState) -> EngineSnapshot:
        workspace_id, run_id = rows.workspace_id, rows.run_id
        try:
            config = engine_config_for(rows.spec)
            graph = self._graphs.load(
                workspace_id=workspace_id,
                version_id=rows.run.version_id,
                expected_hash=self._start_hash(workspace_id, run_id, rows.version),
            )
            folded = self._states.fold(
                workspace_id=workspace_id,
                run_id=run_id,
                version=rows.version,
                graph=graph,
                config=config,
            )
        except RunNotFound:
            raise
        except _LOAD_ERRORS as exc:
            raise EngineLoadFailed(workspace_id, run_id, exc) from exc
        return EngineSnapshot(
            store=rows,
            graph=graph,
            config=config,
            state=folded.state,
            last_engine_seq=folded.last_seq,
        )

    def _start_hash(self, workspace_id: int, run_id: str, version: int) -> str | None:
        """The graph hash the run's ``StartRun`` named; ``None`` before the engine starts."""
        key = (workspace_id, run_id)
        with self._lock:
            known = self._start_hashes.get(key)
            if known is not None:
                self._start_hashes.move_to_end(key)
                return known
        after_seq = 0
        while True:
            rows = self._runs.read_engine_log(
                run_id,
                workspace_id=workspace_id,
                after_seq=after_seq,
                max_run_version=version,
                limit=_START_SCAN_ROWS,
            )
            entries = decode_entries(rows)
            if entries:
                first = entries[0].input
                if not isinstance(first, engine.StartRun):
                    raise EngineLogDecodeError(f"the engine log of run {run_id} has no start")
                with self._lock:
                    self._start_hashes[key] = first.version_hash
                    while len(self._start_hashes) > self._max_start_hashes:
                        self._start_hashes.popitem(last=False)
                return first.version_hash
            if len(rows) < _START_SCAN_ROWS:
                return None
            after_seq = rows[-1].seq

    # ── committing ───────────────────────────────────────────────────────────

    def commit_inputs(
        self,
        *,
        workspace_id: int,
        run_id: str,
        inputs: Inputs,
        actor: str | None = None,
        extra: Extras | None = None,
        lift_store_pause: bool = False,
    ) -> BridgeCommit:
        """
        Apply ``inputs`` (computed from the loaded run) and commit them as one transition.

        A refused input is skipped and the next sees the state unchanged; a result that
        changes nothing is not written. A commit that cannot be built pauses the run
        ``failure_path`` in a separate commit instead, which the result's
        ``unbuildable`` names.

        :param actor: Who asked: a user id, the calling session, or ``None`` for the engine.
        :raises EngineLoadFailed: when the run cannot be loaded; it is paused once.
        :raises RunContended: when other commits kept winning.
        """
        try:
            return self._commit_inputs(
                workspace_id, run_id, inputs, actor, extra, lift_store_pause
            )
        except EngineLoadFailed as exc:
            self._pause_unloadable(exc)
            raise
        except UNBUILDABLE_ERRORS as exc:
            return self.pause_unbuildable(workspace_id=workspace_id, run_id=run_id, error=exc)

    def pause_unbuildable(
        self, *, workspace_id: int, run_id: str, error: Exception
    ) -> BridgeCommit:
        """
        Pause the run ``failure_path`` because ``error`` keeps its commit from being built.

        :param error: One of :data:`UNBUILDABLE_ERRORS`; its kind names the pause detail.
        """
        _logger.warning(
            "Coral pauses run %s: its commit cannot be built (%s)",
            run_id,
            describe_exception(error),
        )
        detail = _unbuildable_detail(error)
        paused = self._pause_visibly(workspace_id, run_id, detail)
        return dataclasses.replace(paused, unbuildable=detail)

    def _commit_inputs(
        self,
        workspace_id: int,
        run_id: str,
        inputs: Inputs,
        actor: str | None,
        extra: Extras | None,
        lift_store_pause: bool,
    ) -> BridgeCommit:
        now = self._clock()
        latest: list[tuple[Applied, ...]] = [()]

        def reduce(rows: RunState) -> Transition:
            snapshot = self._snapshot(rows)
            applied = self._apply(snapshot, inputs(snapshot), now)
            latest[0] = applied
            extras = extra(snapshot, applied) if extra is not None else CommitExtras()
            try:
                return build_commit(
                    snapshot,
                    applied,
                    now=now,
                    actor=actor,
                    extra_logs=extras.logs,
                    extra_outbox=extras.outbox,
                    tool_reply=extras.tool_reply,
                    release_held_codes=extras.release_held_codes,
                    lift_store_pause=lift_store_pause,
                )
            except UNBUILDABLE_ERRORS:
                _logger.warning(
                    "Coral run %s cannot commit inputs %s",
                    run_id,
                    [item.entry.input.kind for item in applied],
                )
                raise

        try:
            outcome = commit_with_retry(
                run_store=self._runs,
                workspace_id=workspace_id,
                run_id=run_id,
                reduce_fn=reduce,
                now=epoch_seconds(now),
                lock_timeout_s=LOCK_TIMEOUT_S,
            )
        except _STORED_TEXT_ERRORS as exc:
            raise EngineLoadFailed(workspace_id, run_id, exc) from exc
        return BridgeCommit(outcome=outcome, entries=tuple(item.entry for item in latest[0]))

    def _apply(
        self, snapshot: EngineSnapshot, inputs: Sequence[engine.Input], now: datetime
    ) -> tuple[Applied, ...]:
        state = snapshot.state
        applied: list[Applied] = []
        for command in inputs:
            result = transition(snapshot.graph, state, command, now, snapshot.config)
            if result.entry.rejection is not None:
                _logger.debug(
                    "Coral run %s refused %s: %s",
                    snapshot.store.run_id,
                    command.kind,
                    result.entry.rejection.code,
                )
            applied.append(Applied(entry=result.entry, before=state, after=result.state))
            state = result.state
        return tuple(applied)

    def _pause_visibly(self, workspace_id: int, run_id: str, detail: str) -> BridgeCommit:
        """Pause ``failure_path`` through the engine, or on the row when it has not started."""
        commit = self._commit_inputs(
            workspace_id,
            run_id,
            lambda _snapshot: (engine.PauseRun(reason="failure_path", detail=detail),),
            None,
            None,
            False,
        )
        if commit.outcome.applied:
            return commit
        outcome = self._pause_row(workspace_id, run_id, detail)
        return BridgeCommit(outcome=outcome, entries=commit.entries)

    def _pause_unloadable(self, failure: EngineLoadFailed) -> None:
        """Pause the run on its row alone; once paused, later failures only warn."""
        cause = describe_exception(failure.__cause__ or failure)
        try:
            outcome = self._pause_row(failure.workspace_id, failure.run_id, LOAD_FAILED_DETAIL)
        except Exception as exc:  # noqa: BLE001 -- the load failure is raised to the caller
            _logger.error(
                "Coral cannot load run %s (%s) and could not pause it: %s",
                failure.run_id,
                cause,
                describe_exception(exc),
            )
            return
        if outcome.applied:
            _logger.error("Coral paused run %s: %s (%s)", failure.run_id, failure, cause)
        else:
            _logger.warning("Coral still cannot load run %s (%s)", failure.run_id, cause)

    def _pause_row(self, workspace_id: int, run_id: str, detail: str) -> CommitOutcome:
        """A store-only pause of a starting or running run, once per pause epoch."""
        return pause_run_once(
            self._runs,
            workspace_id=workspace_id,
            run_id=run_id,
            reason=RunPauseReason.FAILURE_PATH,
            body={"kind": "pause_run", "reason": "failure_path", "detail": detail},
            checksum_parts=("coral-bridge-pause", run_id, detail),
            now_us=epoch_us(self._clock()),
            lock_timeout_s=LOCK_TIMEOUT_S,
        )

    # ── commands ─────────────────────────────────────────────────────────────

    def _start_first(self, snapshot: EngineSnapshot) -> tuple[engine.Input, ...]:
        return (self.start_input(snapshot),) if snapshot.state.status is None else ()

    def resume_run(
        self, *, workspace_id: int, run_id: str, actor: str | None, cap: int | None = None
    ) -> BridgeCommit:
        """
        Resume the run, also from a pause made on its row alone.

        The commit that returns it to running releases held items, revives exhausted
        effects and re-prompts failed and stopped slots.

        :param cap: A new activation cap for a run paused at its cap.
        :raises RunNotRunnable: for a cap outside the bounds a start accepts.
        """
        if cap is not None and not 1 <= cap <= MAX_RUN_ACTIVATIONS:
            raise RunNotRunnable("run.field_invalid", f"cap must be 1-{MAX_RUN_ACTIVATIONS}")
        return self.commit_inputs(
            workspace_id=workspace_id,
            run_id=run_id,
            inputs=lambda snapshot: (*self._start_first(snapshot), engine.ResumeRun(cap=cap)),
            actor=actor,
            lift_store_pause=True,
        )

    def cancel_run(self, *, workspace_id: int, run_id: str, actor: str | None) -> BridgeCommit:
        """
        Cancel the run; its live slots' sessions are cancelled by the derived session id.

        A run whose engine has not started commits its start alone first, so neither
        commit carries both the creates and the cancels of a wide first step.
        """
        self.commit_inputs(
            workspace_id=workspace_id, run_id=run_id, inputs=self._start_first, actor=actor
        )
        return self.commit_inputs(
            workspace_id=workspace_id,
            run_id=run_id,
            inputs=lambda _snapshot: (engine.CancelRun(),),
            actor=actor,
        )

    def fire_timer(self, *, workspace_id: int, run_id: str, timer_key: str) -> BridgeCommit:
        """Commit ``TimerDue`` at the bridge clock; a timer not yet due changes nothing."""
        return self.commit_inputs(
            workspace_id=workspace_id,
            run_id=run_id,
            inputs=lambda _snapshot: (engine.TimerDue(timer_key=timer_key),),
        )

    def pause_for_drift(
        self,
        *,
        workspace_id: int,
        run_id: str,
        cause: str,
        body: dict[str, object],
        checksum_parts: Sequence[str],
        now_us: int,
    ) -> BridgeCommit:
        """
        Pause the run ``drift`` through the engine, starting it first if it has not started.

        A starting or running run also gets the drift ``PAUSED`` row, whose identity
        names the pause epoch, so a run resumed while the drift persists pauses again.
        """

        def marker(snapshot: EngineSnapshot, _applied: Sequence[Applied]) -> CommitExtras:
            if snapshot.store.status not in (int(RunStatus.STARTING), int(RunStatus.RUNNING)):
                return CommitExtras()
            row = LogEntryDraft(
                kind=int(LogKind.PAUSED),
                actor_kind=int(ActorKind.ENGINE),
                body=json.dumps(body, sort_keys=True),
                idempotency_cksum=pause_log_checksum(checksum_parts, snapshot.version),
                created_at_us=now_us,
            )
            return CommitExtras(logs=(row,))

        return self.commit_inputs(
            workspace_id=workspace_id,
            run_id=run_id,
            inputs=lambda snapshot: (
                *self._start_first(snapshot),
                engine.PauseRun(reason="drift", detail=cause),
            ),
            extra=marker,
        )

    def feed(self, finished: FinishedWork) -> None:
        """
        Fold a finished row's outcome into its run; rows the engine does not track are skipped.

        A contended commit is left to the resync, which feeds it from the stored row. A
        failure whose row a resume has revived since is not fed. A completed create's
        session goes into the bound-session index.
        """
        self._index_created(finished)
        command = feedback_input(finished)
        if command is None:
            return
        item = finished.item
        failed = finished.status == int(WorkStatus.FAILED)
        pending = (_Fed(item.id, failed, command, decision_of(item)),)
        try:
            self.commit_inputs(
                workspace_id=item.workspace_id,
                run_id=item.run_id,
                inputs=lambda snapshot: self._current(item.workspace_id, pending, snapshot),
            )
        except RunContended:
            _logger.warning(
                "Coral feedback for work %s of run %s was contended; the resync feeds it",
                item.id,
                item.run_id,
            )
        except EngineLoadFailed:
            return

    def _index_created(self, finished: FinishedWork) -> None:
        if self._bound is None:
            return
        created = created_session(finished)
        if created is not None:
            self._bound.push(*created)

    def apply_turn_fact(self, *, workspace_id: int, run_id: str, fact: TurnFact) -> TurnFactResult:
        """
        Reconcile one gathered turn fact and commit its inputs.

        A slot still waiting on its leased effect (a create, send or nudge without a
        receipt) writes nothing: the caller holds the signal and gathers again after the
        receipt. A fact whose key is receipted, or whose inputs the engine refuses,
        changes nothing.

        :raises EngineLoadFailed: when the run cannot be loaded; it is paused once.
        :raises RunContended: when other commits kept winning.
        """
        awaiting = [False]

        def inputs(snapshot: EngineSnapshot) -> tuple[engine.Input, ...]:
            awaiting[0] = awaiting_effect(snapshot.state, fact.slot_id)
            if awaiting[0]:
                return ()
            return reconcile(snapshot.state, [fact], self._clock(), snapshot.config)

        commit = self.commit_inputs(workspace_id=workspace_id, run_id=run_id, inputs=inputs)
        if awaiting[0]:
            return "awaiting_effect"
        return "applied" if commit.outcome.applied else "no_input"

    # ── repair ───────────────────────────────────────────────────────────────

    def schedule_resync(self, run: CoralRun) -> None:
        """Make the run's one resync row due: now while it runs, 15 minutes out while paused."""
        if run.status not in UNFINISHED_RUN_STATUSES:
            return
        now_s = epoch_seconds(self._clock())
        due = now_s + PAUSED_RESYNC_DELAY_S if run.status == int(RunStatus.PAUSED) else now_s
        draft = resync_draft(run.id)
        # Most ticks find the row already due in time; a read takes no write lock.
        for row in self._queue.get_work([draft.id], workspace_id=run.workspace_id):
            if row.status in (int(WorkStatus.PENDING), int(WorkStatus.CLAIMED)) and (
                row.status == int(WorkStatus.CLAIMED) or row.available_at <= due
            ):
                return
        self._queue.reschedule_work(draft, workspace_id=run.workspace_id, available_at=due)

    def resync_run(self, *, workspace_id: int, run_id: str) -> ResyncReport:
        """
        Repair the run level-triggered; every rule is safe to repeat.

        Starts a run whose ``StartRun`` was lost; feeds finished rows of unreceipted
        effects, the anchor and the orchestrator's create and requests, and queues
        missing ones (never reviving one: only a resume does); restores and revives
        timer rows of armed timers; releases holds of a running run; re-gathers the
        turn facts of its working slots, so a lost status edge is recovered; and
        writes the projection, and names a missing orchestrator, when the rows differ.

        :raises EngineLoadFailed: when the run cannot be loaded; it is paused once.
        """
        snapshot = self.load(workspace_id=workspace_id, run_id=run_id)
        started = False
        if snapshot.state.status is None and snapshot.store.status == int(RunStatus.STARTING):
            # The start's own actor was lost with it; the owner stands in.
            commit = self.commit_inputs(
                workspace_id=workspace_id,
                run_id=run_id,
                inputs=self._start_first,
                actor=snapshot.store.spec.user_id,
            )
            started = commit.outcome.applied
            snapshot = self.load(workspace_id=workspace_id, run_id=run_id)
        fed = enqueued = timers = 0
        rows: list[WorkItem] = []
        if snapshot.state.status not in (None, *engine.TERMINAL_STATUSES):
            fed, enqueued, rows = self._repair_effects(snapshot)
            if fed:
                snapshot = self.load(workspace_id=workspace_id, run_id=run_id)
            timers = self._repair_timers(snapshot)
        held = any(
            row.status == int(WorkStatus.PENDING)
            and row.held_since is not None
            and row.error_code in RESUME_RELEASE_CODES
            for row in rows
        ) or (
            # Signals, which the effect rows above do not cover, held for a pause that
            # ended while they were claimed.
            snapshot.state.status == "running"
            and snapshot.store.status == int(RunStatus.RUNNING)
            and self._queue.has_held_work(run_id, RESUME_RELEASE_CODES, workspace_id=workspace_id)
        )

        def release(snapshot: EngineSnapshot, _applied: Sequence[Applied]) -> CommitExtras:
            # A row paused outside the engine keeps its holds until the resume lifts it.
            running = snapshot.state.status == "running" and snapshot.store.status == int(
                RunStatus.RUNNING
            )
            return CommitExtras(
                release_held_codes=RESUME_RELEASE_CODES if held and running else ()
            )

        repair = self.commit_inputs(
            workspace_id=workspace_id, run_id=run_id, inputs=lambda _snapshot: (), extra=release
        )
        return ResyncReport(
            started=started,
            fed=fed,
            enqueued=enqueued,
            timers=timers,
            released=held and repair.outcome.applied,
            repaired=repair.outcome.applied,
            regathered=self._regather(snapshot),
        )

    def _regather(self, snapshot: EngineSnapshot) -> int:
        """
        Queue a re-gather signal for each working slot of a running run, once per bucket.

        A slot waiting on its leased effect is skipped: its receipt comes first. The
        orchestrator a decision waits on is re-gathered too, so an archived or deleted
        one is found without another message to it. A paused run is not re-gathered;
        its resume re-prompts what failed.
        """
        state, run = snapshot.state, snapshot.store.run
        if state.status != "running" or snapshot.store.status != int(RunStatus.RUNNING):
            return 0
        now_s = epoch_seconds(self._clock())
        drafts: list[WorkItemDraft] = []
        for slot in state.slots:
            if slot.status != "working" or awaiting_effect(state, slot.id):
                continue
            session_id = slot_session_id(run.workspace_id, state, slot.id)
            if session_id is None:
                continue
            drafts.append(
                turn_signal_draft(
                    run_id=run.id,
                    session_id=session_id,
                    engine_slot_id=slot.id,
                    generation=slot.session_generation,
                    idempotency_key=regather_key(session_id, now_s),
                    edge=None,
                    available_at=now_s,
                )
            )
        orchestrator = regather_session(run, state)
        if orchestrator is not None:
            drafts.append(
                turn_signal_draft(
                    run_id=run.id,
                    session_id=orchestrator,
                    engine_slot_id=ORCHESTRATOR_SLOT_ID,
                    generation=ORCHESTRATOR_GENERATION,
                    idempotency_key=regather_key(orchestrator, now_s),
                    edge=None,
                    available_at=now_s,
                )
            )
        if drafts:
            self._queue.enqueue_work(drafts, workspace_id=run.workspace_id, now=now_s)
        return len(drafts)

    def _repair_effects(self, snapshot: EngineSnapshot) -> tuple[int, int, list[WorkItem]]:
        """
        Queue missing rows of unreceipted effects, the anchor and the orchestrator's
        create and requests; feed finished ones.
        """
        run = snapshot.store.run
        now = self._clock()
        ctx = MapContext(
            workspace_id=run.workspace_id,
            run_id=run.id,
            graph=snapshot.graph,
            state=snapshot.state,
            request_preview=snapshot.store.spec.request_preview,
            title=run.title,
            now=now,
        )
        receipted = {receipt.key for receipt in snapshot.state.receipts}
        effects = {
            effect_work_id(run.id, effect.effect_key): effect
            for effect in snapshot.state.effects
            if effect.kind in FED_KINDS and effect.effect_key not in receipted
        }
        anchor_id = effect_work_id(run.id, anchor_effect_key(run.id))
        # Their keys are recomputed from the run and its open decisions.
        orchestrator = {draft.id: draft for draft in repair_drafts(ctx, run)}
        found = self._queue.get_work(
            [*effects, anchor_id, *orchestrator], workspace_id=run.workspace_id
        )
        rows = {row.id: row for row in found}
        missing: list[WorkItemDraft] = []
        for work_id, effect in effects.items():
            if work_id in rows:
                continue
            try:
                draft = map_effect(ctx, effect)
            except (UnsupportedStance, MappedPayloadTooLarge) as exc:
                self._pause_visibly(run.workspace_id, run.id, _unbuildable_detail(exc))
                continue
            if draft is not None:
                missing.append(draft)
        if anchor_id not in rows:
            missing.append(anchor_create_draft(ctx))
        missing.extend(draft for work_id, draft in orchestrator.items() if work_id not in rows)
        if missing:
            self._queue.enqueue_work(
                missing, workspace_id=run.workspace_id, now=epoch_seconds(now)
            )
        fed: list[_Fed] = []
        for row in rows.values():
            if row.status == int(WorkStatus.ABANDONED):
                _logger.debug("Coral run %s has abandoned work %s", run.id, row.id)
                continue
            outcome = finished_from_row(row)
            self._index_created(outcome)
            command = feedback_input(outcome)
            if command is not None:
                failed = row.status == int(WorkStatus.FAILED)
                fed.append(_Fed(row.id, failed, command, decision_of(row)))
        for start in range(0, len(fed), FEED_BATCH):
            batch = tuple(fed[start : start + FEED_BATCH])
            try:
                self.commit_inputs(
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    inputs=lambda snapshot, batch=batch: self._current(
                        run.workspace_id, batch, snapshot
                    ),
                )
            except RunContended:
                _logger.warning(
                    "Coral resync of run %s was contended feeding outcomes; the next one retries",
                    run.id,
                )
        return len(fed), len(missing), list(rows.values())

    def _current(
        self, workspace_id: int, fed: Sequence[_Fed], snapshot: EngineSnapshot
    ) -> tuple[engine.Input, ...]:
        """
        The inputs whose outcome still stands: a failure's row must still be FAILED.

        A resume revives exhausted rows in its own commit; read inside the commit's
        attempt, a stale failure is dropped instead of pausing the resumed run again.
        A failed message to the orchestrator counts only while its decision is open.
        """
        failed = [item.work_id for item in fed if item.failed]
        standing = {
            row.id
            for row in (self._queue.get_work(failed, workspace_id=workspace_id) if failed else ())
            if row.status == int(WorkStatus.FAILED)
        }
        waiting = {item.activation_id for item in open_decisions(snapshot.state)}
        return tuple(
            item.command
            for item in fed
            if (not item.failed or item.work_id in standing)
            and (item.decision_id is None or item.decision_id in waiting)
        )

    def _repair_timers(self, snapshot: EngineSnapshot) -> int:
        """Put back a lost row of an armed timer, and revive a failed one."""
        run = snapshot.store.run
        drafts = {
            draft.id: (timer, draft)
            for timer in snapshot.state.timers
            for draft in (timer_draft(run.id, timer),)
        }
        rows = {
            row.id: row
            for row in self._queue.get_work(list(drafts), workspace_id=run.workspace_id)
        }
        repaired = 0
        for work_id, (timer, draft) in drafts.items():
            row = rows.get(work_id)
            if row is not None and row.status != int(WorkStatus.FAILED):
                continue
            self._queue.reschedule_work(
                draft,
                workspace_id=run.workspace_id,
                available_at=ceil_epoch_seconds(timer.due_at),
            )
            repaired += 1
        return repaired


def _unbuildable_detail(exc: Exception) -> str:
    return next(detail for kind, detail in _UNBUILDABLE if isinstance(exc, kind))


__all__ = [
    "LOAD_FAILED_DETAIL",
    "UNBUILDABLE_ERRORS",
    "BridgeCommit",
    "EngineBridge",
    "EngineLoadFailed",
    "ResyncReport",
    "RunNotRunnable",
    "TurnFactResult",
]
