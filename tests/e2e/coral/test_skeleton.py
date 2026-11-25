"""The walking skeleton: the review-loop workflow on a real server, host, runners and CLI.

A subprocess server with the Coral plugin, a host daemon that launches each step's
runner and the real ``claude`` CLI run "Implement with review loop" on a temporary git
repository. Every model call is scripted on this test's own mock gateway. Each step's
first call is held until its brief arrives, so the test reads the activation id the
engine chose instead of predicting it.

The server is also SIGKILLed and restarted on the same database: mid-step and at the
open gate under a short leader lease, and under the production defaults while the
step's runner is stopped. The live variant runs the same kills against the real API
through a token-gated proxy; it is opt-in and skips otherwise. Run it only on a machine
with no other users (see its docstring).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import psutil
import pytest
import yaml

from coral.bridge.mapping import NEXT_RESYNC_AT
from coral.db.enum_codecs import WorkStatus
from tests.e2e.conftest import get_mock_message_requests, release_mock_gate
from tests.e2e.coral import _skeleton as sk
from tests.e2e.coral._claude_config_probe import HOOK, KEY
from tests.e2e.coral._live_proxy import LiveProxy, Secret, live_proxy

# Absolute deadline for the whole scenario, below the marker's limit.
SCENARIO_S = 200
# The default-lease proof waits out the production lease; its own limits.
DEFAULT_LEASE_SCENARIO_S = 360
# The live run gets 15 minutes against the real API.
LIVE_SCENARIO_S = 900
# A leader lease short enough that a restarted server leads within seconds.
SHORT_LEASE_S = 10
# How long after the new leader's first liveness pass the stopped runner is continued:
# well inside the 90 s grace that pass started.
CONTINUE_AFTER_S = 20
# After the release the reviewer starts in about 4 s; a close that sat out its 120 s
# turn-end limit (a guessed response id after the restart) took about 123 s.
REVIEWER_STARTS_S = 60
# Everything the run may log: no pause, drift, nudge, lost runner or refused call.
EXPECTED_LOG_KINDS = {
    "engine.start_run",
    "engine.effect_completed",
    "engine.handoff_received",
    "engine.handoff_evaluated",
    "engine.answer_gate",
}
GREETING = {"path": "greeting.txt", "content": "hello coral\n"}
GREP = {"command": "grep -q 'hello coral' greeting.txt"}
CAT = {"command": "cat greeting.txt"}
DONE = {"text": "Handed off."}
APPROVE = {"action": "accept", "content": {"decision": "approve"}}
LIVE_FLAG = "CORAL_E2E_LIVE"
LIVE_KEY = "ANTHROPIC_API_KEY"
LIVE_MODEL = "CORAL_E2E_LIVE_MODEL"
LEASE_KEYS = {"coral_worker_lease_seconds", "coral_runner_reconnect_grace_s"}
# Where a Coral CLI keeps its Claude config: a private dir in its scratch, not its home.
PRIVATE_CLAUDE_CONFIG = {
    "name": "claude_config_dir",
    "in_scratch": True,
    "in_home": False,
    "has_config": True,
}
# Offered to the orchestrator but denied by its guard: it would list the user's other sessions.
SESSION_LIST_TOOL = "mcp__omnigent__sys_session_list"


def _anchor_prompt(client: httpx.Client, run_id: str) -> tuple[str, dict[str, Any]] | None:
    """The anchor's id and its pending gate prompt, if one is pending."""
    anchor = sk.detail(client, run_id)["anchor_session_id"]
    pending = sk.session(client, anchor).get("pending_elicitations")
    return (anchor, pending[0]) if pending else None


def _gate_identity(client: httpx.Client, run_id: str) -> tuple[str, str, str | None, str] | None:
    """The open gate's visit id, token and elicitation id, and its prompt's id on the anchor."""
    gates = sk.detail(client, run_id)["gates"]
    prompt = _anchor_prompt(client, run_id)
    if len(gates) != 1 or prompt is None:
        return None
    [gate] = gates
    return gate["visit_id"], gate["token"], gate["elicitation_id"], prompt[1]["elicitation_id"]


def _resolve_route(anchor: str, elicitation_id: str) -> str:
    return f"/v1/sessions/{anchor}/elicitations/{elicitation_id}/resolve"


