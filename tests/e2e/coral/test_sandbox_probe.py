"""Probe 15: what a generated step's shell reaches on a real stack.

The probe runs as the implementer, the widest stance Coral generates, while a reviewer
on a parallel branch is held mid-turn, so its runner, harness socket and CLI are live.
Every target is resolved on the host side and proven live right before the probe call
is released and again after it: a target that went missing fails as a failed control,
never as a verdict. ``probe15.sh``, committed into the repository's first commit,
prints verdict tokens only; it compares canaries in the step by digest (in files, and
in the environments and command lines it reads), and the host's tunnel credential file
by its size, whose content the test never reads.

Pins are change detectors per platform, and a pinned ``reachable`` names its owner.
Without a pin for the platform the test writes its verdicts to ``artifacts/`` (when that
directory exists, as in CI) and fails as not pinned. The second test runs one step on a
server that keeps the allow-listed runner token, with the host exporting it. The plain
tests at the end run the probe on synthetic targets, with no stack.

Canaries and the allow-listed token are held in :class:`Secret` and the probe's output
is reduced to its verdicts where it is read. Only the stack helpers' frames hold raw
values, so only a failure in the stack's start or teardown prints these throwaway values.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.server
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psutil
import pytest

import coral
import omnigent
from coral.omni.server.step_agents import checkout_read_paths
from omnigent._platform import stable_user_id
from omnigent.runtime.harnesses.paths import resolve_harness_tmp_parent
from tests._helpers.live_server import find_free_port, terminate_process
from tests.e2e.conftest import get_mock_message_requests, release_mock_gate
from tests.e2e.coral import _skeleton as sk
from tests.e2e.coral._live_proxy import Secret

# Absolute deadline for a scenario, below the marker's limit.
SCENARIO_S = 200
SHORT_LEASE_S = 10
PROBE = Path(__file__).with_name("probe15.sh")
ARTIFACTS = Path(__file__).resolve().parents[3] / "artifacts"
FIXTURE = "probe.yaml"
README = {"command": "cat README.md"}
NOTHING = {"command": "true"}
DONE = {"text": "Handed off."}
VERDICTS = {"reachable", "denied", "hidden", "not_present", "mismatch", "unclassified"}
# What the probe reports beside a target's own verdict: the names it read, and whether
# the API key canary is in the environment or the command line it read.
SUB_CHECKS = (".names", ".api_key", ".argv_api_key")
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
# The design's credential-like names, the only names a ``.names`` line may carry.
_SENSITIVE_NAME = re.compile(
    r"^(OMNIGENT_RUNNER_\w*TOKEN\w*|\w*API_KEY\w*|HARNESS_CLAUDE_SDK_\w*)$", re.ASCII
)
_TOKEN_NAME = re.compile(r"^OMNIGENT_RUNNER_.*TOKEN.*$")


@dataclass(frozen=True)
class Pin:
    """A pinned verdict (or a ``.names`` list) and, for ``reachable``, its owner ticket."""

    verdict: str
    owner: str | None = None


# Owner tickets, by the exposure a pinned reachable shows.
SERVER_OWNER = "CRL-159"  # a single-user server takes any local process as its owner

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
        "server_loopback": Pin("reachable", SERVER_OWNER),
        "server_localhost": Pin("reachable", SERVER_OWNER),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
    },
    # Pinned from lane run 44980984569 on Ubuntu 24.04.5 LTS, claude 2.1.295 (bwrap).
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
        "server_loopback": Pin("reachable", SERVER_OWNER),
        "server_localhost": Pin("reachable", SERVER_OWNER),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
    },
}
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
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(5)
                client.connect(str(path))
        except OSError as error:
            return f"{path.name}: {type(error).__name__}"
        return None

    return live


def _url_live(url: str) -> Callable[[], str | None]:
    def live() -> str | None:
        try:
            response = httpx.get(url, timeout=5.0, trust_env=False)
        except httpx.HTTPError as error:
            return f"{url}: {type(error).__name__}"
        return None if response.status_code == 200 else f"{url}: HTTP {response.status_code}"

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


def _one_cli(runner: int) -> int:
    """The pid of the step's one ``claude`` CLI below its runner."""
    tree = sk.group_tree(runner)
    clis = sk.claude_clis(tree)
    assert len(clis) == 1, f"{len(clis)} claude CLIs in {sk.process_names(tree)}"
    return clis[0].pid


