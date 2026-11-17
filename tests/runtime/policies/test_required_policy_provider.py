# CORAL(S52): tests for required-policy providers (new file).
"""Required-policy providers lead every policy build for the sessions they claim.

A provider's specs are prepended after the builder's last assembly site, so
they come first on root sessions, inheriting children and sub-agent children
alike, and its ``applies`` keeps the ``any_policies_apply`` fast path from
skipping the session. With no provider, or none that applies, the policy list
is the builder's own. A broken provider denies only its session's tool calls.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Collection, Iterator, Sequence

import pytest

from omnigent.entities import Conversation
from omnigent.policies.schema import PolicyEvent, PolicyResponse
from omnigent.policies.types import EvaluationContext
from omnigent.runtime.policies.builder import (
    any_policies_apply,
    build_policy_engine,
    invalidate_default_policy_specs_cache,
)
from omnigent.runtime.policies.engine import PolicyEngine
from omnigent.runtime.policies.required_providers import (
    RequiredPolicyProvider,
    deny_tool_calls,
    register_required_policy_provider,
    required_policies_apply,
    required_policy_specs,
)
from omnigent.spec.types import (
    AgentSpec,
    FunctionPolicySpec,
    FunctionRef,
    GuardrailsSpec,
    Phase,
    PolicyAction,
    PolicySpec,
)
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.stores.policy_store.sqlalchemy_store import SqlAlchemyPolicyStore
from tests.runtime.policies.conftest import make_fixed_function_policy_spec

_REQUIRED = ["__ask_on_add_policy", "__ask_on_scheduled_task_change"]
_ALLOW_PATH = "tests.runtime.policies.conftest._always_allow"
_ALLOW_AND_WRITE_PATH = "tests.runtime.policies.conftest._always_allow_taint_integrity"
_SHELL_REASON = "shell is off for this session"


def deny_shell(event: PolicyEvent) -> PolicyResponse:
    """Test policy: DENY ``sys_os_shell`` calls, ALLOW everything else."""
    data = event.get("data")
    if event.get("type") == "tool_call" and isinstance(data, dict):
        if data.get("name") == "sys_os_shell":
            return {"result": "DENY", "reason": _SHELL_REASON}
    return {"result": "ALLOW"}


def failing_factory() -> Callable[[PolicyEvent], PolicyResponse]:
    """Test policy factory that raises, as a broken provider's factory would."""
    raise RuntimeError("factory failed")


_SHELL_GUARD = FunctionPolicySpec(
    name="shell_guard", on=None, function=FunctionRef(path=f"{__name__}.deny_shell")
)


class _Provider:
    """Claims *session_ids* (``None``: every call) and answers with *specs*."""

    def __init__(
        self,
        session_ids: Collection[str] | None,
        specs: Sequence[object] = (),
        *,
        fail_for: Collection[str] = (),
        applies_error: Exception | None = None,
    ) -> None:
        self._session_ids = session_ids
        self._specs = list(specs)
        self._fail_for = fail_for
        self._applies_error = applies_error
        self.calls: list[str] = []

    def applies(self, spec: AgentSpec, conversation: Conversation | None) -> bool:
        if self._applies_error is not None:
            raise self._applies_error
        if self._session_ids is None:
            return True
        return conversation is not None and conversation.id in self._session_ids

    def specs(self, spec: AgentSpec, conversation: Conversation) -> Sequence[PolicySpec]:
        self.calls.append(conversation.id)
        if conversation.id in self._fail_for:
            raise RuntimeError("binding store offline")
        return self._specs  # type: ignore[return-value]  # tests feed malformed output too


Register = Callable[[str, RequiredPolicyProvider], Callable[[], None]]


@pytest.fixture()
def register() -> Iterator[Register]:
    """Register providers for one test; every registration is removed afterwards."""
    unregisters: list[Callable[[], None]] = []

    def _register(name: str, provider: RequiredPolicyProvider) -> Callable[[], None]:
        unregister = register_required_policy_provider(name, provider)
        unregisters.append(unregister)
        return unregister

    yield _register
    for unregister in unregisters:
        unregister()