def _briefed(client: httpx.Client, steps: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Each step session's brief items."""
    return {
        session["id"]: [
            text
            for text in sk.session_user_texts(client, session["id"])
            if "Coral step brief." in text
        ]
        for session in steps
    }


def _checkout(stack: sk.Skeleton, run_id: str) -> tuple[subprocess.CompletedProcess[str], Any]:
    """Run the outcome's checkout command; return it with the outcome."""
    outcome = stack.client.get(f"{sk.RUNS}/{run_id}/outcome").json()
    done = subprocess.run(
        ["sh", "-c", outcome["checkout"]["command"]],
        capture_output=True,
        text=True,
        check=False,
        env={**sk.minimal_env(), "HOME": str(stack.root)},
    )
    return done, outcome


# A plugin hook and a session key in the host's home, which no step may change.
def _claude_canaries(home: Path) -> tuple[str, list[str]]:
    return (home / HOOK).read_text(), sorted(path.name for path in (home / KEY).parent.iterdir())


def _plant_claude_canaries(home: Path) -> tuple[str, list[str]]:
    for relative, text in ((HOOK, '{"hooks": {}}'), (KEY, '{"peerToken": "canary"}')):
        (home / relative).parent.mkdir(parents=True, exist_ok=True)
        (home / relative).write_text(text)
    return _claude_canaries(home)


def _cli_claude_config(stack: sk.Skeleton, session_id: str) -> dict[str, Any]:
    """Where the session's live CLI keeps its Claude config."""
    runner = sk.runner_pid(stack, session_id)
    environ = sk.step_processes(runner, sk.session_cli(stack, runner, session_id))["cli"].environ()
    config_dir = Path(environ.get("CLAUDE_CONFIG_DIR", ""))
    return {
        "name": config_dir.name,
        "in_scratch": Path(environ.get("TMPDIR", "/nonexistent")) in config_dir.parents,
        "in_home": config_dir.is_relative_to(stack.host.home),
        "has_config": (config_dir / ".claude.json").is_file(),
    }


def _sigkill_server(stack: sk.Skeleton) -> None:
    """Kill the server outright, then start it again on its port, database and config."""
    server = stack.server.server
    assert server is not None
    server.kill()
    server.wait(timeout=10)
    sk.start_server(stack)


@pytest.mark.timeout(300, method="signal")
def test_the_review_loop_runs_end_to_end_on_a_real_stack(
    tmp_path: Path, isolated_mock_llm_server_url: str
) -> None:
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    # Longer, so a reviewer call that also quotes the implementer's token routes here.
    review_token = f"review-{uid}-pass"
    write, early, done, denied = (f"{name}-{uid}" for name in ("write", "early", "done", "deny"))
    sk.queue(mock, impl_token, [sk.held(sk.tool_call(sk.WRITE_TOOL, GREETING, call_id=write))])
    sk.queue(
        mock,
        review_token,
        [
            sk.held(
                sk.tool_call(sk.WRITE_TOOL, {"path": "owned.txt", "content": "x"}, call_id=denied)
            )
        ],
    )
    deadline = time.monotonic() + SCENARIO_S

    with sk.skeleton_stack(
        tmp_path / "stack", mock_url=mock, host_config=sk.mock_auth(mock), lease_s=SHORT_LEASE_S
    ) as stack:
        client = stack.client
        canaries = _plant_claude_canaries(stack.host.home)
        run_id = sk.start_review_loop(
            stack, impl_token=impl_token, review_token=review_token, start_key=f"skeleton-{uid}"
        )
        wait = sk.waiter(stack, run_id, deadline)

        # Implement, pass 1: a handoff before the check is refused, then accepted after it.
        implement_1 = sk.held_activation(wait, mock, impl_token, 1)
        # Read while the step's CLI is held on its first call.
        cli_switches = {
            (env.get("DISABLE_AUTOUPDATER"), env.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"))
            for env in sk.cli_environs(stack.root)
        }
        step_config = _cli_claude_config(stack, sk.step_session(client, run_id, "implement"))
        sk.queue(
            mock,
            impl_token,
            [
                sk.handoff_call(implement_1, call_id=early, report="Wrote greeting.txt."),
                sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep-{uid}"),
                sk.handoff_call(implement_1, call_id=done, report="Checked greeting.txt."),
                DONE,
                # The next pass's first call, held until its brief is read.
                sk.held(sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep2-{uid}")),
            ],
        )
        release_mock_gate(mock)

        # Review, pass 1: the write was denied; the reviewer asks for one more pass.
        review_1 = sk.held_activation(wait, mock, review_token, 1)
        sk.queue(
            mock,
            review_token,
            [
                sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"cat-{uid}"),
                sk.handoff_call(
                    review_1,
                    call_id=f"changes-{uid}",
                    report="Asked for one more pass.",
                    label="changes_requested",
                ),
                DONE,
                sk.held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"cat2-{uid}")),
            ],
        )
        release_mock_gate(mock)

        # Implement, pass 2, then review, pass 2 approves.
        implement_2 = sk.held_activation(wait, mock, impl_token, 2)
        sk.queue(
            mock,
            impl_token,
            [sk.handoff_call(implement_2, call_id=f"done2-{uid}", report="Checked again."), DONE],
        )
        release_mock_gate(mock)
        review_2 = sk.held_activation(wait, mock, review_token, 2)
        sk.queue(
            mock,
            review_token,
            [
                sk.handoff_call(
                    review_2, call_id=f"approved-{uid}", report="Looks right.", label="approved"
                ),
                DONE,
            ],
        )
        release_mock_gate(mock)

        # The gate: an outcome it does not offer is refused, then approve ends the run.
        visit = wait(lambda: (sk.detail(client, run_id)["gates"] or [None])[0], "the gate visit")
        anchor, prompt = wait(lambda: _anchor_prompt(client, run_id), "the prompt on the anchor")
        resolve = _resolve_route(anchor, prompt["elicitation_id"])
        refused = client.post(resolve, json={"action": "accept", "content": {"decision": "maybe"}})
        waiting = sk.detail(client, run_id)
        answered = client.post(resolve, json=APPROVE)

        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        sessions = sk.coral_sessions(client, run_id)
        steps = [session for session in sessions if session["labels"]["coral.role"] == "step"]
        briefed = _briefed(client, steps)
        kinds = sk.log_kinds(client, run_id)
        logs = "\n".join(path.read_text(errors="replace") for path in stack.root.rglob("*.log"))
        worktree = Path(run["target"]["worktree_path"])
        reviewer_wrote = (worktree / "owned.txt").exists()
        checkout, outcome = _checkout(stack, run_id)
        greeting = (stack.repo / "greeting.txt").read_text() if checkout.returncode == 0 else None
        canaries_after = _claude_canaries(stack.host.home)

    assert (run["status"], run["causes"]) == ("completed", []), run
    # The step's CLI ran with its self-update and non-essential traffic off.
    assert cli_switches == {("1", "1")}, cli_switches
    # Its Claude config was a private dir in its scratch, and the home's canaries held.
    assert step_config == PRIVATE_CLAUDE_CONFIG, step_config
    assert canaries_after == canaries, canaries_after
    # One evidence rejection, then the same activation's handoff is accepted.
    [rejected] = sk.result_texts(mock, early)
    [accepted] = sk.result_texts(mock, done)
    assert '"accepted": false' in rejected and '"reason": "evidence.missing"' in rejected, rejected
    assert '"accepted": true' in accepted, accepted
    # The reviewer's write is denied and leaves the worktree unchanged.
    [denial] = sk.result_texts(mock, denied)
    assert "report-only" in denial, denial
    assert not reviewer_wrote
    # The loop ran once: two passes of each step, each its own activation.
    assert len({implement_1, implement_2, review_1, review_2}) == 4
    # An outcome the gate does not offer is refused and the run keeps waiting at it.
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["message"].startswith("[invalid_answer]"), refused.text
    assert (waiting["status"], waiting["causes"]) == ("running", []), waiting
    assert [gate["visit_id"] for gate in waiting["gates"]] == [visit["visit_id"]]
    assert answered.status_code == 202, answered.text
    # One anchor, and one step session per slot activation, each briefed once.
    assert sorted(session["labels"]["coral.role"] for session in sessions) == [
        "run",
        *["step"] * 4,
    ]
    assert sorted(session["labels"]["coral.node_id"] for session in steps) == [
        "implement",
        "implement",
        "review",
        "review",
    ]
    assert all(len(texts) == 1 for texts in briefed.values()), briefed
    assert set(kinds) <= EXPECTED_LOG_KINDS, kinds
    assert "sending it a '" not in logs
    # The outcome's checkout command puts the change in the repository's checkout.
    assert outcome["branch"] == run["run_branch"]
    assert checkout.returncode == 0, checkout.stderr
    assert greeting == "hello coral\n"


