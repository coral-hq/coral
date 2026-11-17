# CORAL(S40): the host workspace-op dispatcher and its connect branch.
# CORAL(S40b): the workspace-op handler registry from entry points.
"""Host side of the workspace-op channel: the guarded dispatcher, the handler registry
and the ``host.workspace_op`` branch of the host's frame dispatch."""

from __future__ import annotations

import asyncio
import dataclasses
import importlib.metadata
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from omnigent.host import workspace_ops
from omnigent.host.connect import HostProcess
from omnigent.host.frames import decode_host_frame, encode_host_frame
from omnigent.host.identity import HostIdentity
from omnigent.host.workspace_ops import (
    ENTRY_POINT_GROUP,
    HANDLER_FAILED,
    INVALID_PAYLOAD,
    INVALID_REQUEST,
    MAX_WORKSPACE_OP_RESULT_BYTES,
    RESULT_TOO_LARGE,
    UNKNOWN_OP,
    HostWorkspaceOpFrame,
    HostWorkspaceOpResultFrame,
    WorkspaceOpHandlerError,
    WorkspaceOpRequest,
    dispatch_workspace_op,
    load_workspace_op_handlers,
    workspace_op_request_problem,
)
from tests._helpers.live_server import isolated_process_env
from tests.host.test_orphan_reaper import _CollectingTunnel, _exited_process


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> HostProcess:
    monkeypatch.setenv("OMNIGENT_RUNNER_ZYGOTE", "0")
    return HostProcess(
        identity=HostIdentity(host_id="host_workspace_ops_test", name="workspace-ops-test"),
        server_url="http://localhost:8000",
        interactive_shells=["bash"],
    )


class _RecordingGuard:
    """``run_guarded`` stand-in that runs the operation in a thread and counts calls."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, operation: Callable[[], object]) -> object:
        self.calls += 1
        return await asyncio.to_thread(operation)


# Absolute on every platform (a drive-qualified path on Windows).
_ROOT = os.path.abspath("/repo-worktrees/run")


def _op(
    op: str = "head",
    *,
    root: str = _ROOT,
    request_id: str = "req",
    params: dict[str, Any] | None = None,
    timeout_s: float = 30.0,
    op_key: str | None = None,
) -> HostWorkspaceOpFrame:
    return HostWorkspaceOpFrame(
        request_id=request_id,
        op=op,
        root=root,
        params=params or {},
        timeout_s=timeout_s,
        op_key=op_key,
    )


def _never_called(request: WorkspaceOpRequest) -> Mapping[str, Any]:
    raise AssertionError(f"handler ran for a refused op: {request.op}")


# Handler contributions loaded through real entry points (``value`` names this module).
def _head(request: WorkspaceOpRequest) -> Mapping[str, Any]:
    return {"head": "a" * 40}


def _other_head(request: WorkspaceOpRequest) -> Mapping[str, Any]:
    return {"head": "b" * 40}


def _first_ops() -> Mapping[str, Callable[[WorkspaceOpRequest], Mapping[str, Any]]]:
    return {"head": _head}


def _second_ops() -> Mapping[str, Callable[[WorkspaceOpRequest], Mapping[str, Any]]]:
    return {"head": _other_head, "diff_stat": _other_head}


def _raising_ops() -> Mapping[str, Any]:
    raise RuntimeError("plugin failed to initialise")


def _list_ops() -> object:
    return [("head", _head)]


def _badly_named_ops() -> Mapping[str, Any]:
    return {"diff_stat": _head, "Head!": _head}


def _non_callable_ops() -> Mapping[str, Any]:
    return {"head": "not a handler"}


def _no_ops() -> Mapping[str, Any]:
    return {}


def _entry(name: str, attribute: str) -> importlib.metadata.EntryPoint:
    return importlib.metadata.EntryPoint(
        name=name, value=f"{__name__}:{attribute}", group=ENTRY_POINT_GROUP
    )


@pytest.fixture
def fresh_default_handlers() -> Iterator[None]:
    """Forget the process-wide handler cache before and after the test."""
    workspace_ops.default_workspace_op_handlers.cache_clear()
    yield
    workspace_ops.default_workspace_op_handlers.cache_clear()


# ── connect.py branch ───────────────────────────────────


@pytest.mark.posix_only
async def test_workspace_op_keeps_git_exit_status_through_a_reaper_sweep(
    host: HostProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sweep while the handler owns an exited git child leaves its status to the handler."""
    started = threading.Event()
    resume = threading.Event()
    tunnel = _CollectingTunnel()
    frame = _op("commit", request_id="req-exit", op_key="k" * 32)

    with _exited_process(42) as proc:

        def git_like_handler(request: WorkspaceOpRequest) -> Mapping[str, Any]:
            assert request.op == "commit"
            started.set()
            assert resume.wait(timeout=5.0), "workspace op worker was not released"
            return {"exit_code": proc.wait(timeout=5.0)}

        monkeypatch.setattr(
            workspace_ops, "default_workspace_op_handlers", lambda: {"commit": git_like_handler}
        )
        dispatch = asyncio.create_task(
            host._dispatch_host_frame(tunnel, frame)  # type: ignore[arg-type]
        )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5.0), timeout=6.0)
            assert host._owned_subprocess_ops == 1

            # A sweep landing while the handler still owns the exited child.
            assert host._reap_orphans_once([proc.pid]) == 0
            assert proc.returncode is None

            resume.set()
            await asyncio.wait_for(dispatch, timeout=5.0)

            assert [decode_host_frame(sent) for sent in tunnel.sent] == [
                HostWorkspaceOpResultFrame(
                    request_id="req-exit", status="ok", payload={"exit_code": 42}
                )
            ]
            assert host._owned_subprocess_ops == 0
        finally:
            resume.set()
            await asyncio.wait_for(asyncio.gather(dispatch, return_exceptions=True), timeout=5.0)


