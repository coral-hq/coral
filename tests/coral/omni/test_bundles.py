"""Step bundles become hygienic, content-addressed agent rows that repeat across runs."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from coral.omni.server.bundles import StepBundleRejected, check_hygiene, materialize, pack_bundle
from coral.profiles.bundle_spec import (
    STANCE_GUARDS,
    Stance,
    StepRef,
    build_seed_bundle_yaml,
    build_step_bundle_yaml,
)
from omnigent.inner.datamodel import TerminalEnvSpec
from omnigent.server.bundles import validate_agent_bundle
from omnigent.spec.types import (
    AgentSpec,
    BuiltinToolConfig,
    FunctionPolicySpec,
    FunctionRef,
    LocalToolInfo,
    MCPServerConfig,
    Phase,
    PhaseSelector,
    SkillSpec,
)
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from omnigent.tools.manager import ToolManager

OWNER = "alice@example.com"
REVIEW = StepRef(workflow_id="demo.flow", node_id="review", roster_index=0)
STEP_ROSTER = "coral.omni.policies.guards.step_roster"

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
            "deny_vendor_ask is an unconditional tool-call policy",
        ),
        (
            Stance.REVIEWER,
            lambda c: c["os_env"]["sandbox"].update(write_paths=["."]),
            "reviewer sandbox has no write_paths",
        ),
        (
            Stance.REVIEWER,
            lambda c: c["guardrails"]["policies"].pop("read_only_os"),
            "read_only_os is an unconditional tool-call policy",
        ),
        (
            Stance.IMPLEMENTER,
            lambda c: c["os_env"]["sandbox"].update(type="none"),
            "os_env has an OS sandbox",
        ),
        (
            Stance.IMPLEMENTER,
            lambda c: c["guardrails"]["policies"].pop("step_roster"),
            "step_roster is an unconditional tool-call policy",
        ),
        (
            Stance.REVIEWER,
            lambda c: c["guardrails"]["policies"].pop("step_roster"),
            "step_roster is an unconditional tool-call policy",
        ),
        (
            Stance.ANCHOR,
            lambda c: c["guardrails"]["policies"].pop("deny_all_tools"),
            "deny_all_tools is an unconditional tool-call policy",
        ),
        (
            Stance.ORCHESTRATOR,
            # The guard is checked by handler, not by policy name.
            lambda c: c["guardrails"]["policies"]["orchestrator_guard"]["function"].update(
                path=STEP_ROSTER
            ),
            "orchestrator_guard is an unconditional tool-call policy",
        ),
        (
            Stance.ORCHESTRATOR,
            lambda c: c.update(os_env={"type": "caller_process", "cwd": ".", "sandbox": {}}),
            "orchestrator has no os_env",
        ),
        (
            # The roster in place of the anchor's deny-all would let the anchor run tools.
            Stance.ANCHOR,
            lambda c: c["guardrails"]["policies"]["deny_all_tools"]["function"].update(
                path=STEP_ROSTER
            ),
            "deny_all_tools is an unconditional tool-call policy",
        ),
        (
            # A spec MCP server named "mcp" lists its tools as mcp__omnigent__*, the
            # name form the orchestrator allowlist accepts.
            Stance.ORCHESTRATOR,
            lambda c: c["tools"].update(mcp={"type": "mcp", "url": "http://localhost:9/mcp"}),
            "orchestrator has no mcp_servers",
        ),
        (
            # A label gate that never matches would switch the guard off.
            Stance.ORCHESTRATOR,
            lambda c: c["guardrails"]["policies"]["orchestrator_guard"].update(
                condition={"never": "set"}
            ),
            "orchestrator_guard is an unconditional tool-call policy",
        ),
        (
            Stance.IMPLEMENTER,
            lambda c: c["guardrails"]["policies"]["step_roster"]["function"].update(
                arguments={"x": 1}
            ),
            "step_roster is an unconditional tool-call policy",
        ),
        (
            Stance.IMPLEMENTER,
            lambda c: c["tools"].update(mcp={"type": "mcp", "url": "http://localhost:9/mcp"}),
            "no MCP server is named mcp",
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


def _parsed(stance: Stance) -> AgentSpec:
    return validate_agent_bundle(
        pack_bundle(build_step_bundle_yaml(REVIEW, stance, model=None, provider=None))
    )


Loosen = Callable[[FunctionPolicySpec], FunctionPolicySpec]


def _with_policy(spec: AgentSpec, name: str, change: Loosen) -> AgentSpec:
    """*spec* with *change* applied to its guardrail policy *name*."""
    guardrails = spec.guardrails
    assert guardrails is not None
    policies = [
        change(policy)
        if policy.name == name and isinstance(policy, FunctionPolicySpec)
        else policy
        for policy in guardrails.policies or []
    ]
    return dataclasses.replace(spec, guardrails=dataclasses.replace(guardrails, policies=policies))


def _with_arguments(policy: FunctionPolicySpec) -> FunctionPolicySpec:
    assert policy.function is not None
    return dataclasses.replace(policy, function=FunctionRef(policy.function.path, arguments={}))


# Each policy hygiene requires, as (stance, policy name).
_REQUIRED_POLICIES = [
    *STANCE_GUARDS.items(),
    (Stance.IMPLEMENTER, "deny_vendor_ask"),
    (Stance.REVIEWER, "read_only_os"),
]


@pytest.mark.parametrize(
    ("stance", "name"),
    _REQUIRED_POLICIES,
    ids=[f"{stance}-{name}" for stance, name in _REQUIRED_POLICIES],
)
@pytest.mark.parametrize(
    "loosen",
    [
        # The parser drops a function policy's YAML `on`; a spec built in code keeps it.
        lambda policy: dataclasses.replace(policy, on=[PhaseSelector(Phase.REQUEST)]),
        lambda policy: dataclasses.replace(
            policy, on=[PhaseSelector(Phase.TOOL_CALL, "sys_os_read")]
        ),
        lambda policy: dataclasses.replace(policy, condition={"never": "set"}),
        _with_arguments,
        lambda policy: dataclasses.replace(policy, config={"mode": "off"}),
    ],
    ids=["on_request", "tool_selector", "condition", "arguments", "config"],
)
def test_a_required_policy_counts_only_when_it_judges_every_tool_call(
    stance: Stance, name: str, loosen: Loosen
) -> None:
    spec = _parsed(stance)
    check_hygiene(spec, stance)
    # Covering every tool call beside other phases keeps it enforced.
    check_hygiene(
        _with_policy(
            spec,
            name,
            lambda policy: dataclasses.replace(
                policy, on=[PhaseSelector(Phase.REQUEST), PhaseSelector(Phase.TOOL_CALL)]
            ),
        ),
        stance,
    )

    with pytest.raises(StepBundleRejected) as refused:
        check_hygiene(_with_policy(spec, name, loosen), stance)
    assert str(refused.value).endswith(f"breaks: {name} is an unconditional tool-call policy")


@pytest.mark.parametrize("stance", list(Stance))
@pytest.mark.parametrize(
    ("loosen", "rule"),
    [
        (
            lambda spec: dataclasses.replace(
                spec,
                local_tools=[
                    LocalToolInfo(
                        name="coral_submit_handoff", path="tools/python/h.py", language="python"
                    )
                ],
            ),
            "no local tool has an engine tool's name",
        ),
        (
            lambda spec: dataclasses.replace(
                spec,
                local_tools=[
                    LocalToolInfo(
                        name="mcp__omnigent__coral_choose_arrow",
                        path="tools/python/c.py",
                        language="python",
                    )
                ],
            ),
            "no local tool has an engine tool's name",
        ),
        (
            # Its tools are listed as mcp__omnigent__<tool>, like Omnigent's own.
            lambda spec: dataclasses.replace(
                spec, mcp_servers=[MCPServerConfig(name="mcp", url="http://localhost:9/mcp")]
            ),
            "no MCP server is named mcp",
        ),
    ],
    ids=["local_tool", "prefixed_local_tool", "mcp_server_named_mcp"],
)
def test_a_spec_tool_cannot_take_an_engine_tools_name(
    stance: Stance, loosen: Callable[[AgentSpec], AgentSpec], rule: str
) -> None:
    with pytest.raises(StepBundleRejected, match=re.escape(rule)):
        check_hygiene(loosen(_parsed(stance)), stance)


def test_a_step_may_keep_a_local_tool_that_only_looks_like_an_engine_tool() -> None:
    spec = dataclasses.replace(
        _parsed(Stance.IMPLEMENTER),
        local_tools=[LocalToolInfo(name="coral_x", path="tools/python/x.py", language="python")],
    )

    check_hygiene(spec, Stance.IMPLEMENTER)


@pytest.mark.parametrize(
    ("loosen", "rule"),
    [
        (
            # A sandboxed os_env, so only the orchestrator rule breaks.
            lambda spec: dataclasses.replace(spec, os_env=_parsed(Stance.IMPLEMENTER).os_env),
            "orchestrator has no os_env",
        ),
        (
            lambda spec: dataclasses.replace(
                spec, mcp_servers=[MCPServerConfig(name="fs", url="http://localhost:9/mcp")]
            ),
            "orchestrator has no mcp_servers",
        ),
        (
            lambda spec: dataclasses.replace(
                spec,
                local_tools=[
                    LocalToolInfo(name="write", path="tools/python/write.py", language="python")
                ],
            ),
            "orchestrator has no local_tools",
        ),
        (
            lambda spec: dataclasses.replace(
                spec, skills=[SkillSpec(name="edit", description="Edits files.", content="Edit.")]
            ),
            "orchestrator has no bundled skills",
        ),
        (
            lambda spec: dataclasses.replace(
                spec, terminals={"shell": TerminalEnvSpec(command="bash")}
            ),
            "orchestrator has no terminals",
        ),
        (
            lambda spec: dataclasses.replace(
                spec,
                tools=dataclasses.replace(
                    spec.tools, builtins=[BuiltinToolConfig(name="upload_file")]
                ),
            ),
            "orchestrator has no tools.builtins",
        ),
    ],
    ids=["os_env", "mcp_servers", "local_tools", "skills", "terminals", "builtins"],
)
def test_orchestrator_bundle_with_edit_surfaces_is_refused(
    loosen: Callable[[AgentSpec], AgentSpec], rule: str
) -> None:
    orchestrator = _parsed(Stance.ORCHESTRATOR)
    check_hygiene(orchestrator, Stance.ORCHESTRATOR)

    with pytest.raises(StepBundleRejected) as refused:
        check_hygiene(loosen(orchestrator), Stance.ORCHESTRATOR)
    assert str(refused.value).endswith(f"breaks: {rule}")


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
