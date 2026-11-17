"""``HostWorkspaceOps`` and ``map_host_reply``: wire requests, payload parsing, reply mapping.

The channel here is scripted with raw host replies and maps them through
``map_host_reply``, as the in-process and server channels do. Real git runs in
the conformance suite's ``host`` entry and in ``tests/coral/omni/host/ops``.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from coral.workspace.host_backend import (
    HOST_CHANNEL_OPS,
    READ_TIMEOUT_S,
    WRITE_TIMEOUT_S,
    HostWorkspaceOps,
    host_capability_unavailable,
    map_host_reply,
)
from coral.workspace.ops import (
    CommitResult,
    DiffStat,
    Fingerprint,
    HeadResult,
    HostChannel,
    OpName,
    ReadResult,
    ResetResult,
    SalvageResult,
    StepSession,
    WorkspaceOpError,
    WorkspaceRef,
)

HOST_ID = "host-1"
REPO_ROOT = "/u/repo"
REF = WorkspaceRef(
    host_id=HOST_ID, root="/u/repo-worktrees/coral-r-1-base", branch="coral/r-1/base"
)
WRITER = StepSession("s-1", writable=True, at_turn_end=True)
READ_ONLY = StepSession("s-1", writable=False, at_turn_end=True)
HEAD = "a" * 40
NEW = "b" * 40
CONTENT = b"\x00bytes\n"


def _ok(payload: object) -> dict[str, object]:
    return {
        "status": "ok",
        "payload": payload,
        "error_code": None,
        "error": None,
        "exit_code": None,
        "permanent": False,
    }


def _failed(
    code: str | None, error: str = "detail", *, permanent: bool = False
) -> dict[str, object]:
    return {
        "status": "failed",
        "payload": None,
        "error_code": code,
        "error": error,
        "exit_code": 1,
        "permanent": permanent,
    }


@dataclass
class ScriptedChannel:
    """A host channel that answers each request with the next scripted raw reply."""

    replies: list[Mapping[str, object]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    async def request(
        self,
        host_id: str,
        op: OpName,
        *,
        root: str,
        params: Mapping[str, object],
        timeout_s: float,
        op_key: str | None,
    ) -> Mapping[str, object]:
        self.requests.append(
            {
                "host_id": host_id,
                "op": op,
                "root": root,
                "params": dict(params),
                "timeout_s": timeout_s,
                "op_key": op_key,
            }
        )
        return map_host_reply(self.replies.pop(0), host_id=host_id)


def _backend(*replies: Mapping[str, object]) -> tuple[HostWorkspaceOps, ScriptedChannel]:
    channel = ScriptedChannel(list(replies))
    return HostWorkspaceOps(channel, repo_root=REPO_ROOT), channel


def _wire(op: str, timeout_s: float, op_key: str | None = None, **params: object) -> dict:
    return {
        "host_id": HOST_ID,
        "op": op,
        "root": REF.root,
        "params": {"repo_root": REPO_ROOT, "branch": REF.branch, **params},
        "timeout_s": timeout_s,
        "op_key": op_key,
    }


# ── Wire requests and results ───────────────────────────────────────────────

OpCall = Callable[[HostWorkspaceOps], Awaitable[object]]

_ROUND_TRIPS: dict[str, tuple[OpCall, dict, dict, object]] = {
    "head": (
        lambda ops: ops.head(REF, READ_ONLY),
        _wire("head", READ_TIMEOUT_S),
        {"head": HEAD, "branch": "coral/r-1/base", "merge_in_progress": False},
        HeadResult(head=HEAD, branch="coral/r-1/base", merge_in_progress=False),
    ),
    "head-detached": (
        lambda ops: ops.head(REF, READ_ONLY),
        _wire("head", READ_TIMEOUT_S),
        {"head": HEAD, "branch": None, "merge_in_progress": True},
        HeadResult(head=HEAD, branch=None, merge_in_progress=True),
    ),
    "diff_stat": (
        lambda ops: ops.diff_stat(REF, READ_ONLY, from_commit=HEAD, to_commit=NEW),
        _wire("diff_stat", READ_TIMEOUT_S, from_commit=HEAD, to_commit=NEW),
        {"files_changed": 2, "insertions": 3, "deletions": 0, "paths": ["a.md", "b.md"]},
        DiffStat(files_changed=2, insertions=3, deletions=0, paths=("a.md", "b.md")),
    ),
    # A path list too large for the channel arrives cut; the counts still cover the diff.
    "diff_stat-paths-truncated": (
        lambda ops: ops.diff_stat(REF, READ_ONLY, from_commit=HEAD),
        _wire("diff_stat", READ_TIMEOUT_S, from_commit=HEAD, to_commit=None),
        {
            "files_changed": 9,
            "insertions": 9,
            "deletions": 0,
            "paths": ["a.md"],
            "paths_truncated": True,
        },
        DiffStat(
            files_changed=9, insertions=9, deletions=0, paths=("a.md",), paths_truncated=True
        ),
    ),
    "read": (
        lambda ops: ops.read(REF, READ_ONLY, path="data.bin", at_commit=HEAD),
        _wire("read", READ_TIMEOUT_S, path="data.bin", at_commit=HEAD),
        {
            "path": "data.bin",
            "content_b64": base64.b64encode(CONTENT).decode(),
            "sha256": hashlib.sha256(CONTENT).hexdigest(),
        },
        ReadResult(path="data.bin", content=CONTENT, sha256=hashlib.sha256(CONTENT).hexdigest()),
    ),
    "fingerprint": (
        lambda ops: ops.fingerprint(REF, READ_ONLY, level="L1"),
        _wire("fingerprint", READ_TIMEOUT_S, level="L1"),
        {"level": "L1", "digest": "c" * 64, "head": HEAD, "dirty_count": 4},
        Fingerprint(level="L1", digest="c" * 64, head=HEAD, dirty_count=4),
    ),
    "commit": (
        lambda ops: ops.commit(
            REF,
            WRITER,
            op_key="k-1",
            expected_head=HEAD,
            message="Review: done",
            trailers={"Reviewed-By": "x", "A-Run": "r"},
            run_id="r-1",
            attempt_id="a-1",
        ),
        _wire(
            "commit",
            WRITE_TIMEOUT_S,
            "k-1",
            expected_head=HEAD,
            message="Review: done",
            trailers=[["Reviewed-By", "x"], ["A-Run", "r"]],
            run_id="r-1",
            attempt_id="a-1",
        ),
        {"commit": NEW, "empty": False},
        CommitResult(commit=NEW, empty=False),
    ),
    "commit-without-ids": (
        lambda ops: ops.commit(REF, WRITER, op_key="k-1", expected_head=HEAD, message="m"),
        _wire(
            "commit",
            WRITE_TIMEOUT_S,
            "k-1",
            expected_head=HEAD,
            message="m",
            trailers=[],
            run_id=None,
            attempt_id=None,
        ),
        {"commit": HEAD, "empty": True},
        CommitResult(commit=HEAD, empty=True),
    ),
    "salvage": (
        lambda ops: ops.salvage(REF, HostChannel(HOST_ID), op_key="k-2"),
        _wire("salvage", WRITE_TIMEOUT_S, "k-2"),
        {"ref": "refs/coral/salvage/k-2", "commit": NEW},
        SalvageResult(ref="refs/coral/salvage/k-2", commit=NEW),
    ),
    "salvage-clean": (
        lambda ops: ops.salvage(REF, WRITER, op_key="k-2"),
        _wire("salvage", WRITE_TIMEOUT_S, "k-2"),
        {"ref": "refs/coral/salvage/k-2", "commit": None},
        SalvageResult(ref="refs/coral/salvage/k-2", commit=None),
    ),
    "reset": (
        lambda ops: ops.reset(REF, HostChannel(HOST_ID), op_key="k-3", commit=HEAD),
        _wire("reset", WRITE_TIMEOUT_S, "k-3", commit=HEAD),
        {"head": HEAD},
        ResetResult(head=HEAD),
    ),
}


@pytest.mark.parametrize("case", list(_ROUND_TRIPS.values()), ids=list(_ROUND_TRIPS))
async def test_each_served_op_sends_its_wire_request_and_parses_the_payload(
    case: tuple[OpCall, dict, dict, object],
) -> None:
    call, wire, payload, expected = case
    ops, channel = _backend(_ok(payload))

    assert await call(ops) == expected

    assert channel.requests == [wire]


def test_the_host_channel_serves_seven_ops() -> None:
    assert (
        frozenset({"head", "diff_stat", "read", "fingerprint-L1", "commit", "salvage", "reset"})
        == HOST_CHANNEL_OPS
    )
    assert READ_TIMEOUT_S <= WRITE_TIMEOUT_S <= 900


# ── Refusals before anything is sent ────────────────────────────────────────

_WRITES: dict[str, OpCall] = {
    "commit": lambda ops: ops.commit(
        REF, READ_ONLY, op_key="Not A Key", expected_head="HEAD", message=""
    ),
    "salvage": lambda ops: ops.salvage(REF, READ_ONLY, op_key="Not A Key"),
    "reset": lambda ops: ops.reset(REF, READ_ONLY, op_key="Not A Key", commit="HEAD"),
    "merge": lambda ops: ops.merge(
        REF, READ_ONLY, op_key="Not A Key", source_ref="main", message=""
    ),
    "check": lambda ops: ops.check(REF, READ_ONLY, op_key="Not A Key", argv=["x"], timeout_s=0),
    "fingerprint-L2": lambda ops: ops.fingerprint(REF, READ_ONLY, level="L2"),
}


@pytest.mark.parametrize("call", list(_WRITES.values()), ids=list(_WRITES))
async def test_the_op_host_rule_comes_first_and_sends_nothing(call: OpCall) -> None:
    ops, channel = _backend()

    with pytest.raises(WorkspaceOpError) as raised:
        await call(ops)

    assert raised.value.code == "workspace.op_host_violation"
    assert channel.requests == []


_INVALID: dict[str, OpCall] = {
    "diff_stat-from": lambda ops: ops.diff_stat(REF, WRITER, from_commit="HEAD"),
    "diff_stat-to": lambda ops: ops.diff_stat(REF, WRITER, from_commit=HEAD, to_commit="abc"),
    "read-path": lambda ops: ops.read(REF, WRITER, path="../outside"),
    "read-at-commit": lambda ops: ops.read(REF, WRITER, path="a", at_commit="HEAD"),
    "commit-op-key": lambda ops: ops.commit(
        REF, WRITER, op_key="A", expected_head=HEAD, message="m"
    ),
    "commit-expected-head": lambda ops: ops.commit(
        REF, WRITER, op_key="k", expected_head="HEAD", message="m"
    ),
    "commit-message": lambda ops: ops.commit(
        REF, WRITER, op_key="k", expected_head=HEAD, message=" "
    ),
    "commit-trailers": lambda ops: ops.commit(
        REF, WRITER, op_key="k", expected_head=HEAD, message="m", trailers={"Coral-Op": "x"}
    ),
    "commit-run-id": lambda ops: ops.commit(
        REF, WRITER, op_key="k", expected_head=HEAD, message="m", run_id="R 1"
    ),
    "commit-attempt-id": lambda ops: ops.commit(
        REF, WRITER, op_key="k", expected_head=HEAD, message="m", attempt_id=""
    ),
    "salvage-op-key": lambda ops: ops.salvage(REF, WRITER, op_key="a/b"),
    "reset-op-key": lambda ops: ops.reset(REF, WRITER, op_key="", commit=HEAD),
    "reset-commit": lambda ops: ops.reset(REF, WRITER, op_key="k", commit="A" * 40),
}


@pytest.mark.parametrize("call", list(_INVALID.values()), ids=list(_INVALID))
async def test_invalid_params_raise_value_error_before_sending(call: OpCall) -> None:
    ops, channel = _backend()

    with pytest.raises(ValueError):
        await call(ops)

    assert channel.requests == []


async def test_a_host_channel_to_another_host_is_a_target_mismatch_before_sending() -> None:
    ops, channel = _backend()
    other = HostChannel("host-2")
    calls = [
        ops.head(REF, other),
        ops.diff_stat(REF, other, from_commit=HEAD),
        ops.read(REF, other, path="README.md"),
        ops.fingerprint(REF, other, level="L1"),
        ops.commit(REF, other, op_key="k", expected_head=HEAD, message="m"),
        ops.salvage(REF, other, op_key="k"),
        ops.reset(REF, other, op_key="k", commit=HEAD),
    ]

    for call in calls:
        with pytest.raises(WorkspaceOpError) as raised:
            await call
        assert raised.value.code == "workspace.target_mismatch"

    assert channel.requests == []


_UNSERVED: dict[str, OpCall] = {
    "fingerprint-L2": lambda ops: ops.fingerprint(REF, WRITER, level="L2"),
    "merge": lambda ops: ops.merge(
        REF, WRITER, op_key="k", source_ref="refs/heads/coral/r-1/agent", message="m"
    ),
    "check": lambda ops: ops.check(REF, HostChannel(HOST_ID), op_key="k", argv=["x"], timeout_s=5),
}


@pytest.mark.parametrize("call", list(_UNSERVED.values()), ids=list(_UNSERVED))
async def test_unserved_ops_are_permanently_unavailable(call: OpCall) -> None:
    ops, channel = _backend()

    with pytest.raises(WorkspaceOpError) as raised:
        await call(ops)

    assert raised.value.code == "workspace.capability_unavailable"
    assert raised.value.permanent is True
    assert channel.requests == []


# ── Payload parsing ─────────────────────────────────────────────────────────

_BAD_PAYLOADS: dict[str, tuple[OpCall, object]] = {
    "head-short-commit": (
        lambda ops: ops.head(REF, WRITER),
        {"head": "abc", "branch": None, "merge_in_progress": False},
    ),
    "head-flag-not-bool": (
        lambda ops: ops.head(REF, WRITER),
        {"head": HEAD, "branch": None, "merge_in_progress": 0},
    ),
    "head-missing-branch": (
        lambda ops: ops.head(REF, WRITER),
        {"head": HEAD, "merge_in_progress": False},
    ),
    "diff_stat-count-is-bool": (
        lambda ops: ops.diff_stat(REF, WRITER, from_commit=HEAD),
        {"files_changed": True, "insertions": 0, "deletions": 0, "paths": ["a"]},
    ),
    "diff_stat-negative": (
        lambda ops: ops.diff_stat(REF, WRITER, from_commit=HEAD),
        {"files_changed": 0, "insertions": -1, "deletions": 0, "paths": []},
    ),
    "diff_stat-count-mismatch": (
        lambda ops: ops.diff_stat(REF, WRITER, from_commit=HEAD),
        {"files_changed": 2, "insertions": 0, "deletions": 0, "paths": ["a"]},
    ),
    "diff_stat-more-paths-than-files": (
        lambda ops: ops.diff_stat(REF, WRITER, from_commit=HEAD),
        {
            "files_changed": 1,
            "insertions": 0,
            "deletions": 0,
            "paths": ["a", "b"],
            "paths_truncated": True,
        },
    ),
    "diff_stat-path-not-str": (
        lambda ops: ops.diff_stat(REF, WRITER, from_commit=HEAD),
        {"files_changed": 1, "insertions": 0, "deletions": 0, "paths": [5]},
    ),
    "read-other-path": (
        lambda ops: ops.read(REF, WRITER, path="a"),
        {"path": "b", "content_b64": "", "sha256": hashlib.sha256(b"").hexdigest()},
    ),
    "read-not-base64": (
        lambda ops: ops.read(REF, WRITER, path="a"),
        {"path": "a", "content_b64": "***", "sha256": hashlib.sha256(b"").hexdigest()},
    ),
    "read-wrong-sha256": (
        lambda ops: ops.read(REF, WRITER, path="a"),
        {"path": "a", "content_b64": "eA==", "sha256": hashlib.sha256(b"y").hexdigest()},
    ),
    "fingerprint-other-level": (
        lambda ops: ops.fingerprint(REF, WRITER, level="L1"),
        {"level": "L2", "digest": "c" * 64, "head": HEAD, "dirty_count": 0},
    ),
    "fingerprint-digest-not-sha256": (
        lambda ops: ops.fingerprint(REF, WRITER, level="L1"),
        {"level": "L1", "digest": "c" * 40, "head": HEAD, "dirty_count": 0},
    ),
    "commit-not-hex": (
        lambda ops: ops.commit(REF, WRITER, op_key="k", expected_head=HEAD, message="m"),
        {"commit": "HEAD", "empty": False},
    ),
    "commit-empty-not-bool": (
        lambda ops: ops.commit(REF, WRITER, op_key="k", expected_head=HEAD, message="m"),
        {"commit": NEW, "empty": "no"},
    ),
    "salvage-other-ref": (
        lambda ops: ops.salvage(REF, WRITER, op_key="k"),
        {"ref": "refs/coral/salvage/other", "commit": NEW},
    ),
    "reset-missing-head": (
        lambda ops: ops.reset(REF, WRITER, op_key="k", commit=HEAD),
        {"commit": HEAD},
    ),
    "reset-to-another-commit": (
        lambda ops: ops.reset(REF, WRITER, op_key="k", commit=HEAD),
        {"head": NEW},
    ),
    "commit-empty-off-expected-head": (
        lambda ops: ops.commit(REF, WRITER, op_key="k", expected_head=HEAD, message="m"),
        {"commit": NEW, "empty": True},
    ),
}


@pytest.mark.parametrize("case", list(_BAD_PAYLOADS.values()), ids=list(_BAD_PAYLOADS))
async def test_a_malformed_payload_is_permanently_unavailable(
    case: tuple[OpCall, object],
) -> None:
    call, payload = case
    ops, _channel = _backend(_ok(payload))

    with pytest.raises(WorkspaceOpError) as raised:
        await call(ops)

    assert raised.value.code == "workspace.backend_unavailable"
    assert raised.value.permanent is True


# ── Reply mapping ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "code",
    [
        "workspace.backend_unavailable",
        "workspace.git_failed",
        "workspace.op_key_conflict",
        "workspace.target_mismatch",
    ],
)
@pytest.mark.parametrize("permanent", [False, True])
async def test_a_k13_failure_keeps_its_code_message_and_permanence(
    code: str, permanent: bool
) -> None:
    ops, _channel = _backend(_failed(code, "git reset failed", permanent=permanent))

    with pytest.raises(WorkspaceOpError) as raised:
        await ops.reset(REF, WRITER, op_key="k", commit=HEAD)

    assert (raised.value.code, raised.value.message) == (code, "git reset failed")
    assert raised.value.permanent is permanent


@pytest.mark.parametrize(
    ("code", "permanent"),
    [
        ("workspace.capability_unavailable", True),
        ("workspace.worktree_displaced", True),
        ("workspace.timeout", False),
    ],
)
@pytest.mark.parametrize("sent", [False, True], ids=["sent-retryable", "sent-permanent"])
async def test_capability_is_always_permanent_and_a_timeout_never_is(
    code: str, permanent: bool, sent: bool
) -> None:
    ops, _channel = _backend(_failed(code, "host detail", permanent=sent))

    with pytest.raises(WorkspaceOpError) as raised:
        await ops.reset(REF, WRITER, op_key="k", commit=HEAD)

    assert (raised.value.code, raised.value.message) == (code, "host detail")
    assert raised.value.permanent is permanent


async def test_invalid_params_on_the_host_raise_value_error() -> None:
    ops, _channel = _backend(_failed("workspace.invalid_params", "unknown params ['x']"))

    with pytest.raises(ValueError, match=r"unknown params \['x'\]"):
        await ops.head(REF, WRITER)


async def test_an_unknown_op_means_the_host_cannot_run_coral_ops() -> None:
    ops, _channel = _backend(_failed("unknown_op", "this host has no workspace op 'commit'"))

    with pytest.raises(WorkspaceOpError) as raised:
        await ops.commit(REF, WRITER, op_key="k", expected_head=HEAD, message="m")

    error = raised.value
    assert (error.code, error.permanent) == ("workspace.capability_unavailable", True)
    assert f"host {HOST_ID} cannot run Coral workspace ops" in error.message
    assert "CORAL_DISABLE_HOST_ENTRY_POINTS" in error.message
    assert "this host has no workspace op 'commit'" in error.message
    assert "omnigent" not in error.message.lower()


def test_an_unsupported_host_gets_the_same_capability_error() -> None:
    error = host_capability_unavailable(HOST_ID)

    assert (error.code, error.permanent) == ("workspace.capability_unavailable", True)
    assert error.message == (
        f"host {HOST_ID} cannot run Coral workspace ops: update it, or unset "
        "CORAL_DISABLE_HOST_ENTRY_POINTS"
    )


@pytest.mark.parametrize(
    "reply",
    [
        _failed("invalid_request"),
        _failed("handler_failed"),
        _failed("invalid_payload", permanent=True),
        _failed("result_too_large", permanent=True),
        _failed("workspace.something_new"),
        _failed("anything_else"),
        _failed(None),
        _ok(None),
        _ok(["not", "a", "mapping"]),
        {**_ok({}), "status": "maybe"},
    ],
    ids=[
        "invalid_request",
        "handler_failed",
        "invalid_payload",
        "result_too_large",
        "unknown-workspace-code",
        "other-code",
        "no-code",
        "ok-without-payload",
        "ok-with-a-list",
        "unknown-status",
    ],
)
def test_any_other_reply_is_permanently_unavailable(reply: Mapping[str, object]) -> None:
    with pytest.raises(WorkspaceOpError) as raised:
        map_host_reply(reply, host_id=HOST_ID)

    assert (raised.value.code, raised.value.permanent) == ("workspace.backend_unavailable", True)


def test_an_ok_reply_returns_its_payload() -> None:
    assert map_host_reply(_ok({"head": HEAD})) == {"head": HEAD}


async def test_channel_errors_reach_the_caller_unchanged() -> None:
    timeout = WorkspaceOpError("workspace.timeout", "no reply in time")

    class FailingChannel:
        async def request(self, *args: object, **kwargs: object) -> Mapping[str, object]:
            raise timeout

    ops = HostWorkspaceOps(FailingChannel(), repo_root=REPO_ROOT)

    with pytest.raises(WorkspaceOpError) as raised:
        await ops.salvage(REF, WRITER, op_key="k")

    assert raised.value is timeout
