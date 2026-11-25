"""Mechanics for the walking-skeleton E2E: a Coral server, a real host, runners and the CLI.

The stack is a subprocess server with the Coral plugin, a host daemon that launches each
step's runner, and the real ``claude`` CLI, whose model calls go only to the test's mock
gateway, with its self-update and non-essential traffic off. Callers pass the scripts,
tokens, deadlines and faults, and keep every assertion.
"""

from __future__ import annotations

import contextlib
import functools
import itertools
import json
import os
import re
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import httpx
import psutil
import pytest
import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from coral.db.models.sessions import SessionBindingRow
from coral.db.models.work import WorkerLeaseRow, WorkRow
from omnigent.cli_auth import _normalize_server_url
from omnigent.runtime.harnesses.paths import resolve_harness_tmp_parent
from omnigent.testing.process_reaper import _cmdline_references_dir, _is_pytest_process
from tests._helpers.host import Host, isolated_host
from tests._helpers.live_server import terminate_process
from tests._helpers.polling import poll_until
from tests._helpers.server_runner import ServerRunner, server_runner
from tests.e2e.conftest import configure_mock_llm, get_mock_message_requests
from tests.e2e.coral._claude_sdk_kit import (
    KeychainStubs,
    install_keychain_stubs,
    throwaway_cli_env,
    tool_results,
)
from tests.e2e.coral._live_proxy import Secret
from tests.e2e.coral.conftest import CORAL_TIER_B_HARNESS

