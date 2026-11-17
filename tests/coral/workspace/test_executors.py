"""The ``workspace.commit``, ``.salvage`` and ``.reset`` executors over protocol fakes.

The real host path (adapter, tunnel, host dispatch and git) is covered in
``tests/coral/omni/test_host_workspace_ops.py``; here the host channel answers
canned payloads, so each rule is checked without git.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any

import pytest

from coral.db.enum_codecs import SlotRole, WorkspaceOpIntentOp
from coral.model.ids import effect_op_key
from coral.omni.protocols import CoralSessionError, HostAccessRefused
from coral.queue.executors import (
    EffectCompleted,
    EffectExecutor,
    EffectFailed,
    EffectOutcome,
    StartupLeaseLost,
)
from coral.slots.results import RESULT_BYTE_BUDGET, stored_result_bytes
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun
from coral.stores.session_bindings import SessionBinding
from coral.stores.workspace_op_intents import WorkspaceOpIntent
from coral.workspace.executors import (
    TURN_STATE_UNKNOWN,
    commit_executor,
    reset_executor,
    salvage_executor,
)
from coral.workspace.ops import WorkspaceOpError
from coral.workspace.run_worktree import run_branch_name
from tests.coral.workspace._executor_fakes import (
    Events,
    FakeBindings,
    FakeChannels,
    FakeHostChannel,
    FakeIntents,
    RecordingScopeRunner,
    Reply,
    add_slot,
    effect_context,
    start_run,
    step_binding,
)

WORKSPACE = 7
OWNER = "alice@example.com"
GENERATION = "gen-1"
HOST = "host-1"
REPO = "/Users/alice/repo"
ROOT = "/Users/alice/repo-worktrees/coral-r-test-base"
SESSION = "5" * 32
ATTEMPT = "6" * 32
BASE = "1" * 40
NEW = "2" * 40
SALVAGED = "3" * 40
MESSAGE = "Review: done\n\nEvery finding is addressed."
DIFF = {
    "files_changed": 2,
    "insertions": 3,
    "deletions": 1,
    "paths": ["README.md", "src/app.py"],
}


def _replies() -> dict[str, Reply]:
    return {
        "head": {"head": BASE, "branch": None, "merge_in_progress": False},
        "commit": {"commit": NEW, "empty": False},
        "diff_stat": dict(DIFF),
        "salvage": lambda request: {
            "ref": f"refs/coral/salvage/{request.op_key}",
            "commit": SALVAGED,
        },
        "reset": {"head": BASE},
    }


@dataclass
class _Harness:
    """A started run, its stores and a host channel, and the three executors over them."""

    events: Events = field(default_factory=list)
    run_store: FakeRunStore = field(
        default_factory=lambda: FakeRunStore(default_workspace_id=WORKSPACE)
    )
    scope: RecordingScopeRunner = field(default_factory=RecordingScopeRunner)
    turn_end: bool = True

    def __post_init__(self) -> None:
        self.run = self.start()
        add_slot(self.run_store, self.run, session_id=SESSION)
        self.bindings = FakeBindings([self.binding(SlotRole.STEP_AGENT)])
        self.intents = FakeIntents(self.events)
        self.channel = FakeHostChannel(self.events, _replies())
        self.channels = FakeChannels(self.channel, self.scope)
        self.turn_checks: list[dict[str, object]] = []

    def start(self, **spec: str | None) -> CoralRun:
        fields: dict[str, Any] = {
            "workspace_id": WORKSPACE,
            "user_id": OWNER,
            "account_generation": GENERATION,
            "host_id": HOST,
            "repo_path": REPO,
            "worktree_path": ROOT,
            **spec,
        }
        return start_run(self.run_store, **fields)

    @property
    def branch(self) -> str:
        return run_branch_name(self.run.id)

    def binding(
        self,
        slot_role: SlotRole,
        *,
        run_id: str | None = None,
        host_id: str = HOST,
        session_generation: int = 1,
    ) -> SessionBinding:
        return step_binding(
            workspace_id=WORKSPACE,
            run_id=run_id or self.run.id,
            session_id=SESSION,
            slot_role=slot_role,
            host_id=host_id,
            session_generation=session_generation,
        )

    async def _turn_ended(self, *, workspace_id: int, run_id: str, session_id: str) -> bool:
        self.turn_checks.append(
            {"workspace_id": workspace_id, "run_id": run_id, "session_id": session_id}
        )
        return self.turn_end

    def executor(self, kind: str, *, turn_end_timeout_s: float = 30.0) -> EffectExecutor:
        if kind == "commit":
            return commit_executor(
                self.channels,
                self.intents,
                self.bindings,
                self.run_store,
                self.scope,
                turn_ended=self._turn_ended,
                turn_end_timeout_s=turn_end_timeout_s,
            )
        if kind == "salvage":
            return salvage_executor(self.channels, self.run_store, self.scope)
        return reset_executor(self.channels, self.run_store, self.scope)

    def effect_key(self, kind: str) -> str:
        return f"{self.run.id}:4:{kind}:slot-1"

    def payload(self, kind: str, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "effect_type": f"workspace.{kind}",
            "effect_key": self.effect_key(kind),
        }
        if kind == "commit":
            payload |= {
                "session_id": SESSION,
                "message": MESSAGE,
                "attempt_id": ATTEMPT,
                "node_id": "review",
                "item_path": "items/1",
            }
        elif kind == "reset":
            payload["commit"] = BASE
        payload |= overrides
        return {key: value for key, value in payload.items() if value is not _DROP}

    async def run_effect(
        self,
        kind: str,
        payload: dict[str, object] | str | None = None,
        *,
        run_id: str | None = None,
    ) -> EffectOutcome:
        async def _ensure_lease() -> bool:
            self.events.append("lease")
            return True

        ctx = effect_context(
            workspace_id=WORKSPACE,
            run_id=run_id or self.run.id,
            payload=self.payload(kind) if payload is None else payload,
            ensure_lease=_ensure_lease,
        )
        return await self.executor(kind)(ctx)


_DROP = object()
_KINDS = ["commit", "salvage", "reset"]


def _failed(outcome: EffectOutcome) -> EffectFailed:
    assert isinstance(outcome, EffectFailed), outcome
    return outcome


def _completed(outcome: EffectOutcome) -> dict[str, Any]:
    assert isinstance(outcome, EffectCompleted), outcome
    assert outcome.result is not None
    return outcome.result


async def test_a_writer_commit_reserves_the_pre_op_head_before_the_first_try() -> None:
    harness = _Harness()
    op_key = effect_op_key(WORKSPACE, harness.effect_key("commit"))

    result = _completed(await harness.run_effect("commit"))

    assert result == {
        "commit": NEW,
        "empty": False,
        "subject": "Review: done",
        "diff_stat": {**DIFF, "paths_truncated": False},
        "node_id": "review",
        "item_path": "items/1",
    }
    # HEAD is read once and recorded before any write; the lease is checked before each write.
    assert harness.events == ["head", "lease", "reserve", "lease", "commit", "diff_stat"]
    assert harness.intents.rows[(WORKSPACE, op_key)] == WorkspaceOpIntent(
        workspace_id=WORKSPACE,
        op_key=op_key,
        run_id=harness.run.id,
        op=WorkspaceOpIntentOp.COMMIT,
        host_id=HOST,
        root=ROOT,
        expected_head=BASE,
        created_at=0,
    )
    commit = harness.channel.requests[1]
    assert (commit.host_id, commit.root, commit.op_key) == (HOST, ROOT, op_key)
    assert commit.params == {
        "repo_root": REPO,
        "branch": harness.branch,
        "expected_head": BASE,
        "message": MESSAGE,
        "trailers": [],
        "run_id": harness.run.id,
        "attempt_id": ATTEMPT,
    }
    diff = harness.channel.requests[2]
    assert (diff.params["from_commit"], diff.params["to_commit"]) == (BASE, NEW)
    assert harness.turn_checks == [
        {"workspace_id": WORKSPACE, "run_id": harness.run.id, "session_id": SESSION}
    ]

    # A retry after the branch moved commits on the recorded HEAD, not the new one.
    harness.events.clear()
    harness.channel.replies["head"] = {"head": NEW, "branch": None, "merge_in_progress": False}

    assert _completed(await harness.run_effect("commit")) == result
    assert harness.events == ["lease", "reserve", "lease", "commit", "diff_stat"]
    assert harness.channel.requests[-2].params["expected_head"] == BASE


async def test_a_payload_head_is_recorded_without_asking_the_host() -> None:
    harness = _Harness()

    result = _completed(
        await harness.run_effect(
            "commit", harness.payload("commit", expected_head=BASE, diff_from=SALVAGED)
        )
    )

    assert result["commit"] == NEW
    assert harness.channel.ops() == ["commit", "diff_stat"]
    assert harness.channel.requests[0].params["expected_head"] == BASE
    assert harness.channel.requests[1].params["from_commit"] == SALVAGED


@pytest.mark.parametrize(
    ("slot_role", "bound_to_run", "turn_end"),
    [
        (SlotRole.ORCHESTRATOR, True, True),
        (SlotRole.VERIFIER, True, True),
        (None, False, True),
        (SlotRole.STEP_AGENT, False, True),
        (SlotRole.STEP_AGENT, True, False),
        # A turn check that answers anything but a plain True fails closed.
        (SlotRole.STEP_AGENT, True, 1),
        (SlotRole.STEP_AGENT, True, "true"),
        (SlotRole.STEP_AGENT, True, None),
    ],
    ids=[
        "orchestrator",
        "verifier",
        "no-binding",
        "another-runs-binding",
        "writer-mid-turn",
        "truthy-int-turn-check",
        "truthy-text-turn-check",
        "no-turn-answer",
    ],
)
async def test_only_a_writer_at_its_turn_end_may_commit(
    slot_role: SlotRole | None, bound_to_run: bool, turn_end: object
) -> None:
    harness = _Harness(turn_end=turn_end)  # type: ignore[arg-type]
    harness.bindings.rows.clear()
    if slot_role is not None:
        run_id = harness.run.id if bound_to_run else "f" * 32
        harness.bindings.rows[(WORKSPACE, SESSION)] = harness.binding(slot_role, run_id=run_id)

    failure = _failed(await harness.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == ("workspace.op_host_violation", False)
    assert SESSION in failure.message
    # Refused before the host is reached or anything is recorded.
    assert harness.channels.calls == []
    assert harness.events == []


async def test_a_merge_resolver_is_a_writer() -> None:
    harness = _Harness()
    harness.bindings.rows[(WORKSPACE, SESSION)] = harness.binding(SlotRole.MERGE_RESOLVER)

    assert _completed(await harness.run_effect("commit"))["commit"] == NEW


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize(
    ("name", "value"),
    [("user_id", "bob@example.com"), ("account_generation", "gen-2"), ("user_id", None)],
    ids=["other-user", "other-registration", "null-user"],
)
async def test_a_payload_identity_that_differs_from_the_run_row_is_refused(
    kind: str, name: str, value: str | None
) -> None:
    harness = _Harness()

    failure = _failed(await harness.run_effect(kind, harness.payload(kind, **{name: value})))

    assert (failure.error_code, failure.retryable) == ("effect.identity_mismatch", False)
    assert "bob" not in failure.message
    assert harness.scope.entered == []
    assert harness.channels.calls == []


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize(
    "payload_identity",
    [{}, {"user_id": OWNER, "account_generation": GENERATION}],
    ids=["no-payload-identity", "matching-payload-identity"],
)
async def test_each_executor_enters_the_run_rows_scope_before_the_host(
    kind: str, payload_identity: dict[str, str]
) -> None:
    harness = _Harness()
    # Silent or matching, the payload never decides the identity: the run row does.
    _completed(await harness.run_effect(kind, harness.payload(kind, **payload_identity)))

    scope = {
        "workspace_id": WORKSPACE,
        "run_id": harness.run.id,
        "user_id": OWNER,
        "account_generation": GENERATION,
        "host_id": HOST,
    }
    assert harness.scope.entered == [scope]
    assert harness.channels.calls == [
        {
            "workspace_id": WORKSPACE,
            "user_id": OWNER,
            "account_generation": GENERATION,
            "host_id": HOST,
            "scope": scope,
        }
    ]
    assert harness.scope.active is None

    # A payload naming another identity is refused before any scope is entered.
    harness.scope.entered.clear()
    other = harness.payload(kind, user_id="bob@example.com", account_generation=GENERATION)
    failure = _failed(await harness.run_effect(kind, other))
    assert failure.error_code == "effect.identity_mismatch"
    assert harness.scope.entered == []


@pytest.mark.parametrize(
    ("kind", "overrides"),
    [
        ("commit", {"effect_key": _DROP}),
        ("commit", {"effect_key": ""}),
        ("commit", {"session_id": _DROP}),
        ("commit", {"message": _DROP}),
        ("commit", {"message": " \n"}),
        ("commit", {"message": "bad\x1b[31m"}),
        ("commit", {"attempt_id": _DROP}),
        ("commit", {"attempt_id": "Attempt 1"}),
        ("commit", {"expected_head": "HEAD"}),
        ("commit", {"diff_from": "main"}),
        ("commit", {"node_id": 3}),
        ("commit", {"node_id": "n" * 129}),
        ("commit", {"node_id": "\u4e2d" * 22}),
        ("commit", {"item_path": "items/\x1b[2J"}),
        ("commit", {"item_path": "\U0001f600" * 86}),
        ("commit", {"session_id": "S" * 32}),
        ("commit", {"session_id": "s" * 65}),
        ("salvage", {"effect_key": 7}),
        ("salvage", {"effect_key": "x" * 600}),
        ("reset", {"commit": _DROP}),
        ("reset", {"commit": "abc"}),
    ],
    ids=[
        "no-effect-key",
        "empty-effect-key",
        "no-session",
        "no-message",
        "blank-message",
        "escape-in-message",
        "no-attempt",
        "bad-attempt",
        "symbolic-expected-head",
        "symbolic-diff-from",
        "non-text-node",
        "long-node",
        "wide-node",
        "escape-in-item-path",
        "emoji-item-path-over-its-bytes",
        "upper-case-session",
        "long-session",
        "non-text-effect-key",
        "long-effect-key",
        "no-reset-commit",
        "short-reset-commit",
    ],
)
async def test_an_invalid_payload_is_refused_before_the_host(
    kind: str, overrides: dict[str, object]
) -> None:
    harness = _Harness()

    failure = _failed(await harness.run_effect(kind, harness.payload(kind, **overrides)))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert harness.channels.calls == []
    assert harness.events == []


@pytest.mark.parametrize("payload", ["not json", "[1, 2]"], ids=["not-json", "not-an-object"])
async def test_a_payload_that_is_not_a_json_object_is_refused(payload: str) -> None:
    failure = _failed(await _Harness().run_effect("reset", payload))

    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize("missing", ["host_id", "repo_path", "worktree_path", "run_branch"])
async def test_a_run_without_a_run_worktree_is_refused(kind: str, missing: str) -> None:
    harness = _Harness()
    harness.run = harness.start(**{missing: None})
    harness.bindings.rows[(WORKSPACE, SESSION)] = replace(
        harness.bindings.rows[(WORKSPACE, SESSION)], run_id=harness.run.id
    )

    failure = _failed(await harness.run_effect(kind))

    assert (failure.error_code, failure.retryable) == ("workspace.target_mismatch", False)
    assert harness.channels.calls == []


_FAILURES = [
    pytest.param(
        WorkspaceOpError("workspace.backend_unavailable", "tunnel lost"),
        "backend_unavailable",
        True,
        id="tunnel-lost",
    ),
    pytest.param(
        WorkspaceOpError("workspace.backend_unavailable", "repo has hooks", permanent=True),
        "backend_unavailable",
        False,
        id="permanent-backend",
    ),
    pytest.param(
        WorkspaceOpError("workspace.timeout", "index.lock held", permanent=True),
        "timeout",
        True,
        id="timeout-always-retried",
    ),
    pytest.param(
        WorkspaceOpError("workspace.capability_unavailable", "old host"),
        "capability_unavailable",
        False,
        id="capability-never-retried",
    ),
    pytest.param(
        WorkspaceOpError("workspace.worktree_displaced", "both paths exist"),
        "worktree_displaced",
        False,
        id="displaced",
    ),
    pytest.param(
        WorkspaceOpError("workspace.git_failed", "a FIFO in the tree"),
        "git_failed",
        False,
        id="git-failed",
    ),
    pytest.param(
        WorkspaceOpError("workspace.target_mismatch", "HEAD moved"),
        "target_mismatch",
        False,
        id="target-mismatch",
    ),
    pytest.param(
        WorkspaceOpError("workspace.op_key_conflict", "other params"),
        "op_key_conflict",
        False,
        id="op-key-conflict",
    ),
    pytest.param(
        HostAccessRefused("not_permitted", "host is not yours"),
        "host_not_permitted",
        False,
        id="taken-over",
    ),
    pytest.param(
        HostAccessRefused("host_offline", "host is not connected"),
        "backend_unavailable",
        True,
        id="offline",
    ),
    pytest.param(
        ValueError("the host refused a param"), "invalid_params", False, id="invalid-params"
    ),
]


@pytest.mark.parametrize("kind", _KINDS)
@pytest.mark.parametrize(("error", "code", "retryable"), _FAILURES)
async def test_host_failures_map_to_their_retryability(
    kind: str, error: BaseException, code: str, retryable: bool
) -> None:
    harness = _Harness()
    harness.channel.replies[kind] = error

    failure = _failed(await harness.run_effect(kind))

    assert (failure.error_code, failure.retryable) == (f"workspace.{code}", retryable)
    assert len(failure.message) <= 2000


@pytest.mark.parametrize(
    ("refusal", "code", "retryable"),
    [
        (HostAccessRefused("not_permitted", "host is not yours"), "host_not_permitted", False),
        (HostAccessRefused("host_offline", "host is not connected"), "backend_unavailable", True),
    ],
    ids=["not-permitted", "offline"],
)
async def test_a_host_refused_at_authorization_sends_nothing(
    refusal: HostAccessRefused, code: str, retryable: bool
) -> None:
    harness = _Harness()
    harness.channels.refusal = refusal

    failure = _failed(await harness.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == (f"workspace.{code}", retryable)
    assert harness.channel.requests == []


async def test_an_op_key_recorded_for_another_worktree_is_a_permanent_conflict() -> None:
    harness = _Harness()
    op_key = effect_op_key(WORKSPACE, harness.effect_key("commit"))
    harness.intents.rows[(WORKSPACE, op_key)] = WorkspaceOpIntent(
        workspace_id=WORKSPACE,
        op_key=op_key,
        run_id=harness.run.id,
        op=WorkspaceOpIntentOp.COMMIT,
        host_id=HOST,
        root="/Users/alice/elsewhere",
        expected_head=BASE,
        created_at=0,
    )

    failure = _failed(await harness.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == ("workspace.op_key_conflict", False)
    assert "commit" not in harness.channel.ops()


@pytest.mark.parametrize(
    "error",
    [
        WorkspaceOpError("workspace.git_failed", "bad revision"),
        WorkspaceOpError("workspace.backend_unavailable", "tunnel lost"),
    ],
    ids=["git-failed", "tunnel-lost"],
)
async def test_a_diff_stat_failure_after_the_commit_retries_to_the_same_result(
    error: WorkspaceOpError,
) -> None:
    harness = _Harness()
    harness.channel.replies["diff_stat"] = error

    failure = _failed(await harness.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == (error.code, True)

    harness.channel.replies["diff_stat"] = dict(DIFF)
    result = _completed(await harness.run_effect("commit"))
    assert (result["commit"], result["diff_stat"]["files_changed"]) == (NEW, 2)
    assert harness.channel.ops().count("head") == 1


async def test_salvage_and_reset_use_the_host_channel_on_the_run_worktree() -> None:
    harness = _Harness()
    harness.bindings.rows.clear()

    salvaged = _completed(await harness.run_effect("salvage"))
    reset = _completed(await harness.run_effect("reset"))

    salvage_key = effect_op_key(WORKSPACE, harness.effect_key("salvage"))
    reset_key = effect_op_key(WORKSPACE, harness.effect_key("reset"))
    assert salvaged == {"ref": f"refs/coral/salvage/{salvage_key}", "commit": SALVAGED}
    assert reset == {"head": BASE}
    salvage, reset_request = harness.channel.requests
    assert (salvage.op, salvage.root, salvage.op_key) == ("salvage", ROOT, salvage_key)
    assert salvage.params == {"repo_root": REPO, "branch": harness.branch}
    assert (reset_request.op, reset_request.op_key) == ("reset", reset_key)
    assert reset_request.params == {"repo_root": REPO, "branch": harness.branch, "commit": BASE}
    assert harness.events == ["lease", "salvage", "lease", "reset"]


async def test_a_large_diff_is_bounded_in_the_commit_result() -> None:
    harness = _Harness()
    paths = sorted(f"src/{index:03d}/" + "p" * 1016 for index in range(200))
    harness.channel.replies["diff_stat"] = {
        "files_changed": 200,
        "insertions": 200,
        "deletions": 0,
        "paths": paths,
    }

    result = _completed(
        await harness.run_effect("commit", harness.payload("commit", message="s" * 600))
    )

    assert stored_result_bytes(result) <= RESULT_BYTE_BUDGET
    assert result["diff_stat"]["paths_truncated"] is True
    assert result["diff_stat"]["files_changed"] == 200
    assert len(result["subject"]) == 256


async def test_a_path_list_the_host_cut_stays_marked_cut_in_the_result() -> None:
    harness = _Harness()
    # A vendored tree too large for the host channel: the host kept the counts, cut the list.
    harness.channel.replies["diff_stat"] = {
        "files_changed": 40_000,
        "insertions": 40_000,
        "deletions": 0,
        "paths": ["vendor/00000"],
        "paths_truncated": True,
    }

    result = _completed(await harness.run_effect("commit"))

    assert result["diff_stat"] == {
        "files_changed": 40_000,
        "insertions": 40_000,
        "deletions": 0,
        "paths": ["vendor/00000"],
        "paths_truncated": True,
    }


async def test_an_item_path_at_the_payload_bound_is_echoed_whole() -> None:
    harness = _Harness()
    # 1,024 stored bytes, the most the payload accepts; the engine finds its item by it.
    item_path = "items/" + "p" * 1_018

    result = _completed(
        await harness.run_effect("commit", harness.payload("commit", item_path=item_path))
    )

    assert result["item_path"] == item_path


async def test_echoed_text_too_large_for_the_result_fails_before_any_commit() -> None:
    harness = _Harness()
    # Each astral character is stored as a 12-byte escape: 600 of them would not fit the
    # result once the commit had landed, so the payload is refused before anything is sent.
    wide = "\U0001f600" * 600

    outcome = await harness.run_effect(
        "commit", harness.payload("commit", node_id=wide, item_path=wide)
    )

    failure = _failed(outcome)
    assert (failure.error_code, failure.retryable) == ("effect.invalid_payload", False)
    assert wide[:8] not in failure.message
    assert harness.events == []
    assert harness.intents.rows == {}


@pytest.mark.parametrize(
    "subject",
    ["\u4e2d\u6587\u63d0\u4ea4" * 300, "\U0001f680 shipped " * 300],
    ids=["cjk", "emoji"],
)
async def test_a_wide_subject_item_path_and_full_diff_still_fit_the_result(subject: str) -> None:
    harness = _Harness()
    paths = sorted(f"src/{index:03d}/" + "p" * 1016 for index in range(200))
    harness.channel.replies["diff_stat"] = {
        "files_changed": 200,
        "insertions": 200,
        "deletions": 0,
        "paths": paths,
    }
    # The widest echoed ids the payload accepts.
    node_id = "\u8282" * 21
    item_path = "\U0001f4c1" * 85

    result = _completed(
        await harness.run_effect(
            "commit",
            harness.payload(
                "commit", message=f"{subject}\n\nBody.", node_id=node_id, item_path=item_path
            ),
        )
    )

    assert stored_result_bytes(result) <= RESULT_BYTE_BUDGET
    assert (result["node_id"], result["item_path"]) == (node_id, item_path)
    assert result["subject"].endswith("…")
    assert subject.startswith(result["subject"][:-1])
    assert result["diff_stat"]["paths_truncated"] is True
    assert result["diff_stat"]["paths"] == paths[: len(result["diff_stat"]["paths"])]
    assert harness.channel.ops() == ["head", "commit", "diff_stat"]


@pytest.mark.parametrize(
    ("kind", "sent"),
    [("commit", ["head"]), ("salvage", []), ("reset", [])],
    ids=["commit-reads-head-only", "salvage", "reset"],
)
async def test_a_lost_lease_stops_each_write_before_it_is_sent(kind: str, sent: list[str]) -> None:
    harness = _Harness()

    async def _lost() -> bool:
        return False

    ctx = effect_context(
        workspace_id=WORKSPACE,
        run_id=harness.run.id,
        payload=harness.payload(kind),
        ensure_lease=_lost,
    )

    with pytest.raises(StartupLeaseLost):
        await harness.executor(kind)(ctx)

    assert harness.channel.ops() == sent
    assert harness.intents.rows == {}


async def test_a_lease_lost_after_the_intent_leaves_the_next_owner_its_head() -> None:
    harness = _Harness()
    answers = iter([True, False])

    async def _lost_second_time() -> bool:
        harness.events.append("lease")
        return next(answers)

    ctx = effect_context(
        workspace_id=WORKSPACE,
        run_id=harness.run.id,
        payload=harness.payload("commit"),
        ensure_lease=_lost_second_time,
    )

    with pytest.raises(StartupLeaseLost):
        await harness.executor("commit")(ctx)

    # The HEAD is recorded, but the commit itself was never sent.
    assert harness.events == ["head", "lease", "reserve", "lease"]
    # The worker that claims the item next commits on that HEAD, though the branch moved.
    harness.channel.replies["head"] = {"head": NEW, "branch": None, "merge_in_progress": False}

    result = _completed(await harness.run_effect("commit"))

    assert result["commit"] == NEW
    assert harness.channel.ops() == ["head", "commit", "diff_stat"]
    assert harness.channel.requests[1].params["expected_head"] == BASE


@pytest.mark.parametrize("kind", _KINDS)
async def test_an_effect_key_of_another_run_is_refused_before_the_run_is_used(kind: str) -> None:
    harness = _Harness()
    other_run = "f" * 32

    failure = _failed(
        await harness.run_effect(
            kind, harness.payload(kind, effect_key=f"{other_run}:4:{kind}:slot-1")
        )
    )

    assert (failure.error_code, failure.retryable) == ("effect.identity_mismatch", False)
    assert other_run not in failure.message
    assert harness.scope.entered == []
    assert harness.channels.calls == []


@pytest.mark.parametrize(
    "effect_key",
    ["{run}", "{run}x:4:commit:slot-1", "{run}:4:commit\x00commit"],
    ids=["bare-run-id", "longer-run-id", "nul"],
)
async def test_only_a_key_under_the_runs_prefix_is_accepted(effect_key: str) -> None:
    harness = _Harness()

    failure = _failed(
        await harness.run_effect(
            "commit", harness.payload("commit", effect_key=effect_key.format(run=harness.run.id))
        )
    )

    assert failure.error_code in {"effect.identity_mismatch", "effect.invalid_payload"}
    assert not failure.retryable
    assert harness.channels.calls == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"session_generation": 2}, "current session"),
        ({"host_id": "host-2"}, "another host"),
    ],
    ids=["stale-generation", "other-host"],
)
async def test_a_writer_binding_must_be_its_slots_current_session_on_the_run_host(
    change: dict[str, Any], reason: str
) -> None:
    harness = _Harness()
    harness.bindings.rows[(WORKSPACE, SESSION)] = harness.binding(SlotRole.STEP_AGENT, **change)

    failure = _failed(await harness.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == ("workspace.op_host_violation", False)
    assert reason in failure.message
    assert harness.turn_checks == []
    assert harness.channels.calls == []


async def test_a_session_its_slot_has_moved_on_from_cannot_commit() -> None:
    harness = _Harness()
    # A restart gave the slot a new session and generation; the old one stays bound.
    add_slot(harness.run_store, harness.run, session_id="7" * 32, session_generation=2)

    failure = _failed(await harness.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == ("workspace.op_host_violation", False)
    assert "current session" in failure.message
    assert harness.channels.calls == []


async def test_a_spec_naming_another_runs_branch_is_refused() -> None:
    harness = _Harness()
    harness.run = harness.start(run_branch=run_branch_name("f" * 32))

    for kind in _KINDS:
        failure = _failed(await harness.run_effect(kind))
        assert (failure.error_code, failure.retryable) == ("workspace.target_mismatch", False)
    assert harness.channels.calls == []


async def test_an_unknown_turn_state_is_retried_and_sends_nothing() -> None:
    harness = _Harness()

    async def _cold_cache(**_: object) -> bool:
        raise CoralSessionError("session.status_unavailable", "no live status yet", retryable=True)

    harness._turn_ended = _cold_cache  # type: ignore[method-assign]

    failure = _failed(await harness.run_effect("commit"))

    assert (failure.error_code, failure.retryable) == ("session.status_unavailable", True)
    assert harness.channels.calls == []


async def test_a_turn_check_that_does_not_answer_in_time_is_retried() -> None:
    harness = _Harness()
    never = asyncio.Event()

    async def _stuck(**_: object) -> bool:
        await never.wait()
        return True

    harness._turn_ended = _stuck  # type: ignore[method-assign]
    ctx = effect_context(
        workspace_id=WORKSPACE, run_id=harness.run.id, payload=harness.payload("commit")
    )

    failure = _failed(await harness.executor("commit", turn_end_timeout_s=0.01)(ctx))

    assert (failure.error_code, failure.retryable) == (TURN_STATE_UNKNOWN, True)
    assert harness.channels.calls == []


async def test_a_bug_in_the_turn_check_or_a_store_is_never_a_param_error() -> None:
    harness = _Harness()

    async def _broken(**_: object) -> bool:
        raise ValueError("the check misread a status")

    harness._turn_ended = _broken  # type: ignore[method-assign]

    # Left to the drainer, which retries it as an unhandled exception.
    with pytest.raises(ValueError, match="misread"):
        await harness.run_effect("commit")

    harness = _Harness()

    def _store_bug(*_: object, **__: object) -> None:
        raise ValueError("bad stored slot role")

    harness.bindings.get = _store_bug  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="stored slot role"):
        await harness.run_effect("commit")
    assert harness.channels.calls == []


async def test_control_characters_in_host_paths_are_escaped_in_the_result() -> None:
    harness = _Harness()
    harness.channel.replies["diff_stat"] = {
        "files_changed": 2,
        "insertions": 1,
        "deletions": 0,
        "paths": ["docs/\x1b[2Jclear.md", "notes/line\nbreak.txt"],
    }

    result = _completed(await harness.run_effect("commit"))

    assert result["diff_stat"]["paths"] == ["docs/\\x1b[2Jclear.md", "notes/line\\x0abreak.txt"]


async def test_a_reset_the_host_reports_on_another_commit_is_refused() -> None:
    harness = _Harness()
    harness.channel.replies["reset"] = {"head": NEW}

    failure = _failed(await harness.run_effect("reset"))

    assert (failure.error_code, failure.retryable) == ("workspace.backend_unavailable", False)


@pytest.mark.parametrize(
    ("overrides", "echo"),
    [({"attempt_id": "A" * 50_000}, "AAAA"), ({"expected_head": "z" * 50_000}, "zzzz")],
    ids=["attempt", "expected-head"],
)
async def test_an_invalid_payload_message_is_short_and_never_repeats_the_value(
    overrides: dict[str, object], echo: str
) -> None:
    harness = _Harness()

    failure = _failed(await harness.run_effect("commit", harness.payload("commit", **overrides)))

    assert failure.error_code == "effect.invalid_payload"
    assert len(failure.message) <= 500
    assert echo not in failure.message
