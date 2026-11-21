"""The restart executor: fence, head check, salvage, then a reset the salvage still holds.

The old session is a fake session server; the run worktree is a ``FakeWorkspaceOps``
behind ``HostWorkspaceOps``, answered as Coral's host handlers answer, so the reset's
precondition and the salvage records are the contract's. A crash is a
``SimulatedCrash`` right after an op; the repeat runs the same row again.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Any, cast

import pytest

from coral.bridge.mapping import RECOVERY_RESTART
from coral.db.enum_codecs import RunPauseReason, RunStatus, SlotRole, WorkspaceOpIntentOp
from coral.model.ids import effect_op_key
from coral.omni.protocols import CoralSessionError
from coral.queue.conformance import run_executor_conformance
from coral.queue.executors import EffectCompleted, EffectFailed, EffectOutcome, StartupLeaseLost
from coral.recovery.ladder import MAX_SALVAGE_ROUNDS, restart_executor
from coral.slots.executors import close_commit_op_key, close_commit_params
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun, RunStartSpec, Transition
from coral.workspace.fake import FakeWorkspaceOps
from coral.workspace.ops import (
    HostChannel,
    HostChannelBackend,
    OpName,
    WorkspaceOpError,
    WorkspaceRef,
    salvage_ref_name,
)
from coral.workspace.run_worktree import run_branch_name
from tests.coral.slots._close_fakes import FakeDispatch, FakeEdgeWatcher
from tests.coral.workspace._executor_fakes import (
    FakeBindings,
    FakeChannels,
    FakeIntents,
    RecordingScopeRunner,
    effect_context,
    started_run_id,
    step_binding,
)
from tests.stores.coral._faults import SimulatedCrash

WORKSPACE = 4
OWNER = "alice"
HOST = "h" * 32
REPO = "/Users/alice/repo"
WORKTREE = "/Users/alice/repo-worktrees/coral-r-base"
SESSION = "5" * 32
SLOT = "implement||:0"
START_KEY = "restart-1"
RUN_ID = started_run_id(user_id=OWNER, start_key=START_KEY)
KEY = f"{RUN_ID}:7:retry_step:{SLOT}"
REF = WorkspaceRef(host_id=HOST, root=WORKTREE, branch=run_branch_name(RUN_ID))
FILES: Mapping[str, bytes] = {"README.md": b"hello\n"}
# What the fence and the workspace ops do, in the order the fakes see them.
PHASES = frozenset({"interrupt", "set_closed", "stop", "head", "commit", "salvage", "reset"})


def _op_key(qualifier: str) -> str:
    return effect_op_key(WORKSPACE, KEY, qualifier)


def _salvage_ref(round_no: int) -> str:
    return salvage_ref_name(_op_key("salvage" if round_no == 1 else f"salvage-{round_no}"))


class _Host(HostChannelBackend):
    """
    The run worktree's host over a ``FakeWorkspaceOps``, answering as Coral's handlers do.

    :ivar before: Runs before an op, with its attempt number (counted from 1).
    :ivar after: Runs after an op that succeeded, with its attempt number.
    :ivar older: Answers as a host from before the reset's ``salvage_commit``.
    """

    def __init__(self, events: list[str]) -> None:
        self.ops = FakeWorkspaceOps()
        self.base = self.ops.add_workspace(REF, FILES)
        self.events = events
        self.before: dict[str, Callable[[int], None]] = {}
        self.after: dict[str, Callable[[int], None]] = {}
        self.older = False
        self.counts: Counter[str] = Counter()
        # Each salvage's ref and commit, as answered.
        self.salvaged: dict[str, str | None] = {}

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
        self.events.append(op)
        self.counts[op] += 1
        attempt = self.counts[op]
        hook = self.before.get(op)
        if hook is not None:
            hook(attempt)
        ref = WorkspaceRef(host_id=host_id, root=root, branch=str(params["branch"]))
        channel = HostChannel(host_id)
        payload: dict[str, object]
        if op == "head":
            head = await self.ops.head(ref, channel)
            payload = {
                "head": head.head,
                "branch": head.branch,
                "merge_in_progress": head.merge_in_progress,
            }
        elif op == "salvage":
            assert op_key is not None
            salvage = await self.ops.salvage(ref, channel, op_key=op_key)
            self.salvaged[salvage.ref] = salvage.commit
            payload = {"ref": salvage.ref, "commit": salvage.commit}
        elif op == "reset":
            assert op_key is not None
            if self.older and "salvage_commit" in params:
                # An older host's params are strict: the host answers invalid_params.
                raise ValueError("unknown params ['salvage_commit'] or missing params []")
            salvage_commit = params.get("salvage_commit")
            reset = await self.ops.reset(
                ref,
                channel,
                op_key=op_key,
                commit=str(params["commit"]),
                salvage_commit=None if salvage_commit is None else str(salvage_commit),
            )
            payload = {"head": reset.head}
        elif op == "commit":
            assert op_key is not None
            committed = await self.ops.commit(
                ref,
                channel,
                op_key=op_key,
                expected_head=str(params["expected_head"]),
                message=str(params["message"]),
                run_id=cast("str | None", params.get("run_id")),
                attempt_id=cast("str | None", params.get("attempt_id")),
            )
            payload = {"commit": committed.commit, "empty": committed.empty}
        else:
            raise AssertionError(f"the restart sent {op}")
        hook = self.after.get(op)
        if hook is not None:
            hook(attempt)
        return payload

    def write(self, path: str, content: bytes) -> None:
        self.ops.write_file(REF, path, content)

    async def head(self) -> str:
        return (await self.ops.head(REF, HostChannel(HOST))).head

    async def dirty(self) -> int:
        return (await self.ops.fingerprint(REF, HostChannel(HOST), level="L1")).dirty_count

    async def read(self, path: str, *, at_commit: str | None = None) -> bytes | None:
        try:
            found = await self.ops.read(REF, HostChannel(HOST), path=path, at_commit=at_commit)
        except WorkspaceOpError:
            return None
        return found.content

    def commit_on_head(self, files: Mapping[str, bytes]) -> str:
        """A new commit on HEAD with ``files`` written; HEAD stays where it is."""
        return self.ops.add_ref(REF, "refs/heads/coral/handoff", files)

    async def check_out(self, commit: str) -> None:
        await self.ops.reset(REF, HostChannel(HOST), op_key="k-setup", commit=commit)


class _Restart:
    """A run paused for a retry of its writer's slot, whose old session is ``SESSION``."""

    def __init__(
        self,
        *,
        slot_role: SlotRole = SlotRole.STEP_AGENT,
        bound: bool = True,
        base: bool = True,
        status: str = "running",
    ) -> None:
        """:param base: Record the worktree's first commit as the run's ``base_commit``."""
        self.events: list[str] = []
        self.host = _Host(self.events)
        self.run_store = FakeRunStore(default_workspace_id=WORKSPACE)
        self.run: CoralRun = self.run_store.start_run(
            RunStartSpec(
                workflow_id="two-steps",
                version_id="v1",
                title="Ship it",
                request_preview="",
                workspace_id=WORKSPACE,
                user_id=OWNER,
                host_id=HOST,
                repo_path=REPO,
                worktree_path=WORKTREE,
                run_branch=REF.branch,
                base_commit=self.host.base if base else None,
            ),
            start_key=START_KEY,
        )
        assert self.run.id == RUN_ID
        self.dispatch = FakeDispatch(self.events, owner=OWNER)
        self.session = self.dispatch.session(SESSION, status=status, response_id="resp_1")
        self.edges = FakeEdgeWatcher(self.events)
        binding = step_binding(
            workspace_id=WORKSPACE,
            run_id=RUN_ID,
            session_id=SESSION,
            slot_role=slot_role,
            host_id=HOST,
        )
        self.binding = binding
        self.bindings = FakeBindings([binding] if bound else [])
        self.intents = FakeIntents(self.events)
        self.scope = RecordingScopeRunner()
        # Every call the ladder makes into a dependency, in order, and one crash to make.
        self.calls: list[str] = []
        self.crash: tuple[int, str] | None = None
        self._instrument()
        self.executor = restart_executor(
            dispatch=self.dispatch,
            edges=self.edges,
            channels=FakeChannels(self.host, self.scope),
            bindings=self.bindings,
            intents=self.intents,
            run_store=self.run_store,
            scope_runner=self.scope,
        )
        self.lease_checks = 0

    def _due(self, label: str) -> str | None:
        """Count one call; the crash planned for it, once."""
        self.calls.append(label)
        if self.crash is not None and self.crash[0] == len(self.calls) - 1:
            when, self.crash = self.crash[1], None
            return when
        return None

    def _instrument(self) -> None:
        """Wrap every dependency the ladder calls so a crash can come before or after any call."""
        due = self._due

        def wrapped(owner: object, name: str, label: Callable[..., str]) -> None:
            original = getattr(owner, name)

            async def call(*args: Any, **kwargs: Any) -> Any:
                when = due(label(*args, **kwargs))
                if when == "before":
                    raise SimulatedCrash(f"before {name}")
                try:
                    result = original(*args, **kwargs)
                    if asyncio.iscoroutine(result):
                        result = await result
                except Exception:
                    if when == "after":
                        raise SimulatedCrash(f"after {name}") from None
                    raise
                if when == "after":
                    raise SimulatedCrash(f"after {name}")
                return result

            setattr(owner, name, call)

        for name in ("live_status", "interrupt", "set_closed", "stop"):
            wrapped(self.dispatch, name, lambda *_a, name=name, **_k: f"dispatch.{name}")
        wrapped(self.host, "request", lambda _host_id, op, **_k: f"host.{op}")

    def wrap_stores(self) -> None:
        """Make the record stores' calls crash points too; their sync calls run in threads."""
        due = self._due

        def wrapped(owner: object, name: str) -> None:
            original = getattr(owner, name)

            def call(*args: Any, **kwargs: Any) -> Any:
                when = due(f"{type(owner).__name__}.{name}")
                if when == "before":
                    raise SimulatedCrash(f"before {name}")
                result = original(*args, **kwargs)
                if when == "after":
                    raise SimulatedCrash(f"after {name}")
                return result

            setattr(owner, name, call)

        for name in ("get", "reserve"):
            wrapped(self.intents, name)
        wrapped(self.bindings, "get")

    def payload(self, **fields: object) -> dict[str, Any]:
        return {
            "effect_type": RECOVERY_RESTART,
            "effect_key": KEY,
            "engine_kind": "retry_step",
            "engine_slot_id": SLOT,
            "generation": 2,
            "session_id": SESSION,
            "writer": True,
            "expected_head": None,
            "slot_id": "s" * 32,
            **fields,
        }

    async def deliver(
        self, payload: dict[str, Any] | None = None, *, lease_lost_at: int | None = None
    ) -> EffectOutcome:
        checks = 0

        async def ensure_lease() -> bool:
            nonlocal checks
            checks += 1
            self.lease_checks += 1
            return checks != lease_lost_at

        ctx = effect_context(
            workspace_id=WORKSPACE,
            run_id=RUN_ID,
            payload=self.payload() if payload is None else payload,
            ensure_lease=ensure_lease,
        )
        return await self.executor(ctx)

    def phases(self) -> list[str]:
        return [event for event in self.events if event in PHASES]


