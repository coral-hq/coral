"""Session binding store on every DB lane: idempotent reserve, conflicts, monotonic progress."""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import event

from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole, SlotRole
from coral.model.ids import anchor_session_id
from coral.stores.session_bindings import (
    BindingConflict,
    BindingNotFound,
    FreshBindingLookup,
    SessionBinding,
    SessionBindingDraft,
    SessionBindingLookup,
    SessionBindings,
    SqlAlchemySessionBindingStore,
    effect_checksum,
)
from omnigent.db import current_query_name
from tests.stores.coral._faults import fresh_process, run_racing

WORKSPACE = 7
RUN = "a" * 32
OTHER_RUN = "b" * 32
ANCHOR_SESSION = anchor_session_id(WORKSPACE, RUN)
STEP_SESSION = "d" * 32
HOST = "e" * 32


def _clock() -> float:
    return 1_700_000_000.0


def _store(uri: str) -> SqlAlchemySessionBindingStore:
    return SqlAlchemySessionBindingStore(uri, clock=_clock)


def _anchor(**changes: object) -> SessionBindingDraft:
    draft = SessionBindingDraft(
        workspace_id=WORKSPACE,
        session_id=ANCHOR_SESSION,
        run_id=RUN,
        role=SessionBindingRole.ANCHOR,
        effect_key="anchor-effect-1",
    )
    return dataclasses.replace(draft, **changes)


def _step(**changes: object) -> SessionBindingDraft:
    draft = SessionBindingDraft(
        workspace_id=WORKSPACE,
        session_id=STEP_SESSION,
        run_id=RUN,
        role=SessionBindingRole.STEP,
        effect_key="step-effect-1",
        slot_id="Review/0:reviewer",
        slot_role=SlotRole.VERIFIER,
        session_generation=2,
        host_id=HOST,
    )
    return dataclasses.replace(draft, **changes)


