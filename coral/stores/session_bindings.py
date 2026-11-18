"""Session bindings: the Omnigent session a run's anchor or engine slot is bound to."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy import ColumnElement, Engine, asc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.db import (
    RunRow,
    SessionBindingRow,
    coral_engine,
    keyset_after,
    make_named_managed_session_maker,
    run_write_transaction,
    shared_read_scope,
)
from coral.db.enum_codecs import (
    SessionBindingProgress,
    SessionBindingRole,
    SlotRole,
    encode_session_binding_progress,
    encode_session_binding_role,
    encode_slot_role,
)
from coral.model.ids import anchor_session_id
from coral.stores.protocols import UNFINISHED_RUN_STATUSES


class BindingConflict(Exception):
    """A stored binding disagrees with the reservation.

    The message names only the caller's own session, slot and generation.
    ``fields`` lists the fields that differ from the session's stored binding, or
    the reservation's fields another session of the run already holds (its
    effect, or its slot and generation). ``stored`` holds the session's own stored
    binding, if any, for logs.
    """

    def __init__(
        self,
        message: str,
        *,
        fields: tuple[str, ...] = (),
        stored: SessionBinding | None = None,
    ) -> None:
        super().__init__(message)
        self.fields = fields
        self.stored = stored


class BindingNotFound(LookupError):
    """No binding is stored for the session."""


def effect_checksum(effect_key: str) -> bytes:
    """Return the sha256 digest stored for an effect key."""
    return hashlib.sha256(effect_key.encode()).digest()


@dataclass(frozen=True)
class SessionBindingDraft:
    """A binding to reserve before its session is created.

    An anchor's ``session_id`` is ``anchor_session_id(workspace_id, run_id)`` and it
    carries no slot id, slot role or host; a step carries its engine slot id and
    slot role.
    """

    workspace_id: int
    session_id: str
    run_id: str
    role: SessionBindingRole | str
    effect_key: str
    slot_id: str | None = None
    slot_role: SlotRole | str | None = None
    session_generation: int = 1
    host_id: str | None = None
    progress: SessionBindingProgress | str = SessionBindingProgress.RESERVED


@dataclass(frozen=True)
class SessionBinding:
    """A stored session binding."""

    workspace_id: int
    session_id: str
    run_id: str
    role: SessionBindingRole
    slot_id: str | None
    slot_role: SlotRole | None
    effect_cksum: bytes
    session_generation: int
    host_id: str | None
    progress: SessionBindingProgress
    created_at: int
    updated_at: int


@runtime_checkable
class SessionBindings(Protocol):
    """What the session facade, close and executors need from the binding store.

    Lookups are scoped to the caller's run. A session without a binding for the
    run is not writable: callers must not commit for it.
    """

    def reserve(self, draft: SessionBindingDraft) -> SessionBinding: ...

    def record_progress(
        self, workspace_id: int, session_id: str, progress: SessionBindingProgress | str
    ) -> SessionBinding: ...

    def get(self, workspace_id: int, session_id: str, *, run_id: str) -> SessionBinding | None: ...

    def list_for_run(self, workspace_id: int, run_id: str) -> list[SessionBinding]: ...


@runtime_checkable
class SessionBindingLookup(Protocol):
    """Classify a session without knowing its run: guards, policies and the tool bridge.

    Callers take the run, role, slot and generation from the row they read and
    act only for that run, never for one a label or a payload names.
    """

    def find_by_session(self, workspace_id: int, session_id: str) -> SessionBinding | None: ...


@runtime_checkable
class FreshBindingLookup(SessionBindingLookup, Protocol):
    """A lookup that reads the store on every call, so a binding's progress is current.

    Engine-tool planners read ``progress``, which grows after a binding is
    reserved, so a cache that keeps found rows would serve them a stale one.
    Only an implementation that reads every time sets ``reads_fresh`` to true.
    """

    @property
    def reads_fresh(self) -> bool: ...


# Fields a repeat reservation must match; the anchor keeps its first effect checksum.
_MATCHED_FIELDS = ("run_id", "role", "slot_id", "slot_role", "session_generation", "host_id")


def binding_from_draft(draft: SessionBindingDraft, now: int) -> SessionBinding:
    """Return the binding ``draft`` reserves at ``now``.

    :raises ValueError: when an anchor carries slot fields or a non-derived session
        id, or a step lacks its slot id or slot role.
    """
    role = SessionBindingRole(encode_session_binding_role(draft.role))
    slot_role = None if draft.slot_role is None else SlotRole(encode_slot_role(draft.slot_role))
    if role is SessionBindingRole.ANCHOR:
        if draft.slot_id is not None or slot_role is not None or draft.host_id is not None:
            raise ValueError("an anchor binding has no slot id, slot role or host")
        # The derived id makes the primary key allow one anchor per run.
        if draft.session_id != anchor_session_id(draft.workspace_id, draft.run_id):
            raise ValueError("an anchor binding must use the run's derived anchor session id")
    if role is SessionBindingRole.STEP and (draft.slot_id is None or slot_role is None):
        raise ValueError("a step binding needs its engine slot id and slot role")
    return SessionBinding(
        workspace_id=draft.workspace_id,
        session_id=draft.session_id,
        run_id=draft.run_id,
        role=role,
        slot_id=draft.slot_id,
        slot_role=slot_role,
        effect_cksum=effect_checksum(draft.effect_key),
        session_generation=draft.session_generation,
        host_id=draft.host_id,
        progress=SessionBindingProgress(encode_session_binding_progress(draft.progress)),
        created_at=now,
        updated_at=now,
    )


def _to_binding(row: SessionBindingRow) -> SessionBinding:
    return SessionBinding(
        workspace_id=row.workspace_id,
        session_id=row.session_id,
        run_id=row.run_id,
        role=SessionBindingRole(row.role),
        slot_id=row.slot_id,
        slot_role=None if row.slot_role is None else SlotRole(row.slot_role),
        effect_cksum=bytes(row.effect_cksum),
        session_generation=row.session_generation,
        host_id=row.host_id,
        progress=SessionBindingProgress(row.progress),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_row(binding: SessionBinding) -> SessionBindingRow:
    return SessionBindingRow(
        workspace_id=binding.workspace_id,
        session_id=binding.session_id,
        run_id=binding.run_id,
        role=int(binding.role),
        slot_id=binding.slot_id,
        slot_role=None if binding.slot_role is None else int(binding.slot_role),
        effect_cksum=binding.effect_cksum,
        session_generation=binding.session_generation,
        host_id=binding.host_id,
        progress=int(binding.progress),
        created_at=binding.created_at,
        updated_at=binding.updated_at,
    )


def adopt_binding(stored: SessionBinding, wanted: SessionBinding) -> SessionBinding:
    """Return ``stored`` when ``wanted`` reserves the same binding, else raise.

    :raises BindingConflict: naming the fields that differ.
    """
    names = _MATCHED_FIELDS
    if wanted.role is SessionBindingRole.STEP:
        names = (*names, "effect_cksum")
    fields = tuple(name for name in names if getattr(stored, name) != getattr(wanted, name))
    if fields:
        raise BindingConflict(
            f"session {wanted.session_id} is already bound with a different {', '.join(fields)}",
            fields=fields,
            stored=stored,
        )
    return stored


def effect_taken(wanted: SessionBinding) -> BindingConflict:
    """The conflict for an effect already bound to another session of the run."""
    return BindingConflict(
        f"the effect for session {wanted.session_id} is already bound to "
        "another session of this run",
        fields=("effect_cksum",),
    )


def slot_generation_taken(wanted: SessionBinding) -> BindingConflict:
    """The conflict for a slot and generation already bound to another session of the run."""
    return BindingConflict(
        f"slot {wanted.slot_id} generation {wanted.session_generation} for session "
        f"{wanted.session_id} is already bound to another session of this run",
        fields=("slot_id", "session_generation"),
    )


def is_listed_bound_session(binding: SessionBinding, run_status: int | None) -> bool:
    """Whether ``list_bound_sessions`` returns ``binding`` of a run in ``run_status``."""
    return (
        binding.role is SessionBindingRole.STEP
        and binding.progress >= SessionBindingProgress.ROW_CREATED
        and run_status in UNFINISHED_RUN_STATUSES
    )


class SqlAlchemySessionBindingStore:
    """SQLAlchemy implementation of :class:`SessionBindings` and :class:`FreshBindingLookup`."""

    # Every lookup reads the database: nothing is cached.
    reads_fresh = True

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
        self._dialect = engine.dialect.name
        self._clock = clock
        self._session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.session_bindings"
        )
        self._write_session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.session_bindings", immediate=True
        )

    def reserve(self, draft: SessionBindingDraft) -> SessionBinding:
        """Store the binding unless present; return the stored binding.

        :raises BindingConflict: when the stored binding differs in run, role, slot
            id, slot role, generation, host or (for a step) effect, or the effect,
            or the step's slot and generation, is already bound to another session
            of the run.
        :raises ValueError: when an anchor carries slot fields or a non-derived
            session id, or a step lacks its slot id or slot role.
        """
        wanted = binding_from_draft(draft, int(self._clock()))
        key = (wanted.workspace_id, wanted.session_id)

        def _reserve(session: Session) -> SessionBinding:
            stored = session.get(SessionBindingRow, key)
            if stored is not None:
                return adopt_binding(_to_binding(stored), wanted)
            session.add(_to_row(wanted))
            return wanted

        try:
            return run_write_transaction(self._write_session, "reserve", _reserve)
        except IntegrityError as exc:
            with shared_read_scope(), self._session("reserve.read_back") as session:
                stored = session.get(SessionBindingRow, key)
                if stored is not None:
                    return adopt_binding(_to_binding(stored), wanted)
                if _run_has_binding(
                    session, wanted, SessionBindingRow.effect_cksum == wanted.effect_cksum
                ):
                    raise effect_taken(wanted) from exc
                if wanted.slot_id is not None and _run_has_binding(
                    session,
                    wanted,
                    SessionBindingRow.slot_id == wanted.slot_id,
                    SessionBindingRow.session_generation == wanted.session_generation,
                ):
                    raise slot_generation_taken(wanted) from exc
            raise

    def record_progress(
        self, workspace_id: int, session_id: str, progress: SessionBindingProgress | str
    ) -> SessionBinding:
        """Raise the stored progress to ``progress``; a lower value leaves it unchanged.

        :raises BindingNotFound: when no binding is stored for the session.
        """
        target = SessionBindingProgress(encode_session_binding_progress(progress))
        now = int(self._clock())

        def _record(session: Session) -> SessionBinding:
            row = session.get(SessionBindingRow, (workspace_id, session_id), with_for_update=True)
            if row is None:
                raise BindingNotFound(f"no binding for session {session_id}")
            if target > row.progress:
                row.progress = int(target)
                row.updated_at = now
            return _to_binding(row)

        return run_write_transaction(self._write_session, "record_progress", _record)

    def get(self, workspace_id: int, session_id: str, *, run_id: str) -> SessionBinding | None:
        """Return the session's binding for ``run_id``; another run's binding reads as none."""
        binding = self._read("get", workspace_id, session_id)
        return binding if binding is not None and binding.run_id == run_id else None

    def find_by_session(self, workspace_id: int, session_id: str) -> SessionBinding | None:
        """Return the session's binding in whichever run it belongs to, else ``None``.

        Each call reads the store, so it sees progress made since an earlier read.
        """
        return self._read("find_by_session", workspace_id, session_id)

    def _read(self, operation: str, workspace_id: int, session_id: str) -> SessionBinding | None:
        with shared_read_scope(), self._session(operation) as session:
            row = session.get(SessionBindingRow, (workspace_id, session_id))
            return None if row is None else _to_binding(row)

    def list_for_run(self, workspace_id: int, run_id: str) -> list[SessionBinding]:
        """Return the run's bindings, anchor first."""
        with shared_read_scope(), self._session("list_for_run") as session:
            rows = session.scalars(
                select(SessionBindingRow)
                .where(
                    SessionBindingRow.workspace_id == workspace_id,
                    SessionBindingRow.run_id == run_id,
                )
                .order_by(asc(SessionBindingRow.role), asc(SessionBindingRow.session_id))
            ).all()
            return [_to_binding(row) for row in rows]

    def list_bound_sessions(
        self, *, cursor: tuple[int, str] | None = None, limit: int = 500
    ) -> list[SessionBinding]:
        """Return created step sessions, orchestrators included, of unfinished runs.

        Reads every workspace: runs starting, running or paused, bindings past
        ``row_created``. Keyset-paged on ``(workspace_id, session_id)``.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        stmt = (
            select(SessionBindingRow)
            .join(
                RunRow,
                (RunRow.workspace_id == SessionBindingRow.workspace_id)
                & (RunRow.id == SessionBindingRow.run_id),
            )
            .where(
                SessionBindingRow.role == int(SessionBindingRole.STEP),
                SessionBindingRow.progress >= int(SessionBindingProgress.ROW_CREATED),
                RunRow.status.in_(UNFINISHED_RUN_STATUSES),
            )
        )
        if cursor is not None:
            stmt = stmt.where(
                keyset_after(
                    (SessionBindingRow.workspace_id, SessionBindingRow.session_id),
                    cursor,
                    descending=False,
                    dialect_name=self._dialect,
                )
            )
        stmt = stmt.order_by(
            asc(SessionBindingRow.workspace_id), asc(SessionBindingRow.session_id)
        ).limit(limit)
        with shared_read_scope(), self._session("list_bound_sessions") as session:
            return [_to_binding(row) for row in session.scalars(stmt).all()]


def _run_has_binding(
    session: Session, wanted: SessionBinding, *matching: ColumnElement[bool]
) -> bool:
    """Whether another binding of ``wanted``'s run matches every condition."""
    found = session.scalars(
        select(SessionBindingRow.session_id)
        .where(
            SessionBindingRow.workspace_id == wanted.workspace_id,
            SessionBindingRow.run_id == wanted.run_id,
            *matching,
        )
        .limit(1)
    ).first()
    return found is not None


__all__ = [
    "BindingConflict",
    "BindingNotFound",
    "FreshBindingLookup",
    "SessionBinding",
    "SessionBindingDraft",
    "SessionBindingLookup",
    "SessionBindings",
    "SqlAlchemySessionBindingStore",
    "adopt_binding",
    "binding_from_draft",
    "effect_checksum",
    "effect_taken",
    "is_listed_bound_session",
    "slot_generation_taken",
]
