"""The seed-to-bundle transform is deterministic and always stamps hygiene last."""

from __future__ import annotations

from pathlib import Path

import pydantic
import pytest
import yaml

from coral.profiles.bundle_spec import (
    HYGIENE,
    Stance,
    StepRef,
    build_seed_bundle_yaml,
    build_step_bundle_yaml,
    step_agent_name,
)
from coral.profiles.seeds import load_seed

GOLDEN = Path(__file__).with_name("golden") / "reviewer_demo-flow_review_m0.yaml"
REVIEW = StepRef(workflow_id="demo.flow", node_id="review", roster_index=0)


def test_reviewer_bundle_matches_the_golden_file() -> None:
    built = build_step_bundle_yaml(REVIEW, Stance.REVIEWER, model="m", provider="p")

    assert built == GOLDEN.read_bytes()
    config = yaml.safe_load(built)
    assert config["name"] == "coral__demo-flow__review__m0"
    assert config["executor"]["auth"] == {"type": "provider", "name": "p"}
    assert b"api_key" not in built


def test_without_a_provider_the_bundle_has_no_auth() -> None:
    config = yaml.safe_load(
        build_step_bundle_yaml(REVIEW, Stance.REVIEWER, model=None, provider=None)
    )

    assert "auth" not in config["executor"]
    assert "model" not in config["executor"]


@pytest.mark.parametrize("stance", list(Stance))
def test_builds_repeat_byte_for_byte_and_carry_no_run_identity(stance: Stance) -> None:
    first = build_step_bundle_yaml(REVIEW, stance, model="m", provider="p")
    second = build_step_bundle_yaml(
        StepRef(workflow_id="demo.flow", node_id="review", roster_index=0),
        stance,
        model="m",
        provider="p",
    )

    assert first == second
    generated = yaml.safe_load(first)["params"]["coral"]["generated"]
    assert generated == {
        "generator_version": 1,
        "seed": {"name": stance.value, "sha256": load_seed(stance.value).sha256},
        "stance": stance.value,
        "workflow_id": "demo.flow",
        "node_id": "review",
        "roster_index": 0,
    }


def test_hygiene_overrides_a_seed_that_tries_to_loosen_it(monkeypatch: pytest.MonkeyPatch) -> None:
    loose = load_seed("implementer").model_copy(
        update={
            "config": {
                **load_seed("implementer").config,
                "spawn": True,
                "tools": {"agents": ["helper"], "timeout": 30},
                "skills": "all",
                "tool_groups": {"browser": True},
            }
        }
    )
    monkeypatch.setattr("coral.profiles.bundle_spec.load_seed", lambda _name: loose)

    config = yaml.safe_load(
        build_step_bundle_yaml(REVIEW, Stance.IMPLEMENTER, model=None, provider=None)
    )

    for key, forced in HYGIENE.items():
        if key == "tools":
            assert config["tools"] == {"agents": [], "timeout": 30}
        else:
            assert config[key] == forced
    assert set(config["guardrails"]["policies"]) == {"deny_vendor_ask"}


def test_seed_bundles_are_named_for_their_stance() -> None:
    for stance in Stance:
        config = yaml.safe_load(build_seed_bundle_yaml(stance))
        assert config["name"] == f"coral__{stance.value}"
        assert config["params"]["coral"]["generated"]["stance"] == stance.value


def test_the_anchor_agent_keeps_the_harness_default_permission_mode() -> None:
    # An owner can attach a runner to the anchor; it must not skip approvals then.
    config = yaml.safe_load(build_seed_bundle_yaml(Stance.ANCHOR))
    assert "permission_mode" not in config["executor"]["config"]


def test_step_names_map_dots_and_reject_bad_slugs() -> None:
    assert step_agent_name(StepRef(workflow_id="a.b", node_id="c.d", roster_index=3)) == (
        "coral__a-b__c-d__m3"
    )
    with pytest.raises(pydantic.ValidationError):
        StepRef(workflow_id="Bad Slug", node_id="n", roster_index=0)
    with pytest.raises(pydantic.ValidationError):
        StepRef(workflow_id="w", node_id="n", roster_index=-1)
