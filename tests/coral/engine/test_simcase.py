"""Saved Simulate cases: the case file format and comparing a case with its simulation."""

from __future__ import annotations

from pathlib import Path

import pytest

from coral.engine.simcase import (
    MAX_CASES,
    MAX_EXPECTED_ITEM_CHARS,
    MAX_EXPECTED_ITEMS,
    MAX_EXPECTED_SESSIONS,
    SimCase,
    SimExpect,
    check_case,
    load_cases,
)
from coral.engine.simulate import SimInput, SimScript
from coral.model.ir import CompiledGraph
from coral.model.loader import MAX_DOCUMENT_BYTES
from tests.coral.workflow_builders import compile_text

REVIEW_LOOP = Path(__file__).resolve().parents[3] / "tests/e2e/coral/fixtures/review_loop.yaml"
RUN_CAP = 100

CASES = """\
cases:
  - name: approved on the first pass
    script:
      inputs:
        - {node_id: implement, kind: done_when, values: [pass]}
        - {node_id: review, kind: label, values: [approved]}
        - {node_id: approve_change, kind: gate, values: [approve]}
    expect:
      outcome: completed
      steps: ["implement:done", "review:approved", "approve_change:approve"]
      gates_reached: [approve_change]
      limits_hit: []
      sessions: 3
  - name: a rejected change ends the run
    script:
      inputs:
        - {node_id: implement, kind: done_when, values: [pass]}
        - {node_id: review, kind: label, values: [approved]}
        - {node_id: approve_change, kind: gate, values: [reject]}
    expect:
      outcome: completed
"""


def _graph() -> CompiledGraph:
    text = REVIEW_LOOP.read_text().replace("{impl_token}", "").replace("{review_token}", "")
    return compile_text(text)[0]


def test_load_cases_reads_a_case_file() -> None:
    loaded = load_cases(CASES)
    assert [case.name for case in loaded.cases] == [
        "approved on the first pass",
        "a rejected change ends the run",
    ]
    first = loaded.cases[0]
    assert first.script.inputs[1] == SimInput(node_id="review", kind="label", values=("approved",))
    assert first.expect == SimExpect(
        outcome="completed",
        steps=("implement:done", "review:approved", "approve_change:approve"),
        gates_reached=("approve_change",),
        limits_hit=(),
        sessions=3,
    )
    assert loaded.cases[1].expect.steps is None


@pytest.mark.parametrize(
    "text",
    [
        "cases: &shared []\nmore: *shared\n",
        "- not a mapping\n",
        "",
        "cases: []\n",
        "cases:\n  - {name: x, script: {}, expect: {outcome: completed}, extra: 1}\n",
        "cases:\n  - {name: '', script: {}, expect: {outcome: completed}}\n",
        "cases:\n  - {name: x, script: {}, expect: {outcome: finished}}\n",
        "cases:\n  - {name: x, script: {}, expect: {outcome: completed}}\n"
        "  - {name: x, script: {}, expect: {outcome: paused}}\n",
        "cases:\n  - {name: x, name: y, script: {}, expect: {outcome: completed}}\n",
        "cases:\n  - {name: x, script: {inputs: [{node_id: a, kind: done_when, values: [maybe]}]},"
        " expect: {outcome: completed}}\n",
        "cases: [unclosed\n",
        "cases: []\n" + "#" * MAX_DOCUMENT_BYTES,
    ],
    ids=[
        "alias",
        "not_a_mapping",
        "empty",
        "no_cases",
        "unknown_field",
        "empty_name",
        "unknown_outcome",
        "duplicate_names",
        "duplicate_key",
        "bad_script",
        "invalid_yaml",
        "oversized",
    ],
)
def test_load_cases_refuses_a_bad_file(text: str) -> None:
    with pytest.raises(ValueError):
        load_cases(text)


