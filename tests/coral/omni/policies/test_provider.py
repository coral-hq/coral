"""Coral's policy provider: role guards from the binding row, then the run guard."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.omni.server.sessions import ROLE_LABEL_KEY, RUN_ID_LABEL_KEY
from omnigent import process_logging
from omnigent.entities import Conversation
from omnigent.policies.types import EvaluationContext
from omnigent.spec.types import Phase, PolicyAction
from omnigent.util.session_lifecycle import CLOSED_LABEL_KEY, CLOSED_LABEL_VALUE
from tests.coral.omni.policies.conftest import WORKSPACE, Clock, CoralPolicies, coral_spec
from tests.coral.tools.fake_decision_port import step_binding

OMNIGENT = "mcp__omnigent__"
PROVIDER_LOGGER = "coral.omni.policies.provider"


async def _verdicts(
    coral_policies: CoralPolicies, session_id: str, names: tuple[str, ...]
) -> dict[str, tuple[PolicyAction, list[str] | None]]:
    spec = coral_spec()
    verdicts: dict[str, tuple[PolicyAction, list[str] | None]] = {}
    for name in names:
        result = await coral_policies.call(spec, session_id, name)
        verdicts[name] = (result.action, result.deciding_policies)
    return verdicts


async def test_anchor_binding_denies_every_tool(coral_policies: CoralPolicies) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    anchor = coral_policies.session(run_id, role="anchor")
    tools = ("coral_submit_handoff", f"{OMNIGENT}coral_choose_arrow", "ToolSearch", "Skill")

    # The deny-all is the anchor's only Coral policy: nothing else applies to it.
    names = coral_policies.names(coral_spec("anchor"), anchor)
    assert [name for name in names if name.startswith("__coral")] == ["__coral_anchor_deny_all"]
    for name, (action, deciding) in (await _verdicts(coral_policies, anchor, tools)).items():
        assert (action, deciding) == (PolicyAction.DENY, ["__coral_anchor_deny_all"]), name
    result = await coral_policies.call(coral_spec(), anchor, "sys_os_shell")
    assert result.reason == "[anchor] The Coral run anchor does not run tools."
    request = EvaluationContext(phase=Phase.REQUEST, content="Run started.")
    assert (await coral_policies.evaluate(coral_spec(), anchor, request)).action == (
        PolicyAction.ALLOW
    )


async def test_orchestrator_binding_gets_the_allowlist_from_the_binding(
    coral_policies: CoralPolicies,
) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    orchestrator = coral_policies.session(run_id, role="orchestrator")
    allowed = ("coral_choose_arrow", f"{OMNIGENT}coral_choose_arrow", "ToolSearch")
    denied = ("Edit", "sys_os_write", "Skill", "coral_submit_handoff", "sys_session_message")

    # The session's spec has no Coral guardrails at all: the allowlist comes from the binding.
    verdicts = await _verdicts(coral_policies, orchestrator, (*allowed, *denied))
    for name in allowed:
        assert verdicts[name][0] == PolicyAction.ALLOW, name
    for name in denied:
        assert verdicts[name] == (PolicyAction.DENY, ["__coral_orchestrator_guard"]), name
    assert coral_policies.names(coral_spec(), orchestrator)[:3] == [
        "__coral_run_guard",
        "__coral_cost_backstop",
        "__coral_orchestrator_guard",
    ]


@pytest.mark.parametrize("role", ["step", "verifier"])
async def test_a_step_binding_gets_the_run_guard_then_the_roster(
    coral_policies: CoralPolicies, role: str
) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    step = coral_policies.session(run_id, role=role)
    plain = coral_policies.session()

    baseline = coral_policies.names(coral_spec(), plain)
    assert coral_policies.names(coral_spec(), step) == [
        "__coral_run_guard",
        "__coral_cost_backstop",
        "__coral_step_roster",
        *baseline,
    ]
    verdicts = await _verdicts(coral_policies, step, ("sys_session_message", "sys_os_shell"))
    assert verdicts["sys_session_message"] == (PolicyAction.DENY, ["__coral_step_roster"])
    assert verdicts["sys_os_shell"][0] == PolicyAction.ALLOW
    # The binding was read in the request's workspace.
    assert (WORKSPACE, step) in coral_policies.lookup.reads

    # Stopped, the run guard decides first: the roster's text, which points at the
    # handoff report, shows only while the run is live.
    coral_policies.set_status(run_id, RunStatus.PAUSED, reason=RunPauseReason.USER)
    paused = await coral_policies.call(coral_spec(), step, "sys_session_message")
    assert paused.deciding_policies == ["__coral_run_guard"]
    assert (paused.reason or "").startswith("[run.paused]")
    assert "handoff" not in (paused.reason or "")


async def test_labels_without_a_binding_add_no_policies(coral_policies: CoralPolicies) -> None:
    run_id = coral_policies.run(RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    # Labels copied onto a session that no binding names (an old fork, say).
    copied = coral_policies.session(
        labels={RUN_ID_LABEL_KEY: run_id, ROLE_LABEL_KEY: "step_agent"}
    )
    plain = coral_policies.session()
    spec = coral_spec(None)

    assert coral_policies.names(spec, copied) == coral_policies.names(spec, plain)
    assert (await coral_policies.call(spec, copied, "sys_os_shell")).action == PolicyAction.ALLOW
    # The label made the provider look; the binding row decided.
    assert (WORKSPACE, copied) in coral_policies.lookup.reads


def _conversation(labels: Any) -> Conversation:
    return Conversation(
        id="c" * 32, created_at=0, updated_at=0, root_conversation_id="c" * 32, labels=labels
    )


def test_applies_is_a_hint_that_reads_nothing_and_never_raises(
    coral_policies: CoralPolicies,
) -> None:
    provider = coral_policies.provider
    labelled = _conversation({RUN_ID_LABEL_KEY: "run-1"})

    assert provider.applies(coral_spec(), None)
    assert provider.applies(coral_spec(None), labelled)
    assert not provider.applies(coral_spec(None), _conversation({}))
    assert not provider.applies(coral_spec(None), None)
    odd_specs: list[Any] = [SimpleNamespace(), SimpleNamespace(params=None), object()]
    for spec in odd_specs:
        assert not provider.applies(spec, None)
        assert provider.applies(spec, labelled)
    odd: Any = SimpleNamespace(labels=None)
    assert not provider.applies(coral_spec(None), odd)
    assert coral_policies.lookup.reads == []


class _BindingStoreDown(RuntimeError):
    """A binding store failure no other test raises, so its traceback key is this test's."""


