"""
Workflow validate/save/get/list router. Unmounted: the Coral server plugin registers it.

Every route needs a signed-in caller. A caller saves, reads and lists their own
definitions in the request's workspace, plus legacy ones saved before definitions had
owners; saving a key another user holds is refused.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from typing import Any

from fastapi import APIRouter, Depends

from coral.alerts.types import normalize_owner
from coral.api.errors import CoralApiError, CoralRoute, error_responses
from coral.api.schemas import (
    InvalidResult,
    SavedWorkflowOut,
    ValidResult,
    WorkflowDetailOut,
    WorkflowSummaryOut,
    WorkflowYaml,
)
from coral.model import LoadError
from coral.omni.protocols import Viewer
from coral.stores.workflows import (
    WorkflowDefinition,
    WorkflowDefinitionStore,
    WorkflowKeyTaken,
    WorkflowTooLargeError,
)
from coral.validate import ValidateContext
from coral.validate.pipeline import CheckResult, check_text

WORKFLOW_NOT_FOUND = "Workflow not found."
WORKFLOW_KEY_TAKEN = "A workflow with this key already exists."
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


def create_workflows_router(
    store: WorkflowDefinitionStore,
    *,
    viewer_dependency: Callable[..., Viewer] | Callable[..., Awaitable[Viewer]],
    workspace_id_dependency: Callable[..., int],
    validate_context: Callable[[], ValidateContext] = ValidateContext,
) -> APIRouter:
    """
    The workflows routes, mounted by the caller under ``/v1/coral``.

    :param viewer_dependency: Resolves the caller, refusing with 401 or 403; it runs
        before the store is read.
    :param workspace_id_dependency: The request's workspace.
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
        return SavedWorkflowOut(
            **_summary(definition).model_dump(),
            valid=True,
            problems=list(result.report.problems),
            compiled=result.graph,
        )

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

    return router
