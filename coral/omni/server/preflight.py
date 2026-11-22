"""Gather run preflight facts from the host registry and the claude-sdk spawn env."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from coral.bridge.service import RunNotRunnable
from coral.model.ir import CompiledGraph
from coral.omni._upstream import _build_claude_sdk_spawn_env
from coral.omni.server.bundles import StepBundleRejected, parse_step_spec
from coral.omni.server.step_agents import step_bundle_yaml
from coral.tools.catalog import ORCHESTRATOR_STANCE
from coral.validate.preflight import (
    CredentialKind,
    PreflightFacts,
    PreflightReport,
    StepNeeds,
    run_preflight,
    sandbox_from_capabilities,
)
from omnigent.errors import OmnigentError
from omnigent.harness_aliases import canonicalize_harness, is_claude_sdk_harness_name
from omnigent.harness_availability import HARNESS_BINARY_MISSING
from omnigent.server.host_registry import HostRegistry
from omnigent.spec.types import AgentSpec

# Host readiness keys that report the system ``claude`` CLI (same binary coral-sdk wraps).
_SYSTEM_CLAUDE_HARNESS_KEYS = ("claude-native", "claude")


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


def system_claude_from_harnesses(configured: Mapping[str, object] | None) -> bool | None:
    """
    Whether the host's readiness map says a system ``claude`` CLI is installed.

    Uses the same keys the host probes for native Claude. ``False`` / binary-missing
    means absent; any other reported value means present. ``None`` when the map has
    none of those keys (host too old, or readiness not published).
    """
    if not configured:
        return None
    reported = False
    for key in _SYSTEM_CLAUDE_HARNESS_KEYS:
        if key not in configured:
            continue
        reported = True
        value = configured[key]
        if value is False or value == HARNESS_BINARY_MISSING:
            return False
    return True if reported else None


def estimate_session_count(graph: CompiledGraph) -> int:
    """Sessions a one-pass run needs: anchor, orchestrator, and each step roster seat."""
    step_seats = sum(len(node.roster) for node in graph.nodes if node.kind == "step")
    return 2 + step_seats


def plan_preflight_steps(
    graph: CompiledGraph,
    workflow_slug: str,
    *,
    claude_native_steps: bool = False,
) -> tuple[StepPlan, ...]:
    """
    Build parse-only ``AgentSpec`` plans for the orchestrator and every step roster seat.

    Uses the same bundle YAML path as step materialization, without storing agents.
    """
    plans: list[StepPlan] = []
    orch_yaml, orch_stance, _name = step_bundle_yaml(
        ORCHESTRATOR_STANCE, None, None, None, claude_native_steps=False
    )
    plans.append(
        StepPlan(step_ref=ORCHESTRATOR_STANCE, spec=parse_step_spec(orch_yaml, orch_stance))
    )
    for node in graph.nodes:
        if node.kind != "step":
            continue
        for roster_index, stance_name in enumerate(node.roster):
            config_yaml, stance, _agent_name = step_bundle_yaml(
                stance_name,
                workflow_slug,
                node.id,
                roster_index,
                claude_native_steps=claude_native_steps,
            )
            plans.append(
                StepPlan(
                    step_ref=f"{node.id}:{roster_index}",
                    spec=parse_step_spec(config_yaml, stance),
                )
            )
    return tuple(plans)


async def gather_preflight_facts(
    host_registry: HostRegistry, *, host_id: str, steps: Sequence[StepPlan]
) -> PreflightFacts:
    """Read whether the host is online, its OS sandbox, system Claude, and credentials.

    The server's provider config stands in for the host's; the executor repeats the
    credential check on the host before the CLI starts.
    """
    credential, detail, credential_step_ref = await _worst_credential(
        [plan for plan in steps if is_claude_sdk_harness_name(plan.spec.executor.harness_kind)]
    )
    connection = host_registry.get(host_id)
    configured = connection.hello.configured_harnesses if connection is not None else None
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
        system_claude=system_claude_from_harnesses(configured),
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


@dataclass(frozen=True)
class OmniWorkflowPreflight:
    """Plugin-wired preflight: plans step specs, gathers host facts, runs the report."""

    host_registry: HostRegistry
    claude_native_steps: bool = False

    async def check(
        self,
        *,
        workflow_key: str,
        graph: CompiledGraph,
        host_id: str,
    ) -> tuple[PreflightReport, int]:
        try:
            steps = plan_preflight_steps(
                graph, workflow_key, claude_native_steps=self.claude_native_steps
            )
        except StepBundleRejected as exc:
            raise RunNotRunnable("bundle.rejected", str(exc)) from exc
        facts = await gather_preflight_facts(self.host_registry, host_id=host_id, steps=steps)
        return run_preflight(facts), estimate_session_count(graph)
