"""Profile revisions and run pins on every DB lane."""

from __future__ import annotations

import random
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from coral.db import RunRow, coral_engine
from coral.db.enum_codecs import RunStatus
from coral.profiles.spec import ProfileSpec, RuleInstance, RuleStrength
from coral.stores import profiles as profiles_module
from coral.stores.profiles import (
    ProfileExists,
    ProfileKeyTaken,
    ProfileMissing,
    ProfileTooLarge,
    SqlProfileStore,
    StaleRevision,
    revision_id,
)
from tests.db.coral._migration_support import insert_run

WORKSPACE = 1
REF = "reviewer/strict-review"
ALICE = "alice"
BOB = "bob"
RUN_A = "a" * 32
RUN_B = "b" * 32


def _spec(instructions: str = "Be strict.") -> ProfileSpec:
    return ProfileSpec(
        name="Strict review",
        instructions=instructions,
        rules=[
            RuleInstance(
                template="protect_paths",
                params={"paths": ["infra"]},
                strength=RuleStrength.REQUIRED,
            )
        ],
    )


@pytest.fixture
def store(coral_db_uri: str) -> SqlProfileStore:
    return SqlProfileStore(coral_db_uri, clock=lambda: 1_700_000_000)


def _save(
    store: SqlProfileStore,
    spec: ProfileSpec,
    base: int | None,
    *,
    owner: str | None = ALICE,
    ref: str = REF,
) -> tuple[int, bool]:
    revision, created = store.save_revision(
        workspace_id=WORKSPACE, profile_ref=ref, owner=owner, spec=spec, base_revision_no=base
    )
    return revision.revision_no, created


def test_a_first_save_creates_rev_1_and_reads_back(store: SqlProfileStore) -> None:
    revision, created = store.save_revision(
        workspace_id=WORKSPACE, profile_ref=REF, owner=ALICE, spec=_spec(), base_revision_no=None
    )

    assert created
    assert (revision.revision_no, revision.user_id) == (1, ALICE)
    assert revision.created_at == 1_700_000_000
    assert revision.id == revision_id(REF, 1)
    assert revision.spec == _spec()
    assert len(revision.content_digest) == 64
    assert store.latest(workspace_id=WORKSPACE, profile_ref=REF, owner=ALICE) == revision
    assert store.get_revision(workspace_id=WORKSPACE, revision_id=revision.id) == revision


def test_same_content_adds_no_revision_and_changed_content_adds_the_next(
    store: SqlProfileStore,
) -> None:
    assert _save(store, _spec(), None) == (1, True)
    assert _save(store, _spec(), 1) == (1, False)
    assert _save(store, _spec("Be stricter."), 1) == (2, True)
    assert _save(store, _spec("Be stricter."), 2) == (2, False)

    revisions = store.revisions(workspace_id=WORKSPACE, profile_ref=REF, owner=ALICE)
    assert [(r.revision_no, r.spec.instructions) for r in revisions] == [
        (2, "Be stricter."),
        (1, "Be strict."),
    ]


def test_a_save_from_a_stale_base_or_a_second_create_is_refused(store: SqlProfileStore) -> None:
    _save(store, _spec(), None)
    _save(store, _spec("two"), 1)

    with pytest.raises(StaleRevision):
        _save(store, _spec("three"), 1)
    with pytest.raises(StaleRevision):
        _save(store, _spec("three"), 7)
    with pytest.raises(ProfileExists):
        _save(store, _spec("three"), None)
    latest = store.latest(workspace_id=WORKSPACE, profile_ref=REF, owner=ALICE)
    assert latest is not None and latest.revision_no == 2


def test_another_owner_s_ref_is_taken_and_invisible(store: SqlProfileStore) -> None:
    _save(store, _spec(), None)

    with pytest.raises(ProfileKeyTaken):
        _save(store, _spec("mine"), None, owner=BOB)
    with pytest.raises(ProfileKeyTaken):
        _save(store, _spec("mine"), 1, owner=BOB)
    assert store.latest(workspace_id=WORKSPACE, profile_ref=REF, owner=BOB) is None
    assert store.revisions(workspace_id=WORKSPACE, profile_ref=REF, owner=BOB) == []
    assert store.list_latest(workspace_id=WORKSPACE, owner=BOB) == []


