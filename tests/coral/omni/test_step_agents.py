"""A step's stance becomes the run owner's materialized Coral bundle, once per bundle."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from coral.omni.protocols import CoralSessionError, StepAgentResolver
from coral.omni.server import step_agents as step_agents_module
from coral.omni.server.bundles import MaterializedAgent, StepBundleRejected
from coral.omni.server.step_agents import OmnigentStepAgents
from coral.profiles.bundle_spec import Stance
from omnigent.db.db_models import current_workspace_id, workspace_scope
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

OWNER = "alice@example.com"
WORKSPACE = 5
STEP = {"workflow_slug": "two-steps", "node_id": "implement", "roster_index": 0}

pytestmark = pytest.mark.usefixtures("coral_policy_registry")


def _single_user(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    """Run as a single-user local server, or as a server without that marker."""
    if enabled:
        monkeypatch.setenv("OMNIGENT_LOCAL_SINGLE_USER", "1")
    else:
        monkeypatch.delenv("OMNIGENT_LOCAL_SINGLE_USER", raising=False)


@pytest.fixture
def agent_store(db_uri: str) -> SqlAlchemyAgentStore:
    return SqlAlchemyAgentStore(db_uri)


@pytest.fixture
def agents(agent_store: SqlAlchemyAgentStore, tmp_path: Path) -> OmnigentStepAgents:
    return OmnigentStepAgents(agent_store, LocalArtifactStore(str(tmp_path / "artifacts")))


@pytest.fixture
def materialized(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Each materialize call: its owner, stance, workspace and thread."""
    calls: list[dict[str, Any]] = []
    real = step_agents_module.materialize

    def recording(*args: Any, **kwargs: Any) -> MaterializedAgent:
        calls.append(
            {
                "owner": kwargs["owner"],
                "stance": kwargs["stance"],
                "workspace_id": current_workspace_id(),
                "thread": threading.current_thread(),
            }
        )
        return real(*args, **kwargs)

    monkeypatch.setattr(step_agents_module, "materialize", recording)
    return calls


async def test_a_stance_resolves_to_the_owners_bundle_and_repeats_reuse_it(
    agents: OmnigentStepAgents,
    agent_store: SqlAlchemyAgentStore,
    materialized: list[dict[str, Any]],
) -> None:
    assert isinstance(agents, StepAgentResolver)

    first = await agents.resolve(workspace_id=WORKSPACE, owner=OWNER, stance="implementer", **STEP)
    again = await agents.resolve(workspace_id=WORKSPACE, owner=OWNER, stance="implementer", **STEP)

    assert first == again
    [call] = materialized
    assert (call["owner"], call["stance"], call["workspace_id"]) == (
        OWNER,
        Stance.IMPLEMENTER,
        WORKSPACE,
    )
    assert call["thread"] is not threading.main_thread()
    with workspace_scope(WORKSPACE):
        agent = agent_store.get(first)
    assert agent is not None
    assert (agent.kind, agent.created_by, agent.name) == (
        "user",
        OWNER,
        "coral__two-steps__implement__m0",
    )


@pytest.mark.parametrize(("single_user", "stored_as"), [(True, "local"), (False, None)])
async def test_an_ownerless_runs_step_is_one_agent_across_concurrent_and_restarted_resolvers(
    agent_store: SqlAlchemyAgentStore,
    tmp_path: Path,
    materialized: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    single_user: bool,
    stored_as: str | None,
) -> None:
    """
    An auth-less server's run has no owner; each process materializes the same row.

    A single-user server reads no user as its local user, so the row is that user's.
    """
    _single_user(monkeypatch, single_user)
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))

    async def resolve() -> str:
        return await OmnigentStepAgents(agent_store, artifacts).resolve(
            workspace_id=WORKSPACE, owner=None, stance="implementer", **STEP
        )

    concurrent = await asyncio.gather(resolve(), resolve(), resolve())
    restarted = await resolve()

    assert set(concurrent) == {restarted}
    assert len(materialized) == 4
    with workspace_scope(WORKSPACE):
        agent = agent_store.get(restarted)
    assert agent is not None
    assert (agent.kind, agent.created_by) == ("user", stored_as)
    assert {call["owner"] for call in materialized} == {stored_as}


