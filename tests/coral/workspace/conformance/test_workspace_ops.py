"""K13 draft v1 contract obligations, run against every ``WorkspaceOps`` backend.

``BACKENDS`` maps a backend id to a factory. A factory takes the pytest
``request`` (so it can pull fixtures such as a live server with
``request.getfixturevalue``) and ``tmp_path``, and returns an async context
manager that yields a ``BackendUnderTest`` over a fresh worktree holding
``INITIAL_FILES`` at one commit, then tears it down. A backend joins the suite
by adding a factory; the ``backend`` fixture is parametrized over ``BACKENDS``.
Each factory also supplies a ``WorkspaceSetup``, the backend-specific hook that
mutates the working tree and prepares refs, because K13 itself offers neither.

Only the in-memory fake is registered today, so these tests pin the contract
text (``docs/coral/contracts/workspace-ops.md``), not real git. The same suite
passing on a real backend gates CRL-128.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol

import pytest

from coral.workspace.fake import FakeWorkspaceOps
from coral.workspace.ops import (
    MAX_CHECK_TIMEOUT_S,
    MAX_READ_BYTES,
    CheckResult,
    CommitResult,
    Fingerprint,
    FingerprintLevel,
    HostChannel,
    OpExecutor,
    OpName,
    StepSession,
    WorkspaceOpError,
    WorkspaceOps,
    WorkspaceRef,
    check_op_host,
    commit_params_digest,
    salvage_ref_name,
    validate_commit_id,
    validate_coral_ref,
    validate_op_key,
    validate_timeout,
    validate_trailers,
)

INITIAL_FILES: Mapping[str, bytes] = {
    "README.md": b"hello\n",
    "src/app.py": b"print('app')\n",
}
AGENT_REF = "refs/heads/coral/r-test/agent-1"
UNKNOWN_COMMIT = "0" * 40


class WorkspaceSetup(Protocol):
    """Backend-specific test setup: the working-tree and ref changes K13 never makes."""

    def write_file(self, path: str, content: bytes) -> None: ...

    def delete_file(self, path: str) -> None: ...

    def ignore(self, path: str) -> None:
        """Ignore ``path`` without changing the tree: a real backend appends it to
        ``git rev-parse --git-path info/exclude``, never to a tracked ``.gitignore``."""
        ...

    def add_ref(self, name: str, files: Mapping[str, bytes]) -> str:
        """Point full ref ``name`` at a new commit on HEAD with ``files`` written; return it."""
        ...

    def add_conflicting_ref(self, name: str, path: str) -> None:
        """Create full ref ``name`` whose merge into HEAD conflicts on ``path`` (HEAD may move)."""
        ...

    def check_argv(self, exit_code: int | None) -> tuple[str, ...]:
        """Argv that exits with ``exit_code``; for ``None``, one that runs well past 1 s."""
        ...


@dataclass(frozen=True)
class BackendUnderTest:
    ops: WorkspaceOps
    ref: WorkspaceRef
    # A writable step session at a turn end: it may run every op.
    session: StepSession
    setup: WorkspaceSetup


BackendFactory = Callable[
    [pytest.FixtureRequest, Path], AbstractAsyncContextManager[BackendUnderTest]
]


@dataclass(frozen=True)
class _FakeSetup:
    fake: FakeWorkspaceOps
    ref: WorkspaceRef

    def write_file(self, path: str, content: bytes) -> None:
        self.fake.write_file(self.ref, path, content)

    def delete_file(self, path: str) -> None:
        self.fake.delete_file(self.ref, path)

    def ignore(self, path: str) -> None:
        self.fake.ignore(self.ref, path)

    def add_ref(self, name: str, files: Mapping[str, bytes]) -> str:
        return self.fake.add_ref(self.ref, name, files)

    def add_conflicting_ref(self, name: str, path: str) -> None:
        self.fake.add_ref(self.ref, name, {path: b"theirs\n"})
        self.fake.script_merge_conflict(self.ref, name, (path,))

    def check_argv(self, exit_code: int | None) -> tuple[str, ...]:
        argv = ("probe", "overrun" if exit_code is None else f"exit-{exit_code}")
        result = CheckResult(
            exit_code=exit_code,
            timed_out=exit_code is None,
            stdout_tail="",
            stderr_tail="",
            duration_ms=1,
        )
        self.fake.script_check(self.ref, argv, result)
        return argv


@asynccontextmanager
async def _fake_backend(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[BackendUnderTest]:
    fake = FakeWorkspaceOps()
    ref = WorkspaceRef(
        host_id="host-1",
        root=str(tmp_path / "repo-worktrees" / "coral-r-test-base"),
        branch="coral/r-test/base",
    )
    fake.add_workspace(ref, INITIAL_FILES)
    yield BackendUnderTest(
        ops=fake,
        ref=ref,
        session=StepSession("step-1", writable=True, at_turn_end=True),
        setup=_FakeSetup(fake, ref),
    )


BACKENDS: dict[str, BackendFactory] = {"fake": _fake_backend}


@pytest.fixture(params=sorted(BACKENDS))
async def backend(
    request: pytest.FixtureRequest, tmp_path: Path
) -> AsyncIterator[BackendUnderTest]:
    async with BACKENDS[request.param](request, tmp_path) as under_test:
        yield under_test


async def _fingerprint(backend: BackendUnderTest, level: FingerprintLevel = "L1") -> Fingerprint:
    return await backend.ops.fingerprint(backend.ref, backend.session, level=level)


async def _head(backend: BackendUnderTest) -> str:
    return (await backend.ops.head(backend.ref, backend.session)).head


async def _read(backend: BackendUnderTest, path: str, at_commit: str | None = None) -> bytes:
    result = await backend.ops.read(backend.ref, backend.session, path=path, at_commit=at_commit)
    return result.content


async def _commit(
    backend: BackendUnderTest,
    op_key: str,
    message: str = "m",
    *,
    expected_head: str | None = None,
    trailers: Mapping[str, str] | None = None,
) -> CommitResult:
    return await backend.ops.commit(
        backend.ref,
        backend.session,
        op_key=op_key,
        expected_head=await _head(backend) if expected_head is None else expected_head,
        message=message,
        trailers=trailers,
    )


async def _assert_error(code: str, call: Awaitable[object]) -> None:
    with pytest.raises(WorkspaceOpError) as raised:
        await call
    assert raised.value.code == code


async def _assert_missing(
    backend: BackendUnderTest, path: str, at_commit: str | None = None
) -> None:
    await _assert_error("workspace.git_failed", _read(backend, path, at_commit))


# ── Op-host rule ────────────────────────────────────────────────────────────

WRITER = StepSession("s-1", writable=True, at_turn_end=True)
READ_ONLY = StepSession("s-1", writable=False, at_turn_end=True)
MID_TURN = StepSession("s-1", writable=True, at_turn_end=False)
READ_ONLY_MID_TURN = StepSession("s-1", writable=False, at_turn_end=False)
HOST = HostChannel("host-1")

WRITE_CALLS: list[tuple[OpName, FingerprintLevel | None]] = [
    ("commit", None),
    ("salvage", None),
    ("reset", None),
    ("merge", None),
    ("check", None),
    ("fingerprint", "L2"),
]
READ_CALLS: list[tuple[OpName, FingerprintLevel | None]] = [
    ("fingerprint", "L1"),
    ("head", None),
    ("diff_stat", None),
    ("read", None),
]


@pytest.mark.parametrize(("op", "level"), WRITE_CALLS)
@pytest.mark.parametrize(
    "executor",
    [READ_ONLY, MID_TURN, READ_ONLY_MID_TURN],
    ids=["read-only", "mid-turn", "read-only-mid-turn"],
)
def test_write_ops_need_a_writable_session_at_turn_end(
    op: OpName, level: FingerprintLevel | None, executor: StepSession
) -> None:
    with pytest.raises(WorkspaceOpError) as raised:
        check_op_host(op, executor, level=level)
    assert raised.value.code == "workspace.op_host_violation"
    assert executor.session_id in raised.value.message


@pytest.mark.parametrize(("op", "level"), WRITE_CALLS)
@pytest.mark.parametrize("executor", [WRITER, HOST], ids=["writer-at-turn-end", "host-channel"])
def test_write_ops_run_for_a_writer_at_turn_end_or_the_host_channel(
    op: OpName, level: FingerprintLevel | None, executor: OpExecutor
) -> None:
    check_op_host(op, executor, level=level)


@pytest.mark.parametrize(("op", "level"), READ_CALLS)
@pytest.mark.parametrize(
    "executor",
    [WRITER, READ_ONLY, MID_TURN, READ_ONLY_MID_TURN, HOST],
    ids=["writer", "read-only", "mid-turn", "read-only-mid-turn", "host-channel"],
)
def test_read_ops_run_for_every_executor(
    op: OpName, level: FingerprintLevel | None, executor: OpExecutor
) -> None:
    check_op_host(op, executor, level=level)


@pytest.mark.parametrize(
    ("op", "level"),
    [("push", None), ("fingerprint", None), ("fingerprint", "L3"), ("commit", "L1")],
    ids=["unknown-op", "fingerprint-without-level", "unknown-level", "level-on-commit"],
)
def test_check_op_host_rejects_unknown_ops_and_misused_levels(op: str, level: str | None) -> None:
    with pytest.raises(ValueError):
        check_op_host(op, WRITER, level=level)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "executor",
    [SimpleNamespace(session_id="s-1", writable="false", at_turn_end=True), None],
    ids=["duck-typed", "none"],
)
@pytest.mark.parametrize(("op", "level"), [("commit", None), ("head", None)])
def test_check_op_host_rejects_an_unknown_executor(
    executor: object, op: OpName, level: FingerprintLevel | None
) -> None:
    with pytest.raises(TypeError):
        check_op_host(op, executor, level=level)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("writable", "at_turn_end"),
    [("false", True), (True, 1), (None, True)],
    ids=["string-flag", "int-flag", "none-flag"],
)
def test_step_session_flags_must_be_bools(writable: object, at_turn_end: object) -> None:
    with pytest.raises(TypeError):
        StepSession("s-1", writable=writable, at_turn_end=at_turn_end)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        StepSession("", writable=True, at_turn_end=True)


def test_validators_accept_their_documented_bounds() -> None:
    validate_commit_id("a" * 40)
    validate_commit_id("b" * 64)
    validate_op_key("k" * 128)
    validate_timeout(1)
    validate_timeout(MAX_CHECK_TIMEOUT_S)
    validate_trailers({"K" * 64: "v"})
    validate_coral_ref("refs/heads/coral/r-test/base")
    validate_coral_ref("refs/coral/salvage/k-1")
    validate_coral_ref(f"refs/coral/{'a' * 100}/{'b' * 100}/{'c' * 42}")
    assert commit_params_digest("m", {"A": "1", "B": "2"}) == commit_params_digest(
        "m", {"B": "2", "A": "1"}
    )


def _write_op_calls(
    backend: BackendUnderTest, ref: WorkspaceRef, base: str, op_key: str | None = None
) -> dict[str, Callable[[OpExecutor], Awaitable[object]]]:
    """One call per WRITE op; ``op_key``, when given, replaces each op's own key."""
    ops = backend.ops
    check_argv = backend.setup.check_argv(0)

    def key(op: str) -> str:
        return f"k-{op}" if op_key is None else op_key

    return {
        "commit": lambda ex: ops.commit(
            ref, ex, op_key=key("commit"), expected_head=base, message="m"
        ),
        "salvage": lambda ex: ops.salvage(ref, ex, op_key=key("salvage")),
        "reset": lambda ex: ops.reset(ref, ex, op_key=key("reset"), commit=base),
        "merge": lambda ex: ops.merge(
            ref, ex, op_key=key("merge"), source_ref=AGENT_REF, message="m"
        ),
        "check": lambda ex: ops.check(ref, ex, op_key=key("check"), argv=check_argv, timeout_s=5),
        "fingerprint-L2": lambda ex: ops.fingerprint(ref, ex, level="L2"),
    }