async def test_host_answers_every_workspace_op_frame_through_the_patched_registry(
    host: HostProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raw frames reach the patched handlers under the guard; failures still answer."""
    guard_counts: list[int] = []

    def head(request: WorkspaceOpRequest) -> Mapping[str, Any]:
        guard_counts.append(host._owned_subprocess_ops)
        return {"head": "c" * 40}

    def broken(request: WorkspaceOpRequest) -> Mapping[str, Any]:
        raise RuntimeError("token=do-not-leak")

    monkeypatch.setattr(
        workspace_ops, "default_workspace_op_handlers", lambda: {"head": head, "broken": broken}
    )
    tunnel = _CollectingTunnel()
    for op in ("head", "broken", "merge"):
        raw = encode_host_frame(_op(op, request_id=f"req-{op}"))
        await asyncio.wait_for(host._handle_raw_message(tunnel, raw), timeout=5.0)  # type: ignore[arg-type]

    replies = [decode_host_frame(sent) for sent in tunnel.sent]
    assert replies == [
        HostWorkspaceOpResultFrame(request_id="req-head", status="ok", payload={"head": "c" * 40}),
        HostWorkspaceOpResultFrame(
            request_id="req-broken",
            status="failed",
            error_code=HANDLER_FAILED,
            error="workspace op handler raised RuntimeError",
        ),
        HostWorkspaceOpResultFrame(
            request_id="req-merge",
            status="failed",
            error_code=UNKNOWN_OP,
            error="this host has no workspace op 'merge'",
            permanent=True,
        ),
    ]
    # The handler ran inside the reaper guard, which is released afterwards.
    assert len(guard_counts) == 1
    assert guard_counts[0] >= 1
    assert host._owned_subprocess_ops == 0


async def test_host_runs_at_most_two_workspace_ops_at_once(
    host: HostProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A third op waits for a slot without a worker thread or a paused reaper."""
    assert workspace_ops.MAX_CONCURRENT_WORKSPACE_OPS == 2
    release = threading.Event()
    two_running = threading.Event()
    three_running = threading.Event()
    running: list[str | None] = []
    lock = threading.Lock()

    def slow(request: WorkspaceOpRequest) -> Mapping[str, Any]:
        with lock:
            running.append(request.op_key)
            if len(running) == 2:
                two_running.set()
            if len(running) == 3:
                three_running.set()
        assert release.wait(timeout=5.0), "workspace op worker was not released"
        return {"op_key": request.op_key}

    monkeypatch.setattr(workspace_ops, "default_workspace_op_handlers", lambda: {"head": slow})
    tunnel = _CollectingTunnel()
    frames = [_op(request_id=f"req-{index}", op_key=f"k-{index}") for index in range(3)]
    dispatches = [
        asyncio.create_task(host._dispatch_host_frame(tunnel, frame))  # type: ignore[arg-type]
        for frame in frames
    ]
    try:
        assert await asyncio.wait_for(asyncio.to_thread(two_running.wait, 5.0), timeout=6.0)
        assert host._owned_subprocess_ops == 2
        await asyncio.sleep(0.1)
        assert not three_running.is_set()

        release.set()
        await asyncio.wait_for(asyncio.gather(*dispatches), timeout=5.0)
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(*dispatches, return_exceptions=True), timeout=5.0)

    assert three_running.is_set()
    replies = [decode_host_frame(sent) for sent in tunnel.sent]
    assert sorted(reply.payload["op_key"] for reply in replies) == ["k-0", "k-1", "k-2"]  # type: ignore[union-attr]
    assert host._owned_subprocess_ops == 0


