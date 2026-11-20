"""``allowed_actions``: the run-row and engine rules, the list rule, and list within detail."""

from __future__ import annotations

import itertools
from typing import get_args

import pytest

from coral.engine import transition
from coral.engine.projection import RunView
from coral.engine.types import PauseCause, PauseReason, ResumeRun, RunStatus
from coral.runview.actions import LIST_RESUMABLE_REASONS, RunViewFacts, allowed_actions
from coral.runview.types import PauseReasonName, RunAction, RunStatusName
from tests.coral.bridge._scripted_runs import IMPLEMENT, fixture_graph, start_run
from tests.coral.engine.drive import NOW, drive

FINISHED: tuple[RunStatusName, ...] = ("completed", "failed", "cancelled")
UNFINISHED: tuple[RunStatusName, ...] = ("starting", "running", "paused")
ROW_REASONS: tuple[PauseReasonName | None, ...] = (*get_args(PauseReasonName), None)
# The only reasons a pause made on the run row alone writes: drift and an unloadable run.
ROW_ONLY_REASONS: tuple[PauseReasonName, ...] = ("drift", "failure_path")
LIVE: tuple[RunAction, ...] = ("pause", "cancel")
RESUMABLE: tuple[RunAction, ...] = ("resume", "cancel")
CANCEL: tuple[RunAction, ...] = ("cancel",)


def _cause(reason: PauseReason, detail: str = "hold", subject: str = "") -> PauseCause:
    return PauseCause(reason=reason, detail=detail, subject=subject)


# Every engine reason, and a step's failed turn with and without the slot it names.
ENGINE_CAUSES: tuple[PauseCause, ...] = (
    *(_cause(reason) for reason in get_args(PauseReason) if reason != "failure_path"),
    _cause("failure_path", "agent.failed", IMPLEMENT),
    _cause("failure_path", "agent.failed"),
    _cause("failure_path", "effect.permanent", IMPLEMENT),
)
CAUSE_SETS: tuple[tuple[PauseCause, ...], ...] = (
    *((cause,) for cause in ENGINE_CAUSES),
    *itertools.permutations(ENGINE_CAUSES, 2),
)
ENGINE_VIEWS: tuple[RunViewFacts, ...] = (
    RunViewFacts(status=None),
    RunViewFacts(status="running"),
    *(RunViewFacts(status="paused", causes=causes) for causes in CAUSE_SETS),
)


def _paused(*causes: PauseCause) -> RunViewFacts:
    return RunViewFacts(status="paused", causes=causes)


def _detail(
    status: RunStatusName, reason: PauseReasonName | None, view: RunViewFacts
) -> tuple[RunAction, ...]:
    return allowed_actions(row_status=status, row_pause_reason=reason, view=view, loadable=True)


def _listed(status: RunStatusName, reason: PauseReasonName | None) -> tuple[RunAction, ...]:
    return allowed_actions(row_status=status, row_pause_reason=reason, view=None, loadable=True)


@pytest.mark.parametrize("status", FINISHED)
@pytest.mark.parametrize("view", [None, RunViewFacts(status="running"), _paused(_cause("user"))])
@pytest.mark.parametrize("loadable", [True, False])
def test_a_finished_row_offers_nothing_whatever_the_engine_says(
    status: RunStatusName, view: RunViewFacts | None, loadable: bool
) -> None:
    assert (
        allowed_actions(row_status=status, row_pause_reason=None, view=view, loadable=loadable)
        == ()
    )


@pytest.mark.parametrize("status", UNFINISHED)
@pytest.mark.parametrize("reason", [None, "user", "failure_path"])
def test_an_unfinished_run_that_cannot_be_loaded_can_only_be_cancelled(
    status: RunStatusName, reason: PauseReasonName | None
) -> None:
    for view in (None, RunViewFacts(status="running"), _paused(_cause("user"))):
        assert (
            allowed_actions(row_status=status, row_pause_reason=reason, view=view, loadable=False)
            == CANCEL
        )


@pytest.mark.parametrize("status", ["starting", "running"])
@pytest.mark.parametrize("view", [None, *ENGINE_VIEWS[:3]])
def test_a_starting_or_running_row_can_be_paused_or_cancelled(
    status: RunStatusName, view: RunViewFacts | None
) -> None:
    assert (
        allowed_actions(row_status=status, row_pause_reason=None, view=view, loadable=True) == LIVE
    )


@pytest.mark.parametrize("engine_status", [None, "running"])
@pytest.mark.parametrize("reason", ROW_ONLY_REASONS)
def test_a_pause_on_the_row_alone_can_be_resumed(
    engine_status: RunStatus | None, reason: PauseReasonName
) -> None:
    assert _detail("paused", reason, RunViewFacts(status=engine_status)) == RESUMABLE


