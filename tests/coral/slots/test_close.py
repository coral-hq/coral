"""The closed-first bounded close and the cancel, over protocol fakes and the K13 fake backend.

The fake dispatch refuses a user message once the session is closed, as the
server does, and answers the queued-input check with the production rule. The
fake edge watcher hands each wait the edges a test delivered; a wait that finds
none returns at once as if its bound passed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, override

import pytest

from coral.db.enum_codecs import SlotRole
from coral.omni.protocols import CoralSessionError, LiveStatus, engine_message_text
from coral.omni.server.status_edges import CoralStatusEdges
from coral.queue.executors import EffectCompleted
from coral.queue.run_effects import EffectRefused
from coral.slots.close import (
    DEFAULT_BOUNDS,
    INTERRUPT_SETTLE_S,
    TURN_END_S,
    AcceptedEdits,
    CloseBlocked,
    CloseBounds,
    CloseOutcome,
    CloseRestarted,
    CommitSpec,
    ConfirmedStops,
    StopConfirmedTurnEnd,
    cancel_session,
    close_session,
    turn_state,
)
from coral.slots.executors import CLOSE_SLOT, close_slot_executor
from coral.stores.fakes import FakeRunStore
from coral.stores.stable_ids import content_checksum
from coral.workspace.fake import FakeWorkspaceOps
from coral.workspace.ops import (
    CommitResult,
    DiffStat,
    Fingerprint,
    FingerprintLevel,
    OpExecutor,
    WorkspaceOpError,
    WorkspaceRef,
)
from omnigent.server.session_live_state import SessionStatusEdge
from tests.coral.slots._close_fakes import (
    OWNER,
    FakeDispatch,
    FakeEdgeWatcher,
    FakeItem,
    FakeStableIds,
    observed,
)
from tests.coral.workspace._executor_fakes import (
    FakeBindings,
    FakeChannels,
    FakeHostChannel,
    FakeIntents,
    RecordingScopeRunner,
    add_slot,
    effect_context,
    start_run,
    step_binding,
)

WORKSPACE = 4
SESSION = "5e55a7e0c0de4d1e8a0b1c2d3e4f5a02"
RUN_ID = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"
BRIEF = "b" * 32
BRIEF_TEXT = engine_message_text("Review the parser.")
ENGINE_MESSAGES = {BRIEF: content_checksum(BRIEF_TEXT)}
REF = WorkspaceRef(
    host_id="h" * 32,
    root="/Users/alice/repo-worktrees/coral-r-0a1b2c3d4e5f-base",
    branch="coral/r-0a1b2c3d4e5f/base",
)
OP_KEY = "c" * 32
BOUNDS = CloseBounds(turn_end_s=120.0, interrupt_settle_s=30.0)
# The order a writer's close takes when its turn has already ended.
CLOSE_ORDER = [
    "watch",
    "live_status",
    "unwatch",
    "fingerprint",
    "lease",
    "set_closed",
    "lease",
    "stop",
    "fingerprint",
    # The commit gate: the session has not run again since the stop.
    "live_status",
    "head",
    "lease",
    "reserve",
    "lease",
    "commit",
    "diff_stat",
    "queued_user_input",
]


class SimulatedCrash(BaseException):
    """The worker died mid-close; nothing in the close catches it."""


class RecordingWorkspace(FakeWorkspaceOps):
    """The K13 fake backend recording each op in ``events``, with hooks and faults per op."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        # Run once, right after the op of that name returns.
        self.after_once: dict[str, Callable[[], None]] = {}
        # Raised once, before (``"<op>"``) or after (``"<op>:after"``) the op runs.
        self.faults: dict[str, BaseException] = {}

    def _before(self, op: str) -> None:
        self.events.append(op)
        fault = self.faults.pop(op, None)
        if fault is not None:
            raise fault

    def _after(self, op: str) -> None:
        hook = self.after_once.pop(op, None)
        if hook is not None:
            hook()
        fault = self.faults.pop(f"{op}:after", None)
        if fault is not None:
            raise fault

    @override
    async def fingerprint(
        self, ref: WorkspaceRef, executor: OpExecutor, *, level: FingerprintLevel
    ) -> Fingerprint:
        self._before("fingerprint")
        result = await super().fingerprint(ref, executor, level=level)
        self._after("fingerprint")
        return result

    @override
    async def head(self, ref: WorkspaceRef, executor: OpExecutor) -> Any:
        self._before("head")
        return await super().head(ref, executor)

    @override
    async def commit(self, ref: WorkspaceRef, executor: OpExecutor, **params: Any) -> CommitResult:
        self._before("commit")
        result = await super().commit(ref, executor, **params)
        self._after("commit")
        return result

    @override
    async def diff_stat(self, ref: WorkspaceRef, executor: OpExecutor, **params: Any) -> DiffStat:
        self._before("diff_stat")
        result = await super().diff_stat(ref, executor, **params)
        self._after("diff_stat")
        return result