def _tool_call(name: str = "sys_os_shell") -> EvaluationContext:
    return EvaluationContext(
        phase=Phase.TOOL_CALL, content={"name": name, "arguments": {}}, tool_name=name
    )


def _build(
    spec: AgentSpec,
    conversation_id: str,
    store: SqlAlchemyConversationStore,
    *,
    policy_store: SqlAlchemyPolicyStore | None = None,
    default_policies: list[PolicySpec] | None = None,
) -> PolicyEngine:
    return build_policy_engine(
        spec=spec,
        conversation_id=conversation_id,
        conversation_store=store,
        policy_store=policy_store,
        default_policies=default_policies,
    )


def _labels(store: SqlAlchemyConversationStore, conversation_id: str) -> dict[str, str]:
    conversation = store.get_conversation(conversation_id)
    assert conversation is not None
    return dict(conversation.labels)


def _names(engine: PolicyEngine) -> list[str]:
    return [policy.spec.name for policy in engine.policies]


@pytest.mark.parametrize("shape", ["root", "inherited", "sub_agent"])
def test_provider_specs_lead_every_assembly_path(
    db_uri: str,
    conversation_store: SqlAlchemyConversationStore,
    register: Register,
    shape: str,
) -> None:
    """Root, inherited and sub-agent builds each reassign the policy list; specs lead all."""
    invalidate_default_policy_specs_cache()
    policy_store = SqlAlchemyPolicyStore(db_uri)
    worker = AgentSpec(
        spec_version=1,
        name="worker",
        guardrails=GuardrailsSpec(policies=[make_fixed_function_policy_spec("worker_guard")]),
    )
    spec = AgentSpec(
        spec_version=1,
        name="bundle",
        guardrails=GuardrailsSpec(policies=[make_fixed_function_policy_spec("agent_guard")]),
        sub_agents=[worker],
    )
    root = conversation_store.create_conversation()
    policy_store.create(uuid.uuid4().hex, root.id, "root_session_guard", "python", _ALLOW_PATH)
    if shape == "root":
        target = root
        baseline = ["root_session_guard", "agent_guard", "admin_guard", *_REQUIRED]
    elif shape == "inherited":
        target = conversation_store.create_conversation(
            kind="sub_agent", parent_conversation_id=root.id
        )
        policy_store.create(
            uuid.uuid4().hex, target.id, "child_session_guard", "python", _ALLOW_PATH
        )
        baseline = [
            "root_session_guard",
            "child_session_guard",
            "agent_guard",
            "admin_guard",
            *_REQUIRED,
        ]
    else:
        target = conversation_store.create_conversation(
            kind="sub_agent",
            parent_conversation_id=root.id,
            sub_agent_name="worker",
            title="worker:probe",
        )
        baseline = ["root_session_guard", "agent_guard", "worker_guard", "admin_guard", *_REQUIRED]

    def names() -> list[str]:
        return _names(
            _build(
                spec,
                target.id,
                conversation_store,
                policy_store=policy_store,
                default_policies=[make_fixed_function_policy_spec("admin_guard")],
            )
        )

    assert names() == baseline
    register("bystander", _Provider({"another-session"}, [_SHELL_GUARD]))
    assert names() == baseline
    register("required", _Provider({target.id}, [_SHELL_GUARD]))
    assert names() == ["shell_guard", *baseline]