# ── dispatcher ──────────────────────────────────────────


async def test_dispatch_hands_the_handler_its_request_and_deadline() -> None:
    received: list[WorkspaceOpRequest] = []

    def commit(request: WorkspaceOpRequest) -> Mapping[str, Any]:
        received.append(request)
        return {"commit": "d" * 40, "empty": False}

    guard = _RecordingGuard()
    frame = _op("commit", params={"branch": "coral/r/base"}, timeout_s=30.0, op_key="key")
    before = time.monotonic()
    result = await dispatch_workspace_op(frame, run_guarded=guard, handlers={"commit": commit})
    after = time.monotonic()

    assert result == HostWorkspaceOpResultFrame(
        request_id="req", status="ok", payload={"commit": "d" * 40, "empty": False}
    )
    assert guard.calls == 1
    [request] = received
    assert (request.op, request.root, dict(request.params)) == (
        "commit",
        _ROOT,
        {"branch": "coral/r/base"},
    )
    assert (request.timeout_s, request.op_key) == (30.0, "key")
    assert before + 30.0 <= request.deadline <= after + 30.0


@pytest.mark.parametrize(
    ("frame", "code"),
    [
        pytest.param(_op("merge"), UNKNOWN_OP, id="unknown-op"),
        pytest.param(_op(root="repo-worktrees/run"), INVALID_REQUEST, id="relative-root"),
        pytest.param(_op(root=""), INVALID_REQUEST, id="empty-root"),
        pytest.param(_op(root="/repo/../etc"), INVALID_REQUEST, id="dot-dot-root"),
        pytest.param(_op(root="/repo/./run"), INVALID_REQUEST, id="dot-root"),
        pytest.param(_op(root="/repo//run"), INVALID_REQUEST, id="empty-segment-root"),
        pytest.param(_op(root="/repo/run/"), INVALID_REQUEST, id="trailing-slash-root"),
        pytest.param(_op(root="//server/share"), INVALID_REQUEST, id="double-slash-root"),
        pytest.param(_op(root="/repo/r\x00un"), INVALID_REQUEST, id="nul-root"),
        pytest.param(_op(op_key="../../evil"), INVALID_REQUEST, id="op-key-path"),
        pytest.param(_op(op_key="Key-1"), INVALID_REQUEST, id="op-key-uppercase"),
        pytest.param(_op(op_key="k" * 129), INVALID_REQUEST, id="op-key-too-long"),
    ],
)
async def test_dispatch_refuses_permanently_before_running_a_handler(
    frame: HostWorkspaceOpFrame, code: str
) -> None:
    guard = _RecordingGuard()
    result = await dispatch_workspace_op(
        frame, run_guarded=guard, handlers={"head": _never_called}
    )
    assert (result.status, result.error_code, result.permanent) == ("failed", code, True)
    assert result.payload is None
    assert guard.calls == 0


