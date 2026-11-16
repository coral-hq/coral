"""Step bundles become hygienic, content-addressed agent rows that repeat across runs."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from coral.omni.server.bundles import StepBundleRejected, check_hygiene, materialize, pack_bundle
from coral.profiles.bundle_spec import (
    Stance,
    StepRef,
    build_seed_bundle_yaml,
    build_step_bundle_yaml,
)
from omnigent.server.bundles import validate_agent_bundle
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.tools.manager import ToolManager

OWNER = "alice@example.com"
REVIEW = StepRef(workflow_id="demo.flow", node_id="review", roster_index=0)

pytestmark = pytest.mark.usefixtures("coral_policy_registry")


@pytest.fixture
def agent_store(db_uri: str) -> SqlAlchemyAgentStore:
    return SqlAlchemyAgentStore(db_uri)


@pytest.fixture
def artifact_store(tmp_path: Path) -> LocalArtifactStore:
    return LocalArtifactStore(str(tmp_path / "artifacts"))


def _mutated(stance: Stance, change: Callable[[dict], None]) -> bytes:
    config = yaml.safe_load(build_step_bundle_yaml(REVIEW, stance, model=None, provider=None))
    change(config)
    return yaml.safe_dump(config, sort_keys=True).encode()


def test_two_runs_bind_the_same_row_and_a_lost_blob_comes_back(
    agent_store: SqlAlchemyAgentStore, artifact_store: LocalArtifactStore
) -> None:
    def run() -> object:
        config_yaml = build_step_bundle_yaml(REVIEW, Stance.REVIEWER, model="m", provider="p")
        return materialize(
            agent_store,
            artifact_store,
            owner=OWNER,
            config_yaml=config_yaml,
            stance=Stance.REVIEWER,
        )

    first = run()
    artifact_store.delete(first.bundle_location)
    second = run()

    assert second == first
    assert first.name == "coral__demo-flow__review__m0"
    assert artifact_store.exists(first.bundle_location)
    stored = agent_store.get(first.agent_id)
    assert stored is not None and stored.created_by == OWNER
    # Engine rows stay out of the owner's agent list.
    assert agent_store.list_user_agents(OWNER).data == []


def test_another_step_or_model_gets_another_row(
    agent_store: SqlAlchemyAgentStore, artifact_store: LocalArtifactStore
) -> None:
    def ids(ref: StepRef, model: str) -> str:
        config_yaml = build_step_bundle_yaml(ref, Stance.IMPLEMENTER, model=model, provider=None)
        return materialize(
            agent_store,
            artifact_store,
            owner=OWNER,
            config_yaml=config_yaml,
            stance=Stance.IMPLEMENTER,
        ).agent_id

    base = ids(REVIEW, "m")
    assert ids(REVIEW.model_copy(update={"roster_index": 1}), "m") != base
    assert ids(REVIEW, "other") != base


@pytest.mark.parametrize("stance", list(Stance))
def test_every_seed_and_step_bundle_passes_hygiene(
    stance: Stance, agent_store: SqlAlchemyAgentStore, artifact_store: LocalArtifactStore
) -> None:
    for config_yaml in (
        build_seed_bundle_yaml(stance),
        build_step_bundle_yaml(REVIEW, stance, model=None, provider="p"),
    ):
        materialize(
            agent_store, artifact_store, owner=OWNER, config_yaml=config_yaml, stance=stance
        )


@pytest.mark.parametrize(
    ("stance", "change", "rule"),
    [
        (
            Stance.IMPLEMENTER,
            # The parser refuses spawn without agent discovery, so a loosened seed would flip both.
            lambda c: c.update(spawn=True, tool_groups={"agent_discovery": True}),
            "spawn is false",
        ),
        (Stance.ANCHOR, lambda c: c.update(skills="all"), "skills is none"),
        (
            Stance.ANCHOR,
            lambda c: c["executor"]["config"].update(harness="codex"),
            "harness is claude-sdk",
        ),
        (Stance.ANCHOR, lambda c: c.update(timers=True), "timers is false"),
        (
            Stance.ANCHOR,
            lambda c: c["guardrails"]["policies"].pop("deny_vendor_ask"),
            "deny_vendor_ask is a policy",
        ),
        (
            Stance.REVIEWER,
            lambda c: c["os_env"]["sandbox"].update(write_paths=["."]),
            "reviewer sandbox has no write_paths",
        ),
        (
            Stance.REVIEWER,
            lambda c: c["guardrails"]["policies"].pop("read_only_os"),
            "reviewer has read_only_os",
        ),
        (
            Stance.IMPLEMENTER,
            lambda c: c["os_env"]["sandbox"].update(type="none"),
            "os_env has an OS sandbox",
        ),
    ],
)
def test_a_loosened_bundle_is_rejected_naming_the_rule(
    stance: Stance,
    change: Callable[[dict], None],
    rule: str,
    agent_store: SqlAlchemyAgentStore,
    artifact_store: LocalArtifactStore,
) -> None:
    with pytest.raises(StepBundleRejected, match=rule):
        materialize(
            agent_store,
            artifact_store,
            owner=OWNER,
            config_yaml=_mutated(stance, change),
            stance=stance,
        )
    assert agent_store.list_user_agents(OWNER).data == []


def test_declared_sub_agents_are_rejected(
    agent_store: SqlAlchemyAgentStore, artifact_store: LocalArtifactStore
) -> None:
    config_yaml = _mutated(Stance.ANCHOR, lambda c: c["tools"].update(agents=["helper"]))

    with pytest.raises(StepBundleRejected, match=re.escape("tools.agents")):
        materialize(
            agent_store, artifact_store, owner=OWNER, config_yaml=config_yaml, stance=Stance.ANCHOR
        )
    spec = validate_agent_bundle(
        pack_bundle(build_step_bundle_yaml(REVIEW, Stance.ANCHOR, model=None, provider=None))
    )
    spec.tools.agents = ["helper"]
    with pytest.raises(StepBundleRejected, match=re.escape("tools.agents is empty")):
        check_hygiene(spec, Stance.ANCHOR)


def test_an_unregistered_policy_handler_fails_validation(
    agent_store: SqlAlchemyAgentStore, artifact_store: LocalArtifactStore
) -> None:
    def add_handler(config: dict) -> None:
        config["guardrails"]["policies"]["shell"] = {
            "type": "function",
            "on": ["tool_call"],
            "function": {"path": "subprocess.Popen"},
        }

    with pytest.raises(StepBundleRejected, match=re.escape("subprocess.Popen")):
        materialize(
            agent_store,
            artifact_store,
            owner=OWNER,
            config_yaml=_mutated(Stance.ANCHOR, add_handler),
            stance=Stance.ANCHOR,
        )


_FORBIDDEN_TOOL_PREFIXES = ("browser_", "sys_timer_", "sys_scheduled_task_", "sys_agent_")
_SPAWN_TOOLS = {"sys_session_create", "sys_session_send", "sys_session_close", "sys_session_share"}


@pytest.mark.parametrize("stance", list(Stance))
def test_step_agents_get_no_spawn_timer_browser_or_schedule_tools(stance: Stance) -> None:
    spec = validate_agent_bundle(
        pack_bundle(build_step_bundle_yaml(REVIEW, stance, model=None, provider=None))
    )

    names = {
        schema["function"]["name"]
        for schema in ToolManager(spec, os_env_schema_only=True).get_tool_schemas()
    }

    assert not names & _SPAWN_TOOLS
    assert not [name for name in names if name.startswith(_FORBIDDEN_TOOL_PREFIXES)]
    assert ("sys_os_read" in names) is (spec.os_env is not None)
