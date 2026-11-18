"""Pinned workflow versions: the immutable graph a run is folded with, held inline."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.db import (
    WorkflowVersionRow,
    coral_engine,
    make_named_managed_session_maker,
    run_write_transaction,
    shared_read_scope,
)
from coral.db.enum_codecs import WorkflowVersionOrigin, WorkflowVersionStatus
from coral.model import IR_VERSION, CompiledGraph
from coral.model.ids import derived_id
from coral.model.loader import MAX_DOCUMENT_BYTES
from coral.stores.workflows import WorkflowTooLargeError, check_stored_size

_HEX32 = re.compile(r"[0-9a-f]{32}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MAX_CREATED_BY_CHARS = 128


def _check_yaml_text(yaml_text: str) -> None:
    # The loader's own ceiling, so a load never decompresses more than a document allows.
    size = len(yaml_text.encode())
    if size > MAX_DOCUMENT_BYTES:
        raise WorkflowTooLargeError(
            f"yaml_text is {size} bytes; the limit is {MAX_DOCUMENT_BYTES}. Shorten the workflow."
        )
    check_stored_size("yaml_text", yaml_text)


@dataclass(frozen=True)
class PinnedVersion:
    """A pinned workflow version and its compiled graph, analysis included."""

    workspace_id: int
    # derived_id("coral-workflow-version", workflow_id, content_hash)
    id: str
    # The definition's 32-hex id.
    workflow_id: str
    # 64 hex characters.
    content_hash: str
    graph: CompiledGraph
    yaml_text: str


def _to_pinned(row: WorkflowVersionRow) -> PinnedVersion:
    if row.compiled_json is None or row.yaml_text is None:
        raise ValueError(f"workflow version {row.id} is not stored inline")
    return PinnedVersion(
        workspace_id=row.workspace_id,
        id=row.id,
        workflow_id=row.workflow_id,
        content_hash=bytes(row.content_hash).hex(),
        graph=CompiledGraph.model_validate_json(row.compiled_json),
        yaml_text=row.yaml_text,
    )


class SqlAlchemyWorkflowVersionStore:
    """Pins compiled graphs in ``coral_workflow_versions``; a version never changes."""

    def __init__(
        self,
        db_uri_or_engine: str | Engine,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        engine = (
            coral_engine(db_uri_or_engine)
            if isinstance(db_uri_or_engine, str)
            else db_uri_or_engine
        )
        self._clock = clock
        self._session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.workflow_versions"
        )
        self._write_session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.workflow_versions", immediate=True
        )

    def pin(
        self,
        *,
        workspace_id: int,
        workflow_id: str,
        graph: CompiledGraph,
        yaml_text: str,
        created_by: str | None,
        now: int | None = None,
    ) -> PinnedVersion:
        """Store ``graph`` as an immutable version unless pinned already; return the version.

        A graph pinned before, under any YAML that compiles to it, returns the stored
        version unchanged.

        :raises WorkflowTooLargeError: when the YAML exceeds the loader's document
            limit, or the YAML or compiled JSON, compressed, the inline cap.
        :raises ValueError: when ``graph`` has no lowercase 64-hex content hash,
            ``workflow_id`` is not a 32-hex id, or ``created_by`` is too long.
        """
        if not _HEX64.fullmatch(graph.content_hash):
            raise ValueError("a pinned graph needs its lowercase 64-hex content hash")
        if not _HEX32.fullmatch(workflow_id):
            raise ValueError("workflow_id must be the definition's 32-hex id")
        if created_by is not None and len(created_by) > _MAX_CREATED_BY_CHARS:
            raise ValueError(f"created_by is longer than {_MAX_CREATED_BY_CHARS} characters")
        content_hash = bytes.fromhex(graph.content_hash)
        compiled_json = graph.model_dump_json()
        _check_yaml_text(yaml_text)
        check_stored_size("compiled_json", compiled_json)
        version_id = derived_id("coral-workflow-version", workflow_id, graph.content_hash)
        key = (workspace_id, version_id)
        created_at = int(self._clock()) if now is None else now

        def _pin(session: Session) -> PinnedVersion:
            stored = session.get(WorkflowVersionRow, key)
            if stored is not None:
                return _to_pinned(stored)
            row = WorkflowVersionRow(
                workspace_id=workspace_id,
                id=version_id,
                workflow_id=workflow_id,
                content_hash=content_hash,
                yaml_ref=None,
                yaml_bytes=len(yaml_text.encode()),
                compiled_ref=None,
                yaml_text=yaml_text,
                compiled_json=compiled_json,
                compiler_version=IR_VERSION,
                origin=int(WorkflowVersionOrigin.SAVED),
                validation_state=int(WorkflowVersionStatus.VALID),
                created_by=created_by,
                created_at=created_at,
            )
            session.add(row)
            session.flush()
            return _to_pinned(row)

        try:
            return run_write_transaction(self._write_session, "pin", _pin)
        except IntegrityError:
            # A concurrent pin of the same graph stored it first.
            pinned = self.load(workspace_id=workspace_id, version_id=version_id)
            if pinned is None:
                raise
            return pinned

    def load(self, *, workspace_id: int, version_id: str) -> PinnedVersion | None:
        """Return the pinned version, or ``None`` when the workspace has none by that id.

        :raises ValueError: when the version stores its graph by blob ref only.
        """
        with shared_read_scope(), self._session("load") as session:
            row = session.get(WorkflowVersionRow, (workspace_id, version_id))
            return None if row is None else _to_pinned(row)


__all__ = ["PinnedVersion", "SqlAlchemyWorkflowVersionStore"]
