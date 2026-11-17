"""Engine git in the run worktree, through the user's host, without an HTTP request.

The workspace executors build ``HostWorkspaceOps`` over Coral's server adapter
(``coral.omni.server.workspace_ops``). The adapter authorizes the run owner
from the stored host row and sends each op through Omnigent's request helper
and a real ``HostRegistry``. A drain task stands in for the tunnel: it hands
each frame to a real ``HostProcess``'s frame dispatch, whose guarded branch
runs Coral's host handlers on real git in ``tmp_path``, and relays the result
frame through the wire codec as ``host_tunnel.py`` does. WRITE ops refuse
without a git jail, so every commit and reset here ran jailed (and, on macOS,
in the worktree moved aside).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import omnigent.server.routes._host_workspace_ops as host_workspace_ops_route
from coral.db.enum_codecs import SlotRole
from coral.model.ids import effect_op_key
from coral.omni.host.ops import workspace_op_handlers
from coral.omni.process_map import DISABLE_HOST_ENTRY_POINTS_ENV
from coral.omni.protocols import HostAccessRefused
from coral.omni.server.scopes import OmnigentRunScopeRunner
from coral.omni.server.workspace_ops import OmnigentHostWorkspaceChannels
from coral.queue.conformance import run_executor_conformance
from coral.queue.executors import (
    EffectCompleted,
    EffectExecutor,
    EffectFailed,
    EffectOutcome,
    ExecutionContext,
)
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun
from coral.workspace.executors import commit_executor, reset_executor, salvage_executor
from coral.workspace.host_backend import HostWorkspaceOps
from coral.workspace.ops import (
    HostChannel,
    WorkspaceOpError,
    WorkspaceRef,
    commit_params_digest,
)
from coral.workspace.run_worktree import run_branch_name
from omnigent.db.account_authority import AccountAuthority, account_authority_scope
from omnigent.host import workspace_ops as host_workspace_ops
from omnigent.host.connect import HostProcess
from omnigent.host.frames import HOST_CAPABILITIES, decode_host_frame
from omnigent.host.identity import HostIdentity
from omnigent.host.workspace_ops import (
    CAP_WORKSPACE_OPS,
    HostWorkspaceOpFrame,
    HostWorkspaceOpResultFrame,
    WorkspaceOpHandler,
    WorkspaceOpRequest,
)
from omnigent.server import host_registry as host_registry_module
from omnigent.server.host_registry import HostConnection, HostRegistry
from tests.coral.omni.host.ops._worktrees import (
    INITIAL_FILES,
    LinkedWorktree,
    isolate_git_home,
    make_linked_worktree,
    run_git,
)
from tests.coral.omni.test_run_worktree_host import (
    _GENERATION,
    _HOST_ID,
    _OWNER,
    _WORKSPACE_ID,
    _host_row,
    _HostRows,
)
from tests.coral.workspace._executor_fakes import (
    FakeBindings,
    FakeIntents,
    add_slot,
    effect_context,
    start_run,
    started_run_id,
    step_binding,
)
from tests.host.test_orphan_reaper import _CollectingTunnel
from tests.server.routes.test_host_worktree import _FakeWebSocket, _hello_frame

# The run's id is fixed, so its worktree can be laid out on the run's own branch first.
_RUN_START_KEY = "ac3-run"
_RUN_BRANCH = run_branch_name(started_run_id(user_id=_OWNER, start_key=_RUN_START_KEY))
_SESSION = "5" * 32
_ATTEMPT = "6" * 32
_MESSAGE = "Review: done\n\nEvery finding is addressed."
# A committed ignore rule, so an ignored file outlives both the commit and the reset.
_FILES: Mapping[str, bytes] = {**INITIAL_FILES, ".gitignore": b"build/\n"}


@dataclass
class _HostTunnel:
    """The server's side of one host's connections, answered by a real ``HostProcess``."""

    registry: HostRegistry
    host: HostProcess
    handlers: Mapping[str, WorkspaceOpHandler]
    host_rows: _HostRows = field(default_factory=_HostRows)
    frames: list[HostWorkspaceOpFrame] = field(default_factory=list)
    # The next this-many ops run on the host, but the tunnel drops before their results arrive.
    lose_results: int = 0
    # The host stays connected but never answers.
    unanswered: bool = False
    answering: list[asyncio.Task[None]] = field(default_factory=list)

    def connect(
        self,
        *,
        owner: str | None = _OWNER,
        generation: str | None = _GENERATION,
        capabilities: Sequence[str] = HOST_CAPABILITIES,
    ) -> None:
        """Register a connection, replacing any earlier one, and answer its frames."""
        with account_authority_scope(owner, generation):
            conn = self.registry.register(
                host_id=_HOST_ID,
                ws=_FakeWebSocket(),  # type: ignore[arg-type]
                hello=_hello_frame(list(capabilities)),
                owner=owner,
                workspace_id=_WORKSPACE_ID,
            )
        self.answering.append(asyncio.create_task(self._answer(conn)))

    def disconnect(self) -> None:
        self.registry.deregister(_HOST_ID, workspace_id=_WORKSPACE_ID)

    def ops(self) -> list[str]:
        return [frame.op for frame in self.frames]

    async def _answer(self, conn: HostConnection) -> None:
        while (outbound := await conn.outbound_queue.get()) is not None:
            frame = decode_host_frame(outbound.data)
            assert isinstance(frame, HostWorkspaceOpFrame), frame
            self.frames.append(frame)
            if not self.unanswered:
                await self._reply(conn, frame)

    async def _reply(self, conn: HostConnection, frame: HostWorkspaceOpFrame) -> None:
        sent = _CollectingTunnel()
        await self.host._dispatch_host_frame(sent, frame)  # type: ignore[arg-type]
        (data,) = sent.sent
        result = decode_host_frame(data)
        assert isinstance(result, HostWorkspaceOpResultFrame)
        if self.lose_results > 0:
            self.lose_results -= 1
            self.disconnect()
            return
        future = conn.pending_workspace_ops.pop(result.request_id, None)
        if future is not None and not future.done():
            # The fields host_tunnel.py relays for a workspace op result.
            future.set_result(
                {
                    "status": result.status,
                    "payload": result.payload,
                    "error_code": result.error_code,
                    "error": result.error,
                    "exit_code": result.exit_code,
                    "permanent": result.permanent,
                }
            )


@pytest.fixture
def worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LinkedWorktree:
    isolate_git_home(monkeypatch, tmp_path / "home")
    return make_linked_worktree(tmp_path / "work", files=_FILES, branch=_RUN_BRANCH)


@pytest.fixture
async def tunnel(
    worktree: LinkedWorktree, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[_HostTunnel]:
    host = HostProcess(
        identity=HostIdentity(host_id=_HOST_ID, name="laptop"),
        server_url="http://localhost:8000",
    )
    state = _HostTunnel(registry=HostRegistry(), host=host, handlers=workspace_op_handlers())
    # Installed entry-point metadata may be stale, so the host gets Coral's handlers directly.
    monkeypatch.setattr(
        host_workspace_ops, "default_workspace_op_handlers", lambda: state.handlers
    )
    state.host_rows.rows[(_WORKSPACE_ID, _HOST_ID)] = _host_row()
    state.connect()
    try:
        yield state
    finally:
        state.disconnect()
        await asyncio.wait_for(asyncio.gather(*state.answering), timeout=30.0)


@dataclass
class _Engine:
    """A run on the worktree, and the three executors over Coral's server adapter."""

    worktree: LinkedWorktree
    tunnel: _HostTunnel
    run_store: FakeRunStore = field(
        default_factory=lambda: FakeRunStore(default_workspace_id=_WORKSPACE_ID)
    )

    def __post_init__(self) -> None:
        self.run: CoralRun = start_run(
            self.run_store,
            workspace_id=_WORKSPACE_ID,
            user_id=_OWNER,
            account_generation=_GENERATION,
            host_id=_HOST_ID,
            repo_path=str(self.worktree.repo_root),
            worktree_path=str(self.worktree.root),
            run_branch=self.worktree.branch,
            start_key=_RUN_START_KEY,
        )
        add_slot(self.run_store, self.run, session_id=_SESSION)
        self.channels = OmnigentHostWorkspaceChannels(
            host_registry=self.tunnel.registry,
            host_store=self.tunnel.host_rows,  # type: ignore[arg-type]
        )
        self.intents = FakeIntents([])
        bindings = FakeBindings(
            [
                step_binding(
                    workspace_id=_WORKSPACE_ID,
                    run_id=self.run.id,
                    session_id=_SESSION,
                    slot_role=SlotRole.STEP_AGENT,
                    host_id=_HOST_ID,
                )
            ]
        )
        scope_runner = OmnigentRunScopeRunner()

        async def _stopped(*, workspace_id: int, run_id: str, session_id: str) -> bool:
            return True

        self.executors: dict[str, EffectExecutor] = {
            "commit": commit_executor(
                self.channels,
                self.intents,
                bindings,
                self.run_store,
                scope_runner,
                turn_ended=_stopped,
            ),
            "salvage": salvage_executor(self.channels, self.run_store, scope_runner),
            "reset": reset_executor(self.channels, self.run_store, scope_runner),
        }

    def payload(self, kind: str, **fields: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "effect_type": f"workspace.{kind}",
            "effect_key": f"{self.run.id}:4:{kind}:slot-1",
            **fields,
        }
        if kind == "commit":
            payload.setdefault("session_id", _SESSION)
            payload.setdefault("message", _MESSAGE)
            payload.setdefault("attempt_id", _ATTEMPT)
        return payload

    async def run_effect(self, kind: str, **fields: object) -> EffectOutcome:
        ctx = effect_context(
            workspace_id=_WORKSPACE_ID, run_id=self.run.id, payload=self.payload(kind, **fields)
        )
        return await self.executors[kind](ctx)

    def ref(self) -> WorkspaceRef:
        return WorkspaceRef(
            host_id=_HOST_ID, root=str(self.worktree.root), branch=self.worktree.branch
        )


