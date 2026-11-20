"""A finished run's outcome: its checkout command, its displayed diff, and the host read.

The command and path rules are pure. :class:`OutcomeDiffs` reads ``head`` and
``diff_stat`` through a scripted host channel (``FakeHostChannel``): its admission,
single flight, bounded cache, deadlines, error map and logs. The outcome route, the
host's real handlers on real git and the command run in ``sh`` are in
``test_runs_api.py``.
"""

from __future__ import annotations

import ast
import asyncio
import logging
import shlex
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import coral.api.outcome as outcome_module
from coral.api.outcome import (
    INVISIBLE_CODE_POINTS,
    MAX_OUTCOME_PATH_CHARS,
    MAX_OUTCOME_PATHS,
    MAX_OUTCOME_READS,
    MAX_OUTCOME_READS_PER_USER,
    OUTCOME_CACHE_BYTES,
    OUTCOME_CACHE_ENTRIES,
    OUTCOME_DEADLINE_S,
    OUTCOME_HOST_TIMEOUT_S,
    UNSAFE_CATEGORIES,
    DiffRead,
    OutcomeDiffs,
    OutcomeTarget,
    checkout_commands,
    display_path,
    outcome_target,
    run_outcome,
)
from coral.api.run_models import OutcomeCheckout, OutcomeDiff
from coral.db.enum_codecs import RunStatus
from coral.omni.protocols import HostAccessRefused, HostWorkspaceChannels, Viewer
from coral.stores.protocols import CoralRun, RunStartSpec, RunState
from coral.workspace.executors import RunTarget
from coral.workspace.ops import WorkspaceOpError, WorkspaceRef
from coral.workspace.run_worktree import run_branch_name
from tests._helpers.polling import poll_until_async
from tests.budgets import budget
from tests.coral.workspace._executor_fakes import (
    ChannelRequest,
    FakeChannels,
    FakeHostChannel,
    HeldChannels,
    RecordingScopeRunner,
    Reply,
    StalledHost,
)

WORKSPACE = 7
RUN_ID = "0a1b2c3d" * 4
BRANCH = run_branch_name(RUN_ID)
BASE = "a" * 40
HEAD = "b" * 40
REPO = "/home/alice/team's repo"
WORKTREE = "/home/alice/team's repo-worktrees/coral-r-0a1b2c3d4e5f-base"
ALICE = Viewer("alice")
TIMEOUT_S = budget(10)


def _target(
    repo: str = REPO, worktree: str = WORKTREE, *, branch: str = BRANCH, base: str | None = BASE
) -> OutcomeTarget:
    ref = WorkspaceRef(host_id="host-1", root=worktree, branch=branch)
    return OutcomeTarget(
        worktree=RunTarget(host_id="host-1", repo_root=repo, ref=ref), base_commit=base
    )


def _state(
    run_id: str = RUN_ID,
    *,
    user: str | None = "alice",
    generation: str | None = None,
    status: RunStatus = RunStatus.COMPLETED,
    **spec: Any,
) -> RunState:
    run = CoralRun(
        workspace_id=WORKSPACE,
        id=run_id,
        workflow_id="wf",
        version_id="v1",
        status=int(status),
        version=3,
        next_log_seq=4,
        activation_count=1,
        title="Ship it",
        engine_version=1,
        state_version=1,
        log_version=1,
        created_at=10,
        updated_at=20,
        user_id=user,
        account_generation=generation,
        finished_at=20,
    )
    fields: dict[str, Any] = {
        "host_id": "host-1",
        "repo_path": REPO,
        "worktree_path": WORKTREE,
        "run_branch": run_branch_name(run_id),
        "base_commit": BASE,
        **spec,
    }
    return RunState(
        run=run,
        spec=RunStartSpec(
            "wf",
            "v1",
            "Ship it",
            "",
            workspace_id=WORKSPACE,
            user_id=user,
            account_generation=generation,
            **fields,
        ),
    )


def _head(request: ChannelRequest) -> Mapping[str, object]:
    """The run worktree's HEAD, on the branch the request names."""
    return {"head": HEAD, "branch": request.params["branch"], "merge_in_progress": False}


def _stat(*paths: str, truncated: bool | None = None) -> Mapping[str, object]:
    reply: dict[str, object] = {
        "files_changed": len(paths),
        "insertions": 7,
        "deletions": 2,
        "paths": list(paths),
    }
    if truncated is not None:
        reply["paths_truncated"] = truncated
    return reply


