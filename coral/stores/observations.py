"""Command observations: each step session's shell, write and edit calls, as evidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.db import (
    CommandObservationRow,
    coral_engine,
    make_named_managed_session_maker,
    run_write_transaction,
    shared_read_scope,
)
from coral.evidence.ir import CommandObservation, ObservedTool

_TOOL_CODES: dict[ObservedTool, int] = {"shell": 1, "write": 2, "edit": 3}
_TOOLS: dict[int, ObservedTool] = {code: tool for tool, code in _TOOL_CODES.items()}


@runtime_checkable
class ObservationStore(Protocol):
    """Where capture writes observations and the submit check reads them."""

    def record(self, workspace_id: int, run_id: str, observation: CommandObservation) -> bool:
        """Store ``observation``; ``False`` when its op key was already stored."""
        ...

    def list_for_session(
        self, workspace_id: int, session_id: str
    ) -> Sequence[CommandObservation]: ...


def _to_observation(row: CommandObservationRow) -> CommandObservation:
    return CommandObservation(
        session_id=row.session_id,
        op_key=row.op_key,
        obs_seq=row.obs_seq,
        tool=_TOOLS[row.tool],
        command=row.command,
        exit_code=row.exit_code,
        timed_out=row.timed_out,
        l1_after=row.l1_after,
        changed_path=row.changed_path,
    )


class SqlAlchemyObservationStore:
    """SQLAlchemy implementation of :class:`ObservationStore`."""

    def __init__(self, db_uri_or_engine: str | Engine) -> None:
        engine = (
            coral_engine(db_uri_or_engine)
            if isinstance(db_uri_or_engine, str)
            else db_uri_or_engine
        )
        self._session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.observations"
        )
        self._write_session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.observations", immediate=True
        )

    def record(self, workspace_id: int, run_id: str, observation: CommandObservation) -> bool:
        key = (workspace_id, observation.session_id, observation.op_key)

        def _record(session: Session) -> bool:
            if session.get(CommandObservationRow, key) is not None:
                return False
            session.add(
                CommandObservationRow(
                    workspace_id=workspace_id,
                    session_id=observation.session_id,
                    op_key=observation.op_key,
                    run_id=run_id,
                    obs_seq=observation.obs_seq,
                    tool=_TOOL_CODES[observation.tool],
                    command=observation.command,
                    exit_code=observation.exit_code,
                    timed_out=observation.timed_out,
                    l1_after=observation.l1_after,
                    changed_path=observation.changed_path,
                )
            )
            return True

        try:
            return run_write_transaction(self._write_session, "record", _record)
        except IntegrityError:
            # Another server recorded the same call first.
            with shared_read_scope(), self._session("record.read_back") as session:
                if session.get(CommandObservationRow, key) is None:
                    raise
                return False

    def list_for_session(self, workspace_id: int, session_id: str) -> Sequence[CommandObservation]:
        with shared_read_scope(), self._session("list_for_session") as session:
            rows = session.scalars(
                select(CommandObservationRow)
                .where(
                    CommandObservationRow.workspace_id == workspace_id,
                    CommandObservationRow.session_id == session_id,
                )
                .order_by(CommandObservationRow.obs_seq, CommandObservationRow.op_key)
            ).all()
            return [_to_observation(row) for row in rows]


__all__ = ["ObservationStore", "SqlAlchemyObservationStore"]
