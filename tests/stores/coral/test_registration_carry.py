"""A password change moves the owner's Coral rows to the account's new generation.

The server calls ``carry_account_generation`` inside the rotation's transaction;
here a plain transaction stands in for it. Only the owner's rows of the old
generation in the rotation's workspace move.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from coral.db import WorkflowRow, coral_engine
from coral.db.enum_codecs import AlertKind
from coral.stores.alerts import SqlAlchemyAlertStore
from coral.stores.protocols import CoralRun, RunVersionConflict
from coral.stores.registration import carry_account_generation
from coral.stores.runs import SqlAlchemyCoralRunStore
from tests.stores.coral._alerts import (
    ALICE,
    BOB,
    NOW,
    OTHER_WORKSPACE,
    WORKSPACE,
    alert_draft,
    commit_alert_changes,
    start_owned_run,
)
from tests.stores.coral._faults import fresh_process

OLD = "a" * 32
NEW = "b" * 32
# The generation of an earlier, deleted account with the same name.
EARLIER = "c" * 32


def _workflow(
    session: Session, key: str, user_id: str, generation: str, workspace_id: int
) -> None:
    session.add(
        WorkflowRow(
            workspace_id=workspace_id,
            id=key.ljust(32, "0"),
            workflow_key=key,
            name=key,
            user_id=user_id,
            account_generation=generation,
            created_at=NOW,
            updated_at=NOW,
        )
    )


def _stored(runs: SqlAlchemyCoralRunStore, run: CoralRun) -> CoralRun:
    stored = runs.get_run(run.id, workspace_id=run.workspace_id)
    assert stored is not None
    return stored


def _carry(db_uri: str) -> None:
    with Session(coral_engine(db_uri)) as session, session.begin():
        carry_account_generation(session, workspace_id=WORKSPACE, user_id=ALICE, old=OLD, new=NEW)


def test_only_the_owner_s_rows_of_the_old_generation_move(coral_db_uri: str) -> None:
    runs = SqlAlchemyCoralRunStore(coral_db_uri)
    started: dict[str, CoralRun] = {
        "mine": start_owned_run(runs, "mine", generation=OLD),
        "earlier": start_owned_run(runs, "earlier", generation=EARLIER),
        "bob": start_owned_run(runs, "bob", user_id=BOB, generation=OLD),
        "elsewhere": start_owned_run(
            runs, "elsewhere", generation=OLD, workspace_id=OTHER_WORKSPACE
        ),
        "local": start_owned_run(runs, "local", user_id=None),
    }
    for run in started.values():
        commit_alert_changes(runs, run, raises=[alert_draft(run, AlertKind.PAUSE, "1")])
    with Session(coral_engine(coral_db_uri)) as session, session.begin():
        _workflow(session, "mine", ALICE, OLD, WORKSPACE)
        _workflow(session, "earlier", ALICE, EARLIER, WORKSPACE)
        _workflow(session, "bob", BOB, OLD, WORKSPACE)
    versions = {name: _stored(runs, run).version for name, run in started.items()}

    _carry(coral_db_uri)

    fresh_process(coral_db_uri)
    runs = SqlAlchemyCoralRunStore(coral_db_uri)
    alerts = SqlAlchemyAlertStore(coral_db_uri)
    after = {name: _stored(runs, run) for name, run in started.items()}
    assert {name: run.account_generation for name, run in after.items()} == {
        "mine": NEW,
        "earlier": EARLIER,
        "bob": OLD,
        "elsewhere": OLD,
        "local": None,
    }
    # A moved run gets a new version; the others keep theirs.
    assert {name: run.version - versions[name] for name, run in after.items()} == {
        "mine": 1,
        "earlier": 0,
        "bob": 0,
        "elsewhere": 0,
        "local": 0,
    }
    assert {
        name: [
            alert.account_generation
            for alert in alerts.list_for_run(workspace_id=run.workspace_id, run_id=run.id)
        ]
        for name, run in started.items()
    } == {
        "mine": [NEW],
        "earlier": [EARLIER],
        "bob": [OLD],
        "elsewhere": [OLD],
        "local": [None],
    }
    with Session(coral_engine(coral_db_uri)) as session:
        workflows = session.execute(
            select(WorkflowRow.workflow_key, WorkflowRow.account_generation).order_by(
                WorkflowRow.workflow_key
            )
        ).all()
    assert [tuple(row) for row in workflows] == [("bob", OLD), ("earlier", EARLIER), ("mine", NEW)]


def test_a_commit_that_read_the_run_before_the_move_loses_its_version(coral_db_uri: str) -> None:
    """Its alert drafts carry the old generation, so it must be reduced again."""
    runs = SqlAlchemyCoralRunStore(coral_db_uri)
    run = start_owned_run(runs, "mine", generation=OLD)
    read = _stored(runs, run)

    _carry(coral_db_uri)

    with pytest.raises(RunVersionConflict):
        commit_alert_changes(
            runs,
            read,
            raises=[alert_draft(read, AlertKind.PAUSE, "1")],
            expected_version=read.version,
        )
    assert (
        SqlAlchemyAlertStore(coral_db_uri).list_for_run(workspace_id=WORKSPACE, run_id=run.id)
        == []
    )
