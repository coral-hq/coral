# CORAL(S40): engine workspace-op frames and their guarded dispatcher (new file).
"""Workspace ops the server asks a host to run in one of its git worktrees.

The server sends ``host.workspace_op`` only to a host whose hello advertises
:data:`CAP_WORKSPACE_OPS`; the host runs the named handler off the event loop
inside the orphan-reaper guard and answers ``host.workspace_op_result``. The
token is a capability, not authorization: the server authorizes the host
before sending.

Handlers come from installed ``omnigent.host_workspace_ops`` entry points,
loaded on the first op frame. Each entry point names a zero-argument callable
returning ``{op name: handler}``. With none installed every op answers
:data:`UNKNOWN_OP`.

This module imports only the standard library (``frames.py`` imports it), so
loading it never pulls in server or database modules.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import importlib.metadata
import json
import logging
import math
import ntpath
import os
import posixpath
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, cast

_logger = logging.getLogger(__name__)

CAP_WORKSPACE_OPS = "workspace_ops:1"
WORKSPACE_OP_KIND = "host.workspace_op"
WORKSPACE_OP_RESULT_KIND = "host.workspace_op_result"
# CORAL(S40b): installed handler contributions.
ENTRY_POINT_GROUP = "omnigent.host_workspace_ops"
MAX_WORKSPACE_OP_TIMEOUT_S = 900.0
MAX_ERROR_MESSAGE_CHARS = 2000
# A serialised result payload stays far below the tunnel's message limit.
MAX_WORKSPACE_OP_RESULT_BYTES = 8 * 1024 * 1024
# Ops running at once on one host; a queued op holds no thread and leaves the reaper running.
MAX_CONCURRENT_WORKSPACE_OPS = 2

# Frame-level failure codes; handlers report their own. All are permanent except
# HANDLER_FAILED, which may be a transient fault inside the handler.
UNKNOWN_OP = "unknown_op"
INVALID_REQUEST = "invalid_request"
HANDLER_FAILED = "handler_failed"
INVALID_PAYLOAD = "invalid_payload"
RESULT_TOO_LARGE = "result_too_large"

_OP_NAME = re.compile(r"[a-z][a-z0-9_.]{0,63}")
# Failure codes share the op-name shape, e.g. "workspace.git_failed".
ERROR_CODE_PATTERN = _OP_NAME
# K13's op-key format: a key names refs and commit trailers.
_OP_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,127}")


@dataclass(frozen=True)
class HostWorkspaceOpFrame:
    """Server → host: run workspace op ``op`` in the worktree at ``root``.

    :param request_id: Correlation id echoed by the result, e.g. 32 hex chars.
    :param op: Handler name, e.g. ``"commit"``.
    :param root: Canonical absolute worktree root on the host.
    :param params: Op parameters (a JSON object), re-validated by the handler.
    :param timeout_s: Seconds the host may spend, in ``(0, 900]``.
    :param op_key: Idempotency key (K13 format) for ops that take one, else ``None``.
    """

    request_id: str
    op: str
    root: str
    params: dict[str, Any]
    timeout_s: float
    op_key: str | None = None


@dataclass(frozen=True)
class HostWorkspaceOpResultFrame:
    """Host → server: the outcome of one :class:`HostWorkspaceOpFrame`.

    :param request_id: The request's correlation id.
    :param status: ``"ok"`` with a ``payload``, or ``"failed"`` with an ``error_code``.
    :param payload: The handler's JSON object on success.
    :param error_code: Frame-level code (e.g. :data:`UNKNOWN_OP`) or the handler's own.
    :param error: Human-readable detail, at most 2,000 characters.
    :param exit_code: Exit code of the failed command, when there was one.
    :param permanent: ``True`` when retrying cannot succeed; absent on the wire means ``False``.
    """

    request_id: str
    status: Literal["ok", "failed"]
    payload: dict[str, Any] | None = None
    error_code: str | None = None
    error: str | None = None
    exit_code: int | None = None
    permanent: bool = False
    # The payload's JSON from the dispatcher's worker, so it is serialised once. Not an
    # init field: dataclasses.replace() drops it instead of reusing a stale copy.
    _payload_json: str | None = field(default=None, init=False, repr=False, compare=False)


@dataclass(frozen=True)
class WorkspaceOpRequest:
    """What a handler receives: the frame's fields plus a ``time.monotonic()`` deadline.

    The dispatcher cannot stop a handler's thread, so the handler must honour
    ``deadline`` itself (for example by killing its child process group).
    """

    op: str
    root: str
    params: Mapping[str, Any]
    timeout_s: float
    op_key: str | None
    deadline: float


class WorkspaceOpHandlerError(Exception):
    """A handler's typed failure, reported to the server with its code.

    :param code: Failure code shaped like an op name, e.g. ``"workspace.git_failed"``.
    :param message: Detail for the run owner; trimmed to its last 2,000 characters.
    :param exit_code: Exit code of the failed command, if any.
    :param permanent: ``True`` when retrying cannot succeed.
    :raises TypeError: A field has the wrong type (the dispatcher then answers
        :data:`HANDLER_FAILED`).
    :raises ValueError: ``code`` is not shaped like an op name.
    """

    def __init__(
        self, code: str, message: str, *, exit_code: int | None = None, permanent: bool = False
    ) -> None:
        if not isinstance(code, str):
            raise TypeError("workspace op error code must be a str")
        if ERROR_CODE_PATTERN.fullmatch(code) is None:
            raise ValueError(f"workspace op error code {code!r} is not shaped like an op name")
        if not isinstance(message, str):
            raise TypeError("workspace op error message must be a str")
        if exit_code is not None and (
            not isinstance(exit_code, int) or isinstance(exit_code, bool)
        ):
            raise TypeError("workspace op error exit_code must be an int or None")
        if not isinstance(permanent, bool):
            raise TypeError("workspace op error permanent must be a bool")
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.permanent = permanent


WorkspaceOpHandler = Callable[[WorkspaceOpRequest], Mapping[str, Any]]
# The caller's guard, e.g. HostProcess._run_host_subprocess_in_thread.
RunGuarded = Callable[[Callable[[], object]], Awaitable[object]]


class _PayloadRefused(Exception):
    """A handler's return value cannot cross the tunnel (permanent)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def workspace_op_frame_payload(
    frame: HostWorkspaceOpFrame | HostWorkspaceOpResultFrame,
) -> dict[str, Any]:
    """Return a fresh wire object for *frame*, every field present.

    :param frame: A workspace-op request or result.
    :returns: The JSON object, ``kind`` included.
    """
    if isinstance(frame, HostWorkspaceOpFrame):
        return {
            "kind": WORKSPACE_OP_KIND,
            "request_id": frame.request_id,
            "op": frame.op,
            "root": frame.root,
            "params": frame.params,
            "timeout_s": frame.timeout_s,
            "op_key": frame.op_key,
        }
    return {
        "kind": WORKSPACE_OP_RESULT_KIND,
        "request_id": frame.request_id,
        "status": frame.status,
        "payload": frame.payload,
        "error_code": frame.error_code,
        "error": frame.error,
        "exit_code": frame.exit_code,
        "permanent": frame.permanent,
    }


