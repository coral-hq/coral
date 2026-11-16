"""Tests for ``coral.omni.server.worktrees`` against real git over a fake host connection.

The connection lives in a real ``HostRegistry``. A drain task answers each frame
the server sends with the real host handler (``HostProcess._handle_stat``,
``_handle_list_worktrees``, ``_handle_create_worktree``), so git runs through
``omnigent.host.git_worktree`` in ``tmp_path``. Each result frame goes through
the wire codec and resolves the server's future with the fields
``host_tunnel.py`` relays.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, fields
from pathlib import Path

import pytest

import omnigent.server.routes._host_worktree as host_worktree
import omnigent.server.routes._workspace_validation as workspace_validation
from coral.omni.server.worktrees import connect_run_worktree_host
from coral.workspace.run_worktree import (
    RepoBinding,
    RunWorktree,
    RunWorktreeError,
    RunWorktreeHost,
    bind_repo,
    create_or_adopt_run_worktree,
    run_branch_name,
)
from omnigent.db.account_authority import AccountAuthority, account_authority_scope
from omnigent.db.db_models import current_workspace_id
from omnigent.host.connect import HostProcess
from omnigent.host.frames import (
    HOST_CAPABILITIES,
    HostCreateWorktreeFrame,
    HostListWorktreesFrame,
    HostStatFrame,
    decode_host_frame,
    encode_host_frame,
)
from omnigent.host.git_worktree import validate_branch_name
from omnigent.host.identity import HostIdentity
from omnigent.server import host_registry as host_registry_module
from omnigent.server.host_registry import HostConnection, HostRegistry
from omnigent.stores.host_store import Host
from tests.host.test_git_worktree import _current_branch, _git, _rev_parse, _worktree_count
from tests.host.test_git_worktree import git_repo as git_repo
from tests.server.routes.test_host_worktree import _FakeWebSocket, _hello_frame

_HOST_ID = "host_run_worktree"
_OWNER = "alice@example.com"
_GENERATION = "gen-1"
# A non-default workspace proves the host row and the connection are read in its scope.
_WORKSPACE_ID = 7


class _HostRows:
    """``HostStore.get_host`` keyed like the hosts table, by (workspace, host id)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, str], Host] = {}

    def get_host(self, host_id: str) -> Host | None:
        return self.rows.get((current_workspace_id(), host_id))


def _host_row(
    *,
    user_id: str = _OWNER,
    generation: str | None = _GENERATION,
    sandbox_provider: str | None = None,
) -> Host:
    return Host(
        host_id=_HOST_ID,
        name="laptop",
        user_id=user_id,
        status="online",
        created_at=0,
        updated_at=0,
        sandbox_provider=sandbox_provider,
        account_generation=generation,
    )


def _relayed(result: object) -> dict[str, object]:
    """The dict ``host_tunnel.py`` resolves a future with today: the result frame's fields."""
    decoded = decode_host_frame(encode_host_frame(result))  # type: ignore[arg-type]
    return {
        item.name: getattr(decoded, item.name)
        for item in fields(decoded)  # type: ignore[arg-type]
        if item.name != "request_id"
    }


