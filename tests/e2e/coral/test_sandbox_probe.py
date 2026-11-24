"""Probe 15: what a generated step's shell reaches on a real stack.

The probe runs as the implementer, the widest stance Coral generates, while a reviewer
on a parallel branch is held mid-turn, so its runner, harness socket and CLI are live.
Every target is resolved on the host side and proven live right before the probe call
is released and again after it: a target that went missing fails as a failed control,
never as a verdict. ``probe15.sh``, committed into the repository's first commit,
prints verdict tokens only; it compares canaries in the step by digest (in files, and
in the environments and command lines it reads), and the host's tunnel credential file
by its size, whose content the test never reads.

Pins are change detectors per platform. A pinned verdict outside its kind's closed set
(:data:`CLOSED`) is open and names its owner; a closed one names none. Without a pin for
the platform the test writes its verdicts to ``artifacts/`` (when that directory exists,
as in CI) and fails as not pinned. The first test also runs the probe outside the sandbox,
where each process must be read and hold no API key, and both stack probes try the step's
own credential proxy with no session token. The second test runs one step on a server that keeps
the allow-listed runner token, with the host exporting it. The third runs one step on a
server that requires identity, after the same probe ran outside the sandbox and reached
every owner path it tries. The plain tests at the end run the probe on synthetic
targets, with no stack; the last of them check the keychain stand-ins every stack puts
first on its processes' ``PATH``, and the guards that name a process started past them.

Canaries, the allow-listed token and the identity stack's secrets are held in
:class:`Secret` and the probe's output is reduced to its verdicts where it is read. Only
the stack helpers' frames hold the allow-listed token as a raw value, so only a failure
in the stack's start or teardown prints that throwaway value.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import functools
import hashlib
import http.server
import inspect
import json
import mmap
import os
import platform
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import uuid
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import httpx
import psutil
import pytest

import coral
import omnigent
from coral.gates.integrity import (
    GATE_BLOCKERS,
    UNPROBED_BLOCKERS,
    HostSandboxPolicy,
    SandboxBlockers,
)
from coral.omni.process_map import SANDBOX_POLICY_REVISION
from coral.omni.server.step_agents import checkout_read_paths
from omnigent._platform import stable_user_id
from omnigent.inner.claude_gateway_shim import ClaudeGatewayShim, UpstreamCredential
from omnigent.inner.claude_sdk_executor import _ASSUME_FIRST_PARTY_ENV, _find_system_claude
from omnigent.inner.os_env import _DEFAULT_ENV_PASSTHROUGH
from omnigent.runner.identity import RUNNER_TUNNEL_TOKEN_HEADER, token_bound_runner_id
from omnigent.runtime.harnesses.paths import resolve_harness_tmp_parent
from tests._helpers.live_server import find_free_port, terminate_process
from tests._helpers.polling import poll_until
from tests.e2e.conftest import get_mock_message_requests, release_mock_gate
from tests.e2e.coral import _skeleton as sk
from tests.e2e.coral._claude_sdk_kit import (
    KEYCHAIN_PROGRAMS,
    LOCAL_HOSTS,
    EgressRecorder,
    KeychainStubs,
    install_keychain_stubs,
)
from tests.e2e.coral._live_proxy import Secret

# Absolute deadline for a scenario, below the marker's limit.
SCENARIO_S = 200
SHORT_LEASE_S = 10
PROBE = Path(__file__).with_name("probe15.sh")
REPO = Path(__file__).resolve().parents[3]
ARTIFACTS = REPO / "artifacts"
FIXTURE = "probe.yaml"
README = {"command": "cat README.md"}
NOTHING = {"command": "true"}
DONE = {"text": "Handed off."}
VERDICTS = {
    "reachable",
    "denied",
    "hidden",
    "not_present",
    "mismatch",
    "refused",
    "minted",
    "unclassified",
}
# What the probe reports beside a target's own verdict: the names it read, whether the API
# key canary is in the environment or the command line it read, and a credential's read.
SUB_CHECKS = (".names", ".api_key", ".argv_api_key", ".read")
# The probe's own checks that what it uses works in the step; each must be reachable.
CONTROL_NAME = "PROBE_CONTROL_API_KEY"
CONTROLS = (
    "control_file",
    "control_environ",
    "control_environ.api_key",
    "control_environ.argv_api_key",
    "control_python",
)
_LINE = re.compile(r"^([a-z_]+(?:\.[a-z_]+){0,2})=(\S+)$")
# Credential-like names, in any case: the only names a ``.names`` line may carry.
_SENSITIVE_NAME = re.compile(
    r"^(\w*(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|BEARER|API_KEY|PRIVATE_KEY|COOKIE)\w*"
    r"|HARNESS_CLAUDE_SDK_\w*)$",
    re.ASCII | re.IGNORECASE,
)
_TOKEN_NAME = re.compile(r"^OMNIGENT_RUNNER_.*TOKEN.*$")
# The only model credential a Coral step's CLI holds: its session token at its executor's
# loopback credential proxy, which swaps it for the real key.
PROXY_TOKEN_NAME = "OMNIGENT_CLAUDE_PROXY_TOKEN"
FIRST_PARTY_FLAG_NAME = "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL"
# Every beta a gateway launch sends, its experimental betas being switched off (measured on
# claude 2.1.325); a CLI on a key with no gateway sends more.
GATEWAY_PATH_BETAS = frozenset(
    {"claude-code-20250219", "effort-2025-11-24", "interleaved-thinking-2025-05-14"}
)
_PROXY_NAMES = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")
# The model the probe's own requests to that proxy name: none may reach the mock's ledger.
PROXY_PROBE_MODEL = "crl-credential-proxy-probe"
# The runner tokens the probe looks for in an exec-time environment: a binding token that
# mints an owner JWT, and the host's bearer. A host-launched POSIX runner's holds neither.
RUNNER_CREDENTIALS = ("OMNIGENT_RUNNER_INITIAL_AUTH_TOKEN", "OMNIGENT_RUNNER_TUNNEL_BINDING_TOKEN")
# The call a stack host's readiness probe makes on every platform: its copilot row asks gh.
HOST_GH_PROBE = "gh auth token"


@dataclass(frozen=True)
class Pin:
    """A pinned verdict (or a ``.names`` list) and, when it is open, its owner ticket."""

    verdict: str
    owner: str | None = None


# Owners, by the exposure an open pin shows.
ACCEPTED_SINGLE_USER = "accepted: single-user servers are never Enforced (gates-and-inbox.md)"
OTHER_PROGRAMS = "CRL-174"  # other programs' same-user sockets and loopback services
PLANTED_CONFIG = "CRL-181"  # files a step leaves that the owner's tools run unsandboxed

_READ_CLOSED = frozenset({"denied", "hidden"})
# Per probe kind, the verdicts that show the step reaching nothing. Any other verdict is
# open, a credential's read included whatever its use gave, and names its owner.
CLOSED: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        **dict.fromkeys(
            ("environ", "file", "token", "socket", "tcp", "http", "mint", "bearer", "stored"),
            _READ_CLOSED,
        ),
        "plant": _READ_CLOSED,
        "owner_http": frozenset({"refused", "denied", "hidden"}),
        "credential_proxy": frozenset({"refused", "denied", "hidden"}),
        "shell": frozenset({"not_present"}),
    }
)
CLOSED_SUB: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        ".read": _READ_CLOSED,
        ".api_key": _READ_CLOSED,
        ".argv_api_key": _READ_CLOSED,
        ".names": frozenset({"none"}),
    }
)
# Facts the test reads itself, outside the sandbox: change detectors, not the step's reach.
OUTSIDE = "outside"
# The kind of every pinned check, so a pin is judged open or closed without a stack.
PIN_KINDS: Mapping[str, str] = MappingProxyType(
    {
        **dict.fromkeys(
            (
                "runner_environ",
                "cli_environ",
                "host_environ",
                "own_cli_environ",
                "own_runner_environ",
                "server_environ",
            ),
            "environ",
        ),
        **dict.fromkeys(
            (
                "credential_files.claude",
                "credential_files.omnigent_secrets",
                "credential_files.host_tunnel",
                "credential_files.cookie_secret",
                "bridge_dir",
            ),
            "file",
        ),
        **dict.fromkeys(
            ("harness_socket", "other_unix_socket", "other_abstract_socket"), "socket"
        ),
        **dict.fromkeys(("server_loopback", "server_localhost"), "http"),
        **dict.fromkeys(("owner_bare", "owner_bare_localhost"), "owner_http"),
        **dict.fromkeys(("own_runner_bearer", "host_bearer"), "bearer"),
        **dict.fromkeys(("step_runs", "runner", "harness", "launcher", "cli"), OUTSIDE),
        "config_api_key": "token",
        "credential_proxy": "credential_proxy",
        "shell_env_names": "shell",
        "own_runner_mint": "mint",
        "stored_credentials": "stored",
        "other_loopback_tcp": "tcp",
        "worktree_exec_config": "plant",
    }
)

EXPECTED: dict[str, dict[str, Pin]] = {
    # Pinned from one local run on macOS 27.2.1 with claude 2.1.325 (seatbelt).
    "darwin": {
        "harness_socket": Pin("denied"),
        "runner_environ": Pin("denied"),
        "runner_environ.api_key": Pin("denied"),
        "runner_environ.argv_api_key": Pin("denied"),
        "cli_environ": Pin("denied"),
        "cli_environ.api_key": Pin("denied"),
        "cli_environ.argv_api_key": Pin("denied"),
        "host_environ": Pin("denied"),
        "host_environ.api_key": Pin("denied"),
        "host_environ.argv_api_key": Pin("denied"),
        "own_cli_environ": Pin("denied"),
        "own_cli_environ.api_key": Pin("denied"),
        "own_cli_environ.argv_api_key": Pin("denied"),
        "credential_files.claude": Pin("denied"),
        "credential_files.omnigent_secrets": Pin("denied"),
        "credential_files.host_tunnel": Pin("denied"),
        # The config file only; the CLIs' copies of the key are the .api_key checks.
        "config_api_key": Pin("denied"),
        "bridge_dir": Pin("denied"),
        "server_loopback": Pin("reachable", ACCEPTED_SINGLE_USER),
        "server_localhost": Pin("reachable", ACCEPTED_SINGLE_USER),
        "owner_bare": Pin("reachable", ACCEPTED_SINGLE_USER),
        "owner_bare_localhost": Pin("reachable", ACCEPTED_SINGLE_USER),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
        # The step reaches its own credential proxy and is refused without the session token.
        "credential_proxy": Pin("refused"),
    },
    # Pinned from lane run 44980984569 on Ubuntu 24.04.5 LTS, claude 2.1.295 (bwrap); the
    # two owner_bare pins measured in lane run 45187294423 (a shared network namespace).
    "linux": {
        "harness_socket": Pin("hidden"),
        "runner_environ": Pin("hidden"),
        "runner_environ.api_key": Pin("hidden"),
        "runner_environ.argv_api_key": Pin("hidden"),
        "cli_environ": Pin("hidden"),
        "cli_environ.api_key": Pin("hidden"),
        "cli_environ.argv_api_key": Pin("hidden"),
        "host_environ": Pin("hidden"),
        "host_environ.api_key": Pin("hidden"),
        "host_environ.argv_api_key": Pin("hidden"),
        "own_cli_environ": Pin("hidden"),
        "own_cli_environ.api_key": Pin("hidden"),
        "own_cli_environ.argv_api_key": Pin("hidden"),
        "credential_files.claude": Pin("hidden"),
        "credential_files.omnigent_secrets": Pin("hidden"),
        "credential_files.host_tunnel": Pin("hidden"),
        "config_api_key": Pin("hidden"),
        "bridge_dir": Pin("hidden"),
        "server_loopback": Pin("reachable", ACCEPTED_SINGLE_USER),
        "server_localhost": Pin("reachable", ACCEPTED_SINGLE_USER),
        "owner_bare": Pin("reachable", ACCEPTED_SINGLE_USER),
        "owner_bare_localhost": Pin("reachable", ACCEPTED_SINGLE_USER),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
        # Not measured in a lane yet: set from the shared network namespace (server_loopback
        # is reachable there) and the proxy's own refusal, which no sandbox changes.
        "credential_proxy": Pin("refused"),
    },
}
# What the same probe must find outside any sandbox right before the step runs it: each
# process read, its environment and command line without the API key, and the proxy refusing
# a caller that has no session token.
OUTSIDE_PROCESSES = ("runner_environ", "cli_environ", "host_environ", "own_cli_environ")
OUTSIDE_PROBE15: Mapping[str, str] = MappingProxyType(
    {
        **{
            f"{check}{suffix}": verdict
            for check in OUTSIDE_PROCESSES
            for suffix, verdict in (
                ("", "reachable"),
                (".api_key", "not_present"),
                (".argv_api_key", "not_present"),
            )
        },
        "credential_proxy": "refused",
    }
)
# What the pins hold for. Harness sockets sit under the stack's /tmp/crl-* (production:
# /tmp/omnigent-<uid>); bridge canaries under the stack's TMPDIR (production: the
# per-user $TMPDIR). The checkout read grant is on: the checkout is an editable install.
RECORDED: dict[str, dict[str, Any]] = {
    "darwin": {
        "os": "macOS 27.2.1",
        "claude": "2.1.325 (Claude Code)",
        "harness_socket_root": "/tmp/crl-*",
        "bridge_dir_root": "<stack TMPDIR>/omnigent-<uid>/claude-native",
        "checkout_read_grant": True,
        "server_url_given_to_the_host": "http://127.0.0.1:<port>",
    },
    "linux": {
        "os": "Ubuntu 24.04.5 LTS, kernel 7.0.0-1017-azure",
        "claude": "2.1.295 (Claude Code)",
        "harness_socket_root": "/tmp/crl-*",
        "bridge_dir_root": "<stack TMPDIR>/omnigent-<uid>/claude-native",
        "checkout_read_grant": True,
        "server_url_given_to_the_host": "http://127.0.0.1:<port>",
    },
}


@dataclass(frozen=True)
class Target:
    """One probe argument, and how the host proves its target is there and live."""

    check: str
    kind: str
    target: str
    expect: str = ""
    live: Callable[[], str | None] | None = field(default=None, compare=False)

    def argument(self) -> str:
        return f"{self.check}|{self.kind}|{self.target}|{self.expect}"


@dataclass(frozen=True)
class Reading:
    """The probe's output as its verdict tokens, and a count of every line that was not one."""

    verdicts: dict[str, str]
    strays: int
    results: int = 1
    stderr_chars: int = 0


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canary() -> Secret:
    """A random, test-only value the probe can find by its shape (``canary-<hex>``)."""
    return Secret(f"canary-{secrets.token_hex(16)}")


def _digest(value: Secret) -> str:
    """The expectation the probe compares a canary-shaped value with."""
    return f"sha256:{_sha256(value.reveal().encode())}"


def _plant(path: Path, value: Secret) -> None:
    """Write a canary where it belongs, owner-only, never over a file already there."""
    for directory in reversed(path.parents):
        if not directory.exists():
            directory.mkdir(mode=0o700)
    with path.open("xb") as handle:
        handle.write(json.dumps({"canary": value.reveal()}).encode())
    path.chmod(0o600)


def _file_live(path: Path, digest: str) -> Callable[[], str | None]:
    """The test's own canary still holds what it wrote."""

    def live() -> str | None:
        try:
            held = _sha256(path.read_bytes())
        except OSError as error:
            return f"{path.name}: {type(error).__name__}"
        return None if held == digest else f"{path.name} changed"

    return live


def _holds(path: Path, value: Secret) -> Callable[[], str | None]:
    """The test's own config file still holds its canary."""

    def live() -> str | None:
        try:
            found = value.found_in(path)
        except OSError as error:
            return f"{path.name}: {type(error).__name__}"
        return None if found else f"{path.name} lost its canary"

    return live


def _metadata_live(path: Path) -> Callable[[], str | None]:
    """The same regular file is still there, judged by its metadata alone."""
    first = path.stat()

    def live() -> str | None:
        try:
            now = path.stat()
        except OSError as error:
            return f"{path.name}: {type(error).__name__}"
        same = (now.st_ino, now.st_size, now.st_mtime_ns) == (
            first.st_ino,
            first.st_size,
            first.st_mtime_ns,
        )
        return (
            None if same and stat.S_ISREG(now.st_mode) and now.st_size else f"{path.name} changed"
        )

    return live