def _host(replies: Mapping[str, Reply] | None = None) -> tuple[FakeHostChannel, FakeChannels]:
    """A host answering ``head`` on the requested branch and a one-file diff, or ``replies``."""
    scripted: dict[str, Reply] = {"head": _head, "diff_stat": _stat("src/app.py")}
    host = FakeHostChannel([], {**scripted, **(replies or {})})
    return host, FakeChannels(host, RecordingScopeRunner())


async def _read(
    diffs: OutcomeDiffs,
    channels: HostWorkspaceChannels,
    state: RunState | None = None,
    viewer: Viewer = ALICE,
) -> DiffRead:
    state = state or _state()
    target = outcome_target(state)
    assert target is not None
    return await diffs.read(viewer, state=state, target=target, channels=channels)


def test_the_outcome_bounds_are_the_designed_ones() -> None:
    assert (OUTCOME_HOST_TIMEOUT_S, OUTCOME_DEADLINE_S) == (5.0, 12.0)
    assert (MAX_OUTCOME_READS, MAX_OUTCOME_READS_PER_USER) == (4, 1)
    assert (OUTCOME_CACHE_ENTRIES, OUTCOME_CACHE_BYTES) == (256, 2 << 20)
    assert (MAX_OUTCOME_PATHS, MAX_OUTCOME_PATH_CHARS) == (100, 512)
    assert frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}) == UNSAFE_CATEGORIES


# ── The checkout command ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["team's repo", "$HOME", "`id`", "a b", "a;b", "a*b", "~a", "a!b", 'say "hi"', "é", "עברית"],
)
@pytest.mark.parametrize("where", ["repo", "worktree"])
def test_a_checkout_command_quotes_each_path_so_a_shell_reads_it_back(
    name: str, where: str
) -> None:
    repo = f"/work/{name}" if where == "repo" else "/work/repo"
    worktree = f"/work/{name}-worktrees/x" if where == "worktree" else "/work/repo-worktrees/x"

    checkout = checkout_commands(_target(repo, worktree))

    assert checkout.unavailable is None
    assert checkout.command is not None and checkout.worktree_command is not None
    assert shlex.split(checkout.command) == [
        "git",
        "-C",
        repo,
        "checkout",
        "--detach",
        f"refs/heads/{BRANCH}",
    ]
    assert shlex.split(checkout.worktree_command) == ["cd", worktree]
    assert checkout.command == (
        f"git -C {shlex.quote(repo)} checkout --detach {shlex.quote('refs/heads/' + BRANCH)}"
    )


UNSAFE = [
    pytest.param("\\", id="backslash"),
    # fish reads \' inside single quotes as an escaped quote, ending nothing.
    pytest.param("/tmp/a\\'\"; echo INJECTED #", id="fish-escape"),
    pytest.param("\n", id="line-feed"),
    pytest.param("\x7f", id="delete"),
    pytest.param("\x85", id="c1-next-line"),
    pytest.param("\u202e", id="right-to-left-override"),
    pytest.param("\u200b", id="zero-width-space"),
    pytest.param("\u2066", id="left-to-right-isolate"),
    pytest.param("\ufeff", id="byte-order-mark"),
    pytest.param("\u2028", id="line-separator"),
    pytest.param("\u2029", id="paragraph-separator"),
    pytest.param("\ue000", id="private-use"),
    pytest.param("\ud800", id="lone-surrogate"),
    pytest.param("\u0378", id="unassigned"),
    pytest.param("\u3164", id="hangul-filler"),
    pytest.param("\u115f", id="hangul-choseong-filler"),
    pytest.param("\u17b4", id="khmer-vowel-inherent"),
    pytest.param("\u180b", id="mongolian-variation-selector"),
    pytest.param("\ufe0f", id="variation-selector"),
    pytest.param("\U000e0100", id="variation-selector-supplement"),
    pytest.param("\u034f", id="combining-grapheme-joiner"),
    pytest.param("\u2800", id="braille-blank"),
]