WRITE_OP_IDS = ["commit", "salvage", "reset", "merge", "check", "fingerprint-L2"]
KEYED_WRITE_OP_IDS = [op for op in WRITE_OP_IDS if op != "fingerprint-L2"]


@pytest.mark.parametrize("op", WRITE_OP_IDS)
@pytest.mark.parametrize("turn_state", ["read-only", "mid-turn"])
async def test_backend_refuses_write_ops_before_changing_anything(
    backend: BackendUnderTest, op: str, turn_state: str
) -> None:
    backend.setup.add_ref(AGENT_REF, {"agent.txt": b"agent\n"})
    backend.setup.write_file("README.md", b"edited\n")
    before = await _fingerprint(backend)
    executor = (
        replace(backend.session, writable=False)
        if turn_state == "read-only"
        else replace(backend.session, at_turn_end=False)
    )
    # Invalid params too: the op-host rule comes before any validation.
    calls = _write_op_calls(backend, backend.ref, "HEAD", op_key="Not A Key")

    await _assert_error("workspace.op_host_violation", calls[op](executor))

    assert await _fingerprint(backend) == before
    assert await _read(backend, "README.md") == b"edited\n"


def _unverified_target(backend: BackendUnderTest, target: str) -> tuple[WorkspaceRef, OpExecutor]:
    """A ref and executor that must not reach ``backend.ref``'s worktree."""
    ref = backend.ref
    if target == "other-branch":
        return replace(ref, branch="coral/r-test/other"), backend.session
    if target == "user-branch":
        return replace(ref, branch="main"), backend.session
    if target == "other-host":
        return ref, HostChannel(ref.host_id + "-other")
    return replace(ref, root=ref.root + "-other"), backend.session


