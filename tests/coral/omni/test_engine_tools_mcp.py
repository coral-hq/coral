"""Coral's engine tools through the session MCP proxy, decided on the in-memory port.

Each call runs ``_handle_mcp_tools_call`` with a real conversation row bound to
a runner, the real TOOL_CALL policy build and S10's grant check against
Coral's tool provider over the full tool list; only the decision port and the
binding store are fakes.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request

from coral.db.enum_codecs import RunPauseReason, RunStatus, SessionBindingRole, SlotRole
from coral.engine.types import HandoffEvaluated, HandoffReceived, Input, RetryStep
from coral.model.ir import CompiledGraph
from coral.omni.runner.tool_provider import CoralToolProvider
from coral.omni.server.tool_bridge import register_engine_tools
from coral.stores.session_bindings import SessionBinding
from coral.tools.catalog import CHOOSE_ARROW, ENGINE_TOOLS, SUBMIT_HANDOFF, EngineToolDecl
from coral.tools.dispatch import EngineToolCall, ToolDispatcher
from coral.tools.port import RunDecisionPort
from coral.tools.replies import STOP, not_run_member
from coral.tools.schemas import LoopUse, ToolReply
from omnigent.db.db_models import workspace_scope
from omnigent.policies.types import PolicyResult
from omnigent.runner.identity import RUNNER_TUNNEL_TOKEN_HEADER, token_bound_runner_id
from omnigent.runner.mcp_execution_registry import MCP_OPERATION_ID_PARAM
from omnigent.server.routes import sessions as sessions_mod
from omnigent.server.routes._sessions import orchestration
from omnigent.server.routes.sessions import _handle_mcp_tools_call
from omnigent.server.server_tools import server_tool
from omnigent.spec import AgentSpec, ExecutorSpec
from omnigent.spec.types import PolicyAction
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.tools import extensions
from tests.coral.tools.fake_decision_port import (
    WORKSPACE,
    FakeBindingLookup,
    InMemoryDecisionPort,
    step_binding,
)
from tests.coral.tools.test_choose_arrow import _finish_work, _next_pass, _review_loop
from tests.coral.tools.test_dispatch import _HeldPort
from tests.coral.workflow_builders import (
    arrow,
    compile_text,
    decision,
    end,
    start,
    step,
    workflow_text,
)
from tests.tools.test_extensions import installed_tool_providers

SESSION = "c" * 32
AGENT = "a" * 32
TOKEN = "coral-step-runner-token"
OPERATION = "mcpop_coral_1"
SLOT = "work||:0"
SUBMIT = SUBMIT_HANDOFF.name
CHOOSE = CHOOSE_ARROW.name
HANDOFF: dict[str, object] = {
    "activation_id": "work||",
    "status": "done",
    "report": "Parser implemented.",
}
BRIDGE_LOGGER = "coral.omni.server.tool_bridge"


def _graph(nodes: list[dict[str, object]], arrows: list[dict[str, object]]) -> CompiledGraph:
    return compile_text(workflow_text(nodes, arrows))[0]


def _plain() -> CompiledGraph:
    return _graph(
        [start(), step("work"), step("ship"), end()],
        [arrow("a1", "start", "work"), arrow("a2", "work", "ship"), arrow("a3", "ship", "end")],
    )


def _decision_first() -> CompiledGraph:
    return _graph(
        [start(), decision("choose"), step("ship"), end()],
        [
            arrow("a1", "start", "choose"),
            arrow("a2", "choose", "ship", label="approved"),
            arrow("a3", "choose", "end", label="rejected"),
            arrow("a4", "ship", "end"),
        ],
    )


def _spec(stance: str | None, harness: str = "claude-sdk") -> AgentSpec:
    """An agent of a generated Coral bundle with ``stance``; ``None`` is not a Coral bundle."""
    return AgentSpec(
        spec_version=1,
        executor=ExecutorSpec(type="omnigent", config={"harness": harness}),
        params={} if stance is None else {"coral": {"generated": {"stance": stance}}},
    )


def _runner_request(token: str = TOKEN) -> Request:
    """A ``/mcp`` request carrying runner tunnel ``token``; the server allow-lists none."""
    app = Starlette()
    app.state.runner_tunnel_tokens = None
    headers = [(RUNNER_TUNNEL_TOKEN_HEADER.lower().encode(), token.encode())]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers, "app": app})


class _NoAgentStore:
    """The spec loader is patched, so the agent store is never read."""

    def get(self, agent_id: str) -> None:
        raise AssertionError(f"agent store read for {agent_id!r}")


@dataclass
class _Mcp:
    """One session whose runner holds ``TOKEN``, with Coral's engine tools registered."""

    store: SqlAlchemyConversationStore
    stack: AsyncExitStack
    port: InMemoryDecisionPort = field(default_factory=InMemoryDecisionPort)
    lookup: FakeBindingLookup = field(default_factory=FakeBindingLookup)
    spec: AgentSpec = field(default_factory=lambda: _spec("implementer"))
    forwarded: list[dict[str, Any]] = field(default_factory=list)

    def register(self, port: RunDecisionPort | None) -> None:
        register_engine_tools(
            catalog=ENGINE_TOOLS, port=port, bindings=self.lookup, stack=self.stack
        )

    async def call(
        self,
        name: str,
        arguments: object,
        *,
        op: object = OPERATION,
        request: Request | None = None,
        proven: bool = True,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"name": name, "arguments": arguments}
        if op is not None:
            params[MCP_OPERATION_ID_PARAM] = op
        if request is None and proven:
            request = _runner_request()
        with workspace_scope(WORKSPACE):
            response = await _handle_mcp_tools_call(
                rpc_id=1,
                session_id=SESSION,
                params=params,
                conversation_store=self.store,
                agent_store=_NoAgentStore(),  # type: ignore[arg-type]
                runner_router=None,
                actor=None,
                request=request,
            )
        return json.loads(bytes(response.body))


