"""A profile revision's content: an overlay of text, model and rules on a step stance."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from coral.rules.catalog import CATALOG


class RuleStrength(StrEnum):
    """Required rules are enforced by a guardrail policy; Guidance rules are instructions."""

    REQUIRED = "required"
    GUIDANCE = "guidance"


class RuleInstance(BaseModel):
    """One catalog template attached to a profile, with params checked against the template."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    template: str
    params: dict[str, Any] = Field(default_factory=dict)
    strength: RuleStrength

    @model_validator(mode="before")
    @classmethod
    def _check_params(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("template"), str):
            return data
        template = CATALOG.get(data["template"])
        if template is None:
            raise ValueError(f"template: unknown rule template {data['template']!r}")
        try:
            params = template.params_model.model_validate(data.get("params", {}))
        except ValidationError as exc:
            problems = "; ".join(
                f"params.{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise ValueError(problems) from None
        return {**data, "params": params.model_dump(mode="json")}


class ProfileSpec(BaseModel):
    """The content of one profile revision; immutable once saved."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    # Appended to the seed's instructions.
    instructions: str = Field(default="", max_length=8000)
    # The step's executor model; None keeps the harness default.
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
    rules: list[RuleInstance] = Field(default_factory=list, max_length=16)

    @field_validator("rules")
    @classmethod
    def _one_rule_per_template(cls, rules: list[RuleInstance]) -> list[RuleInstance]:
        seen: set[str] = set()
        for rule in rules:
            if rule.template in seen:
                raise ValueError(f"rule template {rule.template!r} appears more than once")
            seen.add(rule.template)
        return rules


def canonical_json(spec: ProfileSpec) -> str:
    """The spec as compact JSON with sorted keys: equal specs give equal text."""
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
