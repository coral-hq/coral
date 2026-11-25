"""Preflight facts come from the host registry and the real claude-sdk spawn env."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from coral.omni.server.preflight import StepPlan, gather_preflight_facts
from coral.validate.preflight import run_preflight
from omnigent.host.frames import HostHelloFrame
from omnigent.inner.datamodel import OSEnvSpec
from omnigent.server.host_registry import HostRegistry
from omnigent.spec.types import AgentSpec, ExecutorSpec, ProviderAuth
from tests._helpers.providers import isolate_provider_resolution
from tests.server.test_host_registry import FakeWebSocket

HOST_ID = "host_preflight"
LITERAL_KEY = "sk-ant-literal-never-in-facts"


@pytest.fixture
def config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    return isolate_provider_resolution(monkeypatch, tmp_path / "config")


def _write_config(config_home: Path, config: dict[str, object]) -> None:
    (config_home / "config.yaml").write_text(yaml.safe_dump(config))


def _coral_step(
    *,
    auth: ProviderAuth | None = None,
    os_env: OSEnvSpec | None = None,
    step_ref: str = "review",
) -> StepPlan:
    spec = AgentSpec(
        spec_version=1,
        name="coral__demo__review__m0",
        instructions="Review.",
        executor=ExecutorSpec(
            type="omnigent",
            config={"harness": "claude-sdk"},
            model="claude-sonnet-4-6",
            auth=auth,
        ),
        os_env=os_env,
        params={"coral": {"generated": {"stance": "reviewer"}}},
    )
    return StepPlan(step_ref=step_ref, spec=spec)


def _online_registry(
    capabilities: list[str],
    *,
    configured_harnesses: dict[str, object] | None = None,
) -> HostRegistry:
    registry = HostRegistry()
    hello = HostHelloFrame(
        version="0.22.0",
        frame_protocol_version=1,
        name="laptop",
        capabilities=capabilities,
        configured_harnesses=configured_harnesses
        if configured_harnesses is not None
        else {"claude-native": True},
    )
    registry.register(HOST_ID, FakeWebSocket(), hello, owner="alice")
    return registry


async def test_offline_host_reports_no_host_and_no_sandbox(config_home: Path) -> None:
    facts = await gather_preflight_facts(HostRegistry(), host_id=HOST_ID, steps=[_coral_step()])

    assert facts.host_online is False
    assert facts.sandbox is None


@pytest.mark.parametrize(
    ("token", "backend"),
    [
        ("os_sandbox:darwin_seatbelt", "seatbelt"),
        ("os_sandbox:linux_bwrap", "bwrap"),
        ("os_sandbox:none", "none"),
        (None, None),
    ],
)
async def test_hello_capabilities_give_the_sandbox_backend(
    config_home: Path, token: str | None, backend: str | None
) -> None:
    registry = _online_registry(["plugins", *([token] if token else [])])
    step = _coral_step(os_env=OSEnvSpec(cwd="."))

    facts = await gather_preflight_facts(registry, host_id=HOST_ID, steps=[step])

    assert facts.host_online is True
    assert facts.sandbox == backend
    assert facts.steps[0].harness == "claude-sdk"
    assert facts.steps[0].needs_fs_sandbox is True


async def test_global_api_key_gives_api_key(config_home: Path) -> None:
    _write_config(config_home, {"auth": {"type": "api_key", "api_key": LITERAL_KEY}})

    facts = await gather_preflight_facts(
        _online_registry([]), host_id=HOST_ID, steps=[_coral_step()]
    )

    assert facts.credential == "api_key"


async def test_declared_provider_gives_provider(config_home: Path) -> None:
    family = {
        "base_url": "https://anthropic.example.com/v1",
        "api_key": LITERAL_KEY,
        "models": {"default": "claude-sonnet-4-6"},
    }
    _write_config(
        config_home, {"providers": {"team-anthropic": {"kind": "key", "anthropic": family}}}
    )

    facts = await gather_preflight_facts(
        _online_registry([]),
        host_id=HOST_ID,
        steps=[_coral_step(auth=ProviderAuth(name="team-anthropic"))],
    )

    assert facts.credential == "provider"


async def test_later_step_without_a_credential_fails_preflight_naming_it(
    config_home: Path,
) -> None:
    family = {
        "base_url": "https://anthropic.example.com/v1",
        "api_key": LITERAL_KEY,
        "models": {"default": "claude-sonnet-4-6"},
    }
    _write_config(
        config_home, {"providers": {"team-anthropic": {"kind": "key", "anthropic": family}}}
    )
    team = ProviderAuth(name="team-anthropic")
    steps = [
        _coral_step(auth=team, step_ref="plan"),
        _coral_step(auth=team, step_ref="review"),
        _coral_step(auth=ProviderAuth(name="missing-provider"), step_ref="implement"),
    ]

    facts = await gather_preflight_facts(_online_registry([]), host_id=HOST_ID, steps=steps)

    assert (facts.credential, facts.credential_step_ref) == ("invalid", "implement")
    auth = run_preflight(facts).items[0]
    assert auth.status == "fail"
    assert "(step implement)" in auth.message and "missing-provider" in auth.message


async def test_no_credential_gives_none(config_home: Path) -> None:
    facts = await gather_preflight_facts(
        _online_registry([]), host_id=HOST_ID, steps=[_coral_step()]
    )

    assert facts.credential == "none"
    assert facts.steps[0].needs_fs_sandbox is False


async def test_undeclared_provider_gives_invalid_with_the_reason(config_home: Path) -> None:
    facts = await gather_preflight_facts(
        _online_registry([]),
        host_id=HOST_ID,
        steps=[_coral_step(auth=ProviderAuth(name="missing-provider"))],
    )

    assert facts.credential == "invalid"
    assert facts.credential_detail is not None and "missing-provider" in facts.credential_detail


async def test_literal_api_key_never_reaches_the_facts_or_report(config_home: Path) -> None:
    _write_config(config_home, {"auth": {"type": "api_key", "api_key": LITERAL_KEY}})

    facts = await gather_preflight_facts(
        _online_registry(["os_sandbox:darwin_seatbelt"]),
        host_id=HOST_ID,
        steps=[_coral_step(os_env=OSEnvSpec(cwd="."))],
    )

    assert LITERAL_KEY not in facts.model_dump_json()
    assert LITERAL_KEY not in run_preflight(facts).model_dump_json()


async def test_subscription_only_host_needs_an_api_key(config_home: Path) -> None:
    facts = await gather_preflight_facts(
        _online_registry(["os_sandbox:darwin_seatbelt"]),
        host_id=HOST_ID,
        steps=[_coral_step(os_env=OSEnvSpec(cwd="."))],
    )

    report = run_preflight(facts)

    assert report.ok is False
    failures = [(item.check, item.fix.target) for item in report.items if item.fix is not None]
    assert failures == [("auth", "add_api_key")]


async def test_missing_system_claude_is_gathered_from_harness_readiness(
    config_home: Path,
) -> None:
    facts = await gather_preflight_facts(
        _online_registry(
            ["os_sandbox:darwin_seatbelt"],
            configured_harnesses={"claude-native": "binary-missing"},
        ),
        host_id=HOST_ID,
        steps=[_coral_step(os_env=OSEnvSpec(cwd="."))],
    )

    assert facts.system_claude is False
    report = run_preflight(facts)
    failures = [(item.check, item.fix.target) for item in report.items if item.fix is not None]
    assert ("system_claude", "install_harness") in failures


@pytest.mark.usefixtures("coral_policy_registry")
def test_a_profile_ref_plans_with_its_base_stance() -> None:
    from coral.omni.server.preflight import plan_preflight_steps
    from tests.coral.workflow_builders import arrow, compile_text, end, start, step, workflow_text

    graph, _source_map = compile_text(
        workflow_text(
            [start(), step("review", ["reviewer/strict-review"]), end()],
            [arrow("a1", "start", "review"), arrow("a2", "review", "end")],
        )
    )

    plans = plan_preflight_steps(graph, "demo")

    assert [plan.step_ref for plan in plans] == ["orchestrator", "review:0"]


# Only a decision starts the orchestrator, whose claude-sdk CLI runs in a read-only OS sandbox.
_ORCHESTRATOR_WORKFLOWS = {
    "decision": (
        [("orchestrator", "claude-sdk", True)],
        ["auth", "host_online", "sandbox", "system_claude"],
    ),
    "step-without-decision": (
        [("orchestrator", "claude-sdk", False), ("middle:0", "claude-sdk", True)],
        ["auth", "host_online", "sandbox", "system_claude"],
    ),
    "gate": ([("orchestrator", "claude-sdk", False)], ["auth", "host_online"]),
}


@pytest.mark.usefixtures("coral_policy_registry")
@pytest.mark.parametrize("workflow", list(_ORCHESTRATOR_WORKFLOWS))
async def test_the_orchestrator_needs_a_sandbox_and_claude_only_for_a_decision(
    config_home: Path, workflow: str
) -> None:
    from coral.omni.server.preflight import plan_preflight_steps
    from tests.coral.workflow_builders import (
        arrow,
        compile_text,
        decision,
        end,
        gate,
        start,
        step,
        workflow_text,
    )

    expected_needs, expected_checks = _ORCHESTRATOR_WORKFLOWS[workflow]
    middle, outgoing = {
        "decision": (decision("middle"), [{"label": "approved"}, {"label": "rejected"}]),
        "step-without-decision": (step("middle", ["reviewer"]), [{}]),
        "gate": (gate("middle", outcomes=["approve"]), [{"label": "approve"}]),
    }[workflow]
    arrows = [
        arrow(f"a{index}", "middle", "end", **fields)
        for index, fields in enumerate(outgoing, start=2)
    ]
    graph, _source_map = compile_text(
        workflow_text([start(), middle, end()], [arrow("a1", "start", "middle"), *arrows])
    )
    steps = plan_preflight_steps(graph, "demo")

    facts = await gather_preflight_facts(
        _online_registry(["os_sandbox:darwin_seatbelt"]), host_id=HOST_ID, steps=steps
    )

    needs = [(plan.step_ref, plan.harness, plan.needs_fs_sandbox) for plan in facts.steps]
    assert needs == expected_needs
    assert [item.check for item in run_preflight(facts).items] == expected_checks
