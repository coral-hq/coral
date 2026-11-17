"""The cost backstop: a bound session at its spend cap is denied tool calls and its run pauses."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
from collections.abc import Iterator
from typing import Any, cast

import pytest

from coral.db.enum_codecs import ActorKind, LogKind, RunPauseReason, RunStatus
from coral.omni.policies.cost_backstop import (
    DEFAULT_SESSION_CAP_USD,
    SESSION_CAP_CONFIG_KEY,
    SESSION_CAP_ENV,
    cost_backstop,
    install_budget_pauser,
    resolve_session_cap_usd,
    session_spend_usd,
)
from coral.omni.policies.provider import CoralPolicyProvider
from coral.omni.policies.state import RunStatusCache
from coral.omni.server.sessions import RUN_ID_LABEL_KEY
from coral.recovery.pause import PauseResult, pause_log_checksum
from coral.stores.protocols import CommitOutcome, RunLogEntry, RunVersionConflict
from omnigent import process_logging
from omnigent.policies.schema import PolicyEvent
from omnigent.policies.types import EvaluationContext, PolicyResult
from omnigent.runtime.policies.required_providers import register_required_policy_provider
from omnigent.spec.types import Phase, PolicyAction
from tests.coral.omni.policies.conftest import (
    SESSION_CAP_USD,
    WORKSPACE,
    Clock,
    CoralPolicies,
    coral_spec,
    tool_call,
)

OMNIGENT = "mcp__omnigent__"
BACKSTOP = "__coral_cost_backstop"
BACKSTOP_LOGGER = "coral.omni.policies.cost_backstop"
OVER_CAP = {"total_cost_usd": 30.5, "input_tokens": 120_000}
BUDGET_TEXT = (
    "[budget] This session has spent about $30.50 of its $25.00 cap (an estimate), so Coral "
    "paused the run. Stop now and end your turn."
)
# The text when this call did not pause the run and it is not paused for budget.
REACHED_TEXT = (
    "[budget] This session has reached its cost cap: it has spent about $30.50 of its $25.00 "
    "cap (an estimate). Stop now and end your turn."
)
EXEMPT = (
    "coral_submit_handoff",
    f"{OMNIGENT}coral_submit_handoff",
    "coral_choose_arrow",
    f"{OMNIGENT}coral_choose_arrow",
    "ToolSearch",
)
WAIT_S = 30.0
LOOK_ALIKES = ("coral_x", f"{OMNIGENT}coral_x", f"{OMNIGENT}ToolSearch", "toolsearch", "")


def _tool_call(name: object) -> PolicyEvent:
    return cast(PolicyEvent, {"type": "tool_call", "target": name, "data": {"name": name}})


def _pauses(coral_policies: CoralPolicies, run_id: str) -> list[RunLogEntry]:
    return [
        entry
        for entry in coral_policies.run_store.logs[(WORKSPACE, run_id)]
        if entry.kind == int(LogKind.PAUSED)
    ]


def _run_row(coral_policies: CoralPolicies, run_id: str) -> tuple[int, int | None, int]:
    run = coral_policies.run_store.get_run(run_id, workspace_id=WORKSPACE)
    assert run is not None
    return run.status, run.pause_reason, run.version


def _over_cap_step(coral_policies: CoralPolicies, *, role: str = "step") -> tuple[str, str]:
    run_id = coral_policies.run(RunStatus.RUNNING)
    session_id = coral_policies.session(run_id, role=role)
    coral_policies.spend(session_id, OVER_CAP)
    return run_id, session_id


class _RecordingPauser:
    """Records each pause the backstop asks for and answers ``result``.

    ``error`` makes it fail as a store would.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self.result: PauseResult | None = None

    def __call__(self, **cause: Any) -> PauseResult | None:
        self.calls.append(cause)
        if self.error is not None:
            raise self.error
        return self.result


# What the real pauser answers when this call paused the run for budget.
PAUSED_NOW = PauseResult(CommitOutcome(run_id="r", version=2), int(RunPauseReason.BUDGET))


def _found_paused(reason: RunPauseReason | None) -> PauseResult:
    """The real pauser's answer for a run it found paused for *reason* (or finished)."""
    commit = CommitOutcome(run_id="r", version=3, applied=False)
    return PauseResult(commit, None if reason is None else int(reason))


@pytest.fixture
def recording_pauser() -> Iterator[_RecordingPauser]:
    pauser = _RecordingPauser()
    uninstall = install_budget_pauser(pauser)
    yield pauser
    uninstall()