HANDOFF_TOOL = "mcp__omnigent__coral_submit_handoff"
CHOOSE_TOOL = "mcp__omnigent__coral_choose_arrow"
SHELL_TOOL = "mcp__omnigent__sys_os_shell"
TOOL_SEARCH = "ToolSearch"
WRITE_TOOL = "mcp__omnigent__sys_os_write"
RUNS = "/v1/coral/runs"
RUN_ID_LABEL = "coral.run_id"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
_ACTIVATION_LINE = re.compile(r"^Activation id: (\S+)$", re.MULTILINE)
_DECISION_LINE = re.compile(r"^Decision id: (\S+)$", re.MULTILINE)
# The host's line for each runner it launches.
_LAUNCHED_RUNNER = re.compile(
    r"Launched runner (\S+) for workspace (.+) \(pid=(\d+)\)$", re.MULTILINE
)
_BRIEF_OPENING = "Coral step brief."
# Kept from the test's environment; HOME and data dirs come from the helpers.
_KEPT_ENV = ("LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
# Every name a stack daemon's base environment may hold, each reviewed: none carries a
# credential or points a tool at the developer's own (a token, an agent socket, a config dir).
BASE_ENV_NAMES = frozenset(
    {
        *("LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "PATH"),
        *("DISABLE_AUTOUPDATER", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"),
        *("GH_CONFIG_DIR", "GIT_CONFIG_GLOBAL", "GIT_TERMINAL_PROMPT"),
    }
)
# Where a stack's processes have their homes, and what a login would leave in one: the macOS
# login keychain's directory, and gh's stored hosts (also under the stack's GH_CONFIG_DIR).
_STACK_HOMES = ("host/home", "server-home", "home")
_LOGIN_TRACES = ("Library/Keychains", ".config/gh/hosts.yml")
# The most call names one summary of the stand-ins' log shows.
_SUMMARY_NAMES = 20
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
# A wait bound to a run ends at once when the run reaches one of these.
STOPPED = frozenset({"paused", "failed", "cancelled"})
# For a wait that goes on while the run is paused.
FAILED = frozenset({"failed", "cancelled"})
_T = TypeVar("_T")
Wait = Callable[[Callable[[], Any], str], Any]
# The first admin of a stack that requires identity; the host signs in with its stored JWT.
IDENTITY_OWNER = "coral-e2e-owner"


@dataclass(frozen=True)
class HostLaunch:
    """How the stack's host daemon was started, so it can be started again the same way."""

    argv: tuple[str, ...]
    env: dict[str, str] = field(repr=False)
    cwd: str


@dataclass
class Skeleton:
    """
    One running stack; ``harness_tmp`` is the host's private harness socket root, and
    ``stubs`` the keychain stand-ins first on every stack process's ``PATH``.

    Without ``failure_log_tails``, as against a real model, failures carry no log text.
    ``respawned`` holds the hosts :func:`respawn_host` started; ``host`` is the newest.
    """

    root: Path
    server: ServerRunner
    host: Host
    client: httpx.Client
    repo: Path
    harness_tmp: Path
    host_launch: HostLaunch
    stubs: KeychainStubs
    failure_log_tails: bool = True
    respawned: list[Host] = field(default_factory=list)
    # The owner's JWT on a stack that requires identity; the client already sends it.
    owner_token: Secret | None = None

    def log_tails(self) -> str:
        """The end of every log under the stack root, for failure messages."""
        tails = []
        for path in sorted(self.root.rglob("*.log")):
            with contextlib.suppress(OSError):
                text = path.read_text(errors="replace")[-_LOG_TAIL_CHARS:]
                tails.append(f"--- {path.relative_to(self.root)}\n{text}")
        return "\n".join(tails)


class _SecretEnv(Mapping[str, str | None]):
    """Environment overrides whose repr names the keys only; secret values stay :class:`Secret`."""

    def __init__(self, values: Mapping[str, str | Secret | None]) -> None:
        self._values = dict(values)

    def __getitem__(self, name: str) -> str | None:
        value = self._values[name]
        return value.reveal() if isinstance(value, Secret) else value

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"_SecretEnv({sorted(self._values)})"


def _accounts_env(root: Path, password: Secret) -> dict[str, str | Secret | None]:
    """A server that signs users in with accounts: a throwaway cookie secret and first admin."""
    return {
        "OMNIGENT_AUTH_PROVIDER": "accounts",
        "OMNIGENT_LOCAL_SINGLE_USER": None,
        "OMNIGENT_ACCOUNTS_COOKIE_SECRET": Secret(secrets.token_hex(32)),
        "OMNIGENT_ACCOUNTS_INIT_ADMIN_USERNAME": IDENTITY_OWNER,
        "OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD": password,
        "OMNIGENT_ACCOUNTS_AUTO_OPEN": "0",
        "OMNIGENT_ADMIN_CREDENTIALS_PATH": str(root / "admin-credentials"),
    }


def _owner_login(base_url: str, password: Secret) -> Secret:
    """
    The owner's JWT from the password sign-in. A failure shows only its status code or error
    type: the frames below, which hold the password or the answer, are dropped.
    """
    try:
        response = httpx.post(
            f"{base_url}/auth/login",
            json={"username": IDENTITY_OWNER, "password": password.reveal()},
            timeout=30,
            trust_env=False,
        )
        token = Secret(response.json()["token"]) if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError, LookupError, TypeError) as error:
        raise AssertionError(f"login: {type(error).__name__}") from None
    assert token is not None, f"login: HTTP {response.status_code}"
    return token


def _store_owner_login(home: Path, base_url: str, token: Secret) -> None:
    """
    The host's stored credentials as ``omnigent login`` leaves them, owner-only and new. A
    failed write shows its error type only: the frames below hold the JWT.
    """
    directory = home / ".omnigent"
    try:
        for path in (*reversed(directory.parents), directory):
            if not path.exists():
                path.mkdir(mode=0o700)
        descriptor = os.open(
            directory / "auth_tokens.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w") as stored:
            json.dump(
                {
                    _normalize_server_url(base_url): {
                        "token": token.reveal(),
                        "user_id": IDENTITY_OWNER,
                        "expires_at": time.time() + 3600,
                    }
                },
                stored,
            )
    except OSError as error:
        raise AssertionError(f"storing the owner's sign-in: {type(error).__name__}") from None


@functools.cache
def _claude_cli() -> tuple[str | None, str]:
    """
    Why the ``claude`` CLI cannot run here, if it cannot, and its version line: from one
    ``--version`` a session. The pytest process never starts the CLI with its own
    environment: the child gets :func:`minimal_env`, a throwaway home and config dir, and
    keychain stand-ins first on its ``PATH``.
    """
    found = shutil.which("claude")
    if found is None:
        return "'claude' CLI is not on PATH", "unavailable (not on PATH)"
    with throwaway_cli_env(minimal_env()) as env:
        try:
            done = subprocess.run(
                [found, "--version"],
                env=env,
                cwd=env["HOME"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            kind = type(error).__name__
            return f"'claude' CLI at {found!r} is not runnable: {kind}", f"unavailable ({kind})"
    version = done.stdout.strip() or f"exit {done.returncode}"
    if done.returncode == 0:
        return None, version
    detail = (done.stderr or done.stdout).strip().splitlines()
    suffix = f": {detail[0][:200]}" if detail else ""
    return f"'claude' CLI at {found!r} exits {done.returncode}{suffix}", version


def require_claude_cli() -> None:
    """Skip without a runnable ``claude`` CLI, or fail where the lane requires one."""
    problem, _version = _claude_cli()
    if os.environ.get(REQUIRE_CLI_ENV) == "1":
        assert problem is None, problem
    if problem is not None:
        pytest.skip(
            f"{CORAL_TIER_B_HARNESS!r} harness requires a runnable 'claude' CLI; {problem}"
        )


def minimal_env() -> dict[str, str]:
    """
    What the test's own ``git``, ``sh`` and probe children start from: no credential, no
    ambient CLI setup. A stack's processes start from :func:`stack_env`, which puts the
    stack's keychain stand-ins in front of this ``PATH``.

    The two switches turn off the CLI's self-update and non-essential traffic; the host
    forwards them to every step's CLI.
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


def stack_env(root: Path, stubs: KeychainStubs, tmp: Path) -> dict[str, str]:
    """
    The base environment of a stack's server and host, whose every name is in
    :data:`BASE_ENV_NAMES`: :func:`minimal_env` with the stack's own temp dir and the stack's
    keychain stand-ins first on ``PATH``, so a ``security`` or ``gh`` found through ``PATH``
    is never the real one. ``gh`` and ``git`` are pointed at a login and a global config
    under ``root``, where neither exists, and ``git`` may not prompt.

    A program that runs ``/usr/bin/security`` by its full path, or asks the keychain
    in-process, meets no stand-in: for those the barrier is the throwaway ``HOME`` the
    helpers add.
    """
    env = stubs.first_on(
        {
            **minimal_env(),
            "TMPDIR": str(tmp),
            "GH_CONFIG_DIR": str(root / "gh"),
            "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    unreviewed = sorted(set(env) - BASE_ENV_NAMES)
    if unreviewed:
        # A report with locals must show no value of a name that should not be here.
        del env
        raise AssertionError(f"unreviewed names in a stack's base environment: {unreviewed}")
    return env


def write_server_config(
    path: Path,
    *,
    mock_url: str | None,
    lease_s: int | None = None,
    grace_s: int | None = None,
) -> Path:
    """
    A server config with the Coral plugin whose own model calls reach only the mock.

    Without ``mock_url`` the server has no model of its own. A lease or grace left
    out keeps the production default.
    """
    config: dict[str, Any] = {"server_plugins": ["coral.server_plugin"]}
    if mock_url is not None:
        config["llm"] = {
            "model": "_policy_llm_",
            "connection": {"base_url": f"{mock_url}/v1", "api_key": "mock-key"},
        }
    if lease_s is not None:
        config["coral_worker_lease_seconds"] = lease_s
    if grace_s is not None:
        config["coral_runner_reconnect_grace_s"] = grace_s
    path.write_text(yaml.safe_dump(config, sort_keys=True))
    return path


def make_repo(path: Path, files: Mapping[str, bytes] | None = None) -> Path:
    """
    A one-commit git repository that ignores the user's git configuration; ``files``
    join the README in that commit.
    """
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
    for name, data in (files or {}).items():
        (path / name).write_bytes(data)
    for argv in (
        ["init", "-q", "-b", "main"],
        # Set, a runner skips its untracked-cache probe, whose scratch directory would
        # otherwise sit in the worktree while a fast scripted turn ends.
        ["config", "core.untrackedCache", "true"],
        ["add", "--", "README.md", *(files or {})],
        ["commit", "-q", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(path), *argv], check=True, env=env, capture_output=True)
    return path


def _under(path: str, needles: tuple[str, ...]) -> bool:
    return any(path == needle or path.startswith(needle + os.sep) for needle in needles)


def _spellings(*paths: Path) -> tuple[str, ...]:
    """
    Each path as given and resolved: macOS resolves /tmp to /private/tmp, while a command
    line or an environment keeps the one given.
    """
    spelled = (str(path).rstrip(os.sep) for given in paths for path in (given, given.resolve()))
    return tuple(dict.fromkeys(spelled))


def _argv(proc: psutil.Process) -> list[str]:
    try:
        return proc.cmdline()
    except (psutil.Error, OSError):
        return []


def _runs_omnigent(argv: list[str]) -> bool:
    """
    Whether a command line runs an Omnigent module, as every process Omnigent starts of its
    own does (``-m omnigent...``). A path that only holds the word does not count.
    """
    return any(
        flag == "-m" and module.split(".")[0] == "omnigent"
        for flag, module in itertools.pairwise(argv)
    )


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


def cli_environs(root: Path) -> list[dict[str, str]]:
    """The environment of each live process the claude-sdk executor started a CLI with."""
    needles = _spellings(root)
    found = []
    for proc in psutil.process_iter():
        with contextlib.suppress(psutil.Error, OSError):
            environ = proc.environ()
            if environ.get("CLAUDE_AGENT_SDK_CLIENT_APP") == "omnigent" and _under(
                environ.get("HOME", ""), needles
            ):
                found.append(environ)
    return found


class _StackProcesses:
    """
    What a stack started: its daemons' descendants, taken just before they stop, and
    every Omnigent process whose cwd, home or command line names its directories.

    Only those are signalled, so a shell or a ``tail`` in the stack root is left alone.
    """

    def __init__(self, scopes: tuple[Path, ...]) -> None:
        self._needles = _spellings(*scopes)
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
        names = process_names(survivors)
        assert not names, f"Stack processes survived teardown: {names}"


def _started_with(proc: psutil.Process) -> tuple[str | None, str | None] | None:
    """A process's exec-time ``PATH`` and ``HOME``; ``None`` if it is gone or neither was read."""
    try:
        environ = proc.environ()
    except (psutil.Error, OSError):
        return None
    path, home = environ.get("PATH"), environ.get("HOME")
    return None if path is None and home is None else (path, home)


def keychain_bypasses(
    stubs: KeychainStubs,
    root: Path,
    processes: Iterable[psutil.Process],
    *,
    unread_fails: bool = False,
) -> list[str]:
    """
    ``pid:name`` of each process started outside the stack's keychain barrier: its ``PATH``
    finds a keychain program elsewhere than the stack's stand-ins (by resolution, nothing
    is run), or its ``HOME`` is not under the stack ``root``. Never a value of either.

    psutil shows the environment a process was exec'd with. So this is evidence for the
    server, the host, the runner zygote, a runner or harness exec'd directly, and each CLI;
    a zygote-forked runner or harness shows its zygote's. A process that is gone, or whose
    environment was not read, is skipped unless ``unread_fails``.
    """
    homes = _spellings(root)
    outside = []
    for proc in processes:
        started = _started_with(proc)
        if started is None:
            if unread_fails:
                outside.append(proc)
            continue
        path, home = started
        if stubs.bypassed(path) or home is None or not _under(home.rstrip(os.sep), homes):
            outside.append(proc)
    return process_names(outside)


def _checked_at_exit(daemons: Iterable[int]) -> list[psutil.Process]:
    """
    The live daemons and those of their descendants that are Omnigent processes or
    ``claude`` CLIs. A ``git`` child, whose ``PATH`` production builds, is left out, whatever
    paths its command line names.
    """
    found: dict[int, psutil.Process] = {}
    for pid in daemons:
        with contextlib.suppress(psutil.Error):
            daemon = psutil.Process(pid)
            found[pid] = daemon
            below = daemon.children(recursive=True)
            clis = {proc.pid for proc in claude_clis(below)}
            for proc in below:
                if proc.pid in clis or _runs_omnigent(_argv(proc)):
                    found[proc.pid] = proc
    return list(found.values())


def keychain_problems(root: Path, stubs: KeychainStubs) -> list[str]:
    """
    What a stack must not leave, by name only: each stand-in call outside the expected ones
    with its count, and a keychain or a ``gh`` login under its ``root``. An empty log says
    only that nothing unexpected was recorded; a sandboxed CLI cannot write to it.
    """
    counts = Counter(stubs.unexpected())
    problems = [f"{call} (x{count})" for call, count in sorted(counts.items())]
    traces = [f"{home}/{trace}" for home in _STACK_HOMES for trace in _LOGIN_TRACES]
    return problems + [trace for trace in ("gh/hosts.yml", *traces) if (root / trace).exists()]


def keychain_calls_summary(stubs: KeychainStubs) -> str:
    """
    What the stand-ins were asked, by name and count, the most frequent first. At most
    :data:`_SUMMARY_NAMES` names, each from the stand-ins' bounded vocabulary.
    """
    counts = Counter(stubs.calls())
    ranked = sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    shown = [f"{call} (x{count})" for call, count in ranked[:_SUMMARY_NAMES]]
    more = f" and {len(ranked) - len(shown)} more names" if len(ranked) > len(shown) else ""
    return f"{shown}{more}, {sum(counts.values())} in all"


class KeychainStubCalls(UserWarning):
    """A stack's :func:`keychain_calls_summary`, in pytest's warnings summary on any outcome."""


@dataclass(frozen=True)
class KeychainGuards:
    """A stack's keychain checks: the three hooks :func:`skeleton_stack` installs."""

    root: Path
    stubs: KeychainStubs

    def _inside(self, processes: Iterable[psutil.Process], *, unread_fails: bool) -> None:
        outside = keychain_bypasses(self.stubs, self.root, processes, unread_fails=unread_fails)
        assert not outside, (
            "Stack processes started outside the keychain barrier "
            f"(a PATH past the stack's stand-ins, or a HOME outside the stack): {outside}"
        )

    def started(self, *daemons: int) -> None:
        """The daemons are live at start, so one whose environment cannot be read fails too."""
        self._inside([psutil.Process(pid) for pid in daemons], unread_fails=True)

    def exiting(self, daemons: Iterable[int]) -> None:
        """The live daemons and what :func:`_checked_at_exit` finds below them, before a stop."""
        self._inside(_checked_at_exit(daemons), unread_fails=False)

    def ended(self) -> None:
        """
        Once every process has ended: warn with the stand-ins' calls, which a passing run
        shows nowhere else, then fail on :func:`keychain_problems`.
        """
        summary = keychain_calls_summary(self.stubs)
        warnings.warn(KeychainStubCalls(f"keychain stand-in calls: {summary}"), stacklevel=1)
        problems = keychain_problems(self.root, self.stubs)
        assert not problems, (
            "The stack asked a keychain stand-in for a call outside the expected ones, or left "
            f"a login: {problems}. A call names its subcommand and item as the stand-in bounded "
            "them ('other' is a name outside its vocabulary). Add a read or a status query to "
            "the expected calls; never a write."
        )


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
    mock_url: str | None,
    host_config: Mapping[str, Any],
    host_env: Mapping[str, str | None] | None = None,
    lease_s: int | None = None,
    grace_s: int | None = None,
    failure_log_tails: bool = True,
    health_timeout: float = 60.0,
    allowlisted_token: str | None = None,
    repo_files: Mapping[str, bytes] | None = None,
    identity: bool = False,
) -> Iterator[Skeleton]:
    """
    Start a Coral server and a host for one test, and tear both down with every process.

    The server runs without the allow-listed runner token, so host-launched runners
    connect with their own, unless ``allowlisted_token`` is given: the server then keeps
    it as ``OMNIGENT_RUNNER_TUNNEL_TOKEN``. Its config, ``root / "server.yaml"``, is read
    again by every restart. ``repo_files`` join the repository's first commit. At exit,
    a SIGTERM included, no process the stack started may survive.

    Both daemons start from :func:`stack_env`. :class:`KeychainGuards` holds the rest: the
    host and server at start, they and their live Omnigent and ``claude`` descendants at
    exit, must have been exec'd inside the keychain barrier (:func:`keychain_bypasses`), and
    once every process has ended the stand-ins' log may hold only the expected calls.

    With ``identity`` the server requires one: accounts with a throwaway cookie secret and
    first admin, :data:`IDENTITY_OWNER`. The host signs in with the owner's JWT, stored in
    its home before it starts, and the client sends it; every secret stays a :class:`Secret`.
    """
    root.mkdir(parents=True, exist_ok=True)
    stubs = install_keychain_stubs(root / "keychain-stubs" / "bin")
    guards = KeychainGuards(root, stubs)
    # Under /tmp to stay within the AF_UNIX path limit for harness sockets.
    harness_tmp = Path(tempfile.mkdtemp(dir="/tmp", prefix="crl-"))
    # The stack's own temp entries go here, short and removed with the stack.
    stack_tmp = Path(tempfile.mkdtemp(prefix="crl-t-"))
    config = write_server_config(
        root / "server.yaml", mock_url=mock_url, lease_s=lease_s, grace_s=grace_s
    )
    processes = _StackProcesses((root, harness_tmp, stack_tmp))
    with ExitStack() as resources:
        resources.enter_context(_sigterm_unwinds())
        resources.callback(shutil.rmtree, harness_tmp, ignore_errors=True)
        resources.callback(shutil.rmtree, stack_tmp, ignore_errors=True)
        # Registered before the reap, so it reads the log after every process has ended.
        resources.callback(guards.ended)
        resources.callback(processes.reap)
        base_env = stack_env(root, stubs, stack_tmp)
        server_env: dict[str, str | Secret | None] = {"CORAL_E2E_SERVER_CONFIG": str(config)}
        if allowlisted_token is None:
            server_env["OMNIGENT_RUNNER_TUNNEL_TOKEN"] = None
        password = Secret(secrets.token_urlsafe(24)) if identity else None
        if password is not None:
            server_env.update(_accounts_env(root, password))
        started = server_runner(
            root,
            server_bootstrap=_SERVER_BOOTSTRAP,
            server_env=_SecretEnv(server_env),
            binding_token=allowlisted_token,
            base_env=base_env,
            health_timeout=health_timeout,
            poll_interval=0.25,
        )
        server = _reported(
            failure_log_tails, "The server's start", lambda: resources.enter_context(started)
        )
        owner_token = None
        if password is not None:
            owner_token = _owner_login(server.base_url, password)
            _store_owner_login(root / "host" / "home", server.base_url, owner_token)
        client = resources.enter_context(
            httpx.Client(
                base_url=server.base_url,
                trust_env=False,
                timeout=30.0,
                headers=None
                if owner_token is None
                else {"Authorization": f"Bearer {owner_token.reveal()}"},
            )
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
        respawned: list[Host] = []
        resources.callback(lambda: [terminate_process(again.proc) for again in respawned])

        def live_daemons() -> list[int]:
            # One that already ended is skipped: its pid may belong to another process by now.
            daemons = (host.proc, *(again.proc for again in respawned), server.server)
            return [
                daemon.pid for daemon in daemons if daemon is not None and daemon.poll() is None
            ]

        # Runs at exit while the daemons still hold their children.
        resources.callback(lambda: processes.remember(*live_daemons()))
        # Runs first at exit, as a step of its own: its failure skips no later teardown step.
        resources.callback(lambda: guards.exiting(live_daemons()))
        _reported(
            failure_log_tails,
            "The host's start",
            lambda: host.wait_online(client, timeout=health_timeout, poll_interval=0.25),
        )
        assert server.server is not None
        guards.started(host.proc.pid, server.server.pid)
        launched = psutil.Process(host.proc.pid)
        launch = HostLaunch(tuple(host.proc.args), launched.environ(), launched.cwd())
        info = client.get("/v1/coral/info")
        assert info.status_code == 200, info.text
        repo = make_repo(root / "repo", repo_files)
        yield Skeleton(
            root,
            server,
            host,
            client,
            repo,
            harness_tmp,
            launch,
            stubs,
            failure_log_tails=failure_log_tails,
            respawned=respawned,
            owner_token=owner_token,
        )


def _reported(log_tails: bool, what: str, step: Callable[[], _T]) -> _T:
    """
    Run one start-up step; without log tails, its failure names only the step.

    The shared helpers' own failures quote the stack's logs. Nothing of that
    failure stays bound in this frame, so even locals in a report show no log text.
    """
    if log_tails:
        return step()
    try:
        return step()
    except AssertionError:
        raise AssertionError(f"{what} failed; its logs are under the stack root") from None


def start_server(skeleton: Skeleton) -> None:
    """Start the stack's server again on its port, database and config."""
    _reported(skeleton.failure_log_tails, "The server's restart", skeleton.server.start_server)


def respawn_host(skeleton: Skeleton, *, timeout: float = 60.0) -> Host:
    """
    Start the host daemon again after the caller ended it: the same command line, home,
    identity and environment, its output added to the same log. Returns it once online.

    Kept here because ``isolated_host`` refuses a home that already holds an identity.
    """
    ended = skeleton.host
    assert ended.proc.poll() is not None, f"host {ended.proc.pid} is still running"
    launch = skeleton.host_launch
    with ended.log_path.open("ab") as log:
        proc = subprocess.Popen(
            list(launch.argv),
            env=dict(launch.env),
            cwd=launch.cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    host = Host(proc, ended.host_id, ended.home, ended.log_path)
    skeleton.respawned.append(host)
    skeleton.host = host
    _reported(
        skeleton.failure_log_tails,
        "The host's restart",
        lambda: host.wait_online(skeleton.client, timeout=timeout, poll_interval=0.25),
    )
    return host


class _ProbeError(Exception):
    """A probe's own failure, kept apart from the wait's timeout."""


def wait_for(
    probe: Callable[[], _T | None],
    *,
    deadline: float,
    what: str,
    skeleton: Skeleton,
    run_id: str | None = None,
    ends_on: Collection[str] = STOPPED,
    poll_interval: float = 0.5,
) -> _T:
    """
    Poll until ``probe`` returns a value other than ``None``, up to an absolute monotonic deadline.

    With ``run_id``, a run whose status is in ``ends_on`` (paused, failed or cancelled)
    while the probe has nothing ends the wait at once. Either failure carries the run's
    detail, the CLI's version line and, unless the stack turned them off, its log tails; a
    probe's own assertion is raised as it is.
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
        if run is not None and run["status"] in ends_on:
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
    if skeleton.failure_log_tails:
        details.append(skeleton.log_tails())
    return "\n".join(details)


def claude_version() -> str:
    """The CLI's own version line, or why it could not be read; see :func:`_claude_cli`."""
    return _claude_cli()[1]


def review_loop_yaml(
    *, impl_token: str, review_token: str, fixture: str = "review_loop.yaml"
) -> str:
    """The review-loop workflow, or ``fixture``, with each step's routing token in its goal."""
    text = (FIXTURES / fixture).read_text()
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


def step_session(client: httpx.Client, run_id: str, node_id: str) -> str:
    """The session of the node's only slot so far."""
    [session_id] = [
        slot["session_id"]
        for slot in detail(client, run_id)["slots"]
        if slot["node_id"] == node_id
    ]
    return session_id


def start_review_loop(
    skeleton: Skeleton,
    *,
    impl_token: str,
    review_token: str,
    start_key: str,
    fixture: str = "review_loop.yaml",
) -> str:
    """Store the review-loop workflow, or ``fixture``, start it on the repo; return the run id."""
    workflow_id = save_workflow(
        skeleton.client,
        review_loop_yaml(impl_token=impl_token, review_token=review_token, fixture=fixture),
    )
    return start_run(
        skeleton.client,
        workflow_id=workflow_id,
        host_id=skeleton.host.host_id,
        repo=skeleton.repo,
        start_key=start_key,
    )["run_id"]


def finished(client: httpx.Client, run_id: str) -> dict[str, Any] | None:
    """The run's detail once it completed, failed or was cancelled."""
    found = detail(client, run_id)
    return found if found["status"] in {"completed", "failed", "cancelled"} else None


def log_entries(client: httpx.Client, run_id: str) -> list[dict[str, Any]]:
    """Every run-log row with its body, in order, read page by page."""
    entries: list[dict[str, Any]] = []
    after: int | None = 0
    while after is not None:
        params = {"limit": 100, "after_seq": after}
        page = client.get(f"{RUNS}/{run_id}/log", params=params).json()
        entries += page["data"]
        after = page["next_after_seq"]
    return entries


def log_kinds(client: httpx.Client, run_id: str) -> list[str]:
    """The kind of every run-log row, in order."""
    return [entry["kind"] for entry in log_entries(client, run_id)]


def waiter(
    skeleton: Skeleton, run_id: str, deadline: float, *, ends_on: Collection[str] = STOPPED
) -> Wait:
    """:func:`wait_for` bound to one run and one absolute deadline."""

    def wait(probe: Callable[[], Any], what: str) -> Any:
        return wait_for(
            probe, deadline=deadline, what=what, skeleton=skeleton, run_id=run_id, ends_on=ends_on
        )

    return wait


def coral_sessions(client: httpx.Client, run_id: str) -> list[dict[str, Any]]:
    """
    Every session labelled with the run, archived ones included, read in full; the list
    route has no label filter.
    """
    listed = client.get(
        "/v1/sessions",
        params={"kind": "any", "visibility": "all", "include_archived": True, "limit": 1000},
    )
    assert listed.status_code == 200, listed.text
    sessions = []
    for item in listed.json()["data"]:
        session = client.get(f"/v1/sessions/{item['id']}")
        assert session.status_code == 200, session.text
        body = session.json()
        if (body.get("labels") or {}).get(RUN_ID_LABEL) == run_id:
            sessions.append(body)
    return sessions


def session(client: httpx.Client, session_id: str) -> dict[str, Any]:
    response = client.get(f"/v1/sessions/{session_id}")
    assert response.status_code == 200, response.text
    return response.json()


def runner_back(client: httpx.Client, session_id: str) -> Callable[[], str | None]:
    """
    A probe: the session's runner id once the server reports its runner online.

    Within 90 s of a server SIGKILL this reads the killed server's stamp, so use
    ``reconnected`` to know a tunnel is back.
    """

    def probe() -> str | None:
        found = session(client, session_id)
        return found["runner_id"] if found["runner_online"] else None

    return probe


def reconnected(skeleton: Skeleton, log: Path, runner_id: str) -> Callable[[], bool | None]:
    """A probe: the restarted server's own log shows the host and the runner connected to it."""
    lines = (f"Host {skeleton.host.host_id} connected", f"Runner {runner_id} connected")

    def probe() -> bool | None:
        text = log.read_text(errors="replace")
        return True if all(line in text for line in lines) else None

    return probe


def _item_texts(items: list[dict[str, Any]]) -> list[str]:
    """The text of each user message among a session's items."""
    return [
        block["text"]
        for item in items
        if item.get("type") == "message" and item.get("role") == "user"
        for block in item.get("content") or []
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]


def session_user_texts(client: httpx.Client, session_id: str) -> list[str]:
    """The text of each user message the session holds, in order."""
    response = client.get(f"/v1/sessions/{session_id}/items", params={"limit": 1000})
    assert response.status_code == 200, response.text
    return _item_texts(response.json()["data"])


def server_logs(skeleton: Skeleton) -> list[Path]:
    """Each server start's own log file, oldest first: the last one is the running server's."""
    directory = skeleton.server.server_home / ".omnigent" / "logs" / "server"
    return sorted(directory.glob("server-*.log"))


def runner_pid(skeleton: Skeleton, session_id: str) -> int:
    """
    The pid of the session's current runner, from the host's own launch line.

    The pid is checked against the launch's workspace and, since each step runner
    leads its own process group, against that group.
    """
    runner_id = session(skeleton.client, session_id)["runner_id"]
    assert runner_id, f"session {session_id} has no runner"
    text = skeleton.host.log_path.read_text(errors="replace")
    [(workspace, pid)] = [
        (found.group(2), int(found.group(3)))
        for found in _LAUNCHED_RUNNER.finditer(text)
        if found.group(1) == runner_id
    ]
    assert os.path.realpath(psutil.Process(pid).cwd()) == os.path.realpath(workspace), pid
    assert os.getpgid(pid) == pid, f"runner {pid} does not lead its process group"
    return pid


def group_members(group_id: int) -> list[psutil.Process]:
    """The live processes of the process group ``group_id``."""
    members = []
    for proc in psutil.process_iter():
        with contextlib.suppress(psutil.Error, OSError):
            if os.getpgid(proc.pid) == group_id and proc.status() != psutil.STATUS_ZOMBIE:
                members.append(proc)
    return members


def group_tree(group_id: int) -> list[psutil.Process]:
    """
    The live members of the process group ``group_id`` and every descendant of theirs.

    A descendant may have left the group yet still be the group's work: under Linux
    bwrap's ``--new-session`` a sandboxed CLI runs in a session of its own below the
    runner's harness. Taken before a fault, it is what must end with the group.
    """
    found: dict[int, psutil.Process] = {}
    for member in group_members(group_id):
        found.setdefault(member.pid, member)
        with contextlib.suppress(psutil.Error):
            for child in member.children(recursive=True):
                found.setdefault(child.pid, child)
    return list(found.values())


def still_running(processes: Iterable[psutil.Process]) -> list[psutil.Process]:
    """Those of ``processes`` still running; a zombie, or a reused pid, does not count."""
    running = []
    for proc in processes:
        with contextlib.suppress(psutil.Error):
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                running.append(proc)
    return running


def group_tree_ended(group_id: int, tree: Iterable[psutil.Process]) -> bool:
    """Whether the group has no live member and no process of ``tree`` still runs."""
    return not group_members(group_id) and not still_running(tree)


def argvs(processes: Iterable[psutil.Process]) -> list[list[str]]:
    """The command line of each process; empty for one that is gone."""
    return [_argv(proc) for proc in processes]


def process_names(processes: Iterable[psutil.Process]) -> list[str]:
    """``pid:name`` of each process, for a failure message that must not show a command line."""
    labels = []
    for proc in processes:
        try:
            labels.append(f"{proc.pid}:{proc.name()}")
        except psutil.Error:
            labels.append(f"{proc.pid}:gone")
    return labels


def claude_clis(processes: Iterable[psutil.Process]) -> list[psutil.Process]:
    """The ``claude`` CLIs among ``processes``: its binary, or node running its script."""
    return [
        proc
        for proc in processes
        if any(os.path.basename(arg) == "claude" for arg in _argv(proc)[:2])
    ]


def _group_of(proc: psutil.Process) -> int | None:
    try:
        return os.getpgid(proc.pid)
    except OSError:
        return None


def harness_socket(stack: Skeleton, session_id: str) -> Path:
    """The session's harness socket, under the stack's root or the default one."""
    roots = dict.fromkeys((stack.harness_tmp, resolve_harness_tmp_parent({})))
    [found] = [path for root in roots for path in root.glob(f"ap-*/conv-{session_id}.sock")]
    return found


def listener_pid(path: Path) -> int:
    """The pid listening on the Unix socket at ``path``: the host connects and asks the kernel."""
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(path))
        if sys.platform == "darwin":
            # SOL_LOCAL and LOCAL_PEERPID of <sys/un.h>, which the socket module does not name.
            return struct.unpack("i", client.getsockopt(0, 2, struct.calcsize("i")))[0]
        peer = client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        return struct.unpack("3i", peer)[0]


def session_cli(stack: Skeleton, runner: int, session_id: str) -> int:
    """
    The pid of the ``claude`` CLI that serves ``session_id`` below its runner: the one below
    the harness that listens on the session's socket. A runner may hold a second harness,
    with a CLI of its own, while it writes the session's title; a zygote-forked harness has
    no command line of its own to tell the two apart.
    """
    harness = listener_pid(harness_socket(stack, session_id))
    tree = group_tree(runner)
    assert harness in {proc.pid for proc in tree}, (
        f"the session's harness {harness} is not among {process_names(tree)}"
    )
    below = psutil.Process(harness).children(recursive=True)
    serving = claude_clis(below)
    assert len(serving) == 1, (
        f"{len(serving)} claude CLIs serve the step's session: {process_names(below)}"
    )
    return serving[0].pid


def step_processes(runner: int, cli: int) -> dict[str, psutil.Process]:
    """
    A step's own processes: its runner, its ``claude`` CLI, the harness (the CLI's
    farthest ancestor in the runner's group) and the launcher the harness started it with.

    ``cli`` names the CLI, from :func:`session_cli`: a runner may hold a second harness,
    with a CLI of its own, while it writes the session's title.
    """
    tree = group_tree(runner)
    clis = [proc for proc in claude_clis(tree) if proc.pid == cli]
    assert len(clis) == 1, f"{len(clis)} claude CLIs in {process_names(tree)}"
    chain = [clis[0], *clis[0].parents()]
    in_group = [
        index
        for index, proc in enumerate(chain)
        if proc.pid != runner and _group_of(proc) == runner
    ]
    assert in_group and in_group[-1] > 0, f"no harness above the CLI: {process_names(chain)}"
    harness_at = in_group[-1]
    return {
        "runner": psutil.Process(runner),
        "harness": chain[harness_at],
        "launcher": chain[harness_at - 1],
        "cli": chain[0],
    }


def group_stopped(group_id: int) -> bool:
    """Whether the group has members and every one of them is stopped."""
    members = group_members(group_id)
    statuses = []
    for proc in members:
        with contextlib.suppress(psutil.Error):
            statuses.append(proc.status())
    return bool(statuses) and all(status == psutil.STATUS_STOPPED for status in statuses)


@dataclass(frozen=True)
class WorkItem:
    """
    One queue row of a run: what it does, its status, when it finished (epoch seconds)
    and its result, decoded.
    """

    effect_type: str | None
    status: int
    finished_at: int | None
    result: dict[str, Any] | None


def _read_database(skeleton: Skeleton) -> Session:
    path = skeleton.server.database_uri.removeprefix("sqlite:///")
    engine = create_engine(
        f"sqlite:///file:{path}?mode=ro&uri=true",
        poolclass=NullPool,
        connect_args={"timeout": 5},
    )
    return Session(engine)


def work_items(skeleton: Skeleton, run_id: str) -> list[WorkItem]:
    """The run's queue rows, read from the server's database without writing to it."""
    with _read_database(skeleton) as db:
        rows = db.execute(select(WorkRow).where(WorkRow.run_id == run_id)).scalars().all()
        return [
            WorkItem(
                json.loads(row.payload).get("effect_type"),
                row.status,
                row.finished_at,
                None if row.result is None else json.loads(row.result),
            )
            for row in rows
        ]


def binding_generation(skeleton: Skeleton, session_id: str) -> int | None:
    """The slot generation the session's Coral binding names, if it has one."""
    with _read_database(skeleton) as db:
        found = select(SessionBindingRow).where(SessionBindingRow.session_id == session_id)
        rows = db.execute(found).scalars().all()
        return rows[0].session_generation if len(rows) == 1 else None


def worker_lease_holder(skeleton: Skeleton) -> str | None:
    """The worker that holds Coral's leader lease now, if any."""
    with _read_database(skeleton) as db:
        leases = db.execute(select(WorkerLeaseRow)).scalars().all()
        live = [lease.holder_id for lease in leases if lease.expires_at > time.time()]
        return live[0] if len(live) == 1 else None


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


def calls_carrying(ledger: list[dict[str, Any]], token: str) -> list[dict[str, Any]]:
    """The step sessions' own model calls whose user messages carry ``token``."""
    return [
        request
        for request in agent_requests(ledger)
        if any(token in text for text in _user_texts(request))
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


def mock_auth(mock_url: str) -> dict[str, Any]:
    """The host's model credential: the mock's dummy key and root URL."""
    return {"auth": {"type": "api_key", "api_key": "mock-key", "base_url": mock_url}}


def queue(
    mock_url: str, token: str, responses: list[dict[str, Any]], *, offering: str = HANDOFF_TOOL
) -> None:
    """
    Replace the queue of ``token``; only the step sessions' own calls may draw from it. They
    are the calls ``offering`` a tool: the handoff tool, or :data:`TOOL_SEARCH` for a CLI that
    defers its MCP tools.
    """
    configure_mock_llm(mock_url, responses, match=token, required_tools=[offering])


def load_step_tools(call_id: str) -> list[dict[str, Any]]:
    """
    Mock responses that have a CLI load the step's two MCP tools. Off the gateway path the
    CLI's betas stay on and it offers ToolSearch in their place until each is selected; from
    then on its calls offer them.
    """
    return [
        tool_call(
            TOOL_SEARCH, {"query": f"select:{tool}", "max_results": 1}, call_id=f"{call_id}-{n}"
        )
        for n, tool in enumerate((SHELL_TOOL, HANDOFF_TOOL))
    ]


def held(response: dict[str, Any]) -> dict[str, Any]:
    """The mock response, held until the test releases it."""
    return {**response, "block": True}


def held_activation(wait: Wait, mock_url: str, token: str, number: int) -> str:
    """The activation of the ``number``-th brief with ``token``, once its first call is held."""

    def found() -> str | None:
        ledger = get_mock_message_requests(mock_url)
        mine = [brief for brief in briefs(ledger) if token in brief]
        if len(mine) >= number and mock_holds_a_call(mock_url):
            return activation_from_brief(mine[number - 1])
        return None

    return wait(found, f"brief {number} with {token}")


def held_decision(wait: Wait, mock_url: str, token: str, *, offering: str) -> str:
    """
    The decision id named by the orchestrator's first request that carries ``token`` and
    offers ``offering``, once that request is held.
    """

    def found() -> str | None:
        texts = [
            text
            for request in get_mock_message_requests(mock_url)
            if any(tool.get("name") == offering for tool in request["body"].get("tools") or [])
            for text in _user_texts(request)
            if token in text
        ]
        if not texts or not mock_holds_a_call(mock_url):
            return None
        match = _DECISION_LINE.search(texts[0])
        assert match is not None, texts[0][:500]
        return match.group(1)

    return wait(found, f"the decision request with {token}")


def result_texts(mock_url: str, call_id: str) -> list[str]:
    """The distinct texts of the tool result the CLI sent back for one scripted call."""
    texts = []
    for raw in tool_results(get_mock_message_requests(mock_url), call_id=call_id):
        content = json.loads(raw).get("content")
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        texts.append(str(content))
    return list(dict.fromkeys(texts))


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
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "activation_id": activation_id,
        "status": status,
        "report": report,
    }
    if label is not None:
        arguments["label"] = label
    if blocked_reason is not None:
        arguments["blocked_reason"] = blocked_reason
    return tool_call(HANDOFF_TOOL, arguments, call_id=call_id)
