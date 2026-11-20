"""Tests for startup_recovery_sweep across multiple workspaces, expired work, and open gates."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

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
from tests._helpers.polling import poll_until_async
from tests.budgets import budget


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

    async def _gate_hook(gates: Sequence[GateVisitState]) -> None:
        if any(gate.id == "gv_1" for gate in gates):
            raise RuntimeError("transient elicitation error on gv_1")
        republished_gates.extend(gate.id for gate in gates)

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


def _open_gates(run_store: FakeRunStore, runs: int, gates_per_run: int) -> list[str]:
    """Start ``runs`` runs in workspace 1, each with ``gates_per_run`` OPEN gate rows."""
    run_ids: list[str] = []
    for index in range(runs):
        run = run_store.start_run(
            RunStartSpec(
                workflow_id="wf",
                version_id="v1",
                title=f"Run {index}",
                request_preview="req",
                workspace_id=1,
                user_id="alice",
            ),
            start_key=f"start-{index}",
            now=100,
        )
        run_store.apply_transition(
            run.id,
            1,
            Transition(
                status=int(RunStatus.RUNNING),
                gate_visits=tuple(
                    GateVisitDraft(
                        id=f"{run.id[:28]}g{gate:03d}",
                        activation_id=f"act_{gate}",
                        node_id=f"gate_{gate}",
                        scope_key="root",
                        visit_no=1,
                        token=f"gate_{gate}||:1",
                        status=int(GateVisitStatus.OPEN),
                        owner_user_id="alice",
                        opened_at=105,
                    )
                    for gate in range(gates_per_run)
                ),
            ),
            workspace_id=1,
            now=105,
        )
        run_ids.append(run.id)
    return sorted(run_ids)


async def test_open_gates_are_republished_one_batch_per_run_across_pages() -> None:
    run_store = FakeRunStore(default_workspace_id=1)
    queue_store = FakeQueueStore(run_store=run_store, default_workspace_id=1)
    run_ids = _open_gates(run_store, runs=3, gates_per_run=3)
    batches: list[tuple[str, int]] = []

    async def republish(gates: Sequence[GateVisitState]) -> None:
        assert len({gate.run_id for gate in gates}) == 1
        batches.append((gates[0].run_id, len(gates)))

    # A page boundary falls inside a run's rows: the run still gets one batch.
    report = await startup_recovery_sweep(
        run_store, queue_store, gate_republisher=republish, page_size=2
    )

    assert sorted(batches) == [(run_id, 3) for run_id in run_ids]
    assert (report.open_gates_scanned, report.open_gates_republished, report.errors) == (9, 9, 0)


async def test_at_most_four_runs_republish_at_once() -> None:
    run_store = FakeRunStore(default_workspace_id=1)
    queue_store = FakeQueueStore(run_store=run_store, default_workspace_id=1)
    _open_gates(run_store, runs=6, gates_per_run=1)
    in_flight = 0
    peak = 0
    release = asyncio.Event()

    async def republish(_gates: Sequence[GateVisitState]) -> None:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await release.wait()
        in_flight -= 1

    sweep = asyncio.create_task(
        startup_recovery_sweep(run_store, queue_store, gate_republisher=republish)
    )
    await poll_until_async(lambda: in_flight >= 4, timeout_s=budget(30))
    release.set()
    report = await asyncio.wait_for(sweep, timeout=budget(30))

    assert peak == 4
    assert (report.open_gates_republished, report.errors) == (6, 0)


async def test_a_run_whose_republish_outlasts_its_bound_is_counted_and_the_others_finish() -> None:
    run_store = FakeRunStore(default_workspace_id=1)
    queue_store = FakeQueueStore(run_store=run_store, default_workspace_id=1)
    stuck, *others = _open_gates(run_store, runs=3, gates_per_run=1)
    done: list[str] = []
    never = asyncio.Event()

    async def republish(gates: Sequence[GateVisitState]) -> None:
        if gates[0].run_id == stuck:
            await never.wait()
        done.append(gates[0].run_id)

    report = await startup_recovery_sweep(
        run_store, queue_store, gate_republisher=republish, gate_timeout_s=0.05
    )

    assert sorted(done) == sorted(others)
    assert (report.open_gates_scanned, report.open_gates_republished, report.errors) == (3, 2, 1)


async def test_a_failed_gate_listing_is_counted_and_the_active_runs_are_still_reconciled() -> None:
    run_store = FakeRunStore(default_workspace_id=1)
    queue_store = FakeQueueStore(run_store=run_store, default_workspace_id=1)
    run_ids = _open_gates(run_store, runs=3, gates_per_run=1)
    listings = 0

    def flaky_listing(**kwargs: object) -> list[GateVisitState]:
        nonlocal listings
        listings += 1
        if listings == 2:
            raise RuntimeError("gate listing failed")
        return FakeRunStore.list_open_gates_all_workspaces(run_store, **kwargs)  # type: ignore[arg-type]

    run_store.list_open_gates_all_workspaces = flaky_listing  # type: ignore[method-assign]
    republished: list[str] = []
    reconciled: list[str] = []

    async def republish(gates: Sequence[GateVisitState]) -> None:
        republished.append(gates[0].run_id)

    async def reconcile(run: CoralRun) -> None:
        reconciled.append(run.id)

    # The second page fails: the first page's run is still republished, then the runs scanned.
    report = await startup_recovery_sweep(
        run_store,
        queue_store,
        gate_republisher=republish,
        run_reconciler=reconcile,
        page_size=1,
    )

    assert republished == run_ids[:1]
    assert sorted(reconciled) == run_ids
    assert (report.open_gates_scanned, report.errors) == (1, 1)
    assert report.active_runs_reconciled == 3
