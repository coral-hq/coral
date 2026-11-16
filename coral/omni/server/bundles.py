"""Pack, validate and store Coral step bundles as content-addressed, hidden agent rows."""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from coral.omni._upstream import _tar_gz_dir
from coral.profiles.bundle_spec import DENY_VENDOR_ASK_HANDLER, ENGINE_PREFIX, Stance
from omnigent.errors import OmnigentError
from omnigent.harness_aliases import is_claude_sdk_harness_name
from omnigent.server.bundles import uploaded_agent_for, validate_agent_bundle
from omnigent.spec.types import AgentSpec, FunctionPolicySpec, SharePolicy
from omnigent.stores.agent_store import AgentStore
from omnigent.stores.artifact_store import ArtifactStore

READ_ONLY_OS_HANDLER = "omnigent.policies.builtins.orchestration.read_only_os"


class MaterializedAgent(BaseModel):
    """The agent row a step bundle resolved to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_id: str
    name: str
    digest: str
    bundle_location: str


class StepBundleRejected(Exception):
    """A step bundle broke a hygiene or validation rule. Retrying cannot fix it."""


def pack_bundle(config_yaml: bytes) -> bytes:
    """Pack *config_yaml* as the only file of a deterministic ``.tar.gz`` bundle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "config.yaml").write_bytes(config_yaml)
        return _tar_gz_dir(Path(tmpdir))


def _function_policy_paths(spec: AgentSpec) -> set[str]:
    policies = spec.guardrails.policies if spec.guardrails else None
    return {
        policy.function.path
        for policy in policies or ()
        if isinstance(policy, FunctionPolicySpec) and policy.function is not None
    }


def _hygiene_violations(spec: AgentSpec, stance: Stance) -> list[str]:
    groups = spec.tool_groups
    policy_paths = _function_policy_paths(spec)
    rules = {
        f"name starts with {ENGINE_PREFIX}": (spec.name or "").startswith(ENGINE_PREFIX),
        "params.coral is set": "coral" in spec.params,
        "harness is claude-sdk": is_claude_sdk_harness_name(spec.executor.harness_kind),
        "spawn is false": not spec.spawn,
        "tools.agents is empty": not spec.tools.agents,
        "timers is false": not spec.timers,
        "async is false": not spec.async_enabled,
        "agent_session_sharing is none": spec.agent_session_sharing is SharePolicy.NONE,
        "skills is none": spec.skills_filter == "none",
        "every tool group is off": not any(
            (
                groups.browser,
                groups.scheduled_tasks,
                groups.comments,
                groups.policies,
                groups.agent_discovery,
            )
        ),
        "deny_vendor_ask is a policy": DENY_VENDOR_ASK_HANDLER in policy_paths,
    }
    if spec.os_env is not None:
        sandbox = spec.os_env.sandbox
        rules["os_env has an OS sandbox"] = sandbox is not None and sandbox.type != "none"
    if stance is Stance.REVIEWER:
        sandbox = spec.os_env.sandbox if spec.os_env is not None else None
        rules["reviewer sandbox has no write_paths"] = (
            sandbox is not None and sandbox.write_paths == []
        )
        rules["reviewer has read_only_os"] = READ_ONLY_OS_HANDLER in policy_paths
    return [rule for rule, holds in rules.items() if not holds]


def check_hygiene(spec: AgentSpec, stance: Stance) -> None:
    """
    Check a parsed step spec against the rules every Coral step must keep.

    :raises StepBundleRejected: Naming each rule the spec breaks.
    """
    violations = _hygiene_violations(spec, stance)
    if violations:
        raise StepBundleRejected(
            f"{stance.value} bundle {spec.name!r} breaks: {'; '.join(violations)}"
        )


def materialize(
    agent_store: AgentStore,
    artifact_store: ArtifactStore,
    *,
    owner: str | None,
    config_yaml: bytes,
    stance: Stance,
) -> MaterializedAgent:
    """
    Store a step bundle and return its agent row, creating the row on first use.

    The row id comes from (owner, name, content digest), so materializing the
    same bundle again returns the same row, and a lost blob is written back.

    :param owner: The run's user, or ``None`` on an auth-less server.
    :param config_yaml: Output of ``build_step_bundle_yaml`` or ``build_seed_bundle_yaml``.
    :param stance: The stance the bundle was built for, to pick hygiene rules.
    :raises StepBundleRejected: When validation or hygiene fails, or the store
        cannot hold user agents.
    """
    bundle = pack_bundle(config_yaml)
    try:
        spec = validate_agent_bundle(bundle, enforce_handler_allowlist=True)
    except OmnigentError as exc:
        raise StepBundleRejected(f"{stance.value} bundle failed validation: {exc}") from exc
    check_hygiene(spec, stance)
    agent = uploaded_agent_for(
        agent_store, artifact_store, owner=owner, spec=spec, bundle_bytes=bundle
    )
    if agent is None:
        raise StepBundleRejected(
            f"{stance.value} bundle {spec.name!r} could not be stored as a user agent"
        )
    return MaterializedAgent(
        agent_id=agent.id,
        name=agent.name,
        digest=agent.bundle_location.rsplit("/", 1)[-1],
        bundle_location=agent.bundle_location,
    )
