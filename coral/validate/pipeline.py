"""Load, compile and validate workflow text in one call."""

from __future__ import annotations

from dataclasses import dataclass

from coral.model import CompiledGraph, Loaded, LoadError, compile, load
from coral.validate import ValidateContext, ValidationReport, validate


@dataclass(frozen=True)
class CheckResult:
    """Outcome of checking workflow text: a load error, or a graph with its report."""

    load_error: LoadError | None = None
    loaded: Loaded | None = None
    graph: CompiledGraph | None = None
    report: ValidationReport | None = None

    @property
    def runnable(self) -> bool:
        return self.report is not None and self.report.runnable


def check_text(text: str, ctx: ValidateContext | None = None) -> CheckResult:
    loaded = load(text)
    if isinstance(loaded, LoadError):
        return CheckResult(load_error=loaded)
    graph = compile(loaded)
    return CheckResult(loaded=loaded, graph=graph, report=validate(graph, loaded.source_map, ctx))
