"""An anchor the user archived pauses its run, and the engine's next send is refused.

Tier A: a real app and its stores, the run's anchor made by the real facade,
the archive through the real ``PATCH /v1/sessions/{id}``, and the real
``send_input`` executor over the real dispatch with its drift pre-send hook.
The runner is an ``httpx`` mock that records every forwarded body.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from coral.db.enum_codecs import LogKind, RunPauseReason, RunStatus, SessionBindingProgress
from coral.db.migrate import ensure_coral_schema
from coral.omni.server.dispatch import OmnigentSessionDispatch
from coral.omni.server.scopes import OmnigentRunScopeRunner
from coral.queue.executors import EffectFailed, EffectOutcome
from coral.recovery.drift import DriftPauser, DriftPreSendHook
from coral.slots.executors import SEND_INPUT, send_input_executor
from coral.stores.session_bindings import SessionBindingDraft
from coral.stores.stable_ids import SqlAlchemyStableIdStore
from omnigent.runtime.agent_cache import AgentCache
from omnigent.server.app import create_app
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.comment_store.sqlalchemy_store import SqlAlchemyCommentStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.file_store.sqlalchemy_store import SqlAlchemyFileStore
from omnigent.stores.host_store import HostStore
from omnigent.stores.permission_store.sqlalchemy_store import SqlAlchemyPermissionStore
from omnigent.stores.project_store.sqlalchemy_store import SqlAlchemyProjectStore
from tests.coral.omni.test_session_facade import SLOT, WORKSPACE, _Coral, _Stores
from tests.coral.workspace._executor_fakes import effect_context
from tests.server.helpers import create_session_for_agent, create_test_agent
from tests.server.integration.test_sessions_web_send_stable_id import _stub_runner


@pytest.fixture
def stores(db_uri: str, tmp_path: Path) -> _Stores:
    artifact = LocalArtifactStore(str(tmp_path / "artifacts"))
    return _Stores(
        conversation=SqlAlchemyConversationStore(db_uri),
        agent=SqlAlchemyAgentStore(db_uri),
        artifact=artifact,
        agent_cache=AgentCache(artifact_store=artifact, cache_dir=tmp_path / "cache"),
        host=HostStore(db_uri),
        project=SqlAlchemyProjectStore(db_uri),
        permission=SqlAlchemyPermissionStore(db_uri),
        file=SqlAlchemyFileStore(db_uri),
        comment=SqlAlchemyCommentStore(db_uri),
    )


@pytest.fixture
def app(stores: _Stores, db_uri: str) -> FastAPI:
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
    ensure_coral_schema(db_uri)
    return app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_archived_anchor_pauses_the_run_and_refuses_the_send(
    app: FastAPI,
    stores: _Stores,
    db_uri: str,
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded: list[dict[str, Any]] = []
    runner = _stub_runner(monkeypatch, forwarded)
    coral = _Coral(app, stores, db_uri)
    await coral.anchor()
    step_id = await _bound_step(coral, client)
    dispatch = OmnigentSessionDispatch(
        app,
        stores.conversation,
        app.state.runner_router,
        pre_send_hooks=[
            DriftPreSendHook(coral.facade, coral.bindings, DriftPauser(coral.run_store))
        ],
    )
    send = send_input_executor(
        dispatch,
        SqlAlchemyStableIdStore(db_uri),
        coral.bindings,
        coral.run_store,
        OmnigentRunScopeRunner(),
    )
    payload = {
        "effect_type": SEND_INPUT,
        "effect_key": f"{coral.run.id}:3:send_input:{SLOT}",
        "session_id": step_id,
        "text": "Review the parser.",
        "kind": "brief",
    }

    async def deliver() -> EffectOutcome:
        return await send(
            effect_context(workspace_id=WORKSPACE, run_id=coral.run.id, payload=payload)
        )

    try:
        archived = await client.patch(f"/v1/sessions/{coral.anchor_id}", json={"archived": True})
        assert archived.status_code == 200, archived.text
        refused = await deliver()
        held = await deliver()
        # Resumed without unarchiving the anchor: the next send pauses it again.
        coral.set_status(RunStatus.RUNNING)
        refused_again = await deliver()
    finally:
        await runner.aclose()

    assert isinstance(refused, EffectFailed) and isinstance(refused_again, EffectFailed)
    assert (refused.error_code, refused.retryable) == ("drift.anchor_archived", False)
    assert (refused_again.error_code, refused_again.retryable) == ("drift.anchor_archived", False)
    assert isinstance(held, EffectFailed)
    assert (held.error_code, held.retryable) == ("run.paused", True)
    state, _ = coral.run_store.load_run_state(coral.run.id, workspace_id=WORKSPACE)
    assert (state.run.status, state.run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.DRIFT)
    pauses = [
        json.loads(entry.body)
        for entry in coral.run_store.logs[(WORKSPACE, coral.run.id)]
        if entry.kind == int(LogKind.PAUSED)
    ]
    assert [(pause["cause"], pause["session_id"]) for pause in pauses] == [
        ("anchor_archived", coral.anchor_id),
        ("anchor_archived", coral.anchor_id),
    ]
    # Nothing was persisted or forwarded to the step.
    assert stores.conversation.list_items(step_id, type="message").data == []
    assert [body for body in forwarded if body.get("type") == "message"] == []


async def _bound_step(coral: _Coral, client: httpx.AsyncClient) -> str:
    """A session bound to the run as its step, as a finished ``create_session`` leaves it."""
    agent = await create_test_agent(client)
    step_id = await create_session_for_agent(client, agent["id"])
    coral.bindings.reserve(
        SessionBindingDraft(
            workspace_id=WORKSPACE,
            session_id=step_id,
            run_id=coral.run.id,
            role="step",
            effect_key=coral.key(2, SLOT),
            slot_id=SLOT,
            slot_role="step_agent",
        )
    )
    for progress in (SessionBindingProgress.ROW_CREATED, SessionBindingProgress.INITIALIZED):
        coral.bindings.record_progress(WORKSPACE, step_id, progress)
    return step_id
