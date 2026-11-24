"""CORAL(S123): hand a child its launch secrets through an inherited socket, never its environment.

Another same-user process can read a process's exec-time environment for that process's
whole life, and on Linux it can reopen an inherited pipe through ``/proc/<pid>/fd``. It can
do neither with a connected UNIX socket. The parent writes the values into one end of a
socket pair and closes it before the spawn; the child inherits the other end through
``pass_fds``, finds its number in an environment variable and reads the values once at boot.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import selectors
import socket
import stat
import sys
import time
from collections.abc import Collection, Iterator, Mapping, MutableMapping

from omnigent.runner.identity import RUNNER_AUTH_SECRET_ENV_VARS

# No credential word in the name: it holds only a fd number.
LAUNCH_SECRETS_FD_ENV_VAR = "OMNIGENT_RUNNER_LAUNCH_FD"
# CORAL(S124): a direct-exec claude-sdk harness's socket. Its name must not start with the
# harness's config prefix, which the harness sweeps from its environment as config.
HARNESS_LAUNCH_FD_ENV_VAR = "OMNIGENT_HARNESS_LAUNCH_FD"
# CORAL(S124): the claude-sdk harness config that can carry a key; only these use the socket.
CLAUDE_SDK_HARNESS_LAUNCH_SECRET_ENV_VARS: frozenset[str] = frozenset(
    {"HARNESS_CLAUDE_SDK_API_KEY_HELPER", "HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND"}
)
# Fits an empty UNIX socket's buffer on Linux and macOS, so the parent's write never waits.
MAX_LAUNCH_SECRETS_BYTES = 4096
# The parent wrote everything and closed its end before the spawn, so EOF is already there.
LAUNCH_SECRETS_READ_TIMEOUT_S = 5.0
LAUNCH_SECRETS_EXIT_CODE = 2


class _LaunchSecretsRefused(Exception):
    """Why the launch secrets were refused, in words that never hold a value."""


def launch_secrets_pipe(values: Mapping[str, str]) -> int:
    """Write *values* as one JSON object into a new UNIX socket pair and return the child's end.

    The parent's end is non-blocking, so a buffer too small for the payload raises rather
    than waits, and it is shut down and closed before this returns. The child's end is
    above fd 2, which the child's own stdio replaces.

    :param values: Names and secrets, e.g. the runner's binding token and bearer.
    :returns: The child's end, not inheritable until passed through ``pass_fds``.
    :raises OSError: ``E2BIG`` over :data:`MAX_LAUNCH_SECRETS_BYTES`, or from the socket
        pair, the write or the fd move; no fd is left open.
    """
    payload = json.dumps(dict(values), separators=(",", ":")).encode()
    if len(payload) > MAX_LAUNCH_SECRETS_BYTES:
        raise OSError(errno.E2BIG, "the launch secrets exceed the payload cap")
    parent_end, child_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    with parent_end, child_end:
        parent_end.setblocking(False)
        parent_end.sendall(payload)
        parent_end.shutdown(socket.SHUT_WR)
        if child_end.fileno() > 2:
            return child_end.detach()
        # A daemon with a closed standard stream got it as the child's end; leaving the
        # block closes that low fd.
        import fcntl  # POSIX only, and this module must import on Windows

        return fcntl.fcntl(child_end.fileno(), fcntl.F_DUPFD_CLOEXEC, 3)


@contextlib.contextmanager
def launch_secrets_in_pipe(
    env: Mapping[str, str],
    names: Collection[str],
    *,
    fd_env_var: str = LAUNCH_SECRETS_FD_ENV_VAR,
) -> Iterator[tuple[dict[str, str], tuple[int, ...]]]:
    """A copy of *env* whose *names* travel in a launch-secrets socket, and the fds to pass.

    Spawn the child inside the block with the copy and ``pass_fds`` including the yielded
    fds; the child's end is closed here when the block exits, spawned or not. Any
    *fd_env_var* in *env* is dropped: a fd number from the parent's own environment names
    nothing the child should read. With none of *names* in *env* the copy gets no socket.

    :param env: The child's environment, holding the secrets.
    :param names: The names that move into the socket; empty keeps env delivery.
    :param fd_env_var: The variable that tells the child its end.
    :raises OSError: From :func:`launch_secrets_pipe`; nothing falls back to the env.
    :raises TypeError: If *names* is one ``str``, which would iterate as characters.
    """
    if isinstance(names, str):
        raise TypeError("names must be a collection of names, not one str")
    spawn_env = {name: value for name, value in env.items() if name != fd_env_var}
    values = {name: spawn_env.pop(name) for name in sorted(names) if name in spawn_env}
    if not values:
        yield spawn_env, ()
        return
    child_fd = launch_secrets_pipe(values)
    spawn_env[fd_env_var] = str(child_fd)
    try:
        yield spawn_env, (child_fd,)
    finally:
        os.close(child_fd)


def adopt_launch_secrets(
    target: MutableMapping[str, str],
    *,
    environ: MutableMapping[str, str] | None = None,
    fd_env_var: str = LAUNCH_SECRETS_FD_ENV_VAR,
    allowed: Collection[str] = RUNNER_AUTH_SECRET_ENV_VARS,
) -> None:
    """Move the values a launching parent sent this process into *target*.

    Pops *fd_env_var* from *environ*; without it, does nothing. Otherwise reads the socket
    it names to EOF, non-blocking under :data:`LAUNCH_SECRETS_READ_TIMEOUT_S`, closes it,
    and requires a non-empty JSON object of strings whose names are all in *allowed*, each
    once.

    :param target: Where the values go, e.g. a process's in-memory holder.
    :param environ: The environment naming the fd, ``os.environ`` by default.
    :param fd_env_var: The variable naming the inherited socket.
    :param allowed: The only names the payload may carry.
    :raises TypeError: If *allowed* is one ``str``, whose ``in`` would match substrings.
    :raises SystemExit: :data:`LAUNCH_SECRETS_EXIT_CODE` on any failure, after one stderr
        line that names no value; *target* is then unchanged.
    """
    if isinstance(allowed, str):
        raise TypeError("allowed must be a collection of names, not one str")
    source = os.environ if environ is None else environ
    raw_fd = source.pop(fd_env_var, None)
    if raw_fd is None:
        return
    try:
        values = _read_launch_secrets(raw_fd, allowed)
    except _LaunchSecretsRefused as refused:
        print(f"error: launch secrets in {fd_env_var} refused: {refused}", file=sys.stderr)
        raise SystemExit(LAUNCH_SECRETS_EXIT_CODE) from None
    target.update(values)


def _read_launch_secrets(raw_fd: str, allowed: Collection[str]) -> dict[str, str]:
    if not (raw_fd.isascii() and raw_fd.isdigit()):
        raise _LaunchSecretsRefused("the descriptor is not a number")
    fd = int(raw_fd)
    # A standard stream is never a launch socket, and is not this reader's to close.
    if fd <= 2:
        raise _LaunchSecretsRefused("the descriptor is a standard stream")
    try:
        payload = _read_socket(fd)
    finally:
        with contextlib.suppress(OSError, OverflowError):
            os.close(fd)
    return _parse_launch_secrets(payload, allowed)


def _read_socket(fd: int) -> bytes:
    try:
        is_socket = stat.S_ISSOCK(os.fstat(fd).st_mode)
    except (OSError, OverflowError):
        raise _LaunchSecretsRefused("the descriptor is not open") from None
    # Only a socket: on Linux a pipe or a file can be reopened through /proc/<pid>/fd.
    if not is_socket:
        raise _LaunchSecretsRefused("the descriptor is not a socket")
    deadline = time.monotonic() + LAUNCH_SECRETS_READ_TIMEOUT_S
    payload = bytearray()
    try:
        os.set_blocking(fd, False)
        with selectors.DefaultSelector() as selector:
            selector.register(fd, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _LaunchSecretsRefused("the payload did not end in time")
                if not selector.select(remaining):
                    continue
                try:
                    chunk = os.read(fd, MAX_LAUNCH_SECRETS_BYTES + 1 - len(payload))
                except BlockingIOError:
                    continue
                if not chunk:
                    return bytes(payload)
                payload += chunk
                if len(payload) > MAX_LAUNCH_SECRETS_BYTES:
                    raise _LaunchSecretsRefused(
                        f"the payload exceeds {MAX_LAUNCH_SECRETS_BYTES} bytes"
                    )
    except OSError as exc:
        raise _LaunchSecretsRefused(f"the read failed ({type(exc).__name__})") from None


def _object_naming_each_once(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded = dict(pairs)
    if len(decoded) != len(pairs):
        raise _LaunchSecretsRefused("the payload names a variable twice")
    return decoded


def _parse_launch_secrets(payload: bytes, allowed: Collection[str]) -> dict[str, str]:
    try:
        decoded: object = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_object_naming_each_once
        )
    except (ValueError, RecursionError):
        raise _LaunchSecretsRefused("the payload is not UTF-8 JSON") from None
    if not isinstance(decoded, dict):
        raise _LaunchSecretsRefused("the payload is not a JSON object")
    if not decoded:
        raise _LaunchSecretsRefused("the payload names no variable")
    values: dict[str, str] = {}
    for name, value in decoded.items():
        if not isinstance(value, str):
            raise _LaunchSecretsRefused("a payload value is not a string")
        if name not in allowed:
            raise _LaunchSecretsRefused("the payload names a variable it may not carry")
        values[name] = value
    return values
