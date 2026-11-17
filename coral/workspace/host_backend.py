"""Coral's K13 backend over the host workspace-op channel (app tier: no Omnigent imports).

``HostWorkspaceOps`` sends each op it serves (``HOST_CHANNEL_OPS``) to the
worktree's host through a ``HostChannelBackend`` and parses the payload
strictly. Every op checks the op-host rule first, then its params
(``ValueError``), then that a host-channel executor names the ref's own host,
before anything is sent; the host re-validates everything. ``fingerprint`` at
L2, ``merge`` and ``check`` are not served at M2: they raise a permanent
``workspace.capability_unavailable`` after the op-host rule.

``map_host_reply`` turns a host's reply into a payload or a K13 error. The
in-process conformance channel and the server adapter share it, so the gate
tests the production mapping.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import cast, override

from coral.workspace.ops import (
    COMMIT_ID,
    WORKSPACE_ERROR_CODES,
    CheckResult,
    CommitResult,
    DiffStat,
    Fingerprint,
    FingerprintLevel,
    HeadResult,
    HostChannel,
    HostChannelBackend,
    MergeResult,
    OpExecutor,
    OpName,
    ReadResult,
    ResetResult,
    SalvageResult,
    WorkspaceErrorCode,
    WorkspaceOpError,
    WorkspaceOps,
    WorkspaceRef,
    check_op_host,
    salvage_ref_name,
    validate_commit_id,
    validate_commit_message,
    validate_op_key,
    validate_record_id,
    validate_trailers,
    validate_workspace_path,
)

# Op ids the host channel serves at M2; fingerprint counts once per level.
HOST_CHANNEL_OPS: frozenset[str] = frozenset(
    {"head", "diff_stat", "read", "fingerprint-L1", "commit", "salvage", "reset"}
)
# Host-side deadlines; the channel refuses anything over 900 s before sending.
READ_TIMEOUT_S = 120.0
WRITE_TIMEOUT_S = 600.0

# The host's own failure codes besides K13's.
_INVALID_PARAMS = "workspace.invalid_params"
_UNKNOWN_OP = "unknown_op"
# Codes a retry never fixes, whatever the host's ``permanent`` flag says.
ALWAYS_PERMANENT_CODES: frozenset[str] = frozenset(
    {"workspace.capability_unavailable", "workspace.worktree_displaced"}
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def map_host_reply(
    reply: Mapping[str, object], *, host_id: str | None = None
) -> Mapping[str, object]:
    """
    Return an ``ok`` reply's payload, or raise the K13 error its failure stands for.

    :param reply: The host's answer: ``status``, ``payload``, ``error_code``,
        ``error``, ``exit_code`` and ``permanent``.
    :param host_id: The host that answered, named in the capability message.
    :raises WorkspaceOpError: a K13 code with the reply's message and
        ``permanent`` (always ``True`` for ``workspace.capability_unavailable``
        and ``workspace.worktree_displaced``, always ``False`` for
        ``workspace.timeout``);
        ``workspace.capability_unavailable`` (permanent) for ``unknown_op``;
        ``workspace.backend_unavailable`` (permanent) for any other code or a
        malformed reply.
    :raises ValueError: for ``workspace.invalid_params``, a caller bug the host caught.
    """
    status = reply.get("status")
    if status == "ok":
        payload = reply.get("payload")
        if not isinstance(payload, Mapping):
            raise _unusable("an ok reply without a JSON object payload")
        return cast("Mapping[str, object]", payload)
    code = reply.get("error_code")
    error = reply.get("error")
    message = error if isinstance(error, str) else ""
    if status != "failed" or not isinstance(code, str):
        raise _unusable(f"a reply with status {status!r} and code {code!r}")
    if code == _INVALID_PARAMS:
        raise ValueError(message)
    if code == _UNKNOWN_OP:
        raise host_capability_unavailable(host_id, message or None)
    if code in WORKSPACE_ERROR_CODES:
        # A missing capability or a displaced worktree never mends by retrying;
        # a timeout may pass.
        permanent = code in ALWAYS_PERMANENT_CODES or (
            code != "workspace.timeout" and reply.get("permanent") is True
        )
        raise WorkspaceOpError(cast("WorkspaceErrorCode", code), message, permanent=permanent)
    # A frame-level failure (invalid_request, handler_failed, invalid_payload,
    # result_too_large) or a code this engine does not know: a retry will not help.
    raise _unusable(f"{code}: {message}")


def host_capability_unavailable(
    host_id: str | None, detail: str | None = None
) -> WorkspaceOpError:
    """
    The permanent error for a host that cannot serve Coral's ops at all.

    Either the host is too old for the channel, or its Coral handlers are
    switched off; the message names both remedies.
    """
    host = f"host {host_id}" if host_id else "the host"
    message = (
        f"{host} cannot run Coral workspace ops: update it, or unset "
        "CORAL_DISABLE_HOST_ENTRY_POINTS"
    )
    if detail:
        message = f"{message} ({detail})"
    return WorkspaceOpError("workspace.capability_unavailable", message, permanent=True)


class HostWorkspaceOps(WorkspaceOps):
    """
    K13 over one host channel, for one repository binding.

    :param channel: Sends one op to a host and returns its payload; raises
        mapped errors (see :func:`map_host_reply`).
    :param repo_root: The bound repository's main worktree on the host, canonical.
    :param read_timeout_s: Host deadline for READ ops.
    :param write_timeout_s: Host deadline for WRITE ops.
    """

    def __init__(
        self,
        channel: HostChannelBackend,
        *,
        repo_root: str,
        read_timeout_s: float = READ_TIMEOUT_S,
        write_timeout_s: float = WRITE_TIMEOUT_S,
    ) -> None:
        self._channel = channel
        self._repo_root = repo_root
        self._read_timeout_s = read_timeout_s
        self._write_timeout_s = write_timeout_s

    # ── READ ops ────────────────────────────────────────────────────────────

    @override
    async def fingerprint(
        self, ref: WorkspaceRef, executor: OpExecutor, *, level: FingerprintLevel
    ) -> Fingerprint:
        check_op_host("fingerprint", executor, level=level)
        if level != "L1":
            raise _not_served(f"fingerprint({level})")
        payload = await self._read(ref, executor, "fingerprint", level=level)
        if payload.text("level") != "L1":
            raise payload.malformed("level")
        return Fingerprint(
            level="L1",
            digest=payload.matching("digest", _SHA256),
            head=payload.commit_id("head"),
            dirty_count=payload.count("dirty_count"),
        )

    @override
    async def head(self, ref: WorkspaceRef, executor: OpExecutor) -> HeadResult:
        check_op_host("head", executor)
        payload = await self._read(ref, executor, "head")
        return HeadResult(
            head=payload.commit_id("head"),
            branch=payload.optional_text("branch"),
            merge_in_progress=payload.flag("merge_in_progress"),
        )

    @override
    async def diff_stat(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        from_commit: str,
        to_commit: str | None = None,
    ) -> DiffStat:
        check_op_host("diff_stat", executor)
        validate_commit_id(from_commit)
        if to_commit is not None:
            validate_commit_id(to_commit)
        payload = await self._read(
            ref, executor, "diff_stat", from_commit=from_commit, to_commit=to_commit
        )
        paths = payload.texts("paths")
        files_changed = payload.count("files_changed")
        # A host cuts a list too large for its channel; an older host never does.
        truncated = payload.optional_flag("paths_truncated")
        if files_changed < len(paths) or (files_changed > len(paths) and not truncated):
            raise payload.malformed("files_changed")
        return DiffStat(
            files_changed=files_changed,
            insertions=payload.count("insertions"),
            deletions=payload.count("deletions"),
            paths=paths,
            paths_truncated=truncated,
        )

    @override
    async def read(
        self, ref: WorkspaceRef, executor: OpExecutor, *, path: str, at_commit: str | None = None
    ) -> ReadResult:
        check_op_host("read", executor)
        validate_workspace_path(path)
        if at_commit is not None:
            validate_commit_id(at_commit)
        payload = await self._read(ref, executor, "read", path=path, at_commit=at_commit)
        if payload.text("path") != path:
            raise payload.malformed("path")
        try:
            content = base64.b64decode(payload.text("content_b64"), validate=True)
        except (binascii.Error, ValueError):
            raise payload.malformed("content_b64") from None
        sha256 = payload.text("sha256")
        if hashlib.sha256(content).hexdigest() != sha256:
            raise payload.malformed("sha256")
        return ReadResult(path=path, content=content, sha256=sha256)

    # ── WRITE ops ───────────────────────────────────────────────────────────

    @override
    async def commit(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        expected_head: str,
        message: str,
        trailers: Mapping[str, str] | None = None,
        run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> CommitResult:
        check_op_host("commit", executor)
        validate_op_key(op_key)
        validate_commit_id(expected_head)
        validate_commit_message(message)
        caller_trailers = dict(trailers or {})
        validate_trailers(caller_trailers)
        for record_id in (run_id, attempt_id):
            if record_id is not None:
                validate_record_id(record_id)
        payload = await self._write(
            ref,
            executor,
            "commit",
            op_key,
            expected_head=expected_head,
            message=message,
            # Pairs keep the caller's order, which the commit's trailer block follows.
            trailers=[[key, value] for key, value in caller_trailers.items()],
            run_id=run_id,
            attempt_id=attempt_id,
        )
        result = CommitResult(commit=payload.commit_id("commit"), empty=payload.flag("empty"))
        # Nothing recorded means the branch stayed at the HEAD the caller expected.
        if result.empty and result.commit != expected_head:
            raise payload.malformed("commit")
        return result

    @override
    async def salvage(
        self, ref: WorkspaceRef, executor: OpExecutor, *, op_key: str
    ) -> SalvageResult:
        check_op_host("salvage", executor)
        ref_name = salvage_ref_name(op_key)
        payload = await self._write(ref, executor, "salvage", op_key)
        if payload.text("ref") != ref_name:
            raise payload.malformed("ref")
        return SalvageResult(ref=ref_name, commit=payload.optional_commit_id("commit"))

    @override
    async def reset(
        self, ref: WorkspaceRef, executor: OpExecutor, *, op_key: str, commit: str
    ) -> ResetResult:
        check_op_host("reset", executor)
        validate_op_key(op_key)
        validate_commit_id(commit)
        payload = await self._write(ref, executor, "reset", op_key, commit=commit)
        head = payload.commit_id("head")
        if head != commit:
            raise payload.malformed("head")
        return ResetResult(head=head)

    @override
    async def merge(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        source_ref: str,
        message: str,
    ) -> MergeResult:
        check_op_host("merge", executor)
        raise _not_served("merge")

    @override
    async def check(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        *,
        op_key: str,
        argv: Sequence[str],
        timeout_s: float,
    ) -> CheckResult:
        check_op_host("check", executor)
        raise _not_served("check")

    # ── Internals ───────────────────────────────────────────────────────────

    async def _read(
        self, ref: WorkspaceRef, executor: OpExecutor, op: OpName, **params: object
    ) -> _Payload:
        return await self._request(ref, executor, op, None, self._read_timeout_s, params)

    async def _write(
        self, ref: WorkspaceRef, executor: OpExecutor, op: OpName, op_key: str, **params: object
    ) -> _Payload:
        return await self._request(ref, executor, op, op_key, self._write_timeout_s, params)

    async def _request(
        self,
        ref: WorkspaceRef,
        executor: OpExecutor,
        op: OpName,
        op_key: str | None,
        timeout_s: float,
        params: Mapping[str, object],
    ) -> _Payload:
        if isinstance(executor, HostChannel) and executor.host_id != ref.host_id:
            raise WorkspaceOpError(
                "workspace.target_mismatch", f"{ref.root} is not on host {executor.host_id}"
            )
        payload = await self._channel.request(
            ref.host_id,
            op,
            root=ref.root,
            params={"repo_root": self._repo_root, "branch": ref.branch, **params},
            timeout_s=timeout_s,
            op_key=op_key,
        )
        if not isinstance(payload, Mapping):
            raise _unusable(f"a {op} payload that is not a JSON object")
        return _Payload(op, payload)


class _Payload:
    """Typed access to one op's payload; anything malformed is permanent."""

    def __init__(self, op: str, payload: Mapping[str, object]) -> None:
        self._op = op
        self._payload = payload

    def malformed(self, name: str) -> WorkspaceOpError:
        return _unusable(f"a {self._op} payload with a malformed {name!r}")

    def text(self, name: str) -> str:
        value = self._payload.get(name)
        if not isinstance(value, str):
            raise self.malformed(name)
        return value

    def optional_text(self, name: str) -> str | None:
        if name not in self._payload:
            raise self.malformed(name)
        value = self._payload[name]
        return None if value is None else self.text(name)

    def matching(self, name: str, pattern: re.Pattern[str]) -> str:
        value = self.text(name)
        if not pattern.fullmatch(value):
            raise self.malformed(name)
        return value

    def commit_id(self, name: str) -> str:
        return self.matching(name, COMMIT_ID)

    def optional_commit_id(self, name: str) -> str | None:
        if name in self._payload and self._payload[name] is None:
            return None
        return self.commit_id(name)

    def flag(self, name: str) -> bool:
        value = self._payload.get(name)
        if not isinstance(value, bool):
            raise self.malformed(name)
        return value

    def optional_flag(self, name: str) -> bool:
        """A flag that reads ``False`` when absent."""
        return name in self._payload and self.flag(name)

    def count(self, name: str) -> int:
        value = self._payload.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise self.malformed(name)
        return value

    def texts(self, name: str) -> tuple[str, ...]:
        value = self._payload.get(name)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise self.malformed(name)
        return tuple(value)


def _not_served(name: str) -> WorkspaceOpError:
    return WorkspaceOpError(
        "workspace.capability_unavailable",
        f"the host channel does not serve {name} at M2",
        permanent=True,
    )


def _unusable(detail: str) -> WorkspaceOpError:
    return WorkspaceOpError(
        "workspace.backend_unavailable", f"the host answered with {detail}", permanent=True
    )
