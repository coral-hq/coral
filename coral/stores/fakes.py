"""In-memory fake implementations of RunStore and QueueStore for unit testing."""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import uuid
from collections.abc import Callable, Collection, Sequence
from typing import Any

from sqlalchemy.exc import IntegrityError

from coral.alerts.types import normalize_owner
from coral.db.enum_codecs import (
    AlertStatus,
    GateVisitStatus,
    LogKind,
    RunStatus,
    WorkKind,
    WorkStatus,
)
from coral.model.ids import derived_id
from coral.stores.alerts import check_alert_raises
from coral.stores.protocols import (
    UNFINISHED_RUN_STATUSES,
    ActivationState,
    AgentSlotState,
    AlertRecord,
    AlertResolution,
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
    WorkItem,
    WorkItemDraft,
    require_checksum32,
)
from coral.stores.runs import PostCommitHooks, _compute_spec_digest
from coral.stores.work_rows import FINISHED_WORK_STATUSES, MIN_HOLD_DELAY_S, repended_values


class FakeRunStore:
    """Thread-safe in-memory implementation of the RunStore protocol."""

    def __init__(self, *, default_workspace_id: int = 1) -> None:
        self._default_workspace_id = default_workspace_id
        self._lock = threading.RLock()
        self.runs: dict[tuple[int, str], CoralRun] = {}
        self.specs: dict[tuple[int, str], RunStartSpec] = {}
        self.activations: dict[tuple[int, str, str], ActivationState] = {}
        self.join_arrivals: dict[tuple[int, str, str, str], JoinArrivalState] = {}
        self.agent_slots: dict[tuple[int, str, str], AgentSlotState] = {}
        self.handoffs: dict[tuple[int, str, str], HandoffState] = {}
        self.handoff_items: dict[tuple[int, str, str, int], HandoffItemState] = {}
        self.gate_visits: dict[tuple[int, str, str], GateVisitState] = {}
        self.alerts: dict[tuple[int, str], AlertRecord] = {}
        self.logs: dict[tuple[int, str], list[RunLogEntry]] = {}
        self.work: dict[tuple[int, str], WorkItem] = {}
        self.tool_replies: dict[tuple[int, str, bytes], str] = {}
        self.post_commit_hooks = PostCommitHooks()
        self.before_apply_hook: Callable[[str, int], None] | None = None

    def _resolve_ws(self, ws: int | None) -> int:
        return ws if ws is not None else self._default_workspace_id

    def register_post_commit(self, callback: Callable[[str, int], None]) -> Callable[[], None]:
        return self.post_commit_hooks.register(callback)

    def start_run(
        self,
        spec: RunStartSpec,
        *,
        start_key: str | None = None,
        now: int | None = None,
    ) -> CoralRun:
        ws = self._resolve_ws(spec.workspace_id)
        now_s = int(time.time()) if now is None else now
        spec_digest = _compute_spec_digest(spec)

        with self._lock:
            if start_key is not None:
                run_id = derived_id("coral-run", spec.user_id or "", start_key)
                if (ws, run_id) in self.runs:
                    existing_spec = self.specs[(ws, run_id)]
                    if _compute_spec_digest(existing_spec) == spec_digest:
                        return self.runs[(ws, run_id)]
                    raise StartKeyConflict(
                        f"Start key {start_key!r} already used for run {run_id!r} "
                        "with different spec"
                    )
            else:
                run_id = uuid.uuid4().hex

            run = CoralRun(
                workspace_id=ws,
                id=run_id,
                workflow_id=spec.workflow_id,
                version_id=spec.version_id,
                status=int(RunStatus.STARTING),
                version=1,
                next_log_seq=1,
                activation_count=0,
                title=spec.title,
                engine_version=spec.engine_version,
                state_version=spec.state_version,
                log_version=spec.log_version,
                created_at=now_s,
                updated_at=now_s,
                user_id=spec.user_id,
                account_generation=spec.account_generation,
                pause_reason=None,
                orchestrator_session_id=spec.orchestrator_session_id,
                finished_at=None,
            )
            self.runs[(ws, run_id)] = run
            self.specs[(ws, run_id)] = spec
            self.logs[(ws, run_id)] = []
            return run

    def load_run_state(
        self,
        run_id: str,
        *,
        workspace_id: int | None = None,
    ) -> tuple[RunState, int]:
        ws = self._resolve_ws(workspace_id)
        with self._lock:
            if (ws, run_id) not in self.runs:
                raise RunNotFound(f"Run {run_id!r} not found in workspace {ws}")
            run = self.runs[(ws, run_id)]
            spec = self.specs[(ws, run_id)]

            acts = sorted(
                (v for (w, r, _), v in self.activations.items() if w == ws and r == run_id),
                key=lambda a: (a.created_at, a.id),
            )
            arrivals = sorted(
                (v for (w, r, _, _), v in self.join_arrivals.items() if w == ws and r == run_id),
                key=lambda j: (j.arrived_at, j.arrow_id),
            )
            slots = sorted(
                (v for (w, r, _), v in self.agent_slots.items() if w == ws and r == run_id),
                key=lambda s: (s.roster_index, s.id),
            )
            handoffs = sorted(
                (v for (w, r, _), v in self.handoffs.items() if w == ws and r == run_id),
                key=lambda h: (h.submitted_at_us, h.id),
            )
            items = sorted(
                (v for (w, r, _, _), v in self.handoff_items.items() if w == ws and r == run_id),
                key=lambda it: (it.handoff_id, it.item_index),
            )
            gates = sorted(
                (v for (w, r, _), v in self.gate_visits.items() if w == ws and r == run_id),
                key=lambda g: (g.opened_at, g.id),
            )

            state = RunState(
                run=run,
                spec=spec,
                activations=tuple(acts),
                join_arrivals=tuple(arrivals),
                agent_slots=tuple(slots),
                handoffs=tuple(handoffs),
                handoff_items=tuple(items),
                gate_visits=tuple(gates),
            )
            return state, run.version

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
        if lock_timeout_s is not None and lock_timeout_s <= 0:
            raise ValueError("lock_timeout_s must be positive")
        if len(transition.logs) > 64:
            raise TransitionTooLarge(f"Transition contains {len(transition.logs)} logs (limit 64)")
        if len(transition.outbox_work) > 64:
            raise TransitionTooLarge(
                f"Transition contains {len(transition.outbox_work)} outbox items (limit 64)"
            )
        check_alert_raises(run_id, transition.alert_raises)

        ws = self._resolve_ws(workspace_id)
        now_s = int(time.time()) if now is None else now
        now_us = now_s * 1_000_000

        with self._lock:
            if self.before_apply_hook is not None:
                hook = self.before_apply_hook
                self.before_apply_hook = None
                try:
                    hook(run_id, expected_version)
                finally:
                    self.before_apply_hook = hook

            if (ws, run_id) not in self.runs:
                raise RunNotFound(f"Run {run_id!r} not found in workspace {ws}")
            run = self.runs[(ws, run_id)]
            if run.version != expected_version:
                raise RunVersionConflict(run_id, expected_version, run.version)
            reply = transition.tool_reply
            if reply is not None and (ws, run_id, reply.cksum) in self.tool_replies:
                # As the primary key does in SQL: the whole transition is refused.
                raise IntegrityError(
                    "INSERT INTO coral_tool_replies", None, Exception("duplicate tool reply")
                )

            new_version = run.version + 1
            new_status = transition.status if transition.status is not None else run.status
            new_pause_reason = (
                None
                if transition.clear_pause_reason
                else (
                    transition.pause_reason
                    if transition.pause_reason is not None
                    else run.pause_reason
                )
            )
            new_session_id = (
                transition.orchestrator_session_id
                if transition.orchestrator_session_id is not None
                else run.orchestrator_session_id
            )
            new_act_count = run.activation_count + transition.activation_count_delta
            new_finished_at = (
                transition.finished_at if transition.finished_at is not None else run.finished_at
            )

            start_seq = run.next_log_seq
            assigned_seqs: list[int] = []
            receipt_obj: RunReceipt | None = None
            log_entries = self.logs.setdefault((ws, run_id), [])

            for i, draft in enumerate(transition.logs):
                seq = start_seq + i
                assigned_seqs.append(seq)
                entry_created_at_us = draft.created_at_us or now_us
                entry = RunLogEntry(
                    workspace_id=ws,
                    run_id=run_id,
                    seq=seq,
                    run_version=new_version,
                    log_version=run.log_version,
                    kind=draft.kind,
                    actor_kind=draft.actor_kind,
                    body=draft.body,
                    created_at_us=entry_created_at_us,
                    audit_only=draft.audit_only,
                    actor_ref=draft.actor_ref,
                    activation_id=draft.activation_id,
                    node_id=draft.node_id,
                    scope_key=draft.scope_key,
                    idempotency_cksum=draft.idempotency_cksum,
                    body_ref=draft.body_ref,
                    view_patch=draft.view_patch,
                    view_patch_ref=draft.view_patch_ref,
                )
                log_entries.append(entry)
                if draft.idempotency_cksum is not None and receipt_obj is None:
                    receipt_obj = RunReceipt(
                        workspace_id=ws,
                        run_id=run_id,
                        seq=seq,
                        run_version=new_version,
                        idempotency_cksum=draft.idempotency_cksum,
                        created_at_us=entry_created_at_us,
                    )

            updated_run = CoralRun(
                workspace_id=ws,
                id=run_id,
                workflow_id=run.workflow_id,
                version_id=run.version_id,
                status=new_status,
                version=new_version,
                next_log_seq=start_seq + len(transition.logs),
                activation_count=new_act_count,
                title=run.title,
                engine_version=run.engine_version,
                state_version=run.state_version,
                log_version=run.log_version,
                created_at=run.created_at,
                updated_at=now_s,
                user_id=run.user_id,
                account_generation=run.account_generation,
                pause_reason=new_pause_reason,
                orchestrator_session_id=new_session_id,
                finished_at=new_finished_at,
            )
            self.runs[(ws, run_id)] = updated_run

            for act in transition.activations:
                existing_act = self.activations.get((ws, run_id, act.id))
                act_created_at = act.created_at or (
                    existing_act.created_at if existing_act is not None else now_s
                )
                self.activations[(ws, run_id, act.id)] = ActivationState(
                    workspace_id=ws,
                    run_id=run_id,
                    id=act.id,
                    node_id=act.node_id,
                    scope_key=act.scope_key,
                    status=act.status,
                    attempt=act.attempt,
                    max_attempts=act.max_attempts,
                    created_at=act_created_at,
                    updated_at=act.updated_at or now_s,
                    parent_activation_id=act.parent_activation_id,
                    outcome=act.outcome,
                    chosen_label=act.chosen_label,
                    taken_over_by=act.taken_over_by,
                    start_commit=act.start_commit,
                    start_fingerprint=act.start_fingerprint,
                    items_total=act.items_total,
                    items_closed=act.items_closed,
                    started_at=act.started_at,
                    closed_at=act.closed_at,
                )

            for arr in transition.join_arrivals:
                arr_key = (ws, run_id, arr.activation_id, arr.arrow_id)
                existing_arr = self.join_arrivals.get(arr_key)
                arr_arrived_at = arr.arrived_at or (
                    existing_arr.arrived_at if existing_arr is not None else now_s
                )
                self.join_arrivals[arr_key] = JoinArrivalState(
                    workspace_id=ws,
                    run_id=run_id,
                    activation_id=arr.activation_id,
                    arrow_id=arr.arrow_id,
                    source_activation_id=arr.source_activation_id,
                    outcome=arr.outcome,
                    arrived_at=arr_arrived_at,
                    handoff_id=arr.handoff_id,
                )

            for slot in transition.agent_slots:
                existing_slot = self.agent_slots.get((ws, run_id, slot.id))
                slot_created_at = slot.created_at or (
                    existing_slot.created_at if existing_slot is not None else now_s
                )
                self.agent_slots[(ws, run_id, slot.id)] = AgentSlotState(
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
                    post_close_activity=slot.post_close_activity,
                    nudges=slot.nudges,
                    consecutive_rejections=slot.consecutive_rejections,
                    created_at=slot_created_at,
                    updated_at=slot.updated_at or now_s,
                    profile_revision_id=slot.profile_revision_id,
                    session_id=slot.session_id,
                    closing_code=slot.closing_code,
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
                    context_used_bp=slot.context_used_bp,
                )

            for hf in transition.handoffs:
                existing_hf = self.handoffs.get((ws, run_id, hf.id))
                hf_submitted_at_us = hf.submitted_at_us or (
                    existing_hf.submitted_at_us if existing_hf is not None else now_us
                )
                self.handoffs[(ws, run_id, hf.id)] = HandoffState(
                    workspace_id=ws,
                    run_id=run_id,
                    id=hf.id,
                    activation_id=hf.activation_id,
                    node_id=hf.node_id,
                    scope_key=hf.scope_key,
                    attempt=hf.attempt,
                    status=hf.status,
                    submit_status=hf.submit_status,
                    idempotency_cksum=hf.idempotency_cksum,
                    submitted_at_us=hf_submitted_at_us,
                    slot_id=hf.slot_id,
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
                    submitted_by_session_id=hf.submitted_by_session_id,
                )

            for itm in transition.handoff_items:
                item_key = (ws, run_id, itm.handoff_id, itm.item_index)
                self.handoff_items[item_key] = HandoffItemState(
                    workspace_id=ws,
                    run_id=run_id,
                    handoff_id=itm.handoff_id,
                    item_index=itm.item_index,
                    item_key=itm.item_key,
                    title=itm.title,
                    payload=itm.payload,
                    payload_ref=itm.payload_ref,
                )

            for gv in transition.gate_visits:
                existing_gv = self.gate_visits.get((ws, run_id, gv.id))
                gv_opened_at = gv.opened_at or (
                    existing_gv.opened_at if existing_gv is not None else now_s
                )
                self.gate_visits[(ws, run_id, gv.id)] = GateVisitState(
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

            # As the SQL store: raises insert absent ids, then resolutions.
            for draft in transition.alert_raises:
                if (ws, draft.id) not in self.alerts:
                    self.alerts[(ws, draft.id)] = AlertRecord(
                        workspace_id=ws,
                        id=draft.id,
                        run_id=draft.run_id,
                        owner_user_id=normalize_owner(draft.owner_user_id),
                        account_generation=draft.account_generation,
                        kind=draft.kind,
                        priority=draft.priority,
                        subject_id=draft.subject_id,
                        status=int(AlertStatus.OPEN),
                        payload=draft.payload,
                        created_at=draft.created_at or now_s,
                    )
            for key, alert in list(self.alerts.items()):
                if (
                    key[0] == ws
                    and alert.run_id == run_id
                    and alert.status != int(AlertStatus.RESOLVED)
                    and any(
                        _resolves(resolution, alert) for resolution in transition.alert_resolutions
                    )
                ):
                    self.alerts[key] = dataclasses.replace(
                        alert, status=int(AlertStatus.RESOLVED), resolved_at=now_s
                    )

            outbox_ids: list[str] = []
            for w in transition.outbox_work:
                outbox_ids.append(w.id)
                existing = any(
                    item.workspace_id == ws
                    and item.run_id == run_id
                    and item.idempotency_cksum == w.idempotency_cksum
                    for item in self.work.values()
                )
                if not existing:
                    self.work[(ws, w.id)] = WorkItem(
                        workspace_id=ws,
                        id=w.id,
                        run_id=run_id,
                        kind=w.kind,
                        status=int(WorkStatus.PENDING),
                        payload=w.payload,
                        idempotency_cksum=w.idempotency_cksum,
                        available_at=w.available_at,
                        created_at_us=now_us,
                        attempts=0,
                        node_id=w.node_id,
                        scope_key=w.scope_key,
                        slot_generation=w.slot_generation,
                        owner_key=w.owner_key,
                        lease_expires_at=None,
                        lease_holder=None,
                        result=None,
                        result_ref=None,
                        error_code=None,
                        finished_at=None,
                    )

            for work_id in transition.consumed_work_ids:
                consumed = self.work.get((ws, work_id))
                if consumed is not None and consumed.run_id == run_id:
                    self.work[(ws, work_id)] = dataclasses.replace(
                        consumed,
                        status=int(WorkStatus.SUCCEEDED),
                        lease_expires_at=None,
                        lease_holder=None,
                        finished_at=now_s,
                        held_since=None,
                    )

            for work_id in transition.revive_work_ids:
                failed = self.work.get((ws, work_id))
                if (
                    failed is not None
                    and failed.run_id == run_id
                    and failed.status == int(WorkStatus.FAILED)
                ):
                    self.work[(ws, work_id)] = dataclasses.replace(
                        failed, **repended_values(now_s)
                    )

            if transition.release_held_codes:
                for key, held in list(self.work.items()):
                    if (
                        key[0] == ws
                        and held.run_id == run_id
                        and held.status == int(WorkStatus.PENDING)
                        and held.error_code in transition.release_held_codes
                    ):
                        self.work[key] = dataclasses.replace(
                            held, available_at=now_s, held_since=None
                        )

            if reply is not None:
                self.tool_replies[(ws, run_id, reply.cksum)] = reply.reply

            outcome = CommitOutcome(
                run_id=run_id,
                version=new_version,
                applied=True,
                receipt=receipt_obj,
                work_ids=tuple(outbox_ids),
                log_seqs=tuple(assigned_seqs),
            )

        self.post_commit_hooks.run(run_id, outcome.version)
        return outcome

    def get_run(
        self,
        run_id: str,
        *,
        workspace_id: int | None = None,
    ) -> CoralRun | None:
        ws = self._resolve_ws(workspace_id)
        with self._lock:
            return self.runs.get((ws, run_id))

    def list_runs(
        self,
        *,
        workspace_id: int | None = None,
        cursor: tuple[int, str] | None = None,
        limit: int = 100,
        descending: bool = True,
    ) -> list[CoralRun]:
        ws = self._resolve_ws(workspace_id)
        with self._lock:
            all_runs = [r for (w, _), r in self.runs.items() if w == ws]
            all_runs.sort(
                key=lambda r: (r.created_at, r.id),
                reverse=descending,
            )
            if cursor is not None:
                c_created, c_id = cursor
                if descending:
                    all_runs = [r for r in all_runs if (r.created_at, r.id) < (c_created, c_id)]
                else:
                    all_runs = [r for r in all_runs if (r.created_at, r.id) > (c_created, c_id)]
            return all_runs[:limit]

    def read_log(
        self,
        run_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
        workspace_id: int | None = None,
    ) -> list[RunLogEntry]:
        ws = self._resolve_ws(workspace_id)
        with self._lock:
            entries = self.logs.get((ws, run_id), [])
            filtered = [e for e in entries if e.seq > after_seq]
            filtered.sort(key=lambda e: e.seq)
            return filtered[:limit]

    def find_receipt(
        self,
        run_id: str,
        idempotency_cksum: bytes,
        *,
        workspace_id: int | None = None,
    ) -> RunReceipt | None:
        ws = self._resolve_ws(workspace_id)
        with self._lock:
            entries = self.logs.get((ws, run_id), [])
            for e in entries:
                if e.idempotency_cksum is not None and e.idempotency_cksum == idempotency_cksum:
                    return RunReceipt(
                        workspace_id=e.workspace_id,
                        run_id=e.run_id,
                        seq=e.seq,
                        run_version=e.run_version,
                        idempotency_cksum=e.idempotency_cksum,
                        created_at_us=e.created_at_us,
                    )
            return None

    def read_engine_log(
        self,
        run_id: str,
        *,
        workspace_id: int,
        after_seq: int = 0,
        max_run_version: int,
        limit: int = 500,
    ) -> list[RunLogEntry]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        with self._lock:
            entries = sorted(
                (
                    entry
                    for entry in self.logs.get((workspace_id, run_id), [])
                    if entry.kind == int(LogKind.ENGINE)
                    and entry.seq > after_seq
                    and entry.run_version <= max_run_version
                ),
                key=lambda entry: entry.seq,
            )
            return entries[:limit]

    def find_tool_reply(self, run_id: str, cksum: bytes, *, workspace_id: int) -> str | None:
        require_checksum32(cksum)
        with self._lock:
            return self.tool_replies.get((workspace_id, run_id, cksum))

    def list_active_runs_all_workspaces(
        self,
        *,
        cursor: tuple[int, str] | None = None,
        limit: int = 100,
    ) -> list[CoralRun]:
        with self._lock:
            active = [r for r in self.runs.values() if r.status in UNFINISHED_RUN_STATUSES]
            active.sort(key=lambda r: (r.workspace_id, r.id))
            if cursor is not None:
                active = [r for r in active if (r.workspace_id, r.id) > cursor]
            return active[:limit]

    def list_alerts(self, run_id: str, *, workspace_id: int | None = None) -> list[AlertRecord]:
        """Every alert of the run, oldest first, as ``SqlAlchemyAlertStore.list_for_run``."""
        ws = self._resolve_ws(workspace_id)
        with self._lock:
            return sorted(
                (a for (w, _), a in self.alerts.items() if w == ws and a.run_id == run_id),
                key=lambda a: (a.created_at, a.id),
            )

    def list_open_gates_all_workspaces(
        self,
        *,
        cursor: tuple[int, str, str] | None = None,
        limit: int = 100,
    ) -> list[GateVisitState]:
        with self._lock:
            open_gates = [
                g for g in self.gate_visits.values() if g.status == int(GateVisitStatus.OPEN)
            ]
            open_gates.sort(key=lambda g: (g.workspace_id, g.run_id, g.id))
            if cursor is not None:
                open_gates = [g for g in open_gates if (g.workspace_id, g.run_id, g.id) > cursor]
            return open_gates[:limit]


def _resolves(resolution: AlertResolution, alert: AlertRecord) -> bool:
    if resolution.subject_id is not None:
        return alert.subject_id == resolution.subject_id
    return alert.kind in resolution.kinds


class FakeQueueStore:
    """Thread-safe in-memory implementation of the QueueStore protocol."""

    def __init__(
        self,
        *,
        default_workspace_id: int = 1,
        run_store: FakeRunStore | None = None,
    ) -> None:
        self._default_workspace_id = default_workspace_id
        self._run_store = run_store
        self._lock = run_store._lock if run_store is not None else threading.RLock()
        self.work: dict[tuple[int, str], WorkItem] = (
            run_store.work if run_store is not None else {}
        )
        self.worker_leases: dict[str, tuple[str, int, int]] = {}
        self.run_statuses: dict[tuple[int, str], int] = {}
        self.slot_generations: dict[tuple[int, str, str], int] = {}

    def _resolve_ws(self, ws: int | None) -> int:
        return ws if ws is not None else self._default_workspace_id

    def enqueue_work(
        self,
        items: Sequence[WorkItemDraft],
        *,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[str]:
        ws = self._resolve_ws(workspace_id)
        now_s = int(time.time()) if now is None else now
        now_us = now_s * 1_000_000
        enqueued: list[str] = []

        with self._lock:
            for item in items:
                enqueued.append(item.id)
                exists = any(
                    w.workspace_id == ws
                    and w.run_id == item.run_id
                    and w.idempotency_cksum == item.idempotency_cksum
                    for w in self.work.values()
                )
                if not exists:
                    self.work[(ws, item.id)] = WorkItem(
                        workspace_id=ws,
                        id=item.id,
                        run_id=item.run_id,
                        kind=item.kind,
                        status=int(WorkStatus.PENDING),
                        payload=item.payload,
                        idempotency_cksum=item.idempotency_cksum,
                        available_at=item.available_at,
                        created_at_us=now_us,
                        attempts=0,
                        node_id=item.node_id,
                        scope_key=item.scope_key,
                        slot_generation=item.slot_generation,
                        owner_key=item.owner_key,
                        lease_expires_at=None,
                        lease_holder=None,
                        result=None,
                        result_ref=None,
                        error_code=None,
                        finished_at=None,
                    )
        return enqueued

    def claim_work(
        self,
        worker_id: str,
        *,
        kinds: Sequence[int] = (int(WorkKind.EFFECT),),
        lease_seconds: int = 60,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
        exclude_run_ids: Collection[str] = (),
    ) -> WorkItem | None:
        clock = now_fn or time.time
        now_s = int(clock())
        kinds_set = set(kinds)
        excluded = set(exclude_run_ids)

        with self._lock:
            for key, item in sorted(
                self.work.items(), key=lambda kv: (kv[1].available_at, kv[1].id)
            ):
                ws, _ = key
                if workspace_id is not None and ws != workspace_id:
                    continue
                if (
                    item.status == int(WorkStatus.PENDING)
                    and item.kind in kinds_set
                    and item.available_at <= now_s
                    and item.run_id not in excluded
                ):
                    claimed = dataclasses.replace(
                        item,
                        status=int(WorkStatus.CLAIMED),
                        attempts=item.attempts + 1,
                        lease_expires_at=now_s + lease_seconds,
                        lease_holder=worker_id,
                    )
                    self.work[key] = claimed
                    return claimed
            return None

    def renew_lease(
        self,
        work_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 60,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> bool:
        clock = now_fn or time.time
        now_s = int(clock())
        ws = self._resolve_ws(workspace_id)

        with self._lock:
            key = (ws, work_id)
            if key not in self.work:
                return False
            item = self.work[key]
            if (
                item.status != int(WorkStatus.CLAIMED)
                or item.lease_holder != worker_id
                or (item.lease_expires_at is not None and item.lease_expires_at <= now_s)
            ):
                return False
            self.work[key] = dataclasses.replace(item, lease_expires_at=now_s + lease_seconds)
            return True

    def finish_work(
        self,
        work_id: str,
        *,
        worker_id: str,
        expected_lease_expires_at: int,
        status: int,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        next_available_at: int | None = None,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
        hold: bool = False,
    ) -> bool:
        if hold and int(status) != int(WorkStatus.PENDING):
            raise ValueError("a hold re-pends the item: status must be PENDING")
        clock = now_fn or time.time
        now_s = int(clock())
        ws = self._resolve_ws(workspace_id)

        with self._lock:
            key = (ws, work_id)
            if key not in self.work:
                return False
            item = self.work[key]
            if (
                item.status != int(WorkStatus.CLAIMED)
                or item.lease_holder != worker_id
                or item.lease_expires_at != expected_lease_expires_at
            ):
                return False

            res_str = json.dumps(result, sort_keys=True) if result is not None else None
            avail_at = next_available_at if next_available_at is not None else item.available_at
            repended = int(status) == int(WorkStatus.PENDING)
            held_since = None if not repended else item.held_since
            if hold:
                avail_at = max(avail_at, now_s + MIN_HOLD_DELAY_S)
                held_since = now_s if held_since is None else held_since
            self.work[key] = dataclasses.replace(
                item,
                status=status,
                available_at=avail_at,
                attempts=max(item.attempts - 1, 0) if hold else item.attempts,
                lease_expires_at=None,
                lease_holder=None,
                result=res_str,
                error_code=error_code,
                finished_at=None if repended else now_s,
                held_since=held_since,
            )
            return True

    def get_work(self, work_ids: Sequence[str], *, workspace_id: int) -> list[WorkItem]:
        wanted = set(work_ids)
        with self._lock:
            found = [
                item
                for (ws, work_id), item in self.work.items()
                if ws == workspace_id and work_id in wanted
            ]
        return sorted(found, key=lambda item: item.id)

    def has_held_work(self, run_id: str, codes: Sequence[str], *, workspace_id: int) -> bool:
        wanted = set(codes)
        with self._lock:
            return any(
                ws == workspace_id
                and item.run_id == run_id
                and item.status == int(WorkStatus.PENDING)
                and item.held_since is not None
                and item.error_code in wanted
                for (ws, _), item in self.work.items()
            )

    def reschedule_work(
        self, draft: WorkItemDraft, *, workspace_id: int, available_at: int
    ) -> None:
        if int(draft.kind) == int(WorkKind.EFFECT):
            raise ValueError("reschedule_work takes signal and timer rows, not effects")
        with self._lock:
            existing = next(
                (
                    (key, item)
                    for key, item in self.work.items()
                    if key[0] == workspace_id
                    and item.run_id == draft.run_id
                    and item.idempotency_cksum == draft.idempotency_cksum
                ),
                None,
            )
            if existing is None:
                self.enqueue_work(
                    [dataclasses.replace(draft, available_at=available_at)],
                    workspace_id=workspace_id,
                )
                return
            key, item = existing
            if item.status == int(WorkStatus.PENDING):
                self.work[key] = dataclasses.replace(
                    item, available_at=min(item.available_at, available_at)
                )
            elif item.status in FINISHED_WORK_STATUSES:
                self.work[key] = dataclasses.replace(item, **repended_values(available_at))

    def purge_finished(
        self, *, kinds: Sequence[int], finished_before: int, limit: int = 500
    ) -> int:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        kind_vals = {int(kind) for kind in kinds}
        if int(WorkKind.EFFECT) in kind_vals:
            raise ValueError("purge_finished keeps effect rows")
        with self._lock:
            purgeable = sorted(
                (
                    (item.finished_at or 0, key)
                    for key, item in self.work.items()
                    if item.status in FINISHED_WORK_STATUSES
                    and item.kind in kind_vals
                    and item.finished_at is not None
                    and item.finished_at < finished_before
                ),
            )[:limit]
            for _, key in purgeable:
                del self.work[key]
            return len(purgeable)

    def reclaim_expired_work(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> int:
        clock = now_fn or time.time
        now_s = int(clock())
        reclaimed = 0

        with self._lock:
            for key, item in self.work.items():
                ws, _ = key
                if workspace_id is not None and ws != workspace_id:
                    continue
                if (
                    item.status == int(WorkStatus.CLAIMED)
                    and item.lease_expires_at is not None
                    and item.lease_expires_at <= now_s
                ):
                    self.work[key] = dataclasses.replace(
                        item,
                        status=int(WorkStatus.PENDING),
                        lease_expires_at=None,
                        lease_holder=None,
                    )
                    reclaimed += 1
                    if reclaimed >= limit:
                        break
        return reclaimed

    def discover_ready_signals(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[WorkItem]:
        now_s = int(time.time()) if now is None else now
        with self._lock:
            items = [
                w
                for (ws, _), w in self.work.items()
                if (workspace_id is None or ws == workspace_id)
                and w.status == int(WorkStatus.PENDING)
                and w.kind == int(WorkKind.SIGNAL)
                and w.available_at <= now_s
            ]
            items.sort(key=lambda w: (w.available_at, w.id))
            return items[:limit]

    def discover_due_timers(
        self,
        *,
        now: int,
        limit: int = 100,
        workspace_id: int | None = None,
    ) -> list[WorkItem]:
        with self._lock:
            items = [
                w
                for (ws, _), w in self.work.items()
                if (workspace_id is None or ws == workspace_id)
                and w.status == int(WorkStatus.PENDING)
                and w.kind == int(WorkKind.TIMER)
                and w.available_at <= now
            ]
            items.sort(key=lambda w: (w.available_at, w.id))
            return items[:limit]

    def discover_ready_effects(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[WorkItem]:
        now_s = int(time.time()) if now is None else now
        with self._lock:
            items = [
                w
                for (ws, _), w in self.work.items()
                if (workspace_id is None or ws == workspace_id)
                and w.status == int(WorkStatus.PENDING)
                and w.kind == int(WorkKind.EFFECT)
                and w.available_at <= now_s
            ]
            items.sort(key=lambda w: (w.available_at, w.id))
            return items[:limit]

    def discover_expired_effects(
        self,
        *,
        limit: int = 100,
        workspace_id: int | None = None,
        now: int | None = None,
    ) -> list[WorkItem]:
        now_s = int(time.time()) if now is None else now
        with self._lock:
            items = [
                w
                for (ws, _), w in self.work.items()
                if (workspace_id is None or ws == workspace_id)
                and w.status == int(WorkStatus.CLAIMED)
                and w.kind == int(WorkKind.EFFECT)
                and w.lease_expires_at is not None
                and w.lease_expires_at <= now_s
            ]
            items.sort(key=lambda w: (w.available_at, w.id))
            return items[:limit]

    def get_run_status(
        self,
        run_id: str,
        *,
        workspace_id: int | None = None,
    ) -> int | None:
        ws = self._resolve_ws(workspace_id)
        with self._lock:
            if (ws, run_id) in self.run_statuses:
                return self.run_statuses[(ws, run_id)]
            if self._run_store is not None and (ws, run_id) in self._run_store.runs:
                return self._run_store.runs[(ws, run_id)].status
            return None

    def get_slot_generation(
        self,
        run_id: str,
        slot_id: str,
        *,
        workspace_id: int | None = None,
    ) -> int | None:
        ws = self._resolve_ws(workspace_id)
        with self._lock:
            if (ws, run_id, slot_id) in self.slot_generations:
                return self.slot_generations[(ws, run_id, slot_id)]
            if (
                self._run_store is not None
                and (ws, run_id, slot_id) in self._run_store.agent_slots
            ):
                return self._run_store.agent_slots[(ws, run_id, slot_id)].session_generation
            return None

    def acquire_worker_lease(
        self,
        name: str,
        worker_id: str,
        *,
        lease_seconds: int = 120,
        now_fn: Callable[[], float] | None = None,
    ) -> bool:
        clock = now_fn or time.time
        now_s = int(clock())
        with self._lock:
            if name in self.worker_leases:
                holder, _, expires = self.worker_leases[name]
                if expires > now_s and holder != worker_id:
                    return False
            self.worker_leases[name] = (worker_id, now_s, now_s + lease_seconds)
            return True

    def renew_worker_lease(
        self,
        name: str,
        worker_id: str,
        *,
        lease_seconds: int = 120,
        now_fn: Callable[[], float] | None = None,
    ) -> bool:
        clock = now_fn or time.time
        now_s = int(clock())
        with self._lock:
            if name not in self.worker_leases:
                return False
            holder, _, expires = self.worker_leases[name]
            if holder != worker_id or expires <= now_s:
                return False
            self.worker_leases[name] = (worker_id, now_s, now_s + lease_seconds)
            return True

    def release_worker_lease(
        self,
        name: str,
        worker_id: str,
    ) -> bool:
        with self._lock:
            if name in self.worker_leases:
                holder, _, _ = self.worker_leases[name]
                if holder == worker_id:
                    del self.worker_leases[name]
                    return True
            return False


__all__ = ["FakeQueueStore", "FakeRunStore"]
