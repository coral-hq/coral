"""Effect specs before a run id exists. The reducer assigns ``effect_key``."""

from __future__ import annotations

from typing import NamedTuple

from pydantic import JsonValue

from coral.engine.types import Effect, effect_key

# ``outcomes`` needs an ``effect_key`` because it returns ``Effect``. It does not
# know the run. These placeholders are replaced by ``assign_effect_keys``.
PLACEHOLDER_RUN_ID = ""
PLACEHOLDER_SEQ = 0


class EffectSpec(NamedTuple):
    """One outbox effect: kind, subject, and payload, with no run id."""

    kind: str
    subject: str
    payload: dict[str, JsonValue]


def effects_from_specs(specs: tuple[EffectSpec, ...], run_id: str, seq: int) -> tuple[Effect, ...]:
    """Build effects whose keys are ``effect_key(run_id, seq, kind, subject)``."""
    return tuple(
        Effect(
            effect_key=effect_key(run_id, seq, spec.kind, spec.subject),
            kind=spec.kind,
            subject=spec.subject,
            payload=dict(spec.payload),
        )
        for spec in specs
    )


def assign_effect_keys(effects: tuple[Effect, ...], run_id: str, seq: int) -> tuple[Effect, ...]:
    """Replace placeholder keys with the run's seq. Kind, subject, and payload stay."""
    return effects_from_specs(
        tuple(EffectSpec(effect.kind, effect.subject, dict(effect.payload)) for effect in effects),
        run_id,
        seq,
    )
