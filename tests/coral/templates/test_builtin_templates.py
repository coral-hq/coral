"""The built-in workflow templates: registry, validation, saved cases and shape."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest
import yaml

import coral.templates as templates_module
from coral.bridge.config import DEFAULT_RUN_ACTIVATIONS
from coral.engine.simcase import SimCase, check_case
from coral.engine.simulate import (
    SIMULATED_BY,
    SIMULATED_HANDOFF,
    SIMULATION_RUN_ID,
    SimScript,
    simulate,
)
from coral.engine.types import (
    RULES,
    AnswerGate,
    EngineConfig,
    HandoffEvaluated,
    HandoffReceived,
    StartRun,
    activation_id,
    loop_limit_key,
)
from coral.model import Loaded, load
from coral.model.authoring import StepNode
from coral.model.ir import CompiledGraph
from coral.templates import (
    BUILTIN_TEMPLATES,
    BuiltinTemplate,
    TemplateError,
    builtin_template,
    builtin_templates,
    with_workflow_id,
)
from coral.validate.pipeline import check_text
from tests.coral.engine.drive import drive
from tests.coral.workflow_builders import arrow, compile_text, end, start, workflow_text

REPO = Path(__file__).resolve().parents[3]
REVIEW_LOOP_FIXTURE = REPO / "tests" / "e2e" / "coral" / "fixtures" / "review_loop.yaml"
TEMPLATE_ID = "implement-review-loop"
CASE_NAMES = (
    "approved on the first pass",
    "changes requested three times reaches the gate",
    "a rejected change ends the run",
)
# Copy, the done-when check and the attempts that count its failures may differ from the
# E2E fixture; the structure may not.
_COPY_AND_CHECKS = frozenset({"name", "goal", "prompt", "question", "attempts", "evidence"})


def _review_loop() -> BuiltinTemplate:
    template = builtin_template(TEMPLATE_ID)
    assert template is not None
    return template


def _loaded(text: str) -> Loaded:
    loaded = load(text)
    assert isinstance(loaded, Loaded), loaded
    return loaded


def _shape(graph: CompiledGraph) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes = [node.model_dump(exclude=set(_COPY_AND_CHECKS)) for node in graph.nodes]
    arrows = [item.model_dump(exclude={"limit"}) for item in graph.arrows]
    return nodes, arrows


def test_the_registry_lists_exactly_the_review_loop_template() -> None:
    assert BUILTIN_TEMPLATES == ("implement_review_loop",)
    templates = builtin_templates()
    assert [template.id for template in templates] == [TEMPLATE_ID]
    template = templates[0]
    assert template.name == "Implement with review loop"
    assert template.description.strip()
    assert template.graph.workflow_id == TEMPLATE_ID
    assert template.loaded.text == template.yaml_text
    assert builtin_template(TEMPLATE_ID) == template


def test_every_builtin_template_validates_with_no_problem() -> None:
    for template in builtin_templates():
        checked = check_text(template.yaml_text)
        assert checked.load_error is None, template.id
        assert checked.report is not None
        assert checked.runnable, template.id
        assert checked.report.problems == (), template.id
        assert checked.graph == template.graph
        assert not template.graph.analysis.unresolved


def test_the_review_loop_ships_the_three_saved_cases() -> None:
    cases = _review_loop().cases
    assert tuple(case.name for case in cases) == CASE_NAMES
    for case in cases:
        expect = case.expect
        # Every field is compared, so a case cannot pass on its outcome alone.
        assert None not in (expect.steps, expect.gates_reached, expect.limits_hit, expect.sessions)


def test_every_saved_case_of_every_builtin_template_passes() -> None:
    for template in builtin_templates():
        assert template.cases, template.id
        for case in template.cases:
            result = check_case(template.graph, case, max_activations=DEFAULT_RUN_ACTIVATIONS)
            assert result.passed, (template.id, case.name, result.mismatches)
            # A saved script holds only the values its path answers.
            simulation = simulate(
                template.graph, case.script, max_activations=DEFAULT_RUN_ACTIVATIONS
            )
            assert simulation.result.unconsumed == (), (template.id, case.name)


def _handoffs_by_hand(case: SimCase) -> tuple[list[HandoffReceived | HandoffEvaluated], str]:
    """The host's reports for a review-loop script: one implement and review pass per label."""
    values = {(item.node_id, item.kind): item.values for item in case.script.inputs}
    handoffs: list[HandoffReceived | HandoffEvaluated] = []
    for index, review_label in enumerate(values["review", "label"], start=1):
        for node_id, label in (("implement", None), ("review", review_label)):
            slot_id = f"{activation_id(node_id, (), (f'a4:{index}',))}:0"
            handoffs += [
                HandoffReceived(slot_id=slot_id, body=SIMULATED_HANDOFF, label=label),
                HandoffEvaluated(slot_id=slot_id, outcome="accepted"),
            ]
    (answer,) = values["approve_change", "gate"]
    return handoffs, answer


