"""Coral's tool provider offers each stance its engine tools and makes hosts advertise Coral."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

from coral.omni.runner.tool_provider import CoralToolProvider, tool_provider
from coral.tools.catalog import CHOOSE_ARROW, ENGINE_TOOLS, SUBMIT_HANDOFF
from omnigent.spec import AgentSpec, ExecutorSpec
from omnigent.tools.extensions import (
    ExtensionToolSet,
    ToolProvider,
    extension_framework_instructions,
    extension_tool_sets,
)
from tests.tools.test_extensions import installed_tool_providers

STEP_SET = ExtensionToolSet(
    tools=(SUBMIT_HANDOFF.schema(),), framework_instructions=(SUBMIT_HANDOFF.instructions,)
)
ORCHESTRATOR_SET = ExtensionToolSet(
    tools=(CHOOSE_ARROW.schema(),), framework_instructions=(CHOOSE_ARROW.instructions,)
)
STANCES = ("anchor", "orchestrator", "implementer", "reviewer")


def _spec(stance: object, harness: str = "claude-sdk") -> AgentSpec:
    return AgentSpec(
        spec_version=1,
        executor=ExecutorSpec(type="omnigent", config={"harness": harness}),
        params={"coral": {"generated": {"stance": stance}}},
    )


def test_stance_filter_gives_the_anchor_nothing() -> None:
    provider = CoralToolProvider(ENGINE_TOOLS)

    assert provider.tool_set(_spec("implementer")) == STEP_SET
    assert provider.tool_set(_spec("reviewer")) == STEP_SET
    assert provider.tool_set(_spec("orchestrator")) == ORCHESTRATOR_SET
    assert provider.tool_set(_spec("anchor")) is None
    assert provider.tool_set(_spec("planner")) is None
    assert provider.tool_set(AgentSpec(spec_version=1)) is None
    assert provider.server_dispatched_names() == frozenset(
        {"coral_submit_handoff", "coral_choose_arrow"}
    )


def test_a_returned_tool_set_is_the_callers_own_copy() -> None:
    provider = CoralToolProvider(ENGINE_TOOLS)
    first = provider.tool_set(_spec("implementer"))
    assert first is not None

    first.tools[0]["function"]["name"] = "hijacked"

    assert provider.tool_set(_spec("implementer")) == STEP_SET
    assert provider.tool_set(_spec("reviewer")) == STEP_SET


def test_production_provider_offers_each_stance_its_engine_tools() -> None:
    provider = tool_provider()

    assert isinstance(provider, ToolProvider)
    assert [provider.tool_set(_spec(stance)) for stance in STANCES] == [
        None,
        ORCHESTRATOR_SET,
        STEP_SET,
        STEP_SET,
    ]
    assert provider.server_dispatched_names() == frozenset(
        {"coral_submit_handoff", "coral_choose_arrow"}
    )


@pytest.mark.parametrize(
    "spec",
    [
        SimpleNamespace(),
        SimpleNamespace(params=None),
        SimpleNamespace(params={"coral": "implementer"}),
        SimpleNamespace(params={"coral": {"generated": ["implementer"]}}),
        _spec(1),
        _spec(None),
    ],
    ids=[
        "no_params",
        "params_none",
        "coral_not_a_mapping",
        "generated_not_a_mapping",
        "int",
        "none",
    ],
)
def test_specs_without_a_stance_string_get_nothing(spec: Any) -> None:
    assert CoralToolProvider(ENGINE_TOOLS).tool_set(spec) is None


@pytest.mark.parametrize("harness", ["claude-native", "opencode", "native-pi"])
def test_native_harness_specs_get_no_tools_or_text(harness: str) -> None:
    # Native relays never carry extension tools, so the prompt must not name them either.
    assert CoralToolProvider(ENGINE_TOOLS).tool_set(_spec("implementer", harness)) is None


def test_tool_sets_pass_the_extension_checks() -> None:
    with installed_tool_providers(CoralToolProvider(ENGINE_TOOLS)):
        assert extension_tool_sets(_spec("implementer")) == (STEP_SET,)
        assert extension_framework_instructions(_spec("orchestrator")) == (
            CHOOSE_ARROW.instructions,
        )
        assert extension_tool_sets(_spec("anchor")) == ()


def test_host_capabilities_follow_the_disable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = tool_provider()
    monkeypatch.delenv("CORAL_DISABLE_HOST_ENTRY_POINTS", raising=False)
    assert provider.host_capabilities() == ("coral_runner:2",)

    monkeypatch.setenv("CORAL_DISABLE_HOST_ENTRY_POINTS", "1")
    assert provider.host_capabilities() == ()


def test_an_invalid_catalog_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="start with coral_"):
        CoralToolProvider((dataclasses.replace(SUBMIT_HANDOFF, name="submit_handoff"),))