async def test_a_lookup_error_denies_tool_calls_only(
    coral_policies: CoralPolicies,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A fresh once-per-process log memory, so the traceback assertion is deterministic.
    monkeypatch.setattr(process_logging, "_log_once_seen", set())
    run_id = coral_policies.run(RunStatus.RUNNING)
    step = coral_policies.session(run_id)
    plain = coral_policies.session()
    ordinary = coral_policies.session()
    baseline = coral_policies.names(coral_spec(), plain)
    ordinary_names = coral_policies.names(coral_spec(None), ordinary)
    # Both Coral stores fail from here on.
    coral_policies.lookup.error = _BindingStoreDown("database is locked")

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(coral_policies.run_store, "get_run", unavailable)

    assert coral_policies.names(coral_spec(), step) == ["__coral_state_unavailable", *baseline]
    denied = await coral_policies.call(coral_spec(), step, "coral_submit_handoff")
    assert denied.action == PolicyAction.DENY
    reason = denied.reason or ""
    assert reason.startswith("[run.state_unavailable]")
    assert "Stop now and end your turn" in reason and "database is locked" not in reason
    request = EvaluationContext(phase=Phase.REQUEST, content="Continue.")
    assert (await coral_policies.evaluate(coral_spec(), step, request)).action == (
        PolicyAction.ALLOW
    )

    # An ordinary session is untouched: the same policies, its calls run, no Coral read.
    assert coral_policies.names(coral_spec(None), ordinary) == ordinary_names
    assert not any(name.startswith("__coral") for name in ordinary_names)
    shell = await coral_policies.call(coral_spec(None), ordinary, "sys_os_shell")
    assert shell.action == PolicyAction.ALLOW
    assert all(session_id != ordinary for _, session_id in coral_policies.lookup.reads)

    # Coral's own deny, not S52's provider-failure fallback. One traceback for this error
    # type; every failing build adds one line naming the session.
    records = [record for record in caplog.records if record.name == PROVIDER_LOGGER]
    assert records and all(record.levelno == logging.WARNING for record in records)
    tracebacks = [record for record in records if record.exc_info]
    assert len(tracebacks) == 1 and "_BindingStoreDown" in tracebacks[0].getMessage()
    lines = [record for record in records if not record.exc_info]
    assert len(lines) == 3
    assert all(getattr(record, "session_id", None) == step for record in lines)


async def test_a_run_status_error_keeps_the_role_guard_and_denies_tool_calls(
    coral_policies: CoralPolicies, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = coral_policies.run(RunStatus.RUNNING)
    orchestrator = coral_policies.session(run_id, role="orchestrator")

    def unavailable(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(coral_policies.run_store, "get_run", unavailable)

    names = coral_policies.names(coral_spec(), orchestrator)
    assert names[:3] == [
        "__coral_state_unavailable",
        "__coral_cost_backstop",
        "__coral_orchestrator_guard",
    ]
    choice = await coral_policies.call(coral_spec(), orchestrator, "coral_choose_arrow")
    assert choice.deciding_policies == ["__coral_state_unavailable"]
    assert (choice.reason or "").startswith("[run.state_unavailable]")


class _RunReads:
    """Counts the run store's status reads; ``error`` makes them fail as an outage would."""

    def __init__(self, coral_policies: CoralPolicies, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        self.error: str | None = None
        read = coral_policies.run_store.get_run

        def get_run(run_id: str, *, workspace_id: int | None = None) -> Any:
            self.count += 1
            if self.error is not None:
                raise RuntimeError(self.error)
            return read(run_id, workspace_id=workspace_id)

        monkeypatch.setattr(coral_policies.run_store, "get_run", get_run)


async def test_a_status_outage_serves_the_last_status_for_30_s_then_denies(
    wired_policies: CoralPolicies, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = _RunReads(wired_policies, monkeypatch)
    running = wired_policies.run(RunStatus.RUNNING)
    paused = wired_policies.run(RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    step, paused_step = wired_policies.session(running), wired_policies.session(paused)
    spec = coral_spec()

    async def bash(session_id: str) -> tuple[PolicyAction, list[str] | None, str]:
        result = await wired_policies.call(spec, session_id, "Bash")
        return result.action, result.deciding_policies, result.reason or ""

    assert (await bash(step))[0] == PolicyAction.ALLOW
    assert (await bash(paused_step))[:2] == (PolicyAction.DENY, ["__coral_run_guard"])
    assert reads.count == 2
    reads.error = "database is locked"

    # Within the TTL nothing is read; past it each build retries the store and, while that
    # fails, falls back to the status read at 1,000 s.
    for elapsed, total_reads in ((1.999, 2), (2.0, 4), (30.0, 6)):
        clock.now = 1_000.0 + elapsed
        assert (await bash(step))[0] == PolicyAction.ALLOW, elapsed
        # The fallback never turns a stopped run into a live one.
        assert (await bash(paused_step))[1] == ["__coral_run_guard"], elapsed
        assert reads.count == total_reads, elapsed

    clock.now = 1_030.001
    for session_id in (step, paused_step):
        action, deciding, reason = await bash(session_id)
        assert (action, deciding) == (PolicyAction.DENY, ["__coral_state_unavailable"])
        assert reason.startswith("[run.state_unavailable]") and "database is locked" not in reason
        # Only tool calls: the engine's message and the engine tools' replies still flow.
        request = EvaluationContext(phase=Phase.REQUEST, content="Continue.")
        assert (await wired_policies.evaluate(spec, session_id, request)).action == (
            PolicyAction.ALLOW
        )
    handoff = await wired_policies.call(spec, step, "coral_submit_handoff")
    assert handoff.deciding_policies == ["__coral_state_unavailable"]

    # The store recovers: the next build reads it again and the run's own state decides.
    reads.error = None
    assert (await bash(step))[0] == PolicyAction.ALLOW
    assert (await bash(paused_step))[1] == ["__coral_run_guard"]


async def test_a_commit_during_a_status_outage_never_serves_the_status_it_replaced(
    wired_policies: CoralPolicies, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = _RunReads(wired_policies, monkeypatch)
    run_id = wired_policies.run(RunStatus.RUNNING)
    step = wired_policies.session(run_id)
    spec = coral_spec()
    assert (await wired_policies.call(spec, step, "Bash")).action == PolicyAction.ALLOW

    # Reads fail, but a pause still commits (another connection, another replica's read path).
    reads.error = "database is locked"
    wired_policies.set_status(run_id, RunStatus.PAUSED, reason=RunPauseReason.USER)
    clock.now += 0.5
    denied = await wired_policies.call(spec, step, "Bash")
    assert denied.deciding_policies == ["__coral_state_unavailable"]


async def test_an_ordinary_session_reads_no_coral_store_on_any_build(
    coral_policies: CoralPolicies, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = _RunReads(coral_policies, monkeypatch)
    paused = coral_policies.run(RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    plain_spec = coral_spec(None)
    sessions = [
        coral_policies.session(),
        # Labels that are not ``coral.run_id`` are no hint to look.
        coral_policies.session(labels={ROLE_LABEL_KEY: "step_agent"}),
        coral_policies.session(labels={CLOSED_LABEL_KEY: CLOSED_LABEL_VALUE}),
        coral_policies.session(labels={"coral.run": paused, "CORAL.RUN_ID": paused}),
    ]
    baseline = coral_policies.names(plain_spec, sessions[0])
    reads.count, coral_policies.lookup.reads[:] = 0, []

    for session_id in sessions:
        assert coral_policies.names(plain_spec, session_id) == baseline
        for tool in ("Bash", "sys_os_shell", "coral_submit_handoff", "ToolSearch"):
            result = await coral_policies.call(plain_spec, session_id, tool)
            assert result.action == PolicyAction.ALLOW, (session_id, tool)
        request = EvaluationContext(phase=Phase.REQUEST, content="Hello.")
        assert (await coral_policies.evaluate(plain_spec, session_id, request)).action == (
            PolicyAction.ALLOW
        )
    assert (reads.count, coral_policies.lookup.reads) == (0, [])


async def test_a_labelled_session_is_decided_by_its_binding_not_its_label(
    wired_policies: CoralPolicies, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = _RunReads(wired_policies, monkeypatch)
    running = wired_policies.run(RunStatus.RUNNING)
    paused = wired_policies.run(RunStatus.PAUSED, reason=RunPauseReason.DRIFT)
    spec = coral_spec(None)
    # Labels naming a paused run, no binding row: nothing applies, nothing reads a run.
    unbound = wired_policies.session(labels={RUN_ID_LABEL_KEY: paused})
    for _ in range(3):
        assert (await wired_policies.call(spec, unbound, "Bash")).action == PolicyAction.ALLOW
    assert reads.count == 0
    # A miss is never kept: each build reads the binding store again.
    assert wired_policies.lookup.reads.count((WORKSPACE, unbound)) == 3

    # The label names the paused run but the binding the running one, and the reverse.
    live = wired_policies.session(running, labels={RUN_ID_LABEL_KEY: paused})
    stopped = wired_policies.session(paused, labels={RUN_ID_LABEL_KEY: running})
    assert (await wired_policies.call(spec, live, "Bash")).action == PolicyAction.ALLOW
    denied = await wired_policies.call(spec, stopped, "Bash")
    assert denied.deciding_policies == ["__coral_run_guard"]
    assert (denied.reason or "").startswith("[run.paused] The Coral run is paused (drift)")

    # A binding in another workspace never classifies this workspace's session.
    elsewhere = wired_policies.session(labels={RUN_ID_LABEL_KEY: paused})
    wired_policies.lookup.add(
        step_binding("work||:0", session_id=elsewhere, run_id=paused, workspace_id=WORKSPACE + 1)
    )
    assert (await wired_policies.call(coral_spec(), elsewhere, "Bash")).action == (
        PolicyAction.ALLOW
    )
