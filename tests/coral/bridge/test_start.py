"""Starting a run: the YAML is compiled and checked here, the graph pinned, StartRun committed."""

from __future__ import annotations

import itertools
import json
import random
import string
from pathlib import Path

import pytest

from coral.bridge.config import (
    ENGINE_VERSION,
    LOG_VERSION,
    STATE_VERSION,
    freeze_engine_config,
)
from coral.bridge.service import EngineBridge
from coral.bridge.start import RunNotRunnable
from coral.db.enum_codecs import ActorKind, LogKind, RunStatus, SlotStatus, WorkKind
from coral.engine.types import EngineConfig
from coral.model.canonical import canonical_bytes, content_hash
from coral.model.ir import Analysis, CompiledGraph, LoopInfo, UnresolvedFact
from coral.model.loader import MAX_DOCUMENT_BYTES
from coral.stores.protocols import StartKeyConflict
from coral.stores.workflow_versions import pinned_version_id
from coral.validate.pipeline import CheckResult
from coral.validate.problems import ValidationReport
from tests.coral.bridge._world import (
    DEFINITION,
    IMPLEMENT,
    START_KEY,
    WORKSPACE,
    World,
    run_id_for,
    run_spec,
    start,
    start_without_engine,
)
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    end,
    fixture_text,
    step,
    workflow_text,
)
from tests.coral.workflow_builders import start as start_node

TWO_STEPS = fixture_text("two_steps")


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World.fake(tmp_path)


def _linear(*steps: dict[str, object]) -> str:
    """``start → steps… → end``."""
    nodes = [start_node(), *steps, end()]
    arrows = [
        arrow(f"a{index}", source["id"], target["id"])  # type: ignore[index]
        for index, (source, target) in enumerate(itertools.pairwise(nodes))
    ]
    return workflow_text(nodes, arrows)


def _region(*branches: dict[str, object], from_start: bool = False) -> str:
    """``start → split → branches (in parallel) → join → end``; or the start splits."""
    join = step("join", ["reviewer"])
    nodes = [start_node(), *branches, join, end()]
    arrows = [arrow("a9", "join", "end")]
    split = "start"
    if not from_start:
        split = "split"
        nodes.insert(1, step(split, ["reviewer"]))
        arrows.append(arrow("a0", "start", split))
    for index, branch in enumerate(branches):
        arrows.append(arrow(f"in{index}", split, str(branch["id"])))
        arrows.append(arrow(f"out{index}", str(branch["id"]), "join"))
    return workflow_text(nodes, arrows)


def _refusal(world: World, yaml_text: str = TWO_STEPS, **options: object) -> str:
    with pytest.raises(RunNotRunnable) as raised:
        start(world, yaml_text, **options)  # type: ignore[arg-type]
    return raised.value.code


def test_a_start_commits_start_run_with_the_actor_and_a_frozen_config(world: World) -> None:
    run = start(world, actor="user:alice")
    assert run.id == run_id_for()
    assert run.status == int(RunStatus.RUNNING)

    state, _version = world.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    graph = compile_text(TWO_STEPS)[0]
    pinned = world.versions.load(workspace_id=WORKSPACE, version_id=run.version_id)
    assert pinned is not None and pinned.graph == graph
    assert run.version_id == pinned_version_id(DEFINITION, graph)
    assert state.spec.engine_config == freeze_engine_config(
        max_activations=100, rejected_call_limit=3
    )
    assert state.spec.rejected_call_limit == 3

    (row,) = world.engine_log(run.id)
    assert (row.kind, row.actor_kind, row.actor_ref) == (
        int(LogKind.ENGINE),
        int(ActorKind.USER),
        "user:alice",
    )
    assert json.loads(row.body)["input"]["kind"] == "start_run"

    (slot,) = state.agent_slots
    assert (slot.scope_key, slot.status, slot.session_generation) == (
        IMPLEMENT,
        int(SlotStatus.PENDING),
        1,
    )
    anchor, create = world.work(run.id)
    assert json.loads(anchor.payload)["bridge_item"] == "anchor"
    assert (anchor.kind, anchor.available_at) == (int(WorkKind.EFFECT), 0)
    payload = json.loads(create.payload)
    assert (payload["effect_type"], payload["stance"], payload["engine_slot_id"]) == (
        "create_session",
        "implementer",
        IMPLEMENT,
    )
    assert (create.available_at, create.slot_generation) == (world.clock.epoch, 1)
    world.assert_fold_matches(run.id)


def test_a_repeated_start_changes_nothing(world: World) -> None:
    first = start(world)
    rows = world.work(first.id)
    world.clock.advance(30)
    again = start(world)
    assert again == first
    assert world.work(first.id) == rows
    assert len(world.engine_log(first.id)) == 1


