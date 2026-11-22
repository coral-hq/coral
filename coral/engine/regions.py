"""ENG-08 parallel region cancel (pure). SES-10 runs ``structure.cancel_region``."""

from __future__ import annotations

from coral.engine.types import Effect, effect_key

CANCEL_REGION = "structure.cancel_region"


def cancel_region_effects(
    *,
    run_id: str,
    seq: int,
    split_node_id: str,
    join_node_id: str,
    active_subjects: tuple[str, ...],
) -> tuple[Effect, ...]:
    """One cancel effect per live sibling slot; subjects are scope-derived activation ids."""
    effects: list[Effect] = []
    for offset, subject in enumerate(active_subjects):
        effects.append(
            Effect(
                effect_key=effect_key(run_id, seq + offset, CANCEL_REGION, subject),
                kind=CANCEL_REGION,
                subject=subject,
                payload={
                    "split_node_id": split_node_id,
                    "join_node_id": join_node_id,
                    "reason": "region_cancelled",
                },
            )
        )
    return tuple(effects)


__all__ = ["CANCEL_REGION", "cancel_region_effects"]
