"""Mechanics for the walking-skeleton E2E: a Coral server, a real host, runners and the CLI.

The stack is a subprocess server with the Coral plugin, a host daemon that launches each
step's runner, and the real ``claude`` CLI, whose model calls go only to the test's mock
gateway. Its update checks and telemetry are not turned off yet: the host strips the
variables that would, before they reach the CLI (step 3b, R62). Callers pass the
scripts, tokens, deadlines and faults, and keep every assertion.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import httpx
import psutil
import yaml

from omnigent.testing.process_reaper import _cmdline_references_dir, _is_pytest_process
from tests._helpers.host import Host, isolated_host
from tests._helpers.polling import poll_until
from tests._helpers.server_runner import ServerRunner, server_runner
from tests.e2e._harness_probes import cli_unavailable_reason, skip_if_harness_cli_missing
from tests.e2e.coral.conftest import CORAL_TIER_B_HARNESS

HANDOFF_TOOL = "mcp__omnigent__coral_submit_handoff"
SHELL_TOOL = "mcp__omnigent__sys_os_shell"
WRITE_TOOL = "mcp__omnigent__sys_os_write"
RUNS = "/v1/coral/runs"
RUN_ID_LABEL = "coral.run_id"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
_ACTIVATION_LINE = re.compile(r"^Activation id: (\S+)$", re.MULTILINE)
_BRIEF_OPENING = "Coral step brief."
# Kept from the test's environment; HOME and data dirs come from the helpers. TMPDIR is
# not: the CLI keeps its temp root under /tmp whatever TMPDIR says, while the runner
# grants the sandboxed CLI <tempdir>/claude-<uid>, so the two agree only on /tmp.
_KEPT_ENV = ("LANG", "LC_ALL", "LC_CTYPE")
# Appends the stack's config file to the server command line before the CLI parses it.
_SERVER_BOOTSTRAP = """
import os
import sys
sys.argv.extend(["--config", os.environ["CORAL_E2E_SERVER_CONFIG"]])
from omnigent.cli import main
main()
"""
_LOG_TAIL_CHARS = 3000
# Set by the coral-e2e lane, where a CLI that installed but does not run must fail, not skip.
REQUIRE_CLI_ENV = "CORAL_E2E_REQUIRE_CLI"
_STOPPED = frozenset({"paused", "failed", "cancelled"})
_T = TypeVar("_T")


@dataclass
class Skeleton:
    """One running stack; ``harness_tmp`` is the host's private harness socket root."""

    root: Path
    server: ServerRunner
    host: Host
    client: httpx.Client
    repo: Path
    harness_tmp: Path

    def log_tails(self) -> str:
        """The end of every log under the stack root, for failure messages."""
        tails = []
        for path in sorted(self.root.rglob("*.log")):
            with contextlib.suppress(OSError):
                text = path.read_text(errors="replace")[-_LOG_TAIL_CHARS:]
                tails.append(f"--- {path.relative_to(self.root)}\n{text}")
        return "\n".join(tails)


def require_claude_cli() -> None:
    """Skip without a runnable ``claude`` CLI, or fail where the lane requires one."""
    if os.environ.get(REQUIRE_CLI_ENV) == "1":
        reason = cli_unavailable_reason("claude")
        assert reason is None, reason
    skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)


def minimal_env() -> dict[str, str]:
    """
    The environment every stack process starts from: no credential, no ambient CLI setup.

    The two CLI switches reach the server, the host and its zygote only; the host's
    runner allowlist drops them before the CLI starts (step 3b, R62).
    """
    path_dirs = [os.path.dirname(sys.executable)]
    # An npm-installed claude is a node script.
    for binary in ("git", "claude", "node"):
        found = shutil.which(binary)
        if found is not None:
            path_dirs.append(os.path.dirname(found))
    path_dirs += ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    env = {name: os.environ[name] for name in _KEPT_ENV if name in os.environ}
    env.update(
        PATH=os.pathsep.join(dict.fromkeys(path_dirs)),
        DISABLE_AUTOUPDATER="1",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
    )
    return env


