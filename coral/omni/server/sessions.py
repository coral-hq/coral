"""Request-free, idempotent create of a Coral run's sessions on Omnigent (K4 ``SessionFacade``).

Session ids come from the run: the run's one anchor from its run id, a step
from its effect key, so a redelivered effect finds its own session. A
binding row records how far a create got (``reserved`` → ``row_created`` →
``initialized``), and the next delivery resumes there. It adopts a row an
earlier try wrote only when the row matches the request. It repairs a torn
split-database row (the conversation row without its metadata) once, and
only a row that is plainly its own unfinished create. It never creates again
a session the user deleted, nor launches one the user archived, after its row
existed. The repair relies on one worker draining at a time (the primary
worker lease).

The anchor is a visible session Coral never launches, filed in the owner's
"Coral runs" project and bound to the hidden ``coral__anchor`` agent (a chat
agent from the anchor seed, which runs only if a user binds a runner to it).
A step is a child of the anchor on the run owner's host, in the run worktree,
with no runner until its own create launches one inside the owner's host
scope. Both get an owner grant and no public grant. A create binds only while
its slot is still at the create's generation: one the slot left meanwhile (a
retry, or an old leader's late create) is labelled closed, stopped and abandoned.

After its create, Coral's own paths launch a step's runner again only through
:class:`OmnigentStepRelauncher`, in the same session: the wake after a lost
runner and any engine send that finds no runner both use it. A person's message
or a resource route can still reach Omnigent's own launch for the session.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, override

from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from coral.bridge.keys import store_slot_id
from coral.db.enum_codecs import SessionBindingProgress, SessionBindingRole
from coral.model.ids import anchor_session_id, derived_id, effect_session_id
from coral.omni._upstream import (
    _announce_session_added,
    _create_resolved_harness,
    _ensure_builtin_agent,
    _ensure_runner_session_initialized,
    _get_runner_client,
    _query_host_runner_status,
    _repl_terminal_ui_labels,
    _stop_session_host_runner,
    canonical_host_id,
    resolve_host_launch,
    validate_create_harness_readiness,
    validate_existing_host_workspace,
    validate_session_agent,
    validate_session_model_metadata,
)
from coral.omni.process_map import CORAL_RUNNER_TOKEN
from coral.omni.protocols import (
    CoralSessionError,
    RunnerRelaunch,
    SessionCreateRequest,
    SessionDispatch,
    SessionFacade,
    SessionRef,
    SessionState,
    StepRelauncher,
)
from coral.omni.server.access import omnigent_owner, ownerless_runs_allowed
from coral.omni.server.bundles import StepBundleRejected, check_hygiene, pack_bundle
from coral.omni.server.host_access import HostAccessError, OwnerHost, authorize_owner_host
from coral.omni.server.worktrees import connect_run_worktree_host
from coral.profiles.bundle_spec import ENGINE_PREFIX, Stance, build_seed_bundle_yaml
from coral.queue.drainer import SlotSuperseded
from coral.recovery.drift import DriftDetected, DriftFinding, classify_anchor, classify_step
from coral.recovery.relaunch import RUNNER_ALIVE_HOLD
from coral.stores.protocols import RunNotFound, RunStore
from coral.stores.session_bindings import (
    BindingConflict,
    SessionBinding,
    SessionBindingDraft,
    SessionBindingLookup,
    SessionBindings,
)
from coral.tools.catalog import ORCHESTRATOR_STANCE, STEP_STANCES, generated_stance
from coral.workspace.run_worktree import RunWorktreeError
from omnigent.db.db_models import workspace_scope
from omnigent.entities import Conversation
from omnigent.entities.conversation import USER_SESSION_TITLE_MAX_CHARS
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.harness_aliases import (
    canonicalize_harness,
    is_claude_sdk_harness_name,
    is_native_harness,
)
from omnigent.server.auth import LEVEL_OWNER, RESERVED_USER_LOCAL
from omnigent.server.host_registry import HostConnection
from omnigent.server.routes.sessions import announce_projects_changed, ensure_runner_connected
from omnigent.server.server_plugins import ServerServices
from omnigent.spec.types import AgentSpec
from omnigent.stores.conversation_store import (
    ARCHIVED_AT_LABEL_KEY,
    ConversationAlreadyExistsError,
    ConversationNotFoundError,
    NameAlreadyExistsError,
)
from omnigent.util.session_lifecycle import (
    CLOSED_LABEL_KEY,
    CLOSED_LABEL_VALUE,
    PARENT_WAKE_LABEL_KEY,
    PARENT_WAKE_OFF_VALUE,
)
from omnigent.util.uuid import InvalidUuidError, uuid_to_bytes

_logger = logging.getLogger(__name__)

ANCHOR_AGENT_NAME = f"{ENGINE_PREFIX}{Stance.ANCHOR.value}"
CORAL_RUNS_PROJECT_NAME = "Coral runs"
RUN_ID_LABEL_KEY = "coral.run_id"
ROLE_LABEL_KEY = "coral.role"
NODE_ID_LABEL_KEY = "coral.node_id"
# Characters of the session id a step title ends with, so a title cannot be taken in advance.
TITLE_ID_SUFFIX_CHARS = 6
_HOST_UNREACHABLE = frozenset(
    {ErrorCode.CONFLICT, ErrorCode.WRONG_REPLICA, ErrorCode.HOST_OFFLINE}
)
_REVOKED = frozenset({ErrorCode.UNAUTHORIZED, ErrorCode.FORBIDDEN})


class StepLauncher(Protocol):
    """Starts a written step session's runner and its session-init handshake."""

    async def launch(
        self, conv: Conversation, *, user_id: str | None, suppress_recovery_turn: bool = False
    ) -> str | None:
        """
        Launch ``conv``'s runner on its host and wait until it is initialized.

        The caller is inside the run owner's host scope.

        :param suppress_recovery_turn: The runner must not resume a turn from the
            session's history on its own: the caller prompts it.
        :returns: The runner the session is on afterwards, when known.
        :raises CoralSessionError: A typed ``session.*`` failure.
        """
        ...


class SlotGenerations(Protocol):
    """Reads a slot's current session generation, as the drainer's fence does."""

    def get_slot_generation(
        self, run_id: str, slot_id: str, *, workspace_id: int | None = None
    ) -> int | None: ...


class _StepIdentity(Protocol):
    """Who a step's launch acts as, and for which slot: a create's request, or a stored run."""

    @property
    def workspace_id(self) -> int: ...

    @property
    def run_id(self) -> str: ...

    @property
    def user_id(self) -> str | None: ...

    @property
    def account_generation(self) -> str | None: ...

    @property
    def host_id(self) -> str | None: ...

    @property
    def engine_slot_id(self) -> str | None: ...

    @property
    def generation(self) -> int: ...


