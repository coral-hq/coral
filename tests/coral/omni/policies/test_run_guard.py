"""The run guard: stopped runs and closed sessions get only the engine tools and ToolSearch."""

from __future__ import annotations

from typing import cast

import pytest

from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.omni.policies.run_guard import run_guard
from omnigent.policies.schema import PolicyEvent
from omnigent.policies.types import EvaluationContext
from omnigent.spec.types import Phase, PolicyAction
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE
from tests.coral.omni.policies.conftest import CoralPolicies, coral_spec, tool_call

OMNIGENT = "mcp__omnigent__"
STOP = "Stop now and end your turn"
# The builder's own policies for a spec without guardrails (its required approval guards).
BUILDER_ONLY = ["__ask_on_add_policy", "__ask_on_scheduled_task_change"]
# Exact engine tool names, either form, and exactly ToolSearch.
EXEMPT = (
    "coral_submit_handoff",
    "mcp__omnigent__coral_submit_handoff",
    "coral_choose_arrow",
    "mcp__omnigent__coral_choose_arrow",
    "ToolSearch",
)
# Everything else, look-alikes of the exempt names included.
DENIED = (
    "sys_os_shell",
    "mcp__omnigent__sys_os_shell",
    "Skill",
    "mcp__fs__write_file",
    "coral_x",
    "mcp__omnigent__coral_x",
    "Coral_submit_handoff",
    "mcp__fs__coral_submit_handoff",
    "mcp__omnigent__ToolSearch",
    "toolsearch",
    "",
)
STOPPED = {
    # (run status, closed): the deny reason's start.
    ("paused", False): "[run.paused] The Coral run is paused (drift).",
    ("cancelled", False): "[run.cancelled] The Coral run was cancelled.",
    ("completed", False): "[run.finished] The Coral run has finished.",
    ("failed", False): "[run.finished] The Coral run has finished.",
    ("missing", False): "[run.missing] This step's Coral run no longer exists.",
    ("running", True): "[session.closed] Coral closed this step.",
    ("starting", True): "[session.closed] Coral closed this step.",
    ("paused", True): "[session.closed] Coral closed this step.",
}
STOPPED_IDS = [f"{status}-{'closed' if closed else 'open'}" for status, closed in STOPPED]


def _tool_call(name: object) -> PolicyEvent:
    return cast(PolicyEvent, {"type": "tool_call", "target": name, "data": {"name": name}})


@pytest.mark.parametrize(("state", "start"), STOPPED.items(), ids=STOPPED_IDS)
def test_a_stopped_run_or_closed_session_allows_only_the_exempt_tools(
    state: tuple[str, bool], start: str
) -> None:
    status, closed = state
    guard = run_guard(run_status=status, pause_reason="drift", closed=closed)

    for name in EXEMPT:
        assert guard(_tool_call(name)) == {"result": "ALLOW"}, name
    for name in DENIED:
        verdict = guard(_tool_call(name))
        assert verdict["result"] == "DENY", name
        reason = str(verdict.get("reason"))
        assert reason.startswith(start), reason
        # Every deny says to stop and never invites a handoff.
        assert STOP in reason and "handoff" not in reason, reason


@pytest.mark.parametrize("status", ["starting", "running"])
def test_a_live_run_allows_every_tool(status: str) -> None:
    guard = run_guard(run_status=status, pause_reason=None, closed=False)

    for name in (*EXEMPT, *DENIED):
        assert guard(_tool_call(name)) == {"result": "ALLOW"}, name


@pytest.mark.parametrize(("state", "start"), STOPPED.items(), ids=STOPPED_IDS)
def test_the_run_guard_decides_tool_calls_only_and_never_raises(
    state: tuple[str, bool], start: str
) -> None:
    status, closed = state
    guard = run_guard(run_status=status, pause_reason="drift", closed=closed)

    for phase in ("request", "tool_result", "response", "llm_request", "llm_response"):
        event = cast(PolicyEvent, {"type": phase, "target": "sys_os_shell", "data": {}})
        assert guard(event) == {"result": "ALLOW"}, phase
    for malformed in (
        None,
        "tool_call",
        {"type": "tool_call"},
        {"type": "tool_call", "target": 3},
    ):
        verdict = guard(cast(PolicyEvent, malformed))
        # Only a tool call can be denied; one that names no tool is not exempt.
        is_tool_call = isinstance(malformed, dict)
        assert verdict["result"] == ("DENY" if is_tool_call else "ALLOW"), malformed
        if is_tool_call:
            assert str(verdict.get("reason")).startswith(start)


def test_the_paused_text_names_a_known_reason_and_who_resumes() -> None:
    def reason(pause_reason: str | None, *, orchestrator: bool = False) -> str:
        guard = run_guard(
            run_status="paused", pause_reason=pause_reason, closed=False, orchestrator=orchestrator
        )
        return str(guard(_tool_call("Skill")).get("reason"))

    assert reason("budget") == (
        "[run.paused] The Coral run is paused (budget). Stop now and end your turn; "
        "Coral resumes this step when the run resumes."
    )
    assert reason(None).startswith(f"[run.paused] The Coral run is paused. {STOP}")
    # An orchestrator has no step to resume.
    assert reason("drift", orchestrator=True) == (
        "[run.paused] The Coral run is paused (drift). Stop now and end your turn."
    )


