"""Authoring models: the shape of a workflow YAML document."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from coral.model.ids import RESERVED_WORKFLOW_IDS as RESERVED_WORKFLOW_IDS
from coral.model.ids import validate_workflow_id
from coral.model.ir import PartKind

# Node, arrow and part ids exclude "." so ``node.part`` references split cleanly.
ELEMENT_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class _Authoring(BaseModel):
    """Base for authoring models: unknown keys and implicit coercion are errors."""

    model_config = ConfigDict(extra="forbid", strict=True)


def _check_element_slug(value: str) -> str:
    if not ELEMENT_SLUG_PATTERN.match(value):
        raise ValueError(
            f"{value!r} is not a valid id; use 1-64 characters from a-z, 0-9, '_' and '-', "
            "starting with a letter or digit"
        )
    return value


class PartSpec(_Authoring):
    """A named output of a node that downstream nodes can reference."""

    name: str
    kind: PartKind = "text"

    @field_validator("name")
    @classmethod
    def _slug(cls, value: str) -> str:
        return _check_element_slug(value)


class _NodeBase(_Authoring):
    id: str
    name: str | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        return _check_element_slug(value)


class StartNode(_NodeBase):
    """Entry point of the workflow."""

    kind: Literal["start"]


class EndNode(_NodeBase):
    """Terminal node of the workflow."""

    kind: Literal["end"]


class StepNode(_NodeBase):
    """Work done by one or more agents."""

    kind: Literal["step"]
    goal: str = Field(min_length=1)
    roster: list[str] = Field(min_length=1)
    harness: str | None = None
    attempts: int | None = Field(default=None, ge=1)
    concurrency: int | None = Field(default=None, ge=1)
    list_from: str | None = None
    parts: list[PartSpec] = Field(default_factory=list)


class DecisionNode(_NodeBase):
    """Automatic branch chosen by label."""

    kind: Literal["decision"]
    question: str | None = None


class GateNode(_NodeBase):
    """Human approval point whose outcomes select the outgoing arrow."""

    kind: Literal["gate"]
    prompt: str | None = None
    outcomes: list[str] = Field(default_factory=lambda: ["approve", "reject"], min_length=1)


AuthoringNode = Annotated[
    StartNode | EndNode | StepNode | DecisionNode | GateNode,
    Field(discriminator="kind"),
]


class Arrow(_Authoring):
    """A directed edge between two nodes."""

    id: str
    from_node: str = Field(alias="from")
    to: str
    label: str | None = Field(default=None, min_length=1)
    back: bool = False
    limit: int | None = None
    at_limit: str | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        return _check_element_slug(value)


class Workflow(_Authoring):
    """A complete workflow document."""

    id: str
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    nodes: list[AuthoringNode]
    arrows: list[Arrow]

    @field_validator("id")
    @classmethod
    def _workflow_slug(cls, value: str) -> str:
        return validate_workflow_id(value)