@pytest.mark.parametrize("character", UNSAFE)
@pytest.mark.parametrize("where", ["repo", "worktree"])
def test_a_path_a_shell_or_a_reader_could_misread_gets_no_command(
    character: str, where: str
) -> None:
    unsafe = f"/work/re{character}po"
    target = _target(unsafe, WORKTREE) if where == "repo" else _target(REPO, unsafe)

    assert checkout_commands(target) == OutcomeCheckout(
        command=None, worktree_command=None, unavailable="unsafe_path"
    )


def test_every_refused_character_is_unsafe_or_invisible() -> None:
    assert unicodedata.category("\u0378") == "Cn"
    for code_point in (0x3164, 0x115F, 0x17B4, 0x180B, 0xFE0F, 0xE0100, 0x034F, 0x2800):
        assert code_point in INVISIBLE_CODE_POINTS


@pytest.mark.parametrize(
    "path", ["repo", "./repo", "~/repo", "C:/repo", "C:\\repo", "//server/share/repo"]
)
@pytest.mark.parametrize("where", ["repo", "worktree"])
def test_a_path_that_is_not_an_absolute_posix_path_gets_no_command(path: str, where: str) -> None:
    target = _target(path, WORKTREE) if where == "repo" else _target(REPO, path)

    assert checkout_commands(target) == OutcomeCheckout(
        command=None, worktree_command=None, unavailable="non_posix_path"
    )


def test_a_run_without_its_own_worktree_gets_no_command() -> None:
    assert checkout_commands(None) == OutcomeCheckout(
        command=None, worktree_command=None, unavailable="no_worktree"
    )


def test_the_outcome_target_is_the_runs_own_worktree_and_its_base() -> None:
    assert outcome_target(_state()) == _target()
    assert outcome_target(_state(base_commit=None)) == _target(base=None)
    for missing in ("host_id", "repo_path", "worktree_path", "run_branch"):
        assert outcome_target(_state(**{missing: None})) is None, missing
    # Another run's branch is never this run's to show or check out.
    assert outcome_target(_state(run_branch=run_branch_name("f" * 32))) is None


# ── Diff paths and the assembled outcome ────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        ("src/app.py", "src/app.py"),
        ("docs/é ü.md", "docs/é ü.md"),
        ("a\u202eb", "a\\u{202E}b"),
        ("a\u200bb", "a\\u{200B}b"),
        ("a\u2066b", "a\\u{2066}b"),
        ("a\nb\x7f", "a\\u{000A}b\\u{007F}"),
        ("\u3164", "\\u{3164}"),
        ("x\U000e0100", "x\\u{E0100}"),
        ("lone\udcff", "lone\\u{DCFF}"),
        ("a\\b", "a\\u{005C}b"),
        # A name that spells an escape never shows as the character it names.
        ("a\\u{202E}b", "a\\u{005C}u{202E}b"),
    ],
)
def test_a_diff_path_shows_each_unsafe_or_invisible_character_as_its_code_point(
    path: str, shown: str
) -> None:
    assert display_path(path) == shown


def test_a_diff_path_is_cut_at_512_characters_between_escapes() -> None:
    assert display_path("a" * 512) == "a" * 512
    assert display_path("a" * 513) == "a" * 511 + "…"
    assert display_path("a" * 504 + "\u202e") == "a" * 504 + "\\u{202E}"
    # An escape that would cross the cut is left out whole.
    assert display_path("a" * 505 + "\u202e") == "a" * 505 + "…"
    assert display_path("\u202e" * 200) == "\\u{202E}" * 63 + "…"


@pytest.mark.parametrize(
    ("spec", "unavailable"),
    [
        ({"repo_path": "/work/re\u202epo"}, "unsafe_path"),
        ({"worktree_path": "work/repo-worktrees/x"}, "non_posix_path"),
    ],
)
def test_an_outcome_with_a_path_it_cannot_command_names_its_branch_and_hides_its_paths(
    spec: dict[str, str], unavailable: str
) -> None:
    state = _state(**spec)
    target = outcome_target(state)

    outcome = run_outcome(state.run, target, DiffRead(None, None, "base_unknown"))

    assert (outcome.branch, outcome.host_id, outcome.repo_path, outcome.worktree_path) == (
        BRANCH,
        "host-1",
        None,
        None,
    )
    assert outcome.checkout.unavailable == unavailable
    assert (outcome.diff, outcome.diff_unavailable) == (None, "base_unknown")