class _Close:
    """A step session whose turn ran on the brief, its worktree and the close's collaborators."""

    def __init__(self, *, status: str | None = "idle", **session: Any) -> None:
        self.events: list[str] = []
        self.dispatch = FakeDispatch(self.events)
        self.session = self.dispatch.session(SESSION, status=status, **session)
        self.session.transcript.append(FakeItem(BRIEF, OWNER, BRIEF_TEXT))
        self.edges = FakeEdgeWatcher(self.events)
        self.workspace = RecordingWorkspace(self.events)
        self.start = self.workspace.add_workspace(REF, {"README.md": b"start\n"})
        self.intents = FakeIntents(self.events)
        self.stops = ConfirmedStops()
        self.accepted_edits = AcceptedEdits()

    def restart_worker(self) -> None:
        """A new server process: the in-memory stop and post-accept records are gone."""
        self.stops = ConfirmedStops()
        self.accepted_edits = AcceptedEdits()

    async def lease(self) -> None:
        self.events.append("lease")

    def spec(self) -> CommitSpec:
        return CommitSpec(
            workspace=self.workspace,
            ref=REF,
            intents=self.intents,
            workspace_id=WORKSPACE,
            run_id=RUN_ID,
            op_key=OP_KEY,
            message="Review: done",
            attempt_id="attempt-1",
        )

    async def close(self, *, writer: bool = True, **changes: Any) -> CloseOutcome:
        params: dict[str, Any] = {
            "workspace_id": WORKSPACE,
            "session_id": SESSION,
            "user_id": OWNER,
            "slot_id": "review/item-0/m0",
            "interrupt": True,
            "closed_label": True,
            "commit": self.spec() if writer else None,
            "engine_messages": ENGINE_MESSAGES,
            "dispatch": self.dispatch,
            "edges": self.edges,
            "ensure_lease": self.lease,
            "bounds": BOUNDS,
            "stops": self.stops,
            "accepted_edits": self.accepted_edits,
            **changes,
        }
        return await close_session(**params)

    def committed(self, commit: str | None, path: str) -> bytes | None:
        """``path`` as ``commit`` recorded it, or ``None``."""
        assert commit is not None
        return self.workspace._commit(commit).files.get(path)

    def main_events(self) -> list[str]:
        wanted = {"interrupt", "set_closed", "stop", "commit", "queued_user_input"}
        return [event for event in self.events if event in wanted]


def _live(**changes: Any) -> LiveStatus:
    fields: dict[str, Any] = {
        "status": "idle",
        "response_id": None,
        "blocked_on": None,
        "pending_elicitations": 0,
        "background_work": False,
        "response_observed": True,
        **changes,
    }
    return LiveStatus(**fields)


@pytest.mark.parametrize(
    ("live", "expected"),
    [
        (_live(), "ended"),
        (_live(status="failed"), "ended"),
        (_live(status=None), "ended"),
        (_live(status="waiting", background_work=True), "ended"),
        (_live(status="running", response_id="r1"), "running"),
        (_live(status="running", blocked_on="permission prompt"), "prompt_open"),
        (_live(status="running", pending_elicitations=1), "prompt_open"),
        (_live(status="idle", pending_elicitations=2), "prompt_open"),
        # Parked on a prompt means a running turn; a stale reason on an ended one is not.
        (_live(status="idle", blocked_on="stale"), "ended"),
    ],
)
def test_turn_state(live: LiveStatus, expected: str) -> None:
    assert turn_state(live) == expected


async def test_an_ended_turn_closes_in_order_without_waiting_or_interrupting() -> None:
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")

    outcome = await env.close()

    assert env.events == CLOSE_ORDER
    assert outcome.commit is not None and outcome.commit != env.start
    assert env.committed(outcome.commit, "work.txt") == b"accepted\n"
    assert outcome == CloseOutcome(
        pending_input=False,
        queued_input=False,
        post_accept_edits=False,
        commit=outcome.commit,
        empty=False,
        diff_stat=DiffStat(files_changed=1, insertions=1, deletions=0, paths=("work.txt",)),
        forced_stop=False,
    )
    assert env.edges.watching == [(SESSION, WORKSPACE, "review/item-0/m0")]
    assert not env.session.runner_alive


async def test_a_turn_that_ends_within_the_bound_needs_no_interrupt() -> None:
    env = _Close(status="running", response_id="resp_1")
    env.edges.arrive_during_next_wait(
        observed(SESSION, "idle", outcome="completed", turn_response_id="resp_1")
    )

    outcome = await env.close()

    assert "interrupt" not in env.events
    assert env.edges.timeouts == []
    assert outcome.forced_stop is False
    assert env.main_events() == ["set_closed", "stop", "commit", "queued_user_input"]


