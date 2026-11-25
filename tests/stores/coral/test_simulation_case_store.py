"""Saved Simulate cases on a workflow, on every DB lane."""

from __future__ import annotations

import secrets

import pytest
from sqlalchemy.orm import Session

from coral.db import coral_engine
from coral.engine.simcase import SimCase, SimExpect
from coral.engine.simulate import SimInput, SimScript
from coral.stores.workflows import (
    MAX_WORKFLOW_CASES,
    CaseExists,
    CaseLimitReached,
    CaseRun,
    SqlWorkflowDefinitionStore,
    WorkflowDefinition,
    WorkflowTooLargeError,
)
from tests.coral.workflow_builders import compile_text, fixture_text
from tests.stores.coral._faults import SimulatedCrash, crash_around, run_racing

WORKSPACE = 1
ALICE = "alice"
BOB = "bob"
PASSED = CaseRun(status="passed", mismatches=())
FAILED = CaseRun(status="failed", mismatches=("steps: expected [a:done], got [a:fail]",))


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000

    def __call__(self) -> int:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def store(coral_db_uri: str, clock: _Clock) -> SqlWorkflowDefinitionStore:
    return SqlWorkflowDefinitionStore(coral_engine(coral_db_uri), clock=clock)


def _case(name: str = "happy path", values: tuple[str, ...] = ("pass",)) -> SimCase:
    return SimCase(
        name=name,
        script=SimScript(inputs=(SimInput(node_id="work", kind="done_when", values=values),)),
        expect=SimExpect(outcome="completed", steps=("work:done",)),
    )


def _save(
    store: SqlWorkflowDefinitionStore,
    fixture: str = "minimal",
    *,
    owner: str | None = ALICE,
    workspace_id: int = WORKSPACE,
) -> WorkflowDefinition:
    yaml_text = fixture_text(fixture)
    graph, _ = compile_text(yaml_text)
    return store.save(
        workspace_id=workspace_id,
        workflow_key=graph.workflow_id,
        name=graph.name,
        yaml_text=yaml_text,
        compiled=graph,
        runnable=True,
        owner=owner,
    )


def _add(
    store: SqlWorkflowDefinitionStore,
    workflow: WorkflowDefinition,
    case: SimCase,
    *,
    result: CaseRun = PASSED,
    owner: str | None = ALICE,
    content_hash: str | None = None,
) -> object:
    return store.add_case(
        workspace_id=workflow.workspace_id,
        workflow_id=workflow.id,
        owner=owner,
        case=case,
        result=result,
        content_hash=workflow.content_hash if content_hash is None else content_hash,
    )


def _list(
    store: SqlWorkflowDefinitionStore, workflow: WorkflowDefinition, *, owner: str | None = ALICE
) -> list[tuple[str, str | None, tuple[str, ...], int | None]] | None:
    cases = store.list_cases(workspace_id=WORKSPACE, workflow_id=workflow.id, owner=owner)
    if cases is None:
        return None
    return [(c.case.name, c.last_result, c.mismatches, c.last_run_at) for c in cases]


def test_an_added_case_reads_back_with_its_result(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store)
    saved = _add(store, workflow, _case(), result=FAILED)
    cases = store.list_cases(workspace_id=WORKSPACE, workflow_id=workflow.id, owner=ALICE)
    assert cases == [saved]
    [case] = cases
    assert (case.workflow_id, case.case, case.last_result, case.mismatches) == (
        workflow.id,
        _case(),
        "failed",
        FAILED.mismatches,
    )
    assert (case.last_run_at, case.created_at) == (1_000, 1_000)


def test_cases_list_by_creation_time_then_name(
    store: SqlWorkflowDefinitionStore, clock: _Clock
) -> None:
    workflow = _save(store)
    _add(store, workflow, _case("b"))
    _add(store, workflow, _case("a"))
    clock.now += 1
    _add(store, workflow, _case("0"))
    listed = _list(store, workflow)
    assert listed is not None
    assert [name for name, *_ in listed] == ["a", "b", "0"]