@dataclass(frozen=True)
class _StoredStep:
    """A bound step's identity, taken from its stored run and binding."""

    workspace_id: int
    run_id: str
    user_id: str | None
    account_generation: str | None
    host_id: str | None
    engine_slot_id: str | None
    generation: int


@dataclass(frozen=True)
class _NewSession:
    """The conversation row a create writes."""

    kind: str
    title: str
    agent_id: str
    labels: dict[str, str]
    parent_id: str | None = None
    host_id: str | None = None
    workspace: str | None = None
    project_id: str | None = None
    reasoning_effort: str | None = None


def _refused(code: str, message: str, *, retryable: bool = False) -> CoralSessionError:
    return CoralSessionError(code, message, retryable=retryable)


def _session_id(request: SessionCreateRequest) -> str:
    if request.role == "anchor":
        return anchor_session_id(request.workspace_id, request.run_id)
    return effect_session_id(request.workspace_id, request.effect_key)


def _written(conv: Conversation, role: str) -> bool:
    """Whether the row's metadata was written; a torn row lacks its project or host."""
    return (conv.project_id if role == "anchor" else conv.host_id) is not None


def _has_no_metadata(conv: Conversation) -> bool:
    """A conversation row read without its metadata row: every metadata field is unset."""
    return (conv.host_id, conv.workspace, conv.project_id, conv.runner_id) == (
        None,
        None,
        None,
        None,
    )


def _step_title(base: str, session_id: str) -> str:
    """The step's title, ending with a short part of its session id, within Omnigent's limit."""
    suffix = f" · {session_id[:TITLE_ID_SUFFIX_CHARS]}"
    return base[: USER_SESSION_TITLE_MAX_CHARS - len(suffix)] + suffix


def session_state_of(session_id: str, conv: Conversation | None) -> SessionState:
    """The drift-relevant state of ``conv`` (``None`` when its row is gone)."""
    if conv is None:
        return SessionState(
            session_id=session_id,
            exists=False,
            archived=False,
            archived_at=None,
            closed=False,
            runner_id=None,
            host_id=None,
        )
    return SessionState(
        session_id=session_id,
        exists=True,
        archived=conv.archived,
        archived_at=conv.labels.get(ARCHIVED_AT_LABEL_KEY),
        closed=conv.labels.get(CLOSED_LABEL_KEY) == CLOSED_LABEL_VALUE,
        runner_id=conv.runner_id,
        host_id=conv.host_id,
    )


def _role_label(request: SessionCreateRequest) -> str:
    if request.role == "anchor":
        return "run"
    return "orchestrator" if request.slot_role == "orchestrator" else "step"


def _host_failure(exc: HostAccessError) -> CoralSessionError:
    if exc.code == "host_offline":
        return _refused("session.host_offline", exc.message, retryable=True)
    return _refused("session.host_not_permitted", exc.message)


def require_coral_runner(conn: HostConnection, host_id: str) -> None:
    """
    Refuse a host whose live connection does not advertise Coral's runner token.

    Self-reported, so a compatibility gate only: the owner checks decide who may use it.

    :raises CoralSessionError: Permanent ``session.host_unsupported``.
    """
    if CORAL_RUNNER_TOKEN not in conn.hello.capabilities:
        raise _refused(
            "session.host_unsupported",
            f"host {host_id!r} cannot run Coral steps: update Coral on that host, "
            "or unset CORAL_DISABLE_HOST_ENTRY_POINTS",
        )


def _owner_failure(exc: OmnigentError, what: str) -> CoralSessionError:
    """A store refused a write for the run owner: revoked for good, or a typed refusal."""
    if exc.code in _REVOKED:
        return _refused("session.owner_revoked", f"the run owner's account can no longer {what}")
    return _refused("session.invalid", f"the server refused to {what}: {exc}")


def _launch_failure(exc: OmnigentError) -> CoralSessionError:
    """A refusal from the runner launch or its session-init handshake."""
    message = str(exc)
    if exc.code == ErrorCode.HARNESS_NOT_CONFIGURED:
        return _refused("session.harness_not_configured", message)
    if exc.code == ErrorCode.WORKSPACE_MISSING:
        return _refused("session.workspace_missing", message)
    if exc.code == ErrorCode.UNAUTHORIZED:
        return _refused("session.host_not_permitted", message)
    if exc.code == ErrorCode.SESSION_AGENT_MISSING:
        return _refused("session.agent_not_permitted", message)
    return _refused("session.runner_unavailable", message, retryable=True)


def _session_deleted(session_id: str) -> DriftDetected:
    return DriftDetected(DriftFinding("session_deleted", session_id, "deleted"))


class OmnigentStepLauncher(StepLauncher):
    """Launches a step's runner through Omnigent's host launch, as a user message would."""

    def __init__(self, app: Any, services: ServerServices) -> None:
        self._app = app
        self._services = services

    @override
    async def launch(
        self, conv: Conversation, *, user_id: str | None, suppress_recovery_turn: bool = False
    ) -> str | None:
        services = self._services
        if conv.host_id is None or services.host_store is None:
            raise _refused("session.invalid", f"step session {conv.id} has no host to launch on")
        try:
            target = await asyncio.to_thread(
                resolve_host_launch,
                user_id=omnigent_owner(user_id),
                host_id=conv.host_id,
                session_id=conv.id,
                host_store=services.host_store,
                host_registry=services.host_registry,
                conversation_store=services.conversation_store,
                # The grants went to the run owner; with auth off nobody is checked.
                permission_store=(
                    services.permission_store if services.auth_provider is not None else None
                ),
                conversation=conv,
                sandbox_profiles=getattr(self._app.state, "sandbox_profiles", None),
            )
        except HTTPException:
            # A 404 also means the session row is gone.
            current = await asyncio.to_thread(
                services.conversation_store.get_conversation, conv.id
            )
            if current is None:
                raise _session_deleted(conv.id) from None
            raise _refused(
                "session.host_not_permitted", f"host {conv.host_id!r} may not run this session"
            ) from None
        except OmnigentError as exc:
            if exc.code in _HOST_UNREACHABLE:
                raise _refused("session.host_offline", str(exc), retryable=True) from exc
            raise _refused("session.host_not_permitted", str(exc)) from exc
        try:
            runner_client, current = await ensure_runner_connected(
                session_id=conv.id,
                conv=target.conv,
                app_state=self._app.state,
                conversation_store=services.conversation_store,
                runner_router=services.runner_router,
                raise_host_refusal=True,
            )
            if runner_client is None:
                raise _refused(
                    "session.runner_unavailable",
                    f"no runner connected for step session {conv.id}",
                    retryable=True,
                )
            await _ensure_runner_session_initialized(
                conv.id,
                current,
                runner_client,
                services.conversation_store,
                initializer=getattr(self._app.state, "runner_session_initializer", None),
                suppress_recovery_turn=suppress_recovery_turn,
                require_success=True,
            )
        except OmnigentError as exc:
            raise _launch_failure(exc) from exc
        return current.runner_id