@dataclass
class _Tunnel:
    """The server side of a host's connections, and every frame the server sent."""

    registry: HostRegistry
    host: HostProcess
    host_rows: _HostRows = field(default_factory=_HostRows)
    frames: list[object] = field(default_factory=list)
    # The host disconnects instead of answering the first frame of this type.
    disconnect_on: type | None = None
    # The host stays connected but never answers frames of this type.
    unanswered: type | None = None
    # Answer each frame on its own task, as the host's frame dispatcher does.
    concurrent: bool = False
    answering: list[asyncio.Task[None]] = field(default_factory=list)

    def connect(self, *, owner: str = _OWNER, generation: str = _GENERATION) -> None:
        """Register a connection, replacing any earlier one, and answer its frames."""
        # The tunnel binds the stored registration before it registers the connection.
        with account_authority_scope(owner, generation):
            conn = self.registry.register(
                host_id=_HOST_ID,
                ws=_FakeWebSocket(),  # type: ignore[arg-type]
                hello=_hello_frame(list(HOST_CAPABILITIES)),
                owner=owner,
                workspace_id=_WORKSPACE_ID,
            )
        self.answering.append(asyncio.create_task(self._answer(conn)))

    def disconnect(self) -> None:
        self.registry.deregister(_HOST_ID, workspace_id=_WORKSPACE_ID)

    def frame_types(self) -> list[type]:
        return [type(frame) for frame in self.frames]

    async def _answer(self, conn: HostConnection) -> None:
        replies: list[asyncio.Task[None]] = []
        while (outbound := await conn.outbound_queue.get()) is not None:
            frame = decode_host_frame(outbound.data)
            self.frames.append(frame)
            if self.disconnect_on is not None and isinstance(frame, self.disconnect_on):
                self.disconnect()
                continue
            if self.unanswered is not None and isinstance(frame, self.unanswered):
                continue
            if self.concurrent:
                replies.append(asyncio.create_task(self._reply(conn, frame)))
            else:
                await self._reply(conn, frame)
        await asyncio.gather(*replies)

    async def _reply(self, conn: HostConnection, frame: object) -> None:
        if isinstance(frame, HostStatFrame):
            pending = conn.pending_stats
            result: object = await asyncio.to_thread(self.host._handle_stat, frame)
        elif isinstance(frame, HostListWorktreesFrame):
            pending = conn.pending_list_worktrees
            result = await self.host._handle_list_worktrees(frame)
        elif isinstance(frame, HostCreateWorktreeFrame):
            pending = conn.pending_create_worktrees
            result = await self.host._handle_create_worktree(frame)
        else:
            return
        future = pending.pop(frame.request_id, None)
        if future is not None and not future.done():
            future.set_result(_relayed(result))


@pytest.fixture()
async def tunnel() -> AsyncIterator[_Tunnel]:
    host = HostProcess(
        identity=HostIdentity(host_id=_HOST_ID, name="laptop"),
        server_url="http://localhost:8000",
    )
    state = _Tunnel(registry=HostRegistry(), host=host)
    state.host_rows.rows[(_WORKSPACE_ID, _HOST_ID)] = _host_row()
    state.connect()
    try:
        yield state
    finally:
        state.disconnect()
        await asyncio.wait_for(asyncio.gather(*state.answering), timeout=30.0)


async def _connect(
    tunnel: _Tunnel,
    *,
    user_id: str | None = _OWNER,
    generation: str | None = _GENERATION,
    workspace_id: int = _WORKSPACE_ID,
) -> RunWorktreeHost:
    return await connect_run_worktree_host(
        host_registry=tunnel.registry,
        host_store=tunnel.host_rows,  # type: ignore[arg-type]
        user_id=user_id,
        account_generation=generation,
        host_id=_HOST_ID,
        workspace_id=workspace_id,
    )


async def _run_worktree(tunnel: _Tunnel, repo_root: str) -> RunWorktree:
    return await create_or_adopt_run_worktree(
        await _connect(tunnel), repo_root=repo_root, run_id="run-1", base_ref="main"
    )


async def _failure(tunnel: _Tunnel, repo_root: str) -> RunWorktreeError:
    with pytest.raises(RunWorktreeError) as caught:
        await _run_worktree(tunnel, repo_root)
    return caught.value


@pytest.mark.parametrize("run_id", ["run-1", "ü/../~:^ x.lock"])
def test_run_branch_name_is_a_valid_git_branch(run_id: str) -> None:
    validate_branch_name(run_branch_name(run_id))