def _completed(outcome: EffectOutcome) -> dict[str, Any]:
    assert isinstance(outcome, EffectCompleted), outcome
    assert outcome.result is not None
    return outcome.result


def _failed(outcome: EffectOutcome) -> EffectFailed:
    assert isinstance(outcome, EffectFailed), outcome
    return outcome


async def test_a_writers_restart_fences_checks_head_salvages_then_resets() -> None:
    env = _Restart()
    env.host.write("draft.txt", b"half done\n")

    result = _completed(await env.deliver())

    # The fence ends the running turn, closes and stops the session before any git.
    assert env.phases() == ["interrupt", "set_closed", "stop", "head", "salvage", "reset"]
    assert env.dispatch.interrupts == ["resp_1"]
    assert env.session.closed and not env.session.runner_alive
    salvaged = env.host.salvaged[_salvage_ref(1)]
    assert result == {
        "salvage_ref": _salvage_ref(1),
        "salvage_commit": salvaged,
        "head_verified": True,
        "head": env.host.base,
    }
    # The salvage holds the work; the worktree is back at its last handoff's commit.
    assert salvaged is not None
    assert await env.host.read("draft.txt", at_commit=salvaged) == b"half done\n"
    assert await env.host.head() == env.host.base
    assert await env.host.dirty() == 0
    assert await env.host.read("draft.txt") is None
    # Each git op ran inside the run's own scope.
    assert env.scope.entered and env.scope.entered[0]["run_id"] == RUN_ID