def _process_live(pid: int) -> Callable[[], str | None]:
    """
    The same process (pid and start time) still runs, and outside the sandbox its user
    reads its environment (PATH or HOME among the names) and a command line; no value is kept.
    """
    started = psutil.Process(pid).create_time()

    def live() -> str | None:
        with contextlib.suppress(psutil.Error):
            proc = psutil.Process(pid)
            if proc.create_time() != started or proc.status() == psutil.STATUS_ZOMBIE:
                return f"process {pid} is gone"
            if not {"PATH", "HOME"} & proc.environ().keys():
                return f"process {pid}'s environment is unreadable outside the sandbox"
            if not proc.cmdline():
                return f"process {pid}'s command line is unreadable outside the sandbox"
            return None
        return f"process {pid} is gone"

    return live


def _socket_live(path: Path) -> Callable[[], str | None]:
    """Something listens on the socket: the host connects and hangs up."""

    def live() -> str | None:
        try:
            if not stat.S_ISSOCK(path.stat().st_mode):
                return f"{path.name} is not a socket"
        except OSError as error:
            return f"{path.name}: {type(error).__name__}"
        return _listening(socket.AF_UNIX, str(path), path.name)()

    return live


def _listening(
    family: int, address: str | tuple[str, int], label: str
) -> Callable[[], str | None]:
    """Something listens at ``address``: the host connects and hangs up."""

    def live() -> str | None:
        try:
            with socket.socket(family) as client:
                client.settimeout(5)
                client.connect(address)
        except OSError as error:
            return f"{label}: {type(error).__name__}"
        return None

    return live


def _url_live(url: str, client: httpx.Client | None = None) -> Callable[[], str | None]:
    """The URL answers 200 to a bare request, or to one with ``client``'s own credential."""

    def live() -> str | None:
        try:
            if client is None:
                response = httpx.get(url, timeout=5.0, trust_env=False)
            else:
                response = client.get(url, timeout=5.0)
        except httpx.HTTPError as error:
            return f"{url}: {type(error).__name__}"
        return None if response.status_code == 200 else f"{url}: HTTP {response.status_code}"

    return live


def _absent(path: Path) -> Callable[[], str | None]:
    """Where the probe plants, its directory exists and nothing was left behind."""

    def live() -> str | None:
        if not path.parent.is_dir():
            return f"{path.parent.name} is gone"
        return f"{path.name} was left behind" if path.exists() else None

    return live


def _failed_controls(targets: list[Target]) -> list[str]:
    return [
        f"{target.check}: {reason}"
        for target in targets
        if target.live is not None and (reason := target.live())
    ]


def _unproven(targets: list[Target]) -> list[str]:
    """Targets without a host-side control; the in-step controls and the shell need none."""
    return [
        target.check
        for target in targets
        if target.live is None
        and not target.check.startswith("control_")
        and target.kind != "shell"
    ]


def _misjudged(targets: list[Target]) -> list[str]:
    """Targets whose kind is not the one :data:`PIN_KINDS` judges their pins by."""
    return [
        target.check
        for target in targets
        if not target.check.startswith("control_") and PIN_KINDS.get(target.check) != target.kind
    ]


def _counts(mock: str, tokens: tuple[str, ...]) -> dict[str, int]:
    ledger = get_mock_message_requests(mock)
    return {token: len(sk.calls_carrying(ledger, token)) for token in tokens}


def _release_oldest(wait: sk.Wait, mock: str, tokens: tuple[str, ...]) -> str:
    """Release the oldest held call; return the token of the session that called again."""
    before = _counts(mock, tokens)
    release_mock_gate(mock)

    def advanced() -> str | None:
        now = _counts(mock, tokens)
        return next((token for token in tokens if now[token] > before[token]), None)

    return wait(advanced, "the released session's next call")


def _harness_socket(stack: sk.Skeleton, session_id: str) -> Path:
    """The session's harness socket, under the stack's root or the default one."""
    roots = dict.fromkeys((stack.harness_tmp, resolve_harness_tmp_parent({})))
    [found] = [path for root in roots for path in root.glob(f"ap-*/conv-{session_id}.sock")]
    return found


def _listener_pid(path: Path) -> int:
    """The pid listening on the Unix socket at ``path``: the host connects and asks the kernel."""
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(path))
        if sys.platform == "darwin":
            # SOL_LOCAL and LOCAL_PEERPID of <sys/un.h>, which the socket module does not name.
            return struct.unpack("i", client.getsockopt(0, 2, struct.calcsize("i")))[0]
        peer = client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        return struct.unpack("3i", peer)[0]


def _session_cli(stack: sk.Skeleton, runner: int, session_id: str) -> int:
    """
    The pid of the ``claude`` CLI that serves ``session_id`` below its runner: the one below
    the harness that listens on the session's socket. A runner may hold a second harness,
    with a CLI of its own, while it writes the session's title; a zygote-forked harness has
    no command line of its own to tell the two apart.
    """
    harness = _listener_pid(_harness_socket(stack, session_id))
    tree = sk.group_tree(runner)
    assert harness in {proc.pid for proc in tree}, (
        f"the session's harness {harness} is not among {sk.process_names(tree)}"
    )
    below = psutil.Process(harness).children(recursive=True)
    serving = sk.claude_clis(below)
    assert len(serving) == 1, (
        f"{len(serving)} claude CLIs serve the step's session: {sk.process_names(below)}"
    )
    return serving[0].pid


def _socket_root(stack: sk.Skeleton, harness_socket: Path) -> str:
    """The root the runner put the socket under, as recorded beside the pins."""
    root = harness_socket.parent.parent
    if root == stack.harness_tmp:
        return str(root.parent / "crl-*")
    return str(root).replace(f"-{os.getuid()}", "-<uid>")


def _owner_urls(stack: sk.Skeleton) -> dict[str, str]:
    """The owner route on both loopback names, as a step would call it with no credential."""
    port = stack.server.port
    return {
        check: f"http://{host}:{port}{sk.RUNS}"
        for check, host in (("owner_bare", "127.0.0.1"), ("owner_bare_localhost", "localhost"))
    }


def _bridge_root(stack: sk.Skeleton) -> Path:
    """Where a host-launched step keeps its bridge tree: under the host's TMPDIR."""
    return Path(stack.host_launch.env["TMPDIR"]) / f"omnigent-{stable_user_id()}" / "claude-native"


def _token_names(proc: psutil.Process) -> str:
    """The ``OMNIGENT_RUNNER_*TOKEN*`` names in a process's environment, never a value."""
    names = set(proc.environ())
    assert {"PATH", "HOME"} & names, f"{proc.pid}'s environment is unreadable outside the sandbox"
    return ",".join(sorted(name for name in names if _TOKEN_NAME.match(name))) or "none"


def _cli_proxy(cli: int) -> tuple[Target, Secret]:
    """
    The credential proxy a step's CLI is pointed at, as a probe target by its loopback port,
    and the session token that CLI holds, redacted; both read outside the sandbox from the
    CLI's environment, none of which is kept.
    """
    environ = psutil.Process(cli).environ
    url = urllib.parse.urlsplit(environ().get("ANTHROPIC_BASE_URL", ""))
    assert url.hostname == "127.0.0.1" and url.port, f"CLI {cli} names no loopback proxy"
    token = Secret(environ().get(PROXY_TOKEN_NAME, ""))
    assert token.reveal(), f"CLI {cli} holds no {PROXY_TOKEN_NAME}"
    live = _listening(socket.AF_INET, ("127.0.0.1", url.port), "the credential proxy")
    return Target("credential_proxy", "credential_proxy", str(url.port), live=live), token


def _fenced(recorder_url: str) -> dict[str, str]:
    """
    Host environment that sends every request of the host, its runners and their CLIs to
    another machine through ``recorder_url`` instead; the host forwards the names it lists.
    """
    return {
        **dict.fromkeys(_PROXY_NAMES, recorder_url),
        "NO_PROXY": LOCAL_HOSTS,
        "OMNIGENT_RUNNER_ENV_PASSTHROUGH": ",".join((*_PROXY_NAMES, "NO_PROXY")),
    }


def _betas_sent(mock: str, token: str) -> set[str]:
    """Every ``anthropic-beta`` flag on the model requests that carry ``token``."""
    return {
        beta
        for entry in get_mock_message_requests(mock)
        if token in json.dumps(entry["body"])
        for beta in entry["betas"]
    }


def _cli_build_files(launcher: Path) -> list[Path]:
    """
    The files that may hold the CLI's code: the launcher, and for an npm install's small
    launcher every file of 1 MiB or more in its package and the platform packages beside it.
    """
    if launcher.stat().st_size >= 1 << 20:
        return [launcher]
    package = next((d for d in launcher.parents if (d / "package.json").is_file()), None)
    roots = [] if package is None else [package, *package.parent.glob("claude-code-*")]
    return [
        launcher,
        *(
            path
            for root in roots
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink() and path.stat().st_size >= 1 << 20
        ),
    ]


def _key_exposed_outside(verdicts: Mapping[str, str]) -> list[str]:
    """
    How the run outside the sandbox departs from :data:`OUTSIDE_PROBE15`, as tokens and names:
    a process it could not read, an API key it found, harness config in a CLI's environment,
    or a CLI without its session token.
    """
    problems = [
        f"{key} is {verdicts.get(key, '-')}"
        for key, verdict in OUTSIDE_PROBE15.items()
        if verdicts.get(key) != verdict
    ]
    for check in ("cli_environ", "own_cli_environ"):
        names = verdicts.get(f"{check}.names", "").split(",")
        config = sorted(name for name in names if name.startswith("HARNESS_CLAUDE_SDK_"))
        if config:
            problems.append(f"{check} holds {config}")
        if PROXY_TOKEN_NAME not in names:
            problems.append(f"{check} holds no {PROXY_TOKEN_NAME}")
    return problems


def _probe_command(targets: list[Target]) -> dict[str, str]:
    return {"command": " ".join(["sh", PROBE.name, *(shlex.quote(t.argument()) for t in targets)])}


def _split_check(check: str) -> tuple[str, str]:
    for suffix in SUB_CHECKS:
        if check.endswith(suffix):
            return check.removesuffix(suffix), suffix
    return check, ""


def _token_allowed(suffix: str, token: str) -> bool:
    if suffix == ".names":
        return token == "none" or all(_SENSITIVE_NAME.match(name) for name in token.split(","))
    return token in VERDICTS


def _parse(output: str, checks: Collection[str]) -> tuple[dict[str, str], int]:
    """The probe's lines as ``{check: token}``, and how many lines were anything else."""
    verdicts: dict[str, str] = {}
    strays = 0
    for line in output.splitlines():
        match = _LINE.match(line)
        if match is None:
            strays += 1
            continue
        check, token = match.groups()
        base, suffix = _split_check(check)
        if base not in checks or check in verdicts or not _token_allowed(suffix, token):
            strays += 1
            continue
        verdicts[check] = token
    return verdicts, strays


def _read_probe(mock: str, call_id: str, checks: Collection[str]) -> Reading | None:
    """
    The probe's result once the CLI sent it back, reduced to its verdicts in this frame;
    its stderr, which lands in the ledger too, is kept only as a length.
    """
    texts = sk.result_texts(mock, call_id)
    if not texts:
        return None
    stdout, stderr_chars = texts[0], 0
    with contextlib.suppress(json.JSONDecodeError, TypeError):
        body = json.loads(texts[0])
        if isinstance(body, dict) and "stdout" in body:
            stdout = str(body["stdout"])
            stderr_chars = len(str(body.get("stderr") or ""))
    verdicts, strays = _parse(stdout, checks)
    return Reading(verdicts, strays, results=len(texts), stderr_chars=stderr_chars)


def _assert_reading(reading: Reading, targets: list[Target]) -> dict[str, str]:
    """The verdicts, once the probe printed only verdict tokens, one for every target."""
    assert reading.results == 1, f"the probe's call has {reading.results} distinct results"
    assert reading.stderr_chars == 0, (
        f"the probe wrote {reading.stderr_chars} character(s) to stderr"
    )
    assert reading.strays == 0, (
        f"the probe printed {reading.strays} line(s) that are not verdict tokens"
    )
    missing = sorted({target.check for target in targets} - reading.verdicts.keys())
    assert not missing, f"the probe gave no verdict for {missing}"
    return reading.verdicts


def _controls_held(verdicts: Mapping[str, str], where: str = "in the step") -> None:
    """The probe's own controls held in the run ``where`` names, and it classified everything."""
    failed = {
        check: verdicts.get(check) for check in CONTROLS if verdicts.get(check) != "reachable"
    }
    assert not failed, f"failed control {where}: {failed}"
    unclassified = sorted(check for check, token in verdicts.items() if token == "unclassified")
    assert not unclassified, f"failed control {where}: the probe could not classify {unclassified}"
    # The control's own variable has a credential-like name, so the names listing is proven too.
    listed = verdicts.get("control_environ.names", "").split(",")
    assert CONTROL_NAME in listed, f"failed control {where}: control_environ.names is {listed}"


def _ledger_holds(mock: str, held: Mapping[str, Secret]) -> list[str]:
    """Which held values the mock's ledger shows, by name; the ledger stays in this frame."""
    ledger = json.dumps(get_mock_message_requests(mock))
    return sorted(name for name, value in held.items() if value.reveal() in ledger)


def _os_version() -> str:
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}"
    with contextlib.suppress(OSError):
        return f"{platform.freedesktop_os_release()['PRETTY_NAME']}, kernel {platform.release()}"
    return platform.platform()


def _recorded(stack: sk.Skeleton, harness_socket: Path) -> dict[str, Any]:
    """What the verdicts hold for: versions, the socket and bridge roots, the read grant."""
    packages = (Path(omnigent.__file__).parent, Path(coral.__file__).parent)
    argv = stack.host_launch.argv
    given = argv[argv.index("--server") + 1].replace(str(stack.server.port), "<port>")
    bridge = str(_bridge_root(stack)).replace(stack.host_launch.env["TMPDIR"], "<stack TMPDIR>")
    return {
        "os": _os_version(),
        "claude": sk.claude_version(),
        "harness_socket_root": _socket_root(stack, harness_socket),
        "bridge_dir_root": bridge.replace(f"omnigent-{stable_user_id()}", "omnigent-<uid>"),
        "checkout_read_grant": bool(checkout_read_paths(packages, Path(sys.prefix))),
        "server_url_given_to_the_host": given,
    }


def _assert_recorded(recorded: Mapping[str, Any], pinned: Mapping[str, Any] | None = None) -> None:
    """
    The pins hold only for the socket root, read grant, server, spawn path and sandbox policy
    pinned with; the identity stack also pins the gate label its server reads.
    """
    pinned = RECORDED.get(sys.platform, {}) if pinned is None else pinned
    keys = ("harness_socket_root", "checkout_read_grant", "server_mode", "runner_spawn")
    for key in (*keys, "sandbox_policy", "gate_integrity"):
        if key in pinned:
            assert recorded[key] == pinned[key], (key, recorded[key])


def _without_controls(verdicts: Mapping[str, str]) -> dict[str, str]:
    """The verdicts a run reports and pins: every check but the probe's own controls."""
    return {check: token for check, token in verdicts.items() if not check.startswith("control_")}


def _write_artifact(name: str, report: Mapping[str, Any]) -> Path | None:
    """Write the run's verdicts where the lane uploads them, when that directory exists."""
    if not ARTIFACTS.is_dir():
        return None
    path = ARTIFACTS / f"{name}-{sys.platform}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path


def _exposure(pinned: str, observed: str, was_open: bool, is_open: bool) -> str:
    if is_open and not was_open:
        return f"{pinned} -> {observed} reads as an exposure"
    if was_open and not is_open:
        return f"{pinned} -> {observed}: the step reaches less; re-pin"
    return f"{pinned} -> {observed}"


def _names_moved(pinned: str, observed: str) -> str:
    """The names a list gained (an exposure) or lost (a reduction); names only."""
    before, after = ({*names.split(",")} - {"none"} for names in (pinned, observed))
    moves = []
    if after - before:
        moves.append(f"exposure, new names {sorted(after - before)}")
    if before - after:
        moves.append(f"reduction, names gone {sorted(before - after)}; re-pin")
    return "; ".join(moves) or f"pinned {pinned}, observed {observed}"


def _open(check: str, verdict: str, kinds: Mapping[str, str] = PIN_KINDS) -> bool:
    """
    Whether a verdict shows the step reaching something: it is outside its kind's closed
    set. A check of no known kind is open; one the test reads outside the sandbox is not.
    """
    base, suffix = _split_check(check)
    kind = kinds.get(base)
    if kind is None:
        return True
    if kind == OUTSIDE:
        return False
    closed = CLOSED_SUB.get(suffix) if suffix else CLOSED.get(kind)
    return closed is None or verdict not in closed