async def test_a_turn_still_running_at_the_bound_is_interrupted_and_settles() -> None:
    env = _Close(status="running", response_id="resp_1")

    def settle(session_id: str) -> None:
        env.session.status = "idle"
        env.edges.arrive_during_next_wait(
            observed(session_id, "idle", outcome="cancelled", turn_response_id="resp_1")
        )

    env.dispatch.settle_on_interrupt = settle

    outcome = await env.close()

    assert env.dispatch.interrupts == ["resp_1"]
    assert env.edges.timeouts == [BOUNDS.turn_end_s]
    assert outcome.forced_stop is False
    assert env.main_events() == ["interrupt", "set_closed", "stop", "commit", "queued_user_input"]


async def test_an_interrupt_that_does_not_settle_still_stops_before_the_commit() -> None:
    env = _Close(status="running", response_id="resp_1")

    outcome = await env.close()

    assert env.edges.timeouts == [BOUNDS.turn_end_s, BOUNDS.interrupt_settle_s]
    assert outcome.forced_stop is True
    assert env.main_events() == ["interrupt", "set_closed", "stop", "commit", "queued_user_input"]


async def test_without_interrupt_a_turn_past_the_bound_is_ended_by_the_stop() -> None:
    env = _Close(status="running", response_id="resp_1")

    outcome = await env.close(interrupt=False)

    assert outcome.forced_stop is True
    assert env.main_events() == ["set_closed", "stop", "commit", "queued_user_input"]


@pytest.mark.parametrize(
    "prompt",
    [
        {"pending_elicitations": 1},
        {"blocked_on": "permission prompt"},
    ],
    ids=["headless_approval", "terminal_prompt"],
)
async def test_open_approval_blocks_the_close_without_interrupting(prompt: dict[str, Any]) -> None:
    env = _Close(status="running", response_id="resp_1", **prompt)

    with pytest.raises(CloseBlocked) as blocked:
        await env.close()

    assert (blocked.value.code, blocked.value.retryable) == ("slot.close_blocked", True)
    # Refused at once: the close neither waits on the prompt nor interrupts it.
    assert "wait_for" not in env.events and env.edges.timeouts == []
    assert env.main_events() == []
    assert "fingerprint" not in env.events
    assert env.session.runner_alive and not env.session.closed


async def test_a_prompt_opened_while_waiting_blocks_the_close_without_interrupting() -> None:
    env = _Close(status="running", response_id="resp_1")
    env.edges.arrive_during_next_wait(observed(SESSION, "running", response_id="resp_1"))
    env.dispatch.hooks["live_status"] = lambda: setattr(env.session, "pending_elicitations", 1)

    with pytest.raises(CloseBlocked):
        await env.close()

    assert env.main_events() == []


async def test_a_prompt_opened_after_an_unsettled_interrupt_blocks_the_close() -> None:
    env = _Close(status="running", response_id="resp_1")
    # The interrupt did not reach the turn, which then asked for an approval.
    env.dispatch.settle_on_interrupt = lambda _session_id: setattr(
        env.session, "pending_elicitations", 1
    )

    with pytest.raises(CloseBlocked):
        await env.close()

    assert env.dispatch.interrupts == ["resp_1"]
    assert env.main_events() == ["interrupt"]
    assert "fingerprint" not in env.events


async def test_an_unknown_response_ends_the_wait_at_the_first_terminal_edge() -> None:
    # A cold cache and a store that names no response yet.
    env = _Close(status="running", response_id=None)
    env.edges.arrive_during_next_wait(
        observed(SESSION, "idle", outcome="completed", turn_response_id="resp_9")
    )

    outcome = await env.close()

    assert env.edges.timeouts == []
    assert "interrupt" not in env.events
    assert outcome.forced_stop is False


async def test_a_known_response_waits_out_another_responses_outcome() -> None:
    # This replica saw the turn start: an outcome for another response ends nothing.
    env = _Close(status="running", response_id="resp_1", response_observed=True)
    env.edges.arrive_during_next_wait(
        observed(SESSION, "idle", outcome="completed", turn_response_id="resp_9")
    )

    await env.close(interrupt=False)

    assert env.edges.timeouts == [BOUNDS.turn_end_s]


async def test_a_guessed_response_ends_the_wait_at_the_turns_own_end_edge() -> None:
    # A server restarted mid-turn stores the rest of it under ids of its own and guesses
    # the newest; the turn's real end names the response the old server saw start.
    env = _Close(status="running", response_id="turn_guessed", response_observed=False)
    env.edges.arrive_during_next_wait(
        observed(SESSION, "idle", outcome="completed", turn_response_id="resp_real")
    )

    outcome = await env.close()

    assert env.edges.timeouts == []
    assert "interrupt" not in env.events
    assert outcome.forced_stop is False


