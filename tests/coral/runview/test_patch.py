"""``apply_view_patch``: RFC 6902 add, remove and replace on a run view, addressed by position."""

from __future__ import annotations

import copy
from typing import Literal

import pytest
from pydantic import JsonValue, ValidationError

from coral.bridge.codec import entry_draft
from coral.engine import empty_state
from coral.engine.projection import RunView, project
from coral.engine.types import JsonPatch
from coral.runview.patch import ViewPatchError, apply_view_patch, stored_view_patch
from tests.coral.bridge._scripted_runs import (
    RUN_ID,
    Step,
    eventful_two_steps,
    exercise,
    fixture_graph,
    replay,
)
from tests.coral.workflow_builders import FIXTURES

Op = Literal["add", "remove", "replace"]
DOCUMENT: dict[str, JsonValue] = {
    "status": "running",
    "items": ["a", "b"],
    "nested": {"a/b": 1, "m~n": 2},
    "none": None,
}


def _op(op: Op, path: str, value: JsonValue = None) -> JsonPatch:
    return JsonPatch(op=op, path=path, value=value)


def _json(view: RunView) -> dict[str, JsonValue]:
    return view.model_dump(mode="json")


def _engine_steps(name: str) -> list[Step]:
    """Every logged entry of a fixture run to its end, or of the eventful two-step run."""
    if name == "eventful_two_steps":
        graph = fixture_graph("two_steps")
        return replay(graph, eventful_two_steps(graph).log)
    graph = fixture_graph(name)
    return replay(graph, exercise(graph).log)


RUNS = [*sorted(path.stem for path in FIXTURES.glob("*.yaml")), "eventful_two_steps"]


@pytest.mark.parametrize("run", RUNS)
def test_every_stored_engine_patch_turns_the_view_before_into_the_view_after(run: str) -> None:
    for step in _engine_steps(run):
        stored = entry_draft(step.entry, run_id=RUN_ID, before=step.before, actor=None).view_patch

        patched = apply_view_patch(_json(project(step.before)), stored_view_patch(stored))

        assert patched == _json(project(step.after))


def test_the_engine_runs_use_every_operation_and_removes_carry_a_null_value() -> None:
    operations = [
        operation for run in RUNS for step in _engine_steps(run) for operation in step.entry.patch
    ]

    assert {operation.op for operation in operations} == {"add", "remove", "replace"}
    assert all(item.value is None for item in operations if item.op == "remove")
    assert project(empty_state()) == RunView()


def test_replace_sets_an_existing_member() -> None:
    assert apply_view_patch(DOCUMENT, [_op("replace", "/status", "paused")])["status"] == "paused"


def test_add_creates_a_member_or_replaces_one_that_exists() -> None:
    patched = apply_view_patch(
        DOCUMENT, [_op("add", "/fresh", [1]), _op("add", "/status", "completed")]
    )

    assert (patched["fresh"], patched["status"]) == ([1], "completed")


@pytest.mark.parametrize(
    ("path", "items"),
    [
        ("/items/0", ["x", "a", "b"]),
        ("/items/1", ["a", "x", "b"]),
        ("/items/2", ["a", "b", "x"]),
        ("/items/-", ["a", "b", "x"]),
    ],
)
def test_add_inserts_into_an_array_at_its_index(path: str, items: list[str]) -> None:
    assert apply_view_patch(DOCUMENT, [_op("add", path, "x")])["items"] == items


def test_remove_drops_a_member_or_an_array_item_and_ignores_its_value() -> None:
    patched = apply_view_patch(DOCUMENT, [_op("remove", "/none"), _op("remove", "/items/0")])

    assert "none" not in patched
    assert patched["items"] == ["b"]


def test_escaped_tokens_name_members_holding_a_slash_or_a_tilde() -> None:
    patched = apply_view_patch(
        DOCUMENT, [_op("replace", "/nested/a~1b", 10), _op("replace", "/nested/m~0n", 20)]
    )

    assert patched["nested"] == {"a/b": 10, "m~n": 20}