async def test_provider_deny_holds_across_engine_rebuilds_and_baseline_without_provider(
    conversation_store: SqlAlchemyConversationStore, register: Register
) -> None:
    """The DENY holds on every build and stops a later ALLOW-and-write; others are untouched."""
    spec = AgentSpec(
        spec_version=1,
        name="probe",
        guardrails=GuardrailsSpec(
            policies=[make_fixed_function_policy_spec("taint", fn_path=_ALLOW_AND_WRITE_PATH)]
        ),
    )
    guarded = conversation_store.create_conversation()
    other = conversation_store.create_conversation()
    assert _names(_build(spec, guarded.id, conversation_store)) == ["taint", *_REQUIRED]
    provider = _Provider({guarded.id}, [_SHELL_GUARD])
    unregister = register("required", provider)

    for _ in range(2):
        result = await _build(spec, guarded.id, conversation_store).evaluate(_tool_call())
        assert result.action == PolicyAction.DENY
        assert result.reason == _SHELL_REASON
        assert result.deciding_policies == ["shell_guard"]
    assert provider.calls == [guarded.id, guarded.id]
    assert "integrity" not in _labels(conversation_store, guarded.id)

    other_result = await _build(spec, other.id, conversation_store).evaluate(_tool_call())
    assert other_result.action == PolicyAction.ALLOW
    assert _labels(conversation_store, other.id)["integrity"] == "0"

    unregister()
    unregister()
    engine = _build(spec, guarded.id, conversation_store)
    assert _names(engine) == ["taint", *_REQUIRED]
    assert (await engine.evaluate(_tool_call())).action == PolicyAction.ALLOW


@pytest.mark.parametrize(
    "answer",
    [
        None,
        [object()],
        [FunctionPolicySpec(name="gone", on=None, function=FunctionRef(path="no_such.module.f"))],
        [
            FunctionPolicySpec(
                name="boom",
                on=None,
                function=FunctionRef(path=f"{__name__}.failing_factory", arguments={}),
            )
        ],
    ],
    ids=["raises", "not_a_policy_spec", "unresolvable_path", "factory_raises"],
)
async def test_raising_provider_denies_only_its_sessions_tool_calls(
    conversation_store: SqlAlchemyConversationStore,
    register: Register,
    caplog: pytest.LogCaptureFixture,
    answer: list[object] | None,
) -> None:
    """A provider failure denies that session's tool calls only, never its requests."""
    spec = AgentSpec(spec_version=1, name="probe")
    broken = conversation_store.create_conversation()
    healthy = conversation_store.create_conversation()
    if answer is None:
        provider = _Provider({broken.id, healthy.id}, fail_for={broken.id})
    else:
        provider = _Provider({broken.id}, answer)
    register("flaky", provider)
    caplog.set_level(logging.ERROR, logger="omnigent.runtime.policies.required_providers")

    engine = _build(spec, broken.id, conversation_store)
    assert _names(engine) == ["__required_policy_unavailable:flaky", *_REQUIRED]
    # The built-in approval would ask the user about this tool; the deny decides first.
    denied = await engine.evaluate(_tool_call("sys_add_policy"))
    assert denied.action == PolicyAction.DENY
    assert denied.deciding_policies == ["__required_policy_unavailable:flaky"]
    assert "flaky" in (denied.reason or "")
    assert "offline" not in (denied.reason or "")
    request = EvaluationContext(
        phase=Phase.REQUEST, content={"user_content": "hello", "attachments": []}
    )
    assert (await engine.evaluate(request)).action == PolicyAction.ALLOW
    healthy_engine = _build(spec, healthy.id, conversation_store)
    assert (await healthy_engine.evaluate(_tool_call())).action == PolicyAction.ALLOW
    _build(spec, broken.id, conversation_store)
    records = [r for r in caplog.records if "flaky" in r.getMessage()]
    # One traceback per registration, then one line per failure.
    assert [bool(r.exc_info) for r in records] == [True, False]
    assert {r.levelno for r in records} == {logging.ERROR}
    assert {getattr(r, "session_id", None) for r in records} == {broken.id}


def test_unavailable_policy_denies_tool_calls_only() -> None:
    evaluator = deny_tool_calls(reason="provider down")
    assert evaluator({"type": "tool_call", "data": {"name": "x"}}) == {
        "result": "DENY",
        "reason": "provider down",
    }
    for event_type in ("request", "tool_result", "response", "llm_request", "llm_response"):
        assert evaluator({"type": event_type})["result"] == "ALLOW"  # type: ignore[typeddict-item]


class _NoTruthValue:
    def __bool__(self) -> bool:
        raise RuntimeError("no truth value")