@pytest.mark.timeout(300, method="signal")
def test_the_review_loop_survives_server_sigkills_mid_step_and_at_the_gate(
    tmp_path: Path, isolated_mock_llm_server_url: str
) -> None:
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    review_token = f"review-{uid}-pass"
    across_kill = f"handoff-{uid}"
    first_write = sk.held(sk.tool_call(sk.WRITE_TOOL, GREETING, call_id=f"w-{uid}"))
    sk.queue(mock, impl_token, [first_write])
    sk.queue(mock, review_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"cat-{uid}"))])
    deadline = time.monotonic() + SCENARIO_S

    with sk.skeleton_stack(
        tmp_path / "stack", mock_url=mock, host_config=sk.mock_auth(mock), lease_s=SHORT_LEASE_S
    ) as stack:
        client = stack.client
        run_id = sk.start_review_loop(
            stack, impl_token=impl_token, review_token=review_token, start_key=f"kills-{uid}"
        )
        wait = sk.waiter(stack, run_id, deadline)

        # Implement, pass 1: its third model call is held mid-turn across the first kill.
        implement_1 = sk.held_activation(wait, mock, impl_token, 1)
        sk.queue(
            mock,
            impl_token,
            [
                sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep-{uid}"),
                sk.held(sk.handoff_call(implement_1, call_id=across_kill, report="Checked it.")),
                DONE,
                sk.held(sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep2-{uid}")),
            ],
        )
        release_mock_gate(mock)

        def third_call_held() -> bool | None:
            calls = sk.calls_carrying(get_mock_message_requests(mock), impl_token)
            return True if len(calls) == 3 and sk.mock_holds_a_call(mock) else None

        wait(third_call_held, "the implementer's third call")
        kinds_at_kill = sk.log_kinds(client, run_id)
        implementer = sk.step_session(client, run_id, "implement")
        runner_before = sk.session(client, implementer)["runner_id"]
        starts = len(sk.server_logs(stack))
        _sigkill_server(stack)
        # The handoff needs the host's workspace channel; release only once both are back.
        [log] = sk.server_logs(stack)[starts:]
        wait(sk.reconnected(stack, log, runner_before), "the host and the implementer's runner")
        runner_after = wait(sk.runner_back(client, implementer), "the implementer's runner")
        release_mock_gate(mock)

        # Review, pass 1 asks for one more pass; pass 2 of each step, then approve.
        review_1 = sk.held_activation(wait, mock, review_token, 1)
        sk.queue(
            mock,
            review_token,
            [
                sk.handoff_call(
                    review_1,
                    call_id=f"changes-{uid}",
                    report="One more.",
                    label="changes_requested",
                ),
                DONE,
                sk.held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"cat2-{uid}")),
            ],
        )
        release_mock_gate(mock)
        implement_2 = sk.held_activation(wait, mock, impl_token, 2)
        sk.queue(
            mock,
            impl_token,
            [sk.handoff_call(implement_2, call_id=f"done2-{uid}", report="Checked again."), DONE],
        )
        release_mock_gate(mock)
        review_2 = sk.held_activation(wait, mock, review_token, 2)
        sk.queue(
            mock,
            review_token,
            [
                sk.handoff_call(
                    review_2, call_id=f"approved-{uid}", report="Looks right.", label="approved"
                ),
                DONE,
            ],
        )
        release_mock_gate(mock)

        # The open gate: its identity before and after the second kill.
        opened = wait(lambda: _gate_identity(client, run_id), "the gate's prompt")
        _sigkill_server(stack)
        reopened = wait(lambda: _gate_identity(client, run_id), "the gate's prompt again")
        anchor, prompt = wait(lambda: _anchor_prompt(client, run_id), "the anchor's prompt")
        resolve = _resolve_route(anchor, prompt["elicitation_id"])
        answered = client.post(resolve, json=APPROVE)
        repeated = client.post(resolve, json=APPROVE)

        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        sessions = sk.coral_sessions(client, run_id)
        steps = [session for session in sessions if session["labels"]["coral.role"] == "step"]
        briefed = _briefed(client, steps)
        kinds = sk.log_kinds(client, run_id)
        logs = "\n".join(path.read_text(errors="replace") for path in stack.root.rglob("*.log"))
        checkout, outcome = _checkout(stack, run_id)
        greeting = (stack.repo / "greeting.txt").read_text() if checkout.returncode == 0 else None

    assert (run["status"], run["causes"]) == ("completed", []), run
    # The first kill landed mid-step: the held call carries the handoff, so none was in yet.
    assert "engine.handoff_received" not in kinds_at_kill, kinds_at_kill
    # The turn held across the first kill went on in the same session and runner.
    assert runner_after == runner_before
    [accepted] = sk.result_texts(mock, across_kill)
    assert '"accepted": true' in accepted, accepted
    # The gate kept its visit, token and prompt across the second kill, and answered once.
    assert reopened == opened, (opened, reopened)
    assert opened[2] == opened[3], opened
    assert (answered.status_code, answered.json()) == (202, {"queued": False}), answered.text
    # A repeat of the answer is recognised as a duplicate and queues nothing.
    assert (repeated.status_code, repeated.json()) == (202, {"queued": False, "duplicate": True})
    assert kinds.count("engine.answer_gate") == 1, kinds
    # No lost runner, no pause and no nudge; the loop ran once.
    assert set(kinds) <= EXPECTED_LOG_KINDS, kinds
    assert len({implement_1, implement_2, review_1, review_2}) == 4
    # Zero duplicate sessions: one anchor, one session per slot, each briefed once.
    assert sorted(session["labels"]["coral.role"] for session in sessions) == [
        "run",
        *["step"] * 4,
    ]
    assert sorted(session["id"] for session in steps) == sorted(
        slot["session_id"] for slot in run["slots"]
    )
    assert {slot["session_generation"] for slot in run["slots"]} == {1}, run["slots"]
    assert all(len(texts) == 1 for texts in briefed.values()), briefed
    assert "sending it a '" not in logs
    assert outcome["branch"] == run["run_branch"]
    assert checkout.returncode == 0, checkout.stderr
    assert greeting == "hello coral\n"


