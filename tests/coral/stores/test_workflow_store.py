"""Slim workflow definition store: round-trip, size cap, idempotent saves and owners."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from coral.db.models_workflows import MAX_STORED_BYTES, CoralBase, WorkflowRow
from coral.stores.workflows import (
    SqlWorkflowDefinitionStore,
    WorkflowDefinition,
    WorkflowKeyTaken,
    WorkflowTooLargeError,
)
from omnigent.db.compression import encode
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    end,
    fixture_text,
    start,
    step,
    workflow_text,
)
from tests.stores.coral._faults import run_racing


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    sqlite_engine = create_engine(f"sqlite:///{tmp_path / 'coral.db'}")
    CoralBase.metadata.create_all(sqlite_engine)
    yield sqlite_engine
    sqlite_engine.dispose()


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000

    def __call__(self) -> int:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def store(engine: Engine, clock: _Clock) -> SqlWorkflowDefinitionStore:
    return SqlWorkflowDefinitionStore(engine, clock=clock)


ALICE = "alice"
BOB = "bob"


def _save(
    store: SqlWorkflowDefinitionStore,
    yaml_text: str,
    *,
    workspace_id: int = 1,
    runnable: bool = True,
    owner: str | None = ALICE,
) -> WorkflowDefinition:
    graph, _ = compile_text(yaml_text)
    return store.save(
        workspace_id=workspace_id,
        workflow_key=graph.workflow_id,
        name=graph.name,
        yaml_text=yaml_text,
        compiled=graph,
        runnable=runnable,
        owner=owner,
    )


def _get(
    store: SqlWorkflowDefinitionStore, workflow_id: str, *, owner: str | None = ALICE
) -> WorkflowDefinition | None:
    return store.get(workspace_id=1, workflow_id=workflow_id, owner=owner)


def _listed(store: SqlWorkflowDefinitionStore, *, owner: str | None = ALICE) -> list[str]:
    return [d.id for d in store.list_definitions(workspace_id=1, owner=owner)]


def _stored_owner(engine: Engine, definition_id: str) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT user_id FROM coral_workflows WHERE id = :id"), {"id": definition_id}
        ).scalar_one()


def _noisy_workflow(goal: str) -> str:
    return workflow_text(
        [start(), step("work", goal=goal), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )


def test_round_trip_preserves_yaml_and_compiled_graph(store: SqlWorkflowDefinitionStore) -> None:
    yaml_text = fixture_text("loop")
    saved = _save(store, yaml_text)
    loaded = _get(store, saved.id)
    assert loaded is not None
    assert loaded.yaml_text == yaml_text
    assert loaded.compiled == compile_text(yaml_text)[0]
    assert loaded.content_hash == loaded.compiled.content_hash
    assert (loaded.workflow_key, loaded.name, loaded.runnable) == (
        "review-loop",
        "Review loop",
        True,
    )
    assert store.get_by_key(workspace_id=1, workflow_key="review-loop", owner=ALICE) == loaded


def test_get_unknown_or_other_workspace_returns_none(store: SqlWorkflowDefinitionStore) -> None:
    saved = _save(store, fixture_text("minimal"), workspace_id=1)
    assert _get(store, "0" * 32) is None
    assert store.get(workspace_id=2, workflow_id=saved.id, owner=ALICE) is None
    assert store.get_by_key(workspace_id=2, workflow_key="demo", owner=ALICE) is None


def test_identical_content_saves_once_with_same_hash(
    store: SqlWorkflowDefinitionStore, clock: _Clock
) -> None:
    first = _save(store, fixture_text("minimal"))
    clock.now += 60
    second = _save(store, fixture_text("minimal"))
    assert second == first
    assert len(_listed(store)) == 1


def test_changed_content_updates_row_in_place(
    store: SqlWorkflowDefinitionStore, clock: _Clock
) -> None:
    first = _save(store, fixture_text("minimal"))
    clock.now += 60
    changed = fixture_text("minimal").replace("Do the thing", "Do another thing")
    second = _save(store, changed)
    assert second.id == first.id
    assert second.content_hash != first.content_hash
    assert (second.created_at, second.updated_at) == (1_000, 1_060)
    assert _get(store, first.id) == second


def test_invalid_draft_is_stored_as_not_runnable(store: SqlWorkflowDefinitionStore) -> None:
    saved = _save(store, fixture_text("deadlock_join"), runnable=False)
    assert saved.runnable is False
    assert _get(store, saved.id).runnable is False  # type: ignore[union-attr]


def test_comment_only_change_keeps_hash_but_updates_text(
    store: SqlWorkflowDefinitionStore, clock: _Clock
) -> None:
    first = _save(store, fixture_text("minimal"))
    clock.now += 5
    second = _save(store, "# note\n" + fixture_text("minimal"))
    assert second.content_hash == first.content_hash
    assert second.yaml_text.startswith("# note")
    assert second.updated_at == 1_005


def test_same_key_in_two_workspaces_is_independent(store: SqlWorkflowDefinitionStore) -> None:
    first = _save(store, fixture_text("minimal"), workspace_id=1)
    second = _save(store, fixture_text("minimal"), workspace_id=2)
    assert first.id != second.id
    assert [d.id for d in store.list_definitions(workspace_id=2, owner=ALICE)] == [second.id]


def test_list_is_ordered_by_key(store: SqlWorkflowDefinitionStore) -> None:
    _save(store, fixture_text("parallel"))
    _save(store, fixture_text("minimal"))
    _save(store, fixture_text("loop"))
    assert [d.workflow_key for d in store.list_definitions(workspace_id=1, owner=ALICE)] == [
        "demo",
        "fan-out",
        "review-loop",
    ]


def test_incompressible_yaml_over_cap_is_rejected_before_writing(
    store: SqlWorkflowDefinitionStore, engine: Engine
) -> None:
    yaml_text = _noisy_workflow(os.urandom(20_000).hex())
    assert len(encode(yaml_text) or b"") > MAX_STORED_BYTES
    with pytest.raises(WorkflowTooLargeError, match="yaml_text"):
        _save(store, yaml_text)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM coral_workflows")).scalar_one() == 0


def test_large_but_compressible_yaml_under_cap_is_stored(
    store: SqlWorkflowDefinitionStore,
) -> None:
    yaml_text = _noisy_workflow("repeat " * 5_000)
    assert len(yaml_text) > MAX_STORED_BYTES
    saved = _save(store, yaml_text)
    loaded = _get(store, saved.id)
    assert loaded is not None and loaded.yaml_text == yaml_text


def test_oversize_update_leaves_existing_row_untouched(
    store: SqlWorkflowDefinitionStore,
) -> None:
    saved = _save(store, fixture_text("minimal"))
    with pytest.raises(WorkflowTooLargeError):
        _save(store, _noisy_workflow(os.urandom(20_000).hex()))
    assert _get(store, saved.id) == saved


def test_cap_is_the_framed_byte_limit() -> None:
    assert MAX_STORED_BYTES == 16_383


# ── Owners ──────────────────────────────────────────────────────────────────


def test_save_stamps_the_saver_as_owner(store: SqlWorkflowDefinitionStore, engine: Engine) -> None:
    saved = _save(store, fixture_text("minimal"))

    assert saved.user_id == ALICE
    assert _stored_owner(engine, saved.id) == ALICE


def test_another_owners_key_is_refused_and_their_row_is_unchanged(
    store: SqlWorkflowDefinitionStore, clock: _Clock
) -> None:
    original = _save(store, fixture_text("minimal"))
    clock.now += 60

    with pytest.raises(WorkflowKeyTaken):
        _save(store, fixture_text("minimal").replace("Do the thing", "Do B's thing"), owner=BOB)

    assert _get(store, original.id) == original


def test_another_owners_workflow_is_neither_found_nor_listed(
    store: SqlWorkflowDefinitionStore,
) -> None:
    alices = _save(store, fixture_text("minimal"))
    bobs = _save(store, fixture_text("loop"), owner=BOB)

    assert _get(store, alices.id, owner=BOB) is None
    assert store.get_by_key(workspace_id=1, workflow_key="demo", owner=BOB) is None
    assert store.get_by_key(workspace_id=1, workflow_key="review-loop", owner=BOB) == bobs
    assert _listed(store, owner=BOB) == [bobs.id]
    assert _listed(store) == [alices.id]


def test_a_legacy_unowned_row_is_readable_by_everyone_until_its_first_save_claims_it(
    store: SqlWorkflowDefinitionStore, engine: Engine, clock: _Clock
) -> None:
    legacy = _save(store, fixture_text("minimal"), owner=None)
    assert legacy.user_id is None
    assert _get(store, legacy.id, owner=BOB) == legacy
    assert _listed(store, owner=BOB) == [legacy.id]
    clock.now += 60

    # Unchanged content: the claim stamps the owner and leaves the definition as it was.
    claimed = _save(store, fixture_text("minimal"))

    assert (claimed.id, claimed.user_id, claimed.updated_at) == (legacy.id, ALICE, 1_000)
    assert _stored_owner(engine, legacy.id) == ALICE
    assert _get(store, legacy.id, owner=BOB) is None
    with pytest.raises(WorkflowKeyTaken):
        _save(store, fixture_text("minimal"), owner=BOB)


def test_the_local_user_owns_its_unowned_rows_without_stamping_them(
    store: SqlWorkflowDefinitionStore, engine: Engine
) -> None:
    first = _save(store, fixture_text("minimal"), owner=None)
    edited = _save(store, "# note\n" + fixture_text("minimal"), owner=None)

    assert (edited.id, edited.user_id) == (first.id, None)
    assert _stored_owner(engine, first.id) is None
    assert _listed(store, owner=None) == [first.id]


def test_the_local_user_cannot_overwrite_a_named_users_workflow(
    store: SqlWorkflowDefinitionStore,
) -> None:
    alices = _save(store, fixture_text("minimal"))

    with pytest.raises(WorkflowKeyTaken):
        _save(store, fixture_text("minimal"), owner=None)
    assert _get(store, alices.id, owner=None) is None


def test_owners_are_compared_exactly(store: SqlWorkflowDefinitionStore) -> None:
    alices = _save(store, fixture_text("minimal"))

    assert _get(store, alices.id, owner=ALICE.upper()) is None
    with pytest.raises(WorkflowKeyTaken):
        _save(store, fixture_text("minimal"), owner=ALICE.upper())


@pytest.mark.parametrize("racer_owners", [(ALICE, BOB), (ALICE, ALICE)])
def test_concurrent_first_saves_of_one_key_leave_one_owner(
    store: SqlWorkflowDefinitionStore, engine: Engine, racer_owners: tuple[str, str]
) -> None:
    outcomes = run_racing(
        2, lambda index: _save(store, fixture_text("minimal"), owner=racer_owners[index])
    )

    saved = [outcome.value for outcome in outcomes if outcome.error is None]
    refused = [outcome.error for outcome in outcomes if outcome.error is not None]
    assert all(isinstance(error, WorkflowKeyTaken) for error in refused)
    assert len(saved) == (1 if racer_owners[0] != racer_owners[1] else 2)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT id, user_id FROM coral_workflows")).all()
    assert [tuple(row) for row in rows] == [(saved[0].id, saved[0].user_id)]


def test_concurrent_claims_of_a_legacy_row_leave_one_owner_and_their_content(
    store: SqlWorkflowDefinitionStore,
) -> None:
    legacy = _save(store, fixture_text("minimal"), owner=None)
    owners = (ALICE, BOB)
    # Each claimer changes the content, so a claim read before the other committed would
    # overwrite that owner's workflow.
    texts = [
        fixture_text("minimal").replace("Do the thing", f"Do {owner}'s thing") for owner in owners
    ]

    outcomes = run_racing(2, lambda index: _save(store, texts[index], owner=owners[index]))

    [winner] = [outcome.value for outcome in outcomes if outcome.error is None]
    refused = [type(outcome.error) for outcome in outcomes if outcome.error is not None]
    assert refused == [WorkflowKeyTaken]
    assert isinstance(winner, WorkflowDefinition) and winner.id == legacy.id
    assert _get(store, legacy.id, owner=winner.user_id) == winner


@pytest.mark.parametrize(("second_owner", "taken"), [(BOB, True), (ALICE, False)])
def test_a_first_save_that_loses_the_insert_race_applies_the_owner_rule(
    store: SqlWorkflowDefinitionStore,
    monkeypatch: pytest.MonkeyPatch,
    second_owner: str,
    taken: bool,
) -> None:
    winner = _save(store, fixture_text("minimal"))
    # The loser looked the key up before the winner committed, so its insert collides.
    find = store._find_by_key
    lookups: list[str] = []

    def stale_once(
        session: Session, *, workspace_id: int, workflow_key: str
    ) -> WorkflowRow | None:
        lookups.append(workflow_key)
        if len(lookups) == 1:
            return None
        return find(session, workspace_id=workspace_id, workflow_key=workflow_key)

    monkeypatch.setattr(store, "_find_by_key", stale_once)

    if taken:
        with pytest.raises(WorkflowKeyTaken):
            _save(store, fixture_text("minimal"), owner=second_owner)
    else:
        assert _save(store, fixture_text("minimal"), owner=second_owner) == winner
    assert lookups == ["demo", "demo"]
    assert _get(store, winner.id) == winner
