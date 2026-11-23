"""CORAL(S117): a launch socket carries a runner's tokens past its exec-time environment."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil
import pytest

from omnigent.runner import launch_secrets
from omnigent.runner.identity import (
    RUNNER_AUTH_SECRET_ENV_VARS,
    RUNNER_INITIAL_AUTH_TOKEN_ENV_VAR,
    RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR,
)
from omnigent.runner.launch_secrets import (
    LAUNCH_SECRETS_EXIT_CODE,
    LAUNCH_SECRETS_FD_ENV_VAR,
    MAX_LAUNCH_SECRETS_BYTES,
    adopt_launch_secrets,
    launch_secrets_in_pipe,
    launch_secrets_pipe,
)


def _fake(label: str) -> str:
    return f"fake-{label}-{secrets.token_hex(8)}"


def _digests(values: dict[str, str]) -> dict[str, str]:
    """Compare secrets by digest, so a failure prints none of them."""
    return {name: hashlib.sha256(value.encode()).hexdigest() for name, value in values.items()}


def _is_open(fd: int) -> bool:
    try:
        os.fstat(fd)
    except OSError:
        return False
    return True


def _socket_holding(
    payload: bytes, *, writer_stays_open: bool = False
) -> tuple[int, socket.socket | None]:
    """A socket whose reading end holds *payload*; its writer stays open only when asked."""
    writer, reader = socket.socketpair()
    writer.sendall(payload)
    if writer_stays_open:
        return reader.detach(), writer
    writer.close()
    return reader.detach(), None


def _token_payload(value: str) -> bytes:
    return json.dumps({RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: value}).encode()


@pytest.mark.parametrize("size", ["small", "at_the_cap"])
def test_sent_values_move_into_the_target_and_the_fd_closes(size: str) -> None:
    values = {
        RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: _fake("binding"),
        RUNNER_INITIAL_AUTH_TOKEN_ENV_VAR: _fake("bearer"),
    }
    if size == "at_the_cap":
        unpadded = len(json.dumps(values, separators=(",", ":")))
        values[RUNNER_INITIAL_AUTH_TOKEN_ENV_VAR] += "x" * (MAX_LAUNCH_SECRETS_BYTES - unpadded)
    read_fd = launch_secrets_pipe(values)
    environ = {LAUNCH_SECRETS_FD_ENV_VAR: str(read_fd), "PATH": "/bin"}
    target: dict[str, str] = {}

    adopt_launch_secrets(target, environ=environ)

    assert _digests(target) == _digests(values)
    assert environ == {"PATH": "/bin"}
    assert not _is_open(read_fd)


def test_without_the_fd_variable_nothing_changes() -> None:
    environ = {"PATH": "/bin"}
    target = {"KEPT": "1"}

    adopt_launch_secrets(target, environ=environ)

    assert (target, environ) == ({"KEPT": "1"}, {"PATH": "/bin"})


def test_one_name_given_as_the_names_to_send_is_refused() -> None:
    env = {RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: _fake("binding")}

    # A str iterates as characters, which would leave the token in the child's env.
    with pytest.raises(TypeError):
        with launch_secrets_in_pipe(env, RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR):
            pass


def test_one_name_given_as_allowed_is_refused_before_anything_is_read() -> None:
    read_fd, _writer = _socket_holding(_token_payload(_fake("binding")))
    environ = {LAUNCH_SECRETS_FD_ENV_VAR: str(read_fd)}
    target: dict[str, str] = {}

    # ``in`` on a str matches substrings, so one name is not an allow-list.
    try:
        with pytest.raises(TypeError):
            adopt_launch_secrets(
                target, environ=environ, allowed=RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR
            )
        unread = _is_open(read_fd)
    finally:
        with contextlib.suppress(OSError):
            os.close(read_fd)

    assert (unread, target, environ) == (True, {}, {LAUNCH_SECRETS_FD_ENV_VAR: str(read_fd)})


_REFUSED_PAYLOADS: dict[str, Callable[[str], bytes]] = {
    "not_json": lambda value: b"{" + value.encode(),
    "not_utf8": lambda value: b'{"x": "\xff' + value.encode() + b'"}',
    "not_an_object": lambda value: json.dumps([value]).encode(),
    "not_a_string": lambda value: json.dumps(
        {RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: [value]}
    ).encode(),
    "unknown_name": lambda value: json.dumps({value: "1"}).encode(),
    "oversize": lambda value: _token_payload(value + "x" * MAX_LAUNCH_SECRETS_BYTES),
    # Valid JSON padded past the cap: refused for its size, not for its parse.
    "padded_past_the_cap": lambda value: _token_payload(value) + b" " * MAX_LAUNCH_SECRETS_BYTES,
    "truncated": lambda value: _token_payload(value)[:-2],
    "empty_object": lambda _value: b"{}",
    "duplicate_name": lambda value: (
        f'{{"{RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR}":"{value}",'
        f'"{RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR}":"{value}"}}'
    ).encode(),
}


@pytest.mark.parametrize("case", [*_REFUSED_PAYLOADS, "timed_out"])
def test_a_refused_payload_exits_2_with_one_line_that_names_no_value(
    case: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = _fake("value")
    if case == "timed_out":
        monkeypatch.setattr(launch_secrets, "LAUNCH_SECRETS_READ_TIMEOUT_S", 0.2)
        read_fd, writer = _socket_holding(b"", writer_stays_open=True)
    else:
        read_fd, writer = _socket_holding(_REFUSED_PAYLOADS[case](value))
    environ = {LAUNCH_SECRETS_FD_ENV_VAR: str(read_fd)}
    target: dict[str, str] = {}
    try:
        with pytest.raises(SystemExit) as exited:
            adopt_launch_secrets(target, environ=environ)
        closed = not _is_open(read_fd)
    finally:
        if writer is not None:
            writer.close()

    out, err = capsys.readouterr()
    assert exited.value.code == LAUNCH_SECRETS_EXIT_CODE
    assert len(err.splitlines()) == 1, err
    assert LAUNCH_SECRETS_FD_ENV_VAR in err
    assert value not in out + err
    assert (closed, target, environ) == (True, {}, {})


@pytest.mark.parametrize(
    "case", ["not_a_number", "standard_stream", "negative", "not_open", "a_file", "a_pipe"]
)
def test_a_descriptor_that_is_not_a_launch_socket_exits_2(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[int] = []
    # A file and a pipe carry a valid payload: only the descriptor's kind refuses them.
    if case == "a_file":
        (tmp_path / "f").write_text(_token_payload(_fake("value")).decode())
        opened.append(os.open(tmp_path / "f", os.O_RDONLY))
    elif case == "a_pipe":
        read_fd, write_fd = os.pipe()
        os.write(write_fd, _token_payload(_fake("value")))
        os.close(write_fd)
        opened.append(read_fd)
    elif case == "not_open":
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        os.close(write_fd)
        opened.append(read_fd)
    raw = {"not_a_number": "3x", "standard_stream": "2", "negative": "-1"}.get(case)
    environ = {LAUNCH_SECRETS_FD_ENV_VAR: raw if raw is not None else str(opened[0])}

    with pytest.raises(SystemExit) as exited:
        adopt_launch_secrets({}, environ=environ)

    assert exited.value.code == LAUNCH_SECRETS_EXIT_CODE
    assert len(capsys.readouterr().err.splitlines()) == 1
    # What the variable named is closed, never a standard stream.
    assert [fd for fd in opened if _is_open(fd)] == []
    assert _is_open(2)


def test_the_writer_refuses_a_payload_over_the_cap_and_leaves_no_fd_open() -> None:
    fds = psutil.Process().num_fds()
    over = {RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: "x" * MAX_LAUNCH_SECRETS_BYTES}

    with pytest.raises(OSError) as refused:
        launch_secrets_pipe(over)

    assert refused.value.errno == errno.E2BIG
    assert psutil.Process().num_fds() == fds


@pytest.mark.timeout(30)
def test_the_writer_raises_on_a_full_socket_instead_of_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_end, child_end = socket.socketpair()
    parent_end.setblocking(False)
    with pytest.raises(BlockingIOError):  # fill the buffer to capacity
        while True:
            parent_end.send(b"x" * 4096)
    parent_end.setblocking(True)
    ends = (parent_end.fileno(), child_end.fileno())
    monkeypatch.setattr(launch_secrets.socket, "socketpair", lambda *_: (parent_end, child_end))

    with pytest.raises(BlockingIOError):
        launch_secrets_pipe({RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: _fake("binding")})

    assert [fd for fd in ends if _is_open(fd)] == []


def test_the_socket_context_moves_only_the_named_values_and_closes_its_fd() -> None:
    values = {
        RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: _fake("binding"),
        RUNNER_INITIAL_AUTH_TOKEN_ENV_VAR: _fake("bearer"),
    }
    # A stale fd number from the parent's own environment never reaches the child.
    env = {**values, "PATH": "/bin", LAUNCH_SECRETS_FD_ENV_VAR: "9"}

    with launch_secrets_in_pipe(env, RUNNER_AUTH_SECRET_ENV_VARS) as (spawn_env, pass_fds):
        [read_fd] = pass_fds
        assert spawn_env == {"PATH": "/bin", LAUNCH_SECRETS_FD_ENV_VAR: str(read_fd)}
        sent = json.loads(os.read(read_fd, MAX_LAUNCH_SECRETS_BYTES + 1))
    assert _digests(sent) == _digests(values)
    assert not _is_open(read_fd)

    # Nothing to move (Windows keeps env delivery): the env is copied without a socket.
    with launch_secrets_in_pipe(env, ()) as (spawn_env, pass_fds):
        assert (sorted(spawn_env), pass_fds) == (sorted({*values, "PATH"}), ())

    # A failed spawn still closes the child's end.
    with pytest.raises(OSError), launch_secrets_in_pipe(env, values) as (_env, pass_fds):
        raise OSError(errno.ENOENT, "spawn failed")
    assert not _is_open(pass_fds[0])


# A runner's boot, then what it holds and what a child spawned with env=None inherits.
_CHILD = """
import hashlib, json, os, subprocess, sys
from omnigent.runner import _entry, identity
from omnigent.runner.launch_secrets import LAUNCH_SECRETS_FD_ENV_VAR