def test_reserve_is_idempotent_and_survives_a_new_process(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    assert isinstance(store, SessionBindings)

    first = store.reserve(_step())
    assert first == SessionBinding(
        workspace_id=WORKSPACE,
        session_id=STEP_SESSION,
        run_id=RUN,
        role=SessionBindingRole.STEP,
        slot_id="Review/0:reviewer",
        slot_role=SlotRole.VERIFIER,
        effect_cksum=effect_checksum("step-effect-1"),
        session_generation=2,
        host_id=HOST,
        progress=SessionBindingProgress.RESERVED,
        created_at=1_700_000_000,
        updated_at=1_700_000_000,
    )
    assert store.reserve(_step()) == first

    reopened = SqlAlchemySessionBindingStore(fresh_process(coral_db_uri), clock=_clock)
    assert reopened.get(WORKSPACE, STEP_SESSION, run_id=RUN) == first
    assert reopened.get(WORKSPACE + 1, STEP_SESSION, run_id=RUN) is None
    assert reopened.list_for_run(WORKSPACE, RUN) == [first]


def test_lookup_of_another_runs_session_finds_nothing(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    store.reserve(_step())

    # A caller acting for another run must treat the session as unbound, so not writable.
    assert store.get(WORKSPACE, STEP_SESSION, run_id=OTHER_RUN) is None


def test_repeat_reservation_with_any_other_field_conflicts(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    stored = store.reserve(_step())

    for conflicting, field in (
        (_step(run_id=OTHER_RUN), "run_id"),
        (_step(effect_key="step-effect-2"), "effect_cksum"),
        (_step(slot_id="Review/0:other"), "slot_id"),
        (_step(slot_role=SlotRole.STEP_AGENT), "slot_role"),
        (_step(session_generation=3), "session_generation"),
        (_step(host_id="f" * 32), "host_id"),
    ):
        with pytest.raises(BindingConflict) as raised:
            store.reserve(conflicting)
        assert raised.value.fields == (field,)
        assert raised.value.stored == stored
        # The message names only the caller's own session, never the stored run.
        assert OTHER_RUN not in str(raised.value)
        assert RUN not in str(raised.value)
    assert store.list_for_run(WORKSPACE, OTHER_RUN) == []


def test_anchor_and_step_cannot_share_a_session(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    anchor = store.reserve(_anchor())

    with pytest.raises(BindingConflict) as raised:
        store.reserve(_step(session_id=ANCHOR_SESSION))
    assert "role" in raised.value.fields
    assert store.list_for_run(WORKSPACE, RUN) == [anchor]


def test_reemitted_anchor_effect_keeps_the_runs_one_anchor(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    anchor = store.reserve(_anchor())

    # A re-keyed anchor effect for the same run adopts the stored anchor binding.
    assert store.reserve(_anchor(effect_key="anchor-effect-2")) == anchor
    assert anchor.effect_cksum == effect_checksum("anchor-effect-1")
    other_run_anchor = store.reserve(
        _anchor(run_id=OTHER_RUN, session_id=anchor_session_id(WORKSPACE, OTHER_RUN))
    )
    assert store.list_for_run(WORKSPACE, RUN) == [anchor]
    assert store.list_for_run(WORKSPACE, OTHER_RUN) == [other_run_anchor]


def test_effect_already_bound_to_another_session_conflicts(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    store.reserve(_step())

    with pytest.raises(BindingConflict) as raised:
        store.reserve(_step(session_id="f" * 32))
    assert raised.value.fields == ("effect_cksum",)
    assert STEP_SESSION not in str(raised.value)
    assert store.get(WORKSPACE, "f" * 32, run_id=RUN) is None


def test_concurrent_reservations_store_one_binding(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)

    outcomes = run_racing(4, lambda _index: store.reserve(_step()))

    assert [outcome.error for outcome in outcomes] == [None] * 4
    assert len({outcome.value for outcome in outcomes}) == 1
    assert len(store.list_for_run(WORKSPACE, RUN)) == 1


def test_record_progress_is_monotonic(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    store.reserve(_step())

    created = store.record_progress(WORKSPACE, STEP_SESSION, SessionBindingProgress.ROW_CREATED)
    assert created.progress is SessionBindingProgress.ROW_CREATED
    store.record_progress(WORKSPACE, STEP_SESSION, "initialized")
    lowered = store.record_progress(WORKSPACE, STEP_SESSION, SessionBindingProgress.RESERVED)
    assert lowered.progress is SessionBindingProgress.INITIALIZED

    # Re-reserving never resets progress.
    assert store.reserve(_step()).progress is SessionBindingProgress.INITIALIZED
    reopened = SqlAlchemySessionBindingStore(fresh_process(coral_db_uri), clock=_clock)
    stored = reopened.get(WORKSPACE, STEP_SESSION, run_id=RUN)
    assert stored is not None
    assert stored.progress is SessionBindingProgress.INITIALIZED

    with pytest.raises(BindingNotFound):
        store.record_progress(WORKSPACE, "f" * 32, SessionBindingProgress.ROW_CREATED)


def test_concurrent_progress_updates_never_lower_progress(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    store.reserve(_step())
    targets = [
        SessionBindingProgress.INITIALIZED,
        SessionBindingProgress.RESERVED,
        SessionBindingProgress.ROW_CREATED,
        SessionBindingProgress.RESERVED,
    ]

    outcomes = run_racing(
        4, lambda index: store.record_progress(WORKSPACE, STEP_SESSION, targets[index])
    )

    assert [outcome.error for outcome in outcomes] == [None] * 4
    assert all(
        outcome.value.progress >= target for outcome, target in zip(outcomes, targets, strict=True)
    )
    reopened = SqlAlchemySessionBindingStore(fresh_process(coral_db_uri), clock=_clock)
    stored = reopened.get(WORKSPACE, STEP_SESSION, run_id=RUN)
    assert stored is not None
    assert stored.progress is SessionBindingProgress.INITIALIZED


def test_list_for_run_returns_the_anchor_first_and_only_that_runs_bindings(
    coral_db_uri: str,
) -> None:
    store = _store(coral_db_uri)
    step = store.reserve(_step())
    anchor = store.reserve(_anchor())
    store.reserve(_step(run_id=OTHER_RUN, session_id="f" * 32, effect_key="other-run-step"))
    store.reserve(_step(workspace_id=WORKSPACE + 1))

    assert store.list_for_run(WORKSPACE, RUN) == [anchor, step]


def test_find_by_session_reads_a_binding_of_any_run(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    step = store.reserve(_step())
    other_anchor = store.reserve(
        _anchor(run_id=OTHER_RUN, session_id=anchor_session_id(WORKSPACE, OTHER_RUN))
    )
    engine = fresh_process(coral_db_uri)
    reopened = SqlAlchemySessionBindingStore(engine, clock=_clock)
    assert isinstance(reopened, SessionBindingLookup)
    # The tool bridge accepts only a lookup that reads the store on every call.
    assert isinstance(reopened, FreshBindingLookup) and reopened.reads_fresh is True
    names: list[str | None] = []

    def capture_name(*_args: object) -> None:
        names.append(current_query_name())

    event.listen(engine, "before_cursor_execute", capture_name)
    try:
        # No run is named: the caller takes the run, role and slot from the row.
        assert reopened.find_by_session(WORKSPACE, STEP_SESSION) == step
    finally:
        event.remove(engine, "before_cursor_execute", capture_name)
    assert names and set(names) == {"coral.session_bindings.find_by_session"}
    assert reopened.find_by_session(WORKSPACE, other_anchor.session_id) == other_anchor
    assert reopened.find_by_session(WORKSPACE + 1, STEP_SESSION) is None
    assert reopened.find_by_session(WORKSPACE, "f" * 32) is None
    # The run-scoped read still treats another run's binding as none.
    assert reopened.get(WORKSPACE, STEP_SESSION, run_id=OTHER_RUN) is None
    assert reopened.get(WORKSPACE, STEP_SESSION, run_id=RUN) == step

    # Every read is fresh, so progress made after the first read shows.
    store.record_progress(WORKSPACE, STEP_SESSION, SessionBindingProgress.ROW_CREATED)
    found = reopened.find_by_session(WORKSPACE, STEP_SESSION)
    assert found is not None
    assert found.progress is SessionBindingProgress.ROW_CREATED


def test_find_by_session_reads_only_the_callers_workspace(coral_db_uri: str) -> None:
    store = _store(coral_db_uri)
    # One session id bound in two workspaces, to different runs, roles and slots.
    mine = store.reserve(_step())
    theirs = store.reserve(
        _step(
            workspace_id=WORKSPACE + 1,
            run_id=OTHER_RUN,
            slot_id="Build/0:implementer",
            slot_role=SlotRole.STEP_AGENT,
            session_generation=1,
        )
    )
    reopened = SqlAlchemySessionBindingStore(fresh_process(coral_db_uri), clock=_clock)

    assert reopened.find_by_session(WORKSPACE, STEP_SESSION) == mine
    assert reopened.find_by_session(WORKSPACE + 1, STEP_SESSION) == theirs
    assert reopened.find_by_session(WORKSPACE + 2, STEP_SESSION) is None
    # Progress in one workspace never shows in the other.
    store.record_progress(WORKSPACE + 1, STEP_SESSION, SessionBindingProgress.INITIALIZED)
    assert reopened.find_by_session(WORKSPACE, STEP_SESSION) == mine
    found = reopened.find_by_session(WORKSPACE + 1, STEP_SESSION)
    assert found is not None and found.progress is SessionBindingProgress.INITIALIZED