@pytest.mark.parametrize("op", WRITE_OP_IDS)
@pytest.mark.parametrize("target", ["other-branch", "user-branch", "other-root", "other-host"])
async def test_backend_refuses_write_ops_on_an_unverified_target(
    backend: BackendUnderTest, op: str, target: str
) -> None:
    base = await _head(backend)
    backend.setup.add_ref(AGENT_REF, {"agent.txt": b"agent\n"})
    backend.setup.write_file("README.md", b"edited\n")
    before = await _fingerprint(backend)
    wrong_ref, executor = _unverified_target(backend, target)

    await _assert_error(
        "workspace.target_mismatch", _write_op_calls(backend, wrong_ref, base)[op](executor)
    )

    assert await _fingerprint(backend) == before


@pytest.mark.parametrize("target", ["other-root", "other-host"])
async def test_backend_refuses_read_ops_on_an_unverified_target(
    backend: BackendUnderTest, target: str
) -> None:
    ops = backend.ops
    base = await _head(backend)
    unknown, session = _unverified_target(backend, target)

    calls: list[Callable[[], Awaitable[object]]] = [
        lambda: ops.fingerprint(unknown, session, level="L1"),
        lambda: ops.head(unknown, session),
        lambda: ops.diff_stat(unknown, session, from_commit=base),
        lambda: ops.read(unknown, session, path="README.md"),
    ]
    for call in calls:
        await _assert_error("workspace.target_mismatch", call())


async def test_backend_runs_read_ops_in_a_read_only_session_mid_turn(
    backend: BackendUnderTest,
) -> None:
    ops, ref = backend.ops, backend.ref
    reader = replace(backend.session, writable=False, at_turn_end=False)
    head = (await ops.head(ref, reader)).head

    fingerprint = await ops.fingerprint(ref, reader, level="L1")
    diff = await ops.diff_stat(ref, reader, from_commit=head)
    read = await ops.read(ref, reader, path="README.md")

    assert fingerprint.head == head
    assert diff.files_changed == 0
    assert read.content == INITIAL_FILES["README.md"]


