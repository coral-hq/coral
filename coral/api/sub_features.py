"""Coral sub-feature flag registry and override validation."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

CORAL_SUB_FEATURES_CONFIG_KEY = "coral_sub_features"

SUB_FEATURE_KEYS: tuple[str, ...] = (
    "editor",
    "canvas_edit",
    "claude_native_steps",
    "codex_steps",
    "webhooks",
    "budgets",
    "takeover",
    "restart_from_node",
    "profiles_desk",
    "slot_refresh",
    "scenario_editor",
    "blocks",
    "sandbox_runs",
)

DEFAULT_SUB_FEATURES: Mapping[str, bool] = MappingProxyType(
    dict.fromkeys(SUB_FEATURE_KEYS, False) | {"profiles_desk": True}
)


def resolve_sub_features(server_config: Mapping[str, Any] | None) -> dict[str, bool]:
    """Resolve and validate ``coral_sub_features`` overrides against known keys."""
    resolved = dict(DEFAULT_SUB_FEATURES)
    if server_config is None:
        return resolved
    raw_overrides = server_config.get(CORAL_SUB_FEATURES_CONFIG_KEY)
    if raw_overrides is None:
        return resolved
    if not isinstance(raw_overrides, Mapping):
        raise ValueError(
            f"{CORAL_SUB_FEATURES_CONFIG_KEY} must be a mapping of sub-feature keys to booleans"
        )
    for key, value in raw_overrides.items():
        if key not in DEFAULT_SUB_FEATURES:
            raise ValueError(f"Unknown Coral sub-feature key: {key!r}")
        if not isinstance(value, bool):
            raise ValueError(
                f"Coral sub-feature {key!r} override must be a bool, got {type(value).__name__}"
            )
        resolved[key] = value
    return resolved