@pytest.mark.parametrize("case_name", CASE_NAMES)
def test_each_saved_case_is_what_the_engine_driven_by_hand_gives(case_name: str) -> None:
    template = _review_loop()
    graph = template.graph
    case = next(item for item in template.cases if item.name == case_name)
    config = EngineConfig(max_activations=DEFAULT_RUN_ACTIVATIONS)
    handoffs, answer = _handoffs_by_hand(case)
    started = StartRun(
        run_id=SIMULATION_RUN_ID,
        start_key=SIMULATION_RUN_ID,
        version_hash=graph.content_hash,
        rules=RULES,
    )
    driven = drive(graph, [started, *handoffs], config=config)
    (visit,) = [item for item in driven.state.gates if item.status == "open"]
    answered = AnswerGate(token=visit.token, label=answer, by=SIMULATED_BY)
    driven = drive(graph, [answered], config=config, after=driven)
    assert all(entry.rejection is None for entry in driven.log)
    simulation = simulate(graph, case.script, max_activations=DEFAULT_RUN_ACTIVATIONS)
    assert driven.log == simulation.log

    # The saved expectation, read from the hand-driven run instead of from Simulate's result.
    state = driven.state
    node_of = {item.id: item.node_id for item in state.activations}
    kinds = {node.id: node.kind for node in graph.nodes}
    answered_nodes = [item.node_id for item in state.activations if kinds[item.node_id] != "start"]
    results = [item.label or "done" for item in handoffs if isinstance(item, HandoffReceived)]
    receipts = {item.key for item in state.receipts}
    effects = [effect for entry in driven.log for effect in entry.effects]
    assert state.status == case.expect.outcome
    assert case.expect.steps == tuple(
        f"{node_id}:{result}"
        for node_id, result in zip(answered_nodes[:-1], [*results, answer], strict=True)
    )
    assert answered_nodes[-1] == "end"
    assert case.expect.gates_reached == tuple(node_of[item.activation_id] for item in state.gates)
    assert case.expect.limits_hit == tuple(
        counter.back_arrow_id
        for counter in state.loop_counters
        if loop_limit_key(counter.back_arrow_id, counter.item_path, counter.iteration_path)
        in receipts
    )
    # The run's anchor, then one session per step seat the run created.
    assert case.expect.sessions == 1 + sum(item.kind == "create_session" for item in effects)


def test_the_template_has_the_e2e_review_loops_shape() -> None:
    template = _review_loop()
    fixture = compile_text(REVIEW_LOOP_FIXTURE.read_text())[0]
    assert _shape(template.graph) == _shape(fixture)
    limits = {item.id: item.limit for item in template.graph.arrows}
    assert limits["a4"] == 3
    implement = next(node for node in template.loaded.workflow.nodes if node.id == "implement")
    assert isinstance(implement, StepNode)
    assert implement.attempts == 3
    # No active done-when: a run gates on handoffs until the project adds its commands.
    assert all(node.evidence is None for node in template.graph.nodes)


