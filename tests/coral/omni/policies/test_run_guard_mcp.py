"""The run guard and the orchestrator allowlist on the session MCP proxy (Omnigent tool calls).

Each call runs ``_handle_mcp_tools_call`` in a non-default workspace with a
real conversation row, the real TOOL_CALL policy build and Coral's guards
wired as the lifespan wires them (``_wire_guards``) over a fake run store and
binding lookup. The engine tools are registered with the in-memory decision
port, so a call the guards let through gets the engine's own answer.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from coral.db.enum_codecs import RunPauseReason, RunStatus, SessionBindingRole, SlotRole
from coral.omni.runner.tool_provider import CoralToolProvider
from coral.omni.server.plugin import _wire_guards
from coral.omni.server.sessions import ROLE_LABEL_KEY, RUN_ID_LABEL_KEY
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import RunStartSpec, Transition
from coral.tools.catalog import ENGINE_TOOLS
from coral.tools.schemas import ToolReply
from omnigent.db.db_models import workspace_scope
from omnigent.runner.identity import token_bound_runner_id
from omnigent.server.routes import sessions as sessions_mod
from omnigent.server.routes.sessions import _handle_mcp_tools_call, _pending_policy_ask_writes
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE
from tests.coral.omni.policies.conftest import SESSION_CAP_USD
from tests.coral.omni.test_engine_tools_mcp import (
    AGENT,
    CHOOSE,
    HANDOFF,
    SESSION,
    SLOT,
    SUBMIT,
    TOKEN,
    _decision_first,
    _error,
    _Mcp,
    _NoAgentStore,
    _plain,
    _reply,
    _runner_request,
    _spec,
    _text,
)
from tests.coral.tools.fake_decision_port import WORKSPACE, step_binding
from tests.tools.test_extensions import installed_tool_providers

OMNIGENT = "mcp__omnigent__"
STOP = "Stop now and end your turn"
ORCHESTRATOR_DENY = (
    "Denied by policy: [orchestrator] A Coral orchestrator can only call coral_choose_arrow "
    "(and ToolSearch to load it)."
)


@dataclass
class _Guarded:
    """The session's MCP proxy, and the run store whose stored status the run guard reads."""

    mcp: _Mcp
    runs: FakeRunStore

    def start_run(self, graph: Any, *, orchestrator: bool = False) -> str:
        """A running run in both the run store and the engine's port; the session bound to it."""
        run = self.runs.start_run(RunStartSpec("wf", "v1", "Run", "", workspace_id=WORKSPACE))
        self.set_status(run.id, RunStatus.RUNNING)
        self.mcp.port.add_run(graph, run_id=run.id)
        if orchestrator:
            self.mcp.port.set_row(
                status=RunStatus.RUNNING, orchestrator_session_id=SESSION, run_id=run.id
            )
        self.mcp.lookup.add(
            step_binding(
                "orchestrator" if orchestrator else SLOT,
                session_id=SESSION,
                run_id=run.id,
                slot_role=SlotRole.ORCHESTRATOR if orchestrator else SlotRole.STEP_AGENT,
            )
        )
        return run.id

    def set_status(
        self, run_id: str, status: RunStatus, *, reason: RunPauseReason | None = None
    ) -> None:
        """Commit *status* through the run store, as a drift or budget pause does."""
        _, version = self.runs.load_run_state(run_id, workspace_id=WORKSPACE)
        self.runs.apply_transition(
            run_id,
            version,
            Transition(
                status=int(status),
                pause_reason=None if reason is None else int(reason),
                clear_pause_reason=reason is None,
            ),
            workspace_id=WORKSPACE,
        )