def encode_workspace_op_frame(
    frame: HostWorkspaceOpFrame | HostWorkspaceOpResultFrame,
    encode_object: Callable[[dict[str, Any]], str],
) -> str:
    """Encode *frame* with *encode_object*, ``frames.py``'s JSON envelope encoder.

    A dispatcher result's payload was already serialised in its worker thread, so
    only the small envelope is encoded here and the payload text is appended.

    :param frame: A workspace-op request or result.
    :param encode_object: Serialises a wire object (and adds trace context).
    :returns: The JSON wire text.
    """
    wire = workspace_op_frame_payload(frame)
    payload_json = frame._payload_json if isinstance(frame, HostWorkspaceOpResultFrame) else None
    if payload_json is None:
        return encode_object(wire)
    del wire["payload"]
    envelope = encode_object(wire)
    return f'{envelope[:-1]}, "payload": {payload_json}}}'


def decode_workspace_op_frame(
    msg: Mapping[str, Any],
) -> HostWorkspaceOpFrame | HostWorkspaceOpResultFrame:
    """Decode a workspace-op wire object, validating every field's type.

    :param msg: Decoded JSON object whose ``kind`` is one of the two kinds.
    :returns: The typed frame.
    :raises ValueError: On a missing or ill-typed field, a timeout outside
        ``(0, 900]``, an ``ok`` result without a payload or a ``failed`` one
        without an error code.
    """
    request_id = _str_field(msg, "request_id")
    if not request_id:
        raise ValueError("workspace op frame needs a non-empty 'request_id'")
    if msg.get("kind") == WORKSPACE_OP_KIND:
        params = msg.get("params")
        if not isinstance(params, dict):
            raise ValueError("workspace op 'params' must be a JSON object")
        return HostWorkspaceOpFrame(
            request_id=request_id,
            op=_str_field(msg, "op"),
            root=_str_field(msg, "root"),
            params=params,
            timeout_s=_timeout_seconds(msg.get("timeout_s")),
            op_key=_optional_str_field(msg, "op_key"),
        )
    if msg.get("kind") != WORKSPACE_OP_RESULT_KIND:
        raise ValueError(f"not a workspace op frame kind: {msg.get('kind')!r}")
    status = msg.get("status")
    if status not in ("ok", "failed"):
        raise ValueError("workspace op result 'status' must be 'ok' or 'failed'")
    payload = msg.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("workspace op result 'payload' must be a JSON object or null")
    if status == "ok" and payload is None:
        raise ValueError("an ok workspace op result needs a 'payload'")
    error_code = _optional_str_field(msg, "error_code")
    if status == "failed" and error_code is None:
        raise ValueError("a failed workspace op result needs an 'error_code'")
    exit_code = msg.get("exit_code")
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool)):
        raise ValueError("workspace op result 'exit_code' must be an integer or null")
    permanent = msg.get("permanent")
    if permanent is not None and not isinstance(permanent, bool):
        raise ValueError("workspace op result 'permanent' must be a boolean")
    return HostWorkspaceOpResultFrame(
        request_id=request_id,
        status=status,
        payload=payload,
        error_code=error_code,
        error=_optional_str_field(msg, "error"),
        exit_code=exit_code,
        permanent=bool(permanent),
    )


