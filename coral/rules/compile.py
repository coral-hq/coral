"""Compile profile rules into guardrail policies (Required) and instruction lines (Guidance)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from coral.profiles.spec import RuleInstance, RuleStrength
from coral.rules.catalog import CATALOG, RELATIVE_PATHS

RULE_POLICY_PREFIX = "coral_rule_"
# Required rules whose policies refuse non-relative file tool paths.
_PATH_RULES = frozenset({"stay_in_worktree", "protect_paths"})


@dataclass(frozen=True)
class GuardrailFragment:
    """What a rule set adds to a step bundle."""

    policies: dict[str, dict[str, Any]]
    # Every rule's statement, for the agent's instructions.
    statements: tuple[str, ...]


def compile_rules(rules: Sequence[RuleInstance]) -> GuardrailFragment:
    """
    Compile *rules* in catalog order, so equal rule sets give equal output.

    :param rules: Validated rules; each template appears at most once.
    :returns: A ``coral_rule_<template>`` policy per Required rule, and every
        rule's statement plus, when a Required rule checks file paths, how to
        give them.
    :raises ValueError: On a strength other than Required or Guidance.
    """
    by_template = {rule.template: rule for rule in rules}
    policies: dict[str, dict[str, Any]] = {}
    statements: list[str] = []
    for template_id, template in CATALOG.items():
        rule = by_template.get(template_id)
        if rule is None:
            continue
        params = template.params_model.model_validate(rule.params)
        if rule.strength is RuleStrength.REQUIRED:
            policies[f"{RULE_POLICY_PREFIX}{template_id}"] = template.policy(params)
        elif rule.strength is not RuleStrength.GUIDANCE:
            raise ValueError(f"rule {template_id!r} has unknown strength {rule.strength!r}")
        statements.append(template.statement(params))
    if any(f"{RULE_POLICY_PREFIX}{template_id}" in policies for template_id in _PATH_RULES):
        statements.append(RELATIVE_PATHS)
    return GuardrailFragment(policies=policies, statements=tuple(statements))
