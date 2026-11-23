"""A step's stance becomes the run owner's materialized Coral bundle, once per bundle."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import create_engine

from coral.db import CoralBase
from coral.omni.protocols import CoralSessionError, StepAgentResolver
from coral.omni.server import step_agents as step_agents_module
from coral.omni.server.bundles import MaterializedAgent, StepBundleRejected
from coral.omni.server.step_agents import OmnigentStepAgents
from coral.profiles.bundle_spec import Stance
from coral.profiles.spec import ProfileSpec
from coral.stores.profiles import SqlProfileStore
from omnigent.db.db_models import current_workspace_id, workspace_scope
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

OWNER = "alice@example.com"
WORKSPACE = 5
STEP = {"workflow_slug": "two-steps", "node_id": "implement", "roster_index": 0}
ORCHESTRATOR_STEP: dict[str, Any] = {"workflow_slug": None, "node_id": None, "roster_index": None}

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
    """Each materialize call: its owner, stance, workspace, thread and bundle."""
    calls: list[dict[str, Any]] = []
    real = step_agents_module.materialize

    def recording(*args: Any, **kwargs: Any) -> MaterializedAgent:
        calls.append(
            {
                "owner": kwargs["owner"],
                "stance": kwargs["stance"],
                "workspace_id": current_workspace_id(),
                "thread": threading.current_thread(),
                "config": yaml.safe_load(kwargs["config_yaml"]),
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


async def test_an_ownerless_runs_step_is_one_agent_across_concurrent_and_restarted_resolvers(
    agent_store: SqlAlchemyAgentStore,
    tmp_path: Path,
    materialized: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A single-user server's run may have no owner; each process materializes the same row.

    That server reads no user as its local user, so the row is that user's.
    """
    stored_as = "local"
    _single_user(monkeypatch, True)
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


