"""SQLAlchemy implementation of the Coral run store."""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, asc, desc, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.db import (
    DEFAULT_WORKSPACE_ID,
    ActivationRow,
    AgentSlotRow,
    GateVisitRow,
    HandoffItemRow,
    HandoffRow,
    JoinArrivalRow,
    RunLogRow,
    RunRow,
    RunSpecRow,
    ToolReplyRow,
    WorkRow,
    coral_engine,
    current_workspace_id,
    keyset_after,
    make_named_managed_session_maker,
    run_write_transaction,
    shared_read_scope,
)
from coral.db.enum_codecs import GateVisitStatus, LogKind, RunStatus, WorkStatus
from coral.model.ids import derived_id
from coral.stores.protocols import (
    UNFINISHED_RUN_STATUSES,
    ActivationState,
    AgentSlotState,
    CommitOutcome,
    CoralRun,
    GateVisitState,
    HandoffItemState,
    HandoffState,
    JoinArrivalState,
    RunLogEntry,
    RunNotFound,
    RunReceipt,
    RunStartSpec,
    RunState,
    RunVersionConflict,
    StartKeyConflict,
    Transition,
    TransitionTooLarge,
    require_checksum32,
)
from coral.stores.work_rows import insert_pending_if_absent, repended_values

_logger = logging.getLogger(__name__)


def _compute_spec_digest(spec: RunStartSpec) -> bytes:
    fields = (
        spec.workflow_id,
        spec.version_id,
        spec.title,
        spec.request_preview,
        spec.user_id or "",
        spec.account_generation or "",
        spec.request_ref or "",
        str(spec.trigger_kind),
        str(spec.execution_target),
        spec.host_id or "",
        spec.repository_id or "",
        spec.repo_path or "",
        spec.worktree_path or "",
        spec.base_ref or "",
        spec.base_commit or "",
        spec.run_branch or "",
        str(spec.auth_mode),
        spec.credential_ref or "",
        str(spec.max_activations),
        str(spec.refresh_threshold_bp),
        str(spec.rejected_call_limit),
        str(spec.engine_version),
        str(spec.state_version),
        str(spec.log_version),
        spec.orchestrator_session_id or "",
        spec.engine_config or "",
    )
    return hashlib.sha256("\0".join(fields).encode()).digest()


def _compute_stored_spec_digest(run: RunRow, spec: RunSpecRow) -> bytes:
    fields = (
        run.workflow_id,
        run.version_id,
        run.title,
        spec.request_preview,
        run.user_id or "",
        run.account_generation or "",
        spec.request_ref or "",
        str(spec.trigger_kind),
        str(spec.execution_target),
        spec.host_id or "",
        spec.repository_id or "",
        spec.repo_path or "",
        spec.worktree_path or "",
        spec.base_ref or "",
        spec.base_commit or "",
        spec.run_branch or "",
        str(spec.auth_mode),
        spec.credential_ref or "",
        str(spec.max_activations),
        str(spec.refresh_threshold_bp),
        str(spec.rejected_call_limit),
        str(run.engine_version),
        str(run.state_version),
        str(run.log_version),
        run.orchestrator_session_id or "",
        spec.engine_config or "",
    )
    return hashlib.sha256("\0".join(fields).encode()).digest()


def _to_coral_run(row: RunRow) -> CoralRun:
    return CoralRun(
        workspace_id=row.workspace_id,
        id=row.id,
        workflow_id=row.workflow_id,
        version_id=row.version_id,
        status=row.status,
        version=row.version,
        next_log_seq=row.next_log_seq,
        activation_count=row.activation_count,
        title=row.title,
        engine_version=row.engine_version,
        state_version=row.state_version,
        log_version=row.log_version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        user_id=row.user_id,
        account_generation=row.account_generation,
        pause_reason=row.pause_reason,
        orchestrator_session_id=row.orchestrator_session_id,
        finished_at=row.finished_at,
    )


def _to_activation_state(row: ActivationRow) -> ActivationState:
    return ActivationState(
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        id=row.id,
        node_id=row.node_id,
        scope_key=row.scope_key,
        status=row.status,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        created_at=row.created_at,
        updated_at=row.updated_at,
        parent_activation_id=row.parent_activation_id,
        outcome=row.outcome,
        chosen_label=row.chosen_label,
        taken_over_by=row.taken_over_by,
        start_commit=row.start_commit,
        start_fingerprint=row.start_fingerprint,
        items_total=row.items_total,
        items_closed=row.items_closed,
        started_at=row.started_at,
        closed_at=row.closed_at,
    )


def _to_join_arrival_state(row: JoinArrivalRow) -> JoinArrivalState:
    return JoinArrivalState(
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        activation_id=row.activation_id,
        arrow_id=row.arrow_id,
        source_activation_id=row.source_activation_id,
        outcome=row.outcome,
        arrived_at=row.arrived_at,
        handoff_id=row.handoff_id,
    )