def test_the_commented_done_when_example_gives_the_implement_step_a_check() -> None:
    template = _review_loop()
    example = [
        line.removeprefix("#   ") for line in template.yaml_text.splitlines() if line[:4] == "#   "
    ]
    assert example[0] == "done_when:"
    # Uncommented under the implement step, as the header tells a user to do.
    snippet = "".join(f"    {line}\n" for line in example)
    text = template.yaml_text.replace("    attempts: 3\n", f"    attempts: 3\n{snippet}", 1)
    checked = check_text(text)
    assert checked.runnable
    assert checked.graph is not None
    asked = simulate(checked.graph, SimScript(), max_activations=DEFAULT_RUN_ACTIVATIONS)
    assert asked.result.needs_input is not None
    assert (asked.result.needs_input.node_id, asked.result.needs_input.kind) == (
        "implement",
        "done_when",
    )


def test_the_implement_steps_attempts_keep_their_done_when_comment() -> None:
    lines = _review_loop().yaml_text.splitlines()
    comment = lines[lines.index("    attempts: 3") - 1].strip()
    assert comment.startswith("#")
    assert "done-when" in comment or "done_when" in comment


def test_every_builtin_templates_id_is_a_one_line_plain_scalar() -> None:
    for template in builtin_templates():
        root = yaml.compose(template.yaml_text)
        assert isinstance(root, yaml.MappingNode)
        [value] = [value for key, value in root.value if key.value == "id"]
        assert isinstance(value, yaml.ScalarNode)
        assert value.style is None, template.id
        assert value.start_mark.line == value.end_mark.line, template.id
        assert value.value == template.id


def test_with_workflow_id_changes_only_the_id_and_keeps_every_comment() -> None:
    template = _review_loop()
    text = with_workflow_id(template, "implement-review-loop-2")
    assert _loaded(text).workflow.id == "implement-review-loop-2"
    before = template.yaml_text.splitlines(keepends=True)
    after = text.splitlines(keepends=True)
    assert len(after) == len(before)
    changed = [
        index for index, (old, new) in enumerate(zip(before, after, strict=True)) if old != new
    ]
    assert changed == [before.index(f"id: {TEMPLATE_ID}\n")]
    assert after[changed[0]] == "id: implement-review-loop-2\n"
    comments = [line for line in before if line.lstrip().startswith("#")]
    assert comments
    assert [line for line in after if line.lstrip().startswith("#")] == comments
    checked = check_text(text)
    assert checked.runnable
    assert checked.graph is not None
    assert checked.graph.workflow_id == "implement-review-loop-2"


def test_with_workflow_id_replaces_only_the_id_value_where_its_text_repeats() -> None:
    template = _review_loop()
    written = f"# {TEMPLATE_ID} is this template's id.\nid: {TEMPLATE_ID}  # {TEMPLATE_ID}\n"
    text = template.yaml_text.replace(f"id: {TEMPLATE_ID}\n", written, 1)
    repeated = dataclasses.replace(template, yaml_text=text, loaded=_loaded(text))
    assert with_workflow_id(repeated, "implement-review-loop-2") == text.replace(
        f"id: {TEMPLATE_ID}  #", "id: implement-review-loop-2  #", 1
    )


@pytest.mark.parametrize("workflow_id", ["", "Bad-Id", "templates", "a b", "loop\nnodes: []"])
def test_with_workflow_id_refuses_an_invalid_workflow_id(workflow_id: str) -> None:
    with pytest.raises(ValueError):
        with_workflow_id(_review_loop(), workflow_id)


@pytest.mark.parametrize(
    "written",
    [f'id: "{TEMPLATE_ID}"\n', f"id: '{TEMPLATE_ID}'\n", f"id: >-\n  {TEMPLATE_ID}\n"],
)
def test_with_workflow_id_refuses_an_id_that_is_not_a_one_line_plain_scalar(written: str) -> None:
    template = _review_loop()
    text = template.yaml_text.replace(f"id: {TEMPLATE_ID}\n", written, 1)
    assert text != template.yaml_text
    quoted = dataclasses.replace(template, yaml_text=text, loaded=_loaded(text))
    with pytest.raises(TemplateError):
        with_workflow_id(quoted, "implement-review-loop-2")