@pytest.fixture
async def guarded(db_uri: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_Guarded]:
    store = SqlAlchemyConversationStore(db_uri)
    with workspace_scope(WORKSPACE):
        store.create_conversation(
            conversation_id=SESSION, agent_id=AGENT, runner_id=token_bound_runner_id(TOKEN)
        )

    async with AsyncExitStack() as stack:
        mcp = _Mcp(store=store, stack=stack)

        def runner_execute(request: httpx.Request) -> httpx.Response:
            mcp.forwarded.append(json.loads(request.content))
            return httpx.Response(200, json={"result": {"output": "runner output"}})

        runner = await stack.enter_async_context(
            httpx.AsyncClient(
                transport=httpx.MockTransport(runner_execute), base_url="http://runner.test"
            )
        )

        async def get_runner(*_args: object, **_kwargs: object) -> httpx.AsyncClient:
            return runner

        monkeypatch.setattr(sessions_mod, "_load_agent_spec_for_session", lambda *_: mcp.spec)
        monkeypatch.setattr(sessions_mod, "_get_runner_client", get_runner)
        stack.enter_context(installed_tool_providers(CoralToolProvider(ENGINE_TOOLS)))
        mcp.register(mcp.port)
        runs = FakeRunStore(default_workspace_id=WORKSPACE)
        # The provider, the commit hook and the budget pauser, as the lifespan registers them.
        _wire_guards(
            run_store=runs, bindings=mcp.lookup, session_cap_usd=SESSION_CAP_USD, stack=stack
        )
        yield _Guarded(mcp=mcp, runs=runs)
        mcp.port.assert_folds()


def _forwarded_tools(guarded: _Guarded) -> list[str]:
    return [call["params"]["name"] for call in guarded.mcp.forwarded]