@pytest.fixture
def engine(worktree: LinkedWorktree, tunnel: _HostTunnel) -> _Engine:
    return _Engine(worktree, tunnel)


def _completed(outcome: EffectOutcome) -> dict[str, Any]:
    assert isinstance(outcome, EffectCompleted), outcome
    assert outcome.result is not None
    return outcome.result


def _failed(outcome: EffectOutcome) -> EffectFailed:
    assert isinstance(outcome, EffectFailed), outcome
    return outcome


def _git(worktree: LinkedWorktree, *args: str) -> str:
    return run_git(worktree.root, *args).strip()


def _edit_tracked_and_untracked(worktree: LinkedWorktree) -> None:
    worktree.write("README.md", b"edited by the step\n")
    (worktree.root / "src" / "app.py").unlink()
    worktree.write("notes/new.txt", b"a new file\n")
    # Neither an ignored file nor Coral's runtime dir is ever recorded.
    worktree.write("build/out.bin", b"\x00ignored")
    worktree.write(".coral/runtime/state.json", b"{}\n")


async def test_commit_then_reset_in_the_run_worktree_through_the_host_channel(
    engine: _Engine, worktree: LinkedWorktree, tunnel: _HostTunnel
) -> None:
    base = worktree.base
    _edit_tracked_and_untracked(worktree)

    committed = _completed(await engine.run_effect("commit", node_id="review"))

    commit = committed["commit"]
    op_key = effect_op_key(_WORKSPACE_ID, engine.payload("commit")["effect_key"])  # type: ignore[arg-type]
    assert committed == {
        "commit": commit,
        "empty": False,
        "subject": "Review: done",
        "diff_stat": {
            "files_changed": 3,
            "insertions": 2,
            "deletions": 2,
            "paths": ["README.md", "notes/new.txt", "src/app.py"],
            "paths_truncated": False,
        },
        "node_id": "review",
        "item_path": None,
    }
    assert tunnel.ops() == ["head", "commit", "diff_stat"]
    assert engine.intents.rows[(_WORKSPACE_ID, op_key)].expected_head == base
    # The branch moved from the recorded HEAD, with the tracked edit, the delete and the new file.
    assert _git(worktree, "rev-parse", f"refs/heads/{worktree.branch}") == commit
    assert _git(worktree, "rev-parse", f"{commit}^@") == base
    assert run_git(worktree.root, "show", f"{commit}:README.md") == "edited by the step\n"
    assert _git(worktree, "ls-tree", "-r", "--name-only", commit).split() == [
        ".gitignore",
        "README.md",
        "notes/new.txt",
    ]
    trailers = _git(worktree, "log", "-1", "--format=%(trailers:only,unfold)", commit)
    assert trailers.splitlines() == [
        f"Coral-Run: {engine.run.id}",
        f"Coral-Attempt: {_ATTEMPT}",
        f"Coral-Op: {op_key}",
        "Coral-Op-Params: "
        + commit_params_digest(_MESSAGE, {}, run_id=engine.run.id, attempt_id=_ATTEMPT),
        "Coral-Hooks: skipped",
    ]
    # The real index followed the branch; only Coral's runtime dir is left untracked.
    assert _git(worktree, "status", "--porcelain") == "?? .coral/"

    worktree.write("scratch.txt", b"an untracked file after the commit\n")
    reset = _completed(await engine.run_effect("reset", commit=base))

    assert reset == {"head": base}
    assert tunnel.ops()[3:] == ["reset"]
    assert _git(worktree, "rev-parse", "HEAD") == base
    assert _git(worktree, "rev-parse", f"refs/heads/{worktree.branch}") == base
    assert (worktree.root / "README.md").read_bytes() == INITIAL_FILES["README.md"]
    assert (worktree.root / "src" / "app.py").read_bytes() == INITIAL_FILES["src/app.py"]
    assert not (worktree.root / "notes").exists()
    assert not (worktree.root / "scratch.txt").exists()
    assert (worktree.root / "build" / "out.bin").read_bytes() == b"\x00ignored"
    assert (worktree.root / ".coral" / "runtime" / "state.json").read_bytes() == b"{}\n"
    assert _git(worktree, "status", "--porcelain") == "?? .coral/"
    # Every write op put the worktree back where it was.
    assert not Path(f"{worktree.root}.coral-op").exists()