async def test_a_readers_restart_stops_after_the_fence() -> None:
    env = _Restart(slot_role=SlotRole.VERIFIER)
    env.host.write("notes.txt", b"the user's\n")

    result = _completed(await env.deliver(env.payload(writer=False)))

    assert env.phases() == ["interrupt", "set_closed", "stop"]
    assert result == {
        "salvage_ref": None,
        "salvage_commit": None,
        "head_verified": False,
        "head": None,
    }
    assert await env.host.read("notes.txt") == b"the user's\n"


async def test_a_clean_tree_is_salvaged_without_a_reset() -> None:
    env = _Restart(status="idle")

    result = _completed(await env.deliver())

    assert env.phases() == ["set_closed", "stop", "head", "salvage"]
    assert result == {
        "salvage_ref": None,
        "salvage_commit": None,
        "head_verified": True,
        "head": env.host.base,
    }


async def test_a_write_between_salvage_and_reset_is_salvaged_again_before_the_reset() -> None:
    env = _Restart()
    env.host.write("draft.txt", b"half done\n")
    # A process the stop missed writes once more after the first salvage.
    env.host.after["salvage"] = lambda count: (
        env.host.write("late.txt", b"late\n") if count == 1 else None
    )

    result = _completed(await env.deliver())

    assert env.phases()[3:] == ["head", "salvage", "reset", "salvage", "reset"]
    second = env.host.salvaged[_salvage_ref(2)]
    assert result == {
        "salvage_ref": _salvage_ref(2),
        "salvage_commit": second,
        "head_verified": True,
        "head": env.host.base,
    }
    assert second is not None
    assert await env.host.read("late.txt", at_commit=second) == b"late\n"
    assert await env.host.read("draft.txt", at_commit=second) == b"half done\n"
    assert await env.host.dirty() == 0