async def test_handler_error_round_trips_its_code_exit_code_and_permanence() -> None:
    def refuse(request: WorkspaceOpRequest) -> Mapping[str, Any]:
        raise WorkspaceOpHandlerError(
            "workspace.backend_unavailable",
            "repository declares filter=lfs in .gitattributes",
            exit_code=128,
            permanent=True,
        )

    result = await dispatch_workspace_op(
        _op(), run_guarded=_RecordingGuard(), handlers={"head": refuse}
    )
    expected = HostWorkspaceOpResultFrame(
        request_id="req",
        status="failed",
        error_code="workspace.backend_unavailable",
        error="repository declares filter=lfs in .gitattributes",
        exit_code=128,
        permanent=True,
    )
    assert result == expected
    assert decode_host_frame(encode_host_frame(result)) == expected


async def test_handler_error_message_keeps_its_last_2000_characters() -> None:
    message = "git commit-tree failed: " + "x" * 3000 + " fatal: the real cause"

    def fail(request: WorkspaceOpRequest) -> Mapping[str, Any]:
        raise WorkspaceOpHandlerError("workspace.git_failed", message, exit_code=128)

    result = await dispatch_workspace_op(
        _op(), run_guarded=_RecordingGuard(), handlers={"head": fail}
    )
    assert result.error is not None
    assert len(result.error) == 2000
    assert result.error.endswith(" fatal: the real cause")
    assert (result.error_code, result.exit_code, result.permanent) == (
        "workspace.git_failed",
        128,
        False,
    )


async def test_unexpected_handler_exception_reports_only_its_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def crash(request: WorkspaceOpRequest) -> Mapping[str, Any]:
        raise KeyError("/Users/a/secret-path")

    with caplog.at_level(logging.ERROR, logger=workspace_ops.__name__):
        result = await dispatch_workspace_op(
            _op(), run_guarded=_RecordingGuard(), handlers={"head": crash}
        )

    assert result == HostWorkspaceOpResultFrame(
        request_id="req",
        status="failed",
        error_code=HANDLER_FAILED,
        error="workspace op handler raised KeyError",
    )
    # The traceback stays in the host's log; only the type name crosses the tunnel.
    [record] = [r for r in caplog.records if r.exc_info is not None]
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], KeyError)


@pytest.mark.parametrize(
    ("fields", "error_type"),
    [
        pytest.param({"code": 7}, "TypeError", id="code-not-str"),
        pytest.param({"code": "Workspace Failed"}, "ValueError", id="code-malformed"),
        pytest.param({"message": b"fatal: bad object"}, "TypeError", id="message-bytes"),
        pytest.param({"message": None}, "TypeError", id="message-none"),
        pytest.param({"exit_code": True}, "TypeError", id="exit-code-bool"),
        pytest.param({"exit_code": 1.5}, "TypeError", id="exit-code-float"),
        pytest.param({"exit_code": "128"}, "TypeError", id="exit-code-str"),
        pytest.param({"permanent": 1}, "TypeError", id="permanent-int"),
        pytest.param({"permanent": None}, "TypeError", id="permanent-none"),
    ],
)
async def test_ill_typed_handler_error_is_answered_as_handler_failed(
    fields: dict[str, object], error_type: str
) -> None:
    """A handler that builds its error badly still gets an answer the server can decode."""
    arguments: dict[str, Any] = {"code": "workspace.git_failed", "message": "git failed", **fields}

    def fail(request: WorkspaceOpRequest) -> Mapping[str, Any]:
        raise WorkspaceOpHandlerError(
            arguments["code"],
            arguments["message"],
            exit_code=arguments.get("exit_code"),
            permanent=arguments.get("permanent", False),
        )

    result = await dispatch_workspace_op(
        _op(), run_guarded=_RecordingGuard(), handlers={"head": fail}
    )
    expected = HostWorkspaceOpResultFrame(
        request_id="req",
        status="failed",
        error_code=HANDLER_FAILED,
        error=f"workspace op handler raised {error_type}",
    )
    assert result == expected
    assert decode_host_frame(encode_host_frame(result)) == expected