def _new_leader(stack: sk.Skeleton, before: str | None) -> Callable[[], str | None]:
    def probe() -> str | None:
        holder = sk.worker_lease_holder(stack)
        return holder if holder is not None and holder != before else None

    return probe


def _resynced_after(stack: sk.Skeleton, run_id: str, at: float) -> Callable[[], bool | None]:
    """
    Whether a resync that found no missing runner finished at least a second after epoch
    second ``at``: a pass with a running clock names when its grace ends.
    """

    def probe() -> bool | None:
        [resync] = [
            item for item in sk.work_items(stack, run_id) if item.effect_type == "run_resync"
        ]
        done = resync.status == int(WorkStatus.SUCCEEDED) and resync.finished_at is not None
        clock_free = NEXT_RESYNC_AT not in (resync.result or {})
        return True if done and clock_free and resync.finished_at >= at + 1 else None

    return probe


@pytest.mark.timeout(420, method="signal")
def test_a_runner_reconnecting_after_a_default_lease_restart_is_not_relaunched(
    tmp_path: Path, isolated_mock_llm_server_url: str
) -> None:
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    review_token = f"review-{uid}-pass"
    handed = f"handoff-{uid}"
    first_write = sk.held(sk.tool_call(sk.WRITE_TOOL, GREETING, call_id=f"w-{uid}"))
    sk.queue(mock, impl_token, [first_write])
    sk.queue(mock, review_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"cat-{uid}"))])
    began = time.monotonic()
    deadline = began + DEFAULT_LEASE_SCENARIO_S
    # Seconds after the runner's stop and the server's kill at which each phase was seen.
    seen: dict[str, float] = {}

    # No lease or grace key: the production defaults.
    with sk.skeleton_stack(
        tmp_path / "stack", mock_url=mock, host_config=sk.mock_auth(mock)
    ) as stack:
        client = stack.client
        server_config = yaml.safe_load((stack.root / "server.yaml").read_text())
        run_id = sk.start_review_loop(
            stack, impl_token=impl_token, review_token=review_token, start_key=f"lease-{uid}"
        )
        wait = sk.waiter(stack, run_id, deadline)

        # The implementer's first call is held; its runner is stopped across the restart.
        implement = sk.held_activation(wait, mock, impl_token, 1)
        # This hold outlasts the CLI's wait for a first byte (about two minutes on 2.1.325),
        # after which it sends the call again. Each repeat is held too; three are all the
        # scenario's deadline leaves room for.
        repeats = [
            sk.held(sk.tool_call(sk.WRITE_TOOL, GREETING, call_id=f"w{number}-{uid}"))
            for number in range(2, 5)
        ]
        sk.queue(mock, impl_token, repeats)
        implementer = sk.step_session(client, run_id, "implement")
        runner_before = sk.session(client, implementer)["runner_id"]
        pid = sk.runner_pid(stack, implementer)
        leader_before = sk.worker_lease_holder(stack)
        starts = len(sk.server_logs(stack))
        os.killpg(pid, signal.SIGSTOP)
        killed = time.monotonic()
        try:
            wait(lambda: sk.group_stopped(pid) or None, "the runner's process group to stop")
            _sigkill_server(stack)
            wait(_new_leader(stack, leader_before), "the new leader")
            seen["leading"] = time.monotonic() - killed
            [log] = sk.server_logs(stack)[starts:]
            clock_started = f"Coral liveness of run {run_id}: 1 runner clock(s) started"
            wait(
                lambda: clock_started in log.read_text(errors="replace") or None, "the first pass"
            )
            seen["first_pass"] = time.monotonic() - killed
            # Continue the runner well inside the grace that pass started.
            time.sleep(max(0.0, killed + seen["first_pass"] + CONTINUE_AFTER_S - time.monotonic()))
        finally:
            # A stopped group would sit out the teardown's SIGTERM; a group the host
            # already ended must not hide the failure that ended it.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGCONT)
        seen["continued"] = time.monotonic() - killed
        runner_after = wait(sk.runner_back(client, implementer), "the stopped runner to reconnect")
        seen["back"] = time.monotonic() - killed
        wait(_resynced_after(stack, run_id, time.time()), "one more resync")
        seen["resynced"] = time.monotonic() - killed
        effects = [item.effect_type for item in sk.work_items(stack, run_id)]
        kinds_before_release = sk.log_kinds(client, run_id)
        launches_before_release = stack.host.log_path.read_text().count("Launched runner ")
        runner_alive = psutil.pid_exists(pid)
        held_calls = sk.calls_carrying(get_mock_message_requests(mock), impl_token)
        sent = len(held_calls)
        liveness_lines = log.read_text(errors="replace")

        # Released, the turn goes on and its handoff is accepted; the run then completes.
        sk.queue(
            mock,
            impl_token,
            [
                sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep-{uid}"),
                sk.handoff_call(implement, call_id=handed, report="Checked greeting.txt."),
                DONE,
            ],
        )
        # The oldest first: the calls the CLI gave up on, then the one it waits on.
        released = time.monotonic()
        while sk.mock_holds_a_call(mock):
            release_mock_gate(mock)
        review = sk.held_activation(wait, mock, review_token, 1)
        reviewer_after = time.monotonic() - released
        seen["handed_off"] = time.monotonic() - killed
        sk.queue(
            mock,
            review_token,
            [
                sk.handoff_call(
                    review, call_id=f"ok-{uid}", report="Looks right.", label="approved"
                ),
                DONE,
            ],
        )
        release_mock_gate(mock)
        anchor, prompt = wait(lambda: _anchor_prompt(client, run_id), "the anchor's prompt")
        answered = client.post(_resolve_route(anchor, prompt["elicitation_id"]), json=APPROVE)
        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        kinds = sk.log_kinds(client, run_id)
        host_log = stack.host.log_path.read_text(errors="replace")
    seen["total"] = time.monotonic() - began
    seen["calls_held"] = sent
    print("Default-lease restart, seconds after the stop and kill:", json.dumps(seen))

    assert not LEASE_KEYS & server_config.keys(), server_config
    # Neither detector lost the runner, and no wake was queued, while it was stopped.
    assert "engine.runner_lost" not in kinds_before_release, kinds_before_release
    assert "recovery.wake" not in effects, effects
    # The same runner came back: none was relaunched or superseded.
    assert runner_after == runner_before
    assert runner_alive
    assert launches_before_release == 1, launches_before_release
    # The held call, and any repeats of it: the same request, not a new turn.
    assert sent >= 1, sent
    assert len({json.dumps(call["body"], sort_keys=True) for call in held_calls}) == 1, held_calls
    # Every pass of the new leader read the runner, and none reported it lost.
    assert "Coral liveness check of run" not in liveness_lines
    assert "could not read a runner's liveness" not in liveness_lines
    assert "Stopped superseded runner" not in host_log
    [accepted] = sk.result_texts(mock, handed)
    assert '"accepted": true' in accepted, accepted
    # The implementer's close ended on its turn's own end edge, not at its time limit.
    assert reviewer_after < REVIEWER_STARTS_S, reviewer_after
    assert answered.status_code == 202, answered.text
    assert (run["status"], run["causes"]) == ("completed", []), run
    assert set(kinds) <= EXPECTED_LOG_KINDS, kinds