def _owner_problems(pins: Mapping[str, Pin], kinds: Mapping[str, str] = PIN_KINDS) -> list[str]:
    """Pins whose owner does not follow their verdict: an open one names it, a closed one not."""
    problems = []
    for check, pin in sorted(pins.items()):
        owned = bool((pin.owner or "").strip())
        if _open(check, pin.verdict, kinds) and not owned:
            problems.append(f"{check}: open without an owner ticket")
        elif owned and not _open(check, pin.verdict, kinds):
            problems.append(f"{check}: closed with an owner ticket")
    return problems


def _assert_pinned(
    name: str,
    pins: Mapping[str, Pin],
    observed: Mapping[str, str],
    written: Path | None,
    kinds: Mapping[str, str] = PIN_KINDS,
) -> None:
    """Compare with the platform's pins, naming each check and the direction it moved."""
    where = f"verdicts written to {written}" if written else "no artifacts/ directory to write to"
    assert pins, f"{name} is not pinned for {sys.platform} ({where}): {json.dumps(observed)}"
    problems = _owner_problems(pins, kinds)
    assert not problems, f"{name}'s pins: {problems}"
    moved = []
    for check in sorted(pins.keys() | observed.keys()):
        pinned = pins[check].verdict if check in pins else None
        seen = observed.get(check)
        if pinned == seen:
            continue
        if pinned is None or seen is None:
            moved.append(f"{check}: pinned {pinned or '-'}, observed {seen or '-'}")
        elif check.endswith(".names"):
            moved.append(f"{check}: {_names_moved(pinned, seen)}")
        else:
            opened = _open(check, pinned, kinds), _open(check, seen, kinds)
            moved.append(f"{check}: {_exposure(pinned, seen, *opened)}")
    assert not moved, f"{name} moved from its pins ({where}): {moved}"


@pytest.mark.timeout(300, method="signal")
def test_probe_15_from_a_step_shell(tmp_path: Path, isolated_mock_llm_server_url: str) -> None:
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    review_token = f"review-{uid}-pass"
    tokens = (impl_token, review_token)
    probe_call = f"probe-{uid}"
    api_key = _canary()
    # The implementer's first call waits for its brief; the reviewer's calls are held so
    # it stays mid-turn while the implementer probes.
    sk.queue(mock, impl_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, NOTHING, call_id=f"n-{uid}"))])
    sk.queue(
        mock,
        review_token,
        [sk.held(sk.tool_call(sk.SHELL_TOOL, README, call_id=f"r{n}-{uid}")) for n in range(3)],
    )
    deadline = time.monotonic() + SCENARIO_S

    with sk.skeleton_stack(
        tmp_path / "stack",
        mock_url=mock,
        host_config={"auth": {"type": "api_key", "api_key": api_key.reveal(), "base_url": mock}},
        lease_s=SHORT_LEASE_S,
        repo_files={PROBE.name: PROBE.read_bytes()},
    ) as stack:
        client = stack.client
        home = stack.host.home
        port = stack.server.port
        # Canaries where a step's user keeps credentials. The host holds no tunnel
        # credential on a single-user server, so one is planted where it would be.
        canaries = {
            "credential_files.claude": home / ".claude" / ".credentials.json",
            "credential_files.omnigent_secrets": home / ".omnigent" / "secrets.json",
            "credential_files.host_tunnel": home / ".omnigent" / "auth_tokens.json",
            "bridge_dir": _bridge_root(stack) / f"probe-{uid}" / "token",
        }
        values = {check: _canary() for check in canaries}
        for check, path in canaries.items():
            _plant(path, values[check])
        run_id = sk.start_review_loop(
            stack,
            impl_token=impl_token,
            review_token=review_token,
            start_key=f"probe-{uid}",
            fixture=FIXTURE,
        )
        wait = sk.waiter(stack, run_id, deadline)

        implement = sk.held_activation(wait, mock, impl_token, 1)
        review = sk.held_activation(wait, mock, review_token, 1)
        reviewer = sk.step_session(client, run_id, "review")
        implementer = sk.step_session(client, run_id, "implement")
        runner = sk.runner_pid(stack, reviewer)
        own_runner = sk.runner_pid(stack, implementer)
        harness_socket = _harness_socket(stack, reviewer)
        recorded = _recorded(stack, harness_socket)
        worktree = Path(sk.detail(client, run_id)["target"]["worktree_path"])
        probe_digest = _sha256(PROBE.read_bytes())
        tunnel = canaries.pop("credential_files.host_tunnel")
        config = home / ".omnigent" / "config.yaml"
        # Processes whose environment and command line the step tries to read, with the API
        # key's digest: the reviewer's runner and CLI, the host daemon and the step's own CLI.
        processes = {
            "runner_environ": runner,
            "cli_environ": _session_cli(stack, runner, reviewer),
            "host_environ": stack.host.proc.pid,
            "own_cli_environ": _session_cli(stack, own_runner, implementer),
        }
        proxy, proxy_token = _cli_proxy(processes["own_cli_environ"])
        targets = [
            Target(
                "control_file",
                "file",
                PROBE.name,
                f"sha256:{probe_digest}",
                _file_live(worktree / PROBE.name, probe_digest),
            ),
            Target("control_environ", "environ", "self"),
            Target("control_python", "python", ""),
            Target(
                "harness_socket", "socket", str(harness_socket), live=_socket_live(harness_socket)
            ),
            *(
                Target(check, "environ", str(pid), _digest(api_key), _process_live(pid))
                for check, pid in processes.items()
            ),
            *(
                Target(
                    check,
                    "file",
                    str(path),
                    f"sha256:{_sha256(path.read_bytes())}",
                    _file_live(path, _sha256(path.read_bytes())),
                )
                for check, path in canaries.items()
            ),
            Target(
                "credential_files.host_tunnel",
                "file",
                str(tunnel),
                f"size:{tunnel.stat().st_size}",
                _metadata_live(tunnel),
            ),
            Target(
                "config_api_key", "token", str(config), _digest(api_key), _holds(config, api_key)
            ),
            Target(
                "server_loopback",
                "http",
                f"http://127.0.0.1:{port}/health",
                live=_url_live(f"http://127.0.0.1:{port}/health"),
            ),
            Target(
                "server_localhost",
                "http",
                f"http://localhost:{port}/health",
                live=_url_live(f"http://localhost:{port}/health"),
            ),
            # Live while the host's own bare request acts as the owner.
            *(
                Target(check, "owner_http", url, live=_url_live(url))
                for check, url in _owner_urls(stack).items()
            ),
            Target("shell_env_names", "shell", ""),
            proxy,
        ]
        unproven = _unproven(targets)
        assert not unproven, f"targets without a host-side control: {unproven}"
        misjudged = _misjudged(targets)
        assert not misjudged, f"targets of another kind than their pins: {misjudged}"
        checks = {target.check for target in targets}
        outside_targets = [
            target
            for target in targets
            if target.check.startswith("control_") or target.check in OUTSIDE_PROBE15
        ]
        sk.queue(
            mock,
            impl_token,
            [
                sk.held(sk.tool_call(sk.SHELL_TOOL, _probe_command(targets), call_id=probe_call)),
                # Held until the step's own CLI is checked again: the handoff ends its turn.
                sk.held(
                    sk.handoff_call(implement, call_id=f"done-{uid}", report="Ran the probe.")
                ),
                DONE,
            ],
        )
        # Release in an order that leaves the probe call the oldest held call, with the
        # reviewer held on a newer one; each reviewer round only reads README.md.
        if _release_oldest(wait, mock, tokens) == review_token:
            assert _release_oldest(wait, mock, tokens) == impl_token
        assert _release_oldest(wait, mock, tokens) == review_token

        before = _failed_controls(targets)
        assert not before, f"failed control before the probe: {before}"
        # The same probe outside any sandbox, as the step's user, in the step's worktree:
        # there every process is read, and none holds the API key.
        outside = _run_probe(outside_targets, _probe_env(home), worktree)
        between = _failed_controls(targets)
        release_mock_gate(mock)
        reading = wait(lambda: _read_probe(mock, probe_call, checks), "the probe's result")
        after = _failed_controls(targets)

        sk.queue(
            mock,
            review_token,
            [sk.handoff_call(review, call_id=f"ok-{uid}", report="README.md is unchanged."), DONE],
        )
        # The reviewer's hold, then the implementer's handoff, held since the probe's result.
        release_mock_gate(mock)
        release_mock_gate(mock)
        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        held = {**values, "config_api_key": api_key, "proxy_session_token": proxy_token}
        leaked = _ledger_holds(mock, held)
        forwarded = len(get_mock_message_requests(mock, key=PROXY_PROBE_MODEL))

    # The verdicts first, so a failing run still leaves them: they are tokens and names only.
    observed = _without_controls(reading.verdicts)
    report = {
        "verdicts": observed,
        "outside": _without_controls(outside.verdicts),
        "recorded": recorded,
    }
    written = _write_artifact("probe15", report)
    print(
        f"Probe 15 on {sys.platform}, checkout read grant {recorded['checkout_read_grant']}:",
        json.dumps(report),
    )
    assert not between, f"failed control after the probe ran outside: {between}"
    assert not after, f"failed control after the probe: {after}"
    outside_verdicts = _assert_reading(outside, outside_targets)
    _controls_held(outside_verdicts, "outside the sandbox")
    exposed = _key_exposed_outside(outside_verdicts)
    assert not exposed, f"outside the sandbox: {exposed}"
    verdicts = _assert_reading(reading, targets)
    _controls_held(verdicts)
    # The ledger holds the probe's tokens, never a canary or the CLI's session token, and
    # none of the probe's own requests to the proxy. It records request bodies, not headers:
    # that the token is in no upstream header is the shim's and the executor's unit tests.
    assert not leaked, f"the mock's ledger holds {leaked}"
    assert not forwarded, f"the proxy forwarded {forwarded} request(s) of the probe"
    assert (run["status"], run["causes"]) == ("completed", []), run
    _assert_recorded(recorded)
    _assert_pinned("probe 15", EXPECTED.get(sys.platform, {}), observed, written)


# The server no longer takes this token as runner proof for a Coral session's /mcp calls or
# tunnel, and runners strip it from their children. ``runner.names`` and ``harness.names``
# are ``none``: the host starts its runner zygote from the allow-listed runner environment,
# so a zygote-forked runner and harness never inherit the host's copy.
EXPECTED_TOKEN: dict[str, dict[str, Pin]] = {
    # Pinned from one local run on macOS 27.2.1 with claude 2.1.325 (seatbelt).
    "darwin": {
        "step_runs": Pin("true"),
        "runner_environ": Pin("denied"),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
        # The zygote starts from the allow-listed runner env, so its forks lack the token.
        "runner.names": Pin("none"),
        "harness.names": Pin("none"),
        "launcher.names": Pin("none"),
        "cli.names": Pin("none"),
    },
    # Pinned from lane run 44980984569 on Ubuntu 24.04.5 LTS, claude 2.1.295 (bwrap).
    "linux": {
        "step_runs": Pin("true"),
        "runner_environ": Pin("hidden"),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
        # As on macOS; the same zygote env on both platforms.
        "runner.names": Pin("none"),
        "harness.names": Pin("none"),
        "launcher.names": Pin("none"),
        "cli.names": Pin("none"),
    },
}


@pytest.mark.timeout(300, method="signal")
def test_a_step_on_a_server_with_the_allow_listed_runner_token(
    tmp_path: Path, isolated_mock_llm_server_url: str
) -> None:
    """
    Whether a step runs on a server that keeps the allow-listed runner token, and which
    token names reach its shell, and its runner, harness, launcher and CLI as read from
    outside. A zygote-forked runner's or harness's readable environment is the zygote's,
    which starts from the allow-listed runner environment, so the host's token is not in it.

    Recorded with it: a host ``unknown`` counts as dead, so a relaunch can start while the
    old runner lives on. The server takes the allow-listed token as runner proof only for a
    session that is not Coral's (``mcp_identity.py``).

    The host's credential here is an API key with no endpoint of its own; the host's
    ``ANTHROPIC_BASE_URL`` names the mock. So each step's CLI runs on the direct-key path:
    through its executor's credential proxy, whose upstream is that inherited endpoint.
    Were that endpoint ever lost on the way, the proxy would forward to the Anthropic API:
    every proxy setting of the host names a recorder that refuses, and it must see nothing.
    """
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    review_token = f"review-{uid}-pass"
    probe_call = f"probe-{uid}"
    handed = f"done-{uid}"
    # Per run and held redacted: the server keeps it and the host exports it. Only the
    # stack helpers' frames hold it, so only a start or teardown failure prints it.
    allowlisted = Secret(secrets.token_urlsafe(32))
    # On a key with no gateway the CLI defers its MCP tools, so each step loads them first.
    queue = functools.partial(sk.queue, offering=sk.TOOL_SEARCH)
    first_calls = {
        impl_token: sk.tool_call(sk.SHELL_TOOL, NOTHING, call_id=f"n-{uid}"),
        review_token: sk.tool_call(sk.SHELL_TOOL, README, call_id=f"r-{uid}"),
    }
    for token, call in first_calls.items():
        queue(mock, token, [*sk.load_step_tools(f"s-{token}"), sk.held(call)])
    deadline = time.monotonic() + SCENARIO_S

    with (
        EgressRecorder() as fence,
        sk.skeleton_stack(
            tmp_path / "stack",
            mock_url=mock,
            host_config={"auth": {"type": "api_key", "api_key": "mock-key"}},
            host_env={
                "OMNIGENT_RUNNER_TUNNEL_TOKEN": allowlisted.reveal(),
                "ANTHROPIC_BASE_URL": mock,
                **_fenced(fence.url),
            },
            lease_s=SHORT_LEASE_S,
            allowlisted_token=allowlisted.reveal(),
            repo_files={PROBE.name: PROBE.read_bytes()},
        ) as stack,
    ):
        client = stack.client
        run_id = sk.start_review_loop(
            stack,
            impl_token=impl_token,
            review_token=review_token,
            start_key=f"token-{uid}",
            fixture=FIXTURE,
        )
        wait = sk.waiter(stack, run_id, deadline)
        implement = sk.held_activation(wait, mock, impl_token, 1)
        review = sk.held_activation(wait, mock, review_token, 1)
        implementer = sk.step_session(client, run_id, "implement")
        runner = sk.runner_pid(stack, implementer)
        step = sk.step_processes(runner, _session_cli(stack, runner, implementer))
        # Each was exec'd, or forked from a zygote that was, inside the stack's keychain barrier.
        outside = sk.keychain_bypasses(stack.stubs, stack.root, step.values(), unread_fails=True)
        assert not outside, f"step processes started outside the keychain barrier: {outside}"
        # The stubs' log works: the host's readiness probe asks gh for a token on every platform.
        wait(
            lambda: True if HOST_GH_PROBE in stack.stubs.calls() else None,
            "the host's gh probe to reach the stack's stub",
        )
        recorded = _recorded(stack, _harness_socket(stack, implementer))
        names = {f"{role}.names": _token_names(proc) for role, proc in step.items()}
        # The CLI holds a session token for a loopback proxy of its own, never the mock's URL.
        # Only a launch with no gateway leaves the CLI's experimental betas on (a gateway
        # launch switches them off or names the gateway); a mock upstream is not the
        # Anthropic API, so the CLI is not told to assume it is.
        proxy, _session_token = _cli_proxy(step["cli"].pid)
        cli_names = set(step["cli"].environ())
        direct_key_path = {
            "proxy_is_not_the_mock": proxy.target != str(urllib.parse.urlsplit(mock).port),
            "betas_left_on": "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS" not in cli_names,
            "no_gateway_switch": "CLAUDE_CODE_USE_GATEWAY" not in cli_names,
            "not_assumed_first_party": FIRST_PARTY_FLAG_NAME not in cli_names,
            "fenced": set(_PROXY_NAMES) <= cli_names,
        }
        # The shell's own runner, as the step tries to read it: where the allow-listed token sits.
        targets = [
            Target("control_file", "file", PROBE.name, f"sha256:{_sha256(PROBE.read_bytes())}"),
            Target("control_environ", "environ", "self"),
            Target("control_python", "python", ""),
            Target("runner_environ", "environ", str(runner), live=_process_live(runner)),
            Target("shell_env_names", "shell", ""),
        ]
        unproven = _unproven(targets)
        assert not unproven, f"targets without a host-side control: {unproven}"
        misjudged = _misjudged(targets)
        assert not misjudged, f"targets of another kind than their pins: {misjudged}"
        checks = {target.check for target in targets}
        queue(
            mock,
            impl_token,
            [
                sk.tool_call(sk.SHELL_TOOL, _probe_command(targets), call_id=probe_call),
                # Held until the runner is checked again: the handoff ends its turn.
                sk.held(
                    sk.handoff_call(
                        implement, call_id=handed, report="Ran the environment checks."
                    )
                ),
                DONE,
            ],
        )
        queue(
            mock,
            review_token,
            [sk.handoff_call(review, call_id=f"ok-{uid}", report="README.md is unchanged."), DONE],
        )
        before = _failed_controls(targets)
        assert not before, f"failed control before the probe: {before}"
        # Both first calls; then only the implementer's handoff is held.
        release_mock_gate(mock)
        release_mock_gate(mock)
        reading = wait(lambda: _read_probe(mock, probe_call, checks), "the probe's result")
        after = _failed_controls(targets)
        release_mock_gate(mock)
        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        accepted = sk.result_texts(mock, handed)
        leaked = _ledger_holds(mock, {"allowlisted_token": allowlisted})
        # What the proxy forwarded: the requests as the mock received them.
        betas = {token: _betas_sent(mock, token) for token in (impl_token, review_token)}
        egress = fence.request_lines

    assert not after, f"failed control after the probe: {after}"
    verdicts = _assert_reading(reading, targets)
    _controls_held(verdicts)
    assert not leaked, f"the mock's ledger holds {leaked}"
    assert all(direct_key_path.values()), f"not the direct-key proxy path: {direct_key_path}"
    assert egress == [], f"the stack reached for another machine: {egress}"
    print(
        "anthropic-beta through the proxy:", json.dumps({k: sorted(v) for k, v in betas.items()})
    )
    # Each step's model calls reached the mock, with betas only a launch with no gateway sends.
    beyond_a_gateway = {token: sorted(sent - GATEWAY_PATH_BETAS) for token, sent in betas.items()}
    assert all(beyond_a_gateway.values()), f"no experimental beta reached the mock: {betas}"
    runs = (run["status"], run["causes"]) == ("completed", []) and any(
        '"accepted": true' in text for text in accepted
    )
    observed = {
        "step_runs": str(runs).lower(),
        **{check: token for check, token in verdicts.items() if not check.startswith("control_")},
        **names,
    }
    # Names and counts only: what the stack's processes asked a keychain program for.
    stub_calls = dict(sorted(Counter(stack.stubs.calls()).items()))
    report = {"verdicts": observed, "recorded": recorded, "keychain_stub_calls": stub_calls}
    written = _write_artifact("probe15-token", report)
    print(f"Allow-listed token on {sys.platform}:", json.dumps(report))
    _assert_recorded(recorded)
    pins = EXPECTED_TOKEN.get(sys.platform, {})
    _assert_pinned("the allow-listed-token step", pins, observed, written)