async def test_dispatch_answers_even_when_it_fails_outside_the_handler() -> None:
    frame = dataclasses.replace(_op(), params=None)  # type: ignore[arg-type]
    guard = _RecordingGuard()
    result = await dispatch_workspace_op(frame, run_guarded=guard, handlers={"head": _head})
    assert result == HostWorkspaceOpResultFrame(
        request_id="req",
        status="failed",
        error_code=HANDLER_FAILED,
        error="workspace op dispatch raised TypeError",
    )
    assert guard.calls == 0


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([("head", "a" * 40)], id="not-a-mapping"),
        pytest.param({"head": object()}, id="not-json"),
        pytest.param({"ratio": float("nan")}, id="nan"),
    ],
)
async def test_payload_that_is_not_a_json_mapping_is_refused(payload: object) -> None:
    result = await dispatch_workspace_op(
        _op(), run_guarded=_RecordingGuard(), handlers={"head": lambda request: payload}
    )
    assert (result.status, result.error_code, result.payload) == ("failed", INVALID_PAYLOAD, None)
    # The handler returns the same value on every retry.
    assert result.permanent is True
    # The refusal itself always crosses the tunnel.
    assert decode_host_frame(encode_host_frame(result)) == result


async def test_result_over_the_size_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    assert MAX_WORKSPACE_OP_RESULT_BYTES == 8 * 1024 * 1024
    at_limit = {"content": "a" * 64}
    monkeypatch.setattr(workspace_ops, "MAX_WORKSPACE_OP_RESULT_BYTES", len(json.dumps(at_limit)))

    fits = await dispatch_workspace_op(
        _op(), run_guarded=_RecordingGuard(), handlers={"head": lambda request: at_limit}
    )
    too_large = await dispatch_workspace_op(
        _op(),
        run_guarded=_RecordingGuard(),
        handlers={"head": lambda request: {"content": "a" * 65}},
    )

    assert (fits.status, fits.payload) == ("ok", at_limit)
    assert (too_large.status, too_large.error_code, too_large.permanent) == (
        "failed",
        RESULT_TOO_LARGE,
        True,
    )
    assert too_large.payload is None


class _SerialisationProbe(dict[str, Any]):
    """Records the thread each time JSON encoding reads its items."""

    threads: list[int]

    def items(self) -> Any:
        self.threads.append(threading.get_ident())
        return super().items()


async def test_ok_payload_is_serialised_once_in_the_worker_thread() -> None:
    probe = _SerialisationProbe(files=2)
    probe.threads = []
    result = await dispatch_workspace_op(
        _op(), run_guarded=_RecordingGuard(), handlers={"head": lambda request: {"stat": probe}}
    )

    # Encoding the frame reuses the worker's text rather than serialising again.
    decoded = decode_host_frame(encode_host_frame(result))
    assert decoded == HostWorkspaceOpResultFrame(
        request_id="req", status="ok", payload={"stat": {"files": 2}}
    )
    assert len(probe.threads) == 1
    assert probe.threads[0] != threading.get_ident()
    # A copy with another payload never reuses the original's text.
    changed = dataclasses.replace(result, payload={"stat": {"files": 3}})
    assert decode_host_frame(encode_host_frame(changed)) == changed


@pytest.mark.parametrize(
    ("root", "accepted"),
    [
        pytest.param("/Users/a/repo-worktrees/run", True, id="posix"),
        pytest.param("/", True, id="posix-root"),
        pytest.param("C:\\Users\\a\\run", True, id="windows-drive"),
        pytest.param("C:/Users/a/run", False, id="windows-forward-slashes"),
        pytest.param("C:\\Users\\..\\run", False, id="windows-dot-dot"),
        pytest.param("\\\\server\\share\\run", False, id="windows-unc"),
        pytest.param("C:run", False, id="windows-drive-relative"),
    ],
)
def test_root_check_judges_each_path_flavour_on_its_own_terms(root: str, accepted: bool) -> None:
    """The server checks a host's root without knowing the host's platform."""
    assert (workspace_op_request_problem(_op(root=root)) is None) is accepted


# ── handler registry (entry points) ─────────────────────


def test_broken_entry_points_are_skipped_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    broken = [
        importlib.metadata.EntryPoint(
            name="a-missing-module",
            value="tests.host.no_such_module:ops",
            group=ENTRY_POINT_GROUP,
        ),
        _entry("b-raises", "_raising_ops"),
        _entry("c-not-a-mapping", "_list_ops"),
        _entry("d-bad-op-name", "_badly_named_ops"),
        _entry("e-non-callable-handler", "_non_callable_ops"),
    ]
    with caplog.at_level(logging.WARNING, logger=workspace_ops.__name__):
        handlers = load_workspace_op_handlers([*broken, _entry("z-good", "_first_ops")])

    # A broken contribution adds none of its ops, not even its well-formed ones.
    assert dict(handlers) == {"head": _head}
    warned = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warned) == len(broken)
    for record, entry in zip(warned, broken, strict=True):
        assert entry.name in record.getMessage()