@pytest.mark.parametrize(
    "template_id",
    [
        "nope",
        "",
        "review-loop",
        "pr_review_loop",
        "pr-review-loop",
        "coral.pr_review_loop",
        "single_agent_steps",
        "implement_review_loop",
        "implement_review_loop.sim",
        "implement-review-loop.yaml",
        "..",
        "../implement_review_loop",
        "./implement-review-loop",
        "IMPLEMENT-REVIEW-LOOP",
        " implement-review-loop",
    ],
)
def test_only_a_registered_workflow_id_finds_a_template(template_id: str) -> None:
    assert builtin_template(template_id) is None


_MINIMAL = workflow_text([start(), end()], [arrow("a1", "start", "end")], description="Ends.")
_MINIMAL_CASES = "cases:\n  - name: ends\n    script: {}\n    expect: {outcome: completed}\n"
_UNWIRED = workflow_text([start(), end()], [], description="Never ends.")
_UNDESCRIBED = workflow_text([start(), end()], [arrow("a1", "start", "end")])
_BLANK = workflow_text([start(), end()], [arrow("a1", "start", "end")], description="  ")


@pytest.mark.parametrize(
    ("files", "stems", "message"),
    [
        pytest.param({"t.yaml": "id: [\n", "t.sim.yaml": _MINIMAL_CASES}, ("t",), "does not load"),
        pytest.param({"t.yaml": _UNWIRED, "t.sim.yaml": _MINIMAL_CASES}, ("t",), "validate"),
        pytest.param(
            {"t.yaml": _UNDESCRIBED, "t.sim.yaml": _MINIMAL_CASES}, ("t",), "description"
        ),
        pytest.param({"t.yaml": _BLANK, "t.sim.yaml": _MINIMAL_CASES}, ("t",), "description"),
        pytest.param({"t.yaml": _MINIMAL}, ("t",), "t.sim.yaml"),
        pytest.param({"t.sim.yaml": _MINIMAL_CASES}, ("t",), "t.yaml"),
        pytest.param({"t.yaml": _MINIMAL, "t.sim.yaml": "cases: []\n"}, ("t",), "saved cases"),
        pytest.param(
            {"t.yaml": _MINIMAL, "t.sim.yaml": "x: &a []\ncases: *a\n"}, ("t",), "saved cases"
        ),
        pytest.param(
            {
                "t.yaml": _MINIMAL,
                "t.sim.yaml": _MINIMAL_CASES,
                "u.yaml": _MINIMAL,
                "u.sim.yaml": _MINIMAL_CASES,
            },
            ("t", "u"),
            "unique",
        ),
    ],
    ids=[
        "does_not_load",
        "validation_error",
        "no_description",
        "blank_description",
        "no_cases_file",
        "no_template_file",
        "no_cases",
        "unsafe_cases_yaml",
        "duplicate_ids",
    ],
)
def test_a_broken_packaged_template_is_a_template_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    files: dict[str, str],
    stems: tuple[str, ...],
    message: str,
) -> None:
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    monkeypatch.setattr(templates_module, "_package_files", lambda: tmp_path)
    monkeypatch.setattr(templates_module, "BUILTIN_TEMPLATES", stems)
    with pytest.raises(TemplateError, match=re.escape(message)):
        builtin_templates()


def test_a_template_read_from_another_package_root_loads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The positive control for the broken-template cases: their files are what is read."""
    (tmp_path / "t.yaml").write_text(_MINIMAL)
    (tmp_path / "t.sim.yaml").write_text(_MINIMAL_CASES)
    monkeypatch.setattr(templates_module, "_package_files", lambda: tmp_path)
    monkeypatch.setattr(templates_module, "BUILTIN_TEMPLATES", ("t",))
    [template] = builtin_templates()
    assert (template.id, template.description) == ("demo", "Ends.")
    assert [case.name for case in template.cases] == ["ends"]
    assert builtin_template("demo") == template
    assert builtin_template(TEMPLATE_ID) is None