_entry._hold_runner_auth_secrets()
names = sorted(identity.RUNNER_AUTH_SECRET_ENV_VARS)
probe = "import os, sys; print(','.join(n for n in sys.argv[1:] if n in os.environ) or 'none')"
inherited = subprocess.run(
    [sys.executable, "-c", probe, *names], capture_output=True, text=True, check=True
).stdout.strip()
held = {n: hashlib.sha256(identity.runner_auth_secret(n).encode()).hexdigest() for n in names}
watched = [*names, LAUNCH_SECRETS_FD_ENV_VAR]
report = {"environ": [n for n in watched if n in os.environ], "held": held, "inherited": inherited}
print(json.dumps(report), flush=True)
sys.stdin.readline()
"""


def test_a_real_runner_holds_its_sent_tokens_while_its_readable_env_lacks_them(
    tmp_path: Path,
) -> None:
    values = {
        RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: _fake("binding"),
        RUNNER_INITIAL_AUTH_TOKEN_ENV_VAR: _fake("bearer"),
    }
    passed = {name: os.environ[name] for name in ("PATH", "PYTHONPATH") if name in os.environ}
    env = {**passed, "HOME": str(tmp_path), "TMPDIR": str(tmp_path), **values}

    with launch_secrets_in_pipe(env, RUNNER_AUTH_SECRET_ENV_VARS) as (spawn_env, pass_fds):
        child = subprocess.Popen(
            [sys.executable, "-c", _CHILD],
            env=spawn_env,
            pass_fds=pass_fds,
            cwd=tmp_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    try:
        assert child.stdout is not None and child.stdin is not None
        line = child.stdout.readline()
        readable = set(psutil.Process(child.pid).environ()) if line else set()
    finally:
        child.kill()
        _out, err = child.communicate(timeout=30)
    assert line, f"the child exited {child.returncode}: {err[-2000:]}"

    # The exec-time environment was read: it names the fd, and neither token.
    assert {"PATH", LAUNCH_SECRETS_FD_ENV_VAR} <= readable
    assert sorted(readable & RUNNER_AUTH_SECRET_ENV_VARS) == []
    report = json.loads(line)
    assert report == {"environ": [], "held": _digests(values), "inherited": "none"}


# A child lists the sockets it holds above its stdio, then reads its own launch socket.
_ADOPTER = """
import hashlib, json, os, stat
from omnigent.runner.launch_secrets import adopt_launch_secrets

