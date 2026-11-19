"""Coral's registration work: rows that keep the account generation they were created under.

A password change rotates the account's generation, and the server moves the
account's registration work to the new one in the same transaction. Coral's
share is every row the owner holds at the old generation: runs and their
alerts, and ``coral_workflows`` rows of this database (the workflow definitions
the routes serve live in another file). Re-creating an account moves nothing.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from coral.db import AlertRow, RunRow, WorkflowRow, query_name_scope


def carry_account_generation(
    session: Session, *, workspace_id: int, user_id: str, old: str, new: str
) -> None:
    """
    Move ``user_id``'s Coral rows from generation ``old`` to ``new`` through ``session``.

    Each run moved gets a new version, so a commit that read the run before the
    move loses its compare-and-swap and is reduced again with the new generation.
    The generation also keeps a look-alike user (a collation that folds case) out
    of the update.
    """
    with query_name_scope("coral.registration.carry"):
        session.execute(
            update(RunRow)
            .where(
                RunRow.workspace_id == workspace_id,
                RunRow.user_id == user_id,
                RunRow.account_generation == old,
            )
            .values(account_generation=new, version=RunRow.version + 1)
        )
        session.execute(
            update(AlertRow)
            .where(
                AlertRow.workspace_id == workspace_id,
                AlertRow.owner_user_id == user_id,
                AlertRow.account_generation == old,
            )
            .values(account_generation=new)
        )
        session.execute(
            update(WorkflowRow)
            .where(
                WorkflowRow.workspace_id == workspace_id,
                WorkflowRow.user_id == user_id,
                WorkflowRow.account_generation == old,
            )
            .values(account_generation=new)
        )


__all__ = ["carry_account_generation"]
