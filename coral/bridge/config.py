"""The bridge's clock helpers, the replay config frozen per run, and its limits."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from pydantic import ValidationError

from coral.engine.types import EngineConfig
from coral.stores.protocols import RunStartSpec

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)

# Every bridge and port commit waits at most this long for the run row's lock.
LOCK_TIMEOUT_S = 10.0
# One process keeps the folded state of this many runs.
FOLD_CACHE_RUNS = 256
# Engine log rows read per page while folding.
ENGINE_LOG_PAGE = 500
# The run-log actor column.
MAX_ACTOR_REF_CHARS = 128
# A message text as JSON, so its work payload stays well under the stored-text cap.
MAX_TEXT_JSON_CHARS = 12_288
MAX_PAYLOAD_BYTES = 15_000
# The run title's share of the orchestrator session title.
ORCHESTRATOR_TITLE_CHARS = 180

# Holds, in seconds: how long a refused item waits, and how long a hold may last
# from its first refusal (None: until a resume or a person ends it).
HOLD_RULES: Mapping[str, tuple[int, int | None]] = MappingProxyType(
    {
        "run.paused": (300, None),
        "slot.close_blocked": (15, None),
        "session.not_ready": (5, 1_800),
        "session.anchor_missing": (5, 1_800),
        "session.host_offline": (30, 1_800),
        "session.turn_state_unknown": (30, 1_800),
        "executor.missing": (60, 1_800),
        "signal.awaiting_effect": (5, None),
        "timer.early": (5, None),
    }
)
# ``drift.<cause>`` failures wait for the resume commit like ``run.paused``.
DRIFT_HOLD_PREFIX = "drift."
DRIFT_HOLD = (300, None)

# Periodic work, in seconds.
RESYNC_INTERVAL_S = 60
PAUSED_RESYNC_DELAY_S = 900
REGATHER_BUCKET_S = 300
BOUND_SESSIONS_REFRESH_S = 60
FINISHED_WORK_RETENTION_S = 86_400


class FrozenConfigMissing(ValueError):
    """The run spec has no readable frozen engine config, so its log cannot be replayed."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def epoch_us(moment: datetime) -> int:
    """Exact microseconds since the epoch of a timezone-aware time."""
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError("moment must be timezone-aware")
    return (moment - _EPOCH) // _MICROSECOND


def epoch_seconds(moment: datetime) -> int:
    """Whole seconds since the epoch, rounded down."""
    return epoch_us(moment) // 1_000_000


def ceil_epoch_seconds(moment: datetime) -> int:
    """Whole seconds since the epoch, rounded up, so nothing becomes due early."""
    return -(-epoch_us(moment) // 1_000_000)


def freeze_engine_config(*, max_activations: int, rejected_call_limit: int) -> str:
    """The JSON a run spec stores: these limits with every other setting at its default."""
    config = EngineConfig(max_activations=max_activations, rejected_call_limit=rejected_call_limit)
    return config.model_dump_json()


def engine_config_for(spec: RunStartSpec) -> EngineConfig:
    """
    The config a run's log is replayed with: the one frozen in its spec, never code defaults.

    :raises FrozenConfigMissing: when the spec has none or it does not parse.
    """
    if spec.engine_config is None:
        raise FrozenConfigMissing("the run spec has no frozen engine config")
    try:
        return EngineConfig.model_validate_json(spec.engine_config)
    except ValidationError as exc:
        raise FrozenConfigMissing(
            f"the run spec's frozen engine config does not parse ({exc.error_count()} errors)"
        ) from None


__all__ = [
    "BOUND_SESSIONS_REFRESH_S",
    "DRIFT_HOLD",
    "DRIFT_HOLD_PREFIX",
    "ENGINE_LOG_PAGE",
    "FINISHED_WORK_RETENTION_S",
    "FOLD_CACHE_RUNS",
    "HOLD_RULES",
    "LOCK_TIMEOUT_S",
    "MAX_ACTOR_REF_CHARS",
    "MAX_PAYLOAD_BYTES",
    "MAX_TEXT_JSON_CHARS",
    "ORCHESTRATOR_TITLE_CHARS",
    "PAUSED_RESYNC_DELAY_S",
    "REGATHER_BUCKET_S",
    "RESYNC_INTERVAL_S",
    "FrozenConfigMissing",
    "ceil_epoch_seconds",
    "engine_config_for",
    "epoch_seconds",
    "epoch_us",
    "freeze_engine_config",
    "utc_now",
]
