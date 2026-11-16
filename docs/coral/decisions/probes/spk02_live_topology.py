"""SPK-02 live topology probe: a run anchor and its children on real processes.

A standalone script, not a test: pytest does not collect it, nothing imports
it and no CI job runs it. It starts an isolated local server and a real host
daemon, registers an agent that is never asked to take a turn, and checks the
ADR-05 topology:

1. an anchor created without ``host_id`` gets no runner;
2. two children created with ``host_id`` and a temporary git repo as their
   ``workspace`` each launch a runner of their own; the second child is
   labelled ``omnigent.parent_wake: off``;
3. stopping the anchor leaves both runners connected;
4. stopping the first (unlabelled) child takes down only its runner;
5. an approval raised on each child stays pending past the real 120 s grace,
   and the server log shows a parent-wake attempt for the unlabelled child
   only (the anchor has no runner, so the attempt cannot wake it).

Everything runs in a private temp root: data, database, HOME and the harness
socket root. The processes get a minimal environment with no provider
credentials, and the Claude, Codex and Pi CLI paths point at a stub that exits
at once. The host's boot readiness check can still find a `claude` or
`cursor-agent` installed in a standard directory (see ADR-05). All
traffic stays on loopback. SIGINT, SIGTERM and SIGHUP stop the probe and clean
up as a normal exit does.

It prints one JSON verdict with no paths, user names, ids or tokens (error text
is scrubbed), and exits non-zero unless every check passed. The verdict is tied
to the notifier's two log messages below; if their wording changes the probe
fails rather than passing. Rerun it from the repository root after changes to
the test helpers it borrows; it takes about two and a half minutes:

    uv run --no-sync python docs/coral/decisions/probes/spk02_live_topology.py
"""

from __future__ import annotations

import datetime
import getpass
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

# The probe borrows the test suite's process helpers from this checkout.
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

_AGENT_NAME = "spk02-topology-probe"
_PARENT_WAKE_LABEL = "omnigent.parent_wake"
_GRACE_S = 120.0
_CHECK_COUNT = 9
# A wake to a runner-less parent logs one line per attempt; the notifier stops after three.
_WAKE_ATTEMPT_TEXT = (
    "subagent block notifier: no runner bound for parent {parent}; dropping wake for {child}"
)
_WAKE_GIVEN_UP_TEXT = "notice undelivered after 3 attempt(s) for parent={parent} child={child}"
# Only what the processes need to start; HOME and data dirs come from the helpers.
_KEPT_ENV = ("LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
_STUBBED_CLI_ENV = ("OMNIGENT_CLAUDE_PATH", "OMNIGENT_CODEX_PATH", "OMNIGENT_PI_PATH")
_HEX_ID = re.compile(r"[0-9a-f]{16,}")


class ProbeError(Exception):
    """A step of the probe could not be carried out."""


class ProbeStopped(Exception):
    """A signal asked the probe to stop."""


def _stop_on_signal(signum: int, _frame: object) -> None:
    # Ignore further signals so the cleanup that follows is not cut short.
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_IGN)
    raise ProbeStopped(f"stopped by signal {signum}")


def _short_tmp_parent() -> str | None:
    """Prefer /tmp, as the test suite does, to stay under the AF_UNIX path limit."""
    return "/tmp" if os.access("/tmp", os.W_OK) else None