def write_server_config(path: Path, *, mock_url: str) -> Path:
    """A server config with the Coral plugin whose own model calls reach only the mock."""
    config = {
        "server_plugins": ["coral.server_plugin"],
        "llm": {
            "model": "_policy_llm_",
            "connection": {"base_url": f"{mock_url}/v1", "api_key": "mock-key"},
        },
    }
    path.write_text(yaml.safe_dump(config, sort_keys=True))
    return path


def make_repo(path: Path) -> Path:
    """A one-commit git repository that ignores the user's git configuration."""
    env = {
        **minimal_env(),
        "HOME": str(path.parent),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Coral E2E",
        "GIT_AUTHOR_EMAIL": "e2e@example.invalid",
        "GIT_COMMITTER_NAME": "Coral E2E",
        "GIT_COMMITTER_EMAIL": "e2e@example.invalid",
    }
    path.mkdir(parents=True)
    (path / "README.md").write_text("Coral walking skeleton\n")
    for argv in (
        ["init", "-q", "-b", "main"],
        # Set, a runner skips its untracked-cache probe, whose scratch directory would
        # otherwise sit in the worktree while a fast scripted turn ends.
        ["config", "core.untrackedCache", "true"],
        ["add", "README.md"],
        ["commit", "-q", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(path), *argv], check=True, env=env, capture_output=True)
    return path


def _under(path: str, needles: tuple[str, ...]) -> bool:
    return any(path == needle or path.startswith(needle + os.sep) for needle in needles)


def _argv(proc: psutil.Process) -> list[str]:
    try:
        return proc.cmdline()
    except (psutil.Error, OSError):
        return []


def _omnigent_processes(needles: tuple[str, ...]) -> list[psutil.Process]:
    """Live Omnigent processes whose cwd, home or command line names one of ``needles``."""
    found = []
    for proc in psutil.process_iter():
        argv = _argv(proc)
        if proc.pid == os.getpid() or "omnigent" not in " ".join(argv):
            continue
        if _is_pytest_process(argv):
            continue
        try:
            cwd = proc.cwd()
            environ = proc.environ()
        except (psutil.Error, OSError):
            continue
        homes = (environ.get("HOME", ""), environ.get("OMNIGENT_DATA_DIR", ""))
        if (
            _under(cwd, needles)
            or any(_under(home, needles) for home in homes)
            or any(_cmdline_references_dir(argv, needle) for needle in needles)
        ):
            found.append(proc)
    return found


class _StackProcesses:
    """
    What a stack started: its daemons' descendants, taken just before they stop, and
    every Omnigent process whose cwd, home or command line names its directories.

    Only those are signalled, so a shell or a ``tail`` in the stack root is left alone.
    """

    def __init__(self, scopes: tuple[Path, ...]) -> None:
        # Both spellings: macOS resolves /tmp to /private/tmp, argv keeps the one given.
        spellings = (
            str(path).rstrip(os.sep) for scope in scopes for path in (scope, scope.resolve())
        )
        self._needles = tuple(dict.fromkeys(spellings))
        self._descendants: dict[int, psutil.Process] = {}

    def remember(self, *pids: int | None) -> None:
        """Note the live descendants of each daemon before it is asked to stop."""
        for pid in pids:
            if pid is None:
                continue
            with contextlib.suppress(psutil.Error):
                for child in psutil.Process(pid).children(recursive=True):
                    self._descendants[child.pid] = child

    def reap(self) -> None:
        """Stop what outlived the stack's owners, as the suite's reaper does; fail on survivors."""
        leaked = {pid: proc for pid, proc in self._descendants.items() if proc.is_running()}
        for proc in _omnigent_processes(self._needles):
            leaked.setdefault(proc.pid, proc)
        for proc in leaked.values():
            with contextlib.suppress(psutil.Error):
                proc.terminate()
        _, alive = psutil.wait_procs(list(leaked.values()), timeout=10)
        for proc in alive:
            with contextlib.suppress(psutil.Error):
                proc.kill()
        _, survivors = psutil.wait_procs(alive, timeout=5)
        names = [" ".join(_argv(proc))[:200] for proc in survivors]
        assert not names, f"Stack processes survived teardown: {names}"