def test_an_outcome_without_a_worktree_names_nothing_of_it() -> None:
    state = _state(run_branch=run_branch_name("f" * 32))

    outcome = run_outcome(state.run, None, DiffRead(None, None, "no_worktree"))

    assert outcome.model_dump() == {
        "run_id": RUN_ID,
        "status": "completed",
        "finished_at": 20,
        "branch": None,
        "host_id": None,
        "repo_path": None,
        "worktree_path": None,
        "base_commit": None,
        "head_commit": None,
        "diff": None,
        "diff_unavailable": "no_worktree",
        "checkout": {"command": None, "worktree_command": None, "unavailable": "no_worktree"},
    }


# ── The host read ───────────────────────────────────────────────────────────


async def test_a_finished_runs_diff_is_read_from_its_worktree_as_its_owner() -> None:
    host, channels = _host({"diff_stat": _stat("src/app.py", "README.md")})
    state = _state(generation="g1")

    read = await _read(OutcomeDiffs(), channels, state)

    assert read == DiffRead(
        HEAD,
        OutcomeDiff(
            from_commit=BASE,
            to_commit=HEAD,
            files_changed=2,
            insertions=7,
            deletions=2,
            paths=("README.md", "src/app.py"),
            paths_truncated=False,
        ),
        None,
    )
    # Every channel argument comes from the stored run.
    assert channels.calls == [
        {
            "workspace_id": WORKSPACE,
            "user_id": "alice",
            "account_generation": "g1",
            "host_id": "host-1",
            "scope": None,
        }
    ]
    params = {"repo_root": REPO, "branch": BRANCH}
    assert host.requests == [
        ChannelRequest("host-1", "head", WORKTREE, params, OUTCOME_HOST_TIMEOUT_S, None),
        ChannelRequest(
            "host-1",
            "diff_stat",
            WORKTREE,
            {**params, "from_commit": BASE, "to_commit": HEAD},
            OUTCOME_HOST_TIMEOUT_S,
            None,
        ),
    ]


async def test_concurrent_reads_of_one_run_share_one_head_and_one_diff_stat() -> None:
    host, _channels = _host()
    held = HeldChannels(host)
    diffs = OutcomeDiffs()

    # The first task to run starts the read; the others join it.
    leader = asyncio.create_task(_read(diffs, held))
    followers = [asyncio.create_task(_read(diffs, held)) for _ in range(2)]
    await poll_until_async(lambda: held.entered == 1, timeout_s=TIMEOUT_S)
    # The leader's client goes away: the read it started goes on for the others.
    leader.cancel()
    await asyncio.gather(leader, return_exceptions=True)
    held.release.set()
    answers = await asyncio.wait_for(asyncio.gather(*followers), TIMEOUT_S)

    assert leader.cancelled()
    assert answers[0] == answers[1] and answers[0].diff is not None
    assert (held.entered, host.ops()) == (1, ["head", "diff_stat"])


async def test_a_read_whose_only_caller_goes_away_lands_in_the_cache_and_frees_its_slot() -> None:
    host, _channels = _host()
    held = HeldChannels(host)
    diffs = OutcomeDiffs()

    gone = asyncio.create_task(_read(diffs, held))
    await poll_until_async(lambda: held.entered == 1, timeout_s=TIMEOUT_S)
    # The client disconnected: nothing waits for the read any more.
    gone.cancel()
    await asyncio.gather(gone, return_exceptions=True)
    held.release.set()
    await poll_until_async(lambda: host.ops() == ["head", "diff_stat"], timeout_s=TIMEOUT_S)
    again = await _read(diffs, held)
    another_run = await _read(diffs, held, _state("e" * 32))

    assert gone.cancelled()
    assert again.diff is not None and again.diff.paths == ("src/app.py",)
    # The abandoned read's diff answers again, and its admission was given back.
    assert another_run.diff is not None
    assert host.ops().count("diff_stat") == 2


async def test_a_read_at_the_same_head_is_answered_from_the_cache() -> None:
    host, channels = _host()
    diffs = OutcomeDiffs()

    first = await _read(diffs, channels)
    again = await _read(diffs, channels)
    host.replies["head"] = {"head": "c" * 40, "branch": BRANCH, "merge_in_progress": False}
    moved = await _read(diffs, channels)

    assert again == first
    assert moved.head == "c" * 40 and moved.diff is not None and moved.diff.to_commit == "c" * 40
    assert host.ops() == ["head", "diff_stat", "head", "head", "diff_stat"]