# ── Strict params ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "commit",
    ["HEAD", "abc1234", "A" * 40, ":/fix", "-x", f"{'a' * 40}^", "", "a" * 41],
    ids=["head", "short", "uppercase", "message-search", "option", "suffix", "empty", "41-hex"],
)
async def test_ops_reject_commit_ids_that_are_not_full_hex(
    backend: BackendUnderTest, commit: str
) -> None:
    ops, ref, session = backend.ops, backend.ref, backend.session
    with pytest.raises(ValueError):
        await ops.reset(ref, session, op_key="k-1", commit=commit)
    with pytest.raises(ValueError):
        await ops.diff_stat(ref, session, from_commit=commit)
    with pytest.raises(ValueError):
        await ops.diff_stat(ref, session, from_commit=await _head(backend), to_commit=commit)
    with pytest.raises(ValueError):
        await ops.read(ref, session, path="README.md", at_commit=commit)
    with pytest.raises(ValueError):
        await _commit(backend, "k-2", expected_head=commit)


@pytest.mark.parametrize(
    "source_ref",
    [
        "coral/r-test/agent-1",
        "refs/heads/main",
        "refs/tags/coral/r-test/agent-1",
        "refs/heads/coral/../main",
        "refs/heads/coral/agent.lock",
        "refs/heads/coral/agent@{1}",
        "refs/heads/coral/.hidden",
        "refs/heads/coral-feature",
        "refs/coralx/r-test/agent-1",
        "refs/heads/coral/agent..1",
        "refs/heads/coral/-agent",
        "refs/heads/coral/agent-1/",
        "refs/heads/coral/agent-1\n",
        "refs/heads/coral/agent-é",
        "refs/heads/coral/agent.",
        "refs/heads/coral/agent.LOCK",
        f"refs/heads/coral/{'a' * 100}/{'b' * 100}/{'c' * 60}",
    ],
    ids=[
        "short",
        "user-branch",
        "tag",
        "dotdot",
        "lock",
        "reflog",
        "dot-component",
        "user-branch-sharing-the-prefix",
        "namespace-sharing-the-prefix",
        "dotdot-inside-a-component",
        "dash-component",
        "trailing-slash",
        "trailing-newline",
        "non-ascii",
        "trailing-dot",
        "lock-any-case",
        "over-255-chars",
    ],
)
async def test_merge_rejects_refs_outside_the_coral_namespaces(
    backend: BackendUnderTest, source_ref: str
) -> None:
    head = await _head(backend)

    with pytest.raises(ValueError):
        await backend.ops.merge(
            backend.ref, backend.session, op_key="k-1", source_ref=source_ref, message="m"
        )

    assert await _head(backend) == head


@pytest.mark.parametrize(
    "timeout_s",
    [float("nan"), float("inf"), 0, 0.5, -1, 1e9, True],
    ids=["nan", "inf", "zero", "sub-second", "negative", "huge", "bool"],
)
async def test_check_rejects_unbounded_timeouts(
    backend: BackendUnderTest, timeout_s: float
) -> None:
    argv = backend.setup.check_argv(0)

    with pytest.raises(ValueError):
        await backend.ops.check(
            backend.ref, backend.session, op_key="k-1", argv=argv, timeout_s=timeout_s
        )


@pytest.mark.parametrize(
    "op_key", ["", "a/b", "a..b", "a b", "line\nbreak", "-dash", "Upper", "x" * 129]
)
async def test_write_ops_reject_op_keys_that_cannot_name_a_ref(
    backend: BackendUnderTest, op_key: str
) -> None:
    base = await _head(backend)
    calls = _write_op_calls(backend, backend.ref, base, op_key=op_key)

    for op in KEYED_WRITE_OP_IDS:
        with pytest.raises(ValueError):
            await calls[op](backend.session)

    assert await _head(backend) == base


@pytest.mark.parametrize(
    "trailers",
    [
        {"Coral-Op": "forged"},
        {"coral-op-params": "forged"},
        {"Coral-Run": "r"},
        {"Run": "a\nCoral-Op: forged"},
        {"Run": "a\0b"},
        {"Run": "a\rb"},
        {"Bad Key": "v"},
        {"K" * 65: "v"},
        {"Run": 5},
        {5: "v"},
    ],
    ids=[
        "op",
        "params-any-case",
        "coral-prefix",
        "newline",
        "nul",
        "carriage-return",
        "space-in-key",
        "long-key",
        "non-string-value",
        "non-string-key",
    ],
)
async def test_commit_rejects_trailers_that_forge_or_break_records(
    backend: BackendUnderTest, trailers: Mapping[str, str]
) -> None:
    backend.setup.write_file("README.md", b"edited\n")
    head = await _head(backend)

    with pytest.raises(ValueError):
        await _commit(backend, "k-1", trailers=trailers)

    assert await _head(backend) == head


