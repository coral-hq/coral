"""Slim workflow definition store: round-trip, size cap and idempotent saves."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text

from coral.db.models_workflows import MAX_STORED_BYTES, CoralBase
from coral.stores.workflows import (
    SqlWorkflowDefinitionStore,
    WorkflowDefinition,
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


def _save(
    store: SqlWorkflowDefinitionStore,
    yaml_text: str,
    *,
    workspace_id: int = 1,
    runnable: bool = True,
) -> WorkflowDefinition:
    graph, _ = compile_text(yaml_text)
    return store.save(
        workspace_id=workspace_id,
        workflow_key=graph.workflow_id,
        name=graph.name,
        yaml_text=yaml_text,
        compiled=graph,
        runnable=runnable,
    )


def _noisy_workflow(goal: str) -> str:
    return workflow_text(
        [start(), step("work", goal=goal), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )


def test_round_trip_preserves_yaml_and_compiled_graph(store: SqlWorkflowDefinitionStore) -> None:
    yaml_text = fixture_text("loop")
    saved = _save(store, yaml_text)
    loaded = store.get(workspace_id=1, workflow_id=saved.id)
    assert loaded is not None
    assert loaded.yaml_text == yaml_text
    assert loaded.compiled == compile_text(yaml_text)[0]
    assert loaded.content_hash == loaded.compiled.content_hash
    assert (loaded.workflow_key, loaded.name, loaded.runnable) == (
        "review-loop",
        "Review loop",
        True,
    )
    assert store.get_by_key(workspace_id=1, workflow_key="review-loop") == loaded


def test_get_unknown_or_other_workspace_returns_none(store: SqlWorkflowDefinitionStore) -> None:
    saved = _save(store, fixture_text("minimal"), workspace_id=1)
    assert store.get(workspace_id=1, workflow_id="0" * 32) is None
    assert store.get(workspace_id=2, workflow_id=saved.id) is None
    assert store.get_by_key(workspace_id=2, workflow_key="demo") is None


def test_identical_content_saves_once_with_same_hash(
    store: SqlWorkflowDefinitionStore, clock: _Clock
) -> None:
    first = _save(store, fixture_text("minimal"))
    clock.now += 60
    second = _save(store, fixture_text("minimal"))
    assert second == first
    assert len(store.list_definitions(workspace_id=1)) == 1


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
    assert store.get(workspace_id=1, workflow_id=first.id) == second


def test_invalid_draft_is_stored_as_not_runnable(store: SqlWorkflowDefinitionStore) -> None:
    saved = _save(store, fixture_text("deadlock_join"), runnable=False)
    assert saved.runnable is False
    assert store.get(workspace_id=1, workflow_id=saved.id).runnable is False  # type: ignore[union-attr]


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
    assert [d.id for d in store.list_definitions(workspace_id=2)] == [second.id]


def test_list_is_ordered_by_key(store: SqlWorkflowDefinitionStore) -> None:
    _save(store, fixture_text("parallel"))
    _save(store, fixture_text("minimal"))
    _save(store, fixture_text("loop"))
    assert [d.workflow_key for d in store.list_definitions(workspace_id=1)] == [
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
    loaded = store.get(workspace_id=1, workflow_id=saved.id)
    assert loaded is not None and loaded.yaml_text == yaml_text


def test_oversize_update_leaves_existing_row_untouched(
    store: SqlWorkflowDefinitionStore,
) -> None:
    saved = _save(store, fixture_text("minimal"))
    with pytest.raises(WorkflowTooLargeError):
        _save(store, _noisy_workflow(os.urandom(20_000).hex()))
    assert store.get(workspace_id=1, workflow_id=saved.id) == saved


def test_cap_is_the_framed_byte_limit() -> None:
    assert MAX_STORED_BYTES == 16_383