class OmnigentSessionFacade(SessionFacade):
    """
    The run's anchor and step sessions, created on this server without a request.

    Auth is on when the server has an auth provider; then every run must have an owner.

    :param bindings: Records how far each create got.
    :param launcher: Starts a step's runner; Omnigent's host launch by default.
    :param slot_generations: Each slot's current generation. Without it, a launch is
        not checked against its slot.
    :param dispatch: Stops the runner of a launch its slot left meanwhile; resolved at
        stop time, since the dispatch's relaunch path holds this facade.
    """

    def __init__(
        self,
        app: Any,
        services: ServerServices,
        bindings: SessionBindings,
        *,
        launcher: StepLauncher | None = None,
        slot_generations: SlotGenerations | None = None,
        dispatch: Callable[[], SessionDispatch] | None = None,
        claude_native_steps: bool = False,
    ) -> None:
        self._services = services
        self._bindings = bindings
        self._launcher = launcher or OmnigentStepLauncher(app, services)
        self._slot_generations = slot_generations
        self._dispatch = dispatch
        self._claude_native_steps = claude_native_steps
        self._auth_on = services.auth_provider is not None
        self._anchor_agent_lock = asyncio.Lock()
        self._anchor_agent_ids: dict[int, str] = {}

    @override
    async def create_session(
        self,
        request: SessionCreateRequest,
        *,
        ensure_lease: Callable[[], Awaitable[None]],
    ) -> SessionRef:
        if request.user_id is None and not ownerless_runs_allowed():
            raise _refused(
                "session.invalid",
                f"run {request.run_id} has no owner, and this server requires one",
            )
        with workspace_scope(request.workspace_id):
            return await self._create(request, ensure_lease)

    @override
    async def session_state(self, *, workspace_id: int, session_id: str) -> SessionState:
        with workspace_scope(workspace_id):
            conv = await asyncio.to_thread(
                self._services.conversation_store.get_conversation, session_id
            )
        return session_state_of(session_id, conv)

    async def _create(
        self, request: SessionCreateRequest, ensure_lease: Callable[[], Awaitable[None]]
    ) -> SessionRef:
        store = self._services.conversation_store
        session_id = _session_id(request)
        binding = await asyncio.to_thread(
            self._bindings.get, request.workspace_id, session_id, run_id=request.run_id
        )
        conv = await asyncio.to_thread(store.get_conversation, session_id)
        if (
            binding is not None
            and binding.progress == SessionBindingProgress.INITIALIZED
            and conv is not None
        ):
            return SessionRef(session_id=session_id, role=request.role, created=False)
        # A step reports its anchor's drift first: deleting the anchor deletes its steps too.
        anchor = await self._live_anchor(request) if request.role == "step" else None
        self._refuse_drifted(request, session_id, binding, conv)
        if anchor is None:
            new = await self._anchor_row(request)
        else:
            new = await self._step_row(request, session_id, anchor)
        binding = await self._reserve(request, session_id)
        if conv is not None:
            if binding.progress == SessionBindingProgress.RESERVED and not _written(
                conv, request.role
            ):
                await self._require_torn(request, session_id, conv, new)
                _logger.warning("Repairing the torn row of Coral session %s", session_id)
                await ensure_lease()
                await store.delete_conversation(session_id)
                conv = None
            else:
                await self._require_match(request, session_id, conv, new)
        created = False
        if conv is None:
            await ensure_lease()
            conv, created = await self._write_row(request, session_id, new)
        await asyncio.to_thread(
            self._bindings.record_progress,
            request.workspace_id,
            session_id,
            SessionBindingProgress.ROW_CREATED,
        )
        await self._grant_owner(request.user_id, session_id)
        _announce_session_added(request.user_id, session_id)
        if request.role == "step":
            await self._launch(request, conv, ensure_lease)
        await asyncio.to_thread(
            self._bindings.record_progress,
            request.workspace_id,
            session_id,
            SessionBindingProgress.INITIALIZED,
        )
        return SessionRef(session_id=session_id, role=request.role, created=created)

    def _refuse_drifted(
        self,
        request: SessionCreateRequest,
        session_id: str,
        binding: SessionBinding | None,
        conv: Conversation | None,
    ) -> None:
        """
        Refuse a session the user deleted or drifted after its row existed.

        :raises DriftDetected: A row gone after ``row_created``; a written step row
            archived; a written anchor row archived or bound.
        :raises CoralSessionError: ``session.identity_conflict`` for a row this
            run holds no binding for; it is never adopted or deleted.
        """
        if conv is None:
            if binding is not None and binding.progress >= SessionBindingProgress.ROW_CREATED:
                if request.role == "anchor":
                    raise DriftDetected(DriftFinding("anchor_deleted", session_id, "deleted"))
                raise _session_deleted(session_id)
            return
        if binding is None:
            raise _refused(
                "session.identity_conflict",
                f"session {session_id} exists, but this run never reserved it",
            )
        if _written(conv, request.role):
            classify = classify_anchor if request.role == "anchor" else classify_step
            finding = classify(session_state_of(session_id, conv))
            if finding is not None:
                raise DriftDetected(finding)

    # ── Anchor ──────────────────────────────────────────────────────────

    async def _anchor_row(self, request: SessionCreateRequest) -> _NewSession:
        return _NewSession(
            kind="default",
            title=request.title[:USER_SESSION_TITLE_MAX_CHARS],
            agent_id=await self._anchor_agent(request.workspace_id),
            labels={RUN_ID_LABEL_KEY: request.run_id, ROLE_LABEL_KEY: _role_label(request)},
            project_id=await self._coral_runs_project(request.workspace_id, request.user_id),
        )

    async def _anchor_agent(self, workspace_id: int) -> str:
        """The hidden anchor agent, seeded on this process's first anchor; Coral never runs it."""
        async with self._anchor_agent_lock:
            agent_id = self._anchor_agent_ids.get(workspace_id)
            if agent_id is None:
                agent_id = await asyncio.to_thread(self._seed_anchor_agent)
                self._anchor_agent_ids[workspace_id] = agent_id
            return agent_id

    def _seed_anchor_agent(self) -> str:
        services = self._services
        bundle = pack_bundle(build_seed_bundle_yaml(Stance.ANCHOR))
        for attempt in range(2):
            try:
                _ensure_builtin_agent(
                    services.agent_store,
                    services.artifact_store,
                    services.agent_cache,
                    name=ANCHOR_AGENT_NAME,
                    bundle_bytes=bundle,
                )
                break
            except IntegrityError:
                # Another server seeded the row first; the second pass finds it.
                if attempt:
                    raise _refused(
                        "session.store_conflict",
                        "the Coral anchor agent could not be stored",
                        retryable=True,
                    ) from None
        agent = services.agent_store.get_by_name(ANCHOR_AGENT_NAME)
        if agent is None:
            raise _refused("session.invalid", "the Coral anchor agent could not be stored")
        return agent.id

    async def _coral_runs_project(self, workspace_id: int, owner: str | None) -> str:
        """The owner's "Coral runs" project, created once under a derived id."""
        project_store = self._services.project_store
        if project_store is None:
            raise _refused("session.invalid", "this server keeps no projects for Coral runs")
        project_id = derived_id("coral-runs-project", str(workspace_id), owner or "")

        def ensure() -> tuple[str, bool]:
            # A renamed project keeps its id, so it stays the runs folder.
            found = project_store.get(project_id, user_id=owner)
            if found is not None:
                return found.id, False
            try:
                return project_store.create(project_id, CORAL_RUNS_PROJECT_NAME, owner).id, True
            except IntegrityError:
                raced = project_store.get(project_id, user_id=owner)
                if raced is None:
                    raise _refused(
                        "session.store_conflict",
                        "the Coral runs project could not be stored",
                        retryable=True,
                    ) from None
                return raced.id, False
            except OmnigentError as exc:
                if exc.code != ErrorCode.ALREADY_EXISTS:
                    raise _owner_failure(exc, "keep a Coral runs project") from exc
                for project in project_store.list(user_id=owner):
                    if project.name == CORAL_RUNS_PROJECT_NAME:
                        return project.id, False
                raise _refused(
                    "session.store_conflict",
                    "the Coral runs project was renamed while it was looked up",
                    retryable=True,
                ) from exc

        found_id, created = await asyncio.to_thread(ensure)
        if created:
            announce_projects_changed(owner)
        return found_id

    # ── Step ────────────────────────────────────────────────────────────

    async def _step_row(
        self, request: SessionCreateRequest, session_id: str, anchor: Conversation
    ) -> _NewSession:
        """Check everything a step needs before anything is written, and build its row."""
        if not (
            request.agent_id
            and request.engine_slot_id
            and request.slot_role
            and request.host_id
            and request.workspace
        ):
            raise _refused(
                "session.invalid",
                "a step needs an agent, an engine slot, a slot role, a host and a workspace",
            )
        owner_host = await self._owner_host(request)
        agent = await self._permitted_agent(request)
        services = self._services
        try:
            harness = await asyncio.to_thread(
                _create_resolved_harness, agent, None, services.agent_cache
            )
        except OmnigentError:
            raise _bad_spec(agent.id) from None
        canonical = canonicalize_harness(harness) or harness
        native_step_ok = (
            self._claude_native_steps
            and canonical == "claude-native"
            and request.slot_role != "orchestrator"
        )
        if harness is None or (is_native_harness(harness) and not native_step_ok):
            raise _refused(
                "session.harness_not_supported",
                f"agent {agent.id} runs on {harness or 'an unknown harness'}; "
                "Coral steps need a headless harness"
                if not self._claude_native_steps
                else "Claude-native is only for steps when claude_native_steps is on",
            )
        spec = await self._loaded_spec(agent)
        _require_coral_bundle(agent.id, spec, harness, request.slot_role)
        reasoning_effort = _spec_effort(spec)
        with owner_host.owner_scope():
            workspace = await self._canonical_workspace(request, agent)
            await self._harness_ready(request, harness, anchor)
        labels = {
            RUN_ID_LABEL_KEY: request.run_id,
            ROLE_LABEL_KEY: _role_label(request),
            PARENT_WAKE_LABEL_KEY: PARENT_WAKE_OFF_VALUE,
            # The terminal-view label POST /v1/sessions stamps on a host-launched REPL session.
            **await asyncio.to_thread(
                _repl_terminal_ui_labels,
                agent=agent,
                agent_cache=services.agent_cache,
                harness_override=None,
            ),
        }
        if request.node_id is not None:
            labels[NODE_ID_LABEL_KEY] = request.node_id
        return _NewSession(
            kind="sub_agent",
            title=_step_title(request.title, session_id),
            agent_id=agent.id,
            labels=labels,
            parent_id=anchor.id,
            host_id=request.host_id,
            workspace=workspace,
            reasoning_effort=reasoning_effort,
        )

    async def _live_anchor(self, request: _StepIdentity) -> Conversation:
        """
        The run's anchor, created and not drifted.

        :raises CoralSessionError: ``session.anchor_missing`` (retryable) while
            the anchor's own create has not finished.
        :raises DriftDetected: When the anchor was deleted, archived or bound.
        """
        anchor_id = anchor_session_id(request.workspace_id, request.run_id)
        binding = await asyncio.to_thread(
            self._bindings.get, request.workspace_id, anchor_id, run_id=request.run_id
        )
        conv = await asyncio.to_thread(
            self._services.conversation_store.get_conversation, anchor_id
        )
        written = binding is not None and binding.progress >= SessionBindingProgress.ROW_CREATED
        if conv is None and written:
            raise DriftDetected(DriftFinding("anchor_deleted", anchor_id, "deleted"))
        if (
            conv is None
            or binding is None
            or binding.progress < SessionBindingProgress.INITIALIZED
        ):
            raise _refused(
                "session.anchor_missing",
                f"run {request.run_id}'s anchor session is not created yet",
                retryable=True,
            )
        finding = classify_anchor(session_state_of(anchor_id, conv))
        if finding is not None:
            raise DriftDetected(finding)
        return conv

    async def _owner_host(self, request: _StepIdentity) -> OwnerHost:
        """
        The run owner's live host: authorized from its stored row, then its connection
        and its Coral token.
        """
        services = self._services
        host_id = request.host_id
        if services.host_store is None or services.host_registry is None or not host_id:
            raise _refused("session.invalid", "this server reaches no hosts")
        try:
            await authorize_owner_host(
                host_store=services.host_store,
                user_id=request.user_id,
                account_generation=request.account_generation,
                host_id=host_id,
                workspace_id=request.workspace_id,
            )
            owner_host = OwnerHost(
                host_registry=services.host_registry,
                host_id=host_id,
                workspace_id=request.workspace_id,
                user_id=request.user_id,
                account_generation=request.account_generation,
            )
            conn = owner_host.connection()
        except HostAccessError as exc:
            raise _host_failure(exc) from exc
        require_coral_runner(conn, host_id)
        return owner_host

    async def _permitted_agent(self, request: SessionCreateRequest) -> Any:
        """
        The step's agent, if the server or the run owner authored it.

        An ownerless run's own agents are its server's local user's on a single-user
        server, as Omnigent reads them (:func:`omnigent_owner`).

        Never a copy of another user's agent (the facade does not mint one), and
        never the run anchor's agent.
        """
        services = self._services
        agent_id = request.agent_id or ""
        try:
            # The store raises an untyped error for an id that is not a uuid.
            uuid_to_bytes(agent_id)
        except InvalidUuidError:
            raise _agent_not_permitted(agent_id) from None
        agent = await asyncio.to_thread(services.agent_store.get, agent_id)
        if (
            agent is None
            or agent.name.lower() == ANCHOR_AGENT_NAME
            or not (agent.operator_authored or agent.created_by == omnigent_owner(request.user_id))
        ):
            raise _agent_not_permitted(agent_id)
        try:
            await validate_session_agent(
                user_id=request.user_id,
                agent_id=agent_id,
                agent_store=services.agent_store,
                permission_store=services.permission_store if self._auth_on else None,
                conversation_store=services.conversation_store,
            )
        except (OmnigentError, HTTPException):
            raise _agent_not_permitted(agent_id) from None
        return agent

    async def _loaded_spec(self, agent: Any) -> AgentSpec:
        """The agent's stored spec, loaded as POST /v1/sessions loads it."""
        agent_cache = self._services.agent_cache
        try:
            loaded = await asyncio.to_thread(
                agent_cache.load,
                agent.id,
                agent.bundle_location,
                expand_env=agent.operator_authored,
            )
        except (
            OmnigentError,
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
            AttributeError,
            ImportError,
        ):
            raise _bad_spec(agent.id) from None
        return loaded.spec

    async def _canonical_workspace(self, request: SessionCreateRequest, agent: Any) -> str:
        services = self._services
        try:
            return await validate_existing_host_workspace(
                user_id=omnigent_owner(request.user_id),
                host_id=request.host_id or "",
                workspace=request.workspace,
                agent=agent,
                agent_cache=services.agent_cache,
                host_store=services.host_store,
                host_registry=services.host_registry,
            )
        except HTTPException:
            raise _refused(
                "session.host_not_permitted", f"host {request.host_id!r} may not run this session"
            ) from None
        except OmnigentError as exc:
            if exc.code in _HOST_UNREACHABLE:
                raise _refused("session.host_offline", str(exc), retryable=True) from exc
            if exc.code != ErrorCode.INVALID_INPUT:
                raise _refused("session.invalid", str(exc)) from exc
            # Validation reports a missing path, a slow or lost host and a host-side
            # error alike, so ask the host again before calling it permanent.
            raise await self._workspace_failure(request, str(exc)) from exc

    async def _workspace_failure(
        self, request: SessionCreateRequest, message: str
    ) -> CoralSessionError:
        """Only a workspace the host confirms missing is permanent; any other failure retries."""
        services = self._services
        assert services.host_store is not None and request.host_id and request.workspace
        try:
            run_host = await connect_run_worktree_host(
                host_registry=services.host_registry,
                host_store=services.host_store,
                user_id=request.user_id,
                account_generation=request.account_generation,
                host_id=request.host_id,
                workspace_id=request.workspace_id,
            )
            stat = await run_host.stat(request.workspace)
        except RunWorktreeError as exc:
            if exc.code == "host_offline":
                return _refused("session.host_offline", exc.message, retryable=True)
            if exc.code == "not_permitted":
                return _refused("session.host_not_permitted", exc.message)
            return _refused("session.workspace_unverified", exc.message, retryable=True)
        if not (stat.exists and stat.is_directory):
            return _refused("session.workspace_missing", message)
        return _refused("session.workspace_unverified", message, retryable=True)

    async def _harness_ready(
        self, request: SessionCreateRequest, harness: str, anchor: Conversation
    ) -> None:
        services = self._services
        try:
            await validate_create_harness_readiness(
                harness=harness,
                host_id=request.host_id,
                parent_session_id=anchor.id,
                inherited_runner_id=None,
                user_id=omnigent_owner(request.user_id),
                conversation_store=services.conversation_store,
                host_store=services.host_store,
                parent=anchor,
            )
        except HTTPException:
            raise _refused(
                "session.host_not_permitted", f"host {request.host_id!r} may not run this session"
            ) from None
        except OmnigentError as exc:
            if exc.code == ErrorCode.HARNESS_NOT_CONFIGURED:
                raise _refused("session.harness_not_configured", str(exc)) from exc
            raise _refused("session.invalid", str(exc)) from exc

    async def _launch(
        self,
        request: _StepIdentity,
        conv: Conversation,
        ensure_lease: Callable[[], Awaitable[None]],
        *,
        relaunch: bool = False,
    ) -> str | None:
        """
        Launch the step, checking its anchor, its own row and its host again first.

        A slot that left the launch's generation meanwhile gets no live runner from it.

        :param relaunch: The step is brought back after a lost runner: Coral prompts it,
            so the runner must not resume a turn from its history on its own.
        :returns: The runner the launch left the session on, when the launcher knows it.
        :raises SlotSuperseded: The slot is at another generation after the launch; the
            session is labelled closed and its runner stopped first.
        """
        await self._live_anchor(request)
        current = await asyncio.to_thread(
            self._services.conversation_store.get_conversation, conv.id
        )
        finding = classify_step(session_state_of(conv.id, current))
        if finding is not None:
            raise DriftDetected(finding)
        assert current is not None
        owner_host = await self._owner_host(request)
        await ensure_lease()
        with owner_host.owner_scope():
            if relaunch:
                launched = await self._launcher.launch(
                    current, user_id=request.user_id, suppress_recovery_turn=True
                )
            else:
                launched = await self._launcher.launch(current, user_id=request.user_id)
        if await self._slot_moved(request):
            await self._retire(request, conv.id)
            raise SlotSuperseded(
                f"step session {conv.id}'s slot moved past generation {request.generation} "
                "while it launched"
            )
        return launched

    async def _slot_moved(self, request: _StepIdentity) -> bool:
        """Whether the step's slot is at another generation; a slot with no row is not."""
        if self._slot_generations is None or request.engine_slot_id is None:
            return False
        current = await asyncio.to_thread(
            self._slot_generations.get_slot_generation,
            request.run_id,
            store_slot_id(request.run_id, request.engine_slot_id),
            workspace_id=request.workspace_id,
        )
        return current is not None and current != request.generation

    async def _retire(self, request: _StepIdentity, session_id: str) -> None:
        """
        Close a superseded step to new messages and stop its runner, each best effort.

        One failing never skips the other: the caller abandons the row either way.
        """
        try:
            await asyncio.to_thread(
                self._services.conversation_store.set_labels,
                session_id,
                {CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE},
            )
        except Exception as exc:  # noqa: BLE001 -- logged; the stop still runs
            _logger.warning(
                "Coral could not close superseded step session %s: %s",
                session_id,
                type(exc).__name__,
            )
        if self._dispatch is None:
            return
        try:
            await self._dispatch().stop(session_id=session_id, user_id=request.user_id)
        except Exception as exc:  # noqa: BLE001 -- logged; an idle runner may linger
            code = exc.code if isinstance(exc, CoralSessionError) else type(exc).__name__
            _logger.warning(
                "Coral could not stop superseded step session %s: %s", session_id, code
            )

    # ── Writes ──────────────────────────────────────────────────────────

    async def _reserve(self, request: SessionCreateRequest, session_id: str) -> SessionBinding:
        step = request.role == "step"
        draft = SessionBindingDraft(
            workspace_id=request.workspace_id,
            session_id=session_id,
            run_id=request.run_id,
            role=request.role,
            effect_key=request.effect_key,
            slot_id=request.engine_slot_id if step else None,
            slot_role=request.slot_role if step else None,
            session_generation=request.generation if step else 1,
            host_id=request.host_id if step else None,
        )
        try:
            return await asyncio.to_thread(self._bindings.reserve, draft)
        except BindingConflict as exc:
            # The store's message names only this session and its own slot and generation.
            raise _refused("session.binding_conflict", str(exc)) from exc

    async def _require_torn(
        self, request: SessionCreateRequest, session_id: str, conv: Conversation, new: _NewSession
    ) -> None:
        """
        Allow the torn-row repair only for this create's own unfinished, unused row.

        :raises CoralSessionError: ``session.identity_conflict`` for any other row.
        """
        store = self._services.conversation_store
        children = await asyncio.to_thread(
            store.list_child_conversation_ids_by_parent, [session_id]
        )
        items = await asyncio.to_thread(store.list_items, session_id, limit=1)
        differs = [
            name
            for name, unused in (
                ("metadata", _has_no_metadata(conv)),
                ("parent", conv.parent_conversation_id == new.parent_id),
                ("agent", conv.agent_id == new.agent_id),
                ("run", conv.labels.get(RUN_ID_LABEL_KEY) == request.run_id),
                ("role", conv.labels.get(ROLE_LABEL_KEY) == new.labels[ROLE_LABEL_KEY]),
                ("children", not children.get(session_id)),
                ("items", not items.data),
            )
            if not unused
        ]
        if differs:
            raise _refused(
                "session.identity_conflict",
                f"session {session_id} is not this run's unfinished create "
                f"({', '.join(differs)}); it is left as it is",
            )

    async def _require_match(
        self, request: SessionCreateRequest, session_id: str, conv: Conversation, new: _NewSession
    ) -> None:
        """
        Adopt an existing row only when it is the session this create would write.

        :raises CoralSessionError: ``session.identity_conflict`` before any grant or launch.
        """
        differs = [
            name
            for name, (stored, wanted) in (
                ("kind", (conv.kind, new.kind)),
                ("parent", (conv.parent_conversation_id, new.parent_id)),
                ("host", (conv.host_id, new.host_id)),
                ("workspace", (conv.workspace, new.workspace)),
                ("agent", (conv.agent_id, new.agent_id)),
                ("run", (conv.labels.get(RUN_ID_LABEL_KEY), request.run_id)),
            )
            if stored != wanted
        ]
        if await self._owned_by_another(session_id, request.user_id):
            differs.append("owner")
        if differs:
            raise _refused(
                "session.identity_conflict",
                f"session {session_id} exists with a different {', '.join(differs)}",
            )

    async def _owned_by_another(self, session_id: str, user_id: str | None) -> bool:
        permission_store = self._services.permission_store
        if permission_store is None:
            return False
        grants, _ = await asyncio.to_thread(permission_store.list_for_session, session_id)
        owner = omnigent_owner(user_id)
        return any(grant.level >= LEVEL_OWNER and grant.user_id != owner for grant in grants)

    async def _write_row(
        self, request: SessionCreateRequest, session_id: str, new: _NewSession
    ) -> tuple[Conversation, bool]:
        """Write the row, or adopt the one with this id. ``True`` when this call wrote it."""
        store = self._services.conversation_store
        try:
            conv = await asyncio.to_thread(
                store.create_conversation,
                conversation_id=session_id,
                kind=new.kind,
                title=new.title,
                parent_conversation_id=new.parent_id,
                agent_id=new.agent_id,
                runner_id=None,
                host_id=new.host_id,
                workspace=new.workspace,
                git_branch=None,
                project_id=new.project_id,
                labels=new.labels,
                reasoning_effort=new.reasoning_effort,
            )
        except (ConversationAlreadyExistsError, NameAlreadyExistsError):
            existing = await asyncio.to_thread(store.get_conversation, session_id)
            if existing is None:
                raise _refused(
                    "session.title_conflict",
                    f"another session under the run's anchor is titled {new.title!r}",
                ) from None
            if not _written(existing, request.role):
                # Written by a concurrent try that has not finished; the next delivery repairs it.
                raise _refused(
                    "session.row_incomplete",
                    f"session {session_id} is still being written",
                    retryable=True,
                ) from None
            await self._require_match(request, session_id, existing, new)
            return existing, False
        except ConversationNotFoundError:
            # The anchor went away while the step was written.
            await self._live_anchor(request)
            raise _refused(
                "session.anchor_missing",
                f"run {request.run_id}'s anchor session is not available",
                retryable=True,
            ) from None
        except OmnigentError as exc:
            if exc.code in _REVOKED:
                raise _owner_failure(exc, "own sessions") from exc
            # The host is being deleted, or a stale metadata row names another host.
            raise _refused("session.host_offline", str(exc), retryable=True) from exc
        return conv, True

    async def _grant_owner(self, user_id: str | None, session_id: str) -> None:
        """The owner grant, before any launch; never a public one."""
        permission_store = self._services.permission_store
        if permission_store is None:
            return
        owner = omnigent_owner(user_id)
        if owner is None:
            raise _refused("session.invalid", "the run has no owner, and this server requires one")
        try:
            if user_id is None:
                # The local user owns it. A real owner's row is never recreated.
                await asyncio.to_thread(permission_store.ensure_user, RESERVED_USER_LOCAL)
            await asyncio.to_thread(permission_store.grant, owner, session_id, LEVEL_OWNER)
        except OmnigentError as exc:
            raise _owner_failure(exc, "own sessions") from exc