EXPECTED_IDENTITY: dict[str, dict[str, Pin]] = {
    # Pinned from local runs on macOS 27.2.1 with claude 2.1.325 (seatbelt).
    "darwin": {
        "owner_bare": Pin("refused"),
        "owner_bare_localhost": Pin("refused"),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
        "own_runner_environ": Pin("denied"),
        "own_runner_mint.read": Pin("denied"),
        "own_runner_mint": Pin("denied"),
        "own_runner_bearer.read": Pin("denied"),
        "own_runner_bearer": Pin("denied"),
        # The host's environment holds no bearer (outside: not_present); this pins the read.
        "host_bearer.read": Pin("denied"),
        "host_bearer": Pin("denied"),
        "server_environ": Pin("denied"),
        "stored_credentials.read": Pin("denied"),
        "stored_credentials": Pin("denied"),
        "credential_files.cookie_secret": Pin("denied"),
        "other_unix_socket": Pin("reachable", OTHER_PROGRAMS),
        "other_loopback_tcp": Pin("reachable", OTHER_PROGRAMS),
        "worktree_exec_config": Pin("reachable", PLANTED_CONFIG),
        "credential_proxy": Pin("refused"),
    },
    # Measured in lane run 45187294423: bwrap's pid namespace and mounts hide
    # the processes, the homes and /tmp; the network namespace and the worktree are shared.
    "linux": {
        "owner_bare": Pin("refused"),
        "owner_bare_localhost": Pin("refused"),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
        "own_runner_environ": Pin("hidden"),
        "own_runner_mint.read": Pin("hidden"),
        "own_runner_mint": Pin("hidden"),
        "own_runner_bearer.read": Pin("hidden"),
        "own_runner_bearer": Pin("hidden"),
        "host_bearer.read": Pin("hidden"),
        "host_bearer": Pin("hidden"),
        "server_environ": Pin("hidden"),
        "stored_credentials.read": Pin("hidden"),
        "stored_credentials": Pin("hidden"),
        "credential_files.cookie_secret": Pin("hidden"),
        "other_unix_socket": Pin("hidden"),
        "other_abstract_socket": Pin("reachable", OTHER_PROGRAMS),
        "other_loopback_tcp": Pin("reachable", OTHER_PROGRAMS),
        "worktree_exec_config": Pin("reachable", PLANTED_CONFIG),
        # Not measured in a lane yet: set from other_loopback_tcp, reachable in that run, and
        # the proxy's own refusal.
        "credential_proxy": Pin("refused"),
    },
}
# What the run's detail says of its gates on that server: the sandbox still has open paths.
OPEN_SANDBOX_LABEL = {"label": "not_enforced", "reasons": ["host_sandbox_open"]}
RECORDED_IDENTITY: dict[str, dict[str, Any]] = {
    "darwin": {
        **RECORDED["darwin"],
        "server_mode": "accounts",
        "runner_spawn": "direct",
        "sandbox_policy": "1",
        "gate_integrity": OPEN_SANDBOX_LABEL,
    },
    # Measured in lane run 45187294423; its artifact records the OS and CLI versions it ran.
    "linux": {
        "harness_socket_root": "/tmp/crl-*",
        "checkout_read_grant": True,
        "server_mode": "accounts",
        "runner_spawn": "direct",
        "sandbox_policy": "1",
        "gate_integrity": OPEN_SANDBOX_LABEL,
    },
}
# The sandbox backend each platform's pins were measured on.
PINNED_BACKENDS: Mapping[str, str] = MappingProxyType({"darwin": "seatbelt", "linux": "bwrap"})
# What the same probe must find outside any sandbox, in the same stack, right before the
# step runs it: every owner path open, so a closed verdict in the step is the sandbox's.
OUTSIDE_IDENTITY: Mapping[str, str] = MappingProxyType(
    {
        "owner_bare": "refused",
        "owner_bare_localhost": "refused",
        "own_runner_environ": "reachable",
        # The direct-spawned runner's environment is read and holds neither token: they came
        # through its launch socket.
        "own_runner_mint.read": "reachable",
        "own_runner_mint": "not_present",
        "own_runner_bearer.read": "reachable",
        "own_runner_bearer": "not_present",
        # The host daemon's environment is read and holds no bearer: a negative control.
        "host_bearer.read": "reachable",
        "host_bearer": "not_present",
        "server_environ": "reachable",
        "stored_credentials.read": "reachable",
        "stored_credentials": "reachable",
        "credential_files.cookie_secret": "reachable",
        "other_unix_socket": "reachable",
        "other_abstract_socket": "reachable",
        "other_loopback_tcp": "reachable",
        "worktree_exec_config": "reachable",
        # The proxy refuses whoever lacks its session token, sandboxed or not.
        "credential_proxy": "refused",
    }
)
_USED_CREDENTIAL = ("mint", "bearer", "stored")


@contextlib.contextmanager
def _other_programs() -> Iterator[list[Target]]:
    """
    Throwaway same-user services, as another program's would be: a socket at a path no
    harness root names, a loopback TCP port and, on Linux, an abstract socket with a random
    name. Each is a probe target with its host-side control; all are closed on exit.
    """
    directory = Path(tempfile.mkdtemp(dir="/tmp", prefix="crl-o-"))
    path = directory / "agent.sock"
    with contextlib.ExitStack() as listeners:
        listeners.callback(shutil.rmtree, directory, ignore_errors=True)
        unix = listeners.enter_context(socket.socket(socket.AF_UNIX))
        unix.bind(str(path))
        unix.listen()
        port = listeners.enter_context(socket.create_server(("127.0.0.1", 0))).getsockname()[1]
        targets = [
            Target("other_unix_socket", "socket", str(path), live=_socket_live(path)),
            Target(
                "other_loopback_tcp",
                "tcp",
                f"127.0.0.1:{port}",
                live=_listening(socket.AF_INET, ("127.0.0.1", port), "the loopback port"),
            ),
        ]
        if sys.platform == "linux":
            name = f"crl-o-{secrets.token_hex(8)}"
            abstract = listeners.enter_context(socket.socket(socket.AF_UNIX))
            abstract.bind("\0" + name)
            abstract.listen()
            live = _listening(socket.AF_UNIX, "\0" + name, "the abstract socket")
            targets.append(Target("other_abstract_socket", "socket", f"@{name}", live=live))
        yield targets


def _broken_outside(verdicts: Mapping[str, str], targets: list[Target]) -> list[str]:
    """Each owner path the run outside the sandbox did not open, as tokens only."""
    keys = [
        key
        for target in targets
        if not target.check.startswith("control_") and target.kind != "shell"
        for key in (
            (f"{target.check}.read", target.check)
            if target.kind in _USED_CREDENTIAL
            else (target.check,)
        )
    ]
    return [
        f"outside control: {key} is {verdicts.get(key, '-')}"
        for key in keys
        if verdicts.get(key) != OUTSIDE_IDENTITY.get(key)
    ]


@pytest.mark.timeout(300, method="signal")
def test_probe_15_on_a_server_that_requires_identity(
    tmp_path: Path, isolated_mock_llm_server_url: str
) -> None:
    """
    Whether a step on an accounts server can act as its owner: mint an owner JWT with its
    runner's binding token, use the host's bearer or the CLI's stored credentials, call an
    owner route bare, read the server's secrets, reach other programs' services, use its
    own credential proxy without the session token, or plant a repository config the owner's
    git would run. The runner is spawned directly by the host
    daemon, which hands it both tokens through an inherited socket, so its exec-time
    environment holds neither. The same probe runs first outside any sandbox and must open
    every other one of those paths, or the probe is broken rather than the step held.
    """
    sk.require_claude_cli()
    mock = isolated_mock_llm_server_url
    uid = uuid.uuid4().hex[:12]
    impl_token = f"impl-{uid}"
    review_token = f"review-{uid}-pass"
    probe_call = f"probe-{uid}"
    handed = f"done-{uid}"
    cookie_value = _canary()
    sk.queue(mock, impl_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, NOTHING, call_id=f"n-{uid}"))])
    sk.queue(
        mock, review_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, README, call_id=f"r-{uid}"))]
    )
    deadline = time.monotonic() + SCENARIO_S

    with (
        sk.skeleton_stack(
            tmp_path / "stack",
            mock_url=mock,
            host_config=sk.mock_auth(mock),
            # Direct spawn: the runner takes its tokens from a socket, not its exec-time env.
            host_env={"OMNIGENT_RUNNER_ZYGOTE": "0"},
            lease_s=SHORT_LEASE_S,
            repo_files={PROBE.name: PROBE.read_bytes()},
            identity=True,
        ) as stack,
        _other_programs() as other_programs,
    ):
        client = stack.client
        server = stack.server.server
        assert stack.owner_token is not None and server is not None
        home = stack.host.home
        # A canary where an accounts server keeps its cookie secret, in the host's data dir.
        cookie = home / ".omnigent" / "artifacts" / "accounts-cookie-secret"
        _plant(cookie, cookie_value)
        cookie_digest = _sha256(cookie.read_bytes())
        # Written by the stack before the host signed in with it; never read by the test.
        stored = home / ".omnigent" / "auth_tokens.json"
        run_id = sk.start_review_loop(
            stack,
            impl_token=impl_token,
            review_token=review_token,
            start_key=f"identity-{uid}",
            fixture=FIXTURE,
        )
        wait = sk.waiter(stack, run_id, deadline)
        implement = sk.held_activation(wait, mock, impl_token, 1)
        review = sk.held_activation(wait, mock, review_token, 1)
        implementer = sk.step_session(client, run_id, "implement")
        runner = sk.runner_pid(stack, implementer)
        # A directly spawned runner is the daemon's child; a zygote-forked one the zygote's.
        parent = psutil.Process(runner).ppid()
        spawn = "direct" if parent == stack.host.proc.pid else "zygote"
        assert spawn == "direct", f"failed control: the runner's parent {parent} is not the host"
        # Read while the step holds its host: the label the owner's run shows on this server.
        detail = sk.detail(client, run_id)
        recorded = {
            **_recorded(stack, _harness_socket(stack, implementer)),
            "server_mode": "accounts",
            "runner_spawn": spawn,
            # The host runs this checkout, so it reports this revision.
            "sandbox_policy": SANDBOX_POLICY_REVISION,
            "gate_integrity": detail["gate_integrity"],
        }
        worktree = Path(detail["target"]["worktree_path"])
        probe_digest = _sha256(PROBE.read_bytes())
        # Every credential is tried on this server's owner route, and only there.
        on_server = f"{stack.server.base_url} {stack.server.base_url}{sk.RUNS}"
        runner_live = _process_live(runner)
        proxy, proxy_token = _cli_proxy(_session_cli(stack, runner, implementer))
        plant = f"crl-plant-{uid}"
        targets = [
            Target(
                "control_file",
                "file",
                PROBE.name,
                f"sha256:{probe_digest}",
                _file_live(worktree / PROBE.name, probe_digest),
            ),
            Target("control_environ", "environ", "self"),
            Target("control_python", "python", ""),
            # Live while the owner's own JWT is accepted there.
            *(
                Target(check, "owner_http", url, live=_url_live(url, client))
                for check, url in _owner_urls(stack).items()
            ),
            Target("shell_env_names", "shell", ""),
            Target("own_runner_environ", "environ", str(runner), live=runner_live),
            Target("own_runner_mint", "mint", str(runner), on_server, runner_live),
            Target("own_runner_bearer", "bearer", str(runner), on_server, runner_live),
            Target(
                "host_bearer",
                "bearer",
                str(stack.host.proc.pid),
                on_server,
                _process_live(stack.host.proc.pid),
            ),
            Target("server_environ", "environ", str(server.pid), live=_process_live(server.pid)),
            Target("stored_credentials", "stored", str(stored), on_server, _metadata_live(stored)),
            Target(
                "credential_files.cookie_secret",
                "file",
                str(cookie),
                f"sha256:{cookie_digest}",
                _file_live(cookie, cookie_digest),
            ),
            Target("worktree_exec_config", "plant", plant, live=_absent(worktree / plant)),
            *other_programs,
            proxy,
        ]
        unproven = _unproven(targets)
        assert not unproven, f"targets without a host-side control: {unproven}"
        misjudged = _misjudged(targets)
        assert not misjudged, f"targets of another kind than their pins: {misjudged}"
        checks = {target.check for target in targets}
        before = _failed_controls(targets)
        assert not before, f"failed control before the probe: {before}"
        # The same probe outside any sandbox, as the step's user, in the step's worktree.
        outside = _run_probe(targets, _probe_env(home), worktree)
        between = _failed_controls(targets)

        sk.queue(
            mock,
            impl_token,
            [
                sk.tool_call(sk.SHELL_TOOL, _probe_command(targets), call_id=probe_call),
                # Held until the targets are checked again: the handoff ends its turn.
                sk.held(sk.handoff_call(implement, call_id=handed, report="Ran the checks.")),
                DONE,
            ],
        )
        sk.queue(
            mock,
            review_token,
            [sk.handoff_call(review, call_id=f"ok-{uid}", report="README.md is unchanged."), DONE],
        )
        # Both first calls; then only the implementer's handoff is held.
        release_mock_gate(mock)
        release_mock_gate(mock)
        reading = wait(lambda: _read_probe(mock, probe_call, checks), "the probe's result")
        after = _failed_controls(targets)
        release_mock_gate(mock)
        run = wait(lambda: sk.finished(client, run_id), "the run to finish")
        leaked = _ledger_holds(
            mock,
            {
                "owner_token": stack.owner_token,
                "credential_files.cookie_secret": cookie_value,
                "proxy_session_token": proxy_token,
            },
        )
        forwarded = len(get_mock_message_requests(mock, key=PROXY_PROBE_MODEL))

    # The verdicts before any assertion, so a failing run still leaves them for re-pinning or
    # escalation: _parse admits verdict tokens and names only.
    observed = _without_controls(reading.verdicts)
    report = {
        "verdicts": observed,
        "outside": _without_controls(outside.verdicts),
        "recorded": recorded,
    }
    written = _write_artifact("probe15-identity", report)
    print(f"Probe 15 on an accounts server on {sys.platform}:", json.dumps(report))
    assert not between, f"failed control after the probe ran outside: {between}"
    assert not after, f"failed control after the probe: {after}"
    outside_verdicts = _assert_reading(outside, targets)
    _controls_held(outside_verdicts, "outside the sandbox")
    verdicts = _assert_reading(reading, targets)
    _controls_held(verdicts)
    # The ledger holds the probe's tokens, never the owner's JWT, a canary or the CLI's
    # session token, and none of the probe's own requests to the proxy (request bodies only,
    # as above).
    assert not leaked, f"the mock's ledger holds {leaked}"
    assert not forwarded, f"the proxy forwarded {forwarded} request(s) of the probe"
    broken = _broken_outside(outside_verdicts, targets)
    assert not broken, f"broken probe: {broken}"
    assert (run["status"], run["causes"]) == ("completed", []), run
    _assert_recorded(recorded, RECORDED_IDENTITY.get(sys.platform, {}))
    pins = EXPECTED_IDENTITY.get(sys.platform, {})
    _assert_pinned("the identity probe", pins, observed, written)