def test_an_ownerless_start_needs_the_auth_less_switch(world: World) -> None:
    ownerless = run_spec(user=None)
    assert _refusal(world, spec=ownerless) == "run.owner_required"
    run = start(world, spec=ownerless, allow_ownerless=True, actor=None)
    assert run.id == run_id_for(None)
    assert world.engine_log(run.id)[0].actor_ref is None


@pytest.mark.parametrize(
    ("yaml_text", "code"),
    [
        ("nodes: [", "workflow.invalid"),
        # Not runnable: the step cannot reach an end.
        (
            workflow_text([start_node(), step("implement")], [arrow("a1", "start", "implement")]),
            "workflow.invalid",
        ),
        ("#" * (MAX_DOCUMENT_BYTES + 1), "workflow.too_large"),
        (_linear(step("plan", ["planner"])), "profile.unsupported"),
        (_linear(step("pair", ["implementer", "implementer"])), "graph.concurrent_writers"),
        (
            _region(step("left", ["implementer"]), step("right", ["implementer"])),
            "graph.concurrent_writers",
        ),
        # 33 slots live at once: one node outside regions, or a region's sum.
        (_linear(step("panel", ["reviewer"] * 33)), "graph.too_wide"),
        (
            _region(*(step(f"r{index}", ["reviewer"] * 11) for index in range(3))),
            "graph.too_wide",
        ),
        # The start's own commit would open all 33 slots.
        (
            _region(
                step("left", ["reviewer"] * 17), step("right", ["reviewer"] * 16), from_start=True
            ),
            "graph.too_wide",
        ),
    ],
    ids=[
        "load_error",
        "not_runnable",
        "oversized_yaml",
        "unsupported_profile",
        "two_writers_in_a_roster",
        "two_writers_in_a_region",
        "33_slots_in_a_node",
        "33_slots_in_a_region",
        "33_slots_opened_by_the_start",
    ],
)
def test_a_workflow_that_cannot_run_safely_is_refused(
    world: World, yaml_text: str, code: str
) -> None:
    assert _refusal(world, yaml_text) == code
    assert world.runs.get_run(run_id_for(), workspace_id=WORKSPACE) is None


def test_a_workflow_too_large_to_pin_is_refused_before_anything_is_written(
    world: World,
) -> None:
    noise = "".join(random.Random(149).choices(string.ascii_letters, k=40_000))
    yaml_text = _linear(step("implement", goal=noise))
    assert _refusal(world, yaml_text) == "workflow.too_large"
    assert world.runs.get_run(run_id_for(), workspace_id=WORKSPACE) is None


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"orchestrator_session_id": "s" * 32}, "run.field_invalid"),
        ({"max_activations": 0}, "run.field_invalid"),
        ({"max_activations": 1001}, "run.field_invalid"),
        ({"title": "t" * 257}, "run.field_invalid"),
        ({"request_preview": "r" * 513}, "run.field_invalid"),
        ({"workflow_id": "not-a-definition-id"}, "run.field_invalid"),
        ({"workspace_id": None}, "run.field_invalid"),
        ({"title": "a\x00b"}, "run.field_invalid"),
        ({"request_preview": "lone \ud800"}, "run.field_invalid"),
        ({"credential_ref": "c\x00"}, "run.field_invalid"),
        ({"trigger_kind": 99}, "run.field_invalid"),
        ({"execution_target": 0}, "run.field_invalid"),
        ({"auth_mode": 77}, "run.field_invalid"),
        ({"refresh_threshold_bp": 10_001}, "run.field_invalid"),
        ({"host_id": None}, "run.target_invalid"),
        ({"worktree_path": ""}, "run.target_invalid"),
        ({"repo_path": None}, "run.target_invalid"),
        ({"run_branch": "main"}, "run.target_invalid"),
    ],
    ids=lambda value: str(value)[:40],
)
def test_out_of_range_caller_fields_and_a_wrong_target_are_refused(
    world: World, fields: dict[str, object], code: str
) -> None:
    assert _refusal(world, spec=run_spec(**fields)) == code


@pytest.mark.parametrize(
    "start_key",
    ["", "k" * 257, "k\x00", "k\udfff"],
    ids=["empty", "257_chars", "nul", "surrogate"],
)
def test_a_start_key_outside_1_to_256_characters_of_text_is_refused(
    world: World, start_key: str
) -> None:
    # The key is refused before the run id (and so the branch) is derived from it.
    assert _refusal(world, spec=run_spec(), start_key=start_key) == "run.field_invalid"