async def test_an_ownerless_run_gets_no_agent_outside_a_single_user_server(
    agent_store: SqlAlchemyAgentStore,
    tmp_path: Path,
    materialized: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _single_user(monkeypatch, False)
    agents = OmnigentStepAgents(agent_store, LocalArtifactStore(str(tmp_path / "artifacts")))

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
    """An upgrade that changes the seeds: a step or the orchestrator gets a new bundle digest."""
    for name in ("build_step_bundle_yaml", "build_seed_bundle_yaml"):
        build = getattr(step_agents_module, name)

        def changed(*args: Any, build: Any = build, **kwargs: Any) -> bytes:
            return build(*args, **kwargs) + b"description: the next release's seed\n"

        monkeypatch.setattr(step_agents_module, name, changed)


@pytest.mark.parametrize(
    ("stance", "step"),
    [("implementer", STEP), ("orchestrator", ORCHESTRATOR_STEP)],
    ids=["step", "orchestrator"],
)
async def test_a_retry_across_a_bundle_change_keeps_the_agent_its_session_runs(
    agent_store: SqlAlchemyAgentStore,
    tmp_path: Path,
    db_uri: str,
    monkeypatch: pytest.MonkeyPatch,
    stance: str,
    step: dict[str, Any],
) -> None:
    artifacts = LocalArtifactStore(str(tmp_path / "artifacts"))
    conversations = SqlAlchemyConversationStore(db_uri)

    def resolver() -> OmnigentStepAgents:
        return OmnigentStepAgents(agent_store, artifacts, conversation_store=conversations)

    first = await resolver().resolve(workspace_id=WORKSPACE, owner=OWNER, stance=stance, **step)
    with workspace_scope(WORKSPACE):
        written = conversations.create_conversation(agent_id=first).id
    _changed_bundle(monkeypatch)
    upgraded = resolver()

    kept = await upgraded.resolve(
        workspace_id=WORKSPACE, owner=OWNER, stance=stance, session_id=written, **step
    )
    fresh = await upgraded.resolve(
        workspace_id=WORKSPACE, owner=OWNER, stance=stance, session_id="f" * 32, **step
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


def test_only_package_directories_outside_the_environment_are_granted(tmp_path: Path) -> None:
    prefix = tmp_path / "venv"
    installed = prefix / "lib" / "site-packages" / "omnigent"
    checkout = tmp_path / "checkout"

    assert step_agents_module.checkout_read_paths([installed], prefix) == ()
    granted = step_agents_module.checkout_read_paths(
        [checkout / "omnigent", checkout / "coral", installed], prefix
    )
    # The package directories only, never the repository root that holds them.
    assert granted == (str(checkout / "coral"), str(checkout / "omnigent"))


async def test_an_editable_checkouts_step_bundles_grant_its_packages_to_the_sandbox(
    agents: OmnigentStepAgents, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sandbox otherwise hides a checkout's packages from its own helper processes."""
    grants = ("/checkout/coral", "/checkout/omnigent")
    monkeypatch.setattr(step_agents_module, "_checkout_read_paths", lambda: grants)
    configs: list[dict[str, Any]] = []
    real = step_agents_module.materialize

    def recording(*args: Any, **kwargs: Any) -> MaterializedAgent:
        configs.append(yaml.safe_load(kwargs["config_yaml"]))
        return real(*args, **kwargs)

    monkeypatch.setattr(step_agents_module, "materialize", recording)

    for stance in ("implementer", "reviewer"):
        await agents.resolve(workspace_id=WORKSPACE, owner=OWNER, stance=stance, **STEP)
    await agents.resolve(
        workspace_id=WORKSPACE, owner=OWNER, stance="orchestrator", **ORCHESTRATOR_STEP
    )

    implementer, reviewer, orchestrator = configs
    assert implementer["os_env"]["sandbox"] == {"read_paths": list(grants), "write_paths": ["."]}
    assert reviewer["os_env"]["sandbox"] == {"read_paths": list(grants), "write_paths": []}
    assert "read_paths" not in str(orchestrator)


PROFILE = "reviewer/strict-review"
RUN = "r" * 32
REVIEW = {"workflow_slug": "two-steps", "node_id": "review", "roster_index": 0}


@pytest.fixture
def profiles(tmp_path: Path) -> SqlProfileStore:
    engine = create_engine(f"sqlite:///{tmp_path / 'profiles.db'}")
    CoralBase.metadata.create_all(engine)
    return SqlProfileStore(engine)


def _save(profiles: SqlProfileStore, instructions: str, base: int | None) -> None:
    profiles.save_revision(
        workspace_id=WORKSPACE,
        profile_ref=PROFILE,
        owner=OWNER,
        spec=ProfileSpec(name="Strict review", instructions=instructions),
        base_revision_no=base,
    )


async def test_a_profile_step_builds_from_the_revision_its_run_pinned(
    agent_store: SqlAlchemyAgentStore,
    tmp_path: Path,
    profiles: SqlProfileStore,
    materialized: list[dict[str, Any]],
) -> None:
    agents = OmnigentStepAgents(
        agent_store, LocalArtifactStore(str(tmp_path / "artifacts")), profiles=profiles
    )
    _save(profiles, "Check every line.", None)
    profiles.pin_run(workspace_id=WORKSPACE, run_id=RUN, owner=OWNER, refs=[PROFILE])
    _save(profiles, "Skim it.", 1)

    pinned = await agents.resolve(
        workspace_id=WORKSPACE,
        owner=OWNER,
        stance="reviewer",
        run_id=RUN,
        profile=PROFILE,
        **REVIEW,
    )
    bare = await agents.resolve(
        workspace_id=WORKSPACE, owner=OWNER, stance="reviewer", run_id=RUN, **REVIEW
    )

    assert pinned != bare
    profiled, plain = (call["config"] for call in materialized)
    assert "Check every line." in profiled["instructions"]
    assert "Skim it." not in profiled["instructions"]
    assert profiled["params"]["coral"]["generated"]["profile"]["revision_no"] == 1
    assert "profile" not in plain["params"]["coral"]["generated"]
    assert materialized[0]["stance"] == Stance.REVIEWER


@pytest.mark.parametrize(
    ("with_store", "pinned", "run_id", "stance"),
    [
        (True, False, RUN, "reviewer"),
        (True, True, None, "reviewer"),
        (True, True, "o" * 32, "reviewer"),
        (False, True, RUN, "reviewer"),
        (True, True, RUN, "implementer"),
    ],
    ids=["unpinned_run", "no_run", "other_run", "no_store", "other_stance"],
)
async def test_a_profile_step_without_its_pin_is_a_permanent_refusal(
    agent_store: SqlAlchemyAgentStore,
    tmp_path: Path,
    profiles: SqlProfileStore,
    materialized: list[dict[str, Any]],
    with_store: bool,
    pinned: bool,
    run_id: str | None,
    stance: str,
) -> None:
    agents = OmnigentStepAgents(
        agent_store,
        LocalArtifactStore(str(tmp_path / "artifacts")),
        profiles=profiles if with_store else None,
    )
    _save(profiles, "Check every line.", None)
    if pinned:
        profiles.pin_run(workspace_id=WORKSPACE, run_id=RUN, owner=OWNER, refs=[PROFILE])

    with pytest.raises(CoralSessionError) as refused:
        await agents.resolve(
            workspace_id=WORKSPACE,
            owner=OWNER,
            stance=stance,
            run_id=run_id,
            profile=PROFILE,
            **REVIEW,
        )

    assert (refused.value.code, refused.value.retryable) == ("session.agent_not_supported", False)
    assert f"Profile missing: {PROFILE}" in refused.value.message
    assert materialized == []
