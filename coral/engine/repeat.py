"""ENG-08 repeat-for-each fan-out (pure). SES-10 executes ``structure.start_item``."""

from __future__ import annotations

from dataclasses import dataclass

from coral.engine.types import Effect, activation_id, effect_key

START_ITEM = "structure.start_item"


@dataclass(frozen=True)
class FanOutPlan:
    """Frozen item ids and the first concurrency window of start effects."""

    item_ids: tuple[str, ...]
    effects: tuple[Effect, ...]
    # How many items may be live at once; further starts wait on completions.
    concurrency: int


def freeze_item_ids(items: tuple[object, ...]) -> tuple[str, ...]:
    """Stable item ids for one fan-out: decimal indices in list order."""
    return tuple(str(index) for index in range(len(items)))


def fan_out(
    *,
    run_id: str,
    seq: int,
    node_id: str,
    parent_item_path: tuple[str, ...] = (),
    iteration_path: tuple[str, ...] = (),
    items: tuple[object, ...],
    concurrency: int = 1,
) -> FanOutPlan:
    """Plan item activations for a repeat step.

    Empty ``items`` yields no effects (the exit still receives ``items: []`` via
    SES-10). Otherwise the first ``concurrency`` items emit ``structure.start_item``.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    item_ids = freeze_item_ids(items)
    if not item_ids:
        return FanOutPlan(item_ids=(), effects=(), concurrency=concurrency)
    window = item_ids[:concurrency]
    effects: list[Effect] = []
    for offset, item_id in enumerate(window):
        path = (*parent_item_path, item_id)
        subject = activation_id(node_id, path, iteration_path)
        effects.append(
            Effect(
                effect_key=effect_key(run_id, seq + offset, START_ITEM, subject),
                kind=START_ITEM,
                subject=subject,
                payload={
                    "node_id": node_id,
                    "item_path": list(path),
                    "iteration_path": list(iteration_path),
                    "item_id": item_id,
                },
            )
        )
    return FanOutPlan(item_ids=item_ids, effects=tuple(effects), concurrency=concurrency)


def repeat_progress(*, done: int, failed: int, total: int) -> dict[str, int]:
    """RunView ``repeat_progress`` patch shape for one region."""
    if min(done, failed, total) < 0 or done + failed > total:
        raise ValueError("repeat_progress counts must be non-negative and fit total")
    return {"done": done, "failed": failed, "total": total}


__all__ = [
    "START_ITEM",
    "FanOutPlan",
    "fan_out",
    "freeze_item_ids",
    "repeat_progress",
]
