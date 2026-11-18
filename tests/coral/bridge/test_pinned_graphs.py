"""Pinned graphs load only when their stored hash is the hash of the graph itself."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, update

from coral.bridge.graphs import (
    PinnedGraphError,
    PinnedGraphMismatch,
    PinnedGraphMissing,
    PinnedGraphs,
    PinnedGraphUnreadable,
    verified_content_hash,
)
from coral.db import CoralBase, WorkflowVersionRow
from coral.db.enum_codecs import WorkflowVersionOrigin, WorkflowVersionStatus
from coral.model import IR_VERSION
from coral.model.ir import CompiledGraph
from coral.stores.workflow_versions import PinnedVersion, SqlAlchemyWorkflowVersionStore
from tests.coral.bridge._scripted_runs import WORKSPACE, fixture_graph
from tests.coral.workflow_builders import fixture_text

DEFINITION = "f" * 32
GRAPH = fixture_graph("two_steps")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    sqlite_engine = create_engine(f"sqlite:///{tmp_path / 'coral.db'}")
    CoralBase.metadata.create_all(sqlite_engine)
    yield sqlite_engine
    sqlite_engine.dispose()


@pytest.fixture
def versions(engine: Engine) -> SqlAlchemyWorkflowVersionStore:
    return SqlAlchemyWorkflowVersionStore(engine, clock=lambda: 1_000.0)


class CountingVersions:
    def __init__(self, versions: SqlAlchemyWorkflowVersionStore) -> None:
        self.versions = versions
        self.loads = 0

    def load(self, *, workspace_id: int, version_id: str) -> PinnedVersion | None:
        self.loads += 1
        return self.versions.load(workspace_id=workspace_id, version_id=version_id)


def _pin(versions: SqlAlchemyWorkflowVersionStore, graph: CompiledGraph = GRAPH) -> PinnedVersion:
    return versions.pin(
        workspace_id=WORKSPACE,
        workflow_id=DEFINITION,
        graph=graph,
        yaml_text=fixture_text("two_steps"),
        created_by="alice",
    )


def test_a_pinned_graph_loads_with_its_hash_and_is_read_once(
    versions: SqlAlchemyWorkflowVersionStore,
) -> None:
    pinned = _pin(versions)
    counting = CountingVersions(versions)
    graphs = PinnedGraphs(counting)
    for _ in range(3):
        loaded = graphs.load(
            workspace_id=WORKSPACE, version_id=pinned.id, expected_hash=GRAPH.content_hash
        )
        assert loaded == GRAPH
    assert counting.loads == 1
    assert graphs.load(workspace_id=WORKSPACE, version_id=pinned.id) == GRAPH


def test_the_hash_is_recomputed_from_the_graph() -> None:
    assert verified_content_hash(GRAPH) == GRAPH.content_hash
    for forged in ("a" * 64, ""):
        with pytest.raises(PinnedGraphMismatch):
            verified_content_hash(GRAPH.model_copy(update={"content_hash": forged}))
    changed = GRAPH.model_copy(update={"name": "Another name"})
    with pytest.raises(PinnedGraphMismatch):
        verified_content_hash(changed)


def test_a_graph_pinned_under_a_hash_it_does_not_have_is_refused(
    versions: SqlAlchemyWorkflowVersionStore,
) -> None:
    # The store keeps whatever hash its caller gives.
    forged = GRAPH.model_copy(update={"content_hash": "a" * 64})
    pinned = _pin(versions, forged)
    with pytest.raises(PinnedGraphMismatch, match=pinned.id):
        PinnedGraphs(versions).load(workspace_id=WORKSPACE, version_id=pinned.id)


def test_a_row_whose_graph_changed_after_it_was_pinned_is_refused(
    versions: SqlAlchemyWorkflowVersionStore, engine: Engine
) -> None:
    pinned = _pin(versions)
    tampered = GRAPH.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(update={"goal": "Delete everything"})
                if node.id == "review"
                else node
                for node in GRAPH.nodes
            )
        }
    )
    with engine.begin() as connection:
        connection.execute(
            update(WorkflowVersionRow)
            .where(WorkflowVersionRow.id == pinned.id)
            .values(compiled_json=tampered.model_dump_json())
        )
    with pytest.raises(PinnedGraphMismatch):
        PinnedGraphs(versions).load(workspace_id=WORKSPACE, version_id=pinned.id)


def test_a_row_whose_hash_or_id_is_not_its_graphs_is_refused(
    versions: SqlAlchemyWorkflowVersionStore, engine: Engine
) -> None:
    pinned = _pin(versions)
    with engine.begin() as connection:
        connection.execute(
            update(WorkflowVersionRow)
            .where(WorkflowVersionRow.id == pinned.id)
            .values(content_hash=b"\1" * 32)
        )
        copied = connection.execute(
            WorkflowVersionRow.__table__.select().where(WorkflowVersionRow.id == pinned.id)
        ).one()
        connection.execute(
            WorkflowVersionRow.__table__.insert().values(
                {
                    **copied._mapping,
                    "id": "2" * 32,
                    "content_hash": bytes.fromhex(GRAPH.content_hash),
                }
            )
        )
    graphs = PinnedGraphs(versions)
    for version_id in (pinned.id, "2" * 32):
        with pytest.raises(PinnedGraphMismatch, match=version_id):
            graphs.load(workspace_id=WORKSPACE, version_id=version_id)


def test_the_run_must_name_the_hash_it_was_started_with(
    versions: SqlAlchemyWorkflowVersionStore,
) -> None:
    pinned = _pin(versions)
    graphs = PinnedGraphs(versions)
    with pytest.raises(PinnedGraphMismatch):
        graphs.load(workspace_id=WORKSPACE, version_id=pinned.id, expected_hash="b" * 64)
    graphs.load(workspace_id=WORKSPACE, version_id=pinned.id)
    with pytest.raises(PinnedGraphMismatch):
        graphs.load(workspace_id=WORKSPACE, version_id=pinned.id, expected_hash="b" * 64)


def test_a_missing_or_blob_only_version_does_not_load(
    versions: SqlAlchemyWorkflowVersionStore, engine: Engine
) -> None:
    pinned = _pin(versions)
    graphs = PinnedGraphs(versions)
    with pytest.raises(PinnedGraphMissing):
        graphs.load(workspace_id=WORKSPACE, version_id="0" * 32)
    with pytest.raises(PinnedGraphMissing):
        graphs.load(workspace_id=WORKSPACE + 1, version_id=pinned.id)
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
    with pytest.raises(PinnedGraphUnreadable):
        graphs.load(workspace_id=WORKSPACE, version_id="1" * 32)
    for error in (PinnedGraphMissing, PinnedGraphMismatch, PinnedGraphUnreadable):
        assert issubclass(error, PinnedGraphError)


def test_the_loaded_graph_keeps_its_analysis_and_its_workspace(
    versions: SqlAlchemyWorkflowVersionStore,
) -> None:
    loop = fixture_graph("loop")
    assert loop.analysis.loops
    pinned = versions.pin(
        workspace_id=WORKSPACE,
        workflow_id=DEFINITION,
        graph=loop,
        yaml_text=fixture_text("loop"),
        created_by="alice",
    )
    graphs = PinnedGraphs(versions)
    loaded = graphs.load(
        workspace_id=WORKSPACE, version_id=pinned.id, expected_hash=loop.content_hash
    )
    assert loaded.analysis == loop.analysis
    # The cached graph is this workspace's; another workspace reads its own rows.
    with pytest.raises(PinnedGraphMissing):
        graphs.load(workspace_id=WORKSPACE + 1, version_id=pinned.id)


@pytest.mark.parametrize("compiled_json", ['{"nodes": [', '{"workflow_id": "x"}', "[]"])
def test_a_row_whose_graph_does_not_parse_is_unreadable(
    versions: SqlAlchemyWorkflowVersionStore, engine: Engine, compiled_json: str
) -> None:
    pinned = _pin(versions)
    with engine.begin() as connection:
        connection.execute(
            update(WorkflowVersionRow)
            .where(WorkflowVersionRow.id == pinned.id)
            .values(compiled_json=compiled_json)
        )
    with pytest.raises(PinnedGraphUnreadable, match=pinned.id):
        PinnedGraphs(versions).load(workspace_id=WORKSPACE, version_id=pinned.id)
