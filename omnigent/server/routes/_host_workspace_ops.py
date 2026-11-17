# CORAL(S40): server side of the host workspace-op channel (new file).
"""Send one ``host.workspace_op`` to a connected host and await its result.

Only hosts whose hello advertises ``workspace_ops:1`` are asked; any other host
is refused before a frame is sent. The token is a capability, not
authorization: callers authorize the host for the acting user first and send
inside a ``host_owner_scope`` naming the connection's owner registration. The
helper refuses to send without one, and the scope makes the registry refuse a
connection that changed owner.

A dropped tunnel fails the request at once; otherwise it waits the op's own
timeout plus :data:`WORKSPACE_OP_REPLY_GRACE_S`. A timeout, a dropped tunnel or
a cancelled request leaves the outcome unknown: the host may still finish the
op. Callers retry with the same ``op_key`` and never treat such a failure as
"not executed".
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from omnigent.host.frames import encode_host_frame
from omnigent.host.workspace_ops import (
    CAP_WORKSPACE_OPS,
    ERROR_CODE_PATTERN,
    HANDLER_FAILED,
    HostWorkspaceOpFrame,
    trim_error_message,
    validate_workspace_op_request,
)
from omnigent.server.host_registry import HostConnection, HostRegistry, host_owner_scope_matches
from omnigent.server.routes._host_worktree import (
    WorktreeHostUnavailableError,
    _await_host_worktree_result,
)

# Outwait the host's own deadline so its typed timeout arrives instead of ours.
WORKSPACE_OP_REPLY_GRACE_S = 15.0


@dataclass(frozen=True)
class WorkspaceOpReply:
    """The host's answer, as relayed by the host tunnel.

    :param status: ``"ok"`` (with a payload) or ``"failed"`` (with an error code).
    :param payload: The handler's JSON object; its shape is the caller's to check.
    :param error_code: Frame-level code (e.g. ``"unknown_op"``) or the handler's own;
        a malformed code reads as ``"handler_failed"``.
    :param error: Detail for the run owner, cut to its last 2,000 characters.
    :param exit_code: Exit code of the failed command, when there was one.
    :param permanent: ``True`` when retrying cannot succeed.
    """

    status: Literal["ok", "failed"]
    payload: dict[str, Any] | None
    error_code: str | None
    error: str | None
    exit_code: int | None
    permanent: bool


class HostWorkspaceOpsUnsupportedError(Exception):
    """The host does not advertise ``workspace_ops:1``; nothing was sent."""


class HostWorkspaceOpNotPermittedError(PermissionError):
    """No ``host_owner_scope`` naming the connection's owner is active; nothing was sent."""


class HostWorkspaceOpUnavailableError(Exception):
    """The host could not be reached, or did not answer in time; the outcome is unknown.

    :param message: Human-readable cause.
    :param timed_out: ``True`` when no reply arrived in time, ``False`` when the
        connection was lost or replaced.
    """

    def __init__(self, message: str, *, timed_out: bool) -> None:
        super().__init__(message)
        self.message = message
        self.timed_out = timed_out


async def request_workspace_op_on_host(
    *,
    host_registry: HostRegistry,
    host_conn: HostConnection,
    op: str,
    root: str,
    params: Mapping[str, object],
    timeout_s: float,
    op_key: str | None,
) -> WorkspaceOpReply:
    """Run workspace op *op* in *root* on the host and return its reply.

    :param host_registry: Registry used to enqueue the frame.
    :param host_conn: The authorized host's live connection.
    :param op: Handler name, e.g. ``"commit"``.
    :param root: Canonical absolute worktree root on the host.
    :param params: JSON-serialisable op parameters.
    :param timeout_s: Seconds the host may spend, in ``(0, 900]``.
    :param op_key: Idempotency key in K13's format for ops that take one, else ``None``.
    :returns: The relayed reply, ``ok`` or ``failed``.
    :raises HostWorkspaceOpsUnsupportedError: The host lacks the token.
    :raises ValueError: The host would drop or refuse the frame (an ill-typed
        field, a timeout outside ``(0, 900]``, a non-canonical root, a malformed op key).
    :raises TypeError: *params* is not JSON-serialisable.
    :raises HostWorkspaceOpNotPermittedError: No matching ``host_owner_scope`` is active.
    :raises HostWorkspaceOpUnavailableError: The tunnel dropped or no reply came in
        time; the op may still run on the host.
    """
    if CAP_WORKSPACE_OPS not in host_conn.hello.capabilities:
        raise HostWorkspaceOpsUnsupportedError(
            f"host {host_conn.host_id!r} does not advertise {CAP_WORKSPACE_OPS}"
        )
    request_id = secrets.token_hex(16)
    request = HostWorkspaceOpFrame(
        request_id=request_id,
        op=op,
        root=root,
        params=dict(params),
        timeout_s=timeout_s,
        op_key=op_key,
    )
    validate_workspace_op_request(request)
    frame = encode_host_frame(request)
    if not host_owner_scope_matches(host_conn):
        raise HostWorkspaceOpNotPermittedError(
            f"no host owner scope names the owner of host {host_conn.host_id!r}"
        )
    try:
        result = await _await_host_worktree_result(
            host_registry=host_registry,
            host_conn=host_conn,
            pending=host_conn.pending_workspace_ops,
            request_id=request_id,
            frame=frame,
            op=f"workspace op {op!r}",
            timeout=timeout_s + WORKSPACE_OP_REPLY_GRACE_S,
            older_host_hint=False,
        )
    except WorktreeHostUnavailableError as exc:
        timed_out = isinstance(exc.__cause__, TimeoutError)
        raise HostWorkspaceOpUnavailableError(exc.message, timed_out=timed_out) from exc
    return _reply(result)


def _reply(result: Mapping[str, object]) -> WorkspaceOpReply:
    """Type the relayed fields and bound the host-controlled text."""
    payload = result.get("payload")
    error_code = result.get("error_code")
    if isinstance(error_code, str) and ERROR_CODE_PATTERN.fullmatch(error_code) is None:
        error_code = HANDLER_FAILED
    error = result.get("error")
    exit_code = result.get("exit_code")
    return WorkspaceOpReply(
        status="ok" if result.get("status") == "ok" else "failed",
        payload=payload if isinstance(payload, dict) else None,
        error_code=error_code if isinstance(error_code, str) else None,
        error=trim_error_message(error) if isinstance(error, str) else None,
        exit_code=exit_code if type(exit_code) is int else None,
        permanent=result.get("permanent") is True,
    )
