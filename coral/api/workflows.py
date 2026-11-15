"""Workflow validate/save/get router. Unmounted: the Coral server plugin registers it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from coral.stores.workflows import (
    WorkflowDefinition,
    WorkflowDefinitionStore,
    WorkflowTooLargeError,
)
from coral.validate import ValidateContext
from coral.validate.pipeline import CheckResult, check_text


class WorkflowYaml(BaseModel):
    yaml: str


def _check_json(result: CheckResult) -> dict[str, Any]:
    if result.load_error is not None:
        return {"valid": False, "runnable": False, "load_error": asdict(result.load_error)}
    assert result.graph is not None and result.report is not None
    return {
        "valid": True,
        "runnable": result.report.runnable,
        "content_hash": result.graph.content_hash,
        "problems": [asdict(problem) for problem in result.report.problems],
    }


def _definition_json(definition: WorkflowDefinition, *, include_body: bool) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": definition.id,
        "workflow_key": definition.workflow_key,
        "name": definition.name,
        "content_hash": definition.content_hash,
        "runnable": definition.runnable,
        "created_at": definition.created_at,
        "updated_at": definition.updated_at,
    }
    if include_body:
        summary["yaml"] = definition.yaml_text
        summary["compiled"] = definition.compiled.model_dump(mode="json")
    return summary


def create_workflows_router(
    store: WorkflowDefinitionStore,
    *,
    workspace_id_dependency: Callable[..., int],
    validate_context: Callable[[], ValidateContext] = ValidateContext,
) -> APIRouter:
    """Build the router; the caller chooses the mount prefix and workspace resolution."""
    router = APIRouter()

    @router.post("/workflows:validate")
    def validate_workflow(body: WorkflowYaml) -> dict[str, Any]:
        return _check_json(check_text(body.yaml, validate_context()))

    @router.post("/workflows")
    def save_workflow(
        body: WorkflowYaml, workspace_id: int = Depends(workspace_id_dependency)
    ) -> dict[str, Any]:
        result = check_text(body.yaml, validate_context())
        if result.graph is None or result.report is None:
            raise HTTPException(status_code=422, detail=_check_json(result))
        try:
            definition = store.save(
                workspace_id=workspace_id,
                workflow_key=result.graph.workflow_id,
                name=result.graph.name,
                yaml_text=body.yaml,
                compiled=result.graph,
                runnable=result.report.runnable,
            )
        except WorkflowTooLargeError as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        return {**_definition_json(definition, include_body=False), **_check_json(result)}

    @router.get("/workflows")
    def list_workflows(
        workspace_id: int = Depends(workspace_id_dependency),
    ) -> list[dict[str, Any]]:
        return [
            _definition_json(definition, include_body=False)
            for definition in store.list_definitions(workspace_id=workspace_id)
        ]

    @router.get("/workflows/{workflow_id}")
    def get_workflow(
        workflow_id: str, workspace_id: int = Depends(workspace_id_dependency)
    ) -> dict[str, Any]:
        definition = store.get(workspace_id=workspace_id, workflow_id=workflow_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="workflow not found")
        return _definition_json(definition, include_body=True)

    return router