def _probe_env(home: Path, **extra: str) -> dict[str, str]:
    return {**sk.minimal_env(), "HOME": str(home), **extra}


def _probe_output(targets: list[Target], env: Mapping[str, str], cwd: Path) -> tuple[Secret, int]:
    """The probe's output from a run outside any sandbox, redacted, and its stderr's length."""
    done = subprocess.run(
        ["/bin/sh", str(PROBE), *(target.argument() for target in targets)],
        capture_output=True,
        text=True,
        env=dict(env),
        cwd=cwd,
        # Room for every request of the identity targets to reach its own timeout.
        timeout=120,
        check=False,
    )
    return Secret(done.stdout), len(done.stderr)


def _run_probe(targets: list[Target], env: Mapping[str, str], cwd: Path) -> Reading:
    """
    Run the probe outside any sandbox, its output reduced here as the ledger's is. Outside,
    the probe reads real environments, so its raw output is held redacted in this frame.
    """
    output, stderr_chars = _probe_output(targets, env, cwd)
    verdicts, strays = _parse(output.reveal(), {target.check for target in targets})
    return Reading(verdicts, strays, stderr_chars=stderr_chars)


@contextlib.contextmanager
def _sleeper(env: Mapping[str, str], *argv: str, ready: Path | None = None) -> Iterator[int]:
    """
    A Python child that waits with ``env`` and ``argv``; ended on exit. With ``ready``, it is
    yielded once it has made that file: macOS execs a venv's interpreter twice, and between
    the two the child's environment reads empty.
    """
    code = "import time; time.sleep(60)"
    if ready is not None:
        code = f"import pathlib; pathlib.Path({str(ready)!r}).touch(); {code}"
    child = subprocess.Popen([sys.executable, "-c", code, *argv], env=env)
    try:
        if ready is not None:
            poll_until(ready.exists, interval_s=0.05)
        yield child.pid
    finally:
        terminate_process(child)


class _Quiet(http.server.BaseHTTPRequestHandler):
    """Answers every request with an error status and logs nothing."""

    def log_message(self, *args: Any) -> None:
        del args


@contextlib.contextmanager
def _serving(handler: type[http.server.BaseHTTPRequestHandler]) -> Iterator[str]:
    """A loopback HTTP server with ``handler``; yields its base URL."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextlib.contextmanager
def _served_url() -> Iterator[str]:
    """A loopback HTTP server that answers every request with an error status."""
    with _serving(_Quiet) as base:
        yield f"{base}/health"


@contextlib.contextmanager
def _redirecting(to: str) -> Iterator[str]:
    """A loopback server that redirects every request to the same path on ``to``."""

    class Moved(_Quiet):
        def _moved(self) -> None:
            self.send_response(302)
            self.send_header("Location", f"{to}{self.path}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = do_POST = _moved

    with _serving(Moved) as base:
        yield base


@contextlib.contextmanager
def _owner_server(
    accepted: Collection[Secret], binding: Secret, minted: Secret, stale: Secret
) -> Iterator[tuple[str, list[str]]]:
    """
    A loopback stand-in for an accounts server: the owner route answers 200 only to an
    ``accepted`` bearer or the ``minted`` JWT, and the mint route mints that JWT only for
    ``binding`` at its runner id, and for ``stale`` one the owner route refuses. Yields its
    URL and the digest of every credential sent.
    """
    received: list[str] = []

    class Owner(_Quiet):
        def _credential(self, header: str) -> str:
            value = (self.headers.get(header) or "").removeprefix("Bearer ")
            received.append(_sha256(value.encode()))
            return value

        def _answer(self, status: int, body: bytes = b"") -> None:
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            bearer = self._credential("Authorization")
            owner = bearer in {value.reveal() for value in (*accepted, minted)}
            self._answer(200 if self.path == sk.RUNS and owner else 401)

        def do_POST(self) -> None:
            token = self._credential(RUNNER_TUNNEL_TOKEN_HEADER)
            route = f"/v1/runners/{token_bound_runner_id(token or '-')}/token"
            jwts = {binding.reveal(): minted.reveal(), stale.reveal(): "not-the-owner"}
            if token in jwts and self.path == route:
                self._answer(200, json.dumps({"token": jwts[token]}).encode())
            else:
                self._answer(401)

    with _serving(Owner) as base:
        yield base, received


def _runner_env(home: Path, server: str | None, binding: Secret | None) -> dict[str, str]:
    """
    A runner's exec-time environment holding its tokens, as a CLI-local or Windows runner's
    does, with ``binding`` as both its binding token and its bearer; without one it holds
    neither, and without ``server`` it names no server.
    """
    tokens = {} if binding is None else dict.fromkeys(RUNNER_CREDENTIALS, binding.reveal())
    named = {} if server is None else {"RUNNER_SERVER_URL": server}
    return _probe_env(home, **named, **tokens)


def _stored_file(path: Path, server: str, token: Secret | None) -> Path:
    """Stored credentials in ``omnigent login``'s shape: one entry, for ``server``."""
    entry = {"user_id": "probe-test"} if token is None else {"token": token.reveal()}
    path.write_text(json.dumps({server: entry}))
    return path


def test_the_installed_cli_knows_the_first_party_switch() -> None:
    """
    Behind its proxy a Coral step's CLI on an Anthropic API key keeps its first-party
    behaviour through a private switch of the CLI, so the installed build must name it.
    Here, not beside the executor's unit tests, because this lane installs the pinned CLI.
    """
    sk.require_claude_cli()
    cli = _find_system_claude()
    assert cli is not None, "the executor finds no claude CLI where the stack tests run one"
    assert FIRST_PARTY_FLAG_NAME == _ASSUME_FIRST_PARTY_ENV
    name = FIRST_PARTY_FLAG_NAME.encode()

    def names_it(path: Path) -> bool:
        with path.open("rb") as build, mmap.mmap(build.fileno(), 0, access=mmap.ACCESS_READ) as m:
            return m.find(name) != -1

    files = [path for path in _cli_build_files(Path(cli).resolve()) if path.stat().st_size]
    assert any(names_it(path) for path in files), (
        f"{FIRST_PARTY_FLAG_NAME} is not in the installed claude CLI "
        f"({sorted({path.name for path in files})}): a Coral step on an Anthropic API key "
        "would lose the CLI's first-party behaviour behind its proxy"
    )


def test_the_probe_classifies_files_and_tokens(tmp_path: Path) -> None:
    value = _canary()
    held = tmp_path / "held"
    _plant(held, value)
    other = tmp_path / "other"
    other.write_text("other")
    locked = tmp_path / "locked"
    locked.write_text("locked")
    locked.chmod(0)
    digest = f"sha256:{_sha256(held.read_bytes())}"
    targets = [
        Target("same", "file", str(held), digest),
        Target("changed", "file", str(other), digest),
        Target("gone", "file", str(tmp_path / "gone"), digest),
        Target("locked", "file", str(locked), digest),
        Target("sized", "file", str(held), f"size:{held.stat().st_size}"),
        Target("directory", "file", str(tmp_path), digest),
        Target("token", "token", str(held), _digest(value)),
        Target("other_token", "token", str(other), _digest(value)),
        Target("unknown_kind", "teleport", ""),
    ]

    reading = _run_probe(targets, _probe_env(tmp_path), tmp_path)

    assert _assert_reading(reading, targets) == {
        "same": "reachable",
        "changed": "mismatch",
        "gone": "hidden",
        "locked": "denied",
        "sized": "reachable",
        "directory": "unclassified",
        "token": "reachable",
        "other_token": "mismatch",
        "unknown_kind": "unclassified",
    }


def test_the_probe_classifies_sockets_and_urls(tmp_path: Path) -> None:
    # Short, to stay within the AF_UNIX path limit.
    short = Path(tempfile.mkdtemp(dir="/tmp", prefix="crl-p-"))
    try:
        plain = short / "plain"
        plain.write_text("")
        with (
            socket.socket(socket.AF_UNIX) as listening,
            socket.socket(socket.AF_UNIX) as bound,
            socket.socket(socket.AF_UNIX) as abstract,
            socket.create_server(("127.0.0.1", 0)) as port,
            _served_url() as url,
        ):
            listening.bind(str(short / "live.sock"))
            listening.listen()
            bound.bind(str(short / "stale.sock"))
            targets = [
                Target("live", "socket", str(short / "live.sock")),
                Target("stale", "socket", str(short / "stale.sock")),
                Target("missing", "socket", str(short / "missing.sock")),
                Target("not_a_socket", "socket", str(plain)),
                Target("no_abstract_name", "socket", f"@crl-p-{secrets.token_hex(8)}"),
                Target("served", "http", url),
                Target("closed_port", "http", f"http://127.0.0.1:{find_free_port()}/health"),
                Target("tcp_live", "tcp", f"127.0.0.1:{port.getsockname()[1]}"),
                Target("tcp_closed", "tcp", f"127.0.0.1:{find_free_port()}"),
            ]
            # Linux only: elsewhere an @name is no address at all, so it reads as hidden.
            if sys.platform == "linux":
                name = f"crl-p-{secrets.token_hex(8)}"
                abstract.bind("\0" + name)
                abstract.listen()
                targets.append(Target("abstract_live", "socket", f"@{name}"))
            reading = _run_probe(targets, _probe_env(tmp_path), tmp_path)
    finally:
        shutil.rmtree(short, ignore_errors=True)

    assert _assert_reading(reading, targets) == {
        "live": "reachable",
        "stale": "unclassified",
        "missing": "hidden",
        "not_a_socket": "unclassified",
        "no_abstract_name": "hidden",
        "served": "reachable",
        "closed_port": "hidden",
        "tcp_live": "reachable",
        "tcp_closed": "hidden",
        **({"abstract_live": "reachable"} if sys.platform == "linux" else {}),
    }


@contextlib.contextmanager
def _model_upstream(admitted: Collection[str] | None = None) -> Iterator[tuple[int, list[Any]]]:
    """
    A loopback stand-in for a model endpoint: answers 200 to a POST on an ``admitted`` path
    (any path when ``None``), else 401. Yields its port and, per request, the path, whether a
    key came with it, and the model it named.
    """
    received: list[Any] = []

    class Upstream(_Quiet):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            keyed = self.headers.get("x-api-key") is not None
            received.append((self.path, keyed, body.get("model")))
            self.send_response(200 if admitted is None or self.path in admitted else 401)
            self.send_header("Content-Length", "0")
            self.end_headers()

    with _serving(Upstream) as base:
        yield urllib.parse.urlsplit(base).port or 0, received


def test_the_probe_reads_a_proxy_as_refused_only_when_every_request_is(tmp_path: Path) -> None:
    climbing = "/v1/models/../messages"
    with (
        _model_upstream(()) as (shut, seen),
        _model_upstream((climbing,)) as (climbed, _),
        _model_upstream() as (admitting, _),
        _served_url() as other,
    ):
        targets = [
            Target("shut", "credential_proxy", str(shut)),
            Target("climbed", "credential_proxy", str(climbed)),
            Target("admitting", "credential_proxy", str(admitting)),
            Target("another_server", "credential_proxy", str(urllib.parse.urlsplit(other).port)),
            Target("closed_port", "credential_proxy", str(find_free_port())),
        ]
        reading = _run_probe(targets, _probe_env(tmp_path), tmp_path)

    assert _assert_reading(reading, targets) == {
        "shut": "refused",
        "climbed": "reachable",
        "admitting": "reachable",
        "another_server": "unclassified",
        "closed_port": "hidden",
    }
    # No key, a wrong key, and a path that climbs to the model route with it.
    assert seen == [
        ("/v1/messages", False, PROXY_PROBE_MODEL),
        ("/v1/messages", True, PROXY_PROBE_MODEL),
        (climbing, True, PROXY_PROBE_MODEL),
    ]


async def test_a_credential_proxy_refuses_the_probe_and_forwards_none_of_it(
    tmp_path: Path,
) -> None:
    """
    The executor's real proxy in front of a stand-in upstream: holding a credential it
    refuses all three of the probe's requests and the upstream sees none; the same shim
    without one forwards them, so the refusal is the proxy's.
    """
    credential = UpstreamCredential(
        f"printf %s sk-ant-test-{secrets.token_hex(16)}", ttl_s=None, env={}
    )
    with _model_upstream() as (port, seen):
        upstream = f"http://127.0.0.1:{port}"
        proxy, plain = (
            ClaudeGatewayShim(upstream, credential=credential),
            ClaudeGatewayShim(upstream),
        )
        try:
            await proxy.start()
            await plain.start()
            ports = {
                name: str(urllib.parse.urlsplit(shim.base_url).port)
                for name, shim in (("proxy", proxy), ("plain", plain))
            }
            guarded = [Target("credential_proxy", "credential_proxy", ports["proxy"])]
            reading = await asyncio.to_thread(_run_probe, guarded, _probe_env(tmp_path), tmp_path)
            forwarded = len(seen)
            unguarded = [Target("credential_proxy", "credential_proxy", ports["plain"])]
            control = await asyncio.to_thread(
                _run_probe, unguarded, _probe_env(tmp_path), tmp_path
            )
        finally:
            await proxy.aclose()
            await plain.aclose()

    assert _assert_reading(reading, guarded) == {"credential_proxy": "refused"}
    assert forwarded == 0
    assert _assert_reading(control, unguarded) == {"credential_proxy": "reachable"}
    assert [model for _, _, model in seen] == [PROXY_PROBE_MODEL] * 3