def test_list_latest_shows_each_visible_profile_s_newest_revision(store: SqlProfileStore) -> None:
    _save(store, _spec(), None)
    _save(store, _spec("two"), 1)
    _save(store, _spec(), None, ref="implementer/fast")
    _save(store, _spec(), None, owner=None, ref="reviewer/shared")
    _save(store, _spec(), None, owner=BOB, ref="reviewer/bobs")

    listed = store.list_latest(workspace_id=WORKSPACE, owner=ALICE)

    assert [(r.profile_ref, r.revision_no) for r in listed] == [
        ("implementer/fast", 1),
        ("reviewer/shared", 1),
        ("reviewer/strict-review", 2),
    ]


def test_an_oversized_spec_is_refused(store: SqlProfileStore) -> None:
    # Random astral characters, escaped in JSON, do not compress below the inline cap.
    draw = random.Random(0)
    noisy = "".join(chr(draw.randrange(0x10000, 0x10FFFF)) for _ in range(8000))
    with pytest.raises(ProfileTooLarge):
        _save(store, _spec(noisy), None)
    assert store.latest(workspace_id=WORKSPACE, profile_ref=REF, owner=ALICE) is None


def test_pins_are_written_once_and_a_replay_keeps_the_first(store: SqlProfileStore) -> None:
    _save(store, _spec(), None)
    first = store.pin_run(workspace_id=WORKSPACE, run_id=RUN_A, owner=ALICE, refs=[REF, REF])
    _save(store, _spec("two"), 1)

    again = store.pin_run(workspace_id=WORKSPACE, run_id=RUN_A, owner=ALICE, refs=[REF])
    other = store.pin_run(workspace_id=WORKSPACE, run_id=RUN_B, owner=ALICE, refs=[REF])

    assert first == again == {REF: revision_id(REF, 1)}
    assert other == {REF: revision_id(REF, 2)}
    assert store.run_pin(workspace_id=WORKSPACE, run_id=RUN_A, profile_ref=REF) == revision_id(
        REF, 1
    )
    assert store.run_pin(workspace_id=WORKSPACE, run_id=RUN_A, profile_ref="reviewer/x") is None


def test_a_missing_profile_pins_nothing(store: SqlProfileStore) -> None:
    _save(store, _spec(), None)
    _save(store, _spec(), None, owner=BOB, ref="reviewer/bobs")

    for missing in ("reviewer/none", "reviewer/bobs"):
        with pytest.raises(ProfileMissing) as raised:
            store.pin_run(workspace_id=WORKSPACE, run_id=RUN_A, owner=ALICE, refs=[REF, missing])
        assert raised.value.ref == missing
    assert store.run_pin(workspace_id=WORKSPACE, run_id=RUN_A, profile_ref=REF) is None


def test_used_by_counts_unfinished_runs_per_revision(
    store: SqlProfileStore, coral_db_uri: str
) -> None:
    engine = coral_engine(coral_db_uri)
    for run_id in ("c" * 32, "d" * 32, "e" * 32, "f" * 32):
        insert_run(engine, run_id, status=int(RunStatus.RUNNING), pause_reason=None)
    _save(store, _spec(), None)
    for run_id in ("c" * 32, "d" * 32):
        store.pin_run(workspace_id=WORKSPACE, run_id=run_id, owner=ALICE, refs=[REF])
    _save(store, _spec("two"), 1)
    for run_id in ("e" * 32, "f" * 32):
        store.pin_run(workspace_id=WORKSPACE, run_id=run_id, owner=ALICE, refs=[REF])
    # A pin whose run row was never written (a start that stopped) counts for nothing.
    store.pin_run(workspace_id=WORKSPACE, run_id="9" * 32, owner=ALICE, refs=[REF])
    with engine.begin() as connection:
        connection.execute(
            update(RunRow).where(RunRow.id == "d" * 32).values(finished_at=1_700_000_100)
        )

    assert store.used_by(workspace_id=WORKSPACE, profile_ref=REF) == {
        revision_id(REF, 1): 1,
        revision_id(REF, 2): 2,
    }
    assert store.used_by(workspace_id=WORKSPACE, profile_ref="reviewer/x") == {}


def test_a_save_that_loses_a_race_answers_for_the_save_that_won(
    store: SqlProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = profiles_module.run_write_transaction
    raced: list[bool] = []

    def losing_first(*args: Any, **kwargs: Any) -> Any:
        if not raced:
            raced.append(True)
            # Another owner's create commits between this save's read and its insert.
            _save(store, _spec(), None, owner=BOB)
            raise IntegrityError("insert", {}, Exception("duplicate"))
        return real(*args, **kwargs)

    monkeypatch.setattr(profiles_module, "run_write_transaction", losing_first)
    with pytest.raises(ProfileKeyTaken):
        _save(store, _spec(), None)