async def test_over_cap_tool_call_pauses_the_run_once_per_epoch_and_denies(
    coral_policies: CoralPolicies,
) -> None:
    run_id, step = _over_cap_step(coral_policies)
    _, _, version = _run_row(coral_policies, run_id)
    spec = coral_spec()

    denied = await coral_policies.call(spec, step, "Bash")
    assert (denied.action, denied.deciding_policies) == (PolicyAction.DENY, [BACKSTOP])
    assert denied.reason == BUDGET_TEXT
    # One pause, committed through the run store, naming the session, spend and cap.
    status, reason, paused_version = _run_row(coral_policies, run_id)
    assert (status, reason, paused_version) == (
        RunStatus.PAUSED,
        RunPauseReason.BUDGET,
        version + 1,
    )
    [entry] = _pauses(coral_policies, run_id)
    assert entry.actor_kind == int(ActorKind.ENGINE)
    assert json.loads(entry.body) == {
        "kind": "pause_run",
        "reason": "budget",
        "cause": "session_cap",
        "session_id": step,
        "spent_usd": 30.5,
        "cap_usd": SESSION_CAP_USD,
    }
    assert entry.idempotency_cksum == pause_log_checksum(
        ("coral-budget", run_id, "session_cap", step), version
    )

    # The commit cleared the status cache, so the run guard now answers first.
    again = await coral_policies.call(spec, step, "Bash")
    assert again.deciding_policies == ["__coral_run_guard"]
    assert (again.reason or "").startswith("[run.paused] The Coral run is paused (budget).")
    # A second over-cap deny in the same pause epoch writes nothing more.
    backstop = cost_backstop(
        cap_usd=SESSION_CAP_USD,
        spent_usd=30.5,
        workspace_id=WORKSPACE,
        run_id=run_id,
        session_id=step,
    )
    assert backstop(_tool_call("Bash")) == {"result": "DENY", "reason": BUDGET_TEXT}
    assert _run_row(coral_policies, run_id)[2] == paused_version
    assert len(_pauses(coral_policies, run_id)) == 1

    # Resumed without a raised cap: the next tool call pauses the run again.
    coral_policies.set_status(run_id, RunStatus.RUNNING)
    resumed = await coral_policies.call(spec, step, "Bash")
    assert resumed.deciding_policies == [BACKSTOP]
    assert _run_row(coral_policies, run_id)[:2] == (RunStatus.PAUSED, RunPauseReason.BUDGET)
    first, second = _pauses(coral_policies, run_id)
    assert second.idempotency_cksum == pause_log_checksum(
        ("coral-budget", run_id, "session_cap", step), paused_version + 1
    )
    assert first.idempotency_cksum != second.idempotency_cksum


def test_engine_tools_and_unpriced_usage_pass(recording_pauser: _RecordingPauser) -> None:
    over = cost_backstop(
        cap_usd=25.0, spent_usd=25.0, workspace_id=WORKSPACE, run_id="run-1", session_id="s-1"
    )
    for name in EXEMPT:
        assert over(_tool_call(name)) == {"result": "ALLOW"}, name
    assert recording_pauser.calls == []
    # Exact names only: a look-alike is any other tool, and spend equal to the cap is over it.
    for name in LOOK_ALIKES:
        verdict = over(_tool_call(name))
        assert verdict["result"] == "DENY", name
        assert str(verdict.get("reason")).startswith("[budget] "), name
    cause = {
        "workspace_id": WORKSPACE,
        "run_id": "run-1",
        "session_id": "s-1",
        "spent_usd": 25.0,
        "cap_usd": 25.0,
    }
    assert len(recording_pauser.calls) == len(LOOK_ALIKES)
    for call in recording_pauser.calls:
        assert {key: value for key, value in call.items() if key != "now_us"} == cause
        assert isinstance(call["now_us"], int) and call["now_us"] > 0

    recording_pauser.calls.clear()
    for spent in (None, 0.0, 24.99):
        under = cost_backstop(
            cap_usd=25.0, spent_usd=spent, workspace_id=WORKSPACE, run_id="r", session_id="s"
        )
        for name in ("Bash", "sys_os_shell", *LOOK_ALIKES):
            assert under(_tool_call(name)) == {"result": "ALLOW"}, (spent, name)
    assert recording_pauser.calls == []


@pytest.mark.parametrize(
    ("usage", "denied"),
    [
        ({}, False),
        ({"input_tokens": 900_000, "output_tokens": 50_000}, False),
        ({"total_cost_usd": 24.99}, False),
        ({"total_cost_usd": 25}, True),
        # The larger of the two figures counts, so a posted lower one never hides spend.
        ({"policy_cost_usd": 10.0, "total_cost_usd": 30.0}, True),
        ({"policy_cost_usd": 0, "total_cost_usd": 30.0}, True),
        ({"policy_cost_usd": 30.0, "total_cost_usd": 10.0}, True),
        ({"policy_cost_usd": 10.0, "total_cost_usd": 20.0}, False),
        ({"policy_cost_usd": None, "total_cost_usd": 30.0}, True),
        # A figure that is not a finite number is unpriced.
        ({"total_cost_usd": True}, False),
        ({"total_cost_usd": math.inf}, False),
    ],
)
async def test_only_the_sessions_own_priced_spend_counts(
    coral_policies: CoralPolicies, usage: dict[str, object], denied: bool
) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    # The run's other spend (here its anchor's) is in the run-wide usage, never in this cap.
    anchor = coral_policies.session(run_id, role="anchor")
    coral_policies.spend(anchor, {"total_cost_usd": 1_000.0, "policy_cost_usd": 1_000.0})
    step = coral_policies.session(run_id, parent=anchor)
    coral_policies.spend(step, usage)

    result = await coral_policies.call(coral_spec(), step, "Bash")

    assert result.action == (PolicyAction.DENY if denied else PolicyAction.ALLOW)
    if denied:
        assert result.deciding_policies == [BACKSTOP]
    assert _run_row(coral_policies, run_id)[0] == (
        RunStatus.PAUSED if denied else RunStatus.RUNNING
    )


