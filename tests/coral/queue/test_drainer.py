"""The drainer's generation re-check: a slot row a retry moved stops at its next lease check.

The claim-time fence sees only the generation at the claim. A retry committed while
the row runs bumps the slot's generation, so each ``ensure_lease`` also reads it and
abandons the row as ``slot.generation_mismatch`` before the side effect it guards.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from coral.bridge.mapping import RECOVERY_RESTART
from coral.db.enum_codecs import WorkStatus
from coral.queue import (
    EffectCompleted,
    ExecutionContext,
    FinishedWork,
    WorkDrainer,
    clear_executors,
    register_executor,
)
from coral.slots.executors import CLOSE_SLOT, SEND_INPUT
from coral.stores.fakes import FakeQueueStore, FakeRunStore
from coral.stores.protocols import RunStartSpec, WorkItemDraft

WORKSPACE = 3
SLOT = "s" * 32
# The wake's row kind (``coral.recovery.relaunch``); every slot row is checked alike.
RECOVERY_WAKE = "recovery.wake"
SLOT_ROWS = [CLOSE_SLOT, RECOVERY_RESTART, RECOVERY_WAKE, SEND_INPUT]
NOW = 200.0


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    clear_executors()
    yield
    clear_executors()


class _Queue:
    """A run with one slot at generation 1, its queue, a drainer and what it finished."""

    def __init__(self) -> None:
        self.runs = FakeRunStore(default_workspace_id=WORKSPACE)
        self.store = FakeQueueStore(run_store=self.runs, default_workspace_id=WORKSPACE)
        self.run = self.runs.start_run(
            RunStartSpec("wf", "v1", "Run", "", workspace_id=WORKSPACE), now=100
        )
        self.store.slot_generations[(WORKSPACE, self.run.id, SLOT)] = 1
        self.finished: list[FinishedWork] = []
        self.reads = 0
        read = self.store.get_slot_generation

        def counted(*args: object, **kwargs: object) -> int | None:
            self.reads += 1
            return read(*args, **kwargs)  # type: ignore[arg-type]

        self.store.get_slot_generation = counted  # type: ignore[method-assign]

        async def hook(finished: FinishedWork) -> None:
            self.finished.append(finished)

        self.drainer = WorkDrainer(
            self.store,
            worker_id="worker-1",
            workspace_id=WORKSPACE,
            clock=lambda: NOW,
            on_finished=hook,
        )

    def enqueue(self, effect_type: str, *, slot_generation: int | None = 1) -> str:
        draft = WorkItemDraft.effect(
            run_id=self.run.id,
            idempotency_key=f"key:{effect_type}",
            payload={"effect_type": effect_type, "slot_id": SLOT},
            slot_generation=slot_generation,
            owner_key=f"slot:{SLOT}",
            available_at=100,
        )
        self.store.enqueue_work([draft], workspace_id=WORKSPACE, now=100)
        return draft.id

    def bump(self) -> None:
        """A retry of the slot commits: its row now names generation 2."""
        self.store.slot_generations[(WORKSPACE, self.run.id, SLOT)] = 2

    def status(self, work_id: str) -> tuple[int, str | None]:
        (row,) = self.store.get_work([work_id], workspace_id=WORKSPACE)
        return row.status, row.error_code


@pytest.mark.parametrize("effect_type", SLOT_ROWS)
async def test_a_slot_row_superseded_while_it_runs_stops_at_its_next_lease_check(
    effect_type: str,
) -> None:
    queue = _Queue()
    side_effects: list[str] = []

    async def executor(ctx: ExecutionContext) -> EffectCompleted:
        await ctx.ensure_lease()
        side_effects.append("first")
        queue.bump()
        await ctx.ensure_lease()
        side_effects.append("second")
        return EffectCompleted(result={})

    register_executor(effect_type, executor)
    work_id = queue.enqueue(effect_type)

    await queue.drainer.drain_once()

    assert queue.status(work_id) == (int(WorkStatus.ABANDONED), "slot.generation_mismatch")
    assert side_effects == ["first"]
    # Abandoned rows are not fed: the resync decides what an abandoned restart means.
    assert queue.finished == []
    # One read at the claim and one per lease check.
    assert queue.reads == 3


async def test_a_slot_row_of_the_current_generation_runs_to_its_end() -> None:
    queue = _Queue()

    async def executor(ctx: ExecutionContext) -> EffectCompleted:
        await ctx.ensure_lease()
        await ctx.ensure_lease()
        return EffectCompleted(result={"ok": True})

    register_executor(CLOSE_SLOT, executor)
    work_id = queue.enqueue(CLOSE_SLOT)

    await queue.drainer.drain_once()

    assert queue.status(work_id) == (int(WorkStatus.SUCCEEDED), None)
    assert [item.status for item in queue.finished] == [int(WorkStatus.SUCCEEDED)]


async def test_a_row_without_a_slot_generation_never_reads_the_slot() -> None:
    queue = _Queue()

    async def executor(ctx: ExecutionContext) -> EffectCompleted:
        queue.bump()
        await ctx.ensure_lease()
        return EffectCompleted(result={})

    register_executor("signal.test", executor)
    work_id = queue.enqueue("signal.test", slot_generation=None)

    await queue.drainer.drain_once()

    assert queue.status(work_id) == (int(WorkStatus.SUCCEEDED), None)
    assert queue.reads == 0