def test_a_start_retried_after_its_engine_start_was_lost_completes_it(world: World) -> None:
    lost = start_without_engine(world, start_key=START_KEY)
    assert lost.status == int(RunStatus.STARTING)
    run = start(world)
    assert (run.id, run.status) == (lost.id, int(RunStatus.RUNNING))
    assert len(world.engine_log(run.id)) == 1
    world.assert_fold_matches(run.id)


@pytest.mark.parametrize("limit", [0, 11])
def test_a_rejected_call_limit_outside_one_to_ten_is_refused(world: World, limit: int) -> None:
    assert _refusal(world, rejected_call_limit=limit) == "run.field_invalid"


def test_the_branch_must_be_the_one_derived_from_this_run(world: World) -> None:
    other_branch = run_spec(run_branch=run_spec(start_key="other").run_branch)
    assert _refusal(world, spec=other_branch) == "run.target_invalid"


def test_refusals_come_in_table_order(world: World) -> None:
    # An unsupported profile and a missing owner: the profile is checked first.
    yaml_text = _linear(step("plan", ["planner"]))
    assert _refusal(world, yaml_text, spec=run_spec(user=None)) == "profile.unsupported"


def _checked_as(monkeypatch: pytest.MonkeyPatch, graph: CompiledGraph) -> None:
    """Hand ``graph`` to start as if the YAML had compiled to it and validated clean."""
    report = ValidationReport(problems=(), runnable=True)
    monkeypatch.setattr(
        "coral.bridge.start.check_text",
        lambda _text, _ctx=None: CheckResult(graph=graph, report=report),
    )


def test_unresolved_analysis_and_a_missing_start_are_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = compile_text(TWO_STEPS)[0]
    fact = UnresolvedFact(code="deadlock", message="the join can never fire")
    _checked_as(monkeypatch, graph.model_copy(update={"analysis": Analysis(unresolved=(fact,))}))
    assert _refusal(world) == "graph.unresolved"

    headless = graph.model_copy(
        update={"nodes": tuple(node for node in graph.nodes if node.kind != "start")}
    )
    rehashed = headless.model_copy(
        update={"content_hash": content_hash(canonical_bytes(headless))}
    )
    _checked_as(monkeypatch, rehashed)
    assert _refusal(world) == "graph.no_start"


def test_a_graph_whose_hash_is_not_its_own_is_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = compile_text(TWO_STEPS)[0]
    _checked_as(monkeypatch, graph.model_copy(update={"content_hash": "a" * 64}))
    assert _refusal(world) == "workflow.invalid"


def test_a_slot_whose_worst_case_effect_key_exceeds_512_characters_is_refused(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_id = "n" * 64
    yaml_text = _linear(step(long_id, ["implementer"]))
    graph = compile_text(yaml_text)[0]

    def nested(count: int) -> CompiledGraph:
        loops = tuple(
            LoopInfo(
                back_arrow_id=f"{index}".rjust(64, "b"),
                head=long_id,
                tail=long_id,
                body=(long_id,),
                limit=None,
                at_limit_arrow_id=None,
                entry_arrow_ids=(),
            )
            for index in range(count)
        )
        return graph.model_copy(update={"analysis": Analysis(loops=loops)})

    # Each enclosing loop adds a 71-character iteration part with six pass digits.
    _checked_as(monkeypatch, nested(4))
    start(world, yaml_text)
    _checked_as(monkeypatch, nested(6))
    assert _refusal(world, yaml_text, start_key="second") == "graph.ids_too_long"


def _reanalyzed(monkeypatch: pytest.MonkeyPatch) -> CompiledGraph:
    """Compile as a deploy with another analyzer would: the same content, another analysis."""
    graph = compile_text(TWO_STEPS)[0]
    changed = graph.model_copy(
        update={"analysis": graph.analysis.model_copy(update={"label_sets": ()})}
    )
    _checked_as(monkeypatch, changed)
    return changed


def test_an_analysis_change_pins_a_new_version_and_running_runs_keep_theirs(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = start(world)
    changed = _reanalyzed(monkeypatch)
    second = start(world, spec=run_spec(start_key="after-deploy"), start_key="after-deploy")
    assert second.version_id == pinned_version_id(DEFINITION, changed) != first.version_id
    # A new process loads each run's own row.
    fresh = EngineBridge(
        run_store=world.runs, queue_store=world.queue, versions=world.versions, clock=world.clock
    )
    original = compile_text(TWO_STEPS)[0]
    assert fresh.load(workspace_id=WORKSPACE, run_id=first.id).graph == original
    assert fresh.load(workspace_id=WORKSPACE, run_id=second.id).graph == changed


@pytest.mark.parametrize("deploy", ["engine_config_default", "analysis"])
def test_a_start_retried_after_a_deploy_returns_the_same_run(
    world: World, monkeypatch: pytest.MonkeyPatch, deploy: str
) -> None:
    first = start(world)
    rows = world.work(first.id)
    if deploy == "analysis":
        _reanalyzed(monkeypatch)
    else:
        config = EngineConfig(max_activations=100, nudge_limit=5).model_dump_json()
        monkeypatch.setattr("coral.bridge.start.freeze_engine_config", lambda **_limits: config)
    assert start(world) == first
    assert world.work(first.id) == rows
    assert len(world.engine_log(first.id)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"spec": run_spec(title="Another title")},
        {"yaml_text": _linear(step("implement", ["implementer"]))},
        {"rejected_call_limit": 4},
    ],
    ids=["title", "workflow", "rejected_call_limit"],
)
def test_a_retry_with_other_caller_fields_or_another_workflow_conflicts(
    world: World, change: dict[str, object]
) -> None:
    start(world)
    with pytest.raises(StartKeyConflict):
        start(world, **change)  # type: ignore[arg-type]