async def test_deny_text_says_stop_and_never_hand_off(
    coral_policies: CoralPolicies, recording_pauser: _RecordingPauser
) -> None:
    _, step = _over_cap_step(coral_policies)
    spec = coral_spec()
    recording_pauser.result = PAUSED_NOW

    # Other phases are never denied over the cap, and nothing ever asks.
    for context in (
        EvaluationContext(phase=Phase.REQUEST, content="Continue."),
        EvaluationContext(phase=Phase.LLM_REQUEST, content={"messages": []}),
        EvaluationContext(
            phase=Phase.TOOL_RESULT, content={"name": "Bash", "output": "ok"}, tool_name="Bash"
        ),
    ):
        assert (await coral_policies.evaluate(spec, step, context)).action == (
            PolicyAction.ALLOW
        ), context.phase

    reason = (await coral_policies.call(spec, step, "Skill")).reason or ""
    assert reason == BUDGET_TEXT
    assert reason.endswith("Stop now and end your turn.") and "estimate" in reason
    assert "handoff" not in reason and "coral_submit_handoff" not in reason
    for spent, cap, text in (
        (25.0, 25.0, "spent about $25.00 of its $25.00 cap"),
        (1_234.567, 1_000.0, "spent about $1,234.57 of its $1,000.00 cap"),
        # A sub-cent cap or spend keeps two significant digits.
        (0.0015, 0.001, "spent about $0.0015 of its $0.001 cap"),
        (0.03, 0.005, "spent about $0.03 of its $0.005 cap"),
    ):
        backstop = cost_backstop(
            cap_usd=cap, spent_usd=spent, workspace_id=WORKSPACE, run_id="r", session_id="s"
        )
        verdict = backstop(_tool_call("Read"))
        assert verdict["result"] == "DENY"
        assert text in str(verdict.get("reason"))
    assert len(recording_pauser.calls) == 5

    # Only a pause that happened, or a run already paused for budget, is called a pause.
    for result, text in (
        (PAUSED_NOW, BUDGET_TEXT),
        (_found_paused(RunPauseReason.BUDGET), BUDGET_TEXT),
        (_found_paused(RunPauseReason.DRIFT), REACHED_TEXT),
        (_found_paused(None), REACHED_TEXT),
        (None, REACHED_TEXT),
    ):
        recording_pauser.result = result
        assert (await coral_policies.call(spec, step, "Skill")).reason == text, result
    assert "handoff" not in REACHED_TEXT and REACHED_TEXT.endswith("Stop now and end your turn.")


def test_the_backstop_decides_tool_calls_only_and_never_raises(
    recording_pauser: _RecordingPauser,
) -> None:
    backstop = cost_backstop(
        cap_usd=1.0, spent_usd=2.0, workspace_id=WORKSPACE, run_id="r", session_id="s"
    )

    for phase in ("request", "tool_result", "response", "llm_request", "llm_response"):
        event = cast(PolicyEvent, {"type": phase, "target": "Bash", "data": {}})
        assert backstop(event) == {"result": "ALLOW"}, phase
    for malformed in (
        None,
        "tool_call",
        [],
        {"type": "tool_call"},
        {"type": "tool_call", "target": 3},
    ):
        verdict = backstop(cast(PolicyEvent, malformed))
        # Only a tool call is denied; one that names no tool is not exempt.
        assert verdict["result"] == ("DENY" if isinstance(malformed, dict) else "ALLOW")
    assert len(recording_pauser.calls) == 2