async def test_a_guessed_response_is_not_used_to_pick_the_turn_to_interrupt() -> None:
    env = _Close(status="running", response_id="turn_guessed", response_observed=False)

    def settle(session_id: str) -> None:
        env.session.status = "idle"
        env.edges.arrive_during_next_wait(
            observed(session_id, "idle", outcome="cancelled", turn_response_id="resp_real")
        )

    env.dispatch.settle_on_interrupt = settle

    outcome = await env.close()

    assert env.dispatch.interrupts == [None]
    assert env.edges.timeouts == [BOUNDS.turn_end_s]
    assert outcome.forced_stop is False


@pytest.mark.parametrize(
    ("published", "response_observed", "forced_stop"),
    [
        ("before_the_watch", False, True),
        ("once_watching", False, False),
        ("once_watching", True, True),
    ],
    ids=["guessed_before_the_watch", "guessed_once_watching", "known_once_watching"],
)
async def test_an_earlier_turns_late_end_edge_ends_only_a_guessed_wait_that_saw_it(
    published: str, response_observed: bool, forced_stop: bool
) -> None:
    # The real watcher: its stream starts when the close begins watching, before the read.
    edges = CoralStatusEdges(asyncio.get_running_loop())
    env = _Close(
        status="running",
        response_id="turn_guessed" if not response_observed else "resp_1",
        response_observed=response_observed,
    )
    # An earlier turn's runner report, published late by the relay.
    earlier = SessionStatusEdge(
        SESSION,
        "idle",
        "running",
        turn_outcome="completed",
        turn_response_id="resp_earlier",
        workspace_id=WORKSPACE,
    )
    reads: list[str] = []

    def once_watching() -> None:
        reads.append("live_status")
        if len(reads) == 1:
            edges.observe(earlier)

    if published == "before_the_watch":
        edges.observe(earlier)
    else:
        env.dispatch.hooks["live_status"] = once_watching
    bounds = CloseBounds(turn_end_s=0.2, interrupt_settle_s=0.05)

    outcome = await env.close(edges=edges, bounds=bounds, interrupt=False)

    # A guess takes any end edge it sees (R89); a known response keeps CRL-128's rule.
    assert outcome.forced_stop is forced_stop
    assert "interrupt" not in env.events
    assert env.main_events() == ["set_closed", "stop", "commit", "queued_user_input"]


@pytest.mark.parametrize("interrupt", [True, False])
async def test_a_guessed_response_with_no_end_edge_waits_out_its_bounds_as_a_known_one_does(
    interrupt: bool,
) -> None:
    closes: dict[bool, tuple[_Close, CloseOutcome]] = {}
    for response_observed in (True, False):
        env = _Close(
            status="running",
            response_id="resp_1" if response_observed else "turn_guessed",
            response_observed=response_observed,
        )
        # No turn end: a running edge for another response, then one naming none.
        env.edges.arrive_during_next_wait(observed(SESSION, "running", response_id="turn_other"))
        env.edges.arrive_during_next_wait(observed(SESSION, "running"))
        outcome = await env.close(interrupt=interrupt, bounds=DEFAULT_BOUNDS)
        closes[response_observed] = (env, outcome)
    (known, known_outcome), (guessed, guessed_outcome) = closes[True], closes[False]

    expected_timeouts = [TURN_END_S, INTERRUPT_SETTLE_S] if interrupt else [TURN_END_S]
    assert guessed.edges.timeouts == known.edges.timeouts == expected_timeouts
    assert guessed_outcome.forced_stop is known_outcome.forced_stop is True
    assert guessed.main_events() == known.main_events()
    # Only the interrupt differs: it never names the guess.
    assert (known.dispatch.interrupts, guessed.dispatch.interrupts) == (
        (["resp_1"], [None]) if interrupt else ([], [])
    )


async def test_a_known_responses_settle_wait_ignores_another_responses_outcome() -> None:
    env = _Close(status="running", response_id="resp_1")
    env.dispatch.settle_on_interrupt = lambda session_id: env.edges.arrive_during_next_wait(
        observed(session_id, "idle", outcome="completed", turn_response_id="resp_9")
    )

    outcome = await env.close()

    assert env.dispatch.interrupts == ["resp_1"]
    assert env.edges.timeouts == [BOUNDS.turn_end_s, BOUNDS.interrupt_settle_s]
    assert outcome.forced_stop is True


