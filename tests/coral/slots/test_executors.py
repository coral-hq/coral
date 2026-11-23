"""The session executors: payload, run identity and scopes, failure mapping, drift, conformance."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from coral.db.enum_codecs import (
    LogKind,
    RunPauseReason,
    RunStatus,
    SessionBindingProgress,
    SlotRole,
    StableIdKind,
)
from coral.model.ids import (
    anchor_session_id,
    derived_id,
    effect_message_id,
    effect_op_key,
    effect_session_id,
)
from coral.omni.protocols import CoralSessionError, engine_message_text
from coral.queue.conformance import run_executor_conformance
from coral.queue.executors import EffectCompleted, EffectFailed, StartupLeaseLost
from coral.recovery.drift import DriftDetected, DriftFinding, DriftPauser
from coral.slots.executors import (
    CANCEL_SESSIONS,
    CLOSE_SLOT,
    CREATE_SESSION,
    MAX_ENGINE_MESSAGE_BYTES,
    SEND_INPUT,
    cancel_sessions_executor,
    close_slot_executor,
    create_session_executor,
    send_input_executor,
)
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun, Transition
from coral.stores.stable_ids import content_checksum
from tests.coral.omni.fakes import FakeSessionFacade
from tests.coral.slots._close_fakes import FakeDispatch, FakeEdgeWatcher, FakeStableIds
from tests.coral.workspace._executor_fakes import (
    FakeBindings,
    FakeChannels,
    FakeHostChannel,
    FakeIntents,
    RecordingScopeRunner,
    Reply,
    add_slot,
    effect_context,
    start_run,
    step_binding,
)

WORKSPACE = 4
OWNER = "alice"
GENERATION = "gen-1"
HOST = "h" * 32
WORKTREE = "/Users/alice/repo-worktrees/coral-r-base"
AGENT = "a" * 32
RESOLVED_AGENT = "b" * 32
NOW_US = 1_700_000_000_000_000


class _Agents:
    """A ``StepAgentResolver`` that records each call and its scope, then answers or refuses."""

    def __init__(self, scope: RecordingScopeRunner, error: BaseException | None = None) -> None:
        self.scope = scope
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def resolve(
        self,
        *,
        workspace_id: int,
        owner: str | None,
        stance: str,
        workflow_slug: str | None,
        node_id: str | None,
        roster_index: int | None,
        session_id: str | None = None,
        run_id: str | None = None,
        profile: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "owner": owner,
                "stance": stance,
                "workflow_slug": workflow_slug,
                "node_id": node_id,
                "roster_index": roster_index,
                "session_id": session_id,
                "run_id": run_id,
                "profile": profile,
                "scope": self.scope.active,
            }
        )
        if self.error is not None:
            raise self.error
        return RESOLVED_AGENT


class _Env:
    """A started run, the executor under test and its fakes."""

    def __init__(
        self,
        *,
        host_id: str | None = HOST,
        worktree_path: str | None = WORKTREE,
        refusal: BaseException | None = None,
        resolver: bool = False,
        resolver_error: BaseException | None = None,
    ) -> None:
        self.run_store = FakeRunStore(default_workspace_id=WORKSPACE)
        self.run: CoralRun = start_run(
            self.run_store,
            workspace_id=WORKSPACE,
            user_id=OWNER,
            account_generation=GENERATION,
            host_id=host_id,
            repo_path="/Users/alice/repo",
            worktree_path=worktree_path,
        )
        self.scope = RecordingScopeRunner()
        self.scopes_at_create: list[dict[str, object] | None] = []
        self.facade = FakeSessionFacade(
            refusal=refusal,
            on_create=lambda _request: self.scopes_at_create.append(self.scope.active),
        )
        self.agents = _Agents(self.scope, resolver_error) if resolver or resolver_error else None
        self.executor = create_session_executor(
            self.facade,
            self.run_store,
            DriftPauser(self.run_store, now_us=lambda: NOW_US),
            self.scope,
            agents=self.agents,
        )

    def key(self, subject: str = "slot-1") -> str:
        return f"{self.run.id}:7:create_session:{subject}"

    def stance_payload(self, **fields: object) -> dict[str, Any]:
        """A step create as the bridge maps it: the stance and step, no agent id."""
        payload = {
            "effect_type": CREATE_SESSION,
            "effect_key": self.key(),
            "engine_kind": "create_session",
            "role": "step",
            "stance": "implementer",
            "workflow_slug": "two-steps",
            "node_id": "implement",
            "roster_index": 0,
            "engine_slot_id": "implement||:0",
            "slot_role": "step_agent",
            "generation": 1,
            "slot_id": "1" * 32,
            **fields,
        }
        return {key: value for key, value in payload.items() if value is not None}

    def anchor_payload(self, **fields: object) -> dict[str, Any]:
        return {
            "effect_type": CREATE_SESSION,
            "effect_key": self.key("anchor"),
            "role": "anchor",
            **fields,
        }

    def step_payload(self, **fields: object) -> dict[str, Any]:
        return {
            "effect_type": CREATE_SESSION,
            "effect_key": self.key(),
            "role": "step",
            "agent_id": AGENT,
            "engine_slot_id": "review/item-0/m0",
            "slot_role": "verifier",
            "node_id": "review",
            **fields,
        }

    async def deliver(self, payload: dict[str, Any] | str) -> EffectCompleted | EffectFailed:
        ctx = effect_context(workspace_id=WORKSPACE, run_id=self.run.id, payload=payload)
        return await self.executor(ctx)

    def set_status(self, status: RunStatus) -> None:
        _, version = self.run_store.load_run_state(self.run.id, workspace_id=WORKSPACE)
        self.run_store.apply_transition(
            self.run.id, version, Transition(status=int(status)), workspace_id=WORKSPACE
        )


def _completed(outcome: object) -> dict[str, Any]:
    assert isinstance(outcome, EffectCompleted), outcome
    assert outcome.result is not None
    return outcome.result


def _failed(outcome: object) -> EffectFailed:
    assert isinstance(outcome, EffectFailed), outcome
    return outcome


@pytest.mark.parametrize("role", ["anchor", "step", "stance"])
async def test_create_session_executor_conformance(role: str) -> None:
    env = _Env(resolver=role == "stance")
    payload = {
        "anchor": env.anchor_payload,
        "step": env.step_payload,
        "stance": env.stance_payload,
    }[role]()
    outcomes: list[object] = []

    async def recording(ctx: Any) -> Any:
        outcome = await env.executor(ctx)
        outcomes.append(outcome)
        return outcome

    await run_executor_conformance(
        recording,
        effect_type=CREATE_SESSION,
        payload=payload,
        workspace_id=WORKSPACE,
        run_id=env.run.id,
    )

    first, repeat = (_completed(outcome) for outcome in outcomes)
    expected_session = (
        anchor_session_id(WORKSPACE, env.run.id)
        if role == "anchor"
        else effect_session_id(WORKSPACE, env.key())
    )
    # Whether this try created the session is logged, never returned: a repeat must match.
    expected_role = "anchor" if role == "anchor" else "step"
    assert (
        first == repeat == {"session_id": expected_session, "role": expected_role, "generation": 1}
    )
    assert len(env.facade.requests) == 2
    # A redelivered stance create resolves the same agent, so it asks for the same session.
    assert env.facade.requests[0] == env.facade.requests[1]


async def test_the_request_comes_from_the_run_row_and_spec_inside_the_run_scope() -> None:
    env = _Env()

    _completed(await env.deliver(env.anchor_payload()))
    _completed(await env.deliver(env.step_payload(generation=2)))

    anchor, step = env.facade.requests
    assert (anchor.role, anchor.title, anchor.host_id, anchor.workspace) == (
        "anchor",
        env.run.title,
        None,
        None,
    )
    assert (anchor.user_id, anchor.account_generation, anchor.run_id) == (
        OWNER,
        GENERATION,
        env.run.id,
    )
    assert step.effect_key == env.key()
    assert (step.host_id, step.workspace, step.agent_id) == (HOST, WORKTREE, AGENT)
    assert (step.engine_slot_id, step.slot_role, step.node_id, step.generation) == (
        "review/item-0/m0",
        "verifier",
        "review",
        2,
    )
    assert step.title == "review/item-0/m0 (attempt 2)"
    expected_scope = {
        "workspace_id": WORKSPACE,
        "run_id": env.run.id,
        "user_id": OWNER,
        "account_generation": GENERATION,
        "host_id": HOST,
    }
    assert env.scopes_at_create == [expected_scope, expected_scope]


@pytest.mark.parametrize(
    ("fields", "title"),
    [
        ({}, "review/item-0/m0"),
        ({"generation": 1}, "review/item-0/m0"),
        ({"generation": 4}, "review/item-0/m0 (attempt 4)"),
        ({"generation": 4, "title": "Review the parser"}, "Review the parser"),
    ],
)
async def test_step_titles(fields: dict[str, object], title: str) -> None:
    env = _Env()

    _completed(await env.deliver(env.step_payload(**fields)))

    assert env.facade.requests[0].title == title


@pytest.mark.parametrize(
    "change",
    [
        {"role": None},
        {"role": "orchestrator"},
        {"agent_id": None},
        {"agent_id": 7},
        {"agent_id": "x" * 65},
        {"engine_slot_id": None},
        {"engine_slot_id": "s" * 513},
        {"slot_role": None},
        {"slot_role": "reviewer"},
        {"generation": 0},
        {"generation": "2"},
        {"generation": True},
        {"generation": 40_000},
        {"title": ""},
        {"title": "line\nbreak"},
        {"title": "t" * 513},
        {"node_id": "n\x1b"},
        {"node_id": "n" * 129},
    ],
)
async def test_invalid_step_payloads_are_refused_before_any_create(
    change: dict[str, object],
) -> None:
    env = _Env()
    payload = {
        key: value for key, value in env.step_payload(**change).items() if value is not None
    }

    failure = _failed(await env.deliver(payload))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert env.facade.requests == []


@pytest.mark.parametrize(
    "payload",
    ["not json", "[1]", {"effect_type": CREATE_SESSION, "role": "anchor"}],
)
async def test_unreadable_payloads_are_refused(payload: object) -> None:
    env = _Env()

    failure = _failed(await env.deliver(payload))  # type: ignore[arg-type]

    assert failure.error_code == "effect.invalid_payload"
    assert env.facade.requests == []


@pytest.mark.parametrize(
    "change",
    [{"user_id": "mallory"}, {"account_generation": "gen-2"}],
)
async def test_a_payload_identity_other_than_the_runs_is_refused(
    change: dict[str, object],
) -> None:
    env = _Env()

    failure = _failed(await env.deliver(env.step_payload(**change)))

    assert (failure.error_code, failure.retryable) == ("effect.identity_mismatch", False)
    assert "mallory" not in failure.message
    assert env.facade.requests == []


async def test_an_effect_key_of_another_run_is_refused() -> None:
    env = _Env()

    failure = _failed(await env.deliver(env.anchor_payload(effect_key="other-run:7:create:x")))

    assert failure.error_code == "effect.identity_mismatch"
    assert env.facade.requests == []


@pytest.mark.parametrize(("host_id", "worktree_path"), [(None, WORKTREE), (HOST, None)])
async def test_a_step_needs_the_runs_host_and_worktree(
    host_id: str | None, worktree_path: str | None
) -> None:
    env = _Env(host_id=host_id, worktree_path=worktree_path)

    failure = _failed(await env.deliver(env.step_payload()))

    assert (failure.error_code, failure.retryable) == ("session.invalid", False)
    assert env.facade.requests == []
    # The anchor runs on no host.
    _completed(await env.deliver(env.anchor_payload()))


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (CoralSessionError("session.anchor_missing", "not yet", retryable=True), True),
        (CoralSessionError("session.host_offline", "offline", retryable=True), True),
        (CoralSessionError("session.title_conflict", "taken"), False),
        (CoralSessionError("session.harness_not_supported", "native"), False),
    ],
)
async def test_facade_refusals_keep_their_code_and_retryability(
    error: CoralSessionError, retryable: bool
) -> None:
    env = _Env(refusal=error)

    failure = _failed(await env.deliver(env.step_payload()))

    assert (failure.error_code, failure.retryable) == (error.code, retryable)


async def test_drift_pauses_the_run_and_fails_permanently() -> None:
    finding = DriftFinding(cause="anchor_archived", session_id="c" * 32, occurrence="1700000000")
    env = _Env(refusal=DriftDetected(finding))
    env.set_status(RunStatus.RUNNING)

    first = _failed(await env.deliver(env.step_payload()))
    repeat = _failed(await env.deliver(env.step_payload()))

    assert (first.error_code, first.retryable) == ("drift.anchor_archived", False)
    # The run is paused now: a repeat is held, and the facade is not asked again.
    assert (repeat.error_code, repeat.retryable) == ("run.paused", True)
    assert len(env.facade.requests) == 1
    state, _ = env.run_store.load_run_state(env.run.id, workspace_id=WORKSPACE)
    assert (state.run.status, state.run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.DRIFT)
    paused = [
        json.loads(entry.body)
        for entry in env.run_store.logs[(WORKSPACE, env.run.id)]
        if entry.kind == int(LogKind.PAUSED)
    ]
    assert paused == [
        {
            "kind": "pause_run",
            "reason": "drift",
            "cause": "anchor_archived",
            "session_id": "c" * 32,
            "detail": "1700000000",
        }
    ]


async def test_a_lost_lease_reaches_the_drainer() -> None:
    env = _Env()

    async def lost() -> bool:
        return False

    ctx = effect_context(
        workspace_id=WORKSPACE, run_id=env.run.id, payload=env.anchor_payload(), ensure_lease=lost
    )
    with pytest.raises(StartupLeaseLost):
        await env.executor(ctx)


@pytest.mark.parametrize("role", ["anchor", "step"])
async def test_a_paused_run_holds_the_create_without_asking_the_facade(role: str) -> None:
    env = _Env()
    env.set_status(RunStatus.PAUSED)
    payload = env.anchor_payload() if role == "anchor" else env.step_payload()

    failure = _failed(await env.deliver(payload))

    assert (failure.error_code, failure.retryable) == ("run.paused", True)
    assert env.facade.requests == []


# ── the stance form: the executor resolves the step's agent ─────────────────

_RUN_SCOPE_KEYS = ("workspace_id", "run_id", "user_id", "account_generation", "host_id")


async def test_a_stance_resolves_to_the_run_owners_agent_inside_the_run_scope() -> None:
    env = _Env(resolver=True)

    result = _completed(await env.deliver(env.stance_payload()))

    assert env.agents is not None
    [call] = env.agents.calls
    scope = call.pop("scope")
    assert call == {
        "workspace_id": WORKSPACE,
        "owner": OWNER,
        "stance": "implementer",
        "workflow_slug": "two-steps",
        "node_id": "implement",
        "roster_index": 0,
        # The session the create makes: a retry keeps the agent it runs.
        "session_id": effect_session_id(WORKSPACE, env.key()),
        "run_id": env.run.id,
        "profile": None,
    }
    assert isinstance(scope, dict)
    assert {key: scope[key] for key in _RUN_SCOPE_KEYS} == {
        "workspace_id": WORKSPACE,
        "run_id": env.run.id,
        "user_id": OWNER,
        "account_generation": GENERATION,
        "host_id": HOST,
    }
    [request] = env.facade.requests
    assert (request.agent_id, request.engine_slot_id, request.slot_role, request.node_id) == (
        RESOLVED_AGENT,
        "implement||:0",
        "step_agent",
        "implement",
    )
    assert result["session_id"] == effect_session_id(WORKSPACE, env.key())


async def test_a_profile_step_resolves_with_its_run_and_profile_ref() -> None:
    env = _Env(resolver=True)

    _completed(await env.deliver(env.stance_payload(profile="implementer/fast")))

    assert env.agents is not None
    [call] = env.agents.calls
    assert (call["stance"], call["run_id"], call["profile"]) == (
        "implementer",
        env.run.id,
        "implementer/fast",
    )


async def test_an_orchestrator_stance_needs_no_step_reference() -> None:
    env = _Env(resolver=True)
    payload = env.stance_payload(
        stance="orchestrator",
        workflow_slug=None,
        node_id=None,
        roster_index=None,
        engine_slot_id="orchestrator",
        slot_role="orchestrator",
        title="Ship it · orchestrator",
    )

    _completed(await env.deliver(payload))

    assert env.agents is not None
    [call] = env.agents.calls
    assert (call["stance"], call["workflow_slug"], call["node_id"], call["roster_index"]) == (
        "orchestrator",
        None,
        None,
        None,
    )
    [request] = env.facade.requests
    assert (request.agent_id, request.slot_role, request.title) == (
        RESOLVED_AGENT,
        "orchestrator",
        "Ship it · orchestrator",
    )


async def test_a_rejected_bundle_fails_permanently_before_any_create() -> None:
    rejected = CoralSessionError("session.agent_not_supported", "the bundle breaks a rule")
    env = _Env(resolver_error=rejected)

    failure = _failed(await env.deliver(env.stance_payload()))

    assert (failure.error_code, failure.retryable) == ("session.agent_not_supported", False)
    assert env.facade.requests == []


async def test_a_stance_without_a_resolver_is_an_invalid_payload() -> None:
    env = _Env()

    failure = _failed(await env.deliver(env.stance_payload()))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert env.facade.requests == []


@pytest.mark.parametrize(
    "change",
    [
        {"stance": "anchor"},
        {"stance": "planner"},
        {"stance": 3},
        {"stance": ["implementer"]},
        {"workflow_slug": None},
        {"workflow_slug": "w" * 65},
        {"workflow_slug": "two\nsteps"},
        {"node_id": None},
        {"roster_index": None},
        {"roster_index": -1},
        {"roster_index": True},
        {"roster_index": "0"},
        {"roster_index": 1_000},
        {"profile": "reviewer/strict"},
        {"profile": "implementer/Bad"},
        {"profile": 3},
    ],
)
async def test_invalid_stance_payloads_are_refused_before_resolving(
    change: dict[str, object],
) -> None:
    env = _Env(resolver=True)

    failure = _failed(await env.deliver(env.stance_payload(**change)))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert env.agents is not None and env.agents.calls == []
    assert env.facade.requests == []


async def test_a_paused_run_holds_a_stance_create_before_resolving() -> None:
    env = _Env(resolver=True)
    env.set_status(RunStatus.PAUSED)

    failure = _failed(await env.deliver(env.stance_payload()))

    assert (failure.error_code, failure.retryable) == ("run.paused", True)
    assert env.agents is not None and env.agents.calls == []


# ── send_input, close_slot, cancel_sessions ─────────────────────────────────

SESSION = "5" * 32
BRIEF_KEY_SUBJECT = "slot-1"
BASE = "1" * 40
NEW = "2" * 40
DIFF = {"files_changed": 1, "insertions": 2, "deletions": 0, "paths": ["work.txt"]}


def _host_replies() -> dict[str, Reply]:
    return {
        "fingerprint": {"level": "L1", "digest": "d" * 64, "head": BASE, "dirty_count": 1},
        "head": {"head": BASE, "branch": None, "merge_in_progress": False},
        "commit": {"commit": NEW, "empty": False},
        "diff_stat": dict(DIFF),
    }


class _Sessions:
    """A started run with one bound step session, and the send, close and cancel executors."""

    def __init__(
        self,
        *,
        slot_role: SlotRole = SlotRole.STEP_AGENT,
        bound: bool = True,
        binding_generation: int = 1,
        slot_generation: int = 1,
        slot_session: str = SESSION,
        progress: SessionBindingProgress = SessionBindingProgress.INITIALIZED,
    ) -> None:
        self.events: list[str] = []
        self.run_store = FakeRunStore(default_workspace_id=WORKSPACE)
        self.run: CoralRun = start_run(
            self.run_store,
            workspace_id=WORKSPACE,
            user_id=OWNER,
            account_generation=GENERATION,
            host_id=HOST,
            repo_path="/Users/alice/repo",
            worktree_path=WORKTREE,
        )
        add_slot(
            self.run_store, self.run, session_id=slot_session, session_generation=slot_generation
        )
        self.dispatch = FakeDispatch(self.events, owner=OWNER)
        self.session = self.dispatch.session(SESSION)
        self.edges = FakeEdgeWatcher(self.events)
        self.stable_ids = FakeStableIds(self.events)
        binding = step_binding(
            workspace_id=WORKSPACE,
            run_id=self.run.id,
            session_id=SESSION,
            slot_role=slot_role,
            host_id=HOST,
            session_generation=binding_generation,
        )
        binding = dataclasses.replace(binding, progress=progress)
        self.bindings = FakeBindings([binding] if bound else [])
        self.intents = FakeIntents(self.events)
        self.channel = FakeHostChannel(self.events, _host_replies())
        self.scope = RecordingScopeRunner()
        self.scopes_at_send: list[dict[str, object] | None] = []
        self.dispatch.hooks["send_message"] = lambda: self.scopes_at_send.append(self.scope.active)
        self.send = send_input_executor(
            self.dispatch, self.stable_ids, self.bindings, self.run_store, self.scope
        )
        self.close = close_slot_executor(
            self.dispatch,
            self.edges,
            FakeChannels(self.channel, self.scope),
            self.intents,
            self.stable_ids,
            self.bindings,
            self.run_store,
            self.scope,
        )
        self.cancel = cancel_sessions_executor(
            self.dispatch, self.edges, self.bindings, self.run_store, self.scope
        )

    def key(self, kind: str) -> str:
        return f"{self.run.id}:9:{kind}:{BRIEF_KEY_SUBJECT}"

    def send_payload(self, **fields: object) -> dict[str, Any]:
        return {
            "effect_type": SEND_INPUT,
            "effect_key": self.key("send_input"),
            "session_id": SESSION,
            "text": "Review the parser.",
            "kind": "brief",
            **fields,
        }

    def close_payload(self, **fields: object) -> dict[str, Any]:
        return {
            "effect_type": CLOSE_SLOT,
            "effect_key": self.key("close_slot"),
            "session_id": SESSION,
            "interrupt": True,
            "closed_label": True,
            "message": "Review: done",
            **fields,
        }

    def cancel_payload(self, **fields: object) -> dict[str, Any]:
        return {
            "effect_type": CANCEL_SESSIONS,
            "effect_key": self.key("cancel_sessions"),
            "session_id": SESSION,
            "closed_label": True,
            **fields,
        }

    async def deliver(
        self, executor: Any, payload: dict[str, Any] | str
    ) -> EffectCompleted | EffectFailed:
        ctx = effect_context(workspace_id=WORKSPACE, run_id=self.run.id, payload=payload)
        return await executor(ctx)

    async def brief(self) -> None:
        """The brief was sent: its stable id is recorded and it is in the transcript."""
        _completed(await self.deliver(self.send, self.send_payload()))

    def set_status(self, status: RunStatus) -> None:
        _, version = self.run_store.load_run_state(self.run.id, workspace_id=WORKSPACE)
        self.run_store.apply_transition(
            self.run.id, version, Transition(status=int(status)), workspace_id=WORKSPACE
        )


async def _conformance(env: _Sessions, executor: Any, effect_type: str, payload: dict[str, Any]):
    outcomes: list[object] = []

    async def recording(ctx: Any) -> Any:
        outcome = await executor(ctx)
        outcomes.append(outcome)
        return outcome

    await run_executor_conformance(
        recording,
        effect_type=effect_type,
        payload=payload,
        workspace_id=WORKSPACE,
        run_id=env.run.id,
    )
    first, repeat = (_completed(outcome) for outcome in outcomes)
    assert first == repeat
    return first


async def test_send_input_executor_conformance() -> None:
    env = _Sessions()

    result = await _conformance(env, env.send, SEND_INPUT, env.send_payload())

    stable_id = effect_message_id(WORKSPACE, env.key("send_input"))
    assert result == {"session_id": SESSION, "stable_id": stable_id}
    # The id was recorded before each send, with the exact text the session receives.
    assert env.events == ["record_send", "send_message", "record_send", "send_message"]
    [record] = env.stable_ids.rows.values()
    assert record.content_cksum == content_checksum(engine_message_text("Review the parser."))
    assert (record.run_id, record.session_id, record.kind) == (
        env.run.id,
        SESSION,
        StableIdKind.BRIEF,
    )
    assert [send["stable_id"] for send in env.dispatch.sends] == [stable_id, stable_id]
    assert [message.item_id for message in env.session.transcript] == [stable_id]
    expected_scope = {
        "workspace_id": WORKSPACE,
        "run_id": env.run.id,
        "user_id": OWNER,
        "account_generation": GENERATION,
        "host_id": HOST,
    }
    assert env.scopes_at_send == [expected_scope]


async def test_a_send_to_a_session_this_run_did_not_bind_is_refused() -> None:
    env = _Sessions(bound=False)

    failure = _failed(await env.deliver(env.send, env.send_payload()))

    assert (failure.error_code, failure.retryable) == ("session.identity_conflict", False)
    assert env.events == []


async def test_a_paused_run_holds_a_send_but_still_closes_and_cancels() -> None:
    env = _Sessions()
    await env.brief()
    env.events.clear()
    env.set_status(RunStatus.PAUSED)

    held = _failed(await env.deliver(env.send, env.send_payload(kind="steer")))
    closed = _completed(await env.deliver(env.close, env.close_payload()))
    cancelled = _completed(await env.deliver(env.cancel, env.cancel_payload()))

    assert (held.error_code, held.retryable) == ("run.paused", True)
    assert "record_send" not in env.events and "send_message" not in env.events
    assert closed["commit"] == NEW and cancelled == {"session_id": SESSION}


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "order"},
        {"kind": None},
        {"text": ""},
        {"text": None},
        {"text": "nul\x00byte"},
        {"text": "x" * (MAX_ENGINE_MESSAGE_BYTES + 1)},
        # A lone surrogate, which a JSON payload can carry but UTF-8 cannot.
        {"text": "brief \ud800 text"},
        {"session_id": "Not-A-Session"},
    ],
)
async def test_invalid_send_payloads_are_refused_before_anything_is_recorded(
    change: dict[str, object],
) -> None:
    env = _Sessions()
    payload = {
        key: value for key, value in env.send_payload(**change).items() if value is not None
    }

    failure = _failed(await env.deliver(env.send, payload))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert env.events == []


async def test_a_changed_text_under_the_same_effect_is_refused_before_sending() -> None:
    env = _Sessions()
    await env.brief()

    failure = _failed(await env.deliver(env.send, env.send_payload(text="Another brief.")))

    assert (failure.error_code, failure.retryable) == ("effect.identity_mismatch", False)
    assert len(env.dispatch.sends) == 1


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (CoralSessionError("dispatch.policy_denied", "denied"), False),
        (CoralSessionError("dispatch.session_closed", "closed"), False),
        (CoralSessionError("drift.anchor_archived", "archived"), False),
        (CoralSessionError("dispatch.runner_unavailable", "down", retryable=True), True),
    ],
)
async def test_send_refusals_keep_their_code_and_retryability(
    error: CoralSessionError, retryable: bool
) -> None:
    env = _Sessions()
    env.dispatch.refusals["send_message"] = error

    failure = _failed(await env.deliver(env.send, env.send_payload()))

    assert (failure.error_code, failure.retryable) == (error.code, retryable)
    # The id was recorded first; a recorded id whose send failed is harmless.
    assert env.events[:2] == ["record_send", "send_message"]


async def test_close_slot_executor_conformance() -> None:
    env = _Sessions()
    await env.brief()

    result = await _conformance(env, env.close, CLOSE_SLOT, env.close_payload())

    assert result == {
        "pending_input": False,
        "queued_input": False,
        "post_accept_edits": False,
        "commit": NEW,
        "empty": False,
        "diff_stat": {**DIFF, "paths_truncated": False},
    }
    [commit, retried] = [request for request in env.channel.requests if request.op == "commit"]
    assert (
        commit.op_key
        == retried.op_key
        == effect_op_key(WORKSPACE, env.key("close_slot"), "commit")
    )
    assert commit.params["expected_head"] == retried.params["expected_head"] == BASE
    assert commit.params["message"] == "Review: done"
    assert commit.params["run_id"] == env.run.id
    assert commit.params["attempt_id"] == derived_id("coral-attempt", env.run.id, "slot-1", "1")


async def test_a_close_without_a_message_commits_with_the_default_one() -> None:
    env = _Sessions()
    await env.brief()

    _completed(await env.deliver(env.close, env.close_payload(message=None)))

    [commit] = [request for request in env.channel.requests if request.op == "commit"]
    assert commit.params["message"] == "Coral: slot-1"


@pytest.mark.parametrize(
    ("slot_role", "binding_generation", "slot_generation"),
    [
        (SlotRole.VERIFIER, 1, 1),
        (SlotRole.ORCHESTRATOR, 1, 1),
        # A writer slot that moved on to a new session: the old one never commits.
        (SlotRole.STEP_AGENT, 1, 2),
    ],
)
async def test_only_the_current_writer_session_commits_at_its_close(
    slot_role: SlotRole, binding_generation: int, slot_generation: int
) -> None:
    env = _Sessions(
        slot_role=slot_role,
        binding_generation=binding_generation,
        slot_generation=slot_generation,
    )
    await env.brief()

    result = _completed(await env.deliver(env.close, env.close_payload()))

    assert (result["commit"], result["empty"], result["diff_stat"]) == (None, None, None)
    assert env.channel.requests == []
    assert "stop" in env.events


async def test_a_writers_close_waits_until_a_slot_names_its_session() -> None:
    # The slot still names another session: closing now would drop the writer's commit.
    writer = _Sessions(slot_session="6" * 32)
    reader = _Sessions(slot_role=SlotRole.VERIFIER, slot_session="6" * 32)

    waiting = _failed(await writer.deliver(writer.close, writer.close_payload()))
    closed = _completed(await reader.deliver(reader.close, reader.close_payload()))

    assert (waiting.error_code, waiting.retryable) == ("session.not_ready", True)
    assert writer.events == [] and writer.channel.requests == []
    # A reader never commits, so its close does not wait for the slot.
    assert closed["commit"] is None and "stop" in reader.events


async def test_a_close_of_a_session_this_run_did_not_bind_is_refused() -> None:
    env = _Sessions(bound=False)

    failure = _failed(await env.deliver(env.close, env.close_payload()))

    assert (failure.error_code, failure.retryable) == ("session.identity_conflict", False)
    assert env.events == []


async def test_a_blocked_close_is_retryable() -> None:
    env = _Sessions()
    env.session.status = "running"
    env.session.pending_elicitations = 1

    failure = _failed(await env.deliver(env.close, env.close_payload()))

    assert (failure.error_code, failure.retryable) == ("slot.close_blocked", True)
    assert "stop" not in env.events


@pytest.mark.parametrize(
    "change",
    [
        {"interrupt": "yes"},
        {"closed_label": 1},
        {"message": "bad\x1b[2Jmessage"},
        {"attempt_id": "Not An Id"},
        {"diff_from": "HEAD"},
        {"session_id": None},
    ],
)
async def test_invalid_close_payloads_are_refused_before_anything_runs(
    change: dict[str, object],
) -> None:
    env = _Sessions()
    payload = {
        key: value for key, value in env.close_payload(**change).items() if value is not None
    }

    failure = _failed(await env.deliver(env.close, payload))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert env.events == []


async def test_cancel_sessions_executor_conformance() -> None:
    env = _Sessions()
    env.session.status = "running"
    env.session.response_id = "resp_1"

    result = await _conformance(env, env.cancel, CANCEL_SESSIONS, env.cancel_payload())

    assert result == {"session_id": SESSION}
    assert env.dispatch.interrupts == ["resp_1"]
    assert [event for event in env.events if event in ("set_closed", "stop")] == [
        "set_closed",
        "stop",
        "set_closed",
        "stop",
    ]


async def test_a_slot_with_no_session_yet_is_cancelled_without_action() -> None:
    env = _Sessions(bound=False)

    result = _completed(await env.deliver(env.cancel, env.cancel_payload(session_id=None)))

    assert result == {"session_id": None}
    assert env.events == []


async def test_a_session_this_run_never_bound_counts_as_cancelled() -> None:
    # The slot's create never got as far as binding the session the cancel names.
    env = _Sessions(bound=False)

    result = _completed(await env.deliver(env.cancel, env.cancel_payload()))

    assert result == {"session_id": SESSION}
    assert env.events == []
    assert env.dispatch.interrupts == []


async def test_a_session_bound_to_another_run_is_left_alone_and_counts_as_cancelled() -> None:
    env = _Sessions()
    for key, binding in list(env.bindings.rows.items()):
        env.bindings.rows[key] = dataclasses.replace(binding, run_id="f" * 32)

    result = _completed(await env.deliver(env.cancel, env.cancel_payload()))

    assert result == {"session_id": SESSION}
    assert env.events == []


async def test_the_session_of_a_create_that_finished_before_the_cancel_is_cancelled() -> None:
    # One item per run runs at a time, so a cancel queued while its slot's create ran
    # finds the session that create bound, by the id the create's effect key derives.
    env = _Sessions(progress=SessionBindingProgress.ROW_CREATED)
    env.session.status = "running"
    env.session.response_id = "resp_1"

    result = _completed(await env.deliver(env.cancel, env.cancel_payload()))

    assert result == {"session_id": SESSION}
    assert env.dispatch.interrupts == ["resp_1"]
    assert "stop" in env.events


async def test_a_cancel_without_a_session_id_key_is_refused() -> None:
    # The reducer's own cancel_sessions payload names no session; forwarded as is,
    # it must fail loudly instead of cancelling nothing.
    env = _Sessions()
    payload = env.cancel_payload()
    del payload["session_id"]

    failure = _failed(await env.deliver(env.cancel, payload))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert "session_id" in failure.message
    assert env.events == []


async def test_cancelling_a_deleted_session_succeeds() -> None:
    env = _Sessions()
    env.dispatch.refusals["live_status"] = CoralSessionError("session.deleted", "gone")

    result = _completed(await env.deliver(env.cancel, env.cancel_payload()))

    assert result == {"session_id": SESSION}


async def test_a_send_or_close_before_the_sessions_row_exists_waits() -> None:
    # The create reserved the binding but has not written the session's row yet.
    env = _Sessions(progress=SessionBindingProgress.RESERVED)

    send = _failed(await env.deliver(env.send, env.send_payload()))
    close = _failed(await env.deliver(env.close, env.close_payload()))

    assert (send.error_code, send.retryable) == ("session.not_ready", True)
    assert (close.error_code, close.retryable) == ("session.not_ready", True)
    assert env.events == []


async def test_a_send_to_the_runs_orchestrator_waits_until_its_create_binds_it() -> None:
    # The bridge names the orchestrator on the run before its create has run.
    env = _Sessions(bound=False)
    _, version = env.run_store.load_run_state(env.run.id, workspace_id=WORKSPACE)
    env.run_store.apply_transition(
        env.run.id, version, Transition(orchestrator_session_id=SESSION), workspace_id=WORKSPACE
    )
    other = _Sessions(bound=False)

    waiting = _failed(await env.deliver(env.send, env.send_payload()))
    refused = _failed(await other.deliver(other.send, other.send_payload()))

    assert (waiting.error_code, waiting.retryable) == ("session.not_ready", True)
    assert (refused.error_code, refused.retryable) == ("session.identity_conflict", False)
    assert env.events == [] and env.dispatch.sends == []


async def test_a_writers_close_without_the_closed_label_is_refused_before_anything_runs() -> None:
    writer = _Sessions()
    reader = _Sessions(slot_role=SlotRole.VERIFIER)
    await reader.brief()
    reader.events.clear()

    refused = _failed(await writer.deliver(writer.close, writer.close_payload(closed_label=False)))
    closed = _completed(
        await reader.deliver(reader.close, reader.close_payload(closed_label=False))
    )

    assert (refused.error_code, refused.retryable) == ("effect.invalid_payload", False)
    assert writer.events == [] and writer.channel.requests == []
    # A reader's close may leave the label off; it never commits.
    assert closed["commit"] is None
    assert "set_closed" not in reader.events and "stop" in reader.events
