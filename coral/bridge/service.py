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
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
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
    REGATHER_BUCKET_S,
    FrozenConfigMissing,
    ceil_epoch_seconds,
    engine_config_for,
    epoch_seconds,
    epoch_us,
    utc_now,
)
from coral.bridge.feedback import (
    abandoned_restart,
    decision_of,
    feedback_input,
    finished_from_row,
    gate_of,
    orchestrator_generation_of,
)
from coral.bridge.fold import EngineStateCache
from coral.bridge.gate_rows import live_publish_effects
from coral.bridge.graphs import PinnedGraphError, PinnedGraphs
from coral.bridge.keys import (
    ORCHESTRATOR_SLOT_ID,
    anchor_effect_key,
    effect_work_id,
    slot_session_id,
    store_activation_id,
)
from coral.bridge.mapping import (
    FED_KINDS,
    NEXT_RESYNC_AT,
    RUN_RESYNC,
    MapContext,
    MappedPayloadTooLarge,
    UnsupportedStance,
    anchor_create_draft,
    boot_regather_key,
    map_effect,
    regather_key,
    resync_draft,
    timer_draft,
    turn_signal_draft,
)
from coral.bridge.messages import sanitize
from coral.bridge.orchestrator import open_decisions, regather_session, repair_drafts
from coral.db.enum_codecs import ActorKind, LogKind, RunPauseReason, RunStatus, WorkStatus
from coral.engine import transition
from coral.engine import types as engine
from coral.engine.facts import TurnFact
from coral.engine.reconcile import awaiting_effect, reconcile
from coral.gates.ids import (
    MAX_GATE_NOTE_CHARS,
    MAX_GATE_OUTCOME_CHARS,
    live_visit_ids,
    new_gate_elicitation_id,
    receipt_label,
)
from coral.model.ir import CompiledGraph
from coral.queue.drainer import FinishedWork
from coral.queue.run_effects import describe_exception
from coral.recovery.pause import pause_log_checksum, pause_run_once
from coral.stores.profiles import SqlProfileStore
from coral.stores.protocols import (
    STORED_TEXT_ERRORS,
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
# Stored text that does not decode in the fold or a commit's reducer. Of the ValueErrors
# only UnicodeDecodeError counts there: another may be a reducer defect.
_FOLD_TEXT_ERRORS = (zstandard.ZstdError, UnicodeDecodeError)
# Commits that fail the same way every time: the run pauses with this detail instead.
_UNBUILDABLE: tuple[tuple[type[Exception], str], ...] = (
    (TransitionTooLarge, "transition_too_large"),
    (UnsupportedStance, "unsupported_stance"),
    (MappedPayloadTooLarge, "payload_too_large"),
)
UNBUILDABLE_ERRORS = tuple(kind for kind, _detail in _UNBUILDABLE)
LOAD_FAILED_DETAIL = "engine.load_failed"
# The detail of the pause a run's owner asks for.
USER_PAUSE_DETAIL = "user"
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
    :param visit_id: For a gate's publish or withdraw, the visit row it is about.
    :param generation: For an orchestrator row, the generation it was queued for.
    """

    work_id: str
    failed: bool
    command: engine.Input
    decision_id: str | None = None
    visit_id: str | None = None
    generation: int | None = None


@dataclass(frozen=True)
class GateAnswerResult:
    """
    What committing one gate answer did.

    :param code: For a refusal, the engine's code, ``invalid_answer`` (a label or note no
        row can store; nothing was loaded), ``unbuildable`` (the run was paused instead)
        or ``run.contended``.
    :param allowed: For ``tool.illegal`` only, the labels the gate takes.
    :param answered_label: The label a receipt for the visit's token held in the state
        the answer was applied to, if it had one.
    """

    outcome: Literal["accepted", "duplicate", "refused"]
    code: str | None = None
    allowed: tuple[str, ...] = ()
    answered_label: str | None = None


@dataclass(frozen=True)
class PauseResult:
    """
    What a user pause did.

    :param outcome: ``paused`` when the engine took the pause, ``unchanged`` when it
        held it already, ``refused`` otherwise.
    :param code: For a refusal, the engine's code (``run_terminal`` for a finished
        run, a row cancelled without its engine included) or ``unbuildable`` (the run
        was paused ``failure_path`` instead).
    """

    outcome: Literal["paused", "unchanged", "refused"]
    commit: BridgeCommit
    code: str | None = None


@dataclass(frozen=True)
class RetryResult:
    """
    What a step retry did.

    :param outcome: ``retried`` when the engine took the retry, ``refused`` otherwise.
    :param commit: ``None`` when nothing was committed (``unknown_activation``).
    :param code: For a refusal: ``unknown_activation`` (no started activation of the run
        has the id), the engine's code (``retry_not_allowed``, ``host_offline_hold``,
        ``restart_in_progress``, ``run_terminal``), or ``unbuildable`` (the run was paused
        ``failure_path`` instead).
    """

    outcome: Literal["retried", "refused"]
    commit: BridgeCommit | None
    code: str | None = None


@dataclass(frozen=True)
class RunRead:
    """
    A run as a read sees it, without the pause a failed load makes.

    :param rows: ``None`` when its stored rows cannot be decoded.
    :param snapshot: ``None`` when its engine state cannot be loaded.
    """

    run: CoralRun
    rows: RunState | None
    snapshot: EngineSnapshot | None

    @property
    def loadable(self) -> bool:
        return self.snapshot is not None


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
        gate_elicitation_ids: Callable[[], str] = new_gate_elicitation_id,
        profiles: SqlProfileStore | None = None,
    ) -> None:
        """
        :param bound_sessions: The status-edge recorder's index; each completed create's
            session is pushed into it.
        :param gate_elicitation_ids: Draws the prompt id of a gate visit's new row.
        :param profiles: Pins the profiles a run uses at its start; without it a
            workflow that uses one is refused.
        """
        self._runs = run_store
        self._queue = queue_store
        self._versions = versions
        self._clock = clock
        self._bound = bound_sessions
        self._gate_ids = gate_elicitation_ids
        self._profiles = profiles
        self._graphs = PinnedGraphs(versions, max_entries=fold_cache_size)
        self._states = EngineStateCache(
            run_store, max_runs=fold_cache_size, max_bytes=fold_cache_bytes
        )
        self._start_hashes: OrderedDict[tuple[int, str], str] = OrderedDict()
        self._max_start_hashes = fold_cache_size
        self._lock = threading.Lock()
        # Names this leader term in the keys of its first re-gathers.
        self._boot_id = uuid.uuid4().hex
        # Runs this term re-gathered, and the bucket of that first re-gather.
        self._regathered: dict[tuple[int, str], int] = {}
        # Runs whose resync this term has scheduled.
        self._scheduled: set[tuple[int, str]] = set()

    @property
    def run_store(self) -> RunStore:
        return self._runs

    @property
    def versions(self) -> SqlAlchemyWorkflowVersionStore:
        return self._versions

    @property
    def profiles(self) -> SqlProfileStore | None:
        return self._profiles

    @property
    def bound_sessions(self) -> BoundSessions | None:
        return self._bound

    @property
    def gate_elicitation_ids(self) -> Callable[[], str]:
        return self._gate_ids

    def now(self) -> datetime:
        return self._clock()

    def begin_leader_term(self) -> None:
        """
        Start this replica's records afresh when it starts leading.

        Another leader may have re-gathered or scheduled the runs in between, so each
        run's first re-gather and first resync in the new term act as after a restart.
        """
        with self._lock:
            self._boot_id = uuid.uuid4().hex
            self._regathered.clear()
            self._scheduled.clear()

    def start_input(self, snapshot: EngineSnapshot) -> engine.StartRun:
        """The run's one ``StartRun``, derived from what its rows store."""
        run_id = snapshot.store.run_id
        # The run id derives from the caller's start key, so it is as idempotent a key.
        return engine.StartRun(
            run_id=run_id,
            start_key=run_id,
            version_hash=snapshot.graph.content_hash,
            rules=engine.RULES,
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

    def read(self, *, workspace_id: int, run_id: str) -> RunRead:
        """
        The run's row, rows and engine state, as far as they load; never writes.

        Unlike :meth:`load`, a run that cannot be loaded is not paused: reads run on
        every view of a run, and a view must not change it.

        A run row whose other rows are missing or do not decode reads as the row alone.

        :raises RunNotFound: when the workspace has no such run.
        """
        try:
            rows = self._load_rows(workspace_id, run_id)
        except (EngineLoadFailed, RunNotFound) as exc:
            run = self._runs.get_run(run_id, workspace_id=workspace_id)
            if run is None:
                raise RunNotFound(
                    f"Run {run_id!r} not found in workspace {workspace_id}"
                ) from None
            _logger.debug(
                "Coral reads run %s without its rows: %s", run_id, describe_exception(exc)
            )
            return RunRead(run=run, rows=None, snapshot=None)
        try:
            snapshot = self._snapshot(rows)
        except (EngineLoadFailed, *_FOLD_TEXT_ERRORS) as exc:
            # A log or pinned version that is not UTF-8 fails below the load errors.
            _logger.debug(
                "Coral reads run %s without its engine state: %s",
                run_id,
                describe_exception(exc),
            )
            return RunRead(run=rows.run, rows=rows, snapshot=None)
        return RunRead(run=rows.run, rows=rows, snapshot=snapshot)

    def pinned_graph(self, *, workspace_id: int, version_id: str) -> CompiledGraph:
        """
        The graph of a pinned workflow version, from the cache loads share; never writes.

        :raises PinnedGraphError: when the version is missing or its graph cannot be used.
        """
        return self._graphs.load(
            workspace_id=workspace_id, version_id=version_id, expected_hash=None
        )

    def _load_rows(self, workspace_id: int, run_id: str) -> RunState:
        return self._load_state(workspace_id, run_id)[0]

    def _load_state(self, workspace_id: int, run_id: str) -> tuple[RunState, int]:
        """The run's rows and version; rows whose stored text does not decode fail the load."""
        try:
            return self._runs.load_run_state(run_id, workspace_id=workspace_id)
        except STORED_TEXT_ERRORS as exc:
            raise EngineLoadFailed(workspace_id, run_id, exc) from exc

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
        ``unbuildable`` names. On a row cancelled without its engine, a running or
        paused engine is cancelled first, and one never started takes no input.

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
            commands = _converging(snapshot, inputs)
            if commands is None:
                latest[0] = ()
                return Transition.empty()
            applied = self._apply(snapshot, commands, now)
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
                    gate_elicitation_ids=self._gate_ids,
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
                load_state=partial(self._load_state, workspace_id, run_id),
                now=epoch_seconds(now),
                lock_timeout_s=LOCK_TIMEOUT_S,
            )
        except _FOLD_TEXT_ERRORS as exc:
            raise EngineLoadFailed(workspace_id, run_id, exc) from exc
        if (
            outcome.applied
            and latest[0]
            and latest[0][-1].after.status in engine.TERMINAL_STATUSES
        ):
            self._forget_run((workspace_id, run_id))
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

    def pause_run(self, *, workspace_id: int, run_id: str, actor: str | None) -> PauseResult:
        """
        Pause the run for its owner through the engine, starting it first if it has not.

        Decided by the pause's own entry, not by whether the commit applied: on a row
        cancelled without its engine, the commit cancels the engine and the pause is
        refused.

        :raises EngineLoadFailed: when the run cannot be loaded; it is paused once.
        :raises RunContended: when other commits kept winning.
        """
        pauses: list[Applied] = []

        def observe(_snapshot: EngineSnapshot, applied: Sequence[Applied]) -> CommitExtras:
            pauses[:] = [item for item in applied if isinstance(item.entry.input, engine.PauseRun)]
            return CommitExtras()

        commit = self.commit_inputs(
            workspace_id=workspace_id,
            run_id=run_id,
            inputs=lambda snapshot: (
                *self._start_first(snapshot),
                engine.PauseRun(reason="user", detail=USER_PAUSE_DETAIL),
            ),
            actor=actor,
            extra=observe,
        )
        if commit.unbuildable is not None:
            return PauseResult(outcome="refused", commit=commit, code="unbuildable")
        if not commit.entries or not pauses:
            # A row cancelled before its engine started takes no input.
            return PauseResult(outcome="refused", commit=commit, code="run_terminal")
        (pause,) = pauses
        if pause.entry.rejection is not None:
            return PauseResult(outcome="refused", commit=commit, code=pause.entry.rejection.code)
        return PauseResult(outcome="paused" if pause.accepted else "unchanged", commit=commit)

    def retry_activation(
        self, *, workspace_id: int, run_id: str, actor: str | None, activation_id: str
    ) -> RetryResult:
        """
        Retry the step activation whose store id is ``activation_id``, as ``actor``.

        The id is matched only against the run's own activations; none, or a run whose
        engine has not started, is refused ``unknown_activation`` with nothing committed.
        The engine decides the rest: the retried step's old session is restarted while
        the run stays paused.

        :raises EngineLoadFailed: when the run cannot be loaded; it is paused once.
        :raises RunContended: when other commits kept winning.
        """
        snapshot = self.load(workspace_id=workspace_id, run_id=run_id)
        found = next(
            (
                activation
                for activation in snapshot.state.activations
                if store_activation_id(run_id, activation.id) == activation_id
            ),
            None,
        )
        if snapshot.state.status is None or found is None:
            return RetryResult(outcome="refused", commit=None, code="unknown_activation")
        command = engine.RetryStep(
            node_id=found.node_id,
            item_path=found.item_path,
            iteration_path=found.iteration_path,
        )
        retries: list[Applied] = []

        def observe(_snapshot: EngineSnapshot, applied: Sequence[Applied]) -> CommitExtras:
            retries[:] = [
                item for item in applied if isinstance(item.entry.input, engine.RetryStep)
            ]
            return CommitExtras()

        commit = self.commit_inputs(
            workspace_id=workspace_id,
            run_id=run_id,
            inputs=lambda _snapshot: (command,),
            actor=actor,
            extra=observe,
        )
        if commit.unbuildable is not None:
            return RetryResult(outcome="refused", commit=commit, code="unbuildable")
        if not retries:
            # A row cancelled without its engine takes the cancel first.
            return RetryResult(outcome="refused", commit=commit, code="run_terminal")
        (retry,) = retries
        if retry.entry.rejection is not None:
            return RetryResult(outcome="refused", commit=commit, code=retry.entry.rejection.code)
        return RetryResult(outcome="retried", commit=commit)

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

    def answer_gate(
        self,
        *,
        workspace_id: int,
        run_id: str,
        token: str,
        label: str,
        note: str,
        actor: str,
    ) -> GateAnswerResult:
        """
        Commit one ``AnswerGate`` for the visit ``token``; ``actor`` answers as a user.

        A receipt for the token with the same label, in the state the commit is reduced
        on, commits nothing: a retry is a duplicate even after the answer asked the gate
        again. A commit that cannot be built pauses the run and is refused
        ``unbuildable``, never accepted. A label over 128 characters, a note over 2,000,
        or either holding NUL or a lone surrogate is refused ``invalid_answer`` first.

        :raises EngineLoadFailed: when the run cannot be loaded; it is paused once.
        :raises RunNotFound: when the workspace has no such run.
        """
        if not _storable(label, MAX_GATE_OUTCOME_CHARS) or not _storable(
            note, MAX_GATE_NOTE_CHARS
        ):
            return GateAnswerResult(outcome="refused", code="invalid_answer")
        answered: list[str | None] = [None]
        answers: list[Applied] = []

        def inputs(snapshot: EngineSnapshot) -> tuple[engine.Input, ...]:
            answered[0] = receipt_label(snapshot.state, token)
            if answered[0] == label:
                return ()
            return (engine.AnswerGate(token=token, label=label, by=actor, note=note),)

        def observe(_snapshot: EngineSnapshot, applied: Sequence[Applied]) -> CommitExtras:
            answers[:] = [
                item for item in applied if isinstance(item.entry.input, engine.AnswerGate)
            ]
            return CommitExtras()

        try:
            commit = self.commit_inputs(
                workspace_id=workspace_id, run_id=run_id, inputs=inputs, actor=actor, extra=observe
            )
        except RunContended:
            return GateAnswerResult(outcome="refused", code="run.contended")
        if commit.unbuildable is not None:
            return GateAnswerResult(
                outcome="refused", code="unbuildable", answered_label=answered[0]
            )
        if not answers:
            return GateAnswerResult(outcome="duplicate", answered_label=answered[0])
        (applied,) = answers
        rejection = applied.entry.rejection
        if rejection is not None:
            # Other refusals list the engine's input kinds, which mean nothing to a person.
            labels = rejection.allowed_values if rejection.code == "tool.illegal" else ()
            return GateAnswerResult(
                outcome="refused",
                code=rejection.code,
                allowed=labels,
                answered_label=answered[0],
            )
        # Decided by the entry, not by whether the commit applied: a gate-row repair in
        # the same commit applies it too.
        if applied.accepted and applied.entry.receipt_key == token and commit.outcome.applied:
            return GateAnswerResult(outcome="accepted")
        return GateAnswerResult(outcome="duplicate", answered_label=answered[0])

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
        session goes into the bound-session index, and a resync that names when it
        should run again is rescheduled for then.
        """
        self._index_created(finished)
        self._resync_again(finished)
        command = feedback_input(finished)
        if command is None:
            return
        item = finished.item
        failed = finished.status == int(WorkStatus.FAILED)
        pending = (
            _Fed(
                item.id,
                failed,
                command,
                decision_of(item),
                gate_of(item),
                orchestrator_generation_of(item),
            ),
        )
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

    def _resync_again(self, finished: FinishedWork) -> None:
        """Make a finished resync row due again by the time its result names."""
        result = finished.result
        if finished.status != int(WorkStatus.SUCCEEDED) or not isinstance(result, dict):
            return
        due = result.get(NEXT_RESYNC_AT)
        if not isinstance(due, int) or isinstance(due, bool):
            return
        item = finished.item
        try:
            effect_type = json.loads(item.payload).get("effect_type")
        except (json.JSONDecodeError, AttributeError):
            return
        if effect_type == RUN_RESYNC:
            self.reschedule_resync(workspace_id=item.workspace_id, run_id=item.run_id, due_s=due)

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
        """
        Make the run's one resync row due: now while it runs, 15 minutes out while paused.

        A paused run's first schedule in a leader term is due now too, so a restart
        finishes at once what a crash cut short (a restart's lost feed, say).
        """
        key = (run.workspace_id, run.id)
        if run.status not in UNFINISHED_RUN_STATUSES:
            self._forget_run(key)
            return
        with self._lock:
            seen = key in self._scheduled
        now_s = epoch_seconds(self._clock())
        paused = run.status == int(RunStatus.PAUSED)
        due = now_s + PAUSED_RESYNC_DELAY_S if paused and seen else now_s
        draft = resync_draft(run.id)
        # Most ticks find the row already due in time; a read takes no write lock.
        rows = self._queue.get_work([draft.id], workspace_id=run.workspace_id)
        if not any(
            row.status == int(WorkStatus.CLAIMED)
            or (row.status == int(WorkStatus.PENDING) and row.available_at <= due)
            for row in rows
        ):
            self._queue.reschedule_work(draft, workspace_id=run.workspace_id, available_at=due)
        with self._lock:
            self._scheduled.add(key)

    def reschedule_resync(self, *, workspace_id: int, run_id: str, due_s: int) -> None:
        """
        Make the run's resync row due by ``due_s`` (epoch seconds).

        A row already due sooner keeps its time; a claimed row is left to its worker.
        """
        self._queue.reschedule_work(
            resync_draft(run_id), workspace_id=workspace_id, available_at=due_s
        )

    def _forget_run(self, key: tuple[int, str]) -> None:
        """Drop a finished run from this term's resync and re-gather records.

        Called when this process finishes the run, and when a resync finds it finished.
        """
        with self._lock:
            self._scheduled.discard(key)
            self._regathered.pop(key, None)

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
        if snapshot.state.status in engine.TERMINAL_STATUSES:
            self._forget_run((workspace_id, run_id))
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
        its resume re-prompts what failed. A run's first re-gather in a leader term is
        keyed by the term, so a restart checks every turn at once even when the last
        leader already re-gathered in this bucket; the rest of that bucket repeats the
        same key.
        """
        state, run = snapshot.state, snapshot.store.run
        if state.status != "running" or snapshot.store.status != int(RunStatus.RUNNING):
            return 0
        now_s = epoch_seconds(self._clock())
        bucket = now_s // REGATHER_BUCKET_S
        run_key = (run.workspace_id, run.id)
        with self._lock:
            booted_in = self._regathered.get(run_key)
            boot_id = self._boot_id

        def key_of(session_id: str) -> str:
            if booted_in is None or booted_in == bucket:
                return boot_regather_key(session_id, boot_id)
            return regather_key(session_id, now_s)

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
                    idempotency_key=key_of(session_id),
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
                    generation=state.orchestrator_generation,
                    idempotency_key=key_of(orchestrator),
                    edge=None,
                    available_at=now_s,
                )
            )
        if drafts:
            self._queue.enqueue_work(drafts, workspace_id=run.workspace_id, now=now_s)
            if booted_in is None:
                with self._lock:
                    self._regathered.setdefault(run_key, bucket)
        return len(drafts)

    def _repair_effects(self, snapshot: EngineSnapshot) -> tuple[int, int, list[WorkItem]]:
        """
        Queue missing rows of unreceipted effects, the anchor, the orchestrator's create
        and requests, and live gate visits' publishes; feed finished ones, and an
        abandoned restart of its slot's generation as the restart's failure.
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
        effects.update(
            (effect_work_id(run.id, effect.effect_key), effect)
            for effect in live_publish_effects(snapshot.state)
        )
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
                ended = abandoned_restart(row, snapshot.state)
                if ended is not None:
                    # Never revived, so it stands without the FAILED re-check.
                    fed.append(_Fed(row.id, False, ended))
                else:
                    _logger.debug("Coral run %s has abandoned work %s", run.id, row.id)
                continue
            outcome = finished_from_row(row)
            self._index_created(outcome)
            command = feedback_input(outcome)
            if command is not None:
                failed = row.status == int(WorkStatus.FAILED)
                fed.append(
                    _Fed(
                        row.id,
                        failed,
                        command,
                        decision_of(row),
                        gate_of(row),
                        orchestrator_generation_of(row),
                    )
                )
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
        A failed message to the orchestrator counts only while its decision is open, an
        orchestrator row only while its generation is the run's, and a failed gate row
        only while its visit is live.
        """
        failed = [item.work_id for item in fed if item.failed]
        standing = {
            row.id
            for row in (self._queue.get_work(failed, workspace_id=workspace_id) if failed else ())
            if row.status == int(WorkStatus.FAILED)
        }
        waiting = {item.activation_id for item in open_decisions(snapshot.state)}
        generation = snapshot.state.orchestrator_generation
        live = live_visit_ids(snapshot.state, snapshot.store.run_id)
        return tuple(
            item.command
            for item in fed
            if (not item.failed or item.work_id in standing)
            and (item.decision_id is None or item.decision_id in waiting)
            and (item.generation is None or item.generation >= generation)
            and (item.visit_id is None or item.visit_id in live)
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


def _converging(snapshot: EngineSnapshot, inputs: Inputs) -> Sequence[engine.Input] | None:
    """
    The inputs to apply; ``None`` refuses them all.

    A run cancelled on its row alone (it could not be loaded then) leads a running or
    paused engine to its cancel before anything else, so the row stays cancelled. An
    engine that never started stays unstarted, so a start and a cancel never share
    one commit.
    """
    if snapshot.store.status != int(RunStatus.CANCELLED):
        return inputs(snapshot)
    status = snapshot.state.status
    if status is None:
        return None
    if status in engine.TERMINAL_STATUSES:
        return inputs(snapshot)
    return (engine.CancelRun(), *inputs(snapshot))


def _unbuildable_detail(exc: Exception) -> str:
    return next(detail for kind, detail in _UNBUILDABLE if isinstance(exc, kind))


def _storable(text: str, limit: int) -> bool:
    """Within ``limit`` characters and free of NUL and lone surrogates, which no row takes."""
    return len(text) <= limit and sanitize(text) == text


__all__ = [
    "LOAD_FAILED_DETAIL",
    "UNBUILDABLE_ERRORS",
    "USER_PAUSE_DETAIL",
    "BridgeCommit",
    "EngineBridge",
    "EngineLoadFailed",
    "GateAnswerResult",
    "PauseResult",
    "ResyncReport",
    "RetryResult",
    "RunNotRunnable",
    "RunRead",
    "TurnFactResult",
]