async def test_a_tree_that_keeps_changing_fails_the_restart_without_a_reset() -> None:
    env = _Restart()
    env.host.write("draft.txt", b"half done\n")
    env.host.after["salvage"] = lambda count: env.host.write(f"late-{count}.txt", b"late\n")

    failure = _failed(await env.deliver())

    assert (failure.error_code, failure.retryable) == ("workspace.tree_changed", False)
    assert env.phases()[3:] == ["head", *(["salvage", "reset"] * MAX_SALVAGE_ROUNDS)]
    # Nothing was reset: every write is still in the worktree, and each round kept a record.
    for count in range(1, MAX_SALVAGE_ROUNDS + 1):
        assert await env.host.read(f"late-{count}.txt") == b"late\n"
        assert env.host.salvaged[_salvage_ref(count)] is not None
    assert await env.host.read("draft.txt") == b"half done\n"


@pytest.mark.parametrize(
    ("named", "head_at", "moved"),
    [
        pytest.param(True, "base", True, id="behind-the-newest-written-commit"),
        pytest.param(False, "handoff", True, id="past-the-base-commit"),
        pytest.param(True, "handoff", False, id="at-the-newest-written-commit"),
        pytest.param(False, "base", False, id="at-the-base-commit"),
    ],
)
async def test_head_is_checked_against_the_newest_written_commit_else_the_base(
    named: bool, head_at: str, moved: bool
) -> None:
    env = _Restart()
    handoff = env.host.commit_on_head({"handoff.txt": b"handed off\n"})
    if head_at == "handoff":
        await env.host.check_out(handoff)
    env.host.write("draft.txt", b"half done\n")
    env.events.clear()

    outcome = await env.deliver(env.payload(expected_head=handoff if named else None))

    if moved:
        failure = _failed(outcome)
        assert (failure.error_code, failure.retryable) == ("workspace.head_moved", False)
        assert env.phases() == ["interrupt", "set_closed", "stop", "head"]
        assert await env.host.read("draft.txt") == b"half done\n"
    else:
        assert _completed(outcome)["head_verified"] is True
        assert await env.host.head() == (handoff if head_at == "handoff" else env.host.base)
        assert await env.host.dirty() == 0


async def test_a_run_without_an_expected_head_resets_to_head_unverified() -> None:
    env = _Restart(base=False)
    env.host.write("draft.txt", b"half done\n")

    result = _completed(await env.deliver())

    assert result["head_verified"] is False
    assert result["salvage_ref"] == _salvage_ref(1)
    assert await env.host.head() == env.host.base