@pytest.fixture
async def mcp(db_uri: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_Mcp]:
    store = SqlAlchemyConversationStore(db_uri)
    # A non-default workspace: the bridge must read the request's own.
    with workspace_scope(WORKSPACE):
        store.create_conversation(
            conversation_id=SESSION, agent_id=AGENT, runner_id=token_bound_runner_id(TOKEN)
        )

    async with AsyncExitStack() as stack:
        harness = _Mcp(store=store, stack=stack)

        def runner_execute(request: httpx.Request) -> httpx.Response:
            harness.forwarded.append(json.loads(request.content))
            return httpx.Response(200, json={"result": {"output": "runner output"}})

        runner = await stack.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.MockTransport(runner_execute), base_url="http://runner.test"
            )
        )

        async def get_runner(*_args: object, **_kwargs: object) -> httpx.AsyncClient:
            return runner

        monkeypatch.setattr(sessions_mod, "_load_agent_spec_for_session", lambda *_: harness.spec)
        monkeypatch.setattr(sessions_mod, "_get_runner_client", get_runner)
        stack.enter_context(installed_tool_providers(CoralToolProvider(ENGINE_TOOLS)))
        harness.register(harness.port)
        yield harness
        assert harness.forwarded == []
        harness.port.assert_folds()


def _text(payload: dict[str, Any]) -> str:
    assert "result" in payload, payload
    return payload["result"]["content"][0]["text"]


def _reply(payload: dict[str, Any]) -> ToolReply:
    return ToolReply.from_json(_text(payload))


def _error(payload: dict[str, Any]) -> str:
    assert payload["error"]["code"] == -32000, payload
    return payload["error"]["message"]


