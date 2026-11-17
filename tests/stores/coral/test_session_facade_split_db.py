"""A torn anchor or step row from a split-DB create is repaired once on redelivery.

The conversation store writes the conversation row to its own database first
and the metadata (an anchor's ``project_id``, a step's ``host_id``) to the
operational database second.
A crash between the two leaves a torn row. The binding, still at
``reserved``, tells the next delivery that this row is its own unfinished
create, so it deletes and re-creates it once.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from coral.db.enum_codecs import SessionBindingProgress
from coral.model.ids import anchor_session_id
from coral.omni.process_map import CORAL_RUNNER_TOKEN
from coral.omni.protocols import SessionCreateRequest
from coral.omni.server.sessions import CORAL_RUNS_PROJECT_NAME, OmnigentSessionFacade
from coral.stores.session_bindings import SqlAlchemySessionBindingStore
from omnigent.db.db_models import SqlConversation, SqlConversationMetadata
from omnigent.db.utils import get_or_create_conversation_engine
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.server.server_plugins import ServerServices
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.comment_store.sqlalchemy_store import SqlAlchemyCommentStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from tests.coral.omni.test_session_facade import (
    _completed,
    _Coral,
    _DiesOnUse,
    _Host,
    _RecordingLauncher,
    _Stores,
)
from tests.server.integration.test_session_host_launch import _HOST_ID, _connect_host
from tests.stores.coral._faults import SimulatedCrash, fresh_process
from tests.stores.coral.conftest import CoralSplitDb

WORKSPACE = 0
RUN_ID = "7" * 32


def _facade(
    split: CoralSplitDb, conversation_store: SqlAlchemyConversationStore, tmp_path: Path
) -> OmnigentSessionFacade:
    artifact = LocalArtifactStore(str(tmp_path / "artifacts"))
    services = SimpleNamespace(
        conversation_store=conversation_store,
        agent_store=SqlAlchemyAgentStore(split.operational_uri),
        artifact_store=artifact,
        agent_cache=AgentCache(artifact_store=artifact, cache_dir=tmp_path / "cache"),
        permission_store=SqlAlchemyPermissionStore(split.operational_uri),
        project_store=SqlAlchemyProjectStore(split.operational_uri),
        host_store=None,
        host_registry=None,
        runner_router=None,
        auth_provider=None,
    )
    return OmnigentSessionFacade(
        SimpleNamespace(state=SimpleNamespace()),
        cast(ServerServices, services),
        SqlAlchemySessionBindingStore(split.operational_uri),
    )


def _anchor_request(effect_seq: int) -> SessionCreateRequest:
    return SessionCreateRequest(
        workspace_id=WORKSPACE,
        run_id=RUN_ID,
        effect_key=f"{RUN_ID}:{effect_seq}:create_session:anchor",
        user_id=None,
        account_generation=None,
        role="anchor",
        title="Review the change",
    )


async def _no_lease_check() -> None:
    return None


def _rows(split: CoralSplitDb, session_id: str) -> tuple[int, int]:
    """Conversation rows in the conversation DB and metadata rows in the operational DB."""
    from sqlalchemy import func, select

    conversation_engine = get_or_create_conversation_engine(split.conversation_uri)
    operational_engine = fresh_process(split.operational_uri)
    with conversation_engine.connect() as connection:
        conversations = connection.execute(
            select(func.count())
            .select_from(SqlConversation)
            .where(SqlConversation.id == session_id)
        ).scalar_one()
    with operational_engine.connect() as connection:
        metadata = connection.execute(
            select(func.count())
            .select_from(SqlConversationMetadata)
            .where(SqlConversationMetadata.id == session_id)
        ).scalar_one()
    return conversations, metadata


async def test_torn_anchor_row_is_repaired_once_on_redelivery(
    coral_split_db: CoralSplitDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    anchor_id = anchor_session_id(WORKSPACE, RUN_ID)
    first = _facade(coral_split_db, coral_split_db.conversation_store, tmp_path)

    # The metadata phase never commits: the process dies after the conversation row.
    with monkeypatch.context() as crash:
        store = coral_split_db.conversation_store
        crash.setattr(store, "_session_immediate", _DiesOnUse(store._session_immediate))
        with pytest.raises(SimulatedCrash):
            await first.create_session(_anchor_request(1), ensure_lease=_no_lease_check)
    assert _rows(coral_split_db, anchor_id) == (1, 0)

    # A new process redelivers the effect.
    fresh_process(coral_split_db.conversation_uri, connect=get_or_create_conversation_engine)
    reopened = SqlAlchemyConversationStore(
        coral_split_db.operational_uri, coral_split_db.conversation_uri
    )
    deletes: list[str] = []
    real_delete = reopened.delete_conversation

    async def counted_delete(conversation_id: str, **kwargs: Any) -> bool:
        deletes.append(conversation_id)
        return await real_delete(conversation_id, **kwargs)

    monkeypatch.setattr(reopened, "delete_conversation", counted_delete)
    second = _facade(coral_split_db, reopened, tmp_path)
    torn = reopened.get_conversation(anchor_id)
    assert torn is not None and torn.project_id is None

    repaired = await second.create_session(_anchor_request(1), ensure_lease=_no_lease_check)
    again = await second.create_session(_anchor_request(1), ensure_lease=_no_lease_check)

    assert (repaired.session_id, repaired.created, again.created) == (anchor_id, True, False)
    assert deletes == [anchor_id]
    assert _rows(coral_split_db, anchor_id) == (1, 1)
    anchor = reopened.get_conversation(anchor_id)
    assert anchor is not None
    project = SqlAlchemyProjectStore(coral_split_db.operational_uri).get(
        anchor.project_id or "", user_id=None
    )
    assert project is not None and project.name == CORAL_RUNS_PROJECT_NAME
    binding = SqlAlchemySessionBindingStore(coral_split_db.operational_uri).get(
        WORKSPACE, anchor_id, run_id=RUN_ID
    )
    assert binding is not None and binding.progress == SessionBindingProgress.INITIALIZED


async def test_torn_step_row_is_repaired_once_on_redelivery(
    coral_split_db: CoralSplitDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operational = coral_split_db.operational_uri
    artifact = LocalArtifactStore(str(tmp_path / "artifacts"))
    stores = _Stores(
        conversation=coral_split_db.conversation_store,
        agent=SqlAlchemyAgentStore(operational),
        artifact=artifact,
        agent_cache=AgentCache(artifact_store=artifact, cache_dir=tmp_path / "cache"),
        host=HostStore(operational),
        project=SqlAlchemyProjectStore(operational),
        permission=SqlAlchemyPermissionStore(operational),
        file=SqlAlchemyFileStore(operational),
        comment=SqlAlchemyCommentStore(operational),
    )
    app = create_app(
        agent_store=stores.agent,
        file_store=stores.file,
        conversation_store=stores.conversation,
        artifact_store=stores.artifact,
        agent_cache=stores.agent_cache,
        comment_store=stores.comment,
        host_store=stores.host,
        project_store=stores.project,
    )
    launcher = _RecordingLauncher()
    coral = _Coral(app, stores, operational, launcher=launcher)
    store = stores.conversation
    step_id = coral.step_id()
    async with _Host(app, await _connect_host(app, [CORAL_RUNNER_TOKEN])):
        await coral.anchor()

        # The step's metadata (host, workspace) never commits to the operational DB.
        with monkeypatch.context() as crash:
            crash.setattr(store, "_session_immediate", _DiesOnUse(store._session_immediate))
            with pytest.raises(SimulatedCrash):
                await coral.deliver(coral.step_payload())
        assert _rows(coral_split_db, step_id) == (1, 0)
        torn = store.get_conversation(step_id)
        assert torn is not None and torn.host_id is None

        deletes: list[str] = []
        real_delete = store.delete_conversation

        async def counted_delete(conversation_id: str, **kwargs: Any) -> bool:
            deletes.append(conversation_id)
            return await real_delete(conversation_id, **kwargs)

        monkeypatch.setattr(store, "delete_conversation", counted_delete)
        _completed(await coral.deliver(coral.step_payload()))
        _completed(await coral.deliver(coral.step_payload()))

    assert deletes == [step_id]
    assert _rows(coral_split_db, step_id) == (1, 1)
    assert coral.children() == [step_id]
    step = store.get_conversation(step_id)
    assert step is not None and step.host_id == _HOST_ID
    assert [call["conv"].id for call in launcher.calls] == [step_id]
    assert coral.progress(step_id) == SessionBindingProgress.INITIALIZED