def test_the_probe_acts_as_the_owner_only_with_a_credential(tmp_path: Path) -> None:
    # The server would take ``relayed`` as the owner, were it ever forwarded by a redirect.
    owner, binding, minted, relayed = (Secret(secrets.token_urlsafe(24)) for _ in range(4))
    # One the server refuses, one for another server, which must never be sent, and one
    # that mints a JWT the owner route refuses.
    wrong, foreign, stale = (Secret(secrets.token_urlsafe(24)) for _ in range(3))
    elsewhere = f"http://127.0.0.1:{find_free_port()}"
    ended = subprocess.Popen([sys.executable, "-c", ""])
    ended.wait()
    locked = _stored_file(tmp_path / "locked.json", elsewhere, None)
    locked.chmod(0)
    # The binding token doubles as the bearer, which the server takes as the owner.
    with (
        _owner_server((owner, binding, relayed), binding, minted, stale) as (base, received),
        _redirecting(base) as moved,
    ):
        runners = {
            "held": (base, binding),
            "refused": (base, wrong),
            "stale": (base, stale),
            # A reused pid: a runner of another server, whose tokens stay unsent.
            "reused": (elsewhere, foreign),
            # Tokens in an environment that names no server stay unsent too.
            "unnamed": (None, foreign),
            "bare": (base, None),
        }
        stored = {
            # The entry's key as a user may have typed it, with a trailing slash.
            "stored": _stored_file(tmp_path / "held.json", f"{base}/", owner),
            "stored_refused": _stored_file(tmp_path / "refused.json", base, wrong),
            "stored_elsewhere": _stored_file(tmp_path / "elsewhere.json", elsewhere, foreign),
            "stored_empty": _stored_file(tmp_path / "empty.json", base, None),
            "stored_locked": locked,
            "stored_missing": tmp_path / "missing.json",
        }
        on_server = f"{base} {base}{sk.RUNS}"
        with contextlib.ExitStack() as children:
            pids = {
                name: children.enter_context(_sleeper(_runner_env(tmp_path, *runner)))
                for name, runner in runners.items()
            }
            pids["ended"] = ended.pid
            # An environment without PATH or HOME counts as not read: its tokens go unused.
            pids["pathless"] = children.enter_context(
                _sleeper(
                    {
                        "RUNNER_SERVER_URL": base,
                        **dict.fromkeys(RUNNER_CREDENTIALS, binding.reveal()),
                    }
                )
            )
            redirected = children.enter_context(_sleeper(_runner_env(tmp_path, moved, relayed)))
            on_moved = f"{moved} {moved}{sk.RUNS}"
            targets = [
                Target("owner", "owner_http", f"{base}{sk.RUNS}"),
                Target("owner_closed", "owner_http", f"{elsewhere}{sk.RUNS}"),
                *(
                    Target(f"{kind}_{name}", kind, str(pid), on_server)
                    for kind in ("mint", "bearer")
                    for name, pid in pids.items()
                ),
                *(Target(name, "stored", str(path), on_server) for name, path in stored.items()),
                # A server that redirects gets no answer through: the credential stays put.
                *(
                    Target(f"{kind}_redirected", kind, str(redirected), on_moved)
                    for kind in ("mint", "bearer")
                ),
                Target(
                    "stored_redirected",
                    "stored",
                    str(_stored_file(tmp_path / "moved.json", moved, relayed)),
                    on_moved,
                ),
            ]
            reading = _run_probe(targets, _probe_env(tmp_path), tmp_path)

    verdicts = _assert_reading(reading, targets)
    used = {
        "mint_held": "minted",
        "bearer_held": "reachable",
        **dict.fromkeys(
            ("mint_refused", "bearer_refused", "mint_stale", "bearer_stale", "stored_refused"),
            "refused",
        ),
        **dict.fromkeys(
            ("mint_reused", "bearer_reused", "mint_unnamed", "bearer_unnamed", "stored_elsewhere"),
            "mismatch",
        ),
        **dict.fromkeys(("mint_bare", "bearer_bare", "stored_empty"), "not_present"),
        **dict.fromkeys(
            ("mint_redirected", "bearer_redirected", "stored_redirected"), "unclassified"
        ),
        "stored": "reachable",
    }
    unread = {
        "mint_ended": "hidden",
        "bearer_ended": "hidden",
        "mint_pathless": "denied",
        "bearer_pathless": "denied",
        "stored_locked": "denied",
        "stored_missing": "hidden",
    }
    assert verdicts == {
        "owner": "refused",
        "owner_closed": "hidden",
        **used,
        **{f"{check}.read": "reachable" for check in used},
        **unread,
        **{f"{check}.read": verdict for check, verdict in unread.items()},
    }
    # Closed are a bare request and a failed read; a credential read is open whatever followed.
    kinds = {target.check: target.kind for target in targets}
    assert {check for check, verdict in verdicts.items() if not _open(check, verdict, kinds)} == {
        "owner",
        "owner_closed",
        *unread,
        *(f"{check}.read" for check in unread),
    }
    assert _sha256(wrong.reveal().encode()) in received
    assert _sha256(foreign.reveal().encode()) not in received
    assert _sha256(relayed.reveal().encode()) not in received