def _harness_socket(stack: sk.Skeleton, session_id: str) -> Path:
    """The session's harness socket, under the stack's root or the default one."""
    roots = dict.fromkeys((stack.harness_tmp, resolve_harness_tmp_parent({})))
    [found] = [path for root in roots for path in root.glob(f"ap-*/conv-{session_id}.sock")]
    return found


def _socket_root(stack: sk.Skeleton, harness_socket: Path) -> str:
    """The root the runner put the socket under, as recorded beside the pins."""
    root = harness_socket.parent.parent
    if root == stack.harness_tmp:
        return str(root.parent / "crl-*")
    return str(root).replace(f"-{os.getuid()}", "-<uid>")


def _bridge_root(stack: sk.Skeleton) -> Path:
    """Where a host-launched step keeps its bridge tree: under the host's TMPDIR."""
    return Path(stack.host_launch.env["TMPDIR"]) / f"omnigent-{stable_user_id()}" / "claude-native"


def _token_names(proc: psutil.Process) -> str:
    """The ``OMNIGENT_RUNNER_*TOKEN*`` names in a process's environment, never a value."""
    names = set(proc.environ())
    assert {"PATH", "HOME"} & names, f"{proc.pid}'s environment is unreadable outside the sandbox"
    return ",".join(sorted(name for name in names if _TOKEN_NAME.match(name))) or "none"


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


def _controls_held(verdicts: Mapping[str, str]) -> None:
    failed = {
        check: verdicts.get(check) for check in CONTROLS if verdicts.get(check) != "reachable"
    }
    assert not failed, f"failed control in the step: {failed}"
    unclassified = sorted(check for check, token in verdicts.items() if token == "unclassified")
    assert not unclassified, f"failed control: the probe could not classify {unclassified}"
    # The control's own variable has a credential-like name, so the names listing is proven too.
    listed = verdicts.get("control_environ.names", "").split(",")
    assert CONTROL_NAME in listed, f"failed control: control_environ.names is {listed}"


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


def _assert_recorded(recorded: Mapping[str, Any]) -> None:
    """The pins hold only for the socket root and read grant they were taken with."""
    pinned = RECORDED.get(sys.platform, {})
    for key in ("harness_socket_root", "checkout_read_grant") if pinned else ():
        assert recorded[key] == pinned[key], (key, recorded[key])


def _write_artifact(name: str, report: Mapping[str, Any]) -> Path | None:
    """Write the run's verdicts where the lane uploads them, when that directory exists."""
    if not ARTIFACTS.is_dir():
        return None
    path = ARTIFACTS / f"{name}-{sys.platform}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return path


def _exposure(pinned: str, observed: str) -> str:
    if observed == "reachable" and pinned != "reachable":
        return f"{pinned} -> reachable reads as an exposure"
    if pinned == "reachable":
        return f"reachable -> {observed}: the step reaches less; re-pin"
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


