"""Engine stable-id store on every DB lane: recorded once, conflicts, per-session listing."""

from __future__ import annotations

import pytest

from coral.db.enum_codecs import StableIdKind
from coral.stores.session_bindings import effect_checksum
from coral.stores.stable_ids import (
    SqlAlchemyStableIdStore,
    StableIdConflict,
    StableIdRecord,
    StableIds,
    content_checksum,
)
from tests.stores.coral._faults import fresh_process, run_racing

WORKSPACE = 7
RUN = "a" * 32
OTHER_RUN = "b" * 32
SESSION = "c" * 32
OTHER_SESSION = "d" * 32
BRIEF_ID = "1" * 32
STEER_ID = "2" * 32


def _clock() -> float:
    return 1_700_000_000.0


def _record(
    store: SqlAlchemyStableIdStore,
    *,
    stable_id: str = BRIEF_ID,
    session_id: str = SESSION,
    effect_key: str = "brief-effect",
    kind: StableIdKind | str = StableIdKind.BRIEF,
    workspace_id: int = WORKSPACE,
    run_id: str = RUN,
    generation: int = 1,
    content: str = "Implement the plan.",
) -> None:
    store.record_send(
        workspace_id,
        stable_id=stable_id,
        run_id=run_id,
        session_id=session_id,
        effect_key=effect_key,
        kind=kind,
        generation=generation,
        content=content,
    )


def test_record_send_is_idempotent_and_survives_a_new_process(coral_db_uri: str) -> None:
    store = SqlAlchemyStableIdStore(coral_db_uri, clock=_clock)
    assert isinstance(store, StableIds)

    _record(store)
    _record(store)

    reopened = SqlAlchemyStableIdStore(fresh_process(coral_db_uri), clock=_clock)
    assert reopened.lookup(WORKSPACE, BRIEF_ID, run_id=RUN) == StableIdRecord(
        workspace_id=WORKSPACE,
        stable_id=BRIEF_ID,
        run_id=RUN,
        session_id=SESSION,
        effect_cksum=effect_checksum("brief-effect"),
        content_cksum=content_checksum("Implement the plan."),
        kind=StableIdKind.BRIEF,
        session_generation=1,
        created_at=1_700_000_000,
    )
    assert reopened.lookup(WORKSPACE, STEER_ID, run_id=RUN) is None
    assert reopened.lookup(WORKSPACE + 1, BRIEF_ID, run_id=RUN) is None
    # Another run never sees this run's sends.
    assert reopened.lookup(WORKSPACE, BRIEF_ID, run_id=OTHER_RUN) is None
    assert reopened.list_for_session(WORKSPACE, SESSION, run_id=OTHER_RUN) == frozenset()


def test_stable_id_recorded_for_a_different_send_conflicts(coral_db_uri: str) -> None:
    store = SqlAlchemyStableIdStore(coral_db_uri, clock=_clock)
    _record(store)
    stored = store.lookup(WORKSPACE, BRIEF_ID, run_id=RUN)

    for record_differently, field in (
        (lambda: _record(store, session_id=OTHER_SESSION), "session_id"),
        (lambda: _record(store, effect_key="another-effect"), "effect_cksum"),
        (lambda: _record(store, content="Implement another plan."), "content_cksum"),
        (lambda: _record(store, kind="steer"), "kind"),
        (lambda: _record(store, generation=2), "session_generation"),
        (lambda: _record(store, run_id=OTHER_RUN), "run_id"),
    ):
        with pytest.raises(StableIdConflict) as raised:
            record_differently()
        assert raised.value.fields == (field,)
        assert raised.value.stored == stored
        # The message names only the caller's stable id, never the stored session or run.
        assert SESSION not in str(raised.value)
        assert RUN not in str(raised.value)
    assert store.list_for_session(WORKSPACE, OTHER_SESSION, run_id=RUN) == frozenset()


def test_list_for_session_returns_exactly_that_sessions_ids(coral_db_uri: str) -> None:
    store = SqlAlchemyStableIdStore(coral_db_uri, clock=_clock)
    _record(store)
    _record(store, stable_id=STEER_ID, effect_key="steer-effect", kind="steer")
    _record(store, stable_id="3" * 32, session_id=OTHER_SESSION, effect_key="other-brief")
    _record(store, stable_id="4" * 32, workspace_id=WORKSPACE + 1, effect_key="other-ws")

    assert store.list_for_session(WORKSPACE, SESSION, run_id=RUN) == frozenset(
        {BRIEF_ID, STEER_ID}
    )
    steer = store.lookup(WORKSPACE, STEER_ID, run_id=RUN)
    assert steer is not None
    assert steer.kind is StableIdKind.STEER


def test_concurrent_records_store_one_send(coral_db_uri: str) -> None:
    store = SqlAlchemyStableIdStore(coral_db_uri, clock=_clock)

    outcomes = run_racing(4, lambda _index: _record(store))

    assert [outcome.error for outcome in outcomes] == [None] * 4
    assert store.list_for_session(WORKSPACE, SESSION, run_id=RUN) == frozenset({BRIEF_ID})


def test_concurrent_records_from_other_sessions_conflict(coral_db_uri: str) -> None:
    store = SqlAlchemyStableIdStore(coral_db_uri, clock=_clock)
    sessions = [str(index) * 32 for index in range(4)]

    outcomes = run_racing(4, lambda index: _record(store, session_id=sessions[index]))

    winners = [index for index, outcome in enumerate(outcomes) if outcome.error is None]
    losers = [outcome.error for outcome in outcomes if outcome.error is not None]
    assert len(winners) == 1
    assert all(isinstance(error, StableIdConflict) for error in losers), losers
    stored = store.lookup(WORKSPACE, BRIEF_ID, run_id=RUN)
    assert stored is not None
    assert stored.session_id == sessions[winners[0]]