def workspace_op_request_problem(frame: HostWorkspaceOpFrame) -> str | None:
    """Say why *frame*'s root or op key is refused, or return ``None``.

    The server checks before sending and the host before dispatching. ``root``
    must be absolute and canonical in its own path flavour (POSIX, or a Windows
    drive path): no NUL, no ``//`` or UNC prefix, no empty, ``.`` or ``..``
    segment and no trailing separator. ``op_key`` must match K13's format.

    :param frame: A request with well-typed fields.
    :returns: The refusal text, or ``None`` when both are acceptable.
    """
    root = frame.root
    flavour = ntpath if ntpath.splitdrive(root)[0] else posixpath
    if (
        "\0" in root
        or root.startswith(("//", "\\\\"))
        or not flavour.isabs(root)
        or flavour.normpath(root) != root
    ):
        return "workspace op root must be a canonical absolute path"
    if frame.op_key is not None and _OP_KEY.fullmatch(frame.op_key) is None:
        return "workspace op key must be 1-128 of a-z, 0-9, '_' or '-'"
    return None


def validate_workspace_op_request(frame: HostWorkspaceOpFrame) -> None:
    """Refuse a request the host would drop or refuse, before it is sent.

    :param frame: The request about to be sent.
    :raises ValueError: When decoding would reject a field or
        :func:`workspace_op_request_problem` reports a problem.
    """
    decode_workspace_op_frame(workspace_op_frame_payload(frame))
    problem = workspace_op_request_problem(frame)
    if problem is not None:
        raise ValueError(problem)


def trim_error_message(message: str) -> str:
    """Keep the last :data:`MAX_ERROR_MESSAGE_CHARS` characters, where the cause usually is."""
    if len(message) <= MAX_ERROR_MESSAGE_CHARS:
        return message
    return "…" + message[-(MAX_ERROR_MESSAGE_CHARS - 1) :]


def _timeout_seconds(value: object) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            seconds = float(value)
        except OverflowError:  # an integer too large for a float
            seconds = math.inf
        if math.isfinite(seconds) and 0 < seconds <= MAX_WORKSPACE_OP_TIMEOUT_S:
            return seconds
    raise ValueError(
        f"workspace op 'timeout_s' must be a number in (0, {MAX_WORKSPACE_OP_TIMEOUT_S:g}]"
    )


def _str_field(msg: Mapping[str, Any], key: str) -> str:
    value = msg.get(key)
    if not isinstance(value, str):
        raise ValueError(f"workspace op frame missing required string field: {key!r}")
    return value


def _optional_str_field(msg: Mapping[str, Any], key: str) -> str | None:
    value = msg.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"workspace op frame field must be a string or null: {key!r}")
    return value