def test_operations_apply_in_order_to_the_result_of_the_previous_one() -> None:
    patched = apply_view_patch(DOCUMENT, [_op("add", "/items/2", "c"), _op("remove", "/items/0")])

    assert patched["items"] == ["b", "c"]


def test_the_empty_path_replaces_the_whole_view() -> None:
    assert apply_view_patch(DOCUMENT, [_op("replace", "", {"status": None})]) == {"status": None}


def test_an_empty_patch_returns_an_equal_view() -> None:
    assert apply_view_patch(DOCUMENT, []) == DOCUMENT


def test_neither_the_view_nor_the_patch_values_are_changed() -> None:
    original = copy.deepcopy(DOCUMENT)
    operation = _op("add", "/extra", {"list": [1]})

    patched = apply_view_patch(
        DOCUMENT,
        [
            operation,
            _op("add", "/extra/list/-", 2),
            _op("replace", "/nested/a~1b", 3),
            _op("remove", "/items/0"),
            _op("add", "/items/-", "c"),
        ],
    )
    extra = patched["extra"]
    assert isinstance(extra, dict)
    assert extra["list"] == [1, 2]
    extra["list"] = []

    assert (patched["items"], patched["nested"]) == (["b", "c"], {"a/b": 3, "m~n": 2})
    assert original == DOCUMENT
    assert operation.value == {"list": [1]}


def test_a_failed_operation_leaves_the_view_unchanged() -> None:
    original = copy.deepcopy(DOCUMENT)

    with pytest.raises(ViewPatchError):
        apply_view_patch(
            DOCUMENT,
            [_op("remove", "/items/0"), _op("replace", "/nested/a~1b", 3), _op("remove", "/x")],
        )

    assert original == DOCUMENT


@pytest.mark.parametrize(
    ("op", "path"),
    [
        ("replace", "status"),
        ("replace", "/nested/a~2b"),
        ("replace", "/nested/a~"),
        ("replace", "/missing"),
        ("remove", "/missing"),
        ("add", "/missing/child"),
        ("replace", "/items/2"),
        ("remove", "/items/2"),
        ("add", "/items/3"),
        ("add", "/items/01"),
        ("replace", "/items/-1"),
        ("replace", "/items/x"),
        ("replace", "/items/-"),
        ("remove", "/items/-"),
        ("add", "/status/child"),
        ("add", "/none/child"),
        ("remove", ""),
        # More digits than ``int()`` converts by default.
        pytest.param("replace", "/items/" + "1" * 5000, id="replace-5000-digit-index"),
        pytest.param("add", "/items/" + "9" * 19, id="add-19-digit-index"),
    ],
)
def test_a_pointer_the_view_cannot_take_raises(op: Op, path: str) -> None:
    with pytest.raises(ViewPatchError):
        apply_view_patch(DOCUMENT, [_op(op, path, "x")])


def test_a_patch_that_leaves_no_object_raises() -> None:
    with pytest.raises(ViewPatchError):
        apply_view_patch(DOCUMENT, [_op("replace", "", ["not", "a", "view"])])


def test_a_view_patch_error_is_a_value_error() -> None:
    assert issubclass(ViewPatchError, ValueError)


def test_a_stored_patch_reads_back_as_its_operations() -> None:
    stored = '[{"op": "remove", "path": "/items/1", "value": null}]'

    assert stored_view_patch(None) == ()
    assert stored_view_patch("[]") == ()
    assert stored_view_patch(stored) == (_op("remove", "/items/1"),)


@pytest.mark.parametrize(
    "stored", ["{", '{"op": "add"}', '[{"op": "move", "path": "/a"}]', '[{"path": "/a"}]']
)
def test_a_stored_patch_that_is_not_a_patch_raises(stored: str) -> None:
    with pytest.raises(ValidationError):
        stored_view_patch(stored)