ONE_CASE = "cases:\n  - {name: x, script: {}, expect: {outcome: needs_input}}\n"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (
            "cases:\n"
            "  - {name: x, script: {}, expect: &expect {outcome: needs_input}}\n"
            "  - {name: y, script: {}, expect: *expect}\n",
            "alias",
        ),
        ("cases:\n  - {name: x, script: {}, expect: {<<: {outcome: needs_input}}}\n", "merge_key"),
        (
            "cases:\n  - {name: x, script: {}, expect: {outcome: needs_input}, 1: y}\n",
            "non_string_key",
        ),
        (
            "cases:\n  - {name: x, name: x, script: {}, expect: {outcome: needs_input}}\n",
            "duplicate_key",
        ),
        (ONE_CASE + "deep: " + "[" * 40 + "]" * 40 + "\n", "too_deep"),
        (ONE_CASE + "#" * MAX_DOCUMENT_BYTES, "oversized"),
        (
            "cases:\n  - {name: x, script: {inputs: [{node_id: a, kind: gate,"
            " values: !!set {approve: null, reject: null}}]}, expect: {outcome: needs_input}}\n",
            "unsupported_type",
        ),
        (ONE_CASE.replace("name: x", "name: 2026-01-01"), "unsupported_type"),
        (ONE_CASE.replace("name: x", "name: x\ud800"), "invalid_text"),
        (
            ONE_CASE.replace("needs_input}", "needs_input, sessions: 0x" + "f" * 4000 + "}"),
            "invalid_yaml",
        ),
        (ONE_CASE.replace("needs_input}", "needs_input, sessions: 1:30}"), "unsupported_type"),
        (ONE_CASE.replace("needs_input}", "needs_input, sessions: 0x10}"), "unsupported_type"),
    ],
    ids=[
        "alias",
        "merge_key",
        "non_string_key",
        "duplicate_key",
        "too_deep",
        "oversized",
        "set",
        "timestamp",
        "lone_surrogate",
        "long_hex_sessions",
        "base_60_sessions",
        "hex_sessions",
    ],
)
def test_load_cases_refuses_what_the_workflow_loader_refuses(text: str, code: str) -> None:
    # The alias, merge, duplicate and oversized files would load without their guard.
    assert len(load_cases(ONE_CASE).cases) == 1
    with pytest.raises(ValueError, match=f"^{code}: "):
        load_cases(text)


def test_check_case_passes_a_matching_case() -> None:
    graph = _graph()
    for case in load_cases(CASES).cases:
        result = check_case(graph, case, max_activations=RUN_CAP)
        assert result.name == case.name
        assert result.passed, result.mismatches
        assert result.mismatches == ()


def test_check_case_lists_one_mismatch_per_differing_field() -> None:
    case = SimCase(
        name="wrong about everything",
        script=SimScript(
            inputs=(
                SimInput(node_id="implement", kind="done_when", values=("pass",)),
                SimInput(node_id="review", kind="label", values=("approved",)),
                SimInput(node_id="approve_change", kind="gate", values=("approve",)),
            )
        ),
        expect=SimExpect(
            outcome="paused",
            steps=("implement:done",),
            gates_reached=(),
            limits_hit=("a4",),
            sessions=4,
        ),
    )
    result = check_case(_graph(), case, max_activations=RUN_CAP)
    assert result.passed is False
    assert result.mismatches == (
        "outcome: expected paused, got completed",
        "steps: expected [implement:done], got "
        "[implement:done, review:approved, approve_change:approve]",
        "gates_reached: expected [], got [approve_change]",
        "limits_hit: expected [a4], got []",
        "sessions: expected 4, got 3",
    )


def test_check_case_compares_only_the_fields_it_sets() -> None:
    case = SimCase(
        name="outcome only", script=SimScript(), expect=SimExpect(outcome="needs_input")
    )
    result = check_case(_graph(), case, max_activations=RUN_CAP)
    assert result.passed


def _case_file(count: int) -> str:
    return "cases:\n" + "".join(
        f"  - {{name: c{index}, script: {{}}, expect: {{outcome: needs_input}}}}\n"
        for index in range(count)
    )


def test_a_case_file_holds_at_most_max_cases() -> None:
    assert len(load_cases(_case_file(MAX_CASES)).cases) == MAX_CASES
    with pytest.raises(ValueError, match="at most 64 items"):
        load_cases(_case_file(MAX_CASES + 1))


@pytest.mark.parametrize(
    "sessions",
    [-1, MAX_EXPECTED_SESSIONS + 1, 10**5000],
    ids=["negative", "over_the_bound", "past_the_digit_limit"],
)
def test_an_expected_session_count_is_bounded(sessions: int) -> None:
    with pytest.raises(ValueError):
        SimExpect(outcome="completed", sessions=sessions)


def test_a_case_file_refuses_a_negative_session_count() -> None:
    assert load_cases(ONE_CASE.replace("needs_input}", "needs_input, sessions: 0}")).cases
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        load_cases(ONE_CASE.replace("needs_input}", "needs_input, sessions: -1}"))


@pytest.mark.parametrize("field", ["steps", "gates_reached", "limits_hit"])
def test_an_expected_list_is_bounded_in_length_and_item_size(field: str) -> None:
    longest = "x" * MAX_EXPECTED_ITEM_CHARS
    assert SimExpect.model_validate(
        {"outcome": "completed", field: [longest] * MAX_EXPECTED_ITEMS}
    )
    for items in (
        ["a:done"] * (MAX_EXPECTED_ITEMS + 1),
        [longest + "x"],
        [""],
        ["a\u202e"],
    ):
        with pytest.raises(ValueError):
            SimExpect.model_validate({"outcome": "completed", field: items})
