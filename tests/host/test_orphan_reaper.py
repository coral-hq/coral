"""Child-process ownership and runner reporting during orphan cleanup."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from omnigent.host.connect import HostProcess, _RunnerHandle
from omnigent.host.frames import (
    HostDetectCredentialsFrame,
    HostDetectCredentialsResultFrame,
    HostFsRequestFrame,
    HostFsResultFrame,
    HostFsWriteFrame,
    HostLaunchRunnerFrame,
    HostSkillContentFrame,
    HostSkillContentResultFrame,
    HostSkillsFrame,
    HostSkillsResultFrame,
    decode_host_frame,
)
from omnigent.host.identity import HostIdentity
from omnigent.host.runner_zygote import ZygoteManager, ZygoteRunnerProc
from omnigent.inner import _proc
from omnigent.runner.identity import RUNNER_FINISH_WORK_SIGNAL

pytestmark = pytest.mark.posix_only


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> HostProcess:
    monkeypatch.setenv("OMNIGENT_RUNNER_ZYGOTE", "0")
    monkeypatch.setattr("omnigent.host.connect._RUNNER_WATCH_INTERVAL_S", 0.01)
    return HostProcess(
        identity=HostIdentity(host_id="host_reaper_test", name="reaper-test"),
        server_url="http://localhost:8000",
        interactive_shells=["bash"],
    )


@pytest.fixture
def zombie_child() -> Iterator[Callable[[], int]]:
    """Create only our own direct children, and collect them even on failure."""
    children: list[int] = []

    def spawn() -> int:
        pid = os.posix_spawn(
            sys.executable,
            [sys.executable, "-c", "import os; os._exit(0)"],
            os.environ,
        )
        children.append(pid)
        return pid

    try:
        yield spawn
    finally:
        for pid in children:
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, 0)


def _wait_for_zombie(pid: int) -> None:
    """Wait until ``pid`` has exited, without collecting its status."""
    deadline = time.monotonic() + 5.0
    while psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
        assert time.monotonic() < deadline, "child did not exit"
        time.sleep(0.01)


@contextlib.contextmanager
def _exited_process(exit_code: int) -> Iterator[subprocess.Popen[bytes]]:
    """Leave an exited child waitable until its real owner collects its status."""
    proc = subprocess.Popen(
        [sys.executable, "-c", f"import os; os._exit({exit_code})"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.read() == b""
        # CORAL(S71): psutil sees a zombie on every POSIX platform, unlike waitid.
        _wait_for_zombie(proc.pid)
        yield proc
    finally:
        proc.wait(timeout=5.0)
        if proc.stdout is not None:
            proc.stdout.close()


def _reap(host: HostProcess, expected: int, child_pids: list[int]) -> None:
    """Sweep until ``expected`` children are reaped; CORAL(S71): a first sweep only records."""
    deadline = time.monotonic() + 2.0
    reaped = 0
    while reaped < expected and time.monotonic() < deadline:
        reaped += host._reap_orphans_once(child_pids=child_pids)
        if reaped < expected:
            time.sleep(0.01)
    assert reaped == expected


def _assert_reaped(pid: int) -> None:
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


def test_child_discovery_preserves_exit_status(host: HostProcess) -> None:
    with _exited_process(42) as proc:
        assert proc.pid in host._orphan_child_pids()

        assert proc.returncode is None
        assert proc.wait(timeout=5.0) == 42


def test_targeted_sweep_leaves_unrelated_child_waitable(
    host: HostProcess, zombie_child: Callable[[], int]
) -> None:
    with _exited_process(43) as unrelated:
        orphan = zombie_child()

        _reap(host, expected=1, child_pids=[orphan])

        _assert_reaped(orphan)
        assert unrelated.returncode is None
        assert unrelated.wait(timeout=5.0) == 43


# CORAL(S71): the two-sweep zombie rule protects owners that no guard covers.
@pytest.mark.asyncio
async def test_reaper_loop_leaves_unguarded_child_exit_status_to_its_owner(
    host: HostProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _exited_process(42) as proc:
        swept = asyncio.Event()
        original_sweep = host._reap_orphans_once

        def observed_sweep(child_pids: Iterable[int] | None = None) -> int:
            count = original_sweep(child_pids)
            swept.set()
            return count

        monkeypatch.setattr(host, "_orphan_child_pids", lambda: [proc.pid])
        monkeypatch.setattr(host, "_reap_orphans_once", observed_sweep)
        monkeypatch.setattr("omnigent.host.connect._ORPHAN_REAP_INTERVAL_S", 0.01)
        reaper = asyncio.create_task(host._orphan_reaper_loop())
        try:
            await asyncio.wait_for(swept.wait(), timeout=5.0)
            assert host._owned_subprocess_ops == 0
            assert proc.pid in host._orphan_zombie_candidates
            assert proc.returncode is None

            # Like subprocess.run, the owner collects its child before the next sweep.
            assert proc.wait(timeout=5.0) == 42
            swept.clear()
            await asyncio.wait_for(swept.wait(), timeout=5.0)
            assert host._orphan_zombie_candidates == {}
        finally:
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)


def test_true_orphan_is_reaped_by_the_second_sweep(
    host: HostProcess, zombie_child: Callable[[], int]
) -> None:
    orphan = zombie_child()
    _wait_for_zombie(orphan)

    assert host._reap_orphans_once([orphan]) == 0
    assert host._reap_orphans_once([orphan]) == 1

    _assert_reaped(orphan)
    assert host._orphan_zombie_candidates == {}


def test_reused_pid_restarts_the_two_sweep_wait(
    host: HostProcess, zombie_child: Callable[[], int]
) -> None:
    orphan = zombie_child()
    _wait_for_zombie(orphan)
    create_time = _proc.process_create_time(orphan)
    assert create_time is not None
    # The previous sweep saw an earlier process at this PID.
    host._orphan_zombie_candidates = {orphan: create_time - 1.0}

    assert host._reap_orphans_once([orphan]) == 0
    assert host._orphan_zombie_candidates == {orphan: create_time}
    assert host._reap_orphans_once([orphan]) == 1

    _assert_reaped(orphan)


def test_long_reaper_pause_warns_at_a_limited_rate(
    host: HostProcess, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="omnigent.host.connect"):
        with host._host_subprocess_op():
            for now in (100.0, 160.0, 161.0, 400.0, 461.0):
                assert host._orphan_sweep_paused(now)
        assert not host._orphan_sweep_paused(462.0)
        # A new pause is timed from its own start, and shares the rate limit.
        with host._host_subprocess_op():
            for now in (470.0, 531.0, 761.0):
                assert host._orphan_sweep_paused(now)

    assert [record.getMessage().split(";")[0] for record in caplog.records] == [
        "Orphan reaper paused for 61s by 1 host subprocess operation(s)",
        "Orphan reaper paused for 361s by 1 host subprocess operation(s)",
        "Orphan reaper paused for 291s by 1 host subprocess operation(s)",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code", [0, 42])
async def test_watcher_releases_exited_runner_and_keeps_crash_report(
    host: HostProcess, tmp_path: Path, exit_code: int
) -> None:
    with _exited_process(exit_code) as proc:
        host._runners["runner_exited"] = _RunnerHandle(proc=proc, log_path=tmp_path / "runner.log")

        await asyncio.wait_for(host._watch_runner("runner_exited"), timeout=5.0)

        assert "runner_exited" not in host._runners
        assert proc.pid not in host._tracked_runner_pids()
        assert proc.returncode == exit_code
        if exit_code:
            assert set(host._unreported_exits) == {"runner_exited"}
            report = host._unreported_exits["runner_exited"]
            assert "code 42" in report.error
            assert report.had_connected is None
        else:
            assert host._unreported_exits == {}


def test_completed_runner_handle_does_not_claim_reused_pid(
    host: HostProcess,
    tmp_path: Path,
    zombie_child: Callable[[], int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _exited_process(0) as proc:
        assert proc.wait(timeout=5.0) == 0
        reused_pid = zombie_child()
        # Reconstruct PID reuse without churning through the OS process IDs.
        monkeypatch.setattr(proc, "pid", reused_pid)
        host._runners["runner_completed"] = _RunnerHandle(
            proc=proc, log_path=tmp_path / "runner.log"
        )
        behind = zombie_child()

        _reap(host, expected=2, child_pids=[reused_pid, behind])

        _assert_reaped(reused_pid)
        _assert_reaped(behind)
        assert proc.returncode == 0


def test_exited_runner_without_watcher_does_not_block_orphans(
    host: HostProcess, tmp_path: Path, zombie_child: Callable[[], int]
) -> None:
    with _exited_process(42) as proc:
        host._runners["runner_unwatched"] = _RunnerHandle(
            proc=proc, log_path=tmp_path / "runner.log"
        )
        assert proc.returncode is None
        assert not host._watcher_tasks
        orphan = zombie_child()

        _reap(host, expected=1, child_pids=[proc.pid, orphan])

        _assert_reaped(orphan)
        assert proc.poll() == 42


def test_exited_zygote_does_not_block_orphans_or_lose_exit_status(
    host: HostProcess, zombie_child: Callable[[], int]
) -> None:
    with _exited_process(43) as proc:
        manager = ZygoteManager()
        manager._proc = proc
        host._zygote = manager
        orphan = zombie_child()

        _reap(host, expected=1, child_pids=[proc.pid, orphan])

        _assert_reaped(orphan)
        assert proc.poll() == 43
        assert not manager.is_running()


def test_completed_zygote_does_not_claim_reused_pid(
    host: HostProcess,
    zombie_child: Callable[[], int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _exited_process(43) as proc:
        assert proc.wait(timeout=5.0) == 43
        reused_pid = zombie_child()
        monkeypatch.setattr(proc, "pid", reused_pid)
        manager = ZygoteManager()
        manager._proc = proc
        host._zygote = manager

        _reap(host, expected=1, child_pids=[reused_pid])

        _assert_reaped(reused_pid)
        assert proc.returncode == 43


def test_busy_runner_owner_does_not_block_other_ready_children(
    host: HostProcess, tmp_path: Path, zombie_child: Callable[[], int]
) -> None:
    with _exited_process(42) as proc:
        host._runners["runner_busy"] = _RunnerHandle(proc=proc, log_path=tmp_path / "runner.log")
        orphan = zombie_child()

        # Popen.poll() cannot collect this child while another owner holds its lock.
        with proc._waitpid_lock:  # type: ignore[attr-defined]
            _reap(host, expected=1, child_pids=[proc.pid, orphan])
            assert proc.returncode is None

        _assert_reaped(orphan)
        assert proc.poll() == 42


def test_zygote_runner_owner_needs_no_ipc_to_reap_other_children(
    host: HostProcess,
    tmp_path: Path,
    zombie_child: Callable[[], int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_pid = zombie_child()
    orphan = zombie_child()
    manager = ZygoteManager()

    def unexpected_poll(pid: int) -> int | None:
        pytest.fail("orphan cleanup must not make a blocking zygote control request")

    monkeypatch.setattr(manager, "poll", unexpected_poll)
    proc = ZygoteRunnerProc(owned_pid, manager)
    host._runners["runner_zygote"] = _RunnerHandle(proc=proc, log_path=tmp_path / "runner.log")

    _reap(host, expected=1, child_pids=[owned_pid, orphan])

    _assert_reaped(orphan)
    assert proc.returncode is None
    assert os.waitpid(owned_pid, 0) == (owned_pid, 0)


def test_unowned_running_child_does_not_block_orphan_cleanup(
    host: HostProcess, zombie_child: Callable[[], int]
) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        orphan = zombie_child()

        _reap(host, expected=1, child_pids=[proc.pid, orphan])

        _assert_reaped(orphan)
        assert proc.poll() is None
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(timeout=5.0)


@pytest.mark.asyncio
async def test_worker_poll_between_snapshot_and_sweep_preserves_crash_report(
    host: HostProcess,
    tmp_path: Path,
    zombie_child: Callable[[], int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _exited_process(42) as proc:
        handle = _RunnerHandle(proc=proc, log_path=tmp_path / "runner.log")
        host._runners["runner_racing"] = handle
        orphan = zombie_child()
        snapshot = [proc.pid, orphan]
        polled = threading.Event()
        release = threading.Event()
        loop_thread = threading.get_ident()
        original_poll = proc.poll

        def paused_worker_poll() -> int | None:
            code = original_poll()
            if threading.get_ident() != loop_thread:
                polled.set()
                assert release.wait(timeout=5.0), "worker poll was not released"
            return code

        monkeypatch.setattr(proc, "poll", paused_worker_poll)
        watcher = asyncio.create_task(host._watch_runner("runner_racing"))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(polled.wait, 5.0), timeout=6.0)
            assert proc.returncode == 42

            # The process has been collected, but its watcher has not resumed yet.
            _reap(host, expected=1, child_pids=snapshot)
            assert host._runners.get("runner_racing") is handle

            release.set()
            await asyncio.wait_for(watcher, timeout=5.0)

            _assert_reaped(orphan)
            assert "runner_racing" not in host._runners
            assert set(host._unreported_exits) == {"runner_racing"}
            report = host._unreported_exits["runner_racing"]
            assert "code 42" in report.error
            assert report.had_connected is None
        finally:
            release.set()
            await asyncio.gather(watcher, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_kind", ["host-operation", "runner"])
async def test_discovery_rechecks_ownership_before_reaping(
    host: HostProcess,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_kind: str,
) -> None:
    with _exited_process(42) as proc:
        started = threading.Event()
        resume = threading.Event()
        swept = asyncio.Event()
        counts: list[int] = []
        original_sweep = host._reap_orphans_once

        def paused_discovery() -> list[int]:
            started.set()
            assert resume.wait(timeout=5.0), "discovery was not released"
            return [proc.pid]

        def observed_sweep(child_pids: Iterable[int] | None = None) -> int:
            count = original_sweep(child_pids)
            counts.append(count)
            swept.set()
            return count

        # CORAL(S71): a first sweep records the zombie, so the loop's sweep would reap it.
        assert host._reap_orphans_once([proc.pid]) == 0
        monkeypatch.setattr(host, "_orphan_child_pids", paused_discovery)
        monkeypatch.setattr(host, "_reap_orphans_once", observed_sweep)
        monkeypatch.setattr("omnigent.host.connect._ORPHAN_REAP_INTERVAL_S", 0.01)
        reaper = asyncio.create_task(host._orphan_reaper_loop())
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5.0), timeout=6.0)
            if owner_kind == "runner":
                host._runners["runner_registered"] = _RunnerHandle(
                    proc=proc, log_path=tmp_path / "runner.log"
                )
            guard = (
                host._host_subprocess_op()
                if owner_kind == "host-operation"
                else contextlib.nullcontext()
            )
            with guard:
                resume.set()
                await asyncio.wait_for(swept.wait(), timeout=5.0)

                assert counts[0] == 0
                assert proc.wait(timeout=5.0) == 42

            if owner_kind == "runner":
                assert "runner_registered" in host._runners
                await asyncio.wait_for(host._watch_runner("runner_registered"), timeout=5.0)
                report = host._unreported_exits["runner_registered"]
                assert "code 42" in report.error
                assert report.had_connected is None
        finally:
            resume.set()
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)


def test_vanished_first_child_does_not_block_later_orphan(
    host: HostProcess, zombie_child: Callable[[], int]
) -> None:
    with _exited_process(42) as proc:
        orphan = zombie_child()
        snapshot = [proc.pid, orphan]
        assert proc.wait(timeout=5.0) == 42

        _reap(host, expected=1, child_pids=snapshot)

        _assert_reaped(orphan)


@pytest.mark.asyncio
async def test_launch_protects_child_until_spawn_worker_returns(
    host: HostProcess, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host._auth_token_factory = lambda: "test-bootstrap-bearer"
    host._auth_token_factory_resolved = True
    started = threading.Event()
    resume = threading.Event()
    frame = HostLaunchRunnerFrame(
        request_id="req_spawn_race",
        binding_token="test-spawn-token",
        workspace=str(tmp_path),
    )

    with _exited_process(42) as proc:

        def paused_spawn(
            env: dict[str, str], session_slug: str, workspace: Path
        ) -> tuple[subprocess.Popen[bytes], Path]:
            started.set()
            assert resume.wait(timeout=5.0), "spawn worker was not released"
            return proc, tmp_path / "runner.log"

        # CORAL(S71): a first sweep records the zombie before the launch guard.
        assert host._reap_orphans_once([proc.pid]) == 0
        monkeypatch.setattr(host, "_spawn_runner_proc", paused_spawn)
        launch = asyncio.create_task(host._handle_launch(frame))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5.0), timeout=6.0)
            assert host._owned_subprocess_ops == 1
            assert not host._runners
            assert proc.returncode is None

            assert host._reap_orphans_once([proc.pid]) == 0
            assert proc.returncode is None

            resume.set()
            result = await asyncio.wait_for(launch, timeout=5.0)

            assert result.status == "failed"
            assert "code 42" in (result.error or "")
            assert proc.returncode == 42
            assert host._owned_subprocess_ops == 0
            assert not host._runners
        finally:
            resume.set()
            await asyncio.wait_for(asyncio.gather(launch, return_exceptions=True), timeout=5.0)


class _CollectingTunnel:
    """Tunnel stand-in that records every frame the host sends."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, data: str) -> None:
        self.sent.append(data)