async def test_a_handoff_and_a_choice_over_mcp_reach_the_engine(mcp: _Mcp) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))

    handoff = await mcp.call(f"mcp__omnigent__{SUBMIT}", HANDOFF)

    assert _reply(handoff) == ToolReply(accepted=True, next=STOP)
    assert [entry.input.kind for entry in mcp.port.log()[-2:]] == [
        "handoff_received",
        "handoff_evaluated",
    ]
    assert mcp.lookup.reads == [(WORKSPACE, SESSION)]

    # The same session as a run's orchestrator, with an orchestrator bundle.
    mcp.port.add_run(_decision_first(), run_id="run-2")
    mcp.port.set_row(status=RunStatus.RUNNING, orchestrator_session_id=SESSION, run_id="run-2")
    mcp.lookup.add(
        step_binding(
            "orchestrator", session_id=SESSION, run_id="run-2", slot_role=SlotRole.ORCHESTRATOR
        )
    )
    mcp.spec = _spec("orchestrator")

    choice = await mcp.call(
        CHOOSE, {"decision_id": "choose||", "label": "approved", "reason": "Looks right."}
    )

    reply = _reply(choice)
    assert reply.accepted and "'ship'" in reply.next
    assert mcp.port.log(run_id="run-2")[-1].input.kind == "choose_arrow"


async def test_stale_generation_handoff_over_mcp_is_a_structured_rejection(mcp: _Mcp) -> None:
    mcp.port.add_run(_plain())
    # The step blocked and the operator retried it: the slot is on generation 2.
    mcp.port.apply(
        HandoffReceived(slot_id=SLOT, body="blocked"),
        HandoffEvaluated(slot_id=SLOT, outcome="blocked"),
        RetryStep(node_id="work"),
    )
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION, generation=1))
    version, log_length = mcp.port.row().version, len(mcp.port.log())

    payload = await mcp.call(SUBMIT, HANDOFF)

    # A normal tool result the model reads, not a transport fault.
    reply = _reply(payload)
    assert (reply.accepted, reply.reason, reply.allowed_values) == (False, "slot.superseded", ())
    assert "Stop now and end your turn" in reply.next
    assert (mcp.port.row().version, len(mcp.port.log())) == (version, log_length)
    assert mcp.port.stored_replies() == {}


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("no_operation_id", "Coral tools need the runner's operation id"),
        ("another_runner", "Coral tools can be called only by the session's own runner"),
        ("no_request", "Coral tools can be called only by the session's own runner"),
        ("lookup_error", "could not look up this session; retry"),
        ("no_port", "Coral's workflow engine is not running on this server"),
    ],
)
async def test_transport_faults_are_32000(
    mcp: _Mcp, caplog: pytest.LogCaptureFixture, fault: str, message: str
) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))
    version = mcp.port.row().version
    if fault == "lookup_error":
        mcp.lookup.error = RuntimeError("database is locked")
    if fault == "no_port":
        mcp.register(None)

    payload = await mcp.call(
        SUBMIT,
        HANDOFF,
        op=None if fault == "no_operation_id" else OPERATION,
        request=_runner_request("another-runner") if fault == "another_runner" else None,
        proven=fault != "no_request",
    )

    assert _error(payload) == message
    assert (mcp.port.find_reply_calls, mcp.port.decide_calls) == (0, 0)
    assert mcp.port.row().version == version
    # Only a call that passed every transport check reads the binding.
    assert mcp.lookup.reads == ([(WORKSPACE, SESSION)] if fault == "lookup_error" else [])
    records = [record for record in caplog.records if record.name == BRIDGE_LOGGER]
    if fault == "lookup_error":
        assert len(records) == 1 and records[0].exc_info is not None
        assert "database is locked" not in message
    else:
        # Each transport refusal leaves one warning naming the session, never the call.
        (record,) = records
        line = record.getMessage()
        assert record.levelno == logging.WARNING
        assert SESSION in line and message in line
        assert OPERATION not in line and "Parser implemented" not in line


