"""Coral's engine tools are declared once, by stance, and the production catalog is empty."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import pytest

from coral.omni.runner.tool_provider import CoralToolProvider
from coral.omni.server.bundles import pack_bundle
from coral.profiles.bundle_spec import (
    Stance,
    StepRef,
    build_seed_bundle_yaml,
    build_step_bundle_yaml,
)
from coral.tools.catalog import (
    CATALOG,
    CHOOSE_ARROW,
    ENGINE_TOOL_NAMES,
    ENGINE_TOOLS,
    SUBMIT_HANDOFF,
    orchestrator_tool_names,
    tools_for_stance,
    validate_catalog,
)
from coral.tools.schemas import CHOOSE_ARROW_PARAMETERS, SUBMIT_HANDOFF_PARAMETERS
from omnigent.server.bundles import validate_agent_bundle
from omnigent.tools.manager import ToolManager
from tests.tools.test_extensions import installed_tool_providers

REVIEW = StepRef(workflow_id="demo.flow", node_id="review", roster_index=0)

# The seed bundle of every stance and a step bundle of every stance a slot can run.
_BUNDLES = [
    *[
        pytest.param(stance, build_seed_bundle_yaml(stance), id=f"seed-{stance}")
        for stance in Stance
    ],
    *[
        pytest.param(
            stance,
            build_step_bundle_yaml(REVIEW, stance, model=None, provider=None),
            id=f"step-{stance}",
        )
        for stance in Stance
        if stance is not Stance.ANCHOR
    ],
]


def test_production_catalog_is_empty() -> None:
    assert CATALOG == ()
    validate_catalog(ENGINE_TOOLS)
    assert ENGINE_TOOLS == (SUBMIT_HANDOFF, CHOOSE_ARROW)
    assert [tools_for_stance(ENGINE_TOOLS, stance.value) for stance in Stance] == [
        (),
        (CHOOSE_ARROW,),
        (SUBMIT_HANDOFF,),
        (SUBMIT_HANDOFF,),
    ]
    assert [tools_for_stance(CATALOG, stance.value) for stance in Stance] == [()] * len(Stance)
    # The orchestrator allowlist and the exact-name exemptions do not depend on
    # what production advertises.
    assert orchestrator_tool_names() == frozenset({"coral_choose_arrow"})
    assert sorted(ENGINE_TOOL_NAMES) == ["coral_choose_arrow", "coral_submit_handoff"]


def test_a_schema_is_a_fresh_openai_tool_schema() -> None:
    schema: dict[str, Any] = SUBMIT_HANDOFF.schema()

    assert schema == {
        "type": "function",
        "function": {
            "name": "coral_submit_handoff",
            "description": SUBMIT_HANDOFF.description,
            "parameters": SUBMIT_HANDOFF.parameters,
        },
    }
    # A caller that edits its copy cannot change the declaration.
    schema["function"]["parameters"]["required"].append("label")
    assert SUBMIT_HANDOFF.schema() != schema


@pytest.mark.parametrize(
    ("parameters", "required", "max_lengths"),
    [
        (
            SUBMIT_HANDOFF_PARAMETERS,
            ["activation_id", "status", "report"],
            {"activation_id": 512, "report": 8000, "blocked_reason": 2000, "label": 200},
        ),
        (
            CHOOSE_ARROW_PARAMETERS,
            ["decision_id", "label", "reason"],
            {"decision_id": 512, "label": 200, "reason": 4000},
        ),
    ],
    ids=["submit_handoff", "choose_arrow"],
)
def test_parameters_are_closed_and_bounded(
    parameters: Any, required: list[str], max_lengths: dict[str, int]
) -> None:
    properties = parameters["properties"]

    assert (parameters["required"], parameters["additionalProperties"]) == (required, False)
    assert {name: properties[name]["maxLength"] for name in max_lengths} == max_lengths
    assert all(properties[name]["minLength"] == 1 for name in max_lengths)


def test_a_handoff_offers_only_its_enums() -> None:
    properties: Any = SUBMIT_HANDOFF_PARAMETERS["properties"]

    assert properties["status"]["enum"] == ["done", "blocked"]
    # A refresh note would always be refused and counted, so it is not offered.
    assert (properties["kind"]["enum"], properties["kind"]["default"]) == (["handoff"], "handoff")
    assert properties["artifacts"]["maxItems"] == 50
    assert properties["artifacts"]["items"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 1024,
    }


def test_instructions_name_the_tool_and_never_say_keep_working() -> None:
    for decl in ENGINE_TOOLS:
        assert decl.name in decl.instructions
        assert "keep working" not in decl.instructions.casefold()
    assert "ToolSearch" in SUBMIT_HANDOFF.instructions
    assert "stop" in SUBMIT_HANDOFF.instructions.casefold()


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"name": "submit_handoff"}, "start with coral_"),
        ({"name": "coral__submit"}, "must not contain __"),
        ({"name": "coral_submit handoff"}, "not a valid tool name"),
        ({"name": "coral_" + "x" * 59}, "not a valid tool name"),
        ({"stances": frozenset({"anchor"})}, "stance"),
        ({"stances": frozenset({"planner"})}, "stance"),
    ],
    ids=["no_prefix", "double_underscore", "space", "too_long", "anchor", "unknown_stance"],
)
def test_validate_catalog_refuses_bad_declarations(change: dict[str, Any], problem: str) -> None:
    bad = dataclasses.replace(SUBMIT_HANDOFF, **change)

    with pytest.raises(ValueError, match=problem):
        validate_catalog((bad,))


def test_validate_catalog_refuses_a_duplicate_name() -> None:
    twin = dataclasses.replace(CHOOSE_ARROW, name=SUBMIT_HANDOFF.name)

    with pytest.raises(ValueError, match="declared twice"):
        validate_catalog((SUBMIT_HANDOFF, twin))


@pytest.mark.parametrize(("stance", "config_yaml"), _BUNDLES)
def test_engine_tools_never_collide_with_seed_tools(
    stance: Stance, config_yaml: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    spec = validate_agent_bundle(pack_bundle(config_yaml), enforce_handler_allowlist=False)
    with installed_tool_providers():
        baseline = ToolManager(spec, os_env_schema_only=True).get_tool_names()
    with (
        installed_tool_providers(CoralToolProvider(ENGINE_TOOLS)),
        caplog.at_level(logging.ERROR, logger="omnigent.tools.extensions"),
    ):
        names = ToolManager(spec, os_env_schema_only=True).get_tool_names()

    offered = [decl.name for decl in tools_for_stance(ENGINE_TOOLS, stance.value)]
    assert not {decl.name for decl in ENGINE_TOOLS} & set(baseline)
    # Each offered tool is registered after the bundle's own tools, none skipped as a clash.
    assert names == [*baseline, *offered]
    assert caplog.records == []
