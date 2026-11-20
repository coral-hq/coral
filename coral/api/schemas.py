"""Request and response models of the Coral workflows API, and the API contract version."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

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


__all__ = [
    "CORAL_API_VERSION",
    "InvalidResult",
    "SavedWorkflowOut",
    "ValidResult",
    "WorkflowDetailOut",
    "WorkflowSummaryOut",
    "WorkflowYaml",
]