async def test_a_dispatcher_transport_error_is_32000_over_mcp(
    mcp: _Mcp, caplog: pytest.LogCaptureFixture
) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))
    # Another writer changes the run before each of the port's five commits.
    mcp.port.lose_next_commits(5)
    log_length = len(mcp.port.log())

    payload = await mcp.call(SUBMIT, HANDOFF)

    assert _error(payload) == "Coral is busy with this run; retry shortly"
    assert (mcp.port.decide_calls, mcp.port.plan_calls) == (1, 5)
    assert len(mcp.port.log()) == log_length
    assert mcp.port.stored_replies() == {}
    # Mapped by the bridge: S10's "server tool failed" error and traceback never appear.
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


async def test_registration_refuses_a_tool_no_planner_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads: list[str] = []

    def load_providers() -> tuple[object, ...]:
        loads.append("loaded")
        return ()

    monkeypatch.setattr(extensions, "default_tool_providers", load_providers)
    unplanned = dataclasses.replace(SUBMIT_HANDOFF, name="coral_unplanned")

    async with AsyncExitStack() as stack:
        with pytest.raises(ValueError, match="no planner answers engine tool 'coral_unplanned'"):
            register_engine_tools(
                catalog=(SUBMIT_HANDOFF, unplanned),
                port=InMemoryDecisionPort(),
                bindings=FakeBindingLookup(),
                stack=stack,
            )
        # Refused before anything registered or the providers were loaded.
        assert server_tool(SUBMIT) is None and server_tool("coral_unplanned") is None
        # The empty production catalog registers nothing and loads no provider.
        register_engine_tools(catalog=(), port=None, bindings=FakeBindingLookup(), stack=stack)
    assert loads == []


class _KeepsFoundRows:
    """Shaped like a positive-only cache: it answers lookups but does not read fresh."""

    def find_by_session(self, workspace_id: int, session_id: str) -> SessionBinding | None:
        raise AssertionError("a refused lookup is never read")


class _SaysItKeepsRows(_KeepsFoundRows):
    reads_fresh = False


@pytest.mark.parametrize("catalog", [ENGINE_TOOLS, ()], ids=["catalog", "empty_catalog"])
async def test_registration_refuses_a_lookup_that_keeps_found_rows(
    catalog: tuple[EngineToolDecl, ...],
) -> None:
    # The planners read a binding's progress, which a cache of found rows would serve stale.
    lookups: list[Any] = [_KeepsFoundRows(), _SaysItKeepsRows()]
    for lookup in lookups:
        async with AsyncExitStack() as stack:
            with pytest.raises(TypeError, match="reads_fresh"):
                register_engine_tools(
                    catalog=catalog,
                    port=InMemoryDecisionPort(),
                    bindings=lookup,
                    stack=stack,
                )
    assert all(server_tool(decl.name) is None for decl in ENGINE_TOOLS)


async def test_an_unbound_session_is_not_run_member(mcp: _Mcp) -> None:
    mcp.port.add_run(_plain())
    # The same session id bound in another workspace is not this request's binding.
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION, workspace_id=WORKSPACE + 1))

    payload = await mcp.call(SUBMIT, HANDOFF)

    assert _reply(payload) == not_run_member()
    assert mcp.lookup.reads == [(WORKSPACE, SESSION)]
    assert (mcp.port.find_reply_calls, mcp.port.decide_calls) == (0, 0)


async def test_one_operation_id_over_mcp_decides_once(mcp: _Mcp) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))

    first = await mcp.call(SUBMIT, HANDOFF)
    resent = await mcp.call(SUBMIT, HANDOFF)

    assert _text(resent) == _text(first)
    assert _reply(first) == ToolReply(accepted=True, next=STOP)
    assert mcp.port.decide_calls == 1
    assert len(mcp.port.stored_replies()) == 1
    kinds = [entry.input.kind for entry in mcp.port.log()]
    assert kinds.count("handoff_received") == 1

    # A new operation id is a new decision; the slot answers with its receipt.
    again = await mcp.call(SUBMIT, HANDOFF, op="mcpop_coral_2")
    assert _reply(again) == ToolReply(accepted=True, next=STOP, duplicate=True)
    assert mcp.port.decide_calls == 2
    assert [entry.input.kind for entry in mcp.port.log()] == kinds