# CORAL(S71): frame handlers whose git/gh/CLI children must keep their exit statuses.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("frame", "handler_name", "reply"),
    [
        pytest.param(
            HostFsRequestFrame("fs-read", "changes", "/workspace", "session"),
            "_handle_fs_request",
            lambda code: HostFsResultFrame("fs-read", "ok", payload={"returncode": code}),
            id="fs_request",
        ),
        pytest.param(
            HostFsWriteFrame("fs-write", "github_merge", "/workspace", "session"),
            "_handle_fs_write",
            lambda code: HostFsResultFrame("fs-write", "ok", payload={"returncode": code}),
            id="fs_write",
        ),
        pytest.param(
            HostSkillsFrame("skills", "codex", "/workspace"),
            "_handle_skills",
            lambda code: HostSkillsResultFrame(
                "skills", "ok", skills=[{"name": "exit-status", "description": str(code)}]
            ),
            id="skills",
        ),
        pytest.param(
            HostSkillContentFrame("skill-content", "codex", "exit-status"),
            "_handle_skill_content",
            lambda code: HostSkillContentResultFrame(
                "skill-content",
                "ok",
                skill={
                    "name": "exit-status",
                    "description": str(code),
                    "content": "",
                    "truncated": False,
                },
            ),
            id="skill_content",
        ),
        pytest.param(
            HostDetectCredentialsFrame("credentials"),
            "_handle_detect_credentials",
            lambda code: HostDetectCredentialsResultFrame(
                "credentials",
                credentials=[{"family": "exit-status", "source": str(code), "env_var": None}],
            ),
            id="detect_credentials",
        ),
    ],
)
async def test_frame_handler_keeps_child_exit_status_while_reaper_sweeps(
    host: HostProcess,
    monkeypatch: pytest.MonkeyPatch,
    frame: object,
    handler_name: str,
    reply: Callable[[int], object],
) -> None:
    started = threading.Event()
    resume = threading.Event()
    tunnel = _CollectingTunnel()

    with _exited_process(42) as proc:

        def paused_handler(request: object) -> object:
            assert request is frame
            started.set()
            assert resume.wait(timeout=5.0), "frame worker was not released"
            return reply(proc.wait(timeout=5.0))

        # A first sweep records the zombie, as when run() still reads a held-open pipe.
        assert host._reap_orphans_once([proc.pid]) == 0
        monkeypatch.setattr(host, handler_name, paused_handler)
        dispatch = asyncio.create_task(
            host._dispatch_host_frame(tunnel, frame)  # type: ignore[arg-type]
        )
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5.0), timeout=6.0)
            assert host._owned_subprocess_ops == 1

            # The second sweep would reap the exited child but for the handler's guard.
            assert host._reap_orphans_once([proc.pid]) == 0
            assert proc.returncode is None

            resume.set()
            await asyncio.wait_for(dispatch, timeout=5.0)

            assert [decode_host_frame(sent) for sent in tunnel.sent] == [reply(42)]
            assert host._owned_subprocess_ops == 0
        finally:
            resume.set()
            await asyncio.wait_for(asyncio.gather(dispatch, return_exceptions=True), timeout=5.0)


