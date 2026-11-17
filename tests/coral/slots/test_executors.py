"""The ``create_session`` executor: payload, run identity and scopes, failure mapping, drift."""

from __future__ import annotations

import json
from typing import Any

import pytest

from coral.db.enum_codecs import LogKind, RunPauseReason, RunStatus
from coral.model.ids import anchor_session_id, effect_session_id
from coral.omni.protocols import CoralSessionError
from coral.queue.conformance import run_executor_conformance
from coral.queue.executors import EffectCompleted, EffectFailed, StartupLeaseLost
from coral.recovery.drift import DriftDetected, DriftFinding, DriftPauser
from coral.slots.executors import CREATE_SESSION, create_session_executor
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun, Transition
from tests.coral.omni.fakes import FakeSessionFacade
from tests.coral.workspace._executor_fakes import RecordingScopeRunner, effect_context, start_run

WORKSPACE = 4
OWNER = "alice"
GENERATION = "gen-1"
HOST = "h" * 32
WORKTREE = "/Users/alice/repo-worktrees/coral-r-base"
AGENT = "a" * 32
NOW_US = 1_700_000_000_000_000


class _Env:
    """A started run, the executor under test and its fakes."""

    def __init__(
        self,
        *,
        host_id: str | None = HOST,
        worktree_path: str | None = WORKTREE,
        refusal: BaseException | None = None,
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
        self.executor = create_session_executor(
            self.facade,
            self.run_store,
            DriftPauser(self.run_store, now_us=lambda: NOW_US),
            self.scope,
        )

    def key(self, subject: str = "slot-1") -> str:
        return f"{self.run.id}:7:create_session:{subject}"

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


@pytest.mark.parametrize("role", ["anchor", "step"])
async def test_create_session_executor_conformance(role: str) -> None:
    env = _Env()
    payload = env.anchor_payload() if role == "anchor" else env.step_payload()
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
    assert first == repeat == {"session_id": expected_session, "role": role, "generation": 1}
    assert len(env.facade.requests) == 2


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