async def test_a_policy_deny_stops_the_call_before_the_handler(
    mcp: _Mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))

    async def deny(_session_id, _spec, _store, _conv, _ctx):  # type: ignore[no-untyped-def]
        return None, PolicyResult(action=PolicyAction.DENY, reason="blocked")

    monkeypatch.setattr(orchestration, "_evaluate_policy_with_fresh_engine", deny)

    payload = await mcp.call(SUBMIT, HANDOFF)

    assert _error(payload) == "Denied by policy: blocked"
    assert mcp.lookup.reads == []
    assert (mcp.port.find_reply_calls, mcp.port.decide_calls) == (0, 0)


async def test_bridge_logs_name_the_session_not_the_arguments(
    mcp: _Mcp, caplog: pytest.LogCaptureFixture
) -> None:
    mcp.port.add_run(_plain())
    caplog.set_level(logging.INFO, logger=BRIDGE_LOGGER)

    await mcp.call(SUBMIT, {**HANDOFF, "report": "secret report text"})

    lines = [record.getMessage() for record in caplog.records if record.name == BRIDGE_LOGGER]
    assert len(lines) == 1
    assert SESSION in lines[0] and "not_run_member" in lines[0]
    assert "secret" not in lines[0]


def _orchestrate(
    mcp: _Mcp, graph: CompiledGraph, inputs: Sequence[Input] = (), *, run_id: str = "run-2"
) -> None:
    """Make ``SESSION`` the current orchestrator of a new run of ``graph`` after ``inputs``."""
    mcp.port.add_run(graph, inputs, run_id=run_id)
    mcp.port.set_row(status=RunStatus.RUNNING, orchestrator_session_id=SESSION, run_id=run_id)
    mcp.lookup.add(
        step_binding(
            "orchestrator", session_id=SESSION, run_id=run_id, slot_role=SlotRole.ORCHESTRATOR
        )
    )
    mcp.spec = _spec("orchestrator")


def _assert_untouched(mcp: _Mcp, *, run_id: str = "run-1") -> None:
    assert (mcp.port.find_reply_calls, mcp.port.decide_calls) == (0, 0)
    assert mcp.port.stored_replies(run_id=run_id) == {}


@pytest.mark.parametrize(
    "op",
    ["", "x" * 129, 5, ["mcpop"], {"id": "mcpop"}],
    ids=["empty", "129", "int", "list", "dict"],
)
async def test_a_malformed_operation_id_never_reaches_the_bridge(mcp: _Mcp, op: object) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))

    payload = await mcp.call(SUBMIT, HANDOFF, op=op)

    assert _error(payload) == "Invalid runner MCP operation id"
    assert mcp.lookup.reads == []
    _assert_untouched(mcp)


async def test_an_operation_id_at_the_length_limit_is_taken(mcp: _Mcp) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))

    payload = await mcp.call(SUBMIT, HANDOFF, op="x" * 128)

    assert _reply(payload) == ToolReply(accepted=True, next=STOP)


@pytest.mark.parametrize("arguments", [["x"], "text", 5, True], ids=["list", "str", "int", "bool"])
async def test_arguments_that_are_not_an_object_never_reach_the_bridge(
    mcp: _Mcp, arguments: object
) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))

    payload = await mcp.call(SUBMIT, arguments)

    assert _error(payload) == "Invalid tool arguments: expected an object"
    assert mcp.lookup.reads == []
    _assert_untouched(mcp)