@pytest.mark.parametrize(
    ("status", "reason", "start"),
    [
        (RunStatus.PAUSED, RunPauseReason.USER, "[run.paused] The Coral run is paused (user)."),
        (RunStatus.COMPLETED, None, "[run.finished]"),
        (RunStatus.FAILED, None, "[run.finished]"),
        (RunStatus.CANCELLED, None, "[run.cancelled]"),
    ],
)
async def test_a_paused_or_finished_run_is_not_paused_again(
    coral_policies: CoralPolicies,
    status: RunStatus,
    reason: RunPauseReason | None,
    start: str,
) -> None:
    run_id, step = _over_cap_step(coral_policies)
    coral_policies.set_status(run_id, status, reason=reason)
    row = _run_row(coral_policies, run_id)

    # The run guard answers first; the backstop never runs.
    denied = await coral_policies.call(coral_spec(), step, "Bash")
    assert denied.deciding_policies == ["__coral_run_guard"]
    assert (denied.reason or "").startswith(start)
    # Even asked directly, the pause leaves a stopped run as it is.
    backstop = cost_backstop(
        cap_usd=SESSION_CAP_USD,
        spent_usd=30.5,
        workspace_id=WORKSPACE,
        run_id=run_id,
        session_id=step,
    )
    assert backstop(_tool_call("Bash"))["result"] == "DENY"
    assert _run_row(coral_policies, run_id) == row
    assert _pauses(coral_policies, run_id) == []


class _StoreDown(RuntimeError):
    """A run store failure no other test raises, so its traceback key is this test's."""