# Host answers that mean the old runner may still be working: it is not superseded.
_RUNNER_ALIVE = frozenset({"alive", "sign_in_pending"})
# The only host answers that let a relaunch stop the old runner: it is gone, or the host
# lost track of it, which counts as gone. Any other answer is no answer.
_RUNNER_GONE = frozenset({"dead", "unknown"})


async def _no_lease() -> None:
    return None


def _same_host(left: str | None, right: str | None) -> bool:
    """Whether two host ids name one host, however each was spelled when stored."""
    return (
        left is not None
        and right is not None
        and canonical_host_id(left) == canonical_host_id(right)
    )


class _RunnerMoved(Exception):
    """The session's row names another runner than the one the host was asked about."""


class OmnigentStepRelauncher(StepRelauncher):
    """
    The relaunch path Coral's own paths use for a bound step's runner, in its own session.

    The binding names the run; the run row names the owner, account registration and
    host. Nothing is launched unless the binding is the step's at the asked generation,
    the slot is still at it, the session is open on its run's host, the owner's host is
    connected with the Coral token, and that host says the old runner is gone. Only that
    runner is then stopped (confirmed), and the facade's own launch sequence starts a new
    one, which resumes no turn from its history: Coral prompts it. A session closed or
    deleted, or a slot moved on, meanwhile gets no live runner. A launch that kept the
    old runner, because it came back, is reported ``connected``.

    :param dispatch: Stops the old runner; resolved at stop time, since the dispatch's
        relaunch path holds this relauncher.
    """

    def __init__(
        self,
        facade: OmnigentSessionFacade,
        services: ServerServices,
        bindings: SessionBindingLookup,
        run_store: RunStore,
        *,
        dispatch: Callable[[], SessionDispatch],
    ) -> None:
        self._facade = facade
        self._services = services
        self._bindings = bindings
        self._run_store = run_store
        self._dispatch = dispatch

    @override
    async def ensure_runner(
        self,
        *,
        workspace_id: int,
        session_id: str,
        generation: int,
        ensure_lease: Callable[[], Awaitable[None]] | None = None,
    ) -> RunnerRelaunch:
        with workspace_scope(workspace_id):
            return await self._ensure(
                workspace_id, session_id, generation, ensure_lease or _no_lease
            )

    async def _ensure(
        self,
        workspace_id: int,
        session_id: str,
        generation: int,
        ensure_lease: Callable[[], Awaitable[None]],
    ) -> RunnerRelaunch:
        step = await self._bound_step(workspace_id, session_id, generation)
        store = self._services.conversation_store
        conv = self._open_on_its_host(
            step, session_id, await asyncio.to_thread(store.get_conversation, session_id)
        )
        if await self._connected(conv):
            return "connected"
        if await self._facade._slot_moved(step):
            raise SlotSuperseded(f"step session {session_id}'s slot moved past {generation}")
        owner_host = await self._facade._owner_host(step)
        try:
            await self._stop_lost_runner(step, owner_host, conv, ensure_lease)
        except _RunnerMoved:
            current = await asyncio.to_thread(store.get_conversation, session_id)
            if current is not None and await self._connected(current):
                return "connected"
            raise _refused(
                "session.runner_changed",
                f"step session {session_id} moved to another runner while Coral relaunched it",
                retryable=True,
            ) from None
        launched = await self._facade._launch(step, conv, ensure_lease, relaunch=True)
        after = await asyncio.to_thread(store.get_conversation, session_id)
        if after is None:
            await self._stop_launched(step, owner_host, session_id, launched)
            raise _session_deleted(session_id)
        if session_state_of(session_id, after).closed:
            # Closed while it launched: the new runner must not take any message.
            await self._stop_launched(step, owner_host, session_id, launched or after.runner_id)
            raise _refused("session.closed", f"step session {session_id} closed while it launched")
        if conv.runner_id is not None and after.runner_id == conv.runner_id:
            # The old runner came back during the launch, which kept it.
            _logger.info("Coral found step session %s's runner back while relaunching", session_id)
            return "connected"
        _logger.info("Coral relaunched the runner of step session %s", session_id)
        return "relaunched"

    async def _connected(self, conv: Conversation) -> bool:
        client = await _get_runner_client(conv.id, self._services.runner_router, conversation=conv)
        return client is not None

    async def _bound_step(
        self, workspace_id: int, session_id: str, generation: int
    ) -> _StoredStep:
        """
        The step's identity from its binding and its stored run.

        :raises CoralSessionError: Permanent ``session.not_bound`` unless the session
            is a step whose create finished at ``generation``, of a run that exists.
        """
        binding = await asyncio.to_thread(self._bindings.find_by_session, workspace_id, session_id)
        if (
            binding is None
            or binding.role is not SessionBindingRole.STEP
            or binding.progress != SessionBindingProgress.INITIALIZED
            or binding.session_generation != generation
        ):
            raise _refused(
                "session.not_bound",
                f"session {session_id} is not a started step at generation {generation}",
            )
        try:
            state, _version = await asyncio.to_thread(
                self._run_store.load_run_state, binding.run_id, workspace_id=workspace_id
            )
        except RunNotFound:
            raise _refused(
                "session.not_bound", f"session {session_id}'s run no longer exists"
            ) from None
        if not _same_host(binding.host_id, state.spec.host_id):
            raise _host_not_permitted(session_id)
        return _StoredStep(
            workspace_id=workspace_id,
            run_id=binding.run_id,
            user_id=state.run.user_id,
            account_generation=state.run.account_generation,
            host_id=state.spec.host_id,
            engine_slot_id=binding.slot_id,
            generation=generation,
        )

    @staticmethod
    def _open_on_its_host(
        step: _StoredStep, session_id: str, conv: Conversation | None
    ) -> Conversation:
        """
        The session's row, open and on its run's host.

        :raises DriftDetected: The row is gone or archived.
        :raises CoralSessionError: Permanent ``session.closed``, or
            ``session.host_not_permitted`` for a row on another host.
        """
        finding = classify_step(session_state_of(session_id, conv))
        if finding is not None:
            raise DriftDetected(finding)
        assert conv is not None
        if session_state_of(session_id, conv).closed:
            raise _refused("session.closed", f"step session {session_id} is closed")
        if not _same_host(conv.host_id, step.host_id):
            raise _host_not_permitted(session_id)
        return conv

    async def _stop_lost_runner(
        self,
        step: _StoredStep,
        owner_host: OwnerHost,
        conv: Conversation,
        ensure_lease: Callable[[], Awaitable[None]],
    ) -> None:
        """
        Ask the host about the old runner, then stop it, confirmed, before any launch.

        Only ``dead`` and ``unknown`` (the host lost track of it, which counts as dead)
        let the stop go ahead, and only while the row still names that runner: a runner
        another launch started meanwhile is never stopped.

        :raises CoralSessionError: Retryable ``recovery.runner_alive`` while the host
            says the runner lives, ``session.runner_status_unknown`` for no answer or any
            other answer, or the stop's own refusal (``dispatch.stop_unconfirmed``).
        :raises DriftDetected: The row is gone.
        :raises _RunnerMoved: The row names another runner by the time of the stop.
        """
        with owner_host.owner_scope():
            if conv.runner_id is not None:
                try:
                    conn = owner_host.connection()
                except HostAccessError as exc:
                    raise _host_failure(exc) from exc
                status = await _query_host_runner_status(
                    conn, owner_host.host_registry, conv.runner_id
                )
                if status in _RUNNER_ALIVE:
                    raise _refused(
                        RUNNER_ALIVE_HOLD,
                        f"step session {conv.id}'s runner is alive but not connected",
                        retryable=True,
                    )
                if status not in _RUNNER_GONE:
                    raise _refused(
                        "session.runner_status_unknown",
                        f"host {step.host_id!r} did not say that step session {conv.id}'s "
                        "runner is gone",
                        retryable=True,
                    )
                if status == "unknown":
                    _logger.info(
                        "Coral relaunches step session %s: its host no longer knows the "
                        "old runner",
                        conv.id,
                    )
            await ensure_lease()
            current = await asyncio.to_thread(
                self._services.conversation_store.get_conversation, conv.id
            )
            if current is None:
                raise _session_deleted(conv.id)
            if current.runner_id != conv.runner_id:
                raise _RunnerMoved(conv.id)
            await self._dispatch().stop(session_id=conv.id, user_id=step.user_id)

    async def _stop_launched(
        self, step: _StoredStep, owner_host: OwnerHost, session_id: str, runner_id: str | None
    ) -> None:
        """Stop the runner this relaunch started, by id through the host, best effort."""
        if runner_id is None or step.host_id is None:
            _logger.warning(
                "Coral cannot stop step session %s's new runner: its id is unknown", session_id
            )
            return
        try:
            with owner_host.owner_scope():
                stopped = await _stop_session_host_runner(
                    session_id, step.host_id, runner_id, owner_host.host_registry
                )
        except Exception as exc:  # noqa: BLE001 -- logged; the session refuses the runner
            stopped = False
            _logger.warning(
                "Coral could not stop step session %s's new runner: %s",
                session_id,
                type(exc).__name__,
            )
        if not stopped:
            _logger.warning(
                "Coral's stop of step session %s's new runner was not confirmed", session_id
            )