def test_another_owners_workflow_hides_its_cases(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store)
    assert _add(store, workflow, _case()) is not None
    assert _list(store, workflow, owner=BOB) is None
    assert _add(store, workflow, _case("bob's"), owner=BOB) is None
    [case] = store.list_cases(workspace_id=WORKSPACE, workflow_id=workflow.id, owner=ALICE) or []
    assert not store.delete_case(
        workspace_id=WORKSPACE, workflow_id=workflow.id, case_id=case.id, owner=BOB
    )
    assert [name for name, *_ in _list(store, workflow) or []] == ["happy path"]


def test_another_workspace_or_unknown_workflow_has_no_cases(
    store: SqlWorkflowDefinitionStore,
) -> None:
    workflow = _save(store)
    _add(store, workflow, _case())
    assert store.list_cases(workspace_id=2, workflow_id=workflow.id, owner=ALICE) is None
    assert store.list_cases(workspace_id=WORKSPACE, workflow_id="0" * 32, owner=ALICE) is None
    assert (
        store.add_case(
            workspace_id=2,
            workflow_id=workflow.id,
            owner=ALICE,
            case=_case(),
            result=PASSED,
            content_hash=workflow.content_hash,
        )
        is None
    )


def test_a_legacy_workflow_shows_its_cases_to_everyone(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store, owner=None)
    assert _add(store, workflow, _case(), owner=BOB) is not None
    assert _list(store, workflow, owner=ALICE) == [("happy path", "passed", (), 1_000)]


def test_a_duplicate_name_is_refused_and_names_are_case_sensitive(
    store: SqlWorkflowDefinitionStore,
) -> None:
    workflow = _save(store)
    _add(store, workflow, _case())
    with pytest.raises(CaseExists):
        _add(store, workflow, _case())
    assert _add(store, workflow, _case("Happy path")) is not None
    other = _save(store, "loop")
    assert _add(store, other, _case()) is not None


def test_concurrent_adds_of_one_name_keep_one(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store)
    outcomes = run_racing(2, lambda _index: _add(store, workflow, _case()))
    assert sorted(type(outcome.error).__name__ for outcome in outcomes) == [
        "CaseExists",
        "NoneType",
    ]
    assert len(_list(store, workflow) or []) == 1


def test_the_case_after_the_cap_is_refused(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store)
    for index in range(MAX_WORKFLOW_CASES):
        _add(store, workflow, _case(f"case {index}"))
    with pytest.raises(CaseLimitReached):
        _add(store, workflow, _case("one more"))
    assert len(_list(store, workflow) or []) == MAX_WORKFLOW_CASES


def _huge_case() -> SimCase:
    inputs = tuple(
        SimInput(
            node_id=f"n{node}",
            kind="label",
            values=tuple(secrets.token_hex(125) for _ in range(100)),
        )
        for node in range(4)
    )
    return SimCase(
        name="huge",
        script=SimScript(inputs=inputs),
        expect=SimExpect(outcome="completed"),
    )


def test_an_oversized_script_is_refused(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store)
    with pytest.raises(WorkflowTooLargeError):
        _add(store, workflow, _huge_case())
    assert _list(store, workflow) == []


def test_a_deleted_case_frees_its_name_and_its_place_under_the_cap(
    store: SqlWorkflowDefinitionStore,
) -> None:
    workflow = _save(store)
    for index in range(MAX_WORKFLOW_CASES):
        _add(store, workflow, _case(f"case {index}"))
    with pytest.raises(CaseExists):
        _add(store, workflow, _case("case 0"))
    [first, *_] = (
        store.list_cases(workspace_id=WORKSPACE, workflow_id=workflow.id, owner=ALICE) or []
    )
    assert store.delete_case(
        workspace_id=WORKSPACE, workflow_id=workflow.id, case_id=first.id, owner=ALICE
    )
    assert _add(store, workflow, _case("case 0")) is not None
    assert len(_list(store, workflow) or []) == MAX_WORKFLOW_CASES


def test_a_case_added_against_a_stale_hash_is_not_run(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store)
    _add(store, workflow, _case(), result=FAILED, content_hash="0" * 64)
    assert _list(store, workflow) == [("happy path", None, (), None)]


