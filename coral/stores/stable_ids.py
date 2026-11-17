"""Stable ids: message item ids the engine sent, recorded before each send."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.db import (
    StableIdRow,
    coral_engine,
    make_named_managed_session_maker,
    run_write_transaction,
    shared_read_scope,
)
from coral.db.enum_codecs import StableIdKind, encode_stable_id_kind
from coral.stores.session_bindings import effect_checksum


class StableIdConflict(Exception):
    """The stable id is recorded for a different send.

    The message names only the caller's stable id; ``fields`` lists what differs
    and ``stored`` holds the stored record for logs.
    """

    def __init__(
        self,
        message: str,
        *,
        fields: tuple[str, ...] = (),
        stored: StableIdRecord | None = None,
    ) -> None:
        super().__init__(message)
        self.fields = fields
        self.stored = stored


def content_checksum(content: str) -> bytes:
    """Return the sha256 digest stored for the exact message text the engine sends."""
    return hashlib.sha256(content.encode()).digest()


@dataclass(frozen=True)
class StableIdRecord:
    """A recorded engine send."""

    workspace_id: int
    stable_id: str
    run_id: str
    session_id: str
    effect_cksum: bytes
    content_cksum: bytes
    kind: StableIdKind
    session_generation: int
    created_at: int


@runtime_checkable
class StableIds(Protocol):
    """What the send and close executors need to tell engine items from user items.

    Lookups are scoped to the caller's run; another run's record reads as none.
    """

    def record_send(
        self,
        workspace_id: int,
        *,
        stable_id: str,
        run_id: str,
        session_id: str,
        effect_key: str,
        kind: StableIdKind | str,
        generation: int,
        content: str,
    ) -> None: ...

    def lookup(
        self, workspace_id: int, stable_id: str, *, run_id: str
    ) -> StableIdRecord | None: ...

    def list_for_session(
        self, workspace_id: int, session_id: str, *, run_id: str
    ) -> frozenset[str]: ...

    def checksums_for_session(
        self, workspace_id: int, session_id: str, *, run_id: str
    ) -> dict[str, bytes]: ...


# Every field a repeat record must match.
_MATCHED_FIELDS = (
    "run_id",
    "session_id",
    "effect_cksum",
    "content_cksum",
    "kind",
    "session_generation",
)


def _to_record(row: StableIdRow) -> StableIdRecord:
    return StableIdRecord(
        workspace_id=row.workspace_id,
        stable_id=row.stable_id,
        run_id=row.run_id,
        session_id=row.session_id,
        effect_cksum=bytes(row.effect_cksum),
        content_cksum=bytes(row.content_cksum),
        kind=StableIdKind(row.kind),
        session_generation=row.session_generation,
        created_at=row.created_at,
    )


def _check_same_send(row: StableIdRow, wanted: StableIdRecord) -> None:
    stored = _to_record(row)
    fields = tuple(
        name for name in _MATCHED_FIELDS if getattr(stored, name) != getattr(wanted, name)
    )
    if fields:
        raise StableIdConflict(
            f"stable id {wanted.stable_id} is already recorded with a different "
            f"{', '.join(fields)}",
            fields=fields,
            stored=stored,
        )


class SqlAlchemyStableIdStore:
    """SQLAlchemy implementation of :class:`StableIds`."""

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
            engine, query_name_prefix="coral.stable_ids"
        )
        self._write_session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.stable_ids", immediate=True
        )

    def record_send(
        self,
        workspace_id: int,
        *,
        stable_id: str,
        run_id: str,
        session_id: str,
        effect_key: str,
        kind: StableIdKind | str,
        generation: int,
        content: str,
    ) -> None:
        """Record the send and the checksum of its exact ``content`` unless already recorded.

        :raises StableIdConflict: when the id is recorded with a different run,
            session, effect, content, kind or generation.
        """
        wanted = StableIdRecord(
            workspace_id=workspace_id,
            stable_id=stable_id,
            run_id=run_id,
            session_id=session_id,
            effect_cksum=effect_checksum(effect_key),
            content_cksum=content_checksum(content),
            kind=StableIdKind(encode_stable_id_kind(kind)),
            session_generation=generation,
            created_at=int(self._clock()),
        )
        key = (workspace_id, stable_id)

        def _record(session: Session) -> None:
            stored = session.get(StableIdRow, key)
            if stored is not None:
                _check_same_send(stored, wanted)
                return
            session.add(
                StableIdRow(
                    workspace_id=wanted.workspace_id,
                    stable_id=wanted.stable_id,
                    run_id=wanted.run_id,
                    session_id=wanted.session_id,
                    effect_cksum=wanted.effect_cksum,
                    content_cksum=wanted.content_cksum,
                    kind=int(wanted.kind),
                    session_generation=wanted.session_generation,
                    created_at=wanted.created_at,
                )
            )

        try:
            run_write_transaction(self._write_session, "record_send", _record)
        except IntegrityError:
            with shared_read_scope(), self._session("record_send.read_back") as session:
                stored = session.get(StableIdRow, key)
                if stored is None:
                    raise
                _check_same_send(stored, wanted)

    def lookup(self, workspace_id: int, stable_id: str, *, run_id: str) -> StableIdRecord | None:
        """Return the record for ``run_id``; another run's record reads as none."""
        with shared_read_scope(), self._session("lookup") as session:
            row = session.get(StableIdRow, (workspace_id, stable_id))
            if row is None or row.run_id != run_id:
                return None
            return _to_record(row)

    def list_for_session(
        self, workspace_id: int, session_id: str, *, run_id: str
    ) -> frozenset[str]:
        """Return every stable id the engine recorded for the session within ``run_id``."""
        with shared_read_scope(), self._session("list_for_session") as session:
            return frozenset(
                session.scalars(
                    select(StableIdRow.stable_id).where(
                        StableIdRow.workspace_id == workspace_id,
                        StableIdRow.session_id == session_id,
                        StableIdRow.run_id == run_id,
                    )
                ).all()
            )

    def checksums_for_session(
        self, workspace_id: int, session_id: str, *, run_id: str
    ) -> dict[str, bytes]:
        """Map every stable id the engine recorded for the session within ``run_id`` to the
        checksum of the text it sent under it."""
        with shared_read_scope(), self._session("checksums_for_session") as session:
            rows = session.execute(
                select(StableIdRow.stable_id, StableIdRow.content_cksum).where(
                    StableIdRow.workspace_id == workspace_id,
                    StableIdRow.session_id == session_id,
                    StableIdRow.run_id == run_id,
                )
            ).all()
            return {stable_id: bytes(content_cksum) for stable_id, content_cksum in rows}


__all__ = [
    "SqlAlchemyStableIdStore",
    "StableIdConflict",
    "StableIdRecord",
    "StableIds",
    "content_checksum",
]
