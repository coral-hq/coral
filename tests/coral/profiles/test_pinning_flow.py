"""A run builds its steps from the profile revision it pinned; the next run uses the latest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from coral.db import WorkRow, coral_engine
from coral.db.migrate import ensure_coral_schema
from coral.omni.server import step_agents as step_agents_module
from coral.omni.server.step_agents import OmnigentStepAgents
from coral.profiles.spec import ProfileSpec
from coral.stores.profiles import revision_id
from coral.stores.protocols import CoralRun
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.artifact_store.local import LocalArtifactStore
from tests.coral.bridge._world import USER, WORKSPACE, World, run_spec, start
from tests.coral.workflow_builders import arrow, end, step, workflow_text
from tests.coral.workflow_builders import start as start_node

pytestmark = pytest.mark.usefixtures("coral_policy_registry")

PROFILE = "reviewer/strict-review"
WORKFLOW = workflow_text(
    [start_node(), step("review", [PROFILE]), end()],
    [arrow("a0", "start", "review"), arrow("a1", "review", "end")],
)


def _save(world: World, instructions: str, base: int | None) -> None:
    world.profiles.save_revision(
        workspace_id=WORKSPACE,
        profile_ref=PROFILE,
        owner=USER,
        spec=ProfileSpec(name="Strict review", instructions=instructions),
        base_revision_no=base,
    )


def _start(world: World, key: str) -> CoralRun:
    return start(world, WORKFLOW, spec=run_spec(start_key=key), start_key=key)


def _create_payload(db_uri: str, run: CoralRun) -> dict[str, Any]:
    """The run's queued step create, as the bridge mapped it."""
    with Session(coral_engine(db_uri)) as session:
        payloads = [
            json.loads(payload)
            for payload in session.scalars(select(WorkRow.payload).where(WorkRow.run_id == run.id))
        ]
    (create,) = (p for p in payloads if p.get("node_id") == "review")
    return create


async def test_a_running_run_keeps_its_revision_after_the_next_is_saved(
    db_uri: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_coral_schema(db_uri)
    world = World.sql(db_uri)
    agents = OmnigentStepAgents(
        SqlAlchemyAgentStore(db_uri),
        LocalArtifactStore(str(tmp_path / "artifacts")),
        profiles=world.profiles,
    )
    bundles: list[dict[str, Any]] = []
    real = step_agents_module.materialize

    def recording(*args: Any, **kwargs: Any) -> Any:
        bundles.append(yaml.safe_load(kwargs["config_yaml"]))
        return real(*args, **kwargs)

    monkeypatch.setattr(step_agents_module, "materialize", recording)

    async def step_agent(run: CoralRun) -> str:
        payload = _create_payload(db_uri, run)
        assert (payload["stance"], payload["profile"]) == ("reviewer", PROFILE)
        return await agents.resolve(
            workspace_id=WORKSPACE,
            owner=USER,
            stance=payload["stance"],
            workflow_slug=payload["workflow_slug"],
            node_id=payload["node_id"],
            roster_index=payload["roster_index"],
            run_id=run.id,
            profile=payload["profile"],
        )

    _save(world, "Check every line.", None)
    run_a = _start(world, "run-a")
    _save(world, "Skim it.", 1)

    agent_a = await step_agent(run_a)
    run_b = _start(world, "run-b")
    agent_b = await step_agent(run_b)

    bundle_a, bundle_b = bundles

    assert bundle_a["params"]["coral"]["generated"]["profile"]["revision_no"] == 1
    assert "Check every line." in bundle_a["instructions"]
    assert "Skim it." not in bundle_a["instructions"]
    assert bundle_b["params"]["coral"]["generated"]["profile"]["revision_no"] == 2
    assert "Skim it." in bundle_b["instructions"]
    # Run A's step resolved again after rev 2 exists is still rev 1's agent.
    assert agent_a != agent_b
    assert await step_agent(run_a) == agent_a
    assert world.profiles.used_by(workspace_id=WORKSPACE, profile_ref=PROFILE) == {
        revision_id(PROFILE, 1): 1,
        revision_id(PROFILE, 2): 1,
    }