async def test_the_three_executors_pass_executor_conformance_on_real_git(
    engine: _Engine, worktree: LinkedWorktree
) -> None:
    _edit_tracked_and_untracked(worktree)

    for kind, fields in (("commit", {}), ("salvage", {}), ("reset", {"commit": worktree.base})):
        if kind == "salvage":
            worktree.write("README.md", b"edited again before the salvage\n")
        recorded: list[EffectOutcome] = []

        async def _recording(
            ctx: ExecutionContext,
            executor: EffectExecutor = engine.executors[kind],
            recorded: list[EffectOutcome] = recorded,
        ) -> EffectOutcome:
            outcome = await executor(ctx)
            recorded.append(outcome)
            return outcome

        await run_executor_conformance(
            _recording,
            effect_type=f"workspace.{kind}",
            payload=engine.payload(kind, **fields),
            workspace_id=_WORKSPACE_ID,
            run_id=engine.run.id,
        )
        # Conformance accepts two equal failures too; each op must have done its work.
        first, repeat = (_completed(outcome) for outcome in recorded)
        assert first == repeat
        if kind == "commit":
            assert (first["empty"], first["commit"]) == (
                False,
                _git(worktree, "rev-parse", "HEAD"),
            )

    salvage_ref = "refs/coral/salvage/" + effect_op_key(
        _WORKSPACE_ID,
        engine.payload("salvage")["effect_key"],  # type: ignore[arg-type]
    )
    salvaged = _git(worktree, "rev-parse", salvage_ref)
    assert run_git(worktree.root, "show", f"{salvaged}:README.md") == (
        "edited again before the salvage\n"
    )
    assert _git(worktree, "rev-parse", "HEAD") == worktree.base