async def test_the_cache_keeps_at_most_256_diffs() -> None:
    host, channels = _host()
    diffs = OutcomeDiffs()
    states = [_state(f"{index:032x}") for index in range(OUTCOME_CACHE_ENTRIES + 1)]
    for state in states:
        await _read(diffs, channels, state)
    host.requests.clear()

    await _read(diffs, channels, states[-1])
    await _read(diffs, channels, states[1])
    # The oldest diff made room for the newest.
    await _read(diffs, channels, states[0])

    assert host.ops() == ["head", "head", "head", "diff_stat"]


async def test_the_cache_keeps_at_most_2_mib_of_paths() -> None:
    # Each diff keeps 100 cut paths of 514 bytes: 40 of them fit in 2 MiB, 41 do not.
    paths = [f"{index:03d}{'p' * 600}" for index in range(MAX_OUTCOME_PATHS)]
    host, channels = _host({"diff_stat": _stat(*paths)})
    diffs = OutcomeDiffs()
    states = [_state(f"{index:032x}") for index in range(41)]
    for state in states:
        read = await _read(diffs, channels, state)
    assert read.diff is not None
    assert sum(len(path.encode()) for path in read.diff.paths) == 100 * (511 + 3)
    host.requests.clear()

    await _read(diffs, channels, states[1])
    await _read(diffs, channels, states[0])

    assert host.ops() == ["head", "head", "diff_stat"]


async def test_one_read_per_user_and_four_in_all_are_admitted_and_followers_take_none() -> None:
    host, _channels = _host()
    held = HeldChannels(host)
    diffs = OutcomeDiffs()
    users = [Viewer(f"user-{index}") for index in range(MAX_OUTCOME_READS + 1)]
    runs = [_state(f"{index:032x}", user=user.user_id) for index, user in enumerate(users)]

    reads = [
        asyncio.create_task(_read(diffs, held, runs[index], users[index]))
        for index in range(MAX_OUTCOME_READS)
    ]
    await poll_until_async(lambda: held.entered == MAX_OUTCOME_READS, timeout_s=TIMEOUT_S)
    follower = asyncio.create_task(_read(diffs, held, runs[0], users[0]))
    refused_in_all = await _read(diffs, held, runs[-1], users[-1])
    second_run = _state("e" * 32, user="user-0")
    refused_for_user = await _read(diffs, held, second_run, users[0])
    held.release.set()
    answers = await asyncio.wait_for(asyncio.gather(*reads, follower), TIMEOUT_S)
    admitted_after = await _read(diffs, held, runs[-1], users[-1])

    assert refused_in_all == refused_for_user == DiffRead(None, None, "busy")
    assert all(answer.diff is not None for answer in answers)
    assert answers[-1] == answers[0]
    assert admitted_after.diff is not None
    assert held.entered == MAX_OUTCOME_READS + 1


@pytest.mark.parametrize("stall", ["channel", "head"])
async def test_a_read_past_its_deadline_is_busy_and_gives_its_slot_back(stall: str) -> None:
    stalled: HostWorkspaceChannels = (
        HeldChannels(FakeHostChannel([], {}))
        if stall == "channel"
        else FakeChannels(StalledHost(), RecordingScopeRunner())
    )
    diffs = OutcomeDiffs(deadline_s=0.05)

    late = await asyncio.wait_for(_read(diffs, stalled), TIMEOUT_S)
    _host_channel, channels = _host()
    after = await _read(diffs, channels)

    assert late == DiffRead(None, None, "busy")
    assert after.diff is not None