def _to_agent_slot_state(row: AgentSlotRow) -> AgentSlotState:
    return AgentSlotState(
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        id=row.id,
        activation_id=row.activation_id,
        node_id=row.node_id,
        scope_key=row.scope_key,
        roster_index=row.roster_index,
        role=row.role,
        session_generation=row.session_generation,
        status=row.status,
        post_close_activity=row.post_close_activity,
        nudges=row.nudges,
        consecutive_rejections=row.consecutive_rejections,
        created_at=row.created_at,
        updated_at=row.updated_at,
        profile_revision_id=row.profile_revision_id,
        session_id=row.session_id,
        closing_code=row.closing_code,
        lease_expires_at=row.lease_expires_at,
        lease_holder=row.lease_holder,
        hold_seen_at=row.hold_seen_at,
        restart_attempt_id=row.restart_attempt_id,
        last_edge_status=row.last_edge_status,
        last_turn_outcome=row.last_turn_outcome,
        last_edge_at=row.last_edge_at,
        branch=row.branch,
        worktree_path=row.worktree_path,
        last_turn_origin=row.last_turn_origin,
        context_used_bp=row.context_used_bp,
    )


def _to_handoff_state(row: HandoffRow) -> HandoffState:
    return HandoffState(
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        id=row.id,
        activation_id=row.activation_id,
        node_id=row.node_id,
        scope_key=row.scope_key,
        attempt=row.attempt,
        status=row.status,
        submit_status=row.submit_status,
        idempotency_cksum=row.idempotency_cksum,
        submitted_at_us=row.submitted_at_us,
        slot_id=row.slot_id,
        label=row.label,
        item_count=row.item_count,
        summary=row.summary,
        report_ref=row.report_ref,
        report_bytes=row.report_bytes,
        blocked_reason=row.blocked_reason,
        evidence_outcome=row.evidence_outcome,
        evidence_ref=row.evidence_ref,
        rejection_code=row.rejection_code,
        rejection_message=row.rejection_message,
        submitted_by_session_id=row.submitted_by_session_id,
    )


def _to_handoff_item_state(row: HandoffItemRow) -> HandoffItemState:
    return HandoffItemState(
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        handoff_id=row.handoff_id,
        item_index=row.item_index,
        item_key=row.item_key,
        title=row.title,
        payload=row.payload,
        payload_ref=row.payload_ref,
    )


def _to_gate_visit_state(row: GateVisitRow) -> GateVisitState:
    return GateVisitState(
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        id=row.id,
        activation_id=row.activation_id,
        node_id=row.node_id,
        scope_key=row.scope_key,
        visit_no=row.visit_no,
        token=row.token,
        status=row.status,
        opened_at=row.opened_at,
        owner_user_id=row.owner_user_id,
        elicitation_id=row.elicitation_id,
        elicitation_session_id=row.elicitation_session_id,
        prompt_ref=row.prompt_ref,
        answer_label=row.answer_label,
        answered_by=row.answered_by,
        note=row.note,
        reminded_at=row.reminded_at,
        resolved_at=row.resolved_at,
    )


def _to_run_log_entry(row: RunLogRow) -> RunLogEntry:
    return RunLogEntry(
        workspace_id=row.workspace_id,
        run_id=row.run_id,
        seq=row.seq,
        run_version=row.run_version,
        log_version=row.log_version,
        kind=row.kind,
        actor_kind=row.actor_kind,
        body=row.body,
        created_at_us=row.created_at_us,
        audit_only=row.audit_only,
        actor_ref=row.actor_ref,
        activation_id=row.activation_id,
        node_id=row.node_id,
        scope_key=row.scope_key,
        idempotency_cksum=row.idempotency_cksum,
        body_ref=row.body_ref,
        view_patch=row.view_patch,
        view_patch_ref=row.view_patch_ref,
    )


def _to_run_spec(row: RunSpecRow, run: RunRow) -> RunStartSpec:
    return RunStartSpec(
        workflow_id=run.workflow_id,
        version_id=run.version_id,
        title=run.title,
        request_preview=row.request_preview,
        workspace_id=row.workspace_id,
        user_id=run.user_id,
        account_generation=run.account_generation,
        request_ref=row.request_ref,
        trigger_kind=row.trigger_kind,
        execution_target=row.execution_target,
        host_id=row.host_id,
        repository_id=row.repository_id,
        repo_path=row.repo_path,
        worktree_path=row.worktree_path,
        base_ref=row.base_ref,
        base_commit=row.base_commit,
        run_branch=row.run_branch,
        auth_mode=row.auth_mode,
        credential_ref=row.credential_ref,
        max_activations=row.max_activations,
        refresh_threshold_bp=row.refresh_threshold_bp,
        rejected_call_limit=row.rejected_call_limit,
        engine_version=run.engine_version,
        state_version=run.state_version,
        log_version=run.log_version,
        orchestrator_session_id=run.orchestrator_session_id,
        engine_config=row.engine_config,
    )