async def test_another_step_owner_or_workspace_gets_its_own_bundle(
    agents: OmnigentStepAgents, materialized: list[dict[str, Any]]
) -> None:
    base = {"workspace_id": WORKSPACE, "owner": OWNER, "stance": "implementer", **STEP}
    variants = [
        base,
        {**base, "roster_index": 1},
        {**base, "stance": "reviewer"},
        {**base, "owner": "bob@example.com"},
        {**base, "workspace_id": WORKSPACE + 1},
    ]

    resolved = [await agents.resolve(**variant) for variant in variants]

    assert len(materialized) == len(variants)
    # One workspace's agent id is never handed to another: each was materialized in its own.
    assert [call["workspace_id"] for call in materialized] == [
        variant["workspace_id"] for variant in variants
    ]
    assert len(set(resolved[:4])) == 4


async def test_the_orchestrator_resolves_to_its_seed_bundle(
    agents: OmnigentStepAgents,
    agent_store: SqlAlchemyAgentStore,
    materialized: list[dict[str, Any]],
) -> None:
    agent_id = await agents.resolve(
        workspace_id=WORKSPACE,
        owner=OWNER,
        stance="orchestrator",
        workflow_slug=None,
        node_id=None,
        roster_index=None,
    )

    with workspace_scope(WORKSPACE):
        agent = agent_store.get(agent_id)
    assert agent is not None
    assert (agent.name, agent.created_by) == ("coral__orchestrator", OWNER)
    assert [call["stance"] for call in materialized] == [Stance.ORCHESTRATOR]