def test_hangup_signals_live_runners_but_not_the_zygote(
    host: HostProcess, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zygote_pid = 4000
    monkeypatch.setattr(host, "_zygote", SimpleNamespace(unreaped_pid=zygote_pid))
    # Direct handles are polled so an unreaped exit never signals a reused PID.
    for name, pid, code in (
        ("live_a", 4001, None),
        ("exited", 4002, 0),
        ("live_b", 4003, None),
        ("zygote_alias", zygote_pid, None),
    ):
        proc = SimpleNamespace(pid=pid, poll=lambda c=code: c)
        host._runners[name] = _RunnerHandle(proc=proc, log_path=tmp_path / "runner.log")  # type: ignore[arg-type]
    # A forked runner reports its cached status without a blocking zygote
    # round trip, which the exit thread must never make.
    manager = ZygoteManager()
    monkeypatch.setattr(
        manager, "poll", lambda *a, **k: pytest.fail("exit thread blocked on zygote IPC")
    )
    # The zygote, not the host, reaps forked runners, so a forked PID can be
    # recycled; the sweep signals one only when its live start time still
    # matches the identity recorded at launch.
    live_create_times = {4005: 111.0, 4007: 222.0}
    monkeypatch.setattr(
        "omnigent.inner._proc.process_create_time", lambda pid: live_create_times.get(pid)
    )
    forked = ZygoteRunnerProc(4005, manager)
    host._runners["forked_live"] = _RunnerHandle(
        proc=forked, log_path=tmp_path / "runner.log", create_time=111.0
    )
    # A forked runner the zygote already reaped reports its cached exit code, so
    # its reused PID is skipped from that cache without a blocking poll.
    forked_exited = ZygoteRunnerProc(4006, manager)
    forked_exited.returncode = 1
    host._runners["forked_exited"] = _RunnerHandle(
        proc=forked_exited, log_path=tmp_path / "runner.log", create_time=333.0
    )
    # A forked runner whose cache still reads live but whose PID the OS reused
    # for an unrelated process (a different start time) must not be signalled.
    forked_reused = ZygoteRunnerProc(4007, manager)
    host._runners["forked_reused"] = _RunnerHandle(
        proc=forked_reused, log_path=tmp_path / "runner.log", create_time=999.0
    )
    sent: list[tuple[int, int]] = []

    def kill(pid: int, sig: int) -> None:
        sent.append((pid, sig))
        if pid == 4001:
            raise ProcessLookupError(pid)  # a runner that just exited must not stop the sweep

    host.signal_runners_finish_work(kill=kill)

    assert sent == [
        (4001, RUNNER_FINISH_WORK_SIGNAL),
        (4003, RUNNER_FINISH_WORK_SIGNAL),
        (4005, RUNNER_FINISH_WORK_SIGNAL),
    ]
    assert 4007 not in [pid for pid, _ in sent]  # the reused PID was never signalled
