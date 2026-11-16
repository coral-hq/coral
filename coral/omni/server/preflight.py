"""Gather run preflight facts from the host registry and the claude-sdk spawn env."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from coral.omni._upstream import _build_claude_sdk_spawn_env
from coral.validate.preflight import (
    CredentialKind,
    PreflightFacts,
    StepNeeds,
    sandbox_from_capabilities,
)
from omnigent.errors import OmnigentError
from omnigent.harness_aliases import canonicalize_harness, is_claude_sdk_harness_name
from omnigent.server.host_registry import HostRegistry
from omnigent.spec.types import AgentSpec


@dataclass(frozen=True)
class StepPlan:
    step_ref: str
    spec: AgentSpec


def _credential_kind(spec: AgentSpec) -> tuple[CredentialKind, str | None]:
    """Classify the spawn env's credential; the env may hold a literal key, so it never leaves."""
    try:
        env = _build_claude_sdk_spawn_env(spec)
    except OmnigentError as exc:
        return "invalid", str(exc)
    if "HARNESS_CLAUDE_SDK_API_KEY_HELPER" in env:
        return "api_key", None
    if env.get("HARNESS_CLAUDE_SDK_GATEWAY") == "true":
        return "provider", None
    return "none", None


async def gather_preflight_facts(
    host_registry: HostRegistry, *, host_id: str, steps: Sequence[StepPlan]
) -> PreflightFacts:
    """Read whether the host is online, its OS sandbox, and the claude-sdk credential kind.

    The server's provider config stands in for the host's; the executor repeats the
    credential check on the host before the CLI starts.
    """
    claude_specs = [
        plan.spec for plan in steps if is_claude_sdk_harness_name(plan.spec.executor.harness_kind)
    ]
    credential, detail = (
        await asyncio.to_thread(_credential_kind, claude_specs[0])
        if claude_specs
        else ("none", None)
    )
    connection = host_registry.get(host_id)
    return PreflightFacts(
        credential=credential,
        credential_detail=detail,
        host_online=connection is not None,
        sandbox=(
            sandbox_from_capabilities(connection.hello.capabilities)
            if connection is not None
            else None
        ),
        steps=tuple(
            StepNeeds(
                step_ref=plan.step_ref,
                harness=canonicalize_harness(plan.spec.executor.harness_kind)
                or plan.spec.executor.harness_kind,
                needs_fs_sandbox=plan.spec.os_env is not None,
            )
            for plan in steps
        ),
    )