def _assert_pinned(
    name: str, pins: Mapping[str, Pin], observed: Mapping[str, str], written: Path | None
) -> None:
    """Compare with the platform's pins, naming each check and the direction it moved."""
    where = f"verdicts written to {written}" if written else "no artifacts/ directory to write to"
    assert pins, f"{name} is not pinned for {sys.platform} ({where}): {json.dumps(observed)}"
    unowned = sorted(
        check
        for check, pin in pins.items()
        if pin.verdict == "reachable" and not (pin.owner or "").strip()
    )
    assert not unowned, f"pinned reachable without an owner ticket: {unowned}"
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
            moved.append(f"{check}: {_exposure(pinned, seen)}")
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
        runner = sk.runner_pid(stack, reviewer)
        own_runner = sk.runner_pid(stack, sk.step_session(client, run_id, "implement"))
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
            "cli_environ": _one_cli(runner),
            "host_environ": stack.host.proc.pid,
            "own_cli_environ": _one_cli(own_runner),
        }
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
            Target("shell_env_names", "shell", ""),
        ]
        unproven = _unproven(targets)
        assert not unproven, f"targets without a host-side control: {unproven}"
        checks = {target.check for target in targets}
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
        leaked = _ledger_holds(mock, {**values, "config_api_key": api_key})

    assert not after, f"failed control after the probe: {after}"
    verdicts = _assert_reading(reading, targets)
    _controls_held(verdicts)
    # The ledger holds the probe's tokens, never a canary.
    assert not leaked, f"the mock's ledger holds {leaked}"
    observed = {
        check: token for check, token in verdicts.items() if not check.startswith("control_")
    }
    report = {"verdicts": observed, "recorded": recorded}
    written = _write_artifact("probe15", report)
    print(
        f"Probe 15 on {sys.platform}, checkout read grant {recorded['checkout_read_grant']}:",
        json.dumps(report),
    )
    assert (run["status"], run["causes"]) == ("completed", []), run
    _assert_recorded(recorded)
    _assert_pinned("probe 15", EXPECTED.get(sys.platform, {}), observed, written)