@pytest.mark.timeout(180, method="signal")
def test_a_stack_without_log_tails_reports_start_failures_without_log_text(
    tmp_path: Path,
) -> None:
    # A lease below the plugin's floor fails the server's start, and its log says why.
    with (
        pytest.raises(AssertionError) as shown,
        sk.skeleton_stack(tmp_path / "tails", mock_url=None, host_config={}, lease_s=9),
    ):
        pass
    with (
        pytest.raises(AssertionError) as hidden,
        sk.skeleton_stack(
            tmp_path / "quiet", mock_url=None, host_config={}, lease_s=9, failure_log_tails=False
        ),
    ):
        pass
    with sk.skeleton_stack(
        tmp_path / "restart", mock_url=None, host_config={}, failure_log_tails=False
    ) as stack:
        sk.write_server_config(stack.root / "server.yaml", mock_url=None, lease_s=9)
        server = stack.server.server
        assert server is not None
        server.kill()
        server.wait(timeout=10)
        with pytest.raises(AssertionError) as restarted:
            sk.start_server(stack)

    assert "coral_worker_lease_seconds" in str(shown.value)
    assert str(hidden.value) == "The server's start failed; its logs are under the stack root"
    assert hidden.value.__suppress_context__ and hidden.value.__cause__ is None
    assert str(restarted.value) == (
        "The server's restart failed; its logs are under the stack root"
    )