def _host_not_permitted(session_id: str) -> CoralSessionError:
    return _refused(
        "session.host_not_permitted", f"step session {session_id} is not on its run's host"
    )


def _agent_not_permitted(agent_id: str) -> CoralSessionError:
    return _refused(
        "session.agent_not_permitted", f"agent {agent_id} is not available to this run"
    )


def _bad_spec(agent_id: str) -> CoralSessionError:
    return _refused(
        "session.harness_not_supported",
        f"agent {agent_id}'s stored spec no longer loads, so its harness is unknown",
    )


def _require_coral_bundle(
    agent_id: str, spec: AgentSpec, harness: str, slot_role: str | None
) -> None:
    """
    Refuse an agent that is not a Coral step/orchestrator bundle whose stance fits the slot.

    Claude-sdk bundles keep the tool-policy hook. Claude-native step bundles
    (when ``claude_native_steps`` is on) use fail-closed native hooks instead.
    Orchestrators stay claude-sdk only.

    :raises CoralSessionError: ``session.agent_not_supported``, naming the first broken rule.
    """
    from omnigent.harness_aliases import canonicalize_harness

    # The stances the catalog offers this slot's engine tools to.
    wanted = frozenset({ORCHESTRATOR_STANCE}) if slot_role == "orchestrator" else STEP_STANCES
    stance = generated_stance(spec.params)
    canonical = canonicalize_harness(harness) or harness
    native_step = canonical == "claude-native" and slot_role != "orchestrator"
    if not is_claude_sdk_harness_name(harness) and not native_step:
        problem = f"it runs on {harness}, not claude-sdk"
    elif stance is None:
        problem = "it has no params.coral.generated.stance"
    elif stance not in wanted:
        problem = f"its stance is {stance[:64]!r}"
    else:
        try:
            check_hygiene(spec, Stance(stance))
        except StepBundleRejected as exc:
            problem = str(exc)
        else:
            return
    raise _refused(
        "session.agent_not_supported",
        f"agent {agent_id} is not a Coral {' or '.join(sorted(wanted))} bundle "
        f"for slot role {slot_role}: {problem}",
    )


def _spec_effort(spec: AgentSpec) -> str | None:
    """The spec's reasoning effort, validated as POST /v1/sessions does."""
    effort = spec.executor.reasoning_effort
    if effort is None:
        return None
    try:
        _, validated = validate_session_model_metadata(
            model_override=None, reasoning_effort=effort
        )
    except OmnigentError as exc:
        raise _refused("session.invalid", str(exc)) from exc
    return validated


__all__ = [
    "ANCHOR_AGENT_NAME",
    "CORAL_RUNS_PROJECT_NAME",
    "NODE_ID_LABEL_KEY",
    "ROLE_LABEL_KEY",
    "RUN_ID_LABEL_KEY",
    "TITLE_ID_SUFFIX_CHARS",
    "OmnigentSessionFacade",
    "OmnigentStepLauncher",
    "OmnigentStepRelauncher",
    "SlotGenerations",
    "StepLauncher",
    "require_coral_runner",
    "session_state_of",
]