def test_texts_shown_to_an_orchestrator_never_call_it_a_step() -> None:
    def reason(status: str, *, closed: bool = False) -> str:
        guard = run_guard(run_status=status, pause_reason=None, closed=closed, orchestrator=True)
        return str(guard(_tool_call("Edit")).get("reason"))

    assert reason("running", closed=True) == (
        f"[session.closed] Coral closed this session. {STOP}."
    )
    assert reason("missing") == f"[run.missing] This session's Coral run no longer exists. {STOP}."
    for status in ("paused", "cancelled", "completed", "failed", "missing"):
        assert "step" not in reason(status), status
        assert "step" not in reason(status, closed=True), status


def test_an_unknown_run_status_is_refused_at_build() -> None:
    # The provider then denies the session's tool calls through S52's fallback.
    with pytest.raises(ValueError, match="unknown run status"):
        run_guard(run_status="resuming", pause_reason=None, closed=False)


async def test_paused_run_denies_shell_and_allows_handoff_across_rebuilds(
    coral_policies: CoralPolicies,
) -> None:
    run_id = coral_policies.run(RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    step = coral_policies.session(run_id)
    plain = coral_policies.session()
    spec = coral_spec()
    plain_spec = coral_spec(None)

    # Two separate builds, as two tool calls make: the deny comes from stored state.
    for _ in range(2):
        shell = await coral_policies.call(spec, step, "sys_os_shell")
        assert shell.action == PolicyAction.DENY
        assert shell.deciding_policies == ["__coral_run_guard"]
        reason = shell.reason or ""
        assert reason.startswith("[run.paused]") and "(drift)" in reason
        assert STOP in reason and "coral_submit_handoff" not in reason
        for name in ("coral_submit_handoff", f"{OMNIGENT}coral_submit_handoff", "ToolSearch"):
            assert (await coral_policies.call(spec, step, name)).action == PolicyAction.ALLOW
        for name in ("coral_x", f"{OMNIGENT}ToolSearch"):
            denied = await coral_policies.call(spec, step, name)
            assert denied.deciding_policies == ["__coral_run_guard"], name
        # Requests (an engine's message, a user's prompt) are never denied by the run guard.
        request = EvaluationContext(phase=Phase.REQUEST, content="Continue the review.")
        assert (await coral_policies.evaluate(spec, step, request)).action == PolicyAction.ALLOW

    # A session with no binding and no Coral spec gets the builder's own policies only:
    # with no guardrails, no session or admin policies, its two built-in approval guards.
    assert coral_policies.names(plain_spec, plain) == BUILDER_ONLY
    assert (await coral_policies.call(plain_spec, plain, "sys_os_shell")).action == (
        PolicyAction.ALLOW
    )


@pytest.mark.parametrize(
    ("status", "start"),
    [
        (RunStatus.CANCELLED, "[run.cancelled]"),
        (RunStatus.COMPLETED, "[run.finished]"),
        (RunStatus.FAILED, "[run.finished]"),
        (None, "[run.missing]"),
    ],
)
async def test_a_cancelled_finished_or_missing_run_denies_through_the_provider(
    coral_policies: CoralPolicies, status: RunStatus | None, start: str
) -> None:
    run_id = "no-such-run" if status is None else coral_policies.run(status)
    step = coral_policies.session(run_id)
    spec = coral_spec()

    denied = await coral_policies.call(spec, step, "sys_os_write")
    assert denied.action == PolicyAction.DENY
    assert (denied.reason or "").startswith(start)
    assert (await coral_policies.call(spec, step, "coral_submit_handoff")).action == (
        PolicyAction.ALLOW
    )


async def test_the_closed_label_alone_makes_a_bound_session_inert(
    coral_policies: CoralPolicies,
) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    closed = coral_policies.session(run_id, labels={CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE})
    # The legacy title marker without the label: an owner's rename never closes a step.
    renamed = coral_policies.session(run_id, title="review:item:closed:abc123")
    spec = coral_spec()

    denied = await coral_policies.call(spec, closed, "sys_os_shell")
    assert denied.action == PolicyAction.DENY
    assert (denied.reason or "").startswith("[session.closed]")
    assert (await coral_policies.call(spec, closed, "ToolSearch")).action == PolicyAction.ALLOW
    assert (await coral_policies.call(spec, renamed, "sys_os_shell")).action == PolicyAction.ALLOW


# What each kind of session tries on a real policy build: sys tools, CLI built-ins, a
# connector, the engine tools in both forms, ToolSearch and names that only look exempt.
ROSTER_TOOLS = ("sys_session_message", f"{OMNIGENT}sys_session_create", "Agent", "Task")
WORK_TOOLS = (
    "sys_os_shell",
    f"{OMNIGENT}sys_os_write",
    "sys_os_read",
    "Bash",
    "Edit",
    "Write",
    "Read",
    "Skill",
    "WebFetch",
    "NotebookEdit",
    "mcp__fs__write_file",
)
HANDOFF_TOOLS = ("coral_submit_handoff", f"{OMNIGENT}coral_submit_handoff")
CHOOSE_TOOLS = ("coral_choose_arrow", f"{OMNIGENT}coral_choose_arrow")
LOOK_ALIKES = (
    "coral_x",
    f"{OMNIGENT}coral_x",
    "Coral_submit_handoff",
    "CORAL_SUBMIT_HANDOFF",
    "coral_submit_handoff ",
    " coral_choose_arrow",
    "coral_submit_handoff\x00",
    "coral_submit_handoff_v2",
    "сoral_submit_handoff",  # a Cyrillic first letter
    "mcp__fs__coral_submit_handoff",
    f"{OMNIGENT}{OMNIGENT}coral_submit_handoff",
    "mcp__omnigent_coral_choose_arrow",
    "ToolSearch ",
    "ToolSearch\n",
    "toolsearch",
    "TOOLSEARCH",
    f"{OMNIGENT}ToolSearch",
    "mcp__fs__ToolSearch",
)
# The builder's own approval ASKs on it, behind Coral's policies.
ADD_POLICY = "sys_add_policy"
ALL_TOOLS = (
    *ROSTER_TOOLS,
    *WORK_TOOLS,
    *HANDOFF_TOOLS,
    *CHOOSE_TOOLS,
    "ToolSearch",
    *LOOK_ALIKES,
    ADD_POLICY,
)
STANCES = {
    "step": "implementer",
    "verifier": "reviewer",
    "orchestrator": "orchestrator",
    "anchor": "anchor",
}
# (stored status, pause reason): the run guard's deny text start for a step, None for live.
RUN_STATES = {
    "starting": (RunStatus.STARTING, None, None),
    "running": (RunStatus.RUNNING, None, None),
    "paused-drift": (
        RunStatus.PAUSED,
        RunPauseReason.DRIFT,
        "[run.paused] The Coral run is paused (drift). Stop now",
    ),
    "paused-no-reason": (RunStatus.PAUSED, None, "[run.paused] The Coral run is paused. Stop now"),
    "cancelled": (RunStatus.CANCELLED, None, "[run.cancelled] The Coral run was cancelled."),
    "completed": (RunStatus.COMPLETED, None, "[run.finished] The Coral run has finished."),
    "failed": (RunStatus.FAILED, None, "[run.finished] The Coral run has finished."),
    "missing": (None, None, "[run.missing] This step's Coral run no longer exists."),
}


def _expected(role: str, stopped: str | None, tool: str) -> tuple[PolicyAction, str, str]:
    """(action, deciding policy, reason start) for *tool*; *stopped* is the run guard's text.

    The run guard goes ahead of the role guards, so on a stopped run it decides every
    tool it does not exempt; the role guards' texts show only while the run is live.
    """
    if role == "anchor":
        return PolicyAction.DENY, "__coral_anchor_deny_all", "[anchor]"
    exempt = tool in (*HANDOFF_TOOLS, *CHOOSE_TOOLS, "ToolSearch")
    if stopped is not None and not exempt:
        # An orchestrator is never called a step.
        text = stopped.replace("step", "session") if role == "orchestrator" else stopped
        return PolicyAction.DENY, "__coral_run_guard", text
    if role == "orchestrator":
        if tool in CHOOSE_TOOLS or tool == "ToolSearch":
            return PolicyAction.ALLOW, "", ""
        return PolicyAction.DENY, "__coral_orchestrator_guard", "[orchestrator]"
    if tool in ROSTER_TOOLS:
        return PolicyAction.DENY, "__coral_step_roster", "[roster]"
    if tool == ADD_POLICY:
        return PolicyAction.ASK, "__ask_on_add_policy", ""
    return PolicyAction.ALLOW, "", ""


@pytest.mark.parametrize("closed", [False, True], ids=["open", "closed"])
@pytest.mark.parametrize("state", list(RUN_STATES))
async def test_every_run_state_role_and_tool_through_a_real_build(
    coral_policies: CoralPolicies, state: str, closed: bool
) -> None:
    status, reason, stopped = RUN_STATES[state]
    run_id = "no-such-run" if status is None else coral_policies.run(status, reason=reason)
    if closed:
        # The label alone, set by Coral's close: it wins over every run state.
        stopped = "[session.closed] Coral closed this step. Stop now"
    labels = {CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE} if closed else None

    for role, stance in STANCES.items():
        session = coral_policies.session(run_id, role=role, labels=labels)
        engine = coral_policies.engine(coral_spec(stance), session)
        for tool in ALL_TOOLS:
            action, deciding, start = _expected(role, stopped, tool)
            result = await engine.evaluate(tool_call(tool))
            assert result.action == action, (role, tool, result)
            if action == PolicyAction.ALLOW:
                continue
            assert result.deciding_policies == [deciding], (role, tool, result)
            reason_text = result.reason or ""
            assert reason_text.startswith(start), (role, tool, reason_text)
            if deciding == "__coral_run_guard":
                assert STOP in reason_text and "handoff" not in reason_text, reason_text
