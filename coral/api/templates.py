"""
Built-in workflow templates router. Unmounted: the Coral server plugin registers it.

Every route needs a signed-in caller. The list is the package's registered templates.
Using one makes the caller's own workflow from it in the request's workspace, under the
first key no definition holds (the template's id, then ``-2``, ``-3``, ... and at last a
random suffix, which a use that keeps losing races to concurrent ones also takes): it
only inserts, so it never replaces anyone's workflow, the caller's own edited copy included.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, Collection

from fastapi import APIRouter, Depends

from coral.alerts.types import normalize_owner
from coral.api.errors import CoralApiError, CoralRoute, error_responses
from coral.api.run_models import EmptyRequest
from coral.api.schemas import SavedWorkflowOut, TemplateOut
from coral.api.workflows import saved_workflow_out
from coral.model.ids import validate_workflow_id
from coral.omni.protocols import Viewer
from coral.stores.workflows import WorkflowDefinitionStore, WorkflowKeyTaken, WorkflowTooLargeError
from coral.templates import (
    BuiltinTemplate,
    TemplateError,
    builtin_template,
    builtin_templates,
    with_workflow_id,
)
from coral.validate import ValidateContext
from coral.validate.pipeline import check_text

TEMPLATE_NOT_FOUND = "Template not found."
# The refusal names no key: the request named none.
NO_FREE_KEY = "No free workflow key could be chosen for a copy of this template."
# Numbered copies tried after the template's own id, before a random suffix.
MAX_TEMPLATE_COPIES = 99
# Inserts one use makes at most; another is tried only when a concurrent one took the key.
MAX_USE_ATTEMPTS = 3
RANDOM_SUFFIX_BYTES = 3
# Random suffixes drawn before giving up on one that nobody holds.
MAX_RANDOM_DRAWS = 3


def _usable(key: str) -> bool:
    try:
        validate_workflow_id(key)
    except ValueError:
        return False
    return True


def free_key(template_id: str, taken: Collection[str], *, numbered: bool = True) -> str | None:
    """
    The first usable workflow key not in ``taken``: the template's id, then ``<id>-2`` to
    ``<id>-<MAX_TEMPLATE_COPIES + 1>``, else ``<id>-<random hex>``; ``None`` when no
    random draw is a usable key nobody holds. ``numbered=False`` goes straight to random.
    """
    if numbered:
        copies = (f"{template_id}-{number}" for number in range(2, MAX_TEMPLATE_COPIES + 2))
        for key in (template_id, *copies):
            if key not in taken and _usable(key):
                return key
    for _draw in range(MAX_RANDOM_DRAWS):
        key = f"{template_id}-{secrets.token_hex(RANDOM_SUFFIX_BYTES)}"
        if key not in taken and _usable(key):
            return key
    return None


def _template_out(template: BuiltinTemplate) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        name=template.name,
        description=template.description,
        yaml=template.yaml_text,
    )


def create_templates_router(
    store: WorkflowDefinitionStore,
    *,
    viewer_dependency: Callable[..., Viewer] | Callable[..., Awaitable[Viewer]],
    workspace_id_dependency: Callable[..., int],
    validate_context: Callable[[], ValidateContext] = ValidateContext,
) -> APIRouter:
    """
    The templates routes, mounted by the caller under ``/v1/coral``.

    :param viewer_dependency: Resolves the caller, refusing with 401 or 403; it runs
        before the store is read.
    :param workspace_id_dependency: The request's workspace.
    """
    router = APIRouter(route_class=CoralRoute)
    caller = Depends(viewer_dependency)
    workspace = Depends(workspace_id_dependency)

    @router.get(
        "/templates",
        operation_id="coral_list_templates",
        response_model=list[TemplateOut],
        responses=error_responses(401, 403),
        dependencies=[caller],
    )
    def list_templates() -> list[TemplateOut]:
        """The built-in workflow templates, in gallery order."""
        return [_template_out(template) for template in builtin_templates()]

    @router.post(
        "/templates/{template_id}:use",
        operation_id="coral_use_template",
        status_code=201,
        response_model=SavedWorkflowOut,
        responses=error_responses(401, 403, 404, 409, 413, 422),
    )
    def use_template(
        template_id: str,
        _body: EmptyRequest,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> SavedWorkflowOut:
        """
        Make the caller's own workflow from a built-in template, under the first key no
        workflow holds; an existing workflow is never replaced.
        """
        # Matched against the registry only; the id is never echoed or used as a path.
        template = builtin_template(template_id)
        if template is None:
            raise CoralApiError("not_found", TEMPLATE_NOT_FOUND, 404)
        owner = normalize_owner(viewer.user_id)
        for attempt in range(MAX_USE_ATTEMPTS):
            taken = store.workflow_keys(workspace_id=workspace_id, prefix=template.id)
            # Concurrent uses race for the same numbered key; the last try takes a random one.
            key = free_key(template.id, taken, numbered=attempt < MAX_USE_ATTEMPTS - 1)
            if key is None:
                break
            text = with_workflow_id(template, key)
            result = check_text(text, validate_context())
            # A row's key is always the id its YAML names.
            if result.graph is None or result.report is None or result.graph.workflow_id != key:
                raise TemplateError(f"built-in template {template.id!r} does not load as {key!r}")
            try:
                definition = store.create(
                    workspace_id=workspace_id,
                    workflow_key=key,
                    name=result.graph.name,
                    yaml_text=text,
                    compiled=result.graph,
                    runnable=result.report.runnable,
                    owner=owner,
                )
            except WorkflowTooLargeError as error:
                raise CoralApiError("payload_too_large", str(error), 413) from error
            except WorkflowKeyTaken:
                # A concurrent save took the key after it was read: read the keys again.
                continue
            return saved_workflow_out(definition, result)
        raise CoralApiError("workflow_key_taken", NO_FREE_KEY, 409)

    return router


__all__ = [
    "MAX_RANDOM_DRAWS",
    "MAX_TEMPLATE_COPIES",
    "MAX_USE_ATTEMPTS",
    "NO_FREE_KEY",
    "TEMPLATE_NOT_FOUND",
    "create_templates_router",
    "free_key",
]
