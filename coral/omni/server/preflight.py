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


_CREDENTIAL_SEVERITY: dict[CredentialKind, int] = {
    "api_key": 0,
    "provider": 0,
    "none": 1,
    "invalid": 2,
}


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


async def _worst_credential(
    claude_steps: Sequence[StepPlan],
) -> tuple[CredentialKind, str | None, str | None]:
    """Classify each distinct (auth, model); return the worst kind, its detail and first step."""
    by_auth_and_model: dict[tuple[str, str | None], tuple[CredentialKind, str | None]] = {}
    results: list[tuple[CredentialKind, str | None, str]] = []
    for plan in claude_steps:
        key = (repr(plan.spec.executor.auth), plan.spec.executor.model)
        if key not in by_auth_and_model:
            by_auth_and_model[key] = await asyncio.to_thread(_credential_kind, plan.spec)
        results.append((*by_auth_and_model[key], plan.step_ref))
    if not results:
        return "none", None, None
    kind, detail, step_ref = max(results, key=lambda result: _CREDENTIAL_SEVERITY[result[0]])
    return kind, detail, step_ref if _CREDENTIAL_SEVERITY[kind] else None


async def gather_preflight_facts(
    host_registry: HostRegistry, *, host_id: str, steps: Sequence[StepPlan]
) -> PreflightFacts:
    """Read whether the host is online, its OS sandbox, and the worst claude-sdk credential.

    The server's provider config stands in for the host's; the executor repeats the
    credential check on the host before the CLI starts.
    """
    credential, detail, credential_step_ref = await _worst_credential(
        [plan for plan in steps if is_claude_sdk_harness_name(plan.spec.executor.harness_kind)]
    )
    connection = host_registry.get(host_id)
    return PreflightFacts(
        credential=credential,
        credential_detail=detail,
        credential_step_ref=credential_step_ref,
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
