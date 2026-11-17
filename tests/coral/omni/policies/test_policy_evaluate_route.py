"""The run guard and the orchestrator allowlist on S21's path: ``POST /policies/evaluate``.

claude-sdk's PreToolUse hook posts every native and connector tool call of a
Coral bundle here (only ``mcp__omnigent__*`` goes through ``/mcp``). The app
is built as the session facade tests build it, the session's agent is a
generated Coral bundle, and Coral's guards are wired as the lifespan wires
them over the real run and binding stores.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.db.migrate import ensure_coral_schema
from coral.model.ids import anchor_session_id
from coral.omni.server.plugin import _wire_guards
from coral.omni.server.sessions import ROLE_LABEL_KEY, RUN_ID_LABEL_KEY
from coral.profiles.bundle_spec import Stance
from coral.stores.protocols import RunStartSpec, Transition
from coral.stores.runs import SqlAlchemyCoralRunStore
from coral.stores.session_bindings import SessionBindingDraft, SqlAlchemySessionBindingStore
from omnigent.db.db_models import DEFAULT_WORKSPACE_ID
from omnigent.runtime import init as init_runtime
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
from tests.coral.omni.test_session_facade import _coral_agent, _Stores
from tests.server.helpers import policy_tool_call_request

WORKSPACE = DEFAULT_WORKSPACE_ID
STOP = "Stop now and end your turn"
NATIVE_AND_CONNECTOR_TOOLS = ("Skill", "mcp__fs__write_file")


@dataclass
class _Coral:
    """A Coral run's stores, an HTTP client on the app, and the guards wired for the test."""

    stores: _Stores
    client: httpx.AsyncClient
    runs: SqlAlchemyCoralRunStore
    bindings: SqlAlchemySessionBindingStore

    def start_run(self) -> str:
        run = self.runs.start_run(RunStartSpec("review", "v1", "Run", "", workspace_id=WORKSPACE))
        self.set_status(run.id, RunStatus.RUNNING)
        return run.id

    def set_status(
        self, run_id: str, status: RunStatus, *, reason: RunPauseReason | None = None
    ) -> None:
        _, version = self.runs.load_run_state(run_id, workspace_id=WORKSPACE)
        self.runs.apply_transition(
            run_id,
            version,
            Transition(
                status=int(status),
                pause_reason=None if reason is None else int(reason),
                clear_pause_reason=reason is None,
            ),
            workspace_id=WORKSPACE,
        )

    def bound_session(self, run_id: str, stance: Stance) -> str:
        """A session on the generated *stance* bundle, bound to *run_id* in that slot role."""
        orchestrator = stance == Stance.ORCHESTRATOR
        slot_role = "orchestrator" if orchestrator else "step_agent"
        session_id = self.stores.conversation.create_conversation(
            agent_id=_coral_agent(self.stores, stance),
            labels={RUN_ID_LABEL_KEY: run_id, ROLE_LABEL_KEY: slot_role},
        ).id
        slot = "orchestrator" if orchestrator else "review/item-0/m0"
        self.bindings.reserve(
            SessionBindingDraft(
                workspace_id=WORKSPACE,
                session_id=session_id,
                run_id=run_id,
                role="step",
                effect_key=f"{run_id}:2:create_session:{slot}",
                slot_id=slot,
                slot_role=slot_role,
            )
        )
        return session_id

    async def evaluate(self, session_id: str, tool: str) -> dict[str, str]:
        response = await self.client.post(
            f"/v1/sessions/{session_id}/policies/evaluate", json=policy_tool_call_request(tool)
        )
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def stores(db_uri: str, tmp_path: Path) -> _Stores:
    """The app's stores; the route loads the session's bundle through the runtime's cache."""
    artifact = LocalArtifactStore(str(tmp_path / "artifacts"))
    stores = _Stores(
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
    init_runtime(
        conversation_store=stores.conversation,
        agent_store=stores.agent,
        agent_cache=stores.agent_cache,
        file_store=stores.file,
        artifact_store=stores.artifact,
    )
    return stores


@pytest_asyncio.fixture
async def coral(stores: _Stores, db_uri: str) -> AsyncIterator[_Coral]:
    app: FastAPI = create_app(
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
    runs = SqlAlchemyCoralRunStore(db_uri)
    bindings = SqlAlchemySessionBindingStore(db_uri)
    transport = httpx.ASGITransport(app=app)
    async with (
        AsyncExitStack() as stack,
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        _wire_guards(run_store=runs, bindings=bindings, stack=stack)
        yield _Coral(stores=stores, client=client, runs=runs, bindings=bindings)


def _deciding_policies(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The deciding policy of each DENY the route logged, in order."""
    lines = [record.getMessage() for record in caplog.records]
    verdicts = [line for line in lines if line.startswith("policy_eval_verdict")]
    return [line.split(" policy=", 1)[1].split(" ", 1)[0] for line in verdicts]


async def test_paused_step_is_denied_native_and_connector_tools(
    coral: _Coral, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    run_id = coral.start_run()
    step = coral.bound_session(run_id, Stance.IMPLEMENTER)
    for tool in NATIVE_AND_CONNECTOR_TOOLS:
        assert await coral.evaluate(step, tool) == {"result": "POLICY_ACTION_ALLOW"}, tool

    # The pause commits through the run store; the next hook call sees it at once.
    coral.set_status(run_id, RunStatus.PAUSED, reason=RunPauseReason.DRIFT)

    for tool in NATIVE_AND_CONNECTOR_TOOLS:
        verdict = await coral.evaluate(step, tool)
        assert verdict["result"] == "POLICY_ACTION_DENY", tool
        assert verdict["reason"].startswith("[run.paused] The Coral run is paused (drift).")
        assert STOP in verdict["reason"] and "coral_submit_handoff" not in verdict["reason"]
    # ToolSearch loads deferred tools, so a paused step can still reach the engine's answer.
    assert await coral.evaluate(step, "ToolSearch") == {"result": "POLICY_ACTION_ALLOW"}
    assert _deciding_policies(caplog) == ["__coral_run_guard"] * 2


async def test_orchestrator_is_denied_native_and_connector_tools(
    coral: _Coral, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    run_id = coral.start_run()
    orchestrator = coral.bound_session(run_id, Stance.ORCHESTRATOR)

    for tool in NATIVE_AND_CONNECTOR_TOOLS:
        verdict = await coral.evaluate(orchestrator, tool)
        assert verdict == {
            "result": "POLICY_ACTION_DENY",
            "reason": "[orchestrator] A Coral orchestrator can only call coral_choose_arrow "
            "(and ToolSearch to load it).",
        }, tool
    assert await coral.evaluate(orchestrator, "ToolSearch") == {"result": "POLICY_ACTION_ALLOW"}
    # The provider's copy, keyed on the binding, decides ahead of the bundle's own guard.
    assert _deciding_policies(caplog) == ["__coral_orchestrator_guard"] * 2


@dataclass
class _StoreReads:
    """Every binding and run read Coral's guards make through the real stores."""

    bindings: list[str]
    runs: list[str]


@pytest.fixture
def store_reads(monkeypatch: pytest.MonkeyPatch) -> _StoreReads:
    reads = _StoreReads(bindings=[], runs=[])
    find = SqlAlchemySessionBindingStore.find_by_session
    get_run = SqlAlchemyCoralRunStore.get_run

    def counted_find(store: SqlAlchemySessionBindingStore, workspace_id: int, session_id: str):
        reads.bindings.append(session_id)
        return find(store, workspace_id, session_id)

    def counted_get_run(store: SqlAlchemyCoralRunStore, run_id: str, **kwargs: Any):
        reads.runs.append(run_id)
        return get_run(store, run_id, **kwargs)

    monkeypatch.setattr(SqlAlchemySessionBindingStore, "find_by_session", counted_find)
    monkeypatch.setattr(SqlAlchemyCoralRunStore, "get_run", counted_get_run)
    return reads


TOOLS = ("Skill", "mcp__fs__write_file", "Bash", "ToolSearch", "coral_submit_handoff")


async def test_anchor_is_denied_every_tool(
    coral: _Coral, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    run_id = coral.start_run()
    anchor = anchor_session_id(WORKSPACE, run_id)
    coral.stores.conversation.create_conversation(
        conversation_id=anchor, agent_id=_coral_agent(coral.stores, Stance.ANCHOR)
    )
    coral.bindings.reserve(
        SessionBindingDraft(
            workspace_id=WORKSPACE,
            session_id=anchor,
            run_id=run_id,
            role="anchor",
            effect_key=f"{run_id}:1:create_anchor",
        )
    )

    for tool in TOOLS:
        assert await coral.evaluate(anchor, tool) == {
            "result": "POLICY_ACTION_DENY",
            "reason": "[anchor] The Coral run anchor does not run tools.",
        }, tool
    # The provider's copy decides ahead of the bundle's own deny-all.
    assert _deciding_policies(caplog) == ["__coral_anchor_deny_all"] * len(TOOLS)


async def test_verifier_gets_the_roster_then_the_run_guard(
    coral: _Coral, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    run_id = coral.start_run()
    verifier = coral.bound_session(run_id, Stance.REVIEWER)

    assert await coral.evaluate(verifier, "Read") == {"result": "POLICY_ACTION_ALLOW"}
    roster = await coral.evaluate(verifier, "sys_session_message")
    assert roster["reason"].startswith("[roster]")
    coral.set_status(run_id, RunStatus.COMPLETED)
    finished = await coral.evaluate(verifier, "Read")
    assert (
        finished["reason"]
        == "[run.finished] The Coral run has finished. Stop now and end your turn."
    )
    assert await coral.evaluate(verifier, "coral_submit_handoff") == {
        "result": "POLICY_ACTION_ALLOW"
    }
    assert _deciding_policies(caplog) == ["__coral_step_roster", "__coral_run_guard"]


async def test_an_ordinary_session_never_reads_a_coral_store(
    coral: _Coral, store_reads: _StoreReads
) -> None:
    run_id = coral.start_run()
    coral.set_status(run_id, RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    plain_agent = _coral_agent(coral.stores, Stance.IMPLEMENTER, name="plain-step", params={})
    # A plain agent with guardrails (the engine is built) and one with none (the fast path).
    bare_agent = _coral_agent(
        coral.stores, Stance.IMPLEMENTER, name="bare-step", params={}, guardrails=None
    )
    store_reads.runs.clear()
    for agent_id in (plain_agent, bare_agent):
        session_id = coral.stores.conversation.create_conversation(agent_id=agent_id).id
        for tool in TOOLS:
            assert await coral.evaluate(session_id, tool) == {"result": "POLICY_ACTION_ALLOW"}
    assert (store_reads.bindings, store_reads.runs) == ([], [])


async def test_copied_labels_without_a_binding_read_no_run(
    coral: _Coral, store_reads: _StoreReads
) -> None:
    run_id = coral.start_run()
    coral.set_status(run_id, RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    copied = coral.stores.conversation.create_conversation(
        agent_id=_coral_agent(coral.stores, Stance.IMPLEMENTER),
        labels={RUN_ID_LABEL_KEY: run_id, ROLE_LABEL_KEY: "step_agent"},
    ).id
    store_reads.runs.clear()

    for tool in ("Skill", "mcp__fs__write_file"):
        assert await coral.evaluate(copied, tool) == {"result": "POLICY_ACTION_ALLOW"}, tool
    # Looked for a binding on each build, found none and read no run.
    assert store_reads.bindings == [copied, copied]
    assert store_reads.runs == []