@pytest.mark.parametrize("operation", ["close", "cancel"])
async def test_a_guessed_turn_is_interrupted_unnamed_though_the_stores_guess_moves(
    operation: str,
) -> None:
    # After a restart each stored item has its own made-up id, so each read guesses anew.
    env = _Close(status="running", response_id="turn_a", response_observed=False)
    guesses = iter(["turn_b", "turn_c", "turn_d"])
    env.dispatch.hooks["live_status"] = lambda: setattr(env.session, "response_id", next(guesses))

    def settle(session_id: str) -> None:
        env.session.status = "idle"
        env.edges.arrive_during_next_wait(
            observed(session_id, "idle", outcome="cancelled", turn_response_id="resp_real")
        )

    env.dispatch.settle_on_interrupt = settle

    if operation == "close":
        await env.close()
    else:
        await _cancel(env)

    assert env.dispatch.interrupts == [None]
    # The settle wait ended at the turn's own end edge, which names another response.
    assert env.edges.timeouts == ([BOUNDS.turn_end_s] if operation == "close" else [])
    assert not env.session.runner_alive and env.session.closed


async def test_the_settle_wait_follows_the_response_the_second_read_found() -> None:
    env = _Close(status="running", response_id="resp_1")

    def continuation_started() -> None:
        # Right after the first read a continuation, resp_2, starts; resp_1's end is missed.
        env.session.response_id = "resp_2"

    def settle(session_id: str) -> None:
        env.session.status = "idle"
        env.edges.arrive_during_next_wait(
            observed(session_id, "idle", outcome="cancelled", turn_response_id="resp_2")
        )

    env.dispatch.hooks["live_status"] = continuation_started
    env.dispatch.settle_on_interrupt = settle

    outcome = await env.close()

    assert env.dispatch.interrupts == ["resp_2"]
    assert env.edges.timeouts == [BOUNDS.turn_end_s]
    assert outcome.forced_stop is False


async def test_waiting_session_closes_without_interrupt() -> None:
    env = _Close(status="waiting", background_work=True)
    env.workspace.write_file(REF, "work.txt", b"accepted\n")

    outcome = await env.close()

    assert "wait_for" not in env.events and "interrupt" not in env.events
    assert env.main_events() == ["set_closed", "stop", "commit", "queued_user_input"]
    # The stop ends the background work the turn left behind.
    assert not env.session.background_work
    assert outcome.forced_stop is False and outcome.empty is False


async def test_input_typed_during_the_accepting_turn_sets_pending_input() -> None:
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")
    # Typed while the agent worked on the brief, so persisted after it.
    env.dispatch.post_user_message(SESSION, "user-1", author=OWNER)

    outcome = await env.close()

    assert (outcome.queued_input, outcome.post_accept_edits, outcome.pending_input) == (
        True,
        False,
        True,
    )
    # The accepted work is still committed; the run pauses for the user's review.
    assert env.committed(outcome.commit, "work.txt") == b"accepted\n"


async def test_message_between_turn_end_and_commit_is_not_committed_and_sets_pending_input() -> (
    None
):
    """
    A message accepted after the turn end is queued input, so the user reviews the close.

    The message is never part of the commit, which records files only. Its turn
    here wrote nothing before the stop ended it; when it does, the commit holds
    those edits and flags them (the next test).
    """
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")
    # A message lands after the turn end, before the session is closed.
    env.workspace.after_once["fingerprint"] = lambda: env.dispatch.post_user_message(
        SESSION, "user-late", author=OWNER
    )

    outcome = await env.close()

    assert [message.item_id for message in env.session.transcript] == [BRIEF, "user-late"]
    assert (outcome.queued_input, outcome.pending_input) == (True, True)
    assert outcome.post_accept_edits is False
    assert env.committed(outcome.commit, "work.txt") == b"accepted\n"
    assert outcome.diff_stat is not None and outcome.diff_stat.paths == ("work.txt",)


async def test_a_late_messages_edits_before_the_stop_are_flagged_for_review() -> None:
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")

    def late_turn() -> None:
        # The late message starts a turn that writes before the stop ends it.
        env.dispatch.post_user_message(SESSION, "user-late", author=OWNER)
        env.workspace.write_file(REF, "late.txt", b"from the late turn\n")

    env.workspace.after_once["fingerprint"] = late_turn

    outcome = await env.close()

    # The commit is the tree the stop left, the late edits included, and they are
    # flagged: the user reviews them before the run goes on.
    assert (outcome.queued_input, outcome.post_accept_edits, outcome.pending_input) == (
        True,
        True,
        True,
    )
    assert env.committed(outcome.commit, "late.txt") == b"from the late turn\n"
    assert env.main_events() == ["set_closed", "stop", "commit", "queued_user_input"]


