"""Turn a Coral seed into the canonical ``config.yaml`` of a hidden, hygienic step agent.

The output is deterministic: the same step, stance, model and provider give the
same bytes, so the bundle's content digest and its derived agent id repeat
across runs. Nothing run-specific (run id, brief) goes into the bundle.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from coral.model.ids import MAX_SLUG_LENGTH, SLUG_PATTERN
from coral.profiles.seeds import load_seed
from coral.profiles.spec import ProfileSpec
from coral.rules.compile import compile_rules

GENERATOR_VERSION = 2
ENGINE_PREFIX = "coral__"
DENY_VENDOR_ASK_HANDLER = "coral.omni.policies.hygiene.deny_vendor_ask"
GUARDS_MODULE = "coral.omni.policies.guards"

Slug = Annotated[
    str, StringConstraints(pattern=f"^{SLUG_PATTERN.pattern}$", max_length=MAX_SLUG_LENGTH)
]


class Stance(StrEnum):
    """The role a step agent plays; each stance has one packaged seed."""

    ANCHOR = "anchor"
    ORCHESTRATOR = "orchestrator"
    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"


# The tool guard forced on each stance's bundle besides deny_vendor_ask: a handler
# name in GUARDS_MODULE, also used as the policy's key.
STANCE_GUARDS: Mapping[Stance, str] = MappingProxyType(
    {
        Stance.ANCHOR: "deny_all_tools",
        Stance.ORCHESTRATOR: "orchestrator_guard",
        Stance.IMPLEMENTER: "step_roster",
        Stance.REVIEWER: "step_roster",
    }
)


def stance_guard_handler(stance: Stance) -> str:
    """The dotted path of *stance*'s guard, e.g. ``coral.omni.policies.guards.step_roster``."""
    return f"{GUARDS_MODULE}.{STANCE_GUARDS[stance]}"


class StepRef(BaseModel):
    """Which roster member of which workflow node a step agent runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: Slug
    node_id: Slug
    roster_index: int = Field(ge=0)


@dataclass(frozen=True)
class ProfileOverlay:
    """The pinned profile revision a step bundle is built from, on top of its stance's seed."""

    profile_ref: str
    revision_id: str
    revision_no: int
    spec: ProfileSpec


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


def _tool_call_policy(handler: str) -> dict[str, object]:
    return {"type": "function", "on": ["tool_call"], "function": {"path": handler}}


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


def _merge_hygiene(config: dict[str, object], stance: Stance) -> None:
    for key, forced in HYGIENE.items():
        current = config.get(key)
        if isinstance(forced, Mapping) and isinstance(current, dict):
            current.update(copy.deepcopy(dict(forced)))
        else:
            config[key] = copy.deepcopy(forced)
    policies = _section(_section(config, "guardrails"), "policies")
    policies["deny_vendor_ask"] = _tool_call_policy(DENY_VENDOR_ASK_HANDLER)
    policies[STANCE_GUARDS[stance]] = _tool_call_policy(stance_guard_handler(stance))


def _apply_profile(config: dict[str, object], spec: ProfileSpec) -> None:
    fragment = compile_rules(spec.rules)
    if spec.description:
        config["description"] = spec.description
    instructions = str(config.get("instructions", ""))
    if spec.instructions:
        instructions += f"\n\nProfile instructions:\n{spec.instructions}"
    if fragment.statements:
        instructions += "\n\nRules you must follow:\n- " + "\n- ".join(fragment.statements)
    config["instructions"] = instructions
    if spec.model is not None:
        _section(config, "executor")["model"] = spec.model
    # Before hygiene, so its forced policies win any key clash.
    _section(_section(config, "guardrails"), "policies").update(fragment.policies)


def _bundle_yaml(
    stance: Stance,
    *,
    name: str,
    generated: Mapping[str, object],
    model: str | None,
    provider: str | None,
    profile: ProfileSpec | None = None,
    harness: str | None = None,
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
    executor_config = _section(executor, "config")
    if harness is not None:
        executor_config["harness"] = harness
    if harness == "claude-native":
        # Run-owned native steps: fail closed and skip the TUI permission prompt.
        executor_config["permission_mode"] = "bypassPermissions"
        executor_config["policy_failure_mode"] = "fail_closed"
        from coral.tools.catalog import CATALOG, tools_for_stance

        # Written for Omnigent launch (S11); Omnigent must not import coral/.
        allowed: list[str] = []
        for decl in tools_for_stance(CATALOG, stance.value):
            allowed.append(decl.name)
            allowed.append(f"mcp__omnigent__{decl.name}")
        executor_config["native_preapproved"] = list(dict.fromkeys(allowed))
    if model is not None:
        executor["model"] = model
    if provider is not None:
        executor["auth"] = {"type": "provider", "name": provider}
    if profile is not None:
        _apply_profile(config, profile)
    _merge_hygiene(config, stance)
    return yaml.safe_dump(config, sort_keys=True, allow_unicode=True).encode("utf-8")


def build_step_bundle_yaml(
    ref: StepRef,
    stance: Stance,
    *,
    model: str | None,
    provider: str | None,
    profile: ProfileOverlay | None = None,
    harness: str | None = None,
) -> bytes:
    """
    Build the ``config.yaml`` bytes for one workflow step's agent.

    :param ref: The workflow, node and roster index the agent runs.
    :param stance: Which seed to start from.
    :param model: Model id to pin, or ``None`` for the harness default.
    :param provider: Name of a configured provider to authenticate with, or
        ``None`` when the run binds credentials another way. A literal API key
        never goes into a bundle.
    :param profile: The pinned profile revision to overlay on the seed, or
        ``None`` for the bare stance. Its model, when set, replaces *model*.
    :param harness: Optional harness override, e.g. ``"claude-native"`` when
        ``claude_native_steps`` is on. ``None`` keeps the seed's harness.
    :returns: Canonical YAML (sorted keys), identical for identical inputs.
    """
    generated: dict[str, object] = {
        "workflow_id": ref.workflow_id,
        "node_id": ref.node_id,
        "roster_index": ref.roster_index,
    }
    if profile is not None:
        generated["profile"] = {
            "ref": profile.profile_ref,
            "revision_id": profile.revision_id,
            "revision_no": profile.revision_no,
        }
    return _bundle_yaml(
        stance,
        name=step_agent_name(ref),
        generated=generated,
        model=model,
        provider=provider,
        profile=profile.spec if profile is not None else None,
        harness=harness,
    )


def build_seed_bundle_yaml(stance: Stance) -> bytes:
    """Build the ``config.yaml`` bytes for the seed agent ``coral__<stance>``."""
    return _bundle_yaml(
        stance, name=f"{ENGINE_PREFIX}{stance.value}", generated={}, model=None, provider=None
    )
