"""Tests for moving a step binding onto a supersession replacement session."""

from __future__ import annotations

import dataclasses

import pytest

from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole, SlotRole
from coral.stores.session_bindings import (
    BindingNotFound,
    SessionBindingDraft,
    SqlAlchemySessionBindingStore,
)

WORKSPACE = 7
RUN = "a" * 32
OLD = "d" * 32
NEW = "e" * 32
HOST = "f" * 32


def _step(**changes: object) -> SessionBindingDraft:
    draft = SessionBindingDraft(
        workspace_id=WORKSPACE,
        session_id=OLD,
        run_id=RUN,
        role=SessionBindingRole.STEP,
        effect_key="step-effect-transfer",
        slot_id="implement",
        slot_role=SlotRole.STEP_AGENT,
        session_generation=2,
        host_id=HOST,
        progress=SessionBindingProgress.INITIALIZED,
    )
    return dataclasses.replace(draft, **changes)


def test_transfer_moves_binding_to_new_session_id(coral_db_uri: str) -> None:
    store = SqlAlchemySessionBindingStore(coral_db_uri)
    store.reserve(_step())
    moved = store.transfer(WORKSPACE, OLD, NEW)
    assert moved.session_id == NEW
    assert moved.run_id == RUN
    assert moved.slot_id == "implement"
    assert moved.session_generation == 2
    assert moved.progress is SessionBindingProgress.INITIALIZED
    assert store.get(WORKSPACE, OLD, run_id=RUN) is None
    assert store.get(WORKSPACE, NEW, run_id=RUN) == moved


def test_transfer_missing_old_raises(coral_db_uri: str) -> None:
    store = SqlAlchemySessionBindingStore(coral_db_uri)
    with pytest.raises(BindingNotFound):
        store.transfer(WORKSPACE, OLD, NEW)
