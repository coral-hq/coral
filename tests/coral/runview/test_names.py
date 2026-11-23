"""The run-view name literals equal the stored codes' names and the engine's."""

from __future__ import annotations

from typing import get_args

from coral.alerts.types import AlertAction
from coral.bridge.service import LOAD_FAILED_DETAIL
from coral.db.enum_codecs import ACTOR_KIND, RUN_PAUSE_REASON, RUN_STATUS
from coral.engine.types import TERMINAL_STATUSES, PauseReason, RunStatus
from coral.runview.types import (
    FINISHED_RUN_STATUSES,
    ActorKindName,
    LoadError,
    PauseReasonName,
    RunAction,
    RunStatusName,
)


def _names(literal: object) -> list[str]:
    names = list(get_args(literal))
    assert len(names) == len(set(names))
    return sorted(names)


def test_run_status_and_pause_reason_names_are_the_stored_codes_names() -> None:
    assert _names(RunStatusName) == sorted(RUN_STATUS)
    assert _names(PauseReasonName) == sorted(RUN_PAUSE_REASON)


def test_actor_kind_names_are_the_stored_codes_names() -> None:
    assert _names(ActorKindName) == sorted(ACTOR_KIND)


def test_the_row_names_cover_every_engine_status_and_pause_reason() -> None:
    assert set(get_args(RunStatus)) <= set(get_args(RunStatusName))
    assert set(get_args(PauseReason)) <= set(get_args(PauseReasonName))
    assert FINISHED_RUN_STATUSES == TERMINAL_STATUSES


def test_the_load_error_is_the_bridge_s_load_failure_detail() -> None:
    assert get_args(LoadError) == (LOAD_FAILED_DETAIL,)


def test_run_actions_are_inbox_actions() -> None:
    assert set(get_args(RunAction)) == {"pause", "resume", "retry", "cancel"}
    # Pause and Retry are offered only in the run view.
    assert set(get_args(RunAction)) - {"pause", "retry"} <= set(get_args(AlertAction))
