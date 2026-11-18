"""Pinned workflow versions: immutable rows holding the YAML and compiled graph inline."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from coral.db import CoralBase, WorkflowVersionRow
from coral.db.enum_codecs import WorkflowVersionOrigin, WorkflowVersionStatus
from coral.model import IR_VERSION
from coral.model.ids import derived_id
from coral.model.loader import MAX_DOCUMENT_BYTES
from coral.stores.workflow_versions import PinnedVersion, SqlAlchemyWorkflowVersionStore
from coral.stores.workflows import WorkflowTooLargeError
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    end,
    fixture_text,
    start,
    step,
    workflow_text,
)

WORKSPACE = 7
DEFINITION = "f" * 32


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    sqlite_engine = create_engine(f"sqlite:///{tmp_path / 'coral.db'}")
    CoralBase.metadata.create_all(sqlite_engine)
    yield sqlite_engine
    sqlite_engine.dispose()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def versions(engine: Engine, clock: _Clock) -> SqlAlchemyWorkflowVersionStore:
    return SqlAlchemyWorkflowVersionStore(engine, clock=clock)


def _pin(
    versions: SqlAlchemyWorkflowVersionStore,
    yaml_text: str,
    *,
    workspace_id: int = WORKSPACE,
    created_by: str | None = "alice",
) -> PinnedVersion:
    graph, _ = compile_text(yaml_text)
    return versions.pin(
        workspace_id=workspace_id,
        workflow_id=DEFINITION,
        graph=graph,
        yaml_text=yaml_text,
        created_by=created_by,
    )


def _rows(engine: Engine) -> list[WorkflowVersionRow]:
    with Session(engine) as session:
        return list(session.scalars(select(WorkflowVersionRow)))


def test_pin_twice_stores_one_version_and_load_returns_the_graph_with_its_analysis(
    versions: SqlAlchemyWorkflowVersionStore, engine: Engine, clock: _Clock
) -> None:
    yaml_text = fixture_text("loop")
    graph, _ = compile_text(yaml_text)
    assert graph.analysis.loops

    pinned = _pin(versions, yaml_text)
    clock.now += 60
    assert _pin(versions, yaml_text, created_by="bob") == pinned

    assert pinned == PinnedVersion(
        workspace_id=WORKSPACE,
        id=derived_id("coral-workflow-version", DEFINITION, graph.content_hash),
        workflow_id=DEFINITION,
        content_hash=graph.content_hash,
        graph=graph,
        yaml_text=yaml_text,
    )
    loaded = versions.load(workspace_id=WORKSPACE, version_id=pinned.id)
    assert loaded == pinned
    assert loaded is not None and loaded.graph.analysis == graph.analysis
    [row] = _rows(engine)
    assert (row.yaml_ref, row.compiled_ref, row.created_by, row.created_at) == (
        None,
        None,
        "alice",
        1_000,
    )
    assert (row.compiler_version, row.origin, row.validation_state, row.yaml_bytes) == (
        IR_VERSION,
        int(WorkflowVersionOrigin.SAVED),
        int(WorkflowVersionStatus.VALID),
        len(yaml_text.encode()),
    )


def test_changed_content_pins_a_new_version_and_keeps_the_old_one(
    versions: SqlAlchemyWorkflowVersionStore,
) -> None:
    first = _pin(versions, fixture_text("minimal"))
    changed = _pin(versions, fixture_text("minimal").replace("Do the thing", "Do another thing"))

    assert changed.id != first.id
    assert versions.load(workspace_id=WORKSPACE, version_id=first.id) == first
    assert versions.load(workspace_id=WORKSPACE, version_id=changed.id) == changed


def test_load_of_an_unknown_version_or_another_workspace_finds_nothing(
    versions: SqlAlchemyWorkflowVersionStore,
) -> None:
    pinned = _pin(versions, fixture_text("minimal"))

    assert versions.load(workspace_id=WORKSPACE, version_id="0" * 32) is None
    assert versions.load(workspace_id=WORKSPACE + 1, version_id=pinned.id) is None
    assert _pin(versions, fixture_text("minimal"), workspace_id=WORKSPACE + 1) == (
        dataclasses.replace(pinned, workspace_id=WORKSPACE + 1)
    )


def test_version_over_the_cap_is_refused_before_writing(
    versions: SqlAlchemyWorkflowVersionStore, engine: Engine
) -> None:
    noisy = workflow_text(
        [start(), step("work", goal=os.urandom(20_000).hex()), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "end")],
    )

    with pytest.raises(WorkflowTooLargeError):
        _pin(versions, noisy)
    assert _rows(engine) == []


def test_graph_without_a_content_hash_is_refused(
    versions: SqlAlchemyWorkflowVersionStore,
) -> None:
    graph, _ = compile_text(fixture_text("minimal"))

    with pytest.raises(ValueError, match="content hash"):
        versions.pin(
            workspace_id=WORKSPACE,
            workflow_id=DEFINITION,
            graph=graph.model_copy(update={"content_hash": ""}),
            yaml_text=fixture_text("minimal"),
            created_by=None,
        )


def test_version_stored_by_blob_ref_is_not_loadable_inline(
    versions: SqlAlchemyWorkflowVersionStore, engine: Engine
) -> None:
    with engine.begin() as connection:
        connection.execute(
            WorkflowVersionRow.__table__.insert().values(
                workspace_id=WORKSPACE,
                id="1" * 32,
                workflow_id=DEFINITION,
                content_hash=b"\0" * 32,
                yaml_ref="blob://yaml",
                yaml_bytes=10,
                compiled_ref="blob://compiled",
                compiler_version=IR_VERSION,
                origin=int(WorkflowVersionOrigin.SAVED),
                validation_state=int(WorkflowVersionStatus.VALID),
                created_at=1,
            )
        )

    with pytest.raises(ValueError, match="not stored inline"):
        versions.load(workspace_id=WORKSPACE, version_id="1" * 32)


def test_pin_refuses_ids_and_text_the_columns_cannot_hold(
    versions: SqlAlchemyWorkflowVersionStore, engine: Engine
) -> None:
    graph, _ = compile_text(fixture_text("minimal"))
    fields = {
        "workspace_id": WORKSPACE,
        "workflow_id": DEFINITION,
        "graph": graph,
        "yaml_text": fixture_text("minimal"),
        "created_by": None,
    }

    for changes, message in (
        # A load returns the hash in lowercase, so an upper-case one could never match.
        ({"graph": graph.model_copy(update={"content_hash": graph.content_hash.upper()})}, "hash"),
        ({"workflow_id": "workflow-1"}, "workflow_id"),
        ({"created_by": "u" * 129}, "created_by"),
    ):
        with pytest.raises(ValueError, match=message):
            versions.pin(**{**fields, **changes})  # type: ignore[arg-type]

    # YAML that compresses under the cap is still refused past the loader's document limit.
    padded = fixture_text("minimal") + "# " + "x" * MAX_DOCUMENT_BYTES + "\n"
    with pytest.raises(WorkflowTooLargeError, match="yaml_text"):
        versions.pin(**{**fields, "yaml_text": padded})  # type: ignore[arg-type]
    assert _rows(engine) == []
