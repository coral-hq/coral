"""
Profile revisions and run pins.

A profile is a stance overlay saved as immutable revisions under its ref
(``reviewer/strict-review``). Saving changed content adds revision N+1; saving the
same content adds nothing. A run pins the latest revision of every profile it uses
when it starts, and its steps are built from the pins only, so a later revision never
reaches a running run. Revisions belong to the user who saved them (``None`` for the
single local user); reads see the owner's and ownerless ones, as for workflows.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Engine, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from coral.db import (
    MAX_STORED_BYTES,
    ProfileRevisionRow,
    RunProfilePinRow,
    RunRow,
    coral_engine,
    encode,
    make_named_managed_session_maker,
    run_write_transaction,
    shared_read_scope,
)
from coral.model.ids import derived_id
from coral.profiles.spec import ProfileSpec, canonical_json


class ProfileExists(Exception):
    """A first save of a ref that already has a revision."""


class ProfileKeyTaken(Exception):
    """Another owner's profile holds this ref in the workspace."""


class StaleRevision(Exception):
    """The save was based on a revision that is no longer the latest."""


class ProfileTooLarge(ValueError):
    """The spec exceeds the inline storage cap."""


class ProfileMissing(Exception):
    """A run uses a profile the owner has no revision of."""

    def __init__(self, ref: str) -> None:
        self.ref = ref
        super().__init__(ref)


@dataclass(frozen=True)
class ProfileRevision:
    workspace_id: int
    id: str
    profile_ref: str
    user_id: str | None
    revision_no: int
    spec: ProfileSpec
    content_digest: str
    created_at: int


def revision_id(profile_ref: str, revision_no: int) -> str:
    return derived_id("coral-profile-revision", profile_ref, str(revision_no))


def _to_revision(row: ProfileRevisionRow) -> ProfileRevision:
    return ProfileRevision(
        workspace_id=row.workspace_id,
        id=row.id,
        profile_ref=row.profile_ref,
        user_id=row.user_id,
        revision_no=row.revision_no,
        spec=ProfileSpec.model_validate_json(row.spec_json),
        content_digest=bytes(row.content_digest).hex(),
        created_at=row.created_at,
    )


def _visible_to(row: ProfileRevisionRow, owner: str | None) -> bool:
    return row.user_id is None or row.user_id == owner


def _owned(owner: str | None) -> ColumnElement[bool]:
    owned: ColumnElement[bool] = ProfileRevisionRow.user_id.is_(None)
    return owned if owner is None else or_(owned, ProfileRevisionRow.user_id == owner)


def _latest_row(
    session: Session, workspace_id: int, profile_ref: str
) -> ProfileRevisionRow | None:
    return session.scalars(
        select(ProfileRevisionRow)
        .where(
            ProfileRevisionRow.workspace_id == workspace_id,
            ProfileRevisionRow.profile_ref == profile_ref,
        )
        .order_by(ProfileRevisionRow.revision_no.desc())
        .limit(1)
    ).one_or_none()