@pytest.mark.parametrize("message", ["step\0one", "", " \n"], ids=["nul", "empty", "blank"])
async def test_commit_and_merge_reject_nul_or_blank_messages(
    backend: BackendUnderTest, message: str
) -> None:
    backend.setup.add_ref(AGENT_REF, {"agent.txt": b"agent\n"})
    backend.setup.write_file("README.md", b"edited\n")
    head = await _head(backend)

    with pytest.raises(ValueError):
        await _commit(backend, "k-1", message)
    with pytest.raises(ValueError):
        await backend.ops.merge(
            backend.ref, backend.session, op_key="k-2", source_ref=AGENT_REF, message=message
        )

    assert await _head(backend) == head


# ── Idempotency by op key ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    ["step 1", "step 1\n", "subject\n\nSee: issue 12"],
    ids=["plain", "trailing-newline", "trailer-like-paragraph"],
)
async def test_commit_repeated_with_its_op_key_returns_the_first_commit(
    backend: BackendUnderTest, message: str
) -> None:
    base = await _head(backend)
    backend.setup.write_file("README.md", b"first\n")
    first = await _commit(backend, "k-1", message, expected_head=base, trailers={"Run": "r"})
    backend.setup.write_file("README.md", b"second\n")

    repeat = await _commit(backend, "k-1", message, expected_head=base, trailers={"Run": "r"})

    assert repeat == first
    assert first.empty is False
    assert await _head(backend) == first.commit
    assert await _read(backend, "README.md", first.commit) == b"first\n"
    assert await _read(backend, "README.md") == b"second\n"
    assert (await _fingerprint(backend)).dirty_count == 1


@pytest.mark.parametrize(
    ("message", "trailers"),
    [("other message", {"Run": "r"}), ("step 1", {"Run": "other"}), ("step 1", {})],
    ids=["message", "trailer-value", "trailers-dropped"],
)
async def test_commit_op_key_reused_with_other_params_conflicts(
    backend: BackendUnderTest, message: str, trailers: Mapping[str, str]
) -> None:
    base = await _head(backend)
    backend.setup.write_file("README.md", b"first\n")
    first = await _commit(backend, "k-1", "step 1", expected_head=base, trailers={"Run": "r"})
    backend.setup.write_file("README.md", b"second\n")

    await _assert_error(
        "workspace.op_key_conflict",
        _commit(backend, "k-1", message, expected_head=base, trailers=trailers),
    )

    assert await _head(backend) == first.commit
    assert await _read(backend, "README.md") == b"second\n"


async def test_commit_refuses_when_head_is_not_the_expected_head(
    backend: BackendUnderTest,
) -> None:
    base = await _head(backend)
    other = backend.setup.add_ref(AGENT_REF, {"agent.txt": b"agent\n"})
    backend.setup.write_file("README.md", b"first\n")
    first = await _commit(backend, "k-1", expected_head=base)
    backend.setup.write_file("README.md", b"second\n")

    await _assert_error("workspace.target_mismatch", _commit(backend, "k-2", expected_head=base))
    # HEAD carries k-1 but not on ``other``: an untrusted record, so params are not compared.
    await _assert_error(
        "workspace.target_mismatch", _commit(backend, "k-1", "changed", expected_head=other)
    )

    assert await _head(backend) == first.commit
    assert await _read(backend, "README.md") == b"second\n"


async def test_salvage_repeated_with_its_op_key_returns_the_first_salvage(
    backend: BackendUnderTest,
) -> None:
    ops, ref, session = backend.ops, backend.ref, backend.session
    backend.setup.write_file("README.md", b"lost work\n")
    first = await ops.salvage(ref, session, op_key="k-1")
    backend.setup.write_file("README.md", b"later work\n")

    repeat = await ops.salvage(ref, session, op_key="k-1")

    assert repeat == first
    assert first.ref == salvage_ref_name("k-1") == "refs/coral/salvage/k-1"
    assert first.commit is not None
    assert await _read(backend, "README.md", first.commit) == b"lost work\n"


async def test_salvage_refuses_a_ref_that_is_not_its_record(backend: BackendUnderTest) -> None:
    backend.setup.add_ref("refs/coral/salvage/k-1", {"planted.txt": b"x\n"})
    backend.setup.write_file("README.md", b"moved on\n")
    await _commit(backend, "k-2")
    backend.setup.write_file("README.md", b"unsaved\n")

    await _assert_error(
        "workspace.op_key_conflict",
        backend.ops.salvage(backend.ref, backend.session, op_key="k-1"),
    )

    assert await _read(backend, "README.md") == b"unsaved\n"


async def test_reset_and_merge_repeated_with_their_op_keys_change_nothing(
    backend: BackendUnderTest,
) -> None:
    ops, ref, session = backend.ops, backend.ref, backend.session
    base = await _head(backend)
    agent = backend.setup.add_ref(AGENT_REF, {"agent.txt": b"agent\n"})
    first_merge = await ops.merge(ref, session, op_key="k-m", source_ref=AGENT_REF, message="m")
    repeat_merge = await ops.merge(ref, session, op_key="k-m", source_ref=AGENT_REF, message="m")
    assert first_merge.status == "clean"
    assert repeat_merge.status == "already_applied"
    assert await _head(backend) == agent

    first_reset = await ops.reset(ref, session, op_key="k-r", commit=base)
    after_first = await _fingerprint(backend)
    repeat_reset = await ops.reset(ref, session, op_key="k-r", commit=base)

    assert first_reset == repeat_reset
    assert first_reset.head == base
    assert await _fingerprint(backend) == after_first