async def test_a_commit_whose_reply_was_lost_is_retried_to_the_same_commit(
    engine: _Engine, worktree: LinkedWorktree, tunnel: _HostTunnel
) -> None:
    base = worktree.base
    worktree.write("README.md", b"edited by the step\n")
    # The host commits, then its connection drops before the result reaches the server.
    tunnel.lose_results = 1

    lost = _failed(await engine.run_effect("commit", expected_head=base))

    assert (lost.error_code, lost.retryable) == ("workspace.backend_unavailable", True)
    landed = _git(worktree, "rev-parse", f"refs/heads/{worktree.branch}")
    assert landed != base
    # As if the host had died after moving the branch, before it synced the index.
    run_git(worktree.root, "read-tree", base)
    tunnel.connect()

    retried = _completed(await engine.run_effect("commit", expected_head=base))

    assert (retried["commit"], retried["empty"]) == (landed, False)
    assert tunnel.ops() == ["commit", "commit", "diff_stat"]
    assert _git(worktree, "rev-list", "--count", f"{base}..HEAD") == "1"
    assert _git(worktree, "status", "--porcelain") == ""


async def test_a_retry_after_someone_else_moved_the_branch_is_a_permanent_mismatch(
    engine: _Engine, worktree: LinkedWorktree, tunnel: _HostTunnel
) -> None:
    base = worktree.base
    worktree.write("README.md", b"edited by the step\n")
    # The first try records the start HEAD, then finds the host gone.
    tunnel.disconnect()
    offline = _failed(await engine.run_effect("commit", expected_head=base))
    assert (offline.error_code, offline.retryable) == ("workspace.backend_unavailable", True)
    # Someone else commits on the run branch before the retry.
    run_git(worktree.root, "commit", "-q", "--allow-empty", "--no-verify", "-m", "by hand")
    moved = _git(worktree, "rev-parse", "HEAD")
    tunnel.connect()

    # The retry still targets the recorded HEAD, so it never commits on top of the stranger's.
    failure = _failed(await engine.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == ("workspace.target_mismatch", False)
    assert tunnel.ops() == ["commit"]
    assert _git(worktree, "rev-parse", f"refs/heads/{worktree.branch}") == moved
    assert (worktree.root / "README.md").read_bytes() == b"edited by the step\n"


async def test_a_commit_with_only_ignored_and_runtime_files_is_empty_on_the_start_head(
    engine: _Engine, worktree: LinkedWorktree, tunnel: _HostTunnel
) -> None:
    worktree.write("build/out.bin", b"\x00ignored")
    worktree.write(".coral/runtime/state.json", b"{}\n")

    first = _completed(await engine.run_effect("commit"))
    repeat = _completed(await engine.run_effect("commit"))

    assert first == repeat
    assert first["commit"] == worktree.base
    assert first["empty"] is True
    assert first["diff_stat"] == {
        "files_changed": 0,
        "insertions": 0,
        "deletions": 0,
        "paths": [],
        "paths_truncated": False,
    }
    assert _git(worktree, "rev-parse", f"refs/heads/{worktree.branch}") == worktree.base


async def _reset_for_a_run_without_an_owner(
    engine: _Engine, worktree: LinkedWorktree
) -> EffectOutcome:
    """Reset the worktree for a run started with auth off; the host row still names an owner."""
    run = start_run(
        engine.run_store,
        workspace_id=_WORKSPACE_ID,
        user_id=None,
        account_generation=None,
        host_id=_HOST_ID,
        repo_path=str(worktree.repo_root),
        worktree_path=str(worktree.root),
    )
    # Each run works on its own branch, so the worktree takes this run's.
    run_git(worktree.root, "branch", "-m", run_branch_name(run.id))
    ctx = effect_context(
        workspace_id=_WORKSPACE_ID,
        run_id=run.id,
        payload={
            "effect_type": "workspace.reset",
            "effect_key": f"{run.id}:1:reset:slot-1",
            "commit": worktree.base,
        },
    )
    return await engine.executors["reset"](ctx)


async def test_a_run_without_an_owner_never_reaches_an_owned_connection(
    engine: _Engine, worktree: LinkedWorktree, tunnel: _HostTunnel
) -> None:
    failure = _failed(await _reset_for_a_run_without_an_owner(engine, worktree))

    assert (failure.error_code, failure.retryable) == ("workspace.host_not_permitted", False)
    assert _OWNER not in failure.message
    assert tunnel.frames == []


async def test_a_run_without_an_owner_reaches_an_ownerless_connection(
    engine: _Engine, worktree: LinkedWorktree, tunnel: _HostTunnel
) -> None:
    tunnel.connect(owner=None, generation=None)

    reset = _completed(await _reset_for_a_run_without_an_owner(engine, worktree))

    assert reset == {"head": worktree.base}
    assert tunnel.ops() == ["reset"]


async def test_every_op_is_sent_under_the_run_owners_host_scope(
    engine: _Engine, worktree: LinkedWorktree, tunnel: _HostTunnel, monkeypatch: pytest.MonkeyPatch
) -> None:
    scopes: list[AccountAuthority | None] = []
    send_text = tunnel.registry.send_text

    def _recording_send_text(conn: HostConnection, data: str) -> None:
        scopes.append(host_registry_module._expected_host_owner.get())
        send_text(conn, data)

    monkeypatch.setattr(tunnel.registry, "send_text", _recording_send_text)
    worktree.write("README.md", b"edited by the step\n")

    _completed(await engine.run_effect("commit"))

    assert scopes == [AccountAuthority(_OWNER, _GENERATION, _WORKSPACE_ID)] * 3


@pytest.mark.parametrize(
    "row",
    [
        None,
        _host_row(user_id="bob@example.com"),
        _host_row(generation="gen-2"),
        _host_row(sandbox_provider="modal"),
    ],
    ids=["unknown-host", "other-owner", "other-registration", "sandbox-host"],
)
async def test_a_host_the_run_owner_may_not_use_is_refused_before_any_frame(
    engine: _Engine, tunnel: _HostTunnel, row: object
) -> None:
    tunnel.host_rows.rows.clear()
    if row is not None:
        tunnel.host_rows.rows[(_WORKSPACE_ID, _HOST_ID)] = row  # type: ignore[assignment]

    for kind, fields in (("commit", {}), ("salvage", {}), ("reset", {"commit": "1" * 40})):
        failure = _failed(await engine.run_effect(kind, **fields))
        assert (failure.error_code, failure.retryable) == ("workspace.host_not_permitted", False)
        assert "bob" not in failure.message

    assert tunnel.frames == []


@pytest.mark.parametrize(
    ("owner", "generation"),
    [("bob@example.com", _GENERATION), (_OWNER, "gen-2")],
    ids=["other-owner", "other-registration"],
)
async def test_a_connection_taken_over_after_authorization_is_sent_nothing(
    engine: _Engine, tunnel: _HostTunnel, owner: str, generation: str
) -> None:
    channel = await engine.channels.channel(
        workspace_id=_WORKSPACE_ID,
        user_id=_OWNER,
        account_generation=_GENERATION,
        host_id=_HOST_ID,
    )
    tunnel.connect(owner=owner, generation=generation)
    workspace = HostWorkspaceOps(channel, repo_root=str(engine.worktree.repo_root))

    with pytest.raises(HostAccessRefused) as caught:
        await workspace.head(engine.ref(), HostChannel(_HOST_ID))

    assert caught.value.code == "not_permitted"
    assert "bob" not in caught.value.message
    assert tunnel.frames == []


async def test_a_channel_serves_only_the_host_it_authorized(
    engine: _Engine, tunnel: _HostTunnel
) -> None:
    channel = await engine.channels.channel(
        workspace_id=_WORKSPACE_ID,
        user_id=_OWNER,
        account_generation=_GENERATION,
        host_id=_HOST_ID,
    )

    with pytest.raises(HostAccessRefused) as caught:
        await channel.request(
            "host_other",
            "head",
            root=str(engine.worktree.root),
            params={"repo_root": str(engine.worktree.repo_root), "branch": engine.worktree.branch},
            timeout_s=30.0,
            op_key=None,
        )

    assert caught.value.code == "not_permitted"
    assert tunnel.frames == []


async def test_a_host_without_the_channel_token_is_never_sent_an_op(
    engine: _Engine, tunnel: _HostTunnel
) -> None:
    tunnel.connect(capabilities=tuple(c for c in HOST_CAPABILITIES if c != CAP_WORKSPACE_OPS))

    for kind, fields in (("commit", {}), ("salvage", {}), ("reset", {"commit": "1" * 40})):
        failure = _failed(await engine.run_effect(kind, **fields))

        assert (failure.error_code, failure.retryable) == (
            "workspace.capability_unavailable",
            False,
        )
        assert _HOST_ID in failure.message
        assert DISABLE_HOST_ENTRY_POINTS_ENV in failure.message
        assert "omnigent" not in failure.message.lower()
    assert tunnel.frames == []


async def test_a_host_with_coral_handlers_switched_off_is_capability_unavailable(
    engine: _Engine, tunnel: _HostTunnel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(DISABLE_HOST_ENTRY_POINTS_ENV, "1")
    tunnel.handlers = workspace_op_handlers()
    assert tunnel.handlers == {}

    failure = _failed(await engine.run_effect("reset", commit=engine.worktree.base))

    assert (failure.error_code, failure.retryable) == ("workspace.capability_unavailable", False)
    assert tunnel.ops() == ["reset"]


async def test_a_host_with_no_live_connection_is_retried_later(
    engine: _Engine, tunnel: _HostTunnel
) -> None:
    tunnel.disconnect()

    failure = _failed(await engine.run_effect("salvage"))

    assert (failure.error_code, failure.retryable) == ("workspace.backend_unavailable", True)
    assert tunnel.frames == []


async def test_a_host_that_never_answers_times_out_retryably(
    engine: _Engine, tunnel: _HostTunnel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host_workspace_ops_route, "WORKSPACE_OP_REPLY_GRACE_S", 0.05)
    tunnel.unanswered = True
    channel = await engine.channels.channel(
        workspace_id=_WORKSPACE_ID,
        user_id=_OWNER,
        account_generation=_GENERATION,
        host_id=_HOST_ID,
    )
    workspace = HostWorkspaceOps(
        channel, repo_root=str(engine.worktree.repo_root), read_timeout_s=0.05
    )

    with pytest.raises(WorkspaceOpError) as caught:
        await workspace.head(engine.ref(), HostChannel(_HOST_ID))

    assert (caught.value.code, caught.value.permanent) == ("workspace.timeout", False)
    assert tunnel.ops() == ["head"]


async def test_a_repository_declaring_a_filter_fails_permanently_after_one_attempt(
    engine: _Engine, worktree: LinkedWorktree, tunnel: _HostTunnel
) -> None:
    worktree.write(".gitattributes", b"*.bin filter=lfs\n")
    worktree.write("README.md", b"edited by the step\n")

    failure = _failed(await engine.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == ("workspace.backend_unavailable", False)
    assert "filter" in failure.message
    assert tunnel.ops() == ["head"]
    assert _git(worktree, "rev-parse", "HEAD") == worktree.base


async def test_a_malformed_host_payload_is_refused_permanently(
    engine: _Engine, tunnel: _HostTunnel
) -> None:
    def _symbolic_head(request: WorkspaceOpRequest) -> Mapping[str, object]:
        return {"head": "HEAD", "branch": None, "merge_in_progress": False}

    tunnel.handlers = {**tunnel.handlers, "head": _symbolic_head}

    failure = _failed(await engine.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == ("workspace.backend_unavailable", False)
    assert "'head'" in failure.message
    assert tunnel.ops() == ["head"]


async def test_params_the_host_refuses_are_a_caller_error(
    engine: _Engine, tunnel: _HostTunnel
) -> None:
    channel = await engine.channels.channel(
        workspace_id=_WORKSPACE_ID,
        user_id=_OWNER,
        account_generation=_GENERATION,
        host_id=_HOST_ID,
    )

    with pytest.raises(ValueError, match="unknown params"):
        await channel.request(
            _HOST_ID,
            "head",
            root=str(engine.worktree.root),
            params={
                "repo_root": str(engine.worktree.repo_root),
                "branch": engine.worktree.branch,
                "surprise": 1,
            },
            timeout_s=30.0,
            op_key=None,
        )

    assert tunnel.ops() == ["head"]


async def test_a_commit_whose_echoed_ids_cannot_fit_its_result_never_reaches_the_host(
    engine: _Engine, worktree: LinkedWorktree, tunnel: _HostTunnel
) -> None:
    worktree.write("README.md", b"edited by the step\n")

    failure = _failed(await engine.run_effect("commit", item_path="\U0001f4c1" * 600))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert tunnel.frames == []
    assert _git(worktree, "rev-parse", f"refs/heads/{worktree.branch}") == worktree.base