# CORAL(S40b): handler registry from installed entry points.
class WorkspaceOpHandlers(Mapping[str, WorkspaceOpHandler]):
    """Read-only loaded handlers, plus what failed to load or conflicted.

    :param handlers: ``{op name: handler}`` served by exactly one contribution.
    :param failed: Contributions that failed to load.
    :param conflicts: Ops offered by more than one contribution, served by none.
    """

    def __init__(
        self,
        handlers: Mapping[str, WorkspaceOpHandler],
        *,
        failed: Iterable[str] = (),
        conflicts: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._handlers = dict(handlers)
        self.failed = tuple(failed)
        self.conflicts: Mapping[str, tuple[str, ...]] = MappingProxyType(dict(conflicts or {}))

    def __getitem__(self, op: str) -> WorkspaceOpHandler:
        return self._handlers[op]

    def __iter__(self) -> Iterator[str]:
        return iter(self._handlers)

    def __len__(self) -> int:
        return len(self._handlers)


def load_workspace_op_handlers(
    entry_points: Iterable[importlib.metadata.EntryPoint] | None = None,
) -> WorkspaceOpHandlers:
    """Load handler contributions; a broken one is skipped with a warning.

    A contribution adds all of its ops or none. An op offered by more than one
    contribution is served by none of them (logged as an error), so no package
    can silently take over another's op. Each served op is logged with its source.

    :param entry_points: Entry points to load; ``None`` discovers the installed
        :data:`ENTRY_POINT_GROUP`, sorted by name.
    :returns: The loaded handlers.
    """
    if entry_points is None:
        try:
            entry_points = sorted(
                importlib.metadata.entry_points(group=ENTRY_POINT_GROUP),
                key=lambda entry: (entry.name, entry.value),
            )
        except Exception:  # unreadable metadata leaves the host with no ops, not a crash
            _logger.warning("Failed to discover host workspace op handlers", exc_info=True)
            return WorkspaceOpHandlers({}, failed=(f"{ENTRY_POINT_GROUP} discovery",))
    offers: dict[str, list[tuple[str, WorkspaceOpHandler]]] = {}
    failed: list[str] = []
    for entry in entry_points:
        source = _entry_source(entry)
        try:
            contribution = entry.load()()
            if not isinstance(contribution, Mapping):
                raise TypeError("contribution must return a mapping of op name to handler")
            ops = dict(contribution)
            for op, handler in ops.items():
                if not isinstance(op, str) or _OP_NAME.fullmatch(op) is None:
                    raise ValueError(f"invalid workspace op name {op!r}")
                if not callable(handler):
                    raise TypeError(f"workspace op {op!r} handler is not callable")
        except Exception:  # a broken plugin must not hide the others
            _logger.warning(
                "Failed to load host workspace ops from %s; skipping", source, exc_info=True
            )
            failed.append(source)
            continue
        for op, handler in ops.items():
            offers.setdefault(op, []).append((source, handler))
    handlers: dict[str, WorkspaceOpHandler] = {}
    conflicts: dict[str, tuple[str, ...]] = {}
    for op, offered in offers.items():
        sources = tuple(source for source, _handler in offered)
        if len(offered) > 1:
            _logger.error(
                "Workspace op %r is offered by %s; serving none of them", op, " and ".join(sources)
            )
            conflicts[op] = sources
            continue
        _logger.info("Workspace op %r is served by %s", op, sources[0])
        handlers[op] = offered[0][1]
    return WorkspaceOpHandlers(handlers, failed=failed, conflicts=conflicts)


def _entry_source(entry: importlib.metadata.EntryPoint) -> str:
    """Name an entry point by its distribution when known, e.g. ``"coral (coral)"``."""
    distribution = getattr(entry, "dist", None)
    package = getattr(distribution, "name", None)
    return f"{package} ({entry.name})" if package else entry.name


@functools.cache
def default_workspace_op_handlers() -> WorkspaceOpHandlers:
    """Return the installed handlers, loaded once on first use (never at import).

    :returns: The loaded handlers; empty when nothing is installed.
    """
    return load_workspace_op_handlers()


async def dispatch_workspace_op(
    frame: HostWorkspaceOpFrame,
    *,
    run_guarded: RunGuarded,
    handlers: Mapping[str, WorkspaceOpHandler],
    slots: asyncio.Semaphore | None = None,
) -> HostWorkspaceOpResultFrame:
    """Run *frame*'s handler through *run_guarded* and always return its result.

    Only cancellation propagates; anything unexpected becomes
    :data:`HANDLER_FAILED`, so the server never waits out its timeout. The
    handler must honour ``request.deadline`` itself: its thread cannot be stopped.

    :param frame: The decoded request.
    :param run_guarded: Runs a blocking callable off the event loop while the
        host's orphan reaper stays paused, e.g.
        ``HostProcess._run_host_subprocess_in_thread``.
    :param handlers: ``{op name: handler}``, usually
        :func:`default_workspace_op_handlers`.
    :param slots: Bounds concurrent ops; acquired before *run_guarded*, so a
        queued op holds no thread and does not pause the reaper.
    :returns: An ``ok`` result with the handler's payload, or a ``failed`` one.
    """
    try:
        return await _dispatch(frame, run_guarded=run_guarded, handlers=handlers, slots=slots)
    except Exception as exc:
        _logger.error("Host workspace op dispatch failed", exc_info=True)
        return _failed(frame, HANDLER_FAILED, f"workspace op dispatch raised {type(exc).__name__}")


async def _dispatch(
    frame: HostWorkspaceOpFrame,
    *,
    run_guarded: RunGuarded,
    handlers: Mapping[str, WorkspaceOpHandler],
    slots: asyncio.Semaphore | None,
) -> HostWorkspaceOpResultFrame:
    handler = handlers.get(frame.op)
    if handler is None:
        return _failed(frame, UNKNOWN_OP, _unknown_op_message(frame.op, handlers), permanent=True)
    problem = workspace_op_request_problem(frame)
    if problem is None and not os.path.isabs(frame.root):
        problem = "workspace op root is not absolute on this host"
    if problem is not None:
        return _failed(frame, INVALID_REQUEST, problem, permanent=True)
    request = WorkspaceOpRequest(
        op=frame.op,
        root=frame.root,
        params=MappingProxyType(dict(frame.params)),
        timeout_s=frame.timeout_s,
        op_key=frame.op_key,
        # Time spent waiting for a slot counts: the server's wait started at send.
        deadline=time.monotonic() + frame.timeout_s,
    )
    slot = slots if slots is not None else contextlib.nullcontext()
    async with slot:
        try:
            outcome = await run_guarded(functools.partial(_run_handler, handler, request))
        except _PayloadRefused as exc:
            return _failed(frame, exc.code, exc.message, permanent=True)
        except WorkspaceOpHandlerError as exc:
            return _failed(
                frame, exc.code, exc.message, permanent=exc.permanent, exit_code=exc.exit_code
            )
        except Exception as exc:
            # Exception text can carry paths or secrets; only the type crosses the tunnel.
            _logger.error("Host workspace op %r failed", frame.op, exc_info=True)
            return _failed(
                frame, HANDLER_FAILED, f"workspace op handler raised {type(exc).__name__}"
            )
    payload, payload_json = cast("tuple[dict[str, Any], str]", outcome)
    result = HostWorkspaceOpResultFrame(request_id=frame.request_id, status="ok", payload=payload)
    object.__setattr__(result, "_payload_json", payload_json)
    return result


def _run_handler(
    handler: WorkspaceOpHandler, request: WorkspaceOpRequest
) -> tuple[dict[str, Any], str]:
    """Run *handler* and serialise its payload once, both in the guarded worker thread."""
    payload = handler(request)
    if not isinstance(payload, Mapping):
        raise _PayloadRefused(INVALID_PAYLOAD, "workspace op handler returned a non-mapping")
    result = dict(payload)
    try:
        payload_json = json.dumps(result, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise _PayloadRefused(
            INVALID_PAYLOAD, "workspace op handler returned a non-JSON payload"
        ) from None
    # ASCII-only JSON (ensure_ascii), so characters are bytes.
    if len(payload_json) > MAX_WORKSPACE_OP_RESULT_BYTES:
        raise _PayloadRefused(
            RESULT_TOO_LARGE,
            f"workspace op result is {len(payload_json)} bytes; the limit is "
            f"{MAX_WORKSPACE_OP_RESULT_BYTES}",
        )
    return result, payload_json


def _unknown_op_message(op: str, handlers: Mapping[str, WorkspaceOpHandler]) -> str:
    if isinstance(handlers, WorkspaceOpHandlers):
        if op in handlers.conflicts:
            sources = " and ".join(handlers.conflicts[op])
            return f"workspace op {op!r} is offered by {sources}; see the host log"
        if handlers.failed:
            failed = ", ".join(handlers.failed)
            return (
                f"no handler for workspace op {op!r} is loaded: {failed} failed to load; "
                "see the host log"
            )
    return f"this host has no workspace op {op!r}"


def _failed(
    frame: HostWorkspaceOpFrame,
    code: str,
    message: str,
    *,
    permanent: bool = False,
    exit_code: int | None = None,
) -> HostWorkspaceOpResultFrame:
    return HostWorkspaceOpResultFrame(
        request_id=frame.request_id,
        status="failed",
        error_code=code,
        error=trim_error_message(message),
        exit_code=exit_code,
        permanent=permanent,
    )