async def test_null_arguments_are_an_empty_object_and_a_structured_refusal(mcp: _Mcp) -> None:
    _orchestrate(mcp, _decision_first())

    payload = await mcp.call(CHOOSE, None)

    reply = _reply(payload)
    assert (reply.accepted, reply.reason, reply.field) == (False, "tool.illegal", "decision_id")
    assert reply.allowed_values == ("choose||",)
    assert mcp.port.stored_replies(run_id="run-2") == {}


@pytest.mark.parametrize(
    ("stance", "harness", "tool"),
    [
        ("implementer", "claude-sdk", CHOOSE),
        ("reviewer", "claude-sdk", CHOOSE),
        ("orchestrator", "claude-sdk", SUBMIT),
        ("anchor", "claude-sdk", SUBMIT),
        (None, "claude-sdk", SUBMIT),
        ("implementer", "claude-native", SUBMIT),
    ],
    ids=[
        "implementer_choose",
        "reviewer_choose",
        "orchestrator_submit",
        "anchor",
        "not_coral",
        "native",
    ],
)
async def test_a_tool_the_agent_was_not_given_is_not_run_by_the_server(
    mcp: _Mcp, stance: str | None, harness: str, tool: str
) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))
    mcp.spec = _spec(stance, harness)

    payload = await mcp.call(tool, HANDOFF)

    # The proxy forwards it to the runner as any other tool; Coral never sees it.
    assert _text(payload) == "runner output"
    assert [body["params"]["name"] for body in mcp.forwarded] == [tool]
    mcp.forwarded.clear()
    assert mcp.lookup.reads == []
    _assert_untouched(mcp)


@pytest.mark.parametrize(
    ("binding", "orchestrator"),
    [
        (step_binding("choose||:0", session_id=SESSION, run_id="run-2"), SESSION),
        (
            step_binding(
                None,
                session_id=SESSION,
                run_id="run-2",
                role=SessionBindingRole.ANCHOR,
                slot_role=None,
            ),
            SESSION,
        ),
        (
            step_binding(
                "orchestrator",
                session_id=SESSION,
                run_id="run-2",
                slot_role=SlotRole.ORCHESTRATOR,
            ),
            "d" * 32,
        ),
    ],
    ids=["step", "anchor", "replaced_orchestrator"],
)
async def test_only_the_current_orchestrator_chooses_over_mcp(
    mcp: _Mcp, binding: SessionBinding, orchestrator: str
) -> None:
    _orchestrate(mcp, _decision_first())
    mcp.port.set_row(
        status=RunStatus.RUNNING, orchestrator_session_id=orchestrator, run_id="run-2"
    )
    mcp.lookup.add(binding)
    version, log_length = mcp.port.row(run_id="run-2").version, len(mcp.port.log(run_id="run-2"))

    payload = await mcp.call(
        CHOOSE, {"decision_id": "choose||", "label": "approved", "reason": "Looks right."}
    )

    reply = _reply(payload)
    assert (reply.accepted, reply.reason) == (False, "not_orchestrator")
    assert "Stop now and end your turn" in reply.next
    assert mcp.port.row(run_id="run-2").version == version
    assert len(mcp.port.log(run_id="run-2")) == log_length
    assert mcp.port.stored_replies(run_id="run-2") == {}


