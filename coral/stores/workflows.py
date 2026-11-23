"""
Slim workflow definition store: YAML and compiled IR inline, size-capped, owned by user.

A definition belongs to the user who saved it (``None`` for the single local user).
Reads see the owner's definitions and legacy ones saved before definitions had owners;
saving a key another owner holds is refused, and the first save of a legacy one claims it.
Creating one only inserts: a key any definition holds is refused, whoever owns it.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import ColumnElement, Engine, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.db import encode, make_named_managed_session_maker
from coral.db.models_workflows import MAX_STORED_BYTES, WorkflowRow
from coral.model import CompiledGraph

_RUNNABLE = "runnable"
_NOT_RUNNABLE = "not_runnable"


class WorkflowTooLargeError(ValueError):
    """The framed value would exceed the inline storage cap."""


class WorkflowKeyTaken(Exception):
    """A definition the caller may not replace holds this workflow key in the workspace."""


@dataclass(frozen=True)
class WorkflowDefinition:
    workspace_id: int
    id: str
    # The user who saved it; ``None`` for the local user and for legacy definitions.
    user_id: str | None
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
        owner: str | None,
    ) -> WorkflowDefinition: ...

    def create(
        self,
        *,
        workspace_id: int,
        workflow_key: str,
        name: str,
        yaml_text: str,
        compiled: CompiledGraph,
        runnable: bool,
        owner: str | None,
    ) -> WorkflowDefinition: ...

    def workflow_keys(self, *, workspace_id: int, prefix: str) -> frozenset[str]: ...

    def get(
        self, *, workspace_id: int, workflow_id: str, owner: str | None
    ) -> WorkflowDefinition | None: ...

    def get_by_key(
        self, *, workspace_id: int, workflow_key: str, owner: str | None
    ) -> WorkflowDefinition | None: ...

    def list_definitions(
        self, *, workspace_id: int, owner: str | None
    ) -> list[WorkflowDefinition]: ...


def check_stored_size(field: str, value: str) -> None:
    """Raise :class:`WorkflowTooLargeError` when ``value`` framed exceeds the inline cap."""
    framed = encode(value)
    assert framed is not None
    if len(framed) > MAX_STORED_BYTES:
        raise WorkflowTooLargeError(
            f"{field} is {len(framed)} bytes after compression; the limit is "
            f"{MAX_STORED_BYTES}. Shorten the workflow."
        )


@dataclass(frozen=True)
class _Stored:
    """A definition's stored columns, checked against the inline cap."""

    yaml_text: str
    compiled_json: str
    content_hash: bytes
    validation_state: str

    @classmethod
    def of(cls, yaml_text: str, compiled: CompiledGraph, runnable: bool) -> _Stored:
        """:raises WorkflowTooLargeError: when the YAML or compiled JSON exceeds the cap."""
        compiled_json = compiled.model_dump_json()
        check_stored_size("yaml_text", yaml_text)
        check_stored_size("compiled_json", compiled_json)
        return cls(
            yaml_text=yaml_text,
            compiled_json=compiled_json,
            content_hash=bytes.fromhex(compiled.content_hash),
            validation_state=_RUNNABLE if runnable else _NOT_RUNNABLE,
        )

    def new_row(
        self, *, workspace_id: int, workflow_key: str, name: str, owner: str | None, now: int
    ) -> WorkflowRow:
        return WorkflowRow(
            workspace_id=workspace_id,
            id=uuid.uuid4().hex,
            workflow_key=workflow_key,
            name=name,
            user_id=owner,
            yaml_text=self.yaml_text,
            compiled_json=self.compiled_json,
            content_hash=self.content_hash,
            validation_state=self.validation_state,
            created_at=now,
            updated_at=now,
        )


def _visible_to(row: WorkflowRow, owner: str | None) -> bool:
    """Whether ``owner`` may read ``row``: its own, or a legacy row with no owner."""
    return row.user_id is None or row.user_id == owner