async def test_a_rejected_bundle_is_a_permanent_refusal_and_is_not_cached(
    agents: OmnigentStepAgents, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[str] = []

    def rejecting(*_args: Any, **kwargs: Any) -> MaterializedAgent:
        attempts.append(kwargs["stance"].value)
        raise StepBundleRejected("implementer bundle 'x' breaks: spawn is false")

    monkeypatch.setattr(step_agents_module, "materialize", rejecting)

    for _ in range(2):
        with pytest.raises(CoralSessionError) as refused:
            await agents.resolve(workspace_id=WORKSPACE, owner=OWNER, stance="implementer", **STEP)
        assert (refused.value.code, refused.value.retryable) == (
            "session.agent_not_supported",
            False,
        )
    assert attempts == ["implementer", "implementer"]


@pytest.mark.parametrize(
    "step",
    [
        {"workflow_slug": "Two Steps", "node_id": "implement", "roster_index": 0},
        {"workflow_slug": "two-steps", "node_id": "-implement", "roster_index": 0},
        {"workflow_slug": "two-steps", "node_id": "implement", "roster_index": -1},
        {"workflow_slug": None, "node_id": "implement", "roster_index": 0},
    ],
    ids=["workflow", "node", "index", "missing"],
)
async def test_a_step_reference_the_bundle_cannot_name_is_a_permanent_refusal(
    agents: OmnigentStepAgents, materialized: list[dict[str, Any]], step: dict[str, Any]
) -> None:
    with pytest.raises(CoralSessionError) as refused:
        await agents.resolve(workspace_id=WORKSPACE, owner=OWNER, stance="reviewer", **step)

    assert (refused.value.code, refused.value.retryable) == ("session.agent_not_supported", False)
    assert materialized == []


@pytest.mark.parametrize("stance", ["anchor", "planner"])
async def test_a_stance_with_no_step_bundle_is_a_permanent_refusal(
    agents: OmnigentStepAgents, materialized: list[dict[str, Any]], stance: str
) -> None:
    with pytest.raises(CoralSessionError) as refused:
        await agents.resolve(workspace_id=WORKSPACE, owner=OWNER, stance=stance, **STEP)

    assert refused.value.code == "session.agent_not_supported"
    assert materialized == []


async def test_an_ownerless_run_gets_no_agent_on_a_server_with_authentication(
    agent_store: SqlAlchemyAgentStore, tmp_path: Path, materialized: list[dict[str, Any]]
) -> None:
    agents = OmnigentStepAgents(
        agent_store, LocalArtifactStore(str(tmp_path / "artifacts")), auth_on=True
    )

    with pytest.raises(CoralSessionError) as refused:
        await agents.resolve(workspace_id=WORKSPACE, owner=None, stance="implementer", **STEP)

    assert (refused.value.code, refused.value.retryable) == ("session.invalid", False)
    # Refused before any bundle is built or stored.
    assert materialized == []


@pytest.mark.parametrize("lost", ["row", "blob"])
async def test_a_cached_agent_deleted_since_is_materialized_again(
    agents: OmnigentStepAgents,
    agent_store: SqlAlchemyAgentStore,
    tmp_path: Path,
    materialized: list[dict[str, Any]],
    lost: str,
) -> None:
    first = await agents.resolve(workspace_id=WORKSPACE, owner=OWNER, stance="implementer", **STEP)
    with workspace_scope(WORKSPACE):
        agent = agent_store.get(first)
        assert agent is not None
        if lost == "row":
            # A forced delete of the hidden agent, which the mutation guard allows.
            agent_store.delete(first)
        else:
            (tmp_path / "artifacts" / agent.bundle_location).unlink()

    again = await agents.resolve(workspace_id=WORKSPACE, owner=OWNER, stance="implementer", **STEP)

    # The same bundle rebuilds the same row, usable again.
    assert again == first
    assert len(materialized) == 2
    with workspace_scope(WORKSPACE):
        restored = agent_store.get(again)
    assert restored is not None and (tmp_path / "artifacts" / restored.bundle_location).is_file()


def _changed_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    """An upgrade that changes the step seed: the same step gets a new bundle digest."""
    build = step_agents_module.build_step_bundle_yaml

    def changed(*args: Any, **kwargs: Any) -> bytes:
        return build(*args, **kwargs) + b"description: the next release's seed\n"

    monkeypatch.setattr(step_agents_module, "build_step_bundle_yaml", changed)


async def test_a_retry_across_a_bundle_change_keeps_the_agent_its_session_runs(
    agent_store: SqlAlchemyAgentStore,
    tmp_path: Path,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    conversations = SqlAlchemyConversationStore(db_uri)

    def resolver() -> OmnigentStepAgents:
        return OmnigentStepAgents(agent_store, artifacts, conversation_store=conversations)

    first = await resolver().resolve(
        workspace_id=WORKSPACE, owner=OWNER, stance="implementer", **STEP
    )
    with workspace_scope(WORKSPACE):
        written = conversations.create_conversation(agent_id=first).id
    _changed_bundle(monkeypatch)
    upgraded = resolver()

    kept = await upgraded.resolve(
        workspace_id=WORKSPACE, owner=OWNER, stance="implementer", session_id=written, **STEP
    )
    fresh = await upgraded.resolve(
        workspace_id=WORKSPACE, owner=OWNER, stance="implementer", session_id="f" * 32, **STEP
    )

    assert kept == first
    # A create whose session does not exist yet gets the new release's bundle.
    assert fresh != first


@pytest.mark.parametrize("other", ["owner", "step"])
async def test_a_session_running_another_agent_does_not_choose_the_agent(
    agent_store: SqlAlchemyAgentStore, tmp_path: Path, db_uri: str, other: str
) -> None:
    conversations = SqlAlchemyConversationStore(db_uri)
    agents = OmnigentStepAgents(
        agent_store,
        LocalArtifactStore(str(tmp_path / "artifacts")),
        conversation_store=conversations,
    )
    owner, step = (
        ("bob@example.com", STEP) if other == "owner" else (OWNER, {**STEP, "roster_index": 1})
    )
    foreign = await agents.resolve(
        workspace_id=WORKSPACE, owner=owner, stance="implementer", **step
    )
    with workspace_scope(WORKSPACE):
        session_id = conversations.create_conversation(agent_id=foreign).id

    resolved = await agents.resolve(
        workspace_id=WORKSPACE, owner=OWNER, stance="implementer", session_id=session_id, **STEP
    )

    assert resolved != foreign