async def test_an_unconfirmed_stop_fails_retryably_with_nothing_salvaged() -> None:
    env = _Restart()
    env.host.write("draft.txt", b"half done\n")
    env.dispatch.unconfirmed_stops = 1

    failure = _failed(await env.deliver())

    assert (failure.error_code, failure.retryable) == ("dispatch.stop_unconfirmed", True)
    assert env.phases() == ["interrupt", "set_closed", "stop"]
    assert env.host.counts == Counter()
    assert await env.host.read("draft.txt") == b"half done\n"


@pytest.mark.parametrize(
    ("session_id", "bound", "deleted"),
    [
        pytest.param(None, False, False, id="no-session"),
        pytest.param(SESSION, False, False, id="never-bound"),
        pytest.param(SESSION, True, True, id="deleted"),
    ],
)
async def test_a_slot_without_a_live_session_is_fenced_without_a_stop(
    session_id: str | None, bound: bool, deleted: bool
) -> None:
    env = _Restart(bound=bound)
    if deleted:
        env.dispatch.refusals["live_status"] = CoralSessionError("session.deleted", "gone")
    env.host.write("draft.txt", b"half done\n")

    result = _completed(await env.deliver(env.payload(session_id=session_id)))

    assert env.phases() == ["head", "salvage", "reset"]
    assert result["salvage_ref"] == _salvage_ref(1)


async def test_the_restart_runs_while_its_run_is_paused() -> None:
    env = _Restart()
    state, version = env.run_store.load_run_state(RUN_ID, workspace_id=WORKSPACE)
    env.run_store.apply_transition(
        RUN_ID,
        version,
        Transition(status=int(RunStatus.PAUSED), pause_reason=int(RunPauseReason.INFRA)),
        workspace_id=state.workspace_id,
    )
    env.host.write("draft.txt", b"half done\n")

    result = _completed(await env.deliver())

    assert result["salvage_ref"] == _salvage_ref(1)


async def test_an_older_host_refuses_the_precondition_and_resets_nothing() -> None:
    env = _Restart()
    env.host.older = True
    env.host.write("draft.txt", b"half done\n")

    failure = _failed(await env.deliver())

    assert (failure.error_code, failure.retryable) == ("workspace.invalid_params", False)
    assert await env.host.read("draft.txt") == b"half done\n"


async def test_a_host_offline_between_salvage_and_reset_fails_retryably_then_completes() -> None:
    env = _Restart()
    env.host.write("draft.txt", b"half done\n")

    def offline_once(attempt: int) -> None:
        if attempt == 1:
            raise WorkspaceOpError("workspace.backend_unavailable", f"host {HOST} is offline")

    env.host.before["reset"] = offline_once

    failure = _failed(await env.deliver())

    assert (failure.error_code, failure.retryable) == ("workspace.backend_unavailable", True)
    assert await env.host.read("draft.txt") == b"half done\n"
    # The host is back: the repeat finds round 1's record and resets under it.
    result = _completed(await env.deliver())
    assert result["salvage_ref"] == _salvage_ref(1)
    assert {ref for ref, commit in env.host.salvaged.items() if commit} == {_salvage_ref(1)}
    assert await env.host.dirty() == 0


async def test_a_lost_lease_stops_the_restart_before_its_next_side_effect() -> None:
    env = _Restart(status="idle")
    env.host.write("draft.txt", b"half done\n")
    # The fence checks before its label and its stop, the ladder before each git write.
    with pytest.raises(StartupLeaseLost):
        await env.deliver(lease_lost_at=3)

    assert env.phases() == ["set_closed", "stop", "head"]
    assert await env.host.read("draft.txt") == b"half done\n"


def _late_write(env: _Restart) -> None:
    """One write after the first salvage, so the restart takes two rounds."""
    write = {"done": False}

    def hook(attempt: int) -> None:
        if attempt == 1 and not write["done"]:
            write["done"] = True
            env.host.write("late.txt", b"late\n")

    env.host.after["salvage"] = hook


def _two_rounds(crash: tuple[int, str] | None = None) -> _Restart:
    env = _Restart()
    env.wrap_stores()
    env.host.write("draft.txt", b"half done\n")
    _late_write(env)
    env.crash = crash
    return env