@pytest.mark.timeout(300, method="signal")
@pytest.mark.parametrize("deferred", [True, False], ids=["direct-key", "gateway"])
def test_a_decision_runs_through_a_real_orchestrator_cli(
    tmp_path: Path, isolated_mock_llm_server_url: str, deferred: bool
) -> None:
    """
    A run whose only node is a decision: the engine asks the orchestrator, whose real CLI the
    host launches in its read-only sandbox, and the mock model chooses the second of two
    labelled arrows. The run ends on that arrow's own end node.

    ``direct-key``: the host's credential is a key with no endpoint of its own, so the CLI
    reaches the mock through its executor's credential proxy and defers its MCP tools; the
    model loads ``coral_choose_arrow`` with ToolSearch first. ``gateway``: the host's
    credential names the mock, the CLI lists its MCP tools directly, and the model first calls
    one that the orchestrator's guard denies. The stack's keychain stand-ins are checked at
    its teardown.
    """
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    token = f"decide-{uid}"
    chose, denied = f"choose-{uid}", f"denied-{uid}"
    if deferred:
        offering = sk.TOOL_SEARCH
        host_config: dict[str, Any] = {"auth": {"type": "api_key", "api_key": "mock-key"}}
        host_env = {"ANTHROPIC_BASE_URL": mock}
        search = {"query": f"select:{sk.CHOOSE_TOOL}", "max_results": 1}
        first = sk.tool_call(sk.TOOL_SEARCH, search, call_id=f"search-{uid}")
    else:
        offering, host_config, host_env = sk.CHOOSE_TOOL, sk.mock_auth(mock), {}
        first = sk.tool_call(SESSION_LIST_TOOL, {}, call_id=denied)
    # Held while the CLI is read and the decision id is taken from the request.
    sk.queue(mock, token, [sk.held(first)], offering=offering)
    deadline = time.monotonic() + SCENARIO_S

    with sk.skeleton_stack(
        tmp_path / "stack",
        mock_url=mock,
        host_config=host_config,
        host_env=host_env,
        lease_s=SHORT_LEASE_S,
    ) as stack:
        client = stack.client
        workflow = (sk.FIXTURES / "decision.yaml").read_text().replace("{token}", token)
        run_id = sk.start_run(
            client,
            workflow_id=sk.save_workflow(client, workflow),
            host_id=stack.host.host_id,
            repo=stack.repo,
            start_key=f"decision-{uid}",
        )["run_id"]
        wait = sk.waiter(stack, run_id, deadline)
        decision = sk.held_decision(wait, mock, token, offering=offering)
        # Read while the orchestrator's CLI is held on its first call.
        orchestrator = sk.detail(client, run_id)["orchestrator_session_id"]
        runner = sk.runner_pid(stack, orchestrator)
        processes = sk.step_processes(runner, sk.session_cli(stack, runner, orchestrator))
        outside = sk.keychain_bypasses(
            stack.stubs, stack.root, processes.values(), unread_fails=True
        )
        # Set only by the CLI's own launcher before its wrap: a Coral harness drops it.
        wrapped = processes["cli"].environ().get("OMNIGENT_LAUNCHER_SPAWN_WRAPPED")
        launched = (processes["launcher"].pid != processes["cli"].pid, wrapped)
        config = _cli_claude_config(stack, orchestrator)
        # The second-declared label, so walking the first labelled arrow cannot pass.
        choice = {"decision_id": decision, "label": "hold", "reason": "It is not ready."}
        sk.queue(
            mock,
            token,
            [sk.tool_call(sk.CHOOSE_TOOL, choice, call_id=chose), {"text": "Chose hold."}],
            offering=offering,
        )
        release_mock_gate(mock)
        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        sessions = sk.coral_sessions(client, run_id)
        log = sk.log_entries(client, run_id)

    assert (run["status"], run["causes"]) == ("completed", []), run
    # One choice, accepted and recorded with its label, and the run went down that arrow only.
    [accepted] = sk.result_texts(mock, chose)
    assert '"accepted": true' in accepted, accepted
    entries = [(row["kind"], row["rejected"], row["body"]["input"].get("label")) for row in log]
    assert entries == [
        ("engine.start_run", None, None),
        ("engine.choose_arrow", None, "hold"),
    ], entries
    reached = [activation["id"].split("|")[0] for activation in run["view"]["activations"]]
    assert reached == ["start", "decide", "held_back"], reached
    if not deferred:
        # The guard denied the earlier call before the runner ran it, and the turn went on.
        [refused] = sk.result_texts(mock, denied)
        assert "[orchestrator]" in refused, refused[:500]
    # One orchestrator session beside the anchor, and the CLI that served it was launched
    # through a sandbox wrap.
    roles = {session["id"]: session["labels"]["coral.role"] for session in sessions}
    assert sorted(roles.values()) == ["orchestrator", "run"], roles
    assert roles.get(orchestrator) == "orchestrator", (orchestrator, roles)
    assert launched == (True, "1"), (launched, sk.process_names(processes.values()))
    # Its HOME was the stack's, with the stand-ins first on PATH; its config dir was private.
    assert not outside, f"orchestrator processes outside the keychain barrier: {outside}"
    assert config == PRIVATE_CLAUDE_CONFIG, config