async def test_first_call_creates_the_sibling_worktree_and_the_next_adopts_it(
    git_repo: Path, tunnel: _Tunnel
) -> None:
    branch = run_branch_name("run-1")
    run12 = hashlib.sha256(b"run-1").hexdigest()[:12]
    expected = git_repo.parent / "myrepo-worktrees" / f"coral-r-{run12}-base"

    created = await _run_worktree(tunnel, str(git_repo))

    assert created == RunWorktree(
        path=str(expected), branch=branch, start_commit=_rev_parse(expected), adopted=False
    )
    assert created.start_commit == _rev_parse(git_repo, "main")
    assert _current_branch(expected) == branch

    adopted = await _run_worktree(tunnel, str(git_repo))

    assert adopted == RunWorktree(
        path=str(expected), branch=branch, start_commit=None, adopted=True
    )
    assert _worktree_count(git_repo) == 2
    assert tunnel.frame_types().count(HostCreateWorktreeFrame) == 1


async def test_deleted_worktree_directory_is_recreated_at_the_same_path(
    git_repo: Path, tunnel: _Tunnel
) -> None:
    created = await _run_worktree(tunnel, str(git_repo))
    shutil.rmtree(created.path)

    recreated = await _run_worktree(tunnel, str(git_repo))

    assert recreated == RunWorktree(
        path=created.path, branch=created.branch, start_commit=None, adopted=True
    )
    assert _current_branch(Path(created.path)) == created.branch
    creates = [frame for frame in tunnel.frames if isinstance(frame, HostCreateWorktreeFrame)]
    assert [frame.existing_branch for frame in creates] == [False, False, True]


@pytest.mark.parametrize("leftover", ["directory", "file"])
async def test_a_leftover_at_a_stale_worktree_path_is_not_adopted(
    git_repo: Path, tunnel: _Tunnel, leftover: str
) -> None:
    created = await _run_worktree(tunnel, str(git_repo))
    shutil.rmtree(created.path)
    if leftover == "directory":
        Path(created.path).mkdir()
    else:
        Path(created.path).write_text("not a worktree\n")

    recreated = await _run_worktree(tunnel, str(git_repo))

    # Recovered beside the leftover through the existing-branch retry, not an error.
    assert recreated.path == f"{created.path}-2"
    assert (recreated.adopted, recreated.start_commit) == (True, None)
    assert (Path(recreated.path) / ".git").is_file()
    assert _current_branch(Path(recreated.path)) == created.branch
    assert Path(created.path).is_dir() is (leftover == "directory")
    assert not (Path(created.path) / ".git").exists()


async def test_a_detached_run_worktree_is_refused_not_forked(
    git_repo: Path, tunnel: _Tunnel
) -> None:
    created = await _run_worktree(tunnel, str(git_repo))
    _git(Path(created.path), "checkout", "-q", "--detach")

    failure = await _failure(tunnel, str(git_repo))

    assert failure.code == "worktree_failed"
    assert "run worktree is detached; repair it" in failure.message
    assert _worktree_count(git_repo) == 2
    assert tunnel.frame_types().count(HostCreateWorktreeFrame) == 1


async def test_concurrent_calls_for_one_run_share_one_worktree(
    git_repo: Path, tunnel: _Tunnel
) -> None:
    # The creates race inside git, so the losers must adopt through the retry path.
    tunnel.concurrent = True
    host = await _connect(tunnel)

    results = await asyncio.gather(
        *(
            create_or_adopt_run_worktree(
                host, repo_root=str(git_repo), run_id="run-1", base_ref="main"
            )
            for _ in range(4)
        )
    )

    assert len({result.path for result in results}) == 1
    assert _worktree_count(git_repo) == 2
    # Only the call that made the branch may report its start commit.
    assert sum(not result.adopted for result in results) <= 1
    assert {result.start_commit for result in results} <= {None, _rev_parse(git_repo, "main")}


@pytest.mark.parametrize(
    ("prepare", "base_ref", "explanation"),
    [
        (lambda repo: None, "no-such-ref", "base branch does not exist: no-such-ref"),
        (
            lambda repo: _git(repo, "checkout", "-q", "-b", run_branch_name("run-1")),
            "main",
            "is already checked out at",
        ),
    ],
    ids=["missing-base-ref", "run-branch-in-main-worktree"],
)
async def test_a_failed_create_and_retry_leave_no_worktree(
    git_repo: Path,
    tunnel: _Tunnel,
    prepare: Callable[[Path], None],
    base_ref: str,
    explanation: str,
) -> None:
    prepare(git_repo)

    with pytest.raises(RunWorktreeError) as caught:
        await create_or_adopt_run_worktree(
            await _connect(tunnel), repo_root=str(git_repo), run_id="run-1", base_ref=base_ref
        )

    assert caught.value.code == "worktree_failed"
    assert explanation in caught.value.message
    assert tunnel.frame_types().count(HostCreateWorktreeFrame) == 2
    assert _worktree_count(git_repo) == 1