def _process_env(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return the minimal base environment and the overrides for server and host."""
    git_dir = os.path.dirname(shutil.which("git") or "/usr/bin/git")
    path_dirs = [
        os.path.dirname(sys.executable),
        git_dir,
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    base_env = {name: os.environ[name] for name in _KEPT_ENV if name in os.environ}
    base_env["PATH"] = os.pathsep.join(dict.fromkeys(path_dirs))
    stub = root / "bin" / "no-vendor-cli"
    stub.parent.mkdir()
    stub.write_text("#!/bin/sh\nexit 127\n")
    stub.chmod(0o755)
    harness_root = root / "h"
    harness_root.mkdir()
    overrides = {name: str(stub) for name in _STUBBED_CLI_ENV}
    overrides["OMNIGENT_HARNESS_TMP_PARENT"] = str(harness_root)
    return base_env, overrides


def _git_repo(path: Path) -> Path:
    """Create a one-commit git repo that ignores the user's git configuration."""
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Coral probe",
        "GIT_AUTHOR_EMAIL": "probe@example.invalid",
        "GIT_COMMITTER_NAME": "Coral probe",
        "GIT_COMMITTER_EMAIL": "probe@example.invalid",
    }
    path.mkdir(parents=True)
    (path / "README.md").write_text("SPK-02 topology probe workspace\n")
    for argv in (
        ["init", "-q", "-b", "main"],
        ["add", "README.md"],
        ["commit", "-q", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(path), *argv], check=True, env=env)
    return path


def _agent_yaml(path: Path) -> Path:
    """Write an SDK agent; it is never sent a message, so its model is never called."""
    path.write_text(
        json.dumps(
            {
                "name": _AGENT_NAME,
                "prompt": "Topology probe agent; it never takes a turn.",
                "executor": {
                    "harness": "openai-agents",
                    "model": "mock-topology-probe",
                    "profile": "",
                    "auth": {
                        "type": "api_key",
                        "api_key": "probe-placeholder",
                        "base_url": "http://127.0.0.1:9/v1",
                    },
                },
            }
        )
    )
    return path