async def test_paused_step_mcp_shell_call_is_denied_and_handoff_reaches_the_engine(
    guarded: _Guarded,
) -> None:
    run_id = guarded.start_run(_plain())
    # The drift pause commits through the run store (the guard's source); the engine's own
    # row is paused too, so the handoff gets the engine's run.paused reply.
    guarded.set_status(run_id, RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    guarded.mcp.port.set_row(
        status=RunStatus.PAUSED, pause_reason=RunPauseReason.DRIFT, run_id=run_id
    )

    for name in ("sys_os_shell", f"{OMNIGENT}sys_os_shell", "coral_x"):
        message = _error(await guarded.mcp.call(name, {"command": "ls"}))
        assert message.startswith("Denied by policy: [run.paused] The Coral run is paused (drift)")
        assert STOP in message and "coral_submit_handoff" not in message
    assert guarded.mcp.forwarded == []

    # The exact engine tool passes the guard and gets the engine's structured answer.
    handoff = _reply(await guarded.mcp.call(f"{OMNIGENT}{SUBMIT}", HANDOFF))
    assert (handoff.accepted, handoff.reason) == (False, "run.paused")
    assert "(drift)" in handoff.next and STOP in handoff.next
    assert guarded.mcp.port.decide_calls == 1
    assert guarded.mcp.forwarded == []


async def test_state_change_between_calls_applies_to_the_second(guarded: _Guarded) -> None:
    run_id = guarded.start_run(_plain())

    assert _text(await guarded.mcp.call("sys_os_shell", {"command": "ls"})) == "runner output"
    # Paused through the run store between the calls: its commit hook drops the cached status.
    guarded.set_status(run_id, RunStatus.PAUSED, reason=RunPauseReason.USER)
    denied = _error(await guarded.mcp.call("sys_os_shell", {"command": "ls"}))
    assert denied.startswith("Denied by policy: [run.paused] The Coral run is paused (user)")
    # Resumed: the next call runs again, with no wait for the cache to expire.
    guarded.set_status(run_id, RunStatus.RUNNING)
    assert _text(await guarded.mcp.call("sys_os_shell", {"command": "pwd"})) == "runner output"
    guarded.set_status(run_id, RunStatus.CANCELLED)
    cancelled = _error(await guarded.mcp.call("sys_os_shell", {"command": "ls"}))
    assert cancelled.startswith("Denied by policy: [run.cancelled]")

    assert _forwarded_tools(guarded) == ["sys_os_shell", "sys_os_shell"]
    # Six policy builds (two per forwarded call), one binding read: the provider uses the
    # lifespan's cache of found bindings, not the store the engine tools read fresh.
    assert guarded.mcp.lookup.reads == [(WORKSPACE, SESSION)]


async def test_over_cap_step_is_denied_and_its_run_paused_then_the_run_guard_answers(
    guarded: _Guarded,
) -> None:
    run_id = guarded.start_run(_plain())
    # The session's own priced spend, as Omnigent records it after a turn.
    with workspace_scope(WORKSPACE):
        guarded.mcp.store.set_session_usage(SESSION, {"total_cost_usd": SESSION_CAP_USD})

    denied = _error(await guarded.mcp.call("sys_os_shell", {"command": "ls"}))
    assert denied == (
        "Denied by policy: [budget] This session has spent about $25.00 of its $25.00 cap "
        f"(an estimate), so Coral paused the run. {STOP}."
    )
    # The lifespan's pauser committed the pause through the run store.
    run = guarded.runs.get_run(run_id, workspace_id=WORKSPACE)
    assert run is not None
    assert (run.status, run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.BUDGET)
    # That commit cleared the status cache, so the next call meets the run guard first.
    paused = _error(await guarded.mcp.call(f"{OMNIGENT}sys_os_shell", {"command": "pwd"}))
    assert paused.startswith("Denied by policy: [run.paused] The Coral run is paused (budget)")
    assert guarded.mcp.forwarded == []


async def test_orchestrator_mcp_edit_tool_is_denied(guarded: _Guarded) -> None:
    run_id = guarded.start_run(_decision_first(), orchestrator=True)
    # The agent carries no Coral guardrails: the allowlist comes from the binding row.
    guarded.mcp.spec = _spec("orchestrator")

    for name in ("sys_os_write", f"{OMNIGENT}sys_os_write", SUBMIT, f"{OMNIGENT}{SUBMIT}"):
        arguments: dict[str, object] = HANDOFF if SUBMIT in name else {"path": "a", "content": ""}
        assert _error(await guarded.mcp.call(name, arguments)) == ORCHESTRATOR_DENY, name
    assert guarded.mcp.forwarded == []
    assert guarded.mcp.port.decide_calls == 0

    choice = _reply(
        await guarded.mcp.call(
            CHOOSE, {"decision_id": "choose||", "label": "approved", "reason": "Looks right."}
        )
    )
    assert isinstance(choice, ToolReply) and choice.accepted
    assert guarded.mcp.port.log(run_id=run_id)[-1].input.kind == "choose_arrow"


def _count_run_reads(guarded: _Guarded, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record each run status read the guards make."""
    reads: list[str] = []
    read = guarded.runs.get_run

    def get_run(run_id: str, *, workspace_id: int | None = None) -> object:
        reads.append(run_id)
        return read(run_id, workspace_id=workspace_id)

    monkeypatch.setattr(guarded.runs, "get_run", get_run)
    return reads


def _set_labels(guarded: _Guarded, labels: dict[str, str]) -> None:
    with workspace_scope(WORKSPACE):
        guarded.mcp.store.set_labels(SESSION, labels)


async def test_anchor_mcp_calls_are_all_denied_engine_tools_included(guarded: _Guarded) -> None:
    run = guarded.runs.start_run(RunStartSpec("wf", "v1", "Run", "", workspace_id=WORKSPACE))
    guarded.set_status(run.id, RunStatus.RUNNING)
    guarded.mcp.lookup.add(
        step_binding(
            None, session_id=SESSION, run_id=run.id, role=SessionBindingRole.ANCHOR, slot_role=None
        )
    )
    calls: list[tuple[str, dict[str, object]]] = [
        ("sys_os_shell", {"command": "ls"}),
        (f"{OMNIGENT}sys_os_write", {"path": "a", "content": ""}),
        ("ToolSearch", {"query": "coral"}),
        (SUBMIT, HANDOFF),
        (f"{OMNIGENT}{CHOOSE}", {"decision_id": "choose||", "label": "approved", "reason": "."}),
    ]

    for name, arguments in calls:
        message = _error(await guarded.mcp.call(name, arguments))
        assert message == "Denied by policy: [anchor] The Coral run anchor does not run tools.", (
            name
        )
    assert guarded.mcp.forwarded == []
    assert guarded.mcp.port.decide_calls == 0


async def test_an_unbound_session_reads_no_run_and_its_calls_run(
    guarded: _Guarded, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = _count_run_reads(guarded, monkeypatch)
    run = guarded.runs.start_run(RunStartSpec("wf", "v1", "Run", "", workspace_id=WORKSPACE))
    guarded.set_status(run.id, RunStatus.PAUSED, reason=RunPauseReason.DRIFT)

    # An ordinary agent with no Coral label: Coral's provider never looks.
    guarded.mcp.spec = _spec(None)
    assert _text(await guarded.mcp.call("sys_os_shell", {"command": "ls"})) == "runner output"
    assert (guarded.mcp.lookup.reads, reads) == ([], [])

    # A label naming the paused run, with no binding row: the provider looks (once per
    # policy build: the call and its result), finds nothing and reads no run.
    _set_labels(guarded, {RUN_ID_LABEL_KEY: run.id, ROLE_LABEL_KEY: "step_agent"})
    assert _text(await guarded.mcp.call("sys_os_shell", {"command": "pwd"})) == "runner output"
    assert guarded.mcp.lookup.reads == [(WORKSPACE, SESSION)] * 2
    assert reads == []
    assert _forwarded_tools(guarded) == ["sys_os_shell", "sys_os_shell"]


async def test_closing_or_reopening_a_bound_session_applies_to_the_next_call(
    guarded: _Guarded,
) -> None:
    guarded.start_run(_plain())

    assert _text(await guarded.mcp.call("sys_os_shell", {"command": "ls"})) == "runner output"
    _set_labels(guarded, {CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE})
    closed = _error(await guarded.mcp.call("sys_os_shell", {"command": "ls"}))
    assert closed == f"Denied by policy: [session.closed] Coral closed this step. {STOP}."
    # Any other value is not Coral's close.
    _set_labels(guarded, {CLOSED_LABEL_KEY: "false"})
    assert _text(await guarded.mcp.call("sys_os_shell", {"command": "pwd"})) == "runner output"
    assert _forwarded_tools(guarded) == ["sys_os_shell", "sys_os_shell"]


async def test_an_approval_granted_after_the_run_paused_is_denied_on_retry(
    guarded: _Guarded,
) -> None:
    run_id = guarded.start_run(_plain())
    arguments = {"name": "audit", "handler": "omnigent.policies.builtins.safety.ask_on_add_policy"}

    # The builder's own approval ASKs while the run runs; the runner parks for the user.
    asked = await guarded.mcp.call("sys_add_policy", arguments)
    assert asked["result"]["resultType"] == "input_required", asked
    (elicitation_id,) = asked["result"]["inputRequests"]
    try:
        guarded.set_status(run_id, RunStatus.PAUSED, reason=RunPauseReason.USER)
        # The user approves; the retry re-evaluates and the run guard answers first.
        with workspace_scope(WORKSPACE):
            response = await _handle_mcp_tools_call(
                rpc_id=2,
                session_id=SESSION,
                params={
                    "name": "sys_add_policy",
                    "arguments": arguments,
                    "requestState": asked["result"]["requestState"],
                    "inputResponses": {elicitation_id: {"action": "accept"}},
                },
                conversation_store=guarded.mcp.store,
                agent_store=_NoAgentStore(),  # type: ignore[arg-type]
                runner_router=None,
                actor=None,
                request=_runner_request(),
            )
        denied = _error(json.loads(bytes(response.body)))
        assert denied.startswith("Denied by policy: [run.paused] The Coral run is paused (user)")
        assert guarded.mcp.forwarded == []
    finally:
        _pending_policy_ask_writes.pop(elicitation_id, None)