@pytest.mark.parametrize(
    ("make_root", "make_dir", "expected_frames"),
    [
        (lambda repo: repo.parent / "ghost", False, [HostStatFrame]),
        (
            lambda repo: repo.parent / "plain",
            True,
            [HostStatFrame, HostListWorktreesFrame, HostStatFrame],
        ),
        (lambda repo: repo / "notes", True, [HostStatFrame, HostListWorktreesFrame]),
        (lambda repo: Path("~") / repo.name, False, []),
    ],
    ids=["missing", "not-git", "nested-plain-dir", "tilde"],
)
async def test_rejects_a_root_that_is_not_a_git_repo_root(
    git_repo: Path,
    tunnel: _Tunnel,
    make_root: Callable[[Path], Path],
    make_dir: bool,
    expected_frames: list[type],
) -> None:
    root = make_root(git_repo)
    if make_dir:
        root.mkdir()

    failure = await _failure(tunnel, str(root))

    assert failure.code == "not_a_git_repo"
    assert tunnel.frame_types() == expected_frames
    assert _worktree_count(git_repo) == 1


async def test_bind_repo_from_a_linked_worktree_binds_the_main_root(
    git_repo: Path, tunnel: _Tunnel
) -> None:
    created = await _run_worktree(tunnel, str(git_repo))

    binding = await bind_repo(
        await _connect(tunnel),
        user_id=_OWNER,
        host_id=_HOST_ID,
        repo_root=created.path,
        default_base_ref=None,
    )

    assert binding == RepoBinding(
        user_id=_OWNER, host_id=_HOST_ID, repo_root=str(git_repo), default_base_ref=None
    )


async def test_a_listing_failure_beside_a_git_entry_is_a_worktree_failure(
    tmp_path: Path, tunnel: _Tunnel
) -> None:
    broken = (tmp_path / "broken").resolve()
    broken.mkdir()
    (broken / ".git").write_text("not a gitdir pointer\n")

    failure = await _failure(tunnel, str(broken))

    assert failure.code == "worktree_failed"
    assert "git worktree list failed" in failure.message


async def test_a_stat_failure_on_a_live_host_is_a_worktree_failure(
    tmp_path: Path, tunnel: _Tunnel
) -> None:
    loop = (tmp_path / "loop").resolve()
    loop.symlink_to(loop)

    failure = await _failure(tunnel, str(loop))

    assert failure.code == "worktree_failed"
    assert "stat failed" in failure.message


_FRAME_TYPES = [HostStatFrame, HostListWorktreesFrame, HostCreateWorktreeFrame]