@contextmanager
def _sigterm_unwinds() -> Iterator[None]:
    """Let a SIGTERM to the test unwind like Ctrl-C, so the stack's teardown still runs."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def interrupt(signum: int, _frame: object) -> None:
        # One unwind only: a second SIGTERM must not cut the teardown short.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt(f"signal {signum}")

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous if previous is not None else signal.SIG_DFL)


@contextmanager
def skeleton_stack(
    root: Path,
    *,
    mock_url: str,
    host_config: Mapping[str, Any],
    host_env: Mapping[str, str | None] | None = None,
    health_timeout: float = 60.0,
) -> Iterator[Skeleton]:
    """
    Start a Coral server and a host for one test, and tear both down with every process.

    The server runs without the allow-listed runner token, so host-launched runners
    connect with their own. At exit, a SIGTERM included, no process the stack started
    may survive.
    """
    root.mkdir(parents=True, exist_ok=True)
    # Under /tmp to stay within the AF_UNIX path limit for harness sockets.
    harness_tmp = Path(tempfile.mkdtemp(dir="/tmp", prefix="crl-"))
    config = write_server_config(root / "server.yaml", mock_url=mock_url)
    base_env = minimal_env()
    processes = _StackProcesses((root, harness_tmp))
    with ExitStack() as resources:
        resources.enter_context(_sigterm_unwinds())
        resources.callback(shutil.rmtree, harness_tmp, ignore_errors=True)
        resources.callback(processes.reap)
        server = resources.enter_context(
            server_runner(
                root,
                server_bootstrap=_SERVER_BOOTSTRAP,
                server_env={
                    "OMNIGENT_RUNNER_TUNNEL_TOKEN": None,
                    "CORAL_E2E_SERVER_CONFIG": str(config),
                },
                base_env=base_env,
                health_timeout=health_timeout,
                poll_interval=0.25,
            )
        )
        client = resources.enter_context(
            httpx.Client(base_url=server.base_url, trust_env=False, timeout=30.0)
        )
        host = resources.enter_context(
            isolated_host(
                root / "host",
                server.base_url,
                base_env=base_env,
                env={**(host_env or {}), "OMNIGENT_HARNESS_TMP_PARENT": str(harness_tmp)},
                config=host_config,
            )
        )
        # Runs first at exit, while the daemons still hold their children.
        resources.callback(
            lambda: processes.remember(
                host.proc.pid, None if server.server is None else server.server.pid
            )
        )
        host.wait_online(client, timeout=health_timeout, poll_interval=0.25)
        info = client.get("/v1/coral/info")
        assert info.status_code == 200, info.text
        repo = make_repo(root / "repo")
        yield Skeleton(root, server, host, client, repo, harness_tmp)


class _ProbeError(Exception):
    """A probe's own failure, kept apart from the wait's timeout."""


def wait_for(
    probe: Callable[[], _T | None],
    *,
    deadline: float,
    what: str,
    skeleton: Skeleton,
    run_id: str | None = None,
    poll_interval: float = 0.5,
) -> _T:
    """
    Poll until ``probe`` returns a value other than ``None``, up to an absolute monotonic deadline.

    With ``run_id``, a run that pauses, fails or is cancelled while the probe has nothing
    ends the wait at once. Either failure carries the run's detail, ``claude --version``
    and the stack's log tails; a probe's own assertion is raised as it is.
    """
    found: list[_T] = []
    stopped: list[str] = []

    def holds() -> bool:
        try:
            value = probe()
            run = None if value is not None or run_id is None else detail(skeleton.client, run_id)
        except AssertionError as error:
            raise _ProbeError from error
        if value is not None:
            found.append(value)
            return True
        if run is not None and run["status"] in _STOPPED:
            stopped.append(f"{run['status']} ({run['pause_reason']}): {run['causes']}")
            return True
        return False

    try:
        poll_until(
            holds, timeout_s=max(0.0, deadline - time.monotonic()), interval_s=poll_interval
        )
    except _ProbeError as error:
        cause = error.__cause__
        assert cause is not None
        raise cause from None
    except AssertionError:
        raise AssertionError(
            _diagnosis(f"Timed out waiting for {what}.", skeleton, run_id)
        ) from None
    if stopped:
        headline = f"The run stopped while waiting for {what}: {stopped[0]}"
        raise AssertionError(_diagnosis(headline, skeleton, run_id))
    return found[-1]


def _diagnosis(headline: str, skeleton: Skeleton, run_id: str | None) -> str:
    details = [headline]
    if run_id is not None:
        with contextlib.suppress(httpx.HTTPError):
            run = skeleton.client.get(f"{RUNS}/{run_id}").text
            details.append(f"Run detail: {run[:6000]}")
    details.append(f"claude --version: {claude_version()}")
    details.append(skeleton.log_tails())
    return "\n".join(details)


def claude_version() -> str:
    """The CLI's own version line, or why it could not be read."""
    try:
        done = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"unavailable ({type(error).__name__})"
    return done.stdout.strip() or f"exit {done.returncode}"