sockets = []
for fd in sorted(int(name) for name in os.listdir("/dev/fd")):
    try:
        status = os.fstat(fd)
    except OSError:
        continue
    if fd > 2 and stat.S_ISSOCK(status.st_mode):
        sockets.append([status.st_dev, status.st_ino])
held = {}
adopt_launch_secrets(held)
digests = {name: hashlib.sha256(value.encode()).hexdigest() for name, value in held.items()}
print(json.dumps({"sockets": sockets, "held": digests}))
"""


def test_concurrent_launches_never_cross_sockets(tmp_path: Path) -> None:
    launches = [{RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: _fake(f"binding-{n}")} for n in range(2)]
    passed = {name: os.environ[name] for name in ("PATH", "PYTHONPATH") if name in os.environ}
    passed |= {"HOME": str(tmp_path), "TMPDIR": str(tmp_path)}
    # Both sockets are open while either child is spawned.
    together = threading.Barrier(len(launches), timeout=30)

    def _launch(values: dict[str, str]) -> tuple[dict[str, object], list[int]]:
        with launch_secrets_in_pipe({**passed, **values}, RUNNER_AUTH_SECRET_ENV_VARS) as (
            spawn_env,
            pass_fds,
        ):
            status = os.fstat(pass_fds[0])
            together.wait()
            child = subprocess.Popen(
                [sys.executable, "-c", _ADOPTER],
                env=spawn_env,
                pass_fds=pass_fds,
                cwd=tmp_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            together.wait()
        out, err = child.communicate(timeout=60)
        assert child.returncode == 0, err[-2000:]
        return json.loads(out), [status.st_dev, status.st_ino]

    with ThreadPoolExecutor(len(launches)) as pool:
        results = list(pool.map(_launch, launches))

    assert [report for report, _socket in results] == [
        {"sockets": [launch_socket], "held": _digests(values)}
        for (_report, launch_socket), values in zip(results, launches, strict=True)
    ]


# A daemon whose stdin and stdout are closed, so its socket pair takes fds 0 and 1.
_DAEMON_WITHOUT_STDIN_OR_STDOUT = """
import os, subprocess, sys
from omnigent.runner.identity import RUNNER_AUTH_SECRET_ENV_VARS
from omnigent.runner.launch_secrets import launch_secrets_in_pipe