def test_delete_removes_only_that_workflows_case(store: SqlWorkflowDefinitionStore) -> None:
    workflow, other = _save(store), _save(store, "loop")
    _add(store, workflow, _case())
    _add(store, other, _case())
    [case] = store.list_cases(workspace_id=WORKSPACE, workflow_id=workflow.id, owner=ALICE) or []
    assert not store.delete_case(
        workspace_id=WORKSPACE, workflow_id=other.id, case_id=case.id, owner=ALICE
    )
    assert store.delete_case(
        workspace_id=WORKSPACE, workflow_id=workflow.id, case_id=case.id, owner=ALICE
    )
    assert not store.delete_case(
        workspace_id=WORKSPACE, workflow_id=workflow.id, case_id=case.id, owner=ALICE
    )
    assert _list(store, workflow) == []
    assert len(_list(store, other) or []) == 1


def test_delete_in_another_workspace_or_unknown_workflow_deletes_nothing(
    store: SqlWorkflowDefinitionStore,
) -> None:
    workflow = _save(store)
    _add(store, workflow, _case())
    [case] = store.list_cases(workspace_id=WORKSPACE, workflow_id=workflow.id, owner=ALICE) or []
    assert not store.delete_case(
        workspace_id=2, workflow_id=workflow.id, case_id=case.id, owner=ALICE
    )
    assert not store.delete_case(
        workspace_id=WORKSPACE, workflow_id="0" * 32, case_id=case.id, owner=ALICE
    )
    assert not store.delete_case(
        workspace_id=WORKSPACE, workflow_id=workflow.id, case_id="0" * 32, owner=ALICE
    )
    assert _list(store, workflow) == [("happy path", "passed", (), 1_000)]


def test_anyone_may_delete_a_legacy_workflows_case(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store, owner=None)
    _add(store, workflow, _case(), owner=ALICE)
    [case] = store.list_cases(workspace_id=WORKSPACE, workflow_id=workflow.id, owner=BOB) or []
    assert store.delete_case(
        workspace_id=WORKSPACE, workflow_id=workflow.id, case_id=case.id, owner=BOB
    )
    assert _list(store, workflow, owner=ALICE) == []


def test_record_case_runs_in_another_workspace_or_unknown_workflow_changes_nothing(
    store: SqlWorkflowDefinitionStore, clock: _Clock
) -> None:
    workflow = _save(store)
    _add(store, workflow, _case())
    [case] = store.list_cases(workspace_id=WORKSPACE, workflow_id=workflow.id, owner=ALICE) or []
    clock.now = 2_000
    for workspace_id, workflow_id in ((2, workflow.id), (WORKSPACE, "0" * 32)):
        store.record_case_runs(
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            runs={case.id: FAILED},
            content_hash=workflow.content_hash,
        )
    assert _list(store, workflow) == [("happy path", "passed", (), 1_000)]


def test_record_case_runs_updates_the_named_cases_of_the_current_definition(
    store: SqlWorkflowDefinitionStore, clock: _Clock
) -> None:
    workflow, other = _save(store), _save(store, "loop")
    _add(store, workflow, _case("a"))
    _add(store, workflow, _case("b"))
    _add(store, other, _case("a"))
    cases = store.list_cases(workspace_id=WORKSPACE, workflow_id=workflow.id, owner=ALICE) or []
    [other_case] = (
        store.list_cases(workspace_id=WORKSPACE, workflow_id=other.id, owner=ALICE) or []
    )
    clock.now = 2_000
    store.record_case_runs(
        workspace_id=WORKSPACE,
        workflow_id=workflow.id,
        runs={cases[0].id: FAILED, other_case.id: FAILED},
        content_hash=workflow.content_hash,
    )
    assert _list(store, workflow) == [
        ("a", "failed", FAILED.mismatches, 2_000),
        ("b", "passed", (), 1_000),
    ]
    assert _list(store, other) == [("a", "passed", (), 1_000)]

    store.record_case_runs(
        workspace_id=WORKSPACE,
        workflow_id=workflow.id,
        runs={cases[1].id: FAILED},
        content_hash="0" * 64,
    )
    assert _list(store, workflow) == [
        ("a", "failed", FAILED.mismatches, 2_000),
        ("b", "passed", (), 1_000),
    ]


def _create(
    store: SqlWorkflowDefinitionStore, cases: list[tuple[SimCase, CaseRun]]
) -> WorkflowDefinition:
    yaml_text = fixture_text("minimal")
    graph, _ = compile_text(yaml_text)
    return store.create(
        workspace_id=WORKSPACE,
        workflow_key=graph.workflow_id,
        name=graph.name,
        yaml_text=yaml_text,
        compiled=graph,
        runnable=True,
        owner=ALICE,
        cases=cases,
    )