async def test_a_message_after_the_session_is_closed_is_refused() -> None:
    env = _Close()
    refused: list[CoralSessionError] = []

    def post() -> None:
        try:
            env.dispatch.post_user_message(SESSION, "user-after-close", author=OWNER)
        except CoralSessionError as exc:
            refused.append(exc)

    env.dispatch.hooks["set_closed"] = post

    outcome = await env.close()

    assert [exc.code for exc in refused] == ["dispatch.session_closed"]
    assert (outcome.queued_input, outcome.pending_input) == (False, False)


async def test_edits_after_the_turn_end_set_post_accept_edits_and_pending_input() -> None:
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")
    # A background shell writes after the turn end, before the stop ends it.
    env.workspace.after_once["fingerprint"] = lambda: env.workspace.write_file(
        REF, "late.txt", b"after the turn end\n"
    )

    outcome = await env.close()

    assert (outcome.post_accept_edits, outcome.queued_input, outcome.pending_input) == (
        True,
        False,
        True,
    )


async def test_reviewer_close_makes_no_commit() -> None:
    events: list[str] = []
    run_store = FakeRunStore(default_workspace_id=WORKSPACE)
    run = start_run(
        run_store,
        workspace_id=WORKSPACE,
        user_id=OWNER,
        account_generation="gen-1",
        host_id=REF.host_id,
        repo_path="/Users/alice/repo",
        worktree_path=REF.root,
    )
    add_slot(run_store, run, session_id=SESSION)
    dispatch = FakeDispatch(events)
    dispatch.session(SESSION, status="idle").transcript.append(FakeItem(BRIEF, OWNER, BRIEF_TEXT))
    channel = FakeHostChannel(events, {})
    scope = RecordingScopeRunner()
    stable_ids = FakeStableIds(events)
    stable_ids.record_send(
        WORKSPACE,
        stable_id=BRIEF,
        run_id=run.id,
        session_id=SESSION,
        effect_key=f"{run.id}:3:send_input:slot-1",
        kind="brief",
        generation=1,
        content=BRIEF_TEXT,
    )
    executor = close_slot_executor(
        dispatch,
        FakeEdgeWatcher(events),
        FakeChannels(channel, scope),
        FakeIntents(events),
        stable_ids,
        FakeBindings(
            [
                step_binding(
                    workspace_id=WORKSPACE,
                    run_id=run.id,
                    session_id=SESSION,
                    slot_role=SlotRole.VERIFIER,
                    host_id=REF.host_id,
                )
            ]
        ),
        run_store,
        scope,
    )
    ctx = effect_context(
        workspace_id=WORKSPACE,
        run_id=run.id,
        payload={
            "effect_type": CLOSE_SLOT,
            "effect_key": f"{run.id}:9:close_slot:slot-1",
            "session_id": SESSION,
            "message": "Review: done",
        },
    )

    outcome = await executor(ctx)

    assert isinstance(outcome, EffectCompleted), outcome
    assert outcome.result == {
        "pending_input": False,
        "queued_input": False,
        "post_accept_edits": False,
        "commit": None,
        "empty": None,
        "diff_stat": None,
    }
    assert channel.requests == []
    assert [event for event in events if event in ("set_closed", "stop")] == ["set_closed", "stop"]


async def test_a_close_without_a_commit_spec_touches_no_worktree() -> None:
    env = _Close()

    outcome = await env.close(writer=False)

    assert (outcome.commit, outcome.empty, outcome.diff_stat) == (None, None, None)
    assert not {"fingerprint", "head", "reserve", "commit", "diff_stat"} & set(env.events)
    assert env.main_events() == ["set_closed", "stop", "queued_user_input"]


async def test_an_unchanged_tree_records_an_empty_commit() -> None:
    env = _Close()

    outcome = await env.close()

    assert (outcome.commit, outcome.empty) == (env.start, True)
    assert outcome.diff_stat == DiffStat(files_changed=0, insertions=0, deletions=0, paths=())


async def test_a_diff_stat_failure_is_retryable_and_the_retry_returns_the_same_result() -> None:
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")
    env.workspace.faults["diff_stat"] = WorkspaceOpError(
        "workspace.backend_unavailable", "the tunnel dropped"
    )

    with pytest.raises(EffectRefused) as failed:
        await env.close()
    retried = await env.close()

    assert (failed.value.code, failed.value.retryable) == ("workspace.backend_unavailable", True)
    assert retried == await _reference_outcome()


