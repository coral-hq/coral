"""Saved Simulate cases: a script and the result it should give, checked against a graph."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from coral.engine.simulate import SimOutcome, SimScript, check_script_text, simulate
from coral.model.ir import CompiledGraph
from coral.model.loader import LoadError, load_yaml_data

MAX_CASE_NAME_CHARS = 120
# Checking a file runs one simulation per case.
MAX_CASES = 64
# Far above any simulation's total, so a mismatch line stays short to print.
MAX_EXPECTED_SESSIONS = 1_000_000

CaseName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_CASE_NAME_CHARS),
    AfterValidator(check_script_text),
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SimExpect(_Frozen):
    """What a case expects; only the fields it sets are compared.

    ``steps`` holds ``node_id:result`` per answered step, in order; ``sessions`` the total.
    """

    outcome: SimOutcome
    steps: tuple[str, ...] | None = None
    gates_reached: tuple[str, ...] | None = None
    limits_hit: tuple[str, ...] | None = None
    sessions: int | None = Field(default=None, ge=0, le=MAX_EXPECTED_SESSIONS)


class SimCase(_Frozen):
    name: CaseName
    script: SimScript
    expect: SimExpect


class SimCaseFile(_Frozen):
    cases: tuple[SimCase, ...] = Field(min_length=1, max_length=MAX_CASES)

    @model_validator(mode="after")
    def _unique_names(self) -> SimCaseFile:
        names = [case.name for case in self.cases]
        if len(set(names)) != len(names):
            raise ValueError("case names must be unique")
        return self


class CaseResult(_Frozen):
    name: str
    passed: bool
    # One line per differing field, e.g. "outcome: expected completed, got paused".
    mismatches: tuple[str, ...]


def load_cases(text: str) -> SimCaseFile:
    """Parse a ``.sim.yaml`` case file under the workflow loader's YAML guards.

    Only JSON-compatible YAML is read: no timestamps, sets, binary or ordered maps.

    :raises ValueError: when the YAML is refused or the document is not a valid case file.
    """
    data = load_yaml_data(text)
    if isinstance(data, LoadError):
        raise ValueError(f"{data.code}: {data.message}")
    return SimCaseFile.model_validate(data)


def check_case(graph: CompiledGraph, case: SimCase, *, max_activations: int) -> CaseResult:
    """Simulate ``case`` on ``graph`` and compare the fields its expectation sets."""
    result = simulate(graph, case.script, max_activations=max_activations).result
    expect = case.expect
    actual: dict[str, object] = {
        "outcome": result.outcome,
        "steps": tuple(f"{item.node_id}:{item.result}" for item in result.steps),
        "gates_reached": result.gates_reached,
        "limits_hit": result.limits_hit,
        "sessions": result.sessions.total,
    }
    expected: dict[str, object] = {
        "outcome": expect.outcome,
        "steps": expect.steps,
        "gates_reached": expect.gates_reached,
        "limits_hit": expect.limits_hit,
        "sessions": expect.sessions,
    }
    mismatches = tuple(
        f"{field}: expected {_show(wanted)}, got {_show(actual[field])}"
        for field, wanted in expected.items()
        if wanted is not None and wanted != actual[field]
    )
    return CaseResult(name=case.name, passed=not mismatches, mismatches=mismatches)


def _show(value: object) -> str:
    if isinstance(value, tuple):
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)