async def test_a_repeat_after_a_crash_at_every_call_boundary_gives_the_uncrashed_result() -> None:
    reference = _two_rounds()
    expected = _completed(await reference.deliver())
    assert expected["salvage_ref"] == _salvage_ref(2)
    # The fence's calls, the head, two rounds and every record read or written.
    assert {label.split(".")[0] for label in reference.calls} == {
        "dispatch",
        "host",
        "FakeIntents",
        "FakeBindings",
    }

    for index, label in enumerate(reference.calls):
        for when in ("before", "after"):
            case = f"crash {when} call {index} ({label})"
            env = _two_rounds(crash=(index, when))
            with pytest.raises(SimulatedCrash):
                await env.deliver()

            assert _completed(await env.deliver()) == expected, case
            # One record per round, the worktree clean at the expected head, and the
            # named record holds all of the old attempt's work.
            salvaged = {ref for ref, commit in env.host.salvaged.items() if commit is not None}
            assert salvaged == {_salvage_ref(1), _salvage_ref(2)}, case
            named = expected["salvage_commit"]
            assert await env.host.read("draft.txt", at_commit=named) == b"half done\n", case
            assert await env.host.read("late.txt", at_commit=named) == b"late\n", case
            assert (await env.host.head(), await env.host.dirty()) == (env.host.base, 0), case
            assert env.session.closed, case


async def test_a_reset_cut_short_before_its_clean_is_finished_on_the_repeat() -> None:
    reference = _Restart()
    reference.host.write("README.md", b"edited\n")
    reference.host.write("draft.txt", b"half done\n")
    expected = _completed(await reference.deliver())

    env = _Restart()
    env.host.write("README.md", b"edited\n")
    env.host.write("draft.txt", b"half done\n")

    def cut_short(attempt: int) -> None:
        # ``reset --hard`` restored the tracked file; the untracked one was never cleaned.
        if attempt == 1:
            env.host.write("draft.txt", b"half done\n")
            raise SimulatedCrash("the host died before clean")

    env.host.after["reset"] = cut_short
    with pytest.raises(SimulatedCrash):
        await env.deliver()

    assert _completed(await env.deliver()) == expected
    named = expected["salvage_commit"]
    assert await env.host.read("README.md", at_commit=named) == b"edited\n"
    assert await env.host.read("draft.txt", at_commit=named) == b"half done\n"
    assert await env.host.dirty() == 0
    assert {ref for ref, commit in env.host.salvaged.items() if commit} == {_salvage_ref(1)}


async def test_nothing_is_salvaged_after_a_reset_and_a_repeat_names_the_same_record() -> None:
    env = _Restart()
    env.host.write("draft.txt", b"half done\n")
    # A person writes in the worktree right after the reset.
    env.host.after["reset"] = lambda _attempt: env.host.write("later.txt", b"a person's\n")

    first = _completed(await env.deliver())
    # A repeat of the finished restart (its completion was lost) changes nothing.
    again = _completed(await env.deliver())

    assert first == again
    assert first["salvage_ref"] == _salvage_ref(1)
    assert await env.host.read("draft.txt", at_commit=first["salvage_commit"]) == b"half done\n"
    assert env.host.counts["salvage"] == 1
    assert {ref for ref, commit in env.host.salvaged.items() if commit} == {_salvage_ref(1)}
    # The later write is left in the worktree for the next generation, never reset away.
    assert await env.host.read("later.txt") == b"a person's\n"


CLOSE_KEY = f"{RUN_ID}:5:close_slot:{SLOT}"


async def _own_close(env: _Restart, *, message: str | None = None, intent: bool = True) -> str:
    """The old session's close commits its work on the base, and its result is lost."""
    op_key = close_commit_op_key(WORKSPACE, CLOSE_KEY)
    default_message, attempt_id = close_commit_params(RUN_ID, env.binding)
    if intent:
        env.intents.reserve(
            WORKSPACE,
            op_key=op_key,
            run_id=RUN_ID,
            op=WorkspaceOpIntentOp.COMMIT,
            host_id=HOST,
            root=WORKTREE,
            expected_head=env.host.base,
        )
    env.host.write("work.txt", b"the step's work\n")
    committed = await env.host.ops.commit(
        REF,
        HostChannel(HOST),
        op_key=op_key,
        expected_head=env.host.base,
        message=message or default_message,
        run_id=RUN_ID,
        attempt_id=attempt_id,
    )
    env.events.clear()
    return committed.commit


