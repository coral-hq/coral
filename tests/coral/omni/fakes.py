"""Protocol fakes for the K4 session subset, used by executor and drift tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from coral.model.ids import anchor_session_id, effect_session_id
from coral.omni.protocols import RunnerRelaunch, SessionCreateRequest, SessionRef, SessionState


def present(session_id: str, **changes: object) -> SessionState:
    """A session that exists, is not archived or closed, and has no runner or host."""
    fields: dict[str, object] = {
        "session_id": session_id,
        "exists": True,
        "archived": False,
        "archived_at": None,
        "closed": False,
        "runner_id": None,
        "host_id": None,
        **changes,
    }
    return SessionState(**fields)  # type: ignore[arg-type]


@dataclass
class FakeSessionFacade:
    """
    ``SessionFacade`` that derives session ids as the real one does and records each call.

    :param refusal: Raised by every ``create_session`` after its lease check.
    :param states: ``session_state`` answers; unknown sessions are ``present``.
    :param on_create: Called with each request, e.g. to record the scope it ran in.
    """

    refusal: BaseException | None = None
    states: dict[tuple[int, str], SessionState] = field(default_factory=dict)
    on_create: Callable[[SessionCreateRequest], None] | None = None
    requests: list[SessionCreateRequest] = field(default_factory=list)
    created: set[tuple[int, str]] = field(default_factory=set)

    async def create_session(
        self,
        request: SessionCreateRequest,
        *,
        ensure_lease: Callable[[], Awaitable[None]],
    ) -> SessionRef:
        self.requests.append(request)
        if self.on_create is not None:
            self.on_create(request)
        await ensure_lease()
        if self.refusal is not None:
            raise self.refusal
        session_id = (
            anchor_session_id(request.workspace_id, request.run_id)
            if request.role == "anchor"
            else effect_session_id(request.workspace_id, request.effect_key)
        )
        key = (request.workspace_id, session_id)
        created = key not in self.created
        self.created.add(key)
        return SessionRef(session_id=session_id, role=request.role, created=created)

    async def session_state(self, *, workspace_id: int, session_id: str) -> SessionState:
        return self.states.get((workspace_id, session_id), present(session_id))


@dataclass
class FakeRelauncher:
    """
    ``StepRelauncher`` that answers from a script and records each call.

    :param answers: Returned (or raised) in order; once used up, ``fallback`` decides.
    :param fallback: Answers a call the script does not, e.g. from the session's runner.
    :param on_relaunch: Called with the session id after each ``relaunched`` answer.
    """

    answers: list[RunnerRelaunch | BaseException] = field(default_factory=list)
    fallback: Callable[[str], RunnerRelaunch] = lambda _session_id: "relaunched"
    on_relaunch: Callable[[str], None] | None = None
    calls: list[tuple[int, str, int]] = field(default_factory=list)

    async def ensure_runner(
        self,
        *,
        workspace_id: int,
        session_id: str,
        generation: int,
        ensure_lease: Callable[[], Awaitable[None]] | None = None,
    ) -> RunnerRelaunch:
        self.calls.append((workspace_id, session_id, generation))
        if ensure_lease is not None:
            await ensure_lease()
        answer = self.answers.pop(0) if self.answers else self.fallback(session_id)
        if isinstance(answer, BaseException):
            raise answer
        if answer == "relaunched" and self.on_relaunch is not None:
            self.on_relaunch(session_id)
        return answer