# ── commit ──────────────────────────────────────────────────────────────────


async def test_commit_records_tracked_and_untracked_changes(backend: BackendUnderTest) -> None:
    base = await _head(backend)
    backend.setup.write_file("README.md", b"edited\n")
    backend.setup.write_file("docs/new.md", b"new\n")
    backend.setup.delete_file("src/app.py")

    result = await _commit(backend, "k-1", "step 1", expected_head=base)

    assert result.empty is False
    assert result.commit != base
    assert await _head(backend) == result.commit
    assert await _read(backend, "README.md", result.commit) == b"edited\n"
    assert await _read(backend, "docs/new.md", result.commit) == b"new\n"
    await _assert_missing(backend, "src/app.py", result.commit)
    assert (await _fingerprint(backend)).dirty_count == 0


async def test_commit_with_nothing_to_record_returns_head_as_empty(
    backend: BackendUnderTest,
) -> None:
    head = await _head(backend)
    backend.setup.ignore("build/out.bin")
    backend.setup.write_file("build/out.bin", b"\x00artifact")
    backend.setup.write_file(".coral/runtime/state.json", b"{}")

    result = await _commit(backend, "k-1", "nothing", expected_head=head)

    assert (result.commit, result.empty) == (head, True)
    assert await _head(backend) == head


# ── salvage ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("noise", [False, True], ids=["clean", "only-ignored-and-runtime-files"])
async def test_salvage_of_a_clean_tree_records_nothing(
    backend: BackendUnderTest, noise: bool
) -> None:
    head = await _head(backend)
    if noise:
        backend.setup.ignore("build/out.bin")
        backend.setup.write_file("build/out.bin", b"ignored")
        backend.setup.write_file(".coral/runtime/state.json", b"{}")

    result = await backend.ops.salvage(backend.ref, backend.session, op_key="k-1")

    assert (result.ref, result.commit) == ("refs/coral/salvage/k-1", None)
    assert await _head(backend) == head


async def test_salvage_of_a_dirty_tree_keeps_head_and_working_tree(
    backend: BackendUnderTest,
) -> None:
    head = await _head(backend)
    backend.setup.write_file("README.md", b"unsaved\n")
    backend.setup.write_file("notes/todo.txt", b"untracked\n")
    backend.setup.ignore("build/out.bin")
    backend.setup.write_file("build/out.bin", b"ignored")
    before = await _fingerprint(backend)

    result = await backend.ops.salvage(backend.ref, backend.session, op_key="k-1")

    assert result.commit is not None
    assert result.commit != head
    assert await _head(backend) == head
    assert await _fingerprint(backend) == before
    assert await _read(backend, "README.md") == b"unsaved\n"
    assert await _read(backend, "README.md", result.commit) == b"unsaved\n"
    assert await _read(backend, "notes/todo.txt", result.commit) == b"untracked\n"
    await _assert_missing(backend, "build/out.bin", result.commit)


# ── reset ───────────────────────────────────────────────────────────────────


async def test_reset_restores_tracked_files_removes_untracked_and_keeps_ignored(
    backend: BackendUnderTest,
) -> None:
    ops, ref, session = backend.ops, backend.ref, backend.session
    base = await _head(backend)
    backend.setup.write_file("README.md", b"committed\n")
    later = await _commit(backend, "k-1", "later", expected_head=base)
    backend.setup.write_file("README.md", b"dirty\n")
    backend.setup.delete_file("src/app.py")
    backend.setup.write_file("notes/todo.txt", b"untracked\n")
    backend.setup.write_file(".coral/other/cache.txt", b"untracked\n")
    backend.setup.ignore("build/out.bin")
    backend.setup.write_file("build/out.bin", b"ignored")
    backend.setup.write_file(".coral/runtime/state.json", b"{}")

    result = await ops.reset(ref, session, op_key="k-2", commit=base)

    assert result.head == base != later.commit
    assert await _head(backend) == base
    assert await _read(backend, "README.md") == INITIAL_FILES["README.md"]
    assert await _read(backend, "src/app.py") == INITIAL_FILES["src/app.py"]
    await _assert_missing(backend, "notes/todo.txt")
    await _assert_missing(backend, ".coral/other/cache.txt")
    assert await _read(backend, "build/out.bin") == b"ignored"
    assert await _read(backend, ".coral/runtime/state.json") == b"{}"
    assert (await _fingerprint(backend)).dirty_count == 0


async def test_reset_to_an_unknown_commit_fails(backend: BackendUnderTest) -> None:
    await _assert_error(
        "workspace.git_failed",
        backend.ops.reset(backend.ref, backend.session, op_key="k-1", commit=UNKNOWN_COMMIT),
    )


# ── merge ───────────────────────────────────────────────────────────────────


