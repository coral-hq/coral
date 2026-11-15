"""Rule registry and the input each rule receives."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from coral.model.ir import CompiledGraph
from coral.model.sourcemap import SourceMap, arrow_path, node_path
from coral.validate.context import ValidateContext
from coral.validate.problems import Problem, Severity


@dataclass(frozen=True)
class RuleInput:
    graph: CompiledGraph
    source_map: SourceMap
    ctx: ValidateContext

    def problem(
        self,
        rule: str,
        message: str,
        *,
        severity: Severity = "error",
        node_ids: tuple[str, ...] = (),
        arrow_ids: tuple[str, ...] = (),
        yaml_path: str | None = None,
        field: str | None = None,
    ) -> Problem:
        """Build a problem anchored at ``yaml_path`` or, by default, its first arrow or node."""
        path = yaml_path
        if path is None:
            path = self._default_path(node_ids, arrow_ids)
        if field is not None and path is not None:
            path = f"{path}.{field}"
        return Problem(
            rule=rule,
            severity=severity,
            message=message,
            node_ids=node_ids,
            arrow_ids=arrow_ids,
            yaml_path=path,
            range=self.source_map.lookup(path) if path is not None else None,
        )

    def _default_path(self, node_ids: tuple[str, ...], arrow_ids: tuple[str, ...]) -> str | None:
        for arrow_id in arrow_ids:
            index = self.graph.arrow_index(arrow_id)
            if index is not None:
                return arrow_path(index)
        for node_id in node_ids:
            index = self.graph.node_index(node_id)
            if index is not None:
                return node_path(index)
        return None


RuleCheck = Callable[[RuleInput], Iterable[Problem]]


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    check: RuleCheck
    # Unresolved Analysis fact codes this rule reports on.
    fact_codes: frozenset[str]


# custom-lint: disable-next=workspace-scoped-cache -- static rule registry
_RULES: dict[str, RuleSpec] = {}


def register_rule(
    rule_id: str, *, fact_codes: Iterable[str] = ()
) -> Callable[[RuleCheck], RuleCheck]:
    """Register a rule so ``validate`` runs it; later rules (V8, V9) plug in here."""

    def decorator(check: RuleCheck) -> RuleCheck:
        if rule_id in _RULES:
            raise ValueError(f"rule {rule_id} is already registered")
        _RULES[rule_id] = RuleSpec(rule_id, check, frozenset(fact_codes))
        return check

    return decorator


def registered_rules() -> tuple[RuleSpec, ...]:
    """Rules in numeric order (V1, V2, ..., V13)."""
    return tuple(sorted(_RULES.values(), key=lambda spec: int(spec.rule_id.removeprefix("V"))))