class _UnanswerableProvider(_Provider):
    """Answers ``applies`` with a value whose truth test raises."""

    def applies(self, spec: AgentSpec, conversation: Conversation | None) -> bool:
        return _NoTruthValue()  # type: ignore[return-value]  # a provider bug under test


def test_fast_path_evaluates_only_when_a_provider_applies(
    conversation_store: SqlAlchemyConversationStore,
    register: Register,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``any_policies_apply`` is True only for a session a provider claims (or cannot rule out)."""
    spec = AgentSpec(spec_version=1, name="probe")
    claimed = conversation_store.create_conversation()
    other = conversation_store.create_conversation()

    def fast(conversation: Conversation, phase: Phase = Phase.TOOL_CALL) -> bool:
        return any_policies_apply(
            spec=spec,
            conversation_id=conversation.id,
            default_policies=None,
            policy_store=None,
            phase=phase,
            tool_name="sys_os_shell" if phase == Phase.TOOL_CALL else None,
            conversation=conversation,
        )

    assert not fast(claimed)
    register("required", _Provider({claimed.id}))
    assert fast(claimed)
    assert fast(claimed, Phase.REQUEST)
    assert not fast(other)
    assert required_policies_apply(spec, claimed)
    assert not required_policies_apply(spec, other)

    caplog.set_level(logging.ERROR, logger="omnigent.runtime.policies.required_providers")
    for broken in (
        _Provider(set(), [_SHELL_GUARD], applies_error=RuntimeError("bug")),
        _UnanswerableProvider(set(), [_SHELL_GUARD]),
    ):
        caplog.clear()
        unregister = register("undecided", broken)
        assert fast(other)
        assert [s.name for s in required_policy_specs(spec, other)] == ["shell_guard"]
        records = [r for r in caplog.records if "undecided" in r.getMessage()]
        assert [bool(r.exc_info) for r in records] == [True, False]
        unregister()
        assert not fast(other)


def test_no_conversation_yields_no_provider_specs(
    conversation_store: SqlAlchemyConversationStore, register: Register
) -> None:
    spec = AgentSpec(spec_version=1, name="probe")
    provider = _Provider(None, [_SHELL_GUARD])
    register("required", provider)

    assert required_policies_apply(spec, None)
    assert required_policy_specs(spec, None) == []
    missing = _build(spec, uuid.uuid4().hex, conversation_store)
    assert _names(missing) == _REQUIRED
    assert provider.calls == []


def test_registry_runs_providers_in_name_order_with_identity_checked_unregister(
    conversation_store: SqlAlchemyConversationStore,
    register: Register,
    caplog: pytest.LogCaptureFixture,
) -> None:
    spec = AgentSpec(spec_version=1, name="probe")
    conversation = conversation_store.create_conversation()

    def provider(name: str) -> _Provider:
        return _Provider(None, [make_fixed_function_policy_spec(name)])

    def names() -> list[str]:
        return [s.name for s in required_policy_specs(spec, conversation)]

    register("b", provider("from_b"))
    unregister_first_a = register("a", provider("from_a"))
    assert names() == ["from_a", "from_b"]

    with caplog.at_level(logging.WARNING, logger="omnigent.runtime.policies.required_providers"):
        unregister_second_a = register("a", provider("from_a2"))
    assert any("'a'" in r.getMessage() for r in caplog.records)
    assert names() == ["from_a2", "from_b"]
    unregister_first_a()
    assert names() == ["from_a2", "from_b"]
    unregister_second_a()
    unregister_second_a()
    assert names() == ["from_b"]

    for invalid in ("", "has space", "x" * 65):
        with pytest.raises(ValueError, match="provider name"):
            register_required_policy_provider(invalid, provider("never"))
    shapeless = (object(), type("NoSpecs", (), {"applies": lambda *args: True})())
    for not_a_provider in shapeless:
        with pytest.raises(TypeError, match="callable applies and specs"):
            register_required_policy_provider("c", not_a_provider)  # type: ignore[arg-type]
    assert names() == ["from_b"]