def test_the_format_versions_are_the_bridge_s(world: World) -> None:
    run = start(world, spec=run_spec(engine_version=9, state_version=9, log_version=9))
    assert (run.engine_version, run.state_version, run.log_version) == (
        ENGINE_VERSION,
        STATE_VERSION,
        LOG_VERSION,
    )


def _leaving_region(*, x_roster: list[str], branches: tuple[list[str], list[str]]) -> str:
    """``x → split → {b1, b2} → join``; ``b1`` may go back to ``x`` while ``b2`` runs."""
    nodes = [
        start_node(),
        step("x", x_roster),
        step("split", ["reviewer"]),
        step("b1", branches[0]),
        step("b2", branches[1]),
        step("join", ["reviewer"]),
        end(),
    ]
    arrows = [
        arrow("a0", "start", "x"),
        arrow("a1", "x", "split"),
        arrow("i1", "split", "b1"),
        arrow("i2", "split", "b2"),
        arrow("done", "b1", "join", label="done"),
        arrow("again", "b1", "x", label="again", back=True, limit=2, at_limit="done"),
        arrow("o2", "b2", "join"),
        arrow("a9", "join", "end"),
    ]
    return workflow_text(nodes, arrows)


@pytest.mark.parametrize(
    "yaml_text",
    [
        # Back to a writer while the other branch's writer still works.
        _leaving_region(x_roster=["implementer"], branches=(["reviewer"], ["implementer"])),
        # Back to 32 reviewers while 31 others are still live.
        _leaving_region(x_roster=["reviewer"] * 32, branches=(["reviewer"], ["reviewer"] * 31)),
    ],
    ids=["two_writers", "63_live_slots"],
)
def test_an_arrow_out_of_a_parallel_branch_is_refused(world: World, yaml_text: str) -> None:
    assert _refusal(world, yaml_text) == "graph.leaves_region"


def test_a_loop_around_a_whole_parallel_region_starts(world: World) -> None:
    nodes = [
        start_node(),
        step("x", ["implementer"]),
        step("split", ["reviewer"]),
        step("b1", ["reviewer"]),
        step("b2", ["reviewer"]),
        step("join", ["reviewer"]),
        end(),
    ]
    arrows = [
        arrow("a0", "start", "x"),
        arrow("a1", "x", "split"),
        arrow("i1", "split", "b1"),
        arrow("i2", "split", "b2"),
        arrow("o1", "b1", "join"),
        arrow("o2", "b2", "join"),
        arrow("again", "join", "x", label="again", back=True, limit=2, at_limit="done"),
        arrow("done", "join", "end", label="done"),
    ]
    assert start(world, workflow_text(nodes, arrows)).status == int(RunStatus.RUNNING)


def test_the_spec_fields_start_owns_are_replaced(world: World) -> None:
    spec = run_spec(rejected_call_limit=9, engine_config='{"max_activations": 1}')
    run = start(world, spec=spec, rejected_call_limit=4)
    state, _version = world.runs.load_run_state(run.id, workspace_id=WORKSPACE)
    assert state.spec.rejected_call_limit == 4
    assert state.spec.engine_config == freeze_engine_config(
        max_activations=100, rejected_call_limit=4
    )
    assert state.spec.version_id == run.version_id != spec.version_id
    snapshot = world.bridge.load(workspace_id=WORKSPACE, run_id=run.id)
    assert snapshot.state.rejected_call_limit == 4


def test_a_start_key_is_the_run_s_idempotency_key(world: World) -> None:
    first = start(world)
    second = start(world, spec=run_spec(start_key="start-2"), start_key="start-2")
    assert first.id != second.id
    assert first.id == run_id_for(start_key=START_KEY)