@pytest.mark.parametrize(
    "crash_at",
    [
        "fingerprint",
        "set_closed",
        "stop",
        "stopped_fingerprint",
        "head",
        "commit",
        "commit:after",
        "diff_stat",
        "queued_user_input",
    ],
)
async def test_a_retry_after_a_crash_at_each_step_returns_the_same_result(crash_at: str) -> None:
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")
    if crash_at in ("set_closed", "queued_user_input"):
        env.dispatch.refusals[crash_at] = SimulatedCrash(crash_at)
    elif crash_at == "stop":
        # The runner stopped; the worker died before it heard so.
        env.dispatch.hooks[crash_at] = _raise(SimulatedCrash(crash_at))
    elif crash_at == "stopped_fingerprint":
        # The worker dies in the fingerprint after the confirmed stop.
        env.dispatch.hooks["stop"] = lambda: env.workspace.faults.__setitem__(
            "fingerprint", SimulatedCrash(crash_at)
        )
    else:
        env.workspace.faults[crash_at] = SimulatedCrash(crash_at)

    with pytest.raises(SimulatedCrash):
        await env.close()
    env.dispatch.hooks.clear()
    retried = await env.close()

    reference = await _reference_outcome()
    if crash_at == "stopped_fingerprint":
        # The first try stopped the session but never compared the trees: flag for review.
        reference = replace(reference, post_accept_edits=True, pending_input=True)
    assert retried == reference
    # The start commit and the one close commit.
    assert len(env.workspace._commits) == 2


@pytest.mark.parametrize(
    ("late_edit", "restart", "flagged"),
    [
        (True, False, True),
        (True, True, True),
        (False, False, False),
        (False, True, True),
    ],
    ids=["late-edit", "late-edit-after-restart", "no-late-edit", "no-late-edit-after-restart"],
)
async def test_a_retry_after_the_commit_landed_never_loses_post_accept_edits(
    late_edit: bool, restart: bool, flagged: bool
) -> None:
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")
    if late_edit:
        # A background shell writes after the turn end, before the stop ends it.
        env.workspace.after_once["fingerprint"] = lambda: env.workspace.write_file(
            REF, "late.txt", b"after the turn end\n"
        )
    env.workspace.faults["diff_stat"] = WorkspaceOpError(
        "workspace.backend_unavailable", "the tunnel dropped"
    )
    with pytest.raises(EffectRefused):
        await env.close()
    if restart:
        env.restart_worker()

    retried = await env.close()

    # Both of the retry's fingerprints show the committed tree; the first try's
    # answer is kept in process, and a lost one flags the tree for review.
    assert (retried.post_accept_edits, retried.pending_input) == (flagged, flagged)
    assert env.events.count("commit") == 2 and len(env.workspace._commits) == 2


async def test_an_unconfirmed_stop_is_retryable_and_nothing_is_committed() -> None:
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")
    env.dispatch.unconfirmed_stops = 1

    with pytest.raises(CoralSessionError) as unconfirmed:
        await env.close()

    assert (unconfirmed.value.code, unconfirmed.value.retryable) == (
        "dispatch.stop_unconfirmed",
        True,
    )
    assert "commit" not in env.events
    assert not env.stops.confirmed(WORKSPACE, SESSION)
    assert (await env.close()).commit is not None


async def test_the_close_records_its_own_confirmed_stop_and_the_label_proves_nothing() -> None:
    env = _Close()
    check = StopConfirmedTurnEnd(env.dispatch, env.stops)
    # A collaborator can set the closed label; without the engine's own stop it proves nothing.
    env.session.closed = True
    with pytest.raises(CoralSessionError) as unknown:
        await check(workspace_id=WORKSPACE, run_id=RUN_ID, session_id=SESSION)
    assert (unknown.value.code, unknown.value.retryable) == ("session.turn_state_unknown", True)

    await env.close(writer=False)

    assert env.stops.confirmed(WORKSPACE, SESSION)
    assert not env.stops.confirmed(WORKSPACE + 1, SESSION)
    assert await check(workspace_id=WORKSPACE, run_id=RUN_ID, session_id=SESSION) is True
    # Relaunched after the stop: background work, or a turn, may write again.
    for live in ("waiting", "running"):
        env.session.status = live
        assert await check(workspace_id=WORKSPACE, run_id=RUN_ID, session_id=SESSION) is False
    # Ended, but not idle: no confirmed stop speaks for a failed runner.
    env.session.status = "failed"
    with pytest.raises(CoralSessionError):
        await check(workspace_id=WORKSPACE, run_id=RUN_ID, session_id=SESSION)


def test_a_later_running_edge_clears_a_confirmed_stop() -> None:
    stops = ConfirmedStops()
    stops.record(WORKSPACE, SESSION)

    stops.observe(_status_edge("idle"))
    stops.observe(_status_edge("running", workspace_id=WORKSPACE + 1))
    still = stops.confirmed(WORKSPACE, SESSION)
    stops.observe(_status_edge("running"))

    assert still is True
    assert stops.confirmed(WORKSPACE, SESSION) is False


