"""Validation results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from coral.model.sourcemap import SourceRange

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class Problem:
    """One finding, anchored to nodes, arrows and a ``yaml_path``."""

    rule: str
    severity: Severity
    message: str
    node_ids: tuple[str, ...] = ()
    arrow_ids: tuple[str, ...] = ()
    yaml_path: str | None = None
    range: SourceRange | None = None


@dataclass(frozen=True)
class ValidationReport:
    """All findings; ``runnable`` is false when any error is present."""

    problems: tuple[Problem, ...]
    runnable: bool

    @property
    def errors(self) -> tuple[Problem, ...]:
        return tuple(p for p in self.problems if p.severity == "error")

    @property
    def warnings(self) -> tuple[Problem, ...]:
        return tuple(p for p in self.problems if p.severity == "warning")

    def for_rule(self, rule: str) -> tuple[Problem, ...]:
        return tuple(p for p in self.problems if p.rule == rule)