@pytest.mark.parametrize(
    ("status", "pause_reason", "submit_reason", "choose_reason"),
    [
        (RunStatus.PAUSED, RunPauseReason.DRIFT, "run.paused", "run.paused"),
        (RunStatus.CANCELLED, None, "run_cancelled", "run_cancelled"),
        (RunStatus.COMPLETED, None, "slot_closed", "decision_closed"),
    ],
    ids=["paused", "cancelled", "completed"],
)
async def test_a_stopped_run_answers_both_tools_over_mcp_with_stop(
    mcp: _Mcp,
    status: RunStatus,
    pause_reason: RunPauseReason | None,
    submit_reason: str,
    choose_reason: str,
) -> None:
    mcp.port.add_run(_plain())
    mcp.port.set_row(status=status, pause_reason=pause_reason)
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))
    log_length = len(mcp.port.log())

    submitted = _reply(await mcp.call(SUBMIT, HANDOFF))

    _orchestrate(mcp, _decision_first())
    mcp.port.set_row(
        status=status, pause_reason=pause_reason, orchestrator_session_id=SESSION, run_id="run-2"
    )
    chosen = _reply(
        await mcp.call(
            CHOOSE,
            {"decision_id": "choose||", "label": "approved", "reason": "Looks right."},
            op="mcpop_coral_2",
        )
    )

    for reply, reason in ((submitted, submit_reason), (chosen, choose_reason)):
        assert (reply.accepted, reply.reason) == (False, reason)
        assert "Stop now and end your turn" in reply.next
        assert "coral_submit_handoff" not in reply.next
    assert len(mcp.port.log()) == log_length
    assert mcp.port.stored_replies() == mcp.port.stored_replies(run_id="run-2") == {}


async def test_choices_over_mcp_refuse_bad_input_and_redirect_at_the_loop_limit(
    mcp: _Mcp,
) -> None:
    _orchestrate(mcp, _review_loop(), _finish_work("a4:1"), run_id="run-1")
    revise = {"decision_id": "review||a4:1", "label": "revise", "reason": "Needs tests."}

    illegal = _reply(await mcp.call(CHOOSE, {**revise, "label": "nope"}, op="op-1"))
    empty = _reply(await mcp.call(CHOOSE, {**revise, "reason": "  "}, op="op-2"))

    assert (illegal.reason, illegal.field, illegal.allowed_values) == (
        "tool.illegal",
        "label",
        ("approved", "revise"),
    )
    assert (empty.reason, empty.field) == ("tool.illegal", "reason")
    assert mcp.port.stored_replies() == {}

    first = _reply(await mcp.call(CHOOSE, revise, op="op-3"))
    assert (first.accepted, first.redirected, first.loop) == (True, False, LoopUse(2, 2))
    _next_pass(mcp.port, "a4:2")

    second = _reply(await mcp.call(CHOOSE, {**revise, "decision_id": "review||a4:2"}, op="op-4"))

    assert (second.accepted, second.redirected, second.loop) == (True, True, LoopUse(2, 2))
    assert "'escalate'" in second.next
    assert [entry.input.kind for entry in mcp.port.log()].count("choose_arrow") == 2


async def test_a_duplicate_operation_id_sent_concurrently_and_after_a_restart_decides_once(
    mcp: _Mcp, monkeypatch: pytest.MonkeyPatch
) -> None:
    mcp.port.add_run(_plain())
    mcp.lookup.add(step_binding(SLOT, session_id=SESSION))
    held = _HeldPort(mcp.port)
    mcp.register(held)
    dispatch = ToolDispatcher.dispatch
    entered: list[EngineToolCall] = []

    async def release_once_both_entered(self: ToolDispatcher, call: EngineToolCall) -> ToolReply:
        entered.append(call)
        if len(entered) == 2:
            # The resent call joins the held decision before it can finish.
            held.release.set()
        return await dispatch(self, call)

    monkeypatch.setattr(ToolDispatcher, "dispatch", release_once_both_entered)

    first, resent = await asyncio.gather(mcp.call(SUBMIT, HANDOFF), mcp.call(SUBMIT, HANDOFF))

    assert _text(first) == _text(resent)
    assert _reply(first) == ToolReply(accepted=True, next=STOP)
    assert (mcp.port.decide_calls, mcp.port.find_reply_calls) == (1, 1)

    # A restarted server registers a new dispatcher; the stored reply still answers.
    mcp.register(mcp.port)
    after_restart = await mcp.call(SUBMIT, HANDOFF)

    assert _text(after_restart) == _text(first)
    assert (mcp.port.decide_calls, mcp.port.find_reply_calls) == (1, 2)
    kinds = [entry.input.kind for entry in mcp.port.log()]
    assert kinds.count("handoff_received") == 1
