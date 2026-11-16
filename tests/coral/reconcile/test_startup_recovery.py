"""Tests for startup_recovery_sweep across multiple workspaces, expired work, and open gates."""

from __future__ import annotations

from coral.db.enum_codecs import GateVisitStatus, RunStatus, WorkStatus
from coral.reconcile import StartupReport, startup_recovery_sweep
from coral.stores.fakes import FakeQueueStore, FakeRunStore
from coral.stores.protocols import (
    CoralRun,
    GateVisitDraft,
    GateVisitState,
    RunStartSpec,
    Transition,
    WorkItemDraft,
)


async def test_startup_recovery_sweep_reclaims_work_and_isolates_hook_errors() -> None:
    """Verify startup_recovery_sweep reclaims expired work and continues when one hook raises."""
    run_store = FakeRunStore(default_workspace_id=1)
    queue_store = FakeQueueStore(run_store=run_store, default_workspace_id=1)

    # Create active runs in workspace 1 and workspace 2, plus a COMPLETED run in workspace 1
    r1 = run_store.start_run(
        RunStartSpec(
            workflow_id="wf_1",
            version_id="v1",
            title="Active WS1",
            request_preview="req",
            workspace_id=1,
            user_id="alice",
            account_generation="gen_a",
        ),
        now=100,
    )
    run_store.apply_transition(
        r1.id,
        1,
        Transition(
            status=int(RunStatus.PAUSED),
            gate_visits=(
                GateVisitDraft(
                    id="gv_1",
                    activation_id="act_1",
                    node_id="gate_node",
                    scope_key="root",
                    visit_no=1,
                    token="tok_1",
                    status=int(GateVisitStatus.OPEN),
                    owner_user_id="alice",
                    opened_at=105,
                ),
            ),
        ),
        workspace_id=1,
        now=105,
    )

    r2 = run_store.start_run(
        RunStartSpec(
            workflow_id="wf_2",
            version_id="v1",
            title="Active WS2",
            request_preview="req2",
            workspace_id=2,
            user_id="bob",
            account_generation="gen_b",
        ),
        now=100,
    )
    run_store.apply_transition(
        r2.id,
        1,
        Transition(
            status=int(RunStatus.RUNNING),
            gate_visits=(
                GateVisitDraft(
                    id="gv_2",
                    activation_id="act_2",
                    node_id="gate_node",
                    scope_key="root",
                    visit_no=1,
                    token="tok_2",
                    status=int(GateVisitStatus.OPEN),
                    owner_user_id="bob",
                    opened_at=106,
                ),
            ),
        ),
        workspace_id=2,
        now=106,
    )

    r_done = run_store.start_run(
        RunStartSpec(
            workflow_id="wf_1",
            version_id="v1",
            title="Completed WS1",
            request_preview="req3",
            workspace_id=1,
        ),
        now=100,
    )
    run_store.apply_transition(
        r_done.id,
        1,
        Transition(status=int(RunStatus.COMPLETED), finished_at=110),
        workspace_id=1,
        now=110,
    )

    # Enqueue and claim an effect whose lease expires before sweep at t=500
    w_exp = WorkItemDraft.effect(
        run_id=r1.id,
        idempotency_key="eff:exp",
        payload={"effect_type": "git.prepare"},
        available_at=100,
    )
    queue_store.enqueue_work([w_exp], workspace_id=1, now=100)
    claimed = queue_store.claim_work(
        "crashed-worker",
        workspace_id=1,
        lease_seconds=60,
        now_fn=lambda: 100.0,
    )
    assert claimed is not None
    assert claimed.status == int(WorkStatus.CLAIMED)

    republished_gates: list[str] = []
    reconciled_runs: list[str] = []

    async def _gate_hook(gate: GateVisitState) -> None:
        if gate.id == "gv_1":
            raise RuntimeError("transient elicitation error on gv_1")
        republished_gates.append(gate.id)

    async def _run_hook(run: CoralRun) -> None:
        if run.id == r1.id:
            raise ValueError("transient reducer error on r1")
        reconciled_runs.append(run.id)

    report: StartupReport = await startup_recovery_sweep(
        run_store,
        queue_store,
        gate_republisher=_gate_hook,
        run_reconciler=_run_hook,
        page_size=1,
        clock=lambda: 500.0,
    )

    assert report.reclaimed_work == 1
    assert report.open_gates_scanned == 2
    assert report.open_gates_republished == 1
    assert report.active_runs_scanned == 2
    assert report.active_runs_reconciled == 1
    assert report.errors == 2
    assert republished_gates == ["gv_2"]
    assert reconciled_runs == [r2.id]

    # Expired effect is back to PENDING and claimable again
    reclaimed_item = queue_store.work[(1, w_exp.id)]
    assert reclaimed_item.status == int(WorkStatus.PENDING)
    assert reclaimed_item.lease_holder is None
    assert reclaimed_item.attempts == 1
