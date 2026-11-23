"""The owner's runs: start, list, detail, pinned graph, log, outcome, actions and gate answers.

Unmounted: the Coral server plugin mounts it under ``/v1/coral`` with its own caller
and workspace dependencies. The runs API is read per request from
``app.state.coral_runs_api``, which the lifespan publishes; without it every route
answers the run 404. Every route that names a run checks it is the caller's through
:meth:`RunsApi.owned_run` before anything else. Every POST takes a JSON body. Run
reads, writes and their refusals are never cached.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
from typing import ClassVar

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response

from coral.api.errors import CoralApiError, CoralRoute, error_responses, run_not_found
from coral.api.run_models import (
    ACTIVATION_ID_PATTERN,
    DEFAULT_LOG_LIMIT,
    DEFAULT_RUNS_LIMIT,
    MAX_LOG_LIMIT,
    MAX_STATUS_FILTERS,
    MAX_STORED_INT,
    WORKFLOW_ID_PATTERN,
    EmptyRequest,
    GateAnswerOut,
    GateAnswerRequest,
    LogPage,
    PreflightRequest,
    PreflightResponse,
    ResumeRequest,
    RunDetail,
    RunOutcome,
    RunPage,
    RunSummary,
    StartRunRequest,
    invalid_run_cursor,
    parse_run_cursor,
)
from coral.api.run_service import RunsApi
from coral.api.stream import CoralEventStream, RunStreamHub, stream_cursor
from coral.model.ir import CompiledGraph
from coral.omni.protocols import Viewer
from coral.runview.types import RunStatusName
from coral.stores.protocols import MAX_OWNED_RUNS_LIMIT
from coral.stores.workflows import WorkflowDefinitionStore

# Run reads carry prompts, paths and step output: never kept by a cache.
_NO_STORE = "private, no-store"
# A pinned graph never changes, but is revalidated so a revoked caller stops seeing it.
_REVALIDATE = "private, no-cache"
_NOT_MODIFIED = {304: {"description": "Not Modified"}}
# Repeated ``status`` values: a run in any of them is listed.
_STATUS_FILTER = Query(default=[], alias="status")
_RUNS_PATH = "/v1/coral/runs"
_REPLAYED = {
    200: {
        "model": RunSummary,
        "description": "The run this start key already started, for the same request",
    }
}
# Refusals of an action on one of the caller's runs.
_ACTION_REFUSALS = error_responses(401, 403, 404, 409, 422, 503)
# The stream is never cached and never buffered by a proxy on its way.
_STREAM_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
_EVENT_STREAM = {
    200: {
        "description": (
            "Server-sent events: each event's data is a RunStreamFrame, or `[DONE]` once a "
            "finished run's rows are all sent"
        ),
        "content": {
            "text/event-stream": {"schema": {"$ref": "#/components/schemas/RunStreamFrame"}}
        },
    }
}


class _RunsRoute(CoralRoute):
    """A runs route, whose refusals are never cached either."""

    refusal_headers: ClassVar[Mapping[str, str]] = MappingProxyType({"Cache-Control": _NO_STORE})


def _runs_api(request: Request) -> RunsApi:
    api = getattr(request.app.state, "coral_runs_api", None)
    if api is None:
        raise run_not_found()
    return api


def _stream_hub(request: Request) -> RunStreamHub:
    hub = getattr(request.app.state, "coral_run_stream_hub", None)
    if hub is None:
        raise run_not_found()
    return hub


def create_runs_router(
    *,
    definitions: WorkflowDefinitionStore,
    viewer_dependency: Callable[..., Viewer] | Callable[..., Awaitable[Viewer]],
    workspace_id_dependency: Callable[..., int],
) -> APIRouter:
    """
    The runs routes, mounted by the caller under ``/v1/coral``.

    :param definitions: The workflows a start reads; only the caller's own start.
    :param viewer_dependency: Resolves the caller, refusing with 401 or 403 before any
        run is read.
    :param workspace_id_dependency: The request's workspace.
    """
    router = APIRouter(route_class=_RunsRoute)
    caller = Depends(viewer_dependency)
    workspace = Depends(workspace_id_dependency)

    @router.post(
        "/runs",
        operation_id="coral_start_run",
        status_code=201,
        response_model=RunSummary,
        responses={**_REPLAYED, **error_responses(400, 401, 403, 404, 409, 422, 503)},
    )
    async def start_run(
        request: Request,
        response: Response,
        body: StartRunRequest,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> RunSummary:
        """
        Start one of the caller's workflows on their host's repository: 201 with the new
        run, or 200 with the run the same ``start_key`` and request started before.
        """
        started = await _runs_api(request).start(
            viewer, workspace_id, body, definitions=definitions
        )
        response.status_code = 201 if started.created else 200
        response.headers["Location"] = f"{_RUNS_PATH}/{started.summary.run_id}"
        response.headers["Cache-Control"] = _NO_STORE
        return started.summary

    @router.post(
        "/runs:preflight",
        operation_id="coral_preflight_run",
        response_model=PreflightResponse,
        responses=error_responses(401, 403, 404, 422, 503),
    )
    async def preflight_run(
        request: Request,
        response: Response,
        body: PreflightRequest,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> PreflightResponse:
        """
        Check whether one of the caller's workflows can start on their host, without
        starting a run: auth, host, OS sandbox and system Claude, plus a session estimate.
        """
        report = await _runs_api(request).preflight(
            viewer, workspace_id, body, definitions=definitions
        )
        response.headers["Cache-Control"] = _NO_STORE
        return report

    @router.post(
        "/runs/{run_id}:pause",
        operation_id="coral_pause_run",
        response_model=RunSummary,
        responses=_ACTION_REFUSALS,
    )
    async def pause_run(
        request: Request,
        response: Response,
        run_id: str,
        _body: EmptyRequest,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> RunSummary:
        """Pause one of the caller's runs; a paused run is left as it is."""
        summary = await _runs_api(request).pause(viewer, workspace_id, run_id)
        response.headers["Cache-Control"] = _NO_STORE
        return summary

    @router.post(
        "/runs/{run_id}:resume",
        operation_id="coral_resume_run",
        response_model=RunSummary,
        responses=_ACTION_REFUSALS,
    )
    async def resume_run(
        request: Request,
        response: Response,
        run_id: str,
        body: ResumeRequest,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> RunSummary:
        """
        Resume one of the caller's paused runs; ``cap`` raises the activation cap of one
        paused at it. A run not paused is left as it is.
        """
        summary = await _runs_api(request).resume(viewer, workspace_id, run_id, cap=body.cap)
        response.headers["Cache-Control"] = _NO_STORE
        return summary

    @router.post(
        "/runs/{run_id}:cancel",
        operation_id="coral_cancel_run",
        response_model=RunSummary,
        responses=_ACTION_REFUSALS,
    )
    async def cancel_run(
        request: Request,
        response: Response,
        run_id: str,
        _body: EmptyRequest,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> RunSummary:
        """Cancel one of the caller's runs; a cancelled run is left as it is."""
        summary = await _runs_api(request).cancel(viewer, workspace_id, run_id)
        response.headers["Cache-Control"] = _NO_STORE
        return summary

    @router.post(
        "/runs/{run_id}:retry",
        operation_id="coral_retry_run",
        response_model=RunSummary,
        responses=_ACTION_REFUSALS,
    )
    async def retry_run(
        request: Request,
        response: Response,
        run_id: str,
        _body: EmptyRequest,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> RunSummary:
        """
        Retry one of the caller's paused runs whose failure no step owns, such as a lost
        orchestrator or anchor: a lost orchestrator is replaced by a new one.
        """
        summary = await _runs_api(request).retry(viewer, workspace_id, run_id, None)
        response.headers["Cache-Control"] = _NO_STORE
        return summary

    @router.post(
        "/runs/{run_id}/activations/{activation_id}:retry",
        operation_id="coral_retry_activation",
        response_model=RunSummary,
        responses=_ACTION_REFUSALS,
    )
    async def retry_activation(
        request: Request,
        response: Response,
        run_id: str,
        _body: EmptyRequest,
        # A store activation id, as the detail's ``retry_activation_ids`` name it; matched
        # only against the run's own activations, never echoed or logged.
        activation_id: str = Path(pattern=ACTIVATION_ID_PATTERN),
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> RunSummary:
        """
        Retry a failed step of one of the caller's runs: its old session is fenced and its
        work saved while the run stays paused, then a new session starts it again.
        """
        summary = await _runs_api(request).retry(viewer, workspace_id, run_id, activation_id)
        response.headers["Cache-Control"] = _NO_STORE
        return summary

    @router.post(
        "/runs/{run_id}/gates/{node_id}:answer",
        operation_id="coral_answer_gate",
        response_model=GateAnswerOut,
        responses=_ACTION_REFUSALS,
    )
    async def answer_gate(
        request: Request,
        response: Response,
        run_id: str,
        node_id: str,
        body: GateAnswerRequest,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> GateAnswerOut:
        """
        Answer a visit of one of the caller's run's gates with one of its outcomes, as
        its prompt would be answered. A visit the run does not have is the run 404.
        """
        answered = await _runs_api(request).answer_gate(
            viewer, workspace_id, run_id, node_id, body
        )
        response.headers["Cache-Control"] = _NO_STORE
        return answered

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
        "/runs/{run_id}/stream",
        operation_id="coral_stream_run",
        response_model=None,
        responses={**_EVENT_STREAM, **error_responses(401, 403, 404, 422, 429, 503)},
    )
    async def stream_run(
        request: Request,
        run_id: str,
        after_seq: int | None = Query(default=None, ge=0, le=MAX_STORED_INT),
        # A malformed one is answered with a resync, never refused.
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> Response:
        """
        Follow one of the caller's runs: a snapshot of its view, then one entry per log
        row with the row's view patch. ``Last-Event-ID`` (else ``after_seq``) resumes
        after the last seq the client holds. A stream ends after five minutes; the
        client resumes from its last seq. Past the stream caps, poll ``/log`` instead.
        """
        api = _runs_api(request)
        hub = _stream_hub(request)
        await api.owned_run(viewer, workspace_id, run_id)
        reservation = hub.reserve(viewer, workspace_id, run_id)
        stream = hub.stream(
            viewer,
            workspace_id,
            run_id,
            cursor=stream_cursor(last_event_id, after_seq),
            is_disconnected=request.is_disconnected,
            reservation=reservation,
        )
        return CoralEventStream(stream.frames(), reservation=reservation, headers=_STREAM_HEADERS)

    @router.get(
        "/runs/{run_id}/outcome",
        operation_id="coral_get_run_outcome",
        response_model=RunOutcome,
        responses=error_responses(401, 403, 404, 422, 503),
    )
    async def get_run_outcome(
        request: Request,
        response: Response,
        run_id: str,
        viewer: Viewer = caller,
        workspace_id: int = workspace,
    ) -> RunOutcome:
        """
        What one of the caller's runs produced: its branch, the commands that check it
        out, and for a finished run its diff from its base commit, read through its host.
        A diff that cannot be read is answered with ``diff_unavailable``, never an error.
        """
        outcome = await _runs_api(request).outcome(viewer, workspace_id, run_id)
        response.headers["Cache-Control"] = _NO_STORE
        return outcome

    return router


__all__ = ["create_runs_router"]
