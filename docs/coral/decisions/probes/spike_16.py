"""Spike 16: does a generated step's long model call outlive the runner and harness reapers?

Run from the repository root: ``uv run --no-sync python docs/coral/decisions/probes/spike_16.py``.

Local only. A Coral implementer's model call is held for 180 s on a real stack whose host
sets ``runner.idle_timeout_s: 60`` and ``OMNIGENT_HARNESS_IDLE_TIMEOUT_S=60``, then
released. It passes only if the step's own runner, harness, sandbox launcher and CLI
all live through the hold, neither reaper logs against the step, and its handoff is
accepted; and only if the positive controls show the runner's window was live: the
runner read its 60 s window, and a sibling step left idle (the reviewer, paused at its
nudge limit) has its runner shut itself down for idleness. The harness window must also
reach the step's launcher; that shows it configured, not its reaper seen firing.

Holds above about 240 s are not holds: the CLI's second resend draws from an exhausted
queue and gets the mock's default answer.
"""

import argparse
import contextlib
import json
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tests.e2e._harness_probes import cli_unavailable_reason
from tests.e2e.conftest import (
    _mock_llm_server_process,
    get_mock_message_requests,
    release_mock_gate,
)
from tests.e2e.coral import _skeleton as sk
from tests.e2e.coral._claude_sdk_kit import cli_versions

RERUN = "uv run --no-sync python docs/coral/decisions/probes/spike_16.py"
GREETING = {"path": "greeting.txt", "content": "hello coral\n"}
GREP = {"command": "grep -q 'hello coral' greeting.txt"}
CAT = {"command": "cat greeting.txt"}
HARNESS_IDLE_ENV = "OMNIGENT_HARNESS_IDLE_TIMEOUT_S"
# The runner's and the harness reaper's own log lines.
RUNNER_IDLE = "runner idle timeout reached after"
RUNNER_EXITING = "runner exiting:"
HARNESS_REAPED = "reaping idle harness subprocess for conversation"
SAMPLE_S = 5.0
# A runner's wait to end: the idle window, the monitor's cadence and its shutdown.
EXIT_WAIT_S = 150.0


def _runner_log(stack: sk.Skeleton, session_id: str) -> str:
    logs = stack.host.home / ".omnigent" / "logs" / "runner"
    return "\n".join(
        path.read_text(errors="replace")
        for path in sorted(logs.glob(f"runner-{session_id}-*.log"))
    )


def _messages(log: str, marker: str) -> list[str]:
    """The text from ``marker`` on, for each log line carrying it."""
    return [line[line.index(marker) :][:120] for line in log.splitlines() if marker in line]


def _paused(stack: sk.Skeleton, run_id: str) -> dict | None:
    run = sk.detail(stack.client, run_id)
    return run if run["status"] == "paused" else None


def _exit_after(proc: psutil.Process) -> float | None:
    """Seconds until ``proc`` ends, within ``EXIT_WAIT_S``, else ``None``."""
    began = time.monotonic()
    while time.monotonic() < began + EXIT_WAIT_S:
        if not sk.still_running([proc]):
            return round(time.monotonic() - began, 1)
        time.sleep(SAMPLE_S)
    return None


