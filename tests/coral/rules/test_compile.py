"""Compiling rules is deterministic: Required rules become policies; every rule is stated."""

from __future__ import annotations

import pytest

from coral.profiles.spec import RuleInstance, RuleStrength
from coral.rules.catalog import RELATIVE_PATHS
from coral.rules.compile import GuardrailFragment, compile_rules

PROTECT = RuleInstance(
    template="protect_paths", params={"paths": ["infra"]}, strength=RuleStrength.REQUIRED
)
WORKTREE = RuleInstance(template="stay_in_worktree", strength=RuleStrength.REQUIRED)
BLAST = RuleInstance(template="limit_blast_radius", strength=RuleStrength.REQUIRED)


def test_no_rules_compile_to_nothing() -> None:
    assert compile_rules([]) == GuardrailFragment(policies={}, statements=())


def test_required_rules_compile_to_policies_in_catalog_order() -> None:
    fragment = compile_rules([PROTECT, WORKTREE, BLAST])

    assert list(fragment.policies) == [
        "coral_rule_limit_blast_radius",
        "coral_rule_stay_in_worktree",
        "coral_rule_protect_paths",
    ]
    assert fragment.policies["coral_rule_limit_blast_radius"] == {
        "type": "function",
        "on": ["tool_call"],
        "function": {
            "path": "omnigent.policies.builtins.orchestration.blast_radius",
            "arguments": {"risky_action": "DENY"},
        },
    }
    # Every rule is stated up front, with the path convention the path rules enforce.
    assert fragment.statements == (
        "Never run outward or destructive shell commands (push, merge, rm -rf, deploy).",
        "Only edit files inside the run's worktree.",
        "Never change files under infra/.",
        RELATIVE_PATHS,
    )


def test_compiling_is_deterministic_whatever_the_input_order() -> None:
    assert compile_rules([PROTECT, WORKTREE]) == compile_rules([WORKTREE, PROTECT])
    assert compile_rules([PROTECT]) == compile_rules([PROTECT.model_copy()])


def test_guidance_rules_compile_to_statements_only() -> None:
    fragment = compile_rules(
        [
            PROTECT.model_copy(update={"strength": RuleStrength.GUIDANCE}),
            BLAST.model_copy(update={"strength": RuleStrength.GUIDANCE}),
            WORKTREE,
        ]
    )

    assert list(fragment.policies) == ["coral_rule_stay_in_worktree"]
    assert fragment.statements == (
        "Never run outward or destructive shell commands (push, merge, rm -rf, deploy).",
        "Only edit files inside the run's worktree.",
        "Never change files under infra/.",
        RELATIVE_PATHS,
    )


def test_the_path_convention_is_stated_only_for_required_path_rules() -> None:
    fragment = compile_rules(
        [
            PROTECT.model_copy(update={"strength": RuleStrength.GUIDANCE}),
            WORKTREE.model_copy(update={"strength": RuleStrength.GUIDANCE}),
            BLAST,
        ]
    )

    assert RELATIVE_PATHS not in fragment.statements
    assert list(fragment.policies) == ["coral_rule_limit_blast_radius"]


def test_an_unknown_strength_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown strength"):
        compile_rules([WORKTREE.model_copy(update={"strength": "maybe"})])
