"""A runner on a run's anchor is stopped as the run owner, unless another session uses it.

The session rows are real (a SQLite conversation store); the run store and the
dispatch are fakes, and the dispatch records each stop and the user it ran as.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from coral.db.enum_codecs import RunPauseReason, RunStatus
from coral.model.ids import anchor_session_id
from coral.omni.protocols import CoralSessionError
from coral.omni.server.anchor_runner import AnchorRunnerStopper
from coral.recovery.drift import DriftFinding, DriftPauser
from coral.stores.fakes import FakeRunStore
from coral.stores.protocols import CoralRun
from omnigent.db.db_models import workspace_scope
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore
from tests.coral.slots._close_fakes import FakeDispatch
from tests.coral.workspace._executor_fakes import start_run

WORKSPACE = 3
OWNER = "alice"
HOST = "a" * 32
LOGGER = "coral.omni.server.anchor_runner"


@dataclass
class _Run:
    """One run with its anchor bound, the stopper over it, and the stores it reads."""

    run: CoralRun
    anchor: str
    run_store: FakeRunStore
    conversations: SqlAlchemyConversationStore
    dispatch: FakeDispatch
    stopper: AnchorRunnerStopper

    def row(
        self, session_id: str | None = None, *, runner_id: str | None, host_id: str | None = None
    ) -> str:
        """A session row in the run's workspace, pinned to *runner_id*; a host needs a path."""
        with workspace_scope(WORKSPACE):
            return self.conversations.create_conversation(
                conversation_id=session_id,
                runner_id=runner_id,
                host_id=host_id,
                workspace=None if host_id is None else "/work/anchor",
            ).id


@pytest.fixture
def coral(db_uri: str) -> _Run:
    run_store = FakeRunStore(default_workspace_id=WORKSPACE)
    run = start_run(
        run_store,
        workspace_id=WORKSPACE,
        user_id=OWNER,
        account_generation="gen-1",
        host_id=None,
        repo_path=None,
        worktree_path=None,
        run_branch=None,
    )
    anchor = anchor_session_id(WORKSPACE, run.id)
    dispatch = FakeDispatch([], owner=OWNER)
    dispatch.session(anchor)
    conversations = SqlAlchemyConversationStore(db_uri)
    stopper = AnchorRunnerStopper(
        conversation_store=conversations, run_store=run_store, dispatch=lambda: dispatch
    )
    return _Run(run, anchor, run_store, conversations, dispatch, stopper)


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == LOGGER]


async def test_stop_uses_the_run_owner(coral: _Run) -> None:
    coral.row(coral.anchor, runner_id="runner-anchor")
    # A step on its own runner is not affected by the anchor's.
    coral.row(runner_id="runner-step")

    await coral.stopper(WORKSPACE, coral.run.id, coral.anchor)
    # Each detection stops again: the stop is safe to repeat.
    await coral.stopper(WORKSPACE, coral.run.id, coral.anchor)

    assert coral.dispatch.stops == [(coral.anchor, OWNER)] * 2


async def test_stop_skips_a_runner_a_step_shares(
    coral: _Run, caplog: pytest.LogCaptureFixture
) -> None:
    coral.row(coral.anchor, runner_id="runner-shared")
    coral.row(runner_id="runner-other")
    sharing = coral.row(runner_id="runner-shared")

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await coral.stopper(WORKSPACE, coral.run.id, coral.anchor)

    assert coral.dispatch.events == []
    [warning] = _records(caplog)
    assert warning.levelno == logging.WARNING
    assert "runner-shared" in warning.getMessage() and sharing in warning.getMessage()


async def test_nothing_is_stopped_without_a_runner_or_a_run(
    coral: _Run, caplog: pytest.LogCaptureFixture
) -> None:
    # The anchor row is gone (a deleted anchor is its own drift cause).
    await coral.stopper(WORKSPACE, coral.run.id, coral.anchor)
    # Bound to a host only: there is no runner to stop.
    coral.row(coral.anchor, runner_id=None, host_id=HOST)
    await coral.stopper(WORKSPACE, coral.run.id, coral.anchor)
    assert coral.dispatch.events == []

    # With a runner but no run row, nobody to stop it as.
    with workspace_scope(WORKSPACE):
        assert coral.conversations.set_runner_id(coral.anchor, "runner-anchor")
    orphan = AnchorRunnerStopper(
        conversation_store=coral.conversations,
        run_store=FakeRunStore(default_workspace_id=WORKSPACE),
        dispatch=lambda: coral.dispatch,
    )
    with caplog.at_level(logging.INFO, logger=LOGGER):
        await orphan(WORKSPACE, coral.run.id, coral.anchor)

    assert coral.dispatch.events == []
    [warning] = _records(caplog)
    assert warning.levelno == logging.WARNING and coral.run.id in warning.getMessage()


async def test_a_failed_stop_is_logged_and_the_drift_pause_stands(
    coral: _Run, caplog: pytest.LogCaptureFixture
) -> None:
    coral.row(coral.anchor, runner_id="runner-anchor")
    refusal = CoralSessionError("dispatch.stop_unconfirmed", "no answer", retryable=True)
    coral.dispatch.refusals["stop"] = refusal
    pauser = DriftPauser(coral.run_store, on_anchor_bound=coral.stopper)

    with caplog.at_level(logging.WARNING, logger="coral.recovery.drift"):
        outcome = await pauser.pause(
            workspace_id=WORKSPACE,
            run_id=coral.run.id,
            finding=DriftFinding("anchor_bound", coral.anchor, "runner-anchor"),
        )

    assert outcome.applied
    assert coral.dispatch.events == ["stop"]
    state, _ = coral.run_store.load_run_state(coral.run.id, workspace_id=WORKSPACE)
    assert (state.run.status, state.run.pause_reason) == (RunStatus.PAUSED, RunPauseReason.DRIFT)
    [logged] = [record for record in caplog.records if record.name == "coral.recovery.drift"]
    assert logged.exc_info is not None and logged.exc_info[1] is refusal


async def test_stop_skips_a_runner_any_other_session_uses(
    coral: _Run, caplog: pytest.LogCaptureFixture
) -> None:
    coral.row(coral.anchor, runner_id="runner-anchor")
    # Not a step of this run: another run's step, a chat, or a child made before the guard.
    elsewhere = coral.row(runner_id="runner-anchor")
    # A session on another runner does not count.
    coral.row(runner_id="runner-other")

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await coral.stopper(WORKSPACE, coral.run.id, coral.anchor)

    assert coral.dispatch.events == []
    [warning] = _records(caplog)
    assert warning.levelno == logging.WARNING
    assert "runner-anchor" in warning.getMessage() and elsewhere in warning.getMessage()
