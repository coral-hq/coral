"""
Workflow validate/simulate/save/get/list router. Unmounted: the Coral server plugin registers it.

Every route needs a signed-in caller. A caller saves, reads and lists their own
definitions in the request's workspace, plus legacy ones saved before definitions had
owners; saving a key another user holds is refused. A simulation reads and stores
nothing: it validates and dry-runs the text it is sent on a small pool of its own,
at most so many at once for one user and in all.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from coral.alerts.types import normalize_owner
from coral.api.errors import CoralApiError, CoralRoute, error_responses
from coral.api.schemas import (
    InvalidResult,
    SavedCaseOut,
    SavedWorkflowOut,
    SimulatedResult,
    SimulateRequest,
    ValidResult,
    WorkflowDetailOut,
    WorkflowSummaryOut,
    WorkflowYaml,
)
from coral.bridge.config import DEFAULT_RUN_ACTIVATIONS
from coral.engine.simcase import SimCase, check_case
from coral.engine.simulate import SimScript, simulate
from coral.model import CompiledGraph, LoadError
from coral.omni.protocols import Viewer
from coral.stores.workflows import (
    MAX_WORKFLOW_CASES,
    CaseExists,
    CaseLimitReached,
    CaseRun,
    SavedCase,
    WorkflowDefinition,
    WorkflowDefinitionStore,
    WorkflowKeyTaken,
    WorkflowTooLargeError,
)
from coral.validate import ValidateContext
from coral.validate.pipeline import CheckResult, check_text

if TYPE_CHECKING:
    from coral.api.run_service import InFlight

_logger = logging.getLogger(__name__)

WORKFLOW_NOT_FOUND = "Workflow not found."
WORKFLOW_KEY_TAKEN = "A workflow with this key already exists."
CASE_NOT_FOUND = "Case not found."
CASE_EXISTS = "The workflow already has a case with this name."
CASE_LIMIT_REACHED = f"A workflow holds at most {MAX_WORKFLOW_CASES} cases."
CASE_TOO_LARGE = "The case is too large to store."
NOT_RUNNABLE_MISMATCH = "workflow: not runnable"
_ID = re.compile(r"[0-9a-f]{32}")
# Simulations in flight at once, for one user and in all; each has a thread of its own.
# One per user, as validating a large valid document can take seconds: four users fill it.
MAX_SIMULATIONS_PER_USER = 1
MAX_SIMULATIONS = 4
# A refused save describes its document in at most this much: the loader's report can
# quote the document once per issue.
MAX_LOAD_ISSUES = 20
MAX_LOAD_TEXT_CHARS = 500


def _clip(text: str) -> str:
    return text if len(text) <= MAX_LOAD_TEXT_CHARS else text[: MAX_LOAD_TEXT_CHARS - 1] + "…"


def load_error_details(error: LoadError) -> dict[str, Any]:
    """
    The details of a save refused because its document does not load.

    Only the loader's report on the caller's own text, which names no server path,
    with its first issues and every message and path cut to a bounded length.
    """
    issues = tuple(
        replace(issue, yaml_path=_clip(issue.yaml_path), message=_clip(issue.message))
        for issue in error.issues[:MAX_LOAD_ISSUES]
    )
    bounded = replace(
        error, yaml_path=_clip(error.yaml_path), message=_clip(error.message), issues=issues
    )
    return {"load_error": asdict(bounded), "issues_omitted": len(error.issues) - len(issues)}


def _check_result(result: CheckResult) -> ValidResult | InvalidResult:
    if result.load_error is not None:
        return InvalidResult(valid=False, runnable=False, load_error=result.load_error)
    assert result.graph is not None and result.report is not None
    return ValidResult(
        valid=True,
        runnable=result.report.runnable,
        content_hash=result.graph.content_hash,
        problems=list(result.report.problems),
        compiled=result.graph,
    )


def simulated(
    text: str, script: SimScript, context: ValidateContext
) -> SimulatedResult | InvalidResult:
    """
    Validate ``text`` as ``:validate`` does, then simulate it with ``script`` when runnable.

    The simulation runs with the server's bounds and the default run's activation cap.
    """
    checked = _check_result(check_text(text, context))
    if isinstance(checked, InvalidResult):
        return checked
    graph = checked.compiled
    runnable = checked.runnable and not graph.analysis.unresolved
    simulation = (
        simulate(graph, script, max_activations=DEFAULT_RUN_ACTIVATIONS).result
        if runnable
        else None
    )
    return SimulatedResult(**dict(checked), simulation=simulation)


def run_case(graph: CompiledGraph, runnable: bool, case: SimCase) -> CaseRun:
    """Run ``case`` on ``graph`` as a simulation would; a graph that cannot run is an error."""
    if not runnable or graph.analysis.unresolved:
        return CaseRun(status="error", mismatches=(NOT_RUNNABLE_MISMATCH,))
    result = check_case(graph, case, max_activations=DEFAULT_RUN_ACTIVATIONS)
    return CaseRun(
        status="passed" if result.passed else "failed",
        mismatches=tuple(_clip(line) for line in result.mismatches),
    )


def _case_out(saved: SavedCase) -> SavedCaseOut:
    return SavedCaseOut(
        id=saved.id,
        name=saved.case.name,
        script=saved.case.script,
        expect=saved.case.expect,
        last_result=saved.last_result,
        mismatches=list(saved.mismatches),
        last_run_at=saved.last_run_at,
        created_at=saved.created_at,
    )


def _summary(definition: WorkflowDefinition) -> WorkflowSummaryOut:
    return WorkflowSummaryOut(
        id=definition.id,
        workflow_key=definition.workflow_key,
        name=definition.name,
        content_hash=definition.content_hash,
        runnable=definition.runnable,
        created_at=definition.created_at,
        updated_at=definition.updated_at,
    )


def saved_workflow_out(definition: WorkflowDefinition, result: CheckResult) -> SavedWorkflowOut:
    """A stored definition with the validation of the text it stores."""
    assert result.graph is not None and result.report is not None
    return SavedWorkflowOut(
        **_summary(definition).model_dump(),
        valid=True,
        problems=list(result.report.problems),
        compiled=result.graph,
    )


def create_workflows_router(
    store: WorkflowDefinitionStore,
    *,
    viewer_dependency: Callable[..., Viewer] | Callable[..., Awaitable[Viewer]],
    workspace_id_dependency: Callable[..., int],
    simulations: Callable[[Request], InFlight],
    validate_context: Callable[[], ValidateContext] = ValidateContext,
) -> APIRouter:
    """
    The workflows routes, mounted by the caller under ``/v1/coral``.

    :param viewer_dependency: Resolves the caller, refusing with 401 or 403; it runs
        before the store is read.
    :param workspace_id_dependency: The request's workspace.
    :param simulations: The pool a request's simulation runs on, validation included;
        it refuses with 503 when it cannot take one.
    """
    router = APIRouter(route_class=CoralRoute)
    caller = Depends(viewer_dependency)
    workspace = Depends(workspace_id_dependency)

    @router.post(
        "/workflows:validate",
        operation_id="coral_validate_workflow",
        response_model=ValidResult | InvalidResult,
        responses=error_responses(401, 403, 422),
        dependencies=[caller],
    )
    def validate_workflow(body: WorkflowYaml) -> ValidResult | InvalidResult:
        """Load, compile and validate a workflow without storing it."""
        return _check_result(check_text(body.yaml, validate_context()))

    @router.post(
        "/workflows:simulate",
        operation_id="coral_simulate_workflow",
        response_model=SimulatedResult | InvalidResult,
        responses=error_responses(401, 403, 422, 503),
    )
    async def simulate_workflow(
        request: Request, body: SimulateRequest, viewer: Viewer = caller
    ) -> SimulatedResult | InvalidResult:
        """
        Validate a workflow and, when it is runnable, dry-run it on the engine with stub
        sessions, answering each question from the script; nothing is stored.
        """
        return await simulations(request).run(
            viewer, lambda: simulated(body.yaml, body.script, validate_context())
        )

    @router.post(
        "/workflows",
        operation_id="coral_save_workflow",
        response_model=SavedWorkflowOut,
        responses=error_responses(401, 403, 409, 413, 422),
    )
    def save_workflow(
        body: WorkflowYaml, viewer: Viewer = caller, workspace_id: int = workspace
    ) -> SavedWorkflowOut:
        """Store the caller's workflow under its key, replacing their earlier version."""
        result = check_text(body.yaml, validate_context())
        if result.graph is None or result.report is None:
            assert result.load_error is not None
            raise CoralApiError(
                "validation_failed",
                "The workflow does not load.",
                422,
                details=load_error_details(result.load_error),
            )
        try:
            definition = store.save(
                workspace_id=workspace_id,
                workflow_key=result.graph.workflow_id,
                name=result.graph.name,
                yaml_text=body.yaml,
                compiled=result.graph,
                runnable=result.report.runnable,
                owner=normalize_owner(viewer.user_id),
            )
        except WorkflowTooLargeError as error:
            raise CoralApiError("payload_too_large", str(error), 413) from error
        except WorkflowKeyTaken as error:
            raise CoralApiError("workflow_key_taken", WORKFLOW_KEY_TAKEN, 409) from error
        try:
            cases = store.list_cases(
                workspace_id=workspace_id,
                workflow_id=definition.id,
                owner=normalize_owner(viewer.user_id),
            )
            store.record_case_runs(
                workspace_id=workspace_id,
                workflow_id=definition.id,
                runs={
                    saved.id: run_case(definition.compiled, definition.runnable, saved.case)
                    for saved in cases or ()
                },
                content_hash=definition.content_hash,
            )
        except (SQLAlchemyError, ValidationError):
            _logger.exception("Coral could not re-run the saved cases of a saved workflow")
        return saved_workflow_out(definition, result)

    @router.get(
        "/workflows",
        operation_id="coral_list_workflows",
        response_model=list[WorkflowSummaryOut],
        responses=error_responses(401, 403),
    )
    def list_workflows(
        viewer: Viewer = caller, workspace_id: int = workspace
    ) -> list[WorkflowSummaryOut]:
        """The caller's workflows, by key."""
        definitions = store.list_definitions(
            workspace_id=workspace_id, owner=normalize_owner(viewer.user_id)
        )
        return [_summary(definition) for definition in definitions]

    @router.get(
        "/workflows/{workflow_id}",
        operation_id="coral_get_workflow",
        response_model=WorkflowDetailOut,
        responses=error_responses(401, 403, 404, 422),
    )
    def get_workflow(
        workflow_id: str, viewer: Viewer = caller, workspace_id: int = workspace
    ) -> WorkflowDetailOut:
        """One of the caller's workflows with its YAML and compiled graph."""
        definition = store.get(
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            owner=normalize_owner(viewer.user_id),
        )
        if definition is None:
            raise CoralApiError("not_found", WORKFLOW_NOT_FOUND, 404)
        return WorkflowDetailOut(
            **_summary(definition).model_dump(),
            yaml=definition.yaml_text,
            compiled=definition.compiled,
        )

    @router.get(
        "/workflows/{workflow_id}/cases",
        operation_id="coral_list_workflow_cases",
        response_model=list[SavedCaseOut],
        responses=error_responses(401, 403, 404, 422),
    )
    def list_workflow_cases(
        workflow_id: str, viewer: Viewer = caller, workspace_id: int = workspace
    ) -> list[SavedCaseOut]:
        """The saved cases of one of the caller's workflows, with their last results."""
        cases = (
            store.list_cases(
                workspace_id=workspace_id,
                workflow_id=workflow_id,
                owner=normalize_owner(viewer.user_id),
            )
            if _ID.fullmatch(workflow_id)
            else None
        )
        if cases is None:
            raise CoralApiError("not_found", WORKFLOW_NOT_FOUND, 404)
        return [_case_out(saved) for saved in cases]

    @router.post(
        "/workflows/{workflow_id}/cases",
        operation_id="coral_save_workflow_case",
        status_code=201,
        response_model=SavedCaseOut,
        responses=error_responses(401, 403, 404, 409, 413, 422),
    )
    def save_workflow_case(
        workflow_id: str, body: SimCase, viewer: Viewer = caller, workspace_id: int = workspace
    ) -> SavedCaseOut:
        """Save a case on one of the caller's workflows and run it on the stored definition."""
        owner = normalize_owner(viewer.user_id)
        definition = (
            store.get(workspace_id=workspace_id, workflow_id=workflow_id, owner=owner)
            if _ID.fullmatch(workflow_id)
            else None
        )
        if definition is None:
            raise CoralApiError("not_found", WORKFLOW_NOT_FOUND, 404)
        held = store.list_cases(workspace_id=workspace_id, workflow_id=workflow_id, owner=owner)
        if held is None:
            raise CoralApiError("not_found", WORKFLOW_NOT_FOUND, 404)
        if any(saved.case.name == body.name for saved in held):
            raise CoralApiError("case_exists", CASE_EXISTS, 409)
        if len(held) >= MAX_WORKFLOW_CASES:
            raise CoralApiError("case_limit_reached", CASE_LIMIT_REACHED, 409)
        try:
            saved = store.add_case(
                workspace_id=workspace_id,
                workflow_id=workflow_id,
                owner=owner,
                case=body,
                result=run_case(definition.compiled, definition.runnable, body),
                content_hash=definition.content_hash,
            )
        except CaseExists as error:
            raise CoralApiError("case_exists", CASE_EXISTS, 409) from error
        except CaseLimitReached as error:
            raise CoralApiError("case_limit_reached", CASE_LIMIT_REACHED, 409) from error
        except WorkflowTooLargeError as error:
            raise CoralApiError("payload_too_large", CASE_TOO_LARGE, 413) from error
        if saved is None:
            raise CoralApiError("not_found", WORKFLOW_NOT_FOUND, 404)
        return _case_out(saved)

    @router.delete(
        "/workflows/{workflow_id}/cases/{case_id}",
        operation_id="coral_delete_workflow_case",
        status_code=204,
        response_class=Response,
        responses=error_responses(401, 403, 404, 422),
    )
    def delete_workflow_case(
        workflow_id: str, case_id: str, viewer: Viewer = caller, workspace_id: int = workspace
    ) -> Response:
        """Delete one of the saved cases of one of the caller's workflows."""
        owner = normalize_owner(viewer.user_id)
        known = _ID.fullmatch(workflow_id) is not None
        if (
            known
            and _ID.fullmatch(case_id)
            and store.delete_case(
                workspace_id=workspace_id, workflow_id=workflow_id, case_id=case_id, owner=owner
            )
        ):
            return Response(status_code=204)
        if (
            not known
            or store.get(workspace_id=workspace_id, workflow_id=workflow_id, owner=owner) is None
        ):
            raise CoralApiError("not_found", WORKFLOW_NOT_FOUND, 404)
        raise CoralApiError("not_found", CASE_NOT_FOUND, 404)

    return router