async def test_a_pauser_failure_still_denies(
    coral_policies: CoralPolicies,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A fresh once-per-process log memory, so the traceback assertion is deterministic.
    monkeypatch.setattr(process_logging, "_log_once_seen", set())
    run_id, step = _over_cap_step(coral_policies)
    failing = _RecordingPauser()
    failing.error = _StoreDown("database is locked")
    uninstall = install_budget_pauser(failing)
    try:
        for _ in range(2):
            denied = await coral_policies.call(coral_spec(), step, "Bash")
            assert (denied.deciding_policies, denied.reason) == ([BACKSTOP], REACHED_TEXT)
    finally:
        uninstall()
    # Each denied call tried the pause again; the run is still running.
    assert len(failing.calls) == 2
    assert _run_row(coral_policies, run_id)[0] == RunStatus.RUNNING
    records = [record for record in caplog.records if record.name == BACKSTOP_LOGGER]
    tracebacks = [record for record in records if record.exc_info]
    assert len(tracebacks) == 1 and "_StoreDown" in tracebacks[0].getMessage()
    lines = [record for record in records if not record.exc_info]
    assert len(lines) == 2
    assert all(getattr(record, "session_id", None) == step for record in lines)
    assert all("database is locked" not in record.getMessage() for record in records)

    # With no pauser installed at all, the call is still denied and the gap is logged.
    caplog.clear()
    denied = await coral_policies.call(coral_spec(), step, "Bash")
    assert (denied.deciding_policies, denied.reason) == ([BACKSTOP], REACHED_TEXT)
    assert _run_row(coral_policies, run_id)[0] == RunStatus.RUNNING
    [missing] = [record for record in caplog.records if record.name == BACKSTOP_LOGGER]
    assert missing.levelno == logging.WARNING and "no budget pauser" in missing.getMessage()


async def test_an_over_cap_session_is_told_to_stop_before_its_role_guard_decides(
    coral_policies: CoralPolicies,
) -> None:
    step_run, step = _over_cap_step(coral_policies)
    assert coral_policies.names(coral_spec(), step)[:3] == [
        "__coral_run_guard",
        BACKSTOP,
        "__coral_step_roster",
    ]
    # The roster's text points at the handoff report; over the cap the stop text wins.
    roster_tool = await coral_policies.call(coral_spec(), step, "sys_session_message")
    assert (roster_tool.deciding_policies, roster_tool.reason) == ([BACKSTOP], BUDGET_TEXT)
    assert _run_row(coral_policies, step_run)[:2] == (RunStatus.PAUSED, RunPauseReason.BUDGET)

    # An orchestrator's forbidden tool gets the stop text too, and pauses its run.
    run_id, orchestrator = _over_cap_step(coral_policies, role="orchestrator")
    edit = await coral_policies.call(coral_spec(), orchestrator, "Edit")
    assert (edit.deciding_policies, edit.reason) == ([BACKSTOP], BUDGET_TEXT)
    assert _run_row(coral_policies, run_id)[:2] == (RunStatus.PAUSED, RunPauseReason.BUDGET)


async def test_an_over_cap_orchestrator_pauses_its_run_even_on_its_engine_tool(
    coral_policies: CoralPolicies,
) -> None:
    run_id, orchestrator = _over_cap_step(coral_policies, role="orchestrator")
    spec = coral_spec()
    assert coral_policies.names(spec, orchestrator)[:3] == [
        "__coral_run_guard",
        BACKSTOP,
        "__coral_orchestrator_guard",
    ]

    # Its engine tool, all it may call, pauses the run and then passes: the engine
    # answers it run.paused.
    choice = await coral_policies.call(spec, orchestrator, "coral_choose_arrow")
    assert choice.action == PolicyAction.ALLOW
    assert _run_row(coral_policies, run_id)[:2] == (RunStatus.PAUSED, RunPauseReason.BUDGET)
    [entry] = _pauses(coral_policies, run_id)
    assert json.loads(entry.body)["session_id"] == orchestrator
    # In the same epoch its exempt calls pass and write nothing; the run guard answers the rest.
    for name in ("ToolSearch", f"{OMNIGENT}coral_choose_arrow"):
        assert (await coral_policies.call(spec, orchestrator, name)).action == (
            PolicyAction.ALLOW
        ), name
    edit = await coral_policies.call(spec, orchestrator, "Edit")
    assert edit.deciding_policies == ["__coral_run_guard"]
    assert (edit.reason or "").startswith("[run.paused] The Coral run is paused (budget).")
    assert len(_pauses(coral_policies, run_id)) == 1

    # Resumed without a raised cap: its next decision pauses the run again.
    coral_policies.set_status(run_id, RunStatus.RUNNING)
    assert (await coral_policies.call(spec, orchestrator, "ToolSearch")).action == (
        PolicyAction.ALLOW
    )
    assert _run_row(coral_policies, run_id)[:2] == (RunStatus.PAUSED, RunPauseReason.BUDGET)
    assert len(_pauses(coral_policies, run_id)) == 2


def test_an_orchestrators_exempt_calls_pause_and_pass_and_a_steps_never_pause(
    recording_pauser: _RecordingPauser,
) -> None:
    def backstop(*, orchestrator: bool, spent: float = 30.0) -> Any:
        return cost_backstop(
            cap_usd=25.0,
            spent_usd=spent,
            workspace_id=WORKSPACE,
            run_id="r",
            session_id="s",
            orchestrator=orchestrator,
        )

    for name in EXEMPT:
        assert backstop(orchestrator=True)(_tool_call(name)) == {"result": "ALLOW"}, name
    assert len(recording_pauser.calls) == len(EXEMPT)
    assert backstop(orchestrator=True)(_tool_call("Edit"))["result"] == "DENY"
    recording_pauser.calls.clear()
    # Below the cap nothing pauses; a step's exempt calls never pause.
    for name in EXEMPT:
        assert backstop(orchestrator=True, spent=24.0)(_tool_call(name)) == {"result": "ALLOW"}
        assert backstop(orchestrator=False)(_tool_call(name)) == {"result": "ALLOW"}
    assert recording_pauser.calls == []


async def test_the_anchor_gets_no_backstop(coral_policies: CoralPolicies) -> None:
    run_id, anchor = _over_cap_step(coral_policies, role="anchor")

    names = coral_policies.names(coral_spec("anchor"), anchor)
    assert [name for name in names if name.startswith("__coral")] == ["__coral_anchor_deny_all"]
    denied = await coral_policies.call(coral_spec("anchor"), anchor, "Bash")
    assert denied.deciding_policies == ["__coral_anchor_deny_all"]
    assert _run_row(coral_policies, run_id)[0] == RunStatus.RUNNING


@pytest.mark.parametrize(
    ("server_config", "env", "expected"),
    [
        (None, {}, DEFAULT_SESSION_CAP_USD),
        ({}, {}, 25.0),
        ({SESSION_CAP_CONFIG_KEY: None}, {}, 25.0),
        ({SESSION_CAP_CONFIG_KEY: 10}, {}, 10.0),
        ({SESSION_CAP_CONFIG_KEY: 0.5}, {}, 0.5),
        ({SESSION_CAP_CONFIG_KEY: 1_000_000}, {}, 1_000_000.0),
        # The environment wins over the server config; blank is unset.
        ({SESSION_CAP_CONFIG_KEY: 10}, {SESSION_CAP_ENV: " 5.5 "}, 5.5),
        (None, {SESSION_CAP_ENV: "1e6"}, 1_000_000.0),
        ({SESSION_CAP_CONFIG_KEY: 10}, {SESSION_CAP_ENV: "  "}, 10.0),
    ],
)
def test_the_session_cap_comes_from_the_env_then_the_server_config(
    server_config: dict[str, object] | None, env: dict[str, str], expected: float
) -> None:
    cap = resolve_session_cap_usd(server_config, env)
    assert (cap, type(cap)) == (expected, float)


@pytest.mark.parametrize(
    ("server_config", "env"),
    [
        ({SESSION_CAP_CONFIG_KEY: 0}, {}),
        ({SESSION_CAP_CONFIG_KEY: -1.0}, {}),
        ({SESSION_CAP_CONFIG_KEY: 1_000_000.01}, {}),
        ({SESSION_CAP_CONFIG_KEY: math.inf}, {}),
        ({SESSION_CAP_CONFIG_KEY: math.nan}, {}),
        ({SESSION_CAP_CONFIG_KEY: True}, {}),
        ({SESSION_CAP_CONFIG_KEY: "25"}, {}),
        ({SESSION_CAP_CONFIG_KEY: 10**400}, {}),
        ({}, {SESSION_CAP_ENV: "lots"}),
        ({}, {SESSION_CAP_ENV: "0"}),
        ({}, {SESSION_CAP_ENV: "nan"}),
        ({}, {SESSION_CAP_ENV: "inf"}),
        ({}, {SESSION_CAP_ENV: "2000000"}),
        # An invalid environment value is refused even when the config is valid.
        ({SESSION_CAP_CONFIG_KEY: 10}, {SESSION_CAP_ENV: "-5"}),
    ],
)
def test_an_invalid_session_cap_is_refused(
    server_config: dict[str, object], env: dict[str, str]
) -> None:
    with pytest.raises(ValueError, match="session cost cap"):
        resolve_session_cap_usd(server_config, env)


def test_a_config_integer_too_long_to_print_is_refused_by_its_setting() -> None:
    # More digits than Python turns into text: the message must not need them.
    with pytest.raises(ValueError, match=f"session cost cap {SESSION_CAP_CONFIG_KEY}=<int too"):
        resolve_session_cap_usd({SESSION_CAP_CONFIG_KEY: 10**5000}, {})


@pytest.mark.parametrize(
    ("usage", "spent"),
    [
        ({"policy_cost_usd": 3.5, "total_cost_usd": 9.0}, 9.0),
        ({"policy_cost_usd": 12.0, "total_cost_usd": 9.0}, 12.0),
        ({"policy_cost_usd": 0, "total_cost_usd": 30.0}, 30.0),
        ({"policy_cost_usd": "lots", "total_cost_usd": 9.0}, 9.0),
        ({"policy_cost_usd": 10**400, "total_cost_usd": 2.0}, 2.0),
        ({"policy_cost_usd": None, "total_cost_usd": 9}, 9.0),
        ({"policy_cost_usd": 4.0}, 4.0),
        ({"total_cost_usd": 0}, 0.0),
        ({"input_tokens": 10}, None),
        ({"total_cost_usd": "lots"}, None),
        ({"total_cost_usd": False}, None),
        ({"total_cost_usd": math.nan}, None),
        ({"policy_cost_usd": -math.inf}, None),
        ({}, None),
        (None, None),
        ([("total_cost_usd", 9.0)], None),
    ],
)
def test_session_spend_is_the_larger_finite_figure(usage: object, spent: float | None) -> None:
    assert session_spend_usd(usage) == spent


def test_the_installed_pauser_is_removed_only_by_its_own_uninstall() -> None:
    first, second = _RecordingPauser(), _RecordingPauser()
    backstop = cost_backstop(
        cap_usd=1.0, spent_usd=1.0, workspace_id=WORKSPACE, run_id="r", session_id="s"
    )
    uninstall_first = install_budget_pauser(first)
    uninstall_second = install_budget_pauser(second)
    try:
        # A later install replaces the earlier one; the earlier undo leaves it in place.
        uninstall_first()
        backstop(_tool_call("Bash"))
        assert (len(first.calls), len(second.calls)) == (0, 1)
    finally:
        uninstall_second()
        uninstall_second()
    backstop(_tool_call("Bash"))
    assert (len(first.calls), len(second.calls)) == (0, 1)


# Exact-name look-alikes of the exemptions; each is any other tool over the cap.
MORE_LOOK_ALIKES = (
    f"{OMNIGENT}{OMNIGENT}coral_submit_handoff",
    "mcp__other__coral_submit_handoff",
    "mcp__omnigent_coral_choose_arrow",
    "Coral_submit_handoff",
    "coral_submit_handoff ",
    "coral_submit",
    "ToolSearch ",
    "TOOLSEARCH",
    f"{OMNIGENT}ToolSearch",
    "Bash",
    "sys_os_shell",
)


async def test_exact_exemptions_and_look_alikes_through_a_real_build(
    coral_policies: CoralPolicies, recording_pauser: _RecordingPauser
) -> None:
    run_id, step = _over_cap_step(coral_policies)

    for name in EXEMPT:
        assert (await coral_policies.call(coral_spec(), step, name)).action == (
            PolicyAction.ALLOW
        ), name
    assert recording_pauser.calls == []
    # The recording pauser pauses nothing, so no text claims a pause.
    for name in MORE_LOOK_ALIKES:
        denied = await coral_policies.call(coral_spec(), step, name)
        assert (denied.deciding_policies, denied.reason) == ([BACKSTOP], REACHED_TEXT), name
    assert [call["session_id"] for call in recording_pauser.calls] == [step] * len(
        MORE_LOOK_ALIKES
    )
    assert _run_row(coral_policies, run_id)[0] == RunStatus.RUNNING


@pytest.mark.parametrize(
    ("usage", "denied"),
    [
        ({"policy_cost_usd": math.nextafter(SESSION_CAP_USD, 0.0)}, False),
        ({"policy_cost_usd": SESSION_CAP_USD}, True),
        ({"total_cost_usd": SESSION_CAP_USD + 1e-6}, True),
        ({"total_cost_usd": -3.0}, False),
        ({"policy_cost_usd": None, "total_cost_usd": None}, False),
    ],
)
async def test_spend_just_under_at_and_over_the_cap(
    coral_policies: CoralPolicies, usage: dict[str, object], denied: bool
) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    step = coral_policies.session(run_id)
    coral_policies.spend(step, usage)

    for name in ("Bash", "coral_submit_handoff"):
        result = await coral_policies.call(coral_spec(), step, name)
        blocked = denied and name == "Bash"
        assert result.action == (PolicyAction.DENY if blocked else PolicyAction.ALLOW), name
    assert len(_pauses(coral_policies, run_id)) == (1 if denied else 0)


async def test_a_step_passes_on_its_own_spend_whatever_its_run_and_sub_agents_spent(
    coral_policies: CoralPolicies,
) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    anchor = coral_policies.session(run_id, role="anchor")
    coral_policies.spend(anchor, {"total_cost_usd": 1_000.0})
    step = coral_policies.session(run_id, parent=anchor)
    coral_policies.spend(step, {"total_cost_usd": 5.0})
    # A sub-agent session the step started: unbound, with its own row and spend.
    sub_agent = coral_policies.session(parent=step)
    coral_policies.spend(sub_agent, {"total_cost_usd": 500.0})

    engine = coral_policies.engine(coral_spec(), step)
    # The usage every other policy sees is far over the cap; the backstop reads the row's own.
    assert engine.usage["total_cost_usd"] > SESSION_CAP_USD
    assert (await engine.evaluate(tool_call("Bash"))).action == PolicyAction.ALLOW
    # The sub-agent session has no binding, so Coral adds no policy to it.
    assert not [name for name in coral_policies.names(coral_spec(), sub_agent) if "coral" in name]
    assert (await coral_policies.call(coral_spec(), sub_agent, "Bash")).action == (
        PolicyAction.ALLOW
    )
    assert _run_row(coral_policies, run_id)[0] == RunStatus.RUNNING
    assert _pauses(coral_policies, run_id) == []


async def test_a_resumed_session_pauses_again_until_the_cap_is_raised(
    coral_policies: CoralPolicies,
) -> None:
    run_id, step = _over_cap_step(coral_policies)
    spec = coral_spec()
    for _ in range(2):
        assert (await coral_policies.call(spec, step, "Bash")).deciding_policies == [BACKSTOP]
        assert _run_row(coral_policies, run_id)[:2] == (RunStatus.PAUSED, RunPauseReason.BUDGET)
        coral_policies.set_status(run_id, RunStatus.RUNNING)
    assert len(_pauses(coral_policies, run_id)) == 2

    # A restart with a raised cap: the same spend now passes and nothing pauses.
    raised = CoralPolicyProvider(
        bindings=coral_policies.lookup, statuses=coral_policies.statuses, session_cap_usd=50.0
    )
    unregister = register_required_policy_provider("coral", raised)
    try:
        assert (await coral_policies.call(spec, step, "Bash")).action == PolicyAction.ALLOW
    finally:
        unregister()
    assert _run_row(coral_policies, run_id)[0] == RunStatus.RUNNING
    assert len(_pauses(coral_policies, run_id)) == 2


def test_many_over_cap_sessions_of_one_run_pause_it_once(
    coral_policies: CoralPolicies, caplog: pytest.LogCaptureFixture
) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    _, _, version = _run_row(coral_policies, run_id)
    sessions = [coral_policies.session(run_id) for _ in range(4)]
    for session_id in sessions:
        coral_policies.spend(session_id, OVER_CAP)
    callers = sessions * 2
    barrier = threading.Barrier(len(callers))
    results: list[PolicyResult | BaseException] = []

    def call(session_id: str) -> None:
        loop = asyncio.new_event_loop()
        try:
            engine = coral_policies.engine(coral_spec(), session_id)
            barrier.wait(WAIT_S)
            results.append(loop.run_until_complete(engine.evaluate(tool_call("Bash"))))
        except BaseException as error:  # reported by the assertion below
            results.append(error)
        finally:
            loop.close()

    caplog.set_level(logging.WARNING, logger=BACKSTOP_LOGGER)
    threads = [threading.Thread(target=call, args=(session_id,)) for session_id in callers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT_S)
    assert not any(thread.is_alive() for thread in threads)

    assert all(isinstance(result, PolicyResult) for result in results), results
    verdicts = cast(list[PolicyResult], results)
    assert len(verdicts) == len(callers)
    assert all(result.action == PolicyAction.DENY for result in verdicts)
    # Every engine was built before any pause, so each call is the backstop's, and each
    # says Coral paused the run: one call paused it, the others found it paused for budget.
    assert all(result.deciding_policies == [BACKSTOP] for result in verdicts)
    assert all(result.reason == BUDGET_TEXT for result in verdicts)
    assert _run_row(coral_policies, run_id) == (
        RunStatus.PAUSED,
        RunPauseReason.BUDGET,
        version + 1,
    )
    [entry] = _pauses(coral_policies, run_id)
    assert json.loads(entry.body)["session_id"] in sessions
    applied = [record for record in caplog.records if "Coral paused run" in record.getMessage()]
    assert len(applied) == 1


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        (RunPauseReason.DRIFT, REACHED_TEXT),
        (RunPauseReason.USER, REACHED_TEXT),
        # Paused for budget already (another session's pause): the text says so.
        (RunPauseReason.BUDGET, BUDGET_TEXT),
    ],
)
async def test_a_run_paused_elsewhere_is_left_as_it_is_while_the_status_is_stale(
    coral_policies: CoralPolicies,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
    reason: RunPauseReason,
    text: str,
) -> None:
    run_id, step = _over_cap_step(coral_policies)
    # A status cache no commit here clears, as when another process pauses the run.
    stale = RunStatusCache(coral_policies.run_store, clock=clock)
    assert stale.status(WORKSPACE, run_id).status == "running"
    coral_policies.set_status(run_id, RunStatus.PAUSED, reason=reason)
    row = _run_row(coral_policies, run_id)
    provider = CoralPolicyProvider(
        bindings=coral_policies.lookup, statuses=stale, session_cap_usd=SESSION_CAP_USD
    )
    unregister = register_required_policy_provider("coral", provider)
    caplog.set_level(logging.WARNING, logger=BACKSTOP_LOGGER)
    try:
        denied = await coral_policies.call(coral_spec(), step, "Bash")
    finally:
        unregister()

    # The stale run guard allows; the backstop still denies, and the pause changes nothing.
    assert (denied.deciding_policies, denied.reason) == ([BACKSTOP], text)
    assert _run_row(coral_policies, run_id) == row
    assert _pauses(coral_policies, run_id) == []
    assert [record for record in caplog.records if record.name == BACKSTOP_LOGGER] == []