# Dialects whose transactions take SET LOCAL lock and statement timeouts.
_LOCK_TIMEOUT_DIALECTS = frozenset({"postgresql", "cockroachdb"})
_MIN_STATEMENT_TIMEOUT_MS = 1000


def _bound_lock_waits(session: Session, lock_timeout_s: float) -> None:
    """Bound this transaction's row-lock waits, and each statement at 1.5 times that (min 1 s)."""
    # At least 1 ms: 0 would turn both timeouts off.
    lock_ms = max(1, math.ceil(lock_timeout_s * 1000))
    # A statement needs real time to run even when lock waits are tiny.
    statement_ms = max(_MIN_STATEMENT_TIMEOUT_MS, lock_ms * 3 // 2)
    # SET takes no bind parameters; both values are ints computed here (milliseconds).
    session.execute(text(f"SET LOCAL lock_timeout = {lock_ms}"))
    session.execute(text(f"SET LOCAL statement_timeout = {statement_ms}"))


@dataclass(eq=False)
class _PostCommitHook:
    """One registration; its identity lets an unregister remove only itself."""

    callback: Callable[[str, int], None]


class PostCommitHooks:
    """Callbacks a run store calls after each committed transition, best effort.

    Thread-safe: a registration or unregister made while hooks run applies from
    the next commit on.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hooks: tuple[_PostCommitHook, ...] = ()

    def register(self, callback: Callable[[str, int], None]) -> Callable[[], None]:
        """Add *callback*; returns an idempotent unregister that removes only this registration."""
        hook = _PostCommitHook(callback)
        with self._lock:
            self._hooks = (*self._hooks, hook)

        def unregister() -> None:
            with self._lock:
                self._hooks = tuple(other for other in self._hooks if other is not hook)

        return unregister

    def run(self, run_id: str, version: int) -> None:
        """Call each callback with the committed run and version; a failing one is logged."""
        with self._lock:
            hooks = self._hooks
        for hook in hooks:
            try:
                hook.callback(run_id, version)
            except Exception:
                _logger.exception(
                    "Error executing post_commit hook for run %r version %r", run_id, version
                )


class SqlAlchemyCoralRunStore:
    """SQLAlchemy implementation of the Coral RunStore protocol."""

    def __init__(
        self,
        db_uri_or_engine: str | Engine,
        *,
        default_workspace_id: int | None = None,
    ) -> None:
        self._engine: Engine = (
            coral_engine(db_uri_or_engine)
            if isinstance(db_uri_or_engine, str)
            else db_uri_or_engine
        )
        self._default_workspace_id = default_workspace_id
        self._session = make_named_managed_session_maker(
            self._engine,
            query_name_prefix="coral.run_store",
        )
        self._write_session = make_named_managed_session_maker(
            self._engine,
            query_name_prefix="coral.run_store",
            immediate=True,
        )
        self._post_commit_hooks = PostCommitHooks()

    def _resolve_workspace_id(self, workspace_id: int | None) -> int:
        if workspace_id is not None:
            return workspace_id
        if self._default_workspace_id is not None:
            return self._default_workspace_id
        try:
            return current_workspace_id()
        except LookupError:
            return DEFAULT_WORKSPACE_ID

    def register_post_commit(self, callback: Callable[[str, int], None]) -> Callable[[], None]:
        """Register a callback invoked best-effort after each committed transition.

        ``start_run`` commits no transition and calls no callback.

        :returns: An idempotent unregister that removes only this registration.
        """
        return self._post_commit_hooks.register(callback)

    def start_run(
        self,
        spec: RunStartSpec,
        *,
        start_key: str | None = None,
        now: int | None = None,
    ) -> CoralRun:
        """Initiate a run idempotently via start_key or freshly via UUID4."""
        ws = self._resolve_workspace_id(spec.workspace_id)
        now_s = int(time.time()) if now is None else now
        spec_digest = _compute_spec_digest(spec)

        if start_key is not None:
            run_id = derived_id("coral-run", spec.user_id or "", start_key)
            with shared_read_scope(), self._session("start_run.check_existing") as session:
                existing_run = session.get(RunRow, (ws, run_id))
                if existing_run is not None:
                    existing_spec = session.get(RunSpecRow, (ws, run_id))
                    if existing_spec is not None:
                        stored_digest = _compute_stored_spec_digest(existing_run, existing_spec)
                        if stored_digest == spec_digest:
                            return _to_coral_run(existing_run)
                        raise StartKeyConflict(
                            f"Start key {start_key!r} already used for run {run_id!r} "
                            "with different spec"
                        )
        else:
            run_id = uuid.uuid4().hex

        run_row = RunRow(
            workspace_id=ws,
            id=run_id,
            workflow_id=spec.workflow_id,
            version_id=spec.version_id,
            user_id=spec.user_id,
            account_generation=spec.account_generation,
            status=int(RunStatus.STARTING),
            pause_reason=None,
            version=1,
            next_log_seq=1,
            activation_count=0,
            orchestrator_session_id=spec.orchestrator_session_id,
            title=spec.title,
            engine_version=spec.engine_version,
            state_version=spec.state_version,
            log_version=spec.log_version,
            created_at=now_s,
            updated_at=now_s,
            finished_at=None,
        )
        spec_row = RunSpecRow(
            workspace_id=ws,
            run_id=run_id,
            start_key=start_key,
            request_preview=spec.request_preview,
            request_ref=spec.request_ref,
            trigger_kind=spec.trigger_kind,
            execution_target=spec.execution_target,
            host_id=spec.host_id,
            repository_id=spec.repository_id,
            repo_path=spec.repo_path,
            worktree_path=spec.worktree_path,
            base_ref=spec.base_ref,
            base_commit=spec.base_commit,
            run_branch=spec.run_branch,
            auth_mode=spec.auth_mode,
            credential_ref=spec.credential_ref,
            max_activations=spec.max_activations,
            refresh_threshold_bp=spec.refresh_threshold_bp,
            rejected_call_limit=spec.rejected_call_limit,
            engine_config=spec.engine_config,
            created_at=now_s,
        )

        try:

            def _insert_run(session: Session) -> CoralRun:
                session.add(run_row)
                session.add(spec_row)
                session.flush()
                return _to_coral_run(run_row)

            return run_write_transaction(self._write_session, "start_run", _insert_run)
        except IntegrityError as exc:
            if start_key is not None:
                with shared_read_scope(), self._session("start_run.race_check") as session:
                    existing_run = session.get(RunRow, (ws, run_id))
                    existing_spec = session.get(RunSpecRow, (ws, run_id))
                    if existing_run is not None and existing_spec is not None:
                        stored_digest = _compute_stored_spec_digest(existing_run, existing_spec)
                        if stored_digest == spec_digest:
                            return _to_coral_run(existing_run)
                        raise StartKeyConflict(
                            f"Start key {start_key!r} already used for run {run_id!r} "
                            "with different spec"
                        ) from exc
            raise

    def load_run_state(
        self,
        run_id: str,
        *,
        workspace_id: int | None = None,
    ) -> tuple[RunState, int]:
        """Load the run aggregate state outside write locks under shared_read_scope."""
        ws = self._resolve_workspace_id(workspace_id)
        with shared_read_scope(), self._session("load_run_state") as session:
            run_row = session.get(RunRow, (ws, run_id))
            if run_row is None:
                raise RunNotFound(f"Run {run_id!r} not found in workspace {ws}")
            spec_row = session.get(RunSpecRow, (ws, run_id))
            if spec_row is None:
                raise RunNotFound(f"RunSpec for run {run_id!r} not found in workspace {ws}")

            activations = (
                session.execute(
                    select(ActivationRow)
                    .where(ActivationRow.workspace_id == ws, ActivationRow.run_id == run_id)
                    .order_by(asc(ActivationRow.created_at), asc(ActivationRow.id))
                )
                .scalars()
                .all()
            )

            join_arrivals = (
                session.execute(
                    select(JoinArrivalRow)
                    .where(JoinArrivalRow.workspace_id == ws, JoinArrivalRow.run_id == run_id)
                    .order_by(asc(JoinArrivalRow.arrived_at), asc(JoinArrivalRow.arrow_id))
                )
                .scalars()
                .all()
            )

            slots = (
                session.execute(
                    select(AgentSlotRow)
                    .where(AgentSlotRow.workspace_id == ws, AgentSlotRow.run_id == run_id)
                    .order_by(asc(AgentSlotRow.roster_index), asc(AgentSlotRow.id))
                )
                .scalars()
                .all()
            )

            handoffs = (
                session.execute(
                    select(HandoffRow)
                    .where(HandoffRow.workspace_id == ws, HandoffRow.run_id == run_id)
                    .order_by(asc(HandoffRow.submitted_at_us), asc(HandoffRow.id))
                )
                .scalars()
                .all()
            )

            handoff_items = (
                session.execute(
                    select(HandoffItemRow)
                    .where(HandoffItemRow.workspace_id == ws, HandoffItemRow.run_id == run_id)
                    .order_by(asc(HandoffItemRow.handoff_id), asc(HandoffItemRow.item_index))
                )
                .scalars()
                .all()
            )

            gates = (
                session.execute(
                    select(GateVisitRow)
                    .where(GateVisitRow.workspace_id == ws, GateVisitRow.run_id == run_id)
                    .order_by(asc(GateVisitRow.opened_at), asc(GateVisitRow.id))
                )
                .scalars()
                .all()
            )

            state = RunState(
                run=_to_coral_run(run_row),
                spec=_to_run_spec(spec_row, run_row),
                activations=tuple(_to_activation_state(r) for r in activations),
                join_arrivals=tuple(_to_join_arrival_state(r) for r in join_arrivals),
                agent_slots=tuple(_to_agent_slot_state(r) for r in slots),
                handoffs=tuple(_to_handoff_state(r) for r in handoffs),
                handoff_items=tuple(_to_handoff_item_state(r) for r in handoff_items),
                gate_visits=tuple(_to_gate_visit_state(r) for r in gates),
            )
            return state, run_row.version

    def apply_transition(
        self,
        run_id: str,
        expected_version: int,
        transition: Transition,
        *,
        workspace_id: int | None = None,
        now: int | None = None,
        lock_timeout_s: float | None = None,
    ) -> CommitOutcome:
        """Apply state mutations against run_id at expected_version atomically.

        :param lock_timeout_s: Bounds the wait for row locks on PostgreSQL and
            CockroachDB; MySQL keeps its lock wait timeout and SQLite its busy timeout.
        :raises IntegrityError: when ``transition.tool_reply`` repeats a stored
            checksum; nothing of the transition is written.
        """
        if lock_timeout_s is not None and lock_timeout_s <= 0:
            raise ValueError("lock_timeout_s must be positive")
        if len(transition.logs) > 64:
            raise TransitionTooLarge(f"Transition contains {len(transition.logs)} logs (limit 64)")
        if len(transition.outbox_work) > 64:
            raise TransitionTooLarge(
                f"Transition contains {len(transition.outbox_work)} outbox items (limit 64)"
            )

        ws = self._resolve_workspace_id(workspace_id)
        now_s = int(time.time()) if now is None else now
        now_us = now_s * 1_000_000

        dialect = self._engine.dialect.name

        def write(session: Session) -> CommitOutcome:
            if lock_timeout_s is not None and dialect in _LOCK_TIMEOUT_DIALECTS:
                _bound_lock_waits(session, lock_timeout_s)
            row = session.get(RunRow, (ws, run_id), with_for_update=True)
            if row is None:
                raise RunNotFound(f"Run {run_id!r} not found in workspace {ws}")
            if row.version != expected_version:
                raise RunVersionConflict(run_id, expected_version, row.version)

            new_version = row.version + 1
            row.version = new_version
            if transition.status is not None:
                row.status = transition.status
            if transition.clear_pause_reason:
                row.pause_reason = None
            elif transition.pause_reason is not None:
                row.pause_reason = transition.pause_reason
            if transition.orchestrator_session_id is not None:
                row.orchestrator_session_id = transition.orchestrator_session_id
            if transition.activation_count_delta != 0:
                row.activation_count += transition.activation_count_delta
            if transition.finished_at is not None:
                row.finished_at = transition.finished_at
            row.updated_at = now_s

            start_seq = row.next_log_seq
            assigned_seqs: list[int] = []
            receipt_obj: RunReceipt | None = None
            for i, log_draft in enumerate(transition.logs):
                seq = start_seq + i
                assigned_seqs.append(seq)
                log_created_at_us = log_draft.created_at_us or now_us
                log_row = RunLogRow(
                    workspace_id=ws,
                    run_id=run_id,
                    seq=seq,
                    run_version=new_version,
                    log_version=row.log_version,
                    kind=log_draft.kind,
                    audit_only=log_draft.audit_only,
                    actor_kind=log_draft.actor_kind,
                    actor_ref=log_draft.actor_ref,
                    activation_id=log_draft.activation_id,
                    node_id=log_draft.node_id,
                    scope_key=log_draft.scope_key,
                    idempotency_cksum=log_draft.idempotency_cksum,
                    body=log_draft.body,
                    body_ref=log_draft.body_ref,
                    view_patch=log_draft.view_patch,
                    view_patch_ref=log_draft.view_patch_ref,
                    created_at_us=log_created_at_us,
                )
                session.add(log_row)
                if log_draft.idempotency_cksum is not None and receipt_obj is None:
                    receipt_obj = RunReceipt(
                        workspace_id=ws,
                        run_id=run_id,
                        seq=seq,
                        run_version=new_version,
                        idempotency_cksum=log_draft.idempotency_cksum,
                        created_at_us=log_created_at_us,
                    )
            row.next_log_seq = start_seq + len(transition.logs)

            for act in transition.activations:
                existing_act = session.get(ActivationRow, (ws, run_id, act.id))
                act_created_at = act.created_at or (
                    existing_act.created_at if existing_act is not None else now_s
                )
                session.merge(
                    ActivationRow(
                        workspace_id=ws,
                        run_id=run_id,
                        id=act.id,
                        node_id=act.node_id,
                        scope_key=act.scope_key,
                        parent_activation_id=act.parent_activation_id,
                        status=act.status,
                        outcome=act.outcome,
                        attempt=act.attempt,
                        max_attempts=act.max_attempts,
                        chosen_label=act.chosen_label,
                        taken_over_by=act.taken_over_by,
                        start_commit=act.start_commit,
                        start_fingerprint=act.start_fingerprint,
                        items_total=act.items_total,
                        items_closed=act.items_closed,
                        created_at=act_created_at,
                        started_at=act.started_at,
                        closed_at=act.closed_at,
                        updated_at=act.updated_at or now_s,
                    )
                )

            for arr in transition.join_arrivals:
                existing_arr = session.get(
                    JoinArrivalRow, (ws, run_id, arr.activation_id, arr.arrow_id)
                )
                arr_arrived_at = arr.arrived_at or (
                    existing_arr.arrived_at if existing_arr is not None else now_s
                )
                session.merge(
                    JoinArrivalRow(
                        workspace_id=ws,
                        run_id=run_id,
                        activation_id=arr.activation_id,
                        arrow_id=arr.arrow_id,
                        source_activation_id=arr.source_activation_id,
                        outcome=arr.outcome,
                        arrived_at=arr_arrived_at,
                        handoff_id=arr.handoff_id,
                    )
                )

            for slot in transition.agent_slots:
                existing_slot = session.get(AgentSlotRow, (ws, run_id, slot.id))
                slot_created_at = slot.created_at or (
                    existing_slot.created_at if existing_slot is not None else now_s
                )
                session.merge(
                    AgentSlotRow(
                        workspace_id=ws,
                        run_id=run_id,
                        id=slot.id,
                        activation_id=slot.activation_id,
                        node_id=slot.node_id,
                        scope_key=slot.scope_key,
                        roster_index=slot.roster_index,
                        role=slot.role,
                        session_generation=slot.session_generation,
                        status=slot.status,
                        profile_revision_id=slot.profile_revision_id,
                        session_id=slot.session_id,
                        closing_code=slot.closing_code,
                        post_close_activity=slot.post_close_activity,
                        lease_expires_at=slot.lease_expires_at,
                        lease_holder=slot.lease_holder,
                        hold_seen_at=slot.hold_seen_at,
                        restart_attempt_id=slot.restart_attempt_id,
                        last_edge_status=slot.last_edge_status,
                        last_turn_outcome=slot.last_turn_outcome,
                        last_edge_at=slot.last_edge_at,
                        branch=slot.branch,
                        worktree_path=slot.worktree_path,
                        last_turn_origin=slot.last_turn_origin,
                        nudges=slot.nudges,
                        consecutive_rejections=slot.consecutive_rejections,
                        context_used_bp=slot.context_used_bp,
                        created_at=slot_created_at,
                        updated_at=slot.updated_at or now_s,
                    )
                )

            for hf in transition.handoffs:
                existing_hf = session.get(HandoffRow, (ws, run_id, hf.id))
                hf_submitted_at_us = hf.submitted_at_us or (
                    existing_hf.submitted_at_us if existing_hf is not None else now_us
                )
                session.merge(
                    HandoffRow(
                        workspace_id=ws,
                        run_id=run_id,
                        id=hf.id,
                        activation_id=hf.activation_id,
                        slot_id=hf.slot_id,
                        node_id=hf.node_id,
                        scope_key=hf.scope_key,
                        attempt=hf.attempt,
                        status=hf.status,
                        submit_status=hf.submit_status,
                        label=hf.label,
                        item_count=hf.item_count,
                        summary=hf.summary,
                        report_ref=hf.report_ref,
                        report_bytes=hf.report_bytes,
                        blocked_reason=hf.blocked_reason,
                        evidence_outcome=hf.evidence_outcome,
                        evidence_ref=hf.evidence_ref,
                        rejection_code=hf.rejection_code,
                        rejection_message=hf.rejection_message,
                        idempotency_cksum=hf.idempotency_cksum,
                        submitted_by_session_id=hf.submitted_by_session_id,
                        submitted_at_us=hf_submitted_at_us,
                    )
                )

            for itm in transition.handoff_items:
                session.merge(
                    HandoffItemRow(
                        workspace_id=ws,
                        run_id=run_id,
                        handoff_id=itm.handoff_id,
                        item_index=itm.item_index,
                        item_key=itm.item_key,
                        title=itm.title,
                        payload=itm.payload,
                        payload_ref=itm.payload_ref,
                    )
                )

            for gv in transition.gate_visits:
                existing_gv = session.get(GateVisitRow, (ws, run_id, gv.id))
                gv_opened_at = gv.opened_at or (
                    existing_gv.opened_at if existing_gv is not None else now_s
                )
                session.merge(
                    GateVisitRow(
                        workspace_id=ws,
                        run_id=run_id,
                        id=gv.id,
                        activation_id=gv.activation_id,
                        node_id=gv.node_id,
                        scope_key=gv.scope_key,
                        visit_no=gv.visit_no,
                        token=gv.token,
                        status=gv.status,
                        opened_at=gv_opened_at,
                        owner_user_id=gv.owner_user_id,
                        elicitation_id=gv.elicitation_id,
                        elicitation_session_id=gv.elicitation_session_id,
                        prompt_ref=gv.prompt_ref,
                        answer_label=gv.answer_label,
                        answered_by=gv.answered_by,
                        note=gv.note,
                        reminded_at=gv.reminded_at,
                        resolved_at=gv.resolved_at,
                    )
                )

            outbox_ids: list[str] = []
            for w in transition.outbox_work:
                outbox_ids.append(w.id)
                session.execute(
                    insert_pending_if_absent(
                        dialect, ws, w, run_id=run_id, available_at=w.available_at, now_us=now_us
                    )
                )

            if transition.consumed_work_ids:
                session.execute(
                    update(WorkRow)
                    .where(
                        WorkRow.workspace_id == ws,
                        WorkRow.run_id == run_id,
                        WorkRow.id.in_(transition.consumed_work_ids),
                    )
                    .values(
                        status=int(WorkStatus.SUCCEEDED),
                        finished_at=now_s,
                        lease_holder=None,
                        lease_expires_at=None,
                        held_since=None,
                    )
                )

            if transition.revive_work_ids:
                session.execute(
                    update(WorkRow)
                    .where(
                        WorkRow.workspace_id == ws,
                        WorkRow.run_id == run_id,
                        WorkRow.id.in_(transition.revive_work_ids),
                        WorkRow.status == int(WorkStatus.FAILED),
                    )
                    .values(**repended_values(now_s))
                )

            if transition.release_held_codes:
                session.execute(
                    update(WorkRow)
                    .where(
                        WorkRow.workspace_id == ws,
                        WorkRow.run_id == run_id,
                        WorkRow.status == int(WorkStatus.PENDING),
                        WorkRow.error_code.in_(transition.release_held_codes),
                    )
                    .values(available_at=now_s, held_since=None)
                )

            if transition.tool_reply is not None:
                # Last, so a repeated checksum fails after every other write and undoes it.
                session.add(
                    ToolReplyRow(
                        workspace_id=ws,
                        run_id=run_id,
                        cksum=transition.tool_reply.cksum,
                        reply=transition.tool_reply.reply,
                        run_version=new_version,
                        created_at_us=now_us,
                    )
                )
                session.flush()

            return CommitOutcome(
                run_id=run_id,
                version=new_version,
                applied=True,
                receipt=receipt_obj,
                work_ids=tuple(outbox_ids),
                log_seqs=tuple(assigned_seqs),
            )

        outcome = run_write_transaction(self._write_session, "apply_run_transition", write)

        self._post_commit_hooks.run(run_id, outcome.version)
        return outcome

    def get_run(
        self,
        run_id: str,
        *,
        workspace_id: int | None = None,
    ) -> CoralRun | None:
        """Fetch a single run by id."""
        ws = self._resolve_workspace_id(workspace_id)
        with shared_read_scope(), self._session("get_run") as session:
            row = session.get(RunRow, (ws, run_id))
            return _to_coral_run(row) if row is not None else None

    def list_runs(
        self,
        *,
        workspace_id: int | None = None,
        cursor: tuple[int, str] | None = None,
        limit: int = 100,
        descending: bool = True,
    ) -> list[CoralRun]:
        """List runs in a workspace using keyset pagination on (created_at, id)."""
        ws = self._resolve_workspace_id(workspace_id)
        dialect = self._engine.dialect.name
        with shared_read_scope(), self._session("list_runs") as session:
            stmt = select(RunRow).where(RunRow.workspace_id == ws)
            if cursor is not None:
                stmt = stmt.where(
                    keyset_after(
                        (RunRow.created_at, RunRow.id),
                        cursor,
                        descending=descending,
                        dialect_name=dialect,
                    )
                )
            order_cols = (
                (desc(RunRow.created_at), desc(RunRow.id))
                if descending
                else (asc(RunRow.created_at), asc(RunRow.id))
            )
            stmt = stmt.order_by(*order_cols).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [_to_coral_run(r) for r in rows]

    def read_log(
        self,
        run_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
        workspace_id: int | None = None,
    ) -> list[RunLogEntry]:
        """Read append-only event logs for a run starting after after_seq."""
        ws = self._resolve_workspace_id(workspace_id)
        with shared_read_scope(), self._session("read_log") as session:
            rows = (
                session.execute(
                    select(RunLogRow)
                    .where(
                        RunLogRow.workspace_id == ws,
                        RunLogRow.run_id == run_id,
                        RunLogRow.seq > after_seq,
                    )
                    .order_by(asc(RunLogRow.seq))
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [_to_run_log_entry(r) for r in rows]

    def find_receipt(
        self,
        run_id: str,
        idempotency_cksum: bytes,
        *,
        workspace_id: int | None = None,
    ) -> RunReceipt | None:
        """Find a durable command receipt by idempotency checksum."""
        ws = self._resolve_workspace_id(workspace_id)
        with shared_read_scope(), self._session("find_receipt") as session:
            row = session.execute(
                select(RunLogRow)
                .where(
                    RunLogRow.workspace_id == ws,
                    RunLogRow.run_id == run_id,
                    RunLogRow.idempotency_cksum == idempotency_cksum,
                )
                .limit(1)
            ).scalar_one_or_none()
            if row is None or row.idempotency_cksum is None:
                return None
            return RunReceipt(
                workspace_id=row.workspace_id,
                run_id=row.run_id,
                seq=row.seq,
                run_version=row.run_version,
                idempotency_cksum=row.idempotency_cksum,
                created_at_us=row.created_at_us,
            )

    def read_engine_log(
        self,
        run_id: str,
        *,
        workspace_id: int,
        after_seq: int = 0,
        max_run_version: int,
        limit: int = 500,
    ) -> list[RunLogEntry]:
        """Return the run's ENGINE rows after ``after_seq`` committed at or below
        ``max_run_version``, in ``seq`` order; audit-only rows included."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with shared_read_scope(), self._session("read_engine_log") as session:
            rows = session.scalars(
                select(RunLogRow)
                .where(
                    RunLogRow.workspace_id == workspace_id,
                    RunLogRow.run_id == run_id,
                    RunLogRow.kind == int(LogKind.ENGINE),
                    RunLogRow.seq > after_seq,
                    RunLogRow.run_version <= max_run_version,
                )
                .order_by(asc(RunLogRow.seq))
                .limit(limit)
            ).all()
            return [_to_run_log_entry(r) for r in rows]

    def find_tool_reply(self, run_id: str, cksum: bytes, *, workspace_id: int) -> str | None:
        """Return the reply a transition stored under ``cksum``, else ``None``."""
        require_checksum32(cksum)
        with shared_read_scope(), self._session("find_tool_reply") as session:
            row = session.get(ToolReplyRow, (workspace_id, run_id, cksum))
            return None if row is None else row.reply

    def list_active_runs_all_workspaces(
        self,
        *,
        cursor: tuple[int, str] | None = None,
        limit: int = 100,
    ) -> list[CoralRun]:
        """List runs across all workspaces in non-terminal states."""
        dialect = self._engine.dialect.name
        with shared_read_scope(), self._session("list_active_runs_all_workspaces") as session:
            stmt = select(RunRow).where(RunRow.status.in_(UNFINISHED_RUN_STATUSES))
            if cursor is not None:
                stmt = stmt.where(
                    keyset_after(
                        (RunRow.workspace_id, RunRow.id),
                        cursor,
                        descending=False,
                        dialect_name=dialect,
                    )
                )
            stmt = stmt.order_by(asc(RunRow.workspace_id), asc(RunRow.id)).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [_to_coral_run(r) for r in rows]

    def list_open_gates_all_workspaces(
        self,
        *,
        cursor: tuple[int, str, str] | None = None,
        limit: int = 100,
    ) -> list[GateVisitState]:
        """List open gates across all workspaces via keyset pagination."""
        dialect = self._engine.dialect.name
        with shared_read_scope(), self._session("list_open_gates_all_workspaces") as session:
            stmt = select(GateVisitRow).where(GateVisitRow.status == int(GateVisitStatus.OPEN))
            if cursor is not None:
                stmt = stmt.where(
                    keyset_after(
                        (GateVisitRow.workspace_id, GateVisitRow.run_id, GateVisitRow.id),
                        cursor,
                        descending=False,
                        dialect_name=dialect,
                    )
                )
            stmt = stmt.order_by(
                asc(GateVisitRow.workspace_id),
                asc(GateVisitRow.run_id),
                asc(GateVisitRow.id),
            ).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [_to_gate_visit_state(r) for r in rows]


__all__ = ["SqlAlchemyCoralRunStore"]
