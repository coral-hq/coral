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


def _coral_step(*, auth: ProviderAuth | None = None, os_env: OSEnvSpec | None = None) -> StepPlan:
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
    return StepPlan(step_ref="review", spec=spec)


def _online_registry(capabilities: list[str]) -> HostRegistry:
    registry = HostRegistry()
    hello = HostHelloFrame(
        version="0.22.0", frame_protocol_version=1, name="laptop", capabilities=capabilities
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
