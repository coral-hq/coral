"""Compiled intermediate representation: a frozen, hashable workflow graph."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

IR_VERSION = 1

# Defaults filled in at compile time; part of the content hash.
DEFAULT_ATTEMPTS = 3
DEFAULT_CONCURRENCY = 1

# Reserved label marking an arrow taken when a node fails.
FAILURE_LABEL = "failure"

NodeKind = Literal["start", "end", "step", "decision", "gate"]
ArrowKind = Literal["forward", "back", "at_limit", "failure"]
JoinType = Literal["none", "and", "xor"]
PartKind = Literal["text", "list"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CompiledPart(_Frozen):
    name: str
    kind: PartKind


class CompiledNode(_Frozen):
    id: str
    kind: NodeKind
    name: str | None = None
    goal: str | None = None
    question: str | None = None
    prompt: str | None = None
    roster: tuple[str, ...] = ()
    harness: str | None = None
    attempts: int | None = None
    concurrency: int | None = None
    list_from: str | None = None
    parts: tuple[CompiledPart, ...] = ()
    outcomes: tuple[str, ...] = ()


class CompiledArrow(_Frozen):
    id: str
    source: str
    target: str
    label: str | None = None
    # Derived from the authoring fields, and hashed: ``back: true`` is recorded only here.
    kind: ArrowKind = "forward"
    limit: int | None = None
    at_limit: str | None = None


class JoinInfo(_Frozen):
    """How a node with several incoming arrows combines them."""

    node_id: str
    join_type: JoinType
    arrow_ids: tuple[str, ...]
    # Unlabelled split that makes this an AND-join.
    split_node_id: str | None = None


class LoopInfo(_Frozen):
    """A loop closed by one back-arrow."""

    back_arrow_id: str
    head: str
    tail: str
    body: tuple[str, ...]
    limit: int | None
    at_limit_arrow_id: str | None
    # Arrows entering the body from outside, by id.
    entry_arrow_ids: tuple[str, ...]


class Region(_Frozen):
    """Parallel region between an unlabelled split and its AND-join."""

    split_node_id: str
    join_node_id: str
    node_ids: tuple[str, ...]


class UnresolvedFact(_Frozen):
    """Something Analysis could not resolve; blocks running the workflow."""

    code: str
    message: str
    node_ids: tuple[str, ...] = ()
    arrow_ids: tuple[str, ...] = ()


class LabelSet(_Frozen):
    """Labels on the label-selected outgoing arrows of a node."""

    node_id: str
    labels: tuple[str, ...]
    labelled_arrow_ids: tuple[str, ...]
    unlabelled_arrow_ids: tuple[str, ...]


class CheckedPart(_Frozen):
    """Resolution of a ``list_from`` reference."""

    node_id: str
    reference: str
    source_node_id: str | None
    part_name: str | None
    source_exists: bool
    source_upstream: bool
    part_is_list: bool


class Analysis(_Frozen):
    join_types: tuple[JoinInfo, ...] = ()
    loops: tuple[LoopInfo, ...] = ()
    regions: tuple[Region, ...] = ()
    unresolved: tuple[UnresolvedFact, ...] = ()
    label_sets: tuple[LabelSet, ...] = ()
    checked_parts: tuple[CheckedPart, ...] = ()


class CompiledGraph(_Frozen):
    ir_version: int = IR_VERSION
    workflow_id: str
    name: str
    description: str | None = None
    nodes: tuple[CompiledNode, ...]
    arrows: tuple[CompiledArrow, ...]
    # Derived fields below are excluded from the content hash.
    content_hash: str = ""
    analysis: Analysis = Analysis()

    def node_index(self, node_id: str) -> int | None:
        """Position of the first node with this id in the authoring document."""
        for index, node in enumerate(self.nodes):
            if node.id == node_id:
                return index
        return None

    def arrow_index(self, arrow_id: str) -> int | None:
        """Position of the first arrow with this id in the authoring document."""
        for index, arrow in enumerate(self.arrows):
            if arrow.id == arrow_id:
                return index
        return None
