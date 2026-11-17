"""Binding drafts are validated before any database access."""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import create_engine

from coral.db.enum_codecs import SessionBindingRole, SlotRole
from coral.model.ids import anchor_session_id
from coral.stores.session_bindings import SessionBindingDraft, SqlAlchemySessionBindingStore

WORKSPACE = 7
RUN = "a" * 32

ANCHOR = SessionBindingDraft(
    workspace_id=WORKSPACE,
    session_id=anchor_session_id(WORKSPACE, RUN),
    run_id=RUN,
    role=SessionBindingRole.ANCHOR,
    effect_key="anchor-effect",
)
STEP = SessionBindingDraft(
    workspace_id=WORKSPACE,
    session_id="d" * 32,
    run_id=RUN,
    role="step",
    effect_key="step-effect",
    slot_id="Review/0:reviewer",
    slot_role="verifier",
    host_id="e" * 32,
)


@pytest.mark.parametrize(
    "draft",
    [
        dataclasses.replace(ANCHOR, slot_role=SlotRole.STEP_AGENT),
        dataclasses.replace(ANCHOR, slot_id="slot"),
        dataclasses.replace(ANCHOR, host_id="e" * 32),
        # One anchor per run holds because only the run-derived id is accepted.
        dataclasses.replace(ANCHOR, session_id="f" * 32),
        dataclasses.replace(ANCHOR, run_id="b" * 32),
        dataclasses.replace(STEP, slot_role=None),
        dataclasses.replace(STEP, slot_id=None),
        dataclasses.replace(STEP, slot_role="reviewer"),
        dataclasses.replace(STEP, role="observer"),
    ],
    ids=[
        "anchor-slot-role",
        "anchor-slot-id",
        "anchor-host",
        "anchor-not-derived",
        "anchor-of-another-run",
        "step-without-slot-role",
        "step-without-slot-id",
        "unknown-slot-role",
        "unknown-role",
    ],
)
def test_invalid_draft_is_refused_before_any_write(draft: SessionBindingDraft) -> None:
    # The engine has no tables: reaching the database would fail with another error.
    store = SqlAlchemySessionBindingStore(create_engine("sqlite://"))

    with pytest.raises(ValueError):
        store.reserve(draft)


def test_anchor_session_id_is_scoped_to_the_workspace_and_run() -> None:
    anchor = anchor_session_id(WORKSPACE, RUN)

    assert len(anchor) == 32
    assert anchor == anchor_session_id(WORKSPACE, RUN)
    assert anchor != anchor_session_id(WORKSPACE + 1, RUN)
    assert anchor != anchor_session_id(WORKSPACE, "b" * 32)