async def test_a_failing_run_store_still_denies_and_the_next_call_pauses(
    coral_policies: CoralPolicies,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, step = _over_cap_step(coral_policies)
    write = coral_policies.run_store.apply_transition
    failures = [_StoreDown("disk I/O error"), RunVersionConflict(run_id, 1, 2)]

    def flaky_write(*args: Any, **kwargs: Any) -> Any:
        if failures:
            raise failures[0]
        return write(*args, **kwargs)

    monkeypatch.setattr(coral_policies.run_store, "apply_transition", flaky_write)
    caplog.set_level(logging.WARNING, logger=BACKSTOP_LOGGER)
    # A store error, then version conflicts until the retries run out: denied, run unchanged.
    for expected in ("_StoreDown", "RunContended"):
        denied = await coral_policies.call(coral_spec(), step, "Bash")
        assert (denied.deciding_policies, denied.reason) == ([BACKSTOP], REACHED_TEXT)
        assert _run_row(coral_policies, run_id)[0] == RunStatus.RUNNING
        failures.pop(0)
        lines = [
            record
            for record in caplog.records
            if record.name == BACKSTOP_LOGGER and not record.exc_info
        ]
        assert expected in lines[-1].getMessage()
        assert getattr(lines[-1], "session_id", None) == step

    # The store recovers: the next denied call pauses the run.
    assert (await coral_policies.call(coral_spec(), step, "Bash")).deciding_policies == [BACKSTOP]
    assert _run_row(coral_policies, run_id)[:2] == (RunStatus.PAUSED, RunPauseReason.BUDGET)
    assert len(_pauses(coral_policies, run_id)) == 1


async def test_ordinary_sessions_are_never_backstopped_whatever_they_spend(
    coral_policies: CoralPolicies, recording_pauser: _RecordingPauser
) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    plain = [
        coral_policies.session(),
        coral_policies.session(labels={"coral.run": run_id}),
    ]
    unbound_coral = [
        coral_policies.session(),
        # Copied run labels are a hint to look; without a binding nothing applies.
        coral_policies.session(labels={RUN_ID_LABEL_KEY: run_id}),
    ]
    for session_id in (*plain, *unbound_coral):
        coral_policies.spend(session_id, {"total_cost_usd": 1_000_000.0})
    coral_policies.lookup.reads.clear()

    for session_id in plain:
        assert (await coral_policies.call(coral_spec(None), session_id, "Bash")).action == (
            PolicyAction.ALLOW
        )
    assert coral_policies.lookup.reads == []
    for session_id in unbound_coral:
        result = await coral_policies.call(coral_spec(), session_id, "Bash")
        assert result.action == PolicyAction.ALLOW
    assert [session for _, session in coral_policies.lookup.reads] == unbound_coral
    assert recording_pauser.calls == []
    assert _run_row(coral_policies, run_id)[0] == RunStatus.RUNNING
