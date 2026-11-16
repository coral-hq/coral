"""Workspace op intents: a write op recorded before its first try, with the HEAD it expects."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.db import (
    WorkspaceOpIntentRow,
    coral_engine,
    make_named_managed_session_maker,
    run_write_transaction,
    shared_read_scope,
)
from coral.db.enum_codecs import WorkspaceOpIntentOp, encode_workspace_op_intent_op


class OpIntentConflict(Exception):
    """The op key is recorded for another run, op, host or root.

    The message names only the caller's op key; ``fields`` lists what differs and
    ``stored`` holds the stored intent for logs.
    """

    def __init__(
        self,
        message: str,
        *,
        fields: tuple[str, ...] = (),
        stored: WorkspaceOpIntent | None = None,
    ) -> None:
        super().__init__(message)
        self.fields = fields
        self.stored = stored


@dataclass(frozen=True)
class WorkspaceOpIntent:
    """A recorded workspace op intent."""

    workspace_id: int
    op_key: str
    run_id: str
    op: WorkspaceOpIntentOp
    host_id: str
    root: str
    expected_head: str | None
    created_at: int


@runtime_checkable
class WorkspaceOpIntents(Protocol):
    """What the commit paths need to keep the pre-op HEAD across retries.

    Lookups are scoped to the caller's run; another run's intent reads as none.
    """

    def reserve(
        self,
        workspace_id: int,
        *,
        op_key: str,
        run_id: str,
        op: WorkspaceOpIntentOp | str,
        host_id: str,
        root: str,
        expected_head: str | None,
    ) -> WorkspaceOpIntent: ...

    def get(self, workspace_id: int, op_key: str, *, run_id: str) -> WorkspaceOpIntent | None: ...


def _to_intent(row: WorkspaceOpIntentRow) -> WorkspaceOpIntent:
    return WorkspaceOpIntent(
        workspace_id=row.workspace_id,
        op_key=row.op_key,
        run_id=row.run_id,
        op=WorkspaceOpIntentOp(row.op),
        host_id=row.host_id,
        root=row.root,
        expected_head=row.expected_head,
        created_at=row.created_at,
    )


def _adopt(row: WorkspaceOpIntentRow, wanted: WorkspaceOpIntent) -> WorkspaceOpIntent:
    """Return the stored intent, whose expected HEAD wins, when it targets the same op."""
    stored = _to_intent(row)
    fields = tuple(
        name
        for name in ("run_id", "op", "host_id", "root")
        if getattr(stored, name) != getattr(wanted, name)
    )
    if fields:
        raise OpIntentConflict(
            f"op key {wanted.op_key} is already recorded with a different {', '.join(fields)}",
            fields=fields,
            stored=stored,
        )
    return stored


class SqlAlchemyWorkspaceOpIntentStore:
    """SQLAlchemy implementation of :class:`WorkspaceOpIntents`."""

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
            engine, query_name_prefix="coral.workspace_op_intents"
        )
        self._write_session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.workspace_op_intents", immediate=True
        )

    def reserve(
        self,
        workspace_id: int,
        *,
        op_key: str,
        run_id: str,
        op: WorkspaceOpIntentOp | str,
        host_id: str,
        root: str,
        expected_head: str | None,
    ) -> WorkspaceOpIntent:
        """Record the intent unless present; return the stored one with its expected HEAD.

        :raises OpIntentConflict: when the op key targets another run, op, host or root.
        """
        wanted = WorkspaceOpIntent(
            workspace_id=workspace_id,
            op_key=op_key,
            run_id=run_id,
            op=WorkspaceOpIntentOp(encode_workspace_op_intent_op(op)),
            host_id=host_id,
            root=root,
            expected_head=expected_head,
            created_at=int(self._clock()),
        )
        key = (workspace_id, op_key)

        def _reserve(session: Session) -> WorkspaceOpIntent:
            stored = session.get(WorkspaceOpIntentRow, key)
            if stored is not None:
                return _adopt(stored, wanted)
            session.add(
                WorkspaceOpIntentRow(
                    workspace_id=wanted.workspace_id,
                    op_key=wanted.op_key,
                    run_id=wanted.run_id,
                    op=int(wanted.op),
                    host_id=wanted.host_id,
                    root=wanted.root,
                    expected_head=wanted.expected_head,
                    created_at=wanted.created_at,
                )
            )
            return wanted

        try:
            return run_write_transaction(self._write_session, "reserve", _reserve)
        except IntegrityError:
            with shared_read_scope(), self._session("reserve.read_back") as session:
                stored = session.get(WorkspaceOpIntentRow, key)
                if stored is None:
                    raise
                return _adopt(stored, wanted)

    def get(self, workspace_id: int, op_key: str, *, run_id: str) -> WorkspaceOpIntent | None:
        """Return the intent for ``run_id``; another run's intent reads as none."""
        with shared_read_scope(), self._session("get") as session:
            row = session.get(WorkspaceOpIntentRow, (workspace_id, op_key))
            if row is None or row.run_id != run_id:
                return None
            return _to_intent(row)


__all__ = [
    "OpIntentConflict",
    "SqlAlchemyWorkspaceOpIntentStore",
    "WorkspaceOpIntent",
    "WorkspaceOpIntents",
]