def _create(client: httpx.Client, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/v1/sessions", json=payload)
    if response.status_code != 201:
        raise ProbeError(f"session create returned HTTP {response.status_code}")
    return response.json()


def _post_event(client: httpx.Client, session_id: str, event: dict[str, Any]) -> httpx.Response:
    return client.post(f"/v1/sessions/{session_id}/events", json=event)


def _online(client: httpx.Client, runner_id: str) -> bool:
    response = client.get(f"/v1/runners/{runner_id}/status")
    return response.status_code == 200 and response.json().get("online") is True


def _bound_runner(client: httpx.Client, session_id: str) -> str | None:
    return client.get(f"/v1/sessions/{session_id}").json().get("runner_id")


def _pending(client: httpx.Client, session_id: str, elicitation_id: str) -> bool:
    response = client.get(f"/v1/sessions/{session_id}/elicitations/{elicitation_id}")
    return response.status_code == 200 and response.json().get("status") == "pending"


def _wake_lines(log_path: Path, parent: str, child: str) -> tuple[int, bool]:
    text = log_path.read_text(errors="replace") if log_path.exists() else ""
    attempts = text.count(_WAKE_ATTEMPT_TEXT.format(parent=parent, child=child))
    return attempts, _WAKE_GIVEN_UP_TEXT.format(parent=parent, child=child) in text


def _first_wake_attempt_after(log_path: Path, parent: str, child: str, armed_by: float) -> float:
    """Wait for the first wake attempt; return a lower bound on its delay after the block.

    The last check that found no attempt bounds the attempt's time from below, and
    ``armed_by`` (taken after the block POST returned) bounds the block's from above.
    """
    deadline = armed_by + _GRACE_S + 60.0
    not_seen_at = armed_by
    while time.monotonic() < deadline:
        checked_at = time.monotonic()
        if _wake_lines(log_path, parent, child)[0]:
            return not_seen_at - armed_by
        not_seen_at = checked_at
        time.sleep(0.1)
    raise ProbeError("no wake attempt was logged for the unlabelled child")


def _probe(
    client: httpx.Client,
    host_id: str,
    workspace: str,
    server_log: Path,
    checks: dict[str, bool],
    observed: dict[str, Any],
) -> None:
    from tests._helpers.polling import poll_until

    agents = client.get("/v1/agents", params={"limit": 100}).json()["data"]
    agent_id = next(agent["id"] for agent in agents if agent["name"] == _AGENT_NAME)

    anchor = _create(client, {"agent_id": agent_id, "title": "run anchor"})
    checks["anchor_has_no_host_or_runner"] = (
        anchor["host_id"] is None and anchor["runner_id"] is None
    )
    step = {
        "agent_id": agent_id,
        "parent_session_id": anchor["id"],
        "host_id": host_id,
        "workspace": workspace,
    }
    unlabelled = _create(client, {**step, "title": "step 1"})
    labelled = _create(client, {**step, "title": "step 2", "labels": {_PARENT_WAKE_LABEL: "off"}})
    children = (unlabelled, labelled)
    runners = [child["runner_id"] for child in children]
    checks["children_own_distinct_runners"] = (
        all(str(runner).startswith("runner_token_") for runner in runners)
        and runners[0] != runners[1]
        and all(child["parent_session_id"] == anchor["id"] for child in children)
    )
    stored_labels = client.get(f"/v1/sessions/{labelled['id']}/labels").json()["labels"]
    checks["label_persisted"] = stored_labels.get(_PARENT_WAKE_LABEL) == "off"

    poll_until(lambda: all(_online(client, runner) for runner in runners), timeout_s=120.0)
    checks["both_runners_connected"] = True

    anchor_stop = _post_event(client, anchor["id"], {"type": "stop_session"})
    observed["anchor_stop_status"] = anchor_stop.status_code
    # Nothing should change, so watch a fixed window instead of waiting for a change.
    time.sleep(5.0)
    checks["anchor_stop_keeps_both_runners"] = (
        anchor_stop.status_code == 202
        and all(_online(client, runner) for runner in runners)
        and [_bound_runner(client, child["id"]) for child in children] == runners
    )

    child_stop = _post_event(client, unlabelled["id"], {"type": "stop_session"})
    observed["child_stop_status"] = child_stop.status_code
    poll_until(lambda: not _online(client, runners[0]), timeout_s=60.0)
    checks["child_stop_stops_only_its_runner"] = (
        child_stop.status_code == 202
        and _online(client, runners[1])
        and _bound_runner(client, labelled["id"]) == runners[1]
    )

    # The labelled child blocks first, so its grace ends before the unlabelled one's.
    block = {"type": "mcp_elicitation", "data": {"message": "Run git push?"}}
    labelled_blocked_at = time.monotonic()
    block_responses = [_post_event(client, child["id"], block) for child in children[::-1]]
    unlabelled_blocked_by = time.monotonic()
    observed["block_status"] = [response.status_code for response in block_responses]
    blocks = [
        (child["id"], response.json().get("elicitation_id", ""))
        for child, response in zip(children[::-1], block_responses, strict=True)
    ]
    pending_at_block = all(_pending(client, *pair) for pair in blocks)
    observed["unlabelled_first_wake_attempt_after_s"] = round(
        _first_wake_attempt_after(
            server_log, anchor["id"], unlabelled["id"], unlabelled_blocked_by
        ),
        1,
    )
    poll_until(
        lambda: _wake_lines(server_log, anchor["id"], unlabelled["id"])[1],
        timeout_s=30.0,
        interval_s=0.5,
    )
    # A few seconds more for the labelled child's handler, whose grace ended first.
    time.sleep(5.0)
    observed["labelled_block_age_at_check_s"] = round(time.monotonic() - labelled_blocked_at, 1)
    checks["both_blocks_pending_through_grace"] = pending_at_block and all(
        _pending(client, *pair) for pair in blocks
    )
    unlabelled_attempts, _ = _wake_lines(server_log, anchor["id"], unlabelled["id"])
    labelled_attempts, labelled_gave_up = _wake_lines(server_log, anchor["id"], labelled["id"])
    log_text = server_log.read_text(errors="replace")
    labelled_mentions = sum(
        1 for line in log_text.splitlines() if "subagent block" in line and labelled["id"] in line
    )
    observed["wake_attempts"] = {"unlabelled": unlabelled_attempts, "labelled": labelled_attempts}
    # The lower bound sits within one 0.1 s check of the true delay.
    checks["unlabelled_child_wake_attempted_after_grace"] = (
        unlabelled_attempts == 3
        and observed["unlabelled_first_wake_attempt_after_s"] >= _GRACE_S - 1.0
    )
    checks["labelled_child_wake_never_attempted"] = (
        labelled_attempts == 0
        and not labelled_gave_up
        and labelled_mentions == 0
        and observed["labelled_block_age_at_check_s"] > _GRACE_S
    )

    # Leave no runner behind; the host's own shutdown is the backstop.
    _post_event(client, labelled["id"], {"type": "stop_session"})


def _scrub(text: str, root: Path | None) -> str:
    """Drop machine paths, the user name and session, runner or host ids from a message."""
    replacements = [
        (str(_REPO_ROOT), "<repo>"),
        (str(Path.home()), "~"),
        (getpass.getuser(), "<user>"),
    ]
    if root is not None:
        replacements[:0] = [(str(root.resolve()), "<tmp>"), (str(root), "<tmp>")]
    for value, placeholder in replacements:
        text = text.replace(value, placeholder)
    text = _HEX_ID.sub("<id>", text)
    return text.splitlines()[0][:240] if text else ""


def _base_commit() -> tuple[str, bool]:
    def git(*argv: str) -> str:
        return subprocess.run(
            ["git", "-C", str(_REPO_ROOT), *argv], capture_output=True, text=True, check=False
        ).stdout.strip()

    return git("rev-parse", "--short", "HEAD"), bool(git("status", "--porcelain"))


def main() -> int:
    if len(sys.argv) > 1:
        print(__doc__)
        return 0 if sys.argv[1] in ("-h", "--help") else 2
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop_on_signal)

    from omnigent.runner.identity import OMNIGENT_INTERNAL_WS_ORIGIN
    from tests._helpers.host import isolated_host
    from tests._helpers.live_server import isolated_local_server

    checks: dict[str, bool] = {}
    observed: dict[str, Any] = {}
    error: str | None = None
    started = time.monotonic()
    root: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="spk02-", dir=_short_tmp_parent()) as tmp:
            root = Path(tmp)
            server_log = root / "server" / "process.log"
            base_env, overrides = _process_env(root)
            workspace = _git_repo(root / "repo")
            agent = _agent_yaml(root / "agent.yaml")
            with (
                isolated_local_server(
                    root / "server",
                    extra_args=["--agent", str(agent)],
                    env={**overrides, "OMNIGENT_PROCESS_LOG_FILE": str(server_log)},
                    base_env=base_env,
                ) as base_url,
                httpx.Client(
                    base_url=base_url,
                    trust_env=False,
                    timeout=60.0,
                    headers={"Origin": OMNIGENT_INTERNAL_WS_ORIGIN},
                ) as client,
                isolated_host(root / "host", base_url, env=overrides, base_env=base_env) as host,
            ):
                host.wait_online(client, timeout=90.0)
                _probe(client, host.host_id, str(workspace), server_log, checks, observed)
    except Exception as exc:  # noqa: BLE001 - every failure becomes the verdict
        error = f"{type(exc).__name__}: {_scrub(str(exc), root)}"
    commit, dirty = _base_commit()
    passed = error is None and len(checks) == _CHECK_COUNT and all(checks.values())
    verdict = {
        "probe": "spk02_live_topology",
        "verdict": "pass" if passed else "fail",
        "date": datetime.datetime.now(datetime.UTC).date().isoformat(),
        "base_commit": commit,
        "base_commit_dirty": dirty,
        "platform": platform.system(),
        "python": platform.python_version(),
        "grace_s": _GRACE_S,
        "checks": checks,
        "observed": observed,
        "duration_s": round(time.monotonic() - started, 1),
        "error": error,
    }
    print(json.dumps(verdict, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
