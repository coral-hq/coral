"""Slim workflow definition store: YAML and compiled IR inline, size-capped."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Engine, select

from coral.db.models_workflows import MAX_STORED_BYTES, WorkflowRow
from coral.model import CompiledGraph
from omnigent.db.compression import encode
from omnigent.db.utils import make_named_managed_session_maker

_RUNNABLE = "runnable"
_NOT_RUNNABLE = "not_runnable"


class WorkflowTooLargeError(ValueError):
    """The framed value would exceed the inline storage cap."""


@dataclass(frozen=True)
class WorkflowDefinition:
    workspace_id: int
    id: str
    workflow_key: str
    name: str
    yaml_text: str
    compiled: CompiledGraph
    content_hash: str
    runnable: bool
    created_at: int
    updated_at: int


class WorkflowDefinitionStore(Protocol):
    def save(
        self,
        *,
        workspace_id: int,
        workflow_key: str,
        name: str,
        yaml_text: str,
        compiled: CompiledGraph,
        runnable: bool,
    ) -> WorkflowDefinition: ...

    def get(self, *, workspace_id: int, workflow_id: str) -> WorkflowDefinition | None: ...

    def get_by_key(self, *, workspace_id: int, workflow_key: str) -> WorkflowDefinition | None: ...

    def list_definitions(self, *, workspace_id: int) -> list[WorkflowDefinition]: ...


def _check_size(field: str, value: str) -> None:
    framed = encode(value)
    assert framed is not None
    if len(framed) > MAX_STORED_BYTES:
        raise WorkflowTooLargeError(
            f"{field} is {len(framed)} bytes after compression; the limit is "
            f"{MAX_STORED_BYTES}. Shorten the workflow."
        )


def _to_definition(row: WorkflowRow) -> WorkflowDefinition:
    return WorkflowDefinition(
        workspace_id=row.workspace_id,
        id=row.id,
        workflow_key=row.workflow_key,
        name=row.name,
        yaml_text=row.yaml_text,
        compiled=CompiledGraph.model_validate_json(row.compiled_json),
        content_hash=bytes(row.content_hash).hex(),
        runnable=row.validation_state == _RUNNABLE,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlWorkflowDefinitionStore:
    """Persists definitions in ``coral_workflows``; saving unchanged content is a no-op."""

    def __init__(self, engine: Engine, *, clock: Callable[[], int] | None = None) -> None:
        self._clock = clock or (lambda: int(time.time()))
        self._session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.workflow_store"
        )
        self._write_session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.workflow_store", immediate=True
        )

    def save(
        self,
        *,
        workspace_id: int,
        workflow_key: str,
        name: str,
        yaml_text: str,
        compiled: CompiledGraph,
        runnable: bool,
    ) -> WorkflowDefinition:
        """Insert or update the definition for ``workflow_key``.

        :raises WorkflowTooLargeError: when the YAML or compiled JSON exceeds the cap.
        """
        compiled_json = compiled.model_dump_json()
        _check_size("yaml_text", yaml_text)
        _check_size("compiled_json", compiled_json)
        content_hash = bytes.fromhex(compiled.content_hash)
        state = _RUNNABLE if runnable else _NOT_RUNNABLE
        now = self._clock()
        with self._write_session("save_definition") as session:
            row = session.scalars(
                select(WorkflowRow).where(
                    WorkflowRow.workspace_id == workspace_id,
                    WorkflowRow.workflow_key == workflow_key,
                )
            ).one_or_none()
            if row is None:
                row = WorkflowRow(
                    workspace_id=workspace_id,
                    id=uuid.uuid4().hex,
                    workflow_key=workflow_key,
                    name=name,
                    yaml_text=yaml_text,
                    compiled_json=compiled_json,
                    content_hash=content_hash,
                    validation_state=state,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            elif (
                bytes(row.content_hash) != content_hash
                or row.yaml_text != yaml_text
                or row.validation_state != state
                or row.name != name
            ):
                row.name = name
                row.yaml_text = yaml_text
                row.compiled_json = compiled_json
                row.content_hash = content_hash
                row.validation_state = state
                row.updated_at = now
            session.flush()
            return _to_definition(row)

    def get(self, *, workspace_id: int, workflow_id: str) -> WorkflowDefinition | None:
        with self._session("get_definition") as session:
            row = session.get(WorkflowRow, (workspace_id, workflow_id))
            return _to_definition(row) if row is not None else None

    def get_by_key(self, *, workspace_id: int, workflow_key: str) -> WorkflowDefinition | None:
        with self._session("get_definition_by_key") as session:
            row = session.scalars(
                select(WorkflowRow).where(
                    WorkflowRow.workspace_id == workspace_id,
                    WorkflowRow.workflow_key == workflow_key,
                )
            ).one_or_none()
            return _to_definition(row) if row is not None else None

    def list_definitions(self, *, workspace_id: int) -> list[WorkflowDefinition]:
        with self._session("list_definitions") as session:
            rows = session.scalars(
                select(WorkflowRow)
                .where(WorkflowRow.workspace_id == workspace_id)
                .order_by(WorkflowRow.workflow_key)
            ).all()
            return [_to_definition(row) for row in rows]