@pytest.mark.parametrize(
    "restart",
    ["running", "waiting", "prompt", "running_edge"],
)
async def test_a_session_that_ran_again_after_the_stop_is_not_committed(restart: str) -> None:
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")

    def relaunched() -> None:
        # A user's retry or a cleared label relaunched the runner after the stop.
        if restart == "prompt":
            env.session.pending_elicitations = 1
        elif restart == "running_edge":
            # The relaunched turn already ended, but the observer saw its running edge.
            env.workspace.after_once["fingerprint"] = lambda: env.stops.observe(
                _status_edge("running")
            )
        else:
            env.session.status = restart

    env.dispatch.hooks["stop"] = relaunched

    with pytest.raises(CloseRestarted) as restarted:
        await env.close()
    env.dispatch.hooks.clear()
    env.session.pending_elicitations = 0
    retried = await env.close()

    assert (restarted.value.code, restarted.value.retryable) == ("slot.close_restarted", True)
    assert env.events.count("commit") == 1
    # The retry stopped the session again before it committed; a relaunched turn
    # still running at the retry is ended by that stop.
    assert replace(retried, forced_stop=False) == await _reference_outcome()


async def test_a_writers_close_always_sets_the_closed_label() -> None:
    env = _Close()

    with pytest.raises(ValueError):
        await env.close(closed_label=False)
    reader = await env.close(writer=False, closed_label=False)

    assert env.main_events() == ["stop", "queued_user_input"]
    assert reader.commit is None


async def test_cancel_interrupts_the_running_turn_then_closes_and_stops() -> None:
    env = _Close(status="running", response_id="resp_1")
    env.dispatch.settle_on_interrupt = lambda session_id: env.edges.arrive_during_next_wait(
        observed(session_id, "idle", outcome="cancelled", turn_response_id="resp_1")
    )

    await cancel_session(
        workspace_id=WORKSPACE,
        session_id=SESSION,
        user_id=OWNER,
        slot_id="slot-1",
        closed_label=True,
        dispatch=env.dispatch,
        edges=env.edges,
        ensure_lease=env.lease,
        bounds=BOUNDS,
    )

    assert env.main_events() == ["interrupt", "set_closed", "stop"]
    assert env.edges.timeouts == []
    assert not env.session.runner_alive and env.session.closed


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        (
            {"status": "running", "response_id": "r1", "pending_elicitations": 1},
            ["set_closed", "stop"],
        ),
        ({"status": "idle"}, ["set_closed", "stop"]),
        ({"status": "running", "response_id": "r1"}, ["interrupt", "stop"]),
    ],
    ids=["open_prompt_not_waited_on", "idle", "no_closed_label"],
)
async def test_cancel_never_waits_on_a_prompt_and_always_stops(
    session: dict[str, Any], expected: list[str]
) -> None:
    env = _Close(**session)
    closed_label = expected[0] != "interrupt"

    await cancel_session(
        workspace_id=WORKSPACE,
        session_id=SESSION,
        user_id=OWNER,
        slot_id="slot-1",
        closed_label=closed_label,
        dispatch=env.dispatch,
        edges=env.edges,
        ensure_lease=env.lease,
        bounds=BOUNDS,
    )

    assert env.main_events() == expected


async def _cancel(env: _Close) -> None:
    await cancel_session(
        workspace_id=WORKSPACE,
        session_id=SESSION,
        user_id=OWNER,
        slot_id="slot-1",
        closed_label=True,
        dispatch=env.dispatch,
        edges=env.edges,
        ensure_lease=env.lease,
        bounds=BOUNDS,
    )


async def test_cancel_with_a_known_response_waits_out_another_responses_outcome() -> None:
    env = _Close(status="running", response_id="resp_1")
    env.dispatch.settle_on_interrupt = lambda session_id: env.edges.arrive_during_next_wait(
        observed(session_id, "idle", outcome="completed", turn_response_id="resp_9")
    )

    await _cancel(env)

    assert env.dispatch.interrupts == ["resp_1"]
    assert env.edges.timeouts == [BOUNDS.interrupt_settle_s]
    assert env.main_events() == ["interrupt", "set_closed", "stop"]


async def _reference_outcome() -> CloseOutcome:
    """The outcome of the same close with no fault."""
    env = _Close()
    env.workspace.write_file(REF, "work.txt", b"accepted\n")
    return replace(await env.close(), forced_stop=False)


@dataclass(frozen=True)
class _StatusEdge:
    """The fields of a published status edge that a confirmed stop reads."""

    workspace_id: int
    session_id: str
    status: str


def _status_edge(status: str, *, workspace_id: int = WORKSPACE) -> _StatusEdge:
    return _StatusEdge(workspace_id=workspace_id, session_id=SESSION, status=status)


def _raise(exc: BaseException) -> Callable[[], None]:
    def raising() -> None:
        raise exc

    return raising