def _run(root: Path, mock: str, hold_s: float, idle_s: int) -> dict:
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    review_token = f"review-{uid}-pass"
    handed = f"handoff-{uid}"
    sk.queue(
        mock, impl_token, [sk.held(sk.tool_call(sk.WRITE_TOOL, GREETING, call_id=f"w-{uid}"))]
    )
    sk.queue(mock, review_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, CAT, call_id=f"c-{uid}"))])
    host_config = {**sk.mock_auth(mock), "runner": {"idle_timeout_s": idle_s}}
    with sk.skeleton_stack(
        root / "stack",
        mock_url=mock,
        host_config=host_config,
        host_env={HARNESS_IDLE_ENV: str(idle_s)},
        lease_s=10,
    ) as stack:
        run_id = sk.start_review_loop(
            stack, impl_token=impl_token, review_token=review_token, start_key=f"spike16-{uid}"
        )
        deadline = time.monotonic() + hold_s + 3 * EXIT_WAIT_S + 120
        wait = sk.waiter(stack, run_id, deadline)
        implement = sk.held_activation(wait, mock, impl_token, 1)
        held_at = time.monotonic()
        # The CLI sends a call with no answer again after about 120 s; hold that too.
        sk.queue(
            mock, impl_token, [sk.held(sk.tool_call(sk.WRITE_TOOL, GREETING, call_id=f"w2-{uid}"))]
        )
        session_id = sk.step_session(stack.client, run_id, "implement")
        runner_id = sk.session(stack.client, session_id)["runner_id"]
        pid = sk.runner_pid(stack, session_id)
        step = sk.step_processes(pid)
        # Not a control: the harness window as configured in the launcher, read once.
        harness_window = step["launcher"].environ().get(HARNESS_IDLE_ENV)
        gone: dict[str, float] = {}
        while True:
            for role, proc in step.items():
                if role not in gone and not sk.still_running([proc]):
                    gone[role] = round(time.monotonic() - held_at, 1)
            if time.monotonic() >= held_at + hold_s:
                break
            time.sleep(SAMPLE_S)
        during = _runner_log(stack, session_id)
        calls = len(sk.calls_carrying(get_mock_message_requests(mock), impl_token))
        same_runner = sk.session(stack.client, session_id)["runner_id"] == runner_id

        sk.queue(
            mock,
            impl_token,
            [
                sk.tool_call(sk.SHELL_TOOL, GREP, call_id=f"grep-{uid}"),
                sk.handoff_call(implement, call_id=handed, report="Checked greeting.txt."),
                {"text": "Handed off."},
            ],
        )
        for _ in range(calls):
            release_mock_gate(mock)
        wait(lambda: sk.result_texts(mock, handed) or None, "the handoff's result")
        accepted = any('"accepted": true' in text for text in sk.result_texts(mock, handed))
        # Not a control: Coral stops a step's runner once its close is accepted.
        closed_exit_s = _exit_after(step["runner"])
        after = _runner_log(stack, session_id)[len(during) :]

        # Control: the reviewer ends each turn without a handoff, so after its nudges the
        # run pauses with the reviewer's session open and idle.
        sk.held_activation(wait, mock, review_token, 1)
        sk.queue(mock, review_token, [{"text": "Not done yet."}] * 8)
        reviewer = sk.step_session(stack.client, run_id, "review")
        reviewer_runner = psutil.Process(sk.runner_pid(stack, reviewer))
        release_mock_gate(mock)
        paused = sk.waiter(stack, run_id, deadline, ends_on=sk.FAILED)(
            lambda: _paused(stack, run_id), "the reviewer's pause"
        )
        idle_exit_s = _exit_after(reviewer_runner)
        idle_log = _runner_log(stack, reviewer)
        cancelled = stack.client.post(f"{sk.RUNS}/{run_id}:cancel", json={}).status_code
    window_read = f"idle_timeout={float(idle_s)}s" in during
    idle_exit = idle_exit_s is not None and RUNNER_IDLE in idle_log
    reaped_step = f"{HARNESS_REAPED} {session_id}" in during
    lived = not gone and same_runner and accepted
    lived = lived and RUNNER_IDLE not in during and not reaped_step
    controls = {
        "runner_read_its_window": window_read,
        "idle_sibling_paused_for": [
            paused["pause_reason"],
            *(cause["detail"] for cause in paused["causes"]),
        ],
        "idle_sibling_runner_exit_after_the_pause_s": idle_exit_s,
        "idle_sibling_runner_exit": _messages(idle_log, RUNNER_EXITING),
    }
    if not lived:
        verdict = "fail"
    elif window_read and idle_exit and harness_window == str(idle_s):
        verdict = "pass"
    else:
        verdict = "inconclusive"
    return {
        "spike": 16,
        "verdict": verdict,
        **cli_versions(),
        "held_s": hold_s,
        "runner_idle_timeout_s": idle_s,
        "harness_idle_timeout_s": idle_s,
        "step_processes_gone_during_the_hold_s": gone,
        "same_runner_id": same_runner,
        "model_calls_held": calls,
        "runner_idle_shutdown_during_the_hold": RUNNER_IDLE in during,
        "step_conversation_reaped_during_the_hold": reaped_step,
        "harness_window_configured_not_seen_firing": harness_window,
        "handoff_accepted_after_release": accepted,
        "runner_exit_after_the_accepted_close_s": closed_exit_s,
        "runner_exit_after_the_accepted_close": _messages(after, RUNNER_EXITING),
        "controls": controls,
        "run_cancelled_http": cancelled,
        "rerun": RERUN,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hold-seconds", type=float, default=180.0)
    parser.add_argument("--idle-timeout", type=int, default=60)
    args = parser.parse_args()
    missing = cli_unavailable_reason("claude")
    if missing is not None:
        print(json.dumps({"spike": 16, "verdict": "blocked", "missing": missing, "rerun": RERUN}))
        return
    root = Path(tempfile.mkdtemp(prefix="spike16-"))
    try:
        with contextlib.contextmanager(_mock_llm_server_process)(root) as mock:
            report = _run(root, mock, args.hold_seconds, args.idle_timeout)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