def _files_holding(root: Path, secret: Secret) -> int:
    """How many regular files under ``root`` hold ``secret``; links are not followed."""
    holding = 0
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink() and secret.found_in(path):
                holding += 1
        except OSError:
            continue
    return holding


@pytest.fixture
def live_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[LiveProxy]:
    """
    The live run's proxy, which alone holds the API key, so no test or helper frame does.

    The key is read once and taken out of the environment, so no process the test
    starts inherits it. At teardown the basetemp is searched for it, then deleted.
    """
    missing = [
        name
        for name, present in (
            (f"{LIVE_FLAG}=1", os.environ.get(LIVE_FLAG) == "1"),
            (LIVE_KEY, bool(os.environ.get(LIVE_KEY))),
        )
        if not present
    ]
    if missing:
        pytest.skip(f"the live review loop needs {' and '.join(missing)}")
    key = Secret(os.environ[LIVE_KEY])
    monkeypatch.delenv(LIVE_KEY)
    with live_proxy(key) as proxy:
        yield proxy
    basetemp = tmp_path_factory.getbasetemp()
    holding = _files_holding(basetemp, key)
    shutil.rmtree(basetemp, ignore_errors=True)
    assert holding == 0, f"{holding} file(s) under the basetemp held the API key"


@pytest.mark.timeout(1200, method="signal")
def test_live_review_loop_survives_server_sigkills(
    tmp_path: Path, live_api: LiveProxy, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    The review loop against the real Anthropic API, with a server kill mid-step and one at
    the gate.

    The CLI gets the proxy's per-run token, never the key, but on macOS a step's shell
    can read the key from the environment of this process and its parents.
    The token does not fence out other local accounts: it reaches the CLI's command
    line, which any local user can read, and the stack's server serves unauthenticated
    local requests. Run this only on a machine with no other users.
    """
    sk.require_claude_cli()
    uid = uuid.uuid4().hex[:12]
    model = os.environ.get(LIVE_MODEL)
    deadline = time.monotonic() + LIVE_SCENARIO_S

    # The CLI gets the proxy's per-run token, never the key.
    auth = {"type": "api_key", "api_key": live_api.token, "base_url": live_api.url}
    with sk.skeleton_stack(
        tmp_path / "stack",
        mock_url=None,
        host_config={"auth": auth},
        host_env={"ANTHROPIC_MODEL": model} if model else None,
        lease_s=SHORT_LEASE_S,
        failure_log_tails=False,
    ) as stack:
        client = stack.client
        run_id = sk.start_review_loop(
            stack, impl_token=f"impl-{uid}", review_token=f"review-{uid}-pass", start_key=uid
        )
        wait = sk.waiter(stack, run_id, deadline)

        def implementing() -> bool | None:
            slots = [
                slot
                for slot in sk.detail(client, run_id)["slots"]
                if slot["node_id"] == "implement" and slot["session_id"]
            ]
            statuses = [sk.session(client, slot["session_id"])["status"] for slot in slots]
            return True if "running" in statuses else None

        wait(implementing, "the implementer's turn")
        _sigkill_server(stack)
        opened = wait(lambda: _gate_identity(client, run_id), "the gate's prompt")
        _sigkill_server(stack)
        reopened = wait(lambda: _gate_identity(client, run_id), "the gate's prompt again")
        anchor, prompt = wait(lambda: _anchor_prompt(client, run_id), "the anchor's prompt")
        answered = client.post(_resolve_route(anchor, prompt["elicitation_id"]), json=APPROVE)
        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        sessions = sk.coral_sessions(client, run_id)
        steps = [session for session in sessions if session["labels"]["coral.role"] == "step"]
        kinds = sk.log_kinds(client, run_id)
        checkout, outcome = _checkout(stack, run_id)

    spend = run["spend"] or {}
    with capsys.disabled():
        print(
            f"\nLive review loop spend: usd={spend.get('usd')} "
            f"tokens={(spend.get('tokens') or {}).get('total')} sessions={spend.get('sessions')}"
        )
    assert (run["status"], run["causes"]) == ("completed", []), (run["status"], run["causes"])
    assert reopened == opened, (opened, reopened)
    assert answered.status_code == 202, answered.status_code
    # Exactly one session per slot that ran, and no drift pause.
    assert sorted(session["id"] for session in steps) == sorted(
        slot["session_id"] for slot in run["slots"]
    )
    assert {slot["session_generation"] for slot in run["slots"]} == {1}, run["slots"]
    assert "engine.pause_run" not in kinds, kinds
    assert outcome["branch"] == run["run_branch"]
    assert checkout.returncode == 0, checkout.returncode
