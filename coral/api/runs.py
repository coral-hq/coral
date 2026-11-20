"""The owner's runs: list, detail, pinned graph and log.

Unmounted: the Coral server plugin mounts it under ``/v1/coral`` with its own caller
and workspace dependencies. The runs API is read per request from
``app.state.coral_runs_api``, which the lifespan publishes; without it every route
answers the run 404. Every route names the caller's run through
:meth:`RunsApi.owned_run` before anything else.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from coral.api.errors import CoralApiError, CoralRoute, error_responses, run_not_found
from coral.api.run_models import (
    DEFAULT_LOG_LIMIT,
    DEFAULT_RUNS_LIMIT,
    MAX_LOG_LIMIT,
    MAX_STATUS_FILTERS,
    MAX_STORED_INT,
    WORKFLOW_ID_PATTERN,
    LogPage,
    RunDetail,
    RunPage,
    invalid_run_cursor,
    parse_run_cursor,
)
from coral.api.run_service import RunsApi
from coral.model.ir import CompiledGraph
from coral.omni.protocols import Viewer
from coral.runview.types import RunStatusName
from coral.stores.protocols import MAX_OWNED_RUNS_LIMIT

# Run reads carry prompts, paths and step output: never kept by a cache.
_NO_STORE = "private, no-store"
# A pinned graph never changes, but is revalidated so a revoked caller stops seeing it.
_REVALIDATE = "private, no-cache"
_NOT_MODIFIED = {304: {"description": "Not Modified"}}
# Repeated ``status`` values: a run in any of them is listed.
_STATUS_FILTER = Query(default=[], alias="status")


def _runs_api(request: Request) -> RunsApi:
    api = getattr(request.app.state, "coral_runs_api", None)
    if api is None:
        raise run_not_found()
    return api


def create_runs_router(
    *,
    viewer_dependency: Callable[..., Viewer] | Callable[..., Awaitable[Viewer]],
    workspace_id_dependency: Callable[..., int],
) -> APIRouter:
    """
    The runs read routes, mounted by the caller under ``/v1/coral``.

    :param viewer_dependency: Resolves the caller, refusing with 401 or 403 before any
        run is read.
    :param workspace_id_dependency: The request's workspace.
    """
    router = APIRouter(route_class=CoralRoute)
    caller = Depends(viewer_dependency)
    workspace = Depends(workspace_id_dependency)

    @router.get(
        "/runs",
        operation_id="coral_list_runs",
        response_model=RunPage,
        responses=error_responses(401, 403, 404, 422, 503),
    )
    async def list_runs(
        request: Request,
        response: Response,
        statuses: list[RunStatusName] = _STATUS_FILTER,
        workflow_id: str | None = Query(default=None, pattern=WORKFLOW_ID_PATTERN),
        # Its length is checked with its format, so both give the cursor's own 422.
        after: str | None = Query(default=None),
        limit: int = Query(default=DEFAULT_RUNS_LIMIT, ge=1, le=MAX_OWNED_RUNS_LIMIT),
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> RunPage:
        """The caller's runs, newest first; spend is what the cache holds, or null."""
        response.headers["Cache-Control"] = _NO_STORE
        api = _runs_api(request)
        distinct = tuple(dict.fromkeys(statuses))
        if len(distinct) > MAX_STATUS_FILTERS:
            raise CoralApiError("validation_failed", "Too many status filters.", 422)
        try:
            cursor = None if after is None else parse_run_cursor(after)
        except ValueError:
            raise invalid_run_cursor() from None
        return await api.list_runs(
            viewer,
            workspace_id,
            statuses=distinct,
            workflow_id=workflow_id,
            after=cursor,
            limit=limit,
        )

    @router.get(
        "/runs/{run_id}",
        operation_id="coral_get_run",
        response_model=RunDetail,
        responses=error_responses(401, 403, 404, 422, 503),
    )
    async def get_run(
        request: Request,
        response: Response,
        run_id: str,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> RunDetail:
        """One of the caller's runs in full, with its spend so far."""
        detail = await _runs_api(request).detail(viewer, workspace_id, run_id)
        response.headers["Cache-Control"] = _NO_STORE
        return detail

    @router.get(
        "/runs/{run_id}/graph",
        operation_id="coral_get_run_graph",
        response_model=CompiledGraph,
        responses={**_NOT_MODIFIED, **error_responses(401, 403, 404, 422, 503)},
    )
    async def get_run_graph(
        request: Request,
        response: Response,
        run_id: str,
        if_none_match: str | None = Header(default=None),
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> CompiledGraph | Response:
        """The workflow graph the run is pinned to; ``If-None-Match`` revalidates it."""
        found = await _runs_api(request).graph(
            viewer, workspace_id, run_id, if_none_match=if_none_match
        )
        headers = {"ETag": found.etag, "Cache-Control": _REVALIDATE}
        if found.graph is None:
            return Response(status_code=304, headers=headers)
        response.headers.update(headers)
        return found.graph

    @router.get(
        "/runs/{run_id}/log",
        operation_id="coral_get_run_log",
        response_model=LogPage,
        responses=error_responses(401, 403, 404, 422, 503),
    )
    async def get_run_log(
        request: Request,
        response: Response,
        run_id: str,
        after_seq: int = Query(default=0, ge=0, le=MAX_STORED_INT),
        limit: int = Query(default=DEFAULT_LOG_LIMIT, ge=1, le=MAX_LOG_LIMIT),
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> LogPage:
        """
        The run's log rows after ``after_seq``, with their bodies: at most 1 MiB of bodies
        and patches a page, then ``next_after_seq``. A body over 256 KiB is left out.
        """
        page = await _runs_api(request).log(
            viewer, workspace_id, run_id, after_seq=after_seq, limit=limit
        )
        response.headers["Cache-Control"] = _NO_STORE
        return page

    @router.get(
        "/runs/{run_id}/outcome",
        operation_id="coral_get_run_outcome",
        status_code=501,
        response_class=Response,
        responses=error_responses(401, 403, 404, 422, 501, 503),
    )
    async def get_run_outcome(
        request: Request,
        run_id: str,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> Response:
        """Not served yet: the caller's own run answers 501."""
        await _runs_api(request).outcome(viewer, workspace_id, run_id)

    return router


__all__ = ["create_runs_router"]
