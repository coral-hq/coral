"""A profile spec validates its rules against the catalog and serializes canonically."""

from __future__ import annotations

import json

import pydantic
import pytest

from coral.profiles.capabilities import harness_capabilities
from coral.profiles.spec import ProfileSpec, RuleInstance, RuleStrength, canonical_json


def _spec(**fields: object) -> ProfileSpec:
    return ProfileSpec.model_validate({"name": "Strict review", **fields})


def _error_locs(exc: pydantic.ValidationError) -> list[str]:
    return [".".join(str(part) for part in error["loc"]) for error in exc.errors()]


def test_a_full_spec_validates_and_normalizes_paths() -> None:
    spec = _spec(
        description="Reviews strictly.",
        instructions="Check every test.",
        model="claude-x",
        rules=[
            {"template": "protect_paths", "params": {"paths": ["infra/"]}, "strength": "required"},
            {"template": "limit_blast_radius", "strength": "guidance"},
        ],
    )

    assert spec.rules[0] == RuleInstance(
        template="protect_paths", params={"paths": ["infra"]}, strength=RuleStrength.REQUIRED
    )
    assert spec.rules[1].params == {}


def test_canonical_json_is_stable_and_sorted() -> None:
    first = _spec(rules=[{"template": "stay_in_worktree", "strength": "required"}])
    second = ProfileSpec.model_validate(json.loads(canonical_json(first)))

    assert canonical_json(first) == canonical_json(second)
    assert canonical_json(first) == (
        '{"description":"","instructions":"","model":null,"name":"Strict review",'
        '"rules":[{"params":{},"strength":"required","template":"stay_in_worktree"}]}'
    )


@pytest.mark.parametrize(
    ("rule", "loc", "message"),
    [
        ({"template": "nope", "strength": "required"}, "rules.0", "unknown rule template"),
        (
            {"template": "protect_paths", "params": {}, "strength": "required"},
            "rules.0",
            "params.paths",
        ),
        (
            {"template": "protect_paths", "params": {"paths": ["/etc"]}, "strength": "required"},
            "rules.0",
            "params.paths.0",
        ),
        (
            {"template": "protect_paths", "params": {"paths": ["a/../b"]}, "strength": "required"},
            "rules.0",
            "params.paths.0",
        ),
        (
            {"template": "protect_paths", "params": {"paths": ["a//b"]}, "strength": "required"},
            "rules.0",
            "params.paths.0",
        ),
        (
            {"template": "protect_paths", "params": {"paths": ["./a"]}, "strength": "required"},
            "rules.0",
            "params.paths.0",
        ),
        (
            {"template": "protect_paths", "params": {"paths": ["a b"]}, "strength": "required"},
            "rules.0",
            "params.paths.0",
        ),
        (
            {"template": "protect_paths", "params": {"paths": ["a"] * 11}, "strength": "required"},
            "rules.0",
            "params.paths",
        ),
        (
            {"template": "stay_in_worktree", "params": {"x": 1}, "strength": "required"},
            "rules.0",
            "params.x",
        ),
        ({"template": "stay_in_worktree", "strength": "maybe"}, "rules.0.strength", ""),
    ],
)
def test_bad_rules_are_refused_naming_the_field(
    rule: dict[str, object], loc: str, message: str
) -> None:
    with pytest.raises(pydantic.ValidationError) as refused:
        _spec(rules=[rule])

    assert loc in _error_locs(refused.value)
    assert message in str(refused.value)


@pytest.mark.parametrize(
    ("fields", "loc"),
    [
        ({"name": ""}, "name"),
        ({"name": "x" * 81}, "name"),
        ({"description": "x" * 501}, "description"),
        ({"instructions": "x" * 8001}, "instructions"),
        ({"model": "x" * 129}, "model"),
        ({"model": "-flag"}, "model"),
        ({"model": "m\nx"}, "model"),
        ({"model": ""}, "model"),
        ({"model": ""}, "model"),
        ({"api_key": "secret"}, "api_key"),
        ({"rules": [{"template": "stay_in_worktree", "strength": "required"}] * 17}, "rules"),
    ],
)
def test_field_limits(fields: dict[str, object], loc: str) -> None:
    with pytest.raises(pydantic.ValidationError) as refused:
        _spec(**fields)

    assert loc in _error_locs(refused.value)


def test_a_template_may_appear_once() -> None:
    rule = {"template": "stay_in_worktree", "strength": "required"}
    with pytest.raises(pydantic.ValidationError, match="stay_in_worktree"):
        _spec(rules=[rule, {**rule, "strength": "guidance"}])


def test_specs_are_frozen() -> None:
    with pytest.raises(pydantic.ValidationError):
        _spec().name = "other"  # type: ignore[misc]


def test_capabilities_are_static_per_harness() -> None:
    assert harness_capabilities("claude-sdk") == {
        "steering": "unknown",
        "tool_gating": "supported",
        "fs_read_only": "supported",
        "usage_reporting": "unknown",
    }
    assert set(harness_capabilities("codex").values()) == {"unknown"}