@pytest.mark.parametrize(
    "causes",
    [
        (_cause("user"),),
        (_cause("drift"),),
        (_cause("budget"), _cause("infra")),
        (_cause("failure_path", "agent.failed", IMPLEMENT),),
    ],
)
def test_an_engine_pause_with_a_cause_resume_clears_can_be_resumed(
    causes: tuple[PauseCause, ...],
) -> None:
    assert _detail("paused", causes[0].reason, _paused(*causes)) == RESUMABLE


@pytest.mark.parametrize(
    "causes",
    [
        (_cause("budget"),),
        (_cause("liveness"),),
        (_cause("engine_upgrade"),),
        (_cause("failure_path", "agent.failed"),),
        (_cause("failure_path", "effect.permanent", IMPLEMENT),),
        (_cause("budget"), _cause("liveness")),
    ],
)
def test_an_engine_pause_no_cause_of_which_resume_clears_can_only_be_cancelled(
    causes: tuple[PauseCause, ...],
) -> None:
    assert _detail("paused", causes[0].reason, _paused(*causes)) == CANCEL


def test_the_list_offers_resume_only_for_reasons_the_engine_clears_without_a_cap() -> None:
    assert {
        "user",
        "rejected_calls",
        "infra",
        "auth",
        "plan_limit",
        "authority_revoked",
    } == LIST_RESUMABLE_REASONS
    for reason in ROW_REASONS:
        expected = RESUMABLE if reason in LIST_RESUMABLE_REASONS else CANCEL
        assert _listed("paused", reason) == expected


def test_a_row_only_drift_pause_over_an_engine_paused_for_budget_lists_only_cancel() -> None:
    # Resume is refused for budget without a cap, so the list must not offer it for drift.
    over_budget = _paused(_cause("budget"))

    assert _detail("paused", "drift", over_budget) == CANCEL
    assert _listed("paused", "drift") == CANCEL


def _reachable(reason: PauseReasonName | None, view: RunViewFacts, *, row_only: bool) -> bool:
    """A paused row as the bridge writes it: on the row alone, or the engine's first cause."""
    if row_only:
        return reason in ROW_ONLY_REASONS
    return view.status == "paused" and bool(view.causes) and view.causes[0].reason == reason


def test_every_list_item_offers_a_subset_of_its_detail() -> None:
    """Over runs the bridge can load; an unloadable run agrees once its row shows it."""
    checked = 0
    for reason, view, row_only in itertools.product(ROW_REASONS, ENGINE_VIEWS, (True, False)):
        if not _reachable(reason, view, row_only=row_only):
            continue
        listed, detail = _listed("paused", reason), _detail("paused", reason, view)
        assert set(listed) <= set(detail), (reason, view, row_only)
        assert "pause" not in detail
        checked += 1
    for status in (*FINISHED, "starting", "running"):
        for view in ENGINE_VIEWS:
            assert set(_listed(status, None)) <= set(_detail(status, None, view))
    assert checked > len(CAUSE_SETS)


def test_a_run_the_bridge_paused_as_unloadable_lists_what_its_detail_offers() -> None:
    # The list cannot see loadability; it agrees through the row's ``failure_path`` pause.
    unloadable = allowed_actions(
        row_status="paused", row_pause_reason="failure_path", view=None, loadable=False
    )

    assert _listed("paused", "failure_path") == unloadable == CANCEL


@pytest.mark.parametrize("causes", CAUSE_SETS)
def test_resume_is_offered_exactly_when_the_engine_accepts_resume_without_a_cap(
    causes: tuple[PauseCause, ...],
) -> None:
    graph = fixture_graph("two_steps")
    started = drive(graph, [start_run(graph)]).state
    paused = started.model_copy(update={"status": "paused", "causes": causes})

    resumed = transition(graph, paused, ResumeRun(), NOW)

    offered = "resume" in _detail("paused", causes[0].reason, _paused(*causes))
    assert offered is (resumed.entry.rejection is None)


@pytest.mark.parametrize(
    "view",
    [
        RunView(),
        RunView(status="running"),
        RunView(status="paused", causes=(_cause("budget"), _cause("user"))),
    ],
)
def test_view_facts_read_the_same_from_a_view_or_its_json(view: RunView) -> None:
    facts = RunViewFacts.of(view)

    assert facts == RunViewFacts.of(view.model_dump(mode="json"))
    assert (facts.status, facts.causes) == (view.status, view.causes)