def test_create_inserts_the_cases_with_the_definition(store: SqlWorkflowDefinitionStore) -> None:
    created = _create(store, [(_case("b"), PASSED), (_case("a"), FAILED)])
    assert _list(store, created) == [
        ("a", "failed", FAILED.mismatches, 1_000),
        ("b", "passed", (), 1_000),
    ]


def test_create_that_fails_leaves_no_definition_and_no_cases(
    store: SqlWorkflowDefinitionStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(CaseLimitReached):
        _create(store, [(_case(f"c{index}"), PASSED) for index in range(MAX_WORKFLOW_CASES + 1)])
    with monkeypatch.context() as patch:
        crash_around(patch, Session, "add_all", when="before")
        with pytest.raises(SimulatedCrash):
            _create(store, [(_case(), PASSED)])
    assert store.list_definitions(workspace_id=WORKSPACE, owner=ALICE) == []
    created = _create(store, [(_case(), PASSED)])
    assert len(_list(store, created) or []) == 1


def test_create_takes_cases_up_to_the_cap(store: SqlWorkflowDefinitionStore) -> None:
    created = _create(store, [(_case(f"c{index}"), PASSED) for index in range(MAX_WORKFLOW_CASES)])
    assert len(_list(store, created) or []) == MAX_WORKFLOW_CASES


def test_create_with_an_oversized_case_leaves_no_definition(
    store: SqlWorkflowDefinitionStore,
) -> None:
    with pytest.raises(WorkflowTooLargeError):
        _create(store, [(_case(), PASSED), (_huge_case(), PASSED)])
    assert store.list_definitions(workspace_id=WORKSPACE, owner=ALICE) == []


def _resave(store: SqlWorkflowDefinitionStore, goal: str) -> WorkflowDefinition:
    yaml_text = fixture_text("minimal").replace("Do the thing", goal)
    graph, _ = compile_text(yaml_text)
    return store.save(
        workspace_id=WORKSPACE,
        workflow_key=graph.workflow_id,
        name=graph.name,
        yaml_text=yaml_text,
        compiled=graph,
        runnable=True,
        owner=ALICE,
    )


def test_a_changed_definition_keeps_its_cases_and_only_takes_runs_for_its_hash(
    store: SqlWorkflowDefinitionStore, clock: _Clock
) -> None:
    first = _save(store)
    _add(store, first, _case("kept"))
    second = _resave(store, "do another thing")
    assert (second.id, second.content_hash != first.content_hash) == (first.id, True)
    _add(store, second, _case("late"), content_hash=first.content_hash)
    cases = store.list_cases(workspace_id=WORKSPACE, workflow_id=first.id, owner=ALICE) or []
    assert [(c.case.name, c.last_result) for c in cases] == [("kept", "passed"), ("late", None)]
    clock.now = 2_000
    runs = {case.id: FAILED for case in cases} | {"0" * 32: PASSED}
    store.record_case_runs(
        workspace_id=WORKSPACE, workflow_id=first.id, runs=runs, content_hash=first.content_hash
    )
    assert _list(store, second) == [("kept", "passed", (), 1_000), ("late", None, (), None)]
    store.record_case_runs(
        workspace_id=WORKSPACE, workflow_id=first.id, runs=runs, content_hash=second.content_hash
    )
    assert _list(store, second) == [
        ("kept", "failed", FAILED.mismatches, 2_000),
        ("late", "failed", FAILED.mismatches, 2_000),
    ]


def test_an_error_run_reads_back_as_error(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store)
    error = CaseRun(status="error", mismatches=("workflow: not runnable",))
    _add(store, workflow, _case(), result=error)
    assert _list(store, workflow) == [("happy path", "error", error.mismatches, 1_000)]


def test_an_oversized_expectation_is_refused(store: SqlWorkflowDefinitionStore) -> None:
    workflow = _save(store)
    steps = tuple(f"n{index}:{secrets.token_hex(125)}" for index in range(400))
    case = SimCase(
        name="huge expect",
        script=SimScript(inputs=()),
        expect=SimExpect(outcome="completed", steps=steps),
    )
    with pytest.raises(WorkflowTooLargeError):
        _add(store, workflow, case)
    assert _list(store, workflow) == []