def _to_definition(row: WorkflowRow) -> WorkflowDefinition:
    return WorkflowDefinition(
        workspace_id=row.workspace_id,
        id=row.id,
        user_id=row.user_id,
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
        owner: str | None,
    ) -> WorkflowDefinition:
        """Insert or update ``owner``'s definition for ``workflow_key``.

        A legacy definition with no owner is claimed by ``owner``.

        :raises WorkflowTooLargeError: when the YAML or compiled JSON exceeds the cap.
        :raises WorkflowKeyTaken: when another owner's definition holds the key; it is
            left unchanged.
        """
        stored = _Stored.of(yaml_text, compiled, runnable)
        now = self._clock()

        def write() -> WorkflowDefinition:
            with self._write_session("save_definition") as session:
                row = self._find_by_key(
                    session, workspace_id=workspace_id, workflow_key=workflow_key
                )
                if row is None:
                    row = stored.new_row(
                        workspace_id=workspace_id,
                        workflow_key=workflow_key,
                        name=name,
                        owner=owner,
                        now=now,
                    )
                    session.add(row)
                elif not _visible_to(row, owner):
                    raise WorkflowKeyTaken(workflow_key)
                else:
                    row.user_id = owner
                    if (
                        bytes(row.content_hash) != stored.content_hash
                        or row.yaml_text != yaml_text
                        or row.validation_state != stored.validation_state
                        or row.name != name
                    ):
                        row.name = name
                        row.yaml_text = yaml_text
                        row.compiled_json = stored.compiled_json
                        row.content_hash = stored.content_hash
                        row.validation_state = stored.validation_state
                        row.updated_at = now
                session.flush()
                return _to_definition(row)

        try:
            return write()
        except IntegrityError:
            # A concurrent first save inserted the key after this one looked it up:
            # look again and apply the owner rule to the row that won.
            return write()

    def create(
        self,
        *,
        workspace_id: int,
        workflow_key: str,
        name: str,
        yaml_text: str,
        compiled: CompiledGraph,
        runnable: bool,
        owner: str | None,
    ) -> WorkflowDefinition:
        """Insert a new definition owned by ``owner``; an existing one is never changed.

        :raises WorkflowKeyTaken: when any definition holds the key, whatever its owner,
            including one a concurrent insert added after this one looked.
        :raises WorkflowTooLargeError: when the YAML or compiled JSON exceeds the cap.
        """
        stored = _Stored.of(yaml_text, compiled, runnable)
        row = stored.new_row(
            workspace_id=workspace_id,
            workflow_key=workflow_key,
            name=name,
            owner=owner,
            now=self._clock(),
        )
        try:
            with self._write_session("create_definition") as session:
                held = self._find_by_key(
                    session, workspace_id=workspace_id, workflow_key=workflow_key
                )
                if held is not None:
                    raise WorkflowKeyTaken(workflow_key)
                session.add(row)
                session.flush()
                created = _to_definition(row)
        except IntegrityError as error:
            # No retry: looking again would find the winner's row, which is not ours to change.
            raise WorkflowKeyTaken(workflow_key) from error
        return created

    def workflow_keys(self, *, workspace_id: int, prefix: str) -> frozenset[str]:
        """Every workflow key in the workspace that starts with ``prefix``, whoever owns it."""
        with self._session("find_taken_workflow_keys") as session:
            keys = session.scalars(
                select(WorkflowRow.workflow_key).where(
                    WorkflowRow.workspace_id == workspace_id,
                    WorkflowRow.workflow_key.startswith(prefix, autoescape=True),
                )
            ).all()
            return frozenset(keys)

    def _find_by_key(
        self, session: Session, *, workspace_id: int, workflow_key: str
    ) -> WorkflowRow | None:
        return session.scalars(
            select(WorkflowRow).where(
                WorkflowRow.workspace_id == workspace_id,
                WorkflowRow.workflow_key == workflow_key,
            )
        ).one_or_none()

    def get(
        self, *, workspace_id: int, workflow_id: str, owner: str | None
    ) -> WorkflowDefinition | None:
        """``owner``'s definition, or a legacy one with no owner; ``None`` for any other."""
        with self._session("get_definition") as session:
            row = session.get(WorkflowRow, (workspace_id, workflow_id))
            return _to_definition(row) if row is not None and _visible_to(row, owner) else None

    def get_by_key(
        self, *, workspace_id: int, workflow_key: str, owner: str | None
    ) -> WorkflowDefinition | None:
        """``owner``'s definition for ``workflow_key``, or a legacy one with no owner."""
        with self._session("get_definition_by_key") as session:
            row = self._find_by_key(session, workspace_id=workspace_id, workflow_key=workflow_key)
            return _to_definition(row) if row is not None and _visible_to(row, owner) else None

    def list_definitions(
        self, *, workspace_id: int, owner: str | None
    ) -> list[WorkflowDefinition]:
        """``owner``'s definitions and legacy ones with no owner, by key."""
        owned: ColumnElement[bool] = WorkflowRow.user_id.is_(None)
        if owner is not None:
            owned = or_(owned, WorkflowRow.user_id == owner)
        with self._session("list_definitions") as session:
            rows = session.scalars(
                select(WorkflowRow)
                .where(WorkflowRow.workspace_id == workspace_id, owned)
                .order_by(WorkflowRow.workflow_key)
            ).all()
            return [_to_definition(row) for row in rows if _visible_to(row, owner)]