@pytest.mark.parametrize("params", ["its-own", "other"])
async def test_a_head_at_the_steps_own_unreported_close_commit_is_kept(params: str) -> None:
    env = _Restart()
    committed = await _own_close(env, message=None if params == "its-own" else "Edited by hand")
    env.host.write("draft.txt", b"after the close\n")

    result = _completed(await env.deliver(env.payload(close_key=CLOSE_KEY)))

    # The close's commit stays on the branch; only what came after it is salvaged.
    assert (result["head"], result["head_verified"]) == (committed, True)
    assert await env.host.head() == committed
    assert await env.host.read("work.txt") == b"the step's work\n"
    assert await env.host.read("draft.txt", at_commit=result["salvage_commit"]) == (
        b"after the close\n"
    )
    assert await env.host.dirty() == 0
    # A repeat checks HEAD against the head the first try recorded.
    assert _completed(await env.deliver(env.payload(close_key=CLOSE_KEY))) == result


@pytest.mark.parametrize(
    ("case", "close_key"),
    [
        pytest.param("no-intent", CLOSE_KEY, id="no-op-intent"),
        pytest.param("other-head", CLOSE_KEY, id="intent-on-another-head"),
        pytest.param("own", None, id="no-unreported-close"),
        pytest.param("on-top", CLOSE_KEY, id="a-commit-on-top-of-the-close"),
        pytest.param("own", f"{'f' * 32}:5:close_slot:{SLOT}", id="another-runs-close"),
    ],
)
async def test_a_head_coral_did_not_commit_is_head_moved_and_never_advised_away(
    case: str, close_key: str | None
) -> None:
    env = _Restart()
    committed = await _own_close(env, intent=case not in ("no-intent", "other-head"))
    if case == "other-head":
        env.intents.reserve(
            WORKSPACE,
            op_key=close_commit_op_key(WORKSPACE, CLOSE_KEY),
            run_id=RUN_ID,
            op=WorkspaceOpIntentOp.COMMIT,
            host_id=HOST,
            root=WORKTREE,
            expected_head="e" * 40,
        )
    if case == "on-top":
        await env.host.check_out(env.host.commit_on_head({"by-hand.txt": b"a person's\n"}))
    head = await env.host.head()

    failure = _failed(await env.deliver(env.payload(close_key=close_key)))

    assert (failure.error_code, failure.retryable) == ("workspace.head_moved", False)
    assert "a commit Coral did not make" in failure.message
    assert "back at a commit Coral made" in failure.message
    assert "reset the branch" not in failure.message
    # Nothing moved the branch: the close's commit is still on it.
    assert await env.host.head() == head
    assert await env.host.read("work.txt", at_commit=committed) == b"the step's work\n"


async def test_restart_executor_conformance() -> None:
    env = _Restart()
    env.host.write("draft.txt", b"half done\n")
    outcomes: list[EffectOutcome] = []

    async def recording(ctx: Any) -> EffectOutcome:
        outcome = await env.executor(ctx)
        outcomes.append(outcome)
        return outcome

    await run_executor_conformance(
        recording,
        effect_type=RECOVERY_RESTART,
        payload=env.payload(),
        workspace_id=WORKSPACE,
        run_id=RUN_ID,
    )
    first, repeat = (_completed(outcome) for outcome in outcomes)
    assert (
        first
        == repeat
        == {
            "salvage_ref": _salvage_ref(1),
            "salvage_commit": env.host.salvaged[_salvage_ref(1)],
            "head_verified": True,
            "head": env.host.base,
        }
    )


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"writer": "yes"}, id="writer-not-a-flag"),
        pytest.param({"expected_head": "HEAD"}, id="expected-head-not-a-commit"),
        pytest.param({"session_id": "Not/A/Session"}, id="bad-session-id"),
        pytest.param({"generation": 0}, id="generation-out-of-range"),
    ],
)
async def test_invalid_payloads_are_refused_before_anything_runs(
    fields: dict[str, object],
) -> None:
    env = _Restart()

    failure = _failed(await env.deliver(env.payload(**fields)))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert env.events == []


async def test_a_payload_without_its_session_key_is_refused() -> None:
    env = _Restart()
    payload = env.payload()
    del payload["session_id"]

    failure = _failed(await env.deliver(payload))

    assert failure.error_code == "effect.invalid_payload"
    assert "session_id" in failure.message
    assert env.events == []