class SqlProfileStore:
    """Persists ``coral_profile_revisions`` and ``coral_run_profile_pins``."""

    def __init__(
        self, db_uri_or_engine: str | Engine, *, clock: Callable[[], int] | None = None
    ) -> None:
        engine = (
            coral_engine(db_uri_or_engine)
            if isinstance(db_uri_or_engine, str)
            else db_uri_or_engine
        )
        self._clock = clock or (lambda: int(time.time()))
        self._session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.profile_store"
        )
        self._write_session = make_named_managed_session_maker(
            engine, query_name_prefix="coral.profile_store", immediate=True
        )

    def save_revision(
        self,
        *,
        workspace_id: int,
        profile_ref: str,
        owner: str | None,
        spec: ProfileSpec,
        base_revision_no: int | None,
    ) -> tuple[ProfileRevision, bool]:
        """
        Save ``spec`` as the next revision of ``profile_ref``.

        :param base_revision_no: The revision the edit started from; ``None`` creates.
        :returns: The latest revision and whether this save created it; the same
            content as the latest creates nothing.
        :raises ProfileKeyTaken: another owner's profile holds the ref.
        :raises ProfileExists: ``base_revision_no`` is ``None`` and the ref has a revision.
        :raises StaleRevision: the latest revision is not ``base_revision_no``.
        :raises ProfileTooLarge: the spec exceeds the inline cap.
        """
        spec_json = canonical_json(spec)
        framed = encode(spec_json)
        assert framed is not None
        if len(framed) > MAX_STORED_BYTES:
            raise ProfileTooLarge(
                f"the profile is {len(framed)} bytes after compression; the limit is "
                f"{MAX_STORED_BYTES}"
            )
        digest = hashlib.sha256(spec_json.encode()).digest()

        def write(session: Session) -> tuple[ProfileRevision, bool]:
            latest = _latest_row(session, workspace_id, profile_ref)
            if latest is not None and not _visible_to(latest, owner):
                raise ProfileKeyTaken(profile_ref)
            if latest is not None and base_revision_no is None:
                raise ProfileExists(profile_ref)
            if latest is not None and bytes(latest.content_digest) == digest:
                return _to_revision(latest), False
            if (latest.revision_no if latest is not None else None) != base_revision_no:
                raise StaleRevision(profile_ref)
            revision_no = 1 if latest is None else latest.revision_no + 1
            row = ProfileRevisionRow(
                workspace_id=workspace_id,
                id=revision_id(profile_ref, revision_no),
                profile_ref=profile_ref,
                user_id=owner if latest is None else latest.user_id,
                revision_no=revision_no,
                spec_json=spec_json,
                content_digest=digest,
                created_at=self._clock(),
            )
            session.add(row)
            session.flush()
            return _to_revision(row), True

        try:
            return run_write_transaction(self._write_session, "save_revision", write)
        except IntegrityError:
            # A concurrent save took this revision number first: look again, so the
            # owner, create and same-content rules apply to the save that won.
            try:
                return run_write_transaction(self._write_session, "save_revision", write)
            except IntegrityError:
                raise StaleRevision(profile_ref) from None

    def latest(
        self, *, workspace_id: int, profile_ref: str, owner: str | None
    ) -> ProfileRevision | None:
        """The newest revision of ``profile_ref`` visible to ``owner``."""
        with shared_read_scope(), self._session("latest") as session:
            row = _latest_row(session, workspace_id, profile_ref)
            return _to_revision(row) if row is not None and _visible_to(row, owner) else None

    def revisions(
        self, *, workspace_id: int, profile_ref: str, owner: str | None
    ) -> list[ProfileRevision]:
        """Every revision of ``profile_ref`` visible to ``owner``, newest first."""
        with shared_read_scope(), self._session("revisions") as session:
            rows = session.scalars(
                select(ProfileRevisionRow)
                .where(
                    ProfileRevisionRow.workspace_id == workspace_id,
                    ProfileRevisionRow.profile_ref == profile_ref,
                    _owned(owner),
                )
                .order_by(ProfileRevisionRow.revision_no.desc())
            ).all()
            return [_to_revision(row) for row in rows]

    def list_latest(self, *, workspace_id: int, owner: str | None) -> list[ProfileRevision]:
        """The newest revision of each profile visible to ``owner``, by ref."""
        with shared_read_scope(), self._session("list_latest") as session:
            rows = session.scalars(
                select(ProfileRevisionRow)
                .where(ProfileRevisionRow.workspace_id == workspace_id, _owned(owner))
                .order_by(ProfileRevisionRow.profile_ref, ProfileRevisionRow.revision_no.desc())
            ).all()
            latest: dict[str, ProfileRevisionRow] = {}
            for row in rows:
                latest.setdefault(row.profile_ref, row)
            return [_to_revision(row) for row in latest.values()]

    def get_revision(self, *, workspace_id: int, revision_id: str) -> ProfileRevision | None:
        """One revision by id, whoever owns it; callers check access."""
        with shared_read_scope(), self._session("get_revision") as session:
            row = session.get(ProfileRevisionRow, (workspace_id, revision_id))
            return None if row is None else _to_revision(row)

    def pin_run(
        self, *, workspace_id: int, run_id: str, owner: str | None, refs: Iterable[str]
    ) -> dict[str, str]:
        """
        Pin the latest revision of each ref ``owner`` sees for ``run_id``, in one transaction.

        A ref the run already pinned keeps its pin, so a retried or raced start keeps
        the first start's revisions.

        :returns: Each ref's pinned revision id.
        :raises ProfileMissing: for the first ref with no visible revision; nothing is pinned.
        """
        wanted = sorted(set(refs))

        def write(session: Session) -> dict[str, str]:
            pinned = {
                pin.profile_ref: pin.revision_id
                for pin in session.scalars(
                    select(RunProfilePinRow).where(
                        RunProfilePinRow.workspace_id == workspace_id,
                        RunProfilePinRow.run_id == run_id,
                        RunProfilePinRow.profile_ref.in_(wanted),
                    )
                )
            }
            for ref in wanted:
                if ref in pinned:
                    continue
                latest = _latest_row(session, workspace_id, ref)
                if latest is None or not _visible_to(latest, owner):
                    raise ProfileMissing(ref)
                session.add(
                    RunProfilePinRow(
                        workspace_id=workspace_id,
                        run_id=run_id,
                        profile_ref=ref,
                        revision_id=latest.id,
                    )
                )
                pinned[ref] = latest.id
            session.flush()
            return pinned

        try:
            return run_write_transaction(self._write_session, "pin_run", write)
        except IntegrityError:
            # A concurrent start of this run pinned first: its pins stand.
            return run_write_transaction(self._write_session, "pin_run", write)

    def run_pin(self, *, workspace_id: int, run_id: str, profile_ref: str) -> str | None:
        """The revision id ``run_id`` pinned for ``profile_ref``, or ``None``."""
        with shared_read_scope(), self._session("run_pin") as session:
            pin = session.get(RunProfilePinRow, (workspace_id, run_id, profile_ref))
            return None if pin is None else pin.revision_id

    def used_by(self, *, workspace_id: int, profile_ref: str) -> dict[str, int]:
        """Unfinished runs pinned to each revision of ``profile_ref``, by revision id."""
        with shared_read_scope(), self._session("used_by") as session:
            rows = (
                session.execute(
                    select(RunProfilePinRow.revision_id, func.count())
                    .join(
                        RunRow,
                        (RunRow.workspace_id == RunProfilePinRow.workspace_id)
                        & (RunRow.id == RunProfilePinRow.run_id),
                    )
                    .where(
                        RunProfilePinRow.workspace_id == workspace_id,
                        RunProfilePinRow.profile_ref == profile_ref,
                        RunRow.finished_at.is_(None),
                    )
                    .group_by(RunProfilePinRow.revision_id)
                )
                .tuples()
                .all()
            )
            return dict(rows)


__all__ = [
    "ProfileExists",
    "ProfileKeyTaken",
    "ProfileMissing",
    "ProfileRevision",
    "ProfileTooLarge",
    "SqlProfileStore",
    "StaleRevision",
    "revision_id",
]