def _short_host_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workspace_validation, "_STAT_TIMEOUT_S", 0.2)
    monkeypatch.setattr(host_worktree, "_WORKTREE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(host_worktree, "_WORKTREE_CREATE_TIMEOUT_S", 0.2)


@pytest.mark.parametrize("frame_type", _FRAME_TYPES)
async def test_host_disconnecting_mid_call_is_host_offline(
    git_repo: Path, tunnel: _Tunnel, frame_type: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A disconnect fails pending worktree replies at once; a stat reply just never comes.
    _short_host_timeouts(monkeypatch)
    tunnel.disconnect_on = frame_type

    failure = await _failure(tunnel, str(git_repo))

    assert failure.code == "host_offline"
    # Raised by the interrupted call itself: a create is not retried on a lost host.
    assert failure.__cause__ is not None
    assert tunnel.frame_types()[-1] is frame_type
    assert _worktree_count(git_repo) == 1


@pytest.mark.parametrize("frame_type", _FRAME_TYPES)
async def test_a_connected_host_that_never_answers_is_a_worktree_failure(
    git_repo: Path, tunnel: _Tunnel, frame_type: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    _short_host_timeouts(monkeypatch)
    tunnel.unanswered = frame_type

    failure = await _failure(tunnel, str(git_repo))

    assert failure.code == "worktree_failed"
    assert "did not respond" in failure.message
    assert tunnel.frame_types()[-1] is frame_type


async def test_no_live_connection_is_host_offline_at_connect(tunnel: _Tunnel) -> None:
    tunnel.disconnect()

    with pytest.raises(RunWorktreeError) as caught:
        await _connect(tunnel)

    assert caught.value.code == "host_offline"
    assert tunnel.frames == []


async def test_each_call_uses_the_current_connection(git_repo: Path, tunnel: _Tunnel) -> None:
    host = await _connect(tunnel)
    tunnel.disconnect()

    with pytest.raises(RunWorktreeError) as caught:
        await host.stat(str(git_repo))
    assert caught.value.code == "host_offline"

    # A host that reconnects is used again; the replaced connection would refuse to send.
    tunnel.connect()
    created = await create_or_adopt_run_worktree(
        host, repo_root=str(git_repo), run_id="run-1", base_ref=None
    )

    assert created.adopted is False
    assert Path(created.path).is_dir()


@pytest.mark.parametrize(
    ("owner", "generation"),
    [("bob@example.com", _GENERATION), (_OWNER, "gen-2")],
    ids=["other-owner", "other-registration"],
)
async def test_a_connection_taken_over_between_calls_is_refused_before_any_frame(
    git_repo: Path, tunnel: _Tunnel, owner: str, generation: str
) -> None:
    host = await _connect(tunnel)
    tunnel.connect(owner=owner, generation=generation)

    with pytest.raises(RunWorktreeError) as caught:
        await host.stat(str(git_repo))

    assert caught.value.code == "not_permitted"
    assert "bob" not in caught.value.message
    assert tunnel.frames == []


async def test_every_frame_is_sent_under_the_owner_scope(
    git_repo: Path, tunnel: _Tunnel, monkeypatch: pytest.MonkeyPatch
) -> None:
    scopes: list[AccountAuthority | None] = []
    send_text = tunnel.registry.send_text

    def _recording_send_text(conn: HostConnection, data: str) -> None:
        scopes.append(host_registry_module._expected_host_owner.get())
        send_text(conn, data)

    monkeypatch.setattr(tunnel.registry, "send_text", _recording_send_text)

    await _run_worktree(tunnel, str(git_repo))

    assert scopes == [AccountAuthority(_OWNER, _GENERATION, _WORKSPACE_ID)] * 3


@pytest.mark.parametrize(
    ("row", "user_id", "workspace_id"),
    [
        (None, _OWNER, _WORKSPACE_ID),
        (_host_row(user_id="bob@example.com"), _OWNER, _WORKSPACE_ID),
        (_host_row(generation="gen-2"), _OWNER, _WORKSPACE_ID),
        (_host_row(sandbox_provider="modal"), _OWNER, _WORKSPACE_ID),
        (_host_row(sandbox_provider="modal"), None, _WORKSPACE_ID),
        (_host_row(), _OWNER, 0),
    ],
    ids=[
        "unknown-host",
        "other-owner",
        "other-registration",
        "sandbox-host",
        "sandbox-host-no-auth",
        "other-workspace",
    ],
)
async def test_refuses_a_host_the_user_may_not_use_before_any_frame(
    tunnel: _Tunnel, row: Host | None, user_id: str | None, workspace_id: int
) -> None:
    tunnel.host_rows.rows.clear()
    if row is not None:
        tunnel.host_rows.rows[(_WORKSPACE_ID, _HOST_ID)] = row

    with pytest.raises(RunWorktreeError) as caught:
        await _connect(tunnel, user_id=user_id, workspace_id=workspace_id)

    assert caught.value.code == "not_permitted"
    assert "bob" not in caught.value.message
    assert tunnel.frames == []