PATH_ERROR = "fatal: bad object in /home/alice/secret repo"
FAILURES = [
    pytest.param("channel", HostAccessRefused("not_permitted", "not yours"), None, "host_offline"),
    pytest.param("channel", HostAccessRefused("host_offline", "offline"), None, "host_offline"),
    pytest.param(
        "head", WorkspaceOpError("workspace.backend_unavailable", "gone"), None, "host_offline"
    ),
    pytest.param(
        "head",
        WorkspaceOpError("workspace.backend_unavailable", "bad reply", permanent=True),
        None,
        "failed",
    ),
    pytest.param("head", WorkspaceOpError("workspace.timeout", "busy"), None, "busy"),
    pytest.param("head", TimeoutError(), None, "busy"),
    pytest.param(
        "head", WorkspaceOpError("workspace.target_mismatch", "gone"), None, "worktree_missing"
    ),
    pytest.param(
        "head",
        WorkspaceOpError("workspace.worktree_displaced", "aside", permanent=True),
        None,
        "worktree_missing",
    ),
    pytest.param(
        "head",
        WorkspaceOpError("workspace.capability_unavailable", "old", permanent=True),
        None,
        "failed",
    ),
    pytest.param(
        "head",
        {"head": HEAD, "branch": "main", "merge_in_progress": False},
        None,
        "worktree_missing",
        id="head-on-another-branch",
    ),
    pytest.param(
        "head",
        {"head": HEAD, "branch": None, "merge_in_progress": False},
        None,
        "worktree_missing",
        id="head-detached",
    ),
    pytest.param(
        "head",
        {"head": "nope", "branch": BRANCH, "merge_in_progress": False},
        None,
        "failed",
        id="malformed-head",
    ),
    # Before diff_stat nothing was compared.
    pytest.param("head", WorkspaceOpError("workspace.git_failed", "bad HEAD"), None, "failed"),
    pytest.param("head", ValueError("refused params"), None, "failed"),
    pytest.param(
        "diff_stat", WorkspaceOpError("workspace.git_failed", PATH_ERROR), HEAD, "compare_failed"
    ),
    pytest.param("diff_stat", ValueError("refused params"), HEAD, "compare_failed"),
    pytest.param("diff_stat", RuntimeError("boom"), HEAD, "failed"),
    pytest.param(
        "diff_stat",
        {"files_changed": 5, "insertions": 1, "deletions": 1, "paths": ["a"]},
        HEAD,
        "failed",
        id="malformed-diff-stat",
    ),
]


@pytest.mark.parametrize(("where", "failure", "head", "code"), FAILURES)
async def test_each_host_failure_answers_its_code(
    where: str, failure: Any, head: str | None, code: str
) -> None:
    host, channels = _host()
    if where == "channel":
        channels.refusal = failure
    else:
        host.replies[where] = failure

    read = await _read(OutcomeDiffs(), channels)

    assert read == DiffRead(head, None, code)


async def test_a_failed_read_logs_its_type_and_code_and_never_a_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _host_channel, channels = _host(
        {"diff_stat": WorkspaceOpError("workspace.git_failed", PATH_ERROR)}
    )
    _refusing_host, refusing = _host()
    refusing.refusal = HostAccessRefused("not_permitted", f"host {PATH_ERROR!r} is not yours")

    with caplog.at_level(logging.DEBUG):
        await _read(OutcomeDiffs(), channels)
        await _read(OutcomeDiffs(), refusing)

    logged = [record.getMessage() for record in caplog.records]
    assert logged == [
        f"Coral could not read run {RUN_ID}'s outcome: WorkspaceOpError workspace.git_failed",
        f"Coral could not read run {RUN_ID}'s outcome: HostAccessRefused not_permitted",
    ]
    assert all(record.exc_info is None for record in caplog.records)
    assert "/home/alice" not in caplog.text


async def test_a_diff_keeps_the_first_100_sorted_paths_each_shown_safely() -> None:
    paths = [f"src/{index:03d}.py" for index in range(150)]
    paths[3] = "src/003\u202e.py"
    _host_channel, channels = _host({"diff_stat": _stat(*reversed(paths))})
    _cut_host, cut_by_host = _host(
        {"diff_stat": {**_stat("a", "b", truncated=True), "files_changed": 9}}
    )

    read = await _read(OutcomeDiffs(), channels)
    host_cut = await _read(OutcomeDiffs(), cut_by_host)

    assert read.diff is not None and host_cut.diff is not None
    assert read.diff.paths == tuple(display_path(path) for path in sorted(paths)[:100])
    assert read.diff.paths[3] == "src/003\\u{202E}.py"
    assert (read.diff.files_changed, read.diff.paths_truncated) == (150, True)
    assert (host_cut.diff.paths, host_cut.diff.files_changed) == (("a", "b"), 9)
    assert host_cut.diff.paths_truncated


def test_the_outcome_module_never_runs_git_on_the_server() -> None:
    tree = ast.parse(Path(outcome_module.__file__).read_text())
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert not imported & {"subprocess", "os", "shutil", "pty"}
