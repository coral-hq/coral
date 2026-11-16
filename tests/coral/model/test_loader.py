"""Loader: YAML 1.2 bools, compose guards, source map and schema errors."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from coral.model import LoadError, load
from coral.model.authoring import StepNode
from coral.model.loader import MAX_DEPTH, MAX_DOCUMENT_BYTES, _CoralYamlLoader
from tests.coral.workflow_builders import fixture_text, load_ok

_HEADER = "id: demo\nname: Demo\n"


def _expect_error(text: str) -> LoadError:
    result = load(text)
    assert isinstance(result, LoadError), result
    return result


def test_minimal_fixture_loads() -> None:
    loaded = load_ok(fixture_text("minimal"))
    assert loaded.workflow.id == "demo"
    assert [node.id for node in loaded.workflow.nodes] == ["start", "work", "end"]
    assert loaded.workflow.arrows[0].from_node == "start"


@pytest.mark.parametrize("word", ["on", "off", "yes", "no", "On", "YES", "No"])
def test_yaml_11_bool_words_stay_strings(word: str) -> None:
    text = f"{_HEADER}description: {word}\nnodes: []\narrows: []\n"
    assert load_ok(text).workflow.description == word


@pytest.mark.parametrize(
    ("literal", "expected"), [("true", True), ("false", False), ("True", True)]
)
def test_true_false_are_bools(literal: str, expected: bool) -> None:
    text = (
        f"{_HEADER}nodes:\n  - {{id: gate1, kind: gate, outcomes: [approve]}}\n"
        f"arrows:\n  - {{id: a1, from: gate1, to: gate1, back: {literal}}}\n"
    )
    assert load_ok(text).workflow.arrows[0].back is expected


def test_bool_words_are_usable_as_keys_and_values() -> None:
    document = yaml.compose("on: yes\n", Loader=_CoralYamlLoader)
    assert _CoralYamlLoader("").construct_object(document, deep=True) == {"on": "yes"}


def test_safe_loader_resolvers_are_not_mutated() -> None:
    assert yaml.safe_load("on: yes") == {True: True}


@pytest.mark.parametrize(
    ("text", "code", "path"),
    [
        (f"{_HEADER}name: Again\nnodes: []\narrows: []\n", "duplicate_key", "name"),
        (
            f"{_HEADER}nodes:\n  - {{id: a, kind: start, id: b}}\narrows: []\n",
            "duplicate_key",
            "nodes[0].id",
        ),
        (f"{_HEADER}nodes: &n []\narrows: *n\n", "alias", ""),
        (f"{_HEADER}<<: {{description: x}}\nnodes: []\narrows: []\n", "merge_key", ""),
        (f"{_HEADER}1: one\nnodes: []\narrows: []\n", "non_string_key", ""),
        (f"{_HEADER}true: one\nnodes: []\narrows: []\n", "non_string_key", ""),
        (f"{_HEADER}? [a, b]\n: one\nnodes: []\narrows: []\n", "non_string_key", ""),
        ("- just\n- a list\n", "invalid_document", ""),
        ("", "invalid_document", ""),
        ("id: [unclosed\n", "invalid_yaml", ""),
        ("a: 1\n---\nb: 2\n", "invalid_yaml", ""),
        ("id: !!python/object:os.system x\n", "invalid_yaml", ""),
    ],
)
def test_structural_errors_have_code_and_path(text: str, code: str, path: str) -> None:
    error = _expect_error(text)
    assert error.code == code
    assert error.yaml_path == path


def test_duplicate_key_range_points_at_second_occurrence() -> None:
    error = _expect_error(f"{_HEADER}nodes: []\narrows: []\nname: Again\n")
    assert error.range is not None
    assert error.range.start_line == 5


def test_alias_is_rejected_even_when_shared_value_is_harmless() -> None:
    error = _expect_error(f"{_HEADER}description: &d hello\nnodes: []\narrows: []\nx: *d\n")
    assert error.code == "alias"
    assert error.range is not None and error.range.start_line == 6


def test_oversized_document_is_rejected() -> None:
    error = _expect_error(f"{_HEADER}description: {'x' * MAX_DOCUMENT_BYTES}\n")
    assert error.code == "oversized"


def test_deeply_nested_document_is_rejected() -> None:
    nested = "[" * (MAX_DEPTH + 1) + "]" * (MAX_DEPTH + 1)
    assert _expect_error(f"{_HEADER}description: {nested}\n").code == "too_deep"


def test_nesting_beyond_recursion_limit_does_not_crash() -> None:
    nested = "[" * 5000 + "]" * 5000
    assert _expect_error(f"{_HEADER}description: {nested}\n").code == "too_deep"


def test_schema_errors_use_yaml_paths_and_ranges() -> None:
    text = (
        f"{_HEADER}nodes:\n"
        "  - id: start\n    kind: start\n"
        "  - id: work\n    kind: step\n    roster: [a]\n"
        "arrows: []\n"
    )
    error = _expect_error(text)
    assert error.code == "invalid_document"
    assert error.yaml_path == "nodes[1].goal"
    assert error.range is not None and error.range.start_line == 6


def test_unknown_key_is_rejected_at_its_path() -> None:
    error = _expect_error(
        f"{_HEADER}nodes:\n  - {{id: s, kind: start, colour: red}}\narrows: []\n"
    )
    assert error.yaml_path == "nodes[0].colour"


def test_unknown_node_kind_is_rejected() -> None:
    error = _expect_error(f"{_HEADER}nodes:\n  - {{id: g, kind: group}}\narrows: []\n")
    assert error.code == "invalid_document"
    assert error.yaml_path.startswith("nodes[0]")


def test_strict_types_reject_coerced_values() -> None:
    text = (
        f"{_HEADER}nodes:\n  - {{id: w, kind: step, goal: x, roster: [a], attempts: '3'}}\n"
        "arrows: []\n"
    )
    assert _expect_error(text).yaml_path == "nodes[0].attempts"


def test_multiple_schema_issues_are_all_reported() -> None:
    error = _expect_error("id: Bad Id\nname: ''\nnodes: []\narrows: []\n")
    assert {issue.yaml_path for issue in error.issues} == {"id", "name"}
    assert "more" in error.message


def test_arrow_requires_from_alias() -> None:
    text = f"{_HEADER}nodes: []\narrows:\n  - {{id: a1, from_node: x, to: y}}\n"
    paths = {issue.yaml_path for issue in _expect_error(text).issues}
    assert "arrows[0].from_node" in paths


def test_source_map_covers_nested_values() -> None:
    loaded = load_ok(fixture_text("minimal"))
    ranges = loaded.source_map
    assert ranges.lookup("nodes[1].goal") is not None
    assert ranges.lookup("nodes[1].goal").start_line == 9  # type: ignore[union-attr]
    # Unknown paths fall back to the nearest ancestor.
    assert ranges.lookup("nodes[1].missing") == ranges.lookup("nodes[1]")
    assert ranges.lookup("") is not None


def test_loaded_workflow_step_fields() -> None:
    workflow = load_ok(fixture_text("minimal")).workflow
    work = workflow.nodes[1]
    assert isinstance(work, StepNode)
    assert work.roster == ["implementer"]


def test_authoring_validation_error_type_is_pydantic() -> None:
    from coral.model import Workflow

    with pytest.raises(ValidationError):
        Workflow.model_validate({"id": "runs", "name": "x", "nodes": [], "arrows": []})