os.close(0)
os.close(1)
with launch_secrets_in_pipe(os.environ, RUNNER_AUTH_SECRET_ENV_VARS) as (spawn_env, pass_fds):
    child = subprocess.run(
        [sys.executable, "-c", sys.argv[1]],
        env=spawn_env,
        pass_fds=pass_fds,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
sys.stderr.write(child.stdout)
"""


def test_a_daemon_without_stdin_or_stdout_still_hands_its_child_the_socket(
    tmp_path: Path,
) -> None:
    values = {
        RUNNER_TUNNEL_BINDING_TOKEN_ENV_VAR: _fake("binding"),
        RUNNER_INITIAL_AUTH_TOKEN_ENV_VAR: _fake("bearer"),
    }
    passed = {name: os.environ[name] for name in ("PATH", "PYTHONPATH") if name in os.environ}
    env = {**passed, "HOME": str(tmp_path), "TMPDIR": str(tmp_path), **values}

    daemon = subprocess.run(
        [sys.executable, "-c", _DAEMON_WITHOUT_STDIN_OR_STDOUT, _ADOPTER],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # The child's stdio replaced fds 0 and 1, yet it read its socket above them.
    last = (daemon.stderr.splitlines() or [""])[-1]
    assert daemon.returncode == 0 and last.startswith("{"), daemon.stderr[-2000:]
    report = json.loads(last)
    assert (len(report["sockets"]), report["held"]) == (1, _digests(values))
