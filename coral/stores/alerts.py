"""Coral alerts: written inside run commits, listed as the owner's feed and acked by the owner."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, cast

from sqlalchemy import ColumnElement, CursorResult, Engine, asc, desc, insert, or_, select, update
from sqlalchemy.orm import InstrumentedAttribute, Session

from coral.alerts.types import LOCAL_USER_ID, generation_matches, normalize_owner
from coral.db import (
    AlertRow,
    coral_engine,
    keyset_after,
    make_named_managed_session_maker,
    query_name_scope,
    run_write_transaction,
    shared_read_scope,
)
from coral.db.enum_codecs import AlertKind, AlertPriority, AlertStatus
from coral.omni.protocols import Viewer
from coral.stores.protocols import (
    AlertDraft,
    AlertRecord,
    AlertResolution,
    TransitionTooLarge,
)

AckOutcome = Literal["acked", "unchanged", "not_found", "not_ackable"]
# (priority, created_at, id) of the last alert a feed page read.
InboxCursor = tuple[int, int, str]

MAX_ALERT_RAISES = 64
MAX_INBOX_LIMIT = 100
# Cleared by answering them, never by marking them read.
_UNACKABLE_KINDS = (int(AlertKind.GATE), int(AlertKind.QUESTION))
_UNRESOLVED_STATUSES = (int(AlertStatus.OPEN), int(AlertStatus.ACKED))
# The feed reads normal priority before low.
_INBOX_PRIORITIES = tuple(sorted(int(priority) for priority in AlertPriority))


def check_alert_raises(run_id: str, raises: Sequence[AlertDraft]) -> None:
    """Refuse a transition's alert raises before anything is written.

    Resolutions need no cap: kinds are a closed set, and the subjects are this commit's
    gate visits, decisions and pause, which the start bounds keep under 50.

    :raises TransitionTooLarge: more than 64 raises.
    :raises ValueError: a raise for another run.
    """
    if len(raises) > MAX_ALERT_RAISES:
        raise TransitionTooLarge(
            f"Transition contains {len(raises)} alert raises (limit {MAX_ALERT_RAISES})"
        )
    for draft in raises:
        if draft.run_id != run_id:
            raise ValueError(f"alert {draft.id} belongs to another run than {run_id}")


def apply_alert_changes(
    session: Session,
    *,
    workspace_id: int,
    run_id: str,
    raises: Sequence[AlertDraft],
    resolutions: Sequence[AlertResolution],
    now: int,
) -> None:
    """Write a transition's alert changes in its run commit, raises first.

    A raise inserts only an absent id (the locked run row serializes every writer of
    the run's alerts); a resolution moves the run's open or acked rows to resolved.
    """
    subjects = sorted({r.subject_id for r in resolutions if r.subject_id is not None})
    kinds = sorted({kind for r in resolutions for kind in r.kinds})
    # The transition's other pending rows flush under the transition's own name.
    with session.no_autoflush:
        if raises:
            with query_name_scope("coral.alerts.raise"):
                _insert_absent(session, workspace_id, raises, now)
        if subjects:
            with query_name_scope("coral.alerts.resolve_subject"):
                _resolve(session, workspace_id, run_id, AlertRow.subject_id.in_(subjects), now)
        if kinds:
            with query_name_scope("coral.alerts.resolve_kinds"):
                _resolve(session, workspace_id, run_id, AlertRow.kind.in_(kinds), now)


def _insert_absent(
    session: Session, workspace_id: int, raises: Sequence[AlertDraft], now: int
) -> None:
    present = set(
        session.scalars(
            select(AlertRow.id).where(
                AlertRow.workspace_id == workspace_id,
                AlertRow.id.in_({draft.id for draft in raises}),
            )
        )
    )
    rows: list[dict[str, Any]] = []
    for draft in raises:
        # The first draft of an id wins, as in a later commit.
        if draft.id in present:
            continue
        present.add(draft.id)
        rows.append(
            {
                "workspace_id": workspace_id,
                "id": draft.id,
                "run_id": draft.run_id,
                # The local user is stored as None however the draft names it.
                "owner_user_id": normalize_owner(draft.owner_user_id),
                "account_generation": draft.account_generation,
                "kind": draft.kind,
                "priority": draft.priority,
                "subject_id": draft.subject_id,
                "status": int(AlertStatus.OPEN),
                "payload": draft.payload,
                "created_at": draft.created_at or now,
            }
        )
    if rows:
        session.execute(insert(AlertRow), rows)


def _resolve(
    session: Session,
    workspace_id: int,
    run_id: str,
    matching: ColumnElement[bool],
    now: int,
) -> None:
    session.execute(
        update(AlertRow)
        .where(
            AlertRow.workspace_id == workspace_id,
            AlertRow.run_id == run_id,
            matching,
            AlertRow.status.in_(_UNRESOLVED_STATUSES),
        )
        .values(status=int(AlertStatus.RESOLVED), resolved_at=now)
    )


def generation_clause(
    recorded: InstrumentedAttribute[str | None], viewer: Viewer
) -> ColumnElement[bool]:
    """``generation_matches`` as SQL: a recorded generation needs the viewer's proven one."""
    if viewer.check_generation and viewer.account_generation is not None:
        return or_(recorded.is_(None), recorded == viewer.account_generation)
    return recorded.is_(None)


def _visible_to(viewer: Viewer, owner: str | None, alert: AlertRecord | AlertRow) -> bool:
    # Exact comparison: MySQL collations can fold case, accents or trailing spaces.
    return alert.owner_user_id == owner and generation_matches(alert.account_generation, viewer)


def _to_record(row: AlertRow) -> AlertRecord:
    return AlertRecord(
        workspace_id=row.workspace_id,
        id=row.id,
        run_id=row.run_id,
        owner_user_id=row.owner_user_id,
        account_generation=row.account_generation,
        kind=row.kind,
        priority=row.priority,
        subject_id=row.subject_id,
        status=row.status,
        payload=row.payload,
        created_at=row.created_at,
        acked_at=row.acked_at,
        acked_by=row.acked_by,
        resolved_at=row.resolved_at,
    )


class SqlAlchemyAlertStore:
    """Reads and acks of the alerts that run commits write through ``apply_alert_changes``."""

    def __init__(self, db_uri_or_engine: str | Engine) -> None:
        self._engine: Engine = (
            coral_engine(db_uri_or_engine)
            if isinstance(db_uri_or_engine, str)
            else db_uri_or_engine
        )
        self._session = make_named_managed_session_maker(
            self._engine, query_name_prefix="coral.alerts"
        )
        self._write_session = make_named_managed_session_maker(
            self._engine, query_name_prefix="coral.alerts", immediate=True
        )

    def list_inbox(
        self,
        *,
        workspace_id: int,
        viewer: Viewer,
        after: InboxCursor | None,
        limit: int,
    ) -> tuple[list[AlertRecord], InboxCursor | None]:
        """The viewer's open alerts: normal priority first, newest first within a priority.

        Rows of another owner or of a generation the viewer does not prove are dropped
        after paging, so a page can be shorter than ``limit`` and still have a cursor.

        :raises ValueError: ``limit`` is not 1-100.
        """
        if not 1 <= limit <= MAX_INBOX_LIMIT:
            raise ValueError(f"limit must be 1-{MAX_INBOX_LIMIT}, not {limit}")
        owner = normalize_owner(viewer.user_id)
        dialect = self._engine.dialect.name
        rows: list[AlertRow] = []
        with shared_read_scope(), self._session("list_inbox") as session:
            for priority in _INBOX_PRIORITIES:
                wanted = limit + 1 - len(rows)
                if wanted <= 0:
                    break
                if after is not None and priority < after[0]:
                    continue
                # Equality on the inbox index's leading columns and a backward range on
                # (created_at, id): one index range per priority, read in order, no sort.
                query = select(AlertRow).where(
                    AlertRow.workspace_id == workspace_id,
                    AlertRow.owner_user_id == owner,
                    AlertRow.status == int(AlertStatus.OPEN),
                    AlertRow.priority == priority,
                )
                if after is not None and priority == after[0]:
                    query = query.where(
                        keyset_after(
                            (AlertRow.created_at, AlertRow.id),
                            (after[1], after[2]),
                            descending=True,
                            dialect_name=dialect,
                        )
                    )
                query = query.order_by(desc(AlertRow.created_at), desc(AlertRow.id))
                rows.extend(session.scalars(query.limit(wanted)).all())
            page = [_to_record(row) for row in rows[:limit]]
        cursor = (
            (page[-1].priority, page[-1].created_at, page[-1].id) if len(rows) > limit else None
        )
        return [alert for alert in page if _visible_to(viewer, owner, alert)], cursor

    def ack(self, *, workspace_id: int, viewer: Viewer, alert_id: str, now: int) -> AckOutcome:
        """Mark one of the viewer's open alerts read.

        :returns: ``acked``; ``unchanged`` when it is already acked or resolved;
            ``not_found`` when it is absent, another owner's, or of a generation the
            viewer does not prove; ``not_ackable`` for an open gate or question.
        """
        owner = normalize_owner(viewer.user_id)

        def _ack(session: Session) -> AckOutcome:
            row = session.get(AlertRow, (workspace_id, alert_id))
            if row is None or not _visible_to(viewer, owner, row):
                return "not_found"
            if row.status != int(AlertStatus.OPEN):
                return "unchanged"
            if row.kind in _UNACKABLE_KINDS:
                return "not_ackable"
            acked = cast(
                CursorResult[Any],
                session.execute(
                    update(AlertRow)
                    .where(
                        AlertRow.workspace_id == workspace_id,
                        AlertRow.id == alert_id,
                        AlertRow.owner_user_id == owner,
                        AlertRow.status == int(AlertStatus.OPEN),
                        AlertRow.kind.not_in(_UNACKABLE_KINDS),
                        generation_clause(AlertRow.account_generation, viewer),
                    )
                    .values(
                        status=int(AlertStatus.ACKED),
                        acked_at=now,
                        acked_by=owner or LOCAL_USER_ID,
                    )
                ),
            )
            # No row: a resolve committed between the read and the update.
            return "acked" if acked.rowcount == 1 else "unchanged"

        return run_write_transaction(self._write_session, "ack", _ack)

    def list_for_run(self, *, workspace_id: int, run_id: str) -> list[AlertRecord]:
        """Every alert of the run, oldest first.

        Internal: nothing here checks the caller, so callers check the run's owner first.
        """
        with shared_read_scope(), self._session("list_for_run") as session:
            rows = session.scalars(
                select(AlertRow)
                .where(AlertRow.workspace_id == workspace_id, AlertRow.run_id == run_id)
                .order_by(asc(AlertRow.created_at), asc(AlertRow.id))
            ).all()
            return [_to_record(row) for row in rows]


__all__ = [
    "MAX_ALERT_RAISES",
    "MAX_INBOX_LIMIT",
    "AckOutcome",
    "InboxCursor",
    "SqlAlchemyAlertStore",
    "apply_alert_changes",
    "check_alert_raises",
    "generation_clause",
]
