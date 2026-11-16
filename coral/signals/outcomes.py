"""Failure-class outbox table. Pure. Does not import the reducer or lifecycle."""

from __future__ import annotations

from datetime import datetime

from coral.engine.timers import infra_backoff_rows, plan_probe_timer, timer_key
from coral.engine.types import Effect, PauseCause, TimerPolicy
from coral.signals.facts import (
    PLACEHOLDER_RUN_ID,
    PLACEHOLDER_SEQ,
    EffectSpec,
    effects_from_specs,
)

_PLAN_CLASSES = frozenset({"plan.usage_limit", "plan.spend_cap"})


def effect_specs(
    class_name: str, slot_id: str, now: datetime, policy: TimerPolicy
) -> tuple[EffectSpec, ...]:
    """Kind, subject, and payload for ``class_name``. No run id and no pause."""
    if class_name == "infra.transient":
        return tuple(
            _arm_spec(row.kind, row.subject, row.stage, row.due_at)
            for row in infra_backoff_rows(slot_id, 0, now, policy)
        )
    if class_name in _PLAN_CLASSES:
        row = plan_probe_timer(slot_id, 0, now, policy, stage=1)
        return (_arm_spec(row.kind, row.subject, row.stage, row.due_at),)
    if class_name == "auth":
        return (EffectSpec("notify", slot_id, {"kind": "pause"}),)
    if class_name == "infra.runner_lost":
        # Session id and generation are not arguments of this table. The reducer
        # already emits the real ``runner_lost`` effect and must not emit this too.
        return (EffectSpec("runner_lost", slot_id, {"session_id": "", "generation": 0}),)
    return ()


def outcomes(
    class_name: str, slot_id: str, now: datetime, policy: TimerPolicy
) -> tuple[Effect, ...]:
    """Effects for ``class_name``.

    Keys use the placeholder run id ``""`` and seq ``0`` via ``effect_key``. The
    reducer rebuilds them with ``assign_effect_keys`` from the run's seq. Due times
    in payloads are ISO-8601 strings. Timer rows store a ``datetime``.
    """
    specs = effect_specs(class_name, slot_id, now, policy)
    return effects_from_specs(specs, PLACEHOLDER_RUN_ID, PLACEHOLDER_SEQ)


def pause_for(class_name: str, slot_id: str) -> PauseCause | None:
    """The pause the reducer applies for ``class_name``. Infra classes do not pause."""
    if class_name in _PLAN_CLASSES:
        return PauseCause(reason="plan_limit", detail=class_name, subject=slot_id)
    if class_name == "auth":
        return PauseCause(reason="auth", detail="auth", subject=slot_id)
    if class_name == "agent.failed":
        return PauseCause(reason="failure_path", detail="agent.failed", subject=slot_id)
    return None


def arm_timer_effect(kind: str, subject: str, stage: int, due_at: datetime) -> Effect:
    """One ``arm_timer`` effect.

    ``subject`` is the timer subject. The effect subject is that timer's key.
    """
    spec = _arm_spec(kind, subject, stage, due_at)
    return effects_from_specs((spec,), PLACEHOLDER_RUN_ID, PLACEHOLDER_SEQ)[0]


def _arm_spec(kind: str, subject: str, stage: int, due_at: datetime) -> EffectSpec:
    return EffectSpec(
        "arm_timer",
        timer_key(kind, subject, stage),
        {"kind": kind, "stage": stage, "due_at": due_at.isoformat()},
    )