async def test_merge_fast_forwards_onto_a_ref_ahead_of_head(backend: BackendUnderTest) -> None:
    agent = backend.setup.add_ref(AGENT_REF, {"README.md": b"agent edit\n"})
    # Ignored and runtime files do not make the tree dirty, and they survive.
    backend.setup.ignore("build/out.bin")
    backend.setup.write_file("build/out.bin", b"ignored")
    backend.setup.write_file(".coral/runtime/state.json", b"{}")
    before = await _fingerprint(backend)

    result = await backend.ops.merge(
        backend.ref, backend.session, op_key="k-1", source_ref=AGENT_REF, message="merge"
    )

    assert (result.status, result.merge_commit, result.conflicts) == ("clean", agent, ())
    assert await _head(backend) == agent
    assert await _read(backend, "README.md") == b"agent edit\n"
    assert await _read(backend, "build/out.bin") == b"ignored"
    assert await _read(backend, ".coral/runtime/state.json") == b"{}"
    # L1 covers HEAD, so it changes although the tree stays clean.
    after = await _fingerprint(backend)
    assert (before.dirty_count, after.dirty_count) == (0, 0)
    assert after.digest != before.digest


async def test_merge_of_a_ref_already_in_head_is_already_applied(
    backend: BackendUnderTest,
) -> None:
    ops, ref, session = backend.ops, backend.ref, backend.session
    agent = backend.setup.add_ref(AGENT_REF, {"agent.txt": b"agent\n"})
    await ops.merge(ref, session, op_key="k-1", source_ref=AGENT_REF, message="merge")
    backend.setup.write_file("README.md", b"after merge\n")
    after = await _commit(backend, "k-2", "after merge", expected_head=agent)
    # Already applied wins over the dirty-tree refusal, and nothing changes.
    backend.setup.write_file("README.md", b"uncommitted\n")

    result = await ops.merge(ref, session, op_key="k-3", source_ref=AGENT_REF, message="again")

    assert (result.status, result.merge_commit, result.conflicts) == ("already_applied", None, ())
    assert await _head(backend) == after.commit != agent
    assert await _read(backend, "README.md") == b"uncommitted\n"


async def test_merge_of_an_unknown_ref_fails(backend: BackendUnderTest) -> None:
    head = await _head(backend)

    await _assert_error(
        "workspace.git_failed",
        backend.ops.merge(
            backend.ref, backend.session, op_key="k-1", source_ref=AGENT_REF, message="m"
        ),
    )

    assert await _head(backend) == head


async def test_merge_conflict_reports_paths_and_leaves_head_and_tree(
    backend: BackendUnderTest,
) -> None:
    backend.setup.add_conflicting_ref(AGENT_REF, "README.md")
    head = await _head(backend)
    before = await _fingerprint(backend)

    result = await backend.ops.merge(
        backend.ref, backend.session, op_key="k-1", source_ref=AGENT_REF, message="merge"
    )

    assert (result.status, result.merge_commit, result.conflicts) == (
        "conflict",
        None,
        ("README.md",),
    )
    assert await _head(backend) == head
    assert await _fingerprint(backend) == before
    assert (await backend.ops.head(backend.ref, backend.session)).merge_in_progress is False


async def test_merge_refuses_a_dirty_working_tree(backend: BackendUnderTest) -> None:
    head = await _head(backend)
    backend.setup.add_ref(AGENT_REF, {"agent.txt": b"agent\n"})
    backend.setup.write_file("README.md", b"uncommitted\n")

    await _assert_error(
        "workspace.git_failed",
        backend.ops.merge(
            backend.ref, backend.session, op_key="k-1", source_ref=AGENT_REF, message="m"
        ),
    )

    assert await _head(backend) == head
    assert await _read(backend, "README.md") == b"uncommitted\n"


# ── fingerprint ─────────────────────────────────────────────────────────────


async def test_l1_is_stable_without_edits_and_changes_on_every_edit(
    backend: BackendUnderTest,
) -> None:
    edits: list[Callable[[], None]] = [
        lambda: backend.setup.write_file("README.md", b"edit 1\n"),
        # Same size as the previous edit: status alone cannot see it.
        lambda: backend.setup.write_file("README.md", b"edit 2\n"),
        lambda: backend.setup.write_file("new_dir/file.txt", b"untracked\n"),
        lambda: backend.setup.delete_file("src/app.py"),
    ]
    seen = [await _fingerprint(backend)]
    assert await _fingerprint(backend) == seen[0]

    for edit in edits:
        edit()
        current = await _fingerprint(backend)
        assert current.digest not in {earlier.digest for earlier in seen}
        assert await _fingerprint(backend) == current
        seen.append(current)

    assert seen[-1].level == "L1"
    assert seen[-1].head == await _head(backend)
    assert seen[-1].dirty_count == 3


@pytest.mark.parametrize("level", ["L1", "L2"])
async def test_fingerprints_skip_ignored_files_and_coral_runtime(
    backend: BackendUnderTest, level: FingerprintLevel
) -> None:
    before = await _fingerprint(backend, level)
    backend.setup.ignore("build/out.bin")
    backend.setup.write_file("build/out.bin", b"ignored")
    backend.setup.write_file(".coral/runtime/state.json", b"{}")

    assert await _fingerprint(backend, level) == before


