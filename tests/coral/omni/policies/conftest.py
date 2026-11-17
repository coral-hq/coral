"""Coral's policy provider over a fake run store and binding lookup, registered for one test."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from coral.db.enum_codecs import RunPauseReason, RunStatus, SessionBindingRole, SlotRole
from coral.omni.policies.bindings_cache import CachedBindingLookup
from coral.omni.policies.provider import CoralPolicyProvider
from coral.omni.policies.state import RunStatusCache
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import RunStartSpec, Transition
from omnigent.db.db_models import workspace_scope
from omnigent.policies.types import EvaluationContext, PolicyResult
from omnigent.runtime.policies.builder import build_policy_engine
from omnigent.runtime.policies.engine import PolicyEngine
from omnigent.runtime.policies.required_providers import register_required_policy_provider
from omnigent.spec import AgentSpec, ExecutorSpec
from omnigent.spec.types import Phase
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests.coral.tools.fake_decision_port import WORKSPACE, FakeBindingLookup, step_binding

ROLES = {
    "step": (SessionBindingRole.STEP, SlotRole.STEP_AGENT),
    "verifier": (SessionBindingRole.STEP, SlotRole.VERIFIER),
    "orchestrator": (SessionBindingRole.STEP, SlotRole.ORCHESTRATOR),
    "anchor": (SessionBindingRole.ANCHOR, None),
}


def coral_spec(stance: str | None = "implementer") -> AgentSpec:
    """A claude-sdk agent of a generated Coral bundle with *stance*; ``None`` is a plain agent."""
    return AgentSpec(
        spec_version=1,
        executor=ExecutorSpec(type="omnigent", config={"harness": "claude-sdk"}),
        params={} if stance is None else {"coral": {"generated": {"stance": stance}}},
    )


def tool_call(name: str) -> EvaluationContext:
    return EvaluationContext(
        phase=Phase.TOOL_CALL, content={"name": name, "arguments": {}}, tool_name=name
    )


@dataclass
class CoralPolicies:
    """Sessions in workspace ``WORKSPACE``, runs in a fake store, bindings in a fake lookup."""

    conversations: SqlAlchemyConversationStore
    run_store: FakeRunStore
    lookup: FakeBindingLookup
    statuses: RunStatusCache
    provider: CoralPolicyProvider

    def run(
        self, status: RunStatus = RunStatus.RUNNING, *, reason: RunPauseReason | None = None
    ) -> str:
        run = self.run_store.start_run(RunStartSpec("wf", "v1", "Run", "", workspace_id=WORKSPACE))
        self.set_status(run.id, status, reason=reason)
        return run.id

    def set_status(
        self, run_id: str, status: RunStatus, *, reason: RunPauseReason | None = None
    ) -> None:
        """Commit *status* through the run store, as the engine and the drift pause do."""
        _, version = self.run_store.load_run_state(run_id, workspace_id=WORKSPACE)
        self.run_store.apply_transition(
            run_id,
            version,
            Transition(
                status=int(status),
                pause_reason=None if reason is None else int(reason),
                clear_pause_reason=reason is None,
            ),
            workspace_id=WORKSPACE,
        )

    def session(
        self,
        run_id: str | None = None,
        *,
        role: str = "step",
        labels: dict[str, str] | None = None,
        title: str | None = None,
    ) -> str:
        """A session row, bound to *run_id* as *role* unless *run_id* is ``None``."""
        with workspace_scope(WORKSPACE):
            session_id = self.conversations.create_conversation(labels=labels, title=title).id
        if run_id is not None:
            binding_role, slot_role = ROLES[role]
            self.lookup.add(
                step_binding(
                    None if slot_role is None else "work||:0",
                    session_id=session_id,
                    run_id=run_id,
                    role=binding_role,
                    slot_role=slot_role,
                )
            )
        return session_id

    def engine(self, spec: AgentSpec, session_id: str) -> PolicyEngine:
        """A fresh engine, as every enforcement path builds one per call."""
        with workspace_scope(WORKSPACE):
            return build_policy_engine(
                spec=spec, conversation_id=session_id, conversation_store=self.conversations
            )

    def names(self, spec: AgentSpec, session_id: str) -> list[str]:
        return [policy.spec.name for policy in self.engine(spec, session_id).policies]

    async def evaluate(
        self, spec: AgentSpec, session_id: str, context: EvaluationContext
    ) -> PolicyResult:
        return await self.engine(spec, session_id).evaluate(context)

    async def call(self, spec: AgentSpec, session_id: str, tool: str) -> PolicyResult:
        return await self.evaluate(spec, session_id, tool_call(tool))


@pytest.fixture
def coral_policies(db_uri: str) -> Iterator[CoralPolicies]:
    """Coral's provider registered under its production name; removed after the test."""
    run_store = FakeRunStore(default_workspace_id=WORKSPACE)
    lookup = FakeBindingLookup()
    statuses = RunStatusCache(run_store)
    unhook = run_store.register_post_commit(statuses.invalidate)
    provider = CoralPolicyProvider(bindings=lookup, statuses=statuses)
    unregister = register_required_policy_provider("coral", provider)
    yield CoralPolicies(
        conversations=SqlAlchemyConversationStore(db_uri),
        run_store=run_store,
        lookup=lookup,
        statuses=statuses,
        provider=provider,
    )
    unregister()
    unhook()


class Clock:
    """Monotonic seconds that only the test moves; frozen, it never expires a cached status."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def wired_policies(coral_policies: CoralPolicies, clock: Clock) -> Iterator[CoralPolicies]:
    """``coral_policies`` composed as the lifespan composes it, its status cache on ``clock``.

    The provider reads bindings through the shared found-rows cache, and its
    status cache is cleared by the run store's commits; it replaces the
    ``coral_policies`` registration for the test.
    """
    statuses = RunStatusCache(coral_policies.run_store, clock=clock)
    unhook = coral_policies.run_store.register_post_commit(statuses.invalidate)
    provider = CoralPolicyProvider(
        bindings=CachedBindingLookup(coral_policies.lookup), statuses=statuses
    )
    unregister = register_required_policy_provider("coral", provider)
    yield dataclasses.replace(coral_policies, statuses=statuses, provider=provider)
    unregister()
    unhook()
