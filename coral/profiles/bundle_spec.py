"""Turn a Coral seed into the canonical ``config.yaml`` of a hidden, hygienic step agent.

The output is deterministic: the same step, stance, model and provider give the
same bytes, so the bundle's content digest and its derived agent id repeat
across runs. Nothing run-specific (run id, brief) goes into the bundle.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from coral.model.ids import MAX_SLUG_LENGTH, SLUG_PATTERN
from coral.profiles.seeds import load_seed

GENERATOR_VERSION = 1
ENGINE_PREFIX = "coral__"
DENY_VENDOR_ASK_HANDLER = "coral.omni.policies.hygiene.deny_vendor_ask"

Slug = Annotated[
    str, StringConstraints(pattern=f"^{SLUG_PATTERN.pattern}$", max_length=MAX_SLUG_LENGTH)
]


class Stance(StrEnum):
    """The role a step agent plays; each stance has one packaged seed."""

    ANCHOR = "anchor"
    ORCHESTRATOR = "orchestrator"
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"


class StepRef(BaseModel):
    """Which roster member of which workflow node a step agent runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: Slug
    node_id: Slug
    roster_index: int = Field(ge=0)


# Forced on every step bundle after the seed, so no seed edit can loosen it.
HYGIENE: Mapping[str, object] = {
    "spawn": False,
    "tools": {"agents": []},
    "timers": False,
    "async": False,
    "agent_session_sharing": "none",
    "skills": "none",
    "tool_groups": {
        "browser": False,
        "scheduled_tasks": False,
        "comments": False,
        "policies": False,
        "agent_discovery": False,
    },
}

_DENY_VENDOR_ASK_POLICY: Mapping[str, object] = {
    "type": "function",
    "on": ["tool_call"],
    "function": {"path": DENY_VENDOR_ASK_HANDLER},
}


def step_agent_name(ref: StepRef) -> str:
    """
    Name the step agent ``coral__<workflow>__<node>__m<index>``.

    Agent names allow only ``[a-zA-Z0-9_-]``, so ``.`` in a slug becomes ``-``.
    The name is for display; identity is the digest-derived agent id.
    """
    workflow = ref.workflow_id.replace(".", "-")
    node = ref.node_id.replace(".", "-")
    return f"{ENGINE_PREFIX}{workflow}__{node}__m{ref.roster_index}"


def _section(config: dict[str, object], key: str) -> dict[str, object]:
    value = config.setdefault(key, {})
    if not isinstance(value, dict):
        raise TypeError(f"seed key {key!r} must be a mapping, got {type(value).__name__}")
    return value


def _merge_hygiene(config: dict[str, object]) -> None:
    for key, forced in HYGIENE.items():
        current = config.get(key)
        if isinstance(forced, Mapping) and isinstance(current, dict):
            current.update(copy.deepcopy(dict(forced)))
        else:
            config[key] = copy.deepcopy(forced)
    policies = _section(_section(config, "guardrails"), "policies")
    policies["deny_vendor_ask"] = copy.deepcopy(dict(_DENY_VENDOR_ASK_POLICY))


def _bundle_yaml(
    stance: Stance,
    *,
    name: str,
    generated: Mapping[str, object],
    model: str | None,
    provider: str | None,
) -> bytes:
    seed = load_seed(stance.value)
    config = copy.deepcopy(dict(seed.config))
    config["name"] = name
    _section(config, "params")["coral"] = {
        "generated": {
            "generator_version": GENERATOR_VERSION,
            "seed": {"name": seed.name, "sha256": seed.sha256},
            "stance": stance.value,
            **generated,
        }
    }
    executor = _section(config, "executor")
    if model is not None:
        executor["model"] = model
    if provider is not None:
        executor["auth"] = {"type": "provider", "name": provider}
    _merge_hygiene(config)
    return yaml.safe_dump(config, sort_keys=True, allow_unicode=True).encode("utf-8")


def build_step_bundle_yaml(
    ref: StepRef,
    stance: Stance,
    *,
    model: str | None,
    provider: str | None,
) -> bytes:
    """
    Build the ``config.yaml`` bytes for one workflow step's agent.

    :param ref: The workflow, node and roster index the agent runs.
    :param stance: Which seed to start from.
    :param model: Model id to pin, or ``None`` for the harness default.
    :param provider: Name of a configured provider to authenticate with, or
        ``None`` when the run binds credentials another way. A literal API key
        never goes into a bundle.
    :returns: Canonical YAML (sorted keys), identical for identical inputs.
    """
    return _bundle_yaml(
        stance,
        name=step_agent_name(ref),
        generated={
            "workflow_id": ref.workflow_id,
            "node_id": ref.node_id,
            "roster_index": ref.roster_index,
        },
        model=model,
        provider=provider,
    )


def build_seed_bundle_yaml(stance: Stance) -> bytes:
    """Build the ``config.yaml`` bytes for the seed agent ``coral__<stance>``."""
    return _bundle_yaml(
        stance, name=f"{ENGINE_PREFIX}{stance.value}", generated={}, model=None, provider=None
    )
