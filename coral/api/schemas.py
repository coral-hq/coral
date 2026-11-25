"""Request and response models of the Coral workflows API, and the API contract version."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from coral.engine.simcase import SimCase, SimExpect
from coral.engine.simulate import SimResult, SimScript
from coral.model import CompiledGraph, LoadError
from coral.validate.problems import Problem

# The version of the Coral API contract in ``coral/api/openapi.json``, not the product's.
CORAL_API_VERSION = "1"


class WorkflowYaml(BaseModel):
    """A workflow document as YAML text."""

    yaml: str


class ValidResult(BaseModel):
    """A workflow that loaded and compiled, with what validation found."""

    valid: Literal[True]
    runnable: bool
    content_hash: str
    problems: list[Problem]
    compiled: CompiledGraph


class SimulateRequest(WorkflowYaml):
    """A workflow document and the values a simulation answers with."""

    # A mistyped field would otherwise simulate with an empty script.
    model_config = ConfigDict(extra="forbid")

    script: SimScript = Field(default_factory=SimScript)


class SimulatedResult(ValidResult):
    """
    A workflow that loaded, what validation found, and its simulation.

    ``simulation`` is ``None`` when blocking problems make the workflow not runnable:
    they are reported, not simulated.
    """

    simulation: SimResult | None


class InvalidResult(BaseModel):
    """A workflow document that did not load."""

    valid: Literal[False]
    runnable: Literal[False]
    load_error: LoadError


class WorkflowSummaryOut(BaseModel):
    """A stored workflow definition as lists show it."""

    id: str
    workflow_key: str
    name: str
    content_hash: str
    runnable: bool
    created_at: int
    updated_at: int


class WorkflowDetailOut(WorkflowSummaryOut):
    """A stored workflow definition with its YAML and compiled graph."""

    yaml: str
    compiled: CompiledGraph


class SavedWorkflowOut(WorkflowSummaryOut):
    """The definition a save stored, with the validation of what was saved."""

    valid: Literal[True]
    problems: list[Problem]
    compiled: CompiledGraph


class TemplateOut(BaseModel):
    """A built-in workflow template: its workflow's id, name and description, and its YAML."""

    id: str
    name: str
    description: str
    yaml: str
    cases: list[SimCase]


class SavedCaseOut(BaseModel):
    """A workflow's saved Simulate case with the result of its last run."""

    id: str
    name: str
    script: SimScript
    expect: SimExpect
    last_result: Literal["passed", "failed", "error"] | None
    mismatches: list[str]
    last_run_at: int | None
    created_at: int


__all__ = [
    "CORAL_API_VERSION",
    "InvalidResult",
    "SavedCaseOut",
    "SavedWorkflowOut",
    "SimulateRequest",
    "SimulatedResult",
    "TemplateOut",
    "ValidResult",
    "WorkflowDetailOut",
    "WorkflowSummaryOut",
    "WorkflowYaml",
]