def review_loop_yaml(*, impl_token: str, review_token: str) -> str:
    """The review-loop workflow with each step's routing token in its goal."""
    text = (FIXTURES / "review_loop.yaml").read_text()
    return text.replace("{impl_token}", impl_token).replace("{review_token}", review_token)


def save_workflow(client: httpx.Client, yaml_text: str) -> str:
    """Store a workflow; return its id."""
    response = client.post("/v1/coral/workflows", json={"yaml": yaml_text})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["runnable"] is True, saved["problems"]
    return saved["id"]


def start_run(
    client: httpx.Client, *, workflow_id: str, host_id: str, repo: Path, start_key: str
) -> dict[str, Any]:
    """Start a run of the workflow on the host's repository; return its summary."""
    response = client.post(
        RUNS,
        json={
            "workflow_id": workflow_id,
            "start_key": start_key,
            "host_id": host_id,
            "repo_path": str(repo),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def detail(client: httpx.Client, run_id: str) -> dict[str, Any]:
    response = client.get(f"{RUNS}/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


def coral_sessions(client: httpx.Client, run_id: str) -> list[dict[str, Any]]:
    """Every session labelled with the run, read in full; the list route has no label filter."""
    listed = client.get("/v1/sessions", params={"kind": "any", "visibility": "all", "limit": 1000})
    assert listed.status_code == 200, listed.text
    sessions = []
    for item in listed.json()["data"]:
        session = client.get(f"/v1/sessions/{item['id']}")
        assert session.status_code == 200, session.text
        body = session.json()
        if (body.get("labels") or {}).get(RUN_ID_LABEL) == run_id:
            sessions.append(body)
    return sessions


def _user_texts(request: Mapping[str, Any]) -> list[str]:
    texts = []
    for message in request["body"].get("messages") or []:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        blocks = [content] if isinstance(content, str) else content or []
        for block in blocks:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
    return texts


def agent_requests(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The step sessions' own model calls: those offering the handoff tool, not side requests."""
    return [
        request
        for request in ledger
        if any(tool.get("name") == HANDOFF_TOOL for tool in request["body"].get("tools") or [])
    ]


def briefs(ledger: list[dict[str, Any]]) -> list[str]:
    """The first brief the step sessions' model calls carried for each activation, in order."""
    found: dict[str, str] = {}
    for request in agent_requests(ledger):
        for text in _user_texts(request):
            start = text.find(_BRIEF_OPENING)
            if start >= 0:
                found.setdefault(activation_from_brief(text[start:]), text[start:])
    return list(found.values())


def mock_holds_a_call(mock_url: str) -> bool:
    """Whether a ``block`` response of the mock is waiting for its release."""
    response = httpx.get(f"{mock_url}/gate/pending", timeout=5.0)
    response.raise_for_status()
    return bool(response.json()["pending"])


def activation_from_brief(brief: str) -> str:
    match = _ACTIVATION_LINE.search(brief)
    assert match is not None, brief[:500]
    return match.group(1)


def tool_call(name: str, arguments: Mapping[str, Any], *, call_id: str) -> dict[str, Any]:
    """A mock response entry that calls one tool."""
    return {"tool_calls": [{"call_id": call_id, "name": name, "arguments": json.dumps(arguments)}]}


def handoff_call(
    activation_id: str,
    *,
    call_id: str,
    report: str,
    status: str = "done",
    label: str | None = None,
) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "activation_id": activation_id,
        "status": status,
        "report": report,
    }
    if label is not None:
        arguments["label"] = label
    return tool_call(HANDOFF_TOOL, arguments, call_id=call_id)