async def test_l2_is_equal_for_equal_tree_content(backend: BackendUnderTest) -> None:
    clean = await _fingerprint(backend, "L2")
    backend.setup.write_file("README.md", b"edited\n")
    edited = await _fingerprint(backend, "L2")
    backend.setup.write_file("README.md", INITIAL_FILES["README.md"])
    reverted = await _fingerprint(backend, "L2")
    assert edited.digest != clean.digest
    assert reverted.digest == clean.digest

    backend.setup.write_file("README.md", b"edited\n")
    l1_dirty = await _fingerprint(backend, "L1")
    await _commit(backend, "k-1", "edit")

    committed = await _fingerprint(backend, "L2")
    assert committed.digest == edited.digest
    assert (committed.level, committed.dirty_count) == ("L2", 0)
    assert (await _fingerprint(backend, "L1")).digest != l1_dirty.digest


# ── read, diff_stat, head, check ────────────────────────────────────────────


async def test_read_returns_exact_bytes_at_a_commit_and_in_the_working_tree(
    backend: BackendUnderTest,
) -> None:
    ops, ref, session = backend.ops, backend.ref, backend.session
    backend.setup.write_file("data.bin", b"\x00\xff\r\n")
    committed = await _commit(backend, "k-1", "data")
    backend.setup.write_file("data.bin", b"changed")

    at_commit = await ops.read(ref, session, path="data.bin", at_commit=committed.commit)
    working = await ops.read(ref, session, path="data.bin")

    assert (at_commit.path, at_commit.content) == ("data.bin", b"\x00\xff\r\n")
    assert at_commit.sha256 == hashlib.sha256(b"\x00\xff\r\n").hexdigest()
    assert working.content == b"changed"
    await _assert_missing(backend, "absent.txt")
    await _assert_missing(backend, "absent.txt", committed.commit)


@pytest.mark.parametrize(
    "path",
    ["../outside", "/etc/passwd", "src/../../outside", "", "./README.md", "src//app.py", "src/"],
)
async def test_read_refuses_paths_outside_the_root(backend: BackendUnderTest, path: str) -> None:
    with pytest.raises(ValueError):
        await _read(backend, path)


async def test_read_refuses_a_file_over_the_size_cap(backend: BackendUnderTest) -> None:
    backend.setup.write_file("big.bin", b"x" * (MAX_READ_BYTES + 1))
    committed = await _commit(backend, "k-1", "big")

    await _assert_error("workspace.git_failed", _read(backend, "big.bin"))
    await _assert_error("workspace.git_failed", _read(backend, "big.bin", committed.commit))


async def test_diff_stat_between_commits_defaults_to_head(backend: BackendUnderTest) -> None:
    ops, ref, session = backend.ops, backend.ref, backend.session
    base = await _head(backend)
    backend.setup.write_file("README.md", b"hello\nmore\n")
    backend.setup.write_file("docs/new.md", b"one\ntwo\n")
    assert (await ops.diff_stat(ref, session, from_commit=base)).files_changed == 0

    committed = await _commit(backend, "k-1", "docs", expected_head=base)
    to_head = await ops.diff_stat(ref, session, from_commit=base)
    between = await ops.diff_stat(ref, session, from_commit=base, to_commit=committed.commit)
    backend.setup.delete_file("src/app.py")
    # A binary file counts as changed with 0 lines.
    backend.setup.write_file("image.bin", b"\x00\x01\x02\n")
    deleted = await _commit(backend, "k-2", "delete", expected_head=committed.commit)
    removed = await ops.diff_stat(ref, session, from_commit=committed.commit)

    assert to_head == between
    assert (between.files_changed, between.insertions, between.deletions) == (2, 3, 0)
    assert between.paths == ("README.md", "docs/new.md")
    assert (await _head(backend)) == deleted.commit
    assert (removed.files_changed, removed.insertions, removed.deletions) == (2, 0, 1)
    assert removed.paths == ("image.bin", "src/app.py")


async def test_head_reports_the_branch_and_no_merge_in_progress(
    backend: BackendUnderTest,
) -> None:
    result = await backend.ops.head(backend.ref, backend.session)
    # READ ops do not verify ref.branch, so head reports the actual branch.
    other = replace(backend.ref, branch="coral/r-test/other")
    reported = await backend.ops.head(other, backend.session)

    assert result.branch == reported.branch == backend.ref.branch
    assert result.merge_in_progress is False
    assert result.head == (await _fingerprint(backend)).head


async def test_check_reports_exit_codes_and_timeouts_without_raising(
    backend: BackendUnderTest,
) -> None:
    ops, ref, session = backend.ops, backend.ref, backend.session
    passing, failing = backend.setup.check_argv(0), backend.setup.check_argv(3)
    overrun = backend.setup.check_argv(None)

    ok = await ops.check(ref, session, op_key="k-1", argv=passing, timeout_s=30)
    failed = await ops.check(ref, session, op_key="k-2", argv=failing, timeout_s=30)
    rerun = await ops.check(ref, session, op_key="k-2", argv=failing, timeout_s=30)
    slow = await ops.check(ref, session, op_key="k-3", argv=overrun, timeout_s=1)

    assert (ok.exit_code, ok.timed_out) == (0, False)
    assert (failed.exit_code, failed.timed_out) == (3, False)
    assert (rerun.exit_code, rerun.timed_out) == (3, False)
    assert (slow.exit_code, slow.timed_out) == (None, True)