def test_the_probe_plants_a_repository_config_and_removes_it(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    taken = tmp_path / "taken"
    taken.mkdir()
    targets = [
        # Relative to the shell's directory, as in a step's worktree.
        Target("planted", "plant", "fresh"),
        Target("absolute", "plant", str(tmp_path / "absolute")),
        Target("locked", "plant", str(locked / "fresh")),
        Target("no_parent", "plant", str(tmp_path / "missing" / "fresh")),
        # Never written into: a path already there.
        Target("taken", "plant", str(taken)),
    ]
    # macOS only: / is a read-only volume, so the write fails with EROFS.
    if sys.platform == "darwin":
        targets.append(Target("read_only", "plant", f"/crl-plant-{secrets.token_hex(8)}"))

    reading = _run_probe(targets, _probe_env(tmp_path), tmp_path)

    assert _assert_reading(reading, targets) == {
        "planted": "reachable",
        "absolute": "reachable",
        "locked": "denied",
        "no_parent": "hidden",
        "taken": "unclassified",
        **({"read_only": "denied"} if sys.platform == "darwin" else {}),
    }
    assert sorted(path.name for path in tmp_path.iterdir()) == ["locked", "taken"]
    assert not any(taken.iterdir())


def test_git_takes_the_planted_directory_as_a_repository_that_names_its_hook(
    tmp_path: Path,
) -> None:
    stub, kept, target = tmp_path / "stub", tmp_path / "kept", tmp_path / "work" / "fresh"
    for directory in (stub, kept, target.parent):
        directory.mkdir()
    # The probe removes what it plants; this rm keeps a copy first.
    (stub / "rm").write_text(
        f'#!/bin/sh\nfor last; do :; done\ncp -R "$last" {shlex.quote(str(kept))}\n'
        'exec /bin/rm "$@"\n'
    )
    (stub / "rm").chmod(0o700)
    env = _probe_env(tmp_path, PATH=f"{stub}{os.pathsep}{sk.minimal_env()['PATH']}")
    targets = [Target("planted", "plant", str(target))]

    reading = _run_probe(targets, env, tmp_path)

    assert _assert_reading(reading, targets) == {"planted": "reachable"}
    assert not target.exists()
    planted = kept / target.name
    # No enclosing repository, system or global config.
    git_env = _probe_env(
        tmp_path,
        GIT_CEILING_DIRECTORIES=str(kept),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )

    def git(*argv: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(planted), *argv],
            env=git_env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done.stdout.strip()

    # The owner's git reads the hook only from a .git it takes as a repository.
    git_dir = git("rev-parse", "--absolute-git-dir")
    assert git_dir, "git takes the planted directory as no repository"
    assert Path(git_dir).resolve() == (planted / ".git").resolve()
    assert git("config", "core.fsmonitor") == str(target / "fsmonitor-hook")
    assert os.access(planted / "fsmonitor-hook", os.X_OK)


def test_the_probe_finds_the_canary_in_environments_and_command_lines(tmp_path: Path) -> None:
    in_environ, in_argv = _canary(), _canary()
    names = "OMNIGENT_RUNNER_TUNNEL_TOKEN,PROBE_TEST_API_KEY"
    ended = subprocess.Popen([sys.executable, "-c", ""])
    ended.wait()
    with (
        _sleeper(
            _probe_env(
                tmp_path,
                PROBE_TEST_API_KEY=in_environ.reveal(),
                OMNIGENT_RUNNER_TUNNEL_TOKEN="test-only",
            ),
            in_argv.reveal(),
        ) as child,
        _sleeper({"PROBE_TEST": "1"}) as bare,
    ):
        targets = [
            Target("control_environ", "environ", "self"),
            Target("by_environ", "environ", str(child), _digest(in_environ)),
            Target("by_argv", "environ", str(child), _digest(in_argv)),
            Target("names_only", "environ", str(child)),
            Target("bare", "environ", str(bare), _digest(in_environ)),
            Target("ended", "environ", str(ended.pid), _digest(in_environ)),
        ]
        reading = _run_probe(targets, _probe_env(tmp_path), tmp_path)

    assert _assert_reading(reading, targets) == {
        "control_environ": "reachable",
        "control_environ.names": CONTROL_NAME,
        "control_environ.api_key": "reachable",
        "control_environ.argv_api_key": "reachable",
        "by_environ": "reachable",
        "by_environ.names": names,
        "by_environ.api_key": "reachable",
        "by_environ.argv_api_key": "not_present",
        "by_argv": "reachable",
        "by_argv.names": names,
        "by_argv.api_key": "not_present",
        "by_argv.argv_api_key": "reachable",
        "names_only": "reachable",
        "names_only.names": names,
        # Neither PATH nor HOME: the environment counts as not read.
        "bare": "denied",
        "bare.api_key": "denied",
        "bare.argv_api_key": "not_present",
        "ended": "hidden",
        "ended.api_key": "hidden",
        "ended.argv_api_key": "hidden",
    }


def test_the_shell_check_needs_path_among_the_names_it_reads(tmp_path: Path) -> None:
    targets = [Target("shell_env_names", "shell", "")]

    exposed = _run_probe(targets, _probe_env(tmp_path, PROBE_TEST_API_KEY="test-only"), tmp_path)
    # Credential-like by any of the name's parts, in any case.
    widened = dict.fromkeys(
        (
            "OMNIGENT_REMOTE_AUTH_TOKEN",
            "OMNIGENT_OIDC_COOKIE_SECRET",
            "DB_PASSWORD",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "ssh_private_key",
        ),
        "test-only",
    )
    named = _run_probe(targets, _probe_env(tmp_path, **widened), tmp_path)
    clean = _run_probe(targets, _probe_env(tmp_path), tmp_path)
    pathless = _run_probe(targets, {"HOME": str(tmp_path)}, tmp_path)

    assert _assert_reading(exposed, targets) == {
        "shell_env_names": "reachable",
        "shell_env_names.names": "PROBE_TEST_API_KEY",
    }
    assert _assert_reading(named, targets) == {
        "shell_env_names": "reachable",
        "shell_env_names.names": ",".join(sorted(widened)),
    }
    # A step's shell gets only Omnigent's default names, none credential-like: the pinned
    # not_present holds until a spec passes a credential through.
    assert not [name for name in _DEFAULT_ENV_PASSTHROUGH if _SENSITIVE_NAME.match(name)]
    assert _assert_reading(clean, targets) == {
        "shell_env_names": "not_present",
        "shell_env_names.names": "none",
    }
    assert _assert_reading(pathless, targets) == {"shell_env_names": "unclassified"}
    with pytest.raises(AssertionError, match=r"could not classify \['shell_env_names'\]"):
        _controls_held({**dict.fromkeys(CONTROLS, "reachable"), **pathless.verdicts})


def test_lines_that_are_not_verdict_tokens_count_only_as_strays() -> None:
    targets = [Target("env", "environ", "1"), Target("file", "file", "f")]
    output = "\n".join(
        [
            "env=reachable",
            "env.names=OMNIGENT_RUNNER_TUNNEL_TOKEN,X_API_KEY",
            "env.api_key=not_present",
            "file=denied",
            "file=reachable",
            "NAME=value",
            "other=reachable",
            "env.argv_api_key=blocked",
            "file.names=AKIAEXAMPLEVALUE",
            "env.names.extra=none",
            "a debug line",
        ]
    )

    verdicts, strays = _parse(output, {target.check for target in targets})

    assert verdicts == {
        "env": "reachable",
        "env.names": "OMNIGENT_RUNNER_TUNNEL_TOKEN,X_API_KEY",
        "env.api_key": "not_present",
        "file": "denied",
    }
    assert strays == 7
    with pytest.raises(AssertionError, match=r"printed 7 line\(s\)") as failed:
        _assert_reading(Reading(verdicts, strays), targets)
    assert "AKIA" not in str(failed.value) and "value" not in str(failed.value)
    with pytest.raises(AssertionError, match=r"no verdict for \['file'\]"):
        _assert_reading(Reading({"env": "reachable"}, 0), targets)


def test_the_pin_comparator_names_owners_and_directions() -> None:
    kinds = {"socket": "socket", "file": "file", "env": "environ", "mint": "mint", "new": "file"}
    pins = {
        "socket": Pin("reachable", OTHER_PROGRAMS),
        "file": Pin("denied"),
        "env.names": Pin("A_API_KEY,B_API_KEY", OTHER_PROGRAMS),
        "mint.read": Pin("denied"),
        "mint": Pin("denied"),
    }
    same = {check: pin.verdict for check, pin in pins.items()}
    _assert_pinned("synthetic", pins, same, None, kinds)

    for owner in (None, "", "  "):
        with pytest.raises(AssertionError, match=r"\['socket: open without an owner ticket'\]"):
            unowned = {**pins, "socket": Pin("reachable", owner)}
            _assert_pinned("synthetic", unowned, same, None, kinds)
    with pytest.raises(AssertionError, match=r"\['file: closed with an owner ticket'\]"):
        _assert_pinned("synthetic", {**pins, "file": Pin("denied", "CRL-1")}, same, None, kinds)
    # A credential read is open whatever its use gave; a check of no known kind is open.
    for check, pin in (
        ("mint.read", Pin("reachable")),
        ("mint", Pin("refused")),
        ("x", Pin("denied")),
    ):
        with pytest.raises(AssertionError, match=rf"\['{check}: open without an owner ticket'\]"):
            _assert_pinned("synthetic", {**pins, check: pin}, same, None, kinds)
    with pytest.raises(AssertionError, match="synthetic is not pinned"):
        _assert_pinned("synthetic", {}, same, None, kinds)
    moved = {
        "socket": "denied",
        "file": "reachable",
        "env.names": "A_API_KEY,C_API_KEY",
        "mint.read": "reachable",
        "mint": "not_present",
    }
    with pytest.raises(AssertionError) as failed:
        _assert_pinned("synthetic", pins, {**moved, "new": "hidden"}, None, kinds)
    message = str(failed.value)
    assert "socket: reachable -> denied: the step reaches less; re-pin" in message
    assert "file: denied -> reachable reads as an exposure" in message
    assert "mint.read: denied -> reachable reads as an exposure" in message
    assert "mint: denied -> not_present reads as an exposure" in message
    assert (
        "env.names: exposure, new names ['C_API_KEY']; reduction, names gone ['B_API_KEY']"
        in message
    )
    assert "new: pinned -, observed hidden" in message


def test_a_removed_target_or_a_dropped_control_fails_as_a_failed_control(tmp_path: Path) -> None:
    canary = tmp_path / "canary"
    _plant(canary, _canary())
    targets = [
        Target("file", "file", str(canary), live=_file_live(canary, _sha256(canary.read_bytes())))
    ]
    assert _failed_controls(targets) == []

    canary.unlink()

    assert _failed_controls(targets) == ["file: canary: FileNotFoundError"]
    held = dict.fromkeys(CONTROLS, "reachable")
    del held["control_environ"]
    with pytest.raises(AssertionError, match=r"in the step: \{'control_environ': None\}"):
        _controls_held(held)
    with pytest.raises(AssertionError, match=r"control outside the sandbox: \{'control_environ'"):
        _controls_held(held, "outside the sandbox")
    assert _unproven([*targets, Target("runner_environ", "environ", "1")]) == ["runner_environ"]
    assert (
        _unproven([Target("control_environ", "environ", "self"), Target("s", "shell", "")]) == []
    )
    misfiled = [Target("harness_socket", "file", "x"), Target("control_file", "file", "x")]
    assert _misjudged(misfiled) == ["harness_socket"]


def test_every_pin_names_an_owner_exactly_when_it_is_open() -> None:
    tables = {
        "probe 15": EXPECTED,
        "the allow-listed-token step": EXPECTED_TOKEN,
        "the identity probe": EXPECTED_IDENTITY,
    }
    every = [
        (f"{name} on {system}", pins)
        for name, table in tables.items()
        for system, pins in table.items()
    ]
    unknown = {
        where: sorted(check for check in pins if _split_check(check)[0] not in PIN_KINDS)
        for where, pins in every
    }
    assert not {where: checks for where, checks in unknown.items() if checks}
    problems = {where: _owner_problems(pins) for where, pins in every}
    assert not {where: found for where, found in problems.items() if found}
    owners = {pin.owner for _, pins in every for pin in pins.values()}
    assert "CRL-159" not in owners
    for system, pins in EXPECTED_IDENTITY.items():
        # Nothing mints, no owner route answers a bare request, and no residual is accepted.
        assert "minted" not in {pin.verdict for pin in pins.values()}, system
        bare = {pins["owner_bare"].verdict, pins["owner_bare_localhost"].verdict}
        assert bare == {"refused"}, system
        assert ACCEPTED_SINGLE_USER not in {pin.owner for pin in pins.values()}, system
        assert RECORDED_IDENTITY[system]["server_mode"] == "accounts", system


def _open_owners(pins: Mapping[str, Pin]) -> set[str | None]:
    """The owner of every pin that is open; an open pin with none counts as ``None``."""
    return {pin.owner for check, pin in pins.items() if _open(check, pin.verdict)}


def _unbound(
    owners: Collection[str | None], blockers: SandboxBlockers, declared: Collection[str]
) -> list[str]:
    """
    How the label's table for one sandbox fails its pins: an open pin's owner it lacks, or,
    once each owner is taken out once, anything but the declared blockers left over.
    """
    table = Counter((*blockers.probed, *blockers.unprobed))
    problems = [
        f"no table entry for open pins of {owner}"
        for owner in sorted(owners, key=str)
        if owner not in table
    ]
    left = table - Counter(owner for owner in owners if owner in table)
    if left != Counter(declared):
        problems.append(f"after the pins' owners the table holds {sorted(left.elements())}")
    return problems


def test_the_gate_label_table_holds_every_open_pin_owner_and_the_declared_blockers() -> None:
    """
    The current revision's rows, against the pins; older revisions' rows stay as recorded
    (``tests/coral/gates/test_integrity.py``), so a moved pin needs a new revision.
    """
    assert set(EXPECTED_IDENTITY) == set(PINNED_BACKENDS)
    # Every row at the current revision is a pinned platform's: none is bound by nothing.
    current = {policy for policy in GATE_BLOCKERS if policy.revision == SANDBOX_POLICY_REVISION}
    pinned = {
        HostSandboxPolicy(backend, SANDBOX_POLICY_REVISION) for backend in PINNED_BACKENDS.values()
    }
    assert current == pinned
    for system, backend in PINNED_BACKENDS.items():
        identity = EXPECTED_IDENTITY[system]
        # A single-user residual is a server-mode fact: it never excuses an identity pin.
        assert ACCEPTED_SINGLE_USER not in {pin.owner for pin in identity.values()}, system
        revision = RECORDED_IDENTITY[system]["sandbox_policy"]
        assert revision == SANDBOX_POLICY_REVISION, f"{system} is pinned at policy {revision}"
        others = (_open_owners(table[system]) for table in (EXPECTED, EXPECTED_TOKEN))
        owners = _open_owners(identity).union(*others) - {ACCEPTED_SINGLE_USER}
        policy = HostSandboxPolicy(backend, revision)
        assert policy in GATE_BLOCKERS, f"no gate label table for {system}'s pins"
        problems = _unbound(owners, GATE_BLOCKERS[policy], UNPROBED_BLOCKERS[policy])
        assert not problems, f"{system}: {problems}"


def test_the_table_binding_fails_when_the_table_and_the_pins_part() -> None:
    owners = {OTHER_PROGRAMS, PLANTED_CONFIG}
    declared = ("CRL-170", PLANTED_CONFIG)
    bound = SandboxBlockers(probed=(OTHER_PROGRAMS, PLANTED_CONFIG), unprobed=declared)
    assert _unbound(owners, bound, declared) == []
    # The table emptied while a pin is still open.
    emptied = SandboxBlockers(probed=(PLANTED_CONFIG,), unprobed=declared)
    assert _unbound(owners, emptied, declared) == [
        f"no table entry for open pins of {OTHER_PROGRAMS}"
    ]
    assert _unbound(owners, SandboxBlockers((), ()), declared) == [
        f"no table entry for open pins of {OTHER_PROGRAMS}",
        f"no table entry for open pins of {PLANTED_CONFIG}",
        "after the pins' owners the table holds []",
    ]
    # A pin re-pinned closed while the table still names its owner.
    assert _unbound({PLANTED_CONFIG}, bound, declared) == [
        "after the pins' owners the table holds ['CRL-170', 'CRL-174', 'CRL-181']"
    ]
    # A declared blocker dropped from the table, though its pin is open too.
    dropped = SandboxBlockers(probed=(OTHER_PROGRAMS, PLANTED_CONFIG), unprobed=("CRL-170",))
    assert _unbound(owners, dropped, declared) == [
        "after the pins' owners the table holds ['CRL-170']"
    ]
    # An open pin with no owner is never in the table.
    assert _unbound({None}, bound, declared)[0] == "no table entry for open pins of None"


def test_only_a_reach_that_failed_reads_as_closed() -> None:
    # What the probe read, minted, found for another value or could not classify is open.
    opened = ("reachable", "minted", "mismatch", "unclassified")
    for kind in CLOSED:
        assert all(_open("check", verdict, {"check": kind}) for verdict in opened), kind
    # A sub-check that read something is open whatever it found there.
    read = (*opened, "not_present", "refused")
    for suffix in (".read", ".api_key", ".argv_api_key"):
        assert all(_open(f"check{suffix}", verdict, {"check": "mint"}) for verdict in read), suffix
    # Refused is closed only for a request with no credential, to an owner route or to the
    # credential proxy; not_present only for the shell's names.
    refusing = ["owner_http", "credential_proxy"]
    for verdict, kinds in (("refused", refusing), ("not_present", ["shell"])):
        assert [kind for kind in CLOSED if not _open("check", verdict, {"check": kind})] == kinds
    # A check of no known kind is open, its sub-checks included.
    assert all(_open(check, "denied", {}) for check in ("check", "check.read", "check.names"))


def test_the_outside_run_must_open_every_owner_path_it_is_given() -> None:
    targets = [
        Target("control_file", "file", PROBE.name),
        Target("shell_env_names", "shell", ""),
        Target("own_runner_mint", "mint", "1"),
        Target("stored_credentials", "stored", "auth_tokens.json"),
        Target("owner_bare", "owner_http", "http://127.0.0.1:1/v1/coral/runs"),
        Target("other_unix_socket", "socket", "agent.sock"),
        Target("worktree_exec_config", "plant", "crl-plant"),
    ]
    keys = (
        "own_runner_mint.read",
        "own_runner_mint",
        "stored_credentials.read",
        "stored_credentials",
        "owner_bare",
        "other_unix_socket",
        "worktree_exec_config",
    )
    required = {key: OUTSIDE_IDENTITY[key] for key in keys}
    assert _broken_outside({**required, "control_file": "denied"}, targets) == []
    # A path the probe did not open outside, a credential's read included, is a broken probe.
    for key in keys:
        assert _broken_outside({**required, key: "denied"}, targets) == [
            f"outside control: {key} is denied"
        ]
    assert _broken_outside({}, targets) == [f"outside control: {key} is -" for key in keys]
    # Outside, every owner path is open but the bare owner routes and the credential proxy,
    # which must refuse a caller with no credential.
    shut = {key for key, verdict in OUTSIDE_IDENTITY.items() if not _open(key, verdict)}
    assert shut == {"owner_bare", "owner_bare_localhost", "credential_proxy"}


def test_the_outside_run_of_probe_15_must_read_every_process_and_find_no_key() -> None:
    names = f"CLAUDE_CODE_API_KEY_HELPER_TTL_MS,{PROXY_TOKEN_NAME}"
    held = {**OUTSIDE_PROBE15, "cli_environ.names": names, "own_cli_environ.names": names}
    assert _key_exposed_outside(held) == []
    assert set(OUTSIDE_PROBE15) == {
        *(f"{check}{suffix}" for check in OUTSIDE_PROCESSES for suffix in ("", *SUB_CHECKS[1:3])),
        "credential_proxy",
    }
    # A process the probe could not read outside proves nothing about its key.
    for key in OUTSIDE_PROBE15:
        moved = "reachable" if OUTSIDE_PROBE15[key] != "reachable" else "denied"
        assert _key_exposed_outside({**held, key: moved}) == [f"{key} is {moved}"]
    with_config = {**held, "cli_environ.names": f"HARNESS_CLAUDE_SDK_MODEL,{names}"}
    assert _key_exposed_outside(with_config) == ["cli_environ holds ['HARNESS_CLAUDE_SDK_MODEL']"]
    assert _key_exposed_outside({**held, "own_cli_environ.names": "none"}) == [
        f"own_cli_environ holds no {PROXY_TOKEN_NAME}"
    ]


# A child pytest run: an identity stack fails to start at each point after its secrets
# exist, under CI's report flags. Its secrets and the owner's JWT carry the leak marker.
_STACK_FAILURES = """
import contextlib
import errno
import functools
import http.server
import json
import os
import threading
from types import SimpleNamespace

import pytest

from tests.e2e.coral import _skeleton as sk


def marked(suffix):
    return lambda *_args: os.environ["CORAL_LEAK_MARKER"] + suffix


@contextlib.contextmanager
def accounts_server(root, *, status, server_env, **_kwargs):
    # Never ready without a status; drops the sign-in's connection unanswered for "drop";
    # else signs in only with the stack's own password.
    assert status is not None, "http://127.0.0.1:1/health never became ready"

    class SignIn(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            del args

        def do_POST(self):
            sent = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if status == "drop":
                self.close_connection = True
                return
            own = sent["password"] == server_env["OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD"]
            body = json.dumps({"token": marked("-owner-jwt")()}).encode()
            self.send_response(status if own else 401)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    assert server_env["OMNIGENT_ACCOUNTS_COOKIE_SECRET"].endswith("-cookie-secret")
    assert server_env["OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD"].endswith("-admin-password")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SignIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield SimpleNamespace(base_url=f"http://127.0.0.1:{server.server_address[1]}")
    finally:
        server.shutdown()
        server.server_close()


@contextlib.contextmanager
def host_never_online(root, *_args, **_kwargs):
    assert (root / "home" / ".omnigent" / "auth_tokens.json").stat().st_size
    raise AssertionError("Host never came online")
    yield


@pytest.fixture(autouse=True)
def marked_stack(monkeypatch):
    monkeypatch.setattr(sk.secrets, "token_hex", marked("-cookie-secret"))
    monkeypatch.setattr(sk.secrets, "token_urlsafe", marked("-admin-password"))
    monkeypatch.setattr(sk, "isolated_host", host_never_online)


def disk_full(obj, stored, **_kwargs):
    # The write fails part-way, with the entry and its JWT in this frame.
    raise OSError(errno.ENOSPC, "No space left on device")


STATUS = {"unready": None, "refused": 500, "dropped": "drop", "unstored": 200, "offline": 200}


@pytest.mark.parametrize("failure", list(STATUS))
def test_the_stack_fails_to_start(tmp_path, monkeypatch, failure):
    server = functools.partial(accounts_server, status=STATUS[failure])
    monkeypatch.setattr(sk, "server_runner", server)
    if failure == "unstored":
        monkeypatch.setattr(sk.json, "dump", disk_full)
    with sk.skeleton_stack(tmp_path / "stack", mock_url=None, host_config={}, identity=True):
        pass


def test_a_plain_local_is_shown():
    # Shown only by --showlocals, and whole only with -vv.
    shown = "<" * 200 + os.environ["CORAL_LEAK_MARKER"] + "-control" + ">" * 200
    raise AssertionError("a plain local")
"""


def test_a_stack_that_fails_to_start_shows_none_of_its_secrets(tmp_path: Path) -> None:
    """
    Under CI's ``--tb=long --showlocals`` and junit XML, an identity stack that fails after
    its cookie secret, admin password and owner JWT exist shows none of them, while a plain
    local in the same run is shown. ``-vv`` shows locals whole, where CI's ``-v`` cuts long
    ones short, so a secret inside a long repr is caught too.
    """
    marker = f"crl-leak-{secrets.token_hex(8)}"
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_stack_failures.py").write_text(_STACK_FAILURES)
    junit = tmp_path / "junit.xml"
    done = subprocess.run(
        [
            *(sys.executable, "-m", "pytest", "test_stack_failures.py", "-p", "no:cacheprovider"),
            f"--basetemp={tmp_path / 'child'}",
            *("--tb=long", "--showlocals", "-vv", "-r", "a", f"--junitxml={junit}"),
        ],
        cwd=tmp_path,
        env=_probe_env(tmp_path, PYTHONPATH=str(REPO), CORAL_LEAK_MARKER=marker),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    report = done.stdout + done.stderr

    assert "6 failed" in done.stdout, done.stdout[-3000:]
    for where, text in (("report", report), ("junit XML", junit.read_text())):
        assert f"{marker}-control" in text, f"the {where} shows no plain local"
        suffixes = ("-cookie-secret", "-admin-password", "-owner-jwt")
        leaked = [suffix for suffix in suffixes if f"{marker}{suffix}" in text]
        assert not leaked, f"the {where} shows {leaked}"
    # Each failure point was reached, and names only a status code or an error type.
    for failure in (
        r"never became ready",
        r"login: HTTP 500",
        r"login: (RemoteProtocolError|ReadError)",
        r"storing the owner's sign-in: OSError",
        r"Host never came online",
    ):
        assert re.search(failure, report), failure


def _stub_call(stubs: KeychainStubs, program: str, *argv: str) -> tuple[int, str]:
    """
    Run a stub by its own path; its status and all it printed. A fake value waits on its
    input, a pipe that stays open: a stub that read to the end would not return, and one
    that read a line would leave less than was written.
    """
    waiting = f"fake-stdin-{uuid.uuid4().hex}\n".encode()
    reads, writes = os.pipe()
    try:
        os.write(writes, waiting)
        done = subprocess.run(
            [str(stubs.directory / program), *argv],
            stdin=reads,
            capture_output=True,
            text=True,
            env={},
            timeout=30,
            check=False,
        )
    finally:
        os.close(writes)
        with os.fdopen(reads, "rb") as unread:
            left = unread.read()
    assert left == waiting, "the stub read its input"
    if stubs.log.is_file():
        assert waiting.decode().strip() not in stubs.log.read_text(errors="replace")
    return done.returncode, done.stdout + done.stderr


def test_the_keychain_stubs_record_bounded_names_and_answer_as_no_login(tmp_path: Path) -> None:
    stubs = install_keychain_stubs(tmp_path / "keychain-stubs" / "bin")
    account, secret, long = "fake-account", f"sk-ant-test-{uuid.uuid4().hex}", "a" * 5000
    asked = {
        (
            "security",
            "find-generic-password",
            "-a",
            account,
            "-w",
            "-s",
            "Claude Code-credentials",
        ): ("security\tfind-generic-password\tClaude Code-credentials"),
        ("security", "add-generic-password", "-a", account, "-s", "Fake Item", "-w", secret): (
            "security\tadd-generic-password\tFake Item"
        ),
        ("security", "-i"): "security\t-i\t",
        ("security", "show-keychain-info"): "security\tshow-keychain-info\t",
        ("security", "Find-Generic-Password", "-s", "a tab\tand a\nnewline"): (
            "security\tother\tother"
        ),
        ("security", long, "-s", long): "security\tother\tother",
        ("security", "find-generic-password", "-s", f"{account}@fake/path", "-s"): (
            "security\tfind-generic-password\tother"
        ),
        ("security",): "security\tother\t",
        ("gh", "auth", "token", "--hostname", "fake.example.invalid"): "gh\tauth token\t",
        (
            "gh",
            "secret",
            "set",
            "FAKE_NAME",
            "--body",
            secret,
            "-s",
            "ignored",
        ): "gh\tsecret set\t",
        ("gh", "api", f"repos/{account}/private"): "gh\tapi other\t",
        ("gh",): "gh\tother other\t",
    }
    status = {"security": 44, "gh": 1}

    answers = {call: _stub_call(stubs, *call) for call in asked}

    # The real tools' "item not found" and "logged out", with nothing printed.
    assert answers == {call: (status[call[0]], "") for call in asked}
    # One line of bounded names per call: no account, secret, later argument or input.
    assert stubs.log.read_text() == "".join(f"{line}\n" for line in asked.values())
    assert stubs.calls()[:2] == [
        "security find-generic-password Claude Code-credentials",
        "security add-generic-password Fake Item",
    ]
    modes = {
        path.relative_to(tmp_path).as_posix(): stat.S_IMODE(path.stat().st_mode)
        for path in (
            stubs.directory.parent,
            stubs.directory,
            stubs.log,
            *stubs.directory.iterdir(),
        )
    }
    assert modes == {
        "keychain-stubs": 0o700,
        "keychain-stubs/bin": 0o700,
        "keychain-stubs/bin/security": 0o700,
        "keychain-stubs/bin/gh": 0o700,
        "keychain-stubs/calls.log": 0o600,
    }
    # A log that cannot be written changes neither the answer nor the silence.
    stubs.log.unlink()
    stubs.log.mkdir()
    assert [_stub_call(stubs, program, "auth", "token") for program in KEYCHAIN_PROGRAMS] == [
        (44, ""),
        (1, ""),
    ]
    assert stubs.calls() == []


def test_only_the_expected_keychain_calls_pass_and_any_other_is_named(tmp_path: Path) -> None:
    stubs = install_keychain_stubs(tmp_path / "bin")
    # The CLI's keychain reads and lock-state query, and the login checks through gh.
    expected = [
        "security\tfind-generic-password\tClaude Code",
        "security\tfind-generic-password\tClaude Code-credentials",
        "security\tfind-generic-password\tClaude Code-0a1b2c3d",
        "security\tfind-generic-password\tClaude Code-credentials-0a1b2c3d",
        "security\tfind-generic-password\tClaude Code-device-keys",
        "security\tfind-generic-password\tClaude Code-doctor-probe",
        "security\tshow-keychain-info\t",
        "gh\tauth token\t",
        "gh\tauth status\t",
    ]
    # A write, another item, a name the stub bounded to ``other``, any other gh call, another
    # ``gh auth`` one among them; then two lines no stub writes.
    others = [
        ("security", "-i", ""),
        ("security", "delete-generic-password", "Claude Code"),
        ("security", "add-generic-password", "Claude Code-doctor-probe"),
        ("security", "find-generic-password", "gh:github.com"),
        ("security", "find-generic-password", "Claude Code-0A1B2C3D"),
        ("security", "find-generic-password", "other"),
        ("security", "find-generic-password", ""),
        ("security", "show-keychain-info", "Claude Code"),
        ("security", "other", ""),
        ("gh", "api other", ""),
        ("gh", "auth login", ""),
        ("gh", "auth refresh", ""),
        ("gh", "auth token", "Claude Code"),
    ]
    malformed = ["not a line a stub writes", "security\tfind-generic-password\tfake/path@host"]
    unlisted = [*("\t".join(names) for names in others), *malformed]
    guards = sk.KeychainGuards(tmp_path, stubs)

    stubs.log.write_text("".join(f"{line}\n" for line in expected))
    assert stubs.unexpected() == []
    assert stubs.calls()[-2:] == [HOST_GH_PROBE, "gh auth status"]
    stubs.log.write_text("".join(f"{line}\n" for line in (*expected, *unlisted, expected[0])))
    # Each is named by its subcommand and its item, apart, as the stub bounded them.
    named = [f"{program} subcommand {call!r} item {item!r}" for program, call, item in others]
    assert stubs.unexpected() == [*named, "malformed", "malformed"]
    # What a stack's teardown reports: each unexpected name with its count, nothing else.
    stubs.log.write_text("security\t-i\t\n" * 3 + "gh\tapi other\t\n" + "gh\tauth token\t\n")
    problems = ["gh subcommand 'api other' item '' (x1)", "security subcommand '-i' item '' (x3)"]
    assert sk.keychain_problems(tmp_path, stubs) == problems
    # And what it shows on any outcome: every call's name and count, in one warning.
    calls = "['security -i (x3)', 'gh api other (x1)', 'gh auth token (x1)'], 5 in all"
    with (
        pytest.warns(sk.KeychainStubCalls) as shown,
        pytest.raises(AssertionError, match=re.escape(f"left a login: {problems}. A call names")),
    ):
        guards.ended()
    assert [str(warning.message) for warning in shown] == [f"keychain stand-in calls: {calls}"]
    # A passing stack warns too, and a long log's summary stays a bounded list of names.
    stubs.log.write_text("gh\tauth token\t\n")
    with pytest.warns(sk.KeychainStubCalls, match=r": \['gh auth token \(x1\)'\], 1 in all$"):
        guards.ended()
    stubs.log.write_text("".join(f"gh\tauth token\t\ngh\tapi {'x' * n}\t\n" for n in range(1, 31)))
    summary = sk.keychain_calls_summary(stubs)
    assert summary.startswith("['gh auth token (x30)', 'gh api x (x1)', 'gh api xx (x1)', ")
    assert summary.endswith("'] and 11 more names, 60 in all") and summary.count(" (x") == 20


def test_a_stack_environment_resolves_the_keychain_programs_to_its_stubs(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    stubs = install_keychain_stubs(root / "keychain-stubs" / "bin")
    everything = list(KEYCHAIN_PROGRAMS)
    plain = sk.minimal_env()["PATH"]

    path = sk.stack_env(root, stubs, tmp_path / "t")["PATH"]

    # By resolution only: nothing on either PATH is executed.
    assert stubs.bypassed(path) == []
    assert path.split(os.pathsep)[0] == str(stubs.directory)
    # Without the stubs, macOS finds /usr/bin/security; a program found nowhere counts too.
    assert stubs.bypassed(plain) == everything
    shadow = install_keychain_stubs(tmp_path / "shadow" / "bin")
    assert stubs.bypassed(shadow.first_on({"PATH": path})["PATH"]) == everything
    (shadow.directory / "security").unlink()
    assert stubs.bypassed(shadow.first_on({"PATH": path})["PATH"]) == ["gh"]
    # An empty or relative entry ahead of the stubs searches the process's own directory.
    for ahead in ("", "bin", "."):
        assert stubs.bypassed(f"{ahead}{os.pathsep}{path}") == everything, ahead
    assert stubs.bypassed(f"{path}{os.pathsep}") == []
    assert stubs.bypassed("") == stubs.bypassed(None) == everything
    # In front of an empty PATH the stubs stand alone, with no entry for the working directory.
    alone = {"PATH": str(stubs.directory)}
    assert stubs.first_on({}) == stubs.first_on({"PATH": ""}) == alone
    given = {"PATH": "/usr/bin", "LANG": "C"}
    assert stubs.first_on(given) == {**given, "PATH": f"{stubs.directory}{os.pathsep}/usr/bin"}
    assert given == {"PATH": "/usr/bin", "LANG": "C"}


def test_a_stack_base_environment_holds_only_reviewed_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "stack"
    stubs = install_keychain_stubs(root / "keychain-stubs" / "bin")
    # What a developer's shell may hold: none of it may reach a stack daemon.
    ambient = (
        *("SSH_AUTH_SOCK", "GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "GIT_CONFIG_GLOBAL"),
        *("XDG_CONFIG_HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "CLAUDE_CONFIG_DIR"),
        *("ANTHROPIC_API_KEY", "KUBECONFIG", "GOOGLE_APPLICATION_CREDENTIALS", "USER"),
    )
    for name in ambient:
        monkeypatch.setenv(name, f"/ambient/{name}")
    for name in ("LANG", "LC_ALL", "LC_CTYPE"):
        monkeypatch.setenv(name, "C")

    env = sk.stack_env(root, stubs, tmp_path / "t")

    assert set(env) == {
        *("LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "PATH"),
        *("DISABLE_AUTOUPDATER", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"),
        *("GH_CONFIG_DIR", "GIT_CONFIG_GLOBAL", "GIT_TERMINAL_PROMPT"),
    }
    assert set(env) == sk.BASE_ENV_NAMES
    assert not [name for name, value in env.items() if "/ambient/" in value]
    assert (env["TMPDIR"], env["GIT_TERMINAL_PROMPT"]) == (str(tmp_path / "t"), "0")
    # gh and git read their login and global config under the stack's root, where none is.
    for name in ("GH_CONFIG_DIR", "GIT_CONFIG_GLOBAL"):
        assert Path(env[name]).is_relative_to(root) and not Path(env[name]).exists(), name
    # A name kept without a review here fails by name, before any daemon starts.
    monkeypatch.setattr(sk, "_KEPT_ENV", (*sk._KEPT_ENV, "SSH_AUTH_SOCK"))
    with pytest.raises(AssertionError, match=r"unreviewed names.*\['SSH_AUTH_SOCK'\]") as failed:
        sk.stack_env(root, stubs, tmp_path / "t")
    # Names only, in the message and in the locals a report would print for the failing frame.
    [guard] = [frame for frame, _line in traceback.walk_tb(failed.tb)][1:]
    assert guard.f_code.co_name == "stack_env" and "unreviewed" in guard.f_locals
    assert "/ambient/" not in f"{failed.value}{guard.f_locals}"


@pytest.mark.parametrize(
    ("left", "failure"),
    [
        (None, r"^the fake host stops the start$"),
        ("call", r"\[\"security subcommand 'fake-marker' item '' \(x1\)\"\]"),
        ("login", r"\['host/home/\.config/gh/hosts\.yml'\]"),
    ],
    ids=["clean", "unexpected-call", "gh-login"],
)
def test_every_stack_daemon_starts_with_the_keychain_stubs_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, left: str | None, failure: str
) -> None:
    """
    The server and the host get one base environment, whose ``PATH`` resolves the keychain
    programs to the stack's own stubs; and a stack that leaves an unexpected stub call, or
    a ``gh`` login in a home of its own, fails at exit by that name.
    """
    root = tmp_path / "stack"
    stubs = KeychainStubs(root / "keychain-stubs" / "bin", root / "keychain-stubs" / "calls.log")
    started: dict[str, dict[str, str]] = {}

    @contextlib.contextmanager
    def server(_root: Path, *, base_env: Mapping[str, str], **_kwargs: Any) -> Iterator[Any]:
        started["server"] = dict(base_env)
        yield SimpleNamespace(base_url="http://127.0.0.1:1", server=None)

    def host(host_root: Path, _url: str, *, base_env: Mapping[str, str], **_kwargs: Any) -> None:
        started["host"] = dict(base_env)
        if left == "call":
            # By its own path: the stack's stub, asked for what no mock stack expects.
            _stub_call(stubs, "security", "fake-marker")
        if left == "login":
            hosts = host_root / "home" / ".config" / "gh" / "hosts.yml"
            hosts.parent.mkdir(parents=True)
            hosts.write_text("")
        raise AssertionError("the fake host stops the start")

    monkeypatch.setattr(sk, "server_runner", server)
    monkeypatch.setattr(sk, "isolated_host", host)
    with (
        pytest.raises(AssertionError, match=failure),
        sk.skeleton_stack(root, mock_url=None, host_config={}),
    ):
        pass

    assert started["server"] == started["host"]
    assert stubs.bypassed(started["host"]["PATH"]) == []


def test_a_stack_installs_each_keychain_guard_as_a_step_of_its_own() -> None:
    """
    A guard dropped from ``skeleton_stack`` fails no stack run, so the three hooks are pinned
    where they are installed; what each one catches is tested on :class:`sk.KeychainGuards`.
    """
    stack = ast.parse(inspect.getsource(sk.skeleton_stack))
    at = {ast.unparse(node): node.lineno for node in ast.walk(stack) if isinstance(node, ast.Call)}
    callbacks = {call: line for call, line in at.items() if call.startswith("resources.callback(")}

    # Registered last, so it runs first at exit and its failure skips no other teardown step.
    exiting = callbacks["resources.callback(lambda: guards.exiting(live_daemons()))"]
    assert exiting == max(callbacks.values())
    # Both daemons, once they are started.
    assert at["guards.started(host.proc.pid, server.server.pid)"] > exiting
    # Registered before the reap, so the log is read after every process has ended.
    reap = callbacks["resources.callback(processes.reap)"]
    assert callbacks["resources.callback(guards.ended)"] < reap


def test_a_process_started_outside_the_keychain_barrier_is_named(tmp_path: Path) -> None:
    root = tmp_path / "stack"
    stubs = install_keychain_stubs(root / "keychain-stubs" / "bin")
    inside = {**stubs.first_on(sk.minimal_env()), "HOME": str(root / "host" / "home")}

    def named(children: list[psutil.Process], **how: bool) -> list[int]:
        # Labels are ``pid:name`` and nothing else: no PATH, no HOME.
        labels = sk.keychain_bypasses(stubs, root, children, **how)
        assert all(re.fullmatch(r"\d+:[^/:]+", label) for label in labels), labels
        return [int(label.partition(":")[0]) for label in labels]

    started = (
        inside,
        {**inside, "PATH": sk.minimal_env()["PATH"]},
        {**inside, "HOME": str(tmp_path / "elsewhere")},
        # Neither PATH nor HOME: the environment counts as not read.
        {"PROBE_TEST": "1"},
    )
    guards = sk.KeychainGuards(root, stubs)
    with contextlib.ExitStack() as running:
        children = [
            psutil.Process(running.enter_context(_sleeper(env, ready=tmp_path / f"ready-{at}")))
            for at, env in enumerate(started)
        ]
        kept, past_the_stubs, another_home, unread = (child.pid for child in children)

        assert named(children) == [past_the_stubs, another_home]
        # Where every process is known to be live, one that was not read is named too.
        assert named(children, unread_fails=True) == [past_the_stubs, another_home, unread]
        # A stack's start is such a place: its guard passes the first child and names the last.
        guards.started(kept)
        with pytest.raises(AssertionError, match=rf"keychain barrier .*\['{unread}:[^/:']+'\]$"):
            guards.started(kept, unread)

    assert named(children) == []
    assert sk.keychain_bypasses(stubs, root, children[:1], unread_fails=True) == [f"{kept}:gone"]


# A stand-in daemon: its children wait past the stubs, each once it has written its pid. One
# is a CLI, one runs an Omnigent module, and one only names paths that hold the word.
_DAEMON = """
import os, subprocess, sys, time
past = {**os.environ, "PATH": os.environ["PAST_THE_STUBS"]}
waits = "import os, sys, time; open(sys.argv[-1], 'w').write(str(os.getpid())); time.sleep(60)"
cli = sys.argv[1]
subprocess.Popen([sys.executable, cli, "claude"], env=past)
subprocess.Popen([sys.executable, "-c", waits, "-m", "omnigent.fake", "omnigent"], env=past)
subprocess.Popen([sys.executable, "-c", waits, "-C", "/fake/omnigent/.omnigent", "git"], env=past)
time.sleep(60)
"""


def test_the_exit_guard_checks_a_daemon_and_its_omnigent_and_claude_descendants(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stack"
    stubs = install_keychain_stubs(root / "keychain-stubs" / "bin")
    cli = tmp_path / "claude"
    cli.write_text(
        "import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(60)\n"
    )
    marks = tmp_path / "marks"
    marks.mkdir()
    env = {
        **stubs.first_on(sk.minimal_env()),
        "HOME": str(root / "host" / "home"),
        "PAST_THE_STUBS": sk.minimal_env()["PATH"],
    }
    daemon = subprocess.Popen(
        [sys.executable, "-c", _DAEMON, str(cli)], env=env, cwd=marks, start_new_session=True
    )
    try:
        poll_until(lambda: len(list(marks.iterdir())) == 3, interval_s=0.05)
        poll_until(lambda: all(mark.read_text() for mark in marks.iterdir()), interval_s=0.05)
        below = {mark.name: int(mark.read_text()) for mark in marks.iterdir()}

        checked = sk._checked_at_exit([daemon.pid])

        # The daemon itself started inside; a child that is neither Omnigent's nor a CLI,
        # as a git child whose PATH production builds, is not checked whatever paths it names.
        assert {proc.pid for proc in checked} == {daemon.pid, below["claude"], below["omnigent"]}
        with pytest.raises(AssertionError, match="outside the keychain barrier") as failed:
            sk.KeychainGuards(root, stubs).exiting([daemon.pid])
        # By pid and name only: no PATH, no HOME.
        message = str(failed.value)
        named = {int(pid) for pid in re.findall(r"'(\d+):", message)}
        assert named == {below["claude"], below["omnigent"]} and os.sep not in message
    finally:
        os.killpg(daemon.pid, signal.SIGKILL)
        daemon.wait(timeout=10)
    assert sk._checked_at_exit([daemon.pid]) == []


def test_the_cli_probe_runs_claude_only_under_a_throwaway_home_with_the_stubs_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    The pytest process asks the ``claude`` CLI for its version once, and never with its own
    environment. The stand-in CLI here records where it was started.
    """
    seen = tmp_path / "seen"
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\n"
        '{ echo "$HOME"; echo "$CLAUDE_CONFIG_DIR"; command -v security; command -v gh;'
        f' echo "${{GH_TOKEN-unset}}"; }} >> {shlex.quote(str(seen))}\n'
        'echo "9.9.9 (stand-in)"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path / "callers-home"))
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.delenv(sk.REQUIRE_CLI_ENV, raising=False)
    sk._claude_cli.cache_clear()
    try:
        sk.require_claude_cli()
        assert sk.claude_version() == "9.9.9 (stand-in)"
        home, config, security, gh, token = seen.read_text().splitlines()
        # A CLI that installed but does not run fails where the lane requires it, else skips.
        fake.write_text("#!/bin/sh\necho broken >&2\nexit 3\n")
        sk._claude_cli.cache_clear()
        for required, outcome in (("0", pytest.skip.Exception), ("1", AssertionError)):
            monkeypatch.setenv(sk.REQUIRE_CLI_ENV, required)
            with pytest.raises(outcome, match="exits 3: broken"):
                sk.require_claude_cli()
    finally:
        sk._claude_cli.cache_clear()

    # One run for both callers, in a home made for it and removed with it.
    assert home != os.environ["HOME"] and not Path(home).exists()
    assert Path(config).is_relative_to(home)
    stub_dir = Path(security).parent
    assert stub_dir == Path(gh).parent and Path(home).parent in stub_dir.parents
    assert token == "unset"