EXPECTED_TOKEN: dict[str, dict[str, Pin]] = {
    # Pinned from one local run on macOS 27.2.1 with claude 2.1.325 (seatbelt).
    "darwin": {
        "step_runs": Pin("true"),
        "runner_environ": Pin("denied"),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
        "runner.names": Pin("OMNIGENT_RUNNER_TUNNEL_TOKEN"),
        "harness.names": Pin("OMNIGENT_RUNNER_TUNNEL_TOKEN"),
        "launcher.names": Pin("none"),
        "cli.names": Pin("none"),
    },
    # Pinned from lane run 44980984569 on Ubuntu 24.04.5 LTS, claude 2.1.295 (bwrap).
    "linux": {
        "step_runs": Pin("true"),
        "runner_environ": Pin("hidden"),
        "shell_env_names": Pin("not_present"),
        "shell_env_names.names": Pin("none"),
        "runner.names": Pin("OMNIGENT_RUNNER_TUNNEL_TOKEN"),
        "harness.names": Pin("OMNIGENT_RUNNER_TUNNEL_TOKEN"),
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
    outside, where a zygote-forked runner's or harness's environment is the host's own.

    Recorded with it: a host ``unknown`` counts as dead, so a relaunch can start while the
    old runner lives on; on such a server runner-id rotation does not fence that runner,
    since the server accepts the allow-listed token for every session (``mcp_identity.py``).
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
    sk.queue(mock, impl_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, NOTHING, call_id=f"n-{uid}"))])
    sk.queue(
        mock, review_token, [sk.held(sk.tool_call(sk.SHELL_TOOL, README, call_id=f"r-{uid}"))]
    )
    deadline = time.monotonic() + SCENARIO_S

    with sk.skeleton_stack(
        tmp_path / "stack",
        mock_url=mock,
        host_config=sk.mock_auth(mock),
        host_env={"OMNIGENT_RUNNER_TUNNEL_TOKEN": allowlisted.reveal()},
        lease_s=SHORT_LEASE_S,
        allowlisted_token=allowlisted.reveal(),
        repo_files={PROBE.name: PROBE.read_bytes()},
    ) as stack:
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
        step = sk.step_processes(sk.runner_pid(stack, implementer))
        recorded = _recorded(stack, _harness_socket(stack, implementer))
        names = {f"{role}.names": _token_names(proc) for role, proc in step.items()}
        runner = step["runner"].pid
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
        checks = {target.check for target in targets}
        sk.queue(
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
        sk.queue(
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

    assert not after, f"failed control after the probe: {after}"
    verdicts = _assert_reading(reading, targets)
    _controls_held(verdicts)
    assert not leaked, f"the mock's ledger holds {leaked}"
    runs = (run["status"], run["causes"]) == ("completed", []) and any(
        '"accepted": true' in text for text in accepted
    )
    observed = {
        "step_runs": str(runs).lower(),
        **{check: token for check, token in verdicts.items() if not check.startswith("control_")},
        **names,
    }
    report = {"verdicts": observed, "recorded": recorded}
    written = _write_artifact("probe15-token", report)
    print(f"Allow-listed token on {sys.platform}:", json.dumps(report))
    _assert_recorded(recorded)
    pins = EXPECTED_TOKEN.get(sys.platform, {})
    _assert_pinned("the allow-listed-token step", pins, observed, written)


def _probe_env(home: Path, **extra: str) -> dict[str, str]:
    return {**sk.minimal_env(), "HOME": str(home), **extra}


def _run_probe(targets: list[Target], env: Mapping[str, str], cwd: Path) -> Reading:
    """Run the probe outside any sandbox, its output reduced here as the ledger's is."""
    done = subprocess.run(
        ["/bin/sh", str(PROBE), *(target.argument() for target in targets)],
        capture_output=True,
        text=True,
        env=dict(env),
        cwd=cwd,
        timeout=60,
        check=False,
    )
    verdicts, strays = _parse(done.stdout, {target.check for target in targets})
    return Reading(verdicts, strays, stderr_chars=len(done.stderr))


@contextlib.contextmanager
def _sleeper(env: Mapping[str, str], *argv: str) -> Iterator[int]:
    """A Python child that waits with ``env`` and ``argv``; ended on exit."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", *argv], env=env)
    try:
        yield child.pid
    finally:
        terminate_process(child)


@contextlib.contextmanager
def _served_url() -> Iterator[str]:
    """A loopback HTTP server that answers every request with an error status."""

    class Quiet(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            del args

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/health"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
                Target("served", "http", url),
                Target("closed_port", "http", f"http://127.0.0.1:{find_free_port()}/health"),
            ]
            reading = _run_probe(targets, _probe_env(tmp_path), tmp_path)
    finally:
        shutil.rmtree(short, ignore_errors=True)

    assert _assert_reading(reading, targets) == {
        "live": "reachable",
        "stale": "unclassified",
        "missing": "hidden",
        "not_a_socket": "unclassified",
        "served": "reachable",
        "closed_port": "hidden",
    }


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
    clean = _run_probe(targets, _probe_env(tmp_path), tmp_path)
    pathless = _run_probe(targets, {"HOME": str(tmp_path)}, tmp_path)

    assert _assert_reading(exposed, targets) == {
        "shell_env_names": "reachable",
        "shell_env_names.names": "PROBE_TEST_API_KEY",
    }
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
    pins = {
        "socket": Pin("reachable", SERVER_OWNER),
        "file": Pin("denied"),
        "env.names": Pin("A_API_KEY,B_API_KEY"),
    }
    same = {"socket": "reachable", "file": "denied", "env.names": "A_API_KEY,B_API_KEY"}
    _assert_pinned("synthetic", pins, same, None)

    for owner in (None, "", "  "):
        with pytest.raises(AssertionError, match=r"without an owner ticket: \['socket'\]"):
            _assert_pinned("synthetic", {**pins, "socket": Pin("reachable", owner)}, same, None)
    with pytest.raises(AssertionError, match="synthetic is not pinned"):
        _assert_pinned("synthetic", {}, same, None)
    moved = {"socket": "denied", "file": "reachable", "env.names": "A_API_KEY,C_API_KEY"}
    with pytest.raises(AssertionError) as failed:
        _assert_pinned("synthetic", pins, {**moved, "new": "hidden"}, None)
    message = str(failed.value)
    assert "socket: reachable -> denied: the step reaches less; re-pin" in message
    assert "file: denied -> reachable reads as an exposure" in message
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
    assert _unproven([*targets, Target("runner_environ", "environ", "1")]) == ["runner_environ"]
    assert (
        _unproven([Target("control_environ", "environ", "self"), Target("s", "shell", "")]) == []
    )