@dataclass(frozen=True)
class _Distribution:
    name: str


@dataclass(frozen=True)
class _InstalledEntry:
    """An entry point as discovered from an installed distribution."""

    name: str
    dist: _Distribution
    contribution: Callable[[], object]

    def load(self) -> Callable[[], object]:
        return self.contribution


async def test_op_offered_by_two_packages_is_served_by_neither(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No package can take over another's op; each served op is logged with its package."""
    installed = [
        _InstalledEntry("acme", _Distribution("acme-tools"), _first_ops),
        _InstalledEntry("coral", _Distribution("coral"), _second_ops),
    ]
    with caplog.at_level(logging.INFO, logger=workspace_ops.__name__):
        handlers = load_workspace_op_handlers(installed)  # type: ignore[arg-type]

    assert dict(handlers) == {"diff_stat": _other_head}
    messages = {record.levelno: record.getMessage() for record in caplog.records}
    assert messages[logging.ERROR] == (
        "Workspace op 'head' is offered by acme-tools (acme) and coral (coral); "
        "serving none of them"
    )
    assert messages[logging.INFO] == "Workspace op 'diff_stat' is served by coral (coral)"

    result = await dispatch_workspace_op(_op(), run_guarded=_RecordingGuard(), handlers=handlers)
    assert (result.error_code, result.permanent) == (UNKNOWN_OP, True)
    assert result.error == (
        "workspace op 'head' is offered by acme-tools (acme) and coral (coral); see the host log"
    )


async def test_unknown_op_after_a_failed_plugin_says_it_failed_to_load() -> None:
    handlers = load_workspace_op_handlers([_entry("coral", "_raising_ops")])
    result = await dispatch_workspace_op(_op(), run_guarded=_RecordingGuard(), handlers=handlers)
    assert (result.error_code, result.permanent) == (UNKNOWN_OP, True)
    assert result.error == (
        "no handler for workspace op 'head' is loaded: coral failed to load; see the host log"
    )


def test_contribution_without_ops_is_not_a_broken_entry_point(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A plugin whose handlers are switched off returns no ops; it adds nothing, silently."""
    with caplog.at_level(logging.WARNING, logger=workspace_ops.__name__):
        handlers = load_workspace_op_handlers(
            [_entry("a-disabled", "_no_ops"), _entry("b-first", "_first_ops")]
        )

    assert dict(handlers) == {"head": _head}
    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []


@pytest.mark.usefixtures("fresh_default_handlers")
def test_default_handlers_load_installed_entry_points_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups: list[str] = []

    def installed(*, group: str) -> list[importlib.metadata.EntryPoint]:
        groups.append(group)
        return [_entry("b-empty", "_no_ops"), _entry("a-first", "_first_ops")]

    monkeypatch.setattr(importlib.metadata, "entry_points", installed)
    first = workspace_ops.default_workspace_op_handlers()
    second = workspace_ops.default_workspace_op_handlers()

    assert groups == [ENTRY_POINT_GROUP]
    assert first is second
    assert dict(first) == {"head": _head}


def test_importing_the_host_loads_no_workspace_op_handlers(tmp_path: Path) -> None:
    """Handlers load on the first op frame, never while the host starts."""
    code = dedent("""\
        import importlib.metadata

        discover = importlib.metadata.entry_points
        groups = []

        # Record instead of raising: the loader would swallow an error raised here.
        def recording(**params):
            groups.append(params.get("group"))
            return discover(**params)

        importlib.metadata.entry_points = recording

        import omnigent.host.connect
        from omnigent.host import workspace_ops

        assert "omnigent.host_workspace_ops" not in groups, "discovered at import"
        assert workspace_ops.default_workspace_op_handlers.cache_info().currsize == 0
        """)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env=isolated_process_env(tmp_path, {}, None),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
